from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from vectorizer.domain.settings import ColorMode, TraceSettings
from vectorizer.export.pdf import export_pdf
from vectorizer.export.png import export_png_preview
from vectorizer.export.svg import export_svg
from vectorizer.jobs.runner import run_trace_sync
from vectorizer.presets import (
    duplicate_preset,
    list_presets,
    load_preset,
    save_preset,
    set_presets_dir_override,
)
from vectorizer.raster.loader import load_image
from vectorizer.raster.preprocess import preprocess_image
from vectorizer.svg.recolor import recolor_document


def test_background_removal_affects_alpha(fixtures: dict[str, Path]) -> None:
    image = load_image(fixtures["aa_logo.png"]).image
    settings = TraceSettings(
        remove_background=True,
        background_r=255,
        background_g=255,
        background_b=255,
        background_tolerance=40,
    ).validated()
    processed = preprocess_image(image, settings)
    assert processed.getpixel((2, 2))[3] == 0
    # Original unchanged.
    assert image.getpixel((2, 2))[3] == 255


def test_target_colors_quantizes(fixtures: dict[str, Path]) -> None:
    image = load_image(fixtures["photo_like.png"]).image
    settings = TraceSettings(target_colors=4).validated()
    processed = preprocess_image(image, settings)
    opaque = [c for c in processed.getcolors(maxcolors=64) or [] if c[1][3] > 0]
    assert len(opaque) <= 8


def test_retrace_with_background_removal(fixtures: dict[str, Path]) -> None:
    image = load_image(fixtures["transparent.png"]).image
    settings = TraceSettings(
        colormode=ColorMode.COLOR,
        remove_background=True,
        background_r=0,
        background_g=0,
        background_b=0,
        background_tolerance=10,
        preserve_transparency=True,
    ).validated()
    result = run_trace_sync(image, settings)
    assert "<svg" in result.document.raw_svg.lower()


def test_pdf_and_png_export(fixtures: dict[str, Path], tmp_path: Path) -> None:
    image = load_image(fixtures["mono_logo.png"]).image
    result = run_trace_sync(image, TraceSettings(colormode=ColorMode.BINARY).validated())
    pdf = export_pdf(result.document, tmp_path / "out.pdf")
    assert pdf.is_file() and pdf.stat().st_size > 100
    # PDF should not be a bare PNG renamed; check header.
    assert pdf.read_bytes()[:4] == b"%PDF"
    png = export_png_preview(
        result.document,
        tmp_path / "out.png",
        width=64,
        height=64,
        background="#ffffff",
    )
    assert png.is_file()
    opened = Image.open(png)
    assert opened.size == (64, 64)
    transparent = export_png_preview(
        result.document,
        tmp_path / "alpha.png",
        width=32,
        background=None,
    )
    assert Image.open(transparent).mode in {"RGBA", "P", "LA"}


def test_recolor_changes_fill(fixtures: dict[str, Path], tmp_path: Path) -> None:
    image = load_image(fixtures["mono_logo.png"]).image
    result = run_trace_sync(image, TraceSettings(colormode=ColorMode.BINARY).validated())
    fills = [g.palette_key for g in result.document.groups if g.palette_key]
    assert fills
    old = fills[0]
    recolored = recolor_document(result.document, {old: "#00aa55"})
    assert "#00aa55" in recolored.raw_svg.lower() or "#00AA55" in recolored.raw_svg
    export_svg(recolored, tmp_path / "recolor.svg")
    assert "#00aa55" in (tmp_path / "recolor.svg").read_text().lower()


def test_presets_round_trip(tmp_path: Path) -> None:
    set_presets_dir_override(tmp_path / "presets")
    try:
        settings = TraceSettings(
            filter_speckle=9,
            remove_background=True,
            target_colors=8,
            background_tolerance=12,
        ).validated()
        save_preset("Logo Soft", settings)
        assert "Logo Soft" in list_presets()
        loaded = load_preset("Logo Soft")
        assert loaded.filter_speckle == 9
        assert loaded.remove_background is True
        assert loaded.target_colors == 8
        duplicate_preset("Logo Soft", "Logo Soft copy")
        assert "Logo Soft copy" in list_presets()
    finally:
        set_presets_dir_override(None)


def test_settings_preprocess_json_round_trip() -> None:
    original = TraceSettings(
        remove_background=True,
        background_r=10,
        background_g=20,
        background_b=30,
        background_tolerance=15,
        target_colors=12,
        preserve_transparency=False,
    ).validated()
    restored = TraceSettings.from_mapping(original.to_json())
    assert restored == original
