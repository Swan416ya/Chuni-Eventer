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
        raw = _http_get_json(f"{PJSK_SEKAI_MASTER_JSON_BASE}/gameCharacters.json", timeout=120.0)
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
        raw = _http_get_json(f"{PJSK_SEKAI_MASTER_JSON_BASE}/outsideCharacters.json", timeout=120.0)
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
        url = f"{PJSK_SEKAI_MASTER_JSON_BASE}/musicVocals.json"
        rows = _http_get_json(url, timeout=120.0)
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
    progress: Callable[[str, float | None], None] | None = None,
    vocal_assetbundle: str | None = None,
    vocal_caption: str | None = None,
) -> Path:
    """下载封面、曲绘、可选完整音频与固定 PJSK 难度的 SUS 到 pjsk_cache/。
    SUS→c2s 在「转写 ACUS」时执行，不在此处生成 chuni/*.c2s。

    完整音频：与 PjskSUSPatcher 一致，来自 `musicVocals` 的 `assetbundleName` 与 long 音频 URL。
    若已安装 ffmpeg 与 PyCriCodecsEx，会在同目录下额外生成去掉前约 9 秒后的 48k WAV，
    以及 ``chuni_cue/cueFileXXXXXX/`` 下的 ``musicXXXX.acb`` / ``.awb``（逻辑对齐
    [PenguinTools MusicConverter](https://github.com/Foahh/PenguinTools/blob/main/PenguinTools.Core/Media/MusicConverter.cs)）。
    """
    from . import pjsk_audio_chuni as pjsk_ac
    from . import sus_to_c2s as s2c

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
        p("生成中二用 WAV / ACB·AWB（若环境齐全）…", None)
        try:
            chuni_extra = pjsk_ac.try_pipeline_pjsk_audio_to_chuni(
                src_audio=audio_path,
                music_id=music_id,
                cache_root=root,
                trim_leading_sec=pjsk_ac.PJSK_AUDIO_TRIM_LEADING_SEC,
                on_log=lambda m: p(m, None),
            )
        except Exception as ex:
            chuni_extra = None
            p(f"中二音频管线跳过：{ex}", None)
        if chuni_extra:
            audio_manifest["chuni"] = chuni_extra
        else:
            audio_manifest["chuniPipelineNote"] = (
                "可选：安装 ffmpeg（PATH）与 pip install PyCriCodecsEx，"
                "并保留 chuni_eventer_desktop/data/dummy.acb 模板，即可自动生成 ACB/AWB。"
            )

    for pj in s2c.PJSK_CHUNI_DOWNLOAD_ORDER:
        if pj not in av:
            continue
        slot = s2c.chuni_slot_name_for_pjsk(pj)
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
        manifest_slots.append(
            {
                "pjskDifficulty": pj,
                "chuniSlot": slot,
                "susFile": f"sus/{pj}.sus",
            }
        )

    readme = (
        "本目录为 PJSK 资源缓存（与 ACUS 同级的 pjsk_cache 下，不在 ACUS 内）。\n"
        "完成 SUS→中二 c2s 并整理为游戏所需结构后，再复制进 ACUS；在此之前请勿把本目录当 ACUS 使用。\n"
        "- sus/ ：原始 SUS（normal / hard / expert / master / append，按曲目实际存在项下载）。\n"
        "- audio/ ：若选择了人声版本，则为完整曲长音频（flac/wav/mp3，视镜像而定）；"
        "环境齐全时另有 48k 修剪 WAV 与 chuni_cue/ 下 ACB·AWB。\n"
        "- chuni/ ：转写进 ACUS 时由程序调用 PenguinTools.CLI 从 SUS 生成 c2s 后写入。\n"
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
        "c2sConversionImplemented": True,
    }
    if audio_manifest is not None:
        manifest["audio"] = audio_manifest
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return root
