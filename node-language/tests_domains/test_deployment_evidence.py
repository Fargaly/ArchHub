import json

import pytest

from nodelang import Store, validate_store
from nodelang.deployment_evidence import (
    DEPLOYMENT_EVIDENCE_ENV,
    build_deployment_evidence,
    load_deployment_evidence,
)


def _receipt():
    return {
        "provider": "sites", "project_ref": "project-opaque",
        "version_ref": "version-opaque", "deployment_ref": "deployment-opaque",
        "url": "https://example.invalid", "status": "succeeded",
        "visibility": "private", "observed_at": "2026-07-12T21:16:02Z",
        "source_commit": "3da6fbd", "content_hash": "sha256:abc",
    }


def test_receipt_is_a_parametric_group_with_a_computed_gate():
    store = Store()
    result = build_deployment_evidence(store, _receipt())
    assert store.nodes[result["session"]]["kind"] == "session"
    assert store.nodes[result["group"]]["kind"] == "group"
    assert all(store.nodes[node_id]["kind"] == "param"
               for node_id in result["fields"].values())
    assert store.pull(result["record"])["url"] == "https://example.invalid"
    assert store.pull(result["gate"]) == 1
    store.edit(result["fields"]["content_hash"],
               ["body", "floor", "value"], "", actor="test")
    assert store.pull(result["gate"]) == 0
    assert validate_store(store) is True


def test_missing_local_receipt_builds_the_same_closed_composition(tmp_path, monkeypatch):
    monkeypatch.setenv(DEPLOYMENT_EVIDENCE_ENV, str(tmp_path / "missing.json"))
    record = load_deployment_evidence()
    assert record["status"] == "not-connected"
    store = Store()
    result = build_deployment_evidence(store)
    assert store.pull(result["gate"]) == 0


def test_local_receipt_rejects_credentials_and_non_https(tmp_path, monkeypatch):
    path = tmp_path / "receipt.json"
    monkeypatch.setenv(DEPLOYMENT_EVIDENCE_ENV, str(path))
    bad = _receipt() | {"content_hash": "token=raw-secret"}
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="credentials"):
        load_deployment_evidence()
    path.write_text(json.dumps(_receipt() | {"url": "http://unsafe"}), encoding="utf-8")
    with pytest.raises(ValueError, match="HTTPS"):
        load_deployment_evidence()
