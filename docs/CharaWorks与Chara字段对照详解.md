# CharaWorks.xml 与 Chara.xml 字段对照详解

本文以 **A001 官方数据**为基准，对照 **`chara024760/Chara.xml`**（角色）与 **`charaWorks000183/CharaWorks.xml`**（作品主数据），说明每个字段在游戏数据层中的含义、**必须与谁一致**，以及自制 MOD 不显示时的排查思路。

> 路径约定：下文「ACUS 根」指选项包根目录（如 `A001/`、`ACUS/`），其下应有 `chara/`、`charaWorks/`、`releaseTag/` 等并列文件夹。

---

## 1. 文件与目录如何对应

| 实体 | 磁盘路径 | 根元素 |
|------|-----------|--------|
| 角色 | `{ACUS根}/chara/chara{角色ID六位}/Chara.xml` | `CharaData` |
| 作品主数据 | `{ACUS根}/charaWorks/charaWorks{作品ID六位}/CharaWorks.xml` | `CharaWorksData` |

- **角色 ID**：`Chara.xml` 里 `dataName` / 目录名里的数字，与 `name.id` 一致（如 `chara024760` → 角色 `24760`）。
- **作品 ID**：`Chara.xml` 里 **`works/id`**（如 `183`），与 **`CharaWorks.xml` 里 `name/id`** 一致；目录名为 **`charaWorks` + 六位零填充**（`183` → `charaWorks000183`；`900001` → `charaWorks900001`）。

**链接关系一句话**：游戏用 **`works/id`** 把角色挂到某条 **CharaWorks** 上；同一条 CharaWorks 可被多个角色引用（同一作品下多角色）。

---

## 2. 官方成对样本（务必逐字段对齐）

### 2.1 角色：`A001/chara/chara024760/Chara.xml`（节选）

该角色所属作品为 **メダリスト**，`works.id = 183`。

```xml
<releaseTagName>
  <id>20</id>
  <str>v2 2.45.00</str>
  <data />
</releaseTagName>
<netOpenName>
  <id>2801</id>
  <str>v2_45 00_1</str>
  <data />
</netOpenName>
<works>
  <id>183</id>
  <str>メダリスト</str>
  <data />
</works>
```

### 2.2 作品：`A001/charaWorks/charaWorks000183/CharaWorks.xml`（全文）

```xml
<CharaWorksData ...>
  <dataName>charaWorks000183</dataName>
  <releaseTagName>
    <id>20</id>
    <str>v2 2.45.00</str>
    <data />
  </releaseTagName>
  <netOpenName>
    <id>2801</id>
    <str>v2_45 00_1</str>
    <data />
  </netOpenName>
  <name>
    <id>183</id>
    <str>メダリスト</str>
    <data />
  </name>
  <sortName>メタリスト</sortName>
  <priority>0</priority>
  <ranks />
</CharaWorksData>
```

### 2.3 对照结论（自制内容最容易错的三点）

| CharaWorks 字段 | 必须与谁一致 | 说明 |
|-----------------|--------------|------|
| **`releaseTagName`**（id + str） | **同包内该角色的 `Chara.releaseTagName`** | 与 **`releaseTag/*/ReleaseTag.xml` 里 `name`（id/str）** 一致时，大类标签才能主数据解析。官方例：`20` / `v2 2.45.00` 对应 `releaseTag000020`。 |
| **`netOpenName`**（id + str） | **同包内该角色的 `Chara.netOpenName`** | 若与角色不一致，客户端在按「解禁 / 版本网」过滤时，可能**只显示角色却不显示作品节点**，或整组被过滤。 |
| **`name`**（id + str） | **`Chara.works`** | **`id` 与目录六位数字对齐**；**`str` 建议与角色 `works/str` 完全一致**（含大小写、空格）。 |

此前仅保证 `name` 与 `works` 一致、而 **`releaseTagName` 或 `netOpenName` 与 Chara 不一致** 时，仍可能出现 **游戏内作品分类不显示** 的情况。本仓库工具已改为在写入 CharaWorks 时从 **同一份 Chara.xml** 读取 `releaseTagName` 与 `netOpenName`；并提供 **`scripts/sync_acus_chara_works.py`** 按全表角色批量对齐。

---

## 3. CharaWorks.xml 各字段说明

### 3.1 `dataName`

- **含义**：本条主数据的内部名，与 **父目录名**一致。
- **格式**：`charaWorks` + **六位零填充的 `name.id`**。
- **链接**：不直接指向其他 XML；与 **`charaWorks` 目录命名**绑定，客户端常据此定位资源。

### 3.2 `releaseTagName`（id / str / data）

- **含义**：该作品在选角 UI 中归属的 **「大类 / 版本带」**（与 `ReleaseTag` 体系一致）。
- **链接**：
  - **必须与** 引用该 `works.id` 的 **`Chara.xml` → `releaseTagName`** 完全一致。
  - 自制扩展时，应与 **`{ACUS根}/releaseTag/releaseTagXXXXXX/ReleaseTag.xml`** 中的 **`<name><id>` / `<name><str>`** 一致（例如 `id=-2 str=PJSK` 对应某条自制 ReleaseTag）；**界面显示的大类文案**通常来自同文件的 **`titleName`**，见 [chara_releaseTag_works_选角分类说明.md](./chara_releaseTag_works_选角分类说明.md)。

