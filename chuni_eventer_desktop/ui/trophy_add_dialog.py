from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox as FluentComboBox,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    isDarkTheme,
)

from ..dds_convert import DdsToolError, ingest_to_bc3_dds
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical, fly_message
from .name_glyph_preview import wrap_name_input_with_preview
from .trophy_pjsk_generator_dialog import TrophyPjskGeneratorDialog
from .trophy_texture_compose_dialog import TrophyTextureComposeDialog


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


def suggest_next_trophy_id(acus_root: Path, *, start: int = 50_000) -> int:
    used: set[int] = set()
    for p in acus_root.glob("trophy/**/Trophy.xml"):
        try:
            root = ET.parse(p).getroot()
            tid = _safe_int(root.findtext("name/id") or "")
            if tid is not None and tid >= 0:
                used.add(tid)
        except Exception:
            continue
    out = max(0, int(start))
    while out in used:
        out += 1
    return out


class TrophyAddDialog(FluentCaptionDialog):
    def __init__(self, *, acus_root: Path, tool_path: Path | None, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("新增称号 (Trophy)")
        self.setModal(True)
        self.resize(620, 920)
        self._acus_root = acus_root
        self._tool = tool_path

        self.id_edit = LineEdit(self)
        self.id_edit.setPlaceholderText("例如 9760")
        self.id_edit.setText(str(suggest_next_trophy_id(acus_root, start=50_000)))
        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText("例如 曲名（请仅用日语字库内字符）")
        self.name_edit.setToolTip(
            "称号显示名请仅使用游戏日语字库内已有的字符；"
            "生僻汉字或部分符号在游戏内可能显示为□（豆腐块）。"
        )
        self.explain_edit = LineEdit(self)
        self.explain_edit.setPlaceholderText("可不填，默认 -")
        self.rare_combo = FluentComboBox(self)
        for val, label in TROPHY_PRESET_RARE:
            self.rare_combo.addItem(f"{val} — {label}", None, val)
        self.rare_auto_label = BodyLabel(self)
        self.rare_auto_label.setWordWrap(True)
        self.rare_auto_label.setTextColor("#6B7280", "#9CA3AF")
        self.rare_auto_label.hide()
        rare_box = QWidget(self)
        rare_lay = QVBoxLayout(rare_box)
        rare_lay.setContentsMargins(0, 0, 0, 0)
        rare_lay.setSpacing(4)
        rare_lay.addWidget(self.rare_combo)
        rare_lay.addWidget(self.rare_auto_label)
        self.image_edit = LineEdit(self)
        self.image_edit.setPlaceholderText("可选：选择称号图片或 DDS（DDS 需为 BC3）")

        name_hint = BodyLabel(self)
        name_hint.setWordWrap(True)
        name_hint.setText("称号名：请仅输入日语字库内可显示的字符，否则机台界面可能出现□。")
        name_hint.setTextColor("#6B7280", "#9CA3AF")
        name_box = QWidget(self)
        name_lay = QVBoxLayout(name_box)
        name_lay.setContentsMargins(0, 0, 0, 0)
        name_lay.setSpacing(4)
        name_lay.addWidget(wrap_name_input_with_preview(self.name_edit, parent=self))
        name_lay.addWidget(name_hint)

        base_card = CardWidget(self)
        base_lay = QVBoxLayout(base_card)
        base_lay.setContentsMargins(16, 14, 16, 14)
        base_lay.setSpacing(10)
        base_lay.addWidget(BodyLabel("基本信息", self))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("Trophy ID", self.id_edit)
        form.addRow("显示名", name_box)
        form.addRow("说明", self.explain_edit)
        form.addRow("稀有度", rare_box)
        base_lay.addLayout(form)

        img_card = CardWidget(self)
        img_lay = QVBoxLayout(img_card)
        img_lay.setContentsMargins(16, 14, 16, 14)
        img_lay.setSpacing(8)
        img_lay.addWidget(BodyLabel("图片（可选）", self))
        img_lay.addWidget(
            self._file_row(
                self.image_edit,
                "选择称号图片",
                dim_hint=(
                    "可选；若使用图片：参考分辨率 608 × 148 像素。"
                    "下方可留空，内容物请靠在整张图最上方排版。"
                    " 也可直接上传 DDS（必须 BC3/DXT5）。"
                ),
            )
        )
        editor_btn = PushButton("称号贴图编辑器（608×148 / 608×80）…", self)
        editor_btn.setToolTip(
            "上传 608×148 或 608×80 的位图；若为 80 高会自动向下扩展透明区并叠加工具模板 trophy.png。"
        )
        editor_btn.clicked.connect(self._open_trophy_texture_editor)
        img_lay.addWidget(editor_btn)
        pjsk_btn = PushButton("PJSK 自助生成称号贴图…", self)
        pjsk_btn.setToolTip("选择 PJSK Trophy 底板与 line，输入文字后自动生成 608×148 PNG 并填入。")
        pjsk_btn.clicked.connect(self._open_pjsk_trophy_generator)
        img_lay.addWidget(pjsk_btn)

        ex_card = CardWidget(self)
        ex_lay = QVBoxLayout(ex_card)
        ex_lay.setContentsMargins(16, 14, 16, 14)
        ex_lay.setSpacing(8)
        ex_lay.addWidget(BodyLabel("格式示例", self))
        ex_lay.addWidget(self._example_row())

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
        layout.addWidget(base_card)
        layout.addWidget(img_card)
        layout.addWidget(ex_card)
        warn = BodyLabel(self)
        warn.setWordWrap(True)
        warn.setText("提示：说明文字同样建议使用日语字库内可显示字符。")
        warn.setStyleSheet("color:#B45309; font-size:12px;")
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

    def _example_row(self) -> QWidget:
        w = QWidget(self)
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        img = QLabel(self)
        img.setText("示例图")
        img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bcol = "#525252" if isDarkTheme() else "#D1D5DB"
        img.setStyleSheet(f"border: 1px solid {bcol};")
        sample = Path(__file__).resolve().parents[1] / "static" / "trophy" / "Custom_Example.png"
        if sample.exists():
            pm = QPixmap(str(sample))
            if not pm.isNull():
                img.setPixmap(pm.scaledToWidth(560, Qt.TransformationMode.SmoothTransformation))
                img.setText("")
        v.addWidget(img)
        tip = BodyLabel(self)
        tip.setWordWrap(True)
        tip.setText(
            "示例说明：上半部分是实际显示内容；下半部分黑白区域用于游戏内闪光遮罩。"
            "如果不需要闪光效果，下半部分可直接填纯黑。"
        )
        tip.setTextColor("#6B7280", "#9CA3AF")
        v.addWidget(tip)
        return w

    def _pick_into(self, edit: QLineEdit, title: str) -> None:
        p, _ = QFileDialog.getOpenFileName(self, title)
        if p:
            edit.setText(p)

    def _open_trophy_texture_editor(self) -> None:
        out_dir = self._acus_root / "_generated" / "trophy_compose_png"
        parent_win = self.window()
        aw = QApplication.activeWindow()
        print(
            f"[trophy-debug] open texture editor ts={time.time():.3f} "
            f"self_visible={self.isVisible()} self_enabled={self.isEnabled()} "
            f"parent={type(parent_win).__name__ if parent_win is not None else None} "
            f"active={type(aw).__name__ if aw is not None else None}"
        )
        dlg = TrophyTextureComposeDialog(out_dir=out_dir, parent=parent_win)
        print(
            f"[trophy-debug] texture dlg created ts={time.time():.3f} "
            f"visible={dlg.isVisible()} modal={dlg.isModal()} "
            f"modality={int(dlg.windowModality())} "
            f"parent={type(dlg.parentWidget()).__name__ if dlg.parentWidget() is not None else None}"
        )
        code = dlg.exec()
        print(f"[trophy-debug] texture dlg finished ts={time.time():.3f} code={code}")
        try:
            dlg.setWindowModality(Qt.WindowModality.NonModal)
            dlg.hide()
        except Exception:
            pass
        dlg.deleteLater()
        QApplication.processEvents()
        try:
            self.setEnabled(True)
            self.raise_()
            self.activateWindow()
        except Exception:
            pass
        if code != QDialog.DialogCode.Accepted:
            return
        if dlg.result_png_path is not None:
            self.image_edit.setText(str(dlg.result_png_path))
            self._sync_rare_ui()

    def _open_pjsk_trophy_generator(self) -> None:
        out_dir = self._acus_root / "_generated" / "trophy_compose_png"
        parent_win = self.window()
        aw = QApplication.activeWindow()
        print(
            f"[trophy-debug] open pjsk generator ts={time.time():.3f} "
            f"self_visible={self.isVisible()} self_enabled={self.isEnabled()} "
            f"parent={type(parent_win).__name__ if parent_win is not None else None} "
            f"active={type(aw).__name__ if aw is not None else None}"
        )
        try:
            dlg = TrophyPjskGeneratorDialog(out_dir=out_dir, parent=parent_win)
        except Exception as e:
            print(f"[trophy-debug] pjsk dlg create failed ts={time.time():.3f} err={e}")
            fly_critical(self, "资源加载失败", str(e))
            return
        print(
            f"[trophy-debug] pjsk dlg created ts={time.time():.3f} "
            f"visible={dlg.isVisible()} modal={dlg.isModal()} "
            f"modality={dlg.windowModality()} "
            f"parent={type(dlg.parentWidget()).__name__ if dlg.parentWidget() is not None else None}"
        )
        code = dlg.exec()
        print(f"[trophy-debug] pjsk dlg finished ts={time.time():.3f} code={code}")
        try:
            dlg.setWindowModality(Qt.WindowModality.NonModal)
            dlg.hide()
        except Exception:
            pass
        dlg.deleteLater()
        QApplication.processEvents()
        try:
            self.setEnabled(True)
            self.raise_()
            self.activateWindow()
        except Exception:
            pass
        if code != QDialog.DialogCode.Accepted:
            return
        if dlg.result_png_path is not None:
            self.image_edit.setText(str(dlg.result_png_path))
            self._sync_rare_ui()

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

            self.accept()
        except DdsToolError as e:
            fly_critical(self, "DDS 转换失败", str(e))
        except Exception as e:
            fly_critical(self, "错误", str(e))
