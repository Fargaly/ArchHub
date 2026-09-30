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
    # Its Code tab is Claude Code and reads the user entry; its chat is never configured.
    assert report["claude_desktop"].startswith("detected: its Code tab uses the Claude Code user entry")
    assert "its chat is not supported" in report["claude_desktop"]
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


# The founder's machine on 2026-09-30 (read by 717): the first claude on PATH is
# ArchHub's governed shim, and the user scope holds the development-era
# coordination launch and the retired 12.PRODUCTION host server beside his own.
_SHIM = ('@echo off\r\nsetlocal\r\nset ARCHHUB_GOVERNED_SHIM_ACTIVE=1\r\n'
         '"C:\\Users\\someone\\AppData\\Local\\Python\\pythoncore-3.14-64\\python.exe" '
         '"C:\\Users\\someone\\00.ARCHUB\\10.PRODUCT\\12.PRODUCTION\\tools\\brainwrap.py" launch '
         '--governed-strict --cwd "C:\\Users\\someone\\00.ARCHUB" -- "%s" %%*\r\n')
_COORDINATION = {"command": "C:/Users/someone/AppData/Local/Python/pythoncore-3.14-64/python.exe",
                 "args": ["-m", "nodelang.clean_coordination_mcp"],
                 "env": {"ARCHHUB_COORDINATION_VENDOR": "claude",
                         "PYTHONPATH": "C:/Users/someone/00.ARCHUB/10.PRODUCT/13.NODE-LANGUAGE"}}
_HOSTS = {"type": "stdio", "command": "C:/Users/someone/AppData/Local/Python/pythoncore-3.14-64/pythonw.exe",
          "args": ["C:/Users/someone/00.ARCHUB/10.PRODUCT/12.PRODUCTION/payload/bridge/server.py"], "env": {}}
_OWN = {"gmail-secondary": {"command": "npx", "args": ["-y", "gmail-mcp"]},
        "magnific": {"type": "http", "url": "https://example.invalid/mcp"}}


def _founder_machine(tmp_path, shim=_SHIM, servers=None):
    legacy = {"archhub-agent-coordination": _COORDINATION, "archhub-hosts": _HOSTS}
    root, state, home, environment = _rig(tmp_path, servers={**(legacy if servers is None else servers), **_OWN})
    governed = tmp_path / "local" / "ArchHub" / "governed-bin"
    governed.mkdir(parents=True)
    target = home / ".local" / "bin" / "claude.exe"
    (governed / "claude.cmd").write_bytes((shim % target).encode("ascii"))
    return root, state, home, dict(environment, PATH=str(governed)), governed / "claude.cmd"


def _claude_cli(home, calls):
    """Claude Code's own add-json / remove, as they change ~/.claude.json."""
    def run(argv, **kwargs):
        assert kwargs["shell"] is False and "PYTHONPATH" not in kwargs["env"]
        assert kwargs["stdout"] is subprocess.DEVNULL and kwargs["stderr"] is subprocess.DEVNULL
        calls.append(list(argv))
        config = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
        if argv[1:3] == ["mcp", "add-json"]:
            config["mcpServers"][argv[3]] = json.loads(argv[4])
        else:
            assert argv[1:3] == ["mcp", "remove"] and argv[4:] == ["--scope", "user"]
            config["mcpServers"].pop(argv[3])
        (home / ".claude.json").write_text(json.dumps(config), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0)
    return run


def test_the_founders_machine_is_reported_truthfully_before_anything_runs(tmp_path):
    root, state, home, environment, shim = _founder_machine(tmp_path)
    report = installation.readiness(root, state, environment=environment)
    # The governed shim is followed to the claude.exe it runs; the shim itself never runs.
    assert report["executable"] == str(home / ".local" / "bin" / "claude.exe")
    assert report["launcher"]["via"] == str(shim)
    assert report["legacy_migration_needed"] == ["archhub-agent-coordination", "archhub-hosts"]
    # Only the coordination launch is offered; the host server's live tools stay.
    assert sorted(report["legacy_retire"]) == ["archhub-agent-coordination"]
    assert report["claude_code"] == "migration_available"
    before = (home / ".claude.json").read_bytes()
    assert installation.register_claude_code(root, state, consent=False, environment=environment,
                                             run=_no_process)["claude_code"] == "migration_available"
    assert (home / ".claude.json").read_bytes() == before


