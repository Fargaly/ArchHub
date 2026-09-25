from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import threading
from types import SimpleNamespace

import pytest

from nodelang import universal_application as universal_application_module
from nodelang.universal_application import (
    UniversalCdeWriteAdmission,
    authorize_universal_cde_write,
)
from nodelang.cell_cde_authority import (
    CdeWriteDenied,
    authorize_cde_container_write,
    bootstrap_cde_write_authority_protocol,
    consume_cde_write_permit,
    issue_cde_write_permit,
    prepare_cde_write_consumption,
    read_cde_write_permit,
    revoke_cde_write_permit,
    verify_cde_write_permit,
)
from nodelang.cell_signing_authority import (
    LocalEd25519KmsProvider,
    bootstrap_signing_authority_protocol,
    build_signing_key_descriptor,
    read_signing_key_descriptor,
)
from nodelang.application_server import (
    ApplicationServer,
    _ensure_cde_write_signing_authority,
)
from nodelang.application_machine_transport import UniversalRuntimeClient
from nodelang.cell_protocols import CellBatch, read_relation
from nodelang.universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    Conflict,
    InvalidCell,
)


# Founder order 2026-09-23 (SPEC 3.3): a CDE write permit is issued only as a
# bounded indexed record (operational storage). The courts that asserted the
# deleted graph-composition issue path were removed with it: test_permit_issue_recovers_one_exact_existing_permit_after_ack_loss, test_permit_issue_recovers_the_exact_concurrent_commit_winner, test_signed_permit_recovers_the_exact_receipt_after_ack_loss, test_permit_commit_conflict_leaves_no_orphan_signature_or_permit, test_consumption_can_join_one_larger_atomic_graph_commit, test_unrelated_commit_preserves_exact_reauthorized_permit, test_signed_payload_tamper_and_revocation_fail_closed.

def _world():
    store = CellStore()
    signing = bootstrap_signing_authority_protocol(store, prefix="court:signing")
    provider = LocalEd25519KmsProvider(
        provider_id="court-cde-provider",
        authority_id="court-cde-authority",
    )
    descriptor = build_signing_key_descriptor(
        store,
        signing,
        provider,
        descriptor_id="court:cde-key:v1",
        resource_version=provider.current_resource,
        authority_id="court-cde-authority",
        purpose="cde-write-permit",
        valid_from="2026-01-01T00:00:00Z",
        valid_until="2030-01-01T00:00:00Z",
        authorization_evidence="court:founder-authorization",
        release_evidence="court:key-release",
    )
    protocol = bootstrap_cde_write_authority_protocol(
        store, prefix="court:cde-write"
    )
    store.commit(store.revision, create=(
        Cell(
            "app:agent-session:runtime:court",
            NULL_CELL_ID,
            NULL_CELL_ID,
            b"court session",
        ),
        Cell("work:court", NULL_CELL_ID, NULL_CELL_ID, b"court Work"),
        Cell(
            "cde:container:court",
            NULL_CELL_ID,
            NULL_CELL_ID,
            b"court CDE container",
        ),
        Cell(
            "court:write-authorization",
            NULL_CELL_ID,
            NULL_CELL_ID,
            b"court authorization",
        ),
    ))
    return store, signing, provider, descriptor, protocol


def _issue(world, *, now=100.0):
    store, signing, provider, descriptor, protocol = world
    content_digest = hashlib.sha256(b"patch bytes").hexdigest()
    permit, revision = issue_cde_write_permit(
        store,
        protocol,
        signing,
        provider,
        descriptor,
        permit_id="court:cde-permit:1",
        runtime="codex",
        agent_session_root="app:agent-session:runtime:court",
        work_root="work:court",
        container_root="cde:container:court",
        container_id="GM.nodes.cde-authority",
        container_digest="a" * 64,
        operation="apply_patch",
        path="10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py",
        content_digest=content_digest,
        request_id="court-write-request-1",
        nonce="court-nonce-1",
        issued_at=now,
        expires_at=now + 60.0,
        authorization_evidence="court:write-authorization",
    )
    return permit, revision, content_digest


@pytest.mark.parametrize(
    ("override", "message"),
    (
        ({"runtime": "claude-code"}, "runtime"),
        ({"agent_session_root": "app:agent-session:runtime:other"}, "session"),
        ({"work_root": "work:other"}, "Work"),
        ({"container_root": "cde:container:other"}, "container root"),
        ({"container_digest": "b" * 64}, "container"),
        ({"operation": "write_file"}, "operation"),
        ({"path": "10.PRODUCT/13.NODE-LANGUAGE/nodelang/other.py"}, "path"),
        ({"content_digest": "c" * 64}, "content"),
        ({"request_id": "different-request"}, "request"),
        ({"authority_revision": 999}, "revision"),
        ({"now": 161.0}, "expired"),
    ),
)
def test_permit_denies_every_foreign_or_stale_request(override, message):
    world = _world()
    store, signing, provider, _descriptor, protocol = world
    permit, revision, content_digest = _issue(world)
    request = {
        "runtime": "codex",
        "agent_session_root": "app:agent-session:runtime:court",
        "work_root": "work:court",
        "container_root": "cde:container:court",
        "container_id": "GM.nodes.cde-authority",
        "container_digest": "a" * 64,
        "operation": "apply_patch",
        "path": "10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py",
        "content_digest": content_digest,
        "request_id": "court-write-request-1",
        "authorization_evidence": "court:write-authorization",
        "authority_revision": revision,
        "now": 120.0,
    }
    request.update(override)

    with pytest.raises(CdeWriteDenied, match=message):
        verify_cde_write_permit(
            store.snapshot(), protocol, signing, provider, permit.root_id, **request
        )


