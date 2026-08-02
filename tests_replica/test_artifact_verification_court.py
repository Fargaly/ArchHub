import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodelang.artifact_verification_court import ArtifactVerificationCourt


def test_court_subprocess_preserves_only_required_windows_local_app_data(
    monkeypatch, tmp_path
):
    local_app_data = str(tmp_path / "LocalAppData")
    monkeypatch.setenv("LOCALAPPDATA", local_app_data)
    monkeypatch.setenv("ARCHHUB_UNADMITTED_ENVIRONMENT", "must-not-cross")

    environment = ArtifactVerificationCourt._subprocess_environment()

    assert environment["LOCALAPPDATA"] == local_app_data
    assert "ARCHHUB_UNADMITTED_ENVIRONMENT" not in environment
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert environment["PYTHONSAFEPATH"] == "1"
