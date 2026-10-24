"""Raster preview export of the vector result (configurable size and background)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from vectorizer.domain.document import VectorDocument
from vectorizer.errors import ExportError


def export_png_preview(
    document: VectorDocument,
    destination: str | Path,
    *,
    width: int | None = None,
    height: int | None = None,
    background: str | None = None,
) -> Path:
    """Rasterize the SVG with QSvgRenderer.

    `background` is a CSS color string, or None for transparent.
    Aspect ratio is preserved when only one dimension is set.
    """
    path = Path(destination)
    if path.exists() and path.is_dir():
        raise ExportError(f"Refusing to overwrite a directory: {path}")
    svg = document.raw_svg
    if not svg.strip():
        raise ExportError("There is no vector document to export.")

    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        raise ExportError("SVG could not be loaded for PNG export.")

    src_w = max(int(document.width or renderer.defaultSize().width() or 1), 1)
    src_h = max(int(document.height or renderer.defaultSize().height() or 1), 1)
    out_w, out_h = _resolve_size(src_w, src_h, width, height)

    image = QImage(QSize(out_w, out_h), QImage.Format.Format_ARGB32_Premultiplied)
    if background:
        image.fill(QColor(background))
    else:
        image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".vectorizer-", suffix=".png", dir=str(path.parent))
    os.close(fd)
    try:
        if not image.save(tmp_name, "PNG"):
            raise ExportError("Qt failed to encode PNG.")
        os.replace(tmp_name, path)
    except ExportError:
        _unlink(tmp_name)
        raise
    except Exception as exc:
        _unlink(tmp_name)
        raise ExportError(f"Could not write PNG: {exc}") from exc
    return path


def _resolve_size(
    src_w: int,
    src_h: int,
    width: int | None,
    height: int | None,
) -> tuple[int, int]:
    if width is None and height is None:
        return src_w, src_h
    if width is not None and height is not None:
        if width < 1 or height < 1:
            raise ExportError("PNG dimensions must be >= 1.")
        return int(width), int(height)
    aspect = src_w / float(src_h)
    if width is not None:
        if width < 1:
            raise ExportError("PNG width must be >= 1.")
        return int(width), max(1, int(round(width / aspect)))
    assert height is not None
    if height < 1:
        raise ExportError("PNG height must be >= 1.")
    return max(1, int(round(height * aspect))), int(height)


def _unlink(tmp_name: str) -> None:
    try:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    except OSError:
        pass
