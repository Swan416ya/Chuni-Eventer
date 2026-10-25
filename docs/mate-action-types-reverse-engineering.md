# Mate actionType 触发条件逆向记录

本文记录 CHUNITHM 2.50 本地程序对 `Mate.xml/actions/MateActionData/actionType`
的实际使用方式。结论来自本地数据库、官方 Mate XML 与原生程序静态分析；没有运行或
修改游戏程序。

## 结论

`actionType` 不是“情绪编号”。它的标准 1～18 槽分为三类：

- `1`：初始化、复位或默认待机；
- `2～15`：歌曲结算的 **score rank**，从 D 到 SSS+ 一一对应；
- `16～18`：Mate ROOM（程序与素材内部称 `MateGarden`）流程中的三个动作，
  不属于歌曲成绩等级。

因此旧的“Type 1=待机、Type 2=生气、Type 3=悲伤、Type 4～18=开心”只是某些
官方角色的动画美术分配，不是游戏调度语义。比如 Type 2 实际表示 D 评价；某个角色
可以为 D 配生气动作，另一个角色也可以为 D 配悲伤或普通动作。

## 结算评价与动作的精确映射

本地 `data/db/ScoreRankTableRecord.bin` 有 14 条记录。结算页构造了同样长度的表，
每条记录的最后一个字段依次为 `2～15`，并以当前 score-rank 索引读取该字段后交给
Mate 控制器。对应关系如下：

| score-rank 索引 | 评价 | 最低分 | actionType |
|---:|:---:|---:|---:|
| 0 | D | 0 | 2 |
| 1 | C | 500,000 | 3 |
| 2 | B | 600,000 | 4 |
| 3 | BB | 700,000 | 5 |
| 4 | BBB | 800,000 | 6 |
| 5 | A | 900,000 | 7 |
| 6 | AA | 925,000 | 8 |
| 7 | AAA | 950,000 | 9 |
| 8 | S | 975,000 | 10 |
| 9 | S+ | 990,000 | 11 |
| 10 | SS | 1,000,000 | 12 |
| 11 | SS+ | 1,005,000 | 13 |
| 12 | SSS | 1,007,500 | 14 |
| 13 | SSS+ | 1,009,000 | 15 |

这也解释了官方 XML 中看似不一致的动作复用：

- `mate000101`（ナイ）为 D 配“怒01”、为 C 配“哀01”，B～AAA 复用“喜01”，
  S～SSS+ 复用“喜02”；
- `mate030000`（ユニ）为 D～AAA 全部使用悲伤动作，S～SS+ 使用喜悦动作，
  SSS/SSS+ 使用专门的 Peace 动作；
- `mate031006` 将 1～18 全部映射为同一个普通动作，说明全槽复用也是受游戏接受的
  降级方案，只是不会表现不同场景。

## 程序调用链证据

### 普通歌曲结算

`PlayMusicResultScoreObject` 所在代码区的函数 `0x00CF4CF0`：

1. 在栈上构造 14 条、每条 5 个 `uint32` 的结果显示记录；
2. 每条记录 `+0x10` 的值依次为 `2, 3, ..., 15`；
3. 从当前玩家结果对象取得 score-rank 索引；
4. 在 `0x00CF534E～0x00CF5357` 用 `index * 20 + 0x10` 读取 actionType；
5. 连同 `1000 ms` 延迟传给 `CommonMateObject`。

等价的简化伪代码为：

```cpp
static const ResultPresentation rankPresentation[14] = {
    /* D    */ { ...,  2 },
    /* C    */ { ...,  3 },
    /* B    */ { ...,  4 },
    /* BB   */ { ...,  5 },
    /* BBB  */ { ...,  6 },
    /* A    */ { ...,  7 },
    /* AA   */ { ...,  8 },
    /* AAA  */ { ...,  9 },
    /* S    */ { ..., 10 },
    /* S+   */ { ..., 11 },
    /* SS   */ { ..., 12 },
    /* SS+  */ { ..., 13 },
    /* SSS  */ { ..., 14 },
    /* SSS+ */ { ..., 15 },
};

mate->enqueueAction(rankPresentation[currentScoreRank].actionType, 1000);
```

### 课程结算

`PlayCourseResultTrackObject` 的函数 `0x00CA75B0` 构造相同的 14 条表。它从对象
`+0x28C` 读取 score-rank 索引，并在 `0x00CA7BDA～0x00CA7BE3` 读取同一位置的
actionType，以 `500 ms` 延迟交给 Mate 控制器。

这说明普通歌曲结算和课程结算共用同一套“评价 → Mate 动作”映射，区别只是展示
流程和延迟。

### CommonMateObject

两个结算页最终调用 `CommonMateObject` 的延迟动作入口：

- 外层包装位于 `0x00B65E90`；
- 内部队列函数位于 `0x00B66CF0`；
- 延迟到期后由 `0x00B651F0` 的更新逻辑取出 actionType；
- 实际按 `MateActionData.actionType` 查找并播放动作的函数位于 `0x00B66950`。

`FULL COMBO`、`ALL JUSTICE`、CLEAR 状态等会影响结算页自己的图标、特效和声音，
但在已还原的 Mate 派发路径上，传入的 actionType 只取自最终 score-rank 索引。
因此目前没有证据表明这些达成状态会覆盖 2～15 的 Mate 动作选择。

## actionType 1 与 16～18

### Type 1

`CommonMateObject` 在初始化、恢复和结束动作时多处显式派发 Type 1。其他页面创建
Mate 时也会显式发送 Type 1。因此它应理解为默认/复位动作，而不是一种结算评价。

### Type 16～18

