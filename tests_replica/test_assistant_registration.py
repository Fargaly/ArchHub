"""Court: an assistant gets the ArchHub MCP entry only on the person's consent.

Real config files in a temporary profile, the real install layout the entry
points at, and the real readiness/registration code. The person's own
configs are never read or written by this court.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nodelang import assistant_registration as registration  # noqa: E402
from nodelang.native_workshop_profile import SERVER_NAME  # noqa: E402


@pytest.fixture
def machine(tmp_path, monkeypatch):
    install = tmp_path / "ArchHub"
    (install / ".venv" / "Scripts").mkdir(parents=True)
    (install / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
    (install / "runtime").mkdir()
    (install / "runtime" / "node.exe").write_bytes(b"")
    (install / "nodelang").mkdir()
    (install / "nodelang" / "native_agent_mcp.py").write_text("", encoding="utf-8")
    profile = tmp_path / "profile"
    profile.mkdir()
    state = tmp_path / "state"
    env = {"USERPROFILE": str(profile), "LOCALAPPDATA": str(tmp_path / "local"),
           "ARCHHUB_TEST_STATE_DIR": str(state), "PATH": ""}
    monkeypatch.setattr(registration, "install_roots", lambda environment=None: (install, state))
    return type("Machine", (), {"install": install, "profile": profile, "state": state, "env": env})


def _codex(machine):
    return next(c for c in registration.readiness(machine.env)["clients"] if c["client"] == "codex")


def test_nothing_is_written_without_consent(machine):
    config = machine.profile / ".codex" / "config.toml"
    assert _codex(machine)["state"] == "ready_to_register"
    with pytest.raises(ValueError):
        registration.register("codex", consent=False, environment=machine.env)
    assert not config.exists()


def test_codex_gets_one_entry_on_consent_and_keeps_every_existing_byte(machine):
    config = machine.profile / ".codex" / "config.toml"
    config.parent.mkdir()
    before = b'model = "gpt"\n\n[mcp_servers.brain]\nurl = "http://127.0.0.1:8473/mcp"\n'
    config.write_bytes(before)
    result = registration.register("codex", consent=True, environment=machine.env)
    assert result["state"] == "registered"
    after = config.read_bytes()
    assert after.startswith(before)
    table = tomllib.loads(after.decode("utf-8"))["mcp_servers"][SERVER_NAME]
    assert table["command"] == str(machine.install / ".venv" / "Scripts" / "python.exe")
    assert table["args"][-1] == str(machine.install)
    assert table["env_vars"] == ["CODEX_THREAD_ID"]
    assert table["env"]["ARCHHUB_COORDINATION_VENDOR"] == "codex"
    # A second consent changes nothing.
    assert registration.register("codex", consent=True, environment=machine.env)["state"] == "registered"
    assert config.read_bytes() == after


def test_a_different_entry_or_a_legacy_entry_is_reported_and_left_alone(machine):
    config = machine.profile / ".codex" / "config.toml"
    config.parent.mkdir()
    mine = '[mcp_servers.%s]\ncommand = "python.exe"\nargs = ["-m", "nodelang.clean_coordination_mcp"]\n' % SERVER_NAME
    config.write_text(mine, encoding="utf-8")
    assert registration.register("codex", consent=True, environment=machine.env)["state"] == "conflict"
    assert config.read_text(encoding="utf-8") == mine
    legacy = '[mcp_servers.archhub-hosts]\ncommand = "pythonw.exe"\n'
    config.write_text(legacy, encoding="utf-8")
    report = registration.register("codex", consent=True, environment=machine.env)
    assert report["state"] == "legacy_migration_required"
    assert report["legacy_migration_needed"] == ["archhub-hosts"]
    assert config.read_text(encoding="utf-8") == legacy


def test_opencode_is_reported_unsupported_and_never_written(machine):
    opencode = next(c for c in registration.readiness(machine.env)["clients"] if c["client"] == "opencode")
    assert opencode["state"] == "unsupported" and "ses_" in opencode["reason"]
    assert registration.register("opencode", consent=True, environment=machine.env)["state"] == "unsupported"
    assert not (machine.profile / ".config").exists()


def test_claude_code_without_its_command_is_reported_not_installed(machine):
    claude = next(c for c in registration.readiness(machine.env)["clients"] if c["client"] == "claude-code")
    assert claude["state"] == "not_installed"


def test_the_settings_route_is_declared_and_needs_consent():
    source = (ROOT / "nodelang" / "universal_application.py").read_text(encoding="utf-8")
    assert '("POST", "/api/universal/assistant-registration", "execute")' in source
    assert '("GET", "/api/universal/assistant-registration", "read")' in source
    server = (ROOT / "nodelang" / "application_server.py").read_text(encoding="utf-8")
    handler = server[server.index("if self.path == '/api/universal/assistant-registration':"):]
    handler = handler[:handler.index("return\n")]
    assert "body['consent'] is not True" in handler and "authorization.subject_root" in handler
