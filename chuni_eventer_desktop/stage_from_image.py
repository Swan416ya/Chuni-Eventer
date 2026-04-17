from __future__ import annotations

from dataclasses import dataclass
import tempfile
from pathlib import Path

from .dds_convert import ingest_to_bc3_dds
from .stage_afb_convert import StageAfbToolError, build_stage_afb_from_image
from PIL import Image, UnidentifiedImageError


def _xml_text(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _stage_overlay_png_path() -> Path:
    return Path(__file__).resolve().parent / "static" / "tool" / "stage.png"


def _prepare_stage_preview_png(source: Path) -> Path:
    """
    预览 DDS 生成规则（按需求）：
    1) 输入必须是 1920x1080
    2) 缩小到 960x540
    3) 裁切最上方 960x450
    4) 把该 960x450 覆盖到 960x540 底图顶部
    5) 叠加半透明轨道指示图 `static/tool/stage.png`
    6) 输出临时 PNG，供 BC3 DDS 编码
    """
    try:
        with Image.open(source) as im0:
            src = im0.convert("RGBA").copy()
    except UnidentifiedImageError as e:
        raise ValueError(f"无法识别图片格式：{source}") from e
    except OSError as e:
        raise ValueError(f"无法读取图片文件：{source}\n{e}") from e

    if src.size != (1920, 1080):
        raise ValueError(f"背景图尺寸必须是 1920x1080，当前为 {src.size[0]}x{src.size[1]}。")

    half = src.resize((960, 540), Image.Resampling.LANCZOS)
    top_crop = half.crop((0, 0, 960, 450))
    composed = half.copy()
    composed.paste(top_crop, (0, 0))

    overlay_path = _stage_overlay_png_path()
    if not overlay_path.is_file():
        raise FileNotFoundError(f"缺少轨道覆盖图：{overlay_path}")
    with Image.open(overlay_path) as ov0:
        overlay = ov0.convert("RGBA").copy()
    if overlay.size != (960, 540):
        overlay = overlay.resize((960, 540), Image.Resampling.LANCZOS)
    composed.alpha_composite(overlay)

    with tempfile.NamedTemporaryFile(prefix="stage_preview_", suffix=".png", delete=False) as tf:
        out = Path(tf.name)
    composed.save(out, "PNG")
    return out


@dataclass(frozen=True)
class StageCreateOptions:
    stage_id: int
    stage_name: str
    image_source: Path | None = None
    net_open_id: int = 2801
    net_open_str: str = "v2_45 00_1"
    release_tag_id: int = 20
    release_tag_str: str = "v2 2.45.00"
    notes_field_line_id: int = 8
    notes_field_line_str: str = "White"
    notes_field_line_data: str = "ホワイト"
    disable_flag: bool = False
    default_have: bool = False
    enable_plate: bool = False
    sort_name: str = ""
    priority: int = 0
    object_file: str = ""

    def stage_dir_name(self) -> str:
        return f"stage{self.stage_id:06d}"

    def default_image_name(self) -> str:
        return f"CHU_UI_Stage_{self.stage_id:05d}.dds"

def create_stage_from_image(
    *,
    acus_root: Path,
    tool_path: Path | None,
    opts: StageCreateOptions,
    game_root: str | None = None,
    use_external_afb: bool = True,
) -> Path:
    """
    根据图片生成 Stage 目录与 Stage.xml。

    - 目录：stage/stageXXXXXX/
    - 可选：把 image_source 转成 BC3 DDS 并写到 image/path
    - 固定写出 StageData 主结构（兼容 A001 样本字段）
    """
    if opts.stage_id <= 0:
        raise ValueError("stage_id 必须大于 0。")

    sdir = acus_root / "stage" / opts.stage_dir_name()
    sxml = sdir / "Stage.xml"
    if sdir.exists():
        raise FileExistsError(f"Stage 目录已存在：{sdir}")
    sdir.mkdir(parents=True, exist_ok=False)

    image_name = ""
    tmp_preview_png: Path | None = None
    if opts.image_source is not None:
        src = opts.image_source.expanduser().resolve()
        if not src.is_file():
            raise FileNotFoundError(f"图片文件不存在：{src}")
        # 外部 convert_stage 与预览贴图都统一要求输入是 1920x1080
        tmp_preview_png = _prepare_stage_preview_png(src)
        image_name = opts.default_image_name()
        try:
            ingest_to_bc3_dds(
                tool_path=tool_path,
                input_path=tmp_preview_png,
                output_dds=sdir / image_name,
            )
        finally:
            tmp_preview_png.unlink(missing_ok=True)

    if use_external_afb and opts.image_source is not None:
        build_stage_afb_from_image(
            stage_dir=sdir,
            stage_id=opts.stage_id,
            background_image=opts.image_source.expanduser().resolve(),
            game_root=game_root,
        )
    object_file = (opts.object_file or "").strip()
    stage_name = (opts.stage_name or "").strip() or f"Stage{opts.stage_id}"
    sort_name = (opts.sort_name or "").strip()

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<StageData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>{opts.stage_dir_name()}</dataName>
  <netOpenName>
    <id>{int(opts.net_open_id)}</id>
    <str>{_xml_text(opts.net_open_str)}</str>
    <data />
  </netOpenName>
  <disableFlag>{"true" if opts.disable_flag else "false"}</disableFlag>
  <releaseTagName>
    <id>{int(opts.release_tag_id)}</id>
    <str>{_xml_text(opts.release_tag_str)}</str>
    <data />
  </releaseTagName>
  <name>
    <id>{int(opts.stage_id)}</id>
    <str>{_xml_text(stage_name)}</str>
    <data />
  </name>
  <notesFieldLine>
    <id>{int(opts.notes_field_line_id)}</id>
    <str>{_xml_text(opts.notes_field_line_str)}</str>
    <data>{_xml_text(opts.notes_field_line_data)}</data>
  </notesFieldLine>
  <objectFile>
    <path>{_xml_text(object_file)}</path>
  </objectFile>
  <defaultHave>{"true" if opts.default_have else "false"}</defaultHave>
  <image>
    <path>{_xml_text(image_name)}</path>
  </image>
  <enablePlate>{"true" if opts.enable_plate else "false"}</enablePlate>
  <sortName>{_xml_text(sort_name)}</sortName>
  <priority>{int(opts.priority)}</priority>
</StageData>
"""
    sxml.write_text(xml, encoding="utf-8")
    return sxml


__all__ = ["StageCreateOptions", "create_stage_from_image", "StageAfbToolError"]

