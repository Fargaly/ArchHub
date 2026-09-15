"""Admitted child conversations in the existing Workshop graph and content store.

An empty ordinary row reserves retry identity only. It becomes a conversation
when one authenticated graph commit publishes its space, content binding and
Workbench scope incidence. No row, name or digest grants graph authority.
"""
import hashlib
import json

from .cell_authorization import AuthorizationDenied
from .cell_deliberation import (
    MAX_TITLE_BYTES, _read_requirement, prepare_deliberation_space,
    read_deliberation_space,
)
from .cell_protocols import prepare_append_relation_members, read_relation
from .conversation_content import CONTROL_BUDGET, read_content_binding, prepare_empty_content_binding
from .universal_cell import InvalidCell, overlay_read_snapshot


MAX_CONVERSATIONS = 50
WORKBENCH_BUDGET = 100_000


def _scope_roots(snapshot, *, workbench_root, scope_role, internal_scope_roots):
    internals = tuple(internal_scope_roots)
    if not internals or len(internals) != len(set(internals)):
        raise InvalidCell("Workshop internal scope declaration is invalid")
    members = read_relation(snapshot, workbench_root, budget=WORKBENCH_BUDGET)
    scopes = tuple(member.participant_id for member in members if member.role_id == scope_role)
    if scopes[:len(internals)] != internals or len(scopes) != len(set(scopes)):
        raise InvalidCell("Workshop internal scope registration changed")
    return (internals[0], *scopes[len(internals):])


def validate_workshop_conversation_scope(snapshot, protocol, *, application_root, canonical_root, root):
    """Validate selected scope content; its ID is never its admission evidence."""
    canonical_binding = read_content_binding(snapshot, protocol,
        application_root=application_root, space_root=canonical_root)
    controls = read_relation(snapshot, root, budget=CONTROL_BUDGET)
    if sum(member.role_id == protocol.role("space-title") for member in controls) != 1:
        raise InvalidCell("Workshop child scope is not a deliberation space")
    binding = read_content_binding(snapshot, protocol,
        application_root=application_root, space_root=root)
    if (binding.instance_root, binding.instance_id) != (
            canonical_binding.instance_root, canonical_binding.instance_id):
        raise InvalidCell("Workshop child conversation content instance changed")
    return binding


def _scope_page(roots, after, limit):
    if type(limit) is not int or not 1 <= limit <= MAX_CONVERSATIONS:
        raise InvalidCell("conversation catalog page limit must be 1 to 50")
    if after is not None and (type(after) is not str or after not in roots):
        raise InvalidCell("conversation catalog position changed; refresh")
    start = 0 if after is None else roots.index(after) + 1
    page = roots[start:start + limit]
    has_more = start + len(page) < len(roots)
    return {"roots": page, "has_more": has_more,
            "next_after": page[-1] if has_more and page else None}


def registered_workshop_conversation_roots(snapshot, protocol, *, application_root,
        workbench_root, scope_role, internal_scope_roots, after=None, limit=50):
    """Return a bounded validated page of actual registered scopes, never ordinary orphans."""
    roots = _scope_roots(snapshot, workbench_root=workbench_root, scope_role=scope_role,
                         internal_scope_roots=internal_scope_roots)
    page = _scope_page(roots, after, limit)
    for root in page["roots"]:
        validate_workshop_conversation_scope(snapshot, protocol,
            application_root=application_root, canonical_root=roots[0], root=root)
    return page


def _registered(snapshot, registry):
    return _scope_roots(snapshot, workbench_root=registry.workshop_workbench_root,
        scope_role=registry.roles["scope"], internal_scope_roots=(
            registry.workshop_root, registry.brain_control_ledger_root,
            registry.governed_work_registry_root, registry.workshop_assignment_registry_root,
            registry.governed_work_claim_binding_protocol_root,
            registry.governed_work_claim_binding_registry_root))