def test_cde_signer_is_purpose_bound_and_wired_into_one_application_graph():
    store = CellStore()
    signing = bootstrap_signing_authority_protocol(
        store, prefix="app:cde-signing-authority-protocol"
    )
    cde = bootstrap_cde_write_authority_protocol(
        store, prefix="app:cde-write-authority-protocol"
    )
    batch = CellBatch(store)
    for root, value in (
        ("app:role:member", "member"),
        ("app:authorization:policy", "authorization"),
        ("app:court:runtime-ownership", "release"),
    ):
        batch.add(Cell(root, NULL_CELL_ID, NULL_CELL_ID, value.encode("ascii")))
    batch.relation(
        (
            ("app:role:member", signing.root_id),
            ("app:role:member", cde.root_id),
        ),
        relation_id="app:archhub",
    )
    batch.commit()
    registry = SimpleNamespace(
        application_root="app:archhub",
        roles={"member": "app:role:member"},
        authorization=SimpleNamespace(policy_root="app:authorization:policy"),
        runtime_ownership_court_root="app:court:runtime-ownership",
        cde_signing_protocol=signing,
        cde_write_authority_protocol=cde,
    )
    provider = LocalEd25519KmsProvider(
        provider_id="court-app-cde-provider",
        authority_id="court-app-cde-authority",
    )

    descriptor_root = _ensure_cde_write_signing_authority(
        store, registry, provider
    )
    same_root = _ensure_cde_write_signing_authority(store, registry, provider)
    descriptor = read_signing_key_descriptor(
        store.snapshot(), signing, descriptor_root
    )
    members = [
        member.participant_id for member in read_relation(
            store.snapshot(), "app:archhub", budget=100_000
        )
        if member.role_id == "app:role:member"
        and member.participant_id == descriptor_root
    ]

    assert same_root == descriptor_root
    assert members == [descriptor_root]
    assert descriptor.values["purpose"] == "cde-write-permit"
    assert descriptor.values["authorization-evidence"] == (
        "app:authorization:policy"
    )
    assert descriptor.values["release-evidence"] == (
        "app:court:runtime-ownership"
    )


def _cde_container(*, lifecycle="WIP"):
    return {
        "container_id": "GM.nodes.cde-authority",
        "source_requirement": "grand-map:cde-authority",
        "domain": "nodes",
        "tier": "T1",
        "lifecycle_state": lifecycle,
        "suitability_status": "S0",
        "revision": "P07",
        "owner": "founder",
        "checker": "court",
        "allowed_paths": [
            (
                "10.PRODUCT/13.NODE-LANGUAGE/"
                "nodelang/cell_cde_authority.py"
            ),
            "10.PRODUCT/13.NODE-LANGUAGE/tests_replica",
        ],
        "gate_kind": "pytest",
        "gate_spec": {
            "path": "10.PRODUCT/13.NODE-LANGUAGE/tests_replica"
        },
        "write_grants": [
            {
                "path": (
                    "10.PRODUCT/13.NODE-LANGUAGE/"
                    "nodelang/cell_cde_authority.py"
                ),
                "scope": "exact",
                "operations": ["apply_patch"],
            },
            {
                "path": "10.PRODUCT/13.NODE-LANGUAGE/tests_replica",
                "scope": "descendants",
                "operations": ["apply_patch", "write_file"],
            },
        ],
    }


def test_cde_container_admission_is_wip_operation_and_path_exact():
    container_id, digest = authorize_cde_container_write(
        _cde_container(),
        operation="apply_patch",
        path="10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py",
    )
    same_id, same_digest = authorize_cde_container_write(
        _cde_container(),
        operation="write_file",
        path="10.PRODUCT/13.NODE-LANGUAGE/tests_replica/court.txt",
    )

    assert container_id == same_id == "GM.nodes.cde-authority"
    assert digest == same_digest
    assert len(digest) == 64


@pytest.mark.parametrize(
    ("container", "operation", "path", "message"),
    (
        (_cde_container(lifecycle="SHARED"), "apply_patch",
         "10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py",
         "WIP"),
        (_cde_container(lifecycle="PUBLISHED"), "apply_patch",
         "10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py",
         "WIP"),
        (_cde_container(), "shell_command",
         "10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py",
         "operation"),
        (_cde_container(), "apply_patch",
         "10.PRODUCT/13.NODE-LANGUAGE/nodelang/other.py", "path"),
        (_cde_container(), "apply_patch", "../outside.py", "path"),
        ({**_cde_container(), "revision": 7}, "apply_patch",
         "10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py",
         "revision"),
        ({**_cde_container(), "allowed_paths": [
            "10.PRODUCT/13.NODE-LANGUAGE/nodelang/other.py"
        ]}, "apply_patch",
         "10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py",
         "disagree"),
    ),
)
def test_cde_container_denies_non_wip_foreign_operation_or_path(
    container, operation, path, message
):
    with pytest.raises(CdeWriteDenied, match=message):
        authorize_cde_container_write(
            container, operation=operation, path=path
        )

    clean = _world()
    store, signing, provider, _descriptor, protocol = clean
    permit, revision, content_digest = _issue(clean)
    revoke_cde_write_permit(store, protocol, permit.root_id, reason="court revoke")
    with pytest.raises(CdeWriteDenied, match="revoked"):
        verify_cde_write_permit(
            store.snapshot(),
            protocol,
            signing,
            provider,
            permit.root_id,
            runtime="codex",
            agent_session_root="app:agent-session:runtime:court",
            work_root="work:court",
            container_root="cde:container:court",
            container_id="GM.nodes.cde-authority",
            container_digest="a" * 64,
            operation="apply_patch",
            path="10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py",
            content_digest=content_digest,
            request_id="court-write-request-1",
            authorization_evidence="court:write-authorization",
            authority_revision=revision,
            now=120.0,
        )


