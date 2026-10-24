"""Content-aware analysis that drives Automatic mode.

This is not a proprietary tracer. It classifies the raster, estimates geometry-
friendly parameters, and suggests preprocess steps that make VTracer produce
cleaner, more editable vectors — the same decisions a skilled operator would
make by eye.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from PIL import Image, ImageChops, ImageFilter, ImageStat

from vectorizer.domain.settings import (
    AutomaticQuality,
    ColorMode,
    HierarchyMode,
    PathFitMode,
    TraceSettings,
    WorkflowMode,
)


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
        elif kind == ContentKind.ILLUSTRATION and tuned.target_colors == 0:
            tuned = replace(tuned, target_colors=min(32, max(8, tuned.color_precision * 4)))
        return tuned.validated()

    # High detail — preserve structure; spend more fitting budget.
    tuned = replace(
        base,
        automatic_quality=quality,
        workflow=WorkflowMode.AUTOMATIC,
        filter_speckle=max(0, base.filter_speckle - 2),
        color_precision=min(8, base.color_precision + 1),
        layer_difference=max(0, base.layer_difference - 4),
        corner_threshold=max(0, base.corner_threshold - 10),
        length_threshold=max(3.5, base.length_threshold - 0.3),
        max_iterations=min(64, base.max_iterations + 6),
        path_precision=min(12, base.path_precision + 1),
        splice_threshold=max(0, base.splice_threshold - 5),
    )
    if kind in {ContentKind.PHOTO, ContentKind.GRADIENT} and tuned.target_colors:
        # High detail: allow a richer palette before tracing.
        tuned = replace(tuned, target_colors=min(64, tuned.target_colors + 12))
    return tuned.validated()


def analyze_image(
    image: Image.Image,
    *,
    quality: AutomaticQuality = AutomaticQuality.BALANCED,
) -> ImageAnalysis:
    metrics = _compute_metrics(image)
    kind = _classify(metrics)
    photo_like = kind in {ContentKind.PHOTO, ContentKind.GRADIENT}
    base = _settings_for_kind(kind, metrics)
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
    palette_estimate = _estimate_palette_size(rgb, unique, exact)

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
    palette_pixels = (
        quantized.get_flattened_data()
        if hasattr(quantized, "get_flattened_data")
        else quantized.getdata()
    )
    approx = len(set(palette_pixels))
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


def _detect_background(
    rgba: Image.Image,
) -> tuple[tuple[int, int, int] | None, float, float]:
    """Consensus background from corner patches + border agreement."""
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
    bg = (rs[mid], gs[mid], bs[mid])

    # Corner consensus: fraction of samples near the median.
    tol = 18
    near = sum(
        1
        for r, g, b in samples
        if abs(r - bg[0]) <= tol and abs(g - bg[1]) <= tol and abs(b - bg[2]) <= tol
    )
    corner_agreement = near / float(len(samples))

    border_match = _border_match_ratio(rgba, bg, tol=tol)
    confidence = 0.55 * corner_agreement + 0.45 * border_match
    if corner_agreement < 0.72:
        return bg, confidence * 0.5, border_match
    return bg, confidence, border_match


def _border_match_ratio(
    rgba: Image.Image,
    color: tuple[int, int, int],
    *,
    tol: int,
) -> float:
    w, h = rgba.size
    tr, tg, tb = color
    matched = 0
    total = 0
    # Sample the outer ring without walking every pixel on huge images.
    step = max(1, max(w, h) // 256)

    def _consider(x: int, y: int) -> None:
        nonlocal matched, total
        r, g, b, a = rgba.getpixel((x, y))
        if a < 128:
            return
        total += 1
        if abs(r - tr) <= tol and abs(g - tg) <= tol and abs(b - tb) <= tol:
            matched += 1

    for x in range(0, w, step):
        _consider(x, 0)
        _consider(x, h - 1)
    for y in range(step, h - step, step):
        _consider(0, y)
        _consider(w - 1, y)

    if total == 0:
        return 0.0
    return matched / float(total)


def _estimate_palette_size(
    rgb: Image.Image,
    unique: int | None,
    exact: bool,
) -> int:
    if exact and unique is not None:
        return max(2, unique)
    # Probe reconstruction error across a few palette sizes.
    probe = rgb
    w, h = probe.size
    if max(w, h) > 256:
        scale = 256 / float(max(w, h))
        probe = probe.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))),
            Image.Resampling.BILINEAR,
        )
    candidates = (4, 8, 12, 16, 24, 32, 48)
    best = 32
    for n in candidates:
        q = probe.quantize(colors=n, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        restored = q.convert("RGB")
        # Mean channel absolute error — cheap stand-in for perceptual fit.
        err = ImageChops.difference(probe, restored)
        mean = sum(ImageStat.Stat(err).mean) / 3.0
        best = n
        if mean < 10.0:
            break
    if unique is None:
        return max(best, 24)
    return max(2, min(best, unique))


# ---------------------------------------------------------------------------
# Classification + settings
# ---------------------------------------------------------------------------


def _classify(m: ImageMetrics) -> ContentKind:
    min_side = min(m.width, m.height)
    unique = m.unique_colors

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

    if (
        unique is not None
        and unique <= 32
        and m.corner_sharpness >= 0.35
        and m.noise_score < 0.45
        and m.fill_ratio >= 0.35
    ):
        return ContentKind.FLAT_LOGO

    if unique is not None and unique <= 96 and m.noise_score < 0.55 and m.corner_sharpness >= 0.25:
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
        target = 0
        if palette > 24 or m.noise_score > 0.3:
            target = min(32, max(8, palette))
        # Soft anti-aliased logos (many near-bg fringe colors): knocking out the
        # background tends to leave a halo of junk paths. Prefer tracing on the
        # opaque raster unless the palette is already hard-edged and tiny.
        logo_remove_bg = remove_bg and unique <= 8
        return TraceSettings(
            workflow=WorkflowMode.AUTOMATIC,
            colormode=ColorMode.COLOR,
            hierarchical=hierarchical,
            mode=PathFitMode.SPLINE,
            filter_speckle=max(1, int(3 * area_scale)),
            color_precision=7 if palette <= 16 else 6,
            layer_difference=10 if palette <= 16 else 14,
            corner_threshold=40 if m.corner_sharpness > 0.5 else 55,
            length_threshold=3.7,
            max_iterations=12,
            splice_threshold=40,
            path_precision=4,
            preserve_transparency=True,
            remove_background=logo_remove_bg,
            background_r=bg[0],
            background_g=bg[1],
            background_b=bg[2],
            background_tolerance=_bg_tolerance(m),
            target_colors=target,
            smooth_noise=False,
        ).validated()

    if kind == ContentKind.ILLUSTRATION:
        target = min(48, max(12, m.palette_estimate))
        return TraceSettings(
            workflow=WorkflowMode.AUTOMATIC,
            colormode=ColorMode.COLOR,
            hierarchical=HierarchyMode.STACKED,
            mode=PathFitMode.SPLINE,
            filter_speckle=max(2, int(5 * area_scale)),
            color_precision=6,
            layer_difference=14,
            corner_threshold=55,
            length_threshold=4.0,
            max_iterations=10,
            splice_threshold=45,
            path_precision=3,
            preserve_transparency=m.has_alpha,
            remove_background=remove_bg and m.background_confidence >= 0.82,
            background_r=bg[0],
            background_g=bg[1],
            background_b=bg[2],
            background_tolerance=_bg_tolerance(m),
            target_colors=target if m.noise_score > 0.25 or (m.unique_colors or 999) > 48 else 0,
            smooth_noise=smooth,
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
    elif m.has_alpha:
        notes.append("Source transparency will be preserved.")

    if suggested.hierarchical == HierarchyMode.CUTOUT:
        notes.append("Using cutout hierarchy so holes stay clean.")

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
