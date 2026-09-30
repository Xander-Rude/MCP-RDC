from pathlib import Path

import pytest

from mcp_rdc.agent import AgentRuntime
from mcp_rdc.config import AgentSettings


def make_runtime(root: Path) -> AgentRuntime:
    return AgentRuntime(
        AgentSettings(
            gateway_ws="ws://127.0.0.1:8765/agent/v1/connect",
            agent_token="x" * 48,
            agent_id="test",
            allowed_roots=(root,),
            max_output_bytes=1024,
            command_timeout=1,
            reconnect_max_seconds=1,
        )
    )


def test_relative_path_stays_in_root(tmp_path):
    runtime = make_runtime(tmp_path)
    assert runtime.resolve_path("logs/app.log") == (tmp_path / "logs/app.log").resolve()


def test_absolute_path_in_root_is_allowed(tmp_path):
    runtime = make_runtime(tmp_path)
    target = tmp_path / "file.txt"
    assert runtime.resolve_path(str(target)) == target.resolve()


def test_parent_escape_is_rejected(tmp_path):
    runtime = make_runtime(tmp_path)
    with pytest.raises(PermissionError):
        runtime.resolve_path("../outside.txt")
