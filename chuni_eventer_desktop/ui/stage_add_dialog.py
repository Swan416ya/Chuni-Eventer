from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from PyQt6.QtWidgets import QFileDialog, QFormLayout, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget
from PyQt6.QtGui import QColor, QIcon, QPixmap
from qfluentwidgets import BodyLabel, CardWidget, ComboBox as FluentComboBox, LineEdit, PrimaryPushButton, PushButton

from ..dds_convert import DdsToolError
from ..stage_from_image import StageAfbToolError, StageCreateOptions, create_stage_from_image
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical, fly_message


def _safe_int(text: str) -> int | None:
    try:
        return int(text.strip())
    except Exception:
        return None


def _next_stage_id(acus_root: Path, start: int = 70000) -> int:
    used: set[int] = set()
    sroot = acus_root / "stage"
    if not sroot.is_dir():
        return start
    for xp in sroot.glob("stage*/Stage.xml"):
        try:
            rid = int((ET.parse(xp).getroot().findtext("name/id") or "").strip())
            if rid > 0:
                used.add(rid)
        except Exception:
            continue
    cand = max(1, int(start))
    while cand in used:
        cand += 1
    return cand


_FIELD_LINE_CHOICES: tuple[tuple[int, str, str, str], ...] = (
    (0, "Orange", "橙色", "#F59E0B"),
    (1, "Blue", "蓝色", "#3B82F6"),
    (2, "Green", "绿色", "#22C55E"),
    (3, "Navy", "海军蓝", "#1E3A8A"),
    (4, "Olive", "橄榄绿", "#6B8E23"),
    (5, "Purple", "紫色", "#8B5CF6"),
    (6, "Red", "红色", "#EF4444"),
    (7, "SkyBlue", "天蓝", "#38BDF8"),
    (8, "White", "白色", "#F3F4F6"),
    (9, "Yellow", "黄色", "#FACC15"),
)

def _color_swatch_icon(hex_color: str) -> QIcon:
    pm = QPixmap(14, 14)
    pm.fill(QColor(hex_color))
    return QIcon(pm)


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
        self.id_edit.setText(str(_next_stage_id(self._acus_root, start=70000)))
        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText("例如 メダリスト")
        self.image_edit = LineEdit(self)
        self.image_edit.setPlaceholderText("必须选择 1920x1080 的背景图（游戏内最终显示）")
        self.line_combo = FluentComboBox(self)
        for lid, lstr, lzh, lhex in _FIELD_LINE_CHOICES:
            self.line_combo.addItem(f"{lstr}（{lzh}）", _color_swatch_icon(lhex), lid)
        self.line_combo.setCurrentIndex(8)

        card = CardWidget(self)
        cly = QVBoxLayout(card)
        cly.setContentsMargins(16, 14, 16, 14)
        cly.setSpacing(10)
        cly.addWidget(BodyLabel("根据 1920x1080 背景图生成 Stage（AFB + 预览DDS）"))

        form = QFormLayout()
        form.addRow("Stage ID", self.id_edit)
        form.addRow("显示名", self.name_edit)
        form.addRow("背景图", self._file_row(self.image_edit, "选择背景图"))
        form.addRow("判定线颜色", self.line_combo)
        cly.addLayout(form)

        hint = BodyLabel(
            "规则：输入背景图必须是 1920x1080；\n"
            "1) AFB 生成会直接使用原始 1920x1080 图走外部 convert_stage 工具链；\n"
            "2) 背景图会按 960x540 + 顶部 450 裁切覆盖 + 轨道半透明图叠加后，再转 BC3 DDS。"
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
        p, _ = QFileDialog.getOpenFileName(
            self,
            title,
            "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;所有文件 (*.*)",
        )
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
                raise ValueError("背景图文件不存在。")
            if image_source is None:
                raise ValueError("请提供 1920x1080 背景图。")
            combo_idx = self.line_combo.currentIndex()
            if combo_idx < 0 or combo_idx >= len(_FIELD_LINE_CHOICES):
                raise ValueError("请选择判定线颜色。")
            line_id, line_str, line_zh, _line_hex = _FIELD_LINE_CHOICES[combo_idx]
            opts = StageCreateOptions(
                stage_id=sid,
                stage_name=name,
                image_source=image_source,
                notes_field_line_id=line_id,
                notes_field_line_str=line_str,
                notes_field_line_data=line_zh,
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

