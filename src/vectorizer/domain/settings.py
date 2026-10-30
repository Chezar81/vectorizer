"""Validated vectorization settings mapped to the active backend."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from enum import Enum
from typing import Any, Mapping


class WorkflowMode(str, Enum):
    AUTOMATIC = "automatic"
    BASIC = "basic"
    ADVANCED = "advanced"


class AutomaticQuality(str, Enum):
    """Quality presets used only while workflow is Automatic."""

    FAST = "fast"
    BALANCED = "balanced"
    HIGH = "high"


class ColorMode(str, Enum):
    COLOR = "color"
    BINARY = "binary"


class HierarchyMode(str, Enum):
    STACKED = "stacked"
    CUTOUT = "cutout"


class PathFitMode(str, Enum):
    SPLINE = "spline"
    POLYGON = "polygon"
    PIXEL = "none"


class EdgeTreatment(str, Enum):
    """How boundary pixels are interpreted before curves are placed."""

    AUTO = "auto"
    BLENDED = "blended"
    HARD = "hard"
    PHOTO = "photo"


class SvgPaintStyle(str, Enum):
    """Export paint. Stroke+fill hides hairline gaps between adjacent fills."""

    FILL = "fill"
    STROKE_FILL = "stroke_fill"


class DxfCurveMode(str, Enum):
    """DXF geometry. Fills are omitted in both modes."""

    LINES = "lines"
    SPLINES = "splines"


@dataclass(frozen=True)
class TraceSettings:
    """Parameters that affect VTracer 0.6.x plus app-side preprocessing.

    Backend kwargs exclude preprocess fields. Values are validated before use.
    """

    workflow: WorkflowMode = WorkflowMode.AUTOMATIC
    automatic_quality: AutomaticQuality = AutomaticQuality.BALANCED
    colormode: ColorMode = ColorMode.COLOR
    hierarchical: HierarchyMode = HierarchyMode.STACKED
    mode: PathFitMode = PathFitMode.SPLINE
    filter_speckle: int = 4
    color_precision: int = 6
    layer_difference: int = 16
    corner_threshold: int = 60
    length_threshold: float = 4.0
    max_iterations: int = 10
    splice_threshold: int = 45
    path_precision: int = 3
    # App-side preprocessing (applied before VTracer; original image stays unchanged).
    preserve_transparency: bool = True
    remove_background: bool = False
    background_r: int = 255
    background_g: int = 255
    background_b: int = 255
    background_tolerance: int = 32
    # Soft palette control via quantization before tracing (None/0 = off).
    # VTracer 0.6 has no palette= kwarg; this is an honest preprocess substitute.
    target_colors: int = 0
    # Light median smooth on RGB before tracing (helps JPEG/photo noise).
    # Alpha is preserved; Automatic mode may enable this for noisy content.
    smooth_noise: bool = False
    # When False, the worker traces the provided raster as-is (used for
    # segmentation retrace so edits are not re-quantized away).
    apply_preprocess: bool = True
    # Blended artwork keeps anti-aliasing and places curves inside those pixels.
    # Hard artwork and pixel art snap to flat colors. Photographs posterize.
    edge_treatment: EdgeTreatment = EdgeTreatment.AUTO
    # Exact output colors. Empty means the tracer may choose.
    palette: tuple[str, ...] = ()
    svg_paint_style: SvgPaintStyle = SvgPaintStyle.FILL
    dxf_curve_mode: DxfCurveMode = DxfCurveMode.LINES

    def background_rgb_tuple(self) -> tuple[int, int, int]:
        return (int(self.background_r), int(self.background_g), int(self.background_b))

    def validated(self) -> TraceSettings:
        errors: list[str] = []
        if not isinstance(self.filter_speckle, int) or self.filter_speckle < 0:
            errors.append("filter_speckle must be an integer >= 0")
        if not (1 <= int(self.color_precision) <= 8):
            errors.append("color_precision must be between 1 and 8")
        if not (0 <= int(self.layer_difference) <= 128):
            errors.append("layer_difference must be between 0 and 128")
        if not (0 <= int(self.corner_threshold) <= 180):
            errors.append("corner_threshold must be between 0 and 180")
        if not (3.5 <= float(self.length_threshold) <= 10.0):
            errors.append("length_threshold must be between 3.5 and 10.0")
        if not (1 <= int(self.max_iterations) <= 64):
            errors.append("max_iterations must be between 1 and 64")
        if not (0 <= int(self.splice_threshold) <= 180):
            errors.append("splice_threshold must be between 0 and 180")
        if not (0 <= int(self.path_precision) <= 12):
            errors.append("path_precision must be between 0 and 12")
        for channel, name in (
            (self.background_r, "background_r"),
            (self.background_g, "background_g"),
            (self.background_b, "background_b"),
        ):
            if not (0 <= int(channel) <= 255):
                errors.append(f"{name} must be between 0 and 255")
        if not (0 <= int(self.background_tolerance) <= 255):
            errors.append("background_tolerance must be between 0 and 255")
        if not (0 <= int(self.target_colors) <= 256):
            errors.append("target_colors must be between 0 and 256 (0 = off)")
        palette = _normalize_palette(self.palette, errors)
        if errors:
            raise ValueError("; ".join(errors))
        return replace(
            self,
            workflow=WorkflowMode(self.workflow),
            automatic_quality=AutomaticQuality(self.automatic_quality),
            colormode=ColorMode(self.colormode),
            hierarchical=HierarchyMode(self.hierarchical),
            mode=PathFitMode(self.mode),
            filter_speckle=int(self.filter_speckle),
            color_precision=int(self.color_precision),
            layer_difference=int(self.layer_difference),
            corner_threshold=int(self.corner_threshold),
            length_threshold=float(self.length_threshold),
            max_iterations=int(self.max_iterations),
            splice_threshold=int(self.splice_threshold),
            path_precision=int(self.path_precision),
            preserve_transparency=bool(self.preserve_transparency),
            remove_background=bool(self.remove_background),
            background_r=int(self.background_r),
            background_g=int(self.background_g),
            background_b=int(self.background_b),
            background_tolerance=int(self.background_tolerance),
            target_colors=int(self.target_colors),
            smooth_noise=bool(self.smooth_noise),
            apply_preprocess=bool(self.apply_preprocess),
            edge_treatment=EdgeTreatment(self.edge_treatment),
            palette=palette,
            svg_paint_style=SvgPaintStyle(self.svg_paint_style),
            dxf_curve_mode=DxfCurveMode(self.dxf_curve_mode),
        )

    def to_backend_kwargs(self) -> dict[str, Any]:
        s = self.validated()
        return {
            "colormode": s.colormode.value,
            "hierarchical": s.hierarchical.value,
            "mode": s.mode.value,
            "filter_speckle": s.filter_speckle,
            "color_precision": s.color_precision,
            "layer_difference": s.layer_difference,
            "corner_threshold": s.corner_threshold,
            "length_threshold": s.length_threshold,
            "max_iterations": s.max_iterations,
            "splice_threshold": s.splice_threshold,
            "path_precision": s.path_precision,
        }

    def to_json(self) -> dict[str, Any]:
        data = asdict(self.validated())
        data["workflow"] = self.workflow.value
        data["automatic_quality"] = self.automatic_quality.value
        data["colormode"] = self.colormode.value
        data["hierarchical"] = self.hierarchical.value
        data["mode"] = self.mode.value
        data["edge_treatment"] = self.edge_treatment.value
        data["svg_paint_style"] = self.svg_paint_style.value
        data["dxf_curve_mode"] = self.dxf_curve_mode.value
        data["palette"] = list(self.palette)
        return data

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> TraceSettings:
        known = {f.name for f in fields(cls)}
        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            if key not in known:
                continue
            kwargs[key] = value
        if "workflow" in kwargs:
            kwargs["workflow"] = WorkflowMode(kwargs["workflow"])
        if "automatic_quality" in kwargs:
            kwargs["automatic_quality"] = AutomaticQuality(kwargs["automatic_quality"])
        if "colormode" in kwargs:
            kwargs["colormode"] = ColorMode(kwargs["colormode"])
        if "hierarchical" in kwargs:
            kwargs["hierarchical"] = HierarchyMode(kwargs["hierarchical"])
        if "mode" in kwargs:
            kwargs["mode"] = PathFitMode(kwargs["mode"])
        if "edge_treatment" in kwargs:
            kwargs["edge_treatment"] = EdgeTreatment(kwargs["edge_treatment"])
        if "svg_paint_style" in kwargs:
            kwargs["svg_paint_style"] = SvgPaintStyle(kwargs["svg_paint_style"])
        if "dxf_curve_mode" in kwargs:
            kwargs["dxf_curve_mode"] = DxfCurveMode(kwargs["dxf_curve_mode"])
        if "palette" in kwargs:
            raw = kwargs["palette"] or ()
            kwargs["palette"] = tuple(str(item) for item in raw)
        return cls(**kwargs).validated()


def _normalize_palette(palette: tuple[str, ...] | list[str], errors: list[str]) -> tuple[str, ...]:
    if palette is None:
        return ()
    if len(palette) > 32:
        errors.append("palette supports at most 32 colors")
        return ()
    normalized: list[str] = []
    for item in palette:
        try:
            normalized.append(normalize_hex(str(item)))
        except ValueError:
            errors.append(f"palette color must be #rrggbb, got {item!r}")
    return tuple(normalized)


def normalize_hex(value: str) -> str:
    text = value.strip().lower()
    if text.startswith("#"):
        text = text[1:]
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6 or any(ch not in "0123456789abcdef" for ch in text):
        raise ValueError(f"invalid color {value!r}")
    return f"#{text}"
