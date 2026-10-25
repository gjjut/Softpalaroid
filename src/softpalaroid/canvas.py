"""Интерактивный предпросмотр листа.

Управление мышью прямо на холсте:
- колесо мыши над полароидом      — масштаб фото внутри рамки
- Shift + колесо                   — наклон карточки
- Ctrl + колесо                    — масштаб просмотра листа
- перетаскивание фото              — сдвиг фото внутри рамки
- перетаскивание белой рамки       — перемещение карточки по листу
- Alt + перетаскивание / ручка ⤾   — наклон карточки
- двойной клик по карточке         — загрузить фото
- перетаскивание пустого места     — прокрутка просмотра (когда увеличено)
"""
from __future__ import annotations

import math
from enum import Enum, auto

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
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

from .filters import apply_filter
from .model import PHOTO_INSET_FRAC, PolaroidItem, Project
from .render import CAPTION_COLOR, FRAME_COLOR, load_photo

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
    ROTATE = auto()
    PAN_VIEW = auto()


class CanvasWidget(QWidget):
    selectionChanged = Signal(int)
    itemChanged = Signal()
    photoLoadRequested = Signal(int)
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
        self._handle_sheet = QPointF()  # позиция ручки наклона (координаты листа)

    # ------------------------------------------------------------------ API
    def set_project(self, project: Project) -> None:
        self.project = project
        self.selected = 0
        self._pixmaps.clear()
        for i in range(len(project.items)):
            self.refresh_item_pixmap(i)
        self.reset_view()

    def on_layout_changed(self) -> None:
        """После смены ориентации/количества: пересобрать список превью."""
        if self.project is None:
            return
        n = len(self.project.items)
        self._pixmaps = {i: p for i, p in self._pixmaps.items() if i < n}
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
            return
        try:
            img = load_photo(item.photo_path)
        except (OSError, UnidentifiedImageError):
            self._pixmaps.pop(index, None)
            self.update()
            return
        item.photo_size = img.size
        img.thumbnail((PREVIEW_MAX_SIDE, PREVIEW_MAX_SIDE))
        img = apply_filter(img, item.filter)
        qimg = QImage(
            img.tobytes(), img.width, img.height, img.width * 3,
            QImage.Format.Format_RGB888,
        ).copy()
        self._pixmaps[index] = QPixmap.fromImage(qimg)
        self.update()

    def refresh_all_pixmaps(self) -> None:
        """Перечитать превью всех слотов (после Undo/Redo или открытия проекта)."""
        self._pixmaps.clear()
        if self.project is None:
            return
        for i in range(len(self.project.items)):
            self.refresh_item_pixmap(i)
        self.update()

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
        px, py, s, _ = item.photo_rect_local()
        return px <= loc.x() <= px + s and py <= loc.y() <= py + s

    def _hit_handle(self, widget_pos: QPointF) -> bool:
        if self.project is None or not self.project.items:
            return False
        hw = self._to_widget(self._handle_sheet)
        d = widget_pos - hw
        return (d.x() ** 2 + d.y() ** 2) ** 0.5 <= 14

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
        # «Свечение»-подложка, контур и сам лист
        p.fillRect(sheet_rect.adjusted(-10, -10, 10, 10), QColor(255, 255, 255, 10))
        p.fillRect(sheet_rect, QColor("#ffffff"))
        p.setPen(QPen(QColor("#2f3336"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(sheet_rect)

        for i, item in enumerate(self.project.items):
            self._paint_item(p, item, self._pixmaps.get(i), origin, scale)

        if self.project.items:
            self._paint_selection(p, self.project.items[self.selected], origin, scale)

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

        # Тень
        p.save()
        p.translate(0, w * 0.018 + 4)
        p.fillPath(frame, QBrush(QColor(0, 0, 0, 60)))
        p.restore()

        p.fillPath(frame, QBrush(QColor(*FRAME_COLOR)))
        p.setPen(QPen(QColor(0, 0, 0, 34), max(0.8, 1.1 / scale)))
        p.drawPath(frame)

        px, py, s, _ = item.photo_rect_local()
        photo_rect = QRectF(px, py, s, s)
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

        p.setPen(QPen(QColor(0, 0, 0, 46), max(0.8, 1.1 / scale)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(photo_rect)

        if item.caption.strip():
            area = QRectF(0, py + s, w, h - (py + s))
            size = int(area.height() * 0.52)
            font = _caption_qfont(size)
            while size > 9 and QFontMetricsF(font).horizontalAdvance(item.caption) > w * 0.88:
                size = int(size * 0.9)
                font = _caption_qfont(size)
            p.setFont(font)
            p.setPen(QColor(*CAPTION_COLOR))
            p.drawText(area, Qt.AlignmentFlag.AlignCenter, item.caption)

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

        # Запомнить позицию ручки в координатах листа для хит-теста
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
                s = item.photo_side
                ox, oy = disp[0] - s, disp[1] - s
                # Тащим в локальной (повёрнутой) системе карточки
                start_loc = self._local(item, self._drag_start_sheet)
                loc = self._local(item, sheet_pt)
                if ox > 0:
                    item.offset_x = self._start_offset[0] - (loc.x() - start_loc.x()) / ox
                if oy > 0:
                    item.offset_y = self._start_offset[1] - (loc.y() - start_loc.y()) / oy
        elif self._mode is _DragMode.MOVE_ITEM:
            item.center_x = sheet_pt.x() + self._grab_delta.x()
            item.center_y = sheet_pt.y() + self._grab_delta.y()
            item.center_x = max(0.0, min(float(self.project.sheet_w), item.center_x))
            item.center_y = max(0.0, min(float(self.project.sheet_h), item.center_y))
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
            _DragMode.PAN_PHOTO, _DragMode.MOVE_ITEM, _DragMode.ROTATE,
        }
        self._mode = _DragMode.NONE
        self._drag_index = -1
        self.setCursor(Qt.CursorShape.ArrowCursor)
        if was_editing:
            self.editFinished.emit()

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if self.project is None:
            return  
        idx = self._hit_item(self._to_sheet(e.position()))
        if idx >= 0:
            self.select(idx)
            self.photoLoadRequested.emit(idx)

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
