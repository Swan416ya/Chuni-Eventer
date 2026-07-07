# 资源压缩包快捷导入 — 架构设计

> 文档版本：v1.1 · 2026-07-07
> 状态：已确认开放问题，待实现
> 关联代码：`map_export_bundle.py`、`acus_scan.py`、`sheet_install.py`、`ui/github_sheet_dialog.py`、`ui/manager_widget.py`

## 0.1 开放问题决策记录（v1.1 更新）

| ID | 决策 | 说明 |
|---|---|---|
| O-1 | **不提供覆盖模式** | 只支持重映射模式 |
| O-2 | **chara 重映射时强制联动重命名 ddsImage 目录** | 包内与该 chara 关联的 ddsImage 目录跟随重命名到新 chara id 对应的 raw6 编码。若 ddsImage 被包内多个 chara 共享，仍执行联动但产生 warning |
| O-3 | **chara/namePlate/stage 从 70000 起，扫 ACUS 取 max+1** | 符合项目"自制资源 70000 起"的隐式约定（ACUS 实测：chara 70120+，namePlate 70004+，stage 70000+） |
| O-4 | **map/mapArea/event/ddsImage/ddsMap/ddsBanner 也分配号段** | 参考现有逻辑：map/mapArea 70000000 起，event/ddsImage 70000 起，ddsMap 70000000 起，ddsBanner 70000 起，mapBonus 10000000 起，mapIcon 扫 ACUS max+1 |
| O-5 | **悬空引用保留原值，不自动删除** | 澄清语义：悬空引用是地图内容的一部分（如官谱作为课题曲），内容不变；只有"被重映射资源的引用方"才需要跟着改 |
| O-6 | **导入入口放设置页** | 具体位置待定，实现时再确认 |

## 0. 设计基线（已勘察事实）

本设计基于对现有代码的实地勘察，关键事实如下：

| 事实 | 来源 | 对新功能的影响 |
|---|---|---|
| 导出包内路径 = 相对 ACUS 根 | `map_export_bundle.export_map_bundle_to_zip` | 导入侧无需发明结构，直接复用 `sheet_install._mapper_for_paths` |
| 引用闭包算法已存在 | `map_export_bundle._expand_*_xml_closure` | 把其中的"收集文件"逻辑反向提炼为"声明式引用表"，复用同一份领域知识 |
| `sheet_install.install_zip_to_acus` 不做冲突检测 | `sheet_install.py:360` | 必须在调用它之前完成重映射，且需新版"非覆盖写入"模式 |
| `_rewrite_package_music_id` 是单 ID 重写器 | `github_sheet_dialog.py:254` | **不能直接复用**：它把所有 `<id>` 文本等于 `old_music_id` 的节点全部改写，会误伤无关资源；且靠字符串替换推导 event/cueFile ID，脆弱。新设计必须按 `(资源类型, ID)` 维度重写 |
| ACUS 侧扫描器齐全 | `acus_scan.scan_*` | 冲突检测的"已有 ID 集合"直接复用 |
| ID 分配器分散且号段不齐 | `unlock_challenge`、`course_rule`、`course_rank` | 需要统一到一个 `ResourceIdAllocator`，并为缺失类型补号段 |
| Map 右键菜单已有"导出资源包" | `manager_widget.py:1258` | 导入入口对称放置：Map 页右键 + 设置页/工具页独立入口 |

---

## 1. 功能概述与 UX 流程

### 1.1 一句话定义

用户选中一个由本工具导出的 map bundle zip，工具自动识别包内全部资源、检测与 ACUS 已有资源的 ID 冲突、对冲突项分配新 ID 并维护包内引用关系链，最终把重映射后的资源写入 ACUS。

### 1.2 操作流程

```
[选包] → [解压到暂存区] → [扫描包内资源清单] 
      → [扫描 ACUS 已有 ID 集合]
      → [冲突检测：包内 ∩ ACUS]
      → [构建包内引用图]
      → [为冲突项分配新 ID，传播到所有引用方]
      → [生成「重映射预览报告」]  ← 用户审阅
      → [用户确认]
      → [在暂存区应用 XML 重写 + 目录/文件重命名]
      → [写入 ACUS（非覆盖模式）]
      → [写入后校验]
      → [报告结果]
```

### 1.3 冲突 UX 决策（推荐方案）

**推荐：自动分配 + 预览报告 + 一键确认**，不逐个询问。

| 方案 | 评价 |
|---|---|
| 逐个询问 | ✗ 一个大包可能含 20+ 冲突，逐个询问极度疲劳；且单个决策无法看到对引用方的影响 |
| **自动分配 + 预览 + 一键确认**（推荐） | ✓ 用户在一张表里看到全部 `(资源, 旧ID→新ID, 冲突原因, 受影响的包内文件数)`，可手动微调个别 ID 后确认 |
| 全自动无预览 | ✗ 用户失去对自制 ID 段的控制感 |

### 1.4 是否提供"覆盖模式"

**推荐：不提供覆盖模式，只支持重映射模式。**

理由：
- 导出包的资源 ID 与 ACUS 已有 ID 相同，几乎必然意味着"不同的资源碰巧用了同一自制号段"，覆盖会丢失用户已有数据，且不可逆。
- "快捷导入"的核心价值是**安全地增量**，覆盖模式与该目标矛盾。
- 若用户确实想覆盖，可直接用现有的 `sheet_install.install_zip_to_acus`（社区谱面导入）——它本来就是直接覆盖。两条路径职责分明。

> **开放问题 O-1**（见 §12）：是否在导入对话框里给一个"高级：直接覆盖（不重映射）"的折返开关，指向 `install_zip_to_acus`？推荐**不**给，避免误操作。

### 1.5 预览报告 UI（Fluent 风格）

预览对话框结构（`ResourcePackImportDialog`，基于 `FluentCaptionDialog`）：

```
┌─ 资源压缩包导入预览 ──────────────────────────┐
│  包：map02006570_acus_bundle.zip              │
│  包内资源：23 项  |  冲突：5 项  |  将重映射：5 │
│ ┌──────────────────────────────────────────┐  │
│  类型    旧ID      新ID      原因  受影响文件 │  │
│  music   7001  →  8421   目录已存在   6      │  │
│  trophy  50012 →  50038  ID已存在     2      │  │
│  ...                                          │  │
│  (双击单元格可手动修改新ID)                    │  │
│ └──────────────────────────────────────────┘  │
│  ⚠ 警告 2 条：包内 trophy#50013 引用 music#9999 │
│           但包内/ACUS 均无此 music，将保留引用  │
│  [折叠详情]                                    │
│                                                │
│           [取消]  [手动调整...]  [确认导入]    │
└────────────────────────────────────────────────┘
```

