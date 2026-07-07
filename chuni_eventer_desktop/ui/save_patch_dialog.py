from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    PrimaryPushButton,
    PushButton,
    SpinBox,
    TabWidget,
    isDarkTheme,
)

from ..chusan_save import (
    PENGUIN_ITEM_IDS,
    PENGUIN_ITEM_KIND,
    PENGUIN_ITEM_NAMES,
    load_save,
    save_save,
    set_equipped_map_icon,
    set_equipped_nameplate,
    set_equipped_stage,
    set_equipped_trophies,
    set_equipped_voice,
    set_penguin_stocks,
    sum_item_stock,
)
from ..dds_preview import dds_to_pixmap
from ..dds_quicktex import quicktex_available
from ..game_data_assets import resolve_row_image_dds
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical, fly_message, fly_warning
from .game_data_browse_dialog import GameDataBrowseDialog

_PAGE_MARGINS = (0, 0, 0, 8)


def _preview_frame_style() -> str:
    b = "#3A3A3A" if isDarkTheme() else "#D1D5DB"
    bg = "#2D2D2D" if isDarkTheme() else "#F9FAFB"
    return f"QLabel {{ border: 1px solid {b}; border-radius: 8px; background: {bg}; }}"


def _make_select_button(parent, *, title: str) -> PrimaryPushButton:
    """创建一个「从所有 opt 中选择…」按钮，点击弹出选择弹窗。"""
    btn = PrimaryPushButton(f"从所有 opt 中选择{title}", parent)
    return btn


class _SelectionHolder:
    """单 tab 选中状态的简单封装（仅持有 row 数据 + clear）。"""

    def __init__(self) -> None:
        self.row: dict | None = None

    def clear(self) -> None:
        self.row = None


