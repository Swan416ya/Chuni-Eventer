# UGC 原生转 c2s 迭代日志

目标：在**不依赖 MGXC 回退**的前提下，实现 `UGC -> c2s`，并尽量与参考 `c2s` 等价。

评估方式：

- 样本：`Ver seX` 与 `Divide et impera!`
- 每轮都执行 `scripts/evaluate_ugc_native_similarity.py`
- 记录指标：
  - `same_bytes`
  - `similarity(seq-pos)`：同下标行一致率
  - `similarity(edit-op)`：基于 `difflib.SequenceMatcher` 的编辑相似度
  - `top_tag_deltas`：输出与参考在各 c2s 标签计数差异
  - `first_diff`：首个差异位置

## 迭代 1：修正 BarTick 跨小节与空中方向映射

### Ver seX（迭代 1）

- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.25%`
- similarity(edit-op): `40.53%`
- sha256(out/ref): `2fd81a8c3fff9c908a581497c0c899bd6464c627c3a4afef3f8948535d5c3e94` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 14: ref='' out='BPM\t0\t0\t205.000'`
- top_tag_deltas: `SLA:-349, SLC:-125, SLD:-110, ASD:-79, HXD:+52, CHR:+47, ALD:-30, HLD:+24, SXC:-22, SXD:-22`

### Divide et impera（迭代 1）

- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.42%`
- similarity(edit-op): `40.43%`
- sha256(out/ref): `b865c8270f04b63435af8679025cfb1f29a37e41529b226bd0f13529ea36a5a9` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 14: ref='' out='BPM\t0\t0\t166.000'`
- top_tag_deltas: `ALD:-653, SLC:-388, SLD:-148, SXC:-59, ASD:-54, CHR:+46, ASC:-37, HLD:+30, SXD:-8, HXD:-4`

## 迭代 2：修正 C 链子节点 long_attr 映射

### Ver seX（迭代 2）

- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.25%`
- similarity(edit-op): `46.70%`
- sha256(out/ref): `55cbc961276a9a780998c2bd9e8d19033b1c733940df1c39a9960822ab67d7d7` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 14: ref='' out='BPM\t0\t0\t205.000'`
- top_tag_deltas: `ALD:-1521, SLA:-349, SLC:-125, SLD:-110, ASD:-79, HXD:+52, CHR:+47, HLD:+24, SXC:-22, SXD:-22`

### Divide et impera（迭代 2）

- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.35%`
- similarity(edit-op): `40.82%`
- sha256(out/ref): `cd3e8fdedabe0c873306518b6f3e7ec07c5eda5707c453d3264cb3adb371d17b` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 14: ref='' out='BPM\t0\t0\t166.000'`
- top_tag_deltas: `ALD:-724, SLC:-388, SLD:-148, SXC:-59, ASD:-54, CHR:+46, ASC:-37, HLD:+30, SXD:-8, HXD:-4`

## 迭代 3：补 C 颜色/间隔并生成 SLA

### Ver seX（迭代 3）

- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `2.13%`
- similarity(edit-op): `46.71%`
- sha256(out/ref): `d7ddc58727ab21b4533c8ea002fde7c78953461c4d00fce06ddf935ca1b5a132` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 127: ref='TAP\t1\t336\t2\t3' out='TAP\t1\t336\t11\t5'`
- top_tag_deltas: `ALD:-1521, SLA:-347, SLC:-125, SLD:-110, ASD:-79, HXD:+52, CHR:+47, HLD:+24, SXC:-22, SXD:-22`

### Divide et impera（迭代 3）

- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.42%`
- similarity(edit-op): `40.76%`
- sha256(out/ref): `be414d672fb51bdc28e9ec9712004530edd62e9596fae22d015c2d25b2aa3541` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 18: ref='CHR\t2\t0\t0\t3\tUP' out='CHR\t2\t0\t13\t3\tUP'`
- top_tag_deltas: `ALD:-724, SLC:-388, SLD:-148, SXC:-59, ASD:-54, CHR:+46, ASC:-37, HLD:+30, SLA:+15, SXD:-8`

## 迭代 4：修正下方向 ADL/ADR 映射

### Ver seX（迭代 4）

- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `2.13%`
- similarity(edit-op): `46.61%`
- sha256(out/ref): `f87903ab459c15f64d919b734baefc9013c117e66b46007832431ef027090e35` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 127: ref='TAP\t1\t336\t2\t3' out='TAP\t1\t336\t11\t5'`
- top_tag_deltas: `ALD:-1521, SLA:-347, SLC:-125, SLD:-110, ASD:-79, HXD:+52, CHR:+47, HLD:+24, SXC:-22, SXD:-22`

