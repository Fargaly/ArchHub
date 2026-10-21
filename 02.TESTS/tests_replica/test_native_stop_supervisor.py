"""Court: the Stop host follows the native owner's binding, per native identity.

A real NativeStopHost (Windows secured pipe) over an in-memory vault and a
fake owner whose binding the court moves: fresh launch, recovery that keeps
the original actor, rebind to a new application instance, unbind and process
shutdown. Two Codex threads hold two hosts. A host that could not start says
so and never reads as ready. A Stop payload whose identity disagrees with the
runtime's own session variable is refused. Nothing here reads a real vault,
~/.codex or a running application.
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace as NS

import pytest

from nodelang import native_agent_hooks
from nodelang import native_stop_hook as hook

WINDOWS = pytest.mark.skipif(hook.os.name != "nt", reason="Windows secured pipe")
ACTOR = "app:agent-session:runtime:" + "a" * 32


def _vault():
    values = {}
    return NS(values=values,
              get_password=lambda service, key: values.get(key),
              set_password=lambda service, key, value: values.__setitem__(key, value),
              delete_password=lambda service, key: values.pop(key, None))


class _Owner:
    """The owner surface NativeStopHost and the supervisor read; the court moves its binding."""

    def __init__(self, thread_id):
        self._lock = threading.RLock()
        self._identity = NS(runtime="codex", external_session_id=thread_id)
        self._active_calls = 0
        self.client = NS(_request_lock=threading.RLock(), _agent_session_expires_at=time.time() + 600,
                         _request_once=lambda *args, **kwargs: {"fixture": "index"})
        self.status = {"state": "unbound", "agent_session": None, "pinned": None,
                       "rebind_pending": False, "recovery_required": False}

    def bind(self, instance, actor=ACTOR):
        self.status = dict(self.status, state="bound", agent_session=actor,
                           pinned={"instance_digest": instance}, recovery_required=False)

    def owner_status(self):
        with self._lock:
            return dict(self.status)

    def _require_bound(self):
        return self.client


def _supervisor(owner, vault, **kwargs):
    return hook.StopHostSupervisor(owner, vault=vault, interval=3600, **kwargs)


@WINDOWS
def test_two_codex_threads_hold_two_distinct_hosts():
    vault = _vault()
    first, second = _Owner("thread-a"), _Owner("thread-b")
    first.bind("instance"); second.bind("instance")
    one, two = _supervisor(first, vault), _supervisor(second, vault)
    try:
        assert one.reconcile() == {"state": "ready", "reason": None}
        assert two.reconcile() == {"state": "ready", "reason": None}
        assert set(vault.values) == {hook._fingerprint("codex", "thread-a"),
                                     hook._fingerprint("codex", "thread-b")}
    finally:
        one.close(); two.close()
    assert vault.values == {}


@WINDOWS
def test_recovery_keeps_the_original_actor_and_start_is_idempotent():
    vault, owner = _vault(), _Owner("thread-a")
    supervisor = _supervisor(owner, vault)
    try:
        assert supervisor.reconcile() == {"state": "absent", "reason": "owner_unbound"}
        assert vault.values == {}
        owner.bind("instance")                      # recovery restored the same actor
        assert supervisor.reconcile()["state"] == "ready"
        host, record = supervisor._host, dict(vault.values)
        assert host.record["actor"] == ACTOR
        for _ in range(3):
            assert supervisor.reconcile()["state"] == "ready"
        assert supervisor._host is host and vault.values == record
    finally:
        supervisor.close()


@WINDOWS
def test_rebind_to_a_new_instance_replaces_the_host_and_invalidates_the_old_one():
    vault, owner = _vault(), _Owner("thread-a")
    owner.bind("instance-1")
    supervisor = _supervisor(owner, vault)
    try:
        assert supervisor.reconcile()["state"] == "ready"
        old = supervisor._host
        old_endpoint = old.record["endpoint"]
        owner.bind("instance-2")                    # the same actor, reconnected elsewhere
        assert supervisor.reconcile()["state"] == "ready"
        assert old.closed.is_set() and supervisor._host is not old
        [record] = vault.values.values()
        assert old_endpoint not in record and supervisor._host.record["instance"] == "instance-2"
    finally:
        supervisor.close()


@WINDOWS
def test_unbind_and_shutdown_close_the_host():
    vault, owner = _vault(), _Owner("thread-a")
    owner.bind("instance")
    supervisor = _supervisor(owner, vault)
    assert supervisor.reconcile()["state"] == "ready"
    owner.status = dict(owner.status, state="uncertain")
    assert supervisor.reconcile() == {"state": "absent", "reason": "owner_unbound"}
    assert vault.values == {}
    owner.bind("instance")
    assert supervisor.reconcile()["state"] == "ready"
    host = supervisor._host
    assert supervisor.close() is True
    assert host.closed.is_set() and vault.values == {}
    assert supervisor.status() == {"state": "absent", "reason": "closed"}


def test_a_host_that_could_not_start_is_reported_and_never_ready():
    owner, calls = _Owner("thread-a"), []
    owner.bind("instance")

    class Refused:
        def __init__(self, held, vault):
            calls.append(held)

        def start(self):
            raise RuntimeError("private failure text")

    supervisor = _supervisor(owner, _vault(), host_factory=Refused, retry_after=3600)
    assert supervisor.reconcile() == {"state": "failed", "reason": "start_failed"}
    assert supervisor.reconcile() == {"state": "failed", "reason": "start_failed"}
    assert len(calls) == 1                          # no retry storm inside retry_after
    supervisor.retry_after = 0
    supervisor.reconcile()
    assert len(calls) == 2
    assert "private" not in repr(supervisor.status())


@WINDOWS
def test_a_live_host_elsewhere_for_the_same_identity_is_not_replaced():
    vault = _vault()
    first, second = _Owner("thread-a"), _Owner("thread-a")
    first.bind("instance"); second.bind("instance")
    holder, other = _supervisor(first, vault), _supervisor(second, vault)
    try:
        assert holder.reconcile()["state"] == "ready"
        assert other.reconcile() == {"state": "failed", "reason": "owned_elsewhere"}
        assert holder.status()["state"] == "ready" and len(vault.values) == 1
    finally:
        other.close(); holder.close()


@WINDOWS
def test_a_host_that_stopped_reads_as_failed_until_it_is_restarted():
    vault, owner = _vault(), _Owner("thread-a")
    owner.bind("instance")
    supervisor = _supervisor(owner, vault)
    try:
        assert supervisor.reconcile()["state"] == "ready"
        supervisor._host.close()
        assert supervisor.status() == {"state": "failed", "reason": "host_stopped"}
        assert supervisor.reconcile()["state"] == "ready"
    finally:
        supervisor.close()


@WINDOWS
def test_a_failed_vault_cleanup_leaves_no_listener_and_never_reads_ready_or_closed():
    from multiprocessing.connection import Client
    vault, owner = _vault(), _Owner("thread-a")
    owner.bind("instance-1")
    supervisor = _supervisor(owner, vault)
    assert supervisor.reconcile()["state"] == "ready"
    host = supervisor._host
    endpoint, key = host.record["endpoint"], bytes.fromhex(host.record["key"])
    healthy = vault.get_password

    def broken(service, name):
        raise OSError("vault unavailable")

    vault.get_password = broken
    owner.bind("instance-2")                        # a rebind needs the old host gone first
    assert supervisor.reconcile() == {"state": "failed", "reason": "cleanup_failed"}
    assert not host.thread.is_alive()               # the listener stopped anyway
    with pytest.raises(OSError):
        Client(endpoint, family="AF_PIPE", authkey=key)
    assert supervisor._host is host                 # still held: no replacement while uncleaned
    assert supervisor.reconcile() == {"state": "failed", "reason": "cleanup_failed"}
    assert len(vault.values) == 1                   # the record is kept, never silently dropped
    assert supervisor.close() is False
    assert supervisor.status() == {"state": "failed", "reason": "cleanup_failed"}
    vault.get_password = healthy                    # the vault heals: the same cleanup completes
    assert supervisor.close() is True
    assert vault.values == {} and supervisor.status() == {"state": "absent", "reason": "closed"}


@WINDOWS
def test_a_failed_cleanup_heals_on_the_next_reconcile_before_any_replacement():
    vault, owner = _vault(), _Owner("thread-a")
    owner.bind("instance-1")
    supervisor = _supervisor(owner, vault)
    try:
        assert supervisor.reconcile()["state"] == "ready"
        old = supervisor._host
        healthy = vault.delete_password
        vault.delete_password = lambda service, name: (_ for _ in ()).throw(OSError("locked"))
        owner.bind("instance-2")
        assert supervisor.reconcile()["reason"] == "cleanup_failed"
        vault.delete_password = healthy
        assert supervisor.reconcile()["state"] == "ready"
        assert supervisor._host is not old and supervisor._host.record["instance"] == "instance-2"
        assert len(vault.values) == 1
    finally:
        supervisor.close()


def test_a_stop_payload_whose_identity_disagrees_is_refused():
    none = NS(get_password=lambda *args: None)
    with pytest.raises(ValueError):
        hook.query_stop({"session_id": "thread-a"}, vendor="codex", vault=none,
                        environment={"CODEX_THREAD_ID": "thread-b"})
    with pytest.raises(ValueError):
        hook.query_stop({"session_id": "thread-a"}, vendor="codex", vault=none,
                        environment={"ARCHHUB_EXTERNAL_SESSION_ID": "thread-b"})
    # Another runtime's variable is an inherited parent's, not this payload's identity.
    claude = "71743447-6dd5-4050-bc4f-d228f7a1d91e"
    ended = hook.query_stop({"session_id": "thread-a"}, vendor="codex", vault=none,
                            environment={"CLAUDE_CODE_SESSION_ID": claude})
    assert set(ended) == {"systemMessage"}
    ended = hook.query_stop({"session_id": claude}, vendor="claude-code", vault=none,
                            environment={"CODEX_THREAD_ID": "thread-a"})
    assert set(ended) == {"systemMessage"}


@WINDOWS
def test_the_codex_stop_query_reaches_its_supervised_host(monkeypatch):
    vault, owner = _vault(), _Owner("thread-a")
    owner.bind("instance")
    verdict = {"decision": "block", "reason": "Work assembly-instance:fixture is still claimed"}
    monkeypatch.setattr(native_agent_hooks, "stop_verdict", lambda status, client: dict(verdict))
    monkeypatch.setattr(hook, "_remember_verdict", lambda fingerprint, value: None)
    supervisor = _supervisor(owner, vault)
    try:
        assert supervisor.reconcile()["state"] == "ready"
        answer = hook.query_stop({"session_id": "thread-a"}, vendor="codex", vault=vault,
                                 environment={"CODEX_THREAD_ID": "thread-a"})
        assert answer == verdict
        other = hook.query_stop({"session_id": "thread-b"}, vendor="codex", vault=vault,
                                environment={"CODEX_THREAD_ID": "thread-b"})
        assert set(other) == {"systemMessage"}      # no host for that thread: may end, nothing declared
    finally:
        supervisor.close()
