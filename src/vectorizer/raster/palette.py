"""Suggested trace palettes and hard assignment of pixels to those colors."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from vectorizer.raster.color import hex_to_rgb, nearest_oklab, rgb_to_hex, srgb_u8_to_oklab

SUGGESTED_COUNTS: tuple[int, ...] = (2, 4, 8, 12)


@dataclass(frozen=True)
class PaletteSuggestions:
    """Palettes of 2, 4, 8 and 12 colors, plus the count that fits the image best."""

    best: int
    palettes: dict[int, tuple[str, ...]]


def suggest_palettes(
    image: Image.Image,
    *,
    ignore_rgb: tuple[int, int, int] | None = None,
) -> PaletteSuggestions:
    """Build a few candidate palettes from a downscaled copy of `image`."""
    rgb = image.convert("RGB")
    width, height = rgb.size
    probe = rgb
    if max(width, height) > 180:
        scale = 180 / float(max(width, height))
        probe = rgb.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.BOX,
        )
    method = getattr(Image.Quantize, "MAXCOVERAGE", Image.Quantize.MEDIANCUT)
    palettes: dict[int, tuple[str, ...]] = {}
    errors: dict[int, float] = {}
    for count in SUGGESTED_COUNTS:
        colors = _quantize_colors(probe, count, method, ignore_rgb=ignore_rgb)
        if len(colors) < 2:
            colors = _quantize_colors(probe, count, method, ignore_rgb=None)
        palettes[count] = tuple(rgb_to_hex(color) for color in colors[:count])
        errors[count] = _reconstruction_error(probe, colors)
    best = SUGGESTED_COUNTS[-1]
    for count in SUGGESTED_COUNTS:
        best = count
        # Mean per-channel error on the probe. Stop at the smallest palette that fits.
        if errors[count] <= 12.0:
            break
    return PaletteSuggestions(best=best, palettes=palettes)


def snap_image_to_palette(image: Image.Image, palette: tuple[str, ...]) -> Image.Image:
    """Replace every pixel's RGB with the nearest palette color. Alpha is kept."""
    if not palette:
        return image.convert("RGBA")
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    colors = np.asarray([hex_to_rgb(color) for color in palette], dtype=np.uint8)
    index, _dist = nearest_oklab(srgb_u8_to_oklab(rgba[..., :3]), srgb_u8_to_oklab(colors))
    snapped = colors[index]
    out = np.empty_like(rgba)
    out[..., :3] = snapped
    out[..., 3] = rgba[..., 3]
    return Image.fromarray(out, mode="RGBA")


def _quantize_colors(
    rgb: Image.Image,
    count: int,
    method: Image.Quantize,
    *,
    ignore_rgb: tuple[int, int, int] | None,
) -> list[tuple[int, int, int]]:
    try:
        quantized = rgb.quantize(colors=max(2, count), method=method, dither=Image.Dither.NONE)
    except Exception:
        quantized = rgb.quantize(
            colors=max(2, count),
            method=Image.Quantize.MEDIANCUT,
            dither=Image.Dither.NONE,
        )
    palette = quantized.getpalette() or []
    histogram = quantized.histogram()
    ranked: list[tuple[int, tuple[int, int, int]]] = []
    for index, freq in enumerate(histogram):
        if freq <= 0 or index * 3 + 2 >= len(palette):
            continue
        color = (
            int(palette[index * 3]),
            int(palette[index * 3 + 1]),
            int(palette[index * 3 + 2]),
        )
        if ignore_rgb is not None and _near(color, ignore_rgb):
            continue
        ranked.append((freq, color))
    ranked.sort(key=lambda item: -item[0])
    unique: list[tuple[int, int, int]] = []
    for _freq, color in ranked:
        if all(not _near(color, kept, tol=18) for kept in unique):
            unique.append(color)
        if len(unique) >= count:
            break
    return unique


def _reconstruction_error(rgb: Image.Image, colors: list[tuple[int, int, int]]) -> float:
    if not colors:
        return 255.0
    pixels = np.asarray(rgb, dtype=np.int16)
    index, _dist = nearest_oklab(
        srgb_u8_to_oklab(np.asarray(rgb, dtype=np.uint8)),
        srgb_u8_to_oklab(np.asarray(colors, dtype=np.uint8)),
    )
    assigned = np.asarray(colors, dtype=np.int16)[index]
    return float(np.abs(pixels - assigned).mean())


def _near(
    a: tuple[int, int, int],
    b: tuple[int, int, int],
    *,
    tol: int = 28,
) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol and abs(a[2] - b[2]) <= tol
