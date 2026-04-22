from __future__ import annotations

from datetime import datetime
from pathlib import Path
import time

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPainter, QPixmap
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QVBoxLayout

from qfluentwidgets import BodyLabel, CardWidget, PrimaryPushButton, PushButton

from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical

TROPHY_TITLE_W = 608
TROPHY_TITLE_H = 148
TROPHY_SHORT_H = 80


def _static_trophy_template_path() -> Path:
    return Path(__file__).resolve().parent.parent / "static" / "tool" / "trophy.png"


def compose_trophy_title_image(*, user_image: QImage | QPixmap, template_path: Path | None = None) -> QImage:
    """
    将用户图与 static/tool/trophy.png 叠合成 608×148。
    - 用户图须宽 608，高 80 或 148。
    - 高 80：先铺到 608×148 透明底（内容顶对齐，下方透明），再叠模板。
    - 高 148：整图顶对齐后叠模板（模板盖在最上层）。
    """
    tpl_path = template_path if template_path is not None else _static_trophy_template_path()
    if isinstance(user_image, QPixmap):
        pm_user = user_image
    else:
        pm_user = QPixmap.fromImage(user_image)
    if pm_user.isNull():
        raise ValueError("无法读取用户图片。")
    w, h = pm_user.width(), pm_user.height()
    if w != TROPHY_TITLE_W:
        raise ValueError(f"图片宽度须为 {TROPHY_TITLE_W}，当前为 {w}。")
    if h not in (TROPHY_SHORT_H, TROPHY_TITLE_H):
        raise ValueError(f"图片高度须为 {TROPHY_SHORT_H} 或 {TROPHY_TITLE_H}，当前为 {h}。")

    out = QImage(TROPHY_TITLE_W, TROPHY_TITLE_H, QImage.Format.Format_ARGB32)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.drawPixmap(0, 0, pm_user)
    tpl = QPixmap(str(tpl_path))
    if tpl.isNull():
        p.end()
        raise ValueError(f"无法读取模板：{tpl_path}")
    if tpl.width() != TROPHY_TITLE_W or tpl.height() != TROPHY_TITLE_H:
        tpl = tpl.scaled(
            TROPHY_TITLE_W,
            TROPHY_TITLE_H,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    p.drawPixmap(0, 0, tpl)
    p.end()
    return out


def compose_trophy_title_png(*, user_image_path: Path, template_path: Path | None = None) -> QImage:
    pm_user = QPixmap(str(user_image_path))
    if pm_user.isNull():
        raise ValueError("无法读取用户图片，请确认格式与路径。")
    return compose_trophy_title_image(user_image=pm_user, template_path=template_path)


class TrophyTextureComposeDialog(FluentCaptionDialog):
    """称号贴图：608×148 或 608×80（自动垫高透明区）后与 trophy.png 叠加。"""

    def __init__(self, *, out_dir: Path, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("称号贴图编辑器")
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(720, 420)
        self._out_dir = out_dir
        self.result_png_path: Path | None = None

        hint = BodyLabel(
            f"上传宽 {TROPHY_TITLE_W}、高 {TROPHY_SHORT_H} 或 {TROPHY_TITLE_H} 的 PNG（或常见位图）。"
            f"若为 {TROPHY_TITLE_W}×{TROPHY_SHORT_H}，会在下方自动扩展透明区域至 {TROPHY_TITLE_H}，"
            "再与工具模板叠加（模板在最上层）。",
            self,
        )
        hint.setWordWrap(True)
        hint.setTextColor("#6B7280", "#9CA3AF")

        self._preview = QLabel(self)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumHeight(160)
        self._preview.setText("尚未选择图片")
        self._preview.setStyleSheet("border: 1px solid #d1d5db; border-radius: 8px;")

        self._src_path: Path | None = None
        self._composed: QImage | None = None

        pick = PushButton("选择图片…", self)
        pick.clicked.connect(self._on_pick)
        save = PrimaryPushButton("生成 608×148 并填入", self)
        save.clicked.connect(self._on_save)
        cancel = PushButton("取消", self)
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(pick)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(save)

        card = CardWidget(self)
        cly = QVBoxLayout(card)
        cly.setContentsMargins(16, 14, 16, 14)
        cly.setSpacing(10)
        cly.addWidget(hint)
        cly.addWidget(self._preview, stretch=1)
        cly.addLayout(row)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*fluent_caption_content_margins())
        lay.setSpacing(10)
        lay.addWidget(card, stretch=1)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.raise_()
        self.activateWindow()
        print(
            f"[trophy-debug] texture show ts={time.time():.3f} "
            f"visible={self.isVisible()} active={self.isActiveWindow()} "
            f"geom={self.geometry().x()},{self.geometry().y()},{self.geometry().width()},{self.geometry().height()}"
        )

    def _on_pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择称号贴图",
            "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*.*)",
        )
        if not path:
            return
        p = Path(path).expanduser()
        try:
            img = compose_trophy_title_png(user_image_path=p)
        except ValueError as e:
            fly_critical(self, "尺寸不符", str(e))
            return
        self._src_path = p
        self._composed = img
        pm = QPixmap.fromImage(img)
        if not pm.isNull():
            self._preview.setPixmap(pm.scaledToWidth(560, Qt.TransformationMode.SmoothTransformation))
            self._preview.setText("")
        else:
            self._preview.setPixmap(QPixmap())
            self._preview.setText("预览失败")

    def _on_save(self) -> None:
        if self._composed is None or self._composed.isNull():
            fly_critical(self, "错误", "请先选择符合尺寸的图片。")
            return
        self._out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out = self._out_dir / f"trophy_title_compose_{ts}.png"
        if not self._composed.save(str(out), "PNG"):
            fly_critical(self, "错误", f"无法写入：{out}")
            return
        self.result_png_path = out
        self.accept()
