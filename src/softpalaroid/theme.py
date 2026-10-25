"""Темы интерфейса в стиле X: тёмная «Lights Out» и светлая.

Обе темы строятся из одного шаблона таблицы стилей и двух палитр, поэтому
геометрия и поведение виджетов не зависят от выбранной темы. Выбор хранится
в QSettings (`ui/theme`) и применяется при запуске.
"""
from __future__ import annotations

from string import Template

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from .resources import asset_path

THEMES = ("dark", "light")
THEME_SETTING = "ui/theme"

# Совместимые имена тёмной палитры (исторически использовались как константы).
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

_PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        "BG": "#000000",
        "SURFACE": "#16181C",
        "SURFACE_HOVER": "#1D1F23",
        "BORDER": "#2F3336",
        "BORDER_STRONG": "#536471",
        "BORDER_INPUT": "#333639",
        "INPUT_BG": "#16181C",
        "TEXT": "#E7E9EA",
        "TEXT_SECONDARY": "#71767B",
        "ACCENT": "#1D9BF0",
        "ACCENT_HOVER": "#1A8CD8",
        "ACCENT_SOFT": "rgba(29,155,240,0.16)",
        "HOVER_BG": "rgba(231,233,234,0.10)",
        "PRESSED_BG": "rgba(231,233,234,0.20)",
        "INVERT_BG": "#EFF3F4",
        "INVERT_HOVER": "#D7DBDC",
        "INVERT_TEXT": "#0F1419",
        "PRIMARY_DISABLED_BG": "#0D4D73",
        "PRIMARY_DISABLED_TEXT": "#8ECDF7",
        "WARNING": "#FFD166",
        "ERROR": "#FF7A93",
        "TOOLBAR_BG": "rgba(22,24,28,0.92)",
    },
    "light": {
        "BG": "#FFFFFF",
        "SURFACE": "#F7F9F9",
        "SURFACE_HOVER": "#EFF3F4",
        "BORDER": "#E6ECF0",
        "BORDER_STRONG": "#536471",
        "BORDER_INPUT": "#CFD9DE",
        "INPUT_BG": "#FFFFFF",
        "TEXT": "#0F1419",
        "TEXT_SECONDARY": "#536471",
        "ACCENT": "#1D9BF0",
        "ACCENT_HOVER": "#1A8CD8",
        "ACCENT_SOFT": "rgba(29,155,240,0.12)",
        "HOVER_BG": "rgba(15,20,25,0.08)",
        "PRESSED_BG": "rgba(15,20,25,0.16)",
        "INVERT_BG": "#0F1419",
        "INVERT_HOVER": "#272C33",
        "INVERT_TEXT": "#FFFFFF",
        "PRIMARY_DISABLED_BG": "#8ECDF7",
        "PRIMARY_DISABLED_TEXT": "#FFFFFF",
        "WARNING": "#9A6B00",
        "ERROR": "#E0245E",
        "TOOLBAR_BG": "rgba(255,255,255,0.94)",
    },
}

UI_FONT_FAMILIES = ["Inter", "Segoe UI Variable Text", "Segoe UI",
                    "Helvetica Neue", "DejaVu Sans"]
CAPTION_FONT_FAMILY = "Caveat"


def normalize_theme(mode: object) -> str:
    value = str(mode or "dark").strip().lower()
    return value if value in THEMES else "dark"


def current_theme() -> str:
    """Сохранённый в настройках режим темы."""
    settings = QSettings("Softpalaroid", "Softpalaroid")
    return normalize_theme(settings.value(THEME_SETTING, "dark"))


def load_fonts() -> None:
    """Зарегистрировать встроенные шрифты Inter и Caveat."""
    for filename in ("Inter.ttf", "Caveat.ttf"):
        path = asset_path("fonts", filename)
        if path:
            QFontDatabase.addApplicationFont(path)


def _palette(mode: str) -> QPalette:
    colors = _PALETTES[mode]
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(colors["BG"]))
    p.setColor(QPalette.ColorRole.WindowText, QColor(colors["TEXT"]))
    p.setColor(QPalette.ColorRole.Base, QColor(colors["INPUT_BG"]))
    p.setColor(QPalette.ColorRole.AlternateBase,
               QColor(colors["SURFACE_HOVER"]))
    p.setColor(QPalette.ColorRole.Text, QColor(colors["TEXT"]))
    p.setColor(QPalette.ColorRole.Button, QColor(colors["SURFACE"]))
    p.setColor(QPalette.ColorRole.ButtonText, QColor(colors["TEXT"]))
    p.setColor(QPalette.ColorRole.Highlight, QColor(colors["ACCENT"]))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    p.setColor(QPalette.ColorRole.PlaceholderText,
               QColor(colors["TEXT_SECONDARY"]))
    p.setColor(QPalette.ColorRole.Link, QColor(colors["ACCENT"]))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor("#1D1F23"))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor("#E7E9EA"))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text,
               QColor(colors["TEXT_SECONDARY"]))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText,
               QColor(colors["TEXT_SECONDARY"]))
    return p


