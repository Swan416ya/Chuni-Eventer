from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QPoint, QThread, QTimer, pyqtSignal, Qt
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from qfluentwidgets import BodyLabel, CardWidget, PrimaryPushButton, PushButton

from ..pjsk_sheet_client import (
    PjskDifficultyRow,
    PjskMusicRow,
    load_difficulties_index,
    load_musics_catalog,
    pjsk_cache_root,
    pjsk_song_cache_dir,
    save_pjsk_bundle_to_cache,
)
from .fluent_dialogs import fly_critical, fly_message, fly_warning
from .fluent_table import apply_fluent_sheet_table
from .sus_c2s_debug_dialog import SusC2sDebugDialog


class _LoadCatalogThread(QThread):
    ok = pyqtSignal(object, object)
    fail = pyqtSignal(str)

    def run(self) -> None:
        try:
            musics = load_musics_catalog()
            diffs = load_difficulties_index()
            self.ok.emit(musics, diffs)
        except Exception as e:
            self.fail.emit(str(e))


class _PjskCacheThread(QThread):
    ok = pyqtSignal(str)
    fail = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(
        self,
        *,
        acus_root: Path,
        row: PjskMusicRow,
        available_diffs: set[str],
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self._acus_root = acus_root
        self._row = row
        self._available_diffs = available_diffs

    def run(self) -> None:
        try:
            save_pjsk_bundle_to_cache(
                self._acus_root,
                music_id=self._row.music_id,
                title=self._row.title,
                composer=self._row.composer,
                assetbundle_name=self._row.assetbundle_name,
                available_pjsk_difficulties=self._available_diffs,
                progress=self.progress.emit,
            )
            root = pjsk_song_cache_dir(self._acus_root, self._row.music_id)
            self.ok.emit(str(root.resolve()))
        except Exception as e:
            self.fail.emit(str(e))


class PjskSusDownloadDialog(QDialog):
    """PJSK：缓存封面、曲绘与固定难度 SUS，并尝试生成实验性 c2s。"""

    def __init__(self, *, acus_root: Path, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("从 Project SEKAI 缓存资源（实验性）")
        self.setModal(True)
        self.resize(760, 520)
        self.setObjectName("pjskSusDownloadDialog")
        win_bg = QApplication.palette().color(QPalette.ColorRole.Window).name()
        self.setStyleSheet(f"#pjskSusDownloadDialog {{ background-color: {win_bg}; }}")
        self._acus_root = acus_root.resolve()
        self._musics: list[PjskMusicRow] = []
        self._diff_index: dict[int, list[PjskDifficultyRow]] = {}
        self._load_thread: _LoadCatalogThread | None = None
        self._cache_thread: _PjskCacheThread | None = None
        self._sus_c2s_debug_win: SusC2sDebugDialog | None = None
        self._header_debug_timer = QTimer(self)
        self._header_debug_timer.setSingleShot(True)
        self._header_debug_timer.timeout.connect(self._open_sus_c2s_debug)

        card = CardWidget(self)

        warn = BodyLabel(
            "【实验】本渠道将资源缓存到本地，并会用内置规则从 SUS 生成 UTF-8 文本 c2s（chuni/ 下各难度）。"
            "转换为首版逻辑：时间轴、滑条链、天空键等与官谱或编辑器可能仍有差异，需在目标环境中自行验证。"
            "若需要可直接游玩的谱面包，也可在「新增」里选择 Swan 站渠道查找现成资源。"
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("color: #b45309;")

        _cache_root = pjsk_cache_root(self._acus_root)
        hint = BodyLabel(
            "将自动下载：封面.png、曲绘.png（与封面同源或第二镜像），"
            "以及谱面 normal / hard / expert / master / append（曲目上存在的才会下载；"
            "无 append 则无 ULTIMA 对应 sus）。"
            f"保存目录与 ACUS 同级：{(_cache_root / 'pjsk_曲目ID').as_posix()}"
        )
        hint.setWordWrap(True)

        self._filter = QLineEdit(card)
        self._filter.setPlaceholderText("按曲名或作曲家过滤…")
        self._filter.textChanged.connect(self._apply_filter)

        self._table = QTableWidget(0, 4, card)
        apply_fluent_sheet_table(self._table)
        self._table.setHorizontalHeaderLabels(["ID", "曲名", "作曲家", "资源包"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.doubleClicked.connect(lambda _i: self._on_download())
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_table_context_menu)

        self._status = BodyLabel("正在加载曲目列表…", card)
        self._status.setWordWrap(True)

        cly = QVBoxLayout(card)
        cly.setContentsMargins(16, 16, 16, 16)
        cly.setSpacing(10)
        cly.addWidget(warn)
        cly.addWidget(hint)
        cly.addWidget(self._filter)
        cly.addWidget(self._table, stretch=1)
        cly.addWidget(self._status)

        refresh = PushButton("重新加载列表", self)
        refresh.clicked.connect(self._on_reload)
        dl_btn = PrimaryPushButton("下载选中曲目到缓存", self)
        dl_btn.clicked.connect(self._on_download)
        close = PushButton("关闭", self)
        close.clicked.connect(self.reject)

        btns = QHBoxLayout()
        btns.setContentsMargins(0, 0, 0, 0)
        btns.addWidget(refresh)
        btns.addStretch(1)
        btns.addWidget(dl_btn)
        btns.addWidget(close)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)
        lay.addWidget(card, stretch=1)
        lay.addLayout(btns)

        QTimer.singleShot(0, self._on_reload)

    def _on_table_context_menu(self, pos: QPoint) -> None:
        idx = self._table.indexAt(pos)
        if not idx.isValid() or idx.column() != 0:
            return
        self._open_sus_c2s_debug()

    def _open_sus_c2s_debug(self) -> None:
        dlg = SusC2sDebugDialog(
            acus_root=self._acus_root,
            selected_music_id_fn=self._selected_music_id,
            parent=self,
        )
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _on_reload(self) -> None:
        if self._pjsk_load_thread_busy():
            return
        self._status.setText("正在加载曲目与难度索引…")
        self._table.setRowCount(0)
        self._musics.clear()
        self._diff_index.clear()
        th = _LoadCatalogThread(parent=self)
        self._load_thread = th
        th.ok.connect(self._on_catalog_ok)
        th.fail.connect(self._on_catalog_fail)
        th.finished.connect(lambda t=th: self._release_pjsk_load_thread(t))
        th.start()

    def _on_catalog_ok(self, musics: object, diff_index: object) -> None:
        if not isinstance(musics, list) or not all(isinstance(m, PjskMusicRow) for m in musics):
            self._status.setText("数据格式错误。")
            return
        if not isinstance(diff_index, dict):
            self._status.setText("难度索引格式错误。")
            return
        self._musics = musics
        self._diff_index = diff_index
        self._status.setText(
            f"已加载 {len(self._musics)} 首曲目。选中一行后点「下载选中曲目到缓存」或双击表格行。"
        )
        self._apply_filter()

    def _on_catalog_fail(self, msg: str) -> None:
        self._status.setText("加载失败。")
        fly_critical(self, "无法加载 PJSK 曲目数据", msg)

    def _apply_filter(self) -> None:
        q = self._filter.text().strip().lower()
        self._table.setRowCount(0)
        shown: list[PjskMusicRow] = []
        for m in self._musics:
            if q:
                blob = f"{m.music_id} {m.title} {m.composer} {m.assetbundle_name}".lower()
                if q not in blob:
                    continue
            shown.append(m)
        self._table.setRowCount(len(shown))
        for i, m in enumerate(shown):
            self._table.setItem(i, 0, QTableWidgetItem(str(m.music_id)))
            self._table.setItem(i, 1, QTableWidgetItem(m.title))
            self._table.setItem(i, 2, QTableWidgetItem(m.composer))
            self._table.setItem(i, 3, QTableWidgetItem(m.assetbundle_name))
            for c in range(4):
                it = self._table.item(i, c)
                if it:
                    it.setData(Qt.ItemDataRole.UserRole, m.music_id)
                    it.setTextAlignment(
                        int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                    )

    def _selected_music_id(self) -> int | None:
        r = self._table.currentRow()
        if r < 0:
            return None
        it = self._table.item(r, 0)
        if it is None:
            return None
        v = it.data(Qt.ItemDataRole.UserRole)
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    def _music_row_by_id(self, mid: int) -> PjskMusicRow | None:
        for m in self._musics:
            if m.music_id == mid:
                return m
        return None

    def _pjsk_load_thread_busy(self) -> bool:
        th = self._load_thread
        if th is None:
            return False
        try:
            return th.isRunning()
        except RuntimeError:
            self._load_thread = None
            return False

    def _release_pjsk_load_thread(self, th: QObject) -> None:
        if self._load_thread is th:
            self._load_thread = None
        th.deleteLater()

    def _pjsk_cache_thread_busy(self) -> bool:
        th = self._cache_thread
        if th is None:
            return False
        try:
            return th.isRunning()
        except RuntimeError:
            self._cache_thread = None
            return False

    def _release_pjsk_cache_thread(self, th: QObject) -> None:
        if self._cache_thread is th:
            self._cache_thread = None
        th.deleteLater()

    def _on_download(self) -> None:
        mid = self._selected_music_id()
        if mid is None:
            fly_warning(self, "未选择曲目", "请先在表格中选择一首乐曲。")
            return
        row = self._music_row_by_id(mid)
        if row is None:
            fly_warning(self, "内部错误", "找不到所选曲目数据。")
            return
        if not row.assetbundle_name.strip():
            fly_warning(
                self,
                "缺少资源包名",
                "该曲目没有 assetbundleName，无法下载封面；仍会继续尝试下载谱面。",
            )
        diffs = self._diff_index.get(mid, [])
        avail = {d.music_difficulty.strip().lower() for d in diffs}
        if self._pjsk_cache_thread_busy():
            return
        self._status.setText("正在下载…")
        th = _PjskCacheThread(
            acus_root=self._acus_root,
            row=row,
            available_diffs=avail,
            parent=self,
        )
        self._cache_thread = th
        th.progress.connect(self._status.setText)
        th.ok.connect(self._on_cache_ok)
        th.fail.connect(self._on_cache_fail)
        th.finished.connect(lambda t=th: self._release_pjsk_cache_thread(t))
        th.start()

    def _on_cache_ok(self, path: str) -> None:
        self._status.setText("已写入缓存。")
        fly_message(self, "完成", f"已缓存到：\n{path}")

    def _on_cache_fail(self, msg: str) -> None:
        self._status.setText("下载失败。")
        fly_critical(self, "缓存失败", msg)
