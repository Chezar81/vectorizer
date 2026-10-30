"""Synchronized side-by-side and split-slider comparison."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from vectorizer.gui.canvas import ImageCanvas
from vectorizer.gui.i18n import t


class SyncSideBySide(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.left = ImageCanvas()
        self.right = ImageCanvas()
        self._syncing = False
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        left_col = QVBoxLayout()
        right_col = QVBoxLayout()
        self._left_label = QLabel()
        self._right_label = QLabel()
        self._left_label.setObjectName("previewCaption")
        self._right_label.setObjectName("previewCaption")
        left_col.addWidget(self._left_label)
        left_col.addWidget(self.left, 1)
        right_col.addWidget(self._right_label)
        right_col.addWidget(self.right, 1)
        row.addLayout(left_col, 1)
        row.addLayout(right_col, 1)
        self.left.view_changed.connect(lambda: self._mirror(self.left, self.right))
        self.right.view_changed.connect(lambda: self._mirror(self.right, self.left))
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self._left_label.setText(t("Original"))
        self._right_label.setText(t("Vector"))

    def _mirror(self, source: ImageCanvas, target: ImageCanvas) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            transform, h, v = source.view_state()
            target.apply_view(transform, h, v)
        finally:
            self._syncing = False


class SplitCompare(QWidget):
    """Shows original and vector stacked with a horizontal wipe slider."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._original: QPixmap | None = None
        self._vector: QPixmap | None = None
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(50)
        self.preview = _WipeLabel()
        self._wipe_left = QLabel()
        self._wipe_right = QLabel()
        self._wipe_left.setObjectName("previewCaption")
        self._wipe_right.setObjectName("previewCaption")
        slider_row = QHBoxLayout()
        slider_row.setContentsMargins(12, 0, 12, 8)
        slider_row.setSpacing(8)
        slider_row.addWidget(self._wipe_left)
        slider_row.addWidget(self.slider, 1)
        slider_row.addWidget(self._wipe_right)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.preview, 1)
        layout.addLayout(slider_row)
        self.slider.valueChanged.connect(self._refresh)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self._wipe_left.setText(t("Original"))
        self._wipe_right.setText(t("Vector"))
        self.slider.setToolTip(
            t("Drag to wipe between original (left) and vector (right).")
        )

    def set_images(self, original: QPixmap | None, vector: QPixmap | None) -> None:
        self._original = original
        self._vector = vector
        self._refresh()

    def _refresh(self) -> None:
        self.preview.set_wipe(self._original, self._vector, self.slider.value() / 100.0)


class _WipeLabel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._original: QPixmap | None = None
        self._vector: QPixmap | None = None
        self._ratio = 0.5
        self.setMinimumHeight(200)

    def set_wipe(self, original: QPixmap | None, vector: QPixmap | None, ratio: float) -> None:
        self._original = original
        self._vector = vector
        self._ratio = max(0.0, min(1.0, ratio))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.white)
        target = self._vector or self._original
        if target is None or target.isNull():
            painter.end()
            return
        scaled = target.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        if self._vector is not None and not self._vector.isNull():
            vec = self._vector.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(x, y, vec)
        if self._original is not None and not self._original.isNull():
            orig = self._original.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            clip_w = int(orig.width() * self._ratio)
            painter.drawPixmap(x, y, orig, 0, 0, clip_w, orig.height())
            pen = QPen(QColor("#1f9ede"))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawLine(x + clip_w, y, x + clip_w, y + orig.height())
        painter.end()