`PlayMateGardenObject` 在 `0x00D5E127～0x00D5E196` 按顺序注册以下 16 个状态：

```text
Init → WaitTransition → StartEmote → CheerGameStartIn
     → CheerGameStartCount → CheerGameLoop
     → CheerGameFinishIn → CheerGameFinishOut
     → ResultPopUpIn → FriendShipGauge → FriendShipLevelUp
     → ResultCheck → ResultPopUpOut → EndEmote
     → ItemGet → AllContentsFinish
```

状态回调表从对象偏移 `+0x04` 开始，前 15 个可执行状态各占连续三个函数指针，分别是
进入、逐帧更新和退出回调；`AllContentsFinish` 是流程终点标记，没有对应的三指针槽。
将三个 actionType 派发函数反查到这张表后，可以得到精确绑定：

| actionType | 状态与回调 | 回调表偏移 | 派发地址 | 实际调度语义 |
|---:|---|---:|---:|---|
| 16 | `StartEmote` 进入回调 | `+0x1C` | `0x00D5A66F` | Mate ROOM 演出开始时派发一次，并启动 1000 ms 动作计时 |
| 17 | `CheerGameLoop` 更新回调 | `+0x44` | `0x00D5C300` | 欢呼小游戏进行期间按“动作 1000 ms / 冷却”两阶段计时反复派发 |
| 18 | `EndEmote` 进入回调 | `+0xA0` | `0x00D5B0DE` | 进入结束演出时派发一次，同时启动 1000 ms 动作计时和结束流程计时 |

因此三个编号适合命名为：

- **16：Mate ROOM 开场动作**；
- **17：Mate ROOM 游戏中循环欢呼动作**；
- **18：Mate ROOM 收尾动作**。

它们不是友情槽升级、结果弹窗或道具获得动作；这些环节在状态机中都有独立状态，
而三个派发点没有落在那些状态的回调里。

Type 17 不是进入 `CheerGameLoop` 时只播一次。其更新回调维护一个标志和同一个计时器：
动作窗口为固定 1000 ms，结束后切换到从对象 `+0x5E4` 读取的冷却时间；冷却结束后
再次派发 Type 17。外层还有一个运行时谓词会暂停这段调度，但静态程序中只有数值枚举
`0x32`，没有保留下可可靠命名的业务符号，因此本文不把它臆测成某个具体按键或条件。

带系统语音的官方 Mate 通常为 16、17、18 各提供两条候选记录：

- 16：`isVoice=true`、普通动作、结束后复位；
- 17：`isVoice=true`、普通动作、结束后复位；
- 18：`isVoice=true`、`isSpecialMotion=true`、不自动复位；
- 每个编号的两条记录使用不同 cue ID，供游戏在同一事件下选择语音变体。

这一字段组合也与状态机语义吻合：16/17 播完回到通常姿态，尤其 17 会在小游戏循环中
再次触发；18 属于结束演出，官方语音角色通常把它标成特殊动作且不要求自动回到待机。
这是一种常见的官方素材配置，不是引擎对 16～18 的硬性格式约束。

无系统语音的官方 Mate 可以把这些字段全部设为 false/0，也可以将 16～18 都复用
同一动画。

## 对转换器的直接影响

### 单 GIF

单 GIF 没有可供 14 个评价分别选择的不同动作。最稳妥的界面与生成策略是：

- 不向普通用户展开 18 个编号；
- 显示“同一动画用于所有评价与 Mate ROOM 场景”；
- 后台将同一个 timeline 映射到 1～18；
- 保持 voice/lipsync/cue 关闭，除非用户确实提供完整的系统语音资源。

这种全槽复用有官方 Mate 样本支撑，不是格式错误，也不应单独造成窗口或游戏卡死。

### 多动作 PSB / 未来多 GIF

如果素材包含多个动作，基础模式应按真实场景分组，而不是按四种情绪分组：

1. D～BBB（2～6）；
2. A～AAA（7～9）；
3. S～SS（10～12）；
4. SS+～SSS+（13～15）；
5. 默认/复位、Mate ROOM 开场与收尾（1、16、18）；
6. Mate ROOM 游戏中循环（17）。

详细模式再允许逐项覆盖全部 18 槽。未覆盖的详细槽继承所属简略组，避免用户只是想
调整一两个特殊动作时重复选择 18 次。

预设可以替用户按评价区间复用动作，但 UI 必须明确这是“项目预设”，不能再描述为
“官方固定的情绪规律”。

## 证据范围与制品身份

分析对象：

- `D:\Chunithm_Mate\bin\chusanApp.unpact.exe`
  - 大小：26,306,048 bytes
  - SHA-256：`D504DD0A68676282349486D6ACB12158CFE53D98F2B818AC957C4C79E489A4A0`
- `D:\Chunithm_Mate\data\db\ScoreRankTableRecord.bin`
  - 大小：286 bytes
  - SHA-256：`9CE1D9F1BD958ECDD2EE7B386FC41C8133DB5964CF901508838D74CE68B5A792`
- 官方 Mate XML：`mate000101`、`mate000102`、`mate030000`、`mate030001`、
  `mate031004`、`mate031005`、`mate031006`。

证据类型与限制：

- score-rank 阈值与名称来自数据库原始记录；
- actionType 表和调用地址来自 x86 静态反汇编；
- 官方动作名称及 voice/special/reset/cue 字段来自本地 XML；
- 16～18 与 MateGarden 子状态的绑定来自状态注册顺序、三回调表槽位和实际派发函数
  三组静态证据的交叉验证；Type 17 外层 `0x32` 运行时谓词的业务名称尚未恢复；
- 地址只适用于上述哈希对应的本地 2.50 可执行文件。
