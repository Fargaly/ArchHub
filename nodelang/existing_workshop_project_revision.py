"""Admitted draft staging and one final same-Work binding transaction.

Draft exposure uses the existing graph APIs. Until the final tracked change,
the Work keeps both old inputs and their old wires. No model is invoked here.
"""
import hashlib
import math
import re
import time

from .cell_authorization import AuthorizationDenied
from .cell_protocols import read_relation
from .cell_value_graph import prepare_value_graphs, read_value_graph
from .universal_cell import InvalidCell
from .existing_workshop_project_execution import project_material_from_values
from .workshop_project_revision import inspect_project_bindings, prepare_project_revision_bindings


ROUTE = "/api/universal/workshop-native"


def pending_project_revisions(snapshot, registry, work):
    """Bounded indexed discovery, including unresolved drafts after restart/undo."""
    from types import MappingProxyType
    from .universal_cell import _LazyHeadCellMap, _OverlayCellMap, ids_with_prefix

    cells = snapshot.cells
    target = getattr(cells, "_head", cells)
    if isinstance(target, _LazyHeadCellMap):
        if len(target._overlay) > 8192:
            raise InvalidCell("Project revision overlay exceeds its discovery bound")
        indexed = True
    elif isinstance(cells, (dict, MappingProxyType, _OverlayCellMap)) and len(cells) <= 1048576:
        indexed = False
    else:
        raise InvalidCell("Project revision discovery requires an indexed snapshot")
    prefix = work + ":project-revision:"
    deadline, count, pending = time.monotonic() + 2, 0, []
    matches = 0
    for index, record_root in enumerate(ids_with_prefix(cells, prefix) if indexed else cells):
        # In-memory owners already hold these IDs; count every examined key
        # without allocating another graph/index. Durable large owners use SQL.
        if index >= (8192 if indexed else 1048576) or time.monotonic() > deadline:
            raise InvalidCell("Project revision discovery exceeded its bound")
        if not record_root.startswith(prefix):
            continue
        matches += 1
        if matches > 8192:
            raise InvalidCell("Project revision discovery exceeded its match bound")
        revision_id = record_root[len(prefix):]
        if re.fullmatch(r"[a-f0-9]{32}", revision_id) is None:
            continue
        count += 1
        if count > 64:
            raise InvalidCell("Project revision history exceeds its bound")
        record = read_value_graph(snapshot, registry.value_graph_protocol, record_root, max_depth=4)
        basic = {"work", "workshop", "scope", "owner", "view", "revision_id", "base_digest",
            "input_digest", "revised_roots", "previous_roots"}
        provenance = ({"previous_receipt"} if type(record) is dict and "previous_receipt" in record
            else {"previous_local_resolution", "previous_result"})
        if (type(record) is not dict or set(record) != basic | provenance
                or record["work"] != work or record["revision_id"] != revision_id
                or any(type(record[key]) is not str or not record[key]
                    for key in (basic | provenance) - {"revised_roots", "previous_roots"})
                or any(re.fullmatch(r"[a-f0-9]{64}", record[key]) is None for key in ("base_digest", "input_digest"))
                or record["revised_roots"] != {key:record_root+":"+key for key in ("inputs", "requirements")}
                or type(record["previous_roots"]) is not dict or set(record["previous_roots"]) != {"inputs", "requirements"}
                or any(type(value) is not str or not value for value in record["previous_roots"].values())):
            raise InvalidCell("Project revision history is malformed")
        applied_root = record_root + ":applied"
        if applied_root in cells:
            expected = {key:value for key,value in record.items() if key != "previous_roots"}
            expected.update(state="applied", authorization_root=record_root+":authorization")
            if read_value_graph(snapshot, registry.value_graph_protocol, applied_root, max_depth=4) != expected:
                raise InvalidCell("Project revision completion evidence changed")
        else:
            pending.append(record)
    if time.monotonic() > deadline:
        raise InvalidCell("Project revision discovery exceeded its bound")
    return tuple(pending)


def _resume_project_value_interface(server, authentication_context, view_root, value_root, scope, check):
    """Finish only an already atomically exposed draft under normal admission."""
    from . import universal_application as app

    store, registry = server.universal_store, server.universal_registry
    snapshot = store.snapshot()
    view, context = app._view_session_for_context(registry, authentication_context)
    visible, _, _, trail = app._session_canvas_roots(snapshot, registry, view, include_trail=True)
    if value_root not in visible or trail[-1] != scope or view.root_id != view_root:
        raise AuthorizationDenied("Revision draft interface recovery is outside its original view")
    app._require_application_authorization(snapshot, registry, "edit", scope, authentication_context=context)
    relations = {}
    def members(root):
        if root not in relations:
            check()
            relations[root] = read_relation(snapshot, root, budget=100_000, retain_projection=False)
        return relations[root]
    for relation, role in {
            (registry.canvas_root, registry.roles["member"]),
            (registry.application_root, registry.roles["member"]),
            (registry.map.domains["brain"], registry.roles["member"]),
            (scope, registry.roles["member"]),
            (view.visibility_root, registry.roles["visible"])}:
        if sum(row.role_id == role and row.participant_id == value_root for row in members(relation)) != 1:
            raise InvalidCell("Revision draft exposure membership is incomplete or duplicated")
    property_roots = tuple(row.participant_id for row in members(scope) if row.role_id == registry.roles["property"])
    if len(property_roots) > 4096 or len(set(property_roots)) != len(property_roots):
        raise InvalidCell("Revision draft property inventory is ambiguous or exceeds its bound")
    properties = app._property_index(snapshot, registry, property_roots).get(value_root, ())
    rows = app._rows_by_label(snapshot, properties)
    if len(properties) != 4 or set(rows) != {"title", "position_x", "position_y", "value_graph"}:
        raise InvalidCell("Revision draft exposure has incomplete or duplicate properties")
    if (not app._text(snapshot, rows["title"].value_root).strip()
            or app._text(snapshot, rows["value_graph"].value_root) != registry.value_graph_protocol.root_id
            or any(not math.isfinite(float(app._text(snapshot, rows[key].value_root)))
                   for key in ("position_x", "position_y"))):
        raise InvalidCell("Revision draft exposure properties changed incompatibly")
    for row in properties:
        for relation, role in ((registry.canvas_root, registry.roles["property"]),
                               (view.properties_lens_root, registry.roles["scope"])):
            if sum(item.role_id == role and item.participant_id == row.relation_root
                   for item in members(relation)) != 1:
                raise InvalidCell("Revision draft property membership is incomplete or duplicated")
    check()
    interfaces, _ = app.create_universal_interfaces(store, registry,
        ((value_root, "value", "app:canvas-interface:presentation:source", registry.assembly_protocol.root_id),),
        mutation_route=ROUTE, authentication_context=context)
    return interfaces[0]


