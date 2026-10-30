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
    PreferencesFileError,
    current_preferences,
    load_preferences,
    read_preferences_file,
    reset_all_preferences,
    save_preferences,
    write_preferences_file,
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


def test_preferences_file_roundtrip(isolated_prefs, tmp_path) -> None:
    save_preferences(
        AppPreferences(
            workflow=WorkflowMode.ADVANCED,
            automatic_quality=AutomaticQuality.FAST,
            export_dir="/tmp/exports",
            export_pdf=True,
            export_dxf=True,
            batch_collision=CollisionPolicy.OVERWRITE,
            batch_continue_on_error=False,
            confirm_overwrite=False,
            last_preset="Logo",
            png_width=640,
            png_height=480,
            png_background="#000000",
            session_history_steps=15,
            segmentation_history_steps=9,
            segmentation_history_mib=64,
        )
    )
    dest = tmp_path / "profiles" / "studio.json"
    write_preferences_file(dest)
    assert dest.is_file()
    assert not dest.with_name(dest.name + ".tmp").exists()
    payload = dest.read_text(encoding="utf-8")
    assert '"kind": "vectorizer-preferences"' in payload

    save_preferences(AppPreferences(), emit=False)
    restored = read_preferences_file(dest)
    assert restored.workflow == WorkflowMode.ADVANCED
    assert restored.automatic_quality == AutomaticQuality.FAST
    assert restored.export_dir == "/tmp/exports"
    assert restored.export_pdf is True
    assert restored.export_dxf is True
    assert restored.batch_collision == CollisionPolicy.OVERWRITE
    assert restored.confirm_overwrite is False
    assert restored.last_preset == "Logo"
    assert restored.png_background == "#000000"
    assert restored.session_history_steps == 15
    assert restored.segmentation_history_mib == 64
    assert current_preferences().png_width == 640

    reloaded = load_preferences()
    assert reloaded.png_height == 480
    assert reloaded.batch_continue_on_error is False


def test_preferences_file_ignores_unknown_fields_and_rejects_foreign(isolated_prefs, tmp_path) -> None:
    import json

    future = tmp_path / "future.json"
    future.write_text(
        json.dumps(
            {
                "schema": "1",
                "kind": "vectorizer-preferences",
                "preferences": {
                    "workflow": "basic",
                    "png_width": 99999,
                    "not_a_real_field": True,
                },
            }
        ),
        encoding="utf-8",
    )
    loaded = read_preferences_file(future)
    assert loaded.workflow == WorkflowMode.BASIC
    assert loaded.png_width == 16000
    assert loaded.export_svg is True
    assert loaded.confirm_overwrite is True

    foreign = tmp_path / "preset.json"
    foreign.write_text(
        json.dumps({"schema": 1, "name": "Logo", "settings": {}}),
        encoding="utf-8",
    )
    with pytest.raises(PreferencesFileError, match="not a Vectorizer preferences file"):
        read_preferences_file(foreign)

    newer = tmp_path / "newer.json"
    newer.write_text(
        json.dumps(
            {"schema": 99, "kind": "vectorizer-preferences", "preferences": {}}
        ),
        encoding="utf-8",
    )
    with pytest.raises(PreferencesFileError, match="schema"):
        read_preferences_file(newer)

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{", encoding="utf-8")
    with pytest.raises(PreferencesFileError, match="corrupt"):
        read_preferences_file(corrupt)

    with pytest.raises(PreferencesFileError, match="Could not read"):
        read_preferences_file(tmp_path / "missing.json")


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
    assert not hasattr(window, "reset_prefs_act")
    assert not hasattr(window, "save_prefs_act")
    assert not hasattr(window, "load_prefs_act")
    window.close()


def test_preferences_dialog_save_and_load_shows_form(
    isolated_prefs, tmp_path, monkeypatch
) -> None:
    import json

    from PySide6.QtWidgets import QFileDialog

    from vectorizer.gui.i18n import LANG_EN, set_language
    from vectorizer.gui.preferences_dialog import PreferencesDialog
    from vectorizer.presets import set_presets_dir_override

    set_language(LANG_EN, persist=False)
    set_presets_dir_override(tmp_path / "presets")
    save_preferences(
        AppPreferences(workflow=WorkflowMode.BASIC, export_pdf=False, session_history_steps=12),
        emit=False,
    )
    dialog = PreferencesDialog()
    assert dialog.session_steps.value() == 12
    assert dialog.fmt_pdf.isChecked() is False

    dialog.fmt_pdf.setChecked(True)
    dialog.session_steps.setValue(22)
    dialog.export_dir.setText("/tmp/shown-exports")
    dest = tmp_path / "shown.json"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(dest), ""),
    )
    dialog._save_to_file()
    assert dest.is_file()
    assert current_preferences().export_pdf is False
    assert current_preferences().session_history_steps == 12
    written = json.loads(dest.read_text(encoding="utf-8"))
    assert written["preferences"]["export_pdf"] is True
    assert written["preferences"]["session_history_steps"] == 22
    assert written["preferences"]["export_dir"] == "/tmp/shown-exports"
    assert "shown.json" in dialog._file_status.text()

    dialog.fmt_pdf.setChecked(False)
    dialog.session_steps.setValue(40)
    assert dialog._file_status.text() == ""
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(dest), ""),
    )
    dialog._load_from_file()
    assert dialog.fmt_pdf.isChecked() is True
    assert dialog.session_steps.value() == 22
    assert dialog.export_dir.text() == "/tmp/shown-exports"
    assert "Press OK to apply" in dialog._file_status.text()
    assert current_preferences().export_pdf is False

    dialog._accept()
    assert current_preferences().export_pdf is True
    assert current_preferences().session_history_steps == 22
    assert current_preferences().workflow == WorkflowMode.BASIC
    dialog.close()


