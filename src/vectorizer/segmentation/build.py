"""Build an initial editable segmentation from a source raster."""

from __future__ import annotations

from PIL import Image

from vectorizer.domain.settings import TraceSettings
from vectorizer.raster.preprocess import preprocess_image
from vectorizer.segmentation.map import SegmentationMap

_HARD_ALPHA_LUT = [255 if a >= 128 else 0 for a in range(256)]


def build_segmentation(
    source: Image.Image,
    settings: TraceSettings | None = None,
    *,
    colors: int | None = None,
) -> SegmentationMap:
    """Create a working segmentation map.

    Uses the same preprocess path as tracing (background knock-out, optional
    quantize), then forces a discrete palette so region edits stay crisp.
    The original `source` image is never mutated.
    """
    settings = (settings or TraceSettings()).validated()
    working = preprocess_image(source, settings)
    target = colors
    if target is None:
        target = settings.target_colors if settings.target_colors > 0 else _auto_colors(settings)
    target = max(2, min(64, int(target)))

    # Avoid a second median-cut pass when preprocess already quantized to the
    # same (capped) palette size — only harden alpha for binary region edits.
    already_quantized = (
        colors is None
        and settings.target_colors > 0
        and max(2, min(64, settings.target_colors)) == target
    )
    if already_quantized:
        quantized = _harden_alpha(working)
    else:
        quantized = _quantize_keep_alpha(working, target)
    return SegmentationMap(quantized)


def _auto_colors(settings: TraceSettings) -> int:
    # color_precision bits roughly map to palette size; keep editable.
    return max(4, min(32, 2 ** max(2, min(5, settings.color_precision - 1))))


def _harden_alpha(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A").point(_HARD_ALPHA_LUT)
    out = rgba.copy()
    out.putalpha(alpha)
    return out


def _quantize_keep_alpha(image: Image.Image, colors: int) -> Image.Image:
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    rgb = rgba.convert("RGB")
    quantized = rgb.quantize(
        colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
    )
    restored = quantized.convert("RGBA")
    # Hard-threshold alpha so regions stay binary for editing.
    restored.putalpha(alpha.point(_HARD_ALPHA_LUT))
    return restored
