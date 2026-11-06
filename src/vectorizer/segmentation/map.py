"""Working segmentation raster. Distinct from the immutable original source."""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from PIL import Image

from vectorizer.errors import SegmentationError


@dataclass
class SegmentationMap:
    """Pixel-aligned RGBA segmentation used as the retrace input.

    Transparent pixels (alpha == 0) are treated as background / no region.

    `soft_source` keeps the anti-aliased original colours so F6 retrace can
    place iso-contours from real coverage even after hard label edits.
    """

    image: Image.Image
    soft_source: Image.Image | None = field(default=None)

    def __post_init__(self) -> None:
        if self.image.mode != "RGBA":
            self.image = self.image.convert("RGBA")
        if self.image.size[0] <= 0 or self.image.size[1] <= 0:
            raise SegmentationError("Segmentation map has invalid dimensions.")
        if self.soft_source is not None:
            if self.soft_source.mode != "RGBA":
                self.soft_source = self.soft_source.convert("RGBA")
            if self.soft_source.size != self.image.size:
                raise SegmentationError("Soft-source size must match the segmentation map.")

    @property
    def size(self) -> tuple[int, int]:
        return self.image.size

    def copy(self) -> SegmentationMap:
        soft = self.soft_source.copy() if self.soft_source is not None else None
        return SegmentationMap(self.image.copy(), soft_source=soft)

    def to_png_bytes(self) -> bytes:
        buffer = io.BytesIO()
        # Fast encode for undo snapshots: optimize=True re-filters every commit
        # and hitchs brush/fill on megapixel maps.
        self.image.save(buffer, format="PNG", compress_level=1, optimize=False)
        return buffer.getvalue()

    def soft_to_png_bytes(self) -> bytes | None:
        if self.soft_source is None:
            return None
        buffer = io.BytesIO()
        self.soft_source.save(buffer, format="PNG", compress_level=1, optimize=False)
        return buffer.getvalue()

    @classmethod
    def from_png_bytes(cls, data: bytes, *, soft_source: Image.Image | None = None) -> SegmentationMap:
        if not data:
            raise SegmentationError("Empty segmentation payload.")
        image = Image.open(io.BytesIO(data))
        image.load()
        return cls(image.convert("RGBA"), soft_source=soft_source)

    def harden_soft_at(self, x: int, y: int) -> None:
        """Copy the hard label colour into the soft sidecar at one pixel."""
        if self.soft_source is None:
            return
        width, height = self.size
        if not (0 <= x < width and 0 <= y < height):
            return
        self.soft_source.putpixel((x, y), self.image.getpixel((x, y)))

    def harden_soft_where_changed(self, before: Image.Image) -> None:
        """For every pixel that differs from `before`, freeze soft to the hard colour."""
        if self.soft_source is None:
            return
        import numpy as np

        hard = np.asarray(self.image, dtype=np.uint8)
        prev = np.asarray(before.convert("RGBA"), dtype=np.uint8)
        if hard.shape != prev.shape:
            return
        soft = np.asarray(self.soft_source, dtype=np.uint8).copy()
        changed = np.any(hard != prev, axis=-1)
        soft[changed] = hard[changed]
        self.soft_source = Image.fromarray(soft, mode="RGBA")

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
        self.harden_soft_at(x, y)

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
