from __future__ import annotations

from pathlib import Path
from datetime import datetime
import xml.etree.ElementTree as ET

from PyQt6.QtCore import QPoint, QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox as FluentComboBox,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    isDarkTheme,
)

from ..acus_workspace import acus_generated_dir
from ..chuni_formats import ChuniCharaId
from ..dds_convert import DdsToolError
from ..xml_writer import (
    CHARA_DEFAULT_NET_OPEN_ID,
    CHARA_DEFAULT_NET_OPEN_STR,
    CHARA_DEFAULT_RELEASE_TAG_ID,
    CHARA_DEFAULT_RELEASE_TAG_STR,
    ensure_chara_works_xml,
    write_chara_xml,
    write_ddsimage_xml,
)
from .dds_progress import run_bc3_jobs_with_progress
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical
from .name_glyph_preview import wrap_name_input_with_preview
from .works_dialogs import (
    WORKS_WARNING_TEXT,
    WorkCreateDialog,
    WorksLibraryManagerDialog,
    combo_works_id_str,
    fill_works_fluent_combo,
    load_works_library,
    user_accepts_vanilla_works_id_for_new_chara_works_folder,
)


def _skin_id_locked_field_style() -> str:
    """只读皮肤 ID 行：浅灰底，与 Fluent 明暗主题协调。"""
    if isDarkTheme():
        bg, bd, fg = "#374151", "#4B5563", "#E5E7EB"
    else:
        bg, bd, fg = "#E5E7EB", "#D1D5DB", "#4B5563"
    return (
        "QLineEdit#skinIdLockedField {"
        f"background-color: {bg};"
        f"color: {fg};"
        f"border: 1px solid {bd};"
        "border-radius: 5px;"
        "padding-left: 10px;"
        "}"
    )


def _muted_label_style() -> str:
    return f"color: {'#9CA3AF' if isDarkTheme() else '#6B7280'};"


def _set_idstr(node: ET.Element, val_id: int, val_str: str) -> None:
    id_el = node.find("id")
    if id_el is None:
        id_el = ET.SubElement(node, "id")
    id_el.text = str(val_id)
    str_el = node.find("str")
    if str_el is None:
        str_el = ET.SubElement(node, "str")
    str_el.text = val_str
    data_el = node.find("data")
    if data_el is None:
        ET.SubElement(node, "data")


def update_chara_variant_slot(*, acus_root: Path, base_id: int, variant: int, variant_name: str) -> Path:
    """
    变体只写回主角色（base*10）的 Chara.xml：
    - addImages{variant}.changeImg = true
    - addImages{variant}.charaName = 当前变体ID/名称
    - addImages{variant}.image = 当前变体ID/chara_key
    """
    if variant <= 0 or variant > 9:
        raise ValueError("仅支持更新 addImages1~9")
    base_raw = base_id * 10
    base_chara_dir = acus_root / "chara" / f"chara{base_raw:06d}"
    xml_path = base_chara_dir / "Chara.xml"
    if not xml_path.exists():
        raise ValueError(f"未找到主角色 Chara.xml：{xml_path}")

    root = ET.parse(xml_path).getroot()
    sec = root.find(f"addImages{variant}")
    if sec is None:
        sec = ET.SubElement(root, f"addImages{variant}")
    chg = sec.find("changeImg")
    if chg is None:
        chg = ET.SubElement(sec, "changeImg")
    chg.text = "true"

    cid = ChuniCharaId(base_raw + variant)
    cname = sec.find("charaName")
    if cname is None:
        cname = ET.SubElement(sec, "charaName")
    _set_idstr(cname, cid.raw, variant_name)

    image = sec.find("image")
    if image is None:
        image = ET.SubElement(sec, "image")
    _set_idstr(image, cid.raw, cid.chara_key)

    rank = sec.find("rank")
    if rank is None:
        rank = ET.SubElement(sec, "rank")
    if not (rank.text or "").strip().isdigit():
        rank.text = "15"

    ET.indent(root, space="  ")
    ET.ElementTree(root).write(xml_path, encoding="utf-8", xml_declaration=True)
    return xml_path


