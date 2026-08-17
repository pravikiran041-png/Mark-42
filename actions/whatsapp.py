"""
whatsapp_desktop.py — Advanced WhatsApp Desktop Automation via macOS Accessibility API

Uses `ApplicationServices` (AXUIElement) via `ax_helper.py` to directly interact with the UI tree.
No AppleScript keystrokes, no coordinate hardcoding, no phone numbers needed.
"""

import time
import subprocess
import pyautogui
import pyperclip

# Import accessibility helper from JARVIS backend
try:
    from actions.ax_helper import (
        click_element,
        find_all_elements_recursive,
        find_element_recursive,
        get_app_ax_root,
        get_ax_attribute,
        type_into_element,
    )
except ImportError:
    pass

def _get_whatsapp_ax_root():
    return get_app_ax_root("WhatsApp")

def _get_whatsapp_ax_window():
    app = _get_whatsapp_ax_root()
    if not app:
        return None
    win = get_ax_attribute(app, "AXFocusedWindow")
    if win:
        return win
    wins = get_ax_attribute(app, "AXWindows") or []
    if wins:
        return wins[0]
    return app

def _element_label_text(element) -> str:
    parts = [
        str(get_ax_attribute(element, "AXLabel") or ""),
        str(get_ax_attribute(element, "AXTitle") or ""),
        str(get_ax_attribute(element, "AXDescription") or ""),
        str(get_ax_attribute(element, "AXPlaceholderValue") or ""),
        str(get_ax_attribute(element, "AXValue") or ""),
        str(get_ax_attribute(element, "AXRoleDescription") or ""),
        str(get_ax_attribute(element, "AXIdentifier") or ""),
    ]
    return " ".join([p for p in parts if p]).strip()

def _find_element_by_label(root, label_keywords: list):
    if not root or not label_keywords:
        return None
    lowered = [k.lower() for k in label_keywords if k]
    def match(el) -> bool:
        txt = _element_label_text(el).lower()
        if not txt:
            return False
        return any(k in txt for k in lowered)
    return find_element_recursive(root, match, max_depth=12)

def _find_element_by_role(root, role: str):
    if not root or not role:
        return []
    def match(el) -> bool:
        r = str(get_ax_attribute(el, "AXRole") or "")
        return r == role
    return find_all_elements_recursive(root, match, max_depth=12)

def _retry_find(fn, tries: int = 3, gap: float = 0.5):
    last = None
    for _ in range(max(1, tries)):
        try:
            last = fn()
            if last:
                return last
        except Exception:
            last = None
        time.sleep(gap)
    return last

def _open_whatsapp():
    try:
        subprocess.run(["open", "-a", "WhatsApp"], capture_output=True, text=True, timeout=5)
    except Exception:
        pass
    deadline = time.time() + 5.0
    while time.time() < deadline:
        root = _get_whatsapp_ax_root()
        if root is not None:
            return True
        time.sleep(0.25)
    return False

def _activate_whatsapp():
    try:
        subprocess.run(
            ["osascript", "-e", 'tell application "WhatsApp" to activate'],
            capture_output=True, text=True, timeout=3,
        )
        time.sleep(0.3)
    except Exception:
        pass

def _looks_like_result_item(text: str) -> bool:
    if not text:
        return False
    t = text.strip().lower()
    if len(t) < 2:
        return False
    bad = ("search", "new chat", "start new chat", "message", "type a message", "send", "voice call", "video call", "calls", "settings")
    return not any(b in t for b in bad)

def _find_first_search_result(root, receiver: str):
    receiver_l = (receiver or "").strip().lower()
    if receiver_l:
        hit = _retry_find(lambda: _find_element_by_label(root, [receiver]), tries=2, gap=0.35)
        if hit: return hit
    for role in ["AXRow", "AXCell", "AXGroup"]:
        items = _find_element_by_role(root, role)
        for it in items[:50]:
            txt = _element_label_text(it)
            if receiver_l and receiver_l in txt.lower(): return it
    for role in ["AXStaticText", "AXButton"]:
        items = _find_element_by_role(root, role)
        for it in items[:120]:
            txt = _element_label_text(it)
            if receiver_l and receiver_l in txt.lower(): return it
            if _looks_like_result_item(txt): return it
    return None

def _search_and_open_contact(receiver: str):
    if not receiver:
        return False
    if not _open_whatsapp():
        return False
    _activate_whatsapp()
    
    root = _get_whatsapp_ax_window()
    if not root:
        return False

    search_keywords = ["Search", "search", "Search or start", "New chat", "Start new chat"]
    search_el = _retry_find(lambda: _find_element_by_label(root, search_keywords))
    if not search_el:
        return False

    click_element(search_el)
    time.sleep(0.2)
    try:
        pyautogui.hotkey("command", "a")
        time.sleep(0.05)
    except Exception:
        pass

    type_into_element(search_el, receiver)
    time.sleep(2.0)

    root = _get_whatsapp_ax_window()
    if not root: return False

    contact_el = _retry_find(lambda: _find_first_search_result(root, receiver), tries=3, gap=0.5)
    if not contact_el:
        try:
            pyautogui.press("down")
            time.sleep(0.1)
            pyautogui.press("enter")
            return True
        except Exception:
            return False

    if not click_element(contact_el):
        try:
            pyautogui.press("down")
            time.sleep(0.1)
            pyautogui.press("enter")
        except Exception:
            return False

    time.sleep(1.5)
    return True

