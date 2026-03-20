from __future__ import annotations

from pathlib import Path

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

from ..dds_convert import DdsToolError, convert_to_bc3_dds


def _safe_int(text: str) -> int | None:
    try:
        return int(text.strip())
    except Exception:
        return None


class NamePlateAddDialog(QDialog):
    def __init__(self, *, acus_root: Path, tool_path: Path | None, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("新增名牌")
        self.setModal(True)
        self._acus_root = acus_root
        self._tool = tool_path

        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText("例如 26017")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如 淀川 沙音瑠")
        self.sort_edit = QLineEdit()
        self.sort_edit.setPlaceholderText("可不填，默认取名字第1字")
        self.image_edit = QLineEdit()
        self.image_edit.setPlaceholderText("选择名牌图片（将转 BC3 DDS）")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("NamePlate ID", self.id_edit)
        form.addRow("显示名", self.name_edit)
        form.addRow("排序名", self.sort_edit)
        form.addRow("图片", self._file_row(self.image_edit, "选择名牌图片"))

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
        warn = QLabel("提示：名称/排序名请尽量使用日语字库内可显示字符；超出字库的汉字在游戏内可能显示为方块。")
        warn.setStyleSheet("color:#B45309;")
        layout.addWidget(warn)
        layout.addLayout(btns)

    def _file_row(self, edit: QLineEdit, title: str) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(edit, stretch=1)
        b = QPushButton("浏览…")
        b.clicked.connect(lambda: self._pick_into(edit, title))
        h.addWidget(b)
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
            convert_to_bc3_dds(tool_path=self._tool, input_image=src, output_dds=dds_path)

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

            QMessageBox.information(self, "完成", f"已生成 namePlate{nid:08d}")
            self.accept()
        except DdsToolError as e:
            QMessageBox.critical(self, "DDS 转换失败", str(e))
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

