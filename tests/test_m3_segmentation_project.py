from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from vectorizer.domain.settings import ColorMode, PathFitMode, TraceSettings
from vectorizer.jobs.runner import run_trace_sync
from vectorizer.project.io import ProjectData, load_project, save_project
from vectorizer.raster.loader import load_image
from vectorizer.segmentation.build import build_segmentation
from vectorizer.segmentation.history import SegmentationHistory
from vectorizer.segmentation.ops import brush_stroke, flood_fill, remove_small_regions


def test_build_and_flood_fill_changes_map(fixtures: dict[str, Path]) -> None:
    source = load_image(fixtures["disconnected.png"]).image
    seg = build_segmentation(source, TraceSettings(target_colors=4))
    before = seg.to_png_bytes()
    # Find an opaque pixel.
    px = next(
        (x, y)
        for y in range(seg.size[1])
        for x in range(seg.size[0])
        if seg.pixel(x, y)[3] > 0
    )
    edited = flood_fill(seg, px[0], px[1], (255, 0, 0, 255))
    assert edited.to_png_bytes() != before
    assert edited.pixel(px[0], px[1])[:3] == (255, 0, 0)


def test_remove_small_regions(fixtures: dict[str, Path]) -> None:
    image = Image.new("RGBA", (40, 40), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((5, 5, 30, 30), fill=(0, 0, 0, 255))
    draw.point((38, 38), fill=(0, 0, 0, 255))
    seg = build_segmentation(image, TraceSettings(target_colors=2, remove_background=False))
    cleaned = remove_small_regions(seg, min_pixels=5)
    assert cleaned.pixel(38, 38)[3] == 0
    assert cleaned.pixel(10, 10)[3] == 255


def test_undo_redo_memory_bound(fixtures: dict[str, Path]) -> None:
    source = load_image(fixtures["mono_logo.png"]).image
    seg = build_segmentation(source, TraceSettings(target_colors=2))
    history = SegmentationHistory(seg, max_bytes=2_000_000, max_steps=5)
    for i in range(8):
        edited = brush_stroke(history.current(), [(10 + i, 10)], (10, 20, 30, 255), radius=2)
        history.commit(edited)
    assert history.depth <= 5
    assert history.can_undo
    restored = history.undo()
    assert restored is not None
    assert history.can_redo
    history.redo()


def test_segmentation_edits_affect_retrace(fixtures: dict[str, Path]) -> None:
    source = load_image(fixtures["disconnected.png"]).image
    settings = TraceSettings(
        colormode=ColorMode.COLOR,
        mode=PathFitMode.POLYGON,
        filter_speckle=0,
        target_colors=4,
        apply_preprocess=True,
    ).validated()
    baseline = run_trace_sync(source, settings)

    seg = build_segmentation(source, settings)
    # Paint a large new region that must appear as an extra/different path set.
    edited = brush_stroke(
        seg,
        [(20, 10), (70, 10), (70, 40), (20, 40), (20, 10)],
        (200, 20, 20, 255),
        radius=3,
    )
    retrace_settings = TraceSettings(
        colormode=ColorMode.COLOR,
        mode=PathFitMode.POLYGON,
        filter_speckle=0,
        apply_preprocess=False,
    ).validated()
    edited_result = run_trace_sync(edited.image, retrace_settings)
    # Edits must change exported SVG content.
    assert edited_result.document.raw_svg != baseline.document.raw_svg
    assert "#c81414" in edited_result.document.raw_svg.lower() or edited_result.document.path_count != baseline.document.path_count


def test_project_round_trip(fixtures: dict[str, Path], tmp_path: Path) -> None:
    source = load_image(fixtures["aa_logo.png"]).image
    settings = TraceSettings(filter_speckle=3, target_colors=6).validated()
    seg = build_segmentation(source, settings)
    result = run_trace_sync(source, settings)
    dest = tmp_path / "demo.vproj"
    save_project(
        dest,
        ProjectData(
            source=source,
            settings=settings,
            segmentation=seg,
            result_svg=result.document.raw_svg,
            source_name="aa_logo.png",
            notes=("fixture",),
        ),
    )
    loaded = load_project(dest)
    assert loaded.source.size == source.size
    assert loaded.settings.filter_speckle == 3
    assert loaded.segmentation is not None
    assert loaded.segmentation.size == source.size
    assert loaded.result_svg and "<path" in loaded.result_svg
    assert loaded.document is not None
    assert loaded.document.path_count >= 1


def test_project_rejects_path_traversal(tmp_path: Path, fixtures: dict[str, Path]) -> None:
    import io
    import json
    import zipfile

    from vectorizer.errors import ProjectError
    import pytest

    bad = tmp_path / "evil.vproj"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "schema": 1,
                    "format": "vectorizer-project",
                    "source": "../evil.png",
                    "settings": TraceSettings().to_json(),
                }
            ),
        )
        buf = io.BytesIO()
        Image.new("RGBA", (4, 4), (0, 0, 0, 255)).save(buf, format="PNG")
        zf.writestr("../evil.png", buf.getvalue())
    with pytest.raises(ProjectError):
        load_project(bad)
