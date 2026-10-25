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
ACUS 管理界面 → 其他分类 → **伴侣（Mate）** → 选择主 GIF → 填显示名 → 配置动作 → 生成。

动作页提供两种模式：

- 简略配置：将 18 个槽按真实触发场景合并为 6 组；
- 详细配置：逐项覆盖 Type 1～18，未选择的槽继承简略组；
- 每一组或每一个槽都可以选择不同 GIF，留空则复用主 GIF。

### 生成流程
```
一个或多个 GIF → Pillow 解析(帧/时长/透明度) → 每条按真实时长重采样 ≤120 帧
    → 透明边界联合裁切 → PSB JSON(基于官方结构模板)
    → 每条 GIF 建立独立子 motion + timelineControl 动作选择器
    → FreeMote PsBuild 编译 → emote{ID}.emtbytes
    → 图标 DDS(第一帧放大 1024×1024, BC3) → Mate.xml(仿 mate030001 最简)
    → ACUS/mate/mate{ID6}/ (3 文件)
```

### 生成产物结构
- `Mate.xml`：18 个 actionType 按简略组或详细覆盖映射到生成的 GIF timeline；无
  lipsync、无 voice、cueId=0（参考 mate030001 最简结构）。
- `emote{ID}.emtbytes`：仍然只有一个文件，但可包含多条 GIF 子 motion；自定义的
  `gif_action` 参数由 `timelineControl` 切换当前子 motion。重复使用同一 GIF 的槽位
  共享同一套帧资源，不会重复打包。

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
- 每条 GIF 最多输出 120 帧，保留源 GIF 总时长并换算到 E-mote 60 tick/s 时间轴；
  超过上限时降低有效采样帧率，不会强制压成 1 秒。
- 每条 GIF 会生成独立纹理资源；18 条完全不同且帧数很高的 GIF 会显著增大
  `emtbytes`。界面允许这样配置，但实际制作时建议让相近评价复用同一条 GIF。
- 位置/大小由 `Mate.xml` 的 `posX/posY/scaleX10000` 控制（可后续做成可配置）。
- 多 GIF 已通过 PsBuild 编译、PsbDecompile 回读和 Mate.xml 映射测试；最终仍建议在
  对应游戏版本中实测一次动作切换与显存占用。
