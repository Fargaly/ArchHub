"""Courts for deferred Codex binding: identity from transport _meta.threadId only,
plus the retained/latched binding lifecycle (per-binding Stop observer, lease
renewal, accurate release, partial/uncertain build retained not rebuilt), and the
disabled dynamic Work-task surface.

The native session/control/supervisor are injected fakes so routing, refusal,
recovery and lifecycle are exercised deterministically without an installed
descriptor, DPAPI custody or a real Stop host. Real binding, per-binding Stop and
real-client provenance are proven on the hidden-desktop rig and the real capture.
"""
import contextlib
import json
import os
import types

import pytest

from mcp.server.lowlevel.server import request_ctx
from mcp.types import RequestParams

from nodelang.application_machine_transport import MachineTransportError
from nodelang import deferred_codex_binding as dcb


class FakeIdentity:
    def __init__(self, runtime, external):
        self.runtime = runtime
        self.external_session_id = external


class FakeClient:
    def __init__(self, owner):
        self.owner = owner

    @property
    def agent_session_root(self):
        return "app:agent-session:runtime:" + (self.owner._identity.external_session_id or "")

    def current_work_assignment(self):
        return {"assignment_for": self.owner._identity.external_session_id}


class FakeOwner:
    def __init__(self, environment, close_mode="confirmed", fail_connect=False, fail_keeper=False):
        self._identity = FakeIdentity(
            environment.get("ARCHHUB_AGENT_RUNTIME"),
            environment.get("ARCHHUB_EXTERNAL_SESSION_ID"))
        self.connect_calls = 0
        self.lease_started = 0
        self.close_calls = 0
        self._close_mode = close_mode
        self._fail_connect = fail_connect
        self._fail_keeper = fail_keeper
        self._stop_supervisor = None
        self.recovered = 0
        self._bound = False

    def connect(self):
        self.connect_calls += 1
        if self._fail_connect:
            raise MachineTransportError("enrollment outcome unknown")
        self._bound = True
        return FakeClient(self)

    def require_client(self):
        if not self._bound:
            raise MachineTransportError("owner is not bound")
        return FakeClient(self)

    def start_lease_keeper(self):
        if self._fail_keeper:
            raise RuntimeError("keeper boom")
        self.lease_started += 1

    def close(self):
        self.close_calls += 1
        tid = self._identity.external_session_id
        if self._close_mode == "retained":
            return {"released": False, "retained": True, "agent_session": tid}
        if self._close_mode == "raise":
            raise MachineTransportError("release uncertain")
        return {"released": True, "agent_session": tid}

    def recover_connection(self, **kwargs):
        self.recovered += 1
        self._bound = True  # same owner reconciled; no new owner, no re-enroll
        return {"state": "recovered", "agent_session": self._identity.external_session_id}

    def owner_status(self):
        return {"state": "bound" if self._bound else "uncertain",
                "recovery_required": not self._bound,
                "runtime": self._identity.runtime,
                "external_session_id": self._identity.external_session_id}


class FakeControl:
    def __init__(self, owner, client):
        self.owner = owner
        self.client = client
        self.calls = []

    def call(self, method, parameters=None, **kwargs):
        self.calls.append((method, parameters))
        return {"ok": True, "thread": self.owner._identity.external_session_id, "method": method}

    @contextlib.contextmanager
    def bound_client(self):
        yield FakeClient(self.owner)


class FakeSupervisor:
    def __init__(self, owner, clean=True):
        self.owner = owner
        self.closed = False
        self.close_calls = 0
        self._clean = clean

    def status(self):
        return {"state": "absent" if self.closed else "ready", "reason": None}

    def close(self):
        self.close_calls += 1
        self.closed = self._clean
        return self._clean


