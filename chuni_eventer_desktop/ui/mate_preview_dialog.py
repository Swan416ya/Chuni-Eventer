"""伴侣预览图合成：400×256，back 斜纹框底 + 立绘（可拖/缩放）+ front Mate 标签。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QImage, QMouseEvent, QPainter, QPixmap, QWheelEvent
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from qfluentwidgets import BodyLabel, CardWidget, PrimaryPushButton, PushButton

from ..acus_workspace import acus_generated_dir
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical

CANVAS_W = 400
CANVAS_H = 256

# 立绘擦除带（自顶向下行号，从 1 计数）：白框底内沿以下全部擦掉，防止人物出框。
# 实测 frontframe.png 白框底内沿约 y=235（0-based），故从第 237 行起擦。
_MATE_TRANSPARENT_ROW_1_FIRST = 237
_MATE_TRANSPARENT_ROW_1_LAST = 256


def _transparent_band_rect_0based() -> tuple[int, int, int, int] | None:
    """返回 (x, y, w, h)：仅用于中立绘层擦除；行号从 1 计数。"""
    y0 = _MATE_TRANSPARENT_ROW_1_FIRST - 1
    y1 = _MATE_TRANSPARENT_ROW_1_LAST - 1
    if y0 >= CANVAS_H:
        return None
    y0 = max(0, y0)
    y1 = min(y1, CANVAS_H - 1)
    if y1 < y0:
        return None
    return (0, y0, CANVAS_W, y1 - y0 + 1)


def _static_mate_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "static" / "tool" / "mate"


class MateComposeWidget(QWidget):
    """400×256：底 background（卡片）、中立绘（可拖，底部擦除）、顶 frontframe（白框+标签）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(CANVAS_W, CANVAS_H)
        self._back = QPixmap(str(_static_mate_dir() / "background.png"))
        self._front = QPixmap(str(_static_mate_dir() / "frontframe.png"))
        self._mid = QPixmap()
        self._ox = 0.0
        self._oy = 0.0
        self._scale = 1.0
        self._drag_from: QPoint | None = None
        self.setMouseTracking(True)

    def clear_portrait(self) -> None:
        self._mid = QPixmap()
        self._ox = 0.0
        self._oy = 0.0
        self._scale = 1.0
        self.update()

    def load_portrait(self, path: Path) -> None:
        pm = QPixmap(str(path))
        if pm.isNull():
            raise ValueError("无法读取立绘图片。")
        self._mid = pm
        self._fit_default_position()
        self.update()

    def set_scale(self, s: float) -> None:
        self._scale = max(0.15, min(4.0, float(s)))
        self.update()

    def scale(self) -> float:
        return self._scale

    def has_portrait(self) -> bool:
        return not self._mid.isNull()

    def _fit_default_position(self) -> None:
        if self._mid.isNull():
            return
        iw, ih = self._mid.width(), self._mid.height()
        base = min(CANVAS_W / max(iw, 1), CANVAS_H / max(ih, 1)) * 0.85
        self._scale = float(max(0.2, min(1.5, base)))
        w = iw * self._scale
        h = ih * self._scale
        self._ox = (CANVAS_W - w) / 2
        self._oy = (CANVAS_H - h) / 2
        self.update()

    def render_composite(self) -> QImage:
        out = QImage(CANVAS_W, CANVAS_H, QImage.Format.Format_ARGB32)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if not self._back.isNull():
            p.drawPixmap(0, 0, self._back)
        if not self._mid.isNull():
            iw, ih = self._mid.width(), self._mid.height()
            w = int(iw * self._scale)
            h = int(ih * self._scale)
            scaled = self._mid.scaled(
                w, h,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            mid_layer = QImage(CANVAS_W, CANVAS_H, QImage.Format.Format_ARGB32)
            mid_layer.fill(Qt.GlobalColor.transparent)
            pmid = QPainter(mid_layer)
            pmid.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            pmid.drawPixmap(int(self._ox), int(self._oy), scaled)
            pmid.end()
            band = _transparent_band_rect_0based()
            if band is not None:
                bx, by, bw, bh = band
                pm2 = QPainter(mid_layer)
                pm2.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                pm2.fillRect(bx, by, bw, bh, Qt.GlobalColor.transparent)
                pm2.end()
            p.drawImage(0, 0, mid_layer)
        if not self._front.isNull():
            p.drawPixmap(0, 0, self._front)
        p.end()
        return out

    def paintEvent(self, _e) -> None:  # noqa: N802
        pm = QPixmap.fromImage(self.render_composite())
        p = QPainter(self)
        p.drawPixmap(0, 0, pm)
        p.end()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_from = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag_from is not None and not self._mid.isNull():
            cur = e.position().toPoint()
            d = cur - self._drag_from
            self._drag_from = cur
            self._ox += d.x()
            self._oy += d.y()
            self.update()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_from = None
        super().mouseReleaseEvent(e)

    def wheelEvent(self, e: QWheelEvent) -> None:
        if self._mid.isNull():
            return
        delta = e.angleDelta().y()
        if delta == 0:
            return
        factor = 1.08 if delta > 0 else 1 / 1.08
        self.set_scale(self._scale * factor)
        self.update()
        e.accept()


class MatePreviewDialog(FluentCaptionDialog):
    """合成 400×256 伴侣预览并导出 PNG；写入 ACUS 时再统一转 BC3 DDS。"""

    def __init__(self, *, acus_root: Path | None = None, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("伴侣预览图")
        self.setModal(True)
        self.resize(520, 460)
        self._acus_root = acus_root
        self.result_png_path: Path | None = None

        hint = BodyLabel(
            "底层为卡片背景（background），中间为立绘（拖动摆位、滚轮缩放），最上层为白框与标签（frontframe）。"
            "立绘在白框底边以下的部分会被自动擦除（防止出框），与系统语音预览图同一套拼接逻辑。"
            "生成 PNG 后在生成伴侣时自动转 BC3 写入 mate 目录。",
            self,
        )
        hint.setWordWrap(True)
        hint.setTextColor("#6B7280", "#9CA3AF")

        self._canvas = MateComposeWidget(self)
        self._scale_slider = QSlider(Qt.Orientation.Horizontal, self)
        self._scale_slider.setRange(15, 400)
        self._scale_slider.setValue(100)
        self._scale_slider.valueChanged.connect(
            lambda v: self._canvas.set_scale(v / 100.0))

        pick = PushButton("选择立绘…", self)
        pick.clicked.connect(self._on_pick)
        gen = PrimaryPushButton("生成 PNG…", self)
        gen.clicked.connect(self._on_generate)
        cancel = PushButton("关闭", self)
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(pick)
        row.addWidget(QLabel("缩放", self))
        row.addWidget(self._scale_slider, stretch=1)
        row.addWidget(cancel)
        row.addWidget(gen)

        card = CardWidget(self)
        cly = QVBoxLayout(card)
        cly.setContentsMargins(16, 14, 16, 14)
        cly.setSpacing(10)
        cly.addWidget(hint)
        cly.addWidget(self._canvas, alignment=Qt.AlignmentFlag.AlignCenter)
        cly.addLayout(row)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*fluent_caption_content_margins())
        lay.setSpacing(10)
        lay.addWidget(card, stretch=1)

    def _on_pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择立绘", "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp *.dds);;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            self._canvas.load_portrait(Path(path).expanduser())
            self._scale_slider.blockSignals(True)
            self._scale_slider.setValue(int(self._canvas.scale() * 100))
            self._scale_slider.blockSignals(False)
        except ValueError as e:
            fly_critical(self, "错误", str(e))

    def _on_generate(self) -> None:
        if not self._canvas.has_portrait():
            fly_critical(self, "错误", "请先选择立绘。")
            return
        img = self._canvas.render_composite()
        if img.isNull():
            fly_critical(self, "错误", "合成失败。")
            return
        if self._acus_root is not None:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            out = acus_generated_dir(self._acus_root, "mate_compose", f"compose_{stamp}.png")
        else:
            path, _ = QFileDialog.getSaveFileName(self, "保存预览 PNG", "mate_preview.png", "PNG (*.png)")
            if not path:
                return
            out = Path(path).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        if not img.save(str(out), "PNG"):
            fly_critical(self, "错误", "无法写入 PNG。")
            return
        self.result_png_path = out
        self.accept()
