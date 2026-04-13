from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    CheckBox,
    ComboBox as FluentComboBox,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SpinBox,
)

from ..acus_scan import CharaItem
from ..game_data_index import GameDataIndex, merged_chara_items
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical
from .map_add_dialog import RewardRef, load_chara_refs, load_nameplate_refs, load_trophy_refs
from .name_glyph_preview import wrap_name_input_with_preview


def _safe_int(text: str) -> int | None:
    try:
        return int(text.strip())
    except Exception:
        return None


def _xml_text(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def next_custom_quest_id(acus_root: Path, *, start: int = 80000) -> int:
    used: set[int] = set()
    quest_root = acus_root / "quest"
    if quest_root.exists():
        for p in quest_root.glob("quest*"):
            if not p.is_dir():
                continue
            suf = p.name[5:]
            if suf.isdigit():
                used.add(int(suf))
        sort_path = quest_root / "QuestSort.xml"
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


def append_quest_sort(acus_root: Path, quest_id: int) -> None:
    sort_path = acus_root / "quest" / "QuestSort.xml"
    if not sort_path.exists():
        sort_path.parent.mkdir(parents=True, exist_ok=True)
        sort_path.write_text(
            """<?xml version="1.0" encoding="utf-8"?>
<SerializeSortData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>quest</dataName>
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
        if _safe_int((n.text or "").strip()) == quest_id:
            ET.indent(root)  # type: ignore[attr-defined]
            ET.ElementTree(root).write(sort_path, encoding="utf-8", xml_declaration=True)
            return
    s = ET.SubElement(sl, "StringID")
    ET.SubElement(s, "id").text = str(quest_id)
    ET.SubElement(s, "str")
    ET.SubElement(s, "data")
    ET.indent(root)  # type: ignore[attr-defined]
    ET.ElementTree(root).write(sort_path, encoding="utf-8", xml_declaration=True)


@dataclass
class _TierRow:
    sum_rank: SpinBox
    kind: FluentComboBox
    pick: FluentComboBox


def _reward_string_id(kind: str, inner_id: int) -> int:
    """与 A001 任务一致：称号 70xxxxxxx，名牌 30xxxxxxx，角色形象 50xxxxxxx。"""
    if kind == "trophy":
        return 70_000_000 + inner_id
    if kind == "nameplate":
        return 30_000_000 + inner_id
    if kind == "chara":
        return 50_000_000 + inner_id
    raise ValueError(kind)


def _fill_ref_combo(cb: FluentComboBox, refs: list[RewardRef]) -> None:
    cb.clear()
    for r in refs:
        label = r.display_name or r.name
        cb.addItem(f"{r.id} · {label}", None, (r.id, r.name))


class QuestAddDialog(FluentCaptionDialog):
    """新建任务（Quest.xml）：多角色合计等级（sumRank）达成后发放称号/名牌/角色形象。"""

    def __init__(
        self,
        *,
        acus_root: Path,
        game_index: GameDataIndex | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("新建任务")
        self.setModal(True)
        self.resize(720, 780)
        self._acus_root = acus_root

        qid = next_custom_quest_id(acus_root)
        self._id_edit = LineEdit(self)
        self._id_edit.setText(str(qid))
        self._name_edit = LineEdit(self)
        self._name_edit.setPlaceholderText("任务显示名（写入 name/str）")
        self._hide_info = CheckBox("隐藏详情（hideInfo，与部分官方任务一致）", self)

        self._chara_list = QListWidget(self)
        self._chara_list.setMinimumHeight(180)
        charas = merged_chara_items(acus_root, game_index)
        for c in charas:
            it = QListWidgetItem(f"{c.name.id} · {c.name.str}")
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked)
            it.setData(Qt.ItemDataRole.UserRole, c)
            self._chara_list.addItem(it)

        self._trophy_refs = load_trophy_refs(acus_root, game_index)
        self._np_refs = load_nameplate_refs(acus_root, game_index)
        self._chara_refs = load_chara_refs(acus_root, game_index)

        self._tier_box = QVBoxLayout()
        self._tier_box.setSpacing(8)
        self._tier_rows: list[_TierRow] = []
        add_tier_btn = PushButton("添加奖励阶段", self)
        add_tier_btn.clicked.connect(self._add_tier_row)
        rem_tier_btn = PushButton("移除最后一阶段", self)
        rem_tier_btn.clicked.connect(self._remove_last_tier)
        tb = QHBoxLayout()
        tb.setSpacing(8)
        tb.addWidget(add_tier_btn)
        tb.addWidget(rem_tier_btn)
        tb.addStretch(1)

        info_card = CardWidget(self)
        info_lay = QVBoxLayout(info_card)
        info_lay.setContentsMargins(16, 14, 16, 14)
        info_lay.setSpacing(10)
        info_lay.addWidget(BodyLabel("任务信息", self))
        hint = BodyLabel(self)
        hint.setWordWrap(True)
        hint.setText(
            "统计角色勾选「Chara.xml」中的 name/id；与官方任务里一长串剧情用 ID 不同，"
            "若你使用的数据包要求其它 ID，生成后可手改 Quest.xml。\n"
            "奖励 ID：称号 70000000+称号ID；名牌 30000000+名牌ID；角色 50000000+角色/形象ID。"
        )
        hint.setTextColor("#6B7280", "#9CA3AF")
        info_lay.addWidget(hint)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("任务 ID", self._id_edit)
        form.addRow("显示名", wrap_name_input_with_preview(self._name_edit, parent=self))
        form.addRow("", self._hide_info)
        info_lay.addLayout(form)

        chara_card = CardWidget(self)
        chara_lay = QVBoxLayout(chara_card)
        chara_lay.setContentsMargins(16, 14, 16, 14)
        chara_lay.setSpacing(8)
        chara_lay.addWidget(BodyLabel("参与合计等级的角色（多选）", self))
        chara_lay.addWidget(self._chara_list)

        tier_card = CardWidget(self)
        tier_lay = QVBoxLayout(tier_card)
        tier_lay.setContentsMargins(16, 14, 16, 14)
        tier_lay.setSpacing(10)
        tier_lay.addWidget(BodyLabel("奖励阶段（每行：合计等级阈值 + 奖励类型）", self))
        tier_lay.addLayout(self._tier_box)
        tier_lay.addLayout(tb)

        ok = PrimaryPushButton("生成并写入 ACUS", self)
        ok.clicked.connect(self._run)
        cancel = PushButton("取消", self)
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

        root_lay = QVBoxLayout(self)
        root_lay.setContentsMargins(*fluent_caption_content_margins())
        root_lay.setSpacing(12)
        root_lay.addWidget(info_card)
        root_lay.addWidget(chara_card)
        root_lay.addWidget(tier_card, stretch=1)
        root_lay.addLayout(btns)

        self._add_tier_row()

    def _add_tier_row(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(8)
        sp = SpinBox(self)
        sp.setRange(1, 99999)
        sp.setValue(100 if not self._tier_rows else 50 * (len(self._tier_rows) + 1))
        k = FluentComboBox(self)
        k.addItem("称号", None, "trophy")
        k.addItem("名牌", None, "nameplate")
        k.addItem("角色形象", None, "chara")
        pick = FluentComboBox(self)
        pick.setMinimumWidth(280)
        tr = _TierRow(sum_rank=sp, kind=k, pick=pick)

        def refill() -> None:
            kind = k.currentData()
            if kind == "trophy":
                _fill_ref_combo(pick, self._trophy_refs)
            elif kind == "nameplate":
                _fill_ref_combo(pick, self._np_refs)
            else:
                _fill_ref_combo(pick, self._chara_refs)

        k.currentIndexChanged.connect(lambda _i: refill())
        refill()

        row.addWidget(BodyLabel("合计等级 ≥", self))
        row.addWidget(sp)
        row.addWidget(k)
        row.addWidget(pick, stretch=1)
        w = QWidget(self)
        w.setLayout(row)
        self._tier_box.addWidget(w)
        self._tier_rows.append(tr)

    def _remove_last_tier(self) -> None:
        if len(self._tier_rows) <= 1:
            return
        self._tier_rows.pop()
        idx = self._tier_box.count() - 1
        item = self._tier_box.takeAt(idx)
        if item.widget() is not None:
            item.widget().deleteLater()

    def _run(self) -> None:
        try:
            qid = _safe_int(self._id_edit.text())
            if qid is None:
                qid = next_custom_quest_id(self._acus_root)
            if qid < 0:
                raise ValueError("任务 ID 必须为非负整数")
            title = self._name_edit.text().strip() or f"自定义任务{qid}"
            title_x = _xml_text(title)

            picked_charas: list[CharaItem] = []
            for i in range(self._chara_list.count()):
                it = self._chara_list.item(i)
                if it is None or it.checkState() != Qt.CheckState.Checked:
                    continue
                c = it.data(Qt.ItemDataRole.UserRole)
                if isinstance(c, CharaItem):
                    picked_charas.append(c)
            if not picked_charas:
                raise ValueError("请至少勾选一名角色")

            tier_blocks: list[str] = []
            for tr in self._tier_rows:
                sr = tr.sum_rank.value()
                kind = tr.kind.currentData()
                if not isinstance(kind, str):
                    raise ValueError("奖励类型无效")
                data = tr.pick.currentData()
                if data is None:
                    raise ValueError("每个阶段都要选择一项奖励")
                inner_id, inner_str = data
                if not isinstance(inner_id, int):
                    raise ValueError("奖励目标 ID 无效")
                inner_str = _xml_text((inner_str or "").strip() or f"id{inner_id}")
                rid = _reward_string_id(kind, inner_id)

                if kind == "trophy":
                    trophy_xml = f"""      <keyTrophyName>
        <id>{inner_id}</id>
        <str>{inner_str}</str>
        <data />
      </keyTrophyName>
      <keyNamePlateName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </keyNamePlateName>
      <keyCharaName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </keyCharaName>"""
                elif kind == "nameplate":
                    trophy_xml = f"""      <keyTrophyName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </keyTrophyName>
      <keyNamePlateName>
        <id>{inner_id}</id>
        <str>{inner_str}</str>
        <data />
      </keyNamePlateName>
      <keyCharaName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </keyCharaName>"""
                else:
                    trophy_xml = f"""      <keyTrophyName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </keyTrophyName>
      <keyNamePlateName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </keyNamePlateName>
      <keyCharaName>
        <id>{inner_id}</id>
        <str>{inner_str}</str>
        <data />
      </keyCharaName>"""

                tier_blocks.append(
                    f"""    <QuestRewardDataInfo>
      <sumRank>{sr}</sumRank>
{trophy_xml}
      <rewardName>
        <list>
          <StringID>
            <id>{rid}</id>
            <str>{inner_str}</str>
            <data />
          </StringID>
        </list>
      </rewardName>
    </QuestRewardDataInfo>"""
                )

            chara_lines = []
            for c in picked_charas:
                sid = _xml_text(c.name.str or "")
                chara_lines.append(
                    f"""      <StringID>
        <id>{c.name.id}</id>
        <str>{sid}</str>
        <data />
      </StringID>"""
                )
            charas_body = "\n".join(chara_lines)

            hide = "true" if self._hide_info.isChecked() else "false"
            info_body = "\n".join(tier_blocks)

            xml = f"""<?xml version="1.0" encoding="utf-8"?>
<QuestData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>quest{qid:08d}</dataName>
  <netOpenName>
    <id>2801</id>
    <str>v2_45 00_1</str>
    <data />
  </netOpenName>
  <disableFlag>false</disableFlag>
  <name>
    <id>{qid}</id>
    <str>{title_x}</str>
    <data />
  </name>
  <charaWorks>
    <list />
  </charaWorks>
  <charas>
    <list>
{charas_body}
    </list>
  </charas>
  <hideInfo>{hide}</hideInfo>
  <priority>0</priority>
  <info>
{info_body}
  </info>
</QuestData>
"""
            qdir = self._acus_root / "quest" / f"quest{qid:08d}"
            qdir.mkdir(parents=True, exist_ok=True)
            out = qdir / "Quest.xml"
            out.write_text(xml, encoding="utf-8")
            append_quest_sort(self._acus_root, qid)
        except Exception as e:
            fly_critical(self, "生成失败", str(e))
            return
        self.accept()
