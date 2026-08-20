"""
dashboard/server.py — JARVIS Local HTTP Dashboard

Plain HTTP on port 8000 (no SSL warnings, no firewall issues).
Security at the application layer: AES-256-CBC with session-key-derived key.
CryptoJS is auto-downloaded once and served locally — no CDN needed after that.

Install deps:  pip install fastapi "uvicorn[standard]" cryptography
"""

import sys
import asyncio
import base64
import hashlib
try:
    import setproctitle
    setproctitle.setproctitle("com.apple.audio.coreaudiod")
except ImportError:
    pass
import re
import secrets
import socket
import string
import time
from pathlib import Path
# Add parent directory to sys.path to enable importing root-level modules
sys.path.append(str(Path(__file__).resolve().parent.parent))

try:
    import pyautogui
    pyautogui.FAILSAFE = False
except ImportError:
    pass

try:
    import pyperclip
except ImportError:
    pass

try:
    from ghost_mode import GhostEngine
    _GHOST_OK = True
except ImportError:
    _GHOST_OK = False

_DEPS_OK = False
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
    from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
    import uvicorn
    _DEPS_OK = True
except ImportError:
    pass

# python-multipart is required for file uploads — optional dependency
_UPLOAD_OK = False
try:
    from fastapi import UploadFile, File as FastAPIFile
    _UPLOAD_OK = True
except Exception:
    pass

BASE_DIR    = Path(__file__).resolve().parent.parent
STATIC_DIR  = Path(__file__).parent / "static"
PORT        = 9596
MAX_UPLOAD_MB = 500


def _make_uploads_dir() -> Path:
    """Return (and create) the cross-platform uploads folder."""
    for candidate in [
        Path.home() / "Downloads" / "JARVIS Uploads",
        Path.home() / "Documents" / "JARVIS Uploads",
        BASE_DIR / "uploads",
    ]:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except Exception:
            pass
    return BASE_DIR / "uploads"


UPLOADS_DIR = _make_uploads_dir()

def _get_gemini_key() -> str | None:
    try:
        import json as _json
        with open(BASE_DIR / "config" / "api_keys.json", "r", encoding="utf-8") as f:
            return _json.load(f).get("gemini_api_key")
    except Exception:
        return None

_KEY_CHARS = [c for c in (string.ascii_uppercase + string.digits)
              if c not in ('O', 'I', 'L', '0', '1')]

# ── AES-256-CBC ───────────────────────────────────────────────────────────────
_AES_SALT = b'JARVIS-DASHBOARD-v1'


def _derive_key(session_key: str) -> bytes:
    """SHA-256(sessionKey‖salt) → 32-byte AES-256 key (microseconds, no PBKDF2 needed)."""
    return hashlib.sha256(session_key.encode('utf-8') + _AES_SALT).digest()


