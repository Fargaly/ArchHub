"""Court: claimed Workshop Work takes no agent effect before its own plan and research.

326b657 moved the coordinate-phase gate (plan + source-backed research) off
the claim to execution admission; nothing enforced it there. Verifier attacks
on the first two fixes (2026-09-25): an unplanned Work got a CDE permit; one
participant's shared entries opened another's Work; another Work's data root
passed as research evidence; the founder's own plan and research did not open
assigned Work; artifact publication, Grand Map sync and unassigned claimed Work
skipped the gate. Each case runs over the real machine pipe where it can, on
both transcript kinds (graph-held and ordinary content).
"""
import hashlib
import secrets
from pathlib import Path

import pytest

import nodelang.application_server as application_server_module
import nodelang.universal_application as app
from nodelang import commit_intent
from nodelang.application_machine_transport import MachineTransportError, UniversalRuntimeClient
from nodelang.application_server import ApplicationServer
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.cell_signing_authority import LocalEd25519KmsProvider
from nodelang.cell_value_graph import build_value_graph
from nodelang.universal_application import create_universal_governed_work

GATE = "plan and source-backed research"
TARGET = "10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py"


def _start(kind, tmp_path, monkeypatch, descriptor, provider):
    from tests_replica.test_application_machine_transport import _green_runtime_compliance as green
    if kind == "in-memory":
        return ApplicationServer(enable_machine_transport=True, machine_descriptor_path=descriptor,
                                 machine_key_provider=provider, runtime_compliance_runner=green).start()
    monkeypatch.setenv("ARCHHUB_GRAND_MAP_PATH", str(Path(app.__file__).parent / "data/public_runtime_map.json"))
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
    keys.add_key("archhub.local.court-attestation", secrets.token_bytes(32))
    return ApplicationServer(
        universal_state_path=tmp_path / "graph.sqlite3", universal_key_provider=keys,
        universal_workspace_root=tmp_path, enable_machine_transport=True,
        machine_descriptor_path=descriptor, machine_key_provider=provider,
        runtime_compliance_runner=green, enable_universal_cloud_gateway=False,
        enable_machine_projection_prewarm=False, live_watch=False).start()


def _serve(kind, tmp_path, monkeypatch):
    descriptor = tmp_path / "execution-gate-runtime.json"
    provider = MemorySigningKeyProvider("archhub.local.universal-runtime-pipe", b"g" * 32)
    server = _start(kind, tmp_path, monkeypatch, descriptor, provider)
    cde = LocalEd25519KmsProvider(provider_id="court.execution-gate", authority_id="court-execution-gate")
    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="CDE signing authority"):
        root = application_server_module._ensure_cde_write_signing_authority(
            server.universal_store, server.universal_registry, cde,
            descriptor_root="court:execution-gate-signing:v1")
    server.cde_write_signing_provider = cde
    server.cde_write_signing_descriptor_root = root
    return server, descriptor, provider


@pytest.fixture(params=["in-memory", "content-store"])
def served(request, tmp_path, monkeypatch):
    server, descriptor, provider = _serve(request.param, tmp_path, monkeypatch)
    try:
        yield server, descriptor, provider
    finally:
        server.close()


@pytest.fixture
def memory(tmp_path, monkeypatch):
    server, descriptor, provider = _serve("in-memory", tmp_path, monkeypatch)
    try:
        yield server, descriptor, provider
    finally:
        server.close()


def _container(key):
    return {
        "container_id": "GM.nodes.cde-authority", "source_requirement": key,
        "domain": "nodes", "tier": "T1", "lifecycle_state": "WIP", "suitability_status": "S0",
        "revision": "P01", "owner": "founder", "checker": "court", "allowed_paths": [TARGET],
        "gate_kind": "pytest",
        "gate_spec": {"path": "10.PRODUCT/13.NODE-LANGUAGE/tests_replica/test_cell_cde_authority.py"},
        "write_grants": [{"path": TARGET, "scope": "exact", "operations": ["apply_patch"]}],
    }


def _work(server, key):
    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="create Work"):
        root, _wire, _revision = create_universal_governed_work(
            server.universal_store, server.universal_registry, title="Gate " + key,
            description="Execution gate court", priority=100, external_key=key,
            structured_references={"cde-container": _container(key)}, x=320, y=240)
    return root


def _assign(server, assignment_id, work_root, session_root):
    return server.dispatch_universal_machine_route({
        "method": "POST", "path": "/api/universal/workshop-assignment",
        "body": {"assignment_id": assignment_id, "work": work_root, "agent_session": session_root}})


def _source(server, key):
    """Content captured in the graph as a registered value graph."""
    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="capture a source"):
        root, _revision = build_value_graph(
            server.universal_store, server.universal_registry.value_graph_protocol,
            {"source": "court", "key": key, "text": "A cited source for the research."},
            root_id="court:source:" + key)
    return root


