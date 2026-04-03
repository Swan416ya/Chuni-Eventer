from __future__ import annotations

import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from PyQt6.QtWidgets import QWidget

from .acus_scan import MusicItem
from .dds_convert import convert_dds_to_png, convert_to_bc3_dds

# 与游戏侧封面缩略图常见规格一致：先规范为方形再压 BC3
JACKET_BC3_EDGE = 300


def _default_jacket_filename(music_id: int) -> str:
    return f"CHU_UI_Jacket_{int(music_id):04d}.dds"


def resolve_jacket_dds_path(item: MusicItem) -> Path:
    """Music.xml 同目录下的封面 DDS 绝对路径。"""
    mdir = item.xml_path.parent.resolve()
    rel = (item.jacket_path or "").strip()
    name = rel if rel else _default_jacket_filename(item.name.id)
    out = (mdir / name).resolve()
    if not str(out).startswith(str(mdir)):
        raise ValueError(f"封面路径超出乐曲目录：{name!r}")
    return out


def ensure_jaket_file_in_music_xml(xml_path: Path, filename: str) -> None:
    """若缺少 jaketFile/path，写入相对文件名（与现有 Music.xml 结构一致）。"""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    jf = root.find("jaketFile")
    if jf is None:
        jf = ET.SubElement(root, "jaketFile")
    p = jf.find("path")
    if p is None:
        p = ET.SubElement(jf, "path")
    p.text = filename
    ET.indent(root, space="  ")  # type: ignore[attr-defined]
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)


def _prepare_square_jacket_png(
    source: Path, edge: int, tool_path: Path | None
) -> Path:
    """
    将位图或 DDS 解码为 RGBA，居中裁剪填满后缩放到 edge×edge，写入临时 PNG。
    调用方负责删除返回路径。
    """
    src = source.resolve()
    sq = (edge, edge)
    if src.suffix.lower() == ".dds":
        fd, tmp_dec = tempfile.mkstemp(suffix="_jacket_dec.png")
        os.close(fd)
        dec_path = Path(tmp_dec)
        try:
            convert_dds_to_png(tool_path=tool_path, input_dds=src, output_png=dec_path)
            with Image.open(dec_path) as im0:
                base = ImageOps.exif_transpose(im0).convert("RGBA").copy()
        finally:
            dec_path.unlink(missing_ok=True)
    else:
        try:
            with Image.open(src) as im0:
                base = ImageOps.exif_transpose(im0).convert("RGBA").copy()
        except UnidentifiedImageError as e:
            raise RuntimeError(f"无法识别图片格式：{src}") from e
        except OSError as e:
            raise RuntimeError(f"无法读取图片：{src}\n{e}") from e

    fitted = ImageOps.fit(base, sq, method=Image.Resampling.LANCZOS)

    fd2, out_tmp = tempfile.mkstemp(suffix="_jacket_300.png")
    os.close(fd2)
    out_path = Path(out_tmp)
    fitted.save(out_path, "PNG")
    return out_path


def apply_music_jacket_image(
    *,
    item: MusicItem,
    source: Path,
    tool_path: Path | None,
    progress_parent: QWidget | None = None,
) -> Path:
    """
    将本地图片或 DDS 先规范为 JACKET_BC3_EDGE×JACKET_BC3_EDGE，再写入 BC3 DDS。
    若 Music.xml 未配置 jaketFile/path，则使用 CHU_UI_Jacket_{id:04d}.dds 并回写 XML。

    progress_parent：若传入则在后台线程编码 BC3 并显示进度，避免打包版主线程长时间无响应。
    """
    src = source.expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(str(src))

    mdir = item.xml_path.parent.resolve()
    rel = (item.jacket_path or "").strip()
    if rel:
        out = (mdir / rel).resolve()
        if not str(out).startswith(str(mdir)):
            raise ValueError(f"封面路径非法：{rel!r}")
    else:
        fname = _default_jacket_filename(item.name.id)
        out = (mdir / fname).resolve()

    tmp_png: Path | None = None
    try:
        tmp_png = _prepare_square_jacket_png(src, JACKET_BC3_EDGE, tool_path)
        if progress_parent is not None:
            from .ui.dds_progress import run_bc3_jobs_with_progress

            ok, err = run_bc3_jobs_with_progress(
                parent=progress_parent,
                tool_path=tool_path,
                jobs=[(tmp_png, out)],
                title="正在生成封面 DDS",
            )
            if not ok:
                raise RuntimeError(err or "DDS 编码失败")
        else:
            convert_to_bc3_dds(
                tool_path=tool_path, input_image=tmp_png, output_dds=out
            )
    finally:
        if tmp_png is not None:
            tmp_png.unlink(missing_ok=True)

    if not rel:
        ensure_jaket_file_in_music_xml(item.xml_path, out.name)

    return out
