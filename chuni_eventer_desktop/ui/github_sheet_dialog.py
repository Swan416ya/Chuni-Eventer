from __future__ import annotations

from pathlib import Path
import re
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from qfluentwidgets import BodyLabel, CardWidget, LineEdit, PrimaryPushButton, PushButton

from ..acus_workspace import app_cache_dir
from ..acus_scan import MusicItem
from ..backend_upload_client import (
    download_backend_song_file,
    list_backend_songs,
    upload_to_backend,
)
from ..music_delete import plan_music_deletion
from ..sheet_install import _mapper_for_paths, install_zip_to_acus
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical, fly_message, fly_question, fly_warning
from .fluent_table import apply_fluent_sheet_table

_UPLOADER_API_BASE = "https://uploader.swan416.top"
_UPLOADER_API_KEY = "114514"


def _safe_song_display_name(item: MusicItem) -> str:
    safe_song = "".join(c if c not in '\\/:*?"<>|' else "_" for c in (item.name.str or "").strip()).strip()
    if not safe_song:
        safe_song = f"music_{item.name.id}"
    return safe_song


def _add_dir_to_zip(zf: zipfile.ZipFile, acus_root: Path, source_dir: Path) -> int:
    count = 0
    root = acus_root.resolve()
    src = source_dir.resolve()
    for p in src.rglob("*"):
        if not p.is_file():
            continue
        rel = p.resolve().relative_to(root).as_posix()
        zf.write(p, arcname=rel)
        count += 1
    return count


def _build_song_package_zip(*, acus_root: Path, item: MusicItem, output_zip: Path) -> tuple[int, list[str]]:
    plan = plan_music_deletion(acus_root, item)
    include_dirs: list[Path] = []
    labels: list[str] = []
    if plan.music_dir is not None and plan.music_dir.is_dir():
        include_dirs.append(plan.music_dir)
        labels.append(f"music/{plan.music_dir.name}")
    if plan.cue_dir is not None and plan.cue_dir.is_dir():
        include_dirs.append(plan.cue_dir)
        labels.append(f"cueFile/{plan.cue_dir.name}")
    if plan.stage_dir is not None and plan.stage_dir.is_dir():
        include_dirs.append(plan.stage_dir)
        labels.append(f"stage/{plan.stage_dir.name}")
    for p in plan.event_dirs_to_remove:
        if p.is_dir():
            include_dirs.append(p)
            labels.append(f"event/{p.name}")
    if not include_dirs:
        raise RuntimeError("未找到可打包目录（至少需要 music 目录）。")
    unique_dirs = list(dict.fromkeys(d.resolve() for d in include_dirs))
    file_count = 0
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for d in unique_dirs:
            file_count += _add_dir_to_zip(zf, acus_root, d)
    if file_count <= 0:
        raise RuntimeError("打包结果为空，请检查歌曲目录内容。")
    return file_count, labels


def _extract_package_zip(src_zip: Path, dst_dir: Path) -> None:
    with zipfile.ZipFile(src_zip, "r") as zf:
        zf.extractall(dst_dir)


def _find_primary_music_xml(root: Path) -> Path | None:
    for p in root.glob("music/**/Music.xml"):
        if p.is_file():
            return p
    return None


def _replace_music_id_in_xml(xml_path: Path, new_music_id: int) -> int:
    changed = 0
    tree = ET.parse(xml_path)
    root = tree.getroot()
    for el in root.findall(".//name/id"):
        old = (el.text or "").strip()
        if old.isdigit():
            if int(old) != new_music_id:
                el.text = str(new_music_id)
                changed += 1
            break
    if changed > 0:
        tree.write(xml_path, encoding="utf-8", xml_declaration=True)
    return changed


