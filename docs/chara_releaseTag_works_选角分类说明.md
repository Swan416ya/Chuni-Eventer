# 角色选角界面：releaseTag（大类）与 works（小类）对照说明

本文对照 **A001 官方 `Chara.xml`**、**官方 `ReleaseTag.xml`**，以及本工具 **`write_chara_xml` 的默认输出**，说明「版本 / 作品」两层分类在数据上**应如何对应**，以及为何会出现「没有自制谱大类 → PJSK / 明日方舟 小类」的预期落空。

---

## 1. 官方数据里两层字段各是什么

### 1.1 `releaseTagName`（通常对应 UI「大类 / 版本带」）

官方角色（示例：`A001/chara/chara024700/Chara.xml`）：

```xml
<releaseTagName>
  <id>20</id>
  <str>v2 2.45.00</str>
  <data />
</releaseTagName>
```

同一条数据在 **A001 的 ReleaseTag 主数据**里有一条**同 id** 的定义（`A001/releaseTag/releaseTag000020/ReleaseTag.xml`）：

```xml
<ReleaseTagData>
  <dataName>releaseTag000020</dataName>
  <name>
    <id>20</id>
    <str>v2 2.45.00</str>
    <data />
  </name>
  <titleName>CHUNITHM X-VERSE-X</titleName>
</ReleaseTagData>
```

**要点：**

- `Chara.xml` 里的 **`releaseTagName.id` / `str`** 与对应 **`ReleaseTag.xml` 里 `name.id` / `str`** 在官方包中是**一致**的（至少 id 必须能主数据里查到）。
- 官方 `ReleaseTag.xml` 另有 **`titleName`**，与 `name.str` 可以不同（例如 `titleName` 为长标题）。

### 1.1.1 自制扩展：「内部键」与「界面显示」分离（X-VERSE-X 实测）

在 **`bin/option/ACUS`**、**`bin/option/AKAO`** 等包中，自定义 `ReleaseTag.xml` 常见格式为：

- **`name`**：供客户端**索引 / 与 `Chara.releaseTagName` 对齐**用的 **StringID**（自制侧常见 **`id=-1`、`str=Invalid`** 或短码如 **`id=-2`、`str=PJSK`**）。
- **`titleName`**：选角等界面上的**大类显示文案**（例如 **自制譜**、**PJSK**）。

因此：**不要把「自制譜」写在 `name.str` 里指望当显示用**；应 **`name` 保持 Invalid/短码 + `titleName` 写玩家看到的分类名**。  
`Chara.xml` 的 `releaseTagName` 应与 **`ReleaseTag` 的 `name`（id/str）** 一致，例如 `-1` + `Invalid`；界面上的「自制譜」由对应 `ReleaseTag.xml` 的 **`titleName`** 提供。

参考（与你本机游戏内文件一致的结构）：

```xml
<!-- ACUS：大类显示「自制譜」 -->
<name><id>-1</id><str>Invalid</str><data /></name>
<titleName>自制譜</titleName>

<!-- AKAO：大类显示「PJSK」 -->
<name><id>-2</id><str>PJSK</str><data /></name>
<titleName>PJSK</titleName>
```

### 1.2 `works`（通常对应 UI「作品 / IP 小类」）

同一 **releaseTag（同为 id 20）** 下，不同角色可以用**不同 `works`** 分出小类。例如：

| 角色目录        | releaseTagName.id | works.id | works.str   |
|----------------|-------------------|----------|-------------|
| chara024690    | 20                | 183      | メダリスト   |
| chara025510    | 20                | 93       | オンゲキ     |

官方 A001 **没有**单独的 `works.xml`；**小类显示名主要来自 `Chara.xml` 内联的 `works/str`**，**小类归并键很可能是 `works/id`**（具体以客户端为准）。

---

## 2. 本工具当前写出的 `Chara.xml` 与官方的主要差异

