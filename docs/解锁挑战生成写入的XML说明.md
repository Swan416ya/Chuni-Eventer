# 创建「解锁挑战（完美挑战）」时写入的 XML 说明

本文说明在 **歌曲卡片右键 →「创建解锁挑战事件…」** 并成功确认后，工具对当前工作区 **ACUS 根目录** 下写入或修改了哪些 XML 文件。

实现入口：`chuni_eventer_desktop/unlock_challenge.py` 中的 `create_unlock_challenge_bundle`，以及 `chuni_eventer_desktop/ui/music_unlock_challenge_dialog.py`。

参考数据：A001 `unlockChallenge00010002`、`course00300005`～`009`、`reward040002705`、`event00016044`。

---

## 1. 新建的主数据文件

| 路径 | 说明 |
|------|------|
| `{ACUS}/reward/reward{奖励ID九位}/Reward.xml` | **自制乐曲解锁奖励**（与 `reward040002705` 同结构，`substances/type=6`，`music` 指向当前曲）。**奖励 ID 使用 `200000000`～`299999999`**（九位数字，目录名为 `reward` + 九位零填充）。 |
| `{ACUS}/course/course{课题ID八位}/Course.xml` | **共 5 份**，结构与 `course00300005` 一致。**课题 `name.id` 使用连续 5 个 `310000`～`319999` 内的空闲号**（与官方 `30000x` 区分）。每关 `infos` 内 3 条 `CourseMusicDataInfo` 指向同一谱面难度；难度按该曲已启用 fumen 在 5 关间分配。 |
| `{ACUS}/unlockChallenge/unlockChallenge{挑战ID八位}/UnlockChallenge.xml` | 解锁挑战主数据；`rewardList` 仅含上述自制 Reward；`courseList` 含 5 个自制课题。 |
| `{ACUS}/event/event{事件ID八位}/Event.xml` | `substances/type=16`，`unlockChallengeName` 指向本次挑战。 |

---

## 2. 可能被新建或追加修改的排序表

| 路径 | 操作 |
|------|------|
| `{ACUS}/course/CourseSort.xml` | 为 5 个新课题 `id` 各追加一条 `SortList/StringID`（不重复则跳过）。若文件不存在则按 A001 结构创建。 |
| `{ACUS}/unlockChallenge/UnlockChallengeSort.xml` | 追加本次挑战 `id`。 |
| `{ACUS}/event/EventSort.xml` | 追加本次事件 `id`。 |

---

## 3. 不会改动的文件

- **`Music.xml`**：只读取 `releaseTagName`、`netOpenName`、已启用谱面；不写回。

---

## 4. ID 约定摘要

| 数据 | 自制约定 |
|------|-----------|
| Reward | `200000000`～`299999999`（避开官方常用 `07xxxxxxx` 等） |
| Course（本功能） | `310000`～`319999` 内连续 5 个空闲 ID |
| UnlockChallenge | 仍从 `90001` 起避撞（与既有逻辑一致） |
| Event | `next_custom_event_id`（默认自 `70000` 起避撞） |

---

## 5. 界面提示

- 生成后，若 **UnlockChallenge** 中已引用该乐曲 ID，**乐曲卡片**左上角会显示 **蓝底 + 黄锁 🔒** 角标（`MusicItem.has_perfect_challenge`）。

---

## 6. 前置目录

`ensure_acus_layout` 会创建 `unlockChallenge`；`reward`、`course`、`event` 在常规 ACUS 中应已存在。
