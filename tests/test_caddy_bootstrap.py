from pathlib import Path


def test_vps_installer_adds_official_caddy_repository():
    installer = Path("scripts/install-vps.sh").read_text(encoding="utf-8")

    assert "https://dl.cloudsmith.io/public/caddy/stable/gpg.key" in installer
    assert "https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt" in installer
    assert "/usr/share/keyrings/caddy-stable-archive-keyring.gpg" in installer
    assert "/etc/apt/sources.list.d/caddy-stable.list" in installer
    assert "apt-get install -y caddy" in installer


def test_vps_installer_pins_caddy_admin_and_waits_for_https():
    installer = Path("scripts/install-vps.sh").read_text(encoding="utf-8")

    assert "admin 127.0.0.1:2019" in installer
    assert 'respond /healthz "ok" 200' in installer
    assert "curl --fail --silent --show-error" in installer
    assert '--resolve "$DOMAIN:443:127.0.0.1"' in installer
    assert "Caddy failed its HTTPS readiness check." in installer


def test_caddy_route_preserves_proxy_before_fallback_404():
    installer = Path("scripts/install-vps.sh").read_text(encoding="utf-8")

    route_pos = installer.index("    route {")
    mcp_proxy_pos = installer.index("reverse_proxy @mcp", route_pos)
    agent_proxy_pos = installer.index("reverse_proxy @agent", route_pos)
    fallback_pos = installer.index("respond 404", route_pos)

    assert route_pos < mcp_proxy_pos < agent_proxy_pos < fallback_pos