def chara_master_xml_path(acus_root: Path, any_chara_id: int) -> Path:
    """主角色 Chara.xml（base*10 目录），与变体 addImages 写入位置一致。"""
    base_raw = (any_chara_id // 10) * 10
    return acus_root / "chara" / f"chara{base_raw:06d}" / "Chara.xml"


def chara_variant_display_name(xml_path: Path, variant_slot: int) -> str:
    try:
        root = ET.parse(xml_path).getroot()
    except Exception:
        return ""
    if variant_slot == 0:
        return (root.findtext("name/str") or "").strip()
    sec = root.find(f"addImages{variant_slot}")
    if sec is None:
        return ""
    return (sec.findtext("charaName/str") or "").strip()


def remove_chara_variant_slot(*, xml_path: Path, variant: int) -> None:
    """从主 Chara.xml 移除 addImages{variant}（仅 1~9）。"""
    if not (1 <= variant <= 9):
        raise ValueError("仅可删除 addImages1~9")
    tree = ET.parse(xml_path)
    root = tree.getroot()
    sec = root.find(f"addImages{variant}")
    if sec is None:
        return
    root.remove(sec)
    ET.indent(root, space="  ")
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)


def _hint_style() -> str:
    c = "#9CA3AF" if isDarkTheme() else "#6B7280"
    return f"color:{c}; font-size:11px;"


