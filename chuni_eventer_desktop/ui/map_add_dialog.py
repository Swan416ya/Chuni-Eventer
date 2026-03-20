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
    QTabWidget,
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


def _default_map_area_extras() -> MapAreaExtras:
    return MapAreaExtras(-1, "Invalid", (0,) * 8)


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
        if t == 2:
            cell.reward_kind = "称号(Trophy)"
            cell.reward_inner_id = _safe_int(sub.findtext("trophy/trophyName/id") or "")
        elif t == 3:
            cell.reward_kind = "角色"
            cell.reward_inner_id = _safe_int(sub.findtext("chara/charaName/id") or "")
        elif t == 5:
            cell.reward_kind = "姓名牌装饰(NamePlate)"
            cell.reward_inner_id = _safe_int(sub.findtext("namePlate/namePlateName/id") or "")
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
    truncated = len(rows) > 9
    rows = rows[:9]

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
            self.reward_pick.addItem(f"{r.id} | {r.name}")

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
        self._area_cells: list[list[CellData]] = []
        self._area_ids: list[int] = []
        self._area_names: list[str] = []
        self._area_extras: list[MapAreaExtras] = []
        # 编辑模式：每格对应 MapArea.xml 里的游戏 index（非 0..8）；与 _area_cells 对齐
        self._area_grid_indices: list[list[int | None]] = []
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

        add_area_btn = QPushButton("新增 MapArea")
        add_area_btn.clicked.connect(self._add_area)
        remove_area_btn = QPushButton("删除当前 MapArea")
        remove_area_btn.clicked.connect(self._remove_current_area)

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

        hint = QLabel("每个 MapArea 为 3x3 九宫格。点击格子配置奖励/乐曲；可留空。")
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
            self._add_area()
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
        self._area_grid_indices.clear()
        rel_root = self._acus_root
        truncated_areas: list[str] = []
        for info in infos:
            aid = _safe_int(info.findtext("mapAreaName/id") or "")
            if aid is None:
                continue
            aname = (info.findtext("mapAreaName/str") or "").strip() or f"Area{aid}"
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
            self._area_cells.append(cells)
            self._area_grid_indices.append(grid_indices)
            aidx = len(self._area_cells) - 1
            page = self._build_area_page(aidx)
            self.tabs.addTab(page, f"Area {len(self._area_cells)}")
        if not self._area_cells:
            return "没有成功载入任何 MapArea"
        self.tabs.setCurrentIndex(0)
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
                    refs.append(RewardRef(rid, name or f"Reward{rid}"))
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

    def _add_area(self) -> None:
        cells = [CellData() for _ in range(9)]
        self._area_cells.append(cells)
        if self._edit_mode:
            nid = (max(self._area_ids) + 1) if self._area_ids else max(1, (self._current_map_id % 10_000_000) * 10 + 1)
            self._area_ids.append(nid)
            mn = self.map_name.text().strip() or f"Map{self._current_map_id}"
            self._area_names.append(f"{mn}_Area{len(self._area_cells)}")
            self._area_extras.append(_default_map_area_extras())
            self._area_grid_indices.append([None] * 9)
        idx = len(self._area_cells)
        page = self._build_area_page(idx - 1)
        self.tabs.addTab(page, f"Area {idx}")
        self.tabs.setCurrentIndex(idx - 1)

    def _remove_current_area(self) -> None:
        if len(self._area_cells) <= 1:
            QMessageBox.information(self, "提示", "至少保留一个 MapArea")
            return
        idx = self.tabs.currentIndex()
        if idx < 0:
            return
        self.tabs.removeTab(idx)
        del self._area_cells[idx]
        if self._edit_mode:
            del self._area_ids[idx]
            del self._area_names[idx]
            del self._area_extras[idx]
            del self._area_grid_indices[idx]
        for i in range(self.tabs.count()):
            self.tabs.setTabText(i, f"Area {i + 1}")

    def _build_area_page(self, area_idx: int) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setSpacing(10)
        for i in range(9):
            btn = QPushButton(self._cell_text(area_idx, i))
            btn.setMinimumHeight(90)
            btn.clicked.connect(lambda _=False, a=area_idx, c=i: self._edit_cell(a, c))
            grid.addWidget(btn, i // 3, i % 3)
        return page

    def _refresh_area_page(self, area_idx: int) -> None:
        page = self.tabs.widget(area_idx)
        if page is None:
            return
        buttons = page.findChildren(QPushButton)
        if len(buttons) < 9:
            return
        for i in range(9):
            buttons[i].setText(self._cell_text(area_idx, i))

    def _cell_text(self, area_idx: int, cell_idx: int) -> str:
        c = self._area_cells[area_idx][cell_idx]
        if c.reward_id is None:
            return f"格子 {cell_idx + 1}\n(空)"
        t = f"格子 {cell_idx + 1}\n奖励:{c.reward_id}"
        if c.music_id is not None:
            t += f"\n乐曲:{c.music_id}"
        return t

    def _edit_cell(self, area_idx: int, cell_idx: int) -> None:
        d = self._area_cells[area_idx][cell_idx]
        dlg = CellEditDialog(
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
            else:
                area_id = (map_id % 10_000_000) * 10 + idx
                area_name = f"{map_name}_Area{idx}"
                extras = None
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
      <ddsMapName><id>0</id><str>共通0001_CHUNITHM</str><data /></ddsMapName>
      <musicName><id>-1</id><str>Invalid</str><data /></musicName>
      <rewardName><id>-1</id><str>Invalid</str><data /></rewardName>
      <isHard>false</isHard><pageIndex>{(idx-1)//9}</pageIndex><indexInPage>{(idx-1)%9}</indexInPage>
      <requiredAchievementCount>0</requiredAchievementCount>
      <gaugeName><id>34</id><str>基本セット34</str><data /></gaugeName>
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

