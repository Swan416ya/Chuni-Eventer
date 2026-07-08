from __future__ import annotations

import socket
import ssl
import time
import urllib.request
from dataclasses import dataclass
from urllib.error import HTTPError

PGKO_BASE_URL = "https://pgko.dev"
# API 端点在 api.pgko.dev 子域名（pgko.dev/api/* 改版后返回 SPA HTML）
# 下载端点 /download/{id} 仍在主站 pgko.dev
PGKO_API_BASE_URL = "https://api.pgko.dev"
_HTTP_MAX_RETRIES = 2  # total 3 attempts
_HTTP_RETRY_DELAYS = [1.0, 2.0]  # exponential backoff


@dataclass(frozen=True)
class PgkoSheetEntry:
    bundle_id: str
    title: str
    artist: str
    detail_url: str


@dataclass(frozen=True)
class PgkoSheetPage:
    entries: list[PgkoSheetEntry]
    next_cursor: str | None


def _http_get_bytes(url: str, timeout: float = 120.0) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        method="GET",
    )
    ctx = ssl.create_default_context()
    last_exc: Exception | None = None
    for attempt in range(_HTTP_MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.read()
        except HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            snippet = body[:400].strip()
            raise RuntimeError(
                f"HTTP {e.code} while GET {url}\n"
                f"reason: {e.reason}\n"
                f"response: {snippet or '<empty>'}"
            ) from e
        except (urllib.error.URLError, socket.timeout) as e:
            last_exc = e
            if attempt < _HTTP_MAX_RETRIES:
                time.sleep(_HTTP_RETRY_DELAYS[attempt])
                continue
            raise RuntimeError(
                f"网络错误 while GET {url}\n"
                f"error_type: {type(e).__name__}\n"
                f"reason: {e}\n"
            ) from e
    # unreachable, but keep the type checker happy
    assert last_exc is not None
    raise last_exc


def _http_get_json(url: str, timeout: float = 60.0):
    import json
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        method="GET",
    )
    ctx = ssl.create_default_context()
    last_exc: Exception | None = None
    for attempt in range(_HTTP_MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                raw = resp.read()
        except HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            snippet = body[:400].strip()
            raise RuntimeError(
                f"HTTP {e.code} while GET {url}\n"
                f"reason: {e.reason}\n"
                f"response: {snippet or '<empty>'}"
            ) from e
        except (urllib.error.URLError, socket.timeout) as e:
            last_exc = e
            if attempt < _HTTP_MAX_RETRIES:
                time.sleep(_HTTP_RETRY_DELAYS[attempt])
                continue
            raise RuntimeError(
                f"网络错误 while GET {url}\n"
                f"error_type: {type(e).__name__}\n"
                f"reason: {e}\n"
            ) from e
        # HTTP 请求成功，尝试解析 JSON
        try:
            return json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as e:
            last_exc = e
            if attempt < _HTTP_MAX_RETRIES:
                time.sleep(_HTTP_RETRY_DELAYS[attempt])
                continue
            # 最后一次重试仍失败，把 raw 内容片段放进报错
            snippet = raw.decode("utf-8", errors="replace")[:300].strip()
            raise RuntimeError(
                f"服务器返回了无效 JSON（重试 {_HTTP_MAX_RETRIES} 次仍失败，url={url}）\n"
                f"JSON 错误: {e}\n"
                f"已收到 {len(raw)} 字节响应\n"
                f"响应内容前 300 字符: {snippet or '<空响应>'}"
            ) from e
    assert last_exc is not None
    raise last_exc


def _bundle_download_api_url(bundle_id: str) -> str:
    return f"{PGKO_BASE_URL}/download/{bundle_id}"


def list_pgko_sheets(
    base_url: str = PGKO_BASE_URL,
    api_base_url: str = PGKO_API_BASE_URL,
) -> list[PgkoSheetEntry]:
    """
    从 pgko.dev 的网站 API 抓取乐曲列表（分页）：
    GET /api/bundles?cursor=...
    这是网站本身使用的数据源，符合“从该网站爬取列表”。
    api_base_url 指向 API 子域名（api.pgko.dev），base_url 指向主站（用于 detail_url）。
    """
    entries: list[PgkoSheetEntry] = []
    seen_ids: set[str] = set()
    cursor: str | None = None
    for _ in range(100):
        url = f"{api_base_url.rstrip('/')}/api/bundles"
        if cursor:
            url += f"?cursor={cursor}"
        data = _http_get_json(url)
        rows = data.get("bundles") if isinstance(data, dict) else None
        if not isinstance(rows, list) or not rows:
            break
        for b in rows:
            if not isinstance(b, dict):
                continue
            bid = str(b.get("id") or "").strip()
            if not bid or bid in seen_ids:
                continue
            seen_ids.add(bid)
            title = str(b.get("title") or "").strip() or f"bundle:{bid}"
            artist = str(b.get("artist") or "").strip()
            entries.append(
                PgkoSheetEntry(
                    bundle_id=bid,
                    title=title,
                    artist=artist,
                    detail_url=f"{base_url.rstrip('/')}/bundles/{bid}",
                )
            )
        nxt = data.get("nextCursor") if isinstance(data, dict) else None
        if not nxt:
            break
        cursor = str(nxt)
    return entries


def fetch_pgko_sheet_page(
    *,
    base_url: str = PGKO_BASE_URL,
    api_base_url: str = PGKO_API_BASE_URL,
    cursor: str | None = None,
) -> PgkoSheetPage:
    """按 cursor 拉取一页 bundles。"""
    url = f"{api_base_url.rstrip('/')}/api/bundles"
    if cursor:
        url += f"?cursor={cursor}"
    data = _http_get_json(url)
    rows = data.get("bundles") if isinstance(data, dict) else None
    out: list[PgkoSheetEntry] = []
    if isinstance(rows, list):
        for b in rows:
            if not isinstance(b, dict):
                continue
            bid = str(b.get("id") or "").strip()
            if not bid:
                continue
            title = str(b.get("title") or "").strip() or f"bundle:{bid}"
            artist = str(b.get("artist") or "").strip()
            out.append(
                PgkoSheetEntry(
                    bundle_id=bid,
                    title=title,
                    artist=artist,
                    detail_url=f"{base_url.rstrip('/')}/bundles/{bid}",
                )
            )
    nxt = data.get("nextCursor") if isinstance(data, dict) else None
    return PgkoSheetPage(entries=out, next_cursor=str(nxt) if nxt else None)


def resolve_pgko_download_from_bundle(
    entry: PgkoSheetEntry,
    base_url: str = PGKO_BASE_URL,
    api_base_url: str = PGKO_API_BASE_URL,
) -> tuple[str, str]:
    """
    点进乐曲后（bundle detail）再从网站推导下载链接：
    - detail: /api/bundles/{id}（走 api_base_url）
    - download: /download/{id}（走 base_url 主站）
    返回 (download_url, ext_guess)。
    """
    detail_api_url = f"{api_base_url.rstrip('/')}/api/bundles/{entry.bundle_id}"
    detail = _http_get_json(detail_api_url)
    ext = "ugc"
    try:
        songs = detail.get("songs") if isinstance(detail, dict) else None
        if isinstance(songs, list):
            for s in songs:
                if not isinstance(s, dict):
                    continue
                p = str(s.get("ugcPath") or "").strip().lower()
                if p.endswith(".mrgc"):
                    ext = "mrgc"
                    break
                if p.endswith(".ugc"):
                    ext = "ugc"
    except Exception:
        pass
    return _bundle_download_api_url(entry.bundle_id), ext


def download_pgko_sheet(download_url: str) -> bytes:
    return _http_get_bytes(download_url)

