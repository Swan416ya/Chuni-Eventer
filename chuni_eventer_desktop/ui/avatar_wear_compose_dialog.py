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
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import BodyLabel, CardWidget, LineEdit, PrimaryPushButton, PushButton

from ..acus_scan import scan_avatar_accessories
from ..dds_convert import DdsToolError
from ..dds_preview import dds_to_pixmap
from ..dds_quicktex import quicktex_available
from .dds_progress import run_bc3_jobs_with_progress
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical
from .name_glyph_preview import wrap_name_input_with_preview

CANVAS = 1024
CROP_X = 78
CROP_Y = 260
CROP_W = 862
CROP_H = 728
TEX_W = 516
TEX_H = 426
# Icon 模板像素坐标：先将 Tex（516×426）缩放到此矩形，再左上角对齐叠加。
ICON_TEX_X = 20
ICON_TEX_Y = 66
ICON_TEX_ON_ICON_W = 215
ICON_TEX_ON_ICON_H = 182

NET_OPEN_ID = 2800
NET_OPEN_STR = "v2_45 00_0"

# 自制企鹅装扮 ID：>70000000；首位 7、第二位为 XML category（1～9），其后 6 位递增。
# 例：衣服 category=1 → 71000000～71999999；目录名为 ``avatarAccessory`` + ``{id:08d}``（与官方一致）。
_AVATAR_CUSTOM_ROOT = 70_000_000


def _package_static_avatar_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "static" / "tool" / "Avatar"


def avatar_accessory_custom_id_band(category: int) -> tuple[int, int]:
    """返回某 category 下自制装饰的合法 ID 闭区间 [lo, hi]（8 位数内第二位为 category）。"""
    c = max(1, min(9, int(category)))
    lo = _AVATAR_CUSTOM_ROOT + c * 1_000_000
    hi = lo + 999_999
    return lo, hi


def suggest_next_avatar_accessory_id(acus_root: Path, category: int) -> int:
    """在对应 category 的自制段内取最小未占用 ID。"""
    lo, hi = avatar_accessory_custom_id_band(category)
    used = {
        it.name.id
        for it in scan_avatar_accessories(acus_root)
        if lo <= it.name.id <= hi
    }
    n = lo
    while n <= hi and n in used:
        n += 1
    if n > hi:
        raise RuntimeError(f"自制装扮 ID 段 [{lo}, {hi}] 已无可用编号（category={category}）")
    return n


def suggest_next_avatar_wear_id(acus_root: Path) -> int:
    """企鹅衣服（category=1）下一个建议 ID：71000000 起。"""
    return suggest_next_avatar_accessory_id(acus_root, 1)


def _set_idstr(parent: ET.Element, val_id: int, val_str: str) -> None:
    id_el = parent.find("id")
    if id_el is None:
        id_el = ET.SubElement(parent, "id")
    id_el.text = str(val_id)
    str_el = parent.find("str")
    if str_el is None:
        str_el = ET.SubElement(parent, "str")
    str_el.text = val_str
    data_el = parent.find("data")
    if data_el is None:
        data_el = ET.SubElement(parent, "data")
    if data_el.text is None:
        data_el.text = ""


def write_avatar_accessory_wear_xml(
    *,
    out_dir: Path,
    accessory_id: int,
    name_str: str,
    icon_basename: str,
    tex_basename: str,
    preserve_from: Path | None,
) -> Path:
    """写入 category=1 企鹅衣服 AvatarAccessory.xml。"""
    sort_key = (name_str[:1] if name_str.strip() else "?").strip() or "?"
    net_id, net_str = NET_OPEN_ID, NET_OPEN_STR
    disable_flag = "false"
    if preserve_from is not None and preserve_from.is_file():
        try:
            old = ET.parse(preserve_from).getroot()
            no = old.find("netOpenName")
            if no is not None:
                try:
                    net_id = int((no.findtext("id") or str(NET_OPEN_ID)).strip())
                except ValueError:
                    net_id = NET_OPEN_ID
                net_str = (no.findtext("str") or NET_OPEN_STR).strip() or NET_OPEN_STR
            df = (old.findtext("disableFlag") or "").strip().lower()
            if df in ("true", "false"):
                disable_flag = df
        except Exception:
            pass

    folder_name = f"avatarAccessory{accessory_id:08d}"
    data_name = folder_name
    root = ET.Element("AvatarAccessoryData")
    ET.SubElement(root, "dataName").text = data_name
    non = ET.SubElement(root, "netOpenName")
    _set_idstr(non, net_id, net_str)
    ET.SubElement(root, "disableFlag").text = disable_flag
    nm = ET.SubElement(root, "name")
    _set_idstr(nm, accessory_id, name_str)
    ET.SubElement(root, "sortName").text = sort_key
    ET.SubElement(root, "category").text = "1"
    img = ET.SubElement(root, "image")
    ET.SubElement(img, "path").text = icon_basename
    tx = ET.SubElement(root, "texture")
    ET.SubElement(tx, "path").text = tex_basename
    ET.SubElement(root, "defaultHave").text = "false"
    ET.SubElement(root, "explainText").text = "-"
    ET.SubElement(root, "priority").text = "0"
    ET.indent(root, space="  ")
    xml_path = out_dir / "AvatarAccessory.xml"
    ET.ElementTree(root).write(xml_path, encoding="utf-8", xml_declaration=True)
    return xml_path


