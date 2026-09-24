"""Court: a BABOOM native frame never holds the graph lock for its whole build.

Observed on the founder's installed build (py-spy, 2026-09-24): every 30 s
GET /api/universal/baboom-native-frame held ``mutation_lock`` for 8-10 s while
it built three projections, so every other machine request (desktop renewal,
presence, agent sessions) queued behind it. The frame must read one immutable
revision, and only a brief admission may hold the lock.

Runs a real BABOOM agent session over this court's own pipe on two fixture
graphs: the in-memory graph, and a persistent graph whose first boot created a
Workshop content store, which is the founder's installed path (the frame then
reads one ordinary-content page under the lock and projects outside it).
"""
import secrets
from pathlib import Path
import json
import threading
import time

import pytest

import nodelang.cell_identity as cell_identity
from nodelang.application_machine_transport import UniversalRuntimeClient
from nodelang import commit_intent
from nodelang import universal_application as app
from nodelang.application_server import ApplicationServer
from nodelang.cell_deliberation import read_deliberation_space
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from tests_replica.test_application_machine_transport import (
    _device_credential, _register_runtime_device, _runtime_device_key,
)

LOCK_HOLD_BOUND_SECONDS = 0.050


class TimedLock:
    """RLock stand-in recording each outermost hold with its thread name."""

    def __init__(self):
        self._lock = threading.RLock()
        self._local = threading.local()
        self.holds = []

    def acquire(self, blocking=True, timeout=-1):
        got = self._lock.acquire(blocking, timeout)
        if got:
            depth = getattr(self._local, "depth", 0)
            if depth == 0:
                self._local.started = time.perf_counter()
            self._local.depth = depth + 1
        return got

    def release(self):
        self._local.depth -= 1
        if self._local.depth == 0:
            self.holds.append((time.perf_counter() - self._local.started,
                               threading.current_thread().name))
        self._lock.release()

    __enter__ = acquire

    def __exit__(self, *exc):
        self.release()


@pytest.fixture(params=["in-memory", "content-store"])
def enrolled(request, tmp_path, monkeypatch):
    descriptor_path = tmp_path / "frame-lock-runtime.json"
    provider = MemorySigningKeyProvider("archhub.local.universal-runtime-pipe", b"L" * 32)
    if request.param == "in-memory":
        server = ApplicationServer(
            enable_machine_transport=True,
            machine_descriptor_path=descriptor_path,
            machine_key_provider=provider,
        ).start()
    else:
        monkeypatch.setenv("ARCHHUB_GRAND_MAP_PATH",
            str(Path(app.__file__).parent / "data/public_runtime_map.json"))
        keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
        keys.add_key("archhub.local.court-attestation", secrets.token_bytes(32))
        server = ApplicationServer(
            universal_state_path=tmp_path / "graph.sqlite3", universal_key_provider=keys,
            universal_workspace_root=tmp_path, enable_machine_transport=True,
            machine_descriptor_path=descriptor_path, machine_key_provider=provider,
            enable_universal_cloud_gateway=False, enable_machine_projection_prewarm=False,
            live_watch=False,
        ).start()
    registry = server.universal_registry
    space = read_deliberation_space(server.universal_store.snapshot(),
        registry.deliberation_protocol, registry.workshop_root)
    assert (space.content_store_root is not None) == (request.param == "content-store")
    server._brain_state = lambda: {"ok": True, "facts": 0}
    key, reference = _runtime_device_key()
    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="register court device"):
        custody_root = _register_runtime_device(server, reference)
    external_session_id = "frame-lock-court"
    try:
        founder = UniversalRuntimeClient(descriptor_path, provider)
        founder.bind_agent_session(runtime="founder-machine", external_session_id="frame-lock-founder")
        founder.bind_runtime_device_custody(runtime="baboom", custody_root=custody_root)
        baboom = UniversalRuntimeClient(descriptor_path, provider)
        baboom.bind_agent_session(
            runtime="baboom", external_session_id=external_session_id,
            device_credential_provider=lambda challenge: _device_credential(
                key, custody_root, challenge, external_session_id))
        baboom.renew_runtime_presence()
        for index in range(6):
            server.dispatch_universal_machine_route({"method": "POST", "path": "/api/universal/work", "body": {
                "title": "Frame lock Work %d" % index, "description": "fixture",
                "priority": 20, "external_key": "frame-lock-%d" % index,
                "references": {"scope": server.universal_registry.map.domains["brain"]},
                "x": 100 + index, "y": 100}})
        server._fixture_kind = request.param
        yield server, baboom
    finally:
        server.close()


