"""Тесты возможностей v0.8: выравнивание карточек, фоны листа, проект v4."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from softpalaroid.model import Project  # noqa: E402
from softpalaroid.project_io import (  # noqa: E402
    MANIFEST_NAME,
    load_project_file,
    save_project_file,
)
from softpalaroid.render import make_background  # noqa: E402
from softpalaroid.templates import apply_design_template  # noqa: E402


def _project_with_centers(centers: list[tuple[float, float]]) -> Project:
    project = Project()
    project.set_layout(len(centers), landscape=True)
    for item, (cx, cy) in zip(project.items, centers):
        item.center_x, item.center_y = cx, cy
        item.width = 500.0
        item.rotation = 0.0
        item.clamp()
    return project


class TestArrangeCards(unittest.TestCase):
    def test_align_left_and_bottom(self) -> None:
        project = _project_with_centers(
            [(400.0, 400.0), (700.0, 500.0), (550.0, 600.0)])
        project.align_items("left")
        lefts = [item.bounds_sheet()[0] for item in project.items]
        self.assertAlmostEqual(lefts[0], lefts[1])
        self.assertAlmostEqual(lefts[0], lefts[2])
        self.assertAlmostEqual(lefts[0], 150.0)  # минимальный исходный левый край

        project.align_items("bottom")
        bottoms = [item.bounds_sheet()[3] for item in project.items]
        self.assertAlmostEqual(bottoms[0], bottoms[1])
        self.assertAlmostEqual(bottoms[0], bottoms[2])

    def test_align_centers(self) -> None:
        project = _project_with_centers(
            [(400.0, 400.0), (700.0, 600.0), (550.0, 500.0)])
        project.align_items("center_x")
        centers_x = []
        for item in project.items:
            left, _top, right, _bottom = item.bounds_sheet()
            centers_x.append((left + right) / 2.0)
        self.assertAlmostEqual(centers_x[0], centers_x[1])
        self.assertAlmostEqual(centers_x[0], centers_x[2])

        project.align_items("center_y")
        centers_y = []
        for item in project.items:
            _left, top, _right, bottom = item.bounds_sheet()
            centers_y.append((top + bottom) / 2.0)
        self.assertAlmostEqual(centers_y[0], centers_y[1])
        self.assertAlmostEqual(centers_y[0], centers_y[2])

    def test_align_invalid_mode_raises(self) -> None:
        project = _project_with_centers([(1.0, 1.0), (2.0, 2.0)])
        with self.assertRaises(ValueError):
            project.align_items("diagonal")

    def test_distribute_centers_evenly(self) -> None:
        project = _project_with_centers(
            [(900.0, 500.0), (100.0, 520.0), (130.0, 540.0)])
        project.distribute_items("x")
        xs = sorted(item.center_x for item in project.items)
        self.assertAlmostEqual(xs[0], 100.0)
        self.assertAlmostEqual(xs[1], 500.0)
        self.assertAlmostEqual(xs[2], 900.0)

        project2 = _project_with_centers(
            [(500.0, 800.0), (520.0, 100.0), (540.0, 180.0)])
        project2.distribute_items("y")
        ys = sorted(item.center_y for item in project2.items)
        self.assertAlmostEqual(ys[1], 450.0)

    def test_straighten_and_deterministic_scatter(self) -> None:
        centers = [(400.0, 400.0), (900.0, 500.0), (600.0, 700.0)]
        first = _project_with_centers(centers)
        second = _project_with_centers(centers)
        first.scatter_items(seed=42)
        second.scatter_items(seed=42)
        for a, b in zip(first.items, second.items):
            self.assertEqual(a.rotation, b.rotation)
            self.assertEqual(a.center_x, b.center_x)
            self.assertLessEqual(abs(a.rotation), 4.0)
            self.assertTrue(0.0 <= a.center_x <= first.sheet_w)
            self.assertTrue(0.0 <= a.center_y <= first.sheet_h)
        first.straighten_items()
        self.assertTrue(all(item.rotation == 0.0 for item in first.items))


def _small_project(style: str, color1: str, color2: str) -> Project:
    project = Project()
    project.set_sheet_dimensions(5.0, 5.0, paper_size="custom")
    project.background_color = color1
    project.background_style = style
    project.background_color2 = color2
    project.clamp_settings()
    return project


class TestBackgroundStyles(unittest.TestCase):
    def test_solid_and_invalid_style_clamps(self) -> None:
        project = _small_project("weird", "#102030", "#ffffff")
        self.assertEqual(project.background_style, "solid")
        img = make_background(project)
        self.assertEqual(img.getpixel((3, 3)), (16, 32, 48))
        self.assertEqual(img.getpixel((img.width - 3, img.height - 3)),
                         (16, 32, 48))

    def test_gradient_goes_from_first_to_second_color(self) -> None:
        project = _small_project("gradient", "#000000", "#ffffff")
        img = make_background(project)
        self.assertLessEqual(img.getpixel((10, 0))[0], 2)
        self.assertEqual(img.getpixel((10, img.height - 1)), (255, 255, 255))
        middle = img.getpixel((10, img.height // 2))[0]
        self.assertTrue(120 <= middle <= 136)

    def test_dots_and_grid_pixels(self) -> None:
        dots = make_background(_small_project("dots", "#ffffff", "#ff0000"))
        self.assertEqual(dots.getpixel((36, 36)), (255, 0, 0))  # центр точки
        self.assertEqual(dots.getpixel((2, 2)), (255, 255, 255))

        grid = make_background(_small_project("grid", "#ffffff", "#0000ff"))
        self.assertEqual(grid.getpixel((0, 50)), (0, 0, 255))  # вертикальная линия
        self.assertEqual(grid.getpixel((50, 96)), (0, 0, 255))  # горизонталь
        self.assertEqual(grid.getpixel((48, 48)), (255, 255, 255))

    def test_explicit_background_override_is_solid(self) -> None:
        project = _small_project("gradient", "#000000", "#ffffff")
        img = make_background(project, (10, 20, 30))
        self.assertEqual(img.getpixel((5, img.height - 5)), (10, 20, 30))

    def test_templates_set_background_styles(self) -> None:
        project = Project()
        project.set_layout(1)
        apply_design_template(project, "pastel")
        self.assertEqual(project.background_style, "dots")
        self.assertEqual(project.background_color2, "#ffe1e8")
        apply_design_template(project, "bright_album")
        self.assertEqual(project.background_style, "gradient")
        apply_design_template(project, "classic")
        self.assertEqual(project.background_style, "solid")


class TestProjectV4(unittest.TestCase):
    def test_background_fields_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project()
            project.set_layout(1, landscape=True)
            project.background_color = "#fff6f9"
            project.background_style = "grid"
            project.background_color2 = "#123456"
            project.clamp_settings()
            filename = os.path.join(tmp, "bg.softpalaroid")
            save_project_file(project, filename)
            with zipfile.ZipFile(filename) as zf:
                manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
            self.assertEqual(manifest["version"], 4)
            loaded = load_project_file(filename, os.path.join(tmp, "extract"))
            self.assertEqual(loaded.project.background_style, "grid")
            self.assertEqual(loaded.project.background_color2, "#123456")
            self.assertEqual(loaded.project.background_color, "#fff6f9")

    def test_v3_manifest_gets_background_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            filename = os.path.join(tmp, "legacy3.softpalaroid")
            manifest = {
                "format": "softpalaroid-project",
                "version": 3,
                "landscape": True,
                "background_color": "#ffffff",
                "cut_marks": True,
                "selected_index": 0,
                "items": [{"center_x": 500, "center_y": 400, "width": 500}],
                "metadata": {},
            }
            with zipfile.ZipFile(filename, "w") as zf:
                zf.writestr(MANIFEST_NAME, json.dumps(manifest))
            loaded = load_project_file(filename, os.path.join(tmp, "extract"))
            self.assertEqual(loaded.project.background_style, "solid")
            self.assertEqual(loaded.project.background_color2, "#dceeff")


if __name__ == "__main__":
    unittest.main()
