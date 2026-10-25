"""Рендер готового листа в полном разрешении 300 DPI (Pillow).

Используется для сохранения JPG/PNG/PDF и печати, поэтому предпросмотр,
экспорт и печатная страница строятся из одной и той же геометрии модели.
"""
from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw, ImageFont

from .filters import apply_filter, apply_photo_adjustments, transform_photo
from .image_io import load_photo, srgb_icc_profile
from .model import (
    BACKGROUND_DOT_RADIUS_PX,
    BACKGROUND_DOT_SPACING_PX,
    BACKGROUND_GRID_SPACING_PX,
    BACKGROUND_GRID_WIDTH_PX,
    CUT_MARK_WIDTH_PX,
    DPI,
    PolaroidItem,
    Project,
    color_to_rgb,
    cut_mark_rgb,
)
from .resources import asset_path

FRAME_COLOR = color_to_rgb("#fcfcfa")
CAPTION_COLOR = (52, 52, 58)
PLACEHOLDER_COLOR = (225, 225, 228)
SS = 2  # supersampling карточки для гладких краёв после поворота


def _font_candidates() -> list[str]:
    """Пути шрифтов подписи по приоритету: сначала встроенный Caveat."""
    names: list[str] = []
    bundled = asset_path("fonts", "Caveat.ttf")
    if bundled:
        names.append(bundled)
    if sys.platform == "win32":
        fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        names += [
            os.path.join(fonts_dir, n)
            for n in ("segoesc.ttf", "SegoePrint.ttf", "comic.ttf",
                      "Gabriola.ttf", "Inkfree.ttf")
        ]
    elif sys.platform == "darwin":
        names += [
            "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",
            "/System/Library/Fonts/Supplemental/ChalkboardSE.ttc",
        ]
    else:
        names += [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        ]
    return [p for p in names if os.path.exists(p)]


def _caption_font(size_px: int) -> ImageFont.ImageFont:
    for path in _font_candidates():
        try:
            font = ImageFont.truetype(path, size_px)
            if path.endswith("Caveat.ttf"):
                # Caveat вариативный (ось Weight 400..700): 600 лучше читается.
                try:
                    font.set_variation_by_axes([600])
                except Exception:  # noqa: BLE001 - останется Regular
                    pass
            return font
        except OSError:
            continue
    return ImageFont.load_default(size_px)


def _fit_caption(draw: ImageDraw.ImageDraw, text: str, max_w: float,
                 base_size: int, max_h: float | None = None,
                 align: str = "center") -> ImageFont.ImageFont:
    """Подобрать размер шрифта для одно- или многострочной подписи."""
    size = max(10, int(base_size))
    while size > 10:
        font = _caption_font(size)
        bbox = draw.multiline_textbbox((0, 0), text, font=font, align=align)
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        if width <= max_w and (max_h is None or height <= max_h):
            return font
        size = max(10, int(size * 0.9))
    return _caption_font(max(10, size))


