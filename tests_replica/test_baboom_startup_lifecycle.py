"""Exercise the launcher's real callbacks without starting its server or UI."""
from __future__ import annotations

import ast
from pathlib import Path
import sys
import json
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


class Denied(TransportFailure):
    """Stand-in for MachineResponseError: the runtime answered and said no."""


class NotEnrolled(TransportFailure):
    """Stand-in for MachineContinuationNotEnrolled: an owner-held refusal receipt."""


class OutcomeUnknown(TransportFailure):
    """Stand-in for MachineEffectOutcomeUnknown: effects are not known."""


class NotSent(TransportFailure):
    """Stand-in for MachineNotSent: the request never left."""


class NoResponse(TransportFailure):
    """Stand-in for MachineNoResponse: sent, no answer (retried on the first attach frame only)."""


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
    def __init__(self, connect=None, *, enrollment_sent=False):
        self.enrollment_sent = enrollment_sent
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


def worker_namespace(monkeypatch, host, *, stop=None, emit=None, startup=lambda: "on", real_transport=False):
    stop = stop or ImmediateWait()
    prepared, delivered = [], []

    def prepare(*args, **kwargs):
        prepared.append(kwargs)
        return host

    monkeypatch.setitem(sys.modules, "nodelang.baboom_attach", SimpleNamespace(prepare_baboom_host=prepare))
    if not real_transport:
        monkeypatch.setitem(sys.modules, "nodelang.application_machine_transport", SimpleNamespace(
            MachineTransportError=TransportFailure, MachineResponseError=Denied,
            MachineContinuationNotEnrolled=NotEnrolled, MachineEffectOutcomeUnknown=OutcomeUnknown,
            MachineNotSent=NotSent, MachineNoResponse=NoResponse))
    owner = SimpleNamespace(pending_host=None, ready=SimpleNamespace(emit=emit or delivered.append))
    namespace = launcher_names(
        "_keep_attaching", _baboom_stop=stop, _baboom_attachment=owner,
        server=object(), state_dir=Path("unused"), descriptor_path=Path("unused"),
        machine_key_provider=object(),
        # The persistent startup gate adds these free names to _keep_attaching.
        _baboom_startup_choice=startup, _baboom_off_reason=None,
    )
    return namespace, stop, prepared, delivered, owner


def test_first_frame_retry_retains_one_prepared_host_and_identity(monkeypatch):
    def busy_first(host):
        if host.connect_calls == 1:
            # The runtime was not reachable yet: nothing was sent.
            raise NotSent("universal runtime pipe is unavailable")

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
    # The runtime's authenticated refusal arrives as MachineResponseError.
    def denied(host):
        raise Denied("runtime device proof challenge is invalid")

    host = Host(denied)
    ns, _, prepared, delivered, _ = worker_namespace(monkeypatch, host)
    ns["_keep_attaching"]()
    assert len(prepared) == host.connect_calls == 1
    assert not delivered and host.stop_calls >= 1


@pytest.mark.parametrize("final", [NotEnrolled, OutcomeUnknown, TransportFailure])
def test_a_refusal_receipt_or_unknown_effect_is_final(monkeypatch, final):
    def refused(host):
        raise final("refused")

    host = Host(refused)
    ns, _, _, delivered, _ = worker_namespace(monkeypatch, host)
    ns["_keep_attaching"]()
    assert host.connect_calls == 1 and not delivered and host.stop_calls >= 1


def test_a_transport_failure_is_retried_until_the_runtime_attaches(monkeypatch):
    # The log showed "attachment refused (attempt 1, MachineTransportError)"
    # launch after launch: one unlisted pipe message ended BABOOM's start.
    def flaky(host):
        if host.connect_calls <= 3:
            raise NotSent("universal runtime pipe is unavailable")

    host = Host(flaky)
    ns, stop, prepared, delivered, _ = worker_namespace(monkeypatch, host)
    ns["_keep_attaching"]()
    assert len(prepared) == 1, "one prepared identity is retried, never a new one"
    assert host.connect_calls == 4 and delivered == [host]
    assert stop.waits == [0.0, 15.0, 15.0, 15.0]


