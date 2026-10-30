"""Choose blend tracing or VTracer from the edge treatment and palette."""

from __future__ import annotations

from dataclasses import replace

from PIL import Image

from vectorizer.domain.settings import EdgeTreatment, TraceSettings
from vectorizer.raster.palette import snap_image_to_palette, suggest_palettes
from vectorizer.raster.preprocess import preprocess_image
from vectorizer.svg.edit import snap_fills_to_palette
from vectorizer.vectorize.backend import TraceResult
from vectorizer.vectorize.blend_trace import BlendTracer
from vectorizer.vectorize.vtracer_backend import VTracerBackend


def trace_prepared(image: Image.Image, settings: TraceSettings) -> TraceResult:
    """Trace `image` with the engine selected by `settings`.

    Blended artwork is traced from the original pixels so anti-alias coverage
    can move the curve. Hard artwork and photographs go through VTracer, after
    an optional snap onto the constrained palette.
    """
    validated = settings.validated()
    treatment = resolve_edge_treatment(image, validated)
    palette = resolve_palette(image, validated, treatment)
    if treatment == EdgeTreatment.BLENDED and palette:
        try:
            return BlendTracer().trace(image, validated, palette)
        except Exception as exc:
            fallback = VTracerBackend().trace(_vtracer_input(image, validated, palette), validated)
            warning = f"Blend tracing failed ({exc}); used the standard tracer."
            return replace(fallback, warnings=fallback.warnings + (warning,))

    working = _vtracer_input(image, validated, palette if treatment != EdgeTreatment.HARD or palette else None)
    tuned = validated
    if palette:
        tuned = replace(validated, color_precision=8, layer_difference=min(validated.layer_difference, 6))
    result = VTracerBackend().trace(working, tuned)
    if palette:
        snapped = snap_fills_to_palette(result.document, palette)
        return replace(result, document=snapped, settings=validated)
    return replace(result, settings=validated)


def resolve_edge_treatment(image: Image.Image, settings: TraceSettings) -> EdgeTreatment:
    if settings.edge_treatment != EdgeTreatment.AUTO:
        return settings.edge_treatment
    if settings.colormode.value == "binary" or settings.mode.value == "none":
        return EdgeTreatment.HARD
    if settings.workflow.value != "automatic":
        return EdgeTreatment.HARD
    from vectorizer.raster.analyzer import analyze_image

    return analyze_image(image, quality=settings.automatic_quality).suggested.edge_treatment


def resolve_palette(
    image: Image.Image,
    settings: TraceSettings,
    treatment: EdgeTreatment,
) -> tuple[str, ...] | None:
    if settings.palette:
        return settings.palette
    if treatment == EdgeTreatment.HARD:
        return None
    suggestions = suggest_palettes(image)
    colors = suggestions.palettes.get(suggestions.best) or ()
    return colors or None


def _vtracer_input(
    image: Image.Image,
    settings: TraceSettings,
    palette: tuple[str, ...] | None,
) -> Image.Image:
    if settings.apply_preprocess:
        working = preprocess_image(image, settings)
    else:
        working = image.convert("RGBA")
    if palette:
        return snap_image_to_palette(working, palette)
    return working
