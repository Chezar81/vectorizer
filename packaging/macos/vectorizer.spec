# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Vectorizer.app (run on macOS only)."""

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.osx import BUNDLE
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_all, collect_data_files

if sys.platform != "darwin":
    raise SystemExit("packaging/macos/vectorizer.spec must be built on macOS.")

ROOT = Path(SPECPATH).resolve().parents[1]
SRC = ROOT / "src"
ICON = Path(SPECPATH) / "Vectorizer.icns"
ENTRY = Path(SPECPATH) / "entry.py"

pyside_datas, pyside_binaries, pyside_hidden = collect_all("PySide6")
vtracer_datas, vtracer_binaries, vtracer_hidden = collect_all("vtracer")
package_datas = collect_data_files("vectorizer", includes=["py.typed", "resources/icons/*"])

datas = [
    *pyside_datas,
    *vtracer_datas,
    *package_datas,
]
binaries = [
    *pyside_binaries,
    *vtracer_binaries,
]
hiddenimports = [
    *pyside_hidden,
    *vtracer_hidden,
    "vectorizer",
    "vectorizer.cli",
    "vectorizer.jobs.trace_worker",
    "vectorizer.gui.app",
    "PIL._tkinter_finder",
]

a = Analysis(
    [str(ENTRY)],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PySide6.Qt3DCore", "PySide6.Qt3DRender"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Vectorizer",
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
    icon=str(ICON) if ICON.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Vectorizer",
)

app = BUNDLE(
    coll,
    name="Vectorizer.app",
    icon=str(ICON) if ICON.is_file() else None,
    bundle_identifier="com.christophrupprich.vectorizer",
    info_plist={
        "CFBundleName": "Vectorizer",
        "CFBundleDisplayName": "Vectorizer",
        "CFBundleShortVersionString": "0.4.0",
        "CFBundleVersion": "0.4.0",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
        "LSMinimumSystemVersion": "11.0",
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "Image",
                "CFBundleTypeRole": "Viewer",
                "LSItemContentTypes": [
                    "public.png",
                    "public.jpeg",
                    "public.tiff",
                    "com.compuserve.gif",
                    "org.webmproject.webp",
                    "com.microsoft.bmp",
                ],
            }
        ],
    },
)
