#!/usr/bin/env bash
set -euo pipefail

DOMAIN=""
WG_IF="wg0"
PORT="8765"
INSTALL_DIR="/opt/mcp-rdc"
ENV_DIR="/etc/mcp-rdc"

usage() {
  echo "Usage: $0 --domain mcp.example.com [--wg-interface wg0] [--port 8765]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2 ;;
    --wg-interface) WG_IF="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1"; usage; exit 2 ;;
  esac
done

if [[ -z "$DOMAIN" ]]; then
  echo "--domain is required"
  exit 2
fi
if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root."
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WG_IP="$(ip -4 -o addr show dev "$WG_IF" | awk '{print $4}' | cut -d/ -f1 | head -n1)"
if [[ -z "$WG_IP" ]]; then
  echo "No IPv4 address found on WireGuard interface $WG_IF"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  apt-get update
  apt-get install -y python3 python3-venv
fi
if ! python3 -m venv --help >/dev/null 2>&1; then
  apt-get update
  apt-get install -y python3-venv
fi

install -d -m 0755 "$INSTALL_DIR" "$ENV_DIR"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install "$ROOT_DIR"

ENV_FILE="$ENV_DIR/gateway.env"
if [[ ! -f "$ENV_FILE" ]]; then
  AGENT_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  PUBLIC_SLUG="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  cat > "$ENV_FILE" <<EOF
MCP_RDC_BIND=$WG_IP
MCP_RDC_PORT=$PORT
MCP_RDC_PUBLIC_HOST=$DOMAIN
MCP_RDC_PUBLIC_SLUG=$PUBLIC_SLUG
MCP_RDC_AGENT_TOKEN=$AGENT_TOKEN
MCP_RDC_DEFAULT_AGENT=octarin
MCP_RDC_REQUEST_TIMEOUT=120
EOF
  chmod 0600 "$ENV_FILE"
fi

cat > /etc/systemd/system/mcp-rdc-gateway.service <<EOF
[Unit]
Description=MCP-RDC Gateway
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=$ENV_FILE
ExecStart=$INSTALL_DIR/venv/bin/mcp-rdc-gateway
Restart=always
RestartSec=2
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
WorkingDirectory=$INSTALL_DIR

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now mcp-rdc-gateway

set -a
source "$ENV_FILE"
set +a

cat <<EOF

MCP-RDC gateway is running on WireGuard address $WG_IP:$PORT.

Public ChatGPT MCP endpoint:
  https://$DOMAIN/$MCP_RDC_PUBLIC_SLUG/mcp

Add this Caddy site (or equivalent reverse-proxy rule):
-------------------------------------------------------
$DOMAIN {
    @mcp path /$MCP_RDC_PUBLIC_SLUG/mcp /$MCP_RDC_PUBLIC_SLUG/mcp/*
    reverse_proxy @mcp $WG_IP:$PORT
    respond 404
}
-------------------------------------------------------

Windows agent install values:
  Gateway WS: ws://$WG_IP:$PORT/agent/v1/connect
  Agent token: $MCP_RDC_AGENT_TOKEN

Keep gateway.env private. The public slug and agent token are credentials.
EOF
