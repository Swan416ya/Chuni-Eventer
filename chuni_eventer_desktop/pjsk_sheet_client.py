"""
从 Project SEKAI 公开资源获取 SUS 谱面文本。

逻辑对齐 PjskSUSPatcher / SusPatcher.js：元数据来自 sekai-master-db-diff，
谱面文件从 pjsek.ai CDN 拉取，失败则尝试 sekai.best（.txt）。

参考：https://github.com/Qrael/PjskSUSPatcher

两层数据源的可用性互相独立：

* **资源层**（SUS / 封面 / 长音频）：``assets.pjsek.ai`` 与 ``storage.sekai.best``；
* **曲目数据库层**（musics / musicDifficulties / musicVocals / 角色）：
  ``api.pjsek.ai`` 与 ``sekai-world.github.io/sekai-master-db-diff``
  —— 该仓库正是 sekai.best / Sekai Viewer 的数据源。直连在部分网络下不可达
  （实测：api.pjsek.ai 503，github.io / raw.githubusercontent 被断连），
  因此这里按序回退 GitHub 代理与 CDN 镜像，并把结果缓存到 ``.cache/pjsk_master/``。
"""

from __future__ import annotations

import json
import re
import ssl
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .acus_workspace import app_cache_dir

# 曲目数据库：官方 API（最快，但可能整体 503）与静态 JSON 镜像
PJSK_API_DB_BASE = "https://api.pjsek.ai/database/master"
PJSK_SEKAI_MASTER_JSON_BASE = "https://sekai-world.github.io/sekai-master-db-diff"
PJSK_MASTER_DB_RAW = "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/main"

# 静态 JSON 镜像候选（按序尝试；首个成功的会被记住）。
# 直接写 GitHub Pages / raw 在前，国内网络常常直接断连（每次白等一个超时），
# 故优先走实测可用的代理与 CDN。
PJSK_MASTER_JSON_MIRRORS: tuple[str, ...] = (
    "https://gcore.jsdelivr.net/gh/Sekai-World/sekai-master-db-diff@main",
    f"https://gh-proxy.com/{PJSK_MASTER_DB_RAW}",
    f"https://ghproxy.net/{PJSK_MASTER_DB_RAW}",
    "https://cdn.jsdelivr.net/gh/Sekai-World/sekai-master-db-diff@main",
    PJSK_SEKAI_MASTER_JSON_BASE,
    PJSK_MASTER_DB_RAW,
)

ASSET_PJSEKAI = "https://assets.pjsek.ai/file/pjsekai-assets"
ASSET_SEKAIBEST = "https://storage.sekai.best/sekai-jp-assets"

_USER_AGENT = "Chuni-Eventer/1.0"

# 曲目数据库本地缓存：网络全挂时仍能用最近一次的数据（转谱定数、下载目录都依赖它）
_MASTER_CACHE_TTL_SEC = 12 * 3600.0
_MASTER_JSON_TIMEOUT_SEC = 25.0
_master_base_lock = threading.Lock()
_master_base_ok: str | None = None


def pjsk_master_cache_dir() -> Path:
    return app_cache_dir() / "pjsk_master"


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


# --------------------------------------------------------------------------- 曲目数据库


def _ordered_master_json_bases() -> tuple[str, ...]:
    """把上次成功的镜像排到最前，避免每次都从不可达的域名开始等超时。"""
    with _master_base_lock:
        preferred = _master_base_ok
    if preferred and preferred in PJSK_MASTER_JSON_MIRRORS:
        return (preferred,) + tuple(b for b in PJSK_MASTER_JSON_MIRRORS if b != preferred)
    return PJSK_MASTER_JSON_MIRRORS


def _remember_master_json_base(base: str) -> None:
    global _master_base_ok
    with _master_base_lock:
        _master_base_ok = base


def _master_cache_path(name: str) -> Path:
    file_name = name if name.endswith(".json") else f"{name}.json"
    return pjsk_master_cache_dir() / file_name


