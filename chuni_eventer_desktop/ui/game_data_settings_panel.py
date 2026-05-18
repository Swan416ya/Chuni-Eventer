from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PyQt6.QtWidgets import QHBoxLayout, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from qfluentwidgets import BodyLabel, CardWidget, LineEdit, PushButton

from ..acus_workspace import AcusConfig, resolve_compressonatorcli_path
from ..game_data_index import GameDataIndex, load_cached_game_index
from .fluent_dialogs import fly_critical, fly_warning
from .rich_hint import rich_hint_label

_log = logging.getLogger("chuni.settings_dialog")

_PREVIEW_LIMIT = 30

_READ_LOGIC_TEXT = (
    "1. 在下方填写**游戏安装根目录**（通常含 `data`、`bin` 文件夹；也可直接指向某个 `A001` 等数据包目录）。\n"
    "2. 保存或点击「重新扫描」后，程序会递归查找名称形如 **A???**、且含有 `music` / `stage` / `ddsImage` / "
    "`ddsMap` / `chara` 等子目录的数据包根。\n"
    "3. 对每个数据包读取 `Music.xml`、`Stage.xml`、`ddsMap`、`Chara.xml` 等，按 ID 合并去重，"
    "结果写入 exe 旁的 `.cache/game_data_index.json`。\n"
    "4. 歌曲、地图、奖励、背景等编辑界面的下拉列表与校验，均会使用该缓存；"
    "更换目录或游戏更新后请重新扫描。"
)


def _pair_lines(pairs: list[tuple[int, str]], *, limit: int = _PREVIEW_LIMIT) -> list[str]:
    lines: list[str] = []
    for mid, name in pairs[:limit]:
        lines.append(f"{mid:05d} · {name}")
    rest = len(pairs) - limit
    if rest > 0:
        lines.append(f"… 另有 {rest} 条未列出")
    return lines


def _music_catalog_lines(catalog: list[dict[str, Any]], *, limit: int = _PREVIEW_LIMIT) -> list[str]:
    lines: list[str] = []
    for row in catalog[:limit]:
        mid = row.get("id")
        try:
            mid_i = int(mid)
        except (TypeError, ValueError):
            continue
        title = str(row.get("title") or row.get("str") or f"Music{mid_i}").strip()
        artist = str(row.get("artist") or "").strip()
        tag = str(row.get("release_tag_str") or "").strip()
        extra = " · ".join(x for x in (artist, tag) if x)
        lines.append(f"{mid_i:05d} · {title}" + (f"（{extra}）" if extra else ""))
    rest = len(catalog) - limit
    if rest > 0:
        lines.append(f"… 另有 {rest} 条未列出")
    return lines


def fill_game_index_tree(tree: QTreeWidget, idx: GameDataIndex | None, *, configured_root: str) -> None:
    tree.clear()
    root_item = tree.invisibleRootItem()

    if idx is None:
        QTreeWidgetItem(root_item, ["尚未建立索引", "请设置目录并重新扫描"])
        tree.expandAll()
        return

    cfg = configured_root.strip()
    cached_root = (idx.game_root or "").strip()
    mismatch = bool(cfg and cached_root and Path(cfg).expanduser().resolve() != Path(cached_root).expanduser().resolve())

    meta = QTreeWidgetItem(root_item, ["索引概况", ""])
    QTreeWidgetItem(meta, ["游戏根目录", cached_root or "—"])
    QTreeWidgetItem(meta, ["索引时间", idx.indexed_at or "—"])
    QTreeWidgetItem(meta, ["数据包数量", str(len(idx.roots_scanned))])
    if mismatch:
        QTreeWidgetItem(meta, ["提示", "当前填写的目录与缓存索引不一致，请重新扫描"])

    packs = QTreeWidgetItem(root_item, [f"数据包路径（{len(idx.roots_scanned)}）", ""])
    for rel in idx.roots_scanned[:20]:
        QTreeWidgetItem(packs, [rel, ""])
    if len(idx.roots_scanned) > 20:
        QTreeWidgetItem(packs, [f"… 另有 {len(idx.roots_scanned) - 20} 个", ""])

    sections: list[tuple[str, list[str]]] = []
    if idx.music_catalog:
        sections.append((f"乐曲（{len(idx.music_catalog)}）", _music_catalog_lines(idx.music_catalog)))
    else:
        sections.append((f"乐曲（{len(idx.music)}）", _pair_lines(idx.music)))
    sections.extend(
        [
            (f"场景 Stage（{len(idx.stage)}）", _pair_lines(idx.stage)),
            (f"DDS 贴图 ddsImage（{len(idx.dds_image)}）", _pair_lines(idx.dds_image)),
            (f"地图 ddsMap（{len(idx.dds_map)}）", _pair_lines(idx.dds_map)),
            (f"角色 Chara（{len(idx.chara)}）", _pair_lines(idx.chara)),
            (f"名牌 NamePlate（{len(idx.nameplate)}）", _pair_lines(idx.nameplate)),
            (f"称号 Trophy（{len(idx.trophy)}）", _pair_lines(idx.trophy)),
        ]
    )

    for title, lines in sections:
        parent = QTreeWidgetItem(root_item, [title, f"{len(lines) if lines and not lines[-1].startswith('…') else ''}"])
        if not lines:
            QTreeWidgetItem(parent, ["（无）", ""])
        else:
            for line in lines:
                QTreeWidgetItem(parent, [line, ""])

    tree.expandToDepth(1)


