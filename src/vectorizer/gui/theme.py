"""Linux Mint Mint-Y-Aqua inspired Fusion theme for Vectorizer."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
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


def mint_stylesheet(dark: bool) -> str:
    if dark:
        bg, panel, base, text, muted, border = (
            MINT_DARK_BG,
            MINT_DARK_PANEL,
            MINT_DARK_BASE,
            MINT_DARK_TEXT,
            "#adadb5",
            "#46464e",
        )
    else:
        bg, panel, base, text, muted, border = (
            MINT_BG,
            MINT_PANEL,
            MINT_BASE,
            MINT_TEXT,
            MINT_MUTED,
            MINT_BORDER,
        )
    return f"""
    QWidget {{
        background-color: {bg};
        color: {text};
        font-size: 13px;
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
        background: {MINT_ACCENT};
        color: #ffffff;
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
        background-color: {MINT_ACCENT};
        color: #ffffff;
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
        background: {MINT_ACCENT};
        color: #ffffff;
        border-color: {MINT_ACCENT_PRESSED};
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
        color: {text};
        border-bottom: 2px solid {MINT_ACCENT};
    }}
    QTabBar::tab:hover:!selected {{
        background: {MINT_BORDER_SOFT if not dark else border};
    }}
    QGroupBox {{
        background: {base};
        border: 1px solid {border};
        border-radius: 8px;
        margin-top: 12px;
        padding: 12px 10px 10px 10px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
        color: {text};
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
        border-color: {MINT_ACCENT_HOVER};
    }}
    QPushButton:pressed {{
        background-color: {MINT_ACCENT_PRESSED};
        color: #ffffff;
        border-color: {MINT_ACCENT_PRESSED};
    }}
    QPushButton:disabled {{
        color: {muted};
        background: {panel};
    }}
    QPushButton#primaryButton, QPushButton[default="true"] {{
        background-color: {MINT_ACCENT};
        color: #ffffff;
        border-color: {MINT_ACCENT_HOVER};
        font-weight: 600;
    }}
    QPushButton#primaryButton:hover, QPushButton[default="true"]:hover {{
        background-color: {MINT_ACCENT_HOVER};
    }}
    QPushButton#primaryButton:pressed, QPushButton[default="true"]:pressed {{
        background-color: {MINT_ACCENT_PRESSED};
    }}
    QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
        background: {base};
        border: 1px solid {border};
        border-radius: 6px;
        padding: 4px 8px;
        min-height: 24px;
        selection-background-color: {MINT_ACCENT};
        selection-color: #ffffff;
    }}
    QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover {{
        border-color: {MINT_ACCENT};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox QAbstractItemView {{
        background: {base};
        border: 1px solid {border};
        selection-background-color: {MINT_ACCENT};
        selection-color: #ffffff;
        outline: 0;
    }}
    QSlider::groove:horizontal {{
        height: 6px;
        background: {border};
        border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: {MINT_ACCENT};
        width: 16px;
        height: 16px;
        margin: -5px 0;
        border-radius: 8px;
    }}
    QSlider::sub-page:horizontal {{
        background: {MINT_ACCENT};
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
        background-color: {MINT_ACCENT};
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
        background: {MINT_ACCENT};
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
        background: {MINT_ACCENT};
        color: #ffffff;
    }}
    QListWidget#paletteList::item {{
        background: transparent;
        padding: 1px 2px;
    }}
    QListWidget#paletteList::item:selected {{
        background: transparent;
        border: 2px solid {MINT_ACCENT};
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
        background: {MINT_ACCENT};
        border-color: {MINT_ACCENT_HOVER};
    }}
    QFrame#sidePanel {{
        background: {panel};
        border-right: 1px solid {border};
    }}
    QGraphicsView {{
        background: {base};
        border: none;
    }}
    """


def apply_theme(app: QApplication, dark: bool) -> None:
    app.setStyle(QStyleFactory.create("Fusion"))
    font = QFont("Noto Sans", 10)
    if not font.exactMatch():
        font = QFont("Ubuntu", 10)
    if not font.exactMatch():
        font = QFont(app.font().family(), 10)
    app.setFont(font)

    palette = QPalette()
    if dark:
        bg = QColor(MINT_DARK_BG)
        panel = QColor(MINT_DARK_PANEL)
        base = QColor(MINT_DARK_BASE)
        text = QColor(MINT_DARK_TEXT)
    else:
        bg = QColor(MINT_BG)
        panel = QColor(MINT_PANEL)
        base = QColor(MINT_BASE)
        text = QColor(MINT_TEXT)
    accent = QColor(MINT_ACCENT)
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
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, accent)
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(MINT_MUTED))
    app.setPalette(palette)
    app.setStyleSheet(mint_stylesheet(dark))