def _entry(category, refs, evidence, key):
    return {"category": category, "text": "%s for %s" % (category, key), "refs": refs,
            "evidence": evidence, "recipients": [], "reply_to": None,
            "idempotency_key": "court:execution-gate:" + key, "created_at": "2026-09-25T10:00:00+00:00"}


def _post(client, category, refs, evidence, key):
    return client.request("POST", "/api/universal/workshop", _entry(category, refs, evidence, key))


def _founder_post(server, category, refs, evidence, key):
    return server.dispatch_universal_machine_route(
        {"method": "POST", "path": "/api/universal/workshop", "body": _entry(category, refs, evidence, key)})


def _permit(client, key):
    return client.issue_cde_write_permit(
        operation="apply_patch", path=TARGET,
        content_digest=hashlib.sha256(key.encode()).hexdigest(),
        request_id="req-" + key, nonce="nonce-" + key)


def _agent(descriptor, provider, name):
    client = UniversalRuntimeClient(descriptor, provider)
    session = client.bind_agent_session(runtime="codex", external_session_id=name)["agent_session"]
    return client, session


def test_unplanned_assigned_work_gets_no_cde_permit(served):
    server, descriptor, provider = served
    work = _work(server, "court:unplanned")
    a, sa = _agent(descriptor, provider, "gate-unplanned-a")
    _assign(server, "app:workshop-assignment:gate-unplanned", work, sa)
    assert a.claim_work(work)["claimed"] is True  # a claim reserves; it does not execute
    before = server.universal_store.revision
    with pytest.raises(MachineTransportError, match=GATE):
        _permit(a, "unplanned")
    assert server.universal_store.revision == before


def test_the_assignees_plan_and_captured_research_admit_the_effect(served):
    server, descriptor, provider = served
    work = _work(server, "court:planned")
    a, sa = _agent(descriptor, provider, "gate-planned-a")
    _assign(server, "app:workshop-assignment:gate-planned", work, sa)
    _post(a, "plan", [work], [], "planned-plan")
    _post(a, "research", [work], [server.universal_registry.map.grand_map_root], "planned-map")
    assert a.claim_work(work)["claimed"] is True
    with pytest.raises(MachineTransportError, match=GATE):
        _permit(a, "planned-too-early")  # the Grand Map is structure, not a source
    _post(a, "research", [work], [_source(server, "planned")], "planned-research")
    issued = _permit(a, "planned")
    assert issued["work"] == work and issued["permit"]


def test_another_works_data_is_not_research_evidence(memory):
    server, descriptor, provider = memory
    work, other = _work(server, "court:evidence"), _work(server, "court:evidence-other")
    a, sa = _agent(descriptor, provider, "gate-evidence-a")
    _assign(server, "app:workshop-assignment:gate-evidence", work, sa)
    _post(a, "plan", [work], [], "evidence-plan")
    # Verifier attack 1: another Work's CDE container, a readable value graph.
    _post(a, "research", [work], [other + ":data:cde-container"], "evidence-other-data")
    assert a.claim_work(work)["claimed"] is True
    before = server.universal_store.revision
    with pytest.raises(MachineTransportError, match=GATE):
        _permit(a, "evidence")
    assert server.universal_store.revision == before


def test_another_participants_shared_entries_never_open_someone_elses_work(memory):
    server, descriptor, provider = memory
    work_a, work_b = _work(server, "court:wa"), _work(server, "court:wb")
    _a, sa = _agent(descriptor, provider, "gate-shared-a")
    b, sb = _agent(descriptor, provider, "gate-shared-b")
    c, _sc = _agent(descriptor, provider, "gate-shared-c")
    _assign(server, "app:workshop-assignment:gate-wa", work_a, sa)
    _assign(server, "app:workshop-assignment:gate-wb", work_b, sb)
    source = _source(server, "shared")
    _post(c, "plan", [work_a, work_b], [], "shared-plan")
    _post(c, "research", [work_a, work_b], [source], "shared-research")
    assert b.claim_work(work_b)["claimed"] is True
    before = server.universal_store.revision
    with pytest.raises(MachineTransportError, match=GATE):
        _permit(b, "shared-b")
    assert server.universal_store.revision == before


def test_the_founders_own_plan_and_research_open_assigned_work(memory):
    server, descriptor, provider = memory
    work = _work(server, "court:founder")
    a, sa = _agent(descriptor, provider, "gate-founder-a")
    _assign(server, "app:workshop-assignment:gate-founder", work, sa)
    _founder_post(server, "plan", [work], [], "founder-plan")
    _founder_post(server, "research", [work], [_source(server, "founder")], "founder-research")
    assert a.claim_work(work)["claimed"] is True
    assert _permit(a, "founder")["work"] == work


