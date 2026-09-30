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


def test_windows_installer_uses_language_neutral_sids():
    installer = Path("scripts/install-windows.ps1").read_text(encoding="utf-8")

    assert 'SecurityIdentifier("S-1-5-32-544")' in installer
    assert 'SecurityIdentifier("S-1-5-18")' in installer
    assert '-UserId "S-1-5-18"' in installer
    assert 'NTAccount("BUILTIN", "Administrators")' not in installer
    assert 'NTAccount("NT AUTHORITY", "SYSTEM")' not in installer


def test_windows_installer_rejects_drive_root_access():
    installer = Path("scripts/install-windows.ps1").read_text(encoding="utf-8")

    assert "Refusing drive-root access in AllowedRoots" in installer
    assert "[IO.Path]::GetPathRoot" in installer
    assert 'C:\\hh-agent' in installer
