import pytest

from nodelang.cell_canvas_interaction_policy import (
    FIELD_DEFAULTS,
    bootstrap_canvas_interaction_policy_protocol,
    build_canvas_interaction_policy,
    canvas_interaction_policy_payload,
    project_canvas_interaction_policy,
    set_canvas_interaction_policy_value,
)
from nodelang.cell_protocols import build_relation, read_relation
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    project_universal_canvas,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def _store_with_canvas():
    store = CellStore()
    store.commit(store.revision, create=[
        Cell("canvas", NULL_CELL_ID, NULL_CELL_ID, b"canvas root"),
    ])
    return store


def test_canvas_interaction_policy_is_openable_cell_assembly_not_kernel_shape():
    store = _store_with_canvas()
    protocol = bootstrap_canvas_interaction_policy_protocol(store)
    policy = build_canvas_interaction_policy(
        store,
        protocol,
        policy_id="policy:interaction",
        canvas_root="canvas",
        evidence_roots=("evidence:pointer-events",),
    )

    snapshot = store.snapshot()
    assert set(policy.values) == set(FIELD_DEFAULTS)
    assert all(root in snapshot.cells for root in policy.value_roots.values())
    assert all(
        snapshot.cells[root].link0 == NULL_CELL_ID
        and snapshot.cells[root].link1 == NULL_CELL_ID
        for root in policy.value_roots.values()
    )

    members = read_relation(snapshot, policy.root_id, budget=100_000)
    assert [member.participant_id for member in members
            if member.role_id == protocol.role("canvas")] == ["canvas"]
    assert len([
        member for member in members
        if member.role_id == protocol.role("setting")
    ]) == len(FIELD_DEFAULTS)
    assert policy.evidence_roots == ("evidence:pointer-events",)

    protocol_members = read_relation(snapshot, protocol.root_id, budget=100_000)
    assert any(
        member.role_id == protocol.role("policy-member")
        and member.participant_id == policy.root_id
        for member in protocol_members
    )


def test_canvas_interaction_policy_payload_is_precise_and_browser_ready():
    store = _store_with_canvas()
    protocol = bootstrap_canvas_interaction_policy_protocol(store)
    policy = build_canvas_interaction_policy(
        store, protocol, policy_id="policy:interaction", canvas_root="canvas"
    )
    payload = canvas_interaction_policy_payload(policy)

    assert payload["root"] == "policy:interaction"
    assert payload["canvas"] == "canvas"
    assert payload["zoom_min"] == 0.1
    assert payload["zoom_max"] == 4.0
    assert payload["zoom_fit_max"] == 1.25
    assert payload["wheel_sensitivity"] == 0.0015
    assert payload["drag_threshold_px"] == 3.0
    assert payload["marquee_window_direction"] == "left-to-right"
    assert payload["marquee_crossing_direction"] == "right-to-left"
    assert payload["shift_selection_mode"] == "remove"
    assert payload["ctrl_selection_mode"] == "add"
    assert payload["pointer_capture_required"] is True
    assert len(payload["settings"]) == len(FIELD_DEFAULTS)
    assert all(
        set(setting) == {
            "key", "setting", "field", "value_root", "value", "kind",
            "allowed",
        }
        for setting in payload["settings"]
    )


def test_canvas_interaction_policy_knobs_are_editable_cells():
    store = _store_with_canvas()
    protocol = bootstrap_canvas_interaction_policy_protocol(store)
    build_canvas_interaction_policy(
        store, protocol, policy_id="policy:interaction", canvas_root="canvas"
    )

    set_canvas_interaction_policy_value(
        store, protocol, "policy:interaction", "zoom-max", "6.0"
    )
    set_canvas_interaction_policy_value(
        store,
        protocol,
        "policy:interaction",
        "shift-selection-mode",
        "toggle",
    )
    updated = project_canvas_interaction_policy(
        store.snapshot(), protocol, "policy:interaction"
    )

    assert updated.values["zoom-max"] == "6.0"
    assert updated.values["shift-selection-mode"] == "toggle"
    assert canvas_interaction_policy_payload(updated)["zoom_max"] == 6.0


def test_canvas_interaction_policy_rejects_invalid_hidden_feel_values():
    store = _store_with_canvas()
    protocol = bootstrap_canvas_interaction_policy_protocol(store)
    build_canvas_interaction_policy(
        store, protocol, policy_id="policy:interaction", canvas_root="canvas"
    )

    with pytest.raises(InvalidCell, match="zoom bounds"):
        set_canvas_interaction_policy_value(
            store, protocol, "policy:interaction", "zoom-min", "9"
        )
    with pytest.raises(InvalidCell, match="outside admitted values"):
        set_canvas_interaction_policy_value(
            store,
            protocol,
            "policy:interaction",
            "shift-selection-mode",
            "invent-new-mode",
        )
    unchanged = project_canvas_interaction_policy(
        store.snapshot(), protocol, "policy:interaction"
    )
    assert unchanged.values["zoom-min"] == FIELD_DEFAULTS["zoom-min"]
    assert unchanged.values["shift-selection-mode"] == (
        FIELD_DEFAULTS["shift-selection-mode"]
    )


def test_canvas_policy_can_be_wired_to_any_canvas_relation():
    store = _store_with_canvas()
    protocol = bootstrap_canvas_interaction_policy_protocol(store)
    policy = build_canvas_interaction_policy(
        store, protocol, policy_id="policy:interaction", canvas_root="canvas"
    )
    store.commit(store.revision, create=[
        Cell("role:canvas", NULL_CELL_ID, NULL_CELL_ID, b"canvas"),
        Cell("role:policy", NULL_CELL_ID, NULL_CELL_ID, b"policy"),
    ])
    build_relation(
        store,
        (
            ("role:canvas", "canvas"),
            ("role:policy", policy.root_id),
        ),
        relation_id="canvas:policy-wire",
    )

    wire_members = read_relation(
        store.snapshot(), "canvas:policy-wire", budget=32
    )
    assert [(member.role_id, member.participant_id)
            for member in wire_members] == [
        ("role:canvas", "canvas"),
        ("role:policy", "policy:interaction"),
    ]


def test_real_application_projects_cell_backed_interaction_policy():
    store, registry = build_universal_application(resolve_map_path())
    projection = project_universal_canvas(store, registry)
    policy = projection["interaction_policy"]

    assert policy["root"] == registry.canvas_interaction_policy_root
    assert policy["canvas"] == registry.canvas_root
    assert policy["zoom_min"] == 0.1
    assert policy["zoom_max"] == 4.0
    assert policy["wheel_sensitivity"] == 0.0015
    assert len(policy["settings"]) == len(FIELD_DEFAULTS)
    assert all(item["value_root"] in store.snapshot().cells
               for item in policy["settings"])

    canvas_members = read_relation(
        store.snapshot(), registry.canvas_root, budget=100_000
    )
    assert any(
        member.role_id == registry.roles["authority"]
        and member.participant_id == registry.canvas_interaction_policy_root
        for member in canvas_members
    )
