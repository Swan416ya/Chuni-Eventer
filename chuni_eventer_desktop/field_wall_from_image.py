from __future__ import annotations

from dataclasses import dataclass
import shutil
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .dds_convert import ingest_to_bc3_dds


def _xml_text(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _normalize_field_wall_size(image: Image.Image) -> Image.Image:
    """规整为 640x480：按宽度缩放到 640 保持纵横比，顶部裁切或底部补齐到 480。"""
    image = image.convert("RGBA")
    w, h = image.size
    if w <= 0 or h <= 0:
        raise ValueError("贴图尺寸无效。")
    if w != 640:
        new_h = max(1, int(round(h * (640.0 / float(w)))))
        image = image.resize((640, new_h), Image.Resampling.LANCZOS)
    w2, h2 = image.size
    if h2 >= 480:
        return image.crop((0, 0, 640, 480))
    # 高度不足时底部补齐
    out = Image.new("RGBA", (640, 480))
    out.paste(image, (0, 0))
    if h2 > 0:
        last_row = image.crop((0, h2 - 1, 640, h2)).resize((640, 480 - h2), Image.Resampling.NEAREST)
        out.paste(last_row, (0, h2))
    return out


@dataclass(frozen=True)
class FieldWallCreateOptions:
    image_source: Path
    wall_name: str = "フィールドウォール0001"


def create_field_wall_from_image(
    *,
    acus_root: Path,
    tool_path: Path | None,
    opts: FieldWallCreateOptions,
) -> Path:
    """
    生成 ACUS/ddsFieldWall/ddsFieldWall0001/ 目录（覆盖式）。
    - 转 DDS: CHU_UI_Fieldwall_0001.dds (640x480 BC3)
    - 写 XML: DDSFieldWall.xml
    返回 XML 路径。
    """
    dir_path = acus_root / "ddsFieldWall" / "ddsFieldWall0001"
    dds_path = dir_path / "CHU_UI_Fieldwall_0001.dds"
    xml_path = dir_path / "DDSFieldWall.xml"

    # 覆盖模式：先删旧目录
    if dir_path.exists():
        shutil.rmtree(dir_path)
    dir_path.mkdir(parents=True)

    wall_name = (opts.wall_name or "").strip() or "フィールドウォール0001"

    try:
        # 1. 读图片 + 规整 640x480
        src = opts.image_source.expanduser().resolve()
        if not src.is_file():
            raise FileNotFoundError(f"图片文件不存在：{src}")
        with Image.open(src) as im0:
            normalized = _normalize_field_wall_size(im0)

        # 2. 保存临时 PNG 供 DDS 转换
        import tempfile
        with tempfile.NamedTemporaryFile(prefix="fieldwall_norm_", suffix=".png", delete=False) as tf:
            norm_tmp = Path(tf.name)
        normalized.save(norm_tmp, "PNG")

        # 3. 转 BC3 DDS
        ingest_to_bc3_dds(
            tool_path=tool_path,
            input_path=norm_tmp,
            output_dds=dds_path,
        )

        # 4. 写 DDSFieldWall.xml
        xml = f"""<?xml version="1.0" encoding="utf-8"?>
<DDSFieldWallData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>ddsFieldWall0001</dataName>
  <name>
    <id>1</id>
    <str>{_xml_text(wall_name)}</str>
    <data />
  </name>
  <netOpenName>
    <id>2800</id>
    <str>v2_45 00_0</str>
    <data />
  </netOpenName>
  <disableFlag>false</disableFlag>
  <image>
    <path>CHU_UI_Fieldwall_0001.dds</path>
  </image>
  <defaultHave>true</defaultHave>
  <explainText />
</DDSFieldWallData>
"""
        xml_path.write_text(xml, encoding="utf-8")
        return xml_path

    except Exception:
        shutil.rmtree(dir_path, ignore_errors=True)
        raise
    finally:
        if 'norm_tmp' in dir():
            norm_tmp.unlink(missing_ok=True)


__all__ = ["FieldWallCreateOptions", "create_field_wall_from_image"]