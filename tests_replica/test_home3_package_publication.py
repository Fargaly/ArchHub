"""HOME3: the reviewed package reaches the issued container through the file broker."""
import hashlib
import json
import shutil
import time

import pytest

from nodelang import library_engines as library
from nodelang import nodeslib_v2_engines as owner
from tests_replica.test_workshop_milestone_one import harness


def package(tmp_path, monkeypatch):
    source = tmp_path / '01.WIP' / 'A101.pdf'
    source.parent.mkdir()
    source.write_bytes(b'%PDF-1.4\nreal reviewed sheet bytes\n%%EOF')
    target = tmp_path / '03.PUBLISHED' / 'reviewed-set'
    sheets = [{'id': 'A101', 'name': 'A101.pdf', 'path': str(source),
               'digest': hashlib.sha256(source.read_bytes()).hexdigest()}]
    request = {'path': str(target.resolve()), 'sheets': sheets}
    grant = {'digest': 'signed-by-existing-authority', 'caller': 'founder',
             'session': 'session', 'work': 'work', 'action': 'write_file',
             'operations': ['write_file'], 'approval_scope': 'file.write',
             'scope': 'exact', 'path': str(target), 'current': True,
             'expires_at': time.time() + 300, 'input_digest': owner._digest_payload(request)}
    params = {'path': str(target), 'sheets': json.dumps(sheets), 'file_grant': json.dumps(grant)}
    calls = []
    verified = []

    def verifier(request):
        verified.append(request)
        return {'ok': True}

    def transport(request):
        calls.append(request)
        target.mkdir(parents=True, exist_ok=False)
        for sheet in request['sheets']:
            shutil.copyfile(sheet['path'], target / sheet['name'])
        return {'ok': True, 'receipt': 'governed-write-receipt'}

    monkeypatch.setattr(owner, '_WRITE_GRANT_VERIFIER', verifier)
    monkeypatch.setattr(owner, '_FILE_WRITE_BROKER', transport)
    return params, target, source, calls, verified


def test_registered_engine_publishes_reviewed_real_files_once(tmp_path, monkeypatch):
    params, target, source, calls, verified = package(tmp_path, monkeypatch)
    result, _ = library.LIBRARY_ENGINES['library.publish_package'](params, {})
    assert (target / 'A101.pdf').read_bytes() == source.read_bytes()
    assert result['receipt'] == 'governed-write-receipt'
    assert result['out'] == [str(target / 'A101.pdf')]
    assert len(verified) == len(calls) == 1
    with pytest.raises(ValueError, match='already published'):
        library.LIBRARY_ENGINES['library.publish_package'](params, {})
    assert len(calls) == 1


@pytest.mark.parametrize('fault', ['changed-sheet', 'bad-name', 'wrong-container', 'revoked', 'missing-verifier'])
def test_publication_refuses_stale_or_ungoverned_input(tmp_path, monkeypatch, fault):
    params, target, source, calls, _ = package(tmp_path, monkeypatch)
    if fault == 'changed-sheet':
        source.write_bytes(b'changed after review')
    elif fault == 'bad-name':
        sheets = json.loads(params['sheets'])
        sheets[0]['name'] = '../escaped.pdf'
        params['sheets'] = json.dumps(sheets)
    elif fault == 'wrong-container':
        params['path'] = str(tmp_path / '01.WIP' / 'not-issued')
    elif fault == 'revoked':
        grant = json.loads(params['file_grant'])
        grant['revoked'] = True
        params['file_grant'] = json.dumps(grant)
    else:
        monkeypatch.setattr(owner, '_WRITE_GRANT_VERIFIER', None)
    with pytest.raises(ValueError):
        library.LIBRARY_ENGINES['library.publish_package'](params, {})
    assert not calls and not target.exists()


def test_publication_requires_receipt_and_rechecks_published_bytes(tmp_path, monkeypatch):
    params, target, _, _, _ = package(tmp_path, monkeypatch)
    def false_receipt(request):
        target.mkdir(parents=True)
        (target / 'A101.pdf').write_bytes(b'not the approved bytes')
        return {'ok': True, 'receipt': 'broker-receipt'}
    monkeypatch.setattr(owner, '_FILE_WRITE_BROKER', false_receipt)
    with pytest.raises(ValueError, match='published sheet digest'):
        library.LIBRARY_ENGINES['library.publish_package'](params, {})


