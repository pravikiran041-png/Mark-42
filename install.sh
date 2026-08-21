#!/bin/bash
echo "=================================================="
echo "  JARVIS Auto-Installer for Mac"
echo "=================================================="
echo ""

# Check for Homebrew
if ! command -v brew &> /dev/null; then
    echo "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# Check for Python 3.12
if ! command -v python3.12 &> /dev/null; then
    echo "Installing Python 3.12..."
    brew install python@3.12
fi

# Create virtual environment
echo "Creating isolated virtual environment..."
python3.12 -m venv .venv
source .venv/bin/activate

# Install requirements
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt pynput websockets ngrok

# Run setup wizard
echo "Running First-Time Setup Wizard..."
python setup_wizard.py

echo ""
echo "=================================================="
echo "  INSTALLATION COMPLETE!"
echo "  To start JARVIS from now on, just run:"
echo "  ./start_ghost.sh"
echo "=================================================="
