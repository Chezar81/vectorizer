"""Choose blend, gradient, or VTracer from the edge treatment and palette."""

from __future__ import annotations

from dataclasses import replace

from PIL import Image

from vectorizer.domain.settings import EdgeTreatment, TraceSettings
from vectorizer.jobs.progress import (
    STAGE_ANALYZE,
    STAGE_COLORS,
    STAGE_CONTOURS,
    STAGE_CURVES,
    STAGE_FINALIZE,
    STAGE_PREPARE,
    STAGE_SVG,
    ProgressCallback,
)
from vectorizer.raster.palette import snap_image_to_palette, suggest_palettes
from vectorizer.raster.preprocess import preprocess_image
from vectorizer.svg.edit import snap_fills_to_palette
from vectorizer.vectorize.backend import TraceResult
from vectorizer.vectorize.blend_trace import BlendTracer
from vectorizer.vectorize.cel_boundary_trace import CelBoundaryTracer
from vectorizer.vectorize.gradient_trace import GradientTracer
from vectorizer.vectorize.vtracer_backend import VTracerBackend


_PHOTO_PIXELS_PER_PATH = 5


def trace_prepared(
    image: Image.Image,
    settings: TraceSettings,
    *,
    soft_source: Image.Image | None = None,
    content_kind: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> TraceResult:
    """Trace `image` with the engine selected by `settings`.

    Blended artwork uses soft-coverage iso-contours. When `soft_source` is set
    (F6 retrace), hard labels come from `image` while coverage is sampled from
    the anti-aliased original. Gradients use planar OKLab patches. Photographs
    posterize through VTracer.

    `content_kind` is an optional analyzer hint from a prior GUI pass so the
    worker can skip a second full analysis (especially gradient vs photo).
    """
    report = on_progress or (lambda _stage, _fraction: None)
    report(STAGE_PREPARE, 0.02)
    validated = settings.validated()
    analysis = None
    auto = None
    if _needs_automatic(validated):
        report(STAGE_ANALYZE, 0.08)
        analysis = _automatic_analysis(image, validated)
        auto = analysis.suggested
    known_kind = _resolve_content_kind(content_kind, analysis)
    treatment = resolve_edge_treatment(image, validated, suggestion=auto)
    report(STAGE_COLORS, 0.18)
    posterize_only = _posterize_only(validated, treatment)
    palette = None if posterize_only else resolve_palette(
        image, validated, treatment, suggestion=auto
    )

    if treatment == EdgeTreatment.PHOTO:
        # Smooth gradients get mesh-like SVG fills; busy photos stay posterized.
        if _is_gradient_content(
            image, validated, known_kind=known_kind, analysis=analysis
        ):
            try:
                report(STAGE_CONTOURS, 0.28)
                return _with_progress_tail(
                    GradientTracer().trace(
                        image, validated, on_progress=_scaled_progress(report, 0.28, 0.92)
                    ),
                    report,
                )
            except Exception as exc:
                report(STAGE_CONTOURS, 0.35)
                fallback = VTracerBackend().trace(
                    _vtracer_input(image, validated, palette),
                    validated,
                    on_progress=_scaled_progress(report, 0.35, 0.92),
                )
                warning = f"Gradient tracing failed ({exc}); used the standard tracer."
                return _with_progress_tail(
                    replace(fallback, warnings=fallback.warnings + (warning,)),
                    report,
                )
        working = _vtracer_input(image, validated, palette)
        # Busy megapixel cels: shared-boundary tracer keeps abutting flats
        # seam-free. Fall back to VTracer if it fails or yields nothing.
        large_cel = bool(
            palette
            and _palette_has_cel_ink(palette)
            and image.width * image.height >= 180_000
            and validated.target_colors == 0
        )
        if large_cel:
            try:
                report(STAGE_CONTOURS, 0.28)
                boundary = CelBoundaryTracer().trace(
                    working,
                    validated,
                    palette,
                    soft_source=soft_source or image,
                    on_progress=_scaled_progress(report, 0.28, 0.92),
                )
                if boundary.document.path_count > 0:
                    return _with_progress_tail(
                        replace(boundary, settings=validated), report
                    )
            except Exception as exc:
                report(STAGE_CONTOURS, 0.35)
                fallback = VTracerBackend().trace(
                    working,
                    validated,
                    on_progress=_scaled_progress(report, 0.35, 0.92),
                )
                warning = (
                    f"Cel boundary tracing failed ({exc}); used the standard tracer."
                )
                if palette or validated.palette_remaps:
                    snapped = snap_fills_to_palette(
                        fallback.document,
                        palette or (),
                        tolerance=validated.palette_tolerance,
                        remaps=validated.palette_remaps,
                    )
                    fallback = replace(fallback, document=snapped)
                return _with_progress_tail(
                    replace(
                        fallback,
                        warnings=fallback.warnings + (warning,),
                        settings=validated,
                    ),
                    report,
                )
        tuned = validated
        if posterize_only:
            # Input is already reduced to target_colors inks; coarser VTracer
            # precision would merge neighbouring posterize steps again.
            tuned = replace(validated, color_precision=8)
        if palette:
            # Photo quality is an output shape budget already stored on
            # target_colors / filter_speckle / layer_difference. The caps
            # below only protect cel ink; they are not the artwork blend-width
            # adjustment (that stays on the blend tracer).
            # Small cel badges keep layers tight so thin outlines survive.
            # Megapixel living-room cels need a wider layer budget or shade
            # islands shatter into jagged micro-paths along every couch fold.
            layer_cap = 8 if large_cel else (4 if _palette_has_cel_ink(palette) else 6)
            # Small cel badges keep a 1 px speckle floor so hairlines survive.
            # Large scenes do not: the analyzer's floor is what stops JPEG
            # freckles from becoming one path each.
            speckle = validated.filter_speckle
            if _palette_has_cel_ink(palette) and image.width * image.height < 180_000:
                speckle = min(speckle, 1)
            tuned = replace(
                validated,
                color_precision=8,
                layer_difference=min(validated.layer_difference, layer_cap),
                filter_speckle=speckle,
            )
        report(STAGE_CONTOURS, 0.30)
        result = VTracerBackend().trace(
            working, tuned, on_progress=_scaled_progress(report, 0.30, 0.90)
        )
        if (
            posterize_only
            and tuned.filter_speckle == 0
            and result.document.path_count * _PHOTO_PIXELS_PER_PATH
            > image.width * image.height
        ):
            # Pattern boards at speckle 0 keep every anti-aliased pixel as its
            # own shape (150k paths, 15 MB). A 1 px floor costs fine hairlines
            # but keeps the document editable.
            result = VTracerBackend().trace(
                working,
                replace(tuned, filter_speckle=1),
                on_progress=_scaled_progress(report, 0.90, 0.92),
            )
        if palette or validated.palette_remaps:
            report(STAGE_SVG, 0.93)
            snapped = snap_fills_to_palette(
                result.document,
                palette or (),
                tolerance=validated.palette_tolerance,
                remaps=validated.palette_remaps,
            )
            return _with_progress_tail(
                replace(result, document=snapped, settings=validated), report
            )
        return _with_progress_tail(replace(result, settings=validated), report)

    if treatment == EdgeTreatment.BLENDED and palette:
        try:
            report(STAGE_CONTOURS, 0.28)
            return _with_progress_tail(
                BlendTracer().trace(
                    image,
                    validated,
                    palette,
                    soft_source=soft_source or image,
                    on_progress=_scaled_progress(report, 0.28, 0.92),
                ),
                report,
            )
        except Exception as exc:
            report(STAGE_CONTOURS, 0.35)
            fallback = VTracerBackend().trace(
                _vtracer_input(image, validated, palette),
                validated,
                on_progress=_scaled_progress(report, 0.35, 0.92),
            )
            warning = f"Blend tracing failed ({exc}); used the standard tracer."
            return _with_progress_tail(
                replace(fallback, warnings=fallback.warnings + (warning,)),
                report,
            )

    working = _vtracer_input(
        image, validated, palette if treatment != EdgeTreatment.HARD or palette else None
    )
    tuned = validated
    if palette:
        tuned = replace(
            validated, color_precision=8, layer_difference=min(validated.layer_difference, 6)
        )
    report(STAGE_CONTOURS, 0.30)
    result = VTracerBackend().trace(
        working, tuned, on_progress=_scaled_progress(report, 0.30, 0.90)
    )
    if palette or validated.palette_remaps:
        report(STAGE_SVG, 0.93)
        snapped = snap_fills_to_palette(
            result.document,
            palette or (),
            tolerance=validated.palette_tolerance,
            remaps=validated.palette_remaps,
        )
        return _with_progress_tail(
            replace(result, document=snapped, settings=validated), report
        )
    return _with_progress_tail(replace(result, settings=validated), report)


def resolve_edge_treatment(
    image: Image.Image,
    settings: TraceSettings,
    *,
    suggestion: TraceSettings | None = None,
) -> EdgeTreatment:
    if settings.edge_treatment != EdgeTreatment.AUTO:
        return settings.edge_treatment
    if settings.colormode.value == "binary" or settings.mode.value == "none":
        return EdgeTreatment.HARD
    if settings.workflow.value != "automatic":
        return EdgeTreatment.HARD
    if suggestion is not None:
        return suggestion.edge_treatment
    return _automatic_suggestion(image, settings).edge_treatment


def resolve_palette(
    image: Image.Image,
    settings: TraceSettings,
    treatment: EdgeTreatment,
    *,
    suggestion: TraceSettings | None = None,
) -> tuple[str, ...] | None:
    if settings.palette:
        return settings.palette
    if treatment == EdgeTreatment.HARD:
        return None
    # Automatic mode: reuse the analyzer palette (flat-mass capped, background
    # aware). A bare suggest_palettes() call over-counts AA fringe colors.
    if _needs_automatic(settings):
        suggested = suggestion or _automatic_suggestion(image, settings)
        if suggested.palette:
            return suggested.palette
    ignore = None
    if settings.remove_background:
        ignore = settings.background_rgb_tuple()
    suggestions = suggest_palettes(image, ignore_rgb=ignore)
    colors = suggestions.palettes.get(suggestions.best) or ()
    return colors or None


def _posterize_only(settings: TraceSettings, treatment: EdgeTreatment) -> bool:
    """Photo posterize keeps the quantizer's own inks.

    The analyzer palette is a ≤16-colour probe of a 320 px thumbnail; snapping
    a 28–60 colour posterize onto it merged translucent overlaps (purple,
    teal) into neighbours and banded soft photos.
    """
    return (
        settings.workflow.value == "automatic"
        and treatment == EdgeTreatment.PHOTO
        and int(settings.target_colors) > 0
        and not settings.palette_remaps
    )


def _needs_automatic(settings: TraceSettings) -> bool:
    return (
        settings.workflow.value == "automatic"
        and settings.edge_treatment.value == "auto"
        and settings.colormode.value != "binary"
        and settings.mode.value != "none"
    )


def _automatic_analysis(image: Image.Image, settings: TraceSettings):
    from vectorizer.raster.analyzer import analyze_image

    return analyze_image(image, quality=settings.automatic_quality)


def _automatic_suggestion(image: Image.Image, settings: TraceSettings) -> TraceSettings:
    return _automatic_analysis(image, settings).suggested


def _resolve_content_kind(content_kind: str | None, analysis) -> object | None:
    from vectorizer.raster.analyzer import ContentKind

    if analysis is not None:
        return analysis.content_kind
    if not content_kind:
        return None
    try:
        return ContentKind(str(content_kind))
    except ValueError:
        return None


def _is_gradient_content(
    image: Image.Image,
    settings: TraceSettings,
    *,
    known_kind=None,
    analysis=None,
) -> bool:
    """Use GradientTracer only for soft continuous-tone fields.

    Stepped ramps, multi-panel flats, and organic poster landscapes are often
    labelled GRADIENT by slow_ramp, but mesh fills then blow up RMSE versus a
    hard/posterized VTracer path (see algo_improve corpus).
    """
    from vectorizer.raster.analyzer import ContentKind

    kind = known_kind
    metrics = None
    if analysis is not None:
        kind = analysis.content_kind
        metrics = analysis.metrics
    if kind is None:
        # Last resort: one analysis pass (manual PHOTO mode without a GUI hint).
        analysis = _automatic_analysis(image, settings)
        kind = analysis.content_kind
        metrics = analysis.metrics
    if kind != ContentKind.GRADIENT:
        return False
    # Suggested settings already pin edge_treatment (not AUTO), so the
    # Automatic re-analysis above is skipped — fetch metrics once so the
    # soft-field gate still runs.
    if metrics is None:
        metrics = _automatic_analysis(image, settings).metrics
    # Soft still-life / wash: low flat_mass. Discrete or stepped colour
    # regions (flat_mass mid/high, sharper corners) posterize instead.
    if metrics.flat_mass >= 0.45:
        return False
    if metrics.corner_sharpness >= 0.55:
        return False
    return True


def _vtracer_input(
    image: Image.Image,
    settings: TraceSettings,
    palette: tuple[str, ...] | None,
) -> Image.Image:
    if settings.apply_preprocess:
        working = preprocess_image(image, settings)
    else:
        working = image.convert("RGBA")
    if not palette and not settings.palette_remaps:
        return working
    # Ink-heavy cel scenes: solidify outlines before the hard snap so JPEG
    # browns do not dissolve into orange fills and VTracer keeps continuous ink.
    # Full prepare_cel_ink is for small badges (speckle floor ≤1). Megapixel
    # living-room cels only get a light fill cleanup — rebaking ink opened
    # outline gaps and raised reconstruction error.
    cel_ink = bool(palette and _palette_has_cel_ink(palette) and settings.target_colors == 0)
    if cel_ink and settings.filter_speckle <= 1:
        from vectorizer.raster.preprocess import prepare_cel_ink

        ink = _darkest_palette_rgb(palette)
        working = prepare_cel_ink(working, palette, ink_rgb=ink)
        return snap_image_to_palette(
            working,
            palette or (),
            tolerance=settings.palette_tolerance,
            remaps=settings.palette_remaps,
            chroma_weight=1.35,
        )
    snapped = snap_image_to_palette(
        working,
        palette or (),
        tolerance=settings.palette_tolerance,
        remaps=settings.palette_remaps,
        chroma_weight=1.35 if cel_ink else 1.0,
    )
    if cel_ink:
        from vectorizer.raster.preprocess import cleanup_cel_fills

        return cleanup_cel_fills(snapped, ink_rgb=_darkest_palette_rgb(palette))
    return snapped


def _palette_has_cel_ink(palette: tuple[str, ...]) -> bool:
    from vectorizer.raster.color import hex_to_rgb

    for color in palette:
        r, g, b = hex_to_rgb(color)
        luma = 0.299 * r + 0.587 * g + 0.114 * b
        sat = max(r, g, b) - min(r, g, b)
        if luma <= 42 and sat <= 55:
            return True
    return False


def _darkest_palette_rgb(palette: tuple[str, ...]) -> tuple[int, int, int]:
    from vectorizer.raster.color import hex_to_rgb

    best = (20, 8, 0)
    best_luma = 999.0
    for color in palette:
        rgb = hex_to_rgb(color)
        luma = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
        if luma < best_luma:
            best = rgb
            best_luma = luma
    return best if best_luma <= 50 else (20, 8, 0)


def _scaled_progress(
    report: ProgressCallback, start: float, end: float
) -> ProgressCallback:
    span = max(0.0, end - start)

    def _inner(stage: str, fraction: float) -> None:
        report(stage, start + span * max(0.0, min(1.0, fraction)))

    return _inner


def _with_progress_tail(result: TraceResult, report: ProgressCallback) -> TraceResult:
    report(STAGE_CURVES if result.backend_name != "vtracer" else STAGE_SVG, 0.95)
    settings = result.settings
    # Only unlimited traces (no locked palette, target_colors 0). Default off.
    if (
        settings.cluster_similar_colors
        and not settings.palette
        and int(settings.target_colors) == 0
    ):
        from vectorizer.svg.edit import cluster_similar_fills

        clustered = cluster_similar_fills(result.document)
        if clustered is not result.document:
            result = replace(result, document=clustered)
    # Apply stroke/gap paint styles to the live preview document, not only on export.
    if settings.svg_paint_style.value != "fill":
        from vectorizer.svg.edit import apply_paint_style

        styled = apply_paint_style(
            result.document,
            settings.svg_paint_style,
            gap_filler_width=settings.gap_filler_width,
            gap_filler_non_scaling=settings.gap_filler_non_scaling,
        )
        if styled is not result.document:
            result = replace(result, document=styled)
    report(STAGE_FINALIZE, 1.0)
    return result
