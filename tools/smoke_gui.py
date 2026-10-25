"""GUI smoke-тест для CI: запуск окна, загрузка фото, экспорт листа.

Запуск:  QT_QPA_PLATFORM=offscreen python tools/smoke_gui.py
Печатает "SMOKE OK" и завершается с кодом 0 при успехе.
"""
from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from PIL import Image, ImageDraw  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from softpalaroid.main_window import MainWindow  # noqa: E402
from softpalaroid.render import save_sheet  # noqa: E402
from softpalaroid.theme import apply_theme  # noqa: E402


def _stage(name: str) -> None:
    print(f"[smoke] {name}", flush=True)


def main() -> None:
    _stage("QApplication + theme + MainWindow")
    app = QApplication(sys.argv)
    apply_theme(app)
    families = QFontDatabase.families()
    print("[smoke] Inter registered:", any(f.startswith("Inter") for f in families),
          "| Caveat registered:", any(f.startswith("Caveat") for f in families),
          "| app font:", app.font().family(), flush=True)
    assert any(f.startswith("Inter") for f in families), "Inter font not registered"
    assert any(f.startswith("Caveat") for f in families), "Caveat font not registered"
    win = MainWindow()
    win._skip_unsaved_prompt = True  # noqa: SLF001 - headless-тест без диалогов
    win.show()
    _stage("window shown")

    with tempfile.TemporaryDirectory() as tmp:
        photo = os.path.join(tmp, "photo.jpg")
        img = Image.new("RGB", (1000, 800), (100, 150, 210))
        d = ImageDraw.Draw(img)
        d.ellipse([650, 80, 880, 310], fill=(250, 210, 110))
        d.rectangle([0, 560, 1000, 800], fill=(80, 150, 90))
        img.save(photo, quality=90)

        # Книжная ориентация, 4 снимка, одно фото на все слоты
        win.project.set_layout(4, landscape=False)
        win.canvas.on_layout_changed()
        assert win._load_photo_into(0, photo)  # noqa: SLF001
        win._duplicate_to_all()  # noqa: SLF001
        for i, item in enumerate(win.project.items):
            item.rotation = -3.0 + i * 2.0
            item.caption = f"Слот {i + 1}"
            item.filter = "vintage"
            win.canvas.refresh_item_pixmap(i)

        _stage("photos loaded, grab canvas")
        app.processEvents()
        grab = win.canvas.grab()  # прогнать paintEvent предпросмотра
        assert not grab.isNull(), "canvas grab is null"

        _stage("project save + undo/redo + reopen")
        project_file = os.path.join(tmp, "demo.softpalaroid")
        assert win._save_project_to(project_file)  # noqa: SLF001
        assert not win._is_dirty()  # noqa: SLF001
        original_caption = win.project.items[0].caption
        win.canvas.select(0)
        win._set_item(caption="Изменено", refresh_pixmap=False)  # noqa: SLF001
        win._undo()  # noqa: SLF001
        assert win.project.items[0].caption == original_caption
        win._redo()  # noqa: SLF001
        assert win.project.items[0].caption == "Изменено"
        assert win._open_project_from(  # noqa: SLF001
            project_file, confirm_discard=False)
        assert win.project.items[0].caption == original_caption
        assert not win._is_dirty()  # noqa: SLF001

        _stage("export sheet")
        out = os.path.join(tmp, "sheet.jpg")
        save_sheet(win.project, out)
        # with: файл обязательно закрыть, иначе Windows не удалит временную папку
        with Image.open(out) as result:
            result.load()
            assert result.size == (1181, 1772), result.size
            assert result.info.get("dpi") == (300, 300), result.info.get("dpi")
        _stage("export verified")

    win.close()
    app.quit()
    print("SMOKE OK")


if __name__ == "__main__":
    main()
