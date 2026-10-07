# PJSK 烤谱（Project SEKAI 官谱 → CHUNITHM）

> 2026-10-07 起，软件内的 PJSK→中二链路整体替换为上游
> `E:\koishi Project\Chunicharter\pjsk2chuni`（下称「上游」）的转谱逻辑 + PenguinTools `option build`。
> 上游规格与裁定依据在其 `docs/01-why.md` … `08-environment.md`，本文只写**本软件内的接线**。

## 1. 入口与用户流程

1. 乐曲页 →「新增」→ 渠道弹窗选 **PJSK**（图标 `pjsk.png`，与 SwanSite / pgko 并列；**不再是实验性功能**）。
2. `PjskHubDialog`（`ui/pjsk_hub_dialog.py`）列出本地 `pjsk_cache/pjsk_XXXX/` 缓存；
   点「从网络下载新曲…」打开 `PjskSusDownloadDialog`（谱面来源与原链路一致：PJSK 官方资源镜像）。
3. 选中一首 →「转换并写入 ACUS…」→ `PjskConvertToAcusDialog`：
   填中二乐曲 ID / 曲名 / 曲师 / 谱师、各难度定数、（可选）舞台与 ULT 解锁事件。
   定数默认值由该难度的 **PJSK 等级等比映射**得到（见 §1.1）。
4. 后台线程执行 `pjsk2chuni.pipeline`：转换 → 打包 → 写入 ACUS，并刷新乐曲列表。

## 1.1 定数默认可映射（PJSK 1..38 → 中二 1..15.5）

```
定数 = 1 + (PJSK等级 - 1) × (15.5 - 1) / (38 - 1)      # 两位小数
```

例：`12 → 5.31`、`18 → 7.66`、`24 → 10.01`、`30 → 12.36`、`32 → 13.15`、`38 → 15.50`；
再由 `const_to_level_pair()` 拆成 Music.xml 的 `(level, levelDecimal)`（12.6 → 12 / 60）。
实现：`pjsk2chuni/pipeline.py` 的 `pjsk_level_to_chuni_const()` / `const_to_level_pair()`。

PJSK 侧元数据（等级 `playLevel`、音频延迟 `fillerSec`）来源：

- **下载时写入**：`save_pjsk_bundle_to_cache(..., play_levels=..., filler_sec=...)` 把每个难度的等级存进
  `slots[].pjskPlayLevel`、把音频延迟存进 `fillerSec`（下载对话框本来就要拉曲目/难度索引，零额外代价）。
- **老缓存回填**：`PjskHubDialog` 显示时若发现某缓存缺等级或 `fillerSec`，会在后台拉一次索引，
  用 `backfill_bundle_play_levels()` / `backfill_bundle_filler_sec()` 补写 manifest（离线 / 镜像不可用则静默跳过）。
- **兜底**：等级仍缺失时用 4 / 8.6 / 12.6 / 14.6 / 15（界面会提示"未记录 PJSK 等级"，可手工改）；
  `fillerSec` 缺失时退回实测前导静音（见 §3）。

> 官方 PJSK 官谱的 SUS 里 `#PLAYLEVEL` 是空串（元数据被清空），所以等级只能来自曲目数据库。

## 1.2 两层数据源的可用性（2026-10-07 实测）

| 层 | 用途 | 域名 | 实测 |
|---|---|---|---|
| **资源层** | SUS 谱面、封面、曲绘、长音频 | `assets.pjsek.ai`（pjsekai-assets）、`storage.sekai.best`（sekai-jp-assets） | ✅ 全通：SUS 4 难度、封面/曲绘、长音频（21.5 MB / 7.9 s）都能下 |
| **曲目数据库层** | 曲目列表、难度等级、`musicVocals`、角色名 | `api.pjsek.ai/database/master`、`sekai-world.github.io/sekai-master-db-diff` | ❌ 直连全挂：API 返回 **503**，`github.io` / `raw.githubusercontent.com` / `cdn.jsdelivr.net` 被断连（各等一个超时） |

`sekai-master-db-diff` 就是 **sekai.best / Sekai Viewer** 用的那份数据（"Sekai Database" 同源），
所以缺的只是"能不能取到这份 JSON"。现在 `pjsk_sheet_client.load_sekai_master_json()` 按序回退 6 个来源：

```
api.pjsek.ai（有查询参数，先试；挂了才回退）
gcore.jsdelivr.net/gh/Sekai-World/sekai-master-db-diff@main     ← 实测可用（国内可直连）
gh-proxy.com/<raw.githubusercontent.com/...>                    ← 实测可用
ghproxy.net/<raw.githubusercontent.com/...>                     ← 实测可用
cdn.jsdelivr.net/gh/...@main / sekai-world.github.io / raw.githubusercontent.com（原路径，作后备）
```

