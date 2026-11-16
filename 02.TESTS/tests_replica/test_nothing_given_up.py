"""NOTHING-GIVEN-UP: Social media, Community and Plan & access answered by file owners.

Every check goes through the real NoGraphServer HTTP routes (or the native MCP tool the
agent uses) in an isolated profile. No real account, credential or provider is touched:
the one success path uses a recording host in place of the network.
"""
import hashlib
import json
import threading
from http.client import HTTPConnection
from types import SimpleNamespace

import pytest

import test_node_params as fixtures

profile = fixtures.profile


def _exchange(connection, method, path, body, headers):
    connection.request(method, path, None if body is None else json.dumps(body).encode('utf-8'), headers)
    response = connection.getresponse()
    raw = response.read()
    return response.status, (json.loads(raw.decode('utf-8')) if raw else {})


def _open(state_dir):
    from nodelang.nograph_server import COOKIE, NoGraphServer
    server = NoGraphServer(state_dir)
    server.thread = threading.Thread(target=server.httpd.serve_forever, daemon=True)
    server.thread.start()
    connection = HTTPConnection('127.0.0.1', server.port, timeout=30)
    status, signed = _exchange(connection, 'POST', '/api/universal/session', {},
                               {'Content-Type': 'application/json', 'X-ArchHub-Sign-In': '1',
                                'Cookie': '%s=%s' % (COOKIE, server._cookie_token)})
    assert status == 200 and signed['ok'] is True
    headers = {'Content-Type': 'application/json', 'X-ArchHub-Session': signed['token'], 'X-ArchHub-CSRF': signed['csrf']}
    return SimpleNamespace(server=server, post=lambda path, body: _exchange(connection, 'POST', path, body, headers),
                           get=lambda path: _exchange(connection, 'GET', path, None, headers))


@pytest.fixture
def app(profile):
    from nodelang.session_files import profile_directory
    opened = _open(profile_directory())
    opened.state_dir = profile_directory()
    try:
        yield opened
    finally:
        opened.server.close()


def social(app, op, *args):
    return app.post('/api/universal/social-surface', {'op': op, 'args': list(args)})


# ---- Social media -----------------------------------------------------------------

def test_empty_profile_never_invents_social_content(app):
    status, answer = social(app, 'get_state')
    assert status == 200
    assert answer['state']['social']['inbox'] == [] and answer['state']['social']['drafts'] == []
    assert answer['state']['social']['office']['name'] == ''
    status, answer = app.get('/api/universal/social-approvals')
    assert status == 200 and answer['items'] == []


def test_office_and_drafts_survive_a_restart_and_archive(app):
    assert social(app, 'update_office_page', {'name': 'User supplied office'})[0] == 200
    status, saved = social(app, 'save_social_draft', {'platform': 'LinkedIn', 'text': 'User supplied post', 'title': '', 'kind': 'post'})
    assert status == 200 and saved['result']['status'] == 'Draft'
    draft = saved['result']['id']
    held = json.loads((app.state_dir / 'settings' / 'social.json').read_text(encoding='utf-8'))
    assert held['state']['social']['drafts'][0]['text'] == 'User supplied post'
    app.server.close()
    reopened = _open(app.state_dir)
    app.server = reopened.server  # the fixture closes the live server
    state = social(reopened, 'get_state')[1]['state']['social']
    assert state['office']['name'] == 'User supplied office'
    assert state['drafts'][0]['id'] == draft and state['drafts'][0]['status'] == 'Draft'
    assert social(reopened, 'discard_social_draft', draft)[1]['state']['social']['drafts'][0]['status'] == 'Archived'


def test_draft_validation_refuses_without_writing(app):
    path = app.state_dir / 'settings' / 'social.json'
    for values in ({'platform': 'LinkedIn', 'text': '  '}, {'platform': 'Myspace', 'text': 'x'},
                   {'platform': 'LinkedIn', 'text': 'x', 'schedule': 'tomorrow'}, {'platform': 'LinkedIn', 'text': 'x', 'author': 'me'}):
        status, answer = social(app, 'save_social_draft', values)
        assert status == 400 and answer['error']
    status, answer = social(app, '_save', [])
    assert status == 400 and 'registered social operation' in answer['error']
    status, answer = social(app, 'add_slide', 'extra')
    assert status == 400 and 'arguments changed' in answer['error']
    assert not path.exists()


