from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
PAYLOAD = REPO / "payload" / "rhino"


def test_rhino_watchdog_payload_is_hidden_detached_and_user_scoped():
    installer = (PAYLOAD / "_install_task.ps1").read_text(encoding="utf-8")
    watchdog = (PAYLOAD / "_ensure_bridge.ps1").read_text(encoding="utf-8")

    assert "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" in installer
    assert "Start-Process" in installer
    assert "-WindowStyle Hidden" in installer
    assert "Unregister-ScheduledTask" in installer
    assert "Register-ScheduledTask" not in installer
    assert "Run as Administrator" not in installer
    assert "Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden" in installer
    assert "[switch]$Watch" in watchdog
    assert "Start-Sleep -Seconds 3" in watchdog
    assert "C:\\Users\\fargaly" not in installer
    assert "C:\\Users\\fargaly" not in watchdog
    assert "Join-Path $PSScriptRoot '_ensure_bridge.ps1'" in installer
    assert "Join-Path $env:APPDATA" in watchdog


def test_rhino_watchdog_only_focuses_real_rhino_when_bridge_is_down():
    watchdog = (PAYLOAD / "_ensure_bridge.ps1").read_text(encoding="utf-8")

    assert "function Test-Bridge" in watchdog
    assert "if (Test-Bridge)" in watchdog
    assert "[AHB]::Find()" in watchdog
    assert "if ([AHB]::Main -eq [IntPtr]::Zero)" in watchdog
    assert "SetForegroundWindow" in watchdog
    assert "Set-Clipboard -Value $cmd" in watchdog
    assert "Set-Clipboard -Value $saved" in watchdog


def test_adapter_payload_candidate_category_has_direct_payload_court():
    source = (REPO / "tools" / "authority_wip_classify.py").read_text(
        encoding="utf-8"
    )

    assert "tests/test_adapter_payload_candidate.py" in source
    assert "ADAPTER_PAYLOAD_COURTS" in source