_TEMPLATE = Template("""
QWidget {
    background-color: $BG;
    color: $TEXT;
    font-family: "Inter", "Segoe UI Variable Text", "Segoe UI", "DejaVu Sans";
    font-size: 13px;
}
QMainWindow { background-color: $BG; }

/* --- верхняя панель --- */
QFrame#header {
    background-color: $BG;
    border: none;
    border-bottom: 1px solid $BORDER;
}
QLabel#appTitle { font-size: 19px; font-weight: 800; color: $TEXT; }
QLabel#appSubtitle { font-size: 12px; color: $TEXT_SECONDARY; }
QLabel#versionChip {
    color: $TEXT_SECONDARY; border: 1px solid $BORDER; border-radius: 11px;
    padding: 3px 10px; font-size: 11px; font-weight: 700;
}

/* --- панель настроек --- */
QScrollArea#inspector {
    background-color: $BG;
    border: none;
    border-left: 1px solid $BORDER;
}
QFrame[card="true"] {
    background-color: $BG;
    border: 1px solid $BORDER;
    border-radius: 16px;
}
QLabel[role="section"] { font-size: 15px; font-weight: 800; color: $TEXT; }
QLabel[role="field"] { font-size: 12px; font-weight: 700; color: $TEXT_SECONDARY; }
QLabel[role="muted"] { font-size: 12px; color: $TEXT_SECONDARY; }
QLabel#slotChip {
    color: $ACCENT; border: 1px solid $ACCENT; border-radius: 11px;
    padding: 3px 10px; font-size: 11px; font-weight: 700;
}

/* --- кнопки: «пилюли» как в X --- */
QPushButton, QToolButton {
    background-color: transparent;
    border: 1px solid $BORDER_STRONG;
    border-radius: 16px;
    padding: 7px 16px;
    font-weight: 700;
    color: $TEXT;
}
QPushButton:hover, QToolButton:hover { background-color: $HOVER_BG; }
QPushButton:pressed, QToolButton:pressed { background-color: $PRESSED_BG; }
QPushButton:disabled, QToolButton:disabled {
    color: $TEXT_SECONDARY; border-color: $BORDER; background-color: transparent;
}
QPushButton#primaryButton:disabled {
    color: $PRIMARY_DISABLED_TEXT; background-color: $PRIMARY_DISABLED_BG;
}
QPushButton#primaryButton {
    background-color: $ACCENT; border: none; color: #FFFFFF; font-size: 14px;
    border-radius: 20px;
}
QPushButton#primaryButton:hover { background-color: $ACCENT_HOVER; }
QPushButton#whiteButton {
    background-color: $INVERT_BG; border: none; color: $INVERT_TEXT;
    font-size: 14px; border-radius: 20px;
}
QPushButton#whiteButton:hover { background-color: $INVERT_HOVER; }
QToolButton#moreButton { padding: 4px 10px; font-size: 16px; }
QToolButton#iconButton { padding: 0; font-size: 16px; }
QToolButton::menu-indicator { image: none; width: 0; }

/* --- сегментные переключатели --- */
QPushButton[segment="true"] {
    background-color: $SURFACE;
    border: 1px solid $BORDER;
    border-radius: 18px;
    padding: 7px 8px;
    font-weight: 700;
    color: $TEXT;
}
QPushButton[segment="true"]:hover { background-color: $SURFACE_HOVER; }
QPushButton[segment="true"]:checked {
    background-color: $ACCENT; border-color: $ACCENT; color: #FFFFFF;
}

/* --- сворачиваемые разделы, визуальные выборы и лента слотов --- */
QPushButton[sectionHeader="true"] {
    background-color: transparent;
    border: none;
    border-radius: 8px;
    padding: 5px 4px;
    text-align: left;
    font-size: 15px;
    font-weight: 800;
    color: $TEXT;
}
QPushButton[sectionHeader="true"]:hover { background-color: $SURFACE; }
QScrollArea#choiceStrip, QScrollArea#slotStrip {
    background-color: transparent;
    border: none;
}
QToolButton[choiceButton="true"], QToolButton[slotButton="true"] {
    background-color: $SURFACE;
    border: 1px solid $BORDER;
    border-radius: 12px;
    padding: 5px 4px;
    font-size: 11px;
    font-weight: 700;
    color: $TEXT;
}
QToolButton[choiceButton="true"]:hover, QToolButton[slotButton="true"]:hover {
    border-color: $BORDER_STRONG; background-color: $SURFACE_HOVER;
}
QToolButton[choiceButton="true"]:checked, QToolButton[slotButton="true"]:checked {
    border: 2px solid $ACCENT; background-color: $ACCENT_SOFT;
}
QToolButton[slotButton="true"][slotState="warning"] { color: $WARNING; }
QToolButton[slotButton="true"][slotState="error"] { color: $ERROR; }
QToolButton[slotButton="true"][slotState="empty"] { color: $TEXT_SECONDARY; }

/* --- плавающая панель масштаба на холсте --- */
QFrame#canvasToolbar {
    background-color: $TOOLBAR_BG;
    border: 1px solid $BORDER;
    border-radius: 18px;
}
QFrame#canvasToolbar QToolButton {
    border: none; background-color: transparent; border-radius: 12px;
    padding: 0; font-size: 15px; color: $TEXT;
}
QFrame#canvasToolbar QToolButton:hover { background-color: $HOVER_BG; }
QLabel#zoomLabel {
    font-size: 12px; font-weight: 700; color: $TEXT_SECONDARY;
    background-color: transparent;
}

/* --- поля ввода и списки --- */
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: $INPUT_BG;
    border: 1px solid $BORDER_INPUT;
    border-radius: 12px;
    padding: 7px 10px;
    selection-background-color: $ACCENT;
    selection-color: #FFFFFF;
}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: $ACCENT;
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
QComboBox QAbstractItemView, QCompleter QAbstractItemView {
    background-color: $INPUT_BG;
    border: 1px solid $BORDER;
    selection-background-color: $ACCENT;
    selection-color: #FFFFFF;
    outline: none;
}

QDialog { background-color: $BG; }
QLabel#DialogTitle { font-size: 18px; font-weight: 800; color: $TEXT; }
QListWidget {
    background-color: $INPUT_BG;
    border: 1px solid $BORDER;
    border-radius: 12px;
    padding: 6px;
    outline: none;
}
QListWidget::item { padding: 7px 9px; border-radius: 8px; }
QListWidget::item:selected {
    background-color: $ACCENT; color: #FFFFFF;
}
QCheckBox { spacing: 8px; color: $TEXT; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid $BORDER_STRONG; background-color: $INPUT_BG;
}
QCheckBox::indicator:checked {
    background-color: $ACCENT; border-color: $ACCENT;
}

/* --- слайдеры --- */
QSlider::groove:horizontal {
    height: 4px; border-radius: 2px; background-color: $BORDER_INPUT;
}
QSlider::sub-page:horizontal {
    height: 4px; border-radius: 2px; background-color: $ACCENT;
}
QSlider::handle:horizontal {
    width: 18px; height: 18px; margin: -7px 0;
    border-radius: 9px; background-color: $ACCENT;
    border: 2px solid #FFFFFF;
}
QSlider::handle:horizontal:hover { background-color: $ACCENT_HOVER; }

/* --- меню --- */
QMenu {
    background-color: $BG;
    border: 1px solid $BORDER;
    border-radius: 12px;
    padding: 6px;
}
QMenu::item { padding: 8px 28px 8px 12px; border-radius: 8px; }
QMenu::item:selected { background-color: $SURFACE; }
QMenu::separator { height: 1px; background-color: $BORDER; margin: 6px 8px; }

/* --- статус, скролл, сплиттер --- */
QStatusBar {
    background-color: $BG; color: $TEXT_SECONDARY;
    border-top: 1px solid $BORDER; font-size: 12px;
}
QScrollBar:vertical { width: 8px; background: transparent; margin: 0; }
QScrollBar::handle:vertical { background-color: $BORDER_INPUT; border-radius: 4px; min-height: 32px; }
QScrollBar::handle:vertical:hover { background-color: $BORDER_STRONG; }
QScrollBar:horizontal { height: 8px; background: transparent; margin: 0; }
QScrollBar::handle:horizontal { background-color: $BORDER_INPUT; border-radius: 4px; min-width: 32px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QSplitter::handle { background-color: $BORDER; }
QToolTip {
    background-color: #1D1F23; color: #E7E9EA;
    border: 1px solid #2F3336; padding: 4px 8px;
}
QGroupBox {
    border: 1px solid $BORDER; border-radius: 16px;
    margin-top: 14px; padding-top: 14px; font-weight: 800;
}
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 4px; }
""")


