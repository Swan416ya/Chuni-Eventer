# CHUNITHM Mate 与 emote 动画格式研究 & GIF→Mate 生成器说明

## 一、Mate 是什么

CHUNITHM（新版本）新增的收藏品类型 **mate（伴侣）**：一种可在游戏内展示动画的小人/角色收藏品。
官方数据位于更新包的 `mate/mate{ID6}/` 目录，由 3~4 类文件组成：

| 文件 | 作用 | 自制难度 |
|---|---|---|
| `Mate.xml` | mate 元数据：名字、贴图引用、emote 动画引用、动作列表（actions） | ✅ 模板化即可 |
| `CHU_UI_Mate_{ID}.dds` | mate 立绘/图标（1024×1024 BC3/DXT5） | ✅ 现有 DDS 编码链 |
| `emote{ID}.emtbytes` | **emote 动画本体**（M2 PSB 格式） | ⚠️ 本生成器的核心 |
| `lipsync*.txt` | 口型数据（可缺省，mate030001 就没有） | ❌ 不需要 |

参考样本（`MateA001/mate/`）：
- `mate000101`（ナイ）：22 个 lipsync + 21 个动作，isLipSync=true
- `mate030000`（ユニ）：95 个动作（18 标准 + 74 个 actionType=200 状态动作）
- `mate030001`（イクシア）：**最简结构** —— 仅 3 个文件，无 lipsync、无 voice、全部 cueId=0，95 个动作

## 二、emtbytes 格式真相

- 文件头 `PSB\x00` + version 4：**M2 公司（株式会社イクセル）的 PSB 格式**，即商业软件
  **emote Editor** 的动画工程运行时格式（emote 引擎已被 CHUNITHM 等音游/视觉小说使用）。
- 本作数据**未加密**（PsbDecompile 可直接完整解包；M2 也有加密变体，本作未使用）。
- 动画本质：**骨骼/网格 + 时间轴关键帧**。部件（part）在时间轴上通过 `frameList`
  关键帧驱动，关键帧的 `content.icon` 引用贴图分块（UV 区域或分块 id），
  `content.coord` 控制位置 —— **在时间轴上依次切换 icon 即"序列帧动画"**，
  这正是 GIF 转 mate 的可行性基础。
- 结构要点（PSB JSON，PsbDecompile 解包后）：
  - 顶层：`object`（部件集合）/ `source.tex`（贴图 + 分块表）/ `metadata`（入口配置）
  - 入口：`metadata.base = {chara: "all_parts", motion: "タイムライン構造"}`
  - 调度链：`all_parts` → `タイムライン構造` → `全体構造`（layer 树，type=3 节点按
    `label`(part名)+`content.icon`(动画名) 引用各 part 的动画，`priority` 数组决定渲染顺序）
  - part：`{metadata, motion: {动画名: {...}}, type}`，动画含 `layer`（可嵌套，
    `layerIndexMap` + `priority` 管理层级）
  - 帧：`{content, time, type}`，type=2 为内容帧（icon 显示 / coord 位置），type=0 结束帧

**兼容性关键（踩坑记录）**：
- 动画 layer 必须带 `stencilType / objTriPriority / meshDivision / meshSyncChildMask`
  字段，缺失会导致 EMT 引擎加载时 Segfault（PsBuild 不会补默认值）。
- 被调度树直接引用的 part 其动画 layer 配置参考 `body_parts`（type=2 / meshTransform=0 /
  parameterize=null）；icon 帧参考 `face_parts/口_基礎`（mask=33554432、mesh 可为 null）。
- 贴图为 DXT5 2048×2048；PsBuild 编译时自动把 PNG 资源编码为 DXT5（无需预转 DDS）。

## 三、Live2D → emote 转换（不可行）

社区曾尝试将 Live2D（moc3）转为 emote PSB —— **格式层面不可行**：
Live2D 是网格形变 + 物理参数，emote 是骨骼 + 关键帧，底层模型不同，无转换器存在
（FreeMote 作者 UlyssesWu 在 issue #144 明确答复两者为竞品无法互转）。
emote Editor 商业软件官网已不可访问，无法从零手 K 动画。
**因此"上传 GIF 生成 mate"是当前唯一可行的自制带动画 mate 的路径**（GIF 天然是序列帧）。

## 四、GIF → Mate 生成器（本项目实现）

### 使用方式
ACUS 管理界面 → 其他分类 → **伴侣（Mate）** → 选择 GIF → 填显示名 → 生成。

### 生成流程
```
GIF → Pillow 解析(帧/时长/透明度) → 抽帧 ≤32 → 每帧 256×256 居中(透明背景)
    → 拼 2048×2048 sprite sheet(8×4 网格) → PSB JSON(基于官方结构模板)
    → FreeMote PsBuild 编译 → emote{ID}.emtbytes
    → 图标 DDS(第一帧放大 1024×1024, BC3) → Mate.xml(仿 mate030001 最简)
    → ACUS/mate/mate{ID6}/ (3 文件)
```

### 生成产物结构
- `Mate.xml`：**多个动作（初期化/喜ぶ/怒り/哀しい/アニメ）全部引用同一个
  emtbytes** —— 与官方"18+74 个动作共用 1 个动画文件"的机制一致；玩家在游戏里
  点任意表情按钮都会播放上传的 GIF 动画。无 lipsync、无 voice、cueId=0
  （参考 mate030001 最简结构）。
- `emote{ID}.emtbytes`：官方 PSB 结构模板 + 新增 `gif_parts` 部件（帧切换动画）
  + 调度树挂载（z-order 更新）；官方部件动画保留但分块 UV 重写指向帧 0 区域
  （观感统一，不显示官方立绘碎片）。

### 代码结构
| 文件 | 作用 |
|---|---|
| `chuni_eventer_desktop/mate_psb.py` | PSB JSON 构造（模板加载/帧动画/挂载）+ PsBuild 编译调用 + FreeMote 定位 |
| `chuni_eventer_desktop/mate_from_gif.py` | GIF 解析/抽帧/sprite sheet/Mate.xml 生成主流程 |
| `chuni_eventer_desktop/ui/mate_add_dialog.py` | 对话框（GIF 选择 + QTimer 帧预览 + ID 自动分配） |
| `chuni_eventer_desktop/data/mate_template/template.json` | PSB 结构模板（官方骨架，无官方素材内容） |
| `tools/FreeMote/` | FreeMote v4.7.0 工具（PsBuild/PsbDecompile/EmtConvert + lib），懒人包自动打包到 `.tools/FreeMote` |

### 验证方式
- 端到端：生成后可用 FreeMoteViewer 打开 `emote{ID}.emtbytes` 预览播放
  （`tools/FreeMote/FreeMoteViewer.exe`，开发期工具）。
- 结构回读：`PsbDecompile.exe emote{ID}.emtbytes` 解包，检查 `gif_parts` 帧列表、
  调度挂载、贴图尺寸。
- **最终验证需游戏内实测**：放入 ACUS 后确认动画播放、位置、动作触发是否符合预期。

### 限制与后续
- GIF 帧数 ≤ 32、单帧 256×256（贴图 2048×2048 上限，与官方一致）。
- 动画时间轴固定 61 帧（约 1 秒循环，与官方一致）；GIF 更长时会在 1 秒处循环播放。
- 位置/大小由 `Mate.xml` 的 `posX/posY/scaleX10000` 控制（可后续做成可配置）。
- 进阶（未实现）：多 GIF 对应多动作（需要动作→motion 映射机制实验，存在不确定性）。
