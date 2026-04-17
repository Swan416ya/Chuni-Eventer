# UGC 转谱外部参考索引

本文档整理当前用于理解 `UGC` 语法、`Margrete/UMIGURI` 行为，以及 `mgxc -> c2s` 对照实现的外部资料。

目标：减少“盲调”，优先依据规格与可复核实现推进 `UGC -> c2s`。

---

## 1) 官方/准官方规格（最高优先级）

- [Umiguri Chart v8 仕様（inonote gist）](https://gist.github.com/inonote/5c01e73781cab17765a1d93641d52298)  
  - 当前最核心的 UGC 语法参考。  
  - 包含头字段、`Bar'Tick`、正文 note 类型、`C` 类参数（颜色/interval）等定义。  
  - 我们的 `_parse_ugc` 应以此为“语法真相来源”。

- [UMIGURI 官方站（English）](https://umgr.inonote.jp/en/)  
  - 产品与文档入口，含下载、手册、Margrete 链接。

- [Margrete 导入 SUS/UGC（English）](https://umgr.inonote.jp/en/margrete/advanced/import/)  
  - 明确 UGC 版本兼容与导入行为说明。  
  - 可用于验证“编辑器端对 UGC 的接受语义”。

- [UMIGURI Add Songs](https://umgr.inonote.jp/en/docs/user-content/add-songs/)  
  - 确认 `.ugc/.sus` 支持、目录结构与音频格式。

---

## 2) 参考实现与对照项目（高优先级）

- [Foahh/PenguinTools](https://github.com/Foahh/PenguinTools)  
  - 关键价值：`mgxc -> c2s` 的开源实现（`MgxcParser`、`C2SConverter`）。  
  - 用法：作为“语义输出目标”对照，不直接解决 UGC 紧凑正文解析。

- [j1nxie/nai-rs](https://github.com/j1nxie/nai-rs)  
  - 轻量 CHUNITHM chart parser，可借鉴解析器结构与数据流分层。

---

## 3) 开发者与生态项目（中优先级）

- [inonote GitHub](https://github.com/inonote)  
  - 可找到 UMIGURI 生态周边仓库（如 `MargreteOnline`、`UmiguriSampleLedServer`、`umgr-hands`）。  
  - 这些仓库主要是周边能力，不是完整 UGC 转 c2s 核心。

- [4yn/slidershim](https://github.com/4yn/slidershim)  
  - 控制器/输入层生态参考，不直接提供谱面转换实现。

---

## 4) 社区经验材料（辅助）

- [An English Guide/Intro to UMIGURI](https://blog.pinapelz.com/blog/umiguri/)  
  - 价值：社区使用路径、文件分发形态、`.ugc/.mgxc` 常见实践。  
  - 局限：不是解析规范，不应替代规格文档。

---

## 5) 本仓库如何使用这些资料

建议顺序：

1. **语法层**：先按 v8 规格补齐 `_parse_ugc`（尤其 `C...` 与子节点语义）。  
2. **语义层**：以 `PenguinTools` 的 `mgxc -> c2s` 为对照，校验目标节点族（`ASC/ASD/SXC/SXD/HXD/ALD/SLA`）的生成规则。  
3. **验证层**：持续运行 `scripts/evaluate_ugc_native_similarity.py`，把每轮结果写入 `docs/ugc_native_conversion_iteration_log_zh.md`。  
4. **体验层**：用户侧保持 `mgxc > ugc`，UGC 直转入口保留“实验性”提示。

---

## 6) 结论

当前最快路径不是继续“只看 diff 盲调”，而是：

- 用 `v8 规格`锁定输入语义，
- 用 `PenguinTools`锁定输出语义，
- 在两者之间建立可验证映射并做批量回归。
