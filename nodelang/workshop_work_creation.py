"""Create native Workshop Work with its existing scope port bound to the room."""
import math

from .cell_authorization import AuthorizationDenied
from .conversation_content import read_content_binding
from .existing_workshop_conversation import _admit
from .universal_cell import InvalidCell


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
        if snapshot.revision != body['revision']:
            raise InvalidCell('Workshop changed before Work creation; refresh its canvas')
        created, wire, revision = create_universal_governed_work(store, registry,
            title=body.get('title', ''), description=body.get('description', ''),
            priority=body.get('priority', 0), external_key=body.get('external_key', 'unset'),
            references={**references, 'scope':root}, structured_references=structured,
            x=float(body.get('x', 0.0)), y=float(body.get('y', 0.0)),
            compact_references=True, select_created=False, authentication_context=binding.context)
        current, current_content = admitted()
        if (current_content != content or current.revision != revision or
                _governed_work_interface_target(current, registry, created, 'scope') != root):
            raise InvalidCell('Created Work conversation link could not be confirmed; inspect its graph before retrying')
        result = {'ok':True, 'created_root':created, 'membership_wire':wire, 'revision':revision,
            'workshop_root':root, 'workshop_scope':scope}
        if body.get('projection', True):
            result.update(project_universal_governed_work_status(store, registry,
                authentication_context=binding.context))
        return result
