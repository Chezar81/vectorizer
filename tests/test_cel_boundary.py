"""Shared-boundary cel tracer: topology, absorb, and dispatch wiring."""

from __future__ import annotations

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
    _label_palette,
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