def test_one_yes_registers_this_install_and_retires_only_the_development_coordination_entry(tmp_path):
    root, state, home, environment, _shim = _founder_machine(tmp_path)
    calls = []
    report = installation.register_claude_code(root, state, consent=True, environment=environment,
                                               run=_claude_cli(home, calls))
    exe = str(home / ".local" / "bin" / "claude.exe")
    assert [call[:4] for call in calls] == [[exe, "mcp", "add-json", SERVER_NAME],
                                           [exe, "mcp", "remove", "archhub-agent-coordination"]]
    servers = json.loads((home / ".claude.json").read_text(encoding="utf-8"))["mcpServers"]
    assert servers == {SERVER_NAME: installation.managed_entry(root, state), "archhub-hosts": _HOSTS, **_OWN}
    assert report["claude_code"] == "registered"
    # What was retired is returned whole, so it can be restored exactly.
    assert report["retired"] == {"archhub-agent-coordination": _COORDINATION}


def test_a_founder_already_moved_by_hand_is_registered_and_the_host_server_is_never_offered(tmp_path):
    # 717 registered this install and retired the coordination entry by hand; the host server remains
    # because his live Revit, AutoCAD and Max sessions use its direct tools.
    root, state, home, environment, _shim = _founder_machine(tmp_path, servers={"archhub-hosts": _HOSTS})
    config = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    config["mcpServers"][SERVER_NAME] = installation.managed_entry(root, state)
    (home / ".claude.json").write_text(json.dumps(config), encoding="utf-8")
    before = (home / ".claude.json").read_bytes()
    report = installation.register_claude_code(root, state, consent=True, environment=environment,
                                               run=_no_process)
    assert (report["claude_code"], report["legacy_retire"]) == ("registered", {})
    assert (home / ".claude.json").read_bytes() == before


def test_a_legacy_name_in_any_other_shape_blocks_and_nothing_runs(tmp_path):
    changed = dict(_COORDINATION, args=["-m", "nodelang.native_agent_mcp"])
    root, state, home, environment, _shim = _founder_machine(
        tmp_path, servers={"archhub-agent-coordination": changed, "archhub-hosts": _HOSTS})
    before = (home / ".claude.json").read_bytes()
    report = installation.register_claude_code(root, state, consent=True, environment=environment,
                                               run=_no_process)
    assert report["claude_code"] == "legacy_migration_required"
    assert report["legacy_retire"] == {}
    assert (home / ".claude.json").read_bytes() == before


def test_a_legacy_entry_changed_after_the_check_is_never_removed(tmp_path):
    root, state, home, environment, _shim = _founder_machine(tmp_path)
    calls = []
    cli = _claude_cli(home, calls)

    def racing(argv, **kwargs):
        result = cli(argv, **kwargs)
        if argv[1:3] == ["mcp", "add-json"]:
            # Another writer changes the coordination entry between the add and its removal.
            config = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
            config["mcpServers"]["archhub-agent-coordination"]["args"] = ["-m", "someone.else"]
            (home / ".claude.json").write_text(json.dumps(config), encoding="utf-8")
        return result

    report = installation.register_claude_code(root, state, consent=True, environment=environment, run=racing)
    assert [call[1:3] for call in calls] == [["mcp", "add-json"]]
    assert (report["claude_code"], report["reason"]) == (
        "migration_unconfirmed", "legacy_entry_changed_before_removal")
    servers = json.loads((home / ".claude.json").read_text(encoding="utf-8"))["mcpServers"]
    assert servers["archhub-agent-coordination"]["args"] == ["-m", "someone.else"]


@pytest.mark.parametrize("shim", [
    _SHIM.replace("setlocal\r\n", "setlocal\r\nset CLAUDE_CONFIG_DIR=C:\\elsewhere\r\n"),   # another config
    _SHIM.replace('-- "%s"', '-- "%s" --mcp-config x.json'),                                # extra arguments
    _SHIM.replace('-- "%s"', '-- "%s.bak"'),                                                # not claude.exe
], ids=["config-dir", "extra-args", "other-program"])
def test_any_other_wrapper_stays_unsupported(tmp_path, shim):
    root, state, _home, environment, wrapper = _founder_machine(tmp_path, shim=shim)
    report = installation.register_claude_code(root, state, consent=True, environment=environment,
                                               run=_no_process)
    assert (report["claude_code"], report["executable"]) == ("unsupported_launcher", str(wrapper))
    # The legacy entries are still reported, so the person sees why nothing changed.
    assert report["legacy_migration_needed"] == ["archhub-agent-coordination", "archhub-hosts"]


def test_the_shim_target_is_checked_like_any_claude_exe_mocked_reparse(tmp_path, monkeypatch):
    root, state, home, environment, _shim = _founder_machine(tmp_path)
    _pretend_redirected(monkeypatch, home / ".local" / "bin" / "claude.exe")
    report = installation.register_claude_code(root, state, consent=True, environment=environment,
                                               run=_no_process)
    assert report["claude_code"] == "launcher_untrusted"
