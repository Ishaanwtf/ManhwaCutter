#!/usr/bin/env python3
"""
Main application window.

Layout:
  ┌──────────────────────────────────────────────────────┐
  │  Toolbar                                              │
  ├──────────┬───────────────────────────┬───────────────┤
  │  Panel   │                           │  Properties   │
  │  List    │     ImageCanvas           │  Panel        │
  │  (left)  │     (center)              │  (right)      │
  ├──────────┴───────────────────────────┴───────────────┤
  │  Status bar                                           │
  └──────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QKeySequence, QAction, QIcon, QFont, QColor
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QToolBar, QPushButton, QLabel, QSplitter, QStatusBar,
    QFileDialog, QMessageBox, QFrame, QSizePolicy, QTabWidget
)

from .models import PanelRect, Project, ExportSettings
from .image_loader import TiledImageLoader
from .commands import (
    CommandStack, AddPanelCommand, DeletePanelCommand, MovePanelCommand,
    ResizePanelCommand, DuplicatePanelCommand, ReorderPanelCommand,
    SetLabelCommand
)
from .canvas import ImageCanvas
from .panel_list import PanelListWidget
from .properties_panel import PropertiesPanel
from .export_dialog import ExportDialog
from .exporter import export_panels
# NEW: TTS Studio
from .tts.tts_widget import TTSWidget
# NEW: Smart Background Eraser
from .magic_wand_eraser import WandDialog


SUPPORTED_IMAGES = "Images (*.png *.jpg *.jpeg *.webp);;All Files (*)"
PROJECT_FILTER   = "Manhwa Slicer Project (*.msp);;All Files (*)"

STYLESHEET = """
QMainWindow, QWidget {
    background: #1a1a22;
    color: #ddd;
    font-family: "Segoe UI", "SF Pro Text", system-ui, sans-serif;
    font-size: 13px;
}
QToolBar {
    background: #14141c;
    border-bottom: 1px solid #2a2a38;
    spacing: 4px;
    padding: 4px 8px;
}
QToolBar QLabel {
    color: #888;
    font-size: 12px;
    padding: 0 4px;
}
QStatusBar {
    background: #14141c;
    border-top: 1px solid #2a2a38;
    color: #666;
    font-size: 12px;
}
QSplitter::handle {
    background: #2a2a38;
    width: 3px;
}
QMessageBox {
    background: #1e1e28;
    color: #ddd;
}
QTabWidget::pane {
    border: none;
    background: #1a1a22;
}
QTabBar::tab {
    background: #2a2a35;
    padding: 6px 16px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}