def test_slides_persist_without_demo_content(app):
    first = social(app, 'add_slide')[1]['result']
    second = social(app, 'add_slide')[1]['result']
    assert first['title'] == first['body'] == ''
    social(app, 'edit_slide', second['id'], {'title': 'User title', 'body': 'User story', 'layout': 'Plan'})
    social(app, 'reorder_slide', second['id'], first['id'])
    slides = social(app, 'get_state')[1]['state']['presentation']['slides']
    assert slides[0]['title'] == 'User title'
    social(app, 'remove_slide', first['id'])
    assert len(social(app, 'get_state')[1]['state']['presentation']['slides']) == 1
    assert social(app, 'edit_slide', second['id'], {'layout': 'Poster'})[0] == 400


def test_real_source_file_is_read_and_hashed_and_private_web_refused(app, tmp_path):
    raw = b'Actual source first line\nActual source second line'
    source = tmp_path / 'SOURCE.txt'
    source.write_bytes(raw)
    status, answer = social(app, 'read_content_source', 'File', str(source))
    assert status == 200
    assert answer['result']['transcript'] == ['Actual source first line', 'Actual source second line']
    assert answer['result']['sha256'] == hashlib.sha256(raw).hexdigest() and answer['result']['keyFrames'] == []
    assert social(app, 'read_content_source', 'File', str(tmp_path / 'MISSING.txt'))[0] == 400
    social(app, 'set_source_read_seconds', 2)
    before = (app.state_dir / 'settings' / 'social.json').read_bytes()
    for url in ('http://localhost', 'https://127.0.0.1', 'https://user:password@example.com'):
        assert social(app, 'read_content_source', 'Web', url)[0] == 400
    assert (app.state_dir / 'settings' / 'social.json').read_bytes() == before


def test_prototype_baseline_uses_supplied_measurements(app):
    assert social(app, 'rebaseline_prototype')[0] == 400
    social(app, 'set_prototype', {'measurements': '0.2,0.4', 'threshold': 0.05})
    assert social(app, 'rebaseline_prototype')[1]['result']['baseline'] == pytest.approx(0.3)
    social(app, 'set_prototype', {'measurements': '0.5,0.7'})
    result = social(app, 'check_verdict_pattern')[1]['result']
    assert result['features'][-1]['value'] == pytest.approx(0.3) and 'exceeds' in result['pattern']
    for values in ({'measurements': 'nan,0.4'}, {'linkedModel': 'yes'}):
        assert social(app, 'set_prototype', values)[0] == 400


def test_calendar_consent_transcript_and_task_binding(app, tmp_path):
    from nodelang.nograph_server import _create_task
    calendar = tmp_path / 'MEETING.ics'
    calendar.write_text('BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:fixture-event\nSUMMARY:Source meeting\n'
                        'URL:https://meet.google.com/fixture\nEND:VEVENT\nEND:VCALENDAR', encoding='utf8')
    social(app, 'import_meeting_calendar', str(calendar))
    assert social(app, 'set_meeting', {'calendarId': 'fixture-event'})[1]['result']['title'] == 'Source meeting'
    transcript = tmp_path / 'TRANSCRIPT.vtt'
    transcript.write_text('WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nActual captured words', encoding='utf8')
    assert social(app, 'import_meeting_transcript', str(transcript))[0] == 400
    social(app, 'set_meeting', {'consent': True})
    turns = social(app, 'import_meeting_transcript', str(transcript))[1]['result']
    assert turns[0]['text'] == 'Actual captured words' and turns[0]['speaker'] == '' and turns[0]['at'] == '00:00:01.000'
    # A meeting action binds only to a task the Workshop owner holds.
    held = json.loads((app.state_dir / 'settings' / 'social.json').read_text(encoding='utf-8'))
    held['state']['meeting']['actions'] = ['Send the drawings']
    (app.state_dir / 'settings' / 'social.json').write_text(json.dumps(held), encoding='utf-8')
    social(app, 'set_meeting_action_owner', 0, 'Architect')
    status, answer = social(app, 'bind_meeting_task', 0, 'invented-task')
    assert status == 400 and 'not in this account' in answer['error']
    task = _create_task(app.server, 'Meeting action task')
    status, answer = social(app, 'bind_meeting_task', 0, task['taskId'])
    assert status == 200 and answer['result']['actionTasks'] == {'0': task['taskId']}


