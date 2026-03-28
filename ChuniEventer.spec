# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller：单文件 exe，控制台关闭（纯 GUI）。"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve()

block_cipher = None

datas = [
    (
        str(ROOT / "chuni_eventer_desktop" / "static" / "trophy"),
        "chuni_eventer_desktop/static/trophy",
    ),
]
binaries: list = []
hiddenimports: list = []

for pkg in ("PyQt6", "qfluentwidgets", "qframelesswindow", "quicktex", "PIL"):
    p_d, p_bin, p_hi = collect_all(pkg)
    datas += p_d
    binaries += p_bin
    hiddenimports += p_hi

a = Analysis(
    [str(ROOT / "run_desktop.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ChuniEventer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
