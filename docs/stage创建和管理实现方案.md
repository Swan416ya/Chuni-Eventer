# Stage 创建和管理实现方案（A001）

本文面向 `Chuni-Eventer` 的后续开发，目标是实现「Stage（场景）创建与管理」能力。  
内容基于仓库中现有对 A001 数据的解析与写入逻辑整理，覆盖 XML 结构、引用关系、数据流和实现步骤。

---

## 1. Stage XML 真实结构（基于多个真实样本）

已确认样本：

- `A001/stage/stage000011/Stage.xml`
- `D:/Chunithm_XVerseX/bin/option/A001/stage/stage027201/Stage.xml`

可见 `Stage.xml` 字段在不同包/版本下会有扩展，需按“核心字段 + 可选扩展字段”兼容。  
可稳定确定的字段如下：

- `dataName`
- `netOpenName`（`id/str/data`）
- `releaseTagName`（`id/str/data`）
- `name`（`id/str/data`）
- `notesFieldLine`（`id/str/data`）
- `notesFieldFile/path`（如 `nf_00011.afb`）
- `baseFile/path`（如 `st_00011.afb`）
- `objectFile/path`（可空）
- `image/path`（可选；存在时通常为 `CHU_UI_Stage_xxxxx.dds`，可用于预览）
- `disableFlag`（可选）
- `defaultHave`（可选）
- `enablePlate`（可选）
- `sortName`（可选）
- `priority`（可选）

可用结构示意：

```xml
<?xml version="1.0" encoding="utf-8"?>
<StageData xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <dataName>stage00xxxxxx</dataName>
  <netOpenName>
    <id>...</id>
    <str>...</str>
    <data></data>
  </netOpenName>
  <releaseTagName>
    <id>...</id>
    <str>...</str>
    <data></data>
  </releaseTagName>
  <name>
    <id>xxxxxx</id>
    <str>StageName</str>
    <data></data>
  </name>
  <notesFieldLine>
    <id>...</id>
    <str>...</str>
    <data></data>
  </notesFieldLine>
  <notesFieldFile>
    <path>nf_xxxxx.afb</path>
  </notesFieldFile>
  <baseFile>
    <path>st_xxxxx.afb</path>
  </baseFile>
  <objectFile>
    <path></path>
  </objectFile>
  <image>
    <path>CHU_UI_Stage_xxxxx.dds</path>
  </image>
</StageData>
```

---

## 2. Stage 的引用关系（必须一起考虑）

### 2.1 Music -> Stage

- `Music.xml` 使用 `stageName` 引用 Stage：
  - `stageName/id`
  - `stageName/str`
- 代码位置：
  - 读取：`chuni_eventer_desktop/acus_scan.py` 的 `scan_music()`
  - 写入：`chuni_eventer_desktop/pjsk_acus_install.py` 的 `build_music_xml()`

结论：Stage 管理不是孤立功能，必须与乐曲编辑联动（至少支持从 Stage 列表选一个 ID/str 写回 `Music.xml`）。

### 2.2 Reward(type=13) -> Stage

- `Reward.xml` 的 `RewardSubstanceData` 在 `type=13` 时表示场景奖励：
  - `stage/stageName/id`
  - `stage/stageName/str`
- 代码位置：
  - 解析：`chuni_eventer_desktop/acus_scan.py`（`_summarize_reward_substance()`）
  - Map 格子回填：`chuni_eventer_desktop/ui/map_add_dialog.py`

结论：删除/修改 Stage 时要检查 Reward 引用，避免悬挂引用。

### 2.3 Map -> Reward -> Stage（地图发放场景的真实链路）

地图不是直接写 `stageId`，而是通过 Reward 间接发放：

1. `map/Map.xml` 的 `MapDataAreaInfo.rewardName.id` 指向某个 Reward  
2. 该 `reward/Reward.xml` 的 `RewardSubstanceData.type` 必须是 `13`（场景）  
3. 同一条 Reward 中 `stage/stageName/id` 指向 `stage/Stage.xml` 的 `name.id`

链路表达式：

