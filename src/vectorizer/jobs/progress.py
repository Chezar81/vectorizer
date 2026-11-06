"""Progress reporting from the tracing worker to the GUI via NDJSON on stdout."""

from __future__ import annotations

import json
import sys
from typing import Callable

ProgressCallback = Callable[[str, float], None]

# English stage keys — also used as i18n lookup strings in the GUI.
STAGE_PREPARE = "Preparing…"
STAGE_ANALYZE = "Analyzing image…"
STAGE_COLORS = "Preparing colors…"
STAGE_CONTOURS = "Tracing contours…"
STAGE_CURVES = "Fitting curves…"
STAGE_SVG = "Building SVG…"
STAGE_FINALIZE = "Finishing…"


def emit_progress(stage: str, fraction: float) -> None:
    """Write one progress event. Safe to call from the worker process only."""
    payload = {
        "type": "progress",
        "stage": str(stage),
        "fraction": float(max(0.0, min(1.0, fraction))),
    }
    try:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except Exception:
        # Progress is best-effort; never fail a trace because of IPC.
        pass


def make_emitter(enabled: bool = True) -> ProgressCallback:
    """Return a callback that emits NDJSON, or a no-op when disabled."""

    if not enabled:
        return lambda _stage, _fraction: None
    return emit_progress


def parse_progress_line(line: str) -> tuple[str, float] | None:
    """Parse a single stdout line into (stage, fraction), or None if not progress."""
    text = line.strip()
    if not text.startswith("{") or '"progress"' not in text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("type") != "progress":
        return None
    stage = payload.get("stage")
    fraction = payload.get("fraction")
    if not isinstance(stage, str):
        return None
    try:
        value = float(fraction)
    except (TypeError, ValueError):
        return None
    return stage, max(0.0, min(1.0, value))
