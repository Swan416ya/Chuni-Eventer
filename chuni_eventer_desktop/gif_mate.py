"""Build a CHUNITHM Mate directly from an animated GIF.

The public interface intentionally hides the frame extraction, donor-skeleton,
FreeMote, icon, XML, and atomic-deployment details from the UI.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .dds_convert import ingest_to_bc3_dds
from .psb_action_assigner import PsbActionAssigner, generate_mate_xml

TICK_RATE = 60
MAX_OUTPUT_FRAMES = 120
_GIF_TIMELINE_LABEL = "平常"


class GifMateError(RuntimeError):
    """GIF Mate conversion failed without publishing a partial Mate directory."""


@dataclass(frozen=True)
class GifMateCreateRequest:
    acus_root: Path
    freemote_dir: Path
    gif_path: Path
    template_emtbytes: Path
    mate_id: int
    name: str
    chara_id: int
    chara_name: str
    dds_illust_key: str
    system_voice_id: int = 0
    pos_x: int = 1
    pos_y: int = -50
    scale_x10000: int | None = None
    target_fps: int = 10
    target_height: int = 384
    dds_tool_path: Path | None = None


@dataclass(frozen=True)
class GifMateCreateResult:
    mate_dir: Path
    frame_count: int
    frame_size: tuple[int, int]
    duration_seconds: float
    effective_fps: float
    scale_x10000: int
    emtbytes_size: int


ProgressFn = Callable[[str], None]


def find_gif_mate_template(acus_root: Path) -> Path | None:
    """Return the first existing Mate animation usable as a donor skeleton."""
    mate_root = Path(acus_root) / "mate"
    candidates = sorted(
        p for p in mate_root.glob("mate*/emote*.emtbytes") if p.is_file()
    )
    return candidates[0] if candidates else None


def _emit(progress: ProgressFn | None, text: str) -> None:
    if progress is not None:
        progress(text)


def _extract_frames(
    gif_path: Path,
    out_dir: Path,
    *,
    target_fps: int,
    target_height: int,
) -> tuple[list[Path], float, tuple[int, int]]:
    if target_fps < 1 or target_fps > 30:
        raise GifMateError("GIF 帧率必须在 1～30 FPS 之间")
    if target_height not in {256, 320, 384, 512}:
        raise GifMateError("GIF 输出高度仅支持 256 / 320 / 384 / 512")

    try:
        source = Image.open(gif_path)
    except Exception as exc:
        raise GifMateError(f"无法读取 GIF：{exc}") from exc
    if getattr(source, "n_frames", 1) < 2:
        source.close()
        raise GifMateError("所选文件不是多帧 GIF")
    if source.width * source.height > 32_000_000:
        source.close()
        raise GifMateError("GIF 单帧尺寸过大（最多约 3200 万像素）")

    durations_ms: list[int] = []
    default_duration = max(10, int(source.info.get("duration", 100) or 100))
    try:
        for index in range(source.n_frames):
            source.seek(index)
            durations_ms.append(
                max(10, int(source.info.get("duration", default_duration) or default_duration))
            )
        total_ms = sum(durations_ms)
        duration_seconds = total_ms / 1000.0
        wanted = max(2, round(duration_seconds * target_fps))
        output_count = min(MAX_OUTPUT_FRAMES, wanted)
        cumulative: list[int] = []
        elapsed = 0
        for duration in durations_ms:
            elapsed += duration
            cumulative.append(elapsed)

        sampled_indices = []
        for index in range(output_count):
            timestamp = min(total_ms - 1, round((index + 0.5) * total_ms / output_count))
            sampled_indices.append(
                min(source.n_frames - 1, bisect_right(cumulative, timestamp))
            )

        needed = set(sampled_indices)
        decoded: dict[int, Image.Image] = {}
        for index in range(source.n_frames):
            source.seek(index)
            if index in needed:
                decoded[index] = source.convert("RGBA")
        sampled = [decoded[index] for index in sampled_indices]
    finally:
        source.close()

    if all(frame.getchannel("A").getextrema()[0] == 255 for frame in sampled):
        raise GifMateError(
            "GIF 没有透明背景，生成后会出现整块矩形底色；请先抠图并导出带透明通道的 GIF"
        )

    boxes = []
    for frame in sampled:
        alpha = frame.getchannel("A").point(lambda value: 255 if value > 8 else 0)
        bbox = alpha.getbbox()
        if bbox:
            boxes.append(bbox)
    if not boxes:
        raise GifMateError("GIF 的所有帧均为透明画面")
    crop_box = (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )
    crop_w = crop_box[2] - crop_box[0]
    crop_h = crop_box[3] - crop_box[1]
    if crop_w <= 0 or crop_h <= 0:
        raise GifMateError("GIF 有效画面尺寸为零")
    output_width = max(1, round(crop_w * target_height / crop_h))

    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, frame in enumerate(sampled):
        output = frame.crop(crop_box).resize(
            (output_width, target_height), Image.Resampling.LANCZOS
        )
        path = out_dir / f"f{index:04d}.png"
        output.save(path, "PNG")
        paths.append(path)
    return paths, duration_seconds, (output_width, target_height)


def _load_skeleton(skeleton_dir: Path) -> tuple[dict, dict]:
    model_paths = sorted(
        path
        for path in skeleton_dir.glob("*.json")
        if not path.name.endswith(".resx.json")
    )
    if not model_paths:
        raise GifMateError("模板解包后没有找到 PSB JSON")
    model_path = model_paths[0]
    resx_path = skeleton_dir / f"{model_path.stem}.resx.json"
    if not resx_path.is_file():
        raise GifMateError(f"模板缺少资源表：{resx_path.name}")
    try:
        return (
            json.loads(model_path.read_text(encoding="utf-8")),
            json.loads(resx_path.read_text(encoding="utf-8")),
        )
    except Exception as exc:
        raise GifMateError(f"无法读取模板骨架：{exc}") from exc


def _build_emtbytes(
    *,
    skeleton_dir: Path,
    frame_paths: list[Path],
    duration_seconds: float,
    output_path: Path,
    freemote_dir: Path,
) -> None:
    model, resx = _load_skeleton(skeleton_dir)
    try:
        base = model["metadata"]["base"]
        motions = model["object"][base["chara"]]["motion"]
        base_motion = motions[base["motion"]]
        composition_name = base_motion["layer"][0]["frameList"][0]["content"]["icon"]
        composition = motions[composition_name]
        source = model["source"]
        resources = resx["Resources"]
    except (KeyError, IndexError, TypeError) as exc:
        raise GifMateError("所选模板不是可识别的完整 Mate 骨架") from exc

    used_resource_ids = {int(key) for key in resources if str(key).isdigit()}
    next_resource_id = max(used_resource_ids | {999}) + 1
    used_texture_ids = {
        int(key.removeprefix("tex#"))
        for key in source
        if key.startswith("tex#") and key.removeprefix("tex#").isdigit()
    }
    next_texture_id = max(used_texture_ids | {999}) + 1
    last_time = max(1, round(duration_seconds * TICK_RATE))
    times = [round(index * last_time / len(frame_paths)) for index in range(len(frame_paths))]

    copied_frames = skeleton_dir / "gif_frames"
    copied_frames.mkdir(exist_ok=True)
    frame_list = []
    with Image.open(frame_paths[0]) as first:
        frame_width, frame_height = first.size
    for index, path in enumerate(frame_paths):
        copied = copied_frames / path.name
        shutil.copyfile(path, copied)
        texture_name = f"tex#{next_texture_id + index}"
        source[texture_name] = {
            "icon": {
                "0000": {
                    "attr": 0,
                    "height": frame_height,
                    "width": frame_width,
                    "left": 0,
                    "top": 0,
                    "originX": frame_width // 2,
                    "originY": frame_height // 2,
                    "metadata": None,
                }
            },
            "metadata": None,
            "texture": {
                "height": frame_height,
                "width": frame_width,
                "pixel": f"#resource#{next_resource_id}",
                "type": "RGBA8",
                "truncated_height": frame_height,
                "truncated_width": frame_width,
            },
            "type": 0,
        }
        resources[str(next_resource_id)] = f"gif_frames/{copied.name}"
        next_resource_id += 1
        frame_list.append(
            {
                "content": {
                    "icon": "0000",
                    "src": texture_name,
                    "mask": 33554432,
                    "mesh": {"bp": None, "cc": None},
                },
                "time": times[index],
                "type": 2,
            }
        )
    frame_list.append({"time": last_time, "type": 0})

    layer = {
        "children": [],
        "coordinate": 0,
        "exportSelf": 1,
        "frameList": frame_list,
        "groundCorrection": 0,
        "inheritMask": 33556476,
        "joinTarget": 1,
        "label": "gif_layer",
        "meshCombine": 0,
        "meshDivision": 20,
        "meshSyncChildMask": 0,
        "meshTransform": 1,
        "metadata": None,
        "objTriPriority": 2,
        "parameterize": None,
        "stencilType": 0,
        "transformOrder": [0, 3, 2, 1],
        "type": 0,
    }
    priority = [
        {"content": [0], "time": 0, "type": 1},
        {"content": None, "time": last_time, "type": 1},
    ]
    composition.update(
        {
            "layer": [layer],
            "lastTime": last_time,
            "loopTime": 0,
            "layerIndexMap": {"gif_layer": 0},
            "parameter": [],
            "parameterize": None,
            "priority": priority,
            "variable": [],
        }
    )
    base_motion["lastTime"] = last_time
    base_motion["loopTime"] = 0
    for frame in base_motion["layer"][0]["frameList"]:
        if frame.get("type") == 0:
            frame["time"] = last_time
    base_motion["priority"] = priority

    model["label"] = output_path.stem
    built_json = skeleton_dir / "built.json"
    built_json.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
    (skeleton_dir / "built.resx.json").write_text(
        json.dumps(resx, ensure_ascii=False), encoding="utf-8"
    )

    psbuild = Path(freemote_dir) / "PsBuild.exe"
    if not psbuild.is_file():
        raise GifMateError(f"缺少 PsBuild.exe：{psbuild}")
    try:
        proc = subprocess.run(
            [str(psbuild), built_json.name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(skeleton_dir),
            timeout=600,
            **(
                {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
                if sys.platform == "win32"
                else {}
            ),
        )
    except subprocess.TimeoutExpired as exc:
        raise GifMateError("PsBuild 编译 GIF Mate 超时（10 分钟）") from exc
    if proc.returncode != 0:
        raise GifMateError(f"PsBuild 编译失败：\n{proc.stdout}\n{proc.stderr}")
    produced = skeleton_dir / "built.pure.psb"
    if not produced.is_file():
        raise GifMateError("PsBuild 未生成 built.pure.psb")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(produced, output_path)


def _make_icon(first_frame: Path, output_path: Path) -> None:
    with Image.open(first_frame) as source:
        source = source.convert("RGBA")
        max_side = 820
        ratio = min(max_side / source.width, max_side / source.height, 1.0)
        size = (max(1, round(source.width * ratio)), max(1, round(source.height * ratio)))
        source = source.resize(size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
        x = (1024 - source.width) // 2
        y = max(0, 930 - source.height)
        canvas.alpha_composite(source, (x, y))
        canvas.save(output_path, "PNG")


def create_gif_mate(
    request: GifMateCreateRequest,
    *,
    progress: ProgressFn | None = None,
) -> GifMateCreateResult:
    """Create and atomically publish one complete Mate directory from a GIF."""
    gif_path = Path(request.gif_path).expanduser().resolve()
    template = Path(request.template_emtbytes).expanduser().resolve()
    if not gif_path.is_file():
        raise GifMateError(f"GIF 不存在：{gif_path}")
    if not template.is_file():
        raise GifMateError(f"Mate 模板不存在：{template}")
    mate_root = Path(request.acus_root) / "mate"
    mate_dir = mate_root / f"mate{request.mate_id:06d}"
    if mate_dir.exists():
        raise GifMateError(f"Mate ID 已存在：{mate_dir.name}")
    mate_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".gif_mate_", dir=mate_root) as temp_name:
        temp_root = Path(temp_name)
        frames_dir = temp_root / "frames"
        skeleton_work = temp_root / "skeleton"
        staged = temp_root / f"mate{request.mate_id:06d}"
        staged.mkdir()

        _emit(progress, "正在读取并优化 GIF 帧…")
        frames, duration, frame_size = _extract_frames(
            gif_path,
            frames_dir,
            target_fps=request.target_fps,
            target_height=request.target_height,
        )
        _emit(progress, f"已准备 {len(frames)} 帧，正在解包 Mate 模板…")
        assigner = PsbActionAssigner(Path(request.freemote_dir))
        assigner.decompile(template, skeleton_work)
        decompiled = skeleton_work / "decompiled"

        emt_name = f"emote{request.mate_id:06d}.emtbytes"
        emt_path = staged / emt_name
        _emit(progress, "正在构建 E-mote 动画…")
        _build_emtbytes(
            skeleton_dir=decompiled,
            frame_paths=frames,
            duration_seconds=duration,
            output_path=emt_path,
            freemote_dir=Path(request.freemote_dir),
        )

        icon_png = temp_root / "mate_icon.png"
        _make_icon(frames[0], icon_png)
        dds_name = f"CHU_UI_Mate_{request.mate_id:06d}.dds"
        _emit(progress, "正在生成 Mate 图标…")
        ingest_to_bc3_dds(
            tool_path=request.dds_tool_path,
            input_path=icon_png,
            output_dds=staged / dds_name,
        )

        recommended_scale = round(900 * 1080 / (0.163 * frame_size[1]))
        scale = request.scale_x10000 or recommended_scale
        slots = {slot: _GIF_TIMELINE_LABEL for slot in range(1, 19)}
        xml = generate_mate_xml(
            mate_id=request.mate_id,
            name=request.name,
            chara_id=request.chara_id,
            chara_name=request.chara_name,
            emote_filename=emt_name,
            dds_filename=dds_name,
            slot_assignments=slots,
            dds_illust_key=request.dds_illust_key,
            system_voice_id=request.system_voice_id,
            pos_x=request.pos_x,
            pos_y=request.pos_y,
            scale_x10000=scale,
        )
        (staged / "Mate.xml").write_text(xml, encoding="utf-8")

        _emit(progress, "正在写入 ACUS…")
        os.replace(staged, mate_dir)
        return GifMateCreateResult(
            mate_dir=mate_dir,
            frame_count=len(frames),
            frame_size=frame_size,
            duration_seconds=duration,
            effective_fps=len(frames) / duration,
            scale_x10000=scale,
            emtbytes_size=(mate_dir / emt_name).stat().st_size,
        )
