from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from vectorizer.gui.canvas import ImageCanvas
from vectorizer.gui.main_window import MainWindow
from vectorizer.gui.theme import apply_theme
from vectorizer.jobs.runner import run_trace_sync
from vectorizer.domain.settings import ColorMode, PathFitMode, TraceSettings, WorkflowMode
from vectorizer.raster.loader import load_image
from vectorizer.resources import icon_path


@pytest.fixture(scope="module")
def qapp(tmp_path_factory) -> QApplication:
    from vectorizer.presets import set_presets_dir_override

    set_presets_dir_override(tmp_path_factory.mktemp("presets"))
    app = QApplication.instance()
    if app is None:
        app = QApplication(["vectorizer-tests"])
    assert isinstance(app, QApplication)
    apply_theme(app, dark=True)
    apply_theme(app, dark=False)
    return app


def test_main_window_smoke(qapp: QApplication, fixtures: dict[str, Path]) -> None:
    window = MainWindow()
    window.show()
    qapp.processEvents()
    assert window.isVisible()
    window.panel.set_settings(TraceSettings(workflow=WorkflowMode.BASIC))
    window.open_path(fixtures["mono_logo.png"])
    qapp.processEvents()
    assert window._loaded is not None
    assert window.preview_tabs.count() == 5
    assert window.seg_editor.has_map()
    assert window.undo_act is not None
    assert not window.undo_act.isEnabled()
    assert window.panel.width() == 420
    assert window.panel.minimumWidth() == window.panel.maximumWidth() == 420
    assert not window.windowIcon().isNull()
    assert not window.original_canvas.file_drop_enabled()
    window.close()


def test_empty_canvas_accepts_file_drop(qapp: QApplication) -> None:
    window = MainWindow()
    assert window._loaded is None
    assert window.original_canvas.file_drop_enabled()
    window.close()


def test_default_geometry_follows_golden_ratio(qapp: QApplication) -> None:
    from PySide6.QtCore import QSettings

    from vectorizer.gui.main_window import GOLDEN_RATIO

    # Even with a stale saved geometry, startup must use the designed default.
    store = QSettings("Vectorizer", "Vectorizer")
    store.setValue("ui/geometry", b"stale")
    store.sync()
    window = MainWindow()
    assert window._pending_default_geometry
    window.show()
    qapp.processEvents()
    assert not window._pending_default_geometry
    ratio = window.width() / max(window.height(), 1)
    assert abs(ratio - GOLDEN_RATIO) < 0.05, (window.width(), window.height(), ratio)
    window.close()
    assert store.value("ui/geometry") is None


def test_bundled_app_icon_files() -> None:
    assert icon_path("vectorizer.png").is_file()
    assert icon_path("vectorizer-256.png").is_file()
    assert icon_path("vectorizer.svg").is_file()


def test_session_undo_after_apply_result(qapp: QApplication, fixtures: dict[str, Path]) -> None:
    window = MainWindow()
    window.panel.set_settings(TraceSettings(workflow=WorkflowMode.BASIC))
    window.open_path(fixtures["mono_logo.png"])
    qapp.processEvents()
    image = load_image(fixtures["mono_logo.png"]).image
    result = run_trace_sync(
        image,
        TraceSettings(colormode=ColorMode.BINARY, mode=PathFitMode.POLYGON).validated(),
    )
    window._apply_result(result, rebuild_segmentation=False, history_label="Vectorize")
    qapp.processEvents()
    assert window.current_result() is not None
    assert window.undo_act.isEnabled()
    window.undo()
    qapp.processEvents()
    assert window.current_result() is None
    assert window.redo_act.isEnabled()
    window.redo()
    qapp.processEvents()
    assert window.current_result() is not None
    window.close()




def test_vector_canvas_renders_real_svg(qapp: QApplication, fixtures: dict[str, Path]) -> None:
    image = load_image(fixtures["mono_logo.png"]).image
    result = run_trace_sync(
        image,
        TraceSettings(colormode=ColorMode.BINARY, mode=PathFitMode.POLYGON).validated(),
    )
    canvas = ImageCanvas()
    canvas.show()
    qapp.processEvents()
    assert canvas.show_svg(result.document.raw_svg) is True
    assert canvas._svg_renderer is not None
    assert canvas._svg_renderer.isValid()
    canvas.close()
