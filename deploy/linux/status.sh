#!/usr/bin/env bash
set -euo pipefail

echo "=== systemd ==="
systemctl status sales-app --no-pager -l || true

echo
echo "=== healthz ==="
curl -fsS http://127.0.0.1:5173/healthz || true
echo

echo "=== nginx ==="
systemctl status nginx --no-pager -l || true

