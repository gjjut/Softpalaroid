"""Точка входа приложения."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import APP_NAME
from .main_window import MainWindow
from .resources import asset_path
from .theme import apply_theme


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
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
    # Фото, переданное первым аргументом командной строки, открывается в слот 1
    args = app.arguments()[1:]
    loaded_cli_photo = False
    if args and os.path.isfile(args[0]):
        loaded_cli_photo = window._load_photo_into(0, args[0])  # noqa: SLF001
    window.show()
    if not loaded_cli_photo:
        QTimer.singleShot(0, window.offer_autosave_recovery)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
