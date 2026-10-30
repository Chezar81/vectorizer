"""Fusion theme that follows the active Linux Mint / GTK controls theme.

Mint-Y light, Mint-Y dark, and each accent (Aqua, Red, …) live in the GTK
theme named by ``org.cinnamon.desktop.interface gtk-theme``. Colors are read
from that theme's ``gtk.css``. If the desktop theme cannot be read, the
built-in Mint-Y-Aqua palette is used.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QSettings, QTimer
from PySide6.QtGui import QColor, QFont, QFontInfo, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

# Colors taken from /usr/share/themes/Mint-Y-Aqua/gtk-3.0/gtk.css
MINT_ACCENT = "#1f9ede"
MINT_ACCENT_HOVER = "#1d91cc"
MINT_ACCENT_PRESSED = "#197eb1"
MINT_BG = "#f8f8f9"
MINT_BASE = "#ffffff"
MINT_PANEL = "#f0f0f2"
MINT_BORDER = "#c8c8ce"
MINT_BORDER_SOFT = "#dedee1"
MINT_TEXT = "#212121"
MINT_MUTED = "#6f6f6f"
MINT_DARK_BG = "#2e2e33"
MINT_DARK_PANEL = "#3a3a40"
MINT_DARK_BASE = "#242428"
MINT_DARK_TEXT = "#dadada"
MINT_DARK_MUTED = "#adadb5"
MINT_DARK_BORDER = "#46464e"

_DEFINE_RE = re.compile(
    r"@define-color\s+([A-Za-z0-9_]+)\s+([^;]+);",
    re.IGNORECASE,
)
_HEX_RE = re.compile(r"#([0-9a-fA-F]{3,8})\b")
_RGB_RE = re.compile(
    r"rgba?\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)",
    re.IGNORECASE,
)
_NAMED = {"white": (255, 255, 255), "black": (0, 0, 0)}
# Separations taken from Mint-Y-Aqua so a parsed theme keeps the same rhythm.
_PANEL_MIX = 0.032
_PANEL_MIX_DARK = 0.06
_BORDER_SOFT_MIX = 0.45
_MUTED_MIX = 0.32
_HOVER_KEEP = 0.92
_PRESSED_KEEP = 0.797
_applied_signature: tuple[object, ...] | None = None
_watch_enabled = False

APPEARANCE_SYSTEM = "system"
APPEARANCE_LIGHT = "light"
APPEARANCE_DARK = "dark"
_APPEARANCE_KEY = "ui/appearance"
_APPEARANCE_MODES = {APPEARANCE_SYSTEM, APPEARANCE_LIGHT, APPEARANCE_DARK}


@dataclass(frozen=True)
class ThemeColors:
    """Colors and interface font for one paint of the application."""

    dark: bool
    accent: str
    accent_hover: str
    accent_pressed: str
    bg: str
    panel: str
    base: str
    text: str
    muted: str
    border: str
    border_soft: str
    on_accent: str
    font_family: str | None = None
    font_size: int = 10

    def signature(self) -> tuple[object, ...]:
        return (
            self.dark,
            self.accent,
            self.accent_hover,
            self.accent_pressed,
            self.bg,
            self.panel,
            self.base,
            self.text,
            self.muted,
            self.border,
            self.border_soft,
            self.on_accent,
            self.font_family,
            self.font_size,
        )


def builtin_colors(dark: bool) -> ThemeColors:
    """Mint-Y-Aqua palette used when the desktop theme cannot be read."""
    if dark:
        bg, panel, base, text, muted, border = (
            MINT_DARK_BG,
            MINT_DARK_PANEL,
            MINT_DARK_BASE,
            MINT_DARK_TEXT,
            MINT_DARK_MUTED,
            MINT_DARK_BORDER,
        )
        border_soft = border
    else:
        bg, panel, base, text, muted, border = (
            MINT_BG,
            MINT_PANEL,
            MINT_BASE,
            MINT_TEXT,
            MINT_MUTED,
            MINT_BORDER,
        )
        border_soft = MINT_BORDER_SOFT
    return ThemeColors(
        dark=dark,
        accent=MINT_ACCENT,
        accent_hover=MINT_ACCENT_HOVER,
        accent_pressed=MINT_ACCENT_PRESSED,
        bg=bg,
        panel=panel,
        base=base,
        text=text,
        muted=muted,
        border=border,
        border_soft=border_soft,
        on_accent="#ffffff",
    )


def colors_from_css(
    text: str,
    *,
    font_family: str | None = None,
    font_size: int = 10,
) -> ThemeColors | None:
    """Build a palette from GTK ``@define-color`` rules. ``None`` if too little is defined."""
    defined = _css_color_map(text)
    accent = defined.get("accent_color") or defined.get("theme_selected_bg_color")
    bg = defined.get("theme_bg_color") or defined.get("bg_color")
    if accent is None or bg is None:
        return None
    base = defined.get("theme_base_color") or defined.get("base_color") or bg
    text_rgb = (
        defined.get("theme_text_color")
        or defined.get("text_color")
        or defined.get("theme_fg_color")
        or ((255, 255, 255) if _is_dark(bg) else (33, 33, 33))
    )
    border = defined.get("borders") or _mix(bg, text_rgb, 0.22)
    on_accent = defined.get("theme_selected_fg_color") or defined.get("selected_fg_color")
    dark = _is_dark(bg)
    if on_accent is None:
        on_accent = (33, 33, 33) if _luminance(accent) > 0.55 else (255, 255, 255)
    if _max_channel_delta(bg, base) < 6:
        base = _mix(bg, (0, 0, 0), 0.22) if dark else _mix(bg, (255, 255, 255), 0.35)
    panel_toward = (255, 255, 255) if dark else (0, 0, 0)
    panel = _mix(bg, panel_toward, _PANEL_MIX_DARK if dark else _PANEL_MIX)
    muted = _mix(text_rgb, bg, _MUTED_MIX)
    border_soft = border if dark else _mix(border, bg, _BORDER_SOFT_MIX)
    return ThemeColors(
        dark=dark,
        accent=_rgb_to_hex(accent),
        accent_hover=_rgb_to_hex(_darken(accent, _HOVER_KEEP)),
        accent_pressed=_rgb_to_hex(_darken(accent, _PRESSED_KEEP)),
        bg=_rgb_to_hex(bg),
        panel=_rgb_to_hex(panel),
        base=_rgb_to_hex(base),
        text=_rgb_to_hex(text_rgb),
        muted=_rgb_to_hex(muted),
        border=_rgb_to_hex(border),
        border_soft=_rgb_to_hex(border_soft),
        on_accent=_rgb_to_hex(on_accent),
        font_family=font_family,
        font_size=font_size,
    )


def read_system_colors() -> ThemeColors:
    """Colors of the active GTK controls theme, or Mint-Y-Aqua if that cannot be read."""
    theme_name, variant_dark = _split_theme_name(_gtk_theme_name())
    css = _load_theme_css(theme_name, variant_dark=variant_dark) if theme_name else None
    font = _interface_font()
    family = font[0] if font else None
    size = font[1] if font else 10
    if css:
        parsed = colors_from_css(css, font_family=family, font_size=size)
        if parsed is not None:
            return parsed
    fallback = builtin_colors(variant_dark or _prefers_dark_variant())
    if family:
        return replace(fallback, font_family=family, font_size=size)
    return fallback


def mint_stylesheet(colors: ThemeColors) -> str:
    dark = colors.dark
    bg = colors.bg
    panel = colors.panel
    base = colors.base
    text = colors.text
    muted = colors.muted
    border = colors.border
    border_soft = colors.border_soft
    accent = colors.accent
    accent_hover = colors.accent_hover
    accent_pressed = colors.accent_pressed
    on_accent = colors.on_accent
    font_px = max(11, int(round(colors.font_size * 4 / 3)))
    family_rule = ""
    if colors.font_family:
        family = colors.font_family.replace("\\", "").replace('"', "")
        family_rule = f'font-family: "{family}";'
    return f"""
    QWidget {{
        background-color: {bg};
        color: {text};
        {family_rule}
        font-size: {font_px}px;
    }}
    QLabel, QCheckBox, QRadioButton {{
        background: transparent;
    }}
    QMainWindow, QDialog {{
        background-color: {bg};
    }}
    QMenuBar {{
        background-color: {bg};
        border-bottom: 1px solid {border};
        padding: 2px 4px;
        spacing: 2px;
    }}
    QMenuBar::item {{
        background: transparent;
        padding: 4px 10px;
        border-radius: 4px;
    }}
    QMenuBar::item:selected {{
        background: {accent};
        color: {on_accent};
    }}
    QMenu {{
        background-color: {base};
        border: 1px solid {border};
        border-radius: 6px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 24px 6px 12px;
        border-radius: 4px;
    }}
    QMenu::item:selected {{
        background-color: {accent};
        color: {on_accent};
    }}
    QToolBar {{
        background-color: {bg};
        border-bottom: 1px solid {border};
        spacing: 6px;
        padding: 6px 8px;
    }}
    QToolButton {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 6px;
        padding: 5px 10px;
        color: {text};
    }}
    QToolButton:hover {{
        background: {panel};
        border-color: {border};
    }}
    QToolButton:pressed, QToolButton:checked {{
        background: {accent};
        color: {on_accent};
        border-color: {accent_pressed};
    }}
    QToolButton#primaryTool {{
        background-color: {accent};
        color: {on_accent};
        border-color: {accent_hover};
        font-weight: 600;
        padding: 5px 14px;
    }}
    QToolButton#primaryTool:hover {{
        background-color: {accent_hover};
        color: {on_accent};
    }}
    QToolButton#primaryTool:pressed {{
        background-color: {accent_pressed};
        color: {on_accent};
    }}
    QToolButton#primaryTool:disabled {{
        background: {panel};
        color: {muted};
        border-color: {border};
    }}
    QStatusBar {{
        background-color: {bg};
        border-top: 1px solid {border};
        color: {muted};
    }}
    QTabWidget::pane {{
        border: 1px solid {border};
        border-radius: 6px;
        background: {base};
        top: -1px;
    }}
    QTabBar::tab {{
        background: {panel};
        color: {text};
        border: 1px solid {border};
        border-bottom: none;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        padding: 7px 14px;
        margin-right: 2px;
    }}
    QTabBar::tab:selected {{
        background: {base};
        color: {accent};
        font-weight: 600;
        border-bottom: 2px solid {accent};
    }}
    QTabBar::tab:hover:!selected {{
        background: {border_soft if not dark else border};
    }}
    QGroupBox {{
        background: {base};
        border: 1px solid {border};
        border-radius: 8px;
        margin-top: 12px;
        /* Title sits inside the card, clear of the border and of the first control. */
        padding: 40px 14px 14px 14px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: padding;
        subcontrol-position: top left;
        left: 14px;
        top: 12px;
        padding: 0 0 8px 0;
        color: {text};
        background: transparent;
    }}
    QGroupBox QLabel, QGroupBox QCheckBox, QGroupBox QPushButton,
    QGroupBox QComboBox, QGroupBox QSpinBox, QGroupBox QDoubleSpinBox,
    QGroupBox QListWidget, QGroupBox QSlider, QGroupBox QToolButton {{
        font-weight: 400;
    }}
    QPushButton {{
        background-color: {base};
        border: 1px solid {border};
        border-radius: 6px;
        padding: 7px 14px;
        min-height: 20px;
    }}
    QPushButton:hover {{
        background-color: {panel};
        border-color: {accent_hover};
    }}
    QPushButton:pressed {{
        background-color: {accent_pressed};
        color: {on_accent};
        border-color: {accent_pressed};
    }}
    QPushButton:disabled {{
        color: {muted};
        background: {panel};
    }}
    QPushButton#primaryButton, QPushButton[default="true"] {{
        background-color: {accent};
        color: {on_accent};
        border-color: {accent_hover};
        font-weight: 600;
    }}
    QPushButton#primaryButton:hover, QPushButton[default="true"]:hover {{
        background-color: {accent_hover};
    }}
    QPushButton#primaryButton:pressed, QPushButton[default="true"]:pressed {{
        background-color: {accent_pressed};
    }}
    QPushButton#primaryButton:disabled, QPushButton[default="true"]:disabled {{
        background: {panel};
        color: {muted};
        border-color: {border};
    }}
    QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
        background: {base};
        border: 1px solid {border};
        border-radius: 6px;
        padding: 4px 8px;
        min-height: 24px;
        selection-background-color: {accent};
        selection-color: {on_accent};
    }}
    QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover,
    QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {{
        border-color: {accent};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox QAbstractItemView {{
        background: {base};
        border: 1px solid {border};
        selection-background-color: {accent};
        selection-color: {on_accent};
        outline: 0;
    }}
    QSlider::groove:horizontal {{
        height: 6px;
        background: {border};
        border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: {accent};
        width: 16px;
        height: 16px;
        margin: -5px 0;
        border-radius: 8px;
    }}
    QSlider::sub-page:horizontal {{
        background: {accent};
        border-radius: 3px;
    }}
    QProgressBar {{
        border: 1px solid {border};
        border-radius: 6px;
        background: {panel};
        text-align: center;
        color: {text};
        min-height: 14px;
    }}
    QProgressBar::chunk {{
        background-color: {accent};
        border-radius: 5px;
    }}
    QScrollBar:vertical {{
        background: {bg};
        width: 12px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {border};
        border-radius: 5px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {accent};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
        height: 0;
    }}
    QSplitter::handle {{
        background: {border};
        width: 1px;
    }}
    QLabel#analysisNotes {{
        color: {muted};
        background: {panel};
        border: 1px solid {border};
        border-radius: 6px;
        padding: 8px;
    }}
    QListWidget {{
        background: {base};
        border: 1px solid {border};
        border-radius: 6px;
        outline: 0;
    }}
    QListWidget::item {{
        padding: 2px 4px;
        border-radius: 6px;
    }}
    QListWidget::item:selected {{
        background: {accent};
        color: {on_accent};
    }}
    QListWidget#paletteList::item {{
        background: transparent;
        padding: 1px 2px;
    }}
    QListWidget#paletteList::item:selected {{
        background: transparent;
        border: 2px solid {accent};
        border-radius: 8px;
    }}
    QListWidget#paletteList::item:hover {{
        background: transparent;
    }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {border};
        border-radius: 3px;
        background: {base};
    }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        background: {accent};
        border-color: {accent_hover};
    }}
    QWidget#sidePanel {{
        background: {panel};
        border-right: 1px solid {border};
    }}
    QFrame#actionBar {{
        background: {bg};
        border-top: 1px solid {border};
    }}
    QLabel#inlineHint, QLabel#previewCaption {{
        color: {muted};
        background: transparent;
        font-size: 12px;
    }}
    QLabel#previewCaption {{
        padding: 6px 8px 2px 8px;
    }}
    QLabel#modeBanner {{
        background: {accent};
        color: {on_accent};
        padding: 8px 14px;
        font-weight: 600;
    }}
    QFrame#welcomeCard {{
        background: {base};
        border: 1px solid {border};
        border-radius: 16px;
    }}
    QFrame#welcomeCard[drag="true"] {{
        border: 2px solid {accent};
    }}
    QWidget#welcomeRow, QWidget#optionBlock {{
        background: transparent;
    }}
    QLabel#welcomeTitle {{
        font-size: 22px;
        font-weight: 600;
        background: transparent;
    }}
    QLabel#welcomeLead, QLabel#welcomeFormats {{
        color: {muted};
        background: transparent;
    }}
    QLabel#welcomeLead {{
        font-size: 14px;
    }}
    QLabel#welcomeStep {{
        background: transparent;
        font-size: 13px;
    }}
    QLabel#stepIndex {{
        background: {accent};
        color: {on_accent};
        border-radius: 11px;
        font-weight: 600;
        min-width: 22px;
        max-width: 22px;
        min-height: 22px;
        max-height: 22px;
    }}
    QFrame#segTools {{
        background: {panel};
        border-bottom: 1px solid {border};
    }}
    QFrame#segTools QToolButton {{
        padding: 6px 12px;
        border-radius: 6px;
    }}
    QFrame#segTools QToolButton:checked {{
        background: {accent};
        color: {on_accent};
        border-color: {accent};
        font-weight: 600;
    }}
    QGraphicsView {{
        background: {base};
        border: none;
    }}
    """


def apply_theme(
    app: QApplication,
    dark: bool | None = None,
    *,
    colors: ThemeColors | None = None,
) -> None:
    """Paint `app`. An explicit `dark` flag uses the built-in Aqua palette."""
    global _applied_signature
    if colors is None:
        colors = builtin_colors(bool(dark)) if dark is not None else read_system_colors()
    _applied_signature = colors.signature()
    app.setStyle(QStyleFactory.create("Fusion"))
    _apply_font(app, colors)

    palette = QPalette()
    bg = QColor(colors.bg)
    panel = QColor(colors.panel)
    base = QColor(colors.base)
    text = QColor(colors.text)
    accent = QColor(colors.accent)
    on_accent = QColor(colors.on_accent)
    palette.setColor(QPalette.ColorRole.Window, bg)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, base)
    palette.setColor(QPalette.ColorRole.AlternateBase, panel)
    palette.setColor(QPalette.ColorRole.ToolTipBase, panel)
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, panel)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#FC4138"))
    palette.setColor(QPalette.ColorRole.Highlight, accent)
    palette.setColor(QPalette.ColorRole.HighlightedText, on_accent)
    palette.setColor(QPalette.ColorRole.Link, accent)
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(colors.muted))
    app.setPalette(palette)
    app.setStyleSheet(mint_stylesheet(colors))


def appearance_mode() -> str:
    """Saved appearance: ``system`` (default), ``light``, or ``dark``."""
    raw = str(_appearance_settings().value(_APPEARANCE_KEY, APPEARANCE_SYSTEM) or "")
    normalized = raw.strip().lower()
    if normalized in _APPEARANCE_MODES:
        return normalized
    return APPEARANCE_SYSTEM


def set_appearance_mode(mode: str) -> str:
    """Persist an appearance choice. Unknown values become ``system``."""
    normalized = mode if mode in _APPEARANCE_MODES else APPEARANCE_SYSTEM
    store = _appearance_settings()
    store.setValue(_APPEARANCE_KEY, normalized)
    store.sync()
    return normalized


def colors_for_appearance(mode: str | None = None) -> ThemeColors:
    """Desktop colors, optionally forced light or dark while keeping the accent."""
    if mode is None:
        selected = appearance_mode()
    elif mode in _APPEARANCE_MODES:
        selected = mode
    else:
        selected = APPEARANCE_SYSTEM
    system = read_system_colors()
    if selected == APPEARANCE_SYSTEM:
        return system
    want_dark = selected == APPEARANCE_DARK
    if system.dark == want_dark:
        return system
    forced = builtin_colors(want_dark)
    return replace(
        forced,
        accent=system.accent,
        accent_hover=system.accent_hover,
        accent_pressed=system.accent_pressed,
        on_accent=system.on_accent,
        font_family=system.font_family,
        font_size=system.font_size,
    )


def apply_appearance(app: QApplication) -> None:
    """Paint `app` from the saved appearance mode."""
    apply_theme(app, colors=colors_for_appearance())


def refresh_system_theme(app: QApplication) -> None:
    """Re-read the desktop theme and repaint when the effective colors changed."""
    if not _watch_enabled:
        return
    colors = colors_for_appearance()
    if colors.signature() == _applied_signature:
        return
    apply_theme(app, colors=colors)


def _appearance_settings() -> QSettings:
    return QSettings("Vectorizer", "Vectorizer")


def watch_system_theme(app: QApplication) -> None:
    """Follow GTK theme changes for the lifetime of `app`."""
    global _watch_enabled
    _watch_enabled = True
    if getattr(app, "_vectorizer_theme_watch", None) is not None:
        return
    watch = _SystemThemeWatch(app)
    setattr(app, "_vectorizer_theme_watch", watch)


def _apply_font(app: QApplication, colors: ThemeColors) -> None:
    size = colors.font_size or 10
    if colors.font_family:
        font = QFont(colors.font_family, size)
        resolved = QFontInfo(font).family()
        if font.exactMatch() or resolved.casefold() == colors.font_family.casefold():
            app.setFont(font)
            return
    font = QFont("Noto Sans", size)
    if not font.exactMatch():
        font = QFont("Ubuntu", size)
    if not font.exactMatch():
        font = QFont(app.font().family(), size)
    app.setFont(font)


def _css_color_map(text: str) -> dict[str, tuple[int, int, int]]:
    raw = {name: value.strip() for name, value in _DEFINE_RE.findall(text)}
    resolved: dict[str, tuple[int, int, int]] = {}

    def resolve(name: str, stack: set[str]) -> tuple[int, int, int] | None:
        if name in resolved:
            return resolved[name]
        if name in stack or name not in raw:
            return None
        stack.add(name)
        color = _parse_color_token(raw[name], resolve, stack)
        stack.remove(name)
        if color is not None:
            resolved[name] = color
        return color

    for name in raw:
        resolve(name, set())
    return resolved


def _parse_color_token(
    token: str,
    resolve,
    stack: set[str],
) -> tuple[int, int, int] | None:
    value = token.strip().rstrip(";")
    if value.startswith("@"):
        return resolve(value[1:].strip(), stack)
    named = _NAMED.get(value.casefold())
    if named is not None:
        return named
    hex_color = _hex_to_rgb(value)
    if hex_color is not None:
        return hex_color
    match = _RGB_RE.search(value)
    if match is None:
        return None
    channels = []
    for group in match.groups():
        number = float(group)
        if number <= 1 and "." in group:
            number *= 255
        channels.append(max(0, min(255, int(round(number)))))
    return channels[0], channels[1], channels[2]


def _hex_to_rgb(token: str) -> tuple[int, int, int] | None:
    match = _HEX_RE.fullmatch(token.strip())
    if match is None:
        return None
    raw = match.group(1)
    if len(raw) in {3, 4}:
        raw = "".join(ch * 2 for ch in raw[:3])
    elif len(raw) in {6, 8}:
        raw = raw[:6]
    else:
        return None
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _mix(
    a: tuple[int, int, int],
    b: tuple[int, int, int],
    t: float,
) -> tuple[int, int, int]:
    return tuple(int(round(a[i] * (1 - t) + b[i] * t)) for i in range(3))  # type: ignore[return-value]


def _darken(rgb: tuple[int, int, int], keep: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(round(channel * keep)))) for channel in rgb)  # type: ignore[return-value]


def _luminance(rgb: tuple[int, int, int]) -> float:
    def channel(value: int) -> float:
        scaled = value / 255
        if scaled <= 0.04045:
            return scaled / 12.92
        return ((scaled + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(component) for component in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _is_dark(rgb: tuple[int, int, int]) -> bool:
    return _luminance(rgb) < 0.4


def _max_channel_delta(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return max(abs(a[i] - b[i]) for i in range(3))


def _gsettings_get(schema: str, key: str) -> str | None:
    try:
        result = subprocess.run(
            ["gsettings", "get", schema, key],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        raw = raw[1:-1]
    if not raw:
        return None
    return raw


def _gtk_theme_name() -> str | None:
    override = os.environ.get("GTK_THEME", "").strip()
    if override:
        return override
    for schema in (
        "org.cinnamon.desktop.interface",
        "org.gnome.desktop.interface",
    ):
        name = _gsettings_get(schema, "gtk-theme")
        if name:
            return name
    ini = Path.home() / ".config" / "gtk-3.0" / "settings.ini"
    try:
        for line in ini.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("gtk-theme-name"):
                _key, _, value = line.partition("=")
                value = value.strip()
                if value:
                    return value
    except OSError:
        return None
    return None


def _split_theme_name(name: str | None) -> tuple[str | None, bool]:
    if not name:
        return None, False
    if ":" in name:
        base, variant = name.split(":", 1)
        return base.strip() or None, variant.strip().casefold() == "dark"
    return name.strip() or None, False


def _prefers_dark_variant() -> bool:
    for schema in ("org.gnome.desktop.interface", "org.x.apps.portal"):
        value = _gsettings_get(schema, "color-scheme")
        if value in {"prefer-dark", "dark"}:
            return True
    return False


def _interface_font() -> tuple[str, int] | None:
    for schema in (
        "org.cinnamon.desktop.interface",
        "org.gnome.desktop.interface",
    ):
        spec = _gsettings_get(schema, "font-name")
        parsed = _parse_font(spec) if spec else None
        if parsed is not None:
            return parsed
    return None


def _parse_font(spec: str) -> tuple[str, int] | None:
    text = spec.strip().strip("'\"").strip()
    if not text:
        return None
    match = re.fullmatch(r"(.+?)\s+(\d+(?:\.\d+)?)", text)
    size = 10
    if match:
        text = match.group(1).strip().strip(",")
        size = max(8, min(24, int(float(match.group(2)))))
    if not text:
        return None
    return text, size


def _theme_search_roots() -> list[Path]:
    home = Path.home()
    return [
        home / ".themes",
        home / ".local" / "share" / "themes",
        Path("/usr/local/share/themes"),
        Path("/usr/share/themes"),
    ]


def _load_theme_css(name: str, *, variant_dark: bool) -> str | None:
    css_path: Path | None = None
    dark_path: Path | None = None
    for root in _theme_search_roots():
        directory = root / name / "gtk-3.0"
        candidate = directory / "gtk.css"
        if candidate.is_file():
            css_path = candidate
            dark_candidate = directory / "gtk-dark.css"
            if dark_candidate.is_file():
                dark_path = dark_candidate
            break
    if css_path is None:
        return None
    try:
        light = css_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    use_dark = variant_dark or _prefers_dark_variant()
    if not use_dark or dark_path is None:
        return light
    parsed = colors_from_css(light)
    if parsed is not None and parsed.dark:
        return light
    try:
        return dark_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return light


class _SystemThemeWatch(QObject):
    """Reapply colors when Cinnamon or GNOME changes the controls theme."""

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._app = app
        self._schemas = (
            "org.cinnamon.desktop.interface",
            "org.gnome.desktop.interface",
        )
        self._index = 0
        self._closing = False
        self._proc = QProcess(self)
        self._proc.finished.connect(self._on_finished)
        self._proc.readyReadStandardOutput.connect(self._on_output)
        app.aboutToQuit.connect(self._stop)
        self._start_current()

    def _start_current(self) -> None:
        if self._closing or self._index >= len(self._schemas):
            return
        self._proc.start("gsettings", ["monitor", self._schemas[self._index]])

    def _stop(self) -> None:
        self._closing = True
        if self._proc.state() != QProcess.ProcessState.NotRunning:
            self._proc.kill()

    def _on_finished(self, code: int, _status: QProcess.ExitStatus) -> None:
        if self._closing or code == 0:
            return
        self._index += 1
        QTimer.singleShot(0, self._start_current)

    def _on_output(self) -> None:
        raw = bytes(self._proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        if any(key in raw for key in ("gtk-theme", "font-name", "color-scheme")):
            refresh_system_theme(self._app)