def stylesheet_for(mode: str) -> str:
    """Таблица стилей выбранной темы с подставленными путями иконок."""
    stylesheet = _TEMPLATE.substitute(_PALETTES[normalize_theme(mode)])
    for token, filename in (("__CHEVRON_UP__", "chevron-up.png"),
                            ("__CHEVRON_DOWN__", "chevron-down.png")):
        path = asset_path("icons", filename)
        stylesheet = stylesheet.replace(
            token, path.replace("\\", "/") if path else "")
    return stylesheet


# Историческое имя: тёмная тема по умолчанию.
STYLESHEET = stylesheet_for("dark")


def apply_theme(app: QApplication, mode: str | None = None) -> str:
    """Подключить шрифты, палитру и таблицу стилей; вернуть режим темы."""
    resolved = normalize_theme(mode) if mode is not None else current_theme()
    load_fonts()
    app.setStyle("Fusion")
    font = QFont()
    font.setFamilies(UI_FONT_FAMILIES)
    font.setPointSize(10)
    app.setFont(font)
    app.setPalette(_palette(resolved))
    app.setStyleSheet(stylesheet_for(resolved))
    return resolved


def set_theme(app: QApplication, mode: str) -> str:
    """Сохранить выбор темы в QSettings и применить его сразу."""
    resolved = normalize_theme(mode)
    settings = QSettings("Softpalaroid", "Softpalaroid")
    settings.setValue(THEME_SETTING, resolved)
    settings.sync()
    return apply_theme(app, resolved)
