"""Модель данных и геометрия: лист 10x15 см и полароидные карточки на нём.

Все координаты хранятся в пикселях экспортного разрешения (300 DPI),
поэтому предпросмотр и итоговый файл всегда совпадают по композиции.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Константы листа и полароида
# ---------------------------------------------------------------------------
DPI = 300
PX_PER_CM = DPI / 2.54  # 118.11 px

# Классический полароид (плёнка 600): карточка 88x107 мм, фото 79x79 мм.
FRAME_RATIO = 107.0 / 88.0        # высота / ширина карточки  (~1.216)
PHOTO_SIDE_FRAC = 79.0 / 88.0     # сторона квадратного фото, доля ширины карточки
PHOTO_INSET_FRAC = (1.0 - PHOTO_SIDE_FRAC) / 2.0  # отступ фото сверху и по бокам


def sheet_size_px(landscape: bool) -> tuple[int, int]:
    """Размер листа 10x15 см в пикселях при 300 DPI."""
    long_side = round(15 * PX_PER_CM)    # 1772
    short_side = round(10 * PX_PER_CM)   # 1181
    return (long_side, short_side) if landscape else (short_side, long_side)


def sheet_size_cm(landscape: bool) -> tuple[float, float]:
    return (15.0, 10.0) if landscape else (10.0, 15.0)


# ---------------------------------------------------------------------------
# Один полароид на листе
# ---------------------------------------------------------------------------
@dataclass
class PolaroidItem:
    # Позиция и размер карточки на листе (экспортные пиксели)
    center_x: float = 0.0
    center_y: float = 0.0
    width: float = 600.0            # ширина карточки; высота = width * FRAME_RATIO
    rotation: float = 0.0           # наклон, градусы (-45..45)

    # Фото внутри квадратного окна
    photo_path: str | None = None
    photo_size: tuple[int, int] | None = None  # (w, h) исходного фото после EXIF-поворота
    zoom: float = 1.0               # >= 1.0; 1.0 = фото ровно покрывает окно (cover)
    offset_x: float = 0.5           # 0..1 — какая часть «лишней» ширины срезана слева
    offset_y: float = 0.5           # 0..1 — аналогично сверху

    caption: str = ""
    filter: str = "none"

    # --- производная геометрия -------------------------------------------
    @property
    def height(self) -> float:
        return self.width * FRAME_RATIO

    @property
    def photo_side(self) -> float:
        return self.width * PHOTO_SIDE_FRAC

    def photo_rect_local(self) -> tuple[float, float, float, float]:
        """Прямоугольник фото в локальных координатах карточки (от её левого верхнего угла)."""
        inset = self.width * PHOTO_INSET_FRAC
        return (inset, inset, self.photo_side, self.photo_side)

    def displayed_photo_size(self) -> tuple[float, float] | None:
        """Размер фото после cover-масштаба * zoom, в пикселях окна."""
        if not self.photo_size:
            return None
        iw, ih = self.photo_size
        s = self.photo_side
        scale = max(s / iw, s / ih) * self.zoom
        return (iw * scale, ih * scale)

    def photo_top_left_local(self) -> tuple[float, float] | None:
        """Левый верхний угол отображаемого фото в локальных координатах карточки."""
        disp = self.displayed_photo_size()
        if disp is None:
            return None
        dw, dh = disp
        px, py, s, _ = self.photo_rect_local()
        return (px - self.offset_x * (dw - s), py - self.offset_y * (dh - s))

    def clamp(self) -> None:
        self.rotation = max(-45.0, min(45.0, self.rotation))
        self.zoom = max(1.0, min(6.0, self.zoom))
        self.offset_x = max(0.0, min(1.0, self.offset_x))
        self.offset_y = max(0.0, min(1.0, self.offset_y))

    def set_photo(self, path: str, size: tuple[int, int]) -> None:
        self.photo_path = path
        self.photo_size = size
        self.zoom = 1.0
        self.offset_x = 0.5
        self.offset_y = 0.5


# ---------------------------------------------------------------------------
# Раскладка карточек по листу (1 / 2 / 4)
# ---------------------------------------------------------------------------
def compute_layout(count: int, sheet_w: int, sheet_h: int) -> list[tuple[float, float, float]]:
    """Вернуть [(center_x, center_y, width), ...] для count карточек.

    Подбирается сетка (колонки x строки), при которой карточки получаются
    максимально крупными.
    """
    margin = min(sheet_w, sheet_h) * 0.035
    gap = min(sheet_w, sheet_h) * 0.03

    best: tuple[int, int, float] | None = None  # (cols, rows, card_width)
    for cols in range(1, count + 1):
        rows = math.ceil(count / cols)
        cell_w = (sheet_w - 2 * margin - (cols - 1) * gap) / cols
        cell_h = (sheet_h - 2 * margin - (rows - 1) * gap) / rows
        card_w = min(cell_w, cell_h / FRAME_RATIO)
        if best is None or card_w > best[2]:
            best = (cols, rows, card_w)
    cols, rows, card_w = best  # type: ignore[misc]

    cell_w = (sheet_w - 2 * margin - (cols - 1) * gap) / cols
    cell_h = (sheet_h - 2 * margin - (rows - 1) * gap) / rows

    result: list[tuple[float, float, float]] = []
    idx = 0
    for row in range(rows):
        # Последняя неполная строка центрируется
        in_row = min(cols, count - idx)
        row_width = in_row * cell_w + (in_row - 1) * gap
        start_x = (sheet_w - row_width) / 2.0
        cy = margin + row * (cell_h + gap) + cell_h / 2.0
        for col in range(in_row):
            cx = start_x + col * (cell_w + gap) + cell_w / 2.0
            result.append((cx, cy, card_w))
            idx += 1
    return result


@dataclass
class Project:
    """Состояние листа: ориентация и список полароидов."""
    landscape: bool = True
    items: list[PolaroidItem] = field(default_factory=list)

    @property
    def sheet_w(self) -> int:
        return sheet_size_px(self.landscape)[0]

    @property
    def sheet_h(self) -> int:
        return sheet_size_px(self.landscape)[1]

    def set_layout(self, count: int, landscape: bool | None = None) -> None:
        """Применить раскладку, сохранив фото/настройки существующих слотов."""
        if landscape is not None:
            self.landscape = landscape
        # Добавляем/отрезаем слоты
        while len(self.items) < count:
            self.items.append(PolaroidItem())
        del self.items[count:]
        positions = compute_layout(count, self.sheet_w, self.sheet_h)
        for item, (cx, cy, w) in zip(self.items, positions):
            item.center_x, item.center_y, item.width = cx, cy, w
