from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

from PyQt6.QtCore import QPoint, Qt, QModelIndex, QSortFilterProxyModel, QTimer
from PyQt6.QtGui import QColor, QPixmap, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    Action,
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox as FluentComboBox,
    FluentIcon as FIF,
    MenuAnimationType,
    PushButton,
    RoundMenu,
    SearchLineEdit,
    TabWidget,
    TableView,
    isDarkTheme,
)

from .chara_add_dialog import (
    CharaAddDialog,
    chara_master_xml_path,
    chara_variant_display_name,
    remove_chara_variant_slot as remove_chara_variant_from_xml,
)
from .fluent_dialogs import fly_critical, fly_message, fly_question
from .music_cards_view import MusicCardsView
from .github_sheet_dialog import GithubSheetDialog

from ..chara_delete import delete_chara_from_acus
from ..music_delete import execute_music_deletion, plan_music_deletion
from ..trophy_delete import execute_trophy_deletion, plan_trophy_deletion
from ..acus_scan import (
    CharaItem,
    DdsImageItem,
    EventItem,
    IdStr,
    MapItem,
    MapBonusItem,
    MusicItem,
    NamePlateItem,
    QuestItem,
    RewardItem,
    TrophyItem,
    scan_charas,
    scan_dds_images,
    scan_events,
    scan_maps,
    scan_map_bonuses,
    scan_music,
    scan_nameplates,
    scan_quests,
    scan_rewards,
    scan_trophies,
)
from ..dds_preview import dds_to_pixmap
from ..dds_quicktex import quicktex_available
from ..game_data_index import GameDataIndex
from ..trophy_preview import load_trophy_frame_pixmap, render_trophy_text_preview

_CHARA_TAB_ADD = "__chara_tab_add__"

_KIND_DEFS: tuple[tuple[str, str], ...] = (
    ("事件", "Event"),
    ("任务", "Quest"),
    ("地图", "Map"),
    ("歌曲", "Music"),
    ("角色", "Chara"),
    ("称号", "Trophy"),
    ("名牌", "NamePlate"),
    ("奖励", "Reward"),
    ("加成", "MapBonus"),
    ("DDS 贴图", "DDSImage"),
)