def test_application_cde_admission_uses_exact_session_work_claim_and_container(
    monkeypatch,
):
    store = CellStore()
    session_root = "app:agent-session:runtime:court"
    subject_root = "app:subject:court"
    work_root = "app:work:court"
    claim_binding = "app:work-claim-binding:court"
    container_root = "app:value-graph:cde-container:court"
    registry = SimpleNamespace(
        authorization=SimpleNamespace(
            broker=SimpleNamespace(
                resolve=lambda _context: SimpleNamespace(
                    subject_root=subject_root
                )
            )
        ),
        value_graph_protocol=object(),
    )
    monkeypatch.setattr(
        universal_application_module,
        "_runtime_agent_session",
        lambda _snapshot, _registry, root: SimpleNamespace(
            root_id=root, subject_root=subject_root
        ),
    )
    monkeypatch.setattr(
        universal_application_module,
        "_view_session_for_context",
        lambda _registry, context: (
            SimpleNamespace(subject_root=subject_root), context
        ),
    )
    monkeypatch.setattr(
        universal_application_module,
        "read_universal_current_claimed_work",
        lambda *_args, **_kwargs: ({
                "root": work_root,
                "claimant_session": session_root,
                "claim_binding": claim_binding,
                "operational": {"current_state_label": "CLAIMED"},
            }, store.revision),
    )
    monkeypatch.setattr(
        universal_application_module,
        "_instance_projection",
        lambda _snapshot, _registry, root: ({
            "interfaces": ({
                "name": "cde-container",
                "target": container_root,
            },),
        } if root == work_root else None),
    )
    monkeypatch.setattr(
        universal_application_module,
        "read_value_graph",
        lambda _snapshot, _protocol, root: (
            _cde_container() if root == container_root else None
        ),
    )
    # This court's registry is a stub for claim/container resolution; the
    # Workshop execution gate has its own courts on a real registry
    # (test_workshop_execution_gate.py). Record that admission asks it.
    gated = []
    monkeypatch.setattr(
        universal_application_module,
        "_require_workshop_execution_gate",
        lambda _snapshot, _registry, *, work_root, agent_session_root=None, content_service=None:
            gated.append((work_root, agent_session_root)),
    )

    admission = authorize_universal_cde_write(
        store,
        registry,
        agent_session_root=session_root,
        operation="apply_patch",
        path=(
            "10.PRODUCT/13.NODE-LANGUAGE/"
            "nodelang/cell_cde_authority.py"
        ),
        authentication_context=object(),
    )
    assert gated == [(work_root, session_root)], (
        "CDE admission must ask the Workshop execution gate for its claiming session")

    assert admission.agent_session_root == session_root
    assert admission.work_root == work_root
    assert admission.claim_binding_root == claim_binding
    assert admission.container_root == container_root
    assert admission.container_id == "GM.nodes.cde-authority"
    assert admission.authority_revision == store.revision


def test_machine_route_issues_from_admission_claim_not_caller_work(
    monkeypatch,
):
    store = CellStore()
    server = object.__new__(ApplicationServer)
    context = object()
    server.universal_store = store
    server.universal_registry = SimpleNamespace(
        authorization=SimpleNamespace(
            session=SimpleNamespace(context=lambda: context),
            protocol=object(),
        ),
        agent_body=SimpleNamespace(protocol=object()),
        cde_write_authority_protocol=object(),
        cde_signing_protocol=object(),
    )
    server.universal_checkpoint_guard = None
    server.mutation_lock = threading.RLock()
    server.cde_write_signing_provider = object()
    server.cde_write_signing_descriptor_root = "app:cde-key"
    server.require_universal_http_route = lambda *_args, **_kwargs: None
    server._resolve_universal_machine_agent_session = (
        lambda _request: "app:agent-session:runtime:court"
    )
    admission = UniversalCdeWriteAdmission(
        "app:agent-session:runtime:court",
        "app:work:court",
        "app:work-claim-binding:court",
        "app:value-graph:cde-container:court",
        "GM.nodes.cde-authority",
        "a" * 64,
        "apply_patch",
        "10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py",
        store.revision,
    )
    monkeypatch.setattr(
        "nodelang.application_server.authorize_universal_cde_write",
        lambda *_args, **_kwargs: admission,
    )
    monkeypatch.setattr(
        "nodelang.application_server.read_agent_session",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "nodelang.application_server._agent_body_catalog_entry_for_session",
        lambda *_args, **_kwargs: SimpleNamespace(runtime="codex"),
    )
    issued = {}

    def issue(*_args, **kwargs):
        issued.update(kwargs)
        return SimpleNamespace(
            root_id="app:cde-write-permit:court",
            agent_session_root=kwargs["agent_session_root"],
            work_root=kwargs["work_root"],
            container_root=kwargs["container_root"],
            container_id=kwargs["container_id"],
            container_digest=kwargs["container_digest"],
            operation=kwargs["operation"],
            path=kwargs["path"],
            content_digest=kwargs["content_digest"],
            request_id=kwargs["request_id"],
            authority_revision=2,
            expires_at=200.0,
        ), 2

    monkeypatch.setattr(
        "nodelang.application_server.issue_cde_write_permit", issue
    )
    result = server.dispatch_universal_machine_route({
        "runtime_id": "court-runtime",
        "request_id": "transport-request",
        "method": "POST",
        "path": "/api/universal/cde-write-permit",
        "body": {
            "operation": "apply_patch",
            "path": admission.path,
            "content_digest": "b" * 64,
            "request_id": "write-request",
            "nonce": "write-nonce",
        },
        "session": {"root": admission.agent_session_root, "proof": "proof"},
    })

    assert issued["work_root"] == admission.work_root
    assert issued["authorization_evidence"] == admission.claim_binding_root
    assert issued["container_root"] == admission.container_root
    assert result["work"] == admission.work_root
    assert result["claim_binding"] == admission.claim_binding_root


