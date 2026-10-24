from __future__ import annotations

import json
from pathlib import Path

from vectorizer.cli import main as cli_main
from vectorizer.domain.settings import TraceSettings
from vectorizer.jobs.trace_worker import run_trace
from vectorizer.jobs.runner import run_trace_sync
from vectorizer.raster.loader import load_image


def test_cli_writes_svg(fixtures: dict[str, Path], tmp_path: Path) -> None:
    dest = tmp_path / "out.svg"
    code = cli_main([str(fixtures["mono_logo.png"]), "-o", str(dest), "--binary", "--polygon"])
    assert code == 0
    assert dest.is_file()
    assert "<path" in dest.read_text(encoding="utf-8")


def test_worker_json_result(fixtures: dict[str, Path], tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(TraceSettings().to_json()), encoding="utf-8")
    svg = tmp_path / "job.svg"
    result = tmp_path / "result.json"
    code = run_trace(fixtures["mono_logo.png"], svg, settings, result)
    assert code == 0
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["path_count"] >= 1


def test_sync_trace_unicode_path(tmp_path: Path, fixtures: dict[str, Path]) -> None:
    dest = tmp_path / "图片 logo.png"
    dest.write_bytes(fixtures["thin_lines.png"].read_bytes())
    loaded = load_image(dest)
    result = run_trace_sync(loaded.image, TraceSettings().validated())
    assert result.document.path_count >= 1
