from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
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


class TrophyAddDialog(QDialog):
    def __init__(self, *, acus_root: Path, tool_path: Path, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("新增称号 (Trophy)")
        self.setModal(True)
        self._acus_root = acus_root
        self._tool = tool_path

        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText("例如 9760")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如 Ave Mujica")
        self.explain_edit = QLineEdit()
        self.explain_edit.setPlaceholderText("可不填，默认 -")
        self.rare_edit = QLineEdit()
        self.rare_edit.setPlaceholderText("可不填，默认 6")
        self.image_edit = QLineEdit()
        self.image_edit.setPlaceholderText("可选：选择称号图片（将转 BC3 DDS）")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("Trophy ID", self.id_edit)
        form.addRow("显示名", self.name_edit)
        form.addRow("说明", self.explain_edit)
        form.addRow("稀有度", self.rare_edit)
        form.addRow("图片", self._file_row(self.image_edit, "选择称号图片"))

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
            tid = _safe_int(self.id_edit.text())
            if tid is None or tid < 0:
                raise ValueError("Trophy ID 必须是非负整数")

            name = self.name_edit.text().strip() or f"Trophy{tid}"
            explain = self.explain_edit.text().strip() or "-"
            rare = _safe_int(self.rare_edit.text())
            if rare is None:
                rare = 6
            src_text = self.image_edit.text().strip()
            src = Path(src_text).expanduser() if src_text else None

            tdir = self._acus_root / "trophy" / f"trophy{tid:06d}"
            tdir.mkdir(parents=True, exist_ok=True)
            dds_name = f"CHU_UI_Trophy_{tid:06d}.dds"
            image_path_xml = ""
            if src is not None:
                if not src.exists():
                    raise ValueError("称号图片路径不存在")
                dds_path = tdir / dds_name
                convert_to_bc3_dds(tool_path=self._tool, input_image=src, output_dds=dds_path)
                image_path_xml = dds_name

            xml = f"""<?xml version="1.0" encoding="utf-8"?>
<TrophyData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>trophy{tid:06d}</dataName>
  <netOpenName><id>2801</id><str>v2_45 00_1</str><data /></netOpenName>
  <disableFlag>false</disableFlag>
  <name><id>{tid}</id><str>{name}</str><data /></name>
  <explainText>{explain}</explainText>
  <defaultHave>false</defaultHave>
  <rareType>{rare}</rareType>
  <image><path>{image_path_xml}</path></image>
  <normCondition><conditions /></normCondition>
  <priority>0</priority>
</TrophyData>
"""
            (tdir / "Trophy.xml").write_text(xml, encoding="utf-8")

            QMessageBox.information(self, "完成", f"已生成 trophy{tid:06d}")
            self.accept()
        except DdsToolError as e:
            QMessageBox.critical(self, "DDS 转换失败", str(e))
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