class _CharaImageAdjustCell(QFrame):
    """单个方格：同一张图可在格内独立移动/缩放，顶部叠加模板定位图。"""

    changed = pyqtSignal()

    def __init__(self, *, template_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumSize(260, 260)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._src: QPixmap | None = None
        self._template = QPixmap(str(template_path))
        self._template_opacity = 0.65
        self._zoom = 1.0
        self._offset_ratio = QPointF(0.0, 0.0)  # 相对格子边长，便于不同导出分辨率复用
        self._dragging = False
        self._drag_last = QPoint()

    def set_source(self, src: QPixmap | None) -> None:
        self._src = src if src is not None and not src.isNull() else None
        self._offset_ratio = QPointF(0.0, 0.0)
        self._zoom = 1.0
        self.update()
        self.changed.emit()

    def _side(self) -> int:
        return max(1, min(self.width(), self.height()))

    def _fit_scale_for_side(self, side: int) -> float:
        if self._src is None or self._src.isNull():
            return 1.0
        side_f = float(max(1, side))
        return min(side_f / max(1.0, float(self._src.width())), side_f / max(1.0, float(self._src.height())))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_last = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            cur = event.position().toPoint()
            delta = cur - self._drag_last
            self._drag_last = cur
            side = float(self._side())
            self._offset_ratio.setX(self._offset_ratio.x() + float(delta.x()) / side)
            self._offset_ratio.setY(self._offset_ratio.y() + float(delta.y()) / side)
            self.update()
            self.changed.emit()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        step = event.angleDelta().y()
        if step == 0:
            return
        fac = 1.1 if step > 0 else (1.0 / 1.1)
        self._zoom = max(0.05, min(40.0, self._zoom * fac))
        self.update()
        self.changed.emit()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        side = self._side()
        x0 = (self.width() - side) // 2
        y0 = (self.height() - side) // 2
        rect = self.rect().adjusted(x0, y0, -(self.width() - side - x0), -(self.height() - side - y0))
        p.fillRect(rect, QColor("#111827" if isDarkTheme() else "#E5E7EB"))
        p.setPen(QPen(QColor("#374151" if isDarkTheme() else "#9CA3AF"), 1))
        p.drawRect(rect)
        self._draw_scene(p, side=side, origin=QPoint(x0, y0), draw_template=True)

    def _draw_scene(self, p: QPainter, *, side: int, origin: QPoint, draw_template: bool) -> None:
        clip_rect = (origin.x(), origin.y(), side, side)
        p.save()
        p.setClipRect(*clip_rect)
        if self._src is not None and not self._src.isNull():
            ox = self._offset_ratio.x() * float(side)
            oy = self._offset_ratio.y() * float(side)
            cx = float(origin.x()) + side / 2.0 + ox
            cy = float(origin.y()) + side / 2.0 + oy
            draw_scale = self._fit_scale_for_side(side) * self._zoom
            p.save()
            p.translate(cx, cy)
            p.scale(draw_scale, draw_scale)
            p.drawPixmap(-self._src.width() // 2, -self._src.height() // 2, self._src)
            p.restore()
        if draw_template and not self._template.isNull():
            tpl = self._template.scaled(
                side,
                side,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.setOpacity(self._template_opacity)
            p.drawPixmap(origin, tpl)
            p.setOpacity(1.0)
        p.restore()

    def set_template_opacity(self, opacity: float) -> None:
        self._template_opacity = max(0.0, min(1.0, float(opacity)))
        self.update()

    def save_render_png(self, out_png: Path, *, size: int) -> None:
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._draw_scene(p, side=size, origin=QPoint(0, 0), draw_template=False)
        p.end()
        out_png.parent.mkdir(parents=True, exist_ok=True)
        if not img.save(str(out_png), "PNG"):
            raise RuntimeError(f"无法写入 PNG：{out_png}")


class _CharaQuickComposeDialog(FluentCaptionDialog):
    def __init__(self, *, static_chara_dir: Path, out_dir: Path, parent=None) -> None:
        super().__init__(parent=parent)
        self.setModal(True)
        self.setWindowTitle("单图快速生成角色贴图")
        self.resize(1280, 680)
        self._out_dir = out_dir
        self.generated_paths: tuple[Path, Path, Path] | None = None  # full, half, head

        self._cell_full = _CharaImageAdjustCell(template_path=static_chara_dir / "Template00.png", parent=self)
        self._cell_half = _CharaImageAdjustCell(template_path=static_chara_dir / "Template01.png", parent=self)
        self._cell_head = _CharaImageAdjustCell(template_path=static_chara_dir / "Template02.png", parent=self)
        for cell in (self._cell_full, self._cell_half, self._cell_head):
            cell.setMinimumSize(240, 240)
            cell.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Expanding,
            )

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(2)
        grid.setVerticalSpacing(4)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 0)
        grid.addWidget(self._cell_full, 0, 0)
        grid.addWidget(self._cell_half, 0, 1)
        grid.addWidget(self._cell_head, 0, 2)
        grid.addWidget(BodyLabel("全身", self), 1, 0, alignment=Qt.AlignmentFlag.AlignHCenter)
        grid.addWidget(BodyLabel("半身", self), 1, 1, alignment=Qt.AlignmentFlag.AlignHCenter)
        grid.addWidget(BodyLabel("大头", self), 1, 2, alignment=Qt.AlignmentFlag.AlignHCenter)
        for i in range(3):
            grid.setColumnStretch(i, 1)

        hint = BodyLabel("上传一张 PNG 后可在三个格子分别拖拽移动、滚轮缩放；模板始终覆盖在最上层。", self)
        hint.setWordWrap(False)
        hint.setStyleSheet(_hint_style())
        hint.setMinimumHeight(22)
        hint.setMaximumHeight(24)
        hint.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self._opacity_slider = QSlider(Qt.Orientation.Horizontal, self)
        self._opacity_slider.setRange(0, 100)
        self._opacity_slider.setValue(65)
        self._opacity_slider.valueChanged.connect(self._on_template_opacity_changed)
        opacity_row = QHBoxLayout()
        opacity_row.setSpacing(8)
        opacity_row.addWidget(BodyLabel("覆盖图透明度", self))
        opacity_row.addWidget(self._opacity_slider, stretch=1)

        upload = PushButton("上传 PNG 到三个格子", self)
        upload.clicked.connect(self._pick_source_png)
        ok = PrimaryPushButton("生成并回填", self)
        ok.clicked.connect(self._on_generate)
        cancel = PushButton("取消", self)
        cancel.clicked.connect(self.reject)
        foot = QHBoxLayout()
        foot.setContentsMargins(0, 4, 0, 0)
        foot.addWidget(upload)
        foot.addStretch(1)
        foot.addWidget(cancel)
        foot.addWidget(ok)

        card = CardWidget(self)
        cly = QVBoxLayout(card)
        cly.setContentsMargins(8, 8, 8, 8)
        cly.setSpacing(4)
        cly.addWidget(hint)
        cly.addLayout(opacity_row)
        cly.addLayout(grid, stretch=1)
        cly.addLayout(foot)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*fluent_caption_content_margins())
        lay.setSpacing(0)
        lay.addWidget(card, stretch=1)

    def _on_template_opacity_changed(self, value: int) -> None:
        op = float(value) / 100.0
        self._cell_full.set_template_opacity(op)
        self._cell_half.set_template_opacity(op)
        self._cell_head.set_template_opacity(op)

    def _pick_source_png(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择立绘 PNG",
            "",
            "PNG 图片 (*.png);;图片文件 (*.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*.*)",
        )
        if not path:
            return
        pm = QPixmap(path)
        if pm.isNull():
            fly_critical(self, "错误", "图片加载失败，请换一张。")
            return
        self._cell_full.set_source(pm)
        self._cell_half.set_source(pm)
        self._cell_head.set_source(pm)

    def _on_generate(self) -> None:
        if self._cell_full._src is None:
            fly_critical(self, "错误", "请先上传一张 PNG。")
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        full = self._out_dir / f"quick_chara_full_{ts}.png"
        half = self._out_dir / f"quick_chara_half_{ts}.png"
        head = self._out_dir / f"quick_chara_head_{ts}.png"
        try:
            self._cell_full.save_render_png(full, size=1024)
            self._cell_half.save_render_png(half, size=512)
            self._cell_head.save_render_png(head, size=128)
        except Exception as e:
            fly_critical(self, "生成失败", str(e))
            return
        self.generated_paths = (full, half, head)
        self.accept()


