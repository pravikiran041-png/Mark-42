@echo off
echo Starting JARVIS Ghost Daemon for Windows...

REM Kill existing processes to prevent conflicts
taskkill /F /IM ngrok.exe >nul 2>&1
wmic process where "CommandLine like '%jarvis_daemon.py%' and name='python.exe'" call terminate >nul 2>&1
wmic process where "CommandLine like '%jarvis_watchdog.bat%' and name='cmd.exe'" call terminate >nul 2>&1

REM Start the watchdog script in a new hidden window (or minimized)
start /min "JARVIS_WATCHDOG" cmd /c "jarvis_watchdog.bat"

echo Daemon and Watchdog started! Mobile Server is now online.
echo You can now connect from your phone.
