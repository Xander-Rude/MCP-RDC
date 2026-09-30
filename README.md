# MCP-RDC

Self-hosted remote computer control for ChatGPT and Codex over MCP.

The design is deliberately simple:

~~~text
ChatGPT -> HTTPS / MCP -> Linux VPS -> WireGuard -> Windows agent -> C:\hh-agent
~~~

No SSH server on Windows. No WinRM. No public Windows ports. The Windows agent keeps
an outbound WebSocket connection to the VPS over the existing WireGuard network.

## What v0.1 contains

- Official MCP Python SDK v2 and Streamable HTTP
- Persistent Windows agent with reconnect
- Allowlisted filesystem access
- Read, write, list and tail files
- PowerShell execution
- Process listing
- Windows Scheduled Task status/start/stop
- Git HEAD and working-tree status
- Agent health and metadata
- MCP tool annotations for read/write/destructive behavior
- Output limits and agent-token redaction
- systemd installer for the Linux gateway
- Scheduled Task installer for the Windows agent
- Linux and Windows CI

## Network layout

The gateway binds to the VPS WireGuard IP, not the public interface.

A reverse proxy such as Caddy exposes only:

~~~text
https://mcp.example.com/<high-entropy-secret>/mcp
~~~

The Windows agent connects directly over WireGuard:

~~~text
ws://<VPS-WG-IP>:8765/agent/v1/connect
~~~

The public reverse proxy must not proxy /agent/v1/connect.

See docs/ARCHITECTURE.md.

## Quick deployment

### 1. VPS

Clone this repository on the VPS and run:

~~~bash
sudo ./scripts/install-vps.sh --domain mcp.example.com --wg-interface wg0
~~~

The installer discovers the VPS WireGuard address, creates a virtual environment,
installs MCP-RDC, generates both secrets, installs the systemd unit, starts it, and
prints the exact public MCP URL plus Windows agent values.

It intentionally does not rewrite an existing reverse-proxy config behind your back.

### 2. Reverse proxy

Add the Caddy block printed by the installer and reload Caddy.

A template is in deploy/Caddyfile.example.

### 3. Windows / octarin

From elevated PowerShell in a local clone:

~~~powershell
.\scripts\install-windows.ps1 -GatewayWs "ws://10.0.0.1:8765/agent/v1/connect" -AgentToken "<token>" -AgentId "octarin" -AllowedRoots "C:\hh-agent"
~~~

The installer creates C:\ProgramData\MCP-RDC, protects the agent configuration,
and registers MCP-RDC Agent as a SYSTEM Scheduled Task that starts at boot and
restarts on failure.

### 4. ChatGPT

Enable developer mode and add the MCP URL printed by the VPS installer:

~~~text
https://mcp.example.com/<secret>/mcp
~~~

For this private single-user deployment the high-entropy endpoint is the access
credential. Do not publish it. OAuth 2.1 is the next hardening layer if this becomes
multi-user or public.

## Security model

Filesystem tools are constrained to configured roots.

run_powershell is intentionally privileged and can escape those filesystem
boundaries. It is therefore marked destructive and non-idempotent in MCP metadata.

The control plane has:

- TLS on the public reverse proxy
- a high-entropy unguessable MCP path
- WireGuard between VPS and Windows
- a separate high-entropy agent bearer token
- no public agent route
- no listening service on Windows public or LAN interfaces

## Development

~~~bash
python -m venv .venv
pip install -e ".[dev]"
ruff check .
ruff format --check .
pytest
~~~

## License

MIT
