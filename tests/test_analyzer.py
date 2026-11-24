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
    # Artwork quality steps input noise, not the photo shape budget or fit knobs.
    assert fast.filter_speckle >= balanced.filter_speckle
    assert high.filter_speckle <= balanced.filter_speckle
    assert fast.color_precision == balanced.color_precision == high.color_precision
    assert fast.max_iterations == balanced.max_iterations == high.max_iterations
    assert fast.layer_difference == balanced.layer_difference == high.layer_difference
    assert fast.target_colors == balanced.target_colors == high.target_colors


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
    # Clean flat logos hard-snap via VTracer; soft blend iso was worse on RMSE.
    assert analysis.suggested.edge_treatment in {
        EdgeTreatment.HARD,
        EdgeTreatment.BLENDED,
    }
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
    """Large flat cel scenes stay on the blend tracer with an ink palette.

    Forcing every scene above ~180k pixels through VTracer exploded clean
    fills into thousands of paths. Blend hard-cel keeps the outlines.
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
    # Flat cel stays on the blend tracer. Routing every scene above ~180k
    # pixels through VTracer turned clean fills into thousands of paths.
    assert analysis.suggested.edge_treatment == EdgeTreatment.BLENDED
    assert analysis.suggested.remove_background is False
    assert analysis.suggested.smooth_noise is False
    assert analysis.suggested.filter_speckle <= 8
    assert analysis.suggested.palette
    assert len(analysis.suggested.palette) >= 4
    assert any(
        0.299 * r + 0.587 * g + 0.114 * b <= 45
        for r, g, b in (hex_to_rgb(c) for c in analysis.suggested.palette)
    )

    result = run_trace_sync(image, analysis.suggested)
    assert result.backend_name == "blend"
    assert 3 <= result.document.path_count <= 400
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
    from vectorizer.domain.settings import EdgeTreatment, PathFitMode
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
    # Busy megapixel cels may use the PHOTO *edge* (VTracer) while remaining
    # classified as illustration — not as ContentKind.PHOTO.
    assert analysis.suggested.edge_treatment in {
        EdgeTreatment.BLENDED,
        EdgeTreatment.PHOTO,
    }
    assert analysis.suggested.target_colors == 0
    assert analysis.suggested.smooth_noise is False
    assert analysis.metrics.ink_outline_score >= 0.012
    assert len(analysis.suggested.palette) >= 8
    # Dark ink + teal + orange must all survive as distinct slots.
    assert any(sum(hex_to_rgb(c)) < 180 for c in analysis.suggested.palette)
    assert any(hex_to_rgb(c)[1] > 100 and hex_to_rgb(c)[2] > 100 for c in analysis.suggested.palette)
    assert any(hex_to_rgb(c)[0] > 180 and hex_to_rgb(c)[1] < 180 for c in analysis.suggested.palette)
    # PHOTO-routed busy cels use polygon fit (fewer wobbly cubics than spline).
    if analysis.suggested.edge_treatment == EdgeTreatment.PHOTO:
        assert analysis.suggested.mode == PathFitMode.POLYGON
        assert analysis.suggested.contour_smoothness >= 60


def test_cleanup_cel_fills_preserves_dark_ink() -> None:
    """Light fill cleanup must not erase near-black outline pixels."""
    from vectorizer.raster.preprocess import cleanup_cel_fills

    image = Image.new("RGB", (80, 60), (255, 200, 210))
    draw = ImageDraw.Draw(image)
    ink = (26, 10, 0)
    draw.rectangle((10, 10, 70, 50), outline=ink, width=2)
    draw.rectangle((20, 20, 40, 40), fill=(240, 140, 70))
    # Sprinkle an orange freckle on the pink wall.
    image.putpixel((5, 5), (240, 140, 70))
    cleaned = cleanup_cel_fills(image.convert("RGBA"), ink_rgb=ink)
    # Outline pixel stays dark.
    outline = cleaned.getpixel((10, 30))[:3]
    assert sum(outline) < 80
    # Interior orange fill survives.
    fill = cleaned.getpixel((30, 30))[:3]
    assert fill[0] > fill[2] + 30


def test_antialiased_logo_is_not_classified_as_photo() -> None:
    """AA fringe inflates unique colors; flat_mass must still avoid the photo path."""
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
    assert analysis.suggested.edge_treatment in {
        EdgeTreatment.HARD,
        EdgeTreatment.BLENDED,
    }
    assert analysis.suggested.edge_treatment != EdgeTreatment.PHOTO
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

    # Near-black mark on a transparent black canvas (ChatGPT-style matte).
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((16, 16, 48, 48), fill=(18, 18, 18, 255))
    solidified = solidify_black_matte(image)
    assert solidified.getpixel((2, 2))[:4] == (0, 0, 0, 255)
    assert solidified.getpixel((32, 32))[:3] == (18, 18, 18)


def test_solidify_black_matte_skips_colourful_cutouts() -> None:
    """YouTube/Brave-style logos: colourful mark + RGBA(0,0,0,0) corners stay clear."""
    from vectorizer.raster.preprocess import solidify_black_matte

    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((16, 16, 48, 48), fill=(240, 80, 20, 255))
    solidified = solidify_black_matte(image)
    assert solidified.getpixel((2, 2))[:4] == (0, 0, 0, 0)
    assert solidified.getpixel((32, 32))[:3] == (240, 80, 20)


def test_solidify_black_matte_keeps_dark_badge_silhouette() -> None:
    """Opaque dark badge already fills the mark — transparent corners stay cut out."""
    from vectorizer.raster.preprocess import solidify_black_matte

    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 4, 60, 60), fill=(12, 12, 12, 255))
    draw.ellipse((22, 22, 42, 42), fill=(245, 245, 245, 255))
    solidified = solidify_black_matte(image)
    assert solidified.getpixel((0, 0))[3] == 0
    assert solidified.getpixel((32, 32))[:3] == (245, 245, 245)
    assert solidified.getpixel((32, 8))[:3] == (12, 12, 12)


def test_alpha_cutout_soft_ramp_is_not_gradient() -> None:
    """Map/badge cutouts with soft fills keep logo/blend — not GradientTracer."""
    image = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    # Soft blue ramp body + sharp black digit (OpenCPN-style).
    for y in range(16, 112):
        t = (y - 16) / 96.0
        color = (
            int(180 + 40 * t),
            int(200 + 20 * t),
            int(220 - 30 * t),
            255,
        )
        draw.line((16, y, 111, y), fill=color)
    draw.ellipse((20, 20, 108, 108), outline=(40, 80, 40, 255), width=6)
    draw.text((48, 52), "0", fill=(0, 0, 0, 255))
    analysis = analyze_image(image)
    assert analysis.content_kind != ContentKind.GRADIENT
    assert analysis.content_kind in {
        ContentKind.FLAT_LOGO,
        ContentKind.ILLUSTRATION,
    }
    assert analysis.suggested.preserve_transparency is True


def test_ensure_dark_ink_skips_logos_without_black_mass() -> None:
    """Light logos must not gain a synthetic black ink slot from AA fringe."""
    from vectorizer.raster.analyzer import _ensure_dark_ink

    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 56, 56), fill=(87, 184, 236, 255))
    draw.rectangle((20, 20, 44, 44), fill=(20, 126, 184, 255))
    palette = ("#57b8ec", "#147eb8", "#e4e4e4", "#106796")
    ensured = _ensure_dark_ink(palette, image)
    assert all(
        not (0.299 * int(c[1:3], 16) + 0.587 * int(c[3:5], 16) + 0.114 * int(c[5:7], 16) <= 20)
        for c in ensured
        if c.startswith("#") and len(c) == 7
    )
    assert "#1a0a00" not in ensured
    assert len(ensured) == len(palette)


def test_apply_automatic_quality_splits_artwork_and_photo() -> None:
    from vectorizer.domain.settings import EdgeTreatment, TraceSettings
    from vectorizer.raster.analyzer import apply_automatic_quality

    artwork = TraceSettings(
        edge_treatment=EdgeTreatment.BLENDED,
        filter_speckle=4,
        color_precision=6,
        layer_difference=10,
        max_iterations=10,
        corner_threshold=55,
        target_colors=0,
        length_threshold=4.0,
    )
    mid = apply_automatic_quality(artwork, AutomaticQuality.BALANCED, content_kind=ContentKind.FLAT_LOGO)
    fast = apply_automatic_quality(artwork, AutomaticQuality.FAST, content_kind=ContentKind.FLAT_LOGO)
    high = apply_automatic_quality(artwork, AutomaticQuality.HIGH, content_kind=ContentKind.FLAT_LOGO)
    assert high.filter_speckle < mid.filter_speckle < fast.filter_speckle
    assert high.filter_speckle <= 2
    assert fast.target_colors == high.target_colors == 0
    assert fast.layer_difference == mid.layer_difference == high.layer_difference
    assert fast.color_precision == high.color_precision == 6
    assert fast.max_iterations == high.max_iterations == 10
    assert fast.corner_threshold == high.corner_threshold == 55
    # Photo quality moves the shape budget and leaves fit knobs alone.
    photo = TraceSettings(
        edge_treatment=EdgeTreatment.PHOTO,
        filter_speckle=8,
        layer_difference=16,
        target_colors=24,
        color_precision=5,
        max_iterations=8,
        corner_threshold=70,
    )
    photo_mid = apply_automatic_quality(
        photo, AutomaticQuality.BALANCED, content_kind=ContentKind.PHOTO
    )
    photo_fast = apply_automatic_quality(
        photo, AutomaticQuality.FAST, content_kind=ContentKind.PHOTO
    )
    photo_high = apply_automatic_quality(
        photo, AutomaticQuality.HIGH, content_kind=ContentKind.PHOTO
    )
    assert photo_fast.target_colors < photo_mid.target_colors < photo_high.target_colors
    assert photo_fast.filter_speckle > photo_mid.filter_speckle > photo_high.filter_speckle
    assert photo_fast.layer_difference > photo_mid.layer_difference > photo_high.layer_difference
    assert photo_fast.color_precision == photo_high.color_precision == 5
    assert photo_fast.max_iterations == photo_high.max_iterations == 8
    assert photo_fast.corner_threshold == photo_high.corner_threshold == 70
    # Cel art on the photo tracer must not gain a posterize pass.
    cel = TraceSettings(
        edge_treatment=EdgeTreatment.PHOTO,
        filter_speckle=8,
        layer_difference=12,
        target_colors=0,
    )
    cel_fast = apply_automatic_quality(
        cel, AutomaticQuality.FAST, content_kind=ContentKind.ILLUSTRATION
    )
    cel_high = apply_automatic_quality(
        cel, AutomaticQuality.HIGH, content_kind=ContentKind.ILLUSTRATION
    )
    assert cel_fast.target_colors == 0
    assert cel_high.target_colors == 0
    assert cel_fast.filter_speckle > cel.filter_speckle > cel_high.filter_speckle


def test_photo_fixture_quality_is_shape_budget(fixtures: dict[str, Path]) -> None:
    image = load_image(fixtures["photo_like.png"]).image
    balanced = analyze_image(image, quality=AutomaticQuality.BALANCED)
    assert balanced.content_kind in {ContentKind.PHOTO, ContentKind.GRADIENT}
    fast = analyze_image(image, quality=AutomaticQuality.FAST).suggested
    high = analyze_image(image, quality=AutomaticQuality.HIGH).suggested
    mid = balanced.suggested
    assert fast.target_colors <= mid.target_colors <= high.target_colors
    assert fast.filter_speckle >= mid.filter_speckle >= high.filter_speckle
    assert fast.layer_difference >= mid.layer_difference >= high.layer_difference
    assert fast.color_precision == mid.color_precision == high.color_precision
    assert any("shape" in note.lower() for note in balanced.notes)


def test_hard_alpha_white_fringe_recommends_flatten_white() -> None:
    import numpy as np

    from vectorizer.raster.analyzer import TransparencyRecommendation

    arr = np.zeros((40, 40, 4), dtype=np.uint8)
    yy, xx = np.mgrid[0:40, 0:40]
    radius = np.hypot(yy - 20, xx - 20)
    arr[radius <= 12, 0] = 180
    arr[radius <= 12, 1] = 20
    arr[radius <= 12, 2] = 20
    arr[radius <= 12, 3] = 255
    halo = (radius > 12) & (radius <= 14.2)
    arr[halo, 0] = 250
    arr[halo, 1] = 250
    arr[halo, 2] = 250
    arr[halo, 3] = 255
    analysis = analyze_image(Image.fromarray(arr, "RGBA"))
    assert analysis.transparency.hard_mask is True
    assert analysis.transparency.recommendation == TransparencyRecommendation.FLATTEN_WHITE
    assert any("flatten" in note.lower() and "white" in note.lower() for note in analysis.notes)


def test_hard_alpha_custom_fringe_recommends_flatten_custom() -> None:
    import numpy as np

    from vectorizer.raster.analyzer import TransparencyRecommendation

    arr = np.zeros((40, 40, 4), dtype=np.uint8)
    yy, xx = np.mgrid[0:40, 0:40]
    radius = np.hypot(yy - 20, xx - 20)
    arr[radius <= 12, :3] = (180, 20, 20)
    arr[radius <= 12, 3] = 255
    halo = (radius > 12) & (radius <= 14.2)
    arr[halo, 0] = 20
    arr[halo, 1] = 40
    arr[halo, 2] = 200
    arr[halo, 3] = 255
    analysis = analyze_image(Image.fromarray(arr, "RGBA"))
    assert analysis.transparency.hard_mask is True
    assert analysis.transparency.recommendation == TransparencyRecommendation.FLATTEN_CUSTOM
    assert analysis.transparency.blend_rgb is not None
    assert any("flatten" in note.lower() for note in analysis.notes)


def test_soft_transparent_aa_recommends_leave() -> None:
    import numpy as np

    from vectorizer.raster.analyzer import TransparencyRecommendation

    arr = np.zeros((40, 40, 4), dtype=np.uint8)
    yy, xx = np.mgrid[0:40, 0:40]
    radius = np.hypot(yy - 20, xx - 20)
    cover = np.clip(255 - (radius - 8) * 28, 0, 255).astype(np.uint8)
    arr[..., 0] = 180
    arr[..., 1] = 30
    arr[..., 2] = 30
    arr[..., 3] = cover
    analysis = analyze_image(Image.fromarray(arr, "RGBA"))
    assert analysis.transparency.hard_mask is False
    assert analysis.transparency.recommendation == TransparencyRecommendation.LEAVE
    assert any("leave transparency" in note.lower() for note in analysis.notes)


def test_settings_smooth_noise_round_trip() -> None:
    from vectorizer.domain.settings import TraceSettings

    original = TraceSettings(smooth_noise=True, target_colors=16).validated()
    restored = TraceSettings.from_mapping(original.to_json())
    assert restored.smooth_noise is True
    assert restored.target_colors == 16
