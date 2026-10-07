"""PJSK 官谱 → CHUNITHM 链路（上游转换器 + 应用侧接线）。

- :mod:`.core`     —— 上游 ``pjsk2chuni/pjsk2chuni.py`` 原样收录（.sus → .ugc/.c2s 的语义转换）。
- :mod:`.pipeline` —— 本软件侧接线：元数据补全、音频偏移测量、PenguinTools ``option build`` 打包、
  规范化与写入 ACUS。

规格与裁定依据见上游 ``pjsk2chuni/docs/01-why.md`` … ``08-environment.md``。
"""

from __future__ import annotations

from . import core, pipeline

__all__ = ["core", "pipeline"]