def revise_project_values(server, binding, *, root, scope, work, revision_id,
        base_digest, inputs, requirements, previous_receipt=None, previous_local_resolution=None,
        previous_result=None, before_binding_commit=None):
    """Caller holds native action, owner and live-context locks; commits use CAS."""
    from . import universal_application as app

    if (type(revision_id) is not str or re.fullmatch(r"[a-f0-9]{32}", revision_id) is None
            or type(base_digest) is not str or re.fullmatch(r"[a-f0-9]{64}", base_digest) is None):
        raise InvalidCell("Project revision identity is invalid")
    if previous_receipt is not None:
        if (type(previous_receipt) is not str or not previous_receipt
                or previous_local_resolution is not None or previous_result is not None):
            raise InvalidCell("Choose exactly one revision provenance")
        provenance = {"previous_receipt":previous_receipt}
    else:
        if (type(previous_local_resolution) is not str or not previous_local_resolution
                or type(previous_result) is not str or not previous_result):
            raise InvalidCell("Local revision requires its exact result and resolution")
        provenance = {"previous_local_resolution":previous_local_resolution,
            "previous_result":previous_result}
    store, registry = server.universal_store, server.universal_registry
    view, context = app._view_session_for_context(registry, binding.context)
    deadline = time.monotonic() + 10

    def check():
        if time.monotonic() > deadline:
            raise InvalidCell("Project revision exceeded its bounded preparation time; read its saved state")
        if not server._model_execution_idle.is_set() or server._project_work_pending is not None:
            raise InvalidCell("An execution is still settling; the Work cannot be revised")
        server.universal_registry.authorization.broker.resolve(context)

    def commit(snapshot, *, create=(), replace=(), extra_scopes=()):
        check()
        return app._commit_universal_user_change(store, registry, view, context, snapshot,
            route=ROUTE, command_name="catalog.configure", authorization_scope_root=work,
            additional_authorization_scope_roots=extra_scopes, create=create, replace=replace)

    check()
    snapshot = store.snapshot()
    current = inspect_project_bindings(snapshot, registry, work, context)
    if current["scope_root"] != scope or current["view_root"] != binding.view_root:
        raise AuthorizationDenied("Project revision moved outside the selected Workshop view")
    for interface in current["interfaces"].values():
        app._authorize(snapshot, registry, "catalog.configure", object_root=work,
            interface_root=interface, authentication_context=context)
    title = app._governed_work_interface(snapshot, registry, work, "title")["value"]
    description = app._governed_work_interface(snapshot, registry, work, "description")["value"]
    _, raw = project_material_from_values(inputs, requirements, title=title, description=description)
    next_digest = hashlib.sha256(raw).hexdigest()
    record_root = work + ":project-revision:" + revision_id
    revised_roots = {name: record_root + ":" + name for name in ("inputs", "requirements")}
    applied_root = record_root + ":applied"
    identity = {"work":work, "workshop":root, "scope":scope, "owner":binding.subject_root,
        "view":binding.view_root, "revision_id":revision_id, "base_digest":base_digest,
        "input_digest":next_digest, **provenance,
        "revised_roots":revised_roots}
    authorization_root = record_root + ":authorization"
    applied_value = {**identity, "state":"applied", "authorization_root":authorization_root}
    if record_root in snapshot.cells:
        record = read_value_graph(snapshot, registry.value_graph_protocol, record_root)
        if type(record) is not dict or {key:record.get(key) for key in identity} != identity:
            raise InvalidCell("Project revision identity was already used for different inputs")
        if applied_root in snapshot.cells:
            if read_value_graph(snapshot, registry.value_graph_protocol, applied_root) != applied_value:
                raise InvalidCell("Project revision completion evidence changed")
            return {"revision_id":revision_id, "record":record_root, "applied":True,
                "input_digest":next_digest, "current_input_digest":current["input_digest"],
                "revision":snapshot.revision, "reused":True}
    else:
        record = {**identity, "previous_roots":current["targets"]}
    if current["input_digest"] != base_digest or current["targets"] != record["previous_roots"]:
        raise InvalidCell("This Work changed since the editor opened; reload its current inputs")
    if next_digest == base_digest:
        raise InvalidCell("The revised Work has no changed input")
    if inputs["artifact_name"] == current["inputs"]["artifact_name"]:
        raise InvalidCell("The revised attempt requires a new artifact name")
    if record_root not in snapshot.cells:
        prepared = prepare_value_graphs(snapshot, registry.value_graph_protocol,
            {revised_roots["inputs"]:inputs, revised_roots["requirements"]:requirements, record_root:record})
        commit(snapshot, create=prepared.create, replace=prepared.replace)
    else:
        for name, value in (("inputs", inputs), ("requirements", requirements)):
            if read_value_graph(snapshot, registry.value_graph_protocol, revised_roots[name]) != value:
                raise InvalidCell("The saved project revision draft changed")

    # Expose only wired replacement values. Existing compact references remain
    # compact. Draft exposure does not switch either executable Work input.
    def precommit(_snapshot):
        if before_binding_commit is not None:
            before_binding_commit()

    revision = _stage_and_bind(server, subject_root=binding.subject_root, view=view, context=context, check=check, commit=commit,
        work=work, title=title, fields=("inputs", "requirements"), current=current, record=record,
        record_root=record_root, revised_roots=revised_roots, applied_value=applied_value,
        authorization_root=authorization_root, base_digest=base_digest, next_digest=next_digest,
        evidence_kind="workshop-project-revision-authorization-v1", evidence_extra={},
        precommit=precommit)
    return {"revision_id":revision_id, "record":record_root, "applied":True,
        "input_digest":next_digest, "current_input_digest":next_digest,
        "revision":revision, "reused":False}


