# Derived from Soyandroid/suspect src/formats/c2s.py (CHUNITHM c2s serialization).

from __future__ import annotations

from abc import ABC

C2S_TICKS_PER_MEASURE = 384

# c2s 页脚：谱面首判定点相对音频的补偿。suspect 模板曾用 100/100，易使谱面整体偏晚、听感上音乐超前。
C2S_FOOTER_FIRST_MSEC = 0
C2S_FOOTER_FIRST_RES = 0


class C2sObject(ABC):
    measure: int = 0
    tick: int = 0


class BpmSetting(C2sObject):
    bpm: float = 0.0

    def __str__(self) -> str:
        return "BPM\t%s\t%s\t%.3f" % (self.measure, self.tick, self.bpm)


class MeterSetting(C2sObject):
    signature: tuple[int, int] = (0, 0)

    def __str__(self) -> str:
        return "MET\t%s\t%s\t%s\t%s" % (
            self.measure,
            self.tick,
            self.signature[0],
            self.signature[1],
        )


class SpeedSetting(C2sObject):
    length: int = 0
    speed: float = 1.0

    def __str__(self) -> str:
        return "SFL\t%s\t%s\t%s\t%s" % (
            self.measure,
            self.tick,
            self.length,
            self.speed,
        )


class TimelineSpeedSetting(C2sObject):
    length: int = 0
    speed: float = 1.0
    timeline: int = 0

    def __str__(self) -> str:
        return "SLP\t%s\t%s\t%s\t%s\t%s" % (
            self.measure,
            self.tick,
            self.length,
            self.speed,
            self.timeline,
        )


class C2sNote(C2sObject):
    lane: int = 0
    width: int = 0


class TapNote(C2sNote):
    def __str__(self) -> str:
        return "TAP\t%s\t%s\t%s\t%s" % (
            self.measure,
            self.tick,
            self.lane,
            self.width,
        )


class MineNote(C2sNote):
    def __str__(self) -> str:
        return "MNE\t%s\t%s\t%s\t%s" % (
            self.measure,
            self.tick,
            self.lane,
            self.width,
        )


class ChargeNote(C2sNote):
    effect: str = "UP"

    def __str__(self) -> str:
        return "CHR\t%s\t%s\t%s\t%s\t%s" % (
            self.measure,
            self.tick,
            self.lane,
            self.width,
            self.effect,
        )


class FlickNote(C2sNote):
    direction_tag: str = "L"

    def __str__(self) -> str:
        return "FLK\t%s\t%s\t%s\t%s\t%s" % (
            self.measure,
            self.tick,
            self.lane,
            self.width,
            self.direction_tag,
        )


class AirHold(C2sNote):
    length: int = 0

    def __str__(self) -> str:
        return "AHD\t%s\t%s\t%s\t%s\tTAP\t%s" % (
            self.measure,
            self.tick,
            self.lane,
            self.width,
            self.length,
        )


class HoldNote(C2sNote):
    length: int = 0

    def __str__(self) -> str:
        return "HLD\t%s\t%s\t%s\t%s\t%s" % (
            self.measure,
            self.tick,
            self.lane,
            self.width,
            self.length,
        )


class SlideNote(C2sNote):
    length: int = 0
    end_lane: int = 0
    end_width: int = 0
    is_curve: bool = False

    def __str__(self) -> str:
        tag = "SLC" if self.is_curve else "SLD"
        return "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s" % (
            tag,
            self.measure,
            self.tick,
            self.lane,
            self.width,
            self.length,
            self.end_lane,
            self.end_width,
        )


class AirNote(C2sNote):
    isUp: bool = True
    direction: int = 0
    linkage: str = "TAP"

    def __str__(self) -> str:
        if self.isUp:
            if self.direction > 0:
                tag = "AUR"
            elif self.direction < 0:
                tag = "AUL"
            else:
                tag = "AIR"
        else:
            if self.direction > 0:
                tag = "ADR"
            elif self.direction < 0:
                tag = "ADL"
            else:
                tag = "ADW"
        return "%s\t%s\t%s\t%s\t%s\t%s\tDEF" % (
            tag,
            self.measure,
            self.tick,
            self.lane,
            self.width,
            self.linkage,
        )


