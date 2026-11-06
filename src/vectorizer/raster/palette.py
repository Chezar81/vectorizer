"""Suggested trace palettes and hard assignment of pixels to those colors."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from vectorizer.domain.settings import normalize_hex
from vectorizer.raster.color import hex_to_rgb, nearest_oklab, rgb_to_hex, srgb_u8_to_oklab

# Include odd counts so 3- and 5-color logos are not forced into 4/8 buckets.
# 24–32 cover rich cel / cartoon scenes (walls, furniture, accents, ink).
SUGGESTED_COUNTS: tuple[int, ...] = (2, 3, 4, 5, 6, 8, 12, 16, 24, 28, 32)
# Cel scenes: mild hue emphasis so pink walls stay off orange chairs without
# pulling shaded oranges into brown ink slots.
_CEL_CHROMA_WEIGHT = 1.35


@dataclass(frozen=True)
class PaletteSuggestions:
    """Candidate palettes plus the count that fits the image best."""

    best: int
    palettes: dict[int, tuple[str, ...]]


def suggest_palettes(
    image: Image.Image,
    *,
    ignore_rgb: tuple[int, int, int] | None = None,
) -> PaletteSuggestions:
    """Build candidate palettes from a downscaled copy of `image`."""
    rgb = image.convert("RGB")
    width, height = rgb.size
    probe = rgb
    # Keep more detail than a 180px probe so small accent colors survive.
    if max(width, height) > 320:
        scale = 320 / float(max(width, height))
        probe = rgb.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.BOX,
        )
    method = getattr(Image.Quantize, "MAXCOVERAGE", Image.Quantize.MEDIANCUT)
    palettes: dict[int, tuple[str, ...]] = {}
    errors: dict[int, float] = {}
    p99: dict[int, float] = {}
    # Convert the probe to OKLab once; each candidate palette reuses it.
    probe_lab = srgb_u8_to_oklab(np.asarray(probe, dtype=np.uint8))
    probe_rgb = np.asarray(probe, dtype=np.int16)
    # When the background ink is excluded from the palette, also exclude those
    # pixels from the error so white paper does not force a 16-color "best".
    keep = np.ones(probe_rgb.shape[:2], dtype=bool)
    if ignore_rgb is not None:
        keep = ~(
            (np.abs(probe_rgb[..., 0] - ignore_rgb[0]) <= 28)
            & (np.abs(probe_rgb[..., 1] - ignore_rgb[1]) <= 28)
            & (np.abs(probe_rgb[..., 2] - ignore_rgb[2]) <= 28)
        )
        if not np.any(keep):
            keep = np.ones(probe_rgb.shape[:2], dtype=bool)
    stable_mass: dict[int, float] = {}
    for count in SUGGESTED_COUNTS:
        colors = _quantize_colors(probe, count, method, ignore_rgb=ignore_rgb)
        if len(colors) < min(2, count):
            # Richer quantize then filter before giving up and re-including paper.
            colors = _quantize_colors(
                probe, max(count * 3, 8), method, ignore_rgb=ignore_rgb
            )[:count]
        if len(colors) < 2 and ignore_rgb is None:
            colors = _quantize_colors(probe, count, method, ignore_rgb=None)
        # Keep large scene colours (walls/floors) and tiny accents that
        # frequency ranking alone drops when merging into a small palette.
        chroma = _CEL_CHROMA_WEIGHT if count >= 12 else 1.0
        colors = _promote_missing_regions(
            probe_rgb[keep],
            probe_lab[keep],
            colors,
            count,
            chroma_weight=chroma,
        )
        colors = _refine_colors_to_medians(
            probe_rgb[keep],
            probe_lab[keep],
            colors,
            chroma_weight=chroma,
        )
        palettes[count] = tuple(rgb_to_hex(color) for color in colors[:count])
        mean_err, err99, stable = _reconstruction_errors(
            probe_rgb[keep], probe_lab[keep], colors, chroma_weight=chroma
        )
        errors[count] = mean_err
        p99[count] = err99
        stable_mass[count] = stable
    best = SUGGESTED_COUNTS[-1]
    for count in SUGGESTED_COUNTS:
        best = count
        # Prefer OKLab stability: anti-aliased fringe keeps mean RGB error high
        # even when the solid inks are correct. Fall back to RGB thresholds for
        # hard-edged art where stability is already perfect.
        if stable_mass[count] >= 0.90 or (errors[count] <= 11.0 and p99[count] <= 42.0):
            break
    return PaletteSuggestions(best=best, palettes=palettes)


def cel_fill_palette(
    image: Image.Image,
    *,
    max_colors: int = 26,
    max_side: int = 1100,
    radius: float = 0.05,
    chroma_weight: float = 1.6,
    min_share: float = 0.0005,
) -> tuple[str, ...]:
    """Flat-fill inks for ink-outlined cel art, ignoring strokes and AA fringe.

    Quantizing the whole raster lets brown JPEG outlines and blended edges eat
    slots, while small but distinct flats (white sails, gold frames, a blue lamp
    neck) disappear. Here only flat interior pixels vote, and inks are chosen
    by set cover in chroma-weighted OKLab so each slot adds a new colour rather
    than another shade of the wall.
    """
    from PIL import ImageFilter

    from vectorizer.raster.preprocess import _binary_dilate, cel_stroke_mask

    rgb_img = image.convert("RGB")
    width, height = rgb_img.size
    if max(width, height) > max_side:
        scale = max_side / float(max(width, height))
        rgb_img = rgb_img.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.BOX,
        )
    rgb = np.asarray(rgb_img, dtype=np.uint8)
    stroke = _binary_dilate(cel_stroke_mask(rgb), 1)
    med_img = Image.fromarray(rgb, "RGB").filter(ImageFilter.MedianFilter(3))
    med = np.asarray(med_img, dtype=np.uint8)
    hi = np.asarray(med_img.filter(ImageFilter.MaxFilter(5)), dtype=np.int16)
    lo = np.asarray(med_img.filter(ImageFilter.MinFilter(5)), dtype=np.int16)
    flat = ((hi - lo).max(axis=2) <= 16) & ~stroke
    pixels = med[flat]
    if len(pixels) < 64:
        return ()
    step = max(1, len(pixels) // 150_000)
    pixels = np.ascontiguousarray(pixels[::step])
    side = int(np.sqrt(len(pixels)))
    square = Image.fromarray(pixels[: side * side].reshape(side, side, 3), "RGB")
    method = getattr(Image.Quantize, "MAXCOVERAGE", Image.Quantize.MEDIANCUT)
    quantized = square.quantize(colors=96, method=method, dither=Image.Dither.NONE)
    raw = np.asarray((quantized.getpalette() or [])[: 96 * 3], dtype=np.uint8).reshape(-1, 3)
    used = np.asarray(quantized.histogram()[: len(raw)]) > 0
    candidates = raw[used]
    if len(candidates) == 0:
        return ()

    weight = np.asarray([1.0, chroma_weight, chroma_weight], dtype=np.float32)
    pix_lab = srgb_u8_to_oklab(pixels.reshape(1, -1, 3))[0] * weight
    cand_lab = srgb_u8_to_oklab(candidates.reshape(1, -1, 3))[0] * weight

    def _sq_dist(centers: np.ndarray) -> np.ndarray:
        return (
            (pix_lab * pix_lab).sum(-1)[:, None]
            - 2.0 * pix_lab @ centers.T
            + (centers * centers).sum(-1)[None, :]
        )

    near = _sq_dist(cand_lab) < radius * radius
    min_pixels = max(8, int(len(pixels) * min_share))
    covered = np.zeros(len(pixels), dtype=bool)
    chosen: list[int] = []
    for _ in range(max_colors):
        gain = (near & ~covered[:, None]).sum(axis=0)
        if chosen:
            gain[chosen] = -1
        best = int(np.argmax(gain))
        if gain[best] < min_pixels:
            break
        chosen.append(best)
        covered |= near[:, best]
    if not chosen:
        return ()

    centers = cand_lab[chosen].copy()
    for _ in range(4):
        assign = np.argmin(_sq_dist(centers), axis=1)
        counts = np.bincount(assign, minlength=len(centers))
        for i in np.nonzero(counts)[0]:
            centers[i] = pix_lab[assign == i].mean(axis=0)
        centers = centers[counts >= min_pixels]
        if len(centers) == 0:
            return ()
    assign = np.argmin(_sq_dist(centers), axis=1)
    ranked: list[tuple[int, str]] = []
    seen: set[str] = set()
    for i in range(len(centers)):
        members = pixels[assign == i]
        if len(members) == 0:
            continue
        median = np.median(members, axis=0)
        hex_color = normalize_hex(
            rgb_to_hex((int(median[0]), int(median[1]), int(median[2])))
        )
        if hex_color in seen:
            continue
        seen.add(hex_color)
        ranked.append((len(members), hex_color))
    ranked.sort(key=lambda item: -item[0])
    return tuple(color for _count, color in ranked)


def snap_image_to_palette(
    image: Image.Image,
    palette: tuple[str, ...],
    *,
    chroma_weight: float = 1.0,
) -> Image.Image:
    """Replace every pixel's RGB with the nearest palette color. Alpha is kept."""
    if not palette:
        return image.convert("RGBA")
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    colors = np.asarray([hex_to_rgb(color) for color in palette], dtype=np.uint8)
    index, _dist = nearest_oklab(
        srgb_u8_to_oklab(rgba[..., :3]),
        srgb_u8_to_oklab(colors),
        chroma_weight=chroma_weight,
    )
    snapped = colors[index]
    out = np.empty_like(rgba)
    out[..., :3] = snapped
    out[..., 3] = rgba[..., 3]
    return Image.fromarray(out, mode="RGBA")


