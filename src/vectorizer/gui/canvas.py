"""Zoomable canvas that shows a bitmap or a live SVG renderer."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QImage,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPixmap,
    QTransform,
    QWheelEvent,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import QFrame, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView

from vectorizer.gui.i18n import t
from vectorizer.raster.loader import OPEN_EXTENSIONS

DROP_EXTENSIONS = set(OPEN_EXTENSIONS) | {".vproj"}


def first_drop_path(event: QDragEnterEvent | QDragMoveEvent | QDropEvent) -> Path | None:
    """Return the first local image/project path from a drag/drop event."""
    mime = event.mimeData()
    if mime is None or not mime.hasUrls():
        return None
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = Path(url.toLocalFile())
        if path.suffix.lower() in DROP_EXTENSIONS:
            return path
    return None


def checkerboard_pixmap(tile: int = 8) -> QPixmap:
    image = QImage(tile * 2, tile * 2, QImage.Format.Format_RGB32)
    c1 = QColor(205, 205, 205)
    c2 = QColor(255, 255, 255)
    for y in range(tile * 2):
        for x in range(tile * 2):
            image.setPixelColor(x, y, c1 if (x // tile + y // tile) % 2 == 0 else c2)
    return QPixmap.fromImage(image)


class ImageCanvas(QGraphicsView):
    """Emits view_changed so paired canvases can stay synchronized."""

    view_changed = Signal()
    # Image-pixel coordinates when sampling is enabled (left click).
    pixel_clicked = Signal(int, int)
    # Local image/project path dropped while file drops are enabled.
    path_dropped = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
            | QPainter.RenderHint.TextAntialiasing
        )
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(checkerboard_pixmap())
        self.setAcceptDrops(True)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._svg_item: QGraphicsSvgItem | None = None
        self._svg_renderer: QSvgRenderer | None = None
        self._content_rect = QRectF()
        self._panning = False
        self._pan_start = QPointF()
        self._zoom = 1.0
        self._syncing = False
        self._sample_mode = False
        self._file_drop_enabled = False
        self.horizontalScrollBar().valueChanged.connect(self._emit_view_changed)
        self.verticalScrollBar().valueChanged.connect(self._emit_view_changed)

    def set_file_drop_enabled(self, enabled: bool) -> None:
        self._file_drop_enabled = bool(enabled)
        self.viewport().update()

    def file_drop_enabled(self) -> bool:
        return self._file_drop_enabled

    def set_sample_mode(self, enabled: bool) -> None:
        self._sample_mode = bool(enabled)
        if enabled:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.unsetCursor()

    def _emit_view_changed(self, *_args) -> None:
        if not self._syncing:
            self.view_changed.emit()

    def clear_content(self) -> None:
        self._scene.clear()
        self._pixmap_item = None
        self._svg_item = None
        self._svg_renderer = None
        self._content_rect = QRectF()
        self.resetTransform()
        self._zoom = 1.0

    def show_pixmap(self, pixmap: QPixmap) -> None:
        self.clear_content()
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._content_rect = QRectF(pixmap.rect())
        self._scene.setSceneRect(self._content_rect)
        self.fit_in_view()

    def show_svg(self, svg_text: str) -> bool:
        renderer = QSvgRenderer(QByteArray(svg_text.encode("utf-8")))
        if not renderer.isValid():
            return False
        self.clear_content()
        item = QGraphicsSvgItem()
        item.setSharedRenderer(renderer)
        self._scene.addItem(item)
        size = renderer.defaultSize()
        self._content_rect = QRectF(0, 0, max(size.width(), 1), max(size.height(), 1))
        self._scene.setSceneRect(self._content_rect)
        self._svg_item = item
        self._svg_renderer = renderer
        self.fit_in_view()
        return True

    def fit_in_view(self) -> None:
        if self._content_rect.isNull():
            return
        self.fitInView(self._content_rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = 1.0
        self._emit_view_changed()

    def zoom_actual(self) -> None:
        self.resetTransform()
        self._zoom = 1.0
        self._emit_view_changed()

    def apply_view(self, transform: QTransform, h_value: int, v_value: int) -> None:
        """Apply another canvas's view without emitting a sync feedback loop."""
        self._syncing = True
        try:
            self.setTransform(transform)
            self.horizontalScrollBar().setValue(h_value)
            self.verticalScrollBar().setValue(v_value)
        finally:
            self._syncing = False

    def view_state(self) -> tuple[QTransform, int, int]:
        return (
            self.transform(),
            self.horizontalScrollBar().value(),
            self.verticalScrollBar().value(),
        )

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(event)
        if not self._file_drop_enabled or not self._content_rect.isNull():
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setPen(QColor(90, 90, 90))
        font = painter.font()
        font.setPointSize(12)
        painter.setFont(font)
        painter.drawText(
            self.viewport().rect(),
            int(Qt.AlignmentFlag.AlignCenter),
            t("Drop an image here\nto open it"),
        )
        painter.end()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._file_drop_enabled and first_drop_path(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if self._file_drop_enabled and first_drop_path(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        path = first_drop_path(event) if self._file_drop_enabled else None
        if path is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self.path_dropped.emit(path)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if self._content_rect.isNull():
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.15 if delta > 0 else 1 / 1.15
        self._zoom *= factor
        self.scale(factor, factor)
        self._emit_view_changed()
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if (
            self._sample_mode
            and event.button() == Qt.MouseButton.LeftButton
            and not self._content_rect.isNull()
        ):
            scene_pos = self.mapToScene(event.position().toPoint())
            x = int(scene_pos.x())
            y = int(scene_pos.y())
            if self._content_rect.contains(scene_pos):
                self.pixel_clicked.emit(x, y)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            h = self.horizontalScrollBar()
            v = self.verticalScrollBar()
            h.setValue(h.value() - int(delta.x()))
            v.setValue(v.value() - int(delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)
