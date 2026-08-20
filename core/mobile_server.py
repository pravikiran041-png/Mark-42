import asyncio
import json
import logging
import websockets
import threading
import uuid
import socket
import base64
import os
import psutil


try:
    from ghost_mode import GhostEngine
    _GHOST_OK = True
except ImportError:
    _GHOST_OK = False

logger = logging.getLogger("MarkL.MobileServer")
logger.setLevel(logging.INFO)

_instance = None
def get_instance():
    return _instance

class MobileWebSocketServer:
    def __init__(self, port=8766):
        global _instance
        _instance = self
        self.port = port
        self.host = "0.0.0.0" # Listen on all interfaces so the phone can connect over LAN
        self.clients = set()
        self.loop = None
        self.thread = None
        self.lock = threading.Lock()
        
        # Persist pairing token so it survives restarts and prevents "invalid token"
        token_file = os.path.join(os.path.dirname(__file__), ".pairing_token")
        if os.path.exists(token_file):
            with open(token_file, "r") as f:
                self.pairing_token = f.read().strip()
        else:
            self.pairing_token = str(uuid.uuid4())
            with open(token_file, "w") as f:
                f.write(self.pairing_token)
                
        self.paired_devices = set()
        self.ui = None # Reference to the JARVIS UI if we need to update it
        self._ghost = None # Reference to the active Ghost Engine instance

        # Phase 5: Native screen streaming
        self.latest_frame = None       # Most recent JPEG bytes from the phone
        self.frame_lock = threading.Lock()
        self._frame_callback = None    # Optional callback for live viewer window
        
        # Laptop Screen Streaming (Ported from Dashboard)
        self._screen_clients = set()
        self._screen_task = None

    def get_local_ip(self):
        import psutil
        fallback_ip = None
        try:
            for interface, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET:
                        ip = addr.address
                        if ip == '127.0.0.1':
                            continue
                        # Prefer standard home networking IPs
                        if ip.startswith('192.168.') or ip.startswith('172.'):
                            return ip
                        # Also accept 10.x.x.x but watch out for tailscale (100.x.x.x)
                        if ip.startswith('10.') and not ip.startswith('100.'):
                            fallback_ip = ip
        except Exception:
            pass
            
        if fallback_ip:
            return fallback_ip

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('10.255.255.255', 1))
            IP = s.getsockname()[0]
        except Exception:
            IP = '127.0.0.1'
        finally:
            s.close()
        return IP
        
    def generate_qr_data(self):
        ip = self.get_local_ip()
        return f"jarvis://pair?ip={ip}&port={self.port}&token={self.pairing_token}"

    async def register(self, websocket, path=None):
        with self.lock:
            self.clients.add(websocket)
        print(f"[MobileServer] Phone connected: {websocket.remote_address}. Total: {len(self.clients)}", flush=True)
        logger.info(f"Mobile Companion connected: {websocket.remote_address}. Total clients: {len(self.clients)}")
        try:
            await websocket.send(json.dumps({"type": "status", "status": "connected"}))
            async for message in websocket:
                if isinstance(message, bytes):
                    # Check if it's a JPEG frame (starts with 0xFF 0xD8)
                    if len(message) > 2 and message[0] == 0xFF and message[1] == 0xD8:
                        # It's a JPEG screen frame from native MediaProjection
                        with self.frame_lock:
                            self.latest_frame = message
                        if self._frame_callback:
                            try:
                                self._frame_callback(message)
                            except Exception:
                                pass
                    else:
                        # It's raw PCM audio coming from the phone
                        try:
                            self.audio_queue.put_nowait(message)
                        except asyncio.QueueFull:
                            pass
                    continue
                    
                try:
                    data = json.loads(message)
                    msg_type = data.get("type")
                    if msg_type == "pair":
                        token = data.get("token")
                        device_id = data.get("device_id")
                        if token == self.pairing_token:
                            self.paired_devices.add(device_id)
                            await websocket.send(json.dumps({"type": "pair_success", "device_id": device_id}))
                            if self.ui and hasattr(self.ui, 'notify_phone_connected'):
                                self.ui.notify_phone_connected()
                            logger.info(f"Phone paired successfully. Screen streaming will begin automatically.")
                        else:
                            await websocket.send(json.dumps({"type": "pair_failed"}))
                            await websocket.close()
                            return
                    elif msg_type == "command":
                        cmd_text = data.get("text", "")
                        logger.info(f"Received text command from phone: {cmd_text}")
                        if self.ui and hasattr(self.ui, 'on_text_command'):
                            self.ui.on_text_command(cmd_text)
                    elif msg_type == "file_upload":
                        filename = data.get("filename")
                        b64_data = data.get("data")
                        logger.info(f"Received file upload from phone: {filename}")
                        try:
                            file_bytes = base64.b64decode(b64_data)
                            os.makedirs("uploads", exist_ok=True)
                            filepath = os.path.join("uploads", filename)
                            with open(filepath, "wb") as f:
                                f.write(file_bytes)
                            if self.ui and hasattr(self.ui, 'on_text_command'):
                                self.ui.on_text_command(f"I just uploaded a file named {filename}. Analyze it.")
                        except Exception as e:
                            logger.error(f"Failed to process file upload: {e}")
                    elif msg_type == "ghost_start":
                        logger.info("Ghost start command received from mobile app.")
                        if _GHOST_OK:
                            if not self._ghost:
                                self.chatgpt_future = None
                                async def _on_ghost_update(event):
                                    await websocket.send(json.dumps({"type": "ghost_log", "msg": event.get("msg")}))
                                    
                                async def _ask_phone_chatgpt(prompt):
                                    self.chatgpt_future = asyncio.get_running_loop().create_future()
                                    try:
                                        await websocket.send(json.dumps({
                                            "type": "control",
                                            "action": "ask_chatgpt",
                                            "prompt": prompt
                                        }))
                                        return await asyncio.wait_for(self.chatgpt_future, timeout=90.0)
                                    except asyncio.TimeoutError:
                                        return "Error: ChatGPT took too long (90s timeout)."
                                    except Exception as e:
                                        return f"Error: {e}"
                                
                                from pathlib import Path
                                try:
                                    cfg_path = Path(__file__).resolve().parent.parent / "config" / "api_keys.json"
                                    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                                    api_key = cfg.get("gemini_api_key", "")
                                except:
                                    api_key = ""
                                    
                                self._ghost = GhostEngine(
                                    api_key=api_key,
                                    on_update=_on_ghost_update,
                                    scan_interval=2.0,
                                    solver_mode=data.get("solver_mode", "phone_chatgpt"),
                                    phone_ip=data.get("phone_ip", "usb"),
                                    phone_pin=data.get("phone_pin", "2580"),
                                    inject_mode=data.get("inject_mode", "type"),
                                    phone_chatgpt_callback=_ask_phone_chatgpt
                                )
                                await self._ghost.start()
                                self._ghost._is_paused = False  # Start unpaused when triggered from phone
                                print("[MobileServer] Ghost Mode started and UNPAUSED (scanning immediately)", flush=True)
                                await websocket.send(json.dumps({"type": "ghost_status", "status": "running"}))
                        else:
                            await websocket.send(json.dumps({"type": "ghost_status", "status": "error", "message": "Ghost Mode not installed."}))
                    elif msg_type == "ghost_stop":
                        if self._ghost:
                            await self._ghost.stop()
                            self._ghost = None
                        await websocket.send(json.dumps({"type": "ghost_status", "status": "stopped"}))
                    elif msg_type == "ghost_toggle_pause":
                        if self._ghost:
                            self._ghost._is_paused = not self._ghost._is_paused
                            state = "paused" if self._ghost._is_paused else "scanning"
                            print(f"[MobileServer] Ghost Mode toggled: {state}", flush=True)
                            await websocket.send(json.dumps({"type": "ghost_pause_status", "paused": self._ghost._is_paused}))
                    elif msg_type == "ghost_update_config":
                        if self._ghost:
                            if "inject_mode" in data:
                                self._ghost.inject_mode = data["inject_mode"]
                            if "solver_mode" in data:
                                self._ghost.solver_mode = data["solver_mode"]
                            print(f"[MobileServer] Live config updated: {data}", flush=True)
                    elif msg_type == "start_screen":
                        self._screen_clients.add(websocket)
                        if self._screen_task is None:
                            self._screen_task = asyncio.create_task(self._screen_stream_loop())
                    elif msg_type == "stop_screen":
                        self._screen_clients.discard(websocket)
                    elif msg_type == "paste_text":
                        try:
                            import pyautogui
                            text = data.get("text", "")
                            if text:
                                # Use pynput for lightning-fast keystroke injection
                                from pynput.keyboard import Controller
                                keyboard = Controller()
                                keyboard.type(text)
                        except Exception as e:
                            logger.error(f"Paste error: {e}")
                    elif msg_type == "chatgpt_response":
                        if hasattr(self, 'chatgpt_future') and self.chatgpt_future and not self.chatgpt_future.done():
                            if "error" in data:
                                self.chatgpt_future.set_exception(Exception(data["error"]))
                            else:
                                self.chatgpt_future.set_result(data.get("response", ""))
                    elif msg_type == "text_type":
                        try:
                            import pyautogui
                            text = data.get("text", "")
                            if text: pyautogui.write(text, _pause=False)
                        except Exception as e:
                            logger.error(f"Type error: {e}")
                    elif msg_type == "read_screen":
                        asyncio.create_task(self._handle_read_screen(websocket))

                except Exception as e:
                    print(f"[MobileServer] Error handling message: {e}", flush=True)
                    logger.error(f"Error handling mobile client message: {e}")
        except websockets.exceptions.ConnectionClosed as cc:
            print(f"[MobileServer] Phone DISCONNECTED: {cc}", flush=True)
        except Exception as ex:
            print(f"[MobileServer] Unexpected error: {ex}", flush=True)
        finally:
            self._screen_clients.discard(websocket)
            with self.lock:
                self.clients.discard(websocket)
            print(f"[MobileServer] Phone removed. Remaining: {len(self.clients)}", flush=True)
            logger.info(f"Mobile Companion disconnected.")

    def start(self, ui=None):
        self.ui = ui
        if self.ui and hasattr(self.ui, 'update_screen_frame'):
            self._frame_callback = self.ui.update_screen_frame
        self.thread = threading.Thread(target=self._run_server, daemon=True)
        self.thread.start()

    def _run_server(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        async def telemetry_loop():
            while True:
                try:
                    cpu = psutil.cpu_percent()
                    ram = psutil.virtual_memory().percent
                    if self.clients:
                        msg = json.dumps({"type": "stats", "cpu": cpu, "ram": ram})
                        for c in list(self.clients):
                            await c.send(msg)
                except Exception as e:
                    pass
                await asyncio.sleep(2.0)

        async def main():
            self.audio_queue = asyncio.Queue(maxsize=100)
            server_task = websockets.serve(
                self.register, self.host, self.port,
                ping_interval=None,
                ping_timeout=None,
                max_size=10 * 1024 * 1024,
                close_timeout=10
            )
            telemetry_task = asyncio.create_task(telemetry_loop())
            
            print(f"[MobileServer] WebSocket server started on ws://{self.host}:{self.port}", flush=True)
            logger.info(f"Mobile WebSocket server started on ws://{self.host}:{self.port}")
            await asyncio.gather(server_task, telemetry_task)

        self.loop.run_until_complete(main())

    def broadcast(self, data):
        if not self.loop or not self.clients:
            return
        
        msg = json.dumps(data)
        with self.lock:
            clients_copy = list(self.clients)
            
        for client in clients_copy:
            asyncio.run_coroutine_threadsafe(client.send(msg), self.loop)

    def send_control(self, action: str, **kwargs):
        """Send a control command (tap/swipe) to the phone over WebSocket."""
        payload = {"type": "control", "action": action}
        payload.update(kwargs)
        self.broadcast(payload)

    def get_latest_frame(self) -> bytes:
        """Return the most recent JPEG screen frame from the phone."""
        with self.frame_lock:
            return self.latest_frame

    async def _screen_stream_loop(self):
        try:
            import mss
            import base64
            import PIL.Image
            import io
            with mss.mss() as sct:
                monitor = sct.monitors[1]  # primary monitor
                while self._screen_clients:
                    sct_img = sct.grab(monitor)
                    img = PIL.Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                    
                    max_dim = 1280
                    if img.width > max_dim:
                        img.thumbnail((max_dim, max_dim), PIL.Image.BILINEAR)
                        
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=65)
                    b64 = base64.b64encode(buf.getvalue()).decode()
                    
                    dead = set()
                    for ws in self._screen_clients:
                        try:
                            await ws.send(json.dumps({"type": "screen_frame", "data": b64}))
                        except Exception:
                            dead.add(ws)
                    self._screen_clients -= dead
                    
                    await asyncio.sleep(0.1) # 10 fps
        except Exception as e:
            logger.error(f"Screen stream loop error: {e}")
        finally:
            self._screen_task = None

    async def _handle_read_screen(self, ws):
        try:
            from ghost_mode import GhostEngine
            # Use a temporary GhostEngine to utilize its _read_screen() logic
            engine = GhostEngine(api_key="")
            text = await engine._read_screen()
            
            if text:
                # Store the last extracted text to prevent spamming ChatGPT with the same question
                last_text = getattr(self, '_last_extracted_text', None)
                if last_text == text:
                    await ws.send(json.dumps({"type": "extracted_text", "text": "Same text detected. Did not resend to ChatGPT."}))
                    return
                    
                self._last_extracted_text = text
                
                # 1. Update the app UI with the extracted text
                await ws.send(json.dumps({"type": "extracted_text", "text": text}))
                
                # 2. Send it to the phone's ChatGPT
                await ws.send(json.dumps({
                    "type": "control",
                    "action": "ask_chatgpt",
                    "prompt": text
                }))
            else:
                await ws.send(json.dumps({"type": "extracted_text", "text": "No text found on screen."}))
                
        except Exception as e:
            logger.error(f"Read screen error: {e}")
            try:
                await ws.send(json.dumps({"type": "extracted_text", "text": f"Error: {e}"}))
            except Exception:
                pass