### 3.3 `netOpenName`（id / str / data）

- **含义**：与客户端 **网络解禁 / 版本阶段** 相关的键，与角色条目使用同一套枚举。
- **链接**：
  - **必须与** **`Chara.netOpenName`** 一致（官方例：`2801` / `v2_45 00_1`）。
  - 若角色能进游戏但作品分类不出现，优先核对这一项是否与 **该角色 Chara** 逐字一致。

### 3.4 `name`（id / str / data）

- **含义**：**作品**的 StringID：`id` 为作品编号，`str` 为作品显示名（与 UI 小类文案强相关）。
- **链接**：
  - **`id`**：等于 **`Chara.works/id`**；并决定目录 **`charaWorks{六位}`**。
  - **`str`**：应与 **`Chara.works/str`** 一致。

### 3.5 `sortName`

- **含义**：列表排序用字符串，**不一定**等于 `name.str`。
- **官方规律（A001）**：
  - 含拉丁字母时：常取 **仅 A–Z / a–z / 0–9 拼接再转大写**（例：`charaWorks000184` → `BanG Dream! Ave Mujica` → `BANGDREAMAVEMUJICA`）。
  - 纯日文等：可能为 **假名读法或与 `name.str` 略有出入的排序键**（例：`メダリスト` 对应 `メタリスト`），**无法从显示名唯一自动推导**；工具对纯日文默认用 **`name.str` 全文**，若需与官方完全一致可手工改 `CharaWorks.xml`。

### 3.6 `priority`

- **含义**：同层内的显示优先级（官方样例为 `0`）。
- **链接**：一般不与 `Chara` 交叉引用；保持与 A001 同类数据一致即可。

### 3.7 `ranks`

- **含义**：官方条目中多为空元素 `<ranks />`。
- **链接**：与 `Chara.ranks`（角色阶级奖励）**不是同一份数据**；自制作品主数据可保持空，与 A001 `charaWorks000183` / `000184` 一致即可。

---

## 4. 与 ReleaseTag 主数据的关系（大类）

- **`Chara.releaseTagName`** 与 **`CharaWorks.releaseTagName`** 应指向 **同一条 ReleaseTag 的 `name`**。
- 自制时请在 **`releaseTag`** 目录下提供对应 **`ReleaseTag.xml`**，且 **`name`** 与 **Chara / CharaWorks** 对齐；**`titleName`** 供界面显示。

详见：[chara_releaseTag_works_选角分类说明.md](./chara_releaseTag_works_选角分类说明.md)。

---

## 5. 游戏内仍不显示时的排查清单

1. **CharaWorks 是否与 Chara 同包部署**  
   仅复制 `chara/` 而未把 **`charaWorks/`** 打进客户端读取的选项包 / 合并目录时，客户端读不到作品主数据。

2. **`releaseTagName` / `netOpenName` 是否与 Chara 完全一致**  
   逐字段比对（含空格、下划线）；不要只比对 `works`。

3. **`ReleaseTag` 主数据是否存在**  
   `releaseTagName.id/str` 在 **`releaseTag/*/ReleaseTag.xml`** 中是否有 **`name`** 匹配项。

4. **同一 `works.id` 多角色冲突**  
   若两个角色共用同一 `works.id`，但 **`releaseTagName` 或 `netOpenName` 不同**，则 **一条 CharaWorks 无法同时满足两者**；应 **拆分不同 `works.id`** 或 **统一所有相关 Chara** 的上述字段。运行 `scripts/sync_acus_chara_works.py` 会检测并打印警告。

5. **打包与缓存**  
   部分环境需重新生成 ACB/索引或清缓存后才会加载新 XML；以你实际使用的注入 / 打包流程为准。

---

## 6. 本仓库相关实现

| 能力 | 位置 |
|------|------|
| 写入单条 CharaWorks | `chuni_eventer_desktop/xml_writer.py` → `write_chara_works_xml` / `ensure_chara_works_xml` |
| 从一份 Chara 同步 | `ensure_chara_works_for_chara_xml` |
| 扫描整个 ACUS | `sync_all_chara_works_masters` |
| 命令行批量同步 | `scripts/sync_acus_chara_works.py` |
| 编辑角色 works 并写 CharaWorks | `chuni_eventer_desktop/ui/works_dialogs.py` → `CharaEditWorksDialog`（已带上 `netOpenName`） |

**作品库（缓存）仅保存 id/显示名**：新建作品**不会**再自动写 CharaWorks（避免在无角色上下文时写错 `releaseTag`）；请在有工作区时 **编辑该角色的 works** 或运行上述同步脚本。

---

## 7. 参考路径速查

- 官方角色示例：`A001/chara/chara024760/Chara.xml`
- 官方作品示例：`A001/charaWorks/charaWorks000183/CharaWorks.xml`
- 拉丁标题作品示例：`A001/charaWorks/charaWorks000184/CharaWorks.xml`（`sortName` 全大写拉丁）
- 官方大类示例：`A001/releaseTag/releaseTag000020/ReleaseTag.xml`
