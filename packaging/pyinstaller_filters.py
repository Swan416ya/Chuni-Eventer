"""PyInstaller Analysis 后处理：缩小 ChuniEventer.exe（S1 + Qt6 二进制裁剪）。"""

from __future__ import annotations

# S1-a: Analysis excludes（spec 中引用）
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
]

ANALYSIS_EXCLUDES = ["Pythonwin", "pywin.debugger"] + PYQT6_UNUSED_MODULES

# S2: Qt6 运行时未使用的 DLL / plugins / QML（业务仅用 Widgets + Svg）
QT6_DROP_PATH_PARTS = (
    "PyQt6/Qt6/bin/Qt6Designer",
    "PyQt6/Qt6/bin/Qt6Quick",
    "PyQt6/Qt6/bin/Qt6Qml",
    "PyQt6/Qt6/bin/Qt6Pdf",
    "PyQt6/Qt6/bin/Qt6Multimedia",
    "PyQt6/Qt6/bin/avcodec-",
    "PyQt6/Qt6/bin/avformat-",
    "PyQt6/Qt6/bin/avutil-",
    "PyQt6/Qt6/bin/Qt6Quick3D",
    "PyQt6/Qt6/bin/Qt6ShaderTools",
    "PyQt6/Qt6/qml/",
    "PyQt6/Qt6/plugins/sqldrivers/",
    "PyQt6/Qt6/plugins/assetimporters/",
    "PyQt6/Qt6/plugins/sceneparsers/",
    "PyQt6/Qt6/plugins/multimedia/",
    "PyQt6/Qt6/plugins/qmlls/",
    "PyQt6/Qt6/plugins/qmllint/",
    "PyQt6/Qt6/plugins/texttospeech/",
    "PyQt6/Qt6/plugins/sensors/",
    "PyQt6/Qt6/plugins/geometryloaders/",
    "PyQt6/Qt6/plugins/scxmldatamodel/",
    "PyQt6/Qt6/plugins/webview/",
    "PyQt6/bindings/",
)

# 未 import 的 PyQt6 .pyd（保留 QtCore/QtGui/QtWidgets/QtSvg/sip）
PYQT6_DROP_PYD_NAMES = {
    "QtDesigner.pyd",
    "QtQuick.pyd",
    "QtQml.pyd",
    "QtMultimedia.pyd",
    "QtPdf.pyd",
    "QtSql.pyd",
    "QtBluetooth.pyd",
    "QtNfc.pyd",
    "QtDBus.pyd",
    "QtWebSockets.pyd",
    "QtSerialPort.pyd",
    "QtPositioning.pyd",
    "QtSensors.pyd",
    "QtTextToSpeech.pyd",
    "QtRemoteObjects.pyd",
    "QtWebChannel.pyd",
    "QtPdfWidgets.pyd",
    "QtMultimediaWidgets.pyd",
    "QtQuickWidgets.pyd",
    "QtQuick3D.pyd",
    "QtOpenGLWidgets.pyd",
    "QAxContainer.pyd",
    "QtHelp.pyd",
    "QtPrintSupport.pyd",
    "QtStateMachine.pyd",
    "QtTest.pyd",
    "QtXml.pyd",
    "QtSpatialAudio.pyd",
    "QtSvgWidgets.pyd",
    # QtOpenGL.pyd / QtNetwork.pyd：qfluentwidgets 可能间接用到，暂保留
}


def _norm(path: str) -> str:
    return path.replace("\\", "/")


def _entry_src(entry: tuple) -> str:
    return _norm(str(entry[0]))


def _should_drop_binary(src: str) -> bool:
    low = src.lower()
    if "pythonwin" in low:
        return True
    if "_avif" in low and low.startswith("pil/"):
        return True
    if low.endswith("_avif.pyi"):
        return True
    name = src.rsplit("/", 1)[-1]
    if name in PYQT6_DROP_PYD_NAMES:
        return True
    return any(part in src for part in QT6_DROP_PATH_PARTS)


def _should_drop_data(src: str) -> bool:
    if "/bindings/" in src or "PyQt6/bindings/" in src:
        return True
    low = src.lower()
    return low.startswith("pil/") and "avifimageplugin" in low


def apply_exe_size_filters(analysis) -> object:
    """S1-b/c + Qt6 二进制裁剪。在 Analysis 之后、PYZ 之前调用。"""
    analysis.binaries = [b for b in analysis.binaries if not _should_drop_binary(_entry_src(b))]
    analysis.datas = [d for d in analysis.datas if not _should_drop_data(_entry_src(d))]
    return analysis
