"""
从 Project SEKAI 公开资源获取 SUS 谱面文本。

逻辑对齐 PjskSUSPatcher / SusPatcher.js：元数据来自 sekai-master-db-diff，
谱面文件从 pjsek.ai CDN 拉取，失败则尝试 sekai.best（.txt）。

参考：https://github.com/Qrael/PjskSUSPatcher
"""

from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.request
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 不在界面暴露；与 SusPatcher.js 一致
PJSK_SEKAI_MASTER_JSON_BASE = "https://sekai-world.github.io/sekai-master-db-diff"
PJSK_API_DB_BASE = "https://api.pjsek.ai/database/master"
ASSET_PJSEKAI = "https://assets.pjsek.ai/file/pjsekai-assets"
ASSET_SEKAIBEST = "https://storage.sekai.best/sekai-jp-assets"

_USER_AGENT = "Chuni-Eventer/1.0"


def pjsk_cache_root(acus_root: Path) -> Path:
    """
    PJSK 下载缓存根目录：与 ACUS **同级** 的 `pjsk_cache`（不写入 ACUS 目录内）。
    例：…/游戏根/ACUS → …/游戏根/pjsk_cache
    """
    return (acus_root.resolve().parent / "pjsk_cache").resolve()


def _http_get_json(url: str, timeout: float = 90.0) -> Any:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
        method="GET",
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8", errors="replace"))


def _http_get_text(url: str, timeout: float = 90.0) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT},
        method="GET",
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="replace").replace("\r", "")


def _http_get_bytes(url: str, timeout: float = 90.0) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT},
        method="GET",
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read()


def jacket_png_urls(assetbundle_name: str) -> tuple[str, ...]:
    """封面用 PNG；与 SusPatcher.js 一致。"""
    ab = (assetbundle_name or "").strip()
    if not ab:
        return ()
    return (
        f"{ASSET_PJSEKAI}/startapp/music/jacket/{ab}/{ab}.png",
        f"{ASSET_SEKAIBEST}/music/jacket/{ab}/{ab}.png",
    )


def download_jacket_images(assetbundle_name: str) -> tuple[bytes | None, bytes | None]:
    """
    返回 (封面 png 字节, 曲绘 png 字节)。
    依次尝试各镜像；若两镜像内容不同则曲绘用第二份，否则曲绘与封面相同。
    """
    urls = jacket_png_urls(assetbundle_name)
    if not urls:
        return None, None
    got: list[bytes] = []
    for url in urls:
        try:
            data = _http_get_bytes(url)
            if len(data) >= 32:
                got.append(data)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
            continue
    if not got:
        return None, None
    cover = got[0]
    illust = got[1] if len(got) > 1 and got[1] != got[0] else cover
    return cover, illust


def _score_path_segment(song_id: int) -> str:
    """与 JS `("000" + id).slice(-4)` 一致。"""
    return ("000" + str(int(song_id)))[-4:]


def chart_asset_urls(song_id: int, music_difficulty: str) -> tuple[str, ...]:
    d = music_difficulty.strip().lower()
    seg = _score_path_segment(song_id)
    return (
        f"{ASSET_PJSEKAI}/startapp/music/music_score/{seg}_01/{d}",
        f"{ASSET_SEKAIBEST}/music/music_score/{seg}_01/{d}.txt",
    )


def fetch_chart_sus(song_id: int, music_difficulty: str) -> str:
    """下载单难度 SUS 文本；依次尝试 pjsekai 与 sekaibest。"""
    last_err: Exception | None = None
    for url in chart_asset_urls(song_id, music_difficulty):
        try:
            return _http_get_text(url)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
    raise RuntimeError(
        f"无法下载乐曲 {song_id} 的 {music_difficulty} 谱面（已尝试全部镜像）。"
        f" 最后错误：{last_err!r}"
    ) from last_err


@dataclass(frozen=True)
class PjskMusicRow:
    music_id: int
    title: str
    composer: str
    assetbundle_name: str


@dataclass(frozen=True)
class PjskDifficultyRow:
    music_difficulty: str
    play_level: int


def _musics_from_sekai_json(rows: list[dict[str, Any]]) -> list[PjskMusicRow]:
    out: list[PjskMusicRow] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            mid = int(row["id"])
        except (KeyError, TypeError, ValueError):
            continue
        title = (row.get("title") or "").strip()
        composer = (row.get("composer") or "").strip()
        ab = (row.get("assetbundleName") or row.get("assetbundle_name") or "").strip()
        out.append(
            PjskMusicRow(
                music_id=mid,
                title=title,
                composer=composer,
                assetbundle_name=ab,
            )
        )
    out.sort(key=lambda r: (r.title.lower(), r.music_id))
    return out


def _try_musics_from_api() -> list[dict[str, Any]] | None:
    url = f"{PJSK_API_DB_BASE}/musics?$limit=100000"
    try:
        data = _http_get_json(url, timeout=20.0)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return data["data"]
    return None


def load_musics_catalog() -> list[PjskMusicRow]:
    """曲目列表：优先 pjsekai API，失败则用 sekai-master-db-diff 的 musics.json。"""
    api_rows = _try_musics_from_api()
    if api_rows is not None:
        return _musics_from_sekai_json(api_rows)
    url = f"{PJSK_SEKAI_MASTER_JSON_BASE}/musics.json"
    rows = _http_get_json(url)
    if not isinstance(rows, list):
        raise ValueError("musics.json 格式异常：应为数组。")
    return _musics_from_sekai_json(rows)


