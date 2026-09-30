#!/usr/bin/env bash
set -euo pipefail

DOMAIN=""
BIND_HOST="127.0.0.1"
PORT="8765"
QUIET="0"
MANAGE_CADDY="0"
INSTALL_DIR="/opt/mcp-rdc"
ENV_DIR="/etc/mcp-rdc"

usage() {
  echo "Usage: $0 --domain mcp.example.com [--bind 127.0.0.1] [--port 8765] [--manage-caddy] [--quiet]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2 ;;
    --bind) BIND_HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --manage-caddy) MANAGE_CADDY="1"; shift ;;
    --quiet) QUIET="1"; shift ;;
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

if ! command -v python3 >/dev/null 2>&1; then
  apt-get update
  apt-get install -y python3 python3-venv
fi
install -d -m 0755 "$INSTALL_DIR" "$ENV_DIR"
rm -rf "$INSTALL_DIR/venv"

if ! python3 -m venv "$INSTALL_DIR/venv"; then
  echo "Python venv is unavailable; installing python3-venv and retrying."
  apt-get update
  apt-get install -y python3-venv
  rm -rf "$INSTALL_DIR/venv"
  python3 -m venv "$INSTALL_DIR/venv"
fi
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install "$ROOT_DIR"

ENV_FILE="$ENV_DIR/gateway.env"
PUBLIC_SLUG=""
AGENT_SLUG=""
AGENT_TOKEN=""

if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
  PUBLIC_SLUG="${MCP_RDC_PUBLIC_SLUG:-}"
  AGENT_SLUG="${MCP_RDC_AGENT_SLUG:-}"
  AGENT_TOKEN="${MCP_RDC_AGENT_TOKEN:-}"
fi

if [[ -z "$PUBLIC_SLUG" ]]; then
  PUBLIC_SLUG="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
fi
if [[ -z "$AGENT_SLUG" ]]; then
  AGENT_SLUG="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
fi
if [[ -z "$AGENT_TOKEN" ]]; then
  AGENT_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
fi

cat > "$ENV_FILE" <<EOF
MCP_RDC_BIND=$BIND_HOST
MCP_RDC_PORT=$PORT
MCP_RDC_PUBLIC_HOST=$DOMAIN
MCP_RDC_PUBLIC_SLUG=$PUBLIC_SLUG
MCP_RDC_AGENT_SLUG=$AGENT_SLUG
MCP_RDC_AGENT_TOKEN=$AGENT_TOKEN
MCP_RDC_DEFAULT_AGENT=octarin
MCP_RDC_REQUEST_TIMEOUT=120
EOF
chmod 0600 "$ENV_FILE"

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
systemctl enable mcp-rdc-gateway >/dev/null
systemctl restart mcp-rdc-gateway

healthy="0"
for _ in $(seq 1 20); do
  if systemctl is-active --quiet mcp-rdc-gateway && \
    "$INSTALL_DIR/venv/bin/python" - "$BIND_HOST" "$PORT" <<'PY' >/dev/null 2>&1
import sys
import urllib.request

host, port = sys.argv[1], sys.argv[2]
with urllib.request.urlopen(f"http://{host}:{port}/healthz", timeout=2) as response:
    if response.status != 200:
        raise SystemExit(1)
PY
  then
    healthy="1"
    break
  fi
  sleep 1
done

if [[ "$healthy" != "1" ]]; then
  echo "MCP-RDC gateway failed its health check." >&2
  journalctl -u mcp-rdc-gateway -n 80 --no-pager >&2 || true
  exit 1
fi

if [[ "$MANAGE_CADDY" == "1" ]]; then
  CADDY_WAS_PRESENT="0"
  if command -v caddy >/dev/null 2>&1; then
    CADDY_WAS_PRESENT="1"
  else
    apt-get update
    apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl gnupg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' |
      gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' |
      tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
    chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    chmod o+r /etc/apt/sources.list.d/caddy-stable.list
    apt-get update
    apt-get install -y caddy
  fi

  CADDY_FILE="/etc/caddy/Caddyfile"
  if [[ "$CADDY_WAS_PRESENT" == "1" && -s "$CADDY_FILE" ]] && \
     ! grep -q '^# Managed by MCP-RDC$' "$CADDY_FILE"; then
    echo "Refusing to overwrite existing unmanaged $CADDY_FILE" >&2
    exit 1
  fi

  cat > "$CADDY_FILE" <<EOF
{
    admin 127.0.0.1:2019
}

# Managed by MCP-RDC
$DOMAIN {
    route {
        @mcp path /$PUBLIC_SLUG/mcp /$PUBLIC_SLUG/mcp/*
        reverse_proxy @mcp $BIND_HOST:$PORT

        @agent path /$AGENT_SLUG/agent/v1/connect
        reverse_proxy @agent $BIND_HOST:$PORT

        respond /healthz "ok" 200
        respond 404
    }
}
EOF

  caddy validate --config "$CADDY_FILE" --adapter caddyfile
  systemctl enable caddy >/dev/null
  systemctl restart caddy

  if ! command -v curl >/dev/null 2>&1; then
    apt-get update
    apt-get install -y curl
  fi

  caddy_ready="0"
  for _ in $(seq 1 30); do
    if ! systemctl is-active --quiet caddy; then
      break
    fi
    if curl --fail --silent --show-error       --resolve "$DOMAIN:443:127.0.0.1"       "https://$DOMAIN/healthz" >/dev/null 2>&1; then
      caddy_ready="1"
      break
    fi
    sleep 1
  done

  if [[ "$caddy_ready" != "1" ]]; then
    echo "Caddy failed its HTTPS readiness check." >&2
    systemctl status caddy --no-pager >&2 || true
    journalctl -u caddy -n 80 --no-pager >&2 || true
    exit 1
  fi
fi

if [[ "$QUIET" == "1" ]]; then
  if [[ "$MANAGE_CADDY" == "1" ]]; then
    echo "MCP-RDC gateway and Caddy deployed successfully."
  else
    echo "MCP-RDC gateway deployed and healthy on $BIND_HOST:$PORT."
  fi
  exit 0
fi

cat <<EOF

MCP-RDC gateway is running on $BIND_HOST:$PORT.

Public ChatGPT MCP endpoint:
  https://$DOMAIN/$PUBLIC_SLUG/mcp

Public Windows agent endpoint:
  wss://$DOMAIN/$AGENT_SLUG/agent/v1/connect

Caddy:
  $([[ "$MANAGE_CADDY" == "1" ]] && echo "installed/configured automatically" || echo "configure deploy/Caddyfile.example manually")

Windows agent install values:
  Gateway WS: wss://$DOMAIN/$AGENT_SLUG/agent/v1/connect
  Agent token: $AGENT_TOKEN

Keep gateway.env private. The public slug, agent slug and agent token are credentials.
EOF
