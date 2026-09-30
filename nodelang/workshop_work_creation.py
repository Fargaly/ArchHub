"""Create native Workshop Work with its existing scope port bound to the room, and
assign it to an agent already running in that room.

Assigning (assign_browser_workshop_work) is the founder's own gesture in his
browser: the same founder browser binding, Workshop admission, room membership,
route revalidation and revision check as creation, then the existing
assign_universal_workshop_work with the browser's own authentication context. It
never builds a direct machine request, launches or enrols a session, or grants
anything: the agent still needs its own claim and root-bound permits to act.
"""
import math
import time

from .cell_authorization import AuthorizationDenied
from .conversation_content import read_content_binding
from .existing_workshop_conversation import _admit
from .universal_cell import InvalidCell


def _work_scope(snapshot, registry, work_root):
    from .universal_application import _governed_work_interface_target
    try:
        return _governed_work_interface_target(snapshot, registry, work_root, 'scope')
    except (InvalidCell, KeyError):
        return None


def _work_external_key(snapshot, registry, work_root):
    from .universal_application import _governed_work_interface, _text
    try:
        interface = _governed_work_interface(snapshot, registry, work_root, 'external-key')
    except (InvalidCell, KeyError):
        return None
    value = interface.get('value')
    return value if type(value) is str else _text(snapshot, interface['target'])


def _registered_work(snapshot, registry):
    from .universal_application import read_relation
    return [member.participant_id for member in read_relation(
                snapshot, registry.governed_work_registry_root, budget=100_000)
            if member.role_id == registry.roles['member']]


def existing_work_for_key(snapshot, registry, *, workshop_root, external_key):
    """The Work already in this Workshop scope under `external_key`, or None.

    Founder decision 3: the same key names the same Work, so creation returns it
    instead of making a second one; a second Work needs a different key. The
    default key 'unset' is not an identity and never reconciles.
    """
    if type(external_key) is not str or not external_key or external_key == 'unset':
        return None
    matches = [root for root in _registered_work(snapshot, registry)
               if _work_scope(snapshot, registry, root) == workshop_root
               and _work_external_key(snapshot, registry, root) == external_key]
    if len(matches) > 1:
        raise InvalidCell('Two Works in this Workshop share one external key; resolve them before creating another')
    return matches[0] if matches else None


