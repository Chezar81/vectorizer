"""Shared-boundary cel tracer: topology, absorb, and dispatch wiring."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from vectorizer.domain.settings import (
    EdgeTreatment,
    PathFitMode,
    TraceSettings,
    WorkflowMode,
)
from vectorizer.raster.color import rgb_to_hex
from vectorizer.vectorize.cel_boundary_trace import (
    CelBoundaryTracer,
    _absorb_small_components,
    _ink_coverage_field,
    _label_palette,
    _merge_slivers,
    _recolor_flecks,
    _recolor_outliers,
    _regrow_fills_under_ink,
    _spatial_resnap,
    _split_shade_bands,
    _stroke_families,
)
from vectorizer.vectorize.dispatch import trace_prepared


def test_absorb_folds_freckle_into_neighbour() -> None:
    labels = np.full((20, 20), 0, dtype=np.int16)
    labels[8:12, 8:12] = 1  # 16-pixel island
    cleaned = _absorb_small_components(labels, min_area=20)
    assert int((cleaned == 1).sum()) == 0
    assert int((cleaned == 0).sum()) == 400


def test_cel_boundary_traces_simple_cel_badge() -> None:
    image = Image.new("RGBA", (64, 48), (255, 200, 210, 255))
    draw = ImageDraw.Draw(image)
    ink = (20, 8, 0)
    fill = (240, 140, 70)
    draw.rectangle((8, 8, 55, 39), outline=ink, width=2)
    draw.rectangle((14, 14, 40, 34), fill=fill)
    palette = (rgb_to_hex(ink), rgb_to_hex(fill), rgb_to_hex((255, 200, 210)))
    settings = TraceSettings(
        workflow=WorkflowMode.ADVANCED,
        edge_treatment=EdgeTreatment.PHOTO,
        mode=PathFitMode.POLYGON,
        filter_speckle=4,
        target_colors=0,
        palette=palette,
        apply_preprocess=False,
    ).validated()
    result = CelBoundaryTracer().trace(image, settings, palette)
    assert result.backend_name == "cel_boundary"
    assert result.document.path_count >= 2
    assert "<svg" in result.document.raw_svg.lower()


def test_dispatch_routes_large_cel_photo_to_boundary(tmp_path: Path) -> None:
    """Megapixel-scale cel ink + PHOTO edge uses the shared-boundary tracer."""
    # 500×400 = 200k pixels (>= 180k gate) with dark ink + flat fills.
    image = Image.new("RGBA", (500, 400), (255, 200, 210, 255))
    draw = ImageDraw.Draw(image)
    ink = (26, 10, 0)
    couch = (240, 140, 70)
    draw.rectangle((40, 80, 460, 320), outline=ink, width=4)
    draw.rectangle((60, 100, 440, 300), fill=couch)
    draw.ellipse((200, 160, 280, 220), outline=ink, width=3)
    palette = (
        rgb_to_hex(ink),
        rgb_to_hex(couch),
        rgb_to_hex((255, 200, 210)),
    )
    settings = TraceSettings(
        workflow=WorkflowMode.ADVANCED,
        edge_treatment=EdgeTreatment.PHOTO,
        mode=PathFitMode.POLYGON,
        filter_speckle=8,
        target_colors=0,
        palette=palette,
        apply_preprocess=False,
        contour_smoothness=65,
    ).validated()
    result = trace_prepared(image, settings)
    assert result.backend_name == "cel_boundary"
    assert result.document.path_count >= 2


def test_label_palette_snaps_near_misses() -> None:
    image = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
    image.putpixel((3, 3), (250, 5, 5, 255))  # near red
    palette = (rgb_to_hex((255, 0, 0)), rgb_to_hex((0, 0, 255)))
    labels = _label_palette(image, palette)
    assert labels.shape == (8, 8)
    assert int(labels[3, 3]) == 0


def _hairline_scene() -> tuple[Image.Image, Image.Image, tuple[str, ...]]:
    """Pink | orange halves split by a soft 1 px ink line (AA peak ~0.6)."""
    pink = np.array((255, 203, 213), dtype=np.float32)
    orange = np.array((236, 119, 42), dtype=np.float32)
    ink = np.array((26, 10, 0), dtype=np.float32)
    height, width = 60, 80
    soft = np.zeros((height, width, 3), dtype=np.float32)
    soft[:, :40] = pink
    soft[:, 40:] = orange
    for x, cov in ((39, 0.3), (40, 0.6), (41, 0.3)):
        soft[:, x] = (1.0 - cov) * soft[:, x] + cov * ink
    soft_img = Image.fromarray(soft.round().astype(np.uint8), "RGB").convert("RGBA")
    palette = (rgb_to_hex((26, 10, 0)), rgb_to_hex((236, 119, 42)), rgb_to_hex((255, 203, 213)))
    # Hard snap loses the hairline: blended pixels land on the fills.
    hard = np.where(np.arange(width)[None, :, None] < 40, pink, orange)
    hard = np.broadcast_to(hard, (height, width, 3)).astype(np.uint8)
    hard_img = Image.fromarray(np.ascontiguousarray(hard), "RGB").convert("RGBA")
    return soft_img, hard_img, palette


def test_ink_coverage_keeps_soft_hairline_between_fills() -> None:
    soft, hard, palette = _hairline_scene()
    labels = _label_palette(hard, palette)
    pal_rgb = np.array([(26, 10, 0), (236, 119, 42), (255, 203, 213)], dtype=np.float32)
    field = _ink_coverage_field(
        soft, (26, 10, 0), labels=labels, palette_rgb=pal_rgb, ink_index=0
    )
    assert float(field[30, 40]) >= 0.5
    assert float(field[30, 10]) == 0.0
    assert float(field[30, 70]) == 0.0


def test_regrow_runs_fills_under_ink() -> None:
    labels = np.full((10, 12), 1, dtype=np.int16)
    labels[:, 6:] = 2
    labels[:, 5:7] = 0  # ink column
    field = np.zeros((10, 12), dtype=np.float32)
    field[:, 5:7] = 1.0
    out = _regrow_fills_under_ink(labels, field, 0)
    assert int((out == 0).sum()) == 0
    assert set(np.unique(out).tolist()) == {1, 2}


def test_cel_boundary_draws_hairline_from_soft_source() -> None:
    soft, hard, palette = _hairline_scene()
    settings = TraceSettings(
        workflow=WorkflowMode.ADVANCED,
        edge_treatment=EdgeTreatment.PHOTO,
        mode=PathFitMode.POLYGON,
        filter_speckle=4,
        target_colors=0,
        palette=palette,
        apply_preprocess=False,
    ).validated()
    result = CelBoundaryTracer().trace(hard, settings, palette, soft_source=soft)
    fills = re.findall(r'fill="(#[0-9a-f]{6})"', result.document.raw_svg)
    strokes = [c for c in fills if c not in palette[1:]]
    # A soft hairline keeps its measured dark colour (not a fill, not lost).
    assert strokes
    r, g, b = (int(strokes[0][i : i + 2], 16) for i in (1, 3, 5))
    assert 0.299 * r + 0.587 * g + 0.114 * b < 110


def _resnap_scene() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Orange field with an ambiguous shade stripe and a crisp teal square."""
    orange, mauve, teal = (236, 119, 42), (185, 111, 81), (24, 163, 158)
    pal = np.array([orange, mauve, teal], dtype=np.float32)
    rgb = np.zeros((40, 40, 3), dtype=np.float32)
    rgb[:] = orange
    labels = np.zeros((40, 40), dtype=np.int16)
    # Stripe sits between orange and the muted entry; the snap picked mauve.
    rgb[5:35, 10:13] = (206, 108, 60)
    labels[5:35, 10:13] = 1
    rgb[20:26, 25:31] = teal
    labels[20:26, 25:31] = 2
    return labels, rgb, pal


