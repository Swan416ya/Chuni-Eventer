from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import tempfile

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from qfluentwidgets import BodyLabel, CardWidget, PrimaryPushButton, PushButton

from ..acus_workspace import AcusConfig, app_cache_dir
from ..acus_scan import MusicItem
from ..backend_upload_client import (
    download_backend_song_file,
    list_backend_songs,
    upload_to_backend,
)
from ..github_sheet_client import (
    GithubChartEntry,
    download_github_chart_bytes,
    _split_repo,
    list_github_chart_files,
    upload_file_to_github_charts,
)
from ..sheet_install import install_zip_to_acus
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical, fly_message, fly_question, fly_warning
from .fluent_table import apply_fluent_sheet_table


def _human_size(n: int) -> str:
    x = float(max(0, n))
    for unit in ("B", "KB", "MB", "GB"):
        if x < 1024.0 or unit == "GB":
            if unit == "B":
                return f"{int(x)} {unit}"
            return f"{x:.1f} {unit}"
        x /= 1024.0
    return f"{int(n)} B"


class _ListGithubThread(QThread):
    ok = pyqtSignal(object)
    fail = pyqtSignal(str)

    def __init__(self, *, repo: str, branch: str, token: str, parent=None) -> None:
        super().__init__(parent=parent)
        self._repo = repo
        self._branch = branch
        self._token = token

    def run(self) -> None:
        try:
            rows = list_github_chart_files(
                repo=self._repo,
                branch=self._branch,
                prefix="charts",
                token=self._token or None,
            )
            self.ok.emit(rows)
        except Exception as e:
            self.fail.emit(str(e))


class _DownloadGithubThread(QThread):
    ok = pyqtSignal(str)
    fail = pyqtSignal(str)

    def __init__(self, *, repo: str, branch: str, file_path: str, parent=None) -> None:
        super().__init__(parent=parent)
        self._repo = repo
        self._branch = branch
        self._path = file_path

    def run(self) -> None:
        try:
            data = download_github_chart_bytes(repo=self._repo, branch=self._branch, file_path=self._path)
            out_dir = app_cache_dir() / "github_charts"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / Path(self._path).name
            out_path.write_bytes(data)
            self.ok.emit(str(out_path))
        except Exception as e:
            self.fail.emit(str(e))


class _UploadGithubThread(QThread):
    ok = pyqtSignal(int)
    fail = pyqtSignal(str)

    def __init__(self, *, repo: str, branch: str, token: str, local_files: list[Path], parent=None) -> None:
        super().__init__(parent=parent)
        self._repo = repo
        self._branch = branch
        self._token = token
        self._files = local_files

    def run(self) -> None:
        try:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            count = 0
            for p in self._files:
                target = f"charts/uploads/{stamp}/{p.name}"
                upload_file_to_github_charts(
                    repo=self._repo,
                    branch=self._branch,
                    target_path=target,
                    local_file=p,
                    token=self._token,
                    message=f"chore(charts): upload {p.name}",
                )
                count += 1
            self.ok.emit(count)
        except Exception as e:
            self.fail.emit(str(e))


