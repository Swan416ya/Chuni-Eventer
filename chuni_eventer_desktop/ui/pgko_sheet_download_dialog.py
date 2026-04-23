from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import logging
import os
import zipfile

from PyQt6.QtCore import QThread, QUrl, pyqtSignal, Qt
from PyQt6.QtGui import QBrush, QColor, QDesktopServices, QEnterEvent, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    CheckBox,
    ComboBox as FluentComboBox,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    isDarkTheme,
)

from ..acus_workspace import AcusConfig, acus_root_dir, app_cache_dir, resolve_compressonatorcli_path
from ..game_data_index import load_cached_game_index, merged_stage_pairs
from ..pgko_sheet_client import (
    PGKO_BASE_URL,
    PgkoSheetPage,
    PgkoSheetEntry,
    download_pgko_sheet,
    fetch_pgko_sheet_page,
    resolve_pgko_download_from_bundle,
)
from ..pgko_to_c2s import (
    convert_pgko_audio_to_chuni_from_pick,
    convert_pgko_chart_pick_to_c2s_with_backend,
    install_pgko_pick_to_acus,
    PgkoChartPick,
    pick_pgko_chart_for_convert,
    read_pgko_meta_for_pick,
    suggest_next_pgko_music_id,
    PgkoInstallOptions,
)
from ..penguin_tools_cli import explain_penguin_tools_cli_lookup, resolve_penguin_tools_cli
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import (
    fly_critical,
    fly_message_async,
    fly_question_async,
    fly_warning,
)
from .fluent_table import (
    apply_fluent_sheet_table,
    mark_sheet_item_readonly,
    sheet_list_card_layout_margins,
    sheet_list_hint_muted_colors,
)

_PGKO_TABLE_COL_DETAIL = 2
_PGKO_DETAIL_URL_ROLE = Qt.ItemDataRole.UserRole + 11
log = logging.getLogger(__name__)


def _pgko_debug_enabled() -> bool:
    return os.getenv("CHUNI_DIALOG_DEBUG", "").strip() in {"1", "true", "TRUE", "yes", "YES"}


def _w_short(w: QWidget | None) -> str:
    if w is None:
        return "None"
    try:
        nm = (w.objectName() or "").strip() or "-"
        return f"{type(w).__name__}[{nm}](vis={w.isVisible()},en={w.isEnabled()},win={w.isWindow()})"
    except Exception:
        return f"{type(w).__name__}[?]"


def _pgko_dlog(tag: str, **kv: object) -> None:
    if not _pgko_debug_enabled():
        return
    try:
        active_modal = QApplication.activeModalWidget()
        active_popup = QApplication.activePopupWidget()
        focus = QApplication.focusWidget()
        payload = ", ".join(f"{k}={v!r}" for k, v in kv.items())
        log.warning(
            "[pgko-debug] %s %s | active_modal=%s active_popup=%s focus=%s",
            tag,
            payload,
            _w_short(active_modal),
            _w_short(active_popup),
            _w_short(focus),
        )
    except Exception:
        log.exception("[pgko-debug] failed to log tag=%s", tag)


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