- 表格用 `fluent_table.apply_fluent_sheet_table` 风格，双击新 ID 列可编辑。
- 手动修改后实时校验：新 ID 是否仍冲突、是否在合法号段内。
- 警告区用 `InfoBar`（warning 级），不阻断确认。

---

## 2. 模块划分

### 2.1 新增模块

| 文件 | 职责 | 行数估算 |
|---|---|---|
| `resource_pack_import.py` | 编排器：解压 → 扫描 → 冲突 → 重映射规划 → 写入 → 校验 | ~400 |
| `resource_reference_graph.py` | 声明式引用规则表 + 引用图构建/查询 | ~350 |
| `resource_id_allocator.py` | 统一 ID 分配器（所有资源类型） | ~200 |
| `resource_xml_rewriter.py` | 字段感知的 XML + 目录/文件名重写器 | ~300 |
| `ui/resource_pack_import_dialog.py` | Fluent 预览/确认对话框 | ~350 |

### 2.2 复用模块（不修改或仅小幅扩展）

| 文件 | 复用点 | 是否修改 |
|---|---|---|
| `acus_scan.py` | 所有 `scan_*` 提供 ACUS 侧 ID 集合 | 不修改 |
| `map_export_bundle.py` | `_resource_dir_by_xml_glob`、`_safe_int`、领域规则作为引用表的来源参考 | 不修改 |
| `sheet_install.py` | `_mapper_for_paths`、`_LEAF_FOLDER_RULES`、`_ACUS_TOP_NAMES_LOWER`、`install_zip_to_acus`（仅用于"非冲突资源"的最终落盘） | **小幅扩展**：新增 `install_zip_to_acus_non_overwriting()`（见 §8.3） |
| `chuni_formats.py` | `ChuniCharaId`（chara addImages 变体目录的 raw6 编码） | 不修改 |
| `system_voice_pack.py` | `system_voice_dir_name`、`cue_folder_name`、`cue_numeric_id_for_voice` | 不修改 |
| `unlock_challenge.py` / `course_rule.py` / `course_rank.py` | 现有 ID 分配常量与函数 | 不修改（allocator 内部调用它们） |

### 2.3 模块依赖

```
resource_pack_import.py
   ├── resource_reference_graph.py  (引用规则 + 图)
   ├── resource_id_allocator.py     (分配新 ID)
   ├── resource_xml_rewriter.py     (应用重映射)
   ├── acus_scan.py                 (ACUS 侧 ID 集合)
   ├── sheet_install.py             (最终落盘)
   └── (解压/校验用标准库)

ui/resource_pack_import_dialog.py
   └── resource_pack_import.py  (调用编排器，渲染预览)
```

---

## 3. ID 冲突检测算法

### 3.1 包内资源扫描

对解压后的暂存区根 `staging_root`，按资源类型分类扫描。复用 `acus_scan` 的扫描函数，但传入 `staging_root` 而非 `acus_root`（它们结构同构）。

```python
# resource_pack_import.py
@dataclass(frozen=True)
class PackageResource:
    kind: str               # "music" | "trophy" | "chara" | ... (见 3.3 枚举)
    resource_id: int        # XML name/id
    xml_path: Path          # 相对 staging_root
    dir_path: Path          # 资源目录（xml_path.parent）
    extra: dict             # 类型特定字段，如 systemVoice 的 cue_numeric_id

def scan_package_resources(staging_root: Path) -> list[PackageResource]:
    """
    复用 acus_scan.scan_music/scan_trophies/... 
    把结果统一映射为 PackageResource。
    对 systemVoice 额外计算 cue_numeric_id（用于冲突判定）。
    """
```

### 3.2 ACUS 已有资源扫描

直接调用 `acus_scan.scan_*(acus_root)`，构建 `used_ids: dict[str, set[int]]`（kind → id 集合）。

对 `systemVoice` 额外纳入 cueFile 目录名集合（与现有 `system_voice_pack` 的 cue 分配逻辑一致）。

### 3.3 资源类型枚举

```python
RESOURCE_KINDS = (
    "map", "mapArea", "mapBonus", "event", "reward",
    "music", "cueFile", "stage", "chara", "ddsImage", "ddsMap",
    "namePlate", "trophy", "mapIcon", "systemVoice",
    "avatarAccessory", "ticket", "quest", "course",
    "charaWorks", "skill", "skillCategory", "musicGenre", "musicLabel",
    "releaseTag", "netOpen", "gauge", "timeTable", "notesFieldLine", "ddsBanner",
)
```

### 3.4 冲突判定标准

**主判据：资源 ID 是否已存在于 ACUS 同类型集合中。** 不依赖目录名比对（目录名是 ID 的派生）。

| 类型 | 冲突判定 |
|---|---|
| music / trophy / chara / namePlate / mapIcon / stage / event / reward / quest / map / mapArea / mapBonus / avatarAccessory / ticket / ddsImage / ddsMap / ddsBanner / charaWorks / skill / skillCategory / musicGenre / musicLabel / releaseTag / netOpen / gauge / timeTable / notesFieldLine | `resource_id in used_ids[kind]` |
| systemVoice | `voice_id in used_ids["systemVoice"]` **或** 其 `cue_numeric_id in used_ids["cueFile"]` |
| cueFile | `cue_id in used_ids["cueFile"]` |
| course | `course_id in used_ids["course"]`（扫所有 Course.xml name/id） |

### 3.5 包内重复 ID 检测

扫描时若发现包内同 kind 出现两个相同 `resource_id`，标记为 **包格式错误**（见 §9），不进入重映射，直接报错要求用户修包。

### 3.6 冲突清单数据结构

```python
@dataclass(frozen=True)
class ConflictEntry:
    kind: str
    old_id: int
    reason: str              # "ACUS 已有同 ID" / "ACUS 已有同 cueFile" 等
    package_resource: PackageResource
    referencing_files: list[Path]  # 包内引用此资源的文件（来自引用图）

@dataclass(frozen=True)
class ConflictReport:
    conflicts: tuple[ConflictEntry, ...]
    clean_resources: tuple[PackageResource, ...]  # 无冲突，保留原 ID
    package_warnings: tuple[str, ...]             # 引用悬空等（见 §9）
```

---

## 4. ID 重映射算法（核心）

### 4.1 重映射优先级

**关键洞察**：重映射的传播方向是"被引用者变 → 引用方跟着变"。因此分配新 ID 时无需考虑优先级——所有冲突项独立分配新 ID，然后**一次性传播**到所有引用方。优先级只在"号段用尽时谁让路"这类极端场景才有意义，正常路径不需要。

但有一个**约束**：若两个冲突项属于同一类型且新 ID 分配需要保持相对顺序（如 unlockChallenge 需连续 5 个 course ID），分配器需感知"块分配"。本设计把这种块分配封装在 allocator 内部，对调用方暴露 `allocate(kind, count=1)`。

### 4.2 引用关系图构建

