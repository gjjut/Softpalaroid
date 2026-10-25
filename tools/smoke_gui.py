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
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QFontDatabase, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from softpalaroid.filters import FILTERS  # noqa: E402
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

        _stage("UX galleries / accordions / slot strip / search")
        win.canvas.select(0)
        app.processEvents()
        assert win.panel_scroll.width() == 404
        assert set(win._section_cards) == {  # noqa: SLF001
            "sheet", "card", "caption", "style", "output", "hints"}

        sheet_card = win._section_cards["sheet"]  # noqa: SLF001
        sheet_was_expanded = sheet_card.is_expanded()
        sheet_card.set_expanded(not sheet_was_expanded)
        app.processEvents()
        assert sheet_card.is_expanded() is (not sheet_was_expanded)
        assert sheet_card.body.isVisible() is (not sheet_was_expanded)
        sheet_card.set_expanded(sheet_was_expanded)
        win._set_all_sections_expanded(False)  # noqa: SLF001
        assert not any(card.is_expanded()
                       for card in win._section_cards.values())  # noqa: SLF001
        win._set_all_sections_expanded(True)  # noqa: SLF001
        assert all(card.is_expanded()
                   for card in win._section_cards.values())  # noqa: SLF001

        assert len(win._slot_buttons) == len(win.project.items)  # noqa: SLF001
        assert not win._slot_buttons[0].icon().isNull()  # noqa: SLF001
        assert any(button.property("slotState") == "warning"
                   for button in win._slot_buttons)  # noqa: SLF001
        win._slot_buttons[2].click()  # noqa: SLF001
        app.processEvents()
        assert win._selected_index() == 2  # noqa: SLF001
        assert win._slot_buttons[2].isChecked()  # noqa: SLF001
        win._select_relative_card(1)  # noqa: SLF001
        assert win._selected_index() == 3  # noqa: SLF001
        win._select_relative_card(1)  # noqa: SLF001
        assert win._selected_index() == 0  # noqa: SLF001
        assert win.act_previous_card.shortcut().toString() == "Ctrl+Shift+Tab"
        assert win.act_next_card.shortcut().toString() == "Ctrl+Tab"
        assert win.act_search_panel.shortcut().toString() == "Ctrl+K"

        win.paper_gallery._activate("13x18")  # noqa: SLF001
        app.processEvents()
        assert win.project.paper_size == "13x18"
        assert win.paper_combo.currentData() == "13x18"
        assert win.paper_gallery.current_key() == "13x18"
        assert str(win._settings.value(  # noqa: SLF001
            "projectDefaults/paper_size")) == "13x18"

        win.format_gallery._activate("instax_square")  # noqa: SLF001
        app.processEvents()
        assert win.project.card_format == "instax_square"
        assert win.card_format_combo.currentData() == "instax_square"
        assert win.format_gallery.current_key() == "instax_square"

        win.template_gallery._activate("pastel")  # noqa: SLF001
        assert win.template_combo.currentData() == "pastel"
        assert win.project.template == "warm_film"  # выбор ещё не применён
        win._apply_template()  # noqa: SLF001
        assert win.project.template == "pastel"
        assert win.template_gallery.current_key() == "pastel"

        win.canvas.select(0)
        assert win.canvas.filter_base_image(0) is not None
        win._refresh_filter_gallery()  # noqa: SLF001
        assert len(win.filter_gallery._buttons) == len(FILTERS)  # noqa: SLF001
        assert win.filter_gallery.current_key() == win.project.items[0].filter
        win.filter_gallery._activate("bw")  # noqa: SLF001
        app.processEvents()
        assert win.project.items[0].filter == "bw"
        assert win.filter_combo.currentData() == "bw"
        assert win.filter_gallery.current_key() == "bw"

        win._set_all_sections_expanded(False)  # noqa: SLF001
        win.panel_search.setText("Цвет рамки")
        win._activate_search_result(win.panel_search.text())  # noqa: SLF001
        for _ in range(5):
            app.processEvents()
        assert win._section_cards["style"].is_expanded()  # noqa: SLF001
        assert win.focusWidget() is win.frame_color_button
        win.canvas.select(0)
        win._activate_search_result("Следующая")  # noqa: SLF001
        assert win._selected_index() == 1  # noqa: SLF001
        for key, expanded in {
                "sheet": True, "card": True, "caption": False,
                "style": False, "output": True, "hints": False}.items():
            win._section_cards[key].set_expanded(expanded)  # noqa: SLF001
        win.canvas.select(0)

        _stage("v0.8 theme / background styles / arrange / zoom toolbar")
        initial_theme = win._ui_theme  # noqa: SLF001
        win.theme_button.click()
        app.processEvents()
        flipped = "light" if initial_theme == "dark" else "dark"
        assert win._ui_theme == flipped  # noqa: SLF001
        assert win.canvas._ui_theme == flipped  # noqa: SLF001
        assert "Тема:" in win.theme_button.text()
        assert str(QSettings("Softpalaroid", "Softpalaroid").value(
            "ui/theme")) == flipped
        win.theme_button.click()
        app.processEvents()
        assert win._ui_theme == initial_theme  # noqa: SLF001
        assert str(QSettings("Softpalaroid", "Softpalaroid").value(
            "ui/theme")) == initial_theme

        win.background_gallery._activate("gradient")  # noqa: SLF001
        app.processEvents()
        assert win.project.background_style == "gradient"
        assert win.background_gallery.current_key() == "gradient"
        assert win.background2_button.isEnabled()
        win._set_background_color2("#123456")  # noqa: SLF001
        assert win.project.background_color2 == "#123456"
        win.background_gallery._activate("dots")  # noqa: SLF001
        assert win.project.background_style == "dots"
        win.background_gallery._activate("solid")  # noqa: SLF001
        app.processEvents()
        assert win.project.background_style == "solid"
        assert not win.background2_button.isEnabled()

        assert win.distribute_x_button.isEnabled()
        win.align_buttons["left"].click()
        app.processEvents()
        lefts = [item.bounds_sheet()[0] for item in win.project.items]
        assert max(lefts) - min(lefts) < 1.0, lefts
        win._arrange_cards("scatter")  # noqa: SLF001
        rotations = [abs(item.rotation) for item in win.project.items]
        assert max(rotations) <= 4.0 + 1e-6
        assert max(rotations) > 0.01
        win.straighten_button.click()
        app.processEvents()
        assert all(item.rotation == 0.0 for item in win.project.items)

        assert win.canvas._zoom_toolbar.isVisible()  # noqa: SLF001
        win.canvas.set_view_zoom(2.0)
        assert win.canvas._view_zoom == 2.0  # noqa: SLF001
        assert win.canvas._zoom_label.text() == "200%"  # noqa: SLF001
        win.canvas.zoom_step(0.5)
        assert win.canvas._view_zoom == 1.0  # noqa: SLF001
        win.canvas.set_view_zoom(99.0)
        assert win.canvas._view_zoom == 5.0  # noqa: SLF001
        win.canvas.reset_view()
        assert win.canvas._zoom_label.text() == "100%"  # noqa: SLF001

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