def test_preferences_dialog_reset_shows_defaults(
    isolated_prefs, tmp_path, monkeypatch
) -> None:
    from PySide6.QtWidgets import QDialogButtonBox, QMessageBox

    from vectorizer.gui.i18n import LANG_EN, set_language
    from vectorizer.gui.preferences_dialog import PreferencesDialog
    from vectorizer.presets import set_presets_dir_override

    set_language(LANG_EN, persist=False)
    set_presets_dir_override(tmp_path / "presets")
    save_preferences(
        AppPreferences(
            workflow=WorkflowMode.ADVANCED,
            export_pdf=True,
            session_history_steps=22,
            confirm_overwrite=False,
        ),
        emit=False,
    )
    dialog = PreferencesDialog()
    dialog.show()
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    assert app is not None
    app.processEvents()

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )
    dialog._reset_to_defaults()
    assert dialog.session_steps.value() == 22
    assert dialog.fmt_pdf.isChecked() is True
    assert dialog.chrome_reset_requested is False

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    dialog._reset_to_defaults()
    defaults = AppPreferences()
    assert dialog.session_steps.value() == defaults.session_history_steps
    assert dialog.fmt_pdf.isChecked() is False
    assert dialog.confirm_overwrite.isChecked() is True
    assert dialog.workflow.currentData() == WorkflowMode.AUTOMATIC
    assert dialog.chrome_reset_requested is True
    assert "Press OK to apply" in dialog._file_status.text()
    assert current_preferences().export_pdf is True
    assert current_preferences().session_history_steps == 22

    buttons = [
        dialog.save_file_btn,
        dialog.load_file_btn,
        dialog.reset_btn,
        dialog._buttons.button(QDialogButtonBox.StandardButton.Cancel),
        dialog._buttons.button(QDialogButtonBox.StandardButton.Ok),
    ]
    assert all(button is not None for button in buttons)
    origins = [button.mapTo(dialog, button.rect().topLeft()) for button in buttons]
    assert max(point.y() for point in origins) - min(point.y() for point in origins) <= 4
    custom_xs = [point.x() for point in origins[:3]]
    assert custom_xs == sorted(custom_xs)
    assert custom_xs[0] <= 24
    reset_right = origins[2].x() + dialog.reset_btn.width()
    standard_left = min(point.x() for point in origins[3:])
    standard_right = max(
        point.x() + button.width() for point, button in zip(origins[3:], buttons[3:])
    )
    assert standard_left - reset_right > dialog.width() * 0.25
    assert standard_right > dialog.width() - 40

    dialog._accept()
    assert current_preferences().export_pdf is False
    assert current_preferences().workflow == WorkflowMode.AUTOMATIC
    assert current_preferences().session_history_steps == defaults.session_history_steps
    dialog.close()
