@echo off
echo ==================================================
echo   JARVIS Auto-Installer for Windows
echo ==================================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.12 from python.org and check "Add to PATH".
    pause
    exit /b
)

echo Creating isolated virtual environment...
python -m venv .venv
call .venv\Scripts\activate.bat

echo Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt pynput websockets ngrok
pip install pywinauto pywin32 comtypes pycaw win10toast

echo Running First-Time Setup Wizard...
python setup_wizard.py

echo.
echo ==================================================
echo   INSTALLATION COMPLETE!
echo   To start JARVIS from now on, just double-click:
echo   start_ghost.bat
echo ==================================================
pause
