"""Settings → Preferences dialog for app-level options."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from vectorizer.batch.engine import CollisionPolicy
from vectorizer.domain.settings import (
    AutomaticQuality,
    DxfCurveMode,
    DxfLineDensity,
    EpsCompatibility,
    SvgPaintStyle,
    WorkflowMode,
)
from vectorizer.export.tools import find_inkscape
from vectorizer.gui.i18n import preferences_file_filter, t, tf
from vectorizer.gui.preferences import (
    AppPreferences,
    PreferencesFileError,
    current_preferences,
    parse_preferences_file,
    save_preferences,
    write_preferences_file,
)
from vectorizer.presets import list_presets


def _comfortable_form(parent: QWidget | None = None) -> QFormLayout:
    form = QFormLayout(parent)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    form.setHorizontalSpacing(16)
    form.setVerticalSpacing(8)
    return form


def _path_row(edit: QLineEdit, *buttons: QPushButton) -> QWidget:
    wrap = QWidget()
    row = QHBoxLayout(wrap)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    row.addWidget(edit, 1)
    for button in buttons:
        button.setMinimumWidth(90)
        row.addWidget(button)
    return wrap


def _tab_page(*widgets: QWidget) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(12)
    for widget in widgets:
        layout.addWidget(widget)
    layout.addStretch(1)
    return page


class PreferencesDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(720, 520)
        prefs = current_preferences()

        self.workflow = QComboBox()
        self.workflow.addItem("", WorkflowMode.AUTOMATIC)
        self.workflow.addItem("", WorkflowMode.BASIC)
        self.workflow.addItem("", WorkflowMode.ADVANCED)
        self.workflow.setMinimumWidth(180)

        self.auto_quality = QComboBox()
        self.auto_quality.addItem("", AutomaticQuality.FAST)
        self.auto_quality.addItem("", AutomaticQuality.BALANCED)
        self.auto_quality.addItem("", AutomaticQuality.HIGH)
        self.auto_quality.setMinimumWidth(180)

        self.export_dir = QLineEdit(prefs.export_dir)
        self.browse_export = QPushButton()
        self.browse_export.clicked.connect(self._browse_export_dir)

        self.fmt_svg = QCheckBox()
        self.fmt_pdf = QCheckBox()
        self.fmt_png = QCheckBox()
        self.fmt_dxf = QCheckBox()
        self.fmt_eps = QCheckBox()

        self.batch_collision = QComboBox()
        self.batch_collision.setMinimumWidth(180)
        self.batch_continue = QCheckBox()
        self.batch_input = QLineEdit(prefs.batch_input_dir)
        self.batch_output = QLineEdit(prefs.batch_output_dir)
        self.browse_batch_in = QPushButton()
        self.browse_batch_out = QPushButton()
        self.browse_batch_in.clicked.connect(self._browse_batch_input)
        self.browse_batch_out.clicked.connect(self._browse_batch_output)

        self.confirm_overwrite = QCheckBox()

        self.last_preset = QComboBox()
        self.last_preset.setMinimumWidth(180)
        self.last_preset.addItem("", "")
        for name in list_presets():
            self.last_preset.addItem(name, name)

        self.inkscape_path = QLineEdit(prefs.inkscape_path)
        self.browse_inkscape = QPushButton()
        self.clear_inkscape = QPushButton()
        self.browse_inkscape.clicked.connect(self._browse_inkscape)
        self.clear_inkscape.clicked.connect(lambda: self.inkscape_path.clear())
        self.inkscape_status = QLabel()
        self.inkscape_status.setWordWrap(True)

        self.png_width = QSpinBox()
        self.png_width.setRange(0, 16000)
        self.png_width.setSpecialValueText("")
        self.png_width.setMinimumWidth(110)
        self.png_height = QSpinBox()
        self.png_height.setRange(0, 16000)
        self.png_height.setSpecialValueText("")
        self.png_height.setMinimumWidth(110)
        self.png_bg = QComboBox()
        self.png_bg.setMinimumWidth(160)
        self.png_bg.addItem("", "")
        self.png_bg.addItem("", "#ffffff")
        self.png_bg.addItem("", "#000000")
        self.png_bg.addItem("", "#1f9ede")

        self.svg_style = QComboBox()
        self.gap_filler_width = QDoubleSpinBox()
        self.gap_filler_width.setRange(0.0, 5.0)
        self.gap_filler_width.setSingleStep(0.1)
        self.gap_filler_width.setDecimals(2)
        self.gap_filler_non_scaling = QCheckBox()
        self.parameterized_shapes = QCheckBox()
        self.palette_tolerance = QSpinBox()
        self.palette_tolerance.setRange(0, 255)
        self.dxf_mode = QComboBox()
        self.dxf_density = QComboBox()
        self.eps_level = QComboBox()
        self.max_side = QSpinBox()
        self.max_side.setRange(0, 16384)

        self.session_steps = QSpinBox()
        self.session_steps.setRange(2, 500)
        self.session_steps.setMinimumWidth(110)
        self.seg_steps = QSpinBox()
        self.seg_steps.setRange(2, 500)
        self.seg_steps.setMinimumWidth(110)
        self.seg_mib = QSpinBox()
        self.seg_mib.setRange(8, 512)
        self.seg_mib.setSuffix(" MiB")
        self.seg_mib.setMinimumWidth(110)

        for combo in (
            self.workflow,
            self.auto_quality,
            self.last_preset,
            self.batch_collision,
            self.png_bg,
            self.svg_style,
            self.dxf_mode,
            self.dxf_density,
            self.eps_level,
        ):
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        defaults = QGroupBox()
        defaults_form = _comfortable_form(defaults)
        self._workflow_label = QLabel()
        self._quality_label = QLabel()
        self._export_dir_label = QLabel()
        self._preset_label = QLabel()
        defaults_form.addRow(self._workflow_label, self.workflow)
        defaults_form.addRow(self._quality_label, self.auto_quality)
        defaults_form.addRow(
            self._export_dir_label, _path_row(self.export_dir, self.browse_export)
        )
        defaults_form.addRow(self._preset_label, self.last_preset)
        defaults_form.addRow(self.confirm_overwrite)
        self._defaults_box = defaults

        formats = QGroupBox()
        fmt_grid = QGridLayout(formats)
        fmt_grid.setHorizontalSpacing(16)
        fmt_grid.setVerticalSpacing(6)
        fmt_boxes = (self.fmt_svg, self.fmt_pdf, self.fmt_png, self.fmt_dxf, self.fmt_eps)
        for index, box in enumerate(fmt_boxes):
            fmt_grid.addWidget(box, index // 3, index % 3)
        self._formats_box = formats

        svg_box = QGroupBox()
        svg_form = _comfortable_form(svg_box)
        self._svg_style_label = QLabel()
        self._gap_width_label = QLabel()
        self._palette_tol_label = QLabel()
        svg_form.addRow(self._svg_style_label, self.svg_style)
        svg_form.addRow(self._gap_width_label, self.gap_filler_width)
        svg_form.addRow(self.gap_filler_non_scaling)
        svg_form.addRow(self.parameterized_shapes)
        svg_form.addRow(self._palette_tol_label, self.palette_tolerance)
        self._svg_box = svg_box

        cad_box = QGroupBox()
        cad_form = _comfortable_form(cad_box)
        self._dxf_mode_label = QLabel()
        self._dxf_density_label = QLabel()
        self._eps_level_label = QLabel()
        cad_form.addRow(self._dxf_mode_label, self.dxf_mode)
        cad_form.addRow(self._dxf_density_label, self.dxf_density)
        cad_form.addRow(self._eps_level_label, self.eps_level)
        self._cad_box = cad_box

        batch = QGroupBox()
        batch_form = _comfortable_form(batch)
        self._collision_label = QLabel()
        self._batch_in_label = QLabel()
        self._batch_out_label = QLabel()
        batch_form.addRow(self._collision_label, self.batch_collision)
        batch_form.addRow(self.batch_continue)
        batch_form.addRow(
            self._batch_in_label, _path_row(self.batch_input, self.browse_batch_in)
        )
        batch_form.addRow(
            self._batch_out_label, _path_row(self.batch_output, self.browse_batch_out)
        )
        self._batch_box = batch

        tools = QGroupBox()
        tools_form = _comfortable_form(tools)
        self._inkscape_label = QLabel()
        tools_form.addRow(
            self._inkscape_label,
            _path_row(self.inkscape_path, self.browse_inkscape, self.clear_inkscape),
        )
        tools_form.addRow(self.inkscape_status)
        self._tools_box = tools

        png = QGroupBox()
        png_form = _comfortable_form(png)
        self._png_w_label = QLabel()
        self._png_h_label = QLabel()
        self._png_bg_label = QLabel()
        self._png_hint = QLabel()
        self._png_hint.setWordWrap(True)
        png_form.addRow(self._png_w_label, self.png_width)
        png_form.addRow(self._png_h_label, self.png_height)
        png_form.addRow(self._png_bg_label, self.png_bg)
        png_form.addRow(self._png_hint)
        self._png_box = png

        history = QGroupBox()
        hist_form = _comfortable_form(history)
        self._session_label = QLabel()
        self._seg_steps_label = QLabel()
        self._seg_mib_label = QLabel()
        self._max_side_label = QLabel()
        hist_form.addRow(self._session_label, self.session_steps)
        hist_form.addRow(self._seg_steps_label, self.seg_steps)
        hist_form.addRow(self._seg_mib_label, self.seg_mib)
        hist_form.addRow(self._max_side_label, self.max_side)
        self._history_box = history

        self.tabs = QTabWidget()
        self.tabs.addTab(_tab_page(defaults), "")
        self.tabs.addTab(_tab_page(formats, png, svg_box, cad_box), "")
        self.tabs.addTab(_tab_page(batch), "")
        self.tabs.addTab(_tab_page(history, tools), "")

        self.save_file_btn = QPushButton()
        self.load_file_btn = QPushButton()
        self.reset_btn = QPushButton()
        self.save_file_btn.clicked.connect(self._save_to_file)
        self.load_file_btn.clicked.connect(self._load_from_file)
        self.reset_btn.clicked.connect(self._reset_to_defaults)
        self._file_status = QLabel()
        self._file_status.setWordWrap(False)
        self._file_status.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        self._file_status.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._file_status.hide()
        self.chrome_reset_requested = False

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self._accept)
        self._buttons.rejected.connect(self.reject)
        self._buttons.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        for button in (self.save_file_btn, self.load_file_btn, self.reset_btn):
            button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._loading_form = False

        button_bar = QHBoxLayout()
        button_bar.setContentsMargins(0, 0, 0, 0)
        box_layout = self._buttons.layout()
        if box_layout is not None:
            box_layout.setContentsMargins(0, 0, 0, 0)
            spacing = box_layout.spacing()
            button_bar.setSpacing(spacing if spacing >= 0 else 8)
        button_bar.addWidget(self.save_file_btn)
        button_bar.addWidget(self.load_file_btn)
        button_bar.addWidget(self.reset_btn)
        button_bar.addWidget(self._file_status, 1)
        button_bar.addStretch(1)
        button_bar.addWidget(self._buttons)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        layout.addWidget(self.tabs, 1)
        layout.addLayout(button_bar)

        self.dxf_mode.currentIndexChanged.connect(self._sync_dxf_density)
        self.svg_style.currentIndexChanged.connect(self._sync_gap_rows)

        self._load_values(prefs)
        self.retranslate_ui()
        self._refresh_inkscape_status()
        self._watch_form_edits()
        self.inkscape_path.textChanged.connect(lambda _t: self._refresh_inkscape_status())
        hint = self.sizeHint()
        self.resize(max(hint.width() + 40, 780), max(hint.height() + 24, 560))

    def retranslate_ui(self) -> None:
        self.setWindowTitle(t("Preferences"))
        self.tabs.setTabText(0, t("General"))
        self.tabs.setTabText(1, t("Export"))
        self.tabs.setTabText(2, t("Batch"))
        self.tabs.setTabText(3, t("Advanced"))
        self.save_file_btn.setText(t("&Save to file"))
        self.load_file_btn.setText(t("&Load from file"))
        self.reset_btn.setText(t("&Reset Preferences"))
        self._defaults_box.setTitle(t("Defaults"))
        self._workflow_label.setText(t("Default mode"))
        self._quality_label.setText(t("Default Automatic quality"))
        self._export_dir_label.setText(t("Default export folder"))
        self._preset_label.setText(t("Last preset"))
        self.browse_export.setText(t("Browse…"))
        self.confirm_overwrite.setText(t("Confirm before overwriting files"))

        self._set_combo_labels(
            self.workflow,
            (
                (t("Automatic"), WorkflowMode.AUTOMATIC),
                (t("Basic"), WorkflowMode.BASIC),
                (t("Advanced"), WorkflowMode.ADVANCED),
            ),
        )
        self._set_combo_labels(
            self.auto_quality,
            (
                (t("Fast"), AutomaticQuality.FAST),
                (t("Balanced"), AutomaticQuality.BALANCED),
                (t("High detail"), AutomaticQuality.HIGH),
            ),
        )
        if self.last_preset.count() > 0 and self.last_preset.itemData(0) == "":
            self.last_preset.setItemText(0, t("(none)"))

        self._formats_box.setTitle(t("Default export formats"))
        self.fmt_svg.setText(t("SVG"))
        self.fmt_pdf.setText(t("PDF"))
        self.fmt_png.setText(t("PNG preview"))
        self.fmt_dxf.setText(t("DXF (outlines)"))
        self.fmt_eps.setText(t("EPS (Inkscape)"))

        self._svg_box.setTitle(t("SVG defaults"))
        self._svg_style_label.setText(t("SVG paint"))
        self._gap_width_label.setText(t("Gap / edge stroke width"))
        self._palette_tol_label.setText(t("Palette snap tolerance"))
        self.gap_filler_non_scaling.setText(t("Non-scaling gap / edge strokes"))
        self.parameterized_shapes.setText(t("Detect circles and rectangles"))
        self._set_combo_labels(
            self.svg_style,
            (
                (t("Fill only"), SvgPaintStyle.FILL),
                (t("Stroke and fill"), SvgPaintStyle.STROKE_FILL),
                (t("Gap filler"), SvgPaintStyle.GAP_FILLER),
                (t("Stroke edges"), SvgPaintStyle.STROKE_EDGES),
            ),
        )

        self._cad_box.setTitle(t("DXF / EPS defaults"))
        self._dxf_mode_label.setText(t("DXF curves"))
        self._dxf_density_label.setText(t("DXF line density"))
        self._eps_level_label.setText(t("EPS compatibility"))
        self._set_combo_labels(
            self.dxf_mode,
            (
                (t("DXF lines"), DxfCurveMode.LINES),
                (t("DXF lines and arcs"), DxfCurveMode.LINES_AND_ARCS),
                (t("DXF splines"), DxfCurveMode.SPLINES),
            ),
        )
        self._set_combo_labels(
            self.dxf_density,
            (
                (t("Few (~4)"), DxfLineDensity.FEW),
                (t("Normal (~8)"), DxfLineDensity.NORMAL),
                (t("Many (~16)"), DxfLineDensity.MANY),
            ),
        )
        self._set_combo_labels(
            self.eps_level,
            (
                (t("Maximize compatibility"), EpsCompatibility.COMPATIBLE),
                (t("Minimize file size"), EpsCompatibility.COMPACT),
            ),
        )
        self._sync_dxf_density()
        self._sync_gap_rows()

        self._batch_box.setTitle(t("Batch defaults"))
        self._collision_label.setText(t("Collisions"))
        self.batch_continue.setText(t("Continue on error"))
        self._batch_in_label.setText(t("Input folder"))
        self._batch_out_label.setText(t("Output folder"))
        self.browse_batch_in.setText(t("Browse…"))
        self.browse_batch_out.setText(t("Browse…"))
        self._set_combo_labels(
            self.batch_collision,
            (
                (t("Rename (file_1.svg)"), CollisionPolicy.RENAME),
                (t("Skip existing"), CollisionPolicy.SKIP),
                (t("Overwrite"), CollisionPolicy.OVERWRITE),
            ),
        )

        self._tools_box.setTitle(t("External tools"))
        self._inkscape_label.setText(t("Inkscape path"))
        self.browse_inkscape.setText(t("Browse…"))
        self.clear_inkscape.setText(t("Clear"))
        self.inkscape_path.setPlaceholderText(t("Leave empty to use PATH"))

        self._png_box.setTitle(t("PNG preview defaults"))
        self._png_w_label.setText(t("Width (px)"))
        self._png_h_label.setText(t("Height (px)"))
        self._png_bg_label.setText(t("Background"))
        self._png_hint.setText(t("Width/height 0 = use the vector document size."))
        self.png_width.setSpecialValueText(t("Document"))
        self.png_height.setSpecialValueText(t("Document"))
        self._set_combo_labels(
            self.png_bg,
            (
                (t("Transparent"), ""),
                (t("White"), "#ffffff"),
                (t("Black"), "#000000"),
                (t("Mint Aqua"), "#1f9ede"),
            ),
        )

        self._history_box.setTitle(t("History and limits"))
        self._session_label.setText(t("Session undo steps"))
        self._seg_steps_label.setText(t("Segmentation undo steps"))
        self._seg_mib_label.setText(t("Segmentation undo memory"))
        self._max_side_label.setText(t("Max working side"))
        self.max_side.setSpecialValueText(t("Prompt"))
        self.max_side.setToolTip(
            t(
                "0 asks before shrinking an image over the working limit. A positive value "
                "shrinks the working copy so the long side is at most this many pixels. "
                "The original file is not modified."
            )
        )

    def _load_values(self, prefs: AppPreferences) -> None:
        self._loading_form = True
        try:
            self._apply_values(prefs)
        finally:
            self._loading_form = False

    def _apply_values(self, prefs: AppPreferences) -> None:
        self._select_data(self.workflow, prefs.workflow)
        self._select_data(self.auto_quality, prefs.automatic_quality)
        self.export_dir.setText(prefs.export_dir)
        self.fmt_svg.setChecked(prefs.export_svg)
        self.fmt_pdf.setChecked(prefs.export_pdf)
        self.fmt_png.setChecked(prefs.export_png)
        self.fmt_dxf.setChecked(prefs.export_dxf)
        self.fmt_eps.setChecked(prefs.export_eps)
        self._select_data(self.batch_collision, prefs.batch_collision)
        self.batch_continue.setChecked(prefs.batch_continue_on_error)
        self.batch_input.setText(prefs.batch_input_dir)
        self.batch_output.setText(prefs.batch_output_dir)
        self.confirm_overwrite.setChecked(prefs.confirm_overwrite)
        idx = self.last_preset.findData(prefs.last_preset)
        if prefs.last_preset and idx < 0:
            self.last_preset.addItem(prefs.last_preset, prefs.last_preset)
            idx = self.last_preset.count() - 1
        self.last_preset.setCurrentIndex(idx if idx >= 0 else 0)
        self.inkscape_path.setText(prefs.inkscape_path)
        self.png_width.setValue(prefs.png_width)
        self.png_height.setValue(prefs.png_height)
        bg = prefs.png_background
        if not bg or bg.lower() == "transparent":
            bg = ""
        bg_idx = self.png_bg.findData(bg)
        self.png_bg.setCurrentIndex(bg_idx if bg_idx >= 0 else 0)
        self._select_data(self.svg_style, prefs.svg_paint_style)
        self.gap_filler_width.setValue(prefs.gap_filler_width)
        self.gap_filler_non_scaling.setChecked(prefs.gap_filler_non_scaling)
        self.parameterized_shapes.setChecked(prefs.parameterized_shapes)
        self.palette_tolerance.setValue(prefs.palette_tolerance)
        self._select_data(self.dxf_mode, prefs.dxf_curve_mode)
        self._select_data(self.dxf_density, prefs.dxf_line_density)
        self._select_data(self.eps_level, prefs.eps_compatibility)
        self.max_side.setValue(prefs.max_side)
        self.session_steps.setValue(prefs.session_history_steps)
        self.seg_steps.setValue(prefs.segmentation_history_steps)
        self.seg_mib.setValue(prefs.segmentation_history_mib)
        self._sync_dxf_density()
        self._sync_gap_rows()

    def _form_preferences(self) -> AppPreferences | None:
        if not (
            self.fmt_svg.isChecked()
            or self.fmt_pdf.isChecked()
            or self.fmt_png.isChecked()
            or self.fmt_dxf.isChecked()
            or self.fmt_eps.isChecked()
        ):
            QMessageBox.warning(
                self,
                t("Preferences"),
                t("Select at least one default export format."),
            )
            return None
        return AppPreferences(
            workflow=self.workflow.currentData(),
            automatic_quality=self.auto_quality.currentData(),
            export_dir=self.export_dir.text().strip(),
            export_svg=self.fmt_svg.isChecked(),
            export_pdf=self.fmt_pdf.isChecked(),
            export_png=self.fmt_png.isChecked(),
            export_dxf=self.fmt_dxf.isChecked(),
            export_eps=self.fmt_eps.isChecked(),
            batch_collision=self.batch_collision.currentData(),
            batch_continue_on_error=self.batch_continue.isChecked(),
            batch_input_dir=self.batch_input.text().strip(),
            batch_output_dir=self.batch_output.text().strip(),
            confirm_overwrite=self.confirm_overwrite.isChecked(),
            last_preset=str(self.last_preset.currentData() or ""),
            inkscape_path=self.inkscape_path.text().strip(),
            png_width=self.png_width.value(),
            png_height=self.png_height.value(),
            png_background=str(self.png_bg.currentData() or ""),
            svg_paint_style=self.svg_style.currentData() or SvgPaintStyle.FILL,
            gap_filler_width=float(self.gap_filler_width.value()),
            gap_filler_non_scaling=self.gap_filler_non_scaling.isChecked(),
            parameterized_shapes=self.parameterized_shapes.isChecked(),
            palette_tolerance=self.palette_tolerance.value(),
            dxf_curve_mode=self.dxf_mode.currentData() or DxfCurveMode.LINES,
            dxf_line_density=self.dxf_density.currentData() or DxfLineDensity.NORMAL,
            eps_compatibility=self.eps_level.currentData() or EpsCompatibility.COMPACT,
            max_side=self.max_side.value(),
            session_history_steps=self.session_steps.value(),
            segmentation_history_steps=self.seg_steps.value(),
            segmentation_history_mib=self.seg_mib.value(),
        ).validated()

    def _accept(self) -> None:
        prefs = self._form_preferences()
        if prefs is None:
            return
        save_preferences(prefs)
        self.accept()

    def _save_to_file(self) -> None:
        prefs = self._form_preferences()
        if prefs is None:
            return
        start = self._file_dialog_dir() / "vectorizer-preferences.json"
        path, _ = QFileDialog.getSaveFileName(
            self,
            t("Save preferences"),
            str(start),
            preferences_file_filter(),
        )
        if not path:
            return
        dest = Path(path)
        if dest.suffix.lower() != ".json":
            dest = dest.with_suffix(".json")
        if dest.exists() and self.confirm_overwrite.isChecked():
            answer = QMessageBox.question(
                self,
                t("Overwrite file?"),
                tf("{name} already exists. Replace it?", name=dest.name),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            write_preferences_file(dest, prefs)
        except PreferencesFileError as exc:
            QMessageBox.warning(self, t("Preferences"), str(exc))
            return
        self._set_file_status(tf("Saved preferences {path}", path=dest))

    def _load_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            t("Load preferences"),
            str(self._file_dialog_dir()),
            preferences_file_filter(),
        )
        if not path:
            return
        try:
            prefs = parse_preferences_file(Path(path))
        except PreferencesFileError as exc:
            QMessageBox.warning(self, t("Preferences"), str(exc))
            return
        self.chrome_reset_requested = False
        self._load_values(prefs)
        self._refresh_inkscape_status()
        self._set_file_status(
            tf("Loaded {path}. Press OK to apply these values.", path=path)
        )

    def _reset_to_defaults(self) -> None:
        answer = QMessageBox.question(
            self,
            t("Reset all preferences?"),
            t(
                "Reset these preferences to their defaults? Theme and recent files are "
                "cleared when you press OK. Language is kept."
            ),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._load_values(AppPreferences())
        self._refresh_inkscape_status()
        self.chrome_reset_requested = True
        self._set_file_status(t("Defaults shown. Press OK to apply them."))

    def _file_dialog_dir(self) -> Path:
        text = self.export_dir.text().strip()
        if text:
            candidate = Path(text).expanduser()
            if candidate.is_dir():
                return candidate
            if candidate.parent.is_dir():
                return candidate.parent
        return current_preferences().resolved_export_dir()

    def _set_file_status(self, text: str) -> None:
        self._file_status.setText(text)
        self._file_status.setToolTip(text)
        self._file_status.setVisible(bool(text))

    def _watch_form_edits(self) -> None:
        for combo in (
            self.workflow,
            self.auto_quality,
            self.last_preset,
            self.batch_collision,
            self.png_bg,
            self.svg_style,
            self.dxf_mode,
            self.dxf_density,
            self.eps_level,
        ):
            combo.currentIndexChanged.connect(self._on_form_edited)
        for box in (
            self.fmt_svg,
            self.fmt_pdf,
            self.fmt_png,
            self.fmt_dxf,
            self.fmt_eps,
            self.batch_continue,
            self.confirm_overwrite,
            self.gap_filler_non_scaling,
            self.parameterized_shapes,
        ):
            box.toggled.connect(self._on_form_edited)
        for edit in (
            self.export_dir,
            self.batch_input,
            self.batch_output,
            self.inkscape_path,
        ):
            edit.textChanged.connect(self._on_form_edited)
        for spin in (
            self.png_width,
            self.png_height,
            self.session_steps,
            self.seg_steps,
            self.seg_mib,
            self.palette_tolerance,
            self.max_side,
        ):
            spin.valueChanged.connect(self._on_form_edited)
        self.gap_filler_width.valueChanged.connect(self._on_form_edited)

    def _on_form_edited(self, *_args: object) -> None:
        if self._loading_form:
            return
        self._set_file_status("")

    def _sync_dxf_density(self) -> None:
        lines = self.dxf_mode.currentData() == DxfCurveMode.LINES
        self.dxf_density.setEnabled(lines)
        self._dxf_density_label.setEnabled(lines)

    def _sync_gap_rows(self) -> None:
        show = self.svg_style.currentData() in {
            SvgPaintStyle.GAP_FILLER,
            SvgPaintStyle.STROKE_EDGES,
        }
        self.gap_filler_width.setEnabled(show)
        self.gap_filler_non_scaling.setEnabled(show)
        self._gap_width_label.setEnabled(show)

    def _browse_export_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, t("Default export folder"), self.export_dir.text()
        )
        if path:
            self.export_dir.setText(path)

    def _browse_batch_input(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, t("Input folder"), self.batch_input.text()
        )
        if path:
            self.batch_input.setText(path)

    def _browse_batch_output(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, t("Output folder"), self.batch_output.text()
        )
        if path:
            self.batch_output.setText(path)

    def _browse_inkscape(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            t("Inkscape executable"),
            self.inkscape_path.text() or "/usr/bin",
        )
        if path:
            self.inkscape_path.setText(path)
            self._refresh_inkscape_status()

    def _refresh_inkscape_status(self) -> None:
        from vectorizer.export.tools import inkscape_override, set_inkscape_override

        previous = inkscape_override()
        try:
            set_inkscape_override(self.inkscape_path.text().strip() or None)
            tool = find_inkscape()
        finally:
            set_inkscape_override(previous)
        if tool.available:
            self.inkscape_status.setText(tool.notes)
        else:
            self.inkscape_status.setText(tool.notes)

    @staticmethod
    def _select_data(combo: QComboBox, value: object) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return

    @staticmethod
    def _set_combo_labels(
        combo: QComboBox, items: tuple[tuple[str, object], ...]
    ) -> None:
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for label, data in items:
            combo.addItem(label, data)
        PreferencesDialog._select_data(combo, current)
        combo.blockSignals(False)
