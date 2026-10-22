"""Real graph persistence and broker effects; no user programs or profile data."""
import copy
from pathlib import Path
from datetime import datetime
import pytest
from nodelang import commit_intent, universal_pipeline
from nodelang.canvas_graph_owner import CanvasOwner
from nodelang.universal_cell import InvalidCell
from tests_replica import test_watcher_actions as watcher_support
from nodelang.workshop_api import WorkshopAPI
from nodelang.desktop_owner import DesktopOwner
from types import SimpleNamespace
from tempfile import TemporaryDirectory


@pytest.fixture(scope='module')
def shared_app(tmp_path_factory):
    with TemporaryDirectory(prefix='DESKTOP-', dir=tmp_path_factory.getbasetemp()) as folder:
        factory = SimpleNamespace(mktemp=lambda name:Path(folder))
        fixture = watcher_support.shared_app.__wrapped__(factory)
        yield next(fixture)
        try:
            next(fixture)
        except StopIteration:
            pass


approvals = watcher_support.approvals
watcher = watcher_support.watcher

@pytest.fixture(autouse=True)
def reset_desktop(watcher):
    api = WorkshopAPI(watcher.server, watcher.binding, watcher.registry.workshop_root, watcher.registry.canvas_root,
        guard=lambda:None, request_id='desktop-reset-'+str(watcher.sequence), route='/api/universal/workshop')
    owner = DesktopOwner(api)
    with commit_intent.declare(commit_intent.USER_ACTION, actor=watcher.binding.subject_root, reason='reset isolated desktop state'):
        for row in owner.ops.project_schedules():
            owner.ops.remove_schedule(row['id'])
        owner._save(owner.root, {'program':'', 'instance':None, 'stage':'Watching', 'offers':[],
            'proposal':None, 'proposals':[], 'taskId':None})


def reopen(w):
    before = w.call('readDesktop')
    w.server.close()
    w.start()
    assert w.call('readDesktop') == before
    return before


def test_setDesktopProgram_binds_available_instance_and_reopens(watcher):
    state = watcher.call('setDesktopProgram', 'Revit')
    assert state['program'] == 'Revit' and state['instance'] == 48884
    assert reopen(watcher)['program'] == 'Revit'
    with pytest.raises(InvalidCell): watcher.call('setDesktopProgram', 'Unsupported')
    assert watcher.effects == []


def test_offerDesktopAction_lists_real_source_bound_primitives(watcher):
    watcher.call('setDesktopProgram', 'Revit')
    watcher.call('editWall', 530)
    offered = watcher.call('offerDesktopAction')
    assert [a['action'] for a in offered['offers']] == ['move', 'read']
    assert offered['offers'][0]['payload']['offsetMm'] == 300
    assert offered['offers'][0]['payload']['source']['element']['id'] == 'wall-unique-214'
    assert reopen(watcher)['offers'] == offered['offers']
    assert watcher.effects == []


def test_prepareDesktopAction_one_approval_reopen_and_exact_broker_effect(watcher):
    watcher.call('setDesktopProgram', 'Revit')
    watcher.call('editWall', 530)
    watcher.call('offerDesktopAction')
    card = watcher.call('prepareDesktopAction')
    assert card['approvalKind'] == 'desktop' and watcher.effects == []
    assert watcher.call('prepareDesktopAction')['id'] == card['id']
    assert len([c for c in watcher.call('listApprovals') if c['approvalKind'] == 'desktop']) == 1
    reopen(watcher)
    watcher.call('postponeApproval', card['id'])
    with pytest.raises(InvalidCell): watcher.call('decideDesktopAction', card['id'], card['input_digest'], 'approve')
    watcher.call('resumeApproval', card['id'])
    result = watcher.call('decideDesktopAction', card['id'], card['input_digest'], 'approve')
    assert result['status'] == 'approved' and len(watcher.effects) == 1
    assert watcher.model['element']['start'][1] == 530
    watcher.call('decideDesktopAction', card['id'], card['input_digest'], 'approve')
    assert len(watcher.effects) == 1
    assert reopen(watcher)['stage'] == 'Applied'


