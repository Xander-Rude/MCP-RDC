#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="/etc/mcp-rdc/gateway.env"
if [[ ! -r "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE. Deploy MCP-RDC first." >&2
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

cat <<EOF
ChatGPT MCP URL:
  https://$MCP_RDC_PUBLIC_HOST/$MCP_RDC_PUBLIC_SLUG/mcp

Windows agent install values:
  GatewayWs: wss://$MCP_RDC_PUBLIC_HOST/$MCP_RDC_AGENT_SLUG/agent/v1/connect
  AgentToken: $MCP_RDC_AGENT_TOKEN
  AgentId: $MCP_RDC_DEFAULT_AGENT
EOF
