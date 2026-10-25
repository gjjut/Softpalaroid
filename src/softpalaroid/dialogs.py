"""Дополнительные диалоги Softpalaroid: preflight и пакетная обработка."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from .batch import BatchOptions
from .image_io import image_file_filter, supported_image_extensions
from .model import CARD_FORMATS, PAPER_LABELS, PAPER_SIZES
from .preflight import PreflightIssue
from .templates import DESIGN_TEMPLATES


class PreflightDialog(QDialog):
    """Предупреждения макета: продолжить, отменить или перейти к карточке."""

    def __init__(self, issues: list[PreflightIssue], parent=None,
                 continue_text: str = "Продолжить") -> None:
        super().__init__(parent)
        self.setWindowTitle("Проверка макета")
        self.setModal(True)
        self.resize(620, 420)
        self.navigation_index = -1

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        title = QLabel("Найдены замечания")
        title.setObjectName("DialogTitle")
        root.addWidget(title)
        subtitle = QLabel(
            "Проверка не блокирует экспорт и печать. Можно перейти к карточке "
            "и исправить проблему либо продолжить как есть.")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        self._list = QListWidget()
        for issue in issues:
            icon = "⚠" if issue.severity == "warning" else "ℹ"
            item = QListWidgetItem(f"{icon}  {issue.title}")
            item.setData(
                Qt.ItemDataRole.UserRole,
                -1 if issue.item_index is None else issue.item_index)
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)
        self._list.currentItemChanged.connect(self._sync_buttons)
        self._list.itemDoubleClicked.connect(lambda _item: self._go_to_selected())
        root.addWidget(self._list, 1)

        buttons = QHBoxLayout()
        self._go_button = QPushButton("Перейти к карточке")
        self._go_button.clicked.connect(self._go_to_selected)
        buttons.addWidget(self._go_button)
        buttons.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        proceed = QPushButton(continue_text)
        proceed.setObjectName("primaryButton")
        proceed.clicked.connect(self.accept)
        proceed.setDefault(True)
        buttons.addWidget(proceed)
        root.addLayout(buttons)
        self._sync_buttons()

    def _selected_index(self) -> int:
        item = self._list.currentItem()
        if item is None:
            return -1
        value = item.data(Qt.ItemDataRole.UserRole)
        return int(value) if isinstance(value, int) else -1

    def _sync_buttons(self, *_args) -> None:
        self._go_button.setEnabled(self._selected_index() >= 0)

    def _go_to_selected(self) -> None:
        index = self._selected_index()
        if index < 0:
            return
        self.navigation_index = index
        self.reject()


def _set_combo_data(combo: QComboBox, data: object) -> None:
    index = combo.findData(data)
    if index >= 0:
        combo.setCurrentIndex(index)


class BatchDialog(QDialog):
    """Выбор фотографий и параметров пакетной сборки листов."""

    def __init__(self, parent=None, initial: BatchOptions | None = None,
                 output_dir: str = "") -> None:
        super().__init__(parent)
        options = initial or BatchOptions()
        self.setWindowTitle("Пакетная обработка фотографий")
        self.setModal(True)
        self.resize(760, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        title = QLabel("Собрать несколько листов автоматически")
        title.setObjectName("DialogTitle")
        root.addWidget(title)
        hint = QLabel(
            "Фотографии будут разложены по выбранному числу карточек на лист. "
            "Нечитаемые файлы пропускаются, а остальные продолжают обработку.")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self._files = QListWidget()
        self._files.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        root.addWidget(self._files, 1)

        file_buttons = QHBoxLayout()
        add_files = QPushButton("Добавить файлы…")
        add_files.clicked.connect(self._add_files)
        file_buttons.addWidget(add_files)
        add_folder = QPushButton("Добавить папку…")
        add_folder.clicked.connect(self._add_folder)
        file_buttons.addWidget(add_folder)
        remove = QPushButton("Удалить выбранные")
        remove.clicked.connect(self._remove_selected)
        file_buttons.addWidget(remove)
        clear = QPushButton("Очистить")
        clear.clicked.connect(self._files.clear)
        file_buttons.addWidget(clear)
        file_buttons.addStretch(1)
        root.addLayout(file_buttons)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(9)

        self._cards = QSpinBox()
        self._cards.setRange(1, 12)
        self._cards.setValue(options.cards_per_sheet)
        form.addRow("Карточек на лист", self._cards)

        self._orientation = QComboBox()
        self._orientation.addItem("Горизонтальный лист", True)
        self._orientation.addItem("Вертикальный лист", False)
        _set_combo_data(self._orientation, options.landscape)
        form.addRow("Ориентация", self._orientation)

        self._paper = QComboBox()
        for key in PAPER_SIZES:
            self._paper.addItem(PAPER_LABELS[key], key)
        _set_combo_data(self._paper, options.paper_size)
        form.addRow("Размер бумаги", self._paper)

        self._card_format = QComboBox()
        for spec in CARD_FORMATS.values():
            self._card_format.addItem(spec.name, spec.key)
        _set_combo_data(self._card_format, options.card_format)
        form.addRow("Формат карточек", self._card_format)

        self._template = QComboBox()
        for template in DESIGN_TEMPLATES.values():
            self._template.addItem(template.name, template.key)
        _set_combo_data(self._template, options.template)
        form.addRow("Дизайн-шаблон", self._template)

        self._output_format = QComboBox()
        self._output_format.addItem("JPEG · 300 DPI", "jpg")
        self._output_format.addItem("PNG · 300 DPI", "png")
        self._output_format.addItem("PDF для печати · 300 DPI", "pdf")
        _set_combo_data(self._output_format, options.normalized_format())
        form.addRow("Формат файлов", self._output_format)

        self._safe_margin = QDoubleSpinBox()
        self._safe_margin.setRange(0.0, 25.0)
        self._safe_margin.setSingleStep(0.5)
        self._safe_margin.setDecimals(1)
        self._safe_margin.setSuffix(" мм")
        self._safe_margin.setValue(options.safe_margin_mm)
        form.addRow("Безопасная область", self._safe_margin)

        self._captions = QCheckBox("Подписывать карточки именами файлов")
        self._captions.setChecked(options.captions_from_filename)
        form.addRow("Подписи", self._captions)

        self._prefix = QLineEdit(options.prefix)
        form.addRow("Префикс файлов", self._prefix)

        output_row = QHBoxLayout()
        self._output_dir = QLineEdit(output_dir)
        output_row.addWidget(self._output_dir, 1)
        browse = QPushButton("Выбрать…")
        browse.clicked.connect(self._choose_output)
        output_row.addWidget(browse)
        form.addRow("Папка результата", output_row)
        root.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        start = QPushButton("Собрать листы")
        start.setObjectName("primaryButton")
        start.setDefault(True)
        start.clicked.connect(self._validate_and_accept)
        buttons.addWidget(start)
        root.addLayout(buttons)

    def _contains(self, path: str) -> bool:
        absolute = os.path.abspath(path)
        for row in range(self._files.count()):
            item = self._files.item(row)
            if os.path.abspath(str(item.data(Qt.ItemDataRole.UserRole))) == absolute:
                return True
        return False

    def _append_path(self, path: str) -> None:
        if self._contains(path):
            return
        item = QListWidgetItem(str(path))
        item.setData(Qt.ItemDataRole.UserRole, str(path))
        self._files.addItem(item)

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Выберите фотографии", "", image_file_filter())
        for path in paths:
            self._append_path(path)

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Папка с фотографиями")
        if not folder:
            return
        extensions = set(supported_image_extensions())
        for path in sorted(Path(folder).rglob("*")):
            if path.is_file() and path.suffix.lower() in extensions:
                self._append_path(str(path))

    def _remove_selected(self) -> None:
        for item in self._files.selectedItems():
            self._files.takeItem(self._files.row(item))

    def _choose_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Папка результата", self._output_dir.text())
        if folder:
            self._output_dir.setText(folder)

    def photo_paths(self) -> list[str]:
        result: list[str] = []
        for row in range(self._files.count()):
            item = self._files.item(row)
            result.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return result

    def output_dir(self) -> str:
        return self._output_dir.text().strip()

    def options(self) -> BatchOptions:
        return BatchOptions(
            cards_per_sheet=self._cards.value(),
            landscape=bool(self._orientation.currentData()),
            paper_size=str(self._paper.currentData()),
            card_format=str(self._card_format.currentData()),
            template=str(self._template.currentData()),
            output_format=str(self._output_format.currentData()),
            captions_from_filename=self._captions.isChecked(),
            prefix=self._prefix.text().strip() or "softpalaroid",
            safe_margin_mm=self._safe_margin.value(),
        )

    def _validate_and_accept(self) -> None:
        if not self.photo_paths():
            QMessageBox.warning(
                self, "Пакетная обработка",
                "Добавьте хотя бы одну фотографию.")
            return
        if not self.output_dir():
            QMessageBox.warning(
                self, "Пакетная обработка",
                "Выберите папку, куда сохранить готовые листы.")
            return
        self.accept()