对应实现：`chuni_eventer_desktop/xml_writer.py` → `write_chara_xml`。

### 2.1 `releaseTagName`（Chara）与 `ReleaseTag.xml`（`name` / `titleName`）

| 项目 | 官方示例 | 工具默认（未改参数时） |
|------|----------|------------------------|
| `id` | 正数，且在 `releaseTag/*/ReleaseTag.xml` 有定义（如 20） | **-1** |
| `str` | 与主数据 `name` 一致（如 `v2 2.45.00`） | **Invalid** |

**自制扩展（与 `ACUS/AKAO` 内 ReleaseTag 一致时）：**

- `Chara.releaseTagName` 应与 **`ReleaseTag.xml` 的 `name`** 一致：例如 **`id=-1`、`str=Invalid`**。
- **大类显示名**在 **`ReleaseTag.xml` 的 `titleName`**（如 **自制譜**），**不要**误把显示名只写在 `name.str` 而省略 `titleName`。

### 2.2 `works`

| 项目 | 官方示例 | 工具默认（未在 UI 中选作品库条目时） |
|------|----------|--------------------------------------|
| `id` | 正数（93、183 等） | **-1** |
| `str` | 具体作品名 | **Invalid** |

**若 `works` 为 `-1` / `Invalid`：** 很多情况下会**进不了「按作品细分」的浏览路径**，只能依赖「最近使用」等——这与此前产品说明一致。

**若要做「PJSK」「明日方舟」两个小类：** 应在 **`works` 层**使用**两个不同的 `works.id`**（及对应 `str`），而不是再建一套「第二个 ReleaseTag」去表示 IP。

### 2.3 其它结构差异（一般不影响「分类树」，但可能影响别的问题）

- 官方常有多形态 `addImages1..` 且 `changeImg=true`；工具模板多为占位 `Invalid`。这与**分类**无直接关系，与**立绘/变体**有关。
- `netOpenName`、`disableFlag` 等与解禁/显示有关；工具默认与 A001 常见值接近，但若客户端按版本过滤，仍需自行对照版本逻辑。

---

## 3. 常见误区：为什么「自制谱大类 + PJSK / 明日方舟 小类」做不出来

### 误区 A：把「PJSK」做成第二个 `ReleaseTag`（例如再做一个 `releaseTag000022`，`name.id = -2`）

在数据语义上，**多一个 ReleaseTag 条目 = 多一个大类（版本带）**，而不是「挂在自制谱下面的小类」。

期望结构应是：

- **大类（releaseTag）**：例如统一 **`id = -1`**（或你自定义的一个**专用正数 id**，并在 `ReleaseTag.xml` 里定义）→ 显示「自制譜」。
- **小类（works）**：  
  - PJSK 角色：`works.id = A`，`works.str = …`（如 `プロジェクトセカイ` 或你希望的日文/中文显示名）；  
  - 明日方舟：`works.id = B`，`works.str = …`。

若角色写的是 **`releaseTagName.id = -2`**，客户端会把它归到 **「-2 对应的那条 ReleaseTag」** 大类下，而**不会**自动变成「-1 自制谱」的子节点。

### 误区 B：`ReleaseTag.xml` 的文件夹名 / `dataName` 与 `name.id` 混用

官方习惯是：`releaseTag000020` 目录里 `name.id = 20`。  
自定义时建议：**每个 ReleaseTag 文件内 `name.id` 与 `Chara.releaseTagName.id` 一致**；目录名与 `dataName` 与游戏其它资源引用习惯保持一致（与具体客户端加载顺序有关）。

### 误区 C：只改 `str` 不改 `id`

小类若依赖 **`works.id`** 分组，仅改显示字符串而多个 IP 共用同一 id，会在 UI 上**并成一类**。

---

## 4. 推荐配置示例（目标：大类「自制譜」、小类「PJSK」「明日方舟」）

