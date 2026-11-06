# Chuni-Eventer v0.8.5

## 更新内容

### 新增：用 GIF 生成伴侣（Mate）

从这一版开始，「新增 → 伴侣」可以直接吃一张透明背景的 GIF，生成能导入游戏的 E-mote 伴侣，
不再需要手工做 PSB、写 Mate.xml、算缩放。

- **自动处理整条管线**：检测有效画面 → 裁掉透明边 → 按 10 FPS 抽帧（单条动画最多 120 帧）→
  编译 emtbytes → 生成 Mate.xml 与伴侣图标，直接写进 ACUS 的 `mate/` 目录。
- **帧高可选 256 / 320 / 384 / 512（默认 384）**。伴侣在游戏里大约画到 900 像素高，
  帧越高越锐利，但每一帧都是整帧 RGBA8 纹理加 mip 链，体积按平方增长——
  ACUS 里的 mate 是会被游戏整包读进内存的，帧高再往上加会让 emtbytes 涨到 GB 级并直接卡死加载，
  所以这里只提供到 512。官方自己也是把多帧打进 2048×2048 图集来省体积。
- **分组动作配置**：简单模式按 6 个场景组替换 GIF（平常 / 待机 / 交互 / 特殊等），
  详细模式可以为 18 个动作槽逐个选 GIF；留空的槽自动复用主 GIF。
  多条 GIF 会各自成为一条独立 timeline，打包进同一个 PSB。
- **每个动作单独摆位置/缩放**：预览里按动作槽保存 posX / posY / scale，
  附结算页与 Mate ROOM 的参考底图，方便对着真实界面调。
- **图标（400×256 卡片）两种来路**：点「生成图标…」上传立绘，拖动/滚轮缩放后合成 PNG；
  或者直接自动取 GIF 首帧。两种方式在 GIF 模式下都可用。
- **布局校准**：从游戏的 SRD 反解出 xml 单位到屏幕像素的换算（0.85），
  按帧高推荐 scale，保证不同大小的 GIF 导入后不会突兀地变大变小。
- 逆向细节记录在 `docs/mate-action-types-reverse-engineering.md` 与
  `docs/mate-layout-reverse-engineering.md`。

### 新增：奖励类型支持「伴侣(Mate)」与「头像配件(AvatarAccessory)」

以前这两类奖励只能读、不能在软件里选，现在「新建 Reward」和「配置格子奖励」都能直接选：

- **伴侣(Mate)**：奖励类型 14，`reward.id = 150000000 + 伴侣 id`，列表里按伴侣名挑选，
  写出的 Reward.xml 里带正确的 `mate/mateName/id`。
- **头像配件(AvatarAccessory)**：奖励类型 9，`reward.id = 100000000 + 配件 id`，
  候选列表按槽位标注（衣服 / 帽子 / 面具 / 手部 / 披风），格子缩略图会解码配件贴图直接显示。
- 地图资源包的闭包与资源引用图都认识这两类：导出时会顺着奖励把伴侣绑定的角色（chara）、
  系统语音（systemVoice）和配件贴图一并带进包内。

### 修复：地图资源包「文件已损坏」

- **先写临时文件再落盘**：导出先写 `xxx.zip.part`，写完重新打开校验条目数与 CRC，通过后才原子替换成正式文件名。
  以前是直接往目标文件名里写，大图（含伴侣动画时能到几百 MB）写的过程中用压缩软件打开、
  或者中途关掉软件，就会看到没有中央目录的残包——这就是「该文件已损坏」的来源。
- **导出改到后台线程**：不再卡界面；关闭窗口时会等后台导出收尾，不会留下半截文件。
- 包内补齐伴侣绑定的角色与系统语音；导出完成的提示会按分类列出数量。

### 其它

- 预览类弹窗的滑块统一成 Fluent Slider；各页说明收敛为一行正文 + ⓘ 细则弹窗；
  错误提示统一走 `fly_critical`；进度弹窗运行中禁止关闭，结束后正常回收。
- 修复 PsBuild 遇到已经是 common 平台的 PSB 时会把它重新编译坏的问题，现在保留原文件。
- 外部工具 PenguinTools.CLI 升级到 2.5.3：谱面转换新增 UGC v9 与 MGXC v4 支持，
  懒人包内自带新的 ffmpeg / texconv / image-tools 资源（不再依赖旧的 mua）。

## 环境要求

- 伴侣（GIF → E-mote）需要 **FreeMote** 工具链（PsBuild / PsbDecompile）：懒人包已内置在 `.tools\FreeMote`。
- DDS 转换默认走 exe 内置的 quicktex；需要离线回退时用 `-IncludeCompressonator` 构建完整懒人包，
  或在「设置 → 外部工具」下载。
- 烤谱（PJSK / pgko）仍需 PenguinTools.CLI 与 ffmpeg，懒人包自带，Lite 单 exe 首次运行时按需下载。

## 打包说明

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\build_windows.ps1" -Version 0.8.5
```

- **懒人包**：`dist\Chuni-Eventer-v0.8.5.zip`
- **Lite 单 exe**：`dist\release\ChuniEventer.exe`

## 升级提示

- 从 v0.8.3 升级：懒人包建议整包替换；Lite 单 exe 可直接覆盖。
- 之前用高帧高生成过伴侣的，确认 mate 目录里 emtbytes 还在几百 MB 以内；如果曾经涨到 GB 级，
  建议按 384 重新生成一次再导入游戏。
- 升级前建议备份 ACUS 与自定义资源目录。
