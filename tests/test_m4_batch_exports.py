from __future__ import annotations

from pathlib import Path

import pytest

from vectorizer.batch.engine import (
    BatchJob,
    CollisionPolicy,
    ExportFormat,
    collect_inputs,
    resolve_output_path,
    run_batch,
)
from vectorizer.domain.settings import ColorMode, PathFitMode, TraceSettings
from vectorizer.export.dxf import export_dxf
from vectorizer.export.eps import export_eps, inkscape_available
from vectorizer.export.tools import find_inkscape
from vectorizer.jobs.runner import run_trace_sync
from vectorizer.raster.loader import load_image


def test_collect_inputs_and_collision_rename(tmp_path: Path, fixtures: dict[str, Path]) -> None:
    folder = tmp_path / "in"
    folder.mkdir()
    (folder / "a.png").write_bytes(fixtures["mono_logo.png"].read_bytes())
    (folder / "b.jpg").write_bytes(fixtures["simple.jpg"].read_bytes())
    (folder / "ignore.txt").write_text("nope", encoding="utf-8")
    found = collect_inputs(folder)
    assert len(found) == 2

    out = tmp_path / "out"
    out.mkdir()
    first = resolve_output_path(out, found[0], ".svg", CollisionPolicy.RENAME)
    assert first is not None
    first.write_text("<svg/>", encoding="utf-8")
    second = resolve_output_path(out, found[0], ".svg", CollisionPolicy.RENAME)
    assert second is not None and second != first
    skipped = resolve_output_path(out, found[0], ".svg", CollisionPolicy.SKIP)
    assert skipped is None


def test_batch_continue_on_error(tmp_path: Path, fixtures: dict[str, Path]) -> None:
    good = tmp_path / "good.png"
    bad = tmp_path / "bad.png"
    good.write_bytes(fixtures["mono_logo.png"].read_bytes())
    bad.write_bytes(b"not-an-image")
    out = tmp_path / "batch-out"
    job = BatchJob(
        inputs=(bad, good),
        output_dir=out,
        settings=TraceSettings(colormode=ColorMode.BINARY, mode=PathFitMode.POLYGON).validated(),
        formats=(ExportFormat.SVG,),
        collision=CollisionPolicy.OVERWRITE,
        continue_on_error=True,
    )
    summary = run_batch(job, summary_path=out / "batch_summary.json")
    assert summary.fail_count == 1
    assert summary.ok_count == 1
    assert (out / "batch_summary.json").is_file()
    assert (out / "batch_summary.md").is_file()
    assert (out / "good.svg").is_file()


def test_batch_unicode_names(tmp_path: Path, fixtures: dict[str, Path]) -> None:
    src = tmp_path / "logo 测试.png"
    src.write_bytes(fixtures["mono_logo.png"].read_bytes())
    out = tmp_path / "üñîçøde out"
    job = BatchJob(
        inputs=(src,),
        output_dir=out,
        settings=TraceSettings(colormode=ColorMode.BINARY).validated(),
        formats=(ExportFormat.SVG, ExportFormat.DXF),
    )
    summary = run_batch(job)
    assert summary.ok_count == 1
    assert any(Path(p).suffix == ".svg" for p in summary.results[0].outputs)
    assert any(Path(p).suffix == ".dxf" for p in summary.results[0].outputs)


def test_dxf_contains_polyline(fixtures: dict[str, Path], tmp_path: Path) -> None:
    image = load_image(fixtures["mono_logo.png"]).image
    result = run_trace_sync(
        image,
        TraceSettings(colormode=ColorMode.BINARY, mode=PathFitMode.POLYGON).validated(),
    )
    dest = tmp_path / "out.dxf"
    export_dxf(result.document, dest)
    text = dest.read_text(encoding="utf-8")
    assert "LWPOLYLINE" in text
    assert text.strip().endswith("EOF")


def test_dxf_elliptical_arc_is_not_a_chord(tmp_path: Path) -> None:
    """Quarter-circle SVG arc must curve away from the straight chord."""
    from vectorizer.domain.document import FillStyle, VectorDocument, VectorGroup, VectorPath
    from vectorizer.export.dxf import _sample_arc

    # Unit circle quarter from (1,0) to (0,1), large-arc=0, sweep=1.
    pts = _sample_arc((1.0, 0.0), 1.0, 1.0, 0.0, False, True, (0.0, 1.0), segments=8)
    assert pts[-1] == (0.0, 1.0)
    # Halfway sample (t=4/8) sits at (√2/2, √2/2), not on the chord y = 1 - x.
    mid = pts[3]
    chord_y = 1.0 - mid[0]
    assert abs(mid[1] - chord_y) > 0.15
    assert abs(mid[0] - mid[1]) < 0.08

    path = VectorPath(
        d="M 10 2 A 8 8 0 0 1 18 10",
        fill=FillStyle(color="#000000", opacity=1.0),
        fill_rule="nonzero",
        transform=None,
        source_order=0,
    )
    document = VectorDocument(
        width=20,
        height=20,
        view_box=None,
        groups=(VectorGroup(name="g0", palette_key="#000000", paths=(path,)),),
        raw_svg='<svg width="20" height="20"><path d="M 10 2 A 8 8 0 0 1 18 10"/></svg>',
        backend_name="test",
        path_count=1,
    )
    dest = tmp_path / "arc.dxf"
    export_dxf(document, dest, curve_segments=16)
    assert "LWPOLYLINE" in dest.read_text(encoding="utf-8")


@pytest.mark.skipif(not inkscape_available(), reason="Inkscape not installed")
def test_eps_via_inkscape(fixtures: dict[str, Path], tmp_path: Path) -> None:
    image = load_image(fixtures["mono_logo.png"]).image
    result = run_trace_sync(
        image,
        TraceSettings(colormode=ColorMode.BINARY, mode=PathFitMode.POLYGON).validated(),
    )
    dest = tmp_path / "out.eps"
    export_eps(result.document, dest, timeout=60.0)
    assert dest.is_file() and dest.stat().st_size > 50
    head = dest.read_bytes()[:20]
    assert b"EPS" in head or b"PS" in head or head.startswith(b"%!")


def test_inkscape_detection_reports_status() -> None:
    tool = find_inkscape()
    assert tool.name == "inkscape"
    assert isinstance(tool.available, bool)
