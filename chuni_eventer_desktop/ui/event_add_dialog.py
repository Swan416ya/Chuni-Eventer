from __future__ import annotations

from pathlib import Path
import struct
import xml.etree.ElementTree as ET

from PIL import Image, UnidentifiedImageError

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


PROMO_WIDTH = 1152
PROMO_HEIGHT = 648


def _safe_int(text: str) -> int | None:
    try:
        return int(text.strip())
    except Exception:
        return None


def _xml_text(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _read_dds_size(path: Path) -> tuple[int, int] | None:
    try:
        raw = path.read_bytes()
    except Exception:
        return None
    if len(raw) < 128 or raw[:4] != b"DDS ":
        return None
    try:
        h = struct.unpack_from("<I", raw, 12)[0]
        w = struct.unpack_from("<I", raw, 16)[0]
        if w <= 0 or h <= 0:
            return None
        return w, h
    except Exception:
        return None


def next_custom_event_id(acus_root: Path, *, start: int = 70000) -> int:
    used: set[int] = set()
    event_root = acus_root / "event"
    if event_root.exists():
        for p in event_root.glob("event*"):
            if not p.is_dir():
                continue
            suffix = p.name[5:]
            if suffix.isdigit():
                used.add(int(suffix))
        sort_path = event_root / "EventSort.xml"
        if sort_path.exists():
            try:
                root = ET.parse(sort_path).getroot()
                for n in root.findall("./SortList/StringID/id"):
                    v = _safe_int((n.text or "").strip())
                    if v is not None:
                        used.add(v)
            except Exception:
                pass
    cur = max(0, start)
    while cur in used:
        cur += 1
    return cur


def append_event_sort(acus_root: Path, event_id: int) -> None:
    sort_path = acus_root / "event" / "EventSort.xml"
    if not sort_path.exists():
        sort_path.write_text(
            """<?xml version="1.0" encoding="utf-8"?>
<SerializeSortData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>event</dataName>
  <SortList>
  </SortList>
</SerializeSortData>
""",
            encoding="utf-8",
        )
    root = ET.parse(sort_path).getroot()
    sl = root.find("SortList")
    if sl is None:
        return
    for n in sl.findall("StringID/id"):
        if _safe_int((n.text or "").strip()) == event_id:
            ET.indent(root)  # type: ignore[attr-defined]
            ET.ElementTree(root).write(sort_path, encoding="utf-8", xml_declaration=True)
            return
    s = ET.SubElement(sl, "StringID")
    ET.SubElement(s, "id").text = str(event_id)
    ET.SubElement(s, "str")
    ET.SubElement(s, "data")
    ET.indent(root)  # type: ignore[attr-defined]
    ET.ElementTree(root).write(sort_path, encoding="utf-8", xml_declaration=True)


class EventAddDialog(FluentCaptionDialog):
    def __init__(self, *, acus_root: Path, tool_path: Path | None, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("新建宣传事件")
        self.setModal(True)
        self.resize(560, 520)
        self._acus_root = acus_root
        self._tool = tool_path

        alloc = next_custom_event_id(acus_root)
        self.id_edit = LineEdit(self)
        self.id_edit.setText(str(alloc))
        self.id_edit.setPlaceholderText("留空自动分配 70000+")
        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText("活动标题（写入 name/str）")
        self.image_edit = LineEdit(self)
        self.image_edit.setPlaceholderText("选择宣传图（1152x648；支持图片或 DDS）")

        main_card = CardWidget(self)
        main_lay = QVBoxLayout(main_card)
        main_lay.setContentsMargins(16, 14, 16, 14)
        main_lay.setSpacing(10)
        main_lay.addWidget(BodyLabel("宣传事件", self))
        hint = BodyLabel(self)
        hint.setWordWrap(True)
        hint.setText(
            "宣传图要求：1152 × 648 像素。\n"
            "可上传图片（将转 BC3 DDS）或直接上传 DDS（必须 BC3/DXT5）。\n"
            "事件结构与官方「Collaboration 告知」一致：substances/type=1，informationDispType=3。"
        )
        hint.setTextColor("#6B7280", "#9CA3AF")
        main_lay.addWidget(hint)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("事件 ID", self.id_edit)
        form.addRow("标题", wrap_name_input_with_preview(self.name_edit, parent=self))
        form.addRow("宣传图", self._file_row(self.image_edit, "选择宣传图"))
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
        layout.addStretch(1)
        layout.addLayout(btns)

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
            "Image or DDS (*.dds *.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;All (*)",
        )
        if p:
            edit.setText(p)

    def _validate_image_size(self, src: Path) -> None:
        if src.suffix.lower() == ".dds":
            wh = _read_dds_size(src)
            if wh is None:
                raise ValueError("DDS 文件头无效，无法读取分辨率")
            w, h = wh
        else:
            try:
                with Image.open(src) as im:
                    im.load()
                    w, h = im.size
            except UnidentifiedImageError as e:
                raise ValueError(f"无法识别图片：{e}") from e
            except OSError as e:
                raise ValueError(f"无法读取图片：{e}") from e
        if (w, h) != (PROMO_WIDTH, PROMO_HEIGHT):
            raise ValueError(
                f"宣传图分辨率必须为 {PROMO_WIDTH}x{PROMO_HEIGHT}，当前为 {w}x{h}"
            )

    def _run(self) -> None:
        try:
            eid = _safe_int(self.id_edit.text())
            if eid is None:
                eid = next_custom_event_id(self._acus_root)
            if eid < 0:
                raise ValueError("事件 ID 必须为非负整数")
            name = self.name_edit.text().strip() or f"宣传事件{eid}"
            src = Path(self.image_edit.text().strip()).expanduser()
            if not src.is_file():
                raise ValueError("请选择有效的宣传图文件")
            self._validate_image_size(src)

            edir = self._acus_root / "event" / f"event{eid:08d}"
            edir.mkdir(parents=True, exist_ok=True)
            dds_name = f"CHU_info_event_custom{eid:08d}.dds"
            ingest_to_bc3_dds(tool_path=self._tool, input_path=src, output_dds=edir / dds_name)

            title = _xml_text(name)
            xml = f"""<?xml version='1.0' encoding='utf-8'?>
<EventData>
  <dataName>event{eid:08d}</dataName>
  <netOpenName>
    <id>2801</id>
    <str>v2_45 00_1</str>
    <data />
  </netOpenName>
  <name>
    <id>{eid}</id>
    <str>{title}</str>
    <data />
  </name>
  <text />
  <ddsBannerName>
    <id>-1</id>
    <str>Invalid</str>
    <data />
  </ddsBannerName>
  <periodDispType>1</periodDispType>
  <alwaysOpen>true</alwaysOpen>
  <teamOnly>false</teamOnly>
  <isKop>false</isKop>
  <priority>0</priority>
  <substances>
    <type>1</type>
    <flag>
      <value>0</value>
    </flag>
    <information>
      <informationType>1</informationType>
      <informationDispType>3</informationDispType>
      <mapFilterID>
        <id>0</id>
        <str>Collaboration</str>
        <data>イベント</data>
      </mapFilterID>
      <courseNames>
        <list />
      </courseNames>
      <text />
      <image>
        <path>{dds_name}</path>
      </image>
      <movieName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </movieName>
      <presentNames>
        <list />
      </presentNames>
    </information>
    <map>
      <tagText />
      <mapName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </mapName>
      <musicNames>
        <list />
      </musicNames>
    </map>
    <music>
      <musicType>0</musicType>
      <musicNames>
        <list />
      </musicNames>
    </music>
    <advertiseMovie>
      <firstMovieName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </firstMovieName>
      <secondMovieName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </secondMovieName>
    </advertiseMovie>
    <recommendMusic>
      <musicNames>
        <list />
      </musicNames>
    </recommendMusic>
    <release>
      <value>0</value>
    </release>
    <course>
      <courseNames>
        <list />
      </courseNames>
    </course>
    <quest>
      <questNames>
        <list />
      </questNames>
    </quest>
    <duel>
      <duelName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </duelName>
    </duel>
    <cmission>
      <cmissionName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </cmissionName>
    </cmission>
    <changeSurfBoardUI>
      <value>0</value>
    </changeSurfBoardUI>
    <avatarAccessoryGacha>
      <avatarAccessoryGachaName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </avatarAccessoryGachaName>
    </avatarAccessoryGacha>
    <rightsInfo>
      <rightsNames>
        <list />
      </rightsNames>
    </rightsInfo>
    <playRewardSet>
      <playRewardSetName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </playRewardSetName>
    </playRewardSet>
    <dailyBonusPreset>
      <dailyBonusPresetName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </dailyBonusPresetName>
    </dailyBonusPreset>
    <matchingBonus>
      <timeTableName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </timeTableName>
    </matchingBonus>
    <unlockChallenge>
      <unlockChallengeName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </unlockChallengeName>
    </unlockChallenge>
    <linkedVerse>
      <linkedVerseName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </linkedVerseName>
    </linkedVerse>
  </substances>
</EventData>
"""
            (edir / "Event.xml").write_text(xml, encoding="utf-8", newline="\n")
            append_event_sort(self._acus_root, eid)
            fly_message(self, "完成", f"已生成 event{eid:08d}")
            self.accept()
        except DdsToolError as e:
            fly_critical(self, "DDS 转换失败", str(e))
        except Exception as e:
            fly_critical(self, "错误", str(e))