def _service(owner):
    service = owner.conversation_content
    service._require_live_owner()
    if not service.belongs_to(owner.universal_store, owner.universal_registry):
        raise AuthorizationDenied("Workshop content service belongs to another owner")
    return service


def _admit(snapshot, registry, context, *, create=False):
    from .universal_application import _require_application_authorization, _view_session_for_context
    if context is None:
        raise AuthorizationDenied("Workshop catalog requires an explicit authenticated context")
    authority = registry.authorization
    identity = authority.broker.resolve(context)
    view, resolved_context = _view_session_for_context(registry, context)
    if resolved_context is not context or view.subject_root != identity.subject_root:
        raise AuthorizationDenied("Workshop catalog application view changed")
    if create and identity.subject_root != authority.subject_root:
        raise AuthorizationDenied("Workshop conversation creation requires the founder")
    _require_application_authorization(snapshot, registry, "create" if create else "read",
        registry.workshop_workbench_root, authentication_context=context)
    return identity.subject_root


def _revision(value):
    if type(value) is not int or not 0 <= value < 2**63:
        raise InvalidCell("Workshop catalog requires an expected graph revision")


def _controls(snapshot, protocol, space):
    requirements = tuple(_read_requirement(snapshot, protocol, root, budget=8)
                         for root in space.requirement_roots)
    values = {name: getattr(space, name) for name in (
        "category_roots", "policy_root", "action_root", "scope_roots", "lifecycle_root",
        "interface_root", "purpose_root", "classification_root", "audience_root",
        "operational_state_root")}
    values["requirements"] = tuple((row.phase_root, row.category_root,
        row.minimum_count, row.minimum_evidence_count) for row in requirements)
    return values, requirements


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def _input(title, participants, key):
    if (type(title) is not str or not title.strip() or "\x00" in title
            or len(title.encode("utf-8")) > MAX_TITLE_BYTES):
        raise InvalidCell("conversation title must be nonempty and at most 512 UTF-8 bytes")
    if (type(participants) not in (list, tuple) or not 1 <= len(participants) <= 64
            or any(type(root) is not str or not root or "\x00" in root
                   or len(root.encode("utf-8")) > 512 for root in participants)
            or len(set(participants)) != len(participants)):
        raise InvalidCell("conversation participants must be 1 to 64 distinct admitted roots")
    if type(key) is not str or not key or "\x00" in key or len(key.encode("utf-8")) > 512:
        raise InvalidCell("conversation creation idempotency key is invalid")
    return title.strip(), tuple(participants)


def _row(snapshot, registry, root):
    space = read_deliberation_space(snapshot, registry.deliberation_protocol, root, budget=CONTROL_BUDGET)
    return {"root": root, "title": space.title, "participant_roots": list(space.participant_roots),
            "is_general": root == registry.workshop_root}


def _prepare_child(snapshot, registry, service, *, root, title, participants, controls,
                   requirements, binding_root, instance_id, context, creator):
    protocol = registry.deliberation_protocol
    prepared = prepare_deliberation_space(snapshot, protocol, space_id=root, title=title,
        participant_roots=participants, requirements=requirements,
        **{name: value for name, value in controls.items() if name != "requirements"})
    candidate = overlay_read_snapshot(snapshot, create=prepared.create)
    binding_patch = prepare_empty_content_binding(candidate, protocol,
        application_root=registry.application_root, space_root=root, binding_root=binding_root)
    if binding_patch.binding.instance_id != instance_id:
        raise InvalidCell("conversation creation changed the application content instance")
    creates = {cell.id: cell for cell in (*prepared.create, *binding_patch.create)}
    if len(creates) != len(prepared.create) + len(binding_patch.create):
        raise InvalidCell("conversation creation patch identity collision")
    replacements = {}
    for cell in binding_patch.replace:
        if cell.id in creates:
            creates[cell.id] = cell
        else:
            replacements[cell.id] = cell
    membership = prepare_append_relation_members(snapshot, registry.workshop_workbench_root,
        ((registry.roles["scope"], root), (registry.roles["member"], root)), budget=WORKBENCH_BUDGET)
    for cell in membership.create:
        if cell.id in creates:
            raise InvalidCell("conversation creation patch identity collision")
        creates[cell.id] = cell
    for cell in membership.replace:
        if cell.id in replacements and replacements[cell.id] != cell:
            raise InvalidCell("conversation creation patch conflict")
        replacements[cell.id] = cell
    candidate = overlay_read_snapshot(snapshot, create=tuple(creates.values()), replace=tuple(replacements.values()))
    if root not in _registered(candidate, registry):
        raise InvalidCell("prepared conversation is not registered")
    validate_workshop_conversation_scope(candidate, protocol,
        application_root=registry.application_root, canonical_root=registry.workshop_root, root=root)
    service._authorize_content_read(candidate, registry, space_root=root,
        authentication_context=context, principal=creator, machine=False)
    return tuple(creates.values()), tuple(replacements.values()), candidate


