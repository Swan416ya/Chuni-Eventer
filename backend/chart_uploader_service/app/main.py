from __future__ import annotations

import hashlib
import json
import os
import re
import time
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from dotenv import load_dotenv


load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Settings:
    upload_api_key: str
    storage_root: str
    max_upload_mb: int
    max_storage_gb: int
    max_zip_entries: int
    max_uncompressed_mb: int
    rate_limit_count: int
    rate_limit_window_sec: int
    cors_allow_origins: str


def load_settings() -> Settings:
    s = Settings(
        upload_api_key=_env("UPLOAD_API_KEY"),
        storage_root=_env("STORAGE_ROOT", "/data/chuni-charts"),
        max_upload_mb=int(_env("MAX_UPLOAD_MB", "100") or "100"),
        max_storage_gb=int(_env("MAX_STORAGE_GB", "20") or "20"),
        max_zip_entries=int(_env("MAX_ZIP_ENTRIES", "2000") or "2000"),
        max_uncompressed_mb=int(_env("MAX_UNCOMPRESSED_MB", "500") or "500"),
        rate_limit_count=int(_env("RATE_LIMIT_COUNT", "30") or "30"),
        rate_limit_window_sec=int(_env("RATE_LIMIT_WINDOW_SEC", "60") or "60"),
        cors_allow_origins=_env("CORS_ALLOW_ORIGINS", "*"),
    )
    if not s.upload_api_key:
        raise RuntimeError("Missing env: UPLOAD_API_KEY")
    return s


SETTINGS = load_settings()
app = FastAPI(title="Chuni Eventer Chart Uploader", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in SETTINGS.cors_allow_origins.split(",") if x.strip()] or ["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def slugify_name(s: str) -> str:
    raw = s.strip().lower()
    raw = re.sub(r"\s+", "-", raw)
    raw = re.sub(r"[^a-z0-9\-_\.]+", "-", raw)
    raw = raw.strip("-_.")
    return raw[:80] or "unknown-song"


def safe_music_id(v: int) -> int:
    if v <= 0:
        raise HTTPException(status_code=400, detail="music_id must be > 0")
    return v


def check_file(name: str, data: bytes) -> None:
    if not name.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail=f"{name}: only .zip is allowed")
    size_mb = len(data) / (1024 * 1024)
    if size_mb > SETTINGS.max_upload_mb:
        raise HTTPException(
            status_code=413,
            detail=f"{name}: file too large ({size_mb:.1f} MB > {SETTINGS.max_upload_mb} MB)",
        )


_ALLOWED_TOP_DIRS = {
    "chara",
    "ddsimage",
    "ddsmap",
    "music",
    "map",
    "maparea",
    "mapbonus",
    "event",
    "course",
    "reward",
    "cuefile",
    "nameplate",
    "trophy",
    "quest",
    "stage",
}
_RATE_BUCKET: Dict[str, List[float]] = {}


def _normalized_entry_name(name: str) -> str:
    return name.replace("\\", "/").strip()


def validate_package_zip(data: bytes) -> None:
    bio = BytesIO(data)
    try:
        zf = zipfile.ZipFile(bio, "r")
    except zipfile.BadZipFile as e:
        raise HTTPException(status_code=400, detail=f"invalid zip: {e}")
    with zf:
        infos = zf.infolist()
        if len(infos) > SETTINGS.max_zip_entries:
            raise HTTPException(status_code=400, detail=f"too many zip entries (> {SETTINGS.max_zip_entries})")
        total_uncompressed = 0
        has_music_xml = False
        for info in infos:
            n = _normalized_entry_name(info.filename)
            if not n or n.endswith("/"):
                continue
            if n.startswith("../") or "/../" in n:
                raise HTTPException(status_code=400, detail=f"invalid zip path: {n}")
            parts = n.split("/")
            if not parts:
                continue
            top = parts[0].lower()
            if top not in _ALLOWED_TOP_DIRS:
                raise HTTPException(status_code=400, detail=f"unsupported top folder in zip: {parts[0]}")
            total_uncompressed += max(0, int(info.file_size))
            if n.lower().endswith("/music.xml") and top == "music":
                has_music_xml = True
        if not has_music_xml:
            raise HTTPException(status_code=400, detail="zip must include at least one music/*/Music.xml")
        if total_uncompressed > SETTINGS.max_uncompressed_mb * 1024 * 1024:
            raise HTTPException(
                status_code=400,
                detail=f"zip uncompressed size too large (> {SETTINGS.max_uncompressed_mb} MB)",
            )


def _dir_size_bytes(root: Path) -> int:
    total = 0
    if not root.is_dir():
        return 0
    for p in root.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                continue
    return total


def ensure_storage_quota(incoming_bytes: int) -> None:
    used = _dir_size_bytes(storage_songs_root())
    cap = SETTINGS.max_storage_gb * 1024 * 1024 * 1024
    if used + incoming_bytes > cap:
        raise HTTPException(
            status_code=507,
            detail=f"storage quota exceeded ({used + incoming_bytes} > {cap})",
        )


def enforce_rate_limit(client_ip: str) -> None:
    now = time.time()
    win = max(1, SETTINGS.rate_limit_window_sec)
    lim = max(1, SETTINGS.rate_limit_count)
    lst = _RATE_BUCKET.get(client_ip, [])
    lst = [x for x in lst if now - x <= win]
    if len(lst) >= lim:
        raise HTTPException(
            status_code=429,
            detail=f"too many requests: {lim} uploads/{win}s",
        )
    lst.append(now)
    _RATE_BUCKET[client_ip] = lst


