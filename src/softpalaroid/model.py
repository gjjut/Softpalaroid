"""Модель данных и геометрия листа и полароидных карточек.

Все координаты хранятся в пикселях экспортного разрешения (300 DPI),
поэтому предпросмотр и итоговый файл всегда совпадают по композиции.
"""
from __future__ import annotations

import copy
import hashlib
import math
import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Константы листа и полароида
# ---------------------------------------------------------------------------
DPI = 300
PX_PER_CM = DPI / 2.54  # 118.11 px
PX_PER_MM = PX_PER_CM / 10.0

# Размеры бумаги: ключ -> (короткая, длинная сторона), см.
PAPER_SIZES: dict[str, tuple[float, float]] = {
    "10x15": (10.0, 15.0),
    "13x18": (13.0, 18.0),
    "15x21": (15.0, 21.0),
    "a5": (14.8, 21.0),
    "a4": (21.0, 29.7),
}
PAPER_LABELS: dict[str, str] = {
    "10x15": "10×15 см (фото)",
    "13x18": "13×18 см (фото)",
    "15x21": "15×21 см (фото)",
    "a5": "A5 · 14,8×21 см",
    "a4": "A4 · 21×29,7 см",
    "custom": "Произвольный размер",
}

# Классический полароид (плёнка 600): карточка 88x107 мм, фото 79x79 мм.
FRAME_RATIO = 107.0 / 88.0
PHOTO_SIDE_FRAC = 79.0 / 88.0
PHOTO_INSET_FRAC = (1.0 - PHOTO_SIDE_FRAC) / 2.0

MIN_CARDS = 1
MAX_CARDS = 12
MIN_CARD_WIDTH_PX = 1.8 * PX_PER_CM
MAX_CARD_WIDTH_PX = 25.0 * PX_PER_CM

DEFAULT_BACKGROUND_COLOR = "#ffffff"
DEFAULT_FRAME_COLOR = "#fcfcfa"
DEFAULT_CAPTION_COLOR = (52, 52, 58)
LIGHT_CAPTION_COLOR = (250, 250, 246)
DEFAULT_SAFE_MARGIN_MM = 5.0
MAX_SAFE_MARGIN_MM = 25.0

# Уголки обреза: короткие L-образные метки снаружи углов карточки.
CUT_MARK_GAP_PX = 9.0
CUT_MARK_ARM_PX = 58.0
CUT_MARK_WIDTH_PX = 3.0

_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


@dataclass(frozen=True)
class CardFormat:
    """Физический формат карточки и окна фотографии.

    ``photo_*_frac`` — доли ширины/высоты карточки. Такой формат одинаково
    удобно использовать и для квадратного окна, и для прямоугольного.
    """

    key: str
    name: str
    frame_ratio: float          # высота / ширина
    photo_x_frac: float
    photo_y_frac: float
    photo_w_frac: float
    photo_h_frac: float


CARD_FORMATS: dict[str, CardFormat] = {
    "classic": CardFormat(
        key="classic",
        name="Классический Polaroid · квадрат",
        frame_ratio=107.0 / 88.0,
        photo_x_frac=4.5 / 88.0,
        photo_y_frac=4.5 / 107.0,
        photo_w_frac=79.0 / 88.0,
        photo_h_frac=79.0 / 107.0,
    ),
    "instax_mini": CardFormat(
        key="instax_mini",
        name="Instax Mini · вертикальное фото",
        frame_ratio=86.0 / 54.0,
        photo_x_frac=4.0 / 54.0,
        photo_y_frac=5.0 / 86.0,
        photo_w_frac=46.0 / 54.0,
        photo_h_frac=62.0 / 86.0,
    ),
    "instax_square": CardFormat(
        key="instax_square",
        name="Instax Square · квадрат",
        frame_ratio=86.0 / 72.0,
        photo_x_frac=5.0 / 72.0,
        photo_y_frac=5.0 / 86.0,
        photo_w_frac=62.0 / 72.0,
        photo_h_frac=62.0 / 86.0,
    ),
    "instax_wide": CardFormat(
        key="instax_wide",
        name="Instax Wide · горизонтальное фото",
        frame_ratio=86.0 / 108.0,
        photo_x_frac=4.5 / 108.0,
        photo_y_frac=5.0 / 86.0,
        photo_w_frac=99.0 / 108.0,
        photo_h_frac=62.0 / 86.0,
    ),
}


