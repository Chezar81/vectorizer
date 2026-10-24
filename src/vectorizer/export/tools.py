"""Optional external tools. Detected at runtime; never assumed present."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Optional absolute path from Settings → Preferences (empty/None = use PATH).
_inkscape_override: Path | None = None


@dataclass(frozen=True)
class ExternalTool:
    name: str
    path: Path | None
    version: str | None
    available: bool
    notes: str


def set_inkscape_override(path: str | Path | None) -> None:
    """Set or clear a user-configured Inkscape executable path."""
    global _inkscape_override
    if path is None or str(path).strip() == "":
        _inkscape_override = None
        return
    candidate = Path(str(path).strip()).expanduser()
    _inkscape_override = candidate


def inkscape_override() -> Path | None:
    return _inkscape_override


def find_inkscape(timeout: float = 5.0) -> ExternalTool:
    override = _inkscape_override
    if override is not None:
        if override.is_file():
            return _probe_inkscape(override, timeout=timeout, via_override=True)
        return ExternalTool(
            name="inkscape",
            path=override,
            version=None,
            available=False,
            notes=(
                f"Configured Inkscape path is missing or not a file: {override}. "
                "Update Settings → Preferences or clear the override."
            ),
        )
    path_str = shutil.which("inkscape")
    if not path_str:
        return ExternalTool(
            name="inkscape",
            path=None,
            version=None,
            available=False,
            notes="Inkscape was not found on PATH. EPS export is disabled until it is installed.",
        )
    return _probe_inkscape(Path(path_str), timeout=timeout, via_override=False)


def _probe_inkscape(
    path: Path, *, timeout: float, via_override: bool
) -> ExternalTool:
    version = None
    try:
        completed = subprocess.run(
            [str(path), "--version"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        line = (completed.stdout or completed.stderr or "").strip().splitlines()
        version = line[0] if line else None
    except (OSError, subprocess.TimeoutExpired):
        return ExternalTool(
            name="inkscape",
            path=path,
            version=None,
            available=False,
            notes=(
                "Configured Inkscape did not respond to --version."
                if via_override
                else "Inkscape was found but did not respond to --version."
            ),
        )
    origin = "override" if via_override else str(path)
    return ExternalTool(
        name="inkscape",
        path=path,
        version=version,
        available=True,
        notes=f"Using {path}"
        + (f" ({version})" if version else "")
        + (f" [{origin}]" if via_override else ""),
    )


def run_inkscape(
    args: list[str],
    *,
    timeout: float = 120.0,
) -> subprocess.CompletedProcess[str]:
    tool = find_inkscape()
    if not tool.available or tool.path is None:
        raise FileNotFoundError(tool.notes)
    # Never use shell=True; pass an argv list only.
    return subprocess.run(
        [str(tool.path), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
