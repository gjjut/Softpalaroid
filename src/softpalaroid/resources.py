"""Доступ к ресурсам из папки assets (исходники и собранный PyInstaller exe)."""
from __future__ import annotations

import os
import sys


def asset_path(*parts: str) -> str | None:
    """Абсолютный путь к файлу в assets или None, если не найден."""
    candidates: list[str] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "assets", *parts))
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(here, "..", "..", "assets", *parts))
    candidates.append(os.path.join(os.getcwd(), "assets", *parts))
    for path in candidates:
        if os.path.exists(path):
            return os.path.normpath(path)
    return None
