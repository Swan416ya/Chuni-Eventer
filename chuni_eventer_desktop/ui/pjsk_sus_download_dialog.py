from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QObject, QPoint, QThread, QTimer, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from qfluentwidgets import BodyLabel, CardWidget, LineEdit, PrimaryPushButton, PushButton

from ..pjsk_sheet_client import (
    PjskDifficultyRow,
    PjskMusicRow,
    load_difficulties_index,
    load_music_vocals_for_music,
    load_musics_catalog,
    pjsk_cache_root,
    pjsk_song_cache_dir,
    save_pjsk_bundle_to_cache,
)
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical, fly_message, fly_warning
from .fluent_table import apply_fluent_sheet_table
from .pjsk_vocal_pick_dialog import PjskVocalPickDialog
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
    # (状态文案, 进度 0~1；-1.0 表示不确定：连接中、换镜像、或无 Content-Length)
    progress = pyqtSignal(str, float)

    def __init__(
        self,
        *,
        acus_root: Path,
        row: PjskMusicRow,
        available_diffs: set[str],
        vocal_assetbundle: str | None,
        vocal_caption: str | None,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self._acus_root = acus_root
        self._row = row
        self._available_diffs = available_diffs
        self._vocal_ab = vocal_assetbundle
        self._vocal_cap = vocal_caption

    def run(self) -> None:
        try:

            def _prog(msg: str, ratio: float | None = None) -> None:
                r = -1.0 if ratio is None else float(max(0.0, min(1.0, ratio)))
                self.progress.emit(msg, r)

            save_pjsk_bundle_to_cache(
                self._acus_root,
                music_id=self._row.music_id,
                title=self._row.title,
                composer=self._row.composer,
                assetbundle_name=self._row.assetbundle_name,
                available_pjsk_difficulties=self._available_diffs,
                progress=_prog,
                vocal_assetbundle=self._vocal_ab,
                vocal_caption=self._vocal_cap,
            )
            root = pjsk_song_cache_dir(self._acus_root, self._row.music_id)
            self.ok.emit(str(root.resolve()))
        except Exception as e:
            self.fail.emit(str(e))


class PjskSusDownloadDialog(FluentCaptionDialog):
    """PJSK：缓存封面、曲绘与固定难度 SUS，后续由 PenguinTools.CLI 负责转 c2s。"""

    def __init__(
        self,
        *,
        acus_root: Path,
        parent=None,
        on_installed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("从 Project SEKAI 缓存资源（实验性）")
        self.setModal(True)
        self.resize(780, 540)
        self._acus_root = acus_root.resolve()
        self._musics: list[PjskMusicRow] = []
        self._diff_index: dict[int, list[PjskDifficultyRow]] = {}
        self._load_thread: _LoadCatalogThread | None = None
        self._cache_thread: _PjskCacheThread | None = None
        self._sus_c2s_debug_win: SusC2sDebugDialog | None = None
        self._on_installed = on_installed

        card = CardWidget(self)

        warn = BodyLabel(
            "SUS→c2s 现改为调用 PenguinTools.CLI。"
            "本窗口仍只缓存 SUS/封面/音频；真正生成 chuni/*.c2s 会在后续转写到 ACUS 时执行。"
            "若未正确配置 PenguinTools.CLI，该步骤会失败并提示检查外部工具路径。"
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("color: #0f766e;")

        _cache_root = pjsk_cache_root(self._acus_root)
        hint = BodyLabel(
            "将自动下载：封面.png、曲绘.png（与封面同源或第二镜像），"
            "谱面 normal / hard / expert / master / append（曲目上存在的才会下载；无 append 则无 ULTIMA 对应 sus），"
            "以及完整音频：若该曲在 PJSK 有多个 musicVocals 版本，下载前会弹出列表供选择；仅 1 个版本时自动选用。"
            "原始音频为 flac/wav/mp3（视镜像）；若本机已装 ffmpeg 与 PyCriCodecsEx，将尝试自动生成修剪后的 48k WAV 与中二用 ACB/AWB。"
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

        self._dl_progress = QProgressBar(card)
        self._dl_progress.setRange(0, 100)
        self._dl_progress.setValue(0)
        self._dl_progress.setTextVisible(True)
        self._dl_progress.setFormat("")
        self._dl_progress.setFixedHeight(22)

        cly = QVBoxLayout(card)
        cly.setContentsMargins(16, 16, 16, 16)
        cly.setSpacing(10)
        cly.addWidget(warn)
        cly.addWidget(hint)
        cly.addWidget(self._filter)
        cly.addWidget(self._table, stretch=1)
        cly.addWidget(self._status)
        cly.addWidget(self._dl_progress)

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
        lay.setContentsMargins(*fluent_caption_content_margins())
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

        self._status.setText("正在查询人声版本（musicVocals）…")
        QApplication.processEvents()
        try:
            vocals = load_music_vocals_for_music(mid)
        except Exception as e:
            self._status.setText("人声索引失败。")
            fly_critical(self, "无法加载 musicVocals", str(e))
            return

        vocal_ab: str | None = None
        vocal_cap: str | None = None
        if not vocals:
            self._status.setText("未找到人声版本条目，将仅下载封面与谱面。")
        elif len(vocals) == 1:
            vocal_ab = vocals[0].assetbundle_name
            vocal_cap = vocals[0].caption
        else:
            dlg = PjskVocalPickDialog(vocals, parent=self)
            code = dlg.exec()
            if code != QDialog.DialogCode.Accepted:
                self._status.setText("已取消下载。")
                return
            if dlg.skip_audio:
                vocal_ab = None
                vocal_cap = None
            elif dlg.selected is not None:
                vocal_ab = dlg.selected.assetbundle_name
                vocal_cap = dlg.selected.caption

        self._reset_cache_progress_bar()
        self._status.setText("正在下载…")
        th = _PjskCacheThread(
            acus_root=self._acus_root,
            row=row,
            available_diffs=avail,
            vocal_assetbundle=vocal_ab,
            vocal_caption=vocal_cap,
            parent=self,
        )
        self._cache_thread = th
        th.progress.connect(self._on_cache_progress)
        th.ok.connect(self._on_cache_ok)
        th.fail.connect(self._on_cache_fail)
        th.finished.connect(lambda t=th: self._release_pjsk_cache_thread(t))
        th.start()

    def _on_cache_progress(self, text: str, ratio: float) -> None:
        self._status.setText(text)
        if ratio < 0:
            self._dl_progress.setRange(0, 0)
            self._dl_progress.setFormat("")
        else:
            self._dl_progress.setRange(0, 1000)
            self._dl_progress.setValue(min(1000, int(ratio * 1000)))
            self._dl_progress.setFormat(f"{ratio * 100:.1f}%")

    def _reset_cache_progress_bar(self) -> None:
        self._dl_progress.setRange(0, 100)
        self._dl_progress.setValue(0)
        self._dl_progress.setFormat("")

    def _on_cache_ok(self, path: str) -> None:
        self._status.setText("已写入缓存。")
        self._dl_progress.setRange(0, 100)
        self._dl_progress.setValue(100)
        self._dl_progress.setFormat("100%")
        fly_message(self, "完成", f"已缓存到：\n{path}")
        if self._on_installed:
            self._on_installed()

    def _on_cache_fail(self, msg: str) -> None:
        self._status.setText("下载失败。")
        self._reset_cache_progress_bar()
        fly_critical(self, "缓存失败", msg)
