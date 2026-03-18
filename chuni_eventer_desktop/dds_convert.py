from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence


class DdsToolError(RuntimeError):
    pass


def run_cmd(argv: Sequence[str]) -> None:
    p = subprocess.run(list(argv), capture_output=True, text=True)
    if p.returncode != 0:
        raise DdsToolError(
            "命令执行失败：\n"
            f"cmd: {' '.join(argv)}\n"
            f"exit: {p.returncode}\n"
            f"stdout:\n{p.stdout}\n"
            f"stderr:\n{p.stderr}\n"
        )


def convert_to_bc3_dds(*, tool_path: Path, input_image: Path, output_dds: Path) -> None:
    """
    Convert image to BC3(DXT5) DDS using Compressonator CLI.

    Requires:
      compressonatorcli -fd BC3 input output
    """
    tool = str(tool_path)
    output_dds.parent.mkdir(parents=True, exist_ok=True)
    run_cmd([tool, "-fd", "BC3", str(input_image), str(output_dds)])


def convert_dds_to_png(*, tool_path: Path, input_dds: Path, output_png: Path) -> None:
    """
    Best-effort DDS -> PNG conversion for preview.

    Compressonator CLI generally supports format conversion by input/output extension.
    """
    tool = str(tool_path)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    run_cmd([tool, str(input_dds), str(output_png)])