- `MapDataAreaInfo.rewardName.id -> RewardData(name.id,type=13) -> stage/stageName.id -> StageData(name.id)`

### 2.4 打包与删除联动

- 删除音乐时会根据 `Music.stage.id` 定位并删除对应 Stage 目录：
  - 位置：`chuni_eventer_desktop/music_delete.py`
- 社区上传包会包含 `stage/<dir>`（若存在）：
  - 位置：`chuni_eventer_desktop/ui/github_sheet_dialog.py`

结论：Stage 生命周期当前偏「从属于某首歌」，但未来要支持共享 Stage 时需引入引用计数或引用扫描防误删。

---

## 3. 建议的数据规范（创建时强约束）

为保证管理可用性，建议统一以下规则：

1. **目录命名**
   - `stage/stage{ID6}/Stage.xml`
   - 示例：`stage/stage123456/Stage.xml`
2. **主键字段**
   - `Stage.xml` 的 `name/id` 必须等于 `{ID6}` 的数值部分
3. **字符串字段**
   - `name/str` 允许自定义，推荐可读名称
   - `Music.xml` 与 `Reward.xml` 中引用时，`str` 允许冗余，但建议和 Stage 主记录一致
4. **资源路径**
   - `notesFieldFile/path` 与 `baseFile/path` 为核心字段，使用 Stage 目录下相对路径
   - 推荐命名：`nf_{ID5}.afb`、`st_{ID5}.afb`（与样本风格一致）
   - `objectFile/path` 可为空
   - 若提供预览图，写入 `image/path=CHU_UI_Stage_{ID}.dds`（文件放在 Stage 目录内）
5. **无效值约定**
   - 未设置引用统一使用 `id=-1, str=Invalid`

---

## 4. 功能实现拆分

### 4.1 阶段一：只做「可创建 + 可选择 + 安全删除」

#### A. Stage 索引能力（已有）

- 复用 `scan_stages()` 生成列表，不新增底层扫描逻辑。

#### B. 新增 Stage 创建器

- 建议位置：`chuni_eventer_desktop/stage_write.py`（新文件）
- 核心接口（建议）：
  - `create_stage(acus_root: Path, stage_id: int, stage_str: str, notes_field_line: IdStr | None, notes_field_file: str, base_file: str, object_file: str = "") -> Path`
- 执行内容：
  1. 校验 ID 冲突（目录存在 / name.id 已存在）
  2. 生成 `stage/stage{ID6}/Stage.xml`
  3. 写入 `netOpenName` / `releaseTagName`
  4. 写入 `notesFieldFile` / `baseFile` / `objectFile`

#### C. Music 编辑 UI 联动

- 在乐曲编辑/导入流程中，把 `stage_id + stage_str` 从「手填」升级为：
  - 下拉选已有 Stage
  - 可一键新建 Stage

#### D. 安全删除策略

- 删除 Stage 前做全局引用扫描：
  - 扫 `music/**/Music.xml` 的 `stageName/id`
  - 扫 `reward/**/Reward.xml` 的 `stage/stageName/id`（type=13）
- 若存在引用：
  - 阻止删除，弹窗列出引用数量与示例路径
- 若无引用：
  - 删除 `stage/stage{ID6}` 目录

### 4.2 阶段二：管理页（批量治理）

建议新增「Stage 管理」页面，字段至少包含：

- `name.id`
- `name.str`
- `releaseTagName`
- `netOpenName`
- `notesFieldLine.id/str`
- `notesFieldFile/path`
- `baseFile/path`
- `objectFile/path`
- `image/path`（若有）
- `disableFlag/defaultHave/enablePlate/sortName/priority`（若有）
- 被 Music 引用次数
- 被 Reward(type=13) 引用次数

支持操作：

- 新建
- 编辑（str、tag、notesFieldLine、afb 路径）
- 引用检查
- 删除（受引用保护）
- 导出/导入单个 Stage（为社区包能力预留）

---

## 5. XML 读写实现细节

### 5.1 读取