def test_runtime_client_requests_cde_permit_without_caller_authority_roots():
    client = object.__new__(UniversalRuntimeClient)
    client.agent_session_root = "app:agent-session:runtime:court"
    observed = {}

    def request(method, path, body):
        observed.update({"method": method, "path": path, "body": body})
        return {
            "permit": "app:cde-write-permit:court",
            "agent_session": client.agent_session_root,
            "work": "app:work:court",
            "claim_binding": "app:work-claim-binding:court",
            "container_root": "app:value-graph:cde-container:court",
            "container_id": "GM.nodes.cde-authority",
            "container_digest": "a" * 64,
            "operation": "apply_patch",
            "path": (
                "10.PRODUCT/13.NODE-LANGUAGE/"
                "nodelang/cell_cde_authority.py"
            ),
            "content_digest": "b" * 64,
            "request_id": "write-request",
            "authority_revision": 42,
            "expires_at": 200.0,
            "revision": 42,
        }

    client.request = request
    result = client.issue_cde_write_permit(
        operation="apply_patch",
        path=(
            "10.PRODUCT/13.NODE-LANGUAGE/"
            "nodelang/cell_cde_authority.py"
        ),
        content_digest="b" * 64,
        request_id="write-request",
        nonce="write-nonce",
    )

    assert result["work"] == "app:work:court"
    assert observed["path"] == "/api/universal/cde-write-permit"
    assert set(observed["body"]) == {
        "operation", "path", "content_digest", "request_id", "nonce"
    }
    assert "work" not in observed["body"]
    assert "container" not in observed["body"]


def test_runtime_client_consumes_cde_permit_without_caller_authority_roots():
    client = object.__new__(UniversalRuntimeClient)
    client.agent_session_root = "app:agent-session:runtime:court"
    observed = {}

    def request(method, path, body):
        observed.update({"method": method, "path": path, "body": body})
        return {
            "receipt": "app:cde-write-permit:court:receipt:consumed",
            "permit": "app:cde-write-permit:court",
            "kind": "consumed",
            "receipt_digest": "c" * 64,
            "agent_session": client.agent_session_root,
            "work": "app:work:court",
            "claim_binding": "app:work-claim-binding:court",
            "container_root": "app:value-graph:cde-container:court",
            "revision": 43,
        }

    client.request = request
    result = client.consume_cde_write_permit(
        permit="app:cde-write-permit:court",
        operation="apply_patch",
        path=(
            "10.PRODUCT/13.NODE-LANGUAGE/"
            "nodelang/cell_cde_authority.py"
        ),
        content_digest="b" * 64,
        request_id="write-request",
    )

    assert result["kind"] == "consumed"
    assert observed["path"] == "/api/universal/cde-write-receipt"
    assert set(observed["body"]) == {
        "permit", "operation", "path", "content_digest", "request_id"
    }
    assert "work" not in observed["body"]
    assert "claim_binding" not in observed["body"]
    assert "container_root" not in observed["body"]


def test_current_work_route_is_provider_neutral(monkeypatch):
    server = object.__new__(ApplicationServer)
    context = object()
    server.universal_store = CellStore()
    server.universal_registry = SimpleNamespace(
        authorization=SimpleNamespace(
            session=SimpleNamespace(context=lambda: context)
        )
    )
    server.universal_checkpoint_guard = None
    server.require_universal_http_route = lambda *_args, **_kwargs: None
    server._resolve_universal_machine_agent_session = (
        lambda _request: "app:agent-session:runtime:codex"
    )
    monkeypatch.setattr(
        "nodelang.application_server.read_universal_current_claimed_work",
        lambda *_args, **_kwargs: ({
            "root": "app:work:codex",
            "interfaces": [{
                "name": "title",
                "value": "Repair the CDE path",
            }],
        }, 17),
    )

    result = server.dispatch_universal_machine_route({
        "runtime_id": "court-runtime",
        "request_id": "transport-request",
        "method": "GET",
        "path": "/api/universal/work-current",
        "body": {},
        "session": {
            "root": "app:agent-session:runtime:codex",
            "proof": "proof",
        },
    })

    assert result == {
        "agent_session": "app:agent-session:runtime:codex",
        "work": {
            "root": "app:work:codex",
            "title": "Repair the CDE path",
        },
        "revision": 17,
    }


