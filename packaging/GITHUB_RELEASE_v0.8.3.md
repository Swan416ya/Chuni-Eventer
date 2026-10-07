# Chuni-Eventer v0.8.3

## 更新内容

### PJSK 烤谱（Project SEKAI → CHUNITHM）全面重做

「烤谱」从实验性功能转正：入口移到 **乐曲页 →「新增」→ PJSK**（与 SwanSite / pgko 并列），
设置页的实验性区域不再有它。谱面来源保持原样（PJSK 官方资源镜像），转谱与打包整条链路换新。

- **转谱逻辑换上游语义转换器**：不再把 SUS 直接丢给 PenguinTools 暴力转。装饰性音符按裁定表降级为装饰线（ALD），
  Slide 曲线用 Margrete Interpolator 烘焙，Skip / Friction / Guide / Flick 分别落到中二的 TAP / CHR / HOLD / SLIDE / AIR，
  `#TIL00` 变速时间轴转成 SLP 保留——**打不中的装饰音符不会再变成判定音符**。
- **音频不再对不上**：旧版把片头固定裁掉 9 秒，遇到 filler 不是 9 秒的曲子必然整体错位。
  现在按 **pjsk 官方的 `musics.json.fillerSec`**（长音频开头静音长度，游戏就是拿它对谱）裁片头，
  再交 PenguinTools 完成响度归一与 ACB/AWB 封装。
  实测对比：某曲 `fillerSec` = 8.05 秒，而"探测第一个非静音采样"会量到 9.03 秒（差近 1 秒）——
  靠实测的旧做法会让这类曲子整体偏 1 秒，所以延迟值一律以元数据为准（元数据缺失时才退回实测）。
- **定数自动换算**：各难度默认定数 = PJSK 等级（1～38）等比映射到中二 1～15.5：

  ```
  定数 = 1 + (PJSK等级 - 1) × (15.5 - 1) / (38 - 1)
  ```

  例：PJSK 24 → 10.01、29 → 11.97、32 → 13.15。下载谱面时会把每个难度的 PJSK 等级记进缓存清单，
  老缓存会在打开时自动补全；映射值只是默认值，随时可手工改。
- **打包**：由官方 `PenguinTools.CLI option build` 一次产出 c2s / 封面 DDS / HCA 音频（ACB·AWB）/
  Music.xml / CueFile.xml，再规范化（c2s 用 CRLF、XML 去 BOM）写入 ACUS，并自动补 MusicSort 与 ULT 解锁事件。
- 音频对齐/打包有完整校验：ACB 时长必须等于「裁切后音频 + 一小节」，SOFFSET 必须正好把谱面后移一小节，
  缺文件会直接报错而不是静默产出半成品。

### 修复：PenguinTools.CLI 自动下载与安装

- **兜底版本号是死链**：API 取不到最新版本时会回退到内嵌的 `v2.0.0`，但该 Release 在 GitHub 上并不存在（必然 404）。
  已改为当前最新的 `v2.4.0`。
- **运行时资产校验过严**：v2.4.0 起上游把媒体后端从 `mua + CRI` 换成自带的 `ffmpeg + texconv`，
  旧校验会误报「运行时资源不完整」导致下载成功也装不上。现在两套布局任一可用即通过。
- **安装漏了原生依赖**：v2.4.0 的封面转换依赖根目录的 `libvips-42.dll`，旧安装逻辑只复制 `exe + assets/`，
  会导致打包**静默丢失封面 DDS**（CLI 仍报成功）。现在整包复制（丢弃 .pdb）。

> 如果所在网络访问不了 GitHub，自动下载仍会失败——这属于网络环境问题，请自行通过代理/镜像解决；
> 软件的下载与安装逻辑本身已按上游最新产物校正。

### 修复：PJSK 曲目数据库取不到

- 曲目列表 / 难度等级 / 音频延迟（`fillerSec`）/ 人声版本依赖 `api.pjsek.ai`（可能整体 503）与 GitHub 直连（部分网络不可达）。
  现在这两个源不可用时会回退到镜像（`gh-proxy.com` / `ghproxy.net` / `gcore.jsdelivr.net`），
  并把结果缓存到 `.cache/pjsk_master/`：12 小时内直接读缓存，网络全断也能用最近一次的数据。
- 谱面 / 封面 / 长音频的资源链路不变（`assets.pjsek.ai`、`storage.sekai.best`）。

### 其它

- 删除旧的「SUS 直接转 c2s」实现与写 ACUS 时的 c2s-sanitize 后处理（问题改为在转换源头修正）；
  下载缓存不再预热生成 `chuni/*.c2s` 与 `chuni_cue/`。
- 新增 `docs/pjsk_to_chuni_zh.md`：链路结构、音频对齐、数据源可用性、验证方法一页看完。

## 环境要求

- 烤谱需要 **PenguinTools.CLI**（支持 `option build`）与 **ffmpeg**：
  懒人包已内置；Lite 单 exe 可在「设置 → 外部工具」一键下载（当前最新 v2.4.0）。

## 打包说明

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\build_windows.ps1" -Version 0.8.3
```

- **懒人包**：`dist\Chuni-Eventer-v0.8.3.zip`
- **Lite 单 exe**：`dist\release\ChuniEventer.exe`

## 升级提示

- 从 v0.8.2 升级：懒人包建议整包替换；Lite 单 exe 可直接覆盖。
- 若你此前用实验性烤谱生成过谱面，建议删掉重新烤一遍（判定音符与音频对齐都变了）。
- 升级前建议备份 ACUS 与自定义资源目录。
