"""Courts for offering ArchHub's MCP owner to a person's own Claude Code.

Each court holds one way registration could damage a setup ArchHub does not
own: replacing a same-name entry, writing without a yes, passing the entry
through a shell wrapper, echoing configuration, starting the server (which
enrolls an actor) just to look, running beside development-era owners, or
touching Claude Desktop.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nodelang import client_mcp_installation as installation  # noqa: E402
from nodelang.native_workshop_profile import SERVER_NAME  # noqa: E402


def _rig(tmp_path, servers=None, projects=None):
    root = tmp_path / "ArchHub"
    for relative in (".venv/Scripts/python.exe", "nodelang/native_agent_mcp.py", "runtime/node.exe"):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"")
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".local" / "bin" / "claude.exe").write_bytes(b"")
    config = {"numStartups": 3, "mcpServers": dict(servers or {})}
    if projects is not None:
        config["projects"] = projects
    (home / ".claude.json").write_text(json.dumps(config), encoding="utf-8")
    environment = {"USERPROFILE": str(home), "PATH": "",
                   "APPDATA": str(tmp_path / "roaming"), "LOCALAPPDATA": str(tmp_path / "local")}
    return root, tmp_path / "state", home, environment


def _no_process(*_args, **_kwargs):
    raise AssertionError("no process may start here")


def _pretend_redirected(monkeypatch, target):
    """MOCKED reparse point: report `target` as redirected without creating a link."""
    real = installation._lstat

    def lstat(path):
        info = real(path)
        if Path(path) == Path(target):
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400,
                                   st_dev=info.st_dev, st_ino=info.st_ino,
                                   st_size=info.st_size, st_mtime_ns=info.st_mtime_ns)
        return info

    monkeypatch.setattr(installation, "_lstat", lstat)


def test_entry_is_the_installed_isolated_loader_without_identity_or_development_paths(tmp_path):
    root, state, _home, _environment = _rig(tmp_path)
    entry = installation.managed_entry(root, state)
    assert entry["command"] == str(root / ".venv" / "Scripts" / "python.exe")
    assert entry["args"] == ["-I", "-B", "-c", installation.LOADER, str(root)]
    assert entry["env"] == {"ARCHHUB_COORDINATION_VENDOR": "claude",
                            "SESSION_LINK_STATE_DIR": str(state / "session-link"),
                            "SESSION_LINK_NODE": str(root / "runtime" / "node.exe")}
    text = json.dumps(entry)
    for forbidden in ("PYTHONPATH", "--expected-actor", "--workshop-task", "--stop-hook-ipc",
                      "SESSION_ID", "assembly-instance:", "app:agent-session"):
        assert forbidden not in text


def test_missing_installed_file_refuses_instead_of_registering_a_dead_entry(tmp_path):
    root, state, _home, environment = _rig(tmp_path)
    (root / "runtime" / "node.exe").unlink()
    report = installation.register_claude_code(root, state, consent=True,
                                               environment=environment, run=_no_process)
    assert report["claude_code"] == "install_incomplete"


def test_directory_named_like_an_executable_is_refused(tmp_path):
    root, state, _home, environment = _rig(tmp_path)
    python = root / ".venv" / "Scripts" / "python.exe"
    python.unlink()
    python.mkdir()
    report = installation.readiness(root, state, environment=environment)
    assert report["claude_code"] == "install_incomplete"
    assert "not a file" in report["reason"]


def test_redirected_install_root_is_refused_with_a_native_junction(tmp_path):
    winapi = pytest.importorskip("_winapi")
    real_root, state, _home, environment = _rig(tmp_path)
    linked = tmp_path / "ArchHub-link"
    try:
        winapi.CreateJunction(str(real_root), str(linked))
    except (AttributeError, OSError) as exc:
        pytest.skip("native junction unavailable here: %s" % exc)
    report = installation.readiness(linked, state, environment=environment)
    assert report["claude_code"] == "install_incomplete"
    assert "redirected" in report["reason"]


def test_redirected_ancestor_of_the_install_is_refused_mocked_reparse(tmp_path, monkeypatch):
    root, state, _home, environment = _rig(tmp_path)
    _pretend_redirected(monkeypatch, tmp_path)
    report = installation.readiness(root, state, environment=environment)
    assert report["claude_code"] == "install_incomplete"
    assert "redirected" in report["reason"]


def test_same_name_entry_that_differs_is_reported_and_never_replaced(tmp_path):
    root, state, home, environment = _rig(tmp_path, servers={SERVER_NAME: {"command": "theirs.exe"}})
    before = (home / ".claude.json").read_bytes()
    report = installation.register_claude_code(root, state, consent=True,
                                               environment=environment, run=_no_process)
    assert report["claude_code"] == "conflict"
    assert (home / ".claude.json").read_bytes() == before


def test_equal_entry_is_already_registered_and_runs_nothing(tmp_path):
    root, state, home, environment = _rig(tmp_path)
    entry = installation.managed_entry(root, state)
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {SERVER_NAME: entry}}, indent=4),
                                       encoding="utf-8")
    report = installation.register_claude_code(root, state, consent=True,
                                               environment=environment, run=_no_process)
    assert report["claude_code"] == "registered"
    assert report["host_execution"] == "not_verified"


def test_unreadable_or_relocated_configuration_is_never_written(tmp_path):
    root, state, home, environment = _rig(tmp_path)
    (home / ".claude.json").write_text("{not json", encoding="utf-8")
    assert installation.register_claude_code(root, state, consent=True, environment=environment,
                                             run=_no_process)["claude_code"] == "config_unreadable"
    (home / ".claude.json").write_text("{}", encoding="utf-8")
    relocated = dict(environment, CLAUDE_CONFIG_DIR=str(tmp_path / "elsewhere"))
    assert installation.register_claude_code(
        root, state, consent=True, environment=relocated,
        run=_no_process)["claude_code"] == "config_location_unverified"


def test_first_claude_on_path_decides_and_a_wrapper_is_refused(tmp_path):
    root, state, _home, environment = _rig(tmp_path)
    wrappers = tmp_path / "governed-bin"
    wrappers.mkdir()
    (wrappers / "claude.cmd").write_text("@echo off", encoding="ascii")
    report = installation.register_claude_code(root, state, consent=True,
                                               environment=dict(environment, PATH=str(wrappers)),
                                               run=_no_process)
    assert report["claude_code"] == "unsupported_launcher"
    assert report["executable"] == str(wrappers / "claude.cmd")


def test_redirected_launcher_is_reported_and_never_run_mocked_reparse(tmp_path, monkeypatch):
    root, state, home, environment = _rig(tmp_path)
    _pretend_redirected(monkeypatch, home / ".local" / "bin" / "claude.exe")
    report = installation.register_claude_code(root, state, consent=True,
                                               environment=environment, run=_no_process)
    assert report["claude_code"] == "launcher_untrusted"


def test_launcher_that_changes_before_the_run_is_never_run(tmp_path, monkeypatch):
    root, state, _home, environment = _rig(tmp_path)
    real = installation.find_claude_code
    seen = []

    def drifting(environment=None):
        found = real(environment)
        seen.append(found)
        return found if len(seen) == 1 else dict(found, identity=[0, 0, 0, 0])

    monkeypatch.setattr(installation, "find_claude_code", drifting)
    report = installation.register_claude_code(root, state, consent=True,
                                               environment=environment, run=_no_process)
    assert (report["claude_code"], report["reason"]) == (
        "registration_unconfirmed", "launcher_changed_before_run")


def test_development_era_owners_need_migration_and_never_count_as_a_connection(tmp_path):
    legacy = {"archhub-hosts": {"command": "pythonw.exe", "args": ["payload/bridge/server.py"]}}
    root, state, home, environment = _rig(tmp_path, servers=legacy)
    before = (home / ".claude.json").read_bytes()
    report = installation.register_claude_code(root, state, consent=True,
                                               environment=environment, run=_no_process)
    assert report["claude_code"] == "legacy_migration_required"
    assert report["legacy_migration_needed"] == ["archhub-hosts"]
    assert (home / ".claude.json").read_bytes() == before


def test_project_entry_of_the_same_name_would_shadow_the_user_entry(tmp_path):
    projects = {"C:/work": {"mcpServers": {SERVER_NAME: {"command": "local.exe"}}}}
    root, state, _home, environment = _rig(tmp_path, projects=projects)
    report = installation.register_claude_code(root, state, consent=True,
                                               environment=environment, run=_no_process)
    assert report["claude_code"] == "project_override"


def test_equal_user_entry_is_not_presented_as_effective_where_a_project_overrides_it(tmp_path):
    root, state, home, environment = _rig(tmp_path)
    entry = installation.managed_entry(root, state)
    projects = {"C:/work": {"mcpServers": {SERVER_NAME: {"command": "local.exe"}}},
                "C:/same": {"mcpServers": {SERVER_NAME: entry}}}
    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {SERVER_NAME: entry}, "projects": projects}), encoding="utf-8")
    report = installation.register_claude_code(root, state, consent=True,
                                               environment=environment, run=_no_process)
    assert report["claude_code"] == "registered_with_project_overrides"
    assert report["project_overrides"] == 1
    assert report["project_mcp_json"] == "not_inspected"


def test_claude_desktop_is_detected_but_never_configured(tmp_path):
    root, state, _home, environment = _rig(tmp_path)
    desktop = tmp_path / "roaming" / "Claude" / "claude_desktop_config.json"
    desktop.parent.mkdir(parents=True)
    desktop.write_text('{"mcpServers": {}}', encoding="utf-8")
    before = desktop.read_bytes()
    report = installation.readiness(root, state, environment=environment)
    assert report["claude_desktop"].startswith("detected: not supported")
    assert desktop.read_bytes() == before


def test_readiness_starts_no_process(tmp_path, monkeypatch):
    root, state, _home, environment = _rig(tmp_path)
    monkeypatch.setattr(subprocess, "run", _no_process)
    monkeypatch.setattr(subprocess, "Popen", _no_process)
    report = installation.readiness(root, state, environment=environment)
    assert report["claude_code"] == "ready_to_register"
    assert report["connection"].startswith("not_checked")


def test_registration_needs_a_yes_uses_no_shell_and_captures_no_output(tmp_path):
    root, state, home, environment = _rig(tmp_path)
    assert installation.register_claude_code(root, state, consent=False, environment=environment,
                                             run=_no_process)["claude_code"] == "ready_to_register"
    calls = []

    def refused(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 1)

    report = installation.register_claude_code(
        root, state, consent=True, environment=dict(environment, PYTHONPATH="x"), run=refused)
    ((argv, kwargs),) = calls
    assert argv[0] == str(home / ".local" / "bin" / "claude.exe")
    assert argv[1:4] == ["mcp", "add-json", SERVER_NAME] and argv[5:] == ["--scope", "user"]
    assert json.loads(argv[4]) == installation.managed_entry(root, state)
    assert kwargs["shell"] is False and "PYTHONPATH" not in kwargs["env"]
    assert kwargs["stdout"] is subprocess.DEVNULL and kwargs["stderr"] is subprocess.DEVNULL
    assert "capture_output" not in kwargs
    assert (report["claude_code"], report["reason"], report["exit_code"]) == (
        "registration_unconfirmed", "claude_mcp_add_refused", 1)


def test_timed_out_command_is_unconfirmed_with_a_fixed_reason(tmp_path):
    root, state, _home, environment = _rig(tmp_path)

    def slow(argv, **_kwargs):
        raise subprocess.TimeoutExpired(argv, 60)

    report = installation.register_claude_code(root, state, consent=True,
                                               environment=environment, run=slow)
    assert (report["claude_code"], report["reason"], report["exit_code"]) == (
        "registration_unconfirmed", "claude_mcp_add_timed_out", None)


def test_registered_is_claimed_only_when_the_configuration_shows_the_entry(tmp_path):
    root, state, home, environment = _rig(tmp_path)

    def cli(argv, **_kwargs):
        config = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
        config["mcpServers"][argv[3]] = json.loads(argv[4])
        (home / ".claude.json").write_text(json.dumps(config), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0)

    report = installation.register_claude_code(root, state, consent=True,
                                               environment=environment, run=cli)
    assert report["claude_code"] == "registered"
    assert json.loads((home / ".claude.json").read_text(encoding="utf-8"))["numStartups"] == 3
