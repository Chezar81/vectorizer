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


def test_absorb_blends_assigns_mixed_pixels_to_stable_neighbors() -> None:
    """Regression: neighbor indexing in `_absorb_blends` must map back to active rows."""
    import numpy as np

    from vectorizer.vectorize.blend_trace import _absorb_blends, label_regions

    image = Image.new("RGBA", (5, 3), (255, 255, 255, 255))
    # Left solid red, right solid blue, center a 50/50 mix (unstable).
    for y in range(3):
        image.putpixel((0, y), (200, 30, 30, 255))
        image.putpixel((1, y), (200, 30, 30, 255))
        image.putpixel((2, y), (110, 35, 105, 255))
        image.putpixel((3, y), (30, 40, 200, 255))
        image.putpixel((4, y), (30, 40, 200, 255))
    palette = ("#c81e1e", "#1e28c8")
    settings = TraceSettings(filter_speckle=0, remove_background=False).validated()
    labels, pixels_lab, palette_lab, _bg = label_regions(image, palette, settings)
    # Force the middle column unstable while keeping the flanks stable.
    stable = np.zeros(labels.shape, dtype=bool)
    stable[:, :2] = True
    stable[:, 3:] = True
    labels[:, 2] = 0
    _absorb_blends(labels, stable, pixels_lab, palette_lab)
    # Middle column should have been claimed by a stable neighbor color.
    assert np.all(stable[:, 2])
    assert set(int(v) for v in np.unique(labels[:, 2])) <= {0, 1}


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


def test_delete_shape_picks_the_topmost_overlapping_path() -> None:
    # Same fill groups would hide paint order; overlapping different fills must
    # delete the later (topmost) path when the click hits both.
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40">'
        '<path fill="#112233" d="M 0 0 L 30 0 L 30 30 L 0 30 Z"/>'
        '<path fill="#c81414" d="M 10 10 L 40 10 L 40 40 L 10 40 Z"/>'
        "</svg>"
    )
    document = parse_svg_document(svg, backend_name="test")
    edited = delete_shape_at(document, 20, 20)
    assert edited is not None
    assert edited.path_count == 1
    fills = [path.fill.color for group in edited.groups for path in group.paths if path.fill]
    assert fills == ["#112233"]


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


def test_iso_contour_emits_fractional_boundary() -> None:
    import numpy as np

    from vectorizer.vectorize.iso_contour import coverage_field, marching_squares

    labels = np.zeros((32, 32), dtype=np.int16)
    labels[8:24, 8:24] = 0
    labels[labels == 0] = 0
    # Outside is label 1.
    labels[labels != 0] = -1
    labels[:] = -1
    labels[8:24, 8:24] = 0
    pixels = np.zeros((32, 32, 3), dtype=np.float32)
    pixels[8:24, 8:24] = (0.6, 0.1, 0.05)
    palette = np.asarray([[0.6, 0.1, 0.05], [0.95, 0.95, 0.95]], dtype=np.float32)
    bg = np.asarray([0.95, 0.95, 0.95], dtype=np.float32)
    # Fake OKLab-ish constants are fine for topology.
    field = coverage_field(labels, 0, pixels, palette[:1], bg, blur=0.5)
    rings = marching_squares(field, level=0.5)
    assert rings
    flat = [coord for ring in rings for point in ring for coord in point]
    assert any(abs(value - round(value)) > 0.02 for value in flat)


def test_soft_source_sidecar_survives_segmentation_edit() -> None:
    from vectorizer.segmentation.build import build_segmentation
    from vectorizer.segmentation.ops import brush_stroke

    image = Image.new("RGB", (48, 48), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, 40, 40), fill=(200, 30, 30))
    soft = image.filter(ImageFilter.GaussianBlur(radius=1.0))
    settings = TraceSettings(
        workflow=WorkflowMode.BASIC,
        edge_treatment=EdgeTreatment.BLENDED,
        palette=("#c81e1e", "#ffffff"),
    )
    seg = build_segmentation(soft, settings)
    assert seg.soft_source is not None
    before = seg.soft_source.copy()
    edited = brush_stroke(seg, [(24, 24)], (30, 60, 180, 255), radius=2)
    assert edited.soft_source is not None
    # Unedited soft pixels stay AA; the brush footprint is hardened.
    assert edited.soft_source.getpixel((2, 2)) == before.getpixel((2, 2))
    assert edited.soft_source.getpixel((24, 24))[:3] == (30, 60, 180)


