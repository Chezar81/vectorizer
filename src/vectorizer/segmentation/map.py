"""Working segmentation raster. Distinct from the immutable original source."""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image

from vectorizer.errors import SegmentationError


@dataclass
class SegmentationMap:
    """Pixel-aligned RGBA segmentation used as the retrace input.

    Transparent pixels (alpha == 0) are treated as background / no region.
    """

    image: Image.Image

    def __post_init__(self) -> None:
        if self.image.mode != "RGBA":
            self.image = self.image.convert("RGBA")
        if self.image.size[0] <= 0 or self.image.size[1] <= 0:
            raise SegmentationError("Segmentation map has invalid dimensions.")

    @property
    def size(self) -> tuple[int, int]:
        return self.image.size

    def copy(self) -> SegmentationMap:
        return SegmentationMap(self.image.copy())

    def to_png_bytes(self) -> bytes:
        buffer = io.BytesIO()
        # Fast encode for undo snapshots: optimize=True re-filters every commit
        # and hitchs brush/fill on megapixel maps.
        self.image.save(buffer, format="PNG", compress_level=1, optimize=False)
        return buffer.getvalue()

    @classmethod
    def from_png_bytes(cls, data: bytes) -> SegmentationMap:
        if not data:
            raise SegmentationError("Empty segmentation payload.")
        image = Image.open(io.BytesIO(data))
        image.load()
        return cls(image.convert("RGBA"))

    def pixel(self, x: int, y: int) -> tuple[int, int, int, int]:
        width, height = self.size
        if not (0 <= x < width and 0 <= y < height):
            raise SegmentationError(f"Pixel ({x}, {y}) is outside the map.")
        return self.image.getpixel((x, y))  # type: ignore[return-value]

    def set_pixel(self, x: int, y: int, color: tuple[int, int, int, int]) -> None:
        width, height = self.size
        if not (0 <= x < width and 0 <= y < height):
            return
        self.image.putpixel((x, y), color)

    def opaque_palette(self, max_colors: int = 64) -> list[str]:
        colors = self.image.getcolors(maxcolors=max_colors * 8)
        if colors is None:
            quantized = self.image.convert("RGB").quantize(colors=max_colors)
            restored = quantized.convert("RGBA")
            # Keep original alpha pattern approximately by using quantized RGB.
            alpha = self.image.getchannel("A")
            restored.putalpha(alpha)
            colors = restored.getcolors(maxcolors=max_colors * 4)
        if not colors:
            return []
        hexes: list[str] = []
        for _count, pixel in sorted(colors, key=lambda item: -item[0]):
            r, g, b, a = pixel
            if a < 16:
                continue
            hexes.append(f"#{r:02x}{g:02x}{b:02x}")
            if len(hexes) >= max_colors:
                break
        return hexes
