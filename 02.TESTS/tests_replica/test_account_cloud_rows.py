"""Settings > Account rows that live on the ArchHub account (D-055): Brain follows your account, Sync .archhub files,
Office policy, Access ends. Two disposable profiles share one fake account cloud, as two PCs share one account."""
import base64
import gzip
import hashlib
import json

import pytest

from nodelang import account_sync, brain_files, session_files, settings_owner


class Cloud:
    """The account's two cloud owners this slice talks to: /v1/brain/sync (LWW by hlc) and /v1/account-sync/*."""

    def __init__(self):
        self.brain, self.items, self.seq, self.sent = {}, {}, 0, []

    def __call__(self, method, url, bearer=None, body=None):
        self.sent.append((method, url, body))
        route = url.split('https://x', 1)[1]
        if route == '/v1/brain/sync':
            for fragment in body['delta']['fragments']:
                held = self.brain.get(fragment['id'])
                if held is None or fragment['hlc'] > held['hlc']:
                    self.brain[fragment['id']] = fragment
            return 200, {'accepted': len(body['delta']['fragments']), 'rejected': [],
                         'merged': {'fragments': list(self.brain.values())}}
        if route.startswith('/v1/account-sync/manifest'):
            return 200, {'items': [{'logical_path': path, 'sha256': sha, 'deleted': deleted}
                                   for path, (sha, _content, deleted) in self.items.items()]}
        if route == '/v1/account-sync/item':
            self.seq += 1
            if body.get('deleted'):
                self.items[body['logical_path']] = ('', b'', True)
                return 200, {'sha256': ''}
            content = gzip.decompress(base64.b64decode(body['content_b64']))
            sha = hashlib.sha256(content).hexdigest()
            self.items[body['logical_path']] = (sha, content, False)
            return 200, {'sha256': sha}
        if route.startswith('/v1/account-sync/blob/'):
            sha = route.split('/blob/', 1)[1].split('?', 1)[0]
            content = next(c for s, c, _d in self.items.values() if s == sha)
            return 200, {'content_b64': base64.b64encode(gzip.compress(content)).decode()}
        return 404, {}


@pytest.fixture
def pcs(tmp_path, monkeypatch):
    cloud = Cloud()
    monkeypatch.setattr(account_sync, '_http', cloud)
    monkeypatch.setattr(account_sync, '_access', type('A', (), {'check': lambda self: {'admitted': True}})())
    monkeypatch.setattr(account_sync._cloud, '_session', lambda _o: ('t', 'https://x'))
    monkeypatch.setattr(account_sync, '_account', lambda: 'qa')
    session_files.register_sessions_sync()

    def on(name, **settings):
        """Switch this process to PC ``name`` (its own state folder), holding these Settings values."""
        brain_files.close()
        monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR', str(tmp_path / name))
        path = session_files.profile_directory() / 'settings' / 'settings.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        if settings or not path.exists():
            path.write_text(json.dumps(settings), encoding='utf-8')
    on.cloud = cloud
    yield on
    brain_files.close()


def facts():
    return {fact['id']: fact['body'] for folder in brain_files._call('brain.list_facts', {})['folders']
            for fact in folder['facts']}


def write(fact_id, text):
    brain_files._call('brain.write', {'ops': [{'op': 'add', 'fragment': {'id': fact_id, 'kind': 'practice', 'text': text}}]})


def test_a_memory_written_on_one_pc_is_read_on_the_other(pcs):
    pcs('A')
    write('ramps', 'Car park ramps are 1:6 with 1:12 transitions')
    assert brain_files.sync_with_account()['ok'] is True
    pcs('B')
    assert facts() == {}
    assert brain_files.sync_with_account()['pulled'] == 1
    assert facts() == {'ramps': 'Car park ramps are 1:6 with 1:12 transitions'}
    assert pcs.cloud.brain['ramps']['extra'] == {'kind': 'practice'}  # the desktop kind survives the round trip


