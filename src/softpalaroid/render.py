"""Рендер готового листа 10x15 см в полном разрешении 300 DPI (Pillow).

Используется и для сохранения JPG/PNG, и для печати, поэтому то, что видит
пользователь в предпросмотре, полностью совпадает с результатом.
"""
from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .filters import apply_filter
from .model import DPI, PHOTO_INSET_FRAC, PolaroidItem, Project

FRAME_COLOR = (252, 252, 250)
CAPTION_COLOR = (52, 52, 58)
PLACEHOLDER_COLOR = (225, 225, 228)
SS = 2  # supersampling карточки для гладких краёв после поворота


def load_photo(path: str) -> Image.Image:
    """Загрузить фото с учётом EXIF-ориентации, в RGB.

    Возвращается полностью загруженная копия, файл сразу закрывается —
    важно для Windows (открытый файл нельзя удалить/перезаписать).
    """
    with Image.open(path) as src:
        img = ImageOps.exif_transpose(src)
        if img.mode != "RGB":
            img = img.convert("RGB")
        return img.copy()


def _font_candidates() -> list[str]:
    """Пути шрифтов, похожих на рукописные, по приоритету."""
    names: list[str] = []
    if sys.platform == "win32":
        fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        names = [
            os.path.join(fonts_dir, n)
            for n in ("segoesc.ttf", "SegoePrint.ttf", "comic.ttf", "Gabriola.ttf", "Inkfree.ttf")
        ]
    elif sys.platform == "darwin":
        names = [
            "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",
            "/System/Library/Fonts/Supplemental/ChalkboardSE.ttc",
        ]
    else:
        names = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        ]
    return [p for p in names if os.path.exists(p)]


def _caption_font(size_px: int) -> ImageFont.ImageFont:
    for path in _font_candidates():
        try:
            return ImageFont.truetype(path, size_px)
        except OSError:
            continue
    return ImageFont.load_default(size_px)


def _fit_caption(draw: ImageDraw.ImageDraw, text: str, max_w: float, base_size: int) -> ImageFont.ImageFont:
    size = base_size
    while size > 10:
        font = _caption_font(size)
        if draw.textlength(text, font=font) <= max_w:
            return font
        size = int(size * 0.9)
    return _caption_font(max(10, size))


def render_card(item: PolaroidItem, photo: Image.Image | None) -> Image.Image:
    """Одна карточка (без наклона и тени) в RGBA, с supersampling x2."""
    w = int(round(item.width)) * SS
    h = int(round(item.height)) * SS
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)

    radius = int(w * 0.018)
    draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=FRAME_COLOR + (255,))

    inset = item.width * PHOTO_INSET_FRAC * SS
    side = item.photo_side * SS
    x0, y0 = int(round(inset)), int(round(inset))
    s = int(round(side))

    if photo is not None and item.photo_size:
        iw, ih = photo.size
        scale = max(s / iw, s / ih) * item.zoom
        dw, dh = max(1, round(iw * scale)), max(1, round(ih * scale))
        resized = photo.resize((dw, dh), Image.LANCZOS)
        resized = apply_filter(resized, item.filter)
        cx = int(round(item.offset_x * (dw - s)))
        cy = int(round(item.offset_y * (dh - s)))
        crop = resized.crop((cx, cy, cx + s, cy + s))
        card.paste(crop, (x0, y0))
    else:
        draw.rectangle([x0, y0, x0 + s, y0 + s], fill=PLACEHOLDER_COLOR + (255,))

    # Тонкая внутренняя рамка вокруг фото
    draw.rectangle([x0, y0, x0 + s - 1, y0 + s - 1], outline=(0, 0, 0, 46), width=max(1, SS))

    if item.caption.strip():
        bottom_top = y0 + s
        area_h = h - bottom_top
        font = _fit_caption(draw, item.caption, w * 0.88, int(area_h * 0.42))
        draw.text(
            (w / 2, bottom_top + area_h / 2),
            item.caption,
            font=font,
            fill=CAPTION_COLOR + (255,),
            anchor="mm",
        )
    return card


def render_sheet(project: Project, background: tuple[int, int, int] = (255, 255, 255)) -> Image.Image:
    """Полный лист в экспортном разрешении."""
    sheet = Image.new("RGB", (project.sheet_w, project.sheet_h), background)

    for item in project.items:
        photo = load_photo(item.photo_path) if item.photo_path else None
        card = render_card(item, photo)

        # Поворот (Pillow крутит против часовой, нам нужна экранная система — по часовой)
        rotated = card.rotate(-item.rotation, resample=Image.BICUBIC, expand=True)
        if SS != 1:
            rotated = rotated.resize(
                (rotated.width // SS, rotated.height // SS), Image.LANCZOS
            )

        # Тень по силуэту повёрнутой карточки
        alpha = rotated.split()[3]
        shadow = Image.new("RGBA", rotated.size, (0, 0, 0, 255))
        shadow.putalpha(alpha.point(lambda a: int(a * 0.28)))
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(3.0, item.width * 0.012)))

        px = int(round(item.center_x - rotated.width / 2))
        py = int(round(item.center_y - rotated.height / 2))
        dy = int(round(item.width * 0.018)) + 4
        sheet.paste(shadow, (px, py + dy), shadow)
        sheet.paste(rotated, (px, py), rotated)

    return sheet


def save_sheet(project: Project, path: str) -> None:
    img = render_sheet(project)
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        img.save(path, "JPEG", quality=95, dpi=(DPI, DPI))
    else:
        img.save(path, "PNG", dpi=(DPI, DPI))
