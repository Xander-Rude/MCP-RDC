import pytest

from mcp_rdc.config import GatewaySettings


def test_gateway_dev_defaults(monkeypatch):
    for name in (
        "MCP_RDC_PUBLIC_SLUG",
        "MCP_RDC_AGENT_TOKEN",
        "MCP_RDC_PUBLIC_HOST",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = GatewaySettings.from_env(strict=False)
    assert settings.mcp_path == "/dev-personal-endpoint/mcp"
    assert settings.default_agent == "octarin"


def test_gateway_strict_rejects_short_secrets(monkeypatch):
    monkeypatch.setenv("MCP_RDC_PUBLIC_SLUG", "short")
    monkeypatch.setenv("MCP_RDC_AGENT_TOKEN", "short")
    with pytest.raises(RuntimeError):
        GatewaySettings.from_env(strict=True)
