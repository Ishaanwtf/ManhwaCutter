#!/usr/bin/env python3
"""
Manhwa Slicer — entry point.
Run with: python main.py
Or package with PyInstaller for a standalone executable.
"""
import sys
import os

# High-DPI support (must be set before QApplication)
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from manhwa_slicer.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Manhwa Slicer")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("ManhwaSlicer")

    # Set default font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    window = MainWindow()

    # Open image from CLI argument if provided
    if len(sys.argv) > 1:
        path = sys.argv[1]
        if os.path.isfile(path):
            window._open_image_path(path)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
