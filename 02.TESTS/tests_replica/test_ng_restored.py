"""Restored without the graph: host packages, Watcher and their approvals, each in one plain file under settings/."""
import base64
import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def server(tmp_path, monkeypatch):
    for name in ('LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'HOME'):
        monkeypatch.setenv(name, str(tmp_path / name))
    from nodelang.nograph_server import NoGraphServer
    instance = NoGraphServer(tmp_path / 'state')
    yield instance
    instance.httpd.server_close()  # never started: shutdown() would wait for a serve loop


def call(server, function, *args, request_id='r1'):
    from nodelang.nograph_server import r_workshop
    req = SimpleNamespace(method='POST', body={'action': 'data-api', 'function': function, 'args': list(args),
                                                'request_id': request_id})
    return r_workshop(server, req)['result']


SKILL = '---\nname: Door schedule\ndescription: Lists doors\n---\nRead the doors and list them.\n'


def test_host_skill_import_review_approve_survives_reopen(server):
    row = call(server, 'importHostSkill', {'host': 'Revit', 'text': SKILL})
    assert row['format'] == 'SKILL.md' and row['enabled'] is False
    card = call(server, 'setHostSkillEnabled', row['id'], True, request_id='enable-1')
    assert card['approvalKind'] == 'hostskills' and card['status'] == 'pending'
    assert [c['id'] for c in call(server, 'listApprovals')] == [card['id']]
    done = call(server, 'answerApproval', 'hostskills', card['id'], card['input_digest'], 'approve')
    assert done['status'] == 'approved'
    stored = json.loads((server.state_dir / 'settings' / 'host-packages.json').read_text(encoding='utf-8'))
    record = stored['packages'][row['id']]
    assert record['enabled'] is True and record['descriptor'] == SKILL
    assert call(server, 'readHostSkills')['hostSkills'][0]['enabled'] is True


def test_host_package_refusals_come_back_as_reasons(server):
    bad = call(server, 'inspectConnectorBundle', {'name': 'x.json', 'base64': base64.b64encode(b'[]').decode()})
    assert bad['ok'] is False and 'bounded UTF-8 manifest' in bad['error']
    card = call(server, 'importHostSkill', {'host': 'Revit', 'text': SKILL})
    stale = call(server, 'answerApproval', 'hostskills', 'app:host-package-review:nope', 'x', 'approve')
    assert stale['ok'] is False and card['id']


def test_watcher_edit_propose_approve_writes_host_and_reads_back(server, monkeypatch):
    from nodelang import host_brokers
    wall = {'host': 'Revit', 'instance': 1, 'document': 'A.rvt', 'view': 'L1', 'views': ['L1'],
            'element': {'id': 'w1', 'label': 'Wall 1', 'revision': '7', 'start': [0, 0], 'end': [10, 0],
                        'lengthMm': 150.0, 'thicknessMm': 200.0}}
    host = {'now': json.loads(json.dumps(wall)), 'writes': []}

    def read(name, **_kw):
        return json.loads(json.dumps(host['now']))

    def write(payload):
        host['writes'].append(payload)
        shift = payload['offsetMm'] / 15.0
        for key in ('start', 'end'):
            host['now']['element'][key][1] += shift

    monkeypatch.setattr(host_brokers, 'watcher_read', read)
    monkeypatch.setattr(host_brokers, 'watcher_write', write)
    assert call(server, 'readWatcher')['status'].startswith('Select')
    assert call(server, 'setWatcherHost', 'Revit')['elementId'] == 'w1'
    assert call(server, 'editWall', 2)['pendingY'] == 2
    assert len(call(server, 'addDimension', {'from': {'x': 0, 'y': 0}, 'to': {'x': 10, 'y': 0}}, request_id='d1')['dimensions']) == 1
    card = call(server, 'proposeWatcherEdit', request_id='p1')
    assert card['approvalKind'] == 'watcher' and card['status'] == 'pending'
    assert card['id'] in [c['id'] for c in call(server, 'listApprovals')]
    done = call(server, 'answerApproval', 'watcher', card['id'], card['input_digest'], 'approve')
    assert done['status'] == 'approved' and host['writes'][0]['offsetMm'] == 30.0
    view = call(server, 'readWatcher')
    assert view['applied'] is True and view['wallY'] == 2 and len(view['dimensions']) == 1
    assert (server.state_dir / 'settings' / 'watcher.json').is_file()


def test_social_finish_enrols_the_provider_confirmed_account_into_the_protected_store(server, monkeypatch):
    from nodelang import model_router, social_connections
    from nodelang.nograph_server import r_social_connection
    saved = []
    monkeypatch.setattr(social_connections.broker, 'current_status', lambda provider: {'name': 'Ahmed'})
    monkeypatch.setattr(social_connections.broker, 'take_verified', lambda provider: ('urn:li:person:abc', 'token-value'))
    monkeypatch.setattr(model_router, 'save_social_credential', lambda body, **kw: saved.append((body, kw)) or {'ok': True})
    monkeypatch.setattr(social_connections, 'connection', lambda provider, **kw: {'provider': provider, 'state': 'connected'})
    result = r_social_connection(server, SimpleNamespace(method='POST', body={'provider': 'linkedin', 'action': 'finish'}))
    assert result['connection']['state'] == 'connected'
    assert saved[0][0]['vault_entry'] == 'social-linkedin-abc' and saved[0][1]['verified'] is True


def test_account_profile_and_billing_use_the_cloud_and_one_local_file(server, monkeypatch):
    from nodelang import settings_owner
    from nodelang.nograph_server import r_settings_action
    calls = []

    def cloud(method, path, body=None, **_kw):
        calls.append((method, path))
        return {'/v1/me': {'email': 'a@b.c', 'user_id': 'u1', 'plan': 'solo', 'full_name': 'Ahmed'},
                '/v1/companies/mine': {'companies': []}, '/v1/billing/plans': {'tiers': [{'tier': 'solo'}]},
                '/v1/companies/invites/mine': {'invitations': []}}.get(path, {})
    monkeypatch.setattr(settings_owner, 'cloud_call', cloud)

    def action(function, *args):
        return r_settings_action(server, SimpleNamespace(method='POST', body={'function': function, 'args': list(args)}))['result']
    assert action('read')['profile']['plan'] == 'Personal'
    assert action('updateProfile', {'firm': 'Albayaty'})['profile'] == {'firm': 'Albayaty'}
    stored = json.loads((server.state_dir / 'settings' / 'account.json').read_text(encoding='utf-8'))
    assert stored['account:u1']['profile'] == {'firm': 'Albayaty'}
    assert action('read')['profile']['firm'] == 'Albayaty' and ('GET', '/v1/me') in calls


def test_signed_out_settings_still_open(server, monkeypatch):
    from nodelang import settings_owner
    from nodelang.nograph_server import r_settings_action
    from nodelang.universal_cell import InvalidCell

    def signed_out(*_a, **_kw):
        raise InvalidCell('Not signed in. Sign in with your browser, then retry.')
    monkeypatch.setattr(settings_owner, 'cloud_call', signed_out)
    result = r_settings_action(server, SimpleNamespace(method='POST', body={'function': 'read', 'args': []}))['result']
    assert result['settingsScope'] == 'User' and 'Not signed in' in result['controlErrors']['account']


def test_watcher_read_opens_no_transaction_in_revit_and_write_does(monkeypatch):
    from nodelang import clean_revit_adapter, host_brokers
    sent = []
    monkeypatch.setattr(clean_revit_adapter, 'broker_sessions', lambda service: [{'port': 7}])
    monkeypatch.setattr(clean_revit_adapter, 'broker_call', lambda service, path, body, **kw: sent.append(body) or {'status': 'ok', 'result': {}})
    host_brokers.watcher_read('Revit')
    host_brokers.watcher_write({'source': {'host': 'Revit', 'instance': 7, 'element': {'id': 'w'}}, 'offsetMm': 30.0})
    assert sent[0]['transaction'] is False and 'transaction' not in sent[1]


def test_brain_remember_edit_forget_export_without_the_graph(server, tmp_path):
    from nodelang.nograph_server import r_brain

    def brain(path, **body):
        return r_brain(server, SimpleNamespace(method='POST', path='/api/universal/' + path, body=body))
    assert brain('brain-remember', text='Doors are 900 mm in Tower A')['written'] == 1
    fact = brain('brain-export')['facts']['folders'][0]['facts'][0]['id']
    assert brain('brain-edit', id=fact, text='Doors are 1000 mm in Tower A')['edited'] is True
    assert brain('brain-export')['facts']['folders'][0]['facts'][0]['body'] == 'Doors are 1000 mm in Tower A'
    assert brain('brain-publish', id=fact)['ok'] is False
    assert brain('brain-forget', id=fact)['ok'] is True
    assert brain('brain-export')['facts']['held'] == 0
    stored = json.loads((tmp_path / 'LOCALAPPDATA' / 'ArchHub' / 'settings' / 'brain.json').read_text(encoding='utf-8'))
    assert stored['facts'][0]['forgotten'] is True   # forget is soft: the fact is kept


def test_providers_poll_starts_the_opencode_cli_once_per_30_s(server, monkeypatch):
    """Gate PERF: each 5 s Providers poll ran `opencode run --help` and `opencode auth list` (385 MB at idle)."""
    import time
    from nodelang import model_router
    calls = []
    monkeypatch.setattr(model_router, 'probe_opencode_status', lambda exe: calls.append(exe) or {'installed': True, 'signed_in': True})
    first = [server.opencode_status('C:/oc/opencode.exe') for _ in range(5)]
    deadline = time.monotonic() + 5
    while not calls and time.monotonic() < deadline:
        time.sleep(0.02)
    time.sleep(0.1)
    later = [server.opencode_status('C:/oc/opencode.exe') for _ in range(5)]
    assert calls == ['C:/oc/opencode.exe']
    assert not first[0].get('signed_in') and later[-1]['signed_in'] is True

def test_the_desktop_builds_its_updater_and_closes_it(server, tmp_path):
    """Fresh-profile gate: `update : unavailable (TypeError)` - the NOGRAPH launcher omitted request_restart."""
    from nodelang.application_update import ApplicationUpdate
    from nodelang.nograph_launcher import _arm_staged_update
    app = tmp_path / 'app'
    app.mkdir()
    lines = []
    update = ApplicationUpdate(tmp_path / 'state', app, request_restart=lambda: None, report=lines.append)
    assert update.status()['restart_supported'] is True
    _arm_staged_update(update, tmp_path / 'state', app, None, relaunch=False)  # nothing staged, quit: no arm, closed
    assert update.status()['restart_supported'] is False

def test_one_agent_row_per_app_with_its_session_count(server, monkeypatch):
    """Plate 077: five Claude Code sessions are one 'Claude Code' row reading 5; no task reads Idle."""
    from nodelang import agent_runtime_registry, nograph_server
    monkeypatch.setattr(agent_runtime_registry, 'discover_runtime_processes', lambda: {
        'processes': [{'runtime': 'claude', 'pid': p} for p in (1, 2, 3, 4, 5)] + [{'runtime': 'codex', 'pid': 9}], 'complete': True})
    monkeypatch.setattr(nograph_server, '_declarations', lambda: [])
    rows = {r['runtime']: r for r in nograph_server._list_agents()}
    assert rows['claude']['session_count'] == 5 and rows['codex']['session_count'] == 1
    assert rows['claude']['task'] == 'Idle' and len(rows) == 2


def test_programs_read_one_plain_status():
    from nodelang.nograph_server import _plain_status
    assert [_plain_status(s) for s in ('connected', 'running', 'installed', 'absent', 'needs-sign-in')] == [
        'Connected', 'Installed · not running', 'Installed · not running', 'Not installed', 'Sign in to connect']

def test_nine_book_starters_are_real_workflows_ending_at_an_approve_gate(server, tmp_path):
    """Book ch.12: each built-in starter opens as its own .archhub file; no counters before real runs."""
    from nodelang import starters
    from nodelang.session_files import SessionFiles, read_document
    rows = starters.listing([{'id': 'revit', 'state': 'connected'}, {'id': 'acad', 'state': 'absent'}])
    assert [r['title'] for r in rows][:3] == ['Submittal turnaround', 'Redline QC with proof table', 'Sheets production']
    assert len(rows) == 9 and all(r['run_count'] is None and r['stops_at'] for r in rows)
    assert rows[3]['needs'] == ['AutoCAD'] and rows[0]['needs'] == []
    for row in rows:
        opened = SessionFiles(tmp_path / 'sessions').dispatch({'action': 'starter', 'id': row['id']})
        doc = read_document(opened['path'])
        assert doc['nodes'][-1]['type'] == 'approval.gate' and len(doc['wires']) == len(doc['nodes']) - 1