def _difficulties_index(rows: list[dict[str, Any]]) -> dict[int, list[PjskDifficultyRow]]:
    by_music: dict[int, list[PjskDifficultyRow]] = defaultdict(list)
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            mid = int(row["musicId"])
        except (KeyError, TypeError, ValueError):
            continue
        diff = (row.get("musicDifficulty") or "").strip().lower()
        if not diff:
            continue
        try:
            pl = int(row.get("playLevel") or 0)
        except (TypeError, ValueError):
            pl = 0
        by_music[mid].append(PjskDifficultyRow(music_difficulty=diff, play_level=pl))
    order = {"easy": 0, "normal": 1, "hard": 2, "expert": 3, "master": 4, "append": 5}

    def sort_key(d: PjskDifficultyRow) -> tuple[int, str]:
        return (order.get(d.music_difficulty, 99), d.music_difficulty)

    for mid in list(by_music.keys()):
        by_music[mid].sort(key=sort_key)
    return dict(by_music)


def _try_difficulties_from_api() -> list[dict[str, Any]] | None:
    url = f"{PJSK_API_DB_BASE}/musicDifficulties?$limit=200000"
    try:
        data = _http_get_json(url, timeout=25.0)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return data["data"]
    return None


def load_difficulties_index() -> dict[int, list[PjskDifficultyRow]]:
    api_rows = _try_difficulties_from_api()
    if api_rows is not None:
        return _difficulties_index(api_rows)
    url = f"{PJSK_SEKAI_MASTER_JSON_BASE}/musicDifficulties.json"
    rows = _http_get_json(url)
    if not isinstance(rows, list):
        raise ValueError("musicDifficulties.json 格式异常：应为数组。")
    return _difficulties_index(rows)


_WIN_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename_stem(s: str, *, max_len: int = 80) -> str:
    t = _WIN_INVALID.sub("_", (s or "").strip())
    t = t.rstrip(" .")
    if not t:
        return "untitled"
    return t[:max_len]


def pjsk_song_cache_dir(acus_root: Path, music_id: int) -> Path:
    return (pjsk_cache_root(acus_root) / f"pjsk_{int(music_id):04d}").resolve()


def save_pjsk_bundle_to_cache(
    acus_root: Path,
    *,
    music_id: int,
    title: str,
    composer: str,
    assetbundle_name: str,
    available_pjsk_difficulties: set[str],
    progress: Callable[[str], None] | None = None,
) -> Path:
    """下载封面、曲绘与固定 PJSK 难度的 SUS 到 ACUS 同级 pjsk_cache/；c2s 见 sus_to_c2s。"""
    from . import sus_to_c2s as s2c

    def p(msg: str) -> None:
        if progress:
            progress(msg)

    base = pjsk_cache_root(acus_root)
    base.mkdir(parents=True, exist_ok=True)
    root = pjsk_song_cache_dir(acus_root, music_id)
    root.mkdir(parents=True, exist_ok=True)
    sus_dir = root / "sus"
    chuni_dir = root / "chuni"
    sus_dir.mkdir(exist_ok=True)
    chuni_dir.mkdir(exist_ok=True)

    p("下载封面 / 曲绘 …")
    cover, illust = download_jacket_images(assetbundle_name)
    if cover:
        (root / "封面.png").write_bytes(cover)
    else:
        p("（未获取到封面 PNG）")
    if illust:
        (root / "曲绘.png").write_bytes(illust)

    av = {x.strip().lower() for x in available_pjsk_difficulties}
    manifest_slots: list[dict[str, object]] = []

    for pj in s2c.PJSK_CHUNI_DOWNLOAD_ORDER:
        if pj not in av:
            continue
        slot = s2c.chuni_slot_name_for_pjsk(pj)
        if slot is None:
            continue
        p(f"下载谱面 {pj} …")
        try:
            text = fetch_chart_sus(music_id, pj)
        except Exception:
            if pj == "append":
                p("append 谱面不可用（视为无该难度），已跳过。")
                continue
            raise
        (sus_dir / f"{pj}.sus").write_text(text, encoding="utf-8")
        c2s_bytes = s2c.try_convert_sus_to_c2s_bytes(text)
        c2s_name = f"{slot}.c2s"
        c2s_rel: str | None = None
        if c2s_bytes is not None:
            (chuni_dir / c2s_name).write_bytes(c2s_bytes)
            c2s_rel = f"chuni/{c2s_name}"
        manifest_slots.append(
            {
                "pjskDifficulty": pj,
                "chuniSlot": slot,
                "susFile": f"sus/{pj}.sus",
                "c2sFile": c2s_rel,
            }
        )

    readme = (
        "本目录为 PJSK 资源缓存（与 ACUS 同级的 pjsk_cache 下，不在 ACUS 内）。\n"
        "完成 SUS→中二 c2s 并整理为游戏所需结构后，再复制进 ACUS；在此之前请勿把本目录当 ACUS 使用。\n"
        "- sus/ ：原始 SUS（normal / hard / expert / master / append，按曲目实际存在项下载）。\n"
        "- chuni/ ：中二 c2s（转换逻辑未实现时为空）。\n"
        "- 与 CHUNITHM 槽位对应：normal→BASIC(Easy)，hard→ADVANCED，expert→EXPERT，"
        "master→MASTER；有 append 时→ULTIMA，无 append 则无 ULTIMA 对应文件。\n"
        "详见 manifest.json。\n"
    )
    (root / "说明.txt").write_text(readme, encoding="utf-8")

    manifest: dict[str, object] = {
        "musicId": music_id,
        "title": title,
        "composer": composer,
        "assetbundleName": assetbundle_name,
        "cacheRoot": str(base),
        "outsideAcus": True,
        "slots": manifest_slots,
        "c2sConversionImplemented": False,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return root