引用图是**有向二部图**：节点 = 资源（按 `(kind, id)` 唯一），边 = 引用（source_xml 中某 xpath 指向 target 资源）。

```python
# resource_reference_graph.py
@dataclass(frozen=True)
class RefEdge:
    source_file: Path          # 引用方 XML（相对 staging_root）
    source_kind: str           # 引用方资源类型
    xpath: str                 # id 字段的 xpath（如 "stageName/id"）
    target_kind: str           # 被引用资源类型
    target_id: int             # 被引用 ID
    in_package: bool           # target 是否在包内（False = 指向 ACUS 已有）

class ReferenceGraph:
    nodes: dict[tuple[str, int], PackageResource]   # (kind, id) → 资源
    edges: list[RefEdge]
    _by_source: dict[Path, list[RefEdge]]            # 按引用方文件索引
    _by_target: dict[tuple[str, int], list[RefEdge]] # 按被引用方索引

    def build(staging_root: Path, resources: list[PackageResource]) -> "ReferenceGraph":
        """根据声明式引用表（§5.1），解析所有包内 XML，提取引用边。"""
    
    def referencers_of(kind: str, resource_id: int) -> list[RefEdge]:
        """查询：谁引用了 (kind, id)？用于重映射传播。"""
```

### 4.3 重映射规划（Plan 阶段，零写入）

```python
@dataclass(frozen=True)
class RemapEntry:
    kind: str
    old_id: int
    new_id: int
    reason: str

@dataclass(frozen=True)
class RemapPlan:
    remaps: dict[tuple[str, int], int]   # (kind, old_id) → new_id
    file_edits: dict[Path, list[FieldEdit]]  # 每个文件要改的字段
    dir_renames: list[tuple[Path, Path]]     # 目录重命名
    file_renames: list[tuple[Path, Path]]    # 文件重命名（jacket/c2s 等）
    warnings: tuple[str, ...]
    errors: tuple[str, ...]                  # 非空则不可应用

def plan_remap(
    *, staging_root: Path, graph: ReferenceGraph,
    conflicts: ConflictReport, allocator: ResourceIdAllocator,
) -> RemapPlan:
    """
    1. 为每个冲突项分配新 ID：remaps[(kind, old_id)] = allocator.allocate(kind)
    2. 对每条引用边：
       a. 若 target 在 remaps 中 → 在 source_file 的对应 xpath 产生 FieldEdit(old, new)
       b. 若 target 不在包内且不在 ACUS → 产生 warning（悬空引用），不产生 edit
       c. 若 target 不在包内但在 ACUS → 不产生 edit（外部引用，保持原样）
    3. 计算目录/文件重命名（基于 remaps + §6.3 命名规则）
    4. 校验：新 ID 是否仍冲突（allocator 已保证不冲突，但二次校验防御）
    """
```

### 4.4 重映射传播规则

