from __future__ import annotations

import json
import re
import ssl
import urllib.request
from dataclasses import dataclass
from urllib.error import HTTPError, URLError

_REPO = "Swan416ya/Chuni-Eventer"
_LATEST_API = f"https://api.github.com/repos/{_REPO}/releases/latest"
_USER_AGENT = "Chuni-Eventer/1.0"


@dataclass(frozen=True)
class LatestReleaseInfo:
    tag_name: str
    version_tuple: tuple[int, ...]
    release_url: str


def parse_version_tuple(text: str) -> tuple[int, ...]:
    """从 tag / 版本字符串提取可比较的整数元组（如 v0.7.1 -> (0, 7, 1)）。"""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if m:
        return tuple(int(x) for x in m.groups())
    parts = [int(x) for x in re.findall(r"\d+", text)]
    return tuple(parts) if parts else (0,)


def compare_version_tuple(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    """Return -1 if a<b, 0 if equal, 1 if a>b."""
    n = max(len(a), len(b))
    ap = a + (0,) * (n - len(a))
    bp = b + (0,) * (n - len(b))
    if ap < bp:
        return -1
    if ap > bp:
        return 1
    return 0


def fetch_latest_release(*, timeout: float = 12.0) -> LatestReleaseInfo:
    req = urllib.request.Request(
        _LATEST_API,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
        method="GET",
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read()
    except HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        raise RuntimeError(f"GitHub API HTTP {e.code}: {body or e.reason}") from e
    except URLError as e:
        raise RuntimeError(f"无法连接 GitHub：{e.reason}") from e

    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise RuntimeError("GitHub 返回了无效的 JSON") from e

    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        raise RuntimeError("未在 latest release 响应中找到 tag_name")

    release_url = str(data.get("html_url") or "").strip()
    if not release_url:
        release_url = f"https://github.com/{_REPO}/releases/latest"

    return LatestReleaseInfo(
        tag_name=tag,
        version_tuple=parse_version_tuple(tag),
        release_url=release_url,
    )