def _safe_int(text: str) -> int | None:
    try:
        return int(text.strip())
    except Exception:
        return None


class PenguinWearEditorWidget(QWidget):
    """1024 逻辑画布：预览为 Body + 衣服 + Hand；导出 Tex 仅取用户衣服图层（透明底）。"""

    changed = pyqtSignal()

    def __init__(self, *, body_path: Path, hand_path: Path, parent: QWidget | None = None) -> None:
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
        self._cloth: QPixmap | None = None
        self._ox = 0.0
        self._oy = 0.0
        self._zoom = 1.0
        self._hand_opacity = 1.0
        self._dragging = False
        self._drag_last = QPoint()

    def set_cloth_pixmap(self, pm: QPixmap | None) -> None:
        self._cloth = pm if pm is not None and not pm.isNull() else None
        self._ox = self._oy = 0.0
        self._zoom = 1.0
        if self._cloth is not None:
            # 初始缩放使衣服大致落在躯干区域
            tw = max(1, self._cloth.width())
            th = max(1, self._cloth.height())
            self._zoom = float(min(900.0 / tw, 900.0 / th, 2.5))
        self.update()
        self.changed.emit()

    def set_hand_opacity(self, alpha: float) -> None:
        self._hand_opacity = max(0.0, min(1.0, float(alpha)))
        self.update()

    def _view_scale(self) -> tuple[float, float, float]:
        w, h = float(max(1, self.width())), float(max(1, self.height()))
        sc = min(w, h) / float(CANVAS)
        ox = (w - CANVAS * sc) / 2.0
        oy = (h - CANVAS * sc) / 2.0
        return sc, ox, oy

    def _widget_to_logical(self, pos: QPointF) -> QPointF:
        sc, ox, oy = self._view_scale()
        return QPointF((pos.x() - ox) / sc, (pos.y() - oy) / sc)

    def paintEvent(self, event) -> None:
        del event
        p = QPainter(self)
        p.fillRect(self.rect(), self.palette().color(QPalette.ColorRole.Window))
        sc, ox, oy = self._view_scale()
        p.translate(ox, oy)
        p.scale(sc, sc)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawPixmap(0, 0, self._body)
        if self._cloth is not None:
            p.save()
            p.translate(CANVAS / 2.0 + self._ox, CANVAS / 2.0 + self._oy)
            p.scale(self._zoom, self._zoom)
            p.drawPixmap(-self._cloth.width() // 2, -self._cloth.height() // 2, self._cloth)
            p.restore()
        p.setOpacity(self._hand_opacity)
        p.drawPixmap(0, 0, self._hand)
        p.setOpacity(1.0)
        p.setPen(QPen(QColor(56, 189, 248, 180), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(CROP_X, CROP_Y, CROP_W, CROP_H)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_last = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging and self._cloth is not None:
            cur = event.position().toPoint()
            delta = cur - self._drag_last
            self._drag_last = cur
            sc, _, _ = self._view_scale()
            self._ox += float(delta.x()) / sc
            self._oy += float(delta.y()) / sc
            self.update()
            self.changed.emit()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        if self._cloth is None:
            return
        d = event.angleDelta().y()
        if d == 0:
            return
        fac = 1.08 if d > 0 else 1.0 / 1.08
        self._zoom = max(0.05, min(12.0, self._zoom * fac))
        self.update()
        self.changed.emit()

    def render_cloth_layer_1024(self) -> QImage:
        """导出 Tex 用：全透明 1024 画布 + 仅用户衣服图层（与预览中衣服平移/缩放一致，不含 Body/手）。"""
        img = QImage(CANVAS, CANVAS, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        if self._cloth is None:
            return img
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.translate(CANVAS / 2.0 + self._ox, CANVAS / 2.0 + self._oy)
        p.scale(self._zoom, self._zoom)
        p.drawPixmap(-self._cloth.width() // 2, -self._cloth.height() // 2, self._cloth)
        p.end()
        return img


class AvatarWearComposeDialog(FluentCaptionDialog):
    """新增/编辑企鹅衣服（category=1）：合成 Tex + Icon DDS 与 AvatarAccessory.xml。"""

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
        self.setWindowTitle("编辑企鹅衣服" if is_edit else "新增企鹅衣服")
        self.setModal(True)
        self.resize(920, 860)

        self.id_edit = LineEdit(self)
        self.id_edit.setPlaceholderText("例如 71000001（自制衣服：71000000～71999999）")
        if is_edit:
            self.id_edit.setReadOnly(True)
        else:
            try:
                self.id_edit.setText(str(suggest_next_avatar_wear_id(acus_root)))
            except RuntimeError:
                lo, _hi = avatar_accessory_custom_id_band(1)
                self.id_edit.setText(str(lo))

        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText("显示名")

        self._editor = PenguinWearEditorWidget(
            body_path=self._static / "Body.png",
            hand_path=self._static / "Hand.png",
            parent=self,
        )

        self._opacity_slider = QSlider(Qt.Orientation.Horizontal, self)
        self._opacity_slider.setRange(0, 100)
        self._opacity_slider.setValue(100)
        self._opacity_slider.setToolTip("Hand 层透明度（便于对齐袖口）")

        hint = BodyLabel(
            "预览：Body + 你的衣服 + Hand（绿框为导出裁剪区）。"
            "导出 Tex 仅为裁剪后的「衣服图层」（透明底，不含身子与手）；"
            "Icon 与模板同尺寸：先铺模板，再将 516×426 Tex 缩放到 215×182，左上角对齐 (20,66) 叠加。",
            self,
        )
        hint.setWordWrap(True)
        hint.setTextColor("#6B7280", "#9CA3AF")

        pick = PushButton("选择衣服图片…", self)
        pick.clicked.connect(self._pick_cloth)

        if is_edit:
            self._load_edit_state()

        op_row = QHBoxLayout()
        op_row.addWidget(BodyLabel("Hand 透明度", self))
        op_row.addWidget(self._opacity_slider, stretch=1)
        self._opacity_slider.valueChanged.connect(self._on_opacity)

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

    def _on_opacity(self, v: int) -> None:
        self._editor.set_hand_opacity(v / 100.0)

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

    def _pick_cloth(self) -> None:
        p, _ = QFileDialog.getOpenFileName(
            self,
            "选择衣服图片",
            "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*.*)",
        )
        if not p:
            return
        src = Path(p)
        pm = QPixmap(str(src))
        if pm.isNull():
            fly_critical(self, "错误", "无法读取该图片")
            return
        self._editor.set_cloth_pixmap(pm)

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
            lo, hi = avatar_accessory_custom_id_band(1)
            if not (lo <= aid <= hi):
                fly_critical(
                    self,
                    "错误",
                    f"企鹅衣服自制 ID 须在 {lo}～{hi}（首位为 7、第二位为 category=1）。",
                )
                return
            taken = {it.name.id for it in scan_avatar_accessories(self._acus_root)}
            if aid in taken:
                fly_critical(self, "错误", f"ID {aid} 已被其它装扮占用，请更换或改用建议值。")
                return
        name = self.name_edit.text().strip() or f"wear{aid}"
        if self._editor._cloth is None:
            fly_critical(self, "错误", "请先选择衣服图片")
            return

        icon_bn = f"CHU_UI_Avatar_Icon_{aid:08d}.dds"
        tex_bn = f"CHU_UI_Avatar_Tex_{aid:08d}.dds"
        folder = self._acus_root / "avatarAccessory" / f"avatarAccessory{aid:08d}"
        folder.mkdir(parents=True, exist_ok=True)
        out_tex = folder / tex_bn
        out_icon = folder / icon_bn
        tpl_path = self._static / "Icon_template" / "1.png"
        if not tpl_path.is_file():
            fly_critical(self, "错误", f"缺少图标模板：{tpl_path}")
            return

        try:
            full = self._editor.render_cloth_layer_1024()
            cropped = full.copy(CROP_X, CROP_Y, CROP_W, CROP_H)
            tex_final = cropped.scaled(
                TEX_W,
                TEX_H,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ).convertToFormat(QImage.Format.Format_ARGB32)
            if tex_final.width() != TEX_W or tex_final.height() != TEX_H:
                tex_final = tex_final.scaled(
                    TEX_W,
                    TEX_H,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )

            tpl = QImage(str(tpl_path))
            if tpl.isNull():
                raise ValueError("无法读取 Icon 模板 PNG")
            out_w, out_h = tpl.width(), tpl.height()
            tex_on_icon = tex_final.scaled(
                ICON_TEX_ON_ICON_W,
                ICON_TEX_ON_ICON_H,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

            icon_img = QImage(out_w, out_h, QImage.Format.Format_ARGB32)
            icon_img.fill(Qt.GlobalColor.transparent)
            pw = QPainter(icon_img)
            pw.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            pw.drawImage(0, 0, tpl)
            pw.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            pw.drawImage(ICON_TEX_X, ICON_TEX_Y, tex_on_icon)
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
                    title="正在生成企鹅衣服 DDS",
                )
                if not ok:
                    raise DdsToolError(err or "DDS 编码失败")

            write_avatar_accessory_wear_xml(
                out_dir=folder,
                accessory_id=aid,
                name_str=name,
                icon_basename=icon_bn,
                tex_basename=tex_bn,
                preserve_from=self._edit_xml,
            )
            self.accept()
        except DdsToolError as e:
            fly_critical(self, "DDS 失败", str(e))
        except Exception as e:
            fly_critical(self, "失败", str(e))