def get_card_format(key: object) -> CardFormat:
    if isinstance(key, str) and key in CARD_FORMATS:
        return CARD_FORMATS[key]
    return CARD_FORMATS["classic"]


def sheet_size_px_for_dimensions(width_cm: float,
                                 height_cm: float) -> tuple[int, int]:
    return (max(1, round(width_cm * PX_PER_CM)),
            max(1, round(height_cm * PX_PER_CM)))


def sheet_size_px(landscape: bool) -> tuple[int, int]:
    """Размер классического листа 10x15 см при 300 DPI (совместимый API)."""
    short, long = PAPER_SIZES["10x15"]
    dims = (long, short) if landscape else (short, long)
    return sheet_size_px_for_dimensions(*dims)


def sheet_size_cm(landscape: bool) -> tuple[float, float]:
    short, long = PAPER_SIZES["10x15"]
    return (long, short) if landscape else (short, long)


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


def stable_grain_seed(path: str | None,
                      size: tuple[int, int] | None) -> int:
    """Стабильный seed зерна для конкретного исходного файла."""
    raw = f"{path or ''}|{size or ''}".encode("utf-8", "ignore")
    return int.from_bytes(hashlib.sha256(raw).digest()[:4], "big")


def _bounded_float(value: object, default: float,
                   minimum: float, maximum: float) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        number = default
    if not math.isfinite(number):
        number = default
    return max(minimum, min(maximum, number))


