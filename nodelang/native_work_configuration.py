"""Native draft editing adapter to the one Work configuration implementation."""
import json
import re
from contextlib import contextmanager

from .cell_authorization import AuthorizationDenied
from .cell_protocols import read_relation
from .universal_cell import InvalidCell

PATH = '/api/universal/work-configuration'


@contextmanager
def _unknown_after_write(owner):
    from .application_machine_transport import MachineEffectOutcomeUnknown
    revision = owner.universal_store.revision
    try:
        yield
    except Exception as exc:
        if owner.universal_store.revision != revision:
            raise MachineEffectOutcomeUnknown('Native Work draft changed before its response failed; reconcile') from exc
        raise


def dispatch(owner, request, context, *, read=False):
    from . import universal_application as app
    from .existing_workshop_project_revision import (
        stage_work_interfaces_for_context, read_work_configuration_for_context)
    from .cell_value_graph import read_value_graph
    from .workshop_project_revision import requirements_digest

    body = request['body']
    expected = {'projection', 'work_root'} if read else {
        'phase', 'work_root', 'revision_id', 'expected_revision', 'purpose', 'fields'}
    if (set(body) not in (expected, expected | {'revision_id'} if read else expected)
            or type(body.get('work_root')) is not str
            or not body['work_root'].startswith('assembly-instance:')
            or len(body['work_root'].encode()) > 512
            or len(json.dumps(body, allow_nan=False).encode()) > 65536):
        raise InvalidCell('Native Work configuration request is invalid')
    if not read and (type(body['phase']) is not str or body['phase'] not in {'stage', 'reconcile'}
            or type(body['purpose']) is not str or body['purpose'] not in {'general','artifact-publication'}
            or type(body['revision_id']) is not str
            or not re.fullmatch('[a-f0-9]{32}', body['revision_id'])
            or type(body['expected_revision']) is not int or body['expected_revision'] < 0
            or type(body['fields']) is not dict or not body['fields']
            or set(body['fields']) - {'inputs', 'requirements', 'cde-container'}):
        raise InvalidCell('Native Work configuration proposal is invalid')
    if not read:
        for entry in body['fields'].values():
            if (type(entry) is not dict or set(entry) != {'expected_target','expected_digest','value'}
                    or type(entry['expected_target']) is not str or not entry['expected_target']
                    or (entry['expected_digest'] is not None and (type(entry['expected_digest']) is not str
                        or re.fullmatch('[a-f0-9]{64}',entry['expected_digest']) is None))):
                raise InvalidCell('Native Work configuration field is invalid')
    if read and 'revision_id' in body and (type(body['revision_id']) is not str
            or not re.fullmatch('[a-f0-9]{32}', body['revision_id'])):
        raise InvalidCell('Native Work draft identity is invalid')
    registry, store, work = owner.universal_registry, owner.universal_store, body['work_root']
    actor = owner._resolve_universal_machine_agent_session(request)
    view, actual_context = app._view_session_for_context(registry, context)

    def admit():
        if owner.universal_checkpoint_guard is not None:
            owner.universal_checkpoint_guard.require_healthy()
        owner.require_universal_http_route(request['method'], request['path'], authentication_context=actual_context)
        if owner._resolve_universal_machine_agent_session(request) != actor:
            raise AuthorizationDenied('Native Work configuration caller changed')
        actual_view, _ = app._view_session_for_context(registry, actual_context)
        if actual_view != view:
            raise AuthorizationDenied('Native Work configuration view changed')
        snapshot = store.snapshot()
        if not any(row.role_id == registry.roles['member'] and row.participant_id == work
                   for row in read_relation(snapshot, registry.governed_work_registry_root, budget=100000)):
            raise AuthorizationDenied('Native Work configuration requires registered Work')
        visible, _, _, trail = app._session_canvas_roots(snapshot, registry, view,
            include_trail=True, authority_snapshot=app._cached_authority_snapshot(snapshot, registry.authorization))
        if work not in visible or not trail:
            raise AuthorizationDenied('Native Work configuration is outside the current canvas')
        assignments = [app._read_workshop_assignment(snapshot,registry,root)
            for root in app._workshop_assignment_roots(snapshot,registry)]
        selected = [row for row in assignments if row.work_root == work]
        if selected:
            admitted = any(row.agent_session_root == actor for row in selected)
        else:
            machine = app.read_instance_state_machine(snapshot,registry.assembly_protocol,
                registry.standard_library.state_machine_protocol,work)
            history = app.machine_history(snapshot,registry.standard_library.state_machine_protocol,machine.root_id)
            latest = next((event for event in reversed(history)
                if app._text(snapshot,event.event_root).casefold() == 'claim'),None)
            bindings = app._governed_work_claim_binding_roots(snapshot,registry)
            roots = [root for root in latest.context_roots if root in bindings] if latest else []
            bound = app._read_governed_work_claim_binding(snapshot,registry,roots[0]) if len(roots)==1 else None
            admitted = (bound is not None and bound['work']==work and bound['session']==actor
                and bound['transition']==latest.event_root)
        if not admitted:
            raise AuthorizationDenied('Native Work configuration requires this actor assignment or latest claim')
        app._require_application_authorization(snapshot, registry, 'read' if read else 'edit', work,
            authentication_context=actual_context)
        return snapshot, trail[-1]

    with owner.mutation_lock, registry.authorization.broker.live_context(actual_context), _unknown_after_write(owner):
        snapshot, scope = admit()
        if read:
            value = read_work_configuration_for_context(owner, actual_context,
                view_root=view.root_id, scope=scope, work=work)
            result = {'projection':'selected-configuration', 'agent_session':actor,
                'work':{'root':work, 'configuration':value}, 'revision':snapshot.revision}
            if 'revision_id' in body:
                draft_root = work + ':work-configuration:' + body['revision_id']
                saved = read_value_graph(snapshot, registry.value_graph_protocol, draft_root)
                subject = registry.authorization.broker.resolve(actual_context).subject_root
                if (type(saved) is not dict or saved.get('proposing_actor') != actor
                        or saved.get('owner') != subject or saved.get('view') != view.root_id
                        or saved.get('scope') != scope or saved.get('work') != work
                        or saved.get('revision_id') != body['revision_id']):
                    raise AuthorizationDenied('Native Work draft belongs to different custody')
                values = {name:read_value_graph(snapshot, registry.value_graph_protocol, target)
                    for name,target in saved['revised_roots'].items()}
                if requirements_digest(values) != saved['input_digest']:
                    raise InvalidCell('Native Work draft values changed')
                result['draft'] = {'record':draft_root, 'revision_id':body['revision_id'],
                    'purpose':saved['purpose'], 'values':values, 'expected':saved['expected'],
                    'expected_revision':saved['read_revision'], 'execution_authorized':False}
        elif body['phase'] == 'stage':
            value = stage_work_interfaces_for_context(owner, actual_context,
                view_root=view.root_id, root=registry.workshop_root, scope=scope, work=work,
                revision_id=body['revision_id'], expected_revision=body['expected_revision'],
                purpose=body['purpose'], fields=body['fields'], proposing_actor=actor,
                before_binding_commit=admit)
            result = {'projection':'configuration-result', 'agent_session':actor, 'work_root':work,
                'revision_id':body['revision_id'], 'configuration':value, 'revision':store.revision,
                'execution_authorized':False}
        else:
            # Read exact existing completion evidence; never invoke apply again.
            root = work + ':work-configuration:' + body['revision_id']
            applied = False
            staged = False
            conflict = False
            proposal = None
            if root in snapshot.cells:
                saved = read_value_graph(snapshot, registry.value_graph_protocol, root)
                if (type(saved) is not dict or type(saved.get('revised_roots')) is not dict
                        or type(saved.get('expected')) is not dict
                        or type(saved.get('input_digest')) is not str):
                    raise InvalidCell('Native Work configuration saved record is malformed')
                fields = body['fields']
                proposed = {name:entry['value'] for name, entry in fields.items()}
                expected_fields = {name:{'target':entry['expected_target'],
                    'digest':entry['expected_digest'] or ''} for name,entry in fields.items()}
                subject = registry.authorization.broker.resolve(actual_context).subject_root
                if (saved.get('work') != work or saved.get('revision_id') != body['revision_id']
                        or saved.get('owner') != subject or saved.get('proposing_actor') != actor
                        or saved.get('view') != view.root_id
                        or saved.get('scope') != scope or saved.get('workshop') != registry.workshop_root
                        or saved.get('read_revision') != body['expected_revision']
                        or saved.get('purpose') != body['purpose'] or saved.get('expected') != expected_fields
                        or saved.get('input_digest') != requirements_digest(proposed)):
                    conflict = True
                if not conflict:
                    for name,value in proposed.items():
                        if read_value_graph(snapshot, registry.value_graph_protocol, root + ':data:' + name) != value:
                            raise InvalidCell('Native Work configuration saved values changed')
                    staged = True
                    proposal = {'record':root,'purpose':saved['purpose'],'fields':body['fields'],
                        'expected_revision':saved['read_revision'],'revision_id':body['revision_id']}
                    if root + ':applied' in snapshot.cells:
                        identity = {key:value for key,value in saved.items() if key != 'previous_roots'}
                        applied = read_value_graph(snapshot, registry.value_graph_protocol, root + ':applied') == {
                            **identity, 'state':'applied', 'authorization_root':root + ':authorization'}
                        if not applied:
                            raise InvalidCell('Native Work configuration completion evidence changed')
            result = {'projection':'configuration-recovery', 'agent_session':actor, 'work_root':work,
                'revision_id':body['revision_id'], 'staged':staged, 'applied':applied,
                'not_staged':conflict or (not staged and snapshot.revision != body['expected_revision']),
                'conflict':conflict,
                'proposal':proposal, 'revision':snapshot.revision,
                'receipt_reconstructed':False, 'execution_authorized':False}
        admit()
        if store.revision != result['revision']:
            raise InvalidCell('Native Work configuration changed during projection')
        if len(json.dumps(result, allow_nan=False).encode()) > 65536:
            raise InvalidCell('Native Work configuration result exceeds its bound')
        return result