CONNECTED = {'state': 'connected', 'account_id': 'urn:li:person:abc123', 'vault_entry': 'social-linkedin-abc123',
             'display_name': 'Test Person'}


class RecordingHost:
    def __init__(self):
        self.calls = []

    def execute(self, prepared, vault_entry, *, before_dispatch):
        before_dispatch()
        self.calls.append((prepared, vault_entry))
        return {'outcome': 'succeeded', 'result': {'ok': True, 'state': 'ok', 'post_id': 'urn:li:share:1'}}


def _prepare_tool():
    from nodelang.native_agent_mcp import build_server
    return build_server()._tool_manager.get_tool('social.work_prepare').fn


def test_post_waits_for_the_approve_card_then_sends_the_exact_request(app, monkeypatch):
    from nodelang import social_connections, social_surface
    monkeypatch.setattr(social_connections, 'connection', lambda network: dict(CONNECTED) if network == 'linkedin' else {'state': 'not_connected'})
    host = RecordingHost()
    monkeypatch.setattr(social_surface, 'http_host', lambda: host)
    draft = social(app, 'save_social_draft', {'platform': 'LinkedIn', 'text': 'Our new library opens', 'kind': 'post'})[1]['result']
    prepared = _prepare_tool()(work_root=draft['id'])
    assert prepared['ok'] is True and prepared['status'] == 'pending' and host.calls == []
    # The card is on the one Approve list (Workshop listApprovals) and in the social approvals read.
    pending = app.get('/api/universal/social-approvals')[1]['items']
    assert [card['id'] for card in pending] == [prepared['id']]
    status, listed = app.post('/api/universal/workshop', {'action': 'data-api', 'function': 'listApprovals', 'args': []})
    assert status == 200 and any(c['id'] == prepared['id'] and c['approvalKind'] == 'social' for c in listed['result'])
    assert app.post('/api/universal/social-approve', {'delegation': prepared['id'], 'input_digest': '0' * 64, 'decision': 'approve'})[0] == 400
    assert host.calls == []
    status, decided = app.post('/api/universal/social-approve', {'delegation': prepared['id'], 'input_digest': prepared['input_digest'], 'decision': 'approve'})
    assert status == 200 and decided['decision'] == 'approved' and decided['status'] == 'posted'
    (sent, vault), = host.calls
    assert vault == 'social-linkedin-abc123' and sent.operation == 'linkedin.post' and sent.url.endswith('/rest/posts')
    assert json.loads(sent.body)['commentary'] == 'Our new library opens'
    assert all(name.lower() != 'authorization' for name, _ in sent.headers)
    drafts = social(app, 'get_state')[1]['state']['social']['drafts']
    assert drafts[0]['status'] == 'Posted' and drafts[0]['receipt'] == {'post_id': 'urn:li:share:1'}
    # Approving again never sends twice.
    app.post('/api/universal/social-approve', {'delegation': prepared['id'], 'input_digest': prepared['input_digest'], 'decision': 'approve'})
    assert len(host.calls) == 1 and app.get('/api/universal/social-approvals')[1]['items'] == []