def test_unassigned_claimed_work_is_gated_too(memory):
    server, descriptor, provider = memory
    work = _work(server, "court:unassigned")
    a, _sa = _agent(descriptor, provider, "gate-unassigned-a")
    assert a.claim_work(work)["claimed"] is True
    before = server.universal_store.revision
    with pytest.raises(MachineTransportError, match=GATE):
        _permit(a, "unassigned-early")
    assert server.universal_store.revision == before
    _post(a, "plan", [work], [], "unassigned-plan")
    _post(a, "research", [work], [_source(server, "unassigned")], "unassigned-research")
    assert _permit(a, "unassigned")["work"] == work


def test_an_agent_cannot_create_governed_work_for_itself(memory):
    server, descriptor, provider = memory
    a, _sa = _agent(descriptor, provider, "gate-self-a")
    before = server.universal_store.revision
    with pytest.raises(MachineTransportError, match="created by the application owner"):
        a.request("POST", "/api/universal/work", {
            "title": "Self-created", "description": "no founder", "priority": 1,
            "external_key": "court:self-created", "references": {},
            "structured_references": {"cde-container": _container("court:self-created")},
            "x": 1, "y": 1})
    with pytest.raises(MachineTransportError, match="created by the application owner"):
        a.request("POST", "/api/universal/grand-map-work", {"limit": 5})
    assert server.universal_store.revision == before


def test_artifact_publication_is_behind_the_gate(memory, monkeypatch):
    import nodelang.native_workshop_execution as native
    server, descriptor, provider = memory
    work = _work(server, "court:artifact")
    a, sa = _agent(descriptor, provider, "gate-artifact-a")
    assert a.claim_work(work)["claimed"] is True
    published = []
    material = {"publisher": sa, "material_digest": "d" * 64}
    monkeypatch.setattr(native, "_existing_actor", lambda _server, _request, _context: sa)
    monkeypatch.setattr(native, "_existing_material",
                        lambda _server, _context, _work: (material, None, "claimed"))

    class Broker:
        def publish_artifact(self, patch, name, *, summary, before_publish):
            published.append(name)
            raise AssertionError("artifact bytes were published before the gate")

    server.project_work_execution_broker = Broker()
    before = server.universal_store.revision
    context = server.universal_registry.authorization.session.context()
    with pytest.raises(Exception, match=GATE):
        native.publish_existing_session_artifact(
            server, request={}, context=context, work_root=work,
            material_digest=material["material_digest"], idempotency_key="court-artifact",
            patch=b"--- a\n+++ b\n", summary="court artifact")
    assert published == [] and server.universal_store.revision == before


def test_an_archived_plan_must_be_planned_again(memory, tmp_path):
    """Retention archives idle Workshop content; archived entries no longer count."""
    from nodelang.conversation_history import ConversationHistoryStore, _RETENTION_SECONDS
    server, descriptor, provider = memory
    work = _work(server, "court:archived")
    a, _sa = _agent(descriptor, provider, "gate-archived-a")
    assert a.claim_work(work)["claimed"] is True
    with pytest.raises(MachineTransportError, match="again, if its plan was archived"):
        _permit(a, "archived")
    clock = [1_000_000.0]
    history = ConversationHistoryStore(tmp_path / "gate-history.sqlite3", instance_id="gate",
                                       retention_clock=lambda: clock[0])
    room = "court:workshop"
    history.ensure_conversation(room)
    history.initialize_retention()
    history.initialize_page_protection()
    categories = server.universal_registry.workshop_category_roots
    for category in ("plan", "research"):
        history.append(room, author="founder", content=category, category=categories[category],
                       refs=(work,), idempotency_key="gate-" + category)
    gate_categories = (categories["plan"], categories["research"])
    assert len(history.messages_referencing(room, work, categories=gate_categories)) == 2
    status = history.retention_status(room)
    history.resolve_page_tracking(room, resolver_identity=("s", "u", "v", "t", "a"),
        expected_activity_revision=status["activity_revision"], before_commit=lambda: None)
    clock[0] += _RETENTION_SECONDS + 3600
    status = history.retention_status(room)
    cas = dict(expected_activity_revision=status["activity_revision"],
               expected_archive_revision=status["archive_revision"],
               expected_head=status["last_sequence"],
               expected_content_generation=status["content_generation"])
    history.archive(room, **cas, protected=False, before_commit=lambda: None)
    status = history.retention_status(room)
    cas = dict(expected_activity_revision=status["activity_revision"],
               expected_archive_revision=status["archive_revision"],
               expected_head=status["last_sequence"],
               expected_content_generation=status["content_generation"])
    history.purge_archived(room, **cas, protected=False, before_commit=lambda: None,
                           export=lambda _messages: None)
    assert history.messages_referencing(room, work, categories=gate_categories) == []
    history.close()
