"""
Export dialog — lets the user configure output directory, format, and
choose which panels to export.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QLineEdit, QRadioButton, QButtonGroup,
    QProgressBar, QCheckBox, QGroupBox, QSpinBox, QDialogButtonBox,
    QListWidget, QListWidgetItem, QAbstractItemView, QFrame
)

from .models import PanelRect, ExportSettings


class ExportDialog(QDialog):
    """Modal export configuration + progress dialog."""

    export_requested = pyqtSignal(list, object)  # panels, ExportSettings

    def __init__(self, panels: list[PanelRect], settings: ExportSettings, parent=None):
        super().__init__(parent)
        self._panels = panels
        self._settings = settings
        self.setWindowTitle("Export Panels")
        self.setMinimumWidth(480)
        self.setModal(True)
        self._build_ui()
        self._populate_from_settings()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        btn_style = """
            QPushButton {
                background: #2a2a35;
                border: 1px solid #555;
                border-radius: 4px;
                color: #ddd;
                padding: 6px 14px;
                font-size: 13px;
            }
            QPushButton:hover { background: #353545; }
        """
        edit_style = """
            QLineEdit {
                background: #1e1e28;
                border: 1px solid #444;
                border-radius: 4px;
                color: #ddd;
                font-size: 13px;
                padding: 5px 8px;
            }
        """
        grp_style = """
            QGroupBox {
                color: #aaa;
                font-size: 12px;
                font-weight: bold;
                border: 1px solid #333;
                border-radius: 4px;
                margin-top: 8px;
                padding: 8px;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; }
        """

        # Output directory
        dir_grp = QGroupBox("Output Directory")
        dir_grp.setStyleSheet(grp_style)
        dir_layout = QHBoxLayout(dir_grp)
        self.edit_dir = QLineEdit()
        self.edit_dir.setStyleSheet(edit_style)
        self.edit_dir.setPlaceholderText("Choose output folder...")
        self.btn_browse = QPushButton("Browse…")
        self.btn_browse.setStyleSheet(btn_style)
        self.btn_browse.clicked.connect(self._browse_dir)
        dir_layout.addWidget(self.edit_dir)
        dir_layout.addWidget(self.btn_browse)
        layout.addWidget(dir_grp)

        # Format
        fmt_grp = QGroupBox("Export Format")
        fmt_grp.setStyleSheet(grp_style)
        fmt_layout = QHBoxLayout(fmt_grp)
        self.radio_png  = QRadioButton("PNG  (lossless)")
        self.radio_webp = QRadioButton("WebP")
        self.radio_png.setChecked(True)
        for r in (self.radio_png, self.radio_webp):
            r.setStyleSheet("color: #ccc; font-size: 13px;")
        self.spin_webp_q = QSpinBox()
        self.spin_webp_q.setRange(1, 100)
        self.spin_webp_q.setValue(90)
        self.spin_webp_q.setSuffix("% quality")
        self.spin_webp_q.setStyleSheet("background:#1e1e28; color:#ddd; border:1px solid #444; border-radius:3px; padding:3px;")
        lbl_q = QLabel("WebP quality:")
        lbl_q.setStyleSheet("color:#888; font-size:12px;")
        fmt_layout.addWidget(self.radio_png)
        fmt_layout.addWidget(self.radio_webp)
        fmt_layout.addStretch()
        fmt_layout.addWidget(lbl_q)
        fmt_layout.addWidget(self.spin_webp_q)
        self.radio_webp.toggled.connect(lambda c: self.spin_webp_q.setEnabled(c))
        self.spin_webp_q.setEnabled(False)
        layout.addWidget(fmt_grp)

        # Panel selection
        sel_grp = QGroupBox("Panels to Export")
        sel_grp.setStyleSheet(grp_style)
        sel_layout = QVBoxLayout(sel_grp)
        self.radio_all = QRadioButton("Export all panels")
        self.radio_sel = QRadioButton("Export selected panels:")
        self.radio_all.setChecked(True)
        for r in (self.radio_all, self.radio_sel):
            r.setStyleSheet("color: #ccc; font-size: 13px;")
        self.panel_list = QListWidget()
        self.panel_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.panel_list.setMaximumHeight(140)
        self.panel_list.setStyleSheet("""
            QListWidget {
                background: #1e1e24;
                border: 1px solid #333;
                color: #ccc;
                font-size: 12px;
            }
            QListWidget::item:selected { background: #2a4a80; }
        """)
        for i, p in enumerate(self._panels):
            label = p.label if p.label else f"Panel {i + 1}"
            self.panel_list.addItem(f"{i+1:3d}. {label}  ({p.w}×{p.h})")
        self.radio_sel.toggled.connect(self.panel_list.setEnabled)
        self.panel_list.setEnabled(False)
        sel_layout.addWidget(self.radio_all)
        sel_layout.addWidget(self.radio_sel)
        sel_layout.addWidget(self.panel_list)
        layout.addWidget(sel_grp)

        # Progress
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        self.progress.setStyleSheet("""
            QProgressBar { background: #1e1e28; border: 1px solid #444; border-radius: 3px; color: #fff; text-align: center; }
            QProgressBar::chunk { background: #3a6ac0; border-radius: 2px; }
        """)
        layout.addWidget(self.progress)
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(self.status_lbl)

        # Buttons
        btn_box = QHBoxLayout()
        self.btn_export = QPushButton("Export")
        self.btn_export.setFixedHeight(34)
        self.btn_export.setStyleSheet("""
            QPushButton {
                background: #2a5aaa;
                border: none;
                border-radius: 4px;
                color: #fff;
                font-size: 14px;
                font-weight: bold;
                padding: 0 20px;
            }
            QPushButton:hover { background: #3a6abb; }
            QPushButton:disabled { background: #2a2a35; color: #555; }
        """)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setFixedHeight(34)
        self.btn_cancel.setStyleSheet(btn_style)
        self.btn_export.clicked.connect(self._on_export)
        self.btn_cancel.clicked.connect(self.reject)
        btn_box.addStretch()
        btn_box.addWidget(self.btn_cancel)
        btn_box.addWidget(self.btn_export)
        layout.addLayout(btn_box)

    def _populate_from_settings(self):
        self.edit_dir.setText(self._settings.output_dir)
        if self._settings.format == "WEBP":
            self.radio_webp.setChecked(True)
        self.spin_webp_q.setValue(self._settings.webp_quality)

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory",
                                             self.edit_dir.text() or str(Path.home()))
        if d:
            self.edit_dir.setText(d)

    def _on_export(self):
        out_dir = self.edit_dir.text().strip()
        if not out_dir:
            self.status_lbl.setText("⚠ Please choose an output directory.")
            return

        self._settings.output_dir = out_dir
        self._settings.format = "WEBP" if self.radio_webp.isChecked() else "PNG"
        self._settings.webp_quality = self.spin_webp_q.value()

        if self.radio_all.isChecked():
            panels = self._panels
        else:
            selected_rows = {item.row() for item in self.panel_list.selectedItems()}
            if not selected_rows:
                self.status_lbl.setText("⚠ No panels selected.")
                return
            panels = [self._panels[r] for r in sorted(selected_rows)]

        self.export_requested.emit(panels, self._settings)

    def show_progress(self, current: int, total: int):
        self.progress.setVisible(True)
        self.progress.setMaximum(total)
        self.progress.setValue(current)
        self.status_lbl.setText(f"Exporting {current + 1} / {total}…")
        self.btn_export.setEnabled(False)

    def show_done(self, exported: list, errors: list):
        self.progress.setValue(self.progress.maximum())
        msg = f"✓ Exported {len(exported)} panel(s)."
        if errors:
            msg += f"  {len(errors)} error(s)."
        self.status_lbl.setText(msg)
        self.btn_cancel.setText("Close")
        self.btn_export.setEnabled(True)
