"""Тесты возможностей v0.6: бумага, форматы, preflight, batch, RAW."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PIL import Image, ImageCms  # noqa: E402

from softpalaroid.batch import BatchOptions, export_batch  # noqa: E402
from softpalaroid.filters import apply_filter, apply_photo_adjustments  # noqa: E402
from softpalaroid.image_io import (  # noqa: E402
    load_photo,
    probe_image_size,
    srgb_icc_profile,
    supported_image_extensions,
)
from softpalaroid.model import (  # noqa: E402
    CARD_FORMATS,
    PAPER_SIZES,
    PolaroidItem,
    Project,
)
from softpalaroid.preflight import analyze_project, intersection_area  # noqa: E402
from softpalaroid.project_io import (  # noqa: E402
    MANIFEST_NAME,
    load_project_file,
    save_project_file,
)
from softpalaroid.render import save_card, save_sheet  # noqa: E402
from softpalaroid.templates import apply_design_template  # noqa: E402


def _make_photo(path: str, size: tuple[int, int] = (420, 300),
                color: tuple[int, int, int] = (80, 140, 200)) -> None:
    Image.new("RGB", size, color).save(path)


class TestPaperAndCardFormats(unittest.TestCase):
    def test_paper_presets_and_custom_dimensions(self) -> None:
        project = Project()
        project.set_paper_size("a4", landscape=True)
        self.assertEqual((project.sheet_w, project.sheet_h), (3508, 2480))
        self.assertEqual(project.sheet_label, "29,7×21 см")

        project.set_sheet_dimensions(12.5, 20.0, paper_size="custom")
        self.assertFalse(project.landscape)
        self.assertEqual(project.paper_size, "custom")
        self.assertAlmostEqual(project.sheet_width_cm, 12.5)
        self.assertAlmostEqual(project.sheet_height_cm, 20.0)
        project.set_layout(1, landscape=True)
        self.assertTrue(project.landscape)
        self.assertAlmostEqual(project.sheet_width_cm, 20.0)
        self.assertAlmostEqual(project.sheet_height_cm, 12.5)

    def test_card_formats_have_expected_photo_shapes_and_fit(self) -> None:
        classic = PolaroidItem(card_format="classic", width=880)
        self.assertAlmostEqual(classic.photo_width, classic.photo_height, places=5)
        mini = PolaroidItem(card_format="instax_mini", width=540)
        self.assertGreater(mini.photo_height, mini.photo_width)
        wide = PolaroidItem(card_format="instax_wide", width=1080)
        self.assertGreater(wide.photo_width, wide.photo_height)

        for paper in PAPER_SIZES:
            for card_format in CARD_FORMATS:
                with self.subTest(paper=paper, card_format=card_format):
                    project = Project()
                    project.set_paper_size(paper, landscape=True)
                    project.set_card_format(card_format)
                    project.set_layout(4, landscape=True)
                    for item in project.items:
                        left, top, right, bottom = item.bounds_sheet()
                        self.assertGreaterEqual(left, -0.01)
                        self.assertGreaterEqual(top, -0.01)
                        self.assertLessEqual(right, project.sheet_w + 0.01)
                        self.assertLessEqual(bottom, project.sheet_h + 0.01)

    def test_effective_dpi_accounts_for_cover_and_zoom(self) -> None:
        item = PolaroidItem(card_format="classic")
        item.width = 600.0 / (79.0 / 88.0)  # фото-окно ровно 600x600 px
        item.set_photo("synthetic.jpg", (600, 600))
        self.assertAlmostEqual(item.effective_print_dpi() or 0, 300.0, places=5)
        item.zoom = 1.5
        self.assertAlmostEqual(item.effective_print_dpi() or 0, 200.0, places=5)

    def test_safe_margin_is_clamped_and_rect_is_inside_sheet(self) -> None:
        project = Project(safe_margin_mm=999)
        self.assertLessEqual(project.safe_margin_mm, 25.0)
        left, top, right, bottom = project.safe_rect_px()
        self.assertLess(left, right)
        self.assertLess(top, bottom)
        self.assertGreaterEqual(left, 0)
        self.assertLessEqual(right, project.sheet_w)


class TestDeterministicFilters(unittest.TestCase):
    def test_grain_seed_is_repeatable_and_intensity_zero_is_identity(self) -> None:
        img = Image.linear_gradient("L").resize((96, 72)).convert("RGB")
        first = apply_filter(img.copy(), "vintage", seed=1234)
        second = apply_filter(img.copy(), "vintage", seed=1234)
        different = apply_filter(img.copy(), "vintage", seed=9876)
        self.assertEqual(first.tobytes(), second.tobytes())
        self.assertNotEqual(first.tobytes(), different.tobytes())
        self.assertEqual(
            apply_filter(img.copy(), "vintage", seed=1234, intensity=0).tobytes(),
            img.tobytes())

    def test_adjustments_change_pixels(self) -> None:
        img = Image.new("RGB", (8, 8), (100, 80, 60))
        out = apply_photo_adjustments(img, brightness=1.4, saturation=1.2)
        self.assertGreater(out.getpixel((0, 0))[0], 100)


class TestPreflightAndTemplates(unittest.TestCase):
    def test_intersection_area_of_identical_cards(self) -> None:
        project = Project()
        project.set_layout(2, landscape=True)
        first, second = project.items
        second.center_x, second.center_y = first.center_x, first.center_y
        second.width, second.rotation = first.width, first.rotation
        area = intersection_area(first.corners_sheet(), second.corners_sheet())
        self.assertAlmostEqual(area, first.width * first.height, places=2)
        codes = {issue.code for issue in analyze_project(project)}
        self.assertIn("overlap", codes)
        self.assertIn("empty_slot", codes)

    def test_preflight_reports_low_dpi_safe_area_and_clipped_marks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            photo = os.path.join(tmp, "small.jpg")
            _make_photo(photo, (100, 100))
            project = Project()
            project.set_layout(1, landscape=True)
            item = project.items[0]
            item.set_photo(photo, (100, 100))
            item.width = 800  # по высоте карточка целиком внутри листа 10x15
            item.center_x = item.width / 2  # у левого края, но внутри листа
            item.center_y = project.sheet_h / 2
            project.safe_margin_mm = 10
            project.cut_marks = True
            codes = {issue.code for issue in analyze_project(project)}
            self.assertIn("low_dpi", codes)
            self.assertIn("outside_safe_area", codes)
            self.assertIn("cut_marks_clipped", codes)

    def test_template_applies_to_sheet_and_items(self) -> None:
        project = Project()
        project.set_layout(2, landscape=True)
        for item in project.items:
            item.caption_color = "#123456"
        template = apply_design_template(project, "pastel")
        self.assertEqual(project.template, "pastel")
        self.assertEqual(project.background_color, template.background_color)
        self.assertEqual(project.items[0].frame_color, template.frame_colors[0])
        self.assertEqual(project.items[1].frame_color, template.frame_colors[1])
        self.assertTrue(all(item.filter == "faded" for item in project.items))
        self.assertTrue(all(item.caption_color is None for item in project.items))


class _FakeRaw:
    sizes = types.SimpleNamespace(
        iwidth=4, iheight=2, width=4, height=2, flip=0)

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def postprocess(self, **_kwargs):
        return [
            [[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 0]],
            [[10, 20, 30], [40, 50, 60], [70, 80, 90], [100, 110, 120]],
        ]


def _fake_rawpy_module() -> types.ModuleType:
    module = types.ModuleType("rawpy")
    module.ColorSpace = types.SimpleNamespace(sRGB=object())  # type: ignore[attr-defined]
    module.DemosaicAlgorithm = types.SimpleNamespace(AHD=object())  # type: ignore[attr-defined]
    module.imread = lambda _path: _FakeRaw()  # type: ignore[attr-defined]
    return module


class TestRawAndColorManagement(unittest.TestCase):
    def test_raw_probe_load_and_extensions_with_fake_libraw(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "camera.cr2")
            with open(path, "wb") as fh:
                fh.write(b"fake raw payload for the injected decoder")
            with patch.dict(sys.modules, {"rawpy": _fake_rawpy_module()}):
                self.assertIn(".cr2", supported_image_extensions())
                self.assertEqual(probe_image_size(path), (4, 2))
                loaded = load_photo(path)
            self.assertEqual(loaded.size, (4, 2))
            self.assertEqual(loaded.getpixel((0, 0)), (255, 0, 0))

    def test_embedded_non_srgb_icc_is_converted_on_load(self) -> None:
        self.assertIsNotNone(srgb_icc_profile())
        self.assertGreater(len(srgb_icc_profile() or b""), 100)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "lab-tagged.tif")
            lab_profile = ImageCms.ImageCmsProfile(
                ImageCms.createProfile("LAB")).tobytes()
            # LAB-профиль должен сопровождаться LAB-пикселями, иначе LCMS
            # закономерно не сможет построить преобразование.
            Image.new("LAB", (16, 16), (180, 160, 80)).save(
                path, icc_profile=lab_profile)
            loaded = load_photo(path)
            self.assertEqual(loaded.mode, "RGB")
            self.assertNotEqual(loaded.getpixel((0, 0)), (180, 160, 80))


class TestProjectV3(unittest.TestCase):
    def test_new_fields_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            photo = os.path.join(tmp, "photo.jpg")
            _make_photo(photo)
            project = Project()
            project.set_paper_size("a5", landscape=False)
            project.set_card_format("instax_mini")
            project.set_layout(1, landscape=False)
            project.template = "warm_film"
            project.safe_margin_mm = 7.5
            project.show_safe_area = False
            project.snap_enabled = False
            project.clamp_settings()
            item = project.items[0]
            item.set_photo(photo, (420, 300))
            item.caption = "Строка 1\nСтрока 2"
            item.filter_intensity = 0.35
            item.brightness = 1.2
            item.contrast = 0.9
            item.saturation = 1.3
            item.sharpness = 1.4
            item.caption_scale = 1.25
            item.caption_color = "#203040"
            item.caption_align = "right"
            item.grain_seed = 123456
            item.clamp()

            filename = os.path.join(tmp, "new.softpalaroid")
            save_project_file(project, filename)
            loaded = load_project_file(filename, os.path.join(tmp, "extract"))
            self.assertEqual(loaded.warnings, [])
            restored = loaded.project
            self.assertEqual(restored.paper_size, "a5")
            self.assertFalse(restored.landscape)
            self.assertEqual(restored.card_format, "instax_mini")
            self.assertEqual(restored.template, "warm_film")
            self.assertAlmostEqual(restored.safe_margin_mm, 7.5)
            self.assertFalse(restored.show_safe_area)
            self.assertFalse(restored.snap_enabled)
            restored_item = restored.items[0]
            self.assertEqual(restored_item.card_format, "instax_mini")
            self.assertEqual(restored_item.caption, "Строка 1\nСтрока 2")
            self.assertAlmostEqual(restored_item.filter_intensity, 0.35)
            self.assertAlmostEqual(restored_item.brightness, 1.2)
            self.assertEqual(restored_item.caption_color, "#203040")
            self.assertEqual(restored_item.caption_align, "right")
            self.assertEqual(restored_item.grain_seed, 123456)

    def test_v2_manifest_gets_new_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            filename = os.path.join(tmp, "legacy2.softpalaroid")
            manifest = {
                "format": "softpalaroid-project",
                "version": 2,
                "landscape": False,
                "background_color": "#ffffff",
                "cut_marks": True,
                "selected_index": 0,
                "items": [{"center_x": 500, "center_y": 600, "width": 500}],
                "metadata": {},
            }
            with zipfile.ZipFile(filename, "w") as zf:
                zf.writestr(MANIFEST_NAME, json.dumps(manifest))
            loaded = load_project_file(filename, os.path.join(tmp, "extract"))
            self.assertEqual(loaded.project.paper_size, "10x15")
            self.assertEqual(loaded.project.sheet_size_cm, (10.0, 15.0))
            self.assertEqual(loaded.project.card_format, "classic")
            self.assertAlmostEqual(loaded.project.safe_margin_mm, 5.0)
            self.assertEqual(loaded.project.items[0].brightness, 1.0)
            self.assertEqual(loaded.project.items[0].caption_align, "center")


class TestBatchAndExports(unittest.TestCase):
    def test_batch_splits_photos_and_continues_after_bad_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for index in range(3):
                path = os.path.join(tmp, f"holiday_day_{index + 1}.jpg")
                _make_photo(path, (360, 240), (40 + index * 50, 120, 180))
                paths.append(path)
            bad = os.path.join(tmp, "bad.txt")
            with open(bad, "w", encoding="utf-8") as fh:
                fh.write("not a photo")
            output = os.path.join(tmp, "out")
            result = export_batch(
                [*paths, bad], output,
                BatchOptions(
                    cards_per_sheet=2,
                    captions_from_filename=True,
                    prefix="My Batch!",
                ))
            self.assertEqual(result.photo_count, 3)
            self.assertEqual(result.sheet_count, 2)
            self.assertEqual(len(result.errors), 1)
            self.assertEqual(
                [path.name for path in result.output_files],
                ["My-Batch-001.jpg", "My-Batch-002.jpg"])
            for path in result.output_files:
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 100)

    def test_pdf_jpg_png_and_single_card_exports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project()
            project.set_layout(1, landscape=True)
            pdf = os.path.join(tmp, "sheet.pdf")
            jpg = os.path.join(tmp, "sheet.jpg")
            png = os.path.join(tmp, "sheet.png")
            save_sheet(project, pdf)
            save_sheet(project, jpg)
            save_sheet(project, png)
            with open(pdf, "rb") as fh:
                self.assertEqual(fh.read(4), b"%PDF")
            for path in (jpg, png):
                with Image.open(path) as img:
                    img.load()
                    self.assertTrue(img.info.get("icc_profile"), path)

            item = project.items[0]
            item.rotation = 12
            card_path = os.path.join(tmp, "card.png")
            save_card(item, card_path)
            with Image.open(card_path) as card:
                card.load()
                self.assertEqual(card.mode, "RGBA")
                self.assertGreater(card.width, item.width)


if __name__ == "__main__":
    unittest.main()
