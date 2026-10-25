"""Главное окно Softpalaroid."""
from __future__ import annotations

import copy
import os
import tempfile
from datetime import datetime

from PIL import UnidentifiedImageError
from PySide6.QtCore import QRect, QSettings, QSize, QSizeF, QStandardPaths, QTimer, Qt
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QImage,
    QKeySequence,
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
from .project_io import (
    PROJECT_EXTENSION,
    PROJECT_FILE_FILTER,
    ProjectFileError,
    load_project_file,
    project_state_key,
    save_project_file,
)
from .render import load_photo, render_sheet, save_sheet
from .resources import asset_path

IMAGE_FILTER = "Изображения (*.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff);;Все файлы (*)"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff")
HISTORY_LIMIT = 100
AUTOSAVE_FILENAME = "autosave.softpalaroid"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Softpalaroid — полароиды на листе 10×15")
        self.resize(1260, 820)
        self.setMinimumSize(1000, 640)
        self.setAcceptDrops(True)

        self.project = Project()
        self.project.set_layout(1, landscape=True)

        # Состояние проекта, истории и автосохранения
        self._settings = QSettings("Softpalaroid", "Softpalaroid")
        self._project_path: str | None = None
        self._project_tempdir: tempfile.TemporaryDirectory | None = None
        self._saved_state_key: str | None = project_state_key(self.project)
        self._undo_stack: list[tuple[Project, int]] = []
        self._redo_stack: list[tuple[Project, int]] = []
        self._pending_before: tuple[Project, int] | None = None
        self._applying_state = False
        self._skip_unsaved_prompt = False
        self._recent_menus: list[QMenu] = []
        self._subtitle_label: QLabel | None = None

        self._history_timer = QTimer(self)
        self._history_timer.setSingleShot(True)
        self._history_timer.setInterval(700)
        self._history_timer.timeout.connect(self._flush_pending_history)

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(1500)
        self._autosave_timer.timeout.connect(self._write_autosave)

        self.canvas = CanvasWidget()
        self.canvas.set_project(self.project)
        self.canvas.selectionChanged.connect(lambda _i: self._sync_panel())
        self.canvas.itemChanged.connect(self._sync_panel)
        self.canvas.itemChanged.connect(self._update_project_ui)
        self.canvas.photoLoadRequested.connect(self._load_photo_dialog)
        self.canvas.editStarted.connect(self._begin_canvas_edit)
        self.canvas.editFinished.connect(self._finish_canvas_edit)

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
        self._update_project_ui()
        self._update_history_actions()

    # ------------------------------------------------------- действия и шапка
    def _build_actions(self) -> None:
        self.act_new_project = QAction("Новый проект", self)
        self.act_new_project.setShortcut("Ctrl+N")
        self.act_new_project.triggered.connect(self._new_project)

        self.act_open_project = QAction("Открыть проект…", self)
        self.act_open_project.setShortcut("Ctrl+Shift+O")
        self.act_open_project.triggered.connect(self._open_project_dialog)

        self.act_save_project = QAction("Сохранить проект", self)
        self.act_save_project.setShortcut("Ctrl+S")
        self.act_save_project.triggered.connect(self._save_project)

        self.act_save_project_as = QAction("Сохранить проект как…", self)
        self.act_save_project_as.setShortcut("Ctrl+Shift+S")
        self.act_save_project_as.triggered.connect(self._save_project_as)

        self.act_open = QAction("Загрузить фото…", self)
        self.act_open.setShortcut("Ctrl+O")
        self.act_open.triggered.connect(
            lambda: self._load_photo_dialog(self._selected_index()))

        self.act_export = QAction("Экспорт листа JPG/PNG…", self)
        self.act_export.setShortcut("Ctrl+E")
        self.act_export.triggered.connect(self._export_dialog)

        self.act_print = QAction("Печать…", self)
        self.act_print.setShortcut("Ctrl+P")
        self.act_print.triggered.connect(self._print_dialog)

        self.act_undo = QAction("Отменить", self)
        self.act_undo.setShortcut("Ctrl+Z")
        self.act_undo.triggered.connect(self._undo)
        self.act_undo.setEnabled(False)

        self.act_redo = QAction("Повторить", self)
        self.act_redo.setShortcuts(
            [QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        self.act_redo.triggered.connect(self._redo)
        self.act_redo.setEnabled(False)

        self.act_about = QAction("О программе", self)
        self.act_about.triggered.connect(self._about)

        self.act_quit = QAction("Выход", self)
        self.act_quit.setShortcut("Ctrl+Q")
        self.act_quit.triggered.connect(self.close)

        self.addActions([
            self.act_new_project, self.act_open_project,
            self.act_save_project, self.act_save_project_as,
            self.act_open, self.act_export, self.act_print,
            self.act_undo, self.act_redo, self.act_about, self.act_quit,
        ])

    # -------------------------------------------------------- недавние проекты
    def _recent_project_paths(self) -> list[str]:
        value = self._settings.value("recentProjects", [])
        if isinstance(value, str):
            return [value] if value else []
        if isinstance(value, (list, tuple)):
            return [str(v) for v in value if str(v)]
        return []

    def _add_recent_project(self, path: str) -> None:
        absolute = os.path.abspath(path)
        paths = [p for p in self._recent_project_paths()
                 if os.path.abspath(p) != absolute]
        paths.insert(0, absolute)
        self._settings.setValue("recentProjects", paths[:8])
        self._settings.sync()
        self._refresh_recent_menus()

    def _remove_recent_project(self, path: str) -> None:
        absolute = os.path.abspath(path)
        paths = [p for p in self._recent_project_paths()
                 if os.path.abspath(p) != absolute]
        self._settings.setValue("recentProjects", paths)
        self._settings.sync()
        self._refresh_recent_menus()

    def _clear_recent_projects(self) -> None:
        self._settings.remove("recentProjects")
        self._settings.sync()
        self._refresh_recent_menus()

    def _refresh_recent_menus(self) -> None:
        paths = self._recent_project_paths()
        for menu in self._recent_menus:
            menu.clear()
            if not paths:
                empty = QAction("Нет недавних проектов", menu)
                empty.setEnabled(False)
                menu.addAction(empty)
                continue
            for path in paths:
                action = QAction(os.path.basename(path), menu)
                action.setToolTip(path)
                action.triggered.connect(
                    lambda _checked=False, p=path: self._open_project_from(p))
                menu.addAction(action)
            menu.addSeparator()
            clear = QAction("Очистить список", menu)
            clear.triggered.connect(self._clear_recent_projects)
            menu.addAction(clear)

    def _make_project_menu(self, parent: QWidget) -> QMenu:
        menu = QMenu("Проект", parent)
        menu.addActions([self.act_new_project, self.act_open_project])
        recent = menu.addMenu("Недавние проекты")
        self._recent_menus.append(recent)
        menu.addSeparator()
        menu.addActions([self.act_save_project, self.act_save_project_as])
        self._refresh_recent_menus()
        return menu

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
        subtitle = QLabel("Новый проект · лист 10×15")
        subtitle.setObjectName("appSubtitle")
        self._subtitle_label = subtitle
        titles.addWidget(title)
        titles.addWidget(subtitle)
        lay.addLayout(titles)
        lay.addStretch(1)

        version = QLabel(f"v{__version__}")
        version.setObjectName("versionChip")
        lay.addWidget(version)

        self._undo_button = QToolButton()
        self._undo_button.setObjectName("moreButton")
        self._undo_button.setText("↶")
        self._undo_button.setToolTip("Отменить (Ctrl+Z)")
        self._undo_button.setAccessibleName("Отменить")
        self._undo_button.setFixedSize(42, 42)
        self._undo_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._undo_button.clicked.connect(self.act_undo.trigger)
        self._undo_button.setEnabled(False)
        lay.addWidget(self._undo_button)

        self._redo_button = QToolButton()
        self._redo_button.setObjectName("moreButton")
        self._redo_button.setText("↷")
        self._redo_button.setToolTip("Повторить (Ctrl+Y)")
        self._redo_button.setAccessibleName("Повторить")
        self._redo_button.setFixedSize(42, 42)
        self._redo_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._redo_button.clicked.connect(self.act_redo.trigger)
        self._redo_button.setEnabled(False)
        lay.addWidget(self._redo_button)

        project_button = QToolButton()
        project_button.setText("Проект ▾")
        project_button.setMinimumHeight(42)
        project_button.setCursor(Qt.CursorShape.PointingHandCursor)
        project_button.setToolTip("Новый, открыть или сохранить проект")
        project_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup)
        project_button.setMenu(self._make_project_menu(project_button))
        lay.addWidget(project_button)

        btn_print = QPushButton("Печать")
        btn_print.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_print.setMinimumHeight(42)
        btn_print.clicked.connect(self._print_dialog)
        lay.addWidget(btn_print)

        btn_save = QPushButton("Экспорт листа")
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
        menu.addActions([self.act_undo, self.act_redo])
        menu.addSeparator()
        menu.addMenu(self._make_project_menu(menu))
        menu.addActions([self.act_open, self.act_export, self.act_print])
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
        before = self._snapshot_state()
        item = self._item()
        for name, value in fields.items():
            setattr(item, name, value)
        item.clamp()
        if refresh_pixmap and "filter" in fields:
            self.canvas.refresh_item_pixmap(self._selected_index())
        self.canvas.update()
        self._sync_panel(from_item=True)
        self._note_change(before)

    # -------------------------------------------- состояние, история, автосейв
    def _snapshot_state(self) -> tuple[Project, int]:
        return (copy.deepcopy(self.project), self.canvas.selected)

    def _is_dirty(self) -> bool:
        return self._saved_state_key is None \
            or project_state_key(self.project) != self._saved_state_key

    def _update_project_ui(self) -> None:
        dirty = self._is_dirty()
        name = os.path.basename(self._project_path) \
            if self._project_path else "Новый проект"
        self.setWindowTitle(
            f"Softpalaroid — {name}{' *' if dirty else ''}")
        if self._subtitle_label is not None:
            if self._project_path:
                state = "не сохранено" if dirty else "сохранено"
                self._subtitle_label.setText(f"{name} · {state} · лист 10×15")
            elif dirty:
                self._subtitle_label.setText("Новый проект · не сохранено · лист 10×15")
            else:
                self._subtitle_label.setText("Новый проект · лист 10×15")

    def _update_history_actions(self) -> None:
        can_undo = bool(self._undo_stack or self._pending_before)
        can_redo = bool(self._redo_stack)
        if hasattr(self, "act_undo"):
            self.act_undo.setEnabled(can_undo)
        if hasattr(self, "act_redo"):
            self.act_redo.setEnabled(can_redo)
        if hasattr(self, "_undo_button"):
            self._undo_button.setEnabled(can_undo)
        if hasattr(self, "_redo_button"):
            self._redo_button.setEnabled(can_redo)

    def _after_state_changed(self) -> None:
        self._update_project_ui()
        self._update_history_actions()
        if self._is_dirty():
            self._autosave_timer.start()
        else:
            self._autosave_timer.stop()
            self._remove_autosave_file()

    def _push_before(self, before: tuple[Project, int]) -> None:
        if project_state_key(before[0]) == project_state_key(self.project):
            return
        self._undo_stack.append(before)
        if len(self._undo_stack) > HISTORY_LIMIT:
            del self._undo_stack[:len(self._undo_stack) - HISTORY_LIMIT]
        self._redo_stack.clear()

    def _note_change(self, before: tuple[Project, int] | None = None) -> None:
        """Зафиксировать изменение с объединением непрерывных правок."""
        if self._applying_state:
            self._after_state_changed()
            return
        if before is not None and self._pending_before is None:
            self._pending_before = before
        if self._pending_before is not None:
            self._history_timer.start()
        self._after_state_changed()

    def _commit_change(self, before: tuple[Project, int] | None = None) -> None:
        self._history_timer.stop()
        candidate = self._pending_before or before
        self._pending_before = None
        if not self._applying_state and candidate is not None:
            self._push_before(candidate)
        self._after_state_changed()

    def _flush_pending_history(self) -> None:
        if self._pending_before is not None:
            self._commit_change()

    def _clear_history(self) -> None:
        self._history_timer.stop()
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._pending_before = None
        self._update_history_actions()

    def _begin_canvas_edit(self) -> None:
        if self._applying_state:
            return
        if self._pending_before is None:
            self._pending_before = self._snapshot_state()
        self._history_timer.stop()
        self._update_history_actions()

    def _finish_canvas_edit(self) -> None:
        self._commit_change()

    def _sync_layout_controls(self) -> None:
        if not hasattr(self, "rb_land"):
            return
        controls = [self.rb_land, self.rb_port, *self.count_buttons.values()]
        blockers = [c.blockSignals(True) for c in controls]
        try:
            self.rb_land.setChecked(self.project.landscape)
            self.rb_port.setChecked(not self.project.landscape)
            for count, button in self.count_buttons.items():
                button.setChecked(count == len(self.project.items))
        finally:
            for control, blocked in zip(controls, blockers):
                control.blockSignals(blocked)

    def _apply_state(self, state: tuple[Project, int]) -> None:
        project, selected = state
        self._applying_state = True
        self._history_timer.stop()
        try:
            self.project.landscape = project.landscape
            self.project.items = copy.deepcopy(project.items)
            if self.project.items:
                self.canvas.selected = max(
                    0, min(len(self.project.items) - 1, selected))
            else:
                self.canvas.selected = 0
            self.canvas.refresh_all_pixmaps()
            self._sync_layout_controls()
            self._sync_panel()
            self.canvas.update()
        finally:
            self._applying_state = False
        self._after_state_changed()

    def _replace_project(self, project: Project, selected: int = 0) -> None:
        self._clear_history()
        self._apply_state((project, selected))
        self._clear_history()

    def _undo(self) -> None:
        self._flush_pending_history()
        if not self._undo_stack:
            return
        current = self._snapshot_state()
        target = self._undo_stack.pop()
        self._redo_stack.append(current)
        self._apply_state(target)
        self.statusBar().showMessage("Действие отменено", 2500)

    def _redo(self) -> None:
        self._flush_pending_history()
        if not self._redo_stack:
            return
        current = self._snapshot_state()
        target = self._redo_stack.pop()
        self._undo_stack.append(current)
        self._apply_state(target)
        self.statusBar().showMessage("Действие повторено", 2500)

    # ------------------------------------------------------------- автосейв
    def _autosave_path(self) -> str:
        root = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation)
        if not root:
            root = os.path.join(os.path.expanduser("~"), ".softpalaroid")
        return os.path.join(root, AUTOSAVE_FILENAME)

    def _write_autosave(self) -> None:
        if self._applying_state or not self._is_dirty():
            return
        try:
            save_project_file(
                self.project,
                self._autosave_path(),
                selected_index=self.canvas.selected,
                metadata={
                    "autosave": True,
                    "source_path": self._project_path or "",
                },
            )
        except Exception as exc:  # noqa: BLE001 - автосейв не должен ронять GUI
            self.statusBar().showMessage(
                f"Автосохранение не удалось: {exc}", 5000)

    def _remove_autosave_file(self) -> None:
        try:
            path = self._autosave_path()
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass

    def offer_autosave_recovery(self) -> None:
        """Предложить восстановить работу после аварийного завершения."""
        path = self._autosave_path()
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            return
        try:
            when = datetime.fromtimestamp(os.path.getmtime(path)) \
                .astimezone().strftime("%d.%m.%Y %H:%M")
        except OSError:
            when = "неизвестно"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Восстановление работы")
        box.setText(
            "Найдено автосохранение несохранённой работы "
            f"({when}). Восстановить его?")
        restore = box.addButton(
            "Восстановить", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(
            "Удалить автосохранение", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(restore)
        box.exec()
        if box.clickedButton() is restore:
            self._open_project_from(
                path, confirm_discard=False,
                add_recent=False, from_autosave=True)
        else:
            self._remove_autosave_file()

    # --------------------------------------------------------------- проекты
    def _set_project_tempdir(
            self, tempdir: tempfile.TemporaryDirectory | None) -> None:
        old = self._project_tempdir
        self._project_tempdir = tempdir
        if old is not None and old is not tempdir:
            try:
                old.cleanup()
            except OSError:
                pass

    def _cleanup_project_tempdir(self) -> None:
        self._set_project_tempdir(None)

    def _confirm_discard_changes(self) -> bool:
        self._flush_pending_history()
        if self._skip_unsaved_prompt or not self._is_dirty():
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Несохранённые изменения")
        box.setText("В проекте есть несохранённые изменения. Сохранить их?")
        save_button = box.addButton(
            "Сохранить", QMessageBox.ButtonRole.AcceptRole)
        discard_button = box.addButton(
            "Не сохранять", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save_button)
        box.exec()
        if box.clickedButton() is save_button:
            return self._save_project()
        return box.clickedButton() is discard_button

    def _new_project(self) -> None:
        if not self._confirm_discard_changes():
            return
        project = Project()
        project.set_layout(1, landscape=True)
        self._replace_project(project, 0)
        self._cleanup_project_tempdir()
        self._project_path = None
        self._saved_state_key = project_state_key(self.project)
        self._remove_autosave_file()
        self.canvas.reset_view()
        self._after_state_changed()
        self.statusBar().showMessage("Создан новый проект", 3000)

    def _open_project_dialog(self) -> None:
        start = self._project_path or ""
        if not start:
            recent = self._recent_project_paths()
            start = recent[0] if recent else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть проект Softpalaroid", start, PROJECT_FILE_FILTER)
        if path:
            self._open_project_from(path)

    def _open_project_from(self, path: str, *,
                           confirm_discard: bool = True,
                           add_recent: bool = True,
                           from_autosave: bool = False) -> bool:
        if confirm_discard and not self._confirm_discard_changes():
            return False
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            QMessageBox.warning(
                self, "Проект не найден",
                f"Файл проекта не существует:\n{path}")
            if add_recent:
                self._remove_recent_project(path)
            return False

        tempdir = tempfile.TemporaryDirectory(prefix="softpalaroid-project-")
        try:
            loaded = load_project_file(path, tempdir.name)
        except (ProjectFileError, OSError) as exc:
            tempdir.cleanup()
            QMessageBox.critical(
                self, "Не удалось открыть проект",
                f"{os.path.basename(path)}\n\n{exc}")
            return False

        self._replace_project(loaded.project, loaded.selected_index)
        self._set_project_tempdir(tempdir)

        if from_autosave:
            source = loaded.metadata.get("source_path")
            self._project_path = source if isinstance(source, str) \
                and source and os.path.abspath(source) != path else None
            self._saved_state_key = None  # восстановленная работа не сохранена
            message = "Несохранённая работа восстановлена"
        else:
            self._project_path = path
            self._saved_state_key = None if loaded.warnings \
                else project_state_key(self.project)
            if add_recent:
                self._add_recent_project(path)
            if not loaded.warnings:
                self._remove_autosave_file()
            message = f"Проект открыт: {os.path.basename(path)}"

        self.canvas.reset_view()
        self._after_state_changed()
        self.statusBar().showMessage(message, 5000)
        if loaded.warnings:
            QMessageBox.warning(
                self, "Проект открыт с предупреждениями",
                "\n".join(loaded.warnings))
        return True

    def _save_project(self) -> bool:
        if not self._project_path:
            return self._save_project_as()
        return self._save_project_to(self._project_path)

    def _save_project_as(self) -> bool:
        start = self._project_path or f"Без названия{PROJECT_EXTENSION}"
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить проект Softpalaroid", start, PROJECT_FILE_FILTER)
        if not path:
            return False
        if not os.path.splitext(path)[1]:
            path += PROJECT_EXTENSION
        return self._save_project_to(path)

    def _save_project_to(self, path: str) -> bool:
        self._flush_pending_history()
        path = os.path.abspath(path)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            save_project_file(
                self.project, path,
                selected_index=self.canvas.selected,
                metadata={"source_path": path},
            )
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(
                self, "Не удалось сохранить проект",
                f"{os.path.basename(path)}\n\n{exc}")
            return False
        QApplication.restoreOverrideCursor()
        self._project_path = path
        self._saved_state_key = project_state_key(self.project)
        self._add_recent_project(path)
        self._remove_autosave_file()
        self._after_state_changed()
        self.statusBar().showMessage(
            f"Проект сохранён: {os.path.basename(path)}", 5000)
        return True

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._flush_pending_history()
        if not self._confirm_discard_changes():
            event.ignore()
            return
        self._history_timer.stop()
        self._autosave_timer.stop()
        self._remove_autosave_file()
        self._cleanup_project_tempdir()
        super().closeEvent(event)

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
        before = self._snapshot_state()
        self.project.set_layout(len(self.project.items), landscape=self.rb_land.isChecked())
        self.canvas.on_layout_changed()
        self.canvas.reset_view()
        self._sync_panel()
        self._commit_change(before)

    def _count_changed(self, count: int) -> None:
        before = self._snapshot_state()
        self.project.set_layout(count)
        if self.canvas.selected >= count:
            self.canvas.selected = 0
        self.canvas.on_layout_changed()
        self._sync_panel()
        self._commit_change(before)

    def _reset_layout(self) -> None:
        before = self._snapshot_state()
        self.project.set_layout(len(self.project.items), landscape=self.rb_land.isChecked())
        self.canvas.on_layout_changed()
        self.canvas.reset_view()
        self._commit_change(before)

    def _load_photo_dialog(self, slot: int) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Выберите фото", "", IMAGE_FILTER)
        if path:
            self._load_photo_into(slot, path)
            self.canvas.select(slot)

    def _load_photo_into(self, slot: int, path: str,
                         *, record_history: bool = True) -> bool:
        try:
            size = load_photo(path).size
        except (OSError, UnidentifiedImageError) as exc:
            QMessageBox.warning(self, "Не удалось открыть фото",
                                f"{os.path.basename(path)}\n\n{exc}")
            return False
        before = self._snapshot_state() if record_history else None
        item = self.project.items[slot]
        keep_filter, keep_caption = item.filter, item.caption
        item.set_photo(path, size)
        item.filter, item.caption = keep_filter, keep_caption
        self.canvas.refresh_item_pixmap(slot)
        self._sync_panel()
        self.statusBar().showMessage(
            f"Фото добавлено в слот {slot + 1}: {os.path.basename(path)}", 5000)
        if before is not None:
            self._commit_change(before)
        return True

    def _duplicate_to_all(self) -> None:
        src = self._item()
        if not src.photo_path:
            QMessageBox.information(self, "Нет фото",
                                    "Сначала загрузите фото в выбранный слот.")
            return
        before = self._snapshot_state()
        for i, item in enumerate(self.project.items):
            if item is src:
                continue
            item.photo_path = src.photo_path
            item.photo_size = src.photo_size
            item.zoom, item.offset_x, item.offset_y = src.zoom, src.offset_x, src.offset_y
            item.filter = src.filter
            self.canvas.refresh_item_pixmap(i)
        self.canvas.update()
        self._commit_change(before)

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
        before = self._snapshot_state()
        loaded_any = False
        slot = self._selected_index()
        for path in files:
            if slot >= len(self.project.items):
                break
            if self._load_photo_into(slot, path, record_history=False):
                loaded_any = True
                slot += 1
        if loaded_any:
            self._commit_change(before)
        e.acceptProposedAction()