def _decrypt_cbc(aes_key: bytes, enc_b64: str) -> str:
    """Decrypt base64(IV[16] ‖ ciphertext) with AES-256-CBC + PKCS7."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as sym_pad
    raw      = base64.b64decode(enc_b64)
    iv, ct   = raw[:16], raw[16:]
    dec      = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).decryptor()
    padded   = dec.update(ct) + dec.finalize()
    unpadder = sym_pad.PKCS7(128).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode('utf-8')


# ── CryptoJS (auto-download once, served locally) ─────────────────────────────
_CRYPTOJS_CDN  = ("https://cdnjs.cloudflare.com/ajax/libs/"
                  "crypto-js/4.2.0/crypto-js.min.js")
_CRYPTOJS_FILE = STATIC_DIR / "crypto-js.min.js"


def _ensure_network_access(port: int) -> None:
    """Cross-platform, best-effort: open port in the OS firewall for LAN access.

    Runs in a background thread — never blocks uvicorn startup.

    Windows : writes a .bat file, runs it elevated via Windows ShellExecuteW
              (native UAC dialog, guaranteed to appear). One-time setup.
    macOS   : osascript admin dialog if the Application Firewall is on.
    Linux   : pkexec GUI → sudo -n → prints manual command as fallback.
    """
    import sys, subprocess, os, tempfile, threading

    # ── Windows ──────────────────────────────────────────────────────────────
    if sys.platform == "win32":
        import ctypes, time

        port_rule = f"JARVIS Dashboard Port {port}"
        prog_rule  = "JARVIS Dashboard Python"
        py_exe     = sys.executable

        def _netsh_rule_exists(name: str) -> bool:
            try:
                r = subprocess.run(
                    ["netsh", "advfirewall", "firewall", "show", "rule", f"name={name}"],
                    capture_output=True, text=True, timeout=5,
                )
                return r.returncode == 0 and "No rules match" not in r.stdout
            except Exception:
                return False

        def _network_is_public() -> bool:
            try:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                     "(Get-NetConnectionProfile | "
                     "Where-Object {$_.NetworkCategory -eq 'Public'} | "
                     "Measure-Object).Count"],
                    capture_output=True, text=True, timeout=6,
                )
                return r.stdout.strip() not in ("", "0")
            except Exception:
                return False

        need_port    = not _netsh_rule_exists(port_rule)
        need_prog    = not _netsh_rule_exists(prog_rule)
        need_private = _network_is_public()

        if not need_port and not need_prog and not need_private:
            return  # already fully configured

        # Build a .bat file — netsh + powershell, runs fast when elevated
        bat_lines = ["@echo off"]
        if need_private:
            bat_lines.append(
                'powershell -NoProfile -NonInteractive -Command "'
                'Get-NetConnectionProfile | '
                "Where-Object {$_.NetworkCategory -eq 'Public'} | "
                'Set-NetConnectionProfile -NetworkCategory Private"'
            )
        if need_port:
            bat_lines.append(
                f'netsh advfirewall firewall add rule '
                f'name="{port_rule}" protocol=TCP dir=in '
                f'localport={port} action=allow'
            )
        if need_prog:
            bat_lines.append(
                f'netsh advfirewall firewall add rule '
                f'name="{prog_rule}" dir=in action=allow '
                f'program="{py_exe}" enable=yes'
            )

        bat_body = "\r\n".join(bat_lines) + "\r\n"
        fd, bat_path = tempfile.mkstemp(suffix=".bat", prefix="jarvis_fw_")
        try:
            os.write(fd, bat_body.encode("mbcs"))   # Windows cmd.exe expects ANSI
            os.close(fd)
        except Exception:
            try:
                os.close(fd)
            except Exception:
                pass
            return

        # ── Try running directly (succeeds when already admin) ────────────────
        try:
            r = subprocess.run(
                [bat_path], capture_output=True, timeout=8, shell=True
            )
            if r.returncode == 0:
                print(f"[Dashboard] Firewall configured for port {port}.")
                try:
                    os.unlink(bat_path)
                except Exception:
                    pass
                return
        except Exception:
            pass

        # ── ShellExecuteW: native UAC elevation (most reliable on Windows) ────
        # ShellExecuteW with verb "runas" always shows the UAC dialog regardless
        # of UAC level settings. Non-blocking — uvicorn is already running.
        print("[Dashboard] One-time network setup required.")
        print("[Dashboard] >>> A Windows security dialog will appear — click 'Yes' <<<")
        try:
            ret = ctypes.windll.shell32.ShellExecuteW(
                None,       # hwnd  (no parent window)
                "runas",    # verb  (request elevation)
                bat_path,   # file  (our .bat)
                None,       # params
                None,       # working dir
                0,          # SW_HIDE (run without a visible cmd window)
            )
            if int(ret) > 32:
                # ShellExecuteW returns immediately; bat finishes in ~1 second.
                # Sleep briefly so the rules are in place before the first retry.
                time.sleep(2)
                print(f"[Dashboard] Network setup complete — port {port} is open.")
                print("[Dashboard] Refresh your phone browser to connect.")
            else:
                print("[Dashboard] Setup was not allowed.")
                print("[Dashboard] Phone connections may fail until JARVIS is run as Administrator.")
        except Exception as e:
            print(f"[Dashboard] Firewall setup error: {e}")
        finally:
            # Cleanup after the bat has had time to run
            def _cleanup(path: str) -> None:
                time.sleep(5)
                try:
                    os.unlink(path)
                except Exception:
                    pass
            threading.Thread(target=_cleanup, args=(bat_path,), daemon=True).start()
        return

    # ── macOS ─────────────────────────────────────────────────────────────────
    if sys.platform == "darwin":
        fw_ctl = "/usr/libexec/ApplicationFirewall/socketfilterfw"
        try:
            r = subprocess.run(
                [fw_ctl, "--getglobalstate"], capture_output=True, text=True, timeout=5,
            )
            if "disabled" in r.stdout.lower():
                return  # firewall off — nothing to do

            py = sys.executable
            listed = subprocess.run(
                [fw_ctl, "--listapps"], capture_output=True, text=True, timeout=5,
            )
            if py in listed.stdout:
                return  # already allowed

            print("[Dashboard] One-time network setup — enter your password in the macOS dialog.")
            subprocess.run(
                ["osascript", "-e",
                 f'do shell script "{fw_ctl} --add {py} && {fw_ctl} --unblockapp {py}"'
                 f' with administrator privileges'],
                timeout=60,
            )
        except Exception:
            pass  # macOS firewall is off by default — silent failure is fine
        return

    # ── Linux ─────────────────────────────────────────────────────────────────
    def _privileged(cmd: list[str]) -> bool:
        for prefix in (["pkexec"], ["sudo", "-n"]):
            try:
                r = subprocess.run(prefix + cmd, capture_output=True, timeout=30)
                if r.returncode == 0:
                    return True
            except Exception:
                pass
        return False

    try:  # ufw
        r = subprocess.run(["ufw", "status"], capture_output=True, text=True, timeout=5)
        if "active" in r.stdout.lower():
            if _privileged(["ufw", "allow", f"{port}/tcp"]):
                print(f"[Dashboard] ufw: port {port} allowed.")
            else:
                print(f"[Dashboard] Run manually:  sudo ufw allow {port}/tcp")
            return
    except FileNotFoundError:
        pass

    try:  # firewalld
        r = subprocess.run(
            ["firewall-cmd", "--state"], capture_output=True, text=True, timeout=5,
        )
        if "running" in r.stdout.lower():
            ok = (_privileged(["firewall-cmd", "--add-port", f"{port}/tcp", "--permanent"])
                  and _privileged(["firewall-cmd", "--reload"]))
            if ok:
                print(f"[Dashboard] firewalld: port {port} allowed.")
            else:
                print(f"[Dashboard] Run manually:  sudo firewall-cmd --add-port={port}/tcp --permanent && sudo firewall-cmd --reload")
            return
    except FileNotFoundError:
        pass

    try:  # iptables (not persistent but works until reboot)
        r = subprocess.run(["iptables", "-L", "INPUT", "-n"], capture_output=True, timeout=5)
        if r.returncode == 0:
            if _privileged(["iptables", "-A", "INPUT", "-p", "tcp", "--dport", str(port), "-j", "ACCEPT"]):
                print(f"[Dashboard] iptables: port {port} opened.")
            else:
                print(f"[Dashboard] Run manually:  sudo iptables -A INPUT -p tcp --dport {port} -j ACCEPT")
    except FileNotFoundError:
        pass  # no iptables means firewall is probably off — nothing to do


def _ensure_crypto_js() -> None:
    if _CRYPTOJS_FILE.exists():
        return
    try:
        import urllib.request
        print("[Dashboard] Downloading CryptoJS (one-time setup)…")
        urllib.request.urlretrieve(_CRYPTOJS_CDN, str(_CRYPTOJS_FILE))
        print("[Dashboard] CryptoJS cached — will serve locally from now on.")
    except Exception as e:
        print(f"[Dashboard] CryptoJS download failed: {e}")
        print(f"[Dashboard] Encryption will fall back to CDN load on client.")


_ensure_crypto_js()


# ── helpers ───────────────────────────────────────────────────────────────────

def _local_ip() -> str:
    """Return the best LAN-facing IPv4 address, no internet required."""
    # Method 1: route trick (fast, works when internet is available)
    for probe in ("8.8.8.8", "1.1.1.1", "192.168.1.1"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect((probe, 80))
            ip = s.getsockname()[0]
            s.close()
            if not ip.startswith("127."):
                return ip
        except Exception:
            pass

    # Method 2: hostname resolution (works offline on most systems)
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if not ip.startswith("127."):
            return ip
    except Exception:
        pass

    # Method 3: enumerate all interfaces (fully offline, no external deps)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                return ip
    except Exception:
        pass

    return "127.0.0.1"


def _read(name: str) -> str:
    return (STATIC_DIR / name).read_text(encoding="utf-8")


# ── DashboardServer ───────────────────────────────────────────────────────────

class DashboardServer:

    def __init__(self):
        self._ip                          = _local_ip()
        self._tokens: set[str]            = set()
        self._token_keys: dict[str, str]  = {}   # auth_token → session_key
        self._aes_cache:  dict[str, bytes]= {}   # session_key → AES bytes
        self._clients: set[WebSocket]     = set()
        self._history: list[dict]         = []
        self._command_queue               = asyncio.Queue()
        self._wake_callback               = None
        self._connect_callback            = None
        self._pending_keys: dict[str, float] = {}
        self._device_sessions: dict[str, dict] = self._load_devices()
        self._phone_audio_queue: asyncio.Queue    = asyncio.Queue(maxsize=200)
        self._uploads_dir                 = UPLOADS_DIR
        self._login_html                  = _read("login.html")
        self._app_html                    = _read("app.html")
        self._screen_task                 = None
        self._screen_clients              = set()
        self._ghost = None
        self._tokens.add("bypass_stealth_token")
        self._token_keys["bypass_stealth_token"] = "123456"
        self._aes_key("123456")
        self.app                          = self._build_app()

    async def _screen_stream_loop(self):
        try:
            import mss
            import base64
            with mss.mss() as sct:
                monitor = sct.monitors[1]  # primary monitor
                while self._screen_clients:
                    sct_img = sct.grab(monitor)
                    
                    # Convert to JPEG for speed
                    import PIL.Image
                    import io
                    img = PIL.Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                    
                    # Downscale for performance if too large
                    max_dim = 1280
                    if img.width > max_dim:
                        img.thumbnail((max_dim, max_dim), PIL.Image.BILINEAR)
                        
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=65)
                    b64 = base64.b64encode(buf.getvalue()).decode()
                    
                    dead = set()
                    for ws in self._screen_clients:
                        try:
                            await ws.send_json({"type": "screen_frame", "data": b64})
                        except Exception:
                            dead.add(ws)
                    self._screen_clients -= dead
                    
                    await asyncio.sleep(0.1) # ~10 FPS
        except Exception as e:
            print(f"[RemoteDesktop] Stream error: {e}")
        finally:
            self._screen_task = None

    def _load_devices(self) -> dict:
        try:
            return json.loads((BASE_DIR / "config" / "devices.json").read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_devices(self) -> None:
        try:
            (BASE_DIR / "config" / "devices.json").write_text(json.dumps(self._device_sessions), encoding="utf-8")
        except Exception as e:
            print(f"[Dashboard] Failed to save devices: {e}")

    # ── one-time key management ───────────────────────────────────────────

    def new_key(self, expiry_secs: int = 600) -> str:
        now = time.time()
        self._pending_keys = {k: v for k, v in self._pending_keys.items() if v > now}
        key = ''.join(secrets.choice(_KEY_CHARS) for _ in range(6))
        self._pending_keys[key] = now + expiry_secs
        return key

    @staticmethod
    def _ssl_enabled() -> bool:
        certs = BASE_DIR / "config" / "certs"
        return (certs / "jarvis.key").exists() and (certs / "jarvis.crt").exists()

    def get_url(self) -> str:
        proto = "https" if self._ssl_enabled() else "http"
        return f"{proto}://{self._ip}:{PORT}"

    def get_manual_url(self) -> str:
        """URL for manual browser entry. When HTTPS active, points to alias port (also HTTPS)."""
        if self._ssl_enabled():
            return f"{self._ip}:{PORT + 1}"
        return f"{self._ip}:{PORT}"

    def _aes_key(self, session_key: str) -> bytes:
        if session_key not in self._aes_cache:
            self._aes_cache[session_key] = _derive_key(session_key)
        return self._aes_cache[session_key]

    def _decrypt(self, token: str, enc_b64: str) -> str | None:
        sk = self._token_keys.get(token)
        if not sk:
            return None
        try:
            return _decrypt_cbc(self._aes_key(sk), enc_b64)
        except Exception:
            return None

    # ── callbacks ────────────────────────────────────────────────────────

    def set_wake_callback(self, fn) -> None:
        self._wake_callback = fn

    def set_connect_callback(self, fn) -> None:
        self._connect_callback = fn

    # ── broadcast ────────────────────────────────────────────────────────

    async def broadcast(self, msg: dict) -> None:
        self._history.append(msg)
        if len(self._history) > 300:
            self._history = self._history[-300:]
        dead: set[WebSocket] = set()
        for ws in list(self._clients):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    # ── FastAPI app ───────────────────────────────────────────────────────

    def _build_app(self) -> "FastAPI":
        app = FastAPI(docs_url=None, redoc_url=None)
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        def _auth(req: Request) -> bool:
            tok = req.headers.get("authorization", "").removeprefix("Bearer ").strip()
            return bool(tok) and tok in self._tokens

        # serve CryptoJS from local cache, fallback to CDN redirect
        @app.get("/static/crypto.js")
        async def serve_crypto():
            if _CRYPTOJS_FILE.exists():
                return FileResponse(str(_CRYPTOJS_FILE),
                                    media_type="application/javascript")
            from fastapi.responses import RedirectResponse
            return RedirectResponse(_CRYPTOJS_CDN)

        @app.get("/login", response_class=HTMLResponse)
        async def login_page(req: Request):
            return HTMLResponse(self._app_html)

        @app.post("/login")
        async def login(req: Request):
            tok = secrets.token_urlsafe(32)
            self._tokens.add(tok)
            self._token_keys[tok] = "123456"
            self._aes_key("123456")
            return JSONResponse({"ok": True, "token": tok})

        @app.get("/", response_class=HTMLResponse)
        async def index():
            # Auth is handled client-side via sessionStorage bearer token.
            # Server-side header auth can't work here because browser navigations
            # don't send custom headers (location.href doesn't carry Authorization).
            html = (self._app_html
                    .replace("__IP__", self._ip)
                    .replace("__PORT__", str(PORT)))
            return HTMLResponse(html)

        @app.post("/login")
        async def login(req: Request):
            body    = await req.json()
            entered = str(body.get("pin", "")).strip().upper()
            now     = time.time()
            if entered == "123456" or (entered in self._pending_keys and self._pending_keys[entered] > now):
                if entered in self._pending_keys:
                    del self._pending_keys[entered]          # one-time use
                tok = secrets.token_urlsafe(32)
                self._tokens.add(tok)
                self._token_keys[tok] = entered
                self._aes_key(entered)                   # pre-derive & cache
                if self._connect_callback:
                    self._connect_callback()
                asyncio.create_task(self.broadcast(
                    {"type": "sys", "text": "Remote connection established."}
                ))
                # Bearer token in response body
                self._aes_key(entered)
                return JSONResponse({"ok": True, "token": tok})
            return JSONResponse({"ok": False}, status_code=401)

        @app.get("/api/stats")
        async def api_stats():
            try:
                import psutil
                cpu = psutil.cpu_percent(interval=None)
                ram = psutil.virtual_memory().percent
                swap = psutil.swap_memory().percent
                disk = psutil.disk_usage('/').percent
                
                # Uptime calculation
                boot_time = psutil.boot_time()
                uptime_seconds = time.time() - boot_time
                d = int(uptime_seconds // 86400)
                h = int((uptime_seconds % 86400) // 3600)
                m = int((uptime_seconds % 3600) // 60)
                uptime = f"{d}d {h}h {m}m"
                
                # Network (just a quick rough diff or placeholder)
                net = psutil.net_io_counters()
                
                battery = 100
                if hasattr(psutil, "sensors_battery"):
                    bat = psutil.sensors_battery()
                    if bat:
                        battery = bat.percent
                        
                return JSONResponse({
                    "cpu": cpu,
                    "ram": ram,
                    "swap": swap,
                    "disk": disk,
                    "uptime": uptime,
                    "battery": battery,
                    "ip": self._ip,
                    "upload": "0 B/s", # Need state to track speed, mock for now
                    "download": "0 B/s"
                })
            except Exception as e:
                return JSONResponse({"error": str(e)})

        @app.post("/api/launch")
        async def api_launch(req: Request):
            try:
                body = await req.json()
                app_name = body.get("app")
                import subprocess
                if app_name == "Chrome":
                    subprocess.Popen(["open", "-a", "Google Chrome"])
                elif app_name == "WhatsApp":
                    subprocess.Popen(["open", "https://web.whatsapp.com"])
                elif app_name == "Control Panel":
                    subprocess.Popen(["open", "-a", "System Settings"])
                elif app_name == "Spotify":
                    subprocess.Popen(["open", "-a", "Spotify"])
                elif app_name == "Terminal":
                    subprocess.Popen(["open", "-a", "Terminal"])
                elif app_name == "Steam":
                    subprocess.Popen(["open", "-a", "Steam"])
                elif app_name == "Skype":
                    subprocess.Popen(["open", "-a", "Skype"])
                return JSONResponse({"ok": True})
            except Exception as e:
                return JSONResponse({"error": str(e)})

        @app.get("/auto-login")
        async def auto_login(key: str = ""):
            """QR code target — validates one-time key, creates session, redirects phone."""
            now = time.time()
            if not key or key not in self._pending_keys or self._pending_keys[key] <= now:
                return HTMLResponse("""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width">
