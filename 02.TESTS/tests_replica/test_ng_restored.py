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
    done = call(server, 'decideHostSkill', card['id'], card['input_digest'], 'approve')
    assert done['status'] == 'approved'
    stored = json.loads((server.state_dir / 'settings' / 'host-packages.json').read_text(encoding='utf-8'))
    record = stored['packages'][row['id']]
    assert record['enabled'] is True and record['descriptor'] == SKILL
    assert call(server, 'readHostSkills')['hostSkills'][0]['enabled'] is True


def test_host_package_refusals_come_back_as_reasons(server):
    bad = call(server, 'inspectConnectorBundle', {'name': 'x.json', 'base64': base64.b64encode(b'[]').decode()})
    assert bad['ok'] is False and 'bounded UTF-8 manifest' in bad['error']
    card = call(server, 'importHostSkill', {'host': 'Revit', 'text': SKILL})
    stale = call(server, 'decideHostSkill', 'app:host-package-review:nope', 'x', 'approve')
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
    done = call(server, 'decideWatcherEdit', card['id'], card['input_digest'], 'approve')
    assert done['status'] == 'approved' and host['writes'][0]['offsetMm'] == 30.0
    view = call(server, 'readWatcher')
    assert view['applied'] is True and view['wallY'] == 2 and len(view['dimensions']) == 1
    assert (server.state_dir / 'settings' / 'watcher.json').is_file()
