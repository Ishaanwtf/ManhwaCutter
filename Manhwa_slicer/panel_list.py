"""
Panel list sidebar — shows all panels with number, position, size.
Supports selection, reordering via drag-drop, and rename.
"""
from __future__ import annotations
from typing import Optional, Callable

from PyQt6.QtCore import Qt, pyqtSignal, QMimeData
from PyQt6.QtGui import QFont, QColor, QIcon, QDrag
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QFrame, QSizePolicy, QAbstractItemView
)

from .models import PanelRect


class PanelListItem(QListWidgetItem):
    def __init__(self, panel: PanelRect, index: int):
        super().__init__()
        self.panel = panel
        self.refresh(index)

    def refresh(self, index: int):
        label = self.panel.label if self.panel.label else f"Panel {index + 1}"
        self.setText(label)
        self.setToolTip(
            f"Position: ({self.panel.x}, {self.panel.y})\n"
            f"Size: {self.panel.w} × {self.panel.h}"
        )


class PanelListWidget(QWidget):
    """
    Left sidebar showing all panels.
    Emits signals when the user interacts.
    """
    panel_selected = pyqtSignal(object)      # PanelRect or None
    panel_delete_requested = pyqtSignal(object)
    panel_duplicate_requested = pyqtSignal(object)
    panel_reorder_requested = pyqtSignal(int, int)   # from_idx, to_idx

    def __init__(self, parent=None):
        super().__init__(parent)
        self._panels: list[PanelRect] = []
        self._updating = False
        self._build_ui()

    def _build_ui(self):
        self.setMinimumWidth(180)
        self.setMaximumWidth(260)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # Header
        header = QLabel("PANELS")
        header.setStyleSheet("color: #888; font-size: 11px; font-weight: bold; letter-spacing: 1px;")
        layout.addWidget(header)

        # List
        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.setStyleSheet("""
            QListWidget {
                background: #1e1e24;
                border: 1px solid #333;
                border-radius: 4px;
                color: #ddd;
                font-size: 13px;
            }
            QListWidget::item {
                padding: 6px 8px;
                border-bottom: 1px solid #2a2a32;
            }
            QListWidget::item:selected {
                background: #2a4a80;
                color: #fff;
            }
            QListWidget::item:hover {
                background: #252530;
            }
        """)
        self.list_widget.currentItemChanged.connect(self._on_selection_changed)
        self.list_widget.model().rowsMoved.connect(self._on_rows_moved)
        layout.addWidget(self.list_widget)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        self.btn_dup = QPushButton("⧉ Dup")
        self.btn_del = QPushButton("✕ Del")
        for btn in (self.btn_dup, self.btn_del):
            btn.setFixedHeight(26)
            btn.setStyleSheet("""
                QPushButton {
                    background: #2a2a35;
                    border: 1px solid #444;
                    border-radius: 3px;
                    color: #ccc;
                    font-size: 12px;
                    padding: 0 8px;
                }
                QPushButton:hover { background: #353545; }
                QPushButton:pressed { background: #1a1a25; }
                QPushButton:disabled { color: #555; }
            """)
        self.btn_dup.clicked.connect(self._on_duplicate)
        self.btn_del.clicked.connect(self._on_delete)
        btn_row.addWidget(self.btn_dup)
        btn_row.addWidget(self.btn_del)
        layout.addLayout(btn_row)

        # Count label
        self.count_label = QLabel("0 panels")
        self.count_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self.count_label)

        self._set_buttons_enabled(False)

    def set_panels(self, panels: list[PanelRect]) -> None:
        self._panels = panels
        self.refresh()

    def refresh(self) -> None:
        self._updating = True
        current_panel = self._current_panel()
        self.list_widget.clear()
        for i, p in enumerate(self._panels):
            item = PanelListItem(p, i)
            self.list_widget.addItem(item)
        # Restore selection
        if current_panel and current_panel in self._panels:
            idx = self._panels.index(current_panel)
            self.list_widget.setCurrentRow(idx)
        self.count_label.setText(f"{len(self._panels)} panel{'s' if len(self._panels) != 1 else ''}")
        self._updating = False

    def select_panel(self, panel: Optional[PanelRect]) -> None:
        self._updating = True
        if panel is None or panel not in self._panels:
            self.list_widget.clearSelection()
        else:
            idx = self._panels.index(panel)
            self.list_widget.setCurrentRow(idx)
        self._updating = False
        self._set_buttons_enabled(panel is not None)

    def _current_panel(self) -> Optional[PanelRect]:
        item = self.list_widget.currentItem()
        if item and isinstance(item, PanelListItem):
            return item.panel
        return None

    def _on_selection_changed(self, current, previous):
        if self._updating:
            return
        if current and isinstance(current, PanelListItem):
            self._set_buttons_enabled(True)
            self.panel_selected.emit(current.panel)
        else:
            self._set_buttons_enabled(False)
            self.panel_selected.emit(None)

    def _on_rows_moved(self, parent, start, end, dest, dest_row):
        if self._updating:
            return
        # Qt updates the list visually; we need to sync _panels
        # The visual order after drop IS the new order
        # Reconstruct order from visible items
        new_order = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if isinstance(item, PanelListItem):
                new_order.append(item.panel)
        # Find what moved
        if new_order != self._panels:
            # Emit from/to for undo support
            from_idx = start
            to_idx = dest_row if dest_row <= start else dest_row - 1
            self.panel_reorder_requested.emit(from_idx, to_idx)

    def _on_duplicate(self):
        panel = self._current_panel()
        if panel:
            self.panel_duplicate_requested.emit(panel)

    def _on_delete(self):
        panel = self._current_panel()
        if panel:
            self.panel_delete_requested.emit(panel)

    def _set_buttons_enabled(self, enabled: bool):
        self.btn_dup.setEnabled(enabled)
        self.btn_del.setEnabled(enabled)
