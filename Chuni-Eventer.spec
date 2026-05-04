# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

project_root = Path(__file__).resolve().parent
main_file = project_root / "chuni_eventer_desktop" / "__main__.py"

# 可选：放一个 icon.ico 到 desktop/assets/icon.ico
icon_file = project_root / "assets" / "icon.ico"
icon_path = str(icon_file) if icon_file.exists() else None

block_cipher = None

a = Analysis(
    [str(main_file)],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "PyCriCodecsEx.acb",
        "PyCriCodecsEx.awb",
        "PyCriCodecsEx.hca",
        "PyCriCodecsEx.chunk",
    ],
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
    name="Chuni-Eventer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)
