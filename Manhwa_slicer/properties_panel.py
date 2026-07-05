"""
Properties panel — right sidebar showing position/size of selected panel
and allowing numeric edits.
"""
from __future__ import annotations
from typing import Optional, Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QLabel, QLineEdit,
    QFrame, QSizePolicy, QPushButton, QGroupBox
)

from .models import PanelRect


class PropertiesPanel(QWidget):
    """Right sidebar for inspecting and editing selected panel geometry."""

    property_changed = pyqtSignal(object, int, int, int, int, int, int, int, int)
    # panel, old_x, old_y, old_w, old_h, new_x, new_y, new_w, new_h

    label_changed = pyqtSignal(object, str, str)   # panel, old_label, new_label

    def __init__(self, parent=None):
        super().__init__(parent)
        self._panel: Optional[PanelRect] = None
        self._updating = False
        self._build_ui()

    def _build_ui(self):
        self.setMinimumWidth(180)
        self.setMaximumWidth(240)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        header = QLabel("PROPERTIES")
        header.setStyleSheet("color: #888; font-size: 11px; font-weight: bold; letter-spacing: 1px;")
        layout.addWidget(header)

        # Group box
        grp = QGroupBox()
        grp.setStyleSheet("""
            QGroupBox {
                background: #1e1e24;
                border: 1px solid #333;
                border-radius: 4px;
                padding: 8px;
                margin-top: 0px;
            }
        """)
        grp_layout = QGridLayout(grp)
        grp_layout.setSpacing(6)
        grp_layout.setContentsMargins(8, 8, 8, 8)

        lbl_style = "color: #888; font-size: 12px;"
        edit_style = """
            QLineEdit {
                background: #252530;
                border: 1px solid #444;
                border-radius: 3px;
                color: #ddd;
                font-size: 13px;
                padding: 3px 6px;
            }
            QLineEdit:focus { border: 1px solid #5588cc; }
            QLineEdit:disabled { color: #444; background: #1a1a20; }
        """

        def make_label(text):
            l = QLabel(text)
            l.setStyleSheet(lbl_style)
            return l

        def make_edit():
            e = QLineEdit()
            e.setValidator(QIntValidator(-99999, 99999))
            e.setStyleSheet(edit_style)
            e.setFixedHeight(28)
            return e

        # Name / label
        grp_layout.addWidget(make_label("Name"), 0, 0)
        self.edit_label = QLineEdit()
        self.edit_label.setStyleSheet(edit_style)
        self.edit_label.setFixedHeight(28)
        self.edit_label.setPlaceholderText("Auto-numbered")
        grp_layout.addWidget(self.edit_label, 0, 1)

        grp_layout.addWidget(make_label("X"), 1, 0)
        self.edit_x = make_edit()
        grp_layout.addWidget(self.edit_x, 1, 1)

        grp_layout.addWidget(make_label("Y"), 2, 0)
        self.edit_y = make_edit()
        grp_layout.addWidget(self.edit_y, 2, 1)

        grp_layout.addWidget(make_label("Width"), 3, 0)
        self.edit_w = make_edit()
        grp_layout.addWidget(self.edit_w, 3, 1)

        grp_layout.addWidget(make_label("Height"), 4, 0)
        self.edit_h = make_edit()
        grp_layout.addWidget(self.edit_h, 4, 1)

        layout.addWidget(grp)

        # Apply button
        self.btn_apply = QPushButton("Apply")
        self.btn_apply.setFixedHeight(30)
        self.btn_apply.setStyleSheet("""
            QPushButton {
                background: #2a4a80;
                border: none;
                border-radius: 4px;
                color: #fff;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background: #3a5a90; }
            QPushButton:pressed { background: #1a3a70; }
            QPushButton:disabled { background: #2a2a35; color: #555; }
        """)
        self.btn_apply.clicked.connect(self._on_apply)
        layout.addWidget(self.btn_apply)

        layout.addStretch()

        # Connect edits
        for edit in (self.edit_label, self.edit_x, self.edit_y, self.edit_w, self.edit_h):
            edit.returnPressed.connect(self._on_apply)

        self._set_enabled(False)

    def set_panel(self, panel: Optional[PanelRect]) -> None:
        self._panel = panel
        self._updating = True
        if panel:
            self.edit_label.setText(panel.label)
            self.edit_x.setText(str(panel.x))
            self.edit_y.setText(str(panel.y))
            self.edit_w.setText(str(panel.w))
            self.edit_h.setText(str(panel.h))
            self._set_enabled(True)
        else:
            self.edit_label.clear()
            self.edit_x.clear()
            self.edit_y.clear()
            self.edit_w.clear()
            self.edit_h.clear()
            self._set_enabled(False)
        self._updating = False

    def refresh(self) -> None:
        self.set_panel(self._panel)

    def _on_apply(self):
        if self._updating or not self._panel:
            return
        try:
            new_x = int(self.edit_x.text())
            new_y = int(self.edit_y.text())
            new_w = int(self.edit_w.text())
            new_h = int(self.edit_h.text())
        except ValueError:
            return

        new_label = self.edit_label.text().strip()

        # Label change
        if new_label != self._panel.label:
            self.label_changed.emit(self._panel, self._panel.label, new_label)

        # Geometry change
        if (new_x, new_y, new_w, new_h) != (self._panel.x, self._panel.y, self._panel.w, self._panel.h):
            self.property_changed.emit(
                self._panel,
                self._panel.x, self._panel.y, self._panel.w, self._panel.h,
                new_x, new_y, new_w, new_h
            )

    def _set_enabled(self, enabled: bool):
        for w in (self.edit_label, self.edit_x, self.edit_y, self.edit_w, self.edit_h, self.btn_apply):
            w.setEnabled(enabled)
