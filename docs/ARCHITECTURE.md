# Architecture

MCP-RDC is split into two processes.

~~~text
ChatGPT / Codex
      |
      | HTTPS, MCP Streamable HTTP
      v
public reverse proxy on VPS :443
      |
      v
MCP-RDC Gateway on 127.0.0.1:8765
      ^
      | WSS + bearer token
      |
MCP-RDC Agent on Windows (octarin)
      |
      +-- filesystem, allowlisted roots
      +-- PowerShell
      +-- processes
      +-- Scheduled Tasks
      +-- git
~~~

## Why this shape

- No SSH or WinRM dependency on Windows.
- No inbound Internet port on the Windows machine.
- The Windows agent only creates an outbound TLS WebSocket connection.
- The agent reconnects automatically after network loss or reboot.
- The gateway binds to localhost and is reachable externally only through the TLS reverse proxy.
- The agent route has its own high-entropy path and separate bearer token.
- The deployment does not depend on how WireGuard, Docker or the host network are configured.

## Trust boundaries

The Windows agent is privileged by design. run_powershell can change the machine
outside filesystem allowlists, so both external routes must be treated as credentials.

The private deployment uses three secrets:

1. MCP_RDC_PUBLIC_SLUG: high-entropy path in the public MCP URL.
2. MCP_RDC_AGENT_SLUG: independent high-entropy path for the agent WebSocket.
3. MCP_RDC_AGENT_TOKEN: authenticates the Windows agent to the VPS gateway.

The agent token is never returned by MCP tools and is redacted from command/process output.

The public agent route is intentionally reachable through TLS so deployment is independent of
VPN topology. Authentication still requires both the secret path and bearer token.

For a multi-user or publicly distributed deployment, add standards-compliant OAuth 2.1.
The gateway boundary is isolated so OAuth can be added without changing the Windows agent
protocol.

## Agent RPC

Gateway to agent:

~~~json
{"type":"request","id":"...","method":"fs.tail","params":{"path":"logs/app.log","lines":200}}
~~~

Agent response:

~~~json
{"type":"response","id":"...","ok":true,"result":{"text":"..."}}
~~~

Supported method groups in v0.1:

- system.*
- fs.*
- shell.*
- process.*
- task.*
- git.*

The protocol is deliberately small and transport-agnostic.