def render_card(item: PolaroidItem, photo: Image.Image | None) -> Image.Image:
    """Одна карточка без наклона и тени, RGBA с supersampling x2."""
    w = max(1, int(round(item.width)) * SS)
    h = max(1, int(round(item.height)) * SS)
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)

    radius = int(w * 0.018)
    draw.rounded_rectangle(
        [0, 0, w - 1, h - 1],
        radius=radius,
        fill=item.frame_rgb + (255,),
        outline=item.contrast_rgb + (42,),
        width=max(1, SS),
    )

    px_f, py_f, pw_f, ph_f = item.photo_rect_local()
    x0, y0 = int(round(px_f * SS)), int(round(py_f * SS))
    pw, ph = max(1, int(round(pw_f * SS))), max(1, int(round(ph_f * SS)))
    # Не даём округлению увести окно фотографии за пределы карточки.
    pw = min(pw, max(1, w - x0))
    ph = min(ph, max(1, h - y0))

    if photo is not None:
        oriented = transform_photo(
            photo,
            rotation=item.photo_rotation,
            flip_horizontal=item.flip_horizontal,
            flip_vertical=item.flip_vertical,
        )
        iw, ih = oriented.size
        if iw > 0 and ih > 0:
            scale = max(pw / iw, ph / ih) * item.zoom
            dw, dh = max(pw, round(iw * scale)), max(ph, round(ih * scale))
            resized = oriented.resize((dw, dh), Image.LANCZOS)
            resized = apply_photo_adjustments(
                resized,
                brightness=item.brightness,
                contrast=item.contrast,
                saturation=item.saturation,
                sharpness=item.sharpness,
            )
            resized = apply_filter(
                resized,
                item.filter,
                seed=item.effective_grain_seed(),
                intensity=item.filter_intensity,
            )
            cx = int(round(item.offset_x * max(0, dw - pw)))
            cy = int(round(item.offset_y * max(0, dh - ph)))
            cx = max(0, min(max(0, dw - pw), cx))
            cy = max(0, min(max(0, dh - ph), cy))
            crop = resized.crop((cx, cy, cx + pw, cy + ph))
            card.paste(crop, (x0, y0))
        else:
            draw.rectangle(
                [x0, y0, x0 + pw - 1, y0 + ph - 1],
                fill=PLACEHOLDER_COLOR + (255,))
    else:
        draw.rectangle(
            [x0, y0, x0 + pw - 1, y0 + ph - 1],
            fill=PLACEHOLDER_COLOR + (255,))

    draw.rectangle(
        [x0, y0, x0 + pw - 1, y0 + ph - 1],
        outline=item.contrast_rgb + (46,),
        width=max(1, SS),
    )

    caption = item.caption.strip("\r\n")
    if caption.strip():
        caption_top = y0 + ph
        area_h = max(1, h - caption_top)
        lines = max(1, len(caption.splitlines()))
        divisor = 1.0 + 0.24 * (lines - 1)
        base_size = int(area_h * 0.52 * item.caption_scale / divisor)
        align = item.caption_align if item.caption_align in {
            "left", "center", "right"} else "center"
        font = _fit_caption(
            draw, caption, w * 0.86, base_size,
            max_h=area_h * 0.88, align=align)
        center_y = caption_top + area_h / 2
        if align == "left":
            position = (w * 0.08, center_y)
            anchor = "lm"
        elif align == "right":
            position = (w * 0.92, center_y)
            anchor = "rm"
        else:
            position = (w / 2, center_y)
            anchor = "mm"
        draw.multiline_text(
            position,
            caption,
            font=font,
            fill=item.caption_rgb + (255,),
            anchor=anchor,
            align=align,
            spacing=max(2, int(area_h * 0.04)),
        )
    return card


def draw_cut_marks(sheet: Image.Image, project: Project,
                   background: tuple[int, int, int] | None = None) -> None:
    """Нарисовать L-образные уголки обреза вокруг каждой карточки."""
    bg = project.background_rgb if background is None else background
    mark_color = cut_mark_rgb("#%02x%02x%02x" % bg)
    draw = ImageDraw.Draw(sheet)
    width = max(1, int(round(CUT_MARK_WIDTH_PX)))
    for item in project.items:
        for start, end in item.cut_mark_segments():
            draw.line([start, end], fill=mark_color, width=width)


def _load_photo_safely(item: PolaroidItem) -> Image.Image | None:
    if not item.photo_path:
        return None
    try:
        return load_photo(item.photo_path)
    except Exception:  # noqa: BLE001 - preflight уже предупреждает пользователя
        return None


