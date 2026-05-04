from __future__ import annotations

import tempfile
from pathlib import Path

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QImage, QMouseEvent, QPainter, QPixmap, QWheelEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import BodyLabel, CardWidget, PrimaryPushButton, PushButton

from ..dds_convert import DdsToolError, convert_to_bc3_dds
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical

CANVAS_W = 400
CANVAS_H = 256


def _static_sysvoice_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "static" / "tool" / "sysvoice"


class SysvoiceComposeWidget(QWidget):
    """400×256：底 back、中立绘（可拖）、顶 front。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(CANVAS_W, CANVAS_H)
        self._back = QPixmap(str(_static_sysvoice_dir() / "back.png"))
        self._front = QPixmap(str(_static_sysvoice_dir() / "front.png"))
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
        self._scale = max(0.15, min(3.0, float(s)))
        self.update()

    def scale(self) -> float:
        return self._scale

    def has_portrait(self) -> bool:
        return not self._mid.isNull()

    def _fit_default_position(self) -> None:
        if self._mid.isNull():
            return
        sw, sh = CANVAS_W, CANVAS_H
        iw, ih = self._mid.width(), self._mid.height()
        base = min(sw / max(iw, 1), sh / max(ih, 1)) * 0.85
        self._scale = float(max(0.2, min(1.2, base)))
        w = iw * self._scale
        h = ih * self._scale
        self._ox = (sw - w) / 2
        self._oy = (sh - h) / 2

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
                w,
                h,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.drawPixmap(int(self._ox), int(self._oy), scaled)
        if not self._front.isNull():
            p.drawPixmap(0, 0, self._front)
        p.end()
        return out

    def paintEvent(self, _e) -> None:
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


class SysvoicePreviewDialog(FluentCaptionDialog):
    """合成预览并导出 BC3 DDS（400×256）。"""

    def __init__(self, *, tool_path: Path | None, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("系统语音预览图")
        self.setModal(True)
        self.resize(520, 420)
        self._tool = tool_path
        self.result_dds_path: Path | None = None

        hint = BodyLabel(
            "底层为工具内置 back.png，顶层为 front.png；中间层为自选立绘。"
            " 在画面上拖动调整位置，滚轮缩放。输出 400×256 BC3 DDS。",
            self,
        )
        hint.setWordWrap(True)
        hint.setTextColor("#6B7280", "#9CA3AF")

        self._canvas = SysvoiceComposeWidget(self)
        self._scale_slider = QSlider(Qt.Orientation.Horizontal, self)
        self._scale_slider.setRange(15, 300)
        self._scale_slider.setValue(100)
        self._scale_slider.valueChanged.connect(self._on_slider)

        pick = PushButton("选择立绘…", self)
        pick.clicked.connect(self._on_pick)
        gen = PrimaryPushButton("生成 DDS…", self)
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

    def _on_slider(self, v: int) -> None:
        self._canvas.set_scale(v / 100.0)
        self._canvas.update()

    def _on_pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择立绘",
            "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*.*)",
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
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存预览 DDS",
            "systemvoice_preview.dds",
            "DDS (*.dds)",
        )
        if not path:
            return
        out = Path(path).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix="sysvoice_png_") as td:
                png = Path(td) / "compose.png"
                if not img.save(str(png), "PNG"):
                    raise RuntimeError("无法写入临时 PNG。")
                convert_to_bc3_dds(tool_path=self._tool, input_image=png, output_dds=out)
        except (DdsToolError, OSError, RuntimeError) as e:
            fly_critical(self, "DDS 失败", str(e))
            return
        self.result_dds_path = out
        self.accept()