def refine_palette_to_image(
    image: Image.Image,
    palette: tuple[str, ...],
    *,
    chroma_weight: float = _CEL_CHROMA_WEIGHT,
    min_pixels: int = 48,
) -> tuple[str, ...]:
    """Snap palette inks to the median of the pixels they currently own.

    Fixes quantized / background-pinned colours that drift from the true flat
    fills (e.g. a light corner pink vs the real wall).
    """
    if not palette:
        return palette
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    colors = [hex_to_rgb(color) for color in palette]
    refined = _refine_colors_to_medians(
        rgb.reshape(-1, 3),
        srgb_u8_to_oklab(rgb).reshape(-1, 3),
        colors,
        chroma_weight=chroma_weight,
        min_pixels=min_pixels,
    )
    # Preserve order; drop exact duplicates that refinement may create.
    out: list[str] = []
    seen: set[str] = set()
    for color in refined:
        hex_color = normalize_hex(rgb_to_hex(color))
        if hex_color in seen:
            continue
        seen.add(hex_color)
        out.append(hex_color)
    # If duplicates collapsed the palette, keep originals to fill the slots.
    if len(out) < max(2, len(palette) // 2):
        return tuple(normalize_hex(c) for c in palette)
    while len(out) < len(palette):
        for color in palette:
            hex_color = normalize_hex(color)
            if hex_color not in seen:
                seen.add(hex_color)
                out.append(hex_color)
            if len(out) >= len(palette):
                break
        else:
            break
    return tuple(out[: len(palette)])


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
    # Tighter merge for richer palettes so teal floors and pink walls stay distinct.
    merge_tol = 12 if count >= 10 else 16
    unique: list[tuple[int, int, int]] = []
    for _freq, color in ranked:
        if all(not _near(color, kept, tol=merge_tol) for kept in unique):
            unique.append(color)
        if len(unique) >= count:
            break
    return unique


def _as_lab_image(pixels_lab: np.ndarray) -> tuple[np.ndarray, tuple[int, ...]]:
    """`nearest_oklab` wants HxWx3; masked probes arrive as Nx3."""
    arr = np.asarray(pixels_lab, dtype=np.float32)
    if arr.ndim == 2 and arr.shape[-1] == 3:
        return arr.reshape(1, -1, 3), arr.shape
    return arr, arr.shape


def _promote_missing_regions(
    pixels: np.ndarray,
    pixels_lab: np.ndarray,
    colors: list[tuple[int, int, int]],
    count: int,
    *,
    chroma_weight: float = 1.0,
) -> list[tuple[int, int, int]]:
    """Add residual clusters that cover real area (scene fills or accents)."""
    if len(colors) >= count or not colors:
        return colors
    lab_img, _shape = _as_lab_image(pixels_lab)
    _index, dist = nearest_oklab(
        lab_img,
        srgb_u8_to_oklab(np.asarray(colors, dtype=np.uint8)),
        chroma_weight=chroma_weight,
    )
    dist = dist.reshape(-1)
    flat_rgb = np.asarray(pixels, dtype=np.int16).reshape(-1, 3)
    # Iteratively pull the largest poorly-represented cluster into the palette.
    # Chroma-weighted distance uses a slightly higher "far" gate because a/b
    # axes are stretched.
    far_gate = 0.0035 * (0.65 + 0.35 * max(1.0, chroma_weight))
    promoted = list(colors)
    for _ in range(max(0, count - len(colors))):
        far = dist >= far_gate
        share = float(far.mean()) if far.size else 0.0
        if share < 0.004:
            break
        far_rgb = flat_rgb[far]
        median = np.median(far_rgb, axis=0)
        candidate = (int(median[0]), int(median[1]), int(median[2]))
        if any(_near(candidate, kept, tol=18) for kept in promoted):
            # Nudge toward the worst residual mean instead of giving up.
            mean = np.mean(far_rgb, axis=0)
            candidate = (int(mean[0]), int(mean[1]), int(mean[2]))
            if any(_near(candidate, kept, tol=18) for kept in promoted):
                break
        promoted.append(candidate)
        if len(promoted) >= count:
            break
        # Recompute distances against the expanded palette for the next pass.
        _index, dist = nearest_oklab(
            lab_img,
            srgb_u8_to_oklab(np.asarray(promoted, dtype=np.uint8)),
            chroma_weight=chroma_weight,
        )
        dist = dist.reshape(-1)
    return promoted


def _refine_colors_to_medians(
    pixels: np.ndarray,
    pixels_lab: np.ndarray,
    colors: list[tuple[int, int, int]],
    *,
    chroma_weight: float = 1.0,
    min_pixels: int = 8,
) -> list[tuple[int, int, int]]:
    """Replace each ink with the median of the pixels currently assigned to it."""
    if not colors:
        return colors
    lab_img, _shape = _as_lab_image(pixels_lab)
    index, _dist = nearest_oklab(
        lab_img,
        srgb_u8_to_oklab(np.asarray(colors, dtype=np.uint8)),
        chroma_weight=chroma_weight,
    )
    flat_index = index.reshape(-1)
    flat_rgb = np.asarray(pixels, dtype=np.int16).reshape(-1, 3)
    refined: list[tuple[int, int, int]] = []
    for i, color in enumerate(colors):
        mask = flat_index == i
        count = int(mask.sum())
        if count < min_pixels:
            refined.append(color)
            continue
        median = np.median(flat_rgb[mask], axis=0)
        refined.append((int(median[0]), int(median[1]), int(median[2])))
    return refined


def _reconstruction_errors(
    pixels: np.ndarray,
    pixels_lab: np.ndarray,
    colors: list[tuple[int, int, int]],
    *,
    chroma_weight: float = 1.0,
) -> tuple[float, float, float]:
    if not colors:
        return 255.0, 255.0, 0.0
    lab_img, _shape = _as_lab_image(pixels_lab)
    index, dist = nearest_oklab(
        lab_img,
        srgb_u8_to_oklab(np.asarray(colors, dtype=np.uint8)),
        chroma_weight=chroma_weight,
    )
    assigned = np.asarray(colors, dtype=np.int16)[index.reshape(-1)]
    flat = np.asarray(pixels, dtype=np.int16).reshape(-1, 3)
    abs_err = np.abs(flat - assigned).mean(axis=-1)
    stable = float((dist.reshape(-1) <= 0.0025 * max(1.0, chroma_weight)).mean())
    return float(abs_err.mean()), float(np.percentile(abs_err, 99)), stable


def _near(
    a: tuple[int, int, int],
    b: tuple[int, int, int],
    *,
    tol: int = 28,
) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol and abs(a[2] - b[2]) <= tol
