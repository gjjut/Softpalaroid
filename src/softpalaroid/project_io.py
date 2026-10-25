"""Сохранение и загрузка проектов Softpalaroid (.softpalaroid).

Файл проекта — ZIP-архив:
- ``manifest.json`` — ориентация листа и все параметры карточек;
- ``images/...`` — копии использованных фотографий.

Копии фото внутри архива делают проект переносимым: его можно отправить
другому человеку или открыть после перемещения исходных фотографий.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from PIL import Image, ImageOps

from . import __version__
from .model import PolaroidItem, Project

FORMAT_NAME = "softpalaroid-project"
FORMAT_VERSION = 1
PROJECT_EXTENSION = ".softpalaroid"
PROJECT_FILE_FILTER = "Проект Softpalaroid (*.softpalaroid);;Все файлы (*)"
MANIFEST_NAME = "manifest.json"

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


class ProjectFileError(ValueError):
    """Файл проекта повреждён, небезопасен или создан более новой версией."""


@dataclass
class LoadedProject:
    project: Project
    selected_index: int = 0
    warnings: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


def _item_state(item: PolaroidItem, photo_ref: str | None,
                *, use_photo_path: bool = False) -> dict:
    return {
        "center_x": float(item.center_x),
        "center_y": float(item.center_y),
        "width": float(item.width),
        "rotation": float(item.rotation),
        "photo": item.photo_path if use_photo_path else photo_ref,
        "photo_size": list(item.photo_size) if item.photo_size else None,
        "zoom": float(item.zoom),
        "offset_x": float(item.offset_x),
        "offset_y": float(item.offset_y),
        "caption": item.caption,
        "filter": item.filter,
    }


def project_state_dict(project: Project) -> dict:
    """JSON-совместимое состояние проекта для сравнения и истории изменений."""
    return {
        "landscape": bool(project.landscape),
        "items": [
            _item_state(item, item.photo_path, use_photo_path=True)
            for item in project.items
        ],
    }


def project_state_key(project: Project) -> str:
    """Стабильный ключ состояния: одинаковый проект -> одинаковый ключ."""
    return json.dumps(project_state_dict(project), ensure_ascii=False,
                      sort_keys=True, separators=(",", ":"))


def _absolute_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def save_project_file(project: Project, path: str | os.PathLike,
                      *, selected_index: int = 0,
                      metadata: dict | None = None) -> None:
    """Атомарно сохранить проект и копии его фотографий в ZIP-архив."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    # Каждое уникальное фото сохраняется в архив только один раз.
    image_refs: dict[str, str] = {}
    for item in project.items:
        if not item.photo_path:
            continue
        source = Path(item.photo_path)
        if not source.is_file():
            raise FileNotFoundError(f"Фотография не найдена: {item.photo_path}")
        key = _absolute_key(item.photo_path)
        if key not in image_refs:
            suffix = source.suffix.lower()
            if suffix not in _IMAGE_SUFFIXES:
                suffix = ".bin"
            image_refs[key] = f"images/img-{len(image_refs) + 1:03d}{suffix}"

    manifest = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "app_version": __version__,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "landscape": bool(project.landscape),
        "selected_index": int(selected_index),
        "items": [
            _item_state(
                item,
                image_refs.get(_absolute_key(item.photo_path))
                if item.photo_path else None,
            )
            for item in project.items
        ],
        "metadata": dict(metadata or {}),
    }

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                MANIFEST_NAME,
                json.dumps(manifest, ensure_ascii=False, indent=2),
                compress_type=zipfile.ZIP_DEFLATED,
            )
            written: set[str] = set()
            for item in project.items:
                if not item.photo_path:
                    continue
                key = _absolute_key(item.photo_path)
                internal_name = image_refs[key]
                if internal_name in written:
                    continue
                # JPEG/PNG уже сжаты: ZIP_STORED экономит время автосейва.
                zf.write(item.photo_path, internal_name,
                         compress_type=zipfile.ZIP_STORED)
                written.add(internal_name)
        os.replace(temp_path, destination)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as img:
        return ImageOps.exif_transpose(img).size


