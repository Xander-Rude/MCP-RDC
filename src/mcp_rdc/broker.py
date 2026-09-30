from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol


class WebSocketLike(Protocol):
    async def send_json(self, data: Any) -> None: ...
    async def close(self, code: int = 1000) -> None: ...


class AgentOfflineError(RuntimeError):
    pass


class RemoteAgentError(RuntimeError):
    pass


@dataclass
class AgentConnection:
    websocket: WebSocketLike
    connected_at: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentBroker:
    def __init__(self) -> None:
        self._agents: dict[str, AgentConnection] = {}
        self._pending: dict[str, tuple[str, asyncio.Future[Any]]] = {}

    async def register(self, agent_id: str, websocket: WebSocketLike) -> AgentConnection:
        old = self._agents.get(agent_id)
        connection = AgentConnection(websocket=websocket)
        self._agents[agent_id] = connection
        if old is not None:
            self._fail_pending_for(agent_id, AgentOfflineError("agent reconnected"))
            with contextlib.suppress(Exception):
                await old.websocket.close(code=4000)
        return connection

    async def unregister(self, agent_id: str, connection: AgentConnection) -> None:
        if self._agents.get(agent_id) is not connection:
            return
        self._agents.pop(agent_id, None)
        self._fail_pending_for(agent_id, AgentOfflineError("agent disconnected"))

    def _fail_pending_for(self, agent_id: str, exc: Exception) -> None:
        for request_id, (pending_agent, future) in list(self._pending.items()):
            if pending_agent == agent_id and not future.done():
                future.set_exception(exc)
                self._pending.pop(request_id, None)

    async def handle_message(self, agent_id: str, payload: dict[str, Any]) -> None:
        connection = self._agents.get(agent_id)
        if connection is None:
            return
        connection.last_seen = time.monotonic()
        kind = payload.get("type")
        if kind == "hello":
            metadata = payload.get("metadata")
            if isinstance(metadata, dict):
                connection.metadata = metadata
            return
        if kind == "heartbeat":
            return
        if kind != "response":
            return

        request_id = str(payload.get("id", ""))
        item = self._pending.get(request_id)
        if item is None:
            return
        pending_agent, future = item
        if pending_agent != agent_id or future.done():
            return
        self._pending.pop(request_id, None)

        if payload.get("ok") is True:
            future.set_result(payload.get("result"))
        else:
            error = payload.get("error")
            if isinstance(error, dict):
                message = str(error.get("message", "remote agent error"))
            else:
                message = str(error or "remote agent error")
            future.set_exception(RemoteAgentError(message))

    async def call(
        self,
        agent_id: str,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 120,
    ) -> Any:
        connection = self._agents.get(agent_id)
        if connection is None:
            raise AgentOfflineError(f"agent {agent_id!r} is offline")

        request_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = (agent_id, future)
        message = {
            "type": "request",
            "id": request_id,
            "method": method,
            "params": params or {},
        }

        try:
            async with connection.send_lock:
                await connection.websocket.send_json(message)
            return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
        except TimeoutError as exc:
            if not future.done():
                future.cancel()
            raise TimeoutError(f"agent {agent_id!r} timed out while executing {method!r}") from exc
        finally:
            self._pending.pop(request_id, None)

    def status(self) -> dict[str, Any]:
        now = time.monotonic()
        agents: dict[str, Any] = {}
        for agent_id, connection in self._agents.items():
            agents[agent_id] = {
                "connected": True,
                "connected_for_seconds": round(now - connection.connected_at, 1),
                "last_seen_seconds_ago": round(now - connection.last_seen, 1),
                "metadata": connection.metadata,
            }
        return {"agents": agents, "pending_requests": len(self._pending)}
