from __future__ import annotations

import json
import ssl
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen


def _multipart_body(fields: dict[str, str], files: list[tuple[str, Path, str]]) -> tuple[bytes, str]:
    boundary = f"----ChuniEventerBoundary{uuid.uuid4().hex}"
    out = bytearray()
    for name, value in fields.items():
        out.extend(f"--{boundary}\r\n".encode("utf-8"))
        out.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        out.extend(value.encode("utf-8"))
        out.extend(b"\r\n")
    for field_name, path, content_type in files:
        filename = path.name
        out.extend(f"--{boundary}\r\n".encode("utf-8"))
        out.extend(
            (
                f'Content-Disposition: form-data; name="{field_name}"; '
                f'filename="{quote(filename)}"\r\n'
            ).encode("utf-8")
        )
        out.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        out.extend(path.read_bytes())
        out.extend(b"\r\n")
    out.extend(f"--{boundary}--\r\n".encode("utf-8"))
    return bytes(out), boundary


def upload_to_backend(
    *,
    api_base: str,
    api_key: str,
    music_id: int,
    song_name: str,
    music_zip: Path,
    cue_zip: Path | None,
    uploader_name: str = "",
) -> dict[str, object]:
    base = api_base.strip().rstrip("/")
    if not base:
        raise ValueError("api_base is required")
    if not api_key.strip():
        raise ValueError("api_key is required")
    fields = {
        "music_id": str(int(music_id)),
        "song_name": song_name.strip(),
        "uploader_name": uploader_name.strip() or "desktop-client",
    }
    files: list[tuple[str, Path, str]] = [("music_zip", music_zip, "application/zip")]
    if cue_zip is not None and cue_zip.is_file():
        files.append(("cue_zip", cue_zip, "application/zip"))
    body, boundary = _multipart_body(fields, files)
    req = Request(
        f"{base}/upload",
        data=body,
        method="POST",
        headers={
            "User-Agent": "Chuni-Eventer/1.0",
            "X-Upload-Key": api_key.strip(),
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    ctx = ssl.create_default_context()
    try:
        with urlopen(req, timeout=180.0, context=ctx) as resp:
            raw = resp.read()
    except HTTPError as e:
        msg = ""
        try:
            msg = e.read().decode("utf-8", errors="replace")
        except Exception:
            msg = ""
        raise RuntimeError(f"后端上传失败 HTTP {e.code}: {msg[:500]}") from e
    try:
        ret = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception as e:
        raise RuntimeError(f"后端返回无法解析的 JSON: {e}") from e
    if not isinstance(ret, dict):
        raise RuntimeError("后端返回格式异常")
    return ret


def list_backend_songs(*, api_base: str) -> list[dict[str, object]]:
    base = api_base.strip().rstrip("/")
    if not base:
        raise ValueError("api_base is required")
    req = Request(
        f"{base}/songs",
        method="GET",
        headers={"User-Agent": "Chuni-Eventer/1.0"},
    )
    ctx = ssl.create_default_context()
    try:
        with urlopen(req, timeout=60.0, context=ctx) as resp:
            raw = resp.read()
    except HTTPError as e:
        msg = ""
        try:
            msg = e.read().decode("utf-8", errors="replace")
        except Exception:
            msg = ""
        raise RuntimeError(f"读取后端歌单失败 HTTP {e.code}: {msg[:500]}") from e
    data = json.loads(raw.decode("utf-8", errors="replace"))
    if not isinstance(data, dict):
        raise RuntimeError("后端歌单返回格式异常")
    rows = data.get("songs")
    if not isinstance(rows, list):
        return []
    return [x for x in rows if isinstance(x, dict)]


def download_backend_song_file(*, api_base: str, song_id: str, filename: str, output_path: Path) -> None:
    base = api_base.strip().rstrip("/")
    if not base:
        raise ValueError("api_base is required")
    url = urljoin(base + "/", f"download/{quote(song_id)}/{quote(filename)}")
    req = Request(url, method="GET", headers={"User-Agent": "Chuni-Eventer/1.0"})
    ctx = ssl.create_default_context()
    try:
        with urlopen(req, timeout=180.0, context=ctx) as resp:
            data = resp.read()
    except HTTPError as e:
        msg = ""
        try:
            msg = e.read().decode("utf-8", errors="replace")
        except Exception:
            msg = ""
        raise RuntimeError(f"下载后端文件失败 HTTP {e.code}: {msg[:500]}") from e
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)