class CharaAddDialog(FluentCaptionDialog):
    def __init__(
        self,
        *,
        acus_root: Path,
        tool_path: Path | None,
        parent=None,
        locked_variant: int | None = None,
        variant_lock_reason: str | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self.setModal(True)
        self.resize(540, 680)
        self._acus_root = acus_root
        self._tool = tool_path
        self._locked_variant: int | None = None
        if locked_variant is not None:
            lv = int(locked_variant)
            if lv < 0 or lv > 9:
                raise ValueError("locked_variant 须在 0-9 之间")
            self._locked_variant = lv

        self.base = LineEdit(self)
        self.base.setPlaceholderText("角色基ID（例如 2469）")
        self.variant = LineEdit(self)
        self.variant.setPlaceholderText("皮肤 ID 0~9（例如 0）")
        if self._locked_variant is not None:
            self.variant.setObjectName("skinIdLockedField")
            self.variant.setText(str(self._locked_variant))
            self.variant.setReadOnly(True)
            self.variant.setClearButtonEnabled(False)
            self.variant.setStyleSheet(_skin_id_locked_field_style())
            if variant_lock_reason == "new_chara":
                self.variant.setToolTip("新建主角色时皮肤 ID 固定为 0，不可修改。")
            elif variant_lock_reason == "chara_variant_add":
                self.variant.setToolTip(
                    "下一可用皮肤 ID 已按立绘槽位自动分配，不可修改。"
                )
            else:
                self.variant.setToolTip("正在编辑的皮肤 ID，不可修改。")
        self.cid_preview = LineEdit(self)
        self.cid_preview.setReadOnly(True)

        self.name = LineEdit(self)
        self.name.setPlaceholderText("角色显示名")
        self.illustrator = LineEdit(self)
        self.illustrator.setPlaceholderText("绘师 / illustratorName.str（可选，不填则 Invalid）")

        self.head = LineEdit(self)
        self.half = LineEdit(self)
        self.full = LineEdit(self)
        for e in (self.head, self.half, self.full):
            e.setPlaceholderText("选择图片或 DDS（DDS 需为 BC3）")

        self.base.textChanged.connect(self._update_preview)
        self.variant.textChanged.connect(self._update_preview)
        self._update_preview()

        id_card = CardWidget(self)
        id_lay = QVBoxLayout(id_card)
        id_lay.setContentsMargins(16, 16, 16, 16)
        id_lay.setSpacing(10)
        id_lay.addWidget(BodyLabel("ID 与名称", self))
        id_lay.addWidget(self._row("基 ID", self.base))
        id_lay.addWidget(
            self._row(
                "皮肤 ID",
                self.variant,
                label_muted=self._locked_variant is not None,
            )
        )
        id_lay.addWidget(self._row("最终 ID", self.cid_preview))
        id_lay.addWidget(self._row("角色名", wrap_name_input_with_preview(self.name, parent=self)))
        id_lay.addWidget(self._row("绘师（可选）", self.illustrator))

        self._works_combo = FluentComboBox(self)
        fill_works_fluent_combo(self._works_combo)
        works_row = QWidget(self)
        wh = QHBoxLayout(works_row)
        wh.setContentsMargins(0, 0, 0, 0)
        wh.setSpacing(8)
        wh.addWidget(self._works_combo, stretch=1)
        new_btn = PushButton("新建…", self)
        mgr_btn = PushButton("管理库…", self)

        def _new_works() -> None:
            _, nid = load_works_library()
            dlg = WorkCreateDialog(suggest_id=nid, acus_root=self._acus_root, parent=self)
            if dlg.exec() == QDialog.DialogCode.Accepted and dlg.created:
                i, s = dlg.created
                fill_works_fluent_combo(self._works_combo)
                for j in range(self._works_combo.count()):
                    d = self._works_combo.itemData(j)
                    if d is not None and len(d) == 2 and int(d[0]) == i:
                        self._works_combo.setCurrentIndex(j)
                        break

        def _mgr_works() -> None:
            WorksLibraryManagerDialog(acus_root=self._acus_root, parent=self).exec()
            cur = combo_works_id_str(self._works_combo)
            fill_works_fluent_combo(self._works_combo)
            for j in range(self._works_combo.count()):
                d = self._works_combo.itemData(j)
                if d is not None and len(d) == 2 and int(d[0]) == cur[0] and d[1] == cur[1]:
                    self._works_combo.setCurrentIndex(j)
                    return
            self._works_combo.setCurrentIndex(0)

        new_btn.clicked.connect(_new_works)
        mgr_btn.clicked.connect(_mgr_works)
        wh.addWidget(new_btn)
        wh.addWidget(mgr_btn)
        id_lay.addWidget(self._row("作品（works）", works_row))
        ww = BodyLabel(WORKS_WARNING_TEXT, self)
        ww.setWordWrap(True)
        ww.setStyleSheet("color:#B45309; font-size:12px;")
        id_lay.addWidget(ww)

        tex_card = CardWidget(self)
        tex_lay = QVBoxLayout(tex_card)
        tex_lay.setContentsMargins(16, 16, 16, 16)
        tex_lay.setSpacing(10)
        tex_lay.addWidget(BodyLabel("贴图（CHU_UI_Character：全身 _00 / 半身 _01 / 大头 _02）", self))
        quick_row = QHBoxLayout()
        quick_btn = PushButton("单图快速生成三张贴图…", self)
        quick_btn.clicked.connect(self._open_quick_compose_dialog)
        quick_row.addWidget(quick_btn)
        quick_row.addStretch(1)
        tex_lay.addLayout(quick_row)
        tex_lay.addWidget(
            self._file_row(
                self.full,
                "选择全身图",
                dim_hint="参考分辨率：1024 × 1024 像素；也可直传 BC3 DDS。",
            )
        )
        tex_lay.addWidget(
            self._file_row(
                self.half,
                "选择半身图",
                dim_hint="参考分辨率：512 × 512 像素；也可直传 BC3 DDS。",
            )
        )
        tex_lay.addWidget(
            self._file_row(
                self.head,
                "选择大头图",
                dim_hint="参考分辨率：128 × 128 像素；也可直传 BC3 DDS。",
            )
        )

        warn = BodyLabel(
            "提示：角色名请尽量使用日语字库内可显示字符；超出字库的汉字在游戏内可能显示为方块。",
            self,
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("color:#B45309;")

        ok = PrimaryPushButton("生成并写入 ACUS", self)
        ok.clicked.connect(self._run)
        cancel = PushButton("取消", self)
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(*fluent_caption_content_margins())
        layout.addWidget(id_card)
        layout.addWidget(tex_card)
        layout.addWidget(warn)
        layout.addLayout(btns)

        self.setWindowTitle("编辑角色" if self.base.isReadOnly() else "新增角色")

    def _row(
        self,
        label: str,
        field: QWidget,
        *,
        label_muted: bool = False,
    ) -> QWidget:
        w = QWidget(self)
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)
        lb = BodyLabel(label, self)
        lb.setMinimumWidth(108)
        if label_muted:
            lb.setStyleSheet(_muted_label_style())
        h.addWidget(lb, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        h.addWidget(field, 1)
        return w

    def _file_row(self, edit: LineEdit, title: str, *, dim_hint: str | None = None) -> QWidget:
        w = QWidget(self)
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        row = QWidget(self)
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        h.addWidget(edit, stretch=1)
        b = PushButton("浏览…", self)
        b.clicked.connect(lambda: self._pick_into(edit, title))
        h.addWidget(b)
        v.addWidget(row)
        if dim_hint:
            hint = BodyLabel(dim_hint, self)
            hint.setWordWrap(True)
            hint.setStyleSheet(_hint_style())
            v.addWidget(hint)
        return w

    def _pick_into(self, edit: LineEdit, title: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, title)
        if path:
            edit.setText(path)

    def _open_quick_compose_dialog(self) -> None:
        static_dir = Path(__file__).resolve().parent.parent / "static" / "tool" / "chara"
        out_dir = acus_generated_dir(self._acus_root, "chara_quick_png")
        dlg = _CharaQuickComposeDialog(static_chara_dir=static_dir, out_dir=out_dir, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.generated_paths is None:
            return
        full, half, head = dlg.generated_paths
        self.full.setText(str(full))
        self.half.setText(str(half))
        self.head.setText(str(head))

    def _update_preview(self) -> None:
        try:
            base = int(self.base.text().strip())
            if self._locked_variant is not None:
                var = self._locked_variant
            else:
                var = int(self.variant.text().strip())
            if var < 0 or var > 9:
                raise ValueError()
            self.cid_preview.setText(str(base * 10 + var))
        except Exception:
            self.cid_preview.setText("")

    def _run(self) -> None:
        base_txt = self.base.text().strip()
        if not base_txt:
            fly_critical(self, "错误", "请填写基 ID")
            return
        try:
            base = int(base_txt)
        except ValueError:
            fly_critical(self, "错误", "基 ID 必须是整数")
            return
        if self._locked_variant is not None:
            var = self._locked_variant
        else:
            var_txt = self.variant.text().strip()
            if not var_txt:
                fly_critical(self, "错误", "请填写皮肤 ID（0~9）")
                return
            try:
                var = int(var_txt)
            except ValueError:
                fly_critical(self, "错误", "皮肤 ID 必须是整数（0~9）")
                return
            if var < 0 or var > 9:
                fly_critical(self, "错误", "皮肤 ID 必须在 0~9 之间")
                return

        try:
            cid_raw = base * 10 + var

            head = Path(self.head.text().strip()).expanduser()
            half = Path(self.half.text().strip()).expanduser()
            full = Path(self.full.text().strip()).expanduser()
            for p, label in ((head, "大头"), (half, "半身"), (full, "全身")):
                if not p.exists():
                    raise ValueError(f"{label} 图片路径不存在")

            cid = ChuniCharaId(cid_raw)
            w_id, w_str = combo_works_id_str(self._works_combo)
            if var == 0:
                if not user_accepts_vanilla_works_id_for_new_chara_works_folder(
                    self, acus_root=self._acus_root, works_id=w_id, works_str=w_str
                ):
                    return

            dds_dir = self._acus_root / "ddsImage" / f"ddsImage{cid.raw6}"

            jobs = [
                (full, dds_dir / cid.dds_filename(0)),
                (half, dds_dir / cid.dds_filename(1)),
                (head, dds_dir / cid.dds_filename(2)),
            ]
            ok, dds_err = run_bc3_jobs_with_progress(
                parent=self,
                tool_path=self._tool,
                jobs=jobs,
                title="正在生成角色 DDS",
            )
            if not ok:
                raise DdsToolError(dds_err or "DDS 编码失败")

            write_ddsimage_xml(out_dir=self._acus_root, chara_id=cid.raw)
            ill = self.illustrator.text().strip() or None
            chara_name = self.name.text().strip()
            if var == 0:
                write_chara_xml(
                    out_dir=self._acus_root,
                    chara_id=cid.raw,
                    chara_name=chara_name,
                    illustrator_name=ill,
                    release_tag_id=CHARA_DEFAULT_RELEASE_TAG_ID,
                    release_tag_str=CHARA_DEFAULT_RELEASE_TAG_STR,
                    works_id=w_id,
                    works_str=w_str,
                )
                ensure_chara_works_xml(
                    out_dir=self._acus_root,
                    works_id=w_id,
                    works_str=w_str,
                    release_tag_id=CHARA_DEFAULT_RELEASE_TAG_ID,
                    release_tag_str=CHARA_DEFAULT_RELEASE_TAG_STR,
                    net_open_id=CHARA_DEFAULT_NET_OPEN_ID,
                    net_open_str=CHARA_DEFAULT_NET_OPEN_STR,
                )
            else:
                update_chara_variant_slot(
                    acus_root=self._acus_root,
                    base_id=base,
                    variant=var,
                    variant_name=chara_name or cid.chara_key,
                )

            self.accept()
        except DdsToolError as e:
            fly_critical(self, "DDS 转换失败", str(e))
        except Exception as e:
            fly_critical(self, "错误", str(e))
