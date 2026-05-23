"""游戏数据包内资源路径解析与 cue 音频导出。"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from .acus_workspace import cue_export_scratch_dir
from .pjsk_audio_chuni import CHUNITHM_HCA_KEY


def pack_path(game_root: Path, pack_relpath: str) -> Path:
    return (game_root.expanduser().resolve() / pack_relpath.replace("\\", "/")).resolve()


def catalog_source_packs(game_root: Path, source: str) -> list[Path]:
    """catalog 行里的 source 可能是「包A; 包B」合并串，逐个解析为有效目录。"""
    raw = str(source or "").strip()
    if not raw:
        return []
    parts = [s.strip() for s in raw.split(";") if s.strip()]
    if not parts:
        parts = [raw]
    out: list[Path] = []
    seen: set[str] = set()
    for rel in parts:
        if rel in seen:
            continue
        seen.add(rel)
        try:
            pack = pack_path(game_root, rel)
        except OSError:
            continue
        if pack.is_dir():
            out.append(pack)
    return out


def asset_in_pack(pack: Path, relpath: str) -> Path:
    rel = relpath.strip().replace("\\", "/")
    return (pack / rel).resolve()


def _find_cue_dir_in_pack(pack: Path, cue_id: int) -> Path | None:
    if cue_id <= 0:
        return None
    cue_dir = pack / "cueFile" / f"cueFile{cue_id:06d}"
    if (cue_dir / "CueFile.xml").is_file():
        return cue_dir
    root = pack / "cueFile"
    if not root.is_dir():
        return None
    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        xf = p / "CueFile.xml"
        if not xf.is_file():
            continue
        try:
            r = ET.parse(xf).getroot()
            raw = (r.findtext("name/id") or "").strip()
            if raw.isdigit() and int(raw) == cue_id:
                return p
        except Exception:
            continue
    return None


def _cue_id_from_music_xml(xml_path: Path) -> int | None:
    if not xml_path.is_file():
        return None
    try:
        r = ET.parse(xml_path).getroot()
        raw = (r.findtext("cueFileName/id") or "").strip()
        if raw.isdigit():
            return int(raw)
    except Exception:
        pass
    return None


def _resolve_cue_id_for_row(*, game_root: Path, row: dict) -> int | None:
    cue_id = row.get("cue_id")
    if cue_id is not None:
        try:
            cid = int(cue_id)
            if cid > 0:
                return cid
        except (TypeError, ValueError):
            pass
    xml_rel = str(row.get("xml_relpath") or "").strip()
    if not xml_rel:
        return None
    for pack in catalog_source_packs(game_root, str(row.get("source") or "")):
        cid = _cue_id_from_music_xml(asset_in_pack(pack, xml_rel))
        if cid is not None:
            return cid
    return None


def _dds_paths_from_dds_image_xml(dds_xml: Path) -> list[Path]:
    try:
        r = ET.parse(dds_xml).getroot()
    except Exception:
        return []
    out: list[Path] = []
    for tag in ("ddsFile0", "ddsFile1", "ddsFile2"):
        rel = (r.findtext(f"{tag}/path") or "").strip()
        if not rel:
            continue
        p = asset_in_pack(dds_xml.parent, rel)
        if p.is_file():
            out.append(p)
    return out


def resolve_catalog_xml_path(*, game_root: Path, row: dict) -> Path | None:
    """根据 catalog 行的 source + xml_relpath 定位磁盘上的 XML。"""
    xml_rel = str(row.get("xml_relpath") or "").strip()
    if not xml_rel:
        return None
    for pack in catalog_source_packs(game_root, str(row.get("source") or "")):
        xp = asset_in_pack(pack, xml_rel)
        if xp.is_file():
            return xp
    return None


def set_default_have_in_xml(xml_path: Path, *, default_have: bool) -> None:
    """写入 Music / Trophy / NamePlate 等 XML 的 defaultHave（true=强制解锁）。"""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    el = root.find("defaultHave")
    if el is None:
        el = ET.SubElement(root, "defaultHave")
    el.text = "true" if default_have else "false"
    try:
        ET.indent(root, space="  ")
    except Exception:
        pass
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)


def resolve_chara_portrait_dds_in_pack(
    pack: Path,
    *,
    chara_id: int,
    image_key: str = "",
) -> list[Path]:
    """按 ddsImage{id} 目录或 name/str 键解析三联立绘 DDS。"""
    if chara_id > 0:
        dds_xml = pack / "ddsImage" / f"ddsImage{chara_id:06d}" / "DDSImage.xml"
        if dds_xml.is_file():
            paths = _dds_paths_from_dds_image_xml(dds_xml)
            if paths:
                return paths
    key = (image_key or "").strip()
    if not key:
        return []
    for xml in sorted(pack.glob("ddsImage/**/DDSImage.xml")):
        try:
            r = ET.parse(xml).getroot()
            name = (r.findtext("name/str") or "").strip()
            if name != key:
                continue
            return _dds_paths_from_dds_image_xml(xml)
        except Exception:
            continue
    return []


def parse_chara_variant_slots(xml_path: Path) -> dict[int, tuple[int, str]]:
    """变体槽位 → (立绘 numeric id, defaultImages/image.str 键)。"""
    variant_map: dict[int, tuple[int, str]] = {}
    if not xml_path.is_file():
        return variant_map
    try:
        root = ET.parse(xml_path).getroot()
    except Exception:
        return variant_map
    base_id_raw = (root.findtext("name/id") or "").strip()
    default_key = (root.findtext("defaultImages/str") or "").strip()
    try:
        base_id = int(base_id_raw)
    except ValueError:
        base_id = -1
    if base_id >= 0:
        variant_map[base_id % 10] = (base_id, default_key)
    for i in range(1, 10):
        sec = root.find(f"addImages{i}")
        if sec is None:
            continue
        if (sec.findtext("changeImg") or "").strip().lower() != "true":
            continue
        vid_raw = (sec.findtext("image/id") or "").strip()
        vkey = (sec.findtext("image/str") or "").strip()
        if vid_raw.isdigit():
            variant_map[i] = (int(vid_raw), vkey)
    return variant_map


def resolve_chara_master_xml(*, game_root: Path, row: dict) -> tuple[Path, Path] | None:
    """定位主 Chara.xml 及其所在数据包（含 addImages 变体）。"""
    xml_rel = str(row.get("xml_relpath") or "").strip()
    try:
        cid = int(row.get("id") or 0)
    except (TypeError, ValueError):
        cid = 0
    base_raw = (cid // 10) * 10 if cid > 0 else 0
    for pack in catalog_source_packs(game_root, str(row.get("source") or "")):
        if base_raw > 0:
            master = pack / "chara" / f"chara{base_raw:06d}" / "Chara.xml"
            if master.is_file():
                return pack, master
        if xml_rel:
            xp = asset_in_pack(pack, xml_rel)
            if xp.is_file():
                return pack, xp
    return None


def list_chara_variants(*, game_root: Path, row: dict) -> list[dict]:
    """
    列出角色全部变体（仅元数据，不含 DDS 路径；预览时再按需解析）。
    返回 dict: slot, chara_id, image_key, master_xml
    """
    resolved = resolve_chara_master_xml(game_root=game_root, row=row)
    if resolved is None:
        key = str(row.get("default_image_key") or "").strip()
        try:
            cid = int(row.get("id") or 0)
        except (TypeError, ValueError):
            cid = 0
        return [{"slot": 0, "chara_id": cid, "image_key": key, "pack": None, "master_xml": None}]
    pack, master_xml = resolved
    slots = parse_chara_variant_slots(master_xml)
    if not slots:
        key = str(row.get("default_image_key") or "").strip()
        try:
            cid = int(row.get("id") or 0)
        except (TypeError, ValueError):
            cid = 0
        return [{"slot": 0, "chara_id": cid, "image_key": key, "pack": pack, "master_xml": master_xml}]
    out: list[dict] = []
    for slot in sorted(slots.keys()):
        cid, key = slots[slot]
        out.append(
            {
                "slot": slot,
                "chara_id": cid,
                "image_key": key,
                "pack": pack,
                "master_xml": master_xml,
            }
        )
    return out


def resolve_chara_portrait_dds_files(*, game_root: Path, row: dict) -> list[Path]:
    """通过 Chara.defaultImages/str 在数据包内匹配 ddsImage 名称（默认变体）。"""
    variants = list_chara_variants(game_root=game_root, row=row)
    if not variants:
        return []
    v0 = variants[0]
    pack = v0.get("pack")
    if pack is None:
        key = str(v0.get("image_key") or "").strip()
        if not key:
            return []
        for p in catalog_source_packs(game_root, str(row.get("source") or "")):
            paths = resolve_chara_portrait_dds_in_pack(p, chara_id=int(v0.get("chara_id") or 0), image_key=key)
            if paths:
                return paths
        return []
    return resolve_chara_portrait_dds_in_pack(
        pack,
        chara_id=int(v0.get("chara_id") or 0),
        image_key=str(v0.get("image_key") or ""),
    )


def resolve_chara_variant_dds_files(*, variant: dict) -> list[Path]:
    """按需解析单个变体的三联 DDS 路径。"""
    pack = variant.get("pack")
    if pack is None:
        return []
    return resolve_chara_portrait_dds_in_pack(
        pack,
        chara_id=int(variant.get("chara_id") or 0),
        image_key=str(variant.get("image_key") or ""),
    )


def resolve_row_image_dds(*, game_root: Path, row: dict) -> Path | None:
    """名牌 / 称号等：image/path 相对 XML 所在目录。"""
    xml_rel = str(row.get("xml_relpath") or "").strip()
    img_rel = str(row.get("image_relpath") or "").strip()
    if not xml_rel or not img_rel:
        return None
    for pack in catalog_source_packs(game_root, str(row.get("source") or "")):
        xml_path = asset_in_pack(pack, xml_rel)
        dds = (xml_path.parent / img_rel).resolve()
        if dds.is_file():
            return dds
    return None


def resolve_music_jacket_dds(*, game_root: Path, row: dict) -> Path | None:
    xml_rel = str(row.get("xml_relpath") or "").strip()
    jacket_rel = str(row.get("jacket_relpath") or "").strip()
    if not xml_rel or not jacket_rel:
        return None
    for pack in catalog_source_packs(game_root, str(row.get("source") or "")):
        xml_path = asset_in_pack(pack, xml_rel)
        dds = (xml_path.parent / jacket_rel).resolve()
        if dds.is_file():
            return dds
    return None


def resolve_music_cue_dir(*, game_root: Path, row: dict) -> Path | None:
    cid = _resolve_cue_id_for_row(game_root=game_root, row=row)
    if cid is None:
        return None
    for pack in catalog_source_packs(game_root, str(row.get("source") or "")):
        found = _find_cue_dir_in_pack(pack, cid)
        if found is not None:
            return found
    return None


def _ffmpeg_exe() -> str | None:
    from .external_tools import TOOL_FFMPEG, resolve_tool_path

    p = resolve_tool_path(TOOL_FFMPEG, None)
    if p is not None and p.is_file():
        return str(p)
    return shutil.which("ffmpeg")


def export_cue_dir_to_ogg(cue_dir: Path, output_ogg: Path) -> None:
    """将 cueFile 目录内 AWB 第一条音轨导出为 OGG（需 PyCriCodecsEx；OGG 需 ffmpeg）。"""
    cue_dir = cue_dir.expanduser().resolve()
    out = Path(output_ogg).expanduser()
    if not out.is_absolute():
        out = out.resolve()
    else:
        try:
            out = out.resolve()
        except OSError:
            pass
    if out.suffix.lower() != ".ogg":
        out = out.with_suffix(".ogg")

    cue_xml = cue_dir / "CueFile.xml"
    if not cue_xml.is_file():
        raise FileNotFoundError(f"缺少 CueFile.xml：{cue_xml}")
    root = ET.parse(cue_xml).getroot()
    awb_rel = (root.findtext("awbFile/path") or "").strip()
    if not awb_rel:
        raise FileNotFoundError("CueFile.xml 中未找到 awbFile/path")
    awb_path = (cue_dir / awb_rel).resolve()
    if not awb_path.is_file():
        raise FileNotFoundError(f"找不到 AWB：{awb_path}")

    try:
        from PyCriCodecsEx.awb import AWB
        from PyCriCodecsEx.hca import HCACodec
    except ImportError as e:
        raise RuntimeError("需要 PyCriCodecsEx 才能解码游戏音频。请执行：pip install PyCriCodecsEx") from e

    awb = AWB(awb_path.read_bytes())
    if awb.numfiles < 1:
        raise RuntimeError("AWB 内无音轨")
    hca_bytes = awb.get_file_at(0)
    if not isinstance(hca_bytes, bytes) or not hca_bytes:
        raise RuntimeError("无法读取 AWB 音轨数据")

    scratch_root = cue_export_scratch_dir()

    with tempfile.TemporaryDirectory(
        prefix="chuni_cue_export_",
        dir=str(scratch_root),
        ignore_cleanup_errors=True,
    ) as td:
        wav_path = Path(td) / "track.wav"
        tmp_ogg = Path(td) / "track.ogg"
        hc = HCACodec(hca_bytes, key=CHUNITHM_HCA_KEY)
        try:
            wav_path.write_bytes(hc.decode())
        finally:
            del hc

        ff = _ffmpeg_exe()
        if ff is None:
            raise RuntimeError("未找到 ffmpeg，无法转换为 OGG。请安装 ffmpeg 或在【外部工具】中配置。")
        r = subprocess.run(
            [ff, "-y", "-i", str(wav_path), "-c:a", "libvorbis", "-q:a", "6", str(tmp_ogg)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if r.returncode != 0:
            raise RuntimeError(r.stderr or r.stdout or "ffmpeg 转 OGG 失败")
        if not tmp_ogg.is_file():
            raise RuntimeError("ffmpeg 未生成 OGG 文件")

        parent = out.parent
        if str(parent) not in ("", "."):
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise OSError(f"无法创建导出目录：{parent}") from e
        shutil.copy2(tmp_ogg, out)
