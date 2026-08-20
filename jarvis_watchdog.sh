#!/bin/bash
# ─────────────────────────────────────────────────
# JARVIS Auto-Heal Watchdog
# Monitors the daemon and ngrok, restarts if dead.
# ─────────────────────────────────────────────────
cd "$(dirname "$0")"

DAEMON_SCRIPT="jarvis_daemon.py"
LOG_FILE="daemon.log"
WATCHDOG_INTERVAL=10  # Check every 10 seconds
MAX_RESTARTS=100      # Safety cap to prevent infinite restarts
restart_count=0

echo "[Watchdog] 🐕 JARVIS Watchdog started at $(date)" >> "$LOG_FILE"

while true; do
    # Check if daemon is alive
    if ! pgrep -f "$DAEMON_SCRIPT" > /dev/null; then
        restart_count=$((restart_count + 1))
        
        if [ "$restart_count" -gt "$MAX_RESTARTS" ]; then
            echo "[Watchdog] ❌ Max restarts ($MAX_RESTARTS) reached. Giving up." >> "$LOG_FILE"
            exit 1
        fi

        echo "[Watchdog] ⚠️ Daemon is DEAD! Restarting... (attempt $restart_count) at $(date)" >> "$LOG_FILE"
        
        # Kill any zombie ngrok processes first
        killall -9 ngrok 2>/dev/null
        sleep 2
        
        # Restart the daemon
        nohup python3 -u "$DAEMON_SCRIPT" >> "$LOG_FILE" 2>&1 &
        
        echo "[Watchdog] ✅ Daemon restarted (PID: $!)" >> "$LOG_FILE"
        
        # Wait a bit before next check to let it start up
        sleep 10
    else
        # Daemon is alive, reset restart counter after 5 min of stability
        if [ "$restart_count" -gt 0 ]; then
            # Only reset after it's been stable for a while
            restart_count=0
        fi
    fi
    
    sleep "$WATCHDOG_INTERVAL"
done