def test_an_edit_and_a_forget_follow_the_account(pcs):
    pcs('A')
    write('lift', 'Lifts are 1.1 x 1.4 m')
    brain_files.sync_with_account()
    pcs('B')
    brain_files.sync_with_account()
    brain_files._call('brain.edit_fact', {'fragment_id': 'lift', 'text': 'Lifts are 1.1 x 2.1 m (stretcher)'})
    brain_files.sync_with_account()
    pcs('A')
    brain_files.sync_with_account()
    assert facts() == {'lift': 'Lifts are 1.1 x 2.1 m (stretcher)'}
    brain_files._call('brain.delete_fact', {'fragment_id': 'lift'})
    brain_files.sync_with_account()
    pcs('B')
    brain_files.sync_with_account()
    assert facts() == {}


def test_a_client_area_memory_never_leaves_this_pc(pcs):
    pcs('A')
    write('secret-job', 'The 20.CLIENTS tower uses a 9 m grid')
    brain_files.sync_with_account()
    assert 'secret-job' not in pcs.cloud.brain


def test_brain_stays_on_this_pc_when_the_row_is_off(pcs):
    pcs('A', syncBrain=False)
    write('local', 'Only here')
    assert brain_files.sync_with_account() == {'ok': False, 'skipped': 'Brain follows your account is off'}
    assert pcs.cloud.sent == []


def _session(title):
    document = session_files.new_document(title)
    path = session_files.write_document(session_files.document_path(session_files.sessions_directory(), document), document)
    return document, path


def test_a_session_saved_on_one_pc_opens_on_the_other(pcs):
    pcs('A', syncFiles='ArchHub account')
    document, path = _session('Tower massing')
    account_sync.pull_and_restore('sessions/')  # the save's own upload, or this restore, puts it on the account
    assert 'sessions/' + document['id'] + '.archhub' in pcs.cloud.items
    pcs('B', syncFiles='ArchHub account')
    assert account_sync.pull_and_restore('sessions/')['sessions/']['pulled'] == 1
    arrived = session_files.sessions_directory() / 'Tower massing.archhub'
    assert arrived.read_bytes() == open(path, 'rb').read()
    assert session_files.read_document(arrived)['id'] == document['id']


def test_a_session_removed_on_one_pc_leaves_the_other(pcs):
    pcs('A', syncFiles='ArchHub account')
    document = _session('Old option')[0]
    account_sync.pull_and_restore('sessions/')
    pcs('B', syncFiles='ArchHub account')
    account_sync.pull_and_restore('sessions/')
    pcs('A')
    account_sync.delete('sessions/' + document['id'] + '.archhub')
    pcs('B')
    assert account_sync.pull_and_restore('sessions/')['sessions/']['dropped'] == 1
    assert not (session_files.sessions_directory() / 'Old option.archhub').exists()


def test_sessions_stay_on_this_pc_when_the_row_is_off(pcs):
    pcs('A', syncFiles='Off')
    _session('Private sketch')
    assert account_sync.pull_and_restore('sessions/')['sessions/']['uploaded'] == 0
    assert pcs.cloud.items == {}


def test_onedrive_moves_the_sessions_folder_into_the_drive_and_off_brings_it_back(pcs, tmp_path, monkeypatch):
    pcs('A')
    drive = tmp_path / 'OneDrive'
    drive.mkdir()
    monkeypatch.setenv('OneDrive', str(drive))
    _session('Drive plan')
    session_files.apply_files_sync('Off', 'OneDrive')
    assert (drive / 'ArchHub' / 'Sessions' / 'Drive plan.archhub').is_file()
    session_files.apply_files_sync('OneDrive', 'Off')
    assert (session_files.sessions_directory() / 'Drive plan.archhub').is_file()
    assert not (drive / 'ArchHub' / 'Sessions' / 'Drive plan.archhub').exists()


def test_a_drive_that_is_not_on_this_pc_is_refused(pcs, monkeypatch):
    pcs('A')
    monkeypatch.setattr(session_files, 'drive_folder', lambda name: None)
    with pytest.raises(ValueError, match='not set up on this PC'):
        session_files.apply_files_sync('Off', 'Google Drive')


def _rows():
    return {row['storageKey']: row for row in settings_owner.preference_settings()['appearanceSettings']}


