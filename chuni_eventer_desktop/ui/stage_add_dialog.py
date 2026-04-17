from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QFormLayout, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CardWidget, LineEdit, PrimaryPushButton, PushButton

from ..dds_convert import DdsToolError
from ..stage_from_image import StageAfbToolError, StageCreateOptions, create_stage_from_image
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical, fly_message


def _safe_int(text: str) -> int | None:
    try:
        return int(text.strip())
    except Exception:
        return None


class StageAddDialog(FluentCaptionDialog):
    def __init__(
        self,
        *,
        acus_root: Path,
        tool_path: Path | None,
        game_root: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("图片转背景(Stage)")
        self.setModal(True)
        self.resize(560, 520)
        self._acus_root = acus_root
        self._tool = tool_path
        self._game_root = game_root

        self.id_edit = LineEdit(self)
        self.id_edit.setPlaceholderText("例如 27201")
        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText("例如 メダリスト")
        self.image_edit = LineEdit(self)
        self.image_edit.setPlaceholderText("选择图片或 DDS（DDS 必须 BC3）")
        self.line_id_edit = LineEdit(self)
        self.line_id_edit.setText("8")
        self.line_str_edit = LineEdit(self)
        self.line_str_edit.setText("White")
        self.notes_afb_edit = LineEdit(self)
        self.base_afb_edit = LineEdit(self)

        card = CardWidget(self)
        cly = QVBoxLayout(card)
        cly.setContentsMargins(16, 14, 16, 14)
        cly.setSpacing(10)
        cly.addWidget(BodyLabel("根据图片生成 Stage.xml 与预览 DDS"))

        form = QFormLayout()
        form.addRow("Stage ID", self.id_edit)
        form.addRow("显示名", self.name_edit)
        form.addRow("预览图", self._file_row(self.image_edit, "选择背景图"))
        form.addRow("判定线 ID", self.line_id_edit)
        form.addRow("判定线 str", self.line_str_edit)
        form.addRow("notesFieldFile", self.notes_afb_edit)
        form.addRow("baseFile", self.base_afb_edit)
        cly.addLayout(form)

        hint = BodyLabel(
            "说明：会在 ACUS/stage/stageXXXXXX 下创建 Stage.xml；若提供图片则写入 "
            "CHU_UI_Stage_xxxxx.dds 并填到 image/path。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#6b7280;")
        cly.addWidget(hint)

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
        p, _ = QFileDialog.getOpenFileName(self, title)
        if p:
            edit.setText(p)

    def _run(self) -> None:
        try:
            sid = _safe_int(self.id_edit.text())
            if sid is None or sid <= 0:
                raise ValueError("Stage ID 必须为正整数。")
            name = self.name_edit.text().strip() or f"Stage{sid}"
            img_text = self.image_edit.text().strip()
            image_source = Path(img_text).expanduser().resolve() if img_text else None
            if image_source is not None and not image_source.is_file():
                raise ValueError("预览图文件不存在。")
            line_id = _safe_int(self.line_id_edit.text())
            if line_id is None:
                raise ValueError("判定线 ID 必须为整数。")
            line_str = self.line_str_edit.text().strip() or "White"
            opts = StageCreateOptions(
                stage_id=sid,
                stage_name=name,
                image_source=image_source,
                notes_field_line_id=line_id,
                notes_field_line_str=line_str,
                notes_field_file=(self.notes_afb_edit.text().strip() or None),
                base_file=(self.base_afb_edit.text().strip() or None),
            )
            out = create_stage_from_image(
                acus_root=self._acus_root,
                tool_path=self._tool,
                opts=opts,
                game_root=self._game_root,
                use_external_afb=True,
            )
            fly_message(self, "完成", f"已生成：\n{out.parent}")
            self.accept()
        except DdsToolError as e:
            fly_critical(self, "DDS 转换失败", str(e))
        except StageAfbToolError as e:
            fly_critical(self, "AFB 生成失败", str(e))
        except Exception as e:
            fly_critical(self, "创建失败", str(e))

