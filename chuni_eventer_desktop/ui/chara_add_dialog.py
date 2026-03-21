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

from ..chuni_formats import ChuniCharaId
from ..dds_convert import DdsToolError, convert_to_bc3_dds
from ..xml_writer import write_chara_xml, write_ddsimage_xml


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

        self.head = QLineEdit()
        self.half = QLineEdit()
        self.full = QLineEdit()
        for e in (self.head, self.half, self.full):
            e.setPlaceholderText("选择图片文件（png/jpg/webp…）")

        self.base.textChanged.connect(self._update_preview)
        self.variant.textChanged.connect(self._update_preview)
        self._update_preview()

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("基ID", self.base)
        form.addRow("变体", self.variant)
        form.addRow("最终ID", self.cid_preview)
        form.addRow("角色名", self.name)
        # A001：CHU_UI_Character_*_00/01/02 = 全身 / 半身 / 大头（与 ddsFile0/1/2 一致）
        form.addRow(
            "全身（_00）",
            self._file_row(self.full, "选择全身图", dim_hint="参考分辨率（A001）：1493 × 1027 像素"),
        )
        form.addRow(
            "半身（_01）",
            self._file_row(self.half, "选择半身图", dim_hint="参考分辨率（A001）：688 × 474 像素"),
        )
        form.addRow(
            "大头（_02）",
            self._file_row(self.head, "选择大头图", dim_hint="参考分辨率（A001）：545 × 375 像素"),
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

            for src, dst in (
                (full, dds_dir / cid.dds_filename(0)),
                (half, dds_dir / cid.dds_filename(1)),
                (head, dds_dir / cid.dds_filename(2)),
            ):
                convert_to_bc3_dds(tool_path=self._tool, input_image=src, output_dds=dst)

            write_ddsimage_xml(out_dir=self._acus_root, chara_id=cid.raw)
            write_chara_xml(out_dir=self._acus_root, chara_id=cid.raw, chara_name=self.name.text().strip())

            QMessageBox.information(self, "完成", f"已写入 ACUS：角色 {cid.raw}")
            self.accept()
        except DdsToolError as e:
            QMessageBox.critical(self, "DDS 转换失败", str(e))
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