QTabBar::tab:selected {
    background: #3a4a80;
    color: white;
}
QTabBar::tab:hover {
    background: #353545;
}
"""

TOOLBAR_BTN_STYLE = """
    QPushButton {
        background: #252530;
        border: 1px solid #3a3a4a;
        border-radius: 4px;
        color: #ccc;
        font-size: 12px;
        padding: 5px 12px;
        min-width: 64px;
    }
    QPushButton:hover  { background: #303040; border-color: #5050aa; }
    QPushButton:pressed { background: #1e1e2a; }
    QPushButton:disabled { color: #444; background: #1e1e28; }
"""

ICON_BTN_STYLE = """
    QPushButton {
        background: #252530;
        border: 1px solid #3a3a4a;
        border-radius: 4px;
        color: #ccc;
        font-size: 18px;
        padding: 4px 8px;
        min-width: 32px;
    }
    QPushButton:hover  { background: #303040; }
    QPushButton:pressed { background: #1e1e2a; }
    QPushButton:disabled { color: #333; }
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Manhwa Slicer")
        self.resize(1280, 900)

        self.project = Project()
        self.loader: Optional[TiledImageLoader] = None
        self.cmd_stack = CommandStack()
        self.cmd_stack.on_change = self._on_stack_changed
        self._export_worker = None

        self.setStyleSheet(STYLESHEET)
        self._build_ui()
        self._build_menu()
        self._connect_signals()
        self._update_toolbar_state()

    # ── UI Construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        # Toolbar
        tb = QToolBar("Main Toolbar")
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(tb)

        def tb_btn(text, tooltip=None):
            b = QPushButton(text)
            b.setStyleSheet(TOOLBAR_BTN_STYLE)
            b.setFixedHeight(30)
            if tooltip:
                b.setToolTip(tooltip)
            tb.addWidget(b)
            return b

        def sep():
            f = QFrame()
            f.setFrameShape(QFrame.Shape.VLine)
            f.setFixedWidth(1)
            f.setStyleSheet("background: #333; margin: 4px 2px;")
            tb.addWidget(f)

        self.btn_open   = tb_btn("📂 Open", "Open image (Ctrl+O)")
        self.btn_save   = tb_btn("💾 Save", "Save project (Ctrl+S)")
        self.btn_load   = tb_btn("📁 Load", "Load project (Ctrl+Shift+O)")
        sep()
        self.btn_export = tb_btn("⬇ Export", "Export panels (Ctrl+E)")
        sep()
        self.btn_undo   = tb_btn("↩ Undo", "Undo (Ctrl+Z)")
        self.btn_redo   = tb_btn("↪ Redo", "Redo (Ctrl+Y)")
        sep()
        self.btn_wand = tb_btn("✨ Smart Eraser", "Click-based background eraser (Ctrl+M)")
        sep()
        self.btn_fit    = tb_btn("↔ Fit", "Fit to width (F)")
        self.btn_zoom1  = tb_btn("1:1", "Reset zoom (0)")

        # Zoom label
        self._lbl_zoom = QLabel("100%")
        self._lbl_zoom.setStyleSheet("color: #888; font-size: 12px; min-width: 48px; padding: 0 6px;")
        tb.addWidget(self._lbl_zoom)

        # Spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        # Help hint
        hint = QLabel("Draw: drag on canvas  |  Move: drag panel  |  Resize: drag corners  |  Pan: middle-click or Space+drag")
        hint.setStyleSheet("color: #555; font-size: 11px;")
        tb.addWidget(hint)

        # Central area: Tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.setMovable(False)

        # --- Slicer Tab (original UI) ---
        slicer_widget = QWidget()
        slicer_layout = QVBoxLayout(slicer_widget)
        slicer_layout.setContentsMargins(0, 0, 0, 0)
        slicer_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(3)

        # Left: panel list
        self.panel_list_widget = PanelListWidget()
        splitter.addWidget(self.panel_list_widget)

        # Center: canvas
        self.canvas = ImageCanvas()
        splitter.addWidget(self.canvas)

        # Right: properties
        self.props_panel = PropertiesPanel()
        splitter.addWidget(self.props_panel)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([200, 900, 200])

        slicer_layout.addWidget(splitter)
        self.tab_widget.addTab(slicer_widget, "Slicer")

        # --- TTS Studio Tab ---
        self.tts_widget = TTSWidget()
        self.tab_widget.addTab(self.tts_widget, "TTS Studio")

        self.setCentralWidget(self.tab_widget)

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self._status_perm = QLabel("Ready — open an image to begin")
        self._status_perm.setStyleSheet("color: #666;")
        self.status.addPermanentWidget(self._status_perm)
        self._status_temp = QLabel("")
        self.status.addWidget(self._status_temp)

    def _build_menu(self):
        mb = self.menuBar()
        mb.setStyleSheet("""
            QMenuBar { background: #14141c; color: #bbb; }
            QMenuBar::item:selected { background: #252535; }
            QMenu { background: #1e1e28; color: #ccc; border: 1px solid #333; }
            QMenu::item:selected { background: #2a4a80; }
            QMenu::separator { height: 1px; background: #333; margin: 2px 0; }
        """)

        # File menu
        file_menu = mb.addMenu("File")
        self._add_action(file_menu, "Open Image…",    "Ctrl+O", self.open_image)
        self._add_action(file_menu, "Save Project",   "Ctrl+S", self.save_project)
        self._add_action(file_menu, "Save Project As…","Ctrl+Shift+S", self.save_project_as)
        self._add_action(file_menu, "Load Project…",  "Ctrl+Shift+O", self.load_project)
        file_menu.addSeparator()
        self._add_action(file_menu, "Export Panels…", "Ctrl+E", self.show_export_dialog)
        file_menu.addSeparator()
        self._add_action(file_menu, "Quit",            "Ctrl+Q", self.close)

        # Edit menu
        edit_menu = mb.addMenu("Edit")
        self._undo_action = self._add_action(edit_menu, "Undo", "Ctrl+Z", self.undo)
        self._redo_action = self._add_action(edit_menu, "Redo", "Ctrl+Y", self.redo)
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Delete Panel",   "Delete", self.delete_selected)
        self._add_action(edit_menu, "Duplicate Panel","Ctrl+D",  self.duplicate_selected)
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Select All",     "Ctrl+A",  self._select_first)

        # Tools menu
        tools_menu = mb.addMenu("Tools")
        self._add_action(tools_menu, "Smart Background Eraser…", "Ctrl+M", self.show_wand_eraser)

        # View menu
        view_menu = mb.addMenu("View")
        self._add_action(view_menu, "Fit to Width", "F",         self.canvas.fit_to_width)
        self._add_action(view_menu, "Reset Zoom",   "0",         self.canvas.reset_zoom)
        self._add_action(view_menu, "Zoom In",      "Ctrl+=",    self._zoom_in)
        self._add_action(view_menu, "Zoom Out",     "Ctrl+-",    self._zoom_out)

    def _add_action(self, menu, text, shortcut, slot):
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    def _connect_signals(self):
        # Toolbar buttons
        self.btn_open.clicked.connect(self.open_image)
        self.btn_save.clicked.connect(self.save_project)
        self.btn_load.clicked.connect(self.load_project)
        self.btn_export.clicked.connect(self.show_export_dialog)
        self.btn_undo.clicked.connect(self.undo)
        self.btn_redo.clicked.connect(self.redo)
        self.btn_wand.clicked.connect(self.show_wand_eraser)
        self.btn_fit.clicked.connect(self.canvas.fit_to_width)
        self.btn_zoom1.clicked.connect(self.canvas.reset_zoom)

        # Canvas callbacks
        self.canvas.on_request_add_panel   = self._request_add_panel
        self.canvas.on_request_move_panel  = self._request_move_panel
        self.canvas.on_request_resize_panel = self._request_resize_panel
        self.canvas.on_drop_image          = self._open_image_path

        self.canvas.panels_changed.connect(self._on_panels_changed)
        self.canvas.selection_changed.connect(self._on_canvas_selection)
        self.canvas.zoom_changed.connect(self._on_zoom_changed)
        self.canvas.status_message.connect(self._set_status_temp)

        # Panel list
        self.panel_list_widget.panel_selected.connect(self._on_list_selection)
        self.panel_list_widget.panel_delete_requested.connect(self._delete_panel)
        self.panel_list_widget.panel_duplicate_requested.connect(self._duplicate_panel)
        self.panel_list_widget.panel_reorder_requested.connect(self._reorder_panel)

        # Properties
        self.props_panel.property_changed.connect(self._on_props_changed)
        self.props_panel.label_changed.connect(self._on_label_changed)

    # ── File operations ────────────────────────────────────────────────────────

    def open_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Image", "", SUPPORTED_IMAGES)
        if path:
            self._open_image_path(path)

    def _open_image_path(self, path: str):
        try:
            if self.loader:
                self.loader.close()
            loader = TiledImageLoader(path)
            loader.open()
            self.loader = loader
            self.project.image_path = path
            self.cmd_stack.clear()
            self.project.panels.clear()
            self.canvas.load_image(loader)
            self.canvas.set_panels(self.project.panels)
            self.panel_list_widget.set_panels(self.project.panels)
            self.canvas.fit_to_width()
            self._set_status(f"Opened: {Path(path).name}  "
                             f"({loader.img_width} × {loader.img_height} px)")
            self._update_toolbar_state()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not open image:\n{e}")

    def save_project(self):
        if not self.project.image_path:
            return
        if not hasattr(self, "_project_path") or not self._project_path:
            self.save_project_as()
            return
        try:
            self.project.save(self._project_path)
            self._set_status_temp(f"Project saved: {self._project_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not save project:\n{e}")

    def save_project_as(self):
        if not self.project.image_path:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Project As", "", PROJECT_FILTER)
        if path:
            if not path.endswith(".msp"):
                path += ".msp"
            self._project_path = path
            try:
                self.project.save(path)
                self._set_status_temp(f"Project saved: {path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not save project:\n{e}")

    def load_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Project", "", PROJECT_FILTER)
        if not path:
            return
        try:
            proj = Project.load(path)
            self._project_path = path
            # Load image
            img_path = proj.image_path
            if not Path(img_path).exists():
                # Ask user to locate it
                new_path, _ = QFileDialog.getOpenFileName(
                    self, f"Locate missing image: {Path(img_path).name}", "", SUPPORTED_IMAGES
                )
                if not new_path:
                    return
                proj.image_path = new_path
                img_path = new_path

            if self.loader:
                self.loader.close()
            loader = TiledImageLoader(img_path)
            loader.open()
            self.loader = loader
            self.project = proj
            self.cmd_stack.clear()
            self.canvas.load_image(loader)
            self.canvas.set_panels(self.project.panels)
            self.panel_list_widget.set_panels(self.project.panels)
            self.canvas.fit_to_width()
            self._set_status(f"Loaded project: {path}  |  {len(proj.panels)} panels")
            self._update_toolbar_state()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not load project:\n{e}")

    # ── Export ─────────────────────────────────────────────────────────────────

    def show_export_dialog(self):
        if not self.loader or not self.project.panels:
            QMessageBox.information(self, "Export", "No panels to export. Draw some panels first.")
            return

        # Generate auto-labels before export
        for i, p in enumerate(self.project.panels):
            if not p.label:
                p.label = f"panel_{i+1:03d}"

        dlg = ExportDialog(self.project.panels, self.project.export_settings, self)
        dlg.export_requested.connect(self._do_export)
        dlg.exec()

    def _do_export(self, panels, settings):
        if not self.loader:
            return
        dlg = self.sender().parent() if hasattr(self.sender(), "parent") else None

        def on_progress(i, total):
            if dlg:
                from PyQt6.QtCore import QMetaObject, Qt as _Qt
                # Safe cross-thread UI update via queued connection
                QTimer.singleShot(0, lambda: dlg.show_progress(i, total))

        def on_done(result):
            def _finish():
                if dlg:
                    dlg.show_done(result.exported, result.errors)
                if result.errors:
                    msgs = "\n".join(f"  {lbl}: {err}" for lbl, err in result.errors[:5])
                    QMessageBox.warning(self, "Export Warnings",
                                        f"{len(result.errors)} export error(s):\n{msgs}")
                else:
                    self._set_status_temp(f"✓ Exported {len(result.exported)} panels → {settings.output_dir}")
            QTimer.singleShot(0, _finish)

        self._export_worker = export_panels(
            self.loader, panels, settings, on_progress, on_done
        )

    # ── Smart Background Eraser ──────────────────────────────────────────────

    def show_wand_eraser(self):
        if not self.loader:
            QMessageBox.information(self, "No Image", "Please open an image first.")
            return
        selected = self.canvas.get_selected()
        if not selected:
            QMessageBox.information(self, "No Panel", "Please select a panel first.")
            return
        dlg = WandDialog(
            loader=self.loader,
            panel=selected,
            parent=self
        )
        dlg.exec()

    # ── Panel commands ─────────────────────────────────────────────────────────

    def _request_add_panel(self, panel: PanelRect):
        cmd = AddPanelCommand(self.project.panels, panel)
        self.cmd_stack.push(cmd)
        self._refresh_all()
        self.canvas.select_panel(panel)
        self.panel_list_widget.select_panel(panel)

    def _request_move_panel(self, panel, ox, oy, nx, ny):
        from .commands import MovePanelCommand
        cmd = MovePanelCommand(panel, ox, oy, nx, ny)
        # Already applied; just record in stack without re-executing
        cmd.execute = lambda: None   # no-op since move already happened
        self.cmd_stack._undo_stack.append(cmd)
        self.cmd_stack._redo_stack.clear()
        self.cmd_stack._notify()
        self._refresh_all()

    def _request_resize_panel(self, panel, ox, oy, ow, oh, nx, ny, nw, nh):
        from .commands import ResizePanelCommand
        cmd = ResizePanelCommand(panel, ox, oy, ow, oh, nx, ny, nw, nh)
        cmd.execute = lambda: None
        self.cmd_stack._undo_stack.append(cmd)
        self.cmd_stack._redo_stack.clear()
        self.cmd_stack._notify()
        self._refresh_all()

    def _delete_panel(self, panel: PanelRect):
        if panel not in self.project.panels:
            return
        cmd = DeletePanelCommand(self.project.panels, panel)
        self.cmd_stack.push(cmd)
        self._refresh_all()
        self.canvas.select_panel(None)

    def delete_selected(self):
        sel = self.canvas.get_selected()
        if sel:
            self._delete_panel(sel)

    def _duplicate_panel(self, panel: PanelRect):
        idx = self.project.panels.index(panel) if panel in self.project.panels else -1
        cmd = DuplicatePanelCommand(self.project.panels, panel, idx)
        self.cmd_stack.push(cmd)
        self._refresh_all()
        self.canvas.select_panel(cmd.new_panel)
        self.panel_list_widget.select_panel(cmd.new_panel)

    def duplicate_selected(self):
        sel = self.canvas.get_selected()
        if sel:
            self._duplicate_panel(sel)

    def _reorder_panel(self, from_idx: int, to_idx: int):
        cmd = ReorderPanelCommand(self.project.panels, from_idx, to_idx)
        self.cmd_stack.push(cmd)
        self._refresh_all()

    def _on_props_changed(self, panel, ox, oy, ow, oh, nx, ny, nw, nh):
        cmd = ResizePanelCommand(panel, ox, oy, ow, oh, nx, ny, nw, nh)
        self.cmd_stack.push(cmd)
        self._refresh_all()

    def _on_label_changed(self, panel, old_label, new_label):
        cmd = SetLabelCommand(panel, old_label, new_label)
        self.cmd_stack.push(cmd)
        self._refresh_all()

    def undo(self):
        self.cmd_stack.undo()
        self._refresh_all()
        sel = self.canvas.get_selected()
        if sel and sel not in self.project.panels:
            self.canvas.select_panel(None)

    def redo(self):
        self.cmd_stack.redo()
        self._refresh_all()

    def _select_first(self):
        if self.project.panels:
            self.canvas.select_panel(self.project.panels[0])
            self.panel_list_widget.select_panel(self.project.panels[0])

    # ── Signal handlers ────────────────────────────────────────────────────────

    def _on_panels_changed(self):
        self._refresh_panel_list()
        self.props_panel.refresh()

    def _on_canvas_selection(self, panel):
        self.panel_list_widget.select_panel(panel)
        self.props_panel.set_panel(panel)

    def _on_list_selection(self, panel):
        self.canvas.select_panel(panel)
        self.props_panel.set_panel(panel)
        if panel:
            # Scroll canvas to show panel
            self._scroll_to_panel(panel)

    def _on_zoom_changed(self, zoom: float):
        self._lbl_zoom.setText(f"{zoom * 100:.0f}%")

    def _on_stack_changed(self):
        self._update_toolbar_state()

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _refresh_all(self):
        self.panel_list_widget.refresh()
        self.canvas.update()
        self.props_panel.refresh()
        self._update_toolbar_state()

    def _refresh_panel_list(self):
        self.panel_list_widget.refresh()

    def _update_toolbar_state(self):
        has_image = self.loader is not None
        has_panels = bool(self.project.panels)
        self.btn_save.setEnabled(has_image)
        self.btn_export.setEnabled(has_image and has_panels)
        self.btn_undo.setEnabled(self.cmd_stack.can_undo())
        self.btn_redo.setEnabled(self.cmd_stack.can_redo())

        undo_desc = self.cmd_stack.undo_description()
        redo_desc = self.cmd_stack.redo_description()
        self.btn_undo.setToolTip(f"Undo: {undo_desc}" if undo_desc else "Nothing to undo")
        self.btn_redo.setToolTip(f"Redo: {redo_desc}" if redo_desc else "Nothing to redo")

    def _set_status(self, msg: str):
        self._status_perm.setText(msg)

    def _set_status_temp(self, msg: str):
        self._status_temp.setText(msg)
        QTimer.singleShot(4000, lambda: self._status_temp.setText(""))

    def _zoom_in(self):
        from PyQt6.QtCore import QPointF
        self.canvas._set_zoom(self.canvas.zoom * 1.25,
                              QPointF(self.canvas.width() / 2, self.canvas.height() / 2))
        self.canvas.update()

    def _zoom_out(self):
        from PyQt6.QtCore import QPointF
        self.canvas._set_zoom(self.canvas.zoom / 1.25,
                              QPointF(self.canvas.width() / 2, self.canvas.height() / 2))
        self.canvas.update()

    def _scroll_to_panel(self, panel: PanelRect):
        """Nudge the canvas offset so the panel is visible."""
        # center of panel in canvas coords
        cx = panel.x * self.canvas.zoom + self.canvas._offset.x()
        cy = panel.y * self.canvas.zoom + self.canvas._offset.y()
        cw = self.canvas.width()
        ch = self.canvas.height()
        # Only scroll if outside viewport
        margin = 40
        dx, dy = 0.0, 0.0
        if cx < margin:
            dx = margin - cx
        elif cx > cw - margin:
            dx = (cw - margin) - cx
        if cy < margin:
            dy = margin - cy
        elif cy > ch - margin:
            dy = (ch - margin) - cy
        if dx or dy:
            from PyQt6.QtCore import QPointF
            self.canvas._offset += QPointF(dx, dy)
            self.canvas.update()

    # ── Close ──────────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self.loader:
            self.loader.close()
        if self._export_worker and self._export_worker.is_alive():
            self._export_worker.cancel()
        super().closeEvent(event)