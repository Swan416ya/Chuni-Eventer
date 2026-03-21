from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..acus_workspace import AcusConfig, ensure_acus_layout
from ..dds_quicktex import quicktex_available
from .manager_widget import ManagerWidget
from .settings_dialog import SettingsDialog
from .chara_add_dialog import CharaAddDialog
from .map_add_dialog import MapAddDialog, RewardCreateDialog, ensure_reward_xml, reward_dialog_bundle
from .nameplate_add_dialog import NamePlateAddDialog
from .trophy_add_dialog import TrophyAddDialog
from .music_trophy_dialog import MusicTrophyDialog


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("chuni eventer desktop (ACUS)")
        self.resize(1100, 650)

        self._acus_root = ensure_acus_layout()
        self._cfg = AcusConfig.load()

        # Left nav
        self.nav = QListWidget()
        self.nav.setFixedWidth(180)
        self.nav.addItem(QListWidgetItem("角色"))
        self.nav.addItem(QListWidgetItem("地图"))
        self.nav.addItem(QListWidgetItem("Event"))
        self.nav.addItem(QListWidgetItem("歌曲"))
        self.nav.addItem(QListWidgetItem("称号"))
        self.nav.addItem(QListWidgetItem("名牌"))
        self.nav.addItem(QListWidgetItem("奖励"))
        self.nav.currentRowChanged.connect(self._on_nav_changed)

        self.settings_btn = QPushButton("设置")
        self.settings_btn.clicked.connect(self._open_settings)
        self.settings_btn.setStyleSheet("background: #FFFFFF; color: #111827; border: 1px solid #E5E7EB;")

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.addWidget(QLabel("导航"))
        left_layout.addWidget(self.nav, stretch=1)
        left_layout.addStretch(1)
        left_layout.addWidget(self.settings_btn)

        # Right header
        self.title = QLabel("角色")
        self.title.setStyleSheet("font-size: 18px; font-weight: 700;")

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索当前列表…")

        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self._on_refresh)
        self.refresh_btn.setStyleSheet("background: #FFFFFF; color: #111827; border: 1px solid #E5E7EB;")

        self.add_btn = QPushButton("新增")
        self.add_btn.clicked.connect(self._on_add)

        header = QHBoxLayout()
        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(self.search, stretch=1)
        header.addWidget(self.refresh_btn)
        header.addWidget(self.add_btn)

        self.manager = ManagerWidget(acus_root=self._acus_root, get_tool_path=self._get_tool_path_or_none, embedded=True)
        self.search.textChanged.connect(self.manager.set_search_text)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.addLayout(header)
        right_layout.addWidget(self.manager, stretch=1)

        split = QSplitter()
        split.setOrientation(Qt.Orientation.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addWidget(split)
        self.setCentralWidget(root)

        self.nav.setCurrentRow(0)

    def _get_tool_path_or_none(self) -> Path | None:
        raw = (self._cfg.compressonatorcli_path or "").strip()
        if not raw:
            return None
        p = Path(raw).expanduser()
        try:
            p = p.resolve(strict=False)
        except OSError:
            return None
        # 误填「.」或目录时 exists 为真但不可执行，预览会崩；必须指向普通文件
        return p if p.is_file() else None

    def _open_settings(self) -> None:
        dlg = SettingsDialog(cfg=self._cfg, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            dlg.apply()
            QMessageBox.information(self, "已保存", "设置已保存。")
            self._on_refresh()

    def _on_refresh(self) -> None:
        self.manager.reload()

    def _on_nav_changed(self, idx: int) -> None:
        self.search.setText("")
        if idx == 0:
            self.title.setText("角色")
            self.manager.set_kind("Chara")
        elif idx == 1:
            self.title.setText("地图")
            self.manager.set_kind("Map")
        elif idx == 2:
            self.title.setText("Event")
            self.manager.set_kind("Event")
        elif idx == 3:
            self.title.setText("歌曲")
            self.manager.set_kind("Music")
        elif idx == 4:
            self.title.setText("称号")
            self.manager.set_kind("Trophy")
        elif idx == 5:
            self.title.setText("名牌")
            self.manager.set_kind("NamePlate")
        elif idx == 6:
            self.title.setText("奖励")
            self.manager.set_kind("Reward")
        else:
            self.title.setText("角色")
            self.manager.set_kind("Chara")

    def _on_add(self) -> None:
        idx = self.nav.currentRow()
        if idx == 6:
            music_r, chara_r, trophy_r, np_r, default_id = reward_dialog_bundle(self._acus_root)
            dlg = RewardCreateDialog(
                default_id=default_id,
                music_refs=music_r,
                chara_refs=chara_r,
                trophy_refs=trophy_r,
                nameplate_refs=np_r,
                parent=self,
            )
            if dlg.exec() == dlg.DialogCode.Accepted and dlg.result_cell is not None:
                ensure_reward_xml(self._acus_root, dlg.result_cell)
                self._on_refresh()
            return

        if idx == 3:
            dlg = MusicTrophyDialog(acus_root=self._acus_root, parent=self)
            if dlg.exec() == dlg.DialogCode.Accepted:
                self._on_refresh()
            return

        tool = self._get_tool_path_or_none()
        if tool is None and not quicktex_available():
            QMessageBox.critical(
                self,
                "无法生成 DDS",
                "请任选其一：\n"
                "• 运行 pip install quicktex（推荐，可不装 compressonator）\n"
                "• 或在左下角【设置】里配置 compressonatorcli 可执行文件路径",
            )
            return

        if idx == 0:
            dlg = CharaAddDialog(acus_root=self._acus_root, tool_path=tool, parent=self)
            if dlg.exec() == dlg.DialogCode.Accepted:
                self._on_refresh()
        elif idx == 1:
            dlg = MapAddDialog(acus_root=self._acus_root, tool_path=tool, parent=self)
            if dlg.exec() == dlg.DialogCode.Accepted:
                self._on_refresh()
        elif idx == 4:
            dlg = TrophyAddDialog(acus_root=self._acus_root, tool_path=tool, parent=self)
            if dlg.exec() == dlg.DialogCode.Accepted:
                self._on_refresh()
        elif idx == 5:
            dlg = NamePlateAddDialog(acus_root=self._acus_root, tool_path=tool, parent=self)
            if dlg.exec() == dlg.DialogCode.Accepted:
                self._on_refresh()
        else:
            QMessageBox.information(
                self,
                "未实现",
                "当前已实现【新增角色】【新增地图】【新增歌曲课题称号】【新增称号】【新增名牌】【新增奖励】。"
                "Event / DDSImage 等请直接在 ACUS 目录维护或用其它工具。",
            )

