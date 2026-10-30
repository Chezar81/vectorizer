"""SVG export writes backend geometry, not a rasterized preview."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from vectorizer.domain.document import VectorDocument
from vectorizer.domain.settings import SvgPaintStyle
from vectorizer.errors import ExportError
from vectorizer.svg.edit import apply_paint_style


def export_svg(
    document: VectorDocument,
    destination: str | Path,
    *,
    paint_style: SvgPaintStyle | str = SvgPaintStyle.FILL,
) -> Path:
    path = Path(destination)
    if path.exists() and path.is_dir():
        raise ExportError(f"Refusing to overwrite a directory: {path}")
    svg = apply_paint_style(document, SvgPaintStyle(paint_style)).raw_svg
    if not svg.strip():
        raise ExportError("There is no vector document to export.")
    payload = svg.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".vectorizer-", suffix=".svg", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception as exc:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass
        raise ExportError(f"Could not write SVG: {exc}") from exc
    return path
