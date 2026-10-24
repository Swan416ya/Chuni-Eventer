"""Game-accurate Mate placement math for result and Mate ROOM previews.

The constants in this module come from the local CHUNITHM 2.50 artifacts:

* ``posX``/``posY`` are forwarded as integer E-mote coordinates.
* ``scaleX10000`` is converted with the literal float ``0.0001``.
* ``Mate.xml`` requests a 1024 x 1024 E-mote render target.
* the result SRD displays that target on a 1080 x 1080 ``C_emote_body`` image,
  centred at (1610, 636), with a 0.85 cast scale.

Keeping this math outside Qt makes it testable and prevents the editor and
the generated defaults from drifting apart again.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path

SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080


@dataclass(frozen=True)
class MateSceneCalibration:
    """Placement of the E-mote dynamic-texture surface in one game scene."""

    scene_key: str = "result"
    scene_label: str = "结算画面"
    anchor_x: float = 1610.0
    anchor_y: float = 636.0
    cast_scale: float = 0.85
    surface_width: float = 1080.0
    surface_height: float = 1080.0
    render_target_width: float = 1024.0
    render_target_height: float = 1024.0
    source: str = "CHU_UI_Result_00_v10 (built-in calibration)"

    @property
    def emote_to_screen(self) -> float:
        """Compatibility alias for the X-axis XML-to-screen ratio."""
        return self.emote_x_to_screen

    @property
    def emote_x_to_screen(self) -> float:
        return self.surface_width / self.render_target_width * self.cast_scale

    @property
    def emote_y_to_screen(self) -> float:
        return self.surface_height / self.render_target_height * self.cast_scale

    @property
    def surface_rect(self) -> tuple[float, float, float, float]:
        """Displayed dynamic-texture rectangle in 1920 x 1080 coordinates."""
        width = self.surface_width * self.cast_scale
        height = self.surface_height * self.cast_scale
        return self.anchor_x - width / 2, self.anchor_y - height / 2, width, height


MateResultCalibration = MateSceneCalibration

DEFAULT_RESULT_CALIBRATION = MateSceneCalibration()
DEFAULT_MATE_ROOM_CALIBRATION = MateSceneCalibration(
    scene_key="mate_room",
    scene_label="Mate ROOM",
    anchor_x=960.0,
    anchor_y=552.0,
    cast_scale=1.0,
    source="CHU_UI_MateGarden_00 (built-in calibration)",
)


def _trs_entries(blob: bytes, start: int) -> list[tuple[float, float, float]]:
    """Read the four compact TRS2 entries used by the result character casts."""
    end = blob.find(b"vtc0", start + 8)
    section = blob[start : end if end >= 0 else start + 512]
    entries: list[tuple[float, float, float]] = []
    cursor = 0
    while len(entries) < 4:
        marker = section.find(b"\x34\x4a", cursor)
        if marker < 0 or marker + 11 > len(section):
            break
        x, y = struct.unpack_from("<ff", section, marker + 3)
        scale_marker = section.find(b"\x36\x4a\x00", marker + 11, marker + 48)
        if scale_marker < 0 or scale_marker + 11 > len(section):
            break
        scale_x, _scale_y = struct.unpack_from("<ff", section, scale_marker + 3)
        if all(abs(value) < 100_000 for value in (x, y, scale_x)):
            entries.append((x, y, scale_x))
        cursor = scale_marker + 11
    return entries


def calibration_from_game(
    game_root: Path | None,
    scene: str = "result",
) -> MateSceneCalibration:
    """Extract an active Mate surface transform from the installed game SRD.

    A safe built-in calibration is returned if this game version uses another
    SRD layout.  No game file is copied into the application.
    """
    fallback = (
        DEFAULT_MATE_ROOM_CALIBRATION
        if scene == "mate_room"
        else DEFAULT_RESULT_CALIBRATION
    )
    if game_root is None:
        return fallback
    if scene == "mate_room":
        candidates = [
            Path(game_root)
            / "data"
            / "surfboard"
            / "play"
            / "mateGarden"
            / "CHU_UI_MateGarden_00.srd"
        ]
        layer_name = b"L_MateGarden_chara"
    else:
        result_dir = Path(game_root) / "data" / "surfboard" / "play" / "result"
        candidates = list(result_dir.glob("CHU_UI_Result_00_v*.srd"))
        layer_name = b"C_chara_control"
    if not candidates:
        return fallback

    def version(path: Path) -> int:
        match = re.search(r"_v(\d+)$", path.stem)
        return int(match.group(1)) if match else -1

    for path in sorted(candidates, key=version, reverse=True):
        try:
            blob = path.read_bytes()
            names = blob.find(layer_name)
            trs = blob.find(b"TRS2", names)
            if names < 0 or trs < 0:
                continue
            entries = _trs_entries(blob, trs)
            if len(entries) < 4:
                continue
            parent_x, parent_y, parent_scale = entries[0]
            chara_x, chara_y, chara_scale = entries[1]
            emote_x, emote_y, emote_scale = entries[3]
            anchor_x = parent_x + chara_x * parent_scale + emote_x * parent_scale * chara_scale
            anchor_y = parent_y + chara_y * parent_scale + emote_y * parent_scale * chara_scale
            cast_scale = parent_scale * chara_scale * emote_scale
            if 0 < cast_scale < 4 and -SCREEN_WIDTH <= anchor_x <= SCREEN_WIDTH * 2:
                return MateSceneCalibration(
                    scene_key=scene,
                    scene_label="Mate ROOM" if scene == "mate_room" else "结算画面",
                    anchor_x=anchor_x,
                    anchor_y=anchor_y,
                    cast_scale=cast_scale,
                    source=path.name,
                )
        except (OSError, ValueError, struct.error):
            continue
    return fallback


def mate_content_rect(
    *,
    source_size: tuple[int, int],
    pos_x: int,
    pos_y: int,
    scale_x10000: int,
    calibration: MateSceneCalibration = DEFAULT_RESULT_CALIBRATION,
) -> tuple[float, float, float, float]:
    """Return the visible source bounds in 1920 x 1080 screen coordinates."""
    source_w, source_h = source_size
    scale = scale_x10000 / 10_000.0
    width = source_w * calibration.emote_x_to_screen * scale
    height = source_h * calibration.emote_y_to_screen * scale
    center_x = calibration.anchor_x + pos_x * calibration.emote_x_to_screen
    center_y = calibration.anchor_y + pos_y * calibration.emote_y_to_screen
    return center_x - width / 2, center_y - height / 2, width, height


def mate_position_from_screen(
    *,
    center_x: float,
    center_y: float,
    calibration: MateSceneCalibration = DEFAULT_RESULT_CALIBRATION,
) -> tuple[int, int]:
    """Inverse of the XML position part of :func:`mate_content_rect`."""
    return (
        round((center_x - calibration.anchor_x) / calibration.emote_x_to_screen),
        round((center_y - calibration.anchor_y) / calibration.emote_y_to_screen),
    )


def recommended_scale_for_height(
    source_height: int,
    target_screen_height: int = 900,
    calibration: MateSceneCalibration = DEFAULT_RESULT_CALIBRATION,
) -> int:
    """Scale needed for an alpha-cropped source to reach a screen height."""
    return round(target_screen_height * 10_000 / (max(1, source_height) * calibration.emote_y_to_screen))