def create_browser_workshop_work(owner, binding, body, *, browser_guard):
    from .universal_application import (create_universal_governed_work,
        _governed_work_interface_target, project_universal_governed_work_status)

    required = {'workshop_root', 'workshop_scope', 'revision'}
    allowed = required | {'title', 'description', 'priority', 'external_key', 'references',
        'structured_references', 'x', 'y', 'projection'}
    if (type(body) is not dict or not required <= set(body) or set(body) - allowed
            or type(body['revision']) is not int or not 0 <= body['revision'] < 2**63
            or not callable(browser_guard)):
        raise InvalidCell('Workshop Work requires an exact conversation, canvas scope and revision')
    root, scope = body['workshop_root'], body['workshop_scope']
    if any(type(value) is not str or not value for value in (root, scope)):
        raise InvalidCell('Workshop Work conversation and canvas scope must be exact roots')
    references = body.get('references', {})
    structured = body.get('structured_references', {})
    if type(references) is not dict or type(structured) is not dict:
        raise InvalidCell('Workshop Work references must be declared mappings')
    if set(references) - {'scope'}:
        raise InvalidCell('Existing Work input nodes require an admitted graph connection')
    if 'scope' in structured or 'scope' in references and references['scope'] != root:
        raise InvalidCell('Workshop Work contains a competing conversation scope')
    for key in ('x', 'y'):
        value = body.get(key, 0.0)
        if type(value) not in (int, float) or not math.isfinite(value):
            raise InvalidCell('Workshop Work requires finite canvas positions')
    if 'projection' in body and type(body['projection']) is not bool:
        raise InvalidCell('Workshop Work projection flag must be boolean')
    store, registry = owner.universal_store, owner.universal_registry
    authority, service = registry.authorization, owner.conversation_content
    with owner.mutation_lock, authority.broker.live_context(binding.context):
        def admitted():
            browser_guard()
            service._require_live_owner()
            if not service.belongs_to(store, registry):
                raise AuthorizationDenied('Workshop conversation owner changed')
            # Native project execution currently admits the canonical Workshop.
            # Child-room execution must be implemented before this is broadened.
            snapshot, room = _admit(owner, binding, root, scope)
            if binding.subject_root not in room.participant_roots:
                raise AuthorizationDenied('Workshop Work requires current conversation membership')
            authority.broker.resolve(binding.context)
            content = read_content_binding(snapshot, registry.deliberation_protocol,
                application_root=registry.application_root, space_root=root)
            service._authorize_content_read(snapshot, registry, space_root=root,
                authentication_context=binding.context, principal=binding.subject_root, machine=False)
            return snapshot, content

        snapshot, content = admitted()
        existing = existing_work_for_key(snapshot, registry, workshop_root=root,
                                         external_key=body.get('external_key', 'unset'))
        if existing is not None:
            # Reconcile before create: the same key returns the Work it names.
            result = {'ok':True, 'created_root':existing, 'existing':True, 'revision':snapshot.revision,
                'workshop_root':root, 'workshop_scope':scope}
            if body.get('projection', True):
                result.update(project_universal_governed_work_status(store, registry,
                    authentication_context=binding.context))
            return result
        if snapshot.revision != body['revision']:
            raise InvalidCell('Workshop changed before Work creation; refresh its canvas')
        created, wire, revision = create_universal_governed_work(store, registry,
            title=body.get('title', ''), description=body.get('description', ''),
            priority=body.get('priority', 0), external_key=body.get('external_key', 'unset'),
            references={**references, 'scope':root}, structured_references=structured,
            x=float(body['x']) if body.get('x') is not None else None,
            y=float(body['y']) if body.get('y') is not None else None,
            compact_references=True, select_created=False, authentication_context=binding.context)
        current, current_content = admitted()
        if (current_content != content or current.revision != revision or
                _governed_work_interface_target(current, registry, created, 'scope') != root):
            raise InvalidCell('Created Work conversation link could not be confirmed; inspect its graph before retrying')
        result = {'ok':True, 'created_root':created, 'existing':False, 'membership_wire':wire,
            'revision':revision, 'workshop_root':root, 'workshop_scope':scope}
        if body.get('projection', True):
            result.update(project_universal_governed_work_status(store, registry,
                authentication_context=binding.context))
        return result


ASSIGNMENT_PREFIX = 'app:workshop-assignment:'
RUNTIME_SESSION_PREFIX = 'app:agent-session:runtime:'


def live_agent_binding(owner, session):
    """The agent's machine binding and last authenticated request, read NOW.

    Neither lock is ever held while the graph or mutation lock is taken
    (application_server takes them briefly and alone), so reading them under
    the mutation lock keeps a single lock order. Returns (binding, seen): the
    exact binding object the pipe holds for this session (None once revoked or
    closed) and the time of its last authenticated request.
    """
    with owner._machine_agent_session_lock:
        binding = owner._machine_agent_sessions.get(session)
    with owner._machine_agent_observation_lock:
        seen = owner._machine_agent_observations.get(session)
    return binding, seen


