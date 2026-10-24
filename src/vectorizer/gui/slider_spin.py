"""Horizontal slider paired with a compact numeric field for direct entry."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QSlider,
    QSpinBox,
    QWidget,
)


class IntSliderSpin(QWidget):
    """Integer range: slider + spin box (no step buttons)."""

    valueChanged = Signal(int)

    def __init__(
        self,
        minimum: int = 0,
        maximum: int = 100,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._updating = False

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(max(1, (maximum - minimum) // 10))

        self.spin = QSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.spin.setFixedWidth(58)
        self.spin.setKeyboardTracking(False)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self.slider, 1)
        row.addWidget(self.spin, 0)

        self.slider.valueChanged.connect(self._on_slider)
        self.spin.valueChanged.connect(self._on_spin)

    def _on_slider(self, value: int) -> None:
        if self._updating:
            return
        self._updating = True
        self.spin.setValue(value)
        self._updating = False
        self.valueChanged.emit(value)

    def _on_spin(self, value: int) -> None:
        if self._updating:
            return
        self._updating = True
        self.slider.setValue(value)
        self._updating = False
        self.valueChanged.emit(value)

    def value(self) -> int:
        return int(self.spin.value())

    def setValue(self, value: int) -> None:  # noqa: N802 — Qt API
        self._updating = True
        self.spin.setValue(value)
        self.slider.setValue(value)
        self._updating = False

    def setRange(self, minimum: int, maximum: int) -> None:  # noqa: N802
        self.slider.setRange(minimum, maximum)
        self.spin.setRange(minimum, maximum)
        self.slider.setPageStep(max(1, (maximum - minimum) // 10))

    def setSpecialValueText(self, text: str) -> None:  # noqa: N802
        self.spin.setSpecialValueText(text)

    def setToolTip(self, tip: str) -> None:  # noqa: N802
        super().setToolTip(tip)
        self.slider.setToolTip(tip)
        self.spin.setToolTip(tip)


class DoubleSliderSpin(QWidget):
    """Float range: slider in discrete steps + double spin box (no step buttons)."""

    valueChanged = Signal(float)

    def __init__(
        self,
        minimum: float = 0.0,
        maximum: float = 1.0,
        *,
        step: float = 0.1,
        decimals: int = 2,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._updating = False
        self._step = float(step)
        self._minimum = float(minimum)
        self._maximum = float(maximum)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self._configure_slider_range()

        self.spin = QDoubleSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setSingleStep(step)
        self.spin.setDecimals(decimals)
        self.spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.spin.setFixedWidth(64)
        self.spin.setKeyboardTracking(False)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self.slider, 1)
        row.addWidget(self.spin, 0)

        self.slider.valueChanged.connect(self._on_slider)
        self.spin.valueChanged.connect(self._on_spin)

    def _configure_slider_range(self) -> None:
        steps = max(1, int(round((self._maximum - self._minimum) / self._step)))
        self.slider.setRange(0, steps)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(max(1, steps // 10))

    def _slider_to_value(self, tick: int) -> float:
        return round(self._minimum + tick * self._step, 6)

    def _value_to_slider(self, value: float) -> int:
        tick = int(round((float(value) - self._minimum) / self._step))
        return max(self.slider.minimum(), min(self.slider.maximum(), tick))

    def _on_slider(self, tick: int) -> None:
        if self._updating:
            return
        value = self._slider_to_value(tick)
        self._updating = True
        self.spin.setValue(value)
        self._updating = False
        self.valueChanged.emit(float(self.spin.value()))

    def _on_spin(self, value: float) -> None:
        if self._updating:
            return
        self._updating = True
        self.slider.setValue(self._value_to_slider(value))
        self._updating = False
        self.valueChanged.emit(float(value))

    def value(self) -> float:
        return float(self.spin.value())

    def setValue(self, value: float) -> None:  # noqa: N802
        self._updating = True
        self.spin.setValue(value)
        self.slider.setValue(self._value_to_slider(value))
        self._updating = False

    def setRange(self, minimum: float, maximum: float) -> None:  # noqa: N802
        self._minimum = float(minimum)
        self._maximum = float(maximum)
        self.spin.setRange(minimum, maximum)
        self._configure_slider_range()
        self.setValue(self.spin.value())

    def setSingleStep(self, step: float) -> None:  # noqa: N802
        self._step = float(step)
        self.spin.setSingleStep(step)
        self._configure_slider_range()
        self.setValue(self.spin.value())

    def setToolTip(self, tip: str) -> None:  # noqa: N802
        super().setToolTip(tip)
        self.slider.setToolTip(tip)
        self.spin.setToolTip(tip)