class WidthScaledPreviewLabel(QLabel):
    """按容器宽度缩放 DDS 图，避免过宽 pixmap 撑死分割条。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._source: QPixmap | None = None

    def clear_source(self) -> None:
        self._source = None
        super().setPixmap(QPixmap())
        self.setMinimumHeight(0)

    def setSourcePixmap(self, pm: QPixmap | None) -> None:
        self._source = pm if pm is not None and not pm.isNull() else None
        self._apply_scale()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_scale()

    def _apply_scale(self) -> None:
        if self._source is None or self._source.isNull():
            super().setPixmap(QPixmap())
            self.setMinimumHeight(0)
            return
        w = self.width()
        if w <= 1:
            par = self.parentWidget()
            w = max(120, (par.width() * 4 // 5) if par is not None and par.width() > 0 else 360)
        scaled = self._source.scaledToWidth(w, Qt.TransformationMode.SmoothTransformation)
        super().setPixmap(scaled)
        self.setMinimumHeight(scaled.height())


class CharaDdsPreviewWidget(QWidget):
    """左：ddsFile0；右：ddsFile1 / ddsFile2 上下等高，总高与左侧一致。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pm: tuple[QPixmap | None, QPixmap | None, QPixmap | None] = (None, None, None)
        self._left = QLabel()
        self._r1 = QLabel()
        self._r2 = QLabel()
        border = "#4B5563" if isDarkTheme() else "#D1D5DB"
        for lb in (self._left, self._r1, self._r2):
            lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lb.setStyleSheet(f"border: 1px solid {border}; border-radius: 4px;")
        self._right_wrap = QWidget()
        rv = QVBoxLayout(self._right_wrap)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        rv.addWidget(self._r1, 1)
        rv.addWidget(self._r2, 1)
        lay = QHBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._left, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self._right_wrap, 0, Qt.AlignmentFlag.AlignTop)

    def clear(self) -> None:
        self._pm = (None, None, None)
        for lb in (self._left, self._r1, self._r2):
            lb.clear()
            lb.setText("")
        self.setMinimumHeight(0)

    def set_pixmaps(self, p0: QPixmap | None, p1: QPixmap | None, p2: QPixmap | None) -> None:
        self._pm = (p0, p1, p2)
        self._relayout()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()

    def _fit_in(self, pm: QPixmap | None, rw: int, rh: int) -> QPixmap:
        if pm is None or pm.isNull() or rw < 1 or rh < 1:
            return QPixmap()
        return pm.scaled(
            rw,
            rh,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _relayout(self) -> None:
        W = self.width()
        if W < 32:
            return
        lay = self.layout()
        gap = lay.spacing() if lay is not None else 8
        col_w = max(1, (W - gap) // 2)
        p0, p1, p2 = self._pm
        if p0 is not None and not p0.isNull():
            s0 = p0.scaledToWidth(col_w, Qt.TransformationMode.SmoothTransformation)
            h = max(s0.height(), 1)
        else:
            s0 = QPixmap()
            h = 160
        h1 = h // 2
        h2 = h - h1
        s1 = self._fit_in(p1, col_w, h1)
        s2 = self._fit_in(p2, col_w, h2)
        self._left.setPixmap(s0)
        self._left.setFixedSize(col_w, h)
        self._right_wrap.setFixedSize(col_w, h)
        self._r1.setPixmap(s1)
        self._r1.setFixedSize(col_w, h1)
        self._r2.setPixmap(s2)
        self._r2.setFixedSize(col_w, h2)
        self.setMinimumHeight(h)


class ManagerWidget(QWidget):
    """
    ACUS 浏览器组件（表格 + DDS 预览 + 属性表）。

    - 可作为独立页面使用（带顶部类型/搜索/刷新）
    - 也可作为“嵌入式”使用（由外层导航控制类型/搜索/刷新）
    """

    def __init__(
        self,
        *,
        acus_root: Path,
        get_tool_path,
        get_game_index: Callable[[], GameDataIndex | None] | None = None,
        get_game_root: Callable[[], str] | None = None,
        embedded: bool = False,
    ) -> None:
        super().__init__()
        self._acus_root = acus_root
        self._get_tool_path = get_tool_path  # callable returning Path|None
        self._get_game_index = get_game_index or (lambda: None)
        self._get_game_root = get_game_root or (lambda: "")
        self._embedded = embedded

        self.kind = FluentComboBox()
        self.kind.blockSignals(True)
        for label, key in _KIND_DEFS:
            self.kind.addItem(label, None, key)
        self.kind.blockSignals(False)
        self.kind.currentIndexChanged.connect(self._on_kind_changed)

        self.event_filter = FluentComboBox()
        for t in ("全部", "ULT/WE曲解锁", "地图解禁", "宣传(含DDS)", "其它"):
            self.event_filter.addItem(t, None, None)
        self.event_filter.currentIndexChanged.connect(self.reload)
        self.event_bar = QWidget()
        ev_row = QHBoxLayout(self.event_bar)
        ev_row.setContentsMargins(0, 0, 0, 0)
        ev_row.addWidget(CaptionLabel("事件分类"))
        ev_row.addWidget(self.event_filter, stretch=1)
        self.event_bar.setVisible(False)

        self.reward_type_filter = FluentComboBox()
        for text, data in (
            ("全部类型", None),
            ("功能票", 1),
            ("称号", 2),
            ("角色", 3),
            ("姓名牌", 5),
            ("乐曲解锁", 6),
            ("地图图标", 7),
            ("头像配件", 9),
            ("场景", 13),
        ):
            self.reward_type_filter.addItem(text, None, data)
        self.reward_type_filter.currentIndexChanged.connect(self.reload)
        self.reward_bar = QWidget()
        rr = QHBoxLayout(self.reward_bar)
        rr.setContentsMargins(0, 0, 0, 0)
        rr.addWidget(CaptionLabel("奖励类型"))
        rr.addWidget(self.reward_type_filter, stretch=1)
        self.reward_bar.setVisible(False)

        self.search = SearchLineEdit()
        self.search.setPlaceholderText(
            "搜索：ID / 名称 / 关键字（地图双击编辑；歌曲双击生成课题称号）"
        )
        self.search.textChanged.connect(self._apply_filter)

        self.refresh_btn = PushButton("刷新")
        self.refresh_btn.clicked.connect(self.reload)
        self._game_music_btn = PushButton("游戏乐曲资源…")
        self._game_music_btn.setToolTip("只读浏览游戏目录内已扫描数据包中的全部乐曲（含版本标签、流派）")
        self._game_music_btn.clicked.connect(self._on_game_music_browser)
        self._game_music_btn.setVisible(False)

        top = QHBoxLayout()
        top.addWidget(CaptionLabel("类型"))
        top.addWidget(self.kind)
        top.addSpacing(8)
        top.addWidget(CaptionLabel("搜索"))
        top.addWidget(self.search, stretch=1)
        top.addStretch(1)
        top.addWidget(self._game_music_btn)
        top.addWidget(self.refresh_btn)

        self.model = QStandardItemModel(0, 4, self)
        self.model.setHorizontalHeaderLabels(["ID", "名称", "分类", "来源(XML)"])
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)  # all columns

        self.table = TableView(self)
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft)
        self.table.selectionModel().selectionChanged.connect(self._on_select)
        self.table.doubleClicked.connect(self._on_table_double_clicked)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_context_menu)

        self.preview_section = QWidget()
        pv = QVBoxLayout(self.preview_section)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(8)
        self.simple_preview = WidthScaledPreviewLabel()
        self.chara_variant_tabs = TabWidget(self)
        self.chara_variant_tabs.setTabsClosable(False)
        self.chara_variant_tabs.tabBar.setAddButtonVisible(False)
        tb_view = self.chara_variant_tabs.tabBar.view
        tb_view.setObjectName("charaVariantTabStrip")
        tb_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tb_view.customContextMenuRequested.connect(self._on_chara_variant_tab_context_menu)
        self.chara_variant_tabs.currentChanged.connect(self._on_chara_variant_changed)
        self._style_chara_variant_tabs()
        self.chara_triple = CharaDdsPreviewWidget()
        pv.addWidget(self.chara_variant_tabs)
        pv.addWidget(self.simple_preview)
        pv.addWidget(self.chara_triple)
        self.preview_section.setVisible(False)

        self._attrs_model = QStandardItemModel(0, 2, self)
        self._attrs_model.setHorizontalHeaderLabels(["属性", "值"])
        self.attrs_table = TableView(self)
        self.attrs_table.setModel(self._attrs_model)
        self.attrs_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.attrs_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.attrs_table.horizontalHeader().setStretchLastSection(True)
        self.attrs_table.verticalHeader().setVisible(False)
        self.attrs_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.attrs_table.setAlternatingRowColors(True)
        self.attrs_table.setWordWrap(True)
        self.attrs_table.setShowGrid(False)

        self._selected_chara: CharaItem | None = None
        self._chara_variant_map: dict[int, int] = {}

        # right panel：上 DDS（有则显示），下属性表
        right_card = CardWidget()
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(12, 6, 12, 12)
        right_layout.addWidget(self.preview_section, stretch=0)
        right_layout.addWidget(BodyLabel("属性"))
        right_layout.addWidget(self.attrs_table, stretch=1)

        split = QSplitter()
        split.setOrientation(Qt.Orientation.Horizontal)
        split.addWidget(self.table)
        split.addWidget(right_card)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 4)

        self.music_cards_view = MusicCardsView(acus_root=self._acus_root)
        self.music_cards_view.doubleClickedMusic.connect(self._on_music_card_double_clicked)
        self.music_cards_view.musicDeleteRequested.connect(self._on_music_delete_requested)
        self.music_cards_view.musicTrophyRequested.connect(self._on_music_trophy_requested)
        self.music_cards_view.musicJacketReplaceRequested.connect(
            self._on_music_jacket_replace_requested
        )
        self.music_cards_view.musicGithubUploadRequested.connect(
            self._on_music_github_upload_requested
        )

        self._main_stack = QStackedWidget()
        self._main_stack.addWidget(split)
        self._main_stack.addWidget(self.music_cards_view)

        layout = QVBoxLayout(self)
        if not self._embedded:
            layout.addLayout(top)
        layout.addWidget(self.event_bar)
        layout.addWidget(self.reward_bar)
        layout.addWidget(self._main_stack, stretch=1)

        self._items: list[object] = []
        # 不在此调用 reload()：默认分类为「事件」，而主窗口随后会切到实际分类（如歌曲），
        # 否则会先全量扫事件再扫目标分类，冷启动白白多一轮磁盘与表格构建。

    def set_kind(self, kind: str) -> None:
        """
        kind: Event / Map / Music / Chara / …（内部英文 key，与导航一致）
        """
        idx = self.kind.findData(kind)
        if idx >= 0 and idx != self.kind.currentIndex():
            self.kind.setCurrentIndex(idx)
        else:
            # still reload if same kind (e.g. external refresh)
            self.reload()

    def _kind_key(self) -> str:
        d = self.kind.currentData()
        return str(d) if d is not None else "Event"

    def set_search_text(self, text: str) -> None:
        if self.search.text() != text:
            self.search.setText(text)
        else:
            self._apply_filter()

    def _on_kind_changed(self) -> None:
        self.reload()

    def _on_game_music_browser(self) -> None:
        from .game_music_browser_dialog import GameMusicBrowserDialog

        raw = (self._get_game_root() or "").strip()
        if not raw:
            fly_message(self, "提示", "请先在【设置】中配置「游戏数据目录」。")
            return
        dlg = GameMusicBrowserDialog(
            game_root=Path(raw).expanduser(),
            get_index=self._get_game_index,
            parent=self,
        )
        dlg.exec()

    def reload(self) -> None:
        self.model.removeRows(0, self.model.rowCount())
        self._attrs_model.removeRows(0, self._attrs_model.rowCount())
        self._hide_preview_section()
        self.simple_preview.clear_source()
        self.chara_triple.clear()

        k = self._kind_key()
        self.event_bar.setVisible(k == "Event")
        self.reward_bar.setVisible(k == "Reward")

        if k == "Quest":
            self.model.setHorizontalHeaderLabels(["ID", "名称", "角色条件", "奖励阶段", "来源(XML)"])
        elif k == "Music":
            self.model.setHorizontalHeaderLabels(["ID", "曲名", "艺术家", "流派", "发布日期", "难度", "CueFile", "来源(XML)"])
        elif k == "Trophy":
            self.model.setHorizontalHeaderLabels(["ID", "名称", "稀有度", "来源(XML)"])
        elif k == "Reward":
            self.model.setHorizontalHeaderLabels(["ID", "名称", "奖励类型", "关联目标", "来源(XML)"])
        elif k == "MapBonus":
            self.model.setHorizontalHeaderLabels(["ID", "名称", "条件数", "type摘要", "来源(XML)"])
        elif k == "Chara":
            self.model.setHorizontalHeaderLabels(["ID", "名称"])
        else:
            self.model.setHorizontalHeaderLabels(["ID", "名称", "分类", "来源(XML)"])

        if k == "Quest":
            items = scan_quests(self._acus_root)
            self._items = items
            for it in items:
                self._append_quest_row(it)
        elif k == "Event":
            items = scan_events(self._acus_root)
            self._items = []
            bucket_label = self.event_filter.currentText()
            for it in items:
                if bucket_label == "ULT/WE曲解锁" and it.filter_bucket != "ult_we":
                    continue
                if bucket_label == "地图解禁" and it.filter_bucket != "map_unlock":
                    continue
                if bucket_label == "宣传(含DDS)" and it.filter_bucket != "promo":
                    continue
                if bucket_label == "其它" and it.filter_bucket != "other":
                    continue
                self._append_row(it.name.id, it.name.str, it.category_label, it.xml_path, it)
                self._items.append(it)
        elif k == "Map":
            items = scan_maps(self._acus_root)
            self._items = items
            for it in items:
                kind = it.map_filter.str if it.map_filter else ""
                self._append_row(it.name.id, it.name.str, kind, it.xml_path, it)
        elif k == "Music":
            items = scan_music(self._acus_root)
            self._items = items
        elif k == "Chara":
            items = scan_charas(self._acus_root)
            self._items = items
            for it in items:
                self._append_chara_row(it)
        elif k == "Trophy":
            items = scan_trophies(self._acus_root)
            self._items = items
            for it in items:
                rare = str(it.rare_type) if it.rare_type is not None else ""
                self._append_row(it.name.id, it.name.str, rare, it.xml_path, it)
        elif k == "NamePlate":
            items = scan_nameplates(self._acus_root)
            self._items = items
            for it in items:
                self._append_row(it.name.id, it.name.str, "NamePlate装饰", it.xml_path, it)
        elif k == "Reward":
            items = scan_rewards(self._acus_root)
            type_f = self.reward_type_filter.currentData()
            self._items = []
            for it in items:
                if type_f is not None and it.substance_type != type_f:
                    continue
                self._append_reward_row(it)
                self._items.append(it)
        elif k == "MapBonus":
            items = scan_map_bonuses(self._acus_root)
            self._items = items
            for it in items:
                self._append_mapbonus_row(it)
        else:
            items = scan_dds_images(self._acus_root)
            self._items = items
            for it in items:
                self._append_row(it.name.id, it.name.str, "DDSImage", it.xml_path, it)

        if k == "Music":
            self._main_stack.setCurrentIndex(1)
        else:
            self._main_stack.setCurrentIndex(0)
            self.music_cards_view.set_items([], self._get_tool_path)

        self._game_music_btn.setVisible(k == "Music" and not self._embedded)

        self._apply_filter()
        self._resize_columns_safely()
        if k != "Music" and self.proxy.rowCount() > 0:
            self.table.selectRow(0)

    def _hide_preview_section(self) -> None:
        self.preview_section.setVisible(False)
        self.simple_preview.setVisible(False)
        self.chara_variant_tabs.setVisible(False)
        self.chara_triple.setVisible(False)

    def _style_chara_variant_tabs(self) -> None:
        """标签条与选中态：与右侧卡片背景区分开，便于辨认。"""
        strip = self.chara_variant_tabs.tabBar.view
        if isDarkTheme():
            strip.setStyleSheet(
                "QWidget#charaVariantTabStrip {"
                " background-color: rgba(255, 255, 255, 0.07);"
                " border: 1px solid rgba(255, 255, 255, 0.14);"
                " border-radius: 8px;"
                "}"
            )
        else:
            strip.setStyleSheet(
                "QWidget#charaVariantTabStrip {"
                " background-color: #eef2f7;"
                " border: 1px solid #d8dee9;"
                " border-radius: 8px;"
                "}"
            )
        # 参数顺序：浅色主题下的选中底色、深色主题下的选中底色
        self.chara_variant_tabs.setTabSelectedBackgroundColor(
            QColor(191, 219, 254),
            QColor(52, 73, 112),
        )

    def _rel_acus_path(self, p: Path) -> str:
        try:
            return str(p.relative_to(self._acus_root))
        except ValueError:
            return str(p)

    @staticmethod
    def _fmt_id_str(x: IdStr | None) -> str:
        if x is None:
            return "—"
        if x.str:
            return f"{x.id} · {x.str}"
        return str(x.id)

    def _append_attr_row(self, label: str, value: str) -> None:
        c0 = QStandardItem(label)
        c1 = QStandardItem(value)
        c0.setEditable(False)
        c1.setEditable(False)
        self._attrs_model.appendRow([c0, c1])

    def _fill_attrs_table(self, it: object) -> None:
        self._attrs_model.removeRows(0, self._attrs_model.rowCount())
        for label, val in self._attr_rows(it):
            self._append_attr_row(label, val)
        self.attrs_table.resizeColumnsToContents()

    def _attr_rows(self, it: object) -> list[tuple[str, str]]:
        if isinstance(it, QuestItem):
            return [
                ("任务名", it.name.str or "—"),
                ("任务 ID", str(it.name.id)),
                ("参与角色", it.chara_label),
                ("奖励阶段摘要", it.tier_label),
                ("XML", self._rel_acus_path(it.xml_path)),
            ]
        if isinstance(it, EventItem):
            et = str(it.event_type) if it.event_type is not None else "—"
            banner = str(it.dds_banner_id) if it.dds_banner_id is not None else "—"
            img = it.info_image_path.strip() or "—"
            return [
                ("名称", it.name.str or "—"),
                ("事件 ID", str(it.name.id)),
                ("substances 类型", et),
                ("列表分类", it.category_label),
                ("关联地图", self._fmt_id_str(it.map_name)),
                ("宣传图路径", img),
                ("MapFilter", self._fmt_id_str(it.map_filter)),
                ("Banner ID", banner),
                ("XML", self._rel_acus_path(it.xml_path)),
            ]
        if isinstance(it, MusicItem):
            artist = it.artist.str if it.artist else "—"
            genres = " / ".join(it.genres) if it.genres else "—"
            levels = " | ".join(it.levels) if it.levels else "—"
            cue = self._fmt_id_str(it.cue_file) if it.cue_file else "—"
            jacket = it.jacket_path.strip() or "—"
            stage = self._fmt_id_str(it.stage) if it.stage else "—"
            ult = "是" if it.has_ultima else "否"
            ver = it.release_tag.str if it.release_tag else "—"
            return [
                ("曲名", it.name.str or "—"),
                ("乐曲 ID", str(it.name.id)),
                ("艺术家", artist),
                ("舞台", stage),
                ("流派", genres),
                ("版本", ver),
                ("发布日期", it.release_date or "—"),
                ("难度", levels),
                ("Cue 文件", cue),
                ("封面 jacket", jacket),
                ("含 Ultima 谱", ult),
                ("XML", self._rel_acus_path(it.xml_path)),
            ]
        if isinstance(it, MapItem):
            mf = self._fmt_id_str(it.map_filter) if it.map_filter else "—"
            return [
                ("地图名称", it.name.str or "—"),
                ("地图 ID", str(it.name.id)),
                ("MapFilter", mf),
                ("XML", self._rel_acus_path(it.xml_path)),
            ]
        if isinstance(it, DdsImageItem):
            return [
                ("资源显示名", it.name.str or "—"),
                ("ddsImage ID", str(it.name.id)),
                ("ddsFile0", it.dds0 or "—"),
                ("ddsFile1", it.dds1 or "—"),
                ("ddsFile2", it.dds2 or "—"),
                ("XML", self._rel_acus_path(it.xml_path)),
            ]
        if isinstance(it, TrophyItem):
            rare = str(it.rare_type) if it.rare_type is not None else "—"
            img = it.image_path.strip() or "（无图称号）"
            return [
                ("称号名", it.name.str or "—"),
                ("称号 ID", str(it.name.id)),
                ("稀有度类型", rare),
                ("说明", it.explain_text or "—"),
                ("贴图路径", img),
                ("XML", self._rel_acus_path(it.xml_path)),
            ]
        if isinstance(it, NamePlateItem):
            img = it.image_path.strip() or "—"
            return [
                ("名牌名", it.name.str or "—"),
                ("名牌 ID", str(it.name.id)),
                ("图片路径", img),
                ("XML", self._rel_acus_path(it.xml_path)),
            ]
        if isinstance(it, RewardItem):
            st = str(it.substance_type) if it.substance_type is not None else "—"
            mc = (
                f"{it.music_course_id} · {it.music_course_str}"
                if it.music_course_id is not None
                else "—"
            )
            return [
                ("奖励名", it.name.str or "—"),
                ("奖励 ID", str(it.name.id)),
                ("物质类型代码", st),
                ("奖励类型", it.type_label),
                ("关联摘要", it.target_summary),
                ("课题/关联乐曲", mc),
                ("XML", self._rel_acus_path(it.xml_path)),
            ]
        if isinstance(it, MapBonusItem):
            return [
                ("MapBonus 名称", it.name.str or "—"),
                ("MapBonus ID", str(it.name.id)),
                ("substances 条数", str(it.substance_count)),
                ("type 摘要", it.type_summary or "—"),
                ("XML", self._rel_acus_path(it.xml_path)),
            ]
        return [("类型", type(it).__name__), ("摘要", str(it))]

    def _chara_attr_rows(self, it: CharaItem, meta: dict[str, str]) -> list[tuple[str, str]]:
        return [
            ("名称", meta.get("name", "—")),
            ("角色 ID", meta.get("id", "—")),
            ("默认立绘键", it.default_image_key or "—"),
            ("发行标签", meta.get("releaseTag", "—")),
            ("画师", meta.get("illustrator", "—")),
            ("作品/所属", meta.get("works", "—")),
            ("XML", self._rel_acus_path(it.xml_path)),
        ]

    def _resolve_dds_path(self, it: object) -> Path | None:
        if isinstance(it, DdsImageItem):
            rel = it.dds0.strip()
            return it.xml_path.parent / rel if rel else None
        if isinstance(it, MusicItem) and it.jacket_path.strip():
            return it.xml_path.parent / it.jacket_path.strip()
        if isinstance(it, NamePlateItem) and it.image_path.strip():
            p = it.xml_path.parent / it.image_path.strip()
            return p if p.is_file() else None
        if isinstance(it, EventItem):
            return it.promo_dds_path
        if isinstance(it, TrophyItem) and it.image_path.strip():
            p = it.xml_path.parent / it.image_path.strip()
            return p if p.is_file() else None
        return None

    def _trophy_source_pixmap(self, it: TrophyItem) -> tuple[QPixmap | None, str | None]:
        tool = self._get_tool_path()
        qt_ok = quicktex_available()
        img_rel = (it.image_path or "").strip()
        if img_rel:
            cand = it.xml_path.parent / img_rel
            if not cand.is_file():
                return None, "贴图路径指向的文件不存在"
            if tool is None and not qt_ok:
                return None, "预览称号贴图需 quicktex 或 compressonatorcli"
            pm = dds_to_pixmap(
                acus_root=self._acus_root,
                compressonatorcli_path=tool,
                dds_path=cand,
                restrict=False,
            )
            if pm is None or pm.isNull():
                return None, f"DDS 解码失败：{cand.name}"
            return pm, None
        frame_pm = load_trophy_frame_pixmap(it.rare_type)
        if frame_pm is None:
            return None, "缺少稀有度底图资源（static/trophy），无法预览无图称号"
        pm = render_trophy_text_preview(frame=frame_pm, display_name=it.name.str or "—")
        if pm is None or pm.isNull():
            return None, "无法生成无图称号预览"
        return pm, None

    def _simple_preview_pixmap_and_hint(self, it: object) -> tuple[QPixmap | None, str | None]:
        if self._kind_key() in ("Map", "Reward", "Quest"):
            return None, None
        if isinstance(it, TrophyItem):
            try:
                return self._trophy_source_pixmap(it)
            except Exception as e:
                return None, f"称号预览异常：{e}"
        dds_path = self._resolve_dds_path(it)
        if dds_path is None:
            return None, None
        tool = self._get_tool_path()
        if tool is None and not quicktex_available():
            return None, "预览需安装 quicktex 或在【设置】中配置 compressonatorcli"
        pm = dds_to_pixmap(
            acus_root=self._acus_root,
            compressonatorcli_path=tool,
            dds_path=dds_path,
            restrict=False,
        )
        if pm is None or pm.isNull():
            return None, f"DDS 解码失败：{dds_path.name}"
        return pm, None

    def _resize_columns_safely(self) -> None:
        """
        大表格上 `resizeColumnsToContents()` 代价很高，可能导致 UI 长时间无响应。
        这里对小数据量保留自动适配，大数据量走固定宽度兜底。
        """
        rows = self.model.rowCount()
        cols = self.model.columnCount()
        if cols <= 0:
            return
        if rows <= 300:
            self.table.resizeColumnsToContents()
            return
        # 兜底宽度：避免在大量 XML 条目时卡在全量内容测量
        widths = [110, 280, 180, 420, 240, 200, 240, 320]
        for i in range(cols):
            self.table.setColumnWidth(i, widths[i] if i < len(widths) else 180)

    def _append_row(self, id_: int, name: str, kind: str, xml_path: Path, payload: object) -> None:
        row = self.model.rowCount()
        self.model.insertRow(row)

        c0 = QStandardItem(str(id_))
        c1 = QStandardItem(name)
        c2 = QStandardItem(kind)
        c3 = QStandardItem(str(xml_path.relative_to(self._acus_root)))

        # store payload on first column
        c0.setData(payload, Qt.ItemDataRole.UserRole)

        for i, c in enumerate((c0, c1, c2, c3)):
            c.setEditable(False)
            self.model.setItem(row, i, c)

    def _append_music_row(self, it: MusicItem) -> None:
        row = self.model.rowCount()
        self.model.insertRow(row)

        artist = it.artist.str if it.artist else ""
        genres = "/".join(it.genres)
        levels = " | ".join(it.levels)
        cue = f"{it.cue_file.id}:{it.cue_file.str}" if it.cue_file else ""
        src = str(it.xml_path.relative_to(self._acus_root))

        cols = [
            QStandardItem(str(it.name.id)),
            QStandardItem(it.name.str),
            QStandardItem(artist),
            QStandardItem(genres),
            QStandardItem(it.release_date),
            QStandardItem(levels),
            QStandardItem(cue),
            QStandardItem(src),
        ]
        cols[0].setData(it, Qt.ItemDataRole.UserRole)
        for i, c in enumerate(cols):
            c.setEditable(False)
            self.model.setItem(row, i, c)

    def _append_quest_row(self, it: QuestItem) -> None:
        row = self.model.rowCount()
        self.model.insertRow(row)
        src = str(it.xml_path.relative_to(self._acus_root))
        cols = [
            QStandardItem(str(it.name.id)),
            QStandardItem(it.name.str),
            QStandardItem(it.chara_label),
            QStandardItem(it.tier_label),
            QStandardItem(src),
        ]
        cols[0].setData(it, Qt.ItemDataRole.UserRole)
        for i, c in enumerate(cols):
            c.setEditable(False)
            self.model.setItem(row, i, c)

    def _append_reward_row(self, it: RewardItem) -> None:
        row = self.model.rowCount()
        self.model.insertRow(row)
        src = str(it.xml_path.relative_to(self._acus_root))
        cols = [
            QStandardItem(str(it.name.id)),
            QStandardItem(it.name.str),
            QStandardItem(it.type_label),
            QStandardItem(it.target_summary),
            QStandardItem(src),
        ]
        cols[0].setData(it, Qt.ItemDataRole.UserRole)
        for i, c in enumerate(cols):
            c.setEditable(False)
            self.model.setItem(row, i, c)

    def _append_mapbonus_row(self, it: MapBonusItem) -> None:
        row = self.model.rowCount()
        self.model.insertRow(row)
        src = str(it.xml_path.relative_to(self._acus_root))
        cols = [
            QStandardItem(str(it.name.id)),
            QStandardItem(it.name.str),
            QStandardItem(str(it.substance_count)),
            QStandardItem(it.type_summary),
            QStandardItem(src),
        ]
        cols[0].setData(it, Qt.ItemDataRole.UserRole)
        for i, c in enumerate(cols):
            c.setEditable(False)
            self.model.setItem(row, i, c)

    def _append_chara_row(self, it: CharaItem) -> None:
        row = self.model.rowCount()
        self.model.insertRow(row)
        c0 = QStandardItem(str(it.name.id))
        c1 = QStandardItem(it.name.str)
        c0.setData(it, Qt.ItemDataRole.UserRole)
        c0.setEditable(False)
        c1.setEditable(False)
        self.model.setItem(row, 0, c0)
        self.model.setItem(row, 1, c1)

    def _apply_filter(self) -> None:
        if self._kind_key() == "Music":
            self._rebuild_music_cards()
        else:
            self.proxy.setFilterFixedString(self.search.text().strip())

    def _music_matches(self, it: MusicItem, needle: str) -> bool:
        if not needle:
            return True
        parts = [
            str(it.name.id),
            (it.name.str or "").lower(),
            (it.artist.str.lower() if it.artist else ""),
            " / ".join(it.genres).lower(),
            (it.release_date or "").lower(),
            (it.release_tag.str.lower() if it.release_tag else ""),
            " | ".join(it.levels).lower(),
            self._rel_acus_path(it.xml_path).lower(),
        ]
        return any(needle in p for p in parts)

    def _rebuild_music_cards(self) -> None:
        needle = self.search.text().strip().lower()
        items = [it for it in self._items if isinstance(it, MusicItem) and self._music_matches(it, needle)]
        self.music_cards_view.set_items(items, self._get_tool_path)

    def _on_music_card_double_clicked(self, it: object) -> None:
        if not isinstance(it, MusicItem):
            return
        from .music_trophy_dialog import MusicTrophyDialog

        dlg = MusicTrophyDialog(
            acus_root=self._acus_root,
            preselect=it,
            parent=self.window(),
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.reload()

    def _on_music_trophy_requested(self, it: object) -> None:
        if not isinstance(it, MusicItem):
            return
        from .music_trophy_dialog import MusicTrophyDialog

        dlg = MusicTrophyDialog(
            acus_root=self._acus_root,
            preselect=it,
            parent=self.window(),
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.reload()

    def _on_music_jacket_replace_requested(self, it: object) -> None:
        if not isinstance(it, MusicItem):
            return
        tool = self._get_tool_path()
        if tool is None and not quicktex_available():
            fly_critical(
                self.window(),
                "无法更换封面",
                "未安装 quicktex 且未在【设置】中配置 compressonatorcli，无法将图片转为 BC3 DDS。",
            )
            return
        path, _ = QFileDialog.getOpenFileName(
            self.window(),
            "选择封面（图片或 BC3 DDS）",
            "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp);;BC3 DDS (*.dds);;所有文件 (*.*)",
        )
        if not path:
            return
        from ..music_jacket_replace import apply_music_jacket_image

        try:
            out = apply_music_jacket_image(
                item=it,
                source=Path(path),
                tool_path=tool,
                progress_parent=self.window(),
            )
        except Exception as e:
            fly_critical(self.window(), "更换封面失败", str(e))
            return
        fly_message(self.window(), "已更新封面", f"已写入：\n{out.name}")
        self.reload()

    def _on_music_github_upload_requested(self, it: object) -> None:
        if not isinstance(it, MusicItem):
            return
        GithubSheetDialog.upload_music_item(
            parent=self.window(),
            acus_root=self._acus_root,
            item=it,
        )

    def _on_music_delete_requested(self, it: object) -> None:
        if not isinstance(it, MusicItem):
            return
        plan = plan_music_deletion(self._acus_root, it)
        if plan.music_dir is None or not plan.music_dir.is_dir():
            fly_message(
                self.window(),
                "无法删除",
                "未找到该乐曲在 ACUS/music 下的目录，已中止。",
            )
            return
        lines = plan.summary_lines()
        body = "将执行以下操作：\n\n• " + "\n• ".join(lines) + "\n\n此操作不可撤销，确定删除？"
        if not fly_question(self.window(), "删除乐曲", body):
            return
        try:
            execute_music_deletion(plan)
        except Exception as e:
            fly_critical(self.window(), "删除失败", str(e))
            return
        self.reload()

    def _on_table_context_menu(self, pos: QPoint) -> None:
        k = self._kind_key()
        if k not in ("Chara", "Trophy", "Quest"):
            return
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        src_idx = self.proxy.mapToSource(idx)
        item0 = self.model.item(src_idx.row(), 0)
        if item0 is None:
            return
        payload = item0.data(Qt.ItemDataRole.UserRole)

        menu = RoundMenu(parent=self.table)
        menu.setItemHeight(36)
        vf = menu.view.font()
        vf.setPointSize(max(12, vf.pointSize()))
        menu.view.setFont(vf)
        gpos = self.table.viewport().mapToGlobal(pos)

        if k == "Chara":
            if not isinstance(payload, CharaItem):
                return
            act_del = Action(FIF.DELETE, "删除角色…", self.table)
            act_del.triggered.connect(
                lambda checked=False, p=payload: QTimer.singleShot(0, lambda: self._delete_chara_item(p))
            )
            menu.addAction(act_del)
            menu.exec(gpos, ani=True, aniType=MenuAnimationType.DROP_DOWN)
            return

        if k == "Trophy":
            if not isinstance(payload, TrophyItem):
                return
            act_trophy_only = Action(FIF.DELETE, "删除称号…", self.table)
            act_trophy_only.triggered.connect(
                lambda checked=False, p=payload: QTimer.singleShot(
                    0, lambda: self._delete_trophy_item(p, with_chara=False)
                )
            )
            menu.addAction(act_trophy_only)
            try:
                plan_preview = plan_trophy_deletion(
                    self._acus_root, payload, scan_charas(self._acus_root)
                )
            except ValueError:
                plan_preview = None
            if plan_preview is not None and plan_preview.linked_chara_ids:
                act_both = Action(FIF.PEOPLE, "删除称号并删除关联角色…", self.table)
                act_both.triggered.connect(
                    lambda checked=False, p=payload: QTimer.singleShot(
                        0, lambda: self._delete_trophy_item(p, with_chara=True)
                    )
                )
                menu.addAction(act_both)
            menu.exec(gpos, ani=True, aniType=MenuAnimationType.DROP_DOWN)
            return

        if k == "Quest":
            if not isinstance(payload, QuestItem):
                return
            act_del_q = Action(FIF.DELETE, "删除任务…", self.table)
            act_del_q.triggered.connect(
                lambda checked=False, p=payload: QTimer.singleShot(0, lambda: self._delete_quest_item(p))
            )
            menu.addAction(act_del_q)
            menu.exec(gpos, ani=True, aniType=MenuAnimationType.DROP_DOWN)

    def _delete_trophy_item(self, it: TrophyItem, *, with_chara: bool) -> None:
        try:
            plan = plan_trophy_deletion(self._acus_root, it, scan_charas(self._acus_root))
        except ValueError as e:
            fly_message(self.window(), "无法删除", str(e))
            return
        lines = plan.summary_lines(include_chara=with_chara)
        if with_chara and plan.linked_chara_ids and not plan.chara_items_to_remove:
            lines.append("（未找到可删的角色目录，将仅删除称号）")
        title = "删除称号并删除关联角色" if with_chara else "删除称号"
        body = "将执行以下操作：\n\n• " + "\n• ".join(lines) + "\n\n此操作不可撤销，确定删除？"
        if not fly_question(self.window(), title, body):
            return
        try:
            execute_trophy_deletion(self._acus_root, plan, delete_linked_charas=with_chara)
        except Exception as e:
            fly_critical(self.window(), "删除失败", str(e))
            return
        fly_message(self.window(), "已删除", "已移除所选称号" + ("及关联角色资源。" if with_chara else "。"))
        self.reload()

    def _delete_quest_item(self, it: QuestItem) -> None:
        qdir = it.xml_path.parent
        if not qdir.is_dir():
            fly_message(
                self.window(),
                "无法删除",
                f"未找到任务目录：\n{qdir}",
            )
            return
        qname = (it.name.str or "").strip() or "—"
        body = (
            f"将永久删除任务 ID {it.name.id}（{qname}）目录：\n"
            f"• {self._rel_acus_path(qdir)}\n\n"
            "此操作不可撤销，确定删除？"
        )
        if not fly_question(self.window(), "删除任务", body):
            return
        try:
            shutil.rmtree(qdir)
        except Exception as e:
            fly_critical(self.window(), "删除失败", str(e))
            return
        fly_message(self.window(), "已删除", f"已移除任务 {it.name.id} 的目录。")
        self.reload()

    def _delete_chara_item(self, it: CharaItem) -> None:
        nm = (it.name.str or "").strip() or "—"
        if not fly_question(
            self.window(),
            "删除角色",
            f"将永久删除角色 ID {it.name.id}（{nm}）在 ACUS 下的目录：\n"
            f"• chara/{it.xml_path.parent.name}/\n"
            f"• ddsImage/ddsImage{it.name.id:06d}/（若存在）\n\n"
            "此操作不可撤销，确定删除？",
        ):
            return
        try:
            delete_chara_from_acus(self._acus_root, it)
        except Exception as e:
            fly_critical(self.window(), "删除失败", str(e))
            return
        fly_message(self.window(), "已删除", f"已移除角色 {it.name.id} 的资源目录。")
        self.reload()

    def _on_select(self, *_args) -> None:
        sel = self.table.selectionModel()
        if sel is None:
            return
        rows = sel.selectedRows()
        if not rows:
            return
        proxy_idx = rows[0]
        src_idx = self.proxy.mapToSource(proxy_idx)
        item = self.model.item(src_idx.row(), 0)
        if item is None:
            return
        payload = item.data(Qt.ItemDataRole.UserRole)
        if payload is None:
            return
        if isinstance(payload, CharaItem):
            self._show_chara_detail(payload)
            return

        self._fill_attrs_table(payload)
        pm, hint = self._simple_preview_pixmap_and_hint(payload)
        if hint:
            self._append_attr_row("预览说明", hint)
        if pm is not None:
            self.simple_preview.setVisible(True)
            self.chara_variant_tabs.setVisible(False)
            self.chara_triple.setVisible(False)
            self.simple_preview.setSourcePixmap(pm)
            self.preview_section.setVisible(True)
        else:
            self.simple_preview.clear_source()
            self._hide_preview_section()

    def _on_table_double_clicked(self, proxy_index: QModelIndex) -> None:
        """地图：双击编辑；歌曲：双击生成课题称号。"""
        if not proxy_index.isValid():
            return
        k = self._kind_key()
        if k not in ("Map", "Music", "MapBonus"):
            return
        src_idx = self.proxy.mapToSource(proxy_index)
        item = self.model.item(src_idx.row(), 0)
        if item is None:
            return
        payload = item.data(Qt.ItemDataRole.UserRole)
        if k == "Map":
            if not isinstance(payload, MapItem):
                return
            from .map_add_dialog import MapAddDialog

            dlg = MapAddDialog(
                acus_root=self._acus_root,
                tool_path=self._get_tool_path(),
                game_index=self._get_game_index(),
                parent=self.window(),
                edit_map_xml=payload.xml_path,
            )
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self.reload()
            return
        if k == "Music":
            if not isinstance(payload, MusicItem):
                return
            from .music_trophy_dialog import MusicTrophyDialog

            dlg = MusicTrophyDialog(
                acus_root=self._acus_root,
                preselect=payload,
                parent=self.window(),
            )
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self.reload()
            return
        if k == "MapBonus":
            if not isinstance(payload, MapBonusItem):
                return
            from .mapbonus_dialogs import MapBonusEditDialog

            dlg = MapBonusEditDialog(
                acus_root=self._acus_root,
                game_index=self._get_game_index(),
                xml_path=payload.xml_path,
                parent=self.window(),
            )
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self.reload()

    def _chara_master_xml(self, it: CharaItem) -> Path:
        p = chara_master_xml_path(self._acus_root, it.name.id)
        return p if p.is_file() else it.xml_path

    def _rebuild_chara_variant_tabs(self) -> None:
        self.chara_variant_tabs.blockSignals(True)
        self.chara_variant_tabs.clear()
        slots = sorted(self._chara_variant_map.keys())
        for s in slots:
            page = QWidget(self.chara_variant_tabs)
            self.chara_variant_tabs.addTab(page, str(s), routeKey=f"cv_slot_{s}")
            idx = self.chara_variant_tabs.count() - 1
            self.chara_variant_tabs.setTabData(idx, s)
        if self._next_free_chara_variant_slot() is not None:
            page = QWidget(self.chara_variant_tabs)
            self.chara_variant_tabs.addTab(page, "+", routeKey="cv_slot_add")
            idx = self.chara_variant_tabs.count() - 1
            self.chara_variant_tabs.setTabData(idx, _CHARA_TAB_ADD)
        self.chara_variant_tabs.blockSignals(False)
        if self.chara_variant_tabs.count() > 0:
            self.chara_variant_tabs.setCurrentIndex(0)

    def _next_free_chara_variant_slot(self) -> int | None:
        for i in range(1, 10):
            if i not in self._chara_variant_map:
                return i
        return None

    def _current_chara_variant_slot(self) -> int | None:
        idx = self.chara_variant_tabs.currentIndex()
        if idx < 0:
            return None
        d = self.chara_variant_tabs.tabData(idx)
        if d == _CHARA_TAB_ADD or not isinstance(d, int):
            return None
        return d

    def _chara_variant_tab_index_at(self, pos_in_view: QPoint) -> int:
        bar = self.chara_variant_tabs.tabBar
        for i in range(bar.count()):
            if bar.tabItem(i).geometry().contains(pos_in_view):
                return i
        return -1

    def _on_chara_variant_tab_context_menu(self, pos: QPoint) -> None:
        if self._selected_chara is None:
            return
        idx = self._chara_variant_tab_index_at(pos)
        if idx < 0:
            return
        d = self.chara_variant_tabs.tabData(idx)
        if d == _CHARA_TAB_ADD:
            return
        if not isinstance(d, int):
            return
        slot = d
        menu = RoundMenu(parent=self.chara_variant_tabs.tabBar.view)
        menu.setItemHeight(36)
        vf = menu.view.font()
        vf.setPointSize(max(12, vf.pointSize()))
        menu.view.setFont(vf)
        gpos = self.chara_variant_tabs.tabBar.view.mapToGlobal(pos)
        act_edit = Action(FIF.EDIT, "编辑此变体…", self.chara_variant_tabs)
        act_edit.triggered.connect(lambda _=False, sl=slot: QTimer.singleShot(0, lambda: self._open_chara_variant_editor(sl)))
        menu.addAction(act_edit)
        if slot >= 1:
            act_del = Action(FIF.DELETE, "删除此变体…", self.chara_variant_tabs)
            act_del.triggered.connect(
                lambda _=False, sl=slot: QTimer.singleShot(0, lambda: self._delete_chara_variant_from_tab(sl))
            )
            menu.addAction(act_del)
        menu.exec(gpos, ani=True, aniType=MenuAnimationType.DROP_DOWN)

    def _open_chara_variant_editor(self, variant_slot: int) -> None:
        it = self._selected_chara
        if it is None:
            return
        master = self._chara_master_xml(it)
        if not master.is_file():
            fly_message(self.window(), "无法编辑", f"未找到主 Chara.xml：\n{master}")
            return
        tool = self._get_tool_path()
        if tool is None and not quicktex_available():
            fly_critical(
                self.window(),
                "无法生成 DDS",
                "请安装 quicktex 或在【设置】中配置 compressonatorcli。",
            )
            return
        base = it.name.id // 10
        dlg = CharaAddDialog(acus_root=self._acus_root, tool_path=tool, parent=self.window())
        dlg.base.setText(str(base))
        dlg.variant.setText(str(variant_slot))
        dlg.base.setReadOnly(True)
        dlg.variant.setReadOnly(True)
        nm = chara_variant_display_name(master, variant_slot)
        if nm:
            dlg.name.setText(nm)
        ill = ""
        try:
            root = ET.parse(master).getroot()
            ill = (root.findtext("illustratorName/str") or "").strip()
        except Exception:
            pass
        if ill:
            dlg.illustrator.setText(ill)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.reload()

    def _open_chara_variant_add_dialog(self) -> None:
        it = self._selected_chara
        if it is None:
            return
        slot = self._next_free_chara_variant_slot()
        if slot is None:
            fly_message(self.window(), "无法新增", "addImages1~9 已全部占用。")
            return
        master = self._chara_master_xml(it)
        if not master.is_file():
            fly_message(self.window(), "无法新增", f"未找到主 Chara.xml：\n{master}")
            return
        tool = self._get_tool_path()
        if tool is None and not quicktex_available():
            fly_critical(
                self.window(),
                "无法生成 DDS",
                "请安装 quicktex 或在【设置】中配置 compressonatorcli。",
            )
            return
        base = it.name.id // 10
        dlg = CharaAddDialog(acus_root=self._acus_root, tool_path=tool, parent=self.window())
        dlg.base.setText(str(base))
        dlg.variant.setText(str(slot))
        dlg.base.setReadOnly(True)
        dlg.variant.setReadOnly(True)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.reload()

    def _delete_chara_variant_from_tab(self, variant_slot: int) -> None:
        it = self._selected_chara
        if it is None:
            return
        if variant_slot < 1:
            fly_message(self.window(), "无法删除", "默认立绘槽位（0）不能从此处删除。")
            return
        master = self._chara_master_xml(it)
        if not master.is_file():
            fly_message(self.window(), "无法删除", f"未找到主 Chara.xml：\n{master}")
            return
        if not fly_question(
            self.window(),
            "删除变体",
            f"将从主 Chara.xml 移除 addImages{variant_slot}。\n"
            f"不会自动删除 ddsImage 目录下的文件，可稍后手动清理。\n\n确定删除？",
        ):
            return
        try:
            remove_chara_variant_from_xml(xml_path=master, variant=variant_slot)
        except Exception as e:
            fly_critical(self.window(), "删除失败", str(e))
            return
        fly_message(self.window(), "已删除", f"已移除 addImages{variant_slot}。")
        self.reload()

    def _show_chara_detail(self, it: CharaItem) -> None:
        self._selected_chara = it
        master = self._chara_master_xml(it)
        self._chara_variant_map, meta = self._parse_chara_variants_and_meta(master)
        self._attrs_model.removeRows(0, self._attrs_model.rowCount())
        for label, val in self._chara_attr_rows(it, meta):
            self._append_attr_row(label, val)
        self.attrs_table.resizeColumnsToContents()

        self.simple_preview.setVisible(False)
        self.simple_preview.clear_source()
        self.chara_variant_tabs.setVisible(True)
        self._rebuild_chara_variant_tabs()
        self._update_chara_variant_preview()
        self.preview_section.setVisible(True)

    def _parse_chara_variants_and_meta(self, xml_path: Path) -> tuple[dict[int, int], dict[str, str]]:
        variant_map: dict[int, int] = {}
        meta: dict[str, str] = {}
        root = ET.parse(xml_path).getroot()
        base_id_raw = (root.findtext("name/id") or "").strip()
        name = (root.findtext("name/str") or "").strip()
        release_tag_id = (root.findtext("releaseTagName/id") or "").strip()
        release_tag_str = (root.findtext("releaseTagName/str") or "").strip()
        illustrator = (root.findtext("illustratorName/str") or "").strip()
        works_id = (root.findtext("works/id") or "").strip()
        works = (root.findtext("works/str") or "").strip()
        meta["name"] = name
        meta["id"] = base_id_raw
        meta["releaseTag"] = f"{release_tag_id}:{release_tag_str}"
        meta["illustrator"] = illustrator or "Invalid"
        if works_id or works:
            meta["works"] = f"{works_id or '?'}" + (" · " + works if works else "")
        else:
            meta["works"] = "Invalid"
        try:
            base_id = int(base_id_raw)
        except Exception:
            base_id = -1
        if base_id >= 0:
            variant_map[base_id % 10] = base_id
        for i in range(1, 10):
            sec = root.find(f"addImages{i}")
            if sec is None:
                continue
            if (sec.findtext("changeImg") or "").strip().lower() != "true":
                continue
            vid_raw = (sec.findtext("image/id") or "").strip()
            if not vid_raw.isdigit():
                continue
            variant_map[i] = int(vid_raw)
        return variant_map, meta

    def _on_chara_variant_changed(self, idx: int) -> None:
        if self._selected_chara is None or idx < 0:
            return
        d = self.chara_variant_tabs.tabData(idx)
        if d == _CHARA_TAB_ADD:
            self.chara_variant_tabs.blockSignals(True)
            prev = max(0, idx - 1)
            self.chara_variant_tabs.setCurrentIndex(prev)
            self.chara_variant_tabs.blockSignals(False)
            # Delay modal dialog opening so tab bar interaction fully settles first.
            QTimer.singleShot(0, self._open_chara_variant_add_dialog)
            return
        self._update_chara_variant_preview()

    def _update_chara_variant_preview(self) -> None:
        if self._selected_chara is None:
            return
        var = self._current_chara_variant_slot()
        if var is None:
            self.chara_triple.clear()
            self.chara_triple.setVisible(False)
            return
        cid = self._chara_variant_map.get(var)
        tool = self._get_tool_path()
        if cid is None:
            self.chara_triple.clear()
            self.chara_triple.setVisible(False)
            self._upsert_chara_preview_hint("当前变体索引无对应立绘 ID。")
            return
        dds_xml = self._acus_root / "ddsImage" / f"ddsImage{cid:06d}" / "DDSImage.xml"
        if not dds_xml.exists():
            self.chara_triple.clear()
            self.chara_triple.setVisible(False)
            self._upsert_chara_preview_hint(f"缺少 ddsImage{cid:06d} / DDSImage.xml。")
            return
        if tool is None and not quicktex_available():
            self.chara_triple.clear()
            self.chara_triple.setVisible(False)
            self._upsert_chara_preview_hint("预览需 quicktex 或【设置】中的 compressonatorcli。")
            return
        root = ET.parse(dds_xml).getroot()
        d0 = (root.findtext("ddsFile0/path") or "").strip()
        d1 = (root.findtext("ddsFile1/path") or "").strip()
        d2 = (root.findtext("ddsFile2/path") or "").strip()
        pms: list[QPixmap | None] = []
        for rel in (d0, d1, d2):
            if not rel:
                pms.append(None)
                continue
            p = dds_xml.parent / rel
            pm = dds_to_pixmap(
                acus_root=self._acus_root,
                compressonatorcli_path=tool,
                dds_path=p,
                restrict=False,
            )
            pms.append(pm if pm is not None and not pm.isNull() else None)
        self._remove_chara_preview_hint()
        if not any(x is not None for x in pms):
            self.chara_triple.clear()
            self.chara_triple.setVisible(False)
            self._upsert_chara_preview_hint("三张 DDS 均解码失败或路径为空。")
            return
        self.chara_triple.setVisible(True)
        self.chara_triple.set_pixmaps(pms[0], pms[1], pms[2])

    def _upsert_chara_preview_hint(self, text: str) -> None:
        for r in range(self._attrs_model.rowCount()):
            it0 = self._attrs_model.item(r, 0)
            if it0 is not None and it0.text() == "预览说明":
                it1 = self._attrs_model.item(r, 1)
                if it1 is None:
                    it1 = QStandardItem()
                    it1.setEditable(False)
                    self._attrs_model.setItem(r, 1, it1)
                it1.setText(text)
                return
        self._append_attr_row("预览说明", text)

    def _remove_chara_preview_hint(self) -> None:
        for r in range(self._attrs_model.rowCount() - 1, -1, -1):
            it0 = self._attrs_model.item(r, 0)
            if it0 is not None and it0.text() == "预览说明":
                self._attrs_model.removeRow(r)
                return

