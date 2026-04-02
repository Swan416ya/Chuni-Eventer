from __future__ import annotations

from pathlib import Path
import zipfile

from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from qfluentwidgets import BodyLabel, CardWidget, PrimaryPushButton, PushButton

from ..acus_workspace import app_cache_dir
from ..pgko_sheet_client import (
    PGKO_BASE_URL,
    PgkoSheetPage,
    PgkoSheetEntry,
    download_pgko_sheet,
    fetch_pgko_sheet_page,
    resolve_pgko_download_from_bundle,
)
from .fluent_dialogs import fly_critical, fly_message, fly_warning
from .fluent_table import apply_fluent_sheet_table


class _FetchPgkoThread(QThread):
    ok = pyqtSignal(object)
    fail = pyqtSignal(str)

    def __init__(self, cursor: str | None, parent=None) -> None:
        super().__init__(parent=parent)
        self._cursor = cursor

    def run(self) -> None:
        try:
            self.ok.emit(fetch_pgko_sheet_page(base_url=PGKO_BASE_URL, cursor=self._cursor))
        except Exception as e:
            self.fail.emit(str(e))


class _DownloadPgkoThread(QThread):
    ok = pyqtSignal(str, str, bool)  # output_path, ext, extracted_zip
    fail = pyqtSignal(str)
    resolved = pyqtSignal(str)

    def __init__(self, entry: PgkoSheetEntry, parent=None) -> None:
        super().__init__(parent=parent)
        self._entry = entry

    def run(self) -> None:
        try:
            download_url, ext = resolve_pgko_download_from_bundle(self._entry, PGKO_BASE_URL)
            self.resolved.emit(
                f"bundle={self._entry.bundle_id}\n"
                f"detail={self._entry.detail_url}\n"
                f"download={download_url}\n"
                f"ext_guess={ext}"
            )
            data = download_pgko_sheet(download_url)
            cache = app_cache_dir() / "pgko_downloads"
            cache.mkdir(parents=True, exist_ok=True)
            safe_name = "".join(c if c not in '\\/:*?"<>|' else "_" for c in self._entry.title).strip() or "pgko_sheet"
            # pgko 返回体通常是 zip；优先按 zip 解包到目录
            zip_path = cache / f"{safe_name}.zip"
            zip_path.write_bytes(data)
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    out_dir = cache / safe_name
                    out_dir.mkdir(parents=True, exist_ok=True)
                    zf.extractall(out_dir)
                self.ok.emit(str(out_dir), ext, True)
            except zipfile.BadZipFile:
                # 兼容极端情况：如果不是 zip，回退为原始单文件
                raw_path = cache / f"{safe_name}.{ext}"
                raw_path.write_bytes(data)
                self.ok.emit(str(raw_path), ext, False)
        except Exception as e:
            self.fail.emit(str(e))