class _InstallPgkoThread(QThread):
    ok = pyqtSignal(object)
    fail = pyqtSignal(str)

    def __init__(
        self,
        *,
        pick: PgkoChartPick,
        acus_root: Path,
        tool_path: Path | None,
        opts: PgkoInstallOptions,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self._pick = pick
        self._acus_root = acus_root
        self._tool_path = tool_path
        self._opts = opts

    def run(self) -> None:
        try:
            ret = install_pgko_pick_to_acus(
                pick=self._pick,
                acus_root=self._acus_root,
                tool_path=self._tool_path,
                opts=self._opts,
            )
            self.ok.emit(ret)
        except Exception as e:
            self.fail.emit(f"{type(e).__name__}: {e}")


def _margrete_ugc_help_image_path() -> Path:
    return Path(__file__).resolve().parents[1] / "static" / "help" / "margrete_input_ugc.jpg"


def _enumerate_pgko_cache_bundle_dirs(cache_root: Path) -> list[Path]:
    """列出 `pgko_downloads` 下「含有任意 .mgxc 或 .ugc」的顶层目录。"""
    if not cache_root.is_dir():
        return []
    out: list[Path] = []
    if any(cache_root.glob("*.mgxc")) or any(cache_root.glob("*.ugc")):
        out.append(cache_root)
    for p in sorted(cache_root.iterdir(), key=lambda x: x.name.lower()):
        if p.is_dir() and (any(p.glob("**/*.mgxc")) or any(p.glob("**/*.ugc"))):
            out.append(p)
    # 去重并保持顺序
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


class _MargreteScreenshotHover(QWidget):
    """默认只显示提示语；鼠标悬停在本区域时展开 Margrete 菜单截图。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._hint = QLabel("鼠标移到这里查看演示截图", self)
        self._hint.setStyleSheet(
            "color:#1565c0;text-decoration:underline;padding-bottom:4px;"
        )
        self._hint.setWordWrap(True)
        self._hint.setCursor(Qt.CursorShape.PointingHandCursor)

        self._img = QLabel(self)
        self._img.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        pm = QPixmap(str(_margrete_ugc_help_image_path()))
        if pm.isNull():
            self._img.setText("（演示图缺失）")
        else:
            max_w = 640
            if pm.width() > max_w:
                pm = pm.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
            self._img.setPixmap(pm)
        self._img.hide()

        lay.addWidget(self._hint)
        lay.addWidget(self._img)

    def enterEvent(self, event: QEnterEvent) -> None:
        self._img.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._img.hide()
        super().leaveEvent(event)


class _PgkoUgcGuideDialog(FluentCaptionDialog):
    """
    UGC 无法直转时的引导：Margrete 手工转 mgxc + 浏览本地 pgko_downloads 缓存中的 mgxc 包。
    """

    def __init__(
        self,
        *,
        on_open_bundle: Callable[[Path], None],
        on_try_experimental_ugc: Callable[[Path], None],
        experimental_enabled: bool,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("UGC → mgxc 与本地缓存谱面")
        self.setModal(True)
        self.resize(800, 660)
        self._on_open_bundle = on_open_bundle
        self._on_try_experimental_ugc = on_try_experimental_ugc
        self._experimental_enabled = experimental_enabled

        help_panel = QWidget(self)
        hp = QVBoxLayout(help_panel)
        hp.setContentsMargins(0, 0, 0, 0)
        hp.setSpacing(8)

        title = QLabel("如何将下载的 UGC 转为 mgxc", help_panel)
        title.setStyleSheet("font-size:15pt;font-weight:700;color:#b71c1c;")

        step1 = QLabel(help_panel)
        step1.setOpenExternalLinks(True)
        step1.setWordWrap(True)
        step1.setTextFormat(Qt.TextFormat.RichText)
        step1.setText(
            "1. 在 "
            "<a href=\"https://umgr.inonote.jp/en/docs/releases\">UMIGURI 官方下载页（Margrete）</a> "
            "下载并安装 <b>Margrete</b> 制谱器（版本以官网为准，例如 v1.8.0）。"
        )

        step2 = QLabel(
            "2. 打开 Margrete，在菜单栏选择「ファイル」→「他形式譜面取り込み…」，从本机选择要导入的 UGC 文件。",
            help_panel,
        )
        step2.setWordWrap(True)

        shot_hover = _MargreteScreenshotHover(help_panel)

        step3 = QLabel(help_panel)
        step3.setTextFormat(Qt.TextFormat.RichText)
        step3.setWordWrap(True)
        step3.setText(
            "3. 使用快捷键 <b>Ctrl+Shift+S</b> 将谱面另存为 <b>mgxc</b>，"
            "保存到与原始 <b>ugc</b> 相同的文件夹（便于本工具与音频、封面等资源同目录识别）。"
        )

        hp.addWidget(title)
        hp.addWidget(step1)
        hp.addWidget(step2)
        hp.addWidget(shot_hover)
        hp.addWidget(step3)

        hint_below = BodyLabel(
            "下方列表来自本应用缓存目录下的 pgko_downloads（与线上下载解压位置一致）。"
            "显示含有 .mgxc 或 .ugc 的文件夹；双击一行仍按默认规则（mgxc 优先）处理。"
        )
        hint_below.setWordWrap(True)
        sheet_list_hint_muted_colors(hint_below)

        self._table = QTableWidget(0, 6, self)
        apply_fluent_sheet_table(self._table)
        self._table.setHorizontalHeaderLabels(
            ["缓存文件夹", "曲名（元数据）", "艺术家", "谱师", "mgxc 数", "ugc 数"]
        )
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self._table.itemDoubleClicked.connect(self._on_row_activated)

        refresh = PushButton("刷新列表", self)
        refresh.clicked.connect(self._reload_table)
        exp = PrimaryPushButton("实验性：仅用 UGC 直转 c2s", self)
        exp.clicked.connect(self._on_experimental_convert)
        exp.setEnabled(self._experimental_enabled)
        if not self._experimental_enabled:
            exp.setToolTip("已在设置中关闭。可在“设置 -> PGKO UGC 直转 c2s（实验）”中启用。")
        close = PushButton("关闭", self)
        close.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(refresh)
        row.addWidget(exp)
        row.addStretch(1)
        row.addWidget(close)

        root = QVBoxLayout(self)
        root.setContentsMargins(*fluent_caption_content_margins())
        root.setSpacing(10)
        root.addWidget(help_panel)
        root.addWidget(hint_below)
        root.addWidget(self._table, stretch=1)
        root.addLayout(row)

        self._reload_table()

    def _reload_table(self) -> None:
        self._table.setRowCount(0)
        root = app_cache_dir() / "pgko_downloads"
        bundles = _enumerate_pgko_cache_bundle_dirs(root)
        for bundle in bundles:
            mgxcs = sorted(bundle.glob("**/*.mgxc")) if bundle.is_dir() else []
            ugcs = sorted(bundle.glob("**/*.ugc")) if bundle.is_dir() else []
            pick = pick_pgko_chart_for_convert(bundle)
            title = artist = designer = "—"
            n_mg = len(mgxcs)
            n_ug = len(ugcs)
            if pick is not None:
                try:
                    meta = read_pgko_meta_for_pick(pick)
                    title = str(meta.get("title") or "—").strip() or "—"
                    artist = str(meta.get("artist") or "—").strip() or "—"
                    designer = str(meta.get("designer") or "—").strip() or "—"
                except Exception:
                    pass
            r = self._table.rowCount()
            self._table.insertRow(r)
            folder_disp = bundle.name if bundle != root else "（pgko_downloads 根目录）"
            it0 = QTableWidgetItem(folder_disp)
            it0.setData(Qt.ItemDataRole.UserRole, str(bundle.resolve()))
            mark_sheet_item_readonly(it0)
            self._table.setItem(r, 0, it0)
            for col, txt in (
                (1, title),
                (2, artist),
                (3, designer),
                (4, str(n_mg)),
                (5, str(n_ug)),
            ):
                itc = QTableWidgetItem(txt)
                mark_sheet_item_readonly(itc)
                self._table.setItem(r, col, itc)

    def _on_row_activated(self, _index=None) -> None:
        r = self._table.currentRow()
        if r < 0:
            return
        it = self._table.item(r, 0)
        if it is None:
            return
        raw = it.data(Qt.ItemDataRole.UserRole)
        if not raw:
            return
        folder = Path(str(raw))
        if not folder.is_dir():
            fly_warning(self, "路径无效", f"不是有效文件夹：\n{folder}")
            return
        self.accept()
        self._on_open_bundle(folder)

    def _on_experimental_convert(self) -> None:
        if not self._experimental_enabled:
            fly_warning(self, "已禁用", "该实验功能已在设置中关闭。")
            return
        r = self._table.currentRow()
        if r < 0:
            fly_warning(self, "未选择", "请先在列表中选择一个缓存文件夹。")
            return
        it = self._table.item(r, 0)
        if it is None:
            return
        raw = it.data(Qt.ItemDataRole.UserRole)
        if not raw:
            return
        folder = Path(str(raw))
        if not folder.is_dir():
            fly_warning(self, "路径无效", f"不是有效文件夹：\n{folder}")
            return
        def _on_continue(ok: bool) -> None:
            if not ok:
                return
            self.accept()
            self._on_try_experimental_ugc(folder)

        fly_question_async(
            self,
            "实验性功能提示",
            "将尝试“仅使用 UGC”直转 c2s（不走 mgxc 回退）。\n"
            "该功能仍在实验阶段，可能失败或结果与官方差异较大。\n\n"
            "是否继续？",
            on_result=_on_continue,
            yes_text="继续",
            no_text="取消",
            window_modal=True,
        )


class PgkoSheetDownloadDialog(FluentCaptionDialog):
    def __init__(self, *, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("从 pgko.dev 下载谱面")
        self.setModal(True)
        self.resize(780, 560)

        self._entries: list[PgkoSheetEntry] = []
        self._fetch_thread: _FetchPgkoThread | None = None
        self._download_thread: _DownloadPgkoThread | None = None
        self._next_cursor: str | None = None
        self._is_fetching_more = False
        self._seen_bundle_ids: set[str] = set()

        credit = QLabel(self)
        credit.setTextFormat(Qt.TextFormat.RichText)
        credit.setOpenExternalLinks(True)
        credit.setText(
            '<p style="margin:0;line-height:1.5;">'
            '<span style="color:#c62828;font-weight:700;">※</span> '
            "<b>pgko.dev</b> 列表数据与 <b>mgxc → c2s</b> 转谱逻辑均参考作者 "
            '<a href="https://github.com/Foahh" style="color:#1565c0;font-weight:600;text-decoration:none;">Foahh</a> '
            "的开源项目（如 PenguinTools）。"
            "</p>"
        )
        credit.setWordWrap(True)

        card = CardWidget(self)
        hint = BodyLabel(
            "加载 pgko.dev 可下载条目。双击行或点「下载选中项」解压到本地缓存，并可转 c2s（需包内存在 mgxc）。"
            "若只有 UGC，请点「UGC → mgxc…」查看用 Margrete 手工导出 mgxc 的步骤，并浏览已缓存的 mgxc 包。"
        )
        hint.setWordWrap(True)
        sheet_list_hint_muted_colors(hint)

        self._table = QTableWidget(0, 3, self)
        apply_fluent_sheet_table(self._table)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.setHorizontalHeaderLabels(["标题", "艺术家", "详情"])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hh.resizeSection(1, 260)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._table.itemDoubleClicked.connect(lambda _it: self._on_download())
        self._table.cellClicked.connect(self._on_pgko_table_cell_clicked)
        self._table.verticalScrollBar().valueChanged.connect(self._on_scroll_value_changed)

        self._status = BodyLabel("点击“刷新列表”加载。")
        self._status.setWordWrap(True)

        cly = QVBoxLayout(card)
        sheet_list_card_layout_margins(cly)
        cly.addWidget(hint)
        cly.addWidget(self._table, stretch=1)
        cly.addWidget(self._status)

        refresh = PushButton("刷新列表", self)
        refresh.clicked.connect(self._on_refresh)
        ugc = PushButton("UGC → mgxc 说明 / 本地缓存", self)
        ugc.clicked.connect(self._on_ugc_guide)
        dl = PrimaryPushButton("下载选中项", self)
        dl.clicked.connect(self._on_download)
        close = PushButton("关闭", self)
        close.clicked.connect(self.reject)

        btns = QHBoxLayout()
        btns.addWidget(refresh)
        btns.addWidget(ugc)
        btns.addStretch(1)
        btns.addWidget(dl)
        btns.addWidget(close)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*fluent_caption_content_margins())
        lay.setSpacing(12)
        lay.addWidget(credit)
        lay.addWidget(card, stretch=1)
        lay.addLayout(btns)

        self._on_refresh()

    def _on_pgko_table_cell_clicked(self, row: int, col: int) -> None:
        if col != _PGKO_TABLE_COL_DETAIL or row < 0:
            return
        it = self._table.item(row, col)
        if it is None:
            return
        raw = it.data(_PGKO_DETAIL_URL_ROLE)
        if not isinstance(raw, str) or not raw.strip():
            return
        u = QUrl(raw.strip())
        if u.isValid() and u.scheme() in ("http", "https"):
            QDesktopServices.openUrl(u)

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

    def _attach_download_thread(self, th: _DownloadPgkoThread) -> None:
        self._download_thread = th
        th.resolved.connect(self._on_download_resolved)
        th.ok.connect(self._on_download_ok)
        th.fail.connect(self._on_download_fail)

        def _on_finished() -> None:
            # 先清空引用，再 deleteLater，避免后续访问已释放对象
            if self._download_thread is th:
                self._download_thread = None
            th.deleteLater()

        th.finished.connect(_on_finished)
        th.start()

    def _on_ugc_guide(self) -> None:
        cfg = AcusConfig.load()
        _PgkoUgcGuideDialog(
            on_open_bundle=self._try_convert_pgko_to_c2s,
            on_try_experimental_ugc=self._try_convert_pgko_ugc_experimental,
            experimental_enabled=bool(getattr(cfg, "enable_pgko_ugc_experimental", False)),
            parent=self,
        ).exec()

    def _try_convert_pgko_ugc_experimental(self, output: Path) -> None:
        cfg = AcusConfig.load()
        if not bool(getattr(cfg, "enable_pgko_ugc_experimental", False)):
            fly_warning(self, "已禁用", "实验性 UGC 直转已在设置中关闭。")
            return
        ugc_list: list[Path] = []
        if output.is_dir():
            ugc_list = sorted(p for p in output.glob("**/*.ugc") if p.is_file())
        elif output.is_file() and output.suffix.lower() == ".ugc":
            ugc_list = [output]
        if not ugc_list:
            fly_warning(
                self,
                "未找到 UGC",
                f"在以下位置未找到可用于实验性转换的 UGC 文件：\n{output}",
            )
            return
        src = ugc_list[0]
        self._status.setText(f"实验性 UGC 转换中：{src.name} ...")
        try:
            out, backend = convert_pgko_chart_pick_to_c2s_with_backend(
                PgkoChartPick(path=src, ext="ugc"),
                allow_ugc_experimental=True,
            )
        except Exception as e:
            self._status.setText("实验性 UGC 转换失败。")
            fly_critical(
                self,
                "实验性 UGC 转换失败",
                f"{type(e).__name__}: {e}",
            )
            return
        self._status.setText(f"实验性 UGC 转换完成：{out.name}（{backend}）")
        fly_message_async(
            self,
            "实验性 UGC 转换完成",
            f"输入：{src}\n输出：{out}\n后端：{backend}\n\n"
            "提示：该结果为实验性输出，不保证可用性与一致性。",
            single_button=True,
            window_modal=False,
        )

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
            t0 = QTableWidgetItem(e.title)
            mark_sheet_item_readonly(t0)
            self._table.setItem(r, 0, t0)
            t1 = QTableWidgetItem(e.artist)
            mark_sheet_item_readonly(t1)
            self._table.setItem(r, 1, t1)
            t2 = QTableWidgetItem("查看")
            t2.setData(_PGKO_DETAIL_URL_ROLE, e.detail_url)
            t2.setToolTip(e.detail_url)
            link_c = "#64B5F6" if isDarkTheme() else "#1565C0"
            t2.setForeground(QBrush(QColor(link_c)))
            mark_sheet_item_readonly(t2)
            self._table.setItem(r, 2, t2)
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
        fly_message_async(
            self,
            "读取 pgko.dev 失败",
            msg,
            single_button=True,
            window_modal=False,
        )

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
        if self._thread_running_safe(self._download_thread):
            return
        self._status.setText(f"正在下载：{e.title} …")
        self._attach_download_thread(_DownloadPgkoThread(e, parent=self))

    def _on_download_resolved(self, text: str) -> None:
        # 直接输出解析到的下载链接，便于用户复制调试
        self._status.setText(f"已解析下载链接：\n{text}")

    def _on_download_ok(self, output_path: str, ext: str, extracted_zip: bool) -> None:
        _pgko_dlog(
            "_on_download_ok:enter",
            output_path=output_path,
            ext=ext,
            extracted_zip=extracted_zip,
        )
        self._status.setText("下载完成。")
        if extracted_zip:
            target_tip = f"已解压到目录：\n{output_path}"
        else:
            target_tip = f"返回体非 zip，已按原始文件保存：\n{output_path}"

        def _on_convert_choice(ok: bool) -> None:
            _pgko_dlog("_on_download_ok:convert_choice", ok=ok, output_path=output_path)
            if ok:
                self._try_convert_pgko_to_c2s(Path(output_path))
                return
            fly_message_async(
                self,
                "已下载",
                target_tip,
                single_button=True,
                window_modal=False,
            )

        fly_question_async(
            self,
            "下载完成",
            f"{target_tip}\n\n是否尝试转码为中二 c2s？",
            on_result=_on_convert_choice,
            yes_text="是",
            no_text="否",
            window_modal=True,
        )
        _pgko_dlog("_on_download_ok:question_shown", output_path=output_path)

    def _on_download_fail(self, msg: str) -> None:
        _pgko_dlog("_on_download_fail", msg=msg[:220])
        self._status.setText(
            "下载失败。\n\n"
            "调试信息（复制给开发者）：\n"
            f"{msg}"
        )

    def _try_convert_pgko_to_c2s(self, output: Path) -> None:
        _pgko_dlog("_try_convert_pgko_to_c2s:start", output=str(output))
        mgxc_list: list[Path] = []
        if output.is_dir():
            mgxc_list = sorted(p for p in output.glob("**/*.mgxc") if p.is_file())
        elif output.is_file() and output.suffix.lower() == ".mgxc":
            mgxc_list = [output]

        pick = pick_pgko_chart_for_convert(output)
        if not mgxc_list and pick is None:
            _pgko_dlog("_try_convert_pgko_to_c2s:no_source", output=str(output))
            fly_warning(
                self,
                "未找到谱面文件",
                f"在以下位置未找到可用谱面：\n{output}\n\n"
                "说明：暂不支持 ugc 直转，需存在 mgxc 文件。",
            )
            return

        converted: list[tuple[Path, Path, str]] = []
        cli_ok = 0
        errs: list[str] = []
        for mg in mgxc_list:
            try:
                out_i, backend_i = convert_pgko_chart_pick_to_c2s_with_backend(
                    PgkoChartPick(path=mg, ext="mgxc")
                )
                converted.append((mg, out_i, backend_i))
                if backend_i == "cli":
                    cli_ok += 1
            except Exception as e:
                errs.append(f"{mg.name}: {type(e).__name__}: {e}")
                _pgko_dlog("_try_convert_pgko_to_c2s:mgxc_fail", mg=str(mg), err=f"{type(e).__name__}: {e}")

        out: Path | None = None
        backend: str = "cli"
        if converted:
            if pick is not None:
                for src_i, out_i, backend_i in converted:
                    if src_i.resolve() == pick.path.resolve():
                        out, backend = out_i, backend_i
                        break
            if out is None:
                _src0, out, backend = converted[0]

        try:
            if out is None:
                if pick is None:
                    raise RuntimeError("未找到可转换的 mgxc 文件")
                out, backend = convert_pgko_chart_pick_to_c2s_with_backend(pick)
                if backend == "cli":
                    cli_ok += 1
        except NotImplementedError as e:
            if pick is not None:
                self._status.setText(
                    f"已选转码源：{pick.path.name}（{pick.ext}，优先级规则：mgxc > ugc）"
                )
            fly_warning(self, "暂不支持该格式", str(e))
            return
        except Exception as e:
            self._status.setText("转码失败。")
            _pgko_dlog("_try_convert_pgko_to_c2s:hard_fail", err=f"{type(e).__name__}: {e}")
            self._status.setText(
                "转码失败。\n\n"
                f"{type(e).__name__}: {e}"
            )
            return

        backend_tip = "PenguinTools.CLI" if backend == "cli" else backend
        total_ok = cli_ok
        self._status.setText(
            f"转码完成：{total_ok} 个（CLI={cli_ok}），主谱 {out.name}（{backend_tip}）"
        )
        if total_ok == 0:
            cli = resolve_penguin_tools_cli()
            why = "未找到 PenguinTools.CLI" if cli is None else f"PenguinTools.CLI 调用失败：{cli}"
            detail = explain_penguin_tools_cli_lookup() if cli is None else ""
            fly_warning(
                self,
                "CLI 转换未生效",
                f"本次没有任何谱面成功走 PenguinTools.CLI。\n原因：{why}\n\n{detail}".strip(),
            )
        if errs:
            _pgko_dlog("_try_convert_pgko_to_c2s:partial_fail", fail_count=len(errs))
            fly_warning(
                self,
                "部分谱面转换失败",
                "以下谱面未成功转换（最多显示 10 条）：\n" + "\n".join(errs[:10]),
            )
        try:
            if pick is None:
                if converted:
                    pick = PgkoChartPick(path=converted[0][0], ext="mgxc")
                else:
                    raise RuntimeError("缺少用于读取元数据的谱面源")
            meta = read_pgko_meta_for_pick(pick)
        except Exception as e:
            _pgko_dlog("_try_convert_pgko_to_c2s:meta_fail", err=f"{type(e).__name__}: {e}")
            fly_warning(self, "读取元数据失败", f"{type(e).__name__}: {e}")
            return
        cfg = AcusConfig.load()
        tool = resolve_compressonatorcli_path(cfg)
        dlg = _PgkoInstallConfigDialog(
            pick=pick,
            meta=meta,
            acus_root=acus_root_dir(),
            tool_path=tool,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            _pgko_dlog("_try_convert_pgko_to_c2s:install_cancel", out=str(out))
            fly_message_async(
                self,
                "转码完成",
                f"输出文件：\n{out}",
                single_button=True,
                window_modal=False,
            )
            return


class _PgkoInstallConfigDialog(FluentCaptionDialog):
    def __init__(
        self,
        *,
        pick: PgkoChartPick,
        meta: dict[str, object],
        acus_root: Path,
        tool_path: Path | None,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("导入 pgko 到 ACUS")
        self.setModal(True)
        self.resize(580, 460)
        self._pick = pick
        self._meta = meta
        self._acus_root = acus_root
        self._tool_path = tool_path
        self._thread: _InstallPgkoThread | None = None

        suggest_id = suggest_next_pgko_music_id(acus_root, start=6000)
        self._id_edit = LineEdit(self)
        self._id_edit.setPlaceholderText(f"留空自动分配（建议 {suggest_id}）")

        self._stage = FluentComboBox(self)
        idx = load_cached_game_index(expected_game_root=AcusConfig.load().game_root)
        pairs = merged_stage_pairs(acus_root, idx)
        if not pairs:
            pairs = [(-1, "Invalid")]
        for sid, sname in pairs:
            self._stage.addItem(f"{sid} | {sname}", None, (int(sid), str(sname)))

        diff = int(meta.get("difficulty") or 3)
        need_ev = diff in (4, 5)
        self._ev = CheckBox("自动生成解禁事件（ULT/WE）", self)
        self._ev.setChecked(need_ev)
        self._ev.setVisible(need_ev)

        form = QFormLayout()
        form.addRow("乐曲ID", self._id_edit)
        form.addRow("Stage", self._stage)
        form.addRow("", self._ev)

        hint = BodyLabel(
            f"曲名: {meta.get('title') or ''}\n"
            f"作者: {meta.get('artist') or meta.get('designer') or ''}\n"
            f"难度标识: {diff}（4=WE, 5=ULT）\n"
            "定数将按包内各 mgxc 的 cnst 自动写入，不允许手填。"
        )
        hint.setWordWrap(True)

        ok = PrimaryPushButton("开始导入", self)
        ok.clicked.connect(self._run_install)
        self._ok_btn = ok
        cancel = PushButton("取消", self)
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)

        root = QVBoxLayout(self)
        root.setContentsMargins(*fluent_caption_content_margins())
        root.setSpacing(12)
        root.addWidget(hint)
        root.addLayout(form)
        self._status = BodyLabel("", self)
        self._status.setWordWrap(True)
        self._status.hide()
        root.addWidget(self._status)
        root.addStretch(1)
        root.addLayout(row)

    def _run_install(self) -> None:
        _pgko_dlog("_run_install:start", pick=str(self._pick.path), ext=self._pick.ext)
        txt = self._id_edit.text().strip()
        if txt:
            try:
                mid = int(txt)
            except ValueError:
                fly_warning(self, "ID无效", "乐曲ID必须是整数，或留空自动分配。")
                return
        else:
            mid = suggest_next_pgko_music_id(self._acus_root, start=6000)

        data = self._stage.currentData()
        stage_id, stage_str = int(data[0]), str(data[1])
        opts = PgkoInstallOptions(
            music_id=mid,
            stage_id=stage_id,
            stage_str=stage_str,
            create_unlock_event=self._ev.isChecked() if self._ev.isVisible() else False,
        )
        if self._thread is not None:
            return
        self._status.setText("正在导入（谱面/音频/事件），请稍候…")
        self._status.show()
        self._ok_btn.setEnabled(False)
        self._thread = _InstallPgkoThread(
            pick=self._pick,
            acus_root=self._acus_root,
            tool_path=self._tool_path,
            opts=opts,
            parent=self,
        )
        self._thread.ok.connect(self._on_install_ok)
        self._thread.fail.connect(self._on_install_fail)
        _pgko_dlog("_run_install:thread_started", music_id=opts.music_id, stage_id=opts.stage_id)

        def _done() -> None:
            th = self._thread
            self._thread = None
            self._ok_btn.setEnabled(True)
            if th is not None:
                th.deleteLater()

        self._thread.finished.connect(_done)
        self._thread.start()

    def _on_install_fail(self, msg: str) -> None:
        _pgko_dlog("_on_install_fail", msg=msg[:220])
        self._status.setText(f"导入失败：{msg}")
        self._status.show()

    def _on_install_ok(self, ret: object) -> None:
        _pgko_dlog("_on_install_ok:enter", ret_type=type(ret).__name__)
        if not isinstance(ret, dict):
            self._status.hide()
            self._status.setText("导入失败：返回结果格式错误")
            self._status.show()
            return
        host = self.window()
        _pgko_dlog("_on_install_ok:accept_before", host=_w_short(host))
        self.accept()
        _pgko_dlog("_on_install_ok:accept_after")
        fly_message_async(
            host,
            "导入完成",
            f"musicId: {ret.get('musicId')}\n"
            f"slots: {ret.get('slots')}\n"
            f"Music.xml: {ret.get('musicXml')}\n"
            f"cue: {ret.get('cueDir')}\n"
            f"event: {ret.get('eventId')}",
            single_button=True,
            window_modal=False,
        )
