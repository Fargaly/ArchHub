from __future__ import annotations

from collections.abc import Iterator, Mapping

import pytest

import nodelang.cell_relation_forms as relation_forms
from nodelang.cell_protocols import CellBatch, read_relation
from nodelang.cell_relation_contract import (
    bootstrap_relation_contract_protocol,
    build_relation_contract,
    build_role_constraint,
    read_relation_contract,
    validate_relation,
)
from nodelang.cell_relation_forms import (
    ROLE_NAMES,
    bootstrap_relation_form_protocol,
    build_relation_form_binding,
    compose_relation_form_submission,
    open_relation_form_protocol,
    read_relation_form_binding,
)
from nodelang.universal_cell import (
    NULL_CELL_ID,
    Cell,
    CellStore,
    InvalidCell,
    Snapshot,
)


class _NoIterationMapping(Mapping[str, Cell]):
    def __init__(self, cells: Mapping[str, Cell]) -> None:
        self._cells = cells

    def __getitem__(self, key: str) -> Cell:
        return self._cells[key]

    def __iter__(self) -> Iterator[str]:
        raise AssertionError("bounded relation composition scanned the host graph")

    def __len__(self) -> int:
        return len(self._cells)


def test_relation_form_protocol_old_vocabulary_appends_operation(monkeypatch):
    store = CellStore()
    prefix = "test:relation-form-protocol"
    monkeypatch.setattr(
        relation_forms,
        "ROLE_NAMES",
        tuple(name for name in ROLE_NAMES if name != "operation"),
    )
    old = bootstrap_relation_form_protocol(store, prefix=prefix)
    assert all(
        member.participant_id != "%s:role:operation" % prefix
        for member in read_relation(store.snapshot(), old.root_id, budget=256)
    )

    monkeypatch.setattr(relation_forms, "ROLE_NAMES", ROLE_NAMES)
    migrated = bootstrap_relation_form_protocol(store, prefix=prefix)
    assert migrated.role("operation") == "%s:role:operation" % prefix
    assert any(
        member.participant_id == "%s:role:operation" % prefix
        for member in read_relation(store.snapshot(), migrated.root_id, budget=256)
    )


def _world():
    store = CellStore()
    batch = CellBatch(store)
    roots = {
        name: "test:%s" % name
        for name in (
            "owner-role", "label-role", "value-role", "property-role",
            "scope-role", "seed-role", "seed", "owner", "control", "command",
            "operation",
        )
    }
    for name, root in roots.items():
        batch.add(Cell(root, NULL_CELL_ID, NULL_CELL_ID, name.encode("utf-8")))
    batch.relation(
        ((roots["seed-role"], roots["seed"]),), relation_id="test:canvas"
    )
    batch.relation(
        ((roots["seed-role"], roots["seed"]),), relation_id="test:lens"
    )
    batch.relation(
        ((roots["seed-role"], roots["seed"]),), relation_id="test:lens-two"
    )
    batch.commit()

    relation_protocol = bootstrap_relation_contract_protocol(
        store, prefix="test:relation-contract-protocol"
    )
    constraints = []
    for name, role, maximum in (
        ("owner", roots["owner-role"], None),
        ("label", roots["label-role"], 512),
        ("value", roots["value-role"], 65_536),
    ):
        built = build_role_constraint(
            store,
            relation_protocol,
            constraint_id="test:property-contract:%s" % name,
            participant_role=role,
            minimum=1,
            maximum=1,
            terminal_atom_maximum=maximum,
            require_participant_exists=True,
            budget=10_000,
        )
        constraints.append(built.root_id)
    contract = build_relation_contract(
        store,
        relation_protocol,
        contract_id="test:property-contract",
        constraint_roots=constraints,
        released=True,
        budget=10_000,
    )
    form_protocol = bootstrap_relation_form_protocol(
        store, prefix="test:relation-form-protocol"
    )
    binding = build_relation_form_binding(
        store,
        form_protocol,
        binding_id="test:property-form",
        control_root=roots["control"],
        command_root=roots["command"],
        operation_root=roots["operation"],
        relation_contract_root=contract.root_id,
        inputs=(
            {
                "key": "selected",
                "source": "context",
                "value_kind": "root",
                "participant_role": roots["owner-role"],
                "allowed_value_roots": (roots["owner"],),
            },
            {
                "key": "label",
                "source": "submitted",
                "value_kind": "text",
                "required": True,
                "maximum_bytes": 512,
                "participant_role": roots["label-role"],
            },
            {
                "key": "value",
                "source": "submitted",
                "value_kind": "text",
                "required": False,
                "maximum_bytes": 65_536,
                "participant_role": roots["value-role"],
            },
        ),
        attachments=(
            {
                "target_source": "fixed",
                "target_root": "test:canvas",
                "member_role": roots["property-role"],
            },
            {
                "target_source": "context",
                "target_key": "properties-lens",
                "member_role": roots["scope-role"],
            },
        ),
        released=True,
    )
    return store, roots, relation_protocol, form_protocol, binding


