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

## 迭代 7：0x0A 连续起点自动收束

### Ver seX（迭代 7）

- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `1.88%`
- similarity(edit-op): `50.92%`
- sha256(out/ref): `9ed9a8ecb41264afe8c23e63a3b2924f9ee97bf4cea5ecf82f0297be21c86079` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 105: ref='ASC\t1\t0\t0\t4\tTAP\t5.0\t11\t2\t4\t5.0\tDEF' out='SLC\t1\t0\t12\t4\t11\t10\t4\tSLD'`
- top_tag_deltas: `ALD:-1361, SLA:-237, SLC:-125, SLD:-110, ASD:-79, HXD:+52, CHR:+47, HLD:+24, SXC:-22, SXD:-22`

### Divide et impera（迭代 7）

- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.51%`
- similarity(edit-op): `37.48%`
- sha256(out/ref): `5069d9b79673de30864422ebf1f22498cefcd152b5ee08d16a9165832590aa77` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 22: ref='SXC\t2\t48\t0\t3\t168\t0\t16\tSLD\tUP' out='CHR\t2\t48\t0\t3\tUP'`
- top_tag_deltas: `SLA:+1256, ALD:-682, SLC:-388, SLD:-148, SXC:-59, ASD:-54, CHR:+46, ASC:-37, HLD:+30, SXD:-8`

## 迭代 8：优化同拍排序与0x0A自动收束条件

### Ver seX（迭代 8：优化同拍排序与0x0A自动收束条件）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `1.91%`
- similarity(edit-op): `52.34%`
- sha256(out/ref): `8c196dd28d4ed0a0d02df242c1d4d7c9a528691e844f32e971fc7c6af81f88f0` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 106: ref='ASC\t1\t11\t2\t4\tASC\t5.0\t28\t5\t4\t5.0\tDEF' out='SLC\t1\t0\t12\t4\t11\t10\t4\tSLD'`
- top_tag_deltas: `ALD:-1521, SLA:-347, SLC:-125, SLD:-110, ASD:-79, HXD:+52, CHR:+47, HLD:+24, SXC:-22, SXD:-22`


### Divide et impera!（迭代 8：优化同拍排序与0x0A自动收束条件）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.51%`
- similarity(edit-op): `44.10%`
- sha256(out/ref): `dd44b08daac0ec7fb809648e3008c0ef3431fc33e4e4d61e39c7f8791f3d3411` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 22: ref='SXC\t2\t48\t0\t3\t168\t0\t16\tSLD\tUP' out='CHR\t2\t48\t0\t3\tUP'`
- top_tag_deltas: `ALD:-723, SLC:-388, SLD:-148, SXC:-59, ASD:-54, CHR:+46, ASC:-37, HLD:+30, SLA:+15, SXD:-8`

## 迭代 9：C按interval分流为0x09/0x0A

### Ver seX（迭代 9：C按interval分流为0x09/0x0A）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `1.91%`
- similarity(edit-op): `52.31%`
- sha256(out/ref): `48b0228a6a615778239c2e04fde5ca8009d4343af8b368a0ad045cfe04fe43fe` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 106: ref='ASC\t1\t11\t2\t4\tASC\t5.0\t28\t5\t4\t5.0\tDEF' out='SLC\t1\t0\t12\t4\t11\t10\t4\tSLD'`
- top_tag_deltas: `ALD:-1955, ASC:+416, SLA:-348, SLC:-125, SLD:-110, ASD:-79, HXD:+52, CHR:+47, HLD:+24, SXC:-22`


### Divide et impera!（迭代 9：C按interval分流为0x09/0x0A）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.51%`
- similarity(edit-op): `43.96%`
- sha256(out/ref): `44936ced51825bdaa476980adbaba0eec241b2b9ad595f7ca99eb741a723dc7e` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 22: ref='SXC\t2\t48\t0\t3\t168\t0\t16\tSLD\tUP' out='CHR\t2\t48\t0\t3\tUP'`
- top_tag_deltas: `ALD:-1007, SLC:-388, ASC:+227, SLD:-148, SXC:-59, ASD:-54, CHR:+46, HLD:+30, SLA:+14, SXD:-8`

## 迭代 10：仅，interval=0保持0x0A

### Ver seX（迭代 10：仅，interval=0保持0x0A）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `1.91%`
- similarity(edit-op): `52.30%`
- sha256(out/ref): `f4d6c0c53e01025ec1d7b5c5a2005829c2c4b8f33485a09308010648d831f457` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 106: ref='ASC\t1\t11\t2\t4\tASC\t5.0\t28\t5\t4\t5.0\tDEF' out='SLC\t1\t0\t12\t4\t11\t10\t4\tSLD'`
- top_tag_deltas: `ALD:-1572, SLA:-347, SLC:-125, SLD:-110, ASD:-79, HXD:+52, CHR:+47, ASC:+33, HLD:+24, SXC:-22`


