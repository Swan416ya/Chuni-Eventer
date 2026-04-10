from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

from PIL import Image, ImageOps, UnidentifiedImageError

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QGroupBox,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtWidgets import QTabBar

from qfluentwidgets import LineEdit as FluentLineEdit

from ..dds_convert import DdsToolError, ingest_to_bc3_dds
from ..game_data_index import (
    GameDataIndex,
    merged_chara_pairs,
    merged_dds_map_pairs,
    merged_music_pairs,
    merged_nameplate_pairs,
    merged_stage_pairs,
    merged_trophy_pairs,
)

from .dds_progress import run_bc3_jobs_with_progress
from ..dds_quicktex import quicktex_available
from ..dds_preview import dds_to_pixmap
from ..xml_writer import write_ddsmap_xml
from ..acus_scan import scan_map_bonuses
from .name_glyph_preview import wrap_name_input_with_preview
from .mapbonus_dialogs import MapBonusEditDialog


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


def _merged_music_refs(acus_root: Path, idx: GameDataIndex | None) -> list[MusicRef]:
    return [MusicRef(i, n) for i, n in merged_music_pairs(acus_root, idx)]


def _merged_dds_map_reward_refs(acus_root: Path, idx: GameDataIndex | None) -> list[RewardRef]:
    return [RewardRef(i, n, "") for i, n in merged_dds_map_pairs(acus_root, idx)]


def _merged_stage_reward_refs(acus_root: Path, idx: GameDataIndex | None) -> list[RewardRef]:
    return [RewardRef(i, n, "") for i, n in merged_stage_pairs(acus_root, idx)]


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


def _maparea_terminator_cell() -> CellData:
    """MapArea 路线终点占位：与 A001 mapArea0230310x 一致（displayType/type=2，Invalid）。"""
    return CellData(
        reward_id=-1,
        reward_name="Invalid",
        reward_kind="外部奖励ID",
        display_type=2,
        cell_type=2,
    )


def infer_map_terminator_index(idxs: list[int | None], cells: list[CellData]) -> int:
    """
    从已载入的 MapArea 节点推断「地图格数」编辑框默认值：
    取所有已写入格子里最大的 <index>（通常即终点 Invalid 格；旧数据也可能是最终奖励所在格）。
    """
    best = 0
    for i in range(min(9, len(idxs), len(cells))):
        ix = idxs[i]
        if ix is not None:
            best = max(best, ix)
    return best if best > 0 else 1


def _maparea_points_to_slots(pairs: list[tuple[int, CellData]]) -> tuple[list[CellData], list[int | None]]:
    pairs = sorted(pairs, key=lambda x: x[0])
    if len(pairs) > 9:
        raise ValueError("超过 9 个 MapArea 节点")
    idxs: list[int | None] = [p[0] for p in pairs] + [None] * (9 - len(pairs))
    cells: list[CellData] = [p[1] for p in pairs] + [CellData() for _ in range(9 - len(pairs))]
    return cells, idxs


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


def _combo_pick_id(combo: QComboBox) -> int | None:
    d = combo.currentData()
    if d is None:
        return None
    try:
        return int(d)
    except (TypeError, ValueError):
        return None


def _target_id_field_label(*, reward_mode: str, reward_kind: str) -> str:
    """格子编辑里「写入 Reward.xml 的目标实体 id」一行左侧文案。"""
    if reward_mode == "角色":
        return "角色ID"
    if reward_mode == "称号(Trophy)":
        return "称号ID"
    if reward_mode == "姓名牌装饰(NamePlate)":
        return "姓名牌ID"
    if reward_mode == "场景(Stage)":
        return "场景ID"
    if reward_mode == "手填奖励ID":
        k = reward_kind or "外部奖励ID"
        if k == "角色":
            return "角色ID"
        if k == "称号(Trophy)":
            return "称号ID"
        if k == "姓名牌装饰(NamePlate)":
            return "姓名牌ID"
    return "目标ID"


def _acus_pick_label(reward_mode: str) -> str:
    if reward_mode == "角色":
        return "从列表选择角色"
    if reward_mode == "称号(Trophy)":
        return "从列表选择称号"
    if reward_mode == "姓名牌装饰(NamePlate)":
        return "从列表选择姓名牌"
    if reward_mode == "场景(Stage)":
        return "从列表选择场景"
    return "从列表选择"


def _reward_create_kind_target_label(kind: str) -> str:
    return {
        "功能票(Ticket)": "功能票ID",
        "角色": "角色ID",
        "称号(Trophy)": "称号ID",
        "姓名牌装饰(NamePlate)": "姓名牌ID",
        "乐曲解锁(Music)": "乐曲ID",
        "场景(Stage)": "场景ID",
        "外部奖励ID": "关联实体ID（外部类型通常留空）",
    }.get(kind, "目标ID")


def _reward_create_acus_label(kind: str) -> str:
    return {
        "角色": "从列表选择角色",
        "称号(Trophy)": "从列表选择称号",
        "姓名牌装饰(NamePlate)": "从列表选择姓名牌",
        "乐曲解锁(Music)": "从列表选择乐曲",
        "场景(Stage)": "从列表选择场景",
    }.get(kind, "")


def _parse_grid_int(el: ET.Element | None, tag: str, default: int) -> int:
    if el is None:
        return default
    t = (el.findtext(tag) or "").strip()
    return int(t) if t.isdigit() else default


def _reward_source_roots(acus_root: Path, idx: GameDataIndex | None = None) -> list[Path]:
    """
    Reward 参考源：
    - ACUS（用户自定义）
    - 仓库 A001（官方基础奖励，如企鹅/功能票等）
    - 已索引的游戏数据包（与 ddsImage 等合并范围一致）
    """
    roots: list[Path] = [acus_root]
    a001 = acus_root.parent / "A001"
    if a001.is_dir() and a001.resolve() not in {r.resolve() for r in roots}:
        roots.append(a001)
    if idx is not None:
        try:
            gr = Path(idx.game_root).resolve()
        except OSError:
            gr = None
        if gr is not None:
            seen = {r.resolve() for r in roots}
            for rel in idx.roots_scanned:
                try:
                    p = (gr / rel).resolve()
                    if p.is_dir() and p not in seen:
                        seen.add(p)
                        roots.append(p)
                except OSError:
                    continue
    return roots


def resolve_reward_xml(
    acus_root: Path, rid: int, idx: GameDataIndex | None = None
) -> Path | None:
    """
    定位 Reward.xml。优先 reward{9位零填充}；否则在 reward/*/Reward.xml 里按 name/id 匹配。
    """
    if rid < 0:
        return None
    for root in _reward_source_roots(acus_root, idx):
        p9 = root / "reward" / f"reward{rid:09d}" / "Reward.xml"
        if p9.exists():
            return p9
        alt = root / "reward" / f"reward{rid}" / "Reward.xml"
        if alt.exists():
            return alt
        reward_root = root / "reward"
        if not reward_root.is_dir():
            continue
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
            continue
    return None


