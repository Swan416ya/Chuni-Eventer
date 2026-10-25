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
from copy import deepcopy
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .dds_convert import ingest_to_bc3_dds
from .mate_layout import recommended_scale_for_height
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
    # Optional game-facing slot overrides.  Unspecified slots reuse gif_path.
    # A tuple keeps this frozen request deterministic and worker-thread safe.
    slot_gif_paths: tuple[tuple[int, Path], ...] = ()


@dataclass(frozen=True)
class FrameMateCreateRequest:
    """Build request for already-rendered transparent RGBA frames.

    Live2D and Spine adapters should render/download their model into this
    format, then cross this seam.  Callers do not need to know anything about
    FreeMote's JSON structure or Mate deployment.
    """

    acus_root: Path
    freemote_dir: Path
    frame_paths: tuple[Path, ...]
    duration_seconds: float
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
    animation_count: int = 1


@dataclass(frozen=True)
class GifFramePlan:
    """The exact sampling/cropping plan used by the E-mote builder."""

    source_frame_count: int
    duration_seconds: float
    requested_fps: int
    output_frame_count: int
    effective_fps: float
    crop_box: tuple[int, int, int, int]
    output_size: tuple[int, int]
    sampled_indices: tuple[int, ...]

    @property
    def capped(self) -> bool:
        return self.output_frame_count >= MAX_OUTPUT_FRAMES and max(
            2, round(self.duration_seconds * self.requested_fps)
        ) > MAX_OUTPUT_FRAMES


@dataclass(frozen=True)
class _PreparedAnimation:
    label: str
    frame_paths: tuple[Path, ...]
    duration_seconds: float
    frame_size: tuple[int, int]


ProgressFn = Callable[[str], None]
MateCreateRequest = GifMateCreateRequest | FrameMateCreateRequest


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


def inspect_gif(
    gif_path: Path,
    *,
    target_fps: int,
    target_height: int,
) -> GifFramePlan:
    """Inspect a GIF and return the plan later used by :func:`create_gif_mate`."""
    if target_fps < 1 or target_fps > 30:
        raise GifMateError("GIF 帧率必须在 1～30 FPS 之间")
    if target_height not in {256, 320, 384, 512}:
        raise GifMateError("GIF 输出高度仅支持 256 / 320 / 384 / 512")

    try:
        source = Image.open(gif_path)
    except Exception as exc:
        raise GifMateError(f"无法读取 GIF：{exc}") from exc
    try:
        frame_count = getattr(source, "n_frames", 1)
        if frame_count < 2:
            raise GifMateError("所选文件不是多帧 GIF")
        if source.width * source.height > 32_000_000:
            raise GifMateError("GIF 单帧尺寸过大（最多约 3200 万像素）")

        durations_ms: list[int] = []
        boxes: list[tuple[int, int, int, int]] = []
        has_transparency = False
        default_duration = max(10, int(source.info.get("duration", 100) or 100))
        for index in range(frame_count):
            source.seek(index)
            durations_ms.append(
                max(10, int(source.info.get("duration", default_duration) or default_duration))
            )
            rgba = source.convert("RGBA")
            alpha = rgba.getchannel("A")
            if alpha.getextrema()[0] < 255:
                has_transparency = True
            bbox = alpha.point(lambda value: 255 if value > 8 else 0).getbbox()
            if bbox:
                boxes.append(bbox)
    finally:
        source.close()

    if not has_transparency:
        raise GifMateError(
            "GIF 没有透明背景，生成后会出现整块矩形底色；请先抠图并导出带透明通道的 GIF"
        )
    if not boxes:
        raise GifMateError("GIF 的所有帧均为透明画面")
    total_ms = sum(durations_ms)
    duration_seconds = total_ms / 1000.0
    wanted = max(2, round(duration_seconds * target_fps))
    output_count = min(MAX_OUTPUT_FRAMES, wanted)
    cumulative: list[int] = []
    elapsed = 0
    for duration in durations_ms:
        elapsed += duration
        cumulative.append(elapsed)
    sampled_indices = tuple(
        min(
            frame_count - 1,
            bisect_right(
                cumulative,
                min(total_ms - 1, round((index + 0.5) * total_ms / output_count)),
            ),
        )
        for index in range(output_count)
    )
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
    return GifFramePlan(
        source_frame_count=frame_count,
        duration_seconds=duration_seconds,
        requested_fps=target_fps,
        output_frame_count=output_count,
        effective_fps=output_count / duration_seconds,
        crop_box=crop_box,
        output_size=(output_width, target_height),
        sampled_indices=sampled_indices,
    )