def test_deny_and_missing_credential_never_reach_the_network(app, monkeypatch):
    from nodelang import social_connections
    monkeypatch.setattr(social_connections, 'connection', lambda network: dict(CONNECTED))
    first = social(app, 'save_social_draft', {'platform': 'LinkedIn', 'text': 'Denied post', 'kind': 'post'})[1]['result']
    card = _prepare_tool()(work_root=first['id'])
    status, decided = app.post('/api/universal/social-approve', {'delegation': card['id'], 'input_digest': card['input_digest'], 'decision': 'deny'})
    assert status == 200 and decided['decision'] == 'denied' and decided['status'] == 'denied'
    # The real host runs, finds no credential in the isolated store, and fails before any connection.
    second = social(app, 'save_social_draft', {'platform': 'LinkedIn', 'text': 'No credential post', 'kind': 'post'})[1]['result']
    card = _prepare_tool()(work_root=second['id'])
    status, decided = app.post('/api/universal/social-approve', {'delegation': card['id'], 'input_digest': card['input_digest'], 'decision': 'approve'})
    assert status == 200 and decided['status'] == 'failed' and 'credential' in decided['message']
    drafts = {d['id']: d['status'] for d in social(app, 'get_state')[1]['state']['social']['drafts']}
    assert drafts == {first['id']: 'Draft', second['id']: 'Draft'}


def test_unsupported_posts_answer_a_visible_open_item(app, monkeypatch):
    from nodelang import social_connections
    monkeypatch.setattr(social_connections, 'connection', lambda network: {'state': 'not_connected'})
    youtube = social(app, 'save_social_draft', {'platform': 'YouTube', 'text': 'Tutorial', 'kind': 'post'})[1]['result']
    answer = _prepare_tool()(work_root=youtube['id'])
    assert answer['ok'] is False and answer['reason'].startswith('Not restored yet: posting to YouTube')
    timed = social(app, 'save_social_draft', {'platform': 'LinkedIn', 'text': 'Later', 'kind': 'post', 'schedule': '2030-01-01T09:00'})[1]['result']
    assert _prepare_tool()(work_root=timed['id'])['reason'].startswith('Not restored yet: timed posting')
    now = social(app, 'save_social_draft', {'platform': 'LinkedIn', 'text': 'Now', 'kind': 'post'})[1]['result']
    assert 'Connect LinkedIn' in _prepare_tool()(work_root=now['id'])['reason']
    assert app.get('/api/universal/social-approvals')[1]['items'] == []


# ---- Community --------------------------------------------------------------------

def command(app, control, **facts):
    body = {'interaction': 'owner:community:' + control, 'control': control, 'event': 'activate', 'revision': 0}
    if facts:
        body['event_facts'] = [{'input': key, 'value': value if isinstance(value, str) else json.dumps(value)}
                               for key, value in facts.items()]
    return app.post('/api/universal/interaction', body)


def test_community_commands_are_exposed_and_kept_in_one_file(app):
    canvas = app.get('/api/universal/canvas')[1]
    controls = {b['control']: [f['input'] for f in b['event_facts']] for b in canvas['interaction_projection']['bindings']}
    assert controls['createCommunityGroup'] == ['name'] and controls['issueCommunityInvite'] == ['group', 'email']
    assert any(node['id'] == 'owner:community' for node in canvas['nodes'])
    status, made = command(app, 'createCommunityGroup', name='Design studio')
    assert status == 200 and made['result']['name'] == 'Design studio'
    group = made['result']['id']
    assert made['result']['community']['groups'][0]['id'] == group
    assert command(app, 'createCommunityGroup', name='design STUDIO')[0] == 400
    assert command(app, 'createCommunityGroup', name='pk' + '_' + 'fixture' + 'notreal01')[0] == 400  # key-shaped name
    status, invite = command(app, 'issueCommunityInvite', group=group, email='colleague@example.test')
    assert status == 200 and 'not sent' in invite['result']['status']
    assert command(app, 'issueCommunityInvite', group=group, email='colleague@example.test')[0] == 400
    assert command(app, 'issueCommunityInvite', group=group, email='not-an-email')[0] == 400
    revoked = command(app, 'revokeCommunityInvite', group=group, invite=invite['result']['id'])[1]['result']
    assert revoked['status'] == 'Revoked'
    command(app, 'setMarketplace', values={'marketQuery': 'stairs'})
    command(app, 'setProjectCharge', values={'client': 'Client A', 'basis': 'Per project', 'amount': 1200})
    assert command(app, 'setProjectCharge', values={'basis': 'Per hour'})[0] == 400
    held = json.loads((app.state_dir / 'settings' / 'community.json').read_text(encoding='utf-8'))
    assert held['groups'][0]['invites'][0]['status'] == 'Revoked'
    assert held['marketQuery'] == 'stairs' and held['charge']['amount'] == 1200
    assert app.post('/api/universal/interaction', {'interaction': 'x', 'control': 'retired', 'event': 'activate'})[1]['status'] == 'not_available'


