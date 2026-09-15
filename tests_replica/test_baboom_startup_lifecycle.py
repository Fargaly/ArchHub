"""Exercise the launcher's real callbacks without starting its server or UI."""
from __future__ import annotations

import ast
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_names(path, names, **bindings):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    selected = [node for node in tree.body if getattr(node, "name", None) in names]
    assert {node.name for node in selected} == set(names)
    module = ast.Module(body=selected, type_ignores=[])
    namespace = dict(bindings)
    exec(compile(module, str(path), "exec"), namespace)
    return namespace


def launcher_names(*names, **bindings):
    if '_finish_application_shutdown' in names:
        # These tests exercise BABOOM/descriptor teardown after the unrelated
        # update/relay owners have quiesced. Supply that real callback's newer
        # dependencies explicitly instead of failing before the target branch.
        bindings.setdefault('cloud_relay', None)
        bindings.setdefault('_update_stop', threading.Event())
        bindings.setdefault('_quiet_update_thread', SimpleNamespace(join=lambda **kw: None, is_alive=lambda: False))
        bindings.setdefault('_restart_after_shutdown', False)
        if not hasattr(bindings['server'], 'application_update'):
            bindings['server'].application_update = SimpleNamespace(close=lambda **kw: True)
    return load_names(ROOT / "launch_archhub_test.py", names, **bindings)


class TransportFailure(RuntimeError):
    pass


class ImmediateWait:
    """Advance retry waits without sleeping; cancellation is still explicit."""
    def __init__(self):
        self.cancelled = False
        self.waits = []

    def is_set(self):
        return self.cancelled

    def set(self):
        self.cancelled = True

    def wait(self, seconds):
        self.waits.append(seconds)
        return self.cancelled


class Host:
    def __init__(self, connect=None):
        self.connect_calls = 0
        self.stop_calls = 0
        self.running = False
        self.on_connect = connect

    def connect(self):
        self.connect_calls += 1
        if self.on_connect:
            self.on_connect(self)

    def stop(self, **kwargs):
        self.stop_calls += 1
        self.running = False


def worker_namespace(monkeypatch, host, *, stop=None, emit=None):
    stop = stop or ImmediateWait()
    prepared, delivered = [], []

    def prepare(*args, **kwargs):
        prepared.append(kwargs)
        return host

    monkeypatch.setitem(sys.modules, "nodelang.baboom_attach", SimpleNamespace(prepare_baboom_host=prepare))
    monkeypatch.setitem(sys.modules, "nodelang.application_machine_transport", SimpleNamespace(MachineTransportError=TransportFailure))
    owner = SimpleNamespace(pending_host=None, ready=SimpleNamespace(emit=emit or delivered.append))
    namespace = launcher_names(
        "_keep_attaching", _baboom_stop=stop, _baboom_attachment=owner,
        server=object(), state_dir=Path("unused"), descriptor_path=Path("unused"),
        machine_key_provider=object(),
    )
    return namespace, stop, prepared, delivered, owner


def test_first_frame_retry_retains_one_prepared_host_and_identity(monkeypatch):
    def busy_first(host):
        if host.connect_calls == 1:
            raise TransportFailure("universal runtime did not respond")

    host = Host(busy_first)
    ns, stop, prepared, delivered, owner = worker_namespace(monkeypatch, host)
    ns["_keep_attaching"]()
    assert len(prepared) == 1
    assert prepared[0]["external_session_id"] == "founder-desktop-baboom"
    assert prepared[0]["cancellation_event"] is stop
    assert host.connect_calls == 2
    assert delivered == [host] and owner.pending_host is host
    assert stop.waits == [0.0, 15.0]


def test_policy_refusal_is_not_retried_under_new_identity(monkeypatch):
    def denied(host):
        raise TransportFailure("runtime device proof challenge is invalid")

    host = Host(denied)
    ns, _, prepared, delivered, _ = worker_namespace(monkeypatch, host)
    ns["_keep_attaching"]()
    assert len(prepared) == host.connect_calls == 1
    assert not delivered and host.stop_calls >= 1


def test_cancellation_during_connect_cleans_host_without_handoff(monkeypatch):
    stop = ImmediateWait()
    host = Host(lambda _: stop.set())
    ns, _, _, delivered, _ = worker_namespace(monkeypatch, host, stop=stop)
    ns["_keep_attaching"]()
    assert not delivered and host.stop_calls >= 1


def test_destroyed_receiver_cleans_undelivered_host(monkeypatch):
    def gone(host):
        raise RuntimeError("receiver destroyed")

    host = Host()
    ns, _, _, _, _ = worker_namespace(monkeypatch, host, emit=gone)
    ns["_keep_attaching"]()
    assert host.stop_calls >= 1


def test_cockpit_uses_late_signed_attachment_without_restarting_relay():
    stop = threading.Event()
    calls = []
    ns = launcher_names("_cockpit_execute", _baboom_stop=stop, baboom_host=None)
    execute = ns["_cockpit_execute"]
    with pytest.raises(RuntimeError, match="no action was performed"):
        execute("run chosen task")
    ns["baboom_host"] = SimpleNamespace(execute_input=lambda text: calls.append(text) or {"signed": True})
    assert execute("run chosen task") == {"signed": True}
    assert calls == ["run chosen task"]
    stop.set()
    with pytest.raises(RuntimeError, match="closing"):
        execute("another task")
    assert len(calls) == 1