def _runtime(*, close_mode="confirmed", fail_control=False, fail_control_once=False,
             fail_connect=False, fail_keeper=False, observer_clean=True):
    built, sups = [], []
    control_state = {"n": 0}

    def session_factory(environment):
        owner = FakeOwner(environment, close_mode=close_mode,
                          fail_connect=fail_connect, fail_keeper=fail_keeper)
        built.append(owner)
        return owner

    def control_factory(owner, client):
        if fail_control or (fail_control_once and control_state["n"] == 0):
            control_state["n"] += 1
            raise RuntimeError("control init boom")
        return FakeControl(owner, client)

    def supervisor_factory(owner):
        supervisor = FakeSupervisor(owner, clean=observer_clean)
        sups.append(supervisor)
        try:
            owner._stop_supervisor = supervisor
        except Exception:
            pass
        return supervisor

    rt = dcb.DeferredCodexRuntime(
        {"ARCHHUB_COORDINATION_VENDOR": "codex"},
        session_factory=session_factory, control_factory=control_factory,
        supervisor_factory=supervisor_factory)
    rt._built, rt._sups = built, sups
    return rt


def _set_meta(**extra):
    meta = RequestParams.Meta(**extra) if extra else RequestParams.Meta()
    return request_ctx.set(types.SimpleNamespace(meta=meta))


@contextlib.contextmanager
def _thread(tid):
    token = _set_meta(threadId=tid)
    try:
        yield
    finally:
        request_ctx.reset(token)


# ---- provenance: threadId only from transport _meta ----

def test_thread_id_from_request_meta_extra():
    with _thread("01a09f43-220e-79e3-90e0-c35f5cdbaa5c"):
        assert dcb.current_codex_thread_id() == "01a09f43-220e-79e3-90e0-c35f5cdbaa5c"


def test_thread_id_ignores_item_id_and_session_id():
    token = _set_meta(threadId="T-thread", itemId="I-item", sessionId="S-session", progressToken=0)
    try:
        assert dcb.current_codex_thread_id() == "T-thread"
    finally:
        request_ctx.reset(token)


def test_no_active_request_is_refused():
    with pytest.raises(MachineTransportError):
        dcb.current_codex_thread_id()


def test_missing_thread_id_refused_with_zero_binds():
    rt = _runtime()
    token = _set_meta(progressToken=0)
    try:
        with pytest.raises(MachineTransportError):
            rt.current()
    finally:
        request_ctx.reset(token)
    assert rt.bound_thread_ids() == ()


def test_empty_thread_id_refused():
    token = _set_meta(threadId="   ")
    try:
        with pytest.raises(MachineTransportError):
            dcb.current_codex_thread_id()
    finally:
        request_ctx.reset(token)


def test_thread_id_only_in_tool_args_never_binds():
    rt = _runtime()

    def tool(threadId=None, **kwargs):
        return rt.current()

    token = _set_meta()
    try:
        with pytest.raises(MachineTransportError):
            tool(threadId="A-forged-in-args")
    finally:
        request_ctx.reset(token)
    assert rt.bound_thread_ids() == ()


# ---- per-thread isolation ----

def test_two_threads_bind_two_distinct_sessions():
    rt = _runtime()
    with _thread("A"):
        a = rt.current()
    with _thread("B"):
        b = rt.current()
    assert a.owner is not b.owner and a.control is not b.control
    assert a.owner._identity.external_session_id == "A"
    assert b.owner._identity.external_session_id == "B"
    assert set(rt.bound_thread_ids()) == {"A", "B"}


def test_same_thread_reuses_its_binding():
    rt = _runtime()
    first = None
    for _ in range(3):
        with _thread("A"):
            binding = rt.current()
        first = first or binding.owner
        assert binding.owner is first
    assert first.connect_calls == 1
    assert len(rt._built) == 1


def test_later_thread_never_acts_under_earlier_binding():
    rt = _runtime()
    with _thread("A"):
        owner_a = rt.current().owner
    with _thread("C"):
        owner_c = rt.current().owner
    assert owner_c is not owner_a and owner_c._identity.external_session_id == "C"
    assert rt.bundle_for("A").owner is owner_a


# ---- no global / env injection ----

def test_binding_does_not_mutate_process_environment():
    before = dict(os.environ)
    rt = _runtime()
    with _thread("A"):
        rt.current()
    assert "ARCHHUB_EXTERNAL_SESSION_ID" not in os.environ
    assert dict(os.environ) == before


