"""Settings → Preferences dialog for app-level options."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
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
    QVBoxLayout,
    QWidget,
)

from vectorizer.batch.engine import CollisionPolicy
from vectorizer.domain.settings import AutomaticQuality, WorkflowMode
from vectorizer.export.tools import find_inkscape
from vectorizer.gui.i18n import t
from vectorizer.gui.preferences import AppPreferences, current_preferences, save_preferences
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


class PreferencesDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(1080, 660)
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
        self.png_bg.addItem("", "")  # transparent
        self.png_bg.addItem("", "#ffffff")
        self.png_bg.addItem("", "#000000")
        self.png_bg.addItem("", "#1f9ede")

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
        hist_form.addRow(self._session_label, self.session_steps)
        hist_form.addRow(self._seg_steps_label, self.seg_steps)
        hist_form.addRow(self._seg_mib_label, self.seg_mib)
        self._history_box = history

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        left = QVBoxLayout()
        left.setSpacing(12)
        left.addWidget(defaults)
        left.addWidget(batch)
        left.addStretch(1)

        right = QVBoxLayout()
        right.setSpacing(12)
        right.addWidget(formats)
        right.addWidget(png)
        right.addWidget(history)
        right.addStretch(1)

        columns = QHBoxLayout()
        columns.setSpacing(16)
        columns.addLayout(left, 3)
        columns.addLayout(right, 2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        layout.addLayout(columns, 1)
        layout.addWidget(tools)
        layout.addWidget(buttons)

        self._load_values(prefs)
        self.retranslate_ui()
        self._refresh_inkscape_status()
        self.inkscape_path.textChanged.connect(lambda _t: self._refresh_inkscape_status())
        # Prefer content size, with a roomy floor so labels and spinboxes are not clipped.
        hint = self.sizeHint()
        self.resize(max(hint.width() + 40, 1120), max(hint.height() + 24, 700))

    def retranslate_ui(self) -> None:
        self.setWindowTitle(t("Preferences"))
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

        self._history_box.setTitle(t("History"))
        self._session_label.setText(t("Session undo steps"))
        self._seg_steps_label.setText(t("Segmentation undo steps"))
        self._seg_mib_label.setText(t("Segmentation undo memory"))

    def _load_values(self, prefs: AppPreferences) -> None:
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
        self.last_preset.setCurrentIndex(idx if idx >= 0 else 0)
        self.inkscape_path.setText(prefs.inkscape_path)
        self.png_width.setValue(prefs.png_width)
        self.png_height.setValue(prefs.png_height)
        bg = prefs.png_background
        if not bg or bg.lower() == "transparent":
            bg = ""
        bg_idx = self.png_bg.findData(bg)
        self.png_bg.setCurrentIndex(bg_idx if bg_idx >= 0 else 0)
        self.session_steps.setValue(prefs.session_history_steps)
        self.seg_steps.setValue(prefs.segmentation_history_steps)
        self.seg_mib.setValue(prefs.segmentation_history_mib)

    def _accept(self) -> None:
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
            return
        prefs = AppPreferences(
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
            session_history_steps=self.session_steps.value(),
            segmentation_history_steps=self.seg_steps.value(),
            segmentation_history_mib=self.seg_mib.value(),
        )
        save_preferences(prefs)
        self.accept()

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
        # Probe with temporary override without mutating global prefs yet.
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
