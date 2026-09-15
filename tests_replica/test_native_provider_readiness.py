"""Installed-client presence is distinct from a discovered live session."""
from nodelang import model_execution_broker as broker_module


def test_local_cli_readiness_uses_real_file_presence_without_http_or_credentials(tmp_path, monkeypatch):
    executable = tmp_path / ".local/bin/claude.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"")
    monkeypatch.setattr(broker_module.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(broker_module.shutil, "which", lambda candidate: None)
    # Neither object admits credential or HTTP methods; invoking either fails.
    broker = broker_module.ModelExecutionBroker(workspace_root=tmp_path,
        host=object(), credential_resolver=object())
    readiness = broker.local_cli_readiness()
    assert set(readiness) == {"codex", "claude", "gemini"}
    assert readiness["claude"]["state"] == "executable-discovered"
    assert readiness["codex"]["state"] == "provider-unavailable"
    assert "session_id" not in readiness["claude"]
    assert str(executable) not in str(readiness)
    executable.unlink()
    assert broker.local_cli_readiness()["claude"]["state"] == "provider-unavailable"