def test_cockpit_reads_switch_to_same_signed_host_after_attachment():
    calls = []
    host = SimpleNamespace(respond_input=lambda text: calls.append(text) or {"answer": text})
    ns = launcher_names("_cockpit_respond", _baboom_stop=threading.Event(), baboom_host=host)
    assert ns["_cockpit_respond"]("what can you do?") == {"answer": "what can you do?"}
    assert calls == ["what can you do?"]


def test_cancel_after_acquiring_mutation_lock_prevents_custody_writes():
    stop = threading.Event()
    released = []

    class Lock:
        def acquire(self, **kwargs):
            stop.set()
            return True

        def release(self):
            released.append(True)

    ns = load_names(
        ROOT / "nodelang/baboom_attach.py", ["prepare_baboom_host"],
        Path=Path, MachineTransportError=TransportFailure,
        _machine_device_key=lambda _: pytest.fail("custody write after cancellation"),
    )
    with pytest.raises(TransportFailure, match="cancelled"):
        ns["prepare_baboom_host"](
            SimpleNamespace(mutation_lock=Lock()), state_dir=Path("unused"),
            descriptor_path=Path("unused"), key_provider=None, cancellation_event=stop,
        )
    assert released == [True]


def test_duplicate_start_callback_keeps_one_worker():
    made = []
    owner = SimpleNamespace(worker=None)

    def worker(**kwargs):
        item = SimpleNamespace(start=lambda: made.append(kwargs))
        return item

    ns = launcher_names(
        "_start_baboom_attachment", _baboom_stop=threading.Event(),
        _baboom_attachment=owner, threading=SimpleNamespace(Thread=worker),
        _keep_attaching=lambda: None,
    )
    ns["_start_baboom_attachment"]()
    first = owner.worker
    ns["_start_baboom_attachment"]()
    assert owner.worker is first and len(made) == 1


def test_incomplete_shutdown_retains_descriptor_and_never_closes_live_journal(capsys):
    actions = []

    def blocked():
        raise RuntimeError("attachment still connecting")

    ns = launcher_names(
        "_finish_application_shutdown", _baboom_stop=threading.Event(),
        _baboom_attachment=SimpleNamespace(shutdown=blocked),
        server=SimpleNamespace(close=lambda: actions.append("close")),
        _active_runtime=SimpleNamespace(unlink=lambda **kw: actions.append("unlink")),
        _previous_active=None,
    )
    assert ns["_finish_application_shutdown"]() is False
    assert actions == []
    assert "INCOMPLETE" in capsys.readouterr().out


def test_successful_shutdown_quiesces_before_restoring_descriptor_and_closing():
    actions = []
    ns = launcher_names(
        "_finish_application_shutdown", _baboom_stop=threading.Event(),
        _baboom_attachment=SimpleNamespace(shutdown=lambda: actions.append("quiesce")),
        server=SimpleNamespace(close=lambda: actions.append("close")),
        _active_runtime=SimpleNamespace(read_bytes=lambda: b"this runtime", write_bytes=lambda data: actions.append(data)),
        _announced_active=b"this runtime",
        _previous_active=b"prior descriptor",
    )
    assert ns["_finish_application_shutdown"]() is True
    assert actions == ["quiesce", "close", b"prior descriptor"]


@pytest.mark.parametrize("announced,current", [(None, b"founder runtime"), (b"this runtime", b"new selection")])
def test_shutdown_preserves_an_unowned_machine_runtime_binding(announced, current):
    actions = []
    ns = launcher_names(
        "_finish_application_shutdown", _baboom_stop=threading.Event(),
        _baboom_attachment=SimpleNamespace(shutdown=lambda: None),
        server=SimpleNamespace(close=lambda: actions.append("close")),
        _active_runtime=SimpleNamespace(read_bytes=lambda: current,
                                       unlink=lambda **kw: pytest.fail("unowned descriptor removed"),
                                       write_bytes=lambda raw: pytest.fail("unowned descriptor overwritten")),
        _previous_active=None, _announced_active=announced,
    )
    assert ns["_finish_application_shutdown"]() is True
    assert actions == ["close"]


def test_descriptor_restore_failure_is_not_reported_as_clean_shutdown(capsys):
    actions = []

    def cannot_restore(raw):
        raise PermissionError("descriptor locked")

    ns = launcher_names(
        "_finish_application_shutdown", _baboom_stop=threading.Event(),
        _baboom_attachment=SimpleNamespace(shutdown=lambda: None),
        server=SimpleNamespace(close=lambda: actions.append("close")),
        _active_runtime=SimpleNamespace(read_bytes=lambda: b"this runtime", write_bytes=cannot_restore),
        _previous_active=b"prior runtime", _announced_active=b"this runtime",
    )
    assert ns["_finish_application_shutdown"]() is False
    assert actions == ["close"] and "descriptor restore" in capsys.readouterr().out