细节：

- 首个成功的镜像会被记住（`_remember_master_json_base`），同一次运行不再重复探测不可达域名；
- 每次成功的响应写入 `.cache/pjsk_master/<name>.json`，**12 小时内直接读缓存**（实测重复调用 0.95s）；
  网络全挂时即使缓存过期也仍然使用（离线可用），彻底拿不到才报错并列出每个镜像的失败原因；
- 覆盖 `musics` / `musicDifficulties` / `musicVocals` / `gameCharacters` / `outsideCharacters`，
  即曲目列表、定数映射来源、人声版本选择都靠这一层。

## 2. 代码结构

| 位置 | 职责 |
|---|---|
| `chuni_eventer_desktop/pjsk2chuni/core.py` | **上游 `pjsk2chuni.py` 原样收录**（SUS 解析、标记音符分类、曲线烘焙、UGC 写出）。文件头有 SHA256 与同步日期；**请勿就地改转谱逻辑**，要改先改上游再整体复制。 |
| `chuni_eventer_desktop/pjsk2chuni/pipeline.py` | 本软件接线：UGC 头部元数据补丁、**PJSK 等级→定数映射**、音频对齐、`options.json` + `option build`、规范化、写入 ACUS。 |
| `chuni_eventer_desktop/penguin_tools_cli.py` | `build_option_with_penguin_tools_cli()`：`option build` 封装（含 **诊断检查**，见 §4）。 |
| `chuni_eventer_desktop/pjsk_acus_install.py` | 只留公共件：缓存清单 / `pjskPlayLevel` 与 `fillerSec` 读写回填、id 分配、MusicSort、ULT 解锁事件（+ PGKO 仍在用的 `build_music_xml`）。 |
| `chuni_eventer_desktop/pjsk_sheet_client.py` | **只下载**：封面/曲绘/音频/SUS + 写入 `pjskPlayLevel` / `fillerSec` → `pjsk_cache/`；曲目数据库走镜像链 + `.cache/pjsk_master/` 本地缓存（见 §1.2）。不再预生成 c2s 或 ACB/AWB。 |
| `chuni_eventer_desktop/pjsk_audio_chuni.py` | 只留底层件：ffmpeg 解码 48k WAV、本地 HCA/ACB/AWB 打包（PGKO、系统语音等仍在用）。 |
| `scripts/verify_pjsk2chuni_pipeline.py` | 端到端验证（见 §5）。 |
| `scripts/smoke_pjsk2chuni_ui.py` | 离屏 UI 冒烟测试。 |

已删除：`sus_to_c2s.py`（旧「SUS 直接丢给 PenguinTools chart convert」）、`ui/sus_c2s_debug_dialog.py`、
以及写入 ACUS 时的 **固定裁 9 秒 + `audio convert` + c2s-sanitize** 老链路。

## 3. 音频对齐（本次修复的核心）

老实现把片头固定裁 9 秒（`PJSK_AUDIO_TRIM_LEADING_SEC`）再让 PenguinTools 按 SUS 对齐，遇到 fillerSec ≠ 9 的曲子必然整体错位。

新实现（`pipeline.build_option_package`）：

1. **延迟值来自元数据**：pjsk `musics.json` 的 `fillerSec`（长音频开头静音长度，游戏/官谱就是拿它把谱面与音频对齐）。
   下载时写进缓存清单（`manifest.json` 的 `fillerSec`），老缓存打开「新增 → PJSK」时自动回填（与 §1.1 同一套机制）；
2. `ffmpeg` 按该值裁掉片头，得到 48 kHz 立体声 s16 WAV；
3. UGC 写 **`@BGMOFS 0.00000` + `@FLAG SOFFSET TRUE`**；PenguinTools 的真实偏移 `real = manual + 1 小节`（正数）
   → 用 `adelay` 补回一小节，同时完成游戏所需的 loudness 归一。

**为什么必须读元数据、不能靠实测前导静音**（本目录三首实测对比）：

| 歌曲 | `fillerSec`（元数据） | `measure_leading_silence()`（阈值 −44 dBFS） | 差 |
|---|---|---|---|
| 88☆彡 (0224) | 9.000 | 9.002 | +0.002 |
| 星界ちゃんと… (0328) | **8.051** | 9.034 | **+0.984** |
| 25時の情熱 (0409) | **8.302** | 9.664 | **+1.362** |