def scheduled(w):
    ops = CanvasOwner(w.store, w.registry, w.binding.context)
    with commit_intent.declare(commit_intent.USER_ACTION, actor=w.binding.subject_root, reason='isolated scheduled workflow'):
        target = universal_pipeline.create_engine_node(w.store, w.registry, title='Fixture', engine='data.constant',
            properties={'value':'fixture'}, authentication_context=w.binding.context)
        schedule = ops.add_schedule([target['root']], time='08:00')['id']
    return ops, schedule


def test_setScheduleResponsibility_partial_updates_and_reopen(watcher):
    _, schedule = scheduled(watcher)
    row = watcher.call('setScheduleResponsibility', schedule, {'responsibility':'Check the output'})
    assert row['owner'] == watcher.binding.subject_root
    watcher.call('setScheduleResponsibility', schedule, {'selfReview':False})
    row = next(r for r in watcher.call('readDesktop')['schedules'] if r['id'] == schedule)
    assert row['responsibility'] == 'Check the output' and row['selfReview'] is False
    assert next(r for r in reopen(watcher)['schedules'] if r['id'] == schedule) == row
    with pytest.raises(InvalidCell): watcher.call('setScheduleResponsibility', schedule, {'operation':'Invented'})


def test_reviewScheduledWork_finished_run_one_owner_card_and_reopen(watcher):
    ops, schedule = scheduled(watcher)
    watcher.call('setScheduleResponsibility', schedule, {'responsibility':'Validate fixture', 'selfReview':True})
    with pytest.raises(InvalidCell): watcher.call('reviewScheduledWork', schedule)
    effects = []
    def run(targets):
        effects.extend(targets)
        return {'ok':True, 'ran':targets, 'outputs':{'fixture':'done'}}
    with commit_intent.declare(commit_intent.USER_ACTION, actor=watcher.binding.subject_root, reason='isolated schedule tick'):
        ops.tick_schedules(datetime(year=2026, month=1, day=1, hour=9), run,
            review=lambda root:watcher.call('reviewScheduledWork', root))
    assert effects
    card = watcher.call('reviewScheduledWork', schedule)
    assert card['approvalKind'] == 'schedule' and card['reviewer'] == watcher.binding.subject_root
    assert watcher.call('reviewScheduledWork', schedule)['id'] == card['id']
    reopen(watcher)
    assert watcher.card(card['id'])['input_digest'] == card['input_digest']
    before = copy.deepcopy(effects)
    assert watcher.call('decideDesktopAction', card['id'], card['input_digest'], 'approve')['status'] == 'approved'
    assert effects == before
    reopen(watcher)


def test_desktop_stale_source_and_denial_never_write(watcher):
    watcher.call('setDesktopProgram', 'Revit')
    watcher.call('editWall', 530)
    watcher.call('offerDesktopAction')
    card = watcher.call('prepareDesktopAction')
    watcher.model['element']['revision'] = 'changed'
    with pytest.raises(InvalidCell): watcher.call('decideDesktopAction', card['id'], card['input_digest'], 'approve')
    assert watcher.effects == []
    assert watcher.call('decideDesktopAction', card['id'], card['input_digest'], 'deny')['status'] == 'declined'


def test_one_offset_has_one_card_across_desktop_and_watcher(watcher):
    watcher.call('setDesktopProgram', 'Revit')
    watcher.call('editWall', 530)
    watcher.call('offerDesktopAction')
    card = watcher.call('prepareDesktopAction')
    with pytest.raises(InvalidCell, match='desktop approval'): watcher.call('proposeWatcherEdit')
    assert len(watcher.call('listApprovals')) == 1 and watcher.effects == []
    watcher.call('decideDesktopAction', card['id'], card['input_digest'], 'deny')
    assert watcher.call('proposeWatcherEdit')['approvalKind'] == 'watcher'