def test_a_transport_failure_stops_at_the_forty_attempt_budget(monkeypatch):
    def down(host):
        raise NotSent("universal runtime is not active")

    host = Host(down)
    ns, stop, prepared, delivered, _ = worker_namespace(monkeypatch, host)
    ns["_keep_attaching"]()
    assert host.connect_calls == 40 and len(prepared) == 1
    assert stop.waits == [0.0] + [15.0] * 39
    assert not delivered and host.stop_calls >= 1


def test_no_answer_after_the_enrollment_was_sent_is_final(monkeypatch):
    """The enrollment left and its answer (the session token) was lost: asking
    again could only be refused "already bound", so BABOOM stops at once."""
    def lost_token(host):
        raise NoResponse("universal runtime did not respond")

    host = Host(lost_token, enrollment_sent=True)
    ns, stop, prepared, delivered, _ = worker_namespace(monkeypatch, host)
    ns["_keep_attaching"]()
    assert len(prepared) == 1 and host.connect_calls == 1
    assert not delivered and host.stop_calls >= 1 and stop.waits == [0.0]


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
    ns = launcher_names("_cockpit_execute", _baboom_stop=stop, baboom_host=None, _baboom_off_reason=None)
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
        _machine_pointer=None,
    )
    assert ns["_finish_application_shutdown"]() is False
    assert actions == []
    assert "INCOMPLETE" in capsys.readouterr().out


def _shutdown(tmp_path, actions, named, *, pointer=True):
    machine = tmp_path / "active-universal-runtime.json"
    machine.write_text('{"format": "archhub.universal-runtime-pointer", "runtime_id": "%s"}' % named)
    before = machine.read_bytes()
    ns = launcher_names(
        "_finish_application_shutdown", "_announcement_at_exit", _baboom_stop=threading.Event(),
        _baboom_attachment=SimpleNamespace(shutdown=lambda: actions.append("quiesce")),
        server=SimpleNamespace(close=lambda: actions.append("close"),
                               machine_transport=SimpleNamespace(runtime_id="this")),
        _machine_pointer=machine if pointer else None,
    )
    return ns, machine, before


def test_successful_shutdown_quiesces_then_closes_and_restores_nothing(tmp_path, capsys):
    actions = []
    ns, machine, before = _shutdown(tmp_path, actions, "this")
    assert ns["_finish_application_shutdown"]() is True
    assert actions == ["quiesce", "close"]
    # The pointer is not rewritten at exit: it names this runtime's own record,
    # which close() left "stopped". No older record is put back.
    assert machine.read_bytes() == before
    assert "announcement names this runtime, now stopped" in capsys.readouterr().out


def test_shutdown_leaves_another_runtimes_announcement_untouched(tmp_path, capsys):
    actions = []
    ns, machine, before = _shutdown(tmp_path, actions, "newer")
    assert ns["_finish_application_shutdown"]() is True
    assert actions == ["quiesce", "close"] and machine.read_bytes() == before
    assert "announcement names another runtime (left)" in capsys.readouterr().out


def test_a_verification_run_never_touches_or_reports_the_machine_announcement(tmp_path, capsys):
    actions = []
    ns, machine, before = _shutdown(tmp_path, actions, "founder", pointer=False)
    assert ns["_finish_application_shutdown"]() is True
    assert machine.read_bytes() == before and "announcement" not in capsys.readouterr().out


# Persistent startup setting: Studio Settings -> graph -> next launch.
# RED-first: every case below fails on the c6e2689 launcher, which prepares
# BABOOM unconditionally and defines no _baboom_startup_choice.

OFF_REASON = "BABOOM is turned off in Settings; no action was performed."
UNREADABLE_REASON = (
    "BABOOM did not start because its Settings value is unreadable; "
    "no action was performed."
)


def test_startup_setting_off_prepares_no_host_and_records_why(monkeypatch, capsys):
    host = Host()
    ns, stop, prepared, delivered, owner = worker_namespace(
        monkeypatch, host, startup=lambda: "off"
    )
    ns["_keep_attaching"]()
    out = capsys.readouterr().out
    assert prepared == [] and delivered == [] and host.connect_calls == 0
    assert owner.pending_host is None
    assert stop.waits == [] and not stop.is_set(), "off is not a shutdown"
    assert ns["_baboom_off_reason"] == OFF_REASON
    assert out.count("  BABOOM     : off (Settings); not started this launch") == 1


