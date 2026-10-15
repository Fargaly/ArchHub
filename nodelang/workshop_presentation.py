"""Workshop presentation preferences in the existing governed Cell store.

The key is application + authenticated account, never a device or browser session.
The existing tracked editor writer supplies authorization, history and undo.
"""
import hashlib
import json

from .cell_authorization import AuthorizationDenied
from .cell_protocols import prepare_append_relation_members, read_relation
from .existing_workshop_conversation import _admit
from .universal_cell import Cell, InvalidCell


ACTIONS = frozenset(('presentation-read', 'presentation-layout'))


def presentation_root(application, subject):
    identity = json.dumps([application, subject], separators=(',', ':'))
    return 'app:workshop-presentation:' + hashlib.sha256(identity.encode()).hexdigest()


def read_layout(snapshot, application, subject, settings_root, member_role):
    cell = snapshot.cells.get(presentation_root(application, subject))
    if cell is None:
        return 1
    try:
        value = json.loads(cell.atom)
    except (ValueError, UnicodeError) as exc:
        raise InvalidCell('Workshop layout preference is unreadable') from exc
    if (cell.link0 != application or cell.link1 != subject or
            type(value) is not dict or set(value) != {'version', 'layout'} or
            type(value['version']) is not int or value['version'] != 1 or type(value['layout']) is not int or value['layout'] not in (1, 2, 4)):
        raise InvalidCell('Workshop layout preference has a foreign or invalid binding')
    # Created Cells remain in the append-only store after compensation. The
    # continuing account settings relation is the live preference authority.
    if not any(row.role_id == member_role and row.participant_id == cell.id
               for row in read_relation(snapshot, settings_root, budget=100_000)):
        return 1
    return value['layout']


def perform_presentation_action(owner, binding, body, *, browser_guard):
    fields = {'action', 'root', 'scope', 'revision'}
    if type(body) is not dict or body.get('action') not in ACTIONS:
        raise InvalidCell('Workshop presentation action is invalid')
    writing = body['action'] == 'presentation-layout'
    if set(body) != fields | ({'layout'} if writing else set()):
        raise InvalidCell('Workshop presentation fields are invalid')
    if type(body['revision']) is not int or body['revision'] < 0:
        raise InvalidCell('Workshop presentation revision is invalid')
    if writing and (type(body['layout']) is not int or body['layout'] not in (1, 2, 4)):
        raise InvalidCell('Choose a Workshop layout of 1, 2 or 4')
    store, registry = owner.universal_store, owner.universal_registry
    with owner.mutation_lock:
        with registry.authorization.broker.live_context(binding.context):
            browser_guard()
            snapshot, _ = _admit(owner, binding, body['root'], body['scope'], allow_child=True)
            if body['revision'] > snapshot.revision or writing and body['revision'] != snapshot.revision:
                raise InvalidCell('Workshop presentation changed; refresh before saving')
            subject = registry.authorization.broker.resolve(binding.context).subject_root
            if subject != binding.subject_root:
                raise AuthorizationDenied('Workshop presentation account changed')
            from .universal_application import _view_session_for_context, _commit_universal_user_change
            view, context = _view_session_for_context(registry, binding.context)
            layout = read_layout(snapshot, registry.application_root, subject, view.settings_root, registry.roles['member'])
            if writing and layout != body['layout']:
                cell = Cell(presentation_root(registry.application_root, subject), registry.application_root,
                    subject, json.dumps({'version': 1, 'layout': body['layout']}, separators=(',', ':')).encode())
                attached = any(row.role_id == registry.roles['member'] and row.participant_id == cell.id
                    for row in read_relation(snapshot, view.settings_root, budget=100_000))
                membership = prepare_append_relation_members(snapshot,view.settings_root,
                    () if attached else ((registry.roles['member'],cell.id),),budget=100_000)
                browser_guard()
                _commit_universal_user_change(store, registry, view, context, snapshot,
                    route='/api/universal/workshop', command_name='catalog.configure',
                    authorization_scope_root=body['root'],
                    create=(*membership.create,*(() if cell.id in snapshot.cells else (cell,))),
                    replace=(*membership.replace,*((cell,) if cell.id in snapshot.cells else ())))
                layout = body['layout']
            return {'ok': True, 'graph_id': registry.application_root, 'subject': subject,
                'root': body['root'], 'scope_root': body['scope'], 'revision': store.revision, 'layout': layout}