def _stage_and_bind(server, *, subject_root, view, context, check, commit, work, title, fields,
        current, record, record_root, revised_roots, applied_value, authorization_root,
        base_digest, next_digest, evidence_kind, evidence_extra, precommit, first_bindings=(), material=None):
    """Expose wired drafts, record authorization evidence, then bind once on the same Work."""
    from . import universal_application as app

    store, registry = server.universal_store, server.universal_registry
    applied_root = record_root + ":applied"
    source_interfaces = {}
    snapshot = store.snapshot()
    visible, _, property_roots, _ = app._session_canvas_roots(snapshot, registry, view, include_trail=True)
    properties = app._property_index(snapshot, registry, property_roots)
    positions = {}
    for node in visible:
        rows = app._rows_by_label(snapshot, properties.get(node, ()))
        if "position_x" in rows and "position_y" in rows:
            try:
                point = tuple(float(app._text(snapshot, rows[key].value_root)) for key in ("position_x", "position_y"))
            except (ValueError, TypeError):
                continue
            if all(math.isfinite(value) for value in point):
                positions[node] = point
    for name in fields:
        if not current["needs_exposure"][name]:
            continue
        check()
        snapshot = store.snapshot()
        interfaces = tuple(item for item in app._registered_canvas_interfaces(snapshot, registry)
            if item["owner"] == revised_roots[name] and item["side"] == "source")
        if len(interfaces) > 1:
            raise InvalidCell("The revision draft has ambiguous source interfaces")
        if interfaces:
            source_interfaces[name] = interfaces[0]["id"]
            continue
        visible, _, _ = app._session_canvas_roots(snapshot, registry, view)
        if revised_roots[name] in visible:
            source_interfaces[name] = _resume_project_value_interface(
                server, context, view.root_id, revised_roots[name], current["scope_root"], check)
            continue
        origin_x, origin_y = positions.get(current["targets"][name], positions.get(work, (0.0, 0.0)))
        placement = None
        for offset in range(1, 129):
            point = (origin_x - 400.0, origin_y + offset * 280.0)
            if all(abs(point[0] - x) >= 340 or abs(point[1] - y) >= 260 for x, y in positions.values()):
                placement = point
                break
        if placement is None:
            raise InvalidCell("No clear position was found for the revision draft; arrange the canvas first")
        exposed, _ = app._expose_universal_value_graphs(store, registry,
            ((revised_roots[name], title + " / Revised " + name, *placement),),
            mutation_route=ROUTE, authentication_context=context)
        source_interfaces[name] = exposed[revised_roots[name]]
        positions[revised_roots[name]] = placement

    def prepare(snapshot, observed):
        prepared = prepare_project_revision_bindings(snapshot, registry, work_root=work,
            revised_roots=revised_roots, source_interfaces=source_interfaces,
            visible_roots=observed["visible_roots"], visible_relation_roots=observed["visible_relation_roots"],
            expected_revision=snapshot.revision, check_budget=check, scope_root=observed["scope_root"],
            fields=fields, first_bindings=first_bindings, material=material)
        if dict(prepared.previous_roots) != record["previous_roots"]:
            raise InvalidCell("Work bindings changed while staging the revision")
        if prepared.input_digest != next_digest:
            raise InvalidCell("Staged Work values differ from the reviewed revision")
        return prepared

    snapshot = store.snapshot()
    observed = inspect_project_bindings(snapshot, registry, work, context, fields=fields, material=material)
    if observed["targets"] != record["previous_roots"] or observed["input_digest"] != base_digest:
        raise InvalidCell("Work bindings changed while staging the revision")
    prepared = prepare(snapshot, observed)
    for requirement in prepared.authorizations:
        app._authorize(snapshot, registry, requirement.command_name,
            object_root=requirement.object_root, interface_root=requirement.interface_root,
            authentication_context=context)
    obligations = {(row.command_name, row.object_root, row.interface_root) for row in prepared.authorizations}
    for wires in current["wires"].values():
        for wire in wires:
            obligations.add(("catalog.connect", wire["source_incidence"], wire["source_interface"]))
    authority_value = {"kind":evidence_kind, "work":work, "view":view.root_id,
        "owner":subject_root, **evidence_extra,
        "authorizations":[{"command_name":command, "object_root":object_root, "interface_root":interface}
            for command, object_root, interface in sorted(obligations)]}
    for obligation in authority_value["authorizations"]:
        app._authorize(snapshot, registry, obligation["command_name"],
            object_root=obligation["object_root"], interface_root=obligation["interface_root"],
            authentication_context=context)
    # Evidence predates the compensated binding transaction, so undoing its
    # marker cannot erase the permissions redo needs to re-evaluate.
    if authorization_root in snapshot.cells:
        if read_value_graph(snapshot, registry.value_graph_protocol, authorization_root) != authority_value:
            raise InvalidCell("Saved revision compensation authority changed")
    else:
        authority_patch = prepare_value_graphs(snapshot, registry.value_graph_protocol,
            {authorization_root:authority_value})
        commit(snapshot, create=authority_patch.create, replace=authority_patch.replace)
    snapshot = store.snapshot()
    prepared = prepare(snapshot, observed)
    marker = prepare_value_graphs(snapshot, registry.value_graph_protocol, {applied_root:applied_value})
    precommit(snapshot)
    return commit(snapshot, create=(*prepared.create, *marker.create),
        replace=(*prepared.replace, *marker.replace))


_GATE_SPEC_KEYS = frozenset(("path", "selector", "args", "timeout_seconds"))


def completion_court_workspace_root(registry):
    """Return the exact workspace root of the admitted Work completion court.

    Edit-time and undo/redo gate validation must resolve paths and junctions
    against the same root the independent court will use; fail closed otherwise.
    """
    from .artifact_verification_court import ArtifactVerificationCourt

    broker = registry.attestation_broker
    with broker._lock:
        admitted = broker._courts.get(registry.work_completion_court_root)
    court = getattr(getattr(admitted, "runner", None), "__self__", None)
    if not isinstance(court, ArtifactVerificationCourt):
        raise InvalidCell("The Work completion court workspace is unavailable; the gate cannot be validated")
    return court.workspace_root


def validate_requirements_gate(snapshot, registry, work, gate, workspace_root, context):
    """Lexically admit one single-path pytest gate that the independent court can run.

    A test the claimant has not written yet is admitted; the completion court
    still fails a missing target. Nothing is executed here. context is None only
    when undo/redo compensation revalidates a restored gate; that caller
    re-authorizes every change obligation itself.
    """
    from . import universal_application as app
    from .artifact_verification_court import ArtifactVerificationCourt, _PYTEST_FLAGS

    if (type(gate) is not dict or set(gate) != {"kind", "spec"} or gate["kind"] != "pytest"
            or type(gate["spec"]) is not dict):
        raise InvalidCell("A founder gate correction admits exactly one pytest gate")
    spec = gate["spec"]
    if set(spec) - _GATE_SPEC_KEYS or "path" not in spec:
        raise InvalidCell("The gate needs a path; only selector, args and timeout_seconds may accompany it")
    if "selector" in spec and spec["selector"] != spec["path"]:
        raise InvalidCell("A gate selector must equal its path")
    cde_root = app._governed_work_interface_target(snapshot, registry, work, "cde-container")
    if context is not None:
        app._require_application_authorization(snapshot, registry, "read", cde_root, authentication_context=context)
    court = ArtifactVerificationCourt(workspace_root)
    try:
        scope_roots = court._scope_roots(read_value_graph(snapshot, registry.value_graph_protocol, cde_root))
        court._target(spec["path"], scope_roots, selector=True)
        args = spec.get("args", [])
        if type(args) is not list or len(args) > 8 or any(
                type(arg) is not str or (arg not in _PYTEST_FLAGS
                    and re.fullmatch(r"--maxfail=[1-9][0-9]?", arg) is None) for arg in args):
            raise ValueError("pytest arguments are outside the court allowlist")
        timeout = spec.get("timeout_seconds", 300)
        if type(timeout) not in (int, float) or not 1 <= float(timeout) <= 600:
            raise ValueError("pytest timeout is outside the court bound")
    except (OSError, ValueError) as exc:
        raise InvalidCell(str(exc)) from exc


