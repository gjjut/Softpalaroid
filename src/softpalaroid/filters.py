"""Фильтры и базовая коррекция в стиле плёночной фотографии (Pillow)."""
from __future__ import annotations

import hashlib
import random

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

FILTERS: dict[str, str] = {
    "none": "Без фильтра",
    "vintage": "Винтаж",
    "warm": "тёплый",
    "cold": "Холодный",
    "faded": "Выцветшая плёнка",
    "sepia": "Сепия",
    "bw": "Чёрно-белый",
}

_DEFAULT_GRAIN_SEED = 0x50F7A1D


def _seed_int(seed: object, width: int, height: int) -> int:
    if isinstance(seed, int):
        base = seed & 0xFFFFFFFF
    elif seed is None:
        base = _DEFAULT_GRAIN_SEED
    else:
        digest = hashlib.sha256(str(seed).encode("utf-8", "ignore")).digest()
        base = int.from_bytes(digest[:4], "big")
    return (base ^ (width << 16) ^ height) & 0xFFFFFFFF


def _tint(img: Image.Image, r: float, g: float, b: float) -> Image.Image:
    chans = img.split()
    out = []
    for ch, k in zip(chans, (r, g, b)):
        out.append(ch.point(lambda v, k=k: max(0, min(255, int(v * k)))))
    return Image.merge("RGB", out)  # type: ignore[arg-type]


def _fade(img: Image.Image, lift: int = 22, compress: int = 18) -> Image.Image:
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


def _grain(img: Image.Image, amount: float = 0.06,
           seed: object = None) -> Image.Image:
    """Детерминированное зерно: одинаковый seed даёт одинаковый результат."""
    w, h = img.size
    rng = random.Random(_seed_int(seed, w, h))
    noise = Image.frombytes("L", (w, h), rng.randbytes(w * h)).convert("RGB")
    return Image.blend(img, noise, amount)


def _sepia(img: Image.Image) -> Image.Image:
    gray = ImageOps.grayscale(img)
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
    if turns == 1:
        out = out.transpose(Image.Transpose.ROTATE_270)
    elif turns == 2:
        out = out.transpose(Image.Transpose.ROTATE_180)
    elif turns == 3:
        out = out.transpose(Image.Transpose.ROTATE_90)
    return out


def apply_photo_adjustments(img: Image.Image,
                            brightness: float = 1.0,
                            contrast: float = 1.0,
                            saturation: float = 1.0,
                            sharpness: float = 1.0) -> Image.Image:
    """Нейтральные по умолчанию коррекции яркости/контраста/цвета/резкости."""
    out = img
    if brightness != 1.0:
        out = ImageEnhance.Brightness(out).enhance(float(brightness))
    if contrast != 1.0:
        out = ImageEnhance.Contrast(out).enhance(float(contrast))
    if saturation != 1.0:
        out = ImageEnhance.Color(out).enhance(float(saturation))
    if sharpness != 1.0:
        out = ImageEnhance.Sharpness(out).enhance(float(sharpness))
    return out


def apply_filter(img: Image.Image, name: str, *,
                 seed: object = None,
                 intensity: float = 1.0) -> Image.Image:
    """Применить фильтр по ключу с повторяемым зерном и силой 0..1."""
    if name == "none" or name not in FILTERS:
        return img
    strength = max(0.0, min(1.0, float(intensity)))
    if strength <= 0.0:
        return img

    if name == "bw":
        filtered = ImageOps.grayscale(img).convert("RGB")
        filtered = ImageEnhance.Contrast(filtered).enhance(1.08)
        filtered = _vignette(_grain(filtered, 0.04, seed), 0.35)
    elif name == "sepia":
        filtered = _vignette(_grain(_sepia(img), 0.03, seed), 0.35)
    elif name == "warm":
        filtered = _tint(img, 1.10, 1.02, 0.86)
        filtered = ImageEnhance.Color(filtered).enhance(1.12)
        filtered = ImageEnhance.Brightness(filtered).enhance(1.03)
    elif name == "cold":
        filtered = _tint(img, 0.90, 1.00, 1.12)
        filtered = ImageEnhance.Color(filtered).enhance(1.05)
    elif name == "faded":
        filtered = ImageEnhance.Color(img).enhance(0.72)
        filtered = ImageEnhance.Contrast(filtered).enhance(0.85)
        filtered = _tint(filtered, 1.04, 0.98, 1.06)
        filtered = _grain(_fade(filtered, lift=28, compress=22), 0.04, seed)
    elif name == "vintage":
        filtered = ImageEnhance.Color(img).enhance(0.82)
        filtered = _tint(filtered, 1.08, 0.98, 0.82)
        filtered = ImageEnhance.Contrast(filtered).enhance(0.95)
        filtered = _fade(filtered, lift=16, compress=12)
        filtered = _vignette(filtered, 0.5)
        filtered = _grain(filtered, 0.05, seed)
    else:  # pragma: no cover - защитный fallback
        return img

    if strength >= 0.999:
        return filtered
    return Image.blend(img, filtered, strength)
