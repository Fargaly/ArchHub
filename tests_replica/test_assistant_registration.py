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


# The layout a real Codex config carries around ArchHub's development-era entry:
# other servers before and after it, a retired installer's region markers, a
# comment that belongs to the next table.
_DEV_ERA = """model = "gpt"
notify = ["C:\\\\notifier.exe", "turn-ended"]

[mcp_servers.node_repl]
args = []
command = 'C:\\node_repl.exe'
env_vars = ["CODEX_WINDOWS_REGISTERED_CORE"]

[shell_environment_policy.set]
KEY = "value"

# personal-brain-mcp (managed by `personal-brain-mcp installer`)
[mcp_servers.%(name)s]
command = 'C:\\Users\\someone\\AppData\\Local\\Python\\pythoncore-3.14-64\\python.exe'
args = ["-m", "nodelang.clean_coordination_mcp"]

[mcp_servers.%(name)s.env]
PYTHONPATH = 'C:\\Users\\someone\\00.ARCHUB\\10.PRODUCT\\13.NODE-LANGUAGE'
ARCHHUB_COORDINATION_VENDOR = "codex"

# the next table's own note
[mcp_servers.higsfield]
enabled = true
url = "https://mcp.example.test/mcp"
# /personal-brain-mcp

[hooks.state.'C:\\Users\\someone\\.codex\\hooks.json:stop:0:0']
trusted_hash = "sha256:fixture"
""" % {"name": SERVER_NAME}


def _dev_config(machine, text=_DEV_ERA):
    config = machine.profile / ".codex" / "config.toml"
    config.parent.mkdir(exist_ok=True)
    config.write_bytes(text.encode("utf-8"))
    return config


def test_only_the_exact_development_era_entry_is_offered_for_replacement(machine):
    _dev_config(machine)
    assert _codex(machine)["state"] == "migration_available"
    variants = {
        "a person's own env_vars": ('args = ["-m", "nodelang.clean_coordination_mcp"]\n',
                                    'args = ["-m", "nodelang.clean_coordination_mcp"]\nenv_vars = ["X"]\n'),
        "another module": ("nodelang.clean_coordination_mcp", "nodelang.native_agent_mcp"),
        "another vendor": ('ARCHHUB_COORDINATION_VENDOR = "codex"', 'ARCHHUB_COORDINATION_VENDOR = "claude"'),
        "a relative path": ("PYTHONPATH = 'C:\\Users\\someone\\00.ARCHUB\\10.PRODUCT\\13.NODE-LANGUAGE'",
                            "PYTHONPATH = 'src'"),
        "an extra variable": ('ARCHHUB_COORDINATION_VENDOR = "codex"\n',
                              'ARCHHUB_COORDINATION_VENDOR = "codex"\nOTHER = "1"\n'),
        "another launcher": ("pythoncore-3.14-64\\python.exe", "pythoncore-3.14-64\\custom.exe"),
    }
    for name, (old, new) in variants.items():
        assert old in _DEV_ERA, name
        config = _dev_config(machine, _DEV_ERA.replace(old, new, 1))
        before = config.read_bytes()
        assert _codex(machine)["state"] == "conflict", name
        assert registration.register("codex", consent=True, environment=machine.env)["state"] == "conflict", name
        assert config.read_bytes() == before, name


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI backup")
def test_replacement_on_consent_changes_only_that_entry_and_keeps_an_encrypted_copy(machine):
    config = _dev_config(machine)
    original = config.read_bytes()
    with pytest.raises(ValueError):
        registration.register("codex", consent=False, environment=machine.env)
    assert registration.migrate_codex(machine.install, machine.state, consent=False,
                                      environment=machine.env)["state"] == "migration_available"
    assert config.read_bytes() == original
    result = registration.register("codex", consent=True, environment=machine.env)
    assert result["state"] == "registered"
    after = config.read_bytes().decode("utf-8")
    # The effective entry, read back, is this install's; nothing else changed meaning.
    data, old = tomllib.loads(after), tomllib.loads(original.decode("utf-8"))
    assert data["mcp_servers"][SERVER_NAME] == registration.codex_entry(machine.install, machine.state)
    assert data["mcp_servers"][SERVER_NAME]["env_vars"] == ["CODEX_THREAD_ID"]
    assert "PYTHONPATH" not in data["mcp_servers"][SERVER_NAME]["env"]
    assert {k: v for k, v in data.items() if k != "mcp_servers"} == {k: v for k, v in old.items() if k != "mcp_servers"}
    assert {k: v for k, v in data["mcp_servers"].items() if k != SERVER_NAME} == \
           {k: v for k, v in old["mcp_servers"].items() if k != SERVER_NAME}
    # Every line outside the replaced table is kept, in order, comments included.
    kept = [line for line in original.decode("utf-8").splitlines()
            if "clean_coordination_mcp" not in line and "PYTHONPATH" not in line
            and "pythoncore" not in line and "ARCHHUB_COORDINATION_VENDOR" not in line
            and not line.startswith("[mcp_servers.%s" % SERVER_NAME) and line.strip()]
    remaining = [line for line in after.splitlines() if line in kept]
    assert remaining == kept
    assert after.index("# personal-brain-mcp") < after.index("[mcp_servers.%s]" % SERVER_NAME) \
        < after.index("# the next table's own note") < after.index("[mcp_servers.higsfield]")
    # The whole prior file is kept, DPAPI-protected, and decrypts to the exact old bytes.
    from nodelang.cell_secret_keys import unprotect_current_user_data
    backup = Path(result["backup"])
    assert backup.parent == machine.state / "private-client-backups" and backup.suffix == ".dpapi"
    assert b"clean_coordination_mcp" not in backup.read_bytes()
    assert unprotect_current_user_data(backup.read_bytes(),
                                       purpose="archhub.client-hook-backup/v1") == original
    # A second consent changes nothing.
    assert registration.register("codex", consent=True, environment=machine.env)["state"] == "registered"
    assert config.read_bytes().decode("utf-8") == after


