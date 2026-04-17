#!/usr/bin/env bash
set -euo pipefail

SERVICE_ROOT="/opt/chuni-chart-uploader"
DOMAIN="${1:-uploader.example.com}"
UPLOAD_API_KEY="${2:-change-me}"
STORAGE_ROOT="${3:-/data/chuni-charts}"
MAX_UPLOAD_MB="${4:-100}"
MAX_STORAGE_GB="${5:-20}"

cd "${SERVICE_ROOT}"
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

cat > .env <<EOF
UPLOAD_API_KEY=${UPLOAD_API_KEY}
STORAGE_ROOT=${STORAGE_ROOT}
MAX_UPLOAD_MB=${MAX_UPLOAD_MB}
MAX_STORAGE_GB=${MAX_STORAGE_GB}
MAX_ZIP_ENTRIES=2000
MAX_UNCOMPRESSED_MB=500
RATE_LIMIT_COUNT=30
RATE_LIMIT_WINDOW_SEC=60
CORS_ALLOW_ORIGINS=*
EOF
chmod 600 .env
mkdir -p "${STORAGE_ROOT}/songs"

cat > /etc/systemd/system/chuni-chart-uploader.service <<EOF
[Unit]
Description=Chuni Chart Uploader FastAPI Service
After=network.target

[Service]
Type=simple
WorkingDirectory=${SERVICE_ROOT}
EnvironmentFile=${SERVICE_ROOT}/.env
ExecStart=${SERVICE_ROOT}/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8081
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/nginx/sites-available/chuni-chart-uploader <<EOF
server {
    listen 80;
    server_name ${DOMAIN};
    client_max_body_size ${MAX_UPLOAD_MB}m;

    location / {
        proxy_pass http://127.0.0.1:8081;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

ln -sf /etc/nginx/sites-available/chuni-chart-uploader /etc/nginx/sites-enabled/chuni-chart-uploader
nginx -t
systemctl daemon-reload
systemctl enable --now chuni-chart-uploader
systemctl reload nginx

systemctl status chuni-chart-uploader --no-pager
curl -sS -m 10 http://127.0.0.1:8081/health