### Divide et impera!（迭代 10：仅，interval=0保持0x0A）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.51%`
- similarity(edit-op): `44.13%`
- sha256(out/ref): `437a68e8d2d0888118d598bbaef74a3131073d7d8dc64b7220f33f1be69f6a7d` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 22: ref='SXC\t2\t48\t0\t3\t168\t0\t16\tSLD\tUP' out='CHR\t2\t48\t0\t3\tUP'`
- top_tag_deltas: `ALD:-788, SLC:-388, SLD:-148, SXC:-59, ASD:-54, CHR:+46, HLD:+30, ASC:+19, SLA:+15, SXD:-8`

## 迭代 11：同拍优先输出SXC/ASC

### Ver seX（迭代 11：同拍优先输出SXC/ASC）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `1.88%`
- similarity(edit-op): `52.28%`
- sha256(out/ref): `f14868c5e8ba155bce3fbdfd6eb101fefc9b763804b6eecdef5fa07c322f4eda` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 104: ref='TAP\t1\t0\t0\t4' out='ASC\t1\t0\t0\t4\tTAP\t5.0\t11\t2\t4\t5.0\tDEF'`
- top_tag_deltas: `ALD:-1572, SLA:-347, SLC:-125, SLD:-110, ASD:-79, HXD:+52, CHR:+47, ASC:+33, HLD:+24, SXC:-22`


### Divide et impera!（迭代 11：同拍优先输出SXC/ASC）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.51%`
- similarity(edit-op): `44.07%`
- sha256(out/ref): `e09cabb8e4570b8e5724082e5eaecb80d77c16df05528e87e6f9600e676d872c` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 22: ref='SXC\t2\t48\t0\t3\t168\t0\t16\tSLD\tUP' out='CHR\t2\t48\t0\t3\tUP'`
- top_tag_deltas: `ALD:-788, SLC:-388, SLD:-148, SXC:-59, ASD:-54, CHR:+46, HLD:+30, ASC:+19, SLA:+15, SXD:-8`

## 迭代 12：细化0x09分支并回调同拍顺序

### Ver seX（迭代 12：细化0x09分支并回调同拍顺序）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `1.90%`
- similarity(edit-op): `51.91%`
- sha256(out/ref): `d15b052010f0bd678abb49a3fe6b9aeef1ee4acbfec7d5cd890e69e0abf313b9` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 105: ref='ASC\t1\t0\t0\t4\tTAP\t5.0\t11\t2\t4\t5.0\tDEF' out='SXC\t1\t0\t0\t4\t11\t2\t4\tSLD\tUP'`
- top_tag_deltas: `ALD:-1572, SLA:-347, SLC:-125, SLD:-110, ASD:-79, SXC:+56, HXD:+52, CHR:+47, ASC:-45, HLD:+24`


### Divide et impera!（迭代 12：细化0x09分支并回调同拍顺序）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.51%`
- similarity(edit-op): `40.69%`
- sha256(out/ref): `13607e5454d2cb1900142c446d99e6abb0cd749a624b744e19d288981eacba8b` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 22: ref='SXC\t2\t48\t0\t3\t168\t0\t16\tSLD\tUP' out='CHR\t2\t48\t0\t3\tUP'`
- top_tag_deltas: `ALD:-788, SLC:-388, ASC:-246, SXC:+206, SLD:-148, ASD:-54, CHR:+46, HLD:+30, SLA:+15, SXD:-8`

## 迭代 13：修复0x0A重叠链配对

### Ver seX（迭代 13：修复0x0A重叠链配对）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `1.90%`
- similarity(edit-op): `45.88%`
- sha256(out/ref): `f50a281777eb2fda7cd093e686eaa7212c6a72103eadce48011314095fd9fc24` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 105: ref='ASC\t1\t0\t0\t4\tTAP\t5.0\t11\t2\t4\t5.0\tDEF' out='SXC\t1\t0\t0\t4\t11\t2\t4\tSLD\tUP'`
- top_tag_deltas: `SLA:-347, SLC:-125, SLD:-110, ASD:-79, ALD:-65, SXC:+56, HXD:+52, CHR:+47, ASC:-45, HLD:+24`


