from __future__ import annotations

import ast
from types import SimpleNamespace
from pathlib import Path

import pytest

from nodelang.universal_cell import DatabaseOwnerConflict


ROOT = Path(__file__).resolve().parents[2]


def _launcher_names(*names, **bindings):
    names = tuple(dict.fromkeys((*names, '_launcher_parameter', '_launcher_seconds')))
    tree = ast.parse((ROOT / "01.APP/nodelang/launcher.py").read_text(encoding="utf-8"))
    selected = [node for node in tree.body if getattr(node, "name", None) in names]
    assert {node.name for node in selected} == set(names)
    namespace = dict(bindings)
    exec(compile(ast.Module(body=selected, type_ignores=[]), "nodelang/launcher.py", "exec"), namespace)
    return namespace


def test_forced_foreground_requires_explicit_activation_and_idle_presence(monkeypatch):
    import sys
    from types import SimpleNamespace
    effects = []
    user32 = SimpleNamespace(
        IsIconic=lambda handle: False,
        ShowWindow=lambda *args: effects.append('show'),
        GetWindowThreadProcessId=lambda *args: 1,
        GetForegroundWindow=lambda: 1,
        BringWindowToTop=lambda *args: effects.append('top'),
        SetForegroundWindow=lambda *args: effects.append('foreground'),
        SetActiveWindow=lambda *args: effects.append('active'),
        IsWindowVisible=lambda handle: True,
    )
    monkeypatch.setitem(sys.modules, 'ctypes', SimpleNamespace(windll=SimpleNamespace(
        user32=user32, kernel32=SimpleNamespace(GetCurrentThreadId=lambda: 1))))
    presence = {'idle': False}
    foreground = _launcher_names('_force_foreground',
        idle_or_away=lambda: presence['idle'])['_force_foreground']
    assert foreground(123, explicit_activation=True) is False
    presence['idle'] = True
    assert foreground(123) is False
    assert effects == []
    assert foreground(123, explicit_activation=True) is True
    assert effects == ['show', 'top', 'foreground', 'active']


@pytest.mark.parametrize('age,allowed', [(0, False), (2, True), (float('inf'), False),
                                      (float('nan'), False), (None, False)])
def test_unknown_or_active_presence_never_allows_forced_focus(monkeypatch, age, allowed):
    import sys
    from types import SimpleNamespace
    monkeypatch.setitem(sys.modules, 'nodelang.baboom_native_companion',
                        SimpleNamespace(desktop_input_idle_seconds=lambda: age))
    assert _launcher_names('idle_or_away')['idle_or_away']() is allowed


def _headless_launch(state_dir, monkeypatch, failure=None):
    """Exercise the current launcher offscreen, with no BABOOM worker or updater."""
    from nodelang import cloud_session, nograph_launcher, quiet_update
    from nodelang.nograph_server import NoGraphServer
    from nodelang.universal_cell import CellStore

    monkeypatch.setenv("ARCHHUB_TEST_NO_OPEN", "1")
    monkeypatch.setenv("ARCHHUB_TEST_HTTP_PORT", "0")
    monkeypatch.setattr(cloud_session, "_roaming_directory", lambda: state_dir / "ROAMING")
    monkeypatch.setattr(quiet_update, "stage_app_folder", lambda *a: None)
    monkeypatch.setattr(quiet_update, "finish_app_folder", lambda *a, **k: None)
    monkeypatch.setattr(quiet_update, "confirm_when_free", lambda *a: {})
    monkeypatch.setattr(nograph_launcher, "threading", SimpleNamespace(
        Thread=lambda **k: SimpleNamespace(start=lambda: None),
        Event=lambda: SimpleNamespace(wait=lambda: None)))

    def no_graph(*a, **k):
        raise AssertionError("NOGRAPH boot must never open a graph")

    monkeypatch.setattr(CellStore, "__init__", no_graph)
    servers = []
    start = NoGraphServer.start

    def boot(server):
        if failure is not None:
            server.httpd.server_close()
            raise failure
        result = start(server)
        servers.append(server)
        return result

    monkeypatch.setattr(NoGraphServer, "start", boot)
    try:
        return nograph_launcher.run(state_dir)
    finally:
        for server in servers:
            server.close()


@pytest.mark.parametrize("name", [
    "archhub-test.universal.sqlite3", "authority.sqlite3-wal",
    "unified-authority/generations/saved/authority.sqlite3", "authority.sqlite3-shm",
])
def test_nograph_boot_preserves_retired_graph_and_recovery_files(tmp_path, monkeypatch, name):
    # NOGRAPH supersedes the deleted graph migration and owner-retry boot path.
    legacy = tmp_path / name
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(b"unreadable legacy graph or unreconciled recovery")
    assert _headless_launch(tmp_path, monkeypatch) == 0
    assert legacy.read_bytes() == b"unreadable legacy graph or unreconciled recovery"


@pytest.mark.parametrize("failure", [DatabaseOwnerConflict("held"), RuntimeError("boot refused")])
def test_nograph_boot_failure_reaches_the_launcher_notice(tmp_path, monkeypatch, failure):
    with pytest.raises(type(failure), match=str(failure)):
        _headless_launch(tmp_path, monkeypatch, failure)


@pytest.mark.parametrize("answered", [True, False])
def test_held_launcher_port_reports_the_existing_instance_without_a_second_boot(answered):
    messages = []
    outcome = _launcher_names("_held_port_outcome")["_held_port_outcome"](
        12345, lambda: answered, messages.append)
    assert bool(messages) is not answered
    assert ("brought its window to the front" if answered else "no ArchHub window answered") in outcome


def test_excepthook_uses_nonblocking_notice_when_qt_loop_is_running():
    boxes = []
    ns = _launcher_names(
        "_tell_the_person",
        "_qt_event_loop_running",
        "_boot_refusal_message",
        traceback=__import__("traceback"),
        _log_path=Path("launcher.log"),
        _message_box=lambda message, **kwargs: boxes.append((message, kwargs)) or True,
        _qt_app_event_loop_active=lambda: True,
    )

    ns["_tell_the_person"](RuntimeError, RuntimeError("bad boot"), None)

    assert boxes
    assert boxes[0][1].get("blocking") is False


def test_failed_boot_notice_keeps_the_original_error_and_delivery_failure(capsys):
    def unavailable(*args, **kwargs):
        raise OSError("notice unavailable")

    ns = _launcher_names(
        "_tell_the_person", "_boot_refusal_message",
        traceback=__import__("traceback"), _log_path=Path("launcher.log"),
        _qt_event_loop_running=lambda: False, _message_box=unavailable,
    )
    ns["_tell_the_person"](RuntimeError, RuntimeError("saved graph refused"), None)
    output = capsys.readouterr()
    assert "saved graph refused" in output.err
    assert "notice unavailable" in output.out


def test_failed_native_notice_result_is_not_reported_as_delivered(capsys):
    ns = _launcher_names(
        "_tell_the_person", "_boot_refusal_message",
        traceback=__import__("traceback"), _log_path=Path("launcher.log"),
        _qt_event_loop_running=lambda: False, _message_box=lambda *a, **k: False,
    )
    ns["_tell_the_person"](RuntimeError, RuntimeError("saved graph refused"), None)
    output = capsys.readouterr()
    assert "saved graph refused" in output.err
    assert "boot refusal notice was not displayed" in output.out
