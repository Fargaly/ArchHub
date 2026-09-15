"""Pure final binding preparation after admitted draft value-node exposure.

The native host retains its action and owner locks plus live caller admission, validates the
published receipt, worker, input digest and revision, and authorizes every
returned requirement before one tracked commit with revision comparison. This module creates no grants,
exposes no nodes, commits nothing, and clears no native operation state.
"""
from dataclasses import dataclass
import hashlib
import json
from typing import Mapping

from .cell_protocols import read_relation
from .cell_value_graph import read_value_graph
from .universal_cell import Cell, InvalidCell


_FIELDS = ("inputs", "requirements")
_REQUIREMENTS_ONLY = ("requirements",)
_CONFIGURABLE = ("inputs", "requirements", "cde-container")
_MAX_VIEW_ROOTS = 4096
_MAX_WIRES = 2048


def _selected_fields(fields):
    """Admit the project pair, the gate correction, or an ordered configuration subset."""
    if (type(fields) is not tuple or not fields or len(set(fields)) != len(fields)
            or fields != tuple(name for name in _CONFIGURABLE if name in fields)):
        raise InvalidCell("Project revision fields are invalid")
    return fields


def _is_unwired(cell):
    """A Work port that was never bound points at the null-link 'unwired' Cell."""
    from .universal_cell import NULL_CELL_ID

    return (cell is not None and cell.link0 == NULL_CELL_ID and cell.link1 == NULL_CELL_ID
            and cell.atom == b"unwired")


def requirements_digest(value):
    """Canonical digest of one requirements value; it is not project material."""
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise InvalidCell("Requirements value is not canonical data") from exc
    return hashlib.sha256(raw).hexdigest()


def _material(fields, values, *, title, description, mode=None):
    """Project Works keep their dispatch material; requirements-only keeps its own digest.

    mode "values" digests the exact field values instead (same-Work configuration);
    an unwired field contributes null. Legacy callers never pass a mode.
    """
    from .existing_workshop_project_execution import project_material_from_values

    if mode == "values":
        return None, requirements_digest({name: values[name] for name in fields})
    if mode is not None:
        raise InvalidCell("Project revision material mode is invalid")
    if fields == _FIELDS:
        request, raw = project_material_from_values(values["inputs"], values["requirements"],
                                                    title=title, description=description)
        return request, hashlib.sha256(raw).hexdigest()
    if fields != _REQUIREMENTS_ONLY:
        raise InvalidCell("Project revision fields require an explicit material mode")
    if type(values["requirements"]) is not dict:
        raise InvalidCell("Requirements revision requires one structured requirements value")
    return None, requirements_digest(values["requirements"])


@dataclass(frozen=True, slots=True)
class RevisionAuthorization:
    command_name: str
    object_root: str
    interface_root: str | None


@dataclass(frozen=True, slots=True)
class PreparedProjectRevisionBindings:
    revision: int
    work_root: str
    previous_roots: tuple[tuple[str, str], ...]
    revised_roots: tuple[tuple[str, str], ...]
    wire_roots: tuple[str, ...]
    authorizations: tuple[RevisionAuthorization, ...]
    create: tuple[Cell, ...]
    replace: tuple[Cell, ...]
    input_digest: str


def _roots(value, maximum, label):
    if (type(value) not in (tuple, list) or len(value) > maximum
            or any(type(root) is not str or not root for root in value)
            or len(value) != len(set(value))):
        raise InvalidCell("Project revision %s are invalid or exceed the bound" % label)
    return tuple(value)


