"""GUI smoke-тест для CI: запуск окна, загрузка JFIF, проект, экспорт листа.

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
from PySide6.QtGui import QFontDatabase, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from softpalaroid.main_window import IMAGE_FILTER, MainWindow  # noqa: E402
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
    assert "*.jfif" in IMAGE_FILTER and "*.heic" in IMAGE_FILTER, IMAGE_FILTER
    assert "*.dng" in IMAGE_FILTER and "*.cr2" in IMAGE_FILTER, IMAGE_FILTER
    win = MainWindow()
    win._skip_unsaved_prompt = True  # noqa: SLF001 - headless-тест без диалогов
    win.show()
    _stage("window shown")

    with tempfile.TemporaryDirectory() as tmp:
        photo = os.path.join(tmp, "photo.jfif")
        img = Image.new("RGB", (1000, 800), (100, 150, 210))
        d = ImageDraw.Draw(img)
        d.ellipse([650, 80, 880, 310], fill=(250, 210, 110))
        d.rectangle([0, 560, 1000, 800], fill=(80, 150, 90))
        img.save(photo, quality=90)

        # Произвольное количество: 3 не является пресетом.
        win._count_changed(3)  # noqa: SLF001
        assert win.count_spin.value() == 3
        assert not any(b.isChecked() for b in win.count_buttons.values())

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

        _stage("paper / card format / template / safe area")
        paper_idx = win.paper_combo.findData("a4")
        assert paper_idx >= 0
        win.paper_combo.setCurrentIndex(paper_idx)
        assert win.project.paper_size == "a4"
        assert (win.project.sheet_w, win.project.sheet_h) == (2480, 3508)
        format_idx = win.card_format_combo.findData("instax_wide")
        assert format_idx >= 0
        win.card_format_combo.setCurrentIndex(format_idx)
        assert win.project.card_format == "instax_wide"
        assert all(item.card_format == "instax_wide"
                   for item in win.project.items)
        template_idx = win.template_combo.findData("warm_film")
        assert template_idx >= 0
        win.template_combo.setCurrentIndex(template_idx)
        win._apply_template()  # noqa: SLF001
        assert win.project.template == "warm_film"
        win.safe_margin_spin.setValue(8.5)
        win.show_safe_button.setChecked(False)
        win.snap_button.setChecked(False)
        assert win.project.safe_margin_mm == 8.5
        assert not win.project.show_safe_area
        assert not win.project.snap_enabled

        win.canvas.select(0)
        win._set_background_color("#f6efe5")  # noqa: SLF001
        win._set_frame_color("#fff2cf")  # noqa: SLF001
        win._rotate_photo(90)  # noqa: SLF001
        assert win.project.cut_marks
        win._set_item(  # noqa: SLF001
            caption="Лето\n2026",
            filter_intensity=0.65,
            brightness=1.12,
            contrast=1.05,
            saturation=1.08,
            sharpness=1.15,
            caption_scale=1.2,
            caption_color="#203040",
            caption_align="left",
        )
        win._copy_card_style()  # noqa: SLF001
        win.canvas.select(2)
        win._paste_card_style()  # noqa: SLF001
        assert win.project.items[2].brightness == 1.12
        assert win.project.items[2].caption_color == "#203040"

        clipboard_image = QImage(320, 240, QImage.Format.Format_RGB32)
        clipboard_image.fill(0xFF336699)
        app.clipboard().setImage(clipboard_image)
        win._paste_photo_from_clipboard(1)  # noqa: SLF001
        assert win.project.items[1].photo_size == (320, 240)
        win.canvas.select(0)

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
        assert win.project.background_color == "#f6efe5"
        assert win.project.items[0].frame_color == "#fff2cf"
        assert win.project.items[0].photo_rotation == 90
        assert win.project.paper_size == "a4"
        assert win.project.sheet_size_cm == (21.0, 29.7)
        assert win.project.card_format == "instax_wide"
        assert win.project.template == "warm_film"
        assert win.project.safe_margin_mm == 8.5
        assert not win.project.show_safe_area
        assert not win.project.snap_enabled
        assert win.project.items[0].caption == "Лето\n2026"
        assert win.project.items[0].brightness == 1.12
        assert win.project.items[0].caption_align == "left"
        assert win.project.items[1].photo_size == (320, 240)
        assert "Проверка макета" in win.preflight_label.text()
        assert not win._is_dirty()  # noqa: SLF001

        _stage("return to classic 10x15 for final export")
        paper_idx = win.paper_combo.findData("10x15")
        assert paper_idx >= 0
        win.paper_combo.setCurrentIndex(paper_idx)
        format_idx = win.card_format_combo.findData("classic")
        assert format_idx >= 0
        win.card_format_combo.setCurrentIndex(format_idx)
        assert (win.project.sheet_w, win.project.sheet_h) == (1181, 1772)

        _stage("free cards add/duplicate/delete/layer")
        win._add_card()  # noqa: SLF001
        assert len(win.project.items) == 5
        win._duplicate_card()  # noqa: SLF001
        assert len(win.project.items) == 6
        win._delete_card()  # noqa: SLF001
        assert len(win.project.items) == 5
        win._count_changed(4)  # noqa: SLF001
        assert len(win.project.items) == 4
        win.canvas.select(0)
        moved_caption = win.project.items[0].caption
        win._move_card_to_layer(front=True)  # noqa: SLF001
        assert win.project.items[-1].caption == moved_caption

        _stage("export sheet")
        out = os.path.join(tmp, "sheet.jpg")
        save_sheet(win.project, out)
        # with: файл обязательно закрыть, иначе Windows не удалит временную папку
        with Image.open(out) as result:
            result.load()
            assert result.size == (1181, 1772), result.size
            assert result.info.get("dpi") == (300, 300), result.info.get("dpi")
        pdf_out = os.path.join(tmp, "sheet.pdf")
        save_sheet(win.project, pdf_out)
        with open(pdf_out, "rb") as pdf_file:
            assert pdf_file.read(4) == b"%PDF"
        _stage("export verified")

    win.close()
    app.quit()
    print("SMOKE OK")


if __name__ == "__main__":
    main()
