"""Интерактивный предпросмотр листа.

Управление мышью прямо на холсте:
- колесо мыши над полароидом      — масштаб фото внутри рамки
- Shift + колесо                   — наклон карточки
- Ctrl + колесо                    — масштаб просмотра листа
- перетаскивание фото              — сдвиг фото внутри рамки
- перетаскивание белой рамки       — перемещение карточки по листу
- Alt + перетаскивание / ручка ⤾   — наклон карточки
- двойной клик по карточке         — загрузить фото
- Delete / Ctrl+D / Ctrl+V         — удалить / дублировать / вставить фото
- перетаскивание пустого места     — прокрутка просмотра (когда увеличено)
"""
from __future__ import annotations

import math
from enum import Enum, auto

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PIL import UnidentifiedImageError
from PySide6.QtWidgets import QWidget

from .filters import apply_filter, apply_photo_adjustments, transform_photo
from .image_io import load_photo
from .model import (
    CUT_MARK_WIDTH_PX,
    PolaroidItem,
    Project,
    cut_mark_rgb,
)

PREVIEW_MAX_SIDE = 1200  # px: разрешение фото для превью (экспорт всегда в полном)

_CAPTION_FAMILIES = [
    "Caveat", "Segoe Script", "Segoe Print", "Ink Free", "Comic Sans MS",
    "Bradley Hand", "Chalkboard SE", "DejaVu Sans",
]


def _caption_qfont(pixel_size: int) -> QFont:
    font = QFont()
    font.setFamilies(_CAPTION_FAMILIES)
    font.setWeight(QFont.Weight.DemiBold)
    font.setPixelSize(max(8, pixel_size))
    return font


class _DragMode(Enum):
    NONE = auto()
    PAN_PHOTO = auto()
    MOVE_ITEM = auto()
    RESIZE_ITEM = auto()
    ROTATE = auto()
    PAN_VIEW = auto()


