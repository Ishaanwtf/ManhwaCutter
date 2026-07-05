#!/usr/bin/env python3
"""
build.py — Package Manhwa Slicer into a standalone executable using PyInstaller.

Usage:
    python build.py            # build for current platform
    python build.py --onefile  # single .exe (slower startup)
    python build.py --clean    # clean build artifacts first
"""

import os
import sys
import shutil
import subprocess
import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--onefile", action="store_true",
                        help="Bundle into a single executable")
    parser.add_argument("--clean", action="store_true",
                        help="Remove build/ and dist/ before building")
    args = parser.parse_args()

    if args.clean:
        for d in ("build", "dist", "__pycache__"):
            if os.path.exists(d):
                shutil.rmtree(d)
                print(f"Removed {d}/")

    # Check PyInstaller
    try:
        import PyInstaller
    except ImportError:
        print("Installing PyInstaller…")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "ManhwaSlicer",
        "--windowed",          # no console window
        "--noconfirm",
        "--clean",
    ]

    if args.onefile:
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")

    # Add hidden imports for PIL
    for hi in ("PIL._tkinter_finder", "PIL.Image", "PIL.ImageFile",
               "PyQt6.QtCore", "PyQt6.QtWidgets", "PyQt6.QtGui"):
        cmd += ["--hidden-import", hi]

    cmd.append("main.py")

    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd)
    print("\n✓ Build complete. Output in dist/ManhwaSlicer/")


if __name__ == "__main__":
    main()
