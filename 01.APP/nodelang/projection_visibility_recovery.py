"""Founder-only repair of one provably ungranted runtime-session visibility.

Called exclusively by the authenticated machine route, under its mutation lock.
Never grants authority, removes an Agent Session, or edits the database directly.
"""
from datetime import datetime, timezone
from collections.abc import Mapping
import json
import sys
import time
import uuid

from . import universal_application as app


MAX_VISIBILITY_MEMBERS = 10_000
MAX_AUTHORITY_MEMBERS = 10_000
MAX_AUTHORITY_RELATIONSHIPS = 5_000
MAX_CELL_LOOKUPS = 300_000
MAX_UNIQUE_CELLS = 100_000
MAX_ATOM_BYTES = 32 * 1024 * 1024
MAX_RETAINED_BYTES = 64 * 1024 * 1024
MAX_READ_SECONDS = 10


class RecoveryReadBudgetExceeded(RuntimeError):
    """Resource exhaustion is not malformed graph data and must not be hidden."""


class _RecoveryReads(Mapping):
    """Bound actual keyed reads; never enumerate or size the backing journal."""
    def __init__(self, cells):
        self.base = cells
        self.cache = {}
        self.lookups = 0
        self.atom_bytes = 0
        self.retained_bytes = 0
        self.started = time.monotonic()
        self.stage = "caller-authorization"

    def metrics(self):
        return {"stage": self.stage, "lookups": self.lookups, "unique_cells": len(self.cache),
                "atom_bytes": self.atom_bytes,
                "retained_bytes": self.retained_bytes + sys.getsizeof(self.cache),
                "elapsed_ms": round((time.monotonic() - self.started) * 1000, 2)}

    def exhausted(self, reason):
        raise RecoveryReadBudgetExceeded("VISIBILITY_RECOVERY_READ_BUDGET_EXCEEDED: " + reason
                                         + "; " + json.dumps(self.metrics(), sort_keys=True))

    def __getitem__(self, key):
        self.lookups += 1
        if self.lookups > MAX_CELL_LOOKUPS:
            self.exhausted("keyed-read limit")
        if time.monotonic() - self.started > MAX_READ_SECONDS:
            self.exhausted("elapsed read deadline")
        if key in self.cache:
            return self.cache[key]
        if len(self.cache) >= MAX_UNIQUE_CELLS:
            self.exhausted("unique-cell limit")
        cell = self.base[key]
        self.atom_bytes += len(cell.atom)
        if self.atom_bytes > MAX_ATOM_BYTES:
            self.exhausted("atom-byte limit")
        # Conservatively count every referenced Cell and field even when the
        # backing snapshot shares those objects. This bounds this reader's
        # retained data; it is not a limit on the whole desktop process.
        self.retained_bytes += sum(sys.getsizeof(value) for value in
            (cell, key, cell.id, cell.link0, cell.link1, cell.atom))
        if self.retained_bytes + sys.getsizeof(self.cache) > MAX_RETAINED_BYTES:
            self.exhausted("retained-object limit")
        self.cache[key] = cell
        if self.retained_bytes + sys.getsizeof(self.cache) > MAX_RETAINED_BYTES:
            self.cache.pop(key)
            self.exhausted("retained-object limit")
        return cell

    def __iter__(self):
        self.exhausted("whole-journal enumeration forbidden")

    def __len__(self):
        self.exhausted("whole-journal cardinality queries forbidden")


def _exact_text(value, name):
    if type(value) is not str or not value or len(value.encode("utf-8")) > 512:
        raise app.InvalidCell("Visibility recovery has invalid " + name)
    return value