def test_spatial_resnap_folds_ambiguous_stripe_into_dominant_fill() -> None:
    labels, rgb, pal = _resnap_scene()
    out = _spatial_resnap(
        labels,
        rgb,
        pal,
        frozen=np.zeros(labels.shape, dtype=bool),
        ink_index=None,
        radius=10,
        bonus=0.14,
    )
    assert int((out[5:35, 10:13] == 0).sum()) == 90


def test_spatial_resnap_keeps_small_clear_region() -> None:
    labels, rgb, pal = _resnap_scene()
    out = _spatial_resnap(
        labels,
        rgb,
        pal,
        frozen=np.zeros(labels.shape, dtype=bool),
        ink_index=None,
        radius=10,
        bonus=0.14,
    )
    assert int((out[20:26, 25:31] == 2).sum()) == 36


def test_shade_bands_split_striped_fill_but_not_flat_one() -> None:
    height, width = 100, 320
    rgb = np.zeros((height, width, 3), dtype=np.float32)
    rgb[:, :160] = (236, 119, 42)
    # Right half: wide light / dark pleat bands of the same orange label.
    for x0 in range(160, 320, 60):
        rgb[:, x0 : x0 + 30] = (236, 119, 42)
        rgb[:, x0 + 30 : x0 + 60] = (196, 96, 36)
    labels = np.zeros((height, width), dtype=np.int16)
    labels[:, 160:] = 1
    palette = ("#ec772a", "#d06c26")
    out, colors = _split_shade_bands(
        labels, rgb, palette, ink_index=None, under_ink=np.zeros((height, width), dtype=bool)
    )
    assert set(np.unique(out[:, :160]).tolist()) == {0}
    assert len(colors) > len(palette)
    assert len(np.unique(out[:, 160:])) >= 2
    # Bands follow the stripes: mid-stripe columns differ between light and dark.
    assert out[50, 175] != out[50, 205]