@pytest.mark.parametrize('control', ['verifyCommunityInvite', 'joinCommunityGroup', 'proposeMarketplaceListing', 'proposeProjectCharge'])
def test_community_effects_without_an_owner_answer_a_visible_notice(app, control):
    status, answer = command(app, control)
    assert status == 400 and answer['error'].startswith('Not restored yet:')


def test_marketplace_install_answers_a_visible_notice(app):
    status, answer = command(app, 'installMarketplaceItem', item='pack-1')
    assert status == 400 and answer['error'].startswith('Not restored yet: installing from the marketplace')


def test_knowledge_network_quarantines_and_judges_once(app):
    from nodelang.community_owner import CommunityOwner
    owner = CommunityOwner(app.server.files['community'])
    peer = owner.join('office-network')
    incoming = owner.receive(peer, 'A reusable non-secret pattern')
    with pytest.raises(ValueError, match='already received'):
        owner.receive(peer, 'A reusable non-secret pattern')
    with pytest.raises(ValueError, match='credential'):
        owner.receive(peer, 'pass' + 'word' + ': ' + 'placeholder')  # credential-shaped claim
    state = app.post('/api/universal/canvas-op', {'op': 'community_state', 'args': []})[1]['result']
    assert state['peers'] == [{'id': peer, 'name': 'office-network', 'subscribed': True}]
    assert state['patterns'][0]['status'] == 'Quarantine'
    toggled = app.post('/api/universal/canvas-op', {'op': 'subscribe_community', 'args': [peer]})[1]['result']
    assert toggled['peers'][0]['subscribed'] is False
    with pytest.raises(ValueError, match='did not subscribe'):
        owner.receive(peer, 'Another pattern')
    judged = app.post('/api/universal/canvas-op', {'op': 'review_community_pattern', 'args': [incoming, 'Accept']})[1]['result']
    assert judged['patterns'][0]['status'] == 'Accepted'
    status, answer = app.post('/api/universal/canvas-op', {'op': 'review_community_pattern', 'args': [incoming, 'Reject']})
    assert status == 400 and 'final judgement' in answer['error']


# ---- Plan & access ----------------------------------------------------------------

def settings_action(app, function, *args):
    return app.post('/api/universal/settings-action', {'function': function, 'args': list(args)})


def test_devices_list_this_pc_and_keep_the_choice(app):
    status, answer = settings_action(app, 'readDevices')
    devices = answer['result']['devices']
    assert status == 200 and [d['id'] for d in devices] == ['this-pc'] and devices[0]['available'] is True
    assert answer['result']['deviceNotice'].startswith('Not restored yet: your other signed-in devices')
    status, chosen = settings_action(app, 'selectDevice', 'this-pc')
    assert status == 200 and chosen['result']['activeDevice'] == 'this-pc'
    held = json.loads((app.state_dir / 'settings' / 'settings.json').read_text(encoding='utf-8'))
    assert held['activeDevice'] == 'this-pc'
    status, answer = settings_action(app, 'selectDevice', 'other-pc')
    assert status == 400 and answer['error'].startswith('Not restored yet: sending work to another device')


@pytest.mark.parametrize('function', ['grantAccess', 'rollBack'])
def test_access_functions_without_an_owner_answer_a_visible_notice(app, function):
    status, answer = settings_action(app, function, 'item')
    assert status == 400 and answer['error'].startswith('Not restored yet:')