def _safe_internal_path(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise ProjectFileError("Некорректная ссылка на фотографию в проекте")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or path.parts[0] != "images" \
            or any(part in {"", ".", ".."} for part in path.parts):
        raise ProjectFileError(f"Небезопасный путь в архиве проекта: {value}")
    return path


def _float_value(data: dict, key: str, default: float) -> float:
    try:
        return float(data.get(key, default))
    except (TypeError, ValueError):
        return default


def load_project_file(path: str | os.PathLike,
                      extract_dir: str | os.PathLike) -> LoadedProject:
    """Загрузить проект, распаковав копии фотографий в extract_dir."""
    source = Path(path)
    target_root = Path(extract_dir).resolve()
    target_root.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(source, "r") as zf:
            names = set(zf.namelist())
            if MANIFEST_NAME not in names:
                raise ProjectFileError("В архиве проекта нет manifest.json")
            try:
                manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProjectFileError("Повреждён manifest.json проекта") from exc

            if not isinstance(manifest, dict) \
                    or manifest.get("format") != FORMAT_NAME:
                raise ProjectFileError("Это не файл проекта Softpalaroid")
            version = manifest.get("version", 0)
            if not isinstance(version, int) or version < 1:
                raise ProjectFileError("Некорректная версия формата проекта")
            if version > FORMAT_VERSION:
                raise ProjectFileError(
                    "Проект создан более новой версией Softpalaroid")

            raw_items = manifest.get("items")
            if not isinstance(raw_items, list):
                raise ProjectFileError("В проекте отсутствует список карточек")

            project = Project(landscape=bool(manifest.get("landscape", True)))
            warnings: list[str] = []

            for slot, raw in enumerate(raw_items, start=1):
                if not isinstance(raw, dict):
                    warnings.append(f"Слот {slot}: некорректные данные, пропущен")
                    continue

                item = PolaroidItem(
                    center_x=_float_value(raw, "center_x", 0.0),
                    center_y=_float_value(raw, "center_y", 0.0),
                    width=max(1.0, _float_value(raw, "width", 600.0)),
                    rotation=_float_value(raw, "rotation", 0.0),
                    zoom=_float_value(raw, "zoom", 1.0),
                    offset_x=_float_value(raw, "offset_x", 0.5),
                    offset_y=_float_value(raw, "offset_y", 0.5),
                    caption=str(raw.get("caption", "")),
                    filter=str(raw.get("filter", "none")),
                )

                photo_ref = raw.get("photo")
                if photo_ref:
                    internal = _safe_internal_path(photo_ref)
                    internal_name = internal.as_posix()
                    if internal_name not in names:
                        warnings.append(
                            f"Слот {slot}: фотография отсутствует в архиве")
                    else:
                        target = target_root.joinpath(*internal.parts).resolve()
                        if os.path.commonpath([str(target_root), str(target)]) \
                                != str(target_root):
                            raise ProjectFileError(
                                f"Небезопасный путь в архиве проекта: {photo_ref}")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(internal_name, "r") as src, \
                                target.open("wb") as dst:
                            shutil.copyfileobj(src, dst)
                        try:
                            item.photo_path = str(target)
                            item.photo_size = _image_size(target)
                        except Exception:  # noqa: BLE001 - битое фото не рушит проект
                            item.photo_path = None
                            item.photo_size = None
                            warnings.append(
                                f"Слот {slot}: фотографию не удалось прочитать")
                item.clamp()
                project.items.append(item)

            if not project.items:
                project.set_layout(1, landscape=project.landscape)
                warnings.append("Проект не содержал карточек, создан пустой слот")

            selected = manifest.get("selected_index", 0)
            if not isinstance(selected, int):
                selected = 0
            selected = max(0, min(len(project.items) - 1, selected))
            metadata = manifest.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            return LoadedProject(project, selected, warnings, metadata)
    except zipfile.BadZipFile as exc:
        raise ProjectFileError("Файл проекта повреждён или не является архивом") from exc
