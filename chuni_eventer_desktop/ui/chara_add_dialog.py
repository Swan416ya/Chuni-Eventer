from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox as FluentComboBox,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    isDarkTheme,
)

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
from .fluent_dialogs import fly_critical, fly_message
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


class CharaAddDialog(FluentCaptionDialog):
    def __init__(self, *, acus_root: Path, tool_path: Path | None, parent=None) -> None:
        super().__init__(parent=parent)
        self.setModal(True)
        self.resize(540, 680)
        self._acus_root = acus_root
        self._tool = tool_path

        self.base = LineEdit(self)
        self.base.setPlaceholderText("角色基ID（例如 2469）")
        self.variant = LineEdit(self)
        self.variant.setPlaceholderText("变体 0-9（例如 0）")
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
        id_lay.addWidget(self._row("变体", self.variant))
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

    def _row(self, label: str, field: QWidget) -> QWidget:
        w = QWidget(self)
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)
        lb = BodyLabel(label, self)
        lb.setMinimumWidth(108)
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

    def _update_preview(self) -> None:
        try:
            base = int(self.base.text().strip())
            var = int(self.variant.text().strip())
            if var < 0 or var > 9:
                raise ValueError()
            self.cid_preview.setText(str(base * 10 + var))
        except Exception:
            self.cid_preview.setText("")

    def _run(self) -> None:
        try:
            base = int(self.base.text().strip())
            var = int(self.variant.text().strip())
            if var < 0 or var > 9:
                raise ValueError("变体必须在 0-9 之间")
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

            msg = f"已写入 ACUS：ddsImage {cid.raw}"
            if var == 0:
                msg += f"\n并生成主角色 chara{cid.raw6}/Chara.xml"
            else:
                msg += f"\n并更新主角色 chara{base*10:06d}/Chara.xml 的 addImages{var}"
            fly_message(self, "完成", msg)
            self.accept()
        except DdsToolError as e:
            fly_critical(self, "DDS 转换失败", str(e))
        except Exception as e:
            fly_critical(self, "错误", str(e))