def test_identity_resolves_to_codex_and_that_thread():
    rt = _runtime()
    with _thread("01a0-xyz"):
        owner = rt.current().owner
    assert owner._identity.runtime == "codex"
    assert owner._identity.external_session_id == "01a0-xyz"


# ---- deferred selection + serve-unbound ----

def test_codex_without_thread_env_selects_deferred_router():
    sentinel = object()
    owner = dcb.owner_for_environment(
        {"ARCHHUB_COORDINATION_VENDOR": "codex"},
        session_factory=lambda environment: sentinel)
    assert isinstance(owner, dcb.RoutingCodexOwner) and owner.is_deferred_router is True


def test_router_binds_nothing_until_first_call():
    rt = _runtime()
    owner = dcb.RoutingCodexOwner(rt)
    assert rt.bound_thread_ids() == ()
    status = owner.owner_status()
    assert status["state"] == "deferred" and status["agent_session"] is None
    with _thread("A"):
        assert owner.control().call("register_session")["thread"] == "A"
    assert rt.bound_thread_ids() == ("A",)


@pytest.mark.parametrize("env", [
    {"ARCHHUB_COORDINATION_VENDOR": "codex", "CODEX_THREAD_ID": "has-thread"},
    {"ARCHHUB_COORDINATION_VENDOR": "claude", "CLAUDE_CODE_SESSION_ID": "c1"},
    {"ARCHHUB_COORDINATION_VENDOR": "gemini", "GEMINI_SESSION_ID": "g1"},
    {"ARCHHUB_COORDINATION_VENDOR": "opencode", "OPENCODE_SESSION_ID": "ses_x"},
])
def test_existing_runtimes_are_not_deferred(env):
    assert dcb.is_deferred_codex_environment(env) is False
    sentinel = object()
    assert dcb.owner_for_environment(env, session_factory=lambda environment: sentinel) is sentinel


def test_routing_control_is_an_installed_workshop_client():
    from nodelang.installed_workshop_coordination import InstalledWorkshopCoordinationClient
    assert isinstance(dcb.RoutingCodexControl(_runtime()), InstalledWorkshopCoordinationClient)


# ---- per-binding lease renewal + Stop observer ----

def test_lease_keeper_starts_once_per_binding():
    rt = _runtime()
    for _ in range(2):
        with _thread("A"):
            owner = rt.current().owner
    assert owner.lease_started == 1


def test_each_binding_gets_its_own_stop_supervisor():
    rt = _runtime()
    with _thread("A"):
        a = rt.current()
    with _thread("B"):
        b = rt.current()
    assert a.supervisor is not None and b.supervisor is not None and a.supervisor is not b.supervisor
    assert a.owner._stop_supervisor is a.supervisor
    assert len(rt._sups) == 2


# ---- accurate release ----

def test_close_drops_bundle_only_on_confirmed_release_with_clean_observer():
    rt = _runtime(close_mode="confirmed", observer_clean=True)
    with _thread("A"):
        binding = rt.current()
    result = rt.close()
    assert result["released"] == 1 and result["retained"] == []
    assert result["outcomes"]["A"]["state"] == "released"
    assert binding.owner.close_calls == 1 and binding.supervisor.close_calls == 1
    assert rt.bound_thread_ids() == ()


def test_close_keeps_bundle_on_uncertain_release():
    rt = _runtime(close_mode="retained")
    with _thread("A"):
        owner = rt.current().owner
    result = rt.close()
    assert result["released"] == 0 and result["outcomes"]["A"]["state"] == "retained"
    assert result["retained"] == ["A"]
    assert rt.bound_thread_ids() == ("A",)
    assert owner.close_calls == 1  # attempted once, not replayed


def test_close_keeps_bundle_when_release_raises():
    rt = _runtime(close_mode="raise")
    with _thread("A"):
        rt.current()
    result = rt.close()
    assert result["released"] == 0 and result["outcomes"]["A"]["state"] == "error"
    assert rt.bound_thread_ids() == ("A",)


