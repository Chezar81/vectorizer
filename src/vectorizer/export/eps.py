"""EPS export via optional Inkscape. SVG is the source of truth."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from vectorizer.domain.document import VectorDocument
from vectorizer.errors import ExportError
from vectorizer.export.tools import find_inkscape, run_inkscape


def inkscape_available() -> bool:
    return find_inkscape().available


def export_eps(document: VectorDocument, destination: str | Path, *, timeout: float = 120.0) -> Path:
    """Convert the document SVG to EPS using Inkscape.

    Requires a local Inkscape install. Uses a safe argv list and a timeout.
    """
    tool = find_inkscape()
    if not tool.available or tool.path is None:
        raise ExportError(tool.notes)

    path = Path(destination)
    if path.exists() and path.is_dir():
        raise ExportError(f"Refusing to overwrite a directory: {path}")
    svg = document.raw_svg
    if not svg.strip():
        raise ExportError("There is no vector document to export.")

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_svg = tempfile.mkstemp(prefix=".vectorizer-", suffix=".svg")
    os.close(fd)
    fd2, tmp_eps = tempfile.mkstemp(prefix=".vectorizer-", suffix=".eps", dir=str(path.parent))
    os.close(fd2)
    try:
        Path(tmp_svg).write_text(svg, encoding="utf-8")
        try:
            completed = run_inkscape(
                [
                    tmp_svg,
                    "--export-type=eps",
                    f"--export-filename={tmp_eps}",
                ],
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise ExportError(f"Inkscape timed out after {timeout:.0f}s.") from exc
        except FileNotFoundError as exc:
            raise ExportError(str(exc)) from exc
        if completed.returncode != 0 or not Path(tmp_eps).is_file() or Path(tmp_eps).stat().st_size == 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise ExportError(
                "Inkscape failed to write EPS" + (f": {detail}" if detail else ".")
            )
        os.replace(tmp_eps, path)
    except ExportError:
        _unlink(tmp_eps)
        raise
    except Exception as exc:
        _unlink(tmp_eps)
        raise ExportError(f"Could not write EPS: {exc}") from exc
    finally:
        _unlink(tmp_svg)
    return path


def _unlink(name: str) -> None:
    try:
        if os.path.exists(name):
            os.unlink(name)
    except OSError:
        pass
