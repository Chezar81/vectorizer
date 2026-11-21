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
    """Quality presets used only while workflow is Automatic.

    The same three labels mean different things by image type. For blended or
    hard artwork they describe the input (noise and blend width). For
    photographs they describe the output (how many shapes to keep).
    """

    FAST = "fast"
    BALANCED = "balanced"
    HIGH = "high"


class AaArtifactRejection(str, Enum):
    """How hard to drop anti-aliased fringe that is not a real feature.

    This is not a minimum-pixel filter; `filter_speckle` already covers that.
    """

    NONE = "none"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


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
    """Export paint style for SVG (and SVG-derived previews).

    FILL — filled shapes only.
    STROKE_FILL — fill plus a same-color hairline (simple gap workaround).
    GAP_FILLER — filled shapes over average-color understrokes along shared edges.
    STROKE_EDGES — one stroke per shared edge, no fills (laser / vinyl cutting).
    """

    FILL = "fill"
    STROKE_FILL = "stroke_fill"
    GAP_FILLER = "gap_filler"
    STROKE_EDGES = "stroke_edges"


class DxfCurveMode(str, Enum):
    """DXF geometry. Fills are omitted in every mode."""

    LINES = "lines"
    LINES_AND_ARCS = "lines_and_arcs"
    SPLINES = "splines"


class DxfLineDensity(str, Enum):
    """Sample count for LINES mode only.

    Lines-and-arcs and splines keep their own geometry and ignore this.
    """

    FEW = "few"
    NORMAL = "normal"
    MANY = "many"


class EpsCompatibility(str, Enum):
    """PostScript level Inkscape uses for EPS.

    COMPACT is Level 3 (smaller files; Inkscape's own default, so existing
    EPS output stays the same size). COMPATIBLE is Level 2, which opens in
    more tools.
    """

    COMPACT = "compact"
    COMPATIBLE = "compatible"


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
    # Max sRGB distance (0–255) for palette snap. 255 = always snap (legacy).
    # Lower values leave unmatched fringe colors unchanged until remapped/removed.
    palette_tolerance: int = 255
    # Optional (source, target) remaps applied after snap. Target #00000000 drops.
    palette_remaps: tuple[tuple[str, str], ...] = ()
    svg_paint_style: SvgPaintStyle = SvgPaintStyle.FILL
    # Gap-filler / stroke-edge stroke width in CSS px (used by GAP_FILLER + STROKE_EDGES).
    gap_filler_width: float = 2.0
    gap_filler_non_scaling: bool = True
    # Prefer native circle/rect geometry when a contour fits (blend/gradient tracers).
    parameterized_shapes: bool = True
    dxf_curve_mode: DxfCurveMode = DxfCurveMode.LINES
    # LINES mode only: few ≈ 4 samples, normal ≈ 8 (historic default), many ≈ 16.
    dxf_line_density: DxfLineDensity = DxfLineDensity.NORMAL
    eps_compatibility: EpsCompatibility = EpsCompatibility.COMPACT
    # Post-pass for unlimited traces (empty palette and target_colors == 0).
    # Off by default: Automatic free-color already snaps to a suggested palette
    # when it has one, and merging near-duplicate fills without a request would
    # hide intentional steps. Medium OKLab radius lives in svg.edit.
    cluster_similar_colors: bool = False
    # 0 = loader default (GUI prompts, CLI/batch reject past ~25 megapixels).
    # A positive value shrinks the working copy; the source file is unchanged.
    max_side: int = 0
    # Curve follow vs wiggle flattening. 0 hugs pixels, 100 flattens them.
    # Scales blend fit tolerance/blur and the VTracer length threshold.
    # `path_precision` stays decimal places and is not a smoothness control.
    contour_smoothness: int = 50
    # Post-fit node density. Higher keeps more nodes (less Douglas–Peucker).
    node_budget: int = 50
    aa_artifact_rejection: AaArtifactRejection = AaArtifactRejection.MODERATE

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
        if not (0 <= int(self.palette_tolerance) <= 255):
            errors.append("palette_tolerance must be between 0 and 255")
        if not (0.0 <= float(self.gap_filler_width) <= 5.0):
            errors.append("gap_filler_width must be between 0 and 5")
        if not (0 <= int(self.contour_smoothness) <= 100):
            errors.append("contour_smoothness must be between 0 and 100")
        if not (0 <= int(self.node_budget) <= 100):
            errors.append("node_budget must be between 0 and 100")
        if not (0 <= int(self.max_side) <= 16384):
            errors.append("max_side must be between 0 and 16384 (0 = prompt)")
        palette = _normalize_palette(self.palette, errors)
        remaps = _normalize_remaps(self.palette_remaps, errors)
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
            palette_tolerance=int(self.palette_tolerance),
            palette_remaps=remaps,
            svg_paint_style=SvgPaintStyle(self.svg_paint_style),
            gap_filler_width=float(self.gap_filler_width),
            gap_filler_non_scaling=bool(self.gap_filler_non_scaling),
            parameterized_shapes=bool(self.parameterized_shapes),
            dxf_curve_mode=DxfCurveMode(self.dxf_curve_mode),
            dxf_line_density=DxfLineDensity(self.dxf_line_density),
            eps_compatibility=EpsCompatibility(self.eps_compatibility),
            cluster_similar_colors=bool(self.cluster_similar_colors),
            max_side=int(self.max_side),
            contour_smoothness=int(self.contour_smoothness),
            node_budget=int(self.node_budget),
            aa_artifact_rejection=AaArtifactRejection(self.aa_artifact_rejection),
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
            "length_threshold": scaled_length_threshold(
                s.length_threshold, s.contour_smoothness
            ),
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
        data["dxf_line_density"] = DxfLineDensity(self.dxf_line_density).value
        data["eps_compatibility"] = EpsCompatibility(self.eps_compatibility).value
        data["aa_artifact_rejection"] = AaArtifactRejection(self.aa_artifact_rejection).value
        data["palette"] = list(self.palette)
        data["palette_remaps"] = [list(pair) for pair in self.palette_remaps]
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
        if "dxf_line_density" in kwargs:
            kwargs["dxf_line_density"] = DxfLineDensity(kwargs["dxf_line_density"])
        if "eps_compatibility" in kwargs:
            kwargs["eps_compatibility"] = EpsCompatibility(kwargs["eps_compatibility"])
        if "aa_artifact_rejection" in kwargs:
            kwargs["aa_artifact_rejection"] = AaArtifactRejection(kwargs["aa_artifact_rejection"])
        if "palette" in kwargs:
            raw = kwargs["palette"] or ()
            kwargs["palette"] = tuple(str(item) for item in raw)
        if "palette_remaps" in kwargs:
            raw_maps = kwargs["palette_remaps"] or ()
            pairs: list[tuple[str, str]] = []
            for item in raw_maps:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    pairs.append((str(item[0]), str(item[1])))
            kwargs["palette_remaps"] = tuple(pairs)
        return cls(**kwargs).validated()


