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

from softpalaroid.filters import FILTERS, apply_filter, transform_photo  # noqa: E402
from softpalaroid.model import (  # noqa: E402
    CUT_MARK_ARM_PX,
    FRAME_RATIO,
    MAX_CARDS,
    PolaroidItem,
    Project,
    compute_layout,
    sheet_size_px,
)
from softpalaroid.render import _caption_font, _font_candidates, load_photo, render_sheet  # noqa: E402


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
            for count in (1, 2, 3, 4, 6, 9, 12):
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


class TestCardOperations(unittest.TestCase):
    def test_add_duplicate_remove_and_reorder(self) -> None:
        project = Project()
        project.set_layout(2, landscape=True)
        project.items[0].caption = "A"
        project.items[1].caption = "B"
        first_position = (project.items[0].center_x, project.items[0].center_y)

        added = project.add_item()
        self.assertEqual(added, 2)
        self.assertEqual(len(project.items), 3)
        self.assertEqual(
            first_position,
            (project.items[0].center_x, project.items[0].center_y),
            "добавление не должно переставлять существующие карточки")

        clone_index = project.duplicate_item(0)
        self.assertEqual(clone_index, 1)
        self.assertEqual(project.items[clone_index].caption, "A")
        self.assertGreater(
            project.items[clone_index].center_x, project.items[0].center_x)

        moved = project.move_item(clone_index, len(project.items) - 1)
        self.assertEqual(project.items[moved].caption, "A")
        removed = project.remove_item(moved)
        self.assertEqual(removed.caption, "A")
        self.assertEqual(len(project.items), 3)

    def test_card_count_limits(self) -> None:
        project = Project()
        project.set_layout(MAX_CARDS, landscape=True)
        with self.assertRaises(ValueError):
            project.add_item()
        project.set_layout(1, landscape=True)
        with self.assertRaises(ValueError):
            project.remove_item(0)


class TestPhotoTransform(unittest.TestCase):
    def test_effective_size_and_reset_on_new_photo(self) -> None:
        item = PolaroidItem()
        item.set_photo("photo.jpg", (1200, 800))
        item.photo_rotation = 90
        item.flip_horizontal = True
        item.clamp()
        self.assertEqual(item.effective_photo_size(), (800, 1200))
        item.set_photo("other.jpg", (900, 900))
        self.assertEqual(item.photo_rotation, 0)
        self.assertFalse(item.flip_horizontal)

    def test_rotate_clockwise_and_flip_pixels(self) -> None:
        img = Image.new("RGB", (2, 1))
        img.putpixel((0, 0), (255, 0, 0))
        img.putpixel((1, 0), (0, 0, 255))

        rotated = transform_photo(img, rotation=90)
        self.assertEqual(rotated.size, (1, 2))
        self.assertEqual(rotated.getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(rotated.getpixel((0, 1)), (0, 0, 255))

        flipped = transform_photo(img, flip_horizontal=True)
        self.assertEqual(flipped.getpixel((0, 0)), (0, 0, 255))


class TestCutMarksGeometry(unittest.TestCase):
    def test_eight_segments_outside_card(self) -> None:
        item = PolaroidItem(center_x=500, center_y=500, width=400)
        segments = item.cut_mark_segments()
        self.assertEqual(len(segments), 8)
        left = item.center_x - item.width / 2
        right = item.center_x + item.width / 2
        top = item.center_y - item.height / 2
        bottom = item.center_y + item.height / 2
        for (x1, y1), (x2, y2) in segments:
            self.assertTrue(
                x1 < left or x1 > right or y1 < top or y1 > bottom,
                (x1, y1))
            self.assertAlmostEqual(
                ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5,
                CUT_MARK_ARM_PX,
                places=5,
            )

    def test_rotated_segments_keep_arm_length(self) -> None:
        item = PolaroidItem(center_x=500, center_y=500, width=400, rotation=30)
        for (x1, y1), (x2, y2) in item.cut_mark_segments(arm=40):
            self.assertAlmostEqual(
                ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5, 40, places=5)


class TestFilters(unittest.TestCase):
    def test_all_filters_keep_size_and_mode(self) -> None:
        img = Image.new("RGB", (120, 90), (120, 90, 60))
        for name in FILTERS:
            with self.subTest(filter=name):
                out = apply_filter(img.copy(), name)
                self.assertEqual(out.size, img.size)
                self.assertEqual(out.mode, "RGB")


class TestCaptionFont(unittest.TestCase):
    def test_bundled_caveat_has_priority(self) -> None:
        candidates = _font_candidates()
        self.assertTrue(candidates, "не найден ни один шрифт подписи")
        self.assertTrue(candidates[0].endswith("Caveat.ttf"), candidates[0])
        font = _caption_font(60)
        self.assertTrue(font.getname()[0].startswith("Caveat"), font.getname())


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

    def test_render_has_no_card_shadow_and_has_cut_marks(self) -> None:
        project = Project()
        project.set_layout(1, landscape=True)
        item = project.items[0]
        item.rotation = 0
        img = render_sheet(project)

        below_card = item.local_to_sheet(item.width / 2, item.height + 7)
        self.assertEqual(
            img.getpixel((int(below_card[0]), int(below_card[1]))),
            (255, 255, 255),
            "под карточкой не должно быть серой размытой тени")

        (x1, y1), (x2, y2) = item.cut_mark_segments()[0]
        mark_mid = (int((x1 + x2) / 2), int((y1 + y2) / 2))
        self.assertEqual(img.getpixel(mark_mid), (92, 96, 102))

        project.cut_marks = False
        without_marks = render_sheet(project)
        self.assertEqual(without_marks.getpixel(mark_mid), (255, 255, 255))

    def test_render_uses_sheet_and_frame_colors(self) -> None:
        project = Project(background_color="#102030")
        project.set_layout(1, landscape=True)
        item = project.items[0]
        item.frame_color = "#ffe1e8"
        img = render_sheet(project)
        self.assertEqual(img.getpixel((3, 3)), (16, 32, 48))
        frame_point = item.local_to_sheet(item.width / 2, item.height * 0.95)
        self.assertEqual(
            img.getpixel((int(frame_point[0]), int(frame_point[1]))),
            (255, 225, 232))

    def test_render_rotates_photo_inside_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "photo.png")
            photo = Image.new("RGB", (200, 100), (0, 0, 255))
            ImageDraw.Draw(photo).rectangle(
                [0, 0, 99, 99], fill=(255, 0, 0))
            photo.save(path)

            project = Project()
            project.set_layout(1, landscape=True)
            item = project.items[0]
            item.set_photo(path, photo.size)
            item.photo_rotation = 90
            img = render_sheet(project)

            inset = item.photo_rect_local()
            top_point = item.local_to_sheet(
                item.width / 2, inset[1] + item.photo_side * 0.25)
            bottom_point = item.local_to_sheet(
                item.width / 2, inset[1] + item.photo_side * 0.75)
            top_pixel = img.getpixel((int(top_point[0]), int(top_point[1])))
            bottom_pixel = img.getpixel(
                (int(bottom_point[0]), int(bottom_point[1])))
            self.assertGreater(top_pixel[0], 200)
            self.assertGreater(bottom_pixel[2], 200)


if __name__ == "__main__":
    unittest.main()
