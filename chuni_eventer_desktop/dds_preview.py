from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

from .acus_workspace import app_cache_dir
from .dds_convert import DdsToolError, convert_dds_to_png
from .dds_quicktex import quicktex_available


def preview_cache_dir(acus_root: Path) -> Path:
    # 保留 acus_root 参数以兼容调用方签名；缓存位置统一在应用根目录
    _ = acus_root
    return app_cache_dir() / "dds_preview"


def dds_to_pixmap(
    *,
    acus_root: Path,
    compressonatorcli_path: Path | None,
    dds_path: Path,
    max_w: int = 320,
    max_h: int = 320,
) -> QPixmap | None:
    """
    Convert DDS -> PNG (cached) -> QPixmap for UI display.
    优先 quicktex；否则使用已配置的 compressonatorcli。
    """
    if not dds_path.exists():
        return None

    cache = preview_cache_dir(acus_root)
    cache.mkdir(parents=True, exist_ok=True)
    png_path = cache / (dds_path.name + ".png")

    if not png_path.exists():
        if compressonatorcli_path is None and not quicktex_available():
            return None
        try:
            convert_dds_to_png(tool_path=compressonatorcli_path, input_dds=dds_path, output_png=png_path)
        except (DdsToolError, OSError, PermissionError):
            return None

    pm = QPixmap(str(png_path))
    if pm.isNull():
        return None
    return pm.scaled(max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

