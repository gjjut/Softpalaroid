"""Проверка макета перед экспортом и печатью.

Все замечания носят предупреждающий характер: пользователь может перейти к
проблемной карточке, исправить её или осознанно продолжить.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .model import Project

Point = tuple[float, float]
Polygon = list[Point]


@dataclass(frozen=True)
class PreflightIssue:
    severity: str  # "warning" или "info"
    code: str
    message: str
    item_index: int | None = None
    related_index: int | None = None

    @property
    def title(self) -> str:
        if self.item_index is None:
            return self.message
        return f"Слот {self.item_index + 1}: {self.message}"


def _signed_area(polygon: Polygon) -> float:
    total = 0.0
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
        total += x1 * y2 - x2 * y1
    return total / 2.0


def polygon_area(polygon: Polygon) -> float:
    return abs(_signed_area(polygon)) if len(polygon) >= 3 else 0.0


def _cross(a: Point, b: Point, p: Point) -> float:
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def _intersection(a: Point, b: Point, p: Point, q: Point) -> Point:
    """Пересечение отрезка p-q с прямой, проходящей через a-b."""
    d1 = _cross(a, b, p)
    d2 = _cross(a, b, q)
    if abs(d1 - d2) < 1e-12:
        return q
    t = d1 / (d1 - d2)
    return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)


def clip_polygon(subject: Polygon, clip: Polygon) -> Polygon:
    """Sutherland–Hodgman для выпуклого clipping-полигона карточки."""
    if len(subject) < 3 or len(clip) < 3:
        return []
    clip_poly = list(clip)
    if _signed_area(clip_poly) < 0:
        clip_poly.reverse()
    output = list(subject)
    eps = -1e-7
    for a, b in zip(clip_poly, clip_poly[1:] + clip_poly[:1]):
        if not output:
            break
        source = output
        output = []
        previous = source[-1]
        previous_inside = _cross(a, b, previous) >= eps
        for current in source:
            current_inside = _cross(a, b, current) >= eps
            if current_inside:
                if not previous_inside:
                    output.append(_intersection(a, b, previous, current))
                output.append(current)
            elif previous_inside:
                output.append(_intersection(a, b, previous, current))
            previous = current
            previous_inside = current_inside
    return output


def intersection_area(first: Polygon, second: Polygon) -> float:
    return polygon_area(clip_polygon(first, second))


def _outside_rect(point: Point, rect: tuple[float, float, float, float],
                  tolerance: float = 1.0) -> bool:
    x, y = point
    left, top, right, bottom = rect
    return (x < left - tolerance or x > right + tolerance
            or y < top - tolerance or y > bottom + tolerance)


def analyze_project(project: Project) -> list[PreflightIssue]:
    """Собрать предупреждения о качестве и геометрии текущего макета."""
    issues: list[PreflightIssue] = []
    if not project.items:
        return [PreflightIssue(
            "warning", "no_cards", "на листе нет ни одной карточки")]

    sheet_rect = (0.0, 0.0, float(project.sheet_w), float(project.sheet_h))
    safe_rect = project.safe_rect_px()
    polygons = [item.corners_sheet() for item in project.items]

    for index, item in enumerate(project.items):
        if not item.photo_path:
            issues.append(PreflightIssue(
                "warning", "empty_slot", "нет фотографии", index))
        elif not os.path.isfile(item.photo_path):
            issues.append(PreflightIssue(
                "warning", "missing_photo",
                "исходный файл фотографии не найден", index))
        elif not item.photo_size:
            issues.append(PreflightIssue(
                "info", "unknown_size",
                "не определён размер фотографии — нельзя проверить DPI", index))
        else:
            dpi = item.effective_print_dpi()
            if dpi is not None and dpi < 180.0:
                issues.append(PreflightIssue(
                    "warning", "low_dpi",
                    f"очень низкое разрешение после кадрирования: {dpi:.0f} DPI",
                    index))
            elif dpi is not None and dpi < 300.0:
                issues.append(PreflightIssue(
                    "warning", "below_print_dpi",
                    f"разрешение ниже печатных 300 DPI: {dpi:.0f} DPI", index))

        corners = polygons[index]
        if any(_outside_rect(point, sheet_rect) for point in corners):
            issues.append(PreflightIssue(
                "warning", "outside_sheet",
                "карточка частично выходит за границы листа", index))
        elif project.safe_margin_mm > 0 and any(
                _outside_rect(point, safe_rect) for point in corners):
            issues.append(PreflightIssue(
                "info", "outside_safe_area",
                "карточка заходит в безопасную зону у края листа", index))

        if project.cut_marks:
            clipped = False
            for segment in item.cut_mark_segments():
                if any(_outside_rect(point, sheet_rect) for point in segment):
                    clipped = True
                    break
            if clipped:
                issues.append(PreflightIssue(
                    "warning", "cut_marks_clipped",
                    "часть уголков обреза не помещается на листе", index))

    for i, first in enumerate(project.items):
        first_area = first.width * first.height
        for j in range(i + 1, len(project.items)):
            second = project.items[j]
            second_area = second.width * second.height
            overlap = intersection_area(polygons[i], polygons[j])
            threshold = max(200.0, min(first_area, second_area) * 0.01)
            if overlap > threshold:
                percent = overlap / min(first_area, second_area) * 100.0
                issues.append(PreflightIssue(
                    "info", "overlap",
                    f"перекрывается со слотом {j + 1} примерно на {percent:.0f}%",
                    i, j))
    return issues


def issue_counts(issues: list[PreflightIssue]) -> tuple[int, int]:
    warnings = sum(1 for issue in issues if issue.severity == "warning")
    infos = sum(1 for issue in issues if issue.severity == "info")
    return warnings, infos