def test_shade_bands_follow_ink_ribs() -> None:
    height, width = 120, 200
    rgb = np.zeros((height, width, 3), dtype=np.float32)
    under = np.zeros((height, width), dtype=bool)
    # Five pleat pockets between 3 px ink ribs, alternating light / dark.
    edges = [0, 40, 80, 120, 160, 200]
    # JPEG-like blotches along each pocket that a 7 px box mean keeps.
    blotch = 14.0 * np.sign(np.sin(np.arange(height) * np.pi / 9.0))[:, None, None]
    for k in range(5):
        x0, x1 = edges[k], edges[k + 1]
        tone = np.asarray((236, 119, 42) if k % 2 == 0 else (200, 98, 36), dtype=np.float32)
        rgb[:, x0:x1] = tone + blotch * (tone / tone[0])
        if k:
            rgb[:, x0 - 1 : x0 + 2] = (26, 10, 0)
            under[:, x0 - 1 : x0 + 2] = True
    labels = np.zeros((height, width), dtype=np.int16)
    out, colors = _split_shade_bands(labels, rgb, ("#ec772a",), ink_index=None, under_ink=under)
    assert len(colors) == 2
    pocket = [out[10:-10, x0 + 5 : x1 - 5] for x0, x1 in zip(edges, edges[1:])]
    for p in pocket:
        assert len(np.unique(p)) == 1
    assert pocket[0][0, 0] == pocket[2][0, 0] == pocket[4][0, 0]
    assert pocket[1][0, 0] == pocket[3][0, 0] != pocket[0][0, 0]


def test_shade_bands_skip_thin_strips_on_narrow_bar() -> None:
    height, width = 14, 420
    rgb = np.zeros((height, width, 3), dtype=np.float32)
    rgb[:] = (160, 98, 46)
    rgb[5:8] = (120, 66, 22)  # 3 px darker line through a shaded frame bar
    labels = np.zeros((height, width), dtype=np.int16)
    out, colors = _split_shade_bands(
        labels, rgb, ("#a0622e",), ink_index=None, under_ink=np.zeros((height, width), dtype=bool)
    )
    assert set(np.unique(out).tolist()) == {0}


