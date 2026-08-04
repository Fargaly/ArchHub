from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.clean_runtime_bootstrap import provision_clean_runtime
from nodelang.runtime_caller_capability import WindowsDpapiCallerKeyStore
from nodelang.unified_authority_runtime import open_current_authority
from nodelang.universal_cell import InvalidCell


pytestmark = pytest.mark.skipif(
    __import__("os").name != "nt",
    reason="the production caller-key boundary uses Windows DPAPI",
)


def _map_source() -> bytes:
    payload = [{
        "key": "brain",
        "title": "Brain and Memory",
        "nodes": [{
            "id": "brain_attention",
            "cat": "behavior",
            "title": "Persistent attention",
            "sub": "Keep accepted work visible",
            "status": "partial",
            "params": [],
            "evidence_ref": "court:bootstrap",
            "authority_source": "founder",
        }],
        "wires": [],
        "cross": [],
    }]
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def test_clean_runtime_selects_only_complete_sources_and_replays_zero(tmp_path):
    root = tmp_path / "runtime"
    provider = MemorySigningKeyProvider(
        "archhub.unified.bootstrap",
        b"clean-bootstrap-authority-key" + b"0" * 5,
    )
    caller_keys = WindowsDpapiCallerKeyStore(tmp_path / "caller.dpapi.json")
    specification = (Path(__file__).parents[1] / "SPEC.md").read_bytes()
    grand_map = _map_source()
    request = {
        "caller_key_id": "founder.bootstrap",
        "specification_source": specification,
        "specification_sha256": hashlib.sha256(specification).hexdigest(),
        "grand_map_source": grand_map,
        "grand_map_sha256": hashlib.sha256(grand_map).hexdigest(),
    }
    first = provision_clean_runtime(
        root,
        provider,
        caller_keys,
        **request,
    )
    graph_id = first.location.authority.manifest.graph_id
    revision = first.location.authority.store.revision
    cell_count = len(first.location.authority.store.snapshot().cells)
    assert first.specification.replayed is False
    assert first.grand_map.replayed is False
    assert first.sessions.definition_root in first.location.authority.store.snapshot().cells
    assert first.workshop.message_definition in first.location.authority.store.snapshot().cells
    assert first.visual.graph_id == graph_id
    assert first.visual.root_id in first.location.authority.store.snapshot().cells
    assert len(first.visual.template_roots) == 22
    assert first.browser.graph_id == graph_id
    assert first.browser.root_id in first.location.authority.store.snapshot().cells
    assert (root / "CURRENT").read_text() == graph_id
    first.location.authority.store.close()

    second = provision_clean_runtime(
        root,
        provider,
        caller_keys,
        **request,
    )
    try:
        assert second.location.authority.manifest.graph_id == graph_id
        assert second.location.authority.store.revision == revision
        assert len(second.location.authority.store.snapshot().cells) == cell_count
        assert second.visual.root_id == first.visual.root_id
        assert second.visual.template_roots == first.visual.template_roots
        assert second.browser.root_id == first.browser.root_id
        assert second.browser.protocol.root_id == first.browser.protocol.root_id
        assert second.specification.replayed is True
        assert second.grand_map.replayed is True
    finally:
        second.location.authority.store.close()

    verified = open_current_authority(root, provider)
    try:
        assert verified.authority.store.revision == revision
        assert len(verified.authority.store.snapshot().cells) == cell_count
    finally:
        verified.authority.store.close()


def test_clean_runtime_builds_full_accepted_sources_and_replays_zero(tmp_path):
    root = tmp_path / "runtime"
    provider = MemorySigningKeyProvider(
        "archhub.unified.bootstrap",
        b"clean-full-authority-key" + b"0" * 8,
    )
    caller_keys = WindowsDpapiCallerKeyStore(tmp_path / "caller.dpapi.json")
    node_language = Path(__file__).parents[1]
    workspace = Path(__file__).parents[3]
    specification = (node_language / "SPEC.md").read_bytes()
    grand_map_path = (
        workspace
        / "30.KNOWLEDGE"
        / "grand-map"
        / "data"
        / "grand_domains.json"
    )
    grand_map = grand_map_path.read_bytes()
    decoded_map = json.loads(grand_map.decode("utf-8"))
    domain_count = len(decoded_map)
    requirement_count = sum(len(domain["nodes"]) for domain in decoded_map)
    relation_count = sum(
        len(domain["wires"]) + len(domain["cross"])
        for domain in decoded_map
    )
    request = {
        "caller_key_id": "founder.full-bootstrap",
        "specification_source": specification,
        "specification_sha256": hashlib.sha256(specification).hexdigest(),
        "grand_map_source": grand_map,
        "grand_map_sha256": hashlib.sha256(grand_map).hexdigest(),
    }

    first = provision_clean_runtime(root, provider, caller_keys, **request)
    graph_id = first.location.authority.manifest.graph_id
    revision = first.location.authority.store.revision
    cell_count = len(first.location.authority.store.snapshot().cells)
    assert first.specification.replayed is False
    assert first.grand_map.replayed is False
    assert len(first.grand_map.domain_roots) == domain_count
    assert len(first.grand_map.requirement_roots) == requirement_count
    assert len(first.grand_map.relation_roots) == relation_count
    assert cell_count > requirement_count
    first.location.authority.store.close()

    second = provision_clean_runtime(root, provider, caller_keys, **request)
    try:
        assert second.location.authority.manifest.graph_id == graph_id
        assert second.location.authority.store.revision == revision
        assert len(second.location.authority.store.snapshot().cells) == cell_count
        assert second.specification.replayed is True
        assert second.grand_map.replayed is True
        assert second.grand_map.source_digest == request["grand_map_sha256"]
        assert second.specification.source_digest == request[
            "specification_sha256"
        ]
    finally:
        second.location.authority.store.close()


def test_clean_runtime_rejects_source_drift_before_pointer_creation(tmp_path):
    root = tmp_path / "runtime"
    provider = MemorySigningKeyProvider(
        "archhub.unified.bootstrap",
        b"clean-bootstrap-authority-key" + b"0" * 5,
    )
    caller_keys = WindowsDpapiCallerKeyStore(tmp_path / "caller.dpapi.json")
    specification = (Path(__file__).parents[1] / "SPEC.md").read_bytes()
    grand_map = _map_source()
    with pytest.raises(InvalidCell, match="specification source digest"):
        provision_clean_runtime(
            root,
            provider,
            caller_keys,
            caller_key_id="founder.bootstrap",
            specification_source=specification,
            specification_sha256="0" * 64,
            grand_map_source=grand_map,
            grand_map_sha256=hashlib.sha256(grand_map).hexdigest(),
        )
    assert not (root / "CURRENT").exists()