def _rewrite_music_related_ids_in_xml(xml_path: Path, old_music_id: int, new_music_id: int) -> int:
    """
    在“music 相关”节点中把 old_music_id 改为 new_music_id。
    规则：当前/父/祖父标签名包含 music，且文本值等于 old_music_id。
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()
    old_s = str(old_music_id)
    new_s = str(new_music_id)
    changed = 0

    def walk(node: ET.Element, parent_tag: str, grand_tag: str) -> None:
        nonlocal changed
        tag = (node.tag or "").strip().lower()
        txt = (node.text or "").strip()
        ctx = f"{tag}|{parent_tag}|{grand_tag}"
        if txt == old_s and ("music" in ctx):
            node.text = new_s
            changed += 1
        for ch in list(node):
            walk(ch, tag, parent_tag)

    walk(root, "", "")
    if changed > 0:
        tree.write(xml_path, encoding="utf-8", xml_declaration=True)
    return changed


def _rewrite_all_id_fields_in_xml(xml_path: Path, old_music_id: int, new_music_id: int) -> int:
    """
    将 XML 内所有 <id>old_music_id</id> 改为 new_music_id。
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()
    old_s = str(old_music_id)
    new_s = str(new_music_id)
    changed = 0
    for id_el in root.findall(".//id"):
        txt = (id_el.text or "").strip()
        if txt == old_s:
            id_el.text = new_s
            changed += 1
    if changed > 0:
        tree.write(xml_path, encoding="utf-8", xml_declaration=True)
    return changed


def _map_related_numeric_id(old_id: int, old_music_id: int, new_music_id: int) -> int:
    old6 = f"{old_music_id:06d}"
    new6 = f"{new_music_id:06d}"
    old_plain = str(old_music_id)
    new_plain = str(new_music_id)
    text = str(old_id)
    mapped = text.replace(old6, new6).replace(old_plain, new_plain)
    if mapped.isdigit():
        return int(mapped)
    if old_id == old_music_id:
        return new_music_id
    return old_id


def _rewrite_primary_name_id(xml_path: Path, new_id: int) -> int:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    name_id = root.find("name/id")
    if name_id is None:
        return 0
    old = (name_id.text or "").strip()
    if old.isdigit() and int(old) == new_id:
        return 0
    name_id.text = str(new_id)
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)
    return 1


def _rewrite_event_and_cue_structures(root: Path, old_music_id: int, new_music_id: int) -> int:
    rename_count = 0
    event_root = root / "event"
    if event_root.is_dir():
        for ev_dir in sorted([p for p in event_root.iterdir() if p.is_dir()]):
            m = re.fullmatch(r"event(\d+)", ev_dir.name, flags=re.IGNORECASE)
            if m is None:
                continue
            old_event_id = int(m.group(1))
            new_event_id = _map_related_numeric_id(old_event_id, old_music_id, new_music_id)
            target_dir = ev_dir
            if new_event_id != old_event_id:
                cand = event_root / f"event{new_event_id:06d}"
                if cand != ev_dir and not cand.exists():
                    ev_dir.rename(cand)
                    target_dir = cand
                    rename_count += 1
            ev_xml = target_dir / "Event.xml"
            if ev_xml.is_file():
                _rewrite_primary_name_id(ev_xml, new_event_id)

    cue_root = root / "cueFile"
    if cue_root.is_dir():
        for cue_dir in sorted([p for p in cue_root.iterdir() if p.is_dir()]):
            m = re.fullmatch(r"cuefile(\d+)", cue_dir.name, flags=re.IGNORECASE)
            if m is None:
                continue
            old_cue_id = int(m.group(1))
            new_cue_id = _map_related_numeric_id(old_cue_id, old_music_id, new_music_id)
            target_dir = cue_dir
            if new_cue_id != old_cue_id:
                cand = cue_root / f"cueFile{new_cue_id:06d}"
                if cand != cue_dir and not cand.exists():
                    cue_dir.rename(cand)
                    target_dir = cand
                    rename_count += 1
            cue_xml = target_dir / "CueFile.xml"
            if cue_xml.is_file():
                _rewrite_primary_name_id(cue_xml, new_cue_id)
    return rename_count


