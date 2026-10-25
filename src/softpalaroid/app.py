"""Точка входа приложения."""
from __future__ import annotations

import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import APP_NAME
from .main_window import MainWindow


def _icon_path() -> str | None:
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "assets", "icon.png"))
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(here, "..", "..", "assets", "icon.png"))
    for path in candidates:
        if os.path.exists(path):
            return os.path.normpath(path)
    return None


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setStyle("Fusion")
    icon = _icon_path()
    if icon:
        app.setWindowIcon(QIcon(icon))

    window = MainWindow()
    if icon:
        window.setWindowIcon(QIcon(icon))
    # Фото, переданное первым аргументом командной строки, открывается в слот 1
    args = app.arguments()[1:]
    if args and os.path.isfile(args[0]):
        window._load_photo_into(0, args[0])  # noqa: SLF001
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