### Divide et impera!（迭代 13：修复0x0A重叠链配对）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.33%`
- similarity(edit-op): `26.37%`
- sha256(out/ref): `d013ba7a6c8081871706c2825e1e13701f37f8dab281c8fb35d3b294d932d624` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 22: ref='SXC\t2\t48\t0\t3\t168\t0\t16\tSLD\tUP' out='CHR\t2\t48\t0\t3\tUP'`
- top_tag_deltas: `SLA:+3290, SLC:-388, ASC:-246, SXC:+206, ALD:-171, SLD:-148, ASD:-54, CHR:+46, HLD:+30, SXD:-8`

## 迭代 14：收紧0x0A链配对窗口

### Ver seX（迭代 14：收紧0x0A链配对窗口）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `1.90%`
- similarity(edit-op): `45.82%`
- sha256(out/ref): `31dafa0b330e9eb8fde47488edf7a3d88f9e7350ecf28d72bb8a28c403bc0c07` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 105: ref='ASC\t1\t0\t0\t4\tTAP\t5.0\t11\t2\t4\t5.0\tDEF' out='SXC\t1\t0\t0\t4\t11\t2\t4\tSLD\tUP'`
- top_tag_deltas: `SLA:-347, SLC:-125, SLD:-110, ALD:-94, ASD:-79, SXC:+56, HXD:+52, CHR:+47, ASC:-45, HLD:+24`


### Divide et impera!（迭代 14：收紧0x0A链配对窗口）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.53%`
- similarity(edit-op): `37.79%`
- sha256(out/ref): `026fe30c726149cfc97aa72bc89021b782ee678f6ce6cf3a8768c0af0312aebe` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 22: ref='SXC\t2\t48\t0\t3\t168\t0\t16\tSLD\tUP' out='CHR\t2\t48\t0\t3\tUP'`
- top_tag_deltas: `SLC:-388, ASC:-246, ALD:-212, SXC:+206, SLD:-148, ASD:-54, CHR:+46, HLD:+30, SXD:-8, SLA:+7`

## 迭代 15：0x0A改为最近早于当前点匹配

### Ver seX（迭代 15：0x0A改为最近早于当前点匹配）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `1.90%`
- similarity(edit-op): `44.99%`
- sha256(out/ref): `3a975b705b0b04d041c84f6078c90e085cc1336aee78466e3c2feb6b1a1625a4` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 105: ref='ASC\t1\t0\t0\t4\tTAP\t5.0\t11\t2\t4\t5.0\tDEF' out='SXC\t1\t0\t0\t4\t11\t2\t4\tSLD\tUP'`
- top_tag_deltas: `SLA:-346, SLC:-125, SLD:-110, ASD:-79, ALD:-65, SXC:+56, HXD:+52, CHR:+47, ASC:-45, HLD:+24`


### Divide et impera!（迭代 15：0x0A改为最近早于当前点匹配）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.69%`
- similarity(edit-op): `37.53%`
- sha256(out/ref): `998d79f936d27e95bb397f938f18d8b8cadbe84e125bb67e3e49715c5e2a21ef` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 22: ref='SXC\t2\t48\t0\t3\t168\t0\t16\tSLD\tUP' out='CHR\t2\t48\t0\t3\tUP'`
- top_tag_deltas: `SLC:-388, ASC:-246, SXC:+206, ALD:-171, SLD:-148, ASD:-54, CHR:+46, HLD:+30, SLA:+16, SXD:-8`

## 迭代 16：0x09仅曲线续接时输出SXC

### Ver seX（迭代 16：0x09仅曲线续接时输出SXC）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `1.91%`
- similarity(edit-op): `51.93%`
- sha256(out/ref): `2dc3503768a5d7bb200ea3fa699a2bcd49ff8fcfcd293373a3947ad92d03df3f` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 106: ref='ASC\t1\t11\t2\t4\tASC\t5.0\t28\t5\t4\t5.0\tDEF' out='SLC\t1\t0\t12\t4\t11\t10\t4\tSLD'`
- top_tag_deltas: `ALD:-1572, SLA:-347, SLC:-125, SLD:-110, ASD:-79, HXD:+52, CHR:+47, HLD:+24, SXD:-22, SXC:+8`


