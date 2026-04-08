from __future__ import annotations

import subprocess
import shutil
import struct
import sys
from pathlib import Path
from typing import Sequence


class DdsToolError(RuntimeError):
    pass


def _dds_fourcc(path: Path) -> str | None:
    """读取 DDS 像素格式 FourCC；非 DDS 或读取失败返回 None。"""
    try:
        raw = path.read_bytes()
    except Exception:
        return None
    if len(raw) < 128 or raw[:4] != b"DDS ":
        return None
    # DDS_HEADER starts at offset 4; ddspf.dwFourCC at absolute offset 84
    fourcc = raw[84:88]
    try:
        return fourcc.decode("ascii")
    except Exception:
        return None


def is_bc3_dds(path: Path) -> bool:
    """
    仅接受 BC3(DXT5)：
    - legacy header: FourCC == DXT5
    - DX10 header: FourCC == DX10 and dxgiFormat == 77 (DXGI_FORMAT_BC3_UNORM)
    """
    fourcc = _dds_fourcc(path)
    if fourcc is None:
        return False
    if fourcc == "DXT5":
        return True
    if fourcc != "DX10":
        return False
    try:
        raw = path.read_bytes()
        if len(raw) < 148:
            return False
        dxgi_format = struct.unpack_from("<I", raw, 128)[0]
        return dxgi_format == 77
    except Exception:
        return False


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
    tool_exe = Path(argv[0])
    validate_compressonator_tool(tool_exe)
    popen_kw: dict = {"cwd": str(tool_exe.parent)}
    if sys.platform == "win32":
        popen_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        p = subprocess.run(list(argv), capture_output=True, text=True, **popen_kw)
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

    默认优先 **Pillow DDS(DXT5)**（纯内置、打包稳定），失败时尝试 **quicktex**，
    最后回退 **compressonatorcli**（若已配置）。

    说明：Pillow 的 DDS 写出为内置编码路径，不依赖外部 exe，可提升打包版可用性。
    """
    from . import dds_quicktex

    last: Exception | None = None

    def _try_quicktex() -> bool:
        nonlocal last
        if not dds_quicktex.quicktex_available():
            return False
        try:
            dds_quicktex.encode_image_to_bc3_dds_quicktex(
                input_image=input_image, output_dds=output_dds
            )
            return True
        except Exception as e:
            last = e
            return False

    def _try_pillow_dds() -> bool:
        nonlocal last
        try:
            from PIL import Image

            with Image.open(input_image) as im:
                rgba = im.convert("RGBA")
                output_dds.parent.mkdir(parents=True, exist_ok=True)
                rgba.save(output_dds, format="DDS", pixel_format="DXT5")
            if not is_bc3_dds(output_dds):
                raise DdsToolError("Pillow 已输出 DDS，但格式校验不是 BC3(DXT5)。")
            return True
        except Exception as e:
            last = e
            return False

    def _try_compress() -> bool:
        nonlocal last
        if tool_path is None:
            return False
        try:
            validate_compressonator_tool(tool_path)
            tool = str(tool_path)
            output_dds.parent.mkdir(parents=True, exist_ok=True)
            run_cmd([tool, "-fd", "BC3", str(input_image), str(output_dds)])
            return True
        except Exception as e:
            last = e
            return False

    if _try_pillow_dds():
        return
    if _try_quicktex():
        return
    if _try_compress():
        return

    hint = (
        "可用转换链路均失败：Pillow DDS(DXT5) -> quicktex -> compressonatorcli。\n"
        "请在【设置】中测试各路径，并优先确认输入图片可被 PIL 正常读取。"
    )
    if last is not None:
        raise DdsToolError(f"生成 BC3 DDS 失败。\n{hint}\n\n底层错误：{last}") from last
    raise DdsToolError(f"无法生成 BC3 DDS。\n{hint}")


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


def ingest_to_bc3_dds(*, tool_path: Path | None, input_path: Path, output_dds: Path) -> None:
    """
    导入到目标 BC3 DDS：
    - 输入是 .dds：校验必须为 BC3 后直接复制
    - 其它图片：转换为 BC3 DDS
    """
    output_dds.parent.mkdir(parents=True, exist_ok=True)
    if input_path.suffix.lower() == ".dds":
        if not is_bc3_dds(input_path):
            raise DdsToolError("检测到上传的是 DDS，但不是 BC3(DXT5) 格式；请先转换为 BC3 后再导入。")
        shutil.copy2(input_path, output_dds)
        return
    convert_to_bc3_dds(tool_path=tool_path, input_image=input_path, output_dds=output_dds)

