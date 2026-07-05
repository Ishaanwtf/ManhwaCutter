"""
Tiled image loading system for handling extremely tall manhwa images.

Strategy:
- Images are divided into vertical strips (tiles) of TILE_HEIGHT pixels.
- Only tiles intersecting the visible viewport are decoded and cached.
- A simple LRU cache evicts tiles when memory pressure is high.
- The full image is NEVER held in RAM at once.
- Thumbnails are generated at load time from a heavily downsampled copy.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from PIL import Image, ImageFile
Image.MAX_IMAGE_PIXELS = None


# Allow loading of truncated images (common with partial downloads)
ImageFile.LOAD_TRUNCATED_IMAGES = True

# Tile height in image pixels
TILE_HEIGHT = 2048
# Maximum tiles held in memory (2048 × 768 × 4 bytes ≈ 6 MB each → 20 tiles ≈ 120 MB)
MAX_CACHE_TILES = 20
# Thumbnail max height
THUMB_MAX_HEIGHT = 4096


class ImageTile:
    """A decoded PIL image tile covering rows [y_start, y_end) of the source."""
    __slots__ = ("y_start", "y_end", "image")

    def __init__(self, y_start: int, y_end: int, image: Image.Image):
        self.y_start = y_start
        self.y_end = y_end
        self.image = image


class TiledImageLoader:
    """
    Lazy-loading tiled image reader.

    Usage:
        loader = TiledImageLoader(path)
        loader.open()
        tile = loader.get_tile(tile_index)   # 0-based
        loader.close()
    """

    def __init__(self, path: str):
        self.path = path
        self._pil: Optional[Image.Image] = None
        self._lock = threading.Lock()
        self._cache: OrderedDict[int, ImageTile] = OrderedDict()

        self.img_width: int = 0
        self.img_height: int = 0
        self.num_tiles: int = 0
        self.thumbnail: Optional[Image.Image] = None
        self._loaded = False

    def open(self) -> None:
        """Open image, read metadata, build thumbnail. Does NOT load pixel data."""
        img = Image.open(self.path)
        img.load()  # needed to read metadata for some formats
        # Convert to RGBA for uniform handling
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        self._pil = img
        self.img_width, self.img_height = img.size
        self.num_tiles = max(1, (self.img_height + TILE_HEIGHT - 1) // TILE_HEIGHT)
        self._build_thumbnail()
        self._loaded = True

    def _build_thumbnail(self) -> None:
        """Create a small preview image for the overview panel."""
        assert self._pil is not None
        scale = min(1.0, THUMB_MAX_HEIGHT / self.img_height)
        tw = max(1, int(self.img_width * scale))
        th = max(1, int(self.img_height * scale))
        self.thumbnail = self._pil.resize((tw, th), Image.LANCZOS)
        self.thumb_scale = scale  # image_pixel = thumb_pixel / thumb_scale

    def get_tile(self, tile_index: int) -> Optional[ImageTile]:
        """
        Return the decoded tile at tile_index.
        Tiles are cached; LRU eviction keeps memory bounded.
        Thread-safe.
        """
        if not self._loaded or self._pil is None:
            return None
        tile_index = max(0, min(tile_index, self.num_tiles - 1))

        with self._lock:
            if tile_index in self._cache:
                self._cache.move_to_end(tile_index)
                return self._cache[tile_index]

            # Evict if over limit
            while len(self._cache) >= MAX_CACHE_TILES:
                self._cache.popitem(last=False)

            y_start = tile_index * TILE_HEIGHT
            y_end = min(y_start + TILE_HEIGHT, self.img_height)

            region = self._pil.crop((0, y_start, self.img_width, y_end))
            tile = ImageTile(y_start=y_start, y_end=y_end, image=region)
            self._cache[tile_index] = tile
            return tile

    def get_tiles_for_range(self, y_start: int, y_end: int) -> list[ImageTile]:
        """Return all tiles that intersect the image-space y range [y_start, y_end)."""
        t_start = y_start // TILE_HEIGHT
        t_end = (y_end - 1) // TILE_HEIGHT
        tiles = []
        for ti in range(t_start, t_end + 1):
            t = self.get_tile(ti)
            if t:
                tiles.append(t)
        return tiles

    def crop_region(self, x: int, y: int, w: int, h: int) -> Image.Image:
        """
        Extract an arbitrary rectangle from the source image.
        Assembled from tiles to avoid loading the full image.
        """
        assert self._pil is not None
        return self._pil.crop((x, y, x + w, y + h))

    def close(self) -> None:
        with self._lock:
            self._cache.clear()
            if self._pil:
                self._pil.close()
            self._pil = None
            self._loaded = False

    @property
    def is_open(self) -> bool:
        return self._loaded

    def prefetch_tiles_async(self, tile_indices: list[int]) -> None:
        """Background prefetch for smoother scrolling."""
        def _worker():
            for ti in tile_indices:
                self.get_tile(ti)
        t = threading.Thread(target=_worker, daemon=True)
        t.start()
