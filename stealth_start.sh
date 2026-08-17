#!/bin/bash
# stealth_start.sh - macOS launchd wrapper script for JARVIS Server

# Export paths required for python and adb
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

# Go to project directory
cd "/Users/mac/Documents/Mark-L-main" || exit 1

# Start the server without buffering output
exec python3 -u dashboard/server.py
