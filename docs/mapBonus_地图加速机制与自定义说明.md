# MapBonus：地图加速机制与自定义说明

本文基于官方 `A001/mapBonus` 与本仓库 `Map/MapArea` 写入逻辑整理，说明：

- `MapBonus.xml` 的字段语义
- 该机制如何绑定到地图
- 当前工具“新建地图”默认使用哪条 `mapBonus`
- 如何新增自定义 `mapBonus`
- 后续把它做成 UI 功能的实现方案

---

## 1. MapBonus 在地图系统里的绑定关系

核心链路是三层：

1. `Map.xml` 里每个 `MapDataAreaInfo` 通过 `mapAreaName` 指向一个 `MapArea.xml`
2. `MapArea.xml` 里 `mapBonusName`（`id/str`）指向 `mapBonus/mapBonusXXXXXXXX/MapBonus.xml` 的 `name`
3. `MapBonus.xml` 里的 `substances` 决定“满足什么条件会加速（额外格数）”

也就是：

`Map.xml (MapDataAreaInfo.mapAreaName)` -> `MapArea.xml (mapBonusName)` -> `MapBonus.xml (substances)`

---

## 2. MapArea 与 MapBonus 的关键字段

`MapArea.xml` 里与加速最相关的是：

- `mapBonusName.id/str`：引用哪条 `MapBonusData.name`
- `shorteningGridCountList`：8 个 `count`，用于“缩短格数”配置（每档条件触发时的减格量）
- `mapAreaBoostType` / `mapAreaBoostMultiple`：区域加成参数（官方常见 `0` / `10`）

如果 `mapBonusName = -1 / Invalid`，通常就不会有有效加速条件。

---

## 3. MapBonus.xml 字段如何理解（逐字段）

`MapBonusData` 根：

- `dataName`：目录名，通常是 `mapBonus{8位ID}`
- `name.id/str`：给 `MapArea.mapBonusName` 引用的主键
- `substances/list`：条件列表（每条是 `MapBonusSubstanceData`）

`MapBonusSubstanceData`：

- `type`：条件类别代码（官方常见 `1/5/6/9`）
- 各维度节点（`music` / `musicGenre` / `musicWorks` / `chara` ...）：
  - `point`：该条命中时加成格数
  - `...Name.id/str`：匹配对象（`-1/Invalid` 表示该维度不参与匹配）
- `charaRank/charaRank`：角色等级阈值（仅在“角色等级>=N”类规则使用）
- `charaRank/explainText`：展示文本，可留空

可粗略理解为：命中某条 `substance` 后，系统按该条 `point`（加成格数）参与加速结算，最终反映到地图移动格数。

---

## 4. 当前工具“新建地图”默认 mapBonus

当前“新建地图”默认仍保持：

- `mapBonusName.id = -1`
- `mapBonusName.str = Invalid`

即默认不绑定加速规则。若需要加速，需在 MapArea 参数里手动绑定或新建 `mapBonus`。

---

## 5. 现在允许配置的规则类型（已限制）

编辑器只允许以下 5 类（同类可重复；单个 `MapBonus` 最多 4 条）：

- 指定乐曲
- 指定流派乐曲
- 指定版本乐曲（releaseTag）
- 指定角色
- 角色等级大于等于某值

> 说明：`MapBonus` 结构里没有直接叫 `releaseTag` 的字段。当前实现把“指定版本乐曲（releaseTag）”落到 `musicWorks/worksName`（与官方 `VRS通常_*` 样本一致的版本维度写法）。

---

## 6. 每种规则的 XML 示例

以下示例均是单条 `MapBonusSubstanceData` 的核心段（为可读性省略了未使用维度，它们应为 `-1/Invalid`）。

### 6.1 指定乐曲

```xml
<MapBonusSubstanceData>
  <type>6</type>
  <music>
    <point>2</point>
    <musicName>
      <id>1234</id>
      <str>曲名示例</str>
      <data />
    </musicName>
  </music>
  <charaRank><point>1</point><charaRank>1</charaRank><explainText /></charaRank>
</MapBonusSubstanceData>
```

### 6.2 指定流派乐曲

```xml
<MapBonusSubstanceData>
  <type>5</type>
  <musicGenre>
    <point>2</point>
    <genreName>
      <id>3</id>
      <str>東方Project</str>
      <data />
    </genreName>
  </musicGenre>
  <charaRank><point>1</point><charaRank>1</charaRank><explainText /></charaRank>
</MapBonusSubstanceData>
```

### 6.3 指定版本乐曲（releaseTag 维度）

```xml
<MapBonusSubstanceData>
  <type>6</type>
  <musicWorks>
    <point>1</point>
    <worksName>
      <id>23</id>
      <str>[ORIGINAL] Ver. NEW PLUS</str>
      <data />
    </worksName>
  </musicWorks>
  <charaRank><point>1</point><charaRank>1</charaRank><explainText /></charaRank>
</MapBonusSubstanceData>
```

