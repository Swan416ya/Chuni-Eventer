from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QGroupBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


def _safe_int(text: str) -> int | None:
    try:
        return int(text.strip())
    except Exception:
        return None


@dataclass
class RewardRef:
    id: int
    name: str
    display_name: str = ""


@dataclass
class MusicRef:
    id: int
    name: str


@dataclass
class CellData:
    reward_id: int | None = None
    reward_name: str = ""
    reward_kind: str = "外部奖励ID"
    reward_inner_id: int | None = None
    music_id: int | None = None
    music_name: str = ""
    # MapAreaGridData 元数据（从官方 XML 读入，保存编辑模式时尽量写回）
    display_type: int | None = None
    cell_type: int | None = None


@dataclass
class MapAreaExtras:
    """从已有 MapArea.xml 读入，保存时写回（mapBonus、缩短格次数等）。"""

    bonus_id: int
    bonus_str: str
    shorten_counts: tuple[int, ...]  # 8


@dataclass
class MapInfoMeta:
    """Map.xml infos/MapDataAreaInfo 的页面与展示元数据。"""

    dds_id: int = 0
    dds_str: str = "共通0001_CHUNITHM"
    page_index: int = 0
    index_in_page: int = 0
    required_achievement_count: int = 0
    gauge_id: int = 34
    gauge_str: str = "基本セット34"
    is_hard: bool = False


def _default_map_area_extras() -> MapAreaExtras:
    return MapAreaExtras(-1, "Invalid", (0,) * 8)


def _kind_label(kind: str) -> str:
    return {
        "外部奖励ID": "外部",
        "角色": "角色",
        "称号(Trophy)": "称号",
        "姓名牌装饰(NamePlate)": "姓名牌",
        "功能票(Ticket)": "功能票",
        "乐曲解锁(Music)": "乐曲",
        "地图图标(MapIcon)": "地图图标",
        "头像配件(AvatarAccessory)": "头像配件",
        "场景(Stage)": "场景",
    }.get(kind, kind)


def _parse_grid_int(el: ET.Element | None, tag: str, default: int) -> int:
    if el is None:
        return default
    t = (el.findtext(tag) or "").strip()
    return int(t) if t.isdigit() else default


def resolve_reward_xml(acus_root: Path, rid: int) -> Path | None:
    """
    定位 Reward.xml。优先 reward{9位零填充}；否则在 reward/*/Reward.xml 里按 name/id 匹配。
    """
    if rid < 0:
        return None
    p9 = acus_root / "reward" / f"reward{rid:09d}" / "Reward.xml"
    if p9.exists():
        return p9
    alt = acus_root / "reward" / f"reward{rid}" / "Reward.xml"
    if alt.exists():
        return alt
    reward_root = acus_root / "reward"
    if not reward_root.is_dir():
        return None
    try:
        for folder in reward_root.iterdir():
            if not folder.is_dir():
                continue
            rx = folder / "Reward.xml"
            if not rx.exists():
                continue
            try:
                rr = ET.parse(rx).getroot()
                nid = _safe_int(rr.findtext("name/id") or "")
                if nid == rid:
                    return rx
            except Exception:
                continue
    except OSError:
        pass
    return None


def enrich_cell_from_reward_xml(acus_root: Path, cell: CellData) -> None:
    """根据 reward XML 补全 reward_kind / inner_id / 课题曲。"""
    rid = cell.reward_id
    if rid is None or rid < 0:
        return
    p = resolve_reward_xml(acus_root, rid)
    if p is None:
        cell.reward_kind = "外部奖励ID"
        return
    try:
        r = ET.parse(p).getroot()
        # 可能有多个 RewardSubstanceData，优先能解析出类型/乐曲的那条
        subs = r.findall(".//RewardSubstanceData")
        if not subs:
            return
        chosen = subs[0]
        best_score = -1
        for sub in subs:
            t_raw = (sub.findtext("type") or "0").strip()
            t = int(t_raw) if t_raw.isdigit() else 0
            mid = _safe_int(sub.findtext("music/musicName/id") or "")
            score = 0
            if t in (2, 3, 5):
                score += 4
            if mid is not None and mid != -1:
                score += 2
            if score > best_score:
                best_score = score
                chosen = sub
        sub = chosen
        t_raw = (sub.findtext("type") or "0").strip()
        t = int(t_raw) if t_raw.isdigit() else 0
        mid = _safe_int(sub.findtext("music/musicName/id") or "")
        mstr = (sub.findtext("music/musicName/str") or "").strip()
        if mid is not None and mid != -1:
            cell.music_id = mid
            cell.music_name = mstr or f"Music{mid}"
        if t == 1:
            cell.reward_kind = "功能票(Ticket)"
            cell.reward_inner_id = _safe_int(sub.findtext("ticket/ticketName/id") or "")
        elif t == 2:
            cell.reward_kind = "称号(Trophy)"
            cell.reward_inner_id = _safe_int(sub.findtext("trophy/trophyName/id") or "")
        elif t == 3:
            cell.reward_kind = "角色"
            cell.reward_inner_id = _safe_int(sub.findtext("chara/charaName/id") or "")
        elif t == 5:
            cell.reward_kind = "姓名牌装饰(NamePlate)"
            cell.reward_inner_id = _safe_int(sub.findtext("namePlate/namePlateName/id") or "")
        elif t == 6:
            cell.reward_kind = "乐曲解锁(Music)"
            cell.reward_inner_id = _safe_int(sub.findtext("music/musicName/id") or "")
        elif t == 7:
            cell.reward_kind = "地图图标(MapIcon)"
            cell.reward_inner_id = _safe_int(sub.findtext("mapIcon/mapIconName/id") or "")
        elif t == 9:
            cell.reward_kind = "头像配件(AvatarAccessory)"
            cell.reward_inner_id = _safe_int(sub.findtext("avatarAccessory/avatarAccessoryName/id") or "")
        elif t == 13:
            cell.reward_kind = "场景(Stage)"
            cell.reward_inner_id = _safe_int(sub.findtext("stage/stageName/id") or "")
        else:
            cell.reward_kind = "外部奖励ID"
            cell.reward_inner_id = None
    except Exception:
        pass


def parse_maparea_file(
    acus_root: Path, area_xml: Path
) -> tuple[list[CellData], MapAreaExtras, list[int | None], bool]:
    """
    解析 MapArea 九宫格。

    官方 MapAreaGridData 的 index 往往不是 0..8（如 205、405），不能按 index 当数组下标。
    这里按 index 数值排序后，依次填入 UI 的 9 个格子；并返回每格对应的游戏 index（无格则为 None）。

    若文件中超过 9 个格子，只取排序后的前 9 个，truncated=True。
    """
    r = ET.parse(area_xml).getroot()
    grids_el = r.find("grids")
    grid_nodes: list[ET.Element] = []
    if grids_el is not None:
        grid_nodes = list(grids_el.findall("MapAreaGridData"))

    rows: list[tuple[int, CellData]] = []
    for gd in grid_nodes:
        try:
            gix = int((gd.findtext("index") or "").strip())
        except ValueError:
            continue
        dt = _parse_grid_int(gd, "displayType", 1)
        ct = _parse_grid_int(gd, "type", 1)
        rid = _safe_int(gd.findtext("reward/rewardName/id") or "")
        rstr = (gd.findtext("reward/rewardName/str") or "").strip()
        if rid is None or rid < 0:
            c = CellData(display_type=dt, cell_type=ct)
        else:
            c = CellData(
                reward_id=rid,
                reward_name=rstr or f"Reward{rid}",
                reward_kind="外部奖励ID",
                display_type=dt,
                cell_type=ct,
            )
            enrich_cell_from_reward_xml(acus_root, c)
        rows.append((gix, c))

    rows.sort(key=lambda x: x[0])
    # 官方 MapArea 往往有很多路径格；编辑器只显示 9 格时，优先放「有奖励」的格子
    # 避免简单截断前 9 个导致看起来全空。
    reward_rows = [x for x in rows if x[1].reward_id is not None and x[1].reward_id >= 0]
    empty_rows = [x for x in rows if not (x[1].reward_id is not None and x[1].reward_id >= 0)]
    selected_rows = reward_rows[:9]
    if len(selected_rows) < 9:
        selected_rows.extend(empty_rows[: 9 - len(selected_rows)])
    truncated = len(rows) > len(selected_rows)
    rows = selected_rows[:9]

    cells: list[CellData] = []
    grid_indices: list[int | None] = []
    for i in range(9):
        if i < len(rows):
            gix, c = rows[i]
            cells.append(c)
            grid_indices.append(gix)
        else:
            cells.append(CellData())
            grid_indices.append(None)

    counts: list[int] = []
    for el in r.findall("shorteningGridCountList/MapAreaGridShorteningData/count"):
        try:
            counts.append(int((el.text or "0").strip()))
        except ValueError:
            counts.append(0)
    while len(counts) < 8:
        counts.append(0)
    bid = _safe_int(r.findtext("mapBonusName/id") or "")
    bstr = (r.findtext("mapBonusName/str") or "").strip() or "Invalid"
    if bid is None:
        bid = -1
    extras = MapAreaExtras(bonus_id=bid, bonus_str=bstr, shorten_counts=tuple(counts[:8]))
    return cells, extras, grid_indices, truncated