class CanvasWidget(QWidget):
    selectionChanged = Signal(int)
    itemChanged = Signal()
    photoLoadRequested = Signal(int)
    deleteRequested = Signal(int)
    duplicateRequested = Signal(int)
    pasteRequested = Signal(int)
    contextMenuRequested = Signal(int, QPoint)
    editStarted = Signal()
    editFinished = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(420, 340)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        self.project: Project | None = None
        self.selected: int = 0
        self._pixmaps: dict[int, QPixmap] = {}
        self._filter_bases: dict[int, object] = {}

        self._view_zoom = 1.0
        self._pan = QPointF(0.0, 0.0)

        self._mode = _DragMode.NONE
        self._drag_index = -1
        self._drag_start_widget = QPointF()
        self._drag_start_sheet = QPointF()
        self._start_offset = (0.5, 0.5)
        self._start_center = QPointF()
        self._grab_delta = QPointF()
        self._start_angle = 0.0
        self._start_rotation = 0.0
        self._start_pan = QPointF()
        self._handle_sheet = QPointF()  # ручка наклона, координаты листа
        self._resize_handle_sheet = QPointF()  # ручка размера, координаты листа
        self._start_width = 0.0
        self._start_local_vector = QPointF()
        self._snap_guides: list[tuple[str, float]] = []

    # ------------------------------------------------------------------ API
    def set_project(self, project: Project) -> None:
        self.project = project
        self.selected = 0
        self._pixmaps.clear()
        self._filter_bases.clear()
        for i in range(len(project.items)):
            self.refresh_item_pixmap(i)
        self.reset_view()

    def on_layout_changed(self) -> None:
        """После смены ориентации/количества: пересобрать список превью."""
        if self.project is None:
            return
        n = len(self.project.items)
        self._pixmaps = {i: p for i, p in self._pixmaps.items() if i < n}
        self._filter_bases = {
            i: p for i, p in self._filter_bases.items() if i < n}
        for i in range(n):
            if i not in self._pixmaps and self.project.items[i].photo_path:
                self.refresh_item_pixmap(i)
        if self.selected >= n:
            self.selected = max(0, n - 1)
        self.update()

    def refresh_item_pixmap(self, index: int) -> None:
        """Загрузить/перефильтровать превью фото слота."""
        if self.project is None or index >= len(self.project.items):
            return
        item = self.project.items[index]
        if not item.photo_path:
            self._pixmaps.pop(index, None)
            self._filter_bases.pop(index, None)
            return
        try:
            img = load_photo(item.photo_path)
        except Exception:  # noqa: BLE001 - битый/пропавший файл = пустой слот
            self._pixmaps.pop(index, None)
            self._filter_bases.pop(index, None)
            self.update()
            return
        item.photo_size = img.size
        img.thumbnail((PREVIEW_MAX_SIDE, PREVIEW_MAX_SIDE))
        img = transform_photo(
            img,
            rotation=item.photo_rotation,
            flip_horizontal=item.flip_horizontal,
            flip_vertical=item.flip_vertical,
        )
        img = apply_photo_adjustments(
            img,
            brightness=item.brightness,
            contrast=item.contrast,
            saturation=item.saturation,
            sharpness=item.sharpness,
        )
        # Небольшая копия до фильтра нужна визуальной галерее фильтров:
        # она показывает каждый фильтр на текущем фото, а не на абстрактной
        # картинке. Полноразмерный экспорт при этом не затрагивается.
        filter_base = img.copy()
        filter_base.thumbnail((320, 320))
        self._filter_bases[index] = filter_base
        img = apply_filter(
            img, item.filter,
            seed=item.effective_grain_seed(),
            intensity=item.filter_intensity,
        )
        qimg = QImage(
            img.tobytes(), img.width, img.height, img.width * 3,
            QImage.Format.Format_RGB888,
        ).copy()
        self._pixmaps[index] = QPixmap.fromImage(qimg)
        self.update()

    def refresh_all_pixmaps(self) -> None:
        """Перечитать превью всех слотов (после Undo/Redo или открытия проекта)."""
        self._pixmaps.clear()
        self._filter_bases.clear()
        if self.project is None:
            return
        for i in range(len(self.project.items)):
            self.refresh_item_pixmap(i)
        self.update()

    def preview_pixmap(self, index: int) -> QPixmap | None:
        """Текущее превью слота для ленты карточек."""
        return self._pixmaps.get(index)

    def filter_base_image(self, index: int):
        """Копия фото после ориентации/коррекций, но до плёночного фильтра."""
        base = self._filter_bases.get(index)
        return base.copy() if base is not None else None

    def select(self, index: int) -> None:
        if index != self.selected:
            self.selected = index
            self.selectionChanged.emit(index)
            self.update()

    def reset_view(self) -> None:
        self._view_zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.update()

    # ----------------------------------------------------- преобразования
    def _scale(self) -> float:
        if self.project is None:
            return 1.0
        pad = 28.0
        fit = min(
            (self.width() - pad * 2) / self.project.sheet_w,
            (self.height() - pad * 2) / self.project.sheet_h,
        )
        return max(0.01, fit) * self._view_zoom

    def _origin(self, scale: float | None = None) -> QPointF:
        """Смещение левого верхнего угла листа в виджете."""
        if self.project is None:
            return QPointF()
        s = self._scale() if scale is None else scale
        cx = self.width() / 2 - self.project.sheet_w * s / 2
        cy = self.height() / 2 - self.project.sheet_h * s / 2
        return QPointF(cx, cy) + self._pan

    def _to_sheet(self, widget_pos: QPointF) -> QPointF:
        s = self._scale()
        o = self._origin(s)
        return QPointF((widget_pos.x() - o.x()) / s, (widget_pos.y() - o.y()) / s)

    def _to_widget(self, sheet_pos: QPointF) -> QPointF:
        s = self._scale()
        o = self._origin(s)
        return QPointF(o.x() + sheet_pos.x() * s, o.y() + sheet_pos.y() * s)

    # --------------------------------------------------------- хит-тесты
    @staticmethod
    def _local(item: PolaroidItem, sheet_pt: QPointF) -> QPointF:
        """Точка листа -> локальные координаты карточки (от левого верхнего угла)."""
        dx = sheet_pt.x() - item.center_x
        dy = sheet_pt.y() - item.center_y
        a = math.radians(item.rotation)
        lx = dx * math.cos(a) + dy * math.sin(a)
        ly = -dx * math.sin(a) + dy * math.cos(a)
        return QPointF(lx + item.width / 2, ly + item.height / 2)

    def _hit_item(self, sheet_pt: QPointF) -> int:
        if self.project is None:
            return -1
        for i in range(len(self.project.items) - 1, -1, -1):
            item = self.project.items[i]
            loc = self._local(item, sheet_pt)
            if 0 <= loc.x() <= item.width and 0 <= loc.y() <= item.height:
                return i
        return -1

    def _in_photo(self, item: PolaroidItem, sheet_pt: QPointF) -> bool:
        loc = self._local(item, sheet_pt)
        px, py, pw, ph = item.photo_rect_local()
        return px <= loc.x() <= px + pw and py <= loc.y() <= py + ph

    @staticmethod
    def _local_vector(item: PolaroidItem, sheet_pt: QPointF) -> QPointF:
        """Вектор от центра карточки в её локальных осях."""
        dx = sheet_pt.x() - item.center_x
        dy = sheet_pt.y() - item.center_y
        a = math.radians(item.rotation)
        return QPointF(
            dx * math.cos(a) + dy * math.sin(a),
            -dx * math.sin(a) + dy * math.cos(a),
        )

    @staticmethod
    def _distance(a: QPointF, b: QPointF) -> float:
        d = a - b
        return (d.x() ** 2 + d.y() ** 2) ** 0.5

    def _hit_handle(self, widget_pos: QPointF) -> bool:
        if self.project is None or not self.project.items:
            return False
        return self._distance(widget_pos, self._to_widget(self._handle_sheet)) <= 14

    def _hit_resize_handle(self, widget_pos: QPointF) -> bool:
        if self.project is None or not self.project.items:
            return False
        return self._distance(
            widget_pos, self._to_widget(self._resize_handle_sheet)) <= 14

    def _snap_center(self, item: PolaroidItem, proposed: QPointF,
                     modifiers=Qt.KeyboardModifier.NoModifier) -> QPointF:
        """Магнит центра/краёв карточки к листу, безопасной зоне и соседям."""
        self._snap_guides = []
        if self.project is None or not self.project.snap_enabled:
            return proposed
        if modifiers & Qt.KeyboardModifier.AltModifier:
            return proposed
        threshold = 10.0 / max(0.01, self._scale())
        corners = item.corners_sheet()
        rel_x = [x - item.center_x for x, _y in corners]
        rel_y = [y - item.center_y for _x, y in corners]
        own_x = (proposed.x() + min(rel_x), proposed.x(),
                 proposed.x() + max(rel_x))
        own_y = (proposed.y() + min(rel_y), proposed.y(),
                 proposed.y() + max(rel_y))

        targets_x = [0.0, self.project.sheet_w / 2.0,
                     float(self.project.sheet_w)]
        targets_y = [0.0, self.project.sheet_h / 2.0,
                     float(self.project.sheet_h)]
        if self.project.safe_margin_mm > 0:
            left, top, right, bottom = self.project.safe_rect_px()
            targets_x.extend([left, right])
            targets_y.extend([top, bottom])
        for other in self.project.items:
            if other is item:
                continue
            left, top, right, bottom = other.bounds_sheet()
            targets_x.extend([left, (left + right) / 2.0, right])
            targets_y.extend([top, (top + bottom) / 2.0, bottom])

        def best(own: tuple[float, float, float],
                 targets: list[float]) -> tuple[float, float] | None:
            result: tuple[float, float] | None = None
            for anchor in own:
                for target in targets:
                    delta = target - anchor
                    if abs(delta) <= threshold and (
                            result is None or abs(delta) < abs(result[0])):
                        result = (delta, target)
            return result

        dx = best(own_x, targets_x)
        dy = best(own_y, targets_y)
        snapped = QPointF(proposed)
        if dx is not None:
            snapped.setX(snapped.x() + dx[0])
            self._snap_guides.append(("v", dx[1]))
        if dy is not None:
            snapped.setY(snapped.y() + dy[0])
            self._snap_guides.append(("h", dy[1]))
        return snapped

    # ------------------------------------------------------------ рисование
    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#000000"))
        # Едва заметная точечная сетка рабочего пространства
        p.setPen(QPen(QColor("#17191c"), 2))
        step = 28
        for gx in range(step, self.width(), step):
            for gy in range(step, self.height(), step):
                p.drawPoint(gx, gy)

        if self.project is None:
            return
        scale = self._scale()
        origin = self._origin(scale)
        sheet_rect = QRectF(
            origin.x(), origin.y(),
            self.project.sheet_w * scale, self.project.sheet_h * scale,
        )
        # «Свечение»-подложка рабочего пространства, контур и сам лист
        p.fillRect(sheet_rect.adjusted(-10, -10, 10, 10), QColor(255, 255, 255, 10))
        p.fillRect(sheet_rect, QColor(self.project.background_color))
        p.setPen(QPen(QColor("#2f3336"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(sheet_rect)
        self._paint_cut_marks(p, origin, scale)

        for i, item in enumerate(self.project.items):
            self._paint_item(p, item, self._pixmaps.get(i), origin, scale)

        self._paint_safe_area(p, origin, scale)
        self._paint_dpi_badges(p)
        self._paint_snap_guides(p, origin, scale)
        if self.project.items:
            selected = max(0, min(self.selected, len(self.project.items) - 1))
            self._paint_selection(p, self.project.items[selected], origin, scale)

    def _paint_safe_area(self, p: QPainter,
                         origin: QPointF, scale: float) -> None:
        if self.project is None or not self.project.show_safe_area:
            return
        if self.project.safe_margin_mm <= 0:
            return
        left, top, right, bottom = self.project.safe_rect_px()
        rect = QRectF(
            origin.x() + left * scale, origin.y() + top * scale,
            (right - left) * scale, (bottom - top) * scale)
        accent = QColor("#1D9BF0")
        p.save()
        # Лёгкая вуаль снаружи безопасной зоны не меняет финальный рендер:
        # это только редакторская подсказка.
        sheet = QRectF(origin.x(), origin.y(),
                       self.project.sheet_w * scale,
                       self.project.sheet_h * scale)
        veil = QPainterPath()
        veil.setFillRule(Qt.FillRule.OddEvenFill)
        veil.addRect(sheet)
        veil.addRect(rect)
        p.fillPath(veil, QBrush(QColor(29, 155, 240, 18)))
        pen = QPen(accent, 1.4)
        pen.setDashPattern([6, 4])
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(rect)
        font = QFont()
        font.setPixelSize(10)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        label_rect = QRectF(rect.left() + 5, rect.top() + 4, 190, 18)
        p.fillRect(label_rect, QColor(0, 0, 0, 115))
        p.setPen(QColor("#ffffff"))
        p.drawText(label_rect.adjusted(5, 0, 0, 0),
                   Qt.AlignmentFlag.AlignVCenter,
                   f"безопасная область · {self.project.safe_margin_mm:g} мм")
        p.restore()

    def _paint_dpi_badges(self, p: QPainter) -> None:
        if self.project is None:
            return
        p.save()
        font = QFont()
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.Bold)
        metrics = QFontMetricsF(font)
        p.setFont(font)
        for item in self.project.items:
            if not item.photo_path:
                continue
            dpi = item.effective_print_dpi()
            if dpi is None or dpi >= 300.0:
                continue
            text = f"{dpi:.0f} DPI"
            pos = self._to_widget(QPointF(*item.local_to_sheet(8.0, 8.0)))
            width = metrics.horizontalAdvance(text) + 14
            rect = QRectF(pos.x() + 6, pos.y() + 6, width, 21)
            critical = dpi < 180.0
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor("#E0245E" if critical else "#F7B928")))
            p.drawRoundedRect(rect, 6, 6)
            p.setPen(QColor("#ffffff" if critical else "#1c1c1c"))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        p.restore()

    def _paint_snap_guides(self, p: QPainter,
                           origin: QPointF, scale: float) -> None:
        if self.project is None or not self._snap_guides:
            return
        p.save()
        pen = QPen(QColor("#F91880"), 1.4)
        pen.setDashPattern([7, 4])
        p.setPen(pen)
        top = origin.y()
        bottom = origin.y() + self.project.sheet_h * scale
        left = origin.x()
        right = origin.x() + self.project.sheet_w * scale
        for orientation, coord in self._snap_guides:
            if orientation == "v":
                x = origin.x() + coord * scale
                p.drawLine(QPointF(x, top), QPointF(x, bottom))
            else:
                y = origin.y() + coord * scale
                p.drawLine(QPointF(left, y), QPointF(right, y))
        p.restore()

    def _paint_cut_marks(self, p: QPainter,
                         origin: QPointF, scale: float) -> None:
        """Уголки обреза на макете: как в финальном файле и печати."""
        if self.project is None or not self.project.cut_marks:
            return
        color = QColor(*cut_mark_rgb(self.project.background_color))
        pen = QPen(color, max(1.0, CUT_MARK_WIDTH_PX * scale))
        pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        p.save()
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for item in self.project.items:
            for (x1, y1), (x2, y2) in item.cut_mark_segments():
                p.drawLine(
                    QPointF(origin.x() + x1 * scale, origin.y() + y1 * scale),
                    QPointF(origin.x() + x2 * scale, origin.y() + y2 * scale),
                )
        p.restore()

    def _paint_item(self, p: QPainter, item: PolaroidItem, pixmap: QPixmap | None,
                    origin: QPointF, scale: float) -> None:
        w, h = item.width, item.height
        p.save()
        p.translate(origin.x() + item.center_x * scale, origin.y() + item.center_y * scale)
        p.scale(scale, scale)
        p.rotate(item.rotation)
        p.translate(-w / 2, -h / 2)

        radius = w * 0.018
        frame = QPainterPath()
        frame.addRoundedRect(QRectF(0, 0, w, h), radius, radius)

        # Без тени: плоская карточка и тонкий нейтральный контур.
        p.fillPath(frame, QBrush(QColor(item.frame_color)))
        p.setPen(QPen(QColor(*item.contrast_rgb, 42), max(0.8, 1.1 / scale)))
        p.drawPath(frame)

        px, py, pw, ph = item.photo_rect_local()
        photo_rect = QRectF(px, py, pw, ph)
        if pixmap is not None:
            disp = item.displayed_photo_size()
            tl = item.photo_top_left_local()
            if disp and tl:
                p.save()
                p.setClipRect(photo_rect)
                p.drawPixmap(QRectF(tl[0], tl[1], disp[0], disp[1]), pixmap,
                             QRectF(pixmap.rect()))
                p.restore()
        else:
            p.fillRect(photo_rect, QColor("#e4e5e8"))
            p.setPen(QColor("#8a8f98"))
            font = QFont()
            font.setPixelSize(max(10, int(w * 0.042)))
            p.setFont(font)
            p.drawText(photo_rect, Qt.AlignmentFlag.AlignCenter,
                       "+ Добавить фото\n\nдвойной клик или перетаскивание файла")

        p.setPen(QPen(QColor(*item.contrast_rgb, 46), max(0.8, 1.1 / scale)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(photo_rect)

        caption = item.caption.strip()
        if caption.strip():
            area = QRectF(0, py + ph, w, h - (py + ph))
            lines = max(1, len(caption.splitlines()))
            divisor = 1.0 + 0.24 * (lines - 1)
            size = max(9, int(area.height() * 0.52 * item.caption_scale / divisor))
            horizontal = {
                "left": Qt.AlignmentFlag.AlignLeft,
                "center": Qt.AlignmentFlag.AlignHCenter,
                "right": Qt.AlignmentFlag.AlignRight,
            }.get(item.caption_align, Qt.AlignmentFlag.AlignHCenter)
            flags = (horizontal | Qt.AlignmentFlag.AlignVCenter
                     | Qt.TextFlag.TextWordWrap)
            font = _caption_qfont(size)
            while size > 9:
                bounds = QFontMetricsF(font).boundingRect(
                    area, int(flags), caption)
                if bounds.width() <= area.width() * 0.88 and \
                        bounds.height() <= area.height() * 0.92:
                    break
                size = max(9, int(size * 0.9))
                font = _caption_qfont(size)
            p.setFont(font)
            p.setPen(QColor(*item.caption_rgb))
            p.drawText(
                area.adjusted(w * 0.06, 0, -w * 0.06, 0),
                int(flags), caption)

        p.restore()

    def _paint_selection(self, p: QPainter, item: PolaroidItem,
                         origin: QPointF, scale: float) -> None:
        w, h = item.width, item.height
        accent = QColor("#1D9BF0")
        p.save()
        p.translate(origin.x() + item.center_x * scale, origin.y() + item.center_y * scale)
        p.scale(scale, scale)
        p.rotate(item.rotation)
        p.translate(-w / 2, -h / 2)

        pen = QPen(accent, 2.0 / scale)
        pen.setDashPattern([7 / scale, 5 / scale])
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        m = 7 / scale
        p.drawRoundedRect(QRectF(-m, -m, w + 2 * m, h + 2 * m), w * 0.018, w * 0.018)

        # Ручка наклона сверху по центру
        handle_dist = h / 2 + 34 / scale  # от центра карточки
        local_handle = QPointF(w / 2, h / 2 - handle_dist)
        p.setPen(QPen(accent, 1.6 / scale))
        p.drawLine(QPointF(w / 2, -m), local_handle)
        r = 9.0 / scale
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(local_handle, r, r)
        p.setBrush(QBrush(accent))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(local_handle, r * 0.45, r * 0.45)

        # Квадратная ручка размера в правом нижнем углу.
        local_resize = QPointF(w + m, h + m)
        rr = 8.0 / scale
        p.setPen(QPen(accent, 1.6 / scale))
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawRoundedRect(
            QRectF(local_resize.x() - rr, local_resize.y() - rr,
                   rr * 2, rr * 2),
            2.0 / scale, 2.0 / scale)
        p.setPen(QPen(accent, 1.4 / scale))
        p.drawLine(
            QPointF(local_resize.x() - rr * 0.45, local_resize.y() + rr * 0.45),
            QPointF(local_resize.x() + rr * 0.45, local_resize.y() - rr * 0.45))
        resize_sheet = item.local_to_sheet(local_resize.x(), local_resize.y())
        self._resize_handle_sheet = QPointF(*resize_sheet)

        # Запомнить позицию ручки наклона в координатах листа для хит-теста
        a = math.radians(item.rotation)
        dx, dy = 0.0, -handle_dist
        self._handle_sheet = QPointF(
            item.center_x + dx * math.cos(a) - dy * math.sin(a),
            item.center_y + dx * math.sin(a) + dy * math.cos(a),
        )
        p.restore()

    # ------------------------------------------------------------- мышь
    def mousePressEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if self.project is None or e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position()
        sheet_pt = self._to_sheet(pos)
        self._drag_start_widget = pos
        self._drag_start_sheet = sheet_pt

        if self._hit_resize_handle(pos) and self.project.items:
            self._begin_resize(self.selected, sheet_pt)
            return

        if self._hit_handle(pos) and self.project.items:
            self._begin_rotate(self.selected, sheet_pt)
            return

        idx = self._hit_item(sheet_pt)
        if idx >= 0:
            self.select(idx)
            item = self.project.items[idx]
            if e.modifiers() & Qt.KeyboardModifier.AltModifier:
                self._begin_rotate(idx, sheet_pt)
            elif item.photo_path and self._in_photo(item, sheet_pt):
                self.editStarted.emit()
                self._mode = _DragMode.PAN_PHOTO
                self._drag_index = idx
                self._start_offset = (item.offset_x, item.offset_y)
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            else:
                self.editStarted.emit()
                self._mode = _DragMode.MOVE_ITEM
                self._drag_index = idx
                self._grab_delta = QPointF(
                    item.center_x - sheet_pt.x(), item.center_y - sheet_pt.y())
                self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self._mode = _DragMode.PAN_VIEW
            self._start_pan = QPointF(self._pan)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _begin_resize(self, idx: int, sheet_pt: QPointF) -> None:
        if self.project is None or not 0 <= idx < len(self.project.items):
            return
        self.editStarted.emit()
        item = self.project.items[idx]
        self._mode = _DragMode.RESIZE_ITEM
        self._drag_index = idx
        self._start_width = item.width
        self._start_local_vector = self._local_vector(item, sheet_pt)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)

    def _begin_rotate(self, idx: int, sheet_pt: QPointF) -> None:
        self.editStarted.emit()
        item = self.project.items[idx]  # type: ignore[union-attr]
        self._mode = _DragMode.ROTATE
        self._drag_index = idx
        self._start_angle = math.degrees(
            math.atan2(sheet_pt.y() - item.center_y, sheet_pt.x() - item.center_x))
        self._start_rotation = item.rotation
        self.setCursor(Qt.CursorShape.CrossCursor)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if self.project is None:
            return
        pos = e.position()
        sheet_pt = self._to_sheet(pos)

        if self._mode is _DragMode.NONE:
            self._update_hover_cursor(pos, sheet_pt)
            return

        if self._mode is _DragMode.PAN_VIEW:
            self._pan = self._start_pan + (pos - self._drag_start_widget)
            self.update()
            return

        item = self.project.items[self._drag_index]
        if self._mode is _DragMode.PAN_PHOTO:
            disp = item.displayed_photo_size()
            if disp:
                _px, _py, pw, ph = item.photo_rect_local()
                ox, oy = disp[0] - pw, disp[1] - ph
                # Тащим в локальной (повёрнутой) системе карточки
                start_loc = self._local(item, self._drag_start_sheet)
                loc = self._local(item, sheet_pt)
                if ox > 0:
                    item.offset_x = self._start_offset[0] - (loc.x() - start_loc.x()) / ox
                if oy > 0:
                    item.offset_y = self._start_offset[1] - (loc.y() - start_loc.y()) / oy
        elif self._mode is _DragMode.MOVE_ITEM:
            proposed = QPointF(
                sheet_pt.x() + self._grab_delta.x(),
                sheet_pt.y() + self._grab_delta.y())
            snapped = self._snap_center(item, proposed, e.modifiers())
            item.center_x = max(
                0.0, min(float(self.project.sheet_w), snapped.x()))
            item.center_y = max(
                0.0, min(float(self.project.sheet_h), snapped.y()))
        elif self._mode is _DragMode.RESIZE_ITEM:
            current = self._local_vector(item, sheet_pt)
            denominator = (
                self._start_local_vector.x() ** 2
                + self._start_local_vector.y() ** 2)
            if denominator > 1e-9 and self._start_width > 0:
                factor = (
                    current.x() * self._start_local_vector.x()
                    + current.y() * self._start_local_vector.y()) / denominator
                item.width = self._start_width * max(0.05, factor)
        elif self._mode is _DragMode.ROTATE:
            ang = math.degrees(math.atan2(
                sheet_pt.y() - item.center_y, sheet_pt.x() - item.center_x))
            rot = self._start_rotation + (ang - self._start_angle)
            if abs(rot) < 2.0:  # магнит к нулю
                rot = 0.0
            item.rotation = rot

        item.clamp()
        self.itemChanged.emit()
        self.update()

    def _update_hover_cursor(self, pos: QPointF, sheet_pt: QPointF) -> None:
        if self._hit_resize_handle(pos):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            return
        if self._hit_handle(pos):
            self.setCursor(Qt.CursorShape.CrossCursor)
            return
        idx = self._hit_item(sheet_pt)
        if idx >= 0 and self.project is not None:
            item = self.project.items[idx]
            if item.photo_path and self._in_photo(item, sheet_pt):
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, _e: QMouseEvent) -> None:  # noqa: N802
        was_editing = self._mode in {
            _DragMode.PAN_PHOTO, _DragMode.MOVE_ITEM,
            _DragMode.RESIZE_ITEM, _DragMode.ROTATE,
        }
        self._mode = _DragMode.NONE
        self._drag_index = -1
        self._snap_guides = []
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        if was_editing:
            self.editFinished.emit()

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if self.project is None:
            return  
        idx = self._hit_item(self._to_sheet(e.position()))
        if idx >= 0:
            self.select(idx)
            self.photoLoadRequested.emit(idx)

    def contextMenuEvent(self, e) -> None:  # noqa: N802
        if self.project is None:
            return
        idx = self._hit_item(self._to_sheet(e.pos()))
        if idx >= 0:
            self.select(idx)
        self.contextMenuRequested.emit(idx, e.globalPos())
        e.accept()

    def wheelEvent(self, e: QWheelEvent) -> None:  # noqa: N802
        if self.project is None or not self.project.items:
            return
        steps = e.angleDelta().y() / 120.0
        if steps == 0:
            return
        pos = e.position()
        mods = e.modifiers()

        if mods & Qt.KeyboardModifier.ControlModifier:
            # Масштаб просмотра вокруг курсора
            sheet_pt = self._to_sheet(pos)
            fit_scale = self._scale() / self._view_zoom
            self._view_zoom = max(0.4, min(5.0, self._view_zoom * (1.15 ** steps)))
            new_scale = fit_scale * self._view_zoom
            # origin, при котором точка под курсором не сдвинется:
            target_origin = QPointF(pos.x() - sheet_pt.x() * new_scale,
                                    pos.y() - sheet_pt.y() * new_scale)
            center_term = QPointF(
                self.width() / 2 - self.project.sheet_w * new_scale / 2,
                self.height() / 2 - self.project.sheet_h * new_scale / 2)
            self._pan = target_origin - center_term
            self.update()
            e.accept()
            return

        idx = self._hit_item(self._to_sheet(pos))
        if idx < 0:
            idx = self.selected
        else:
            self.select(idx)
        item = self.project.items[idx]

        self.editStarted.emit()
        if mods & Qt.KeyboardModifier.ShiftModifier:
            item.rotation += steps * 2.0
        else:
            item.zoom *= 1.12 ** steps
        item.clamp()
        self.itemChanged.emit()
        self.update()
        self.editFinished.emit()
        e.accept()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        """Стрелки — точный сдвиг фото в выбранной карточке."""
        if self.project is None or not self.project.items:
            return super().keyPressEvent(e)
        step = 0.1 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 0.02
        item = self.project.items[self.selected]
        key = e.key()
        if key == Qt.Key.Key_Delete:
            self.deleteRequested.emit(self.selected)
            e.accept()
            return
        if key == Qt.Key.Key_D and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.duplicateRequested.emit(self.selected)
            e.accept()
            return
        if key == Qt.Key.Key_V and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.pasteRequested.emit(self.selected)
            e.accept()
            return
        if key in {Qt.Key.Key_PageDown, Qt.Key.Key_BracketRight}:
            self.select((self.selected + 1) % len(self.project.items))
            e.accept()
            return
        if key in {Qt.Key.Key_PageUp, Qt.Key.Key_BracketLeft}:
            self.select((self.selected - 1) % len(self.project.items))
            e.accept()
            return
        if key in {Qt.Key.Key_Left, Qt.Key.Key_Right,
                   Qt.Key.Key_Up, Qt.Key.Key_Down}:
            self.editStarted.emit()
        moved = True
        if key == Qt.Key.Key_Left:
            item.offset_x -= step
        elif key == Qt.Key.Key_Right:
            item.offset_x += step
        elif key == Qt.Key.Key_Up:
            item.offset_y -= step
        elif key == Qt.Key.Key_Down:
            item.offset_y += step
        else:
            moved = False
        if moved:
            item.clamp()
            self.itemChanged.emit()
            self.update()
            self.editFinished.emit()
            e.accept()
        else:
            super().keyPressEvent(e)
