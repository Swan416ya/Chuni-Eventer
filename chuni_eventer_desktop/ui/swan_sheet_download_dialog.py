from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QHBoxLayout,
    QProgressDialog,
    QVBoxLayout,
)

from qfluentwidgets import BodyLabel, CardWidget, PrimaryPushButton, PushButton, TableView

from .fluent_table import (
    apply_fluent_tableview_header_style,
    sheet_list_card_layout_margins,
    sheet_list_hint_muted_colors,
)

from ..sheet_install import install_zip_to_acus, peek_root_readme_from_archive
from ..swan_sheet_client import (
    SWAN_SHEET_API_BASE_URL,
    SheetListEntry,
    download_sheet_archive,
    list_downloadable_sheets,
)
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import (
    fly_critical,
    fly_message,
    fly_warning,
    safe_dismiss_modal_progress_dialog,
    show_archive_readme_dialog,
)


def _readonly_item(text: str) -> QStandardItem:
    it = QStandardItem(text)
    it.setEditable(False)
    return it


class _FetchSheetsThread(QThread):
    ok = pyqtSignal(list)
    fail = pyqtSignal(str)
    phase = pyqtSignal(str)

    def __init__(self, base_url: str, parent=None) -> None:
        super().__init__(parent=parent)
        self._base = base_url

    def run(self) -> None:
        try:
            self.phase.emit("正在连接 SwanSite…")
            rows = list_downloadable_sheets(self._base)
            self.ok.emit(rows)
        except Exception as e:
            self.fail.emit(str(e))


class _DownloadSheetThread(QThread):
    """仅下载到临时文件；readme 弹窗与解压须在主线程顺序执行。"""

    ok = pyqtSignal(object)  # Path
    fail = pyqtSignal(str)
    phase = pyqtSignal(str)

    def __init__(self, base_url: str, content_id: int, parent=None) -> None:
        super().__init__(parent=parent)
        self._base = base_url
        self._cid = content_id

    def run(self) -> None:
        tmp: Path | None = None
        try:
            self.phase.emit("正在下载谱面包…")
            data = download_sheet_archive(self._base, self._cid)
            fd, path = tempfile.mkstemp(prefix="chuni_swan_")
            os.close(fd)
            tmp = Path(path)
            tmp.write_bytes(data)
            self.ok.emit(tmp)
        except Exception as e:
            if tmp is not None:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
            self.fail.emit(str(e))


class _InstallLocalArchiveThread(QThread):
    ok = pyqtSignal(str)
    fail = pyqtSignal(str)
    phase = pyqtSignal(str)

    def __init__(self, archive: Path, acus_root: Path, parent=None) -> None:
        super().__init__(parent=parent)
        self._archive = archive
        self._acus = acus_root

    def run(self) -> None:
        try:
            self.phase.emit("正在解压并写入 ACUS…")
            written = install_zip_to_acus(self._archive, self._acus)
            n = len(written)
            self.ok.emit(f"已写入 {n} 个文件到 ACUS。")
        except Exception as e:
            self.fail.emit(str(e))
        finally:
            try:
                self._archive.unlink(missing_ok=True)
            except OSError:
                pass


