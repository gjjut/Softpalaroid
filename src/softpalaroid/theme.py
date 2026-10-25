"""Тема интерфейса в стиле X: чёрный фон, акцент #1D9BF0, шрифт Inter.

Inter — свободный шрифт (OFL) с кириллицей, визуально близкий к фирменному
Chirp. Для подписей на полароидах подключается рукописный Caveat.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from .resources import asset_path

# Палитра X (тёмная тема "Lights Out")
BG = "#000000"
SURFACE = "#16181C"
SURFACE_HOVER = "#1D1F23"
BORDER = "#2F3336"
BORDER_STRONG = "#536471"
TEXT = "#E7E9EA"
TEXT_SECONDARY = "#71767B"
ACCENT = "#1D9BF0"
ACCENT_HOVER = "#1A8CD8"
ON_LIGHT = "#0F1419"
LIGHT_BUTTON = "#EFF3F4"
LIGHT_BUTTON_HOVER = "#D7DBDC"

UI_FONT_FAMILIES = ["Inter", "Segoe UI Variable Text", "Segoe UI",
                    "Helvetica Neue", "DejaVu Sans"]
CAPTION_FONT_FAMILY = "Caveat"


def load_fonts() -> None:
    """Зарегистрировать встроенные шрифты Inter и Caveat."""
    for filename in ("Inter.ttf", "Caveat.ttf"):
        path = asset_path("fonts", filename)
        if path:
            QFontDatabase.addApplicationFont(path)


def _dark_palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(BG))
    p.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    p.setColor(QPalette.ColorRole.Base, QColor(SURFACE))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(SURFACE_HOVER))
    p.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    p.setColor(QPalette.ColorRole.Button, QColor(SURFACE))
    p.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    p.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_SECONDARY))
    p.setColor(QPalette.ColorRole.Link, QColor(ACCENT))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(SURFACE_HOVER))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text,
               QColor(TEXT_SECONDARY))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText,
               QColor(TEXT_SECONDARY))
    return p


STYLESHEET = """
QWidget {
    background-color: #000000;
    color: #E7E9EA;
    font-family: "Inter", "Segoe UI Variable Text", "Segoe UI", "DejaVu Sans";
    font-size: 13px;
}
QMainWindow { background-color: #000000; }

/* --- верхняя панель --- */
QFrame#header {
    background-color: #000000;
    border: none;
    border-bottom: 1px solid #2F3336;
}
QLabel#appTitle { font-size: 19px; font-weight: 800; color: #E7E9EA; }
QLabel#appSubtitle { font-size: 12px; color: #71767B; }
QLabel#versionChip {
    color: #71767B; border: 1px solid #2F3336; border-radius: 11px;
    padding: 3px 10px; font-size: 11px; font-weight: 700;
}

/* --- панель настроек --- */
QScrollArea#inspector {
    background-color: #000000;
    border: none;
    border-left: 1px solid #2F3336;
}
QFrame[card="true"] {
    background-color: #000000;
    border: 1px solid #2F3336;
    border-radius: 16px;
}
QLabel[role="section"] { font-size: 15px; font-weight: 800; color: #E7E9EA; }
QLabel[role="field"] { font-size: 12px; font-weight: 700; color: #71767B; }
QLabel[role="muted"] { font-size: 12px; color: #71767B; }
QLabel#slotChip {
    color: #1D9BF0; border: 1px solid #1D9BF0; border-radius: 11px;
    padding: 3px 10px; font-size: 11px; font-weight: 700;
}

/* --- кнопки: «пилюли» как в X --- */
QPushButton, QToolButton {
    background-color: transparent;
    border: 1px solid #536471;
    border-radius: 16px;
    padding: 7px 16px;
    font-weight: 700;
    color: #E7E9EA;
}
QPushButton:hover, QToolButton:hover { background-color: rgba(231,233,234,0.10); }
QPushButton:pressed, QToolButton:pressed { background-color: rgba(231,233,234,0.20); }
QPushButton#primaryButton {
    background-color: #1D9BF0; border: none; color: #FFFFFF; font-size: 14px;
    border-radius: 20px;
}
QPushButton#primaryButton:hover { background-color: #1A8CD8; }
QPushButton#whiteButton {
    background-color: #EFF3F4; border: none; color: #0F1419; font-size: 14px;
    border-radius: 20px;
}
QPushButton#whiteButton:hover { background-color: #D7DBDC; }
QToolButton#moreButton { padding: 4px 10px; font-size: 16px; }
QToolButton::menu-indicator { image: none; width: 0; }

