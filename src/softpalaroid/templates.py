"""Дизайн-шаблоны оформления листа и карточек."""
from __future__ import annotations

from dataclasses import dataclass

from .model import Project


@dataclass(frozen=True)
class DesignTemplate:
    key: str
    name: str
    background_color: str
    frame_colors: tuple[str, ...]
    filter: str = "none"
    filter_intensity: float = 1.0
    brightness: float = 1.0
    contrast: float = 1.0
    saturation: float = 1.0
    sharpness: float = 1.0
    cut_marks: bool = True


DESIGN_TEMPLATES: dict[str, DesignTemplate] = {
    "classic": DesignTemplate(
        key="classic",
        name="Классика",
        background_color="#ffffff",
        frame_colors=("#fcfcfa",),
        filter="none",
    ),
    "warm_film": DesignTemplate(
        key="warm_film",
        name="Тёплая плёнка",
        background_color="#f6efe5",
        frame_colors=("#fff2cf", "#fcfcfa"),
        filter="vintage",
        saturation=1.03,
    ),
    "mono_night": DesignTemplate(
        key="mono_night",
        name="Монохромная ночь",
        background_color="#111418",
        frame_colors=("#263238", "#fcfcfa"),
        filter="bw",
        contrast=1.05,
    ),
    "pastel": DesignTemplate(
        key="pastel",
        name="Пастельный альбом",
        background_color="#fff6f9",
        frame_colors=("#ffe1e8", "#dff3ff", "#e6f4e3", "#fff2cf"),
        filter="faded",
        brightness=1.03,
        saturation=0.94,
    ),
    "bright_album": DesignTemplate(
        key="bright_album",
        name="Яркий альбом",
        background_color="#dceeff",
        frame_colors=("#ffffff", "#ffe1e8", "#dff3ff", "#fff2cf"),
        filter="warm",
        saturation=1.12,
        sharpness=1.08,
    ),
}


def get_design_template(key: object) -> DesignTemplate:
    if isinstance(key, str) and key in DESIGN_TEMPLATES:
        return DESIGN_TEMPLATES[key]
    return DESIGN_TEMPLATES["classic"]


def apply_design_template(project: Project, key: str, *,
                          apply_filter: bool = True) -> DesignTemplate:
    """Применить оформление ко всему проекту, сохранив фото и геометрию."""
    template = get_design_template(key)
    project.template = template.key
    project.background_color = template.background_color
    project.cut_marks = template.cut_marks
    project.clamp_settings()
    for index, item in enumerate(project.items):
        item.frame_color = template.frame_colors[
            index % len(template.frame_colors)]
        item.caption_color = None
        if apply_filter:
            item.filter = template.filter
            item.filter_intensity = template.filter_intensity
            item.brightness = template.brightness
            item.contrast = template.contrast
            item.saturation = template.saturation
            item.sharpness = template.sharpness
        item.clamp()
    return template