def test_released_relation_form_composes_and_attaches_one_valid_relation():
    store, roots, relation_protocol, form_protocol, binding = _world()
    before = store.snapshot()
    candidate = compose_relation_form_submission(
        before,
        form_protocol,
        relation_protocol,
        binding.root_id,
        {"label": "Acoustic rating", "value": "Rw 50"},
        {
            "selected": roots["owner"],
            "properties-lens": ("test:lens", "test:lens-two"),
        },
        relation_id="test:property",
    )
    store.commit(before.revision, create=candidate.create, replace=candidate.replace)
    snapshot = store.snapshot()

    validation = validate_relation(
        snapshot,
        relation_protocol,
        "test:property-contract",
        candidate.relation_root,
        budget=10_000,
    )
    assert validation.member_count == 3
    assert candidate.input_participants["selected"] == roots["owner"]
    assert snapshot.cells[candidate.input_participants["label"]].atom == (
        b"Acoustic rating"
    )
    assert snapshot.cells[candidate.input_participants["value"]].atom == b"Rw 50"
    assert any(
        member.role_id == roots["property-role"]
        and member.participant_id == candidate.relation_root
        for member in read_relation(snapshot, "test:canvas")
    )
    assert any(
        member.role_id == roots["scope-role"]
        and member.participant_id == candidate.relation_root
        for member in read_relation(snapshot, "test:lens")
    )
    assert any(
        member.role_id == roots["scope-role"]
        and member.participant_id == candidate.relation_root
        for member in read_relation(snapshot, "test:lens-two")
    )


def test_relation_form_candidate_does_not_scan_the_host_graph():
    store, roots, relation_protocol, form_protocol, binding = _world()
    before = store.snapshot()
    bounded = Snapshot(
        before.revision,
        _NoIterationMapping(before.cells),
    )

    candidate = compose_relation_form_submission(
        bounded,
        form_protocol,
        relation_protocol,
        binding.root_id,
        {"label": "Acoustic rating", "value": "Rw 50"},
        {
            "selected": roots["owner"],
            "properties-lens": ("test:lens", "test:lens-two"),
        },
        relation_id="test:bounded-property",
    )

    assert candidate.relation_root == "test:bounded-property"
    assert candidate.create


def test_relation_form_submission_folds_rewrites_to_new_relation_cells():
    store, roots, relation_protocol, form_protocol, _binding = _world()
    self_binding = build_relation_form_binding(
        store,
        form_protocol,
        binding_id="test:self-attaching-property-form",
        control_root=roots["control"],
        command_root=roots["command"],
        operation_root=roots["operation"],
        relation_contract_root="test:property-contract",
        inputs=(
            {
                "key": "selected",
                "source": "context",
                "value_kind": "root",
                "participant_role": roots["owner-role"],
                "allowed_value_roots": (roots["owner"],),
            },
            {
                "key": "label",
                "source": "submitted",
                "value_kind": "text",
                "required": True,
                "maximum_bytes": 512,
                "participant_role": roots["label-role"],
            },
            {
                "key": "value",
                "source": "submitted",
                "value_kind": "text",
                "required": False,
                "maximum_bytes": 65_536,
                "participant_role": roots["value-role"],
            },
        ),
        attachments=({
            "target_source": "context",
            "target_key": "created-relation",
            "member_role": roots["scope-role"],
        },),
        released=True,
    )
    before = store.snapshot()
    relation_id = "test:self-attached-property"
    candidate = compose_relation_form_submission(
        before,
        form_protocol,
        relation_protocol,
        self_binding.root_id,
        {"label": "Self visible", "value": "folded"},
        {
            "selected": roots["owner"],
            "created-relation": relation_id,
        },
        relation_id=relation_id,
    )
    create_ids = {cell.id for cell in candidate.create}
    replace_ids = {cell.id for cell in candidate.replace}
    assert create_ids.isdisjoint(replace_ids)
    assert all(root in before.cells for root in replace_ids)

    store.commit(
        before.revision,
        create=candidate.create,
        replace=candidate.replace,
    )
    assert any(
        member.role_id == roots["scope-role"]
        and member.participant_id == relation_id
        for member in read_relation(store.snapshot(), relation_id)
    )


def test_relation_form_rejects_hidden_fields_missing_context_and_byte_overflow():
    store, roots, relation_protocol, form_protocol, binding = _world()
    snapshot = store.snapshot()
    context = {"selected": roots["owner"], "properties-lens": "test:lens"}
    with pytest.raises(InvalidCell, match="fields do not match"):
        compose_relation_form_submission(
            snapshot,
            form_protocol,
            relation_protocol,
            binding.root_id,
            {"label": "Name", "value": "", "admin": "true"},
            context,
        )
    with pytest.raises(InvalidCell, match="context input is missing"):
        compose_relation_form_submission(
            snapshot,
            form_protocol,
            relation_protocol,
            binding.root_id,
            {"label": "Name", "value": ""},
            {"properties-lens": "test:lens"},
        )
    with pytest.raises(InvalidCell, match="byte limit"):
        compose_relation_form_submission(
            snapshot,
            form_protocol,
            relation_protocol,
            binding.root_id,
            {"label": "x" * 513, "value": ""},
            context,
        )


