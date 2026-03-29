# SwanSite 谱面相关 API（与 Chuni-Eventer 客户端对齐）

本文档根据 `chuni_eventer_desktop/swan_sheet_client.py` 与 `ui/swan_sheet_download_dialog.py` 中的实际调用整理，便于对照后端或自建镜像。

---

## 1. 基址

| 项目 | 值 |
|------|-----|
| 默认基址（代码常量） | `https://api.swan416.top` |
| 配置 | 当前**写死**，不在设置里修改；所有 URL 由基址 + 路径拼接（`urljoin`） |

请求头：

- 列表 JSON：`User-Agent: Chuni-Eventer/1.0`，`Accept: application/json`
- 下载二进制：`User-Agent: Chuni-Eventer/1.0`

---

## 2. 谱面列表

**请求**

```http
GET /api/contents?contentType=SHEET
```

- **方法**：仅使用 GET  
- **Query**：`contentType=SHEET`（大小写按服务端约定；注释中对应 SwanSite `CoreContentController`）

**响应（客户端期望）**

- `Content-Type` 含 `json`，或正文以 `{` / `[` 开头  
- 根节点：**JSON 数组** `[]`，每一项为一个 **对象**

**数组元素（客户端读取的字段）**

| JSON 路径（蛇形/驼峰均可） | 用途 |
|---------------------------|------|
| `id` | 内容 ID，整型；用于后续下载路径 |
| `contentType` / `content_type` | 若有值且不为 `SHEET`（忽略大小写）则跳过 |
| `title` | 网页/条目标题；表格第三列「网页标题」 |
| `sheet` | **对象**，必填；非对象则跳过整条 |
| `sheet.packageUrl` / `sheet.package_url` | 非空字符串才视为可下载；否则跳过 |
| `sheet.musicName` / `sheet.music_name` | 曲名；表格第一列 |
| `sheet.artistName` / `sheet.artist_name` | 艺术家；表格第二列 |

**客户端行为**

- 只保留：`contentType` 为空或为 `SHEET`，且 `sheet.packageUrl` 非空的条目。  
- 展示用曲名：若 `musicName` 为空则用 `title`。  
- 列表排序：先按 `music_name` 不区分大小写，再按 `content_id`。

**封装函数**

- `list_downloadable_sheets(base_url: str) -> list[SheetListEntry]`

---

## 3. 谱面包下载

**请求**

```http
GET /api/contents/{id}/download
```

- `{id}`：列表接口返回的 **`id`**（`content_id`）  
- **方法**：GET  
- **重定向**：客户端使用 `urllib`，会**跟随 302** 等到最终文件（注释说明：常跳到 `packageUrl`）

**响应**

- 成功时为**二进制流**（通常为 ZIP），写入临时文件后由 `install_zip_to_acus` 解压进 `ACUS/`。

**封装函数**

- `download_sheet_archive(base_url: str, content_id: int) -> bytes`

---

## 4. 数据类型（Python）

```text
@dataclass SheetListEntry
  content_id: int
  title: str
  music_name: str
  artist_name: str
  package_url: str
```

---

## 5. 超时

| 调用 | 默认超时 |
|------|----------|
| `_http_get_json`（列表） | 60s |
| `_http_get_bytes`（下载） | 120s |

---

## 6. 与 UI 的对应关系

| UI 操作 | API |
|---------|-----|
| 「刷新列表」 | `GET /api/contents?contentType=SHEET` |
| 「下载并解压到 ACUS」 | `GET /api/contents/{content_id}/download` → ZIP → 安装到 ACUS |
| 歌曲页「新增」弹窗内对 **「关闭」右键**（与 Swan 相同解压逻辑） | 无 HTTP；`install_zip_to_acus(zip_path, acus_root)`（见 `sheet_install.py`） |

---

## 7. 说明与限制

- 本文档**不**保证与 Swan 站后台版本永久一致；以后端 OpenAPI 或源码为准。  
- 若根 URL 误指向前端 SPA 而非 API，`_http_get_json` 会报「响应不是 JSON」类错误（部分历史提示语提到「设置里改 API」，与当前固定 `api.swan416.top` 的 UI 可能不完全一致，以代码为准）。