def _extract_frames(
    gif_path: Path,
    out_dir: Path,
    *,
    target_fps: int,
    target_height: int,
    plan: GifFramePlan | None = None,
) -> tuple[list[Path], float, tuple[int, int]]:
    plan = plan or inspect_gif(
        gif_path, target_fps=target_fps, target_height=target_height
    )

    try:
        source = Image.open(gif_path)
    except Exception as exc:
        raise GifMateError(f"无法读取 GIF：{exc}") from exc
    try:
        needed = set(plan.sampled_indices)
        decoded: dict[int, Image.Image] = {}
        for index in range(source.n_frames):
            source.seek(index)
            if index in needed:
                decoded[index] = source.convert("RGBA")
        sampled = [decoded[index] for index in plan.sampled_indices]
    finally:
        source.close()

    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, frame in enumerate(sampled):
        output = frame.crop(plan.crop_box).resize(
            plan.output_size, Image.Resampling.LANCZOS
        )
        path = out_dir / f"f{index:04d}.png"
        output.save(path, "PNG")
        paths.append(path)
    return paths, plan.duration_seconds, plan.output_size


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


def _build_single_emtbytes(
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

    # The E-mote origin is the centre of its authored screen.  Keeping the
    # donor's 800x1080 screen/pixel-marker bounds would make wide or short GIFs
    # use the donor model's culling envelope even though their textures were
    # replaced.  Describe the generated model's real union-cropped canvas.
    model["screenSize"] = {
        "height": frame_height,
        "originX": 0,
        "originY": 0,
        "width": frame_width,
    }
    chara_profile = model.get("metadata", {}).get("charaProfile", {})
    pixel_marker = chara_profile.get("pixelMarker")
    if isinstance(pixel_marker, dict):
        pixel_marker.update(
            {
                "boundsBottom": frame_height / 2,
                "boundsLeft": -frame_width / 2,
                "boundsRight": frame_width / 2,
                "boundsTop": -frame_height / 2,
            }
        )
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


def _compile_built_model(
    *,
    skeleton_dir: Path,
    model: dict,
    resx: dict,
    output_path: Path,
    freemote_dir: Path,
) -> None:
    """Compile an already-mutated PSB model and copy the common PSB output."""
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
        raise GifMateError("PsBuild 编译多动作 GIF Mate 超时（10 分钟）") from exc
    if proc.returncode != 0:
        raise GifMateError(f"PsBuild 编译失败：\n{proc.stdout}\n{proc.stderr}")
    produced = skeleton_dir / "built.pure.psb"
    if not produced.is_file():
        raise GifMateError("PsBuild 未生成 built.pure.psb")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(produced, output_path)


def _build_multi_emtbytes(
    *,
    skeleton_dir: Path,
    animations: tuple[_PreparedAnimation, ...],
    output_path: Path,
    freemote_dir: Path,
) -> None:
    """Build one PSB containing independently selectable GIF timelines.

    Each GIF becomes a looping child motion.  A discrete ``gif_action``
    parameter selects one child, while metadata.timelineControl exposes the
    animation labels consumed by Mate.xml's ``emote`` field.
    """
    if len(animations) < 2:
        raise GifMateError("多动作构建至少需要两条不同 GIF 动画")
    model, resx = _load_skeleton(skeleton_dir)
    try:
        base = model["metadata"]["base"]
        motions = model["object"][base["chara"]]["motion"]
        base_motion = motions[base["motion"]]
        composition_name = base_motion["layer"][0]["frameList"][0]["content"]["icon"]
        composition_template = motions[composition_name]
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
    copied_root = skeleton_dir / "gif_frames"
    copied_root.mkdir(exist_ok=True)
    motion_names: list[str] = []
    last_times: list[int] = []
    max_width = max(animation.frame_size[0] for animation in animations)
    max_height = max(animation.frame_size[1] for animation in animations)

    model["screenSize"] = {
        "height": max_height,
        "originX": 0,
        "originY": 0,
        "width": max_width,
    }
    pixel_marker = model.get("metadata", {}).get("charaProfile", {}).get("pixelMarker")
    if isinstance(pixel_marker, dict):
        pixel_marker.update(
            {
                "boundsBottom": max_height / 2,
                "boundsLeft": -max_width / 2,
                "boundsRight": max_width / 2,
                "boundsTop": -max_height / 2,
            }
        )

    for animation_index, animation in enumerate(animations):
        motion_name = f"__gif_action_{animation_index + 1:02d}"
        motion_names.append(motion_name)
        last_time = max(1, round(animation.duration_seconds * TICK_RATE))
        last_times.append(last_time)
        times = [
            round(index * last_time / len(animation.frame_paths))
            for index in range(len(animation.frame_paths))
        ]
        action_dir = copied_root / f"a{animation_index + 1:02d}"
        action_dir.mkdir(exist_ok=True)
        frame_list: list[dict] = []
        frame_width, frame_height = animation.frame_size
        for frame_index, path in enumerate(animation.frame_paths):
            copied = action_dir / path.name
            shutil.copyfile(path, copied)
            texture_name = f"tex#{next_texture_id}"
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
            resources[str(next_resource_id)] = (
                f"gif_frames/a{animation_index + 1:02d}/{copied.name}"
            )
            next_resource_id += 1
            next_texture_id += 1
            frame_list.append(
                {
                    "content": {
                        "icon": "0000",
                        "src": texture_name,
                        "mask": 33554432,
                        "mesh": {"bp": None, "cc": None},
                    },
                    "time": times[frame_index],
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
            "label": f"gif_layer_{animation_index + 1:02d}",
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
        motion = deepcopy(composition_template)
        motion.update(
            {
                "layer": [layer],
                "lastTime": last_time,
                "loopTime": 0,
                "layerIndexMap": {layer["label"]: 0},
                "parameter": [],
                "parameterize": None,
                "priority": priority,
                "variable": [],
            }
        )
        motions[motion_name] = motion

    selector_end = max(1, len(animations) - 1)
    selector_frames = []
    for index, motion_name in enumerate(motion_names):
        selector_frames.append(
            {
                "content": {
                    "icon": motion_name,
                    "mask": 524288,
                    "motion": {"mask": 0, "timeOffset": 0},
                    "src": base["chara"],
                },
                "time": index,
                "type": 2 if index in {0, len(motion_names) - 1} else 3,
            }
        )
    selector_frames.append({"time": selector_end + 1, "type": 0})
    selector_layer = {
        "children": [],
        "coordinate": 0,
        "exportSelf": 1,
        "frameList": selector_frames,
        "groundCorrection": 0,
        "inheritMask": 33556476,
        "joinTarget": 1,
        "label": "gif_action_selector",
        "meshCombine": 0,
        "meshTransform": 0,
        "metadata": None,
        "motionIndependentLayerInherit": 0,
        "parameterize": 0,
        "stencilType": 0,
        "transformOrder": [0, 3, 2, 1],
        "type": 3,
    }
    composition_template.update(
        {
            "layer": [selector_layer],
            "lastTime": selector_end + 1,
            "loopTime": -1,
            "layerIndexMap": {"gif_action_selector": 0},
            "parameter": [
                {
                    "discretization": 0,
                    "division": selector_end,
                    "enabled": 1,
                    "id": "gif_action",
                    "rangeBegin": 0,
                    "rangeEnd": len(animations) - 1,
                }
            ],
            "parameterize": 0,
            "priority": [
                {"content": [0], "time": 0, "type": 1},
                {"content": None, "time": selector_end + 1, "type": 1},
            ],
            "variable": [],
        }
    )

    max_last_time = max(last_times)
    base_motion["lastTime"] = max_last_time
    base_motion["loopTime"] = 0
    for frame in base_motion["layer"][0]["frameList"]:
        if frame.get("type") == 0:
            frame["time"] = max_last_time
    base_motion["priority"] = [
        {"content": [0], "time": 0, "type": 1},
        {"content": None, "time": max_last_time, "type": 1},
    ]

    metadata = model["metadata"]
    metadata["timelineControl"] = [
        {
            "diff": 0,
            "label": animation.label,
            "lastTime": -1,
            "loopBegin": -1,
            "loopEnd": -1,
            "variableList": [
                {
                    "frameList": [
                        {
                            "content": {"easing": 0, "value": index},
                            "time": 0,
                            "type": 2,
                        },
                        {"content": None, "time": last_times[index], "type": 0},
                    ],
                    "label": "gif_action",
                }
            ],
        }
        for index, animation in enumerate(animations)
    ]
    variable_list = metadata.setdefault("variableList", [])
    variable_list[:] = [item for item in variable_list if item.get("label") != "gif_action"]
    variable_list.append(
        {
            "frameList": [
                {"frame": index, "label": animation.label}
                for index, animation in enumerate(animations)
            ],
            "label": "gif_action",
        }
    )
    _compile_built_model(
        skeleton_dir=skeleton_dir,
        model=model,
        resx=resx,
        output_path=output_path,
        freemote_dir=freemote_dir,
    )


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


def _validate_rendered_frames(
    frame_paths: tuple[Path, ...], duration_seconds: float
) -> tuple[list[Path], tuple[int, int]]:
    if not 2 <= len(frame_paths) <= MAX_OUTPUT_FRAMES:
        raise GifMateError(f"透明帧序列必须包含 2～{MAX_OUTPUT_FRAMES} 帧")
    if duration_seconds <= 0:
        raise GifMateError("动画时长必须大于 0 秒")
    if len(frame_paths) / duration_seconds > TICK_RATE:
        raise GifMateError(f"动画帧率不能超过 E-mote 时间轴的 {TICK_RATE} FPS")

    resolved: list[Path] = []
    expected_size: tuple[int, int] | None = None
    has_transparency = False
    for raw_path in frame_paths:
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise GifMateError(f"动画帧不存在：{path}")
        try:
            with Image.open(path) as frame:
                rgba = frame.convert("RGBA")
                if expected_size is None:
                    expected_size = rgba.size
                elif rgba.size != expected_size:
                    raise GifMateError(
                        f"动画帧尺寸不一致：期望 {expected_size[0]}×{expected_size[1]}，"
                        f"实际 {rgba.width}×{rgba.height}（{path.name}）"
                    )
                if rgba.getchannel("A").getextrema()[0] < 255:
                    has_transparency = True
        except GifMateError:
            raise
        except Exception as exc:
            raise GifMateError(f"无法读取动画帧 {path.name}：{exc}") from exc
        resolved.append(path)

    if not has_transparency:
        raise GifMateError("动画帧没有透明通道，生成后会出现矩形底色")
    assert expected_size is not None
    return resolved, expected_size


def _publish_frame_mate(
    request: MateCreateRequest,
    *,
    frame_paths: list[Path],
    duration: float,
    frame_size: tuple[int, int],
    temp_root: Path,
    progress: ProgressFn | None,
    animations: tuple[_PreparedAnimation, ...] | None = None,
    slot_assignments: dict[int, str] | None = None,
) -> GifMateCreateResult:
    template = Path(request.template_emtbytes).expanduser().resolve()
    if not template.is_file():
        raise GifMateError(f"Mate 模板不存在：{template}")
    mate_root = Path(request.acus_root) / "mate"
    mate_dir = mate_root / f"mate{request.mate_id:06d}"
    if mate_dir.exists():
        raise GifMateError(f"Mate ID 已存在：{mate_dir.name}")
    mate_root.mkdir(parents=True, exist_ok=True)

    skeleton_work = temp_root / "skeleton"
    staged = temp_root / f"mate{request.mate_id:06d}"
    staged.mkdir()

    _emit(progress, f"已准备 {len(frame_paths)} 帧，正在解包 Mate 模板…")
    assigner = PsbActionAssigner(Path(request.freemote_dir))
    assigner.decompile(template, skeleton_work)
    decompiled = skeleton_work / "decompiled"

    emt_name = f"emote{request.mate_id:06d}.emtbytes"
    emt_path = staged / emt_name
    _emit(progress, "正在构建 E-mote 动画…")
    if animations and len(animations) > 1:
        _build_multi_emtbytes(
            skeleton_dir=decompiled,
            animations=animations,
            output_path=emt_path,
            freemote_dir=Path(request.freemote_dir),
        )
    else:
        _build_single_emtbytes(
            skeleton_dir=decompiled,
            frame_paths=frame_paths,
            duration_seconds=duration,
            output_path=emt_path,
            freemote_dir=Path(request.freemote_dir),
        )

    icon_png = temp_root / "mate_icon.png"
    _make_icon(frame_paths[0], icon_png)
    dds_name = f"CHU_UI_Mate_{request.mate_id:06d}.dds"
    _emit(progress, "正在生成 Mate 图标…")
    ingest_to_bc3_dds(
        tool_path=request.dds_tool_path,
        input_path=icon_png,
        output_dds=staged / dds_name,
    )

    recommended_scale = recommended_scale_for_height(frame_size[1])
    scale = request.scale_x10000 or recommended_scale
    slots = slot_assignments or {slot: _GIF_TIMELINE_LABEL for slot in range(1, 19)}
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
        frame_count=(
            sum(len(animation.frame_paths) for animation in animations)
            if animations
            else len(frame_paths)
        ),
        frame_size=frame_size,
        duration_seconds=duration,
        effective_fps=(
            sum(len(animation.frame_paths) for animation in animations)
            / sum(animation.duration_seconds for animation in animations)
            if animations
            else len(frame_paths) / duration
        ),
        scale_x10000=scale,
        emtbytes_size=(mate_dir / emt_name).stat().st_size,
        animation_count=len(animations) if animations else 1,
    )


def create_frame_mate(
    request: FrameMateCreateRequest,
    *,
    progress: ProgressFn | None = None,
) -> GifMateCreateResult:
    """Create a Mate from transparent frames rendered by any source adapter."""
    frames, frame_size = _validate_rendered_frames(
        request.frame_paths, request.duration_seconds
    )
    mate_root = Path(request.acus_root) / "mate"
    mate_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".frame_mate_", dir=mate_root) as temp_name:
        return _publish_frame_mate(
            request,
            frame_paths=frames,
            duration=request.duration_seconds,
            frame_size=frame_size,
            temp_root=Path(temp_name),
            progress=progress,
        )


def create_gif_mate(
    request: GifMateCreateRequest,
    *,
    progress: ProgressFn | None = None,
) -> GifMateCreateResult:
    """Create and atomically publish one complete Mate directory from a GIF."""
    gif_path = Path(request.gif_path).expanduser().resolve()
    if not gif_path.is_file():
        raise GifMateError(f"GIF 不存在：{gif_path}")
    mate_root = Path(request.acus_root) / "mate"
    mate_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".gif_mate_", dir=mate_root) as temp_name:
        temp_root = Path(temp_name)
        slot_paths = {slot: gif_path for slot in range(1, 19)}
        for raw_slot, raw_path in request.slot_gif_paths:
            slot = int(raw_slot)
            if slot not in slot_paths:
                raise GifMateError(f"GIF 动作槽必须在 1～18 之间：{slot}")
            resolved = Path(raw_path).expanduser().resolve()
            if not resolved.is_file():
                raise GifMateError(f"动作 Type {slot} 的 GIF 不存在：{resolved}")
            slot_paths[slot] = resolved

        unique_paths: list[Path] = []
        for slot in range(1, 19):
            path = slot_paths[slot]
            if path not in unique_paths:
                unique_paths.append(path)

        prepared: list[_PreparedAnimation] = []
        path_labels: dict[Path, str] = {}
        _emit(progress, f"正在读取并优化 {len(unique_paths)} 条 GIF 动作…")
        for index, path in enumerate(unique_paths):
            label = _GIF_TIMELINE_LABEL if len(unique_paths) == 1 else f"GIF_ACTION_{index + 1:02d}"
            plan = inspect_gif(
                path,
                target_fps=request.target_fps,
                target_height=request.target_height,
            )
            extracted, action_duration, action_size = _extract_frames(
                path,
                temp_root / "frames" / f"a{index + 1:02d}",
                target_fps=request.target_fps,
                target_height=request.target_height,
                plan=plan,
            )
            path_labels[path] = label
            prepared.append(
                _PreparedAnimation(
                    label=label,
                    frame_paths=tuple(extracted),
                    duration_seconds=action_duration,
                    frame_size=action_size,
                )
            )

        first = prepared[0]
        frames = list(first.frame_paths)
        duration = max(animation.duration_seconds for animation in prepared)
        frame_size = (
            max(animation.frame_size[0] for animation in prepared),
            max(animation.frame_size[1] for animation in prepared),
        )
        slots = {slot: path_labels[path] for slot, path in slot_paths.items()}
        return _publish_frame_mate(
            request,
            frame_paths=frames,
            duration=duration,
            frame_size=frame_size,
            temp_root=temp_root,
            progress=progress,
            animations=tuple(prepared),
            slot_assignments=slots,
        )