def revise_work_requirements(server, binding, *, root, scope, work, revision_id, expected_revision,
        expected_target, expected_digest, gate, workspace_root, before_binding_commit=None):
    """Replace only an OPEN, unclaimed Work's acceptance gate on the same Work identity.

    Caller holds the native action lock, the owner mutation lock and a live
    founder browser context. Every other requirement key keeps its content.
    expected_revision is the graph revision the editor read; a new correction
    is refused before any staging when the graph moved since that read, so a
    read -> claim -> release -> save sequence or a changed CDE cannot slip in.
    """
    from . import universal_application as app
    from .workshop_project_revision import requirements_digest, work_custody_snapshot

    if (type(revision_id) is not str or re.fullmatch(r"[a-f0-9]{32}", revision_id) is None
            or type(expected_revision) is not int or expected_revision < 0
            or type(expected_digest) is not str or re.fullmatch(r"[a-f0-9]{64}", expected_digest) is None
            or type(expected_target) is not str or not expected_target):
        raise InvalidCell("Requirements revision identity is invalid")
    fields = ("requirements",)
    store, registry = server.universal_store, server.universal_registry
    view, context = app._view_session_for_context(registry, binding.context)
    deadline = time.monotonic() + 10

    def check():
        if time.monotonic() > deadline:
            raise InvalidCell("Requirements revision exceeded its bounded preparation time; read its saved state")
        if not server._model_execution_idle.is_set() or server._project_work_pending is not None:
            raise InvalidCell("An execution is still settling; the Work cannot be revised")
        server.universal_registry.authorization.broker.resolve(context)

    def commit(snapshot, *, create=(), replace=()):
        check()
        return app._commit_universal_user_change(store, registry, view, context, snapshot,
            route=ROUTE, command_name="catalog.configure", authorization_scope_root=work,
            create=create, replace=replace)

    check()
    snapshot = store.snapshot()
    current = inspect_project_bindings(snapshot, registry, work, context, fields=fields)
    if current["scope_root"] != scope or current["view_root"] != binding.view_root:
        raise AuthorizationDenied("Requirements revision moved outside the selected Workshop view")
    app._authorize(snapshot, registry, "catalog.configure", object_root=work,
        interface_root=current["interfaces"]["requirements"], authentication_context=context)
    live_custody = work_custody_snapshot(snapshot, registry, work)
    record_root = work + ":requirements-revision:" + revision_id
    revised_roots = {"requirements": record_root + ":data:requirements"}
    applied_root = record_root + ":applied"
    authorization_root = record_root + ":authorization"
    saved = None
    if record_root in snapshot.cells:
        saved = read_value_graph(snapshot, registry.value_graph_protocol, record_root)
        if (type(saved) is not dict or saved.get("work") != work or saved.get("revision_id") != revision_id
                or saved.get("owner") != binding.subject_root or saved.get("view") != binding.view_root
                or saved.get("workshop") != root or saved.get("scope") != scope
                or saved.get("base_digest") != expected_digest or saved.get("gate") != gate
                or saved.get("revised_roots") != revised_roots
                or type(saved.get("previous_roots")) is not dict
                or saved["previous_roots"].get("requirements") != expected_target
                or saved.get("read_revision") != expected_revision):
            raise InvalidCell("Requirements revision identity was already used for a different correction")
        identity = {key: value for key, value in saved.items() if key != "previous_roots"}
        applied_value = {**identity, "state":"applied", "authorization_root":authorization_root}
        if applied_root in snapshot.cells:
            if read_value_graph(snapshot, registry.value_graph_protocol, applied_root) != applied_value:
                raise InvalidCell("Requirements revision completion evidence changed")
            return {"revision_id":revision_id, "record":record_root, "applied":True,
                "input_digest":saved["input_digest"], "current_input_digest":current["input_digest"],
                "target":current["targets"]["requirements"], "revision":snapshot.revision, "reused":True}
    # A new correction is admitted only against the exact graph the editor read.
    # A saved but unapplied draft was staged at that revision and is bound to
    # its recorded read revision and custody instead.
    if saved is None and snapshot.revision != expected_revision:
        raise InvalidCell("This Work changed since the editor opened; reload its current requirements")
    custody = saved["custody"] if saved is not None else live_custody
    if type(custody) is not dict or custody.get("state") != "open" or custody.get("claimant"):
        raise InvalidCell("Only OPEN, unclaimed Work accepts a founder gate correction")
    if live_custody != custody:
        raise InvalidCell("Work lifecycle or custody changed since this correction was saved")
    if current["targets"]["requirements"] != expected_target or current["input_digest"] != expected_digest:
        raise InvalidCell("This Work's requirements changed since the editor opened; reload them")
    requirements = current["requirements"]
    # Resolve against the admitted completion court's own workspace, not a caller copy.
    validate_requirements_gate(snapshot, registry, work, gate, completion_court_workspace_root(registry), context)
    if requirements.get("gate") == gate:
        raise InvalidCell("The corrected gate is unchanged")
    revised = {**requirements, "gate":gate}
    next_digest = requirements_digest(revised)
    if saved is None:
        identity = {"work":work, "workshop":root, "scope":scope, "owner":binding.subject_root,
            "view":binding.view_root, "revision_id":revision_id, "base_digest":expected_digest,
            "read_revision":expected_revision,
            "input_digest":next_digest, "gate":gate, "custody":custody, "revised_roots":revised_roots}
        record = {**identity, "previous_roots":current["targets"]}
        applied_value = {**identity, "state":"applied", "authorization_root":authorization_root}
        prepared = prepare_value_graphs(snapshot, registry.value_graph_protocol,
            {revised_roots["requirements"]:revised, record_root:record})
        commit(snapshot, create=prepared.create, replace=prepared.replace)
    else:
        record = saved
        if (record.get("input_digest") != next_digest or record.get("previous_roots") != current["targets"]
                or read_value_graph(snapshot, registry.value_graph_protocol, revised_roots["requirements"]) != revised):
            raise InvalidCell("The saved requirements draft changed")
    title = app._governed_work_interface(snapshot, registry, work, "title")["value"]

    def precommit(final):
        if work_custody_snapshot(final, registry, work) != custody:
            raise InvalidCell("Work lifecycle or custody changed before the correction could bind")
        if before_binding_commit is not None:
            before_binding_commit()

    revision = _stage_and_bind(server, subject_root=binding.subject_root, view=view, context=context, check=check, commit=commit,
        work=work, title=title, fields=fields, current=current, record=record, record_root=record_root,
        revised_roots=revised_roots, applied_value=applied_value, authorization_root=authorization_root,
        base_digest=expected_digest, next_digest=next_digest,
        evidence_kind="workshop-requirements-revision-authorization-v1",
        evidence_extra={"custody":custody}, precommit=precommit)
    return {"revision_id":revision_id, "record":record_root, "applied":True,
        "input_digest":next_digest, "current_input_digest":next_digest,
        "target":revised_roots["requirements"], "revision":revision, "reused":False}


def read_work_requirements(server, binding, *, scope, work):
    """Founder editor read: exact requirements, target, digest, custody and any saved draft."""
    from . import universal_application as app
    from .workshop_project_revision import work_custody_snapshot

    store, registry = server.universal_store, server.universal_registry
    _view, context = app._view_session_for_context(registry, binding.context)
    snapshot = store.snapshot()
    current = inspect_project_bindings(snapshot, registry, work, context, fields=("requirements",))
    if current["scope_root"] != scope or current["view_root"] != binding.view_root:
        raise AuthorizationDenied("Requirements read moved outside the selected Workshop view")
    custody = work_custody_snapshot(snapshot, registry, work)
    return {"requirements":current["requirements"], "target":current["targets"]["requirements"],
        "digest":current["input_digest"], "state":custody["state"],
        "editable":custody["state"] == "open" and not custody["claimant"],
        "wired":current["needs_exposure"]["requirements"], "revision":snapshot.revision}


