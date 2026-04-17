#!/usr/bin/env bash
set -euo pipefail

# One-shot installer for Ubuntu (root)
# - installs Python deps
# - writes .env
# - installs systemd service
# - configures nginx reverse proxy for subdomain
# - (optional) enables HTTPS via certbot

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run as root: sudo bash scripts/install-on-ubuntu.sh"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${SERVICE_ROOT}/.venv"
ENV_FILE="${SERVICE_ROOT}/.env"

echo "== Chuni chart uploader one-click install =="

read -rp "Uploader domain (e.g. uploader.example.com): " UPLOADER_DOMAIN
read -rp "Upload API key (random long string): " UPLOAD_API_KEY
read -rp "Storage root [/data/chuni-charts]: " STORAGE_ROOT
STORAGE_ROOT="${STORAGE_ROOT:-/data/chuni-charts}"
read -rp "Max upload size MB [100]: " MAX_UPLOAD_MB
MAX_UPLOAD_MB="${MAX_UPLOAD_MB:-100}"
read -rp "Max storage size GB [20]: " MAX_STORAGE_GB
MAX_STORAGE_GB="${MAX_STORAGE_GB:-20}"
read -rp "Rate limit count per window [30]: " RATE_LIMIT_COUNT
RATE_LIMIT_COUNT="${RATE_LIMIT_COUNT:-30}"
read -rp "Rate limit window sec [60]: " RATE_LIMIT_WINDOW_SEC
RATE_LIMIT_WINDOW_SEC="${RATE_LIMIT_WINDOW_SEC:-60}"
read -rp "Enable HTTPS with certbot now? [y/N]: " ENABLE_TLS

if [[ -z "${UPLOADER_DOMAIN}" || -z "${UPLOAD_API_KEY}" ]]; then
  echo "Missing required inputs."
  exit 1
fi

apt-get update
retry_cmd() {
  local n=0
  local max_n=3
  local delay=3
  until "$@"; do
    n=$((n + 1))
    if [[ $n -ge $max_n ]]; then
      echo "Command failed after ${max_n} attempts: $*"
      return 1
    fi
    echo "Retry $n/${max_n} in ${delay}s: $*"
    sleep $delay
  done
}

# Force IPv4 in case server IPv6 route is broken.
APT_IPV4_OPTS=(
  "-o" "Acquire::ForceIPv4=true"
  "-o" "Acquire::Retries=3"
  "-o" "Acquire::http::Timeout=20"
  "-o" "Acquire::https::Timeout=20"
)

# Prefer https mirrors to avoid some 80/tcp restrictions.
if [[ -f /etc/apt/sources.list ]]; then
  sed -i 's|http://archive.ubuntu.com/ubuntu|https://archive.ubuntu.com/ubuntu|g' /etc/apt/sources.list || true
  sed -i 's|http://security.ubuntu.com/ubuntu|https://security.ubuntu.com/ubuntu|g' /etc/apt/sources.list || true
fi

retry_cmd apt-get "${APT_IPV4_OPTS[@]}" update
retry_cmd apt-get "${APT_IPV4_OPTS[@]}" install -y python3 python3-venv python3-pip nginx

python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install -r "${SERVICE_ROOT}/requirements.txt"

cat > "${ENV_FILE}" <<EOF
UPLOAD_API_KEY=${UPLOAD_API_KEY}
STORAGE_ROOT=${STORAGE_ROOT}
MAX_UPLOAD_MB=${MAX_UPLOAD_MB}
MAX_STORAGE_GB=${MAX_STORAGE_GB}
MAX_ZIP_ENTRIES=2000
MAX_UNCOMPRESSED_MB=500
RATE_LIMIT_COUNT=${RATE_LIMIT_COUNT}
RATE_LIMIT_WINDOW_SEC=${RATE_LIMIT_WINDOW_SEC}
CORS_ALLOW_ORIGINS=*
EOF
chmod 600 "${ENV_FILE}"
mkdir -p "${STORAGE_ROOT}/songs"

cat > /etc/systemd/system/chuni-chart-uploader.service <<EOF
[Unit]
Description=Chuni Chart Uploader FastAPI Service
After=network.target

[Service]
Type=simple
WorkingDirectory=${SERVICE_ROOT}
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_DIR}/bin/uvicorn app.main:app --host 127.0.0.1 --port 8081
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/nginx/sites-available/chuni-chart-uploader <<EOF
server {
    listen 80;
    server_name ${UPLOADER_DOMAIN};
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

if [[ "${ENABLE_TLS}" =~ ^[Yy]$ ]]; then
  retry_cmd apt-get "${APT_IPV4_OPTS[@]}" install -y certbot python3-certbot-nginx
  certbot --nginx -d "${UPLOADER_DOMAIN}" --non-interactive --agree-tos -m "admin@${UPLOADER_DOMAIN#*.}" --redirect || true
fi

echo
echo "Install done."
echo "- Health check: curl http://127.0.0.1:8081/health"
echo "- Public URL: http://${UPLOADER_DOMAIN}/health"
echo "- Service status: systemctl status chuni-chart-uploader --no-pager"
