"""Генерация иконки приложения: python tools/make_icon.py

Рисует наклонённую полароидную карточку с «закатом» и сохраняет
assets/icon.png (512x512) и assets/icon.ico (набор размеров для Windows).
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "assets")


def make_icon() -> Image.Image:
    size = 1024
    card_w, card_h = 620, 754
    card = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle([4, 4, card_w - 5, card_h - 5], radius=26,
                        fill=(252, 252, 250, 255), outline=(190, 190, 195, 255), width=4)

    # Фото: градиентный закат + солнце + горы
    inset = 34
    side = card_w - inset * 2
    photo = Image.new("RGBA", (side, side), (0, 0, 0, 255))
    pd = ImageDraw.Draw(photo)
    top, mid, bot = (61, 90, 180), (238, 130, 90), (250, 190, 110)
    for y in range(side):
        t = y / side
        if t < 0.55:
            k = t / 0.55
            c = tuple(int(top[i] + (mid[i] - top[i]) * k) for i in range(3))
        else:
            k = (t - 0.55) / 0.45
            c = tuple(int(mid[i] + (bot[i] - mid[i]) * k) for i in range(3))
        pd.line([(0, y), (side, y)], fill=c + (255,))
    r = 78
    cx, cy = int(side * 0.66), int(side * 0.40)
    pd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 236, 170, 255))
    pd.polygon([(0, side), (int(side * 0.42), int(side * 0.58)), (int(side * 0.72), side)],
               fill=(70, 60, 95, 255))
    pd.polygon([(int(side * 0.45), side), (int(side * 0.78), int(side * 0.66)), (side, side)],
               fill=(50, 42, 75, 255))
    card.paste(photo, (inset, inset))
    d.rectangle([inset, inset, inset + side - 1, inset + side - 1],
                outline=(0, 0, 0, 40), width=3)

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    rotated = card.rotate(9, resample=Image.BICUBIC, expand=True)
    canvas.paste(rotated, ((size - rotated.width) // 2, (size - rotated.height) // 2), rotated)
    return canvas


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    icon = make_icon()
    icon.resize((512, 512), Image.LANCZOS).save(os.path.join(OUT_DIR, "icon.png"))
    icon.save(os.path.join(OUT_DIR, "icon.ico"),
              sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("OK:", os.path.join(OUT_DIR, "icon.png"), os.path.join(OUT_DIR, "icon.ico"))


if __name__ == "__main__":
    main()
