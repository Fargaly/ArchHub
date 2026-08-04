import hashlib
import json
from pathlib import Path
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.requirement_graph_import import (
    import_requirement_graph,
    import_specification_graph,
)
from nodelang.unified_authority import (
    composition_root,
    create_unified_authority,
    read_contained_scope,
    read_instance,
    read_relation_node,
)
from nodelang.universal_cell import CellStore, InvalidCell


COMMAND_NAMESPACE = uuid.UUID("653958f3-e13e-4c41-8b0f-7e06b6e4a89b")
CALLER_PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
CALLER_PUBLIC = CALLER_PRIVATE.public_key().public_bytes(
    serialization.Encoding.Raw,
    serialization.PublicFormat.Raw,
)


def _command_id(label: str) -> str:
    return str(uuid.uuid5(COMMAND_NAMESPACE, label))


def _authority():
    provider = MemorySigningKeyProvider(
        "accepted-source-test", b"accepted-source-key" + b"0" * 13
    )
    authority = create_unified_authority(
        CellStore(),
        provider,
        key_id="accepted-source-test",
        application_label="ArchHub",
        principal_label="Founder",
        bootstrap_session_label="Accepted source import",
        bootstrap_session_public_key=CALLER_PUBLIC,
        composition_labels=("Grand Map", "Governance"),
    )
    return authority


class _Caller:
    def __init__(self, authority):
        self.actor_root = authority.manifest.principal_root
        self.session_root = authority.manifest.bootstrap_session_root
        self.public_key = CALLER_PUBLIC

    def sign(self, payload: bytes) -> bytes:
        return CALLER_PRIVATE.sign(payload)


def _source() -> bytes:
    payload = [
        {
            "key": "brain",
            "title": "Brain and Memory",
            "nodes": [
                {
                    "id": "brain_attention",
                    "cat": "behavior",
                    "title": "Persistent Attention",
                    "sub": "Keep accepted work visible across sessions",
                    "status": "partial",
                    "params": [{"k": "budget", "v": "bounded"}],
                    "evidence_ref": "source:attention",
                    "last_verified": "2026-08-03",
                    "authority_source": "founder",
                    "bim_phase": "All",
                    "standard": "ISO 19650",
                },
                {
                    "id": "brain_history",
                    "cat": "data",
                    "title": "History",
                    "sub": "Preserve accepted revisions",
                    "status": "partial",
                    "params": [],
                    "evidence_ref": "source:history",
                    "last_verified": "2026-08-03",
                    "authority_source": "founder",
                    "bim_phase": "All",
                    "standard": "ISO 19650",
                },
            ],
            "wires": [["brain_attention", "brain_history"]],
            "cross": [
                {
                    "from": "brain_attention",
                    "to_domain": "ui",
                    "why": "Attention is visible through the interface",
                }
            ],
        },
        {
            "key": "ui",
            "title": "UI and Design System",
            "nodes": [
                {
                    "id": "ui_properties",
                    "cat": "interface",
                    "title": "Properties Rail",
                    "sub": "Edit graph-held parameters",
                    "status": "partial",
                    "params": [{"k": "tabs", "v": ["Use", "Build", "Govern"]}],
                    "evidence_ref": "source:properties",
                    "last_verified": "2026-08-03",
                    "authority_source": "founder",
                    "bim_phase": "All",
                    "standard": "ISO 9241",
                }
            ],
            "wires": [],
            "cross": [],
        },
    ]
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def test_accepted_requirement_source_imports_atomically_into_one_graph_and_replays():
    authority = _authority()
    caller = _Caller(authority)
    grand_map_root = composition_root(authority, "Grand Map", caller=caller)
    source = _source()
    digest = hashlib.sha256(source).hexdigest()
    request = {
        "source_bytes": source,
        "expected_sha256": digest,
        "caller": caller,
        "command_id": _command_id("import-accepted-requirements-v1"),
    }
    first = import_requirement_graph(authority, **request)

    assert first.replayed is False
    assert set(first.domain_roots) == {"brain", "ui"}
    assert set(first.requirement_roots) == {
        "brain_attention", "brain_history", "ui_properties"
    }
    assert len(first.relation_roots) == 2
    assert read_instance(
        authority,
        first.requirement_roots["brain_attention"],
        scope_root=grand_map_root,
        caller=caller,
    )["values"]["parameters"] == {"budget": {"value": "bounded"}}
    for relation_root in first.relation_roots:
        relation = read_relation_node(
            authority,
            relation_root,
            scope_root=grand_map_root,
            caller=caller,
        )
        assert {role for role, _ in relation.participants} == {"source", "target"}
    assert first.root_id in {
        member.participant_id
        for member in __import__(
            "nodelang.unified_authority", fromlist=["relation_members"]
        ).relation_members(
            authority.store.snapshot(), grand_map_root
        )
    }

    revision = authority.store.revision
    count = len(authority.store.snapshot().cells)
    second = import_requirement_graph(authority, **request)
    assert second.replayed is True
    assert second.root_id == first.root_id
    assert second.revision == first.revision
    assert authority.store.revision == revision
    assert len(authority.store.snapshot().cells) == count


