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
    from vectorizer.domain.settings import EdgeTreatment

    image = load_image(fixtures["aa_logo.png"]).image
    analysis = analyze_image(image)
    assert analysis.content_kind in {
        ContentKind.FLAT_LOGO,
        ContentKind.ILLUSTRATION,
        ContentKind.BINARY_MARK,
    }
    assert analysis.suggested.edge_treatment == EdgeTreatment.BLENDED
    assert analysis.metrics.flat_mass >= 0.9
    assert analysis.metrics.background_rgb is not None
    # White-ish corners on the AA logo fixture.
    r, g, b = analysis.metrics.background_rgb
    assert r > 200 and g > 200 and b > 200
    if analysis.suggested.remove_background:
        assert analysis.suggested.background_r > 200


def test_cel_scene_keeps_wall_and_floor_colors() -> None:
    """Automatic must not merge large scene fills (pink wall, teal floor) away."""
    from vectorizer.domain.settings import EdgeTreatment
    from vectorizer.raster.color import hex_to_rgb
    from vectorizer.raster.palette import snap_image_to_palette

    image = Image.new("RGB", (320, 200), (255, 203, 213))  # pink wall
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 130, 319, 199), fill=(20, 180, 190))  # teal floor
    draw.rectangle((40, 80, 140, 150), fill=(243, 137, 70))  # orange couch
    draw.rectangle((200, 40, 260, 120), fill=(136, 62, 143))  # purple lamp
    draw.ellipse((220, 20, 280, 70), fill=(255, 220, 80))  # yellow shade
    # Dark brown ink outlines — cel cartoons must not route as Photograph.
    ink = (45, 22, 10)
    draw.rectangle((40, 80, 140, 150), outline=ink, width=3)
    draw.rectangle((200, 40, 260, 120), outline=ink, width=2)
    draw.ellipse((220, 20, 280, 70), outline=ink, width=2)
    analysis = analyze_image(image)
    assert analysis.content_kind == ContentKind.ILLUSTRATION
    assert analysis.photo_like is False
    assert analysis.suggested.edge_treatment == EdgeTreatment.BLENDED
    assert analysis.suggested.remove_background is False
    assert analysis.suggested.target_colors == 0
    assert analysis.suggested.smooth_noise is False
    assert analysis.metrics.background_rgb is not None
    br, bg, bb = analysis.metrics.background_rgb
    assert br > 200 and bg > 150 and bb > 160  # pink wall, not floor teal
    palette = analysis.suggested.palette
    assert len(palette) >= 4
    # Pink wall and teal floor must both appear as distinct palette inks.
    assert any(hex_to_rgb(c)[0] > 200 and hex_to_rgb(c)[2] > 180 for c in palette)
    assert any(hex_to_rgb(c)[1] > 140 and hex_to_rgb(c)[2] > 140 for c in palette)
    # Dark ink must survive as its own palette slot.
    assert any(sum(hex_to_rgb(c)) < 180 for c in palette)
    snapped = snap_image_to_palette(image, palette)
    wall = snapped.getpixel((10, 10))[:3]
    floor = snapped.getpixel((160, 170))[:3]
    # Wall must stay pinkish, not collapse to white/grey.
    assert wall[0] > 180 and wall[1] > 120 and wall[2] > 140
    assert wall[0] + wall[1] + wall[2] < 720  # not near-white
    # Floor must stay cyan/teal, not olive/brown.
    assert floor[2] >= floor[0] - 10
    assert floor[1] > 100
    assert any("cel" in note.lower() or "cartoon" in note.lower() for note in analysis.notes)


