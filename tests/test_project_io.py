"""Тесты сохранения/загрузки проектов .softpalaroid."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PIL import Image  # noqa: E402

from softpalaroid.model import Project  # noqa: E402
from softpalaroid.project_io import (  # noqa: E402
    MANIFEST_NAME,
    ProjectFileError,
    load_project_file,
    save_project_file,
)
from softpalaroid.render import load_photo  # noqa: E402


def _make_photo(path: str) -> tuple[int, int]:
    img = Image.new("RGB", (1000, 800), (70, 120, 180))
    img.save(path, quality=90)
    return load_photo(path).size


class TestProjectIO(unittest.TestCase):
    def _project(self, photo: str, size: tuple[int, int]) -> Project:
        project = Project()
        project.set_layout(2, landscape=True)
        for i, item in enumerate(project.items):
            item.set_photo(photo, size)
            item.caption = f"Фото {i + 1}"
            item.filter = "vintage"
            item.rotation = -2.0 + i
            item.zoom = 1.2
            item.offset_x = 0.4
            item.offset_y = 0.6
        return project

    def test_roundtrip_embeds_and_deduplicates_photo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            photo = os.path.join(tmp, "source.jpg")
            size = _make_photo(photo)
            project = self._project(photo, size)
            filename = os.path.join(tmp, "demo.softpalaroid")
            save_project_file(project, filename, selected_index=1)

            with zipfile.ZipFile(filename) as zf:
                images = [n for n in zf.namelist() if n.startswith("images/")]
            self.assertEqual(len(images), 1, "одно и то же фото хранится один раз")

            # Проект должен открываться даже после удаления исходника.
            os.remove(photo)
            extract = os.path.join(tmp, "extract")
            loaded = load_project_file(filename, extract)

            self.assertEqual(loaded.selected_index, 1)
            self.assertEqual(loaded.warnings, [])
            self.assertTrue(loaded.project.landscape)
            self.assertEqual(len(loaded.project.items), 2)
            first = loaded.project.items[0]
            self.assertEqual(first.caption, "Фото 1")
            self.assertEqual(first.filter, "vintage")
            self.assertAlmostEqual(first.rotation, -2.0)
            self.assertAlmostEqual(first.zoom, 1.2)
            self.assertAlmostEqual(first.offset_x, 0.4)
            self.assertIsNotNone(first.photo_path)
            self.assertTrue(os.path.isfile(first.photo_path))
            self.assertEqual(first.photo_size, size)

    def test_missing_image_in_archive_becomes_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            photo = os.path.join(tmp, "source.jpg")
            project = self._project(photo, _make_photo(photo))
            original = os.path.join(tmp, "original.softpalaroid")
            save_project_file(project, original)

            stripped = os.path.join(tmp, "stripped.softpalaroid")
            with zipfile.ZipFile(original) as src, \
                    zipfile.ZipFile(stripped, "w") as dst:
                dst.writestr(MANIFEST_NAME, src.read(MANIFEST_NAME))

            loaded = load_project_file(
                stripped, os.path.join(tmp, "extract"))
            self.assertTrue(loaded.warnings)
            self.assertIsNone(loaded.project.items[0].photo_path)

    def test_unsafe_image_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            filename = os.path.join(tmp, "evil.softpalaroid")
            manifest = {
                "format": "softpalaroid-project",
                "version": 1,
                "landscape": True,
                "selected_index": 0,
                "items": [{"photo": "../evil.jpg"}],
                "metadata": {},
            }
            with zipfile.ZipFile(filename, "w") as zf:
                zf.writestr(MANIFEST_NAME, json.dumps(manifest))
            with self.assertRaises(ProjectFileError):
                load_project_file(filename, os.path.join(tmp, "extract"))

    def test_save_missing_photo_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project()
            project.set_layout(1, landscape=True)
            project.items[0].set_photo(
                os.path.join(tmp, "does-not-exist.jpg"), (100, 100))
            destination = os.path.join(tmp, "broken.softpalaroid")
            with self.assertRaises(FileNotFoundError):
                save_project_file(project, destination)
            self.assertFalse(os.path.exists(destination))


if __name__ == "__main__":
    unittest.main()
