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
from vectorizer.vectorize.gradient_trace import GradientTracer
from vectorizer.vectorize.vtracer_backend import VTracerBackend


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
    palette = resolve_palette(image, validated, treatment, suggestion=auto)

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
        tuned = validated
        if palette:
            # Cel ink prep already quantized fills; keep layers tight so thin
            # outlines are not merged into neighbouring flats.
            layer_cap = 4 if _palette_has_cel_ink(palette) else 6
            tuned = replace(
                validated,
                color_precision=8,
                layer_difference=min(validated.layer_difference, layer_cap),
                filter_speckle=min(validated.filter_speckle, 1)
                if _palette_has_cel_ink(palette)
                else validated.filter_speckle,
            )
        report(STAGE_CONTOURS, 0.30)
        result = VTracerBackend().trace(
            working, tuned, on_progress=_scaled_progress(report, 0.30, 0.90)
        )
        if palette:
            report(STAGE_SVG, 0.93)
            snapped = snap_fills_to_palette(result.document, palette)
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
    if palette:
        report(STAGE_SVG, 0.93)
        snapped = snap_fills_to_palette(result.document, palette)
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
    from vectorizer.raster.analyzer import ContentKind

    if known_kind is not None:
        return known_kind == ContentKind.GRADIENT
    if analysis is not None:
        return analysis.content_kind == ContentKind.GRADIENT
    # Last resort: one analysis pass (manual PHOTO mode without a GUI hint).
    return (
        _automatic_analysis(image, settings).content_kind == ContentKind.GRADIENT
    )


def _vtracer_input(
    image: Image.Image,
    settings: TraceSettings,
    palette: tuple[str, ...] | None,
) -> Image.Image:
    if settings.apply_preprocess:
        working = preprocess_image(image, settings)
    else:
        working = image.convert("RGBA")
    if not palette:
        return working
    # Ink-heavy cel scenes: solidify outlines before the hard snap so JPEG
    # browns do not dissolve into orange fills and VTracer keeps continuous ink.
    if _palette_has_cel_ink(palette) and (
        settings.filter_speckle <= 1 and settings.target_colors == 0
    ):
        from vectorizer.raster.color import hex_to_rgb
        from vectorizer.raster.preprocess import prepare_cel_ink

        ink = _darkest_palette_rgb(palette)
        return prepare_cel_ink(working, palette, ink_rgb=ink)
    return snap_image_to_palette(working, palette)


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
    report(STAGE_FINALIZE, 1.0)
    return result
