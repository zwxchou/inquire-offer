#!/usr/bin/env bash
set -euo pipefail

# 一键发版（自动回滚）
# 用法:
#   sudo bash deploy/linux/release.sh [branch]
#
# 示例:
#   sudo bash deploy/linux/release.sh main

BRANCH="${1:-main}"
APP_DIR="/opt/sales-app/app"
SERVICE="sales-app"
HEALTH_URL="http://127.0.0.1:5173/healthz"

if [[ ! -d "${APP_DIR}/.git" ]]; then
  echo "ERROR: ${APP_DIR} is not a git repository"
  exit 1
fi

cd "${APP_DIR}"
OLD_REV="$(git rev-parse HEAD)"
echo "Current revision: ${OLD_REV}"

echo "==> Pull latest code from origin/${BRANCH}"
git fetch origin
git checkout "${BRANCH}"
git pull --ff-only origin "${BRANCH}"
NEW_REV="$(git rev-parse HEAD)"
echo "New revision: ${NEW_REV}"

echo "==> Restart service"
systemctl restart "${SERVICE}"
sleep 2

echo "==> Health check"
if curl -fsS "${HEALTH_URL}" >/dev/null; then
  echo "Release success: ${NEW_REV}"
  exit 0
fi

echo "Health check failed, rollback to ${OLD_REV}"
git reset --hard "${OLD_REV}"
systemctl restart "${SERVICE}"
sleep 2

if curl -fsS "${HEALTH_URL}" >/dev/null; then
  echo "Rollback success: ${OLD_REV}"
  exit 1
fi

echo "Rollback failed, manual intervention required"
exit 2

