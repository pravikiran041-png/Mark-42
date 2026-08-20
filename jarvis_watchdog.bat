@echo off
set DAEMON_SCRIPT=jarvis_daemon.py
set LOG_FILE=daemon.log
set ATTEMPT=0

:loop
REM Check if daemon is running
wmic process where "CommandLine like '%%%DAEMON_SCRIPT%%%' and name='python.exe'" get ProcessId | findstr [0-9] >nul
if %ERRORLEVEL% equ 0 (
    REM Daemon is alive
    timeout /t 10 /nobreak >nul
    goto loop
)

REM Daemon is dead, restart it
set /a ATTEMPT+=1
echo [Watchdog] Daemon is DEAD! Restarting... (attempt %ATTEMPT%) >> %LOG_FILE%
echo [Watchdog] Daemon is DEAD! Restarting... (attempt %ATTEMPT%)

REM Kill zombie ngrok processes which exhaust the free tier limits
taskkill /F /IM ngrok.exe >nul 2>&1

REM Start the daemon in the background
start /B python %DAEMON_SCRIPT% >> %LOG_FILE% 2>&1

echo [Watchdog] Daemon restarted >> %LOG_FILE%
timeout /t 5 /nobreak >nul
goto loop
