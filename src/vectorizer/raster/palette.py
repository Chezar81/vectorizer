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
    rgba = image.convert("RGBA")
    width, height = rgba.size
    probe_rgba = rgba
    # Keep more detail than a 180px probe so small accent colors survive.
    if max(width, height) > 320:
        scale = 320 / float(max(width, height))
        probe_rgba = rgba.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.BOX,
        )
    probe = probe_rgba.convert("RGB")
    # Transparent pixels store arbitrary RGB (usually black) and translucent
    # drop shadows are black too; neither is an ink the tracer should paint.
    probe_alpha = np.asarray(probe_rgba.getchannel("A"))
    opaque = probe_alpha >= 128
    if 0 < int(opaque.sum()) < opaque.size and float(opaque.mean()) <= 0.98:
        opaque_px = np.asarray(probe, dtype=np.uint8)[opaque]
        probe = Image.fromarray(np.ascontiguousarray(opaque_px.reshape(1, -1, 3)), "RGB")
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
    thin_strip_residuals: bool = False,
) -> tuple[str, ...]:
    """Flat-fill inks for ink-outlined cel art, ignoring strokes and AA fringe.

    Quantizing the whole raster lets brown JPEG outlines and blended edges eat
    slots, while small but distinct flats (white sails, gold frames, a blue lamp
    neck) disappear. Here only flat interior pixels vote, and inks are chosen
    by set cover in chroma-weighted OKLab so each slot adds a new colour rather
    than another shade of the wall.

    `thin_strip_residuals` lets fills hatched by dense ink (a curtain with fold
    lines every few pixels) earn a slot: they fail the 5×5 flatness vote or
    fall just under `min_pixels` after downscale, so soft 3×3 pixels far from
    every chosen ink get a second set-cover pass (including flat leftovers).
    """
    from PIL import ImageFilter

    from vectorizer.raster.preprocess import _binary_dilate, cel_stroke_mask

    rgba_img = image.convert("RGBA")
    width, height = rgba_img.size
    if max(width, height) > max_side:
        scale = max_side / float(max(width, height))
        rgba_img = rgba_img.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.BOX,
        )
    rgba = np.asarray(rgba_img, dtype=np.uint8)
    rgb = rgba[..., :3]
    opaque = rgba[..., 3] >= 128
    stroke = _binary_dilate(cel_stroke_mask(rgb), 1)
    med_img = Image.fromarray(rgb, "RGB").filter(ImageFilter.MedianFilter(3))
    med = np.asarray(med_img, dtype=np.uint8)
    hi = np.asarray(med_img.filter(ImageFilter.MaxFilter(5)), dtype=np.int16)
    lo = np.asarray(med_img.filter(ImageFilter.MinFilter(5)), dtype=np.int16)
    # Skip transparent / chroma-key leftovers so magenta never earns a slot.
    chroma = (
        (med[..., 0] >= 200)
        & (med[..., 2] >= 200)
        & (med[..., 1] <= 80)
    )
    flat = ((hi - lo).max(axis=2) <= 16) & ~stroke & opaque & ~chroma
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
    colors = [color for _count, color in ranked]
    if thin_strip_residuals and len(colors) < max_colors:
        # Curtain yellow & similar: fold lines fail 5×5 flatness, and the few
        # flat leftovers often sit just under min_pixels after downscale. Pull
        # soft 3×3 interiors that are still far from every reported ink.
        hi3 = np.asarray(med_img.filter(ImageFilter.MaxFilter(3)), dtype=np.int16)
        lo3 = np.asarray(med_img.filter(ImageFilter.MinFilter(3)), dtype=np.int16)
        soft = (
            ((hi3 - lo3).max(axis=2) <= 24) & ~stroke & opaque & ~chroma
        )
        # Measure against reported medians, not k-means means: a cream mean
        # drifts toward yellow when yellow pixels joined its votes.
        reported = np.asarray([hex_to_rgb(c) for c in colors], dtype=np.uint8)
        extras = _thin_strip_inks(
            med[soft],
            srgb_u8_to_oklab(reported.reshape(1, -1, 3))[0] * weight,
            weight,
            radius=radius,
            min_pixels=max(8, min_pixels // 3),
            limit=6,
            seen=seen,
        )
        # Small shaded solids (a sea-green lamp base, a green book spine)
        # fall under min_pixels once the flat vote is subsampled and sit
        # inside the 2r blend gate of a neighbouring teal, so they dither
        # between two inks. Their flat pixels are not edge blends.
        reported = np.asarray(
            [hex_to_rgb(c) for c in (*colors, *extras)], dtype=np.uint8
        )
        extras += _thin_strip_inks(
            med[flat],
            srgb_u8_to_oklab(reported.reshape(1, -1, 3))[0] * weight,
            weight,
            radius=radius,
            min_pixels=max(8, min_pixels * 2),
            limit=3,
            seen=seen,
            far_gate=1.6,
        )
        colors = _prune_by_error_rise(
            med[soft | flat],
            [*colors, *extras],
            weight,
            max_colors,
            tolerance=1.2 * radius,
        )
    return tuple(colors)


def soft_ramp_palette(
    image: Image.Image,
    *,
    max_colors: int = 24,
    accents: tuple[str, ...] = (),
    max_side: int = 512,
) -> tuple[str, ...]:
    """Evenly stepped inks for glossy icons (sheens, lit propellers, domes).

    Quantizing the whole raster spends slots on blue↔yellow AA mixes (olive,
    teal-grey, brown) while a wide sheen gets only two or three blues that
    posterize into jagged shards. Here only locally smooth pixels vote, so
    k-means places steps along the real gradients. `accents` (e.g. the
    regular suggestion) re-adds thin distinct inks such as white linework
    that never pass the smoothness gate, unless they are a mix of two steps.
    """
    from PIL import ImageFilter

    rgba_img = image.convert("RGBA")
    width, height = rgba_img.size
    if max(width, height) > max_side:
        scale = max_side / float(max(width, height))
        rgba_img = rgba_img.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.BOX,
        )
    rgba = np.asarray(rgba_img, dtype=np.uint8)
    # Glass icon bodies sit at alpha ≈ 240; they are still the fill, not fringe.
    opaque = rgba[..., 3] >= 200
    med_img = Image.fromarray(np.ascontiguousarray(rgba[..., :3]), "RGB").filter(
        ImageFilter.MedianFilter(3)
    )
    med = np.asarray(med_img, dtype=np.uint8)
    hi = np.asarray(med_img.filter(ImageFilter.MaxFilter(5)), dtype=np.int16)
    lo = np.asarray(med_img.filter(ImageFilter.MinFilter(5)), dtype=np.int16)
    smooth = ((hi - lo).max(axis=2) <= 28) & opaque
    pixels = med[smooth]
    if len(pixels) < 256:
        return ()
    pixels = np.ascontiguousarray(pixels[:: max(1, len(pixels) // 60_000)])
    lab = srgb_u8_to_oklab(pixels.reshape(1, -1, 3))[0].astype(np.float64)

    def _sq_dist(points: np.ndarray, centers: np.ndarray) -> np.ndarray:
        return (
            (points * points).sum(-1)[:, None]
            - 2.0 * points @ centers.T
            + (centers * centers).sum(-1)[None, :]
        )

    side = int(np.sqrt(len(pixels)))
    square = Image.fromarray(pixels[: side * side].reshape(side, side, 3), "RGB")
    method = getattr(Image.Quantize, "MAXCOVERAGE", Image.Quantize.MEDIANCUT)
    seed = square.quantize(colors=max_colors, method=method, dither=Image.Dither.NONE)
    raw = np.asarray((seed.getpalette() or [])[: max_colors * 3], dtype=np.uint8)
    seeds = raw.reshape(-1, 3)[np.asarray(seed.histogram()[: len(raw) // 3]) > 0]
    if len(seeds) == 0:
        return ()
    centers = srgb_u8_to_oklab(seeds.reshape(1, -1, 3))[0].astype(np.float64)
    min_pixels = max(16, len(lab) // 2000)
    for _ in range(10):
        assign = np.argmin(_sq_dist(lab, centers), axis=1)
        counts = np.bincount(assign, minlength=len(centers))
        for i in np.nonzero(counts)[0]:
            centers[i] = lab[assign == i].mean(axis=0)
        centers = centers[counts >= min_pixels]
        if len(centers) == 0:
            return ()
    # Near-twin steps waste a slot; ~0.012 OKLab is below a visible band.
    assign = np.argmin(_sq_dist(lab, centers), axis=1)
    counts = np.bincount(assign, minlength=len(centers))
    order = np.argsort(-counts)
    kept: list[int] = []
    for i in order.tolist():
        if counts[i] < min_pixels:
            continue
        if kept and float(np.sqrt(_sq_dist(centers[[i]], centers[kept]).min())) < 0.012:
            continue
        kept.append(i)
    colors: list[str] = []
    seen: set[str] = set()
    for i in kept:
        median = np.median(pixels[assign == i], axis=0)
        hex_color = normalize_hex(rgb_to_hex((int(median[0]), int(median[1]), int(median[2]))))
        if hex_color not in seen:
            seen.add(hex_color)
            colors.append(hex_color)
    if not accents:
        return tuple(colors[:max_colors])
    step_lab = srgb_u8_to_oklab(
        np.asarray([hex_to_rgb(c) for c in colors], dtype=np.uint8).reshape(1, -1, 3)
    )[0].astype(np.float64)
    known_rgb = [np.asarray(hex_to_rgb(c), dtype=np.float64) for c in colors]
    body = rgba[..., :3][opaque].astype(np.int16)
    min_support = max(8, int(0.001 * len(body)))
    extras: list[str] = []
    for accent in accents:
        hex_color = normalize_hex(accent)
        if hex_color in seen:
            continue
        rgb = np.asarray(hex_to_rgb(hex_color), dtype=np.float64)
        # Shadow / matte inks that no opaque body pixel actually shows.
        support = int((np.abs(body - rgb.astype(np.int16)).max(axis=1) <= 24).sum())
        if support < min_support:
            continue
        point = srgb_u8_to_oklab(rgb.astype(np.uint8).reshape(1, 1, 3))[0, 0]
        if float(np.sqrt(((step_lab - point) ** 2).sum(-1).min())) < 0.06:
            continue
        # AA edges blend in gamma sRGB, so test for mixes there.
        if _is_mix_of(rgb, np.asarray(known_rgb), tol=24.0):
            continue
        seen.add(hex_color)
        extras.append(hex_color)
        known_rgb.append(rgb)
    budget = max(0, max_colors - len(extras))
    return tuple([*colors[:budget], *extras][:max_colors])


def prune_aa_fringe(
    image: Image.Image,
    palette: tuple[str, ...],
    *,
    min_area: float = 0.006,
    rescue: float = 0.0012,
) -> tuple[str, ...]:
    """Drop anti-aliased mix colors that have no flat interior.

    A 1 px ring of pale blue between a blue fill and a white mark is a blend,
    not an ink. Shading bands and real accents keep their slot when they own
    a measurable flat area, or when they are not a mix of two larger inks.
    """
    from PIL import ImageFilter

    if len(palette) <= 2:
        return palette
    rgba = image.convert("RGBA")
    width, height = rgba.size
    if max(width, height) > 360:
        scale = 360 / float(max(width, height))
        rgba = rgba.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.BOX,
        )
    arr = np.asarray(rgba, dtype=np.uint8)
    opaque = arr[..., 3] >= 128
    total = int(opaque.sum())
    if total < 32:
        return palette
    rgb_img = Image.fromarray(np.ascontiguousarray(arr[..., :3]), "RGB")
    hi = np.asarray(rgb_img.filter(ImageFilter.MaxFilter(5)), dtype=np.int16)
    lo = np.asarray(rgb_img.filter(ImageFilter.MinFilter(5)), dtype=np.int16)
    flat = ((hi - lo).max(axis=2) <= 14) & opaque
    pixels = arr[..., :3].astype(np.int16)
    rgbs = [hex_to_rgb(color) for color in palette]
    shares: list[float] = []
    covered: list[float] = []
    for rgb in rgbs:
        delta = np.abs(pixels - np.asarray(rgb, dtype=np.int16)).max(axis=2)
        shares.append(float(((delta <= 12) & flat).sum()) / float(total))
        # Any opaque support, flat or not. A shading band is wide but not flat;
        # a 1 px ring stays under a few percent.
        covered.append(float(((delta <= 18) & opaque).sum()) / float(total))
    kept = [
        index
        for index, share in enumerate(shares)
        if share >= min_area or covered[index] >= 0.04
    ]
    kept_rgb = (
        np.asarray([rgbs[index] for index in kept], dtype=np.float64)
        if kept
        else np.zeros((0, 3), dtype=np.float64)
    )
    for index, share in enumerate(shares):
        if index in kept:
            continue
        # Thin frames (a set-square, a needle) are not 5×5-flat, but they are
        # not mixes of the big fills either. 1 px rims stay under ~1.5%.
        if share < rescue and covered[index] < 0.015:
            continue
        point = np.asarray(rgbs[index], dtype=np.float64)
        if (
            len(kept_rgb) >= 2
            and covered[index] < 0.04
            and _is_mix_of(point, kept_rgb, tol=22.0)
        ):
            continue
        kept.append(index)
        kept_rgb = np.vstack([kept_rgb, point]) if len(kept_rgb) else point.reshape(1, 3)
    if len(kept) < 2:
        kept = sorted(range(len(shares)), key=lambda index: -shares[index])[:2]
    chosen = set(kept)
    pruned = tuple(palette[index] for index in range(len(palette)) if index in chosen)
    return pruned or palette


def _is_mix_of(point: np.ndarray, centers: np.ndarray, *, tol: float) -> bool:
    """True when `point` lies on a segment between two of `centers` (AA blend)."""
    n = len(centers)
    for i in range(n):
        a = centers[i]
        ab = centers[i + 1 :] - a
        if not len(ab):
            continue
        denom = np.maximum((ab * ab).sum(-1), 1e-12)
        t = ((point - a) * ab).sum(-1) / denom
        inside = (t > 0.15) & (t < 0.85)
        resid = point - (a + ab * np.clip(t, 0.0, 1.0)[:, None])
        if np.any(inside & (np.sqrt((resid * resid).sum(-1)) < tol)):
            return True
    return False


def _prune_by_error_rise(
    pixels: np.ndarray,
    colors: list[str],
    weight: np.ndarray,
    max_colors: int,
    *,
    tolerance: float = 0.0,
) -> list[str]:
    """Drop inks whose removal raises snap error over `pixels` the least.

    The dominant (first) ink is always kept. A faint base shade can then yield
    its slot to a small but distinct solid found by the residual passes.

    Error below `tolerance` is free: a wide pastel with a near-twin otherwise
    outvotes a small book spine whose pixels would snap to a different hue.
    """
    if len(colors) <= max_colors:
        return list(colors)
    sample = np.ascontiguousarray(pixels[:: max(1, len(pixels) // 200_000)])
    lab = srgb_u8_to_oklab(sample.reshape(1, -1, 3))[0] * weight
    rgb = np.asarray([hex_to_rgb(c) for c in colors], dtype=np.uint8)
    c = srgb_u8_to_oklab(rgb.reshape(1, -1, 3))[0] * weight
    d = (lab * lab).sum(-1)[:, None] - 2.0 * lab @ c.T + (c * c).sum(-1)[None, :]
    dist = np.maximum(np.sqrt(np.maximum(d, 0.0)) - tolerance, 0.0)
    alive = list(range(len(colors)))
    while len(alive) > max_colors:
        sub = dist[:, alive]
        order = np.argsort(sub, axis=1)
        rows = np.arange(len(sub))
        first = sub[rows, order[:, 0]]
        second = sub[rows, order[:, 1]]
        rise = np.bincount(order[:, 0], weights=second - first, minlength=len(alive))
        rise[0] = np.inf
        alive.pop(int(np.argmin(rise)))
    return [colors[i] for i in alive]


def _thin_strip_inks(
    pixels: np.ndarray,
    centers: np.ndarray,
    weight: np.ndarray,
    *,
    radius: float,
    min_pixels: int,
    limit: int,
    seen: set[str],
    far_gate: float = 2.0,
) -> list[str]:
    if limit <= 0 or len(pixels) < min_pixels:
        return []
    lab = srgb_u8_to_oklab(np.ascontiguousarray(pixels).reshape(1, -1, 3))[0] * weight

    def _nearest(c: np.ndarray) -> np.ndarray:
        d = (
            (lab * lab).sum(-1)[:, None]
            - 2.0 * lab @ c.T
            + (c * c).sum(-1)[None, :]
        )
        return np.sqrt(np.maximum(d.min(axis=1), 0.0))

    # Default twice the vote radius: blends between two chosen inks stay unclaimed.
    far = _nearest(centers) > far_gate * radius
    added: list[str] = []
    for _ in range(limit):
        if int(far.sum()) < min_pixels:
            break
        cand = lab[far]
        sample = cand[:: max(1, len(cand) // 4000)]
        d = (
            (sample * sample).sum(-1)[:, None]
            - 2.0 * sample @ cand.T
            + (cand * cand).sum(-1)[None, :]
        )
        near = d < radius * radius
        best = int(np.argmax(near.sum(axis=1)))
        members = near[best]
        if int(members.sum()) < min_pixels:
            break
        median = np.median(pixels[far][members], axis=0)
        hex_color = normalize_hex(
            rgb_to_hex((int(median[0]), int(median[1]), int(median[2])))
        )
        idx = np.nonzero(far)[0][members]
        far[idx] = False
        if hex_color in seen:
            continue
        seen.add(hex_color)
        added.append(hex_color)
    return added


def snap_image_to_palette(
    image: Image.Image,
    palette: tuple[str, ...],
    *,
    chroma_weight: float = 1.0,
    tolerance: int = 255,
    remaps: tuple[tuple[str, str], ...] = (),
) -> Image.Image:
    """Replace pixels with nearest palette colors (optionally gated by tolerance).

    When `tolerance` < 255, pixels farther than the gate keep their original RGB.
    Remaps run afterward; a target of `#00000000` makes matching pixels transparent.
    """
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    out = rgba.copy()
    if palette:
        colors = np.asarray([hex_to_rgb(color) for color in palette], dtype=np.uint8)
        index, dist = nearest_oklab(
            srgb_u8_to_oklab(rgba[..., :3]),
            srgb_u8_to_oklab(colors),
            chroma_weight=chroma_weight,
        )
        snapped = colors[index]
        if int(tolerance) >= 255:
            out[..., :3] = snapped
        else:
            limit = (max(0, int(tolerance)) / 255.0) ** 2 * 0.45
            mask = dist <= limit
            out_rgb = out[..., :3].copy()
            out_rgb[mask] = snapped[mask]
            out[..., :3] = out_rgb
    if remaps:
        out = _apply_image_remaps(out, remaps)
    return Image.fromarray(out, mode="RGBA")


def _apply_image_remaps(
    rgba: np.ndarray,
    remaps: tuple[tuple[str, str], ...],
) -> np.ndarray:
    out = rgba.copy()
    for source, target in remaps:
        try:
            src = hex_to_rgb(source)
        except ValueError:
            continue
        match = (
            (out[..., 0] == src[0])
            & (out[..., 1] == src[1])
            & (out[..., 2] == src[2])
            & (out[..., 3] > 0)
        )
        if not np.any(match):
            continue
        if target == "#00000000":
            out[..., 3][match] = 0
            continue
        try:
            dst = hex_to_rgb(target)
        except ValueError:
            continue
        out[..., 0][match] = dst[0]
        out[..., 1][match] = dst[1]
        out[..., 2][match] = dst[2]
    return out


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