### Divide et impera（迭代 4）

- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.42%`
- similarity(edit-op): `40.27%`
- sha256(out/ref): `cea8283edcb01b3645f3c727bc8f0ad8b896138965177baefc8635172a06a958` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 18: ref='CHR\t2\t0\t0\t3\tUP' out='CHR\t2\t0\t13\t3\tUP'`
- top_tag_deltas: `ALD:-724, SLC:-388, SLD:-148, SXC:-59, ASD:-54, CHR:+46, ASC:-37, HLD:+30, SLA:+15, SXD:-8`

## 迭代 5：统一同拍音符排序规则

### Ver seX（迭代 5）

- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `1.88%`
- similarity(edit-op): `52.32%`
- sha256(out/ref): `529f6b800720337db8df2655b278ca3163bce143e153406c8a1e4ec69a8f2127` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 105: ref='ASC\t1\t0\t0\t4\tTAP\t5.0\t11\t2\t4\t5.0\tDEF' out='SLC\t1\t0\t12\t4\t11\t10\t4\tSLD'`
- top_tag_deltas: `ALD:-1521, SLA:-347, SLC:-125, SLD:-110, ASD:-79, HXD:+52, CHR:+47, HLD:+24, SXC:-22, SXD:-22`

### Divide et impera（迭代 5）

- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.51%`
- similarity(edit-op): `44.11%`
- sha256(out/ref): `b52b2d73774cfca034afc256743900802d7594b90487555bfe8169322a816992` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 22: ref='SXC\t2\t48\t0\t3\t168\t0\t16\tSLD\tUP' out='CHR\t2\t48\t0\t3\tUP'`
- top_tag_deltas: `ALD:-724, SLC:-388, SLD:-148, SXC:-59, ASD:-54, CHR:+46, ASC:-37, HLD:+30, SLA:+15, SXD:-8`

## 迭代 6：补 ALD 颜色映射

### Ver seX（迭代 6）

- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `1.88%`
- similarity(edit-op): `52.32%`
- sha256(out/ref): `6f68655d76c32a7b6c02f51b23b3c669a6c3fc93303a667b328ad17c63cec6c5` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 105: ref='ASC\t1\t0\t0\t4\tTAP\t5.0\t11\t2\t4\t5.0\tDEF' out='SLC\t1\t0\t12\t4\t11\t10\t4\tSLD'`
- top_tag_deltas: `ALD:-1521, SLA:-347, SLC:-125, SLD:-110, ASD:-79, HXD:+52, CHR:+47, HLD:+24, SXC:-22, SXD:-22`

### Divide et impera（迭代 6）

- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.51%`
- similarity(edit-op): `44.11%`
- sha256(out/ref): `e531dfbd8fe5eb6f6e284dd5f2c50134b71df955aaf45739f02ec1ced2ab4e15` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 22: ref='SXC\t2\t48\t0\t3\t168\t0\t16\tSLD\tUP' out='CHR\t2\t48\t0\t3\tUP'`
- top_tag_deltas: `ALD:-724, SLC:-388, SLD:-148, SXC:-59, ASD:-54, CHR:+46, ASC:-37, HLD:+30, SLA:+15, SXD:-8`