def _validate_scoped_reference(snapshot, registry, wire_root, rows, visible_roots, check,
                               scope_root, scope_members):
    """Recognize an incidence-owned reference, never an editable Work binding."""
    from . import universal_application as app

    scopes = tuple(row.participant_id for row in rows if row.role_id == registry.roles["scope"])
    if len(scopes) != 1 or scopes[0] != scope_root:
        # Shared assignments are declared Workshop relations displayed on its
        # Workbench. Admit only the actual registry member and its validated
        # assignment/obligation, never an arbitrary differently scoped wire.
        if (scopes != (registry.workshop_root,) or scope_root != registry.workshop_workbench_root
                or wire_root not in app._workshop_assignment_roots(snapshot, registry)):
            raise InvalidCell("Project revision scoped relation has no exact scope authority")
        assignment = app._read_workshop_assignment(snapshot, registry, wire_root)
        if assignment.workshop_root != registry.workshop_root:
            raise InvalidCell("Project revision assignment authority changed")
    if sum(row.role_id == registry.roles["relation"] and row.participant_id == wire_root
           for row in scope_members) != 1:
        raise InvalidCell("Project revision scoped relation membership is not exact")
    for side in ("source", "target"):
        check()
        endpoints = tuple(row for row in rows if row.role_id == registry.roles[side])
        if len(endpoints) != 1:
            raise InvalidCell("Project revision scoped relation endpoints are ambiguous")
        endpoint = endpoints[0]
        read_relation(snapshot, endpoint.participant_id, budget=256, retain_projection=False)
        interface = app._project_canvas_interface(snapshot, registry.assembly_protocol, endpoint.participant_id)
        if (interface is None or interface["side"] != side
                or interface["owner"] not in visible_roots
                or not interface["read_only"]
                or interface["relation_roots"] != [wire_root]
                or interface["endpoint_incidences"] != [endpoint.incidence_id]
                or interface["previous_roots"]):
            raise InvalidCell("Project revision scoped relation requires its editable authority path")


def _incoming_wires(snapshot, registry, ports, visible_relation_roots, check, visible_roots=(),
                    scope_root=None):
    visible_wires = set(_roots(visible_relation_roots, _MAX_WIRES, "visible wires"))
    members = read_relation(snapshot, registry.canvas_root, budget=100_000,
                            retain_projection=False)
    wires = tuple(member.participant_id for member in members
                  if member.role_id == registry.roles["relation"])
    if len(wires) > _MAX_WIRES or len(wires) != len(set(wires)):
        raise InvalidCell("Project revision wire inventory is ambiguous or exceeds its bound")
    registered_wires = set(wires)
    scope_members = ()
    scope_wires = ()
    if scope_root is not None:
        if type(scope_root) is not str or not scope_root:
            raise InvalidCell("Project revision scope identity is invalid")
        check()
        scope_members = read_relation(snapshot, scope_root, budget=100_000, retain_projection=False)
        scope_wires = _roots(tuple(row.participant_id for row in scope_members
            if row.role_id == registry.roles["relation"]), _MAX_WIRES, "scope wires")
    # Nested scopes also project their own relations (for example, Workshop
    # entry references). They are not necessarily editable canvas wires. Read
    # them as well so an incoming binding is never silently treated as compact,
    # but do not require unrelated scoped relations to join the global registry.
    # Raw scope membership must be included: endpoint drift may make the view
    # omit an incoming relation. Visibility still gates every editable wire.
    scoped_wires = tuple(sorted((visible_wires | set(scope_wires)) - registered_wires))
    if len(scoped_wires) > _MAX_WIRES:
        raise InvalidCell("Project revision scoped wire inventory exceeds its bound")
    matches = {name: [] for name in ports}
    for wire_root in (*wires, *scoped_wires):
        check()
        rows = read_relation(snapshot, wire_root, budget=256, retain_projection=False)
        targets = tuple(row for row in rows if row.role_id == registry.roles["target"])
        for name, port in ports.items():
            if not any(row.participant_id == port["id"] for row in targets):
                continue
            if wire_root not in registered_wires:
                raise InvalidCell("Project revision incoming scoped relation requires its editable authority path")
            sources = tuple(row for row in rows if row.role_id == registry.roles["source"])
            if len(targets) != 1 or len(sources) != 1 or wire_root not in visible_wires:
                raise InvalidCell("Project revision requires one admitted visible wire per connected port")
            matches[name].append((wire_root, sources[0], targets[0]))
        if wire_root not in registered_wires:
            _validate_scoped_reference(snapshot, registry, wire_root, rows, visible_roots, check,
                                       scope_root, scope_members)
    if any(len(rows) > 1 for rows in matches.values()):
        raise InvalidCell("Project revision port has multiple incoming wires")
    return matches


