"""Preprocessing applied to a copy of the source; never mutates the original."""

from __future__ import annotations

from PIL import Image, ImageChops, ImageFilter

from vectorizer.domain.settings import TraceSettings


def preprocess_image(image: Image.Image, settings: TraceSettings) -> Image.Image:
    """Return a working RGBA image for tracing.

    Original `image` is left unchanged. Operations (in order):
    - optional flattening of existing alpha when preserve_transparency is False
    - optional background removal by color + tolerance
    - optional light noise smoothing (median) while preserving alpha
    - optional color quantization (soft palette / target color count, no dither)
    """
    settings = settings.validated()
    working = image.convert("RGBA").copy()

    if not settings.preserve_transparency:
        bg = (
            settings.background_r,
            settings.background_g,
            settings.background_b,
            255,
        )
        flat = Image.new("RGBA", working.size, bg)
        flat.paste(working, mask=working.split()[3])
        working = flat

    if settings.remove_background:
        working = _knock_out_color(
            working,
            (settings.background_r, settings.background_g, settings.background_b),
            settings.background_tolerance,
        )

    if settings.smooth_noise:
        working = _smooth_noise_rgba(working)

    if settings.target_colors and settings.target_colors > 0:
        working = _quantize_rgba(working, settings.target_colors)

    return working


def _knock_out_color(
    image: Image.Image,
    color: tuple[int, int, int],
    tolerance: int,
) -> Image.Image:
    """Set alpha to 0 where RGB is within tolerance of `color`.

    Uses Pillow channel ops (C-level) instead of a Python per-pixel loop.
    """
    r, g, b, a = image.split()
    tr, tg, tb = color
    tol = max(0, int(tolerance))

    def _near(channel: Image.Image, target: int) -> Image.Image:
        lut = [255 if abs(i - target) <= tol else 0 for i in range(256)]
        return channel.point(lut)

    match = ImageChops.multiply(ImageChops.multiply(_near(r, tr), _near(g, tg)), _near(b, tb))
    # Where match is white, knock out alpha; otherwise keep existing alpha.
    new_alpha = Image.composite(Image.new("L", image.size, 0), a, match)
    return Image.merge("RGBA", (r, g, b, new_alpha))


def _smooth_noise_rgba(image: Image.Image) -> Image.Image:
    """3×3 median on RGB; keep the original alpha channel untouched."""
    alpha = image.getchannel("A")
    rgb = image.convert("RGB").filter(ImageFilter.MedianFilter(size=3))
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


def _quantize_rgba(image: Image.Image, colors: int) -> Image.Image:
    """Palette-reduce RGB without dithering (dither creates fake speckles for tracers)."""
    colors = max(2, min(256, int(colors)))
    alpha = image.getchannel("A")
    rgb = image.convert("RGB")
    # MAXCOVERAGE tends to keep saturated brand colors better than median-cut alone
    # on logos; fall back if the Pillow build lacks the enum member.
    method = getattr(Image.Quantize, "MAXCOVERAGE", Image.Quantize.MEDIANCUT)
    try:
        quantized = rgb.quantize(colors=colors, method=method, dither=Image.Dither.NONE)
    except Exception:
        quantized = rgb.quantize(
            colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
        )
    restored = quantized.convert("RGBA")
    restored.putalpha(alpha)
    return restored


def extract_palette_hex(image: Image.Image, max_colors: int = 32) -> list[str]:
    """Unique opaque colors from an RGBA image, capped for UI display."""
    rgba = image.convert("RGBA")
    colors = rgba.getcolors(maxcolors=max_colors * 8)
    if colors is None:
        quantized = _quantize_rgba(rgba, max_colors)
        colors = quantized.getcolors(maxcolors=max_colors * 4)
    if not colors:
        return []
    hexes: list[str] = []
    for _count, pixel in sorted(colors, key=lambda item: -item[0]):
        if len(pixel) == 4:
            r, g, b, a = pixel
            if a < 16:
                continue
        else:
            r, g, b = pixel[:3]
        hexes.append(f"#{r:02x}{g:02x}{b:02x}")
        if len(hexes) >= max_colors:
            break
    return hexes