def test_package_projection_reads_actual_sources_and_omits_missing_files(tmp_path, monkeypatch):
    params, _, source, _, _ = package(tmp_path, monkeypatch)
    projected = owner.package_preview(params)
    assert projected['sheets'][0]['id'] == 'A101'
    assert projected['sheets'][0]['name'] == source.name
    assert 'thumbnail_url' not in projected['sheets'][0]
    source.unlink()
    assert owner.package_preview(params) is None


@pytest.mark.parametrize('kind', ['source', 'destination'])
def test_publication_refuses_symbolic_links_before_resolving(tmp_path, monkeypatch, kind):
    params, target, source, calls, _ = package(tmp_path, monkeypatch)
    original = source if kind == 'source' else target
    link = original.with_name('linked-' + original.name)
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(original, target_is_directory=kind == 'destination')
    except OSError:
        # Windows may withhold symlink privilege. Simulate exactly the two
        # filesystem answers without skipping the pre-resolution regression.
        class SymbolicLink:
            def is_symlink(self):
                return True
            def resolve(self):
                return original.resolve()
        local_path = owner._local_output_path
        monkeypatch.setattr(owner, '_local_output_path',
            lambda value, *, label: SymbolicLink() if str(value) == str(link)
            else local_path(value, label=label))
    if kind == 'source':
        sheets = json.loads(params['sheets'])
        sheets[0]['path'] = str(link)
        params['sheets'] = json.dumps(sheets)
    else:
        params['path'] = str(link)
    with pytest.raises(ValueError, match='symbolic link'):
        library.LIBRARY_ENGINES['library.publish_package'](params, {})
    assert not calls and not target.exists()


def test_http_workflow_projects_real_sheets_and_approves_then_publishes(harness, tmp_path, monkeypatch):
    from tests_replica import test_workshop_milestone_one as court
    params, target, source, calls, _ = package(tmp_path, monkeypatch)
    # Native replies cannot carry private absolute paths or approval material.
    # The user's ordinary property edit supplies the already-issued file grant.
    monkeypatch.chdir(tmp_path)
    proposal_params = dict(params, path='03.PUBLISHED/reviewed-set', file_grant='', template_runs='0')
    sheets = json.loads(params['sheets'])
    sheets[0]['path'] = '01.WIP/A101.pdf'
    proposal_params['sheets'] = json.dumps(sheets)
    monkeypatch.setattr(court, 'PROPOSAL', {'answer': 'Issue the reviewed package.', 'actions': [
        {'op': 'node', 'ref': 'package', 'engine': 'library.publish_package',
         'title': 'Reviewed package', 'params': proposal_params}]})
    harness.start()
    convo = harness.conversation_with_two_agents()
    sent = court._send_contact(harness, convo, convo['opencode'],
        court._opencode_digest(harness, convo), 'PROPOSE the reviewed package', 'package-proposal')
    harness.settle()
    message = court._message(harness.page(convo['root'], convo['scope']), sent['message_id'])
    assert message['delivery'][0].get('reply_message_id'), message['delivery']
    reply = message['delivery'][0]['reply_message_id']
    drafted = court._draft(harness, convo, reply, 'package-draft')
    workflow = drafted['workflow']
    state = court._workflow(harness, convo, workflow)
    grant_property = court._param(state, state['members'][0], 'file_grant')
    unreviewed_digest = state['digest']
    harness.request('/api/universal/set-property', {'relation': grant_property['relation'],
        'value': params['file_grant']})
    state = court._workflow(harness, convo, workflow)
    court._approve(harness, convo, workflow, unreviewed_digest, expected=400)
    assert state['package']['sheets'][0]['name'] == 'A101.pdf'
    assert state['package']['destination'] == str(target)
    court._execute(harness, convo, workflow, 'before-approval', expected=400)
    assert not calls
    court._approve(harness, convo, workflow, state['digest'])
    runs_property = court._param(state, state['members'][0], 'template_runs')
    harness.request('/api/universal/set-property', {'relation': runs_property['relation'], 'value': '1'})
    assert court._workflow(harness, convo, workflow)['approval']['current']
    result = court._execute(harness, convo, workflow, 'after-approval')
    assert result['ran'], result
    assert result['publication']['receipt'] == 'governed-write-receipt'
    assert not result['pending']
    assert (target / 'A101.pdf').read_bytes() == source.read_bytes()
    court._execute(harness, convo, workflow, 'double-click')
    assert len(calls) == 1