def enrich_cell_from_reward_xml(
    acus_root: Path, cell: CellData, idx: GameDataIndex | None = None
) -> None:
    """根据 reward XML 补全 reward_kind、目标实体 id（reward_inner_id）与课题曲。"""
    rid = cell.reward_id
    if rid is None or rid < 0:
        return
    p = resolve_reward_xml(acus_root, rid, idx)
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
    acus_root: Path,
    area_xml: Path,
    game_index: GameDataIndex | None = None,
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
            enrich_cell_from_reward_xml(acus_root, c, game_index)
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
        stage_refs: list[RewardRef],
        music_refs: list[MusicRef],
        data: CellData,
        game_index: GameDataIndex | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("配置格子奖励")
        self.setModal(True)
        self._acus_root = acus_root
        self._game_index = game_index
        self._reward_refs = reward_refs
        self._chara_refs = chara_refs
        self._trophy_refs = trophy_refs
        self._nameplate_refs = nameplate_refs
        self._stage_refs = stage_refs
        self._music_refs = music_refs
        self._data = data
        self._pending_inner_match_id: int | None = None

        self.reward_mode = QComboBox()
        self.reward_mode.addItems(
            [
                "留空",
                "选择 ACUS 奖励",
                "角色",
                "称号(Trophy)",
                "姓名牌装饰(NamePlate)",
                "场景(Stage)",
                "手填奖励ID",
            ]
        )
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
        self.reward_kind.currentTextChanged.connect(self._sync_state)
        self.reward_inner_id = QLineEdit()
        self.reward_inner_id.setPlaceholderText("目标ID")
        self.inner_pick = QComboBox()
        self.inner_pick.activated.connect(self._on_acus_pick_activated)
        self._lbl_target_id = QLabel("目标ID")
        self._lbl_acus_pick = QLabel("从列表选择")

        self.music_mode = QComboBox()
        self.music_mode.addItems(["不配置乐曲", "选择乐曲"])
        self.music_mode.currentTextChanged.connect(self._sync_state)
        self.music_pick = QComboBox()
        self.music_pick.addItem("(请选择)")
        for m in music_refs:
            self.music_pick.addItem(f"{m.id} | {m.name}", m.id)

        self.warn_reward = QLabel("")
        self.warn_reward.setStyleSheet("color:#DC2626;")
        self.warn_music = QLabel("")
        self.warn_music.setStyleSheet("color:#DC2626;")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("奖励模式", self.reward_mode)
        form.addRow("ACUS奖励", self.reward_pick)
        form.addRow("奖励ID", self.reward_id)
        form.addRow("奖励显示名", wrap_name_input_with_preview(self.reward_name, parent=self))
        form.addRow("奖励类型", self.reward_kind)
        form.addRow(self._lbl_acus_pick, self.inner_pick)
        form.addRow(self._lbl_target_id, self.reward_inner_id)
        form.addRow("", self.warn_reward)
        form.addRow(QLabel(""), QLabel(""))
        form.addRow("课题曲", self.music_mode)
        form.addRow("乐曲", self.music_pick)
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
        glyph_warn = QLabel("提示：所有名称字段请尽量使用日语字库内字符；超出字库的汉字在游戏内可能无法显示。")
        glyph_warn.setStyleSheet("color:#B45309;")
        layout.addWidget(glyph_warn)
        layout.addLayout(btns)

        self._load_from_data()
        self._sync_state()

    def _load_from_data(self) -> None:
        d = self._data
        self._pending_inner_match_id = None
        if d.reward_id is None:
            self.reward_mode.setCurrentText("留空")
        else:
            idx = next((i for i, r in enumerate(self._reward_refs, start=1) if r.id == d.reward_id), -1)
            if idx > 0:
                self.reward_mode.setCurrentText("选择 ACUS 奖励")
                self.reward_pick.setCurrentIndex(idx)
            elif d.reward_kind in (
                "角色",
                "称号(Trophy)",
                "姓名牌装饰(NamePlate)",
                "场景(Stage)",
            ) and d.reward_inner_id is not None:
                mode_map = {
                    "角色": "角色",
                    "称号(Trophy)": "称号(Trophy)",
                    "姓名牌装饰(NamePlate)": "姓名牌装饰(NamePlate)",
                    "场景(Stage)": "场景(Stage)",
                }
                self.reward_mode.setCurrentText(mode_map.get(d.reward_kind, "手填奖励ID"))
                self.reward_name.setText(d.reward_name or "")
                self._pending_inner_match_id = d.reward_inner_id
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
            self.music_mode.setCurrentText("选择乐曲")
            idx = next((i for i, m in enumerate(self._music_refs, start=1) if m.id == d.music_id), -1)
            if idx > 0:
                self.music_pick.setCurrentIndex(idx)
            else:
                self.music_pick.addItem(
                    f"{d.music_id} | {d.music_name or f'Music{d.music_id}'}",
                    d.music_id,
                )
                self.music_pick.setCurrentIndex(self.music_pick.count() - 1)

    def _refs_for_reward_mode(self, rm: str) -> list[RewardRef]:
        if rm == "角色":
            return self._chara_refs
        if rm == "称号(Trophy)":
            return self._trophy_refs
        if rm == "姓名牌装饰(NamePlate)":
            return self._nameplate_refs
        if rm == "场景(Stage)":
            return self._stage_refs
        return []

    def _on_acus_pick_activated(self, index: int) -> None:
        if index <= 0:
            return
        rm = self.reward_mode.currentText()
        refs = self._refs_for_reward_mode(rm)
        if index - 1 >= len(refs):
            return
        self.reward_inner_id.setText(str(refs[index - 1].id))

    def _match_inner_pick(self, *, refs: list[RewardRef], tid: int | None) -> None:
        self.inner_pick.blockSignals(True)
        self.inner_pick.setCurrentIndex(0)
        if tid is not None:
            for i, x in enumerate(refs, start=1):
                if x.id == tid:
                    self.inner_pick.setCurrentIndex(i)
                    break
        self.inner_pick.blockSignals(False)

    def _sync_state(self) -> None:
        rm = self.reward_mode.currentText()
        rk = self.reward_kind.currentText()
        self.reward_pick.setEnabled(rm == "选择 ACUS 奖励")
        manual = rm == "手填奖励ID"
        typed = rm in {
            "角色",
            "称号(Trophy)",
            "姓名牌装饰(NamePlate)",
            "场景(Stage)",
        }
        self.reward_id.setEnabled(manual)
        self.reward_name.setEnabled(manual or typed)
        self.reward_kind.setEnabled(manual)
        need_target_id = typed or (manual and rk != "外部奖励ID")
        show_line = manual and need_target_id
        self.reward_inner_id.setVisible(show_line)
        self._lbl_target_id.setVisible(show_line)
        self.reward_inner_id.setEnabled(show_line)
        self.inner_pick.setEnabled(typed)

        self._lbl_target_id.setText(_target_id_field_label(reward_mode=rm, reward_kind=rk))
        self._lbl_acus_pick.setText(_acus_pick_label(rm))
        self._lbl_acus_pick.setVisible(typed)
        self.inner_pick.setVisible(typed)

        self.inner_pick.blockSignals(True)
        self.inner_pick.clear()
        self.inner_pick.addItem("(请选择)")
        refs = self._refs_for_reward_mode(rm)
        for x in refs:
            self.inner_pick.addItem(f"{x.id} | {x.name}")
        self.inner_pick.blockSignals(False)
        if typed:
            tid = self._pending_inner_match_id
            self._pending_inner_match_id = None
            self._match_inner_pick(refs=refs, tid=tid)

        if manual:
            if rk == "角色":
                self.reward_inner_id.setPlaceholderText("填写角色 ID（CharaData.name.id）")
            elif rk == "称号(Trophy)":
                self.reward_inner_id.setPlaceholderText("填写称号 ID（TrophyData.name.id）")
            elif rk == "姓名牌装饰(NamePlate)":
                self.reward_inner_id.setPlaceholderText("填写姓名牌 ID（NamePlateData.name.id）")
            else:
                self.reward_inner_id.setPlaceholderText("手填模式下选「外部奖励」时无需填写此项")
        else:
            self.reward_inner_id.setPlaceholderText("目标ID")

        mm = self.music_mode.currentText()
        self.music_pick.setEnabled(mm == "选择乐曲")

        if rm in {"手填奖励ID", "角色", "称号(Trophy)", "姓名牌装饰(NamePlate)", "场景(Stage)"}:
            self.warn_reward.setText(
                "⚠ 手填奖励 ID 或关联对象若与游戏数据不一致可能导致异常；对象类奖励请优先用列表选择。"
            )
        else:
            self.warn_reward.setText("")
        self.warn_music.setText("")

    def _on_ok(self) -> None:
        preserve_dt = self._data.display_type
        preserve_ct = self._data.cell_type
        out = CellData()
        prev_rid = self._data.reward_id

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
            enrich_cell_from_reward_xml(self._acus_root, out, self._game_index)
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
                    cap = _target_id_field_label(reward_mode="手填奖励ID", reward_kind=out.reward_kind)
                    QMessageBox.critical(self, "错误", f"该奖励类型需要填写「{cap}」")
                    return
                out.reward_inner_id = inner
        elif rm == "场景(Stage)":
            out.reward_kind = "场景(Stage)"
            out.reward_inner_id = self._resolve_inner_typed_only(self._stage_refs)
            if out.reward_inner_id is None:
                QMessageBox.critical(self, "错误", "请从列表选择场景")
                return
            ref = next(
                (x for x in self._stage_refs if x.id == out.reward_inner_id),
                None,
            )
            if ref is None:
                QMessageBox.critical(self, "错误", "场景列表异常，请重试")
                return
            out.reward_name = self.reward_name.text().strip() or ref.name
            if self._data.reward_kind == "场景(Stage)" and prev_rid is not None:
                out.reward_id = prev_rid
            else:
                out.reward_id = next_custom_reward_id(self._acus_root)
        else:
            if rm == "角色":
                out.reward_kind = "角色"
                out.reward_inner_id = self._resolve_inner_typed_only(self._chara_refs)
            elif rm == "称号(Trophy)":
                out.reward_kind = "称号(Trophy)"
                out.reward_inner_id = self._resolve_inner_typed_only(self._trophy_refs)
            else:
                out.reward_kind = "姓名牌装饰(NamePlate)"
                out.reward_inner_id = self._resolve_inner_typed_only(self._nameplate_refs)

            if out.reward_inner_id is None:
                cap = _target_id_field_label(reward_mode=rm, reward_kind="")
                QMessageBox.critical(self, "错误", f"请从列表选择有效的「{cap}」")
                return
            out.reward_name = self.reward_name.text().strip() or f"Reward{out.reward_inner_id}"
            out.reward_id = self._default_reward_id(out.reward_kind, out.reward_inner_id)

        mm = self.music_mode.currentText()
        if mm == "不配置乐曲":
            out.music_id = None
        else:
            mid = _combo_pick_id(self.music_pick)
            if mid is None:
                QMessageBox.critical(self, "错误", "请选择乐曲")
                return
            out.music_id = mid
            txt = self.music_pick.currentText()
            out.music_name = (
                txt.split("|", 1)[1].strip() if "|" in txt else f"Music{mid}"
            )

        self._data.reward_id = out.reward_id
        self._data.reward_name = out.reward_name
        self._data.reward_kind = out.reward_kind
        self._data.reward_inner_id = out.reward_inner_id
        self._data.music_id = out.music_id
        self._data.music_name = out.music_name
        self._data.display_type = preserve_dt
        self._data.cell_type = preserve_ct
        self.accept()

    def _resolve_inner_typed_only(self, refs: list[RewardRef]) -> int | None:
        pick = self.inner_pick.currentIndex()
        if pick > 0 and pick - 1 < len(refs):
            return refs[pick - 1].id
        return None

    def _default_reward_id(self, kind: str, inner_id: int) -> int:
        if kind == "角色":
            return 50_000_000 + inner_id
        if kind == "称号(Trophy)":
            return 70_000_000 + inner_id
        if kind == "姓名牌装饰(NamePlate)":
            return 30_000_000 + inner_id
        return inner_id


