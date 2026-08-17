import asyncio
import json
import logging
import websockets
import threading
import uuid
import socket

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
        import os
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

        # Phase 5: Native screen streaming
        self.latest_frame = None       # Most recent JPEG bytes from the phone
        self.frame_lock = threading.Lock()
        self._frame_callback = None    # Optional callback for live viewer window

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
                            # Notify UI if it exists
                            if self.ui and hasattr(self.ui, 'notify_phone_connected'):
                                self.ui.notify_phone_connected()
                            logger.info(f"Phone paired successfully. Screen streaming will begin automatically.")
                                
                        else:
                            await websocket.send(json.dumps({"type": "pair_failed"}))
                            await websocket.close()
                            return
                except Exception as e:
                    logger.error(f"Error handling mobile client message: {e}")
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            with self.lock:
                self.clients.discard(websocket)
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
        
        async def main():
            self.audio_queue = asyncio.Queue(maxsize=100)
            async with websockets.serve(self.register, self.host, self.port):
                logger.info(f"Mobile WebSocket server started on ws://{self.host}:{self.port}")
                await asyncio.Future()  # run forever

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
