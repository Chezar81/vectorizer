from __future__ import annotations

from pathlib import Path

from vectorizer.domain.settings import ColorMode, PathFitMode, TraceSettings
from vectorizer.export.svg import export_svg
from vectorizer.svg.parse import parse_svg_document
from vectorizer.vectorize.vtracer_backend import VTracerBackend
from vectorizer.raster.loader import load_image


def _trace(path: Path, **kwargs) -> object:
    image = load_image(path).image
    settings = TraceSettings(**kwargs).validated()
    return VTracerBackend().trace(image, settings)


def test_mono_logo_produces_svg_paths(fixtures: dict[str, Path]) -> None:
    result = _trace(fixtures["mono_logo.png"], colormode=ColorMode.BINARY, mode=PathFitMode.POLYGON)
    assert "<svg" in result.document.raw_svg.lower()
    assert result.document.path_count >= 1
    parsed = parse_svg_document(result.document.raw_svg, backend_name="vtracer")
    assert parsed.path_count == result.document.path_count
    assert parsed.groups


def test_color_logo_and_ordering(fixtures: dict[str, Path]) -> None:
    result = _trace(fixtures["aa_logo.png"], colormode=ColorMode.COLOR)
    orders = [path.source_order for group in result.document.groups for path in group.paths]
    assert orders == sorted(orders)
    assert result.document.path_count >= 1


def test_disconnected_regions(fixtures: dict[str, Path]) -> None:
    result = _trace(fixtures["disconnected.png"], colormode=ColorMode.COLOR, filter_speckle=0)
    assert result.document.path_count >= 2


def test_nested_shapes_export_valid_svg(fixtures: dict[str, Path], tmp_path: Path) -> None:
    result = _trace(fixtures["nested_holes.png"], colormode=ColorMode.BINARY, mode=PathFitMode.POLYGON)
    dest = tmp_path / "nested.svg"
    export_svg(result.document, dest)
    text = dest.read_text(encoding="utf-8")
    assert text.count("<path") >= 1
    # VTracer stacked mode typically uses overlapping fills rather than compound holes.
    parsed = parse_svg_document(text, backend_name="vtracer")
    assert parsed.width == result.document.width


def test_transparency_does_not_crash(fixtures: dict[str, Path]) -> None:
    result = _trace(fixtures["transparent.png"])
    assert "<svg" in result.document.raw_svg.lower()


def test_photo_like_stylized_output(fixtures: dict[str, Path]) -> None:
    result = _trace(fixtures["photo_like.png"], filter_speckle=8, color_precision=5)
    assert result.document.path_count >= 1
