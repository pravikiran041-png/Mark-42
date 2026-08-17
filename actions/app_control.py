import subprocess
import platform

_OS = platform.system()

def _get_app_process_name(app_name: str) -> str:
    """Normalize common app names to their process names."""
    app = app_name.lower()
    mapping = {
        "chrome": "Google Chrome",
        "safari": "Safari",
        "firefox": "Firefox",
        "spotify": "Spotify",
        "discord": "Discord",
        "terminal": "Terminal",
        "finder": "Finder",
        "settings": "System Settings",
    }
    return mapping.get(app, app_name.title())

def open_application(app_name: str) -> str:
    """Open an application by name natively."""
    if _OS == "Darwin":
        try:
            # -a allows opening by application name
            subprocess.run(["open", "-a", app_name], check=True, timeout=5)
            return f"Opened {app_name}."
        except Exception as e:
            return f"Failed to open {app_name}: {e}"
    elif _OS == "Windows":
        try:
            subprocess.run(f"start {app_name}", shell=True, timeout=5)
            return f"Opened {app_name}."
        except Exception as e:
            return f"Failed to open {app_name}: {e}"
    return "OS not supported for open_application."

def close_application(app_name: str, force: bool = False) -> str:
    """Gracefully (or forcefully) quit a specific application."""
    if _OS == "Darwin":
        try:
            proc_name = _get_app_process_name(app_name)
            if force:
                subprocess.run(["killall", proc_name], check=True, timeout=5)
                return f"Force quit {proc_name}."
            else:
                subprocess.run(["osascript", "-e", f'quit app "{proc_name}"'], check=True, timeout=5)
                return f"Gracefully closed {proc_name}."
        except Exception as e:
            return f"Failed to close {app_name}: {e}"
    elif _OS == "Windows":
        try:
            if force:
                subprocess.run(["taskkill", "/F", "/IM", f"{app_name}.exe"], check=True, timeout=5)
            else:
                subprocess.run(["taskkill", "/IM", f"{app_name}.exe"], check=True, timeout=5)
            return f"Closed {app_name}."
        except Exception as e:
            return f"Failed to close {app_name}: {e}"
    return "OS not supported for close_application."

def minimize_application(app_name: str = "") -> str:
    """Minimize a specific application, or the frontmost window if empty."""
    if _OS == "Darwin":
        try:
            if app_name:
                proc_name = _get_app_process_name(app_name)
                script = f'''
                tell application "System Events"
                    set frontmost of process "{proc_name}" to true
                    keystroke "m" using command down
                end tell
                '''
                subprocess.run(["osascript", "-e", script], check=True, timeout=5)
                return f"Minimized {proc_name}."
            else:
                subprocess.run(["osascript", "-e", 'tell application "System Events" to keystroke "m" using command down'], check=True, timeout=5)
                return "Minimized current window."
        except Exception as e:
            return f"Failed to minimize: {e}"
    return "OS not supported for minimize_application."

def close_browser_tab() -> str:
    """Closes the active tab in the active application."""
    if _OS == "Darwin":
        try:
            subprocess.run(["osascript", "-e", 'tell application "System Events" to keystroke "w" using command down'], check=True, timeout=5)
            return "Closed current tab."
        except Exception as e:
            return f"Failed to close tab: {e}"
    return "OS not supported for close_browser_tab."

app_control_tool = {
    "name": "app_control",
    "description": "Manage applications on the computer: open, close, minimize, or close tabs.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "The action to perform: 'open', 'close', 'minimize', 'close_tab'"
            },
            "app_name": {
                "type": "STRING",
                "description": "The name of the application (e.g. 'safari', 'chrome', 'spotify'). Leave empty if action is 'close_tab' or minimizing current window."
            },
            "force": {
                "type": "BOOLEAN",
                "description": "If true, forcefully quits the app (use only if app is frozen or user requests a hard kill)."
            }
        },
        "required": ["action"]
    }
}