def list_workshop_conversations(owner, *, authentication_context, expected_revision, limit=50,
                                after=None, read_guard=None):
    _revision(expected_revision)
    if type(limit) is not int or not 1 <= limit <= MAX_CONVERSATIONS:
        raise InvalidCell("conversation catalog limit must be 1 to 50")
    if read_guard is not None and not callable(read_guard):
        raise InvalidCell("conversation catalog read guard must be a trusted callable")
    with owner.mutation_lock:
        service = _service(owner)
        registry, store = owner.universal_registry, owner.universal_store
        with registry.authorization.broker.live_context(authentication_context):
            with store.stable_snapshot(expected_revision=expected_revision) as snapshot:
                principal = _admit(snapshot, registry, authentication_context)
                if read_guard is not None:
                    read_guard()
                page = _scope_page(_registered(snapshot, registry), after, limit)
                rows = []
                for root in page["roots"]:
                    row = _row(snapshot, registry, root)
                    if root != registry.workshop_root and principal not in row["participant_roots"]:
                        continue
                    validate_workshop_conversation_scope(snapshot, registry.deliberation_protocol,
                        application_root=registry.application_root, canonical_root=registry.workshop_root, root=root)
                    try:
                        binding = service._authorize_content_read(snapshot, registry,
                            space_root=root, authentication_context=authentication_context,
                            principal=principal, machine=principal != registry.authorization.subject_root)
                    except AuthorizationDenied:
                        continue
                    history = service._history_for(binding)
                    history.conversation_head(root)  # A dangling graph binding is not a usable chat.
                    rows.append(row)
                registry.authorization.broker.resolve(authentication_context)
                if read_guard is not None:
                    read_guard()
                return {"graph_id": registry.application_root, "workbench_root": registry.workshop_workbench_root,
                    "revision": snapshot.revision, "conversations": rows,
                    "has_more": page["has_more"], "next_after": page["next_after"]}


