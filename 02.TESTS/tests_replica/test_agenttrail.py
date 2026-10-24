"""Runtime courts over real JSONL/files and the existing Workshop row owner."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from nodelang import agent_declarations
from nodelang.workshop_api import WorkshopAPI

pytest_plugins = ['tests_replica.test_workshop_assign_to_agent']


def write(path, *rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')


def codex(root, session='codex-fixture', file='01.APP/OWNED.py', at=None):
    at = at or time.time()
    stamp = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(at)) + 'Z'
    return [
        {'type':'session_meta','payload':{'id':session,'cwd':str(root)}},
        {'timestamp':stamp,'type':'response_item','payload':{'type':'function_call',
         'name':'apply_patch','call_id':'tool-1','arguments':json.dumps({'path':file}),
         'input':'PRIVATE_PROMPT_CANARY'}},
    ]


def claude(root, session='claude-fixture', file='01.APP/OWNED.py', at=None):
    return {'sessionId':session,'cwd':str(root),'uuid':'event-1',
        'timestamp':time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(at or time.time()))+'Z',
        'type':'assistant','message':{'content':[
            {'type':'thinking','thinking':'PRIVATE_REASONING_CANARY'},
            {'type':'tool_use','id':'tool-1','name':'Edit','input':{'file_path':file,'new_string':'PRIVATE_PROMPT_CANARY'}}]}}


def setup(tmp_path, monkeypatch, *, installed_at=None, owns=None):
    root = tmp_path / 'WORKSPACE'
    file = root / '01.APP' / 'OWNED.py'
    file.parent.mkdir(parents=True)
    file.write_text('original', encoding='utf-8')
    home = tmp_path / 'HOME'
    monkeypatch.setenv('CODEX_HOME', str(home / '.codex'))
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(home / '.claude'))
    owner = SimpleNamespace(universal_workspace_root=root, universal_store=SimpleNamespace(revision=7))
    api = WorkshopAPI(owner, None, 'room', 'scope', guard=lambda: None, request_id='court', route='court')
    options = {'activity':{'owns':owns or ['01.APP/*.py'], 'installed_at':installed_at}}
    monkeypatch.setattr(api, '_options', lambda task: options)
    monkeypatch.setattr(api, '_messages', lambda task: ([], False))
    row = {'root':'work:real-row','operational':{'current_state_label':'open'},
           'interfaces':{'title':{'value':'AgentTrail real Work row'}}}
    monkeypatch.setattr(api, '_works', lambda: [row])
    monkeypatch.setattr(agent_declarations, 'declarations', lambda owner, **kw: [])
    return root, home, file, api, options


def logs(home):
    return (home / '.codex/sessions/2026/10/24/session.jsonl',
            home / '.claude/projects/WORKSPACE/session.jsonl')


def test_codex_and_claude_appear_on_the_existing_row_within_ten_seconds(tmp_path, monkeypatch):
    root, home, _file, api, _options = setup(tmp_path, monkeypatch)
    started = time.monotonic()
    a, b = logs(home)
    write(a, *codex(root))
    write(b, claude(root))
    task = api.listTasks()[0]
    assert 'activity' in task, 'existing Work row has no runtime activity projection'
    assert {row['provider'] for row in task['activity']['sessions']} == {'codex', 'claude'}
    assert {row['file'] for row in task['activity']['sessions']} == {'01.APP/OWNED.py'}
    assert task['status'] == 'WIP'
    assert time.monotonic() - started < 10


def test_editing_installed_owned_file_flips_flag_without_marking_work_done(tmp_path, monkeypatch):
    stamp = time.time() + 1
    _root, _home, file, api, options = setup(tmp_path, monkeypatch, installed_at=stamp)
    task = api.listTasks()[0]
    assert 'activity' in task, 'existing Work row has no installed-file observation'
    assert task['activity']['touched_after_install'] is False
    file.write_text('edited', encoding='utf-8')
    os.utime(file, (stamp + 1, stamp + 1))
    assert api.listTasks()[0]['activity']['touched_after_install'] is True
    assert api.listTasks()[0]['status'] == 'PLANNED'
    options['activity']['installed_at'] = stamp + 2
    assert api.listTasks()[0]['activity']['touched_after_install'] is False


def test_prompt_reasoning_and_private_paths_never_enter_observer_state(tmp_path, monkeypatch):
    root, home, _file, api, _options = setup(tmp_path, monkeypatch)
    a, b = logs(home)
    write(a, *codex(root))
    write(b, claude(root), claude(root, file='20.CLIENTS/SECRET.dwg'),
          claude(root, file='60.PERSONAL/SECRET.txt'))
    task = api.listTasks()[0]
    assert 'activity' in task, 'no privacy-enforced runtime observer'
    from nodelang.workshop_activity import observer_for
    reader = observer_for(api.owner)
    state = repr(vars(reader)) + json.dumps(task['activity'])
    for forbidden in ('PRIVATE_PROMPT_CANARY', 'PRIVATE_REASONING_CANARY', '20.CLIENTS', '60.PERSONAL'):
        assert forbidden not in state
    assert {row['provider'] for row in task['activity']['sessions']} == {'codex','claude'}


@pytest.mark.parametrize('value', [
    {'owns':['../OUTSIDE.py']}, {'owns':['20.CLIENTS/*.dwg']},
    {'owns':['60.personal/SECRET.txt']}, {'owns':['C:/SECRET.txt']},
    {'owns':['.git/config']}, {'owns':['01.APP/../20.CLIENTS/*']},
    {'owns':['01.APP/FILE\nSECRET.py']}, {'owns':[],'installed_at':float('nan')},
    {'owns':[],'installed_at':True}, {'owns':[],'prompt':'private'},
])
def test_ownership_rejects_private_escape_or_unbounded_metadata(value):
    from nodelang.workshop_activity import ownership
    with pytest.raises(ValueError):
        ownership(value)


def test_partial_utf8_lines_and_shrink_are_read_once_without_retaining_raw_text(tmp_path, monkeypatch):
    root, home, _file, api, _options = setup(tmp_path, monkeypatch)
    a, _b = logs(home)
    write(a, *codex(root))
    api.listTasks()
    row = claude(root, file='01.APP/OWNED.py')
    row['message']['content'][0]['thinking'] = 'PRIVATE_REASONING_CANARY مشمش'
    _a, b = logs(home)
    write(b, {'sessionId':'claude-fixture','cwd':str(root)})
    from nodelang.workshop_activity import observer_for
    reader = observer_for(api.owner)
    reader.last_discovery = -float('inf')
    raw = json.dumps(row, ensure_ascii=False).encode()
    split = raw.index('م'.encode()) + 1
    with b.open('ab') as stream:
        stream.write(raw[:split])
    api.listTasks()
    assert 'PRIVATE_REASONING_CANARY' not in repr(vars(reader))
    with b.open('ab') as stream:
        stream.write(raw[split:] + b'\n')
    assert {r['provider'] for r in api.listTasks()[0]['activity']['sessions']} == {'codex','claude'}
    a.write_text('', encoding='utf-8')
    write(a, *codex(root, session='codex-replacement'))
    sessions = api.listTasks()[0]['activity']['sessions']
    assert 'codex-replacement' in {r['session'] for r in sessions}
    assert 'codex-fixture' not in {r['session'] for r in sessions}


def test_oversize_tail_drops_prompt_partial_and_keeps_latest_tool(tmp_path, monkeypatch):
    root, home, _file, api, _options = setup(tmp_path, monkeypatch)
    a, _b = logs(home)
    write(a, codex(root)[0], {'type':'prompt','text':'PRIVATE_PROMPT_CANARY' * 120000}, *codex(root)[1:])
    task = api.listTasks()[0]
    assert task['activity']['sessions'][0]['provider'] == 'codex'
    assert task['activity']['limited'] is True
    assert 'PRIVATE_PROMPT_CANARY' not in repr(vars(api.owner._workshop_activity))


def test_turn_end_and_completed_todos_never_promote_work_or_installed_status(tmp_path, monkeypatch):
    root, home, _file, api, _options = setup(tmp_path, monkeypatch)
    a, _b = logs(home)
    write(a, *codex(root))
    assert api.listTasks()[0]['status'] == 'WIP'
    stamp = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()) + 'Z'
    write(a, {'timestamp':stamp,'type':'response_item','payload':{'type':'function_call',
        'name':'update_plan','arguments':json.dumps({'plan':[{'step':'PRIVATE_PROMPT_CANARY','status':'completed'}]})}},
        {'timestamp':stamp,'type':'event_msg','payload':{'type':'task_complete'}})
    task = api.listTasks()[0]
    assert task['status'] == 'PLANNED'
    assert task['activity']['sessions'][0]['state'] == 'turn_ended'
    assert task['activity']['touched_after_install'] is False


@pytest.mark.parametrize('file', ['../OUTSIDE.py','20.CLIENTS/SECRET.dwg','60.PERSONAL/SECRET.txt'])
def test_private_cwd_and_file_escape_are_dropped_before_session_state(tmp_path, monkeypatch, file):
    root, home, _file, api, _options = setup(tmp_path, monkeypatch)
    a, b = logs(home)
    write(a, *codex(root, file=file))
    write(b, claude(root / '20.CLIENTS'))
    task = api.listTasks()[0]
    assert task['activity']['sessions'] == []
    state = repr(vars(api.owner._workshop_activity))
    assert 'SECRET' not in state and '20.CLIENTS' not in state and '60.PERSONAL' not in state


def test_codex_to_claude_handoff_is_metadata_only_and_emitted_once(tmp_path, monkeypatch):
    root, home, _file, api, _options = setup(tmp_path, monkeypatch)
    a, b = logs(home)
    write(a, *codex(root, at=time.time()-3))
    stamp = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(time.time()-2)) + 'Z'
    write(a, {'timestamp':stamp,'type':'event_msg','payload':{'type':'task_complete'}})
    write(b, claude(root))
    entries = []
    monkeypatch.setattr(api, 'history', lambda: SimpleNamespace(append=lambda *args, **kwargs: entries.append(kwargs)))
    api.owner.universal_registry = SimpleNamespace(workshop_category_roots={'note':'category:note'})
    api.listTasks()
    api.listTasks()
    assert len(entries) == 1
    assert entries[0]['content'] == 'codex → claude on work:real-row'
    assert entries[0]['refs'] == ('work:real-row',)
    assert 'PRIVATE' not in json.dumps(entries)


def test_missing_ownership_is_unknown_and_other_rows_do_not_inherit_activity(tmp_path, monkeypatch):
    root, home, _file, api, options = setup(tmp_path, monkeypatch)
    a, _b = logs(home)
    write(a, *codex(root))
    options['activity']['owns'] = []
    task = api.listTasks()[0]
    assert task['activity']['ownership'] == 'unknown'
    assert task['activity']['sessions'] == [] and task['status'] == 'PLANNED'
    options['activity']['owns'] = ['01.APP/OTHER.py']
    assert api.listTasks()[0]['activity']['sessions'] == []


def test_wildcard_ownership_walks_only_the_selected_workspace(tmp_path, monkeypatch):
    from nodelang.workshop_activity import WorkshopActivity
    workspace = tmp_path / 'WORKSPACE'
    workspace.mkdir()
    (workspace / 'OWNED.py').write_text('owned', encoding='utf-8')
    (tmp_path / 'SIBLING.py').write_text('outside', encoding='utf-8')
    reader = WorkshopActivity(workspace)
    walked = []
    real_walk = os.walk
    def walk(start, **kwargs):
        walked.append(Path(start))
        return real_walk(start, **kwargs)
    monkeypatch.setattr(os, 'walk', walk)
    assert set(reader._files(['**'])) == {'OWNED.py'}
    assert walked == [workspace]


def test_excluded_workspace_never_creates_an_observer(tmp_path):
    from nodelang.workshop_activity import observer_for
    owner = SimpleNamespace(universal_workspace_root=tmp_path / '20.CLIENTS')
    assert observer_for(owner) is None
    assert not hasattr(owner, '_workshop_activity')


def test_unrelated_project_is_ignored_without_reporting_a_read_failure(tmp_path):
    from nodelang.workshop_activity import WorkshopActivity
    reader = WorkshopActivity(tmp_path / 'WORKSPACE')
    assert reader.relative(str(tmp_path / 'OTHER')) is None
    assert reader.unavailable is False


def test_conflicting_native_session_and_file_association_is_unknown(tmp_path, monkeypatch):
    root, home, _file, api, _options = setup(tmp_path, monkeypatch)
    write(logs(home)[0], *codex(root))
    monkeypatch.setattr(agent_declarations, 'declarations', lambda owner, **kw: [
        {'app':'codex','native_session_id':'codex-fixture','request_id':'work:other','current':True,'status':'working'}])
    task = api.listTasks()[0]
    assert task['activity']['sessions'][0]['association_conflict'] is True
    assert task['status'] == 'PLANNED'


def test_exact_owned_file_does_not_scan_unrelated_folders(tmp_path, monkeypatch):
    from nodelang.workshop_activity import WorkshopActivity
    owned = tmp_path / 'OWNED.py'
    owned.write_text('owned', encoding='utf-8')
    def no_walk(*args, **kwargs):
        pytest.fail('Exact owned file must not walk unrelated folders')
    monkeypatch.setattr(os, 'walk', no_walk)
    assert WorkshopActivity(tmp_path)._files(['OWNED.py']) == {'OWNED.py':owned.stat().st_mtime}


def test_workspace_root_declaration_does_not_break_the_board(tmp_path, monkeypatch):
    root, home, _file, api, options = setup(tmp_path, monkeypatch)
    options.clear()
    monkeypatch.setattr(agent_declarations, 'declarations', lambda owner, **kw: [
        {'request_id':'work:real-row','app':'codex','status':'working','current':True,'paths':[str(root)]}])
    write(logs(home)[0], *codex(root))
    task = api.listTasks()[0]
    assert task['activity']['ownership'] == 'known'
    assert task['activity']['sessions'][0]['file'] == '01.APP/OWNED.py'


def test_observation_preserves_committed_claim_for_unobserved_providers(tmp_path, monkeypatch):
    root, _home, _file, api, _options = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(agent_declarations, 'declarations', lambda owner, **kw: [
        {'request_id':'work:real-row','app':'gemini','status':'working','current':True,'paths':[str(root)]}])
    row = api._works()[0]
    row['operational']['current_state_label'] = 'claimed'
    assert api.listTasks()[0]['status'] == 'WIP'


def test_codex_shell_tool_uses_exact_declared_session_without_retaining_command(tmp_path, monkeypatch):
    root, home, _file, api, _options = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(agent_declarations, 'declarations', lambda owner, **kw: [
        {'request_id':'work:real-row','app':'codex','status':'working','current':True,
         'native_session_id':'codex-fixture','paths':[str(root)]}])
    rows = codex(root)
    rows[1]['payload'].update(name='functions.exec', arguments=json.dumps({'cmd':'PRIVATE_PROMPT_CANARY'}))
    write(logs(home)[0], *rows)
    activity = api.listTasks()[0]['activity']
    assert activity['sessions'][0]['tool'] == 'functions.exec'
    assert activity['sessions'][0]['file'] is None
    assert 'PRIVATE_PROMPT_CANARY' not in repr(vars(api.owner._workshop_activity))
    monkeypatch.setattr(agent_declarations, 'declarations', lambda owner, **kw: [])
    assert api.listTasks()[0]['activity']['sessions'] == []


def test_opencode_uses_the_existing_transport_reader_and_revalidates_its_metadata(tmp_path):
    from nodelang.workshop_activity import WorkshopActivity
    reader = WorkshopActivity(tmp_path)
    calls = []
    events = [{'provider':'opencode','session':'ses_fixture','tool':'edit','file':file,
               'state':'working','at':time.time()-1} for file in ('01.APP/OWNED.py','20.CLIENTS/SECRET.dwg','../OUTSIDE')]
    transport = SimpleNamespace(activity=lambda *args: calls.append(args) or {'status':'ok','events':events})
    reader.read_opencode(transport, ['ses_fixture'])
    reader.read_opencode(transport, ['ses_fixture'])
    assert len(calls) == 1 and calls[0] == ('ses_fixture', tmp_path)
    assert reader.project('work', {'owns':['01.APP/*']})['sessions'][0]['provider'] == 'opencode'
    assert 'SECRET' not in repr(vars(reader))


def test_fileless_tools_new_turns_and_foreign_cwd_are_honestly_unassociated(tmp_path, monkeypatch):
    root, home, _file, api, _options = setup(tmp_path, monkeypatch)
    a, _b = logs(home)
    write(a, *codex(root, at=time.time()-2))
    assert api.listTasks()[0]['status'] == 'WIP'
    stamp = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime())+'Z'
    write(a, {'timestamp':stamp,'type':'response_item','payload':{'type':'function_call',
        'name':'exec_command','arguments':json.dumps({'cmd':'PRIVATE_PROMPT_CANARY'})}})
    task = api.listTasks()[0]
    assert task['status'] == 'PLANNED'
    assert task['activity']['sessions'][0]['state'] == 'unassociated'
    assert task['activity']['sessions'][0]['associated'] is False
    write(a, *codex(root)[1:], {'timestamp':stamp,'type':'event_msg','payload':{'type':'task_started'}})
    assert api.listTasks()[0]['activity']['sessions'][0]['state'] == 'unassociated'
    write(a, *codex(root)[1:], {'timestamp':stamp,'type':'turn_context','payload':{'cwd':str(tmp_path / 'OUTSIDE')}})
    assert api.listTasks()[0]['activity']['sessions'][0]['state'] == 'unassociated'


def test_slow_opencode_read_never_holds_codex_and_claude_rows(tmp_path, monkeypatch):
    from contextlib import nullcontext
    root, home, _file, api, _options = setup(tmp_path, monkeypatch)
    a, b = logs(home)
    write(a, *codex(root))
    write(b, claude(root))
    entered, release = threading.Event(), threading.Event()
    def activity(*args):
        entered.set()
        assert release.wait(5)
        return {'status':'ok','events':[]}
    api.owner._cloud_relay_transport = SimpleNamespace(create_channel=lambda:
        nullcontext(SimpleNamespace(activity=activity)))
    monkeypatch.setattr(agent_declarations, 'declarations', lambda owner, **kw: [
        {'app':'opencode','native_session_id':'ses_slow','request_id':'other','current':True,'status':'working'}])
    try:
        start = time.monotonic()
        row = api.listTasks()[0]
        assert time.monotonic()-start < 1
        assert entered.wait(1)
        assert {item['provider'] for item in row['activity']['sessions']} == {'codex','claude'}
    finally:
        release.set()
        api.owner._workshop_activity.opencode_worker.join(2)


@pytest.mark.parametrize('route', ['native-work', 'cloud-session'])
def test_board_activity_does_not_starve_delivery_transport(tmp_path, monkeypatch, route):
    import hashlib
    import shutil
    from nodelang.application_server import NativeWorkDelivery
    from nodelang.cloud_relay import RemoteSessionCaller
    from nodelang.session_link_transport import SessionLinkTransport

    _root, _home, _file, api, _options = setup(tmp_path, monkeypatch)
    assets = tmp_path / 'ASSETS'
    assets.mkdir()
    (assets / 'worker.mjs').write_text(r'''
import readline from 'node:readline';
import fs from 'node:fs';
import path from 'node:path';
const input=readline.createInterface({input:process.stdin,crlfDelay:Infinity});
input.on('line', async line=>{
 const r=JSON.parse(line), state=process.env.SESSION_LINK_STATE_DIR;
 const recipient={app:'claude',id:'court-peer',account:'court-account'};
 if(r.operation==='activity'){
  fs.writeFileSync(path.join(state,'ENTERED'),'');
  while(!fs.existsSync(path.join(state,'RELEASE'))){
   await new Promise(resolve=>setTimeout(resolve,10));
  }
 }
 const result=r.operation==='request'
  ? {status:'replied',recipient:r.recipient,reply:{text:'court reply'}}
  : {status:'ok',events:[],recipients:[recipient]};
 process.stdout.write(JSON.stringify({event:'result',...result})+'\n',()=>process.exit(0));
});
''', encoding='utf-8')
    state = tmp_path / 'STATE'
    transport = SessionLinkTransport(node_executable=Path(shutil.which('node')), state_dir=state)
    transport._assets = assets
    channels = []
    create = transport.create_channel
    def create_channel():
        channel = create()
        channel._assets = assets
        channels.append(channel)
        return channel
    monkeypatch.setattr(transport, 'create_channel', create_channel)
    api.owner._cloud_relay_transport = transport
    monkeypatch.setattr(agent_declarations, 'declarations', lambda owner, **kw: [
        {'app':'opencode','native_session_id':'ses_busy','request_id':'other','current':True,'status':'working'}])
    delivery = NativeWorkDelivery.__new__(NativeWorkDelivery)
    delivery._owner, delivery._transport, delivery._stop = api.owner, transport, threading.Event()
    delivery._admitted = lambda job: True
    delivery._settle = lambda job, result: result
    api.owner.native_work_delivery = delivery
    try:
        api.listTasks()
        deadline = time.monotonic() + 2
        while not (state / 'ENTERED').exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert (state / 'ENTERED').exists(), 'activity helper never entered'
        if route == 'native-work':
            result = delivery._deliver({'app':'claude','fingerprint':hashlib.sha256(b'court-peer').hexdigest(),
                'text':'court message'})
        else:
            caller = RemoteSessionCaller(account=lambda: 'court-account', transport=transport)
            result = caller('court-account', 'send_to_session', {'id':'court-peer','text':'court message'})['delivery']
        assert result['status'] == 'replied', result
        assert api.owner._workshop_activity.opencode_worker.is_alive(), 'activity was not held during delivery'
        assert not transport._closed.is_set()
    finally:
        state.mkdir(exist_ok=True)
        (state / 'RELEASE').touch()
        api.owner._workshop_activity.opencode_worker.join(4)
        transport.close()
    assert len(channels) == 1
    assert channels[0]._closed.is_set(), 'owned activity channel leaked'
    assert not channels[0]._processes


def test_closed_delivery_transport_marks_observation_unavailable(tmp_path, monkeypatch):
    from nodelang.workshop_activity import WorkshopActivity
    reader = WorkshopActivity(tmp_path)
    def create_channel():
        raise ValueError('transport closed')
    reader.poll_opencode(SimpleNamespace(create_channel=create_channel), ['ses_closed'])
    reader.opencode_worker.join(2)
    assert not reader.opencode_worker.is_alive()
    assert reader.unavailable


def test_real_ledger_revision_and_declared_owned_files_need_no_manual_install_timestamp(tmp_path, monkeypatch):
    root, _home, file, api, options = setup(tmp_path, monkeypatch)
    def git(*args):
        return subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True,text=True).stdout.strip()
    git('init','-q')
    git('add','01.APP/OWNED.py')
    git('-c','user.name=AgentTrail court','-c','user.email=court@local.invalid','commit','-qm','fixture')
    revision = git('rev-parse','HEAD')
    ledger = root / '70.COMPANY/72.HANDOFFS/72.03-ARCHHUB-INTEGRATED-REPAIR/DELIVERY-STATUS.md'
    ledger.parent.mkdir(parents=True)
    ledger.write_text('| F29 | date | request | behavior | owner | INSTALLED 20261024-1200-'+revision[:8]+' |\n', encoding='utf-8')
    row = api._works()[0]
    row['interfaces']['external-key'] = {'value':'F29'}
    options.clear()
    monkeypatch.setattr(agent_declarations, 'declarations', lambda owner, **kw: [
        {'app':'codex','request_id':'F29','paths':[str(file)],'current':False,'status':'done'}])
    task = api.listTasks()[0]
    assert task['activity']['installed_revision'] == revision[:8]
    assert not task['activity']['touched_after_install']
    file.write_text('edited after installation', encoding='utf-8')
    assert api.listTasks()[0]['activity']['touched_after_install']
    ledger.write_text('| F29 | date | request | behavior | owner | PARTLY INSTALLED build; Was: INSTALLED 20261024-1200-'+revision[:8]+' |\n', encoding='utf-8')
    task = api.listTasks()[0]
    assert task['activity']['installed_revision'] is None
    assert not task['activity']['touched_after_install']


def test_stale_row_nudge_uses_the_existing_workshop_and_exact_declared_session(tmp_path, monkeypatch):
    _root, _home, _file, api, options = setup(tmp_path, monkeypatch)
    options['activity']['updated_at'] = time.time()-1300
    monkeypatch.setattr(agent_declarations, 'declarations', lambda owner, **kw: [
        {'app':'codex','agent':'Codex court','request_id':'work:real-row','current':True,
         'status':'working','native_session_id':'codex-fixture'}])
    entries = []
    monkeypatch.setattr(api, 'history', lambda: SimpleNamespace(append=lambda *args, **kwargs: entries.append(kwargs)))
    api.owner.universal_registry = SimpleNamespace(workshop_category_roots={'note':'category:note'})
    assert api.listTasks()[0]['activity']['stale']
    assert entries[0]['content'].startswith('To Codex court:\nRe-verify row status on work:real-row;')
    assert entries[0]['refs'] == ('work:real-row',)
    assert entries[0]['idempotency_key'].startswith('activity-stale:')


def test_http_real_work_options_activity_handoff_and_privacy(served, tmp_path, monkeypatch):
    from tests_replica.test_workshop_assign_to_agent import _work, _scope, _http
    server, _descriptor, _provider = served
    home = tmp_path / 'HOME'
    monkeypatch.setenv('CODEX_HOME', str(home / '.codex'))
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(home / '.claude'))
    work = _work(server, 'agenttrail-http', title='Runtime evidence on an existing Work')['created_root']
    owned = tmp_path / '01.APP/OWNED.py'
    owned.parent.mkdir()
    owned.write_text('original', encoding='utf-8')
    installed = time.time()+1
    def call(name, args):
        status, result = _http(server, '/api/universal/workshop', {'action':'data-api','function':name,
            'args':args,'root':server.universal_registry.workshop_root,'scope':_scope(server),'request_id':name})
        assert status == 200, result
        return result['result']
    call('setTaskActivity', [work, {'owns':['01.APP/*.py'],'installed_at':installed}])
    revision = server.universal_store.revision
    a, b = logs(home)
    write(a, *codex(tmp_path, at=time.time()-3))
    write(b, claude(tmp_path, at=time.time()-3))
    started = time.monotonic()
    live_row = next(item for item in call('listTasks', []) if item['id'] == work)
    assert {session['provider'] for session in live_row['activity']['sessions']} == {'codex','claude'}
    latency = time.monotonic() - started
    assert latency < 10
    assert server.universal_store.revision == revision, 'observations must not commit graph revisions'
    owned.write_text('edited', encoding='utf-8')
    os.utime(owned, (installed+1, installed+1))
    changed = next(row for row in call('listTasks', []) if row['id'] == work)
    assert changed['activity']['touched_after_install']
    (tmp_path / 'AGENTTRAIL-ROW.json').write_text(json.dumps({'row':changed,
        'latency_seconds':latency, 'graph_revision_unchanged':server.universal_store.revision == revision}), encoding='utf-8')
    stamp = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(time.time()-2))+'Z'
    write(a, {'timestamp':stamp,'type':'event_msg','payload':{'type':'task_complete'}})
    write(b, claude(tmp_path), claude(tmp_path, file='60.PERSONAL/SECRET.txt'))
    call('listTasks', [])
    messages = call('listWorkshopMessages', [])['messages']
    assert any(message['text'] == 'codex → claude on '+work for message in messages)
    assert not any('PRIVATE_' in message['text'] or '60.PERSONAL' in message['text'] for message in messages)
    status, _refusal = _http(server, '/api/universal/workshop', {'action':'data-api','function':'setTaskActivity',
        'args':[work, {'owns':['20.CLIENTS/SECRET.dwg']}],'root':server.universal_registry.workshop_root,
        'scope':_scope(server),'request_id':'reject-private'})
    assert status == 400