_CONFIGURATION_PURPOSES = frozenset(("general", "artifact-publication"))
_RUNTIME_SESSION_PREFIX = "app:agent-session:runtime:"


def _work_publisher_sessions(snapshot, registry, work):
    """Every runtime Agent Session that ever claimed this Work, plus its current claimant.

    All bound runtime sessions share the founder subject, so reviewer
    independence is decided by exact session identity, never by subject.
    """
    from . import universal_application as app

    machine = app.read_instance_state_machine(snapshot, registry.assembly_protocol,
        registry.standard_library.state_machine_protocol, work)
    sessions = set()
    for event in app.machine_history(snapshot, registry.standard_library.state_machine_protocol, machine.root_id):
        if app._text(snapshot, event.event_root).casefold() == "claim":
            sessions.update(root for root in event.context_roots
                            if type(root) is str and root.startswith(_RUNTIME_SESSION_PREFIX))
    current = app._governed_work_claimant_binding(snapshot, registry, work)
    if current is not None:
        sessions.add(current[0])
    return sessions


def _validate_configured_gate(court, gate, scope_roots):
    """Lexically admit one court gate inside the configured CDE; nothing runs."""
    from .artifact_verification_court import _GATE_KINDS, _PYTEST_FLAGS

    if (type(gate) is not dict or set(gate) != {"kind", "spec"} or gate["kind"] not in _GATE_KINDS
            or type(gate["spec"]) is not dict):
        raise ValueError("A Work gate needs one admitted court kind and an object spec")
    spec = gate["spec"]
    if gate["kind"] == "pytest":
        if set(spec) - _GATE_SPEC_KEYS or "path" not in spec:
            raise ValueError("The pytest gate needs a path; only selector, args and timeout_seconds may accompany it")
        if "selector" in spec and spec["selector"] != spec["path"]:
            raise ValueError("A gate selector must equal its path")
        court._target(spec["path"], scope_roots, selector=True)
        args = spec.get("args", [])
        if type(args) is not list or len(args) > 8 or any(
                type(arg) is not str or (arg not in _PYTEST_FLAGS
                    and re.fullmatch(r"--maxfail=[1-9][0-9]?", arg) is None) for arg in args):
            raise ValueError("pytest arguments are outside the court allowlist")
        timeout = spec.get("timeout_seconds", 300)
        if type(timeout) not in (int, float) or not 1 <= float(timeout) <= 600:
            raise ValueError("pytest timeout is outside the court bound")
        return
    if "path" in spec:
        court._target(spec["path"], scope_roots)
    paths = spec.get("paths", [])
    if type(paths) is not list or len(paths) > 64:
        raise ValueError("Work gate paths are invalid")
    for raw in paths:
        court._target(raw, scope_roots)


def validate_work_configuration(snapshot, registry, work, *, purpose, current, proposed, workspace_root, context):
    """Validate the complete configuration that would result; nothing is written or run.

    General Works get object shapes, CDE confinement and any gate. Artifact
    publication additionally requires public-text inputs and 1 to 16 reviewers
    that are registered runtime Agent Sessions and never this Work's publisher.
    context is None when undo/redo compensation revalidates a restored state.
    """
    from .artifact_verification_court import ArtifactVerificationCourt
    from .cell_agent_body import list_agent_session_roots

    if purpose not in _CONFIGURATION_PURPOSES:
        raise InvalidCell("Work configuration purpose is invalid")
    if any(type(value) is not dict for value in proposed.values()):
        raise InvalidCell("A configured Work field must be a structured object")
    final = {**current, **proposed}
    court = ArtifactVerificationCourt(workspace_root)
    try:
        cde = final.get("cde-container")
        scope_roots = None
        if cde is not None:
            if type(cde) is not dict:
                raise ValueError("Work CDE container is not an object")
            scope_roots = court._scope_roots(cde)
        requirements = final.get("requirements")
        if requirements is not None and type(requirements) is not dict:
            raise ValueError("Work requirements are not an object")
        if requirements is not None and "gate" in requirements:
            if scope_roots is None:
                raise ValueError("A Work gate requires a configured CDE container")
            _validate_configured_gate(court, requirements["gate"], scope_roots)
    except (OSError, ValueError) as exc:
        raise InvalidCell(str(exc)) from exc
    if purpose != "artifact-publication":
        return
    inputs, requirements = final.get("inputs"), final.get("requirements")
    if type(inputs) is not dict or inputs.get("data_class") != "public-text":
        raise InvalidCell("Artifact publication requires public-text Work inputs")
    if type(requirements) is not dict or type(final.get("cde-container")) is not dict:
        raise InvalidCell("Artifact publication requires configured requirements and a CDE")
    reviewers = requirements.get("artifact_reviewers")
    if (type(reviewers) is not list or not 0 < len(reviewers) <= 16
            or any(type(root) is not str or not root or len(root) > 256 for root in reviewers)
            or len(set(reviewers)) != len(reviewers)):
        raise InvalidCell("Artifact publication requires 1 to 16 unique reviewer Agent Session roots")
    registered = set(list_agent_session_roots(snapshot, registry.agent_body.protocol))
    for reviewer in reviewers:
        if not reviewer.startswith(_RUNTIME_SESSION_PREFIX) or reviewer not in registered:
            raise InvalidCell("Artifact reviewer %s is not a registered runtime Agent Session" % reviewer)
    if set(reviewers) & _work_publisher_sessions(snapshot, registry, work):
        raise InvalidCell("An artifact reviewer has already claimed this Work and cannot review its publication")


def configure_work_interfaces(server, binding, *, root, scope, work, revision_id, expected_revision,
        purpose, fields, before_binding_commit=None):
    """Browser admission delegates to the same actual-context configuration core."""
    identity = server.universal_registry.authorization.broker.resolve(binding.context)
    if identity.subject_root != binding.subject_root:
        raise AuthorizationDenied("Work configuration subject differs from the admitted browser")
    return _configure_work_interfaces_for_context(server, binding.context,
        view_root=binding.view_root, root=root, scope=scope, work=work, revision_id=revision_id,
        expected_revision=expected_revision, purpose=purpose, fields=fields,
        before_binding_commit=before_binding_commit)


def stage_work_interfaces_for_context(server, authentication_context, *, proposing_actor,
        before_binding_commit, **arguments):
    """Save the same configuration draft without changing executable Work bindings.

    The native adapter supplies its resolved actor and revalidates that authenticated
    actor in before_binding_commit; caller-supplied request identities are not accepted.
    """
    if not isinstance(proposing_actor, str) or not proposing_actor or not callable(before_binding_commit):
        raise AuthorizationDenied("Work configuration draft requires authenticated actor admission")
    return _configure_work_interfaces_for_context(server, authentication_context,
        proposing_actor=proposing_actor, stage_only=True,
        before_binding_commit=before_binding_commit, **arguments)


