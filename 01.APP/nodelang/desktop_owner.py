"""Source-bound desktop plans and completed-schedule reviews in the existing graph."""
import json
from types import SimpleNamespace

from .canvas_graph_owner import CanvasOwner
from .cell_protocols import prepare_append_relation_members
from .universal_cell import Cell, InvalidCell
from .watcher_owner import WatcherOwner, _digest, SCALE_MM

PREFIX = 'app:desktop-proposal:'


class DesktopOwner:
    def __init__(self, api):
        self.api = api
        self.root = api.root + ':desktop:' + _digest([api.scope, api.binding.subject_root])
        self.ops = CanvasOwner(api.owner.universal_store, api.owner.universal_registry, api.binding.context)

    def _node(self, create=False):
        from .universal_pipeline import create_engine_node
        self.api.admit()
        found = [n['id'] for n in self.ops.canvas()['nodes']
                 if self.ops._rows(None, n['id']).get('desktop_owner', {}).get('value') == self.root]
        if len(found) > 1:
            raise InvalidCell('Reconcile the duplicate desktop owner nodes')
        if found:
            return found[0]
        if create:
            self.api.guard()
            return create_engine_node(self.api.owner.universal_store, self.api.owner.universal_registry,
                title='Desktop automation', engine='note', properties={'desktop_owner':self.root},
                authentication_context=self.api.binding.context)['root']
        return None

    def _read(self, root):
        cell = self.api.admit().cells.get(root)
        return json.loads(cell.atom) if cell else None

    def _save(self, root, value):
        from . import universal_application as app
        api = self.api
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        if len(raw) > 65536:
            raise InvalidCell('Desktop record exceeds 64 KiB; existing content is unchanged')
        parent = self._node(create=True)
        snapshot = api.admit()
        registry, store = api.owner.universal_registry, api.owner.universal_store
        cell = Cell(root, parent, api.binding.subject_root, raw)
        if snapshot.cells.get(root) == cell:
            return
        patch = prepare_append_relation_members(snapshot, parent,
            () if root in snapshot.cells else ((registry.roles['member'], root),))
        view, context = app._view_session_for_context(registry, api.binding.context)
        api.guard()
        app._commit_universal_user_change(store, registry, view, context, snapshot,
            route=api.route, command_name='catalog.configure', authorization_scope_root=api.root,
            create=(*patch.create, *((cell,) if root not in snapshot.cells else ())),
            replace=(*patch.replace, *((cell,) if root in snapshot.cells else ())))

    def _state(self):
        return self._read(self.root) or {'program':'', 'instance':None, 'stage':'Watching',
            'offers':[], 'proposal':None, 'proposals':[], 'taskId':None}

    def read(self):
        state = self._state()
        return {**state, 'owner':self.root, 'schedules':self.ops.project_schedules()}

    def _idle(self, state):
        if state['proposal'] and self.proposal(state['proposal'])['status'] in {'pending', 'executing', 'unconfirmed'}:
            raise InvalidCell('Decide the existing desktop plan before changing its program or offer')

    def set_program(self, program):
        from .clean_revit_adapter import broker_sessions
        if program not in {'Revit', 'AutoCAD'}:
            raise InvalidCell('Choose an available Revit or AutoCAD broker; other desktop actions have no typed primitive')
        state = self._state()
        self._idle(state)
        sessions = broker_sessions('revit' if program == 'Revit' else 'acad')
        if len(sessions) != 1:
            raise InvalidCell('Choose exactly one available program instance')
        state.update(program=program, instance=sessions[0]['port'], offers=[], proposal=None, taskId=None, stage='Watching')
        self._save(self.root, state)
        return self.read()

    def _source(self, source):
        from .host_brokers import watcher_read
        return watcher_read(source['host'], instance=source['instance'], view=source['view'],
            document=source['document'], element=source['element']['id'])

    def offer(self):
        from .host_brokers import watcher_read
        state = self._state()
        self._idle(state)
        if not state['program']:
            raise InvalidCell('Select an available program first')
        source = watcher_read(state['program'], instance=state['instance'])
        if not source.get('element'):
            raise InvalidCell('Select one wall or line in the program before requesting an action')
        offers = [{'action':'read', 'title':'Read selected geometry', 'payload':{'source':source}}]
        watcher = WatcherOwner(self.api)._state()
        if watcher['source'] == source and watcher['pendingY'] is not None:
            if watcher['proposal']:
                raise InvalidCell('This edit already has a Watcher approval; decide that card first')
            offers.insert(0, {'action':'move', 'title':'Apply the Watcher offset', 'payload':{
                'source':source, 'offsetMm':(watcher['pendingY']-source['element']['start'][1])*SCALE_MM}})
        state.update(offers=offers, stage='Offering')
        self._save(self.root, state)
        return self.read()

    def _draft_for(self, offer):
        watcher = WatcherOwner(self.api)
        draft = watcher._state()
        source = offer['payload']['source']
        if (draft['source'] != source or draft['proposal'] or draft['pendingY'] is None or
                (draft['pendingY']-source['element']['start'][1])*SCALE_MM != offer['payload']['offsetMm']):
            raise InvalidCell('The Watcher draft changed; review the new offset')
        return watcher, draft

    def prepare(self):
        state = self._state()
        if state['proposal']:
            proposal = self.proposal(state['proposal'])
            if proposal['status'] == 'pending':
                return self.card(state['proposal'])
            self._idle(state)
        if not state['offers']:
            raise InvalidCell('Request a concrete desktop offer first')
        offer = state['offers'][0]
        if offer['action'] == 'move':
            self._draft_for(offer)
        if self._source(offer['payload']['source']) != offer['payload']['source']:
            raise InvalidCell('The source changed; request a fresh offer')
        root = PREFIX + _digest([self.root, self.api.request_id])
        payload = {**offer, 'scope':self.api.scope, 'reviewer':self.api.binding.subject_root}
        if self._read(root):
            raise InvalidCell('Use a fresh request identity for a new desktop plan')
        self._save(root, {'owner':self.root, 'kind':'desktop', 'payload':payload,
            'input_digest':_digest(payload), 'status':'pending'})
        state.update(proposal=root, taskId=root, stage='Needs OK')
        state['proposals'].append(root)
        self._save(self.root, state)
        return self.card(root)

    def responsibility(self, schedule, values):
        self.api.admit()
        self.ops._schedule(self.ops.canvas(), schedule)
        if type(values) is not dict or not values or set(values)-{'operation', 'responsibility', 'selfReview'}:
            raise InvalidCell('Use the schedule operation, responsibility or self-review parameters')
        if ('operation' in values and values['operation'] != 'Workflow' or
                'selfReview' in values and type(values['selfReview']) is not bool or
                'responsibility' in values and (type(values['responsibility']) is not str or len(values['responsibility']) > 2000)):
            raise InvalidCell('Choose Workflow, a responsibility up to 2000 characters and boolean self-review')
        rows = self.ops._rows(None, schedule)
        current = json.loads(rows.get('responsibility', {}).get('value', '{}'))
        if current.get('owner', self.api.binding.subject_root) != self.api.binding.subject_root:
            raise InvalidCell('Only the schedule outcome owner can change its responsibility')
        current = {'operation':'Workflow', 'responsibility':'', 'selfReview':True, **current,
            **values, 'owner':self.api.binding.subject_root}
        self.api.guard()
        self.ops.set_property(schedule, 'responsibility', json.dumps(current))
        return next(row for row in self.ops.project_schedules() if row['id'] == schedule)

    def review_schedule(self, schedule):
        self.api.admit()
        self.ops._schedule(self.ops.canvas(), schedule)
        rows = self.ops._rows(None, schedule)
        run = json.loads(rows.get('last_result', {}).get('value', 'null'))
        if not run or run['status'] != 'complete':
            raise InvalidCell('Only a confirmed finished scheduled run can be reviewed')
        responsibility = run['responsibility']
        if responsibility.get('owner') != self.api.binding.subject_root:
            raise InvalidCell('This finished run belongs to its recorded outcome owner')
        root = PREFIX + _digest([self.root, schedule, run['id']])
        payload = {'schedule':schedule, 'run':run, 'scope':self.api.scope,
            'reviewer':responsibility['owner'], 'title':'Review scheduled work'}
        existing = self._read(root)
        if existing is None:
            self._save(root, {'owner':self.root, 'kind':'schedule', 'payload':payload,
                'input_digest':_digest(payload), 'status':'pending'})
        elif existing['input_digest'] != _digest(payload):
            raise InvalidCell('The retained scheduled result changed; reconcile its evidence')
        state = self._state()
        if root not in state['proposals']:
            state['proposals'].append(root)
            self._save(self.root, state)
        return self.card(root)

    def proposal(self, root):
        state = self._state()
        if type(root) is not str or root not in state['proposals']:
            raise InvalidCell('This desktop review belongs to another graph or account')
        proposal = self._read(root)
        if not proposal or proposal['owner'] != self.root:
            raise InvalidCell('The desktop review is not linked to this owner')
        return proposal

    def card(self, root):
        proposal = self.proposal(root)
        payload = proposal['payload']
        review = self._read(root + ':approval-review') or {'status':'pending', 'rows':[], 'rubric':{}, 'events':[]}
        return {**review, 'rows':review['rows'] or [{'element':payload.get('schedule') or payload['payload']['source']['element']['id'],
            'before':'Not executed' if proposal['kind'] == 'desktop' else 'Finished scheduled run',
            'after':json.dumps(payload, sort_keys=True)}], 'id':root, 'delegation':root, 'work':self._node(),
            'input_digest':proposal['input_digest'], 'approvalKind':proposal['kind'], 'kind':'qc',
            'reviewer':payload['reviewer'], 'title':payload['title'],
            'status':review['status'] if proposal['status'] == 'pending' else proposal['status'],
            'revision':self.api.owner.universal_store.revision}

    def reviews(self):
        return [self.card(root) for root in self._state()['proposals']]

    def decide(self, root, digest, decision):
        from .host_brokers import watcher_write
        proposal = self.proposal(root)
        payload = proposal['payload']
        if (decision not in {'approve', 'deny'} or digest != proposal['input_digest'] or digest != _digest(payload)
                or payload['scope'] != self.api.scope or payload['reviewer'] != self.api.binding.subject_root):
            raise InvalidCell('Decide the exact plan, scope and reviewer shown on this approval')
        if proposal['status'] == 'approved' and decision == 'approve':
            return self.card(root)
        if proposal['status'] != 'pending':
            raise InvalidCell('This desktop outcome is closed or needs reconciliation')
        if decision == 'deny':
            proposal['status'] = 'declined'
        elif proposal['kind'] == 'schedule':
            proposal['status'] = 'approved'
        else:
            source = payload['payload']['source']
            state = self._state()
            if state['proposal'] != root or state['program'] != source['host'] or state['instance'] != source['instance']:
                raise InvalidCell('The selected program changed; review a fresh plan')
            if self._source(source) != source:
                raise InvalidCell('Source revision changed; decline and request a fresh offer')
            if payload['action'] not in {'read', 'move'}:
                raise InvalidCell('The selected program has no such desktop primitive')
            if payload['action'] == 'move':
                watcher, draft = self._draft_for(payload)
            proposal['status'] = 'executing'
            self._save(root, proposal)
            try:
                if payload['action'] == 'move':
                    watcher_write(payload['payload'])
                actual = self._source(source)
                expected = json.loads(json.dumps(source))
                if payload['action'] == 'move':
                    for key in ('start', 'end'):
                        expected['element'][key][1] += payload['payload']['offsetMm']/SCALE_MM
                    expected['element']['revision'] = actual['element']['revision']
                if actual != expected:
                    raise InvalidCell('Broker readback differs from the approved plan')
            except Exception:
                proposal['status'] = 'unconfirmed'
                self._save(root, proposal)
                state['stage'] = 'Needs reconciliation'
                self._save(self.root, state)
                raise
            proposal.update(status='approved', readback=actual)
            if payload['action'] == 'move':
                draft.update(source=actual, pendingY=None, applied=True)
                watcher._save(watcher.root, draft, self.api.root)
        self._save(root, proposal)
        if proposal['kind'] == 'desktop':
            state = self._state()
            state.update(proposal=None, offers=[], stage='Applied' if decision == 'approve' else 'Watching')
            self._save(self.root, state)
        return self.card(root)


def approval_context(api, root):
    owner = DesktopOwner(api)
    proposal = owner.proposal(root)
    delegation = SimpleNamespace(root_id=root, permission_root=root, work_root=owner._node(),
        input_digest=proposal['input_digest'], expires_at=float('inf'))
    lifecycle = 'requested' if proposal['status'] == 'pending' else 'granted' if proposal['status'] == 'approved' else 'revoked'
    permission = SimpleNamespace(lifecycle_root=api.owner.universal_registry.adapter_protocol.states[lifecycle],
        user_root=api.binding.subject_root)
    return api.admit(), proposal['kind'], delegation, permission, {'interfaces':{'title':{'value':owner.card(root)['title']}}}
