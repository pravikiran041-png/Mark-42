"""
stealth.py — JARVIS Stealth Mode

Runs ONLY the dashboard web server — no window, no voice, no mic, no sound.
Completely invisible on the laptop. Control everything from your phone:

  1. Open the dashboard on your phone
  2. Tap 🕵️ to open stealth panel
  3. "Extract Screen Text" reads your laptop screen silently
  4. "Inject Answer" pastes text into the laptop silently

Usage:  python3 stealth.py
   or:  nohup python3 stealth.py &   (run in background, survives terminal close)
"""

import asyncio
import sys
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent
if str(_BASE_DIR) not in sys.path:
    sys.path.insert(0, str(_BASE_DIR))

from dashboard.server import DashboardServer


async def main():
    print("[Stealth] ╔════════════════════════════════════════╗")
    print("[Stealth] ║  JARVIS — Stealth Mode Active          ║")
    print("[Stealth] ║  No window • No voice • No mic         ║")
    print("[Stealth] ║  Dashboard only — control from phone   ║")
    print("[Stealth] ╚════════════════════════════════════════╝")
    print()

    server = DashboardServer()
    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[Stealth] Exiting...")
