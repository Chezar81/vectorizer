# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Linux onedir tree used by the .deb."""

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_all, collect_data_files

if sys.platform != "linux":
    raise SystemExit("packaging/linux/vectorizer.spec must be built on Linux.")

ROOT = Path(SPECPATH).resolve().parents[1]
SRC = ROOT / "src"
ENTRY = Path(SPECPATH) / "entry.py"

pyside_datas, pyside_binaries, pyside_hidden = collect_all("PySide6")
vtracer_datas, vtracer_binaries, vtracer_hidden = collect_all("vtracer")
package_datas = collect_data_files("vectorizer", includes=["py.typed", "resources/icons/*"])

a = Analysis(
    [str(ENTRY)],
    pathex=[str(SRC)],
    binaries=[*pyside_binaries, *vtracer_binaries],
    datas=[*pyside_datas, *vtracer_datas, *package_datas],
    hiddenimports=[
        *pyside_hidden,
        *vtracer_hidden,
        "vectorizer",
        "vectorizer.cli",
        "vectorizer.jobs.trace_worker",
        "vectorizer.gui.app",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="vectorizer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="vectorizer",
)