@pytest.mark.parametrize("indexed", (False, True))
@pytest.mark.parametrize("replayed", ("nonce", "request"))
def test_permit_issue_denies_replayed_nonce_or_request(replayed, indexed):
    world = _world()
    store, signing, provider, descriptor, protocol = world
    _permit, _revision, content_digest = _issue(world)
    if indexed:
        from nodelang.cell_cde_authority import ensure_store_cde_storage
        ensure_store_cde_storage(store)
    request_id = (
        "court-write-request-1" if replayed == "request"
        else "court-write-request-2"
    )
    nonce = "court-nonce-1" if replayed == "nonce" else "court-nonce-2"

    with pytest.raises(CdeWriteDenied, match=replayed):
        issue_cde_write_permit(
            store,
            protocol,
            signing,
            provider,
            descriptor,
            permit_id="court:cde-permit:2",
            runtime="codex",
            agent_session_root="app:agent-session:runtime:court",
            work_root="work:court",
            container_root="cde:container:court",
            container_id="GM.nodes.cde-authority",
            container_digest="a" * 64,
            operation="apply_patch",
            path=(
                "10.PRODUCT/13.NODE-LANGUAGE/"
                "nodelang/cell_cde_authority.py"
            ),
            content_digest=content_digest,
            request_id=request_id,
            nonce=nonce,
            issued_at=200.0,
            expires_at=260.0,
            authorization_evidence="court:write-authorization",
        )


def test_permit_issue_denies_non_graph_session_work_container_or_evidence():
    for missing, message in (
        ("agent_session_root", "agent session"),
        ("work_root", "Work"),
        ("container_root", "container root"),
        ("authorization_evidence", "authorization evidence"),
    ):
        world = _world()
        store, signing, provider, descriptor, protocol = world
        request = {
            "permit_id": "court:cde-permit:missing",
            "runtime": "codex",
            "agent_session_root": "app:agent-session:runtime:court",
            "work_root": "work:court",
            "container_root": "cde:container:court",
            "container_id": "GM.nodes.cde-authority",
            "container_digest": "a" * 64,
            "operation": "apply_patch",
            "path": (
                "10.PRODUCT/13.NODE-LANGUAGE/"
                "nodelang/cell_cde_authority.py"
            ),
            "content_digest": "b" * 64,
            "request_id": "court-write-request-missing",
            "nonce": "court-nonce-missing",
            "issued_at": 100.0,
            "expires_at": 160.0,
            "authorization_evidence": "court:write-authorization",
        }
        request[missing] = "court:missing-root"

        with pytest.raises(CdeWriteDenied, match=message):
            issue_cde_write_permit(
                store,
                protocol,
                signing,
                provider,
                descriptor,
                **request,
            )


