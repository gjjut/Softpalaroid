"""Главное окно Softpalaroid."""
from __future__ import annotations

import os

from PIL import UnidentifiedImageError
from PySide6.QtCore import QRect, QSize, QSizeF, Qt
from PySide6.QtGui import (
    QAction,
    QDragEnterEvent,
    QDropEvent,
    QImage,
    QPainter,
    QPixmap,
)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .canvas import CanvasWidget
from .filters import FILTERS
from .model import PolaroidItem, Project
from .render import load_photo, render_sheet, save_sheet
from .resources import asset_path

IMAGE_FILTER = "Изображения (*.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff);;Все файлы (*)"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Softpalaroid — полароиды на листе 10×15")
        self.resize(1260, 820)
        self.setMinimumSize(1000, 640)
        self.setAcceptDrops(True)

        self.project = Project()
        self.project.set_layout(1, landscape=True)

        self.canvas = CanvasWidget()
        self.canvas.set_project(self.project)
        self.canvas.selectionChanged.connect(lambda _i: self._sync_panel())
        self.canvas.itemChanged.connect(self._sync_panel)
        self.canvas.photoLoadRequested.connect(self._load_photo_dialog)

        self._build_actions()
        panel = self._build_panel()

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.canvas)
        splitter.addWidget(panel)
        splitter.setStretchFactor(0, 1)
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([900, 360])
        root.addWidget(splitter, 1)
        self.setCentralWidget(central)

        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().showMessage(
            "Колесо мыши — масштаб фото • Shift+колесо — наклон • "
            "Ctrl+колесо — масштаб просмотра • перетаскивание — сдвиг фото/карточки")
        self._sync_panel()

    # ------------------------------------------------------- действия и шапка
    def _build_actions(self) -> None:
        self.act_open = QAction("Загрузить фото…", self)
        self.act_open.setShortcut("Ctrl+O")
        self.act_open.triggered.connect(
            lambda: self._load_photo_dialog(self._selected_index()))

        self.act_save = QAction("Сохранить лист 10×15…", self)
        self.act_save.setShortcut("Ctrl+S")
        self.act_save.triggered.connect(self._export_dialog)

        self.act_print = QAction("Печать…", self)
        self.act_print.setShortcut("Ctrl+P")
        self.act_print.triggered.connect(self._print_dialog)

        self.act_about = QAction("О программе", self)
        self.act_about.triggered.connect(self._about)

        self.act_quit = QAction("Выход", self)
        self.act_quit.setShortcut("Ctrl+Q")
        self.act_quit.triggered.connect(self.close)

        self.addActions([self.act_open, self.act_save, self.act_print,
                         self.act_about, self.act_quit])

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(68)
        lay = QHBoxLayout(header)
        lay.setContentsMargins(18, 10, 18, 10)
        lay.setSpacing(12)

        logo = QLabel()
        icon = asset_path("icon.png")
        if icon:
            logo.setPixmap(QPixmap(icon).scaled(
                QSize(38, 38), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            logo.setText("S")
        lay.addWidget(logo)

        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(0)
        title = QLabel("Softpalaroid")
        title.setObjectName("appTitle")
        subtitle = QLabel("Полароиды на листе 10×15 · готово к печати")
        subtitle.setObjectName("appSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        lay.addLayout(titles)
        lay.addStretch(1)

        version = QLabel(f"v{__version__}")
        version.setObjectName("versionChip")
        lay.addWidget(version)

        btn_print = QPushButton("Печать")
        btn_print.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_print.setMinimumHeight(42)
        btn_print.clicked.connect(self._print_dialog)
        lay.addWidget(btn_print)

        btn_save = QPushButton("Сохранить лист")
        btn_save.setObjectName("primaryButton")
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.setMinimumHeight(42)
        btn_save.clicked.connect(self._export_dialog)
        lay.addWidget(btn_save)

        more = QToolButton()
        more.setObjectName("moreButton")
        more.setText("···")
        more.setCursor(Qt.CursorShape.PointingHandCursor)
        more.setMinimumHeight(42)
        more.setToolTip("Ещё")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more)
        menu.addActions([self.act_open, self.act_save, self.act_print])
        menu.addSeparator()
        menu.addAction(self.act_about)
        menu.addSeparator()
        menu.addAction(self.act_quit)
        more.setMenu(menu)
        lay.addWidget(more)
        return header

    # ---------------------------------------------------------------- панель
    @staticmethod
    def _field_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "field")
        return label

    @staticmethod
    def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setProperty("card", True)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)
        heading = QLabel(title)
        heading.setProperty("role", "section")
        layout.addWidget(heading)
        return frame, layout

    @staticmethod
    def _segment_button(text: str) -> QPushButton:
        button = QPushButton(text)
        button.setProperty("segment", True)
        button.setCheckable(True)
        button.setMinimumHeight(36)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    @staticmethod
    def _ghost_button(text: str, height: int = 36) -> QPushButton:
        button = QPushButton(text)
        button.setMinimumHeight(height)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _build_panel(self) -> QWidget:
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(14)

        # --- Лист ---
        sheet_card, gl = self._card("Лист 10×15")
        gl.addWidget(self._field_label("Ориентация"))
        self.orientation_group = QButtonGroup(self)
        self.rb_land = self._segment_button("Альбомная")
        self.rb_port = self._segment_button("Книжная")
        self.orientation_group.addButton(self.rb_land)
        self.orientation_group.addButton(self.rb_port)
        self.rb_land.setChecked(True)
        self.rb_land.toggled.connect(self._orientation_changed)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.rb_land, 1)
        row.addWidget(self.rb_port, 1)
        gl.addLayout(row)

        gl.addWidget(self._field_label("Снимков на листе"))
        self.count_group = QButtonGroup(self)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.count_buttons: dict[int, QPushButton] = {}
        for n in (1, 2, 4):
            btn = self._segment_button(str(n))
            btn.setChecked(n == 1)
            self.count_group.addButton(btn, n)
            self.count_buttons[n] = btn
            row.addWidget(btn, 1)
        self.count_group.idToggled.connect(
            lambda count, checked: checked and self._count_changed(count))
        gl.addLayout(row)

        btn_reset_layout = self._ghost_button("Сбросить расположение")
        btn_reset_layout.clicked.connect(self._reset_layout)
        gl.addWidget(btn_reset_layout)
        lay.addWidget(sheet_card)

        # --- Выбранный полароид ---
        item_card, il = self._card("Полароид")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.slot_label = QLabel("Слот 1 / 1")
        self.slot_label.setObjectName("slotChip")
        self.slot_state = QLabel("Без фото")
        self.slot_state.setProperty("role", "muted")
        row.addWidget(self.slot_label)
        row.addWidget(self.slot_state, 1)
        il.addLayout(row)

        btn_load = QPushButton("+  Загрузить фото")
        btn_load.setObjectName("whiteButton")
        btn_load.setMinimumHeight(42)
        btn_load.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_load.clicked.connect(lambda: self._load_photo_dialog(self._selected_index()))
        il.addWidget(btn_load)

        btn_dup = self._ghost_button("Это же фото — во все слоты")
        btn_dup.clicked.connect(self._duplicate_to_all)
        il.addWidget(btn_dup)

        il.addWidget(self._field_label("Наклон"))
        row = QHBoxLayout()
        row.setSpacing(10)
        self.rot_slider = QSlider(Qt.Orientation.Horizontal)
        self.rot_slider.setRange(-450, 450)  # десятые градуса
        self.rot_slider.valueChanged.connect(
            lambda v: self._set_item(rotation=v / 10.0))
        self.rot_spin = QDoubleSpinBox()
        self.rot_spin.setRange(-45.0, 45.0)
        self.rot_spin.setSingleStep(0.5)
        self.rot_spin.setDecimals(1)
        self.rot_spin.setSuffix("°")
        self.rot_spin.setFixedWidth(88)
        self.rot_spin.setMinimumHeight(34)
        self.rot_spin.valueChanged.connect(lambda v: self._set_item(rotation=v))
        row.addWidget(self.rot_slider, 1)
        row.addWidget(self.rot_spin)
        il.addLayout(row)

        il.addWidget(self._field_label("Масштаб фото"))
        row = QHBoxLayout()
        row.setSpacing(10)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(100, 400)
        self.zoom_slider.valueChanged.connect(
            lambda v: self._set_item(zoom=v / 100.0))
        self.zoom_spin = QSpinBox()
        self.zoom_spin.setRange(100, 600)
        self.zoom_spin.setSuffix("%")
        self.zoom_spin.setFixedWidth(88)
        self.zoom_spin.setMinimumHeight(34)
        self.zoom_spin.valueChanged.connect(
            lambda v: self._set_item(zoom=v / 100.0))
        row.addWidget(self.zoom_slider, 1)
        row.addWidget(self.zoom_spin)
        il.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(8)
        btn_center = self._ghost_button("Фото по центру", 34)
        btn_center.clicked.connect(lambda: self._set_item(offset_x=0.5, offset_y=0.5))
        btn_straight = self._ghost_button("Наклон 0°", 34)
        btn_straight.clicked.connect(lambda: self._set_item(rotation=0.0))
        row.addWidget(btn_center, 1)
        row.addWidget(btn_straight, 1)
        il.addLayout(row)

        il.addWidget(self._field_label("Подпись на рамке"))
        self.caption_edit = QLineEdit()
        self.caption_edit.setPlaceholderText("лето 2026")
        self.caption_edit.setMaxLength(40)
        self.caption_edit.setMinimumHeight(40)
        self.caption_edit.textChanged.connect(
            lambda t: self._set_item(caption=t, refresh_pixmap=False))
        il.addWidget(self.caption_edit)

        il.addWidget(self._field_label("Фильтр в стиле плёнки"))
        self.filter_combo = QComboBox()
        self.filter_combo.setMinimumHeight(40)
        self.filter_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        for key, title in FILTERS.items():
            self.filter_combo.addItem(title, key)
        self.filter_combo.currentIndexChanged.connect(
            lambda: self._set_item(filter=self.filter_combo.currentData()))
        il.addWidget(self.filter_combo)
        lay.addWidget(item_card)

        # --- Готово ---
        out_card, ol = self._card("Готовый лист")
        self.size_label = QLabel()
        self.size_label.setProperty("role", "muted")
        self.size_label.setWordWrap(True)
        ol.addWidget(self.size_label)
        btn_save = QPushButton("Сохранить JPG/PNG · 300 DPI")
        btn_save.setObjectName("primaryButton")
        btn_save.setMinimumHeight(44)
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.clicked.connect(self._export_dialog)
        ol.addWidget(btn_save)
        btn_print = self._ghost_button("Печать 10×15", 38)
        btn_print.clicked.connect(self._print_dialog)
        ol.addWidget(btn_print)
        lay.addWidget(out_card)

        # --- Подсказки ---
        hint_card, hl = self._card("Управление на холсте")
        hint = QLabel(
            "Колесо — масштаб фото\n"
            "Shift + колесо — наклон\n"
            "Ctrl + колесо — масштаб просмотра\n"
            "Тянуть фото — сдвиг в рамке\n"
            "Тянуть рамку — двигать карточку\n"
            "Ручка сверху / Alt + тянуть — наклон\n"
            "Двойной клик — загрузить фото\n"
            "Стрелки — точный сдвиг фото\n\n"
            "Файл фото можно просто перетащить в окно.")
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        hl.addWidget(hint)
        lay.addWidget(hint_card)
        lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setObjectName("inspector")
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(356)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
            f"Слот {self._selected_index() + 1} / {len(self.project.items)}")
        self.slot_state.setText("Фото загружено" if item.photo_path else "Без фото")
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
        self.statusBar().showMessage(
            f"Фото добавлено в слот {slot + 1}: {os.path.basename(path)}", 5000)
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
            "в окне предпросмотра — мышью и с панели справа.<br><br>"
            "Тёмный интерфейс в стиле X. Шрифты: Inter и Caveat (OFL).")

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
