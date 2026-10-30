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

    def slow_fire(key, kind, reason='scheduled'):
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
    service.fire = lambda key, kind, reason='scheduled': calls.append(reason)
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
