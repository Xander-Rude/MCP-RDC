from mcp_rdc.config import GatewaySettings
from mcp_rdc.gateway import build_gateway_app


def test_gateway_app_constructs():
    settings = GatewaySettings(
        bind_host="127.0.0.1",
        port=8765,
        public_host="localhost",
        public_slug="x" * 32,
        agent_token="y" * 48,
        default_agent="octarin",
        request_timeout=1,
    )

    app = build_gateway_app(settings)

    assert app is not None
    assert app.routes