def require_live_agent(owner, snapshot, session, captured, now):
    """Refuse unless the agent is connected now, on the same binding the request saw.

    The rail row a page drew is only how a candidate was offered; it is never
    authority. At commit: the pipe still holds the SAME binding object that was
    captured before the lock (a disconnect, revocation or re-bind replaces or
    drops it), its capability has not expired, an authenticated request was
    seen within the presence lease, and, for a device-proof session, its device
    custody is still active in the graph.
    """
    from .application_server import RUNTIME_PRESENCE_LEASE_SECONDS
    binding, seen = live_agent_binding(owner, session)
    if binding is None or binding is not captured:
        raise AuthorizationDenied('This agent\'s connection changed or was revoked; nothing was assigned')
    capability = binding.get('expires_at', 0)
    if (type(capability) not in (int, float) or not math.isfinite(capability) or capability <= now
            or type(seen) not in (int, float) or not seen <= now < seen + RUNTIME_PRESENCE_LEASE_SECONDS):
        raise AuthorizationDenied('This agent has no live verified connection now; nothing was assigned')
    custody = binding.get('device_custody')
    if custody is not None:
        from .cell_device_custody import read_device_custody
        registry = owner.universal_registry
        held = read_device_custody(snapshot, registry.device_custody_protocol, custody)
        if held.state_root != registry.device_custody_protocol.states['active']:
            raise AuthorizationDenied('This agent\'s device custody is revoked; nothing was assigned')


class WorkshopAssignmentRefused(InvalidCell):
    """A refusal raised BEFORE the assignment commit: nothing was written, and it is
    a refusal of exactly this assignment id (the browser may clear its retry)."""

    def __init__(self, message, assignment, status=400):
        super().__init__(message)
        self.assignment = assignment
        self.status = status
        # Raised only after the exact id was read ABSENT under the mutation lock (every
        # commit holds that lock), so this refusal also reconciles that id as absent.
        self.reconciled_absent = True