def test_cde_operational_storage_repeated_writes_preserve_graph_revision_and_cells(tmp_path):
    from nodelang.cell_cde_authority import ensure_store_cde_storage
    db_file = tmp_path / "primary_instance.sqlite"
    store = CellStore(database_path=db_file)
    signing = bootstrap_signing_authority_protocol(store, prefix="court:signing")
    provider = LocalEd25519KmsProvider(
        provider_id="court-cde-provider",
        authority_id="court-cde-authority",
    )
    descriptor = build_signing_key_descriptor(
        store,
        signing,
        provider,
        descriptor_id="court:cde-key:v1",
        resource_version=provider.current_resource,
        authority_id="court-cde-authority",
        purpose="cde-write-permit",
        valid_from="2026-01-01T00:00:00Z",
        valid_until="2030-01-01T00:00:00Z",
        authorization_evidence="court:founder-authorization",
        release_evidence="court:key-release",
    )
    storage = ensure_store_cde_storage(store)
    protocol = bootstrap_cde_write_authority_protocol(
        store, prefix="court:cde-write", operational_storage=storage
    )
    store.commit(store.revision, create=(
        Cell("app:agent-session:runtime:court", NULL_CELL_ID, NULL_CELL_ID, b"court session"),
        Cell("work:court", NULL_CELL_ID, NULL_CELL_ID, b"court Work"),
        Cell("cde:container:court", NULL_CELL_ID, NULL_CELL_ID, b"court CDE container"),
        Cell("court:write-authorization", NULL_CELL_ID, NULL_CELL_ID, b"court authorization"),
    ))

    base_revision = store.revision
    base_cells = len(store.snapshot().cells)

    for i in range(10):
        content_digest = hashlib.sha256(f"content-{i}".encode("utf-8")).hexdigest()
        permit, issue_rev = issue_cde_write_permit(
            store,
            protocol,
            signing,
            provider,
            descriptor,
            permit_id=f"court:cde-permit:op:{i}",
            runtime="codex",
            agent_session_root="app:agent-session:runtime:court",
            work_root="work:court",
            container_root="cde:container:court",
            container_id="GM.nodes.cde-authority",
            container_digest="a" * 64,
            operation="apply_patch",
            path="10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py",
            content_digest=content_digest,
            request_id=f"court-req-{i}",
            nonce=f"court-nonce-{i}",
            issued_at=100.0 + i * 10,
            expires_at=200.0 + i * 10,
            authorization_evidence="court:write-authorization",
        )
        assert issue_rev == base_revision
        assert store.revision == base_revision
        assert len(store.snapshot().cells) == base_cells

        receipt, consume_rev = consume_cde_write_permit(
            store,
            protocol,
            signing,
            provider,
            permit.root_id,
            runtime="codex",
            agent_session_root="app:agent-session:runtime:court",
            work_root="work:court",
            container_root="cde:container:court",
            container_id="GM.nodes.cde-authority",
            container_digest="a" * 64,
            operation="apply_patch",
            path="10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py",
            content_digest=content_digest,
            request_id=f"court-req-{i}",
            authorization_evidence="court:write-authorization",
            authority_revision=base_revision,
            now=105.0 + i * 10,
        )
        assert consume_rev == base_revision
        assert store.revision == base_revision
        assert len(store.snapshot().cells) == base_cells
        assert receipt.kind_root == protocol.receipt_kinds["consumed"]

        recovered_receipt, recovered_revision = consume_cde_write_permit(
            store,
            protocol,
            signing,
            provider,
            permit.root_id,
            runtime="codex",
            agent_session_root="app:agent-session:runtime:court",
            work_root="work:court",
            container_root="cde:container:court",
            container_id="GM.nodes.cde-authority",
            container_digest="a" * 64,
            operation="apply_patch",
            path="10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py",
            content_digest=content_digest,
            request_id=f"court-req-{i}",
            authorization_evidence="court:write-authorization",
            authority_revision=base_revision,
            now=106.0 + i * 10,
        )
        assert recovered_receipt == receipt
        assert recovered_revision == consume_rev

    assert store.revision == base_revision
    assert len(store.snapshot().cells) == base_cells

    # A graph commit between admission and the SQLite effect must refuse,
    # including a retained-receipt recovery; no stale authority is relabelled.
    from nodelang.cde_operational_storage import CdeOperationalDenied
    pending = storage.get_permit(permit.root_id)
    pending.update(permit_root="court:stale", request_id="stale-request", nonce="stale-nonce", state="active")
    stored_receipt = storage.get_receipt(receipt.root_id)
    store.commit(store.revision, create=(Cell("court:concurrent", NULL_CELL_ID, NULL_CELL_ID, b"advanced"),))
    with pytest.raises(CdeOperationalDenied, match="authority revision is stale"):
        storage.record_permit(pending)
    assert storage.get_permit("court:stale") is None
    with pytest.raises(CdeOperationalDenied, match="authority revision is stale"):
        storage.consume_permit(permit.root_id, stored_receipt, expected_content_digest=permit.content_digest, now=196.0)
    with pytest.raises(CdeOperationalDenied, match="authority revision is stale"):
        storage.revoke_permit(permit.root_id, stored_receipt, reason="stale", now=196.0)
    assert storage.get_receipt(receipt.root_id) == stored_receipt


