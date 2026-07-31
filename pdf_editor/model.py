from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass
class Placement:
    kind: Literal["text", "image"]
    page_index: int
    x: float
    y: float
    width: float
    height: float
    text: str = ""
    image_path: Path | None = None
    font_size: float = 14.0

    def contains(self, pdf_x: float, pdf_y: float) -> bool:
        return (
            self.x <= pdf_x <= self.x + self.width
            and self.y <= pdf_y <= self.y + self.height
        )


@dataclass(frozen=True)
class ViewTransform:
    page_width: float
    page_height: float
    canvas_left: float
    canvas_top: float
    scale: float

    def pdf_to_canvas(self, x: float, y: float) -> tuple[float, float]:
        return self.canvas_left + x * self.scale, self.canvas_top + y * self.scale

    def canvas_to_pdf(self, x: float, y: float) -> tuple[float, float]:
        return (
            (x - self.canvas_left) / self.scale,
            (y - self.canvas_top) / self.scale,
        )

    def clamp_box(
        self, x: float, y: float, width: float, height: float
    ) -> tuple[float, float]:
        return (
            min(max(0.0, x), max(0.0, self.page_width - width)),
            min(max(0.0, y), max(0.0, self.page_height - height)),
        )


def size_from_bottom_right(
    placement: Placement,
    pointer_x: float,
    pointer_y: float,
    page_width: float,
    page_height: float,
    minimum_width: float = 12.0,
) -> tuple[float, float]:
    """Resize from the bottom-right corner while preserving the aspect ratio."""
    aspect_ratio = placement.height / max(placement.width, 0.01)
    maximum_width = max(
        1.0,
        min(
            page_width - placement.x,
            (page_height - placement.y) / max(aspect_ratio, 0.01),
        ),
    )
    pointer_width = pointer_x - placement.x
    pointer_height = pointer_y - placement.y
    requested_width = (
        pointer_width + aspect_ratio * pointer_height
    ) / (1.0 + aspect_ratio * aspect_ratio)
    requested_width = max(minimum_width, requested_width)
    width = min(requested_width, maximum_width)
    return width, width * aspect_ratio
