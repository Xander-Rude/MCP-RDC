from __future__ import annotations

import contextlib
import hmac
import os
import re
from typing import Any

import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from .broker import AgentBroker
from .config import GatewaySettings

_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def build_gateway_app(settings: GatewaySettings) -> Starlette:
    broker = AgentBroker()
    mcp = MCPServer(
        "MCP-RDC",
        instructions=(
            "Remote control for a trusted private computer. Prefer focused read-only tools. "
            "Use run_powershell only when a focused tool cannot accomplish the task. "
            "Write and execution tools change the remote machine."
        ),
    )

    def pick_agent(agent_id: str | None) -> str:
        return agent_id or settings.default_agent

    async def remote(
        method: str,
        params: dict[str, Any] | None = None,
        *,
        agent_id: str | None = None,
        timeout: float | None = None,
    ) -> Any:
        return await broker.call(
            pick_agent(agent_id),
            method,
            params,
            timeout=timeout or settings.request_timeout,
        )

    @mcp.tool(
        title="Remote agent status",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    async def agent_status() -> dict[str, Any]:
        """Show connected remote agents and their heartbeat metadata."""
        return broker.status()

    @mcp.tool(
        title="System information",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    async def system_info(agent_id: str | None = None) -> dict[str, Any]:
        """Get OS, host, memory, Python, uptime and allowed roots from a remote agent."""
        return await remote("system.info", agent_id=agent_id)

    @mcp.tool(
        title="Read text file",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    async def read_text_file(
        path: str,
        max_bytes: int = 262144,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Read a UTF-8 text file inside the agent's allowed roots."""
        return await remote(
            "fs.read_text", {"path": path, "max_bytes": max_bytes}, agent_id=agent_id
        )

    @mcp.tool(
        title="List directory",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    async def list_directory(
        path: str = "",
        limit: int = 500,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """List files and directories inside the agent's allowed roots."""
        return await remote("fs.list", {"path": path, "limit": limit}, agent_id=agent_id)

    @mcp.tool(
        title="Tail file",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    async def tail_file(
        path: str,
        lines: int = 200,
        max_bytes: int = 524288,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Read the last lines of a log or text file without loading the whole file."""
        return await remote(
            "fs.tail",
            {"path": path, "lines": lines, "max_bytes": max_bytes},
            agent_id=agent_id,
        )

    @mcp.tool(
        title="Write text file",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    async def write_text_file(
        path: str,
        content: str,
        create_parents: bool = True,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Atomically replace a text file inside the agent's allowed roots."""
        return await remote(
            "fs.write_text",
            {"path": path, "content": content, "create_parents": create_parents},
            agent_id=agent_id,
        )

    @mcp.tool(
        title="Run PowerShell",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )
    async def run_powershell(
        command: str,
        cwd: str | None = None,
        timeout_seconds: float = 120,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Run an arbitrary PowerShell command. Prefer focused tools when available."""
        return await remote(
            "shell.powershell",
            {"command": command, "cwd": cwd, "timeout_seconds": timeout_seconds},
            agent_id=agent_id,
            timeout=timeout_seconds + 10,
        )

    @mcp.tool(
        title="List processes",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    async def list_processes(
        name_contains: str = "",
        limit: int = 200,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """List remote processes, optionally filtering by executable name."""
        return await remote(
            "process.list",
            {"name_contains": name_contains, "limit": limit},
            agent_id=agent_id,
        )

    @mcp.tool(
        title="Scheduled task status",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    async def scheduled_task_status(name: str, agent_id: str | None = None) -> dict[str, Any]:
        """Get state and last/next run information for a Windows Scheduled Task."""
        return await remote("task.status", {"name": name}, agent_id=agent_id)

    @mcp.tool(
        title="Start scheduled task",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    async def start_scheduled_task(name: str, agent_id: str | None = None) -> dict[str, Any]:
        """Start a Windows Scheduled Task on the remote agent."""
        return await remote("task.start", {"name": name}, agent_id=agent_id)

    @mcp.tool(
        title="Stop scheduled task",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    async def stop_scheduled_task(name: str, agent_id: str | None = None) -> dict[str, Any]:
        """Stop a running Windows Scheduled Task on the remote agent."""
        return await remote("task.stop", {"name": name}, agent_id=agent_id)

    @mcp.tool(
        title="Git status",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    async def git_status(repo_path: str = "", agent_id: str | None = None) -> dict[str, Any]:
        """Return git branch and short working-tree status for a repository."""
        return await remote("git.status", {"repo_path": repo_path}, agent_id=agent_id)

    @mcp.tool(
        title="Git HEAD",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    async def git_head(repo_path: str = "", agent_id: str | None = None) -> dict[str, Any]:
        """Return current git commit SHA and branch for a repository."""
        return await remote("git.head", {"repo_path": repo_path}, agent_id=agent_id)

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", **broker.status()})

    async def agent_socket(websocket: WebSocket) -> None:
        auth = websocket.headers.get("authorization", "")
        expected = f"Bearer {settings.agent_token}"
        agent_id = websocket.query_params.get("agent_id", "")
        if not hmac.compare_digest(auth, expected) or not _AGENT_ID_RE.fullmatch(agent_id):
            await websocket.close(code=4401)
            return

        await websocket.accept()
        connection = await broker.register(agent_id, websocket)
        try:
            while True:
                payload = await websocket.receive_json()
                if isinstance(payload, dict):
                    await broker.handle_message(agent_id, payload)
        except WebSocketDisconnect:
            pass
        finally:
            await broker.unregister(agent_id, connection)

    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=settings.allowed_hosts,
        allowed_origins=[],
    )
    mcp_app = mcp.streamable_http_app(
        streamable_http_path=settings.mcp_path,
        stateless_http=True,
        json_response=True,
        transport_security=transport_security,
    )

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette):
        async with mcp.session_manager.run():
            yield

    return Starlette(
        routes=[
            Route("/healthz", health, methods=["GET"]),
            WebSocketRoute(settings.agent_path, agent_socket),
            Mount("/", app=mcp_app),
        ],
        lifespan=lifespan,
    )


def main() -> None:
    settings = GatewaySettings.from_env(strict=True)
    uvicorn.run(
        build_gateway_app(settings),
        host=settings.bind_host,
        port=settings.port,
        log_level=os.getenv("MCP_RDC_LOG_LEVEL", "info"),
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )


if __name__ == "__main__":
    main()
