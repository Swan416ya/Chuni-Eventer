from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PyQt6.QtCore import QThread, QTimer, pyqtSignal, Qt
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from qfluentwidgets import BodyLabel, CardWidget, PrimaryPushButton, PushButton

from .fluent_table import apply_fluent_sheet_table

from ..sheet_install import install_zip_to_acus
from ..swan_sheet_client import (
    SWAN_SHEET_API_BASE_URL,
    SheetListEntry,
    download_sheet_archive,
    list_downloadable_sheets,
)
from .fluent_dialogs import fly_critical, fly_message, fly_warning


class _FetchSheetsThread(QThread):
    ok = pyqtSignal(list)
    fail = pyqtSignal(str)

    def __init__(self, base_url: str, parent=None) -> None:
        super().__init__(parent=parent)
        self._base = base_url

    def run(self) -> None:
        try:
            rows = list_downloadable_sheets(self._base)
            self.ok.emit(rows)
        except Exception as e:
            self.fail.emit(str(e))


class _InstallSheetThread(QThread):
    ok = pyqtSignal(str)
    fail = pyqtSignal(str)

    def __init__(self, base_url: str, content_id: int, acus_root: Path, parent=None) -> None:
        super().__init__(parent=parent)
        self._base = base_url
        self._cid = content_id
        self._acus = acus_root

    def run(self) -> None:
        try:
            data = download_sheet_archive(self._base, self._cid)
            # 不写死 .zip：服务端可能是 zip/tar/7z/rar 等任意包；由 sheet_install 嗅探/解压
            fd, path = tempfile.mkstemp(prefix="chuni_swan_")
            os.close(fd)
            tmp = Path(path)
            try:
                tmp.write_bytes(data)
                written = install_zip_to_acus(tmp, self._acus)
                n = len(written)
                self.ok.emit(f"已写入 {n} 个文件到 ACUS。")
            finally:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
        except Exception as e:
            self.fail.emit(str(e))


class SwanSheetDownloadDialog(QDialog):
    def __init__(self, *, acus_root: Path, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("从 Swan 站下载铺面")
        self.setModal(True)
        self.resize(720, 520)
        self.setObjectName("swanSheetDownloadDialog")
        win_bg = QApplication.palette().color(QPalette.ColorRole.Window).name()
        self.setStyleSheet(
            f"#swanSheetDownloadDialog {{ background-color: {win_bg}; }}"
        )
        self._acus_root = acus_root
        self._base_url = SWAN_SHEET_API_BASE_URL
        self._entries: list[SheetListEntry] = []
        self._fetch_thread: _FetchSheetsThread | None = None
        self._install_thread: _InstallSheetThread | None = None

        card = CardWidget(self)

        hint = BodyLabel(
            "以下为站点上已配置下载包的自制谱列表。"
            "选择一行后点击「下载并解压到 ACUS」。若加载失败请检查网络或服务是否可用。"
        )
        hint.setWordWrap(True)

        self._table = QTableWidget(0, 3, card)
        apply_fluent_sheet_table(self._table)
        self._table.setHorizontalHeaderLabels(["曲名", "艺术家", "网页标题"])
        for col in range(3):
            self._table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.Stretch
            )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.doubleClicked.connect(lambda _i: self._on_install())

        self._status = BodyLabel("点击「刷新列表」加载。", card)
        self._status.setWordWrap(True)

        cly = QVBoxLayout(card)
        cly.setContentsMargins(16, 16, 16, 16)
        cly.setSpacing(10)
        cly.addWidget(hint)
        cly.addWidget(self._table, stretch=1)
        cly.addWidget(self._status)

        refresh = PushButton("刷新列表", self)
        refresh.clicked.connect(self._on_refresh)
        install = PrimaryPushButton("下载并解压到 ACUS", self)
        install.clicked.connect(self._on_install)
        close = PushButton("关闭", self)
        close.clicked.connect(self.reject)

        btns = QHBoxLayout()
        btns.setContentsMargins(0, 0, 0, 0)
        btns.addWidget(refresh)
        btns.addStretch(1)
        btns.addWidget(install)
        btns.addWidget(close)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)
        lay.addWidget(card, stretch=1)
        lay.addLayout(btns)

        QTimer.singleShot(0, self._on_refresh)

    def _on_refresh(self) -> None:
        base = self._base_url
        if self._fetch_thread and self._fetch_thread.isRunning():
            return
        self._status.setText("正在加载列表…")
        self._table.setRowCount(0)
        self._entries.clear()
        th = _FetchSheetsThread(base, parent=self)
        self._fetch_thread = th
        th.ok.connect(self._on_fetch_ok)
        th.fail.connect(self._on_fetch_fail)
        th.finished.connect(lambda t=th: self._finalize_fetch_thread(t))
        th.start()

    def _on_fetch_ok(self, rows: object) -> None:
        if not isinstance(rows, list):
            self._status.setText("列表格式错误。")
            return
        self._entries = [r for r in rows if isinstance(r, SheetListEntry)]
        self._table.setRowCount(len(self._entries))
        for i, e in enumerate(self._entries):
            self._table.setItem(i, 0, QTableWidgetItem(e.music_name))
            self._table.setItem(i, 1, QTableWidgetItem(e.artist_name))
            self._table.setItem(i, 2, QTableWidgetItem(e.title))
            for c in range(3):
                it = self._table.item(i, c)
                if it:
                    it.setTextAlignment(
                        int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                    )
        self._status.setText(f"共 {len(self._entries)} 条可下载铺面。")

    def _on_fetch_fail(self, msg: str) -> None:
        self._status.setText("加载失败。")
        fly_critical(self, "无法获取铺面列表", msg)

    def _finalize_fetch_thread(self, th: _FetchSheetsThread) -> None:
        if self._fetch_thread is th:
            self._fetch_thread = None
        th.deleteLater()

    def _finalize_install_thread(self, th: _InstallSheetThread) -> None:
        if self._install_thread is th:
            self._install_thread = None
        th.deleteLater()

    def _selected_entry(self) -> SheetListEntry | None:
        r = self._table.currentRow()
        if r < 0 or r >= len(self._entries):
            return None
        return self._entries[r]

    def _on_install(self) -> None:
        e = self._selected_entry()
        if e is None:
            fly_warning(self, "未选择", "请先在表格中选择一条铺面。")
            return
        base = self._base_url
        if self._install_thread and self._install_thread.isRunning():
            return
        self._status.setText(f"正在下载并安装：{e.music_name or e.title or '所选条目'} …")
        th = _InstallSheetThread(base, e.content_id, self._acus_root, parent=self)
        self._install_thread = th
        th.ok.connect(self._on_install_ok)
        th.fail.connect(self._on_install_fail)
        th.finished.connect(lambda t=th: self._finalize_install_thread(t))
        th.start()

    def _on_install_ok(self, msg: str) -> None:
        self._status.setText("安装完成。")
        fly_message(self, "完成", msg)

    def _on_install_fail(self, msg: str) -> None:
        self._status.setText("安装失败。")
        fly_critical(self, "下载或解压失败", msg)