class PgkoSheetDownloadDialog(QDialog):
    def __init__(self, *, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("从 pgko.dev 下载谱面")
        self.setModal(True)
        self.resize(760, 540)

        self._entries: list[PgkoSheetEntry] = []
        self._fetch_thread: _FetchPgkoThread | None = None
        self._download_thread: _DownloadPgkoThread | None = None
        self._next_cursor: str | None = None
        self._is_fetching_more = False
        self._seen_bundle_ids: set[str] = set()

        card = CardWidget(self)
        hint = BodyLabel(
            "加载 pgko.dev 可下载的 ugc/mrgc。双击行或点击下载保存到本地缓存。"
            "下载完成后可选择是否转码为 c2s（当前仅提供入口，转码逻辑待实现）。"
        )
        hint.setWordWrap(True)

        self._table = QTableWidget(0, 4, self)
        apply_fluent_sheet_table(self._table)
        self._table.setHorizontalHeaderLabels(["标题", "艺术家", "详情页", "来源"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.doubleClicked.connect(lambda _i: self._on_download())
        self._table.verticalScrollBar().valueChanged.connect(self._on_scroll_value_changed)

        self._status = BodyLabel("点击“刷新列表”加载。")
        self._status.setWordWrap(True)

        cly = QVBoxLayout(card)
        cly.setContentsMargins(16, 16, 16, 16)
        cly.setSpacing(10)
        cly.addWidget(hint)
        cly.addWidget(self._table, stretch=1)
        cly.addWidget(self._status)

        refresh = PushButton("刷新列表", self)
        refresh.clicked.connect(self._on_refresh)
        dl = PrimaryPushButton("下载选中项", self)
        dl.clicked.connect(self._on_download)
        close = PushButton("关闭", self)
        close.clicked.connect(self.reject)

        btns = QHBoxLayout()
        btns.addWidget(refresh)
        btns.addStretch(1)
        btns.addWidget(dl)
        btns.addWidget(close)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)
        lay.addWidget(card, stretch=1)
        lay.addLayout(btns)

        self._on_refresh()

    @staticmethod
    def _thread_running_safe(th: QThread | None) -> bool:
        if th is None:
            return False
        try:
            return th.isRunning()
        except RuntimeError:
            return False

    def _attach_fetch_thread(self, th: _FetchPgkoThread) -> None:
        self._fetch_thread = th
        th.ok.connect(self._on_fetch_ok)
        th.fail.connect(self._on_fetch_fail)

        def _on_finished() -> None:
            # 先清空引用，再 deleteLater，避免后续访问已释放对象
            if self._fetch_thread is th:
                self._fetch_thread = None
            th.deleteLater()

        th.finished.connect(_on_finished)
        th.start()

    def _on_refresh(self) -> None:
        if self._thread_running_safe(self._fetch_thread):
            return
        self._next_cursor = None
        self._seen_bundle_ids.clear()
        self._is_fetching_more = False
        self._entries.clear()
        self._table.setRowCount(0)
        self._status.setText("正在加载 pgko.dev 列表…")
        self._attach_fetch_thread(_FetchPgkoThread(cursor=None, parent=self))

    def _on_fetch_ok(self, rows: object) -> None:
        if not isinstance(rows, PgkoSheetPage):
            self._status.setText("列表格式错误。")
            self._is_fetching_more = False
            return
        added = 0
        for e in rows.entries:
            if e.bundle_id in self._seen_bundle_ids:
                continue
            self._seen_bundle_ids.add(e.bundle_id)
            self._entries.append(e)
            r = self._table.rowCount()
            self._table.insertRow(r)
            self._table.setItem(r, 0, QTableWidgetItem(e.title))
            self._table.setItem(r, 1, QTableWidgetItem(e.artist))
            self._table.setItem(r, 2, QTableWidgetItem(e.detail_url))
            self._table.setItem(r, 3, QTableWidgetItem("pgko.dev"))
            added += 1
        self._next_cursor = rows.next_cursor
        self._is_fetching_more = False
        if self._next_cursor:
            self._status.setText(
                f"已加载 {len(self._entries)} 条（本次 +{added}）。下拉可继续加载…"
            )
        else:
            self._status.setText(f"已加载全部 {len(self._entries)} 条。")

    def _on_fetch_fail(self, msg: str) -> None:
        self._status.setText("加载失败。")
        self._is_fetching_more = False
        fly_critical(self, "读取 pgko.dev 失败", msg)

    def _fetch_more(self) -> None:
        if not self._next_cursor:
            return
        if self._is_fetching_more:
            return
        if self._thread_running_safe(self._fetch_thread):
            return
        self._is_fetching_more = True
        self._status.setText(
            f"正在加载更多…（当前 {len(self._entries)} 条）"
        )
        self._attach_fetch_thread(_FetchPgkoThread(cursor=self._next_cursor, parent=self))

    def _on_scroll_value_changed(self, value: int) -> None:
        bar = self._table.verticalScrollBar()
        # 接近底部时触发下一页
        if value >= max(0, bar.maximum() - 3):
            self._fetch_more()

    def _selected(self) -> PgkoSheetEntry | None:
        r = self._table.currentRow()
        if r < 0 or r >= len(self._entries):
            return None
        return self._entries[r]

    def _on_download(self) -> None:
        e = self._selected()
        if e is None:
            fly_warning(self, "未选择", "请先选择一条谱面。")
            return
        if self._download_thread and self._download_thread.isRunning():
            return
        self._status.setText(f"正在下载：{e.title} …")
        self._download_thread = _DownloadPgkoThread(e, parent=self)
        self._download_thread.resolved.connect(self._on_download_resolved)
        self._download_thread.ok.connect(self._on_download_ok)
        self._download_thread.fail.connect(self._on_download_fail)
        self._download_thread.finished.connect(self._download_thread.deleteLater)
        self._download_thread.start()

    def _on_download_resolved(self, text: str) -> None:
        # 直接输出解析到的下载链接，便于用户复制调试
        self._status.setText(f"已解析下载链接：\n{text}")

    def _on_download_ok(self, output_path: str, ext: str, extracted_zip: bool) -> None:
        self._status.setText("下载完成。")
        if extracted_zip:
            target_tip = f"已解压到目录：\n{output_path}"
        else:
            target_tip = f"返回体非 zip，已按原始文件保存：\n{output_path}"
        ans = QMessageBox.question(
            self,
            "下载完成",
            f"{target_tip}\n\n是否尝试转码为中二 c2s？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            fly_message(
                self,
                "转码未实现",
                f"已记录选择：{Path(output_path).name}（{ext}）-> c2s。\n当前版本先不实现 ugc/mrgc 转码。",
            )
        else:
            fly_message(self, "已下载", target_tip)

    def _on_download_fail(self, msg: str) -> None:
        self._status.setText("下载失败。")
        fly_critical(
            self,
            "下载失败",
            "下载过程中发生错误。\n\n"
            "调试信息（复制给开发者）：\n"
            f"{msg}",
        )