def _configure_work_interfaces_for_context(server, authentication_context, *, view_root,
        root, scope, work, revision_id, expected_revision, purpose, fields, before_binding_commit=None,
        stage_only=False, proposing_actor=None):
    """First-bind or revise an OPEN, unclaimed Work's inputs, requirements and CDE on the same Work.

    fields maps a subset of inputs/requirements/cde-container to exactly
    {expected_target, expected_digest (null only for an unwired port), value}.
    Only the named fields change, and the complete result is validated first.
    """
    if authentication_context is None:
        raise AuthorizationDenied("Work configuration requires an explicit authenticated context")
    from . import universal_application as app
    from .workshop_project_revision import _CONFIGURABLE, requirements_digest, work_custody_snapshot

    if (type(revision_id) is not str or re.fullmatch(r"[a-f0-9]{32}", revision_id) is None
            or type(expected_revision) is not int or expected_revision < 0
            or type(purpose) is not str or purpose not in _CONFIGURATION_PURPOSES
            or type(fields) is not dict or not fields or set(fields) - set(_CONFIGURABLE)):
        raise InvalidCell("Work configuration identity is invalid")
    names = tuple(name for name in _CONFIGURABLE if name in fields)
    for name in names:
        entry = fields[name]
        if (type(entry) is not dict or set(entry) != {"expected_target", "expected_digest", "value"}
                or type(entry["expected_target"]) is not str or not entry["expected_target"]
                or not (entry["expected_digest"] is None or (type(entry["expected_digest"]) is str
                    and re.fullmatch(r"[a-f0-9]{64}", entry["expected_digest"]) is not None))):
            raise InvalidCell("Work configuration field %s is invalid" % name)
    store, registry = server.universal_store, server.universal_registry
    view, context = app._view_session_for_context(registry, authentication_context)
    subject_root = registry.authorization.broker.resolve(context).subject_root
    proposing_actor = proposing_actor or subject_root
    if stage_only:
        actor_session = app._runtime_agent_session(store.snapshot(), registry, proposing_actor)
        if proposing_actor == subject_root or actor_session.subject_root != subject_root:
            raise AuthorizationDenied("Work configuration proposer differs from its authenticated subject")
    deadline = time.monotonic() + 10

    def check():
        if time.monotonic() > deadline:
            raise InvalidCell("Work configuration exceeded its bounded preparation time; read its saved state")
        # Another Work's execution never blocks this one; this Work's own effects are refused
        # at admission and again against the final snapshot, under the caller's mutation lock.
        server.universal_registry.authorization.broker.resolve(context)

    def commit(snapshot, *, create=(), replace=()):
        check()
        return app._commit_universal_user_change(store, registry, view, context, snapshot,
            route=ROUTE, command_name="catalog.configure", authorization_scope_root=work,
            create=create, replace=replace)

    check()
    snapshot = store.snapshot()
    current = inspect_project_bindings(snapshot, registry, work, context, fields=names, material="values")
    if current["scope_root"] != scope or current["view_root"] != view_root:
        raise AuthorizationDenied("Work configuration moved outside the selected Workshop view")
    for name in names:
        app._authorize(snapshot, registry, "catalog.configure", object_root=work,
            interface_root=current["interfaces"][name], authentication_context=context)
    live_custody = work_custody_snapshot(snapshot, registry, work)
    record_root = work + ":work-configuration:" + revision_id
    revised_roots = {name: record_root + ":data:" + name for name in names}
    applied_root, authorization_root = record_root + ":applied", record_root + ":authorization"
    expected = {name: {"target": fields[name]["expected_target"], "digest": fields[name]["expected_digest"] or ""}
                for name in names}
    proposed = {name: fields[name]["value"] for name in names}
    first_bindings = tuple(name for name in names if current["unwired"][name])
    saved = None
    if record_root + ":discarded" in snapshot.cells:
        raise InvalidCell("This Work configuration draft was discarded")
    if record_root in snapshot.cells:
        saved = read_value_graph(snapshot, registry.value_graph_protocol, record_root)
        if stage_only and (type(saved) is not dict or saved.get("proposing_actor") != proposing_actor):
            raise AuthorizationDenied("Work configuration draft belongs to another actor")
        if (type(saved) is not dict or saved.get("work") != work or saved.get("revision_id") != revision_id
                or saved.get("owner") != subject_root or saved.get("view") != view_root
                or saved.get("workshop") != root or saved.get("scope") != scope
                or saved.get("purpose") != purpose or saved.get("expected") != expected
                or saved.get("revised_roots") != revised_roots
                or saved.get("read_revision") != expected_revision):
            raise InvalidCell("Work configuration identity was already used for a different configuration")
        # A successful replay must identify the same proposal, not merely the
        # same request ID and old bindings. Check before the applied return.
        try:
            same_values = (saved.get("input_digest") == requirements_digest(proposed)
                and all(read_value_graph(snapshot, registry.value_graph_protocol, revised_roots[name]) == proposed[name]
                        for name in names))
        except (TypeError, ValueError):
            same_values = False
        if not same_values:
            raise InvalidCell("Work configuration identity was already used for a different configuration")
        identity = {key: value for key, value in saved.items() if key != "previous_roots"}
        applied_value = {**identity, "state":"applied", "authorization_root":authorization_root}
        if applied_root in snapshot.cells:
            if read_value_graph(snapshot, registry.value_graph_protocol, applied_root) != applied_value:
                raise InvalidCell("Work configuration completion evidence changed")
            return {"revision_id":revision_id, "record":record_root, "applied":True, "staged":True,
                "input_digest":saved["input_digest"], "targets":revised_roots,
                "first_bindings":saved["first_bindings"], "purpose":purpose,
                "revision":snapshot.revision, "reused":True}
    _refuse_selected_work_execution(server, snapshot, registry, work)
    # A new configuration is admitted only against the exact graph the editor read.
    if saved is None and snapshot.revision != expected_revision:
        raise InvalidCell("This Work changed since the editor opened; reload its current configuration")
    custody = saved["custody"] if saved is not None else live_custody
    if type(custody) is not dict or custody.get("state") != "open" or custody.get("claimant"):
        raise InvalidCell("Only OPEN, unclaimed Work accepts a configuration change")
    if live_custody != custody:
        raise InvalidCell("Work lifecycle or custody changed since this configuration was saved")
    for name in names:
        digest = "" if current["unwired"][name] else requirements_digest(current[name])
        if current["targets"][name] != expected[name]["target"] or digest != expected[name]["digest"]:
            raise InvalidCell("This Work's %s changed since the editor opened; reload it" % name)
    baseline = inspect_project_bindings(snapshot, registry, work, context, fields=_CONFIGURABLE, material="values")
    validate_work_configuration(snapshot, registry, work, purpose=purpose,
        current={name: baseline[name] for name in _CONFIGURABLE}, proposed=proposed,
        workspace_root=completion_court_workspace_root(registry), context=context)
    if all(proposed[name] == current[name] for name in names):
        raise InvalidCell("The Work configuration is unchanged")
    base_digest = current["input_digest"]
    next_digest = requirements_digest({name: proposed[name] for name in names})
    if saved is None:
        if stage_only and sum(not draft["stale"] for draft in pending_work_configurations(
                snapshot, registry, work=work, scope=scope, view_root=view_root, subject_root=subject_root,
                current_fields={name: {"target":baseline["targets"][name],
                    "digest":None if baseline["unwired"][name] else requirements_digest(baseline[name])}
                    for name in _CONFIGURABLE})) >= 8:
            raise InvalidCell("This Work already has eight pending configuration drafts; review them first")
        identity = {"work":work, "workshop":root, "scope":scope, "owner":subject_root,
            "proposing_actor":proposing_actor,
            "view":view_root, "revision_id":revision_id, "purpose":purpose,
            "read_revision":expected_revision, "expected":expected, "base_digest":base_digest,
            "input_digest":next_digest, "fields":list(names), "first_bindings":list(first_bindings),
            "custody":custody, "revised_roots":revised_roots}
        record = {**identity, "previous_roots":current["targets"]}
        applied_value = {**identity, "state":"applied", "authorization_root":authorization_root}
        prepared = prepare_value_graphs(snapshot, registry.value_graph_protocol,
            {**{revised_roots[name]: proposed[name] for name in names}, record_root: record})
        if before_binding_commit is not None:
            before_binding_commit()
        commit(snapshot, create=prepared.create, replace=prepared.replace)
    else:
        record = saved
        if (record.get("input_digest") != next_digest or record.get("previous_roots") != current["targets"]
                or record.get("first_bindings") != list(first_bindings)
                or any(read_value_graph(snapshot, registry.value_graph_protocol, revised_roots[name]) != proposed[name]
                       for name in names)):
            raise InvalidCell("The saved Work configuration draft changed")
    if stage_only:
        if saved is not None:
            before_binding_commit()
        return {"revision_id":revision_id, "record":record_root, "applied":False, "staged":True,
            "input_digest":next_digest, "targets":current["targets"],
            "first_bindings":list(first_bindings), "purpose":purpose,
            "revision":store.revision, "reused":saved is not None}
    title = app._governed_work_interface(snapshot, registry, work, "title")["value"]

    def precommit(final):
        if work_custody_snapshot(final, registry, work) != custody:
            raise InvalidCell("Work lifecycle or custody changed before the configuration could bind")
        _refuse_selected_work_execution(server, final, registry, work)
        if before_binding_commit is not None:
            before_binding_commit()

    revision = _stage_and_bind(server, subject_root=subject_root, view=view, context=context, check=check, commit=commit,
        work=work, title=title, fields=names, current=current, record=record, record_root=record_root,
        revised_roots=revised_roots, applied_value=applied_value, authorization_root=authorization_root,
        base_digest=base_digest, next_digest=next_digest,
        evidence_kind="workshop-work-configuration-authorization-v1",
        evidence_extra={"custody":custody, "fields":list(names), "first_bindings":list(first_bindings),
                        "purpose":purpose},
        precommit=precommit, first_bindings=first_bindings, material="values")
    return {"revision_id":revision_id, "record":record_root, "applied":True, "input_digest":next_digest,
        "targets":revised_roots, "first_bindings":list(first_bindings), "purpose":purpose,
        "revision":revision, "reused":False}


