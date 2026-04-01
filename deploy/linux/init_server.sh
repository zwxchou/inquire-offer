#!/usr/bin/env bash
set -euo pipefail

# 用法:
#   sudo bash deploy/linux/init_server.sh <git_repo_url> [branch]
#
# 示例:
#   sudo bash deploy/linux/init_server.sh https://github.com/your-org/sales.git main

REPO_URL="${1:-}"
BRANCH="${2:-main}"

if [[ -z "${REPO_URL}" ]]; then
  echo "ERROR: missing repo url"
  echo "Usage: sudo bash deploy/linux/init_server.sh <git_repo_url> [branch]"
  exit 1
fi

APP_USER="salesapp"
APP_GROUP="salesapp"
APP_ROOT="/opt/sales-app"
APP_DIR="${APP_ROOT}/app"
SERVICE_NAME="sales-app"

echo "==> Install runtime packages"
dnf install -y python3 python3-pip git nginx curl rsync

echo "==> Create app user/group if not exists"
if ! id -u "${APP_USER}" >/dev/null 2>&1; then
  useradd --system --home "${APP_ROOT}" --shell /sbin/nologin "${APP_USER}"
fi

mkdir -p "${APP_ROOT}"
chown -R "${APP_USER}:${APP_GROUP}" "${APP_ROOT}"

echo "==> Clone or update repository"
if [[ ! -d "${APP_DIR}/.git" ]]; then
  sudo -u "${APP_USER}" git clone -b "${BRANCH}" "${REPO_URL}" "${APP_DIR}"
else
  sudo -u "${APP_USER}" bash -lc "cd '${APP_DIR}' && git fetch origin && git checkout '${BRANCH}' && git pull --ff-only origin '${BRANCH}'"
fi

echo "==> Prepare writable directories"
mkdir -p "${APP_DIR}/backups/daily" "${APP_DIR}/backups/latest" "${APP_DIR}/customer_cards"
chown -R "${APP_USER}:${APP_GROUP}" "${APP_DIR}"

echo "==> Install systemd service"
install -m 0644 "${APP_DIR}/deploy/linux/sales-app.service" "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}"

echo "==> Install nginx reverse proxy"
install -m 0644 "${APP_DIR}/deploy/linux/nginx-sales.conf" /etc/nginx/conf.d/sales.conf
nginx -t
systemctl enable --now nginx
systemctl restart nginx

echo "==> Open firewall port 80 (if firewalld is running)"
if systemctl is-active --quiet firewalld; then
  firewall-cmd --permanent --add-service=http || true
  firewall-cmd --reload || true
fi

echo "==> Health check"
sleep 1
curl -fsS http://127.0.0.1:5173/healthz || true

echo ""
echo "Deployment finished."
echo "Open: http://47.112.197.85/index.html"
echo "Service status: systemctl status ${SERVICE_NAME} --no-pager"

