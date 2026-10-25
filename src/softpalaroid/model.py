"""Модель данных и геометрия: лист 10x15 см и полароидные карточки на нём.

Все координаты хранятся в пикселях экспортного разрешения (300 DPI),
поэтому предпросмотр и итоговый файл всегда совпадают по композиции.
"""
from __future__ import annotations

import copy
import math
import re
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

MIN_CARDS = 1
MAX_CARDS = 12
MIN_CARD_WIDTH_PX = 1.8 * PX_PER_CM
MAX_CARD_WIDTH_PX = 10.5 * PX_PER_CM

DEFAULT_BACKGROUND_COLOR = "#ffffff"
DEFAULT_FRAME_COLOR = "#fcfcfa"
DEFAULT_CAPTION_COLOR = (52, 52, 58)
LIGHT_CAPTION_COLOR = (250, 250, 246)

# Уголки обреза: короткие L-образные метки снаружи углов карточки.
CUT_MARK_GAP_PX = 9.0
CUT_MARK_ARM_PX = 58.0
CUT_MARK_WIDTH_PX = 3.0

_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def sheet_size_px(landscape: bool) -> tuple[int, int]:
    """Размер листа 10x15 см в пикселях при 300 DPI."""
    long_side = round(15 * PX_PER_CM)    # 1772
    short_side = round(10 * PX_PER_CM)   # 1181
    return (long_side, short_side) if landscape else (short_side, long_side)


def sheet_size_cm(landscape: bool) -> tuple[float, float]:
    return (15.0, 10.0) if landscape else (10.0, 15.0)


def normalize_color(value: object, default: str = DEFAULT_FRAME_COLOR) -> str:
    """Привести цвет к виду #rrggbb; при некорректном значении вернуть default."""
    if not isinstance(value, str) or not _COLOR_RE.fullmatch(value.strip()):
        return default
    color = value.strip().lower()
    if len(color) == 4:  # #rgb -> #rrggbb
        color = "#" + "".join(ch * 2 for ch in color[1:])
    return color


