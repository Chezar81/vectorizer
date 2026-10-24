from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from vectorizer.domain.settings import AutomaticQuality, ColorMode, HierarchyMode, PathFitMode
from vectorizer.raster.analyzer import ContentKind, analyze_image
from vectorizer.raster.loader import load_image
from vectorizer.raster.preprocess import preprocess_image


def test_mono_suggests_binary(fixtures: dict[str, Path]) -> None:
    image = load_image(fixtures["mono_logo.png"]).image
    analysis = analyze_image(image)
    assert analysis.suggested.colormode == ColorMode.BINARY
    assert analysis.photo_like is False
    assert analysis.content_kind == ContentKind.BINARY_MARK


def test_photo_warning(fixtures: dict[str, Path]) -> None:
    image = load_image(fixtures["photo_like.png"]).image
    analysis = analyze_image(image)
    assert analysis.photo_like is True
    assert analysis.content_kind in {ContentKind.PHOTO, ContentKind.GRADIENT}
    assert analysis.suggested.target_colors > 0
    assert any("photograph" in note.lower() or "gradient" in note.lower() for note in analysis.notes)


def test_automatic_quality_tiers(fixtures: dict[str, Path]) -> None:
    image = load_image(fixtures["aa_logo.png"]).image
    balanced = analyze_image(image, quality=AutomaticQuality.BALANCED).suggested
    fast = analyze_image(image, quality=AutomaticQuality.FAST).suggested
    high = analyze_image(image, quality=AutomaticQuality.HIGH).suggested
    assert fast.filter_speckle >= balanced.filter_speckle
    assert fast.color_precision <= balanced.color_precision
    assert high.filter_speckle <= balanced.filter_speckle
    assert high.color_precision >= balanced.color_precision
    assert high.max_iterations >= balanced.max_iterations


def test_nested_holes_prefer_cutout(fixtures: dict[str, Path]) -> None:
    image = load_image(fixtures["nested_holes.png"]).image
    analysis = analyze_image(image)
    assert analysis.content_kind == ContentKind.BINARY_MARK
    assert analysis.suggested.hierarchical == HierarchyMode.CUTOUT


def test_logo_detects_white_background(fixtures: dict[str, Path]) -> None:
    image = load_image(fixtures["aa_logo.png"]).image
    analysis = analyze_image(image)
    assert analysis.content_kind in {
        ContentKind.FLAT_LOGO,
        ContentKind.ILLUSTRATION,
        ContentKind.BINARY_MARK,
    }
    assert analysis.metrics.background_rgb is not None
    # White-ish corners on the AA logo fixture.
    r, g, b = analysis.metrics.background_rgb
    assert r > 200 and g > 200 and b > 200
    if analysis.suggested.remove_background:
        assert analysis.suggested.background_r > 200


def test_thin_lines_keep_low_speckle(fixtures: dict[str, Path]) -> None:
    image = load_image(fixtures["thin_lines.png"]).image
    analysis = analyze_image(image)
    assert analysis.suggested.filter_speckle <= 4
    assert analysis.content_kind in {
        ContentKind.BINARY_MARK,
        ContentKind.LINE_ART,
        ContentKind.FLAT_LOGO,
    }


def test_pixel_art_uses_pixel_paths() -> None:
    image = Image.new("RGB", (48, 48), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 20, 20), fill=(200, 40, 40))
    draw.rectangle((24, 8, 36, 20), fill=(40, 120, 200))
    draw.rectangle((8, 24, 20, 36), fill=(40, 160, 80))
    draw.rectangle((24, 24, 36, 36), fill=(20, 20, 20))
    analysis = analyze_image(image)
    assert analysis.content_kind == ContentKind.PIXEL_ART
    assert analysis.suggested.mode == PathFitMode.PIXEL


def test_smooth_noise_preprocess_preserves_alpha() -> None:
    image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 4, 28, 28), fill=(180, 40, 40, 255))
    from vectorizer.domain.settings import TraceSettings

    settings = TraceSettings(smooth_noise=True, target_colors=0).validated()
    processed = preprocess_image(image, settings)
    assert processed.getpixel((2, 2))[3] == 0
    assert processed.getpixel((16, 16))[3] == 255


def test_settings_smooth_noise_round_trip() -> None:
    from vectorizer.domain.settings import TraceSettings

    original = TraceSettings(smooth_noise=True, target_colors=16).validated()
    restored = TraceSettings.from_mapping(original.to_json())
    assert restored.smooth_noise is True
    assert restored.target_colors == 16
