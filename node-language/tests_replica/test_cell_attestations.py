"""Security courts for digest-bound, signed graph evidence."""
import hashlib
import json
import pickle

import pytest

from nodelang.cell_attestations import (
    CourtAttestationBroker,
    CourtEvidenceDenied,
    CourtResult,
    bootstrap_attestation_protocol,
    build_court_definition,
    read_court_attestation,
    verify_court_definition,
)
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.universal_cell import Cell, CellStore, InvalidCell


def _build():
    store = CellStore()
    protocol = bootstrap_attestation_protocol(store)
    court = build_court_definition(
        store,
        protocol,
        court_id="court:fixture",
        name="Fixture configuration court",
        builder_id="https://archhub.local/builder/fixture",
        runner_version="1.0.0",
        policy_digest="policy-sha256-fixture",
        checks=("valid-json", "declared-safe"),
    )

    def runner(invocation):
        valid_json = False
        declared_safe = False
        try:
            document = json.loads(invocation.subject_content.decode("utf-8"))
            valid_json = isinstance(document, dict)
            declared_safe = document.get("safe") is True
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        return CourtResult(
            valid_json and declared_safe,
            {
                "valid-json": valid_json,
                "declared-safe": declared_safe,
            },
            {"document": "fixture"},
        )

    broker = CourtAttestationBroker()
    broker.admit_court(store.snapshot(), protocol, court.root_id, runner)
    return store, protocol, court, broker


def _run(store, protocol, court, broker, payload=b'{"safe":true}'):
    return broker.run(
        store,
        protocol,
        court.root_id,
        subject_name="revision:fixture",
        subject_content=payload,
        external_parameters={
            "asset": "asset:fixture",
            "targetState": "SHARED",
        },
    )


def _verify(store, protocol, court, broker, evidence, payload=b'{"safe":true}'):
    return broker.verify(
        store.snapshot(),
        protocol,
        evidence,
        expected_court_root=court.root_id,
        expected_subject_name="revision:fixture",
        expected_subject_digest=hashlib.sha256(payload).hexdigest(),
        expected_parameters={
            "asset": "asset:fixture",
            "targetState": "SHARED",
        },
    )


def test_released_court_and_attestation_are_visible_universal_cells():
    store, protocol, court, broker = _build()
    evidence = _run(store, protocol, court, broker)
    verified = verify_court_definition(
        store.snapshot(), protocol, court.root_id
    )
    projection = read_court_attestation(
        store.snapshot(), protocol, evidence
    )
    statement = _verify(store, protocol, court, broker, evidence)

    assert verified.root_id == court.root_id
    assert projection.court_root == court.root_id
    assert statement["subject"][0]["name"] == "revision:fixture"
    assert statement["predicate"]["result"] == "pass"
    assert statement["predicate"]["checks"] == {
        "declared-safe": True,
        "valid-json": True,
    }
    assert all(type(cell) is Cell for cell in store.snapshot().cells.values())


def test_graph_text_cannot_forge_a_court_pass_or_signer():
    store, protocol, court, broker = _build()
    evidence = _run(store, protocol, court, broker)
    projection = read_court_attestation(
        store.snapshot(), protocol, evidence
    )
    signature = store.read(projection.signature_root)
    store.commit(store.revision, replace=(Cell(
        signature.id,
        signature.link0,
        signature.link1,
        b"agent-says-passed",
    ),))
    with pytest.raises(CourtEvidenceDenied, match="signature"):
        _verify(store, protocol, court, broker, evidence)

    forged = CourtAttestationBroker()
    with pytest.raises(CourtEvidenceDenied, match="not admitted"):
        forged.verify(
            store.snapshot(), protocol, evidence,
            expected_court_root=court.root_id,
            expected_subject_name="revision:fixture",
            expected_subject_digest=hashlib.sha256(b'{"safe":true}').hexdigest(),
            expected_parameters={
                "asset": "asset:fixture", "targetState": "SHARED"
            },
        )
    with pytest.raises(TypeError):
        pickle.dumps(broker)


def test_attestation_is_bound_to_exact_digest_parameters_and_court():
    store, protocol, court, broker = _build()
    payload = b'{"safe":true}'
    evidence = _run(store, protocol, court, broker, payload)
    with pytest.raises(CourtEvidenceDenied, match="exact promotion"):
        broker.verify(
            store.snapshot(), protocol, evidence,
            expected_court_root=court.root_id,
            expected_subject_name="revision:fixture",
            expected_subject_digest=hashlib.sha256(b'{"safe":false}').hexdigest(),
            expected_parameters={
                "asset": "asset:fixture", "targetState": "SHARED"
            },
        )
    with pytest.raises(CourtEvidenceDenied, match="exact promotion"):
        broker.verify(
            store.snapshot(), protocol, evidence,
            expected_court_root=court.root_id,
            expected_subject_name="revision:fixture",
            expected_subject_digest=hashlib.sha256(payload).hexdigest(),
            expected_parameters={
                "asset": "asset:other", "targetState": "SHARED"
            },
        )


