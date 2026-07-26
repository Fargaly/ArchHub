"""Protocol court: relations and inspector projection contain no new cell type."""
from nodelang.cell_protocols import (
    CellBatch,
    append_relation_member,
    build_relation,
    inspect_properties,
    inspect_wired_properties,
    insert_relation_member,
    open_composition,
    prepare_append_relation_members,
    prepare_remove_relation_members,
    read_relation,
    relation_projection_scope,
    remove_relation_member,
    reorder_relation_members,
    rewire_incidence,
    set_property_atom,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, Snapshot
from nodelang.universal_cell import InvalidCell, MatchBudgetExceeded

import pytest


def _atom(cell_id, value):
    return Cell(cell_id, NULL_CELL_ID, NULL_CELL_ID, value)


def _base_store():
    store = CellStore()
    store.commit(store.revision, create=[
        _atom("wall", b"Wall panel"),
        _atom("material", b"Terracotta"),
        _atom("stone", b"Limestone"),
        _atom("label", b"Facade material"),
        _atom("owner-role", b"owner"),
        _atom("value-role", b"value"),
        _atom("label-role", b"label"),
        _atom("constraint-role", b"constraint"),
        _atom("constraint", b"A1 fire rating"),
        _atom("subject-role", b"subject"),
        _atom("policy-role", b"policy"),
        _atom("policy", b"founder approval"),
    ])
    return store


def test_plural_append_can_join_a_larger_atomic_commit():
    store = _base_store()
    relation = build_relation(store, [], relation_id="ordered")
    before = store.snapshot()
    patch = prepare_append_relation_members(
        before,
        relation.root_id,
        (("value-role", "material"), ("value-role", "stone")),
    )
    store.commit(
        before.revision,
        create=patch.create,
        replace=patch.replace,
    )
    members = read_relation(store.snapshot(), relation.root_id)
    assert [member.participant_id for member in members] == [
        "material", "stone"
    ]
    assert tuple(member.incidence_id for member in members) == patch.incidence_ids
    assert store.revision == before.revision + 1

    after = store.snapshot()
    patch = prepare_append_relation_members(
        after,
        relation.root_id,
        (("value-role", "wall"), ("value-role", "material")),
    )
    store.commit(after.revision, create=patch.create, replace=patch.replace)
    assert [
        member.participant_id
        for member in read_relation(store.snapshot(), relation.root_id)
    ] == ["material", "stone", "wall", "material"]


def test_arbitrary_arity_relation_is_only_cells_and_every_incidence_has_identity():
    store = _base_store()
    built = build_relation(store, [
        ("owner-role", "wall"),
        ("value-role", "material"),
        ("label-role", "label"),
        ("constraint-role", "constraint"),
    ], relation_id="property")
    members = read_relation(store.snapshot(), built.root_id, budget=32)
    assert len(members) == 4
    assert [member.role_id for member in members] == [
        "owner-role", "value-role", "label-role", "constraint-role"
    ]
    assert len(set(member.incidence_id for member in members)) == 4
    assert all(type(cell) is Cell for cell in store.snapshot().cells.values())


def test_relation_projection_cache_is_request_scoped_revision_safe_and_budgeted():
    store = _base_store()
    built = build_relation(store, [
        ("owner-role", "wall"),
        ("value-role", "material"),
    ], relation_id="cached-property")
    before = store.snapshot()

    with relation_projection_scope():
        first = read_relation(before, built.root_id, budget=16)
        assert read_relation(before, built.root_id, budget=16) is first
        with pytest.raises(MatchBudgetExceeded):
            read_relation(before, built.root_id, budget=1)

        value = next(member for member in first if member.role_id == "value-role")
        rewire_incidence(store, value.incidence_id, "stone")
        after = store.snapshot()
        assert next(
            member.participant_id for member in read_relation(
                after, built.root_id, budget=16
            ) if member.role_id == "value-role"
        ) == "stone"
        assert next(
            member.participant_id for member in read_relation(
                before, built.root_id, budget=16
            ) if member.role_id == "value-role"
        ) == "material"

    outside = read_relation(before, built.root_id, budget=16)
    assert outside == first
    assert outside is not first


def test_relation_can_be_participant_of_another_relation_and_be_rewired():
    store = _base_store()
    property_relation = build_relation(store, [
        ("owner-role", "wall"),
        ("value-role", "material"),
    ], relation_id="property")
    policy_relation = build_relation(store, [
        ("subject-role", property_relation.root_id),
        ("policy-role", "policy"),
    ], relation_id="policy-relation")
    members = read_relation(store.snapshot(), policy_relation.root_id, budget=16)
    subject = next(member for member in members if member.role_id == "subject-role")
    assert subject.participant_id == "property"

    rewire_incidence(store, subject.incidence_id, "wall")
    members = read_relation(store.snapshot(), policy_relation.root_id, budget=16)
    rewired = next(member for member in members if member.role_id == "subject-role")
    assert rewired.incidence_id == subject.incidence_id
    assert rewired.participant_id == "wall"


def test_properties_lens_discovers_rows_from_explicit_wires_after_selection():
    store = _base_store()
    relation = build_relation(store, [
        ("owner-role", "wall"),
        ("value-role", "material"),
        ("label-role", "label"),
        ("constraint-role", "constraint"),
    ], relation_id="property")
    rows = inspect_properties(
        store.snapshot(),
        selected_root="wall",
        relation_roots=[relation.root_id],
        owner_role="owner-role",
        value_role="value-role",
        label_role="label-role",
        budget=32,
    )
    assert len(rows) == 1
    assert rows[0].relation_root == "property"
    assert rows[0].label_root == "label"
    assert rows[0].value_root == "material"


def test_properties_edit_changes_the_value_cell_not_an_inline_form_field():
    store = _base_store()
    relation = build_relation(store, [
        ("owner-role", "wall"),
        ("value-role", "material"),
        ("label-role", "label"),
    ], relation_id="property")
    before_revision = store.revision
    changed_root = set_property_atom(
        store,
        relation.root_id,
        value_role="value-role",
        atom=b"Limestone",
        budget=16,
    )
    assert changed_root == "material"
    assert store.read("material").atom == b"Limestone"
    assert store.at(before_revision).cells["material"].atom == b"Terracotta"


def test_same_root_can_participate_in_multiple_roles_without_class_change():
    store = _base_store()
    relation = build_relation(store, [
        ("owner-role", "wall"),
        ("value-role", "wall"),
        ("label-role", "wall"),
    ], relation_id="multi-role")
    members = read_relation(store.snapshot(), relation.root_id, budget=16)
    assert {member.participant_id for member in members} == {"wall"}
    assert {member.role_id for member in members} == {
        "owner-role", "value-role", "label-role"
    }
    assert store.read("wall") == _atom("wall", b"Wall panel")


def test_properties_panel_reads_selection_and_scope_only_through_wired_cells():
    store = _base_store()
    store.commit(store.revision, create=[
        _atom("selection-role", b"selection"),
        _atom("scope-role", b"scope"),
    ])
    property_relation = build_relation(store, [
        ("owner-role", "wall"),
        ("value-role", "material"),
        ("label-role", "label"),
    ], relation_id="property")
    lens = build_relation(store, [
        ("selection-role", "wall"),
        ("scope-role", property_relation.root_id),
    ], relation_id="properties-lens")

    rows = inspect_wired_properties(
        store.snapshot(),
        lens_root=lens.root_id,
        selection_role="selection-role",
        scope_role="scope-role",
        owner_role="owner-role",
        value_role="value-role",
        label_role="label-role",
        budget=64,
    )
    assert [row.relation_root for row in rows] == ["property"]

    selection = next(
        member for member in read_relation(store.snapshot(), lens.root_id)
        if member.role_id == "selection-role"
    )
    rewire_incidence(store, selection.incidence_id, "material")
    assert inspect_wired_properties(
        store.snapshot(),
        lens_root=lens.root_id,
        selection_role="selection-role",
        scope_role="scope-role",
        owner_role="owner-role",
        value_role="value-role",
        label_role="label-role",
        budget=64,
    ) == ()


def test_wiring_another_relation_into_lens_adds_another_property_row():
    store = _base_store()
    store.commit(store.revision, create=[
        _atom("selection-role", b"selection"),
        _atom("scope-role", b"scope"),
        _atom("finish", b"Matte"),
        _atom("finish-label", b"Finish"),
    ])
    material = build_relation(store, [
        ("owner-role", "wall"),
        ("value-role", "material"),
        ("label-role", "label"),
    ], relation_id="material-property")
    finish = build_relation(store, [
        ("owner-role", "wall"),
        ("value-role", "finish"),
        ("label-role", "finish-label"),
    ], relation_id="finish-property")
    lens = build_relation(store, [
        ("selection-role", "wall"),
        ("scope-role", material.root_id),
    ], relation_id="properties-lens")
    append_relation_member(store, lens.root_id, "scope-role", finish.root_id)

    rows = inspect_wired_properties(
        store.snapshot(),
        lens_root=lens.root_id,
        selection_role="selection-role",
        scope_role="scope-role",
        owner_role="owner-role",
        value_role="value-role",
        label_role="label-role",
        budget=64,
    )
    assert {row.relation_root for row in rows} == {
        "material-property", "finish-property"
    }


def test_application_supernode_is_opened_by_reachability_not_group_membership():
    store = CellStore()
    store.commit(store.revision, create=[
        _atom("component-role", b"component"),
        _atom("brain", b"Brain"),
        _atom("grand-map", b"Grand Map"),
        _atom("workspace", b"Workspace"),
        _atom("website", b"Website"),
        _atom("session", b"AI session"),
    ])
    app = build_relation(store, [
        ("component-role", "brain"),
        ("component-role", "grand-map"),
        ("component-role", "workspace"),
        ("component-role", "website"),
        ("component-role", "session"),
    ], relation_id="archhub")
    before = store.snapshot()
    opened = open_composition(before, app.root_id, budget=64)
    assert {"brain", "grand-map", "workspace", "website", "session"} <= opened
    assert store.snapshot() == before
    assert "children" not in Cell.__dataclass_fields__
    assert "parent" not in Cell.__dataclass_fields__


def test_batch_composer_publishes_many_compositions_in_one_atomic_revision():
    store = CellStore()
    batch = CellBatch(store)
    batch.add(_atom("role", b"participant"))
    for index in range(100):
        batch.add(_atom("value-%s" % index, str(index).encode("ascii")))
    for index in range(100):
        batch.relation(
            [("role", "value-%s" % index)],
            relation_id="relation-%s" % index,
        )
    revision = batch.commit()
    assert revision == 1
    assert store.revision == 1
    assert len(store.snapshot().cells) == 1 + 1 + 100 + 200


def test_batch_construction_does_not_scan_the_committed_graph():
    class MembershipOnlyCells:
        def __contains__(self, key):
            return key == NULL_CELL_ID

        def __getitem__(self, key):
            if key == NULL_CELL_ID:
                return Cell(NULL_CELL_ID, NULL_CELL_ID, NULL_CELL_ID, b"")
            raise KeyError(key)

        def __iter__(self):
            raise AssertionError("CellBatch construction scanned the graph")

        def __len__(self):
            return 1

    class MembershipOnlyStore:
        def snapshot(self):
            return Snapshot(0, MembershipOnlyCells())

    batch = CellBatch(MembershipOnlyStore())
    batch.add(_atom("new-value", b"value"))
    with pytest.raises(InvalidCell, match="already exists"):
        batch.add(_atom(NULL_CELL_ID, b"duplicate"))


def test_ordered_relation_insert_remove_and_reorder_preserve_incidence_identity():
    store = _base_store()
    store.commit(store.revision, create=[
        _atom("item-role", b"item"),
        _atom("a", b"A"),
        _atom("b", b"B"),
        _atom("c", b"C"),
        _atom("d", b"D"),
    ])
    built = build_relation(store, [
        ("item-role", "a"),
        ("item-role", "c"),
    ], relation_id="ordered")
    original = read_relation(store.snapshot(), built.root_id)
    a_incidence, c_incidence = (
        original[0].incidence_id, original[1].incidence_id
    )

    b_incidence = insert_relation_member(
        store,
        built.root_id,
        "item-role",
        "b",
        before_incidence=c_incidence,
    )
    d_incidence = insert_relation_member(
        store,
        built.root_id,
        "item-role",
        "d",
        after_incidence=c_incidence,
    )
    assert [member.participant_id for member in read_relation(
        store.snapshot(), built.root_id
    )] == ["a", "b", "c", "d"]

    reorder_relation_members(
        store,
        built.root_id,
        (d_incidence, b_incidence, a_incidence, c_incidence),
    )
    reordered = read_relation(store.snapshot(), built.root_id)
    assert [member.participant_id for member in reordered] == ["d", "b", "a", "c"]
    assert [member.incidence_id for member in reordered] == [
        d_incidence, b_incidence, a_incidence, c_incidence,
    ]

    before_remove = store.revision
    removed = remove_relation_member(store, built.root_id, b_incidence)
    assert removed.participant_id == "b"
    assert [member.participant_id for member in read_relation(
        store.snapshot(), built.root_id
    )] == ["d", "a", "c"]
    assert [member.participant_id for member in read_relation(
        store.at(before_remove), built.root_id
    )] == ["d", "b", "a", "c"]


def test_ordered_relation_mutations_reject_unknown_or_partial_membership():
    store = _base_store()
    built = build_relation(store, [
        ("owner-role", "wall"),
        ("value-role", "material"),
    ], relation_id="ordered")
    members = read_relation(store.snapshot(), built.root_id)
    with pytest.raises(InvalidCell, match="anchor"):
        insert_relation_member(
            store, built.root_id, "owner-role", "wall",
            before_incidence="missing",
        )
    with pytest.raises(InvalidCell, match="not a member"):
        remove_relation_member(store, built.root_id, "missing")
    with pytest.raises(InvalidCell, match="exact member permutation"):
        reorder_relation_members(
            store, built.root_id, (members[0].incidence_id,)
        )


def test_relation_detach_rewrites_only_the_changed_chain_links():
    store = _base_store()
    participants = []
    create = []
    for index in range(2_000):
        participant = "large-item-%s" % index
        participants.append(participant)
        create.append(_atom(participant, participant.encode("ascii")))
    store.commit(store.revision, create=create)
    built = build_relation(
        store,
        (("value-role", participant) for participant in participants),
        relation_id="large-ordered-relation",
    )
    before = store.snapshot()
    members = read_relation(before, built.root_id, budget=3_000)

    patch = prepare_remove_relation_members(
        before,
        built.root_id,
        (members[700].incidence_id, members[1_300].incidence_id),
        budget=3_000,
    )

    assert len(patch.removed) == 2
    assert len(patch.replace) == 2
    store.commit(before.revision, replace=patch.replace)
    after = read_relation(store.snapshot(), built.root_id, budget=3_000)
    assert len(after) == 1_998
    assert all(
        member.incidence_id not in {
            members[700].incidence_id,
            members[1_300].incidence_id,
        }
        for member in after
    )
    assert read_relation(store.at(before.revision), built.root_id, budget=3_000) == members
