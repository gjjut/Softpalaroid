"""Главное окно Softpalaroid."""
from __future__ import annotations

import copy
import os
import tempfile
from datetime import datetime

from PIL import Image as PilImage, ImageDraw as PilDraw, UnidentifiedImageError
from PySide6.QtCore import (
    QPointF,
    QRect,
    QRectF,
    QSettings,
    QSize,
    QSizeF,
    QStandardPaths,
    QStringListModel,
    QTimer,
    Qt,
)
from PySide6.QtGui import (
    QAction,
    QBrush,
    QCloseEvent,
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QIcon,
    QImage,
    QLinearGradient,
    QKeySequence,
    QPageSize,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrinter
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QCompleter,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
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
from .batch import BatchOptions, export_batch
from .dialogs import BatchDialog, PreflightDialog
from .filters import FILTERS, apply_filter
from .model import (
    BACKGROUND_STYLES,
    CARD_FORMATS,
    MAX_CARDS,
    PAPER_LABELS,
    PAPER_SIZES,
    PX_PER_CM,
    PolaroidItem,
    Project,
)
from .project_io import (
    PROJECT_EXTENSION,
    PROJECT_FILE_FILTER,
    ProjectFileError,
    load_project_file,
    project_state_key,
    save_project_file,
)
from .image_io import (
    image_file_filter,
    is_supported_image_file,
    probe_image_size,
)
from .preflight import analyze_project, issue_counts
from .render import render_sheet, save_card, save_sheet
from .templates import DESIGN_TEMPLATES, apply_design_template
from .resources import asset_path
from .theme import current_theme, set_theme
from .widgets import ChoiceItem, CollapsibleCard, VisualChoiceStrip

IMAGE_FILTER = image_file_filter()
SHEET_COLOR_PRESETS = ("#ffffff", "#f6efe5", "#e7e9ea", "#dceeff", "#16181c")
FRAME_COLOR_PRESETS = ("#fcfcfa", "#fff2cf", "#ffe1e8", "#dff3ff", "#263238", "#7a1f1f")
HISTORY_LIMIT = 100
AUTOSAVE_FILENAME = "autosave.softpalaroid"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Softpalaroid — полароидные карточки для печати")
        self.resize(1260, 820)
        self.setMinimumSize(1000, 640)
        self.setAcceptDrops(True)

        self.project = Project()
        self.project.set_layout(1, landscape=True)

        # Состояние проекта, истории и автосохранения
        self._settings = QSettings("Softpalaroid", "Softpalaroid")
        self._apply_saved_project_defaults(self.project)
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
        self._style_clipboard: dict | None = None
        self._adjustment_controls: dict[str, tuple[QSlider, QDoubleSpinBox, int]] = {}
        self._section_cards: dict[str, CollapsibleCard] = {}
        self._slot_buttons: list[QToolButton] = []
        self._slot_icon_keys: dict[int, tuple] = {}
        self._search_targets: dict[str, object] = {}
        self._filter_gallery_key: tuple | None = None
        self._filter_sample_cache: PilImage.Image | None = None

        self._history_timer = QTimer(self)
        self._history_timer.setSingleShot(True)
        self._history_timer.setInterval(700)
        self._history_timer.timeout.connect(self._flush_pending_history)

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(1500)
        self._autosave_timer.timeout.connect(self._write_autosave)

        self._filter_gallery_timer = QTimer(self)
        self._filter_gallery_timer.setSingleShot(True)
        self._filter_gallery_timer.setInterval(250)
        self._filter_gallery_timer.timeout.connect(self._refresh_filter_gallery)

        self.canvas = CanvasWidget()
        self.canvas.set_project(self.project)
        self._ui_theme = current_theme()
        self.canvas.set_ui_theme(self._ui_theme)
        self.canvas.selectionChanged.connect(lambda _i: self._sync_panel())
        self.canvas.itemChanged.connect(self._sync_panel)
        self.canvas.itemChanged.connect(self._update_project_ui)
        self.canvas.photoLoadRequested.connect(self._load_photo_dialog)
        self.canvas.deleteRequested.connect(lambda _i: self._delete_card())
        self.canvas.duplicateRequested.connect(lambda _i: self._duplicate_card())
        self.canvas.pasteRequested.connect(self._paste_photo_from_clipboard)
        self.canvas.contextMenuRequested.connect(self._show_canvas_context_menu)
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
        splitter.setSizes([856, 404])
        root.addWidget(splitter, 1)
        self.setCentralWidget(central)

        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().showMessage(
            "Ctrl+K — поиск настройки • Ctrl+Tab — следующая карточка • "
            "колесо мыши — масштаб фото • Ctrl+колесо — масштаб просмотра")
        self._sync_layout_controls()
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

        self.act_export = QAction("Экспорт листа JPG/PNG/PDF…", self)
        self.act_export.setShortcut("Ctrl+E")
        self.act_export.triggered.connect(self._export_dialog)

        self.act_print = QAction("Предпросмотр и печать…", self)
        self.act_print.setShortcut("Ctrl+P")
        self.act_print.triggered.connect(self._print_dialog)

        self.act_preflight = QAction("Проверить макет", self)
        self.act_preflight.setShortcut("Ctrl+Shift+P")
        self.act_preflight.triggered.connect(
            lambda: self._confirm_preflight("Закрыть", manual=True))

        self.act_batch = QAction("Пакетная обработка…", self)
        self.act_batch.setShortcut("Ctrl+Shift+B")
        self.act_batch.triggered.connect(self._batch_dialog)

        self.act_search_panel = QAction("Найти настройку или действие…", self)
        self.act_search_panel.setShortcut("Ctrl+K")
        self.act_search_panel.triggered.connect(self._focus_panel_search)

        self.act_previous_card = QAction("Предыдущая карточка", self)
        self.act_previous_card.setShortcut("Ctrl+Shift+Tab")
        self.act_previous_card.triggered.connect(
            lambda: self._select_relative_card(-1))

        self.act_next_card = QAction("Следующая карточка", self)
        self.act_next_card.setShortcut("Ctrl+Tab")
        self.act_next_card.triggered.connect(
            lambda: self._select_relative_card(1))

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
            self.act_preflight, self.act_batch,
            self.act_search_panel, self.act_previous_card, self.act_next_card,
            self.act_undo, self.act_redo, self.act_about, self.act_quit,
        ])

    # ------------------------------------------- запоминаемые параметры листа
    @staticmethod
    def _as_setting_bool(value: object, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
        return default if value is None else bool(value)

    @staticmethod
    def _as_setting_float(value: object, default: float) -> float:
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default

    def _remember_project_defaults(self) -> None:
        """Запомнить формат листа/карточек для следующих новых проектов."""
        values = {
            "enabled": True,
            "paper_size": self.project.paper_size,
            "sheet_width_cm": self.project.sheet_width_cm,
            "sheet_height_cm": self.project.sheet_height_cm,
            "landscape": self.project.landscape,
            "card_format": self.project.card_format,
            "template": self.project.template,
            "background_color": self.project.background_color,
            "background_style": self.project.background_style,
            "background_color2": self.project.background_color2,
            "cut_marks": self.project.cut_marks,
            "safe_margin_mm": self.project.safe_margin_mm,
            "show_safe_area": self.project.show_safe_area,
            "snap_enabled": self.project.snap_enabled,
        }
        for key, value in values.items():
            self._settings.setValue(f"projectDefaults/{key}", value)
        self._settings.sync()

    def _apply_saved_project_defaults(self, project: Project) -> None:
        if not self._as_setting_bool(
                self._settings.value("projectDefaults/enabled", False), False):
            return

        def value(key: str, default: object) -> object:
            return self._settings.value(f"projectDefaults/{key}", default)

        landscape = self._as_setting_bool(
            value("landscape", project.landscape), project.landscape)
        paper = str(value("paper_size", project.paper_size))
        if paper in PAPER_SIZES:
            project.set_paper_size(paper, landscape=landscape)
        elif paper == "custom":
            project.set_sheet_dimensions(
                self._as_setting_float(
                    value("sheet_width_cm", project.sheet_width_cm),
                    project.sheet_width_cm),
                self._as_setting_float(
                    value("sheet_height_cm", project.sheet_height_cm),
                    project.sheet_height_cm),
                paper_size="custom")
            project.landscape = landscape

        card_format = str(value("card_format", project.card_format))
        if card_format in CARD_FORMATS:
            project.card_format = card_format
        template = str(value("template", project.template))
        if template in DESIGN_TEMPLATES:
            project.template = template
        background = str(value("background_color", project.background_color))
        if background.startswith("#"):
            project.background_color = background
        background_style = str(
            value("background_style", project.background_style))
        if background_style in BACKGROUND_STYLES:
            project.background_style = background_style
        background2 = str(value("background_color2", project.background_color2))
        if background2.startswith("#"):
            project.background_color2 = background2
        project.cut_marks = self._as_setting_bool(
            value("cut_marks", project.cut_marks), project.cut_marks)
        project.safe_margin_mm = self._as_setting_float(
            value("safe_margin_mm", project.safe_margin_mm),
            project.safe_margin_mm)
        project.show_safe_area = self._as_setting_bool(
            value("show_safe_area", project.show_safe_area),
            project.show_safe_area)
        project.snap_enabled = self._as_setting_bool(
            value("snap_enabled", project.snap_enabled), project.snap_enabled)
        project.clamp_settings()
        if project.items:
            project.set_layout(len(project.items), landscape=project.landscape)

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
        subtitle = QLabel("Новый проект · лист 15×10 см")
        subtitle.setObjectName("appSubtitle")
        self._subtitle_label = subtitle
        titles.addWidget(title)
        titles.addWidget(subtitle)
        lay.addLayout(titles)
        lay.addStretch(1)

        version = QLabel(f"v{__version__}")
        version.setObjectName("versionChip")
        lay.addWidget(version)

        self.theme_button = QPushButton()
        self.theme_button.setMinimumHeight(42)
        self.theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_button.setToolTip(
            "Переключить светлую или тёмную тему интерфейса")
        self.theme_button.setAccessibleName("Тема интерфейса")
        self.theme_button.clicked.connect(self._toggle_theme)
        self._sync_theme_button()
        lay.addWidget(self.theme_button)

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
        menu.addActions([
            self.act_open, self.act_export, self.act_print,
            self.act_preflight, self.act_batch,
        ])
        menu.addSeparator()
        menu.addActions([
            self.act_search_panel, self.act_previous_card, self.act_next_card])
        menu.addSeparator()
        menu.addAction(self.act_about)
        menu.addSeparator()
        menu.addAction(self.act_quit)
        more.setMenu(menu)
        lay.addWidget(more)
        return header

    # ---------------------------------------------------------------- панель
    def _sync_theme_button(self) -> None:
        if hasattr(self, "theme_button"):
            self.theme_button.setText(
                "Тема: тёмная" if self._ui_theme == "dark"
                else "Тема: светлая")

    def _toggle_theme(self) -> None:
        target = "light" if self._ui_theme == "dark" else "dark"
        app = QApplication.instance()
        self._ui_theme = set_theme(app, target) if app is not None else target
        self.canvas.set_ui_theme(self._ui_theme)
        self._sync_theme_button()
        if hasattr(self, "format_gallery"):
            self.format_gallery.set_choices(
                self._make_card_format_choices(),
                current=self.project.card_format)
        self._sync_layout_controls()
        self._sync_panel()
        self.statusBar().showMessage(
            "Включена светлая тема" if self._ui_theme == "light"
            else "Включена тёмная тема", 3000)

    @staticmethod
    def _field_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "field")
        return label

    def _card(self, title: str, *, key: str | None = None,
              expanded: bool = True) -> tuple[CollapsibleCard, QVBoxLayout]:
        card = CollapsibleCard(
            title, key=key, settings=self._settings, expanded=expanded)
        if key:
            self._section_cards[key] = card
        return card, card.content_layout

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

    @staticmethod
    def _style_color_button(button: QPushButton, color: str, text: str) -> None:
        qcolor = QColor(color)
        foreground = "#0F1419" if qcolor.lightnessF() >= 0.58 else "#FFFFFF"
        button.setText(text)
        button.setStyleSheet(
            f"background-color: {color}; color: {foreground}; "
            "border: 1px solid #536471; border-radius: 12px; "
            "padding: 7px 12px; font-weight: 800;")

    @staticmethod
    def _color_button() -> QPushButton:
        button = QPushButton()
        button.setMinimumHeight(38)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip("Выбрать произвольный цвет")
        return button

    @staticmethod
    def _swatch_button(color: str) -> QToolButton:
        button = QToolButton()
        button.setFixedSize(30, 30)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(color.upper())
        button.setStyleSheet(
            f"background-color: {color}; border: 1px solid #536471; "
            "border-radius: 10px; padding: 0;")
        return button

    def _make_swatch_row(self, colors: tuple[str, ...], callback) -> QWidget:
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(7)
        for color in colors:
            button = self._swatch_button(color)
            button.clicked.connect(lambda _checked=False, c=color: callback(c))
            row.addWidget(button)
        row.addStretch(1)
        return wrap

    def _make_adjustment_row(self, layout: QVBoxLayout, text: str,
                             field_name: str, minimum: float,
                             maximum: float) -> None:
        """Добавить пару слайдер+спинбокс для числового поля карточки."""
        layout.addWidget(self._field_label(text))
        row = QHBoxLayout()
        row.setSpacing(10)
        scale = 100
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(int(round(minimum * scale)), int(round(maximum * scale)))
        slider.valueChanged.connect(
            lambda value, f=field_name, sc=scale:
            self._set_item(**{f: value / sc}))
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(2)
        spin.setSingleStep(0.05)
        spin.setSuffix("×")
        spin.setFixedWidth(88)
        spin.setMinimumHeight(34)
        spin.valueChanged.connect(
            lambda value, f=field_name: self._set_item(**{f: value}))
        row.addWidget(slider, 1)
        row.addWidget(spin)
        layout.addLayout(row)
        self._adjustment_controls[field_name] = (slider, spin, scale)

    # ----------------------------------------- визуальные выборы и навигация
    @staticmethod
    def _select_combo_data(combo: QComboBox, data: object) -> None:
        index = combo.findData(data)
        if index >= 0 and index != combo.currentIndex():
            combo.setCurrentIndex(index)

    @staticmethod
    def _pil_icon(image: PilImage.Image) -> QIcon:
        rgb = image.convert("RGB")
        qimage = QImage(
            rgb.tobytes(), rgb.width, rgb.height, rgb.width * 3,
            QImage.Format.Format_RGB888).copy()
        return QIcon(QPixmap.fromImage(qimage))

    @staticmethod
    def _choice_pixmap(theme: str = "dark") -> QPixmap:
        pixmap = QPixmap(144, 92)
        pixmap.fill(QColor("#111418" if theme == "dark" else "#EFF3F4"))
        return pixmap

    def _paper_icon(self, key: str) -> QIcon:
        pixmap = self._choice_pixmap(self._ui_theme)
        if key == "custom":
            width_cm = self.project.sheet_width_cm
            height_cm = self.project.sheet_height_cm
        else:
            short, long = PAPER_SIZES[key]
            width_cm, height_cm = (
                (long, short) if self.project.landscape else (short, long))
        scale = min(112.0 / width_cm, 66.0 / height_cm)
        width = max(28.0, width_cm * scale)
        height = max(22.0, height_cm * scale)
        x = (144.0 - width) / 2.0
        y = (92.0 - height) / 2.0

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#536471"), 3))
        painter.setBrush(QBrush(QColor("#EFF3F4")))
        painter.drawRoundedRect(QRectF(x, y, width, height), 4, 4)
        painter.setPen(QPen(QColor("#1D9BF0"), 2))
        painter.setBrush(QBrush(QColor("#DCEEFF")))
        card_w = max(12.0, width * 0.28)
        card_h = max(14.0, height * 0.52)
        painter.drawRoundedRect(
            QRectF(x + width * 0.16, y + height * 0.20, card_w, card_h), 3, 3)
        painter.setBrush(QBrush(QColor("#FFF2CF")))
        painter.drawRoundedRect(
            QRectF(x + width * 0.56, y + height * 0.20, card_w, card_h), 3, 3)
        painter.end()
        return QIcon(pixmap)

    @staticmethod
    def _card_format_icon(spec, theme: str = "dark") -> QIcon:
        pixmap = MainWindow._choice_pixmap(theme)
        height = 68.0
        width = height / spec.frame_ratio
        if width > 112.0:
            factor = 112.0 / width
            width *= factor
            height *= factor
        x = (144.0 - width) / 2.0
        y = (92.0 - height) / 2.0
        photo = QRectF(
            x + width * spec.photo_x_frac,
            y + height * spec.photo_y_frac,
            width * spec.photo_w_frac,
            height * spec.photo_h_frac)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#536471"), 3))
        painter.setBrush(QBrush(QColor("#FCFCFA")))
        painter.drawRoundedRect(QRectF(x, y, width, height), 4, 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#7FC8F8")))
        painter.drawRect(QRectF(
            photo.x(), photo.y(), photo.width(), photo.height() * 0.60))
        painter.setBrush(QBrush(QColor("#F6C177")))
        painter.drawRect(QRectF(
            photo.x(), photo.y() + photo.height() * 0.60,
            photo.width(), photo.height() * 0.40))
        painter.setBrush(QBrush(QColor("#FFF3B0")))
        sun = min(photo.width(), photo.height()) * 0.22
        painter.drawEllipse(QRectF(
            photo.x() + photo.width() * 0.62,
            photo.y() + photo.height() * 0.12, sun, sun))
        painter.end()
        return QIcon(pixmap)

    @staticmethod
    def _template_icon(template) -> QIcon:
        pixmap = QPixmap(144, 92)
        pixmap.fill(QColor(template.background_color))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#536471"), 2))
        painter.drawRoundedRect(QRectF(2, 2, 140, 88), 6, 6)
        positions = [(48.0, 46.0, -7.0), (96.0, 46.0, 6.0)]
        for index, (cx, cy, angle) in enumerate(positions):
            frame = template.frame_colors[index % len(template.frame_colors)]
            painter.save()
            painter.translate(cx, cy)
            painter.rotate(angle)
            painter.setPen(QPen(QColor("#536471"), 2))
            painter.setBrush(QBrush(QColor(frame)))
            painter.drawRoundedRect(QRectF(-24, -31, 48, 62), 4, 4)
            painter.setPen(Qt.PenStyle.NoPen)
            photo_color = "#6B7280" if template.filter == "bw" else "#7FC8F8"
            painter.setBrush(QBrush(QColor(photo_color)))
            painter.drawRect(QRectF(-18, -24, 36, 25))
            painter.setBrush(QBrush(QColor(
                "#D1D5DB" if template.filter == "bw" else "#F6C177")))
            painter.drawRect(QRectF(-18, 1, 36, 12))
            painter.restore()
        painter.end()
        return QIcon(pixmap)

    def _make_paper_choices(self) -> list[ChoiceItem]:
        labels = {
            "10x15": "10×15",
            "13x18": "13×18",
            "15x21": "15×21",
            "a5": "A5",
            "a4": "A4",
            "custom": "Свой размер",
        }
        keys = [*PAPER_SIZES, "custom"]
        return [
            ChoiceItem(key, labels[key], self._paper_icon(key),
                       PAPER_LABELS[key])
            for key in keys
        ]

    def _make_card_format_choices(self) -> list[ChoiceItem]:
        labels = {
            "classic": "Classic",
            "instax_mini": "Mini",
            "instax_square": "Square",
            "instax_wide": "Wide",
        }
        return [
            ChoiceItem(spec.key, labels.get(spec.key, spec.name),
                       self._card_format_icon(spec, self._ui_theme), spec.name)
            for spec in CARD_FORMATS.values()
        ]

    def _make_template_choices(self) -> list[ChoiceItem]:
        labels = {
            "classic": "Классика",
            "warm_film": "Тёплая",
            "mono_night": "Монохром",
            "pastel": "Пастель",
            "bright_album": "Яркий",
        }
        return [
            ChoiceItem(template.key, labels.get(template.key, template.name),
                       self._template_icon(template), template.name)
            for template in DESIGN_TEMPLATES.values()
        ]

    def _background_icon(self, style: str) -> QIcon:
        pixmap = QPixmap(144, 92)
        color1 = QColor(self.project.background_color)
        color2 = QColor(self.project.background_color2)
        pixmap.fill(color1)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if style == "gradient":
            gradient = QLinearGradient(0.0, 0.0, 0.0, 92.0)
            gradient.setColorAt(0.0, color1)
            gradient.setColorAt(1.0, color2)
            painter.fillRect(pixmap.rect(), QBrush(gradient))
        elif style == "dots":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color2))
            row = 0
            y = 10.0
            while y < 92:
                x = 10.0 + (9.0 if row % 2 else 0.0)
                while x < 144:
                    painter.drawEllipse(QRectF(x - 3.2, y - 3.2, 6.4, 6.4))
                    x += 18.0
                y += 18.0
                row += 1
        elif style == "grid":
            painter.setPen(QPen(color2, 1.6))
            x = 0.0
            while x <= 144:
                painter.drawLine(QPointF(x, 0.0), QPointF(x, 92.0))
                x += 18.0
            y = 0.0
            while y <= 92:
                painter.drawLine(QPointF(0.0, y), QPointF(144.0, y))
                y += 18.0
        # Мини-карточка поверх фона: как будет выглядеть лист.
        painter.setPen(QPen(QColor("#536471"), 2))
        painter.setBrush(QBrush(QColor("#FCFCFA")))
        painter.drawRoundedRect(QRectF(52, 16, 40, 52), 3, 3)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#7FC8F8")))
        painter.drawRect(QRectF(57, 21, 30, 20))
        painter.setBrush(QBrush(QColor("#F6C177")))
        painter.drawRect(QRectF(57, 41, 30, 9))
        painter.setPen(QPen(QColor("#536471"), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(1, 1, 142, 90), 6, 6)
        painter.end()
        return QIcon(pixmap)

    def _make_background_choices(self) -> list[ChoiceItem]:
        return [
            ChoiceItem(key, label, self._background_icon(key),
                       f"Стиль фона листа: {label}")
            for key, label in BACKGROUND_STYLES.items()
        ]

    def _filter_sample_image(self) -> PilImage.Image:
        if self._filter_sample_cache is not None:
            return self._filter_sample_cache.copy()
        width, height, horizon = 192, 128, 82
        image = PilImage.new("RGB", (width, height))
        pixels = image.load()
        for yy in range(height):
            if yy < horizon:
                t = yy / max(1, horizon - 1)
                color = (
                    int(72 + (250 - 72) * t),
                    int(155 + (205 - 155) * t),
                    int(235 + (145 - 235) * t),
                )
            else:
                t = (yy - horizon) / max(1, height - horizon - 1)
                color = (
                    int(96 + (58 - 96) * t),
                    int(164 + (118 - 164) * t),
                    int(84 + (64 - 84) * t),
                )
            for xx in range(width):
                pixels[xx, yy] = color
        draw = PilDraw.Draw(image)
        draw.ellipse((132, 14, 166, 48), fill=(255, 238, 150))
        draw.polygon(
            [(0, 84), (48, 52), (92, 84), (132, 58), (192, 84), (192, 96),
             (0, 96)],
            fill=(88, 126, 145))
        draw.polygon([(0, 128), (0, 96), (70, 84), (150, 98), (192, 90),
                      (192, 128)], fill=(74, 145, 82))
        draw.rectangle((24, 88, 62, 114), fill=(250, 245, 225))
        draw.polygon([(18, 89), (43, 72), (68, 89)], fill=(176, 72, 62))
        draw.rectangle((38, 98, 49, 114), fill=(96, 62, 45))
        self._filter_sample_cache = image
        return image.copy()

    def _make_filter_choices(
            self, base: PilImage.Image,
            item: PolaroidItem | None = None) -> list[ChoiceItem]:
        work = base.convert("RGB")
        target_ratio = 1.5
        ratio = work.width / max(1, work.height)
        if ratio > target_ratio:
            crop_w = int(work.height * target_ratio)
            left = (work.width - crop_w) // 2
            work = work.crop((left, 0, left + crop_w, work.height))
        elif ratio < target_ratio:
            crop_h = int(work.width / target_ratio)
            top = (work.height - crop_h) // 2
            work = work.crop((0, top, work.width, top + crop_h))
        work = work.resize((192, 128), PilImage.Resampling.LANCZOS)
        intensity = item.filter_intensity if item is not None else 1.0
        seed = item.effective_grain_seed() if item is not None else 0
        return [
            ChoiceItem(
                key, title,
                self._pil_icon(apply_filter(
                    work.copy(), key, seed=seed, intensity=intensity)),
                f"Фильтр: {title}")
            for key, title in FILTERS.items()
        ]

    def _filter_gallery_cache_key(self) -> tuple | None:
        if not self.project.items:
            return None
        index = self._selected_index()
        item = self.project.items[index]
        return (
            index, item.photo_path, tuple(item.photo_size or ()),
            item.photo_rotation, item.flip_horizontal, item.flip_vertical,
            round(item.filter_intensity, 4), round(item.brightness, 4),
            round(item.contrast, 4), round(item.saturation, 4),
            round(item.sharpness, 4),
        )

    def _schedule_filter_gallery_refresh(self) -> None:
        if not hasattr(self, "filter_gallery"):
            return
        if self._filter_gallery_cache_key() != self._filter_gallery_key:
            self._filter_gallery_timer.start()

    def _refresh_filter_gallery(self) -> None:
        if not hasattr(self, "filter_gallery") or not self.project.items:
            return
        item = self._item()
        base = self.canvas.filter_base_image(self._selected_index())
        if base is None:
            base = self._filter_sample_image()
        self.filter_gallery.set_choices(
            self._make_filter_choices(base, item), current=item.filter)
        self._filter_gallery_key = self._filter_gallery_cache_key()

    def _set_all_sections_expanded(self, expanded: bool) -> None:
        for card in self._section_cards.values():
            card.set_expanded(expanded)

    def _focus_panel_search(self) -> None:
        if hasattr(self, "panel_search"):
            self.activateWindow()
            self.panel_search.setFocus(Qt.FocusReason.ShortcutFocusReason)
            self.panel_search.selectAll()

    def _build_search_targets(self) -> None:
        entries: list[tuple[str, object]] = [
            ("Размер бумаги — точный список", self.paper_combo),
            ("Размер бумаги — визуальный выбор", self.paper_gallery),
            ("Ширина произвольного листа", self.sheet_width_spin),
            ("Высота произвольного листа", self.sheet_height_spin),
            ("Формат карточек — точный список", self.card_format_combo),
            ("Формат карточек — визуальный выбор", self.format_gallery),
            ("Дизайн-шаблон — точный список", self.template_combo),
            ("Дизайн-шаблон — визуальный выбор", self.template_gallery),
            ("Ориентация листа", self.rb_land),
            ("Количество снимков на листе", self.count_spin),
            ("Добавить карточку", self.add_card_button),
            ("Дублировать карточку", self.duplicate_card_button),
            ("Удалить карточку", self.delete_card_button),
            ("Уголки обреза", self.cut_marks_button),
            ("Безопасная область", self.safe_margin_spin),
            ("Показывать безопасную область", self.show_safe_button),
            ("Магнитное выравнивание", self.snap_button),
            ("Фон листа", self.background_button),
            ("Стиль фона листа", self.background_gallery),
            ("Второй цвет фона", self.background2_button),
            ("Выравнивание карточек", self.align_buttons["left"]),
            ("Случайный разброс карточек", self.scatter_button),
            ("Размер карточки", self.card_size_spin),
            ("Наклон карточки", self.rot_spin),
            ("Масштаб фотографии", self.zoom_spin),
            ("Отражение фотографии", self.flip_h_button),
            ("Подпись на рамке", self.caption_edit),
            ("Выравнивание подписи", self.caption_align_combo),
            ("Цвет подписи", self.caption_color_button),
            ("Фильтр в стиле плёнки", self.filter_gallery),
            ("Цвет рамки карточки", self.frame_color_button),
            ("Загрузить фотографию", self.act_open),
            ("Проверить макет перед печатью", self.act_preflight),
            ("Экспорт листа", self.act_export),
            ("Предпросмотр и печать", self.act_print),
            ("Пакетная обработка", self.act_batch),
            ("Новый проект", self.act_new_project),
            ("Открыть проект", self.act_open_project),
            ("Сохранить проект", self.act_save_project),
            ("Предыдущая карточка", self.act_previous_card),
            ("Следующая карточка", self.act_next_card),
        ]
        adjustment_labels = {
            "filter_intensity": "Сила фильтра",
            "brightness": "Яркость фотографии",
            "contrast": "Контраст фотографии",
            "saturation": "Насыщенность фотографии",
            "sharpness": "Резкость фотографии",
            "caption_scale": "Размер подписи",
        }
        for field_name, label in adjustment_labels.items():
            if field_name in self._adjustment_controls:
                entries.append(
                    (label, self._adjustment_controls[field_name][1]))
        self._search_targets = dict(entries)

        if hasattr(self, "panel_search"):
            model = QStringListModel(list(self._search_targets), self)
            completer = QCompleter(model, self)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setCompletionMode(
                QCompleter.CompletionMode.PopupCompletion)
            completer.activated[str].connect(self._activate_search_result)
            self.panel_search.setCompleter(completer)
            self._search_completer = completer

    def _show_panel_widget(self, widget: QWidget) -> None:
        current: QWidget | None = widget
        while current is not None:
            if isinstance(current, CollapsibleCard):
                current.set_expanded(True)
            current = current.parentWidget()

        def reveal() -> None:
            if hasattr(self, "panel_scroll"):
                self.panel_scroll.ensureWidgetVisible(widget, 24, 24)
            self.activateWindow()
            widget.setFocus(Qt.FocusReason.OtherFocusReason)

        QTimer.singleShot(0, reveal)

    def _activate_search_result(self, text: str) -> None:
        query = (text or "").strip()
        if not query:
            return
        target = self._search_targets.get(query)
        if target is None:
            folded = query.casefold()
            target = next(
                (value for label, value in self._search_targets.items()
                 if folded in label.casefold()), None)
        if target is None:
            self.statusBar().showMessage(
                f"Настройка не найдена: {query}", 3500)
            return
        if isinstance(target, QAction):
            target.trigger()
        elif isinstance(target, QWidget):
            self._show_panel_widget(target)
        if hasattr(self, "panel_search"):
            self.panel_search.selectAll()

    @staticmethod
    def _placeholder_slot_icon(symbol: str = "+", theme: str = "dark") -> QIcon:
        pixmap = QPixmap(96, 68)
        pixmap.fill(QColor("#16181C" if theme == "dark" else "#F7F9F9"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#536471"), 2, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(4, 4, 88, 60), 8, 8)
        painter.setPen(QColor("#71767B"))
        painter.drawText(
            pixmap.rect(), Qt.AlignmentFlag.AlignCenter, symbol)
        painter.end()
        return QIcon(pixmap)

    def _select_slot(self, index: int) -> None:
        if not (0 <= index < len(self.project.items)):
            return
        card = self._section_cards.get("card")
        if card is not None:
            card.set_expanded(True)
        self.canvas.select(index)
        self._sync_panel()

    def _select_relative_card(self, delta: int) -> None:
        count = len(self.project.items)
        if count <= 1:
            return
        self._select_slot((self._selected_index() + delta) % count)

    def _refresh_slot_strip(self) -> None:
        if not hasattr(self, "_slot_strip_layout"):
            return
        count = len(self.project.items)
        if len(self._slot_buttons) != count:
            while self._slot_strip_layout.count():
                layout_item = self._slot_strip_layout.takeAt(0)
                widget = layout_item.widget()
                if widget is not None:
                    widget.setParent(None)
                    widget.deleteLater()
            self._slot_buttons.clear()
            self._slot_icon_keys.clear()
            for index in range(count):
                button = QToolButton()
                button.setProperty("slotButton", True)
                button.setCheckable(True)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setFixedSize(68, 64)
                button.setIconSize(QSize(48, 34))
                button.setToolButtonStyle(
                    Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
                button.setAccessibleName(f"Карточка {index + 1}")
                button.clicked.connect(
                    lambda _checked=False, i=index: self._select_slot(i))
                self._slot_strip_layout.addWidget(button)
                self._slot_buttons.append(button)
            self._slot_strip_layout.addStretch(1)

        selected = self._selected_index()
        for index, (item, button) in enumerate(
                zip(self.project.items, self._slot_buttons)):
            pixmap = self.canvas.preview_pixmap(index)
            has_preview = pixmap is not None and not pixmap.isNull()
            exists = bool(item.photo_path and os.path.isfile(item.photo_path))
            dpi = item.effective_print_dpi() if item.photo_path else None
            if not item.photo_path:
                state, suffix = "empty", "+"
                detail = "без фотографии"
            elif not exists:
                state, suffix = "error", "!"
                detail = "файл фотографии не найден"
            elif not has_preview:
                state, suffix = "error", "!"
                detail = "не удалось загрузить фотографию"
            elif dpi is not None and dpi < 300:
                state, suffix = "warning", f"⚠ {dpi:.0f}"
                detail = f"эффективный DPI: {dpi:.0f}"
            elif dpi is not None:
                state, suffix = "ok", "✓"
                detail = f"эффективный DPI: {dpi:.0f}"
            else:
                state, suffix = "ok", "✓"
                detail = "фотография загружена"

            text = f"{index + 1} · {suffix}"
            if button.text() != text:
                button.setText(text)
            if button.property("slotState") != state:
                button.setProperty("slotState", state)
                button.style().unpolish(button)
                button.style().polish(button)
            blocked = button.blockSignals(True)
            try:
                button.setChecked(index == selected)
            finally:
                button.blockSignals(blocked)

            name = os.path.basename(item.photo_path) if item.photo_path else ""
            button.setToolTip(
                f"Карточка {index + 1}: {detail}"
                + (f"\n{name}" if name else ""))
            icon_key = (
                state, self._ui_theme, item.photo_path,
                tuple(item.photo_size or ()),
                item.filter, item.filter_intensity, item.brightness,
                item.contrast, item.saturation, item.sharpness,
                item.photo_rotation, item.flip_horizontal,
                item.flip_vertical,
            )
            if self._slot_icon_keys.get(index) != icon_key:
                if has_preview:
                    scaled = pixmap.scaled(
                        QSize(96, 68),
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation)
                    left = max(0, (scaled.width() - 96) // 2)
                    top = max(0, (scaled.height() - 68) // 2)
                    button.setIcon(QIcon(scaled.copy(left, top, 96, 68)))
                else:
                    button.setIcon(self._placeholder_slot_icon(
                        "!" if state == "error" else "+", self._ui_theme))
                self._slot_icon_keys[index] = icon_key

        if 0 <= selected < len(self._slot_buttons):
            self.slot_scroll.ensureWidgetVisible(
                self._slot_buttons[selected], 10, 0)

    def _build_panel(self) -> QWidget:
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(14)

        # --- Лист ---
        sheet_card, gl = self._card(
            "Лист и форматы", key="sheet", expanded=True)
        gl.addWidget(self._field_label("Размер бумаги"))
        self.paper_combo = QComboBox()
        self.paper_combo.setMinimumHeight(38)
        for key in PAPER_SIZES:
            self.paper_combo.addItem(PAPER_LABELS[key], key)
        self.paper_combo.addItem(PAPER_LABELS["custom"], "custom")
        paper_idx = self.paper_combo.findData(self.project.paper_size)
        if paper_idx >= 0:
            self.paper_combo.setCurrentIndex(paper_idx)
        self.paper_combo.currentIndexChanged.connect(
            lambda _idx: self._paper_changed())
        gl.addWidget(self.paper_combo)
        self.paper_gallery = VisualChoiceStrip()
        self.paper_gallery.set_choices(
            self._make_paper_choices(), current=self.project.paper_size)
        self.paper_gallery.selected.connect(
            lambda key: self._select_combo_data(self.paper_combo, key))
        gl.addWidget(self.paper_gallery)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self._field_label("Ш"))
        self.sheet_width_spin = QDoubleSpinBox()
        self.sheet_width_spin.setRange(5.0, 50.0)
        self.sheet_width_spin.setDecimals(1)
        self.sheet_width_spin.setSingleStep(0.1)
        self.sheet_width_spin.setSuffix(" см")
        self.sheet_width_spin.setMinimumHeight(36)
        self.sheet_width_spin.setValue(self.project.sheet_width_cm)
        self.sheet_width_spin.valueChanged.connect(
            lambda _v: self._custom_sheet_changed())
        row.addWidget(self.sheet_width_spin, 1)
        row.addWidget(QLabel("×"))
        row.addWidget(self._field_label("В"))
        self.sheet_height_spin = QDoubleSpinBox()
        self.sheet_height_spin.setRange(5.0, 50.0)
        self.sheet_height_spin.setDecimals(1)
        self.sheet_height_spin.setSingleStep(0.1)
        self.sheet_height_spin.setSuffix(" см")
        self.sheet_height_spin.setMinimumHeight(36)
        self.sheet_height_spin.setValue(self.project.sheet_height_cm)
        self.sheet_height_spin.valueChanged.connect(
            lambda _v: self._custom_sheet_changed())
        row.addWidget(self.sheet_height_spin, 1)
        gl.addLayout(row)

        gl.addWidget(self._field_label("Формат карточек"))
        self.card_format_combo = QComboBox()
        self.card_format_combo.setMinimumHeight(38)
        for spec in CARD_FORMATS.values():
            self.card_format_combo.addItem(spec.name, spec.key)
        format_idx = self.card_format_combo.findData(self.project.card_format)
        if format_idx >= 0:
            self.card_format_combo.setCurrentIndex(format_idx)
        self.card_format_combo.currentIndexChanged.connect(
            lambda _idx: self._card_format_changed())
        gl.addWidget(self.card_format_combo)
        self.format_gallery = VisualChoiceStrip()
        self.format_gallery.set_choices(
            self._make_card_format_choices(), current=self.project.card_format)
        self.format_gallery.selected.connect(
            lambda key: self._select_combo_data(self.card_format_combo, key))
        gl.addWidget(self.format_gallery)

        gl.addWidget(self._field_label("Дизайн-шаблон"))
        self.template_combo = QComboBox()
        self.template_combo.setMinimumHeight(38)
        for template in DESIGN_TEMPLATES.values():
            self.template_combo.addItem(template.name, template.key)
        template_idx = self.template_combo.findData(self.project.template)
        if template_idx >= 0:
            self.template_combo.setCurrentIndex(template_idx)
        gl.addWidget(self.template_combo)
        self.template_gallery = VisualChoiceStrip()
        self.template_gallery.set_choices(
            self._make_template_choices(), current=self.project.template)
        self.template_gallery.selected.connect(
            lambda key: self._select_combo_data(self.template_combo, key))
        gl.addWidget(self.template_gallery)
        btn_template = self._ghost_button("Применить шаблон ко всему листу", 34)
        btn_template.clicked.connect(self._apply_template)
        gl.addWidget(btn_template)

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
        row = QHBoxLayout()
        row.setSpacing(10)
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, MAX_CARDS)
        self.count_spin.setValue(1)
        self.count_spin.setFixedWidth(92)
        self.count_spin.setMinimumHeight(36)
        self.count_spin.setToolTip(
            "Произвольное количество карточек; раскладка будет пересчитана")
        self.count_spin.valueChanged.connect(self._count_changed)
        count_hint = QLabel(f"произвольно: 1–{MAX_CARDS}")
        count_hint.setProperty("role", "muted")
        row.addWidget(self.count_spin)
        row.addWidget(count_hint, 1)
        gl.addLayout(row)

        self.count_group = QButtonGroup(self)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.count_buttons: dict[int, QPushButton] = {}
        for n in (1, 2, 4, 6, 9):
            btn = self._segment_button(str(n))
            btn.setChecked(n == 1)
            self.count_group.addButton(btn, n)
            self.count_buttons[n] = btn
            row.addWidget(btn, 1)
        self.count_group.idToggled.connect(
            lambda count, checked: checked and self._count_changed(count))
        gl.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.add_card_button = self._ghost_button("+ Карточка", 34)
        self.add_card_button.clicked.connect(self._add_card)
        self.duplicate_card_button = self._ghost_button("Дубликат", 34)
        self.duplicate_card_button.clicked.connect(self._duplicate_card)
        self.delete_card_button = self._ghost_button("Удалить", 34)
        self.delete_card_button.clicked.connect(self._delete_card)
        row.addWidget(self.add_card_button, 1)
        row.addWidget(self.duplicate_card_button, 1)
        row.addWidget(self.delete_card_button, 1)
        gl.addLayout(row)

        btn_reset_layout = self._ghost_button("Сбросить расположение")
        btn_reset_layout.clicked.connect(self._reset_layout)
        gl.addWidget(btn_reset_layout)

        gl.addWidget(self._field_label("Выравнивание карточек"))
        align_grid = QGridLayout()
        align_grid.setSpacing(8)
        self.align_buttons: dict[str, QPushButton] = {}
        for i, (text, mode) in enumerate((
                ("Слева", "left"), ("По центру", "center_x"),
                ("Справа", "right"), ("Сверху", "top"),
                ("По середине", "center_y"), ("Снизу", "bottom"))):
            align_btn = self._ghost_button(text, 34)
            align_btn.clicked.connect(
                lambda _checked=False, m=mode:
                self._arrange_cards("align", m))
            self.align_buttons[mode] = align_btn
            align_grid.addWidget(align_btn, i // 3, i % 3)
        gl.addLayout(align_grid)
        self.distribute_x_button = self._ghost_button(
            "Равномерные промежутки по горизонтали", 34)
        self.distribute_x_button.clicked.connect(
            lambda: self._arrange_cards("distribute", "x"))
        gl.addWidget(self.distribute_x_button)
        self.distribute_y_button = self._ghost_button(
            "Равномерные промежутки по вертикали", 34)
        self.distribute_y_button.clicked.connect(
            lambda: self._arrange_cards("distribute", "y"))
        gl.addWidget(self.distribute_y_button)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.scatter_button = self._ghost_button("Случайный разброс", 34)
        self.scatter_button.setToolTip(
            "Небольшие случайные наклоны и сдвиги всех карточек")
        self.scatter_button.clicked.connect(
            lambda: self._arrange_cards("scatter"))
        row.addWidget(self.scatter_button, 1)
        self.straighten_button = self._ghost_button("Наклон 0° всем", 34)
        self.straighten_button.clicked.connect(
            lambda: self._arrange_cards("straighten"))
        row.addWidget(self.straighten_button, 1)
        gl.addLayout(row)

        self.cut_marks_button = self._segment_button("Уголки обреза на макете")
        self.cut_marks_button.setChecked(True)
        self.cut_marks_button.setToolTip(
            "Короткие L-образные линии вокруг карточек в экспорте и печати")
        self.cut_marks_button.toggled.connect(
            lambda checked: self._set_project_setting(cut_marks=checked))
        gl.addWidget(self.cut_marks_button)

        gl.addWidget(self._field_label("Безопасная область от края"))
        self.safe_margin_spin = QDoubleSpinBox()
        self.safe_margin_spin.setRange(0.0, 25.0)
        self.safe_margin_spin.setDecimals(1)
        self.safe_margin_spin.setSingleStep(0.5)
        self.safe_margin_spin.setSuffix(" мм")
        self.safe_margin_spin.setMinimumHeight(36)
        self.safe_margin_spin.setValue(self.project.safe_margin_mm)
        self.safe_margin_spin.valueChanged.connect(
            lambda value: self._set_project_setting(safe_margin_mm=value))
        gl.addWidget(self.safe_margin_spin)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.show_safe_button = self._segment_button("Показывать область")
        self.show_safe_button.setChecked(self.project.show_safe_area)
        self.show_safe_button.toggled.connect(
            lambda checked: self._set_project_setting(show_safe_area=checked))
        row.addWidget(self.show_safe_button, 1)
        self.snap_button = self._segment_button("Магниты")
        self.snap_button.setChecked(self.project.snap_enabled)
        self.snap_button.setToolTip(
            "Притягивать карточки к краям, центру, безопасной области и соседям; "
            "Alt временно отключает магниты")
        self.snap_button.toggled.connect(
            lambda checked: self._set_project_setting(snap_enabled=checked))
        row.addWidget(self.snap_button, 1)
        gl.addLayout(row)

        gl.addWidget(self._field_label("Фон листа"))
        self.background_button = self._color_button()
        self.background_button.clicked.connect(self._choose_background_color)
        gl.addWidget(self.background_button)
        gl.addWidget(self._make_swatch_row(
            SHEET_COLOR_PRESETS, self._set_background_color))

        gl.addWidget(self._field_label("Стиль фона"))
        self.background_gallery = VisualChoiceStrip()
        self.background_gallery.set_choices(
            self._make_background_choices(),
            current=self.project.background_style)
        self._background_gallery_state = (
            self.project.background_color, self.project.background_color2,
            self._ui_theme)
        self.background_gallery.selected.connect(
            lambda key: self._set_project_setting(background_style=key))
        gl.addWidget(self.background_gallery)

        gl.addWidget(self._field_label("Второй цвет фона"))
        self.background2_button = self._color_button()
        self.background2_button.clicked.connect(self._choose_background_color2)
        gl.addWidget(self.background2_button)
        gl.addWidget(self._make_swatch_row(
            SHEET_COLOR_PRESETS, self._set_background_color2))
        lay.addWidget(sheet_card)

        # --- Выбранный полароид ---
        item_card, il = self._card(
            "Карточка и фото", key="card", expanded=True)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.slot_label = QLabel("Слот 1 / 1")
        self.slot_label.setObjectName("slotChip")
        self.slot_state = QLabel("Без фото")
        self.slot_state.setProperty("role", "muted")
        row.addWidget(self.slot_label)
        row.addWidget(self.slot_state, 1)
        il.addLayout(row)
        self.dpi_label = QLabel()
        self.dpi_label.setProperty("role", "muted")
        self.dpi_label.setWordWrap(True)
        il.addWidget(self.dpi_label)

        btn_load = QPushButton("+  Загрузить фото")
        btn_load.setObjectName("whiteButton")
        btn_load.setMinimumHeight(42)
        btn_load.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_load.clicked.connect(lambda: self._load_photo_dialog(self._selected_index()))
        il.addWidget(btn_load)

        btn_dup = self._ghost_button("Это же фото — во все слоты")
        btn_dup.clicked.connect(self._duplicate_to_all)
        il.addWidget(btn_dup)

        row = QHBoxLayout()
        row.setSpacing(8)
        btn_paste = self._ghost_button("Вставить из буфера", 34)
        btn_paste.clicked.connect(
            lambda: self._paste_photo_from_clipboard(self._selected_index()))
        row.addWidget(btn_paste, 1)
        btn_export_card = self._ghost_button("Экспорт карточки…", 34)
        btn_export_card.clicked.connect(
            lambda: self._export_card_dialog(self._selected_index()))
        row.addWidget(btn_export_card, 1)
        il.addLayout(row)

        il.addWidget(self._field_label("Размер карточки"))
        row = QHBoxLayout()
        row.setSpacing(10)
        self.card_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.card_size_slider.setRange(18, 250)  # десятые сантиметра
        self.card_size_slider.valueChanged.connect(
            lambda v: self._set_item(width=v / 10.0 * PX_PER_CM))
        self.card_size_spin = QDoubleSpinBox()
        self.card_size_spin.setRange(1.8, 25.0)
        self.card_size_spin.setDecimals(1)
        self.card_size_spin.setSingleStep(0.1)
        self.card_size_spin.setSuffix(" см")
        self.card_size_spin.setFixedWidth(88)
        self.card_size_spin.setMinimumHeight(34)
        self.card_size_spin.valueChanged.connect(
            lambda v: self._set_item(width=v * PX_PER_CM))
        row.addWidget(self.card_size_slider, 1)
        row.addWidget(self.card_size_spin)
        il.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(8)
        btn_front = self._ghost_button("Вперёд", 34)
        btn_front.setToolTip("Переместить карточку на передний план")
        btn_front.clicked.connect(lambda: self._move_card_to_layer(front=True))
        btn_back = self._ghost_button("Назад", 34)
        btn_back.setToolTip("Переместить карточку на задний план")
        btn_back.clicked.connect(lambda: self._move_card_to_layer(front=False))
        btn_center_card = self._ghost_button("В центр листа", 34)
        btn_center_card.clicked.connect(self._center_card_on_sheet)
        row.addWidget(btn_front, 1)
        row.addWidget(btn_back, 1)
        row.addWidget(btn_center_card, 1)
        il.addLayout(row)

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

        il.addWidget(self._field_label("Поворот и отражение фото"))
        grid = QGridLayout()
        grid.setSpacing(8)
        btn_photo_left = self._ghost_button("↺ Влево 90°", 34)
        btn_photo_left.clicked.connect(lambda: self._rotate_photo(-90))
        btn_photo_right = self._ghost_button("↻ Вправо 90°", 34)
        btn_photo_right.clicked.connect(lambda: self._rotate_photo(90))
        self.flip_h_button = self._segment_button("⇄ Горизонтально")
        self.flip_h_button.toggled.connect(
            lambda checked: self._set_item(flip_horizontal=checked))
        self.flip_v_button = self._segment_button("⇅ Вертикально")
        self.flip_v_button.toggled.connect(
            lambda checked: self._set_item(flip_vertical=checked))
        grid.addWidget(btn_photo_left, 0, 0)
        grid.addWidget(btn_photo_right, 0, 1)
        grid.addWidget(self.flip_h_button, 1, 0)
        grid.addWidget(self.flip_v_button, 1, 1)
        il.addLayout(grid)
        self.photo_transform_label = QLabel()
        self.photo_transform_label.setProperty("role", "muted")
        il.addWidget(self.photo_transform_label)

        lay.addWidget(item_card)

        caption_card, il = self._card(
            "Подпись", key="caption", expanded=False)
        il.addWidget(self._field_label("Подпись на рамке"))
        self.caption_edit = QPlainTextEdit()
        self.caption_edit.setPlaceholderText("лето 2026")
        self.caption_edit.setFixedHeight(58)
        self.caption_edit.setTabChangesFocus(True)
        self.caption_edit.textChanged.connect(
            lambda: self._set_item(
                caption=self.caption_edit.toPlainText()[:120],
                refresh_pixmap=False))
        il.addWidget(self.caption_edit)

        il.addWidget(self._field_label("Выравнивание подписи"))
        self.caption_align_combo = QComboBox()
        self.caption_align_combo.setMinimumHeight(36)
        self.caption_align_combo.addItem("Слева", "left")
        self.caption_align_combo.addItem("По центру", "center")
        self.caption_align_combo.addItem("Справа", "right")
        self.caption_align_combo.setCurrentIndex(1)
        self.caption_align_combo.currentIndexChanged.connect(
            lambda _idx: self._set_item(
                caption_align=self.caption_align_combo.currentData(),
                refresh_pixmap=False))
        il.addWidget(self.caption_align_combo)
        self._make_adjustment_row(
            il, "Размер подписи", "caption_scale", 0.6, 1.6)

        il.addWidget(self._field_label("Цвет подписи"))
        self.caption_color_button = self._color_button()
        self.caption_color_button.clicked.connect(self._choose_caption_color)
        il.addWidget(self.caption_color_button)
        btn_caption_auto = self._ghost_button("Цвет подписи — автоматически", 34)
        btn_caption_auto.clicked.connect(
            lambda: self._set_item(caption_color=None, refresh_pixmap=False))
        il.addWidget(btn_caption_auto)

        lay.addWidget(caption_card)

        style_card, il = self._card(
            "Фильтр и цвета", key="style", expanded=False)
        il.addWidget(self._field_label("Фильтр в стиле плёнки"))
        self.filter_combo = QComboBox()
        self.filter_combo.setMinimumHeight(40)
        self.filter_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        for key, title in FILTERS.items():
            self.filter_combo.addItem(title, key)
        self.filter_combo.currentIndexChanged.connect(
            lambda: self._set_item(filter=self.filter_combo.currentData()))
        il.addWidget(self.filter_combo)
        self.filter_gallery = VisualChoiceStrip()
        initial_item = self._item()
        self.filter_gallery.set_choices(
            self._make_filter_choices(
                self._filter_sample_image(), initial_item),
            current=initial_item.filter)
        self._filter_gallery_key = self._filter_gallery_cache_key()
        self.filter_gallery.selected.connect(
            lambda key: self._set_item(filter=key))
        il.addWidget(self.filter_gallery)
        self._make_adjustment_row(
            il, "Сила фильтра", "filter_intensity", 0.0, 1.0)
        self._make_adjustment_row(il, "Яркость", "brightness", 0.4, 1.8)
        self._make_adjustment_row(il, "Контраст", "contrast", 0.4, 1.8)
        self._make_adjustment_row(il, "Насыщенность", "saturation", 0.0, 2.0)
        self._make_adjustment_row(il, "Резкость", "sharpness", 0.0, 2.5)

        il.addWidget(self._field_label("Цвет рамки карточки"))
        self.frame_color_button = self._color_button()
        self.frame_color_button.clicked.connect(self._choose_frame_color)
        il.addWidget(self.frame_color_button)
        il.addWidget(self._make_swatch_row(
            FRAME_COLOR_PRESETS, lambda color: self._set_frame_color(color)))
        btn_frame_all = self._ghost_button("Этот цвет рамки — всем карточкам", 34)
        btn_frame_all.clicked.connect(self._apply_frame_color_to_all)
        il.addWidget(btn_frame_all)

        row = QHBoxLayout()
        row.setSpacing(8)
        btn_copy_style = self._ghost_button("Копир. стиль", 34)
        btn_copy_style.clicked.connect(self._copy_card_style)
        row.addWidget(btn_copy_style, 1)
        btn_paste_style = self._ghost_button("Встав. стиль", 34)
        btn_paste_style.clicked.connect(self._paste_card_style)
        row.addWidget(btn_paste_style, 1)
        il.addLayout(row)
        lay.addWidget(style_card)

        # --- Готово ---
        out_card, ol = self._card(
            "Готовый лист", key="output", expanded=True)
        self.size_label = QLabel()
        self.size_label.setProperty("role", "muted")
        self.size_label.setWordWrap(True)
        ol.addWidget(self.size_label)
        self.preflight_label = QLabel()
        self.preflight_label.setProperty("role", "muted")
        self.preflight_label.setWordWrap(True)
        ol.addWidget(self.preflight_label)
        btn_check = self._ghost_button("Проверить макет перед печатью", 38)
        btn_check.clicked.connect(
            lambda: self._confirm_preflight("Закрыть", manual=True))
        ol.addWidget(btn_check)
        btn_save = QPushButton("Сохранить JPG/PNG/PDF · 300 DPI")
        btn_save.setObjectName("primaryButton")
        btn_save.setMinimumHeight(44)
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.clicked.connect(self._export_dialog)
        ol.addWidget(btn_save)
        self.print_button = self._ghost_button("Предпросмотр и печать", 38)
        self.print_button.clicked.connect(self._print_dialog)
        ol.addWidget(self.print_button)
        btn_batch = self._ghost_button("Пакетная обработка фотографий…", 38)
        btn_batch.clicked.connect(self._batch_dialog)
        ol.addWidget(btn_batch)
        lay.addWidget(out_card)

        # --- Подсказки ---
        hint_card, hl = self._card(
            "Управление на холсте", key="hints", expanded=False)
        hint = QLabel(
            "Колесо — масштаб фото\n"
            "Shift + колесо — наклон\n"
            "Ctrl + колесо — масштаб просмотра\n"
            "Панель − / % / + слева внизу холста — масштаб просмотра\n"
            "Тянуть фото — сдвиг в рамке\n"
            "Тянуть рамку — двигать карточку\n"
            "Ручка сверху / Alt + тянуть — наклон\n"
            "Квадратная ручка — размер карточки\n"
            "Магниты помогают выровнять карточки; Alt отключает их\n"
            "Правый клик — действия с карточкой\n"
            "Ctrl+V на холсте — фото из буфера обмена\n"
            "Двойной клик — загрузить фото\n"
            "Лента карточек сверху — быстрый переход между слотами\n"
            "Ctrl+Tab / Ctrl+Shift+Tab — соседние карточки\n"
            "PageUp / PageDown на холсте — соседние карточки\n"
            "Ctrl+K — найти настройку или действие\n"
            "Стрелки — точный сдвиг фото\n"
            "Delete — удалить карточку, Ctrl+D — дублировать\n\n"
            "Можно выбрать или перетащить сразу несколько фото — "
            "новые карточки добавятся автоматически.")
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        hl.addWidget(hint)
        lay.addWidget(hint_card)
        lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setObjectName("inspector")
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(404)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.panel_scroll = scroll

        panel = QFrame()
        panel.setObjectName("inspectorPanel")
        panel.setFixedWidth(404)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(12, 12, 12, 10)
        header_layout.setSpacing(8)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.panel_search = QLineEdit()
        self.panel_search.setPlaceholderText(
            "Найти настройку или действие… (Ctrl+K)")
        self.panel_search.setClearButtonEnabled(True)
        self.panel_search.setMinimumHeight(38)
        self.panel_search.setAccessibleName("Поиск по настройкам и действиям")
        self.panel_search.returnPressed.connect(
            lambda: self._activate_search_result(self.panel_search.text()))
        search_row.addWidget(self.panel_search, 1)
        expand_all = QToolButton()
        expand_all.setObjectName("iconButton")
        expand_all.setText("+")
        expand_all.setFixedSize(36, 38)
        expand_all.setToolTip("Развернуть все разделы")
        expand_all.setAccessibleName("Развернуть все разделы")
        expand_all.clicked.connect(
            lambda: self._set_all_sections_expanded(True))
        search_row.addWidget(expand_all)
        collapse_all = QToolButton()
        collapse_all.setObjectName("iconButton")
        collapse_all.setText("-")
        collapse_all.setFixedSize(36, 38)
        collapse_all.setToolTip("Свернуть все разделы")
        collapse_all.setAccessibleName("Свернуть все разделы")
        collapse_all.clicked.connect(
            lambda: self._set_all_sections_expanded(False))
        search_row.addWidget(collapse_all)
        header_layout.addLayout(search_row)

        slot_title_row = QHBoxLayout()
        slot_title_row.setSpacing(8)
        slot_title = QLabel("Карточки")
        slot_title.setProperty("role", "section")
        slot_title_row.addWidget(slot_title)
        slot_title_row.addStretch(1)
        self.previous_slot_button = QToolButton()
        self.previous_slot_button.setObjectName("iconButton")
        self.previous_slot_button.setText("<")
        self.previous_slot_button.setFixedSize(34, 32)
        self.previous_slot_button.setToolTip("Предыдущая карточка (Ctrl+Shift+Tab)")
        self.previous_slot_button.setAccessibleName("Предыдущая карточка")
        self.previous_slot_button.clicked.connect(
            lambda: self._select_relative_card(-1))
        slot_title_row.addWidget(self.previous_slot_button)
        self.next_slot_button = QToolButton()
        self.next_slot_button.setObjectName("iconButton")
        self.next_slot_button.setText(">")
        self.next_slot_button.setFixedSize(34, 32)
        self.next_slot_button.setToolTip("Следующая карточка (Ctrl+Tab)")
        self.next_slot_button.setAccessibleName("Следующая карточка")
        self.next_slot_button.clicked.connect(
            lambda: self._select_relative_card(1))
        slot_title_row.addWidget(self.next_slot_button)
        header_layout.addLayout(slot_title_row)

        self.slot_scroll = QScrollArea()
        self.slot_scroll.setObjectName("slotStrip")
        self.slot_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.slot_scroll.setWidgetResizable(True)
        self.slot_scroll.setFixedHeight(78)
        self.slot_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.slot_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._slot_strip_content = QWidget()
        self._slot_strip_layout = QHBoxLayout(self._slot_strip_content)
        self._slot_strip_layout.setContentsMargins(2, 4, 2, 4)
        self._slot_strip_layout.setSpacing(7)
        self.slot_scroll.setWidget(self._slot_strip_content)
        header_layout.addWidget(self.slot_scroll)

        outer.addWidget(header)
        outer.addWidget(scroll, 1)
        self._build_search_targets()
        self._refresh_slot_strip()
        return panel

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
        if refresh_pixmap and fields.keys() & {
                "filter", "filter_intensity", "brightness", "contrast",
                "saturation", "sharpness", "photo_rotation",
                "flip_horizontal", "flip_vertical"}:
            self.canvas.refresh_item_pixmap(self._selected_index())
        self.canvas.update()
        self._sync_panel(from_item=True)
        self._note_change(before)

    def _set_project_setting(self, **fields) -> None:
        before = self._snapshot_state()
        for name, value in fields.items():
            setattr(self.project, name, value)
        self.project.clamp_settings()
        self.canvas.update()
        self._sync_layout_controls()
        self._sync_panel()
        self._commit_change(before)
        self._remember_project_defaults()

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
            sheet_label = self.project.sheet_label
            if self._project_path:
                state = "не сохранено" if dirty else "сохранено"
                self._subtitle_label.setText(
                    f"{name} · {state} · лист {sheet_label}")
            elif dirty:
                self._subtitle_label.setText(
                    f"Новый проект · не сохранено · лист {sheet_label}")
            else:
                self._subtitle_label.setText(f"Новый проект · лист {sheet_label}")

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
        controls = [
            self.paper_combo, self.sheet_width_spin, self.sheet_height_spin,
            self.card_format_combo, self.template_combo,
            self.safe_margin_spin, self.show_safe_button, self.snap_button,
            self.rb_land, self.rb_port, self.count_spin,
            *self.count_buttons.values(), self.cut_marks_button,
        ]
        blockers = [c.blockSignals(True) for c in controls]
        # При произвольном количестве ни один пресет не должен быть активен;
        # эксклюзивная QButtonGroup не даёт программно снять все отметки.
        self.count_group.setExclusive(False)
        try:
            paper_idx = self.paper_combo.findData(self.project.paper_size)
            if paper_idx >= 0:
                self.paper_combo.setCurrentIndex(paper_idx)
            self.sheet_width_spin.setValue(self.project.sheet_width_cm)
            self.sheet_height_spin.setValue(self.project.sheet_height_cm)
            is_custom_paper = self.project.paper_size == "custom"
            self.sheet_width_spin.setEnabled(is_custom_paper)
            self.sheet_height_spin.setEnabled(is_custom_paper)
            format_idx = self.card_format_combo.findData(self.project.card_format)
            if format_idx >= 0:
                self.card_format_combo.setCurrentIndex(format_idx)
            template_idx = self.template_combo.findData(self.project.template)
            if template_idx >= 0:
                self.template_combo.setCurrentIndex(template_idx)
            self.safe_margin_spin.setValue(self.project.safe_margin_mm)
            self.show_safe_button.setChecked(self.project.show_safe_area)
            self.snap_button.setChecked(self.project.snap_enabled)
            self.rb_land.setChecked(self.project.landscape)
            self.rb_port.setChecked(not self.project.landscape)
            count = len(self.project.items)
            self.count_spin.setValue(count)
            for preset, button in self.count_buttons.items():
                button.setChecked(preset == count)
            self.cut_marks_button.setChecked(self.project.cut_marks)
            if hasattr(self, "paper_gallery"):
                paper_key = (
                    self._ui_theme,
                    self.project.landscape,
                    (self.project.sheet_width_cm,
                     self.project.sheet_height_cm)
                    if self.project.paper_size == "custom" else None,
                )
                if getattr(self, "_paper_gallery_state", None) != paper_key:
                    self.paper_gallery.set_choices(
                        self._make_paper_choices(),
                        current=self.project.paper_size)
                    self._paper_gallery_state = paper_key
                else:
                    self.paper_gallery.set_current(self.project.paper_size)
            if hasattr(self, "format_gallery"):
                self.format_gallery.set_current(self.project.card_format)
            if hasattr(self, "template_gallery"):
                self.template_gallery.set_current(self.project.template)
        finally:
            for control, blocked in zip(controls, blockers):
                control.blockSignals(blocked)
            self.count_group.setExclusive(True)
        can_add = len(self.project.items) < MAX_CARDS
        self.add_card_button.setEnabled(can_add)
        self.duplicate_card_button.setEnabled(can_add)
        self.delete_card_button.setEnabled(len(self.project.items) > 1)
        if hasattr(self, "align_buttons"):
            for button in self.align_buttons.values():
                button.setEnabled(len(self.project.items) >= 2)
            self.distribute_x_button.setEnabled(len(self.project.items) >= 3)
            self.distribute_y_button.setEnabled(len(self.project.items) >= 3)
        self._style_color_button(
            self.background_button, self.project.background_color,
            f"Фон: {self.project.background_color.upper()}")
        self._style_color_button(
            self.background2_button, self.project.background_color2,
            f"Второй: {self.project.background_color2.upper()}")
        self.background2_button.setEnabled(
            self.project.background_style != "solid")
        if hasattr(self, "background_gallery"):
            bg_key = (self.project.background_color,
                      self.project.background_color2, self._ui_theme)
            if getattr(self, "_background_gallery_state", None) != bg_key:
                self.background_gallery.set_choices(
                    self._make_background_choices(),
                    current=self.project.background_style)
                self._background_gallery_state = bg_key
            else:
                self.background_gallery.set_current(
                    self.project.background_style)
        self._refresh_slot_strip()

    def _apply_state(self, state: tuple[Project, int]) -> None:
        project, selected = state
        self._applying_state = True
        self._history_timer.stop()
        try:
            # Один и тот же объект Project уже привязан к Canvas: заменяем
            # целиком его словарь полей, включая все новые настройки.
            new_state = copy.deepcopy(project)
            self.project.__dict__.clear()
            self.project.__dict__.update(new_state.__dict__)
            self.project.clamp_settings()
            for state_item in self.project.items:
                state_item.clamp()
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
        self._apply_saved_project_defaults(project)
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
        self.size_label.setText(
            f"Файл: {self.project.sheet_w}×{self.project.sheet_h} px\n"
            f"Печать: {self.project.sheet_label} при 300 DPI")
        self.print_button.setText(
            f"Предпросмотр и печать {self.project.sheet_label}")

        if item.photo_path and item.photo_size:
            self.slot_state.setText(
                f"Фото: {item.photo_size[0]}×{item.photo_size[1]} px")
            dpi = item.effective_print_dpi()
            if dpi is None:
                self.dpi_label.setText("Разрешение печати: не определено")
            elif dpi >= 300:
                self.dpi_label.setText(
                    f"✓ {dpi:.0f} DPI после кадрирования — отлично для печати")
            elif dpi >= 180:
                self.dpi_label.setText(
                    f"⚠ {dpi:.0f} DPI после кадрирования — ниже 300 DPI")
            else:
                self.dpi_label.setText(
                    f"⚠ {dpi:.0f} DPI после кадрирования — низкое разрешение")
        elif item.photo_path:
            self.dpi_label.setText("Разрешение печати: размер фото не определён")
        else:
            self.dpi_label.setText("Разрешение печати: нет фотографии")

        issues = analyze_project(self.project)
        if issues:
            warning_count, info_count = issue_counts(issues)
            self.preflight_label.setText(
                f"Проверка макета: {warning_count} предупреждений, "
                f"{info_count} замечаний")
        else:
            self.preflight_label.setText("✓ Проверка макета: замечаний нет")

        widgets = [
            self.rot_slider, self.rot_spin, self.zoom_slider, self.zoom_spin,
            self.card_size_slider, self.card_size_spin,
            self.flip_h_button, self.flip_v_button,
            self.caption_edit, self.caption_align_combo, self.filter_combo,
        ]
        for slider, spin, _scale in self._adjustment_controls.values():
            widgets.extend([slider, spin])
        blockers = [w.blockSignals(True) for w in widgets]
        try:
            self.rot_slider.setValue(int(round(item.rotation * 10)))
            self.rot_spin.setValue(item.rotation)
            self.zoom_slider.setValue(min(400, int(round(item.zoom * 100))))
            self.zoom_spin.setValue(int(round(item.zoom * 100)))
            self.card_size_slider.setValue(int(round(item.width_cm * 10)))
            self.card_size_spin.setValue(item.width_cm)
            self.flip_h_button.setChecked(item.flip_horizontal)
            self.flip_v_button.setChecked(item.flip_vertical)
            if self.caption_edit.toPlainText() != item.caption:
                self.caption_edit.setPlainText(item.caption)
            align_idx = self.caption_align_combo.findData(item.caption_align)
            if align_idx >= 0:
                self.caption_align_combo.setCurrentIndex(align_idx)
            for field_name, (slider, spin, scale) in \
                    self._adjustment_controls.items():
                value = float(getattr(item, field_name))
                slider.setValue(int(round(value * scale)))
                spin.setValue(value)
            idx = self.filter_combo.findData(item.filter)
            if idx >= 0:
                self.filter_combo.setCurrentIndex(idx)
        finally:
            for w, b in zip(widgets, blockers):
                w.blockSignals(b)

        transform_parts: list[str] = []
        if item.photo_rotation:
            transform_parts.append(f"поворот {item.photo_rotation}°")
        if item.flip_horizontal:
            transform_parts.append("отражение ⇄")
        if item.flip_vertical:
            transform_parts.append("отражение ⇅")
        self.photo_transform_label.setText(
            "Ориентация фото: "
            + (", ".join(transform_parts) if transform_parts else "исходная"))
        self._style_color_button(
            self.frame_color_button, item.frame_color,
            f"Рамка: {item.frame_color.upper()}")
        caption_hex = item.caption_color or ("#%02x%02x%02x" % item.caption_rgb)
        caption_text = (
            f"Подпись: {caption_hex.upper()}" if item.caption_color
            else "Подпись: автоматически")
        self._style_color_button(
            self.caption_color_button, caption_hex, caption_text)
        if hasattr(self, "filter_gallery"):
            self.filter_gallery.set_current(item.filter)
            self._schedule_filter_gallery_refresh()
        self._refresh_slot_strip()

    # ------------------------------------------------------------- действия
    def _orientation_changed(self, _checked: bool) -> None:
        before = self._snapshot_state()
        self.project.set_layout(len(self.project.items), landscape=self.rb_land.isChecked())
        self.canvas.on_layout_changed()
        self.canvas.reset_view()
        self._sync_layout_controls()
        self._sync_panel()
        self._commit_change(before)
        self._remember_project_defaults()

    def _count_changed(self, count: int) -> None:
        before = self._snapshot_state()
        self.project.set_layout(count)
        if self.canvas.selected >= count:
            self.canvas.selected = 0
        self.canvas.on_layout_changed()
        self._sync_layout_controls()
        self._sync_panel()
        self._commit_change(before)

    def _paper_changed(self) -> None:
        paper = str(self.paper_combo.currentData() or "custom")
        before = self._snapshot_state()
        if paper == "custom":
            self.project.paper_size = "custom"
            self.project.clamp_settings()
        else:
            self.project.set_paper_size(
                paper, landscape=self.project.landscape)
            self.project.set_layout(
                len(self.project.items), landscape=self.project.landscape)
            self.canvas.reset_view()
        self.canvas.on_layout_changed()
        self._sync_layout_controls()
        self._sync_panel()
        self._commit_change(before)
        self._remember_project_defaults()

    def _custom_sheet_changed(self) -> None:
        if str(self.paper_combo.currentData() or "") != "custom":
            return
        width = self.sheet_width_spin.value()
        height = self.sheet_height_spin.value()
        if abs(width - self.project.sheet_width_cm) < 0.001 and \
                abs(height - self.project.sheet_height_cm) < 0.001:
            return
        before = self._snapshot_state()
        self.project.set_sheet_dimensions(width, height, paper_size="custom")
        self.project.set_layout(
            len(self.project.items), landscape=self.project.landscape)
        self.canvas.on_layout_changed()
        self.canvas.reset_view()
        self._sync_layout_controls()
        self._sync_panel()
        self._commit_change(before)
        self._remember_project_defaults()

    def _card_format_changed(self) -> None:
        card_format = str(self.card_format_combo.currentData() or "classic")
        if card_format == self.project.card_format:
            return
        before = self._snapshot_state()
        self.project.set_card_format(card_format, relayout=True)
        self.canvas.on_layout_changed()
        self._sync_layout_controls()
        self._sync_panel()
        self._commit_change(before)
        self._remember_project_defaults()

    def _apply_template(self) -> None:
        template_key = str(self.template_combo.currentData() or "classic")
        before = self._snapshot_state()
        template = apply_design_template(self.project, template_key)
        self.canvas.refresh_all_pixmaps()
        self._sync_layout_controls()
        self._sync_panel()
        self._commit_change(before)
        self._remember_project_defaults()
        self.statusBar().showMessage(
            f"Применён шаблон «{template.name}»", 3500)

    def _arrange_cards(self, action: str, mode: str = "") -> None:
        """Выравнивание/распределение/разброс всех карточек одной операцией."""
        before = self._snapshot_state()
        if action == "align":
            self.project.align_items(mode)
            message = "Карточки выровнены"
        elif action == "distribute":
            self.project.distribute_items(mode)
            message = "Промежутки между карточками выровнены"
        elif action == "scatter":
            self.project.scatter_items()
            message = "Карточки слегка разбросаны"
        elif action == "straighten":
            self.project.straighten_items()
            message = "Наклон всех карточек сброшен"
        else:  # pragma: no cover - защитный fallback
            return
        self.canvas.update()
        self._sync_panel()
        self._commit_change(before)
        self.statusBar().showMessage(message, 3000)

    def _reset_layout(self) -> None:
        before = self._snapshot_state()
        self.project.set_layout(len(self.project.items), landscape=self.rb_land.isChecked())
        self.canvas.on_layout_changed()
        self.canvas.reset_view()
        self._sync_layout_controls()
        self._sync_panel()
        self._commit_change(before)

    # ------------------------------------------- карточки, цвета и фото
    def _after_structure_changed(self, selected: int,
                                 before: tuple[Project, int], message: str) -> None:
        self.canvas.selected = max(
            0, min(len(self.project.items) - 1, selected))
        # Индексы могли сдвинуться: превью безопаснее пересоздать целиком.
        self.canvas.refresh_all_pixmaps()
        self._sync_layout_controls()
        self._sync_panel()
        self.canvas.update()
        self._commit_change(before)
        self.statusBar().showMessage(message, 3500)

    def _add_card(self) -> None:
        before = self._snapshot_state()
        try:
            index = self.project.add_item()
        except ValueError as exc:
            QMessageBox.information(self, "Лист заполнен", str(exc))
            return
        self._after_structure_changed(
            index, before, f"Добавлена карточка {index + 1}")

    def _duplicate_card(self) -> None:
        before = self._snapshot_state()
        try:
            index = self.project.duplicate_item(self._selected_index())
        except ValueError as exc:
            QMessageBox.information(self, "Лист заполнен", str(exc))
            return
        self._after_structure_changed(
            index, before, f"Карточка продублирована: слот {index + 1}")

    def _delete_card(self) -> None:
        if len(self.project.items) <= 1:
            QMessageBox.information(
                self, "Нельзя удалить",
                "На листе должна остаться хотя бы одна карточка.")
            return
        before = self._snapshot_state()
        index = self._selected_index()
        self.project.remove_item(index)
        self._after_structure_changed(
            min(index, len(self.project.items) - 1), before,
            "Карточка удалена")

    def _move_card_to_layer(self, *, front: bool) -> None:
        index = self._selected_index()
        target = len(self.project.items) - 1 if front else 0
        if index == target:
            return
        before = self._snapshot_state()
        new_index = self.project.move_item(index, target)
        self._after_structure_changed(
            new_index, before,
            "Карточка перемещена на передний план" if front
            else "Карточка перемещена на задний план")

    def _center_card_on_sheet(self) -> None:
        self._set_item(
            center_x=self.project.sheet_w / 2.0,
            center_y=self.project.sheet_h / 2.0,
        )

    def _rotate_photo(self, delta: int) -> None:
        item = self._item()
        self._set_item(photo_rotation=(item.photo_rotation + delta) % 360)

    def _pick_color(self, current: str, title: str) -> str | None:
        color = QColorDialog.getColor(QColor(current), self, title)
        return color.name() if color.isValid() else None

    def _set_background_color(self, color: str) -> None:
        self._set_project_setting(background_color=color)

    def _set_background_color2(self, color: str) -> None:
        self._set_project_setting(background_color2=color)

    def _choose_background_color2(self) -> None:
        color = self._pick_color(
            self.project.background_color2, "Второй цвет фона листа")
        if color:
            self._set_background_color2(color)

    def _choose_background_color(self) -> None:
        color = self._pick_color(
            self.project.background_color, "Цвет фона листа")
        if color:
            self._set_background_color(color)

    def _set_frame_color(self, color: str) -> None:
        self._set_item(frame_color=color, refresh_pixmap=False)

    def _choose_frame_color(self) -> None:
        color = self._pick_color(self._item().frame_color, "Цвет рамки карточки")
        if color:
            self._set_frame_color(color)

    def _choose_caption_color(self) -> None:
        item = self._item()
        current = item.caption_color or ("#%02x%02x%02x" % item.caption_rgb)
        color = self._pick_color(current, "Цвет подписи")
        if color:
            self._set_item(caption_color=color, refresh_pixmap=False)

    def _apply_frame_color_to_all(self) -> None:
        before = self._snapshot_state()
        color = self._item().frame_color
        for item in self.project.items:
            item.frame_color = color
            item.clamp()
        self.canvas.update()
        self._sync_panel()
        self._commit_change(before)

    def _load_photo_dialog(self, slot: int) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Выберите одно или несколько фото", "", IMAGE_FILTER)
        if paths:
            self._load_photo_paths(paths, slot)

    def _load_photo_paths(self, paths: list[str], start_slot: int = 0) -> int:
        """Загрузить фото подряд, при необходимости добавляя карточки."""
        if not paths or not self.project.items:
            return 0
        start_slot = max(0, min(len(self.project.items) - 1, int(start_slot)))
        before = self._snapshot_state()
        current = start_slot
        loaded = 0
        for path in paths:
            if current >= len(self.project.items):
                if len(self.project.items) >= MAX_CARDS:
                    break
                self.project.add_item()
            if self._load_photo_into(current, path, record_history=False):
                loaded += 1
                current += 1
        if loaded:
            self.canvas.selected = start_slot
            self.canvas.on_layout_changed()
            self._sync_layout_controls()
            self._sync_panel()
            self._commit_change(before)
        return loaded

    def _load_photo_into(self, slot: int, path: str,
                         *, record_history: bool = True) -> bool:
        try:
            # Для RAW и огромных оригиналов не нужно декодировать весь кадр
            # только ради размеров: превью Canvas загрузит отдельно.
            size = probe_image_size(path)
        except Exception as exc:  # noqa: BLE001 - все ошибки кодеков показываем в GUI
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
            item.photo_rotation = src.photo_rotation
            item.flip_horizontal = src.flip_horizontal
            item.flip_vertical = src.flip_vertical
            item.filter = src.filter
            item.filter_intensity = src.filter_intensity
            item.brightness = src.brightness
            item.contrast = src.contrast
            item.saturation = src.saturation
            item.sharpness = src.sharpness
            item.grain_seed = src.effective_grain_seed()
            item.clamp()
            self.canvas.refresh_item_pixmap(i)
        self.canvas.update()
        self._commit_change(before)

    _STYLE_FIELDS = (
        "frame_color", "filter", "filter_intensity", "brightness",
        "contrast", "saturation", "sharpness", "caption_scale",
        "caption_color", "caption_align",
    )

    def _copy_card_style(self) -> None:
        item = self._item()
        self._style_clipboard = {
            field_name: copy.deepcopy(getattr(item, field_name))
            for field_name in self._STYLE_FIELDS
        }
        self.statusBar().showMessage(
            f"Стиль карточки {self._selected_index() + 1} скопирован", 3000)

    def _paste_card_style(self) -> None:
        if not self._style_clipboard:
            QMessageBox.information(
                self, "Стиль не скопирован",
                "Сначала скопируйте стиль другой карточки.")
            return
        before = self._snapshot_state()
        item = self._item()
        for field_name, value in self._style_clipboard.items():
            setattr(item, field_name, copy.deepcopy(value))
        item.clamp()
        self.canvas.refresh_item_pixmap(self._selected_index())
        self.canvas.update()
        self._sync_panel()
        self._commit_change(before)
        self.statusBar().showMessage("Стиль карточки вставлен", 3000)

    def _paste_photo_from_clipboard(self, slot: int = -1) -> None:
        target = self._selected_index() if slot < 0 else slot
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()
        if mime is not None and mime.hasUrls():
            files = [path for url in mime.urls()
                     if (path := url.toLocalFile())
                     and is_supported_image_file(path)]
            if files:
                self._load_photo_paths(files, target)
                return
        if mime is not None and mime.hasImage():
            image = clipboard.image()
            if not image.isNull():
                handle, path = tempfile.mkstemp(
                    prefix="softpalaroid-clipboard-", suffix=".png")
                os.close(handle)
                if image.save(path, "PNG"):
                    if self._load_photo_into(target, path):
                        return
                else:
                    QMessageBox.warning(
                        self, "Буфер обмена",
                        "Не удалось сохранить изображение из буфера обмена.")
                    return
        if mime is not None and mime.hasText():
            candidate = mime.text().strip().strip('"')
            if candidate and os.path.isfile(candidate) \
                    and is_supported_image_file(candidate):
                self._load_photo_paths([candidate], target)
                return
        QMessageBox.information(
            self, "Буфер обмена",
            "В буфере обмена нет изображения или файла фотографии.")

    def _export_card_dialog(self, index: int = -1) -> None:
        if not self.project.items:
            return
        if 0 <= index < len(self.project.items):
            self.canvas.select(index)
        item = self._item()
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Сохранить отдельную карточку",
            f"polaroid_card_{self._selected_index() + 1}.png",
            "PNG с прозрачным фоном (*.png);;JPEG (*.jpg);;PDF (*.pdf)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            if "JPEG" in selected_filter:
                path += ".jpg"
            elif "PDF" in selected_filter:
                path += ".pdf"
            else:
                path += ".png"
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            save_card(item, path, background=self.project.background_rgb)
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Ошибка сохранения", str(exc))
            return
        QApplication.restoreOverrideCursor()
        self.statusBar().showMessage(
            f"Карточка сохранена: {os.path.basename(path)}", 5000)

    def _show_canvas_context_menu(self, index: int, global_pos) -> None:
        menu = QMenu(self)
        if 0 <= index < len(self.project.items):
            load_action = menu.addAction("Загрузить / заменить фото…")
            load_action.triggered.connect(lambda: self._load_photo_dialog(index))
            paste_action = menu.addAction("Вставить фото из буфера обмена")
            paste_action.triggered.connect(
                lambda: self._paste_photo_from_clipboard(index))
            export_action = menu.addAction("Экспорт этой карточки…")
            export_action.triggered.connect(
                lambda: self._export_card_dialog(index))
            menu.addSeparator()
            copy_style_action = menu.addAction("Копировать стиль карточки")
            copy_style_action.triggered.connect(self._copy_card_style)
            paste_style_action = menu.addAction("Вставить стиль карточки")
            paste_style_action.setEnabled(self._style_clipboard is not None)
            paste_style_action.triggered.connect(self._paste_card_style)
            menu.addSeparator()
            duplicate_action = menu.addAction("Дублировать карточку")
            duplicate_action.triggered.connect(self._duplicate_card)
            front_action = menu.addAction("На передний план")
            front_action.triggered.connect(
                lambda: self._move_card_to_layer(front=True))
            back_action = menu.addAction("На задний план")
            back_action.triggered.connect(
                lambda: self._move_card_to_layer(front=False))
            center_action = menu.addAction("В центр листа")
            center_action.triggered.connect(self._center_card_on_sheet)
            menu.addSeparator()
            delete_action = menu.addAction("Удалить карточку")
            delete_action.triggered.connect(self._delete_card)
        else:
            add_action = menu.addAction("Добавить карточку")
            add_action.triggered.connect(self._add_card)
            paste_action = menu.addAction("Вставить фото из буфера обмена")
            paste_action.triggered.connect(
                lambda: self._paste_photo_from_clipboard(self._selected_index()))
            check_action = menu.addAction("Проверить макет")
            check_action.triggered.connect(
                lambda: self._confirm_preflight("Закрыть", manual=True))
            batch_action = menu.addAction("Пакетная обработка…")
            batch_action.triggered.connect(self._batch_dialog)
        menu.exec(global_pos)

    def _confirm_preflight(self, continue_text: str = "Продолжить", *,
                           manual: bool = False) -> bool:
        """Показать замечания, но дать пользователю продолжить работу."""
        issues = analyze_project(self.project)
        if not issues:
            if manual:
                QMessageBox.information(
                    self, "Проверка макета",
                    "Замечаний нет: макет готов к экспорту и печати.")
            return True
        dialog = PreflightDialog(issues, self, continue_text=continue_text)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if dialog.navigation_index >= 0:
            self.canvas.select(dialog.navigation_index)
            self._sync_panel()
            self.canvas.setFocus()
            self.statusBar().showMessage(
                f"Выбрана проблемная карточка {dialog.navigation_index + 1}",
                3500)
            return False
        return accepted

    def _warn_empty_slots(self) -> bool:
        # Совместимое имя для старых вызовов: теперь проверяется весь макет.
        return self._confirm_preflight("Продолжить")

    def _export_dialog(self) -> None:
        if not self._confirm_preflight("Продолжить экспорт"):
            return
        dims = (f"{self.project.sheet_width_cm:g}x"
                f"{self.project.sheet_height_cm:g}").replace(".", "_")
        path, selected_filter = QFileDialog.getSaveFileName(
            self, f"Сохранить лист {self.project.sheet_label}",
            f"polaroid_{dims}.jpg",
            "JPEG — для печати (*.jpg);;PNG (*.png);;PDF для печати (*.pdf)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            if "PNG" in selected_filter:
                path += ".png"
            elif "PDF" in selected_filter:
                path += ".pdf"
            else:
                path += ".jpg"
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
            f"можно печатать как лист {self.project.sheet_label}.")

    def _batch_dialog(self) -> None:
        initial = BatchOptions(
            cards_per_sheet=max(1, min(12, len(self.project.items) or 4)),
            landscape=self.project.landscape,
            paper_size=(self.project.paper_size
                        if self.project.paper_size in PAPER_SIZES else "10x15"),
            sheet_width_cm=self.project.sheet_width_cm,
            sheet_height_cm=self.project.sheet_height_cm,
            card_format=self.project.card_format,
            template=(self.project.template
                      if self.project.template in DESIGN_TEMPLATES else "classic"),
            safe_margin_mm=self.project.safe_margin_mm,
        )
        saved_output = self._settings.value("batchOutputDir", "")
        if not isinstance(saved_output, str) or not saved_output:
            saved_output = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.DocumentsLocation)
        dialog = BatchDialog(self, initial=initial, output_dir=saved_output)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        output_dir = dialog.output_dir()
        self._settings.setValue("batchOutputDir", output_dir)
        self._settings.sync()

        progress = QProgressDialog("Подготовка пакетной обработки…", "Отмена", 0, 1, self)
        progress.setWindowTitle("Пакетная обработка")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.show()

        def report(done: int, total: int, message: str) -> bool:
            progress.setMaximum(max(1, total))
            progress.setValue(done)
            progress.setLabelText(message)
            QApplication.processEvents()
            return not progress.wasCanceled()

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = export_batch(
                dialog.photo_paths(), output_dir,
                options=dialog.options(), progress=report)
        finally:
            QApplication.restoreOverrideCursor()
            progress.close()

        lines = [
            f"Фотографий обработано: {result.photo_count}",
            f"Листов сохранено: {result.sheet_count}",
            f"Папка: {output_dir}",
        ]
        if result.errors:
            lines.append("")
            lines.append("Предупреждения:")
            lines.extend(result.errors[:10])
            if len(result.errors) > 10:
                lines.append(f"…и ещё {len(result.errors) - 10}")
        text = "\n".join(lines)
        if result.output_files:
            QMessageBox.information(self, "Пакетная обработка завершена", text)
        else:
            QMessageBox.warning(self, "Пакетная обработка", text)
        self.statusBar().showMessage(
            f"Пакетно сохранено листов: {result.sheet_count}", 5000)

    @staticmethod
    def _draw_image_to_printer(printer: QPrinter, image: QImage) -> None:
        painter = QPainter(printer)
        try:
            page_rect = QRectF(printer.pageRect(QPrinter.Unit.DevicePixel))
            scaled = QSizeF(image.size()).scaled(
                page_rect.size(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRectF(
                page_rect.x() + (page_rect.width() - scaled.width()) / 2.0,
                page_rect.y() + (page_rect.height() - scaled.height()) / 2.0,
                scaled.width(), scaled.height())
            painter.drawImage(target, image)
        finally:
            painter.end()

    def _print_dialog(self) -> None:
        if not self._confirm_preflight("Продолжить к печати"):
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
        w_mm = self.project.sheet_width_cm * 10.0
        h_mm = self.project.sheet_height_cm * 10.0
        printer.setPageSize(
            QPageSize(QSizeF(w_mm, h_mm), QPageSize.Unit.Millimeter))
        printer.setFullPage(True)
        printer.setPageMargins(0, 0, 0, 0, QPrinter.Unit.Millimeter)

        dialog = QPrintPreviewDialog(printer, self)
        dialog.setWindowTitle(
            f"Предпросмотр и печать листа {self.project.sheet_label}")
        dialog.paintRequested.connect(
            lambda target_printer: self._draw_image_to_printer(
                target_printer, qimg))
        dialog.exec()
        self.statusBar().showMessage("Предпросмотр печати закрыт", 3000)

    def _about(self) -> None:
        QMessageBox.about(
            self, "О программе",
            f"<b>Softpalaroid {__version__}</b><br><br>"
            "Создание полароидных снимков из фотографий и их раскладка "
            "на фотобумаге 10×15, 13×18, 15×21, A5, A4 или произвольном "
            "листе для печати (300 DPI).<br><br>"
            "Поддерживаются классический Polaroid и форматы Instax, RAW, "
            "проверка фактического DPI и безопасной области, шаблоны, "
            "пакетная обработка, JPG/PNG/PDF и предпросмотр печати.<br><br>"
            "Тёмный интерфейс в стиле X. Шрифты: Inter и Caveat (OFL).")

    # ---------------------------------------------------------- drag & drop
    def dragEnterEvent(self, e: QDragEnterEvent) -> None:  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent) -> None:  # noqa: N802
        files = [path for url in e.mimeData().urls()
                 if (path := url.toLocalFile())
                 and is_supported_image_file(path)]
        if not files:
            return
        self._load_photo_paths(files, self._selected_index())
        e.acceptProposedAction()