class CellEditDialog(QDialog):
    def __init__(
        self,
        *,
        acus_root: Path,
        reward_refs: list[RewardRef],
        chara_refs: list[RewardRef],
        trophy_refs: list[RewardRef],
        nameplate_refs: list[RewardRef],
        music_refs: list[MusicRef],
        data: CellData,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("配置格子奖励")
        self.setModal(True)
        self._acus_root = acus_root
        self._reward_refs = reward_refs
        self._chara_refs = chara_refs
        self._trophy_refs = trophy_refs
        self._nameplate_refs = nameplate_refs
        self._music_refs = music_refs
        self._data = data

        self.reward_mode = QComboBox()
        self.reward_mode.addItems(["留空", "选择 ACUS 奖励", "角色", "称号(Trophy)", "姓名牌装饰(NamePlate)", "手填奖励ID"])
        self.reward_mode.currentTextChanged.connect(self._sync_state)

        self.reward_pick = QComboBox()
        self.reward_pick.addItem("(请选择)")
        for r in reward_refs:
            label = r.display_name or r.name
            self.reward_pick.addItem(f"{r.id} | {label}")

        self.reward_id = QLineEdit()
        self.reward_id.setPlaceholderText("例如 70099001")
        self.reward_name = QLineEdit()
        self.reward_name.setPlaceholderText("显示名（可不填）")

        self.reward_kind = QComboBox()
        self.reward_kind.addItems(["外部奖励ID", "角色", "称号(Trophy)", "姓名牌装饰(NamePlate)"])
        self.reward_inner_id = QLineEdit()
        self.reward_inner_id.setPlaceholderText("奖励内部ID")
        self.inner_pick = QComboBox()

        self.music_mode = QComboBox()
        self.music_mode.addItems(["不配置乐曲", "选择 ACUS 乐曲", "手填乐曲ID"])
        self.music_mode.currentTextChanged.connect(self._sync_state)
        self.music_pick = QComboBox()
        self.music_pick.addItem("(请选择)")
        for m in music_refs:
            self.music_pick.addItem(f"{m.id} | {m.name}")
        self.music_id = QLineEdit()
        self.music_id.setPlaceholderText("例如 7001")
        self.music_name = QLineEdit()
        self.music_name.setPlaceholderText("乐曲名（可不填）")

        self.warn_reward = QLabel("")
        self.warn_reward.setStyleSheet("color:#DC2626;")
        self.warn_music = QLabel("")
        self.warn_music.setStyleSheet("color:#DC2626;")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("奖励模式", self.reward_mode)
        form.addRow("ACUS奖励", self.reward_pick)
        form.addRow("奖励ID", self.reward_id)
        form.addRow("奖励显示名", self.reward_name)
        form.addRow("奖励类型", self.reward_kind)
        form.addRow("奖励内部ID", self.reward_inner_id)
        form.addRow("固定/ACUS项", self.inner_pick)
        form.addRow("", self.warn_reward)
        form.addRow(QLabel(""), QLabel(""))
        form.addRow("乐曲模式", self.music_mode)
        form.addRow("ACUS乐曲", self.music_pick)
        form.addRow("乐曲ID", self.music_id)
        form.addRow("乐曲名", self.music_name)
        form.addRow("", self.warn_music)

        ok = QPushButton("确定")
        ok.clicked.connect(self._on_ok)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)

        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(btns)

        self._load_from_data()
        self._sync_state()

    def _load_from_data(self) -> None:
        d = self._data
        if d.reward_id is None:
            self.reward_mode.setCurrentText("留空")
        else:
            idx = next((i for i, r in enumerate(self._reward_refs, start=1) if r.id == d.reward_id), -1)
            if idx > 0:
                self.reward_mode.setCurrentText("选择 ACUS 奖励")
                self.reward_pick.setCurrentIndex(idx)
            elif d.reward_kind in ("角色", "称号(Trophy)", "姓名牌装饰(NamePlate)") and d.reward_inner_id is not None:
                mode_map = {
                    "角色": "角色",
                    "称号(Trophy)": "称号(Trophy)",
                    "姓名牌装饰(NamePlate)": "姓名牌装饰(NamePlate)",
                }
                self.reward_mode.setCurrentText(mode_map.get(d.reward_kind, "手填奖励ID"))
                self.reward_name.setText(d.reward_name or "")
                self.reward_inner_id.setText(str(d.reward_inner_id))
            else:
                self.reward_mode.setCurrentText("手填奖励ID")
                self.reward_id.setText(str(d.reward_id))
                self.reward_name.setText(d.reward_name or "")
                self.reward_kind.setCurrentText(d.reward_kind or "外部奖励ID")
                if d.reward_inner_id is not None:
                    self.reward_inner_id.setText(str(d.reward_inner_id))

        if d.music_id is None:
            self.music_mode.setCurrentText("不配置乐曲")
        else:
            idx = next((i for i, m in enumerate(self._music_refs, start=1) if m.id == d.music_id), -1)
            if idx > 0:
                self.music_mode.setCurrentText("选择 ACUS 乐曲")
                self.music_pick.setCurrentIndex(idx)
            else:
                self.music_mode.setCurrentText("手填乐曲ID")
                self.music_id.setText(str(d.music_id))
                self.music_name.setText(d.music_name or "")

    def _sync_state(self) -> None:
        rm = self.reward_mode.currentText()
        self.reward_pick.setEnabled(rm == "选择 ACUS 奖励")
        manual = rm == "手填奖励ID"
        typed = rm in {"角色", "称号(Trophy)", "姓名牌装饰(NamePlate)"}
        self.reward_id.setEnabled(manual)
        self.reward_name.setEnabled(manual or typed)
        self.reward_kind.setEnabled(manual)
        self.reward_inner_id.setEnabled(manual or typed)
        self.inner_pick.setEnabled(typed)

        self.inner_pick.clear()
        self.inner_pick.addItem("(可不选)")
        if rm == "角色":
            for x in self._chara_refs:
                self.inner_pick.addItem(f"{x.id} | {x.name}")
        elif rm == "称号(Trophy)":
            for x in self._trophy_refs:
                self.inner_pick.addItem(f"{x.id} | {x.name}")
        elif rm == "姓名牌装饰(NamePlate)":
            for x in self._nameplate_refs:
                self.inner_pick.addItem(f"{x.id} | {x.name}")

        mm = self.music_mode.currentText()
        self.music_pick.setEnabled(mm == "选择 ACUS 乐曲")
        self.music_id.setEnabled(mm == "手填乐曲ID")
        self.music_name.setEnabled(mm == "手填乐曲ID")

        self.warn_reward.setText("⚠ 手填奖励/手填内部ID 若游戏内不存在，可能报错，请谨慎使用。" if rm in {"手填奖励ID", "角色", "称号(Trophy)", "姓名牌装饰(NamePlate)"} else "")
        self.warn_music.setText("⚠ 手填乐曲ID若游戏内不存在，可能报错，请谨慎使用。" if mm == "手填乐曲ID" else "")

    def _on_ok(self) -> None:
        preserve_dt = self._data.display_type
        preserve_ct = self._data.cell_type
        out = CellData()

        rm = self.reward_mode.currentText()
        if rm == "留空":
            out.reward_id = None
        elif rm == "选择 ACUS 奖励":
            idx = self.reward_pick.currentIndex()
            if idx <= 0:
                QMessageBox.critical(self, "错误", "请选择 ACUS 奖励")
                return
            ref = self._reward_refs[idx - 1]
            out.reward_id = ref.id
            out.reward_name = ref.name
            out.reward_kind = "外部奖励ID"
            enrich_cell_from_reward_xml(self._acus_root, out)
        elif rm == "手填奖励ID":
            rid = _safe_int(self.reward_id.text())
            if rid is None:
                QMessageBox.critical(self, "错误", "奖励ID 必须是整数")
                return
            out.reward_id = rid
            out.reward_name = self.reward_name.text().strip() or f"Reward{rid}"
            out.reward_kind = self.reward_kind.currentText()
            if out.reward_kind != "外部奖励ID":
                inner = _safe_int(self.reward_inner_id.text())
                if inner is None:
                    QMessageBox.critical(self, "错误", "该奖励类型需要填写“奖励内部ID”")
                    return
                out.reward_inner_id = inner
        else:
            if rm == "角色":
                out.reward_kind = "角色"
                out.reward_inner_id = self._resolve_inner_from_ui(self._chara_refs)
            elif rm == "称号(Trophy)":
                out.reward_kind = "称号(Trophy)"
                out.reward_inner_id = self._resolve_inner_from_ui(self._trophy_refs)
            else:
                out.reward_kind = "姓名牌装饰(NamePlate)"
                out.reward_inner_id = self._resolve_inner_from_ui(self._nameplate_refs)

            if out.reward_inner_id is None:
                QMessageBox.critical(self, "错误", "请填写或选择有效的奖励内部ID")
                return
            out.reward_name = self.reward_name.text().strip() or f"Reward{out.reward_inner_id}"
            out.reward_id = self._default_reward_id(out.reward_kind, out.reward_inner_id)

        mm = self.music_mode.currentText()
        if mm == "不配置乐曲":
            out.music_id = None
        elif mm == "选择 ACUS 乐曲":
            idx = self.music_pick.currentIndex()
            if idx <= 0:
                QMessageBox.critical(self, "错误", "请选择 ACUS 乐曲")
                return
            ref = self._music_refs[idx - 1]
            out.music_id = ref.id
            out.music_name = ref.name
        else:
            mid = _safe_int(self.music_id.text())
            if mid is None:
                QMessageBox.critical(self, "错误", "乐曲ID 必须是整数")
                return
            out.music_id = mid
            out.music_name = self.music_name.text().strip() or f"Music{mid}"

        self._data.reward_id = out.reward_id
        self._data.reward_name = out.reward_name
        self._data.reward_kind = out.reward_kind
        self._data.reward_inner_id = out.reward_inner_id
        self._data.music_id = out.music_id
        self._data.music_name = out.music_name
        # 保留从 MapArea 读入的 displayType / type，避免保存时丢失
        # (out 不含这两项，故从编辑前的 _data 保留)
        self._data.display_type = preserve_dt
        self._data.cell_type = preserve_ct
        self.accept()

    def _resolve_inner_from_ui(self, refs: list[RewardRef]) -> int | None:
        pick = self.inner_pick.currentIndex()
        if pick > 0 and pick - 1 < len(refs):
            return refs[pick - 1].id
        return _safe_int(self.reward_inner_id.text())

    def _default_reward_id(self, kind: str, inner_id: int) -> int:
        if kind == "角色":
            return 50_000_000 + inner_id
        if kind == "称号(Trophy)":
            return 70_000_000 + inner_id
        if kind == "姓名牌装饰(NamePlate)":
            return 30_000_000 + inner_id
        return inner_id


