"""Palette constraint, blended edges, segmentation cleanup, and export options."""

from __future__ import annotations

import re

from PIL import Image, ImageDraw, ImageFilter

from vectorizer.domain.document import FillStyle, VectorDocument, VectorGroup, VectorPath
from vectorizer.domain.settings import (
    ColorMode,
    DxfCurveMode,
    EdgeTreatment,
    SvgPaintStyle,
    TraceSettings,
    WorkflowMode,
)
from vectorizer.export.dxf import export_dxf
from vectorizer.export.svg import export_svg
from vectorizer.jobs.runner import run_trace_sync
from vectorizer.raster.palette import SUGGESTED_COUNTS, suggest_palettes
from vectorizer.segmentation.map import SegmentationMap
from vectorizer.segmentation.ops import find_problems, zap_fringes
from vectorizer.svg.edit import delete_shape_at, remove_background_shapes, snap_fills_to_palette
from vectorizer.svg.parse import parse_svg_document
from vectorizer.vectorize.blend_trace import BlendTracer


def test_suggest_palettes_offers_counts_and_a_best_guess() -> None:
    image = Image.new("RGB", (48, 48), (240, 240, 240))
    draw = ImageDraw.Draw(image)
    draw.rectangle((4, 4, 20, 44), fill=(200, 16, 16))
    draw.rectangle((24, 4, 44, 44), fill=(20, 40, 180))
    suggestions = suggest_palettes(image)
    assert set(SUGGESTED_COUNTS) <= set(suggestions.palettes)
    assert suggestions.best in SUGGESTED_COUNTS
    assert len(suggestions.palettes[2]) == 2


def test_settings_round_trip_keeps_palette_and_export_choices() -> None:
    original = TraceSettings(
        edge_treatment=EdgeTreatment.BLENDED,
        palette=("#c81e1e", "#1e5ab4"),
        svg_paint_style=SvgPaintStyle.STROKE_FILL,
        dxf_curve_mode=DxfCurveMode.SPLINES,
    ).validated()
    restored = TraceSettings.from_mapping(original.to_json())
    assert restored.edge_treatment == EdgeTreatment.BLENDED
    assert restored.palette == ("#c81e1e", "#1e5ab4")
    assert restored.svg_paint_style == SvgPaintStyle.STROKE_FILL
    assert restored.dxf_curve_mode == DxfCurveMode.SPLINES


def test_snap_fills_uses_only_palette_colors() -> None:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">'
        '<path fill="#ff0000" d="M 0 0 L 20 0 L 20 20 L 0 20 Z"/>'
        '<path fill="#0000ff" d="M 20 0 L 40 0 L 40 20 L 20 20 Z"/>'
        "</svg>"
    )
    document = parse_svg_document(svg, backend_name="test")
    snapped = snap_fills_to_palette(document, ("#ff2020",))
    fills = [path.fill.color for group in snapped.groups for path in group.paths if path.fill]
    assert fills
    assert set(fills) == {"#ff2020"}


def test_blended_trace_places_a_fractional_edge() -> None:
    image = Image.new("RGB", (64, 64), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 12, 56, 52), fill=(200, 30, 30))
    image = image.filter(ImageFilter.GaussianBlur(radius=1.2))
    settings = TraceSettings(
        workflow=WorkflowMode.BASIC,
        edge_treatment=EdgeTreatment.BLENDED,
        filter_speckle=0,
        path_precision=3,
        remove_background=True,
        background_r=255,
        background_g=255,
        background_b=255,
        background_tolerance=36,
    )
    result = BlendTracer().trace(image, settings, ("#c81e1e",))
    assert result.backend_name == "blend"
    assert result.document.path_count >= 1
    fills = {
        path.fill.color
        for group in result.document.groups
        for path in group.paths
        if path.fill is not None
    }
    assert fills == {"#c81e1e"}
    numbers = [float(value) for value in re.findall(r"-?\d+\.\d+", result.document.raw_svg)]
    assert any(abs(value - round(value)) > 0.05 for value in numbers)