### Divide et impera!（迭代 16：0x09仅曲线续接时输出SXC）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.51%`
- similarity(edit-op): `40.86%`
- sha256(out/ref): `fc15658fe75f0f00d3202663cce001b00d853f43f38d5e20ca786d8c227b46ff` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 22: ref='SXC\t2\t48\t0\t3\t168\t0\t16\tSLD\tUP' out='CHR\t2\t48\t0\t3\tUP'`
- top_tag_deltas: `ALD:-788, SLC:-388, ASC:-194, SXC:+154, SLD:-148, ASD:-54, CHR:+46, HLD:+30, SLA:+15, SXD:-8`

## 迭代 17：保留缩放塌缩的短ALD段

### Ver seX（迭代 17：保留缩放塌缩的短ALD段）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `1.91%`
- similarity(edit-op): `51.93%`
- sha256(out/ref): `2dc3503768a5d7bb200ea3fa699a2bcd49ff8fcfcd293373a3947ad92d03df3f` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 106: ref='ASC\t1\t11\t2\t4\tASC\t5.0\t28\t5\t4\t5.0\tDEF' out='SLC\t1\t0\t12\t4\t11\t10\t4\tSLD'`
- top_tag_deltas: `ALD:-1572, SLA:-347, SLC:-125, SLD:-110, ASD:-79, HXD:+52, CHR:+47, HLD:+24, SXD:-22, SXC:+8`


### Divide et impera!（迭代 17：保留缩放塌缩的短ALD段）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.51%`
- similarity(edit-op): `40.86%`
- sha256(out/ref): `fc15658fe75f0f00d3202663cce001b00d853f43f38d5e20ca786d8c227b46ff` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 22: ref='SXC\t2\t48\t0\t3\t168\t0\t16\tSLD\tUP' out='CHR\t2\t48\t0\t3\tUP'`
- top_tag_deltas: `ALD:-788, SLC:-388, ASC:-194, SXC:+154, SLD:-148, ASD:-54, CHR:+46, HLD:+30, SLA:+15, SXD:-8`

## 迭代 18：为C链引入timeline级链路配对

### Ver seX（迭代 18：为C链引入timeline级链路配对）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `1.91%`
- similarity(edit-op): `45.90%`
- sha256(out/ref): `ae08a6d86d2675a4d8218c274027d91b1c0ea00039a6ca68878340ebbdda062f` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 106: ref='ASC\t1\t11\t2\t4\tASC\t5.0\t28\t5\t4\t5.0\tDEF' out='SLC\t1\t0\t12\t4\t11\t10\t4\tSLD'`
- top_tag_deltas: `SLA:-347, SLC:-125, SLD:-110, ASD:-79, ALD:-65, HXD:+52, CHR:+47, HLD:+24, SXD:-22, SXC:+8`


### Divide et impera!（迭代 18：为C链引入timeline级链路配对）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.74%`
- similarity(edit-op): `37.69%`
- sha256(out/ref): `d166dec11f7cb15efbfb33ddd188055aa987bb9804679669888d1461bd5778b0` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 22: ref='SXC\t2\t48\t0\t3\t168\t0\t16\tSLD\tUP' out='CHR\t2\t48\t0\t3\tUP'`
- top_tag_deltas: `SLC:-388, ASC:-194, ALD:-171, SXC:+154, SLD:-148, ASD:-54, CHR:+46, HLD:+30, SLA:+15, SXD:-8`

## 迭代 19：回退C链timeline实验保持0x09续接规则

### Ver seX（迭代 19：回退C链timeline实验保持0x09续接规则）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `1.91%`
- similarity(edit-op): `51.93%`
- sha256(out/ref): `2dc3503768a5d7bb200ea3fa699a2bcd49ff8fcfcd293373a3947ad92d03df3f` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 106: ref='ASC\t1\t11\t2\t4\tASC\t5.0\t28\t5\t4\t5.0\tDEF' out='SLC\t1\t0\t12\t4\t11\t10\t4\tSLD'`
- top_tag_deltas: `ALD:-1572, SLA:-347, SLC:-125, SLD:-110, ASD:-79, HXD:+52, CHR:+47, HLD:+24, SXD:-22, SXC:+8`


