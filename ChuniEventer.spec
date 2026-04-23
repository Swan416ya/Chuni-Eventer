# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller：单文件 exe，控制台关闭（纯 GUI）。"""
import importlib.util
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve()
icon_file = ROOT / "assets" / "icon.ico"
icon_path = str(icon_file) if icon_file.exists() else None

block_cipher = None

datas = [
    (
        str(ROOT / "chuni_eventer_desktop" / "static"),
        "chuni_eventer_desktop/static",
    ),
    (
        str(ROOT / "chuni_eventer_desktop" / "data"),
        "chuni_eventer_desktop/data",
    ),
]
# 运行时用 LoadImage(ICO) 设置任务栏 HWND 图标；需与 app._app_icon_path 能找到的路径一致。
if icon_file.is_file():
    datas.append((str(icon_file), str(ROOT / "chuni_eventer_desktop" / "static" / "logo")))
binaries: list = []
hiddenimports: list = []

for pkg in ("PyQt6", "qfluentwidgets", "qframelesswindow", "quicktex", "PIL"):
    p_d, p_bin, p_hi = collect_all(pkg)
    datas += p_d
    binaries += p_bin
    hiddenimports += p_hi

# quicktex 的 BC3 编码依赖 site-packages 根目录下的 _quicktex*.pyd（与 quicktex/ 包并列），
# collect_all("quicktex") 不会带上该二进制；子进程 worker 也需能加载，故显式打入。
hiddenimports += ["_quicktex", "_quicktex._s3tc"]
_qt = importlib.util.find_spec("_quicktex")
if _qt is not None and _qt.origin:
    _pyd = Path(_qt.origin)
    if _pyd.is_file() and _pyd.suffix.lower() == ".pyd":
        binaries.append((str(_pyd), "."))

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
    icon=icon_path,
)
