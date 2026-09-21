"""PSB 动作分配对话框：上传/在线获取 PSB → 可视化分配动作槽 → 位置预览 → 生成部署。"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPixmap, QLinearGradient
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSpinBox,
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
)

from ..acus_scan import scan_charas, scan_system_voices
from ..dds_convert import DdsToolError, ingest_to_bc3_dds
from ..psb_action_assigner import (
    PsbActionAssigner,
    PsbActionData,
    generate_mate_xml,
)
from .chara_add_dialog import CharaAddDialog
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical
from .mate_preview_dialog import MatePreviewDialog


# ---------------------------------------------------------------------------
# lolicount 在线模型仓库接口
# ---------------------------------------------------------------------------

LOLICOUNT_API_BASE = "https://lolicount.top"


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

# 实测标定（mate031004 红豆, 1080p 游戏截图对照）:
#   scale=6000 时角色显示高约 980px  → 显示高 = scale * 0.163
#   posY=-50 刚好(脚底离屏底约50px), posY=-130 裁头, +100 裁脚
#   → 底边 y = 1080 + posY (负值上移)
#   posX=1 时角色中心约在 x=1620 → 中心 x = 1520 + posX*100 (近似)
_CHARA_H_PER_SCALE = 0.163
_CHARA_BASE_X = 1520
_CHARA_X_PER_POS = 100
_LOGICAL_W, _LOGICAL_H = 1920, 1080


class MatePositionPreview(QWidget):
    """16:9 预览画布：显示 mate 在游戏画面里的大概位置/大小，支持拖动。"""

    positionChanged = pyqtSignal(int, int, int)  # posX, posY, scale

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bg: QPixmap | None = None
        self._chara: QPixmap | None = None
        self._pos_x = 1
        self._pos_y = -50
        self._scale = 6000
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

    def set_chara_image(self, path: Path | None) -> None:
        if path and Path(path).is_file():
            self._chara = QPixmap(str(path))
        else:
            self._chara = None
        self.update()

    def chara_rect(self) -> QRectF:
        """角色在 1920x1080 逻辑坐标里的矩形。"""
        h = self._scale * _CHARA_H_PER_SCALE
        bottom = _LOGICAL_H + self._pos_y
        cx = _CHARA_BASE_X + self._pos_x * _CHARA_X_PER_POS
        if self._chara is not None and not self._chara.isNull():
            ratio = self._chara.width() / max(1, self._chara.height())
        else:
            ratio = 0.45  # 人形占位剪影的宽高比
        w = h * ratio
        return QRectF(cx - w / 2, bottom - h, w, h)

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

        # 背景
        if self._bg is not None and not self._bg.isNull():
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
                             "游戏结算画面 (示意) — 可加载自己的截图做背景")

        # 角色
        rect = self.chara_rect()
        head_clipped = rect.top() < 0
        feet_clipped = rect.bottom() > _LOGICAL_H
        if self._chara is not None and not self._chara.isNull():
            painter.drawPixmap(rect, self._chara, QRectF(self._chara.rect()))
        else:
            self._draw_placeholder_figure(painter, rect)

        # 溢出警告
        f = QFont()
        f.setPixelSize(36)
        painter.setFont(f)
        warn = None
        if head_clipped:
            warn = "⚠ 头部超出屏幕顶端（游戏内会被裁剪）— 减小 posY 绝对值"
        elif feet_clipped:
            warn = "⚠ 脚部超出屏幕底端 — 增大 posY"
        if warn:
            painter.setPen(QColor(200, 30, 30))
            painter.drawText(QRectF(40, 20, _LOGICAL_W - 80, 60),
                             Qt.AlignmentFlag.AlignLeft, warn)

        # 边框
        painter.setPen(QPen(QColor(60, 60, 60), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(0, 0, _LOGICAL_W, _LOGICAL_H)

    def _draw_placeholder_figure(self, painter: QPainter, rect: QRectF) -> None:
        """画一个简洁的人形剪影，表示角色的位置和大小（相对关系示意）。"""
        from PyQt6.QtGui import QPainterPath

        w, h = rect.width(), rect.height()
        x, y = rect.left(), rect.top()
        cx = x + w / 2
        head_r = w * 0.30

        path = QPainterPath()
        # 头
        path.addEllipse(QPointF(cx, y + head_r), head_r, head_r)
        # 脖子 + 上身
        body_top = y + head_r * 2.0
        body = QPainterPath()
        body.moveTo(cx - w * 0.24, body_top)
        body.quadTo(cx, body_top + h * 0.02, cx + w * 0.24, body_top)
        body.lineTo(cx + w * 0.30, y + h * 0.58)
        body.lineTo(cx - w * 0.30, y + h * 0.58)
        body.closeSubpath()
        path.addPath(body)
        # 裙摆/下身
        skirt = QPainterPath()
        skirt.moveTo(cx - w * 0.30, y + h * 0.58)
        skirt.lineTo(cx + w * 0.30, y + h * 0.58)
        skirt.lineTo(cx + w * 0.38, y + h * 0.78)
        skirt.lineTo(cx - w * 0.38, y + h * 0.78)
        skirt.closeSubpath()
        path.addPath(skirt)
        # 双腿
        for sign in (-1, 1):
            leg = QPainterPath()
            lx = cx + sign * w * 0.16
            leg.addRoundedRect(QRectF(lx - w * 0.09, y + h * 0.78, w * 0.18, h * 0.22), 4, 4)
            path.addPath(leg)

        painter.fillPath(path, QColor(110, 150, 225, 95))
        pen = QPen(QColor(70, 110, 190, 220), 3)
        painter.setPen(pen)
        painter.drawPath(path)

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
            self._drag_offset = QPointF(lp.x() - self.chara_rect().center().x(),
                                        lp.y() - self.chara_rect().bottom())
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._dragging:
            return
        lp = self._to_logical(QPointF(event.position()))
        new_cx = lp.x() - self._drag_offset.x()
        new_bottom = lp.y() - self._drag_offset.y()
        self._pos_x = round((new_cx - _CHARA_BASE_X) / _CHARA_X_PER_POS)
        self._pos_y = round(new_bottom - _LOGICAL_H)
        self.update()
        self.positionChanged.emit(self._pos_x, self._pos_y, self._scale)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.positionChanged.emit(self._pos_x, self._pos_y, self._scale)


class PsbActionDialog(FluentCaptionDialog):
    """PSB → mate 全流程对话框。"""

    def __init__(self, *, acus_root: Path, freemote_dir: Path, mate_id: int,
                 chara_id: int = 80000, get_tool_path=None, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("新增伴侣（PSB 导入）")
        self.setModal(True)
        self.resize(1240, 820)

        self._acus_root = acus_root
        self._freemote_dir = freemote_dir
        self._mate_id = mate_id
        self._assigner = PsbActionAssigner(freemote_dir)
        self._psb_data: PsbActionData | None = None
        self._work_dir: Path | None = None
        self._psb_path: Path | None = None
        self._get_tool_path = get_tool_path
        self._preview_png: Path | None = None
        self._fetch_thread = None

        # ---- 控件 ----
        self.psb_path_edit = LineEdit(self)
        self.psb_path_edit.setPlaceholderText("选择本地 PSB 文件")
        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText("伴侣显示名，例如 アズキ")
        self.mate_id_edit = QSpinBox(self)
        self.mate_id_edit.setRange(1, 999999)
        self.mate_id_edit.setValue(mate_id)
        self.chara_combo = FluentComboBox(self)
        self._reload_charas(prefer_id=chara_id)
        chara_row = QWidget(self)
        ch_h = QHBoxLayout(chara_row)
        ch_h.setContentsMargins(0, 0, 0, 0)
        ch_h.setSpacing(8)
        ch_h.addWidget(self.chara_combo, stretch=1)
        self.chara_new_btn = PushButton("新建…", self)
        self.chara_new_btn.clicked.connect(self._new_chara)
        ch_h.addWidget(self.chara_new_btn)

        self.pos_x_spin = QSpinBox(self)
        self.pos_x_spin.setRange(-500, 500)
        self.pos_x_spin.setValue(1)
        self.pos_y_spin = QSpinBox(self)
        self.pos_y_spin.setRange(-1000, 500)
        self.pos_y_spin.setValue(-50)
        self.scale_spin = QSpinBox(self)
        self.scale_spin.setRange(1000, 20000)
        self.scale_spin.setValue(6000)

        self.preview = MatePositionPreview(self)

        # 4 个核心动作选择（按官方规律自动展开成 18 个槽）
        self.core_combos: dict[str, QComboBox] = {}
        core_group = QGroupBox("动作匹配：从模型动画列表里选出 4 个", self)
        core_form = QFormLayout(core_group)
        core_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        core_defs: tuple[tuple[str, str, str], ...] = (
            ("idle", "待机 idle", "平时站立循环（呼吸/眨眼），出场默认动作"),
            ("angry", "生气", "游戏内生气场景"),
            ("sad", "悲伤", "游戏内难过场景"),
            ("happy", "开心", "其余大部分场景（欢呼/高兴）都会用这个"),
        )
        for key, title, desc in core_defs:
            combo = QComboBox(self)
            combo.addItem("（未选择）", userData="")
            self.core_combos[key] = combo
            cap = QLabel(self)
            cap.setText(f"<b>{title}</b><br><span style='color:#6B7280'>{desc}</span>")
            core_form.addRow(cap, combo)
        core_tip = CaptionLabel(
            "生成时按官方 mate 规律展开：Type1=待机，Type2=生气，Type3=悲伤，"
            "Type4~18 全部=开心（官方原版也是这样复用，无需逐槽挑选）。", self)
        core_tip.setWordWrap(True)
        core_lay = QVBoxLayout()
        core_lay.addWidget(core_group)
        core_lay.addWidget(core_tip)
        core_lay.addStretch(1)
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
        src_lay.addWidget(BodyLabel("① PSB 来源", self))
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
        src_lay.addWidget(psb_row)
        url_row = QWidget(self)
        ur_h = QHBoxLayout(url_row)
        ur_h.setContentsMargins(0, 0, 0, 0)
        ur_h.setSpacing(8)
        self.model_combo = QComboBox(self)
        self.model_combo.addItem("（点击「获取列表」从 lolicount 拉取在线模型）", userData="")
        ur_h.addWidget(self.model_combo, stretch=1)
        refresh_btn = PushButton("获取列表", self)
        refresh_btn.clicked.connect(self._fetch_models)
        ur_h.addWidget(refresh_btn)
        dl_btn = PushButton("下载并解析", self)
        dl_btn.clicked.connect(self._download_online)
        ur_h.addWidget(dl_btn)
        src_lay.addWidget(url_row)
        self.voice_combo = FluentComboBox(self)
        self._reload_voices()
        info_form = QFormLayout()
        info_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        info_form.addRow("伴侣显示名", self.name_edit)
        info_form.addRow("Mate ID", self.mate_id_edit)
        info_form.addRow("关联角色 Chara", chara_row)
        info_form.addRow("系统语音 SystemVoice", self.voice_combo)
        src_lay.addLayout(info_form)
        src_lay.addWidget(CaptionLabel(
            "伴侣在游戏内的名字/立绘来自关联角色：可选现有角色，或点「新建…」先建一个角色再回来选。", self))
        src_lay.addWidget(CaptionLabel(
            "系统语音决定语音包（无语音模型选「不绑定」即可，官方イクシア同款填法）；不提供在此新增。", self))
        src_lay.addWidget(CaptionLabel(
            "解析后自动列出模型内全部动作（主/差分），并按官方模板预分配；可手动调整每个槽。", self))
        layout.addWidget(src_card)

        mid = QHBoxLayout()
        # 左: 预览
        prev_card = CardWidget(self)
        pv_lay = QVBoxLayout(prev_card)
        pv_lay.setContentsMargins(16, 12, 16, 12)
        pv_lay.setSpacing(8)
        pv_lay.addWidget(BodyLabel("② 位置预览（拖动角色调整，或用右侧数值）", self))
        self.preview.positionChanged.connect(self._on_preview_drag)
        pv_lay.addWidget(self.preview, stretch=1)
        bg_row = QHBoxLayout()
        preview_btn = PushButton("生成预览图…", self)
        preview_btn.clicked.connect(self._make_preview_icon)
        bg_row.addWidget(preview_btn)
        self._preview_status = CaptionLabel("图标：未生成（生成伴侣时若无预览图则跳过图标）", self)
        bg_row.addWidget(self._preview_status, stretch=1)
        bg_btn = PushButton("加载游戏截图做背景…", self)
        bg_btn.clicked.connect(self._pick_background)
        bg_row.addWidget(bg_btn)
        pv_lay.addLayout(bg_row)

        param_form = QFormLayout()
        param_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for w, tip in ((self.pos_x_spin, "水平位置（游戏内像素偏移·近似）"),
                       (self.pos_y_spin, "垂直位置（脚底相对屏幕底部, 负值上移）"),
                       (self.scale_spin, "缩放 (万分之一, 6000=0.6 倍)")):
            w.valueChanged.connect(self._on_param_changed)
            param_form.addRow(tip, w)
        pv_lay.addLayout(param_form)
        self.preview.set_params(1, -50, 6000)

        mid.addWidget(prev_card, stretch=3)
        mid.addWidget(core_host, stretch=2)
        layout.addLayout(mid, stretch=1)

        btns = QHBoxLayout()
        self._status = CaptionLabel("", self)
        btns.addWidget(self._status, stretch=1)
        cancel = PushButton("取消", self)
        cancel.clicked.connect(self.reject)
        gen = PrimaryPushButton("生成并写入 ACUS", self)
        gen.clicked.connect(self._generate)
        btns.addWidget(cancel)
        btns.addWidget(gen)
        layout.addLayout(btns)

        self._bind_slots()

    # ---- 槽分配联动 --------------------------------------------------------

    def _bind_slots(self) -> None:
        for combo in self.core_combos.values():
            combo.currentIndexChanged.connect(self._on_slot_changed)

    def _on_slot_changed(self, _idx: int) -> None:
        chosen = "、".join(
            f"{title}={cb.currentData() or '？'}"
            for (key, title, _d), cb in zip(
                (("idle", "待机", ""), ("angry", "生气", ""), ("sad", "悲伤", ""), ("happy", "开心", "")),
                self.core_combos.values(),
            )
        )
        self._status.setText(chosen)

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
        if self._fetch_thread is not None and self._fetch_thread.isRunning():
            self._status.setText("正在下载/解析模型，完成后才能关闭。")
            return
        super().reject()

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
        """从 lolicount 拉取在线模型列表。"""
        try:
            models = _LolicountClient().list_models()
        except Exception as e:
            fly_critical(self.window(), "获取列表失败", f"{e}\n\n请检查网络连接。")
            return
        if not models:
            fly_critical(self.window(), "提示", "在线仓库为空")
            return
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for m in models:
            self.model_combo.addItem(m, userData=m)
        self.model_combo.blockSignals(False)
        self._status.setText(f"在线仓库共 {len(models)} 个模型，选择后点「下载并解析」")

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
        from PyQt6.QtCore import QThread

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

        self.setEnabled(False)
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
        w.finished.connect(lambda: (self.setEnabled(True), setattr(self, "_fetch_thread", None)))
        w.start()

    def _finish_load(self) -> None:
        """解析完成后的 UI 填充（主线程）。"""
        if self._psb_data is None or self._psb_path is None:
            return
        if not self._psb_data.timelines:
            fly_critical(self.window(), "错误", "PSB 中没有 timeline（可能是空模型）")
            return
        self.psb_path_edit.setText(str(self._psb_path))

        for combo in self.core_combos.values():
            while combo.count() > 1:
                combo.removeItem(1)
            for tl in self._psb_data.timelines:
                tag = "主" if tl.diff == 0 else "差"
                combo.addItem(f"[{tag}] {tl.label}", userData=tl.label)

        self._apply_template()
        self.preview.set_chara_image(None)
        self._status.setText(
            f"平台 {self._psb_data.platform} · 主 {len(self._psb_data.main_timelines)} 条 / "
            f"差分 {len(self._psb_data.diff_timelines)} 条 — 已按官方模板预分配，可手动微调")

    def _apply_template(self) -> None:
        """按关键词给 4 个核心槽预填默认值。"""
        if not self._psb_data:
            return
        labels = [t.label for t in self._psb_data.timelines]
        rules: dict[str, list[str]] = {
            "idle": ["平常", "初期化", "通常待機", "待機ループ", "waiting"],
            "angry": ["怒る00", "怒0", "怒り", "sample_怒"],
            "sad": ["哀しい00", "哀0", "哀しみ", "sample_哀"],
            "happy": ["喜ぶ00", "喜0", "喜び", "sample_喜"],
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
            combo = self.core_combos[key]
            combo.setCurrentIndex(combo.findData(found) if found else 0)

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
        if self._psb_data is None or self._psb_path is None:
            fly_critical(self.window(), "错误", "请先解析 PSB")
            return
        chara = self._current_chara()
        if chara is None:
            fly_critical(self.window(), "错误", "请选择关联角色（或点「新建…」先创建一个）")
            return
        chara_id, chara_name, dds_illust_key = chara
        core = {k: cb.currentData() for k, cb in self.core_combos.items()}
        missing = [k for k, v in core.items() if not v]
        if missing:
            fly_critical(self.window(), "错误", f"还有动作没选：{missing}（4 个都要从列表里选）")
            return
        # 按官方 mate000101 规律展开成 18 槽
        slot_assignments: dict[int, str] = {
            1: core["idle"],
            2: core["angry"],
            3: core["sad"],
        }
        for s in range(4, 19):
            slot_assignments[s] = core["happy"]

        mate_id = self.mate_id_edit.value()
        name = self.name_edit.text().strip() or chara_name
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

        try:
            mate_dir = self._acus_root / "mate" / f"mate{mate_id:06d}"
            mate_dir.mkdir(parents=True, exist_ok=True)
            emt = mate_dir / f"emote{mate_id:06d}.emtbytes"
            self._assigner.port_to_common(self._psb_path, emt)
            (mate_dir / "Mate.xml").write_text(xml_str, encoding="utf-8")
            icon_msg = "图标：未生成（可在资源包导入或手动放入）"
            if self._preview_png is not None and self._preview_png.is_file():
                tool = self._get_tool_path() if self._get_tool_path else None
                ingest_to_bc3_dds(
                    tool_path=tool,
                    input_path=self._preview_png,
                    output_dds=mate_dir / f"CHU_UI_Mate_{mate_id:06d}.dds",
                )
                icon_msg = f"图标：CHU_UI_Mate_{mate_id:06d}.dds（BC3）"
        except DdsToolError as e:
            fly_critical(self.window(), "图标转换失败", f"{e}\n\nMate.xml/emtbytes 已写入，图标可稍后手动补。")
            return
        except Exception as e:
            fly_critical(self.window(), "部署失败", str(e))
            return

        QMessageBox.information(
            self.window(), "完成",
            f"已写入 {mate_dir}\n\n"
            f"  emote{mate_id:06d}.emtbytes（已转 common 平台）\n"
            f"  Mate.xml（关联 chara {chara_id} · {chara_name}）\n"
            f"  {icon_msg}")
        self.accept()
