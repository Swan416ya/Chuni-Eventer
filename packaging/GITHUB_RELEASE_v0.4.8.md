# Chuni-Eventer v0.4.8

## 更新内容

- **CharaWorks 与角色主数据**
  - 完善 Chara / CharaWorks 写入与对齐逻辑：新建与编辑角色时按同一份 `Chara.xml` 同步 `releaseTagName`、`netOpenName` 与 `works`，并生成或更新对应 `charaWorks{六位}/CharaWorks.xml`。
  - 与 XVERSE `A000` 官方样本对齐的默认值与修复脚本：`netOpenName`（2800 / `v2_45 00_0`）、根节点 `xmlns`、`ranks` 内有效 `rewardSkillSeed`；可选运行 `python scripts/fix_acus_chara_a000_compat.py [ACUS根]` 批量修正已有包内角色与 `ddsImage`。
  - 角色侧 `releaseTagName` 默认写入 `0` / `v1 1.00.00`（仅 Chara/CharaWorks 内联字段；不强制在 ACUS 内新增 ReleaseTag 主数据）。

- **任务（Quest）**
  - 任务编辑与落盘流程可用：支持在 ACUS 中创建与维护 Quest 主数据（与导航「任务」入口一致）。

- **奖励（Reward）**
  - 管理页奖励类型筛选与展示优化：可按奖励类型分类浏览，便于在大量 Reward 中定位条目。

- **其他**
  - 乐曲「新增」渠道选择中 **pgko.dev 入口暂时置灰**（维护中），Swan 与本地压缩包导入仍可使用。

## 打包说明

- 版本号：`chuni_eventer_desktop/version.py` 中 `APP_VERSION = "0.4.8"`（窗口标题与说明一致）。
- Windows 一键打包：`powershell -ExecutionPolicy Bypass -File ".\scripts\build_windows.ps1" -Version 0.4.8`  
  详见仓库内 `packaging/BUILD_AND_DISTRIBUTION.md`。

## 已知问题

- pgko 相关链路保留在代码中，待后续验证后再开放 UI 入口。
- 若游戏环境与 A000 解禁轴不一致，请自行核对 `netOpenName` 与官方 option。
