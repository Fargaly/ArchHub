"""Forcing court for universal immutable revision and CDE promotion."""
import hashlib
import inspect
from types import MappingProxyType

import pytest

from nodelang.cell_attestations import (
    CourtAttestationBroker,
    CourtEvidenceDenied,
    CourtInvocation,
    CourtResult,
    bootstrap_attestation_protocol,
    build_court_definition,
)
from nodelang.cell_catalog import (
    bootstrap_assembly_protocol,
    compose_catalog_instance,
    instantiate_catalog_definition,
)
from nodelang.cell_lifecycle import (
    append_wip_graph_revision,
    append_wip_revision,
    graph_content_bytes,
    graph_content_digest,
    lifecycle_history,
    merge_wip_revisions,
    promote_revision,
    read_lifecycle_instance,
    read_revision,
    restore_revision_as_wip,
    seed_composed_lifecycle_content,
    state_heads,
)
from nodelang.cell_protocols import build_relation, read_relation, rewire_incidence
from nodelang.cell_standard_library import build_standard_library_v0
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


@pytest.fixture()
def versioned():
    store = CellStore()
    assembly = bootstrap_assembly_protocol(store)
    library = build_standard_library_v0(store, assembly)
    definition = library.definition_roots[2]
    instance = instantiate_catalog_definition(
        store, assembly, library.catalog_root, definition
    )
    store.commit(store.revision, create=(
        Cell("actor:author", NULL_CELL_ID, NULL_CELL_ID, b"Author"),
        Cell("actor:approver", NULL_CELL_ID, NULL_CELL_ID, b"Approver"),
        Cell("evidence:qa", NULL_CELL_ID, NULL_CELL_ID, b"QA passed"),
        Cell("evidence:authorization", NULL_CELL_ID, NULL_CELL_ID, b"Authorized"),
        Cell("branch:author-a", NULL_CELL_ID, NULL_CELL_ID, b"Author A"),
        Cell("branch:author-b", NULL_CELL_ID, NULL_CELL_ID, b"Author B"),
        Cell("branch:resolved", NULL_CELL_ID, NULL_CELL_ID, b"Resolved"),
    ))
    return store, assembly, library, instance


@pytest.fixture()
def promotion_authority(versioned):
    store, _, library, _ = versioned
    protocol = bootstrap_attestation_protocol(
        store, prefix="test:lifecycle-attestation"
    )
    checks = ("content-digest", "target-state")
    court = build_court_definition(
        store,
        protocol,
        court_id="test:court:lifecycle-promotion",
        name="Lifecycle promotion",
        builder_id="test:lifecycle-promotion-runner",
        runner_version="1",
        policy_digest=hashlib.sha256(
            b"test lifecycle promotion policy"
        ).hexdigest(),
        checks=checks,
    )

    def runner(invocation: CourtInvocation) -> CourtResult:
        results = {
            "content-digest": hashlib.sha256(
                invocation.subject_content
            ).hexdigest() == invocation.subject_digest,
            "target-state": invocation.external_parameters.get(
                "targetState"
            ) in library.lifecycle_protocol.states.values(),
        }
        return CourtResult(
            all(results.values()),
            MappingProxyType(results),
            MappingProxyType({"court": "test"}),
        )

    broker = CourtAttestationBroker()
    broker.admit_court(store.snapshot(), protocol, court.root_id, runner)
    return protocol, court.root_id, broker


def _promotion_evidence(
    versioned, promotion_authority, source_revision_root, target_state_root
):
    store, _, library, instance = versioned
    protocol, court_root, broker = promotion_authority
    lifecycle = library.lifecycle_protocol
    source = read_revision(store.snapshot(), lifecycle, source_revision_root)
    subject_content = graph_content_bytes(
        store.snapshot(), source.content_root
    )
    parameters = {
        "asset": instance.root_id,
        "targetState": target_state_root,
    }
    evidence = broker.run(
        store,
        protocol,
        court_root,
        subject_name=source_revision_root,
        subject_content=subject_content,
        external_parameters=parameters,
    )
    receipt = broker.consume(
        store.snapshot(),
        protocol,
        evidence,
        purpose="promote:%s:%s" % (instance.root_id, target_state_root),
        expected_court_root=court_root,
        expected_subject_name=source_revision_root,
        expected_subject_digest=store.read(source.content_digest_root).atom.decode(
            "ascii"
        ),
        expected_parameters=parameters,
    )
    return evidence, receipt, broker