class GameDataSettingsPanel(QWidget):
    """设置 → 游戏数据：读取逻辑、目录配置、索引结果预览。"""

    def __init__(
        self,
        *,
        cfg: AcusConfig,
        get_game_index: Callable[[], GameDataIndex | None] | None = None,
        on_request_game_rescan: Callable[[Path, Path | None], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self._cfg = cfg
        self._get_game_index = get_game_index or (lambda: None)
        self._on_request_game_rescan = on_request_game_rescan

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(16)

        logic_card = CardWidget(self)
        logic_lay = QVBoxLayout(logic_card)
        logic_lay.setContentsMargins(16, 16, 16, 16)
        logic_lay.setSpacing(8)
        logic_lay.addWidget(BodyLabel("读取逻辑", self))
        logic_lay.addWidget(rich_hint_label(_READ_LOGIC_TEXT, self, color="#4B5563"))
        layout.addWidget(logic_card)

        dir_card = CardWidget(self)
        dir_lay = QVBoxLayout(dir_card)
        dir_lay.setContentsMargins(16, 16, 16, 16)
        dir_lay.setSpacing(12)
        dir_lay.addWidget(BodyLabel("游戏数据目录", self))
        dir_hint = BodyLabel(
            "指向已安装 CHUNITHM 的数据位置，用于建立下方列表中的乐曲、场景等资源索引。",
            self,
        )
        dir_hint.setWordWrap(True)
        dir_hint.setStyleSheet("color:#6B7280;font-size:13px;")
        dir_lay.addWidget(dir_hint)

        self.game_root = LineEdit(self)
        self.game_root.setPlaceholderText("例如 D:\\Games\\CHUNITHM 或 …\\A001 的上一级")
        if cfg.game_root:
            self.game_root.setText(cfg.game_root)
        game_browse = PushButton("浏览文件夹…", self)
        game_browse.clicked.connect(self._pick_game_root)
        rescan = PushButton("重新扫描", self)
        rescan.clicked.connect(self._rescan_game_index)

        game_row = QHBoxLayout()
        game_row.setSpacing(8)
        game_row.addWidget(self.game_root, stretch=1)
        game_row.addWidget(game_browse)
        game_row.addWidget(rescan)
        dir_lay.addLayout(game_row)
        layout.addWidget(dir_card)

        data_card = CardWidget(self)
        data_lay = QVBoxLayout(data_card)
        data_lay.setContentsMargins(16, 16, 16, 16)
        data_lay.setSpacing(8)
        data_lay.addWidget(BodyLabel("已读取的数据", self))
        self._data_hint = BodyLabel("", self)
        self._data_hint.setWordWrap(True)
        self._data_hint.setStyleSheet("color:#6B7280;font-size:13px;")
        data_lay.addWidget(self._data_hint)

        self._index_tree = QTreeWidget(self)
        self._index_tree.setHeaderLabels(["条目", ""])
        self._index_tree.setColumnHidden(1, True)
        self._index_tree.setRootIsDecorated(True)
        self._index_tree.setAlternatingRowColors(True)
        self._index_tree.setMinimumHeight(280)
        data_lay.addWidget(self._index_tree)
        layout.addWidget(data_card, stretch=1)

        tools_hint = BodyLabel(
            "DDS 工具、FFmpeg、PenguinTools.CLI、mua 等请在【设置 → 外部工具】中配置。",
            self,
        )
        tools_hint.setWordWrap(True)
        tools_hint.setStyleSheet("color:#6B7280;font-size:13px;")
        layout.addWidget(tools_hint)

        self.refresh_index_display()

    def refresh_index_display(self) -> None:
        idx = self._get_game_index()
        if idx is None:
            gr = self.game_root.text().strip() or (self._cfg.game_root or "").strip()
            if gr:
                idx = load_cached_game_index(gr)
        configured = self.game_root.text().strip() or (self._cfg.game_root or "")
        if idx is None:
            self._data_hint.setText("暂无缓存。保存目录后将自动后台扫描，或点击「重新扫描」。")
        else:
            self._data_hint.setText(
                f"共 {len(idx.music)} 首乐曲、{len(idx.stage)} 个场景、"
                f"{len(idx.dds_image)} 条 DDS 贴图、{len(idx.dds_map)} 条地图 ddsMap、"
                f"{len(idx.chara)} 个角色、{len(idx.nameplate)} 个名牌、{len(idx.trophy)} 个称号。"
            )
        fill_game_index_tree(self._index_tree, idx, configured_root=configured)

    def _pick_game_root(self) -> None:
        from PyQt6.QtWidgets import QFileDialog

        d = QFileDialog.getExistingDirectory(self, "选择游戏数据目录（含 A001）")
        if d:
            self.game_root.setText(d)

    def _rescan_game_index(self) -> None:
        raw = self.game_root.text().strip()
        if not raw:
            fly_warning(self, "未设置", "请先填写或浏览选择游戏数据目录。")
            return
        root = Path(raw).expanduser()
        tool_path = resolve_compressonatorcli_path(self._cfg)
        if self._on_request_game_rescan is None:
            fly_warning(self, "不可用", "当前窗口未提供后台扫描入口。")
            return
        self._on_request_game_rescan(root, tool_path)

    def apply(self) -> bool:
        _log.info("save_button_clicked")
        try:
            gr = self.game_root.text().strip()
            self._cfg.game_root = gr
            self._cfg.save()
            _log.info("apply_done game_root=%s", gr)
            self.refresh_index_display()
            return True
        except Exception:
            _log.exception("save_button_crash")
            fly_critical(self, "保存失败", "设置保存时发生未处理异常，请提供 settings_save.log。")
            return False
