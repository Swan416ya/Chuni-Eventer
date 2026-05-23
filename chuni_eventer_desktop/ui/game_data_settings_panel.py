from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon, QMouseEvent
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from qfluentwidgets import BodyLabel, CaptionLabel, CardWidget, LineEdit, PushButton

from ..acus_workspace import AcusConfig, resolve_compressonatorcli_path
from ..game_data_index import GameDataIndex, load_cached_game_index
from .fluent_dialogs import fly_critical, fly_warning
from .game_data_browse_dialog import GameDataBrowseDialog, GameDataKind
from .nav_icons import SVG_CHARA, SVG_MUSIC, SVG_NAMEPLATE, SVG_TROPHY, nav_qicon

_log = logging.getLogger("chuni.settings_dialog")

_TILE_ICON_PX = 52
_TILE_MIN_H = 96


class _GameDataCategoryTile(CardWidget):
    """白底描边卡片：上图标下文字，单行排列。"""

    def __init__(
        self,
        label: str,
        icon: QIcon,
        *,
        on_click: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(_TILE_MIN_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 14, 12, 14)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        icon_lbl = QLabel(self)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pm = icon.pixmap(QSize(_TILE_ICON_PX, _TILE_ICON_PX))
        icon_lbl.setPixmap(pm)
        icon_lbl.setFixedSize(_TILE_ICON_PX + 8, _TILE_ICON_PX + 8)

        text = CaptionLabel(label, self)
        text.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        lay.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(text, 0, Qt.AlignmentFlag.AlignHCenter)

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        if event is not None and event.button() == Qt.MouseButton.LeftButton:
            self._on_click()
        super().mouseReleaseEvent(event)

class GameDataSettingsPanel(QWidget):
    """设置 → 游戏数据：目录配置与四类资源浏览。"""

    def __init__(
        self,
        *,
        cfg: AcusConfig,
        acus_root: Path,
        get_tool_path: Callable[[], Path | None],
        get_game_index: Callable[[], GameDataIndex | None] | None = None,
        on_request_game_rescan: Callable[[Path, Path | None], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self._cfg = cfg
        self._acus_root = acus_root
        self._get_tool_path = get_tool_path
        self._get_game_index = get_game_index or (lambda: None)
        self._on_request_game_rescan = on_request_game_rescan

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(16)

        dir_card = CardWidget(self)
        dir_lay = QVBoxLayout(dir_card)
        dir_lay.setContentsMargins(16, 16, 16, 16)
        dir_lay.setSpacing(12)
        dir_lay.addWidget(BodyLabel("游戏数据目录", self))
        dir_hint = BodyLabel(
            "请选择包含 bin 和 data 两个文件夹的最上层文件夹。",
            self,
        )
        dir_hint.setWordWrap(True)
        dir_hint.setStyleSheet("color:#6B7280;font-size:13px;")
        dir_lay.addWidget(dir_hint)

        self.game_root = LineEdit(self)
        self.game_root.setPlaceholderText("例如 D:\\Games\\CHUNITHM")
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

        browse_card = CardWidget(self)
        browse_lay = QVBoxLayout(browse_card)
        browse_lay.setContentsMargins(16, 16, 16, 16)
        browse_lay.setSpacing(12)
        browse_lay.addWidget(BodyLabel("浏览游戏数据", self))
        self._summary = BodyLabel("", self)
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet("color:#6B7280;font-size:13px;")
        browse_lay.addWidget(self._summary)

        row = QHBoxLayout()
        row.setSpacing(12)
        row.setContentsMargins(0, 4, 0, 0)
        specs: list[tuple[str, GameDataKind, str]] = [
            ("乐曲", "music", SVG_MUSIC),
            ("角色", "chara", SVG_CHARA),
            ("称号", "trophy", SVG_TROPHY),
            ("名牌", "nameplate", SVG_NAMEPLATE),
        ]
        for label, kind, svg in specs:
            tile = _GameDataCategoryTile(
                label,
                nav_qicon(svg),
                on_click=lambda k=kind: self._open_browse(k),
                parent=self,
            )
            row.addWidget(tile, 1)
        browse_lay.addLayout(row)
        layout.addWidget(browse_card)
        tools_hint = BodyLabel(
            "预览曲绘/立绘需 quicktex 或 compressonatorcli；导出 OGG 需 PyCriCodecsEx 与 ffmpeg。",
            self,
        )
        tools_hint.setWordWrap(True)
        tools_hint.setStyleSheet("color:#6B7280;font-size:13px;")
        layout.addWidget(tools_hint)
        layout.setContentsMargins(0, 0, 0, 16)

        self.refresh_index_display()

    def refresh_index_display(self) -> None:
        idx = self._get_game_index()
        if idx is None:
            gr = self.game_root.text().strip() or (self._cfg.game_root or "").strip()
            if gr:
                idx = load_cached_game_index(gr)
        if idx is None:
            self._summary.setText("暂无索引。保存目录后将自动后台扫描，或点击「重新扫描」。")
            return
        self._summary.setText(
            f"已索引 {len(idx.music_catalog or idx.music)} 首乐曲、"
            f"{len(idx.chara_catalog or idx.chara)} 个角色、"
            f"{len(idx.trophy_catalog or idx.trophy)} 个称号、"
            f"{len(idx.nameplate_catalog or idx.nameplate)} 个名牌。"
            f"（stage / ddsImage / ddsMap 等 {len(idx.stage) + len(idx.dds_image) + len(idx.dds_map)} 条已同步，供新增乐曲选 stage 等编辑功能使用。）"
        )

    def _game_root_path(self) -> Path | None:
        raw = self.game_root.text().strip() or (self._cfg.game_root or "").strip()
        if not raw:
            return None
        p = Path(raw).expanduser()
        return p if p.is_dir() else None

    def _open_browse(self, kind: GameDataKind) -> None:
        root = self._game_root_path()
        if root is None:
            fly_warning(self, "未设置目录", "请先选择有效的游戏数据目录并重新扫描。")
            return
        GameDataBrowseDialog(
            kind=kind,
            game_root=root,
            acus_root=self._acus_root,
            get_index=self._get_game_index,
            get_tool_path=self._get_tool_path,
            parent=self.window(),
        ).exec()

    def _pick_game_root(self) -> None:
        from PyQt6.QtWidgets import QFileDialog

        d = QFileDialog.getExistingDirectory(
            self,
            "选择游戏数据目录",
        )
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
