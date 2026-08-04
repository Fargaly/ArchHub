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


def test_permit_issue_recovers_one_exact_existing_permit_after_ack_loss():
    world = _world()
    store, signing, provider, descriptor, protocol = world
    permit, revision, content_digest = _issue(world)

    recovered, recovered_revision = issue_cde_write_permit(
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
        issued_at=110.0,
        expires_at=170.0,
        authorization_evidence="court:write-authorization",
    )

    assert recovered == permit
    assert recovered_revision == revision
    assert store.revision == revision
    assert [
        member.participant_id
        for member in read_relation(
            store.snapshot(), protocol.root_id, budget=100_000
        )
        if member.role_id == protocol.role("permit-member")
    ] == [permit.root_id]
    common = {
        "permit_id": "court:cde-permit:1",
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
        "content_digest": content_digest,
        "request_id": "court-write-request-1",
        "authorization_evidence": "court:write-authorization",
    }
    with pytest.raises(CdeWriteDenied, match="nonce mismatched"):
        issue_cde_write_permit(
            store,
            protocol,
            signing,
            provider,
            descriptor,
            **common,
            nonce="court-forged-nonce",
            issued_at=111.0,
            expires_at=171.0,
        )
    with pytest.raises(
        CdeWriteDenied, match="expired or is not yet valid"
    ):
        issue_cde_write_permit(
            store,
            protocol,
            signing,
            provider,
            descriptor,
            **common,
            nonce="court-nonce-1",
            issued_at=161.0,
            expires_at=221.0,
        )


def test_permit_issue_recovers_the_exact_concurrent_commit_winner(monkeypatch):
    world = _world()
    store = world[0]
    original_commit = CellStore.commit
    barrier = threading.Barrier(2)
    results = []
    errors = []

    def race_identical_permits(
        self, expected_revision, *, create=(), replace=(), precommit_guard=None,
    ):
        created = tuple(create)
        if self is store and any(
            cell.id == "court:cde-permit:1" for cell in created
        ):
            barrier.wait(timeout=5)
        return original_commit(
            self,
            expected_revision,
            create=created,
            replace=replace,
            precommit_guard=precommit_guard,
        )

    monkeypatch.setattr(CellStore, "commit", race_identical_permits)

    def issue():
        try:
            results.append(_issue(world)[:2])
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=issue) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert len(results) == 2
    assert results[0] == results[1]
    assert [
        member.participant_id
        for member in read_relation(
            store.snapshot(), world[-1].root_id, budget=100_000
        )
        if member.role_id == world[-1].role("permit-member")
    ] == ["court:cde-permit:1"]


