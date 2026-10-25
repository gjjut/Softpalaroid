"""Фильтры в стиле плёночной/полароидной фотографии (только Pillow)."""
from __future__ import annotations

import os

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps

# Ключ -> отображаемое имя в интерфейсе
FILTERS: dict[str, str] = {
    "none": "Без фильтра",
    "vintage": "Винтаж",
    "warm": "тёплый",
    "cold": "Холодный",
    "faded": "Выцветшая плёнка",
    "sepia": "Сепия",
    "bw": "Чёрно-белый",
}


def _tint(img: Image.Image, r: float, g: float, b: float) -> Image.Image:
    """Умножить каналы на коэффициенты."""
    chans = img.split()
    out = []
    for ch, k in zip(chans, (r, g, b)):
        out.append(ch.point(lambda v, k=k: max(0, min(255, int(v * k)))))
    return Image.merge("RGB", out)  # type: ignore[arg-type]


def _fade(img: Image.Image, lift: int = 22, compress: int = 18) -> Image.Image:
    """Поднять чёрную точку и убрать чисто-белый — эффект выцветшей плёнки."""
    lut = [lift + int(v * (255 - lift - compress) / 255) for v in range(256)]
    return img.point(lut * 3)


def _vignette(img: Image.Image, strength: float = 0.55) -> Image.Image:
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse([-w * 0.25, -h * 0.25, w * 1.25, h * 1.25], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=max(w, h) * 0.18))
    dark = ImageEnhance.Brightness(img).enhance(1.0 - strength)
    return Image.composite(img, dark, mask)


def _grain(img: Image.Image, amount: float = 0.06) -> Image.Image:
    w, h = img.size
    noise = Image.frombytes("L", (w, h), os.urandom(w * h)).convert("RGB")
    return Image.blend(img, noise, amount)


def _sepia(img: Image.Image) -> Image.Image:
    gray = ImageOps.grayscale(img)
    # Тёплая тонировка через таблицы каналов
    r = gray.point(lambda v: min(255, int(v * 1.07) + 12))
    g = gray.point(lambda v: int(v * 0.88) + 4)
    b = gray.point(lambda v: int(v * 0.62))
    return Image.merge("RGB", (r, g, b))


def transform_photo(img: Image.Image, rotation: int = 0,
                    flip_horizontal: bool = False,
                    flip_vertical: bool = False) -> Image.Image:
    """Отразить и повернуть само фото на 0/90/180/270° по часовой стрелке."""
    out = img
    if flip_horizontal:
        out = out.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if flip_vertical:
        out = out.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

    turns = int(round(rotation / 90.0)) % 4
    if turns == 1:       # 90° по часовой = 270° против часовой в Pillow
        out = out.transpose(Image.Transpose.ROTATE_270)
    elif turns == 2:
        out = out.transpose(Image.Transpose.ROTATE_180)
    elif turns == 3:     # 270° по часовой
        out = out.transpose(Image.Transpose.ROTATE_90)
    return out


def apply_filter(img: Image.Image, name: str) -> Image.Image:
    """Применить фильтр по ключу. img ожидается в режиме RGB."""
    if name == "none" or name not in FILTERS:
        return img

    if name == "bw":
        out = ImageOps.grayscale(img).convert("RGB")
        out = ImageEnhance.Contrast(out).enhance(1.08)
        return _vignette(_grain(out, 0.04), 0.35)

    if name == "sepia":
        return _vignette(_grain(_sepia(img), 0.03), 0.35)

    if name == "warm":
        out = _tint(img, 1.10, 1.02, 0.86)
        out = ImageEnhance.Color(out).enhance(1.12)
        return ImageEnhance.Brightness(out).enhance(1.03)

    if name == "cold":
        out = _tint(img, 0.90, 1.00, 1.12)
        out = ImageEnhance.Color(out).enhance(1.05)
        return out

    if name == "faded":
        out = ImageEnhance.Color(img).enhance(0.72)
        out = ImageEnhance.Contrast(out).enhance(0.85)
        out = _tint(out, 1.04, 0.98, 1.06)
        return _grain(_fade(out, lift=28, compress=22), 0.04)

    if name == "vintage":
        out = ImageEnhance.Color(img).enhance(0.82)
        out = _tint(out, 1.08, 0.98, 0.82)
        out = ImageEnhance.Contrast(out).enhance(0.95)
        out = _fade(out, lift=16, compress=12)
        out = _vignette(out, 0.5)
        return _grain(out, 0.05)

    return img
