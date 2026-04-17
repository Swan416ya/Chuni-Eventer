from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .dds_convert import ingest_to_bc3_dds
from .stage_afb_convert import StageAfbToolError, build_stage_afb_from_image


def _xml_text(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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
    notes_field_file: str | None = None
    base_file: str | None = None
    object_file: str = ""

    def stage_dir_name(self) -> str:
        return f"stage{self.stage_id:06d}"

    def default_image_name(self) -> str:
        return f"CHU_UI_Stage_{self.stage_id:05d}.dds"

    def default_notes_field_file(self) -> str:
        return f"nf_{self.stage_id:05d}.afb"

    def default_base_file(self) -> str:
        return f"st_{self.stage_id:05d}.afb"


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
    if opts.image_source is not None:
        src = opts.image_source.expanduser().resolve()
        if not src.is_file():
            raise FileNotFoundError(f"图片文件不存在：{src}")
        image_name = opts.default_image_name()
        ingest_to_bc3_dds(
            tool_path=tool_path,
            input_path=src,
            output_dds=sdir / image_name,
        )

    notes_field_file = (opts.notes_field_file or "").strip() or opts.default_notes_field_file()
    base_file = (opts.base_file or "").strip() or opts.default_base_file()
    if use_external_afb and opts.image_source is not None:
        afb = build_stage_afb_from_image(
            stage_dir=sdir,
            stage_id=opts.stage_id,
            background_image=opts.image_source.expanduser().resolve(),
            game_root=game_root,
        )
        notes_field_file = afb.notes_field_file
        base_file = afb.base_file
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
  <notesFieldFile>
    <path>{_xml_text(notes_field_file)}</path>
  </notesFieldFile>
  <baseFile>
    <path>{_xml_text(base_file)}</path>
  </baseFile>
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

