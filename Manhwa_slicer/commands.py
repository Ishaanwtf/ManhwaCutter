"""
Command pattern for undo/redo support.
Each user action that modifies the panel list is wrapped in a Command object.
"""
from __future__ import annotations
from typing import Callable, Any
import copy


class Command:
    """Base reversible command."""
    description: str = ""

    def execute(self): ...
    def undo(self): ...


class CommandStack:
    """Linear undo/redo stack with configurable depth."""

    def __init__(self, max_depth: int = 100):
        self._undo_stack: list[Command] = []
        self._redo_stack: list[Command] = []
        self._max = max_depth
        self.on_change: Callable[[], None] | None = None

    def push(self, cmd: Command) -> None:
        cmd.execute()
        self._undo_stack.append(cmd)
        self._redo_stack.clear()
        if len(self._undo_stack) > self._max:
            self._undo_stack.pop(0)
        self._notify()

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        cmd = self._undo_stack.pop()
        cmd.undo()
        self._redo_stack.append(cmd)
        self._notify()
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        cmd = self._redo_stack.pop()
        cmd.execute()
        self._undo_stack.append(cmd)
        self._notify()
        return True

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def undo_description(self) -> str:
        return self._undo_stack[-1].description if self._undo_stack else ""

    def redo_description(self) -> str:
        return self._redo_stack[-1].description if self._redo_stack else ""

    def clear(self) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._notify()

    def _notify(self):
        if self.on_change:
            self.on_change()


# ── Concrete commands ──────────────────────────────────────────────────────────

class AddPanelCommand(Command):
    description = "Add panel"

    def __init__(self, panels: list, panel):
        self._panels = panels
        self._panel = panel

    def execute(self):
        self._panels.append(self._panel)

    def undo(self):
        if self._panel in self._panels:
            self._panels.remove(self._panel)


class DeletePanelCommand(Command):
    description = "Delete panel"

    def __init__(self, panels: list, panel):
        self._panels = panels
        self._panel = panel
        self._idx = panels.index(panel)

    def execute(self):
        if self._panel in self._panels:
            self._panels.remove(self._panel)

    def undo(self):
        self._panels.insert(self._idx, self._panel)


class MovePanelCommand(Command):
    description = "Move panel"

    def __init__(self, panel, old_x: int, old_y: int, new_x: int, new_y: int):
        self._panel = panel
        self._ox, self._oy = old_x, old_y
        self._nx, self._ny = new_x, new_y

    def execute(self):
        self._panel.x = self._nx
        self._panel.y = self._ny

    def undo(self):
        self._panel.x = self._ox
        self._panel.y = self._oy


class ResizePanelCommand(Command):
    description = "Resize panel"

    def __init__(self, panel, old_x, old_y, old_w, old_h, new_x, new_y, new_w, new_h):
        self._panel = panel
        self._old = (old_x, old_y, old_w, old_h)
        self._new = (new_x, new_y, new_w, new_h)

    def execute(self):
        self._panel.x, self._panel.y, self._panel.w, self._panel.h = self._new

    def undo(self):
        self._panel.x, self._panel.y, self._panel.w, self._panel.h = self._old


class DuplicatePanelCommand(Command):
    description = "Duplicate panel"

    def __init__(self, panels: list, source_panel, after_idx: int):
        self._panels = panels
        self._copy = source_panel.copy()
        self._idx = after_idx + 1

    def execute(self):
        self._panels.insert(self._idx, self._copy)

    def undo(self):
        if self._copy in self._panels:
            self._panels.remove(self._copy)

    @property
    def new_panel(self):
        return self._copy


class ReorderPanelCommand(Command):
    description = "Reorder panels"

    def __init__(self, panels: list, from_idx: int, to_idx: int):
        self._panels = panels
        self._from = from_idx
        self._to = to_idx

    def execute(self):
        item = self._panels.pop(self._from)
        self._panels.insert(self._to, item)

    def undo(self):
        item = self._panels.pop(self._to)
        self._panels.insert(self._from, item)


class SetLabelCommand(Command):
    description = "Rename panel"

    def __init__(self, panel, old_label: str, new_label: str):
        self._panel = panel
        self._old = old_label
        self._new = new_label

    def execute(self):
        self._panel.label = self._new

    def undo(self):
        self._panel.label = self._old
