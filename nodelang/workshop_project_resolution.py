"""Explicit local patch-delivery closure; never settle an unknown provider call.

The original result and one-use grant remain intact. This evidence is specific
to the project artifact host, not a generic connector execution receipt.
"""
import hashlib
import json
import math
import time

from .cell_adapters import read_permission
from .cell_authorization import AuthorizationDenied
from .cell_connector_execution import (
    read_connector_delegation, read_connector_execution_grant,
    read_connector_execution_receipt, read_connector_provider,
)
from .cell_protocols import read_relation, prepare_append_relation_members
from .cell_value_graph import prepare_value_graphs, read_value_graph
from .existing_workshop_project_execution import PROVIDER, OPERATION
from .universal_cell import Cell, InvalidCell, Snapshot


_EMPTY = hashlib.sha256(b"").hexdigest()
_PREPUBLICATION_ERRORS = frozenset({"provider_transport_uncertain", "provider_dispatch_timeout",
    "provider_dispatch_transport_uncertain", "provider_response_too_large",
    "provider_response_timeout", "provider_response_incomplete"})
_RESULT_FIELDS = {"work", "session", "delegation", "grant", "input_digest", "outcome",
    "artifact_name", "output_digest", "output_bytes", "error_code", "summary"}
_RESOLUTION_FIELDS = {"decision", "provider_outcome", "result", "result_digest", "grant",
    "grant_revision", "delegation", "input_digest", "work", "worker", "actor", "view",
    "scope", "claim", "created_at"}


def _roots(snapshot, protocol, name):
    rows = read_relation(snapshot, protocol.registry(name), budget=8192, retain_projection=False)
    roots = [row.participant_id for row in rows if row.role_id == protocol.role("registry-member")]
    if len(roots) > 256 or len(roots) != len(set(roots)):
        raise InvalidCell("Project delivery inventory exceeds its bounded registry")
    return roots


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def read_unresolved_project_delivery(snapshot, registry, grant_root, *, work=None):
    """Validate exact trusted prepublication evidence, without inferring failure."""
    protocol, adapters = registry.baboom_connector_execution_protocol, registry.adapter_protocol
    grant = read_connector_execution_grant(snapshot, protocol, adapters, grant_root)
    delegation = read_connector_delegation(snapshot, protocol, adapters, grant.delegation_root)
    provider = read_connector_provider(snapshot, protocol, adapters, delegation.provider_root)
    if (provider.root_id != registry.baboom_connector_provider_roots.get(PROVIDER)
            or provider.operation != OPERATION or grant.session_root != delegation.session_root
            or work is not None and delegation.work_root != work):
        raise AuthorizationDenied("Local delivery belongs to another project Work or provider")
    result_root = grant_root + ":project-result"
    value = read_value_graph(snapshot, registry.value_graph_protocol, result_root, max_depth=4)
    if (type(value) is not dict or set(value) != _RESULT_FIELDS
            or value["work"] != delegation.work_root or value["session"] != delegation.session_root
            or value["delegation"] != delegation.root_id or value["grant"] != grant_root
            or value["input_digest"] != delegation.input_digest or value["outcome"] != "uncertain"
            or value["error_code"] not in _PREPUBLICATION_ERRORS
            or type(value["output_bytes"]) is not int or value["output_bytes"] != 0
            or value["output_digest"] != _EMPTY):
        raise InvalidCell("Local abandonment requires exact prepublication transport evidence")
    for root in _roots(snapshot, protocol, "receipt"):
        receipt = read_connector_execution_receipt(snapshot, protocol, adapters, root)
        if receipt.grant_root == grant_root or receipt.delegation_root == delegation.root_id:
            raise InvalidCell("Project provider outcome already has a receipt")
    return value, grant, delegation


class _HistoricalScopeCells(dict):
    """At most 256 historical point reads; never reconstruct the whole graph."""
    def __init__(self, store, revision):
        super().__init__()
        self.store, self.revision = store, revision

    def __missing__(self, key):
        if len(self) >= 256:
            raise InvalidCell("Local delivery historical scope exceeds its bound")
        value = self.store.cells_at(self.revision, (key,))[key]
        self[key] = value
        return value

    def get(self, key, default=None):
        return self[key]

    def __contains__(self, key):
        self[key]
        return True