def test_close_keeps_released_bundle_when_observer_cleanup_unclean():
    # Ping #6: a confirmed release with an unclean Stop observer keeps the cleanup
    # obligation; the bundle is NOT dropped until the observer is confirmed stopped.
    rt = _runtime(close_mode="confirmed", observer_clean=False)
    with _thread("A"):
        rt.current()
    result = rt.close()
    assert result["released"] == 0
    assert result["outcomes"]["A"]["state"] == "released_observer_unclean"
    assert rt.bound_thread_ids() == ("A",)


# ---- partial/uncertain build is RETAINED and latched, never rebuilt (Ping A, B) ----

def test_connect_failure_is_retained_latched_and_not_rebuilt():
    # Ping (B): owner.connect raises with an unknown enrollment outcome. The owner
    # is retained and latched; a second governed call refuses and makes NO 2nd owner
    # or 2nd connect, so connect's attaching/uncertain no-retry guard stands.
    rt = _runtime(fail_connect=True)
    with _thread("A"):
        with pytest.raises(MachineTransportError):
            rt.current()
        # retained + latched
        assert rt.bound_thread_ids() == ("A",)
        assert rt.latched_threads() == ("A",)
        # a second governed call refuses; it does not rebuild
        with pytest.raises(MachineTransportError):
            rt.current()
    assert len(rt._built) == 1
    assert rt._built[0].connect_calls == 1
    assert rt._built[0].close_calls == 0  # never auto-closed


def test_control_failure_after_connect_is_retained_not_closed_or_rebuilt():
    # Ping (A): control init raises after a successful connect and owner.close would
    # return retained. v4 wrongly uncached it (via _release_quietly), so a 2nd call
    # built a 2nd owner. v5 retains + latches the connected owner; no auto-close, no
    # rebuild; the 2nd governed call refuses.
    rt = _runtime(fail_control=True, close_mode="retained")
    with _thread("A"):
        with pytest.raises(RuntimeError):
            rt.current()
        assert rt.bound_thread_ids() == ("A",)
        assert rt.latched_threads() == ("A",)
        with pytest.raises(MachineTransportError):
            rt.current()
    owner = rt._built[0]
    assert len(rt._built) == 1
    assert owner.connect_calls == 1
    assert owner.close_calls == 0  # retained/uncertain capability is NOT auto-closed


def test_keeper_failure_is_retained_latched_not_closed():
    rt = _runtime(fail_keeper=True)
    with _thread("A"):
        with pytest.raises(RuntimeError):
            rt.current()
        assert rt.latched_threads() == ("A",)
    owner = rt._built[0]
    assert owner.close_calls == 0  # retained, not auto-closed
    assert len(rt._built) == 1


def test_latched_thread_refuses_governed_but_allows_reconciliation():
    rt = _runtime(fail_connect=True)
    owner = dcb.RoutingCodexOwner(rt)
    with _thread("A"):
        with pytest.raises(MachineTransportError):
            rt.current()
        with pytest.raises(MachineTransportError):      # governed refused
            owner.control().call("register_session")
        assert owner.owner_status()["state"] == "uncertain"   # status still inspectable
        assert owner.recover_connection(expected_owner="x")["state"] == "recovered"
    assert len(rt._built) == 1


# ---- composed-server status through the REAL tool path (Ping #1) ----

def test_composed_server_status_tool_works_for_latched_thread():
    from nodelang.native_agent_mcp import build_server as build_installed_server
    rt = _runtime(fail_connect=True)
    server = build_installed_server(session=dcb.RoutingCodexOwner(rt))
    status_fn = server._tool_manager.get_tool("native.owner_status").fn
    with _thread("A"):
        with pytest.raises(MachineTransportError):
            rt.current()                       # latched
        status = status_fn()                   # real _with_stop_host path must NOT raise
    assert status["state"] == "uncertain"
    assert rt.latched_threads() == ("A",)


# ---- recovery + stage-aware resume restores governed calls (Ping #2) ----