def test_startup_setting_on_is_read_before_the_host_is_prepared(monkeypatch):
    order = []

    def on():
        order.append("startup")
        return "on"

    host = Host(lambda _: order.append("connect"))
    ns, _, prepared, delivered, _ = worker_namespace(monkeypatch, host, startup=on)
    ns["_keep_attaching"]()
    assert order == ["startup", "connect"]
    assert len(prepared) == 1 and delivered == [host]
    assert ns["_baboom_off_reason"] is None


def test_unreadable_startup_setting_fails_closed_before_prepare(monkeypatch, capsys):
    from nodelang.universal_cell import InvalidCell

    def unreadable():
        raise InvalidCell("BABOOM startup binding drifted")

    host = Host()
    ns, stop, prepared, delivered, _ = worker_namespace(
        monkeypatch, host, startup=unreadable
    )
    ns["_keep_attaching"]()
    out = capsys.readouterr().out
    assert prepared == [] and delivered == [] and host.connect_calls == 0
    assert not stop.is_set()
    assert ns["_baboom_off_reason"] == UNREADABLE_REASON
    assert "  BABOOM     : not started; startup setting unreadable (InvalidCell)" in out


def test_startup_value_outside_on_off_is_unreadable_never_on(monkeypatch, capsys):
    host = Host()
    ns, _, prepared, _, _ = worker_namespace(monkeypatch, host, startup=lambda: "enabled")
    ns["_keep_attaching"]()
    assert prepared == [] and host.connect_calls == 0
    assert ns["_baboom_off_reason"] == UNREADABLE_REASON
    assert "startup setting unreadable (ValueError)" in capsys.readouterr().out


def test_cancelled_startup_read_returns_quietly_without_prepare(monkeypatch, capsys):
    host = Host()
    ns, _, prepared, delivered, _ = worker_namespace(monkeypatch, host, startup=lambda: None)
    ns["_keep_attaching"]()
    assert prepared == [] and delivered == [] and host.connect_calls == 0
    assert ns["_baboom_off_reason"] is None
    assert "BABOOM" not in capsys.readouterr().out


def startup_choice(monkeypatch, server, stop, reader):
    monkeypatch.setitem(
        sys.modules, "nodelang.universal_application",
        SimpleNamespace(read_universal_baboom_startup=reader),
    )
    return launcher_names(
        "_baboom_startup_choice", server=server, _baboom_stop=stop,
    )["_baboom_startup_choice"]


def test_startup_choice_reads_the_graph_under_the_mutation_lock(monkeypatch):
    events, snapshot, registry = [], object(), object()

    class Lock:
        def acquire(self, *args, **kwargs):
            events.append("acquire")
            return True

        def release(self):
            events.append("release")

    def reader(read_snapshot, read_registry):
        assert read_snapshot is snapshot and read_registry is registry
        events.append("read")
        return {"value": "off", "source": "graph"}

    server = SimpleNamespace(
        mutation_lock=Lock(), universal_registry=registry,
        universal_store=SimpleNamespace(snapshot=lambda: events.append("snapshot") or snapshot),
    )
    choose = startup_choice(monkeypatch, server, threading.Event(), reader)
    assert choose() == "off"
    assert events == ["acquire", "snapshot", "read", "release"]


def test_startup_choice_releases_the_lock_when_the_setting_is_unreadable(monkeypatch):
    released = []

    class Lock:
        def acquire(self, *args, **kwargs):
            return True

        def release(self):
            released.append(True)

    def reader(*_):
        raise ValueError("BABOOM startup value is invalid")

    server = SimpleNamespace(
        mutation_lock=Lock(), universal_registry=object(),
        universal_store=SimpleNamespace(snapshot=object),
    )
    choose = startup_choice(monkeypatch, server, threading.Event(), reader)
    with pytest.raises(ValueError, match="value is invalid"):
        choose()
    assert released == [True]


