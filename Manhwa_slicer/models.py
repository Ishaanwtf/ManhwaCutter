"""
Core data models for the Manhwa Slicer application.
All coordinates are stored in image-space (pixel coordinates of the source image).
"""
from __future__ import annotations
import json
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional
from pathlib import Path


@dataclass
class PanelRect:
    """A single crop rectangle in image-space coordinates."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    x: int = 0
    y: int = 0
    w: int = 100
    h: int = 100
    label: str = ""

    def __post_init__(self):
        if not self.label:
            self.label = ""

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h

    def contains_point(self, px: int, py: int) -> bool:
        return self.x <= px <= self.x2 and self.y <= py <= self.y2

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PanelRect":
        return cls(**d)

    def copy(self) -> "PanelRect":
        return PanelRect(
            id=str(uuid.uuid4()),
            x=self.x + 20,
            y=self.y + 20,
            w=self.w,
            h=self.h,
            label=self.label,
        )

    def normalized(self) -> "PanelRect":
        """Ensure w and h are positive (handle reversed drags)."""
        x = self.x if self.w >= 0 else self.x + self.w
        y = self.y if self.h >= 0 else self.y + self.h
        return PanelRect(id=self.id, x=x, y=y, w=abs(self.w), h=abs(self.h), label=self.label)

    def clamp(self, img_w: int, img_h: int) -> "PanelRect":
        x = max(0, min(self.x, img_w - 1))
        y = max(0, min(self.y, img_h - 1))
        x2 = max(x + 1, min(self.x + self.w, img_w))
        y2 = max(y + 1, min(self.y + self.h, img_h))
        return PanelRect(id=self.id, x=x, y=y, w=x2 - x, h=y2 - y, label=self.label)


@dataclass
class ExportSettings:
    output_dir: str = ""
    format: str = "PNG"   # PNG or WEBP
    webp_quality: int = 90
    name_template: str = "panel_{n:03d}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ExportSettings":
        return cls(**d)


@dataclass
class Project:
    image_path: str = ""
    panels: list[PanelRect] = field(default_factory=list)
    export_settings: ExportSettings = field(default_factory=ExportSettings)
    version: str = "1.0"

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "image_path": self.image_path,
            "panels": [p.to_dict() for p in self.panels],
            "export_settings": self.export_settings.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        return cls(
            image_path=d.get("image_path", ""),
            panels=[PanelRect.from_dict(p) for p in d.get("panels", [])],
            export_settings=ExportSettings.from_dict(d.get("export_settings", {})),
            version=d.get("version", "1.0"),
        )

    def save(self, path: str | Path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