def _merge_evidence(versioned, promotion_authority, parents, content):
    store, _, library, instance = versioned
    protocol, court_root, broker = promotion_authority
    ordered = tuple(parents)
    payload = bytes(content)
    parents_digest = hashlib.sha256(
        "\0".join(ordered).encode("utf-8")
    ).hexdigest()
    parameters = {
        "asset": instance.root_id,
        "targetState": library.lifecycle_protocol.states["wip"],
        "parentsDigest": parents_digest,
    }
    evidence = broker.run(
        store,
        protocol,
        court_root,
        subject_name=instance.root_id,
        subject_content=payload,
        external_parameters=parameters,
    )
    receipt = broker.consume(
        store.snapshot(),
        protocol,
        evidence,
        purpose="merge:%s:%s" % (instance.root_id, parents_digest),
        expected_court_root=court_root,
        expected_subject_name=instance.root_id,
        expected_subject_digest=hashlib.sha256(payload).hexdigest(),
        expected_parameters=parameters,
    )
    return evidence, receipt, broker


def test_atomic_seed_records_the_real_initial_actor(versioned):
    store, assembly, library, _ = versioned
    snapshot = store.snapshot()
    composed = compose_catalog_instance(
        snapshot,
        assembly,
        library.catalog_root,
        library.definition_roots[2],
        token="real-initial-actor",
    )
    seeded = seed_composed_lifecycle_content(
        snapshot,
        assembly,
        library.lifecycle_protocol,
        composed,
        b"personal presentation value",
        actor_root="actor:author",
    )
    store.commit(snapshot.revision, create=seeded.cells)
    instance = read_lifecycle_instance(
        store.snapshot(),
        assembly,
        library.lifecycle_protocol,
        seeded.instance.root_id,
    )
    heads = state_heads(
        store.snapshot(),
        library.lifecycle_protocol,
        instance.state_pointers[library.lifecycle_protocol.states["wip"]],
    )
    assert len(heads) == 1
    revision = read_revision(
        store.snapshot(), library.lifecycle_protocol, heads[0]
    )
    assert revision.actor_root == "actor:author"
    assert store.read(revision.content_root).atom == b"personal presentation value"


def _pointed_revision(store, lifecycle, pointer_root):
    members = read_relation(store.snapshot(), pointer_root, budget=8)
    values = [
        member.participant_id for member in members
        if member.role_id == lifecycle.role("revision")
    ]
    return values[0] if values else None


def test_wip_edits_append_revisions_without_overwriting_history(versioned):
    store, assembly, library, instance = versioned
    lifecycle = library.lifecycle_protocol
    active = read_lifecycle_instance(
        store.snapshot(), assembly, lifecycle, instance.root_id
    )
    initial = lifecycle_history(store.snapshot(), lifecycle, active)[0]
    initial_content = read_revision(
        store.snapshot(), lifecycle, initial
    ).content_root
    assert store.read(initial_content).atom == b""

    first = append_wip_revision(
        store, assembly, lifecycle, instance.root_id,
        content=b"revision one", actor_root="actor:author",
    )
    second = append_wip_revision(
        store, assembly, lifecycle, instance.root_id,
        content=b"revision two", actor_root="actor:author",
    )
    active = read_lifecycle_instance(
        store.snapshot(), assembly, lifecycle, instance.root_id
    )
    history = lifecycle_history(store.snapshot(), lifecycle, active)
    assert history == (initial, first, second)
    assert read_revision(store.snapshot(), lifecycle, second).predecessor_root == first
    assert store.read(read_revision(store.snapshot(), lifecycle, first).content_root).atom == b"revision one"
    assert store.read(initial_content).atom == b""
    content_interface = read_relation(
        store.snapshot(), active.content_interface_root, budget=32
    )
    exposed = next(
        member.participant_id for member in content_interface
        if member.role_id == assembly.role("interface-target")
    )
    assert exposed == read_revision(
        store.snapshot(), lifecycle, second
    ).content_root
    assert store.read(exposed).atom == b"revision two"