def _rename_contains_token(p: Path, old_token: str, new_token: str) -> Path:
    if old_token not in p.name:
        return p
    new_name = p.name.replace(old_token, new_token)
    new_path = p.with_name(new_name)
    p.rename(new_path)
    return new_path


def _rewrite_package_music_id(src_zip: Path, new_music_id: int, out_zip: Path) -> tuple[int, int]:
    old_music_id = -1
    rename_count = 0
    with tempfile.TemporaryDirectory(prefix="chuni_pkg_rewrite_") as td:
        root = Path(td)
        _extract_package_zip(src_zip, root)
        music_xml = _find_primary_music_xml(root)
        if music_xml is None:
            raise RuntimeError("包内缺少 music/*/Music.xml，无法改 ID。")
        old_id_text = (ET.parse(music_xml).getroot().findtext("name/id") or "").strip()
        if not old_id_text.isdigit():
            raise RuntimeError("Music.xml 中缺少有效的 name/id。")
        old_music_id = int(old_id_text)
        if old_music_id == new_music_id:
            shutil.copy2(src_zip, out_zip)
            return old_music_id, 0
        _replace_music_id_in_xml(music_xml, new_music_id)
        rename_count += _rewrite_event_and_cue_structures(root, old_music_id, new_music_id)
        for xp in root.rglob("*.xml"):
            if xp == music_xml:
                continue
            _rewrite_all_id_fields_in_xml(xp, old_music_id, new_music_id)
            _rewrite_music_related_ids_in_xml(xp, old_music_id, new_music_id)
        old6 = f"{old_music_id:06d}"
        new6 = f"{new_music_id:06d}"
        old_plain = str(old_music_id)
        new_plain = str(new_music_id)
        music_dir_old = root / "music" / f"music{old6}"
        music_dir_new = root / "music" / f"music{new6}"
        if music_dir_old.is_dir():
            music_dir_old.rename(music_dir_new)
            rename_count += 1
        for p in sorted(root.rglob("*"), key=lambda x: len(str(x)), reverse=True):
            if p == music_xml:
                continue
            renamed = _rename_contains_token(p, old6, new6)
            if renamed == p:
                renamed = _rename_contains_token(p, old_plain, new_plain)
            if renamed != p:
                rename_count += 1
        with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in root.rglob("*"):
                if not p.is_file():
                    continue
                zf.write(p, arcname=p.relative_to(root).as_posix())
    return old_music_id, rename_count