class AreaExtrasDialog(QDialog):
    def __init__(self, *, extras: MapAreaExtras, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("编辑区域参数(MapArea)")
        self.setModal(True)
        self._extras = extras

        self.bonus_id = QLineEdit(str(extras.bonus_id))
        self.bonus_str = QLineEdit(extras.bonus_str)
        self.counts = QLineEdit(",".join(str(x) for x in extras.shorten_counts[:8]))
        self.counts.setPlaceholderText("8个整数，用逗号分隔，例如 0,0,0,0,0,0,0,0")

        form = QFormLayout()
        form.addRow("mapBonusName.id", self.bonus_id)
        form.addRow("mapBonusName.str", self.bonus_str)
        form.addRow("shorteningGridCountList", self.counts)

        ok = QPushButton("确定")
        ok.clicked.connect(self._on_ok)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addLayout(btns)

    def _on_ok(self) -> None:
        bid = _safe_int(self.bonus_id.text())
        if bid is None:
            QMessageBox.critical(self, "错误", "mapBonusName.id 必须是整数")
            return
        bstr = self.bonus_str.text().strip() or "Invalid"
        raw = self.counts.text().strip()
        parts = [x.strip() for x in raw.split(",") if x.strip() != ""]
        if len(parts) != 8:
            QMessageBox.critical(self, "错误", "shorteningGridCountList 需要恰好8个整数")
            return
        vals: list[int] = []
        for p in parts:
            v = _safe_int(p)
            if v is None:
                QMessageBox.critical(self, "错误", f"shortening 里存在非整数：{p}")
                return
            vals.append(v)
        self._extras.bonus_id = bid
        self._extras.bonus_str = bstr
        self._extras.shorten_counts = tuple(vals)
        self.accept()


class AreaPageMetaDialog(QDialog):
    def __init__(self, *, meta: MapInfoMeta, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("编辑页面参数(Map.xml)")
        self.setModal(True)
        self._meta = meta

        self.page_index = QLineEdit(str(meta.page_index))
        self.index_in_page = QLineEdit(str(meta.index_in_page))
        self.required = QLineEdit(str(meta.required_achievement_count))
        self.gauge_id = QLineEdit(str(meta.gauge_id))
        self.gauge_str = QLineEdit(meta.gauge_str)
        self.dds_id = QLineEdit(str(meta.dds_id))
        self.dds_str = QLineEdit(meta.dds_str)
        self.is_hard = QCheckBox("isHard = true")
        self.is_hard.setChecked(meta.is_hard)

        form = QFormLayout()
        form.addRow("pageIndex", self.page_index)
        form.addRow("indexInPage", self.index_in_page)
        form.addRow("requiredAchievementCount", self.required)
        form.addRow("gaugeName.id", self.gauge_id)
        form.addRow("gaugeName.str", self.gauge_str)
        form.addRow("ddsMapName.id", self.dds_id)
        form.addRow("ddsMapName.str", self.dds_str)
        form.addRow("", self.is_hard)

        ok = QPushButton("确定")
        ok.clicked.connect(self._on_ok)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addLayout(btns)

    def _on_ok(self) -> None:
        page_index = _safe_int(self.page_index.text())
        slot = _safe_int(self.index_in_page.text())
        required = _safe_int(self.required.text())
        gauge_id = _safe_int(self.gauge_id.text())
        dds_id = _safe_int(self.dds_id.text())
        if page_index is None or page_index < 0:
            QMessageBox.critical(self, "错误", "pageIndex 必须为非负整数")
            return
        if slot is None or not (0 <= slot <= 8):
            QMessageBox.critical(self, "错误", "indexInPage 必须在 0~8")
            return
        if required is None or required < 0:
            QMessageBox.critical(self, "错误", "requiredAchievementCount 必须为非负整数")
            return
        if gauge_id is None:
            QMessageBox.critical(self, "错误", "gaugeName.id 必须是整数")
            return
        if dds_id is None:
            QMessageBox.critical(self, "错误", "ddsMapName.id 必须是整数")
            return
        self._meta.page_index = page_index
        self._meta.index_in_page = slot
        self._meta.required_achievement_count = required
        self._meta.gauge_id = gauge_id
        self._meta.gauge_str = self.gauge_str.text().strip() or "基本セット34"
        self._meta.dds_id = dds_id
        self._meta.dds_str = self.dds_str.text().strip() or "共通0001_CHUNITHM"
        self._meta.is_hard = self.is_hard.isChecked()
        self.accept()


class MapAreaProgressDialog(QDialog):
    def __init__(self, *, area_id: int, cells: list[CellData], grid_indices: list[int | None], parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle(f"编辑 MapArea 进度（{area_id}）")
        self.setModal(True)
        self._cells = cells
        self._grid_indices = grid_indices

        max_step = 0
        lines: list[str] = []
        for i, c in enumerate(cells):
            step = grid_indices[i] if i < len(grid_indices) and grid_indices[i] is not None else i
            max_step = max(max_step, step)
            if c.reward_id is not None and c.reward_id >= 0:
                lines.append(f"{step},{c.reward_id},{c.reward_name or f'Reward{c.reward_id}'}")

        self.total_steps = QLineEdit(str(max_step))
        self.reward_lines = QTextEdit()
        self.reward_lines.setPlaceholderText("每行一个奖励：步数,reward_id,reward_name")
        self.reward_lines.setPlainText("\n".join(lines))

        form = QFormLayout()
        form.addRow("总步数(最大 index)", self.total_steps)
        form.addRow("奖励列表", self.reward_lines)

        ok = QPushButton("确定")
        ok.clicked.connect(self._on_ok)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addLayout(btns)

    def _on_ok(self) -> None:
        t = _safe_int(self.total_steps.text())
        if t is None or t < 0:
            QMessageBox.critical(self, "错误", "总步数必须为非负整数")
            return
        reward_by_step: dict[int, tuple[int, str]] = {}
        raw = self.reward_lines.toPlainText().strip()
        if raw:
            for ln in raw.splitlines():
                s = ln.strip()
                if not s:
                    continue
                parts = [x.strip() for x in s.split(",")]
                if len(parts) < 2:
                    QMessageBox.critical(self, "错误", f"格式错误：{ln}")
                    return
                step = _safe_int(parts[0])
                rid = _safe_int(parts[1])
                if step is None or rid is None or step < 0:
                    QMessageBox.critical(self, "错误", f"步数/奖励ID 非法：{ln}")
                    return
                name = parts[2] if len(parts) >= 3 and parts[2] else f"Reward{rid}"
                reward_by_step[step] = (rid, name)

        # 以 9 个关键节点表示 MapArea 过程，index 覆盖 [0..总步数]
        points = sorted(set([0, t] + list(reward_by_step.keys())))
        points = points[:9]
        while len(points) < 9:
            points.append(points[-1] if points else 0)
        new_cells: list[CellData] = []
        new_idx: list[int | None] = []
        for p in points[:9]:
            if p in reward_by_step:
                rid, rname = reward_by_step[p]
                c = CellData(reward_id=rid, reward_name=rname)
            else:
                c = CellData()
            new_cells.append(c)
            new_idx.append(p)
        self._cells[:] = new_cells
        self._grid_indices[:] = new_idx
        self.accept()


class RewardCreateDialog(QDialog):
    def __init__(self, *, default_id: int, music_refs: list[MusicRef], parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("新建 Reward")
        self.setModal(True)
        self.result_cell: CellData | None = None

        self.reward_id = QLineEdit(str(default_id))
        self.reward_name = QLineEdit()
        self.reward_kind = QComboBox()
        self.reward_kind.addItems(
            [
                "功能票(Ticket)",
                "外部奖励ID",
                "角色",
                "称号(Trophy)",
                "姓名牌装饰(NamePlate)",
                "乐曲解锁(Music)",
            ]
        )
        self.inner_id = QLineEdit()
        self.has_music = QCheckBox("有课题曲")
        self.music_mode = QComboBox()
        self.music_mode.addItems(["选择 ACUS 乐曲", "手填乐曲ID"])
        self.music_pick = QComboBox()
        self.music_pick.addItem("(请选择)")
        for m in music_refs:
            self.music_pick.addItem(f"{m.id} | {m.name}")
        self.music_id = QLineEdit()
        self.music_name = QLineEdit()
        self.music_name.setPlaceholderText("留空则自动 Music{id}")
        self.has_music.toggled.connect(self._sync)
        self.music_mode.currentTextChanged.connect(self._sync)

        form = QFormLayout()
        form.addRow("reward.id", self.reward_id)
        form.addRow("reward.str", self.reward_name)
        form.addRow("类型", self.reward_kind)
        form.addRow("内部ID(可空)", self.inner_id)
        form.addRow("", self.has_music)
        form.addRow("课题曲模式", self.music_mode)
        form.addRow("ACUS乐曲", self.music_pick)
        form.addRow("乐曲ID", self.music_id)
        form.addRow("乐曲名", self.music_name)

        ok = QPushButton("创建")
        ok.clicked.connect(self._on_ok)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addLayout(btns)
        self._sync()

    def _sync(self) -> None:
        on = self.has_music.isChecked()
        self.music_mode.setEnabled(on)
        pick = on and self.music_mode.currentText() == "选择 ACUS 乐曲"
        self.music_pick.setEnabled(pick)
        self.music_id.setEnabled(on and not pick)
        self.music_name.setEnabled(on and not pick)

    def _on_ok(self) -> None:
        rid = _safe_int(self.reward_id.text())
        if rid is None or rid < 0 or str(rid)[0] != "7":
            QMessageBox.critical(self, "错误", "reward.id 必须是非负整数，且首位为 7")
            return
        name = self.reward_name.text().strip() or f"Reward{rid}"
        kind = self.reward_kind.currentText()
        inner = _safe_int(self.inner_id.text()) if self.inner_id.text().strip() else None
        c = CellData(reward_id=rid, reward_name=name, reward_kind=kind, reward_inner_id=inner)
        if self.has_music.isChecked():
            if self.music_mode.currentText() == "选择 ACUS 乐曲":
                idx = self.music_pick.currentIndex()
                if idx <= 0:
                    QMessageBox.critical(self, "错误", "请选择 ACUS 乐曲")
                    return
                text = self.music_pick.currentText().split("|", 1)
                c.music_id = _safe_int(text[0].strip())
                c.music_name = text[1].strip() if len(text) > 1 else ""
            else:
                mid = _safe_int(self.music_id.text())
                if mid is None:
                    QMessageBox.critical(self, "错误", "乐曲ID 必须是整数")
                    return
                c.music_id = mid
                c.music_name = self.music_name.text().strip() or f"Music{mid}"
        self.result_cell = c
        self.accept()


class MapAddDialog(QDialog):
    def __init__(self, *, acus_root: Path, parent=None, edit_map_xml: Path | None = None) -> None:
        super().__init__(parent=parent)
        self._edit_mode = edit_map_xml is not None
        self.setWindowTitle("编辑地图" if self._edit_mode else "新增地图")
        self.setModal(True)
        self.resize(980, 700)
        self._acus_root = acus_root
        self._reward_refs = self._load_reward_refs()
        self._chara_refs = self._load_chara_refs()
        self._trophy_refs = self._load_trophy_refs()
        self._nameplate_refs = self._load_nameplate_refs()
        self._music_refs = self._load_music_refs()
        self._chara_name_by_id = {x.id: x.name for x in self._chara_refs}
        self._trophy_name_by_id = {x.id: x.name for x in self._trophy_refs}
        self._nameplate_name_by_id = {x.id: x.name for x in self._nameplate_refs}
        self._music_name_by_id = {x.id: x.name for x in self._music_refs}
        self._area_cells: list[list[CellData]] = []
        self._area_ids: list[int] = []
        self._area_names: list[str] = []
        self._area_extras: list[MapAreaExtras] = []
        # Map.xml infos 层：每页显示的奖励/乐曲（不是跑图节点）
        self._area_info_cells: list[CellData] = []
        self._area_info_meta: list[MapInfoMeta] = []
        # 编辑模式：每格对应 MapArea.xml 里的游戏 index（非 0..8）；与 _area_cells 对齐
        self._area_grid_indices: list[list[int | None]] = []
        self._page_area_slots: list[list[int | None]] = []
        self._current_map_id = 0

        self.map_id = QLineEdit()
        self.map_id.setPlaceholderText("例如 99000001（8位推荐）")
        self.map_name = QLineEdit()
        self.map_name.setPlaceholderText("可不填，默认 Map{id}")

        self.create_unlock_event = QCheckBox("同时生成地图解锁 Event（event/ + EventSort.xml）")
        self.create_unlock_event.setChecked(True)
        self.create_unlock_event.toggled.connect(self._sync_event_id_enabled)
        self.event_id = QLineEdit()
        self.event_id.setPlaceholderText("留空则默认 = max(1, MapID ÷ 1000)，可手填 Event ID")
        if self._edit_mode:
            self.create_unlock_event.setVisible(False)
            self.event_id.setVisible(False)

        self.tabs = QTabWidget()

        add_area_btn = QPushButton("新增 MapPage")
        add_area_btn.clicked.connect(self._add_page)
        remove_area_btn = QPushButton("删除当前 MapPage")
        remove_area_btn.clicked.connect(self._remove_current_page)

        top = QFormLayout()
        top.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        top.addRow("Map ID", self.map_id)
        top.addRow("Map 名称", self.map_name)
        top.addRow("", self.create_unlock_event)
        top.addRow("解锁 Event ID", self.event_id)

        area_btns = QHBoxLayout()
        area_btns.addWidget(add_area_btn)
        area_btns.addWidget(remove_area_btn)
        area_btns.addStretch(1)

        hint = QLabel("每个 MapPage 为 3x3 九宫格（9个最终奖励位）。点击格子编辑最终奖励与对应 MapArea 过程设置。")
        hint.setStyleSheet("color:#374151;")

        ok = QPushButton("保存修改" if self._edit_mode else "生成 Map + MapArea + Reward (+Event)")
        ok.clicked.connect(self._generate)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(area_btns)
        layout.addWidget(hint)
        layout.addWidget(self.tabs, stretch=1)
        layout.addLayout(btns)

        if self._edit_mode:
            self.map_id.setReadOnly(True)
            err = self._load_existing(edit_map_xml)
            if err:
                QMessageBox.critical(self, "无法加载地图", err)
                QTimer.singleShot(0, self.reject)
        else:
            self._add_page()
            self._sync_event_id_enabled(self.create_unlock_event.isChecked())

    def _sync_event_id_enabled(self, on: bool) -> None:
        self.event_id.setEnabled(on)

    def _load_existing(self, map_xml: Path) -> str:
        """载入 Map.xml 及对应 MapArea；成功返回空串，失败返回错误说明。"""
        try:
            root = ET.parse(map_xml).getroot()
        except Exception as e:
            return str(e)
        mid = _safe_int(root.findtext("name/id") or "")
        if mid is None:
            return "Map.xml 缺少有效的 name/id"
        mname = (root.findtext("name/str") or "").strip() or f"Map{mid}"
        self._current_map_id = mid
        self.map_id.setText(str(mid))
        self.map_name.setText(mname)
        infos = root.findall("infos/MapDataAreaInfo")
        if not infos:
            return "Map.xml 中没有 MapDataAreaInfo（区域列表为空）"
        while self.tabs.count() > 0:
            self.tabs.removeTab(0)
        self._area_cells.clear()
        self._area_ids.clear()
        self._area_names.clear()
        self._area_extras.clear()
        self._area_info_cells.clear()
        self._area_info_meta.clear()
        self._area_grid_indices.clear()
        rel_root = self._acus_root
        truncated_areas: list[str] = []
        for info in infos:
            aid = _safe_int(info.findtext("mapAreaName/id") or "")
            if aid is None:
                continue
            aname = (info.findtext("mapAreaName/str") or "").strip() or f"Area{aid}"
            info_rid = _safe_int(info.findtext("rewardName/id") or "")
            info_rstr = (info.findtext("rewardName/str") or "").strip()
            info_mid = _safe_int(info.findtext("musicName/id") or "")
            info_mstr = (info.findtext("musicName/str") or "").strip()
            dds_id = _safe_int(info.findtext("ddsMapName/id") or "")
            dds_str = (info.findtext("ddsMapName/str") or "").strip()
            page_index = _safe_int(info.findtext("pageIndex") or "")
            index_in_page = _safe_int(info.findtext("indexInPage") or "")
            req = _safe_int(info.findtext("requiredAchievementCount") or "")
            gauge_id = _safe_int(info.findtext("gaugeName/id") or "")
            gauge_str = (info.findtext("gaugeName/str") or "").strip()
            hard_raw = (info.findtext("isHard") or "false").strip().lower()
            meta = MapInfoMeta(
                dds_id=dds_id if dds_id is not None else 0,
                dds_str=dds_str or "共通0001_CHUNITHM",
                page_index=page_index if page_index is not None else 0,
                index_in_page=index_in_page if index_in_page is not None else 0,
                required_achievement_count=req if req is not None else 0,
                gauge_id=gauge_id if gauge_id is not None else 34,
                gauge_str=gauge_str or "基本セット34",
                is_hard=(hard_raw == "true"),
            )
            info_cell = CellData()
            if info_rid is not None and info_rid >= 0:
                info_cell.reward_id = info_rid
                info_cell.reward_name = info_rstr or f"Reward{info_rid}"
                enrich_cell_from_reward_xml(self._acus_root, info_cell)
            if info_mid is not None and info_mid >= 0:
                info_cell.music_id = info_mid
                info_cell.music_name = info_mstr or f"Music{info_mid}"
            ap = self._acus_root / "mapArea" / f"mapArea{aid:08d}" / "MapArea.xml"
            if not ap.exists():
                try:
                    rel = ap.relative_to(rel_root)
                except ValueError:
                    rel = ap
                return f"找不到 MapArea 文件：{rel}"
            try:
                cells, extras, grid_indices, truncated = parse_maparea_file(self._acus_root, ap)
            except Exception as e:
                return f"读取 MapArea 失败 ({ap.name}): {e}"
            if truncated:
                truncated_areas.append(aname or f"mapArea{aid:08d}")
            self._area_ids.append(aid)
            self._area_names.append(aname)
            self._area_extras.append(extras)
            self._area_info_cells.append(info_cell)
            self._area_info_meta.append(meta)
            self._area_cells.append(cells)
            self._area_grid_indices.append(grid_indices)
        if not self._area_cells:
            return "没有成功载入任何 MapArea"
        self._rebuild_page_tabs()
        if truncated_areas:
            QTimer.singleShot(
                0,
                lambda: QMessageBox.warning(
                    self,
                    "MapArea 格子过多",
                    "以下 MapArea 中格子超过 9 个，已按 index 排序后只保留前 9 个，其余未载入：\n"
                    + "\n".join(truncated_areas[:12])
                    + ("\n…" if len(truncated_areas) > 12 else ""),
                ),
            )
        return ""

    def _load_reward_refs(self) -> list[RewardRef]:
        refs: list[RewardRef] = []
        for p in self._acus_root.glob("reward/**/Reward.xml"):
            try:
                r = ET.parse(p).getroot()
                rid = _safe_int(r.findtext("name/id") or "")
                name = (r.findtext("name/str") or "").strip()
                if rid is not None:
                    c = CellData(reward_id=rid, reward_name=name or f"Reward{rid}")
                    enrich_cell_from_reward_xml(self._acus_root, c)
                    k = _kind_label(c.reward_kind)
                    label = f"[{k}] {c.reward_name or f'Reward{rid}'}"
                    if c.reward_inner_id is not None and c.reward_inner_id >= 0:
                        label += f" (inner:{c.reward_inner_id})"
                    refs.append(RewardRef(rid, c.reward_name or f"Reward{rid}", label))
            except Exception:
                continue
        return sorted(refs, key=lambda x: x.id)

    def _load_music_refs(self) -> list[MusicRef]:
        refs: list[MusicRef] = []
        for p in self._acus_root.glob("music/**/Music.xml"):
            try:
                r = ET.parse(p).getroot()
                mid = _safe_int(r.findtext("name/id") or "")
                name = (r.findtext("name/str") or "").strip()
                if mid is not None:
                    refs.append(MusicRef(mid, name or f"Music{mid}"))
            except Exception:
                continue
        return sorted(refs, key=lambda x: x.id)

    def _load_chara_refs(self) -> list[RewardRef]:
        refs: list[RewardRef] = []
        for p in self._acus_root.glob("chara/**/Chara.xml"):
            try:
                r = ET.parse(p).getroot()
                cid = _safe_int(r.findtext("name/id") or "")
                name = (r.findtext("name/str") or "").strip()
                if cid is not None:
                    refs.append(RewardRef(cid, name or f"Chara{cid}"))
            except Exception:
                continue
        return sorted(refs, key=lambda x: x.id)

    def _load_nameplate_refs(self) -> list[RewardRef]:
        refs: list[RewardRef] = []
        for p in self._acus_root.glob("namePlate/**/NamePlate.xml"):
            try:
                r = ET.parse(p).getroot()
                nid = _safe_int(r.findtext("name/id") or "")
                name = (r.findtext("name/str") or "").strip()
                if nid is not None:
                    refs.append(RewardRef(nid, name or f"NamePlate{nid}"))
            except Exception:
                continue
        return sorted(refs, key=lambda x: x.id)

    def _load_trophy_refs(self) -> list[RewardRef]:
        refs: list[RewardRef] = []
        for p in self._acus_root.glob("trophy/**/Trophy.xml"):
            try:
                r = ET.parse(p).getroot()
                tid = _safe_int(r.findtext("name/id") or "")
                name = (r.findtext("name/str") or "").strip()
                if tid is not None:
                    refs.append(RewardRef(tid, name or f"Trophy{tid}"))
            except Exception:
                continue
        return sorted(refs, key=lambda x: x.id)

    def _append_new_area_with_meta(self, *, page_index: int, index_in_page: int) -> int:
        cells = [CellData() for _ in range(9)]
        self._area_cells.append(cells)
        self._area_info_cells.append(CellData())
        self._area_info_meta.append(MapInfoMeta(page_index=page_index, index_in_page=index_in_page))
        self._area_extras.append(_default_map_area_extras())
        self._area_grid_indices.append([None] * 9)
        if self._edit_mode:
            nid = (max(self._area_ids) + 1) if self._area_ids else max(1, (self._current_map_id % 10_000_000) * 10 + 1)
            self._area_ids.append(nid)
            mn = self.map_name.text().strip() or f"Map{self._current_map_id}"
            self._area_names.append(f"{mn}_Area{len(self._area_cells)}")
        return len(self._area_cells) - 1

    def _add_page(self) -> None:
        new_page = len(self._page_area_slots) if self._page_area_slots else 0
        for slot in range(9):
            self._append_new_area_with_meta(page_index=new_page, index_in_page=slot)
        self._rebuild_page_tabs()
        if new_page < self.tabs.count():
            self.tabs.setCurrentIndex(new_page)

    def _remove_current_page(self) -> None:
        cur_page = self.tabs.currentIndex()
        if cur_page < 0:
            return
        # 至少保留一个 page
        if len(self._page_area_slots) <= 1:
            QMessageBox.information(self, "提示", "至少保留一个 MapPage")
            return
        keep: list[int] = []
        for i, m in enumerate(self._area_info_meta):
            if m.page_index != cur_page:
                keep.append(i)
        self._area_cells = [self._area_cells[i] for i in keep]
        self._area_info_cells = [self._area_info_cells[i] for i in keep]
        self._area_info_meta = [self._area_info_meta[i] for i in keep]
        self._area_extras = [self._area_extras[i] for i in keep]
        self._area_grid_indices = [self._area_grid_indices[i] for i in keep]
        if self._edit_mode:
            self._area_ids = [self._area_ids[i] for i in keep]
            self._area_names = [self._area_names[i] for i in keep]
        # 删除后压缩 pageIndex，保证连续
        for m in self._area_info_meta:
            if m.page_index > cur_page:
                m.page_index -= 1
        self._rebuild_page_tabs()
        self.tabs.setCurrentIndex(max(0, min(cur_page, self.tabs.count() - 1)))

    def _rebuild_page_slots(self) -> None:
        max_page = 0
        for m in self._area_info_meta:
            max_page = max(max_page, m.page_index)
        slots = [[None for _ in range(9)] for _ in range(max_page + 1)]
        for i, m in enumerate(self._area_info_meta):
            if 0 <= m.index_in_page <= 8 and m.page_index >= 0:
                while m.page_index >= len(slots):
                    slots.append([None for _ in range(9)])
                slots[m.page_index][m.index_in_page] = i
        self._page_area_slots = slots

    def _rebuild_page_tabs(self) -> None:
        self._rebuild_page_slots()
        while self.tabs.count() > 0:
            self.tabs.removeTab(0)
        for pidx, slots in enumerate(self._page_area_slots):
            page = self._build_page_tab(pidx, slots)
            self.tabs.addTab(page, f"Page {pidx + 1}")
        if self.tabs.count() > 0:
            self.tabs.setCurrentIndex(0)

    def _build_page_tab(self, page_idx: int, slots: list[int | None]) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        grid = QGridLayout()
        grid.setSpacing(10)
        for i in range(9):
            aid = slots[i] if i < len(slots) else None
            btn = QPushButton(self._slot_text(page_idx, i, aid))
            btn.setMinimumHeight(90)
            btn.clicked.connect(lambda _=False, p=page_idx, s=i: self._edit_page_slot(p, s))
            grid.addWidget(btn, i // 3, i % 3)
        root.addLayout(grid)
        return page

    def _refresh_area_page(self, area_idx: int) -> None:
        _ = area_idx
        self._rebuild_page_tabs()

    def _area_info_text(self, area_idx: int) -> str:
        c = self._area_info_cells[area_idx]
        meta = self._area_info_meta[area_idx]
        if c.reward_id is None:
            return (
                f"P{meta.page_index + 1}-S{meta.index_in_page + 1} 页面奖励: (空) | "
                f"Req:{meta.required_achievement_count} Gauge:{meta.gauge_id}"
            )
        t = (
            f"P{meta.page_index + 1}-S{meta.index_in_page + 1} 页面奖励: "
            f"{_kind_label(c.reward_kind)} #{c.reward_id} | Req:{meta.required_achievement_count} Gauge:{meta.gauge_id}"
        )
        if c.reward_name:
            t += f" {c.reward_name}"
        return t

    def _area_extras_text(self, area_idx: int) -> str:
        ex = self._area_extras[area_idx] if area_idx < len(self._area_extras) else _default_map_area_extras()
        return f"mapBonus:{ex.bonus_id} | shorten:{','.join(str(x) for x in ex.shorten_counts[:4])}..."

    def _slot_text(self, page_idx: int, slot_idx: int, area_idx: int | None) -> str:
        if area_idx is None:
            return f"P{page_idx + 1}-S{slot_idx + 1}\n(空)"
        c = self._area_info_cells[area_idx]
        meta = self._area_info_meta[area_idx]
        aid = self._area_ids[area_idx] if area_idx < len(self._area_ids) else -1
        base = f"P{meta.page_index + 1}-S{meta.index_in_page + 1}\nArea:{aid}"
        if c.reward_id is None:
            return base + "\n最终奖励:(空)"
        return base + f"\n最终:{_kind_label(c.reward_kind)} {c.reward_name or c.reward_id}"

    def _cell_text(self, area_idx: int, cell_idx: int) -> str:
        c = self._area_cells[area_idx][cell_idx]
        if c.reward_id is None:
            return f"格子 {cell_idx + 1}\n(空)"
        kind_text = _kind_label(c.reward_kind)
        t = f"格子 {cell_idx + 1}\n{kind_text}:{c.reward_id}"
        if c.reward_name:
            t += f"\n{c.reward_name}"
        if c.reward_inner_id is not None and c.reward_inner_id >= 0:
            inner_name = self._inner_name(c)
            if inner_name:
                t += f"\n对象:{inner_name}"
            else:
                t += f"\n对象ID:{c.reward_inner_id}"
        if c.music_id is not None:
            mname = self._music_name_by_id.get(c.music_id, c.music_name or f"Music{c.music_id}")
            t += f"\n乐曲:{c.music_id} {mname}"
        return t

    def _inner_name(self, c: CellData) -> str:
        iid = c.reward_inner_id
        if iid is None:
            return ""
        if c.reward_kind == "角色":
            return self._chara_name_by_id.get(iid, "")
        if c.reward_kind == "称号(Trophy)":
            return self._trophy_name_by_id.get(iid, "")
        if c.reward_kind == "姓名牌装饰(NamePlate)":
            return self._nameplate_name_by_id.get(iid, "")
        if c.reward_kind == "乐曲解锁(Music)":
            return self._music_name_by_id.get(iid, "")
        return ""

    def _edit_cell(self, area_idx: int, cell_idx: int) -> None:
        d = self._area_cells[area_idx][cell_idx]
        dlg = CellEditDialog(
            acus_root=self._acus_root,
            reward_refs=self._reward_refs,
            chara_refs=self._chara_refs,
            trophy_refs=self._trophy_refs,
            nameplate_refs=self._nameplate_refs,
            music_refs=self._music_refs,
            data=d,
            parent=self,
        )
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._refresh_area_page(area_idx)

    def _edit_area_info(self, area_idx: int) -> None:
        d = self._area_info_cells[area_idx]
        dlg = CellEditDialog(
            acus_root=self._acus_root,
            reward_refs=self._reward_refs,
            chara_refs=self._chara_refs,
            trophy_refs=self._trophy_refs,
            nameplate_refs=self._nameplate_refs,
            music_refs=self._music_refs,
            data=d,
            parent=self,
        )
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._refresh_area_page(area_idx)

    def _edit_area_extras(self, area_idx: int) -> None:
        ex = self._area_extras[area_idx]
        dlg = AreaExtrasDialog(extras=ex, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._refresh_area_page(area_idx)

    def _edit_area_meta(self, area_idx: int) -> None:
        meta = self._area_info_meta[area_idx]
        dlg = AreaPageMetaDialog(meta=meta, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._refresh_area_page(area_idx)

    def _edit_page_slot(self, page_idx: int, slot_idx: int) -> None:
        if page_idx < 0 or page_idx >= len(self._page_area_slots):
            return
        area_idx = self._page_area_slots[page_idx][slot_idx]
        if area_idx is None:
            # 点击空格：自动新建一个 MapArea 并绑定到当前 page/slot
            area_idx = self._append_new_area_with_meta(page_index=page_idx, index_in_page=slot_idx)
            self._rebuild_page_tabs()
        self._edit_page_slot_single_dialog(area_idx)

    def _next_custom_reward_id(self) -> int:
        max_id = 700000000
        for p in self._acus_root.glob("reward/**/Reward.xml"):
            try:
                r = ET.parse(p).getroot()
                rid = _safe_int(r.findtext("name/id") or "")
                if rid is not None and str(rid).startswith("7"):
                    max_id = max(max_id, rid)
            except Exception:
                continue
        return max_id + 1

    def _is_intermediate_reward_allowed(self, rid: int) -> bool:
        rx = resolve_reward_xml(self._acus_root, rid)
        if rx is None:
            return False
        try:
            root = ET.parse(rx).getroot()
            sub = root.find(".//RewardSubstanceData")
            if sub is None:
                return False
            t = _safe_int(sub.findtext("type") or "")
            if t == 1:
                return True
            if t == 0:
                gp = _safe_int(sub.findtext("gamePoint/gamePoint") or "")
                return gp is not None and gp > 0
            return False
        except Exception:
            return False

    def _edit_page_slot_single_dialog(self, area_idx: int) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("编辑页面格子")
        dlg.setModal(True)
        lay = QVBoxLayout(dlg)

        # 最终奖励（Map.xml）
        top = QGroupBox("最终奖励（Map.xml）")
        top_form = QFormLayout(top)
        reward_pick = QComboBox()
        reward_pick.addItem("(请选择)")
        cur = self._area_info_cells[area_idx].reward_id
        cur_idx = 0
        for i, r in enumerate(self._reward_refs, start=1):
            reward_pick.addItem(f"{r.id} | {r.display_name or r.name}", r.id)
            if cur is not None and r.id == cur:
                cur_idx = i
        reward_pick.setCurrentIndex(cur_idx)
        new_reward_btn = QPushButton("新增 Reward")
        music_on = QCheckBox("有课题曲")
        music_pick = QComboBox()
        music_pick.addItem("(请选择)")
        for m in self._music_refs:
            music_pick.addItem(f"{m.id} | {m.name}", m.id)
        music_id = QLineEdit()
        music_name = QLineEdit()
        music_mode = QComboBox()
        music_mode.addItems(["选择 ACUS 乐曲", "手填乐曲ID"])
        cinfo = self._area_info_cells[area_idx]
        if cinfo.music_id is not None:
            music_on.setChecked(True)
            idx = next((i for i, m in enumerate(self._music_refs, start=1) if m.id == cinfo.music_id), -1)
            if idx > 0:
                music_mode.setCurrentText("选择 ACUS 乐曲")
                music_pick.setCurrentIndex(idx)
            else:
                music_mode.setCurrentText("手填乐曲ID")
                music_id.setText(str(cinfo.music_id))
                music_name.setText(cinfo.music_name or "")

        def _sync_music() -> None:
            has_reward = reward_pick.currentIndex() > 0
            on = music_on.isChecked()
            music_on.setEnabled(has_reward)
            if not has_reward:
                music_on.setChecked(False)
            music_mode.setEnabled(has_reward and on)
            pick_mode = has_reward and on and music_mode.currentText() == "选择 ACUS 乐曲"
            music_pick.setEnabled(pick_mode)
            music_id.setEnabled(has_reward and on and not pick_mode)
            music_name.setEnabled(has_reward and on and not pick_mode)

        music_on.toggled.connect(_sync_music)
        music_mode.currentTextChanged.connect(_sync_music)
        reward_pick.currentIndexChanged.connect(_sync_music)
        _sync_music()
        top_form.addRow("Reward", reward_pick)
        top_form.addRow("", new_reward_btn)
        top_form.addRow("", music_on)
        top_form.addRow("课题曲模式", music_mode)
        top_form.addRow("课题曲", music_pick)
        top_form.addRow("手填乐曲ID", music_id)
        top_form.addRow("手填乐曲名", music_name)
        lay.addWidget(top)

        # MapArea 基础
        mid = QGroupBox("MapArea 基础")
        mid_form = QFormLayout(mid)
        meta = self._area_info_meta[area_idx]
        page_idx_edit = QLineEdit(str(meta.page_index))
        slot_edit = QLineEdit(str(meta.index_in_page))
        total_steps_edit = QLineEdit(str(max([x for x in self._area_grid_indices[area_idx] if x is not None] or [0])))
        mid_form.addRow("pageIndex", page_idx_edit)
        mid_form.addRow("indexInPage(0~8)", slot_edit)
        mid_form.addRow("地图格数(总步数)", total_steps_edit)
        lay.addWidget(mid)

        # 高级设置
        adv = QGroupBox("高级设置")
        adv.setCheckable(True)
        adv.setChecked(False)
        adv_form = QFormLayout(adv)
        add_step = QLineEdit()
        add_reward = QComboBox()
        add_reward.addItem("(仅功能票/Points)")
        for r in self._reward_refs:
            if self._is_intermediate_reward_allowed(r.id):
                add_reward.addItem(f"{r.id} | {r.display_name or r.name}", r.id)
        extra_lines = QTextEdit()
        extra_lines.setPlaceholderText("每行：步数,reward_id,reward_name")
        add_btn = QPushButton("新增过程奖励")

        def _on_add_line() -> None:
            step = _safe_int(add_step.text())
            idx = add_reward.currentIndex()
            if step is None or step < 0 or idx <= 0:
                return
            rid = add_reward.currentData()
            txt = add_reward.currentText()
            rname = txt.split("|", 1)[1].strip() if "|" in txt else f"Reward{rid}"
            old = extra_lines.toPlainText().strip()
            line = f"{step},{rid},{rname}"
            extra_lines.setPlainText((old + "\n" + line).strip())
            add_step.clear()

        add_btn.clicked.connect(_on_add_line)
        adv_form.addRow("出现步数", add_step)
        adv_form.addRow("过程奖励", add_reward)
        adv_form.addRow("", add_btn)
        adv_form.addRow("过程奖励列表", extra_lines)
        lay.addWidget(adv)

        def _sync_advanced() -> None:
            on = adv.isChecked()
            add_step.setEnabled(on)
            add_reward.setEnabled(on)
            add_btn.setEnabled(on)
            extra_lines.setEnabled(on)

        adv.toggled.connect(_sync_advanced)
        _sync_advanced()

        btns = QHBoxLayout()
        ok = QPushButton("保存")
        cancel = QPushButton("取消")
        cancel.clicked.connect(dlg.reject)
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

        def _new_reward() -> None:
            rd = RewardCreateDialog(default_id=self._next_custom_reward_id(), music_refs=self._music_refs, parent=dlg)
            if rd.exec() == rd.DialogCode.Accepted and rd.result_cell is not None:
                self._ensure_reward_xml(cell=rd.result_cell)
                self._reward_refs = self._load_reward_refs()
                reward_pick.clear()
                reward_pick.addItem("(请选择)")
                for rr in self._reward_refs:
                    reward_pick.addItem(f"{rr.id} | {rr.display_name or rr.name}", rr.id)
                idx_new = next((i for i in range(1, reward_pick.count()) if reward_pick.itemData(i) == rd.result_cell.reward_id), 0)
                reward_pick.setCurrentIndex(idx_new)

        new_reward_btn.clicked.connect(_new_reward)

        def _save() -> None:
            # page/slot
            p = _safe_int(page_idx_edit.text())
            s = _safe_int(slot_edit.text())
            total = _safe_int(total_steps_edit.text())
            if p is None or p < 0 or s is None or not (0 <= s <= 8) or total is None or total < 0:
                QMessageBox.critical(dlg, "错误", "page/slot/总步数 输入不合法")
                return
            # final reward
            rp = reward_pick.currentIndex()
            if rp <= 0:
                QMessageBox.critical(dlg, "错误", "请先选择最终奖励")
                return
            rid = reward_pick.currentData()
            cell = self._area_info_cells[area_idx]
            cell.reward_id = int(rid)
            for rr in self._reward_refs:
                if rr.id == rid:
                    cell.reward_name = rr.name
                    break
            cell.reward_kind = "外部奖励ID"
            cell.reward_inner_id = None
            cell.music_id = None
            cell.music_name = ""
            enrich_cell_from_reward_xml(self._acus_root, cell)
            if music_on.isChecked():
                if music_mode.currentText() == "选择 ACUS 乐曲":
                    mi = music_pick.currentData()
                    if mi is not None:
                        cell.music_id = int(mi)
                        cell.music_name = next((m.name for m in self._music_refs if m.id == mi), f"Music{mi}")
                else:
                    mi = _safe_int(music_id.text())
                    if mi is None:
                        QMessageBox.critical(dlg, "错误", "手填乐曲ID不合法")
                        return
                    cell.music_id = mi
                    cell.music_name = music_name.text().strip() or f"Music{mi}"
            # update meta
            self._area_info_meta[area_idx].page_index = p
            self._area_info_meta[area_idx].index_in_page = s

            # maparea default: only final reward on last step in basic mode
            cells = [CellData() for _ in range(9)]
            idxs: list[int | None] = [0, total] + [None] * 7
            # advanced intermediate rewards
            if adv.isChecked():
                lines = [x.strip() for x in extra_lines.toPlainText().splitlines() if x.strip()]
                points: list[tuple[int, CellData]] = [(0, CellData()), (total, CellData())]
                for ln in lines:
                    ps = [x.strip() for x in ln.split(",")]
                    if len(ps) < 2:
                        continue
                    st = _safe_int(ps[0])
                    rrid = _safe_int(ps[1])
                    if st is None or rrid is None:
                        continue
                    if not self._is_intermediate_reward_allowed(rrid):
                        continue
                    rnm = ps[2] if len(ps) >= 3 and ps[2] else f"Reward{rrid}"
                    points.append((st, CellData(reward_id=rrid, reward_name=rnm)))
                points = sorted(points, key=lambda x: x[0])[:9]
                idxs = [p[0] for p in points] + [None] * (9 - len(points))
                cells = [p[1] for p in points] + [CellData() for _ in range(9 - len(points))]
            self._area_cells[area_idx] = cells[:9]
            self._area_grid_indices[area_idx] = idxs[:9]
            dlg.accept()

        ok.clicked.connect(_save)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._refresh_area_page(area_idx)

    def _generate(self) -> None:
        if self._edit_mode:
            map_id = self._current_map_id
        else:
            map_id = _safe_int(self.map_id.text())
            if map_id is None:
                QMessageBox.critical(self, "错误", "Map ID 必须是整数")
                return
            if map_id < 0:
                QMessageBox.critical(self, "错误", "Map ID 必须为非负整数")
                return

        map_name = self.map_name.text().strip() or f"Map{map_id}"
        map_dir = self._acus_root / "map" / f"map{map_id:08d}"
        map_dir.mkdir(parents=True, exist_ok=True)

        # build map infos and write maparea/reward files
        infos_xml = []
        for idx, cells in enumerate(self._area_cells, start=1):
            if self._edit_mode:
                area_id = self._area_ids[idx - 1]
                area_name = self._area_names[idx - 1]
                extras = self._area_extras[idx - 1]
                info_cell = self._area_info_cells[idx - 1]
                meta = self._area_info_meta[idx - 1]
            else:
                area_id = (map_id % 10_000_000) * 10 + idx
                area_name = f"{map_name}_Area{idx}"
                extras = self._area_extras[idx - 1]
                info_cell = self._area_info_cells[idx - 1]
                meta = self._area_info_meta[idx - 1]
            grid_ix = self._area_grid_indices[idx - 1] if self._edit_mode else None
            self._write_maparea(
                area_id=area_id,
                area_name=area_name,
                cells=cells,
                extras=extras,
                grid_indices=grid_ix,
            )
            infos_xml.append(
                f"""    <MapDataAreaInfo>
      <mapAreaName><id>{area_id}</id><str>{self._xml_text(area_name)}</str><data /></mapAreaName>
      <ddsMapName><id>{meta.dds_id}</id><str>{self._xml_text(meta.dds_str)}</str><data /></ddsMapName>
      <musicName><id>{info_cell.music_id if info_cell.music_id is not None else -1}</id><str>{self._xml_text(info_cell.music_name if info_cell.music_id is not None else "Invalid")}</str><data /></musicName>
      <rewardName><id>{info_cell.reward_id if info_cell.reward_id is not None else -1}</id><str>{self._xml_text(info_cell.reward_name if info_cell.reward_id is not None else "Invalid")}</str><data /></rewardName>
      <isHard>{"true" if meta.is_hard else "false"}</isHard><pageIndex>{meta.page_index}</pageIndex><indexInPage>{meta.index_in_page}</indexInPage>
      <requiredAchievementCount>{meta.required_achievement_count}</requiredAchievementCount>
      <gaugeName><id>{meta.gauge_id}</id><str>{self._xml_text(meta.gauge_str)}</str><data /></gaugeName>
    </MapDataAreaInfo>"""
            )

        map_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<MapData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>map{map_id:08d}</dataName>
  <netDispPeriod>false</netDispPeriod>
  <name><id>{map_id}</id><str>{self._xml_text(map_name)}</str><data /></name>
  <mapType>1</mapType>
  <hiddenType>0</hiddenType>
  <unlockText>-</unlockText>
  <mapFilterID><id>3</id><str>Other</str><data>CHUNITHM</data></mapFilterID>
  <categoryName><id>0</id><str>設定なし</str><data /></categoryName>
  <timeTableName><id>-1</id><str>Invalid</str><data /></timeTableName>
  <stopPageIndex>0</stopPageIndex>
  <stopReleaseEventName><id>-1</id><str>Invalid</str><data /></stopReleaseEventName>
  <priority>0</priority>
  <infos>
{chr(10).join(infos_xml)}
  </infos>
</MapData>
"""
        (map_dir / "Map.xml").write_text(map_xml, encoding="utf-8")
        self._append_map_sort(map_id)

        msg = (
            f"已保存地图 map{map_id:08d}，共 {len(self._area_cells)} 个 Area。"
            if self._edit_mode
            else f"已生成地图 map{map_id:08d}，共 {len(self._area_cells)} 个 Area。"
        )
        if not self._edit_mode and self.create_unlock_event.isChecked():
            eid_in = _safe_int(self.event_id.text())
            event_id = eid_in if eid_in is not None else max(1, map_id // 1000)
            if event_id < 0:
                QMessageBox.critical(self, "错误", "解锁 Event ID 必须为非负整数")
                return
            try:
                self._write_map_unlock_event(map_id=map_id, map_name=map_name, event_id=event_id)
                self._append_event_sort(event_id)
                msg += f"\n已生成地图解锁 Event：event{event_id:08d}"
            except Exception as e:
                QMessageBox.warning(self, "Event 未完整写入", f"地图已生成，但 Event/EventSort 写入失败：\n{e}")

        QMessageBox.information(self, "完成", msg)
        self.accept()

    def _write_maparea(
        self,
        *,
        area_id: int,
        area_name: str,
        cells: list[CellData],
        extras: MapAreaExtras | None = None,
        grid_indices: list[int | None] | None = None,
    ) -> None:
        area_dir = self._acus_root / "mapArea" / f"mapArea{area_id:08d}"
        area_dir.mkdir(parents=True, exist_ok=True)
        ex = extras or _default_map_area_extras()
        bid, bstr = ex.bonus_id, ex.bonus_str
        counts = list(ex.shorten_counts)
        while len(counts) < 8:
            counts.append(0)
        shorten_lines = "\n".join(
            f"    <MapAreaGridShorteningData><count>{c}</count></MapAreaGridShorteningData>" for c in counts[:8]
        )

        grids: list[str] = []
        # 编辑模式新增的 Area：grid 全为 None 时按「新增地图」写满 9 格 index 0..8
        if grid_indices is not None and all(x is None for x in grid_indices):
            grid_indices = None
        sparse = grid_indices is not None

        for i, c in enumerate(cells):
            has_r = c.reward_id is not None and c.reward_id >= 0
            if sparse:
                orig = grid_indices[i] if i < len(grid_indices) else None
                if orig is None and not has_r:
                    # 载入时该 UI 格为「补位」，且仍为空：不写节点（保持官方稀疏结构）
                    continue
                ix = orig if orig is not None else i
            else:
                ix = i

            if has_r:
                rid = c.reward_id
                assert rid is not None
                rname = c.reward_name or f"Reward{rid}"
                self._ensure_reward_xml(cell=c)
            else:
                rid = -1
                rname = "Invalid"

            dt = c.display_type if c.display_type is not None else 1
            ct = c.cell_type if c.cell_type is not None else 1
            grids.append(
                f"""    <MapAreaGridData>
      <index>{ix}</index><displayType>{dt}</displayType><type>{ct}</type><exit /><entrance />
      <reward><rewardName><id>{rid}</id><str>{rname}</str><data /></rewardName></reward>
    </MapAreaGridData>"""
            )

        xml = f"""<?xml version="1.0" encoding="utf-8"?>
<MapAreaData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>mapArea{area_id:08d}</dataName>
  <netOpenName><id>2801</id><str>v2_45 00_1</str><data /></netOpenName>
  <name><id>{area_id}</id><str>{self._xml_text(area_name)}</str><data /></name>
  <hiddenType>0</hiddenType><unlockText>-</unlockText>
  <mapBonusName><id>{bid}</id><str>{self._xml_text(bstr)}</str><data /></mapBonusName>
  <mapAreaBoostType>0</mapAreaBoostType><mapAreaBoostMultiple>10</mapAreaBoostMultiple>
  <shorteningGridCountList>
{shorten_lines}
  </shorteningGridCountList>
  <stopReleaseEventName><id>-1</id><str>Invalid</str><data /></stopReleaseEventName>
  <grids>
{chr(10).join(grids)}
  </grids>
</MapAreaData>
"""
        (area_dir / "MapArea.xml").write_text(xml, encoding="utf-8")

    def _ensure_reward_xml(self, *, cell: CellData) -> None:
        if cell.reward_id is None:
            return
        rid = cell.reward_id
        if resolve_reward_xml(self._acus_root, rid) is not None:
            return
        rdir = self._acus_root / "reward" / f"reward{rid:09d}"
        rdir.mkdir(parents=True, exist_ok=True)

        # build a basic RewardData; unknown IDs are allowed with warning in UI
        kind = cell.reward_kind
        inner = cell.reward_inner_id if cell.reward_inner_id is not None else -1
        ticket_id = -1
        chara_id = inner if kind == "角色" else -1
        trophy_id = inner if kind == "称号(Trophy)" else -1
        nameplate_id = inner if kind == "姓名牌装饰(NamePlate)" else -1
        music_id = cell.music_id if cell.music_id is not None else -1
        music_name = cell.music_name if (cell.music_id is not None and cell.music_name) else ("Invalid" if music_id == -1 else f"Music{music_id}")
        reward_type = 0
        if kind == "角色":
            reward_type = 3
        elif kind == "称号(Trophy)":
            reward_type = 2
        elif kind == "姓名牌装饰(NamePlate)":
            reward_type = 5

        xml = f"""<?xml version="1.0" encoding="utf-8"?>
<RewardData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>reward{rid:09d}</dataName>
  <name><id>{rid}</id><str>{cell.reward_name or f"Reward{rid}"}</str><data /></name>
  <substances>
    <list>
      <RewardSubstanceData>
        <type>{reward_type}</type>
        <gamePoint><gamePoint>0</gamePoint></gamePoint>
        <ticket><ticketName><id>{ticket_id}</id><str>{"Invalid" if ticket_id==-1 else f"Ticket{ticket_id}"}</str><data /></ticketName></ticket>
        <trophy><trophyName><id>{trophy_id}</id><str>{"Invalid" if trophy_id==-1 else f"Trophy{trophy_id}"}</str><data /></trophyName></trophy>
        <chara><charaName><id>{chara_id}</id><str>{"Invalid" if chara_id==-1 else f"Chara{chara_id}"}</str><data /></charaName></chara>
        <skillSeed><skillSeedName><id>-1</id><str>Invalid</str><data /></skillSeedName><skillSeedCount>1</skillSeedCount></skillSeed>
        <namePlate><namePlateName><id>{nameplate_id}</id><str>{"Invalid" if nameplate_id==-1 else f"NamePlate{nameplate_id}"}</str><data /></namePlateName></namePlate>
        <music><musicName><id>{music_id}</id><str>{music_name}</str><data /></musicName></music>
        <mapIcon><mapIconName><id>-1</id><str>Invalid</str><data /></mapIconName></mapIcon>
        <systemVoice><systemVoiceName><id>-1</id><str>Invalid</str><data /></systemVoiceName></systemVoice>
        <avatarAccessory><avatarAccessoryName><id>-1</id><str>Invalid</str><data /></avatarAccessoryName></avatarAccessory>
        <frame><frameName><id>-1</id><str>Invalid</str><data /></frameName></frame>
        <symbolChat><symbolChatName><id>-1</id><str>Invalid</str><data /></symbolChatName></symbolChat>
        <ultimaScore><musicName><id>-1</id><str>Invalid</str><data /></musicName></ultimaScore>
        <stage><stageName><id>-1</id><str>Invalid</str><data /></stageName></stage>
      </RewardSubstanceData>
    </list>
  </substances>
</RewardData>
"""
        rxml.write_text(xml, encoding="utf-8")

    def _xml_text(self, s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _write_map_unlock_event(self, *, map_id: int, map_name: str, event_id: int) -> None:
        """与 example/event 结构一致：substances/type=6 + map/mapName 指向本图。"""
        ev_dir = self._acus_root / "event" / f"event{event_id:08d}"
        ev_dir.mkdir(parents=True, exist_ok=True)
        title = self._xml_text(f"【MapUnlock】{map_name}")
        mstr = self._xml_text(map_name)
        xml = f"""<?xml version='1.0' encoding='utf-8'?>
<EventData>
  <dataName>event{event_id:08d}</dataName>
  <netOpenName>
    <id>2801</id>
    <str>v2_45 00_1</str>
    <data />
  </netOpenName>
  <name>
    <id>{event_id}</id>
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
    <type>6</type>
    <flag><value>0</value></flag>
    <information>
      <informationType>0</informationType>
      <informationDispType>0</informationDispType>
      <mapFilterID>
        <id>3</id>
        <str>Other</str>
        <data>CHUNITHM</data>
      </mapFilterID>
      <courseNames><list /></courseNames>
      <text />
      <image><path /></image>
      <movieName><id>-1</id><str>Invalid</str><data /></movieName>
      <presentNames><list /></presentNames>
    </information>
    <map>
      <tagText />
      <mapName>
        <id>{map_id}</id>
        <str>{mstr}</str>
        <data />
      </mapName>
      <musicNames><list /></musicNames>
    </map>
    <music><musicType>0</musicType><musicNames><list /></musicNames></music>
    <advertiseMovie>
      <firstMovieName><id>-1</id><str>Invalid</str><data /></firstMovieName>
      <secondMovieName><id>-1</id><str>Invalid</str><data /></secondMovieName>
    </advertiseMovie>
    <recommendMusic><musicNames><list /></musicNames></recommendMusic>
    <release><value>0</value></release>
    <course><courseNames><list /></courseNames></course>
    <quest><questNames><list /></questNames></quest>
    <duel><duelName><id>-1</id><str>Invalid</str><data /></duelName></duel>
    <cmission><cmissionName><id>-1</id><str>Invalid</str><data /></cmissionName></cmission>
    <changeSurfBoardUI><value>0</value></changeSurfBoardUI>
    <avatarAccessoryGacha><avatarAccessoryGachaName><id>-1</id><str>Invalid</str><data /></avatarAccessoryGachaName></avatarAccessoryGacha>
    <rightsInfo><rightsNames><list /></rightsNames></rightsInfo>
    <playRewardSet><playRewardSetName><id>-1</id><str>Invalid</str><data /></playRewardSetName></playRewardSet>
    <dailyBonusPreset><dailyBonusPresetName><id>-1</id><str>Invalid</str><data /></dailyBonusPresetName></dailyBonusPreset>
    <matchingBonus><timeTableName><id>-1</id><str>Invalid</str><data /></timeTableName></matchingBonus>
    <unlockChallenge><unlockChallengeName><id>-1</id><str>Invalid</str><data /></unlockChallengeName></unlockChallenge>
    <linkedVerse><linkedVerseName><id>-1</id><str>Invalid</str><data /></linkedVerseName></linkedVerse>
  </substances>
</EventData>
"""
        (ev_dir / "Event.xml").write_text(xml, encoding="utf-8")

    def _append_event_sort(self, event_id: int) -> None:
        sort_path = self._acus_root / "event" / "EventSort.xml"
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
            try:
                if int((n.text or "").strip()) == event_id:
                    ET.indent(root)  # type: ignore[attr-defined]
                    ET.ElementTree(root).write(sort_path, encoding="utf-8", xml_declaration=True)
                    return
            except Exception:
                continue
        s = ET.SubElement(sl, "StringID")
        ET.SubElement(s, "id").text = str(event_id)
        ET.SubElement(s, "str")
        ET.SubElement(s, "data")
        ET.indent(root)  # type: ignore[attr-defined]
        ET.ElementTree(root).write(sort_path, encoding="utf-8", xml_declaration=True)

    def _append_map_sort(self, map_id: int) -> None:
        sort_path = self._acus_root / "map" / "MapSort.xml"
        if not sort_path.exists():
            sort_path.write_text(
                """<?xml version="1.0" encoding="utf-8"?>
<SerializeSortData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>map</dataName>
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
            try:
                if int((n.text or "").strip()) == map_id:
                    ET.indent(root)  # type: ignore[attr-defined]
                    ET.ElementTree(root).write(sort_path, encoding="utf-8", xml_declaration=True)
                    return
            except Exception:
                continue
        s = ET.SubElement(sl, "StringID")
        ET.SubElement(s, "id").text = str(map_id)
        ET.SubElement(s, "str")
        ET.SubElement(s, "data")
        ET.indent(root)  # type: ignore[attr-defined]
        ET.ElementTree(root).write(sort_path, encoding="utf-8", xml_declaration=True)