def test_binary_trace_stays_on_vtracer() -> None:
    image = Image.new("RGB", (32, 32), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((6, 6, 26, 26), fill=(0, 0, 0))
    result = run_trace_sync(
        image,
        TraceSettings(colormode=ColorMode.BINARY, workflow=WorkflowMode.BASIC),
    )
    assert result.backend_name == "vtracer"
    assert result.document.path_count >= 1


def test_zap_merges_a_fringe_into_the_neighbor() -> None:
    image = Image.new("RGBA", (7, 7), (180, 20, 20, 255))
    image.putpixel((3, 3), (20, 20, 180, 255))
    updated = zap_fringes(SegmentationMap(image), max_pixels=8)
    pixel = updated.image.getpixel((3, 3))
    assert pixel[:3] == (180, 20, 20)
    assert pixel[3] == 255


def test_finder_marks_a_one_pixel_gap() -> None:
    image = Image.new("RGBA", (5, 3), (0, 0, 0, 0))
    for x in range(5):
        image.putpixel((x, 1), (200, 0, 0, 255))
    image.putpixel((2, 1), (0, 0, 0, 0))
    problems = find_problems(SegmentationMap(image))
    assert (2, 1, "gap") in problems


def test_delete_shape_removes_the_clicked_path() -> None:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="40">'
        '<path fill="#ffffff" d="M 0 0 L 30 0 L 30 30 L 0 30 Z"/>'
        '<path fill="#c81414" d="M 40 0 L 70 0 L 70 30 L 40 30 Z"/>'
        "</svg>"
    )
    document = parse_svg_document(svg, backend_name="test")
    edited = delete_shape_at(document, 10, 10)
    assert edited is not None
    assert edited.path_count == 1
    fills = [path.fill.color for group in edited.groups for path in group.paths if path.fill]
    assert fills == ["#c81414"]


def test_remove_background_shapes_drops_the_paper_fill() -> None:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="40">'
        '<path fill="#ffffff" d="M 0 0 L 30 0 L 30 30 L 0 30 Z"/>'
        '<path fill="#c81414" d="M 40 0 L 70 0 L 70 30 L 40 30 Z"/>'
        "</svg>"
    )
    document = parse_svg_document(svg, backend_name="test")
    edited = remove_background_shapes(document, (255, 255, 255), tolerance=12)
    fills = [path.fill.color for group in edited.groups for path in group.paths if path.fill]
    assert fills == ["#c81414"]


def test_svg_stroke_and_fill_uses_a_same_color_hairline(tmp_path) -> None:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">'
        '<path fill="#112233" d="M 0 0 L 20 0 L 20 20 L 0 20 Z"/>'
        "</svg>"
    )
    document = parse_svg_document(svg, backend_name="test")
    dest = tmp_path / "stroke.svg"
    export_svg(document, dest, paint_style=SvgPaintStyle.STROKE_FILL)
    text = dest.read_text(encoding="utf-8")
    assert 'stroke="#112233"' in text
    assert 'stroke-width="1"' in text


def test_dxf_spline_mode_writes_a_cubic(tmp_path) -> None:
    path = VectorPath(
        d="M 0 0 C 30 0 30 40 0 40",
        fill=FillStyle(color="#000000"),
        source_order=0,
    )
    document = VectorDocument(
        width=40,
        height=40,
        view_box=None,
        groups=(VectorGroup(name="g0", palette_key="#000000", paths=(path,)),),
        raw_svg=(
            '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40">'
            '<path fill="#000000" d="M 0 0 C 30 0 30 40 0 40"/>'
            "</svg>"
        ),
        backend_name="test",
        path_count=1,
    )
    splines = tmp_path / "curves.dxf"
    export_dxf(document, splines, curve_mode=DxfCurveMode.SPLINES)
    spline_text = splines.read_text(encoding="utf-8")
    assert "SPLINE" in spline_text
    assert "LWPOLYLINE" not in spline_text
    lines = tmp_path / "lines.dxf"
    export_dxf(document, lines, curve_mode=DxfCurveMode.LINES)
    assert "LWPOLYLINE" in lines.read_text(encoding="utf-8")