@pytest.mark.parametrize("near_miss", [
    ('args = ["-m", "nodelang.clean_coordination_mcp"]\n',
     'args = ["-m", "nodelang.clean_coordination_mcp"]\nenv_vars = ["CODEX_THREAD_ID"]\n'),
    ('ARCHHUB_COORDINATION_VENDOR = "codex"\n', 'ARCHHUB_COORDINATION_VENDOR = "codex"\nMY_SETTING = "kept"\n'),
])
def test_an_entry_changed_after_the_check_is_never_overwritten(machine, monkeypatch, near_miss):
    """Readiness sees the legacy shape; the bytes read next carry another writer's entry."""
    config = _dev_config(machine)
    changed = _DEV_ERA.replace(*near_miss, 1).encode("utf-8")
    checked = registration.codex_readiness
    raced = []

    def racing(*args, **kwargs):
        result = checked(*args, **kwargs)
        if not raced:
            raced.append(True)
            config.write_bytes(changed)          # another writer, between check and read
        return result

    monkeypatch.setattr(registration, "codex_readiness", racing)
    # migrate_codex's own readiness check is the one the other writer races.
    result = registration.migrate_codex(machine.install, machine.state, consent=True,
                                        environment=machine.env)
    assert raced and result["state"] == "conflict"
    assert config.read_bytes() == changed
    backups = machine.state / "private-client-backups"
    assert not backups.exists() or not any(backups.iterdir())


def test_a_split_table_is_refused_and_left_exactly_as_it_was(machine):
    split = _DEV_ERA.replace("[mcp_servers.%s.env]" % SERVER_NAME, "[unrelated]\nx = 1\n\n[mcp_servers.%s.env]" % SERVER_NAME)
    config = _dev_config(machine, split)
    before = config.read_bytes()
    assert _codex(machine)["state"] == "migration_available"
    result = registration.register("codex", consent=True, environment=machine.env)
    assert result["state"] == "migration_unconfirmed"
    assert config.read_bytes() == before
    assert not (machine.state / "private-client-backups").exists() or \
        not any((machine.state / "private-client-backups").iterdir())


def test_opencode_gets_no_mcp_entry_and_is_not_written_when_absent(machine):
    # OpenCode connects through the Session Link plugin (test_opencode_is_recognised_and_connected).
    opencode = next(c for c in registration.readiness(machine.env)["clients"] if c["client"] == "opencode")
    assert opencode["state"] == "not_installed" and opencode["governance"] == "blocked"
    assert registration.register("opencode", consent=True, environment=machine.env)["state"] == "not_installed"
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
    assert "authorization.subject_root" in handler


from tests_replica.test_settings_terminal_routes import server, call  # noqa: E402


def test_the_settings_route_writes_nothing_without_explicit_consent(server, monkeypatch):
    """Behaviour, not source text: only consent=True reaches either writer (connect or hook repair)."""
    written = []
    monkeypatch.setattr(registration, "register", lambda client, **kwargs: written.append(
        ("register", client, kwargs)) or {"client": client, "state": "registered"})
    monkeypatch.setattr(registration, "repair_hooks", lambda client, **kwargs: written.append(
        ("repair", client, kwargs)) or {"changed": True}, raising=False)
    route = "/api/universal/assistant-registration"
    repair = {"client": "codex", "action": "repair-hooks", "plan_digest": "reviewed"}
    for body in ({"client": "codex", "consent": False}, {"client": "codex", "consent": "true"},
                 {"client": "codex"}, {"client": "codex", "consent": True, "extra": 1},
                 dict(repair, consent=False), dict(repair, consent="true"), dict(repair),
                 dict(repair, consent=True, plan_digest=1), dict(repair, consent=True, extra=1)):
        call(server, route, body, expected=400)
    assert written == []
    call(server, route, {"client": "codex", "consent": True})
    call(server, route, dict(repair, consent=True))
    assert written == [("register", "codex", {"consent": True}),
                       ("repair", "codex", {"consent": True, "plan_digest": "reviewed"})]


def test_gemini_without_its_folder_is_not_installed(machine):
    """Court: Settings never claims Gemini safety settings when ~/.gemini is absent."""
    gemini = next(c for c in registration.readiness(machine.env)["clients"] if c["client"] == "gemini-cli")
    assert gemini["state"] == "not_installed"
    assert not (machine.profile / ".gemini").exists()
