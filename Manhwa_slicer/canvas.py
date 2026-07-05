"""
ImageCanvas — the central viewport widget.

Architecture:
  - Uses QPainter on a QWidget (no OpenGL needed; Qt's raster pipeline is fast enough
    for 768-wide images and handles RGBA tiles efficiently).
  - Coordinate spaces:
      image-space  : pixel coordinates of the source image (integers)
      canvas-space : widget pixel coordinates (integers), = image-space * zoom + offset
  - Tiles are rendered only if their canvas-space bounding box intersects the widget rect.
  - Panel rectangles are drawn over the image in canvas-space.
  - Hit-testing for drag handles uses canvas-space.

Mouse interaction modes:
  NONE      – hover / idle
  DRAW      – drag-creating a new rectangle
  MOVE      – dragging an existing rect body
  RESIZE    – dragging a resize handle
  PAN       – middle-button or space+drag pan
"""
from __future__ import annotations

import math
from enum import Enum, auto
from typing import Optional

from PyQt6.QtCore import (
    Qt, QRect, QRectF, QPointF, QPoint, QSize, pyqtSignal, QTimer
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QFontMetrics,
    QPixmap, QImage, QCursor, QKeyEvent, QWheelEvent,
    QMouseEvent, QPainterPath
)
from PyQt6.QtWidgets import QWidget, QSizePolicy, QApplication

from .models import PanelRect
from .image_loader import TiledImageLoader

# ── Constants ─────────────────────────────────────────────────────────────────

HANDLE_SIZE = 8          # px in canvas-space
HANDLE_HIT  = 12         # slightly larger hit area
MIN_RECT_SIZE = 4        # minimum panel size in image-space pixels
ZOOM_MIN = 0.02
ZOOM_MAX = 32.0

# Colors
COL_PANEL_FILL   = QColor(80, 160, 255, 40)
COL_PANEL_BORDER = QColor(80, 160, 255, 220)
COL_SELECTED_FILL   = QColor(255, 180, 50, 60)
COL_SELECTED_BORDER = QColor(255, 180, 50, 255)
COL_LABEL_BG    = QColor(30, 30, 30, 180)
COL_LABEL_TEXT  = QColor(255, 255, 255)
COL_DRAW_FILL   = QColor(100, 200, 100, 40)
COL_DRAW_BORDER = QColor(100, 200, 100, 220)
COL_CANVAS_BG   = QColor(30, 30, 34)
COL_IMAGE_BORDER = QColor(60, 60, 70)

HANDLE_POSITIONS = [
    "tl", "tc", "tr",
    "ml",        "mr",
    "bl", "bc", "br",
]


class InteractionMode(Enum):
    NONE   = auto()
    DRAW   = auto()
    MOVE   = auto()
    RESIZE = auto()
    PAN    = auto()


