"""Главное окно Softpalaroid."""
from __future__ import annotations

import os

from PIL import Image, UnidentifiedImageError
from PySide6.QtCore import QRect, QSizeF, Qt
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QImage, QPainter
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .canvas import CanvasWidget
from .filters import FILTERS
from .model import PolaroidItem, Project
from .render import load_photo, render_sheet, save_sheet

IMAGE_FILTER = "Изображения (*.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff);;Все файлы (*)"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Softpalaroid {__version__} — полароиды на листе 10×15")
        self.resize(1180, 760)
        self.setAcceptDrops(True)

        self.project = Project()
        self.project.set_layout(1, landscape=True)

        self.canvas = CanvasWidget()
        self.canvas.set_project(self.project)
        self.canvas.selectionChanged.connect(lambda _i: self._sync_panel())
        self.canvas.itemChanged.connect(self._sync_panel)
        self.canvas.photoLoadRequested.connect(self._load_photo_dialog)

        self._build_menu()
        panel = self._build_panel()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.canvas)
        splitter.addWidget(panel)
        splitter.setStretchFactor(0, 1)
        splitter.setSizes([860, 320])
        self.setCentralWidget(splitter)

        self.statusBar().showMessage(
            "Колесо мыши — масштаб фото • Shift+колесо — наклон • "
            "Ctrl+колесо — масштаб просмотра • перетаскивание — сдвиг фото/карточки")
        self._sync_panel()

    # ------------------------------------------------------------------ меню
    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("Файл")

        act_open = QAction("Загрузить фото…", self)
        act_open.setShortcut("Ctrl+O")
        act_open.triggered.connect(lambda: self._load_photo_dialog(self._selected_index()))
        file_menu.addAction(act_open)

        act_save = QAction("Сохранить лист 10×15…", self)
        act_save.setShortcut("Ctrl+S")
        act_save.triggered.connect(self._export_dialog)
        file_menu.addAction(act_save)

        act_print = QAction("Печать…", self)
        act_print.setShortcut("Ctrl+P")
        act_print.triggered.connect(self._print_dialog)
        file_menu.addAction(act_print)

        file_menu.addSeparator()
        act_quit = QAction("Выход", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        help_menu = self.menuBar().addMenu("Справка")
        act_about = QAction("О программе", self)
        act_about.triggered.connect(self._about)
        help_menu.addAction(act_about)

    # ---------------------------------------------------------------- панель
    def _build_panel(self) -> QWidget:
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setSpacing(12)

        # --- Лист ---
        g_sheet = QGroupBox("Лист 10×15 см")
        gl = QVBoxLayout(g_sheet)
        self.rb_land = QRadioButton("Альбомная 15×10")
        self.rb_port = QRadioButton("Книжная 10×15")
        self.rb_land.setChecked(True)
        self.rb_land.toggled.connect(self._orientation_changed)
        row = QHBoxLayout()
        row.addWidget(self.rb_land)
        row.addWidget(self.rb_port)
        gl.addLayout(row)

        gl.addWidget(QLabel("Снимков на листе:"))
        self.count_group = QButtonGroup(self)
        row = QHBoxLayout()
        self.count_buttons: dict[int, QRadioButton] = {}
        for n in (1, 2, 4):
            rb = QRadioButton(str(n))
            rb.setChecked(n == 1)
            self.count_group.addButton(rb, n)
            self.count_buttons[n] = rb
            row.addWidget(rb)
        self.count_group.idToggled.connect(
            lambda count, checked: checked and self._count_changed(count))
        gl.addLayout(row)

        btn_reset_layout = QPushButton("Сбросить расположение")
        btn_reset_layout.clicked.connect(self._reset_layout)
        gl.addWidget(btn_reset_layout)
        lay.addWidget(g_sheet)

        # --- Выбранный полароид ---
        g_item = QGroupBox("Выбранный полароид")
        il = QVBoxLayout(g_item)
        self.slot_label = QLabel("Слот 1")
        self.slot_label.setStyleSheet("font-weight: 600;")
        il.addWidget(self.slot_label)

        btn_load = QPushButton("Загрузить фото…")
        btn_load.clicked.connect(lambda: self._load_photo_dialog(self._selected_index()))
        il.addWidget(btn_load)

        btn_dup = QPushButton("Это же фото — во все слоты")
        btn_dup.clicked.connect(self._duplicate_to_all)
        il.addWidget(btn_dup)

        il.addWidget(QLabel("Наклон, °"))
        row = QHBoxLayout()
        self.rot_slider = QSlider(Qt.Orientation.Horizontal)
        self.rot_slider.setRange(-450, 450)  # десятые градуса
        self.rot_slider.valueChanged.connect(
            lambda v: self._set_item(rotation=v / 10.0))
        self.rot_spin = QDoubleSpinBox()
        self.rot_spin.setRange(-45.0, 45.0)
        self.rot_spin.setSingleStep(0.5)
        self.rot_spin.setDecimals(1)
        self.rot_spin.setSuffix("°")
        self.rot_spin.valueChanged.connect(lambda v: self._set_item(rotation=v))
        row.addWidget(self.rot_slider, 1)
        row.addWidget(self.rot_spin)
        il.addLayout(row)

        il.addWidget(QLabel("Масштаб фото"))
        row = QHBoxLayout()
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(100, 400)
        self.zoom_slider.valueChanged.connect(
            lambda v: self._set_item(zoom=v / 100.0))
        self.zoom_spin = QSpinBox()
        self.zoom_spin.setRange(100, 600)
        self.zoom_spin.setSuffix("%")
        self.zoom_spin.valueChanged.connect(
            lambda v: self._set_item(zoom=v / 100.0))
        row.addWidget(self.zoom_slider, 1)
        row.addWidget(self.zoom_spin)
        il.addLayout(row)

        row = QHBoxLayout()
        btn_center = QPushButton("Фото по центру")
        btn_center.clicked.connect(lambda: self._set_item(offset_x=0.5, offset_y=0.5))
        btn_straight = QPushButton("Наклон 0°")
        btn_straight.clicked.connect(lambda: self._set_item(rotation=0.0))
        row.addWidget(btn_center)
        row.addWidget(btn_straight)
        il.addLayout(row)

        il.addWidget(QLabel("Подпись на рамке"))
        self.caption_edit = QLineEdit()
        self.caption_edit.setPlaceholderText("Например: лето 2026 ♡")
        self.caption_edit.setMaxLength(40)
        self.caption_edit.textChanged.connect(
            lambda t: self._set_item(caption=t, refresh_pixmap=False))
        il.addWidget(self.caption_edit)

        il.addWidget(QLabel("Фильтр в стиле плёнки"))
        self.filter_combo = QComboBox()
        for key, title in FILTERS.items():
            self.filter_combo.addItem(title, key)
        self.filter_combo.currentIndexChanged.connect(
            lambda: self._set_item(filter=self.filter_combo.currentData()))
        il.addWidget(self.filter_combo)
        lay.addWidget(g_item)

        # --- Готово ---
        g_out = QGroupBox("Готовый лист")
        ol = QVBoxLayout(g_out)
        self.size_label = QLabel()
        self.size_label.setStyleSheet("color: #666;")
        ol.addWidget(self.size_label)
        btn_save = QPushButton("Сохранить JPG/PNG (300 DPI)…")
        btn_save.setMinimumHeight(38)
        btn_save.clicked.connect(self._export_dialog)
        ol.addWidget(btn_save)
        btn_print = QPushButton("Печать 10×15…")
        btn_print.clicked.connect(self._print_dialog)
        ol.addWidget(btn_print)
        lay.addWidget(g_out)

        hint = QLabel(
            "<b>Управление на холсте</b><br>"
            "Колесо — масштаб фото<br>"
            "Shift + колесо — наклон<br>"
            "Ctrl + колесо — масштаб просмотра<br>"
            "Тянуть фото — сдвиг в рамке<br>"
            "Тянуть рамку — двигать карточку<br>"
            "Ручка сверху / Alt + тянуть — наклон<br>"
            "Двойной клик — загрузить фото<br>"
            "Стрелки — точный сдвиг фото<br>"
            "Файл фото можно просто перетащить в окно")
        hint.setStyleSheet("color:#666;")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(330)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        return scroll

    # ------------------------------------------------------------- помощники
    def _selected_index(self) -> int:
        return self.canvas.selected

    def _item(self) -> PolaroidItem:
        return self.project.items[self._selected_index()]

    def _set_item(self, refresh_pixmap: bool = True, **fields) -> None:
        item = self._item()
        for name, value in fields.items():
            setattr(item, name, value)
        item.clamp()
        if refresh_pixmap and "filter" in fields:
            self.canvas.refresh_item_pixmap(self._selected_index())
        self.canvas.update()
        self._sync_panel(from_item=True)

    def _sync_panel(self, from_item: bool = False) -> None:
        if not self.project.items:
            return
        item = self._item()
        self.slot_label.setText(
            f"Слот {self._selected_index() + 1} из {len(self.project.items)}"
            + ("" if item.photo_path else " — фото не загружено"))
        w_cm, h_cm = (15, 10) if self.project.landscape else (10, 15)
        self.size_label.setText(
            f"Файл: {self.project.sheet_w}×{self.project.sheet_h} px\n"
            f"Печать: {w_cm}×{h_cm} см при 300 DPI")

        blockers = [w.blockSignals(True) for w in
                    (self.rot_slider, self.rot_spin, self.zoom_slider,
                     self.zoom_spin, self.caption_edit, self.filter_combo)]
        try:
            self.rot_slider.setValue(int(round(item.rotation * 10)))
            self.rot_spin.setValue(item.rotation)
            self.zoom_slider.setValue(min(400, int(round(item.zoom * 100))))
            self.zoom_spin.setValue(int(round(item.zoom * 100)))
            if self.caption_edit.text() != item.caption:
                self.caption_edit.setText(item.caption)
            idx = self.filter_combo.findData(item.filter)
            if idx >= 0:
                self.filter_combo.setCurrentIndex(idx)
        finally:
            for w, b in zip((self.rot_slider, self.rot_spin, self.zoom_slider,
                             self.zoom_spin, self.caption_edit, self.filter_combo),
                            blockers):
                w.blockSignals(b)

    # ------------------------------------------------------------- действия
    def _orientation_changed(self, _checked: bool) -> None:
        self.project.set_layout(len(self.project.items), landscape=self.rb_land.isChecked())
        self.canvas.on_layout_changed()
        self.canvas.reset_view()
        self._sync_panel()

    def _count_changed(self, count: int) -> None:
        self.project.set_layout(count)
        if self.canvas.selected >= count:
            self.canvas.selected = 0
        self.canvas.on_layout_changed()
        self._sync_panel()

    def _reset_layout(self) -> None:
        self.project.set_layout(len(self.project.items), landscape=self.rb_land.isChecked())
        self.canvas.on_layout_changed()
        self.canvas.reset_view()

    def _load_photo_dialog(self, slot: int) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Выберите фото", "", IMAGE_FILTER)
        if path:
            self._load_photo_into(slot, path)
            self.canvas.select(slot)

    def _load_photo_into(self, slot: int, path: str) -> bool:
        try:
            size = load_photo(path).size
        except (OSError, UnidentifiedImageError) as exc:
            QMessageBox.warning(self, "Не удалось открыть фото",
                                f"{os.path.basename(path)}\n\n{exc}")
            return False
        item = self.project.items[slot]
        keep_filter, keep_caption = item.filter, item.caption
        item.set_photo(path, size)
        item.filter, item.caption = keep_filter, keep_caption
        self.canvas.refresh_item_pixmap(slot)
        self._sync_panel()
        self.statusBar().showMessage(f"Фото загружено в слот {slot + 1}: {path}", 5000)
        return True

    def _duplicate_to_all(self) -> None:
        src = self._item()
        if not src.photo_path:
            QMessageBox.information(self, "Нет фото",
                                    "Сначала загрузите фото в выбранный слот.")
            return
        for i, item in enumerate(self.project.items):
            if item is src:
                continue
            item.photo_path = src.photo_path
            item.photo_size = src.photo_size
            item.zoom, item.offset_x, item.offset_y = src.zoom, src.offset_x, src.offset_y
            item.filter = src.filter
            self.canvas.refresh_item_pixmap(i)
        self.canvas.update()

    def _warn_empty_slots(self) -> bool:
        empty = [i + 1 for i, it in enumerate(self.project.items) if not it.photo_path]
        if not empty:
            return True
        answer = QMessageBox.question(
            self, "Есть пустые слоты",
            f"Слоты без фото: {', '.join(map(str, empty))}. "
            "На готовом листе они останутся серыми.\n\nПродолжить?")
        return answer == QMessageBox.StandardButton.Yes

    def _export_dialog(self) -> None:
        if not self._warn_empty_slots():
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Сохранить лист 10×15", "polaroid_10x15.jpg",
            "JPEG — для печати (*.jpg);;PNG (*.png)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".png" if "PNG" in selected_filter else ".jpg"
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            save_sheet(self.project, path)
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Ошибка сохранения", str(exc))
            return
        QApplication.restoreOverrideCursor()
        QMessageBox.information(
            self, "Готово",
            f"Лист сохранён:\n{path}\n\n"
            f"Размер: {self.project.sheet_w}×{self.project.sheet_h} px, 300 DPI — "
            "можно печатать как фото 10×15.")

    def _print_dialog(self) -> None:
        if not self._warn_empty_slots():
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            pil_img = render_sheet(self.project)
        finally:
            QApplication.restoreOverrideCursor()
        qimg = QImage(pil_img.tobytes(), pil_img.width, pil_img.height,
                      pil_img.width * 3, QImage.Format.Format_RGB888).copy()

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setResolution(300)
        from PySide6.QtGui import QPageSize
        w_mm, h_mm = (150, 100) if self.project.landscape else (100, 150)
        printer.setPageSize(QPageSize(QSizeF(w_mm, h_mm), QPageSize.Unit.Millimeter))
        printer.setFullPage(True)
        printer.setPageMargins(0, 0, 0, 0, QPrinter.Unit.Millimeter)

        dialog = QPrintDialog(printer, self)
        dialog.setWindowTitle("Печать листа 10×15")
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return
        painter = QPainter(printer)
        rect: QRect = printer.pageRect(QPrinter.Unit.DevicePixel)
        painter.drawImage(rect, qimg)
        painter.end()
        self.statusBar().showMessage("Лист отправлен на печать", 5000)

    def _about(self) -> None:
        QMessageBox.about(
            self, "О программе",
            f"<b>Softpalaroid {__version__}</b><br><br>"
            "Создание полароидных снимков из фотографий и их раскладка "
            "на листе 10×15 см для печати (300 DPI).<br><br>"
            "Наклон, масштаб и сдвиг фото редактируются прямо "
            "в окне предпросмотра — мышью и с панели справа.")

    # ---------------------------------------------------------- drag & drop
    def dragEnterEvent(self, e: QDragEnterEvent) -> None:  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent) -> None:  # noqa: N802
        files = [u.toLocalFile() for u in e.mimeData().urls()
                 if u.toLocalFile().lower().endswith(IMAGE_EXTS)]
        if not files:
            return
        slot = self._selected_index()
        for path in files:
            if slot >= len(self.project.items):
                break
            if self._load_photo_into(slot, path):
                slot += 1
        e.acceptProposedAction()