# ---------------------------------------------------------------------------
# Один полароид на листе
# ---------------------------------------------------------------------------
@dataclass
class PolaroidItem:
    center_x: float = 0.0
    center_y: float = 0.0
    width: float = 600.0
    rotation: float = 0.0

    photo_path: str | None = None
    photo_size: tuple[int, int] | None = None
    zoom: float = 1.0
    offset_x: float = 0.5
    offset_y: float = 0.5

    caption: str = ""
    filter: str = "none"

    photo_rotation: int = 0
    flip_horizontal: bool = False
    flip_vertical: bool = False
    frame_color: str = DEFAULT_FRAME_COLOR

    # Новые параметры редактора/шаблонов
    card_format: str = "classic"
    filter_intensity: float = 1.0
    brightness: float = 1.0
    contrast: float = 1.0
    saturation: float = 1.0
    sharpness: float = 1.0
    caption_scale: float = 1.0
    caption_color: str | None = None
    caption_align: str = "center"
    grain_seed: int = 0

    @property
    def card_format_spec(self) -> CardFormat:
        return get_card_format(self.card_format)

    @property
    def height(self) -> float:
        return self.width * self.card_format_spec.frame_ratio

    @property
    def photo_width(self) -> float:
        return self.width * self.card_format_spec.photo_w_frac

    @property
    def photo_height(self) -> float:
        return self.height * self.card_format_spec.photo_h_frac

    @property
    def photo_side(self) -> float:
        """Совместимое имя: ширина окна (для классики оно квадратное)."""
        return self.photo_width

    @property
    def width_cm(self) -> float:
        return self.width / PX_PER_CM

    @property
    def frame_rgb(self) -> tuple[int, int, int]:
        return color_to_rgb(self.frame_color)

    @property
    def caption_rgb(self) -> tuple[int, int, int]:
        if self.caption_color:
            return color_to_rgb(self.caption_color, "#34343a")
        return caption_rgb_for(self.frame_color)

    @property
    def contrast_rgb(self) -> tuple[int, int, int]:
        return ((0, 0, 0)
                if relative_luminance(self.frame_rgb) >= 0.45
                else (255, 255, 255))

    def effective_grain_seed(self) -> int:
        if self.grain_seed:
            return int(self.grain_seed)
        return stable_grain_seed(self.photo_path, self.photo_size)

    def photo_rect_local(self) -> tuple[float, float, float, float]:
        spec = self.card_format_spec
        return (
            self.width * spec.photo_x_frac,
            self.height * spec.photo_y_frac,
            self.photo_width,
            self.photo_height,
        )

    def effective_photo_size(self) -> tuple[int, int] | None:
        if not self.photo_size:
            return None
        iw, ih = self.photo_size
        if self.photo_rotation % 360 in (90, 270):
            return (ih, iw)
        return (iw, ih)

    def cover_scale(self) -> float | None:
        """Масштаб исходного фото к экспортным пикселям окна."""
        size = self.effective_photo_size()
        if not size:
            return None
        iw, ih = size
        if iw <= 0 or ih <= 0:
            return None
        return max(self.photo_width / iw, self.photo_height / ih) * self.zoom

    def effective_print_dpi(self) -> float | None:
        """Фактическая плотность исходных пикселей после cover-кадрирования."""
        scale = self.cover_scale()
        if not scale or scale <= 0:
            return None
        return DPI / scale

    def displayed_photo_size(self) -> tuple[float, float] | None:
        size = self.effective_photo_size()
        scale = self.cover_scale()
        if not size or scale is None:
            return None
        return (size[0] * scale, size[1] * scale)

    def photo_top_left_local(self) -> tuple[float, float] | None:
        disp = self.displayed_photo_size()
        if disp is None:
            return None
        dw, dh = disp
        px, py, pw, ph = self.photo_rect_local()
        return (px - self.offset_x * (dw - pw),
                py - self.offset_y * (dh - ph))

    def local_to_sheet(self, x: float, y: float) -> tuple[float, float]:
        dx = x - self.width / 2.0
        dy = y - self.height / 2.0
        a = math.radians(self.rotation)
        return (
            self.center_x + dx * math.cos(a) - dy * math.sin(a),
            self.center_y + dx * math.sin(a) + dy * math.cos(a),
        )

    def sheet_to_local(self, x: float, y: float) -> tuple[float, float]:
        dx = x - self.center_x
        dy = y - self.center_y
        a = math.radians(self.rotation)
        return (
            dx * math.cos(a) + dy * math.sin(a) + self.width / 2.0,
            -dx * math.sin(a) + dy * math.cos(a) + self.height / 2.0,
        )

    def corners_sheet(self) -> list[tuple[float, float]]:
        return [
            self.local_to_sheet(0.0, 0.0),
            self.local_to_sheet(self.width, 0.0),
            self.local_to_sheet(self.width, self.height),
            self.local_to_sheet(0.0, self.height),
        ]

    def bounds_sheet(self) -> tuple[float, float, float, float]:
        corners = self.corners_sheet()
        xs = [p[0] for p in corners]
        ys = [p[1] for p in corners]
        return (min(xs), min(ys), max(xs), max(ys))

    def cut_mark_segments(
            self, gap: float = CUT_MARK_GAP_PX,
            arm: float | None = None,
    ) -> list[tuple[tuple[float, float], tuple[float, float]]]:
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
        self.width = _bounded_float(
            self.width or 600.0, 600.0, MIN_CARD_WIDTH_PX, MAX_CARD_WIDTH_PX)
        self.rotation = _bounded_float(self.rotation or 0.0, 0.0, -45.0, 45.0)
        self.zoom = _bounded_float(self.zoom or 1.0, 1.0, 1.0, 6.0)
        self.offset_x = _bounded_float(self.offset_x, 0.5, 0.0, 1.0)
        self.offset_y = _bounded_float(self.offset_y, 0.5, 0.0, 1.0)
        try:
            turns = int(round(float(self.photo_rotation) / 90.0))
        except (TypeError, ValueError):
            turns = 0
        self.photo_rotation = (turns * 90) % 360
        self.flip_horizontal = bool(self.flip_horizontal)
        self.flip_vertical = bool(self.flip_vertical)
        self.frame_color = normalize_color(self.frame_color)
        self.card_format = get_card_format(self.card_format).key
        self.filter_intensity = _bounded_float(
            self.filter_intensity, 1.0, 0.0, 1.0)
        self.brightness = _bounded_float(self.brightness, 1.0, 0.4, 1.8)
        self.contrast = _bounded_float(self.contrast, 1.0, 0.4, 1.8)
        self.saturation = _bounded_float(self.saturation, 1.0, 0.0, 2.0)
        self.sharpness = _bounded_float(self.sharpness, 1.0, 0.0, 2.5)
        self.caption_scale = _bounded_float(
            self.caption_scale, 1.0, 0.6, 1.6)
        if isinstance(self.caption_color, str) and self.caption_color.strip():
            self.caption_color = normalize_color(
                self.caption_color, "#34343a")
        else:
            self.caption_color = None
        if self.caption_align not in {"left", "center", "right"}:
            self.caption_align = "center"
        try:
            self.grain_seed = int(self.grain_seed) & 0xFFFFFFFF
        except (TypeError, ValueError):
            self.grain_seed = 0

    def set_photo(self, path: str, size: tuple[int, int]) -> None:
        self.photo_path = path
        self.photo_size = size
        self.zoom = 1.0
        self.offset_x = 0.5
        self.offset_y = 0.5
        self.photo_rotation = 0
        self.flip_horizontal = False
        self.flip_vertical = False
        self.brightness = 1.0
        self.contrast = 1.0
        self.saturation = 1.0
        self.sharpness = 1.0
        self.grain_seed = stable_grain_seed(path, size)


