from __future__ import annotations

import json
import sys
from pathlib import Path

from vectorizer.cli import main as cli_main
from vectorizer.domain.settings import TraceSettings
from vectorizer.jobs.runner import TRACE_WORKER_FLAG, worker_process_arguments


def test_worker_argv_uses_module_when_not_frozen() -> None:
    args = worker_process_arguments(
        input_path=Path("in.png"),
        output_svg=Path("out.svg"),
        settings_path=Path("settings.json"),
        result_path=Path("result.json"),
    )
    assert args[:2] == ["-m", "vectorizer.jobs.trace_worker"]
    assert "--input" in args


def test_worker_argv_uses_flag_when_frozen(monkeypatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    args = worker_process_arguments(
        input_path=Path("in.png"),
        output_svg=Path("out.svg"),
        settings_path=Path("settings.json"),
        result_path=Path("result.json"),
    )
    assert args[0] == TRACE_WORKER_FLAG
    assert "-m" not in args


def test_cli_routes_trace_worker_flag(fixtures: dict[str, Path], tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(TraceSettings().to_json()), encoding="utf-8")
    svg = tmp_path / "job.svg"
    result = tmp_path / "result.json"
    code = cli_main(
        [
            TRACE_WORKER_FLAG,
            "--input",
            str(fixtures["mono_logo.png"]),
            "--output-svg",
            str(svg),
            "--settings",
            str(settings),
            "--result",
            str(result),
        ]
    )
    assert code == 0
    assert svg.is_file()
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["ok"] is True
