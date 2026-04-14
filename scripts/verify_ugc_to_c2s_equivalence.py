from __future__ import annotations

import argparse
import difflib
import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chuni_eventer_desktop.pgko_to_c2s import PgkoChartPick, convert_pgko_chart_pick_to_c2s_with_backend


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert a UGC chart to c2s and compare with a reference c2s file."
    )
    parser.add_argument("--ugc", required=True, help="Path to .ugc chart file")
    parser.add_argument("--ref", required=True, help="Path to reference .c2s file")
    parser.add_argument(
        "--show-diff-lines",
        type=int,
        default=120,
        help="Max number of unified diff lines to print when mismatch",
    )
    args = parser.parse_args()

    ugc_path = Path(args.ugc).resolve()
    ref_path = Path(args.ref).resolve()
    if not ugc_path.is_file():
        raise FileNotFoundError(f"UGC file not found: {ugc_path}")
    if not ref_path.is_file():
        raise FileNotFoundError(f"Reference c2s file not found: {ref_path}")

    ref_bytes = ref_path.read_bytes()
    ref_text = ref_path.read_text(encoding="utf-8", errors="replace")

    out_path, backend = convert_pgko_chart_pick_to_c2s_with_backend(
        PgkoChartPick(path=ugc_path, ext="ugc")
    )
    out_path = out_path.resolve()

    out_bytes = out_path.read_bytes()
    same = ref_bytes == out_bytes

    print(f"backend: {backend}")
    print(f"ugc: {ugc_path}")
    print(f"out: {out_path}")
    print(f"ref: {ref_path}")
    print(f"same_bytes: {same}")
    print(f"out_sha256: {_sha256(out_path)}")
    print(f"ref_sha256: {_sha256(ref_path)}")

    if same:
        return 0

    ref_lines = ref_text.splitlines()
    out_lines = out_path.read_text(encoding="utf-8", errors="replace").splitlines()
    diff = list(
        difflib.unified_diff(
            ref_lines,
            out_lines,
            fromfile=str(ref_path),
            tofile=str(out_path),
            lineterm="",
        )
    )
    if not diff:
        # Encoding/newline-level mismatch fallback.
        print("Mismatch detected in bytes but no textual diff lines were produced.")
        return 1

    max_lines = max(1, int(args.show_diff_lines))
    print(f"--- unified diff (showing first {max_lines} lines) ---")
    for line in diff[:max_lines]:
        print(line)
    if len(diff) > max_lines:
        print(f"... ({len(diff) - max_lines} more diff lines omitted)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