# ---------------------------------------------------------------------------
# Раскладка карточек по листу
# ---------------------------------------------------------------------------
def compute_layout(count: int, sheet_w: int, sheet_h: int,
                   frame_ratio: float = FRAME_RATIO,
                   ) -> list[tuple[float, float, float]]:
    """Вернуть [(center_x, center_y, width), ...] для count карточек."""
    if count < 1:
        return []
    frame_ratio = max(0.2, float(frame_ratio or FRAME_RATIO))
    margin = min(sheet_w, sheet_h) * 0.035
    gap = min(sheet_w, sheet_h) * 0.03

    best: tuple[int, int, float] | None = None
    for cols in range(1, count + 1):
        rows = math.ceil(count / cols)
        cell_w = (sheet_w - 2 * margin - (cols - 1) * gap) / cols
        cell_h = (sheet_h - 2 * margin - (rows - 1) * gap) / rows
        card_w = min(cell_w, cell_h / frame_ratio)
        if best is None or card_w > best[2]:
            best = (cols, rows, card_w)
    cols, rows, card_w = best  # type: ignore[misc]

    cell_w = (sheet_w - 2 * margin - (cols - 1) * gap) / cols
    cell_h = (sheet_h - 2 * margin - (rows - 1) * gap) / rows

    result: list[tuple[float, float, float]] = []
    idx = 0
    for row in range(rows):
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
    """Состояние листа: бумага, оформление и список полароидов."""

    landscape: bool = True
    items: list[PolaroidItem] = field(default_factory=list)
    background_color: str = DEFAULT_BACKGROUND_COLOR
    cut_marks: bool = True

    paper_size: str = "10x15"
    sheet_width_cm: float = 15.0
    sheet_height_cm: float = 10.0
    card_format: str = "classic"
    template: str = "classic"
    safe_margin_mm: float = DEFAULT_SAFE_MARGIN_MM
    show_safe_area: bool = True
    snap_enabled: bool = True

    def __post_init__(self) -> None:
        self.clamp_settings()
        for item in self.items:
            item.clamp()

    @property
    def sheet_w(self) -> int:
        return sheet_size_px_for_dimensions(
            self.sheet_width_cm, self.sheet_height_cm)[0]

    @property
    def sheet_h(self) -> int:
        return sheet_size_px_for_dimensions(
            self.sheet_width_cm, self.sheet_height_cm)[1]

    @property
    def sheet_size_cm(self) -> tuple[float, float]:
        return (float(self.sheet_width_cm), float(self.sheet_height_cm))

    @property
    def sheet_label(self) -> str:
        def fmt(value: float) -> str:
            return ("%g" % value).replace(".", ",")

        return f"{fmt(self.sheet_width_cm)}×{fmt(self.sheet_height_cm)} см"

    @property
    def background_rgb(self) -> tuple[int, int, int]:
        return color_to_rgb(self.background_color, DEFAULT_BACKGROUND_COLOR)

    @property
    def card_format_spec(self) -> CardFormat:
        return get_card_format(self.card_format)

    @property
    def safe_margin_px(self) -> float:
        return float(self.safe_margin_mm) * PX_PER_MM

    def safe_rect_px(self) -> tuple[float, float, float, float]:
        margin = self.safe_margin_px
        return (margin, margin,
                max(margin, self.sheet_w - margin),
                max(margin, self.sheet_h - margin))

    def clamp_settings(self) -> None:
        self.background_color = normalize_color(
            self.background_color, DEFAULT_BACKGROUND_COLOR)
        self.cut_marks = bool(self.cut_marks)
        self.show_safe_area = bool(self.show_safe_area)
        self.snap_enabled = bool(self.snap_enabled)

        if not isinstance(self.paper_size, str) or not self.paper_size:
            self.paper_size = "custom"
        self.paper_size = self.paper_size.lower()
        if self.paper_size not in PAPER_SIZES and self.paper_size != "custom":
            self.paper_size = "custom"

        default_w, default_h = (15.0, 10.0) if self.landscape else (10.0, 15.0)
        self.sheet_width_cm = _bounded_float(
            self.sheet_width_cm, default_w, 5.0, 50.0)
        self.sheet_height_cm = _bounded_float(
            self.sheet_height_cm, default_h, 5.0, 50.0)
        # landscape остаётся источником истины для ориентации.
        if self.landscape and self.sheet_width_cm < self.sheet_height_cm:
            self.sheet_width_cm, self.sheet_height_cm = (
                self.sheet_height_cm, self.sheet_width_cm)
        elif not self.landscape and self.sheet_width_cm > self.sheet_height_cm:
            self.sheet_width_cm, self.sheet_height_cm = (
                self.sheet_height_cm, self.sheet_width_cm)

        self.card_format = get_card_format(self.card_format).key
        self.template = str(self.template or "custom")[:40]
        max_margin = min(
            MAX_SAFE_MARGIN_MM,
            min(self.sheet_width_cm, self.sheet_height_cm) * 10.0 * 0.45,
        )
        self.safe_margin_mm = _bounded_float(
            self.safe_margin_mm, DEFAULT_SAFE_MARGIN_MM, 0.0, max_margin)

    def set_paper_size(self, paper_size: str,
                       landscape: bool | None = None) -> None:
        if landscape is not None:
            self.landscape = bool(landscape)
        key = str(paper_size or "custom").lower()
        if key in PAPER_SIZES:
            short, long = PAPER_SIZES[key]
            self.paper_size = key
            self.sheet_width_cm, self.sheet_height_cm = (
                (long, short) if self.landscape else (short, long))
        else:
            self.paper_size = "custom"
        self.clamp_settings()

    def set_sheet_dimensions(self, width_cm: float, height_cm: float,
                             paper_size: str = "custom") -> None:
        self.sheet_width_cm = float(width_cm)
        self.sheet_height_cm = float(height_cm)
        self.landscape = self.sheet_width_cm >= self.sheet_height_cm
        self.paper_size = str(paper_size or "custom").lower()
        self.clamp_settings()

    def set_card_format(self, card_format: str, *, relayout: bool = False) -> None:
        self.card_format = get_card_format(card_format).key
        for item in self.items:
            item.card_format = self.card_format
            item.clamp()
        if relayout and self.items:
            self.set_layout(len(self.items))

    def set_layout(self, count: int, landscape: bool | None = None) -> None:
        if landscape is not None:
            landscape = bool(landscape)
            if landscape != self.landscape:
                self.landscape = landscape
                self.sheet_width_cm, self.sheet_height_cm = (
                    self.sheet_height_cm, self.sheet_width_cm)
                self.clamp_settings()
        count = max(MIN_CARDS, min(MAX_CARDS, int(count)))
        while len(self.items) < count:
            frame = self.items[-1].frame_color if self.items \
                else DEFAULT_FRAME_COLOR
            self.items.append(PolaroidItem(
                frame_color=frame, card_format=self.card_format))
        del self.items[count:]
        positions = compute_layout(
            count, self.sheet_w, self.sheet_h,
            frame_ratio=self.card_format_spec.frame_ratio)
        for item, (cx, cy, w) in zip(self.items, positions):
            item.center_x, item.center_y, item.width = cx, cy, w
            item.card_format = self.card_format
            item.clamp()

    def add_item(self, item: PolaroidItem | None = None) -> int:
        if len(self.items) >= MAX_CARDS:
            raise ValueError(f"На листе уже максимум карточек: {MAX_CARDS}")
        if item is None:
            frame = self.items[-1].frame_color if self.items \
                else DEFAULT_FRAME_COLOR
            item = PolaroidItem(frame_color=frame, card_format=self.card_format)
        else:
            item.card_format = self.card_format
        position = compute_layout(
            len(self.items) + 1, self.sheet_w, self.sheet_h,
            frame_ratio=self.card_format_spec.frame_ratio)[-1]
        item.center_x, item.center_y, item.width = position
        item.clamp()
        self.items.append(item)
        return len(self.items) - 1

    def duplicate_item(self, index: int) -> int:
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
        if len(self.items) <= MIN_CARDS:
            raise ValueError("На листе должна остаться хотя бы одна карточка")
        if not 0 <= index < len(self.items):
            raise IndexError(index)
        return self.items.pop(index)

    def move_item(self, index: int, new_index: int) -> int:
        if not 0 <= index < len(self.items):
            raise IndexError(index)
        new_index = max(0, min(len(self.items) - 1, int(new_index)))
        item = self.items.pop(index)
        self.items.insert(new_index, item)
        return new_index
