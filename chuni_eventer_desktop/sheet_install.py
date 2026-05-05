from __future__ import annotations

import re
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path


# 与 ACUS 根下目录名一致（小写比较）
_ACUS_TOP_NAMES_LOWER = frozenset(
    x.lower()
    for x in (
        "chara",
        "ddsImage",
        "ddsMap",
        "music",
        "map",
        "mapArea",
        "mapBonus",
        "event",
        "course",
        "reward",
        "cueFile",
        "namePlate",
        "trophy",
        "quest",
        "stage",
    )
)

# 压缩包顶层为「资源文件夹本体」时（如 music0820、cueFile7013），映射到 ACUS 下的父目录。
# 顺序：先匹配更长前缀（mapArea 先于 map）。
_LEAF_FOLDER_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^maparea\d+$", re.IGNORECASE), "mapArea"),
    (re.compile(r"^mapbonus\d+$", re.IGNORECASE), "mapBonus"),
    (re.compile(r"^map\d+$", re.IGNORECASE), "map"),
    (re.compile(r"^ddsmap\d+$", re.IGNORECASE), "ddsMap"),
    (re.compile(r"^ddsimage\d+$", re.IGNORECASE), "ddsImage"),
    (re.compile(r"^music\d+$", re.IGNORECASE), "music"),
    (re.compile(r"^cuefile\d+$", re.IGNORECASE), "cueFile"),
    (re.compile(r"^chara\d+$", re.IGNORECASE), "chara"),
    (re.compile(r"^nameplate\d+$", re.IGNORECASE), "namePlate"),
    (re.compile(r"^trophy\d+$", re.IGNORECASE), "trophy"),
    (re.compile(r"^event\d+$", re.IGNORECASE), "event"),
    (re.compile(r"^course\d+$", re.IGNORECASE), "course"),
    (re.compile(r"^reward\d+$", re.IGNORECASE), "reward"),
    (re.compile(r"^quest\d+$", re.IGNORECASE), "quest"),
    (re.compile(r"^stage\d+$", re.IGNORECASE), "stage"),
)


def _is_readme_root_entry(name: str) -> bool:
    """压缩包根目录下的说明文件（如 readme.txt、README.md），不参与 ACUS 落盘。"""
    n = _norm_posix(name).strip().rstrip("/")
    if not n or "/" in n:
        return False
    low = n.lower()
    return low == "readme" or low.startswith("readme.")


def _is_junk_member(name: str) -> bool:
    n = name.replace("\\", "/").strip()
    if not n:
        return True
    if n.startswith("__MACOSX/") or "/__MACOSX/" in n:
        return True
    if n.endswith(".DS_Store") or "/.DS_Store" in n:
        return True
    if "/._" in n or n.startswith("._"):
        return True
    return False


def _norm_posix(name: str) -> str:
    return name.replace("\\", "/").strip()


def _strip_acus_prefix(n: str) -> str:
    p = _norm_posix(n)
    low = p.lower()
    if low == "acus":
        return ""
    if low.startswith("acus/"):
        return p[5:]
    return p


def _acus_parent_for_leaf_folder(first_segment: str) -> str | None:
    for rx, parent in _LEAF_FOLDER_RULES:
        if rx.match(first_segment):
            return parent
    return None


