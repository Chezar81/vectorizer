"""EPS export via optional Inkscape. SVG is the source of truth."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from vectorizer.domain.document import VectorDocument
from vectorizer.domain.settings import EpsCompatibility, TraceSettings
from vectorizer.errors import ExportError
from vectorizer.export.tools import find_inkscape, run_inkscape


def inkscape_available() -> bool:
    return find_inkscape().available


def eps_ps_level_arg(level: EpsCompatibility | str) -> str:
    """Inkscape `--export-ps-level` for one compatibility choice.

    Level 2 maximizes compatibility. Level 3 minimizes file size.
    Inkscape 1.0 and later accept this flag.
    """
    level = EpsCompatibility(level)
    number = "2" if level == EpsCompatibility.COMPATIBLE else "3"
    return f"--export-ps-level={number}"


def export_eps(
    document: VectorDocument,
    destination: str | Path,
    *,
    timeout: float = 120.0,
    ps_level: EpsCompatibility | str | None = None,
    settings: TraceSettings | None = None,
) -> Path:
    """Convert the document SVG to EPS using Inkscape.

    Requires a local Inkscape install. Uses a safe argv list and a timeout.
    `ps_level` wins over `settings.eps_compatibility`. The default is Level 3
    (minimize file size), matching Inkscape and previous exports.
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

    level = EpsCompatibility.COMPACT
    if settings is not None:
        level = EpsCompatibility(settings.eps_compatibility)
    if ps_level is not None:
        level = EpsCompatibility(ps_level)

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
                    eps_ps_level_arg(level),
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