def _read_master_cache(name: str, *, max_age_sec: float | None) -> Any | None:
    path = _master_cache_path(name)
    try:
        if not path.is_file():
            return None
        if max_age_sec is not None and (time.time() - path.stat().st_mtime) > max_age_sec:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_master_cache(name: str, data: Any) -> None:
    path = _master_cache_path(name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def load_sekai_master_json(name: str, *, timeout: float | None = None) -> Any:
    """读取 sekai-master-db-diff 的 ``<name>.json``（sekai.best / Sekai Viewer 的数据源）。

    顺序：本地缓存（12h 内直接用）→ 各镜像逐个尝试 → 过期缓存兜底。
    全部失败时抛 :class:`RuntimeError`（附每个镜像的失败原因）。
    """
    file_name = name if name.endswith(".json") else f"{name}.json"
    fresh = _read_master_cache(file_name, max_age_sec=_MASTER_CACHE_TTL_SEC)
    if fresh is not None:
        return fresh

    wait = float(_MASTER_JSON_TIMEOUT_SEC if timeout is None else timeout)
    errors: list[str] = []
    for base in _ordered_master_json_bases():
        url = f"{base.rstrip('/')}/{file_name}"
        try:
            data = _http_get_json(url, timeout=wait)
        except Exception as e:  # noqa: BLE001 — 逐个镜像降级
            errors.append(f"{base.rsplit('/', 1)[-1] or base}: {type(e).__name__}")
            continue
        _remember_master_json_base(base)
        _write_master_cache(file_name, data)
        return data

    stale = _read_master_cache(file_name, max_age_sec=None)
    if stale is not None:
        return stale
    raise RuntimeError(
        f"无法获取 PJSK 曲目数据库 {file_name}（已尝试 {len(_ordered_master_json_bases())} 个镜像）："
        + "; ".join(errors)
    )


def _http_get_bytes_chunked(
    url: str,
    *,
    timeout: float = 180.0,
    chunk_size: int = 65536,
    on_chunk: Callable[[int, int | None], None] | None = None,
) -> bytes:
    """
    流式下载；若响应含 Content-Length，则 on_chunk(current_bytes, total_bytes)；
    否则 on_chunk(current_bytes, None)。total 为解压后的完整长度（urllib 已透明解压 gzip）。
    """
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT},
        method="GET",
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        cl = resp.headers.get("Content-Length")
        total: int | None = None
        if cl:
            try:
                n = int(cl)
                if n > 0:
                    total = n
            except ValueError:
                pass
        buf = bytearray()
        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            buf.extend(chunk)
            if on_chunk:
                on_chunk(len(buf), total)
        return bytes(buf)


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


@dataclass(frozen=True)
class PjskVocalRow:
    """对应 PJSK `musicVocals` 的一条人声/伴奏版本（同一曲可有多条）。"""

    music_id: int
    assetbundle_name: str
    caption: str
    tooltip: str = ""


def _try_api_data_list(url: str, *, timeout: float = 60.0) -> list[dict[str, Any]] | None:
    try:
        data = _http_get_json(url, timeout=timeout)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return [x for x in data["data"] if isinstance(x, dict)]
    return None


_game_characters_by_id: dict[int, dict[str, Any]] | None = None
_outside_characters_by_id: dict[int, dict[str, Any]] | None = None


def _game_characters_by_id_map() -> dict[int, dict[str, Any]]:
    global _game_characters_by_id
    if _game_characters_by_id is not None:
        return _game_characters_by_id
    rows = _try_api_data_list(f"{PJSK_API_DB_BASE}/gameCharacters?$limit=500")
    if rows is None:
        raw = load_sekai_master_json("gameCharacters.json")
        rows = raw if isinstance(raw, list) else []
    m: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            m[int(row["id"])] = row
        except (KeyError, TypeError, ValueError):
            continue
    _game_characters_by_id = m
    return m


