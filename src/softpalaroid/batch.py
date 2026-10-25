"""Пакетная сборка фотографий в несколько готовых листов."""
from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .image_io import probe_image_size
from .model import PAPER_SIZES, Project
from .render import save_sheet
from .templates import apply_design_template

ProgressCallback = Callable[[int, int, str], bool | None]

_FORMAT_EXTENSIONS = {
    "jpg": ".jpg",
    "jpeg": ".jpg",
    "png": ".png",
    "pdf": ".pdf",
}


@dataclass
class BatchOptions:
    cards_per_sheet: int = 4
    landscape: bool = True
    paper_size: str = "10x15"
    sheet_width_cm: float = 15.0
    sheet_height_cm: float = 10.0
    card_format: str = "classic"
    template: str = "classic"
    output_format: str = "jpg"
    captions_from_filename: bool = False
    prefix: str = "softpalaroid"
    safe_margin_mm: float = 5.0

    def normalized_format(self) -> str:
        fmt = str(self.output_format or "jpg").lower().lstrip(".")
        return fmt if fmt in _FORMAT_EXTENSIONS else "jpg"


@dataclass
class BatchResult:
    output_files: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    photo_count: int = 0

    @property
    def sheet_count(self) -> int:
        return len(self.output_files)


def _chunks(values: Sequence[Path], size: int) -> Iterable[Sequence[Path]]:
    step = max(1, int(size))
    for start in range(0, len(values), step):
        yield values[start:start + step]


def _caption_from_path(path: Path) -> str:
    text = re.sub(r"[_-]+", " ", path.stem).strip()
    return text[:80]


def _safe_prefix(value: str) -> str:
    cleaned = re.sub(r"[^\w\- ]+", "", str(value or ""), flags=re.UNICODE)
    cleaned = cleaned.strip().replace(" ", "-")
    return cleaned[:48] or "softpalaroid"


def build_batch_project(photo_paths: Sequence[Path],
                        options: BatchOptions,
                        photo_sizes: dict[Path, tuple[int, int]],
                        ) -> Project:
    """Собрать один лист пакетного задания из уже проверенных фото."""
    project = Project()
    if options.paper_size in PAPER_SIZES:
        project.set_paper_size(options.paper_size, landscape=options.landscape)
    else:
        project.set_sheet_dimensions(
            options.sheet_width_cm, options.sheet_height_cm,
            paper_size="custom")
        if project.landscape != options.landscape:
            project.set_layout(1, landscape=options.landscape)
    project.card_format = options.card_format
    project.safe_margin_mm = options.safe_margin_mm
    project.set_layout(max(1, len(photo_paths)), landscape=options.landscape)
    project.set_card_format(options.card_format)
    for item, path in zip(project.items, photo_paths):
        item.set_photo(str(path), photo_sizes[path])
        if options.captions_from_filename:
            item.caption = _caption_from_path(path)
    apply_design_template(project, options.template)
    project.safe_margin_mm = options.safe_margin_mm
    project.clamp_settings()
    return project


def export_batch(photo_paths: Sequence[str | os.PathLike],
                 output_dir: str | os.PathLike,
                 options: BatchOptions | None = None,
                 progress: ProgressCallback | None = None) -> BatchResult:
    """Разложить фотографии по листам и сохранить JPG/PNG/PDF.

    Нечитаемые файлы не прерывают всё задание: они собираются в
    ``BatchResult.errors``, а остальные фотографии обрабатываются.
    """
    opts = options or BatchOptions()
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    result = BatchResult()

    valid: list[Path] = []
    sizes: dict[Path, tuple[int, int]] = {}
    for raw_path in photo_paths:
        path = Path(raw_path)
        try:
            sizes[path] = probe_image_size(path)
            valid.append(path)
        except Exception as exc:  # noqa: BLE001 - пакет должен продолжить работу
            result.errors.append(f"{path.name}: {exc}")
    result.photo_count = len(valid)
    if not valid:
        return result

    groups = list(_chunks(valid, opts.cards_per_sheet))
    extension = _FORMAT_EXTENSIONS[opts.normalized_format()]
    prefix = _safe_prefix(opts.prefix)
    total = len(groups)

    for number, group in enumerate(groups, start=1):
        if progress is not None:
            keep_going = progress(
                number - 1, total,
                f"Собирается лист {number} из {total}…")
            if keep_going is False:
                result.errors.append("Пакетная обработка отменена пользователем")
                break
        project = build_batch_project(group, opts, sizes)
        output = destination / f"{prefix}-{number:03d}{extension}"
        try:
            save_sheet(project, str(output))
            result.output_files.append(output)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"Лист {number}: {exc}")
        if progress is not None:
            keep_going = progress(
                number, total, f"Готов лист {number} из {total}")
            if keep_going is False:
                result.errors.append("Пакетная обработка отменена пользователем")
                break
    return result
