"""Court: the Stop hook stops sending the agent to a tool; the native owner recovers itself (founder, 2026-09-30).

The founder watched a session end every turn on "run native_owner_status, then
native_owner_rebind with the exact owners it reports" while the tool it named
could itself be unreachable. The Stop host lived only while the owner was bound,
so after an application restart the hook replayed its last open-Work verdict
with that instruction on every turn.

Now the native owner process runs that same step itself (recover_same_actor):
settle a retained attempt, then continue the SAME actor on the current owner,
never a new enrollment, at most once per owner per recover_after. The hook says
what is known once per episode, the reconnection or the one step it could not
take, and every later turn end of the same episode is quiet.

Real application server, real machine pipe and real native owner for the
recovery; the fake owner only drives the retained-attempt order.
"""
from types import SimpleNamespace as NS

import pytest

from nodelang import native_stop_hook as hook
from tests_replica.test_native_inbox_recovery import World, _stale, _start

EXTERNAL = "b7d6a1c2-3e4f-4a5b-8c6d-7e8f9a0b1c2d"
OPEN = {"decision": "block", "reason": "Work W-7 is open: submit its evidence."}


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    root = tmp_path_factory.mktemp("stop-recovery-template")
    _start(root).close()
    return root


@pytest.fixture
def world(template, tmp_path):
    made = World(template, tmp_path / "app")
    try:
        yield made
    finally:
        made.close()


def _supervisor(owner, tmp_path, **kwargs):
    return hook.StopHostSupervisor(owner, vault=NS(), interval=3600, recovery_directory=tmp_path / "verdicts",
                                   **kwargs)


def _recorded(owner, tmp_path):
    fingerprint = hook._fingerprint("claude", owner._identity.external_session_id)
    return hook._load_guard(hook._recovery_path(fingerprint, tmp_path / "verdicts"))


def test_after_an_application_restart_the_owner_continues_its_actor_with_no_tool_call(world, tmp_path):
    owner, _control = world.owner(EXTERNAL)
    actor, generation = owner.owner_status()["agent_session"], owner.owner_status()["generation"]
    world.restart()
    assert owner.owner_status()["recovery_required"] is True
    supervisor = _supervisor(owner, tmp_path)
    assert supervisor.recover()["state"] == "bound"
    status = owner.owner_status()
    assert (status["state"], status["agent_session"], status["recovery_required"]) == ("bound", actor, False)
    assert status["generation"] == generation + 1
    # The first enrollment, then exactly one conditional continuation of the same actor.
    assert world.bind_calls == [(EXTERNAL, None), (EXTERNAL, actor)]
    assert _recorded(owner, tmp_path)["state"] == "bound"


def test_a_refusal_is_recorded_once_and_never_retried_in_a_loop(world, tmp_path):
    owner, _control = world.owner(EXTERNAL)
    actor = owner.owner_status()["agent_session"]
    _stale(world, actor, name="stop-recovery")                 # an unresolved permit gates continuation
    world.restart()
    supervisor = _supervisor(owner, tmp_path)
    first = supervisor.recover()
    assert first["state"] == "impossible" and "effect reconciliation" in first["reason"]
    calls = list(world.bind_calls)
    assert supervisor.recover() is first                      # same owner, within recover_after: no retry
    assert world.bind_calls == calls
    recorded = _recorded(owner, tmp_path)
    assert recorded["state"] == "impossible" and "effect reconciliation" in recorded["reason"]
    assert owner.owner_status()["agent_session"] == actor     # never a new enrollment


class _Retained:
    """An owner holding a failed rebind attempt: recovery settles it, then continues."""

    def __init__(self):
        self.calls, self._lock = [], __import__("threading").RLock()
        self._identity = NS(runtime="claude", external_session_id=EXTERNAL)
        self.state = "uncertain"

    def owner_status(self):
        bound = self.state == "bound-current"
        return {"state": "bound" if self.state != "uncertain" else "uncertain",
                "agent_session": "app:agent-session:runtime:" + "a" * 32,
                "pinned": {"fingerprint": "p" * 64}, "current": {"fingerprint": "c" * 64},
                "current_error": None, "recovery_required": not bound,
                "failed_attempt": ({"kind": "rebind", "owner_fingerprint": "f" * 64}
                                   if self.state == "uncertain" else None)}

    def recover_rebind_owner(self, **kwargs):
        self.calls.append(("recover", kwargs))
        self.state = "bound-stale"
        return {"next": "native.owner_rebind"}

    def rebind_owner(self, **kwargs):
        self.calls.append(("rebind", kwargs))
        self.state = "bound-current"


def test_a_retained_attempt_is_settled_before_the_same_actor_continues():
    owner = _Retained()
    assert hook.recover_same_actor(owner) == ("bound", None)
    assert owner.calls == [
        ("recover", {"expected_failed_owner": "f" * 64, "expected_current_owner": "c" * 64}),
        ("rebind", {"expected_old_owner": "p" * 64, "expected_new_owner": "c" * 64})]


def test_the_hook_says_it_once_and_names_no_tool(tmp_path):
    payload = {"session_id": EXTERNAL, "stop_hook_active": False}
    fingerprint = hook._fingerprint("claude", EXTERNAL)
    directory = tmp_path / "verdicts"
    hook._remember_verdict(fingerprint, OPEN, directory=directory)
    hook._save_guard(hook._recovery_path(fingerprint, directory),
                     {"at": 1.0, "state": "impossible",
                      "reason": "conditional native enrollment requires effect reconciliation"})
    first = hook.no_idle_decision(payload, "claude-code", directory=directory)
    assert first["decision"] == "block" and "Work W-7 is open" in first["reason"]
    assert "effect reconciliation" in first["reason"] and "native_owner_rebind" not in first["reason"]
    assert hook.no_idle_decision(payload, "claude-code", directory=directory) == {}   # said once
    assert hook.no_idle_decision(payload, "claude-code", directory=directory) == {}
    # The owner reconnected and the authority spoke again: a new episode is told once.
    hook._save_guard(hook._recovery_path(fingerprint, directory), {"at": 2.0, "state": "bound", "reason": None})
    again = hook.no_idle_decision(payload, "claude-code", directory=directory)
    assert again["decision"] == "block" and "reconnects this session" in again["reason"]
    assert hook.no_idle_decision(payload, "claude-code", directory=directory) == {}


def test_with_no_open_work_an_impossible_recovery_is_a_notice_once(tmp_path):
    payload = {"session_id": EXTERNAL, "stop_hook_active": False}
    fingerprint = hook._fingerprint("claude", EXTERNAL)
    directory = tmp_path / "verdicts"
    hook._save_guard(hook._recovery_path(fingerprint, directory),
                     {"at": 1.0, "state": "impossible", "reason": "the native owner is release-uncertain"})
    notice = hook.no_idle_decision(payload, "claude-code", directory=directory)
    assert set(notice) == {"systemMessage"} and "release-uncertain" in notice["systemMessage"]
    assert hook.no_idle_decision(payload, "claude-code", directory=directory) == {}