def create_file(
    definitions: list,
    notes: list,
    *,
    creator: str,
    bpm_def: float,
    version: str = "1.13.00",
) -> str:
    bpm_s = f"{bpm_def:.3f}"
    cr = creator.strip() or "SUS import"
    header = "\n".join(
        [
            f"VERSION\t{version}\t{version}",
            "MUSIC\t0",
            "SEQUENCEID\t0",
            "DIFFICULT\t0",
            "LEVEL\t0.0",
            f"CREATOR\t{cr}",
            f"BPM_DEF\t{bpm_s}\t{bpm_s}\t{bpm_s}\t{bpm_s}",
            "MET_DEF\t4\t4",
            f"RESOLUTION\t{C2S_TICKS_PER_MEASURE}",
            f"CLK_DEF\t{C2S_TICKS_PER_MEASURE}",
            "PROGJUDGE_BPM\t240.000",
            "PROGJUDGE_AER\t 0.999",
            "TUTORIAL\t0",
            "",
        ]
    )
    sample_footer = """T_REC_TAP\t999
T_REC_CHR\t999
T_REC_FLK\t999
T_REC_MNE\t999
T_REC_HLD\t999
T_REC_SLD\t999
T_REC_AIR\t999
T_REC_AHD\t999
T_REC_ALL\t999
T_NOTE_TAP\t999
T_NOTE_CHR\t999
T_NOTE_FLK\t999
T_NOTE_MNE\t0
T_NOTE_HLD\t999
T_NOTE_SLD\t999
T_NOTE_AIR\t999
T_NOTE_AHD\t999
T_NOTE_ALL\t999
T_NUM_TAP\t999
T_NUM_CHR\t999
T_NUM_FLK\t999
T_NUM_MNE\t0
T_NUM_HLD\t999
T_NUM_SLD\t999
T_NUM_AIR\t999
T_NUM_AHD\t999
T_NUM_AAC\t999
T_CHRTYPE_UP\t999
T_CHRTYPE_DW\t0
T_CHRTYPE_CE\t0
T_LEN_HLD\t999999
T_LEN_SLD\t999999
T_LEN_AHD\t999999
T_LEN_ALL\t999999
T_JUDGE_TAP\t999
T_JUDGE_HLD\t999
T_JUDGE_SLD\t999
T_JUDGE_AIR\t999
T_JUDGE_FLK\t999
T_JUDGE_ALL\t9999
T_FIRST_MSEC\t{first_msec}
T_FIRST_RES\t{first_res}
T_FINAL_MSEC\t999999
T_FINAL_RES\t999999
T_PROG_00\t46
T_PROG_05\t52
T_PROG_10\t57
T_PROG_15\t43
T_PROG_20\t58
T_PROG_25\t56
T_PROG_30\t55
T_PROG_35\t60
T_PROG_40\t88
T_PROG_45\t51
T_PROG_50\t43
T_PROG_55\t43
T_PROG_60\t44
T_PROG_65\t53
T_PROG_70\t64
T_PROG_75\t65
T_PROG_80\t51
T_PROG_85\t84
T_PROG_90\t52
T_PROG_95\t81
""".format(
        first_msec=int(C2S_FOOTER_FIRST_MSEC),
        first_res=int(C2S_FOOTER_FIRST_RES),
    )
    defs = list(definitions)
    if not any(isinstance(d, MeterSetting) for d in defs):
        m0 = MeterSetting()
        m0.signature = (4, 4)
        m0.measure = 0
        m0.tick = 0
        defs.append(m0)

    body_defs = "\n".join(str(d) for d in defs)
    body_notes = "\n".join(str(n) for n in notes)
    return (
        header
        + body_defs
        + "\n\n"
        + body_notes
        + "\n\n"
        + sample_footer
    )
