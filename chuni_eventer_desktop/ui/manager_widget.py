from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import xml.etree.ElementTree as ET

from PyQt6.QtCore import QPoint, Qt, QModelIndex, QSortFilterProxyModel
from PyQt6.QtGui import QPixmap, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import BodyLabel, CaptionLabel, ComboBox as FluentComboBox, TableView

from .fluent_dialogs import fly_critical, fly_message
from .music_cards_view import MusicCardsView

from ..chara_delete import delete_chara_from_acus
from ..music_delete import execute_music_deletion, plan_music_deletion
from ..acus_scan import (
    CharaItem,
    DdsImageItem,
    EventItem,
    IdStr,
    MapItem,
    MusicItem,
    NamePlateItem,
    QuestItem,
    RewardItem,
    TrophyItem,
    scan_charas,
    scan_dds_images,
    scan_events,
    scan_maps,
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

_KIND_DEFS: tuple[tuple[str, str], ...] = (
    ("事件", "Event"),
    ("任务", "Quest"),
    ("地图", "Map"),
    ("歌曲", "Music"),
    ("角色", "Chara"),
    ("称号", "Trophy"),
    ("名牌", "NamePlate"),
    ("奖励", "Reward"),
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
        for lb in (self._left, self._r1, self._r2):
            lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lb.setStyleSheet("border: 1px solid #555;")
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

        self.event_filter = QComboBox()
        self.event_filter.addItems(["全部", "ULT/WE曲解锁", "地图解禁", "宣传(含DDS)", "其它"])
        self.event_filter.currentIndexChanged.connect(self.reload)
        self.event_bar = QWidget()
        ev_row = QHBoxLayout(self.event_bar)
        ev_row.setContentsMargins(0, 0, 0, 0)
        ev_row.addWidget(QLabel("事件分类"))
        ev_row.addWidget(self.event_filter, stretch=1)
        self.event_bar.setVisible(False)

        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "搜索：ID / 名称 / 关键字（地图双击编辑；歌曲双击生成课题称号）"
        )
        self.search.textChanged.connect(self._apply_filter)

        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.reload)
        self._game_music_btn = QPushButton("游戏乐曲资源…")
        self._game_music_btn.setToolTip("只读浏览游戏目录内已扫描数据包中的全部乐曲（含版本标签、流派）")
        self._game_music_btn.clicked.connect(self._on_game_music_browser)
        self._game_music_btn.setVisible(False)

        top = QHBoxLayout()
        top.addWidget(QLabel("类型"))
        top.addWidget(self.kind)
        top.addSpacing(8)
        top.addWidget(QLabel("搜索"))
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
        self.preview_title = CaptionLabel("DDS 预览（quicktex 或 compressonator）")
        self.simple_preview = WidthScaledPreviewLabel()
        self.chara_variant_tabs = QTabWidget()
        for i in range(10):
            self.chara_variant_tabs.addTab(QWidget(), str(i))
        self.chara_variant_tabs.currentChanged.connect(self._on_chara_variant_changed)
        self.chara_triple = CharaDdsPreviewWidget()
        pv.addWidget(self.preview_title)
        pv.addWidget(self.simple_preview)
        pv.addWidget(self.chara_variant_tabs)
        pv.addWidget(self.chara_triple)
        self.preview_section.setVisible(False)

        self.attrs_table = QTableWidget(0, 2)
        self.attrs_table.setHorizontalHeaderLabels(["属性", "值"])
        self.attrs_table.horizontalHeader().setStretchLastSection(True)
        self.attrs_table.verticalHeader().setVisible(False)
        self.attrs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.attrs_table.setAlternatingRowColors(True)
        self.attrs_table.setWordWrap(True)

        self._selected_chara: CharaItem | None = None
        self._chara_variant_map: dict[int, int] = {}

        # right panel：上 DDS（有则显示），下属性表
        right_card = QFrame()
        right_card.setFrameShape(QFrame.Shape.NoFrame)
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(12, 12, 12, 12)
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

        self._main_stack = QStackedWidget()
        self._main_stack.addWidget(split)
        self._main_stack.addWidget(self.music_cards_view)

        layout = QVBoxLayout(self)
        if not self._embedded:
            layout.addLayout(top)
        layout.addWidget(self.event_bar)
        layout.addWidget(self._main_stack, stretch=1)

        self._items: list[object] = []
        self.reload()

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
        self.attrs_table.setRowCount(0)
        self._hide_preview_section()
        self.simple_preview.clear_source()
        self.chara_triple.clear()

        k = self._kind_key()
        self.event_bar.setVisible(k == "Event")

        if k == "Quest":
            self.model.setHorizontalHeaderLabels(["ID", "名称", "角色条件", "奖励阶段", "来源(XML)"])
        elif k == "Music":
            self.model.setHorizontalHeaderLabels(["ID", "曲名", "艺术家", "流派", "发布日期", "难度", "CueFile", "来源(XML)"])
        elif k == "Trophy":
            self.model.setHorizontalHeaderLabels(["ID", "名称", "稀有度", "来源(XML)"])
        elif k == "Reward":
            self.model.setHorizontalHeaderLabels(["ID", "名称", "奖励类型", "关联目标", "来源(XML)"])
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
            self._items = items
            for it in items:
                self._append_reward_row(it)
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
        self.preview_title.setVisible(True)
        self.simple_preview.setVisible(False)
        self.chara_variant_tabs.setVisible(False)
        self.chara_triple.setVisible(False)

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
        r = self.attrs_table.rowCount()
        self.attrs_table.insertRow(r)
        self.attrs_table.setItem(r, 0, QTableWidgetItem(label))
        self.attrs_table.setItem(r, 1, QTableWidgetItem(value))

    def _fill_attrs_table(self, it: object) -> None:
        self.attrs_table.setRowCount(0)
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
            QMessageBox.critical(
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

    def _on_music_delete_requested(self, it: object) -> None:
        if not isinstance(it, MusicItem):
            return
        plan = plan_music_deletion(self._acus_root, it)
        if plan.music_dir is None or not plan.music_dir.is_dir():
            QMessageBox.warning(
                self.window(),
                "无法删除",
                "未找到该乐曲在 ACUS/music 下的目录，已中止。",
            )
            return
        lines = plan.summary_lines()
        body = "将执行以下操作：\n\n• " + "\n• ".join(lines) + "\n\n此操作不可撤销，确定删除？"
        r = QMessageBox.question(
            self.window(),
            "删除乐曲",
            body,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if r != QMessageBox.StandardButton.Yes:
            return
        try:
            execute_music_deletion(plan)
        except Exception as e:
            QMessageBox.critical(self.window(), "删除失败", str(e))
            return
        self.reload()

    def _on_table_context_menu(self, pos: QPoint) -> None:
        if self._kind_key() != "Chara":
            return
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        src_idx = self.proxy.mapToSource(idx)
        item0 = self.model.item(src_idx.row(), 0)
        if item0 is None:
            return
        payload = item0.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, CharaItem):
            return
        menu = QMenu(self.table)
        act_del = menu.addAction("删除角色…")
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen != act_del:
            return
        self._delete_chara_item(payload)

    def _delete_chara_item(self, it: CharaItem) -> None:
        nm = (it.name.str or "").strip() or "—"
        r = QMessageBox.question(
            self.window(),
            "删除角色",
            f"将永久删除角色 ID {it.name.id}（{nm}）在 ACUS 下的目录：\n"
            f"• chara/{it.xml_path.parent.name}/\n"
            f"• ddsImage/ddsImage{it.name.id:06d}/（若存在）\n\n"
            "此操作不可撤销，确定删除？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if r != QMessageBox.StandardButton.Yes:
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
            self.preview_title.setVisible(True)
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
        if k not in ("Map", "Music"):
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

    def _show_chara_detail(self, it: CharaItem) -> None:
        self._selected_chara = it
        self._chara_variant_map, meta = self._parse_chara_variants_and_meta(it.xml_path)
        self.attrs_table.setRowCount(0)
        for label, val in self._chara_attr_rows(it, meta):
            self._append_attr_row(label, val)
        self.attrs_table.resizeColumnsToContents()

        self.preview_title.setVisible(True)
        self.simple_preview.setVisible(False)
        self.simple_preview.clear_source()
        self.chara_variant_tabs.setVisible(True)
        cur = self.chara_variant_tabs.currentIndex()
        for i in range(10):
            has_variant = i in self._chara_variant_map
            self.chara_variant_tabs.setTabEnabled(i, has_variant)
            self.chara_variant_tabs.setTabText(i, f"{i}{' *' if has_variant else ''}")
        if cur not in self._chara_variant_map:
            next_idx = 0
            for i in range(10):
                if i in self._chara_variant_map:
                    next_idx = i
                    break
            self.chara_variant_tabs.setCurrentIndex(next_idx)

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
        works = (root.findtext("works/str") or "").strip()
        meta["name"] = name
        meta["id"] = base_id_raw
        meta["releaseTag"] = f"{release_tag_id}:{release_tag_str}"
        meta["illustrator"] = illustrator or "Invalid"
        meta["works"] = works or "Invalid"
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

    def _on_chara_variant_changed(self, _idx: int) -> None:
        if self._selected_chara is not None:
            self._update_chara_variant_preview()

    def _update_chara_variant_preview(self) -> None:
        if self._selected_chara is None:
            return
        var = self.chara_variant_tabs.currentIndex()
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
        for r in range(self.attrs_table.rowCount()):
            it0 = self.attrs_table.item(r, 0)
            if it0 is not None and it0.text() == "预览说明":
                self.attrs_table.setItem(r, 1, QTableWidgetItem(text))
                return
        self._append_attr_row("预览说明", text)

    def _remove_chara_preview_hint(self) -> None:
        for r in range(self.attrs_table.rowCount() - 1, -1, -1):
            it0 = self.attrs_table.item(r, 0)
            if it0 is not None and it0.text() == "预览说明":
                self.attrs_table.removeRow(r)
                return