def test_shared_and_published_are_immutable_promotions_not_synced_copies(
    versioned, promotion_authority
):
    store, assembly, library, instance = versioned
    lifecycle = library.lifecycle_protocol
    wip = append_wip_revision(
        store, assembly, lifecycle, instance.root_id,
        content=b"coordinated model", actor_root="actor:author",
    )
    evidence, receipt, broker = _promotion_evidence(
        versioned, promotion_authority, wip, lifecycle.states["shared"]
    )
    shared = promote_revision(
        store, assembly, lifecycle, instance.root_id,
        target_state_root=lifecycle.states["shared"],
        actor_root="actor:approver", evidence_roots=(evidence,),
        evidence_receipts=(receipt,), attestation_broker=broker,
    )
    shared_content = read_revision(
        store.snapshot(), lifecycle, shared
    ).content_root
    assert shared_content == read_revision(
        store.snapshot(), lifecycle, wip
    ).content_root

    later_wip = append_wip_revision(
        store, assembly, lifecycle, instance.root_id,
        content=b"unshared later work", actor_root="actor:author",
    )
    active = read_lifecycle_instance(
        store.snapshot(), assembly, lifecycle, instance.root_id
    )
    assert _pointed_revision(
        store, lifecycle, active.state_pointers[lifecycle.states["shared"]]
    ) == shared
    assert _pointed_revision(
        store, lifecycle, active.state_pointers[lifecycle.states["wip"]]
    ) == later_wip

    evidence, receipt, broker = _promotion_evidence(
        versioned, promotion_authority, shared, lifecycle.states["published"]
    )
    published = promote_revision(
        store, assembly, lifecycle, instance.root_id,
        target_state_root=lifecycle.states["published"],
        actor_root="actor:approver",
        evidence_roots=(evidence,), evidence_receipts=(receipt,),
        attestation_broker=broker,
    )
    published_revision = read_revision(
        store.snapshot(), lifecycle, published
    )
    assert published_revision.predecessor_root == shared
    assert published_revision.content_root == shared_content
    assert store.read(published_revision.content_root).atom == b"coordinated model"


def test_restore_appends_a_new_wip_revision_instead_of_rewriting(versioned):
    store, assembly, library, instance = versioned
    lifecycle = library.lifecycle_protocol
    first = append_wip_revision(
        store, assembly, lifecycle, instance.root_id,
        content=b"first", actor_root="actor:author",
    )
    append_wip_revision(
        store, assembly, lifecycle, instance.root_id,
        content=b"second", actor_root="actor:author",
    )
    before = read_revision(store.snapshot(), lifecycle, first)
    restored = restore_revision_as_wip(
        store, assembly, lifecycle, instance.root_id, first,
        actor_root="actor:author",
    )
    after = read_revision(store.snapshot(), lifecycle, restored)
    assert after.root_id != first
    assert after.content_root == before.content_root
    assert store.read(after.reason_root).atom.startswith(b"restore:")
    assert first in lifecycle_history(
        store.snapshot(), lifecycle,
        read_lifecycle_instance(store.snapshot(), assembly, lifecycle, instance.root_id),
    )


def test_transition_requires_graph_rule_source_and_evidence(versioned):
    store, assembly, library, instance = versioned
    lifecycle = library.lifecycle_protocol
    with pytest.raises(InvalidCell, match="consumed court receipt"):
        promote_revision(
            store, assembly, lifecycle, instance.root_id,
            target_state_root=lifecycle.states["shared"],
            actor_root="actor:approver", evidence_roots=(),
            evidence_receipts=(), attestation_broker=None,  # type: ignore[arg-type]
        )


def test_named_evidence_cell_without_consumed_signed_receipt_cannot_promote(
    versioned, promotion_authority
):
    store, assembly, library, instance = versioned
    lifecycle = library.lifecycle_protocol
    append_wip_revision(
        store,
        assembly,
        lifecycle,
        instance.root_id,
        content=b"not authorized by a court",
        actor_root="actor:author",
    )
    with pytest.raises(CourtEvidenceDenied, match="unknown"):
        promote_revision(
            store,
            assembly,
            lifecycle,
            instance.root_id,
            target_state_root=lifecycle.states["shared"],
            actor_root="actor:approver",
            evidence_roots=("evidence:qa",),
            evidence_receipts=(object(),),
            attestation_broker=promotion_authority[2],
        )


