"""Тесты модели, раскладки и экспортного рендера (без GUI).

Запуск:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PIL import Image, ImageDraw  # noqa: E402

from softpalaroid.filters import FILTERS, apply_filter  # noqa: E402
from softpalaroid.model import (  # noqa: E402
    FRAME_RATIO,
    Project,
    compute_layout,
    sheet_size_px,
)
from softpalaroid.render import load_photo, render_sheet  # noqa: E402


def _make_photo(path: str, w: int = 1200, h: int = 900) -> None:
    img = Image.new("RGB", (w, h), (90, 140, 200))
    d = ImageDraw.Draw(img)
    d.ellipse([w * 0.6, h * 0.1, w * 0.85, h * 0.45], fill=(250, 210, 110))
    d.rectangle([0, h * 0.7, w, h], fill=(70, 140, 80))
    img.save(path, quality=90)


class TestLayout(unittest.TestCase):
    def test_sheet_size(self) -> None:
        self.assertEqual(sheet_size_px(True), (1772, 1181))
        self.assertEqual(sheet_size_px(False), (1181, 1772))

    def test_layouts_inside_sheet(self) -> None:
        for landscape in (True, False):
            w, h = sheet_size_px(landscape)
            for count in (1, 2, 4):
                with self.subTest(landscape=landscape, count=count):
                    pos = compute_layout(count, w, h)
                    self.assertEqual(len(pos), count)
                    for cx, cy, cw in pos:
                        ch = cw * FRAME_RATIO
                        self.assertGreaterEqual(cx - cw / 2, 0)
                        self.assertLessEqual(cx + cw / 2, w)
                        self.assertGreaterEqual(cy - ch / 2, 0)
                        self.assertLessEqual(cy + ch / 2, h)

    def test_more_cards_are_smaller(self) -> None:
        w, h = sheet_size_px(True)
        sizes = [compute_layout(n, w, h)[0][2] for n in (1, 2, 4)]
        self.assertTrue(sizes[0] > sizes[1] > sizes[2])


class TestFilters(unittest.TestCase):
    def test_all_filters_keep_size_and_mode(self) -> None:
        img = Image.new("RGB", (120, 90), (120, 90, 60))
        for name in FILTERS:
            with self.subTest(filter=name):
                out = apply_filter(img.copy(), name)
                self.assertEqual(out.size, img.size)
                self.assertEqual(out.mode, "RGB")


class TestRender(unittest.TestCase):
    def _project_with_photo(self, tmp: str, count: int, landscape: bool) -> Project:
        path = os.path.join(tmp, "photo.jpg")
        _make_photo(path)
        size = load_photo(path).size
        project = Project()
        project.set_layout(count, landscape=landscape)
        for item in project.items:
            item.set_photo(path, size)
            item.caption = "Тест 2026"
            item.filter = "vintage"
            item.rotation = 4.0
            item.zoom = 1.3
        return project

    def test_render_sizes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for landscape in (True, False):
                for count in (1, 2, 4):
                    with self.subTest(landscape=landscape, count=count):
                        project = self._project_with_photo(tmp, count, landscape)
                        img = render_sheet(project)
                        self.assertEqual(img.size, sheet_size_px(landscape))
                        lo, hi = img.getextrema()[0]
                        self.assertLess(lo, 250)  # лист не пустой/не чисто белый

    def test_render_without_photo(self) -> None:
        project = Project()
        project.set_layout(2, landscape=True)
        img = render_sheet(project)
        self.assertEqual(img.size, (1772, 1181))


if __name__ == "__main__":
    unittest.main()
