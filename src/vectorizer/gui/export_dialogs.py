"""Per-format export option dialogs (moved out of the sidebar)."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from vectorizer.domain.settings import (
    DxfCurveMode,
    DxfLineDensity,
    EpsCompatibility,
    SvgPaintStyle,
    TraceSettings,
)
from vectorizer.gui.i18n import t
from vectorizer.gui.slider_spin import DoubleSliderSpin


class SvgExportDialog(QDialog):
    def __init__(self, parent: QWidget | None, settings: TraceSettings) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("Export SVG"))
        self.svg_style = QComboBox()
        self.gap_filler_width = DoubleSliderSpin(0.0, 5.0, step=0.1, decimals=2)
        self.gap_filler_non_scaling = QCheckBox()

        form = QFormLayout()
        self._style_label = QLabel()
        form.addRow(self._style_label, self.svg_style)
        self._gap_wrap = QWidget()
        gap_col = QVBoxLayout(self._gap_wrap)
        gap_col.setContentsMargins(0, 0, 0, 0)
        gap_col.setSpacing(2)
        self._gap_label = QLabel()
        gap_col.addWidget(self._gap_label)
        gap_col.addWidget(self.gap_filler_width)
        form.addRow(self._gap_wrap)
        form.addRow(self.gap_filler_non_scaling)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self.svg_style.currentIndexChanged.connect(self._sync_gap_rows)
        self._retranslate()
        self._load(settings)
        self._sync_gap_rows()

    def _retranslate(self) -> None:
        self._style_label.setText(t("SVG paint"))
        self._gap_label.setText(t("Gap / edge stroke width"))
        self.gap_filler_non_scaling.setText(t("Non-scaling gap / edge strokes"))
        self.svg_style.blockSignals(True)
        self.svg_style.clear()
        for key, data in (
            ("Fill only", SvgPaintStyle.FILL),
            ("Stroke and fill", SvgPaintStyle.STROKE_FILL),
            ("Gap filler", SvgPaintStyle.GAP_FILLER),
            ("Stroke edges", SvgPaintStyle.STROKE_EDGES),
        ):
            self.svg_style.addItem(t(key), data)
        self.svg_style.blockSignals(False)
        self.svg_style.setToolTip(
            t(
                "Fill only is the simpler file. Stroke and fill paints a same-color hairline. "
                "Gap filler puts average-color strokes under shared edges. "
                "Stroke edges exports cutting paths only."
            )
        )
        self.gap_filler_non_scaling.setToolTip(
            t("Keep stroke width constant when zooming (SVG vector-effect).")
        )

    def _load(self, settings: TraceSettings) -> None:
        self._set_combo(self.svg_style, settings.svg_paint_style)
        self.gap_filler_width.setValue(settings.gap_filler_width)
        self.gap_filler_non_scaling.setChecked(settings.gap_filler_non_scaling)

    def _sync_gap_rows(self) -> None:
        show = self.svg_style.currentData() in {
            SvgPaintStyle.GAP_FILLER,
            SvgPaintStyle.STROKE_EDGES,
        }
        self._gap_wrap.setEnabled(show)
        self.gap_filler_non_scaling.setEnabled(show)

    def applied(self, settings: TraceSettings) -> TraceSettings:
        return replace(
            settings,
            svg_paint_style=self.svg_style.currentData() or SvgPaintStyle.FILL,
            gap_filler_width=float(self.gap_filler_width.value()),
            gap_filler_non_scaling=self.gap_filler_non_scaling.isChecked(),
        ).validated()

    @staticmethod
    def _set_combo(combo: QComboBox, value: object) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return


class DxfExportDialog(QDialog):
    def __init__(self, parent: QWidget | None, settings: TraceSettings) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("Export DXF"))
        self.dxf_mode = QComboBox()
        self.dxf_density = QComboBox()
        form = QFormLayout()
        self._mode_label = QLabel()
        self._density_label = QLabel()
        form.addRow(self._mode_label, self.dxf_mode)
        form.addRow(self._density_label, self.dxf_density)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.dxf_mode.currentIndexChanged.connect(self._sync_density)
        self._retranslate()
        self._load(settings)
        self._sync_density()

    def _retranslate(self) -> None:
        self._mode_label.setText(t("DXF curves"))
        self._density_label.setText(t("DXF line density"))
        self.dxf_mode.blockSignals(True)
        self.dxf_mode.clear()
        for key, data in (
            ("DXF lines", DxfCurveMode.LINES),
            ("DXF lines and arcs", DxfCurveMode.LINES_AND_ARCS),
            ("DXF splines", DxfCurveMode.SPLINES),
        ):
            self.dxf_mode.addItem(t(key), data)
        self.dxf_mode.blockSignals(False)
        self.dxf_density.blockSignals(True)
        self.dxf_density.clear()
        for key, data in (
            ("Few (~4)", DxfLineDensity.FEW),
            ("Normal (~8)", DxfLineDensity.NORMAL),
            ("Many (~16)", DxfLineDensity.MANY),
        ):
            self.dxf_density.addItem(t(key), data)
        self.dxf_density.blockSignals(False)
        self.dxf_mode.setToolTip(
            t(
                "Lines samples curves into polylines. Lines and arcs keep circular arcs. "
                "Splines keep cubic curves. None of these modes write fills."
            )
        )
        self.dxf_density.setToolTip(
            t(
                "How many samples LINES mode uses per curve. Few is about 4, normal is 8, "
                "many is about 16. Lines-and-arcs and splines keep their own geometry."
            )
        )

    def _load(self, settings: TraceSettings) -> None:
        SvgExportDialog._set_combo(self.dxf_mode, settings.dxf_curve_mode)
        SvgExportDialog._set_combo(self.dxf_density, settings.dxf_line_density)

    def _sync_density(self) -> None:
        lines = self.dxf_mode.currentData() == DxfCurveMode.LINES
        self.dxf_density.setEnabled(lines)
        self._density_label.setEnabled(lines)

    def applied(self, settings: TraceSettings) -> TraceSettings:
        return replace(
            settings,
            dxf_curve_mode=self.dxf_mode.currentData() or DxfCurveMode.LINES,
            dxf_line_density=self.dxf_density.currentData() or DxfLineDensity.NORMAL,
        ).validated()


class EpsExportDialog(QDialog):
    def __init__(self, parent: QWidget | None, settings: TraceSettings) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("Export EPS"))
        self.eps_level = QComboBox()
        form = QFormLayout()
        self._level_label = QLabel()
        form.addRow(self._level_label, self.eps_level)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self._retranslate()
        SvgExportDialog._set_combo(self.eps_level, settings.eps_compatibility)

    def _retranslate(self) -> None:
        self._level_label.setText(t("EPS compatibility"))
        self.eps_level.blockSignals(True)
        self.eps_level.clear()
        for key, data in (
            ("Maximize compatibility", EpsCompatibility.COMPATIBLE),
            ("Minimize file size", EpsCompatibility.COMPACT),
        ):
            self.eps_level.addItem(t(key), data)
        self.eps_level.blockSignals(False)
        self.eps_level.setToolTip(
            t(
                "Maximize compatibility writes PostScript Level 2. "
                "Minimize file size writes Level 3."
            )
        )

    def applied(self, settings: TraceSettings) -> TraceSettings:
        return replace(
            settings,
            eps_compatibility=self.eps_level.currentData() or EpsCompatibility.COMPACT,
        ).validated()
