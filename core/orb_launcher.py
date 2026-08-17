import subprocess
import os
import sys
import threading
import socket
import webbrowser
import time
from pathlib import Path

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

class OrbLauncher:
    def __init__(self, port=3000):
        self.port = port
        self.process = None
        self.base_dir = _base_dir()
        self.orb_dir = self.base_dir / "orb"
        self._thread = None

    def start(self):
        """Start Next.js server in the background if it's not already running on port."""
        if self.is_port_active(self.port):
            print(f"Next.js app already running on port {self.port}.")
            self.open_browser()
            return
        
        self._thread = threading.Thread(target=self._run_next_dev, daemon=True)
        self._thread.start()
        
        # Give it a moment to boot, then open browser
        threading.Thread(target=self._delayed_browser_open, daemon=True).start()

    def _delayed_browser_open(self):
        # Poll the port until it is ready, up to 15 seconds
        for _ in range(30):
            if self.is_port_active(self.port):
                self.open_browser()
                return
            time.sleep(0.5)
        # Fallback open anyway
        self.open_browser()

    def _run_next_dev(self):
        # Serve the static production build files instead of running in dev mode
        try:
            cmd = f"npx serve -s out -l {self.port}"
            print(f"Launching Production static server via: {cmd} in {self.orb_dir}")
            
            # On Windows we hide the window
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW
                
            self.process = subprocess.Popen(
                cmd,
                shell=True,
                cwd=str(self.orb_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags
            )
            self.process.wait()
        except Exception as e:
            print(f"Error starting static server: {e}")

    def stop(self):
        if self.process:
            self.process.terminate()
            self.process = None

    def is_port_active(self, port) -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect(("127.0.0.1", port))
            s.close()
            return True
        except Exception:
            return False

    def open_browser(self):
        pass # webbrowser.open(f"http://localhost:{self.port}")
