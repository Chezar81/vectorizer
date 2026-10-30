"""Application bootstrap."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from vectorizer.gui.i18n import load_language
from vectorizer.gui.main_window import MainWindow, _load_app_icon
from vectorizer.gui.preferences import load_preferences
from vectorizer.gui.theme import apply_appearance, watch_system_theme


def run_app(argv: list[str] | None = None, *, initial_image: Path | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    app = QApplication.instance()
    owns_app = app is None
    if owns_app:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        app = QApplication(args)
        app.setApplicationName("Vectorizer")
        app.setOrganizationName("Vectorizer")
        app.setApplicationDisplayName("Vectorizer")
        app.setDesktopFileName("vectorizer")
    assert isinstance(app, QApplication)
    icon = _load_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    load_language()
    load_preferences()
    apply_appearance(app)
    watch_system_theme(app)
    window = MainWindow()
    window.show()
    if initial_image is not None:
        window.open_path(initial_image)
    if owns_app:
        return app.exec()
    return 0
