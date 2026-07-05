"""
Export engine: extracts panel crops from source image and saves to disk.
Runs in a worker thread so the UI stays responsive during export.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

from PIL import Image

from .models import PanelRect, ExportSettings
from .image_loader import TiledImageLoader


class ExportResult:
    def __init__(self):
        self.exported: list[str] = []
        self.errors: list[tuple[str, str]] = []  # (panel_label, error_msg)
        self.cancelled = False


class ExportWorker(threading.Thread):
    """
    Background thread that exports selected panels.

    Signals (all called on worker thread, marshal to UI thread as needed):
        on_progress(panel_index, total)
        on_done(ExportResult)
    """

    def __init__(
        self,
        loader: TiledImageLoader,
        panels: list[PanelRect],
        settings: ExportSettings,
        on_progress: Optional[Callable[[int, int], None]] = None,
        on_done: Optional[Callable[[ExportResult], None]] = None,
    ):
        super().__init__(daemon=True)
        self._loader = loader
        self._panels = list(panels)
        self._settings = settings
        self.on_progress = on_progress
        self.on_done = on_done
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        result = ExportResult()
        out_dir = Path(self._settings.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        total = len(self._panels)
        fmt = self._settings.format.upper()
        ext = ".png" if fmt == "PNG" else ".webp"

        for i, panel in enumerate(self._panels):
            if self._cancel.is_set():
                result.cancelled = True
                break

            if self.on_progress:
                self.on_progress(i, total)

            label = panel.label if panel.label else self._settings.name_template.format(n=i + 1)
            filename = f"{label}{ext}"
            out_path = out_dir / filename

            try:
                rect = panel.normalized().clamp(self._loader.img_width, self._loader.img_height)
                if rect.w < 1 or rect.h < 1:
                    result.errors.append((label, "Empty crop region"))
                    continue

                crop = self._loader.crop_region(rect.x, rect.y, rect.w, rect.h)

                save_kwargs: dict = {}
                if fmt == "PNG":
                    save_kwargs = {"format": "PNG", "optimize": False, "compress_level": 1}
                    # Convert to RGB for PNG if saving without alpha
                    if crop.mode == "RGBA":
                        # Keep RGBA — preserves transparency
                        pass
                elif fmt == "WEBP":
                    save_kwargs = {"format": "WEBP", "quality": self._settings.webp_quality, "method": 4}
                    if crop.mode == "RGBA":
                        save_kwargs["lossless"] = False

                crop.save(str(out_path), **save_kwargs)
                result.exported.append(str(out_path))

            except Exception as exc:
                result.errors.append((label, str(exc)))

        if self.on_done:
            self.on_done(result)


def export_panels(
    loader: TiledImageLoader,
    panels: list[PanelRect],
    settings: ExportSettings,
    on_progress: Optional[Callable] = None,
    on_done: Optional[Callable] = None,
) -> ExportWorker:
    """Convenience function: start export and return worker (can be cancelled)."""
    worker = ExportWorker(loader, panels, settings, on_progress, on_done)
    worker.start()
    return worker
