"""PSB 动作分配对话框：上传/在线获取 PSB → 可视化分配动作槽 → 位置预览 → 生成部署。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QCloseEvent, QFont, QPainter, QPen, QPixmap, QLinearGradient
from PyQt6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox as FluentComboBox,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SegmentedWidget,
    SpinBox,
    SwitchButton,
)

from ..acus_scan import scan_charas, scan_system_voices
from ..dds_convert import ingest_to_bc3_dds
from ..dds_preview import ensure_dds_preview_png
from ..gif_mate import (
    GifFramePlan,
    GifMateCreateRequest,
    create_gif_mate,
    find_gif_mate_template,
    inspect_gif,
)
from ..mate_layout import (
    DEFAULT_RESULT_CALIBRATION,
    MateSceneCalibration,
    calibration_from_game,
    mate_content_rect,
    mate_position_from_screen,
    recommended_scale_for_height,
)
from ..mate_action_slots import (
    DETAILED_ACTION_GROUPS,
    SIMPLE_ACTION_GROUPS,
    MateActionGroup,
    expand_action_assignments,
)
from ..psb_action_assigner import (
    PsbActionAssigner,
    PsbActionData,
    generate_mate_xml,
)
from .chara_add_dialog import CharaAddDialog
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical, fly_message
from .mate_preview_dialog import MatePreviewDialog


# ---------------------------------------------------------------------------
# lolicount 在线模型仓库接口
# ---------------------------------------------------------------------------

LOLICOUNT_API_BASE = "https://lolicount.top"


class _TaskWorker(QThread):
    """Run a long conversion without blocking the modal window's event loop."""

    done = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, task, parent=None) -> None:
        super().__init__(parent)
        self._task = task

    def run(self) -> None:  # noqa: D102
        try:
            self.done.emit(self._task(self.progress.emit))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class _LolicountClient:
    """lolicount.top 的 PSB 模型仓库客户端（GET /api/psb/models、/api/psb/:m/download）。"""

    def list_models(self, base: str = LOLICOUNT_API_BASE) -> list[str]:
        import json as _json
        from urllib.request import Request, urlopen

        req = Request(f"{base}/api/psb/models", headers={"User-Agent": "ChuniEventer/1.0"})
        with urlopen(req, timeout=20) as resp:
            data = _json.load(resp)
        models = data.get("models", [])
        return [str(m) for m in models if m]

    def download(self, model: str, dest: Path, base: str = LOLICOUNT_API_BASE) -> Path:
        """下载模型并落盘为 .psb（.psb.gz 自动解压）。返回 psb 路径。"""
        import gzip
        from urllib.request import Request, urlopen

        req = Request(
            f"{base}/api/psb/{model}/download",
            headers={"User-Agent": "ChuniEventer/1.0"},
        )
        with urlopen(req, timeout=300) as resp:
            raw = resp.read()
        if raw[:2] == b"\x1f\x8b":  # gzip magic → 解压成纯 PSB
            raw = gzip.decompress(raw)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        return dest


# ---------------------------------------------------------------------------
# 位置预览画布
# ---------------------------------------------------------------------------

_LOGICAL_W, _LOGICAL_H = 1920, 1080


