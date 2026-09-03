"""Static security court for the versioned Windows runtime task installer."""
from pathlib import Path


def test_runtime_task_registration_is_background_limited_and_not_self_starting():
    script = (
        Path(__file__).resolve().parents[1]
        / "packaging" / "windows" / "install_runtime_task.ps1"
    ).read_text(encoding="utf-8")

    assert "pythonw" in script.casefold()
    assert "-MultipleInstances IgnoreNew" in script
    assert "-ExecutionTimeLimit ([TimeSpan]::Zero)" in script
    assert "-RunLevel Limited" in script
    assert "$AuditOnly" in script
    assert "Get-ScheduledTask" in script
    assert "compliant =" in script
    assert "Start-ScheduledTask" not in script
    assert "Stop-ScheduledTask" not in script