- 使用 `xml.etree.ElementTree`（与项目一致）。
- 对 `id` 读取统一走安全整数转换（参考 `_safe_int`）。
- 对缺失字段做容错：
  - 无 `notesFieldLine` 时默认 `Invalid`
  - 无 `objectFile/path` 时置空

### 5.2 写入

- 写回统一 `encoding="utf-8", xml_declaration=True`
- 建议调用 `ET.indent()` 保持可读性（与现有写法一致）
- 生成 `<id>/<str>/<data>` 结构时复用现有 helper 设计风格（如 `_entry_el` / `_invalid_entry`）

---

## 6. 与现有模块的改造点

1. `chuni_eventer_desktop/ui/pjsk_hub_dialog.py`
   - 现状：手填 `stageName.id/str`
   - 改造：改为 Stage 下拉 + 新建按钮
2. `chuni_eventer_desktop/pjsk_acus_install.py`
   - 现状：只写 `Music.xml` 的 `stageName`
   - 改造：导入流程前校验目标 Stage 是否存在；不存在时提示创建
3. `chuni_eventer_desktop/music_delete.py`
   - 现状：按 `Music.stage.id` 直接定位删除 Stage
   - 改造：删除前增加「是否被其他 Music/Reward 引用」检查，避免误删共享 Stage
4. `chuni_eventer_desktop/ui/github_sheet_dialog.py`
   - 现状：按删除计划自动打包 stage 目录
   - 改造：保持不变，但在未来共享 Stage 场景需支持可选打包策略

---

## 7. 关于“Stage 预览图到底存在哪里”

结论更新：**Stage 预览图路径存放在 `Stage.xml` 的 `image/path`（若该字段存在）。**

1. `Reward.xml`（含 `type=13` 场景奖励）只存：
   - `stage/stageName/id`
   - `stage/stageName/str`
   不存图片路径。
2. `Stage.xml` 的图片信息在 `image/path`：
   - 例如：`CHU_UI_Stage_27201.dds`
   - 对应文件位于同目录：`stage/stage027201/CHU_UI_Stage_27201.dds`（按常见包结构）
3. `Stage.xml` 同时还存演出相关资源：
   - `notesFieldFile/path`（`nf_*.afb`）
   - `baseFile/path`（`st_*.afb`）
   - `objectFile/path`（可空）
4. 因此地图发 Stage 奖励时，显示流程应为：
   - Map -> Reward(type=13) -> stageName.id -> Stage.xml
   - 再从 Stage.xml 的 `image/path` 取预览 DDS（若字段缺失则降级为无图预览）

工程实现建议：

- Stage 列表优先展示 `image/path` 对应 DDS 预览；找不到文件时降级为文本预览（ID、名称、notesFieldLine、afb 文件名）。
- 创建 Stage 时把 `image/path` 作为可选输入项（推荐可自动按 ID 生成默认命名）。

---

## 8. 验收标准（MVP）

满足以下条件即认为 Stage 功能可上线：

1. 可新建合法 `Stage.xml` 并被 `scan_stages()` 正常识别
2. `Music.xml` 可通过 UI 绑定已有 Stage（不再只能手填）
3. 删除 Stage 有引用保护，不会破坏已有 Music/Reward
4. 打包上传时 Stage 目录可随音乐包正确包含
5. 全流程无新增解析异常（扫描、导入、删除）

---

## 9. 风险与后续校准项

1. 当前仓库缺少真实 `A001/stage/**/Stage.xml` 样本，字段集合来自现有代码可见结构，后续建议用官方样本补充比对。
2. 若后续发现 Stage 存在排序文件（类似 `MapSort`）或额外索引文件，需要追加「注册步骤」。
3. 若 Stage 被设计为全局共享资源，需将现有「随歌曲删除 Stage」策略升级为引用计数策略。

---

## 10. 推荐开发顺序

1. 先做 `stage_write.py`（创建 + 校验 + 删除前引用扫描）
2. 再改 `pjsk_hub_dialog.py`（Stage 下拉 + 新建）
3. 最后改 `music_delete.py`（删除保护）并做端到端验证

按这个顺序改，回归成本最低，且能尽快形成可用闭环。
