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


def test_diagonal_hairline_survives_vtracer() -> None:
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (64, 64), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    for offset in range(0, 48, 6):
        draw.line([(offset, 4), (offset + 12, 16)], fill=(0, 0, 0, 255), width=1)
    settings = TraceSettings(
        colormode=ColorMode.BINARY, mode=PathFitMode.POLYGON, filter_speckle=0
    ).validated()
    result = VTracerBackend().trace(image, settings)
    svg = result.document.raw_svg
    assert 'width="64"' in svg and 'height="64"' in svg
    # One-pixel diagonal clusters used to collapse to empty "M0,0 Z" paths.
    assert 'd=""' not in svg
    assert result.document.path_count >= 8


def test_compact_path_data_turns_straight_cubics_into_lines() -> None:
    from vectorizer.vectorize.vtracer_backend import _compact_path_data

    d = "M0,0 C2,0 4,0 6,0 C6,2 6,4 6,6 C4,8 2,8 0,6 Z"
    out = _compact_path_data(d, 0.5)
    assert out.startswith("M0 0 L3 0 L3 3 C")
    assert out.endswith("Z")


def test_quantize_keeps_exact_solids() -> None:
    from PIL import Image

    from vectorizer.raster.preprocess import _quantize_rgba

    image = Image.new("RGBA", (40, 10), (250, 10, 10, 255))
    for x0, color in ((10, (10, 200, 10)), (20, (12, 12, 240)), (30, (240, 240, 20))):
        image.paste(Image.new("RGBA", (10, 10), color + (255,)), (x0, 0))
    out = _quantize_rgba(image, 4)
    assert sorted(c for _n, c in out.getcolors()) == sorted(c for _n, c in image.getcolors())


def test_diagonal_hairline_survives_vtracer() -> None:
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (64, 64), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    for offset in range(0, 48, 6):
        draw.line([(offset, 4), (offset + 12, 16)], fill=(0, 0, 0, 255), width=1)
    settings = TraceSettings(
        colormode=ColorMode.BINARY, mode=PathFitMode.POLYGON, filter_speckle=0
    ).validated()
    result = VTracerBackend().trace(image, settings)
    svg = result.document.raw_svg
    assert 'width="64"' in svg and 'height="64"' in svg
    # One-pixel diagonal clusters used to collapse to empty "M0,0 Z" paths.
    assert 'd=""' not in svg
    assert result.document.path_count >= 8


def test_compact_path_data_turns_straight_cubics_into_lines() -> None:
    from vectorizer.vectorize.vtracer_backend import _compact_path_data

    d = "M0,0 C2,0 4,0 6,0 C6,2 6,4 6,6 C4,8 2,8 0,6 Z"
    out = _compact_path_data(d, 0.5)
    assert out.startswith("M0 0 L3 0 L3 3 C")
    assert out.endswith("Z")


def test_quantize_keeps_exact_solids() -> None:
    from PIL import Image

    from vectorizer.raster.preprocess import _quantize_rgba

    image = Image.new("RGBA", (40, 10), (250, 10, 10, 255))
    for x0, color in ((10, (10, 200, 10)), (20, (12, 12, 240)), (30, (240, 240, 20))):
        image.paste(Image.new("RGBA", (10, 10), color + (255,)), (x0, 0))
    out = _quantize_rgba(image, 4)
    assert sorted(c for _n, c in out.getcolors()) == sorted(c for _n, c in image.getcolors())