class SwanSheetDownloadDialog(FluentCaptionDialog):
    def __init__(self, *, acus_root: Path, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("SwanSite")
        self.setModal(True)
        self.resize(720, 520)
        self._acus_root = acus_root
        self._base_url = SWAN_SHEET_API_BASE_URL
        self._entries: list[SheetListEntry] = []
        self._fetch_thread: _FetchSheetsThread | None = None
        self._download_thread: _DownloadSheetThread | None = None
        self._install_thread: _InstallLocalArchiveThread | None = None
        self._progress_dialog: QProgressDialog | None = None

        card = CardWidget(self)

        hint = BodyLabel(
            "以下为站点上已配置下载包的自制谱列表。"
            "选择一行后点击「下载并解压到 ACUS」。若加载失败请检查网络或服务是否可用。"
        )
        hint.setWordWrap(True)
        sheet_list_hint_muted_colors(hint)

        self._model = QStandardItemModel(0, 3, self)
        self._model.setHorizontalHeaderLabels(["曲名", "作曲家", "备注"])

        self._table = TableView(self)
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        apply_fluent_tableview_header_style(self._table, object_name="SwanSheetTable")
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.doubleClicked.connect(lambda _idx: self._on_install())

        self._status = BodyLabel("点击「刷新列表」加载。", card)
        self._status.setWordWrap(True)

        cly = QVBoxLayout(card)
        sheet_list_card_layout_margins(cly)
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
        lay.setContentsMargins(*fluent_caption_content_margins())
        lay.setSpacing(12)
        lay.addWidget(card, stretch=1)
        lay.addLayout(btns)

        QTimer.singleShot(0, self._on_refresh)

    def _open_progress(self, title: str, text: str) -> QProgressDialog:
        dlg = QProgressDialog(self)
        dlg.setWindowTitle(title)
        dlg.setLabelText(text)
        dlg.setRange(0, 0)
        dlg.setCancelButton(None)
        dlg.setMinimumDuration(0)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.show()
        QApplication.processEvents()
        return dlg

    def _close_progress(self) -> None:
        if self._progress_dialog is not None:
            dlg = self._progress_dialog
            self._progress_dialog = None
            safe_dismiss_modal_progress_dialog(dlg)

    def _on_refresh(self) -> None:
        base = self._base_url
        if self._fetch_thread and self._fetch_thread.isRunning():
            return
        self._status.setText("正在加载列表…")
        self._model.removeRows(0, self._model.rowCount())
        self._entries.clear()
        self._close_progress()
        self._progress_dialog = self._open_progress("SwanSite", "正在获取铺面列表…")
        th = _FetchSheetsThread(base, parent=self)
        self._fetch_thread = th
        th.phase.connect(self._on_fetch_phase)
        th.ok.connect(self._on_fetch_ok)
        th.fail.connect(self._on_fetch_fail)
        th.finished.connect(lambda t=th: self._finalize_fetch_thread(t))
        th.start()

    def _on_fetch_phase(self, msg: str) -> None:
        if self._progress_dialog is not None:
            self._progress_dialog.setLabelText(msg)
            QApplication.processEvents()

    def _on_fetch_ok(self, rows: object) -> None:
        self._close_progress()
        try:
            if not isinstance(rows, list):
                self._status.setText("列表格式错误。")
                return
            self._entries = [r for r in rows if isinstance(r, SheetListEntry)]
            self._table.setSortingEnabled(False)
            try:
                self._model.removeRows(0, self._model.rowCount())
                for i, e in enumerate(self._entries):
                    self._model.insertRow(i)
                    c0 = _readonly_item(e.song_display())
                    c0.setData(e.content_id, Qt.ItemDataRole.UserRole)
                    c0.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                    self._model.setItem(i, 0, c0)
                    c1 = _readonly_item(e.artist_name)
                    c1.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                    self._model.setItem(i, 1, c1)
                    c2 = _readonly_item(e.summary)
                    c2.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                    self._model.setItem(i, 2, c2)
                self._status.setText(f"共 {len(self._entries)} 条可下载铺面。")
            finally:
                self._table.setSortingEnabled(True)
        except Exception as ex:
            self._status.setText("列表展示失败。")
            fly_critical(self, "铺面列表", str(ex))

    def _on_fetch_fail(self, msg: str) -> None:
        self._close_progress()
        self._status.setText("加载失败。")
        fly_critical(self, "无法获取铺面列表", msg)

    def _finalize_fetch_thread(self, th: _FetchSheetsThread) -> None:
        # 幂等兜底：正常在 _on_fetch_ok / _on_fetch_fail 开头已关；若信号顺序异常可避免进度条悬挂
        self._close_progress()
        if self._fetch_thread is th:
            self._fetch_thread = None
        # 推迟销毁，避免 finished 先于 ok 入队时 deleteLater 影响尚未投递的 ok 槽
        QTimer.singleShot(0, th.deleteLater)

    def _finalize_download_thread(self, th: _DownloadSheetThread) -> None:
        if self._download_thread is th:
            self._download_thread = None
        QTimer.singleShot(0, th.deleteLater)

    def _finalize_install_thread(self, th: _InstallLocalArchiveThread) -> None:
        self._close_progress()
        if self._install_thread is th:
            self._install_thread = None
        QTimer.singleShot(0, th.deleteLater)

    def _selected_entry(self) -> SheetListEntry | None:
        idx = self._table.currentIndex()
        if not idx.isValid():
            return None
        id_idx = self._model.index(idx.row(), 0)
        cid = self._model.data(id_idx, Qt.ItemDataRole.UserRole)
        try:
            icid = int(cid)
        except (TypeError, ValueError):
            return None
        for e in self._entries:
            if e.content_id == icid:
                return e
        return None

    def _on_install(self) -> None:
        e = self._selected_entry()
        if e is None:
            fly_warning(self, "未选择", "请先在表格中选择一条铺面。")
            return
        base = self._base_url
        if (self._download_thread and self._download_thread.isRunning()) or (
            self._install_thread and self._install_thread.isRunning()
        ):
            return
        self._status.setText(f"正在下载并安装：{e.song_display()} …")
        self._close_progress()
        self._progress_dialog = self._open_progress(
            "SwanSite",
            "正在下载谱面包…",
        )
        th = _DownloadSheetThread(base, e.content_id, parent=self)
        self._download_thread = th
        th.phase.connect(self._on_install_phase)
        th.ok.connect(self._on_download_ok)
        th.fail.connect(self._on_download_fail)
        th.finished.connect(lambda t=th: self._finalize_download_thread(t))
        th.start()

    def _on_install_phase(self, msg: str) -> None:
        if self._progress_dialog is not None:
            self._progress_dialog.setLabelText(msg)
            QApplication.processEvents()

    def _on_download_ok(self, tmp: object) -> None:
        if not isinstance(tmp, Path):
            self._close_progress()
            fly_critical(self, "下载失败", "内部错误：临时文件路径无效。")
            return
        self._close_progress()
        readme = peek_root_readme_from_archive(tmp)
        if readme is not None and readme.strip():
            show_archive_readme_dialog(self, readme)
        self._progress_dialog = self._open_progress(
            "SwanSite",
            "正在解压并写入 ACUS…",
        )
        ith = _InstallLocalArchiveThread(tmp, self._acus_root, parent=self)
        self._install_thread = ith
        ith.phase.connect(self._on_install_phase)
        ith.ok.connect(self._on_install_ok)
        ith.fail.connect(self._on_install_fail)
        ith.finished.connect(lambda t=ith: self._finalize_install_thread(t))
        ith.start()

    def _on_download_fail(self, msg: str) -> None:
        self._close_progress()
        self._status.setText("下载失败。")
        fly_critical(self, "下载失败", msg)

    def _on_install_ok(self, msg: str) -> None:
        self._close_progress()
        self._status.setText("安装完成。")
        fly_message(self, "完成", msg)

    def _on_install_fail(self, msg: str) -> None:
        self._close_progress()
        self._status.setText("安装失败。")
        fly_critical(self, "下载或解压失败", msg)
