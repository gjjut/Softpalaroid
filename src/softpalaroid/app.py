"""Точка входа приложения."""
from __future__ import annotations

import os
import sys
import traceback

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import APP_NAME
from .main_window import MainWindow
from .resources import asset_path
from .theme import apply_theme


def _run_self_test(argv: list[str]) -> int:
    """Невидимая проверка ядра и кодеков, в том числе внутри PyInstaller exe."""
    output_path: str | None = None
    if "--self-test" in argv:
        idx = argv.index("--self-test")
        if idx + 1 < len(argv) and not argv[idx + 1].startswith("-"):
            output_path = argv[idx + 1]

    lines: list[str] = []
    status = 0
    try:
        import tempfile
        from pathlib import Path

        from . import __version__
        from .image_io import rawpy_available, supported_image_extensions
        from .model import Project
        from .render import save_sheet

        extensions = set(supported_image_extensions())
        required = {".jpg", ".jpeg", ".jfif", ".png"}
        missing = sorted(required - extensions)
        if missing:
            raise RuntimeError(f"Missing image extensions: {missing}")
        if not rawpy_available():
            raise RuntimeError("rawpy/LibRaw is not available")
        if ".dng" not in extensions:
            raise RuntimeError("RAW extensions are not advertised")

        project = Project()
        project.set_paper_size("a4", landscape=True)
        project.set_card_format("instax_wide", relayout=True)
        project.safe_margin_mm = 7.0
        project.clamp_settings()
        with tempfile.TemporaryDirectory(prefix="softpalaroid-selftest-") as tmp:
            pdf_path = Path(tmp) / "self-test.pdf"
            jpg_path = Path(tmp) / "self-test.jpg"
            save_sheet(project, str(pdf_path))
            save_sheet(project, str(jpg_path))
            if not pdf_path.read_bytes().startswith(b"%PDF"):
                raise RuntimeError("PDF export did not produce a PDF file")
            if jpg_path.stat().st_size < 100:
                raise RuntimeError("JPEG export produced an unexpectedly small file")
        lines.append(f"Softpalaroid {__version__} self-test OK")
        lines.append(f"supported extensions: {len(extensions)}")
        lines.append("rawpy: OK")
    except Exception:  # noqa: BLE001 - самотест возвращает код вместо GUI-ошибки
        status = 1
        lines.append("Softpalaroid self-test FAILED")
        lines.append(traceback.format_exc())
    text = "\n".join(lines) + "\n"
    if output_path:
        try:
            with open(output_path, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError:
            status = 1
    try:
        (sys.stderr if status else sys.stdout).write(text)
    except Exception:  # noqa: BLE001 - windowed exe может не иметь консоли
        pass
    return status


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv if argv is None else argv)
    if "--self-test" in raw_argv:
        return _run_self_test(raw_argv)

    app = QApplication(raw_argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    apply_theme(app)

    icon = asset_path("icon.png")
    if icon:
        app.setWindowIcon(QIcon(icon))

    window = MainWindow()
    if icon:
        window.setWindowIcon(QIcon(icon))

    # Аргументом может быть .softpalaroid (двойной клик в проводнике)
    # или одна/несколько фотографий.
    args = [arg for arg in app.arguments()[1:] if not arg.startswith("-")]
    file_args = [arg for arg in args if os.path.isfile(arg)]
    project_args = [
        arg for arg in file_args if arg.casefold().endswith(".softpalaroid")]
    photo_args = [arg for arg in file_args if arg not in project_args]
    loaded_cli_file = False
    if project_args:
        loaded_cli_file = window._open_project_from(  # noqa: SLF001
            project_args[0], confirm_discard=False)
    elif photo_args:
        loaded_cli_file = window._load_photo_paths(photo_args, 0) > 0  # noqa: SLF001

    window.show()
    if not loaded_cli_file:
        QTimer.singleShot(0, window.offer_autosave_recovery)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