def work_custody_snapshot(snapshot, registry, work_root):
    """Lifecycle and custody facts one founder requirements revision is bound to.

    The same value is recorded before staging, rechecked immediately before the
    binding commit, and compared again before undo or redo compensates it.
    """
    from . import universal_application as app

    machine = app.read_instance_state_machine(snapshot, registry.assembly_protocol,
        registry.standard_library.state_machine_protocol, work_root)
    history = app.machine_history(snapshot, registry.standard_library.state_machine_protocol,
        machine.root_id)
    claimant = app._governed_work_claimant_binding(snapshot, registry, work_root)
    assignments = sorted(root for root in app._workshop_assignment_roots(snapshot, registry)
        if app._read_workshop_assignment(snapshot, registry, root).work_root == work_root)
    return {"state": app._text(snapshot, machine.current_state_root).casefold(),
        "state_root": machine.current_state_root,
        "history_head": history[-1].root_id if history else "none",
        "claimant": [part for part in claimant if type(part) is str] if claimant is not None else [],
        "assignments": assignments,
        "policy": app._governed_work_interface(snapshot, registry, work_root, "applicable-policy")["target"]}


def _validate_previous_wire(snapshot, registry, work_root, port, wire, visible):
    from . import universal_application as app

    _wire_root, source, target = wire
    registered = app._registered_canvas_interfaces(snapshot, registry,
        admitted_roots=frozenset((source.participant_id,)))
    if (len(registered) != 1 or registered[0].get("side") != "source"
            or registered[0].get("owner") != port["target"] or port["target"] not in visible):
        raise InvalidCell("Project revision previous wire differs from its visible value binding")
    owner, socket = app._canvas_endpoint(snapshot, registry, target, (work_root,))
    if owner != work_root or socket is None or target.participant_id != port["id"]:
        raise InvalidCell("Project revision previous wire targets another Work port")
    for interface in (source.participant_id, target.participant_id):
        if (app._is_domain_public_interface(snapshot, registry.assembly_protocol, interface)
                or app._is_derived_composition_interface(snapshot, registry, interface)):
            raise InvalidCell("Project revision special interfaces require their full rewire path")
    if not app._interface_contracts_compatible(registry.assembly_protocol,
            app._interface_contract_root(snapshot, registry.assembly_protocol, source.participant_id),
            app._interface_contract_root(snapshot, registry.assembly_protocol, target.participant_id)):
        raise InvalidCell("Project revision previous wire contracts are incompatible")


def inspect_project_bindings(snapshot, registry, work_root, context, *, fields=_FIELDS, material=None):
    """Read the admitted view's current ports before any draft staging writes.

    A never-bound port reads as unwired with a null value instead of failing,
    so a same-Work configuration can first-bind it. material selects the digest.
    """
    from . import universal_application as app

    fields = _selected_fields(fields)
    view, context = app._view_session_for_context(registry, context)
    visible, relations, _, trail = app._session_canvas_roots(snapshot, registry, view, include_trail=True)
    visible = _roots(visible, _MAX_VIEW_ROOTS, "visible roots")
    if work_root not in visible:
        raise InvalidCell("Project revision Work is outside the admitted view")
    app._require_application_authorization(snapshot, registry, "read", work_root,
                                          authentication_context=context)
    ports = {name: app._governed_work_interface(snapshot, registry, work_root, name) for name in fields}
    for port in ports.values():
        if (port.get("mode") != "connection" or type(port.get("target_incidence")) is not str
                or type(port.get("id")) is not str):
            raise InvalidCell("Project revision port has no exact connection binding")
        current = snapshot.cells.get(port["target_incidence"])
        if current is None or current.link1 != port["target"]:
            raise InvalidCell("Project revision port binding drifted")
    wires = _incoming_wires(snapshot, registry, ports, relations, lambda: None, visible, trail[-1])
    for name, rows in wires.items():
        for wire in rows:
            _validate_previous_wire(snapshot, registry, work_root, ports[name], wire, visible)
    unwired = {name: _is_unwired(snapshot.cells.get(port["target"])) for name, port in ports.items()}
    values = {name: None if unwired[name] else read_value_graph(snapshot, registry.value_graph_protocol, port["target"])
              for name, port in ports.items()}
    title = app._governed_work_interface(snapshot, registry, work_root, "title").get("value")
    description = app._governed_work_interface(snapshot, registry, work_root, "description").get("value")
    request, digest = _material(fields, values, title=title, description=description, mode=material)
    return {"revision": snapshot.revision, "work": work_root, "view_root": view.root_id,
        "scope_root": trail[-1], "visible_roots": visible, "visible_relation_roots": tuple(relations),
        "targets": {name: port["target"] for name, port in ports.items()},
        "interfaces": {name: port["id"] for name, port in ports.items()},
        "bindings": {name: port["target_incidence"] for name, port in ports.items()},
        "wires": {name: tuple({"root": row[0], "source_incidence": row[1].incidence_id,
            "source_interface": row[1].participant_id, "target_interface": row[2].participant_id}
            for row in rows) for name, rows in wires.items()},
        "needs_exposure": {name: bool(rows) for name, rows in wires.items()},
        **values, "unwired": unwired, "request": request, "input_digest": digest}


