from __future__ import annotations

"""
可选依赖：quicktex（PyPI）可在纯 Python 流程中解码/编码 BC3(DXT5) DDS。

- 预览：read + decode → PNG
- 生成：PIL Image + BC3Encoder + DXT5 → DDS

不支持 DX10 头等特殊 DDS；失败时可回退到 compressonatorcli（若已配置）。
"""

import subprocess
import sys
from pathlib import Path

from .cli_flags import QUICKTEX_WORKER_ARG


def _package_parent_dir() -> Path:
    """含 `chuni_eventer_desktop` 包的目录（用于子进程 -m 导入时的 cwd）。"""
    return Path(__file__).resolve().parents[1]


def quicktex_available() -> bool:
    try:
        import quicktex.dds  # noqa: F401

        return True
    except ImportError:
        return False


def dds_to_png_quicktex(*, input_dds: Path, output_png: Path) -> None:
    from quicktex.dds import read as dds_read

    dds = dds_read(input_dds)
    img = dds.decode()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_png, "PNG")


def _rgba_padded_to_multiple_of_4(image):
    """
    DXT/BC3 按 4×4 块压缩；非 4 对齐的宽高在部分 Windows 环境下会触发 quicktex 原生访问冲突。
    用透明像素在右下方向补齐（不改变已绘制内容）。
    """
    from PIL import Image

    image = image.convert("RGBA")
    w, h = image.size
    nw = (w + 3) // 4 * 4
    nh = (h + 3) // 4 * 4
    if nw == w and nh == h:
        return image.copy()
    canvas = Image.new("RGBA", (nw, nh), (0, 0, 0, 0))
    canvas.paste(image, (0, 0))
    return canvas


def encode_bc3_inprocess(
    *,
    input_image: Path,
    output_dds: Path,
    quality_level: int = 18,
    mip_count: int = 1,
) -> None:
    """
    在当前进程内调用 quicktex 编码（可能因原生 bug 直接崩溃，仅供子进程 worker 使用）。
    """
    from PIL import Image, UnidentifiedImageError
    from quicktex.dds import encode as dds_encode
    from quicktex.s3tc.bc3 import BC3Encoder

    try:
        with Image.open(input_image) as im:
            im.seek(0)
            im.load()
            image = _rgba_padded_to_multiple_of_4(im.convert("RGBA").copy())
    except UnidentifiedImageError as e:
        raise RuntimeError(f"无法识别图片格式：{input_image}") from e
    except OSError as e:
        raise RuntimeError(f"无法读取图片文件：{input_image}\n{e}") from e

    # 与 quicktex CLI 默认一致：不在这里做垂直翻转；若实机贴图上下颠倒再单独加开关
    dds_file = dds_encode(image, BC3Encoder(quality_level), "DXT5", mip_count=mip_count)
    output_dds.parent.mkdir(parents=True, exist_ok=True)
    dds_file.save(output_dds)


def encode_image_to_bc3_dds_quicktex(
    *,
    input_image: Path,
    output_dds: Path,
    quality_level: int = 18,
    mip_count: int = 1,
) -> None:
    """
    使用 quicktex 将常见位图转为 DXT5/BC3 单级 mipmap DDS（与 CLI `encode bc3` 同类）。

    始终在**子进程**中执行编码，避免 Windows 上 quicktex 原生崩溃/访问冲突拖垮 PyQt 主进程。

    - 开发环境：``python -m chuni_eventer_desktop.quicktex_worker ...``
    - PyInstaller：``ChuniEventer.exe --chuni-quicktex-worker ...``（run_desktop 入口在启动 GUI 前转交 quicktex_worker）
    """
    in_p = str(input_image.resolve())
    out_p = str(output_dds.resolve())
    q = str(quality_level)
    m = str(mip_count)

    if getattr(sys, "frozen", False):
        cmd = [sys.executable, QUICKTEX_WORKER_ARG, in_p, out_p, q, m]
        popen_kw: dict = {}
    else:
        root = _package_parent_dir()
        cmd = [
            sys.executable,
            "-m",
            "chuni_eventer_desktop.quicktex_worker",
            in_p,
            out_p,
            q,
            m,
        ]
        popen_kw = {"cwd": str(root)}

    if sys.platform == "win32":
        popen_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            **popen_kw,
        )
    except OSError as e:
        raise RuntimeError(f"无法启动 quicktex 子进程：{e}") from e

    if p.returncode == 0:
        return

    err = (p.stderr or p.stdout or "").strip()
    # Windows: 0xC0000005 STATUS_ACCESS_VIOLATION，常见于 quicktex 原生编码器
    if p.returncode in (-1073741819, 3221225477):
        hint = (
            "quicktex 在子进程内发生访问冲突（access violation），主界面已保持运行。\n"
            "打包版请在【设置】中填写 compressonatorcli 完整路径并保存，"
            "生成 BC3 时将优先使用 Compressonator（比 quicktex 更稳）。"
        )
        err = f"{hint}\n\n{err}" if err else hint
    elif not err:
        err = (
            f"quicktex 编码子进程异常结束（exit {p.returncode}）。"
            "若在部分图片上稳定复现，多为 quicktex 在 Windows 上的原生问题，"
            "可在【设置】中配置 compressonatorcli 作为回退。"
        )
    raise RuntimeError(err)