class AreaExtrasDialog(QDialog):
    def __init__(
        self,
        *,
        acus_root: Path,
        game_index: GameDataIndex | None,
        extras: MapAreaExtras,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("编辑区域参数(MapArea)")
        self.setModal(True)
        self._acus_root = acus_root
        self._game_index = game_index
        self._extras = extras

        self.bonus_id = QLineEdit(str(extras.bonus_id))
        self.bonus_str = QLineEdit(extras.bonus_str)
        self.counts = QLineEdit(",".join(str(x) for x in extras.shorten_counts[:8]))
        self.counts.setPlaceholderText("8个整数，用逗号分隔，例如 0,0,0,0,0,0,0,0")
        self.bonus_pick = QComboBox()
        self.bonus_pick.addItem("(手填 / 不使用 mapBonus)")
        self._bonus_refs: list[tuple[int, str, Path]] = []
        self._reload_mapbonus_refs(select_id=extras.bonus_id)
        self.bonus_pick.currentIndexChanged.connect(self._on_pick_bonus)
        self.new_bonus_btn = QPushButton("新建 mapBonus…")
        self.edit_bonus_btn = QPushButton("编辑当前 mapBonus…")
        self.new_bonus_btn.clicked.connect(self._on_new_bonus)
        self.edit_bonus_btn.clicked.connect(self._on_edit_bonus)
        pick_row = QHBoxLayout()
        pick_row.setContentsMargins(0, 0, 0, 0)
        pick_row.addWidget(self.bonus_pick, stretch=1)
        pick_row.addWidget(self.new_bonus_btn)
        pick_row.addWidget(self.edit_bonus_btn)
        pick_box = QWidget()
        pick_box.setLayout(pick_row)

        form = QFormLayout()
        form.addRow("选择现有 mapBonus", pick_box)
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
        glyph_warn = QLabel("提示：reward 名称/乐曲名称请尽量使用日语字库内字符；超出字库的汉字在游戏内可能无法显示。")
        glyph_warn.setStyleSheet("color:#B45309;")
        lay.addWidget(glyph_warn)
        lay.addLayout(btns)

    def _reload_mapbonus_refs(self, *, select_id: int | None = None) -> None:
        self.bonus_pick.blockSignals(True)
        self.bonus_pick.clear()
        self.bonus_pick.addItem("(手填 / 不使用 mapBonus)")
        self._bonus_refs.clear()
        for it in scan_map_bonuses(self._acus_root):
            self._bonus_refs.append((it.name.id, it.name.str, it.xml_path))
            self.bonus_pick.addItem(f"{it.name.id} | {it.name.str}")
        self.bonus_pick.blockSignals(False)
        if select_id is not None:
            for i, (bid, _bs, _xp) in enumerate(self._bonus_refs, start=1):
                if bid == select_id:
                    self.bonus_pick.setCurrentIndex(i)
                    break

    def _on_pick_bonus(self, idx: int) -> None:
        if idx <= 0 or idx - 1 >= len(self._bonus_refs):
            return
        bid, bstr, _ = self._bonus_refs[idx - 1]
        self.bonus_id.setText(str(bid))
        self.bonus_str.setText(bstr)

    def _on_new_bonus(self) -> None:
        dlg = MapBonusEditDialog(acus_root=self._acus_root, game_index=self._game_index, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted and dlg.result_name is not None:
            bid, bstr = dlg.result_name
            self._reload_mapbonus_refs(select_id=bid)
            self.bonus_id.setText(str(bid))
            self.bonus_str.setText(bstr)

    def _on_edit_bonus(self) -> None:
        bid = _safe_int(self.bonus_id.text())
        if bid is None:
            QMessageBox.critical(self, "错误", "mapBonusName.id 必须是整数，才能编辑。")
            return
        xp = self._acus_root / "mapBonus" / f"mapBonus{bid:08d}" / "MapBonus.xml"
        if not xp.is_file():
            QMessageBox.information(self, "提示", f"未找到：{xp}\n可先点击“新建 mapBonus…”。")
            return
        dlg = MapBonusEditDialog(
            acus_root=self._acus_root,
            game_index=self._game_index,
            xml_path=xp,
            parent=self,
        )
        if dlg.exec() == dlg.DialogCode.Accepted and dlg.result_name is not None:
            nbid, nbstr = dlg.result_name
            self._reload_mapbonus_refs(select_id=nbid)
            self.bonus_id.setText(str(nbid))
            self.bonus_str.setText(nbstr)

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
    def __init__(
        self,
        *,
        meta: MapInfoMeta,
        dds_refs: list[RewardRef],
        parent=None,
        show_dds: bool = True,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("编辑页面参数(Map.xml)")
        self.setModal(True)
        self._meta = meta
        self._dds_refs = dds_refs
        self._show_dds = show_dds

        hint = QLabel(
            "ddsMapName：地图格背景贴图，与 **Map.xml → MapDataAreaInfo** 绑定（每格可不同）。\n"
            "对应资源在 ACUS/ddsMap/ddsMapXXXXXXXX/DDSMap.xml；此处填其 name.id / name.str。"
            if show_dds
            else "pageIndex / indexInPage：地图分页九宫格位置；gauge / isHard 等写入 Map.xml 的 MapDataAreaInfo。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#374151; font-size: 12px;")

        self.page_index = QLineEdit(str(meta.page_index))
        self.index_in_page = QLineEdit(str(meta.index_in_page))
        self.required = QLineEdit(str(meta.required_achievement_count))
        self.gauge_id = QLineEdit(str(meta.gauge_id))
        self.gauge_str = QLineEdit(meta.gauge_str)
        self.dds_id = QLineEdit(str(meta.dds_id))
        self.dds_id.setReadOnly(True)
        self.dds_str = QLineEdit(meta.dds_str)
        self.dds_str.setReadOnly(True)
        self.dds_pick = QComboBox()
        self.dds_pick.addItem("(请选择 ddsMap)")
        for ref in dds_refs:
            self.dds_pick.addItem(f"{ref.id} | {ref.name}")
        self.dds_pick.activated.connect(self._on_dds_pick_activated)
        self.is_hard = QCheckBox("isHard = true")
        self.is_hard.setChecked(meta.is_hard)

        form = QFormLayout()
        form.addRow("", hint)
        form.addRow("pageIndex", self.page_index)
        form.addRow("indexInPage", self.index_in_page)
        form.addRow("requiredAchievementCount", self.required)
        form.addRow("gaugeName.id", self.gauge_id)
        form.addRow("gaugeName.str", self.gauge_str)
        if show_dds:
            form.addRow("选择 ddsMap", self.dds_pick)
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

    def _on_dds_pick_activated(self, index: int) -> None:
        if index <= 0:
            return
        ref = self._dds_refs[index - 1]
        self.dds_id.setText(str(ref.id))
        self.dds_str.setText(ref.name)

    def _on_ok(self) -> None:
        page_index = _safe_int(self.page_index.text())
        slot = _safe_int(self.index_in_page.text())
        required = _safe_int(self.required.text())
        gauge_id = _safe_int(self.gauge_id.text())
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
        self._meta.page_index = page_index
        self._meta.index_in_page = slot
        self._meta.required_achievement_count = required
        self._meta.gauge_id = gauge_id
        self._meta.gauge_str = self.gauge_str.text().strip() or "基本セット34"
        if self._show_dds:
            dds_id = _safe_int(self.dds_id.text())
            if dds_id is None:
                QMessageBox.critical(self, "错误", "ddsMapName.id 必须是整数")
                return
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
    _PICK_KINDS = frozenset(
        {
            "角色",
            "称号(Trophy)",
            "姓名牌装饰(NamePlate)",
            "乐曲解锁(Music)",
            "场景(Stage)",
        }
    )

    def __init__(
        self,
        *,
        default_id: int,
        music_refs: list[MusicRef],
        chara_refs: list[RewardRef],
        trophy_refs: list[RewardRef],
        nameplate_refs: list[RewardRef],
        stage_refs: list[RewardRef],
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("新建 Reward")
        self.setModal(True)
        self.result_cell: CellData | None = None
        self._music_refs = music_refs
        self._chara_refs = chara_refs
        self._trophy_refs = trophy_refs
        self._nameplate_refs = nameplate_refs
        self._stage_refs = stage_refs
        self._auto_name_enabled = True
        self._last_auto_name = ""

        self.reward_id = QLineEdit(str(default_id))
        self.reward_name = QLineEdit()
        self.reward_name.setPlaceholderText("可自动命名；手动修改后不再自动覆盖")
        self.reward_name.textEdited.connect(self._on_reward_name_edited)
        self.reward_kind = QComboBox()
        self.reward_kind.addItems(
            [
                "功能票(Ticket)",
                "外部奖励ID",
                "角色",
                "称号(Trophy)",
                "姓名牌装饰(NamePlate)",
                "场景(Stage)",
                "乐曲解锁(Music)",
            ]
        )
        self.reward_kind.currentTextChanged.connect(self._sync)
        self.inner_id = QLineEdit()
        self.inner_pick = QComboBox()
        self.inner_pick.activated.connect(self._on_inner_pick_activated)
        self.inner_id.textChanged.connect(self._on_inner_id_changed)
        self._lbl_acus_inner = QLabel("")
        self._lbl_target_inner = QLabel("目标ID")

        self.has_music = QCheckBox("有课题曲")
        self.music_mode = QComboBox()
        self.music_mode.addItems(["不配置乐曲", "选择乐曲"])
        self.music_pick = QComboBox()
        self.music_pick.addItem("(请选择)")
        for m in music_refs:
            self.music_pick.addItem(f"{m.id} | {m.name}", m.id)
        self.has_music.toggled.connect(self._sync)
        self.music_mode.currentTextChanged.connect(self._sync)
        self.music_pick.activated.connect(self._on_music_pick_activated)

        form = QFormLayout()
        form.addRow("reward.id", self.reward_id)
        form.addRow("reward.str", wrap_name_input_with_preview(self.reward_name, parent=self))
        form.addRow("类型", self.reward_kind)
        form.addRow(self._lbl_acus_inner, self.inner_pick)
        form.addRow(self._lbl_target_inner, self.inner_id)
        form.addRow("", self.has_music)
        form.addRow("课题曲", self.music_mode)
        form.addRow("乐曲", self.music_pick)

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

    def _inner_refs_for_kind(self, kind: str) -> list[RewardRef]:
        if kind == "角色":
            return self._chara_refs
        if kind == "称号(Trophy)":
            return self._trophy_refs
        if kind == "姓名牌装饰(NamePlate)":
            return self._nameplate_refs
        if kind == "乐曲解锁(Music)":
            return [RewardRef(m.id, m.name) for m in self._music_refs]
        if kind == "场景(Stage)":
            return self._stage_refs
        return []

    def _on_inner_pick_activated(self, index: int) -> None:
        if index <= 0:
            return
        kind = self.reward_kind.currentText()
        if kind not in self._PICK_KINDS:
            return
        refs = self._inner_refs_for_kind(kind)
        if index - 1 >= len(refs):
            return
        self.inner_id.setText(str(refs[index - 1].id))
        self._apply_auto_reward_name()

    def _on_inner_id_changed(self, _text: str) -> None:
        self._apply_auto_reward_name()

    def _on_music_pick_activated(self, _index: int) -> None:
        self._apply_auto_reward_name()

    def _on_reward_name_edited(self, _text: str) -> None:
        self._auto_name_enabled = False

    def _current_pick_inner_id(self, kind: str) -> int | None:
        if kind not in self._PICK_KINDS:
            return _safe_int(self.inner_id.text())
        refs = self._inner_refs_for_kind(kind)
        pick = self.inner_pick.currentIndex()
        if pick > 0 and pick - 1 < len(refs):
            return refs[pick - 1].id
        return _safe_int(self.inner_id.text())

    def _name_from_refs_or_id(self, kind: str, target_id: int | None) -> str:
        if target_id is None:
            return ""
        refs = self._inner_refs_for_kind(kind)
        for x in refs:
            if x.id == target_id:
                return x.name
        return str(target_id)

    def _build_auto_reward_name(self) -> str:
        kind = self.reward_kind.currentText()
        if kind == "外部奖励ID":
            rid = _safe_int(self.reward_id.text())
            return f"reward+{rid}" if rid is not None else "reward"

        target_id = self._current_pick_inner_id(kind)
        target_name = self._name_from_refs_or_id(kind, target_id)
        if kind == "角色":
            return f"character+{target_name or 'Unknown'}"
        if kind == "称号(Trophy)":
            return f"trophy+{target_name or 'Unknown'}"
        if kind == "姓名牌装饰(NamePlate)":
            return f"nameplate+{target_name or 'Unknown'}"
        if kind == "乐曲解锁(Music)":
            return f"music+{target_name or 'Unknown'}"
        if kind == "场景(Stage)":
            return f"stage+{target_name or 'Unknown'}"
        if kind == "功能票(Ticket)":
            return f"ticket+{target_name or 'Unknown'}"
        return f"reward+{target_name or 'Unknown'}"

    def _apply_auto_reward_name(self) -> None:
        auto = self._build_auto_reward_name()
        if not auto:
            return
        if self._auto_name_enabled or self.reward_name.text().strip() == self._last_auto_name:
            self.reward_name.setText(auto)
            self._last_auto_name = auto
            self._auto_name_enabled = True

    def _match_inner_pick(self, refs: list[RewardRef]) -> None:
        tid = _safe_int(self.inner_id.text())
        self.inner_pick.blockSignals(True)
        self.inner_pick.setCurrentIndex(0)
        if tid is not None:
            for i, x in enumerate(refs, start=1):
                if x.id == tid:
                    self.inner_pick.setCurrentIndex(i)
                    break
        self.inner_pick.blockSignals(False)

    def _sync(self) -> None:
        kind = self.reward_kind.currentText()
        refs = self._inner_refs_for_kind(kind)
        show_pick = kind in self._PICK_KINDS and len(refs) > 0
        self._lbl_acus_inner.setText(_reward_create_acus_label(kind) if show_pick else "")
        self._lbl_acus_inner.setVisible(show_pick)
        self.inner_pick.setVisible(show_pick)
        self.inner_pick.blockSignals(True)
        self.inner_pick.clear()
        self.inner_pick.addItem("(请选择)")
        for x in refs:
            self.inner_pick.addItem(f"{x.id} | {x.name}")
        self.inner_pick.blockSignals(False)
        if show_pick:
            self._match_inner_pick(refs)

        ticket_only = kind == "功能票(Ticket)"
        self._lbl_target_inner.setVisible(ticket_only)
        self.inner_id.setVisible(ticket_only)
        self._lbl_target_inner.setText(_reward_create_kind_target_label(kind))
        self.inner_id.setEnabled(ticket_only)
        if kind == "外部奖励ID":
            self.inner_id.setPlaceholderText("外部奖励通常无需填写")
        elif kind == "功能票(Ticket)":
            self.inner_id.setPlaceholderText("填写功能票 ID（TicketData.name.id）")
        else:
            self.inner_id.setPlaceholderText("目标ID")

        on = self.has_music.isChecked()
        self.music_mode.setEnabled(on)
        pick_on = on and self.music_mode.currentText() == "选择乐曲"
        self.music_pick.setEnabled(pick_on)
        if not on:
            self.music_pick.setCurrentIndex(0)
        self._apply_auto_reward_name()

    def _on_ok(self) -> None:
        rid = _safe_int(self.reward_id.text())
        if rid is None or rid < 0 or str(rid)[0] != "7":
            QMessageBox.critical(self, "错误", "reward.id 必须是非负整数，且首位为 7")
            return
        name = self.reward_name.text().strip() or f"Reward{rid}"
        kind = self.reward_kind.currentText()
        inner: int | None = None
        if kind == "外部奖励ID":
            inner = None
        elif kind == "功能票(Ticket)":
            inner = _safe_int(self.inner_id.text())
            if inner is None:
                QMessageBox.critical(self, "错误", "请填写有效的功能票 ID")
                return
        else:
            refs = self._inner_refs_for_kind(kind)
            pick = self.inner_pick.currentIndex()
            if pick <= 0 or pick - 1 >= len(refs):
                cap = _reward_create_kind_target_label(kind)
                QMessageBox.critical(self, "错误", f"请从列表选择「{cap}」")
                return
            inner = refs[pick - 1].id
        c = CellData(reward_id=rid, reward_name=name, reward_kind=kind, reward_inner_id=inner)
        if self.has_music.isChecked():
            if self.music_mode.currentText() != "选择乐曲":
                pass
            else:
                mid = _combo_pick_id(self.music_pick)
                if mid is None:
                    QMessageBox.critical(self, "错误", "请选择乐曲")
                    return
                c.music_id = mid
                txt = self.music_pick.currentText()
                c.music_name = (
                    txt.split("|", 1)[1].strip() if "|" in txt else f"Music{mid}"
                )
        self.result_cell = c
        self.accept()


def load_reward_refs(
    acus_root: Path, idx: GameDataIndex | None = None
) -> list[RewardRef]:
    refs: list[RewardRef] = []
    seen: set[int] = set()
    for root in _reward_source_roots(acus_root, idx):
        for p in root.glob("reward/**/Reward.xml"):
            try:
                r = ET.parse(p).getroot()
                rid = _safe_int(r.findtext("name/id") or "")
                name = (r.findtext("name/str") or "").strip()
                if rid is None or rid in seen:
                    continue
                if root != acus_root:
                    allow_a001 = False
                    for sub in r.findall(".//RewardSubstanceData"):
                        t = _safe_int(sub.findtext("type") or "")
                        if t == 1:
                            allow_a001 = True
                            break
                        if t == 0:
                            gp = _safe_int(sub.findtext("gamePoint/gamePoint") or "")
                            if gp is not None and gp > 0:
                                allow_a001 = True
                                break
                    if not allow_a001:
                        continue
                c = CellData(reward_id=rid, reward_name=name or f"Reward{rid}")
                enrich_cell_from_reward_xml(acus_root, c, idx)
                k = _kind_label(c.reward_kind)
                label = f"[{k}] {c.reward_name or f'Reward{rid}'}"
                if c.reward_inner_id is not None and c.reward_inner_id >= 0:
                    tid_lbl = {
                        "角色": "角色ID",
                        "称号(Trophy)": "称号ID",
                        "姓名牌装饰(NamePlate)": "姓名牌ID",
                        "乐曲解锁(Music)": "乐曲ID",
                        "功能票(Ticket)": "功能票ID",
                        "场景(Stage)": "场景ID",
                    }.get(c.reward_kind, "目标ID")
                    label += f" ({tid_lbl}:{c.reward_inner_id})"
                refs.append(RewardRef(rid, c.reward_name or f"Reward{rid}", label))
                seen.add(rid)
            except Exception:
                continue
    return sorted(refs, key=lambda x: x.id)


def load_music_refs(acus_root: Path) -> list[MusicRef]:
    refs: list[MusicRef] = []
    for p in acus_root.glob("music/**/Music.xml"):
        try:
            r = ET.parse(p).getroot()
            mid = _safe_int(r.findtext("name/id") or "")
            name = (r.findtext("name/str") or "").strip()
            if mid is not None:
                refs.append(MusicRef(mid, name or f"Music{mid}"))
        except Exception:
            continue
    return sorted(refs, key=lambda x: x.id)


def load_chara_refs(
    acus_root: Path, idx: GameDataIndex | None = None
) -> list[RewardRef]:
    return [
        RewardRef(i, n, "")
        for i, n in merged_chara_pairs(acus_root, idx)
    ]


def load_nameplate_refs(
    acus_root: Path, idx: GameDataIndex | None = None
) -> list[RewardRef]:
    return [
        RewardRef(i, n, "")
        for i, n in merged_nameplate_pairs(acus_root, idx)
    ]


def load_trophy_refs(
    acus_root: Path, idx: GameDataIndex | None = None
) -> list[RewardRef]:
    return [
        RewardRef(i, n, "")
        for i, n in merged_trophy_pairs(acus_root, idx)
    ]


def load_dds_map_refs(acus_root: Path) -> list[RewardRef]:
    """ddsMap/**/DDSMap.xml（或 DdsMap.xml）→ Map.xml 里 MapDataAreaInfo.ddsMapName 引用。"""
    seen: set[int] = set()
    refs: list[RewardRef] = []
    paths: set[Path] = set()
    for pat in ("ddsMap/**/DDSMap.xml", "ddsMap/**/DdsMap.xml"):
        for p in acus_root.glob(pat):
            paths.add(p)
    for p in sorted(paths):
        try:
            r = ET.parse(p).getroot()
            did = _safe_int(r.findtext("name/id") or "")
            dstr = (r.findtext("name/str") or "").strip()
            if did is None or did in seen:
                continue
            seen.add(did)
            refs.append(RewardRef(did, dstr or f"DdsMap{did}", ""))
        except Exception:
            continue
    return sorted(refs, key=lambda x: x.id)


def next_custom_dds_map_id(acus_root: Path) -> int:
    """自定义 ddsMap：与 Reward 类似，使用首位为 7 的 id（70000000 起递增）。"""
    max_id = 69999999
    paths: set[Path] = set()
    for pat in ("ddsMap/**/DDSMap.xml", "ddsMap/**/DdsMap.xml"):
        for p in acus_root.glob(pat):
            paths.add(p)
    for p in paths:
        try:
            r = ET.parse(p).getroot()
            did = _safe_int(r.findtext("name/id") or "")
            if did is not None and str(did).startswith("7"):
                max_id = max(max_id, did)
        except Exception:
            continue
    return max_id + 1


MAP_DDS_WIDTH = 1220
MAP_DDS_HEIGHT = 680


def prepare_map_background_rgba(*, source_image: Path) -> Image.Image:
    """将任意比例图源缩放并居中裁切为地图背景贴图尺寸（BC3 编码前）。"""
    with Image.open(source_image) as im:
        im.seek(0)
        im.load()
        rgba = im.convert("RGBA")
    return ImageOps.fit(rgba, (MAP_DDS_WIDTH, MAP_DDS_HEIGHT), method=Image.Resampling.LANCZOS)


class DdsMapCreateDialog(QDialog):
    """从位图生成 ddsMap 目录（BC3 DDS + DDSMap.xml），供 Map.xml ddsMapName 引用。"""

    def __init__(self, *, acus_root: Path, tool_path: Path | None, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("新建地图贴图 (ddsMap)")
        self.setModal(True)
        self._acus_root = acus_root
        self._tool = tool_path
        self.created_id = -1

        self._alloc_id = next_custom_dds_map_id(acus_root)
        self.dds_id_show = QLineEdit(str(self._alloc_id))
        self.dds_id_show.setReadOnly(True)
        self.name = QLineEdit()
        self.name.setPlaceholderText("显示名（写入 DDSMap name.str）")
        self.image_path = QLineEdit()
        self.image_path.setPlaceholderText("选择图片或 DDS（DDS 将直接导入，需为 BC3）…")
        br = QPushButton("浏览…")
        br.clicked.connect(self._pick_image)

        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(self.image_path, stretch=1)
        hl.addWidget(br)

        hint = QLabel(
            f"贴图将自动缩放并裁切为 **{MAP_DDS_WIDTH}×{MAP_DDS_HEIGHT}** 像素（与游戏地图格背景常见规格一致），再编码为 BC3 DDS。\n"
            "若直接上传 `.dds` 则不会重编码，会直接写入（必须是 BC3/DXT5）。\n"
            f"ID 自动分配为 **7xxxxxxx**，与官方小包 id 错开。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#374151; font-size: 12px;")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("", hint)
        form.addRow("ddsMap id", self.dds_id_show)
        form.addRow("显示名", wrap_name_input_with_preview(self.name, parent=self))
        form.addRow("源图片", row)

        ok = QPushButton("生成并写入 ACUS")
        ok.clicked.connect(self._run)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addLayout(btns)

    def _pick_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择地图背景图",
            "",
            "Image or DDS (*.dds *.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;All (*)",
        )
        if path:
            self.image_path.setText(path)

    def _run(self) -> None:
        mid = self._alloc_id
        src = Path(self.image_path.text().strip()).expanduser()
        if not src.is_file():
            QMessageBox.critical(self, "错误", "请选择有效的输入文件")
            return
        disp = self.name.text().strip() or f"MapTex{mid}"
        dds_basename = f"CHU_MAP_{mid:08d}.dds"
        ddir = self._acus_root / "ddsMap" / f"ddsMap{mid:08d}"
        try:
            ddir.mkdir(parents=True, exist_ok=True)
            out_dds = ddir / dds_basename
            if src.suffix.lower() == ".dds":
                ingest_to_bc3_dds(tool_path=self._tool, input_path=src, output_dds=out_dds)
            else:
                try:
                    img = prepare_map_background_rgba(source_image=src)
                except UnidentifiedImageError as e:
                    QMessageBox.critical(self, "错误", f"无法识别图片：{e}")
                    return
                except OSError as e:
                    QMessageBox.critical(self, "错误", f"无法读取图片：{e}")
                    return
                with tempfile.TemporaryDirectory() as td:
                    tp = Path(td) / "map_bg.png"
                    img.save(tp, "PNG")
                    ok, dds_msg = run_bc3_jobs_with_progress(
                        parent=self,
                        tool_path=self._tool,
                        jobs=[(tp, out_dds)],
                        title="正在生成地图 DDS",
                    )
                    if not ok:
                        raise DdsToolError(dds_msg)
            write_ddsmap_xml(
                out_dir=self._acus_root,
                dds_map_id=mid,
                name_str=disp,
                dds_basename=dds_basename,
            )
        except DdsToolError as e:
            QMessageBox.critical(self, "DDS 转换失败", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))
            return
        self.created_id = mid
        QMessageBox.information(
            self,
            "完成",
            f"已写入 {ddir.name}/（id={mid}）\n可在编辑地图格子弹窗顶部的「ddsMap 背景贴图」中选择该 ddsMap。",
        )
        self.accept()


def next_custom_reward_id(acus_root: Path) -> int:
    max_id = 700000000
    for p in acus_root.glob("reward/**/Reward.xml"):
        try:
            r = ET.parse(p).getroot()
            rid = _safe_int(r.findtext("name/id") or "")
            if rid is not None and str(rid).startswith("7"):
                max_id = max(max_id, rid)
        except Exception:
            continue
    return max_id + 1


def reward_dialog_bundle(
    acus_root: Path,
    game_index: GameDataIndex | None = None,
) -> tuple[
    list[MusicRef],
    list[RewardRef],
    list[RewardRef],
    list[RewardRef],
    list[RewardRef],
    int,
]:
    return (
        _merged_music_refs(acus_root, game_index),
        load_chara_refs(acus_root, game_index),
        load_trophy_refs(acus_root, game_index),
        load_nameplate_refs(acus_root, game_index),
        _merged_stage_reward_refs(acus_root, game_index),
        next_custom_reward_id(acus_root),
    )


def ensure_reward_xml(
    acus_root: Path, cell: CellData, idx: GameDataIndex | None = None
) -> None:
    if cell.reward_id is None:
        return
    rid = cell.reward_id
    if resolve_reward_xml(acus_root, rid, idx) is not None:
        return
    rdir = acus_root / "reward" / f"reward{rid:09d}"
    rdir.mkdir(parents=True, exist_ok=True)

    kind = cell.reward_kind
    inner = cell.reward_inner_id if cell.reward_inner_id is not None else -1
    ticket_id = inner if kind == "功能票(Ticket)" else -1
    chara_id = inner if kind == "角色" else -1
    trophy_id = inner if kind == "称号(Trophy)" else -1
    nameplate_id = inner if kind == "姓名牌装饰(NamePlate)" else -1
    music_id = cell.music_id if cell.music_id is not None else -1
    music_name = cell.music_name if (cell.music_id is not None and cell.music_name) else ("Invalid" if music_id == -1 else f"Music{music_id}")
    reward_type = 0
    stage_id = -1
    stage_str = "Invalid"
    if kind == "功能票(Ticket)":
        reward_type = 1
    elif kind == "角色":
        reward_type = 3
    elif kind == "称号(Trophy)":
        reward_type = 2
    elif kind == "姓名牌装饰(NamePlate)":
        reward_type = 5
    elif kind == "乐曲解锁(Music)":
        reward_type = 6
        music_id = inner if inner >= 0 else -1
        music_name = f"Music{music_id}" if music_id != -1 else "Invalid"
    elif kind == "场景(Stage)":
        reward_type = 13
        stage_id = inner if inner >= 0 else -1
        st_raw = (cell.reward_name or "").strip()
        stage_str = st_raw if st_raw else (f"Stage{stage_id}" if stage_id >= 0 else "Invalid")

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
        <stage><stageName><id>{stage_id}</id><str>{stage_str}</str><data /></stageName></stage>
      </RewardSubstanceData>
    </list>
  </substances>
</RewardData>
"""
    (rdir / "Reward.xml").write_text(xml, encoding="utf-8")


def ensure_points_reward_xml(
    acus_root: Path,
    *,
    reward_id: int,
    reward_name: str = "3000 Points",
    points: int = 3000,
    idx: GameDataIndex | None = None,
) -> None:
    """
    保证存在一个纯 Points 类型 Reward（type=0, gamePoint=points）。
    用于 MapArea 路线中的固定金币奖励节点。
    """
    if reward_id < 0:
        return
    if resolve_reward_xml(acus_root, reward_id, idx) is not None:
        return
    rdir = acus_root / "reward" / f"reward{reward_id:09d}"
    rdir.mkdir(parents=True, exist_ok=True)
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<RewardData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>reward{reward_id:09d}</dataName>
  <name><id>{reward_id}</id><str>{reward_name}</str><data /></name>
  <substances>
    <list>
      <RewardSubstanceData>
        <type>0</type>
        <gamePoint><gamePoint>{int(points)}</gamePoint></gamePoint>
        <ticket><ticketName><id>-1</id><str>Invalid</str><data /></ticketName></ticket>
        <trophy><trophyName><id>-1</id><str>Invalid</str><data /></trophyName></trophy>
        <chara><charaName><id>-1</id><str>Invalid</str><data /></charaName></chara>
        <skillSeed><skillSeedName><id>-1</id><str>Invalid</str><data /></skillSeedName><skillSeedCount>1</skillSeedCount></skillSeed>
        <namePlate><namePlateName><id>-1</id><str>Invalid</str><data /></namePlateName></namePlate>
        <music><musicName><id>-1</id><str>Invalid</str><data /></musicName></music>
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
    (rdir / "Reward.xml").write_text(xml, encoding="utf-8")


class MapAddDialog(QDialog):
    def __init__(
        self,
        *,
        acus_root: Path,
        tool_path: Path | None = None,
        parent=None,
        edit_map_xml: Path | None = None,
        game_index: GameDataIndex | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self._edit_mode = edit_map_xml is not None
        self.setWindowTitle("编辑地图" if self._edit_mode else "新增地图")
        self.setModal(True)
        self.resize(980, 700)
        self._acus_root = acus_root
        self._tool = tool_path
        self._game_index = game_index
        self._reward_refs = load_reward_refs(acus_root, game_index)
        self._chara_refs = load_chara_refs(acus_root, game_index)
        self._trophy_refs = load_trophy_refs(acus_root, game_index)
        self._nameplate_refs = load_nameplate_refs(acus_root, game_index)
        self._music_refs = _merged_music_refs(acus_root, game_index)
        self._stage_refs = _merged_stage_reward_refs(acus_root, game_index)
        self._dds_map_refs = _merged_dds_map_reward_refs(acus_root, game_index)
        self._page_area_slots: list[list[int | None]] = []
        self._chara_name_by_id = {x.id: x.name for x in self._chara_refs}
        self._trophy_name_by_id = {x.id: x.name for x in self._trophy_refs}
        self._nameplate_name_by_id = {x.id: x.name for x in self._nameplate_refs}
        self._stage_name_by_id = {x.id: x.name for x in self._stage_refs}
        self._music_name_by_id = {x.id: x.name for x in self._music_refs}
        # UI thumbs (只读展示用，不影响保存逻辑)
        self._static_ui_root = Path(__file__).resolve().parents[1] / "static" / "UI"
        self._trophy_ui_dir = self._static_ui_root / "trophy"
        self._course_music_label_pm = QPixmap(str(self._static_ui_root / "map" / "CourseMusic.png"))
        self._trophy_thumb_pm_cache: dict[int, QPixmap] = {}
        self._chara_back_pm_cache: dict[int, QPixmap] = {}
        self._chara_head_pm_cache: dict[int, QPixmap] = {}
        self._penguin_icon_pm_cache: dict[int, QPixmap] = {}
        self._nameplate_img_path_by_id: dict[int, Path] = {}
        self._nameplate_pm_cache: dict[int, QPixmap] = {}
        self._trophy_rare_type_by_id = self._scan_trophy_rare_type_by_id(acus_root)
        self._penguin_ui_dir = self._static_ui_root / "penguin"
        self._nameplate_img_path_by_id = self._scan_nameplate_image_paths(acus_root)
        self._area_cells: list[list[CellData]] = []
        self._area_ids: list[int] = []
        self._area_names: list[str] = []
        self._area_extras: list[MapAreaExtras] = []
        # Map.xml infos 层：每页显示的奖励/乐曲（不是跑图节点）
        self._area_info_cells: list[CellData] = []
        self._area_info_meta: list[MapInfoMeta] = []
        # 编辑模式：每格对应 MapArea.xml 里的游戏 index（非 0..8）；与 _area_cells 对齐
        self._area_grid_indices: list[list[int | None]] = []
        self._current_map_id = 0

        self.map_id = FluentLineEdit(self)
        self.map_id.setPlaceholderText("例如 99000001（8位推荐）")
        self.map_name = FluentLineEdit(self)
        self.map_name.setPlaceholderText("可不填，默认 Map{id}")

        self.create_unlock_event = QCheckBox("同时生成地图解锁事件（event/ + EventSort.xml）")
        self.create_unlock_event.setChecked(True)
        if self._edit_mode:
            self.create_unlock_event.setVisible(False)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._on_page_tab_close_requested)
        self.tabs.currentChanged.connect(self._on_page_tab_current_changed)
        self._page_tab_plus_index = -1
        self._page_tab_suppress = False

        top = QFormLayout()
        top.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        top.addRow("Map ID", self.map_id)
        top.addRow("Map 名称", wrap_name_input_with_preview(self.map_name, parent=self))
        top.addRow("", self.create_unlock_event)

        ok = QPushButton("保存修改" if self._edit_mode else "生成 Map + MapArea + Reward (+解锁事件)")
        ok.clicked.connect(self._generate)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
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
            # 解锁事件 ID 不再手填；若勾选则始终自动分配。

    def _create_ddsmap_and_refresh(self) -> int:
        """打开新建 ddsMap 对话框；成功后刷新 ddsMap 引用并返回 created_id。"""
        if self._tool is None and not quicktex_available():
            QMessageBox.critical(
                self,
                "无法生成 DDS",
                "生成地图贴图需要 quicktex 或 compressonatorcli：\n"
                "• pip install quicktex\n"
                "• 或在【设置】中配置 compressonatorcli",
            )
            return -1
        dlg = DdsMapCreateDialog(acus_root=self._acus_root, tool_path=self._tool, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.created_id >= 0:
            self._dds_map_refs = _merged_dds_map_reward_refs(
                self._acus_root, self._game_index
            )
            return dlg.created_id
        return -1

    def _on_page_tab_current_changed(self, idx: int) -> None:
        if self._page_tab_suppress:
            return
        if idx == self._page_tab_plus_index:
            self._add_page()

    def _on_page_tab_close_requested(self, idx: int) -> None:
        if self._page_tab_suppress:
            return
        if idx == self._page_tab_plus_index:
            return
        if idx < 0:
            return
        self.tabs.setCurrentIndex(idx)
        self._remove_current_page()

    @staticmethod
    def _scan_trophy_rare_type_by_id(acus_root: Path) -> dict[int, int | None]:
        """trophy/**/Trophy.xml → trophyId -> rareType（用于 UI 缩略图分组）。"""
        out: dict[int, int | None] = {}
        for p in acus_root.glob("trophy/**/Trophy.xml"):
            try:
                r = ET.parse(p).getroot()
                tid = _safe_int(r.findtext("name/id") or "")
                if tid is None:
                    continue
                rare_raw = (r.findtext("rareType") or "").strip()
                rare_type = int(rare_raw) if rare_raw.isdigit() else None
                out[tid] = rare_type
            except Exception:
                continue
        return out

    @staticmethod
    def _scan_nameplate_image_paths(acus_root: Path) -> dict[int, Path]:
        """
        namePlate/**/NamePlate.xml -> nameplateId -> image/path 绝对路径。
        用于地图格子里显示名牌缩略图（比只显示文字更符合你的要求）。
        """
        out: dict[int, Path] = {}
        for p in acus_root.glob("namePlate/**/NamePlate.xml"):
            try:
                r = ET.parse(p).getroot()
                nid = _safe_int(r.findtext("name/id") or "")
                if nid is None:
                    continue
                img_rel = (r.findtext("image/path") or "").strip()
                if not img_rel:
                    continue
                out[nid] = p.parent / img_rel
            except Exception:
                continue
        return out

    def _get_nameplate_pixmap(self, nid: int) -> QPixmap | None:
        if nid in self._nameplate_pm_cache:
            pm = self._nameplate_pm_cache.get(nid)
            return None if pm is None or pm.isNull() else pm

        p = self._nameplate_img_path_by_id.get(nid)
        if p is None or not p.is_file():
            self._nameplate_pm_cache[nid] = QPixmap()
            return None

        try:
            if p.suffix.lower() == ".dds":
                pm = dds_to_pixmap(
                    acus_root=self._acus_root,
                    compressonatorcli_path=self._tool,
                    dds_path=p,
                    max_w=220,
                    max_h=220,
                    restrict=True,
                )
            else:
                pm = QPixmap(str(p))
                if pm is not None and not pm.isNull():
                    pm = pm.scaled(
                        220,
                        220,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
        except Exception:
            pm = None

        if pm is None or pm.isNull():
            self._nameplate_pm_cache[nid] = QPixmap()
            return None

        self._nameplate_pm_cache[nid] = pm
        return pm

    def _candidate_ddsmap_dds_files(self, dds_map_id: int) -> list[Path]:
        """收集 ACUS + 游戏资源中该 ddsMap 目录下的 .dds 文件（不读 image/path）。"""
        out: list[Path] = []
        seen: set[Path] = set()

        def _add_file(p: Path) -> None:
            try:
                rp = p.resolve()
            except Exception:
                rp = p
            if rp in seen:
                return
            seen.add(rp)
            out.append(rp)

        candidate_dirs: list[Path] = [self._acus_root / "ddsMap" / f"ddsMap{dds_map_id:08d}"]
        for root in self._game_resource_roots_for_dds_preview():
            candidate_dirs.append(root / "ddsMap" / f"ddsMap{dds_map_id:08d}")

        for ddir in candidate_dirs:
            if not ddir.is_dir():
                continue
            for p in sorted(ddir.glob("*.dds")):
                _add_file(p)
        return out

    def _game_resource_roots_for_dds_preview(self) -> list[Path]:
        """
        实时枚举游戏资源根（不依赖缓存索引）：
        - data/A000/opt 及其所有子目录
        - bin/option 下所有子目录（A001/A010/...）
        """
        out: list[Path] = []
        seen: set[Path] = set()

        gr_raw = ""
        if self._game_index is not None:
            gr_raw = str(getattr(self._game_index, "game_root", "") or "").strip()
        if not gr_raw:
            return out
        try:
            gr = Path(gr_raw).expanduser().resolve()
        except Exception:
            return out
        if not gr.is_dir():
            return out

        def _add(p: Path) -> None:
            try:
                rp = p.resolve()
            except Exception:
                rp = p
            if rp in seen:
                return
            seen.add(rp)
            out.append(rp)

        # data/A000/opt (and case variants)
        for data_name in ("data", "Data"):
            for a_name in ("a000", "A000"):
                opt_base = gr / data_name / a_name / "opt"
                if not opt_base.is_dir():
                    continue
                _add(opt_base)
                try:
                    for child in sorted(opt_base.iterdir()):
                        if child.is_dir():
                            _add(child)
                except Exception:
                    pass

        # bin/option/* all dirs
        for bin_name in ("bin", "Bin"):
            bo = gr / bin_name / "option"
            if not bo.is_dir():
                continue
            try:
                for child in sorted(bo.iterdir()):
                    if child.is_dir():
                        _add(child)
            except Exception:
                pass
        return out

    def _warm_game_dds_preview_cache(self) -> None:
        """把游戏资源 roots 下 ddsMap 的 dds 全量转一次预览缓存 (.cache/dds_preview/*.png)。"""
        roots = self._game_resource_roots_for_dds_preview()
        if not roots:
            return
        all_dds: list[Path] = []
        for root in roots:
            dds_root = root / "ddsMap"
            if not dds_root.is_dir():
                continue
            for p in dds_root.glob("**/*.dds"):
                all_dds.append(p)
        if not all_dds:
            return

        # 去重，避免同名资源在多个 roots 重复处理造成卡顿
        uniq = sorted({x.resolve() for x in all_dds})
        prog = QProgressDialog("正在缓存游戏 ddsMap 预览…", "取消", 0, len(uniq), self)
        prog.setWindowTitle("读取游戏资源")
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        prog.setValue(0)
        QApplication.processEvents()

        for i, p in enumerate(uniq, start=1):
            if prog.wasCanceled():
                break
            prog.setLabelText(f"正在处理 {p.name} ({i}/{len(uniq)})")
            try:
                _ = dds_to_pixmap(
                    acus_root=self._acus_root,
                    compressonatorcli_path=self._tool,
                    dds_path=p,
                    max_w=8,
                    max_h=8,
                    restrict=True,
                )
            except Exception:
                pass
            prog.setValue(i)
            QApplication.processEvents()
        prog.close()

    def _get_chara_back_head_pixmaps(
        self, chara_id: int
    ) -> tuple[QPixmap | None, QPixmap | None]:
        """
        角色奖励缩略图：
        - 仅头像：ddsFile2（preview 三张中的第 3 张 / 文件名常以 _02 结尾）
        """
        if chara_id in self._chara_back_pm_cache or chara_id in self._chara_head_pm_cache:
            return (
                self._chara_back_pm_cache.get(chara_id),
                self._chara_head_pm_cache.get(chara_id),
            )

        back_pm: QPixmap | None = None
        head_pm: QPixmap | None = None
        try:
            dds_xml = (
                self._acus_root
                / "ddsImage"
                / f"ddsImage{chara_id:06d}"
                / "DDSImage.xml"
            )
            if dds_xml.exists():
                root = ET.parse(dds_xml).getroot()
                d2 = (root.findtext("ddsFile2/path") or "").strip()
                tool = self._tool
                if d2:
                    p2 = dds_xml.parent / d2
                    head_pm = dds_to_pixmap(
                        acus_root=self._acus_root,
                        compressonatorcli_path=tool,
                        dds_path=p2,
                        max_w=220,
                        max_h=220,
                        restrict=True,
                    )
        except Exception:
            back_pm, head_pm = None, None

        # 用 None 也缓存，避免重复解码
        self._chara_back_pm_cache[chara_id] = back_pm if back_pm is not None else QPixmap()
        self._chara_head_pm_cache[chara_id] = head_pm if head_pm is not None else QPixmap()
        return back_pm, head_pm

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
        self._page_area_slots.clear()
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
                enrich_cell_from_reward_xml(self._acus_root, info_cell, self._game_index)
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
                cells, extras, grid_indices, truncated = parse_maparea_file(
                    self._acus_root, ap, self._game_index
                )
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
            return "没有成功载入任何 MapArea（请检查 Map.xml 的 MapDataAreaInfo 与对应 mapArea 文件）"
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
        """新增一页 3×3：默认全空，不创建 MapArea。"""
        self._page_area_slots.append([None] * 9)
        self._rebuild_page_tabs()
        new_page = len(self._page_area_slots) - 1
        if 0 <= new_page < self.tabs.count():
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
        if cur_page < len(self._page_area_slots):
            del self._page_area_slots[cur_page]
        # 删除后压缩 pageIndex，保证连续
        for m in self._area_info_meta:
            if m.page_index > cur_page:
                m.page_index -= 1
        self._rebuild_page_tabs()
        # tabs 最右侧是 '+'，所以不能用 tabs.count()-1 直接当 pageIndex
        self.tabs.setCurrentIndex(
            max(0, min(cur_page, len(self._page_area_slots) - 1))
        )

    def _rebuild_page_slots(self) -> None:
        """根据 Area 的 pageIndex/indexInPage 铺到九宫格；保留仅有空格的 MapPage 行数。"""
        n_from_meta = max((m.page_index + 1 for m in self._area_info_meta), default=0)
        n_from_pages = len(self._page_area_slots)
        n_pages = max(1, n_from_meta, n_from_pages)
        slots: list[list[int | None]] = [[None] * 9 for _ in range(n_pages)]
        for i, m in enumerate(self._area_info_meta):
            if 0 <= m.page_index < n_pages and 0 <= m.index_in_page <= 8:
                slots[m.page_index][m.index_in_page] = i
        self._page_area_slots = slots

    def _rebuild_page_tabs(self) -> None:
        self._rebuild_page_slots()
        # Preserve current page index (ignore '+' tab).
        old_idx = self.tabs.currentIndex()
        old_page_idx = old_idx if 0 <= old_idx < len(self._page_area_slots) else 0

        self._page_tab_suppress = True
        while self.tabs.count() > 0:
            self.tabs.removeTab(0)
        for pidx, slots in enumerate(self._page_area_slots):
            page = self._build_page_tab(pidx, slots)
            self.tabs.addTab(page, f"Page {pidx + 1}")

        plus_widget = QWidget()
        plus_lay = QVBoxLayout(plus_widget)
        plus_lay.setContentsMargins(10, 10, 10, 10)
        plus_lay.setSpacing(0)
        plus_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        plus_lbl = QLabel("+")
        plus_lbl.setStyleSheet("font-size: 28px; font-weight: 600; color:#374151;")
        plus_lay.addWidget(plus_lbl)
        self.tabs.addTab(plus_widget, "+")
        self._page_tab_plus_index = self.tabs.count() - 1
        # '+' tab 不需要关闭按钮
        bar = self.tabs.tabBar()
        if bar is not None:
            bar.setTabButton(self._page_tab_plus_index, QTabBar.ButtonPosition.RightSide, None)
            bar.setTabButton(self._page_tab_plus_index, QTabBar.ButtonPosition.LeftSide, None)

        if self._page_tab_plus_index > 0:
            self.tabs.setCurrentIndex(
                max(0, min(old_page_idx, self._page_tab_plus_index - 1))
            )
        self._page_tab_suppress = False

    def _build_page_tab(self, page_idx: int, slots: list[int | None]) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        grid = QGridLayout()
        grid.setSpacing(12)
        for i in range(9):
            aid = slots[i] if i < len(slots) else None
            tile_size = 148
            count_h = 26
            img_h = tile_size - count_h
            course_size = 64  # 两倍+，更醒目
            head_size = 84

            btn = QPushButton("")
            btn.setFixedSize(tile_size, tile_size)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setStyleSheet(
                "QPushButton{background:#FFFFFF;border:1px solid #E5E7EB;border-radius:8px;}"
                "QPushButton:hover{border:1px solid #D1D5DB;}"
            )
            btn.setToolTip(self._slot_text(page_idx, i, aid))

            # 让子控件不抢点击事件（保证点任意位置都能触发按钮）
            def _make_click_through(w: QLabel) -> None:
                w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

            img_lbl = QLabel(btn)
            img_lbl.setGeometry(0, 0, tile_size, img_h)
            img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_lbl.hide()
            _make_click_through(img_lbl)

            head_lbl = QLabel(btn)
            head_lbl.setGeometry(
                (tile_size - head_size) // 2, img_h - head_size - 2, head_size, head_size
            )
            head_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            head_lbl.hide()
            _make_click_through(head_lbl)

            course_lbl = QLabel(btn)
            course_lbl.setGeometry(2, 2, course_size, course_size)
            course_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            course_lbl.hide()
            _make_click_through(course_lbl)

            other_text_lbl = QLabel(btn)
            other_text_lbl.setGeometry(6, (img_h - 44) // 2, tile_size - 12, 44)
            other_text_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            other_text_lbl.setWordWrap(True)
            other_text_lbl.setStyleSheet(
                "background-color: rgba(0,0,0,140); color:#FFFFFF; border-radius:6px;"
                "font-size:11px; font-weight:600;"
            )
            other_text_lbl.hide()
            _make_click_through(other_text_lbl)

            count_lbl = QLabel(btn)
            count_lbl.setGeometry(0, img_h, tile_size, count_h)
            count_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            count_lbl.setWordWrap(True)
            count_lbl.setStyleSheet(
                "background-color: rgba(0,0,0,140); color:#FFFFFF; border-radius:0px;"
                "font-size:12px; font-weight:600;"
            )
            count_lbl.hide()
            _make_click_through(count_lbl)

            if aid is not None and aid >= 0 and aid < len(self._area_info_cells):
                c = self._area_info_cells[aid]

                # 1) 总格数（MapArea 终点 index 的推断值）
                total_steps = 1
                try:
                    if aid < len(self._area_grid_indices) and aid < len(self._area_cells):
                        total_steps = infer_map_terminator_index(
                            self._area_grid_indices[aid], self._area_cells[aid]
                        )
                except Exception:
                    total_steps = 1
                count_lbl.setText(f"{total_steps}格")
                count_lbl.show()

                # 2) 最终奖励缩略图（角色/称号）
                if c.reward_id is not None and c.reward_id >= 0:
                    thumb_shown = False
                    if c.reward_kind == "角色" and c.reward_inner_id is not None:
                        _back_pm, head_pm = self._get_chara_back_head_pixmaps(c.reward_inner_id)
                        if head_pm is not None and not head_pm.isNull():
                            img_pm = head_pm.scaled(
                                tile_size,
                                img_h,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation,
                            )
                            img_lbl.setPixmap(img_pm)
                            img_lbl.show()
                            thumb_shown = True
                    elif c.reward_kind == "称号(Trophy)" and c.reward_inner_id is not None:
                        rt = self._trophy_rare_type_by_id.get(c.reward_inner_id)
                        thumb_idx: int | None = None
                        if rt == 0:
                            thumb_idx = 0
                        elif rt == 1:
                            thumb_idx = 1
                        elif rt == 2:
                            thumb_idx = 2
                        elif rt == 3:
                            thumb_idx = 3
                        elif rt == 5:
                            thumb_idx = 4
                        elif rt == 11:
                            thumb_idx = 5
                        elif rt == 12:
                            thumb_idx = 2
                        elif rt == 13:
                            thumb_idx = 3
                        elif rt in (18, 19, 20):
                            thumb_idx = 6
                        elif rt in (7, 14):
                            thumb_idx = 7
                        elif rt == 9:
                            thumb_idx = 8
                        elif rt == 10:
                            thumb_idx = 9
                        else:
                            thumb_idx = 0

                        if thumb_idx is not None:
                            pm = self._trophy_thumb_pm_cache.get(thumb_idx)
                            if pm is None or pm.isNull():
                                src = self._trophy_ui_dir / f"{thumb_idx}.png"
                                if src.is_file():
                                    pm = QPixmap(str(src))
                                else:
                                    pm = QPixmap()
                                self._trophy_thumb_pm_cache[thumb_idx] = pm
                            if pm is not None and not pm.isNull():
                                img_pm = pm.scaled(
                                    tile_size,
                                    img_h,
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation,
                                )
                                img_lbl.setPixmap(img_pm)
                                img_lbl.show()
                                thumb_shown = True
                    elif c.reward_kind == "姓名牌装饰(NamePlate)" and c.reward_inner_id is not None:
                        pm = self._get_nameplate_pixmap(c.reward_inner_id)
                        if pm is not None and not pm.isNull():
                            img_pm = pm.scaled(
                                tile_size,
                                img_h,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation,
                            )
                            img_lbl.setPixmap(img_pm)
                            img_lbl.show()
                            thumb_shown = True
                    elif c.reward_kind == "功能票(Ticket)" and c.reward_inner_id is not None:
                        # 企鹅：A001 中 ticketName/id 实际上对应企鹅 itemId
                        penguin_id = c.reward_inner_id
                        fn_map = {8000: "gold.png", 8010: "silver.png", 8020: "soul.png", 8030: "rainbow.png"}
                        fn = fn_map.get(penguin_id)
                        if fn is not None:
                            pm = self._penguin_icon_pm_cache.get(penguin_id)
                            if pm is None or pm.isNull():
                                src = self._penguin_ui_dir / fn
                                if src.is_file():
                                    pm = QPixmap(str(src))
                                else:
                                    pm = QPixmap()
                                self._penguin_icon_pm_cache[penguin_id] = pm
                            if pm is not None and not pm.isNull():
                                img_pm = pm.scaled(
                                    tile_size,
                                    img_h,
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation,
                                )
                                img_lbl.setPixmap(img_pm)
                                img_lbl.show()
                                thumb_shown = True

                    if not thumb_shown:
                        # 如果该类型没有对应缩略图资源，则显示名称（优先 reward_name）。
                        name_txt = (c.reward_name or "").strip() or str(c.reward_inner_id or c.reward_id)
                        other_text_lbl.setText(name_txt)
                        other_text_lbl.show()
                # 3) 课题曲标签（左上角，放大）
                if c.music_id is not None:
                    if (
                        self._course_music_label_pm is not None
                        and not self._course_music_label_pm.isNull()
                    ):
                        course_pm = self._course_music_label_pm.scaled(
                            course_size,
                            course_size,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        course_lbl.setPixmap(course_pm)
                        course_lbl.show()

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
        if c.reward_kind == "场景(Stage)":
            return self._stage_name_by_id.get(iid, "")
        return ""

    def _edit_cell(self, area_idx: int, cell_idx: int) -> None:
        d = self._area_cells[area_idx][cell_idx]
        dlg = CellEditDialog(
            acus_root=self._acus_root,
            reward_refs=self._reward_refs,
            chara_refs=self._chara_refs,
            trophy_refs=self._trophy_refs,
            nameplate_refs=self._nameplate_refs,
            stage_refs=self._stage_refs,
            music_refs=self._music_refs,
            data=d,
            game_index=self._game_index,
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
            stage_refs=self._stage_refs,
            music_refs=self._music_refs,
            data=d,
            game_index=self._game_index,
            parent=self,
        )
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._refresh_area_page(area_idx)

    def _edit_area_extras(self, area_idx: int) -> None:
        ex = self._area_extras[area_idx]
        dlg = AreaExtrasDialog(acus_root=self._acus_root, game_index=self._game_index, extras=ex, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._refresh_area_page(area_idx)

    def _edit_area_meta(self, area_idx: int) -> None:
        meta = self._area_info_meta[area_idx]
        dlg = AreaPageMetaDialog(meta=meta, dds_refs=self._dds_map_refs, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self._refresh_area_page(area_idx)

    def _edit_page_slot(self, page_idx: int, slot_idx: int) -> None:
        if page_idx < 0 or page_idx >= len(self._page_area_slots):
            return
        area_idx = self._page_area_slots[page_idx][slot_idx]
        if area_idx is None:
            ans = QMessageBox.question(
                self,
                "空格子",
                "此格尚未绑定 MapArea。\n\n要在本格创建跑图区域并配置最终奖励吗？\n（与 A001 一致：无内容的格子可不写 MapArea。）",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
            area_idx = self._append_new_area_with_meta(page_index=page_idx, index_in_page=slot_idx)
            self._rebuild_page_tabs()
        self._edit_page_slot_single_dialog(area_idx)

    def _is_intermediate_reward_allowed(self, rid: int) -> bool:
        rx = resolve_reward_xml(self._acus_root, rid, self._game_index)
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
        dlg.setMinimumWidth(720)
        scr = QApplication.primaryScreen()
        if scr is not None:
            g = scr.availableGeometry()
            dlg.setMaximumHeight(int(g.height() * 0.92))
            dlg.resize(min(920, g.width() - 48), int(g.height() * 0.88))

        lay = QVBoxLayout(dlg)
        scroll = QScrollArea(dlg)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        content_lay = QVBoxLayout(content)
        content_lay.setContentsMargins(0, 0, 0, 0)
        content_lay.setSpacing(12)

        dds_box = QGroupBox("ddsMap 背景贴图 (Map.xml)")
        dds_form = QFormLayout(dds_box)
        meta_dds = self._area_info_meta[area_idx]
        dds_selected_id = meta_dds.dds_id
        dds_selected_str = meta_dds.dds_str
        selected_lbl = QLabel(f"当前：{dds_selected_id} | {dds_selected_str}")
        selected_lbl.setStyleSheet("color:#374151;")
        dds_form.addRow("", selected_lbl)

        dds_scroll = QScrollArea(dlg)
        dds_scroll.setWidgetResizable(True)
        dds_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        dds_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        dds_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        dds_scroll.setMinimumHeight(134)
        dds_row_host = QWidget()
        dds_row = QHBoxLayout(dds_row_host)
        # 给水平滚动条预留底部空间，避免遮挡卡片下缘
        dds_row.setContentsMargins(0, 0, 0, 12)
        dds_row.setSpacing(10)
        dds_scroll.setWidget(dds_row_host)

        dds_preview_cache: dict[int, QPixmap] = {}

        def _dds_preview_for(ref_id: int) -> QPixmap | None:
            if ref_id in dds_preview_cache:
                pm = dds_preview_cache[ref_id]
                return None if pm.isNull() else pm
            try:
                dds_files = self._candidate_ddsmap_dds_files(ref_id)
                if not dds_files:
                    dds_preview_cache[ref_id] = QPixmap()
                    return None
                # 不读 XML/path，直接取同级目录里的 dds（缓存后）进行预览。
                p = dds_files[0]
                pm = dds_to_pixmap(
                    acus_root=self._acus_root,
                    compressonatorcli_path=self._tool,
                    dds_path=p,
                    max_w=240,
                    max_h=120,
                    restrict=True,
                )
                if pm is None or pm.isNull():
                    dds_preview_cache[ref_id] = QPixmap()
                    return None
                dds_preview_cache[ref_id] = pm
                return pm
            except Exception:
                dds_preview_cache[ref_id] = QPixmap()
                return None

        def _select_dds(ref_id: int, ref_name: str) -> None:
            nonlocal dds_selected_id, dds_selected_str
            dds_selected_id = ref_id
            dds_selected_str = ref_name.strip() or "共通0001_CHUNITHM"
            selected_lbl.setText(f"当前：{dds_selected_id} | {dds_selected_str}")

        def _render_dds_cards() -> None:
            while dds_row.count() > 0:
                it = dds_row.takeAt(0)
                w = it.widget()
                if w is not None:
                    w.deleteLater()

            add_card = QPushButton("+\n新增")
            add_card.setFixedSize(130, 108)
            add_card.setStyleSheet(
                "QPushButton{background:#FFFFFF;border:1px solid #E5E7EB;border-radius:8px;"
                "text-align:center;font-size:16px;font-weight:700;color:#374151;}"
                "QPushButton:hover{border:1px solid #D1D5DB;}"
            )

            def _on_add_dds() -> None:
                created_id = self._create_ddsmap_and_refresh()
                if created_id < 0:
                    return
                for rr in self._dds_map_refs:
                    if rr.id == created_id:
                        _select_dds(rr.id, rr.name)
                        break
                _render_dds_cards()

            add_card.clicked.connect(_on_add_dds)
            dds_row.addWidget(add_card)

            refs = sorted(self._dds_map_refs, key=lambda x: x.id, reverse=True)
            for ref in refs:
                card = QPushButton("")
                card.setFixedSize(150, 108)
                card.setStyleSheet(
                    "QPushButton{background:#FFFFFF;border:1px solid #E5E7EB;border-radius:8px;}"
                    "QPushButton:hover{border:1px solid #D1D5DB;}"
                )
                col = QVBoxLayout(card)
                col.setContentsMargins(6, 6, 6, 6)
                col.setSpacing(4)
                pv = QLabel("无预览")
                pv.setAlignment(Qt.AlignmentFlag.AlignCenter)
                pv.setFixedHeight(66)
                pm = _dds_preview_for(ref.id)
                if pm is not None and not pm.isNull():
                    pv.setText("")
                    pv.setPixmap(
                        pm.scaled(
                            138,
                            64,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                cap = QLabel(f"{ref.id} | {ref.name}")
                cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cap.setWordWrap(True)
                cap.setStyleSheet("font-size:11px;color:#374151;")
                col.addWidget(pv)
                col.addWidget(cap)
                card.clicked.connect(lambda _=False, rid=ref.id, rn=ref.name: _select_dds(rid, rn))
                dds_row.addWidget(card)
            dds_row.addStretch(1)

        _render_dds_cards()
        dds_form.addRow("", dds_scroll)
        content_lay.addWidget(dds_box)

        # MapArea：仅编辑地图格数 + 过程奖励
        mid = QGroupBox("MapArea")
        mid_form = QFormLayout(mid)
        total_steps_edit = QLineEdit(
            str(
                infer_map_terminator_index(
                    self._area_grid_indices[area_idx], self._area_cells[area_idx]
                )
            )
        )
        total_steps_edit.setPlaceholderText("地图格数（终点 index，>=1）")
        mid_form.addRow("地图格数", total_steps_edit)

        add_step = QLineEdit()
        add_reward = QComboBox()
        add_reward.addItem("(仅功能票/Points)")
        for r in self._reward_refs:
            if self._is_intermediate_reward_allowed(r.id):
                add_reward.addItem(f"{r.id} | {r.display_name or r.name}", r.id)
        extra_lines = QTextEdit()
        extra_lines.setMinimumHeight(86)
        extra_lines.setPlaceholderText("每行：步数,reward_id,reward_name（步数 < 地图格数，且不可等于 地图格数−1）")
        add_btn = QPushButton("新增过程奖励")
        add_btn.setStyleSheet("QPushButton{text-align:center;}")

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
        mid_form.addRow("出现步数", add_step)
        mid_form.addRow("过程奖励", add_reward)
        mid_form.addRow("", add_btn)
        mid_form.addRow("过程奖励列表", extra_lines)
        content_lay.addWidget(mid)

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
        new_reward_btn.setStyleSheet("QPushButton{text-align:center;}")
        music_on = QCheckBox("有课题曲")
        music_pick = QComboBox()
        music_pick.addItem("(请选择)")
        for m in self._music_refs:
            music_pick.addItem(f"{m.id} | {m.name}", m.id)
        cinfo = self._area_info_cells[area_idx]
        if cinfo.music_id is not None:
            music_on.setChecked(True)
            idx = next((i for i, m in enumerate(self._music_refs, start=1) if m.id == cinfo.music_id), -1)
            if idx > 0:
                music_pick.setCurrentIndex(idx)
            else:
                music_pick.addItem(
                    f"{cinfo.music_id} | {cinfo.music_name or f'Music{cinfo.music_id}'}",
                    cinfo.music_id,
                )
                music_pick.setCurrentIndex(music_pick.count() - 1)

        def _sync_music() -> None:
            has_reward = reward_pick.currentIndex() > 0
            on = music_on.isChecked()
            music_on.setEnabled(has_reward)
            if not has_reward:
                music_on.setChecked(False)
            pick_on = has_reward and on
            music_pick.setEnabled(pick_on)
            if not (has_reward and on):
                music_pick.setCurrentIndex(0)

        music_on.toggled.connect(_sync_music)
        reward_pick.currentIndexChanged.connect(_sync_music)
        _sync_music()
        top_form.addRow("Reward", reward_pick)
        top_form.addRow("", new_reward_btn)
        top_form.addRow("", music_on)
        top_form.addRow("乐曲", music_pick)
        content_lay.addWidget(top)

        content_lay.addStretch(1)
        scroll.setWidget(content)
        lay.addWidget(scroll, 1)

        btns = QHBoxLayout()
        ok = QPushButton("保存")
        ok.setStyleSheet("QPushButton{text-align:center;}")
        cancel = QPushButton("取消")
        cancel.setStyleSheet("QPushButton{text-align:center;}")
        cancel.clicked.connect(dlg.reject)
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

        def _new_reward() -> None:
            rd = RewardCreateDialog(
                default_id=next_custom_reward_id(self._acus_root),
                music_refs=self._music_refs,
                chara_refs=self._chara_refs,
                trophy_refs=self._trophy_refs,
                nameplate_refs=self._nameplate_refs,
                stage_refs=self._stage_refs,
                parent=dlg,
            )
            if rd.exec() == rd.DialogCode.Accepted and rd.result_cell is not None:
                ensure_reward_xml(self._acus_root, rd.result_cell, self._game_index)
                self._reward_refs = load_reward_refs(self._acus_root, self._game_index)
                reward_pick.clear()
                reward_pick.addItem("(请选择)")
                for rr in self._reward_refs:
                    reward_pick.addItem(f"{rr.id} | {rr.display_name or rr.name}", rr.id)
                idx_new = next((i for i in range(1, reward_pick.count()) if reward_pick.itemData(i) == rd.result_cell.reward_id), 0)
                reward_pick.setCurrentIndex(idx_new)

        new_reward_btn.clicked.connect(_new_reward)

        def _save() -> None:
            total = _safe_int(total_steps_edit.text())
            if total is None or total < 1:
                QMessageBox.critical(
                    dlg, "错误", "地图格数输入不合法（须 >= 1）"
                )
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
            enrich_cell_from_reward_xml(self._acus_root, cell, self._game_index)
            if music_on.isChecked():
                mi = _combo_pick_id(music_pick)
                if mi is None:
                    QMessageBox.critical(dlg, "错误", "请选择课题曲对应的乐曲")
                    return
                cell.music_id = mi
                txt = music_pick.currentText()
                cell.music_name = (
                    txt.split("|", 1)[1].strip() if "|" in txt else f"Music{mi}"
                )
            else:
                cell.music_id = None
                cell.music_name = ""

            # update meta
            self._area_info_meta[area_idx].dds_id = int(dds_selected_id)
            self._area_info_meta[area_idx].dds_str = dds_selected_str or "共通0001_CHUNITHM"

            points_reward_id = 703000000
            ensure_points_reward_xml(
                self._acus_root,
                reward_id=points_reward_id,
                reward_name="3000 Points",
                points=3000,
                idx=self._game_index,
            )

            by_step: dict[int, CellData] = {
                total: _maparea_terminator_cell(),
                total - 1: CellData(
                    reward_id=points_reward_id,
                    reward_name="3000 Points",
                    reward_kind="外部奖励ID",
                    display_type=3,
                    cell_type=3,
                ),
            }
            lines = [x.strip() for x in extra_lines.toPlainText().splitlines() if x.strip()]
            for ln in lines:
                ps = [x.strip() for x in ln.split(",")]
                if len(ps) < 2:
                    continue
                st = _safe_int(ps[0])
                rrid = _safe_int(ps[1])
                if st is None or rrid is None:
                    continue
                if st >= total:
                    QMessageBox.critical(
                        dlg,
                        "错误",
                        f"过程奖励步数须小于地图格数（终点 index）{total}",
                    )
                    return
                if st == total - 1:
                    QMessageBox.critical(
                        dlg,
                        "错误",
                        "过程奖励不可占用地图格数-1（该步固定为 3000 Points）。",
                    )
                    return
                if not self._is_intermediate_reward_allowed(rrid):
                    continue
                rnm = ps[2] if len(ps) >= 3 and ps[2] else f"Reward{rrid}"
                by_step[st] = CellData(
                    reward_id=rrid,
                    reward_name=rnm,
                    reward_kind="外部奖励ID",
                    display_type=3,
                    cell_type=3,
                )
            if total >= 2:
                by_step.setdefault(
                    0, CellData(display_type=1, cell_type=1)
                )
            try:
                cells, idxs = _maparea_points_to_slots(list(by_step.items()))
            except ValueError as e:
                QMessageBox.critical(dlg, "错误", str(e))
                return
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

        if not self._area_cells:
            QMessageBox.critical(self, "错误", "请至少在九宫格中创建并保存一个 MapArea（点击空格并选择「是」创建区域）。")
            return

        for aix, gix in enumerate(self._area_grid_indices):
            if not any(x is not None for x in gix):
                QMessageBox.critical(
                    self,
                    "错误",
                    f"区域 {aix + 1} 尚未保存 MapArea 路线（请点开对应格子 → 保存「编辑页面格子」）。\n"
                    "否则写入时会错误地使用 index 0~8，游戏内会显示为极短路线。",
                )
                return

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
            grid_ix = self._area_grid_indices[idx - 1]
            self._write_maparea(
                area_id=area_id,
                area_name=area_name,
                cells=cells,
                extras=extras,
                grid_indices=grid_ix,
            )
            infos_xml.append(
                self._map_data_area_info_xml(
                    area_id=area_id,
                    area_name=area_name,
                    meta=meta,
                    info_cell=info_cell,
                )
            )

        map_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<MapData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>map{map_id:08d}</dataName>
  <netDispPeriod>true</netDispPeriod>
  <name>
    <id>{map_id}</id>
    <str>{self._xml_text(map_name)}</str>
    <data />
  </name>
  <mapType>2</mapType>
  <hiddenType>0</hiddenType>
  <unlockText>-</unlockText>
  <mapFilterID>
    <id>0</id>
    <str>Collaboration</str>
    <data>イベント</data>
  </mapFilterID>
  <categoryName>
    <id>0</id>
    <str>設定なし</str>
    <data />
  </categoryName>
  <timeTableName>
    <id>-1</id>
    <str>Invalid</str>
    <data />
  </timeTableName>
  <stopPageIndex>0</stopPageIndex>
  <stopReleaseEventName>
    <id>-1</id>
    <str>Invalid</str>
    <data />
  </stopReleaseEventName>
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
            event_id = self._next_available_unlock_event_id()
            if event_id < 0:
                QMessageBox.critical(self, "错误", "无法自动分配解锁事件 ID")
                return
            try:
                self._write_map_unlock_event(map_id=map_id, map_name=map_name, event_id=event_id)
                self._append_event_sort(event_id)
                msg += f"\n已生成地图解锁事件：event{event_id:08d}"
            except Exception as e:
                QMessageBox.warning(self, "事件未完整写入", f"地图已生成，但 Event/EventSort 写入失败：\n{e}")

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
            # MapArea 路径末端：倒数第二格不写奖励，最终格固定 -1/Invalid
            if i == len(cells) - 2:
                has_r = False
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
                ensure_reward_xml(self._acus_root, c, self._game_index)
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

    def _xml_text(self, s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _map_data_area_info_xml(
        self,
        *,
        area_id: int,
        area_name: str,
        meta: MapInfoMeta,
        info_cell: CellData,
    ) -> str:
        """与 A001 map02006619 中 MapDataAreaInfo 排版、字段顺序一致。"""
        mid = info_cell.music_id if info_cell.music_id is not None else -1
        mstr = (
            info_cell.music_name if info_cell.music_id is not None else "Invalid"
        )
        rid = info_cell.reward_id if info_cell.reward_id is not None else -1
        rstr = (
            info_cell.reward_name if info_cell.reward_id is not None else "Invalid"
        )
        return f"""    <MapDataAreaInfo>
      <mapAreaName>
        <id>{area_id}</id>
        <str>{self._xml_text(area_name)}</str>
        <data />
      </mapAreaName>
      <ddsMapName>
        <id>{meta.dds_id}</id>
        <str>{self._xml_text(meta.dds_str)}</str>
        <data />
      </ddsMapName>
      <musicName>
        <id>{mid}</id>
        <str>{self._xml_text(mstr)}</str>
        <data />
      </musicName>
      <rewardName>
        <id>{rid}</id>
        <str>{self._xml_text(rstr)}</str>
        <data />
      </rewardName>
      <isHard>{"true" if meta.is_hard else "false"}</isHard>
      <pageIndex>{meta.page_index}</pageIndex>
      <indexInPage>{meta.index_in_page}</indexInPage>
      <requiredAchievementCount>{meta.required_achievement_count}</requiredAchievementCount>
      <gaugeName>
        <id>{meta.gauge_id}</id>
        <str>{self._xml_text(meta.gauge_str)}</str>
        <data />
      </gaugeName>
    </MapDataAreaInfo>"""

    def _write_map_unlock_event(self, *, map_id: int, map_name: str, event_id: int) -> None:
        """
        与 A001 联动地图一致：event00018077（Ave Mujica）/ event00018087（MyGO）「マップフラグ」。

        - substances/type = 2（地图旗标），不是 6
        - information/mapFilterID = Invalid（-1）；Collaboration 只写在 Map.xml，不在此 Event
        """
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
    <type>2</type>
    <flag>
      <value>0</value>
    </flag>
    <information>
      <informationType>0</informationType>
      <informationDispType>0</informationDispType>
      <mapFilterID>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </mapFilterID>
      <courseNames>
        <list />
      </courseNames>
      <text />
      <image>
        <path />
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
        <id>{map_id}</id>
        <str>{mstr}</str>
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
        (ev_dir / "Event.xml").write_text(xml, encoding="utf-8", newline="\n")

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

    def _next_available_unlock_event_id(self, *, start: int = 70000) -> int:
        """返回从 start 开始的首个未被占用 Event ID。"""
        used: set[int] = set()
        event_root = self._acus_root / "event"
        if event_root.exists():
            for p in event_root.glob("event*"):
                if not p.is_dir():
                    continue
                name = p.name
                if len(name) <= 5:
                    continue
                suffix = name[5:]
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