### 6.4 指定角色

```xml
<MapBonusSubstanceData>
  <type>1</type>
  <chara>
    <point>2</point>
    <charaName>
      <id>70000</id>
      <str>角色名示例</str>
      <data />
    </charaName>
  </chara>
  <charaRank><point>1</point><charaRank>1</charaRank><explainText /></charaRank>
</MapBonusSubstanceData>
```

### 6.5 角色等级 >= N

```xml
<MapBonusSubstanceData>
  <type>9</type>
  <!-- 该模式下角色目标固定 Invalid -->
  <chara>
    <point>1</point>
    <charaName>
      <id>-1</id>
      <str>Invalid</str>
      <data />
    </charaName>
  </chara>
  <charaRank>
    <point>1</point>
    <charaRank>26</charaRank>
    <explainText>26以上</explainText>
  </charaRank>
</MapBonusSubstanceData>
```

---

## 7. 如何新增自定义 MapBonus（手工方式）

1. 在 ACUS 下新建目录：`mapBonus/mapBonus{8位ID}/`
2. 新建 `MapBonus.xml`，`name.id/str` 设为你的新值（需全局唯一）
3. 参考官方条目新增 `substances/list/MapBonusSubstanceData`
4. 在目标 `MapArea.xml` 里把 `mapBonusName.id/str` 改成新条目
5. 视需要调整 `shorteningGridCountList`（8 个 count）
6. 进游戏实测一局，验证条件命中后移动格数是否增加

建议：

- 先复制一条官方稳定样本（如 `mapBonus00920186`）再改
- 一次只改一个维度（例如先做“指定乐曲 works 加速”），便于排错

---

## 8. 已实现的自定义能力

### 8.1 MapArea 绑定层（新建/编辑地图时）

在“编辑区域参数(MapArea)”弹窗中，现已支持：

- `选择现有 mapBonus`（扫描 `ACUS/mapBonus/*/MapBonus.xml`）
- `新建 mapBonus…`（直接创建并回填到当前 `MapArea.mapBonusName`）
- `编辑当前 mapBonus…`（按当前 `mapBonusName.id` 打开编辑器）

同时保留 `mapBonusName.id/str` 手填，兼容历史数据。

### 8.2 MapBonus 管理页

主导航新增 `MapBonus` 页面，可统一管理：

- 列表字段：ID、名称、`substances` 条数、`type` 摘要、来源 XML
- 双击条目可进入编辑器修改并保存
- 顶部“新增”可直接创建新的 `MapBonus`

### 8.3 MapBonus 编辑器

编辑器支持维护：

- 主键：`mapBonusName.id/str`
- 条件行（`MapBonusSubstanceData`），仅上述 5 类
- `target.id/target.str` 不再让用户手填，改为按“条件类型”给下拉目标：
  - 指定乐曲 -> 乐曲下拉
  - 指定流派 -> 流派下拉
  - 指定版本(releaseTag) -> releaseTag 下拉
  - 指定角色 -> 角色下拉
  - 角色等级>=N -> 目标栏改为“等级阈值输入”，无下拉

保存后落盘到：`ACUS/mapBonus/mapBonus{8位ID}/MapBonus.xml`

### 8.4 为什么之前“指定乐曲”还出现等级字段

此前编辑器采用“通用 XML 表格”设计，直接暴露了 `MapBonusSubstanceData` 的共通字段（包括 `charaRank`），
所以即使选了“指定乐曲”，界面仍会看到等级字段，容易造成误解。

现已改为“按业务类型驱动”：

- 非“角色等级>=N”类型时，不提供等级阈值输入项（内部固定写 `1`）
- 只有“角色等级>=N”时才显示等级阈值输入
- 其它底层字段由程序按类型自动填充

---

## 9. MapBonus 能否控制“通关格子数”？

结论：**不直接在 `MapBonus.xml` 控制。**

- `MapBonus.xml` 负责“命中哪些加速条件”和“条件点数（point）”
- 实际格数侧参数在 `MapArea.xml`：
  - `shorteningGridCountList`（8 项）
  - `mapAreaBoostType` / `mapAreaBoostMultiple`

所以如果你要调“7 格变更快/更慢”的体感，需要同时看 `MapBonus` 条件 + `MapArea` 缩短格参数。

---

## 10. 排错清单

- 地图不加速：
  - 检查 `MapArea.mapBonusName` 是否引用存在的 `MapBonus`
  - 检查 `MapBonusData.name.id/str` 是否与 `MapArea` 一致
  - 检查 `substances` 是否全是 `Invalid`（等于没有有效条件）
- 条件看似命中但不生效：
  - 先把 `shorteningGridCountList` 全设为明显值（如 `1,1,1,1,1,1,1,1`）做 A/B 对比
  - 再逐项还原，定位是条件不命中还是减格量太小
