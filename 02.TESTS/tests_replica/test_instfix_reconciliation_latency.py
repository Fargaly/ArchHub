"""A native recovery read cannot monopolize the desktop/BABOOM owner lock."""
from pathlib import Path
import sys
import threading

import pytest

from tests_replica.test_native_inbox_recovery import KEY, World, _start


@pytest.fixture(scope="module")
def runtime_map():
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("ARCHHUB_GRAND_MAP_PATH", str(Path(__file__).resolve().parents[2] / "01.APP/nodelang/data/public_runtime_map.json"))
        yield


@pytest.fixture(scope="module")
def template(tmp_path_factory, runtime_map):
    root = tmp_path_factory.mktemp("instfix-reconciliation-template")
    _start(root, enable_machine_projection_prewarm=False, live_watch=False).close()
    return root


@pytest.fixture
def world(template, tmp_path):
    owner = World(template, tmp_path / "instance", enable_machine_projection_prewarm=False, live_watch=False)
    try:
        yield owner
    finally:
        owner.close()


def test_effects_scan_yields_to_desktop_and_signed_baboom(world, monkeypatch):
    from nodelang import application_machine_transport as transport
    from nodelang import application_server, native_session_release
    from nodelang.application_machine_transport import UniversalRuntimeClient
    from tests_replica.test_application_machine_transport import _bind_runtime_device, _runtime_device_key, _device_credential
    from tests_replica.test_desktop_renewal_not_behind_graph_lock import _handoff_request
    owner, _control = world.owner("instfix-reconcile")
    fingerprint = owner.owner_status()["current"]["fingerprint"]
    key, reference = _runtime_device_key()
    from nodelang import commit_intent
    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="install this fixture's BABOOM device"):
        custody = _bind_runtime_device(world.server, reference, runtime="baboom")
    baboom = UniversalRuntimeClient(world.root / "runtime.json", KEY)
    external = "instfix-reconcile-baboom"
    baboom.bind_agent_session(runtime="baboom", external_session_id=external,
        device_credential_provider=lambda challenge: _device_credential(key, custody, challenge, external))
    baboom.baboom_native_frame()
    root = Path(transport.__file__).resolve().parents[2]
    desktop = transport.MachinePipePeer(12345, 100.0, str(Path(sys.executable).resolve()),
        (sys.executable, str(root / "nodelang/launcher.py")), str(root))
    observed = transport._observe_machine_process
    physical = application_server._verified_machine_pipe_peer
    monkeypatch.setattr(transport, "_observe_machine_process", lambda pid: desktop if pid == desktop.pid else observed(pid))
    monkeypatch.setattr(application_server, "_verified_machine_pipe_peer", lambda request:
        desktop if request.get("path") == "/api/universal/browser-handoff" else physical(request))
    world.server._dispatch_verified_machine_route(_handoff_request())
    entered, release = threading.Event(), threading.Event()
    original = native_session_release.read_pending_effects
    outcomes, errors = {}, []

    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(15), "court failed to release its read-only scan"
        return original(*args, **kwargs)

    def run(name, operation):
        try:
            outcomes[name] = operation()
        except BaseException as error:
            errors.append(error)

    monkeypatch.setattr(native_session_release, "read_pending_effects", slow)
    inspection = threading.Thread(target=lambda: run("effects", lambda:
        owner.inspect_enrollment(expected_owner=fingerprint, projection="effects")), daemon=True)
    inspection.start()
    assert entered.wait(10), errors
    renewal = threading.Thread(target=lambda: run("desktop", lambda:
        world.server._dispatch_verified_machine_route(_handoff_request())), daemon=True)
    frame = threading.Thread(target=lambda: run("baboom", baboom.baboom_native_frame), daemon=True)
    try:
        renewal.start()
        frame.start()
        renewal.join(2)
        frame.join(2)
        answered_during_scan = "desktop" in outcomes and "baboom" in outcomes
    finally:
        release.set()
        for worker in (inspection, renewal, frame):
            worker.join(20)
    assert not errors, errors
    assert answered_during_scan, "native effects enumeration held the desktop/BABOOM global lock"
    assert outcomes["desktop"]["one_use"] is True
    assert outcomes["effects"]["continuation_authorized"] is False
    print("CONTENTION: desktop renewal and signed BABOOM frame both answered while effects scan paused")