def assign_browser_workshop_work(owner, binding, body, *, browser_guard):
    """The founder assigns one Work in this Workshop to one agent already running in it.

    Body {workshop_root, workshop_scope, revision, work, agent_session, assignment_id}.
    Admission is creation's (founder browser binding, Workshop admission, room
    membership, route revalidation right before commit, current revision). Then,
    under the mutation lock: the Work is registered in this scope and not
    complete; the agent is a participant of this room and active; its live
    binding is re-read now and must be the same binding captured before the lock,
    unexpired, seen within the presence lease, with active device custody
    (require_live_agent -- what a page showed is never authority); and the Work
    has no other active assignee (founder decision 4). Only then the existing
    assign_universal_workshop_work runs with this browser's context. It is
    idempotent on assignment_id and grants nothing.
    """
    from .universal_application import (assign_universal_workshop_work, _read_workshop_assignment,
        _workshop_assignment_roots)

    fields = {'workshop_root', 'workshop_scope', 'revision', 'work', 'agent_session', 'assignment_id'}
    if (type(body) is not dict or set(body) != fields or type(body['revision']) is not int
            or not 0 <= body['revision'] < 2**63 or not callable(browser_guard)):
        raise InvalidCell('Workshop assignment requires an exact conversation, canvas scope, revision, '
                          'Work, agent and assignment id')
    root, scope, work, session, assignment = (body['workshop_root'], body['workshop_scope'], body['work'],
                                              body['agent_session'], body['assignment_id'])
    if any(type(value) is not str or not value for value in (root, scope, work, session, assignment)):
        raise InvalidCell('Workshop assignment identities must be exact roots')
    if not assignment.startswith(ASSIGNMENT_PREFIX) or not session.startswith(RUNTIME_SESSION_PREFIX):
        raise InvalidCell('Workshop assignment names an assignment and a running agent session')
    store, registry = owner.universal_store, owner.universal_registry
    authority, service = registry.authorization, owner.conversation_content
    # The binding object the pipe holds for this agent, captured before the lock; the
    # commit requires that very object, still live (require_live_agent).
    try:
        captured, _seen = live_agent_binding(owner, session)
        capture_refusal = None
    except (AuthorizationDenied, InvalidCell) as refusal:
        captured, capture_refusal = None, refusal
    with owner.mutation_lock, authority.broker.live_context(binding.context):
        # Reconcile first: an earlier attempt with this exact id may have committed and
        # lost its reply. Under the lock (every commit holds it) the id is either held
        # -- report it, whatever admission says now -- or absent, in which case any
        # refusal below proves this id was never committed.
        browser_guard()
        if assignment in _workshop_assignment_roots(store.snapshot(), registry):
            held = _read_workshop_assignment(store.snapshot(), registry, assignment)
            if held.work_root != work or held.agent_session_root != session:
                raise InvalidCell('This assignment id already names another Work or agent')
            return {'ok':True, 'assignment':held.root_id, 'work':held.work_root,
                    'agent_session':held.agent_session_root, 'obligation':held.obligation_root,
                    'existing':True, 'reconciled':True, 'revision':store.revision,
                    'workshop_root':root, 'workshop_scope':scope}
        # Everything up to assign_universal_workshop_work is a check: a refusal here
        # committed nothing, so it is reported as a refusal OF THIS assignment id.
        try:
            if capture_refusal is not None:
                raise capture_refusal
            def admitted():
                browser_guard()
                service._require_live_owner()
                if not service.belongs_to(store, registry):
                    raise AuthorizationDenied('Workshop conversation owner changed')
                snapshot, room = _admit(owner, binding, root, scope)
                if binding.subject_root not in room.participant_roots:
                    raise AuthorizationDenied('Workshop assignment requires current conversation membership')
                if binding.subject_root != authority.subject_root:
                    raise AuthorizationDenied('Only the founder assigns Workshop Work')
                authority.broker.resolve(binding.context)
                return snapshot, room

            snapshot, room = admitted()
            existing = None
            if assignment in _workshop_assignment_roots(snapshot, registry):
                existing = _read_workshop_assignment(snapshot, registry, assignment)
            if existing is None and snapshot.revision != body['revision']:
                raise InvalidCell('Workshop changed before assignment; refresh its canvas')
            if work not in _registered_work(snapshot, registry) or _work_scope(snapshot, registry, work) != root:
                raise InvalidCell('This Work is not in this Workshop')
            if session not in room.participant_roots:
                raise AuthorizationDenied('Only an agent attached to this Workshop can be assigned')
            if existing is None:
                for other in _workshop_assignment_roots(snapshot, registry):
                    held = _read_workshop_assignment(snapshot, registry, other)
                    if held.work_root == work and held.agent_session_root != session:
                        raise InvalidCell('This Work already has an active assignee; cancel that assignment first')
            current, _room = admitted()         # the route and the browser, again, right before commit
            if existing is None:
                require_live_agent(owner, current, session, captured, time.time())
        except (AuthorizationDenied, InvalidCell) as refusal:
            raise WorkshopAssignmentRefused(str(refusal), assignment,
            403 if isinstance(refusal, AuthorizationDenied) else 400) from refusal
        projection = assign_universal_workshop_work(store, registry, assignment_id=assignment, work_root=work,
            agent_session_root=session, authentication_context=binding.context)
        return {'ok':True, 'assignment':projection.root_id, 'work':projection.work_root,
                'agent_session':projection.agent_session_root, 'obligation':projection.obligation_root,
                'existing':existing is not None, 'revision':store.revision,
                'workshop_root':root, 'workshop_scope':scope}


def workshop_assignment_rows(owner, snapshot, root):
    """The active assignments of Work in this Workshop room, for its read projection."""
    from .universal_application import _read_workshop_assignment, _workshop_assignment_roots
    registry = owner.universal_registry
    rows = []
    for assignment in _workshop_assignment_roots(snapshot, registry):
        held = _read_workshop_assignment(snapshot, registry, assignment)
        if _work_scope(snapshot, registry, held.work_root) == root:
            rows.append({'assignment': held.root_id, 'work': held.work_root,
                         'agent_session': held.agent_session_root})
    return sorted(rows, key=lambda row: row['assignment'])
