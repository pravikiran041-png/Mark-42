#!/bin/bash
cd "$(dirname "$0")"

# Check if the watchdog is already running
if pgrep -f "jarvis_watchdog.sh" > /dev/null; then
    echo "JARVIS Ghost Daemon is already running (watchdog active)!"
    exit 0
fi

# Check if just the daemon is running (no watchdog)
if pgrep -f "jarvis_daemon.py" > /dev/null; then
    echo "JARVIS Ghost Daemon is already running!"
    exit 0
fi

echo "Starting JARVIS Ghost Daemon with Auto-Heal Watchdog..."
nohup bash jarvis_watchdog.sh > /dev/null 2>&1 &
echo "Daemon started! Mobile Server is now online."
echo "You can now connect from your phone and activate Ghost Mode even if JARVIS is closed."
echo "The watchdog will automatically restart the daemon if it ever crashes."