以下为**数据语义**示例，id 数字需在你工程内**唯一、且不与会冲突的官方 id 撞车**（自制常用 9xxxxx 段或工具「作品库」生成的 id）。

**ACUS（或合并包）内 ReleaseTag（大类）一条即可，例如：**

- `releaseTag/.../ReleaseTag.xml`：`name.id = -1`，`name.str = Invalid`，**`titleName = 自制譜`**

**PJSK 角色 `Chara.xml`：**

```xml
<releaseTagName>
  <id>-1</id>
  <str>Invalid</str>
  <data />
</releaseTagName>
<works>
  <id>900001</id>
  <str>プロジェクトセカイ</str>
  <data />
</works>
```

**明日方舟角色 `Chara.xml`：**

```xml
<releaseTagName>
  <id>-1</id>
  <str>Invalid</str>
  <data />
</releaseTagName>
<works>
  <id>900002</id>
  <str>アークナイツ</str>
  <data />
</works>
```

**不要**再把「PJSK」单独做成 `releaseTagName.id = -2` 除非你的目标本来就是**第二个顶层大类**。

---

## 5. 自检清单（游戏内仍看不到预期分类时）

1. **`Chara.releaseTagName.id`** 是否在**任意已加载包**的 `ReleaseTag/*/ReleaseTag.xml` 里存在同 id 的 `name`？
2. **`Chara.releaseTagName`** 是否与 `ReleaseTag` 的 **`name`（id/str）** 一致？自制侧常见 **`-1` + `Invalid`**；**显示名**看 **`titleName`**。
3. **小类**是否落在 **`works`**：`works.id` 是否**按 IP 分开**？是否仍为 `-1` / `Invalid`？
4. 是否误把 IP 写成了**第二个 ReleaseTag**，导致大类变成「プロセカ」等而非「自制譜」下子类？
5. 自定义包是否在游戏**实际读取路径**（如 `bin/option/ACUS`）且**被加载顺序覆盖/合并**？

---

## 6. 与仓库内种子的关系说明

当前仓库内 `chuni_eventer_desktop/data/acus_seed/releaseTag/` 已与游戏内 **ACUS / AKAO** 样本对齐格式：

- `releaseTag000021`：`name` 为 **`-1` / `Invalid`**，`titleName` 为 **自制譜**（界面大类）。
- `releaseTag000022`：`name` 为 **`-2` / `PJSK`**，`titleName` 为 **PJSK**（另一条顶层大类；若不要该大类，角色不要引用 `-2`）。

**注意：** 你本机 `ACUS\releaseTag000021` 目录下的文件曾出现 **`dataName` 仍为 `releaseTag000020`** 的拷贝痕迹；种子与仓库已改为 **`dataName` 与目录名一致**（`releaseTag000021` / `releaseTag000022`）。若游戏强绑定 `dataName` 与路径，请与实机包保持一致。

---

## 7. 小结

| 层级 | 字段位置 | 作用（理解用） |
|------|----------|----------------|
| 大类 | `Chara.releaseTagName` + `ReleaseTag.xml` | 与版本/发行带对应，宜**全自制共用同一 releaseTag id** |
| 小类 | `Chara.works`（仅 Chara 内联，无单独 works 主表文件） | **PJSK / 明日方舟等 IP** 用**不同 `works.id`** 区分 |

本工具将 `Chara.releaseTagName` 固定为 **`-1` / `Invalid`** 与 **ACUS 侧 `ReleaseTag.name`** 一致；**大类显示**依赖同包或合并加载的 **`ReleaseTag.titleName`（如 自制譜）**。IP 小类仍建议放在 **`works`**；是否需要第二条顶层 ReleaseTag（如 `-2` PJSK）按你的分区设计决定。

---

*文档基于仓库内 A001 样本与 `write_chara_xml` 实现整理；客户端 UI 树的具体判定以游戏程序为准，本文侧重数据层可验证的差异与推荐做法。*
