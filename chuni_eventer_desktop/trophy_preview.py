from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap, QTextDocument, QTextOption

_STATIC_TROPHY_DIR = Path(__file__).resolve().parent / "static" / "trophy"

_TROPHY_FONT_FAMILIES = [
    "Yu Gothic UI",
    "Yu Gothic",
    "Meiryo UI",
    "MS UI Gothic",
    "Segoe UI",
    "Sans-serif",
]


def _fit_trophy_font_point_size(*, text: str, width_px: int, max_height_px: int) -> int:
    """在固定宽度换行前提下，取最大字号使文档总高度不超过 max_height_px（像素）。"""
    if width_px < 4 or max_height_px < 4:
        return 8
    font = QFont()
    font.setFamilies(_TROPHY_FONT_FAMILIES)
    lo, hi = 8, min(240, max(24, max_height_px * 3))
    best = 8
    while lo <= hi:
        mid = (lo + hi) // 2
        font.setPointSize(mid)
        doc = QTextDocument()
        doc.setDocumentMargin(0.0)
        doc.setDefaultFont(font)
        doc.setPlainText(text)
        opt = QTextOption()
        opt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        opt.setWrapMode(QTextOption.WrapMode.WordWrap)
        doc.setDefaultTextOption(opt)
        doc.setTextWidth(float(width_px))
        dh = int(doc.size().height()) + 1
        if 0 < dh <= max_height_px:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def trophy_static_frame_path(rare_type: int | None) -> Path | None:
    """`static/trophy/{rare}.png`，缺失时回退 `0.png`。"""
    r = 0 if rare_type is None else int(rare_type)
    cand = _STATIC_TROPHY_DIR / f"{r}.png"
    if cand.is_file():
        return cand
    fallback = _STATIC_TROPHY_DIR / "0.png"
    return fallback if fallback.is_file() else None


def load_trophy_frame_pixmap(rare_type: int | None) -> QPixmap | None:
    p = trophy_static_frame_path(rare_type)
    if p is None:
        return None
    pm = QPixmap(str(p))
    return None if pm.isNull() else pm


def render_trophy_text_preview(*, frame: QPixmap, display_name: str) -> QPixmap | None:
    """
    无图称号：稀有度条底图在下，显示名居中；文字块总高度不超过底图高度的 92%（自动换行并尽量放大字号）。
    """
    if frame.isNull() or frame.width() < 2 or frame.height() < 2:
        return None
    w, h = frame.width(), frame.height()
    out = QPixmap(w, h)
    out.fill(QColor(0, 0, 0, 0))
    painter = QPainter(out)
    if not painter.isActive():
        return None
    try:
        painter.drawPixmap(0, 0, frame)

        margin_x = min(max(6, int(w * 0.04)), w // 3)
        tw = max(1, w - 2 * margin_x)
        text_h = max(1, int(round(h * 0.92)))
        y0 = max(0, (h - text_h) // 2)
        text_rect = QRect(margin_x, y0, tw, text_h)

        name = display_name.strip() or "—"
        pt = _fit_trophy_font_point_size(text=name, width_px=tw, max_height_px=text_h)
        font = QFont()
        font.setFamilies(_TROPHY_FONT_FAMILIES)
        font.setPointSize(pt)
        painter.setFont(font)

        flags = int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap)

        painter.setPen(QColor(0, 0, 0))
        painter.drawText(text_rect, flags, name)
    finally:
        painter.end()
    return out
