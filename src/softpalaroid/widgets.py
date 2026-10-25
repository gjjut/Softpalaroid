"""Небольшие переиспользуемые виджеты инспектора Softpalaroid."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings, QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


class CollapsibleCard(QFrame):
    """Карточка инспектора со сворачивающимся содержимым.

    Состояние раздела сохраняется в QSettings, поэтому пользовательская
    организация панели переживает перезапуск приложения.
    """

    expandedChanged = Signal(bool)

    def __init__(self, title: str, key: str | None = None,
                 settings: QSettings | None = None,
                 expanded: bool = True,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self.section_key = key or title
        self._settings = settings
        self.setProperty("card", True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 16)
        outer.setSpacing(8)

        self.header_button = QPushButton()
        self.header_button.setProperty("sectionHeader", True)
        self.header_button.setCheckable(True)
        self.header_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header_button.setAccessibleName(f"Раздел: {title}")
        outer.addWidget(self.header_button)

        self.body = QWidget()
        self.content_layout = QVBoxLayout(self.body)
        self.content_layout.setContentsMargins(0, 2, 0, 0)
        self.content_layout.setSpacing(10)
        outer.addWidget(self.body)

        initial = expanded
        if settings is not None:
            initial = _as_bool(
                settings.value(f"panelSection/{self.section_key}", expanded),
                expanded)
        self.header_button.toggled.connect(self._on_header_toggled)
        self.set_expanded(initial, save=False)

    def _update_header(self) -> None:
        arrow = "▾" if self.header_button.isChecked() else "▸"
        self.header_button.setText(f"{arrow}  {self.title}")
        self.header_button.setToolTip(
            "Свернуть раздел" if self.header_button.isChecked()
            else "Развернуть раздел")

    def _on_header_toggled(self, checked: bool) -> None:
        self.body.setVisible(checked)
        self._update_header()
        if self._settings is not None:
            self._settings.setValue(
                f"panelSection/{self.section_key}", checked)
            self._settings.sync()
        self.expandedChanged.emit(checked)

    def is_expanded(self) -> bool:
        return self.header_button.isChecked()

    def set_expanded(self, expanded: bool, *, save: bool = True) -> None:
        if self.header_button.isChecked() == expanded:
            self.body.setVisible(expanded)
            self._update_header()
            if save and self._settings is not None:
                self._settings.setValue(
                    f"panelSection/{self.section_key}", expanded)
                self._settings.sync()
            return
        if save:
            self.header_button.setChecked(expanded)
            return
        blocked = self.header_button.blockSignals(True)
        try:
            self.header_button.setChecked(expanded)
            self.body.setVisible(expanded)
            self._update_header()
        finally:
            self.header_button.blockSignals(blocked)


@dataclass(frozen=True)
class ChoiceItem:
    key: str
    label: str
    icon: QIcon
    tooltip: str = ""


class VisualChoiceStrip(QWidget):
    """Горизонтальная галерея выбора: иконка-превью + короткая подпись."""

    selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._buttons: dict[str, QToolButton] = {}
        self._current_key: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("choiceStrip")
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFixedHeight(92)
        self._scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._content = QWidget()
        self._layout = QHBoxLayout(self._content)
        self._layout.setContentsMargins(2, 4, 2, 4)
        self._layout.setSpacing(8)
        self._layout.addStretch(1)
        self._scroll.setWidget(self._content)
        root.addWidget(self._scroll)

    def _clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._buttons.clear()
        self._layout.addStretch(1)

    def set_choices(self, choices: list[ChoiceItem],
                    current: str | None = None) -> None:
        selected = current if current is not None else self._current_key
        self._clear()
        # Растяжка всегда последний элемент; кнопки вставляем перед ней.
        for choice in choices:
            button = QToolButton()
            button.setProperty("choiceButton", True)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIcon(choice.icon)
            button.setIconSize(QSize(72, 46))
            button.setText(choice.label)
            button.setToolTip(choice.tooltip or choice.label)
            button.setAccessibleName(choice.label)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setFixedSize(94, 78)
            button.clicked.connect(
                lambda _checked=False, key=choice.key: self._activate(key))
            self._layout.insertWidget(self._layout.count() - 1, button)
            self._buttons[choice.key] = button
        if selected in self._buttons:
            self.set_current(selected)
        elif choices:
            self.set_current(choices[0].key)
        else:
            self._current_key = None

    def _activate(self, key: str) -> None:
        self.set_current(key)
        self.selected.emit(key)

    def set_current(self, key: str) -> None:
        if key not in self._buttons:
            return
        self._current_key = key
        for item_key, button in self._buttons.items():
            blocked = button.blockSignals(True)
            try:
                button.setChecked(item_key == key)
            finally:
                button.blockSignals(blocked)
        self._scroll.ensureWidgetVisible(self._buttons[key], 12, 0)

    def current_key(self) -> str | None:
        return self._current_key
