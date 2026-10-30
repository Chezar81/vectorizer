"""Settings sidebar. Background and color controls stay visible in every mode."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from vectorizer.domain.settings import (
    AutomaticQuality,
    ColorMode,
    DxfCurveMode,
    EdgeTreatment,
    HierarchyMode,
    PathFitMode,
    SvgPaintStyle,
    TraceSettings,
    WorkflowMode,
    normalize_hex,
)
from vectorizer.gui.i18n import t, tf
from vectorizer.gui.preferences import update_preferences
from vectorizer.gui.slider_spin import DoubleSliderSpin, IntSliderSpin
from vectorizer.presets import (
    PresetError,
    delete_preset,
    duplicate_preset,
    list_presets,
    load_preset,
    save_preset,
)


def _add_slider_row(form: QFormLayout, title_key: str, widget: QWidget) -> QLabel:
    """Full-width label above slider+value so the track has room in the sidebar."""
    wrap = QWidget()
    col = QVBoxLayout(wrap)
    col.setContentsMargins(0, 2, 0, 4)
    col.setSpacing(2)
    label = QLabel(t(title_key))
    label.setProperty("i18n_key", title_key)
    col.addWidget(label)
    col.addWidget(widget)
    form.addRow(wrap)
    return label


class SettingsPanel(QWidget):
    vectorize_requested = Signal()
    cancel_requested = Signal()
    settings_changed = Signal()
    palette_recolor_requested = Signal(dict)  # old_hex -> new_hex
    pick_background_requested = Signal()  # enter click-to-pick on Original tab
    pick_trace_color_requested = Signal()
    automatic_quality_changed = Signal()  # re-apply Automatic suggestions

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("sidePanel")
        self._updating = False
        self._ready = False
        self._palette_colors: list[str] = []
        self._trace_palette: list[str] = []
        self._palette_suggestions: dict[int, tuple[str, ...]] = {}
        self._notes_en = ""

        self.workflow = QComboBox()
        self.auto_quality = QComboBox()
        self.colormode = QComboBox()
        self.hierarchy = QComboBox()
        self.path_mode = QComboBox()

        self.filter_speckle = IntSliderSpin(0, 64)
        self.color_precision = IntSliderSpin(1, 8)
        self.layer_difference = IntSliderSpin(0, 128)
        self.corner_threshold = IntSliderSpin(0, 180)
        self.length_threshold = DoubleSliderSpin(3.5, 10.0, step=0.1, decimals=2)
        self.max_iterations = IntSliderSpin(1, 64)
        self.splice_threshold = IntSliderSpin(0, 180)
        self.path_precision = IntSliderSpin(0, 12)

        # --- Always-visible background controls ---
        self.preserve_transparency = QCheckBox()
        self.remove_background = QCheckBox()
        self.bg_tolerance = IntSliderSpin(0, 255)
        self.bg_color_btn = QPushButton()
        self.bg_pick_btn = QPushButton()
        self._bg_color = QColor(255, 255, 255)

        # --- Always-visible color count ---
        self.target_colors = IntSliderSpin(0, 256)
        self.smooth_noise = QCheckBox()
        self.edge_treatment = QComboBox()
        self.palette_choice = QComboBox()
        self.trace_palette_list = QListWidget()
        self.trace_palette_list.setObjectName("paletteList")
        self.trace_palette_list.setMaximumHeight(120)
        self.trace_add_btn = QPushButton()
        self.trace_remove_btn = QPushButton()
        self.svg_style = QComboBox()
        self.dxf_mode = QComboBox()

        self.palette_list = QListWidget()
        self.palette_list.setObjectName("paletteList")
        self.palette_list.setMaximumHeight(160)
        self.palette_list.setSpacing(4)
        self.palette_list.setUniformItemSizes(True)
        self.recolor_btn = QPushButton()

        self.preset_combo = QComboBox()
        self.preset_save = QPushButton()
        self.preset_load = QPushButton()
        self.preset_delete = QPushButton(self)
        self.preset_dup = QPushButton(self)
        self.preset_delete.hide()
        self.preset_dup.hide()

        self.notes = QLabel()
        self.notes.setWordWrap(True)
        self.notes.setObjectName("analysisNotes")
        self.notes.setVisible(False)

        self.vectorize_btn = QPushButton()
        self.vectorize_btn.setObjectName("primaryButton")
        self.vectorize_btn.setDefault(True)
        self.cancel_btn = QPushButton()
        self.cancel_btn.setEnabled(False)

        # Background group — always visible
        background = QGroupBox()
        bg_form = QFormLayout(background)
        bg_form.addRow(self.preserve_transparency)
        bg_form.addRow(self.remove_background)
        bg_color_row = QHBoxLayout()
        bg_color_row.addWidget(self.bg_color_btn, 1)
        bg_color_row.addWidget(self.bg_pick_btn)
        self._bg_color_label = QLabel()
        bg_form.addRow(self._bg_color_label, bg_color_row)
        self._bg_tolerance_label = _add_slider_row(bg_form, "Color tolerance", self.bg_tolerance)
        self._bg_hint = QLabel()
        self._bg_hint.setWordWrap(True)
        self._bg_hint.setObjectName("inlineHint")
        bg_form.addRow(self._bg_hint)
        self._preprocess_box = background

        # Colors group — always visible
        colors = QGroupBox()
        colors_form = QFormLayout(colors)
        self._image_type_label = QLabel()
        colors_form.addRow(self._image_type_label, self.colormode)
        self._target_colors_label = _add_slider_row(
            colors_form, "Target color count", self.target_colors
        )
        colors_form.addRow(self.smooth_noise)
        self._edge_label = QLabel()
        colors_form.addRow(self._edge_label, self.edge_treatment)
        self._palette_choice_label = QLabel()
        colors_form.addRow(self._palette_choice_label, self.palette_choice)
        self._trace_palette_caption = QLabel()
        self._trace_editor = QWidget()
        self._trace_editor.setObjectName("optionBlock")
        trace_layout = QVBoxLayout(self._trace_editor)
        trace_layout.setContentsMargins(0, 0, 0, 0)
        trace_layout.setSpacing(4)
        trace_layout.addWidget(self._trace_palette_caption)
        trace_layout.addWidget(self.trace_palette_list)
        trace_btns = QHBoxLayout()
        trace_btns.addWidget(self.trace_add_btn)
        trace_btns.addWidget(self.trace_remove_btn)
        trace_layout.addLayout(trace_btns)
        colors_form.addRow(self._trace_editor)
        self._palette_caption = QLabel()
        self._result_palette = QWidget()
        self._result_palette.setObjectName("optionBlock")
        result_layout = QVBoxLayout(self._result_palette)
        result_layout.setContentsMargins(0, 4, 0, 0)
        result_layout.setSpacing(4)
        result_layout.addWidget(self._palette_caption)
        result_layout.addWidget(self.palette_list)
        result_layout.addWidget(self.recolor_btn)
        colors_form.addRow(self._result_palette)
        self._colors_box = colors

        output = QGroupBox()
        output_form = QFormLayout(output)
        self._svg_style_label = QLabel()
        output_form.addRow(self._svg_style_label, self.svg_style)
        self._dxf_mode_label = QLabel()
        output_form.addRow(self._dxf_mode_label, self.dxf_mode)
        self._output_box = output

        basic = QGroupBox()
        basic_form = QFormLayout(basic)
        self._path_fitting_label = QLabel()
        basic_form.addRow(self._path_fitting_label, self.path_mode)
        self._noise_label = _add_slider_row(basic_form, "Noise removal (px)", self.filter_speckle)
        self._layering_label = QLabel()
        basic_form.addRow(self._layering_label, self.hierarchy)
        self._basic_box = basic

        advanced = QGroupBox()
        adv_form = QFormLayout(advanced)
        self._color_precision_label = _add_slider_row(
            adv_form, "Color precision (bits)", self.color_precision
        )
        self._layer_diff_label = _add_slider_row(adv_form, "Layer difference", self.layer_difference)
        self._corner_label = _add_slider_row(adv_form, "Corner threshold (°)", self.corner_threshold)
        self._length_label = _add_slider_row(adv_form, "Length threshold (px)", self.length_threshold)
        self._max_iter_label = _add_slider_row(adv_form, "Max iterations", self.max_iterations)
        self._splice_label = _add_slider_row(adv_form, "Splice threshold (°)", self.splice_threshold)
        self._path_precision_label = _add_slider_row(adv_form, "Path precision", self.path_precision)
        self._advanced_box = advanced

        self._preset_menu = QMenu(self)
        self._preset_dup_act = self._preset_menu.addAction("")
        self._preset_delete_act = self._preset_menu.addAction("")
        self._preset_dup_act.triggered.connect(self._duplicate_preset)
        self._preset_delete_act.triggered.connect(self._delete_preset)
        self.preset_more = QToolButton()
        self.preset_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.preset_more.setMenu(self._preset_menu)
        self.preset_more.setText("⋯")

        presets = QGroupBox()
        preset_row = QHBoxLayout()
        preset_row.addWidget(self.preset_combo, 1)
        preset_row.addWidget(self.preset_load)
        preset_row.addWidget(self.preset_save)
        preset_row.addWidget(self.preset_more)
        preset_layout = QVBoxLayout(presets)
        preset_layout.addLayout(preset_row)
        self._presets_box = presets

        top = QFormLayout()
        self._mode_label = QLabel()
        top.addRow(self._mode_label, self.workflow)
        self._auto_quality_label = QLabel()
        top.addRow(self._auto_quality_label, self.auto_quality)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addLayout(top)
        layout.addWidget(self.notes)
        layout.addWidget(background)
        layout.addWidget(colors)
        layout.addWidget(output)
        layout.addWidget(basic)
        layout.addWidget(advanced)
        layout.addWidget(presets)
        layout.addStretch(1)
        self.retranslate_ui()

        self._scroll_inner = inner
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(inner)
        self.vectorize_btn.setMinimumHeight(36)
        self.cancel_btn.setMinimumHeight(36)
        self.cancel_btn.setVisible(False)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(10, 10, 10, 10)
        action_row.setSpacing(8)
        action_row.addWidget(self.vectorize_btn, 1)
        action_row.addWidget(self.cancel_btn)
        self._action_bar = QFrame()
        self._action_bar.setObjectName("actionBar")
        self._action_bar.setLayout(action_row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll, 1)
        outer.addWidget(self._action_bar)

        self.workflow.currentIndexChanged.connect(self._on_workflow_changed)
        self.auto_quality.currentIndexChanged.connect(self._on_auto_quality_changed)
        for widget in (
            self.colormode,
            self.hierarchy,
            self.path_mode,
            self.filter_speckle,
            self.color_precision,
            self.layer_difference,
            self.corner_threshold,
            self.length_threshold,
            self.max_iterations,
            self.splice_threshold,
            self.path_precision,
            self.bg_tolerance,
            self.target_colors,
            self.edge_treatment,
            self.palette_choice,
            self.svg_style,
            self.dxf_mode,
        ):
            if hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(self._emit_changed)
            else:
                widget.currentIndexChanged.connect(self._emit_changed)
        self.preserve_transparency.toggled.connect(self._emit_changed)
        self.smooth_noise.toggled.connect(self._emit_changed)
        self.remove_background.toggled.connect(self._on_remove_bg_toggled)
        self.bg_color_btn.clicked.connect(self._pick_bg_color)
        self.bg_pick_btn.clicked.connect(self.pick_background_requested.emit)
        self.trace_add_btn.clicked.connect(self.pick_trace_color_requested.emit)
        self.trace_remove_btn.clicked.connect(self._remove_trace_color)
        self.palette_choice.currentIndexChanged.connect(self._apply_palette_choice)
        self.vectorize_btn.clicked.connect(self.vectorize_requested.emit)
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)
        self.recolor_btn.clicked.connect(self._recolor_selected)
        self.preset_save.clicked.connect(self._save_preset)
        self.preset_load.clicked.connect(self._load_preset)
        self.preset_delete.clicked.connect(self._delete_preset)
        self.preset_dup.clicked.connect(self._duplicate_preset)

        self.set_settings(TraceSettings())
        self.refresh_presets()
        self._on_workflow_changed()
        self._update_bg_button()
        self._on_remove_bg_toggled(self.remove_background.isChecked())
        self.set_ready(False)

    def preferred_content_height(self) -> int:
        """Full sidebar content height (no scrollbar), for default window sizing."""
        self._scroll_inner.ensurePolished()
        self._scroll_inner.adjustSize()
        hint = self._scroll_inner.sizeHint()
        minimum = self._scroll_inner.minimumSizeHint()
        bar = self._action_bar.sizeHint().height()
        return max(hint.height(), minimum.height(), 1) + max(bar, 0)

    def retranslate_ui(self) -> None:
        """Apply the active language to all sidebar labels and controls."""
        self._updating = True
        try:
            self._refill_combo(
                self.workflow,
                (
                    ("Automatic", WorkflowMode.AUTOMATIC),
                    ("Basic", WorkflowMode.BASIC),
                    ("Advanced", WorkflowMode.ADVANCED),
                ),
            )
            self.workflow.setToolTip(
                t(
                    "Automatic classifies the image (logo, line art, photo, …) and "
                    "chooses tracing plus preprocess defaults. Background and color "
                    "controls below always apply — switch to Basic for path-fitting options."
                )
            )
            self._refill_combo(
                self.auto_quality,
                (
                    ("Fast", AutomaticQuality.FAST),
                    ("Balanced", AutomaticQuality.BALANCED),
                    ("High detail", AutomaticQuality.HIGH),
                ),
            )
            self.auto_quality.setToolTip(
                t(
                    "Fast: quicker, fewer paths. Balanced: default. "
                    "High detail: finer colors and more path detail."
                )
            )
            self._refill_combo(
                self.colormode,
                (
                    ("Color", ColorMode.COLOR),
                    ("Black and white", ColorMode.BINARY),
                ),
            )
            self._refill_combo(
                self.hierarchy,
                (
                    ("Stacked layers", HierarchyMode.STACKED),
                    ("Cutout mosaic", HierarchyMode.CUTOUT),
                ),
            )
            self._refill_combo(
                self.path_mode,
                (
                    ("Spline curves", PathFitMode.SPLINE),
                    ("Polygons", PathFitMode.POLYGON),
                    ("Pixel-aligned", PathFitMode.PIXEL),
                ),
            )
            self._refill_combo(
                self.edge_treatment,
                (
                    ("Automatic edges", EdgeTreatment.AUTO),
                    ("Artwork with blending", EdgeTreatment.BLENDED),
                    ("Artwork without blending", EdgeTreatment.HARD),
                    ("Photograph", EdgeTreatment.PHOTO),
                ),
            )
            self.edge_treatment.setToolTip(
                t(
                    "Blending uses anti-aliased pixels to place the curve inside the pixel. "
                    "Without blending, shapes snap to flat colors. Photographs are posterized."
                )
            )
            self._refill_combo(
                self.palette_choice,
                (
                    ("Unlimited", 0),
                    ("2 colors", 2),
                    ("4 colors", 4),
                    ("8 colors", 8),
                    ("12 colors", 12),
                    ("Best guess", -1),
                    ("Custom", -2),
                ),
            )
            self._refill_combo(
                self.svg_style,
                (
                    ("Fill only", SvgPaintStyle.FILL),
                    ("Stroke and fill", SvgPaintStyle.STROKE_FILL),
                ),
            )
            self.svg_style.setToolTip(
                t(
                    "Fill only is the simpler file. Stroke and fill paints a hairline of the "
                    "same color so viewers do not show thin gaps between shapes."
                )
            )
            self._refill_combo(
                self.dxf_mode,
                (
                    ("DXF lines", DxfCurveMode.LINES),
                    ("DXF splines", DxfCurveMode.SPLINES),
                ),
            )
            self.dxf_mode.setToolTip(
                t(
                    "Lines samples curves into polylines. Splines keep cubic curves. "
                    "Neither mode writes fills."
                )
            )

            self.preserve_transparency.setText(t("Keep existing transparency"))
            self.remove_background.setText(t("Remove background"))
            self.remove_background.setToolTip(
                t(
                    "Make pixels near the selected background color transparent before tracing "
                    "(similar to a background knockout)."
                )
            )
            self.bg_tolerance.setToolTip(
                t("How close a pixel may be to the background color (0 = exact).")
            )
            self.bg_pick_btn.setText(t("Pick from image"))
            self.bg_pick_btn.setToolTip(
                t(
                    "Click a pixel on the Original tab to set the background color, then Vectorize."
                )
            )
            self.target_colors.setSpecialValueText(t("Auto (off)"))
            self.target_colors.setToolTip(
                t(
                    "Limit the number of colors before tracing (quantize). "
                    "Use 8–32 for logos. 0 leaves colors to the tracer."
                )
            )
            self.smooth_noise.setText(t("Smooth noise before tracing"))
            self.smooth_noise.setToolTip(
                t(
                    "Apply a light median filter to RGB before tracing. "
                    "Helps JPEG artifacts and photographic noise; keep off for crisp logos."
                )
            )
            self.recolor_btn.setText(t("Recolor selected fill…"))
            self.recolor_btn.setToolTip(
                t("Change a fill color in the current SVG without retracing geometry.")
            )
            self.preset_save.setText(t("Save"))
            self.preset_load.setText(t("Load"))
            self.preset_delete.setText(t("Delete"))
            self.preset_dup.setText(t("Duplicate"))
            self._preset_dup_act.setText(t("Duplicate"))
            self._preset_delete_act.setText(t("Delete"))
            self.preset_more.setToolTip(t("More preset actions"))
            self.vectorize_btn.setToolTip(t("Trace the open image (F5)"))
            self.notes.setToolTip(t("Hints from Automatic analysis of the opened image."))
            self.vectorize_btn.setText(t("Vectorize"))
            self.cancel_btn.setText(t("Cancel"))

            self._preprocess_box.setTitle(t("Background"))
            self._bg_color_label.setText(t("Background color"))
            self._bg_tolerance_label.setText(t("Color tolerance"))
            self._bg_hint.setText(
                t("Tip: enable Remove background, pick a color, then Vectorize.")
            )
            self._colors_box.setTitle(t("Colors"))
            self._output_box.setTitle(t("Output"))
            self._image_type_label.setText(t("Image type"))
            self._edge_label.setText(t("Edges"))
            self._palette_choice_label.setText(t("Trace palette"))
            self._trace_palette_caption.setText(t("Colors the trace must use:"))
            self.trace_add_btn.setText(t("Add from image"))
            self.trace_add_btn.setToolTip(
                t("Click a pixel on the Original image to add that color to the trace palette.")
            )
            self.trace_remove_btn.setText(t("Remove color"))
            self._svg_style_label.setText(t("SVG paint"))
            self._dxf_mode_label.setText(t("DXF curves"))
            self._target_colors_label.setText(t("Target color count"))
            self._palette_caption.setText(t("Result palette (after vectorize):"))
            self._basic_box.setTitle(t("Tracing (Basic)"))
            self._path_fitting_label.setText(t("Path fitting"))
            self._noise_label.setText(t("Noise removal (px)"))
            self._layering_label.setText(t("Layering"))
            self._advanced_box.setTitle(t("Advanced (VTracer)"))
            self._color_precision_label.setText(t("Color precision (bits)"))
            self._layer_diff_label.setText(t("Layer difference"))
            self._corner_label.setText(t("Corner threshold (°)"))
            self._length_label.setText(t("Length threshold (px)"))
            self._max_iter_label.setText(t("Max iterations"))
            self._splice_label.setText(t("Splice threshold (°)"))
            self._path_precision_label.setText(t("Path precision"))
            self._presets_box.setTitle(t("Presets"))
            self._mode_label.setText(t("Mode"))
            self._auto_quality_label.setText(t("Quality"))

            self.color_precision.setToolTip(
                t(
                    "Fewer bits merge similar colors (faster, simpler). "
                    "More bits keep more hues (more paths)."
                )
            )
            self.filter_speckle.setToolTip(
                t(
                    "Drop regions smaller than this many pixels. "
                    "Higher values clean noise and remove tiny paths."
                )
            )
            self.path_mode.setToolTip(
                t(
                    "Spline: smooth logos. Polygon: harder corners. "
                    "Pixel-aligned: pixel art, more nodes."
                )
            )
            self.hierarchy.setToolTip(
                t(
                    "Stacked: overlapping shapes, compact files. "
                    "Cutout: non-overlapping mosaic, often more paths."
                )
            )
            self.preserve_transparency.setToolTip(
                t(
                    "Keep existing alpha. If unchecked, alpha is composited onto the background color."
                )
            )
            self._apply_notes_text()
            self._update_bg_button()
        finally:
            self._updating = False

    @staticmethod
    def _refill_combo(combo: QComboBox, items: tuple[tuple[str, object], ...]) -> None:
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for key, data in items:
            combo.addItem(t(key), data)
        SettingsPanel._set_combo(combo, current)
        combo.blockSignals(False)

    def _emit_changed(self, *_args) -> None:
        if not self._updating:
            self.settings_changed.emit()

    def _on_remove_bg_toggled(self, checked: bool) -> None:
        self.bg_tolerance.setEnabled(checked)
        self.bg_color_btn.setEnabled(checked)
        self.bg_pick_btn.setEnabled(checked)
        self._emit_changed()

    def _on_auto_quality_changed(self) -> None:
        if self._updating:
            return
        self._emit_changed()
        if self.workflow.currentData() == WorkflowMode.AUTOMATIC:
            self.automatic_quality_changed.emit()

    def _on_workflow_changed(self) -> None:
        mode = self.workflow.currentData()
        # Background + Colors stay visible in every mode.
        self._preprocess_box.setVisible(True)
        self._colors_box.setVisible(True)
        self._basic_box.setVisible(mode in {WorkflowMode.BASIC, WorkflowMode.ADVANCED})
        self._advanced_box.setVisible(mode == WorkflowMode.ADVANCED)
        auto = mode == WorkflowMode.AUTOMATIC
        self.auto_quality.setVisible(auto)
        self._auto_quality_label.setVisible(auto)
        self._emit_changed()
        if not self._updating and auto:
            self.automatic_quality_changed.emit()

    def set_ready(self, ready: bool) -> None:
        """Enable Vectorize only after an image is open and no job is running."""
        self._ready = bool(ready)
        busy = self.cancel_btn.isVisible()
        self.vectorize_btn.setEnabled(self._ready and not busy)

    def set_busy(self, busy: bool) -> None:
        self.cancel_btn.setVisible(busy)
        self.vectorize_btn.setEnabled(self._ready and not busy)
        self.cancel_btn.setEnabled(busy)
        self.workflow.setEnabled(not busy)
        self.auto_quality.setEnabled(not busy)
        self._basic_box.setEnabled(not busy)
        self._preprocess_box.setEnabled(not busy)
        self._colors_box.setEnabled(not busy)
        self._advanced_box.setEnabled(not busy)
        if not busy:
            self._on_remove_bg_toggled(self.remove_background.isChecked())

    def set_notes(self, text: str) -> None:
        """Store English note lines and show them in the active language."""
        self._notes_en = (text or "").strip()
        self._apply_notes_text()

    @property
    def notes_english(self) -> str:
        return self._notes_en

    def _apply_notes_text(self) -> None:
        if not self._notes_en:
            self.notes.clear()
            self.notes.setVisible(False)
            return
        translated = "\n".join(t(line) for line in self._notes_en.splitlines())
        self.notes.setText(translated)
        self.notes.setVisible(True)

    def set_palette(self, colors: list[str]) -> None:
        self._palette_colors = list(colors)
        self.palette_list.clear()
        for color in colors:
            qcolor = QColor(color)
            if not qcolor.isValid():
                continue
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, color)
            item.setToolTip(color)
            item.setSizeHint(QSize(0, 30))
            self.palette_list.addItem(item)
            swatch = QLabel(color)
            swatch.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fg = "#000000" if qcolor.lightness() > 140 else "#ffffff"
            swatch.setStyleSheet(
                "QLabel {"
                f" background-color: {qcolor.name()};"
                f" color: {fg};"
                " border: 1px solid #c8c8ce;"
                " border-radius: 6px;"
                " padding: 4px 8px;"
                " font-weight: 600;"
                "}"
            )
            self.palette_list.setItemWidget(item, swatch)
        self._sync_optional_color_rows()

    def set_background_color(self, color: QColor, *, enable_removal: bool = True) -> None:
        if not color.isValid():
            return
        self._bg_color = QColor(color)
        if enable_removal and not self.remove_background.isChecked():
            self.remove_background.setChecked(True)
        self._update_bg_button()
        self._on_remove_bg_toggled(self.remove_background.isChecked())
        self._emit_changed()

    def set_palette_suggestions(self, suggestions: dict[int, tuple[str, ...]]) -> None:
        """Counts 2/4/8/12 plus -1 for the analyzer's best palette."""
        self._palette_suggestions = {int(key): tuple(value) for key, value in suggestions.items()}

    def add_trace_color(self, hex_color: str) -> None:
        try:
            color = normalize_hex(hex_color)
        except ValueError:
            return
        if color not in self._trace_palette and len(self._trace_palette) < 32:
            self._trace_palette.append(color)
        self._refresh_trace_palette()
        self._set_combo(self.palette_choice, -2)
        self._emit_changed()

    def _remove_trace_color(self) -> None:
        row = self.trace_palette_list.currentRow()
        if row < 0 or row >= len(self._trace_palette):
            QMessageBox.information(self, t("Palette"), t("Select a palette color first."))
            return
        del self._trace_palette[row]
        self._refresh_trace_palette()
        self._set_combo(self.palette_choice, -2 if self._trace_palette else 0)
        self._emit_changed()

    def _sync_optional_color_rows(self) -> None:
        """Show the custom palette editor and result swatches only when they have a job."""
        choice = self.palette_choice.currentData()
        self._trace_editor.setVisible(choice == -2 or bool(self._trace_palette))
        self._result_palette.setVisible(self.palette_list.count() > 0)

    def _apply_palette_choice(self) -> None:
        if self._updating:
            return
        choice = self.palette_choice.currentData()
        if choice == -2:
            self._sync_optional_color_rows()
            return
        if choice in (None,):
            return
        if choice == 0:
            self._trace_palette = []
        else:
            colors = self._palette_suggestions.get(int(choice))
            if not colors:
                self._sync_optional_color_rows()
                return
            self._trace_palette = list(colors)
        self._refresh_trace_palette()
        self._sync_optional_color_rows()
        self._emit_changed()

    def _refresh_trace_palette(self) -> None:
        self.trace_palette_list.clear()
        for color in self._trace_palette:
            item = QListWidgetItem(color)
            item.setData(Qt.ItemDataRole.UserRole, color)
            swatch = QLabel(color)
            swatch.setAutoFillBackground(True)
            swatch.setStyleSheet(
                f"QLabel {{ background: {color}; color: {'#000' if QColor(color).lightness() > 140 else '#fff'}; "
                "padding: 2px 6px; }}"
            )
            self.trace_palette_list.addItem(item)
            self.trace_palette_list.setItemWidget(item, swatch)
        self._sync_optional_color_rows()

    def _select_palette_choice(self, palette: tuple[str, ...]) -> None:
        if not palette:
            self._set_combo(self.palette_choice, 0)
            return
        for count, colors in self._palette_suggestions.items():
            if count > 0 and tuple(colors) == tuple(palette):
                self._set_combo(self.palette_choice, count)
                return
        self._set_combo(self.palette_choice, -2)

    def set_settings(self, settings: TraceSettings) -> None:
        self._updating = True
        try:
            self._set_combo(self.workflow, settings.workflow)
            self._set_combo(self.auto_quality, settings.automatic_quality)
            self._set_combo(self.colormode, settings.colormode)
            self._set_combo(self.hierarchy, settings.hierarchical)
            self._set_combo(self.path_mode, settings.mode)
            self.filter_speckle.setValue(settings.filter_speckle)
            self.color_precision.setValue(settings.color_precision)
            self.layer_difference.setValue(settings.layer_difference)
            self.corner_threshold.setValue(settings.corner_threshold)
            self.length_threshold.setValue(settings.length_threshold)
            self.max_iterations.setValue(settings.max_iterations)
            self.splice_threshold.setValue(settings.splice_threshold)
            self.path_precision.setValue(settings.path_precision)
            self.preserve_transparency.setChecked(settings.preserve_transparency)
            self.remove_background.setChecked(settings.remove_background)
            self.bg_tolerance.setValue(settings.background_tolerance)
            self._bg_color = QColor(
                settings.background_r, settings.background_g, settings.background_b
            )
            self.target_colors.setValue(settings.target_colors)
            self.smooth_noise.setChecked(settings.smooth_noise)
            self._set_combo(self.edge_treatment, settings.edge_treatment)
            self._set_combo(self.svg_style, settings.svg_paint_style)
            self._set_combo(self.dxf_mode, settings.dxf_curve_mode)
            self._trace_palette = list(settings.palette)
            self._refresh_trace_palette()
            self._select_palette_choice(settings.palette)
            self._update_bg_button()
            self._on_workflow_changed()
            self._on_remove_bg_toggled(settings.remove_background)
            self._sync_optional_color_rows()
        finally:
            self._updating = False

    def settings(self) -> TraceSettings:
        return TraceSettings(
            workflow=self.workflow.currentData(),
            automatic_quality=self.auto_quality.currentData() or AutomaticQuality.BALANCED,
            colormode=self.colormode.currentData(),
            hierarchical=self.hierarchy.currentData(),
            mode=self.path_mode.currentData(),
            filter_speckle=self.filter_speckle.value(),
            color_precision=self.color_precision.value(),
            layer_difference=self.layer_difference.value(),
            corner_threshold=self.corner_threshold.value(),
            length_threshold=float(self.length_threshold.value()),
            max_iterations=self.max_iterations.value(),
            splice_threshold=self.splice_threshold.value(),
            path_precision=self.path_precision.value(),
            preserve_transparency=self.preserve_transparency.isChecked(),
            remove_background=self.remove_background.isChecked(),
            background_r=self._bg_color.red(),
            background_g=self._bg_color.green(),
            background_b=self._bg_color.blue(),
            background_tolerance=self.bg_tolerance.value(),
            target_colors=self.target_colors.value(),
            smooth_noise=self.smooth_noise.isChecked(),
            edge_treatment=self.edge_treatment.currentData() or EdgeTreatment.AUTO,
            palette=tuple(self._trace_palette),
            svg_paint_style=self.svg_style.currentData() or SvgPaintStyle.FILL,
            dxf_curve_mode=self.dxf_mode.currentData() or DxfCurveMode.LINES,
        ).validated()

    def refresh_presets(self) -> None:
        current = self.preset_combo.currentText()
        self.preset_combo.clear()
        for name in list_presets():
            self.preset_combo.addItem(name)
        idx = self.preset_combo.findText(current)
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)

    def _pick_bg_color(self) -> None:
        color = QColorDialog.getColor(self._bg_color, self, t("Background color"))
        if color.isValid():
            self.set_background_color(color, enable_removal=True)

    def _update_bg_button(self) -> None:
        self.bg_color_btn.setText(self._bg_color.name())
        self.bg_color_btn.setStyleSheet(
            f"QPushButton {{ background: {self._bg_color.name()}; "
            f"color: {'#000' if self._bg_color.lightness() > 140 else '#fff'}; }}"
        )

    def _recolor_selected(self) -> None:
        item = self.palette_list.currentItem()
        if item is None:
            QMessageBox.information(self, t("Palette"), t("Select a palette color first."))
            return
        old = item.data(Qt.ItemDataRole.UserRole) or item.text()
        if not isinstance(old, str) or not old:
            QMessageBox.information(self, t("Palette"), t("Select a palette color first."))
            return
        color = QColorDialog.getColor(QColor(old), self, t("New fill color"))
        if not color.isValid():
            return
        self.palette_recolor_requested.emit({old: color.name()})

    def _save_preset(self) -> None:
        name, ok = QInputDialog.getText(self, t("Save preset"), t("Preset name:"))
        if not ok or not name.strip():
            return
        try:
            save_preset(name.strip(), self.settings())
        except (PresetError, ValueError) as exc:
            QMessageBox.warning(self, t("Preset"), str(exc))
            return
        self.refresh_presets()
        self.preset_combo.setCurrentText(name.strip())

    def _load_preset(self) -> None:
        name = self.preset_combo.currentText()
        if not name:
            return
        try:
            settings = load_preset(name)
        except PresetError as exc:
            QMessageBox.warning(self, t("Preset"), str(exc))
            return
        self.set_settings(settings)
        update_preferences(
            last_preset=name,
            workflow=settings.workflow,
            automatic_quality=settings.automatic_quality,
        )
        self.settings_changed.emit()

    def apply_last_preset(self) -> bool:
        """Load the remembered preset if it still exists. Returns True on success."""
        from vectorizer.gui.preferences import current_preferences

        name = current_preferences().last_preset
        if not name or name not in list_presets():
            return False
        try:
            settings = load_preset(name)
        except PresetError:
            return False
        self.set_settings(settings)
        idx = self.preset_combo.findText(name)
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)
        return True

    def _delete_preset(self) -> None:
        name = self.preset_combo.currentText()
        if not name:
            return
        answer = QMessageBox.question(
            self, t("Delete preset"), tf('Delete preset “{name}”?', name=name)
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_preset(name)
        except PresetError as exc:
            QMessageBox.warning(self, t("Preset"), str(exc))
            return
        self.refresh_presets()

    def _duplicate_preset(self) -> None:
        source = self.preset_combo.currentText()
        if not source:
            return
        name, ok = QInputDialog.getText(
            self,
            t("Duplicate preset"),
            t("New name:"),
            text=tf("{source} copy", source=source),
        )
        if not ok or not name.strip():
            return
        try:
            duplicate_preset(source, name.strip())
        except PresetError as exc:
            QMessageBox.warning(self, t("Preset"), str(exc))
            return
        self.refresh_presets()
        self.preset_combo.setCurrentText(name.strip())

    @staticmethod
    def _set_combo(combo: QComboBox, value) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return