def test_cde_operational_storage_reopen_preserves_evidence_without_resurrecting_consumed_or_expired(tmp_path):
    from nodelang.cell_cde_authority import ensure_store_cde_storage, project_cde_write_authority_protocol, read_cde_write_receipt
    db_file = tmp_path / "reopen_court.sqlite"
    store = CellStore(database_path=db_file)
    signing = bootstrap_signing_authority_protocol(store, prefix="court:signing")
    provider = LocalEd25519KmsProvider(
        provider_id="court-cde-provider",
        authority_id="court-cde-authority",
    )
    descriptor = build_signing_key_descriptor(
        store,
        signing,
        provider,
        descriptor_id="court:cde-key:v1",
        resource_version=provider.current_resource,
        authority_id="court-cde-authority",
        purpose="cde-write-permit",
        valid_from="2026-01-01T00:00:00Z",
        valid_until="2030-01-01T00:00:00Z",
        authorization_evidence="court:founder-authorization",
        release_evidence="court:key-release",
    )
    storage = ensure_store_cde_storage(store)
    protocol = bootstrap_cde_write_authority_protocol(
        store, prefix="court:cde-write", operational_storage=storage
    )
    store.commit(store.revision, create=(
        Cell("app:agent-session:runtime:court", NULL_CELL_ID, NULL_CELL_ID, b"court session"),
        Cell("work:court", NULL_CELL_ID, NULL_CELL_ID, b"court Work"),
        Cell("cde:container:court", NULL_CELL_ID, NULL_CELL_ID, b"court CDE container"),
        Cell("court:write-authorization", NULL_CELL_ID, NULL_CELL_ID, b"court authorization"),
    ))

    content_digest_1 = hashlib.sha256(b"content-1").hexdigest()
    permit1, _ = issue_cde_write_permit(
        store, protocol, signing, provider, descriptor,
        permit_id="court:cde-permit:p1",
        runtime="codex",
        agent_session_root="app:agent-session:runtime:court",
        work_root="work:court",
        container_root="cde:container:court",
        container_id="GM.nodes.cde-authority",
        container_digest="a" * 64,
        operation="apply_patch",
        path="10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py",
        content_digest=content_digest_1,
        request_id="req-1",
        nonce="nonce-1",
        issued_at=100.0,
        expires_at=150.0,
        authorization_evidence="court:write-authorization",
    )
    receipt1, _ = consume_cde_write_permit(
        store, protocol, signing, provider,
        permit1.root_id,
        runtime="codex",
        agent_session_root="app:agent-session:runtime:court",
        work_root="work:court",
        container_root="cde:container:court",
        container_id="GM.nodes.cde-authority",
        container_digest="a" * 64,
        operation="apply_patch",
        path="10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py",
        content_digest=content_digest_1,
        request_id="req-1",
        authorization_evidence="court:write-authorization",
        authority_revision=store.revision,
        now=110.0,
    )

    content_digest_2 = hashlib.sha256(b"content-2").hexdigest()
    permit2, _ = issue_cde_write_permit(
        store, protocol, signing, provider, descriptor,
        permit_id="court:cde-permit:p2",
        runtime="codex",
        agent_session_root="app:agent-session:runtime:court",
        work_root="work:court",
        container_root="cde:container:court",
        container_id="GM.nodes.cde-authority",
        container_digest="a" * 64,
        operation="apply_patch",
        path="10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py",
        content_digest=content_digest_2,
        request_id="req-2",
        nonce="nonce-2",
        issued_at=100.0,
        expires_at=150.0,
        authorization_evidence="court:write-authorization",
    )

    store.close()

    reopened_store = CellStore(database_path=db_file)
    reopened_storage = ensure_store_cde_storage(reopened_store)
    reopened_protocol = project_cde_write_authority_protocol(
        reopened_store.snapshot(),
        prefix="court:cde-write",
        store=reopened_store,
        operational_storage=reopened_storage,
    )

    p1_read = read_cde_write_permit(reopened_store.snapshot(), reopened_protocol, permit1.root_id)
    assert p1_read.state_root == reopened_protocol.states["consumed"]

    r1_read = read_cde_write_receipt(reopened_store.snapshot(), reopened_protocol, receipt1.root_id)
    assert r1_read == receipt1

    with pytest.raises(CdeWriteDenied, match="CDE write permit content digest mismatched"):
        consume_cde_write_permit(
            reopened_store, reopened_protocol, signing, provider,
            permit1.root_id,
            runtime="codex",
            agent_session_root="app:agent-session:runtime:court",
            work_root="work:court",
            container_root="cde:container:court",
            container_id="GM.nodes.cde-authority",
            container_digest="a" * 64,
            operation="apply_patch",
            path="10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py",
            content_digest="b" * 64,
            request_id="req-1-retry",
            authorization_evidence="court:write-authorization",
            authority_revision=reopened_store.revision,
            now=120.0,
        )

    with pytest.raises(CdeWriteDenied, match="expired or is not yet valid"):
        consume_cde_write_permit(
            reopened_store, reopened_protocol, signing, provider,
            permit2.root_id,
            runtime="codex",
            agent_session_root="app:agent-session:runtime:court",
            work_root="work:court",
            container_root="cde:container:court",
            container_id="GM.nodes.cde-authority",
            container_digest="a" * 64,
            operation="apply_patch",
            path="10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py",
            content_digest=content_digest_2,
            request_id="req-2",
            authorization_evidence="court:write-authorization",
            authority_revision=reopened_store.revision,
            now=160.0,
        )


def test_cde_operational_storage_refuses_replays_wrong_actor_and_tampered_proofs(tmp_path):
    from nodelang.cell_cde_authority import ensure_store_cde_storage
    db_file = tmp_path / "security_court.sqlite"
    store = CellStore(database_path=db_file)
    signing = bootstrap_signing_authority_protocol(store, prefix="court:signing")
    provider = LocalEd25519KmsProvider(
        provider_id="court-cde-provider",
        authority_id="court-cde-authority",
    )
    descriptor = build_signing_key_descriptor(
        store,
        signing,
        provider,
        descriptor_id="court:cde-key:v1",
        resource_version=provider.current_resource,
        authority_id="court-cde-authority",
        purpose="cde-write-permit",
        valid_from="2026-01-01T00:00:00Z",
        valid_until="2030-01-01T00:00:00Z",
        authorization_evidence="court:founder-authorization",
        release_evidence="court:key-release",
    )
    storage = ensure_store_cde_storage(store)
    protocol = bootstrap_cde_write_authority_protocol(
        store, prefix="court:cde-write", operational_storage=storage
    )
    store.commit(store.revision, create=(
        Cell("app:agent-session:runtime:court", NULL_CELL_ID, NULL_CELL_ID, b"court session"),
        Cell("app:agent-session:runtime:intruder", NULL_CELL_ID, NULL_CELL_ID, b"intruder session"),
        Cell("work:court", NULL_CELL_ID, NULL_CELL_ID, b"court Work"),
        Cell("cde:container:court", NULL_CELL_ID, NULL_CELL_ID, b"court CDE container"),
        Cell("court:write-authorization", NULL_CELL_ID, NULL_CELL_ID, b"court authorization"),
    ))

    content_digest = hashlib.sha256(b"sec-content").hexdigest()
    permit, _ = issue_cde_write_permit(
        store, protocol, signing, provider, descriptor,
        permit_id="court:cde-permit:sec:1",
        runtime="codex",
        agent_session_root="app:agent-session:runtime:court",
        work_root="work:court",
        container_root="cde:container:court",
        container_id="GM.nodes.cde-authority",
        container_digest="a" * 64,
        operation="apply_patch",
        path="10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py",
        content_digest=content_digest,
        request_id="sec-req-1",
        nonce="sec-nonce-1",
        issued_at=100.0,
        expires_at=200.0,
        authorization_evidence="court:write-authorization",
    )

    with pytest.raises(CdeWriteDenied, match="nonce was replayed"):
        issue_cde_write_permit(
            store, protocol, signing, provider, descriptor,
            permit_id="court:cde-permit:sec:2",
            runtime="codex",
            agent_session_root="app:agent-session:runtime:court",
            work_root="work:court",
            container_root="cde:container:court",
            container_id="GM.nodes.cde-authority",
            container_digest="a" * 64,
            operation="apply_patch",
            path="10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py",
            content_digest=content_digest,
            request_id="sec-req-2",
            nonce="sec-nonce-1",
            issued_at=100.0,
            expires_at=200.0,
            authorization_evidence="court:write-authorization",
        )

    with pytest.raises(CdeWriteDenied, match="request was replayed"):
        issue_cde_write_permit(
            store, protocol, signing, provider, descriptor,
            permit_id="court:cde-permit:sec:3",
            runtime="codex",
            agent_session_root="app:agent-session:runtime:court",
            work_root="work:court",
            container_root="cde:container:court",
            container_id="GM.nodes.cde-authority",
            container_digest="a" * 64,
            operation="apply_patch",
            path="10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py",
            content_digest=content_digest,
            request_id="sec-req-1",
            nonce="sec-nonce-3",
            issued_at=100.0,
            expires_at=200.0,
            authorization_evidence="court:write-authorization",
        )

    with pytest.raises(CdeWriteDenied, match="agent session mismatched"):
        consume_cde_write_permit(
            store, protocol, signing, provider,
            permit.root_id,
            runtime="codex",
            agent_session_root="app:agent-session:runtime:intruder",
            work_root="work:court",
            container_root="cde:container:court",
            container_id="GM.nodes.cde-authority",
            container_digest="a" * 64,
            operation="apply_patch",
            path="10.PRODUCT/13.NODE-LANGUAGE/nodelang/cell_cde_authority.py",
            content_digest=content_digest,
            request_id="sec-req-1",
            authorization_evidence="court:write-authorization",
            authority_revision=store.revision,
            now=110.0,
        )


