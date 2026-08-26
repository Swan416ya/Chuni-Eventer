# Chuni-Eventer v0.8.1

## 更新内容

### 新功能

- **图片裁剪编辑器**：新建跑图背景（ddsMap）或地图图标（MapIcon）时，源图片行新增「✂ 编辑裁剪…」按钮。导入图片后可滚轮缩放、中键/右键平移，左键拖拽比例锁定的选区（支持四角/四边手柄调整、整体平移、选区外重画）。选区允许超出原图边界，超出部分导出时补透明，最终按选区导出固定尺寸 PNG（ddsMap 1220×680 / MapIcon 256×256）。原有的自动裁切兜底流程保持不变，编辑器为可选增强。
- **PenguinTools 2.0 迁移**：转谱工具 PenguinTools.CLI 升级到 2.0，仓库迁移至 [ChuniPingu/PenguinTools](https://github.com/ChuniPingu/PenguinTools)。CLI 改为 Native AOT 编译（启动更快、无需单独安装 .NET 运行时），并内置 CRI 音频工具与 mua 媒体工具（mua_wav / mua_img）。「设置 - 外部工具」中的一键下载已同步适配新的 AOT.zip 包结构。

### 修复

- **修复角色立绘压缩过度发糊的问题**（[#14](https://github.com/Swan416ya/Chuni-Eventer/issues/14)）：DDS 编码器的回退顺序此前把 Pillow 内置 DXT5 编码器排在第一位，而它的质量远低于 quicktex（同一张立绘 PSNR 42dB vs 58dB），导致角色立绘默认走最差编码器。现已调整为 quicktex 优先 → compressonator → Pillow 兜底，角色立绘不再发糊。
- **修复宣传图 / 地图背景 / 音乐封面 / 舞台背景 / 场景墙 DDS 格式错误的问题**（[#14](https://github.com/Swan416ya/Chuni-Eventer/issues/14)）：原版游戏中这些无 alpha 通道的资源使用 DXT1(BC1) 格式，但程序此前对所有资源统一转 BC3(DXT5)，格式不匹配导致游戏内显示异常。现已按资源类型分别选用正确格式——封面/地图背景/宣传图/舞台/场景墙走 BC1(DXT1)，角色立绘/名牌/奖杯/avatar/地图图标等带 alpha 资源保持 BC3(DXT5)。新生成的封面 DDS 与原版文件大小完全一致。
- 场景墙贴图格式同步从 BC3 修正为 BC1。

## 打包说明

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\build_windows.ps1" -Version 0.8.1
```

- **懒人包**：`dist\Chuni-Eventer-v0.8.1.zip`
- **Lite 单 exe**：`dist\release\ChuniEventer.exe`

## 升级提示

- 从 v0.8.0 升级：懒人包建议整包替换；Lite 单 exe 可直接覆盖。
- 建议升级前备份当前 ACUS 与自定义资源目录。
- 如果之前用 v0.8.0 生成过角色立绘 / 封面 / 宣传图 / 地图背景等资源并发现发糊或显示异常，升级后重新生成即可。
