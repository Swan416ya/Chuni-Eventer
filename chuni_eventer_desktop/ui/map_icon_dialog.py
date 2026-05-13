from __future__ import annotations

import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QFileDialog, QFormLayout, QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import BodyLabel, CardWidget, LineEdit, PrimaryPushButton, PushButton

from ..dds_convert import DdsToolError, ingest_to_bc3_dds, is_bc3_dds
from ..dds_quicktex import quicktex_available
from ..map_icon_xml import (
    map_icon_dds_basename,
    map_icon_dir_name,
    suggest_next_map_icon_id,
    write_map_icon_xml,
)
from .dds_progress import run_bc3_jobs_with_progress
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical
from .name_glyph_preview import wrap_name_input_with_preview


MAP_ICON_PX = 256


def _safe_int(text: str) -> int | None:
    try:
        return int(text.strip())
    except Exception:
        return None


def letterbox_to_map_icon_rgba(source_path: Path) -> QImage:
    """等比缩放 + 透明底居中补齐至 MAP_ICON_PX 方形。"""
    img = QImage(str(source_path))
    if img.isNull():
        raise ValueError(f"无法读取图片：{source_path}")
    if img.format() != QImage.Format.Format_ARGB32 and img.format() != QImage.Format.Format_RGBA8888:
        img = img.convertToFormat(QImage.Format.Format_ARGB32)
    out = QImage(MAP_ICON_PX, MAP_ICON_PX, QImage.Format.Format_ARGB32)
    out.fill(Qt.GlobalColor.transparent)
    scaled = img.scaled(
        MAP_ICON_PX,
        MAP_ICON_PX,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = (MAP_ICON_PX - scaled.width()) // 2
    y = (MAP_ICON_PX - scaled.height()) // 2
    p = QPainter(out)
    p.drawImage(x, y, scaled)
    p.end()
    return out


class MapIconAddEditDialog(FluentCaptionDialog):
    """新增或编辑跑图小人（MapIcon）：256×256 BC3 DDS + MapIcon.xml。"""

    def __init__(
        self,
        *,
        acus_root: Path,
        tool_path: Path | None,
        game_index,
        edit_map_icon_xml: Path | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self._acus_root = acus_root
        self._tool = tool_path
        self._game_index = game_index
        self._edit_xml = edit_map_icon_xml
        is_edit = edit_map_icon_xml is not None and edit_map_icon_xml.is_file()
        self.setWindowTitle("编辑跑图小人" if is_edit else "新增跑图小人")
        self.setModal(True)
        self.resize(520, 520)

        self.id_edit = LineEdit(self)
        self.id_edit.setPlaceholderText("例如 7000")
        if is_edit:
            self.id_edit.setReadOnly(True)
        else:
            self.id_edit.setText(str(suggest_next_map_icon_id(acus_root, game_index)))

        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText("显示名")

        self.image_edit = LineEdit(self)
        self.image_edit.setPlaceholderText("选择 256×256 图片或 BC3 DDS（非 256 图将自动 letterbox）")

        if is_edit:
            try:
                root = ET.parse(edit_map_icon_xml).getroot()
                mid = _safe_int(root.findtext("name/id") or "")
                mstr = (root.findtext("name/str") or "").strip()
                if mid is not None:
                    self.id_edit.setText(str(mid))
                self.name_edit.setText(mstr)
            except Exception:
                pass

        main_card = CardWidget(self)
        ml = QVBoxLayout(main_card)
        ml.setContentsMargins(16, 14, 16, 14)
        ml.setSpacing(10)
        ml.addWidget(BodyLabel("跑图小人（MapIcon）", self))
        hint = BodyLabel(self)
        hint.setWordWrap(True)
        hint.setText(
            f"建议提供接近 {MAP_ICON_PX}×{MAP_ICON_PX} 的 PNG/JPEG；"
            "若尺寸不同，将等比缩放并以透明边补齐到正方形后再转 BC3。"
        )
        hint.setTextColor("#6B7280", "#9CA3AF")
        ml.addWidget(hint)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("MapIcon ID", self.id_edit)
        form.addRow("显示名", wrap_name_input_with_preview(self.name_edit, parent=self))
        form.addRow(
            "贴图",
            self._file_row(self.image_edit, "选择图片或 DDS"),
        )
        ml.addLayout(form)

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
        layout.addStretch(1)
        layout.addLayout(btns)

    def _file_row(self, edit: LineEdit, title: str) -> QWidget:
        w = QWidget(self)
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        h.addWidget(edit, stretch=1)
        b = PushButton("浏览…", self)
        b.clicked.connect(lambda: self._pick_into(edit, title))
        h.addWidget(b)
        return w

    def _pick_into(self, edit: LineEdit, title: str) -> None:
        p, _ = QFileDialog.getOpenFileName(
            self,
            title,
            "",
            "图片或 DDS (*.png *.jpg *.jpeg *.webp *.bmp *.dds);;所有文件 (*.*)",
        )
        if p:
            edit.setText(p)

    def _run(self) -> None:
        if self._tool is None and not quicktex_available():
            fly_critical(
                self,
                "无法生成 DDS",
                "请安装 quicktex（pip install quicktex）或在【设置】中配置 compressonatorcli。",
            )
            return
        try:
            mid = _safe_int(self.id_edit.text())
            if mid is None or mid < 0:
                raise ValueError("MapIcon ID 必须是非负整数")
            name = self.name_edit.text().strip() or f"MapIcon{mid}"
            src_raw = self.image_edit.text().strip()
            if not src_raw and self._edit_xml is None:
                raise ValueError("请选择贴图文件")
            dds_name = map_icon_dds_basename(mid)
            folder = self._acus_root / "mapIcon" / map_icon_dir_name(mid)
            folder.mkdir(parents=True, exist_ok=True)
            out_dds = folder / dds_name

            if src_raw:
                src = Path(src_raw).expanduser()
                if not src.is_file():
                    raise ValueError("贴图路径不存在")
                if src.suffix.lower() == ".dds":
                    if not is_bc3_dds(src):
                        raise ValueError("DDS 须为 BC3(DXT5)")
                    ingest_to_bc3_dds(tool_path=self._tool, input_path=src, output_dds=out_dds)
                else:
                    rgba = letterbox_to_map_icon_rgba(src)
                    with tempfile.TemporaryDirectory() as td:
                        tp = Path(td) / "map_icon.png"
                        if not rgba.save(str(tp), "PNG"):
                            raise ValueError("无法写出中间 PNG")
                        ok, err = run_bc3_jobs_with_progress(
                            parent=self,
                            tool_path=self._tool,
                            jobs=[(tp, out_dds)],
                            title="正在生成跑图小人 DDS",
                        )
                        if not ok:
                            raise DdsToolError(err or "DDS 编码失败")
            else:
                # 仅改名：保留已有 DDS
                if self._edit_xml is None or not self._edit_xml.is_file():
                    raise ValueError("编辑模式下未选择新图时，无法保留贴图")
                try:
                    root = ET.parse(self._edit_xml).getroot()
                    rel = (root.findtext("image/path") or root.findtext("ddsFile/path") or "").strip()
                except Exception:
                    rel = ""
                if not rel:
                    raise ValueError("当前 MapIcon.xml 未找到贴图路径")
                old = self._edit_xml.parent / rel
                if not old.is_file():
                    raise ValueError("原贴图文件不存在，请重新选择图片")
                if old.resolve() != out_dds.resolve():
                    shutil.copy2(old, out_dds)

            write_map_icon_xml(
                out_dir=self._acus_root,
                map_icon_id=mid,
                name_str=name,
                dds_basename=dds_name,
                preserve_fields_from=self._edit_xml
                if self._edit_xml is not None and self._edit_xml.is_file()
                else None,
            )
            self.accept()
        except DdsToolError as e:
            fly_critical(self.window(), "DDS 转换失败", str(e))
        except Exception as e:
            fly_critical(self.window(), "错误", str(e))
