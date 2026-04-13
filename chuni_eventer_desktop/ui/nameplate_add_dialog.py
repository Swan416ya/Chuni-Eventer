from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import BodyLabel, CardWidget, LineEdit, PrimaryPushButton, PushButton

from ..dds_convert import DdsToolError, ingest_to_bc3_dds
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical, fly_message
from .name_glyph_preview import wrap_name_input_with_preview


def _safe_int(text: str) -> int | None:
    try:
        return int(text.strip())
    except Exception:
        return None


class NamePlateAddDialog(FluentCaptionDialog):
    def __init__(self, *, acus_root: Path, tool_path: Path | None, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("新增名牌")
        self.setModal(True)
        self.resize(520, 480)
        self._acus_root = acus_root
        self._tool = tool_path

        self.id_edit = LineEdit(self)
        self.id_edit.setPlaceholderText("例如 26017")
        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText("例如 淀川 沙音瑠")
        self.sort_edit = LineEdit(self)
        self.sort_edit.setPlaceholderText("可不填，默认取名字第1字")
        self.image_edit = LineEdit(self)
        self.image_edit.setPlaceholderText("选择名牌图片或 DDS（DDS 需为 BC3）")

        main_card = CardWidget(self)
        main_lay = QVBoxLayout(main_card)
        main_lay.setContentsMargins(16, 14, 16, 14)
        main_lay.setSpacing(10)
        main_lay.addWidget(BodyLabel("名牌信息", self))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("NamePlate ID", self.id_edit)
        form.addRow("显示名", wrap_name_input_with_preview(self.name_edit, parent=self))
        form.addRow("排序名", wrap_name_input_with_preview(self.sort_edit, parent=self))
        form.addRow(
            "图片",
            self._file_row(
                self.image_edit,
                "选择名牌图片",
                dim_hint=(
                    "参考分辨率：576 × 228 像素；下方可留空，内容物请靠在整张图最上方排版。"
                    " 也可直接上传 DDS（必须 BC3/DXT5）。"
                ),
            ),
        )
        main_lay.addLayout(form)

        ok = PrimaryPushButton("生成并写入 ACUS", self)
        ok.clicked.connect(self._run)
        cancel = PushButton("取消", self)
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*fluent_caption_content_margins())
        layout.setSpacing(12)
        layout.addWidget(main_card)
        warn = BodyLabel(self)
        warn.setWordWrap(True)
        warn.setText(
            "提示：名称/排序名请尽量使用日语字库内可显示字符；超出字库的汉字在游戏内可能显示为方块。"
        )
        warn.setStyleSheet("color:#B45309; font-size:12px;")
        layout.addWidget(warn)
        layout.addStretch(1)
        layout.addLayout(btns)

    def _file_row(self, edit: QLineEdit, title: str, *, dim_hint: str | None = None) -> QWidget:
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
            hint = BodyLabel(self)
            hint.setText(dim_hint)
            hint.setWordWrap(True)
            hint.setTextColor("#6B7280", "#9CA3AF")
            v.addWidget(hint)
        return w

    def _pick_into(self, edit: QLineEdit, title: str) -> None:
        p, _ = QFileDialog.getOpenFileName(self, title)
        if p:
            edit.setText(p)

    def _run(self) -> None:
        try:
            nid = _safe_int(self.id_edit.text())
            if nid is None or nid < 0:
                raise ValueError("NamePlate ID 必须是非负整数")

            name = self.name_edit.text().strip() or f"NamePlate{nid}"
            sort_name = self.sort_edit.text().strip() or name[:1]
            src = Path(self.image_edit.text().strip()).expanduser()
            if not src.exists():
                raise ValueError("名牌图片路径不存在")

            plate_dir = self._acus_root / "namePlate" / f"namePlate{nid:08d}"
            plate_dir.mkdir(parents=True, exist_ok=True)
            dds_name = f"CHU_UI_NamePlate_{nid:08d}.dds"
            dds_path = plate_dir / dds_name
            ingest_to_bc3_dds(tool_path=self._tool, input_path=src, output_dds=dds_path)

            xml = f"""<?xml version="1.0" encoding="utf-8"?>
<NamePlateData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>namePlate{nid:08d}</dataName>
  <netOpenName><id>2801</id><str>v2_45 00_1</str><data /></netOpenName>
  <disableFlag>false</disableFlag>
  <name><id>{nid}</id><str>{name}</str><data /></name>
  <sortName>{sort_name}</sortName>
  <image><path>{dds_name}</path></image>
  <defaultHave>false</defaultHave>
  <explainText>-</explainText>
  <priority>0</priority>
</NamePlateData>
"""
            (plate_dir / "NamePlate.xml").write_text(xml, encoding="utf-8")

            fly_message(self, "完成", f"已生成 namePlate{nid:08d}")
            self.accept()
        except DdsToolError as e:
            fly_critical(self, "DDS 转换失败", str(e))
        except Exception as e:
            fly_critical(self, "错误", str(e))
