from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..chuni_formats import ChuniCharaId
from ..dds_convert import DdsToolError
from ..xml_writer import ensure_chara_works_xml, write_chara_xml, write_ddsimage_xml
from .dds_progress import run_bc3_jobs_with_progress
from .works_dialogs import combo_works_id_str, make_works_picker_row, works_warning_label


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


class CharaAddDialog(QDialog):
    def __init__(self, *, acus_root: Path, tool_path: Path | None, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("新增角色")
        self.setModal(True)
        self._acus_root = acus_root
        self._tool = tool_path

        self.base = QLineEdit()
        self.base.setPlaceholderText("角色基ID（例如 2469）")
        self.variant = QLineEdit()
        self.variant.setPlaceholderText("变体 0-9（例如 0）")
        self.cid_preview = QLineEdit()
        self.cid_preview.setReadOnly(True)

        self.name = QLineEdit()
        self.name.setPlaceholderText("角色显示名")
        self.illustrator = QLineEdit()
        self.illustrator.setPlaceholderText("绘师 / illustratorName.str（可选，不填则 Invalid）")

        self.head = QLineEdit()
        self.half = QLineEdit()
        self.full = QLineEdit()
        for e in (self.head, self.half, self.full):
            e.setPlaceholderText("选择图片或 DDS（DDS 需为 BC3）")

        self.base.textChanged.connect(self._update_preview)
        self.variant.textChanged.connect(self._update_preview)
        self._update_preview()

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("基ID", self.base)
        form.addRow("变体", self.variant)
        form.addRow("最终ID", self.cid_preview)
        form.addRow("角色名", self.name)
        form.addRow("绘师（可选）", self.illustrator)
        self._works_row, self._works_combo = make_works_picker_row(parent=self, acus_root=self._acus_root)
        form.addRow("作品（works）", self._works_row)
        form.addRow("", works_warning_label())
        # releaseTagName 固定为 -1 / Invalid；游戏侧通过 ACUS 预置的 releaseTag XML 显示为「自制譜」等，不由本工具填写。
        # A001：CHU_UI_Character_*_00/01/02 = 全身 / 半身 / 大头（与 ddsFile0/1/2 一致）
        form.addRow(
            "全身（_00）",
            self._file_row(
                self.full,
                "选择全身图",
                dim_hint="参考分辨率：1024 × 1024 像素；也可直传 BC3 DDS。",
            ),
        )
        form.addRow(
            "半身（_01）",
            self._file_row(
                self.half,
                "选择半身图",
                dim_hint="参考分辨率：512 × 512 像素；也可直传 BC3 DDS。",
            ),
        )
        form.addRow(
            "大头（_02）",
            self._file_row(
                self.head,
                "选择大头图",
                dim_hint="参考分辨率：128 × 128 像素；也可直传 BC3 DDS。",
            ),
        )

        ok = QPushButton("生成并写入 ACUS")
        ok.clicked.connect(self._run)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)

        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        warn = QLabel("提示：角色名请尽量使用日语字库内可显示字符；超出字库的汉字在游戏内可能显示为方块。")
        warn.setStyleSheet("color:#B45309;")
        layout.addWidget(warn)
        layout.addLayout(btns)

    def _file_row(self, edit: QLineEdit, title: str, *, dim_hint: str | None = None) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(edit, stretch=1)
        b = QPushButton("浏览…")
        b.clicked.connect(lambda: self._pick_into(edit, title))
        h.addWidget(b)
        v.addWidget(row)
        if dim_hint:
            hint = QLabel(dim_hint)
            hint.setStyleSheet("color:#6B7280; font-size: 11px;")
            hint.setWordWrap(True)
            v.addWidget(hint)
        return w

    def _pick_into(self, edit: QLineEdit, title: str) -> None:
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
            w_id, w_str = combo_works_id_str(self._works_combo)
            if var == 0:
                write_chara_xml(
                    out_dir=self._acus_root,
                    chara_id=cid.raw,
                    chara_name=chara_name,
                    illustrator_name=ill,
                    release_tag_id=-1,
                    release_tag_str="Invalid",
                    works_id=w_id,
                    works_str=w_str,
                )
                ensure_chara_works_xml(
                    out_dir=self._acus_root,
                    works_id=w_id,
                    works_str=w_str,
                    release_tag_id=-1,
                    release_tag_str="Invalid",
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
            QMessageBox.information(self, "完成", msg)
            self.accept()
        except DdsToolError as e:
            QMessageBox.critical(self, "DDS 转换失败", str(e))
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

