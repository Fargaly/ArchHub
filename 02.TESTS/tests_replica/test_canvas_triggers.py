"""Trigger nodes fire while the app is open: schedule and file change run the downstream nodes once."""
import copy
import datetime
import time

import pytest


@pytest.fixture(autouse=True)
def profile(tmp_path, monkeypatch):
    for name in ('LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'HOME'):
        monkeypatch.setenv(name, str(tmp_path / name))
        (tmp_path / name).mkdir()
    yield tmp_path


def workflow(path, trigger, params):
    from nodelang.session_files import SessionFiles, catalogue, new_document, write_document
    items = {row['id']: row for row in catalogue()}
    params = {'ask_before_running': False, **params}  # these routines run at once; asking is the default (session model)
    doc = new_document('Triggered')
    doc['nodes'] = [
        {'id': 't', 'item': trigger, 'type': items[trigger]['engine'], 'title': 'Trigger',
         'params': {**copy.deepcopy(items[trigger]['params']), **params}, 'position': {'x': 0, 'y': 0}},
        {'id': 'c', 'item': 'data.convert', 'type': 'data.convert', 'title': 'Convert',
         'params': {'target_type': 'text'}, 'position': {'x': 300, 'y': 0}}]
    doc['wires'] = [{'id': 'w', 'from': {'node': 't', 'socket': 'payload'}, 'to': {'node': 'c', 'socket': 'in'}}]
    write_document(path, doc)
    SessionFiles().remember(path, doc)          # a workflow the app knows (recent)
    return doc


def test_schedule_trigger_is_armed_and_fires_downstream(profile):
    from nodelang.canvas_triggers import TriggerService
    from nodelang.session_files import read_document
    path = profile / 'daily.archhub'
    workflow(path, 'tr_schedule', {'every_seconds': '600'})
    service = TriggerService()
    try:
        armed = service.refresh()
        assert [(a['node'], a['kind']) for a in armed] == [('t', 'trigger.schedule')]
        service.fire((str(path), 't'), 'trigger.schedule')
        saved = read_document(path)
        assert next(n for n in saved['nodes'] if n['id'] == 'c')['result']['status'] == 'Done'
        assert saved['properties']['history'][-1]['by'] == 'trigger:schedule'
        assert service.fired[-1]['outcome'] == 'ran'
    finally:
        service.close()


def test_file_trigger_fires_on_a_change_only(profile):
    from nodelang.canvas_triggers import TriggerService
    folder = profile / 'drop'
    folder.mkdir()
    path = profile / 'watch.archhub'
    workflow(path, 'tr_file', {'folder': str(folder), 'pattern': '*.txt', 'debounce_seconds': '1'})
    service = TriggerService()
    try:
        service.refresh()
        time.sleep(1.5)
        assert not service.fired                     # first look only records the folder
        (folder / 'new.txt').write_text('x')
        deadline = time.time() + 6
        while not service.fired and time.time() < deadline:
            time.sleep(0.2)
        assert service.fired and service.fired[0]['kind'] == 'trigger.file'
    finally:
        service.close()


def test_next_delay_interval_floor_and_daily_time():
    from nodelang.canvas_triggers import next_delay
    assert next_delay({'every_seconds': '300'}) == 300
    assert next_delay({'every_seconds': '1'}) == 10
    noon = datetime.datetime(2026, 10, 28, 12, 0)
    assert next_delay({'every_seconds': '', 'daily_at': '13:30'}, noon) == 5400
    assert next_delay({'every_seconds': '', 'daily_at': '08:00'}, noon) == 20 * 3600


def workshop_rows():
    from nodelang.workshop_mailbox import ROOM, application_history
    with application_history() as history:
        return [row[0] for row in history._db.execute(
            'SELECT content FROM messages WHERE conversation_id=? ORDER BY sequence', (ROOM,))]


def test_routine_one_second_schedule_fires_and_records_a_workshop_entry(profile, monkeypatch):
    from nodelang.canvas_triggers import TRIGGER_NODE, TriggerService
    from nodelang.session_files import read_document
    monkeypatch.setitem(TRIGGER_NODE['params'], 'min_every_seconds', 1)
    path = profile / 'routine.archhub'
    workflow(path, 'tr_schedule', {'every_seconds': '1'})
    service = TriggerService()
    try:
        service.refresh()
        deadline = time.time() + 10
        while not any(f['outcome'] == 'ran' and f.get('workshop') for f in service.fired) and time.time() < deadline:
            time.sleep(0.2)
        assert any(f['outcome'] == 'ran' and f.get('workshop') for f in service.fired), service.fired
    finally:
        service.close()
    assert any(row.startswith('To Ahmed:\nRoutine Trigger (routine) fired, scheduled: ran') for row in workshop_rows())
    trigger = next(n for n in read_document(path)['nodes'] if n['id'] == 't')
    assert isinstance(trigger['result']['fired_at'], float)


@pytest.mark.parametrize('policy, runs, outcomes', [('skip', 1, ['skipped', 'skipped']),
                                                    ('queue', 3, ['queued', 'queued'])])
def test_routine_concurrency_policy(profile, policy, runs, outcomes):
    import threading
    from nodelang.canvas_triggers import TriggerService
    service = TriggerService(files=type('F', (), {'open_files': lambda self: []})())
    calls, gate = [], threading.Event()

    def slow_fire(key, kind, reason='scheduled', *, expected=None):
        calls.append(reason)
        gate.wait(5)
    service.fire = slow_fire
    key, params = ('p.archhub', 't'), {'concurrency': policy}
    first = threading.Thread(target=service.dispatch, args=(key, 'trigger.schedule', params))
    first.start()
    while not calls:
        time.sleep(0.01)
    assert [service.dispatch(key, 'trigger.schedule', params) for _ in range(2)] == outcomes
    gate.set()
    first.join(5)
    assert len(calls) == runs and key not in service.running and not service.queued


@pytest.mark.parametrize('policy, fires', [('run_once', ['catch-up']), ('skip', [])])
def test_routine_catch_up_policy(profile, policy, fires):
    from nodelang.canvas_triggers import TriggerService, missed_while_closed
    from nodelang.session_files import write_document
    path = profile / 'missed.archhub'
    doc = workflow(path, 'tr_schedule', {'every_seconds': '600', 'catch_up': policy})
    doc['nodes'][0]['result'] = {'fired_at': time.time() - 1200}   # app was closed past one fire
    write_document(path, doc)
    service = TriggerService()
    calls = []
    def fire(key, kind, reason='scheduled', *, expected=None):
        assert expected['params']['every_seconds'] == '600'
        calls.append(reason)

    service.fire = fire
    try:
        service.refresh()
        time.sleep(0.5)
    finally:
        service.close()
    assert calls == fires
    assert not missed_while_closed({'every_seconds': '600', 'catch_up': 'run_once'}, time.time() - 60)
    assert not missed_while_closed({'every_seconds': '600', 'catch_up': 'run_once'}, None)


def test_routine_addressed_to_an_agent_is_pushed_live_through_the_composer_path(profile, monkeypatch):
    import nodelang.workshop_live as live
    from nodelang.canvas_triggers import TriggerService
    pushed = []
    monkeypatch.setattr(live, 'send_as_founder', lambda text, handles, reply_to=None: pushed.append((text, handles))
                        or {'message_id': 'm1', 'deliveries': [{'agent': 'coord', 'state': 'delivered'}]})
    path = profile / 'agent.archhub'
    workflow(path, 'tr_schedule', {'every_seconds': '600', 'to': '@Coord'})
    service = TriggerService()
    try:
        entry = service.fire((str(path), 't'), 'trigger.schedule')
    finally:
        service.close()
    assert pushed == [('Routine Trigger (agent) fired, scheduled: ran', ['coord'])]
    assert entry['workshop'] == 'm1' and entry['deliveries'][0]['state'] == 'delivered'


def test_refresh_replaces_changed_schedule_and_ignores_superseded_callback(profile, monkeypatch):
    from nodelang import canvas_documents, canvas_triggers

    class ManualTimer:
        def __init__(self, delay, callback, args):
            self.delay, self.callback, self.args = delay, callback, args
            self.cancelled = False

        def start(self):
            pass

        def cancel(self):
            self.cancelled = True

        def fire(self):
            self.callback(*self.args)

    monkeypatch.setattr(canvas_triggers.threading, 'Timer', ManualTimer)
    path = profile / 'editable.archhub'
    workflow(path, 'tr_schedule', {'every_seconds': '600'})
    key = (str(path), 't')
    service = canvas_triggers.TriggerService()
    calls = []
    monkeypatch.setattr(service, 'dispatch', lambda *args, **kwargs: calls.append(args))

    def set_interval(document):
        document['nodes'][0]['params']['every_seconds'] = '1200'
        return ['t']

    try:
        service.refresh()
        previous = service.timers[key]
        assert previous.delay == 600
        canvas_documents.edit(path, 'Test', 'Change schedule', set_interval, solve_changed=False)
        service.refresh()
        current = service.timers[key]
        assert previous.cancelled
        assert current is not previous
        assert current.delay == 1200
        previous.fire()
        assert service.timers[key] is current
        assert calls == []
        current.fire()
        assert len(calls) == 1
        assert calls[0][2]['every_seconds'] == '1200'
    finally:
        service.close()


def test_asking_run_can_be_approved_only_once(profile, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from nodelang.canvas_triggers import TriggerService
    from nodelang.session_files import append_run, read_runs

    path = profile / 'approve-once.archhub'
    workflow(path, 'tr_schedule', {'ask_before_running': True})
    append_run(path, {'id': 'pending', 'trigger': 't', 'kind': 'trigger.schedule', 'state': 'asking'})
    service = TriggerService()
    ready = Barrier(2)
    dispatches = []
    monkeypatch.setattr(service, 'dispatch', lambda *args, **kwargs: dispatches.append((args, kwargs)) or 'ran')

    def approve():
        ready.wait(timeout=5)
        try:
            return service.approve(path, 'pending')
        except ValueError:
            return 'refused'

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = [pool.submit(approve) for _ in range(2)]
            assert sorted(result.result(timeout=10) for result in attempts) == ['ran', 'refused']
        with pytest.raises(ValueError):
            service.approve(path, 'pending')
        assert len(dispatches) == 1
        assert next(row for row in read_runs(path) if row['id'] == 'pending')['state'] == 'approved'
    finally:
        service.close()


def test_overlapping_refresh_cannot_rearm_a_paused_schedule(profile, monkeypatch):
    from threading import Event, Thread, current_thread
    from nodelang import canvas_triggers, session_files

    path = profile / 'refresh-race.archhub'
    original = workflow(path, 'tr_schedule', {'every_seconds': '600'})
    service = canvas_triggers.TriggerService()
    captured, release = Event(), Event()
    read_document = session_files.read_document

    def delayed_read(filename):
        document = read_document(filename)
        if current_thread().name == 'old-refresh':
            captured.set()
            assert release.wait(5)
        return document

    monkeypatch.setattr(session_files, 'read_document', delayed_read)
    old = Thread(target=service.refresh, name='old-refresh')
    try:
        old.start()
        assert captured.wait(5)
        original['nodes'][0]['params']['armed'] = False
        session_files.write_document(path, original)
        service.refresh()
        release.set()
        old.join(5)
        assert not old.is_alive()
        assert service.armed == [] and service.timers == {}
    finally:
        release.set()
        old.join(5)
        service.close()


def test_schedule_paused_during_callback_cannot_emit_after_resume(profile, monkeypatch):
    from threading import Event, Thread
    from nodelang import canvas_triggers, session_files

    path = profile / 'pause-race.archhub'
    document = workflow(path, 'tr_schedule', {'every_seconds': '600', 'catch_up': 'run_once'})
    service = canvas_triggers.TriggerService()
    key = (str(path), 't')
    reached, release = Event(), Event()
    dispatches = []

    dispatch = service.dispatch

    def admission(*args, **kwargs):
        reached.set()
        assert release.wait(5)
        return dispatch(*args, **kwargs)

    monkeypatch.setattr(service, 'dispatch', admission)
    monkeypatch.setattr(service, 'fire', lambda *args, **kwargs: dispatches.append(args))
    service.refresh()
    timer = service.timers[key]
    timer.cancel()
    callback = Thread(target=timer.function)
    try:
        callback.start()
        assert reached.wait(5)
        document['nodes'][0]['result'] = {'fired_at': time.time() - 1200}
        document['nodes'][0]['params']['armed'] = False
        session_files.write_document(path, document)
        service.refresh()
        document['nodes'][0]['params']['armed'] = True
        session_files.write_document(path, document)
        service.refresh()
        release.set()
        callback.join(5)
        assert not callback.is_alive()
        assert key in service.timers
        assert dispatches == [] and service.fired == []
    finally:
        release.set()
        callback.join(5)
        service.close()


@pytest.mark.parametrize('change', [{'armed': False}, {'every_seconds': '1200'}])
@pytest.mark.parametrize('ask', [True, False])
def test_persisted_schedule_edit_blocks_old_timer_before_refresh(profile, monkeypatch, change, ask):
    from nodelang import canvas_documents, canvas_triggers, session_files

    path = profile / 'before-refresh.archhub'
    workflow(path, 'tr_schedule', {'every_seconds': '600', 'ask_before_running': ask})
    service = canvas_triggers.TriggerService()
    key = (str(path), 't')
    calls = []
    monkeypatch.setattr(service, 'fire', lambda *args, **kwargs: calls.append(args))

    def save(document):
        document['nodes'][0]['params'].update(change)
        return ['t']

    try:
        service.refresh()
        timer = service.timers[key]
        timer.cancel()
        canvas_documents.edit(path, 'Test', 'Change schedule before refresh', save, solve_changed=False)
        assert service.timers[key] is timer
        timer.function()
        assert calls == [] and service.fired == [] and session_files.read_runs(path) == []
    finally:
        service.close()


def test_opening_autosave_keeps_committed_schedule_retime(profile):
    from nodelang import canvas_triggers, session_files

    path = profile / 'retimed.archhub'
    workflow(path, 'tr_schedule', {'every_seconds': 600, 'armed': True})
    files = session_files.SessionFiles()
    service = canvas_triggers.TriggerService(files)
    key = (str(path), 't')
    try:
        opened = files.dispatch({'action': 'open', 'path': str(path)})
        service.refresh()
        old_timer = service.timers[key]
        old_timer.cancel()

        service.change_schedule('set_schedule_time', [str(path) + '#t', '18:30'])
        opened['document']['nodes'][0]['position']['x'] = 20
        files.dispatch({'action': 'autosave', 'path': str(path), 'document': opened['document'],
                        'base_revision': opened['document']['properties'].get('revision', 0)})

        saved = session_files.read_document(path)['nodes'][0]
        assert saved['position']['x'] == 20
        assert saved['params']['daily_at'] == '18:30'
        assert saved['params']['every_seconds'] is None
        old_timer.function()
        assert session_files.read_runs(path) == []
    finally:
        service.close()


def test_stale_autosave_does_not_recreate_removed_armed_workflow(profile):
    from nodelang import canvas_triggers, session_files

    path = profile / 'removed-armed.archhub'
    workflow(path, 'tr_schedule', {'every_seconds': 600, 'armed': True})
    files = session_files.SessionFiles()
    service = canvas_triggers.TriggerService(files)
    key = (str(path), 't')
    try:
        opened = files.dispatch({'action': 'open', 'path': str(path)})['document']
        service.refresh()
        old_timer = service.timers[key]
        old_timer.cancel()
        path.unlink()
        opened['nodes'][0]['position']['x'] = 20
        with pytest.raises(ValueError, match='workflow moved or was removed'):
            files.dispatch({'action': 'autosave', 'path': str(path), 'document': opened})
        service.refresh()
        old_timer.function()
        assert not path.exists() and key not in service.timers
        assert service.armed == [] and service.fired == []
    finally:
        service.close()


@pytest.mark.parametrize('copy_kind', ['save-as', 'recover'])
def test_workflow_copies_keep_both_automations_dormant(profile, copy_kind):
    from nodelang import canvas_triggers, session_files

    original = profile / 'original-workflow.archhub'
    document = workflow(original, 'tr_schedule', {'every_seconds': 600, 'armed': True})
    watched = profile / 'watched'
    watched.mkdir()
    params = {'folder': watched.name, 'pattern': '*.txt', 'debounce_seconds': 600, 'ask_before_running': False}
    document['nodes'].append({'id': 'watch', 'type': 'trigger.file', 'item': 'tr_file', 'params': params,
                              'position': {'x': 0, 'y': 200}})
    session_files.write_document(original, document)
    files = session_files.SessionFiles()
    opened = files.dispatch({'action': 'open', 'path': str(original)})['document']
    service = canvas_triggers.TriggerService(files)
    try:
        before = original.read_bytes()
        destination = {'conflict_copy_of': str(original)} if copy_kind == 'recover' else {
            'path': str(profile / 'saved-copy.archhub'), 'copy_source': str(original)}
        saved = files.dispatch({'action': 'save', 'save_as': True, 'document': opened, **destination})
        copied = session_files.read_document(saved['path'])
        for key in ('t', 'watch'):
            source = next(node['params'] for node in opened['nodes'] if node['id'] == key)
            assert next(node['params'] for node in copied['nodes'] if node['id'] == key) == {**source, 'armed': False}
        assert original.read_bytes() == before
        service.refresh()
        assert {(row['path'], row['node']) for row in service.armed} == {(str(original), 't'), (str(original), 'watch')}
        assert session_files.read_runs(saved['path']) == []
    finally:
        service.close()


def test_timed_approval_uses_the_same_saved_parameters_as_admission(profile, monkeypatch):
    from nodelang.canvas_triggers import TriggerService
    from nodelang.session_files import read_runs

    path = profile / 'saved-ask.archhub'
    workflow(path, 'tr_schedule', {'every_seconds': '600', 'ask_before_running': True})
    service = TriggerService()
    key = (str(path), 't')
    monkeypatch.setattr(service, '_asks', lambda _: False)
    calls = []
    monkeypatch.setattr(service, 'fire', lambda *args, **kwargs: calls.append(args))
    try:
        service.refresh()
        assert service.dispatch(key, 'trigger.schedule', service.armed[0]['params'],
                                timer=service.timers[key]) == 'asking'
        assert calls == []
        assert [run['state'] for run in read_runs(path)] == ['asking']
    finally:
        service.close()


@pytest.mark.parametrize('transition', ['pause', 'pause-resume', 'close'])
def test_approved_run_does_not_drain_a_superseded_timed_occurrence(profile, monkeypatch, transition):
    from threading import Event, Thread
    from nodelang import canvas_triggers, session_files

    path = profile / 'queued-before-pause.archhub'
    workflow(path, 'tr_schedule', {'every_seconds': '600', 'concurrency': 'queue'})
    service = canvas_triggers.TriggerService()
    key = (str(path), 't')
    reached, release = Event(), Event()
    results, posted = [], []
    fire = service.fire

    def record(key, kind, reason='scheduled', *, expected=None):
        if reason == 'approved':
            reached.set()
            assert release.wait(5)
        else:
            results.append(fire(key, kind, reason, expected=expected))

    monkeypatch.setattr(service, 'fire', record)
    monkeypatch.setattr(service, '_post', lambda *args: posted.append(args) or {})
    first = Thread(target=service.dispatch, args=(key, 'trigger.schedule', {}, 'approved'))
    try:
        service.refresh()
        first.start()
        assert reached.wait(5)
        assert service.dispatch(key, 'trigger.schedule', service.armed[0]['params'],
                                timer=service.timers[key]) == 'queued'
        if transition == 'close':
            service.close()
        else:
            session_files.set_session_fields(str(path), {'automation': [{'node': 't', 'armed': False}]})
            service.refresh()
            if transition == 'pause-resume':
                session_files.set_session_fields(str(path), {'automation': [{'node': 't', 'armed': True}]})
                service.refresh()
                assert key in service.timers
        release.set()
        first.join(5)
        assert not first.is_alive()
        assert results == [{'outcome': 'superseded'}]
        assert posted == []
        assert [run['state'] for run in session_files.read_runs(path)] == ['queued']
    finally:
        release.set()
        first.join(5)
        service.close()

def test_pause_all_persists_and_drops_automatic_starts(profile, monkeypatch):
    from nodelang.canvas_triggers import TriggerService
    from nodelang.nograph_server import JsonFile
    from nodelang.session_files import read_runs

    chosen = profile / 'armed.archhub'
    other = profile / 'also-armed.archhub'
    held = profile / 'held.archhub'
    watch = profile / 'watch.archhub'
    host = profile / 'host.archhub'
    folder = profile / 'drop'
    folder.mkdir()
    workflow(chosen, 'tr_schedule', {'every_seconds': '600', 'armed': True, 'catch_up': 'run_once'})
    workflow(other, 'tr_schedule', {'every_seconds': '600', 'armed': True})
    workflow(held, 'tr_schedule', {'every_seconds': '600', 'armed': False})
    workflow(watch, 'tr_file', {'folder': str(folder), 'pattern': '*.txt', 'debounce_seconds': '600'})
    workflow(host, 'tr_host', {})
    before = {path: path.read_bytes() for path in (chosen, other, held, watch, host)}
    settings = JsonFile(profile / 'settings.json', {'settingsScope': 'User'})
    service = TriggerService(pause_settings=settings)
    monkeypatch.setattr(service, '_post', lambda *args: pytest.fail('Paused work must not post'))

    def tick(owner, path):
        timer = owner.timers[(str(path), 't')]
        timer.cancel()
        timer.function()

    try:
        assert {row['path'] for row in service.refresh()} == {str(chosen), str(other), str(watch)}
        tick(service, watch)
        assert service.set_paused(True) is True
        tick(service, chosen)
        tick(service, chosen)
        (folder / 'new.txt').write_text('changed during the pause')
        tick(service, watch)
        assert service.dispatch((str(host), 't'), 'trigger.host', {}, reason='host-event') == 'paused'
        assert settings.read() == {'settingsScope': 'User', 'automationsPaused': True}
    finally:
        service.close()
    for path, count in ((chosen, 2), (watch, 1), (host, 1)):
        [row] = read_runs(path)
        assert row['state'] == 'skipped' and row['reason'] == f'skipped while paused: {count}'
    restored = TriggerService(pause_settings=settings)
    try:
        assert restored.paused is True
        assert {row['path'] for row in restored.refresh()} == {str(chosen), str(other), str(watch)}
        tick(restored, watch)
        (folder / 'more.txt').write_text('changed between the last tick and Resume all')
        assert restored.set_paused(False) is False
        tick(restored, watch)
        assert restored.fired == []
        assert [row['count'] for row in read_runs(watch)] == [1, 1]
        assert settings.read() == {'settingsScope': 'User', 'automationsPaused': False}
        assert {path: path.read_bytes() for path in before} == before
    finally:
        restored.close()


@pytest.mark.parametrize('resume_before_release', [False, True])
def test_pause_serializes_run_admission_and_leaves_approved_runs_available(profile, monkeypatch, resume_before_release):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from nodelang import session_files
    from nodelang.canvas_triggers import TriggerService
    from nodelang.hook_decision import ask_apply, ask_reviews
    from nodelang.nograph_server import JsonFile

    path = profile / 'automatic.archhub'
    approved = profile / 'approved.archhub'
    target = profile / 'approved-output.txt'
    document = workflow(path, 'tr_schedule', {'every_seconds': '600'})
    document['nodes'].append({'id': 'write', 'type': 'thing.file.write', 'title': 'Manual output',
                              'params': {'path': str(target), 'content': 'approved only'},
                              'position': {'x': 300, 'y': 240}})
    session_files.write_document(path, document)
    result = session_files.SessionFiles().dispatch({'action': 'run', 'path': str(path),
                                                   'document': document, 'roots': ['write']})
    card = next(card for card in ask_reviews() if card['id'] == result['approvalId'])
    workflow(approved, 'tr_schedule', {'every_seconds': '600', 'ask_before_running': True})
    original = path.read_bytes()
    history_before = session_files.read_runs(path)
    reached, release = Event(), Event()
    owner = TriggerService(pause_settings=JsonFile(profile / 'settings.json', {}))
    run_document = session_files.run_document
    posted = []

    def delay_automatic(document, **kwargs):
        if kwargs['path'] == str(path):
            reached.set()
            assert release.wait(5)
        return run_document(document, **kwargs)

    monkeypatch.setattr(session_files, 'run_document', delay_automatic)
    monkeypatch.setattr(owner, '_post', lambda *args: posted.append(args[0]) or {})
    try:
        owner.refresh()
        key = (str(path), 't')
        params = next(row['params'] for row in owner.armed if row['path'] == str(path))
        assert owner.dispatch((str(approved), 't'), 'trigger.schedule', {}) == 'asking'
        [asking] = session_files.read_runs(approved)
        with ThreadPoolExecutor() as pool:
            automatic = pool.submit(owner.dispatch, key, 'trigger.schedule', params, timer=owner.timers[key])
            try:
                assert reached.wait(5)
                assert owner.set_paused(True) is True
                assert owner.approve(approved, asking['id']) == 'ran'
                assert session_files.read_document(approved)['nodes'][1]['result']['status'] == 'Done'
                if resume_before_release:
                    assert owner.set_paused(False) is False
            finally:
                release.set()
            automatic.result(timeout=5)
        assert path.read_bytes() == original
        assert session_files.read_runs(path) == history_before
        assert owner.set_paused(False) is False
        assert owner.fire(key, 'trigger.schedule')['outcome'] == 'skipped'
        [skipped] = [row for row in session_files.read_runs(path) if row['state'] == 'skipped']
        assert skipped['state'] == 'skipped' and 'waiting for approval' in skipped['reason']
        assert posted == [(str(approved), 't')]
        assert path.read_bytes() == original and not target.exists()
        assert next(row for row in ask_reviews() if row['id'] == card['id'])['status'] == 'pending'
        assert owner.set_paused(True) is True
        ask_apply(card['id'], card['input_digest'], 'approve')
        assert target.read_text(encoding='utf-8') == 'approved only'
    finally:
        owner.close()


def test_pause_leaves_an_admitted_node_running_and_holds_the_next_node(profile, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from nodelang import session_files
    from nodelang.canvas_triggers import TriggerService
    from nodelang.nograph_server import JsonFile

    path = profile / 'admitted.archhub'
    workflow(path, 'tr_schedule', {'every_seconds': '600'})
    reached, release = Event(), Event()
    owner = TriggerService(pause_settings=JsonFile(profile / 'settings.json', {}))
    dispatch_node = session_files._dispatch_node

    def delay_admitted(document, node, *args, **kwargs):
        assert node['id'] == 't'
        reached.set()
        assert release.wait(5)
        return dispatch_node(document, node, *args, **kwargs)

    monkeypatch.setattr(session_files, '_dispatch_node', delay_admitted)
    monkeypatch.setattr(owner, '_post', lambda *args: {})
    try:
        [row] = owner.refresh()
        key = (str(path), 't')
        with ThreadPoolExecutor() as pool:
            automatic = pool.submit(owner.dispatch, key, 'trigger.schedule', row['params'], timer=owner.timers[key])
            try:
                assert reached.wait(5)
                assert owner.set_paused(True) is True
            finally:
                release.set()
            automatic.result(timeout=5)
        results = {node['id']: node['result']['status'] for node in session_files.read_document(path)['nodes']}
        assert results == {'t': 'Done', 'c': 'Stopped'}
    finally:
        owner.close()
