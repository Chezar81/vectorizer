from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from vectorizer.gui.slider_spin import DoubleSliderSpin, IntSliderSpin


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(["slider-spin-tests"])
    assert isinstance(app, QApplication)
    return app


def test_int_slider_spin_sync(qapp: QApplication) -> None:
    w = IntSliderSpin(0, 10)
    seen: list[int] = []
    w.valueChanged.connect(seen.append)
    w.setValue(7)
    assert w.value() == 7
    assert w.slider.value() == 7
    w.slider.setValue(3)
    assert w.value() == 3
    assert seen[-1] == 3
    w.spin.setValue(9)
    assert w.slider.value() == 9
    w.close()


def test_double_slider_spin_sync(qapp: QApplication) -> None:
    w = DoubleSliderSpin(3.5, 10.0, step=0.1, decimals=2)
    w.setValue(4.0)
    assert abs(w.value() - 4.0) < 1e-6
    w.slider.setValue(w.slider.maximum())
    assert abs(w.value() - 10.0) < 1e-6
    w.spin.setValue(5.5)
    assert w.slider.value() == w._value_to_slider(5.5)
    w.close()