class ImageCanvas(QWidget):
    """Central tiled image canvas with pan/zoom and panel editing."""

    # Emitted when panel list or selection changes
    panels_changed = pyqtSignal()
    selection_changed = pyqtSignal(object)   # Optional[PanelRect]
    zoom_changed = pyqtSignal(float)
    status_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)

        # Image state
        self._loader: Optional[TiledImageLoader] = None
        self._tile_pixmaps: dict[int, QPixmap] = {}  # tile_index → QPixmap

        # View state
        self._zoom: float = 1.0
        self._offset: QPointF = QPointF(0, 0)  # canvas origin of image top-left

        # Panel state (shared reference to project panels list)
        self._panels: list[PanelRect] = []
        self._selected: Optional[PanelRect] = None

        # Interaction state
        self._mode = InteractionMode.NONE
        self._drag_start_canvas: Optional[QPointF] = None
        self._drag_start_image: Optional[QPointF] = None
        self._drag_panel_origin: tuple[int, int] = (0, 0)
        self._drag_resize_handle: str = ""
        self._drag_resize_origin: tuple[int, int, int, int] = (0, 0, 0, 0)
        self._draw_rect: Optional[PanelRect] = None  # in-progress draw
        self._pan_start: Optional[QPointF] = None
        self._pan_offset_start: Optional[QPointF] = None
        self._space_held = False

        # Callbacks (set by parent)
        self.on_request_add_panel: Optional[callable] = None   # (PanelRect) -> None
        self.on_request_move_panel: Optional[callable] = None  # (panel, ox, oy, nx, ny)
        self.on_request_resize_panel: Optional[callable] = None

        # Font
        self._label_font = QFont("Segoe UI", 9)
        self._label_font.setBold(True)

        # Prefetch timer
        self._prefetch_timer = QTimer(self)
        self._prefetch_timer.setSingleShot(True)
        self._prefetch_timer.timeout.connect(self._prefetch_visible)

    # ── Public API ─────────────────────────────────────────────────────────────

    def load_image(self, loader: TiledImageLoader) -> None:
        self._loader = loader
        self._tile_pixmaps.clear()
        self._fit_to_width()
        self.update()

    def set_panels(self, panels: list[PanelRect]) -> None:
        """Bind to the project's panel list (shared reference)."""
        self._panels = panels
        self._selected = None
        self.update()

    def select_panel(self, panel: Optional[PanelRect]) -> None:
        self._selected = panel
        self.update()
        self.selection_changed.emit(panel)

    def get_selected(self) -> Optional[PanelRect]:
        return self._selected

    def fit_to_width(self) -> None:
        self._fit_to_width()
        self.update()

    def reset_zoom(self) -> None:
        self._set_zoom(1.0, QPointF(self.width() / 2, self.height() / 2))
        self.update()

    @property
    def zoom(self) -> float:
        return self._zoom

    # ── Coordinate helpers ─────────────────────────────────────────────────────

    def _img_to_canvas(self, ix: float, iy: float) -> QPointF:
        return QPointF(ix * self._zoom + self._offset.x(),
                       iy * self._zoom + self._offset.y())

    def _canvas_to_img(self, cx: float, cy: float) -> QPointF:
        return QPointF((cx - self._offset.x()) / self._zoom,
                       (cy - self._offset.y()) / self._zoom)

    def _panel_to_canvas_rect(self, p: PanelRect) -> QRectF:
        tl = self._img_to_canvas(p.x, p.y)
        return QRectF(tl.x(), tl.y(), p.w * self._zoom, p.h * self._zoom)

    def _fit_to_width(self) -> None:
        if not self._loader:
            return
        iw = self._loader.img_width
        available = max(100, self.width() - 20)
        self._zoom = available / iw
        self._zoom = max(ZOOM_MIN, min(ZOOM_MAX, self._zoom))
        # Center horizontally
        canvas_img_w = iw * self._zoom
        self._offset = QPointF((self.width() - canvas_img_w) / 2, 10)
        self.zoom_changed.emit(self._zoom)

    def _set_zoom(self, new_zoom: float, anchor: QPointF) -> None:
        new_zoom = max(ZOOM_MIN, min(ZOOM_MAX, new_zoom))
        img_pt = self._canvas_to_img(anchor.x(), anchor.y())
        self._zoom = new_zoom
        # Keep img_pt under anchor
        self._offset = QPointF(
            anchor.x() - img_pt.x() * self._zoom,
            anchor.y() - img_pt.y() * self._zoom,
        )
        self.zoom_changed.emit(self._zoom)

    # ── Tile pixmap cache ──────────────────────────────────────────────────────

    def _get_tile_pixmap(self, tile_index: int) -> Optional[QPixmap]:
        if tile_index in self._tile_pixmaps:
            return self._tile_pixmaps[tile_index]
        if not self._loader:
            return None
        tile = self._loader.get_tile(tile_index)
        if tile is None:
            return None
        img = tile.image
        # PIL RGBA → QImage
        data = img.tobytes("raw", "RGBA")
        qimg = QImage(data, img.width, img.height, img.width * 4,
                      QImage.Format.Format_RGBA8888)
        px = QPixmap.fromImage(qimg)
        # Cap cache to avoid OOM (simple FIFO)
        if len(self._tile_pixmaps) > 25:
            oldest = next(iter(self._tile_pixmaps))
            del self._tile_pixmaps[oldest]
        self._tile_pixmaps[tile_index] = px
        return px

    def _prefetch_visible(self) -> None:
        if not self._loader:
            return
        y0_img = max(0, self._canvas_to_img(0, 0).y())
        y1_img = min(self._loader.img_height, self._canvas_to_img(0, self.height()).y())
        from .image_loader import TILE_HEIGHT
        t0 = max(0, int(y0_img) // TILE_HEIGHT - 1)
        t1 = min(self._loader.num_tiles - 1, int(y1_img) // TILE_HEIGHT + 1)
        self._loader.prefetch_tiles_async(list(range(t0, t1 + 1)))

    # ── Paint ──────────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # Background
        painter.fillRect(self.rect(), COL_CANVAS_BG)

        if not self._loader:
            painter.setPen(QColor(120, 120, 130))
            painter.setFont(QFont("Segoe UI", 14))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "Drop an image here or use File → Open Image")
            return

        self._draw_image(painter)
        self._draw_panels(painter)
        if self._draw_rect:
            self._draw_in_progress(painter)

    def _draw_image(self, painter: QPainter) -> None:
        assert self._loader
        from .image_loader import TILE_HEIGHT

        iw = self._loader.img_width
        ih = self._loader.img_height

        # Image border shadow
        canvas_rect = QRectF(
            self._offset.x() - 1, self._offset.y() - 1,
            iw * self._zoom + 2, ih * self._zoom + 2
        )
        painter.setPen(QPen(COL_IMAGE_BORDER, 1))
        painter.drawRect(canvas_rect)

        # Determine visible tile range
        vy0 = (0 - self._offset.y()) / self._zoom
        vy1 = (self.height() - self._offset.y()) / self._zoom
        vy0 = max(0, int(vy0))
        vy1 = min(ih, int(vy1) + 1)

        t_start = vy0 // TILE_HEIGHT
        t_end   = (vy1 - 1) // TILE_HEIGHT if vy1 > 0 else 0

        for ti in range(t_start, t_end + 1):
            px = self._get_tile_pixmap(ti)
            if px is None:
                continue
            tile = self._loader.get_tile(ti)
            if tile is None:
                continue
            dst = QRectF(
                self._offset.x(),
                self._offset.y() + tile.y_start * self._zoom,
                iw * self._zoom,
                (tile.y_end - tile.y_start) * self._zoom,
            )
            painter.drawPixmap(dst.toRect(), px)

    def _draw_panels(self, painter: QPainter) -> None:
        for i, panel in enumerate(self._panels):
            is_sel = (panel is self._selected)
            r = self._panel_to_canvas_rect(panel)

            fill = COL_SELECTED_FILL if is_sel else COL_PANEL_FILL
            border = COL_SELECTED_BORDER if is_sel else COL_PANEL_BORDER

            painter.fillRect(r, fill)
            pen = QPen(border, 1.5 if not is_sel else 2.0)
            painter.setPen(pen)
            painter.drawRect(r)

            # Label
            display = panel.label if panel.label else f"Panel {i + 1}"
            self._draw_label(painter, r, display, is_sel)

            # Handles for selected
            if is_sel:
                self._draw_handles(painter, r)

    def _draw_label(self, painter: QPainter, r: QRectF, text: str, selected: bool):
        painter.setFont(self._label_font)
        fm = QFontMetrics(self._label_font)
        tw = fm.horizontalAdvance(text) + 8
        th = fm.height() + 4
        lx = r.x() + 4
        ly = r.y() + 4
        bg = QColor(40, 40, 255, 200) if selected else QColor(20, 20, 20, 180)
        painter.fillRect(QRectF(lx, ly, tw, th), bg)
        painter.setPen(COL_LABEL_TEXT)
        painter.drawText(int(lx + 4), int(ly + th - 4), text)

    def _draw_handles(self, painter: QPainter, r: QRectF):
        painter.setPen(QPen(COL_SELECTED_BORDER, 1))
        painter.setBrush(QBrush(QColor(255, 255, 255, 220)))
        for hx, hy in self._handle_centers(r).values():
            hs = HANDLE_SIZE
            painter.drawRect(QRectF(hx - hs/2, hy - hs/2, hs, hs))

    def _draw_in_progress(self, painter: QPainter):
        if not self._draw_rect:
            return
        r = self._panel_to_canvas_rect(self._draw_rect)
        painter.fillRect(r, COL_DRAW_FILL)
        pen = QPen(COL_DRAW_BORDER, 1.5, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRect(r)

    @staticmethod
    def _handle_centers(r: QRectF) -> dict[str, tuple[float, float]]:
        x0, y0, x1, y1 = r.x(), r.y(), r.right(), r.bottom()
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        return {
            "tl": (x0, y0), "tc": (mx, y0), "tr": (x1, y0),
            "ml": (x0, my),                  "mr": (x1, my),
            "bl": (x0, y1), "bc": (mx, y1), "br": (x1, y1),
        }

    def _hit_handle(self, r: QRectF, pt: QPointF) -> Optional[str]:
        hs = HANDLE_HIT
        for name, (hx, hy) in self._handle_centers(r).items():
            if abs(pt.x() - hx) <= hs/2 and abs(pt.y() - hy) <= hs/2:
                return name
        return None

    # ── Mouse events ───────────────────────────────────────────────────────────

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else (1 / 1.15)
        anchor = QPointF(event.position())
        self._set_zoom(self._zoom * factor, anchor)
        self._prefetch_timer.start(80)
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        pos = QPointF(event.position())
        btn = event.button()

        # Middle button or space+left → pan
        if btn == Qt.MouseButton.MiddleButton or (
                btn == Qt.MouseButton.LeftButton and self._space_held):
            self._mode = InteractionMode.PAN
            self._pan_start = pos
            self._pan_offset_start = QPointF(self._offset)
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            return

        if btn != Qt.MouseButton.LeftButton:
            return

        img_pt = self._canvas_to_img(pos.x(), pos.y())

        # Check for handle hit on selected panel
        if self._selected:
            r = self._panel_to_canvas_rect(self._selected)
            handle = self._hit_handle(r, pos)
            if handle:
                self._mode = InteractionMode.RESIZE
                self._drag_resize_handle = handle
                self._drag_resize_origin = (
                    self._selected.x, self._selected.y,
                    self._selected.w, self._selected.h
                )
                self._drag_start_image = img_pt
                return

        # Check body hit on any panel (top-most first)
        for panel in reversed(self._panels):
            r = self._panel_to_canvas_rect(panel)
            if r.contains(pos):
                self.select_panel(panel)
                self._mode = InteractionMode.MOVE
                self._drag_start_canvas = pos
                self._drag_panel_origin = (panel.x, panel.y)
                return

        # Deselect + start drawing
        self.select_panel(None)
        self._mode = InteractionMode.DRAW
        ix, iy = int(img_pt.x()), int(img_pt.y())
        self._draw_rect = PanelRect(x=ix, y=iy, w=0, h=0)
        self._drag_start_image = img_pt

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = QPointF(event.position())

        if self._mode == InteractionMode.PAN:
            assert self._pan_start and self._pan_offset_start
            delta = pos - self._pan_start
            self._offset = self._pan_offset_start + delta
            self.update()
            return

        if self._mode == InteractionMode.DRAW:
            assert self._draw_rect and self._drag_start_image
            img_pt = self._canvas_to_img(pos.x(), pos.y())
            sx, sy = self._drag_start_image.x(), self._drag_start_image.y()
            self._draw_rect.x = int(min(sx, img_pt.x()))
            self._draw_rect.y = int(min(sy, img_pt.y()))
            self._draw_rect.w = int(abs(img_pt.x() - sx))
            self._draw_rect.h = int(abs(img_pt.y() - sy))
            self.update()
            return

        if self._mode == InteractionMode.MOVE:
            assert self._drag_start_canvas and self._selected
            delta = pos - self._drag_start_canvas
            ox, oy = self._drag_panel_origin
            new_x = ox + int(delta.x() / self._zoom)
            new_y = oy + int(delta.y() / self._zoom)
            if self._loader:
                new_x = max(0, min(new_x, self._loader.img_width - self._selected.w))
                new_y = max(0, min(new_y, self._loader.img_height - self._selected.h))
            self._selected.x = new_x
            self._selected.y = new_y
            self.update()
            return

        if self._mode == InteractionMode.RESIZE:
            assert self._selected and self._drag_start_image
            img_pt = self._canvas_to_img(pos.x(), pos.y())
            dx = int(img_pt.x() - self._drag_start_image.x())
            dy = int(img_pt.y() - self._drag_start_image.y())
            ox, oy, ow, oh = self._drag_resize_origin
            h = self._drag_resize_handle

            nx, ny, nw, nh = ox, oy, ow, oh
            if "l" in h:
                nx = ox + dx
                nw = ow - dx
            if "r" in h:
                nw = ow + dx
            if "t" in h:
                ny = oy + dy
                nh = oh - dy
            if "b" in h:
                nh = oh + dy

            if nw >= MIN_RECT_SIZE and nh >= MIN_RECT_SIZE:
                self._selected.x, self._selected.y = nx, ny
                self._selected.w, self._selected.h = nw, nh
            self.update()
            return

        # Update cursor based on hover
        self._update_hover_cursor(pos)

    def mouseReleaseEvent(self, event: QMouseEvent):
        pos = QPointF(event.position())
        btn = event.button()

        if self._mode == InteractionMode.PAN:
            self._mode = InteractionMode.NONE
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self._prefetch_timer.start(80)
            return

        if btn != Qt.MouseButton.LeftButton:
            return

        if self._mode == InteractionMode.DRAW:
            r = self._draw_rect
            self._draw_rect = None
            if r and r.w >= MIN_RECT_SIZE and r.h >= MIN_RECT_SIZE:
                r = r.normalized()
                if self._loader:
                    r = r.clamp(self._loader.img_width, self._loader.img_height)
                if self.on_request_add_panel:
                    self.on_request_add_panel(r)
            self._mode = InteractionMode.NONE
            self.update()
            return

        if self._mode == InteractionMode.MOVE:
            assert self._selected
            ox, oy = self._drag_panel_origin
            nx, ny = self._selected.x, self._selected.y
            if (ox != nx or oy != ny) and self.on_request_move_panel:
                self.on_request_move_panel(self._selected, ox, oy, nx, ny)
            self._mode = InteractionMode.NONE
            self.panels_changed.emit()
            return

        if self._mode == InteractionMode.RESIZE:
            assert self._selected
            ox, oy, ow, oh = self._drag_resize_origin
            nx, ny, nw, nh = self._selected.x, self._selected.y, self._selected.w, self._selected.h
            if (ox, oy, ow, oh) != (nx, ny, nw, nh) and self.on_request_resize_panel:
                self.on_request_resize_panel(self._selected, ox, oy, ow, oh, nx, ny, nw, nh)
            self._mode = InteractionMode.NONE
            self.panels_changed.emit()
            return

        self._mode = InteractionMode.NONE

    def _update_hover_cursor(self, pos: QPointF):
        if self._space_held:
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            return

        if self._selected:
            r = self._panel_to_canvas_rect(self._selected)
            handle = self._hit_handle(r, pos)
            if handle:
                cursors = {
                    "tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
                    "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
                    "tc": Qt.CursorShape.SizeVerCursor,   "bc": Qt.CursorShape.SizeVerCursor,
                    "ml": Qt.CursorShape.SizeHorCursor,   "mr": Qt.CursorShape.SizeHorCursor,
                }
                self.setCursor(QCursor(cursors.get(handle, Qt.CursorShape.ArrowCursor)))
                return

        for panel in reversed(self._panels):
            r = self._panel_to_canvas_rect(panel)
            if r.contains(pos):
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
                return

        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

    # ── Keyboard ───────────────────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()

        if key == Qt.Key.Key_Space:
            self._space_held = True
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            return

        if not self._selected:
            return

        # Arrow key nudge (1px normally, 10px with shift)
        nudge = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        if key == Qt.Key.Key_Left:
            self._selected.x -= nudge
        elif key == Qt.Key.Key_Right:
            self._selected.x += nudge
        elif key == Qt.Key.Key_Up:
            self._selected.y -= nudge
        elif key == Qt.Key.Key_Down:
            self._selected.y += nudge
        elif key == Qt.Key.Key_Delete or key == Qt.Key.Key_Backspace:
            return  # handled by main window

        self.panels_changed.emit()
        self.update()

    def keyReleaseEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Space:
            self._space_held = False
            self._update_hover_cursor(QPointF(self.mapFromGlobal(QCursor.pos())))

    # ── Drag and drop ──────────────────────────────────────────────────────────

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                # Signal to parent via attribute callback
                if hasattr(self, "on_drop_image"):
                    self.on_drop_image(path)

    # ── Resize ─────────────────────────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._loader and self._offset == QPointF(0, 0):
            self._fit_to_width()