def storage_songs_root() -> Path:
    root = Path(SETTINGS.storage_root).expanduser().resolve()
    p = root / "songs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def song_dir_name(song_name: str, music_id: int) -> str:
    _ = music_id
    return slugify_name(song_name)


def song_dir_path(song_name: str, music_id: int) -> Path:
    return storage_songs_root() / song_dir_name(song_name, music_id)


def extract_meta_from_package_zip(data: bytes, fallback_song_name: str, fallback_music_id: int) -> Dict[str, Any]:
    song_name = fallback_song_name.strip()
    artist_name = ""
    charter_name = ""
    music_id = fallback_music_id
    bio = BytesIO(data)
    with zipfile.ZipFile(bio, "r") as zf:
        music_xml_entry = ""
        for n in zf.namelist():
            low = _normalized_entry_name(n).lower()
            if low.startswith("music/") and low.endswith("/music.xml"):
                music_xml_entry = n
                break
        if not music_xml_entry:
            return {
                "musicId": music_id,
                "songName": song_name or f"music_{music_id}",
                "artistName": artist_name,
                "charterName": charter_name,
            }
        try:
            raw = zf.read(music_xml_entry)
            root = ET.fromstring(raw)
            sid = (root.findtext("name/id") or "").strip()
            sname = (root.findtext("name/str") or "").strip()
            aname = (root.findtext("artistName/str") or "").strip()
            if sid.isdigit():
                music_id = int(sid)
            if sname:
                song_name = sname
            artist_name = aname
            charter_candidates = (
                "fumens/MusicFumenData/notesDesignerName/str",
                "fumens/MusicFumenData/designerName/str",
                "fumens/MusicFumenData/creator/str",
            )
            for cp in charter_candidates:
                for val in root.findall(cp):
                    text = (val.text or "").strip()
                    if text:
                        charter_name = text
                        break
                if charter_name:
                    break
        except Exception:
            pass
    return {
        "musicId": music_id,
        "songName": song_name or f"music_{music_id}",
        "artistName": artist_name,
        "charterName": charter_name,
    }


def read_meta(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def verify_api_key(client_key: Optional[str]) -> None:
    if not client_key or client_key != SETTINGS.upload_api_key:
        raise HTTPException(status_code=401, detail="invalid upload api key")


@app.get("/health")
def health() -> Dict[str, str]:
    return {"ok": "true", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/songs")
def list_songs() -> Dict[str, object]:
    songs_root = storage_songs_root()
    out: List[Dict[str, object]] = []
    for d in sorted((p for p in songs_root.iterdir() if p.is_dir()), key=lambda p: p.name.lower()):
        meta_path = d / "meta.json"
        m = read_meta(meta_path)
        package = d / "package.zip"
        out.append(
            {
                "songId": d.name,
                "musicId": int(m.get("musicId") or 0),
                "songName": str(m.get("songName") or d.name),
                "artistName": str(m.get("artistName") or ""),
                "charterName": str(m.get("charterName") or ""),
                "uploadedAtUtc": str(m.get("uploadedAtUtc") or ""),
                "hasPackageZip": package.is_file(),
            }
        )
    return {"ok": True, "songs": out}


@app.get("/download/{song_id}/{filename}")
def download_song_file(song_id: str, filename: str):
    if filename not in {"music.zip", "cueFile.zip", "meta.json", "package.zip"}:
        raise HTTPException(status_code=400, detail="invalid filename")
    safe_song = song_id.strip().replace("\\", "/")
    if "/" in safe_song or ".." in safe_song or not safe_song:
        raise HTTPException(status_code=400, detail="invalid song_id")
    file_path = storage_songs_root() / safe_song / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path=file_path, filename=filename)


@app.post("/upload")
async def upload_chart(
    request: Request,
    music_id: int = Form(...),
    song_name: str = Form(...),
    package_zip: UploadFile = File(...),
    uploader_name: str = Form(""),
    x_upload_key: Optional[str] = Header(None),
) -> Dict[str, Any]:
    verify_api_key(x_upload_key)
    client_ip = (request.client.host if request.client is not None else "").strip() or "unknown"
    enforce_rate_limit(client_ip)
    mid = safe_music_id(music_id)
    song_name_clean = (song_name or "").strip()
    if not song_name_clean:
        raise HTTPException(status_code=400, detail="song_name is required")

    package_bytes = await package_zip.read()
    check_file(package_zip.filename or "package.zip", package_bytes)
    validate_package_zip(package_bytes)
    ensure_storage_quota(len(package_bytes))

    pkg_meta = extract_meta_from_package_zip(package_bytes, song_name_clean, mid)
    mid_from_pkg = int(pkg_meta.get("musicId") or mid)
    if mid_from_pkg > 0:
        mid = mid_from_pkg
    song_name_effective = str(pkg_meta.get("songName") or song_name_clean).strip() or song_name_clean
    song_slug = slugify_name(song_name_effective)
    folder = song_dir_path(song_name_effective, mid)
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    package_sha256 = hashlib.sha256(package_bytes).hexdigest()
    package_path = folder / "package.zip"
    package_path.write_bytes(package_bytes)

    meta = {
        "musicId": mid,
        "songName": song_name_effective,
        "artistName": str(pkg_meta.get("artistName") or ""),
        "charterName": str(pkg_meta.get("charterName") or ""),
        "songSlug": song_slug,
        "uploadedAtUtc": now,
        "uploaderName": uploader_name.strip() or "anonymous-client",
        "packageZipSha256": package_sha256,
        "packageSize": len(package_bytes),
        "clientIp": client_ip,
    }
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "storageRoot": str(storage_songs_root()),
        "songId": folder.name,
        "folder": str(folder),
        "packageSize": len(package_bytes),
        "downloadPackageUrl": f"/download/{folder.name}/package.zip",
    }
