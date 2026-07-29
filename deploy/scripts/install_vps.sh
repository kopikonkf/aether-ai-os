#!/usr/bin/env bash
set -euo pipefail
if [[ ${EUID:-$(id -u)} -ne 0 ]]; then echo "Run as root" >&2; exit 2; fi
RELEASE_DIR=${1:-$(pwd)}
id -u aether >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/aether --shell /usr/sbin/nologin aether
install -d -o aether -g aether /opt/aether /var/lib/aether /etc/aether
python3 -m venv /opt/aether/.venv
/opt/aether/.venv/bin/pip install --upgrade pip
/opt/aether/.venv/bin/pip install \
  "$RELEASE_DIR/dist/aether_core-0.19.2-py3-none-any.whl" \
  "$RELEASE_DIR/dist/aether_tools-0.3.0-py3-none-any.whl" \
  "$RELEASE_DIR/dist/aether_gateway-0.19.2-py3-none-any.whl"
install -m 0644 "$RELEASE_DIR/deploy/systemd/aether-gateway.service" /etc/systemd/system/
install -m 0644 "$RELEASE_DIR/deploy/systemd/aether-sense-worker.service" /etc/systemd/system/
if [[ ! -f /etc/aether/aether.env ]]; then
  install -m 0600 -o root -g aether "$RELEASE_DIR/aether-core/.env.example" /etc/aether/aether.env
  echo "Edit /etc/aether/aether.env before starting services." >&2
fi
systemctl daemon-reload
systemctl enable aether-gateway.service
printf '%s\n' "Installed. Configure /etc/aether/aether.env, Caddy, and optional AionUi before systemctl start aether-gateway."