def test_concurrent_edits_preserve_multiple_heads_and_require_explicit_base(versioned):
    store, assembly, library, instance = versioned
    lifecycle = library.lifecycle_protocol
    active = read_lifecycle_instance(
        store.snapshot(), assembly, lifecycle, instance.root_id
    )
    initial = state_heads(
        store.snapshot(), lifecycle,
        active.state_pointers[lifecycle.states["wip"]],
    )[0]

    authored_a = append_wip_revision(
        store, assembly, lifecycle, instance.root_id,
        content=b"author A variation", actor_root="actor:author",
        base_revision_root=initial, branch_root="branch:author-a",
    )
    authored_b = append_wip_revision(
        store, assembly, lifecycle, instance.root_id,
        content=b"author B variation", actor_root="actor:author",
        base_revision_root=initial, branch_root="branch:author-b",
    )
    active = read_lifecycle_instance(
        store.snapshot(), assembly, lifecycle, instance.root_id
    )
    heads = state_heads(
        store.snapshot(), lifecycle,
        active.state_pointers[lifecycle.states["wip"]],
    )
    assert heads == (authored_a, authored_b)
    assert read_revision(
        store.snapshot(), lifecycle, authored_a
    ).predecessor_roots == (initial,)
    assert read_revision(
        store.snapshot(), lifecycle, authored_b
    ).predecessor_roots == (initial,)
    assert read_revision(
        store.snapshot(), lifecycle, authored_a
    ).branch_root == "branch:author-a"
    assert read_revision(
        store.snapshot(), lifecycle, authored_b
    ).branch_root == "branch:author-b"

    with pytest.raises(InvalidCell, match="multiple heads"):
        append_wip_revision(
            store, assembly, lifecycle, instance.root_id,
            content=b"ambiguous", actor_root="actor:author",
        )


def test_explicit_merge_has_every_parent_and_replaces_only_merged_heads(
    versioned, promotion_authority
):
    store, assembly, library, instance = versioned
    lifecycle = library.lifecycle_protocol
    active = read_lifecycle_instance(
        store.snapshot(), assembly, lifecycle, instance.root_id
    )
    initial = state_heads(
        store.snapshot(), lifecycle,
        active.state_pointers[lifecycle.states["wip"]],
    )[0]
    authored_a = append_wip_revision(
        store, assembly, lifecycle, instance.root_id,
        content=b"A", actor_root="actor:author",
        base_revision_root=initial, branch_root="branch:author-a",
    )
    authored_b = append_wip_revision(
        store, assembly, lifecycle, instance.root_id,
        content=b"B", actor_root="actor:author",
        base_revision_root=initial, branch_root="branch:author-b",
    )

    evidence, receipt, broker = _merge_evidence(
        versioned, promotion_authority,
        (authored_a, authored_b), b"resolved A+B",
    )
    before_denial = store.revision
    with pytest.raises(CourtEvidenceDenied):
        merge_wip_revisions(
            store, assembly, lifecycle, instance.root_id,
            parent_revision_roots=(authored_a, authored_b),
            content=b"resolved A+B", actor_root="actor:approver",
            branch_root="branch:resolved", evidence_roots=(evidence,),
            evidence_receipts=(object(),), attestation_broker=broker,
        )
    assert store.revision == before_denial

    merged = merge_wip_revisions(
        store, assembly, lifecycle, instance.root_id,
        parent_revision_roots=(authored_a, authored_b),
        content=b"resolved A+B", actor_root="actor:approver",
        branch_root="branch:resolved", evidence_roots=(evidence,),
        evidence_receipts=(receipt,), attestation_broker=broker,
    )
    active = read_lifecycle_instance(
        store.snapshot(), assembly, lifecycle, instance.root_id
    )
    assert state_heads(
        store.snapshot(), lifecycle,
        active.state_pointers[lifecycle.states["wip"]],
    ) == (merged,)
    projection = read_revision(store.snapshot(), lifecycle, merged)
    assert projection.predecessor_roots == (authored_a, authored_b)
    assert projection.evidence_roots == (evidence,)
    assert store.read(
        read_revision(store.snapshot(), lifecycle, authored_a).content_root
    ).atom == b"A"
    assert store.read(
        read_revision(store.snapshot(), lifecycle, authored_b).content_root
    ).atom == b"B"