def test_prepare_checks_fresh_offset_before_creating_card(watcher):
    watcher.call('setDesktopProgram', 'Revit')
    watcher.call('editWall', 530)
    watcher.call('offerDesktopAction')
    watcher.call('editWall', 540)
    with pytest.raises(InvalidCell, match='draft changed'): watcher.call('prepareDesktopAction')
    assert not [c for c in watcher.call('listApprovals') if c['approvalKind'] == 'desktop']
    assert watcher.effects == []


def test_read_only_desktop_plan_runs_broker_read_after_approval(watcher):
    watcher.call('setDesktopProgram', 'Revit')
    assert watcher.call('offerDesktopAction')['offers'][0]['action'] == 'read'
    card = watcher.call('prepareDesktopAction')
    result = watcher.call('decideDesktopAction', card['id'], card['input_digest'], 'approve')
    assert result['status'] == 'approved' and watcher.effects == []
    assert reopen(watcher)['stage'] == 'Applied'


@pytest.mark.parametrize('failure', ['after-write', 'bad-readback'])
def test_desktop_uncertain_effect_is_durable_and_never_replayed(watcher, monkeypatch, failure):
    from nodelang import host_brokers
    watcher.call('setDesktopProgram', 'Revit')
    watcher.call('editWall', 530)
    watcher.call('offerDesktopAction')
    card = watcher.call('prepareDesktopAction')
    write = host_brokers.watcher_write
    def uncertain(payload):
        result = write(payload)
        if failure == 'after-write':
            raise InvalidCell('Fixture lost the response after writing')
        watcher.model['element']['start'][1] += 1
        return result
    monkeypatch.setattr(host_brokers, 'watcher_write', uncertain)
    with pytest.raises(InvalidCell): watcher.call('decideDesktopAction', card['id'], card['input_digest'], 'approve')
    assert len(watcher.effects) == 1 and watcher.card(card['id'])['status'] == 'unconfirmed'
    reopen(watcher)
    assert watcher.card(card['id'])['status'] == 'unconfirmed'
    with pytest.raises(InvalidCell): watcher.call('decideDesktopAction', card['id'], card['input_digest'], 'approve')
    assert len(watcher.effects) == 1


def test_schedule_scope_refusal_precedes_any_mutation(watcher):
    from nodelang.universal_graphs import create_graph, open_graph
    _, schedule = scheduled(watcher)
    with commit_intent.declare(commit_intent.USER_ACTION, actor=watcher.binding.subject_root, reason='isolated second graph'):
        other = create_graph(watcher.store, watcher.registry, 'Other fixture graph', authentication_context=watcher.binding.context)
        try:
            api = WorkshopAPI(watcher.server, watcher.binding, watcher.registry.workshop_root, other['graph']['id'],
                guard=lambda:None, request_id='off-scope-schedule', route='/api/universal/workshop')
            revision = watcher.store.revision
            with pytest.raises(InvalidCell): DesktopOwner(api).responsibility(schedule, {'responsibility':'Wrong graph'})
            assert watcher.store.revision == revision
            with pytest.raises(InvalidCell): DesktopOwner(api).review_schedule(schedule)
            assert watcher.store.revision == revision
        finally:
            open_graph(watcher.store, watcher.registry, watcher.registry.canvas_root, authentication_context=watcher.binding.context)


def test_failed_schedule_exposes_outcome_without_replay_or_finished_review(watcher):
    ops, schedule = scheduled(watcher)
    effects, reviews = [], []
    def run(targets):
        effects.append(targets)
        return {'ok':False, 'ran':[], 'error':'Fixture failure'}
    now = datetime(year=2026, month=1, day=1, hour=9)
    with commit_intent.declare(commit_intent.USER_ACTION, actor=watcher.binding.subject_root, reason='isolated failed schedule'):
        with pytest.raises(InvalidCell): ops.tick_schedules(now, run, review=reviews.append)
        assert ops.tick_schedules(now, run, review=reviews.append) == []
    assert len(effects) == 1 and reviews == []
    row = next(r for r in watcher.call('readDesktop')['schedules'] if r['id'] == schedule)
    assert row['lastResult']['status'] == 'needs-attention' and row['lastResult']['result']['error'] == 'Fixture failure'
    assert row['owner'] == watcher.binding.subject_root
    with pytest.raises(InvalidCell): watcher.call('reviewScheduledWork', schedule)
    reopen(watcher)


