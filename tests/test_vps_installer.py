from pathlib import Path


def test_vps_installer_retries_after_real_venv_failure():
    installer = Path("scripts/install-vps.sh").read_text(encoding="utf-8")

    assert 'if ! python3 -m venv "$INSTALL_DIR/venv"; then' in installer
    assert "apt-get install -y python3-venv" in installer
    assert 'rm -rf "$INSTALL_DIR/venv"' in installer
    assert "python3 -m venv --help" not in installer
