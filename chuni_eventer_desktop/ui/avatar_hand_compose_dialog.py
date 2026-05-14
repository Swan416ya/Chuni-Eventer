"""企鹅手部饰物（AvatarAccessory category=5）：左右双图、Tex 左右条拼接、Icon 模板 5.png。"""

from __future__ import annotations

import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from PyQt6.QtCore import QPoint, QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPalette, QPen, QPixmap
from PyQt6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import BodyLabel, CardWidget, LineEdit, PrimaryPushButton, PushButton

from ..acus_scan import scan_avatar_accessories
from ..dds_convert import DdsToolError
from ..dds_preview import dds_to_pixmap
from ..dds_quicktex import quicktex_available
from .avatar_wear_compose_dialog import (
    CANVAS,
    _package_static_avatar_dir,
    _safe_int,
    avatar_accessory_custom_id_band,
    suggest_next_avatar_accessory_id,
    write_avatar_accessory_xml,
)
from .dds_progress import run_bc3_jobs_with_progress
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical
from .name_glyph_preview import wrap_name_input_with_preview

# 1024 画布上左右手导出区（各 290×791）
HAND_L_X, HAND_L_Y = 130, 141
HAND_R_X, HAND_R_Y = 597, 141
HAND_SLOT_W, HAND_SLOT_H = 290, 791
# 官机从中间裁开后左右条横向拼成一张 Tex
HAND_TEX_W = HAND_SLOT_W * 2
HAND_TEX_H = HAND_SLOT_H
# Icon：5.png 上左右各 64×175
ICON_L_X, ICON_L_Y = 51, 60
ICON_R_X, ICON_R_Y = 140, 60
ICON_SIDE_W, ICON_SIDE_H = 64, 175
HAND_CATEGORY = 5


def suggest_next_avatar_hand_id(acus_root: Path) -> int:
    """自制手部（category=5）下一个建议 ID：75000000 起。"""
    return suggest_next_avatar_accessory_id(acus_root, HAND_CATEGORY)


