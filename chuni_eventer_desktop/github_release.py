from __future__ import annotations

import json
import re
import ssl
import urllib.request
from dataclasses import dataclass
from urllib.error import HTTPError, URLError

_REPO = "Swan416ya/Chuni-Eventer"
_USER_AGENT = "Chuni-Eventer/1.0"

_PENGUIN_TOOLS_CLI_AOT_ZIP_RE = re.compile(
    r"^PenguinTools\.CLI\.v\d+(?:\.\d+)*\.AOT\.zip$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GitHubReleaseAsset:
    name: str
    download_url: str


@dataclass(frozen=True)
class GitHubReleaseDetails:
    tag_name: str
    release_url: str
    assets: tuple[GitHubReleaseAsset, ...]


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


def _github_latest_release_api(repo: str) -> str:
    return f"https://api.github.com/repos/{repo}/releases/latest"


def fetch_github_release_latest(repo: str, *, timeout: float = 12.0) -> GitHubReleaseDetails:
    req = urllib.request.Request(
        _github_latest_release_api(repo),
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
        release_url = f"https://github.com/{repo}/releases/latest"

    assets: list[GitHubReleaseAsset] = []
    for item in data.get("assets") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        url = str(item.get("browser_download_url") or "").strip()
        if name and url:
            assets.append(GitHubReleaseAsset(name=name, download_url=url))

    return GitHubReleaseDetails(tag_name=tag, release_url=release_url, assets=tuple(assets))


def fetch_latest_release(*, timeout: float = 12.0) -> LatestReleaseInfo:
    details = fetch_github_release_latest(_REPO, timeout=timeout)
    return LatestReleaseInfo(
        tag_name=details.tag_name,
        version_tuple=parse_version_tuple(details.tag_name),
        release_url=details.release_url,
    )


def penguin_tools_cli_aot_zip_url_from_tag(tag: str) -> str:
    """按 ChuniPingu/PenguinTools Release 命名规则构造 Native AOT 包 URL。"""
    tag = tag.strip()
    if not tag:
        raise ValueError("tag 为空")
    if not tag.startswith("v"):
        tag = f"v{tag}"
    return (
        f"https://github.com/ChuniPingu/PenguinTools/releases/download/{tag}/"
        f"PenguinTools.CLI.{tag}.AOT.zip"
    )


def resolve_penguin_tools_cli_download_url(release: GitHubReleaseDetails) -> str:
    """从 latest release 解析 ``PenguinTools.CLI.v*.AOT.zip`` 下载地址。"""
    for asset in release.assets:
        if _PENGUIN_TOOLS_CLI_AOT_ZIP_RE.match(asset.name):
            return asset.download_url
    return penguin_tools_cli_aot_zip_url_from_tag(release.tag_name)
