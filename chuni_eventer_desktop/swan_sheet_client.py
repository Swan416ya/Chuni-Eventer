from __future__ import annotations

import json
import ssl
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

# 固定 SwanSite 后端根地址（列表与下载均走此域名，不在界面或配置中修改）
SWAN_SHEET_API_BASE_URL = "https://api.swan416.top"


@dataclass(frozen=True)
class SheetListEntry:
    content_id: int
    title: str
    music_name: str
    artist_name: str
    package_url: str


def _join_url(base: str, path: str) -> str:
    b = (base or "").strip().rstrip("/")
    p = path if path.startswith("/") else "/" + path
    return urljoin(b + "/", p.lstrip("/"))


def _http_get_json(url: str, timeout: float = 60.0) -> Any:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Chuni-Eventer/1.0", "Accept": "application/json"},
        method="GET",
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        raw = resp.read()
        ctype = (resp.headers.get("Content-Type") or "").lower()
    if not raw.strip():
        raise ValueError("服务器返回空内容（请检查 API 基址是否指向后端，而不是纯前端页面）。")
    if "json" not in ctype and raw[:1] not in (b"[", b"{"):
        raise ValueError(
            "响应不是 JSON。若站点根路径是前端 SPA，请在设置里把「铺面网站 API」改为实际后端地址。"
        )
    return json.loads(raw.decode("utf-8", errors="replace"))


def _http_get_bytes(url: str, timeout: float = 120.0) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Chuni-Eventer/1.0"},
        method="GET",
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read()


def list_downloadable_sheets(base_url: str) -> list[SheetListEntry]:
    """
    GET /api/contents?contentType=SHEET — SwanSite CoreContentController.
    仅保留带 packageUrl 的谱面条目。
    """
    url = _join_url(base_url, "/api/contents?contentType=SHEET")
    data = _http_get_json(url)
    if not isinstance(data, list):
        raise ValueError("谱面列表格式异常：期望 JSON 数组。")
    out: list[SheetListEntry] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        cid = row.get("id")
        try:
            content_id = int(cid)
        except (TypeError, ValueError):
            continue
        ctype = (row.get("contentType") or row.get("content_type") or "").strip()
        if ctype and ctype.upper() != "SHEET":
            continue
        sheet = row.get("sheet")
        if not isinstance(sheet, dict):
            continue
        pkg = (sheet.get("packageUrl") or sheet.get("package_url") or "").strip()
        if not pkg:
            continue
        title = (row.get("title") or "").strip()
        music_name = (sheet.get("musicName") or sheet.get("music_name") or "").strip()
        artist_name = (sheet.get("artistName") or sheet.get("artist_name") or "").strip()
        out.append(
            SheetListEntry(
                content_id=content_id,
                title=title,
                music_name=music_name or title,
                artist_name=artist_name,
                package_url=pkg,
            )
        )
    out.sort(key=lambda e: (e.music_name.lower(), e.content_id))
    return out


def download_sheet_archive(base_url: str, content_id: int) -> bytes:
    """
    GET /api/contents/{id}/download — 302 到 packageUrl；urllib 会跟随重定向。
    """
    url = _join_url(base_url, f"/api/contents/{content_id}/download")
    return _http_get_bytes(url)
