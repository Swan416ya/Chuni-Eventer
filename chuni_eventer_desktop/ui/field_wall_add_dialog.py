from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from qfluentwidgets import BodyLabel, CardWidget, LineEdit as FluentLineEdit, PrimaryPushButton, PushButton

from ..dds_convert import DdsToolError
from ..field_wall_from_image import FieldWallCreateOptions, create_field_wall_from_image
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical, fly_message


class FieldWallAddDialog(FluentCaptionDialog):
    def __init__(
        self,
        *,
        acus_root: Path,
        tool_path: Path | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("替换默认挡板（FieldWall）")
        self.setModal(True)
        self.resize(480, 420)
        self._acus_root = acus_root
        self._tool = tool_path

        self.name_edit = FluentLineEdit(self)
        self.name_edit.setPlaceholderText("例如 フィールドウォール0001（留空则使用默认名）")
        self.name_edit.setText("フィールドウォール0001")
        self.image_edit = FluentLineEdit(self)
        self.image_edit.setPlaceholderText("选择一张图片（建议 640×480，其他尺寸会自动裁切/补齐）")

        card = CardWidget(self)
        cly = QVBoxLayout(card)
        cly.setContentsMargins(16, 16, 16, 16)
        cly.setSpacing(12)
        cly.addWidget(BodyLabel("默认挡板贴图替换（ddsFieldWall0001）"))

        hint = BodyLabel(
            "建议 640×480（4:3），其他尺寸会自动裁切/补齐。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#6b7280;font-size:13px;")
        cly.addWidget(hint)

        form = QFormLayout()
        form.addRow("显示名", self.name_edit)
        form.addRow("贴图图片", self._file_row(self.image_edit, "选择挡板贴图"))
        cly.addLayout(form)

        self._preview_label = BodyLabel("")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumSize(420, 315)
        self._preview_label.setStyleSheet(
            "background:#0b1220;border:1px solid rgba(148,163,184,0.35);border-radius:8px;"
        )
        cly.addWidget(self._preview_label)

        ok = PrimaryPushButton("生成并写入 ACUS", self)
        ok.clicked.connect(self._run)
        cancel = PushButton("取消", self)
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*fluent_caption_content_margins())
        lay.setSpacing(12)
        lay.addWidget(card)
        lay.addStretch(1)
        lay.addLayout(btns)
        self.image_edit.textChanged.connect(self._update_preview)
        self._update_preview()

    def _file_row(self, edit: QLineEdit, title: str) -> QWidget:
        w = QWidget(self)
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        h.addWidget(edit, stretch=1)
        b = PushButton("浏览…", self)
        b.clicked.connect(lambda: self._pick_into(edit, title))
        h.addWidget(b)
        return w

    def _pick_into(self, edit: QLineEdit, title: str) -> None:
        p, _ = QFileDialog.getOpenFileName(
            self,
            title,
            "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;所有文件 (*.*)",
        )
        if p:
            edit.setText(p)

    def _update_preview(self) -> None:
        p = self.image_edit.text().strip()
        if not p:
            self._preview_label.setText("暂无预览")
            self._preview_label.setPixmap(QPixmap())
            return
        src_path = Path(p).expanduser()
        src = QPixmap(str(src_path))
        if src.isNull():
            self._preview_label.setText("无法读取图片")
            self._preview_label.setPixmap(QPixmap())
            return
        show = src.scaled(
            self._preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview_label.setText("")
        self._preview_label.setPixmap(show)

    def _run(self) -> None:
        try:
            img_text = self.image_edit.text().strip()
            image_source = Path(img_text).expanduser().resolve() if img_text else None
            if image_source is None or not image_source.is_file():
                raise ValueError("请提供挡板贴图图片。")
            wall_name = self.name_edit.text().strip() or "フィールドウォール0001"
            opts = FieldWallCreateOptions(
                image_source=image_source,
                wall_name=wall_name,
            )
            out = create_field_wall_from_image(
                acus_root=self._acus_root,
                tool_path=self._tool,
                opts=opts,
            )
            fly_message(self, "完成", f"已生成：\n{out.parent}")
            self.accept()
        except DdsToolError as e:
            fly_critical(self, "DDS 转换失败", str(e))
        except Exception as e:
            fly_critical(self, "创建失败", str(e))