"""Загрузка фотографий практически любого растрового формата.

Основной декодер — Pillow: формат определяется по содержимому файла, а не
только по расширению. Поэтому открываются и JFIF, и JPEG с нестандартным
или отсутствующим расширением. Отдельно подключается ``pillow-heif`` для
HEIC/HEIF; AVIF и JPEG 2000 поддерживаются современными сборками Pillow.
"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

_PLUGINS_REGISTERED = False

# Форматы Pillow, которые имеет смысл показывать в диалоге выбора фото.
_RASTER_FORMATS = {
    "AVIF", "BLP", "BMP", "CUR", "DCX", "DDS", "FITS", "FLI", "GBR",
    "GIF", "HEIF", "ICNS", "ICO", "JPEG", "JPEG2000", "JXL", "MPO",
    "PCD", "PCX", "PIXAR", "PNG", "PPM", "PSD", "QOI", "SGI", "SUN",
    "TGA", "TIFF", "WEBP", "XBM", "XPM",
}

# Алиасы и расширения, которые Pillow может не зарегистрировать отдельным
# расширением, хотя содержимое декодирует тем же кодеком.
_MANUAL_EXTENSIONS = {
    ".apng", ".avifs", ".hif", ".jfif", ".jpe", ".pjp", ".pjpeg",
}

# Сначала самые частые форматы — так фильтр выглядит предсказуемо.
_PREFERRED_ORDER = (
    ".jpg", ".jpeg", ".jfif", ".png", ".heic", ".heics", ".heif",
    ".heifs", ".avif", ".webp", ".gif", ".bmp", ".tif", ".tiff",
)


def register_image_plugins() -> None:
    """Подключить встроенные кодеки Pillow и необязательные плагины."""
    global _PLUGINS_REGISTERED
    if _PLUGINS_REGISTERED:
        return
    _PLUGINS_REGISTERED = True

    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except Exception:  # noqa: BLE001 - без плагина просто нет HEIC
        pass

    # JPEG XL не входит в обязательные зависимости, но если плагин есть
    # в окружении, используем и его.
    try:
        import pillow_jxl  # noqa: F401
    except Exception:  # noqa: BLE001
        pass

    Image.init()


def supported_image_extensions() -> tuple[str, ...]:
    """Расширения изображений, доступные установленным кодекам."""
    register_image_plugins()
    registered = Image.registered_extensions()
    extensions = {
        ext.lower()
        for ext, fmt in registered.items()
        if fmt in _RASTER_FORMATS
    }
    extensions.update(_MANUAL_EXTENSIONS)
    ordered = [ext for ext in _PREFERRED_ORDER if ext in extensions]
    ordered.extend(sorted(extensions.difference(ordered)))
    return tuple(ordered)


def image_file_filter() -> str:
    """Фильтр QFileDialog для всех поддерживаемых изображений."""
    patterns = " ".join(f"*{ext}" for ext in supported_image_extensions())
    return f"Изображения и фотографии ({patterns});;Все файлы (*)"


def _unsupported_error(path: str | os.PathLike) -> UnidentifiedImageError:
    return UnidentifiedImageError(
        "Файл повреждён или его формат не поддерживается: "
        f"{os.path.basename(os.fspath(path))}")


def identify_image_format(path: str | os.PathLike) -> str | None:
    """Определить формат по содержимому, не декодируя все пиксели."""
    register_image_plugins()
    try:
        with Image.open(path) as img:
            return img.format
    except Exception:  # noqa: BLE001
        return None


def is_supported_image_file(path: str | os.PathLike) -> bool:
    """True для известных расширений и файлов с распознаваемым содержимым."""
    candidate = Path(path)
    if not candidate.is_file():
        return False
    if candidate.suffix.lower() in supported_image_extensions():
        return True
    return identify_image_format(candidate) is not None


def _seek_first_frame(img: Image.Image) -> None:
    try:
        if getattr(img, "is_animated", False):
            img.seek(0)
    except (EOFError, OSError, ValueError):
        pass


def _to_rgb(img: Image.Image) -> Image.Image:
    has_alpha = img.mode in {"RGBA", "LA", "PA"} or (
        img.mode == "P" and "transparency" in img.info)
    if has_alpha:
        rgba = img.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        background.alpha_composite(rgba)
        return background.convert("RGB")
    if img.mode != "RGB":
        return img.convert("RGB")
    return img.copy()


def load_photo(path: str | os.PathLike) -> Image.Image:
    """Загрузить первый кадр изображения как полностью готовую RGB-копию.

    Учитывается EXIF-ориентация. Прозрачность накладывается на белый фон,
    что соответствует белой карточке полароида. Исходный файл сразу
    закрывается — это важно для Windows.
    """
    register_image_plugins()
    try:
        with Image.open(path) as src:
            _seek_first_frame(src)
            transposed = ImageOps.exif_transpose(src)
            return _to_rgb(transposed).copy()
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        raise
    except UnidentifiedImageError:
        raise
    except Exception as exc:  # noqa: BLE001 - плагины бросают разные ошибки
        raise _unsupported_error(path) from exc


def probe_image_size(path: str | os.PathLike) -> tuple[int, int]:
    """Размер первого кадра с учётом EXIF-ориентации."""
    register_image_plugins()
    try:
        with Image.open(path) as src:
            _seek_first_frame(src)
            return ImageOps.exif_transpose(src).size
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        raise
    except UnidentifiedImageError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _unsupported_error(path) from exc


register_image_plugins()
