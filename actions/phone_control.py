"""
Phone Control — Phase 5 Redux (Native Accessibility)
No longer uses ADB or scrcpy. All control goes through the WebSocket
to the JARVIS Accessibility Service running natively on the phone.
Screen viewing uses the native MediaProjection stream stored in mobile_server.
"""

def phone_control(parameters: dict, player=None, speak=None) -> str:
    action = parameters.get("action", "").lower()

    if action == "connect" or action == "mirror":
        return (
            "The phone is automatically connected and streaming its screen natively. "
            "Use the 'see' tool with angle='screen' to view what's on the phone."
        )

    elif action == "tap":
        x = parameters.get("x")
        y = parameters.get("y")
        if x is None or y is None:
            return "I need x and y coordinates to tap on the phone screen."
        try:
            from core.mobile_server import get_instance
            server = get_instance()
            if server:
                server.send_control("tap", x=float(x), y=float(y))
                return f"Tapped at ({x}, {y}) on the phone screen."
            return "Phone is not connected."
        except Exception as e:
            return f"Tap failed: {e}"

    elif action == "swipe":
        x1 = parameters.get("x1")
        y1 = parameters.get("y1")
        x2 = parameters.get("x2")
        y2 = parameters.get("y2")
        if None in (x1, y1, x2, y2):
            return "I need x1, y1, x2, y2 coordinates to perform a swipe."
        try:
            from core.mobile_server import get_instance
            server = get_instance()
            if server:
                server.send_control("swipe", x1=float(x1), y1=float(y1), x2=float(x2), y2=float(y2))
                return f"Swiped from ({x1},{y1}) to ({x2},{y2}) on the phone."
            return "Phone is not connected."
        except Exception as e:
            return f"Swipe failed: {e}"

    elif action == "screenshot":
        try:
            from core.mobile_server import get_instance
            server = get_instance()
            if server:
                frame = server.get_latest_frame()
                if frame:
                    return f"Screenshot captured ({len(frame)} bytes). Use the 'see' tool to analyze it."
                return "No screen frame available yet. Make sure the phone app is streaming."
            return "Phone is not connected."
        except Exception as e:
            return f"Screenshot failed: {e}"

    elif action == "execute":
        command = parameters.get("command", "")
        if not command:
            return "I need a specific command to execute."
        # For safety, we no longer run ADB shell commands. 
        # All control goes through the Accessibility Service.
        return (
            "Direct shell commands are no longer supported. "
            "Use tap/swipe actions instead, which work natively through the Accessibility Service."
        )
            
    return f"Unknown phone control action: {action}. Supported: tap, swipe, screenshot"