def test_requirement_source_digest_and_endpoints_fail_closed():
    authority = _authority()
    source = _source()
    with pytest.raises(InvalidCell, match="digest"):
        import_requirement_graph(
            authority,
            source,
            expected_sha256="0" * 64,
            caller=_Caller(authority),
            command_id=_command_id("bad-digest"),
        )

    payload = json.loads(source)
    payload[0]["wires"].append(["brain_attention", "missing"])
    changed = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(InvalidCell, match="internal relation"):
        import_requirement_graph(
            authority,
            changed,
            expected_sha256=hashlib.sha256(changed).hexdigest(),
            caller=_Caller(authority),
            command_id=_command_id("bad-endpoint"),
        )


def test_normative_specification_imports_as_one_revision_bound_governance_graph():
    authority = _authority()
    caller = _Caller(authority)
    source = (Path(__file__).parents[1] / "SPEC.md").read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    request = {
        "source_bytes": source,
        "expected_sha256": digest,
        "caller": caller,
        "command_id": _command_id("import-normative-specification-v1"),
    }
    first = import_specification_graph(authority, **request)

    assert first.replayed is False
    assert first.source_digest == digest
    assert {
        "0", "1", "3", "3.1", "3.2", "4.1", "4.5", "7", "9", "11", "12", "13"
    }.issubset(first.section_roots)
    assert len(first.section_roots) == 22
    assert len(first.requirement_roots) == 163
    assert len(first.relation_roots) == 151
    governance_root = composition_root(authority, "Governance", caller=caller)
    assert first.root_id in {
        member.participant_id
        for member in __import__(
            "nodelang.unified_authority", fromlist=["relation_members"]
        ).relation_members(authority.store.snapshot(), governance_root)
    }
    contained = read_contained_scope(
        authority,
        first.root_id,
        scope_root=governance_root,
        caller=caller,
        at_revision=first.revision,
    )
    relation_pairs = {
        (
            dict(projection.participants)["source"],
            dict(projection.participants)["target"],
        )
        for projection in contained.relations.values()
    }
    assert {
        (first.section_roots["3"], first.section_roots["3.1"]),
        (first.section_roots["3"], first.section_roots["3.2"]),
        (first.section_roots["3"], first.section_roots["3.3"]),
        (first.section_roots["4"], first.section_roots["4.1"]),
        (first.section_roots["4"], first.section_roots["4.2"]),
        (first.section_roots["4"], first.section_roots["4.3"]),
        (first.section_roots["4"], first.section_roots["4.4"]),
        (first.section_roots["4"], first.section_roots["4.5"]),
    }.issubset(relation_pairs)
    critical = {
        key: contained.instances[first.requirement_roots[key]]["values"]["statement"]
        for key in ("spec:1:003", "spec:4.1:001", "spec:7:002", "spec:11:002")
    }
    assert "Every persisted semantic fact MUST" in critical["spec:1:003"]
    assert "Meaning MUST resolve" in critical["spec:4.1:001"]
    assert "first screen is the usable graph workspace" in critical["spec:7:002"]
    assert "Uniform Cell" in critical["spec:11:002"]

    revision = authority.store.revision
    cell_count = len(authority.store.snapshot().cells)
    second = import_specification_graph(authority, **request)
    assert second.replayed is True
    assert second.root_id == first.root_id
    assert second.revision == first.revision
    assert authority.store.revision == revision
    assert len(authority.store.snapshot().cells) == cell_count


def test_specification_digest_and_executable_html_fail_closed_without_writes():
    authority = _authority()
    caller = _Caller(authority)
    source = (Path(__file__).parents[1] / "SPEC.md").read_bytes()
    revision = authority.store.revision
    count = len(authority.store.snapshot().cells)

    with pytest.raises(InvalidCell, match="digest"):
        import_specification_graph(
            authority,
            source,
            expected_sha256="0" * 64,
            caller=caller,
            command_id=_command_id("bad-spec-digest"),
        )
    unsafe = b"# Specification\n\n## 1. Rule\n\n<script>alert(1)</script>\n"
    with pytest.raises(InvalidCell, match="executable HTML"):
        import_specification_graph(
            authority,
            unsafe,
            expected_sha256=hashlib.sha256(unsafe).hexdigest(),
            caller=caller,
            command_id=_command_id("unsafe-spec-html"),
        )

    assert authority.store.revision == revision
    assert len(authority.store.snapshot().cells) == count