### Divide et impera!（迭代 19：回退C链timeline实验保持0x09续接规则）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.51%`
- similarity(edit-op): `40.86%`
- sha256(out/ref): `fc15658fe75f0f00d3202663cce001b00d853f43f38d5e20ca786d8c227b46ff` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 22: ref='SXC\t2\t48\t0\t3\t168\t0\t16\tSLD\tUP' out='CHR\t2\t48\t0\t3\tUP'`
- top_tag_deltas: `ALD:-788, SLC:-388, ASC:-194, SXC:+154, SLD:-148, ASD:-54, CHR:+46, HLD:+30, SLA:+15, SXD:-8`

## 迭代 20：C链chain_id配对避免跨链串接

### Ver seX（迭代 20：C链chain_id配对避免跨链串接）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `1.91%`
- similarity(edit-op): `45.90%`
- sha256(out/ref): `ae08a6d86d2675a4d8218c274027d91b1c0ea00039a6ca68878340ebbdda062f` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 106: ref='ASC\t1\t11\t2\t4\tASC\t5.0\t28\t5\t4\t5.0\tDEF' out='SLC\t1\t0\t12\t4\t11\t10\t4\tSLD'`
- top_tag_deltas: `SLA:-347, SLC:-125, SLD:-110, ASD:-79, ALD:-65, HXD:+52, CHR:+47, HLD:+24, SXD:-22, SXC:+8`


### Divide et impera!（迭代 20：C链chain_id配对避免跨链串接）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.74%`
- similarity(edit-op): `37.69%`
- sha256(out/ref): `d166dec11f7cb15efbfb33ddd188055aa987bb9804679669888d1461bd5778b0` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 22: ref='SXC\t2\t48\t0\t3\t168\t0\t16\tSLD\tUP' out='CHR\t2\t48\t0\t3\tUP'`
- top_tag_deltas: `SLC:-388, ASC:-194, ALD:-171, SXC:+154, SLD:-148, ASD:-54, CHR:+46, HLD:+30, SLA:+15, SXD:-8`

## 迭代 21：修正c型末节点闭合标记(0x06)

### Ver seX（迭代 21：修正c型末节点闭合标记(0x06)）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `1.91%`
- similarity(edit-op): `45.85%`
- sha256(out/ref): `cb8918f6ea1a0808933ece5a28bb5ad7794e6ca2347885d856c41d28832661fb` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 106: ref='ASC\t1\t11\t2\t4\tASC\t5.0\t28\t5\t4\t5.0\tDEF' out='SLC\t1\t0\t12\t4\t11\t10\t4\tSLD'`
- top_tag_deltas: `SLA:-347, SLC:-125, SLD:-110, ASD:-79, ALD:-65, HXD:+52, CHR:+47, ASC:-40, SXD:+39, HLD:+24`


### Divide et impera!（迭代 21：修正c型末节点闭合标记(0x06)）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.74%`
- similarity(edit-op): `37.65%`
- sha256(out/ref): `a4f362ae61b3a50252691b07a1ce380891529f8b50ff9dc077d823297f58da9b` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 22: ref='SXC\t2\t48\t0\t3\t168\t0\t16\tSLD\tUP' out='CHR\t2\t48\t0\t3\tUP'`
- top_tag_deltas: `SLC:-388, ASC:-197, ALD:-171, SXC:+149, SLD:-148, ASD:-54, CHR:+46, HLD:+30, SLA:+15, SXD:+7`

## 迭代 22：0x09按来源链区分ASC与SXC

### Ver seX（迭代 22：0x09按来源链区分ASC与SXC）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `1.91%`
- similarity(edit-op): `46.17%`
- sha256(out/ref): `5e57cf6884af0b3bba81dfba8021be222bb06d8a1581f823eeae33e9c28eb2bd` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 106: ref='ASC\t1\t11\t2\t4\tASC\t5.0\t28\t5\t4\t5.0\tDEF' out='SLC\t1\t0\t12\t4\t11\t10\t4\tSLD'`
- top_tag_deltas: `SLA:-347, SLC:-125, SLD:-110, ASD:-79, ALD:-65, HXD:+52, CHR:+47, SXD:+39, HLD:+24, SXC:-22`


