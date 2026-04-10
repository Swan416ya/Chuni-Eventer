from __future__ import annotations

from pathlib import Path
import zipfile

from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QCheckBox,
    QComboBox,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from qfluentwidgets import BodyLabel, CardWidget, PrimaryPushButton, PushButton

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
    convert_pgko_chart_pick_to_c2s,
    convert_pgko_chart_pick_to_c2s_with_backend,
    install_pgko_pick_to_acus,
    PgkoChartPick,
    pick_pgko_chart_for_convert,
    read_pgko_meta_for_pick,
    suggest_next_pgko_music_id,
    PgkoInstallOptions,
)
from ..pgko_cs_bridge import explain_penguin_bridge_lookup, resolve_penguin_bridge
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


class _ReconvertLocalPgkoThread(QThread):
    ok = pyqtSignal(str)
    fail = pyqtSignal(str)

    def run(self) -> None:
        try:
            root = app_cache_dir() / "pgko_downloads"
            if not root.exists():
                self.ok.emit("未找到 .cache/pgko_downloads，跳过。")
                return
            mgxcs = sorted(p for p in root.glob("**/*.mgxc") if p.is_file())
            if not mgxcs:
                self.ok.emit("未找到本地 mgxc 文件。")
                return
            cs_ok = 0
            py_ok = 0
            errs: list[str] = []
            for p in mgxcs:
                try:
                    _out, backend = convert_pgko_chart_pick_to_c2s_with_backend(
                        PgkoChartPick(path=p, ext="mgxc")
                    )
                    if backend == "cs":
                        cs_ok += 1
                    else:
                        py_ok += 1
                except Exception as e:
                    errs.append(f"{p.name}: {type(e).__name__}: {e}")
            msg = f"重转完成：总计 {len(mgxcs)}，C#={cs_ok}，Python={py_ok}，失败={len(errs)}"
            if errs:
                msg += "\n\n失败样例：\n" + "\n".join(errs[:10])
            self.ok.emit(msg)
        except Exception as e:
            self.fail.emit(f"{type(e).__name__}: {e}")


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
            "加载 pgko.dev 可下载的 ugc/mgxc。双击行或点击下载保存到本地缓存。"
            "下载完成后可选择是否转码为 c2s（优先 mgxc）。"
            "暂不支持 ugc 直转；部分不含 mgxc 文件的谱面无法转化。"
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
        reconv = PushButton("重转本地 pgko_downloads", self)
        reconv.clicked.connect(self._on_reconvert_local)
        dl = PrimaryPushButton("下载选中项", self)
        dl.clicked.connect(self._on_download)
        close = PushButton("关闭", self)
        close.clicked.connect(self.reject)

        btns = QHBoxLayout()
        btns.addWidget(refresh)
        btns.addWidget(reconv)
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
        if self._thread_running_safe(self._download_thread):
            return
        self._status.setText(f"正在下载：{e.title} …")
        self._attach_download_thread(_DownloadPgkoThread(e, parent=self))

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
            self._try_convert_pgko_to_c2s(Path(output_path))
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

    def _on_reconvert_local(self) -> None:
        ans = QMessageBox.question(
            self,
            "重转本地缓存",
            "将扫描 .cache/pgko_downloads 下所有 mgxc 并重转为 c2s。\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._status.setText("正在重转本地 pgko_downloads…")
        th = _ReconvertLocalPgkoThread(parent=self)
        self._download_thread = th  # 复用下载线程槽位，避免重复启动下载
        th.ok.connect(self._on_reconvert_local_ok)
        th.fail.connect(self._on_reconvert_local_fail)
        th.finished.connect(th.deleteLater)
        th.start()

    def _on_reconvert_local_ok(self, msg: str) -> None:
        self._status.setText("本地重转完成。")
        fly_message(self, "重转结果", msg)

    def _on_reconvert_local_fail(self, msg: str) -> None:
        self._status.setText("本地重转失败。")
        fly_critical(self, "重转失败", msg)

    def _try_convert_pgko_to_c2s(self, output: Path) -> None:
        mgxc_list: list[Path] = []
        if output.is_dir():
            mgxc_list = sorted(p for p in output.glob("**/*.mgxc") if p.is_file())
        elif output.is_file() and output.suffix.lower() == ".mgxc":
            mgxc_list = [output]

        pick = pick_pgko_chart_for_convert(output)
        if not mgxc_list and pick is None:
            fly_warning(
                self,
                "未找到谱面文件",
                f"在以下位置未找到可用谱面：\n{output}\n\n"
                "说明：暂不支持 ugc 直转，需存在 mgxc 文件。",
            )
            return

        converted: list[tuple[Path, Path, str]] = []
        cs_ok = 0
        py_ok = 0
        errs: list[str] = []
        for mg in mgxc_list:
            try:
                out_i, backend_i = convert_pgko_chart_pick_to_c2s_with_backend(
                    PgkoChartPick(path=mg, ext="mgxc")
                )
                converted.append((mg, out_i, backend_i))
                if backend_i == "cs":
                    cs_ok += 1
                else:
                    py_ok += 1
            except Exception as e:
                errs.append(f"{mg.name}: {type(e).__name__}: {e}")

        out: Path | None = None
        backend: str = "python"
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
                if backend == "cs":
                    cs_ok += 1
                else:
                    py_ok += 1
        except NotImplementedError as e:
            if pick is not None:
                self._status.setText(
                    f"已选转码源：{pick.path.name}（{pick.ext}，优先级规则：mgxc > ugc）"
                )
            fly_warning(self, "暂不支持该格式", str(e))
            return
        except Exception as e:
            self._status.setText("转码失败。")
            fly_critical(self, "转码失败", f"{type(e).__name__}: {e}")
            return

        backend_tip = "C#(PenguinBridge)" if backend == "cs" else "Python(回退)"
        total_ok = cs_ok + py_ok
        self._status.setText(
            f"转码完成：{total_ok} 个（C#={cs_ok}, Python={py_ok}），主谱 {out.name}（{backend_tip}）"
        )
        if py_ok > 0:
            bridge = resolve_penguin_bridge()
            why = "未找到 PenguinBridge.exe" if bridge is None else f"PenguinBridge 调用失败：{bridge}"
            detail = explain_penguin_bridge_lookup() if bridge is None else ""
            fly_warning(
                self,
                "C# 转换未生效",
                f"本次已有 {py_ok} 个谱面回退到 Python 转换。\n原因：{why}\n\n{detail}".strip(),
            )
        if errs:
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
            fly_message(self, "转码完成", f"输出文件：\n{out}")
            return


class _PgkoInstallConfigDialog(QDialog):
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
        self.resize(560, 420)
        self._pick = pick
        self._meta = meta
        self._acus_root = acus_root
        self._tool_path = tool_path
        self._thread: _InstallPgkoThread | None = None

        suggest_id = suggest_next_pgko_music_id(acus_root, start=6000)
        self._id_edit = QLineEdit(self)
        self._id_edit.setPlaceholderText(f"留空自动分配（建议 {suggest_id}）")

        self._stage = QComboBox(self)
        idx = load_cached_game_index(expected_game_root=AcusConfig.load().game_root)
        pairs = merged_stage_pairs(acus_root, idx)
        if not pairs:
            pairs = [(-1, "Invalid")]
        for sid, sname in pairs:
            self._stage.addItem(f"{sid} | {sname}", (int(sid), str(sname)))

        diff = int(meta.get("difficulty") or 3)
        need_ev = diff in (4, 5)
        self._ev = QCheckBox("自动生成解禁事件（ULT/WE）", self)
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
        root.addWidget(hint)
        root.addLayout(form)
        self._status = BodyLabel("", self)
        self._status.setWordWrap(True)
        self._status.hide()
        root.addWidget(self._status)
        root.addLayout(row)

    def _run_install(self) -> None:
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

        def _done() -> None:
            th = self._thread
            self._thread = None
            self._ok_btn.setEnabled(True)
            if th is not None:
                th.deleteLater()

        self._thread.finished.connect(_done)
        self._thread.start()

    def _on_install_fail(self, msg: str) -> None:
        self._status.hide()
        fly_critical(self, "导入失败", msg)

    def _on_install_ok(self, ret: object) -> None:
        if not isinstance(ret, dict):
            fly_critical(self, "导入失败", "返回结果格式错误")
            return
        fly_message(
            self,
            "导入完成",
            f"musicId: {ret.get('musicId')}\n"
            f"slots: {ret.get('slots')}\n"
            f"Music.xml: {ret.get('musicXml')}\n"
            f"cue: {ret.get('cueDir')}\n"
            f"event: {ret.get('eventId')}",
        )
        self.accept()

