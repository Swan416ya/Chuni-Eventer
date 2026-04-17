#!/usr/bin/env bash
set -euo pipefail

# Switch Ubuntu apt sources to HTTPS mirror and install python3-venv only.
# Usage: sudo bash fix-apt-and-install-venv.sh

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run as root."
  exit 1
fi

if [[ -f /etc/apt/sources.list ]]; then
  # Prefer HTTPS mirror to avoid outbound 80 blocks.
  sed -i 's|http://us.archive.ubuntu.com/ubuntu|https://mirrors.tuna.tsinghua.edu.cn/ubuntu|g' /etc/apt/sources.list || true
  sed -i 's|http://archive.ubuntu.com/ubuntu|https://mirrors.tuna.tsinghua.edu.cn/ubuntu|g' /etc/apt/sources.list || true
  sed -i 's|http://security.ubuntu.com/ubuntu|https://mirrors.tuna.tsinghua.edu.cn/ubuntu|g' /etc/apt/sources.list || true
fi

apt-get -o Acquire::ForceIPv4=true -o Acquire::Retries=5 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20 update
DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::ForceIPv4=true -o Acquire::Retries=5 install -y --no-install-recommends python3-venv

python3 -m venv /tmp/chuni_test_venv
rm -rf /tmp/chuni_test_venv
echo "python3-venv is ready."