def _refuse_selected_work_execution(server, snapshot, registry, work):
    """Refuse only execution effects bound to this Work; other Works' executions never block it.

    A released Work can still own an unsettled grant or a retained result, so
    OPEN custody alone does not prove the Work has no live effect.
    """
    from .cell_connector_execution import (read_connector_delegation, read_connector_execution_grant,
        read_connector_execution_receipt)
    from .cell_model_execution import read_model_delegation, read_model_execution_grant, read_model_execution_receipt

    pending = server._project_work_pending
    if pending is not None and pending[0].work_root == work:
        raise InvalidCell("This Work has a pending project result; reconcile it before configuring the Work")
    if any(row._delegation.work_root == work
           for row in tuple(getattr(server, "_native_workshop_reservations", {}).values())):
        raise InvalidCell("This Work has a retained native turn; release it before configuring the Work")
    adapters = registry.adapter_protocol
    for protocol, read_delegation, read_grant, read_receipt in (
            (registry.baboom_model_execution_protocol, read_model_delegation,
             read_model_execution_grant, read_model_execution_receipt),
            (registry.baboom_connector_execution_protocol, read_connector_delegation,
             read_connector_execution_grant, read_connector_execution_receipt)):
        member = protocol.role("registry-member")
        settled = {read_receipt(snapshot, protocol, adapters, row.participant_id).grant_root
                   for row in read_relation(snapshot, protocol.registry("receipt"), budget=100000)
                   if row.role_id == member}
        for row in read_relation(snapshot, protocol.registry("grant"), budget=100000):
            if row.role_id != member or row.participant_id in settled:
                continue
            grant = read_grant(snapshot, protocol, adapters, row.participant_id)
            if read_delegation(snapshot, protocol, adapters, grant.delegation_root).work_root == work:
                raise InvalidCell("This Work has an unsettled execution grant; "
                                  "reconcile its receipt before configuring the Work")


def read_work_configuration(server, binding, *, scope, work):
    """Founder editor read: each configurable field's binding, value, digest and artifact readiness."""
    result = read_work_configuration_for_context(server, binding.context,
        view_root=binding.view_root, scope=scope, work=work)
    snapshot = server.universal_store.snapshot()
    if snapshot.revision != result["revision"]:
        raise InvalidCell("Work configuration changed while reading drafts; reopen it")
    result["invalid_drafts"] = []
    result["drafts"] = pending_work_configurations(snapshot, server.universal_registry,
        work=work, scope=scope, view_root=binding.view_root, subject_root=binding.subject_root,
        current_fields=result["fields"], invalid=result["invalid_drafts"])
    return result


def discard_work_configuration(server, binding, *, scope, work, revision_id, expected_revision):
    """Resolve one saved draft without deleting its provenance or touching Work bindings."""
    from . import universal_application as app
    from .workshop_project_revision import requirements_digest
    if (type(revision_id) is not str or re.fullmatch(r"[a-f0-9]{32}", revision_id) is None
            or type(expected_revision) is not int or expected_revision < 0):
        raise InvalidCell("Work draft discard identity is invalid")
    store, registry = server.universal_store, server.universal_registry
    view, context = app._view_session_for_context(registry, binding.context)
    identity = registry.authorization.broker.resolve(context)
    if identity.subject_root != binding.subject_root or view.root_id != binding.view_root:
        raise AuthorizationDenied("Work draft discard context changed")
    snapshot = store.snapshot()
    app._authorize(snapshot, registry, "catalog.configure", object_root=work, authentication_context=context)
    record_root = work + ":work-configuration:" + revision_id
    draft = _read_configuration_draft(snapshot, registry, record_root, revision_id,
        work=work, scope=scope, view_root=binding.view_root, subject_root=binding.subject_root)
    if draft is None:
        raise AuthorizationDenied("Work draft belongs to another context")
    if record_root + ":applied" in snapshot.cells:
        raise InvalidCell("An applied configuration cannot be discarded as a draft")
    marker = record_root + ":discarded"
    value = {"state":"discarded", "work":work, "revision_id":revision_id,
        "owner":binding.subject_root, "view":binding.view_root, "scope":scope,
        "draft_digest":requirements_digest(draft)}
    if marker in snapshot.cells:
        if read_value_graph(snapshot, registry.value_graph_protocol, marker) != value:
            raise InvalidCell("Work draft discard evidence changed")
        return {"revision_id":revision_id, "discarded":True, "revision":snapshot.revision, "reused":True}
    if snapshot.revision != expected_revision:
        raise InvalidCell("Work configuration changed; reopen it before discarding a draft")
    prepared = prepare_value_graphs(snapshot, registry.value_graph_protocol, {marker:value})
    app._commit_universal_user_change(store, registry, view, context, snapshot,
        route=ROUTE, command_name="catalog.configure", authorization_scope_root=work,
        create=prepared.create, replace=prepared.replace)
    return {"revision_id":revision_id, "discarded":True, "revision":store.revision, "reused":False}