def _decode_readme_bytes(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gbk", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _map_internal_to_rel(p: str) -> Path:
    """
    将归档内路径（已去 ACUS 前缀）映射为相对于 ACUS 根的路径。
    """
    p = _norm_posix(p)
    if not p or p == ".":
        return Path(".")
    fparts = [x for x in p.split("/") if x != ""]
    if len(fparts) == 1 and _is_readme_root_entry(fparts[0]):
        return Path(".")
    parts = p.split("/")
    head = parts[0]
    tail = parts[1:]

    parent = _acus_parent_for_leaf_folder(head)
    if parent is not None:
        rel = Path(parent) / head
        if tail:
            rel = rel.joinpath(*tail)
        return rel

    if head.lower() in _ACUS_TOP_NAMES_LOWER:
        return Path(p)

    raise ValueError(
        f"无法识别压缩包路径的顶层「{head}」。"
        f"请使用与 ACUS 一致的目录（如 music/…），或顶层为 music编号、cueFile编号、stage编号 等资源文件夹。"
    )


def _mapper_for_paths(namelist: list[str]):
    names = [_norm_posix(n) for n in namelist if not _is_junk_member(n)]
    names = [n for n in names if n]
    if not names:
        raise ValueError("压缩包内没有可用文件。")

    file_entries = [n.rstrip("/") for n in names if n and not n.endswith("/")]
    if file_entries and all(
        x.lower().startswith("acus/") or x.lower() == "acus" for x in file_entries
    ):
        names = [_strip_acus_prefix(n) for n in names]
        names = [n for n in names if n]

    def map_path(internal: str) -> Path:
        p = _strip_acus_prefix(_norm_posix(internal))
        return _map_internal_to_rel(p)

    return map_path


def _install_zip_core(zip_path: Path, acus_root: Path) -> list[str]:
    acus_root = acus_root.resolve()
    written: list[str] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        map_path = _mapper_for_paths(zf.namelist())
        for name in zf.namelist():
            if _is_junk_member(name):
                continue
            try:
                rel = map_path(name)
            except ValueError as e:
                raise ValueError(f"{e}\n（条目：{name!r}）") from e
            if str(rel) in (".", ""):
                continue
            if name.endswith("/"):
                dest_dir = (acus_root / rel).resolve()
                if not str(dest_dir).startswith(str(acus_root)):
                    raise ValueError(f"非法路径：{name!r}")
                dest_dir.mkdir(parents=True, exist_ok=True)
                continue
            dest = (acus_root / rel).resolve()
            if not str(dest).startswith(str(acus_root)):
                raise ValueError(f"非法路径（压缩包路径穿越）：{name!r}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name, "r") as src, dest.open("wb") as out:
                out.write(src.read())
            written.append(rel.as_posix())

    return written


def _install_tar_core(tar_path: Path, acus_root: Path) -> list[str]:
    acus_root = acus_root.resolve()
    written: list[str] = []
    with tarfile.open(tar_path, "r:*") as tf:
        members = [m for m in tf.getmembers() if not _is_junk_member(m.name)]
        namelist = [m.name for m in members]
        map_path = _mapper_for_paths(namelist)
        for m in members:
            name = m.name
            if m.isdir():
                try:
                    rel = map_path(name.rstrip("/") + "/")
                except ValueError as e:
                    raise ValueError(f"{e}\n（条目：{name!r}）") from e
                if str(rel) in (".", ""):
                    continue
                dest_dir = (acus_root / rel).resolve()
                if not str(dest_dir).startswith(str(acus_root)):
                    raise ValueError(f"非法路径：{name!r}")
                dest_dir.mkdir(parents=True, exist_ok=True)
                continue
            if not m.isfile():
                continue
            if m.issym() or m.islnk():
                continue
            try:
                rel = map_path(name)
            except ValueError as e:
                raise ValueError(f"{e}\n（条目：{name!r}）") from e
            if str(rel) in (".", ""):
                continue
            dest = (acus_root / rel).resolve()
            if not str(dest).startswith(str(acus_root)):
                raise ValueError(f"非法路径（压缩包路径穿越）：{name!r}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            f = tf.extractfile(m)
            if f is None:
                continue
            dest.write_bytes(f.read())
            written.append(rel.as_posix())

    return written


def _is_7z_magic(path: Path) -> bool:
    """7z 文件头：37 7A BC AF 27 1C（与 py7zr 一致）。"""
    try:
        with path.open("rb") as f:
            return f.read(6) == b"7z\xbc\xaf\x27\x1c"
    except OSError:
        return False


def _install_from_flat_dir(root: Path, acus_root: Path) -> list[str]:
    """将已展开到 root 的目录树按与 zip 相同规则写入 ACUS。"""
    acus_root = acus_root.resolve()
    root = root.resolve()
    rels: list[str] = []
    for p in root.rglob("*"):
        if p.is_file():
            rels.append(p.relative_to(root).as_posix())
    if not rels:
        raise ValueError("解压后的目录中没有文件。")
    map_path = _mapper_for_paths(rels)
    written: list[str] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        name = p.relative_to(root).as_posix()
        try:
            rel = map_path(name)
        except ValueError as e:
            raise ValueError(f"{e}\n（条目：{name!r}）") from e
        if str(rel) in (".", ""):
            continue
        dest = (acus_root / rel).resolve()
        if not str(dest).startswith(str(acus_root)):
            raise ValueError(f"非法路径：{name!r}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
        written.append(rel.as_posix())
    return written


def _install_7z_core(archive: Path, acus_root: Path) -> list[str]:
    """使用纯 Python 的 py7zr 解压 .7z（不依赖本机安装 7-Zip）。"""
    import py7zr

    td = Path(tempfile.mkdtemp(prefix="chuni_7z_"))
    try:
        with py7zr.SevenZipFile(archive, mode="r") as z:
            z.extractall(path=td)
        return _install_from_flat_dir(td, acus_root)
    finally:
        shutil.rmtree(td, ignore_errors=True)


def peek_root_readme_from_archive(archive_path: Path) -> str | None:
    """
    若归档根目录存在 readme 类文件（readme、readme.txt、README.md 等），返回解码后的全文；
    否则返回 None。用于导入前弹窗提示；安装逻辑会跳过此类文件。
    """
    p = archive_path.expanduser().resolve()
    if not p.is_file():
        return None

    def _pick_root_readme_names(namelist: list[str]) -> list[str]:
        cands: list[str] = []
        for name in namelist:
            if _is_junk_member(name) or name.endswith("/"):
                continue
            fp = [x for x in _norm_posix(name).split("/") if x != ""]
            if len(fp) == 1 and _is_readme_root_entry(fp[0]):
                cands.append(name)
        return cands

    if zipfile.is_zipfile(p):
        with zipfile.ZipFile(p, "r") as zf:
            cands = _pick_root_readme_names(zf.namelist())
            if not cands:
                return None
            name = sorted(cands, key=lambda x: x.lower())[0]
            with zf.open(name, "r") as f:
                return _decode_readme_bytes(f.read())

    if tarfile.is_tarfile(p):
        with tarfile.open(p, "r:*") as tf:
            names = [m.name for m in tf.getmembers() if m.isfile()]
            cands = _pick_root_readme_names(names)
            if not cands:
                return None
            name = sorted(cands, key=lambda x: x.lower())[0]
            m = tf.getmember(name)
            f = tf.extractfile(m)
            if f is None:
                return None
            try:
                return _decode_readme_bytes(f.read())
            finally:
                f.close()

    try:
        import py7zr
    except ImportError:
        py7zr = None  # type: ignore[assignment]

    if py7zr is not None and py7zr.is_7zfile(p):
        with py7zr.SevenZipFile(p, "r") as z:
            cands = _pick_root_readme_names(list(z.getnames()))
        if not cands:
            return None
        name = sorted(cands, key=lambda x: x.lower())[0]
        td = Path(tempfile.mkdtemp(prefix="chuni_r7z_readme_"))
        try:
            with py7zr.SevenZipFile(p, "r") as z:
                z.extract(path=td, targets=[name])
            target = (td / Path(name).as_posix()).resolve()
            if not target.is_file():
                for f in td.rglob("*"):
                    if f.is_file() and f.name.lower() == Path(name).name.lower():
                        target = f.resolve()
                        break
            if not target.is_file():
                return None
            if not str(target).startswith(str(td.resolve())):
                return None
            return _decode_readme_bytes(target.read_bytes())
        finally:
            shutil.rmtree(td, ignore_errors=True)

    return None


def install_zip_to_acus(archive_path: Path, acus_root: Path) -> list[str]:
    """
    将归档文件解压并写入 ACUS（不做谱面格式转换，仅按路径规则落位）。

    支持：zip、tar（含 .tar.gz / .bz2 / .xz）、7z（依赖 py7zr，见 requirements.txt）。
    下载到临时文件时请勿写死扩展名，以便按文件头正确识别。

    函数名保留 install_zip_to_acus 以兼容旧调用处（Swan 站 / 本地导入）。
    """
    p = archive_path.expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(str(p))

    if zipfile.is_zipfile(p):
        return _install_zip_core(p, acus_root)
    if tarfile.is_tarfile(p):
        return _install_tar_core(p, acus_root)

    try:
        import py7zr
    except ImportError:
        py7zr = None  # type: ignore[assignment]

    if py7zr is not None and py7zr.is_7zfile(p):
        return _install_7z_core(p, acus_root)
    if _is_7z_magic(p):
        raise ValueError(
            "检测到 7z 压缩包，但当前环境未安装 py7zr。\n"
            "请执行：pip install py7zr\n"
            "（随项目 requirements.txt 安装依赖即可）"
        )
    raise ValueError(
        "无法识别该压缩包格式（支持 zip、tar / .tar.gz 等、以及 7z）。\n"
        "若为 rar 等其它格式，请先在本机解压为上述格式再导入。"
    )