def test_startup_choice_lock_wait_is_cancellable_and_never_reads(monkeypatch):
    stop, attempts, released = threading.Event(), [], []

    class Busy:
        def acquire(self, *args, **kwargs):
            attempts.append(kwargs.get("timeout", args[1] if len(args) > 1 else None))
            if len(attempts) == 2:
                stop.set()
            return False

        def release(self):
            released.append(True)

    server = SimpleNamespace(
        mutation_lock=Busy(), universal_registry=object(),
        universal_store=SimpleNamespace(snapshot=lambda: pytest.fail("graph read after cancellation")),
    )
    choose = startup_choice(
        monkeypatch, server, stop,
        lambda *_: pytest.fail("startup setting read after cancellation"),
    )
    assert choose() is None
    assert len(attempts) == 2 and released == []
    # Bounded waits, so GUI shutdown can always cancel the worker.
    assert all(isinstance(wait, (int, float)) and 0 < wait <= 0.1 for wait in attempts)


def test_startup_choice_cancelled_after_acquire_releases_without_reading(monkeypatch):
    stop, released = threading.Event(), []

    class Lock:
        def acquire(self, *args, **kwargs):
            stop.set()
            return True

        def release(self):
            released.append(True)

    server = SimpleNamespace(
        mutation_lock=Lock(), universal_registry=object(),
        universal_store=SimpleNamespace(snapshot=lambda: pytest.fail("graph read after cancellation")),
    )
    choose = startup_choice(
        monkeypatch, server, stop,
        lambda *_: pytest.fail("startup setting read after cancellation"),
    )
    assert choose() is None
    assert released == [True]


@pytest.mark.parametrize("reason,named", [
    (OFF_REASON, "turned off in Settings"),
    (UNREADABLE_REASON, "Settings value is unreadable"),
])
def test_cockpit_execute_names_the_startup_setting_instead_of_retry(reason, named):
    stop = threading.Event()
    ns = launcher_names(
        "_cockpit_execute", _baboom_stop=stop, baboom_host=None, _baboom_off_reason=reason,
    )
    with pytest.raises(RuntimeError, match=named) as refused:
        ns["_cockpit_execute"]("run chosen task")
    assert "no action was performed" in str(refused.value)
    assert "Retry when it connects" not in str(refused.value)
    stop.set()
    with pytest.raises(RuntimeError, match="closing"):
        ns["_cockpit_execute"]("another task")


# -- the REAL client's error mapping, through the real launcher loop ---------