def prepare_project_revision_bindings(
    snapshot, registry, *, work_root, revised_roots, source_interfaces,
    visible_roots, visible_relation_roots, expected_revision, check_budget=None, scope_root=None,
    fields=_FIELDS, first_bindings=(), material=None,
):
    """Replace the selected Work ports and each corresponding visible source endpoint.

    first_bindings names selected ports whose current target is the unwired
    Cell; only those may bind without a previous value. material selects the
    digest mode exactly as inspect_project_bindings does.

    Visibility tuples must come from the caller's current admitted view at
    expected_revision. scope_root is that view's admitted scope; its raw relation
    inventory also guards bindings omitted by projection. Omitting scope_root
    supports historical global-only patch reconstruction, not live admission.
    Revised values are already registered; wired revisions
    are also exposed through existing APIs. source_interfaces maps wired fields to
    their actual exposed source interfaces; compact fields need no interface.
    Title, description, priority, Plan, values, result records and wires' target
    endpoints are preserved. A later task-text revision requires a separate
    explicit Plan revision path. fields is the established inputs+requirements
    pair, or requirements alone for a founder gate correction; an unselected
    port and its wires are not touched.

    Domain public sockets and derived composition boundaries require additional
    incidence ownership changes and are deliberately refused here.
    """
    from . import universal_application as app

    if check_budget is not None and not callable(check_budget):
        raise InvalidCell("Project revision budget check is invalid")

    def check():
        if check_budget is not None:
            check_budget()

    check()
    fields = _selected_fields(fields)
    if (type(first_bindings) is not tuple or len(set(first_bindings)) != len(first_bindings)
            or any(name not in fields for name in first_bindings)):
        raise InvalidCell("Project revision first bindings are invalid")
    if type(expected_revision) is not int or expected_revision != snapshot.revision:
        raise InvalidCell("Project revision graph changed")
    if type(work_root) is not str or not work_root:
        raise InvalidCell("Project revision Work identity is invalid")
    if (not isinstance(revised_roots, Mapping) or set(revised_roots) != set(fields)
            or any(type(revised_roots[name]) is not str or not revised_roots[name] for name in fields)
            or len(set(revised_roots.values())) != len(fields)):
        raise InvalidCell("Project revision requires distinct inputs and requirements roots")
    if (not isinstance(source_interfaces, Mapping) or set(source_interfaces) - set(fields)
            or any(type(root) is not str or not root for root in source_interfaces.values())):
        raise InvalidCell("Project revision source interfaces are invalid")
    visible = _roots(visible_roots, _MAX_VIEW_ROOTS, "visible roots")
    if work_root not in visible:
        raise InvalidCell("Project revision Work is outside the admitted view")

    ports = {name: app._governed_work_interface(snapshot, registry, work_root, name) for name in fields}
    replacements, previous, required, revised_values = {}, {}, [], {}
    for name, port in ports.items():
        check()
        if (port.get("mode") != "connection" or type(port.get("id")) is not str
                or type(port.get("target_incidence")) is not str):
            raise InvalidCell("Project revision port has no exact connection binding")
        if app._is_derived_composition_interface(snapshot, registry, port["id"]):
            raise InvalidCell("Project revision cannot bypass a derived boundary")
        current = snapshot.cells.get(port["target_incidence"])
        if current is None or current.link1 != port["target"]:
            raise InvalidCell("Project revision port binding drifted")
        previous[name] = current.link1
        if revised_roots[name] == current.link1:
            raise InvalidCell("Project revision requires new immutable value roots")
        if name in first_bindings:
            if not _is_unwired(snapshot.cells.get(current.link1)):
                raise InvalidCell("Project revision first binding requires an unwired Work port")
        else:
            read_value_graph(snapshot, registry.value_graph_protocol, current.link1)
        revised_values[name] = read_value_graph(snapshot, registry.value_graph_protocol, revised_roots[name])
        if current.id in replacements:
            raise InvalidCell("Project revision ports share a binding incidence")
        replacements[current.id] = Cell(current.id, current.link0, revised_roots[name], current.atom)
        required.append(RevisionAuthorization("catalog.configure", work_root, port["id"]))
    if set(previous.values()) & set(revised_roots.values()):
        raise InvalidCell("Project revision cannot reuse another previous value root")

    # Check the registered canvas inventory as well as the caller's view: an
    # invisible incoming wire cannot silently be mistaken for a compact port.
    matches = _incoming_wires(snapshot, registry, ports, visible_relation_roots, check, visible, scope_root)
    title = app._governed_work_interface(snapshot, registry, work_root, "title").get("value")
    description = app._governed_work_interface(snapshot, registry, work_root, "description").get("value")
    _request, digest = _material(fields, revised_values, title=title, description=description, mode=material)

    changed_wires = []
    for name, connected in matches.items():
        check()
        if len(connected) > 1:
            raise InvalidCell("Project revision port has multiple incoming wires")
        if not connected:
            continue
        wire_root, source, target = connected[0]
        new_interface = source_interfaces.get(name)
        if new_interface is None:
            raise InvalidCell("Project revision wired draft has no declared source interface")
        registered = app._registered_canvas_interfaces(snapshot, registry,
            admitted_roots=frozenset((source.participant_id, new_interface)))
        sockets = {row["id"]: row for row in registered}
        old_socket, new_socket = sockets.get(source.participant_id), sockets.get(new_interface)
        if (old_socket is None or new_socket is None
                or old_socket.get("side") != "source" or new_socket.get("side") != "source"
                or old_socket.get("owner") != previous[name]
                or new_socket.get("owner") != revised_roots[name]
                or previous[name] not in visible or revised_roots[name] not in visible):
            raise InvalidCell("Project revision source does not match its visible value binding")
        for interface in (source.participant_id, new_interface, target.participant_id):
            if (app._is_domain_public_interface(snapshot, registry.assembly_protocol, interface)
                    or app._is_derived_composition_interface(snapshot, registry, interface)):
                raise InvalidCell("Project revision special interfaces require their full rewire path")
        target_owner, target_socket = app._canvas_endpoint(snapshot, registry, target, (work_root,))
        if target_owner != work_root or target_socket is None:
            raise InvalidCell("Project revision wire target is not the declared Work interface")
        target_contract = app._interface_contract_root(snapshot, registry.assembly_protocol, target.participant_id)
        for source_interface in (source.participant_id, new_interface):
            if not app._interface_contracts_compatible(registry.assembly_protocol,
                    app._interface_contract_root(snapshot, registry.assembly_protocol, source_interface), target_contract):
                raise InvalidCell("Project revision source and target contracts are incompatible")
        current = snapshot.cells[source.incidence_id]
        if current.link0 != registry.roles["source"] or current.link1 != source.participant_id:
            raise InvalidCell("Project revision wire source incidence drifted")
        if current.id in replacements:
            raise InvalidCell("Project revision wire and binding incidences overlap")
        replacements[current.id] = Cell(current.id, current.link0, new_interface, current.atom)
        required.append(RevisionAuthorization("catalog.connect", current.id, new_interface))
        changed_wires.append(wire_root)
    check()
    return PreparedProjectRevisionBindings(snapshot.revision, work_root,
        tuple((name, previous[name]) for name in fields),
        tuple((name, revised_roots[name]) for name in fields),
        tuple(changed_wires), tuple(required), (), tuple(replacements.values()), digest)


__all__ = ["RevisionAuthorization", "PreparedProjectRevisionBindings",
           "inspect_project_bindings", "prepare_project_revision_bindings"]