def _finished_card(item: PolaroidItem,
                   photo: Image.Image | None) -> Image.Image:
    card = render_card(item, photo)
    rotated = card.rotate(-item.rotation, resample=Image.BICUBIC, expand=True)
    if SS != 1:
        rotated = rotated.resize(
            (max(1, rotated.width // SS), max(1, rotated.height // SS)),
            Image.LANCZOS)
    return rotated


def make_background(project: Project,
                    background: tuple[int, int, int] | None = None) -> Image.Image:
    """Фон листа по стилю проекта: однотонный, градиент, точки или сетка.

    Явный ``background`` (например, белый для печати) всегда даёт однотонную
    заливку и игнорирует стиль.
    """
    width, height = project.sheet_w, project.sheet_h
    color1 = project.background_rgb if background is None else background
    sheet = Image.new("RGB", (width, height), color1)
    style = project.background_style if background is None else "solid"
    if style == "solid":
        return sheet
    color2 = project.background_rgb2
    draw = ImageDraw.Draw(sheet)
    if style == "gradient":
        for y in range(height):
            t = y / max(1, height - 1)
            draw.line(
                [(0, y), (width, y)],
                fill=tuple(int(round(a + (b - a) * t))
                           for a, b in zip(color1, color2)))
    elif style == "dots":
        spacing = BACKGROUND_DOT_SPACING_PX
        radius = BACKGROUND_DOT_RADIUS_PX
        row = 0
        y = spacing / 2.0
        while y < height + radius:
            x = spacing / 2.0 + (spacing / 2.0 if row % 2 else 0.0)
            while x < width + radius:
                draw.ellipse(
                    [x - radius, y - radius, x + radius, y + radius],
                    fill=color2)
                x += spacing
            y += spacing
            row += 1
    elif style == "grid":
        spacing = int(BACKGROUND_GRID_SPACING_PX)
        line_w = max(1, int(round(BACKGROUND_GRID_WIDTH_PX)))
        for x in range(0, width + 1, spacing):
            draw.line([(x, 0), (x, height)], fill=color2, width=line_w)
        for y in range(0, height + 1, spacing):
            draw.line([(0, y), (width, y)], fill=color2, width=line_w)
    return sheet


def render_sheet(project: Project,
                 background: tuple[int, int, int] | None = None) -> Image.Image:
    """Полный лист в экспортном разрешении, без теней карточек."""
    bg = project.background_rgb if background is None else background
    sheet = make_background(project, background)
    if project.cut_marks:
        draw_cut_marks(sheet, project, bg)
    for item in project.items:
        rotated = _finished_card(item, _load_photo_safely(item))
        px = int(round(item.center_x - rotated.width / 2))
        py = int(round(item.center_y - rotated.height / 2))
        sheet.paste(rotated, (px, py), rotated)
    return sheet


def render_card_export(item: PolaroidItem) -> Image.Image:
    """Одна повёрнутая карточка на прозрачном фоне для отдельного экспорта."""
    return _finished_card(item, _load_photo_safely(item))


def _icc_kwargs() -> dict[str, bytes]:
    profile = srgb_icc_profile()
    return {"icc_profile": profile} if profile else {}


def _save_image(img: Image.Image, path: str,
                background: tuple[int, int, int] = (255, 255, 255)) -> None:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        flat = img
        if flat.mode in ("RGBA", "LA", "PA"):
            base = Image.new("RGBA", flat.size, background + (255,))
            base.alpha_composite(flat.convert("RGBA"))
            flat = base.convert("RGB")
        elif flat.mode != "RGB":
            flat = flat.convert("RGB")
        flat.save(path, "JPEG", quality=95, subsampling=0,
                  dpi=(DPI, DPI), **_icc_kwargs())
    elif ext == ".pdf":
        flat = img
        if flat.mode in ("RGBA", "LA", "PA"):
            base = Image.new("RGBA", flat.size, background + (255,))
            base.alpha_composite(flat.convert("RGBA"))
            flat = base.convert("RGB")
        elif flat.mode != "RGB":
            flat = flat.convert("RGB")
        flat.save(path, "PDF", resolution=float(DPI), **_icc_kwargs())
    else:
        img.save(path, "PNG", dpi=(DPI, DPI), **_icc_kwargs())


def save_sheet(project: Project, path: str) -> None:
    _save_image(render_sheet(project), path, project.background_rgb)


def save_card(item: PolaroidItem, path: str,
              background: tuple[int, int, int] = (255, 255, 255)) -> None:
    _save_image(render_card_export(item), path, background)