def test_failed_runner_result_is_visible_but_cannot_authorize_transition():
    store, protocol, court, broker = _build()
    payload = b'{"safe":false}'
    evidence = _run(store, protocol, court, broker, payload)
    projection = read_court_attestation(
        store.snapshot(), protocol, evidence
    )
    assert projection.result_root == protocol.states["failed"]
    with pytest.raises(CourtEvidenceDenied, match="exact promotion"):
        _verify(store, protocol, court, broker, evidence, payload)


def test_evidence_consumption_is_one_use_per_exact_purpose():
    store, protocol, court, broker = _build()
    payload = b'{"safe":true}'
    evidence = _run(store, protocol, court, broker, payload)
    arguments = dict(
        expected_court_root=court.root_id,
        expected_subject_name="revision:fixture",
        expected_subject_digest=hashlib.sha256(payload).hexdigest(),
        expected_parameters={
            "asset": "asset:fixture", "targetState": "SHARED"
        },
    )
    broker.consume(
        store.snapshot(), protocol, evidence,
        purpose="share:asset:fixture", **arguments,
    )
    with pytest.raises(CourtEvidenceDenied, match="already consumed"):
        broker.consume(
            store.snapshot(), protocol, evidence,
            purpose="share:asset:fixture", **arguments,
        )


def test_court_definition_drift_is_rejected_before_execution():
    store, protocol, court, broker = _build()
    builder = store.read(court.builder_root)
    store.commit(store.revision, replace=(Cell(
        builder.id, builder.link0, builder.link1, b"untrusted-builder"
    ),))
    with pytest.raises(InvalidCell, match="drifted"):
        _run(store, protocol, court, broker)


def test_attestations_survive_restart_and_key_rotation(tmp_path):
    path = tmp_path / "court.sqlite3"
    provider = MemorySigningKeyProvider("durable-court", b"1" * 32)
    store = CellStore(path)
    protocol = bootstrap_attestation_protocol(store, prefix="durable:attestation")
    court = build_court_definition(
        store,
        protocol,
        court_id="durable:court",
        name="Durable court",
        builder_id="https://archhub.local/builder/durable",
        runner_version="1.0.0",
        policy_digest="durable-policy",
        checks=("valid-json", "declared-safe"),
    )

    def runner(invocation):
        document = json.loads(invocation.subject_content.decode("utf-8"))
        checks = {
            "valid-json": isinstance(document, dict),
            "declared-safe": document.get("safe") is True,
        }
        return CourtResult(all(checks.values()), checks, {"court": "durable"})

    broker = CourtAttestationBroker(
        key_provider=provider, key_id="durable-court"
    )
    broker.admit_court(store.snapshot(), protocol, court.root_id, runner)
    first = _run(store, protocol, court, broker)
    provider.rotate("durable-court", b"2" * 32)
    second = _run(store, protocol, court, broker)
    first_projection = read_court_attestation(store.snapshot(), protocol, first)
    second_projection = read_court_attestation(store.snapshot(), protocol, second)
    assert store.read(first_projection.key_version_root).atom == b"1"
    assert store.read(second_projection.key_version_root).atom == b"2"
    store.close()
    database = path.read_bytes()
    assert b"1" * 32 not in database
    assert b"2" * 32 not in database

    reopened = CellStore(path)
    restarted = CourtAttestationBroker(
        key_provider=provider, key_id="durable-court"
    )
    restarted.admit_court(
        reopened.snapshot(), protocol, court.root_id, runner
    )
    assert _verify(reopened, protocol, court, restarted, first)[
        "predicate"
    ]["result"] == "pass"
    assert _verify(reopened, protocol, court, restarted, second)[
        "predicate"
    ]["result"] == "pass"

    wrong = CourtAttestationBroker(
        key_provider=MemorySigningKeyProvider("durable-court", b"z" * 32),
        key_id="durable-court",
    )
    wrong.admit_court(reopened.snapshot(), protocol, court.root_id, runner)
    with pytest.raises(CourtEvidenceDenied, match="signature"):
        _verify(reopened, protocol, court, wrong, first)
    reopened.close()
