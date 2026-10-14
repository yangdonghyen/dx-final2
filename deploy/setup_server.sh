#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu 22.04/24.04 server (Naver Cloud).
# Usage: sudo bash setup_server.sh   (run from a clone at /opt/travelmate)
set -euo pipefail
APP=/opt/travelmate
apt-get update
apt-get install -y nginx git curl
# Python 3.14 (the project's version) through uv, without touching the system Python.
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
cd "$APP/backend"
uv python install 3.14
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements.txt
test -f .env || { echo "Copy backend/.env to $APP/backend/.env first (secrets are not in git)."; exit 1; }
install -m 644 "$APP/deploy/travelmate.service" /etc/systemd/system/travelmate.service
install -m 644 "$APP/deploy/nginx-travelmate.conf" /etc/nginx/sites-available/travelmate
ln -sf /etc/nginx/sites-available/travelmate /etc/nginx/sites-enabled/travelmate
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
systemctl daemon-reload && systemctl enable --now travelmate
sleep 3 && curl -fsS http://127.0.0.1:8000/docs >/dev/null && echo "backend is up"