def _outside_characters_by_id_map() -> dict[int, dict[str, Any]]:
    global _outside_characters_by_id
    if _outside_characters_by_id is not None:
        return _outside_characters_by_id
    rows = _try_api_data_list(f"{PJSK_API_DB_BASE}/outsideCharacters?$limit=500")
    if rows is None:
        raw = load_sekai_master_json("outsideCharacters.json")
        rows = raw if isinstance(raw, list) else []
    m: dict[int, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            m[int(row["id"])] = row
        except (KeyError, TypeError, ValueError):
            continue
    _outside_characters_by_id = m
    return m


def _pjsk_character_display_name(ch: dict[str, Any]) -> str:
    n = (ch.get("name") or "").strip()
    if n:
        return n
    fn = (ch.get("firstName") or "").strip()
    gn = (ch.get("givenName") or "").strip()
    return f"{fn} {gn}".strip() or str(ch.get("id", ""))


def _resolve_vocal_character_entry(
    m: dict[str, Any],
    game: dict[int, dict[str, Any]],
    outside: dict[int, dict[str, Any]],
) -> dict[str, Any] | None:
    ctype = (m.get("characterType") or "").strip().lower()
    try:
        cid = int(m["characterId"])
    except (KeyError, TypeError, ValueError):
        return None
    if ctype in ("game_character", "gamecharacter", "game"):
        return game.get(cid)
    if ctype in ("outside_character", "outsidecharacter", "outside"):
        return outside.get(cid)
    return game.get(cid) or outside.get(cid)


def _vocal_cast_names(
    row: dict[str, Any],
    game: dict[int, dict[str, Any]],
    outside: dict[int, dict[str, Any]],
) -> list[str]:
    chars = row.get("characters")
    if not isinstance(chars, list):
        return []
    names: list[str] = []
    for m in chars:
        if not isinstance(m, dict):
            continue
        ent = _resolve_vocal_character_entry(m, game, outside)
        if ent:
            names.append(_pjsk_character_display_name(ent))
    return names


def _build_vocal_row(
    row: dict[str, Any],
    game: dict[int, dict[str, Any]],
    outside: dict[int, dict[str, Any]],
) -> PjskVocalRow | None:
    try:
        mid = int(row["musicId"])
    except (KeyError, TypeError, ValueError):
        return None
    ab = (row.get("assetbundleName") or "").strip()
    if not ab:
        return None
    cap = (row.get("caption") or "").strip()
    vt = (row.get("musicVocalType") or row.get("vocalType") or "").strip()
    cast = _vocal_cast_names(row, game, outside)
    cast_s = " / ".join(cast) if cast else ""

    if cast_s and cap:
        main_caption = f"{cast_s} — {cap}"
    elif cast_s:
        main_caption = cast_s
    elif cap:
        main_caption = cap
    elif vt:
        main_caption = f"{vt} · {ab}"
    else:
        main_caption = ab

    tip_lines: list[str] = [f"资源包名（assetbundleName）\n{ab}"]
    if vt:
        tip_lines.append(f"musicVocalType：{vt}")
    if cap and cap not in main_caption:
        tip_lines.append(f"caption：{cap}")
    if cast_s:
        tip_lines.append(f"角色解析：{cast_s}")

    return PjskVocalRow(
        music_id=mid,
        assetbundle_name=ab,
        caption=main_caption,
        tooltip="\n".join(tip_lines),
    )


def _try_music_vocals_from_api(music_id: int) -> list[dict[str, Any]] | None:
    url = f"{PJSK_API_DB_BASE}/musicVocals?musicId={int(music_id)}&$limit=200"
    try:
        data = _http_get_json(url, timeout=45.0)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return data["data"]
    return None


_music_vocals_json_cache: list[dict[str, Any]] | None = None


def _all_music_vocals_from_sekai_json() -> list[dict[str, Any]]:
    global _music_vocals_json_cache
    if _music_vocals_json_cache is None:
        rows = load_sekai_master_json("musicVocals.json")
        _music_vocals_json_cache = rows if isinstance(rows, list) else []
    return _music_vocals_json_cache


def load_music_vocals_for_music(music_id: int) -> list[PjskVocalRow]:
    """
    查询指定乐曲的所有人声版本（与 PjskSUSPatcher loadVocals 同源：API 优先，失败则 JSON）。

    列表文案：`characters` → gameCharacters/outsideCharacters 解析演唱者名，并拼接官方 `caption`
   （如「セカイver.」「バーチャル・シンガーver.」）；悬停可见 assetbundleName。
    """
    game = _game_characters_by_id_map()
    outside = _outside_characters_by_id_map()
    raw = _try_music_vocals_from_api(music_id)
    if raw is None:
        raw = [r for r in _all_music_vocals_from_sekai_json() if int(r.get("musicId", -1)) == int(music_id)]
    seen: set[str] = set()
    out: list[PjskVocalRow] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        v = _build_vocal_row(row, game, outside)
        if v is None or v.assetbundle_name in seen:
            continue
        seen.add(v.assetbundle_name)
        out.append(v)
    return out


def pjsk_long_music_download_urls(assetbundle_name: str) -> tuple[tuple[str, str], ...]:
    """
    完整曲长音频 URL 尝试顺序（与 SusPatcher.js 一致）。
    返回 (扩展名不含点, url) 元组列表。
    """
    ab = (assetbundle_name or "").strip()
    if not ab:
        return ()
    return (
        ("flac", f"{ASSET_PJSEKAI}/ondemand/music/long/{ab}/{ab}.flac"),
        ("wav", f"{ASSET_PJSEKAI}/ondemand/music/long/{ab}/{ab}.wav"),
        ("flac", f"{ASSET_SEKAIBEST}/music/long/{ab}/{ab}.flac"),
        ("mp3", f"{ASSET_SEKAIBEST}/music/long/{ab}/{ab}.mp3"),
    )


def download_pjsk_long_music(
    assetbundle_name: str,
    *,
    on_progress: Callable[[str, float | None], None] | None = None,
) -> tuple[bytes, str]:
    """
    依次尝试各镜像与格式，返回 (字节, 扩展名)。
    on_progress(说明文案, 已下比例 0~1 或 None 表示总长未知/不定)。
    """
    last_err: Exception | None = None
    for ext, url in pjsk_long_music_download_urls(assetbundle_name):
        mirror = "pjsek.ai" if "pjsek.ai" in url else "sekai.best"

        def chunk_cb(nread: int, ntotal: int | None) -> None:
            if not on_progress:
                return
            if ntotal and ntotal > 0:
                r = min(1.0, nread / float(ntotal))
                on_progress(
                    f"音频 .{ext}（{mirror}）— {r * 100:.1f}% "
                    f"（{nread // 1024} / {ntotal // 1024} KiB）",
                    r,
                )
            else:
                on_progress(
                    f"音频 .{ext}（{mirror}）— 已接收 {nread // 1024} KiB（无 Content-Length，不显示总百分比）",
                    None,
                )

        if on_progress:
            on_progress(f"音频 .{ext}（{mirror}）— 正在连接…", None)
        try:
            data = _http_get_bytes_chunked(url, timeout=300.0, on_chunk=chunk_cb)
            if len(data) >= 512:
                if on_progress:
                    on_progress(f"音频 .{ext} — 完成（共 {len(data) // 1024} KiB）", 1.0)
                return data, ext
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            if on_progress:
                on_progress(f"音频 .{ext}（{mirror}）失败，尝试下一镜像…", None)
            continue
    raise RuntimeError(
        f"无法下载人声资源 {assetbundle_name!r}（已尝试 flac/wav/mp3 全部镜像）。"
        f" 最后错误：{last_err!r}"
    ) from last_err


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
    rows = load_sekai_master_json("musics.json")
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
    rows = load_sekai_master_json("musicDifficulties.json")
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
    progress: Callable[[str, float | None], None] | None = None,
    vocal_assetbundle: str | None = None,
    vocal_caption: str | None = None,
    play_levels: dict[str, int] | None = None,
) -> Path:
    """只负责下载：封面、曲绘、可选完整音频与固定 PJSK 难度的 SUS 到 pjsk_cache/。

    这里**不做任何转谱/转音频**——转换与打包统一走
    :mod:`chuni_eventer_desktop.pjsk2chuni.pipeline`（乐曲页「新增 → PJSK 烤谱」）。

    ``play_levels``：``{pjsk 难度: 等级}``（1..38），存进 manifest 的 ``pjskPlayLevel``，
    供转谱对话框按「1..38 → 中二 1..15.5」的等比映射给默认定数。
    """
    from .pjsk2chuni import pipeline as pjsk_pipeline

    def p(msg: str, ratio: float | None = None) -> None:
        if progress:
            progress(msg, ratio)

    base = pjsk_cache_root(acus_root)
    base.mkdir(parents=True, exist_ok=True)
    root = pjsk_song_cache_dir(acus_root, music_id)
    root.mkdir(parents=True, exist_ok=True)
    sus_dir = root / "sus"
    audio_dir = root / "audio"
    sus_dir.mkdir(exist_ok=True)

    p("下载封面 / 曲绘 …", None)
    cover, illust = download_jacket_images(assetbundle_name)
    if cover:
        (root / "封面.png").write_bytes(cover)
    else:
        p("（未获取到封面 PNG）", None)
    if illust:
        (root / "曲绘.png").write_bytes(illust)

    av = {x.strip().lower() for x in available_pjsk_difficulties}
    manifest_slots: list[dict[str, object]] = []
    audio_manifest: dict[str, object] | None = None

    vab = (vocal_assetbundle or "").strip()
    if vab:
        p(f"下载完整音频（{vab}）…", None)
        audio_dir.mkdir(exist_ok=True)

        def _audio_p(msg: str, ratio: float | None) -> None:
            p(msg, ratio)

        audio_bytes, ext = download_pjsk_long_music(vab, on_progress=_audio_p)
        stem = sanitize_filename_stem(vab, max_len=120)
        audio_path = audio_dir / f"{stem}.{ext}"
        audio_path.write_bytes(audio_bytes)
        audio_rel = audio_path.relative_to(root).as_posix()
        audio_manifest: dict[str, object] = {
            "assetbundleName": vab,
            "caption": (vocal_caption or "").strip() or vab,
            "file": audio_rel,
            "format": ext,
        }
        audio_manifest["chuniPipelineNote"] = (
            "转谱与音频打包在「乐曲页 → 新增 → PJSK 烤谱」中执行"
            "（上游 pjsk2chuni 语义转换 + PenguinTools option build）。"
        )

    for pj in pjsk_pipeline.PJSK_CHUNI_DOWNLOAD_ORDER:
        if pj not in av:
            continue
        slot = pjsk_pipeline.chuni_slot_name_for_pjsk(pj)
        if slot is None:
            continue
        p(f"下载谱面 {pj} …", None)
        try:
            text = fetch_chart_sus(music_id, pj)
        except Exception:
            if pj == "append":
                p("append 谱面不可用（视为无该难度），已跳过。", None)
                continue
            raise
        (sus_dir / f"{pj}.sus").write_text(text, encoding="utf-8")
        slot_entry: dict[str, object] = {
            "pjskDifficulty": pj,
            "chuniSlot": slot,
            "susFile": f"sus/{pj}.sus",
        }
        pl = (play_levels or {}).get(pj)
        try:
            if pl is not None:
                slot_entry["pjskPlayLevel"] = int(pl)
        except (TypeError, ValueError):
            pass
        manifest_slots.append(slot_entry)

    readme = (
        "本目录为 PJSK 资源缓存（与 ACUS 同级的 pjsk_cache 下，不在 ACUS 内）。\n"
        "转谱/打包请用软件内「乐曲页 → 新增 → PJSK 烤谱」，不要手工把本目录当 ACUS 使用。\n"
        "- sus/ ：原始 SUS（normal / hard / expert / master / append，按曲目实际存在项下载）。\n"
        "  manifest 里的 pjskPlayLevel 是该难度的 PJSK 等级（1..38），转谱时按等比映射给默认定数。\n"
        "- audio/ ：若选择了人声版本，则为完整曲长音频（flac/wav/mp3，视镜像而定）；\n"
        "  转谱时才由软件解码为 48k WAV、实测前导静音并交给 PenguinTools 生成 ACB·AWB。\n"
        "- chuni_build/ ：转谱时生成的 UMIGURI 工程目录（有 options.json/*.ugc 等，可事后排查）。\n"
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
    }
    if audio_manifest is not None:
        manifest["audio"] = audio_manifest
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return root