def _ax_element_y(element) -> float:
    try:
        import Quartz
        pos = get_ax_attribute(element, "AXPosition")
        if not pos: return -1.0
        ok, pt = Quartz.AXValueGetValue(pos, Quartz.kAXValueCGPointType, None)
        if not ok: return -1.0
        return float(pt.y)
    except Exception:
        return -1.0

def _is_editable_text(el) -> bool:
    try:
        role = str(get_ax_attribute(el, "AXRole") or "")
        if role not in ("AXTextArea", "AXTextField"): return False
        editable = get_ax_attribute(el, "AXEditable")
        enabled = get_ax_attribute(el, "AXEnabled")
        if editable is False or enabled is False: return False
        return True
    except Exception:
        return False

def _find_message_input_element(root):
    if not root: return None
    candidates = []
    for role in ("AXTextArea", "AXTextField"):
        for el in _find_element_by_role(root, role)[:200]:
            if not _is_editable_text(el): continue
            txt = _element_label_text(el).lower()
            placeholder = str(get_ax_attribute(el, "AXPlaceholderValue") or "").lower()
            desc = str(get_ax_attribute(el, "AXDescription") or "").lower()
            score = 0
            if "type a message" in placeholder or "message" in placeholder: score += 100
            if "type a message" in desc or "message" in desc: score += 80
            if "message" in txt: score += 40
            y = _ax_element_y(el)
            candidates.append((score, y, el))
    if not candidates: return None
    candidates.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return candidates[0][2]

def send_message(receiver: str, message: str) -> str:
    if not _search_and_open_contact(receiver):
        return f"Could not open chat with {receiver}, Sir."
    
    _activate_whatsapp()
    root = _get_whatsapp_ax_window()
    if not root:
        return "WhatsApp is not open, Sir."

    input_el = _retry_find(lambda: _find_message_input_element(root))
    if not input_el:
        try:
            pyautogui.press("esc")
            time.sleep(0.15)
            for _ in range(8):
                pyautogui.press("tab")
                time.sleep(0.08)
        except Exception:
            return "Could not find the message input field, Sir."
    else:
        click_element(input_el)
        time.sleep(0.2)

    try:
        pyperclip.copy(message)
        time.sleep(0.2)
        pyautogui.hotkey("command", "v")
        time.sleep(0.2)
    except Exception:
        return "Could not type the message, Sir."

    time.sleep(0.3)
    try:
        pyautogui.press("enter")
    except Exception:
        return "Failed to press Enter, Sir."

    return f"Message sent to {receiver} via WhatsApp Desktop, Sir."

def make_call(receiver: str, call_type: str = "voice") -> str:
    video = call_type.lower() == "video"
    if not _search_and_open_contact(receiver):
        return f"Could not open chat with {receiver}, Sir."

    time.sleep(0.8)
    root = _get_whatsapp_ax_window()
    if not root:
        return "WhatsApp is not open, Sir."

    if video:
        keywords = ["Video call", "video call", "Video Call", "Start video call"]
    else:
        keywords = ["Voice call", "voice call", "Voice Call", "Start voice call"]

    btn = _retry_find(lambda: _find_element_by_label(root, keywords))
    if not btn:
        buttons = _find_element_by_role(root, "AXButton")
        for b in buttons:
            t = _element_label_text(b).lower()
            if video and ("video" in t and "call" in t):
                btn = b
                break
            if not video and ("voice" in t and "call" in t):
                btn = b
                break

    if not btn:
        return f"Could not find the {'video' if video else 'voice'} call button, Sir."

    if not click_element(btn):
        return f"Could not click the call button for {receiver}, Sir."

    return f"{'Video' if video else 'Voice'} calling {receiver} on WhatsApp, Sir."

def check_incoming_call() -> bool:
    """
    Checks if there is an incoming WhatsApp call ringing.
    Returns True if an incoming call is detected.
    """
    root = _get_whatsapp_ax_window()
    if not root:
        return False
    
    # Looking for Accept button or incoming call text
    accept_btn = _find_element_by_label(root, ["Accept", "accept"])
    if accept_btn:
        return True
    
    # Alternative: check for text that says "Incoming call"
    for role in ["AXStaticText"]:
        items = _find_element_by_role(root, role)
        for it in items[:120]:
            txt = _element_label_text(it).lower()
            if "incoming call" in txt or "ringing" in txt:
                return True
    return False

def answer_call() -> dict:
    """
    Answers an incoming WhatsApp call.
    """
    _activate_whatsapp()
    root = _get_whatsapp_ax_window()
    if not root:
        return {"success": False, "message": "WhatsApp is not open, Sir."}
        
    accept_btn = _retry_find(lambda: _find_element_by_label(root, ["Accept", "accept"]))
    if not accept_btn:
        return {"success": False, "message": "No incoming call found to answer, Sir."}
        
    if click_element(accept_btn):
        return {"success": True, "message": "Call answered successfully, Sir."}
    return {"success": False, "message": "Failed to click Accept button, Sir."}

def end_call() -> dict:
    """
    Ends an active WhatsApp call or declines an incoming one.
    """
    _activate_whatsapp()
    root = _get_whatsapp_ax_window()
    if not root:
        return {"success": False, "message": "WhatsApp is not open, Sir."}
        
    end_btn = _retry_find(lambda: _find_element_by_label(root, ["Decline", "decline", "End call", "end call"]))
    if not end_btn:
        return {"success": False, "message": "Could not find Decline/End Call button, Sir."}
        
    if click_element(end_btn):
        return {"success": True, "message": "Call ended successfully, Sir."}
    return {"success": False, "message": "Failed to click End Call button, Sir."}
