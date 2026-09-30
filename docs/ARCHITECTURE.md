# Architecture

MCP-RDC is split into two processes.

~~~text
ChatGPT / Codex
      |
      | HTTPS, MCP Streamable HTTP
      v
public reverse proxy on VPS :443
      |
      | only /<secret>/mcp
      v
MCP-RDC Gateway on VPS WireGuard IP :8765
      ^
      | WebSocket over WireGuard
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
- The agent reconnects automatically after network loss or reboot.
- The gateway is the only MCP endpoint ChatGPT needs to know.
- WireGuard carries the gateway-to-agent control channel.
- The public reverse proxy never exposes the agent WebSocket path.
- A high-entropy MCP path is generated for a private single-user deployment.

## Trust boundaries

The Windows agent is privileged by design. run_powershell can change the machine
outside filesystem allowlists, so the public MCP endpoint must be treated as a credential.

The initial private deployment uses two secrets:

1. MCP_RDC_PUBLIC_SLUG: high-entropy path in the public MCP URL.
2. MCP_RDC_AGENT_TOKEN: authenticates the Windows agent to the VPS gateway.

The agent token is never returned by MCP tools and is redacted from command/process output.

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
