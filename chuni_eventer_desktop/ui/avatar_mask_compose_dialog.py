"""企鹅面具（AvatarAccessory category=3）：1024 对齐编辑、Tex/Icon DDS 与 XML。"""

from __future__ import annotations

import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPainter, QPixmap
from PyQt6.QtWidgets import QFileDialog, QFormLayout, QHBoxLayout, QSlider, QVBoxLayout

from qfluentwidgets import BodyLabel, CardWidget, LineEdit, PrimaryPushButton, PushButton

from ..acus_scan import scan_avatar_accessories
from ..dds_convert import DdsToolError
from ..dds_preview import dds_to_pixmap
from ..dds_quicktex import quicktex_available
from .avatar_wear_compose_dialog import (
    PenguinWearEditorWidget,
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

# 裁剪 (337,227)+(341×306)；Tex 232×208；Icon 模板 3.png 上叠 183×164，左上角 (39,57)
MASK_CROP_X = 337
MASK_CROP_Y = 227
MASK_CROP_W = 341
MASK_CROP_H = 306
MASK_TEX_W = 232
MASK_TEX_H = 208
ICON_MASK_X = 39
ICON_MASK_Y = 57
ICON_MASK_W = 183
ICON_MASK_H = 164
MASK_CATEGORY = 3

_MASK_CROP = (MASK_CROP_X, MASK_CROP_Y, MASK_CROP_W, MASK_CROP_H)


def suggest_next_avatar_mask_id(acus_root: Path) -> int:
    """自制面具（category=3）下一个建议 ID：73000000 起。"""
    return suggest_next_avatar_accessory_id(acus_root, MASK_CATEGORY)


class AvatarMaskComposeDialog(FluentCaptionDialog):
    """新增/编辑企鹅面具（category=3）。"""

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
        self.setWindowTitle("编辑面具" if is_edit else "新增面具")
        self.setModal(True)
        self.resize(920, 860)

        self.id_edit = LineEdit(self)
        self.id_edit.setPlaceholderText("例如 73000001（自制面具：73000000～73999999）")
        if is_edit:
            self.id_edit.setReadOnly(True)
        else:
            try:
                self.id_edit.setText(str(suggest_next_avatar_mask_id(acus_root)))
            except RuntimeError:
                lo, _hi = avatar_accessory_custom_id_band(MASK_CATEGORY)
                self.id_edit.setText(str(lo))

        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText("显示名")

        self._editor = PenguinWearEditorWidget(
            body_path=self._static / "Body.png",
            hand_path=self._static / "Hand.png",
            crop=_MASK_CROP,
            parent=self,
        )

        self._opacity_slider = QSlider(Qt.Orientation.Horizontal, self)
        self._opacity_slider.setRange(0, 100)
        self._opacity_slider.setValue(100)
        self._opacity_slider.setToolTip("Hand 层透明度（便于对齐）")

        hint = BodyLabel(
            "预览：Body + 你的面具图 + Hand（绿框为导出裁剪区 (337,227)+(341×306)）。"
            "导出 Tex 为裁剪后面具图层缩放到 232×208（透明底）；"
            "Icon 在模板 3.png 上将 Tex 缩至 183×164，左上角对齐 (39,57)。",
            self,
        )
        hint.setWordWrap(True)
        hint.setTextColor("#6B7280", "#9CA3AF")

        pick = PushButton("选择面具图片…", self)
        pick.clicked.connect(self._pick_mask)

        if is_edit:
            self._load_edit_state()

        op_row = QHBoxLayout()
        op_row.addWidget(BodyLabel("Hand 透明度", self))
        op_row.addWidget(self._opacity_slider, stretch=1)
        self._opacity_slider.valueChanged.connect(self._on_opacity)

        self._cloth_zoom_slider = QSlider(Qt.Orientation.Horizontal, self)
        self._cloth_zoom_slider.setRange(5, 1200)
        self._cloth_zoom_slider.setEnabled(False)
        self._cloth_zoom_slider.setToolTip("上传图缩放（也可用鼠标滚轮）")
        self._cloth_zoom_slider.valueChanged.connect(self._on_cloth_zoom_slider)
        self._editor.changed.connect(self._sync_cloth_zoom_slider)

        card = CardWidget(self)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(8)
        form = QFormLayout()
        form.addRow("配件 ID", self.id_edit)
        form.addRow("显示名", wrap_name_input_with_preview(self.name_edit, parent=self))
        cl.addLayout(form)
        cl.addWidget(hint)
        cl.addWidget(pick)
        cl.addLayout(op_row)
        zoom_row = QHBoxLayout()
        zoom_row.addWidget(BodyLabel("图片缩放", self))
        zoom_row.addWidget(self._cloth_zoom_slider, stretch=1)
        cl.addLayout(zoom_row)
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

        self._sync_cloth_zoom_slider()

    def _on_opacity(self, v: int) -> None:
        self._editor.set_hand_opacity(v / 100.0)

    def _on_cloth_zoom_slider(self, v: int) -> None:
        self._editor.set_cloth_zoom(max(0.05, min(12.0, v / 100.0)))

    def _sync_cloth_zoom_slider(self) -> None:
        if not self._editor.has_cloth:
            self._cloth_zoom_slider.setEnabled(False)
            return
        self._cloth_zoom_slider.setEnabled(True)
        v = int(round(self._editor.cloth_zoom * 100))
        v = max(self._cloth_zoom_slider.minimum(), min(self._cloth_zoom_slider.maximum(), v))
        self._cloth_zoom_slider.blockSignals(True)
        self._cloth_zoom_slider.setValue(v)
        self._cloth_zoom_slider.blockSignals(False)

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
            if tex_rel:
                tex_p = self._edit_xml.parent / tex_rel
                if tex_p.is_file():
                    pm = dds_to_pixmap(
                        acus_root=self._acus_root,
                        compressonatorcli_path=self._tool,
                        dds_path=tex_p,
                        max_w=2048,
                        max_h=2048,
                        restrict=False,
                    )
                    if pm is not None and not pm.isNull():
                        self._editor.set_cloth_pixmap(pm)
        except Exception:
            pass

    def _pick_mask(self) -> None:
        p, _ = QFileDialog.getOpenFileName(
            self,
            "选择面具图片",
            "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*.*)",
        )
        if not p:
            return
        pm = QPixmap(str(Path(p)))
        if pm.isNull():
            fly_critical(self, "错误", "无法读取该图片")
            return
        self._editor.set_cloth_pixmap(pm)
        self._sync_cloth_zoom_slider()

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
            lo, hi = avatar_accessory_custom_id_band(MASK_CATEGORY)
            if not (lo <= aid <= hi):
                fly_critical(
                    self,
                    "错误",
                    f"面具自制 ID 须在 {lo}～{hi}（首位为 7、第二位为 category=3）。",
                )
                return
            taken = {it.name.id for it in scan_avatar_accessories(self._acus_root)}
            if aid in taken:
                fly_critical(self, "错误", f"ID {aid} 已被其它装扮占用，请更换或改用建议值。")
                return
        name = self.name_edit.text().strip() or f"mask{aid}"
        if not self._editor.has_cloth:
            fly_critical(self, "错误", "请先选择面具图片")
            return

        icon_bn = f"CHU_UI_Avatar_Icon_{aid:08d}.dds"
        tex_bn = f"CHU_UI_Avatar_Tex_{aid:08d}.dds"
        folder = self._acus_root / "avatarAccessory" / f"avatarAccessory{aid:08d}"
        folder.mkdir(parents=True, exist_ok=True)
        out_tex = folder / tex_bn
        out_icon = folder / icon_bn
        tpl_path = self._static / "Icon_template" / "3.png"
        if not tpl_path.is_file():
            fly_critical(self, "错误", f"缺少图标模板：{tpl_path}")
            return

        try:
            full = self._editor.render_cloth_layer_1024()
            cx, cy, cw, ch = self._editor.crop_rect
            cropped = full.copy(cx, cy, cw, ch)
            tex_final = cropped.scaled(
                MASK_TEX_W,
                MASK_TEX_H,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ).convertToFormat(QImage.Format.Format_ARGB32)
            if tex_final.width() != MASK_TEX_W or tex_final.height() != MASK_TEX_H:
                tex_final = tex_final.scaled(
                    MASK_TEX_W,
                    MASK_TEX_H,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )

            tpl = QImage(str(tpl_path))
            if tpl.isNull():
                raise ValueError("无法读取面具 Icon 模板 PNG")
            out_w, out_h = tpl.width(), tpl.height()
            tex_on_icon = tex_final.scaled(
                ICON_MASK_W,
                ICON_MASK_H,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

            icon_img = QImage(out_w, out_h, QImage.Format.Format_ARGB32)
            icon_img.fill(Qt.GlobalColor.transparent)
            pw = QPainter(icon_img)
            pw.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            pw.drawImage(0, 0, tpl)
            pw.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            pw.drawImage(ICON_MASK_X, ICON_MASK_Y, tex_on_icon)
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
                    title="正在生成面具 DDS",
                )
                if not ok:
                    raise DdsToolError(err or "DDS 编码失败")

            write_avatar_accessory_xml(
                out_dir=folder,
                accessory_id=aid,
                name_str=name,
                icon_basename=icon_bn,
                tex_basename=tex_bn,
                category=MASK_CATEGORY,
                preserve_from=self._edit_xml,
            )
            self.accept()
        except DdsToolError as e:
            fly_critical(self, "DDS 失败", str(e))
        except Exception as e:
            fly_critical(self, "失败", str(e))
