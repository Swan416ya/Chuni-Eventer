from __future__ import annotations

import base64
import json
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError


GITHUB_API_BASE = "https://api.github.com"


@dataclass(frozen=True)
class GithubChartEntry:
    path: str
    size: int
    sha: str

    @property
    def name(self) -> str:
        p = Path(self.path)
        return p.name or self.path


def _headers(token: str | None = None) -> dict[str, str]:
    h = {
        "User-Agent": "Chuni-Eventer/1.0",
        "Accept": "application/vnd.github+json",
    }
    tk = (token or "").strip()
    if tk:
        h["Authorization"] = f"Bearer {tk}"
    return h


def _http_json(url: str, *, token: str | None = None, timeout: float = 60.0) -> object:
    req = urllib.request.Request(url, headers=_headers(token), method="GET")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read()
    except HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        snippet = body[:500].strip() or "<empty>"
        raise RuntimeError(f"GitHub API 请求失败 HTTP {e.code}: {snippet}") from e
    return json.loads(raw.decode("utf-8", errors="replace"))


def _http_json_request(
    *,
    url: str,
    method: str,
    token: str | None = None,
    payload: dict[str, object] | None = None,
    timeout: float = 60.0,
) -> object:
    data: bytes | None = None
    headers = _headers(token)
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, headers=headers, data=data, method=method.upper())
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read()
    except HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        snippet = body[:500].strip() or "<empty>"
        raise RuntimeError(f"GitHub API 请求失败 HTTP {e.code}: {snippet}") from e
    if not raw.strip():
        return {}
    return json.loads(raw.decode("utf-8", errors="replace"))


def _http_bytes(url: str, timeout: float = 120.0) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Chuni-Eventer/1.0"},
        method="GET",
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read()


def _split_repo(repo: str) -> tuple[str, str]:
    s = (repo or "").strip().strip("/")
    if "/" not in s:
        raise ValueError("仓库格式应为 owner/repo。")
    owner, name = s.split("/", 1)
    owner = owner.strip()
    name = name.strip()
    if not owner or not name:
        raise ValueError("仓库格式应为 owner/repo。")
    return owner, name


def list_github_chart_files(
    *,
    repo: str,
    branch: str = "charts",
    prefix: str = "charts",
    token: str | None = None,
) -> list[GithubChartEntry]:
    owner, name = _split_repo(repo)
    tree_url = f"{GITHUB_API_BASE}/repos/{owner}/{name}/git/trees/{urllib.parse.quote(branch, safe='')}?recursive=1"
    data = _http_json(tree_url, token=token)
    rows = data.get("tree") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("GitHub 返回的树结构格式异常。")
    base = prefix.strip().strip("/")
    out: list[GithubChartEntry] = []
    for it in rows:
        if not isinstance(it, dict):
            continue
        if str(it.get("type") or "").strip().lower() != "blob":
            continue
        p = str(it.get("path") or "").strip()
        if not p:
            continue
        if base:
            if p != base and not p.startswith(base + "/"):
                continue
        out.append(
            GithubChartEntry(
                path=p,
                size=int(it.get("size") or 0),
                sha=str(it.get("sha") or ""),
            )
        )
    out.sort(key=lambda x: x.path.lower())
    return out


def download_github_chart_bytes(*, repo: str, branch: str, file_path: str) -> bytes:
    owner, name = _split_repo(repo)
    safe_path = "/".join(urllib.parse.quote(seg, safe="") for seg in file_path.split("/"))
    raw_url = f"https://raw.githubusercontent.com/{owner}/{name}/{urllib.parse.quote(branch, safe='')}/{safe_path}"
    return _http_bytes(raw_url)


def upload_file_to_github_charts(
    *,
    repo: str,
    branch: str = "charts",
    target_path: str,
    local_file: Path,
    token: str,
    message: str | None = None,
) -> None:
    tk = (token or "").strip()
    if not tk:
        raise ValueError("上传需要 GitHub Token（repo contents:write 权限）。")
    if not local_file.is_file():
        raise ValueError(f"文件不存在：{local_file}")
    owner, name = _split_repo(repo)
    _ensure_branch_exists(repo=repo, branch=branch, token=tk)
    api_path = "/".join(urllib.parse.quote(seg, safe="") for seg in target_path.split("/"))
    content_api = f"{GITHUB_API_BASE}/repos/{owner}/{name}/contents/{api_path}"
    sha: str | None = None
    ref_q = urllib.parse.quote(branch, safe="")
    try:
        existing = _http_json(f"{content_api}?ref={ref_q}", token=tk)
        if isinstance(existing, dict):
            v = existing.get("sha")
            if isinstance(v, str) and v.strip():
                sha = v.strip()
    except RuntimeError as e:
        if "HTTP 404" not in str(e):
            raise
    raw = local_file.read_bytes()
    body: dict[str, object] = {
        "message": message or f"chore(charts): upload {target_path}",
        "content": base64.b64encode(raw).decode("ascii"),
        "branch": branch,
    }
    if sha:
        body["sha"] = sha
    _http_json_request(
        url=content_api,
        method="PUT",
        token=tk,
        payload=body,
        timeout=120.0,
    )


def _ensure_branch_exists(*, repo: str, branch: str, token: str) -> None:
    owner, name = _split_repo(repo)
    b = urllib.parse.quote(branch, safe="")
    ref_url = f"{GITHUB_API_BASE}/repos/{owner}/{name}/git/ref/heads/{b}"
    try:
        _http_json(ref_url, token=token)
        return
    except RuntimeError as e:
        if "HTTP 404" not in str(e):
            raise
    repo_url = f"{GITHUB_API_BASE}/repos/{owner}/{name}"
    info = _http_json(repo_url, token=token)
    if not isinstance(info, dict):
        raise RuntimeError("读取仓库信息失败。")
    default_branch = str(info.get("default_branch") or "main").strip() or "main"
    db = urllib.parse.quote(default_branch, safe="")
    default_ref = _http_json(f"{GITHUB_API_BASE}/repos/{owner}/{name}/git/ref/heads/{db}", token=token)
    if not isinstance(default_ref, dict):
        raise RuntimeError("读取默认分支引用失败。")
    obj = default_ref.get("object")
    if not isinstance(obj, dict):
        raise RuntimeError("默认分支引用缺少 object。")
    sha = str(obj.get("sha") or "").strip()
    if not sha:
        raise RuntimeError("默认分支引用缺少 sha。")
    _http_json_request(
        url=f"{GITHUB_API_BASE}/repos/{owner}/{name}/git/refs",
        method="POST",
        token=token,
        payload={"ref": f"refs/heads/{branch}", "sha": sha},
    )
