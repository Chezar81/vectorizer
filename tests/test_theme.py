"""GTK theme colors follow the active Mint-Y controls theme."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from vectorizer.gui.theme import (
    ThemeColors,
    apply_theme,
    builtin_colors,
    colors_for_appearance,
    colors_from_css,
    read_system_colors,
)

AQUA = """
@define-color accent_color #1f9ede;
@define-color theme_selected_bg_color #1f9ede;
@define-color theme_selected_fg_color #FFFFFF;
@define-color theme_text_color #303030;
@define-color theme_bg_color #f8f8f9;
@define-color theme_base_color #FFFFFF;
@define-color borders #c8c8ce;
"""

DARK_RED = """
@define-color accent_color #e82127;
@define-color theme_selected_fg_color #FFFFFF;
@define-color theme_text_color #DADADA;
@define-color theme_bg_color #2e2e33;
@define-color theme_base_color #2E2E33;
@define-color borders #202023;
"""


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(["vectorizer-theme-tests"])
    assert isinstance(app, QApplication)
    return app


@pytest.fixture(autouse=True)
def _restore_builtin_theme(qapp: QApplication):
    yield
    apply_theme(qapp, dark=False)


def test_aqua_css_keeps_mint_accent_and_light_surfaces() -> None:
    colors = colors_from_css(AQUA)
    assert colors is not None
    assert colors.accent == "#1f9ede"
    assert colors.accent_hover == "#1d91cc"
    assert colors.accent_pressed == "#197eb1"
    assert colors.dark is False
    assert colors.bg == "#f8f8f9"
    assert colors.base == "#ffffff"
    assert colors.on_accent == "#ffffff"


def test_dark_variant_uses_dark_surfaces_and_its_accent() -> None:
    colors = colors_from_css(DARK_RED)
    assert colors is not None
    assert colors.dark is True
    assert colors.accent == "#e82127"
    assert colors.bg == "#2e2e33"
    assert colors.base != colors.bg
    assert colors.text == "#dadada"


def test_explicit_dark_flag_stays_on_the_builtin_palette(qapp: QApplication) -> None:
    apply_theme(qapp, dark=True)
    sheet = qapp.styleSheet()
    assert "#2e2e33" in sheet
    assert "#1f9ede" in sheet
    apply_theme(qapp, dark=False)
    assert "#f8f8f9" in qapp.styleSheet()


def test_apply_theme_paints_a_parsed_accent(qapp: QApplication) -> None:
    colors = colors_from_css(DARK_RED, font_family="Ubuntu", font_size=10)
    assert isinstance(colors, ThemeColors)
    apply_theme(qapp, colors=colors)
    sheet = qapp.styleSheet()
    assert "#e82127" in sheet
    assert 'font-family: "Ubuntu"' in sheet
    assert builtin_colors(False).accent == "#1f9ede"


def test_read_system_colors_uses_the_named_theme(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from vectorizer.gui import theme as theme_mod

    theme_dir = tmp_path / "Mint-Y-Purple" / "gtk-3.0"
    theme_dir.mkdir(parents=True)
    (theme_dir / "gtk.css").write_text(
        """
        @define-color accent_color #8c5dd9;
        @define-color theme_selected_fg_color #FFFFFF;
        @define-color theme_text_color #303030;
        @define-color theme_bg_color #f8f8f9;
        @define-color theme_base_color #FFFFFF;
        @define-color borders #c8c8ce;
        """,
        encoding="utf-8",
    )
    monkeypatch.delenv("GTK_THEME", raising=False)
    monkeypatch.setattr(theme_mod, "_gtk_theme_name", lambda: "Mint-Y-Purple")
    monkeypatch.setattr(theme_mod, "_prefers_dark_variant", lambda: False)
    monkeypatch.setattr(theme_mod, "_interface_font", lambda: ("Ubuntu", 11))
    monkeypatch.setattr(theme_mod, "_theme_search_roots", lambda: [tmp_path])

    colors = read_system_colors()
    assert colors.accent == "#8c5dd9"
    assert colors.dark is False
    assert colors.font_family == "Ubuntu"
    assert colors.font_size == 11


def test_dark_variant_file_is_used_when_requested(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from vectorizer.gui import theme as theme_mod

    theme_dir = tmp_path / "Mint-Y-Aqua" / "gtk-3.0"
    theme_dir.mkdir(parents=True)
    (theme_dir / "gtk.css").write_text(AQUA, encoding="utf-8")
    (theme_dir / "gtk-dark.css").write_text(DARK_RED, encoding="utf-8")
    monkeypatch.delenv("GTK_THEME", raising=False)
    monkeypatch.setattr(theme_mod, "_gtk_theme_name", lambda: "Mint-Y-Aqua:dark")
    monkeypatch.setattr(theme_mod, "_prefers_dark_variant", lambda: False)
    monkeypatch.setattr(theme_mod, "_interface_font", lambda: None)
    monkeypatch.setattr(theme_mod, "_theme_search_roots", lambda: [tmp_path])

    colors = read_system_colors()
    assert colors.dark is True
    assert colors.accent == "#e82127"


def test_light_and_dark_overrides_keep_the_system_accent(monkeypatch: pytest.MonkeyPatch) -> None:
    from vectorizer.gui import theme as theme_mod

    dark_red = colors_from_css(DARK_RED)
    assert dark_red is not None
    monkeypatch.setattr(theme_mod, "read_system_colors", lambda: dark_red)

    light = colors_for_appearance("light")
    assert light.dark is False
    assert light.accent == "#e82127"
    assert light.bg == "#f8f8f9"

    same_dark = colors_for_appearance("dark")
    assert same_dark == dark_red

    aqua = colors_from_css(AQUA)
    assert aqua is not None
    monkeypatch.setattr(theme_mod, "read_system_colors", lambda: aqua)
    forced_dark = colors_for_appearance("dark")
    assert forced_dark.dark is True
    assert forced_dark.accent == "#1f9ede"
    assert forced_dark.bg == "#2e2e33"
    assert colors_for_appearance("system") == aqua
    assert colors_for_appearance("nope") == aqua


class _MemorySettings:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def value(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)

    def setValue(self, key: str, value: object) -> None:
        self.values[key] = str(value)

    def sync(self) -> None:
        return None


def test_appearance_mode_defaults_to_system(monkeypatch: pytest.MonkeyPatch) -> None:
    from vectorizer.gui import theme as theme_mod
    from vectorizer.gui.theme import appearance_mode, set_appearance_mode

    store = _MemorySettings()
    monkeypatch.setattr(theme_mod, "_appearance_settings", lambda: store)
    assert appearance_mode() == "system"
    assert set_appearance_mode("dark") == "dark"
    assert appearance_mode() == "dark"
    assert set_appearance_mode("light") == "light"
    assert appearance_mode() == "light"
    assert set_appearance_mode("nope") == "system"
    assert appearance_mode() == "system"


def test_missing_theme_falls_back_to_aqua(monkeypatch: pytest.MonkeyPatch) -> None:
    from vectorizer.gui import theme as theme_mod

    monkeypatch.delenv("GTK_THEME", raising=False)
    monkeypatch.setattr(theme_mod, "_gtk_theme_name", lambda: "Not-A-Real-Theme")
    monkeypatch.setattr(theme_mod, "_prefers_dark_variant", lambda: False)
    monkeypatch.setattr(theme_mod, "_interface_font", lambda: None)
    monkeypatch.setattr(theme_mod, "_theme_search_roots", lambda: [])

    colors = read_system_colors()
    assert colors == builtin_colors(False)


@pytest.mark.skipif(
    not Path("/usr/share/themes/Mint-Y-Aqua/gtk-3.0/gtk.css").is_file(),
    reason="Mint-Y themes are not installed",
)
def test_installed_mint_themes_expose_their_accents() -> None:
    aqua = colors_from_css(
        Path("/usr/share/themes/Mint-Y-Aqua/gtk-3.0/gtk.css").read_text(encoding="utf-8", errors="replace")
    )
    red = colors_from_css(
        Path("/usr/share/themes/Mint-Y-Red/gtk-3.0/gtk.css").read_text(encoding="utf-8", errors="replace")
    )
    dark = colors_from_css(
        Path("/usr/share/themes/Mint-Y-Dark-Aqua/gtk-3.0/gtk.css").read_text(
            encoding="utf-8", errors="replace"
        )
    )
    assert aqua is not None and aqua.accent == "#1f9ede" and aqua.dark is False
    assert red is not None and red.accent == "#e82127" and red.dark is False
    assert dark is not None and dark.accent == "#1f9ede" and dark.dark is True