### Divide et impera!（迭代 22：0x09按来源链区分ASC与SXC）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.85%`
- similarity(edit-op): `40.67%`
- sha256(out/ref): `ff7fb6aab1854a8cb4c9b17509e029738595b6490a55cb88dc9f7cab6c3a5257` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 22: ref='SXC\t2\t48\t0\t3\t168\t0\t16\tSLD\tUP' out='CHR\t2\t48\t0\t3\tUP'`
- top_tag_deltas: `SLC:-388, ALD:-171, SLD:-148, ASD:-52, CHR:+46, ASC:-43, HLD:+30, SLA:+15, SXC:-5, SXD:+5`

## 迭代 23：回退链路实验并用ex_attr区分C$ trace

### Ver seX（迭代 23：回退链路实验并用ex_attr区分C$ trace）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `1.91%`
- similarity(edit-op): `52.30%`
- sha256(out/ref): `dc0ec4f1fb1ac5ce37f30ffdc740b9bd5bce01c8411ebb9d81c48c0672f31ae6` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 106: ref='ASC\t1\t11\t2\t4\tASC\t5.0\t28\t5\t4\t5.0\tDEF' out='SLC\t1\t0\t12\t4\t11\t10\t4\tSLD'`
- top_tag_deltas: `ALD:-1572, SLA:-347, SLC:-125, SLD:-110, ASD:-79, HXD:+52, CHR:+47, ASC:+25, HLD:+24, SXD:-22`


### Divide et impera!（迭代 23：回退链路实验并用ex_attr区分C$ trace）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.51%`
- similarity(edit-op): `44.13%`
- sha256(out/ref): `3692d7385a3d1d93d0bcfa6455f88c9525f5f096244e71d5549c0e3e411882f1` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 22: ref='SXC\t2\t48\t0\t3\t168\t0\t16\tSLD\tUP' out='CHR\t2\t48\t0\t3\tUP'`
- top_tag_deltas: `ALD:-788, SLC:-388, SLD:-148, ASD:-54, CHR:+46, ASC:-38, HLD:+30, SLA:+15, SXD:-8, HXD:-4`

## 迭代 24：0x0A按chain_id逐链配对发射ALD

### Ver seX（迭代 24：0x0A按chain_id逐链配对发射ALD）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `1.91%`
- similarity(edit-op): `46.21%`
- sha256(out/ref): `61637bfc9954521614505c1235a4afc2cdbe34c85b8f4f9d13f2f53d7a53e548` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 106: ref='ASC\t1\t11\t2\t4\tASC\t5.0\t28\t5\t4\t5.0\tDEF' out='SLC\t1\t0\t12\t4\t11\t10\t4\tSLD'`
- top_tag_deltas: `SLA:-347, SLC:-125, SLD:-110, ASD:-79, ALD:-65, HXD:+52, CHR:+47, ASC:+25, HLD:+24, SXD:-22`


### Divide et impera!（迭代 24：0x0A按chain_id逐链配对发射ALD）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.74%`
- similarity(edit-op): `40.70%`
- sha256(out/ref): `e6affa6a4c0dba4bc418f9e061b1c7880fbbcb61ceb7edfaaa770f53d55bafed` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 22: ref='SXC\t2\t48\t0\t3\t168\t0\t16\tSLD\tUP' out='CHR\t2\t48\t0\t3\tUP'`
- top_tag_deltas: `SLC:-388, ALD:-171, SLD:-148, ASD:-54, CHR:+46, ASC:-38, HLD:+30, SLA:+15, SXD:-8, HXD:-4`

## 迭代 25：同tick按宽度优先排序再按类型

### Ver seX（迭代 25：同tick按宽度优先排序再按类型）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `1.86%`
- similarity(edit-op): `44.78%`
- sha256(out/ref): `af35f07a95b395dd1c90f0c93360ce665b88aeabdb0ba7a202d6dc58edfdc482` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 106: ref='ASC\t1\t11\t2\t4\tASC\t5.0\t28\t5\t4\t5.0\tDEF' out='SLC\t1\t0\t12\t4\t11\t10\t4\tSLD'`
- top_tag_deltas: `SLA:-347, SLC:-125, SLD:-110, ASD:-79, ALD:-65, HXD:+52, CHR:+47, ASC:+25, HLD:+24, SXD:-22`


