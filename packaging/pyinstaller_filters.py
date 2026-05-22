"""PyInstaller Analysis 后处理：缩小 ChuniEventer.exe（S1 + S2）。"""

from __future__ import annotations

# --- S1: Analysis.excludes ---
PYQT6_UNUSED_MODULES = [
    "PyQt6.QtDesigner",
    "PyQt6.QtQuick",
    "PyQt6.QtQml",
    "PyQt6.QtMultimedia",
    "PyQt6.QtPdf",
    "PyQt6.QtSql",
    "PyQt6.QtBluetooth",
    "PyQt6.QtNfc",
    "PyQt6.QtDBus",
    "PyQt6.QtWebSockets",
    "PyQt6.QtSerialPort",
    "PyQt6.QtPositioning",
    "PyQt6.QtSensors",
    "PyQt6.QtTextToSpeech",
    "PyQt6.QtRemoteObjects",
    "PyQt6.QtWebChannel",
    "PyQt6.Qt3DCore",
    "PyQt6.Qt3DRender",
    "PyQt6.Qt3DInput",
    "PyQt6.Qt3DLogic",
    "PyQt6.Qt3DAnimation",
    "PyQt6.Qt3DExtras",
    "PyQt6.QtCharts",
    "PyQt6.QtDataVisualization",
    "PyQt6.QtGraphs",
    "PyQt6.QtGraphsWidgets",
    "PyQt6.QtHttpServer",
    "PyQt6.QtNetworkAuth",
    "PyQt6.QtOpenGLWidgets",
    "PyQt6.uic",
    "PyQt6.QtNetwork",
    "PyQt6.QtOpenGL",
    "PyQt6.QtPrintSupport",
    "PyQt6.QtHelp",
    "PyQt6.QtTest",
]

ANALYSIS_EXCLUDES = ["Pythonwin", "pywin.debugger"] + PYQT6_UNUSED_MODULES

# --- S2: 不再 collect_all(PyQt6)；由 Analysis + hook 按需拉取，并显式声明 ---
PYQT6_HIDDENIMPORTS = [
    "PyQt6.sip",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.QtSvg",
    "PyQt6.QtXml",  # qfluentwidgets.common.icon → QDomDocument
]

# Qt6/bin 白名单（Widgets + Svg + Windows 软件 OpenGL 回退）
QT6_BIN_ALLOW = {
    "qt6core.dll",
    "qt6gui.dll",
    "qt6widgets.dll",
    "qt6svg.dll",
    "qt6xml.dll",
    "opengl32sw.dll",
    "d3dcompiler_47.dll",
    "msvcp140.dll",
    "msvcp140_1.dll",
    "msvcp140_2.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "concrt140.dll",
}

# PyQt6 根目录 .pyd 白名单
PYQT6_PYD_ALLOW_NAMES = frozenset(
    {"QtCore.pyd", "QtGui.pyd", "QtWidgets.pyd", "QtSvg.pyd", "QtXml.pyd"}
)


def _pyqt6_pyd_allowed(name: str) -> bool:
    if name in PYQT6_PYD_ALLOW_NAMES:
        return True
    return name.startswith("sip.") and name.endswith(".pyd")

# plugins 子路径白名单（匹配 PyQt6/Qt6/plugins/<name>/...）
QT6_PLUGIN_ALLOW = (
    "platforms/qwindows.dll",
    "platforms/qminimal.dll",
    "imageformats/qjpeg.dll",
    "imageformats/qpng.dll",
    "imageformats/qgif.dll",
    "imageformats/qico.dll",
    "imageformats/qbmp.dll",
    "imageformats/qwebp.dll",
    "imageformats/qsvg.dll",
    "imageformats/qtga.dll",
    "imageformats/qtiff.dll",
    "styles/qmodernwindowsstyle.dll",
    "styles/qwindowsvistastyle.dll",
    "iconengines/qsvgicon.dll",
)

# datas：整树丢弃（collect_all 残留或 hook 误收）
QT6_DATA_DROP_PREFIXES = (
    "PyQt6/Qt6/qml/",
    "PyQt6/Qt6/translations/",
    "PyQt6/qsci/",
    "PyQt6/bindings/",
    "PyQt6/Qt6/lib/",
    "PyQt6/Qt6/metatypes/",
    "PyQt6/Qt6/modules/",
)


def _norm(path: str) -> str:
    return path.replace("\\", "/")


def _entry_src(entry: tuple) -> str:
    return _norm(str(entry[0]))


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _is_pyqt6_path(src: str) -> bool:
    return src.startswith("PyQt6/")


def _qt6_plugin_rel(src: str) -> str | None:
    marker = "PyQt6/Qt6/plugins/"
    if marker not in src:
        return None
    return src.split(marker, 1)[1].lower()


def _should_drop_binary(src: str) -> bool:
    low = src.lower()
    if "pythonwin" in low:
        return True
    if "_avif" in low and low.startswith("pil/"):
        return True
    if low.endswith("_avif.pyi"):
        return True

    if not _is_pyqt6_path(src):
        return False

    if "/Qt6/bin/" in src:
        return _basename(src).lower() not in QT6_BIN_ALLOW

    rel = _qt6_plugin_rel(src)
    if rel is not None:
        return rel not in QT6_PLUGIN_ALLOW

    if src.startswith("PyQt6/") and src.endswith(".pyd"):
        return not _pyqt6_pyd_allowed(_basename(src))

    if any(src.startswith(prefix) for prefix in QT6_DATA_DROP_PREFIXES):
        return True

    if "/Qt6/plugins/" in src:
        return True

    return False


def _should_drop_data(src: str) -> bool:
    if any(src.startswith(prefix) for prefix in QT6_DATA_DROP_PREFIXES):
        return True
    low = src.lower()
    if low.startswith("pil/") and "avifimageplugin" in low:
        return True
    if _is_pyqt6_path(src) and "/Qt6/plugins/" in src:
        rel = _qt6_plugin_rel(src)
        return rel is None or rel not in QT6_PLUGIN_ALLOW
    return False


def apply_exe_size_filters(analysis) -> object:
    """S1 + S2：在 Analysis 之后、PYZ 之前调用。"""
    analysis.binaries = [b for b in analysis.binaries if not _should_drop_binary(_entry_src(b))]
    analysis.datas = [d for d in analysis.datas if not _should_drop_data(_entry_src(d))]
    return analysis