| 被重映射的资源 | 传播到哪些文件的哪些字段 |
|---|---|
| `music` (id: M→M') | 包内所有 XML 中 xpath 命中 `music/.../id`、`musicName/id`、`selectMusic/musicName/id` 的节点；Music.xml 自身 `name/id`；目录 `music{M:04d}` → `music{M':04d}`；文件 `CHU_UI_Jacket_{M:04d}.dds`、`{M:04d}_{idx:02d}.c2s` |
| `trophy` (T→T') | Reward.xml `trophy/trophyName/id`；Trophy.xml 自身 `name/id`；Quest.xml `keyTrophyName/id`；目录 `trophy{T:06d}` → `trophy{T':06d}` |
| `chara` (C→C') | Reward.xml `chara/charaName/id`；Quest.xml `keyCharaName/id`；**其他 Chara.xml 的 `addImages{n}/charaName/id`**；目录 `chara{C:06d}` → `chara{C':06d}`；**变体目录 `chara{C*10}` → `chara{C'*10}`**；联动 `ddsImage{raw6(C)}` → `ddsImage{raw6(C')}`（见 §6.4） |
| `namePlate` (N→N') | Reward.xml `namePlate/namePlateName/id`；Quest.xml `keyNamePlateName/id`；目录 `namePlate{N:08d}` → `namePlate{N':08d}` |
| `systemVoice` (V→V') | Reward.xml `systemVoice/systemVoiceName/id`；目录 `systemVoice{V:04d}` → `systemVoice{V':04d}`；**联动 cueFile**：若 cue_id 也冲突则一并重映射 cueFile 目录 |
| `cueFile` (Q→Q') | Music.xml `cueFileName/id`；目录 `cueFile{Q:06d}` → `cueFile{Q':06d}` |
| `stage` (S→S') | Music.xml `stageName/id`；Reward.xml(type=13) `stage/stageName/id`；目录 `stage{S}` |
| `map` | Event.xml `substances/map/mapName/id`；目录 `map{ID}` |
| `event` (E→E') | Map.xml `stopReleaseEventName/id`；Event.xml 自身 `name/id`；目录 `event{E:08d}` → `event{E':08d}` |
| `reward` (R→R') | Map.xml `infos/.../rewardName/id`；MapArea.xml `grids/.../rewardName/id`；Chara.xml `ranks/.../rewardSkillSeed/id`；目录 `reward{R:09d}` |
| `mapBonus` / `mapArea` / `quest` / `course` / `ticket` / `avatarAccessory` / `mapIcon` | 见 §5.1 声明式表，按表传播 |
| `releaseTag`/`netOpen`/`gauge`/`timeTable`/`notesFieldLine`/`ddsBanner`/`ddsMap`/`ddsImage`/`charaWorks`/`skill`/`skillCategory`/`musicGenre`/`musicLabel` | 通常不冲突（多为官方只读资源）；若冲突按表传播；这些类型若需重映射，目录命名规则在 §6.3 表中给出 |

### 4.5 原子性

**Plan 阶段零写入**，所有编辑先聚合成 `RemapPlan`。Plan 完成后做完整性校验（§4.6），通过后才进入 Apply 阶段。Apply 阶段在暂存区操作（不是 ACUS），失败可整体丢弃暂存区重做。最终落盘 ACUS 的原子性见 §8.5。

### 4.6 Plan 校验（apply 前必须全部通过）

1. 所有 `new_id` 不与 ACUS 已有 ID 冲突（allocator 保证，二次校验防御）。
2. 所有 `new_id` 不与包内其他保留原 ID 的资源冲突。
3. 所有 `new_id` 不与 plan 内其他 `new_id` 冲突（同 kind 内唯一）。
4. 每个被重映射的资源，其所有引用方文件都生成了对应的 FieldEdit（无遗漏）。
5. 悬空引用（target 既不在包内也不在 ACUS）只产生 warning，不产生 error——除非该引用是 Map.xml 的 `mapAreaName` 这种**结构性必需**字段（这类进 error）。

### 4.7 边界情况处理

| 情况 | 处理 |
|---|---|
| 包内 A 引用包内 B，B 也冲突 | B 分配新 ID，A 对 B 的引用边产生 FieldEdit(B_old → B_new)。由 `referencers_of(B)` 一次性覆盖 |
| 包内 A 引用包外 C，C 在 ACUS 存在且不冲突 | 不产生 edit，保留原引用。**额外校验**：C 确实存在于 ACUS（`_resource_dir_by_xml_glob`） |
| 包内 A 引用包外 C，C 在 ACUS 不存在 | warning：「包内 X 引用 (kind, id) 但包内/ACUS 均无此资源，引用保留原值」。**不**自动删除引用字段（用户可能后续手动补）。若该字段是结构性必需（Map→mapArea），升级为 error |
| 同类多冲突，部分冲突 | 只对冲突项分配新 ID，未冲突项保留原 ID。引用图对两种都正确传播 |
| systemVoice 冲突但 cueFile 不冲突 | systemVoice 目录重命名；cueFile 保留。但需校验：保留的 cueFile 是否被包内其他 systemVoice 引用（一个 cueFile 可被多 voice 共享） |
| chara addImages 变体目录 | 见 §6.4，按 `ChuniCharaId` 编码联动重命名 |

---

## 5. 引用关系图数据结构

### 5.1 声明式引用规则表（单一真相源）

```python
# resource_reference_graph.py

@dataclass(frozen=True)
class RefRule:
    """一条引用规则：某类 XML 的某 xpath 指向某类资源。"""
    source_kind: str          # 引用方资源类型
    xpath: str                # 相对 XML root 的 id 字段 xpath
    target_kind: str          # 被引用资源类型
    condition: str | None     # 可选条件，如 Reward substance "type=2" 时才生效

# 完整规则表（从 map_export_bundle._expand_*_xml_closure 提炼）
REF_RULES: tuple[RefRule, ...] = (
    # --- Music.xml ---
    RefRule("music", "releaseTagName/id", "releaseTag", None),
    RefRule("music", "netOpenName/id", "netOpen", None),
    RefRule("music", "stageName/id", "stage", None),
    RefRule("music", "cueFileName/id", "cueFile", None),
    # --- Map.xml ---
    RefRule("map", "infos/MapDataAreaInfo/mapAreaName/id", "mapArea", None),
    RefRule("map", "infos/MapDataAreaInfo/rewardName/id", "reward", None),
    RefRule("map", "infos/MapDataAreaInfo/musicName/id", "music", None),
    RefRule("map", "infos/MapDataAreaInfo/ddsMapName/id", "ddsMap", None),
    RefRule("map", "timeTableName/id", "timeTable", None),
    RefRule("map", "stopReleaseEventName/id", "event", None),
    RefRule("map", "infos/MapDataAreaInfo/gaugeName/id", "gauge", None),
    # --- MapArea.xml ---
    RefRule("mapArea", "mapBonusName/id", "mapBonus", None),
    RefRule("mapArea", "grids/MapAreaGridData/reward/rewardName/id", "reward", None),
    # --- MapBonus.xml (substance 内多类型，按 FIELD_PATHS) ---
    RefRule("mapBonus", "substances/list/MapBonusSubstanceData/chara/charaName/id", "chara", None),
    RefRule("mapBonus", "substances/list/MapBonusSubstanceData/music/musicName/id", "music", None),
    RefRule("mapBonus", "substances/list/MapBonusSubstanceData/charaWorks/charaWorksName/id", "charaWorks", None),
    RefRule("mapBonus", "substances/list/MapBonusSubstanceData/skill/skillName/id", "skill", None),
    RefRule("mapBonus", "substances/list/MapBonusSubstanceData/musicGenre/musicGenreName/id", "musicGenre", None),
    # --- Reward.xml (按 substance type 分发) ---
    RefRule("reward", ".//RewardSubstanceData/ticket/ticketName/id", "ticket", "type=1"),
    RefRule("reward", ".//RewardSubstanceData/trophy/trophyName/id", "trophy", "type=2"),
    RefRule("reward", ".//RewardSubstanceData/chara/charaName/id", "chara", "type=3"),
    RefRule("reward", ".//RewardSubstanceData/namePlate/namePlateName/id", "namePlate", "type=5"),
    RefRule("reward", ".//RewardSubstanceData/music/musicName/id", "music", "type=6"),
    RefRule("reward", ".//RewardSubstanceData/mapIcon/mapIconName/id", "mapIcon", "type=7"),
    RefRule("reward", ".//RewardSubstanceData/systemVoice/systemVoiceName/id", "systemVoice", "type=8"),
    RefRule("reward", ".//RewardSubstanceData/avatarAccessory/avatarAccessoryName/id", "avatarAccessory", "type=9"),
    RefRule("reward", ".//RewardSubstanceData/stage/stageName/id", "stage", "type=13"),
    # --- Event.xml ---
    RefRule("event", "netOpenName/id", "netOpen", None),
    RefRule("event", "ddsBannerName/id", "ddsBanner", None),
    RefRule("event", "substances/map/mapName/id", "map", None),
    RefRule("event", ".//musicNames/list/StringID/id", "music", None),
    # --- Chara.xml ---
    RefRule("chara", "addImages1/charaName/id", "chara", None),
    RefRule("chara", "addImages2/charaName/id", "chara", None),
    # ... addImages3..9 同构
    RefRule("chara", "works/id", "charaWorks", None),
    RefRule("chara", "releaseTagName/id", "releaseTag", None),
    RefRule("chara", "netOpenName/id", "netOpen", None),
    RefRule("chara", "ranks/CharaRankData/rewardSkillSeed/rewardSkillSeed/id", "reward", None),
    # --- Stage.xml ---
    RefRule("stage", "releaseTagName/id", "releaseTag", None),
    RefRule("stage", "netOpenName/id", "netOpen", None),
    RefRule("stage", "notesFieldLine/id", "notesFieldLine", None),
    # --- Course.xml (包内可能有) ---
    RefRule("course", "selectMusic/musicName/id", "music", None),
    # --- Quest.xml ---
    RefRule("quest", "charas/list/StringID/id", "chara", None),
    RefRule("quest", "info/QuestRewardDataInfo/keyTrophyName/id", "trophy", None),
    RefRule("quest", "info/QuestRewardDataInfo/keyNamePlateName/id", "namePlate", None),
    RefRule("quest", "info/QuestRewardDataInfo/keyCharaName/id", "chara", None),
)
```

> **设计要点**：这张表是 `map_export_bundle._expand_*_xml_closure` 的"反向声明式镜像"。导出侧用它收集文件，导入侧用它提取引用边。**未来若引用规则变更，只需改这一处**。建议把这张表放到 `resource_reference_graph.py` 顶层，并在 `map_export_bundle.py` 顶部加注释指向它，长期可反向重构导出侧也复用此表（本次不做）。

### 5.2 图构建伪代码

```
build(staging_root, resources):
    nodes = {(r.kind, r.resource_id): r for r in resources}
    edges = []
    for xml_path in staging_root.rglob("*.xml"):
        source_kind = infer_kind_from_xml(xml_path)   # 按 xml 文件名/根 tag
        tree = ET.parse(xml_path)
        for rule in REF_RULES where rule.source_kind == source_kind:
            for el in tree.findall(rule.xpath):
                target_id = safe_int(el.text)
                if target_id is None or target_id < 0: continue
                if rule.condition: 
                    if not condition_holds(el, rule.condition): continue
                in_package = (rule.target_kind, target_id) in nodes
                edges.append(RefEdge(xml_path, source_kind, rule.xpath, 
                                     rule.target_kind, target_id, in_package))
    return ReferenceGraph(nodes, edges)
```

### 5.3 查询接口

- `referencers_of(kind, id) → list[RefEdge]`：重映射传播时用，找出所有需要改的 source_file + xpath。
- `references_of(file_path) → list[RefEdge]`：单个文件引用了哪些资源（用于校验该文件所有引用均已处理）。
- `dangling_references() → list[RefEdge]`：`in_package == False` 且 target 不在 ACUS 的边（悬空引用，进 warning）。

---

## 6. XML 重写器

### 6.1 字段感知重写（修复现有 bug）

现有 `_rewrite_all_id_fields_in_xml` 把所有 `<id>` 文本等于某值的节点全改——**这是 bug**，会误伤无关资源。新重写器按 `(xpath, old_id, new_id)` 精确改写。

```python
# resource_xml_rewriter.py
@dataclass(frozen=True)
class FieldEdit:
    xpath: str        # 相对 XML root
    old_id: int
    new_id: int

def apply_field_edits(xml_path: Path, edits: list[FieldEdit]) -> int:
    """
    按 xpath 分组，每个 xpath 一次 findall，只改文本匹配 old_id 的节点。
    返回修改节点数。写回时保留原 encoding 与 xml_declaration。
    """
```

**关键**：同一文件可能有多个 xpath 指向同一 old_id（如 Map.xml 多个 area 都引用同一 reward），全部都要改。按 xpath 分组遍历，O(文件节点数)。

### 6.2 name/id 自身改写

资源自身的 `name/id` 不在 REF_RULES 里（它是被引用方，不是引用方）。重写器单独处理：每个被重映射资源的 XML，改其 `name/id` 为 new_id。

```python
def rewrite_own_name_id(xml_path: Path, new_id: int) -> None
```

### 6.3 目录与文件重命名规则表

```python
@dataclass(frozen=True)
class NamingRule:
    kind: str
    dir_template: str           # 如 "music{ID:04d}"
    file_token_templates: tuple[str, ...]  # 如 ("CHU_UI_Jacket_{ID:04d}", "{ID:04d}_")

NAMING_RULES: dict[str, NamingRule] = {
    "music":       NamingRule("music",       "music{ID:04d}",    ("CHU_UI_Jacket_{ID:04d}", "{ID:04d}_")),
    "cueFile":     NamingRule("cueFile",     "cueFile{ID:06d}",  ()),
    "event":       NamingRule("event",       "event{ID:08d}",    ()),
    "chara":       NamingRule("chara",       "chara{ID:06d}",    ()),   # +变体目录见 §6.4
    "namePlate":   NamingRule("namePlate",   "namePlate{ID:08d}",()),
    "trophy":      NamingRule("trophy",      "trophy{ID:06d}",   ()),
    "map":         NamingRule("map",         "map{ID:08d}",      ()),
    "mapArea":     NamingRule("mapArea",     "mapArea{ID:08d}",  ()),
    "reward":      NamingRule("reward",      "reward{ID:09d}",   ()),
    "systemVoice": NamingRule("systemVoice", "systemVoice{ID:04d}", ()),
    "stage":       NamingRule("stage",       "stage{ID}",        ()),
    "charaWorks":  NamingRule("charaWorks",  "charaWorks{ID:06d}",()),
    # ... 其余类型按实际目录命名补全
}
```

重命名流程：
1. 先重写所有 XML 内容（含 path 文本内可能含旧 ID token 的，按 NAMING_RULES.file_token_templates 做 token 替换——但要**限定在 path 元素文本内**，避免误伤）。
2. 再做目录重命名（深度优先，先子后父，避免父目录先动导致路径失效）。
3. 再做文件重命名（按 file_token_templates 匹配文件名子串）。

### 6.4 chara addImages 变体目录

`chara{base*10}/` 是 chara 变体目录的命名约定（见 `_expand_chara_xml_closure` 的 `addImages{n}/charaName/id`）。当 chara C 重映射到 C'：

1. 主目录 `chara{C:06d}` → `chara{C':06d}`。
2. **若包内存在 `chara{C*10}/` 形式的变体目录**（即 `chara{C:06d}` 后跟一个 0 的目录），同步重命名为 `chara{C'*10}/`。
3. **联动重命名 ddsImage 目录**（O-2 决策：强制联动）：chara 与 ddsImage 通过 `ChuniCharaId(cid).raw6` 编码联动。chara C 重映射到 C' 时：
   - 计算旧 raw6 = `ChuniCharaId(C).raw6`，新 raw6 = `ChuniCharaId(C').raw6`
   - 若包内存在 `ddsImage/ddsImage{旧raw6}/` 目录，重命名为 `ddsImage/ddsImage{新raw6}/`
   - **同步重写 DDSImage.xml 的 `name/id` 字段**为新 raw6（因为 ddsImage 的 id 就是 raw6 编码）
   - **同步传播**：包内所有引用该 ddsImage 的 XML（如 Chara.xml 的 `addImages{n}/image{id}` 路径）也要跟着改
   - 若该 ddsImage 被包内多个 chara 共享（即另一个 chara 也引用同一 ddsImage），仍执行联动但产生 warning：「ddsImage {旧raw6} 被 chara {C} 和 chara {另一C} 共享，重映射后 {另一C} 的引用可能失效，请手动检查」

---

## 7. ID 分配器

### 7.1 统一接口

```python
# resource_id_allocator.py
class ResourceIdAllocator:
    def __init__(self, acus_root: Path): ...
    
    def allocate(self, kind: str, count: int = 1) -> int | tuple[int, ...]:
        """分配 count 个连续/独立的新 ID。返回单个或元组。"""
    
    def used_ids(self, kind: str) -> set[int]:
        """返回该类型当前已占用 ID（含 ACUS + 本 plan 已分配）。"""
```

### 7.2 各类型号段策略

> **决策（O-3/O-4）**：所有资源类型都分配号段，参考现有 ACUS 实际分布与现有 suggest 函数。原则：自制资源从 70000 起（map/mapArea/ddsMap 70000000 起，mapBonus 10000000 起），扫 ACUS 取 max+1。

| 类型 | 号段 | 来源/依据 |
|---|---|---|
| course (rank) | 490000-499999 | 现有 `course_rank.CUSTOM_RANK_COURSE_ID_MIN/MAX` |
| course (unlockChallenge) | 310000-319999（连续5个） | `unlock_challenge.next_perfect_challenge_course_base_id` |
| courseRule | 7001-7999 | `course_rule.CUSTOM_COURSE_RULE_ID_MIN/MAX` |
| reward | 200000000-299999999 | `unlock_challenge.CUSTOM_REWARD_ID_MIN/MAX` |
| trophy | ≥50000 | 现有约定（music_trophy_xml.py） |
| systemVoice | ≥700 | 现有约定（system_voice_pack.py） |
| music | ≥7000 递增 | 现有约定（pjsk_acus_install.py） |
| **chara** | **≥70000，扫 ACUS max+1** | ACUS 实测自制 chara 70120+（新增 allocator） |
| **namePlate** | **≥70000，扫 ACUS max+1** | ACUS 实测自制 namePlate 70004+（新增 allocator） |
| **stage** | **≥70000，扫 ACUS max+1** | ACUS 实测自制 stage 70000+（新增 allocator） |
| **map** | **≥70000000，扫 ACUS max+1** | ACUS 实测自制 map 70000000+（新增 allocator） |
| **mapArea** | **≥70000000，扫 ACUS max+1** | 与 map 一致（新增 allocator） |
| **mapBonus** | **≥10000000，扫 ACUS max+1** | 现有 `suggest_next_mapbonus_id` 默认 start=10000000 |
| **mapIcon** | **扫 ACUS max+1** | 现有 `suggest_next_map_icon_id` |
| **event** | **≥70000，扫 ACUS max+1** | 现有 `_next_available_unlock_event_id` 默认 start=70000 |
| **ddsImage** | **≥70000，扫 ACUS max+1** | 与 chara 联动，参考 ACUS 实测 |
| **ddsMap** | **≥70000000，扫 ACUS max+1** | map_add_dialog.py 注释「首位为 7 的 id（70000000 起递增）」 |
| **ddsBanner** | **≥70000，扫 ACUS max+1** | 与 event 一致 |
| **cueFile** | **联动 systemVoice**（10000+voice_id） | 复用 `system_voice_pack.cue_numeric_id_for_voice` 逻辑；若 cueFile 独立冲突，扫 ACUS cueFile 目录取 max+1 |
| **charaWorks/skill/skillCategory/musicGenre/musicLabel/releaseTag/netOpen/gauge/timeTable/notesFieldLine/ticket/avatarAccessory/quest** | **扫 ACUS max+1，下限取 ACUS 实际分布** | 多为官方资源；若 ACUS 无自制则从 70000 起（保守） |

### 7.3 实现策略

```python
class ResourceIdAllocator:
    _STRATEGIES = {
        "course":       _alloc_rank_course,        # 调 course_rank.next_custom_rank_course_id
        "courseRule":   _alloc_course_rule,        # 调 course_rule.next_custom_rule_id
        "reward":       _alloc_reward,             # 调 unlock_challenge.next_custom_unlock_reward_id
        "trophy":       _alloc_trophy,             # 扫 ACUS trophy，max(50000, used_max+1)
        "systemVoice":  _alloc_system_voice,       # max(700, used_max+1)
        "music":        _alloc_music,              # max(7000, used_max+1)
        "chara":        _alloc_chara,              # max(70000, used_max+1)
        "namePlate":    _alloc_nameplate,          # max(70000, used_max+1)
        "stage":        _alloc_stage,              # max(70000, used_max+1)
        "map":          _alloc_map,                # max(70000000, used_max+1)
        "mapArea":      _alloc_maparea,            # max(70000000, used_max+1)
        "mapBonus":     _alloc_mapbonus,           # 调 mapbonus_xml.suggest_next_mapbonus_id
        "mapIcon":      _alloc_mapicon,            # 调 map_icon_xml.suggest_next_map_icon_id
        "event":        _alloc_event,              # max(70000, used_max+1)
        "ddsImage":     _alloc_ddsimage,           # max(70000, used_max+1)
        "ddsMap":       _alloc_ddsmap,             # max(70000000, used_max+1)
        "ddsBanner":    _alloc_ddsbanner,          # max(70000, used_max+1)
        "cueFile":      _alloc_cuefile,            # 联动 systemVoice 或 max+1
        # 其余类型（charaWorks/skill/...）: 通用 _alloc_generic(kind, min_id=70000)
    }
    
    def allocate(self, kind, count=1):
        strategy = self._STRATEGIES.get(kind) or self._make_generic(kind)
        return strategy(self._acus_root, count, self._plan_allocated)
```

> 所有类型都支持分配，无 `_UNSUPPORTED`。对于罕见类型（charaWorks/skill 等），用通用策略：扫 ACUS 对应目录取 max+1，下限 70000。

### 7.4 并发/竞态

单用户单进程，但仍需考虑"扫描后到写入前 ACUS 被外部改动"：

- allocator 内部缓存 `_plan_allocated: dict[str, set[int]]`，同一次 plan 内多次分配不会重复。
- 写入前（§8.2）**重新扫描 ACUS** 做最终冲突校验。若此时新 ID 已被占用（极端情况），中止写入并提示用户重试。

---

## 8. 写入流程

### 8.1 总流程

```
1. 在暂存区应用 RemapPlan（XML 重写 + 重命名）—— 已在 §4 描述
2. 对暂存区做写入前校验（§8.2）
3. 把暂存区写入 ACUS（§8.3，非覆盖模式）
4. 写入后校验（§8.4）
5. 失败回滚（§8.5）
```

### 8.2 写入前校验

- 暂存区内所有 XML 可被 `ET.parse` 正常解析。
- 暂存区内每个资源的目录名与 XML name/id 一致（如 `music07001/Music.xml` 的 name/id == 7001）。
- **重新扫 ACUS**：确认 plan 中所有 new_id 仍不冲突（防御 ACUS 被外部改动）。
- 暂存区内引用图无新增悬空（重命名后引用边应自洽）。

### 8.3 非覆盖写入

`sheet_install.install_zip_to_acus` 是覆盖式的（`dest.open("wb")`）。新增非覆盖变体：

```python
# sheet_install.py（小幅扩展）
def install_zip_to_acus_non_overwriting(zip_path: Path, acus_root: Path) -> list[str]:
    """
    与 install_zip_to_acus 相同，但若目标文件已存在则跳过并记录到 skipped。
    用于 resource_pack_import 的最终落盘：plan 已保证无冲突，理论上不会触发 skip。
    若触发 skip，说明 ACUS 在 plan 后被改动，应中止。
    """
```

> 由于 plan 阶段已做冲突检测 + 写入前二次校验，正常路径不会触发 skip。`non_overwriting` 是安全网：任何 skip 都视为异常，中止整个导入。

### 8.4 写入后校验

- 统计写入文件数，与暂存区文件数比对。
- 对写入的 XML 做 `ET.parse` 抽查。
- 对每个被重映射的资源，在 ACUS 内 `_resource_dir_by_xml_glob` 确认新 ID 资源存在。

### 8.5 失败回滚

写入是文件复制，非事务性。回滚策略：

- **记录写入清单** `written: list[Path]`。
- 失败时按清单**反向删除**已写入文件（仅删本次写入的，不动 ACUS 原有文件）。
- 若写入的是新建目录且删空，删除空目录。
- 回滚失败（罕见）则报告残留文件路径，让用户手动清理。

> 不做"备份 ACUS 再恢复"——成本高且本场景下 plan 已保证只写新文件不覆盖。

### 8.6 写入顺序

文件复制无依赖顺序（都是独立文件）。但建议**先写被引用方再写引用方**，便于写入后校验时引用关系已成立。实现上按 `topological_sort(引用图)` 排序，被引用方先写。

---

## 9. 关键边界情况与错误处理

| 情况 | 检测 | 处理 |
|---|---|---|
| 非 zip / 损坏 zip | `zipfile.is_zipfile` + `BadZipFile` | 报错：「无法识别的压缩包格式」 |
| 缺 Music.xml / Map.xml | 扫描后包内无任何已知 XML | 报错：「包内未发现任何可识别资源 XML」 |
| XML 解析失败 | `ET.parse` 抛异常 | 收集所有失败文件，报告「以下 XML 解析失败：...」，中止导入 |
| 包内同类型 ID 重复 | 扫描时同 kind 出现重复 resource_id | 报错：「包内 music ID 7001 重复，请修复压缩包」，不进入重映射 |
| 包内引用悬空（target 不在包内也不在 ACUS） | 引用图 `dangling_references()` | warning，保留原引用字段；若为结构性必需字段（Map→mapArea）则 error |
| 重映射后新 ID 仍冲突 | §8.2 二次校验 | 中止，提示「ACUS 在导入期间被改动，请重试」 |
| 用户中途取消 | 对话框 reject | 暂存区用 `tempfile.TemporaryDirectory` 自动清理；已落盘的回滚见 §8.5 |
| allocator 号段用尽 | `UnsupportedAllocationError` / `ValueError` | 报错：「trophy 自制号段已满，请清理旧自制称号」 |
| chara 变体目录命名异常 | 扫描时遇 `chara{X}` 但 X 不符合 base*10 规则 | warning，跳过变体重命名，提示用户手动检查 |
| 暂存区磁盘不足 | 写入时 `OSError` | 回滚，提示「磁盘空间不足」 |

---

## 10. 与现有代码的集成

### 10.1 复用清单

| 现有函数/常量 | 复用方式 |
|---|---|
| `acus_scan.scan_*` | 直接调用，构建 ACUS 侧 `used_ids` |
| `map_export_bundle._resource_dir_by_xml_glob` | 写入后校验、悬空引用校验时调用 |
| `map_export_bundle._safe_int` | 引用图构建时复用（或复制一份，避免跨模块依赖） |
| `sheet_install._mapper_for_paths` / `_LEAF_FOLDER_RULES` | 暂存区→ACUS 路径映射复用 |
| `sheet_install.install_zip_to_acus` | 不直接用（覆盖式）；新增 `non_overwriting` 变体 |
| `system_voice_pack.cue_numeric_id_for_voice` | systemVoice 冲突判定与 cueFile 联动 |
| `chuni_formats.ChuniCharaId` | chara 变体目录与 ddsImage 联动 |
| `unlock_challenge.*` / `course_rule.*` / `course_rank.*` 的分配函数 | allocator 内部委托调用 |

### 10.2 新增函数

| 模块 | 新增函数 |
|---|---|
| `resource_pack_import.py` | `import_resource_pack(zip_path, acus_root) -> ImportResult`（编排器入口） |
| `resource_reference_graph.py` | `build_reference_graph(staging_root, resources) -> ReferenceGraph` |
| `resource_id_allocator.py` | `ResourceIdAllocator` 类 |
| `resource_xml_rewriter.py` | `apply_remap_plan(staging_root, plan) -> ApplyReport` |
| `sheet_install.py` | `install_zip_to_acus_non_overwriting`（扩展） |

### 10.3 UI 入口

**入口 1（主入口，推荐）**：Map 管理页右键菜单，与"导出地图资源包"对称。

```python
# manager_widget.py _on_table_context_menu，k == "Map" 分支
act_export = Action(FIF.SAVE, "导出地图资源包(Zip)…", ...)
act_import = Action(FIF.FOLDER_ADD, "导入资源包(Zip)…", self.table)  # 新增
act_import.triggered.connect(
    lambda checked=False: QTimer.singleShot(80, self._import_resource_pack)
)
menu.addAction(act_export)
menu.addAction(act_import)
```

> 注意：导入入口放在 Map 右键**不需要选中某个 Map**——它是对整个 ACUS 的导入。更准确的位置是"其他"分段或设置页。但为对称性与可发现性，建议**两处都放**：Map 右键 + 一个独立入口。

**入口 2（独立入口）**：`main_window` 的"其他"分段新增一个 `import_pack` 项，或在设置页加按钮。打开 `ResourcePackImportDialog`。

```python
# ui/resource_pack_import_dialog.py
class ResourcePackImportDialog(FluentCaptionDialog):
    def __init__(self, *, acus_root: Path, parent=None): ...
        # 顶部：[选择压缩包...] LineEdit + Browse 按钮
        # 中部：预览表格（冲突清单）+ 警告区
        # 底部：[取消] [确认导入]
    
    def _on_browse(self): ...           # QFileDialog 选 zip
    def _on_package_selected(self, path): 
        # 调 import_resource_pack 的 plan 阶段，填充预览表
    def _on_confirm(self): 
        # 调 apply 阶段，报告结果
```

### 10.4 与 `github_sheet_dialog` 的关系

`github_sheet_dialog._rewrite_package_music_id` 是单 music ID 重写的特例。新模块上线后：
- **不删除** `_rewrite_package_music_id`（社区谱面导入只需改单个 music ID，用现有函数足够）。
- 但在新模块的 `resource_xml_rewriter` 中**不复用**它，避免继承其"全 id 误改"bug。
- 长期可选：把 `github_sheet_dialog` 也迁移到新重写器（本次不做，列为后续迭代）。

---

## 11. 测试策略

### 11.1 单元测试

| 模块 | 测试用例 |
|---|---|
| `resource_reference_graph` | 1. 构建包内引用图，验证节点数/边数符合预期<br>2. Reward substance 各 type 分发正确<br>3. Chara addImages 引用正确识别<br>4. 悬空引用识别 |
| `resource_id_allocator` | 1. 各类型分配在合法号段内<br>2. 不与 ACUS 已有 ID 冲突<br>3. 同 plan 内多次分配不重复<br>4. 不支持类型抛 `UnsupportedAllocationError`<br>5. reward 连续分配（unlockChallenge 块分配） |
| `resource_xml_rewriter` | 1. 单文件多 xpath 重写正确<br>2. **不误改无关 `<id>`**（核心：修复现有 bug 的回归测试）<br>3. 目录/文件重命名按 NAMING_RULES<br>4. chara 变体目录联动<br>5. path 文本内 token 替换限定在 path 元素内 |
| `resource_pack_import` | 1. 无冲突包：原样写入<br>2. 全冲突包：全部重映射后写入<br>3. 部分冲突包：仅冲突项重映射<br>4. 悬空引用：warning 不 error<br>5. 包内 ID 重复：报错<br>6. 二次校验失败：中止 |

### 11.2 集成测试

端到端：用 `map_export_bundle.export_map_bundle_to_zip` 导出一个真实 Map 的包 → 手动改包内某 music ID 制造冲突 → 调 `import_resource_pack` → 验证 ACUS 内资源完整、引用关系自洽。

### 11.3 测试包构造

```python
def test_remap_with_conflict(tmp_path):
    acus = tmp_path / "acus"; acus.mkdir()
    # 1. 在 ACUS 预放一个 music id=7001
    _place_music(acus, 7001)
    # 2. 构造包：含 music id=7001（冲突）+ 引用它的 trophy + 不冲突的 chara
    staging = _build_test_package(tmp_path, 
        music_ids=[7001], trophy_refs=[7001], chara_ids=50001)
    zip_path = _zip_dir(staging, tmp_path / "pkg.zip")
    # 3. 导入
    result = import_resource_pack(zip_path, acus)
    # 4. 断言
    assert result.written_count > 0
    assert (acus / "music" / f"music{result.remaps[('music',7001)]:04d}").exists()
    assert _trophy_references(acus, result.remaps[('music',7001)])  # trophy 引用已更新
    assert (acus / "chara" / "chara050001").exists()  # 不冲突的保留原 ID
```

---

## 12. 风险与开放问题

### 12.1 开放问题决策记录

所有开放问题已在 §0.1 记录决策。此处保留原始问题描述供参考。

| ID | 问题 | 决策 |
|---|---|---|
| O-1 | 是否提供"直接覆盖（不重映射）"模式？ | **不提供** |
| O-2 | chara 重映射时是否强制联动重命名 ddsImage 目录？ | **强制联动**（多 chara 共享时 warning） |
| O-3 | chara / namePlate / stage 自制 ID 号段 | **从 70000 起，扫 ACUS max+1** |
| O-4 | map / event / mapArea 等类型冲突时如何处理？ | **也分配号段**（map/mapArea 70000000 起，event/ddsImage 70000 起，详见 §7.2） |
| O-5 | 悬空引用是否自动清理引用字段？ | **保留原引用**（悬空引用是地图内容，内容不变） |
| O-6 | 导入入口放在哪里？ | **设置页**（具体位置待定） |

### 12.2 性能考虑

- **大包扫描**：一个含 50+ 资源的包，引用图构建需解析全部 XML。预计 <2s（参考 `acus_scan` 对同等规模 ACUS 的扫描耗时）。
- **重映射规划**：O(包内 XML 节点数 × REF_RULES 数)，可忽略。
- **ACUS 侧扫描**：复用 `acus_scan`，大 ACUS（数千资源）约 1-3s。可在后台线程执行，UI 显示进度。
- **优化方向**：若 ACUS 侧扫描慢，可缓存 `used_ids` 到内存（按 ACUS mtime 失效），但首版不做。

### 12.3 后续迭代

1. 把 `map_export_bundle._expand_*_xml_closure` 重构为复用 `REF_RULES` 表，消除导出/导入侧的领域知识重复。
2. 把 `github_sheet_dialog._rewrite_package_music_id` 迁移到新重写器，消除"全 id 误改"bug。
3. 支持增量导入（多次导入同一包的不同子集）。
4. 支持"导入前预览差异"（与 ACUS 现有资源的 diff 视图）。

### 12.4 关键风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| 引用规则表与实际 XML 结构不一致（遗漏某 xpath） | **高** | REF_RULES 必须由 `map_export_bundle` 的领域专家 review；测试覆盖每种资源类型 |
| chara 变体目录联动遗漏 | 中 | §6.4 单独处理 + 测试用例 |
| 写入回滚不彻底 | 中 | §8.5 记录清单反向删除 + 失败报告残留路径 |
| ACUS 在导入期间被外部改动 | 低 | §8.2 二次校验防御 |
| 大包性能 | 低 | 后台线程 + 进度提示 |

---

## 附录 A：核心数据结构汇总

```python
# resource_pack_import.py
@dataclass(frozen=True)
class PackageResource:
    kind: str; resource_id: int; xml_path: Path; dir_path: Path; extra: dict

@dataclass(frozen=True)
class ConflictEntry:
    kind: str; old_id: int; reason: str
    package_resource: PackageResource; referencing_files: list[Path]

@dataclass(frozen=True)
class ConflictReport:
    conflicts: tuple[ConflictEntry, ...]
    clean_resources: tuple[PackageResource, ...]
    package_warnings: tuple[str, ...]

@dataclass(frozen=True)
class ImportResult:
    success: bool
    written_count: int
    remaps: dict[tuple[str, int], int]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]

# resource_reference_graph.py
@dataclass(frozen=True)
class RefEdge:
    source_file: Path; source_kind: str; xpath: str
    target_kind: str; target_id: int; in_package: bool

# resource_xml_rewriter.py
@dataclass(frozen=True)
class FieldEdit:
    xpath: str; old_id: int; new_id: int

@dataclass(frozen=True)
class RemapPlan:
    remaps: dict[tuple[str, int], int]
    file_edits: dict[Path, list[FieldEdit]]
    dir_renames: list[tuple[Path, Path]]
    file_renames: list[tuple[Path, Path]]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
```

## 附录 B：编排器接口签名

```python
# resource_pack_import.py

def import_resource_pack(
    *, zip_path: Path, acus_root: Path,
    on_progress: Callable[[str], None] | None = None,
) -> ImportResult:
    """完整导入流程（plan + apply + write）。"""

def plan_import(
    *, zip_path: Path, acus_root: Path,
) -> tuple[ConflictReport, RemapPlan, ReferenceGraph]:
    """仅规划，不写入。供 UI 预览。"""

def apply_and_write(
    *, staging_root: Path, plan: RemapPlan, acus_root: Path,
) -> ImportResult:
    """应用 plan 并写入 ACUS。供 UI 确认后调用。"""
```

---

**文档结束。**