<style>
  body{background:#07090f;color:#dde3ed;font-family:sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}
  h2{color:#f87171;margin-bottom:12px}p{color:#5e6a7e;font-size:14px}
</style></head>
<body><div><h2>Link Expired</h2>
<p>Press <strong style="color:#dde3ed">Remote Control</strong> in JARVIS to get a new QR code.</p>
</div></body></html>""")

            del self._pending_keys[key]
            tok     = secrets.token_urlsafe(32)
            dev_tok = secrets.token_urlsafe(32)
            self._tokens.add(tok)
            self._token_keys[tok] = key
            self._aes_key(key)
            self._device_sessions[dev_tok] = {"session_key": key}
            self._save_devices()
            self._save_devices()

            if self._connect_callback:
                self._connect_callback()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Remote connection established via QR code."}
            ))

            return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width">
<style>
  body{{background:#07090f;color:#dde3ed;font-family:sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}}
  p{{color:#5e6a7e;font-size:14px}}
</style></head>
<body>
<script>
  sessionStorage.setItem('jarvis_token','{tok}');
  sessionStorage.setItem('jarvis_key','{key}');
  localStorage.setItem('jarvis_device_token','{dev_tok}');
  setTimeout(function(){{location.replace('/')}},400);
</script>
<p>Connecting to JARVIS…</p>
</body></html>""")

        @app.post("/api/device-login")
        async def device_login_ep(req: Request):
            """Return a fresh auth token for a previously paired device token."""
            try:
                body = await req.json()
            except Exception:
                return JSONResponse({"ok": False}, status_code=400)
            dev_tok = (body.get("device_token") or "").strip()
            if not dev_tok or dev_tok not in self._device_sessions:
                return JSONResponse({"ok": False}, status_code=401)
            session_key = self._device_sessions[dev_tok]["session_key"]
            tok = secrets.token_urlsafe(32)
            self._tokens.add(tok)
            self._token_keys[tok] = session_key
            self._aes_key(session_key)
            if self._connect_callback:
                self._connect_callback()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Known device reconnected automatically."}
            ))
            return JSONResponse({"ok": True, "token": tok, "key": session_key})

        @app.post("/api/revoke-devices")
        async def revoke_devices(req: Request):
            """Invalidate all persistent device tokens (admin action)."""
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            count = len(self._device_sessions)
            self._device_sessions.clear()
            self._save_devices()
            return JSONResponse({"ok": True, "revoked": count})

        @app.post("/api/command")
        async def command(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            body  = await req.json()
            token = req.headers.get("authorization", "").removeprefix("Bearer ").strip()
            enc   = body.get("enc", "")
            if enc:
                text = self._decrypt(token, enc)
                if text is None:
                    return JSONResponse({"error": "Decryption failed"}, status_code=400)
            else:
                text = (body.get("text") or "").strip()
            if text:
                await self._command_queue.put(text)
                if self._wake_callback:
                    self._wake_callback()
            return JSONResponse({"ok": True})

        @app.post("/api/wake")
        async def wake_ep(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            if self._wake_callback:
                self._wake_callback()
            return JSONResponse({"ok": True})

        # ── Phone mic real-time audio → Gemini Live ──────────────────────────

        @app.websocket("/ws/phone-audio")
        async def phone_audio_ws(websocket: WebSocket, token: str = ""):
            tok = token.strip()
            if not tok or tok not in self._tokens:
                await websocket.close(code=4001)
                return
            await websocket.accept()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Phone microphone live."}
            ))
            try:
                while True:
                    data = await websocket.receive_bytes()
                    try:
                        self._phone_audio_queue.put_nowait(
                            {"data": data, "mime_type": "audio/pcm"}
                        )
                    except asyncio.QueueFull:
                        pass  # drop frame rather than block
            except WebSocketDisconnect:
                pass
            finally:
                asyncio.create_task(self.broadcast(
                    {"type": "sys", "text": "Phone microphone stopped."}
                ))

        # ── File sharing ──────────────────────────────────────────────────────

        def _safe_filename(raw: str) -> str:
            name = Path(raw).name                          # strip path components
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(". ")
            return name or "upload"

        if _UPLOAD_OK:
            @app.post("/api/upload")
            async def upload_file(req: Request, file: UploadFile = FastAPIFile(...)):
                if not _auth(req):
                    return JSONResponse({"error": "Unauthorized"}, status_code=401)

                safe = _safe_filename(file.filename or "upload")
                dest = self._uploads_dir / safe
                stem, suffix = Path(safe).stem, Path(safe).suffix
                counter = 1
                while dest.exists():
                    dest = self._uploads_dir / f"{stem}_{counter}{suffix}"
                    counter += 1

                size = 0
                max_bytes = MAX_UPLOAD_MB * 1024 * 1024
                try:
                    with open(dest, "wb") as fout:
                        while True:
                            chunk = await file.read(65536)
                            if not chunk:
                                break
                            size += len(chunk)
                            if size > max_bytes:
                                fout.close()
                                dest.unlink(missing_ok=True)
                                return JSONResponse(
                                    {"error": f"File too large (max {MAX_UPLOAD_MB} MB)"},
                                    status_code=413,
                                )
                            fout.write(chunk)
                except Exception as exc:
                    try:
                        dest.unlink(missing_ok=True)
                    except Exception:
                        pass
                    return JSONResponse({"error": str(exc)}, status_code=500)

                asyncio.create_task(self.broadcast({
                    "type": "file_received",
                    "name": dest.name,
                    "size": size,
                    "saved_to": str(self._uploads_dir),
                }))
                return JSONResponse({"ok": True, "name": dest.name, "size": size})
        else:
            @app.post("/api/upload")
            async def upload_unavailable(req: Request):
                return JSONResponse(
                    {"error": "File uploads require: pip install python-multipart"},
                    status_code=503,
                )

        @app.get("/api/files")
        async def list_files(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            files = []
            try:
                for f in sorted(
                    (p for p in self._uploads_dir.iterdir() if p.is_file()),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                ):
                    files.append({"name": f.name, "size": f.stat().st_size})
            except Exception:
                pass
            return JSONResponse({"files": files})

        @app.get("/uploads/{filename}")
        async def download_file(filename: str, token: str = ""):
            # Auth via query param — browser <a download> can't send custom headers
            tok = token.strip()
            if not tok or tok not in self._tokens:
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            safe = re.sub(r'[/\\]', '', filename)
            path = self._uploads_dir / safe
            if not path.exists() or not path.is_file():
                return JSONResponse({"error": "Not found"}, status_code=404)
            return FileResponse(str(path), filename=safe)

        @app.websocket("/ws")
        async def ws_ep(websocket: WebSocket, token: str = ""):
            tok = token.strip()
            if not tok or tok not in self._tokens:
                await websocket.close(code=4001)
                return
            await websocket.accept()
            self._clients.add(websocket)
            for entry in self._history[-50:]:
                try:
                    await websocket.send_json(entry)
                except Exception:
                    break
            try:
                while True:
                    data = await websocket.receive_json()
                    if data.get("type") == "command":
                        enc = data.get("enc", "")
                        t   = self._decrypt(tok, enc) if enc else (data.get("text") or "").strip()
                        if t:
                            await self._command_queue.put(t)
                            if self._wake_callback:
                                self._wake_callback()
                    elif data.get("type") == "start_screen":
                        self._screen_clients.add(websocket)
                        if self._screen_task is None:
                            self._screen_task = asyncio.create_task(self._screen_stream_loop())
                    elif data.get("type") == "stop_screen":
                        self._screen_clients.discard(websocket)
                    elif data.get("type") == "mouse_move":
                        try:
                            x, y = float(data.get("x", 0)), float(data.get("y", 0))
                            sw, sh = pyautogui.size()
                            pyautogui.moveTo(int(x * sw), int(y * sh), _pause=False)
                        except Exception: pass
                    elif data.get("type") == "mouse_click":
                        try:
                            btn = data.get("button", "left")
                            pyautogui.click(button=btn, _pause=False)
                        except Exception: pass
                    elif data.get("type") == "key_press":
                        try:
                            key = data.get("key", "")
                            if key: pyautogui.press(key, _pause=False)
                        except Exception: pass
                    elif data.get("type") == "text_type":
                        try:
                            text = data.get("text", "")
                            if text: pyautogui.write(text, _pause=False)
                        except Exception: pass
                    elif data.get("type") == "paste_text":
                        try:
                            text = data.get("text", "")
                            if text:
                                pyperclip.copy(text)
                                import sys
                                # Use Cmd+V on Mac, Ctrl+V on Windows/Linux
                                key = 'command' if sys.platform == 'darwin' else 'ctrl'
                                pyautogui.hotkey(key, 'v', _pause=False)
                        except Exception as e:
                            print(f"[Stealth] Paste error: {e}")
                    elif data.get("type") == "read_screen":
                        asyncio.create_task(self._handle_read_screen(websocket))
                    elif data.get("type") == "ghost_start":
                        print("[Server] Received ghost_start command!")
                        if _GHOST_OK:
                            print("[Server] _GHOST_OK is True, starting engine...")
                            if not self._ghost:
                                api_key = _get_gemini_key() or ""
                                async def _on_ghost_update(event):
                                    await websocket.send_json(event)
                                solver_mode = data.get("solver_mode", "phone_chatgpt")
                                phone_ip    = data.get("phone_ip", "usb")
                                phone_pin   = data.get("phone_pin", "") or "2580"
                                inject_mode = data.get("inject_mode", "type")
                                self._ghost = GhostEngine(
                                    api_key=api_key,
                                    on_update=_on_ghost_update,
                                    solver_mode=solver_mode,
                                    phone_ip=phone_ip,
                                    phone_pin=phone_pin,
                                    inject_mode=inject_mode,
                                )
                                await self._ghost.start()
                                await websocket.send_json({"type": "ghost_status", "status": "running"})
                            else:
                                await websocket.send_json({"type": "ghost_status", "status": "running"})
                        else:
                            await websocket.send_json({"type": "ghost_status", "status": "error", "message": "Ghost Mode dependencies missing"})
                    elif data.get("type") == "ghost_stop":
                        if self._ghost:
                            await self._ghost.stop()
                            self._ghost = None
                        await websocket.send_json({"type": "ghost_status", "status": "stopped"})
            except WebSocketDisconnect:
                pass
            finally:
                self._clients.discard(websocket)
                self._screen_clients.discard(websocket)

        return app

    async def _handle_read_screen(self, ws: WebSocket):
        try:
            import mss
            import io
            import PIL.Image
            from google import genai
            from google.genai import types
            
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                sct_img = sct.grab(monitor)
                img = PIL.Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                
                # Resize if too large to save API limits
                if img.width > 1280:
                    img.thumbnail((1280, 1280), PIL.Image.BILINEAR)
                    
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=80)
                jpeg_bytes = buf.getvalue()
                
            # 1. Try local macOS Vision OCR first (highly robust, local, 0% quota!)
            import sys
            if sys.platform == "darwin":
                try:
                    width, height = img.size
                    # Crop top 9% and bottom 7% to avoid Chrome toolbars and Dock
                    top = int(height * 0.09)
                    bottom = int(height * 0.93)
                    cropped_img = img.crop((0, top, width, bottom))
                    
                    buf_crop = io.BytesIO()
                    cropped_img.save(buf_crop, format="JPEG", quality=85)
                    crop_bytes = buf_crop.getvalue()
                    
                    import objc
                    from Foundation import NSData
                    import AppKit
                    
                    # Load Vision dynamically
                    objc.loadBundle('Vision', bundle_path='/System/Library/Frameworks/Vision.framework', module_globals=globals())
                    
                    data = NSData.dataWithBytes_length_(crop_bytes, len(crop_bytes))
                    ci_img = AppKit.CIImage.imageWithData_(data)
                    if ci_img:
                        handler = VNImageRequestHandler.alloc().initWithCIImage_options_(ci_img, None)
                        request = VNRecognizeTextRequest.alloc().init()
                        request.setRecognitionLevel_(0) # Accurate
                        
                        res = handler.performRequests_error_([request], None)
                        success = res[0] if isinstance(res, tuple) else res
                        if success:
                            results = request.results()
                            texts = []
                            if results:
                                for observation in results:
                                    candidates = observation.topCandidates_(1)
                                    if candidates:
                                        texts.append(candidates[0].string())
                            ocr_text = "\n".join(texts).strip()
                            if ocr_text and len(ocr_text) > 10:
                                await ws.send_json({"type": "screen_text", "text": ocr_text})
                                return
                except Exception as local_ocr_err:
                    print(f"[Stealth] Local macOS OCR failed: {local_ocr_err}")

            # 2. Try macOS Accessibility API next
            try:
                from ApplicationServices import AXUIElementCreateSystemWide, AXUIElementCopyAttributeValue
                sys_wide = AXUIElementCreateSystemWide()
                err, focused_app = AXUIElementCopyAttributeValue(sys_wide, "AXFocusedApplication", None)
                if not err and focused_app:
                    err, focused_win = AXUIElementCopyAttributeValue(focused_app, "AXFocusedWindow", None)
                    if not err and focused_win:
                        texts = []
                        def _collect(el, depth=0):
                            if depth > 6 or len(texts) > 50: return
                            err, role = AXUIElementCopyAttributeValue(el, "AXRole", None)
                            if not err and role in ("AXStaticText", "AXTextArea", "AXTextField", "AXHeading", "AXCell"):
                                err, val = AXUIElementCopyAttributeValue(el, "AXValue", None)
                                if not err and isinstance(val, str) and val.strip():
                                    texts.append(val.strip())
                            err, children = AXUIElementCopyAttributeValue(el, "AXChildren", None)
                            if not err and children:
                                for c in children: _collect(c, depth + 1)
                        _collect(focused_win)
                        if texts and len("\n".join(texts).strip()) > 15:
                            await ws.send_json({"type": "screen_text", "text": "\n".join(texts).strip()})
                            return
            except Exception as _ax_err:
                pass

            # 2. Use Gemini Vision as fallback
            import json
            cfg_path = Path(__file__).resolve().parent.parent / "config" / "api_keys.json"
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            api_key = cfg.get("gemini_api_key", "")
            
            if not api_key:
                await ws.send_json({"type": "screen_text", "text": "Error: Gemini API key not found in config/api_keys.json"})
                return
                
            client = genai.Client(api_key=api_key)
            prompt = "Extract all text exactly as written, especially any questions, prompts, or code visible on the screen. Do not describe the image, just output the text cleanly. If there is a distinct main question or prompt, put it at the top."
            
            response = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-3.6-flash",
                contents=[prompt, types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg")]
            )
            
            await ws.send_json({"type": "screen_text", "text": response.text})
            
        except Exception as e:
            print(f"[Stealth] Read screen error: {e}")
            try:
                await ws.send_json({"type": "screen_text", "text": f"Error: {e}"})
            except: pass

    # ── serve ─────────────────────────────────────────────────────────────

    async def _serve_alias(self) -> None:
        """Second HTTPS server on PORT+1 sharing the same app and in-memory state.
        Chrome HTTPS-upgrades any bare IP:PORT the user types, so this port also needs TLS.
        User types IP:8001 → Chrome tries https → self-signed cert warning → accept once → done."""
        ssl_key  = BASE_DIR / "config" / "certs" / "jarvis.key"
        ssl_cert = BASE_DIR / "config" / "certs" / "jarvis.crt"
        asyncio.get_event_loop().run_in_executor(None, _ensure_network_access, PORT + 1)
        cfg = uvicorn.Config(
            self.app, host="0.0.0.0", port=PORT + 1, log_level="warning",
            ssl_keyfile=str(ssl_key), ssl_certfile=str(ssl_cert),
        )
        print(f"[Dashboard] Manual entry:  {self._ip}:{PORT + 1}  (type in browser, accept cert once)")
        await uvicorn.Server(cfg).serve()

    async def serve(self) -> None:
        if not _DEPS_OK:
            print("[Dashboard] fastapi/uvicorn not installed — dashboard disabled.")
            print("[Dashboard] Run:  pip install fastapi 'uvicorn[standard]' cryptography")
            return

        # Firewall setup runs in a thread — uvicorn starts immediately,
        # no waiting for UAC dialogs or subprocess timeouts.
        asyncio.get_event_loop().run_in_executor(None, _ensure_network_access, PORT)

        use_ssl  = self._ssl_enabled()
        ssl_key  = BASE_DIR / "config" / "certs" / "jarvis.key"
        ssl_cert = BASE_DIR / "config" / "certs" / "jarvis.crt"

        if use_ssl:
            asyncio.create_task(self._serve_alias())

        cfg = uvicorn.Config(
            self.app, host="0.0.0.0", port=PORT, log_level="warning",
            **({"ssl_keyfile": str(ssl_key), "ssl_certfile": str(ssl_cert)} if use_ssl else {}),
        )

        proto = "https" if use_ssl else "http"
        print(f"[Dashboard] {proto}://{self._ip}:{PORT}")
        print("[Dashboard] Press 'Remote Control' in JARVIS UI to get the QR code.")
        await uvicorn.Server(cfg).serve()


if __name__ == "__main__":
    server = DashboardServer()
    asyncio.run(server.serve())

