#!/usr/bin/env python3
"""
Build script for packaging captureME into a macOS .app bundle.
Run:
    python build_mac.py
"""

import sys
import os
import subprocess

def main():
    if sys.platform != 'darwin':
        print("Note: PyInstaller native macOS app bundling is typically executed on macOS.")
        print("Validating spec file and structure...")

    spec_file = os.path.join(os.path.dirname(__file__), "captureME_mac.spec")
    if not os.path.exists(spec_file):
        print(f"Error: Spec file not found at {spec_file}")
        sys.exit(1)

    print("Building captureME for macOS using PyInstaller...")
    cmd = [sys.executable, "-m", "PyInstaller", "--clean", spec_file]
    
    try:
        res = subprocess.run(cmd, check=True)
        print("Build completed successfully!")
        print("Output app located at: dist/captureME.app")
    except Exception as e:
        print(f"Build failed or PyInstaller missing: {e}")
        print("To install dependencies on macOS:")
        print("  pip install pyqt5 mss opencv-python sounddevice numpy pyinstaller")

if __name__ == "__main__":
    main()
