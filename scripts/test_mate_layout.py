"""Regression checks for game-accurate Mate placement and GIF sampling."""

from __future__ import annotations

import tempfile
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chuni_eventer_desktop.gif_mate import MAX_OUTPUT_FRAMES, inspect_gif
from chuni_eventer_desktop.mate_layout import (
    DEFAULT_MATE_ROOM_CALIBRATION,
    DEFAULT_RESULT_CALIBRATION,
    calibration_from_game,
    mate_content_rect,
    mate_position_from_screen,
    recommended_scale_for_height,
)


def _make_variable_gif(path: Path, frame_count: int = 20) -> None:
    frames: list[Image.Image] = []
    for index in range(frame_count):
        frame = Image.new("RGBA", (100, 80), (0, 0, 0, 0))
        draw = ImageDraw.Draw(frame)
        draw.rectangle((10 + index % 5, 5, 69, 64), fill=(255, 80, 80, 255))
        frames.append(frame)
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=[50, 150] * (frame_count // 2),
        loop=0,
        disposal=2,
    )


def main() -> None:
    game_root = Path(r"D:\Chunithm_Mate")
    calibration = (
        calibration_from_game(game_root)
        if game_root.is_dir()
        else DEFAULT_RESULT_CALIBRATION
    )
    assert abs(calibration.anchor_x - 1610) < 0.01
    assert abs(calibration.anchor_y - 636) < 0.01
    assert abs(calibration.emote_to_screen - 0.896484375) < 0.000001
    surface = calibration.surface_rect
    assert all(abs(actual - expected) < 0.01 for actual, expected in zip(
        surface, (1151.0, 177.0, 918.0, 918.0)
    ))

    rect = mate_content_rect(
        source_size=(800, 1080),
        pos_x=1,
        pos_y=-50,
        scale_x10000=6000,
        calibration=calibration,
    )
    assert abs(rect[0] - 1395.742) < 0.01
    assert abs(rect[1] - 300.715) < 0.01
    assert abs(rect[2] - 430.3125) < 0.01
    assert abs(rect[3] - 580.921875) < 0.01
    center = (rect[0] + rect[2] / 2, rect[1] + rect[3] / 2)
    assert mate_position_from_screen(
        center_x=center[0], center_y=center[1], calibration=calibration
    ) == (1, -50)
    assert recommended_scale_for_height(384, calibration=calibration) == 26_144

    mate_room = (
        calibration_from_game(game_root, "mate_room")
        if game_root.is_dir()
        else DEFAULT_MATE_ROOM_CALIBRATION
    )
    assert mate_room.scene_key == "mate_room"
    assert abs(mate_room.anchor_x - 960) < 0.01
    assert abs(mate_room.anchor_y - 552) < 0.01
    assert abs(mate_room.cast_scale - 1.0) < 0.000001
    assert all(abs(actual - expected) < 0.01 for actual, expected in zip(
        mate_room.surface_rect, (420.0, 12.0, 1080.0, 1080.0)
    ))
    room_rect = mate_content_rect(
        source_size=(800, 1080),
        pos_x=1,
        pos_y=-50,
        scale_x10000=6000,
        calibration=mate_room,
    )
    # Same XML values: Mate ROOM is 1 / 0.85 larger than result, and uses its
    # own scene anchor.  The XML itself is not rewritten when switching views.
    assert abs(room_rect[2] / rect[2] - 1 / 0.85) < 0.000001
    assert mate_position_from_screen(
        center_x=room_rect[0] + room_rect[2] / 2,
        center_y=room_rect[1] + room_rect[3] / 2,
        calibration=mate_room,
    ) == (1, -50)

    with tempfile.TemporaryDirectory(prefix="mate_layout_test_") as temp_name:
        gif_path = Path(temp_name) / "variable.gif"
        _make_variable_gif(gif_path)
        plan = inspect_gif(gif_path, target_fps=30, target_height=384)
        assert abs(plan.duration_seconds - 2.0) < 0.01
        assert plan.output_frame_count == 60
        assert abs(plan.effective_fps - 30) < 0.01
        assert plan.crop_box == (10, 5, 70, 65)
        assert plan.output_size == (384, 384)

        long_gif = Path(temp_name) / "long.gif"
        _make_variable_gif(long_gif, frame_count=60)
        capped = inspect_gif(long_gif, target_fps=30, target_height=384)
        assert capped.output_frame_count == MAX_OUTPUT_FRAMES
        assert capped.capped
        assert capped.effective_fps < capped.requested_fps

    print("Mate placement and GIF sampling checks passed")


if __name__ == "__main__":
    main()