def read_project_delivery_resolution(snapshot, registry, grant_root, *, store):
    """Read a complete local decision, never manufacture an execution outcome."""
    root = grant_root + ":project-local-resolution"
    if root not in snapshot.cells:
        return None
    result, grant, delegation = read_unresolved_project_delivery(snapshot, registry, grant_root)
    value = read_value_graph(snapshot, registry.value_graph_protocol, root, max_depth=4)
    if (type(value) is not dict or set(value) != _RESOLUTION_FIELDS
            or value["decision"] != "abandon_local_delivery" or value["provider_outcome"] != "unknown"
            or value["result"] != grant_root + ":project-result" or value["result_digest"] != _digest(result)
            or value["grant"] != grant_root or value["delegation"] != delegation.root_id
            or value["input_digest"] != delegation.input_digest or value["work"] != delegation.work_root
            or value["worker"] != delegation.session_root or value["actor"] != registry.authorization.subject_root
            or type(value["grant_revision"]) is not int or value["grant_revision"] < 1
            or type(value["created_at"]) not in (int, float) or not math.isfinite(value["created_at"])
            or any(type(value[key]) is not str or value[key] not in snapshot.cells
                   for key in ("actor", "view", "scope", "claim"))):
        raise InvalidCell("Local delivery resolution does not match its original attempt")
    permission = read_permission(snapshot, registry.adapter_protocol, delegation.permission_root)
    if permission.lifecycle_root != registry.adapter_protocol.states["revoked"]:
        raise InvalidCell("Local delivery resolution permission is not revoked")
    from . import universal_application as app
    view = registry.view_sessions.get(value["actor"])
    if view is None or view.root_id != value["view"] or view.subject_root != value["actor"]:
        raise InvalidCell("Local delivery resolution view belongs to another owner")
    if value["grant_revision"] != store.cell_created_revision(grant_root):
        raise InvalidCell("Local delivery resolution invocation chronology changed")
    recorded_revision = store.cell_created_revision(root)
    historical = Snapshot(recorded_revision, _HistoricalScopeCells(store, recorded_revision))
    if app._read_view_scope_trail_structure(historical, registry, view)[-1] != value["scope"]:
        raise InvalidCell("Local delivery resolution scope differs from its recorded view")
    machine = app.read_instance_state_machine(snapshot, registry.assembly_protocol,
        registry.standard_library.state_machine_protocol, value["work"])
    rows = read_relation(snapshot, machine.history_root, budget=2048, retain_projection=False)
    if len(rows) > 256:
        raise InvalidCell("Local delivery resolution claim history exceeds its bound")
    events = app.machine_history(snapshot, registry.standard_library.state_machine_protocol, machine.root_id)
    claims = [event for event in events if event.root_id == value["claim"]]
    if (len(claims) != 1 or app._text(snapshot, claims[0].event_root).casefold() != "claim"
            or value["worker"] not in claims[0].context_roots
            or store.cell_created_revision(claims[0].root_id) > recorded_revision):
        raise InvalidCell("Local delivery resolution claim does not belong to this Work and worker")
    for region in (registry.application_root, registry.map.domains["connectors"]):
        rows = read_relation(snapshot, region, budget=100_000, retain_projection=False)
        if sum(row.role_id == registry.roles["member"] and row.participant_id == root for row in rows) != 1:
            raise InvalidCell("Local delivery resolution authority is incomplete")
    return {**value, "resolution":root, "state":"local_delivery_abandoned"}


