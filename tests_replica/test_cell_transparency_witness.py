from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import threading

import pytest

import nodelang.cell_transparency_witness as witness_module
from nodelang.cell_protocols import read_relation
from nodelang.cell_signing_authority import (
    LocalEd25519KmsProvider,
    bootstrap_signing_authority_protocol,
    build_signing_key_descriptor,
    project_signing_authority_protocol,
    read_signing_key_descriptor,
)
from nodelang.cell_transparency_witness import (
    GraphWitnessService,
    TransparencyDenied,
    WITNESS_SIGNING_PURPOSE,
    WitnessAdmission,
    WitnessReceiptEvidence,
    append_transparency_leaf,
    bootstrap_transparency_protocol,
    build_log_consistency_proof,
    build_transparency_log,
    build_witness_policy,
    build_witness_state_log,
    consistency_proof,
    inclusion_proof,
    issue_transparency_checkpoint,
    latest_witness_state,
    merkle_head,
    merkle_tree_hash,
    project_transparency_protocol,
    read_consistency_proof,
    read_log_leaves,
    read_transparency_checkpoint,
    read_transparency_log,
    read_witness_policy,
    read_witness_receipt,
    verify_consistency_proof,
    verify_inclusion_proof,
    verify_transparency_checkpoint,
    verify_witness_quorum,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


POLICY_ROOT = "court:witness-policy"
POLICY_DIGEST = "sha256:" + "a" * 64


def _entries(count: int):
    return tuple(("leaf-%04d" % index).encode("ascii") for index in range(count))


def _system(path=None):
    store = CellStore(path)
    signing = bootstrap_signing_authority_protocol(
        store, prefix="court:log-signing"
    )
    provider = LocalEd25519KmsProvider(
        provider_id="transparency-log", authority_id="archhub-history"
    )
    descriptor = build_signing_key_descriptor(
        store,
        signing,
        provider,
        descriptor_id="court:log-key:v1",
        resource_version=provider.current_resource,
        authority_id="archhub-history",
        purpose="transparency-checkpoint",
        valid_from="2026-01-01T00:00:00Z",
        valid_until="2030-01-01T00:00:00Z",
        authorization_evidence="court:log-authorization",
        release_evidence="court:log-release",
    )
    protocol = bootstrap_transparency_protocol(
        store, prefix="court:transparency"
    )
    log = build_transparency_log(
        store,
        protocol,
        log_id="court:transparency-log",
        origin="archhub.example/history",
    )
    return store, protocol, signing, provider, descriptor, log


def _witness(name: str, path=None):
    store = CellStore(path)
    signing = bootstrap_signing_authority_protocol(
        store, prefix="court:%s:signing" % name
    )
    provider = LocalEd25519KmsProvider(
        provider_id="witness-%s" % name,
        authority_id="archhub-history",
    )
    descriptor = build_signing_key_descriptor(
        store,
        signing,
        provider,
        descriptor_id="court:%s:key:v1" % name,
        resource_version=provider.current_resource,
        authority_id="archhub-history",
        purpose=WITNESS_SIGNING_PURPOSE,
        valid_from="2026-01-01T00:00:00Z",
        valid_until="2030-01-01T00:00:00Z",
        authorization_evidence="court:%s:authorization" % name,
        release_evidence="court:%s:release" % name,
    )
    transparency = bootstrap_transparency_protocol(
        store, prefix="court:%s:transparency" % name
    )
    state_log = build_witness_state_log(
        store,
        transparency,
        state_log_id="court:%s:state-log" % name,
        witness_id=name,
    )
    service = GraphWitnessService(
        store=store,
        transparency_protocol=transparency,
        signing_protocol=signing,
        provider=provider,
        descriptor_root=descriptor,
        state_log_root=state_log,
        witness_id=name,
    )
    return {
        "name": name,
        "store": store,
        "signing": signing,
        "provider": provider,
        "descriptor": descriptor,
        "transparency": transparency,
        "state_log": state_log,
        "service": service,
    }


def _admission(witness, *, state="active"):
    descriptor = read_signing_key_descriptor(
        witness["store"].snapshot(),
        witness["signing"],
        witness["descriptor"],
    )
    return WitnessAdmission(
        witness["name"],
        witness["descriptor"],
        descriptor.digest,
        state,
    )


def _evidence(witness, receipt):
    return WitnessReceiptEvidence(
        witness["store"],
        witness["transparency"],
        witness["signing"],
        witness["provider"],
        witness["descriptor"],
        witness["state_log"],
        receipt,
    )


def _cosign(witness, system, checkpoint, policy, proof):
    store, protocol, signing, provider, descriptor, log = system
    return witness["service"].cosign(
        log_snapshot=store.snapshot(),
        log_protocol=protocol,
        log_signing_protocol=signing,
        log_provider=provider,
        log_descriptor_root=descriptor,
        log_root=log,
        checkpoint_root=checkpoint,
        policy_root=policy,
        proof_root=proof,
    )


def test_rfc9162_tree_hash_domain_separation_and_basic_vectors():
    assert merkle_tree_hash(()) == hashlib.sha256(b"").digest()
    assert merkle_tree_hash((b"alpha",)) == hashlib.sha256(
        b"\x00alpha"
    ).digest()
    left = hashlib.sha256(b"\x00alpha").digest()
    right = hashlib.sha256(b"\x00beta").digest()
    assert merkle_tree_hash((b"alpha", b"beta")) == hashlib.sha256(
        b"\x01" + left + right
    ).digest()
    assert merkle_tree_hash((b"alpha",)) != hashlib.sha256(b"alpha").digest()


@pytest.mark.parametrize("size", tuple(range(1, 66)) + (127, 128, 129, 255, 256, 257))
def test_rfc9162_inclusion_proofs_verify_and_mutations_fail(size: int):
    entries = _entries(size)
    root = merkle_tree_hash(entries)
    indexes = tuple(dict.fromkeys((0, size // 2, size - 1)))
    for index in indexes:
        proof = inclusion_proof(entries, index)
        leaf_hash = hashlib.sha256(b"\x00" + entries[index]).digest()
        assert verify_inclusion_proof(leaf_hash, index, size, root, proof)
        assert not verify_inclusion_proof(
            leaf_hash, index, size, root, proof + (b"x" * 32,)
        )
        if proof:
            changed = (bytes([proof[0][0] ^ 1]) + proof[0][1:], *proof[1:])
            assert not verify_inclusion_proof(
                leaf_hash, index, size, root, changed
            )


@pytest.mark.parametrize("new_size", tuple(range(1, 66)) + (127, 128, 129, 255, 256, 257))
def test_rfc9162_consistency_all_boundaries_and_mutations(new_size: int):
    entries = _entries(new_size)
    new_root = merkle_tree_hash(entries)
    old_sizes = set((0, 1, new_size // 2, max(0, new_size - 1), new_size))
    old_sizes.update(
        value for value in (2, 3, 4, 7, 8, 15, 16, 31, 32, 63, 64, 127, 128, 255, 256)
        if value <= new_size
    )
    for old_size in sorted(old_sizes):
        old_root = merkle_tree_hash(entries[:old_size])
        proof = consistency_proof(entries, old_size)
        assert verify_consistency_proof(
            old_size, new_size, old_root, new_root, proof
        )
        if 0 < old_size < new_size:
            assert not verify_consistency_proof(
                old_size, new_size, old_root, new_root, proof + (b"x" * 32,)
            )
            if proof:
                changed = (
                    bytes([proof[0][0] ^ 1]) + proof[0][1:],
                    *proof[1:],
                )
                assert not verify_consistency_proof(
                    old_size, new_size, old_root, new_root, changed
                )


def test_rfc9162_rejects_invalid_sizes_roots_and_empty_proofs():
    entries = _entries(7)
    old_root = merkle_tree_hash(entries[:3])
    new_root = merkle_tree_hash(entries)

    assert not verify_consistency_proof(3, 7, old_root, new_root, ())
    assert not verify_consistency_proof(8, 7, old_root, new_root, ())
    assert not verify_consistency_proof(3, 7, b"short", new_root, ())
    assert not verify_inclusion_proof(b"short", 0, 7, new_root, ())
    with pytest.raises(ValueError):
        consistency_proof(entries, 8)
    with pytest.raises(ValueError):
        inclusion_proof(entries, 7)


def test_log_leaves_proofs_and_signed_checkpoints_are_universal_cells(tmp_path):
    path = tmp_path / "transparency.sqlite3"
    store, protocol, signing, provider, descriptor, log = _system(path)
    first_leaf = append_transparency_leaf(store, protocol, log, b"checkpoint-1")
    first = issue_transparency_checkpoint(
        store,
        protocol,
        signing,
        provider,
        descriptor,
        log,
        policy_root=POLICY_ROOT,
        policy_digest=POLICY_DIGEST,
        authorization_evidence="court:log-authorization",
        checkpoint_id="court:checkpoint:1",
        issued_at="2026-07-17T10:00:00Z",
    )
    append_transparency_leaf(store, protocol, log, b"checkpoint-2")
    append_transparency_leaf(store, protocol, log, b"checkpoint-3")
    second = issue_transparency_checkpoint(
        store,
        protocol,
        signing,
        provider,
        descriptor,
        log,
        policy_root=POLICY_ROOT,
        policy_digest=POLICY_DIGEST,
        authorization_evidence="court:log-authorization",
        checkpoint_id="court:checkpoint:3",
        issued_at="2026-07-17T10:01:00Z",
    )
    snapshot = store.snapshot()
    first_projection = verify_transparency_checkpoint(
        snapshot,
        protocol,
        signing,
        provider,
        descriptor,
        log,
        first,
        expected_policy_root=POLICY_ROOT,
        expected_policy_digest=POLICY_DIGEST,
    )
    second_projection = verify_transparency_checkpoint(
        snapshot,
        protocol,
        signing,
        provider,
        descriptor,
        log,
        second,
        expected_policy_root=POLICY_ROOT,
        expected_policy_digest=POLICY_DIGEST,
    )
    proof = read_consistency_proof(
        snapshot, protocol, second_projection.proof_root
    )

    assert first_projection.tree_size == 1
    assert second_projection.tree_size == 3
    assert second_projection.previous_size == 1
    assert proof.old_size == 1 and proof.new_size == 3
    assert first_leaf == read_log_leaves(snapshot, protocol, log)[0].root_id
    assert read_transparency_log(snapshot, protocol, log).checkpoint_roots == (
        first,
        second,
    )
    assert all(isinstance(cell, Cell) for cell in snapshot.cells.values())

    store.close()
    reopened = CellStore(path)
    reopened_signing = project_signing_authority_protocol(
        reopened.snapshot(), prefix="court:log-signing"
    )
    reopened_protocol = project_transparency_protocol(
        reopened.snapshot(), prefix="court:transparency"
    )
    verify_transparency_checkpoint(
        reopened.snapshot(),
        reopened_protocol,
        reopened_signing,
        provider,
        descriptor,
        log,
        second,
        expected_policy_root=POLICY_ROOT,
        expected_policy_digest=POLICY_DIGEST,
    )
    reopened.close()


def test_log_tampering_and_checkpoint_policy_substitution_fail_closed():
    store, protocol, signing, provider, descriptor, log = _system()
    append_transparency_leaf(store, protocol, log, b"checkpoint")
    checkpoint = issue_transparency_checkpoint(
        store,
        protocol,
        signing,
        provider,
        descriptor,
        log,
        policy_root=POLICY_ROOT,
        policy_digest=POLICY_DIGEST,
        authorization_evidence="court:log-authorization",
        checkpoint_id="court:checkpoint",
        issued_at="2026-07-17T10:00:00Z",
    )

    with pytest.raises(TransparencyDenied, match="policy"):
        verify_transparency_checkpoint(
            store.snapshot(),
            protocol,
            signing,
            provider,
            descriptor,
            log,
            checkpoint,
            expected_policy_root="court:other-policy",
            expected_policy_digest=POLICY_DIGEST,
        )

    root = checkpoint + ":root-hash"
    original = store.read(root)
    store.commit(
        store.revision,
        replace=(Cell(
            original.id,
            original.link0,
            original.link1,
            ("sha256:" + "0" * 64).encode("ascii"),
        ),),
    )
    with pytest.raises(InvalidCell, match="digest mismatched"):
        read_transparency_checkpoint(store.snapshot(), protocol, checkpoint)


def test_independent_witness_receipts_require_distinct_policy_quorum():
    system = _system()
    store, protocol, signing, provider, descriptor, log = system
    witnesses = tuple(_witness("witness-%d" % index) for index in range(3))
    policy_root = build_witness_policy(
        store,
        protocol,
        policy_id="court:quorum-policy",
        origin="archhub.example/history",
        threshold=2,
        admissions=tuple(_admission(witness) for witness in witnesses),
    )
    policy = read_witness_policy(store.snapshot(), protocol, policy_root)
    append_transparency_leaf(store, protocol, log, b"release-1")
    checkpoint = issue_transparency_checkpoint(
        store,
        protocol,
        signing,
        provider,
        descriptor,
        log,
        policy_root=policy_root,
        policy_digest=policy.digest,
        authorization_evidence="court:log-authorization",
        checkpoint_id="court:quorum-checkpoint:1",
        issued_at="2026-07-17T10:00:00Z",
    )
    projected = read_transparency_checkpoint(
        store.snapshot(), protocol, checkpoint
    )
    receipts = tuple(
        _cosign(witness, system, checkpoint, policy_root, projected.proof_root)
        for witness in witnesses[:2]
    )
    evidence = tuple(
        _evidence(witness, receipt)
        for witness, receipt in zip(witnesses, receipts)
    )

    verified = verify_witness_quorum(
        log_snapshot=store.snapshot(),
        log_protocol=protocol,
        log_signing_protocol=signing,
        log_provider=provider,
        log_descriptor_root=descriptor,
        log_root=log,
        checkpoint_root=checkpoint,
        policy_root=policy_root,
        evidence=evidence,
    )
    assert {receipt.witness_id for receipt in verified} == {
        "witness-0",
        "witness-1",
    }

    with pytest.raises(TransparencyDenied, match="threshold"):
        verify_witness_quorum(
            log_snapshot=store.snapshot(),
            log_protocol=protocol,
            log_signing_protocol=signing,
            log_provider=provider,
            log_descriptor_root=descriptor,
            log_root=log,
            checkpoint_root=checkpoint,
            policy_root=policy_root,
            evidence=evidence[:1],
        )
    with pytest.raises(TransparencyDenied, match="duplicate"):
        verify_witness_quorum(
            log_snapshot=store.snapshot(),
            log_protocol=protocol,
            log_signing_protocol=signing,
            log_provider=provider,
            log_descriptor_root=descriptor,
            log_root=log,
            checkpoint_root=checkpoint,
            policy_root=policy_root,
            evidence=(evidence[0], evidence[0]),
        )


def test_witness_restart_accepts_missed_checkpoint_and_rejects_rollback(tmp_path):
    system = _system()
    store, protocol, signing, provider, descriptor, log = system
    path = tmp_path / "witness.sqlite3"
    witness = _witness("durable-witness", path)
    policy_root = build_witness_policy(
        store,
        protocol,
        policy_id="court:durable-policy",
        origin="archhub.example/history",
        threshold=1,
        admissions=(_admission(witness),),
    )
    policy = read_witness_policy(store.snapshot(), protocol, policy_root)

    append_transparency_leaf(store, protocol, log, b"release-1")
    checkpoint_1 = issue_transparency_checkpoint(
        store,
        protocol,
        signing,
        provider,
        descriptor,
        log,
        policy_root=policy_root,
        policy_digest=policy.digest,
        authorization_evidence="court:log-authorization",
        checkpoint_id="court:durable-checkpoint:1",
    )
    checkpoint_1_projection = read_transparency_checkpoint(
        store.snapshot(), protocol, checkpoint_1
    )
    _cosign(
        witness,
        system,
        checkpoint_1,
        policy_root,
        checkpoint_1_projection.proof_root,
    )
    witness["store"].close()

    append_transparency_leaf(store, protocol, log, b"release-2")
    issue_transparency_checkpoint(
        store,
        protocol,
        signing,
        provider,
        descriptor,
        log,
        policy_root=policy_root,
        policy_digest=policy.digest,
        authorization_evidence="court:log-authorization",
        checkpoint_id="court:durable-checkpoint:2",
    )
    append_transparency_leaf(store, protocol, log, b"release-3")
    checkpoint_3 = issue_transparency_checkpoint(
        store,
        protocol,
        signing,
        provider,
        descriptor,
        log,
        policy_root=policy_root,
        policy_digest=policy.digest,
        authorization_evidence="court:log-authorization",
        checkpoint_id="court:durable-checkpoint:3",
    )
    proof_1_to_3 = build_log_consistency_proof(
        store, protocol, log, old_size=1, new_size=3
    )

    reopened_store = CellStore(path)
    reopened_signing = project_signing_authority_protocol(
        reopened_store.snapshot(), prefix="court:durable-witness:signing"
    )
    reopened_transparency = project_transparency_protocol(
        reopened_store.snapshot(), prefix="court:durable-witness:transparency"
    )
    reopened_service = GraphWitnessService(
        store=reopened_store,
        transparency_protocol=reopened_transparency,
        signing_protocol=reopened_signing,
        provider=witness["provider"],
        descriptor_root=witness["descriptor"],
        state_log_root=witness["state_log"],
        witness_id=witness["name"],
    )
    reopened = {
        **witness,
        "store": reopened_store,
        "signing": reopened_signing,
        "transparency": reopened_transparency,
        "service": reopened_service,
    }
    receipt_3 = _cosign(
        reopened, system, checkpoint_3, policy_root, proof_1_to_3
    )
    latest = latest_witness_state(
        reopened_store.snapshot(),
        reopened_transparency,
        witness["state_log"],
    )
    assert latest is not None
    assert latest.tree_size == 3 and latest.receipt_root == receipt_3

    with pytest.raises(TransparencyDenied, match="roll history back"):
        _cosign(
            reopened,
            system,
            checkpoint_1,
            policy_root,
            checkpoint_1_projection.proof_root,
        )


def test_witness_rejects_same_size_split_view():
    canonical = _system()
    store, protocol, signing, provider, descriptor, log = canonical
    witness = _witness("split-witness")
    policy_root = build_witness_policy(
        store,
        protocol,
        policy_id="court:split-policy",
        origin="archhub.example/history",
        threshold=1,
        admissions=(_admission(witness),),
    )
    policy = read_witness_policy(store.snapshot(), protocol, policy_root)
    append_transparency_leaf(store, protocol, log, b"shared-release")
    append_transparency_leaf(store, protocol, log, b"canonical-release")
    checkpoint = issue_transparency_checkpoint(
        store,
        protocol,
        signing,
        provider,
        descriptor,
        log,
        policy_root=policy_root,
        policy_digest=policy.digest,
        authorization_evidence="court:log-authorization",
    )
    projection = read_transparency_checkpoint(store.snapshot(), protocol, checkpoint)
    _cosign(witness, canonical, checkpoint, policy_root, projection.proof_root)

    alternate = _system()
    alt_store, alt_protocol, alt_signing, alt_provider, alt_descriptor, alt_log = alternate
    alt_policy_root = build_witness_policy(
        alt_store,
        alt_protocol,
        policy_id="court:split-policy",
        origin="archhub.example/history",
        threshold=1,
        admissions=(_admission(witness),),
    )
    alt_policy = read_witness_policy(
        alt_store.snapshot(), alt_protocol, alt_policy_root
    )
    assert alt_policy.digest == policy.digest
    append_transparency_leaf(alt_store, alt_protocol, alt_log, b"shared-release")
    append_transparency_leaf(alt_store, alt_protocol, alt_log, b"forked-release")
    alt_checkpoint = issue_transparency_checkpoint(
        alt_store,
        alt_protocol,
        alt_signing,
        alt_provider,
        alt_descriptor,
        alt_log,
        policy_root=alt_policy_root,
        policy_digest=alt_policy.digest,
        authorization_evidence="court:log-authorization",
    )
    alt_projection = read_transparency_checkpoint(
        alt_store.snapshot(), alt_protocol, alt_checkpoint
    )
    with pytest.raises(TransparencyDenied, match="split root"):
        _cosign(
            witness,
            alternate,
            alt_checkpoint,
            alt_policy_root,
            alt_projection.proof_root,
        )


def test_witness_receipt_follows_declared_state_log_and_tampering_fails():
    system = _system()
    store, protocol, signing, provider, descriptor, log = system
    witness = _witness("strict-witness")
    policy_root = build_witness_policy(
        store,
        protocol,
        policy_id="court:strict-policy",
        origin="archhub.example/history",
        threshold=1,
        admissions=(_admission(witness),),
    )
    policy = read_witness_policy(store.snapshot(), protocol, policy_root)
    append_transparency_leaf(store, protocol, log, b"release")
    checkpoint = issue_transparency_checkpoint(
        store,
        protocol,
        signing,
        provider,
        descriptor,
        log,
        policy_root=policy_root,
        policy_digest=policy.digest,
        authorization_evidence="court:log-authorization",
    )
    projection = read_transparency_checkpoint(store.snapshot(), protocol, checkpoint)
    receipt = _cosign(
        witness, system, checkpoint, policy_root, projection.proof_root
    )
    evidence = _evidence(witness, receipt)

    witness["store"].commit(
        witness["store"].revision,
        create=(Cell(
            "unrelated:state",
            NULL_CELL_ID,
            NULL_CELL_ID,
            b"not-witness-state",
        ),),
    )
    assert verify_witness_quorum(
        log_snapshot=store.snapshot(),
        log_protocol=protocol,
        log_signing_protocol=signing,
        log_provider=provider,
        log_descriptor_root=descriptor,
        log_root=log,
        checkpoint_root=checkpoint,
        policy_root=policy_root,
        evidence=(evidence,),
    )[0].root_id == receipt

    digest_root = receipt + ":receipt-digest"
    original = witness["store"].read(digest_root)
    witness["store"].commit(
        witness["store"].revision,
        replace=(Cell(
            original.id,
            original.link0,
            original.link1,
            ("sha256:" + "0" * 64).encode("ascii"),
        ),),
    )
    with pytest.raises(InvalidCell, match="digest mismatched"):
        read_witness_receipt(
            witness["store"].snapshot(), witness["transparency"], receipt
        )


def test_checkpoint_verification_requires_the_exact_log_key_descriptor():
    store, protocol, signing, provider, descriptor, log = _system()
    append_transparency_leaf(store, protocol, log, b"release")
    checkpoint = issue_transparency_checkpoint(
        store,
        protocol,
        signing,
        provider,
        descriptor,
        log,
        policy_root=POLICY_ROOT,
        policy_digest=POLICY_DIGEST,
        authorization_evidence="court:log-authorization",
    )
    provider.rotate()
    substituted = build_signing_key_descriptor(
        store,
        signing,
        provider,
        descriptor_id="court:log-key:v2",
        resource_version=provider.current_resource,
        authority_id="archhub-history",
        purpose="transparency-checkpoint",
        valid_from="2026-01-01T00:00:00Z",
        valid_until="2030-01-01T00:00:00Z",
        predecessor_descriptor=descriptor,
        authorization_evidence="court:log-authorization:v2",
        release_evidence="court:log-release:v2",
    )
    with pytest.raises(TransparencyDenied, match="descriptor mismatched"):
        verify_transparency_checkpoint(
            store.snapshot(),
            protocol,
            signing,
            provider,
            substituted,
            log,
            checkpoint,
            expected_policy_root=POLICY_ROOT,
            expected_policy_digest=POLICY_DIGEST,
        )


def test_policy_threshold_cannot_count_disabled_witnesses():
    store, protocol, *_ = _system()
    active = _witness("active-witness")
    disabled = _witness("disabled-witness")
    with pytest.raises(InvalidCell, match="threshold"):
        build_witness_policy(
            store,
            protocol,
            policy_id="court:invalid-policy",
            origin="archhub.example/history",
            threshold=2,
            admissions=(
                _admission(active),
                _admission(disabled, state="disabled"),
            ),
        )


def test_concurrent_witness_calls_cannot_corrupt_monotonic_state(monkeypatch):
    system = _system()
    store, protocol, signing, provider, descriptor, log = system
    witness = _witness("concurrent-witness")
    second_service = GraphWitnessService(
        store=witness["store"],
        transparency_protocol=witness["transparency"],
        signing_protocol=witness["signing"],
        provider=witness["provider"],
        descriptor_root=witness["descriptor"],
        state_log_root=witness["state_log"],
        witness_id=witness["name"],
    )
    policy_root = build_witness_policy(
        store,
        protocol,
        policy_id="court:concurrent-policy",
        origin="archhub.example/history",
        threshold=1,
        admissions=(_admission(witness),),
    )
    policy = read_witness_policy(store.snapshot(), protocol, policy_root)
    append_transparency_leaf(store, protocol, log, b"release")
    checkpoint = issue_transparency_checkpoint(
        store,
        protocol,
        signing,
        provider,
        descriptor,
        log,
        policy_root=policy_root,
        policy_digest=policy.digest,
        authorization_evidence="court:log-authorization",
    )
    proof = read_transparency_checkpoint(
        store.snapshot(), protocol, checkpoint
    ).proof_root

    original_sign = witness_module.sign_statement
    serial_signing = threading.Lock()
    both_envelopes_persisted = threading.Barrier(2)

    def coordinated_sign(*args, **kwargs):
        with serial_signing:
            result = original_sign(*args, **kwargs)
        both_envelopes_persisted.wait(timeout=5)
        return result

    monkeypatch.setattr(witness_module, "sign_statement", coordinated_sign)

    def run(service):
        local = {**witness, "service": service}
        return _cosign(local, system, checkpoint, policy_root, proof)

    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = tuple(pool.map(run, (witness["service"], second_service)))

    assert len(set(receipts)) == 1
    latest = latest_witness_state(
        witness["store"].snapshot(),
        witness["transparency"],
        witness["state_log"],
    )
    assert latest is not None and latest.receipt_root == receipts[0]
    members = read_relation(
        witness["store"].snapshot(), witness["state_log"]
    )
    state_role = witness["transparency"].role("witness-state-log-state")
    assert sum(member.role_id == state_role for member in members) == 1
