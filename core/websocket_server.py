import asyncio
import json
import logging
import websockets
import threading

logger = logging.getLogger("MarkL.WebSocketServer")
logger.setLevel(logging.INFO)

class OrbWebSocketServer:
    def __init__(self, host="127.0.0.1", port=8765):
        self.host = host
        self.port = port
        self.clients = set()
        self.loop = None
        self.thread = None
        self.lock = threading.Lock()

    async def register(self, websocket):
        with self.lock:
            self.clients.add(websocket)
        logger.info(f"Orb connected: {websocket.remote_address}. Total clients: {len(self.clients)}")
        try:
            await websocket.send(json.dumps({"type": "status", "status": "connected"}))
            async for message in websocket:
                try:
                    data = json.loads(message)
                    if data.get("type") == "get_files":
                        import os
                        from pathlib import Path
                        # Default to Desktop directory
                        target_dir = Path.home() / "Desktop"
                        files_list = []
                        if target_dir.exists():
                            for entry in os.scandir(target_dir):
                                # Skip hidden files
                                if not entry.name.startswith("."):
                                    files_list.append({
                                        "name": entry.name,
                                        "path": entry.path,
                                        "is_dir": entry.is_dir()
                                    })
                        await websocket.send(json.dumps({
                            "type": "file_list",
                            "files": files_list
                        }))
                    elif data.get("type") == "delete_file":
                        file_path = data.get("path")
                        if file_path:
                            from send2trash import send2trash
                            import os
                            if os.path.exists(file_path):
                                send2trash(file_path)
                                # Send confirmation and refresh list
                                await websocket.send(json.dumps({"type": "delete_done", "path": file_path}))
                                # Automatically broadcast refreshed list
                                self.broadcast_files()
                except Exception as e:
                    logger.error(f"Error handling websocket client message: {e}")
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            with self.lock:
                self.clients.discard(websocket)
            logger.info(f"Orb disconnected. Total clients: {len(self.clients)}")

    def start(self):
        self.thread = threading.Thread(target=self._run_server, daemon=True)
        self.thread.start()

    def _run_server(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        async def main():
            async with websockets.serve(self.register, self.host, self.port):
                logger.info(f"WebSocket server started on ws://{self.host}:{self.port}")
                await asyncio.Future()  # run forever

        self.loop.run_until_complete(main())

    def broadcast(self, data):
        """Thread-safe broadcast method to send events to all connected clients."""
        if not self.loop or not self.clients:
            return
        
        msg = json.dumps(data)
        with self.lock:
            clients_copy = list(self.clients)
            
        for client in clients_copy:
            asyncio.run_coroutine_threadsafe(client.send(msg), self.loop)

    def send_audio_level(self, level: float):
        self.broadcast({"type": "audio_level", "level": level})

    def send_status(self, status: str):
        self.broadcast({"type": "status", "status": status})

    def send_text(self, text: str):
        self.broadcast({"type": "text", "text": text})

    def broadcast_files(self):
        import os
        from pathlib import Path
        target_dir = Path.home() / "Desktop"
        files_list = []
        if target_dir.exists():
            for entry in os.scandir(target_dir):
                if not entry.name.startswith("."):
                    files_list.append({
                        "name": entry.name,
                        "path": entry.path,
                        "is_dir": entry.is_dir()
                    })
        self.broadcast({
            "type": "file_list",
            "files": files_list
        })
