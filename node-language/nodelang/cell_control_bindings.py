"""Graph-held activation and applicability for visible controls.

This protocol does not execute graph atoms.  It projects exact admitted
capability identities, inert argument values, and generic predicate trees.
Device adapters must separately allowlist the capability roots they support.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .cell_control_presentations import ControlCatalogBuild
from .cell_protocols import compose_relation_cells, read_relation
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot


PROTOCOL_PREFIX = "app:control-binding-protocol:v1"
CATALOG_ROOT = "app:control-binding-catalog:v1"
ROLE_NAMES = (
    "vocabulary-member",
    "catalog-member",
    "control",
    "activation",
    "condition",
    "capability",
    "argument",
    "key",
    "value",
    "operator",
    "operand",
)

CAPABILITY_VIEW_SECTION = "app:device-capability:view-section"
CAPABILITY_INSTANTIATE = "app:device-capability:instantiate"
CAPABILITY_SCOPE = "app:device-capability:scope"
CAPABILITY_VIEWPORT = "app:device-capability:viewport"
CAPABILITY_COMPOSITION = "app:device-capability:composition"
CAPABILITY_HISTORY = "app:device-capability:history"
CAPABILITY_RELATION_FORM = "app:device-capability:relation-form"
CAPABILITY_EDIT_VALUE = "app:device-capability:edit-value"
CAPABILITY_RELATION_MEMBERS = "app:device-capability:relation-members"
CAPABILITY_TOPOLOGY = "app:device-capability:topology"
CAPABILITY_TRANSITION = "app:device-capability:transition"
# Running a declared host operation is its own capability. Folding it
# into an existing one would let a control that may reach a machine
# be granted by a permission written for something that cannot.
CAPABILITY_EXECUTE = "app:device-capability:execute"
CAPABILITIES = MappingProxyType({
    "execute": CAPABILITY_EXECUTE,
    "view-section": CAPABILITY_VIEW_SECTION,
    "instantiate": CAPABILITY_INSTANTIATE,
    "scope": CAPABILITY_SCOPE,
    "viewport": CAPABILITY_VIEWPORT,
    "composition": CAPABILITY_COMPOSITION,
    "history": CAPABILITY_HISTORY,
    "relation-form": CAPABILITY_RELATION_FORM,
    "edit-value": CAPABILITY_EDIT_VALUE,
    "relation-members": CAPABILITY_RELATION_MEMBERS,
    "topology": CAPABILITY_TOPOLOGY,
    "transition": CAPABILITY_TRANSITION,
})

OP_TRUE = "app:control-operator:true"
OP_TRUTHY = "app:control-operator:truthy"
OP_EQUAL = "app:control-operator:equal"
OP_AT_LEAST = "app:control-operator:at-least"
OP_ALL = "app:control-operator:all"
OPERATORS = MappingProxyType({
    "true": OP_TRUE,
    "truthy": OP_TRUTHY,
    "equal": OP_EQUAL,
    "at-least": OP_AT_LEAST,
    "all": OP_ALL,
})

FACT_SCOPE_PARENT = "app:control-fact:scope-parent-present"
FACT_SELECTION_COUNT = "app:control-fact:selection-count"
FACT_FOCUS_COMPOSITION = "app:control-fact:focus-is-composition"
# Whether the focused node declares a host operation. A canvas can
# hold nodes that mean something and nodes that DO something, and a
# control that acts on a machine must be able to tell them apart.
FACT_FOCUS_OPERATION = "app:control-fact:focus-is-operation"
FACT_CAN_UNDO = "app:control-fact:can-undo"
FACT_CAN_REDO = "app:control-fact:can-redo"
FACTS = MappingProxyType({
    "scope-parent-present": FACT_SCOPE_PARENT,
    "selection-count": FACT_SELECTION_COUNT,
    "focus-is-composition": FACT_FOCUS_COMPOSITION,
    "focus-is-operation": FACT_FOCUS_OPERATION,
    "can-undo": FACT_CAN_UNDO,
    "can-redo": FACT_CAN_REDO,
})

PROTOCOL_CAPABILITY_ORDER = (
    "view-section",
    "instantiate",
    "scope",
    "viewport",
    "composition",
    "history",
)
PROTOCOL_ADDED_CAPABILITY_ORDER = (
    "relation-form", "edit-value", "relation-members", "topology",
    "transition",
)


@dataclass(frozen=True, slots=True)
class FactOperand:
    name: str


@dataclass(frozen=True, slots=True)
class LiteralOperand:
    value: str


@dataclass(frozen=True, slots=True)
class ConditionSpec:
    operator: str
    operands: tuple["ConditionOperand", ...] = ()


ConditionOperand = FactOperand | LiteralOperand | ConditionSpec


@dataclass(frozen=True, slots=True)
class ControlBindingSpec:
    control_root: str
    capability: str
    arguments: tuple[tuple[str, str], ...]
    condition: ConditionSpec


ALWAYS = ConditionSpec("true")
CONTROL_BINDING_SPECS = (
    ControlBindingSpec(
        "app:control:rail:home", "view-section", (("section", "home"),), ALWAYS
    ),
    ControlBindingSpec(
        "app:control:rail:search", "view-section", (("section", "search"),), ALWAYS
    ),
    ControlBindingSpec(
        "app:control:rail:share", "view-section", (("section", "share"),), ALWAYS
    ),
    ControlBindingSpec(
        "app:control:rail:settings", "view-section", (("section", "settings"),), ALWAYS
    ),
    ControlBindingSpec(
        "app:control:library:place", "instantiate", (), ALWAYS
    ),
    ControlBindingSpec(
        "app:control:canvas:scope-up",
        "scope",
        (("target", "parent"),),
        ConditionSpec("truthy", (FactOperand("scope-parent-present"),)),
    ),
    ControlBindingSpec(
        "app:control:canvas:zoom-out",
        "viewport",
        (("operation", "delta"), ("amount", "-0.1")),
        ALWAYS,
    ),
    ControlBindingSpec(
        "app:control:canvas:zoom-in",
        "viewport",
        (("operation", "delta"), ("amount", "0.1")),
        ALWAYS,
    ),
    ControlBindingSpec(
        "app:control:canvas:fit",
        "viewport",
        (("operation", "fit"),),
        ALWAYS,
    ),
    ControlBindingSpec(
        "app:control:canvas:undo",
        "history",
        (("operation", "undo"),),
        ConditionSpec("truthy", (FactOperand("can-undo"),)),
    ),
    ControlBindingSpec(
        "app:control:canvas:redo",
        "history",
        (("operation", "redo"),),
        ConditionSpec("truthy", (FactOperand("can-redo"),)),
    ),
    ControlBindingSpec(
        "app:control:canvas:group",
        "composition",
        (("operation", "group"),),
        ConditionSpec("at-least", (
            FactOperand("selection-count"), LiteralOperand("2"),
        )),
    ),
    ControlBindingSpec(
        "app:control:canvas:ungroup",
        "composition",
        (("operation", "ungroup"),),
        ConditionSpec("all", (
            ConditionSpec("equal", (
                FactOperand("selection-count"), LiteralOperand("1"),
            )),
            ConditionSpec("truthy", (FactOperand("focus-is-composition"),)),
        )),
    ),
    ControlBindingSpec(
        "app:control:canvas:run",
        "execute",
        (),
        # A Run offered where nothing runnable is selected is a control that
        # lies about what the graph can do, so it appears only when exactly
        # one node is focused and that node declares a host operation.
        ConditionSpec("all", (
            ConditionSpec("equal", (
                FactOperand("selection-count"), LiteralOperand("1"),
            )),
            ConditionSpec("truthy", (FactOperand("focus-is-operation"),)),
        )),
    ),
    ControlBindingSpec(
        "app:control:inspector:add-property",
        "relation-form",
        (("form", "app:relation-form:property:v3"),),
        ALWAYS,
    ),
    ControlBindingSpec(
        "app:control:inspector:add-interface",
        "relation-form",
        (("form", "app:relation-form:interface:v3"),),
        ALWAYS,
    ),
)

RELATION_FORM_POINTER_UPGRADES = MappingProxyType({
    "app:control-binding:inspector:add-property:activation:argument:0:value": (
        frozenset((
            b"app:relation-form:property:v1",
            b"app:relation-form:property:v2",
        )),
        b"app:relation-form:property:v3",
    ),
    "app:control-binding:inspector:add-interface:activation:argument:0:value": (
        frozenset((
            b"app:relation-form:interface:v1",
            b"app:relation-form:interface:v2",
        )),
        b"app:relation-form:interface:v3",
    ),
})


@dataclass(frozen=True, slots=True)
class ControlBindingProtocol:
    root_id: str
    roles: Mapping[str, str]
    capabilities: Mapping[str, str]
    operators: Mapping[str, str]
    facts: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown control-binding role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class ControlBinding:
    root_id: str
    control_root: str
    activation_root: str
    capability_root: str
    arguments: Mapping[str, str]
    condition_root: str


@dataclass(frozen=True, slots=True)
class ControlBindingBuild:
    protocol: ControlBindingProtocol
    catalog_root: str
    binding_roots: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ControlBindingCatalogProjection:
    root_id: str
    bindings: Mapping[str, ControlBinding]


def _leaf(expected: dict[str, Cell], root_id: str, value: str) -> str:
    cell = Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))
    previous = expected.get(root_id)
    if previous is not None and previous != cell:
        raise InvalidCell("control-binding identity collision")
    expected[root_id] = cell
    return root_id


def _relation(expected: dict[str, Cell], root_id: str, members) -> str:
    for cell in compose_relation_cells(tuple(members), relation_id=root_id).cells:
        previous = expected.get(cell.id)
        if previous is not None and previous != cell:
            raise InvalidCell("control-binding relation collision")
        expected[cell.id] = cell
    return root_id


def _protocol_vocabulary_members(
    roles: Mapping[str, str],
) -> tuple[tuple[str, str], ...]:
    member_role = roles["vocabulary-member"]
    roots = (
        *roles.values(),
        *(CAPABILITIES[name] for name in PROTOCOL_CAPABILITY_ORDER),
        *OPERATORS.values(),
        *FACTS.values(),
        *(CAPABILITIES[name] for name in PROTOCOL_ADDED_CAPABILITY_ORDER),
    )
    return tuple((member_role, root) for root in roots)


def _is_additive_relation_tail_upgrade(
    snapshot: Snapshot,
    relation_root: str,
    expected_members: tuple[tuple[str, str], ...],
    drift: tuple[str, Cell, Cell],
) -> bool:
    root_id, existing, expected = drift
    if relation_root not in snapshot.cells:
        return False
    try:
        existing_members = read_relation(snapshot, relation_root, budget=256)
    except InvalidCell:
        return False
    existing_pairs = tuple(
        (member.role_id, member.participant_id)
        for member in existing_members
    )
    if (
        not existing_pairs
        or len(existing_pairs) >= len(expected_members)
        or existing_pairs != expected_members[:len(existing_pairs)]
    ):
        return False
    tail_index = len(existing_pairs) - 1
    expected_tail_id = (
        relation_root if tail_index == 0
        else "%s:chain:%s" % (relation_root, tail_index)
    )
    return (
        root_id == expected_tail_id
        and existing.id == expected.id
        and existing.link0 == expected.link0
        and existing.link1 == NULL_CELL_ID
        and expected.link1 != NULL_CELL_ID
        and existing.atom == expected.atom
    )


def _is_relation_form_pointer_upgrade(
    drift: tuple[str, Cell, Cell],
) -> bool:
    root_id, existing, expected = drift
    migration = RELATION_FORM_POINTER_UPGRADES.get(root_id)
    return (
        migration is not None
        and existing.link0 == NULL_CELL_ID
        and existing.link1 == NULL_CELL_ID
        and expected.link0 == NULL_CELL_ID
        and expected.link1 == NULL_CELL_ID
        and existing.atom in migration[0]
        and expected.atom == migration[1]
    )


def _condition_cells(
    expected: dict[str, Cell],
    roles: Mapping[str, str],
    root_id: str,
    specification: ConditionSpec,
) -> str:
    try:
        operator_root = OPERATORS[specification.operator]
    except KeyError as exc:
        raise InvalidCell("condition references an unknown operator") from exc
    operands: list[str] = []
    for index, operand in enumerate(specification.operands):
        if isinstance(operand, FactOperand):
            try:
                operand_root = FACTS[operand.name]
            except KeyError as exc:
                raise InvalidCell("condition references an unknown fact") from exc
        elif isinstance(operand, LiteralOperand):
            operand_root = _leaf(
                expected, "%s:literal:%s" % (root_id, index), operand.value
            )
        elif isinstance(operand, ConditionSpec):
            operand_root = _condition_cells(
                expected,
                roles,
                "%s:condition:%s" % (root_id, index),
                operand,
            )
        else:  # pragma: no cover - frozen internal specification guard
            raise InvalidCell("condition operand has an unknown shape")
        operands.append(operand_root)
    return _relation(expected, root_id, (
        (roles["operator"], operator_root),
        *((roles["operand"], operand_root) for operand_root in operands),
    ))


def ensure_archhub_control_binding_catalog(
    store: CellStore,
    controls: ControlCatalogBuild,
) -> ControlBindingBuild:
    """Materialize inert control bindings as ordinary graph compositions."""
    expected: dict[str, Cell] = {}
    roles = {
        name: "%s:role:%s" % (PROTOCOL_PREFIX, name) for name in ROLE_NAMES
    }
    for name, root_id in roles.items():
        _leaf(expected, root_id, name)
    for name, root_id in CAPABILITIES.items():
        _leaf(expected, root_id, name)
    for name, root_id in OPERATORS.items():
        _leaf(expected, root_id, name)
    for name, root_id in FACTS.items():
        _leaf(expected, root_id, name)
    protocol_members = _protocol_vocabulary_members(roles)
    protocol_root = _relation(
        expected, PROTOCOL_PREFIX + ":root", protocol_members
    )

    binding_roots: dict[str, str] = {}
    for specification in CONTROL_BINDING_SPECS:
        control_presentation = controls.control_roots.get(specification.control_root)
        if control_presentation is None:
            raise InvalidCell("binding references a control outside the catalogue")
        try:
            capability_root = CAPABILITIES[specification.capability]
        except KeyError as exc:
            raise InvalidCell("binding references an unknown capability") from exc
        token = specification.control_root.removeprefix("app:control:")
        binding_root = "app:control-binding:%s" % token
        activation_root = binding_root + ":activation"
        argument_roots = []
        for index, (key, value) in enumerate(specification.arguments):
            argument_root = "%s:argument:%s" % (activation_root, index)
            key_root = _leaf(expected, argument_root + ":key", key)
            value_root = _leaf(expected, argument_root + ":value", value)
            _relation(expected, argument_root, (
                (roles["key"], key_root), (roles["value"], value_root),
            ))
            argument_roots.append(argument_root)
        _relation(expected, activation_root, (
            (roles["capability"], capability_root),
            *((roles["argument"], root) for root in argument_roots),
        ))
        condition_root = _condition_cells(
            expected, roles, binding_root + ":condition", specification.condition
        )
        _relation(expected, binding_root, (
            (roles["control"], specification.control_root),
            (roles["activation"], activation_root),
            (roles["condition"], condition_root),
        ))
        binding_roots[specification.control_root] = binding_root
    catalog_members = tuple(
        (roles["catalog-member"], root) for root in binding_roots.values()
    )
    _relation(expected, CATALOG_ROOT, catalog_members)

    snapshot = store.snapshot()
    drifted: list[tuple[str, Cell, Cell]] = []
    for root_id, expected_cell in expected.items():
        existing = snapshot.cells.get(root_id)
        if existing is not None and existing != expected_cell:
            drifted.append((root_id, existing, expected_cell))
    if drifted and not all(
        _is_additive_relation_tail_upgrade(
            snapshot, protocol_root, protocol_members, drift
        )
        or _is_additive_relation_tail_upgrade(
            snapshot, CATALOG_ROOT, catalog_members, drift
        )
        or _is_relation_form_pointer_upgrade(drift)
        for drift in drifted
    ):
        raise InvalidCell(
            "persisted control binding drifted at %s" % drifted[0][0]
        )
    missing = tuple(
        cell for root_id, cell in expected.items() if root_id not in snapshot.cells
    )
    replacement = tuple(expected_cell for _root, _old, expected_cell in drifted)
    if missing or replacement:
        store.commit(snapshot.revision, create=missing, replace=replacement)
    return ControlBindingBuild(
        ControlBindingProtocol(
            protocol_root,
            MappingProxyType(roles),
            CAPABILITIES,
            OPERATORS,
            FACTS,
        ),
        CATALOG_ROOT,
        MappingProxyType(binding_roots),
    )


def _single(members, role_id: str, label: str) -> str:
    values = tuple(
        member.participant_id for member in members if member.role_id == role_id
    )
    if len(values) != 1:
        raise InvalidCell("control binding must have exactly one %s" % label)
    return values[0]


def _text(snapshot: Snapshot, root_id: str) -> str:
    try:
        cell = snapshot.cells[root_id]
        if cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
            raise InvalidCell("control binding value is not terminal")
        return cell.atom.decode("utf-8")
    except (KeyError, UnicodeDecodeError) as exc:
        raise InvalidCell("control binding value is missing or invalid") from exc


def project_control_binding(
    snapshot: Snapshot,
    protocol: ControlBindingProtocol,
    binding_root: str,
) -> ControlBinding:
    members = read_relation(snapshot, binding_root, budget=256)
    declared = {
        protocol.role("control"), protocol.role("activation"),
        protocol.role("condition"),
    }
    if any(member.role_id not in declared for member in members):
        raise InvalidCell("control binding has an undeclared role")
    control_root = _single(members, protocol.role("control"), "control")
    activation_root = _single(
        members, protocol.role("activation"), "activation"
    )
    condition_root = _single(members, protocol.role("condition"), "condition")
    activation = read_relation(snapshot, activation_root, budget=128)
    activation_roles = {protocol.role("capability"), protocol.role("argument")}
    if any(member.role_id not in activation_roles for member in activation):
        raise InvalidCell("control activation has an undeclared role")
    capability_root = _single(
        activation, protocol.role("capability"), "capability"
    )
    if capability_root not in protocol.capabilities.values():
        raise InvalidCell("control activation capability is not admitted")
    arguments: dict[str, str] = {}
    for member in activation:
        if member.role_id != protocol.role("argument"):
            continue
        argument = read_relation(snapshot, member.participant_id, budget=32)
        key = _text(
            snapshot, _single(argument, protocol.role("key"), "argument key")
        )
        value = _text(
            snapshot, _single(argument, protocol.role("value"), "argument value")
        )
        if not key or key in arguments:
            raise InvalidCell("control activation repeats or empties an argument")
        arguments[key] = value
    return ControlBinding(
        binding_root,
        control_root,
        activation_root,
        capability_root,
        MappingProxyType(arguments),
        condition_root,
    )


def project_control_binding_catalog(
    snapshot: Snapshot,
    protocol: ControlBindingProtocol,
    catalog_root: str,
) -> ControlBindingCatalogProjection:
    members = read_relation(snapshot, catalog_root, budget=512)
    bindings: dict[str, ControlBinding] = {}
    for member in members:
        if member.role_id != protocol.role("catalog-member"):
            raise InvalidCell("control-binding catalogue has an undeclared role")
        binding = project_control_binding(snapshot, protocol, member.participant_id)
        if binding.control_root in bindings:
            raise InvalidCell("control-binding catalogue repeats a control")
        bindings[binding.control_root] = binding
    if not bindings:
        raise InvalidCell("control-binding catalogue is empty")
    return ControlBindingCatalogProjection(
        catalog_root, MappingProxyType(bindings)
    )


def _literal_value(value: str) -> object:
    if value == "true":
        return True
    if value == "false":
        return False
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def evaluate_control_condition(
    snapshot: Snapshot,
    protocol: ControlBindingProtocol,
    condition_root: str,
    facts: Mapping[str, object],
    *,
    budget: int = 128,
) -> bool:
    """Evaluate a bounded generic predicate tree; unknown data fails closed."""
    remaining = [budget]
    active: set[str] = set()

    def operand_value(root_id: str) -> object:
        if root_id in protocol.facts.values():
            if root_id not in facts:
                raise InvalidCell("control condition fact is missing")
            return facts[root_id]
        cell = snapshot.cells.get(root_id)
        if cell is None:
            raise InvalidCell("control condition operand is missing")
        if cell.link0 == NULL_CELL_ID and cell.link1 == NULL_CELL_ID:
            return _literal_value(_text(snapshot, root_id))
        return evaluate(root_id)

    def evaluate(root_id: str) -> bool:
        remaining[0] -= 1
        if remaining[0] < 0:
            raise InvalidCell("control condition exceeds its evaluation budget")
        if root_id in active:
            raise InvalidCell("control condition contains a cycle")
        active.add(root_id)
        try:
            members = read_relation(snapshot, root_id, budget=budget)
            allowed = {protocol.role("operator"), protocol.role("operand")}
            if any(member.role_id not in allowed for member in members):
                raise InvalidCell("control condition has an undeclared role")
            operator_root = _single(
                members, protocol.role("operator"), "operator"
            )
            values = tuple(
                operand_value(member.participant_id) for member in members
                if member.role_id == protocol.role("operand")
            )
            if operator_root == protocol.operators["true"]:
                if values:
                    raise InvalidCell("true condition cannot have operands")
                return True
            if operator_root == protocol.operators["truthy"]:
                if len(values) != 1:
                    raise InvalidCell("truthy condition requires one operand")
                return bool(values[0])
            if operator_root == protocol.operators["equal"]:
                if len(values) != 2:
                    raise InvalidCell("equal condition requires two operands")
                return values[0] == values[1]
            if operator_root == protocol.operators["at-least"]:
                if (
                    len(values) != 2
                    or any(type(value) not in (int, float) for value in values)
                ):
                    raise InvalidCell("at-least condition requires two numbers")
                return values[0] >= values[1]
            if operator_root == protocol.operators["all"]:
                if not values or any(type(value) is not bool for value in values):
                    raise InvalidCell("all condition requires boolean operands")
                return all(values)
            raise InvalidCell("control condition operator is not admitted")
        finally:
            active.remove(root_id)

    return evaluate(condition_root)


__all__ = [
    "CAPABILITIES",
    "CAPABILITY_COMPOSITION",
    "CAPABILITY_EDIT_VALUE",
    "CAPABILITY_INSTANTIATE",
    "CAPABILITY_HISTORY",
    "CAPABILITY_RELATION_FORM",
    "CAPABILITY_RELATION_MEMBERS",
    "CAPABILITY_TOPOLOGY",
    "CAPABILITY_EXECUTE",
    "CAPABILITY_TRANSITION",
    "CAPABILITY_SCOPE",
    "CAPABILITY_VIEWPORT",
    "CAPABILITY_VIEW_SECTION",
    "CATALOG_ROOT",
    "CONTROL_BINDING_SPECS",
    "ControlBinding",
    "ControlBindingBuild",
    "ControlBindingCatalogProjection",
    "ControlBindingProtocol",
    "ControlBindingSpec",
    "FACT_FOCUS_COMPOSITION",
    "FACT_FOCUS_OPERATION",
    "FACT_CAN_UNDO",
    "FACT_CAN_REDO",
    "FACT_SCOPE_PARENT",
    "FACT_SELECTION_COUNT",
    "ensure_archhub_control_binding_catalog",
    "evaluate_control_condition",
    "project_control_binding",
    "project_control_binding_catalog",
]
