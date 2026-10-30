"""Pixel-aligned segmentation editor. Editing logic lives in segmentation/."""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vectorizer.gui.i18n import t, tf
from vectorizer.gui.preferences import current_preferences
from vectorizer.gui.qtutil import pil_to_qpixmap
from vectorizer.segmentation.history import DEFAULT_MAX_STEPS, SegmentationHistory
from vectorizer.segmentation.map import SegmentationMap
from vectorizer.segmentation.ops import (
    brush_stroke,
    find_problems,
    flood_fill,
    pick_color,
    remove_small_regions,
    separate_with_stroke,
    zap_fringes,
)


class SegTool(str, Enum):
    PICKER = "picker"
    BRUSH = "brush"
    FILL = "fill"
    RECOLOR = "recolor"
    ERASER = "eraser"  # transparent cut / separate
    JOIN = "join"  # brush with current color (connect)


class SegmentationEditor(QWidget):
    map_changed = Signal()
    retrace_requested = Signal()
    status_message = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._history: SegmentationHistory | None = None
        self._map: SegmentationMap | None = None
        self._pixmap: QPixmap | None = None
        self._checker: QPixmap | None = None
        self._tool = SegTool.BRUSH
        self._color = (0, 0, 0, 255)
        self._radius = 2
        self._stroke: list[tuple[int, int]] = []
        self._drawing = False
        self._zoom = 4.0
        self._pan = QPoint(0, 0)
        self._panning = False
        self._pan_start = QPoint()
        self._show_grid = True
        self._problems: list[tuple[int, int, str]] = []

        self.canvas = _SegCanvas(self)
        self.canvas.request_paint.connect(self._paint_canvas)
        self.canvas.pressed.connect(self._on_press)
        self.canvas.moved.connect(self._on_move)
        self.canvas.released.connect(self._on_release)
        self.canvas.wheel_zoom.connect(self._on_wheel)

        self.color_btn = QPushButton()
        self.color_btn.clicked.connect(self._pick_dialog_color)
        self.radius = QSpinBox()
        self.radius.setRange(0, 32)
        self.radius.setValue(self._radius)
        self.radius.valueChanged.connect(self._set_radius)
        self.small_spin = QSpinBox()
        self.small_spin.setRange(2, 5000)
        self.small_spin.setValue(16)
        self.remove_small_btn = QPushButton(self)
        self.remove_small_btn.hide()
        self.remove_small_btn.clicked.connect(self._remove_small)
        self.zap_btn = QPushButton(self)
        self.zap_btn.hide()
        self.zap_btn.clicked.connect(self._zap)
        self.find_btn = QPushButton(self)
        self.find_btn.hide()
        self.find_btn.clicked.connect(self._find_problems)
        self.undo_btn = QPushButton()
        self.redo_btn = QPushButton()
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn.clicked.connect(self.redo)
        self.retrace_btn = QPushButton()
        self.retrace_btn.setObjectName("primaryButton")
        self.retrace_btn.clicked.connect(self.retrace_requested.emit)
        self.rebuild_btn = QPushButton()
        self.fit_btn = QPushButton()
        self.fit_btn.clicked.connect(self.fit_view)

        tools_frame = QFrame()
        tools_frame.setObjectName("segTools")
        tools = QHBoxLayout(tools_frame)
        tools.setContentsMargins(8, 6, 8, 6)
        tools.setSpacing(4)
        self._tool_group = QButtonGroup(self)
        self._tool_buttons: dict[SegTool, QToolButton] = {}
        self._tool_label_keys = {
            SegTool.PICKER: "Pick",
            SegTool.BRUSH: "Brush",
            SegTool.FILL: "Fill",
            SegTool.RECOLOR: "Recolor",
            SegTool.JOIN: "Connect",
            SegTool.ERASER: "Separate",
        }
        for tool in self._tool_label_keys:
            btn = QToolButton()
            btn.setCheckable(True)
            btn.setAutoRaise(True)
            self._tool_group.addButton(btn)
            self._tool_buttons[tool] = btn
            tools.addWidget(btn)
            btn.clicked.connect(lambda checked=False, tool_id=tool: self._set_tool(tool_id))
        tools.addStretch(1)
        self._tool_buttons[SegTool.BRUSH].setChecked(True)

        self._cleanup_menu = QMenu(self)
        self._remove_small_act = self._cleanup_menu.addAction("")
        self._zap_act = self._cleanup_menu.addAction("")
        self._find_act = self._cleanup_menu.addAction("")
        self._remove_small_act.triggered.connect(self._remove_small)
        self._zap_act.triggered.connect(self._zap)
        self._find_act.triggered.connect(self._find_problems)
        self.cleanup_btn = QToolButton()
        self.cleanup_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.cleanup_btn.setMenu(self._cleanup_menu)

        bar = QHBoxLayout()
        bar.setContentsMargins(8, 4, 8, 4)
        bar.setSpacing(6)
        self._radius_label = QLabel()
        self._small_label = QLabel()
        bar.addWidget(self.color_btn)
        bar.addWidget(self._radius_label)
        bar.addWidget(self.radius)
        bar.addStretch(1)
        self.undo_btn.hide()
        self.redo_btn.hide()
        self.fit_btn.hide()
        bar.addWidget(self._small_label)
        bar.addWidget(self.small_spin)
        bar.addWidget(self.cleanup_btn)
        bar.addWidget(self.rebuild_btn)
        bar.addWidget(self.retrace_btn)

        self._hint = QLabel()
        self._hint.setWordWrap(True)
        self._hint.setObjectName("inlineHint")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(tools_frame)
        layout.addLayout(bar)
        hint_wrap = QHBoxLayout()
        hint_wrap.setContentsMargins(8, 0, 8, 6)
        hint_wrap.addWidget(self._hint)
        layout.addLayout(hint_wrap)
        layout.addWidget(self.canvas, 1)
        self.retranslate_ui()
        self._update_color_btn()
        self._update_history_buttons()

    def retranslate_ui(self) -> None:
        for tool, key in self._tool_label_keys.items():
            btn = self._tool_buttons[tool]
            btn.setText(t(key))
            btn.setToolTip(self._tool_tip(tool))
        self.remove_small_btn.setText(t("Remove small regions"))
        self._remove_small_act.setText(t("Remove small regions"))
        self.zap_btn.setText(t("Zap fringes"))
        self._zap_act.setText(t("Zap fringes"))
        zap_tip = t(
            "Merge thin anti-aliased leftovers into the neighboring region "
            "instead of deleting them."
        )
        self.zap_btn.setToolTip(zap_tip)
        self._zap_act.setToolTip(zap_tip)
        self.find_btn.setText(t("Find problems"))
        self._find_act.setText(t("Find problems"))
        find_tip = t("Mark one-pixel gaps and pinched strokes so you can paint them closed.")
        self.find_btn.setToolTip(find_tip)
        self._find_act.setToolTip(find_tip)
        self.cleanup_btn.setText(t("Clean up"))
        self.undo_btn.setText(t("Undo"))
        self.redo_btn.setText(t("Redo"))
        self.retrace_btn.setText(t("Retrace"))
        self.retrace_btn.setToolTip(t("Retrace the segmentation (F6)"))
        self.rebuild_btn.setText(t("Rebuild…"))
        self.rebuild_btn.setToolTip(
            t(
                "Rebuild the segmentation from the original image. "
                "Edits that are not retraced are discarded."
            )
        )
        self.fit_btn.setText(t("Fit"))
        self._radius_label.setText(t("Radius"))
        self._small_label.setText(t("Smaller than"))
        self.small_spin.setToolTip(
            t(
                "Regions smaller than this many pixels are removed by "
                "Clean up → Remove small regions."
            )
        )
        self._hint.setText(
            t(
                "Segmentation is a separate raster from the original. "
                "Edits affect the next Retrace. Middle-drag pans; wheel zooms."
            )
        )
        self._update_color_btn()

    @staticmethod
    def _tool_tip(tool: SegTool) -> str:
        return t(
            {
                SegTool.PICKER: "Sample a region color.",
                SegTool.BRUSH: "Paint with the current color.",
                SegTool.FILL: "Flood-fill a contiguous region.",
                SegTool.RECOLOR: "Recolor the clicked region.",
                SegTool.JOIN: "Paint a bridge to connect separated regions of the current color.",
                SegTool.ERASER: "Paint transparency to separate accidentally connected regions.",
            }[tool]
        )

    def set_map(self, map_: SegmentationMap, *, reset_history: bool = True) -> None:
        self._map = map_.copy()
        self._pixmap = None
        if reset_history or self._history is None:
            prefs = current_preferences()
            self._history = SegmentationHistory(
                self._map,
                max_bytes=max(
                    1_000_000,
                    int(prefs.segmentation_history_mib) * 1024 * 1024,
                ),
                max_steps=int(prefs.segmentation_history_steps or DEFAULT_MAX_STEPS),
            )
        self._update_history_buttons()
        self._update_color_btn()
        self.fit_view()
        self.canvas.update()
        self.map_changed.emit()

    def clear_map(self) -> None:
        """Drop the working map (e.g. while auto-vectorize rebuilds it)."""
        self._map = None
        self._pixmap = None
        self._history = None
        self._update_history_buttons()
        self.canvas.update()
        self.map_changed.emit()

    def current_map(self) -> SegmentationMap | None:
        return None if self._map is None else self._map.copy()

    def has_map(self) -> bool:
        return self._map is not None

    @property
    def can_undo(self) -> bool:
        return bool(self._history and self._history.can_undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._history and self._history.can_redo)

    def undo(self) -> None:
        if self._history is None:
            return
        restored = self._history.undo()
        if restored is None:
            return
        self._map = restored
        self._pixmap = None
        self._update_history_buttons()
        self.canvas.update()
        self.map_changed.emit()
        self.status_message.emit(
            tf(
                "Undo ({depth} steps, {kib} KiB)",
                depth=self._history.depth,
                kib=self._history.memory_bytes // 1024,
            )
        )

    def redo(self) -> None:
        if self._history is None:
            return
        restored = self._history.redo()
        if restored is None:
            return
        self._map = restored
        self._pixmap = None
        self._update_history_buttons()
        self.canvas.update()
        self.map_changed.emit()

    def _commit(self, new_map: SegmentationMap) -> None:
        self._map = new_map
        self._pixmap = None
        if self._history is not None:
            self._history.commit(new_map)
        self._update_history_buttons()
        self.canvas.update()
        self.map_changed.emit()

    def _set_tool(self, tool: SegTool) -> None:
        self._tool = tool
        self._tool_buttons[tool].setChecked(True)

    def _set_radius(self, value: int) -> None:
        self._radius = int(value)

    def _pick_dialog_color(self) -> None:
        color = QColorDialog.getColor(QColor(*self._color[:3]), self, t("Brush color"))
        if color.isValid():
            self._color = (color.red(), color.green(), color.blue(), 255)
            self._update_color_btn()

    def _update_color_btn(self) -> None:
        r, g, b, a = self._color
        self.color_btn.setStyleSheet(
            f"QPushButton {{ background: rgba({r},{g},{b},{a}); "
            f"color: {'#000' if (r + g + b) / 3 > 140 else '#fff'}; }}"
        )
        self.color_btn.setText(f"#{r:02x}{g:02x}{b:02x}" if a else t("Transparent"))

    def _update_history_buttons(self) -> None:
        can_undo = bool(self._history and self._history.can_undo)
        can_redo = bool(self._history and self._history.can_redo)
        self.undo_btn.setEnabled(can_undo)
        self.redo_btn.setEnabled(can_redo)

    def _remove_small(self) -> None:
        if self._map is None:
            return
        self._problems = []
        self._commit(remove_small_regions(self._map, self.small_spin.value()))

    def _zap(self) -> None:
        if self._map is None:
            return
        updated = zap_fringes(self._map, max_pixels=max(8, self.small_spin.value()))
        self._problems = []
        self._commit(updated)
        self.status_message.emit(t("Fringe regions merged into their neighbors."))

    def _find_problems(self) -> None:
        if self._map is None:
            return
        self._problems = find_problems(self._map)
        self.canvas.update()
        self.status_message.emit(
            t("No pinched gaps found.")
            if not self._problems
            else t("Problem spots are marked. Paint across a pinch or gap, then retrace.")
        )
        self.status_message.emit(t("Removed small regions from the segmentation."))

    def fit_view(self) -> None:
        if self._map is None:
            return
        w, h = self._map.size
        if w <= 0 or h <= 0:
            return
        cw = max(self.canvas.width(), 1)
        ch = max(self.canvas.height(), 1)
        self._zoom = max(1.0, min(cw / w, ch / h) * 0.95)
        self._pan = QPoint(0, 0)
        self.canvas.update()

    def _image_pos(self, pos: QPoint) -> tuple[int, int] | None:
        if self._map is None:
            return None
        x = int((pos.x() - self._pan.x()) / self._zoom)
        y = int((pos.y() - self._pan.y()) / self._zoom)
        w, h = self._map.size
        if 0 <= x < w and 0 <= y < h:
            return x, y
        return None

    def _on_press(self, pos: QPoint, button: Qt.MouseButton) -> None:
        if self._map is None:
            return
        if button == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = pos
            return
        if button != Qt.MouseButton.LeftButton:
            return
        pixel = self._image_pos(pos)
        if pixel is None:
            return
        x, y = pixel
        if self._tool == SegTool.PICKER:
            self._color = pick_color(self._map, x, y)
            self._update_color_btn()
            self.status_message.emit(tf("Picked {color}", color=self.color_btn.text()))
            return
        if self._tool in {SegTool.FILL, SegTool.RECOLOR}:
            self._commit(flood_fill(self._map, x, y, self._color))
            return
        self._drawing = True
        self._stroke = [pixel]

    def _on_move(self, pos: QPoint) -> None:
        if self._panning:
            delta = pos - self._pan_start
            self._pan_start = pos
            self._pan += delta
            self.canvas.update()
            return
        if not self._drawing or self._map is None:
            return
        pixel = self._image_pos(pos)
        if pixel is None:
            return
        if not self._stroke or self._stroke[-1] != pixel:
            self._stroke.append(pixel)
            self.canvas.update()

    def _on_release(self, pos: QPoint, button: Qt.MouseButton) -> None:
        if button == Qt.MouseButton.MiddleButton:
            self._panning = False
            return
        if not self._drawing or self._map is None:
            self._drawing = False
            self._stroke = []
            return
        self._drawing = False
        points = list(self._stroke)
        self._stroke = []
        if not points:
            return
        if self._tool == SegTool.ERASER:
            self._commit(separate_with_stroke(self._map, points, radius=self._radius))
        else:
            # BRUSH and JOIN both paint the current color.
            self._commit(brush_stroke(self._map, points, self._color, radius=self._radius))

    def _on_wheel(self, delta: int, pos: QPoint) -> None:
        if self._map is None or delta == 0:
            return
        old = self._zoom
        factor = 1.15 if delta > 0 else 1 / 1.15
        self._zoom = max(0.25, min(64.0, self._zoom * factor))
        # Zoom toward cursor.
        self._pan = QPoint(
            int(pos.x() - (pos.x() - self._pan.x()) * (self._zoom / old)),
            int(pos.y() - (pos.y() - self._pan.y()) * (self._zoom / old)),
        )
        self.canvas.update()

    def _ensure_checker(self) -> QPixmap:
        if self._checker is not None:
            return self._checker
        tile = QPixmap(32, 32)
        tile.fill(QColor("#ffffff"))
        painter = QPainter(tile)
        painter.fillRect(0, 0, 16, 16, QColor("#cdcdcd"))
        painter.fillRect(16, 16, 16, 16, QColor("#cdcdcd"))
        painter.end()
        self._checker = tile
        return tile

    def _paint_canvas(self, painter: QPainter, size) -> None:
        painter.fillRect(0, 0, size.width(), size.height(), QColor("#dedee1"))
        if self._map is None:
            painter.setPen(QColor("#6f6f6f"))
            painter.drawText(
                QRect(24, 24, max(size.width() - 48, 1), max(size.height() - 48, 1)),
                int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                t("No segmentation yet. Open an image and vectorize, or rebuild."),
            )
            return
        if self._pixmap is None:
            self._pixmap = pil_to_qpixmap(self._map.image)
        pixmap = self._pixmap
        target_w = int(self._map.size[0] * self._zoom)
        target_h = int(self._map.size[1] * self._zoom)
        # Tiled checkerboard behind transparency (O(1) vs per-tile fillRect loop).
        painter.drawTiledPixmap(
            self._pan.x(),
            self._pan.y(),
            target_w,
            target_h,
            self._ensure_checker(),
        )
        painter.drawPixmap(
            self._pan.x(),
            self._pan.y(),
            target_w,
            target_h,
            pixmap,
        )
        if self._show_grid and self._zoom >= 8:
            painter.setPen(QPen(QColor(0, 0, 0, 40)))
            w, h = self._map.size
            for x in range(w + 1):
                px = self._pan.x() + int(x * self._zoom)
                painter.drawLine(px, self._pan.y(), px, self._pan.y() + target_h)
            for y in range(h + 1):
                py = self._pan.y() + int(y * self._zoom)
                painter.drawLine(self._pan.x(), py, self._pan.x() + target_w, py)
        if self._stroke and self._drawing:
            painter.setPen(QPen(QColor(31, 158, 222), max(1, int(self._zoom / 2))))
            pts = [
                QPoint(
                    self._pan.x() + int(x * self._zoom + self._zoom / 2),
                    self._pan.y() + int(y * self._zoom + self._zoom / 2),
                )
                for x, y in self._stroke
            ]
            for a, b in zip(pts, pts[1:]):
                painter.drawLine(a, b)
        if self._problems:
            painter.setPen(QPen(QColor(252, 65, 56), 2))
            painter.setBrush(QColor(252, 65, 56, 180))
            radius = max(3, int(self._zoom * 0.45))
            for x, y, _kind in self._problems:
                cx = self._pan.x() + int((x + 0.5) * self._zoom)
                cy = self._pan.y() + int((y + 0.5) * self._zoom)
                painter.drawEllipse(QPoint(cx, cy), radius, radius)


class _SegCanvas(QWidget):
    request_paint = Signal(object, object)
    pressed = Signal(QPoint, Qt.MouseButton)
    moved = Signal(QPoint)
    released = Signal(QPoint, Qt.MouseButton)
    wheel_zoom = Signal(int, QPoint)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(280)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        self.request_paint.emit(painter, self.size())
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.pressed.emit(event.position().toPoint(), event.button())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.moved.emit(event.position().toPoint())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.released.emit(event.position().toPoint(), event.button())

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        self.wheel_zoom.emit(event.angleDelta().y(), event.position().toPoint())
        event.accept()
