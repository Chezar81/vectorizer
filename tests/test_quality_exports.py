"""Tests for gap filler, stroke edges, parameterized shapes, palette remaps, DXF arcs."""

from __future__ import annotations

from pathlib import Path

import pytest

from vectorizer.domain.document import FillStyle, VectorDocument, VectorGroup, VectorPath
from vectorizer.domain.settings import (
    DxfCurveMode,
    SvgPaintStyle,
    TraceSettings,
)
from vectorizer.export.dxf import export_dxf
from vectorizer.export.svg import export_svg
from vectorizer.raster.palette import snap_image_to_palette
from vectorizer.svg.edit import apply_paint_style, snap_fills_to_palette
from vectorizer.svg.parse import parse_svg_document
from vectorizer.vectorize.shapes import CircleShape, RectShape, try_parameterized_shape


def _two_touching_rects_doc() -> VectorDocument:
    svg = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20" viewBox="0 0 40 20">
  <path d="M 0 0 L 20 0 L 20 20 L 0 20 Z" fill="#ff0000"/>
  <path d="M 20 0 L 40 0 L 40 20 L 20 20 Z" fill="#0000ff"/>
</svg>
"""
    return parse_svg_document(svg, backend_name="test")


def test_settings_round_trip_new_fields() -> None:
    original = TraceSettings(
        svg_paint_style=SvgPaintStyle.GAP_FILLER,
        gap_filler_width=1.5,
        gap_filler_non_scaling=False,
        parameterized_shapes=False,
        palette_tolerance=40,
        palette_remaps=(("#ff0000", "#00ff00"), ("#0000ff", "#00000000")),
        dxf_curve_mode=DxfCurveMode.LINES_AND_ARCS,
    ).validated()
    restored = TraceSettings.from_mapping(original.to_json())
    assert restored == original


def test_gap_filler_inserts_average_understroke(tmp_path: Path) -> None:
    document = _two_touching_rects_doc()
    styled = apply_paint_style(
        document, SvgPaintStyle.GAP_FILLER, gap_filler_width=2.0, gap_filler_non_scaling=True
    )
    assert 'id="gap-filler"' in styled.raw_svg
    assert "vector-effect" in styled.raw_svg
    # Average of red and blue is purple-ish #7f007f or #800080 depending on //2.
    assert "#7f007f" in styled.raw_svg.lower() or "#800080" in styled.raw_svg.lower()
    dest = export_svg(document, tmp_path / "gap.svg", settings=TraceSettings(
        svg_paint_style=SvgPaintStyle.GAP_FILLER
    ).validated())
    assert dest.is_file() and "gap-filler" in dest.read_text(encoding="utf-8")


def test_stroke_edges_replaces_fills() -> None:
    document = _two_touching_rects_doc()
    styled = apply_paint_style(document, SvgPaintStyle.STROKE_EDGES, gap_filler_width=1.0)
    assert 'id="stroke-edges"' in styled.raw_svg
    assert 'fill="#ff0000"' not in styled.raw_svg.lower()
    assert "stroke=" in styled.raw_svg


def test_parameterized_circle_and_rect() -> None:
    import math

    circle_pts = [
        (50.0 + 20.0 * math.cos(t), 40.0 + 20.0 * math.sin(t))
        for t in [i * math.tau / 48 for i in range(49)]
    ]
    shape = try_parameterized_shape(circle_pts, tolerance=0.8)
    assert isinstance(shape, CircleShape)
    assert abs(shape.radius - 20.0) < 1.0
    assert "<circle" in shape.to_svg(fill="#112233")

    rect_pts = [
        (10.0, 10.0),
        (40.0, 10.0),
        (40.0, 30.0),
        (10.0, 30.0),
        (10.0, 10.0),
    ]
    # Dense samples along edges.
    dense = []
    for a, b in zip(rect_pts, rect_pts[1:]):
        for i in range(8):
            t = i / 8
            dense.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    dense.append(rect_pts[0])
    shape = try_parameterized_shape(dense, tolerance=1.0)
    assert isinstance(shape, RectShape)
    assert abs(shape.width - 30.0) < 0.5
    assert "<rect" in shape.to_svg(fill="#abcdef")


def test_parse_circle_and_rect_elements() -> None:
    svg = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" width="100" height="80" viewBox="0 0 100 80">
  <circle cx="30" cy="30" r="10" fill="#ff0000"/>
  <rect x="50" y="10" width="40" height="20" fill="#00ff00"/>
</svg>
"""
    doc = parse_svg_document(svg, backend_name="test")
    assert doc.path_count == 2
    assert any("A " in p.d for g in doc.groups for p in g.paths)


def test_palette_tolerance_and_remap(fixtures: dict[str, Path]) -> None:
    from PIL import Image

    image = Image.new("RGBA", (4, 4), (255, 0, 0, 255))
    image.putpixel((0, 0), (10, 200, 10, 255))  # far from red
    # Tight tolerance: green fringe stays; only near-red snaps.
    snapped = snap_image_to_palette(
        image, ("#ff0000",), tolerance=20, remaps=(("#ff0000", "#0000ff"),)
    )
    assert snapped.getpixel((1, 1))[:3] == (0, 0, 255)
    assert snapped.getpixel((0, 0))[:3] == (10, 200, 10)

    document = _two_touching_rects_doc()
    remapped = snap_fills_to_palette(
        document,
        (),
        remaps=(("#ff0000", "#00ff00"), ("#0000ff", "#00000000")),
    )
    text = remapped.raw_svg.lower()
    assert "#00ff00" in text
    assert remapped.path_count == 1


def test_dxf_lines_and_arcs_emits_arc(tmp_path: Path) -> None:
    # Filled closed arc pair so the exporter keeps the geometry.
    svg = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">
  <path d="M 10 50 A 40 40 0 0 1 90 50 A 40 40 0 0 1 10 50 Z" fill="#336699"/>
</svg>
"""
    document = parse_svg_document(svg, backend_name="test")
    dest = export_dxf(document, tmp_path / "arcs.dxf", curve_mode=DxfCurveMode.LINES_AND_ARCS)
    text = dest.read_text(encoding="utf-8")
    assert "\n0\nARC\n" in text
