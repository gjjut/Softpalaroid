"""Загрузка фотографий практически любого растрового и RAW-формата.

Основной декодер — Pillow: формат определяется по содержимому файла, а не
только по расширению. Отдельно подключаются ``pillow-heif`` для HEIC/HEIF
и ``rawpy``/LibRaw для камерных RAW. Встроенный ICC-профиль преобразуется
в sRGB — рабочее пространство предпросмотра, экспорта и печати.
"""
from __future__ import annotations

import os
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

_PLUGINS_REGISTERED = False

_RASTER_FORMATS = {
    "AVIF", "BLP", "BMP", "CUR", "DCX", "DDS", "FITS", "FLI", "GBR",
    "GIF", "HEIF", "ICNS", "ICO", "JPEG", "JPEG2000", "JXL", "MPO",
    "PCD", "PCX", "PIXAR", "PNG", "PPM", "PSD", "QOI", "SGI", "SUN",
    "TGA", "TIFF", "WEBP", "XBM", "XPM",
}

_MANUAL_EXTENSIONS = {
    ".apng", ".avifs", ".hif", ".jfif", ".jpe", ".pjp", ".pjpeg",
}

RAW_EXTENSIONS = {
    ".3fr", ".arw", ".bay", ".cr2", ".cr3", ".crw", ".dcs", ".dng",
    ".drf", ".eip", ".erf", ".fff", ".ii", ".k25", ".kdc", ".mdc",
    ".mef", ".mos", ".mrw", ".nef", ".nrw", ".orf", ".pef", ".pxn",
    ".r3d", ".raf", ".raw", ".rw2", ".rwl", ".sr2", ".srf", ".x3f",
}

