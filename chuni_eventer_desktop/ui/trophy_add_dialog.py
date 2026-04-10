from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
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

from ..dds_convert import DdsToolError, ingest_to_bc3_dds
from .name_glyph_preview import wrap_name_input_with_preview


def _safe_int(text: str) -> int | None:
    try:
        return int(text.strip())
    except Exception:
        return None


def _xml_text(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# 普通称号（非乐曲AJ）条件模板：对齐 A001 trophy009715 的结构，但字段留空/Invalid
_NORM_CONDITION_EMPTY_TEMPLATE = """<normCondition>
    <conditions>
      <ConditionSubData>
        <type>11</type>
        <eventData>
          <eventNames>
            <list />
          </eventNames>
        </eventData>
        <playMusicData>
          <genreNames>
            <list />
          </genreNames>
          <musicNames>
            <list />
          </musicNames>
          <musicDif>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </musicDif>
        </playMusicData>
        <playSettingData>
          <playOptionSpeed>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </playOptionSpeed>
          <playOptionFieldWallPosition>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </playOptionFieldWallPosition>
          <playOptionMirror>false</playOptionMirror>
        </playSettingData>
        <playMusicResultData>
          <memberNum>0</memberNum>
          <scoreRank>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </scoreRank>
          <matchingResultType>0</matchingResultType>
          <memberRanking>0</memberRanking>
          <gameOver>false</gameOver>
          <fullCombo>false</fullCombo>
          <fullChain>false</fullChain>
          <allJustice>false</allJustice>
          <memberOtherTrophyName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </memberOtherTrophyName>
          <missNum>0</missNum>
          <maxComboNum>0</maxComboNum>
        </playMusicResultData>
        <playTotalResultData>
          <allPlayedMusicName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </allPlayedMusicName>
        </playTotalResultData>
        <personData>
          <playerRebirthCount>0</playerRebirthCount>
          <playerLv>0</playerLv>
          <playerRating>0</playerRating>
          <totalGamePoint>0</totalGamePoint>
          <totalNetBattle>0</totalNetBattle>
          <battleRank>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </battleRank>
        </personData>
        <charaData>
          <targetRank>0</targetRank>
          <charaName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </charaName>
        </charaData>
        <skillData>
          <lvMax>false</lvMax>
        </skillData>
        <trophyData>
          <haveTrophyNames>
            <list />
          </haveTrophyNames>
        </trophyData>
        <travelData>
          <japanRegionID>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </japanRegionID>
          <japanRegionPlayNum>0</japanRegionPlayNum>
          <playedRegionNum>0</playedRegionNum>
          <lapNum>0</lapNum>
        </travelData>
        <musicData>
          <musicName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </musicName>
          <musicDif>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </musicDif>
          <masterUnderAll>false</masterUnderAll>
          <totalPlayNum>0</totalPlayNum>
          <scoreRank>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </scoreRank>
          <fullCombo>false</fullCombo>
          <fullChain>false</fullChain>
          <allJustice>false</allJustice>
          <playNum>0</playNum>
        </musicData>
        <completeData>
          <releaseTagName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </releaseTagName>
          <scoreRank>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </scoreRank>
          <allJustice>false</allJustice>
        </completeData>
      </ConditionSubData>
    </conditions>
  </normCondition>"""


# 无图称号：与游戏内标准稀有度一致（有图时用 ≥50 的自定义段）
TROPHY_PRESET_RARE: tuple[tuple[int, str], ...] = (
    (0, "normal"),
    (1, "bronze"),
    (2, "silver"),
    (3, "gold"),
    (5, "platinum"),
    (7, "rainbow"),
    (9, "staff"),
    (10, "ongeki"),
    (11, "maimai"),
    (12, "irodori silver"),
    (13, "irodori gold"),
    (14, "irodori rainbow"),
)


def max_trophy_rare_type_in_acus(acus_root: Path) -> int:
    """扫描 trophy/**/Trophy.xml 中 rareType 的最大值（无有效文件则为 0）。"""
    m = 0
    for p in acus_root.glob("trophy/**/Trophy.xml"):
        try:
            raw = ET.parse(p).getroot().findtext("rareType")
            v = int((raw or "0").strip())
            m = max(m, v)
        except Exception:
            continue
    return m


def next_trophy_rare_type_with_image(acus_root: Path) -> int:
    """有图称号：固定 rareType=20（按当前实机兼容测试规则）。"""
    _ = acus_root
    return 20


class TrophyAddDialog(QDialog):
    def __init__(self, *, acus_root: Path, tool_path: Path | None, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("新增称号 (Trophy)")
        self.setModal(True)
        self._acus_root = acus_root
        self._tool = tool_path

        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText("例如 9760")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如 曲名（请仅用日语字库内字符）")
        self.name_edit.setToolTip(
            "称号显示名请仅使用游戏日语字库内已有的字符；"
            "生僻汉字或部分符号在游戏内可能显示为□（豆腐块）。"
        )
        self.explain_edit = QLineEdit()
        self.explain_edit.setPlaceholderText("可不填，默认 -")
        self.rare_combo = QComboBox()
        for val, label in TROPHY_PRESET_RARE:
            self.rare_combo.addItem(f"{val} — {label}", val)
        self.rare_auto_label = QLabel()
        self.rare_auto_label.setWordWrap(True)
        self.rare_auto_label.setStyleSheet("color:#374151; font-size: 12px;")
        self.rare_auto_label.hide()
        rare_box = QWidget()
        rare_lay = QVBoxLayout(rare_box)
        rare_lay.setContentsMargins(0, 0, 0, 0)
        rare_lay.setSpacing(4)
        rare_lay.addWidget(self.rare_combo)
        rare_lay.addWidget(self.rare_auto_label)
        self.image_edit = QLineEdit()
        self.image_edit.setPlaceholderText("可选：选择称号图片或 DDS（DDS 需为 BC3）")

        name_hint = QLabel(
            "称号名：请仅输入日语字库内可显示的字符，否则机台界面可能出现□。"
        )
        name_hint.setWordWrap(True)
        name_hint.setStyleSheet("color:#6B7280; font-size:11px;")
        name_box = QWidget()
        name_lay = QVBoxLayout(name_box)
        name_lay.setContentsMargins(0, 0, 0, 0)
        name_lay.setSpacing(4)
        name_lay.addWidget(wrap_name_input_with_preview(self.name_edit, parent=self))
        name_lay.addWidget(name_hint)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("Trophy ID", self.id_edit)
        form.addRow("显示名", name_box)
        form.addRow("说明", self.explain_edit)
        form.addRow("稀有度", rare_box)
        form.addRow(
            "图片",
            self._file_row(
                self.image_edit,
                "选择称号图片",
                dim_hint=(
                    "可选；若使用图片：参考分辨率 608 × 148 像素。"
                    "下方可留空，内容物请靠在整张图最上方排版。"
                    " 也可直接上传 DDS（必须 BC3/DXT5）。"
                ),
            ),
        )
        form.addRow("格式示例", self._example_row())

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
        warn = QLabel("提示：说明文字同样建议使用日语字库内可显示字符。")
        warn.setStyleSheet("color:#B45309;")
        layout.addWidget(warn)
        layout.addLayout(btns)

        self.image_edit.textChanged.connect(self._sync_rare_ui)
        self._sync_rare_ui()

    def _sync_rare_ui(self) -> None:
        has_img = bool(self.image_edit.text().strip())
        self.rare_combo.setVisible(not has_img)
        if has_img:
            r = next_trophy_rare_type_with_image(self._acus_root)
            self.rare_auto_label.setText(
                f"已选择图片：将自动写入 rareType = {r}（固定值）"
            )
            self.rare_auto_label.show()
        else:
            self.rare_auto_label.hide()

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

    def _example_row(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        img = QLabel("示例图")
        img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img.setStyleSheet("border: 1px solid #444;")
        sample = Path(__file__).resolve().parents[1] / "static" / "trophy" / "Custom_Example.png"
        if sample.exists():
            pm = QPixmap(str(sample))
            if not pm.isNull():
                img.setPixmap(pm.scaledToWidth(560, Qt.TransformationMode.SmoothTransformation))
                img.setText("")
        v.addWidget(img)
        tip = QLabel(
            "示例说明：上半部分是实际显示内容；下半部分黑白区域用于游戏内闪光遮罩。"
            "如果不需要闪光效果，下半部分可直接填纯黑。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#6B7280; font-size: 11px;")
        v.addWidget(tip)
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
            src_text = self.image_edit.text().strip()
            src = Path(src_text).expanduser() if src_text else None
            if src is not None:
                rare = next_trophy_rare_type_with_image(self._acus_root)
            else:
                rid = self.rare_combo.currentData()
                rare = int(rid) if rid is not None else 0

            tdir = self._acus_root / "trophy" / f"trophy{tid:06d}"
            tdir.mkdir(parents=True, exist_ok=True)
            dds_name = f"CHU_UI_Trophy_{tid:06d}.dds"
            image_path_xml = ""
            if src is not None:
                if not src.exists():
                    raise ValueError("称号图片路径不存在")
                dds_path = tdir / dds_name
                ingest_to_bc3_dds(tool_path=self._tool, input_path=src, output_dds=dds_path)
                image_path_xml = dds_name

            # 与 A001 一致：有图时为同目录下 CHU_UI_Trophy_XXXXXX.dds；无图时 <path /> 空元素
            if image_path_xml:
                image_xml = f"<image><path>{image_path_xml}</path></image>"
            else:
                image_xml = "<image><path /></image>"
            name_x = _xml_text(name)
            explain_x = _xml_text(explain)

            xml = f"""<?xml version="1.0" encoding="utf-8"?>
<TrophyData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>trophy{tid:06d}</dataName>
  <netOpenName><id>2801</id><str>v2_45 00_1</str><data /></netOpenName>
  <disableFlag>false</disableFlag>
  <name><id>{tid}</id><str>{name_x}</str><data /></name>
  <explainText>{explain_x}</explainText>
  <defaultHave>false</defaultHave>
  <rareType>{rare}</rareType>
  {image_xml}
  {_NORM_CONDITION_EMPTY_TEMPLATE}
  <priority>0</priority>
</TrophyData>
"""
            (tdir / "Trophy.xml").write_text(xml, encoding="utf-8")

            QMessageBox.information(
                self, "完成", f"已生成 trophy{tid:06d}（rareType={rare}）"
            )
            self.accept()
        except DdsToolError as e:
            QMessageBox.critical(self, "DDS 转换失败", str(e))
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

