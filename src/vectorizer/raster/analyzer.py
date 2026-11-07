"""Content-aware analysis that drives Automatic mode.

This is not a proprietary tracer. It classifies the raster, estimates geometry-
friendly parameters, and suggests preprocess steps that make VTracer produce
cleaner, more editable vectors — the same decisions a skilled operator would
make by eye.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

import numpy as np
from PIL import Image, ImageChops, ImageFilter, ImageStat

from vectorizer.domain.settings import (
    AutomaticQuality,
    ColorMode,
    EdgeTreatment,
    HierarchyMode,
    PathFitMode,
    TraceSettings,
    WorkflowMode,
)
from vectorizer.raster.palette import suggest_palettes


class ContentKind(str, Enum):
    """Coarse content class used to pick a tracing recipe."""

    BINARY_MARK = "binary_mark"
    FLAT_LOGO = "flat_logo"
    PIXEL_ART = "pixel_art"
    LINE_ART = "line_art"
    ILLUSTRATION = "illustration"
    PHOTO = "photo"
    GRADIENT = "gradient"


@dataclass(frozen=True)
class ImageMetrics:
    width: int
    height: int
    pixel_count: int
    unique_colors: int | None
    unique_colors_exact: bool
    has_alpha: bool
    opaque_ratio: float
    edge_density: float
    noise_score: float
    fill_ratio: float
    corner_sharpness: float
    background_rgb: tuple[int, int, int] | None
    background_confidence: float
    border_match_ratio: float
    palette_estimate: int
    minority_ratio: float
    foreground_coverage: float
    # Share of pixels that sit near a small solid palette (anti-aliased logos
    # have huge unique-color counts but still score high here).
    flat_mass: float
    # Dark ink-like outline energy — high for cel cartoons, low for photos.
    ink_outline_score: float


@dataclass(frozen=True)
class ImageAnalysis:
    width: int
    height: int
    unique_colors: int | None
    has_alpha: bool
    opaque_ratio: float
    suggested: TraceSettings
    photo_like: bool
    content_kind: ContentKind
    metrics: ImageMetrics
    notes: tuple[str, ...]


def apply_automatic_quality(
    settings: TraceSettings,
    quality: AutomaticQuality,
    *,
    photo_like: bool = False,
    content_kind: ContentKind | None = None,
) -> TraceSettings:
    """Tune analyzer defaults for Fast / Balanced / High detail."""
    quality = AutomaticQuality(quality)
    base = settings.validated()
    kind = content_kind or (ContentKind.PHOTO if photo_like else ContentKind.ILLUSTRATION)

    if quality == AutomaticQuality.BALANCED:
        return replace(base, automatic_quality=quality, workflow=WorkflowMode.AUTOMATIC)

    if quality == AutomaticQuality.FAST:
        tuned = replace(
            base,
            automatic_quality=quality,
            workflow=WorkflowMode.AUTOMATIC,
            filter_speckle=min(64, base.filter_speckle + 4),
            color_precision=max(1, base.color_precision - 1),
            layer_difference=min(128, base.layer_difference + 8),
            corner_threshold=min(180, base.corner_threshold + 15),
            length_threshold=min(10.0, base.length_threshold + 0.5),
            max_iterations=max(1, min(6, base.max_iterations)),
            path_precision=max(0, base.path_precision - 1),
            splice_threshold=min(180, base.splice_threshold + 10),
        )
        if kind in {ContentKind.PHOTO, ContentKind.GRADIENT} and tuned.target_colors == 0:
            tuned = replace(tuned, target_colors=20)
        # Illustrations already constrain via palette — do not double-posterize.
        return tuned.validated()

    # High detail — preserve structure; spend more fitting budget.
    # Cel illustrations must keep a positive layer_difference: High used to
    # drive it to 0 (base 4 − 4), which shredded flat yellow curtains into
    # white/orange VTracer shards.
    layer_floor = 4 if kind == ContentKind.ILLUSTRATION else 0
    tuned = replace(
        base,
        automatic_quality=quality,
        workflow=WorkflowMode.AUTOMATIC,
        filter_speckle=max(0, base.filter_speckle - 2),
        color_precision=min(8, base.color_precision + 1),
        layer_difference=max(layer_floor, base.layer_difference - 4),
        corner_threshold=max(0, base.corner_threshold - 10),
        length_threshold=max(3.5, base.length_threshold - 0.3),
        max_iterations=min(64, base.max_iterations + 6),
        path_precision=min(12, base.path_precision + 1),
        splice_threshold=max(0, base.splice_threshold - 5),
    )
    if kind in {ContentKind.PHOTO, ContentKind.GRADIENT} and tuned.target_colors:
        # High detail: allow a richer palette before tracing.
        tuned = replace(tuned, target_colors=min(64, tuned.target_colors + 12))
    if kind == ContentKind.ILLUSTRATION and tuned.palette and len(tuned.palette) < 24:
        # Prefer the analyzer's richer suggestion when High detail is chosen.
        # Palette expansion itself happens in analyze_image; here we only
        # tighten geometry further for ink-heavy cartoons.
        tuned = replace(
            tuned,
            corner_threshold=max(0, tuned.corner_threshold - 4),
            path_precision=min(12, tuned.path_precision + 1),
        )
    return tuned.validated()


def analyze_image(
    image: Image.Image,
    *,
    quality: AutomaticQuality = AutomaticQuality.BALANCED,
) -> ImageAnalysis:
    # Match preprocess: scrub chroma-key fringe, then bake near-black transparent
    # mattes so icons classify as logos/binary instead of sparse illustrations.
    from vectorizer.raster.preprocess import scrub_chroma_key_alpha, solidify_black_matte

    image = solidify_black_matte(scrub_chroma_key_alpha(image))
    metrics = _compute_metrics(image)
    kind = _classify(metrics)
    photo_like = kind in {ContentKind.PHOTO, ContentKind.GRADIENT}
    base = _settings_for_kind(kind, metrics)
    treatment = _edge_for_kind(kind, metrics)
    palette: tuple[str, ...] = ()
    if treatment in {EdgeTreatment.BLENDED, EdgeTreatment.PHOTO}:
        # Only drop the paper color from the palette when knock-out will clear it;
        # otherwise white must stay so the blend tracer can keep paper as a fill.
        ignore = (
            metrics.background_rgb
            if base.remove_background and metrics.background_confidence >= 0.7
            else None
        )
        suggestions = suggest_palettes(image, ignore_rgb=ignore)
        count = suggestions.best
        ink_heavy = metrics.ink_outline_score >= 0.008
        # Cel / multi-fill scenes need more than 16 inks so teal phones and
        # orange chairs stay distinct; photos stay capped lower for editability.
        palette_cap = 32 if (kind == ContentKind.ILLUSTRATION and ink_heavy) else 16
        if treatment == EdgeTreatment.PHOTO and not (
            kind == ContentKind.ILLUSTRATION and ink_heavy
        ):
            # True photos/gradients: keep the posterize budget editable.
            # Never hard-cap at 12 — that merges walls/floors into white/olive.
            ink_budget = max(suggestions.best, min(16, max(12, metrics.palette_estimate)))
            count = min(16, ink_budget)
            if count not in suggestions.palettes:
                count = min(
                    suggestions.palettes,
                    key=lambda n: (abs(n - count), -n),
                )
        elif treatment == EdgeTreatment.PHOTO and kind == ContentKind.ILLUSTRATION:
            # Cel scenes routed to VTracer still need the rich illustration
            # palette (walls, furniture, accents, ink) — the photo 16-cap
            # merged couch shadows and purple tables into muddy midtones.
            ink_budget = max(
                2,
                metrics.palette_estimate,
                min(palette_cap, max(16 if ink_heavy else 8, suggestions.best)),
            )
            count = min(palette_cap, max(count, ink_budget))
            if count not in suggestions.palettes:
                count = min(
                    suggestions.palettes,
                    key=lambda n: (abs(n - count), -n),
                )
        else:
            # Blended artwork: prefer the solid-ink estimate over AA fringe colors.
            ink_budget = max(2, metrics.palette_estimate)
            if base.remove_background and metrics.background_rgb is not None:
                # Paper is knocked out, so it should not consume a palette slot.
                ink_budget = max(2, ink_budget - 1)
            # Illustrations need headroom so large scene colours survive.
            if kind == ContentKind.ILLUSTRATION:
                scene_floor = 16 if ink_heavy else 8
                ink_budget = max(
                    ink_budget,
                    min(palette_cap, max(scene_floor, suggestions.best)),
                )
            # Flat logos with hard left/right shading need more than 3 inks
            # (light + dark orange, white + off-white, black). Soft app icons
            # with gradients need a richer posterize budget than `best` alone.
            if kind == ContentKind.FLAT_LOGO:
                soft_logo = metrics.flat_mass < 0.85
                logo_floor = 12 if soft_logo else (8 if metrics.flat_mass < 0.92 else 5)
                if soft_logo:
                    ink_budget = max(
                        ink_budget,
                        min(16, max(logo_floor, metrics.palette_estimate // 2)),
                    )
                else:
                    ink_budget = max(ink_budget, min(16, max(suggestions.best, logo_floor)))
            count = (
                min(count, ink_budget)
                if kind != ContentKind.ILLUSTRATION
                else min(palette_cap, max(count, ink_budget))
            )
            if kind == ContentKind.FLAT_LOGO:
                soft_logo = metrics.flat_mass < 0.85
                logo_floor = 12 if soft_logo else (8 if metrics.flat_mass < 0.92 else 5)
                target = (
                    min(16, max(logo_floor, metrics.palette_estimate // 2))
                    if soft_logo
                    else min(16, max(suggestions.best, logo_floor))
                )
                count = max(count, target)
            # Snap to a palette we actually built.
            if count not in suggestions.palettes:
                count = min(
                    suggestions.palettes,
                    key=lambda n: (abs(n - count), -n),
                )
        palette = suggestions.palettes.get(count, ())
        cel_flats = False
        cutout_badge = (
            metrics.has_alpha
            and metrics.opaque_ratio < 0.92
            and metrics.opaque_ratio >= 0.50
            and ink_heavy
        )
        if (
            treatment == EdgeTreatment.PHOTO
            and kind == ContentKind.ILLUSTRATION
            and ink_heavy
        ):
            # Cel scenes on the VTracer path: pick inks from flat interiors so
            # small distinct fills (white sails, gold frames) keep a slot and
            # brown outline fringe does not.
            from vectorizer.raster.palette import cel_fill_palette

            flats = cel_fill_palette(image, max_colors=31, thin_strip_residuals=True)
            if len(flats) >= 6:
                cel_flats = True
                palette = (
                    flats if base.remove_background else _fold_background_into(flats, metrics)
                )
                palette_cap = 32
        elif (
            treatment == EdgeTreatment.BLENDED
            and cutout_badge
            and kind in {ContentKind.FLAT_LOGO, ContentKind.ILLUSTRATION}
        ):
            # Transparent crests/badges: AA fringe invents greys/yellows that
            # soft-iso then paints as white slivers between ink and fill.
            # Flat-interior voting keeps the true solids (olive/grey/gold/red).
            from vectorizer.raster.palette import cel_fill_palette

            flats = cel_fill_palette(image, max_colors=14, min_share=0.0003)
            if len(flats) >= 4 and _flats_cover_cutout(image, flats):
                cel_flats = True
                palette = flats
                palette_cap = 16
        # When the scene fill stays in the output, pin the exact detected
        # background colour so walls/skies cannot collapse to near-white.
        if (
            palette
            and not cel_flats
            and not base.remove_background
            and metrics.background_rgb is not None
            and metrics.background_confidence >= 0.45
        ):
            from vectorizer.domain.settings import normalize_hex
            from vectorizer.raster.color import rgb_to_hex

            bg_hex = normalize_hex(rgb_to_hex(metrics.background_rgb))
            if bg_hex not in palette:
                palette = (bg_hex, *palette)[:palette_cap]
            else:
                # Move it to the front so underlays / paint order prefer it.
                palette = (bg_hex, *[c for c in palette if c != bg_hex])
        # Keep a dedicated dark ink slot for cel outlines when present.
        if (
            palette
            and ink_heavy
            and kind in {ContentKind.ILLUSTRATION, ContentKind.FLAT_LOGO}
        ):
            palette = _ensure_dark_ink(palette, image, max_colors=palette_cap)
        # Never keep chroma-key magenta in a preserve-transparency palette.
        if palette and metrics.has_alpha and base.preserve_transparency:
            from vectorizer.raster.color import hex_to_rgb as _hex_to_rgb

            cleaned_pal = []
            for color in palette:
                r, g, b = _hex_to_rgb(color)
                if r >= 200 and b >= 200 and g <= 80:
                    continue
                cleaned_pal.append(color)
            if cleaned_pal:
                palette = tuple(cleaned_pal)
        # Do not median-refine the whole palette here: averaging JPEG shadow
        # into orange couches turns them muddy brown. Chroma-aware snap at
        # label time is enough to keep pink walls off salmon fills.
    base = replace(base, edge_treatment=treatment, palette=palette)
    suggested = apply_automatic_quality(
        base, quality, photo_like=photo_like, content_kind=kind
    )
    notes = _build_notes(kind, metrics, quality, suggested)

    return ImageAnalysis(
        width=metrics.width,
        height=metrics.height,
        unique_colors=metrics.unique_colors,
        has_alpha=metrics.has_alpha,
        opaque_ratio=metrics.opaque_ratio,
        suggested=suggested,
        photo_like=photo_like,
        content_kind=kind,
        metrics=metrics,
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _compute_metrics(image: Image.Image) -> ImageMetrics:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixel_count = max(1, width * height)

    alpha = rgba.getchannel("A")
    extrema = alpha.getextrema()
    has_alpha = bool(extrema and extrema[0] < 255)
    hist = alpha.histogram()
    opaque_pixels = sum(hist[128:]) if len(hist) == 256 else pixel_count
    opaque_ratio = opaque_pixels / float(pixel_count)

    rgb = rgba.convert("RGB")
    unique, exact = _estimate_unique_colors(rgb)
    bg_rgb, bg_conf, border_match = _detect_background(rgba)
    edge_density = _edge_density(rgb, alpha if has_alpha else None)
    noise_score = _noise_score(rgb, unique_colors=unique)
    fill_ratio, foreground_coverage = _foreground_geometry(
        rgb,
        alpha if has_alpha else None,
        background_rgb=bg_rgb,
    )
    corner_sharpness = _corner_sharpness(rgb)
    minority_ratio = _minority_color_ratio(rgb, unique)
    flat_mass, palette_estimate = _flat_mass_and_palette(rgb, unique, exact)
    ink_outline_score = _ink_outline_score(rgb)

    return ImageMetrics(
        width=width,
        height=height,
        pixel_count=pixel_count,
        unique_colors=unique,
        unique_colors_exact=exact,
        has_alpha=has_alpha,
        opaque_ratio=opaque_ratio,
        edge_density=edge_density,
        noise_score=noise_score,
        fill_ratio=fill_ratio,
        corner_sharpness=corner_sharpness,
        background_rgb=bg_rgb,
        background_confidence=bg_conf,
        border_match_ratio=border_match,
        palette_estimate=palette_estimate,
        minority_ratio=minority_ratio,
        foreground_coverage=foreground_coverage,
        flat_mass=flat_mass,
        ink_outline_score=ink_outline_score,
    )


def _estimate_unique_colors(rgb: Image.Image) -> tuple[int | None, bool]:
    """Return (count, exact). Exact fails gracefully on continuous-tone images."""
    colors = rgb.getcolors(maxcolors=8192)
    if colors is not None:
        return len(colors), True
    # Approximate on a downscaled copy so multi-megapixel photos stay cheap.
    probe = rgb
    w, h = probe.size
    if max(w, h) > 384:
        scale = 384 / float(max(w, h))
        probe = probe.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))),
            Image.Resampling.BILINEAR,
        )
    quantized = probe.quantize(
        colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
    )
    # Histogram over palette indices avoids materializing a Python set of every pixel.
    approx = sum(1 for freq in quantized.histogram() if freq > 0)
    # If we saturated the 128-slot palette, treat as "many".
    if approx >= 120:
        return None, False
    return max(approx, 64), False


def _edge_density(rgb: Image.Image, alpha: Image.Image | None) -> float:
    gray = rgb.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    if alpha is not None:
        # Ignore fully transparent regions so hollow icons are not under-estimated.
        edges = ImageChops.multiply(edges, alpha.point(lambda a: 255 if a >= 128 else 0))
    stat = ImageStat.Stat(edges)
    mean = float(stat.mean[0]) if stat.mean else 0.0
    return max(0.0, min(1.0, mean / 64.0))


def _noise_score(rgb: Image.Image, *, unique_colors: int | None) -> float:
    """High-frequency residual after a light blur. Photos/JPEG score higher.

    Limited-palette art has hard edges that look "noisy" to a blur residual;
    clamp those so pixel art and logos are not misclassified as photos.
    """
    if unique_colors is not None and unique_colors <= 24:
        return min(0.22, unique_colors / 120.0)

    gray = rgb.convert("L")
    # Downscale large images so analysis stays cheap and stable.
    w, h = gray.size
    if max(w, h) > 512:
        scale = 512 / float(max(w, h))
        gray = gray.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))),
            Image.Resampling.BILINEAR,
        )
    blurred = gray.filter(ImageFilter.GaussianBlur(radius=1.2))
    residual = ImageChops.difference(gray, blurred)
    stat = ImageStat.Stat(residual)
    mean = float(stat.mean[0]) if stat.mean else 0.0
    return max(0.0, min(1.0, mean / 18.0))


def _foreground_geometry(
    rgb: Image.Image,
    alpha: Image.Image | None,
    *,
    background_rgb: tuple[int, int, int] | None,
) -> tuple[float, float]:
    """Return (fill_ratio, foreground_coverage).

    `fill_ratio` is high for solid shapes and lower when foreground is mostly
    edge. `foreground_coverage` is the share of pixels that are not background.
    Thin line art has very low coverage; chunky pixel art / logos do not.
    """
    gray = rgb.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_mask = edges.point(lambda v: 255 if v > 24 else 0)
    pixel_count = max(1, gray.size[0] * gray.size[1])

    if alpha is not None:
        opaque = alpha.point(lambda a: 255 if a >= 128 else 0)
    else:
        opaque = Image.new("L", gray.size, 255)

    if background_rgb is not None:
        tr, tg, tb = background_rgb
        tol = 22
        r, g, b = rgb.split()
        near = ImageChops.multiply(
            ImageChops.multiply(
                r.point(lambda v, t=tr, o=tol: 255 if abs(v - t) <= o else 0),
                g.point(lambda v, t=tg, o=tol: 255 if abs(v - t) <= o else 0),
            ),
            b.point(lambda v, t=tb, o=tol: 255 if abs(v - t) <= o else 0),
        )
        fg = ImageChops.multiply(opaque, ImageChops.invert(near))
    else:
        fg = opaque

    fg_count = ImageStat.Stat(fg).sum[0] / 255.0
    coverage = max(0.0, min(1.0, fg_count / float(pixel_count)))
    if fg_count < 1:
        return 0.0, coverage
    fg_edges = ImageChops.multiply(fg, edge_mask)
    edge_count = ImageStat.Stat(fg_edges).sum[0] / 255.0
    fill_ratio = max(0.0, min(1.0, 1.0 - (edge_count / fg_count)))
    return fill_ratio, coverage


def _minority_color_ratio(rgb: Image.Image, unique: int | None) -> float:
    """Share of the least-used color when the palette is tiny (hole heuristic)."""
    if unique is None or unique > 4:
        return 0.0
    colors = rgb.getcolors(maxcolors=64)
    if not colors:
        return 0.0
    total = sum(count for count, _pixel in colors) or 1
    smallest = min(count for count, _pixel in colors)
    return smallest / float(total)


def _corner_sharpness(rgb: Image.Image) -> float:
    """Higher when edges are crisp (logos) vs soft (photos / heavy AA)."""
    gray = rgb.convert("L")
    w, h = gray.size
    if max(w, h) > 384:
        scale = 384 / float(max(w, h))
        gray = gray.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))),
            Image.Resampling.BILINEAR,
        )
    edges = gray.filter(ImageFilter.FIND_EDGES)
    # Contrast of the edge map: sharp art concentrates energy in high bins.
    hist = edges.histogram()
    total = sum(hist) or 1
    strong = sum(hist[80:]) / total
    mid = sum(hist[20:80]) / total
    if strong + mid < 1e-6:
        return 0.0
    return max(0.0, min(1.0, strong / (strong + mid + 1e-6)))


def _ink_outline_score(rgb: Image.Image) -> float:
    """Share of dark outline pixels abutting much brighter fills.

    Cel cartoons score high (brown/black ink between flat colours). Photographs
    with large dark regions score near zero because their dark neighbours are
    also dark.
    """
    gray = rgb.convert("L")
    w, h = gray.size
    if max(w, h) > 512:
        scale = 512 / float(max(w, h))
        gray = gray.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))),
            Image.Resampling.BOX,
        )
    arr = np.asarray(gray, dtype=np.int16)
    padded = np.pad(arr, 1, mode="edge")
    neigh_max = np.maximum.reduce(
        [
            padded[:-2, 1:-1],
            padded[2:, 1:-1],
            padded[1:-1, :-2],
            padded[1:-1, 2:],
            padded[:-2, :-2],
            padded[:-2, 2:],
            padded[2:, :-2],
            padded[2:, 2:],
        ]
    )
    contrast = neigh_max - arr
    # Dark-ish ink (including brown) with a substantially brighter neighbour.
    outline = (arr <= 100) & (contrast >= 45)
    return float(outline.mean())


def _detect_background(
    rgba: Image.Image,
) -> tuple[tuple[int, int, int] | None, float, float]:
    """Consensus background from corners, with border-mode fallback for scenes.

    Living-room / cel scenes often put a floor colour in the bottom corners
    while the wall (true scene fill) dominates the top and side borders. When
    corner agreement is weak, prefer the dominant opaque border colour.
    """
    w, h = rgba.size
    if w < 4 or h < 4:
        return None, 0.0, 0.0

    patch = max(2, min(12, min(w, h) // 8))
    samples: list[tuple[int, int, int]] = []
    for x0, y0 in (
        (0, 0),
        (w - patch, 0),
        (0, h - patch),
        (w - patch, h - patch),
    ):
        crop = rgba.crop((x0, y0, x0 + patch, y0 + patch))
        pixels = (
            crop.get_flattened_data()
            if hasattr(crop, "get_flattened_data")
            else crop.getdata()
        )
        for pixel in pixels:
            r, g, b, a = pixel
            if a < 128:
                continue
            samples.append((r, g, b))

    if len(samples) < 8:
        # Mostly transparent — no opaque background to knock out.
        return None, 0.0, 0.0

    # Median of corner samples is robust to a few foreground pixels.
    rs = sorted(p[0] for p in samples)
    gs = sorted(p[1] for p in samples)
    bs = sorted(p[2] for p in samples)
    mid = len(samples) // 2
    corner_bg = (rs[mid], gs[mid], bs[mid])

    # Corner consensus: fraction of samples near the median.
    tol = 18
    near = sum(
        1
        for r, g, b in samples
        if abs(r - corner_bg[0]) <= tol
        and abs(g - corner_bg[1]) <= tol
        and abs(b - corner_bg[2]) <= tol
    )
    corner_agreement = near / float(len(samples))
    border_match = _border_match_ratio(rgba, corner_bg, tol=tol)
    confidence = 0.55 * corner_agreement + 0.45 * border_match

    if corner_agreement >= 0.72 and border_match >= 0.35:
        return corner_bg, confidence, border_match

    # Scene fallback: dominant colour along the full border ring (walls beat
    # floors that only occupy the bottom edge).
    border_bg = _dominant_border_color(rgba, tol=tol)
    if border_bg is not None:
        border_match_b = _border_match_ratio(rgba, border_bg, tol=tol)
        if border_match_b >= max(border_match, 0.28):
            # Mild confidence: enough to pin the palette / underlay, not enough
            # to auto-knock the fill out of a cel scene.
            return border_bg, min(0.82, 0.4 + 0.5 * border_match_b), border_match_b

    if corner_agreement < 0.72:
        return corner_bg, confidence * 0.5, border_match
    return corner_bg, confidence, border_match


def _dominant_border_color(
    rgba: Image.Image,
    *,
    tol: int,
) -> tuple[int, int, int] | None:
    """Mode of quantized opaque border pixels."""
    w, h = rgba.size
    step = max(1, max(w, h) // 256)
    arr = np.asarray(rgba, dtype=np.uint8)
    xs = list(range(0, w, step))
    ys = list(range(step, h - step, step))
    samples: list[np.ndarray] = [arr[0, xs], arr[h - 1, xs]]
    if ys:
        samples.append(arr[ys, 0])
        samples.append(arr[ys, w - 1])
    ring = np.concatenate(samples, axis=0)
    opaque = ring[:, 3] >= 128
    if not np.any(opaque):
        return None
    pixels = ring[opaque, :3].astype(np.int16)
    # Bucket to keep JPEG fringe from splitting one wall colour into many bins.
    buckets = (pixels // 8) * 8 + 4
    # Count unique rows.
    flat = buckets[:, 0].astype(np.int32) * 65536 + buckets[:, 1].astype(np.int32) * 256 + buckets[:, 2]
    values, counts = np.unique(flat, return_counts=True)
    key = int(values[int(np.argmax(counts))])
    return ((key >> 16) & 255, (key >> 8) & 255, key & 255)


def _border_match_ratio(
    rgba: Image.Image,
    color: tuple[int, int, int],
    *,
    tol: int,
) -> float:
    w, h = rgba.size
    tr, tg, tb = color
    # Sample the outer ring without walking every pixel on huge images.
    step = max(1, max(w, h) // 256)
    arr = np.asarray(rgba, dtype=np.uint8)
    xs = list(range(0, w, step))
    ys = list(range(step, h - step, step))
    samples: list[np.ndarray] = [
        arr[0, xs],
        arr[h - 1, xs],
    ]
    if ys:
        samples.append(arr[ys, 0])
        samples.append(arr[ys, w - 1])
    ring = np.concatenate(samples, axis=0)
    opaque = ring[:, 3] >= 128
    if not np.any(opaque):
        return 0.0
    pixels = ring[opaque, :3].astype(np.int16)
    near = (
        (np.abs(pixels[:, 0] - tr) <= tol)
        & (np.abs(pixels[:, 1] - tg) <= tol)
        & (np.abs(pixels[:, 2] - tb) <= tol)
    )
    return float(near.mean())


def _analysis_probe(rgb: Image.Image, *, max_side: int = 256) -> Image.Image:
    w, h = rgb.size
    if max(w, h) <= max_side:
        return rgb
    scale = max_side / float(max(w, h))
    return rgb.resize(
        (max(1, int(w * scale)), max(1, int(h * scale))),
        Image.Resampling.BOX,
    )


def _flat_mass_and_palette(
    rgb: Image.Image,
    unique: int | None,
    exact: bool,
) -> tuple[float, int]:
    """Return (flat_mass, effective_palette_size).

    Anti-aliased logos inflate unique-color counts into the hundreds while still
    reconstructing cleanly from a handful of solid inks. `flat_mass` is the
    share of probe pixels whose OKLab distance to a 12-color MAXCOVERAGE
    palette stays within the blend-tracer "stable" band.
    """
    from vectorizer.raster.color import nearest_oklab, srgb_u8_to_oklab

    probe = _analysis_probe(rgb, max_side=256)
    method = getattr(Image.Quantize, "MAXCOVERAGE", Image.Quantize.MEDIANCUT)
    probe_arr = np.asarray(probe, dtype=np.uint8)
    probe_lab = srgb_u8_to_oklab(probe_arr)

    def _palette_colors(count: int) -> list[tuple[int, int, int]]:
        try:
            quantized = probe.quantize(
                colors=max(2, count), method=method, dither=Image.Dither.NONE
            )
        except Exception:
            quantized = probe.quantize(
                colors=max(2, count),
                method=Image.Quantize.MEDIANCUT,
                dither=Image.Dither.NONE,
            )
        palette = quantized.getpalette() or []
        colors: list[tuple[int, int, int]] = []
        for index, freq in enumerate(quantized.histogram()):
            if freq <= 0 or index * 3 + 2 >= len(palette):
                continue
            colors.append(
                (
                    int(palette[index * 3]),
                    int(palette[index * 3 + 1]),
                    int(palette[index * 3 + 2]),
                )
            )
        return colors

    colors12 = _palette_colors(12)
    if not colors12:
        fallback = max(2, unique or 24)
        return 0.0, fallback
    index, dist = nearest_oklab(
        probe_lab, srgb_u8_to_oklab(np.asarray(colors12, dtype=np.uint8))
    )
    flat_mass = float((dist <= 0.0025).mean())
    assigned = np.asarray(colors12, dtype=np.int16)[index]
    mean12 = float(np.abs(probe_arr.astype(np.int16) - assigned).mean())

    # Tiny exact palettes are trusted directly (pixel art, binary marks).
    if exact and unique is not None and unique <= 32 and flat_mass >= 0.98:
        return flat_mass, max(2, unique)

    candidates = (2, 3, 4, 6, 8, 12, 16, 24, 32, 48)
    best = candidates[-1]
    for n in candidates:
        colors = _palette_colors(n)
        if not colors:
            continue
        _idx, _dist = nearest_oklab(
            probe_lab, srgb_u8_to_oklab(np.asarray(colors, dtype=np.uint8))
        )
        restored = np.asarray(colors, dtype=np.int16)[_idx]
        mean = float(np.abs(probe_arr.astype(np.int16) - restored).mean())
        best = n
        # Prefer the smallest palette that still reconstructs the solids; AA
        # fringe keeps mean error a bit above zero even on perfect logos.
        if mean <= 10.0 or (flat_mass >= 0.92 and mean <= max(12.0, mean12 + 1.0)):
            break
    if unique is None and flat_mass < 0.75:
        return flat_mass, max(best, 24)
    if unique is not None and unique <= best:
        return flat_mass, max(2, unique)
    return flat_mass, max(2, best)


# ---------------------------------------------------------------------------
# Classification + settings
# ---------------------------------------------------------------------------


def _edge_for_kind(kind: ContentKind, m: ImageMetrics) -> EdgeTreatment:
    """Blended artwork keeps anti-alias coverage. Hard edges and photos do not."""
    if kind == ContentKind.PIXEL_ART:
        return EdgeTreatment.HARD
    if kind in {ContentKind.PHOTO, ContentKind.GRADIENT}:
        return EdgeTreatment.PHOTO
    if kind == ContentKind.BINARY_MARK and m.corner_sharpness >= 0.45:
        return EdgeTreatment.HARD
    if kind == ContentKind.LINE_ART and m.corner_sharpness >= 0.55:
        return EdgeTreatment.HARD
    # Large ink-heavy cel scenes: BlendTracer hard-cel collapses to ~one path
    # per palette colour (broken outlines, splotchy fills). VTracer on a
    # stroke-solidified snap keeps continuous ink and flat fills.
    # Transparent badges/patches must stay on the blend path — VTracer has no
    # alpha channel and would paint chroma-key / empty pixels as solid fills.
    if (
        kind == ContentKind.ILLUSTRATION
        and m.ink_outline_score >= 0.008
        and (m.width * m.height) >= 180_000
        and not (m.has_alpha and m.opaque_ratio < 0.92)
    ):
        return EdgeTreatment.PHOTO
    # Logos / smaller illustrations keep the blend iso-contour path.
    return EdgeTreatment.BLENDED


def _fold_background_into(
    palette: tuple[str, ...],
    metrics: ImageMetrics,
    *,
    tol: int = 10,
) -> tuple[str, ...]:
    """Put the scene-background ink first without adding a near-twin.

    The detected background is a bucket centre (#fcccd4); the flat palette
    already holds the true wall median (#ffcbd5). Inserting both splits one
    wall into two interleaved fills, so prefer the palette's own colour.
    """
    from vectorizer.domain.settings import normalize_hex
    from vectorizer.raster.color import hex_to_rgb, rgb_to_hex

    if metrics.background_rgb is None or metrics.background_confidence < 0.45:
        return palette
    bg = metrics.background_rgb
    for i, color in enumerate(palette):
        r, g, b = hex_to_rgb(color)
        if max(abs(r - bg[0]), abs(g - bg[1]), abs(b - bg[2])) <= tol:
            return (color, *palette[:i], *palette[i + 1 :])
    return (normalize_hex(rgb_to_hex(bg)), *palette)


def _ensure_dark_ink(
    palette: tuple[str, ...],
    image: Image.Image,
    *,
    max_colors: int = 24,
) -> tuple[str, ...]:
    """Guarantee a near-black ink slot for cel outlines.

    JPEG cel art often browns true black strokes. Sampling the *median* outline
    pixel yields muddy brown (#724241) that then eats orange couches. Use the
    darkest outline percentile instead, and never accept an ink lighter than
    luma 45. The palette is always cleaned of stroke impostors, even when a
    near-black ink is already present.
    """
    from vectorizer.raster.color import hex_to_rgb

    def _luma(hex_color: str) -> float:
        r, g, b = hex_to_rgb(hex_color)
        return 0.299 * r + 0.587 * g + 0.114 * b

    existing = [c for c in palette if _luma(c) <= 45]
    if existing:
        ink = min(existing, key=_luma)
    else:
        ink = _sample_dark_ink(image)
    # Drop muddy-brown stroke impostors: JPEG outline pixels otherwise snap to
    # them and break the black line work. High-chroma oranges (couch shadows
    # like #b35427, sat > 110), dark hues (purple shelf, teal floor shadow) and
    # neutral greys (metal hoops, tyres) are real fills and stay.
    cleaned: list[str] = []
    ink_luma = _luma(ink)
    for color in palette:
        if color == ink:
            continue
        r, g, b = hex_to_rgb(color)
        luma = 0.299 * r + 0.587 * g + 0.114 * b
        sat = max(r, g, b) - min(r, g, b)
        if luma <= 45 and sat <= 48:
            # Charcoal fields (heraldic halves, dark panels) are fills, not
            # stroke fringe: keep them when they own a large flat interior.
            if luma - ink_luma >= 22 and _flat_fill_share(image, (r, g, b)) >= 0.02:
                cleaned.append(color)
            continue
        brown = r >= g - 2 and g >= b - 2 and r - b >= 24
        if 40 < luma <= 130 and sat <= 85 and brown:
            continue
        cleaned.append(color)
    palette = tuple(cleaned) if cleaned else palette
    if len(palette) < max_colors:
        return palette + (ink,)
    if len(palette) <= 1:
        return (ink,)
    replace_at = max(range(1, len(palette)), key=lambda i: _luma(palette[i]))
    return tuple(ink if i == replace_at else c for i, c in enumerate(palette))


def _flats_cover_cutout(image: Image.Image, flats: tuple[str, ...]) -> bool:
    """True when nearly every locally flat opaque pixel sits on one of `flats`.

    Gradient app icons also have flat-looking 5×5 patches, but those drift off
    any small solid palette — they must keep the richer posterize budget.
    """
    from vectorizer.raster.color import hex_to_rgb, nearest_oklab, srgb_u8_to_oklab

    if not flats or len(flats) > 12:
        return False
    rgba = image.convert("RGBA")
    w, h = rgba.size
    if max(w, h) > 512:
        scale = 512 / float(max(w, h))
        rgba = rgba.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.BOX
        )
    arr = np.asarray(rgba, dtype=np.uint8)
    rgb_img = Image.fromarray(np.ascontiguousarray(arr[..., :3]), "RGB")
    hi = np.asarray(rgb_img.filter(ImageFilter.MaxFilter(5)), dtype=np.int16)
    lo = np.asarray(rgb_img.filter(ImageFilter.MinFilter(5)), dtype=np.int16)
    flat = ((hi - lo).max(axis=2) <= 16) & (arr[..., 3] >= 250)
    if int(flat.sum()) < 256:
        return False
    pal_lab = srgb_u8_to_oklab(np.asarray([hex_to_rgb(c) for c in flats], dtype=np.uint8))
    _index, dist = nearest_oklab(srgb_u8_to_oklab(arr[..., :3]), pal_lab)
    return float((dist[flat] <= 0.0012).mean()) >= 0.97


def _flat_fill_share(image: Image.Image, rgb: tuple[int, int, int], *, tol: int = 10) -> float:
    """Share of opaque probe pixels that are `rgb` inside a flat 5×5 patch."""
    rgba = image.convert("RGBA")
    w, h = rgba.size
    if max(w, h) > 256:
        scale = 256 / float(max(w, h))
        rgba = rgba.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.NEAREST
        )
    arr = np.asarray(rgba, dtype=np.int16)
    opaque = arr[..., 3] >= 128
    if not np.any(opaque):
        return 0.0
    rgb_img = rgba.convert("RGB")
    hi = np.asarray(rgb_img.filter(ImageFilter.MaxFilter(5)), dtype=np.int16)
    lo = np.asarray(rgb_img.filter(ImageFilter.MinFilter(5)), dtype=np.int16)
    flat = (hi - lo).max(axis=2) <= 12
    near = (np.abs(arr[..., :3] - np.asarray(rgb, dtype=np.int16)).max(axis=2) <= tol)
    return float((near & flat & opaque).sum()) / float(opaque.sum())


def _sample_dark_ink(image: Image.Image) -> str:
    """Darkest-quartile outline colour, forced to cel black when too light."""
    from vectorizer.domain.settings import normalize_hex
    from vectorizer.raster.color import rgb_to_hex

    probe = _analysis_probe(image.convert("RGB"), max_side=256)
    arr = np.asarray(probe, dtype=np.int16)
    gray = (0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]).astype(
        np.float32
    )
    padded = np.pad(gray, 1, mode="edge")
    neigh_max = np.maximum.reduce(
        [
            padded[:-2, 1:-1],
            padded[2:, 1:-1],
            padded[1:-1, :-2],
            padded[1:-1, 2:],
        ]
    )
    # Prefer true stroke pixels: dark + high local contrast.
    outline = (gray <= 70.0) & ((neigh_max - gray) >= 45.0)
    if np.count_nonzero(outline) < 16:
        # Fall back to globally darkest opaque pixels.
        thr = float(np.percentile(gray, 1.0))
        outline = gray <= thr
    fallback = normalize_hex("#1a0a00")
    if not np.any(outline):
        return fallback
    dark = arr[outline]
    # Darkest quartile of outline samples — not the brown JPEG fringe median.
    lumas = (0.299 * dark[:, 0] + 0.587 * dark[:, 1] + 0.114 * dark[:, 2]).astype(
        np.float32
    )
    keep = lumas <= float(np.percentile(lumas, 25.0))
    sample = dark[keep] if np.any(keep) else dark
    median = np.median(sample, axis=0)
    r, g, b = (int(median[0]), int(median[1]), int(median[2]))
    if 0.299 * r + 0.587 * g + 0.114 * b > 45:
        return fallback
    return normalize_hex(rgb_to_hex((r, g, b)))


def _classify(m: ImageMetrics) -> ContentKind:
    min_side = min(m.width, m.height)
    unique = m.unique_colors
    # Effective ink count: prefer the reconstruction palette when anti-aliasing
    # or JPEG fringe inflates the raw unique-color tally.
    effective = m.palette_estimate
    if unique is not None:
        effective = min(effective, unique) if unique <= 48 else effective

    if unique is not None and unique <= 2:
        return ContentKind.BINARY_MARK

    # Thin strokes before pixel-art: both can be small + limited palette.
    if (
        unique is not None
        and unique <= 16
        and m.noise_score < 0.4
        and m.edge_density > 0.22
        and (
            m.foreground_coverage < 0.14
            or (m.fill_ratio < 0.55 and m.edge_density > 0.28)
        )
    ):
        return ContentKind.LINE_ART

    if (
        unique is not None
        and unique <= 16
        and min_side <= 128
        and m.corner_sharpness > 0.45
        and m.noise_score < 0.35
        and m.foreground_coverage >= 0.14
    ):
        return ContentKind.PIXEL_ART

    # Cel / cartoon with ink outlines — check before flat-logo so large scenes
    # with pink walls do not get the aggressive logo speckle recipe.
    # Strong ink alone can certify cel art: rich JPEG scenes often report a
    # collapsed flat_mass against a 12-colour probe even when fills are flat.
    strong_ink = m.ink_outline_score >= 0.012
    # Near-black canvas + sparse opaque mark is a logo/icon, not a cel scene.
    logo_matte = (
        m.background_rgb is not None
        and max(m.background_rgb) <= 40
        and m.background_confidence >= 0.7
        and m.opaque_ratio >= 0.85
    )
    cel_like = (
        not logo_matte
        and m.ink_outline_score >= 0.008
        and m.corner_sharpness >= 0.40
        and m.fill_ratio >= 0.40
        and m.noise_score < 0.60
        and (m.flat_mass >= 0.40 or strong_ink)
    )

    # Flat logos: either a hard limited palette, or a small solid palette with
    # anti-aliased / JPEG fringe that looks like "many colors". Large multi-
    # colour scenes with ink outlines are illustrations, not logos.
    if (
        not cel_like
        and m.corner_sharpness >= 0.35
        and m.noise_score < 0.45
        and m.fill_ratio >= 0.35
        and (
            logo_matte
            or (unique is not None and unique <= 32 and m.pixel_count <= 250_000)
            or (m.flat_mass >= 0.90 and effective <= 8 and m.pixel_count <= 500_000)
            or (m.flat_mass >= 0.95 and effective <= 6)
        )
    ):
        return ContentKind.FLAT_LOGO

    # Transparent cutout badges/crests with a limited solid palette are logos,
    # not megapixel cel scenes — keep them on the blend/logo recipe so alpha
    # stays empty and thin ink rings are not VTracer-posterized.
    # palette_estimate often lands ~24 from AA fringe even when solids are ≤10.
    if (
        m.has_alpha
        and 0.55 <= m.opaque_ratio <= 0.92
        and effective <= 32
        and m.corner_sharpness >= 0.40
        and m.noise_score < 0.45
        and m.fill_ratio >= 0.40
    ):
        return ContentKind.FLAT_LOGO

    # Cel / cartoon / poster art: flat fills + dark ink outlines beat the
    # unique-color explosion from JPEG/AA fringe. Do not use mid flat_mass
    # alone — photographic probes often land around 0.6–0.7.
    # Continuous-tone photos can look "flat" after aggressive quantization;
    # require ink / limited unique colours before trusting mid flat_mass.
    continuous_tone = unique is None or unique > 256
    if (
        m.noise_score < 0.60
        and m.corner_sharpness >= 0.25
        and (
            cel_like
            or (
                strong_ink
                and m.fill_ratio >= 0.55
                and m.corner_sharpness >= 0.35
            )
            or (unique is not None and unique <= 96)
            or (m.flat_mass >= 0.82 and effective <= 48 and not continuous_tone)
            or (
                m.flat_mass >= 0.70
                and m.fill_ratio >= 0.45
                and m.corner_sharpness >= 0.35
                and effective <= 64
                and not continuous_tone
            )
        )
    ):
        return ContentKind.ILLUSTRATION

    # Continuous tone: separate smooth gradients from photographic noise.
    if m.noise_score < 0.28 and m.corner_sharpness < 0.3 and m.edge_density < 0.35:
        return ContentKind.GRADIENT
    return ContentKind.PHOTO


def _settings_for_kind(kind: ContentKind, m: ImageMetrics) -> TraceSettings:
    area_scale = _speckle_scale(m.pixel_count)
    bg = m.background_rgb or (255, 255, 255)
    remove_bg = _should_remove_background(kind, m)
    smooth = m.noise_score >= 0.48 and kind in {
        ContentKind.PHOTO,
        ContentKind.GRADIENT,
        ContentKind.ILLUSTRATION,
    }

    if kind == ContentKind.BINARY_MARK:
        mode = PathFitMode.POLYGON if min(m.width, m.height) <= 256 else PathFitMode.SPLINE
        # Nested holes / rings: both ink and paper occupy meaningful area.
        # Also honor true alpha silhouettes that are not full-bleed.
        hierarchical = (
            HierarchyMode.CUTOUT
            if (
                (0.08 <= m.minority_ratio <= 0.45 and m.fill_ratio > 0.2)
                or (m.has_alpha and 0.12 <= m.opaque_ratio <= 0.88 and m.fill_ratio > 0.25)
            )
            else HierarchyMode.STACKED
        )
        return TraceSettings(
            workflow=WorkflowMode.AUTOMATIC,
            colormode=ColorMode.BINARY,
            hierarchical=hierarchical,
            mode=mode,
            filter_speckle=max(0, int(2 * area_scale) if min(m.width, m.height) < 128 else int(4 * area_scale)),
            color_precision=6,
            layer_difference=16,
            corner_threshold=50 if m.corner_sharpness > 0.5 else 60,
            length_threshold=3.8,
            max_iterations=10,
            splice_threshold=40,
            path_precision=3,
            preserve_transparency=m.has_alpha,
            remove_background=remove_bg,
            background_r=bg[0],
            background_g=bg[1],
            background_b=bg[2],
            background_tolerance=_bg_tolerance(m, binary=True),
            target_colors=0,
            smooth_noise=False,
        ).validated()

    if kind == ContentKind.PIXEL_ART:
        return TraceSettings(
            workflow=WorkflowMode.AUTOMATIC,
            colormode=ColorMode.COLOR,
            hierarchical=HierarchyMode.STACKED,
            mode=PathFitMode.PIXEL,
            filter_speckle=0 if m.noise_score < 0.25 else 1,
            color_precision=8,
            layer_difference=8,
            corner_threshold=30,
            length_threshold=3.5,
            max_iterations=8,
            splice_threshold=30,
            path_precision=2,
            preserve_transparency=m.has_alpha,
            remove_background=remove_bg and not m.has_alpha,
            background_r=bg[0],
            background_g=bg[1],
            background_b=bg[2],
            background_tolerance=_bg_tolerance(m),
            target_colors=0 if (m.unique_colors or 0) <= 16 else min(32, m.palette_estimate),
            smooth_noise=False,
        ).validated()

    if kind == ContentKind.LINE_ART:
        return TraceSettings(
            workflow=WorkflowMode.AUTOMATIC,
            colormode=ColorMode.BINARY if (m.unique_colors or 99) <= 4 else ColorMode.COLOR,
            hierarchical=HierarchyMode.STACKED,
            mode=PathFitMode.SPLINE,
            filter_speckle=max(0, int(1 * area_scale)),
            color_precision=7,
            layer_difference=10,
            corner_threshold=45,
            length_threshold=3.6,
            max_iterations=12,
            splice_threshold=35,
            path_precision=4,
            preserve_transparency=m.has_alpha,
            remove_background=remove_bg,
            background_r=bg[0],
            background_g=bg[1],
            background_b=bg[2],
            background_tolerance=_bg_tolerance(m),
            target_colors=0,
            smooth_noise=False,
        ).validated()

    if kind == ContentKind.FLAT_LOGO:
        hierarchical = (
            HierarchyMode.CUTOUT
            if m.border_match_ratio > 0.55 and 0.15 <= m.opaque_ratio <= 0.9
            else HierarchyMode.STACKED
        )
        palette = m.palette_estimate
        unique = m.unique_colors or palette
        # Soft anti-aliased logos (many near-bg fringe colors): knocking out the
        # background tends to leave a halo of junk paths on the VTracer path.
        # The blend tracer handles paper via empty labels, so allow knock-out
        # when the effective solid palette is still small.
        logo_remove_bg = remove_bg and (unique <= 8 or (m.flat_mass >= 0.9 and palette <= 8))
        # Alpha cutout badges: keep corner low so letterforms and heraldic
        # points stay sharp; target_colors must stay 0 so hard_cel engages.
        alpha_cutout = bool(m.has_alpha and m.opaque_ratio < 0.95)
        target = 0
        if (not alpha_cutout) and (palette > 24 or m.noise_score > 0.3):
            target = min(32, max(8, palette))
        logo_corner = (
            32
            if alpha_cutout
            else (40 if m.corner_sharpness > 0.5 else 55)
        )
        logo_speckle = (
            0
            if alpha_cutout or (m.ink_outline_score is not None and m.ink_outline_score >= 0.12)
            else max(0, int(2 * area_scale))
        )
        return TraceSettings(
            workflow=WorkflowMode.AUTOMATIC,
            colormode=ColorMode.COLOR,
            hierarchical=hierarchical,
            mode=PathFitMode.SPLINE,
            # Speckle filter eats thin AA fringes and small accents; keep mild.
            filter_speckle=logo_speckle,
            color_precision=7 if palette <= 16 else 6,
            layer_difference=10 if palette <= 16 else 14,
            corner_threshold=logo_corner,
            length_threshold=3.7,
            max_iterations=12,
            splice_threshold=40,
            path_precision=4,
            preserve_transparency=m.has_alpha and m.opaque_ratio < 0.98,
            remove_background=logo_remove_bg,
            background_r=bg[0],
            background_g=bg[1],
            background_b=bg[2],
            background_tolerance=_bg_tolerance(m),
            target_colors=target,
            smooth_noise=False,
        ).validated()

    if kind == ContentKind.ILLUSTRATION:
        # Cel-shaded scenes often match wall/sky to the corner colour — never
        # auto-knock those out; the user can still enable removal manually.
        illustration_remove = (
            remove_bg
            and m.background_confidence >= 0.88
            and m.border_match_ratio >= 0.7
            and m.foreground_coverage >= 0.5
        )
        # Keep thin ink outlines; the constrained palette already limits colours
        # so an extra target_colors pass would only blur and merge fills.
        ink_heavy = m.ink_outline_score >= 0.008
        # Prefer smooth, faithful fills over ultra-tight "keen" geometry that
        # turned cel couches muddy and edges crunchy at megapixel sizes.
        # Large ink-heavy cels route to VTracer (PHOTO edge): favour slightly
        # smoother corners so solidified ink ribbons do not look stair-stepped.
        large_cel = ink_heavy and (m.width * m.height) >= 180_000
        # Transparent badges/crests stay on BlendTracer soft iso
        # (preserve_transparency disables hard_cel). Corner stays low so
        # letterforms keep sharp apexes; crack-edge is what caused ghost rings.
        cutout_badge = m.has_alpha and m.opaque_ratio < 0.92
        if cutout_badge:
            corner = 32
        elif large_cel:
            corner = 48
        elif ink_heavy:
            corner = 38
        else:
            corner = 50
        return TraceSettings(
            workflow=WorkflowMode.AUTOMATIC,
            colormode=ColorMode.COLOR,
            hierarchical=HierarchyMode.STACKED,
            mode=PathFitMode.SPLINE,
            # Speckle must stay tiny on cel art — filter_speckle≥4 eats 1–2 px
            # ink outlines on megapixel scenes and the couch loses its contour.
            filter_speckle=0 if ink_heavy else max(0, int(1 * area_scale)),
            color_precision=8 if large_cel else 7,
            layer_difference=4 if large_cel else (8 if ink_heavy else 10),
            corner_threshold=corner,
            length_threshold=3.5 if ink_heavy else 3.6,
            max_iterations=14 if ink_heavy else 12,
            splice_threshold=30 if large_cel else (28 if ink_heavy else 35),
            path_precision=4 if ink_heavy else 3,
            preserve_transparency=m.has_alpha,
            remove_background=illustration_remove,
            background_r=bg[0],
            background_g=bg[1],
            background_b=bg[2],
            background_tolerance=_bg_tolerance(m),
            target_colors=0,
            smooth_noise=False,
        ).validated()

    # PHOTO / GRADIENT — posterize then spline for editable regions.
    if kind == ContentKind.GRADIENT:
        target = min(36, max(12, m.palette_estimate))
        layer_diff = 12
        filter_speckle = max(4, int(6 * area_scale))
    else:
        target = min(48, max(16, m.palette_estimate))
        layer_diff = 16
        filter_speckle = max(6, int(8 * area_scale))

    return TraceSettings(
        workflow=WorkflowMode.AUTOMATIC,
        colormode=ColorMode.COLOR,
        hierarchical=HierarchyMode.STACKED,
        mode=PathFitMode.SPLINE,
        filter_speckle=min(64, filter_speckle),
        color_precision=5,
        layer_difference=layer_diff,
        corner_threshold=70,
        length_threshold=4.2,
        max_iterations=8,
        splice_threshold=50,
        path_precision=2,
        preserve_transparency=m.has_alpha,
        remove_background=False,
        background_r=bg[0],
        background_g=bg[1],
        background_b=bg[2],
        background_tolerance=32,
        target_colors=target,
        smooth_noise=smooth or kind == ContentKind.PHOTO,
    ).validated()


def _speckle_scale(pixel_count: int) -> float:
    """Scale filter_speckle with resolution; VTracer's unit is roughly pixel area."""
    if pixel_count <= 40_000:
        return 1.0
    if pixel_count <= 250_000:
        return 1.35
    if pixel_count <= 1_000_000:
        return 1.8
    return 2.4


def _should_remove_background(kind: ContentKind, m: ImageMetrics) -> bool:
    if m.has_alpha and m.opaque_ratio < 0.98:
        # Already has real transparency; knocking out again is usually harmful.
        return False
    if kind in {ContentKind.PHOTO, ContentKind.GRADIENT}:
        return False
    if m.background_rgb is None:
        return False
    if m.background_confidence < 0.78:
        return False
    if m.border_match_ratio < 0.55:
        return False
    # Scene colours (walls, skies) dominate the interior while also matching the
    # corners. Knocking those out swallows half the illustration.
    if m.foreground_coverage < 0.42:
        return False
    # Black / near-black mattes are part of the logo (Brave, ChatGPT, app icons).
    # Knocking them out leaves the mark floating on white and destroys the mark.
    br, bg, bb = m.background_rgb
    if max(br, bg, bb) <= 40:
        return False
    # Background must cover a meaningful outer frame but not the whole image.
    if m.opaque_ratio > 0.995 and m.border_match_ratio > 0.97 and kind == ContentKind.FLAT_LOGO:
        # Full-bleed flat image with uniform border — still OK to knock out.
        return True
    return kind in {
        ContentKind.BINARY_MARK,
        ContentKind.FLAT_LOGO,
        ContentKind.LINE_ART,
        ContentKind.PIXEL_ART,
        ContentKind.ILLUSTRATION,
    }


def _bg_tolerance(m: ImageMetrics, *, binary: bool = False) -> int:
    if binary:
        return 28 if m.noise_score < 0.3 else 40
    base = 24
    if m.noise_score > 0.4:
        base += 12
    if m.corner_sharpness < 0.35:
        base += 8  # soft AA fringe around logos
    return max(12, min(64, base))


def _build_notes(
    kind: ContentKind,
    m: ImageMetrics,
    quality: AutomaticQuality,
    suggested: TraceSettings,
) -> list[str]:
    notes: list[str] = []
    labels = {
        ContentKind.BINARY_MARK: "Detected a binary mark / stencil.",
        ContentKind.FLAT_LOGO: "Detected a flat-color logo or icon.",
        ContentKind.PIXEL_ART: "Detected small pixel-art / limited palette art.",
        ContentKind.LINE_ART: "Detected line art; preserving thin strokes.",
        ContentKind.ILLUSTRATION: "Detected an illustration with a moderate palette.",
        ContentKind.PHOTO: (
            "This image looks photographic. Vectorization will produce stylized "
            "color regions, not a lossless stand-in for the photograph."
        ),
        ContentKind.GRADIENT: (
            "Smooth gradients detected. Colors will be posterized into editable regions."
        ),
    }
    if kind == ContentKind.ILLUSTRATION and m.ink_outline_score >= 0.008:
        notes.append(
            "Detected cel / cartoon art with ink outlines; preserving flat fills "
            "and dark line work."
        )
    else:
        notes.append(labels[kind])

    if m.unique_colors is not None:
        notes.append(f"About {m.unique_colors} unique colors sampled.")
    else:
        notes.append("Continuous color range; palette will be reduced before tracing.")

    if suggested.remove_background and suggested.background_rgb_tuple():
        r, g, b = suggested.background_rgb_tuple()
        notes.append(
            f"Auto background removal armed (#{r:02x}{g:02x}{b:02x}, "
            f"confidence {m.background_confidence:.0%})."
        )
    elif (
        not suggested.remove_background
        and m.background_rgb is not None
        and m.background_confidence >= 0.45
        and kind in {ContentKind.ILLUSTRATION, ContentKind.FLAT_LOGO}
    ):
        r, g, b = m.background_rgb
        notes.append(
            f"Scene background kept as fill (#{r:02x}{g:02x}{b:02x})."
        )
    elif m.has_alpha:
        notes.append("Source transparency will be preserved.")

    if suggested.hierarchical == HierarchyMode.CUTOUT:
        notes.append("Using cutout hierarchy so holes stay clean.")

    if suggested.palette:
        notes.append(
            f"Output colors constrained to a {len(suggested.palette)}-color palette."
        )
    if (
        kind == ContentKind.ILLUSTRATION
        and m.ink_outline_score >= 0.008
        and suggested.edge_treatment == EdgeTreatment.PHOTO
    ):
        notes.append(
            "Cel outlines solidified before tracing so ink stays continuous."
        )
    if suggested.edge_treatment == EdgeTreatment.BLENDED:
        notes.append("Edges follow anti-aliased blending inside each boundary pixel.")
    elif suggested.edge_treatment == EdgeTreatment.HARD:
        notes.append("Hard edges: shapes snap to flat colors before fitting.")
    elif suggested.edge_treatment == EdgeTreatment.PHOTO:
        if kind == ContentKind.ILLUSTRATION and m.ink_outline_score >= 0.008:
            notes.append(
                "Cel scene: palette-snapped regions with solidified ink outlines."
            )
        else:
            notes.append("Photograph: posterized to the palette, then traced as regions.")

    if suggested.target_colors:
        notes.append(f"Pre-quantizing to {suggested.target_colors} colors for cleaner regions.")

    if suggested.smooth_noise:
        notes.append("Light noise smoothing enabled before tracing.")

    quality = AutomaticQuality(quality)
    if quality == AutomaticQuality.FAST:
        notes.append("Automatic quality: Fast — fewer paths, quicker result.")
    elif quality == AutomaticQuality.HIGH:
        notes.append("Automatic quality: High detail — finer colors and paths.")
    else:
        notes.append("Automatic quality: Balanced.")

    return notes
