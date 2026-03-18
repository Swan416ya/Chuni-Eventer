from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from PyQt6.QtCore import Qt, QSortFilterProxyModel
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QComboBox,
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
    scan_charas,
    scan_dds_images,
    scan_events,
    scan_maps,
    scan_music,
)
from ..dds_preview import dds_to_pixmap


class ManagerWidget(QWidget):
    def __init__(self, *, acus_root: Path, get_tool_path) -> None:
        super().__init__()
        self._acus_root = acus_root
        self._get_tool_path = get_tool_path  # callable returning Path|None

        self.kind = QComboBox()
        self.kind.addItems(["Event", "Map", "Music", "Chara", "DDSImage"])
        self.kind.currentTextChanged.connect(self.reload)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索：ID / 名称 / 关键字（实时过滤）")
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
        right_layout.addWidget(QLabel("DDS 预览（需要配置 compressonatorcli）"))
        right_layout.addWidget(self.preview, stretch=0)

        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        split = QSplitter()
        split.setOrientation(Qt.Orientation.Horizontal)
        split.addWidget(self.table)
        split.addWidget(right_card)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 4)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(split, stretch=1)

        self._items: list[object] = []
        self.reload()

    def reload(self) -> None:
        self.model.removeRows(0, self.model.rowCount())
        self.detail.clear()
        self.preview.setText("预览")
        self.preview.clear()

        k = self.kind.currentText()
        if k == "Event":
            items = scan_events(self._acus_root)
            self._items = items
            for it in items:
                self._append_row(it.name.id, it.name.str, it.kind, it.xml_path, it)
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
                extra = it.artist.str if it.artist else ""
                self._append_row(it.name.id, it.name.str, extra, it.xml_path, it)
        elif k == "Chara":
            items = scan_charas(self._acus_root)
            self._items = items
            for it in items:
                self._append_row(it.name.id, it.name.str, it.default_image_key, it.xml_path, it)
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
        tool = self._get_tool_path()
        if tool is None or not tool.exists():
            self.preview.setText("未配置 compressonatorcli，无法预览 DDS")
            self.preview.clear()
            return

        dds_path: Path | None = None

        if isinstance(it, DdsImageItem):
            # 默认预览 ddsFile0（大头）
            dds_path = it.xml_path.parent / it.dds0
        elif isinstance(it, MusicItem) and it.jacket_path:
            # jacket is a .dds file in music folder
            dds_path = it.xml_path.parent / it.jacket_path
        elif isinstance(it, CharaItem):
            # 通过 defaultImages.str 找到匹配的 DDSImage.xml，再取 ddsFile0
            for d in scan_dds_images(self._acus_root):
                if d.name.str == it.default_image_key:
                    dds_path = d.xml_path.parent / d.dds0
                    break
        elif isinstance(it, EventItem):
            # event 本身通常没有 dds；保持空
            dds_path = None
        elif isinstance(it, MapItem):
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

