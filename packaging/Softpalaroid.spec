# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller: сборка Softpalaroid.exe (one-dir, без консоли).

Запуск из корня репозитория:  pyinstaller packaging/Softpalaroid.spec --noconfirm
Результат: dist/Softpalaroid/Softpalaroid.exe
"""
import os

from PyInstaller.utils.hooks import collect_dynamic_libs

ROOT = os.path.dirname(SPECPATH)

# pillow-heif: нативный модуль и DLL libheif/libde265 должны попасть в сборку,
# иначе HEIC/HEIF не откроются именно в .exe (в исходниках всё работает).
heif_binaries = collect_dynamic_libs("pillow_heif")

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[os.path.join(ROOT, "src"), ROOT],
    binaries=heif_binaries,
    datas=[(os.path.join(ROOT, "assets"), "assets")],
    hiddenimports=["pillow_heif", "_pillow_heif"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Softpalaroid",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, "assets", "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Softpalaroid",
)