def test_promotion_names_one_head_and_never_erases_sibling_variations(
    versioned, promotion_authority
):
    store, assembly, library, instance = versioned
    lifecycle = library.lifecycle_protocol
    active = read_lifecycle_instance(
        store.snapshot(), assembly, lifecycle, instance.root_id
    )
    initial = state_heads(
        store.snapshot(), lifecycle,
        active.state_pointers[lifecycle.states["wip"]],
    )[0]
    authored_a = append_wip_revision(
        store, assembly, lifecycle, instance.root_id,
        content=b"A", actor_root="actor:author",
        base_revision_root=initial, branch_root="branch:author-a",
    )
    authored_b = append_wip_revision(
        store, assembly, lifecycle, instance.root_id,
        content=b"B", actor_root="actor:author",
        base_revision_root=initial, branch_root="branch:author-b",
    )
    with pytest.raises(InvalidCell, match="multiple heads"):
        promote_revision(
            store, assembly, lifecycle, instance.root_id,
            target_state_root=lifecycle.states["shared"],
            actor_root="actor:approver", evidence_roots=("evidence:qa",),
            evidence_receipts=(object(),),
            attestation_broker=promotion_authority[2],
        )
    evidence, receipt, broker = _promotion_evidence(
        versioned,
        promotion_authority,
        authored_a,
        lifecycle.states["shared"],
    )
    shared = promote_revision(
        store, assembly, lifecycle, instance.root_id,
        target_state_root=lifecycle.states["shared"],
        source_revision_root=authored_a,
        actor_root="actor:approver", evidence_roots=(evidence,),
        evidence_receipts=(receipt,), attestation_broker=broker,
    )
    active = read_lifecycle_instance(
        store.snapshot(), assembly, lifecycle, instance.root_id
    )
    assert state_heads(
        store.snapshot(), lifecycle,
        active.state_pointers[lifecycle.states["wip"]],
    ) == (authored_a, authored_b)
    assert state_heads(
        store.snapshot(), lifecycle,
        active.state_pointers[lifecycle.states["shared"]],
    ) == (shared,)


def test_revision_content_digest_detects_tampering(
    versioned, promotion_authority
):
    store, assembly, library, instance = versioned
    lifecycle = library.lifecycle_protocol
    revision = append_wip_revision(
        store, assembly, lifecycle, instance.root_id,
        content=b"verified bytes", actor_root="actor:author",
    )
    projection = read_revision(store.snapshot(), lifecycle, revision)
    content = store.read(projection.content_root)
    store.commit(store.revision, replace=(Cell(
        content.id, content.link0, content.link1, b"tampered bytes",
    ),))
    with pytest.raises(InvalidCell, match="digest"):
        read_revision(store.snapshot(), lifecycle, revision)
    with pytest.raises(InvalidCell, match="source state has no revision"):
        promote_revision(
            store, assembly, lifecycle, instance.root_id,
            target_state_root=lifecycle.states["published"],
            actor_root="actor:approver",
            evidence_roots=("evidence:authorization",),
            evidence_receipts=(object(),),
            attestation_broker=promotion_authority[2],
        )


def test_wired_graph_is_versioned_as_content_and_rewiring_breaks_revision(versioned):
    store, assembly, library, instance = versioned
    lifecycle = library.lifecycle_protocol
    store.commit(store.revision, create=(
        Cell("config:role:catalogue", NULL_CELL_ID, NULL_CELL_ID, b"catalogue"),
        Cell("config:role:policy", NULL_CELL_ID, NULL_CELL_ID, b"policy"),
        Cell("config:catalogue:v1", NULL_CELL_ID, NULL_CELL_ID, b"released catalogue"),
        Cell("config:policy:v1", NULL_CELL_ID, NULL_CELL_ID, b"released policy"),
        Cell("config:policy:attacker", NULL_CELL_ID, NULL_CELL_ID, b"attacker policy"),
    ))
    config = build_relation(store, (
        ("config:role:catalogue", "config:catalogue:v1"),
        ("config:role:policy", "config:policy:v1"),
    ), relation_id="config:tenant:revision-content")
    before = graph_content_digest(store.snapshot(), config.root_id)
    revision = append_wip_graph_revision(
        store,
        assembly,
        lifecycle,
        instance.root_id,
        content_root=config.root_id,
        actor_root="actor:author",
        reason="tenant configuration graph",
    )
    projected = read_revision(store.snapshot(), lifecycle, revision)
    assert projected.content_root == config.root_id
    assert store.read(projected.content_digest_root).atom == before

    policy_member = next(
        member for member in read_relation(store.snapshot(), config.root_id)
        if member.role_id == "config:role:policy"
    )
    rewire_incidence(
        store, policy_member.incidence_id, "config:policy:attacker"
    )
    assert graph_content_digest(store.snapshot(), config.root_id) != before
    with pytest.raises(InvalidCell, match="digest"):
        read_revision(store.snapshot(), lifecycle, revision)


def test_runtime_has_no_bim_money_database_or_geometry_dispatch():
    source = "\n".join(inspect.getsource(function) for function in (
        append_wip_revision, append_wip_graph_revision, merge_wip_revisions,
        promote_revision, restore_revision_as_wip,
    )).lower()
    for forbidden in ('"bim"', '"money"', '"database"', '"geometry"'):
        assert forbidden not in source
