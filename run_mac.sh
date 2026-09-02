#!/bin/bash
# ==========================================
# captureME macOS Executable Launcher
# ==========================================
# Grants execute permissions and launches captureME on macOS

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "Launching captureME on macOS..."

# Check Python 3 installation
if ! command -v python3 &> /dev/null; then
    echo "[!] Error: Python 3 is not installed on this Mac."
    echo "    Please install Python 3 via https://www.python.org or 'brew install python'"
    exit 1
fi

# Ensure required libraries are installed
echo "[*] Verifying python dependencies..."
python3 -m pip install pyqt5 mss opencv-python sounddevice numpy --quiet

# Launch main.py
echo "[*] Starting captureME widget..."
python3 main.py
