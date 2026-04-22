from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import BodyLabel, CardWidget, LineEdit, PrimaryPushButton, PushButton

from ..release_tag_xml import (
    ReleaseTagEntry,
    count_music_using_release_tag,
    delete_release_tag,
    list_release_tags,
    suggest_next_custom_release_tag_id,
    write_release_tag_xml,
)
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical, fly_message, fly_question
from .fluent_table import apply_fluent_sheet_table


class MusicReleaseTagDialog(FluentCaptionDialog):
    def __init__(
        self,
        *,
        acus_root: Path,
        current_release_tag_id: int | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("乐曲分类管理")
        self.setModal(True)
        self.resize(860, 600)
        self._acus_root = acus_root
        self.selected_release_tag: tuple[int, str] | None = None
        self._items: list[ReleaseTagEntry] = []
        self._current_id = current_release_tag_id

        tip = BodyLabel("提示：需要在游戏内使用“按版本分类”才能按这里的分类显示。", self)
        tip.setWordWrap(True)
        tip.setTextColor("#6B7280", "#9CA3AF")

        self._table = QTableWidget(0, 4, self)
        apply_fluent_sheet_table(self._table)
        self._table.setHorizontalHeaderLabels(["id", "str", "titleName", "来源(XML)"])
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.itemDoubleClicked.connect(lambda _it: self._on_apply())

        list_card = CardWidget(self)
        list_lay = QVBoxLayout(list_card)
        list_lay.setContentsMargins(16, 14, 16, 14)
        list_lay.setSpacing(8)
        list_lay.addWidget(tip)
        list_lay.addWidget(self._table, stretch=1)

        self._new_id = LineEdit(self)
        self._new_id.setPlaceholderText("留空自动分配（700+）")
        self._new_id.setText(str(suggest_next_custom_release_tag_id(self._acus_root, start=700)))
        self._new_str = LineEdit(self)
        self._new_str.setPlaceholderText("例如：Custom700")
        self._new_title = LineEdit(self)
        self._new_title.setPlaceholderText("例如：自定义版本")

        make_btn = PrimaryPushButton("创建新的 releaseTag 文件", self)
        make_btn.clicked.connect(self._on_create_new)
        del_btn = PushButton("删除选中 releaseTag", self)
        del_btn.clicked.connect(self._on_delete_selected)

        create_card = CardWidget(self)
        create_lay = QVBoxLayout(create_card)
        create_lay.setContentsMargins(16, 14, 16, 14)
        create_lay.setSpacing(8)
        create_lay.addWidget(BodyLabel("新建 releaseTag", self))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("name.id", self._new_id)
        form.addRow("name.str", self._new_str)
        form.addRow("titleName", self._new_title)
        create_lay.addLayout(form)
        create_btns = QHBoxLayout()
        create_btns.addWidget(del_btn)
        create_btns.addStretch(1)
        create_btns.addWidget(make_btn)
        create_lay.addLayout(create_btns)

        apply_btn = PrimaryPushButton("应用到当前乐曲", self)
        apply_btn.clicked.connect(self._on_apply)
        cancel_btn = PushButton("取消", self)
        cancel_btn.clicked.connect(self.reject)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(cancel_btn)
        foot.addWidget(apply_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*fluent_caption_content_margins())
        lay.setSpacing(12)
        lay.addWidget(list_card, stretch=1)
        lay.addWidget(create_card)
        lay.addLayout(foot)

        self._reload_table()

    def _reload_table(self) -> None:
        self._items = list_release_tags(self._acus_root)
        self._table.setRowCount(len(self._items))
        target_row = -1
        for row, item in enumerate(self._items):
            rel = self._to_rel(item.xml_path)
            vals = [str(item.id), item.name, item.title, rel]
            for col, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, item.id)
                self._table.setItem(row, col, cell)
            if self._current_id is not None and item.id == self._current_id and target_row < 0:
                target_row = row
        if target_row >= 0:
            self._table.selectRow(target_row)

    def _to_rel(self, p: Path) -> str:
        try:
            return str(p.relative_to(self._acus_root))
        except Exception:
            return str(p)

    def _selected_entry(self) -> ReleaseTagEntry | None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._items):
            return None
        return self._items[row]

    def _on_create_new(self) -> None:
        raw_id = (self._new_id.text() or "").strip()
        if raw_id:
            try:
                rid = int(raw_id)
            except ValueError:
                fly_critical(self, "错误", "name.id 必须是整数。")
                return
        else:
            rid = suggest_next_custom_release_tag_id(self._acus_root, start=700)
        if rid < 700:
            fly_critical(self, "错误", "自定义 releaseTag 的 id 请使用 700 及以上。")
            return
        rstr = (self._new_str.text() or "").strip() or f"Custom{rid}"
        title = (self._new_title.text() or "").strip() or rstr

        existing_ids = {x.id for x in list_release_tags(self._acus_root)}
        if rid in existing_ids:
            fly_critical(self, "错误", f"id={rid} 已存在，请换一个。")
            return
        try:
            xp = write_release_tag_xml(
                self._acus_root,
                release_tag_id=rid,
                release_tag_str=rstr,
                title_name=title,
            )
        except Exception as e:
            fly_critical(self, "写入失败", str(e))
            return
        self._current_id = rid
        self._new_id.setText(str(suggest_next_custom_release_tag_id(self._acus_root, start=700)))
        self._reload_table()
        fly_message(self, "已创建", f"已写入：\n{self._to_rel(xp)}")

    def _on_apply(self) -> None:
        picked = self._selected_entry()
        if picked is None:
            fly_critical(self, "错误", "请先从列表中选择一个 releaseTag。")
            return
        self.selected_release_tag = (picked.id, picked.name)
        self.accept()

    def _on_delete_selected(self) -> None:
        picked = self._selected_entry()
        if picked is None:
            fly_critical(self, "错误", "请先从列表中选择一个 releaseTag。")
            return
        if picked.id < 700:
            fly_critical(self, "错误", "内置 releaseTag（id<700）不允许删除。")
            return
        used = count_music_using_release_tag(self._acus_root, picked.id)
        if used > 0:
            fly_critical(
                self,
                "无法删除",
                f"当前有 {used} 首乐曲正在使用 id={picked.id}（{picked.name}），请先把这些乐曲改到其他分类。",
            )
            return
        ok = fly_question(
            self,
            "确认删除",
            f"将删除以下目录：\n{self._to_rel(picked.xml_path.parent)}\n\n此操作不可撤销，确定继续？",
        )
        if not ok:
            return
        try:
            out = delete_release_tag(self._acus_root, picked.id)
        except Exception as e:
            fly_critical(self, "删除失败", str(e))
            return
        self._current_id = None
        self._reload_table()
        self._new_id.setText(str(suggest_next_custom_release_tag_id(self._acus_root, start=700)))
        target = self._to_rel(out) if out is not None else f"id={picked.id}"
        fly_message(self, "已删除", f"已删除：\n{target}")
