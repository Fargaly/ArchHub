"""Prepare an isolated history binding; activation and presentation are separate.

Keep existing entry/evidence Cells unchanged for historical references. Detach
only their live conversation memberships. This creates no per-message alias and
does not authorize a commit, retire canvas members, or validate old approvals.
"""
from dataclasses import dataclass, asdict

from .cell_deliberation import read_deliberation_entry, read_deliberation_space, _optional, _terminal
from .cell_protocols import read_relation, prepare_remove_relation_members, prepare_append_relation_members
from .conversation_content import (
    APPLICATION_BINDING_BUDGET, CONTROL_BUDGET, PreparedContentBinding,
    _instance_id, prepare_empty_content_binding, read_content_binding, read_content_space,
)
from .conversation_migration import (
    _check_time, _deadline, _encoded, _record, _reconcile_history, _source_matches, _verify_stage_owner,
)
from .universal_cell import overlay_read_snapshot


@dataclass(frozen=True)
class PreparedLegacyContentBinding:
    """Review data, not activation authority; recheck both stores before commit."""
    patch: PreparedContentBinding
    source_authority: str
    source_digest: str
    manifest_digest: str
    stage_id: str
    retained_entry_roots: tuple[str, ...]
    historical_roots: tuple[str, ...]


def _controls(space):
    result = asdict(space)
    result.pop("entry_roots")
    result.pop("content_store_root")
    return result


def prepare_legacy_content_binding(importing, *, binding_root=None, time_budget_seconds=30):
    """Verify the complete owned stage and return one uncommitted graph patch.

    Use the importer's existing exclusive destination handle and pinned manifest.
    The application keeps its existing instance, or adopts the exact instance
    already selected for this migration. Original entry content is compared one
    record at a time; only root metadata is retained in the prepared result.
    An explicit binding root preserves an owner's pending publication identity;
    it does not bypass the current source, control, or staging checks.
    """
    if importing._closed or importing._failed:
        raise ValueError("migration importer is closed or interrupted")
    if not importing._verified_complete or importing.copied != importing.total:
        raise ValueError("migration copy must be complete before binding preparation")
    deadline = _deadline(time_budget_seconds)
    header, protocol = importing.header, importing.protocol
    with importing.source.stable_snapshot(expected_revision=header["source_revision"]), importing._history._lock:
        _check_time(deadline)
        snapshot = _source_matches(importing.source, header)
        _verify_stage_owner(importing._history, importing.destination, importing.ticket.manifest_digest)
        stage = importing._history._db.execute("SELECT stage_id FROM migration_staging WHERE singleton=1").fetchone()
        conversations = importing._history._db.execute("SELECT id,last_sequence FROM conversations LIMIT 2").fetchall()
        count = importing._history._db.execute("SELECT count(*) FROM messages").fetchone()[0]
        if (len(conversations) != 1 or tuple(conversations[0]) != (header["space_root"], importing.total)
                or count != importing.total):
            raise ValueError("migration destination scope or message count mismatch")
        space = read_deliberation_space(snapshot, protocol, header["space_root"])
        controls = dict(header["controls"])
        controls.pop("content_store_root")
        if space.content_store_root is not None or _encoded(_controls(space)) != _encoded(controls):
            raise ValueError("migration conversation controls changed")
        members = read_relation(snapshot, space.root_id,
            budget=importing.total + CONTROL_BUDGET, retain_projection=False)
        entry_members = tuple(member for member in members if member.role_id == protocol.role("space-entry"))
        roots = tuple(row[0] for row in importing._manifest.execute("SELECT message_id FROM entries ORDER BY sequence"))
        if tuple(member.participant_id for member in entry_members) != roots or len(roots) != importing.total:
            raise ValueError("migration entry membership mismatch")
        detached = prepare_remove_relation_members(snapshot, space.root_id,
            (member.incidence_id for member in entry_members), budget=importing.total + CONTROL_BUDGET)
        creates, replaces = {}, {cell.id: cell for cell in detached.replace}
        candidate = overlay_read_snapshot(snapshot, replace=replaces.values())

        application_members = read_relation(candidate, header["application_root"], budget=APPLICATION_BINDING_BUDGET)
        instance_root = _optional(application_members, protocol.role("scope-content-instance"), "application content instance")
        if instance_root is None:
            instance_root = "conversation-instance:" + header["instance_id"]
            if instance_root in snapshot.cells:
                raise ValueError("migration instance identity already exists outside its application binding")
            creates[instance_root] = _terminal(instance_root, header["instance_id"])
            instance_patch = prepare_append_relation_members(candidate, header["application_root"],
                ((protocol.role("scope-content-instance"), instance_root),), budget=APPLICATION_BINDING_BUDGET)
            creates.update((cell.id, cell) for cell in instance_patch.create)
            replaces.update((cell.id, cell) for cell in instance_patch.replace)
            candidate = overlay_read_snapshot(snapshot, create=creates.values(), replace=replaces.values())
        elif _instance_id(candidate, instance_root) != header["instance_id"]:
            raise ValueError("migration application instance mismatch")

        content = prepare_empty_content_binding(candidate, protocol,
            application_root=header["application_root"], space_root=space.root_id,
            binding_root=binding_root)
        for cell in content.create:
            if cell.id in creates or cell.id in snapshot.cells:
                raise ValueError("migration binding creates an existing identity")
            creates[cell.id] = cell
        for cell in content.replace:
            if cell.id in creates:
                creates[cell.id] = cell
            else:
                replaces[cell.id] = cell
        candidate = overlay_read_snapshot(snapshot, create=creates.values(), replace=replaces.values())
        binding = read_content_binding(candidate, protocol,
            application_root=header["application_root"], space_root=space.root_id)
        bound_space = read_content_space(candidate, protocol, space.root_id)
        if binding.instance_id != header["instance_id"] or bound_space.entry_roots or _encoded(_controls(bound_space)) != _encoded(controls):
            raise ValueError("migration prospective binding changed controls or instance")

        historical_roots = set()
        for expected in importing._manifest.execute("SELECT * FROM entries ORDER BY sequence"):
            _check_time(deadline)
            actual = importing._history.get(space.root_id, expected["message_id"],
                principal="migration-reconciliation", read_all=True)
            importing._verify_record(actual, expected)
            # This also detects unintended changes to shared relation/body Cells
            # in the prospective graph, rather than checking only root IDs.
            entry = read_deliberation_entry(candidate, protocol, expected["message_id"])
            record, historical, digest, _ = _record(entry, candidate)
            if digest != expected["record_digest"] or _encoded(historical).decode() != expected["historical"]:
                raise ValueError("migration historical entry changed in prospective binding")
            importing._verify_record(record, expected)
            historical_roots.update((entry.policy_root, entry.authorization_action_root, entry.lifecycle_root,
                *entry.authorization_rule_roots, *entry.reference_roots, *entry.evidence_roots))
        _reconcile_history(importing._history, deadline)
        _source_matches(importing.source, header)
        _check_time(deadline)
        return PreparedLegacyContentBinding(
            PreparedContentBinding(snapshot.revision, binding, tuple(creates.values()), tuple(replaces.values())),
            header["source_authority"], header["source_digest"], importing.ticket.manifest_digest,
            stage["stage_id"], roots, tuple(sorted(historical_roots)))
