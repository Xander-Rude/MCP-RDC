from pathlib import Path


def test_vps_installer_adds_official_caddy_repository():
    installer = Path("scripts/install-vps.sh").read_text(encoding="utf-8")

    assert "https://dl.cloudsmith.io/public/caddy/stable/gpg.key" in installer
    assert "https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt" in installer
    assert "/usr/share/keyrings/caddy-stable-archive-keyring.gpg" in installer
    assert "/etc/apt/sources.list.d/caddy-stable.list" in installer
    assert "apt-get install -y caddy" in installer