def _real_client_error(monkeypatch, scenario):
    """What nodelang.application_machine_transport.UniversalRuntimeClient raises."""
    import json
    from nodelang import application_machine_transport as amt

    descriptor = SimpleNamespace(status="starting" if scenario == "not-active" else "active",
                                 runtime_id="a" * 32, pipe="court-pipe", key_id="k", key_version=1)

    class Connection:
        def send_bytes(self, raw):
            self.sent = json.loads(raw)

        def poll(self, _seconds):
            path = self.sent["path"]
            return not (scenario == "did-not-respond"
                        or (scenario == "challenge-no-answer" and path.endswith("-challenge"))
                        or (scenario == "enrollment-no-answer" and path == "/api/universal/agent-session"))

        def recv_bytes(self, _limit):
            if scenario == "pipe-closed-mid-answer":
                raise EOFError
            answer = {"ok": True, "runtime_id": "a" * 32, "request_id": self.sent["request_id"],
                      "result": {}}
            if scenario == "unknown-outcome":
                answer.update(ok=False, effect_outcome="unknown", error="commit outcome unknown")
            elif scenario == "denied" and self.sent["path"] == "/api/universal/agent-session":
                # The real server's refusal of a second enrollment
                # (application_server.py, _machine_agent_identity_is_currently_bound).
                answer.update(ok=False, error="runtime Agent Session identity is already bound; renew it instead")
            elif scenario == "binding-failed":
                answer["request_id"] = "0" * 32
            elif scenario == "status-invalid":
                answer["ok"] = "maybe"
            elif scenario == "result-invalid":
                answer["result"] = []
            return json.dumps(answer).encode("utf-8")

        def close(self):
            pass

    def connect(*_args, **_kwargs):
        if scenario == "pipe-unavailable":
            raise OSError("no pipe")
        return Connection()

    monkeypatch.setattr(amt, "_read_descriptor", lambda *_a: descriptor)
    monkeypatch.setattr(amt, "Client", connect)
    # HEAD moved owner verification into verify_active_runtime (full process and
    # graph-generation identity), after v3.4 was written. This court exercises
    # response classification, not owner verification (that is
    # test_runtime_owner_resolution.py), so keep the precondition minimal: an
    # active descriptor proceeds, a non-active one refuses -- which is exactly the
    # distinction the bounded-lock correction answers (not-active -> MachineNotSent).
    def _verify_active(desc, **_kwargs):
        if desc.status != "active":
            raise amt.RuntimeResolutionError(desc.status or "stopped", "runtime owner is not active")
        return desc
    monkeypatch.setattr(amt, "verify_active_runtime", _verify_active)
    client = amt.UniversalRuntimeClient(
        Path("unused"), SimpleNamespace(resolve=lambda *_a: SimpleNamespace(secret=b"k" * 32)))
    if scenario == "already-bound":
        client.agent_session_root = "app:agent-session:runtime:" + "b" * 32
    if scenario == "continuation-retained":
        client._continuation_request = {"runtime": "baboom"}
    if scenario == "owner-changed":
        client._pinned_runtime_descriptor = SimpleNamespace(status="active", runtime_id="e" * 32)
    if scenario == "owner-released":
        client._agent_session_access = "released"
    if scenario == "did-not-respond":
        client.enrollment_sent = True  # a presence request is only ever sent after enrollment
    body, wait = {}, None
    if scenario == "size-limit":
        body = {"pad": "x" * (amt._MAX_MESSAGE_BYTES + 1)}
    if scenario == "timeout-invalid":
        wait = -1
    if scenario == "did-not-respond":
        wait = 0.05
    with pytest.raises(amt.MachineTransportError) as raised:
        if scenario in {"enrollment-invalid", "already-bound", "continuation-retained"}:
            client.bind_agent_session(runtime="baboom", external_session_id="founder-desktop-baboom")
        elif scenario in {"denied", "challenge-no-answer", "enrollment-no-answer"}:
            client.bind_agent_session(runtime="baboom", external_session_id="founder-desktop-baboom",
                                      device_credential_provider=lambda challenge: {"proof": "court"})
        elif scenario == "device-credential-invalid":
            client.bind_agent_session(runtime="baboom", external_session_id="founder-desktop-baboom",
                                      device_credential_provider=lambda challenge: "not a credential")
        else:
            client.request("POST", "/api/universal/runtime-presence", body,
                           response_timeout_seconds=wait)
    return raised.value, client.enrollment_sent


@pytest.mark.parametrize("scenario,final", [
    ("unknown-outcome", True),
    ("denied", True),
    ("binding-failed", True),
    ("status-invalid", True),
    ("result-invalid", True),
    ("enrollment-invalid", True),
    ("already-bound", True),
    ("continuation-retained", True),
    ("pipe-closed-mid-answer", True),
    ("did-not-respond", True),
    ("challenge-no-answer", False),
    ("enrollment-no-answer", True),
    ("owner-changed", True),
    ("owner-released", True),
    ("size-limit", True),
    ("device-credential-invalid", True),
    ("timeout-invalid", True),
    ("pipe-unavailable", False),
    ("not-active", False),
])
def test_the_real_client_errors_are_final_or_retried(monkeypatch, scenario, final):
    error, enrollment_sent = _real_client_error(monkeypatch, scenario)

    def fails(host):
        raise error

    host = Host(fails, enrollment_sent=enrollment_sent)
    ns, _, prepared, delivered, _ = worker_namespace(monkeypatch, host, real_transport=True)
    ns["_keep_attaching"]()
    assert len(prepared) == 1 and not delivered
    assert host.connect_calls == (1 if final else 40), (scenario, type(error).__name__, str(error))
