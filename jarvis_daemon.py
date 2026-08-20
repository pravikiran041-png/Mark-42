import os
import sys
import time
import signal

# Make sure we can import from the project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.mobile_server import MobileWebSocketServer
from dotenv import load_dotenv

load_dotenv()

def handle_sigterm(signum, frame):
    print("Daemon shutting down...")
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_sigterm)
signal.signal(signal.SIGINT, handle_sigterm)

if __name__ == "__main__":
    print("Starting JARVIS Background Daemon...")
    server = MobileWebSocketServer(port=8766)
    server.start(ui=None) # Start in daemon mode (no UI attached)
    
    # Start Ngrok Tunnel if configured
    try:
        import json
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "api_keys.json"), "r") as f:
            cfg = json.load(f)
        ngrok_token = cfg.get("ngrok_authtoken")
        if ngrok_token:
            from pyngrok import ngrok, conf
            print("[Ngrok] Starting Internet Tunnel (HTTPS)...")
            ngrok.set_auth_token(ngrok_token)
            tunnel = ngrok.connect(8766, "http", bind_tls=True)
            url = tunnel.public_url.replace("https://", "").replace("http://", "")
            
            # Write to file so main.py can read it for the QR code
            ngrok_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "core", ".ngrok_url")
            with open(ngrok_file, "w") as f:
                f.write(url)
            print(f"[Ngrok] Tunnel online at: {url}")
    except Exception as e:
        print(f"[Ngrok] Failed to start tunnel: {e}")
        
    # Keep the main thread alive so the daemon doesn't exit
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Daemon stopped by user.")