def test_recolor_outliers_splits_off_colour_component() -> None:
    height, width = 60, 120
    rgb = np.zeros((height, width, 3), dtype=np.float32)
    labels = np.full((height, width), 1, dtype=np.int16)
    rgb[:] = (255, 203, 213)
    labels[:, :60] = 0
    rgb[:, :60] = (102, 205, 199)  # floor teal
    labels[5:15, 80:110] = 0
    rgb[5:15, 80:110] = (125, 210, 230)  # sky-rim shadow sharing the teal label
    labels[40:50, 80:110] = 0
    rgb[40:50, 80:110] = (104, 204, 198)  # a second real teal patch
    sample = np.ones((height, width), dtype=bool)
    out, colors = _recolor_outliers(
        labels, rgb, ("#66cdc7", "#ffcbd5"), ink_index=None, sample=sample
    )
    assert len(colors) == 3
    assert set(np.unique(out[5:15, 80:110]).tolist()) == {2}
    assert set(np.unique(out[40:50, 80:110]).tolist()) == {0}
    assert set(np.unique(out[:, :60]).tolist()) == {0}


def test_merge_slivers_folds_similar_strip_keeps_distinct_line() -> None:
    labels = np.zeros((40, 80), dtype=np.int16)
    labels[10:12, :] = 1  # 2 px near-identical brown strip
    labels[25:27, :] = 2  # 2 px blue line
    pal = np.asarray([(160, 98, 46), (155, 96, 49), (30, 90, 200)], dtype=np.float32)
    out = _merge_slivers(labels, pal, None, max_dist=0.06)
    assert int((out == 1).sum()) == 0
    assert int((out == 2).sum()) == 2 * 80


def test_stroke_families_merge_near_duplicates() -> None:
    fills = _stroke_families(["#703810", "#783818", None, "#2050a0"], [500, 50, 30, 40], "#1a0a00")
    assert fills[0] == fills[1]
    assert fills[2] == "#1a0a00"
    assert fills[3] != fills[0]


def test_enclosing_fill_paints_before_bridged_doors() -> None:
    """Two doors bridged into one component out-count their frame ring."""
    image = Image.new("RGBA", (120, 100), (255, 203, 213, 255))
    draw = ImageDraw.Draw(image)
    red = (200, 90, 70)
    purple = (180, 130, 190)
    draw.rectangle((10, 10, 109, 89), fill=red)
    draw.rectangle((14, 14, 57, 85), fill=purple)
    draw.rectangle((62, 14, 105, 85), fill=purple)
    draw.rectangle((57, 40, 62, 44), fill=purple)
    palette = (rgb_to_hex((26, 10, 0)), rgb_to_hex(red), rgb_to_hex(purple), rgb_to_hex((255, 203, 213)))
    settings = TraceSettings(
        workflow=WorkflowMode.ADVANCED,
        edge_treatment=EdgeTreatment.PHOTO,
        mode=PathFitMode.POLYGON,
        filter_speckle=4,
        target_colors=0,
        palette=palette,
        apply_preprocess=False,
    ).validated()
    svg = CelBoundaryTracer().trace(image, settings, palette).document.raw_svg
    assert svg.index(f'fill="{palette[1]}"') < svg.index(f'fill="{palette[2]}"')


def _fleck_scene() -> tuple[np.ndarray, np.ndarray]:
    """Orange pocket + rust stripe (left), olive-brown frame far right."""
    height, width = 60, 160
    rgb = np.zeros((height, width, 3), dtype=np.float32)
    labels = np.zeros((height, width), dtype=np.int16)
    rgb[:, :100] = (214, 106, 50)  # pocket orange, label 0
    labels[:, 32:44] = 2
    rgb[:, 32:44] = (150, 62, 30)  # rust stripe, label 2
    labels[:, 120:] = 1
    rgb[:, 120:] = (162, 99, 46)  # frame brown, label 1
    return labels, rgb


