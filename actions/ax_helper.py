import subprocess
import time
from typing import Any, Callable, Optional


def get_app_ax_root(app_name: str):
    """
    Return AXUIElement application root for a running app (by exact process name).
    Returns None if app is not running or AX root cannot be created.
    """
    try:
        r = subprocess.run(
            ["pgrep", "-x", app_name],
            capture_output=True,
            text=True,
            timeout=2,
        )
        pid_str = (r.stdout or "").strip().splitlines()
        if not pid_str:
            return None
        pid = int(pid_str[0])
    except Exception:
        return None

    try:
        import ApplicationServices as AppSvc

        return AppSvc.AXUIElementCreateApplication(pid)
    except Exception:
        return None


def get_ax_attribute(element, attribute: str) -> Any:
    """Safely fetch an AX attribute value, returning None on failure."""
    try:
        import ApplicationServices as AppSvc

        err, value = AppSvc.AXUIElementCopyAttributeValue(element, attribute, None)
        if err == 0:
            return value
    except Exception:
        return None
    return None


def _get_ax_str(element, attribute: str) -> str:
    v = get_ax_attribute(element, attribute)
    if v is None:
        return ""
    try:
        return str(v)
    except Exception:
        return ""


def find_element_recursive(
    root,
    match_func: Callable[[Any], bool],
    max_depth: int = 10,
):
    """
    Depth-limited DFS over AX tree returning the first match.
    match_func(element) -> bool
    """
    try:
        if not root:
            return None
        if match_func(root):
            return root
        if max_depth <= 0:
            return None
        children = get_ax_attribute(root, "AXChildren") or []
        for child in children:
            found = find_element_recursive(child, match_func, max_depth=max_depth - 1)
            if found is not None:
                return found
    except Exception:
        return None
    return None


def find_all_elements_recursive(
    root,
    match_func: Callable[[Any], bool],
    max_depth: int = 10,
):
    """Depth-limited DFS over AX tree returning all matches."""
    results = []

    def _walk(node, depth: int):
        if not node or depth < 0:
            return
        try:
            if match_func(node):
                results.append(node)
            if depth == 0:
                return
            children = get_ax_attribute(node, "AXChildren") or []
            for c in children:
                _walk(c, depth - 1)
        except Exception:
            return

    _walk(root, max_depth)
    return results


def _get_element_center(element) -> Optional[tuple[int, int]]:
    try:
        import Quartz

        pos = get_ax_attribute(element, "AXPosition")
        size = get_ax_attribute(element, "AXSize")
        if not pos or not size:
            return None
        ok1, pt = Quartz.AXValueGetValue(pos, Quartz.kAXValueCGPointType, None)
        ok2, sz = Quartz.AXValueGetValue(size, Quartz.kAXValueCGSizeType, None)
        if not ok1 or not ok2:
            return None
        cx = int(pt.x + (sz.width / 2))
        cy = int(pt.y + (sz.height / 2))
        if cx == 0 and cy == 0:
            return None
        return (cx, cy)
    except Exception:
        return None


def click_element(element) -> bool:
    """
    Click/press an AX element.
    Tries AXPress first, then coordinate click fallback using the element's center.
    """
    if not element:
        return False
    try:
        import ApplicationServices as AppSvc

        err = AppSvc.AXUIElementPerformAction(element, "AXPress")
        if err == 0:
            return True
    except Exception:
        pass

    center = _get_element_center(element)
    if not center:
        return False
    try:
        import pyautogui

        pyautogui.click(center[0], center[1])
        time.sleep(0.15)
        return True
    except Exception:
        return False


def type_into_element(element, text: str) -> bool:
    """
    Focus element (via click) then paste text via clipboard (Cmd+V).
    Uses pyautogui for the actual keystrokes to remain compatible with WhatsApp's UI.
    """
    if not element:
        return False
    if text is None:
        text = ""

    if not click_element(element):
        return False

    try:
        import pyperclip
        import pyautogui

        pyperclip.copy(text)
        time.sleep(0.05)
        pyautogui.hotkey("command", "v")
        time.sleep(0.1)
        return True
    except Exception:
        return False

