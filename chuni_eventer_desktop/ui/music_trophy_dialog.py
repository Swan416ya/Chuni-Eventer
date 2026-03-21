from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..acus_scan import MusicItem, scan_music
from ..music_trophy_xml import (
    build_expert_gold_trophy_xml,
    build_master_platinum_trophy_xml,
    build_ultima_trophy_xml,
    next_trophy_id,
    write_trophy_file,
)


class MusicTrophyDialog(QDialog):
    """
    乐曲课题称号：Expert→金(4)、Master→铂(6)、Ultima→课题(8，仅当存在 Ultima 谱面)。
    与「新增称号」分离，稀有度不可在手动对话框中选。
    """

    def __init__(
        self,
        *,
        acus_root: Path,
        preselect: MusicItem | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("生成乐曲课题称号")
        self.setModal(True)
        self._acus_root = acus_root

        self._combo = QComboBox()
        self._combo.setMinimumWidth(420)
        self._hint = QLabel()
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color:#374151; font-size:12px;")

        self._reload_combo(preselect)

        btn_expert = QPushButton("生成 Expert 金 (rare 4)")
        btn_expert.clicked.connect(lambda: self._gen_one("expert"))
        btn_master = QPushButton("生成 Master 铂 (rare 6)")
        btn_master.clicked.connect(lambda: self._gen_one("master"))
        self._btn_ultima = QPushButton("生成 Ultima 课题 (rare 8)")
        self._btn_ultima.clicked.connect(lambda: self._gen_one("ultima"))
        btn_all = QPushButton("一键生成（本曲全部适用）")
        btn_all.clicked.connect(self._gen_all)

        row1 = QHBoxLayout()
        row1.addWidget(btn_expert)
        row1.addWidget(btn_master)
        row1.addWidget(self._btn_ultima)

        cancel = QPushButton("关闭")
        cancel.clicked.connect(self.reject)
        row2 = QHBoxLayout()
        row2.addStretch(1)
        row2.addWidget(btn_all)
        row2.addWidget(cancel)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("选择乐曲"))
        lay.addWidget(self._combo)
        lay.addWidget(self._hint)
        lay.addLayout(row1)
        lay.addLayout(row2)

        self._combo.currentIndexChanged.connect(self._sync_ultima_btn)
        self._sync_ultima_btn()

    def _current_music(self) -> MusicItem | None:
        return self._combo.currentData(Qt.ItemDataRole.UserRole)

    def _reload_combo(self, preselect: MusicItem | None) -> None:
        self._combo.clear()
        items = scan_music(self._acus_root)
        sel_idx = 0
        for i, it in enumerate(items):
            suffix = " · Ultima" if it.has_ultima else ""
            self._combo.addItem(f"{it.name.id} — {it.name.str}{suffix}", it)
            if preselect is not None and it.name.id == preselect.name.id:
                sel_idx = i
        if items:
            self._combo.setCurrentIndex(sel_idx)
        self._hint.setText(
            "条件写法对齐官方：Expert/Master 为条件 type 1（指定难度通关）+ type 3（ALL JUSTICE）；"
            "Ultima 为 type 10 + musicData。无 Ultima 谱面的曲目不会启用 Ultima 按钮。"
        )

    def _sync_ultima_btn(self) -> None:
        m = self._current_music()
        self._btn_ultima.setEnabled(bool(m and m.has_ultima))

    def _gen_one(self, kind: str) -> None:
        m = self._current_music()
        if m is None:
            QMessageBox.warning(self, "提示", "没有可选择的乐曲。")
            return
        if kind == "ultima" and not m.has_ultima:
            QMessageBox.warning(self, "提示", "当前乐曲没有已启用的 Ultima 难度，无法生成 Ultima 课题称号。")
            return
        try:
            tid = next_trophy_id(self._acus_root)
            name = m.name.str
            mid = m.name.id
            if kind == "expert":
                xml = build_expert_gold_trophy_xml(trophy_id=tid, music_id=mid, display_name=name)
                label = "Expert 金"
            elif kind == "master":
                xml = build_master_platinum_trophy_xml(trophy_id=tid, music_id=mid, display_name=name)
                label = "Master 铂"
            else:
                xml = build_ultima_trophy_xml(trophy_id=tid, music_id=mid, display_name=name)
                label = "Ultima 课题"
            path = write_trophy_file(self._acus_root, tid, xml)
            QMessageBox.information(
                self,
                "完成",
                f"已写入 {label}：trophy{tid:06d}\n{path}",
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def _gen_all(self) -> None:
        m = self._current_music()
        if m is None:
            QMessageBox.warning(self, "提示", "没有可选择的乐曲。")
            return
        try:
            tid = next_trophy_id(self._acus_root)
            paths: list[str] = []
            name = m.name.str
            mid = m.name.id
            for kind in ("expert", "master"):
                xml = (
                    build_expert_gold_trophy_xml(trophy_id=tid, music_id=mid, display_name=name)
                    if kind == "expert"
                    else build_master_platinum_trophy_xml(trophy_id=tid, music_id=mid, display_name=name)
                )
                paths.append(str(write_trophy_file(self._acus_root, tid, xml)))
                tid += 1
            if m.has_ultima:
                xml = build_ultima_trophy_xml(trophy_id=tid, music_id=mid, display_name=name)
                paths.append(str(write_trophy_file(self._acus_root, tid, xml)))
            QMessageBox.information(
                self,
                "完成",
                "已生成：\n" + "\n".join(paths),
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))
