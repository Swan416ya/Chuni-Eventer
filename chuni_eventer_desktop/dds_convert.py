from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence


class DdsToolError(RuntimeError):
    pass


def validate_compressonator_tool(tool_path: Path) -> None:
    """
    配置里若误填「当前目录 .」或文件夹，exists() 仍为真但无法执行，会导致 PermissionError。
    在调用 subprocess 前先做校验并给出可读错误。
    """
    p = tool_path.expanduser()
    try:
        p = p.resolve(strict=False)
    except OSError as e:
        raise DdsToolError(f"DDS 工具路径无效：{e}") from e
    if not p.exists():
        raise DdsToolError(f"DDS 工具路径不存在：{p}")
    if p.is_dir():
        raise DdsToolError(
            "DDS 工具路径指向的是「文件夹」而不是可执行文件。\n"
            "常见误操作：填了「.」或选了目录；请在【设置】里选择 compressonatorcli 的本体文件。"
        )
    if not p.is_file():
        raise DdsToolError(f"DDS 工具路径不是可用的可执行文件：{p}")


def run_cmd(argv: Sequence[str]) -> None:
    if not argv:
        raise DdsToolError("命令为空")
    validate_compressonator_tool(Path(argv[0]))
    try:
        p = subprocess.run(list(argv), capture_output=True, text=True)
    except PermissionError as e:
        raise DdsToolError(
            "无法执行 DDS 工具（权限被拒绝或路径不是可执行文件）。\n"
            f"当前配置：{argv[0]}\n"
            "请打开【设置】重新选择 compressonatorcli 的实际路径（不要填「.」或文件夹）。"
        ) from e
    except OSError as e:
        raise DdsToolError(f"启动 DDS 工具失败：{e}") from e
    if p.returncode != 0:
        raise DdsToolError(
            "命令执行失败：\n"
            f"cmd: {' '.join(argv)}\n"
            f"exit: {p.returncode}\n"
            f"stdout:\n{p.stdout}\n"
            f"stderr:\n{p.stderr}\n"
        )


def convert_to_bc3_dds(*, tool_path: Path | None, input_image: Path, output_dds: Path) -> None:
    """
    图片 → BC3(DXT5) DDS。

    优先使用可选依赖 **quicktex**（纯 Python 侧编码）；失败或未安装时再尝试 **compressonatorcli**。
    """
    from . import dds_quicktex

    last: Exception | None = None
    if dds_quicktex.quicktex_available():
        try:
            dds_quicktex.encode_image_to_bc3_dds_quicktex(input_image=input_image, output_dds=output_dds)
            return
        except Exception as e:
            last = e

    if tool_path is not None:
        try:
            validate_compressonator_tool(tool_path)
            tool = str(tool_path)
            output_dds.parent.mkdir(parents=True, exist_ok=True)
            run_cmd([tool, "-fd", "BC3", str(input_image), str(output_dds)])
            return
        except Exception as e:
            last = e

    hint = (
        "请任选其一：\n"
        "1) pip install quicktex（推荐，可不装 compressonator）\n"
        "2) 在【设置】中配置 compressonatorcli 可执行文件路径"
    )
    if last is not None:
        raise DdsToolError(f"生成 BC3 DDS 失败。\n{hint}\n\n底层错误：{last}") from last
    raise DdsToolError(f"无法生成 BC3 DDS：未安装 quicktex 且未配置 compressonatorcli。\n{hint}")


def convert_dds_to_png(*, tool_path: Path | None, input_dds: Path, output_png: Path) -> None:
    """
    DDS → PNG（预览用）。

    优先 **quicktex** 解码；失败或未安装时用 **compressonatorcli**。
    """
    from . import dds_quicktex

    last: Exception | None = None
    if dds_quicktex.quicktex_available():
        try:
            dds_quicktex.dds_to_png_quicktex(input_dds=input_dds, output_png=output_png)
            return
        except Exception as e:
            last = e

    if tool_path is not None:
        try:
            validate_compressonator_tool(tool_path)
            tool = str(tool_path)
            output_png.parent.mkdir(parents=True, exist_ok=True)
            run_cmd([tool, str(input_dds), str(output_png)])
            return
        except Exception as e:
            last = e

    hint = "请 pip install quicktex，或在【设置】配置 compressonatorcli。"
    if last is not None:
        raise DdsToolError(f"DDS 转 PNG 失败（可能为不支持的 DDS 变体，如 DX10）。\n{hint}\n\n底层错误：{last}") from last
    raise DdsToolError(f"无法预览 DDS：未安装 quicktex 且未配置 compressonatorcli。\n{hint}")