def test_the_four_rows_are_controls_not_off_notices(pcs):
    pcs('A')
    rows = _rows()
    for key in ('syncBrain', 'syncFiles', 'policyLock', 'accessEnds'):
        assert 'unavailable' not in rows[key], key
    assert 'ArchHub account' in rows['syncFiles']['options']
    assert rows['accessEnds']['disabledOptions'] == {
        'When the project ends': 'Needs a project end date, which the Project register does not hold yet'}


def test_a_disabled_choice_is_refused_not_stored(pcs):
    pcs('A')
    for identity, value in (('Account.Access ends', 'When the project ends'), ('Account.Sync .archhub files', 'Office server')):
        with pytest.raises(ValueError):
            settings_owner.preference_settings('setAppearance', [identity, value])


def test_an_invite_carries_the_access_period(pcs):
    pcs('A', accessEnds='30 days', inviteRole='Member')
    sent = []

    def cloud(method, path, body=None):
        sent.append((method, path, body))
        if path == '/v1/companies/mine':
            return {'companies': [{'id': 'c1', 'is_current': True, 'role': 'owner'}]}
        return {'email': body['email']}
    owner = settings_owner.SettingsOwner(None, cloud=cloud, dependencies=object())
    owner.invitePerson('new@studio.example')
    assert sent[-1] == ('POST', '/v1/companies/c1/invites', {'email': 'new@studio.example', 'role': 'member', 'access_days': 30})


def test_never_sends_no_access_period(pcs):
    pcs('A', accessEnds='Never')
    sent = []

    def cloud(method, path, body=None):
        sent.append(body)
        return {'companies': [{'id': 'c1', 'is_current': True}]} if path.endswith('mine') else {'email': 'x'}
    settings_owner.SettingsOwner(None, cloud=cloud, dependencies=object()).invitePerson('x@studio.example')
    assert 'access_days' not in sent[-1]


def test_a_locked_office_value_replaces_the_members_and_refuses_an_edit(pcs):
    pcs('A', lenUnit='Millimetres')
    file = settings_owner._settings_file()
    settings_owner.apply_office_policy({'locked': True, 'values': {'lenUnit': 'Metres'}, 'company_id': 'c1'}, 'member', file)
    assert _rows()['lenUnit']['value'] == 'Metres'
    assert _rows()['policyLock']['value'] == settings_owner.OFFICE_LOCKED
    with pytest.raises(ValueError, match='locked by your office admin'):
        settings_owner.preference_scope().change({'Projects.Length': 'Feet and inches'})
    settings_owner.apply_office_policy({'locked': False, 'values': {'lenUnit': 'Metres'}}, 'member', file)
    settings_owner.preference_scope().change({'Projects.Length': 'Feet and inches'})
    assert _rows()['lenUnit']['value'] == 'Feet and inches'


def test_an_admin_locking_publishes_the_offices_values(pcs, monkeypatch):
    pcs('A', lenUnit='Metres')
    sent = []

    def cloud(method, path, body=None):
        sent.append((method, path, body))
        if path == '/v1/companies/mine':
            return {'companies': [{'id': 'c1', 'is_current': True, 'role': 'admin'}]}
        return {'locked': body['locked'], 'values': body['values']}
    monkeypatch.setattr(settings_owner, 'cloud_call', cloud)
    settings_owner.preference_scope().change({'Account.Office policy': settings_owner.OFFICE_LOCKED})
    method, path, body = sent[-1]
    assert (method, path, body['locked'], body['values']['lenUnit']) == ('PUT', '/v1/companies/c1/policy', True, 'Metres')
    assert _rows()['policyLock']['value'] == settings_owner.OFFICE_LOCKED


def test_a_member_cannot_lock_the_office(pcs, monkeypatch):
    pcs('A')
    monkeypatch.setattr(settings_owner, 'cloud_call', lambda method, path, body=None: {
        'companies': [{'id': 'c1', 'is_current': True, 'role': 'member'}]})
    with pytest.raises(ValueError, match='Only an office owner or admin'):
        settings_owner.preference_scope().change({'Account.Office policy': settings_owner.OFFICE_LOCKED})
    assert _rows()['policyLock']['value'] == settings_owner.OFFICE_OPEN