def test_cde_operational_storage_no_monkeypatching_or_global_registries():
    import nodelang.cell_cde_authority as cca
    import nodelang.cde_operational_storage as cos
    from nodelang.cell_cde_authority import ensure_store_cde_storage

    for mod in (cca, cos):
        for attr in dir(mod):
            if attr.startswith("_") and "REGISTRY" in attr.upper():
                raise AssertionError(f"Global registry found in {mod}: {attr}")

    assert "commit" in CellStore.__dict__
    assert "snapshot" in CellStore.__dict__
    assert not getattr(CellStore.commit, "__wrapped__", None)
    assert not getattr(CellStore.snapshot, "__wrapped__", None)

    s1 = CellStore()
    s2 = CellStore()
    st1 = ensure_store_cde_storage(s1)
    st2 = ensure_store_cde_storage(s2)
    assert st1 is not st2


def test_cde_storage_failed_close_retains_handle_for_retry(tmp_path):
    from nodelang.cde_operational_storage import CdeOperationalStorage
    storage = CdeOperationalStorage(tmp_path / "close.sqlite3")
    connection = storage._connection

    class RefusedClose:
        def close(self):
            raise RuntimeError("close refused")

    blocked = RefusedClose()
    storage._connection = blocked
    try:
        with pytest.raises(RuntimeError, match="close refused"):
            storage.close()
        assert not storage.is_closed and storage._connection is blocked
    finally:
        storage._connection = connection
        storage.close()
    assert storage.is_closed and storage._connection is None
    storage.close()


@pytest.mark.parametrize("indexed", (False, True))
def test_issue_reads_legacy_registry_once(indexed, monkeypatch):
    import nodelang.cell_cde_authority as cde
    world = _world()
    store, signing, provider, descriptor, protocol = world
    permit, _, _ = _issue(world)
    values = {name: getattr(permit, name) for name in (
        "runtime", "agent_session_root", "work_root", "container_root",
        "container_id", "container_digest", "operation", "path", "content_digest")}
    values.update(issued_at=100.0, expires_at=160.0,
                  authorization_evidence="court:write-authorization")

    def issue(index):
        return issue_cde_write_permit(
            store, protocol, signing, provider, descriptor,
            permit_id=f"court:linear:{index}", request_id=f"linear-request-{index}",
            nonce=f"linear-nonce-{index}", **values)

    for index in range(6):
        issue(index)
    if indexed:
        cde.ensure_store_cde_storage(store)
    reads = []
    original = cde.read_relation

    def counted(snapshot, root, **kwargs):
        if root == protocol.root_id:
            reads.append(snapshot.revision)
        return original(snapshot, root, **kwargs)

    monkeypatch.setattr(cde, "read_relation", counted)
    before = store.revision
    issue(6)
    assert reads.count(before) == 1
    # 72bcaae (SPEC 3.3, founder order 2026-09-23) deleted the graph-composition
    # issue path: a store without attached storage gets it attached, so both
    # parameters take the indexed path, read the registry once, and never
    # write the new permit into the graph.
    assert len(reads) == 1
    assert store.revision == before
    assert "court:linear:6" not in store.snapshot().cells
    assert store._cde_operational_storage.get_permit("court:linear:6") is not None
    with pytest.raises(InvalidCell, match="not registered"):
        cde._read_cde_write_permit_unchecked(store.snapshot(), protocol, "court:absent")
