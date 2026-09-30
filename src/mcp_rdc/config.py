from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _required(name: str, *, strict: bool, fallback: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    if strict:
        raise RuntimeError(f"{name} is required")
    return fallback


@dataclass(frozen=True)
class GatewaySettings:
    bind_host: str
    port: int
    public_host: str
    public_slug: str
    agent_token: str
    default_agent: str
    request_timeout: float

    @property
    def mcp_path(self) -> str:
        return f"/{self.public_slug}/mcp"

    @property
    def allowed_hosts(self) -> list[str]:
        return [
            self.public_host,
            f"{self.public_host}:*",
            self.bind_host,
            f"{self.bind_host}:*",
            "127.0.0.1",
            "127.0.0.1:*",
            "localhost",
            "localhost:*",
        ]

    @classmethod
    def from_env(cls, *, strict: bool = True) -> GatewaySettings:
        public_host = os.getenv("MCP_RDC_PUBLIC_HOST", "localhost").strip() or "localhost"
        public_slug = _required(
            "MCP_RDC_PUBLIC_SLUG", strict=strict, fallback="dev-personal-endpoint"
        )
        agent_token = _required("MCP_RDC_AGENT_TOKEN", strict=strict, fallback="dev-agent-token")
        if strict and len(public_slug) < 20:
            raise RuntimeError("MCP_RDC_PUBLIC_SLUG must be at least 20 characters")
        if strict and len(agent_token) < 32:
            raise RuntimeError("MCP_RDC_AGENT_TOKEN must be at least 32 characters")
        return cls(
            bind_host=os.getenv("MCP_RDC_BIND", "127.0.0.1"),
            port=int(os.getenv("MCP_RDC_PORT", "8765")),
            public_host=public_host,
            public_slug=public_slug,
            agent_token=agent_token,
            default_agent=os.getenv("MCP_RDC_DEFAULT_AGENT", "octarin"),
            request_timeout=float(os.getenv("MCP_RDC_REQUEST_TIMEOUT", "120")),
        )


@dataclass(frozen=True)
class AgentSettings:
    gateway_ws: str
    agent_token: str
    agent_id: str
    allowed_roots: tuple[Path, ...]
    max_output_bytes: int
    command_timeout: float
    reconnect_max_seconds: float

    @classmethod
    def from_env(cls, *, strict: bool = True) -> AgentSettings:
        gateway_ws = _required(
            "MCP_RDC_GATEWAY_WS",
            strict=strict,
            fallback="ws://127.0.0.1:8765/agent/v1/connect",
        )
        agent_token = _required("MCP_RDC_AGENT_TOKEN", strict=strict, fallback="dev-agent-token")
        raw_roots = os.getenv("MCP_RDC_ALLOWED_ROOTS", r"C:\hh-agent")
        roots = tuple(
            Path(item.strip()).expanduser() for item in raw_roots.split(os.pathsep) if item.strip()
        )
        if not roots:
            raise RuntimeError("MCP_RDC_ALLOWED_ROOTS must contain at least one path")
        if strict and len(agent_token) < 32:
            raise RuntimeError("MCP_RDC_AGENT_TOKEN must be at least 32 characters")
        return cls(
            gateway_ws=gateway_ws,
            agent_token=agent_token,
            agent_id=os.getenv("MCP_RDC_AGENT_ID", "octarin"),
            allowed_roots=roots,
            max_output_bytes=int(os.getenv("MCP_RDC_MAX_OUTPUT_BYTES", "1000000")),
            command_timeout=float(os.getenv("MCP_RDC_COMMAND_TIMEOUT", "120")),
            reconnect_max_seconds=float(os.getenv("MCP_RDC_RECONNECT_MAX_SECONDS", "30")),
        )