_PREFERRED_ORDER = (
    ".jpg", ".jpeg", ".jfif", ".png", ".heic", ".heics", ".heif",
    ".heifs", ".avif", ".webp", ".gif", ".bmp", ".tif", ".tiff",
    ".dng", ".cr2", ".cr3", ".nef", ".arw", ".raf", ".rw2", ".orf",
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

    try:
        import pillow_jxl  # noqa: F401
    except Exception:  # noqa: BLE001
        pass

    Image.init()


def _get_rawpy():
    try:
        import rawpy

        return rawpy
    except Exception:  # noqa: BLE001
        return None


def rawpy_available() -> bool:
    return _get_rawpy() is not None


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
    if rawpy_available():
        extensions.update(RAW_EXTENSIONS)
    ordered = [ext for ext in _PREFERRED_ORDER if ext in extensions]
    ordered.extend(sorted(extensions.difference(ordered)))
    return tuple(ordered)


def image_file_filter() -> str:
    """Фильтр QFileDialog для всех поддерживаемых изображений."""
    patterns = " ".join(f"*{ext}" for ext in supported_image_extensions())
    return f"Изображения, RAW и фотографии ({patterns});;Все файлы (*)"


def _unsupported_error(path: str | os.PathLike) -> UnidentifiedImageError:
    return UnidentifiedImageError(
        "Файл повреждён или его формат не поддерживается: "
        f"{os.path.basename(os.fspath(path))}")


@lru_cache(maxsize=1)
def srgb_icc_profile() -> bytes | None:
    """ICC-профиль sRGB для встраивания в экспорт."""
    try:
        # createProfile возвращает core-объект; байты ICC умеет отдавать
        # высокоуровневая обёртка ImageCmsProfile.
        return ImageCms.ImageCmsProfile(
            ImageCms.createProfile("sRGB")).tobytes()
    except Exception:  # noqa: BLE001
        return None


def _seek_first_frame(img: Image.Image) -> None:
    try:
        if getattr(img, "is_animated", False):
            img.seek(0)
    except (EOFError, OSError, ValueError):
        pass


def _has_alpha(img: Image.Image) -> bool:
    return img.mode in {"RGBA", "LA", "PA"} or (
        img.mode == "P" and "transparency" in img.info)


def _to_rgb(img: Image.Image) -> Image.Image:
    if _has_alpha(img):
        rgba = img.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        background.alpha_composite(rgba)
        return background.convert("RGB")
    if img.mode != "RGB":
        return img.convert("RGB")
    return img.copy()


def _convert_to_srgb(img: Image.Image,
                     icc_profile: bytes | bytearray | None) -> Image.Image:
    """Преобразовать картинку с встроенным ICC в sRGB, сохранив прозрачность."""
    if not icc_profile:
        return _to_rgb(img)
    try:
        incoming = ImageCms.ImageCmsProfile(BytesIO(bytes(icc_profile)))
        outgoing = ImageCms.createProfile("sRGB")
        if _has_alpha(img):
            rgba = img.convert("RGBA")
            alpha = rgba.getchannel("A")
            converted = ImageCms.profileToProfile(
                rgba.convert("RGB"), incoming, outgoing, outputMode="RGB")
            if converted is not None:
                converted.putalpha(alpha)
                result = _to_rgb(converted)
                return result
        else:
            source = img if img.mode in {"RGB", "RGBA", "CMYK", "L", "LAB"} \
                else img.convert("RGB")
            converted = ImageCms.profileToProfile(
                source, incoming, outgoing, outputMode="RGB")
            if converted is not None:
                result = _to_rgb(converted)
                return result
    except Exception:  # noqa: BLE001 - битый профиль не должен ломать загрузку
        pass
    return _to_rgb(img)


def _load_raw_photo(path: str | os.PathLike) -> Image.Image:
    rawpy = _get_rawpy()
    if rawpy is None:
        raise ImportError("rawpy is not available")
    import numpy as np

    with rawpy.imread(os.fspath(path)) as raw:
        rgb = raw.postprocess(
            use_camera_wb=True,
            output_bps=8,
            output_color=rawpy.ColorSpace.sRGB,
            demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,
        )
    array = np.ascontiguousarray(rgb, dtype=np.uint8)
    if array.ndim != 3 or array.shape[2] < 3:
        raise UnidentifiedImageError("RAW decoder returned an invalid image")
    if array.shape[2] > 3:
        array = np.ascontiguousarray(array[:, :, :3])
    return Image.fromarray(array, mode="RGB").copy()


def _probe_raw_size(path: str | os.PathLike) -> tuple[int, int]:
    rawpy = _get_rawpy()
    if rawpy is None:
        raise ImportError("rawpy is not available")
    with rawpy.imread(os.fspath(path)) as raw:
        sizes = raw.sizes
        iwidth = int(getattr(sizes, "iwidth", 0) or 0)
        iheight = int(getattr(sizes, "iheight", 0) or 0)
        if iwidth > 0 and iheight > 0:
            return (iwidth, iheight)
        width = int(getattr(sizes, "width", 0) or 0)
        height = int(getattr(sizes, "height", 0) or 0)
        flip = int(getattr(sizes, "flip", 0) or 0)
        if flip in {5, 6}:
            width, height = height, width
        if width <= 0 or height <= 0:
            raise UnidentifiedImageError("RAW image size is unavailable")
        return (width, height)


def _is_raw_path(path: str | os.PathLike) -> bool:
    return Path(path).suffix.lower() in RAW_EXTENSIONS


def identify_image_format(path: str | os.PathLike) -> str | None:
    """Определить формат по содержимому, не декодируя все пиксели."""
    register_image_plugins()
    if _is_raw_path(path) and rawpy_available():
        try:
            _probe_raw_size(path)
            return "RAW"
        except Exception:  # noqa: BLE001
            pass
    try:
        with Image.open(path) as img:
            if img.format:
                return img.format
    except Exception:  # noqa: BLE001
        pass
    if rawpy_available():
        try:
            _probe_raw_size(path)
            return "RAW"
        except Exception:  # noqa: BLE001
            pass
    return None


def is_supported_image_file(path: str | os.PathLike) -> bool:
    candidate = Path(path)
    if not candidate.is_file():
        return False
    if candidate.suffix.lower() in supported_image_extensions():
        return True
    return identify_image_format(candidate) is not None


def _load_with_pillow(path: str | os.PathLike) -> Image.Image:
    with Image.open(path) as src:
        _seek_first_frame(src)
        profile = src.info.get("icc_profile")
        transposed = ImageOps.exif_transpose(src)
        return _convert_to_srgb(transposed, profile).copy()


def load_photo(path: str | os.PathLike) -> Image.Image:
    """Загрузить первый кадр/RAW как полностью готовую sRGB-копию."""
    register_image_plugins()
    if _is_raw_path(path) and rawpy_available():
        try:
            return _load_raw_photo(path)
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            raise
        except Exception:  # noqa: BLE001 - DNG/ошибочное расширение пробуем Pillow
            pass
    try:
        return _load_with_pillow(path)
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        raise
    except Exception as exc:  # noqa: BLE001
        if rawpy_available():
            try:
                return _load_raw_photo(path)
            except (FileNotFoundError, IsADirectoryError, PermissionError):
                raise
            except Exception:  # noqa: BLE001
                pass
        if isinstance(exc, UnidentifiedImageError):
            raise
        raise _unsupported_error(path) from exc


def probe_image_size(path: str | os.PathLike) -> tuple[int, int]:
    """Размер первого кадра/RAW с учётом ориентации."""
    register_image_plugins()
    if _is_raw_path(path) and rawpy_available():
        try:
            return _probe_raw_size(path)
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            raise
        except Exception:  # noqa: BLE001
            pass
    try:
        with Image.open(path) as src:
            _seek_first_frame(src)
            return ImageOps.exif_transpose(src).size
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        raise
    except Exception as exc:  # noqa: BLE001
        if rawpy_available():
            try:
                return _probe_raw_size(path)
            except (FileNotFoundError, IsADirectoryError, PermissionError):
                raise
            except Exception:  # noqa: BLE001
                pass
        if isinstance(exc, UnidentifiedImageError):
            raise
        raise _unsupported_error(path) from exc


register_image_plugins()
