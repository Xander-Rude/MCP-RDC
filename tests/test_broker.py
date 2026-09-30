import asyncio

import pytest

from mcp_rdc.broker import AgentBroker, AgentOfflineError, RemoteAgentError


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.closed = []

    async def send_json(self, data):
        self.sent.append(data)

    async def close(self, code=1000):
        self.closed.append(code)


@pytest.mark.asyncio
async def test_round_trip():
    broker = AgentBroker()
    socket = FakeSocket()
    await broker.register("octarin", socket)

    call = asyncio.create_task(broker.call("octarin", "system.info", timeout=1))
    await asyncio.sleep(0)
    request = socket.sent[0]
    await broker.handle_message(
        "octarin",
        {"type": "response", "id": request["id"], "ok": True, "result": {"ok": 1}},
    )

    assert await call == {"ok": 1}


@pytest.mark.asyncio
async def test_remote_error():
    broker = AgentBroker()
    socket = FakeSocket()
    await broker.register("octarin", socket)

    call = asyncio.create_task(broker.call("octarin", "bad", timeout=1))
    await asyncio.sleep(0)
    request = socket.sent[0]
    await broker.handle_message(
        "octarin",
        {
            "type": "response",
            "id": request["id"],
            "ok": False,
            "error": {"message": "boom"},
        },
    )

    with pytest.raises(RemoteAgentError, match="boom"):
        await call


@pytest.mark.asyncio
async def test_offline_agent():
    broker = AgentBroker()
    with pytest.raises(AgentOfflineError):
        await broker.call("missing", "system.info", timeout=0.01)