def color_to_rgb(value: object,
                 default: str = DEFAULT_FRAME_COLOR) -> tuple[int, int, int]:
    color = normalize_color(value, default)
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    """Относительная яркость 0..1 (упрощённая sRGB-формула)."""
    r, g, b = (channel / 255.0 for channel in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def caption_rgb_for(frame_color: object) -> tuple[int, int, int]:
    """Читаемый цвет подписи для светлой или тёмной рамки."""
    luminance = relative_luminance(color_to_rgb(frame_color))
    return DEFAULT_CAPTION_COLOR if luminance >= 0.45 else LIGHT_CAPTION_COLOR


def cut_mark_rgb(background_color: object) -> tuple[int, int, int]:
    """Цвет уголков обреза, контрастный к фону листа."""
    luminance = relative_luminance(
        color_to_rgb(background_color, DEFAULT_BACKGROUND_COLOR))
    return (92, 96, 102) if luminance >= 0.45 else (226, 229, 233)


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

    # Ориентация самого фото (не карточки) и оформление рамки
    photo_rotation: int = 0         # 0 / 90 / 180 / 270 по часовой стрелке
    flip_horizontal: bool = False
    flip_vertical: bool = False
    frame_color: str = DEFAULT_FRAME_COLOR

    # --- производная геометрия -------------------------------------------
    @property
    def height(self) -> float:
        return self.width * FRAME_RATIO

    @property
    def photo_side(self) -> float:
        return self.width * PHOTO_SIDE_FRAC

    @property
    def width_cm(self) -> float:
        return self.width / PX_PER_CM

    @property
    def frame_rgb(self) -> tuple[int, int, int]:
        return color_to_rgb(self.frame_color)

    @property
    def caption_rgb(self) -> tuple[int, int, int]:
        return caption_rgb_for(self.frame_color)

    @property
    def contrast_rgb(self) -> tuple[int, int, int]:
        """Чёрный или белый для тонких контуров поверх рамки."""
        return ((0, 0, 0)
                if relative_luminance(self.frame_rgb) >= 0.45
                else (255, 255, 255))

    def photo_rect_local(self) -> tuple[float, float, float, float]:
        """Прямоугольник фото в локальных координатах карточки (от её левого верхнего угла)."""
        inset = self.width * PHOTO_INSET_FRAC
        return (inset, inset, self.photo_side, self.photo_side)

    def effective_photo_size(self) -> tuple[int, int] | None:
        """Размер фото после его собственного поворота на 90/270 градусов."""
        if not self.photo_size:
            return None
        iw, ih = self.photo_size
        if self.photo_rotation % 360 in (90, 270):
            return (ih, iw)
        return (iw, ih)

    def displayed_photo_size(self) -> tuple[float, float] | None:
        """Размер фото после cover-масштаба * zoom, в пикселях окна."""
        size = self.effective_photo_size()
        if not size:
            return None
        iw, ih = size
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

    def local_to_sheet(self, x: float, y: float) -> tuple[float, float]:
        """Точка карточки от её левого верхнего угла -> координаты листа."""
        dx = x - self.width / 2.0
        dy = y - self.height / 2.0
        a = math.radians(self.rotation)
        return (
            self.center_x + dx * math.cos(a) - dy * math.sin(a),
            self.center_y + dx * math.sin(a) + dy * math.cos(a),
        )

    def cut_mark_segments(
            self, gap: float = CUT_MARK_GAP_PX,
            arm: float | None = None,
    ) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        """Отрезки уголков обреза вокруг карточки в координатах листа.

        Каждый уголок состоит из двух коротких линий снаружи угла карточки.
        Линии идут параллельно краям и «смотрят» внутрь макета, не заходя
        на саму белую рамку.
        """
        w, h = self.width, self.height
        actual_arm = CUT_MARK_ARM_PX if arm is None else arm
        actual_arm = min(actual_arm, w * 0.28, h * 0.28)
        segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for corner_x, corner_y in ((0.0, 0.0), (w, 0.0), (w, h), (0.0, h)):
            sx = -1.0 if corner_x == 0 else 1.0
            sy = -1.0 if corner_y == 0 else 1.0
            outside = (corner_x + sx * gap, corner_y + sy * gap)
            horizontal_end = (outside[0] - sx * actual_arm, outside[1])
            vertical_end = (outside[0], outside[1] - sy * actual_arm)
            p0 = self.local_to_sheet(*outside)
            segments.append((p0, self.local_to_sheet(*horizontal_end)))
            segments.append((p0, self.local_to_sheet(*vertical_end)))
        return segments

    def clamp(self) -> None:
        self.width = max(MIN_CARD_WIDTH_PX,
                         min(MAX_CARD_WIDTH_PX, float(self.width or 600.0)))
        self.rotation = max(-45.0, min(45.0, float(self.rotation or 0.0)))
        self.zoom = max(1.0, min(6.0, float(self.zoom or 1.0)))
        self.offset_x = max(0.0, min(1.0, float(self.offset_x)))
        self.offset_y = max(0.0, min(1.0, float(self.offset_y)))
        try:
            turns = int(round(float(self.photo_rotation) / 90.0))
        except (TypeError, ValueError):
            turns = 0
        self.photo_rotation = (turns * 90) % 360
        self.flip_horizontal = bool(self.flip_horizontal)
        self.flip_vertical = bool(self.flip_vertical)
        self.frame_color = normalize_color(self.frame_color)

    def set_photo(self, path: str, size: tuple[int, int]) -> None:
        self.photo_path = path
        self.photo_size = size
        self.zoom = 1.0
        self.offset_x = 0.5
        self.offset_y = 0.5
        self.photo_rotation = 0
        self.flip_horizontal = False
        self.flip_vertical = False


# ---------------------------------------------------------------------------
# Раскладка карточек по листу
# ---------------------------------------------------------------------------
def compute_layout(count: int, sheet_w: int, sheet_h: int) -> list[tuple[float, float, float]]:
    """Вернуть [(center_x, center_y, width), ...] для count карточек.

    Подбирается сетка (колонки x строки), при которой карточки получаются
    максимально крупными.
    """
    if count < 1:
        return []
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
    """Состояние листа: ориентация, оформление и список полароидов."""
    landscape: bool = True
    items: list[PolaroidItem] = field(default_factory=list)
    background_color: str = DEFAULT_BACKGROUND_COLOR
    cut_marks: bool = True

    def __post_init__(self) -> None:
        self.clamp_settings()
        for item in self.items:
            item.clamp()

    @property
    def sheet_w(self) -> int:
        return sheet_size_px(self.landscape)[0]

    @property
    def sheet_h(self) -> int:
        return sheet_size_px(self.landscape)[1]

    @property
    def background_rgb(self) -> tuple[int, int, int]:
        return color_to_rgb(self.background_color, DEFAULT_BACKGROUND_COLOR)

    def clamp_settings(self) -> None:
        self.background_color = normalize_color(
            self.background_color, DEFAULT_BACKGROUND_COLOR)
        self.cut_marks = bool(self.cut_marks)

    def set_layout(self, count: int, landscape: bool | None = None) -> None:
        """Применить раскладку, сохранив фото/настройки существующих слотов."""
        if landscape is not None:
            self.landscape = bool(landscape)
        count = max(MIN_CARDS, min(MAX_CARDS, int(count)))
        # Добавляем/отрезаем слоты
        while len(self.items) < count:
            self.items.append(PolaroidItem())
        del self.items[count:]
        positions = compute_layout(count, self.sheet_w, self.sheet_h)
        for item, (cx, cy, w) in zip(self.items, positions):
            item.center_x, item.center_y, item.width = cx, cy, w
            item.clamp()

    def add_item(self, item: PolaroidItem | None = None) -> int:
        """Добавить карточку в конец, не переставляя уже размещённые."""
        if len(self.items) >= MAX_CARDS:
            raise ValueError(f"На листе уже максимум карточек: {MAX_CARDS}")
        if item is None:
            frame = self.items[-1].frame_color if self.items \
                else DEFAULT_FRAME_COLOR
            item = PolaroidItem(frame_color=frame)
        position = compute_layout(
            len(self.items) + 1, self.sheet_w, self.sheet_h)[-1]
        item.center_x, item.center_y, item.width = position
        item.clamp()
        self.items.append(item)
        return len(self.items) - 1

    def duplicate_item(self, index: int) -> int:
        """Скопировать карточку сразу после оригинала с небольшим смещением."""
        if len(self.items) >= MAX_CARDS:
            raise ValueError(f"На листе уже максимум карточек: {MAX_CARDS}")
        if not 0 <= index < len(self.items):
            raise IndexError(index)
        clone = copy.deepcopy(self.items[index])
        shift = max(18.0, min(48.0, clone.width * 0.07))
        clone.center_x = max(0.0, min(float(self.sheet_w), clone.center_x + shift))
        clone.center_y = max(0.0, min(float(self.sheet_h), clone.center_y + shift))
        clone.clamp()
        self.items.insert(index + 1, clone)
        return index + 1

    def remove_item(self, index: int) -> PolaroidItem:
        """Удалить карточку; на листе должна остаться хотя бы одна."""
        if len(self.items) <= MIN_CARDS:
            raise ValueError("На листе должна остаться хотя бы одна карточка")
        if not 0 <= index < len(self.items):
            raise IndexError(index)
        return self.items.pop(index)

    def move_item(self, index: int, new_index: int) -> int:
        """Изменить порядок слоя карточки и вернуть её новый индекс."""
        if not 0 <= index < len(self.items):
            raise IndexError(index)
        new_index = max(0, min(len(self.items) - 1, int(new_index)))
        item = self.items.pop(index)
        self.items.insert(new_index, item)
        return new_index
