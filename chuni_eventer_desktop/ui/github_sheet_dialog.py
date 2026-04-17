from __future__ import annotations

from pathlib import Path
import shutil
import tempfile

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from qfluentwidgets import BodyLabel, CardWidget, PrimaryPushButton, PushButton

from ..acus_workspace import app_cache_dir
from ..acus_scan import MusicItem
from ..backend_upload_client import (
    download_backend_song_file,
    list_backend_songs,
    upload_to_backend,
)
from ..sheet_install import install_zip_to_acus
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical, fly_message, fly_question, fly_warning
from .fluent_table import apply_fluent_sheet_table

_UPLOADER_API_BASE = "https://uploader.swan416.top"
_UPLOADER_API_KEY = "114514"


class GithubSheetDialog(FluentCaptionDialog):
    def __init__(self, *, acus_root: Path, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("SwanClub 社区谱面")
        self.setModal(True)
        self.resize(780, 560)
        self._acus_root = acus_root

        self._backend_api = _UPLOADER_API_BASE
        self._song_rows: list[dict[str, object]] = []

        card = CardWidget(self)
        hint = BodyLabel(
            "从 SwanClub 服务浏览社区谱面并下载；上传请在乐曲卡右键菜单中操作。\n"
            "当前客户端已内置上传服务地址与密钥。"
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
        upload = PushButton("上传入口提示", self)
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

    def _on_refresh(self) -> None:
        if not self._backend_api:
            fly_warning(self, "服务不可用", "内置上传服务地址为空，请联系开发者。")
            return
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
            fly_warning(self, "服务不可用", "内置上传服务地址为空，请联系开发者。")
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

    def _on_upload(self) -> None:
        fly_message(self, "提示", "请在“乐曲页面 -> 卡片右键 -> 上传”执行上传。")

    @staticmethod
    def upload_music_item(*, parent, acus_root: Path, item: MusicItem) -> None:
        backend_api = _UPLOADER_API_BASE
        backend_key = _UPLOADER_API_KEY
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
            "上传到 SwanClub",
            f"将上传 songId：{safe_song}_{item.name.id}\n\n包含：music 目录"
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
                    fly_message(parent, "上传完成", tip)
                    return
        except Exception as e:
            fly_critical(parent, "上传失败", str(e))
