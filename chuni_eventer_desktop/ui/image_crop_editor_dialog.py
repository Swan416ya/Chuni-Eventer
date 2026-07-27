"""通用图片缩放 + 裁剪编辑器对话框。

导入任意图片后，可滚轮缩放、拖拽平移图片，并用鼠标拖出一个锁定目标比例的选区
（支持四角/四边手柄调整、整体平移、外部重画），最终导出固定尺寸的 PNG。

供 ddsMap（1220×680 背景）与 MapIcon（256×256 小人）等场景复用。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPalette, QPen, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QSlider, QVBoxLayout, QWidget

from qfluentwidgets import BodyLabel, CardWidget, PrimaryPushButton, PushButton

from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical

# 选区手柄命中半径（屏幕像素）
_HANDLE_HIT_PX = 10
# 滚轮缩放因子（与现有编辑器一致）
_WHEEL_FACTOR = 1.08


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else (hi if v > hi else v)


class ImageCropCanvas(QWidget):
    """自绘画布：图片层（缩放/平移）+ 选区层（固定比例矩形，可拖拽调整）。"""

    def __init__(self, *, source_pixmap: QPixmap, aspect: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if source_pixmap.isNull():
            raise ValueError("源图为空")
        self._src = source_pixmap
        self._src_w = float(source_pixmap.width())
        self._src_h = float(source_pixmap.height())
        # 目标宽高比（w/h）
        self._aspect = float(aspect) if aspect > 0 else 1.0

        self.setMinimumSize(420, 320)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # 图片视图变换：源图像素 → 屏幕坐标
        self._zoom = 1.0  # 屏幕像素 / 源图像素
        self._ox = 0.0  # 屏幕原点对应的源图 x
        self._oy = 0.0  # 屏幕原点对应的源图 y

        # 选区（源图像素坐标）
        self._crop = self._default_crop()

        # 拖拽状态
        self._mode = "none"  # none | pan | move | resize
        self._handle = ""  # 角/边标识：nw n ne e se s sw w
        self._drag_start = QPointF()  # 鼠标按下时屏幕坐标
        self._drag_start_crop = (0.0, 0.0, 0.0, 0.0)  # 按下时选区（x,y,w,h 源图像素）

        self._first_show = True  # 首次显示时重新 fit（构造时尺寸尚未就绪）
        self._fit_to_view()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            self._fit_to_view()
            self.update()

    # ---- 公共接口 ----------------------------------------------------------

    @property
    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, z: float) -> None:
        # 以画布中心为锚点缩放，保持视觉中心稳定
        z = _clamp(float(z), 0.02, 40.0)
        if abs(self._zoom - z) < 1e-9:
            return
        cx_src = self._screen_to_src(QPointF(self.width() / 2.0, self.height() / 2.0))
        self._zoom = z
        cx_src2 = self._screen_to_src(QPointF(self.width() / 2.0, self.height() / 2.0))
        self._ox += cx_src.x() - cx_src2.x()
        self._oy += cx_src.y() - cx_src2.y()
        self.update()

    def fit_to_view(self) -> None:
        self._fit_to_view()
        self.update()

    def reset_crop(self) -> None:
        self._crop = self._default_crop()
        self.update()

    def render_cropped(self) -> QImage:
        """按当前选区裁剪：选区范围内的源图内容，超出源图部分补透明。"""
        x, y, w, h = self._crop
        iw = max(1, int(round(w)))
        ih = max(1, int(round(h)))
        # 透明画布，尺寸=选区尺寸；把源图按 (-x, -y) 偏移画上来
        out = QImage(iw, ih, QImage.Format.Format_ARGB32)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawPixmap(int(round(-x)), int(round(-y)), self._src)
        p.end()
        return out

    # ---- 坐标变换 ----------------------------------------------------------

    def _fit_to_view(self) -> None:
        """适应窗口：让「源图 ∪ 选区」的整体可见，选区超出图的部分也能看到。"""
        w = max(1, self.width())
        h = max(1, self.height())
        # bounding box = 源图与选区的并集
        cx, cy, cw, ch = self._crop
        bx0 = min(0.0, cx)
        by0 = min(0.0, cy)
        bx1 = max(self._src_w, cx + cw)
        by1 = max(self._src_h, cy + ch)
        bw = max(1.0, bx1 - bx0)
        bh = max(1.0, by1 - by0)
        zx = w / bw
        zy = h / bh
        self._zoom = _clamp(min(zx, zy) * 0.92, 0.02, 40.0)
        # 让 bounding box 居中
        self._ox = bx0 - (w / self._zoom - bw) / 2.0
        self._oy = by0 - (h / self._zoom - bh) / 2.0

    def _src_to_screen(self, p: QPointF) -> QPointF:
        return QPointF((p.x() - self._ox) * self._zoom, (p.y() - self._oy) * self._zoom)

    def _screen_to_src(self, p: QPointF) -> QPointF:
        return QPointF(p.x() / self._zoom + self._ox, p.y() / self._zoom + self._oy)

    # ---- 选区几何 ----------------------------------------------------------

    def _default_crop(self) -> tuple[float, float, float, float]:
        """默认选区：以源图居中，允许超出图边界（超出部分导出时补透明）。"""
        sw, sh = self._src_w, self._src_h
        if sw / sh > self._aspect:
            h = sh
            w = h * self._aspect
        else:
            w = sw
            h = w / self._aspect
        x = (sw - w) / 2.0
        y = (sh - h) / 2.0
        return (x, y, w, h)

    def _normalize_crop(self, c: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        """维持目标比例与最小尺寸；位置自由，允许超出源图边界。"""
        x, y, w, h = c
        # 维持目标比例（以较大的方向为准）
        if w / h > self._aspect:
            w = h * self._aspect
        else:
            h = w / self._aspect
        w = max(8.0, w)
        h = w / self._aspect
        return (x, y, w, h)

    def _handle_at(self, src_pt: QPointF) -> str:
        """返回 src_pt 所命中的手柄标识，未命中返回 ''。"""
        x, y, w, h = self._crop
        cx, cy = x + w / 2.0, y + h / 2.0
        # 把手柄中心转到屏幕坐标比较半径
        centers = {
            "nw": QPointF(x, y),
            "n": QPointF(cx, y),
            "ne": QPointF(x + w, y),
            "e": QPointF(x + w, cy),
            "se": QPointF(x + w, y + h),
            "s": QPointF(cx, y + h),
            "sw": QPointF(x, y + h),
            "w": QPointF(x, cy),
        }
        hit_r = _HANDLE_HIT_PX / self._zoom
        for k, c in centers.items():
            if (src_pt.x() - c.x()) ** 2 + (src_pt.y() - c.y()) ** 2 <= hit_r * hit_r:
                return k
        return ""

    def _point_in_crop(self, src_pt: QPointF) -> bool:
        x, y, w, h = self._crop
        return x <= src_pt.x() <= x + w and y <= src_pt.y() <= y + h

    # ---- 绘制 --------------------------------------------------------------

    def paintEvent(self, event) -> None:
        del event
        p = QPainter(self)
        p.fillRect(self.rect(), self.palette().color(QPalette.ColorRole.Window))
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # 图片层
        p.save()
        p.scale(self._zoom, self._zoom)
        p.translate(-self._ox, -self._oy)
        p.drawPixmap(0, 0, self._src)
        p.restore()

        # 源图实际边界（虚线框，提示图的范围，便于分辨图与选区超出部分）
        img_tl = self._src_to_screen(QPointF(0, 0))
        img_br = self._src_to_screen(QPointF(self._src_w, self._src_h))
        p.setPen(QPen(QColor(148, 163, 184, 200), 1, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(img_tl.x(), img_tl.y(),
                          img_br.x() - img_tl.x(), img_br.y() - img_tl.y()))

        # 棋盘格底（图外的透明区域显示棋盘，提示边界）
        # 这里简单用窗口色填充（已 fillRect），不额外画棋盘，保持简洁。

        # 遮罩：选区外压暗（用 QRectF 重载，因坐标为 float）
        x, y, w, h = self._crop
        tl = self._src_to_screen(QPointF(x, y))
        br = self._src_to_screen(QPointF(x + w, y + h))
        cx, cy, cw, ch = tl.x(), tl.y(), br.x() - tl.x(), br.y() - tl.y()
        mask = QColor(0, 0, 0, 130)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(mask)
        # 上、下、左、右四条
        p.drawRect(QRectF(0, 0, self.width(), max(0.0, cy)))
        p.drawRect(QRectF(0, cy + ch, self.width(), max(0.0, self.height() - (cy + ch))))
        p.drawRect(QRectF(0, cy, max(0.0, cx), ch))
        p.drawRect(QRectF(cx + cw, cy, max(0.0, self.width() - (cx + cw)), ch))

        # 选区边框
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(56, 189, 248, 220), 2))
        p.drawRect(QRectF(cx, cy, cw, ch))

        # 九宫格辅助线（三分法）
        p.setPen(QPen(QColor(255, 255, 255, 80), 1))
        for i in (1, 2):
            p.drawLine(QPointF(cx + cw * i / 3.0, cy),
                       QPointF(cx + cw * i / 3.0, cy + ch))
            p.drawLine(QPointF(cx, cy + ch * i / 3.0),
                       QPointF(cx + cw, cy + ch * i / 3.0))

        # 8 个手柄
        self._draw_handles(p, cx, cy, cw, ch)

    def _draw_handles(self, p: QPainter, cx: float, cy: float, cw: float, ch: float) -> None:
        centers = [
            (cx, cy), (cx + cw / 2.0, cy), (cx + cw, cy),
            (cx + cw, cy + ch / 2.0), (cx + cw, cy + ch),
            (cx + cw / 2.0, cy + ch), (cx, cy + ch), (cx, cy + ch / 2.0),
        ]
        p.setPen(QPen(QColor(15, 23, 42, 200), 1))
        p.setBrush(QColor(255, 255, 255, 230))
        hs = 5.0
        for hx, hy in centers:
            p.drawRect(QRectF(hx - hs, hy - hs, hs * 2, hs * 2))

    # ---- 鼠标交互 ----------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        # 中键 / 右键：平移图片
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self._mode = "pan"
            self._drag_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        pos = event.position()
        src = self._screen_to_src(pos)
        h = self._handle_at(src)
        self._drag_start = pos
        self._drag_start_crop = self._crop
        if h:
            self._mode = "resize"
            self._handle = h
        elif self._point_in_crop(src):
            self._mode = "move"
            self._handle = ""
        else:
            # 外部按下：以该点为左上角起一个默认大小的比例选区（允许超出图边界）
            self._mode = "resize"
            self._handle = "se"  # 之后向右下拖动扩展
            # 默认取源图短边的 80% 作为选区高度，按比例算宽度
            base = min(self._src_w, self._src_h) * 0.8
            h2 = max(8.0, base)
            w2 = h2 * self._aspect
            self._crop = self._normalize_crop((src.x(), src.y(), w2, h2))
            self._drag_start_crop = self._crop
            self.update()
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if self._mode == "none":
            # 仅更新鼠标光标提示
            src = self._screen_to_src(pos)
            h = self._handle_at(src)
            if h or self._point_in_crop(src):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.unsetCursor()
            super().mouseMoveEvent(event)
            return

        if self._mode == "pan":
            delta = pos - self._drag_start
            self._ox -= delta.x() / self._zoom
            self._oy -= delta.y() / self._zoom
            self._drag_start = pos
            self.update()
            event.accept()
            return

        src = self._screen_to_src(pos)
        x, y, w, h = self._drag_start_crop

        if self._mode == "move":
            # 整体平移选区，允许超出图边界。delta 用源图坐标算，单位一致。
            drag_start_src = self._screen_to_src(self._drag_start)
            dx = src.x() - drag_start_src.x()
            dy = src.y() - drag_start_src.y()
            self._crop = (x + dx, y + dy, w, h)
        elif self._mode == "resize":
            self._crop = self._resize_from_handle(self._handle, src, (x, y, w, h))
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.RightButton,
        ) and self._mode != "none":
            self._mode = "none"
            self._handle = ""
            self.unsetCursor()
        super().mouseReleaseEvent(event)

    def _resize_from_handle(self, handle: str, src: QPointF, start: tuple[float, float, float, float]
                            ) -> tuple[float, float, float, float]:
        sx, sy, sw, sh = start
        # 用鼠标位置定义新的对角点，按比例约束
        if handle in ("nw", "n", "ne"):
            top = src.y()
        else:
            top = sy
        if handle in ("sw", "s", "se"):
            bottom = src.y()
        else:
            bottom = sy + sh
        if handle in ("nw", "w", "sw"):
            left = src.x()
        else:
            left = sx
        if handle in ("ne", "e", "se"):
            right = src.x()
        else:
            right = sx + sw

        # 边中点手柄：固定对边，单方向拖动并按比例缩放另一方向
        if handle in ("n", "s"):
            left = sx
            right = sx + sw
        if handle in ("w", "e"):
            top = sy
            bottom = sy + sh

        raw_w = max(1.0, right - left)
        raw_h = max(1.0, bottom - top)
        # 按比例修正：以拖动主导方向为准
        if raw_w / raw_h > self._aspect:
            new_h = raw_h
            new_w = new_h * self._aspect
        else:
            new_w = raw_w
            new_h = new_w / self._aspect

        # 维持"固定角"不动（取决于 handle）
        if handle in ("nw", "w", "sw"):
            new_left = left + raw_w - new_w
        else:
            new_left = left
        if handle in ("nw", "n", "ne"):
            new_top = top + raw_h - new_h
        else:
            new_top = top

        return self._normalize_crop((new_left, new_top, new_w, new_h))

    def wheelEvent(self, event) -> None:
        d = event.angleDelta().y()
        if d == 0:
            return
        fac = _WHEEL_FACTOR if d > 0 else 1.0 / _WHEEL_FACTOR
        self.set_zoom(self._zoom * fac)
        event.accept()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)


class ImageCropEditorDialog(FluentCaptionDialog):
    """图片缩放 + 比例锁定选区裁剪编辑器。确认后输出临时 PNG。"""

    def __init__(
        self,
        *,
        source_path: Path,
        target_size: tuple[int, int],
        title: str = "裁剪图片",
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(900, 680)

        self._source_path = Path(source_path)
        self._target_w, self._target_h = int(target_size[0]), int(target_size[1])
        aspect = self._target_w / float(self._target_h)
        self.output_path: Path | None = None

        pm = QPixmap(str(self._source_path))
        if pm.isNull():
            raise ValueError(f"无法读取图片：{self._source_path}")
        self._canvas = ImageCropCanvas(source_pixmap=pm, aspect=aspect, parent=self)

        hint = BodyLabel(
            f"滚轮缩放图片，中键/右键拖动平移图片；左键拖拽选区调整裁剪范围（锁定 {self._target_w}:{self._target_h}），"
            "选区内拖动可平移选区，选区外点击可重画。确定后将按选区导出 "
            f"{self._target_w}×{self._target_h} PNG。",
            self,
        )
        hint.setWordWrap(True)
        hint.setTextColor("#6B7280", "#9CA3AF")

        self._zoom_slider = QSlider(Qt.Orientation.Horizontal, self)
        self._zoom_slider.setRange(2, 4000)
        self._zoom_slider.setValue(int(self._canvas.zoom * 100))
        self._zoom_slider.setToolTip("图片缩放（也可用鼠标滚轮）")
        self._zoom_slider.valueChanged.connect(self._on_zoom_slider)

        fit_btn = PushButton("适应窗口", self)
        fit_btn.clicked.connect(self._on_fit)
        reset_btn = PushButton("重置选区", self)
        reset_btn.clicked.connect(self._on_reset)

        ctrl = QHBoxLayout()
        ctrl.addWidget(BodyLabel("图片缩放", self))
        ctrl.addWidget(self._zoom_slider, stretch=1)
        ctrl.addWidget(fit_btn)
        ctrl.addWidget(reset_btn)

        card = CardWidget(self)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(8)
        cl.addWidget(hint)
        cl.addLayout(ctrl)
        cl.addWidget(self._canvas, stretch=1)

        ok = PrimaryPushButton("确定", self)
        ok.clicked.connect(self._on_accept)
        cancel = PushButton("取消", self)
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

        root = QVBoxLayout(self)
        root.setContentsMargins(*fluent_caption_content_margins())
        root.setSpacing(10)
        root.addWidget(card, stretch=1)
        root.addLayout(btns)

    # ---- 槽 ----------------------------------------------------------------

    def _on_zoom_slider(self, v: int) -> None:
        self._canvas.set_zoom(v / 100.0)

    def _on_fit(self) -> None:
        self._canvas.fit_to_view()
        self._zoom_slider.blockSignals(True)
        self._zoom_slider.setValue(int(self._canvas.zoom * 100))
        self._zoom_slider.blockSignals(False)

    def _on_reset(self) -> None:
        self._canvas.reset_crop()

    def _on_accept(self) -> None:
        try:
            img = self._canvas.render_cropped()
            # 缩放到目标尺寸
            scaled = img.scaled(
                self._target_w,
                self._target_h,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            tmp = tempfile.NamedTemporaryFile(
                suffix=".png", prefix="cropped_", delete=False
            )
            tmp.close()
            out = Path(tmp.name)
            if not scaled.save(str(out), "PNG"):
                raise ValueError("无法写出裁剪结果 PNG")
            self.output_path = out
        except Exception as e:
            fly_critical(self, "裁剪失败", str(e))
            return
        self.accept()
