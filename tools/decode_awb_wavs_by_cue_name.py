"""
Decode each subsong in a CHUNITHM-style ``.awb`` to WAV.

Output names come **only from the paired ``.acb``** (Cue names aggregated per
WaveformTable slot). Alias cues sharing one waveform become ``0011_0100.wav``.

Audio decode still uses vgmstream on the ``.awb``; HCA stream titles are **not**
used for naming.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from PyCriCodecsEx.acb import ACB
from PyCriCodecsEx.awb import AWB


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _vgmstream_cli() -> Path:
    p = _repo_root() / "tools" / "vgmstream" / "vgmstream-cli.exe"
    if not p.is_file():
        raise FileNotFoundError(f"缺少 {p}")
    return p


def _wf_key(w: object) -> tuple[int, int, int, int, int]:
    return (
        int(w.NumSamples),
        int(w.SamplingRate),
        int(w.EncodeType),
        int(w.Streaming),
        int(w.NumChannels),
    )


def _cue_names_primary_sort_key(name: str) -> int:
    base = name.strip().split(";")[0].strip()
    return int(base) if base.isdigit() else 999_999


def _fs_safe_label(lab: str) -> str:
    for ch in '<>:"/\\|?*':
        lab = lab.replace(ch, "_")
    return lab or "unnamed"


def _slot_labels_from_acb(acb_path: Path) -> list[str]:
    """
    One label per ``WaveformTable`` row / AWB blob (0..N-1), derived from all
    cues that reference that waveform (streaming banks: match by audio key tuple).
    """
    acb = ACB(str(acb_path))
    v = acb.view
    n = len(v.WaveformTable)
    slot_names: list[set[str]] = [set() for _ in range(n)]

    for k in range(len(v.CueTable)):
        try:
            wfs = list(v.waveform_of(v.CueTable[k].CueId))
        except Exception:
            continue
        if not wfs:
            continue
        cue_nm = v.CueNameTable[k].CueName
        for wf in wfs:
            hits = [
                i
                for i, row in enumerate(v.WaveformTable)
                if _wf_key(row) == _wf_key(wf)
            ]
            if len(hits) != 1:
                raise RuntimeError(
                    f"{acb_path.name}: cue {cue_nm!r} waveform key {_wf_key(wf)!r} "
                    f"matched rows {hits!r} (expected exactly one)"
                )
            slot_names[hits[0]].add(cue_nm)

    # CHUNITHM systemVoice：0100～0113 与 0011～0024 共用波形，但 PyCriCodecsEx 对这批行
    # ``waveform_of`` 会因 Sequence/Track 索引解析失败；按官方表结构并入同一 AWB 槽位。
    for k in range(61, min(75, len(v.CueTable))):
        wf_idx = k - 51
        if 0 <= wf_idx < n:
            slot_names[wf_idx].add(v.CueNameTable[k].CueName)

    labels: list[str] = []
    for i, names in enumerate(slot_names):
        if not names:
            labels.append(f"__missing_wf{i}")
            continue
        merged = "_".join(sorted(names, key=_cue_names_primary_sort_key))
        labels.append(_fs_safe_label(merged))

    return _uniquify_labels(labels)


def _uniquify_labels(labels: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for lab in labels:
        if lab not in seen:
            seen[lab] = 1
            out.append(lab)
        else:
            seen[lab] += 1
            out.append(f"{lab}__dup{seen[lab]}")
    return out


def decode_awb_bank(*, acb_or_awb: Path, dry_run: bool = False) -> list[Path]:
    acb_or_awb = acb_or_awb.resolve()
    if acb_or_awb.suffix.lower() == ".acb":
        acb_path = acb_or_awb
        awb = acb_or_awb.with_suffix(".awb")
        stem = acb_or_awb.stem
    else:
        awb = acb_or_awb
        stem = awb.stem
        acb_path = awb.with_suffix(".acb")

    if not awb.is_file():
        raise FileNotFoundError(awb)
    if not acb_path.is_file():
        raise FileNotFoundError(
            f"需要同目录下的 ACB 以解析 Cue 名：{acb_path}（与 {awb.name} 同名）"
        )

    cli = _vgmstream_cli()
    folder = awb.parent
    written: list[Path] = []

    labels = _slot_labels_from_acb(acb_path)
    n_py = AWB(str(awb)).numfiles
    if len(labels) != n_py:
        raise ValueError(
            f"{acb_path.name}: WaveformTable 条数 {len(labels)} 与 AWB 内文件数 {n_py} 不一致"
        )

    if not dry_run:
        for p in folder.iterdir():
            if (
                p.is_file()
                and p.suffix.lower() == ".wav"
                and p.name.lower().startswith(stem.lower())
            ):
                try:
                    p.unlink()
                except OSError:
                    pass

    for s in range(1, n_py + 1):
        lab = labels[s - 1]
        out = folder / f"{stem}_{lab}.wav"
        if dry_run:
            print(out.name)
            continue
        r = subprocess.run(
            [str(cli), "-s", str(s), "-o", str(out), str(awb)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if r.returncode != 0:
            raise RuntimeError(f"decode failed subsong={s}: {r.stderr or r.stdout}")
        written.append(out)
    return written


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Decode AWB subsongs to WAV files named from paired ACB cue names."
    )
    ap.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="``.acb`` or ``.awb`` paths (default: scan audio_test/test)",
    )
    ap.add_argument(
        "--scan-root",
        type=Path,
        default=None,
        help="If no paths given, glob ``**/systemvoice*.acb`` under this directory.",
    )
    ap.add_argument("--dry-run", action="store_true", help="Print output names only.")
    args = ap.parse_args()

    paths = [p.resolve() for p in args.paths]
    if not paths:
        root = (args.scan_root or (_repo_root() / "audio_test" / "test")).resolve()
        paths = sorted(root.glob("**/systemvoice*.acb"))
        paths = [p for p in paths if "repacked" not in p.parts]

    if not paths:
        print("No .acb files found.", file=sys.stderr)
        sys.exit(1)

    for p in paths:
        print(f"=== {p.parent.name} / {p.name} ===")
        decode_awb_bank(acb_or_awb=p, dry_run=args.dry_run)
        if not args.dry_run:
            print(f"  wrote {AWB(str(p.with_suffix('.awb'))).numfiles} wav(s)")


if __name__ == "__main__":
    main()