def test_large_cel_jpeg_uses_vtracer_with_ink_palette() -> None:
    """Megapixel cel scenes route to VTracer with a rich ink-aware palette.

    BlendTracer hard-cel collapsed these scenes to ~one path per colour; the
    PHOTO edge + cel ink prep keeps continuous outlines and flat fills.
    """
    from vectorizer.domain.settings import EdgeTreatment
    from vectorizer.export.svg import export_svg
    from vectorizer.jobs.runner import run_trace_sync
    from vectorizer.raster.color import hex_to_rgb

    image = Image.new("RGB", (1200, 700), (255, 203, 213))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 500, 1199, 699), fill=(20, 180, 190))
    draw.rectangle((150, 280, 900, 560), fill=(243, 137, 70), outline=(50, 25, 12), width=5)
    draw.rectangle((420, 60, 780, 260), fill=(160, 200, 230), outline=(50, 25, 12), width=4)
    import io

    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=85)
    buf.seek(0)
    image = Image.open(buf).convert("RGB")

    analysis = analyze_image(image)
    assert analysis.content_kind == ContentKind.ILLUSTRATION
    assert analysis.suggested.edge_treatment == EdgeTreatment.PHOTO
    assert analysis.suggested.remove_background is False
    assert analysis.suggested.smooth_noise is False
    assert analysis.suggested.filter_speckle <= 8
    assert analysis.suggested.palette
    assert len(analysis.suggested.palette) >= 8
    assert any(
        0.299 * r + 0.587 * g + 0.114 * b <= 45
        for r, g, b in (hex_to_rgb(c) for c in analysis.suggested.palette)
    )

    result = run_trace_sync(image, analysis.suggested)
    assert result.backend_name == "vtracer"
    assert result.document.path_count >= 3
    out = Path("/tmp/vectorizer_cel_test.svg")
    export_svg(result.document, out)
    svg = out.read_text(encoding="utf-8")
    assert "#ff" in svg.lower() or "#fe" in svg.lower() or "#fc" in svg.lower()


def test_cel_palette_keeps_pink_wall_off_orange_fill() -> None:
    """Chroma-weighted refine must not merge a pink wall into a salmon/orange ink."""
    from vectorizer.domain.settings import EdgeTreatment
    from vectorizer.raster.palette import snap_image_to_palette

    image = Image.new("RGB", (240, 160), (247, 152, 159))  # pink wall
    draw = ImageDraw.Draw(image)
    ink = (40, 18, 8)
    draw.rectangle((0, 110, 239, 159), fill=(20, 170, 185), outline=ink, width=2)  # teal floor
    draw.rectangle((30, 50, 120, 120), fill=(243, 137, 70), outline=ink, width=3)  # orange
    import io

    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=88)
    buf.seek(0)
    image = Image.open(buf).convert("RGB")

    analysis = analyze_image(image)
    assert analysis.content_kind == ContentKind.ILLUSTRATION
    assert analysis.suggested.edge_treatment == EdgeTreatment.BLENDED
    snapped = snap_image_to_palette(
        image, analysis.suggested.palette, chroma_weight=1.35
    )
    wall = snapped.getpixel((12, 12))[:3]
    chair = snapped.getpixel((70, 80))[:3]
    # Wall stays pinkish (R high, B not far below G); chair stays orange (B low).
    assert wall[0] > 200
    assert wall[2] >= wall[1] - 25
    assert wall[2] >= 120
    assert chair[0] > chair[2] + 40
    assert abs(wall[0] - chair[0]) + abs(wall[1] - chair[1]) + abs(wall[2] - chair[2]) > 60


