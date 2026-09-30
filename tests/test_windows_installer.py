from pathlib import Path


def test_windows_installer_uses_exit_code_for_native_commands():
    installer = Path("scripts/install-windows.ps1").read_text(encoding="utf-8")

    assert "function Invoke-NativeCommand" in installer
    assert '$ErrorActionPreference = "Continue"' in installer
    assert "$LASTEXITCODE" in installer
    assert 'Join-Path $venv "Scripts\\python.exe"' in installer
    assert "Invoke-NativeCommand -FilePath $venvPython" in installer
    assert '@("-m", "pip", "install", "--upgrade", "pip")' in installer
    assert '@("-m", "pip", "install", $SourceRoot)' in installer
    assert "Scripts\\pip.exe" not in installer
    assert 'throw "$FilePath exited with code $exitCode"' in installer
