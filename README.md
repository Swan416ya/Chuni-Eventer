# chuni eventer desktop

一个最小的 Python 桌面端工具（PyQt6）：选择 3 张角色图片（大头/半身/全身）+ 输入角色 ID（基ID+变体），然后自动：

- 写入程序目录自带的 `ACUS/` 工作区（按 A001 路径规则）
- 生成 `ACUS/ddsImage/ddsImage{ID6位}/DDSImage.xml`
- 生成 `ACUS/chara/chara{ID6位}/Chara.xml`（默认立绘引用 `ddsImage`）
- 将三张图片转换为 **BC3(DXT5)** 的 `.dds`（需要外部转换工具）

## 安装与运行

在 `desktop/` 目录下：

```bash
python3 -m pip install -r requirements.txt
python3 -m chuni_eventer_desktop
```

## DDS 转换工具（必需）

### 为什么不能“纯 Python 内置 BC3 压缩”？（重要）

- **BC3(DXT5) 属于块压缩纹理格式**，编码器实现复杂且速度敏感。\n+- 纯 Python 直接实现/集成成熟编码器通常不可行（性能/依赖/授权），因此本工具当前采用“外部 CLI”方案。\n+- **预览**（DDS→图片）理论上可以用 Python 解码库做，但编码（图片→BC3 DDS）仍更适合用原生库/工具。

本工具目前会调用外部命令行工具进行转换。你需要安装其一，并在 UI 里配置可执行文件路径：

- **Compressonator CLI**：`compressonatorcli`（跨平台）

转换命令形如：

```bash
compressonatorcli -fd BC3 input.png output.dds
```

## 输出结构

输出会写到 `desktop/ACUS/`，结构类似：

```
ACUS/
  chara/chara024690/Chara.xml
  ddsImage/ddsImage024690/DDSImage.xml
  ddsImage/ddsImage024690/CHU_UI_Character_2469_00_00.dds   # 大头
  ddsImage/ddsImage024690/CHU_UI_Character_2469_00_01.dds   # 半身
  ddsImage/ddsImage024690/CHU_UI_Character_2469_00_02.dds   # 全身
```