def test_rich_cel_jpeg_with_many_fills_is_not_photograph() -> None:
    """Busy cel scenes can report tiny flat_mass vs a 12-ink probe; ink wins."""
    from vectorizer.domain.settings import EdgeTreatment
    from vectorizer.raster.color import hex_to_rgb

    image = Image.new("RGB", (960, 540), (255, 203, 213))  # pink wall
    draw = ImageDraw.Draw(image)
    ink = (40, 18, 8)
    # Many distinct flat fills — living-room complexity without photo grain.
    fills = [
        ((0, 360, 959, 539), (18, 170, 185)),  # teal floor
        ((80, 200, 420, 400), (243, 137, 70)),  # orange chair
        ((500, 120, 620, 340), (120, 55, 140)),  # purple lamp
        ((530, 70, 640, 150), (255, 220, 80)),  # yellow shade
        ((700, 260, 820, 340), (30, 140, 150)),  # teal phone
        ((200, 40, 360, 160), (150, 190, 220)),  # window
        ((40, 80, 120, 200), (90, 140, 70)),  # plant
        ((850, 80, 930, 200), (220, 60, 50)),  # picture mat
    ]
    for box, color in fills:
        draw.rectangle(box, fill=color, outline=ink, width=3)
    draw.ellipse((540, 300, 600, 360), fill=(90, 200, 90), outline=ink, width=2)
    draw.ellipse((250, 280, 290, 320), fill=(60, 40, 30), outline=ink, width=2)  # button
    import io

    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=82)
    buf.seek(0)
    image = Image.open(buf).convert("RGB")

    analysis = analyze_image(image)
    assert analysis.content_kind == ContentKind.ILLUSTRATION
    assert analysis.photo_like is False
    # Large ink-heavy cels use VTracer (PHOTO edge), not BlendTracer hard-cel.
    assert analysis.suggested.edge_treatment == EdgeTreatment.PHOTO
    assert analysis.suggested.target_colors == 0
    assert analysis.suggested.smooth_noise is False
    assert analysis.metrics.ink_outline_score >= 0.012
    assert len(analysis.suggested.palette) >= 8
    # Dark ink + teal + orange must all survive as distinct slots.
    assert any(sum(hex_to_rgb(c)) < 180 for c in analysis.suggested.palette)
    assert any(hex_to_rgb(c)[1] > 100 and hex_to_rgb(c)[2] > 100 for c in analysis.suggested.palette)
    assert any(hex_to_rgb(c)[0] > 180 and hex_to_rgb(c)[1] < 180 for c in analysis.suggested.palette)


def test_antialiased_logo_is_not_classified_as_photo() -> None:
    """AA fringe inflates unique colors; flat_mass must still select the blend path."""
    from vectorizer.domain.settings import EdgeTreatment

    image = Image.new("RGB", (256, 256), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((40, 40, 216, 216), fill=(200, 30, 30))
    draw.rectangle((90, 100, 166, 180), fill=(30, 60, 180))
    aa = image.resize((128, 128), Image.Resampling.LANCZOS).resize(
        (256, 256), Image.Resampling.LANCZOS
    )
    analysis = analyze_image(aa)
    assert analysis.content_kind in {ContentKind.FLAT_LOGO, ContentKind.ILLUSTRATION}
    assert analysis.photo_like is False
    assert analysis.suggested.edge_treatment == EdgeTreatment.BLENDED
    assert analysis.metrics.flat_mass >= 0.9
    assert analysis.metrics.palette_estimate <= 16


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
    # Use a non-black transparent matte so solidify_black_matte (icon canvases)
    # does not bake the clear pixels into opaque black.
    image = Image.new("RGBA", (32, 32), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 4, 28, 28), fill=(180, 40, 40, 255))
    from vectorizer.domain.settings import TraceSettings

    settings = TraceSettings(smooth_noise=True, target_colors=0).validated()
    processed = preprocess_image(image, settings)
    assert processed.getpixel((2, 2))[3] == 0
    assert processed.getpixel((16, 16))[3] == 255


def test_solidify_black_matte_for_icon_canvas() -> None:
    from vectorizer.raster.preprocess import solidify_black_matte

    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((16, 16, 48, 48), fill=(240, 80, 20, 255))
    solidified = solidify_black_matte(image)
    assert solidified.getpixel((2, 2))[:4] == (0, 0, 0, 255)
    assert solidified.getpixel((32, 32))[:3] == (240, 80, 20)


def test_settings_smooth_noise_round_trip() -> None:
    from vectorizer.domain.settings import TraceSettings

    original = TraceSettings(smooth_noise=True, target_colors=16).validated()
    restored = TraceSettings.from_mapping(original.to_json())
    assert restored.smooth_noise is True
    assert restored.target_colors == 16