class MatePositionPreview(QWidget):
    """Scene preview driven by the same two-stage transforms as the game."""

    positionChanged = pyqtSignal(int, int, int)  # posX, posY, scale

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bg: QPixmap | None = None
        self._chara: QPixmap | None = None
        self._result_atlas: QPixmap | None = None
        self._score_atlas: QPixmap | None = None
        self._rank_atlas: QPixmap | None = None
        self._mate_room_bg: QPixmap | None = None
        self._mate_room_atlas: QPixmap | None = None
        self._mate_room_title: QPixmap | None = None
        self._pos_x = 1
        self._pos_y = -50
        self._scale = 6000
        self._source_size = (432, 960)
        self._calibration: MateSceneCalibration = DEFAULT_RESULT_CALIBRATION
        self._dragging = False
        self._drag_offset = QPointF()
        self.setMinimumSize(480, 270)
        self.setMouseTracking(True)

    # -- 外部接口 -----------------------------------------------------------

    def set_params(self, pos_x: int, pos_y: int, scale: int) -> None:
        self._pos_x, self._pos_y, self._scale = pos_x, pos_y, scale
        self.update()

    def set_background(self, path: Path | None) -> None:
        if path and Path(path).is_file():
            self._bg = QPixmap(str(path))
        else:
            self._bg = None
        self.update()

    def set_result_overlay_assets(self, paths: dict[str, Path | None]) -> None:
        """Load the installed game's result atlases used by the foreground UI."""
        def load(name: str) -> QPixmap | None:
            path = paths.get(name)
            if path is None or not Path(path).is_file():
                return None
            pixmap = QPixmap(str(path))
            return None if pixmap.isNull() else pixmap

        self._result_atlas = load("result")
        self._score_atlas = load("score")
        self._rank_atlas = load("rank")
        self._mate_room_bg = load("mate_room_bg")
        self._mate_room_atlas = load("mate_room")
        self._mate_room_title = load("mate_room_title")
        self.update()

    def set_chara_image(
        self,
        path: Path | None,
        crop_box: tuple[int, int, int, int] | None = None,
    ) -> None:
        if path and Path(path).is_file():
            pixmap = QPixmap(str(path))
            if crop_box is not None and not pixmap.isNull():
                left, top, right, bottom = crop_box
                pixmap = pixmap.copy(left, top, max(1, right - left), max(1, bottom - top))
            self._chara = pixmap
        else:
            self._chara = None
        self.update()

    def set_source_size(self, width: int, height: int) -> None:
        """Set the alpha-cropped E-mote source bounds used for placement."""
        self._source_size = max(1, width), max(1, height)
        self.update()

    def set_calibration(self, calibration: MateSceneCalibration) -> None:
        self._calibration = calibration
        self.update()

    def chara_rect(self) -> QRectF:
        """角色在 1920x1080 逻辑坐标里的矩形。"""
        left, top, width, height = mate_content_rect(
            source_size=self._source_size,
            pos_x=self._pos_x,
            pos_y=self._pos_y,
            scale_x10000=self._scale,
            calibration=self._calibration,
        )
        return QRectF(left, top, width, height)

    # -- 绘制 ---------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # letterbox: 保持 16:9 居中
        widget_w, widget_h = self.width(), self.height()
        scale = min(widget_w / _LOGICAL_W, widget_h / _LOGICAL_H)
        ox = (widget_w - _LOGICAL_W * scale) / 2
        oy = (widget_h - _LOGICAL_H * scale) / 2
        painter.translate(ox, oy)
        painter.scale(scale, scale)

        painter.setClipRect(0, 0, _LOGICAL_W, _LOGICAL_H)

        is_mate_room = self._calibration.scene_key == "mate_room"

        # 背景。Mate ROOM 使用游戏自己的专用纹理；用户截图只替换结算页。
        if is_mate_room and self._mate_room_bg is not None and not self._mate_room_bg.isNull():
            painter.drawPixmap(
                QRectF(0, 0, _LOGICAL_W, _LOGICAL_H),
                self._mate_room_bg,
                QRectF(self._mate_room_bg.rect()),
            )
        elif self._bg is not None and not self._bg.isNull():
            painter.drawPixmap(QRectF(0, 0, _LOGICAL_W, _LOGICAL_H), self._bg, QRectF(self._bg.rect()))
        else:
            grad = QLinearGradient(0, 0, 0, _LOGICAL_H)
            grad.setColorAt(0, QColor(250, 240, 210))
            grad.setColorAt(1, QColor(250, 205, 140))
            painter.fillRect(0, 0, _LOGICAL_W, _LOGICAL_H, QBrush(grad))
            # 简化 UI 占位(结算画面风格)
            painter.setPen(QPen(QColor(255, 255, 255, 160), 3))
            for x, y, w, h in ((340, 320, 600, 140), (960, 320, 460, 240),
                               (340, 500, 300, 100), (660, 500, 260, 100),
                               (960, 600, 460, 180)):
                painter.drawRoundedRect(QRectF(x, y, w, h), 12, 12)
            painter.setPen(QPen(QColor(150, 120, 80, 180), 2))
            f = QFont()
            f.setPixelSize(30)
            painter.setFont(f)
            painter.drawText(QRectF(340, 200, 900, 60), Qt.AlignmentFlag.AlignLeft,
                             f"{self._calibration.scene_label}（参考布局）")

        if is_mate_room:
            self._draw_mate_room_background_deco(painter)

        # 角色先绘制到 E-mote 动态纹理，再由 SurfRide 的 1080x1080
        # C_emote_body 面片显示；面片之外的内容在游戏里不可见。
        rect = self.chara_rect()
        surface = QRectF(*self._calibration.surface_rect)
        # GIF frames are union-alpha-cropped, so their rectangle is a real
        # visible bound.  A native PSB fallback is only its authored canvas;
        # warning from that box would claim clipping even when all visible
        # parts are safely inside the surface.
        has_exact_visible_bounds = self._chara is not None and not self._chara.isNull()
        head_clipped = has_exact_visible_bounds and rect.top() < surface.top()
        feet_clipped = has_exact_visible_bounds and rect.bottom() > surface.bottom()
        painter.save()
        painter.setClipRect(surface, Qt.ClipOperation.IntersectClip)
        if self._chara is not None and not self._chara.isNull():
            painter.drawPixmap(rect, self._chara, QRectF(self._chara.rect()))
        else:
            self._draw_placeholder_figure(painter, rect)
        painter.restore()

        if is_mate_room:
            self._draw_mate_room_foreground(painter)
        else:
            self._draw_result_foreground(painter)

        self._draw_transform_guides(painter, rect, surface)

        # 溢出警告
        f = QFont()
        f.setPixelSize(36)
        painter.setFont(f)
        warn = None
        if head_clipped:
            warn = "⚠ 顶部超出 E-mote 显示面 — 向下拖动或减小缩放"
        elif feet_clipped:
            warn = "⚠ 底部超出 E-mote 显示面 — 向上拖动或减小缩放"
        if warn:
            painter.setPen(QColor(200, 30, 30))
            painter.drawText(QRectF(40, 20, _LOGICAL_W - 80, 60),
                             Qt.AlignmentFlag.AlignLeft, warn)

        # 边框
        painter.setPen(QPen(QColor(60, 60, 60), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(0, 0, _LOGICAL_W, _LOGICAL_H)

    def _draw_transform_guides(
        self, painter: QPainter, canvas: QRectF, surface: QRectF
    ) -> None:
        """Make the two coordinate spaces explicit instead of implying one box."""
        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(14, 116, 144, 210), 3, Qt.PenStyle.DotLine))
        painter.drawRect(surface)
        painter.setPen(QPen(QColor(43, 101, 210, 225), 3, Qt.PenStyle.DashLine))
        painter.drawRect(canvas)
        box = QRectF(32, 936, 720, 112)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(19, 30, 49, 205))
        painter.drawRoundedRect(box, 12, 12)
        self._draw_result_text(
            painter, QRectF(52, 948, 680, 34),
            f"{self._calibration.scene_label} · XML → 动态贴图 → 场景面片",
            22, QColor(255, 255, 255),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        painter.setPen(QPen(QColor(14, 188, 220), 4, Qt.PenStyle.DotLine))
        painter.drawLine(QPointF(54, 1003), QPointF(116, 1003))
        self._draw_result_text(
            painter, QRectF(128, 986, 235, 34), "动态贴图可见面", 18,
            QColor(214, 249, 255), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        painter.setPen(QPen(QColor(84, 142, 255), 4, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(382, 1003), QPointF(444, 1003))
        self._draw_result_text(
            painter, QRectF(456, 986, 260, 34), "模型画布（非透明边界）", 18,
            QColor(225, 234, 255), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        painter.restore()

    def _draw_mate_room_foreground(self, painter: QPainter) -> None:
        """Draw Mate ROOM's occupied UI areas above the E-mote body layer."""
        # The Mate Room title belongs to L_MateGarden_BG and is deliberately
        # drawn before the character.  Drawing it here would hide the head and
        # reproduce the exact false clipping reported by users.
        self._draw_mate_room_panel(painter, QRectF(58, 254, 430, 612), "MATE INFO")
        self._draw_mate_room_panel(painter, QRectF(1432, 254, 430, 612), "YELL / RANK")
        self._draw_mate_room_panel(painter, QRectF(640, 858, 640, 136), "ACTION")

    def _draw_mate_room_background_deco(self, painter: QPainter) -> None:
        atlas = self._mate_room_title
        if atlas is not None and not atlas.isNull():
            # The title is an authored crop in CHU_UI_MateGarden_00.dds.
            painter.drawPixmap(
                QRectF(360, 18, 1200, 280), atlas, QRectF(0, 0, 1200, 280)
            )
        else:
            self._draw_result_text(
                painter, QRectF(360, 28, 1200, 150), "Mate ROOM", 86,
                QColor(83, 205, 70), Qt.AlignmentFlag.AlignCenter,
            )

    @classmethod
    def _draw_mate_room_panel(cls, painter: QPainter, rect: QRectF, title: str) -> None:
        painter.setPen(QPen(QColor(255, 255, 255, 235), 6))
        painter.setBrush(QColor(255, 255, 248, 214))
        painter.drawRoundedRect(rect, 24, 24)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 107, 123, 235))
        painter.drawRoundedRect(
            QRectF(rect.left() + 5, rect.top() + 5, rect.width() - 10, 48), 18, 18
        )
        cls._draw_result_text(
            painter, QRectF(rect.left() + 20, rect.top() + 8, rect.width() - 40, 40),
            title, 24, QColor(255, 255, 255),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )

    def _draw_result_foreground(self, painter: QPainter) -> None:
        """Draw the default result page in the installed game's layer order.

        SurfRide stores a cast's translation at its authored pivot.  It is not
        the centre of the atlas crop.  In particular ``C_score_base`` resolves
        to the *top-left* of the score card at (316, 263).  Treating that value
        as a centre was the source of the large offset in the old preview.
        """
        atlas = self._result_atlas

        # Persistent result HUD.  These scenes are composed above Result_00/01
        # by the game; keeping their occupied areas visible matters when a tall
        # Mate is dragged upwards.
        self._draw_hud_card(painter, QRectF(50, 24, 565, 200), "PLAYER DATA")
        self._draw_hud_card(painter, QRectF(615, 24, 755, 200), "CLEAR / SCORE")
        self._draw_hud_card(painter, QRectF(1370, 24, 500, 200), "TRACK 2  MASTER 15")

        # Result_01 / score layer.  C_score_base is the authored top-left.
        score_rect = QRectF(316, 263, 616, 215)
        if atlas is not None:
            self._draw_nine_slice(
                painter, atlas, QRectF(0, 0, 616, 112), score_rect,
                left=12, top=58, right=12, bottom=12,
            )
        else:
            self._draw_result_panel(painter, score_rect, "SCORE")
        if atlas is not None:
            painter.drawPixmap(
                QRectF(332, 319, 578, 36),
                atlas,
                QRectF(0, 116, 578, 36),
            )
        self._draw_result_text(
            painter, QRectF(650, 283, 250, 34), "HIGH SCORE  1,009,876", 20,
            QColor(48, 24, 67), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        self._draw_result_text(
            painter,
            QRectF(342, 351, 560, 100),
            "1,009,876",
            66,
            QColor(77, 29, 112),
            Qt.AlignmentFlag.AlignCenter,
        )

        # Result_01 / rank reference.  Its control sits in the right result
        # column; the referenced glyph scene supplies the animated letters.
        rank_rect = QRectF(960, 263, 480, 290)
        if atlas is not None:
            self._draw_nine_slice(
                painter, atlas, QRectF(0, 515, 480, 110), rank_rect,
                left=12, top=58, right=12, bottom=12,
            )
        else:
            self._draw_result_panel(painter, rank_rect, "RANK")
        if self._rank_atlas is not None:
            painter.drawPixmap(
                QRectF(976, 319, 448, 36),
                self._rank_atlas,
                QRectF(461, 0, 441, 36),
            )
            for index in range(3):
                painter.drawPixmap(
                    QRectF(994 + index * 132, 354, 130, 136),
                    self._rank_atlas,
                    QRectF(275, 500, 170, 178),
                )
        else:
            self._draw_result_text(
                painter, QRectF(990, 348, 420, 150), "SSS", 104,
                QColor(119, 51, 170), Qt.AlignmentFlag.AlignCenter,
            )

        # Clear/skill and max-combo layers are siblings in the left column.
        skill_rect = QRectF(316, 503, 292, 112)
        combo_rect = QRectF(621, 503, 339, 112)
        self._draw_result_panel(painter, skill_rect, "SKILL")
        self._draw_result_text(
            painter, QRectF(337, 548, 250, 54), "HARD     17 / 20", 27,
            QColor(69, 44, 84), Qt.AlignmentFlag.AlignCenter,
        )
        self._draw_result_panel(painter, combo_rect, "MAX COMBO")
        self._draw_result_text(
            painter, QRectF(758, 545, 180, 58), "1406", 39,
            QColor(70, 35, 105),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )

        # Default judge summary.  The large 5x4 table at atlas y=195 belongs
        # to Score Page 01 and must not be shown on the default Page 00.
        judge_rect = QRectF(660, 638, 310, 208)
        if atlas is not None:
            painter.drawPixmap(judge_rect, atlas, QRectF(623, 786, 310, 208))
        else:
            self._draw_result_panel(painter, judge_rect, "JUDGEMENT")
        for row, value in enumerate((2315, 130, 3, 3)):
            self._draw_result_text(
                painter, QRectF(856, 646 + row * 41, 92, 36), str(value), 23,
                QColor(255, 255, 255), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            )

        # Rating and version-over-power bases recovered from their respective
        # Result_01 cast chains: (923,568) and (923,739).
        # The base pivot includes 37 px of authored left padding; visible card
        # content therefore starts at x=960.
        rating_rect = QRectF(960, 568, 460, 160)
        overpower_rect = QRectF(960, 739, 460, 111)
        self._draw_result_panel(painter, rating_rect, "RATING")
        self._draw_result_text(
            painter, QRectF(1030, 618, 285, 72), "17.25", 57,
            QColor(91, 35, 120), Qt.AlignmentFlag.AlignCenter,
        )
        self._draw_result_panel(painter, overpower_rect, "VERSION OVER POWER")
        self._draw_result_text(
            painter, QRectF(1030, 779, 285, 54), "5271.20", 34,
            QColor(91, 35, 120), Qt.AlignmentFlag.AlignCenter,
        )

        # Do not draw Result_01's character-rank branch in Mate mode.  The game
        # selects C_emote_body instead of C_chara_body; character progression
        # belongs to the normal character result branch shown in cabinet photos.

    @staticmethod
    def _draw_nine_slice(
        painter: QPainter,
        pixmap: QPixmap,
        source: QRectF,
        target: QRectF,
        *,
        left: float,
        top: float,
        right: float,
        bottom: float,
    ) -> None:
        """Stretch an atlas panel while preserving its authored borders."""
        sx = (source.left(), source.left() + left, source.right() - right, source.right())
        sy = (source.top(), source.top() + top, source.bottom() - bottom, source.bottom())
        tx = (target.left(), target.left() + left, target.right() - right, target.right())
        ty = (target.top(), target.top() + top, target.bottom() - bottom, target.bottom())
        for row in range(3):
            for column in range(3):
                painter.drawPixmap(
                    QRectF(tx[column], ty[row], tx[column + 1] - tx[column], ty[row + 1] - ty[row]),
                    pixmap,
                    QRectF(sx[column], sy[row], sx[column + 1] - sx[column], sy[row + 1] - sy[row]),
                )

    @staticmethod
    def _draw_hud_card(painter: QPainter, rect: QRectF, text: str) -> None:
        painter.setPen(QPen(QColor(255, 255, 255, 220), 4))
        painter.setBrush(QColor(40, 28, 76, 215))
        painter.drawRect(rect)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 160, 53, 230))
        painter.drawRect(QRectF(rect.left(), rect.bottom() - 34, rect.width(), 34))
        MatePositionPreview._draw_result_text(
            painter, QRectF(rect.left() + 16, rect.top() + 8, rect.width() - 32, 42),
            text, 25, QColor(255, 255, 255),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )

    @staticmethod
    def _draw_result_panel(painter: QPainter, rect: QRectF, title: str) -> None:
        painter.setPen(QPen(QColor(229, 204, 249, 235), 7))
        painter.setBrush(QColor(255, 255, 255, 228))
        painter.drawRoundedRect(rect, 18, 18)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 91, 134, 230))
        painter.drawRoundedRect(QRectF(rect.left() + 5, rect.top() + 5,
                                      rect.width() - 10, 34), 12, 12)
        MatePositionPreview._draw_result_text(
            painter, QRectF(rect.left() + 18, rect.top() + 4, rect.width() - 36, 37),
            title, 23, QColor(255, 255, 255),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )

    @staticmethod
    def _draw_result_text(
        painter: QPainter,
        rect: QRectF,
        text: str,
        size: int,
        color: QColor,
        alignment: Qt.AlignmentFlag,
    ) -> None:
        # Use the Windows CJK UI family explicitly; Qt's off-screen/default
        # fallback can otherwise select a Latin-only face and render boxes.
        font = QFont("Microsoft YaHei UI")
        font.setPixelSize(size)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(rect, alignment, text)

    def _draw_placeholder_figure(self, painter: QPainter, rect: QRectF) -> None:
        """Show the real E-mote canvas when no renderable frame is available.

        A fabricated humanoid silhouette falsely implied visible model bounds.
        Native PSB geometry can only be composed by the E-mote runtime, so the
        honest fallback is its authored screen rectangle and origin.
        """
        painter.setPen(QPen(QColor(48, 105, 190, 210), 3, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(80, 145, 220, 22))
        painter.drawRect(rect)
        center = rect.center()
        painter.drawLine(QPointF(center.x() - 18, center.y()), QPointF(center.x() + 18, center.y()))
        painter.drawLine(QPointF(center.x(), center.y() - 18), QPointF(center.x(), center.y() + 18))
        self._draw_result_text(
            painter, QRectF(rect.left(), rect.top() + 12, rect.width(), 42),
            "E-mote authored canvas", 20, QColor(48, 105, 190),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
        )

    # -- 交互: 拖动角色 ------------------------------------------------------

    def _to_logical(self, pos: QPointF) -> QPointF:
        scale = min(self.width() / _LOGICAL_W, self.height() / _LOGICAL_H)
        ox = (self.width() - _LOGICAL_W * scale) / 2
        oy = (self.height() - _LOGICAL_H * scale) / 2
        return QPointF((pos.x() - ox) / scale, (pos.y() - oy) / scale)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        lp = self._to_logical(QPointF(event.position()))
        if self.chara_rect().contains(lp):
            self._dragging = True
            self._drag_offset = lp - self.chara_rect().center()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._dragging:
            return
        lp = self._to_logical(QPointF(event.position()))
        new_center = lp - self._drag_offset
        self._pos_x, self._pos_y = mate_position_from_screen(
            center_x=new_center.x(),
            center_y=new_center.y(),
            calibration=self._calibration,
        )
        self.update()
        self.positionChanged.emit(self._pos_x, self._pos_y, self._scale)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.positionChanged.emit(self._pos_x, self._pos_y, self._scale)


class PsbActionDialog(FluentCaptionDialog):
    """Create a Mate from a GIF or an existing PSB model."""

    def __init__(self, *, acus_root: Path, freemote_dir: Path, mate_id: int,
                 chara_id: int = 80000, game_root: Path | None = None,
                 get_tool_path=None, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("新增伴侣")
        self.setModal(True)
        self.resize(980, 650)

        self._acus_root = acus_root
        self._freemote_dir = freemote_dir
        self._game_root = Path(game_root) if game_root else None
        self._scene_calibrations = {
            "result": calibration_from_game(self._game_root, "result"),
            "mate_room": calibration_from_game(self._game_root, "mate_room"),
        }
        self._calibration = self._scene_calibrations["result"]
        self._mate_id = mate_id
        self._assigner = PsbActionAssigner(freemote_dir)
        self._psb_data: PsbActionData | None = None
        self._psb_path: Path | None = None
        self._get_tool_path = get_tool_path
        self._preview_png: Path | None = None
        self._fetch_thread = None
        self._build_thread = None
        self._gif_thread = None
        self._background_thread = None
        self._models_thread = None
        self._gif_plan: GifFramePlan | None = None

        # ---- 控件 ----
        self.psb_path_edit = LineEdit(self)
        self.psb_path_edit.setPlaceholderText("选择本地 PSB 文件")
        self.gif_path_edit = LineEdit(self)
        self.gif_path_edit.setPlaceholderText("选择一张动态 GIF")
        self.gif_fps_spin = SpinBox(self)
        self.gif_fps_spin.setRange(1, 30)
        self.gif_fps_spin.setValue(10)
        self.gif_height_combo = FluentComboBox(self)
        for height in (256, 320, 384, 512):
            self.gif_height_combo.addItem(f"{height} px", userData=height)
        self.gif_height_combo.setCurrentIndex(2)
        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText("伴侣显示名，例如 アズキ")
        self.mate_id_edit = SpinBox(self)
        self.mate_id_edit.setRange(1, 999999)
        self.mate_id_edit.setValue(mate_id)
        self.chara_combo = FluentComboBox(self)
        self.chara_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._reload_charas(prefer_id=chara_id)
        chara_row = QWidget(self)
        ch_h = QHBoxLayout(chara_row)
        ch_h.setContentsMargins(0, 0, 0, 0)
        ch_h.setSpacing(8)
        ch_h.addWidget(self.chara_combo, stretch=1)
        self.chara_new_btn = PushButton("新建…", self)
        self.chara_new_btn.clicked.connect(self._new_chara)
        ch_h.addWidget(self.chara_new_btn)

        self.pos_x_spin = SpinBox(self)
        self.pos_x_spin.setRange(-500, 500)
        self.pos_x_spin.setValue(1)
        self.pos_y_spin = SpinBox(self)
        self.pos_y_spin.setRange(-1000, 500)
        self.pos_y_spin.setValue(-50)
        self.scale_spin = SpinBox(self)
        self.scale_spin.setRange(1000, 40000)
        self.scale_spin.setValue(6000)

        self.preview = MatePositionPreview(self)
        self.preview.set_calibration(self._calibration)

        # 游戏始终读取 18 个槽；编辑器在这个 seam 上提供六组简略映射或
        # 18 槽覆盖。PSB 和 GIF 共享同一组语义，只有输入控件不同。
        self.simple_psb_combos: dict[str, FluentComboBox] = {}
        self.detail_psb_combos: dict[int, FluentComboBox] = {}
        self.simple_gif_edits: dict[str, LineEdit] = {}
        self.detail_gif_edits: dict[int, LineEdit] = {}
        core_group = CardWidget(self)
        core_group_lay = QVBoxLayout(core_group)
        core_group_lay.setContentsMargins(16, 12, 16, 12)
        core_group_lay.setSpacing(8)
        mode_row = QHBoxLayout()
        mode_row.addWidget(BodyLabel("动作配置", core_group), stretch=1)
        mode_row.addWidget(CaptionLabel("简略配置", core_group))
        self._action_mode_switch = SwitchButton(core_group)
        self._action_mode_switch.setChecked(False)
        mode_row.addWidget(self._action_mode_switch)
        mode_row.addWidget(CaptionLabel("详细配置", core_group))
        core_group_lay.addLayout(mode_row)
        self._action_explanation = CaptionLabel("", core_group)
        self._action_explanation.setWordWrap(True)
        core_group_lay.addWidget(self._action_explanation)

        self._action_stack = QStackedWidget(core_group)
        self._action_stack.addWidget(
            self._make_psb_action_page(SIMPLE_ACTION_GROUPS, detailed=False)
        )
        self._action_stack.addWidget(
            self._make_psb_action_page(DETAILED_ACTION_GROUPS, detailed=True)
        )
        self._action_stack.addWidget(
            self._make_gif_action_page(SIMPLE_ACTION_GROUPS, detailed=False)
        )
        self._action_stack.addWidget(
            self._make_gif_action_page(DETAILED_ACTION_GROUPS, detailed=True)
        )
        core_group_lay.addWidget(self._action_stack, stretch=1)
        core_lay = QVBoxLayout()
        core_lay.addWidget(core_group)
        core_host = QWidget(self)
        core_host.setLayout(core_lay)

        # ---- 布局 ----
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*fluent_caption_content_margins())
        layout.setSpacing(10)

        src_card = CardWidget(self)
        src_lay = QVBoxLayout(src_card)
        src_lay.setContentsMargins(16, 12, 16, 12)
        src_lay.setSpacing(8)
        src_lay.addWidget(BodyLabel("① 选择素材", self))
        self._source_segment = SegmentedWidget(self)
        self._source_segment.addItem("gif", "GIF 动画")
        self._source_segment.addItem("psb", "PSB 模型")
        self._source_segment.setCurrentItem("gif")
        src_lay.addWidget(self._source_segment)

        self._source_stack = QStackedWidget(self)

        gif_panel = QWidget(self)
        gif_lay = QVBoxLayout(gif_panel)
        gif_lay.setContentsMargins(0, 4, 0, 0)
        gif_lay.setSpacing(8)
        gif_row = QWidget(gif_panel)
        gif_h = QHBoxLayout(gif_row)
        gif_h.setContentsMargins(0, 0, 0, 0)
        gif_h.setSpacing(8)
        gif_h.addWidget(self.gif_path_edit, stretch=1)
        gif_browse = PushButton("选择 GIF…", gif_panel)
        gif_browse.clicked.connect(self._browse_gif)
        gif_h.addWidget(gif_browse)
        gif_lay.addWidget(gif_row)
        gif_options = QHBoxLayout()
        gif_options.addWidget(QLabel("采样帧率", gif_panel))
        gif_options.addWidget(self.gif_fps_spin)
        gif_options.addSpacing(16)
        gif_options.addWidget(QLabel("角色清晰度", gif_panel))
        gif_options.addWidget(self.gif_height_combo)
        gif_options.addStretch(1)
        gif_lay.addLayout(gif_options)
        gif_tip = CaptionLabel(
            "先选择一张透明背景主 GIF。进入下一步后可按 6 个场景组替换 GIF，或打开详细配置为 18 个槽分别选择；"
            "留空的项目自动复用主 GIF。多条 GIF 会作为独立 timeline 打包进同一个 E-mote PSB（每条最多 120 帧）。",
            gif_panel,
        )
        gif_tip.setWordWrap(True)
        gif_lay.addWidget(gif_tip)
        self._gif_plan_label = CaptionLabel("选择 GIF 后会先计算真实输出帧数、时长和有效 FPS。", gif_panel)
        self._gif_plan_label.setWordWrap(True)
        gif_lay.addWidget(self._gif_plan_label)
        self._source_stack.addWidget(gif_panel)

        psb_panel = QWidget(self)
        psb_lay = QVBoxLayout(psb_panel)
        psb_lay.setContentsMargins(0, 4, 0, 0)
        psb_lay.setSpacing(8)
        psb_row = QWidget(self)
        pr_h = QHBoxLayout(psb_row)
        pr_h.setContentsMargins(0, 0, 0, 0)
        pr_h.setSpacing(8)
        pr_h.addWidget(self.psb_path_edit, stretch=1)
        browse = PushButton("浏览…", self)
        browse.clicked.connect(self._browse_psb)
        pr_h.addWidget(browse)
        load_btn = PrimaryPushButton("解析", self)
        load_btn.clicked.connect(self._load_psb)
        pr_h.addWidget(load_btn)
        psb_lay.addWidget(psb_row)
        url_row = QWidget(self)
        ur_h = QHBoxLayout(url_row)
        ur_h.setContentsMargins(0, 0, 0, 0)
        ur_h.setSpacing(8)
        self.model_combo = FluentComboBox(self)
        self.model_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.model_combo.addItem("（点击「获取列表」从 lolicount 拉取在线模型）", userData="")
        ur_h.addWidget(self.model_combo, stretch=1)
        self._refresh_models_btn = PushButton("获取列表", self)
        self._refresh_models_btn.clicked.connect(self._fetch_models)
        ur_h.addWidget(self._refresh_models_btn)
        dl_btn = PushButton("下载并解析", self)
        dl_btn.clicked.connect(self._download_online)
        ur_h.addWidget(dl_btn)
        psb_lay.addWidget(url_row)
        psb_tip = CaptionLabel(
            "解析后才显示位置预览和动作匹配；可使用本地模型，也可从在线仓库获取。",
            psb_panel,
        )
        psb_tip.setWordWrap(True)
        psb_lay.addWidget(psb_tip)
        self._source_stack.addWidget(psb_panel)
        src_lay.addWidget(self._source_stack)

        info_card = CardWidget(self)
        info_lay = QVBoxLayout(info_card)
        info_lay.setContentsMargins(16, 12, 16, 12)
        info_lay.setSpacing(8)
        info_lay.addWidget(BodyLabel("② 伴侣信息", self))
        self.voice_combo = FluentComboBox(self)
        self.voice_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._reload_voices()
        info_grid = QGridLayout()
        info_grid.setHorizontalSpacing(10)
        info_grid.setVerticalSpacing(8)
        info_grid.addWidget(QLabel("伴侣显示名", self), 0, 0)
        info_grid.addWidget(self.name_edit, 0, 1)
        info_grid.addWidget(QLabel("Mate ID", self), 0, 2)
        info_grid.addWidget(self.mate_id_edit, 0, 3)
        info_grid.addWidget(QLabel("关联角色", self), 1, 0)
        info_grid.addWidget(chara_row, 1, 1)
        info_grid.addWidget(QLabel("系统语音", self), 1, 2)
        info_grid.addWidget(self.voice_combo, 1, 3)
        info_grid.setColumnStretch(1, 3)
        info_grid.setColumnStretch(3, 2)
        info_lay.addLayout(info_grid)
        info_lay.addWidget(CaptionLabel(
            "伴侣在游戏内的名字/立绘来自关联角色：可选现有角色，或点「新建…」先建一个角色再回来选。", self))
        layout.addWidget(src_card)
        self._source_card = src_card
        layout.addWidget(info_card)

        self._details_host = QWidget(self)
        mid = QHBoxLayout(self._details_host)
        mid.setContentsMargins(0, 0, 0, 0)
        # 左: 预览
        prev_card = CardWidget(self)
        pv_lay = QVBoxLayout(prev_card)
        pv_lay.setContentsMargins(16, 12, 16, 12)
        pv_lay.setSpacing(8)
        detail_head = QHBoxLayout()
        detail_head.addWidget(BodyLabel("③ 位置与动作（拖动角色即可调整）", self), stretch=1)
        self._scene_segment = SegmentedWidget(self)
        self._scene_segment.addItem("result", "结算画面")
        self._scene_segment.addItem("mate_room", "Mate ROOM")
        self._scene_segment.setCurrentItem("result")
        self._scene_segment.currentItemChanged.connect(self._on_preview_scene_changed)
        detail_head.addWidget(self._scene_segment)
        edit_source_btn = PushButton("更换素材", self)
        edit_source_btn.clicked.connect(self._show_source_editor)
        detail_head.addWidget(edit_source_btn)
        pv_lay.addLayout(detail_head)
        self.preview.positionChanged.connect(self._on_preview_drag)
        pv_lay.addWidget(self.preview, stretch=1)
        self._placement_accuracy = CaptionLabel("", self)
        self._placement_accuracy.setWordWrap(True)
        pv_lay.addWidget(self._placement_accuracy)
        bg_row = QHBoxLayout()
        self._preview_btn = PushButton("生成图标…", self)
        self._preview_btn.clicked.connect(self._make_preview_icon)
        bg_row.addWidget(self._preview_btn)
        self._preview_status = CaptionLabel("图标：未生成（生成伴侣时若无预览图则跳过图标）", self)
        bg_row.addWidget(self._preview_status, stretch=1)
        bg_btn = PushButton("加载游戏截图做背景…", self)
        bg_btn.clicked.connect(self._pick_background)
        bg_row.addWidget(bg_btn)
        pv_lay.addLayout(bg_row)

        param_form = QFormLayout()
        param_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for w, tip in ((self.pos_x_spin, "水平位置（E-mote 动态贴图坐标）"),
                       (self.pos_y_spin, "垂直位置（E-mote 逻辑像素，负值上移）"),
                       (self.scale_spin, "缩放 (万分之一, 6000=0.6 倍)")):
            w.valueChanged.connect(self._on_param_changed)
            param_form.addRow(tip, w)
        pv_lay.addLayout(param_form)
        self.preview.set_params(1, -50, 6000)

        mid.addWidget(prev_card, stretch=3)
        mid.addWidget(core_host, stretch=2)
        self._core_host = core_host
        layout.addWidget(self._details_host, stretch=1)

        btns = QHBoxLayout()
        self._status = CaptionLabel("", self)
        btns.addWidget(self._status, stretch=1)
        self._cancel_btn = PushButton("取消", self)
        self._cancel_btn.clicked.connect(self.reject)
        self._generate_btn = PrimaryPushButton("从 GIF 生成并写入 ACUS", self)
        self._generate_btn.clicked.connect(self._generate)
        btns.addWidget(self._cancel_btn)
        btns.addWidget(self._generate_btn)
        layout.addLayout(btns)

        self._bind_slots()
        self._action_mode_switch.checkedChanged.connect(self._update_action_mode)
        self._source_segment.currentItemChanged.connect(self._on_source_mode_changed)
        self.gif_height_combo.currentIndexChanged.connect(self._gif_options_changed)
        self.gif_fps_spin.valueChanged.connect(self._gif_options_changed)
        self.gif_path_edit.editingFinished.connect(self._prepare_gif_preview)
        self._on_source_mode_changed("gif")
        self._update_action_mode()
        QTimer.singleShot(0, self._load_game_background)

    def _on_preview_scene_changed(self, scene_key: str) -> None:
        """Switch only the game scene; XML values remain identical."""
        calibration = self._scene_calibrations.get(scene_key)
        if calibration is None:
            return
        self._calibration = calibration
        self.preview.set_calibration(calibration)
        self._placement_accuracy.setText(
            (
                "Mate ROOM：动态贴图面中心 (960, 552)、场景倍率 1.0；"
                "同一组 XML 参数会比结算画面大约大 17.6%，且顶部从 y≈12 开始。"
            )
            if scene_key == "mate_room"
            else (
                "结算画面：动态贴图面中心 (1610, 636)、场景倍率 0.85；"
                "虚线是模型画布，点线是 1080×1080 面片经场景缩放后的裁切范围。"
            )
        )

    # ---- 槽分配联动 --------------------------------------------------------

    @staticmethod
    def _action_caption(group: MateActionGroup, parent: QWidget) -> QLabel:
        caption = QLabel(parent)
        caption.setText(
            f"<b>{group.title}</b><br>"
            f"<span style='color:#6B7280'>{group.description}</span>"
        )
        caption.setWordWrap(True)
        return caption

    def _make_action_page(self, groups, make_input) -> QWidget:
        page = QWidget(self)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget(scroll)
        form = QFormLayout(content)
        form.setContentsMargins(0, 0, 4, 0)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setVerticalSpacing(8)
        for group in groups:
            form.addRow(self._action_caption(group, content), make_input(group, content))
        scroll.setWidget(content)
        page_layout.addWidget(scroll)
        return page

    def _make_psb_action_page(self, groups, *, detailed: bool) -> QWidget:
        def make_input(group: MateActionGroup, parent: QWidget):
            combo = FluentComboBox(parent)
            combo.addItem("（继承简略模式）" if detailed else "（未选择）", userData="")
            if detailed:
                self.detail_psb_combos[group.slots[0]] = combo
            else:
                self.simple_psb_combos[group.key] = combo
            return combo

        return self._make_action_page(groups, make_input)

    def _make_gif_action_page(self, groups, *, detailed: bool) -> QWidget:
        def make_input(group: MateActionGroup, parent: QWidget):
            row = QWidget(parent)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            edit = LineEdit(row)
            edit.setReadOnly(True)
            edit.setPlaceholderText(
                "留空则继承对应简略组" if detailed else "留空则复用步骤①的主 GIF"
            )
            button = PushButton("选择…", row)
            button.clicked.connect(lambda _checked=False, target=edit: self._browse_action_gif(target))
            clear = PushButton("清除", row)
            clear.clicked.connect(edit.clear)
            row_layout.addWidget(edit, stretch=1)
            row_layout.addWidget(button)
            row_layout.addWidget(clear)
            if detailed:
                self.detail_gif_edits[group.slots[0]] = edit
            else:
                self.simple_gif_edits[group.key] = edit
            return row

        return self._make_action_page(groups, make_input)

    def _browse_action_gif(self, edit: LineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择此动作的透明 GIF", "", "GIF 动画 (*.gif)")
        if path:
            edit.setText(path)

    def _update_action_mode(self, _checked=None) -> None:
        detailed = self._action_mode_switch.isChecked()
        is_gif = self._source_mode() == "gif"
        self._action_stack.setCurrentIndex((2 if is_gif else 0) + (1 if detailed else 0))
        if detailed:
            self._action_explanation.setText(
                "详细配置直接对应 Mate.xml 的 18 个 actionType。未单独选择的槽位会继承简略模式，"
                "所以只需要覆盖确实要使用不同动作的项目。Type 2～15 依次对应 D～SSS+；"
                "Type 16/17/18 分别是 Mate ROOM 开场、游戏中循环和收尾。"
            )
        else:
            self._action_explanation.setText(
                "简略模式把 18 个底层槽合并成 6 组：D～BBB、A～AAA、S～SS、SS+～SSS+、"
                "默认/ROOM 开场/收尾，以及 Mate ROOM 游戏中循环。这样保留真实触发语义，"
                "又不需要逐项配置 18 次。"
            )

    def _bind_slots(self) -> None:
        for combo in (*self.simple_psb_combos.values(), *self.detail_psb_combos.values()):
            combo.currentIndexChanged.connect(self._on_slot_changed)

    def _source_mode(self) -> str:
        return "gif" if self._source_stack.currentIndex() == 0 else "psb"

    def _on_source_mode_changed(self, route_key: str) -> None:
        is_gif = route_key == "gif"
        self._source_stack.setCurrentIndex(0 if is_gif else 1)
        self._core_host.setVisible(True)
        self._update_action_mode()
        self._preview_btn.setVisible(not is_gif)
        self._preview_status.setText(
            "图标：自动使用 GIF 首帧生成"
            if is_gif
            else "图标：未生成（可选；也可稍后手动补入）"
        )
        self._placement_accuracy.setText(
            "GIF 已按所有帧的透明边界裁切；拖动位置和缩放使用游戏实际坐标链。"
            if is_gif
            else "XML 坐标链已精确还原；原生 PSB 的内部骨骼、部件和画布边界只有 E-mote 运行时能完整渲染，剪影仅表示典型范围。"
        )
        self._source_card.show()
        self._details_host.hide()
        self._generate_btn.setText(
            "从 GIF 生成并写入 ACUS" if is_gif else "从 PSB 生成并写入 ACUS"
        )

    def _show_source_editor(self) -> None:
        self._details_host.hide()
        self._source_card.show()
        self.resize(max(980, self.minimumSizeHint().width()), 650)

    def _browse_gif(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择动态 GIF", "", "GIF 动画 (*.gif)")
        if not path:
            return
        self.gif_path_edit.setText(path)
        self._prepare_gif_preview()

    def _prepare_gif_preview(self) -> None:
        path = self.gif_path_edit.text().strip()
        if not Path(path).is_file():
            return
        if self._gif_thread is not None and self._gif_thread.isRunning():
            self._status.setText("正在分析上一项 GIF，请稍候…")
            return
        gif_path = Path(path)
        target_fps = self.gif_fps_spin.value()
        target_height = int(self.gif_height_combo.currentData() or 384)
        self._status.setText("正在后台分析 GIF 帧与透明边界…")
        self._gif_plan_label.setText("正在计算真实输出计划…")
        self.gif_path_edit.setEnabled(False)
        self.gif_fps_spin.setEnabled(False)
        self.gif_height_combo.setEnabled(False)
        worker = _TaskWorker(
            lambda _progress: inspect_gif(
                gif_path, target_fps=target_fps, target_height=target_height
            ),
            self,
        )
        self._gif_thread = worker
        state: dict[str, object] = {}
        worker.done.connect(lambda result: state.update(result=result))
        worker.failed.connect(lambda error: state.update(error=error))

        def finish() -> None:
            self._gif_thread = None
            self.gif_path_edit.setEnabled(True)
            self.gif_fps_spin.setEnabled(True)
            self.gif_height_combo.setEnabled(True)
            error = state.get("error")
            if error is not None:
                self._gif_plan = None
                self._gif_plan_label.setText("GIF 分析失败")
                self._status.setText("GIF 分析失败，可更换文件后重试")
                fly_critical(self.window(), "无法读取 GIF", str(error))
                return
            plan = state.get("result")
            if not isinstance(plan, GifFramePlan):
                return
            self._gif_plan = plan
            self.preview.set_chara_image(gif_path, plan.crop_box)
            self.preview.set_source_size(*plan.output_size)
            recommended = recommended_scale_for_height(
                plan.output_size[1], calibration=self._calibration
            )
            self.scale_spin.setValue(
                max(self.scale_spin.minimum(), min(self.scale_spin.maximum(), recommended))
            )
            cap = "；已触发 120 帧上限，实际帧率会降低" if plan.capped else ""
            self._gif_plan_label.setText(
                f"源 {plan.source_frame_count} 帧 / {plan.duration_seconds:.2f} 秒 → "
                f"输出 {plan.output_frame_count} 帧 / {plan.effective_fps:.1f} FPS / "
                f"{plan.output_size[0]}×{plan.output_size[1]}{cap}"
            )
            self._source_card.hide()
            self._details_host.show()
            if self.height() < 780:
                self.resize(max(self.width(), 1120), 820)
            self._status.setText("GIF 已就绪；预览已按游戏实际坐标链换算")

        worker.finished.connect(finish)
        worker.start()

    def _gif_options_changed(self, _value=None) -> None:
        if self.gif_path_edit.text().strip():
            self._prepare_gif_preview()

    def _load_game_background(self) -> None:
        """Decode the installed game's result layers without blocking Qt."""
        if self._game_root is None or self._background_thread is not None:
            return
        texture_dir = (
            self._game_root
            / "data"
            / "surfboard"
            / "texture"
        )
        sources = {
            "background": texture_dir / "CHU_UI_Common_BK_00_Mate.dds",
            "result": texture_dir / "CHU_UI_Result_01_v16.dds",
            "score": texture_dir / "CHU_UI_Result_score_00.dds",
            "rank": texture_dir / "CHU_UI_Result_Rank_00.dds",
            "mate_room_bg": texture_dir / "CHU_UI_MateGarden_bg_00.dds",
            "mate_room_title": texture_dir / "CHU_UI_MateGarden_bg_01.dds",
            "mate_room": texture_dir / "CHU_UI_MateGarden_00.dds",
        }
        if not sources["background"].is_file():
            return
        tool_path = self._get_tool_path() if self._get_tool_path else None

        def decode_result_layers(_progress) -> dict[str, Path | None]:
            return {
                name: ensure_dds_preview_png(
                    acus_root=self._acus_root,
                    compressonatorcli_path=tool_path,
                    dds_path=dds,
                )
                if dds.is_file()
                else None
                for name, dds in sources.items()
            }

        worker = _TaskWorker(
            decode_result_layers,
            self,
        )
        self._background_thread = worker
        state: dict[str, object] = {}
        worker.done.connect(lambda result: state.update(result=result))

        def finish() -> None:
            self._background_thread = None
            paths = state.get("result")
            if isinstance(paths, dict):
                background = paths.get("background")
                if isinstance(background, Path):
                    self.preview.set_background(background)
                self.preview.set_result_overlay_assets(paths)

        worker.finished.connect(finish)
        worker.start()

    def _on_slot_changed(self, _idx: int) -> None:
        if self._action_mode_switch.isChecked():
            overrides = sum(bool(combo.currentData()) for combo in self.detail_psb_combos.values())
            self._status.setText(f"详细配置：已覆盖 {overrides} / 18 个槽，其余继承简略模式")
        else:
            selected = sum(bool(combo.currentData()) for combo in self.simple_psb_combos.values())
            self._status.setText(f"简略配置：已选择 {selected} / 6 个场景组")

    # ---- 关联角色 ----------------------------------------------------------

    def _reload_charas(self, *, prefer_id: int | None = None) -> None:
        self.chara_combo.blockSignals(True)
        self.chara_combo.clear()
        try:
            items = scan_charas(self._acus_root)
        except Exception:
            items = []
        select_idx = 0
        for i, it in enumerate(items):
            label = f"{it.name.id} · {it.name.str}（{it.default_image_key}）"
            self.chara_combo.addItem(label, userData=(it.name.id, it.name.str, it.default_image_key))
            if prefer_id is not None and it.name.id == prefer_id:
                select_idx = i
        if self.chara_combo.count() == 0:
            self.chara_combo.addItem("（ACUS 里还没有角色，点「新建…」）", userData=None)
        self.chara_combo.setCurrentIndex(select_idx)
        self.chara_combo.blockSignals(False)

    def _new_chara(self) -> None:
        existing = {it.name.id for it in scan_charas(self._acus_root)}
        dlg = CharaAddDialog(
            acus_root=self._acus_root,
            tool_path=self._get_tool_path() if self._get_tool_path else None,
            parent=self.window(),
            locked_variant=0,
            variant_lock_reason="new_chara",
        )
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        created = [i for i in ({it.name.id for it in scan_charas(self._acus_root)}) if i not in existing]
        self._reload_charas(prefer_id=created[-1] if created else None)
        self._status.setText("角色已创建，已自动选为关联角色")

    def _current_chara(self) -> tuple[int, str, str] | None:
        data = self.chara_combo.currentData()
        if not data:
            return None
        cid, cname, key = data
        return int(cid), str(cname), str(key)

    def reject(self) -> None:  # noqa: D102
        if self._is_busy():
            self._status.setText("正在处理素材，完成后即可关闭；窗口仍可正常移动和刷新。")
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._is_busy():
            event.ignore()
            self._status.setText("正在处理素材，完成后即可关闭；不会在后台留下隐藏窗口。")
            return
        super().closeEvent(event)

    def _is_busy(self) -> bool:
        return any(
            thread is not None and thread.isRunning()
            for thread in (
                self._fetch_thread,
                self._build_thread,
                self._gif_thread,
                self._background_thread,
                self._models_thread,
            )
        )

    # ---- 系统语音 ----------------------------------------------------------

    def _reload_voices(self) -> None:
        self.voice_combo.blockSignals(True)
        self.voice_combo.clear()
        self.voice_combo.addItem("不绑定（systemVoiceId=0，无语音）", userData=0)
        try:
            items = scan_system_voices(self._acus_root)
        except Exception:
            items = []
        for it in items:
            self.voice_combo.addItem(
                f"{it.name.id} · {it.name.str}", userData=int(it.name.id))
        self.voice_combo.setCurrentIndex(0)
        self.voice_combo.blockSignals(False)

    # ---- PSB 加载 ----------------------------------------------------------

    def _browse_psb(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "选择 PSB", "", "PSB (*.psb);;All (*)")
        if p:
            self.psb_path_edit.setText(p)

    def _fetch_models(self) -> None:
        """从 lolicount 拉取在线模型列表（后台线程，避免网络阻塞 GUI）。"""
        if self._models_thread is not None and self._models_thread.isRunning():
            self._status.setText("正在获取在线模型列表…")
            return
        self._refresh_models_btn.setEnabled(False)
        self._status.setText("正在获取在线模型列表…")

        worker = _TaskWorker(lambda _progress: _LolicountClient().list_models(), self)
        self._models_thread = worker
        state: dict[str, object] = {}
        worker.done.connect(lambda result: state.update(models=result))

        def _finish() -> None:
            self._models_thread = None
            self._refresh_models_btn.setEnabled(True)
            models = state.get("models")
            if not isinstance(models, list):
                return
            if not models:
                fly_critical(self.window(), "提示", "在线仓库为空")
                return
            self.model_combo.blockSignals(True)
            self.model_combo.clear()
            for m in models:
                self.model_combo.addItem(str(m), userData=str(m))
            self.model_combo.blockSignals(False)
            self._status.setText(f"在线仓库共 {len(models)} 个模型，选择后点「下载并解析」")

        def _fail(msg: str) -> None:
            self._models_thread = None
            self._refresh_models_btn.setEnabled(True)
            fly_critical(self.window(), "获取列表失败", f"{msg}\n\n请检查网络连接。")

        worker.done.connect(lambda _result: _finish())
        worker.failed.connect(_fail)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _download_online(self) -> None:
        """下载选中的 lolicount 模型并进入解析（后台线程）。"""
        model = self.model_combo.currentData()
        if not model:
            fly_critical(self.window(), "提示", "请先「获取列表」并选择模型")
            return
        dest = Path(tempfile.gettempdir()) / "chuni_eventer_psb" / f"{model}.psb"
        self._run_fetch(
            f"正在下载 {model} …",
            lambda: _LolicountClient().download(model, dest),
            lambda psb: f"下载完成，正在解包 {psb.name} …",
        )

    def _load_psb(self) -> None:
        psb = Path(self.psb_path_edit.text().strip())
        if not psb.is_file():
            fly_critical(self.window(), "错误", "PSB 文件不存在")
            return
        self._run_fetch(
            f"正在解包 {psb.name} …",
            lambda: psb,
            lambda _p: "",
        )

    def _run_fetch(self, start_msg: str, step_download, running_msg) -> None:
        """后台执行 下载(可选)+解包；完成后回主线程填充 UI。"""
        if self._fetch_thread is not None and self._fetch_thread.isRunning():
            self._status.setText("上一次解析还在进行中，请稍候…")
            return

        def _work():
            psb_path = step_download()
            if running_msg(psb_path):
                pass  # 跨线程不能直接改 UI, 提示由完成回调统一处理
            work_dir = psb_path.parent / "_psb_import_tmp"
            data = self._assigner.decompile(psb_path, work_dir)
            return psb_path, data

        class _Worker(QThread):
            done = pyqtSignal(object)
            failed = pyqtSignal(str)

            def run(self):  # noqa: D102
                try:
                    self.done.emit(_work())
                except Exception as e:  # noqa: BLE001
                    self.failed.emit(f"{type(e).__name__}: {e}")

        self._status.setText(start_msg)
        w = _Worker(self)
        self._fetch_thread = w

        def _on_done(result):
            psb_path, data = result
            self._psb_path = psb_path
            self._psb_data = data
            self._finish_load()

        def _on_fail(msg):
            self._status.setText("解析失败")
            fly_critical(self.window(), "解析失败", f"{msg}\n\n模型过大/网络中断都可能引起，可重试或换小模型。")

        w.done.connect(_on_done)
        w.failed.connect(_on_fail)
        w.finished.connect(lambda: setattr(self, "_fetch_thread", None))
        w.start()

    def _finish_load(self) -> None:
        """解析完成后的 UI 填充（主线程）。"""
        if self._psb_data is None or self._psb_path is None:
            return
        if not self._psb_data.timelines:
            fly_critical(self.window(), "错误", "PSB 中没有 timeline（可能是空模型）")
            return
        self.psb_path_edit.setText(str(self._psb_path))

        for combo in (*self.simple_psb_combos.values(), *self.detail_psb_combos.values()):
            while combo.count() > 1:
                combo.removeItem(1)
            for tl in self._psb_data.timelines:
                if tl.label.strip().startswith("-----"):
                    continue
                tag = "主" if tl.diff == 0 else "差"
                combo.addItem(f"[{tag}] {tl.label}", userData=tl.label)

        self._apply_template()
        if self._source_mode() == "psb":
            # XML transforms the E-mote authored screen, not its packed texture
            # atlas.  Use the PSB declaration (official Vanilla is 800x1080)
            # rather than a made-up human silhouette envelope.
            self.preview.set_source_size(*(self._psb_data.screen_size or (800, 1080)))
            self.preview.set_chara_image(None)
            self._source_card.hide()
            self._details_host.show()
            if self.height() < 780:
                self.resize(max(self.width(), 1120), 820)
        self._status.setText(
            f"平台 {self._psb_data.platform} · 主 {len(self._psb_data.main_timelines)} 条 / "
            f"差分 {len(self._psb_data.diff_timelines)} 条 — 已按场景组预分配，可切换详细配置")

    def _apply_template(self) -> None:
        """按关键词给场景槽预填默认值。"""
        if not self._psb_data:
            return
        labels = [t.label for t in self._psb_data.timelines]
        rules: dict[str, list[str]] = {
            "rank_d_bbb": ["哀しい00", "哀0", "哀しみ", "怒る00", "怒0", "怒り", "sample_哀", "sample_怒"],
            "rank_a_aaa": ["喜ぶ00", "喜0", "喜び", "sample_喜"],
            "rank_s_ss": ["喜ぶ02", "喜02", "喜ぶ00", "喜0", "sample_喜"],
            "rank_ssp_sssp": ["喜ぶ01", "喜01", "喜ぶ02", "喜02", "sample_喜"],
            "default_room_edges": ["平常", "初期化", "通常待機", "待機ループ", "waiting"],
            "room_loop": ["喜ぶ02", "喜02", "喜ぶ00", "喜0", "sample_喜"],
        }
        for key, kws in rules.items():
            found = ""
            for kw in kws:
                for lb in labels:
                    if kw in lb:
                        found = lb
                        break
                if found:
                    break
            combo = self.simple_psb_combos[key]
            combo.setCurrentIndex(combo.findData(found) if found else 0)
        for combo in self.detail_psb_combos.values():
            combo.setCurrentIndex(0)

    # ---- 参数联动 ----------------------------------------------------------

    def _on_param_changed(self) -> None:
        self.preview.set_params(self.pos_x_spin.value(), self.pos_y_spin.value(),
                                self.scale_spin.value())

    def _on_preview_drag(self, px: int, py: int, sc: int) -> None:
        self.pos_x_spin.blockSignals(True)
        self.pos_y_spin.blockSignals(True)
        self.scale_spin.blockSignals(True)
        self.pos_x_spin.setValue(px)
        self.pos_y_spin.setValue(py)
        self.scale_spin.setValue(sc)
        self.pos_x_spin.blockSignals(False)
        self.pos_y_spin.blockSignals(False)
        self.scale_spin.blockSignals(False)

    def _make_preview_icon(self) -> None:
        dlg = MatePreviewDialog(acus_root=self._acus_root, parent=self.window())
        if dlg.exec() != dlg.DialogCode.Accepted or dlg.result_png_path is None:
            return
        self._preview_png = dlg.result_png_path
        self._preview_status.setText(f"图标：已生成 {self._preview_png.name}")

    def _pick_background(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "选择游戏截图", "", "图片 (*.png *.jpg *.jpeg *.bmp)")
        if p:
            self.preview.set_background(Path(p))

    # ---- 生成部署 ----------------------------------------------------------

    def _generate(self) -> None:
        if self._is_busy():
            self._status.setText("已有任务正在处理，请稍候…")
            return
        if self._source_mode() == "gif":
            self._generate_gif()
        else:
            self._generate_psb()

    def _validated_identity(self) -> tuple[int, str, int, str, str] | None:
        chara = self._current_chara()
        if chara is None:
            fly_critical(self.window(), "错误", "请选择关联角色（或点「新建…」先创建一个）")
            return None
        chara_id, chara_name, dds_illust_key = chara
        mate_id = self.mate_id_edit.value()
        name = self.name_edit.text().strip() or chara_name
        return mate_id, name, chara_id, chara_name, dds_illust_key

    def _generate_gif(self) -> None:
        identity = self._validated_identity()
        if identity is None:
            return
        gif_path = Path(self.gif_path_edit.text().strip())
        if not gif_path.is_file():
            fly_critical(self.window(), "错误", "请先选择一张动态 GIF")
            return
        simple_paths: dict[str, Path] = {}
        for group in SIMPLE_ACTION_GROUPS:
            text = self.simple_gif_edits[group.key].text().strip()
            path = Path(text) if text else gif_path
            if not path.is_file():
                fly_critical(self.window(), "错误", f"{group.title} 的 GIF 不存在：{path}")
                return
            simple_paths[group.key] = path
        detailed_paths: dict[int, Path] = {}
        if self._action_mode_switch.isChecked():
            for slot, edit in self.detail_gif_edits.items():
                text = edit.text().strip()
                if not text:
                    continue
                path = Path(text)
                if not path.is_file():
                    fly_critical(self.window(), "错误", f"Type {slot} 的 GIF 不存在：{path}")
                    return
                detailed_paths[slot] = path
        slot_gif_paths = expand_action_assignments(simple_paths, detailed_paths)
        template_path = find_gif_mate_template(self._acus_root)
        if template_path is None:
            fly_critical(
                self.window(),
                "缺少兼容骨架",
                "当前 ACUS 中没有可复用的 Mate 动画。请先导入任意一个 PSB Mate；之后 GIF、Live2D 和 Spine 都会自动复用它，不需要再次选择。",
            )
            return
        mate_id, name, chara_id, chara_name, dds_illust_key = identity
        request = GifMateCreateRequest(
            acus_root=self._acus_root,
            freemote_dir=self._freemote_dir,
            gif_path=gif_path,
            template_emtbytes=template_path,
            mate_id=mate_id,
            name=name,
            chara_id=chara_id,
            chara_name=chara_name,
            dds_illust_key=dds_illust_key,
            system_voice_id=int(self.voice_combo.currentData() or 0),
            pos_x=self.pos_x_spin.value(),
            pos_y=self.pos_y_spin.value(),
            scale_x10000=self.scale_spin.value(),
            target_fps=self.gif_fps_spin.value(),
            target_height=int(self.gif_height_combo.currentData() or 384),
            dds_tool_path=self._get_tool_path() if self._get_tool_path else None,
            slot_gif_paths=tuple(sorted(slot_gif_paths.items())),
        )

        def task(progress):
            return create_gif_mate(request, progress=progress)

        def message(result):
            return (
                f"已写入 {result.mate_dir}\n\n"
                f"GIF 动作：{result.animation_count} 条 · 共 {result.frame_count} 帧 · "
                f"最大画布 {result.frame_size[0]}×{result.frame_size[1]} · "
                f"{result.effective_fps:.1f} FPS\n"
                "已生成 E-mote、Mate.xml 与 BC3 图标。"
            )

        self._run_build(task, message)

    def _generate_psb(self) -> None:
        if self._psb_data is None or self._psb_path is None:
            fly_critical(self.window(), "错误", "请先解析 PSB")
            return
        identity = self._validated_identity()
        if identity is None:
            return
        mate_id, name, chara_id, chara_name, dds_illust_key = identity
        simple = {key: combo.currentData() for key, combo in self.simple_psb_combos.items()}
        missing = [group.title for group in SIMPLE_ACTION_GROUPS if not simple.get(group.key)]
        if missing:
            fly_critical(self.window(), "错误", f"简略模式还有动作没选：{'、'.join(missing)}")
            return
        detailed = (
            {slot: combo.currentData() for slot, combo in self.detail_psb_combos.items()}
            if self._action_mode_switch.isChecked()
            else None
        )
        slot_assignments = expand_action_assignments(simple, detailed)

        xml_str = generate_mate_xml(
            mate_id=mate_id,
            name=name,
            chara_id=chara_id,
            chara_name=chara_name,
            emote_filename=f"emote{mate_id:06d}.emtbytes",
            dds_filename=f"CHU_UI_Mate_{mate_id:06d}.dds",
            slot_assignments=slot_assignments,
            dds_illust_key=dds_illust_key,
            system_voice_id=int(self.voice_combo.currentData() or 0),
            pos_x=self.pos_x_spin.value(),
            pos_y=self.pos_y_spin.value(),
            scale_x10000=self.scale_spin.value(),
        )
        psb_path = self._psb_path
        preview_png = self._preview_png
        dds_tool = self._get_tool_path() if self._get_tool_path else None
        assigner = self._assigner

        def task(progress):
            mate_dir = self._acus_root / "mate" / f"mate{mate_id:06d}"
            if mate_dir.exists():
                raise FileExistsError(f"Mate ID 已存在：{mate_dir.name}")
            mate_root = mate_dir.parent
            mate_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".psb_mate_", dir=mate_root) as temp_name:
                staged = Path(temp_name) / mate_dir.name
                staged.mkdir()
                progress("正在转换 PSB 到 common 平台…")
                assigner.port_to_common(
                    psb_path, staged / f"emote{mate_id:06d}.emtbytes"
                )
                (staged / "Mate.xml").write_text(xml_str, encoding="utf-8")
                icon_msg = "图标未生成，可稍后补入"
                if preview_png is not None and preview_png.is_file():
                    progress("正在生成 BC3 图标…")
                    ingest_to_bc3_dds(
                        tool_path=dds_tool,
                        input_path=preview_png,
                        output_dds=staged / f"CHU_UI_Mate_{mate_id:06d}.dds",
                    )
                    icon_msg = "BC3 图标已生成"
                progress("正在写入 ACUS…")
                os.replace(staged, mate_dir)
            return mate_dir, icon_msg

        def message(result):
            mate_dir, icon_msg = result
            return (
                f"已写入 {mate_dir}\n\n"
                f"emote{mate_id:06d}.emtbytes（common 平台）\n"
                f"Mate.xml（关联 chara {chara_id} · {chara_name}）\n"
                f"{icon_msg}"
            )

        self._run_build(task, message)

    def _run_build(self, task, message_factory) -> None:
        """Start one conversion and finalize only after its QThread has stopped."""
        self._generate_btn.setEnabled(False)
        self._status.setText("正在准备转换…")
        worker = _TaskWorker(task, self)
        self._build_thread = worker
        state: dict[str, object] = {}
        worker.progress.connect(self._status.setText)
        worker.done.connect(lambda result: state.update(result=result))
        worker.failed.connect(lambda error: state.update(error=error))

        def finish() -> None:
            self._build_thread = None
            self._generate_btn.setEnabled(True)
            error = state.get("error")
            if error is not None:
                self._status.setText("生成失败，可调整后重试")
                fly_critical(self.window(), "生成失败", str(error))
                return
            result = state.get("result")
            if result is None:
                self._status.setText("任务意外结束")
                return
            message = message_factory(result)
            notify_parent = self.parentWidget()
            self.accept()
            if notify_parent is not None:
                fly_message(notify_parent, "完成", message)

        worker.finished.connect(finish)
        worker.start()
