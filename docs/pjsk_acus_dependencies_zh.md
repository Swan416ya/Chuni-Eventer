# PJSK 转写 ACUS：依赖与环境

本文说明「乐曲 → 新增 → PJSK → 转写选中到 ACUS」流程所需的 Python 包与外部工具。

## Python 依赖（pip）

在项目根目录执行：

```text
pip install -r requirements.txt
```

与 PJSK / 音频相关的条目包括：

| 包 | 作用 |
|----|------|
| `PyCriCodecsEx` | 将 48 kHz WAV 编码为加密 HCA，并生成中二用 `musicXXXX.acb` / `.awb`（与 PenguinTools 思路一致） |
| `quicktex` | 将 `封面.png` 转为 BC3(DXT5) 夹克 DDS（可不装 **compressonator**，二选一即可） |

其余 UI 依赖见 `requirements.txt` 全文。

## 外部程序

| 工具 | 作用 |
|------|------|
| **ffmpeg** | 必须加入 **PATH**。用于：裁掉 PJSK 长音频前约 9 秒空白、重采样为 48 kHz 立体声 16-bit WAV，供 ACB 管线使用。 |

安装示例（需自行下载对应系统版本）：

- Windows：从 [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html) 获取构建，把 `ffmpeg.exe` 所在目录加入 PATH。

## 可选：compressonatorcli

若未安装 `quicktex`，可在应用 **设置** 中配置 **compressonatorcli** 可执行文件路径，用于封面 → DDS。

## 验证

在终端中：

```text
python -c "import PyCriCodecsEx; print('PyCriCodecsEx OK')"
ffmpeg -version
```

若第一句报错，请执行 `pip install PyCriCodecsEx`；若 `ffmpeg` 找不到，请检查 PATH。