def test_schedule_false_self_review_is_manual_and_next_run_has_new_card(watcher):
    ops, schedule = scheduled(watcher)
    watcher.call('setScheduleResponsibility', schedule, {'selfReview':False})
    reviews = []
    def run(targets): return {'ok':True, 'ran':targets}
    with commit_intent.declare(commit_intent.USER_ACTION, actor=watcher.binding.subject_root, reason='isolated manual schedule review'):
        ops.tick_schedules(datetime(year=2026, month=1, day=1, hour=9), run, review=reviews.append)
    assert reviews == []
    first = watcher.call('reviewScheduledWork', schedule)
    with commit_intent.declare(commit_intent.USER_ACTION, actor=watcher.binding.subject_root, reason='isolated next scheduled run'):
        ops.tick_schedules(datetime(year=2026, month=1, day=2, hour=9), run, review=reviews.append)
    second = watcher.call('reviewScheduledWork', schedule)
    assert second['id'] != first['id'] and reviews == []
    reopen(watcher)


def test_http_scheduler_tick_uses_existing_run_transport_and_auto_queues_review(watcher, monkeypatch):
    import io
    import json
    import urllib.request
    ops, schedule = scheduled(watcher)
    with commit_intent.declare(commit_intent.USER_ACTION, actor=watcher.binding.subject_root, reason='fixture schedule due now'):
        ops.set_schedule_time(schedule, '00:00')
    urlopen = urllib.request.urlopen
    effects = []
    def transport(request, *args, **kwargs):
        if getattr(request, 'full_url', '').endswith('/api/universal/run-graph'):
            roots = json.loads(request.data)['roots']
            effects.extend(roots)
            return io.BytesIO(json.dumps({'ok':True, 'ran':roots}).encode())
        return urlopen(request, *args, **kwargs)
    monkeypatch.setattr(urllib.request, 'urlopen', transport)
    request = urllib.request.Request(watcher.server.public_url+'/api/universal/canvas-op',
        data=json.dumps({'op':'scheduler_tick', 'args':[]}).encode(), method='POST', headers={
            'Content-Type':'application/json', 'X-ArchHub-Session':watcher.server.browser_session_token,
            'X-ArchHub-CSRF':watcher.server.browser_csrf_token})
    with urlopen(request, timeout=30.0) as response:
        result = json.load(response)
    assert result['ok'] and effects
    cards = [c for c in watcher.call('listApprovals') if c['approvalKind'] == 'schedule']
    assert len(cards) == 1 and cards[0]['reviewer'] == watcher.binding.subject_root
    reopen(watcher)


def test_schedule_graph_switch_during_effect_preserves_uncertainty_without_cross_scope_landing(watcher):
    from nodelang.universal_graphs import create_graph, open_graph
    ops, schedule = scheduled(watcher)
    effects, reviews = [], []
    def run(targets):
        effects.extend(targets)
        create_graph(watcher.store, watcher.registry, 'Switch during fixture run', authentication_context=watcher.binding.context)
        return {'ok':True, 'ran':targets}
    now = datetime(year=2026, month=1, day=1, hour=9)
    with commit_intent.declare(commit_intent.USER_ACTION, actor=watcher.binding.subject_root, reason='isolated schedule graph-switch race'):
        try:
            with pytest.raises(InvalidCell, match='graph changed'):
                ops.tick_schedules(now, run, review=reviews.append)
        finally:
            open_graph(watcher.store, watcher.registry, watcher.registry.canvas_root, authentication_context=watcher.binding.context)
        assert ops.tick_schedules(now, run, review=reviews.append) == []
    assert effects and reviews == []
    row = next(r for r in watcher.call('readDesktop')['schedules'] if r['id'] == schedule)
    assert row['lastResult']['status'] == 'unconfirmed'
    with pytest.raises(InvalidCell): watcher.call('reviewScheduledWork', schedule)
    reopen(watcher)