def artwork_input_width_px(quality: AutomaticQuality | str) -> int:
    """Input noise/blend width that Automatic quality means for artwork.

    High is about 1 px, balanced (the default for uncertain artwork) about 2 px,
    and fast is wider than 2 px. Photographs do not use this width; their
    quality is an output shape budget.
    """
    quality = AutomaticQuality(quality)
    if quality == AutomaticQuality.HIGH:
        return 1
    if quality == AutomaticQuality.FAST:
        return 4
    return 2


def scaled_length_threshold(length_threshold: float, contour_smoothness: int) -> float:
    """Map contour smoothness 0–100 onto VTracer's 3.5–10 length threshold.

    Smoothness 50 keeps `length_threshold` (the recipe / slider value). Lower
    follows pixels more tightly; higher flattens wiggles. Decimal
    `path_precision` is unrelated.
    """
    smoothness = max(0, min(100, int(contour_smoothness)))
    base = min(10.0, max(3.5, float(length_threshold)))
    if smoothness <= 50:
        t = smoothness / 50.0
        value = 3.5 + t * (base - 3.5)
    else:
        t = (smoothness - 50) / 50.0
        value = base + t * (10.0 - base)
    return max(3.5, min(10.0, value))


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


def _normalize_remaps(
    remaps: tuple[tuple[str, str], ...] | list[tuple[str, str]] | list[list[str]],
    errors: list[str],
) -> tuple[tuple[str, str], ...]:
    if not remaps:
        return ()
    if len(remaps) > 64:
        errors.append("palette_remaps supports at most 64 entries")
        return ()
    out: list[tuple[str, str]] = []
    for item in remaps:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            errors.append(f"palette remap must be [from, to], got {item!r}")
            continue
        try:
            source = normalize_hex(str(item[0]))
            target = normalize_hex_or_transparent(str(item[1]))
        except ValueError as exc:
            errors.append(str(exc))
            continue
        out.append((source, target))
    return tuple(out)


def normalize_hex(value: str) -> str:
    text = value.strip().lower()
    if text.startswith("#"):
        text = text[1:]
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6 or any(ch not in "0123456789abcdef" for ch in text):
        raise ValueError(f"invalid color {value!r}")
    return f"#{text}"


def normalize_hex_or_transparent(value: str) -> str:
    """Accept #rrggbb or #rrggbbaa (00 alpha means drop / transparent)."""
    text = value.strip().lower()
    if text.startswith("#"):
        text = text[1:]
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) == 8:
        if any(ch not in "0123456789abcdef" for ch in text):
            raise ValueError(f"invalid color {value!r}")
        if text[6:] == "00":
            return "#00000000"
        return f"#{text[:6]}"
    if len(text) != 6 or any(ch not in "0123456789abcdef" for ch in text):
        raise ValueError(f"invalid color {value!r}")
    return f"#{text}"