class SavePatchPanel(QWidget):
    """
    上传 ALL.Net 导出存档 JSON，编辑 userData 中装备相关字段（名牌、主/副称号、系统语音、
    MapIcon、背景（Stage）、企鹅等），另存为新 JSON。

    数据源改为跨 opt 扫描：从 game_root 下所有数据包读取 catalog。
    每个装备 tab 用「按钮 + 弹窗选择器」替代原来的 EditableComboBox。
    """

    def __init__(
        self,
        *,
        acus_root: Path,
        game_root: Path,
        get_tool_path,
        get_index=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self._acus_root = Path(acus_root) if acus_root else Path()
        # game_root 可能从 cfg 传来是 str，统一转 Path，避免 scan_game_*_catalog 内部调 expanduser 崩
        self._game_root = Path(game_root) if game_root else Path()
        self._get_tool_path = get_tool_path
        self._get_index = get_index or (lambda: None)
        self._save_path: Path | None = None
        self._data: dict | None = None

        # 跨 opt catalog（list[dict]）
        self._load_catalogs()

        self.path_label = CaptionLabel("未选择文件", self)
        self.path_label.setWordWrap(True)

        pick_btn = PrimaryPushButton("选择存档 JSON…", self)
        pick_btn.clicked.connect(self._pick_save)

        self.tabs = TabWidget(self)
        self.tabs.setTabsClosable(False)
        self.tabs.tabBar.setAddButtonVisible(False)

        # === 名牌 ===
        np_page = self._build_np_page()
        self.tabs.addTab(np_page, "名牌")

        # === 称号 ===
        tr_page = self._build_tr_page()
        self.tabs.addTab(tr_page, "称号")

        # === 系统语音 ===
        sv_page = self._build_sv_page()
        self.tabs.addTab(sv_page, "系统语音")

        # === 跑图小人 ===
        mi_page = self._build_mi_page()
        self.tabs.addTab(mi_page, "跑图小人")

        # === 背景 ===
        st_page = self._build_st_page()
        self.tabs.addTab(st_page, "背景")

        # === 企鹅 ===
        pg_page = self._build_pg_page()
        self.tabs.addTab(pg_page, "企鹅")

        apply_btn = PrimaryPushButton("写入并另存为…", self)
        apply_btn.clicked.connect(self._apply)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        btns.addStretch(1)
        btns.addWidget(apply_btn)

        hint = BodyLabel(
            "另存为会写入：名牌、主/副称号、系统语音 voiceId、mapIconId、背景 stageId、企鹅数量（userItemList）。"
            " 其它字段不动；原文件不会被覆盖。"
            " 若目标服校验持有物，请自行保证资源已解锁。",
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #CA8A04;")

        tabs_card = CardWidget(self)
        tc_lay = QVBoxLayout(tabs_card)
        tc_lay.setContentsMargins(12, 12, 12, 12)
        tc_lay.addWidget(self.tabs)

        root = QVBoxLayout(self)
        root.setContentsMargins(*_PAGE_MARGINS)
        root.setSpacing(14)
        root.addWidget(pick_btn)
        root.addWidget(self.path_label)
        root.addWidget(hint)
        root.addWidget(tabs_card, stretch=1)
        root.addLayout(btns)

        # 初始化预览
        self._on_np_changed()
        self._on_tr_main_changed()
        self._on_sv_changed()
        self._on_mi_changed()
        self._on_st_changed()

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------

    def _load_catalogs(self) -> None:
        """初始化 catalog 容器为空。实际扫描延迟到打开选择器时（避免 UI 线程卡死）。"""
        self._nameplates: list[dict] = []
        self._trophies: list[dict] = []
        self._system_voices: list[dict] = []
        self._map_icons: list[dict] = []
        self._stages: list[dict] = []

    # ------------------------------------------------------------------
    # 延迟扫描 — 只在用户打开对应选择器时才扫描（避免 UI 线程卡死）
    # ------------------------------------------------------------------

    def _ensure_np_catalog(self) -> None:
        """如果名牌 catalog 还没扫描，现在扫（只扫一次，优先走索引缓存）。"""
        if self._nameplates:
            return
        if not str(self._game_root).strip():
            return
        # 优先走索引缓存
        idx = self._get_index()
        if idx is not None and getattr(idx, "nameplate_catalog", None):
            self._nameplates = [dict(r) for r in idx.nameplate_catalog if isinstance(r, dict)]
            return
        from ..game_data_index import scan_game_nameplate_catalog
        self._nameplates = scan_game_nameplate_catalog(self._game_root)

    def _ensure_tr_catalog(self) -> None:
        """如果称号 catalog 还没扫描，现在扫（只扫一次，优先走索引缓存）。"""
        if self._trophies:
            return
        if not str(self._game_root).strip():
            return
        idx = self._get_index()
        if idx is not None and getattr(idx, "trophy_catalog", None):
            self._trophies = [dict(r) for r in idx.trophy_catalog if isinstance(r, dict)]
            return
        from ..game_data_index import scan_game_trophy_catalog
        self._trophies = scan_game_trophy_catalog(self._game_root)

    def _ensure_sv_catalog(self) -> None:
        """系统语音无索引缓存，直接扫。"""
        if self._system_voices:
            return
        if not str(self._game_root).strip():
            return
        from ..game_data_index import scan_game_system_voice_catalog
        self._system_voices = scan_game_system_voice_catalog(self._game_root)

    def _ensure_mi_catalog(self) -> None:
        """跑图小人无索引缓存，直接扫。"""
        if self._map_icons:
            return
        if not str(self._game_root).strip():
            return
        from ..game_data_index import scan_game_map_icon_catalog
        self._map_icons = scan_game_map_icon_catalog(self._game_root)

    def _ensure_st_catalog(self) -> None:
        """背景（Stage）无索引缓存，直接扫。"""
        if self._stages:
            return
        if not str(self._game_root).strip():
            return
        from ..game_data_index import scan_game_stage_catalog
        self._stages = scan_game_stage_catalog(self._game_root)

    # ------------------------------------------------------------------
    # Tab 构建器 — 名牌
    # ------------------------------------------------------------------

    def _build_np_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)

        self.np_preview = QLabel("预览", self)
        self.np_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.np_preview.setMinimumHeight(200)
        self.np_preview.setStyleSheet(_preview_frame_style())

        self.np_holder = _SelectionHolder()

        self._np_label = CaptionLabel("存档: - | 已选: 未选择", self)

        btn_select = _make_select_button(self, title="…")
        btn_select.clicked.connect(self._open_np_picker)
        btn_clear = PushButton("清除", self)
        btn_clear.clicked.connect(self._clear_np)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addWidget(btn_select)
        btn_row.addWidget(btn_clear)

        lay.addWidget(self._np_label)
        lay.addWidget(self.np_preview)
        lay.addLayout(btn_row)
        lay.addStretch(1)
        return page

    def _open_np_picker(self) -> None:
        self._ensure_np_catalog()
        dlg = GameDataBrowseDialog(
            kind="nameplate",
            game_root=self._game_root,
            acus_root=self._acus_root,
            get_index=self._get_index,
            get_tool_path=self._get_tool_path,
            select_mode=True,
            preset_rows=list(self._nameplates),
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            item = dlg.selected_item()
            if item:
                self._set_np_selected(item)

    def _set_np_selected(self, row: dict) -> None:
        self.np_holder.row = row
        self._update_np_label()
        self._on_np_changed()

    def _clear_np(self) -> None:
        self.np_holder.clear()
        self._update_np_label()
        self._on_np_changed()

    # ------------------------------------------------------------------
    # Tab 构建器 — 称号
    # ------------------------------------------------------------------

    def _update_np_label(self) -> None:
        """更新名牌合并 label：存档值 | 已选"""
        if self._data:
            nid = (self._data.get("userData") or {}).get("nameplateId")
            archive_text = str(nid) if isinstance(nid, int) else "-"
        else:
            archive_text = "-"
        row = self.np_holder.row
        if row is None:
            selected_text = "未选择"
        else:
            selected_text = f"{row.get('id', '')} | {row.get('name', '')}"
        self._np_label.setText(f"存档: {archive_text} | 已选: {selected_text}")

    def _build_tr_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)

        self.tr_limit_hint = BodyLabel(
            "提示：本工具仅离线修改导出 JSON。若目标环境校验持有物，请自行保证账号已解锁对应称号/语音/跑图小人/背景等资源。",
            self,
        )
        self.tr_limit_hint.setWordWrap(True)
        self.tr_limit_hint.setStyleSheet("color: #CA8A04;")

        self.tr_main_holder = _SelectionHolder()
        self.tr_sub1_holder = _SelectionHolder()
        self.tr_sub2_holder = _SelectionHolder()

        self._tr_slot_labels: list[CaptionLabel] = []

        self.tr_preview = QLabel("预览（主称号）", self)
        self.tr_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tr_preview.setMinimumHeight(200)
        self.tr_preview.setStyleSheet(_preview_frame_style())

        main_row = self._build_tr_slot_row("主称号", self.tr_main_holder)
        sub1_row = self._build_tr_slot_row("副称号 1", self.tr_sub1_holder)
        sub2_row = self._build_tr_slot_row("副称号 2", self.tr_sub2_holder)

        form = QFormLayout()
        form.addRow("当前选中", main_row[1])
        form.addRow("从 opt 选择", main_row[0])
        form.addRow("当前选中", sub1_row[1])
        form.addRow("从 opt 选择", sub1_row[0])
        form.addRow("当前选中", sub2_row[1])
        form.addRow("从 opt 选择", sub2_row[0])

        lay.addWidget(self.tr_limit_hint)
        lay.addLayout(form)
        lay.addWidget(self.tr_preview)
        lay.addStretch(1)
        return page

    def _build_tr_slot_row(self, label: str, holder: _SelectionHolder) -> tuple[QWidget, QWidget]:
        """返回 (按钮组 widget, 选中显示 label) 用于 QFormLayout。"""
        btn_container = QWidget()
        btn_lay = QHBoxLayout(btn_container)
        btn_lay.setContentsMargins(0, 0, 0, 0)
        btn_lay.setSpacing(4)

        btn_select = _make_select_button(self, title=f"({label})")
        btn_select.clicked.connect(
            lambda _=False, h=holder, k=label: self._open_tr_picker(h, k)
        )
        btn_clear = PushButton("清除", self)
        btn_clear.clicked.connect(lambda _=False, h=holder: self._clear_tr(h))
        btn_lay.addWidget(btn_select)
        btn_lay.addWidget(btn_clear)

        sel_label = CaptionLabel("未选择", self)
        self._tr_slot_labels.append(sel_label)
        return btn_container, sel_label

    def _open_tr_picker(self, holder: _SelectionHolder, _label: str) -> None:
        self._ensure_tr_catalog()
        dlg = GameDataBrowseDialog(
            kind="trophy",
            game_root=self._game_root,
            acus_root=self._acus_root,
            get_index=self._get_index,
            get_tool_path=self._get_tool_path,
            select_mode=True,
            preset_rows=list(self._trophies),
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            item = dlg.selected_item()
            if item:
                holder.row = item
                # 更新当前 holder 对应的 slot label（按 holder 引用找索引）
                holder_idx = id(holder)
                label_idx = None
                for idx, h in enumerate([self.tr_main_holder, self.tr_sub1_holder, self.tr_sub2_holder]):
                    if id(h) == holder_idx:
                        label_idx = idx
                        break
                if label_idx is not None and label_idx < len(self._tr_slot_labels):
                    self._update_tr_slot_label(label_idx)
                self._on_tr_main_changed()

    def _clear_tr(self, holder: _SelectionHolder) -> None:
        holder.clear()
        # 更新当前 holder 对应的 slot label
        holder_idx = id(holder)
        label_idx = None
        for idx, h in enumerate([self.tr_main_holder, self.tr_sub1_holder, self.tr_sub2_holder]):
            if id(h) == holder_idx:
                label_idx = idx
                break
        if label_idx is not None and label_idx < len(self._tr_slot_labels):
            self._update_tr_slot_label(label_idx)
        self._on_tr_main_changed()

    def _update_tr_slot_label(self, label_idx: int) -> None:
        """更新称号 slot label：存档: XXX | 已选: YYY"""
        holders = [self.tr_main_holder, self.tr_sub1_holder, self.tr_sub2_holder]
        if label_idx < 0 or label_idx >= len(holders):
            return
        holder = holders[label_idx]
        row = holder.row
        if row is not None and "id" in row:
            selected_text = f"{row.get('id', '')} | {row.get('name', '')}"
        else:
            selected_text = "未选择"
        if self._data:
            slot_keys = ["trophyId", "trophyIdSub1", "trophyIdSub2"]
            tid = (self._data.get("userData") or {}).get(slot_keys[label_idx])
            archive_text = str(tid) if isinstance(tid, int) else "-"
        else:
            archive_text = "-"
        self._tr_slot_labels[label_idx].setText(f"存档: {archive_text} | 已选: {selected_text}")

    # ------------------------------------------------------------------
    # Tab 构建器 — 系统语音
    # ------------------------------------------------------------------

    def _build_sv_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)

        self.sv_holder = _SelectionHolder()

        self.sv_preview = QLabel("预览", self)
        self.sv_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sv_preview.setMinimumHeight(200)
        self.sv_preview.setStyleSheet(_preview_frame_style())

        self._sv_label = CaptionLabel("存档: - | 已选: 未选择", self)

        btn_select = _make_select_button(self, title="…")
        btn_select.clicked.connect(self._open_sv_picker)
        btn_clear = PushButton("清除", self)
        btn_clear.clicked.connect(self._clear_sv)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addWidget(btn_select)
        btn_row.addWidget(btn_clear)

        info_lay = QVBoxLayout()
        info_lay.addWidget(self._sv_label)
        info_lay.addLayout(btn_row)
        lay.addLayout(info_lay)

        lay.addWidget(self.sv_preview)
        lay.addStretch(1)
        return page

    def _open_sv_picker(self) -> None:
        self._ensure_sv_catalog()
        dlg = GameDataBrowseDialog(
            kind="system_voice",
            game_root=self._game_root,
            acus_root=self._acus_root,
            get_index=self._get_index,
            get_tool_path=self._get_tool_path,
            select_mode=True,
            preset_rows=list(self._system_voices),
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            item = dlg.selected_item()
            if item:
                self.sv_holder.row = item
                self._update_sv_label()
                self._on_sv_changed()

    def _clear_sv(self) -> None:
        self.sv_holder.clear()
        self._update_sv_label()
        self._on_sv_changed()

    def _update_sv_label(self) -> None:
        """更新系统语音合并 label：存档: XXX | 已选: YYY"""
        if self._data:
            vid = (self._data.get("userData") or {}).get("voiceId")
            archive_text = str(vid) if isinstance(vid, int) else "-"
        else:
            archive_text = "-"
        row = self.sv_holder.row
        if row is None:
            selected_text = "未选择"
        else:
            selected_text = f"{row.get('id', '')} | {row.get('name', '')}"
        self._sv_label.setText(f"存档: {archive_text} | 已选: {selected_text}")

    # ------------------------------------------------------------------
    # Tab 构建器 — 跑图小人
    # ------------------------------------------------------------------

    def _build_mi_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)

        self.mi_holder = _SelectionHolder()

        self.mi_preview = QLabel("预览", self)
        self.mi_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mi_preview.setMinimumHeight(200)
        self.mi_preview.setStyleSheet(_preview_frame_style())

        self._mi_label = CaptionLabel("存档: - | 已选: 未选择", self)

        btn_select = _make_select_button(self, title="…")
        btn_select.clicked.connect(self._open_mi_picker)
        btn_clear = PushButton("清除", self)
        btn_clear.clicked.connect(self._clear_mi)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addWidget(btn_select)
        btn_row.addWidget(btn_clear)

        info_lay = QVBoxLayout()
        info_lay.addWidget(self._mi_label)
        info_lay.addLayout(btn_row)
        lay.addLayout(info_lay)

        lay.addWidget(self.mi_preview)
        lay.addStretch(1)
        return page

    def _open_mi_picker(self) -> None:
        self._ensure_mi_catalog()
        dlg = GameDataBrowseDialog(
            kind="map_icon",
            game_root=self._game_root,
            acus_root=self._acus_root,
            get_index=self._get_index,
            get_tool_path=self._get_tool_path,
            select_mode=True,
            preset_rows=list(self._map_icons),
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            item = dlg.selected_item()
            if item:
                self.mi_holder.row = item
                self._update_mi_label()
                self._on_mi_changed()

    def _clear_mi(self) -> None:
        self.mi_holder.clear()
        self._update_mi_label()
        self._on_mi_changed()

    def _update_mi_label(self) -> None:
        """更新跑图小人合并 label：存档: XXX | 已选: YYY"""
        if self._data:
            mid = (self._data.get("userData") or {}).get("mapIconId")
            archive_text = str(mid) if isinstance(mid, int) else "-"
        else:
            archive_text = "-"
        row = self.mi_holder.row
        if row is None:
            selected_text = "未选择"
        else:
            selected_text = f"{row.get('id', '')} | {row.get('name', '')}"
        self._mi_label.setText(f"存档: {archive_text} | 已选: {selected_text}")

    # ------------------------------------------------------------------
    # Tab 构建器 — 背景（Stage）
    # ------------------------------------------------------------------

    def _build_st_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)

        self.st_holder = _SelectionHolder()

        self.st_preview = QLabel("预览", self)
        self.st_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.st_preview.setMinimumHeight(200)
        self.st_preview.setStyleSheet(_preview_frame_style())

        self._st_label = CaptionLabel("存档: - | 已选: 未选择", self)

        btn_select = _make_select_button(self, title="…")
        btn_select.clicked.connect(self._open_st_picker)
        btn_clear = PushButton("清除", self)
        btn_clear.clicked.connect(self._clear_st)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addWidget(btn_select)
        btn_row.addWidget(btn_clear)

        info_lay = QVBoxLayout()
        info_lay.addWidget(self._st_label)
        info_lay.addLayout(btn_row)
        lay.addLayout(info_lay)

        lay.addWidget(self.st_preview)
        return page

    def _open_st_picker(self) -> None:
        self._ensure_st_catalog()
        dlg = GameDataBrowseDialog(
            kind="stage",
            game_root=self._game_root,
            acus_root=self._acus_root,
            get_index=self._get_index,
            get_tool_path=self._get_tool_path,
            select_mode=True,
            preset_rows=list(self._stages),
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            item = dlg.selected_item()
            if item:
                self.st_holder.row = item
                self._update_st_label()
                self._on_st_changed()

    def _clear_st(self) -> None:
        self.st_holder.clear()
        self._update_st_label()
        self._on_st_changed()

    def _update_st_label(self) -> None:
        """更新背景合并 label：存档: XXX | 已选: YYY"""
        if self._data:
            sid = (self._data.get("userData") or {}).get("stageId")
            archive_text = str(sid) if isinstance(sid, int) else "-"
        else:
            archive_text = "-"
        row = self.st_holder.row
        if row is None:
            selected_text = "未选择"
        else:
            selected_text = f"{row.get('id', '')} | {row.get('name', '')}"
        self._st_label.setText(f"存档: {archive_text} | 已选: {selected_text}")

    # ------------------------------------------------------------------
    # Tab 构建器 — 企鹅
    # ------------------------------------------------------------------

    def _build_pg_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)
        pg_hint = BodyLabel(
            "对应导出存档 userItemList：itemKind=5，itemId 8000 金企鹅 / 8010 小企鹅 / 8020 企鹅之魂 / 8030 彩色企鹅，"
            "isValid 固定为 true，stock 为数量（含 0）。"
            " 修改后须点击底部「另存为」写入新 JSON，不会改动原文件。",
            self,
        )
        pg_hint.setWordWrap(True)
        lay.addWidget(pg_hint)
        pg_form = QFormLayout()
        self._penguin_spins: list[SpinBox] = []
        for pid in PENGUIN_ITEM_IDS:
            sp = SpinBox(self)
            sp.setRange(0, 9_999_999)
            sp.setSingleStep(1)
            sp.setKeyboardTracking(False)
            self._penguin_spins.append(sp)
            name = PENGUIN_ITEM_NAMES.get(pid, str(pid))
            pg_form.addRow(f"{name}（itemId {pid}）", sp)
        lay.addLayout(pg_form)
        lay.addStretch(1)
        return page

    # ------------------------------------------------------------------
    # 存档加载 / 同步
    # ------------------------------------------------------------------

    def _pick_save(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择导出存档", "", "JSON (*.json);;All (*)")
        if not path:
            return
        p = Path(path)
        try:
            self._data = load_save(p)
            if "userData" not in self._data:
                raise ValueError("不是有效的导出存档：缺少 userData")
        except Exception as e:
            fly_critical(self, "读取失败", str(e))
            self._data = None
            self._save_path = None
            self.path_label.setText("读取失败")
            return
        self._save_path = p
        self.path_label.setText(str(p))
        self._sync_from_save()

    def _sync_from_save(self) -> None:
        if not self._data:
            return
        ud = self._data.get("userData") or {}

        # 延迟确保 catalog 已加载（只会在首次打开存档时触发扫描）
        self._ensure_np_catalog()
        self._ensure_tr_catalog()
        self._ensure_sv_catalog()
        self._ensure_mi_catalog()
        self._ensure_st_catalog()

        # 名牌 — 先匹配 catalog
        nid = ud.get("nameplateId")
        if isinstance(nid, int):
            for row in self._nameplates:
                if int(row.get("id", -1)) == nid:
                    self._set_np_selected(row)
                    return
            # catalog 未匹配：仅设置 holder row（含 id），由 _update_np_label 展示
            self.np_holder.row = {"id": nid}

        # 称号
        for holder, slot_key in [
            (self.tr_main_holder, "trophyId"),
            (self.tr_sub1_holder, "trophyIdSub1"),
            (self.tr_sub2_holder, "trophyIdSub2"),
        ]:
            tid = ud.get(slot_key)
            if isinstance(tid, int):
                for row in self._trophies:
                    if int(row.get("id", -1)) == tid:
                        holder.row = row
                        break
                else:
                    holder.row = {"id": tid}

        # 系统语音
        vid = ud.get("voiceId")
        if isinstance(vid, int):
            for row in self._system_voices:
                if int(row.get("id", -1)) == vid:
                    self.sv_holder.row = row
                    break
            else:
                self.sv_holder.row = {"id": vid}

        # 跑图小人
        mid = ud.get("mapIconId")
        if isinstance(mid, int):
            for row in self._map_icons:
                if int(row.get("id", -1)) == mid:
                    self.mi_holder.row = row
                    break
            else:
                self.mi_holder.row = {"id": mid}

        # 背景
        sid = ud.get("stageId")
        if isinstance(sid, int):
            for row in self._stages:
                if int(row.get("id", -1)) == sid:
                    self.st_holder.row = row
                    break
            else:
                self.st_holder.row = {"id": sid}

        self._update_np_label()
        self._update_tr_slot_label(0)
        self._update_tr_slot_label(1)
        self._update_tr_slot_label(2)
        self._update_sv_label()
        self._update_mi_label()
        self._update_st_label()

        self._sync_penguins_from_save()
        self._on_np_changed()
        self._on_tr_main_changed()
        self._on_sv_changed()
        self._on_mi_changed()
        self._on_st_changed()

    def _sync_penguins_from_save(self) -> None:
        if not self._data:
            for sp in self._penguin_spins:
                sp.setValue(0)
            return
        for sp, pid in zip(self._penguin_spins, PENGUIN_ITEM_IDS, strict=True):
            n = sum_item_stock(self._data, item_kind=PENGUIN_ITEM_KIND, item_id=pid)
            sp.blockSignals(True)
            sp.setValue(max(0, min(n, sp.maximum())))
            sp.blockSignals(False)

    # ------------------------------------------------------------------
    # DDS 预览
    # ------------------------------------------------------------------

    def _tool(self) -> Path | None:
        return self._get_tool_path()

    def _set_preview(self, label: QLabel, dds_path: Path | None) -> None:
        tool = self._tool()
        label.clear()
        if dds_path is None or not dds_path.is_file():
            label.setText("无预览图")
            return
        if tool is None and not quicktex_available():
            label.setText("配置 quicktex 或 compressonator 后可预览 DDS")
            return
        pm = dds_to_pixmap(acus_root=self._acus_root, compressonatorcli_path=tool, dds_path=dds_path)
        if pm is None:
            label.setText("预览失败")
            return
        label.setPixmap(pm.scaled(280, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        label.setText("")

    def _on_np_changed(self) -> None:
        row = self.np_holder.row
        if row is None:
            self._set_preview(self.np_preview, None)
            return
        # 如果只设置了 id（来自存档原值未匹配到 catalog），不预览
        if "xml_relpath" not in row and "xml_path" not in row:
            self._set_preview(self.np_preview, None)
            return
        # 跨 opt catalog 可能没有完整 xml_path，用 resolve_row_image_dds 搜索
        dds = resolve_row_image_dds(game_root=self._game_root, row=row)
        self._set_preview(self.np_preview, dds)

    def _on_tr_main_changed(self) -> None:
        row = self.tr_main_holder.row
        if row is None:
            self._set_preview(self.tr_preview, None)
            return
        if "xml_relpath" not in row and "xml_path" not in row:
            self._set_preview(self.tr_preview, None)
            return
        dds = resolve_row_image_dds(game_root=self._game_root, row=row)
        self._set_preview(self.tr_preview, dds)

    def _on_sv_changed(self) -> None:
        row = self.sv_holder.row
        if row is None:
            self._set_preview(self.sv_preview, None)
            return
        xml_path = row.get("xml_path")
        if not xml_path:
            self._set_preview(self.sv_preview, None)
            return
        rel = (row.get("preview_relpath") or "").strip()
        if not rel:
            self._set_preview(self.sv_preview, None)
            return
        dds = Path(xml_path).parent / rel
        self._set_preview(self.sv_preview, dds if dds.is_file() else None)

    def _on_mi_changed(self) -> None:
        row = self.mi_holder.row
        if row is None:
            self._set_preview(self.mi_preview, None)
            return
        xml_path = row.get("xml_path")
        if not xml_path:
            self._set_preview(self.mi_preview, None)
            return
        rel = (row.get("image_path") or "").strip()
        if not rel:
            self._set_preview(self.mi_preview, None)
            return
        dds = Path(xml_path).parent / rel
        self._set_preview(self.mi_preview, dds if dds.is_file() else None)

    def _on_st_changed(self) -> None:
        row = self.st_holder.row
        if row is None:
            self._set_preview(self.st_preview, None)
            return
        xml_path = row.get("xml_path")
        if not xml_path:
            self._set_preview(self.st_preview, None)
            return
        rel = (row.get("image_path") or "").strip()
        if not rel:
            self._set_preview(self.st_preview, None)
            return
        dds = Path(xml_path).parent / rel
        self._set_preview(self.st_preview, dds if dds.is_file() else None)

    # ------------------------------------------------------------------
    # 保存
    # ------------------------------------------------------------------

    def _apply(self) -> None:
        if not self._data:
            fly_warning(self, "提示", "请先选择存档 JSON")
            return

        # 名牌
        np_row = self.np_holder.row
        if np_row is None:
            fly_warning(self, "提示", "请选择名牌")
            return
        np_id = int(np_row.get("id", -1))
        if np_id < 0:
            fly_warning(self, "提示", "请选择有效的名牌")
            return

        # 称号
        main_row = self.tr_main_holder.row
        if main_row is None:
            fly_warning(self, "提示", "请选择主称号")
            return
        main_id = int(main_row.get("id", -1))
        if main_id < 0:
            fly_warning(self, "提示", "请选择有效的主称号")
            return
        sub1_row = self.tr_sub1_holder.row
        sub1_id = int(sub1_row.get("id", -1)) if sub1_row and sub1_row.get("id") is not None else -1
        sub2_row = self.tr_sub2_holder.row
        sub2_id = int(sub2_row.get("id", -1)) if sub2_row and sub2_row.get("id") is not None else -1

        # 系统语音
        sv_row = self.sv_holder.row
        if sv_row is None:
            fly_warning(self, "提示", "请选择系统语音")
            return
        voice_id = int(sv_row.get("id", -1))
        if voice_id < 0:
            fly_warning(self, "提示", "请选择有效的系统语音")
            return

        # 跑图小人
        mi_row = self.mi_holder.row
        if mi_row is None:
            fly_warning(self, "提示", "请选择跑图小人")
            return
        map_icon_id = int(mi_row.get("id", -1))
        if map_icon_id < 0:
            fly_warning(self, "提示", "请选择有效的跑图小人")
            return

        # 背景
        st_row = self.st_holder.row
        if st_row is None:
            fly_warning(self, "提示", "请选择背景")
            return
        stage_id = int(st_row.get("id", -1))
        if stage_id < 0:
            fly_warning(self, "提示", "请选择有效的背景")
            return

        set_equipped_nameplate(self._data, np_id)
        set_equipped_trophies(self._data, main_id, sub1_id, sub2_id)
        set_equipped_voice(self._data, voice_id)
        set_equipped_map_icon(self._data, map_icon_id)
        set_equipped_stage(self._data, stage_id)

        stocks = {pid: sp.value() for sp, pid in zip(self._penguin_spins, PENGUIN_ITEM_IDS, strict=True)}
        set_penguin_stocks(self._data, stocks)

        out, _ = QFileDialog.getSaveFileName(
            self,
            "另存为",
            str(self._save_path.with_name(self._save_path.stem + "_patched.json")) if self._save_path else "patched.json",
            "JSON (*.json)",
        )
        if not out:
            return
        try:
            save_save(out, self._data, indent=None)
        except Exception as e:
            fly_critical(self, "写入失败", str(e))
            return
        fly_message(self, "完成", f"已写入：\n{out}")


class SavePatchDialog(FluentCaptionDialog):
    """独立弹窗版存档编辑器（兼容）；主窗口请使用 SettingsPage 内嵌面板。"""

    def __init__(
        self,
        *,
        acus_root: Path,
        game_root: Path,
        get_tool_path,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("存档编辑器")
        self.setModal(True)
        self.resize(760, 680)
        self._panel = SavePatchPanel(
            acus_root=acus_root,
            game_root=game_root,
            get_tool_path=get_tool_path,
            parent=self,
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*fluent_caption_content_margins())
        layout.addWidget(self._panel)