音频开头常有淡入/混响尾巴，阈值法会把"第一个超过 −44 dBFS 的采样"当成开头，比真实 filler 晚将近 1 秒，
照实测裁会让这些曲子整体错位约 1 秒。上游 `measure_leading_silence()` 的注释虽写着它等于 `fillerSec`，
但那只在兔洞 7067 上验证过，并不普遍成立。

> 只有缓存清单里**确实没有** `fillerSec`（离线且从未拉过曲目数据库）时，才退回 `core.measure_leading_silence()` 实测，
> 并在结果里标明来源（`BuildResult.trim_source`）。

> **为什么不照抄上游的 `@BGMOFS = -fillerSec`**：部分 `mua_wav` 版本（如 PenguinTools 2.3.3 资源）把 `-o -7.19`
> 的负号当选项而报错，音频会静默转换失败（CLI 仍返回 `success:true`）；懒人包内置的正是这一代 CLI。
> 「本侧先裁 + 正偏移」与上游时间轴完全等价，且两代 CLI 都能跑。
> 验证方式：ACB 时长应 ≈（裁切后音频时长 + 1 小节），`scripts/verify_pjsk2chuni_pipeline.py` 会实测比较，
> 并断言实际裁切量等于 `fillerSec`。

## 4. PenguinTools `option build` 的两条硬约束

1. **单项失败不报错**：音频/封面转不出来时 CLI 仍然 `success=true`，只在 `diagnostics` 里给 `error`。
   因此 `build_option_with_penguin_tools_cli()` 会主动扫描诊断并在有 error 时抛错（否则会出现"打包成功但没有音频"）。
2. **`options.json` 键名大小写敏感**，且部分键与上游示例不同：
   `customReleaseTagXml` / `customReleaseTagId` / `customReleaseTagTitleName` / `selectedGenreId` /
   `overrideChartGenre` / `hcaEncryptionKey`（必须是 JSON 数字）。`build_option_package` 已按 2.3.3 的 `OptionDocument` 写全。

其它要点：
- `@DIFF`：UGC 与 PenguinTools 枚举末两位错位 —— `4=WORLD'S END`、`5=Ultima`（见 `SLOT_UGC_DIFF`）。
- `@CONST` 决定 Music.xml 的 `<level>/<levelDecimal>`（12.6 → 12/60）；`@LEVEL` 仅用于 WE 星级。
- 主谱面决定 `<enableUltima>`：本实现给 ULTIMA 打 `@CMT #meta main true`、其余打 `false`，并同时传 `--main-difficulty`。
- 舞台：`option build` 无 UGC 入口，默认 stage 8；用户选了别的舞台时由 `patch_music_xml_stage()` 定点改写 Music.xml。
- 编码：PenguinTools 输出 XML 带 BOM，本实现统一转成 **c2s CRLF + XML 无 BOM**（用户库惯例）。
- `releaseTag` 固定 `-2 / PJSK`，genre 固定 `2 / niconico`；ULTIMA 存在时额外写 `event/eventXXXXXXXX/Event.xml`。

## 5. 如何验证

```powershell
# 端到端：与上游转换器逐字节等价 + option build + 写入临时 ACUS
$env:CHUNI_PENGUINTOOLS_CLI="<PenguinTools.CLI.exe>"
.venv-build\Scripts\python.exe scripts\verify_pjsk2chuni_pipeline.py `
    --bundle pjsk_cache/pjsk_0224 --music-id 7903 --levels 4.5 8.6 12.6 14.6 15

# UI 冒烟（离屏，不弹窗）
.venv-build\Scripts\python.exe scripts\smoke_pjsk2chuni_ui.py
```

脚本会断言：谱面正文与上游一致、头部 `@DIFF/@GENRE/@CONST/@SOFFSET/@CMT` 正确、
c2s CRLF 无 BOM、Music.xml（genre/releaseTag/等级/stage/sortName）、ACB 时长对齐、ACUS 落位与 ULT 事件。

## 6. 已知遗留

- 旧的 `pjsk_cache/pjsk_XXXX/chuni/`、`chuni_cue/`（老链路产物）不会被自动清理，可手工删除；
  新链路的工作目录是 `chuni_build/`。
- `c2s-sanitize` 工具与 `c2s_sanitize.py` 仍在设置里可选，但当前主链路不再调用（问题改在转换源头修）。
- `PenguinTools.CLI` 过旧（不支持 `option build`）时会在对话框报"未返回可解析的 JSON"，请到「设置 → 外部工具」更新。
