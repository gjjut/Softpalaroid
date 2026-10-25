"""Тесты универсальной загрузки изображений разных форматов."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PIL import Image, UnidentifiedImageError  # noqa: E402

from softpalaroid.image_io import (  # noqa: E402
    identify_image_format,
    image_file_filter,
    is_supported_image_file,
    load_photo,
    probe_image_size,
    supported_image_extensions,
)


class TestSupportedExtensions(unittest.TestCase):
    def test_common_and_modern_extensions_are_advertised(self) -> None:
        exts = supported_image_extensions()
        for ext in (".jfif", ".jpg", ".jpeg", ".png", ".heic", ".heif",
                    ".avif", ".webp", ".gif", ".bmp", ".tiff", ".jp2"):
            with self.subTest(ext=ext):
                self.assertIn(ext, exts)
        self.assertIn("*.jfif", image_file_filter())
        self.assertIn("*.heic", image_file_filter())


class TestLoadPhoto(unittest.TestCase):
    def _save_sample(self, path: str) -> None:
        Image.new("RGB", (80, 60), (30, 100, 170)).save(path)

    def test_jfif_loads_as_jpeg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "photo.jfif")
            self._save_sample(path)
            self.assertEqual(identify_image_format(path), "JPEG")
            self.assertTrue(is_supported_image_file(path))
            img = load_photo(path)
            self.assertEqual(img.size, (80, 60))
            self.assertEqual(img.mode, "RGB")
            self.assertEqual(probe_image_size(path), (80, 60))

    def test_format_is_detected_by_content_not_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source.jpg")
            self._save_sample(source)
            for name in ("photo.bin", "photo.photo", "photo"):
                target = os.path.join(tmp, name)
                shutil.copyfile(source, target)
                with self.subTest(name=name):
                    self.assertEqual(identify_image_format(target), "JPEG")
                    self.assertTrue(is_supported_image_file(target))
                    self.assertEqual(load_photo(target).size, (80, 60))

    def test_common_raster_encodings_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Image.new("RGB", (48, 36), (90, 40, 160))
            for name in ("sample.bmp", "sample.gif", "sample.webp",
                         "sample.tiff", "sample.jp2", "sample.qoi",
                         "sample.tga"):
                path = os.path.join(tmp, name)
                try:
                    source.save(path)
                except Exception as exc:  # noqa: BLE001 - кодек записи опционален
                    self.skipTest(f"encoder for {name} unavailable: {exc}")
                with self.subTest(name=name):
                    loaded = load_photo(path)
                    self.assertEqual(loaded.size, source.size)
                    self.assertEqual(loaded.mode, "RGB")

    def test_animated_gif_uses_first_frame(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "animated.gif")
            first = Image.new("RGB", (40, 30), (255, 0, 0))
            second = Image.new("RGB", (40, 30), (0, 0, 255))
            first.save(path, save_all=True, append_images=[second], duration=100)
            loaded = load_photo(path)
            self.assertEqual(loaded.getpixel((0, 0)), (255, 0, 0))

    def test_transparency_is_composited_on_white(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "alpha.png")
            Image.new("RGBA", (20, 20), (255, 0, 0, 0)).save(path)
            loaded = load_photo(path)
            self.assertEqual(loaded.mode, "RGB")
            self.assertEqual(loaded.getpixel((0, 0)), (255, 255, 255))

    def test_heic_and_avif_when_encoders_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Image.new("RGB", (40, 30), (20, 120, 80))
            for name, expected in (("photo.heic", "HEIF"),
                                   ("photo.avif", "AVIF")):
                path = os.path.join(tmp, name)
                try:
                    source.save(path)
                except Exception:  # noqa: BLE001 - энкодер зависит от сборки
                    continue
                with self.subTest(name=name):
                    self.assertEqual(identify_image_format(path), expected)
                    self.assertEqual(load_photo(path).size, (40, 30))

    def test_non_image_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "not-a-photo.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("это не изображение")
            self.assertIsNone(identify_image_format(path))
            self.assertFalse(is_supported_image_file(path))
            with self.assertRaises(UnidentifiedImageError):
                load_photo(path)


if __name__ == "__main__":
    unittest.main()