class GithubSheetDialog(FluentCaptionDialog):
    def __init__(self, *, acus_root: Path, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("GitHub Charts 社区谱面")
        self.setModal(True)
        self.resize(780, 560)
        self._acus_root = acus_root

        cfg = AcusConfig.load()
        self._backend_api = (getattr(cfg, "uploader_api_base", "") or "").strip()
        self._repo = (cfg.github_charts_repo or "").strip()
        self._branch = (cfg.github_charts_branch or "charts").strip() or "charts"
        self._token = (cfg.github_charts_token or "").strip()

        self._rows: list[GithubChartEntry] = []
        self._song_rows: list[dict[str, object]] = []
        self._list_th: _ListGithubThread | None = None
        self._dl_th: _DownloadGithubThread | None = None
        self._up_th: _UploadGithubThread | None = None

        card = CardWidget(self)
        hint = BodyLabel(
            "从后端服务浏览社区谱面并下载；上传请在乐曲卡右键菜单中操作。\n"
            "请先在【设置】填写“后端代传服务地址 + 上传密钥”。"
        )
        hint.setWordWrap(True)

        self._table = QTableWidget(0, 4, self)
        apply_fluent_sheet_table(self._table)
        self._table.setHorizontalHeaderLabels(["歌名目录", "music 包", "cueFile 包", "路径"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.doubleClicked.connect(lambda _i: self._on_download())

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
        upload = PushButton("上传本地谱面文件…", self)
        upload.clicked.connect(self._on_upload)
        dl = PrimaryPushButton("下载选中项", self)
        dl.clicked.connect(self._on_download)
        close = PushButton("关闭", self)
        close.clicked.connect(self.reject)

        btns = QHBoxLayout()
        btns.addWidget(refresh)
        btns.addWidget(upload)
        btns.addStretch(1)
        btns.addWidget(dl)
        btns.addWidget(close)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*fluent_caption_content_margins())
        lay.setSpacing(12)
        lay.addWidget(card, stretch=1)
        lay.addLayout(btns)

        self._on_refresh()

    def _thread_running(self, th: QThread | None) -> bool:
        if th is None:
            return False
        try:
            return th.isRunning()
        except RuntimeError:
            return False

    def _on_refresh(self) -> None:
        if not self._backend_api:
            fly_warning(self, "未配置后端", "请先在【设置】填写“后端代传服务地址”。")
            return
        self._rows.clear()
        self._table.setRowCount(0)
        self._status.setText(f"正在拉取后端歌单：{self._backend_api}")
        try:
            songs = list_backend_songs(api_base=self._backend_api)
        except Exception as e:
            self._status.setText("加载失败。")
            fly_critical(self, "读取后端歌单失败", str(e))
            return
        self._song_rows = []
        for s in songs:
            sid = str(s.get("songId") or "").strip()
            if not sid:
                continue
            self._song_rows.append(
                {
                    "song_dir": sid,
                    "music_path": "music.zip" if bool(s.get("hasMusicZip")) else "",
                    "cue_path": "cueFile.zip" if bool(s.get("hasCueZip")) else "",
                    "base_path": sid,
                    "song_name": str(s.get("songName") or sid),
                }
            )
        self._song_rows.sort(key=lambda x: str(x.get("song_name") or "").lower())
        self._table.setRowCount(0)
        for e in self._song_rows:
            r = self._table.rowCount()
            self._table.insertRow(r)
            music_ok = bool(str(e.get("music_path") or "").strip())
            cue_ok = bool(str(e.get("cue_path") or "").strip())
            self._table.setItem(r, 0, QTableWidgetItem(str(e.get("song_name") or e.get("song_dir") or "")))
            self._table.setItem(r, 1, QTableWidgetItem("有" if music_ok else "无"))
            self._table.setItem(r, 2, QTableWidgetItem("有" if cue_ok else "无"))
            self._table.setItem(r, 3, QTableWidgetItem(str(e.get("base_path") or "")))
        self._status.setText(f"已加载 {len(self._song_rows)} 首社区乐曲。双击可下载。")

    def _release_list_thread(self, th: _ListGithubThread) -> None:
        if self._list_th is th:
            self._list_th = None
        th.deleteLater()

    def _on_list_ok(self, rows: object) -> None:
        if not isinstance(rows, list):
            self._status.setText("列表格式错误。")
            return
        self._rows = [x for x in rows if isinstance(x, GithubChartEntry)]
        grouped: dict[str, dict[str, object]] = {}
        for e in self._rows:
            p = e.path.strip().replace("\\", "/")
            if not p.startswith("charts/songs/"):
                continue
            rel = p[len("charts/songs/") :]
            if "/" not in rel:
                continue
            song_dir, fn = rel.split("/", 1)
            rec = grouped.setdefault(
                song_dir,
                {"song_dir": song_dir, "music_path": "", "cue_path": "", "base_path": f"charts/songs/{song_dir}"},
            )
            low = fn.lower()
            if low.endswith("music.zip"):
                rec["music_path"] = e.path
            elif low.endswith("cuefile.zip"):
                rec["cue_path"] = e.path
        self._song_rows = sorted(grouped.values(), key=lambda x: str(x.get("song_dir") or "").lower())
        self._table.setRowCount(0)
        for e in self._song_rows:
            r = self._table.rowCount()
            self._table.insertRow(r)
            music_ok = bool(str(e.get("music_path") or "").strip())
            cue_ok = bool(str(e.get("cue_path") or "").strip())
            self._table.setItem(r, 0, QTableWidgetItem(str(e.get("song_dir") or "")))
            self._table.setItem(r, 1, QTableWidgetItem("有" if music_ok else "无"))
            self._table.setItem(r, 2, QTableWidgetItem("有" if cue_ok else "无"))
            self._table.setItem(r, 3, QTableWidgetItem(str(e.get("base_path") or "")))
        self._status.setText(f"已加载 {len(self._song_rows)} 首社区乐曲。双击可下载。")

    def _on_list_fail(self, msg: str) -> None:
        self._status.setText("加载失败。")
        fly_critical(self, "读取 GitHub 分支失败", msg)

    def _selected(self) -> dict[str, object] | None:
        r = self._table.currentRow()
        if r < 0 or r >= len(self._song_rows):
            return None
        return self._song_rows[r]

    def _on_download(self) -> None:
        e = self._selected()
        if e is None:
            fly_warning(self, "未选择", "请先选择一个文件。")
            return
        if not self._backend_api:
            fly_warning(self, "未配置后端", "请先在【设置】填写“后端代传服务地址”。")
            return
        music_path = str(e.get("music_path") or "").strip()
        cue_path = str(e.get("cue_path") or "").strip()
        if not music_path and not cue_path:
            fly_warning(self, "无可下载文件", "该条目不含 music.zip 或 cueFile.zip。")
            return
        song_id = str(e.get("song_dir") or "").strip()
        song_title = str(e.get("song_name") or song_id)
        self._status.setText(f"正在下载：{song_title}")
        out_dir = app_cache_dir() / "github_charts"
        out_dir.mkdir(parents=True, exist_ok=True)
        files: list[Path] = []
        try:
            if music_path:
                p1 = out_dir / f"{song_id}_music.zip"
                download_backend_song_file(api_base=self._backend_api, song_id=song_id, filename="music.zip", output_path=p1)
                files.append(p1)
            if cue_path:
                p2 = out_dir / f"{song_id}_cueFile.zip"
                download_backend_song_file(api_base=self._backend_api, song_id=song_id, filename="cueFile.zip", output_path=p2)
                files.append(p2)
        except Exception as ex:
            self._status.setText("下载失败。")
            fly_critical(self, "下载失败", str(ex))
            return
        self._status.setText("下载完成。")
        if fly_question(
            self,
            "下载完成",
            f"已下载 {song_title} 的 {len(files)} 个包。\n\n是否立即导入到 ACUS？",
            yes_text="导入",
            no_text="仅保存",
        ):
            total = 0
            try:
                for p in files:
                    total += len(install_zip_to_acus(p, self._acus_root))
                fly_message(self, "导入完成", f"已累计写入 {total} 个文件到 ACUS。")
                return
            except Exception as ex:
                fly_critical(self, "导入失败", str(ex))
                return
        fly_message(self, "下载完成", "文件已保存到缓存目录 .cache/github_charts。")

    def _release_download_thread(self, th: _DownloadGithubThread) -> None:
        if self._dl_th is th:
            self._dl_th = None
        th.deleteLater()

    def _on_download_ok(self, out: str) -> None:
        self._status.setText("下载完成。")
        th = self._dl_th
        extra = ""
        song_name = ""
        if th is not None:
            extra = str(getattr(th, "_extra_path", "") or "")
            song_name = str(getattr(th, "_song_dir", "") or "")
        files = [Path(out)]
        if extra:
            try:
                data = download_github_chart_bytes(repo=self._repo, branch=self._branch, file_path=extra)
                out_dir = app_cache_dir() / "github_charts"
                out_dir.mkdir(parents=True, exist_ok=True)
                p2 = out_dir / Path(extra).name
                p2.write_bytes(data)
                files.append(p2)
            except Exception as e:
                fly_warning(self, "部分下载失败", f"次要文件下载失败：{e}")
        if fly_question(
            self,
            "下载完成",
            f"已下载 {song_name or '所选乐曲'} 的 {len(files)} 个包。\n\n是否立即导入到 ACUS？",
            yes_text="导入",
            no_text="仅保存",
        ):
            total = 0
            try:
                for p in files:
                    total += len(install_zip_to_acus(p, self._acus_root))
                fly_message(self, "导入完成", f"已累计写入 {total} 个文件到 ACUS。")
                return
            except Exception as e:
                fly_critical(self, "导入失败", str(e))
                return
        fly_message(self, "下载完成", "文件已保存到缓存目录 .cache/github_charts。")

    def _on_download_fail(self, msg: str) -> None:
        self._status.setText("下载失败。")
        fly_critical(self, "下载失败", msg)

    def _on_upload(self) -> None:
        fly_message(self, "提示", "请在“乐曲页面 -> 卡片右键 -> 上传到 GitHub 社区谱面…”执行上传。")

    @staticmethod
    def upload_music_item(*, parent, acus_root: Path, item: MusicItem) -> None:
        cfg = AcusConfig.load()
        backend_api = (getattr(cfg, "uploader_api_base", "") or "").strip()
        backend_key = (getattr(cfg, "uploader_api_key", "") or "").strip()
        repo = (cfg.github_charts_repo or "").strip()
        branch = (cfg.github_charts_branch or "charts").strip() or "charts"
        token = (cfg.github_charts_token or "").strip()
        music_dir = item.xml_path.parent
        if not music_dir.is_dir():
            fly_warning(parent, "目录不存在", f"未找到乐曲目录：\n{music_dir}")
            return
        cue_dir: Path | None = None
        if item.cue_file is not None and item.cue_file.id > 0:
            cand = acus_root / "cueFile" / f"cueFile{item.cue_file.id:06d}"
            if cand.is_dir():
                cue_dir = cand
        safe_song = "".join(c if c not in '\\/:*?"<>|' else "_" for c in (item.name.str or "").strip()).strip()
        if not safe_song:
            safe_song = f"music_{item.name.id}"
        remote_base = f"charts/songs/{safe_song}_{item.name.id}"
        if not fly_question(
            parent,
            "上传社区谱面",
            f"将上传目录：{remote_base}\n\n包含：music 目录"
            + ("\n包含：cueFile 目录" if cue_dir is not None else "\n不包含 cueFile（未找到）"),
            yes_text="上传",
            no_text="取消",
        ):
            return
        try:
            with tempfile.TemporaryDirectory(prefix="chuni_gh_upload_") as td:
                tdp = Path(td)
                music_zip_base = tdp / "music_bundle"
                cue_zip_base = tdp / "cue_bundle"
                music_zip = Path(shutil.make_archive(str(music_zip_base), "zip", root_dir=music_dir))
                cue_zip: Path | None = None
                if cue_dir is not None and cue_dir.is_dir():
                    cue_zip = Path(shutil.make_archive(str(cue_zip_base), "zip", root_dir=cue_dir))
                if backend_api and backend_key:
                    ret = upload_to_backend(
                        api_base=backend_api,
                        api_key=backend_key,
                        music_id=item.name.id,
                        song_name=item.name.str or f"music_{item.name.id}",
                        music_zip=music_zip,
                        cue_zip=cue_zip,
                        uploader_name="desktop-user",
                    )
                    song_id = str(ret.get("songId") or "").strip()
                    folder = str(ret.get("folder") or "").strip()
                    tip = f"songId: {song_id}\nfolder: {folder}" if song_id or folder else "上传成功。"
                    fly_message(parent, "上传完成（后端代传）", tip)
                    return
                if not repo:
                    fly_warning(parent, "未配置仓库", "请先在【设置】填写 GitHub Charts 仓库（owner/repo）。")
                    return
                if not token:
                    fly_warning(parent, "缺少 Token", "请在【设置】填写 GitHub Token，或配置后端代传。")
                    return
                upload_file_to_github_charts(
                    repo=repo,
                    branch=branch,
                    target_path=f"{remote_base}/music.zip",
                    local_file=music_zip,
                    token=token,
                    message=f"chore(charts): upload music {item.name.id}",
                )
                if cue_zip is not None:
                    upload_file_to_github_charts(
                        repo=repo,
                        branch=branch,
                        target_path=f"{remote_base}/cueFile.zip",
                        local_file=cue_zip,
                        token=token,
                        message=f"chore(charts): upload cue {item.name.id}",
                    )
            owner, name = _split_repo(repo)
            url = f"https://github.com/{owner}/{name}/tree/{branch}/{remote_base}"
            fly_message(parent, "上传完成", f"已上传到：\n{url}")
        except Exception as e:
            fly_critical(parent, "上传失败", str(e))

    def _release_upload_thread(self, th: _UploadGithubThread) -> None:
        if self._up_th is th:
            self._up_th = None
        th.deleteLater()

    def _on_upload_ok(self, n: int) -> None:
        self._status.setText("上传完成。")
        fly_message(self, "上传完成", f"已上传 {n} 个文件到分支 {self._branch}。")
        self._on_refresh()

    def _on_upload_fail(self, msg: str) -> None:
        self._status.setText("上传失败。")
        fly_critical(self, "上传失败", msg)