def test_flecks_take_matching_local_label() -> None:
    labels, rgb = _fleck_scene()
    labels[20:26, 20:26] = 1  # frame-brown label on rust lamp shading
    rgb[20:26, 20:26] = (146, 60, 28)
    labels[40:46, 130:136] = 2  # rust label on frame brown, no rust nearby
    rgb[40:46, 130:136] = (160, 98, 45)
    sample = np.ones(labels.shape, dtype=bool)
    out = _recolor_flecks(labels, rgb, ink_index=None, sample=sample)
    assert set(np.unique(out[20:26, 20:26]).tolist()) == {2}
    assert set(np.unique(out[40:46, 130:136]).tolist()) == {1}


def test_ink_side_fleck_joins_pocket_fill() -> None:
    labels, rgb = _fleck_scene()
    ink = np.asarray((26, 10, 0), dtype=np.float32)
    orange = np.asarray((214, 106, 50), dtype=np.float32)
    shade = orange + 0.45 * (ink - orange)
    ink_field = np.zeros(labels.shape, dtype=np.float32)
    ink_field[:, 70:73] = 1.0  # a rib
    labels[20:30, 73:76] = 1  # dark AA beside the rib, snapped to frame brown
    rgb[20:30, 73:76] = shade
    labels[20:30, 85:88] = 1  # same colour away from ink keeps its label
    rgb[20:30, 85:88] = shade
    sample = ink_field < 0.2
    out = _recolor_flecks(
        labels, rgb, ink_index=None, sample=sample, ink_field=ink_field, ink_rgb=(26, 10, 0)
    )
    assert set(np.unique(out[20:30, 73:76]).tolist()) == {0}
    assert set(np.unique(out[20:30, 85:88]).tolist()) == {1}


def test_solid_ink_stroke_keeps_palette_ink_colour() -> None:
    image = Image.new("RGBA", (80, 60), (255, 203, 213, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 39, 59), fill=(236, 119, 42))
    draw.rectangle((38, 0, 41, 59), fill=(26, 10, 0))
    palette = (rgb_to_hex((26, 10, 0)), rgb_to_hex((236, 119, 42)), rgb_to_hex((255, 203, 213)))
    settings = TraceSettings(
        workflow=WorkflowMode.ADVANCED,
        edge_treatment=EdgeTreatment.PHOTO,
        mode=PathFitMode.POLYGON,
        filter_speckle=4,
        target_colors=0,
        palette=palette,
        apply_preprocess=False,
    ).validated()
    svg = CelBoundaryTracer().trace(image, settings, palette).document.raw_svg
    assert f'fill="{palette[0]}"' in svg


def test_outer_ring_wins_over_long_jagged_hole() -> None:
    """A fill whose hole has a longer perimeter must still paint its outline."""
    image = Image.new("RGBA", (120, 120), (255, 203, 213, 255))
    draw = ImageDraw.Draw(image)
    purple = (172, 76, 174)
    draw.rectangle((20, 20, 99, 99), fill=purple)
    dark = (113, 57, 123)
    # Comb-shaped hole: short bbox, very long crack perimeter.
    draw.rectangle((30, 30, 89, 89), fill=dark)
    for x in range(32, 88, 4):
        draw.rectangle((x, 30, x + 1, 87), fill=purple)
    palette = (rgb_to_hex((26, 10, 0)), rgb_to_hex(purple), rgb_to_hex(dark), rgb_to_hex((255, 203, 213)))
    settings = TraceSettings(
        workflow=WorkflowMode.ADVANCED,
        edge_treatment=EdgeTreatment.PHOTO,
        mode=PathFitMode.POLYGON,
        filter_speckle=4,
        target_colors=0,
        palette=palette,
        apply_preprocess=False,
    ).validated()
    svg = CelBoundaryTracer().trace(image, settings, palette).document.raw_svg
    purple_hex = rgb_to_hex(purple)
    purple_paths = [line for line in svg.splitlines() if purple_hex in line]
    assert purple_paths
    # The outline path must reach the outer edge (x=20) of the purple frame.
    assert any(" 20." in p or " 19." in p for p in purple_paths)
