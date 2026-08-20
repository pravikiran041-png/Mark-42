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
                 phone_ip: str = "usb", phone_pin: str = "2580",
                 phone_chatgpt_callback=None):
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
        self.phone_chatgpt_callback = phone_chatgpt_callback
        self._is_paused = True
        self._state = "IDLE"
        
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
        await self._emit({"type": "ghost_log", "msg": "👻 Ghost Mode ready. Press Alt+Z to trigger."})
        while self._running:
            try:
                if self._is_paused:
                    await asyncio.sleep(self.scan_interval)
                    continue

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
                    print(f"[Ghost] 🎯 TRIGGERED on new content!", flush=True)
                    try:
                        await self._emit({"type": "ghost_screen_text", "text": current_text})
                    except Exception:
                        pass

                    # 4. Auto-answer if enabled
                    if self._auto_answer:
                        # Prevent loop: immediately mark this text as handled so we don't spam if the answer fails
                        self._last_answered_text = current_text
                        
                        print(f"[Ghost] 🧠 Getting answer via {self.solver_mode}...", flush=True)
                        try:
                            await self._emit({"type": "ghost_log", "msg": f"🧠 Getting answer via {self.solver_mode}..."})
                        except Exception:
                            pass
                        answer = await self._get_answer(current_text)
                        print(f"[Ghost] 📝 Answer received: {repr(answer[:100]) if answer else 'None'}...", flush=True)
                        if answer and not answer.startswith("[Error") and not answer.startswith("Error:"):
                            self._last_answer = answer
                            try:
                                await self._emit({"type": "ghost_answer", "question": current_text[:200], "answer": answer})
                            except Exception:
                                pass
                            # Auto-inject answer silently to cursor on laptop if not 'none'
                            if self.inject_mode.lower() != "none":
                                print(f"[Ghost] ⌨️ Injecting answer ({self.inject_mode} mode)...", flush=True)
                                try:
                                    await self._emit({"type": "ghost_log", "msg": f"⌨️ Injecting answer ({self.inject_mode} mode)..."})
                                except Exception:
                                    pass
                                await self._do_inject(answer)
                                print(f"[Ghost] ✅ Injection complete!", flush=True)
                            else:
                                print(f"[Ghost] 🛑 inject_mode is 'none'. Skipping injection to laptop.", flush=True)
                                try:
                                    await self._emit({"type": "ghost_log", "msg": f"🛑 Answer received on phone. (Injection disabled)"})
                                except Exception:
                                    pass
                        elif answer:
                            print(f"[Ghost] ⚠️ Error answer: {answer[:100]}", flush=True)
                            try:
                                await self._emit({"type": "ghost_log", "msg": f"⚠️ {answer}"})
                            except Exception:
                                pass

                await asyncio.sleep(self.scan_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Ghost] ❌ EXCEPTION: {e}", flush=True)
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
                    model="gemini-3.6-flash",
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
                    model="gemini-3.6-flash",
                    contents=prompt
                )
            )
            return response.text.strip() if response.text else ""

        except Exception as e:
            return f"[AI Error: {e}]"

    async def _get_answer_phone_chatgpt(self, question_text: str) -> str:
        """Runs the Phone ChatGPT Route entirely natively on the phone over WebSocket (No ADB required)."""
        await self._emit({"type": "ghost_log", "msg": "🤖 Asking ChatGPT natively on your phone..."})
        
        if not hasattr(self, 'phone_chatgpt_callback') or not self.phone_chatgpt_callback:
            return "[Error: Native phone ChatGPT automation is not available. Please restart the daemon.]"
            
        try:
            answer = await self.phone_chatgpt_callback(question_text)
            await self._emit({"type": "ghost_log", "msg": "✅ Native ChatGPT response received."})
            return answer
        except Exception as e:
            return f"[Error: Native Phone ChatGPT failed: {e}]"

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
                    # Live abort check
                    if self.inject_mode.lower() == "none":
                        print("[Ghost] 🛑 Typing aborted because inject_mode was changed to 'none'!")
                        break
                        
                    # Panic Button check
                    while self._is_paused:
                        await asyncio.sleep(0.1)
                        if self.inject_mode.lower() == "none":
                            break
                    if self.inject_mode.lower() == "none":
                        break
                        
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