def test_signed_permit_recovers_the_exact_receipt_after_ack_loss():
    world = _world()
    store, signing, provider, _descriptor, protocol = world
    base_revision = store.revision
    permit, revision, content_digest = _issue(world)

    assert revision == base_revision + 1
    changed_roots = frozenset(store.revision_changes(revision))
    assert permit.root_id in changed_roots
    assert permit.signature_envelope_root in changed_roots

    verified = verify_cde_write_permit(
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
    receipt, consumed_revision = consume_cde_write_permit(
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
        request_id="court-write-request-1",
        authorization_evidence="court:write-authorization",
        authority_revision=revision,
        now=120.0,
    )

    assert verified == permit
    assert receipt.permit_root == permit.root_id
    evidence_digest = hashlib.sha256(
        content_digest.encode("ascii")
    ).hexdigest()
    assert receipt.digest == hashlib.sha256(json.dumps(
        {
            "permit": permit.root_id,
            "kind": "consumed",
            "evidence": evidence_digest,
            "recorded-at": "120.000000",
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")).hexdigest()
    assert consumed_revision == revision + 1
    assert read_cde_write_permit(
        store.snapshot(), protocol, permit.root_id
    ).state_root == protocol.states["consumed"]
    recovered, recovered_revision = consume_cde_write_permit(
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
        request_id="court-write-request-1",
        authorization_evidence="court:write-authorization",
        authority_revision=consumed_revision,
        now=200.0,
    )
    assert recovered == receipt
    assert recovered_revision == consumed_revision
    assert store.revision == consumed_revision

    with pytest.raises(CdeWriteDenied, match="request mismatched"):
        consume_cde_write_permit(
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
            request_id="court-write-request-forged",
            authorization_evidence="court:write-authorization",
            authority_revision=consumed_revision,
            now=200.0,
        )


def test_permit_commit_conflict_leaves_no_orphan_signature_or_permit(monkeypatch):
    world = _world()
    store = world[0]
    original_commit = CellStore.commit

    def conflict_on_permit(self, expected_revision, *, create=(), replace=(),
                           precommit_guard=None):
        created = tuple(create)
        if self is store and any(
            cell.id == "court:cde-permit:1" for cell in created
        ):
            raise Conflict("court conflict")
        return original_commit(
            self,
            expected_revision,
            create=created,
            replace=replace,
            precommit_guard=precommit_guard,
        )

    monkeypatch.setattr(CellStore, "commit", conflict_on_permit)

    with pytest.raises(Conflict, match="court conflict"):
        _issue(world)

    snapshot = store.snapshot()
    assert "court:cde-permit:1" not in snapshot.cells
    assert "court:cde-permit:1:signature" not in snapshot.cells


def test_consumption_can_join_one_larger_atomic_graph_commit():
    world = _world()
    store, signing, provider, _descriptor, protocol = world
    permit, revision, content_digest = _issue(world)
    snapshot = store.snapshot()
    marker = Cell(
        "court:source-revision:accepted",
        NULL_CELL_ID,
        NULL_CELL_ID,
        content_digest.encode("ascii"),
    )

    patch = prepare_cde_write_consumption(
        snapshot,
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
    accepted = store.commit(
        patch.expected_revision,
        create=(*patch.create, marker),
        replace=patch.replace,
    )

    assert accepted == revision + 1
    assert store.read(marker.id) == marker
    assert read_cde_write_permit(
        store.snapshot(), protocol, permit.root_id
    ).state_root == protocol.states["consumed"]
    assert patch.receipt.permit_root == permit.root_id


def test_unrelated_commit_preserves_exact_reauthorized_permit():
    world = _world()
    store, signing, provider, _descriptor, protocol = world
    permit, issued_revision, content_digest = _issue(world)
    store.commit(store.revision, create=(Cell(
        "court:unrelated:observation",
        NULL_CELL_ID,
        NULL_CELL_ID,
        b"unrelated accepted graph fact",
    ),))
    current_revision = store.revision

    verified = verify_cde_write_permit(
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
        authority_revision=current_revision,
        now=120.0,
    )
    receipt, consumed_revision = consume_cde_write_permit(
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
        request_id="court-write-request-1",
        authorization_evidence="court:write-authorization",
        authority_revision=current_revision,
        now=120.0,
    )

    assert current_revision == issued_revision + 1
    assert verified == permit
    assert receipt.permit_root == permit.root_id
    assert consumed_revision == current_revision + 1


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


def test_signed_payload_tamper_and_revocation_fail_closed():
    world = _world()
    store, signing, provider, _descriptor, protocol = world
    permit, revision, content_digest = _issue(world)
    path_root = permit.field_roots["path"]
    original = store.read(path_root)
    store.commit(
        store.revision,
        replace=(replace(original, atom=b"10.PRODUCT/other.py"),),
    )

    with pytest.raises((InvalidCell, CdeWriteDenied)):
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


@pytest.mark.parametrize("replayed", ("nonce", "request"))
def test_permit_issue_denies_replayed_nonce_or_request(replayed):
    world = _world()
    store, signing, provider, descriptor, protocol = world
    _permit, _revision, content_digest = _issue(world)
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
