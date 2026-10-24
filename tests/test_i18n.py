from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from vectorizer.gui.i18n import (
    LANG_DE,
    LANG_EN,
    current_language,
    load_language,
    set_language,
    t,
)


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(["vectorizer-i18n-tests"])
    assert isinstance(app, QApplication)
    return app


def test_translate_switches_and_falls_back(qapp: QApplication) -> None:
    set_language(LANG_EN, persist=False)
    assert t("&File") == "&File"
    set_language(LANG_DE, persist=False)
    assert t("&File") == "&Datei"
    assert t("Unknown string xyz") == "Unknown string xyz"
    set_language(LANG_EN, persist=False)


def test_language_persists_across_load(qapp: QApplication, tmp_path, monkeypatch) -> None:
    from vectorizer.gui import i18n as i18n_mod

    ini = str(tmp_path / "vectorizer-ui.ini")

    def _isolated_settings() -> QSettings:
        return QSettings(ini, QSettings.Format.IniFormat)

    monkeypatch.setattr(i18n_mod, "_ui_settings", _isolated_settings)
    set_language(LANG_DE, persist=True)
    set_language(LANG_EN, persist=False)  # in-memory only
    assert current_language() == LANG_EN
    restored = load_language()
    assert restored == LANG_DE
    assert current_language() == LANG_DE
    assert t("Vectorize") == "Vektorisieren"
    set_language(LANG_EN, persist=True)


def test_main_window_language_switch(qapp: QApplication, tmp_path_factory) -> None:
    from vectorizer.gui.main_window import MainWindow
    from vectorizer.presets import set_presets_dir_override

    set_presets_dir_override(tmp_path_factory.mktemp("presets-i18n"))
    set_language(LANG_EN, persist=False)
    window = MainWindow()
    assert window.panel.vectorize_btn.text() == "Vectorize"
    assert window._settings_menu.title() == "&Settings"
    assert any(a.menu() is window.language_menu for a in window._settings_menu.actions())
    assert not any(a.menu() is window.language_menu for a in window._view_menu.actions())
    window._set_ui_language(LANG_DE)
    assert window._file_menu.title() == "&Datei"
    assert window._settings_menu.title() == "&Einstellungen"
    assert window.language_menu.title() == "&Sprache"
    assert window.panel.vectorize_btn.text() == "Vektorisieren"
    assert window.preview_tabs.tabText(4) == "Segmentierung"
    window._set_ui_language(LANG_EN)
    assert window.panel.vectorize_btn.text() == "Vectorize"
    window.close()
