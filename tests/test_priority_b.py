"""Priority B: cutout SVG groups, DXF line density, fill clustering, shrink advice."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from vectorizer.domain.settings import (
    DxfCurveMode,
    DxfLineDensity,
    EpsCompatibility,
    HierarchyMode,
    TraceSettings,
)
from vectorizer.errors import ImageOversizeError
from vectorizer.export.dxf import dxf_line_samples, export_dxf
from vectorizer.export.eps import eps_ps_level_arg
from vectorizer.export.svg import export_svg, group_svg_by_fill
from vectorizer.raster.loader import (
    load_image,
    recommend_max_side,
    shrink_to_max_side,
)
from vectorizer.svg.edit import MEDIUM_CLUSTER_DIST2, cluster_similar_fills
from vectorizer.svg.parse import parse_svg_document

_FLAT = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 10 10">
  <path d="M 0 0 H 4 V 4 H 0 Z" fill="#ff0000"/>
  <path d="M 5 0 H 9 V 4 H 5 Z" fill="#00ff00"/>
  <path d="M 0 5 H 4 V 9 H 0 Z" fill="#FF0000"/>
</svg>
"""

_CURVE = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 20 20">
  <path d="M 0 10 C 0 0 20 0 20 10" fill="#000000"/>
</svg>
"""

_NEAR = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="12" height="8" viewBox="0 0 12 8">
  <path d="M 0 0 H 4 V 4 H 0 Z" fill="#ff0000"/>
  <path d="M 4 0 H 8 V 4 H 4 Z" fill="#ff0000"/>
  <path d="M 8 0 H 12 V 4 H 8 Z" fill="#ff0101"/>
  <path d="M 0 4 H 4 V 8 H 0 Z" fill="#0000ff"/>
</svg>
"""


def _local(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _fill_groups(svg_text: str) -> list[tuple[str, int]]:
    root = ET.fromstring(svg_text)
    groups = []
    for child in list(root):
        if _local(child.tag) != "g":
            continue
        paths = [el for el in list(child) if _local(el.tag) == "path"]
        groups.append((child.get("fill") or "", len(paths)))
    return groups


def test_svg_cutout_export_groups_same_fill(tmp_path: Path) -> None:
    document = parse_svg_document(_FLAT, backend_name="test")
    grouped = group_svg_by_fill(document.raw_svg)
    fills = _fill_groups(grouped)
    assert len(fills) == 2
    red = next(item for item in fills if item[0] == "#ff0000")
    green = next(item for item in fills if item[0] == "#00ff00")
    assert red[1] == 2
    assert green[1] == 1

    dest = export_svg(
        document,
        tmp_path / "cutout.svg",
        settings=TraceSettings(hierarchical=HierarchyMode.CUTOUT),
    )
    assert _fill_groups(dest.read_text(encoding="utf-8")) == fills

    stacked = export_svg(
        document,
        tmp_path / "stacked.svg",
        settings=TraceSettings(hierarchical=HierarchyMode.STACKED),
    )
    assert "<g" not in stacked.read_text(encoding="utf-8").lower()


def test_dxf_line_density_samples_and_lines_export(tmp_path: Path) -> None:
    assert dxf_line_samples(DxfLineDensity.FEW) == 4
    assert dxf_line_samples("normal") == 8
    assert dxf_line_samples(DxfLineDensity.MANY) == 16
    document = parse_svg_document(_CURVE, backend_name="test")
    few = export_dxf(
        document,
        tmp_path / "few.dxf",
        curve_mode=DxfCurveMode.LINES,
        line_density=DxfLineDensity.FEW,
    )
    many = export_dxf(
        document,
        tmp_path / "many.dxf",
        curve_mode=DxfCurveMode.LINES,
        line_density=DxfLineDensity.MANY,
    )
    assert _polyline_vertices(few.read_text(encoding="utf-8")) < _polyline_vertices(
        many.read_text(encoding="utf-8")
    )
    splines = export_dxf(
        document,
        tmp_path / "splines.dxf",
        curve_mode=DxfCurveMode.SPLINES,
        line_density=DxfLineDensity.MANY,
    )
    assert "SPLINE" in splines.read_text(encoding="utf-8")
    assert eps_ps_level_arg(EpsCompatibility.COMPATIBLE) == "--export-ps-level=2"
    assert eps_ps_level_arg(EpsCompatibility.COMPACT) == "--export-ps-level=3"


def _polyline_vertices(dxf_text: str) -> int:
    lines = dxf_text.splitlines()
    total = 0
    for index, line in enumerate(lines):
        if line.strip() == "90" and index + 1 < len(lines):
            total += int(lines[index + 1].strip())
    return total


def test_cluster_similar_fills_merges_near_duplicates() -> None:
    document = parse_svg_document(_NEAR, backend_name="test")
    assert MEDIUM_CLUSTER_DIST2 == pytest.approx(0.0009)
    edited = cluster_similar_fills(document)
    colors = sorted(
        {
            path.fill.color.lower()
            for group in edited.groups
            for path in group.paths
            if path.fill is not None
        }
    )
    assert colors == ["#0000ff", "#ff0000"]
    untouched = cluster_similar_fills(document, max_dist2=0.0)
    assert untouched is document


def test_loader_shrink_recommendation(fixtures: dict[str, Path]) -> None:
    assert recommend_max_side(128, 128, max_pixels=128 * 128) == 0
    side = recommend_max_side(8000, 4000, max_pixels=25_000_000)
    assert 0 < side < 8000
    from PIL import Image

    tiny = Image.new("RGBA", (40, 20), (10, 20, 30, 255))
    shrunk = shrink_to_max_side(tiny, 10, max_pixels=1000)
    assert max(shrunk.size) <= 10
    assert shrunk.size[0] * shrunk.size[1] <= 1000

    with pytest.raises(ImageOversizeError) as raised:
        load_image(fixtures["mono_logo.png"], max_pixels=1000)
    assert raised.value.recommended_max_side > 0
    assert raised.value.width == 128

    loaded = load_image(
        fixtures["mono_logo.png"],
        max_pixels=1000,
        max_side=raised.value.recommended_max_side,
        shrink=True,
    )
    assert loaded.original_width == 128
    assert loaded.original_height == 128
    assert max(loaded.image.size) <= raised.value.recommended_max_side
    assert loaded.image.size[0] * loaded.image.size[1] <= 1000
    assert any("working copy" in note.lower() for note in loaded.notes)
