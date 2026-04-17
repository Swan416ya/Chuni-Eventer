from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
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
    cors_allow_origins: str


def load_settings() -> Settings:
    s = Settings(
        upload_api_key=_env("UPLOAD_API_KEY"),
        storage_root=_env("STORAGE_ROOT", "/data/chuni-charts"),
        max_upload_mb=int(_env("MAX_UPLOAD_MB", "100") or "100"),
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


def storage_songs_root() -> Path:
    root = Path(SETTINGS.storage_root).expanduser().resolve()
    p = root / "songs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def song_dir_name(song_name: str, music_id: int) -> str:
    return f"{slugify_name(song_name)}_{music_id}"


def song_dir_path(song_name: str, music_id: int) -> Path:
    return storage_songs_root() / song_dir_name(song_name, music_id)


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
        music = d / "music.zip"
        cue = d / "cueFile.zip"
        out.append(
            {
                "songId": d.name,
                "musicId": int(m.get("musicId") or 0),
                "songName": str(m.get("songName") or d.name),
                "uploadedAtUtc": str(m.get("uploadedAtUtc") or ""),
                "hasMusicZip": music.is_file(),
                "hasCueZip": cue.is_file(),
            }
        )
    return {"ok": True, "songs": out}


@app.get("/download/{song_id}/{filename}")
def download_song_file(song_id: str, filename: str):
    if filename not in {"music.zip", "cueFile.zip", "meta.json"}:
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
    music_id: int = Form(...),
    song_name: str = Form(...),
    music_zip: UploadFile = File(...),
    cue_zip: Optional[UploadFile] = File(None),
    uploader_name: str = Form(""),
    x_upload_key: Optional[str] = Header(None),
) -> Dict[str, Any]:
    verify_api_key(x_upload_key)
    mid = safe_music_id(music_id)
    song_name_clean = (song_name or "").strip()
    if not song_name_clean:
        raise HTTPException(status_code=400, detail="song_name is required")

    music_bytes = await music_zip.read()
    check_file(music_zip.filename or "music.zip", music_bytes)

    cue_bytes = b""
    has_cue = cue_zip is not None
    if cue_zip is not None:
        cue_bytes = await cue_zip.read()
        check_file(cue_zip.filename or "cue.zip", cue_bytes)

    song_slug = slugify_name(song_name_clean)
    folder = song_dir_path(song_name_clean, mid)
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    music_sha256 = hashlib.sha256(music_bytes).hexdigest()
    cue_sha256 = hashlib.sha256(cue_bytes).hexdigest() if has_cue else ""
    music_path = folder / "music.zip"
    music_path.write_bytes(music_bytes)
    cue_path = folder / "cueFile.zip"
    if has_cue:
        cue_path.write_bytes(cue_bytes)
    elif cue_path.exists():
        cue_path.unlink(missing_ok=True)

    meta = {
        "musicId": mid,
        "songName": song_name_clean,
        "songSlug": song_slug,
        "uploadedAtUtc": now,
        "uploaderName": uploader_name.strip() or "anonymous-client",
        "musicZipSha256": music_sha256,
        "cueZipSha256": cue_sha256,
        "hasCueZip": has_cue,
    }
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "storageRoot": str(storage_songs_root()),
        "songId": folder.name,
        "folder": str(folder),
        "hasCueZip": has_cue,
        "musicSize": len(music_bytes),
        "cueSize": len(cue_bytes) if has_cue else 0,
        "downloadMusicUrl": f"/download/{folder.name}/music.zip",
        "downloadCueUrl": f"/download/{folder.name}/cueFile.zip" if has_cue else "",
    }