def _preview_install_targets(zip_path: Path, limit: int = 120) -> tuple[int, list[str]]:
    """
    预览 install_zip_to_acus 将要写入的 ACUS 相对路径（不落盘）。
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        mapper = _mapper_for_paths(names)
        out: list[str] = []
        for n in names:
            if n.endswith("/"):
                continue
            rel = mapper(n).as_posix()
            if rel in ("", "."):
                continue
            out.append(rel)
    out = sorted(dict.fromkeys(out))
    return len(out), out[:limit]


class MusicIdInputDialog(FluentCaptionDialog):
    def __init__(self, *, current_id: int, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("导入前修改 ID")
        self.setModal(True)
        self.resize(520, 220)
        self._value: str = ""

        card = CardWidget(self)
        cly = QVBoxLayout(card)
        cly.setContentsMargins(16, 16, 16, 16)
        cly.setSpacing(10)
        hint = BodyLabel("请输入新的乐曲 ID（留空或保持原值则不修改）")
        hint.setWordWrap(True)
        self._edit = LineEdit(self)
        self._edit.setPlaceholderText("例如 123456")
        self._edit.setText(str(current_id if current_id > 0 else ""))
        cly.addWidget(hint)
        cly.addWidget(self._edit)

        ok = PrimaryPushButton("确定", self)
        cancel = PushButton("取消", self)
        ok.clicked.connect(self._on_ok)
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*fluent_caption_content_margins())
        lay.setSpacing(12)
        lay.addWidget(card, stretch=1)
        lay.addLayout(btns)

    def _on_ok(self) -> None:
        txt = self._edit.text().strip()
        if txt and not re.fullmatch(r"\d+", txt):
            fly_warning(self, "输入不合法", "ID 只能是正整数。")
            return
        if txt and int(txt) <= 0:
            fly_warning(self, "输入不合法", "ID 必须大于 0。")
            return
        self._value = txt
        self.accept()

    def value(self) -> str:
        return self._value


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

        self._table = QTableWidget(0, 5, self)
        apply_fluent_sheet_table(self._table)
        self._table.setHorizontalHeaderLabels(["歌名", "艺术家", "谱师", "ID", "整包"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
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
                    "package_path": "package.zip" if bool(s.get("hasPackageZip")) else "",
                    "base_path": sid,
                    "song_name": str(s.get("songName") or sid),
                    "artist_name": str(s.get("artistName") or ""),
                    "charter_name": str(s.get("charterName") or ""),
                    "music_id": int(s.get("musicId") or 0),
                }
            )
        self._song_rows.sort(key=lambda x: str(x.get("song_name") or "").lower())
        self._table.setRowCount(0)
        for e in self._song_rows:
            r = self._table.rowCount()
            self._table.insertRow(r)
            package_ok = bool(str(e.get("package_path") or "").strip())
            self._table.setItem(r, 0, QTableWidgetItem(str(e.get("song_name") or e.get("song_dir") or "")))
            self._table.setItem(r, 1, QTableWidgetItem(str(e.get("artist_name") or "")))
            self._table.setItem(r, 2, QTableWidgetItem(str(e.get("charter_name") or "")))
            self._table.setItem(r, 3, QTableWidgetItem(str(e.get("music_id") or "")))
            self._table.setItem(r, 4, QTableWidgetItem("有" if package_ok else "无"))
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
        package_path = str(e.get("package_path") or "").strip()
        if not package_path:
            fly_warning(self, "无可下载文件", "该条目不含 package.zip。")
            return
        song_id = str(e.get("song_dir") or "").strip()
        song_title = str(e.get("song_name") or song_id)
        self._status.setText(f"正在下载：{song_title}")
        out_dir = app_cache_dir() / "github_charts"
        out_dir.mkdir(parents=True, exist_ok=True)
        package_file = out_dir / f"{song_id}_package.zip"
        try:
            download_backend_song_file(
                api_base=self._backend_api, song_id=song_id, filename="package.zip", output_path=package_file
            )
        except Exception as ex:
            self._status.setText("下载失败。")
            fly_critical(self, "下载失败", str(ex))
            return
        self._status.setText("下载完成。")
        if fly_question(
            self,
            "下载完成",
            f"已下载 {song_title} 的整包。\n\n是否继续导入（可先改 ID）？",
            yes_text="继续",
            no_text="仅保存",
        ):
            try:
                default_id = int(e.get("music_id") or 0)
                id_dlg = MusicIdInputDialog(current_id=default_id, parent=self)
                ok = id_dlg.exec() == id_dlg.DialogCode.Accepted
                to_install = package_file
                if ok:
                    new_text = id_dlg.value().strip()
                    if new_text and re.fullmatch(r"\d+", new_text):
                        new_id = int(new_text)
                        if new_id <= 0:
                            raise RuntimeError("ID 必须大于 0。")
                        rewritten = out_dir / f"{song_id}_package_reid_{new_id}.zip"
                        old_id, renamed = _rewrite_package_music_id(package_file, new_id, rewritten)
                        to_install = rewritten
                        if old_id != new_id:
                            fly_message(
                                self,
                                "ID 已修改",
                                f"已将乐曲 ID 从 {old_id} 改为 {new_id}，并处理相关目录/文件重命名 {renamed} 处。",
                            )
                total_preview, preview_paths = _preview_install_targets(to_install)
                preview_text = "\n".join(preview_paths)
                if total_preview > len(preview_paths):
                    preview_text += f"\n...（其余 {total_preview - len(preview_paths)} 项省略）"
                if not fly_question(
                    self,
                    "导入预览",
                    f"将写入 ACUS：{self._acus_root}\n"
                    f"预计写入文件：{total_preview}\n\n"
                    f"{preview_text or '（无可写入项）'}\n\n"
                    "确认继续导入吗？",
                    yes_text="确认导入",
                    no_text="取消",
                ):
                    fly_message(self, "已取消", "你已取消本次导入。")
                    return
                total = len(install_zip_to_acus(to_install, self._acus_root))
                fly_message(
                    self,
                    "导入完成",
                    f"已累计写入 {total} 个文件到 ACUS。\n\n目标目录：\n{self._acus_root}",
                )
                return
            except Exception as ex:
                fly_critical(self, "导入失败", str(ex))
                return
        fly_message(self, "下载完成", f"文件已保存到：\n{package_file}")

    def _on_upload(self) -> None:
        fly_message(self, "提示", "请在“乐曲页面 -> 卡片右键 -> 上传”执行上传。")

    @staticmethod
    def upload_music_item(*, parent, acus_root: Path, item: MusicItem) -> None:
        backend_api = _UPLOADER_API_BASE
        backend_key = _UPLOADER_API_KEY
        music_dir = item.xml_path.parent.resolve()
        if not music_dir.is_dir():
            fly_warning(parent, "目录不存在", f"未找到乐曲目录：\n{music_dir}")
            return
        safe_song = _safe_song_display_name(item)
        plan = plan_music_deletion(acus_root, item)
        include_texts: list[str] = []
        if plan.music_dir is not None and plan.music_dir.is_dir():
            include_texts.append(f"music/{plan.music_dir.name}")
        if plan.cue_dir is not None and plan.cue_dir.is_dir():
            include_texts.append(f"cueFile/{plan.cue_dir.name}")
        if plan.stage_dir is not None and plan.stage_dir.is_dir():
            include_texts.append(f"stage/{plan.stage_dir.name}")
        include_texts.extend([f"event/{p.name}" for p in plan.event_dirs_to_remove if p.is_dir()])
        if not fly_question(
            parent,
            "上传到 SwanClub",
            f"将上传 songId：{safe_song}_{item.name.id}\n\n"
            + ("包含目录：\n- " + "\n- ".join(include_texts) if include_texts else "包含目录：music（自动检测）"),
            yes_text="上传",
            no_text="取消",
        ):
            return
        try:
            with tempfile.TemporaryDirectory(prefix="chuni_gh_upload_") as td:
                tdp = Path(td)
                package_zip = tdp / f"{safe_song}_{item.name.id}.zip"
                file_count, packed_dirs = _build_song_package_zip(acus_root=acus_root, item=item, output_zip=package_zip)
                if backend_api and backend_key:
                    ret = upload_to_backend(
                        api_base=backend_api,
                        api_key=backend_key,
                        music_id=item.name.id,
                        song_name=item.name.str or f"music_{item.name.id}",
                        package_zip=package_zip,
                        uploader_name="desktop-user",
                    )
                    song_id = str(ret.get("songId") or "").strip()
                    folder = str(ret.get("folder") or "").strip()
                    tip = (
                        f"上传成功。\n"
                        f"songId: {song_id or '-'}\n"
                        f"folder: {folder or '-'}\n"
                        f"打包目录数: {len(packed_dirs)}\n"
                        f"打包文件数: {file_count}"
                    )
                    fly_message(parent, "上传完成", tip)
                    return
        except Exception as e:
            fly_critical(parent, "上传失败", str(e))