def _stable(frame):
    """Frame content without its per-issue lease clock."""
    return json.dumps({key: value for key, value in frame.items()
                       if key not in ("issued_at", "expires_at")}, sort_keys=True)


def test_native_frame_holds_the_graph_lock_only_briefly(enrolled):
    server, baboom = enrolled
    baboom.baboom_native_frame(response_timeout_seconds=60)  # warm the route caches
    verifications = [0, 0]
    broker_class = cell_identity.RelationshipAuthorityBroker
    original_verify = broker_class.verify_signature
    original_snapshot = cell_identity.verify_relationship_authority_snapshot

    def counted(self, *args, **kwargs):
        verifications[0] += 1
        return original_verify(self, *args, **kwargs)

    def counted_snapshot(*args, **kwargs):
        verifications[1] += 1
        return original_snapshot(*args, **kwargs)

    timed = TimedLock()
    server.mutation_lock = timed
    broker_class.verify_signature = counted
    cell_identity.verify_relationship_authority_snapshot = counted_snapshot
    try:
        builds = []
        for _ in range(3):
            timed.holds.clear()
            started = time.perf_counter()
            frame = baboom.baboom_native_frame(response_timeout_seconds=60)
            builds.append((time.perf_counter() - started,
                           max((hold for hold, name in timed.holds
                                if name == "archhub-universal-runtime-request"), default=0.0)))
    finally:
        broker_class.verify_signature = original_verify
        cell_identity.verify_relationship_authority_snapshot = original_snapshot
    print("\n[%s] frame build ms %s; longest lock hold ms %s; signature verifications per frame %d; authority snapshot verifications per frame %d" % (
        server._fixture_kind, [round(build * 1000, 1) for build, _ in builds],
        [round(hold * 1000, 1) for _, hold in builds], verifications[0] // 3, verifications[1] // 3))
    assert frame["report"] is not None and frame["context"]["revision"] == frame["revision"]
    longest = max(hold for _, hold in builds)
    assert longest < LOCK_HOLD_BOUND_SECONDS, (
        "native frame held mutation_lock %.1f ms (bound %.0f ms)"
        % (longest * 1000, LOCK_HOLD_BOUND_SECONDS * 1000))


def test_native_frame_equals_the_locked_build_of_the_same_revision(enrolled):
    server, baboom = enrolled
    revision = server.universal_store.revision
    server._native_frame_outside_lock = False
    locked = baboom.baboom_native_frame(response_timeout_seconds=60)
    server._native_frame_outside_lock = True
    unlocked = baboom.baboom_native_frame(response_timeout_seconds=60)
    assert server.universal_store.revision == revision
    assert locked["revision"] == unlocked["revision"] == revision
    assert locked["report"] is not None
    assert _stable(locked) == _stable(unlocked)


def test_native_frame_stays_on_one_revision_while_the_graph_commits(enrolled):
    server, baboom = enrolled
    stop, commits, errors = threading.Event(), [0], []

    def writer():
        index = 0
        while not stop.is_set():
            index += 1
            try:
                server.dispatch_universal_machine_route({"method": "POST", "path": "/api/universal/work", "body": {
                    "title": "Concurrent Work %d" % index, "description": "fixture",
                    "priority": 30, "external_key": "frame-lock-concurrent-%d" % index,
                    "references": {"scope": server.universal_registry.map.domains["brain"]},
                    "x": 300 + index, "y": 300}})
                commits[0] += 1
            except Exception as exc:  # the writer is fixture load, not the court
                errors.append(repr(exc))

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    try:
        frames = [baboom.baboom_native_frame(response_timeout_seconds=60) for _ in range(4)]
    finally:
        stop.set()
        thread.join(30)
    assert commits[0] > 0, errors[:3]
    for frame in frames:
        assert frame["context"]["revision"] == frame["directive"]["revision"] == frame["revision"]
        if frame["report"] is not None:
            assert frame["report"]["data"]["revision"] == frame["revision"]