def require_latest_project_delivery(store, registry, work, grant_root):
    """Use graph birth revisions, not a new decision timestamp, to order calls."""
    from .cell_model_execution import (read_model_delegation, read_model_execution_grant,
                                      read_model_execution_receipt)
    snapshot = store.snapshot()
    selected_revision = store.cell_created_revision(grant_root)
    if selected_revision < 1:
        raise InvalidCell("Project invocation chronology is unavailable")
    families = (
        (registry.baboom_connector_execution_protocol, read_connector_delegation,
         read_connector_execution_grant, read_connector_execution_receipt, True),
        (registry.baboom_model_execution_protocol, read_model_delegation,
         read_model_execution_grant, read_model_execution_receipt, False))
    for protocol, read_delegation, read_grant, read_receipt, connector in families:
        delegations = {}
        for root in _roots(snapshot, protocol, "delegation"):
            row = read_delegation(snapshot, protocol, registry.adapter_protocol, root)
            if row.work_root == work:
                delegations[root] = row
        receipts = {}
        for root in _roots(snapshot, protocol, "receipt"):
            row = read_receipt(snapshot, protocol, registry.adapter_protocol, root)
            if row.delegation_root in delegations:
                if row.grant_root in receipts:
                    raise InvalidCell("Project invocation has ambiguous receipts")
                receipts[row.grant_root] = row
        issued = set()
        for root in _roots(snapshot, protocol, "grant"):
            grant = read_grant(snapshot, protocol, registry.adapter_protocol, root)
            if grant.delegation_root not in delegations:
                continue
            issued.add(grant.delegation_root)
            if root == grant_root:
                continue
            if store.cell_created_revision(root) >= selected_revision:
                raise AuthorizationDenied("A newer invocation prevents local delivery closure")
            if root not in receipts and not (connector and read_project_delivery_resolution(snapshot, registry, root, store=store)):
                raise AuthorizationDenied("Another unknown invocation prevents local delivery closure")
        for root, delegation in delegations.items():
            if root not in issued:
                permission = read_permission(snapshot, registry.adapter_protocol, delegation.permission_root)
                if time.time() < delegation.expires_at and permission.lifecycle_root in {
                        registry.adapter_protocol.states["requested"], registry.adapter_protocol.states["granted"]}:
                    raise AuthorizationDenied("Another live delegation prevents local delivery closure")
    if store.revision != snapshot.revision:
        raise InvalidCell("Project invocation chronology changed during admission")
    return selected_revision


def project_local_deliveries(store, registry, work):
    """Selected-Work restart projection from graph grants, with no file reads."""
    snapshot = store.snapshot()
    protocol, adapters = registry.baboom_connector_execution_protocol, registry.adapter_protocol
    deliveries = []
    for grant_root in _roots(snapshot, protocol, "grant"):
        grant = read_connector_execution_grant(snapshot, protocol, adapters, grant_root)
        delegation = read_connector_delegation(snapshot, protocol, adapters, grant.delegation_root)
        if delegation.work_root != work or delegation.provider_root != registry.baboom_connector_provider_roots.get(PROVIDER):
            continue
        result_root = grant_root + ":project-result"
        if result_root not in snapshot.cells:
            continue
        value = read_value_graph(snapshot, registry.value_graph_protocol, result_root, max_depth=4)
        if type(value) is not dict:
            raise InvalidCell("Project delivery result is malformed")
        if value.get("outcome") != "uncertain" or value.get("error_code") not in _PREPUBLICATION_ERRORS:
            continue
        read_unresolved_project_delivery(snapshot, registry, grant_root, work=work)
        decision = read_project_delivery_resolution(snapshot, registry, grant_root, store=store)
        deliveries.append({"work":work, "grant":grant_root, "result":result_root,
            "input_digest":delegation.input_digest, "worker":delegation.session_root,
            "provider_outcome":"unknown", "output_bytes":0,
            "state":"local_delivery_abandoned" if decision else "unreceived",
            "resolution":decision["resolution"] if decision else None})
        if len(deliveries) > 32:
            raise InvalidCell("Selected Work exceeds its local delivery history bound")
    if store.revision != snapshot.revision:
        raise InvalidCell("Project delivery history changed during selection")
    return deliveries


