"""Vector PDF export via Qt: SVG paths are painted as drawing operations, not a page bitmap."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QByteArray, QMarginsF, QSizeF
from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter
from PySide6.QtSvg import QSvgRenderer

from vectorizer.domain.document import VectorDocument
from vectorizer.errors import ExportError


def export_pdf(
    document: VectorDocument,
    destination: str | Path,
    *,
    margin_pt: float = 0.0,
) -> Path:
    """Write a PDF whose page content is the SVG rendered by QSvgRenderer onto QPdfWriter.

    Qt paints SVG geometry as vector operations into the PDF. This is not a full-page
    raster embed. Complex SVG features unsupported by Qt SVG may be approximated.
    """
    path = Path(destination)
    if path.exists() and path.is_dir():
        raise ExportError(f"Refusing to overwrite a directory: {path}")
    svg = document.raw_svg
    if not svg.strip():
        raise ExportError("There is no vector document to export.")

    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        raise ExportError("SVG could not be loaded for PDF export.")

    width = float(document.width) or float(renderer.defaultSize().width()) or 1.0
    height = float(document.height) or float(renderer.defaultSize().height()) or 1.0

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".vectorizer-", suffix=".pdf", dir=str(path.parent))
    os.close(fd)
    try:
        writer = QPdfWriter(tmp_name)
        writer.setTitle("Vectorizer export")
        writer.setCreator("Vectorizer")
        # Treat 1 SVG pixel ≈ 1 PDF point for predictable dimensions.
        page_size = QPageSize(QSizeF(width, height), QPageSize.Unit.Point)
        writer.setPageSize(page_size)
        writer.setPageMargins(
            QMarginsF(margin_pt, margin_pt, margin_pt, margin_pt),
            QPageLayout.Unit.Point,
        )

        painter = QPainter(writer)
        if not painter.isActive():
            raise ExportError("Could not open a paint device for PDF.")
        try:
            renderer.render(painter, painter.viewport())
        finally:
            painter.end()
        os.replace(tmp_name, path)
    except ExportError:
        _unlink(tmp_name)
        raise
    except Exception as exc:
        _unlink(tmp_name)
        raise ExportError(f"Could not write PDF: {exc}") from exc
    return path


def _unlink(tmp_name: str) -> None:
    try:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    except OSError:
        pass
