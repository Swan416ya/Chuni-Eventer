from __future__ import annotations

import argparse
import difflib
import hashlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from chuni_eventer_desktop.pgko_to_c2s import PgkoChartPick, convert_pgko_chart_pick_to_c2s_with_backend


@dataclass
class EvalResult:
    name: str
    backend: str
    same_bytes: bool
    seq_similarity_pct: float
    op_similarity_pct: float
    out_sha256: str
    ref_sha256: str
    top_tag_deltas: list[tuple[str, int]]
    first_diff: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _line_seq_similarity(a: list[str], b: list[str]) -> float:
    n = max(len(a), len(b), 1)
    same_pos = 0
    for i in range(min(len(a), len(b))):
        if a[i] == b[i]:
            same_pos += 1
    return same_pos * 100.0 / n


def _op_similarity(a: list[str], b: list[str]) -> float:
    sm = difflib.SequenceMatcher(a=a, b=b)
    return sm.ratio() * 100.0


def _tag_counts(lines: list[str]) -> Counter[str]:
    c: Counter[str] = Counter()
    for ln in lines:
        if "\t" not in ln:
            continue
        tag = ln.split("\t", 1)[0].strip()
        if tag:
            c[tag] += 1
    return c


def _first_diff_line(a: list[str], b: list[str]) -> str:
    for i, (x, y) in enumerate(zip(a, b), start=1):
        if x != y:
            return f"line {i}: ref={x!r} out={y!r}"
    if len(a) != len(b):
        return f"line-count differs: ref={len(a)} out={len(b)}"
    return "none"


def evaluate_case(name: str, ugc: Path, ref: Path, out: Path) -> EvalResult:
    ref_text = ref.read_text(encoding="utf-8", errors="replace")
    ref_lines = ref_text.splitlines()
    ref_bytes = ref.read_bytes()
    out_path, backend = convert_pgko_chart_pick_to_c2s_with_backend(PgkoChartPick(path=ugc, ext="ugc"))
    out.write_bytes(out_path.read_bytes())
    out_lines = out.read_text(encoding="utf-8", errors="replace").splitlines()
    out_bytes = out.read_bytes()

    ref_tags = _tag_counts(ref_lines)
    out_tags = _tag_counts(out_lines)
    tag_keys = sorted(set(ref_tags) | set(out_tags))
    deltas = [(k, out_tags.get(k, 0) - ref_tags.get(k, 0)) for k in tag_keys]
    deltas = sorted(deltas, key=lambda kv: abs(kv[1]), reverse=True)

    return EvalResult(
        name=name,
        backend=backend,
        same_bytes=(ref_bytes == out_bytes),
        seq_similarity_pct=_line_seq_similarity(ref_lines, out_lines),
        op_similarity_pct=_op_similarity(ref_lines, out_lines),
        out_sha256=_sha256(out),
        ref_sha256=_sha256(ref),
        top_tag_deltas=deltas[:10],
        first_diff=_first_diff_line(ref_lines, out_lines),
    )


def format_result_md(result: EvalResult) -> str:
    tag_delta_text = ", ".join(f"{k}:{v:+d}" for k, v in result.top_tag_deltas) or "none"
    return (
        f"### {result.name}\n"
        f"- backend: `{result.backend}`\n"
        f"- same_bytes: `{result.same_bytes}`\n"
        f"- similarity(seq-pos): `{result.seq_similarity_pct:.2f}%`\n"
        f"- similarity(edit-op): `{result.op_similarity_pct:.2f}%`\n"
        f"- sha256(out/ref): `{result.out_sha256}` / `{result.ref_sha256}`\n"
        f"- first_diff: `{result.first_diff}`\n"
        f"- top_tag_deltas: `{tag_delta_text}`\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate native ugc->c2s similarity against reference c2s.")
    parser.add_argument("--append-doc", default="", help="Optional markdown doc path to append results.")
    parser.add_argument("--title", default="iteration", help="Section title for this run.")
    args = parser.parse_args()

    cases = [
        (
            "Ver seX",
            Path(r"e:/Python Project/Chuni-Eventer/.cache/pgko_downloads/Ver seX/Ver seX/Ver seX.ugc"),
            Path(r"e:/Python Project/Chuni-Eventer/.cache/pgko_downloads/Ver seX/Ver seX/Ver seX.official.bak.c2s"),
            Path(r"e:/Python Project/Chuni-Eventer/.cache/pgko_downloads/Ver seX/Ver seX/Ver seX.ugc_native.c2s"),
        ),
        (
            "Divide et impera!",
            Path(r"e:/Python Project/Chuni-Eventer/.cache/pgko_downloads/Divide et impera!/divide/divide.ugc"),
            Path(r"e:/Python Project/Chuni-Eventer/.cache/pgko_downloads/Divide et impera!/divide/divide.official.bak.c2s"),
            Path(r"e:/Python Project/Chuni-Eventer/.cache/pgko_downloads/Divide et impera!/divide/divide.ugc_native.c2s"),
        ),
    ]

    results = [evaluate_case(name, ugc, ref, out) for name, ugc, ref, out in cases]
    section = [f"## {args.title}", ""]
    for r in results:
        r2 = EvalResult(
            name=f"{r.name}（{args.title}）",
            backend=r.backend,
            same_bytes=r.same_bytes,
            seq_similarity_pct=r.seq_similarity_pct,
            op_similarity_pct=r.op_similarity_pct,
            out_sha256=r.out_sha256,
            ref_sha256=r.ref_sha256,
            top_tag_deltas=r.top_tag_deltas,
            first_diff=r.first_diff,
        )
        section.append(format_result_md(r2))
        section.append("")
    text = "\n".join(section).strip() + "\n"
    print(text)

    if args.append_doc:
        doc_path = Path(args.append_doc)
        prev = doc_path.read_text(encoding="utf-8", errors="replace") if doc_path.exists() else ""
        if prev and not prev.endswith("\n"):
            prev += "\n"
        doc_path.write_text(prev + "\n" + text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