class PenguinHandPairEditorWidget(QWidget):
    """
    1024 逻辑画布：Body → Hand → 左手用户图 → 右手用户图（用户图层在手之上）。
    绿框标出左右导出矩形 (130,141)+(290×791) 与 (597,141)+(290×791)。
    """

    changed = pyqtSignal()

    def __init__(
        self,
        *,
        body_path: Path,
        hand_path: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setMinimumSize(400, 400)
        self.setMouseTracking(True)
        self._body = QPixmap(str(body_path))
        self._hand = QPixmap(str(hand_path))
        if self._body.isNull() or self._hand.isNull():
            raise ValueError(f"无法加载 Body/Hand：{body_path} / {hand_path}")
        self._body = self._body.scaled(
            CANVAS,
            CANVAS,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._hand = self._hand.scaled(
            CANVAS,
            CANVAS,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._cloth_l: QPixmap | None = None
        self._cloth_r: QPixmap | None = None
        self._zoom_l = 1.0
        self._zoom_r = 1.0
        self._ox_l = self._oy_l = 0.0
        self._ox_r = self._oy_r = 0.0
        self._hand_opacity = 1.0
        self._dragging = False
        self._drag_slot = -1  # 0 左 1 右
        self._drag_last = QPoint()

    def set_hand_opacity(self, alpha: float) -> None:
        self._hand_opacity = max(0.0, min(1.0, float(alpha)))
        self.update()

    def _slot_rects(self) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
        return (
            (HAND_L_X, HAND_L_Y, HAND_SLOT_W, HAND_SLOT_H),
            (HAND_R_X, HAND_R_Y, HAND_SLOT_W, HAND_SLOT_H),
        )

    def _which_slot(self, logical: QPointF) -> int:
        x, y = logical.x(), logical.y()
        for i, (sx, sy, sw, sh) in enumerate(self._slot_rects()):
            if sx <= x < sx + sw and sy <= y < sy + sh:
                return i
        return -1

    def _fit_zoom_for_slot(self, pm: QPixmap, sw: int, sh: int) -> float:
        tw = max(1, pm.width())
        th = max(1, pm.height())
        return float(min((sw * 0.92) / tw, (sh * 0.92) / th, 3.5))

    def set_left_pixmap(self, pm: QPixmap | None) -> None:
        self._cloth_l = pm if pm is not None and not pm.isNull() else None
        self._ox_l = self._oy_l = 0.0
        if self._cloth_l is not None:
            self._zoom_l = self._fit_zoom_for_slot(self._cloth_l, HAND_SLOT_W, HAND_SLOT_H)
        self.update()
        self.changed.emit()

    def set_right_pixmap(self, pm: QPixmap | None) -> None:
        self._cloth_r = pm if pm is not None and not pm.isNull() else None
        self._ox_r = self._oy_r = 0.0
        if self._cloth_r is not None:
            self._zoom_r = self._fit_zoom_for_slot(self._cloth_r, HAND_SLOT_W, HAND_SLOT_H)
        self.update()
        self.changed.emit()

    def clear_right_pixmap(self) -> None:
        self.set_right_pixmap(None)

    @property
    def zoom_left(self) -> float:
        return self._zoom_l

    @property
    def zoom_right(self) -> float:
        return self._zoom_r

    def set_zoom_left(self, z: float) -> None:
        z = max(0.05, min(8.0, float(z)))
        if abs(self._zoom_l - z) < 1e-9:
            return
        self._zoom_l = z
        self.update()
        self.changed.emit()

    def set_zoom_right(self, z: float) -> None:
        z = max(0.05, min(8.0, float(z)))
        if abs(self._zoom_r - z) < 1e-9:
            return
        self._zoom_r = z
        self.update()
        self.changed.emit()

    def _view_scale(self) -> tuple[float, float, float]:
        w, h = float(max(1, self.width())), float(max(1, self.height()))
        sc = min(w, h) / float(CANVAS)
        ox = (w - CANVAS * sc) / 2.0
        oy = (h - CANVAS * sc) / 2.0
        return sc, ox, oy

    def _widget_to_logical(self, pos: QPointF) -> QPointF:
        sc, ox, oy = self._view_scale()
        return QPointF((pos.x() - ox) / sc, (pos.y() - oy) / sc)

    def _draw_slot_cloth(
        self,
        p: QPainter,
        rect: tuple[int, int, int, int],
        cloth: QPixmap | None,
        zoom: float,
        ox: float,
        oy: float,
    ) -> None:
        if cloth is None:
            return
        sx, sy, sw, sh = rect
        cx = sx + sw / 2.0 + ox
        cy = sy + sh / 2.0 + oy
        p.save()
        p.translate(cx, cy)
        p.scale(zoom, zoom)
        p.drawPixmap(-cloth.width() // 2, -cloth.height() // 2, cloth)
        p.restore()

    def paintEvent(self, event) -> None:
        del event
        p = QPainter(self)
        p.fillRect(self.rect(), self.palette().color(QPalette.ColorRole.Window))
        sc, ox, oy = self._view_scale()
        p.translate(ox, oy)
        p.scale(sc, sc)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawPixmap(0, 0, self._body)
        p.setOpacity(self._hand_opacity)
        p.drawPixmap(0, 0, self._hand)
        p.setOpacity(1.0)
        left_r, right_r = self._slot_rects()
        self._draw_slot_cloth(p, left_r, self._cloth_l, self._zoom_l, self._ox_l, self._oy_l)
        self._draw_slot_cloth(p, right_r, self._cloth_r, self._zoom_r, self._ox_r, self._oy_r)
        pen = QPen(QColor(56, 189, 248, 180), 2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for sx, sy, sw, sh in (left_r, right_r):
            p.drawRect(sx, sy, sw, sh)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_slot = self._which_slot(self._widget_to_logical(event.position()))
            if self._drag_slot >= 0:
                has = self._cloth_l if self._drag_slot == 0 else self._cloth_r
                if has is not None:
                    self._dragging = True
                    self._drag_last = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging and self._drag_slot >= 0:
            cloth = self._cloth_l if self._drag_slot == 0 else self._cloth_r
            if cloth is not None:
                cur = event.position().toPoint()
                delta = cur - self._drag_last
                self._drag_last = cur
                sc, _, _ = self._view_scale()
                dx = float(delta.x()) / sc
                dy = float(delta.y()) / sc
                if self._drag_slot == 0:
                    self._ox_l += dx
                    self._oy_l += dy
                else:
                    self._ox_r += dx
                    self._oy_r += dy
                self.update()
                self.changed.emit()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._drag_slot = -1
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        slot = self._which_slot(self._widget_to_logical(event.position()))
        if slot < 0:
            return
        cloth = self._cloth_l if slot == 0 else self._cloth_r
        if cloth is None:
            return
        d = event.angleDelta().y()
        if d == 0:
            return
        fac = 1.08 if d > 0 else 1.0 / 1.08
        if slot == 0:
            self.set_zoom_left(self._zoom_l * fac)
        else:
            self.set_zoom_right(self._zoom_r * fac)
        event.accept()

    def render_user_layers_1024(self) -> QImage:
        """仅用户左右图层，全透明 1024。"""
        img = QImage(CANVAS, CANVAS, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self._draw_slot_cloth(p, self._slot_rects()[0], self._cloth_l, self._zoom_l, self._ox_l, self._oy_l)
        self._draw_slot_cloth(p, self._slot_rects()[1], self._cloth_r, self._zoom_r, self._ox_r, self._oy_r)
        p.end()
        return img

    def merged_hand_tex_image(self) -> QImage:
        """左右 (290×791) 裁切后横向拼成 580×791（透明底）。"""
        full = self.render_user_layers_1024()
        left = full.copy(HAND_L_X, HAND_L_Y, HAND_SLOT_W, HAND_SLOT_H)
        right = full.copy(HAND_R_X, HAND_R_Y, HAND_SLOT_W, HAND_SLOT_H)
        out = QImage(HAND_TEX_W, HAND_TEX_H, QImage.Format.Format_ARGB32)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.drawImage(0, 0, left)
        p.drawImage(HAND_SLOT_W, 0, right)
        p.end()
        return out.convertToFormat(QImage.Format.Format_ARGB32)

    def set_from_saved_merged_tex(self, left: QImage, right: QImage | None) -> None:
        """从已写入的 580×791 Tex 左右条恢复编辑（条内 1:1 置于槽中）。"""
        self._cloth_l = QPixmap.fromImage(left) if not left.isNull() else None
        self._cloth_r = (
            QPixmap.fromImage(right) if right is not None and not right.isNull() else None
        )
        self._ox_l = self._oy_l = self._ox_r = self._oy_r = 0.0
        self._zoom_l = 1.0
        if self._cloth_l is not None and (
            self._cloth_l.width() != HAND_SLOT_W or self._cloth_l.height() != HAND_SLOT_H
        ):
            self._zoom_l = self._fit_zoom_for_slot(self._cloth_l, HAND_SLOT_W, HAND_SLOT_H)
        self._zoom_r = 1.0
        if self._cloth_r is not None and (
            self._cloth_r.width() != HAND_SLOT_W or self._cloth_r.height() != HAND_SLOT_H
        ):
            self._zoom_r = self._fit_zoom_for_slot(self._cloth_r, HAND_SLOT_W, HAND_SLOT_H)
        self.update()
        self.changed.emit()

    def has_user_pixmaps(self) -> bool:
        return self._cloth_l is not None or self._cloth_r is not None


class AvatarHandComposeDialog(FluentCaptionDialog):
    """新增/编辑企鹅手部饰物（category=5）。"""

    def __init__(
        self,
        *,
        acus_root: Path,
        tool_path: Path | None,
        edit_xml_path: Path | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self._acus_root = acus_root
        self._tool = tool_path
        self._edit_xml = edit_xml_path
        self._static = _package_static_avatar_dir()
        is_edit = edit_xml_path is not None and edit_xml_path.is_file()
        self._is_edit = is_edit
        self.setWindowTitle("编辑手部饰物" if is_edit else "新增手部饰物")
        self.setModal(True)
        self.resize(940, 900)

        self.id_edit = LineEdit(self)
        self.id_edit.setPlaceholderText("例如 75000001（自制手部：75000000～75999999）")
        if is_edit:
            self.id_edit.setReadOnly(True)
        else:
            try:
                self.id_edit.setText(str(suggest_next_avatar_hand_id(acus_root)))
            except RuntimeError:
                lo, _hi = avatar_accessory_custom_id_band(HAND_CATEGORY)
                self.id_edit.setText(str(lo))

        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText("显示名")

        self._editor = PenguinHandPairEditorWidget(
            body_path=self._static / "Body.png",
            hand_path=self._static / "Hand.png",
            parent=self,
        )

        self._opacity_slider = QSlider(Qt.Orientation.Horizontal, self)
        self._opacity_slider.setRange(0, 100)
        self._opacity_slider.setValue(100)
        self._opacity_slider.setToolTip("Hand 层透明度（便于对齐）")

        self._zoom_l_slider = QSlider(Qt.Orientation.Horizontal, self)
        self._zoom_l_slider.setRange(5, 800)
        self._zoom_r_slider = QSlider(Qt.Orientation.Horizontal, self)
        self._zoom_r_slider.setRange(5, 800)

        hint = BodyLabel(
            "预览：Body + Hand + 左手图 + 右手图（饰物在用户图层，叠在手之上）。"
            "绿框为导出区 (130,141)+(290×791) 与 (597,141)+(290×791)。"
            "Tex 为左右两矩形拼成 580×791；Icon 在 5.png 上将左右条各缩至 64×175，"
            "分别放在 (51,60) 与 (140,60)。可只传一侧图片，另一侧留空。",
            self,
        )
        hint.setWordWrap(True)
        hint.setTextColor("#6B7280", "#9CA3AF")

        pick_l = PushButton("选择左手侧图片…", self)
        pick_l.clicked.connect(self._pick_left)
        pick_r = PushButton("选择右手侧图片…", self)
        pick_r.clicked.connect(self._pick_right)
        clear_r = PushButton("清除右手侧", self)
        clear_r.clicked.connect(self._editor.clear_right_pixmap)

        if is_edit:
            self._load_edit_state()

        op_row = QHBoxLayout()
        op_row.addWidget(BodyLabel("Hand 透明度", self))
        op_row.addWidget(self._opacity_slider, stretch=1)
        self._opacity_slider.valueChanged.connect(self._on_opacity)

        zl_row = QHBoxLayout()
        zl_row.addWidget(BodyLabel("左手缩放", self))
        zl_row.addWidget(self._zoom_l_slider, stretch=1)
        zr_row = QHBoxLayout()
        zr_row.addWidget(BodyLabel("右手缩放", self))
        zr_row.addWidget(self._zoom_r_slider, stretch=1)

        self._zoom_l_slider.valueChanged.connect(self._on_zoom_l_slider)
        self._zoom_r_slider.valueChanged.connect(self._on_zoom_r_slider)
        self._editor.changed.connect(self._sync_hand_zoom_sliders)

        card = CardWidget(self)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(8)
        form = QFormLayout()
        form.addRow("配件 ID", self.id_edit)
        form.addRow("显示名", wrap_name_input_with_preview(self.name_edit, parent=self))
        cl.addLayout(form)
        cl.addWidget(hint)
        pick_row = QHBoxLayout()
        pick_row.addWidget(pick_l)
        pick_row.addWidget(pick_r)
        pick_row.addWidget(clear_r)
        cl.addLayout(pick_row)
        cl.addLayout(op_row)
        cl.addLayout(zl_row)
        cl.addLayout(zr_row)
        cl.addWidget(self._editor, stretch=1)

        ok = PrimaryPushButton("生成并写入 ACUS", self)
        ok.clicked.connect(self._run)
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

        self._sync_hand_zoom_sliders()

    def _on_opacity(self, v: int) -> None:
        self._editor.set_hand_opacity(v / 100.0)

    def _slider_to_zoom(self, v: int) -> float:
        return max(0.05, min(8.0, v / 100.0))

    def _zoom_to_slider(self, z: float) -> int:
        v = int(round(z * 100))
        return max(5, min(800, v))

    def _on_zoom_l_slider(self, v: int) -> None:
        self._editor.set_zoom_left(self._slider_to_zoom(v))

    def _on_zoom_r_slider(self, v: int) -> None:
        self._editor.set_zoom_right(self._slider_to_zoom(v))

    def _sync_hand_zoom_sliders(self) -> None:
        self._zoom_l_slider.blockSignals(True)
        self._zoom_r_slider.blockSignals(True)
        self._zoom_l_slider.setValue(self._zoom_to_slider(self._editor.zoom_left))
        self._zoom_r_slider.setValue(self._zoom_to_slider(self._editor.zoom_right))
        self._zoom_l_slider.blockSignals(False)
        self._zoom_r_slider.blockSignals(False)

    def _load_edit_state(self) -> None:
        if self._edit_xml is None or not self._edit_xml.is_file():
            return
        try:
            tree = ET.parse(self._edit_xml)
            r = tree.getroot()
            nm = r.find("name")
            mid = _safe_int((nm.findtext("id") if nm is not None else "") or "")
            mstr = ((nm.findtext("str") if nm is not None else "") or "").strip()
            if mid is not None:
                self.id_edit.setText(str(mid))
            self.name_edit.setText(mstr)
            tx = r.find("texture")
            tex_rel = ((tx.findtext("path") if tx is not None else "") or "").strip()
            if not tex_rel:
                return
            tex_p = self._edit_xml.parent / tex_rel
            if not tex_p.is_file():
                return
            pm = dds_to_pixmap(
                acus_root=self._acus_root,
                compressonatorcli_path=self._tool,
                dds_path=tex_p,
                max_w=4096,
                max_h=4096,
                restrict=False,
            )
            if pm is None or pm.isNull():
                return
            w, h = pm.width(), pm.height()
            if w == HAND_TEX_W and h == HAND_TEX_H:
                im = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
                left = im.copy(0, 0, HAND_SLOT_W, HAND_SLOT_H)
                right = im.copy(HAND_SLOT_W, 0, HAND_SLOT_W, HAND_SLOT_H)
                self._editor.set_from_saved_merged_tex(left, right)
                self._sync_hand_zoom_sliders()
        except Exception:
            pass

    def _pick_left(self) -> None:
        p, _ = QFileDialog.getOpenFileName(
            self,
            "选择左手侧图片",
            "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*.*)",
        )
        if not p:
            return
        pm = QPixmap(str(Path(p)))
        if pm.isNull():
            fly_critical(self, "错误", "无法读取该图片")
            return
        self._editor.set_left_pixmap(pm)
        self._sync_hand_zoom_sliders()

    def _pick_right(self) -> None:
        p, _ = QFileDialog.getOpenFileName(
            self,
            "选择右手侧图片",
            "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*.*)",
        )
        if not p:
            return
        pm = QPixmap(str(Path(p)))
        if pm.isNull():
            fly_critical(self, "错误", "无法读取该图片")
            return
        self._editor.set_right_pixmap(pm)
        self._sync_hand_zoom_sliders()

    def _run(self) -> None:
        if self._tool is None and not quicktex_available():
            fly_critical(
                self,
                "无法生成 DDS",
                "请安装 quicktex（pip install quicktex）或在【设置】中配置 compressonatorcli。",
            )
            return
        aid = _safe_int(self.id_edit.text())
        if aid is None or aid < 1:
            fly_critical(self, "错误", "配件 ID 须为正整数")
            return
        if not self._is_edit:
            lo, hi = avatar_accessory_custom_id_band(HAND_CATEGORY)
            if not (lo <= aid <= hi):
                fly_critical(
                    self,
                    "错误",
                    f"手部自制 ID 须在 {lo}～{hi}（首位为 7、第二位为 category=5）。",
                )
                return
            taken = {it.name.id for it in scan_avatar_accessories(self._acus_root)}
            if aid in taken:
                fly_critical(self, "错误", f"ID {aid} 已被其它装扮占用，请更换或改用建议值。")
                return
        name = self.name_edit.text().strip() or f"hand{aid}"
        if not self._editor.has_user_pixmaps():
            fly_critical(self, "错误", "请至少选择左手侧或右手侧中的一张图片")
            return

        icon_bn = f"CHU_UI_Avatar_Icon_{aid:08d}.dds"
        tex_bn = f"CHU_UI_Avatar_Tex_{aid:08d}.dds"
        folder = self._acus_root / "avatarAccessory" / f"avatarAccessory{aid:08d}"
        folder.mkdir(parents=True, exist_ok=True)
        out_tex = folder / tex_bn
        out_icon = folder / icon_bn
        tpl_path = self._static / "Icon_template" / "5.png"
        if not tpl_path.is_file():
            fly_critical(self, "错误", f"缺少图标模板：{tpl_path}")
            return

        try:
            tex_final = self._editor.merged_hand_tex_image()
            if tex_final.width() != HAND_TEX_W or tex_final.height() != HAND_TEX_H:
                tex_final = tex_final.scaled(
                    HAND_TEX_W,
                    HAND_TEX_H,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )

            left_strip = tex_final.copy(0, 0, HAND_SLOT_W, HAND_TEX_H)
            right_strip = tex_final.copy(HAND_SLOT_W, 0, HAND_SLOT_W, HAND_TEX_H)
            il = left_strip.scaled(
                ICON_SIDE_W,
                ICON_SIDE_H,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            ir = right_strip.scaled(
                ICON_SIDE_W,
                ICON_SIDE_H,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

            tpl = QImage(str(tpl_path))
            if tpl.isNull():
                raise ValueError("无法读取手部 Icon 模板 PNG")
            out_w, out_h = tpl.width(), tpl.height()
            icon_img = QImage(out_w, out_h, QImage.Format.Format_ARGB32)
            icon_img.fill(Qt.GlobalColor.transparent)
            pw = QPainter(icon_img)
            pw.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            pw.drawImage(0, 0, tpl)
            pw.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            pw.drawImage(ICON_L_X, ICON_L_Y, il)
            pw.drawImage(ICON_R_X, ICON_R_Y, ir)
            pw.end()

            with tempfile.TemporaryDirectory() as td:
                tdir = Path(td)
                tex_png = tdir / "tex.png"
                icon_png = tdir / "icon.png"
                if not tex_final.save(str(tex_png), "PNG"):
                    raise RuntimeError("无法写出中间 tex PNG")
                if not icon_img.save(str(icon_png), "PNG"):
                    raise RuntimeError("无法写出中间 icon PNG")
                ok, err = run_bc3_jobs_with_progress(
                    parent=self,
                    tool_path=self._tool,
                    jobs=[(tex_png, out_tex), (icon_png, out_icon)],
                    title="正在生成手部饰物 DDS",
                )
                if not ok:
                    raise DdsToolError(err or "DDS 编码失败")

            write_avatar_accessory_xml(
                out_dir=folder,
                accessory_id=aid,
                name_str=name,
                icon_basename=icon_bn,
                tex_basename=tex_bn,
                category=HAND_CATEGORY,
                preserve_from=self._edit_xml,
            )
            self.accept()
        except DdsToolError as e:
            fly_critical(self, "DDS 失败", str(e))
        except Exception as e:
            fly_critical(self, "失败", str(e))