def _inspect(store, registry, *, view_root, agent_session_root, context):
    original = store.snapshot()
    snapshot = app.Snapshot(original.revision, _RecoveryReads(original.cells))
    identity = registry.authorization.broker.resolve(context)
    if identity.subject_root != registry.authorization.subject_root:
        raise app.AuthorizationDenied("Visibility recovery requires live founder authority")
    if agent_session_root == registry.agent_body.session.root_id:
        founder = app.read_agent_session(snapshot, registry.agent_body.protocol,
                                        registry.authorization.protocol, agent_session_root)
        if founder.body_root != registry.agent_body.body.root_id or founder.state_root != registry.agent_body.protocol.state("active"):
            raise app.AuthorizationDenied("Visibility recovery founder session is not active")
    else:
        founder = app._require_founder_runtime_session(
            snapshot, registry, agent_session_root, purpose="Visibility recovery"
        )
    if founder.subject_root != identity.subject_root:
        raise app.AuthorizationDenied("Visibility recovery caller differs from founder authority")
    view, _ = app._view_session_for_context(registry, context)
    if view.root_id != _exact_text(view_root, "view"):
        raise app.AuthorizationDenied("Visibility recovery is restricted to the caller view")
    snapshot.cells.stage = "visibility-membership"
    members = app.read_relation(snapshot, view.visibility_root, budget=MAX_VISIBILITY_MEMBERS)
    visible = [m for m in members if m.role_id == registry.roles["visible"]]
    assigned = [m.participant_id for m in visible]
    if len(assigned) != len(set(assigned)):
        raise app.InvalidCell("Visibility recovery refuses duplicate visible members")
    authority = registry.authorization
    snapshot.cells.stage = "authority-membership"
    authority_members = app.read_relation(snapshot, authority.identity_protocol.root_id,
                                         budget=MAX_AUTHORITY_MEMBERS)
    registered = [m.participant_id for m in authority_members
                  if m.role_id == authority.identity_protocol.role("relationship-member")]
    if len(registered) > MAX_AUTHORITY_RELATIONSHIPS or len(registered) != len(set(registered)):
        raise app.InvalidCell("Visibility recovery authority registry exceeds its bound or repeats roots")
    snapshot.cells.stage = "signature-verification"
    verified = app.verify_relationship_authority_snapshot(
        snapshot, authority.identity_protocol, authority.relationship_broker
    )
    signed = {}
    for relationship in verified.active_relationships:
        if (
            relationship.source_root == authority.resource_reader_principal_root
            and relationship.target_root == view.subject_root
            and relationship.kind_root == authority.identity_protocol.kinds["delegation"]
            and relationship.tenant_root == authority.tenant_root
            and relationship.scope_root is not None
            and relationship.action_roots == (authority.protocol.actions["read"],)
            and view.visibility_root in relationship.evidence_roots
        ):
            if relationship.scope_root in signed:
                raise app.InvalidCell("Visibility recovery refuses duplicate signed grants")
            signed[relationship.scope_root] = relationship.root_id
    ungranted = sorted(set(assigned) - set(signed))
    unassigned = sorted(set(signed) - set(assigned))
    if len(ungranted) != 1 or unassigned:
        raise app.InvalidCell("Visibility recovery requires exactly one ungranted root and no unassigned grants")
    target = ungranted[0]
    _exact_text(target, "target")
    if not target.startswith("app:agent-session:runtime:"):
        raise app.InvalidCell("Visibility recovery target is not a runtime Agent Session")
    snapshot.cells.stage = "target-session-validation"
    app._runtime_agent_session(snapshot, registry, target)
    selected = [m for m in visible if m.participant_id == target]
    if len(selected) != 1:
        raise app.InvalidCell("Visibility recovery incidence is ambiguous")
    incidence = selected[0].incidence_id
    snapshot.cells.stage = "prospective-single-incidence-removal"
    removal = app.prepare_remove_relation_members(snapshot, view.visibility_root,
        (incidence,), budget=MAX_VISIBILITY_MEMBERS)
    candidate = app._candidate_snapshot_for_atomic_commit(snapshot, replace=removal.replace)
    # Keep the production law unchanged. It verifies interfaces, exposed scopes,
    # signed grants, resource audiences and scope trail on the prospective view.
    snapshot.cells.stage = "candidate-projection-validation"
    error = None
    try:
        app._session_canvas_roots(candidate, registry, view, authority_snapshot=verified)
    except app.InvalidCell as exc:
        # Genuine structural refusal is useful diagnostic data. Resource
        # exceptions deliberately bypass this handler and retain their metrics.
        error = str(exc)[:512]
    result = {"view": view.root_id, "visibility": view.visibility_root,
              "root": target, "incidence": incidence, "revision": snapshot.revision,
              "ungranted_count": 1, "unassigned_grant_count": 0,
              "candidate_projection_valid": error is None,
              "read_metrics": snapshot.cells.metrics()}
    if error is not None:
        result["error"] = error
    return snapshot, view, removal, result


def diagnose_visibility_recovery(store, registry, *, view_root, agent_session_root, context):
    return _inspect(store, registry, view_root=view_root,
                    agent_session_root=agent_session_root, context=context)[3]


def repair_visibility_recovery(store, registry, *, request, agent_session_root, context):
    if type(request) is not dict or set(request) != {"view", "root", "incidence", "expected_revision"}:
        raise app.InvalidCell("Visibility recovery request must name exact view, root, incidence and revision")
    if type(request["expected_revision"]) is not int:
        raise app.InvalidCell("Visibility recovery revision must be an integer")
    if store.revision != request["expected_revision"]:
        raise app.Conflict("Visibility recovery revision is stale")
    snapshot, view, removal, result = _inspect(
        store, registry, view_root=request["view"],
        agent_session_root=agent_session_root, context=context,
    )
    if snapshot.revision != request["expected_revision"]:
        raise app.Conflict("Visibility recovery revision changed during validation")
    if result["candidate_projection_valid"] is not True:
        raise app.InvalidCell("Visibility recovery candidate projection is invalid: " + result["error"])
    for key in ("root", "incidence"):
        if result[key] != _exact_text(request[key], key):
            raise app.Conflict("Visibility recovery target differs from diagnosis")
    audit_root = "app:visibility-recovery:" + uuid.uuid4().hex
    evidence = {"operation": "remove-ungranted-runtime-visibility",
                "actor_session": agent_session_root, "timestamp": datetime.now(timezone.utc).isoformat(),
                "before_revision": snapshot.revision, **result}
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(payload) > 4096:
        raise app.InvalidCell("Visibility recovery audit exceeds its bound")
    audit = app.Cell(audit_root, view.visibility_root, result["root"], payload)
    revision = store.commit(snapshot.revision, create=(audit,), replace=removal.replace)
    return {**result, "revision": revision, "audit": audit_root, "status": "visibility-only-repaired"}