@pytest.mark.parametrize("changed", ["revision", "custody", "route", "cursor"])
def test_unlocked_projection_refuses_changed_authority_before_disclosure(changed, monkeypatch):
    import hashlib
    import time
    from types import SimpleNamespace
    from nodelang import application_server, native_session_release
    from nodelang.application_machine_transport import MachinePipePeer
    from nodelang.cell_authorization import AuthorizationDenied
    from nodelang.native_enrollment_reconciliation import PATH, reconcile_enrollment
    from nodelang.universal_cell import NULL_CELL_ID
    actor = "app:agent-session:runtime:" + "1" * 32
    peer = MachinePipePeer(123, 100.0, sys.executable, (), str(Path.cwd()))
    binding = {"runtime": "codex", "catalog_entry": "catalog-codex", "device_custody": None,
        "external_session_fingerprint": hashlib.sha256(b"court").hexdigest(),
        "expires_at": time.time() + 600, "enrollment_peer": {"pid": peer.pid, "created_at": peer.created_at},
        "token": "court-only-token"}
    store = SimpleNamespace(revision=1)
    store.snapshot = lambda: SimpleNamespace(revision=store.revision)
    owner = SimpleNamespace(mutation_lock=threading.RLock(), _machine_agent_session_lock=threading.RLock(),
        universal_store=store, universal_registry=SimpleNamespace(cde_write_authority_protocol=object()),
        _machine_agent_sessions={actor: binding}, _machine_agent_active_requests={}, _native_effects_read_cursors={},
        _bound_machine_agent_session_identity=lambda **kwargs: SimpleNamespace(root_id=actor))
    monkeypatch.setattr(application_server, "_agent_body_catalog_entry_for_runtime",
        lambda *args: SimpleNamespace(credential_mode="machine-transport", root_id="catalog-codex"))
    body = {"runtime": "codex", "external_session_id": "court", "expected_agent_session": actor, "projection": "effects"}
    if changed == "cursor":
        body["cursor"] = "cursor"
        owner._native_effects_read_cursors["cursor"] = {"actor": actor, "peer": peer, "revision": 1,
            "chain": "fixture-chain", "remaining": 100, "until": time.monotonic() + 60}

    def scan(snapshot, *args, **kwargs):
        if changed == "revision":
            store.revision += 1
        elif changed == "custody":
            binding["token"] = "replacement-token"
        elif changed == "cursor":
            owner._native_effects_read_cursors.clear()
        return {"projection": "effects", "revision": snapshot.revision, "pending_permits": [],
            "receipt_references": [], "_next_chain": NULL_CELL_ID, "_next_remaining": 0}

    def revalidate():
        if changed == "route":
            raise AuthorizationDenied("route revoked during projection")

    monkeypatch.setattr(native_session_release, "read_pending_effects", scan)
    request = {"method": "POST", "path": PATH, "session": {}, "body": body, "runtime_id": "fixture"}
    with pytest.raises(AuthorizationDenied):
        reconcile_enrollment(owner, request, peer, read_guard=revalidate)
    assert owner._native_effects_read_cursors == {}


def test_default_reconciliation_rechecks_route_before_identity_disclosure(monkeypatch):
    from types import SimpleNamespace
    from nodelang import application_server
    from nodelang.application_machine_transport import MachinePipePeer
    from nodelang.cell_authorization import AuthorizationDenied
    from nodelang.native_enrollment_reconciliation import PATH, reconcile_enrollment
    owner = SimpleNamespace(mutation_lock=threading.RLock(), _machine_agent_session_lock=threading.RLock())
    monkeypatch.setattr(application_server, "_agent_body_catalog_entry_for_runtime",
        lambda *args: pytest.fail("identity read preceded current route authority"))
    request = {"method": "POST", "path": PATH, "session": {}, "runtime_id": "court", "body": {
        "runtime": "codex", "external_session_id": "court", "expected_agent_session": "app:agent-session:runtime:" + "1" * 32}}
    def revoked():
        raise AuthorizationDenied("route revoked before reconciliation")
    with pytest.raises(AuthorizationDenied, match="route revoked"):
        reconcile_enrollment(owner, request, MachinePipePeer(1, 100.0, sys.executable, (), str(Path.cwd())), read_guard=revoked)
