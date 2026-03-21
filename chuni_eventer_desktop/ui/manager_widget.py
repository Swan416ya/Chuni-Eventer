from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from PyQt6.QtCore import Qt, QModelIndex, QSortFilterProxyModel
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..acus_scan import (
    CharaItem,
    DdsImageItem,
    EventItem,
    MapItem,
    MusicItem,
    NamePlateItem,
    RewardItem,
    TrophyItem,
    scan_charas,
    scan_dds_images,
    scan_events,
    scan_maps,
    scan_music,
    scan_nameplates,
    scan_rewards,
    scan_trophies,
)
from ..dds_preview import dds_to_pixmap
from ..dds_quicktex import quicktex_available
from ..trophy_preview import load_trophy_frame_pixmap, render_trophy_text_preview


class ManagerWidget(QWidget):
    """
    ACUS 浏览器组件（表格 + 详情 + DDS 预览）。

    - 可作为独立页面使用（带顶部类型/搜索/刷新）
    - 也可作为“嵌入式”使用（由外层导航控制类型/搜索/刷新）
    """

    def __init__(self, *, acus_root: Path, get_tool_path, embedded: bool = False) -> None:
        super().__init__()
        self._acus_root = acus_root
        self._get_tool_path = get_tool_path  # callable returning Path|None
        self._embedded = embedded

        self.kind = QComboBox()
        self.kind.addItems(["Event", "Map", "Music", "Chara", "Trophy", "NamePlate", "Reward", "DDSImage"])
        self.kind.currentTextChanged.connect(self.reload)

        self.event_filter = QComboBox()
        self.event_filter.addItems(["全部", "ULT/WE曲解锁", "地图解禁", "宣传(含DDS)", "其它"])
        self.event_filter.currentIndexChanged.connect(self.reload)
        self.event_bar = QWidget()
        ev_row = QHBoxLayout(self.event_bar)
        ev_row.setContentsMargins(0, 0, 0, 0)
        ev_row.addWidget(QLabel("Event 分类"))
        ev_row.addWidget(self.event_filter, stretch=1)
        self.event_bar.setVisible(False)

        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "搜索：ID / 名称 / 关键字（地图双击编辑；歌曲双击生成课题称号）"
        )
        self.search.textChanged.connect(self._apply_filter)

        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.reload)

        top = QHBoxLayout()
        top.addWidget(QLabel("类型"))
        top.addWidget(self.kind)
        top.addSpacing(8)
        top.addWidget(QLabel("搜索"))
        top.addWidget(self.search, stretch=1)
        top.addStretch(1)
        top.addWidget(self.refresh_btn)

        self.model = QStandardItemModel(0, 4, self)
        self.model.setHorizontalHeaderLabels(["ID", "名称", "分类", "来源(XML)"])
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)  # all columns

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft)
        self.table.selectionModel().selectionChanged.connect(self._on_select)
        self.table.doubleClicked.connect(self._on_table_double_clicked)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)

        self.preview = QLabel("预览")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(340)
        self.preview.setStyleSheet("border: 1px solid #444;")

        # right panel "card"
        right_card = QFrame()
        right_card.setFrameShape(QFrame.Shape.NoFrame)
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.addWidget(QLabel("详情"))
        right_layout.addWidget(self.detail, stretch=1)
        right_layout.addWidget(QLabel("DDS 预览（quicktex 或 compressonator）"))
        right_layout.addWidget(self.preview, stretch=0)

        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        split = QSplitter()
        split.setOrientation(Qt.Orientation.Horizontal)
        split.addWidget(self.table)
        split.addWidget(right_card)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 4)

        layout = QVBoxLayout(self)
        if not self._embedded:
            layout.addLayout(top)
        layout.addWidget(self.event_bar)
        layout.addWidget(split, stretch=1)

        self._items: list[object] = []
        self.reload()

    def set_kind(self, kind: str) -> None:
        """
        kind: Event / Map / Music / Chara / …
        """
        idx = self.kind.findText(kind)
        if idx >= 0 and idx != self.kind.currentIndex():
            self.kind.setCurrentIndex(idx)
        else:
            # still reload if same kind (e.g. external refresh)
            self.reload()

    def set_search_text(self, text: str) -> None:
        if self.search.text() != text:
            self.search.setText(text)
        else:
            self._apply_filter()

    def reload(self) -> None:
        self.model.removeRows(0, self.model.rowCount())
        self.detail.clear()
        self.preview.setText("预览")
        self.preview.clear()

        k = self.kind.currentText()
        self.event_bar.setVisible(k == "Event")

        if k == "Music":
            self.model.setHorizontalHeaderLabels(["ID", "曲名", "艺术家", "流派", "发布日期", "难度", "CueFile", "来源(XML)"])
        elif k == "Trophy":
            self.model.setHorizontalHeaderLabels(["ID", "名称", "稀有度", "来源(XML)"])
        elif k == "Reward":
            self.model.setHorizontalHeaderLabels(["ID", "名称", "奖励类型", "关联目标", "来源(XML)"])
        else:
            self.model.setHorizontalHeaderLabels(["ID", "名称", "分类", "来源(XML)"])

        if k == "Event":
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
            for it in items:
                self._append_music_row(it)
        elif k == "Chara":
            items = scan_charas(self._acus_root)
            self._items = items
            for it in items:
                self._append_row(it.name.id, it.name.str, it.default_image_key, it.xml_path, it)
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

        self._apply_filter()
        self.table.resizeColumnsToContents()
        if self.proxy.rowCount() > 0:
            self.table.selectRow(0)

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

    def _apply_filter(self) -> None:
        self.proxy.setFilterFixedString(self.search.text().strip())

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
        self.detail.setPlainText(self._format_detail(payload))
        self._update_preview(payload)

    def _on_table_double_clicked(self, proxy_index: QModelIndex) -> None:
        """地图：双击编辑；歌曲：双击生成课题称号。"""
        if not proxy_index.isValid():
            return
        k = self.kind.currentText()
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

    def _format_detail(self, it: object) -> str:
        # dataclass -> dict for readability
        try:
            d = asdict(it)  # type: ignore[arg-type]
        except Exception:
            d = {"value": str(it)}
        lines = []
        for k, v in d.items():
            lines.append(f"{k}: {v}")
        return "\n".join(lines)

    def _update_preview(self, it: object) -> None:
        if isinstance(it, TrophyItem):
            self._preview_trophy(it)
            return

        tool = self._get_tool_path()
        if tool is None and not quicktex_available():
            self.preview.setText(
                "无法预览 DDS：未安装 quicktex，且未在【设置】中配置有效的 compressonatorcli。\n"
                "推荐：pip install quicktex；或选择 compressonator 可执行文件（不要填「.」或文件夹）。"
            )
            self.preview.clear()
            return

        dds_path: Path | None = None

        if isinstance(it, DdsImageItem):
            # 默认预览 ddsFile0（角色立绘：全身 / _00）
            dds_path = it.xml_path.parent / it.dds0
        elif isinstance(it, MusicItem) and it.jacket_path:
            # jacket is a .dds file in music folder
            dds_path = it.xml_path.parent / it.jacket_path
        elif isinstance(it, CharaItem):
            # 通过 defaultImages.str 找到匹配的 DDSImage.xml，再取 ddsFile0（全身）
            for d in scan_dds_images(self._acus_root):
                if d.name.str == it.default_image_key:
                    dds_path = d.xml_path.parent / d.dds0
                    break
        elif isinstance(it, NamePlateItem):
            if it.image_path:
                dds_path = it.xml_path.parent / it.image_path
        elif isinstance(it, EventItem):
            dds_path = it.promo_dds_path
        elif isinstance(it, MapItem):
            dds_path = None
        elif isinstance(it, RewardItem):
            dds_path = None

        if dds_path is None:
            self.preview.setText("该条目无可预览 DDS")
            self.preview.clear()
            return

        pm = dds_to_pixmap(acus_root=self._acus_root, compressonatorcli_path=tool, dds_path=dds_path)
        if pm is None:
            self.preview.setText(f"预览失败：{dds_path.name}")
            self.preview.clear()
            return
        self.preview.setPixmap(pm)
        self.preview.setText("")

    def _preview_trophy(self, it: TrophyItem) -> None:
        """
        无图称号：稀有度底图 + 居中显示名。
        有图（DDS）称号：仅显示 DDS 内容，不叠稀有度条底图。
        """
        try:
            self._preview_trophy_impl(it)
        except Exception as e:
            self.preview.clear()
            self.preview.setText(f"称号预览异常：{e}")

    def _preview_trophy_impl(self, it: TrophyItem) -> None:
        tool = self._get_tool_path()
        qt_ok = quicktex_available()

        img_rel = (it.image_path or "").strip()
        dds_path: Path | None = None
        if img_rel:
            cand = it.xml_path.parent / img_rel
            if cand.is_file():
                dds_path = cand

        if dds_path is not None:
            if tool is None and not qt_ok:
                self.preview.setText(
                    "无法预览称号 DDS：未安装 quicktex，且未在【设置】中配置 compressonatorcli。"
                )
                self.preview.clear()
                return
            pm = dds_to_pixmap(
                acus_root=self._acus_root,
                compressonatorcli_path=tool,
                dds_path=dds_path,
                max_w=640,
                max_h=200,
            )
            if pm is None:
                self.preview.setText(f"预览失败：{dds_path.name}")
                self.preview.clear()
                return
        else:
            frame_pm = load_trophy_frame_pixmap(it.rare_type)
            if frame_pm is None:
                self.preview.setText("缺少稀有度底图资源（static/trophy），无法预览无图称号")
                self.preview.clear()
                return
            pm = render_trophy_text_preview(frame=frame_pm, display_name=it.name.str or "—")
            if pm is None:
                self.preview.setText("该称号无法生成预览")
                self.preview.clear()
                return

        if pm.width() > 640:
            pm = pm.scaledToWidth(640, Qt.TransformationMode.SmoothTransformation)
        self.preview.setPixmap(pm)
        self.preview.setText("")