def test_relation_form_release_digest_fails_closed_after_graph_tampering():
    store, _roots, _relation_protocol, form_protocol, binding = _world()
    snapshot = store.snapshot()
    key_root = binding.input_specs[1].root_id + ":key"
    key = snapshot.cells[key_root]
    store.commit(snapshot.revision, replace=(Cell(
        key.id, key.link0, key.link1, b"renamed-hidden-field"
    ),))
    with pytest.raises(InvalidCell, match="tampered"):
        read_relation_form_binding(store.snapshot(), form_protocol, binding.root_id)


def test_relation_form_protocol_and_released_binding_reopen_from_cells():
    store, _roots, _relation_protocol, protocol, binding = _world()
    reopened_protocol = open_relation_form_protocol(
        store.snapshot(), prefix="test:relation-form-protocol"
    )
    reopened = read_relation_form_binding(
        store.snapshot(), reopened_protocol, binding.root_id
    )
    assert reopened == binding
    assert reopened_protocol == protocol


def test_relation_form_root_allowlist_and_lifecycle_gates_fail_closed():
    store, roots, relation_protocol, form_protocol, binding = _world()
    snapshot = store.snapshot()
    with pytest.raises(InvalidCell, match="outside its allowlist"):
        compose_relation_form_submission(
            snapshot,
            form_protocol,
            relation_protocol,
            binding.root_id,
            {"label": "Name", "value": ""},
            {"selected": roots["seed"], "properties-lens": "test:lens"},
        )

    draft_form = build_relation_form_binding(
        store,
        form_protocol,
        binding_id="test:draft-form",
        control_root=roots["control"],
        command_root=roots["command"],
        operation_root=roots["operation"],
        relation_contract_root="test:property-contract",
        inputs=({
            "key": "selected",
            "source": "context",
            "value_kind": "root",
            "participant_role": roots["owner-role"],
        },),
        attachments=(),
        released=False,
    )
    with pytest.raises(InvalidCell, match="not released"):
        compose_relation_form_submission(
            store.snapshot(),
            form_protocol,
            relation_protocol,
            draft_form.root_id,
            {},
            {"selected": roots["owner"]},
        )

    released_contract = read_relation_contract(
        store.snapshot(), relation_protocol, "test:property-contract", budget=10_000
    )
    draft_contract = build_relation_contract(
        store,
        relation_protocol,
        contract_id="test:draft-property-contract",
        constraint_roots=released_contract.constraint_roots,
        budget=10_000,
    )
    released_form = build_relation_form_binding(
        store,
        form_protocol,
        binding_id="test:released-form-over-draft-contract",
        control_root=roots["control"],
        command_root=roots["command"],
        operation_root=roots["operation"],
        relation_contract_root=draft_contract.root_id,
        inputs=({
            "key": "selected",
            "source": "context",
            "value_kind": "root",
            "participant_role": roots["owner-role"],
        },),
        attachments=(),
        released=True,
    )
    with pytest.raises(InvalidCell, match="unreleased relation contract"):
        compose_relation_form_submission(
            store.snapshot(),
            form_protocol,
            relation_protocol,
            released_form.root_id,
            {},
            {"selected": roots["owner"]},
        )


def test_relation_form_builder_rejects_ambiguous_or_coerced_specs_before_commit():
    store, roots, _relation_protocol, form_protocol, _binding = _world()
    before = store.snapshot()
    with pytest.raises(InvalidCell, match="input specification is invalid"):
        build_relation_form_binding(
            store,
            form_protocol,
            binding_id="test:bad-coercion",
            control_root=roots["control"],
            command_root=roots["command"],
            operation_root=roots["operation"],
            relation_contract_root="test:property-contract",
            inputs=({
                "key": "label",
                "source": "submitted",
                "value_kind": "text",
                "required": "false",
                "participant_role": roots["label-role"],
            },),
            attachments=(),
        )
    assert store.snapshot() == before

    with pytest.raises(InvalidCell, match="input specification is invalid"):
        build_relation_form_binding(
            store,
            form_protocol,
            binding_id="test:duplicate-keys",
            control_root=roots["control"],
            command_root=roots["command"],
            operation_root=roots["operation"],
            relation_contract_root="test:property-contract",
            inputs=tuple({
                "key": "label",
                "source": "submitted",
                "value_kind": "text",
                "participant_role": roots["label-role"],
            } for _ in range(2)),
            attachments=(),
        )
    assert store.snapshot() == before