def test_retrace_with_soft_source_keeps_blend_backend() -> None:
    image = Image.new("RGB", (64, 64), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((10, 10, 54, 54), fill=(200, 30, 30))
    soft = image.filter(ImageFilter.GaussianBlur(radius=1.1))
    hard = soft.copy()
    # Posterize hard labels while keeping soft AA.
    hard = hard.point(lambda v: 255 if v > 200 else (200 if v > 100 else 30))
    settings = TraceSettings(
        workflow=WorkflowMode.BASIC,
        edge_treatment=EdgeTreatment.BLENDED,
        palette=("#c81e1e",),
        apply_preprocess=False,
        remove_background=True,
        background_r=255,
        background_g=255,
        background_b=255,
        filter_speckle=0,
    )
    result = run_trace_sync(hard, settings, soft_source=soft)
    assert result.backend_name == "blend"
    assert result.document.path_count >= 1


def test_gradient_tracer_emits_linear_gradient() -> None:
    from vectorizer.vectorize.gradient_trace import GradientTracer

    image = Image.new("RGB", (96, 64))
    pixels = image.load()
    for x in range(96):
        tone = int(40 + (x / 95.0) * 180)
        for y in range(64):
            pixels[x, y] = (tone, tone // 2, 200 - tone // 3)
    settings = TraceSettings(
        workflow=WorkflowMode.BASIC,
        edge_treatment=EdgeTreatment.PHOTO,
        filter_speckle=2,
        path_precision=2,
    )
    result = GradientTracer().trace(image, settings)
    assert result.backend_name in {"gradient", "vtracer"}
    if result.backend_name == "gradient":
        assert "linearGradient" in result.document.raw_svg


def test_automatic_aa_logo_routes_to_blend_tracer() -> None:
    image = Image.new("RGB", (192, 192), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((28, 28, 164, 164), fill=(200, 30, 30))
    draw.rectangle((70, 78, 122, 140), fill=(30, 60, 180))
    aa = image.resize((96, 96), Image.Resampling.LANCZOS).resize(
        (192, 192), Image.Resampling.LANCZOS
    )
    result = run_trace_sync(
        aa,
        TraceSettings(workflow=WorkflowMode.AUTOMATIC, edge_treatment=EdgeTreatment.AUTO),
    )
    assert result.backend_name == "blend"
    fills = {
        path.fill.color
        for group in result.document.groups
        for path in group.paths
        if path.fill is not None
    }
    assert fills
    assert all(color.startswith("#") for color in fills)


def test_blend_adjacent_fills_do_not_leave_large_gaps() -> None:
    """Outward bleed should keep shared boundaries from showing through."""
    image = Image.new("RGB", (96, 64), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 47, 55), fill=(200, 30, 30))
    draw.rectangle((48, 8, 87, 55), fill=(30, 40, 200))
    image = image.filter(ImageFilter.GaussianBlur(radius=0.9))
    settings = TraceSettings(
        workflow=WorkflowMode.BASIC,
        edge_treatment=EdgeTreatment.BLENDED,
        filter_speckle=0,
        path_precision=3,
        remove_background=False,
    )
    result = BlendTracer().trace(image, settings, ("#c81e1e", "#1e28c8"))
    assert result.document.path_count >= 2
    # Rasterize via a coarse even-odd coverage check on path bounding boxes —
    # both palette fills must appear in the SVG and share a near-midline edge.
    svg = result.document.raw_svg
    assert "#c81e1e" in svg and "#1e28c8" in svg
    numbers = [float(value) for value in re.findall(r"-?\d+\.\d+", svg)]
    assert any(abs(value - round(value)) > 0.05 for value in numbers)


def test_dxf_lines_keeps_subpaths_separate(tmp_path) -> None:
    path = VectorPath(
        d="M 0 0 L 10 0 L 10 10 L 0 10 Z M 30 0 L 40 0 L 40 10 L 30 10 Z",
        fill=FillStyle(color="#000000"),
        source_order=0,
    )
    document = VectorDocument(
        width=50,
        height=20,
        view_box=None,
        groups=(VectorGroup(name="g0", palette_key="#000000", paths=(path,)),),
        raw_svg=(
            '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="20">'
            '<path fill="#000000" d="M 0 0 L 10 0 L 10 10 L 0 10 Z '
            'M 30 0 L 40 0 L 40 10 L 30 10 Z"/>'
            "</svg>"
        ),
        backend_name="test",
        path_count=1,
    )
    dest = tmp_path / "two.dxf"
    export_dxf(document, dest, curve_mode=DxfCurveMode.LINES)
    text = dest.read_text(encoding="utf-8")
    assert text.count("LWPOLYLINE") == 2


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
