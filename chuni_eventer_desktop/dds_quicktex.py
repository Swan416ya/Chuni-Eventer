from __future__ import annotations

"""
可选依赖：quicktex（PyPI）可在纯 Python 流程中解码/编码 BC3(DXT5) DDS。

- 预览：read + decode → PNG
- 生成：PIL Image + BC3Encoder + DXT5 → DDS

不支持 DX10 头等特殊 DDS；失败时可回退到 compressonatorcli（若已配置）。
"""

from pathlib import Path


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


def encode_image_to_bc3_dds_quicktex(
    *,
    input_image: Path,
    output_dds: Path,
    quality_level: int = 18,
    mip_count: int = 1,
) -> None:
    """
    使用 quicktex 将常见位图转为 DXT5/BC3 单级 mipmap DDS（与 CLI `encode bc3` 同类）。
    """
    from PIL import Image
    from quicktex.dds import encode as dds_encode
    from quicktex.s3tc.bc3 import BC3Encoder

    image = Image.open(input_image)
    # 与 quicktex CLI 默认一致：不在这里做垂直翻转；若实机贴图上下颠倒再单独加开关
    dds_file = dds_encode(image, BC3Encoder(quality_level), "DXT5", mip_count=mip_count)
    output_dds.parent.mkdir(parents=True, exist_ok=True)
    dds_file.save(output_dds)