def create_workshop_conversation(owner, *, authentication_context, expected_revision,
                                title, participant_roots, idempotency_key, before_commit=None):
    _revision(expected_revision)
    title, participants = _input(title, participant_roots, idempotency_key)
    if before_commit is not None and not callable(before_commit):
        raise InvalidCell("conversation creation guard must be a trusted callable")
    with owner.mutation_lock:
        service = _service(owner)
        registry, store = owner.universal_registry, owner.universal_store
        authority, protocol = registry.authorization, registry.deliberation_protocol
        with authority.broker.live_context(authentication_context):
            with store.stable_snapshot(expected_revision=expected_revision) as snapshot:
                creator = _admit(snapshot, registry, authentication_context, create=True)
                roots = _registered(snapshot, registry)
                canonical = read_deliberation_space(snapshot, protocol, registry.workshop_root,
                                                   budget=CONTROL_BUDGET)
                canonical_binding = service._authorize_content_read(snapshot, registry,
                    space_root=registry.workshop_root, authentication_context=authentication_context,
                    principal=creator, machine=False)
                if creator not in participants or set(participants) - set(canonical.participant_roots):
                    raise AuthorizationDenied("conversation participant is not admitted by the general Workshop")
                controls, requirements = _controls(snapshot, protocol, canonical)
                namespace = _digest([canonical_binding.instance_id, registry.application_root,
                    registry.workshop_workbench_root, creator, idempotency_key])
                prefix = "app:workshop:conversation:" + namespace + ":"
                intent = _digest([title, participants, controls])
                root = prefix + intent
                binding_root = "conversation-content:" + _digest([root, "binding"])[:32]
                history = service._history_for(canonical_binding)
                pending = None if root in snapshot.cells else _prepare_child(snapshot, registry, service,
                    root=root, title=title, participants=participants, controls=controls,
                    requirements=requirements, binding_root=binding_root,
                    instance_id=canonical_binding.instance_id, context=authentication_context, creator=creator)

                def guard():
                    _service(owner)
                    if store.revision != expected_revision:
                        raise AuthorizationDenied("Workshop changed before conversation publication; refresh")
                    _admit(snapshot, registry, authentication_context, create=True)
                    if before_commit is not None:
                        before_commit()

                guard()

                # Binary primary-key range over at most two ordinary identities.
                # The trailing ':' is replaced by ';' for an exclusive upper bound.
                with history._transaction(write=True, before_commit=guard):
                    reservations = history._db.execute(
                        "SELECT id,last_sequence FROM conversations WHERE id>=? COLLATE BINARY "
                        "AND id<? COLLATE BINARY ORDER BY id COLLATE BINARY LIMIT 2",
                        (prefix, prefix[:-1] + ";")).fetchall()
                    if len(reservations) > 1 or reservations and reservations[0]["id"] != root:
                        raise InvalidCell("conversation creation idempotency intent changed")
                    if root in snapshot.cells:
                        if root not in roots or not reservations:
                            raise InvalidCell("conversation creation identity is not a registered conversation")
                        current = read_deliberation_space(snapshot, protocol, root, budget=CONTROL_BUDGET)
                        current_binding = read_content_binding(snapshot, protocol,
                            application_root=registry.application_root, space_root=root)
                        current_controls, _requirements = _controls(snapshot, protocol, current)
                        if (current.title != title or current.participant_roots != participants
                                or current_controls != controls or current_binding.root_id != binding_root
                                or current_binding.instance_id != canonical_binding.instance_id):
                            raise InvalidCell("committed conversation creation intent changed")
                        service._authorize_content_read(snapshot, registry, space_root=root,
                            authentication_context=authentication_context, principal=creator, machine=False)
                        return {"created": False, "revision": snapshot.revision, **_row(snapshot, registry, root)}
                    if reservations:
                        status = history._retention_status(root)
                        if (reservations[0]["last_sequence"] != 0 or status["activity_basis"] != "unknown"
                                or status["activity_revision"] != 0 or status["archive_revision"] != 0
                                or status["content_generation"] != 0 or status["purged_messages"] != 0
                                or history._db.execute("SELECT 1 FROM messages WHERE conversation_id=? LIMIT 1",
                                                       (root,)).fetchone() is not None):
                            raise InvalidCell("unpublished conversation reservation is not empty and protected")
                    else:
                        history._db.execute("INSERT INTO conversations(id) VALUES(?)", (root,))

                creates, replacements, candidate = pending
                guard()
            # Graph commits cannot run inside stable_snapshot. The exact revision
            # and live context are rechecked by the existing authenticated broker.
            revision = authority.broker.commit_authenticated(authentication_context, store,
                expected_revision, create=creates, replace=replacements)
            return {"created": True, "revision": revision, **_row(candidate, registry, root)}