def pending_work_configurations(snapshot, registry, *, work, scope, view_root, subject_root,
        current_fields, invalid=None):
    """Read this Work's existing proposal records through the journal's ID index."""
    import json
    from types import MappingProxyType
    from .universal_cell import _LazyHeadCellMap, _OverlayCellMap, ids_with_prefix
    from .workshop_project_revision import requirements_digest

    cells = snapshot.cells
    target = getattr(cells, "_head", cells)
    indexed = isinstance(target, _LazyHeadCellMap)
    if indexed:
        if len(target._overlay) > 8192:
            raise InvalidCell("Work draft overlay exceeds its discovery bound")
    elif not isinstance(cells, (dict, MappingProxyType, _OverlayCellMap)) or len(cells) > 1048576:
        raise InvalidCell("Work draft discovery requires an indexed snapshot")
    prefix = work + ":work-configuration:"
    deadline, matches, count, byte_count, drafts = time.monotonic() + 2, 0, 0, 0, []
    invalid = [] if invalid is None else invalid
    for index, record_root in enumerate(ids_with_prefix(cells, prefix) if indexed else cells):
        if index >= (8192 if indexed else 1048576) or time.monotonic() > deadline:
            raise InvalidCell("Work draft discovery exceeded its bound")
        if not record_root.startswith(prefix):
            continue
        matches += 1
        if matches > 8192:
            raise InvalidCell("Work draft discovery exceeded its match bound")
        revision_id = record_root[len(prefix):]
        if re.fullmatch(r"[a-f0-9]{32}", revision_id) is None:
            continue
        if record_root + ":applied" in cells or record_root + ":discarded" in cells:
            continue
        try:
            draft = _read_configuration_draft(snapshot, registry, record_root, revision_id,
                work=work, scope=scope, view_root=view_root, subject_root=subject_root)
        except (InvalidCell, KeyError, TypeError, ValueError, AttributeError):
            invalid.append({"revision_id":revision_id, "reason":"invalid_saved_draft"})
            continue
        if draft is None:
            continue
        draft["stale"] = any(entry["expected_target"] != current_fields[name]["target"]
            or entry["expected_digest"] != current_fields[name]["digest"]
            for name, entry in draft["fields"].items())
        count += 1
        if count > 64:
            raise InvalidCell("Pending Work drafts exceed their display bound")
        byte_count += len(json.dumps(draft, ensure_ascii=False).encode("utf-8"))
        if byte_count > 262144:
            raise InvalidCell("Work draft content exceeds its display bound")
        drafts.append(draft)
    return sorted(drafts, key=lambda draft: (draft["expected_revision"], draft["revision_id"]), reverse=True)


def _read_configuration_draft(snapshot, registry, record_root, revision_id, *, work, scope, view_root, subject_root):
        from .workshop_project_revision import requirements_digest
        record = read_value_graph(snapshot, registry.value_graph_protocol, record_root)
        if type(record) is not dict:
            raise InvalidCell("Work configuration draft is malformed")
        if (record.get("work") != work or record.get("revision_id") != revision_id
                or record.get("owner") != subject_root or record.get("scope") != scope
                or record.get("view") != view_root):
            return None
        names = record.get("fields")
        if (type(names) is not list or not names or any(type(name) is not str for name in names)
                or len(set(names)) != len(names)
                or any(name not in ("inputs", "requirements", "cde-container") for name in names)
                or record.get("revised_roots") != {name: record_root + ":data:" + name for name in names}
                or type(record.get("expected")) is not dict or set(record["expected"]) != set(names)
                or type(record.get("read_revision")) is not int
                or type(record.get("purpose")) is not str or record["purpose"] not in _CONFIGURATION_PURPOSES
                or any(type(record["expected"][name]) is not dict
                    or set(record["expected"][name]) != {"target", "digest"}
                    or type(record["expected"][name]["target"]) is not str
                    or type(record["expected"][name]["digest"]) is not str for name in names)):
            raise InvalidCell("Work configuration draft fields are malformed")
        proposed = {name: read_value_graph(snapshot, registry.value_graph_protocol,
            record["revised_roots"][name]) for name in names}
        if requirements_digest(proposed) != record.get("input_digest"):
            raise InvalidCell("Work configuration draft values changed")
        fields = {name: {"value": proposed[name], "expected_target": record["expected"][name]["target"],
            "expected_digest": record["expected"][name]["digest"] or None} for name in names}
        draft = {"revision_id":revision_id, "expected_revision":record["read_revision"],
            "purpose":record["purpose"], "fields":fields,
            "proposing_actor":record.get("proposing_actor", record["owner"])}
        return draft


def read_work_configuration_for_context(server, authentication_context, *, view_root, scope, work):
    """Shared projection for an already admitted caller's actual view and context.

    Transport admission and selected-Work access remain the caller's duty; this
    projection does not construct a browser identity or grant write authority.
    """
    if authentication_context is None:
        raise AuthorizationDenied("Work configuration requires an explicit authenticated context")
    from . import universal_application as app
    from .workshop_project_revision import _CONFIGURABLE, requirements_digest, work_custody_snapshot

    store, registry = server.universal_store, server.universal_registry
    _view, context = app._view_session_for_context(registry, authentication_context)
    snapshot = store.snapshot()
    current = inspect_project_bindings(snapshot, registry, work, context, fields=_CONFIGURABLE, material="values")
    if current["scope_root"] != scope or current["view_root"] != view_root:
        raise AuthorizationDenied("Work configuration read moved outside the selected Workshop view")
    custody = work_custody_snapshot(snapshot, registry, work)
    values = {name: current[name] for name in _CONFIGURABLE}
    try:
        validate_work_configuration(snapshot, registry, work, purpose="artifact-publication", current=values,
            proposed={}, workspace_root=completion_court_workspace_root(registry), context=context)
        blocker = None
    except InvalidCell as exc:
        blocker = str(exc)
    return {"fields": {name: {"target": current["targets"][name], "wired": not current["unwired"][name],
                "exposed": current["needs_exposure"][name], "value": values[name],
                "digest": None if current["unwired"][name] else requirements_digest(values[name])}
            for name in _CONFIGURABLE},
        "state": custody["state"], "editable": custody["state"] == "open" and not custody["claimant"],
        "artifact_ready": blocker is None, "artifact_blocker": blocker, "revision": snapshot.revision}
