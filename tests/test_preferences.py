from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from vectorizer.batch.engine import CollisionPolicy, ExportFormat
from vectorizer.domain.settings import AutomaticQuality, WorkflowMode
from vectorizer.export.tools import find_inkscape, set_inkscape_override
from vectorizer.gui.preferences import (
    AppPreferences,
    current_preferences,
    load_preferences,
    reset_all_preferences,
    save_preferences,
)


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(["vectorizer-prefs-tests"])
    assert isinstance(app, QApplication)
    return app


@pytest.fixture()
def isolated_prefs(tmp_path, monkeypatch, qapp: QApplication):
    ini = str(tmp_path / "prefs.ini")

    def _store() -> QSettings:
        return QSettings(ini, QSettings.Format.IniFormat)

    monkeypatch.setattr("vectorizer.gui.preferences._store", _store)
    set_inkscape_override(None)
    prefs = save_preferences(AppPreferences(), emit=False)
    yield prefs
    set_inkscape_override(None)


def test_preferences_roundtrip(isolated_prefs) -> None:
    saved = save_preferences(
        AppPreferences(
            workflow=WorkflowMode.BASIC,
            automatic_quality=AutomaticQuality.HIGH,
            export_dir="/tmp/out",
            export_svg=True,
            export_pdf=True,
            export_png=False,
            export_dxf=True,
            export_eps=False,
            batch_collision=CollisionPolicy.SKIP,
            batch_continue_on_error=False,
            batch_input_dir="/tmp/in",
            batch_output_dir="/tmp/out",
            confirm_overwrite=False,
            last_preset="Logo",
            inkscape_path="",
            png_width=800,
            png_height=600,
            png_background="#ffffff",
            session_history_steps=12,
            segmentation_history_steps=20,
            segmentation_history_mib=32,
        )
    )
    assert saved.workflow == WorkflowMode.BASIC
    assert ExportFormat.PDF in saved.export_formats()
    assert ExportFormat.DXF in saved.export_formats()

    # Simulate restart: drift in-memory state, then reload from store.
    from vectorizer.gui import preferences as prefs_mod

    prefs_mod._current = AppPreferences().validated()
    restored = load_preferences()
    assert restored.workflow == WorkflowMode.BASIC
    assert restored.automatic_quality == AutomaticQuality.HIGH
    assert restored.export_dir == "/tmp/out"
    assert restored.export_pdf is True
    assert restored.batch_collision == CollisionPolicy.SKIP
    assert restored.confirm_overwrite is False
    assert restored.last_preset == "Logo"
    assert restored.png_width == 800
    assert restored.session_history_steps == 12


def test_reset_all_preferences(isolated_prefs) -> None:
    save_preferences(
        AppPreferences(
            workflow=WorkflowMode.ADVANCED,
            confirm_overwrite=False,
            export_pdf=True,
        )
    )
    reset = reset_all_preferences(include_ui=False)
    assert reset.workflow == WorkflowMode.AUTOMATIC
    assert reset.confirm_overwrite is True
    assert reset.export_pdf is False
    assert current_preferences().workflow == WorkflowMode.AUTOMATIC


def test_inkscape_override_missing_path(isolated_prefs) -> None:
    set_inkscape_override("/definitely/not/inkscape-binary")
    tool = find_inkscape()
    assert tool.available is False
    assert "Configured Inkscape path" in tool.notes
    set_inkscape_override(None)


def test_main_window_prefs_menu(qapp: QApplication, tmp_path_factory, monkeypatch) -> None:
    from vectorizer.gui.main_window import MainWindow
    from vectorizer.gui import preferences as prefs_mod
    from vectorizer.presets import set_presets_dir_override

    ini = str(tmp_path_factory.mktemp("mw-prefs") / "ui.ini")

    def _store() -> QSettings:
        return QSettings(ini, QSettings.Format.IniFormat)

    monkeypatch.setattr(prefs_mod, "_store", _store)
    set_presets_dir_override(tmp_path_factory.mktemp("presets-prefs"))
    save_preferences(
        AppPreferences(
            workflow=WorkflowMode.BASIC,
            automatic_quality=AutomaticQuality.FAST,
        ),
        emit=False,
    )
    window = MainWindow()
    assert window.panel.settings().workflow == WorkflowMode.BASIC
    assert window.panel.settings().automatic_quality == AutomaticQuality.FAST
    assert window.prefs_act is not None
    assert window.reset_prefs_act is not None
    window.close()
