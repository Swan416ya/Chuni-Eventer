# Chart Uploader Service (FastAPI)

给 `Chuni-Eventer` 用的“本地存储上传服务”。  
桌面端上传到你的服务器，文件直接落到服务器磁盘并供其他用户下载。

## 1) 一键部署（Ubuntu，最少输入）

前提：你已把本目录上传到服务器。

```bash
cd /path/to/chart_uploader_service
sudo bash scripts/install-on-ubuntu.sh
```

脚本会自动：

- 安装 Python/Nginx
- 创建虚拟环境并安装依赖
- 根据你输入写 `.env`
- 写入 `systemd` 服务 `chuni-chart-uploader`
- 写入 Nginx 站点（子域名反代到 `127.0.0.1:8081`）
- 可选自动申请 HTTPS 证书

输入项只有这些：

- 上传子域名（如 `uploader.example.com`）
- `UPLOAD_API_KEY`（你自己定义一个长随机串）
- `STORAGE_ROOT`（默认 `/data/chuni-charts`）
- 最大上传体积（默认 100MB）

### Windows 一键推送 + 远程安装（推荐）

在你的 Windows PowerShell 里执行：

```powershell
cd "E:\Python Project\Chuni-Eventer\backend\chart_uploader_service\scripts"
.\deploy-from-windows.ps1 -ServerIp YOUR_SERVER_IP -ServerUser root
```

脚本会自动：

- 上传当前服务目录到服务器 `/opt/chuni-chart-uploader`
- 在远端执行 `install-on-ubuntu.sh`
- 输出可直接填入桌面端设置的上传地址与密钥

## 2) 桌面端要填什么

在 `Chuni-Eventer` 设置里新增了“后端代传服务（推荐）”：

- `上传服务地址`：`https://uploader.example.com`
- `上传服务密钥`：你脚本里输入的 `UPLOAD_API_KEY`

填完后，乐曲卡右键“上传到 GitHub 社区谱面…”会优先走后端代传。

## 3) 接口说明（后端）

- `GET /health`
- `GET /songs`：返回歌单
- `GET /download/{song_id}/{filename}`：下载文件（白名单：`package.zip` / `meta.json`）
- `POST /upload`
  - Header: `X-Upload-Key: <UPLOAD_API_KEY>`
  - Form:
    - `music_id` int
    - `song_name` string
    - `package_zip` file(.zip, 必填)
    - `uploader_name` optional

上传目标：

- `${STORAGE_ROOT}/songs/<song_slug>/package.zip`
- `${STORAGE_ROOT}/songs/<song_slug>/meta.json`

`package.zip` 由客户端打包：同一首歌的 `music/`、`cueFile/`、（可能的）`stage/`、`event/` 子目录会一起打进一个包。  
`meta.json` 会记录 `songName`、`artistName`、`charterName`、`musicId` 等信息，供客户端列表展示。

## 4) 上传保护机制

- API Key 校验（`X-Upload-Key`）
- 单文件大小限制（`MAX_UPLOAD_MB`）
- 单包解压后体积限制（`MAX_UNCOMPRESSED_MB`）
- 单包条目数量限制（`MAX_ZIP_ENTRIES`）
- 服务器总存储限额（`MAX_STORAGE_GB`）
- 按客户端 IP 的上传限流（`RATE_LIMIT_COUNT` / `RATE_LIMIT_WINDOW_SEC`）
- ZIP 路径穿越检测、顶层目录白名单校验

## 5) 常用运维命令

```bash
systemctl status chuni-chart-uploader --no-pager
journalctl -u chuni-chart-uploader -n 120 --no-pager
nginx -t
systemctl reload nginx
curl -sS http://127.0.0.1:8081/health
curl -sS http://127.0.0.1:8081/songs
```

## 6) 管理员删除服务器谱面（手动）

当前版本未提供删除 API。管理员可直接在服务器删除目录。

存储根目录：

- `${STORAGE_ROOT}/songs/`

### 5.1 查看现有谱面目录

```bash
ssh root@YOUR_SERVER_IP
ls -lah /data/chuni-charts/songs
```

> 如果你的 `STORAGE_ROOT` 不是 `/data/chuni-charts`，请替换为实际路径。

### 5.2 删除指定谱面目录

```bash
rm -rf "/data/chuni-charts/songs/SONG_ID_DIR"
```

例如：

```bash
rm -rf "/data/chuni-charts/songs/ver-se_x_6000"
```

### 5.3 验证删除结果

```bash
curl -sS https://uploader.example.com/songs
```

## 7) 重新部署（代码更新后）

```bash
cd /path/to/chart_uploader_service
source .venv/bin/activate
pip install -r requirements.txt
systemctl restart chuni-chart-uploader
```

## 8) 目录

- `app/main.py`：FastAPI 主程序
- `.env.example`：环境变量模板
- `scripts/install-on-ubuntu.sh`：一键安装脚本

## 9) 环境变量

- `UPLOAD_API_KEY`
- `STORAGE_ROOT=/data/chuni-charts`
- `MAX_UPLOAD_MB=100`
- `MAX_STORAGE_GB=20`
- `MAX_ZIP_ENTRIES=2000`
- `MAX_UNCOMPRESSED_MB=500`
- `RATE_LIMIT_COUNT=30`
- `RATE_LIMIT_WINDOW_SEC=60`
- `CORS_ALLOW_ORIGINS=*`