def test_recovery_then_resume_restores_governed_calls():
    from nodelang.native_agent_mcp import build_server as build_installed_server
    rt = _runtime(fail_connect=True)
    owner = dcb.RoutingCodexOwner(rt)
    server = build_installed_server(session=owner)
    resume_fn = server._tool_manager.get_tool("native.owner_resume").fn
    with _thread("A"):
        with pytest.raises(MachineTransportError):
            rt.current()                       # connect-latched
        assert resume_fn()["resumed"] is False  # refused before reconciliation
        owner.recover_connection(expected_owner="x")   # same owner reconciled
        assert resume_fn() == {"state": "bound", "resumed": True}
        assert owner.control().call("register_session")["thread"] == "A"  # governed works now
    built = rt._built
    assert len(built) == 1               # never minted a 2nd owner
    assert built[0].connect_calls == 1   # connect never replayed
    assert built[0].recovered == 1
    assert built[0].lease_started == 1   # keeper completed during resume


def test_control_latched_resume_completes_without_replaying_connect():
    rt = _runtime(fail_control_once=True)
    with _thread("A"):
        with pytest.raises(RuntimeError):
            rt.current()                       # control-latched (connect already succeeded)
        assert rt.latched_threads() == ("A",)
        assert rt.resume("A") == {"state": "bound", "resumed": True}
        assert rt.current().control is not None    # governed works
    owner = rt._built[0]
    assert owner.connect_calls == 1          # connect not replayed
    assert len(rt._built) == 1


def test_resume_completion_failure_keeps_original_latch():
    rt = _runtime(fail_control=True)   # control never succeeds
    with _thread("A"):
        with pytest.raises(RuntimeError):
            rt.current()
        outcome = rt.resume("A")
        assert outcome["resumed"] is False and outcome["stage"] == "control"
        assert rt.latched_threads() == ("A",)   # still latched, original stage kept


# ---- composed deferred server: disabled attach surface + claim/review present ----

def _deferred_server():
    from nodelang.native_agent_mcp import build_server as build_installed_server
    rt = _runtime()
    return build_installed_server(session=dcb.RoutingCodexOwner(rt)), rt


def test_deferred_server_omits_dynamic_work_task_surface_but_keeps_claim_and_review():
    server, _ = _deferred_server()
    names = {t.name for t in server._tool_manager.list_tools()}
    assert "native.work_task_attach" not in names
    assert "native.work_task_detach" not in names
    assert "coordination.claim_work" in names
    assert "native.work_propose" in names
    assert "native.work_review_artifact" in names
    assert "native.work_publish_artifact" in names
    assert "native.work_assignment" in names
    assert "native.owner_status" in names


def test_work_assignment_resolved_per_thread():
    server, _ = _deferred_server()
    fn = server._tool_manager.get_tool("native.work_assignment").fn
    results = {}
    for tid in ("A", "B"):
        with _thread(tid):
            results[tid] = fn()
    assert results["A"]["assignment_for"] == "A"
    assert results["B"]["assignment_for"] == "B"


# ---- optional genuine-frame capture (default OFF; not acceptance evidence) ----

def test_meta_capture_is_off_by_default(monkeypatch):
    monkeypatch.delenv("ARCHHUB_CODEX_META_LOG", raising=False)
    with _thread("A"):
        assert dcb.current_codex_thread_id() == "A"


def test_meta_capture_records_genuine_frame_when_enabled(tmp_path, monkeypatch):
    log = tmp_path / "codex-meta.log"
    monkeypatch.setenv("ARCHHUB_CODEX_META_LOG", str(log))
    dcb._CAPTURE_STATE["count"] = 0
    token = _set_meta(threadId="real-chat-0199", sessionId="sess-77", itemId="item-5")
    try:
        assert dcb.current_codex_thread_id() == "real-chat-0199"
    finally:
        request_ctx.reset(token)
    frames = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert frames and frames[0]["request_meta"]["threadId"] == "real-chat-0199"
    assert frames[0]["request_meta"]["sessionId"] == "sess-77"
    assert frames[0]["request_meta"]["itemId"] == "item-5"
