"""Cell-native policy for canvas interaction feel and limits.

This is a released assembly above the universal Cell floor, not a new kernel
kind.  The browser adapter may project these values into JavaScript, but the
source of truth is a visible relation graph whose setting values are Cells.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Mapping

from .cell_protocols import (
    prepare_append_relation_member,
    read_relation,
)
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


ROLE_NAMES = (
    "vocabulary-member",
    "policy-member",
    "canvas",
    "setting",
    "field",
    "value",
    "allowed-value",
    "evidence",
)

FIELD_DEFAULTS = MappingProxyType({
    "zoom-min": "0.1",
    "zoom-max": "4.0",
    "zoom-fit-max": "1.25",
    "zoom-toolbar-step": "0.1",
    "zoom-wheel-sensitivity": "0.0015",
    "zoom-wheel-delta-cap": "800",
    "selection-drag-threshold-px": "3",
    "marquee-window-direction": "left-to-right",
    "marquee-crossing-direction": "right-to-left",
    "shift-selection-mode": "remove",
    "ctrl-selection-mode": "add",
    "pointer-capture-required": "true",
    "viewport-commit-debounce-ms": "140",
    "gesture-suppression-ms": "300",
    "target-fps": "60",
    "feedback-budget-ms": "16",
    "commit-budget-ms": "250",
    "projection-payload-budget-bytes": "1048576",
})

FIELD_KINDS = MappingProxyType({
    "zoom-min": "number",
    "zoom-max": "number",
    "zoom-fit-max": "number",
    "zoom-toolbar-step": "number",
    "zoom-wheel-sensitivity": "number",
    "zoom-wheel-delta-cap": "number",
    "selection-drag-threshold-px": "number",
    "marquee-window-direction": "direction",
    "marquee-crossing-direction": "direction",
    "shift-selection-mode": "selection-mode",
    "ctrl-selection-mode": "selection-mode",
    "pointer-capture-required": "boolean",
    "viewport-commit-debounce-ms": "number",
    "gesture-suppression-ms": "number",
    "target-fps": "number",
    "feedback-budget-ms": "number",
    "commit-budget-ms": "number",
    "projection-payload-budget-bytes": "number",
})

ENUM_VALUES = MappingProxyType({
    "direction": ("left-to-right", "right-to-left"),
    "selection-mode": ("replace", "add", "remove", "toggle"),
    "boolean": ("true", "false"),
})


@dataclass(frozen=True, slots=True)
class CanvasInteractionPolicyProtocol:
    root_id: str
    roles: Mapping[str, str]
    fields: Mapping[str, str]
    enum_values: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown canvas interaction role") from exc


@dataclass(frozen=True, slots=True)
class CanvasInteractionPolicyProjection:
    root_id: str
    canvas_root: str
    setting_roots: Mapping[str, str]
    field_roots: Mapping[str, str]
    value_roots: Mapping[str, str]
    values: Mapping[str, str]
    evidence_roots: tuple[str, ...]


def _terminal(root_id: str, value: object) -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, str(value).encode("utf-8"))


def _part(value: str) -> str:
    return "".join(
        character if character.isalnum() else "-"
        for character in value.lower()
    ).strip("-")


def _text(snapshot: Snapshot, root_id: str, label: str) -> str:
    try:
        cell = snapshot.cells[root_id]
    except KeyError as exc:
        raise InvalidCell("%s Cell is missing" % label) from exc
    if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
        raise InvalidCell("%s is not a terminal Cell" % label)
    try:
        return cell.atom.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidCell("%s is not text" % label) from exc


def _role_map(prefix: str) -> Mapping[str, str]:
    return MappingProxyType({
        name: "%s:role:%s" % (prefix, name) for name in ROLE_NAMES
    })


def _field_map(prefix: str) -> Mapping[str, str]:
    return MappingProxyType({
        name: "%s:field:%s" % (prefix, name)
        for name in FIELD_DEFAULTS
    })


def _enum_map(prefix: str) -> Mapping[str, str]:
    return MappingProxyType({
        value: "%s:enum:%s" % (prefix, _part(value))
        for values in ENUM_VALUES.values()
        for value in values
    })


def bootstrap_canvas_interaction_policy_protocol(
    store: CellStore,
    *,
    prefix: str = "canvas-interaction-policy-protocol",
) -> CanvasInteractionPolicyProtocol:
    root_id = prefix + ":root"
    if root_id in store.snapshot().cells:
        return project_canvas_interaction_policy_protocol(
            store.snapshot(), prefix=prefix
        )
    roles = _role_map(prefix)
    fields = _field_map(prefix)
    enum_values = _enum_map(prefix)
    cells = [
        *(
            _terminal(root, name)
            for name, root in roles.items()
        ),
        *(
            _terminal(root, name)
            for name, root in fields.items()
        ),
        *(
            _terminal(root, value)
            for value, root in enum_values.items()
        ),
    ]
    members = tuple(
        (roles["vocabulary-member"], root)
        for root in (*roles.values(), *fields.values(), *enum_values.values())
    )
    from .cell_protocols import compose_relation_cells

    relation = compose_relation_cells(members, relation_id=root_id)
    store.commit(
        store.revision,
        create=(*cells, *relation.cells),
    )
    return CanvasInteractionPolicyProtocol(
        root_id, roles, fields, enum_values
    )


def project_canvas_interaction_policy_protocol(
    snapshot: Snapshot,
    *,
    prefix: str = "canvas-interaction-policy-protocol",
) -> CanvasInteractionPolicyProtocol:
    roles = _role_map(prefix)
    fields = _field_map(prefix)
    enum_values = _enum_map(prefix)
    root_id = prefix + ":root"
    required = {root_id, *roles.values(), *fields.values(), *enum_values.values()}
    if any(_root not in snapshot.cells for _root in required):
        raise InvalidCell("canvas interaction protocol is incomplete")
    members = read_relation(snapshot, root_id, budget=100_000)
    allowed_roles = {
        roles["vocabulary-member"],
        roles["policy-member"],
    }
    if any(member.role_id not in allowed_roles for member in members):
        raise InvalidCell("canvas interaction protocol has an undeclared role")
    vocabulary = {
        member.participant_id
        for member in members
        if member.role_id == roles["vocabulary-member"]
    }
    if vocabulary != { *roles.values(), *fields.values(), *enum_values.values() }:
        raise InvalidCell("canvas interaction vocabulary drifted")
    for name, root in roles.items():
        if _text(snapshot, root, "role") != name:
            raise InvalidCell("canvas interaction role label drifted")
    for name, root in fields.items():
        if _text(snapshot, root, "field") != name:
            raise InvalidCell("canvas interaction field label drifted")
    for value, root in enum_values.items():
        if _text(snapshot, root, "enum") != value:
            raise InvalidCell("canvas interaction enum label drifted")
    return CanvasInteractionPolicyProtocol(
        root_id, roles, fields, enum_values
    )


def build_canvas_interaction_policy(
    store: CellStore,
    protocol: CanvasInteractionPolicyProtocol,
    *,
    policy_id: str = "canvas-interaction-policy",
    canvas_root: str,
    values: Mapping[str, object] | None = None,
    evidence_roots: tuple[str, ...] = (),
) -> CanvasInteractionPolicyProjection:
    if policy_id in store.snapshot().cells:
        return project_canvas_interaction_policy(
            store.snapshot(), protocol, policy_id
        )
    snapshot = store.snapshot()
    if canvas_root not in snapshot.cells:
        raise InvalidCell("canvas interaction policy target is missing")
    overrides = {key: str(value) for key, value in (values or {}).items()}
    unknown = set(overrides) - set(FIELD_DEFAULTS)
    if unknown:
        raise InvalidCell(
            "canvas interaction policy has unknown fields: %s" % sorted(unknown)
        )
    policy_values = {
        key: overrides.get(key, default)
        for key, default in FIELD_DEFAULTS.items()
    }
    _validate_values(policy_values)
    from .cell_protocols import compose_relation_cells

    create: list[Cell] = []
    policy_members: list[tuple[str, str]] = [
        (protocol.role("canvas"), canvas_root),
    ]
    for root in evidence_roots:
        if root not in snapshot.cells:
            create.append(_terminal(root, root))
        policy_members.append((protocol.role("evidence"), root))
    for key, value in policy_values.items():
        field_root = protocol.fields[key]
        setting_root = "%s:setting:%s" % (policy_id, key)
        value_root = "%s:value:%s" % (policy_id, key)
        create.append(_terminal(value_root, value))
        members: list[tuple[str, str]] = [
            (protocol.role("field"), field_root),
            (protocol.role("value"), value_root),
        ]
        kind = FIELD_KINDS[key]
        if kind in ENUM_VALUES:
            members.extend(
                (protocol.role("allowed-value"), protocol.enum_values[item])
                for item in ENUM_VALUES[kind]
            )
        setting = compose_relation_cells(members, relation_id=setting_root)
        create.extend(setting.cells)
        policy_members.append((protocol.role("setting"), setting_root))
    policy = compose_relation_cells(policy_members, relation_id=policy_id)
    protocol_patch = prepare_append_relation_member(
        snapshot,
        protocol.root_id,
        protocol.role("policy-member"),
        policy_id,
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=(*create, *policy.cells, *protocol_patch.create),
        replace=protocol_patch.replace,
    )
    return project_canvas_interaction_policy(
        store.snapshot(), protocol, policy_id
    )


def project_canvas_interaction_policy(
    snapshot: Snapshot,
    protocol: CanvasInteractionPolicyProtocol,
    policy_root: str,
) -> CanvasInteractionPolicyProjection:
    registered = {
        member.participant_id
        for member in read_relation(snapshot, protocol.root_id, budget=100_000)
        if member.role_id == protocol.role("policy-member")
    }
    if policy_root not in registered:
        raise InvalidCell("canvas interaction policy is not registered")
    members = read_relation(snapshot, policy_root, budget=100_000)
    allowed = {
        protocol.role("canvas"),
        protocol.role("setting"),
        protocol.role("evidence"),
    }
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("canvas interaction policy contains an unknown role")
    canvas_roots = [
        member.participant_id for member in members
        if member.role_id == protocol.role("canvas")
    ]
    if len(canvas_roots) != 1:
        raise InvalidCell("canvas interaction policy requires one canvas")
    setting_by_key: dict[str, str] = {}
    field_by_key: dict[str, str] = {}
    value_by_key: dict[str, str] = {}
    values: dict[str, str] = {}
    reverse_fields = {root: key for key, root in protocol.fields.items()}
    for setting_member in members:
        if setting_member.role_id != protocol.role("setting"):
            continue
        setting_members = read_relation(
            snapshot, setting_member.participant_id, budget=256
        )
        if any(member.role_id not in {
            protocol.role("field"),
            protocol.role("value"),
            protocol.role("allowed-value"),
        } for member in setting_members):
            raise InvalidCell("canvas interaction setting contains unknown role")
        field_roots = [
            member.participant_id for member in setting_members
            if member.role_id == protocol.role("field")
        ]
        value_roots = [
            member.participant_id for member in setting_members
            if member.role_id == protocol.role("value")
        ]
        if len(field_roots) != 1 or len(value_roots) != 1:
            raise InvalidCell("canvas interaction setting is incomplete")
        key = reverse_fields.get(field_roots[0])
        if key is None:
            raise InvalidCell("canvas interaction setting field is undeclared")
        if key in values:
            raise InvalidCell("canvas interaction policy repeats a field")
        value = _text(snapshot, value_roots[0], key)
        allowed_values = {
            _text(snapshot, member.participant_id, "allowed value")
            for member in setting_members
            if member.role_id == protocol.role("allowed-value")
        }
        kind = FIELD_KINDS[key]
        if kind in ENUM_VALUES and allowed_values != set(ENUM_VALUES[kind]):
            raise InvalidCell("canvas interaction setting allowed values drifted")
        setting_by_key[key] = setting_member.participant_id
        field_by_key[key] = field_roots[0]
        value_by_key[key] = value_roots[0]
        values[key] = value
    if set(values) != set(FIELD_DEFAULTS):
        raise InvalidCell("canvas interaction policy field coverage is incomplete")
    _validate_values(values)
    return CanvasInteractionPolicyProjection(
        policy_root,
        canvas_roots[0],
        MappingProxyType(setting_by_key),
        MappingProxyType(field_by_key),
        MappingProxyType(value_by_key),
        MappingProxyType(values),
        tuple(
            member.participant_id for member in members
            if member.role_id == protocol.role("evidence")
        ),
    )


def set_canvas_interaction_policy_value(
    store: CellStore,
    protocol: CanvasInteractionPolicyProtocol,
    policy_root: str,
    field: str,
    value: object,
) -> int:
    projection = project_canvas_interaction_policy(
        store.snapshot(), protocol, policy_root
    )
    if field not in projection.values:
        raise InvalidCell("canvas interaction policy field is unknown")
    next_values = dict(projection.values)
    next_values[field] = str(value)
    _validate_values(next_values)
    value_root = projection.value_roots[field]
    current = store.read(value_root)
    return store.commit(store.revision, replace=(
        Cell(current.id, current.link0, current.link1, str(value).encode("utf-8")),
    ))


def canvas_interaction_policy_payload(
    projection: CanvasInteractionPolicyProjection,
) -> Mapping[str, object]:
    values = projection.values
    return {
        "root": projection.root_id,
        "canvas": projection.canvas_root,
        "settings": [{
            "key": key,
            "setting": projection.setting_roots[key],
            "field": projection.field_roots[key],
            "value_root": projection.value_roots[key],
            "value": values[key],
            "kind": FIELD_KINDS[key],
            "allowed": list(ENUM_VALUES.get(FIELD_KINDS[key], ())),
        } for key in FIELD_DEFAULTS],
        "zoom_min": _number(values, "zoom-min"),
        "zoom_max": _number(values, "zoom-max"),
        "zoom_fit_max": _number(values, "zoom-fit-max"),
        "zoom_toolbar_step": _number(values, "zoom-toolbar-step"),
        "wheel_sensitivity": _number(values, "zoom-wheel-sensitivity"),
        "wheel_delta_cap": _number(values, "zoom-wheel-delta-cap"),
        "drag_threshold_px": _number(values, "selection-drag-threshold-px"),
        "marquee_window_direction": values["marquee-window-direction"],
        "marquee_crossing_direction": values["marquee-crossing-direction"],
        "shift_selection_mode": values["shift-selection-mode"],
        "ctrl_selection_mode": values["ctrl-selection-mode"],
        "pointer_capture_required": values["pointer-capture-required"] == "true",
        "viewport_commit_debounce_ms": _number(
            values, "viewport-commit-debounce-ms"
        ),
        "gesture_suppression_ms": _number(values, "gesture-suppression-ms"),
        "target_fps": _number(values, "target-fps"),
        "feedback_budget_ms": _number(values, "feedback-budget-ms"),
        "commit_budget_ms": _number(values, "commit-budget-ms"),
        "projection_payload_budget_bytes": _number(
            values, "projection-payload-budget-bytes"
        ),
        "evidence": list(projection.evidence_roots),
    }


def _number(values: Mapping[str, str], key: str) -> float:
    try:
        result = float(values[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidCell("canvas interaction %s must be numeric" % key) from exc
    if not math.isfinite(result):
        raise InvalidCell("canvas interaction %s must be finite" % key)
    return result


def _validate_values(values: Mapping[str, str]) -> None:
    for key, kind in FIELD_KINDS.items():
        value = values.get(key)
        if value is None:
            raise InvalidCell("canvas interaction %s is missing" % key)
        if kind == "number":
            _number(values, key)
            continue
        admitted = ENUM_VALUES[kind]
        if value not in admitted:
            raise InvalidCell(
                "canvas interaction %s is outside admitted values" % key
            )
    zoom_min = _number(values, "zoom-min")
    zoom_max = _number(values, "zoom-max")
    fit_max = _number(values, "zoom-fit-max")
    if zoom_min <= 0 or zoom_max < zoom_min:
        raise InvalidCell("canvas interaction zoom bounds are invalid")
    if fit_max < zoom_min or fit_max > zoom_max:
        raise InvalidCell("canvas interaction fit zoom is outside zoom bounds")
    if _number(values, "zoom-toolbar-step") <= 0:
        raise InvalidCell("canvas interaction toolbar step must be positive")
    for key in (
        "zoom-wheel-sensitivity",
        "zoom-wheel-delta-cap",
        "selection-drag-threshold-px",
        "viewport-commit-debounce-ms",
        "gesture-suppression-ms",
        "target-fps",
        "feedback-budget-ms",
        "commit-budget-ms",
        "projection-payload-budget-bytes",
    ):
        if _number(values, key) <= 0:
            raise InvalidCell("canvas interaction %s must be positive" % key)
    if (
        values["marquee-window-direction"]
        == values["marquee-crossing-direction"]
    ):
        raise InvalidCell("canvas marquee modes must use opposite directions")


__all__ = [
    "CanvasInteractionPolicyProjection",
    "CanvasInteractionPolicyProtocol",
    "FIELD_DEFAULTS",
    "bootstrap_canvas_interaction_policy_protocol",
    "build_canvas_interaction_policy",
    "canvas_interaction_policy_payload",
    "project_canvas_interaction_policy",
    "project_canvas_interaction_policy_protocol",
    "set_canvas_interaction_policy_value",
]
