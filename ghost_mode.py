"""
ghost_mode.py — JARVIS Ghost Mode Engine

Invisible screen reader + AI auto-answer system.
Reads the laptop screen at OS level, detects questions,
gets answers from Gemini AI, and types them back silently.

Designed to be imported by dashboard/server.py and run as
an asyncio background task.
"""

import asyncio
import subprocess
import json
import base64
import io
import time
import sys
import traceback
import re
import difflib
from pathlib import Path

# ── Optional macOS Accessibility API ────────────────────────────────
_HAS_AX = False
try:
    if sys.platform == "darwin":
        from ApplicationServices import (
            AXUIElementCreateSystemWide,
            AXUIElementCopyAttributeValue,
            AXUIElementCreateApplication,
        )
        from Quartz import (
            CGWindowListCopyWindowInfo,
            kCGWindowListOptionOnScreenOnly,
            kCGNullWindowID,
            kCGWindowListExcludeDesktopElements,
        )
        import AppKit
        _HAS_AX = True
except ImportError:
    pass

# ── Screenshot + AI deps ────────────────────────────────────────────
try:
    import mss
except ImportError:
    mss = None

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    from google import genai
except ImportError:
    genai = None


# ─────────────────────────────────────────────────────────────────────
#  Ghost Mode Engine
# ─────────────────────────────────────────────────────────────────────