/* --- сегментные переключатели --- */
QPushButton[segment="true"] {
    background-color: #16181C;
    border: 1px solid #2F3336;
    border-radius: 18px;
    padding: 7px 8px;
    font-weight: 700;
    color: #E7E9EA;
}
QPushButton[segment="true"]:hover { background-color: #1D1F23; }
QPushButton[segment="true"]:checked {
    background-color: #1D9BF0; border-color: #1D9BF0; color: #FFFFFF;
}

/* --- поля ввода и списки --- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #16181C;
    border: 1px solid #333639;
    border-radius: 12px;
    padding: 7px 10px;
    selection-background-color: #1D9BF0;
    selection-color: #FFFFFF;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #1D9BF0;
}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    width: 18px; border: none; background: transparent;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: url("__CHEVRON_UP__"); width: 10px; height: 10px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: url("__CHEVRON_DOWN__"); width: 10px; height: 10px;
}
QComboBox::drop-down { width: 24px; border: none; background: transparent; }
QComboBox::down-arrow {
    image: url("__CHEVRON_DOWN__"); width: 12px; height: 12px;
}
QComboBox QAbstractItemView {
    background-color: #16181C;
    border: 1px solid #2F3336;
    selection-background-color: #1D9BF0;
    selection-color: #FFFFFF;
    outline: none;
}

/* --- слайдеры --- */
QSlider::groove:horizontal {
    height: 4px; border-radius: 2px; background-color: #2F3336;
}
QSlider::sub-page:horizontal {
    height: 4px; border-radius: 2px; background-color: #1D9BF0;
}
QSlider::handle:horizontal {
    width: 18px; height: 18px; margin: -7px 0;
    border-radius: 9px; background-color: #1D9BF0;
    border: 2px solid #FFFFFF;
}
QSlider::handle:horizontal:hover { background-color: #1A8CD8; }

/* --- меню --- */
QMenu {
    background-color: #000000;
    border: 1px solid #2F3336;
    border-radius: 12px;
    padding: 6px;
}
QMenu::item { padding: 8px 28px 8px 12px; border-radius: 8px; }
QMenu::item:selected { background-color: #16181C; }
QMenu::separator { height: 1px; background-color: #2F3336; margin: 6px 8px; }

/* --- статус, скролл, сплиттер --- */
QStatusBar {
    background-color: #000000; color: #71767B;
    border-top: 1px solid #2F3336; font-size: 12px;
}
QScrollBar:vertical { width: 8px; background: transparent; margin: 0; }
QScrollBar::handle:vertical { background-color: #2F3336; border-radius: 4px; min-height: 32px; }
QScrollBar::handle:vertical:hover { background-color: #536471; }
QScrollBar:horizontal { height: 8px; background: transparent; margin: 0; }
QScrollBar::handle:horizontal { background-color: #2F3336; border-radius: 4px; min-width: 32px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QSplitter::handle { background-color: #2F3336; }
QToolTip {
    background-color: #1D1F23; color: #E7E9EA;
    border: 1px solid #2F3336; padding: 4px 8px;
}
QGroupBox {
    border: 1px solid #2F3336; border-radius: 16px;
    margin-top: 14px; padding-top: 14px; font-weight: 800;
}
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 4px; }
"""


def apply_theme(app: QApplication) -> None:
    """Подключить шрифты, палитру и таблицу стилей."""
    load_fonts()
    app.setStyle("Fusion")
    font = QFont()
    font.setFamilies(UI_FONT_FAMILIES)
    font.setPointSize(10)
    app.setFont(font)
    app.setPalette(_dark_palette())
    stylesheet = STYLESHEET
    for token, filename in (("__CHEVRON_UP__", "chevron-up.png"),
                            ("__CHEVRON_DOWN__", "chevron-down.png")):
        path = asset_path("icons", filename)
        stylesheet = stylesheet.replace(
            token, path.replace("\\", "/") if path else "")
    app.setStyleSheet(stylesheet)