def abandon_project_delivery(host, binding, *, root, scope, work, grant_root, result_root, input_digest):
    """Explicit native action; atomic decision, registration and revocation."""
    from . import universal_application as app
    server = host.server
    with server.mutation_lock, server.universal_registry.authorization.broker.live_context(binding.context):
        host._admit(binding, root, scope, work, work_action="edit")
        if host._identity is not None and host._identity[:6] != (*host._binding(binding, root, scope), work):
            raise AuthorizationDenied("Resolve the current Workshop operation before another local delivery")
        if host._identity is not None and (not host._project or
                host._grant is not None and host._grant.get("grant") != grant_root):
            raise AuthorizationDenied("Local delivery is not the retained project attempt")
        server.require_universal_http_route("POST", "/api/universal/workshop-native",
            authentication_context=binding.context, revalidate=True)
        if server.universal_checkpoint_guard is not None:
            server.universal_checkpoint_guard.require_healthy()
        if (host._cancel.is_set() or server._model_execution_closing or server._model_execution_active
                or not server._model_execution_idle.is_set() or server._project_work_pending is not None):
            raise AuthorizationDenied("Local delivery cannot close while execution is active or pending")
        store, registry = server.universal_store, server.universal_registry
        snapshot = store.snapshot()
        value, grant, delegation = read_unresolved_project_delivery(snapshot, registry, grant_root, work=work)
        if result_root != grant_root + ":project-result" or input_digest != delegation.input_digest:
            raise AuthorizationDenied("Local delivery selection changed")
        machine = app.read_instance_state_machine(snapshot, registry.assembly_protocol,
            registry.standard_library.state_machine_protocol, work)
        rows = read_relation(snapshot, machine.history_root, budget=2048, retain_projection=False)
        if len(rows) > 256:
            raise InvalidCell("Local delivery claim history exceeds its bound")
        history = app.machine_history(snapshot, registry.standard_library.state_machine_protocol, machine.root_id)
        if (app._text(snapshot, machine.current_state_root).casefold() != "claimed"
                or app._governed_work_claimant_session(snapshot, registry, work) != delegation.session_root
                or not history or app._text(snapshot, history[-1].event_root).casefold() != "claim"
                or delegation.session_root not in history[-1].context_roots):
            raise AuthorizationDenied("Local delivery no longer owns the selected Work claim")
        grant_revision = require_latest_project_delivery(store, registry, work, grant_root)
        previous = read_project_delivery_resolution(snapshot, registry, grant_root, store=store)
        if previous is not None:
            if any(previous[key] != expected for key, expected in {
                    "actor":binding.subject_root, "view":binding.view_root, "scope":scope,
                    "claim":history[-1].root_id, "grant_revision":grant_revision}.items()):
                raise AuthorizationDenied("Local delivery resolution belongs to another admitted decision")
            return previous
        resolution_root = grant_root + ":project-local-resolution"
        decision = {"decision":"abandon_local_delivery", "provider_outcome":"unknown",
            "result":result_root, "result_digest":_digest(value), "grant":grant_root,
            "grant_revision":grant_revision, "delegation":delegation.root_id,
            "input_digest":input_digest, "work":work, "worker":delegation.session_root,
            "actor":binding.subject_root, "view":binding.view_root, "scope":scope,
            "claim":history[-1].root_id, "created_at":time.time()}
        patches = [prepare_value_graphs(snapshot, registry.value_graph_protocol, {resolution_root:decision})]
        for region in (registry.application_root, registry.map.domains["connectors"]):
            patches.append(prepare_append_relation_members(snapshot, region,
                ((registry.roles["member"], resolution_root),), budget=100_000))
        permission = read_permission(snapshot, registry.adapter_protocol, delegation.permission_root)
        replacements = {}
        if permission.lifecycle_root in {registry.adapter_protocol.states["requested"], registry.adapter_protocol.states["granted"]}:
            rows = read_relation(snapshot, delegation.permission_root)
            lifecycle = [row for row in rows if row.role_id == registry.adapter_protocol.role("lifecycle")]
            if len(lifecycle) != 1:
                raise InvalidCell("Local delivery permission lifecycle is ambiguous")
            cell = snapshot.cells[lifecycle[0].incidence_id]
            replacements[cell.id] = Cell(cell.id, cell.link0, registry.adapter_protocol.states["revoked"], cell.atom)
        elif permission.lifecycle_root != registry.adapter_protocol.states["revoked"]:
            raise InvalidCell("Local delivery permission cannot be closed")
        for patch in patches:
            for cell in patch.replace:
                if cell.id in replacements and replacements[cell.id] != cell:
                    raise InvalidCell("Local delivery decision patches conflict")
                replacements[cell.id] = cell
        host._admit(binding, root, scope, work, work_action="edit")
        registry.authorization.broker.resolve(binding.context)
        store.commit(snapshot.revision, create=tuple(cell for patch in patches for cell in patch.create),
                     replace=tuple(replacements.values()))
        return read_project_delivery_resolution(store.snapshot(), registry, grant_root, store=store)