class GhostEngine:
    """
    Invisible screen reader + AI solver.

    Usage:
        engine = GhostEngine(api_key="...", on_update=callback)
        await engine.start()   # runs until stop() is called
        await engine.stop()
    """

    def __init__(self, api_key: str, on_update=None, scan_interval: float = 4.0,
                 solver_mode: str = "phone_chatgpt", inject_mode: str = "type",
                 phone_ip: str = "usb", phone_pin: str = "2580"):
        """
        Args:
            api_key:       Gemini API key
            on_update:     async callback(event_dict) for status updates to dashboard
            scan_interval: seconds between screen scans
        """
        self.api_key = api_key
        self.on_update = on_update
        self.scan_interval = scan_interval
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_text = ""
        self._last_raw_text = ""
        self._last_answer = ""
        self._last_answered_text = ""
        self._pending_paste = None
        self._auto_answer = True
        
        self.solver_mode = solver_mode
        self.inject_mode = inject_mode
        self.phone_ip = phone_ip
        self.phone_pin = phone_pin
        self._is_paused = False
        self._state = "ACTIVE"
        
        # Start global hotkey listener for Panic Button
        try:
            from pynput import keyboard
            def toggle_pause():
                self._is_paused = not self._is_paused
                state_str = "PAUSED" if self._is_paused else "RESUMED"
                print(f"[Ghost] 🛑 Panic Button Pressed! Typing {state_str}.")
            
            self._listener = keyboard.GlobalHotKeys({
                '<ctrl>+<esc>': toggle_pause,
                '<alt>+z': toggle_pause
            })
            self._listener.start()
        except ImportError:
            print("[Ghost] Warning: pynput not installed. Panic Button disabled.")

    # ── Public API ──────────────────────────────────────────────────

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        await self._emit({"type": "ghost_status", "active": True, "msg": f"Ghost Mode activated ({self.solver_mode} mode)"})

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._emit({"type": "ghost_status", "active": False, "msg": "Ghost Mode deactivated"})

    @property
    def is_running(self) -> bool:
        return self._running

    async def inject_text(self, text: str):
        """Manually inject text to type on laptop (from phone dashboard)."""
        await self._do_inject(text)
        await self._emit({"type": "ghost_injected", "text": text})

    async def read_once(self) -> str:
        """Single screen read, returns extracted text."""
        text = await self._read_screen()
        await self._emit({"type": "ghost_screen_text", "text": text})
        return text

    # ── Main Loop ───────────────────────────────────────────────────

    async def _loop(self):
        await self._emit({"type": "ghost_log", "msg": "👻 Scanning screen..."})
        while self._running:
            try:
                # 1. Read screen text
                current_text = await self._read_screen()

                if not current_text or not current_text.strip():
                    await asyncio.sleep(self.scan_interval)
                    continue
                
                print(f"[Ghost] Read {len(current_text)} chars. Meaningful: {self._is_meaningful_content(current_text)}")

                # 2. Filter out UI noise (toolbar buttons, navigation elements)
                if not self._is_meaningful_content(current_text):
                    print(f"[Ghost] Rejected noise: {repr(current_text[:100])}...")
                    await asyncio.sleep(self.scan_interval)
                    continue
                
                print(f"[Ghost] Accepted text: {repr(current_text[:100])}...")

                # 3. Check if content changed significantly
                if self._should_trigger(current_text):
                    self._last_text = current_text
                    await self._emit({
                        "type": "ghost_screen_text",
                        "text": current_text
                    })

                    # 4. Auto-answer if enabled
                    if self._auto_answer:
                        await self._emit({"type": "ghost_log", "msg": f"🧠 Getting answer via {self.solver_mode}..."})
                        answer = await self._get_answer(current_text)
                        if answer and not answer.startswith("[Error"):
                            self._last_answer = answer
                            self._last_answered_text = current_text
                            await self._emit({
                                "type": "ghost_answer",
                                "question": current_text[:200],
                                "answer": answer
                            })
                            # Auto-inject answer silently to cursor on laptop
                            await self._emit({"type": "ghost_log", "msg": f"⌨️ Injecting answer ({self.inject_mode} mode)..."})
                            await self._do_inject(answer)
                        elif answer:
                            await self._emit({"type": "ghost_log", "msg": f"⚠️ {answer}"})

                await asyncio.sleep(self.scan_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                await self._emit({"type": "ghost_log", "msg": f"❌ Error: {e}"})
                await asyncio.sleep(self.scan_interval)

    # ── Screen Reading ──────────────────────────────────────────────

    async def _read_screen(self) -> str:
        """
        Read screen text. Tries local macOS Vision OCR first (very robust, skips menus),
        falls back to macOS AX API, and finally falls back to Gemini Vision OCR if not on Mac.
        """
        # 1. Try local macOS Vision OCR (highly robust, local, 0% quota)
        if sys.platform == "darwin":
            try:
                img_bytes = await asyncio.to_thread(self._capture_screen, True)
                if img_bytes:
                    text = await asyncio.to_thread(self._local_ocr_mac, img_bytes)
                    if text and len(text.strip()) > 10:
                        return text.strip()
            except Exception as e:
                print(f"Local macOS Vision OCR failed: {e}")

        # 2. Fallback to Accessibility API (macOS)
        if _HAS_AX:
            text = await asyncio.to_thread(self._read_ax_text)
            if text and len(text.strip()) > 10:
                return text.strip()

        # 3. Fallback to Gemini Vision OCR (if not on Mac/failed)
        return await self._read_screen_vision()

    def _read_ax_text(self) -> str:
        """
        Read text from all active windows using macOS Accessibility API.
        """
        try:
            texts = []
            sys_wide = AXUIElementCreateSystemWide()
            
            # 1. Try focused application first
            err, focused_app = AXUIElementCopyAttributeValue(sys_wide, "AXFocusedApplication", None)
            if not err and focused_app:
                err, focused_win = AXUIElementCopyAttributeValue(focused_app, "AXFocusedWindow", None)
                if not err and focused_win:
                    self._collect_ax_text(focused_win, texts, depth=0, max_depth=8)
                    if texts:
                        return "\n".join(texts)

            # 2. Fallback: Iterate all active workspace applications via AppKit
            if _HAS_AX:
                ws = AppKit.NSWorkspace.sharedWorkspace()
                for app in ws.runningApplications():
                    if app.activationPolicy() == AppKit.NSApplicationActivationPolicyRegular and not app.isHidden():
                        pid = app.processIdentifier()
                        ax_app = AXUIElementCreateApplication(pid)
                        err, win_list = AXUIElementCopyAttributeValue(ax_app, "AXWindows", None)
                        if not err and win_list:
                            for win in win_list:
                                self._collect_ax_text(win, texts, depth=0, max_depth=6)

            return "\n".join(texts).strip()

        except Exception:
            return ""

    def _collect_ax_text(self, element, texts: list, depth: int, max_depth: int):
        """Recursively collect text from AX element tree."""
        if depth > max_depth or len(texts) > 100:
            return
        try:
            # Get role
            err, role = AXUIElementCopyAttributeValue(element, "AXRole", None)
            role = str(role) if not err and role else ""

            # Collect text from text-bearing elements (exclude buttons, links, menu items)
            if role in ("AXStaticText", "AXTextArea", "AXTextField", "AXTextGroup", "AXHeading"):
                err, val = AXUIElementCopyAttributeValue(element, "AXValue", None)
                if not err and val and isinstance(val, str) and val.strip():
                    texts.append(val.strip())
                else:
                    err, title = AXUIElementCopyAttributeValue(element, "AXTitle", None)
                    if not err and title and isinstance(title, str) and title.strip():
                        texts.append(title.strip())

            # Recurse into children
            err, children = AXUIElementCopyAttributeValue(element, "AXChildren", None)
            if not err and children:
                for child in children:
                    self._collect_ax_text(child, texts, depth + 1, max_depth)

        except Exception:
            pass

    async def _read_screen_vision(self) -> str:
        """Fallback: screenshot + Gemini Vision OCR."""
        if not mss or not Image or not genai:
            return "[Ghost] Missing deps: mss, Pillow, or google-genai"

        try:
            # Capture screen without cropping for cloud OCR
            img_bytes = await asyncio.to_thread(self._capture_screen, False)
            if not img_bytes:
                return ""

            # Send to Gemini Vision for OCR
            client = genai.Client(api_key=self.api_key)
            b64 = base64.standard_b64encode(img_bytes).decode()

            response = await asyncio.to_thread(
                lambda: client.models.generate_content(
                    model="gemini-1.5-flash",
                    contents=[
                        {
                            "role": "user",
                            "parts": [
                                {"text": "Extract ALL text visible on this screen. Return ONLY the raw text, no formatting or commentary. Focus on the main content area — questions, paragraphs, form fields. Ignore toolbars, menus, and system UI."},
                                {"inline_data": {"mime_type": "image/jpeg", "data": b64}}
                            ]
                        }
                    ]
                )
            )
            return response.text.strip() if response.text else ""

        except Exception as e:
            return f"[Vision error: {e}]"

    def _capture_screen(self, crop: bool = True) -> bytes | None:
        """Capture primary display as JPEG bytes, optionally cropping toolbars."""
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                shot = sct.grab(monitor)
                img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                
                if crop:
                    width, height = img.size
                    # Crop top 15% (menu bar, tabs, URL bar, bookmarks) and bottom 10% (dock, taskbar)
                    top = int(height * 0.15)
                    bottom = int(height * 0.90)
                    img = img.crop((0, top, width, bottom))
                    
                # Resize to standard width to speed up processing
                max_w = 1440
                if img.width > max_w:
                    ratio = max_w / img.width
                    img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=85)
                return buf.getvalue()
        except Exception:
            return None

    def _local_ocr_mac(self, img_bytes: bytes) -> str:
        """Use macOS native Vision framework to perform high-speed offline OCR."""
        try:
            import objc
            from Foundation import NSData
            import AppKit
            
            # Load Vision bundle dynamically
            objc.loadBundle('Vision', bundle_path='/System/Library/Frameworks/Vision.framework', module_globals=globals())
            
            data = NSData.dataWithBytes_length_(img_bytes, len(img_bytes))
            ci_image = AppKit.CIImage.imageWithData_(data)
            if not ci_image:
                return ""
                
            handler = VNImageRequestHandler.alloc().initWithCIImage_options_(ci_image, None)
            request = VNRecognizeTextRequest.alloc().init()
            request.setRecognitionLevel_(0) # Accurate level
            
            res = handler.performRequests_error_([request], None)
            success = res[0] if isinstance(res, tuple) else res
            if not success:
                return ""
                
            results = request.results()
            texts = []
            if results:
                for observation in results:
                    candidates = observation.topCandidates_(1)
                    if candidates:
                        texts.append(candidates[0].string())
            return "\n".join(texts).strip()
        except Exception as e:
            print(f"Local macOS OCR error: {e}")
            return ""

    # ── AI Answer Generation ────────────────────────────────────────

    async def _get_answer(self, question_text: str) -> str:
        """Send question to Gemini or phone ChatGPT and get answer."""
        if self.solver_mode == "phone_chatgpt":
            return await self._get_answer_phone_chatgpt(question_text)

        if not genai:
            return "[Error: google-genai not installed]"

        try:
            client = genai.Client(api_key=self.api_key)
            
            lower_q = question_text.lower()
            is_error = "wrong answer" in lower_q or "compile error" in lower_q or "runtime error" in lower_q
            
            if is_error and self._last_answer:
                # Self-Correction Loop
                self._is_correcting = True
                prompt = (
                    "You are an expert coding assistant. The user submitted the following code, but it resulted in an error.\n\n"
                    f"--- PREVIOUS CODE ---\n{self._last_answer}\n--- END PREVIOUS CODE ---\n\n"
                    f"--- ERROR MESSAGE & SCREEN CONTEXT ---\n{question_text[:2000]}\n--- END CONTEXT ---\n\n"
                    "Analyze the error and provide the COMPLETE, CORRECTED CODE. Do not include any markdown formatting, explanations, or backticks. ONLY output the raw code."
                )
            else:
                # Co-Pilot Mode (Context Awareness)
                self._is_correcting = False
                prompt = (
                    "You are an expert coding assistant operating in 'Co-Pilot' mode. The user has a problem on their screen.\n"
                    "If they have already started writing code, you must output ONLY the CONTINUATION of their code (starting exactly where their cursor left off). Do not repeat what they already wrote.\n"
                    "If the editor is empty, provide the full solution.\n"
                    "Do NOT add any preamble, markdown blocks, backticks, or formatting. Output ONLY raw text/code to be typed directly.\n\n"
                    "--- SCREEN CONTENT ---\n"
                    f"{question_text[:3000]}\n"
                    "--- END ---\n"
                )

            response = await asyncio.to_thread(
                lambda: client.models.generate_content(
                    model="gemini-1.5-flash",
                    contents=prompt
                )
            )
            return response.text.strip() if response.text else ""

        except Exception as e:
            return f"[AI Error: {e}]"

    async def _get_answer_phone_chatgpt(self, question_text: str) -> str:
        """Runs the Phone ChatGPT Route: connect -> unlock -> open ChatGPT -> paste question -> wait -> copy answer."""
        import subprocess
        ip = self.phone_ip or ""
        pin = self.phone_pin
        
        adb_prefix = ["adb"]
        if ip and ip != "usb":
            await self._emit({"type": "ghost_log", "msg": f"📱 Connecting to phone {ip}..."})
            connect_cmd = ["adb", "connect", f"{ip}:5555"]
            proc = await asyncio.create_subprocess_exec(*connect_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            await proc.communicate()
            adb_prefix = ["adb", "-s", f"{ip}:5555"]
        else:
            await self._emit({"type": "ghost_log", "msg": "📱 Connecting to phone via USB..."})
        
        # Check connection status
        check_cmd = adb_prefix + ["get-state"]
        proc = await asyncio.create_subprocess_exec(*check_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = await proc.communicate()
        if b"device" not in stdout:
            return f"[Error: Phone not detected via ADB ({'USB' if not ip or ip=='usb' else ip}). ADB state: {stdout.decode().strip()}]"
            
        # 2. Wake phone if asleep
        await self._emit({"type": "ghost_log", "msg": "📱 Waking screen..."})
        proc = await asyncio.create_subprocess_exec(
            *(adb_prefix + ["shell", "dumpsys", "power"]),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        is_awake = b"mWakefulness=Awake" in stdout
        if not is_awake:
            proc = await asyncio.create_subprocess_exec(
                *(adb_prefix + ["shell", "input", "keyevent", "26"])
            )
            await proc.wait()
            await asyncio.sleep(0.5)
            
        # 3. Unlock phone if locked
        await self._emit({"type": "ghost_log", "msg": "📱 Checking lock screen..."})
        proc = await asyncio.create_subprocess_exec(
            *(adb_prefix + ["shell", "dumpsys", "window"]),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode()
        is_locked = "mDreamingLockscreen=true" in output or \
                    "isStatusBarKeyguard=true" in output or \
                    "mShowingLockscreen=true" in output
                    
        if is_locked:
            await self._emit({"type": "ghost_log", "msg": "📱 Unlocking screen..."})
            proc = await asyncio.create_subprocess_exec(
                *(adb_prefix + ["shell", "input", "swipe", "540", "1600", "540", "800", "300"])
            )
            await proc.wait()
            await asyncio.sleep(0.8)
            
            if pin:
                proc = await asyncio.create_subprocess_exec(
                    *(adb_prefix + ["shell", "input", "text", pin])
                )
                await proc.wait()
                await asyncio.sleep(0.2)
                proc = await asyncio.create_subprocess_exec(
                    *(adb_prefix + ["shell", "input", "keyevent", "66"])
                )
                await proc.wait()
                await asyncio.sleep(0.8)
                
        # 4. Open ChatGPT and inject question text via Android Share Intent
        await self._emit({"type": "ghost_log", "msg": "📱 Injecting question via Intent..."})
        
        # Get screen size to compute dynamic tap coordinates
        width, height = 1080, 2400
        proc = await asyncio.create_subprocess_exec(
            *(adb_prefix + ["shell", "wm", "size"]),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        size_match = re.search(r"Physical size:\s*(\d+)x(\d+)", stdout.decode())
        if size_match:
            width, height = int(size_match.group(1)), int(size_match.group(2))
        
        # If this is an error, format the prompt so ChatGPT knows to fix it
        lower_q = question_text.lower()
        if "wrong answer" in lower_q or "compile error" in lower_q or "runtime error" in lower_q:
            final_prompt = "The previous code failed with this error. Please fix it:\n\n" + question_text[:1000]
        else:
            final_prompt = question_text[:1000]
            
        # Robust escaping for Android shell (sh):
        # 1. Escape single quotes as '\''
        # 2. Wrap entire string in single quotes
        escaped_text = final_prompt.replace("'", "'\\''")
        safe_text = f"'{escaped_text}'"
        
        # This intent natively opens ChatGPT and pre-fills the input box with the text!
        proc = await asyncio.create_subprocess_exec(
            *(adb_prefix + ["shell", "am", "start", "-a", "android.intent.action.SEND", "-t", "text/plain", "--es", "android.intent.extra.TEXT", safe_text, "-n", "com.openai.chatgpt/.MainActivity"]),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        await proc.wait()
        
        # Give ChatGPT time to open and animate the keyboard before tapping
        await asyncio.sleep(2.0)
        
        # 5. Tap the Send button instantly
        await self._emit({"type": "ghost_log", "msg": "📱 Tapping Send button..."})
        
        # UI Automator dump is too slow and buggy during keyboard animations.
        # We know exactly where the Send button is proportionally on the screen:
        # 1. If the keyboard is open, it's roughly at 52.5% height
        # 2. If the keyboard is closed, it's roughly at 93% height
        # The X coordinate is always at 92% width.
        scx = int(width * 0.92)
        scy_open = int(height * 0.525)
        scy_closed = int(height * 0.93)
        
        # Tap the open keyboard location first
        proc = await asyncio.create_subprocess_exec(
            *(adb_prefix + ["shell", "input", "tap", str(scx), str(scy_open)])
        )
        await proc.wait()
        await asyncio.sleep(0.5)
        
        # Tap the closed keyboard location next (in case keyboard didn't pop up)
        proc = await asyncio.create_subprocess_exec(
            *(adb_prefix + ["shell", "input", "tap", str(scx), str(scy_closed)])
        )
        await proc.wait()
        await asyncio.sleep(0.5)
        
        # Final fallback: press Enter key
        proc = await asyncio.create_subprocess_exec(
            *(adb_prefix + ["shell", "input", "keyevent", "66"])
        )
        await proc.wait()
        await asyncio.sleep(1.0)
        
        # 8. Wait for ChatGPT to generate response, then poll for answer
        await self._emit({"type": "ghost_log", "msg": "📱 Waiting for ChatGPT response..."})
        
        # Poll multiple times — ChatGPT may take 5-20s depending on question complexity
        answer = ""
        for attempt in range(4):
            wait_time = 5 if attempt == 0 else 4
            await asyncio.sleep(wait_time)
            await self._emit({"type": "ghost_log", "msg": f"📱 Extracting answer (attempt {attempt + 1}/4)..."})
            answer = await self._extract_chatgpt_response(adb_prefix, question_text)
            if answer and len(answer) > 10:
                break
        
        if not answer:
            answer = "[Error: Could not extract answer from screen layout]"
            
        return answer

    async def _find_element_coords(self, adb_target, match_fn) -> tuple[int, int] | None:
        import xml.etree.ElementTree as ET
        adb_cmd = adb_target if isinstance(adb_target, list) else ["adb", "-s", f"{adb_target}:5555"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *(adb_cmd + ["shell", "uiautomator", "dump", "/sdcard/window_dump.xml"]),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            await proc.wait()
            
            proc = await asyncio.create_subprocess_exec(
                *(adb_cmd + ["shell", "cat", "/sdcard/window_dump.xml"]),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            xml_data = stdout.decode("utf-8", errors="ignore")
            if not xml_data or "<hierarchy" not in xml_data:
                return None
                
            root = ET.fromstring(xml_data)
            for node in root.iter():
                if match_fn(node.attrib):
                    bounds = node.attrib.get("bounds", "")
                    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
                    if m:
                        x1, y1, x2, y2 = map(int, m.groups())
                        return (x1 + x2) // 2, (y1 + y2) // 2
        except Exception as e:
            print(f"Error parsing layout: {e}")
        return None

    async def _extract_chatgpt_response(self, adb_target, question_text: str) -> str:
        import xml.etree.ElementTree as ET
        adb_cmd = adb_target if isinstance(adb_target, list) else ["adb", "-s", f"{adb_target}:5555"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *(adb_cmd + ["shell", "uiautomator", "dump", "/sdcard/window_dump.xml"]),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            await proc.wait()
            
            proc = await asyncio.create_subprocess_exec(
                *(adb_cmd + ["shell", "cat", "/sdcard/window_dump.xml"]),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            xml_data = stdout.decode("utf-8", errors="ignore")
            if not xml_data or "<hierarchy" not in xml_data:
                return ""
                
            root = ET.fromstring(xml_data)
            
            # Collect text nodes ONLY from ChatGPT's package
            chatgpt_texts = []
            
            for node in root.iter():
                text = node.attrib.get("text", "").strip()
                pkg = node.attrib.get("package", "")
                res_id = node.attrib.get("resource-id", "")
                role = node.attrib.get("class", "")
                content_desc = node.attrib.get("content-desc", "").strip()
                
                if not text or len(text) < 3:
                    continue
                
                # STRICTLY only collect from ChatGPT package — no fallback to other apps
                if "openai" in pkg.lower() or "chatgpt" in pkg.lower():
                    entry = {"text": text, "pkg": pkg, "res_id": res_id, "role": role, "desc": content_desc}
                    chatgpt_texts.append(entry)
            
            # Only use ChatGPT-scoped texts — no fallback
            candidates = chatgpt_texts
            
            # UI labels to ignore
            ignored = {"chatgpt", "send", "copy", "share", "select", "regenerate",
                       "good response", "bad response", "stop", "pause", "new chat",
                       "message", "attach", "search", "gpt-4o", "gpt-4", "gpt-3.5",
                       "explore gpts", "today", "yesterday", "previous 7 days",
                       "message chatgpt", "you", "chatgpt said", "temporary chat",
                       "fast answer", "reason", "search", "web search", "analyzing"}
            
            # Normalize question text for filtering
            q_lower = question_text.lower().strip()
            q_words = set(q_lower.split())
            
            valid_texts = []
            for entry in candidates:
                t = entry["text"]
                t_lower = t.lower().strip()
                
                # Skip UI labels
                if t_lower in ignored:
                    continue
                    
                # Skip notification/status bar elements
                if "statusbar" in entry["res_id"].lower() or "notification" in entry["res_id"].lower():
                    continue
                
                # Skip input field text (EditText) — this is the user's typed question
                if "EditText" in entry["role"]:
                    continue
                    
                # Skip if text IS the user's question
                if t_lower == q_lower:
                    continue
                t_words = set(t_lower.split())
                if q_words and t_words and len(q_words) > 1:
                    overlap = len(q_words & t_words) / max(len(q_words), len(t_words))
                    if overlap > 0.8:
                        continue
                
                # Skip very short single-word UI artifacts
                if len(t) < 4 and " " not in t:
                    continue
                
                valid_texts.append(t)
                
            if valid_texts:
                # Return the longest text — ChatGPT responses are typically the longest text on screen
                return max(valid_texts, key=len)
        except Exception as e:
            print(f"Error extracting response: {e}")
        return ""

    # ── Answer Injection ────────────────────────────────────────────

    async def _do_inject(self, text: str):
        """Type or paste text on the laptop using Biometric Typing Engine."""
        try:
            import pyperclip
            import pyautogui
            import random
            
            # Active Window Tracker (Common Sense)
            active_app_name = None
            ws = None
            if _HAS_AX:
                import AppKit
                ws = AppKit.NSWorkspace.sharedWorkspace()
                front = ws.frontmostApplication()
                if front:
                    active_app_name = front.localizedName()
                    print(f"[Ghost] 🎯 Locked onto application: {active_app_name}")

            # Handle Self-Correction Mode: Cmd+A then Backspace to clear old code
            if getattr(self, '_is_correcting', False):
                await self._emit({"type": "ghost_log", "msg": "🧹 Clearing old code for correction..."})
                key = "command" if sys.platform == "darwin" else "ctrl"
                pyautogui.hotkey(key, "a", _pause=False)
                await asyncio.sleep(0.2)
                pyautogui.press("backspace", _pause=False)
                await asyncio.sleep(0.5)
                self._is_correcting = False

            if self.inject_mode == "paste":
                pyperclip.copy(text)
                await asyncio.sleep(0.1)
                key = "command" if sys.platform == "darwin" else "ctrl"
                pyautogui.hotkey(key, "v", _pause=False)
            else:
                # Biometric Typing Engine
                common_seqs = ["int", "for", "def", "while", "return", "class", "public", "void", "if", "else"]
                
                i = 0
                while i < len(text):
                    # Panic Button check
                    while self._is_paused:
                        await asyncio.sleep(0.1)
                        
                    # Active App Check (Common Sense)
                    if ws and active_app_name:
                        front = ws.frontmostApplication()
                        if front and front.localizedName() != active_app_name:
                            print(f"[Ghost] 🛑 Danger! Focus shifted to {front.localizedName()}! Auto-pausing...")
                            self._is_paused = True
                            continue # Loop back up to pause
                            
                    char = text[i]
                    
                    # Simulated typo (2% chance for regular lowercase letters)
                    if char.islower() and char.isalpha() and random.random() < 0.02:
                        wrong_char = chr(ord(char) + random.choice([-1, 1]))
                        if wrong_char.isalpha():
                            pyautogui.write(wrong_char, _pause=False)
                            await asyncio.sleep(random.uniform(0.1, 0.25))
                            pyautogui.press("backspace", _pause=False)
                            await asyncio.sleep(random.uniform(0.05, 0.15))
                    
                    # Shift simulation for uppercase
                    if char.isupper():
                        pyautogui.keyDown("shift")
                        await asyncio.sleep(random.uniform(0.02, 0.06))
                        pyautogui.press(char.lower(), _pause=False)
                        await asyncio.sleep(random.uniform(0.02, 0.06))
                        pyautogui.keyUp("shift")
                    elif char == '\n':
                        pyautogui.press("enter", _pause=False)
                        # Thinking pause after new line
                        await asyncio.sleep(random.uniform(0.5, 1.5))
                    else:
                        pyautogui.write(char, _pause=False)
                        
                    # Calculate flight time
                    delay = random.uniform(0.04, 0.12)
                    
                    # Slower for symbols
                    if char in "{}[];_=-+*&^%$#@!":
                        delay = random.uniform(0.15, 0.35)
                        
                    # Faster for common sequences (lookahead)
                    for seq in common_seqs:
                        if text[i:i+len(seq)] == seq:
                            delay = random.uniform(0.01, 0.04)
                            break
                            
                    await asyncio.sleep(delay)
                    i += 1

        except Exception as e:
            await self._emit({"type": "ghost_log", "msg": f"❌ Inject error: {e}"})

    # ── Helpers ─────────────────────────────────────────────────────

    def _raw_text_changed(self, new_text: str) -> bool:
        """Stage 1.5: Fast local check to see if the raw OCR text changed significantly before wasting an LLM call."""
        if not self._last_raw_text:
            return True
            
        # If it's an error, we always want to process it at least once if it wasn't the exact last string
        lower = new_text.lower()
        if "wrong answer" in lower or "compile error" in lower or "runtime error" in lower:
            # We still debounced in LLM Router, but we let it pass Stage 1.5 if the string is vaguely new
            similarity = difflib.SequenceMatcher(None, self._last_raw_text, new_text).ratio()
            return similarity < 0.95
            
        similarity = difflib.SequenceMatcher(None, self._last_raw_text, new_text).ratio()
        # If the raw screen is > 85% similar to the last raw screen, it hasn't changed.
        return similarity < 0.85

    def _is_meaningful_content(self, text: str) -> bool:
        """Filter out UI noise — toolbar buttons, nav elements, dashboard text, short junk."""
        if not text or len(text.strip()) < 20:
            return False
        
        lower = text.lower()
        
        # Reject JARVIS dashboard text
        if "jarvis" in lower and ("aes-256" in lower or "remote session" in lower or "connecting" in lower):
            return False
        
        # Count bracket-wrapped items like [Back] [Forward] [Reload]
        bracket_items = re.findall(r'\[.+?\]', text)
        non_bracket_text = re.sub(r'\[.+?\]', '', text).strip()
        
        # If mostly bracket items and very little real text, it's UI noise
        if len(bracket_items) >= 3 and len(non_bracket_text) < 20:
            return False
        
        # Known UI navigation patterns to reject
        ui_patterns = [
            "back", "forward", "reload", "new tab", "bookmark",
            "open gemini", "open chrome", "downloads", "history",
            "settings", "extensions", "more tools", "remote session",
            "ghost mode", "stealth", "aes-256", "connecting"
        ]
        ui_matches = sum(1 for p in ui_patterns if p in lower)
        if ui_matches >= 3:
            return False
        
        # Must have at least some real words (not just symbols/short fragments)
        words = [w for w in text.split() if len(w) > 2 and not w.startswith('[')]
        if len(words) < 4:
            return False
            
        return True

    def _should_trigger(self, new_text: str) -> bool:
        """
        Check if we should trigger an answer for this screen.
        """
        lower = new_text.lower()
        
        # 1. Job Done Lock: If success detected, lock state.
        if "accepted" in lower or "success" in lower or "passed" in lower:
            if self._state == "ACTIVE":
                print("[Ghost] 🔒 Success detected! Locking to IDLE_MODE.")
                self._state = "IDLE"
            return False
            
        # If IDLE, only wake up if structural similarity to last answered is very low (new problem)
        if self._state == "IDLE":
            if not self._last_answered_text:
                self._state = "ACTIVE"
                return True
            similarity = difflib.SequenceMatcher(None, self._last_answered_text, new_text).ratio()
            if similarity < 0.4:  # Completely different screen
                print("[Ghost] 🔓 New problem detected! Waking up to ACTIVE_MODE.")
                self._state = "ACTIVE"
                return True
            return False
            
        is_error = "wrong answer" in lower or "compile error" in lower or "runtime error" in lower
        
        # If it's an error state, only trigger if we haven't already answered THIS EXACT text
        if is_error:
            if not self._last_answered_text:
                return True
            similarity = difflib.SequenceMatcher(None, self._last_answered_text, new_text).ratio()
            return similarity < 0.95
            
        # Normal question flow:
        if not self._last_answered_text:
            return True
            
        similarity = difflib.SequenceMatcher(None, self._last_answered_text, new_text).ratio()
        if similarity > 0.75:
            return False
            
        return True

    async def _emit(self, data: dict):
        """Send update to dashboard via callback."""
        if self.on_update:
            try:
                await self.on_update(data)
            except Exception:
                pass