### Divide et impera!（迭代 25：同tick按宽度优先排序再按类型）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.55%`
- similarity(edit-op): `40.35%`
- sha256(out/ref): `76d074617f185b0e3df3eec382678233be9d2c05927d1f9071200807d9b2947f` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 18: ref='CHR\t2\t0\t0\t3\tUP' out='TAP\t2\t0\t3\t5'`
- top_tag_deltas: `SLC:-388, ALD:-171, SLD:-148, ASD:-54, CHR:+46, ASC:-38, HLD:+30, SLA:+15, SXD:-8, HXD:-4`

## 迭代 26：回退排序与逐链ALD实验恢复基线

### Ver seX（迭代 26：回退排序与逐链ALD实验恢复基线）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `1.91%`
- similarity(edit-op): `52.30%`
- sha256(out/ref): `dc0ec4f1fb1ac5ce37f30ffdc740b9bd5bce01c8411ebb9d81c48c0672f31ae6` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 106: ref='ASC\t1\t11\t2\t4\tASC\t5.0\t28\t5\t4\t5.0\tDEF' out='SLC\t1\t0\t12\t4\t11\t10\t4\tSLD'`
- top_tag_deltas: `ALD:-1572, SLA:-347, SLC:-125, SLD:-110, ASD:-79, HXD:+52, CHR:+47, ASC:+25, HLD:+24, SXD:-22`


### Divide et impera!（迭代 26：回退排序与逐链ALD实验恢复基线）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.51%`
- similarity(edit-op): `44.13%`
- sha256(out/ref): `3692d7385a3d1d93d0bcfa6455f88c9525f5f096244e71d5549c0e3e411882f1` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 22: ref='SXC\t2\t48\t0\t3\t168\t0\t16\tSLD\tUP' out='CHR\t2\t48\t0\t3\tUP'`
- top_tag_deltas: `ALD:-788, SLC:-388, SLD:-148, ASD:-54, CHR:+46, ASC:-38, HLD:+30, SLA:+15, SXD:-8, HXD:-4`

## 迭代 27：slide链遇新起点时隐式闭链

### Ver seX（迭代 27：slide链遇新起点时隐式闭链）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `1.91%`
- similarity(edit-op): `52.29%`
- sha256(out/ref): `46b753443a14224521d573a10de1cf12937ee2020607df509d49f5804df0e91d` / `e5f27afad36507c70f8dcd92be8488c5a71aa2a3b15c0279201308bb9f8c3ca1`
- first_diff: `line 106: ref='ASC\t1\t11\t2\t4\tASC\t5.0\t28\t5\t4\t5.0\tDEF' out='SLC\t1\t0\t12\t4\t11\t10\t4\tSLD'`
- top_tag_deltas: `ALD:-1572, SLA:-347, SLC:-121, SLD:-104, ASD:-79, HXD:+52, CHR:+47, ASC:+25, HLD:+24, SXD:-22`


### Divide et impera!（迭代 27：slide链遇新起点时隐式闭链）
- backend: `python`
- same_bytes: `False`
- similarity(seq-pos): `0.60%`
- similarity(edit-op): `44.46%`
- sha256(out/ref): `34e6db8c310c414d81446b259f49d2b404c111d430d246285ab7e57a64cd9a57` / `ed7fdbdc526a88ebf8c81671356d842a18884b4e07f23cb985b548cfb0fa83c8`
- first_diff: `line 22: ref='SXC\t2\t48\t0\t3\t168\t0\t16\tSLD\tUP' out='CHR\t2\t48\t0\t3\tUP'`
- top_tag_deltas: `ALD:-788, SLC:-305, SLD:-141, ASD:-54, CHR:+46, ASC:-38, HLD:+30, SLA:+15, SXD:-8, HXD:-4`
