"""Settings owner behavior on one isolated CellStore; no live account or package writes."""
import pytest
from nodelang.settings_owner import SettingsOwner
from nodelang.universal_cell import CellStore


class Cloud:
    def __init__(self):
        self.mail = 'one@example.test'
        self.calls = []
        self.plan = 'solo'
    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == '/v1/me':
            return {'email': self.mail, 'user_id': self.mail, 'plan': self.plan, 'remaining_messages': 7}
        if path == '/v1/companies/mine':
            return {'companies': [{'id':'office', 'name':'Test office', 'is_current':True}]}
        if path == '/v1/companies/office':
            return {'members':[{'user_id':'member', 'email':'two@example.test','role':'member'}]}
        if path == '/v1/billing/plans':
            return {'tiers':[{'tier':'solo'},{'tier':'studio'},{'tier':'firm'}], 'pricing_visible':True}
        if path == '/v1/billing/checkout':
            return {'checkout_url':'https://billing.example.test/checkout'}
        if path == '/v1/billing/portal':
            return {'url':'https://billing.example.test/portal'}
        if path.endswith('/invites'):
            return {'email':body['email'], 'token':'must-not-leak'}
        return {'ok':True}


def test_profile_persists_in_same_store_and_isolates_accounts():
    cloud = Cloud()
    store = CellStore()
    owner = SettingsOwner(store, cloud=cloud, dependencies=object())
    owner.updateProfile({'name':'A User','firm':'A Firm'})
    assert SettingsOwner(store, cloud=cloud, dependencies=object()).read()['profile']['name'] == 'A User'
    cloud.mail = 'two@example.test'
    assert 'name' not in owner.read()['profile']
    with pytest.raises(ValueError, match='identity'):
        owner.updateProfile({'email':'other@example.test'})


def test_invite_and_access_use_existing_cloud_owners_without_token_exposure():
    cloud = Cloud()
    owner = SettingsOwner(CellStore(), cloud=cloud, dependencies=object())
    result = owner.invitePerson('colleague@example.test')
    assert 'token' not in result
    assert cloud.calls[-1] == ('POST','/v1/companies/office/invites',{'email':'colleague@example.test','role':'member'})
    owner.setTeamAccess('member', {'accessRole':'Viewer','expires':'2030-01-01'})
    assert ('PATCH','/v1/companies/office/members/member',{'role':'viewer','access_until':'2030-01-01'}) in cloud.calls
    owner.setTeamAccess('member', {'accessRole':'Owner'})
    assert ('POST','/v1/companies/office/transfer-ownership',{'new_owner_user_id':'member'}) in cloud.calls


def test_checkout_never_grants_a_plan_before_provider_confirmation():
    cloud = Cloud()
    owner = SettingsOwner(CellStore(), cloud=cloud, dependencies=object())
    assert owner.setBilling({'requestedPlan':'Office'})['billing']['requestedPlan'] == 'Office'
    result = owner.prepareCheckout()
    assert result['open_url'] == 'https://billing.example.test/checkout'
    assert ('POST','/v1/billing/checkout',{'tier':'studio','annual':False}) in cloud.calls
    assert owner.completeCheckout()['billing']['status'] == 'solo'
    cloud.plan = 'studio'
    assert owner.completeCheckout()['billing']['status'] == 'studio'
    with pytest.raises(ValueError, match='payment confirmation'):
        owner.setBilling({'checkout':{'status':'paid'}})


def test_rejected_owner_and_invalid_commands_do_not_write():
    store = CellStore()
    owner = SettingsOwner(store, cloud=lambda *args: (_ for _ in ()).throw(ValueError('Sign in again')), dependencies=object())
    before = store.revision
    with pytest.raises(ValueError, match='Sign in again'):
        owner.updateProfile({'name':'Example'})
    assert store.revision == before
    with pytest.raises(ValueError, match='registered'):
        owner.dispatch('__dict__', [])
    with pytest.raises(ValueError, match='arguments'):
        owner.dispatch('setBilling', [])

def test_managed_dependencies_use_publisher_ids_and_verify_actual_inventory():
    import json
    from nodelang.managed_dependencies import ManagedDependencies, PACKAGES
    inventory = {'name':'npm', 'dependencies': {}}
    calls = []
    def run(args):
        calls.append(args)
        if args[0] == 'ls':
            return json.dumps(inventory)
        if args[0] == 'root':
            return 'C:/NONEXISTENT-ISOLATED-FIXTURE/node_modules'
        if args[0] == 'view':
            return json.dumps('2.0.0')
        if args[0] == 'install':
            inventory['dependencies']['@openai/codex'] = {'version':'2.0.0'}
        if args[0] == 'uninstall':
            inventory['dependencies'].pop('@openai/codex', None)
        return ''
    owner = ManagedDependencies(run=run, find=lambda name: 'C:/BIN/codex' if name=='codex' and '@openai/codex' in inventory['dependencies'] else None)
    result = owner.manage('codex', 'Install')
    assert ['install','--global','@openai/codex@latest'] in calls
    assert next(row for row in result['dependencies'] if row['id']=='codex')['state'] == 'Ready'
    owner.manage('codex','Remove')
    assert ['uninstall','--global','@openai/codex'] in calls
    with pytest.raises(ValueError, match='listed'):
        owner.manage('codex; unsafe', 'Install')
    assert '@openai/codex' == PACKAGES['codex']


def test_cloud_membership_role_and_expiry_are_enforced_in_the_existing_database(monkeypatch):
    from pathlib import Path
    from datetime import date, timedelta
    from fastapi import HTTPException
    backend = Path(__file__).resolve().parents[2] / '06.CLOUD/cloud_backend'
    monkeypatch.syspath_prepend(str(backend))
    import db
    import companies
    database = Path(__file__).resolve().parents[3] / 'FIXTURE' / 'CLOUD.db'
    assert not database.exists()
    monkeypatch.setattr(db.config,'DATABASE_URL',str(database))
    try:
        db.init_schema()
        owner = db.get_or_create_user('owner@example.test')
        member = db.get_or_create_user('member@example.test')
        company = db.create_company(name='Fixture office',owner_user_id=owner['id'],plan='studio',seat_limit=5,billing_email=owner['email'])
        db.add_company_member(company_id=company['id'],user_id=member['id'])
        monkeypatch.setattr(companies,'_require_user',lambda _auth: owner)
        result = companies.set_member_access(company['id'],member['id'],companies.MemberAccessReq(role='viewer',access_until=(date.today()+timedelta(days=1)).isoformat()))
        assert result['member']['role'] == 'viewer'
        monkeypatch.setattr(companies,'_require_user',lambda _auth: member)
        companies._require_membership(company['id'],member['id'])
        with pytest.raises(HTTPException):
            companies.set_member_access(company['id'],owner['id'],companies.MemberAccessReq(role='admin'))
        with db.connect() as con:
            con.execute('UPDATE company_members SET access_until=? WHERE company_id=? AND user_id=?',((date.today()-timedelta(days=1)).isoformat(),company['id'],member['id']))
        assert db.get_membership(company['id'],member['id']) is None
        db.set_current_company(member['id'], company['id'])
        assert db._reader_company_id(member['id']) is None
        assert companies.list_my_companies()['companies']==[]
        bearer = db.issue_token(member['id'])
        assert db.user_for_token(bearer)['current_company_id'] is None
        actor = {**member, 'current_company_id':company['id']}
        assert db.quota_remaining_for_actor(actor) == db.quota_remaining(member['id'])
        assert db.credit_balance_for_actor(actor) == db.credit_balance(user_id=member['id'])
        with pytest.raises(HTTPException):
            companies._require_membership(company['id'],member['id'])
        monkeypatch.setattr(companies,'_require_user',lambda _auth: owner)
        companies.set_member_access(company['id'],member['id'],companies.MemberAccessReq(access_until=''))
        assert db.get_membership(company['id'],member['id'])['access_until'] is None
        invitation = db.create_company_invite(company_id=company['id'],email=member['email'],role='member',invited_by_user_id=owner['id'])
        monkeypatch.setattr(companies,'_require_user',lambda _auth: member)
        assert companies.list_account_invitations()['invitations'][0]['email']==member['email']
        companies.decline_account_invitation(companies.AcceptInviteReq(invite_token=invitation['token']))
        assert db.get_company_invite(invitation['token'])['expires_at'] < __import__('time').time()
        monkeypatch.setattr(companies,'_require_user',lambda _auth: owner)
        assert companies.list_account_invitations()['invitations']==[]
        with pytest.raises(HTTPException):
            companies.decline_account_invitation(companies.AcceptInviteReq(invite_token=invitation['token']))
    finally:
        database.unlink(missing_ok=True)

def test_settings_http_route_authenticates_and_commits_to_the_selected_store(monkeypatch):
    import json
    import secrets
    from pathlib import Path
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    import shutil
    from nodelang import universal_application as app
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    import nodelang.settings_owner as settings
    directory = Path(__file__).resolve().parents[3] / 'FIXTURE' / 'HTTP'
    assert not directory.exists()
    directory.mkdir()
    monkeypatch.setenv('ARCHHUB_GRAND_MAP_PATH',str(Path(app.__file__).parent / 'data/public_runtime_map.json'))
    monkeypatch.setenv('ARCHHUB_TEST_STATE_DIR',str(directory))
    monkeypatch.setattr(settings,'cloud_call',Cloud())
    monkeypatch.setattr(SettingsOwner, '_roots', lambda self: [{'root_id': 'workspace', 'privacy': 'private'}])
    monkeypatch.setattr(SettingsOwner, '_recovery_directory', lambda self: directory / 'RECOVERY')
    keys = MemorySigningKeyProvider('archhub.local.relationship-authority',secrets.token_bytes(32))
    keys.add_key('archhub.local.court-attestation',secrets.token_bytes(32))
    server = None
    try:
        server = ApplicationServer(universal_state_path=directory/'APP.sqlite3',universal_key_provider=keys,
            universal_workspace_root=directory,enable_machine_transport=False,enable_universal_cloud_gateway=False,
            enable_machine_projection_prewarm=False,live_watch=False,enable_cloud_relay=False).start()
        def post(body, authenticated=True):
            headers={'Content-Type':'application/json'}
            if authenticated:
                headers.update({'X-ArchHub-Session':server.browser_session_token,'X-ArchHub-CSRF':server.browser_csrf_token})
            request = Request(server.public_url+'/api/universal/settings-action',data=json.dumps(body).encode(),headers=headers,method='POST')
            with urlopen(request,timeout=20) as response:
                return json.load(response)
        with pytest.raises(HTTPError) as refusal:
            post({'function':'updateProfile','args':[{'name':'Forbidden'}]},False)
        assert refusal.value.code == 403
        result=post({'function':'updateProfile','args':[{'name':'HTTP User','firm':'HTTP Office'}]})
        assert result['result']['profile']['name']=='HTTP User'
        assert post({'function':'read','args':[]})['result']['profile']['name']=='HTTP User'
        policy = post({'function':'setWorkspaceRules','args':['workspace',{'rules':'Keep client work private','privacy':'Secret'}]})
        assert policy['result']['workspacePolicies']['workspace']['privacy'] == 'Secret'
        graph = server.universal_registry.canvas_root
        assert post({'function':'setGraphWorkspaces','args':[graph,['workspace']]})['result']['workspaceIds'] == ['workspace']
        assert post({'function':'setSettingsScope','args':['Workspace','workspace']})['result']['settingsScope'] == 'Workspace'
        assert post({'function':'readOperations','args':[]})['result']['workspacePolicies']['workspace']['rules'] == 'Keep client work private'
        try:
            backup = post({'function':'backUpNow','args':[]})['result']
        except HTTPError as error:
            raise AssertionError(error.read().decode('utf-8')) from error
        assert (directory/'RECOVERY'/backup['backup']/'recovery.json').is_file()
        prepared = post({'function':'rollBack','args':[backup['backup']]})['result']
        assert prepared['status'] == 'prepared' and prepared['restored'] is False
        assert (Path(prepared['restoreDirectory'])/'restoration.json').is_file()
        before=server.universal_store.revision
        with pytest.raises(HTTPError):
            post({'function':'updateProfile','args':[{'email':'wrong@example.test'}]})
        assert server.universal_store.revision==before
        with pytest.raises(HTTPError):
            post({'function':'read','args':[],'environment':{}})
        assert server.universal_store.revision==before
    finally:
        if server is not None:
            server.close()
        assert directory.resolve().is_relative_to(Path(__file__).resolve().parents[3]/'FIXTURE')
        shutil.rmtree(directory)


def test_invitation_actions_use_authenticated_existing_company_owners():
    cloud = Cloud()
    owner = SettingsOwner(CellStore(),cloud=cloud,dependencies=object())
    owner.acceptOfficeInvitation('recipient-bound-invitation')
    assert ('POST','/v1/companies/invites/accept',{'invite_token':'recipient-bound-invitation'}) in cloud.calls
    owner.declineOfficeInvitation('recipient-bound-invitation')
    assert ('POST','/v1/companies/invites/decline',{'invite_token':'recipient-bound-invitation'}) in cloud.calls


def test_archive_displays_the_real_bounded_retention_result():
    from unittest.mock import Mock
    content = Mock()
    content.maintain_retention.return_value={'status':'waiting-for-idle','archived':0,'protected':3}
    context = object()
    owner = SettingsOwner(CellStore(),dependencies=object(),content=content,authentication_context=context)
    result = owner.archiveActivity()
    content.maintain_retention.assert_called_once_with(authentication_context=context)
    assert result['retention']['status']=='waiting-for-idle'
    assert result['message']=='waiting-for-idle: 0 conversations archived; 3 protected.'


def test_existing_cloud_profile_is_used_without_overwriting_local_account_preferences():
    cloud = Cloud()
    def fetch(method, path, body=None):
        result = cloud(method, path, body)
        if path == '/v1/me':
            result.update(full_name='Existing account name', firm_name='Existing office')
        return result
    store = CellStore()
    owner = SettingsOwner(store, cloud=fetch, dependencies=object())
    assert owner.read()['profile']['name'] == 'Existing account name'
    assert owner.read()['profile']['firm'] == 'Existing office'
    owner.updateProfile({'name': 'Chosen local name'})
    assert owner.read()['profile']['name'] == 'Chosen local name'
    assert owner.read()['profile']['firm'] == 'Existing office'


"""BUTTONS owner checks: one isolated fixture, no installed app or live state."""
import threading
import time
from types import SimpleNamespace

from PyQt6.QtCore import QCoreApplication, QObject, QUrl

from nodelang.baboom_native_voice import BaboomVoiceInput, BaboomVoiceCancelled
from nodelang.window_commands import WindowCommands


@pytest.fixture
def bridge():
    app = QCoreApplication.instance() or QCoreApplication([])
    page = QObject()
    navigation = []
    view = SimpleNamespace(page=lambda: page, url=lambda: QUrl('http://127.0.0.1:1234/studio'),
                           urlChanged=SimpleNamespace(connect=navigation.append), navigation=navigation)
    commands = WindowCommands(view, None, lambda: None, 'http://127.0.0.1:1234')
    yield commands, app, view
    commands.stopVoice()
    if commands._voice_worker:
        commands._voice_worker.join(1)


def wait_result(app, results):
    end = time.monotonic() + 2
    while not results and time.monotonic() < end:
        app.processEvents()
        time.sleep(.001)
    assert results
    return results[0]


def test_startVoiceInput_uses_existing_capture_and_returns_normalized_text(bridge):
    commands, app, _ = bridge
    entered = threading.Event()
    class Backend:
        def capture_once(self, **kwargs):
            entered.set()
            return '  review   the plan '
    commands._voice_input = BaboomVoiceInput(backend_factory=Backend)
    results = []
    commands.voiceFinished.connect(lambda key, data: results.append((key, data)))
    assert commands.startVoice('capture-one')['ok']
    assert entered.wait(1)
    key, result = wait_result(app, results)
    assert key == 'capture-one'
    assert result == {'ok': True, 'text': 'review the plan'}


def test_stopVoiceInput_cancels_the_same_capture_and_refuses_overlap(bridge):
    commands, app, _ = bridge
    entered = threading.Event()
    class Backend:
        def capture_once(self, *, cancel, timeout_seconds):
            entered.set()
            assert cancel.wait(1)
            raise BaboomVoiceCancelled('Voice capture was cancelled')
    commands._voice_input = BaboomVoiceInput(backend_factory=Backend)
    results = []
    commands.voiceFinished.connect(lambda key, data: results.append(data))
    assert commands.startVoice('capture-two')['ok']
    assert entered.wait(1)
    assert commands.startVoice('overlap')['ok'] is False
    assert commands.stopVoice()['ok']
    assert wait_result(app, results) == {'ok': True, 'cancelled': True}


def test_voice_refuses_other_origins_without_opening_microphone(bridge):
    commands, _, view = bridge
    view.url = lambda: QUrl('https://example.com/studio')
    assert commands.startVoice('capture-three')['ok'] is False
    assert commands.stopVoice()['ok'] is False
    assert commands._voice_worker is None


def test_ensureDependency_dispatches_existing_manager_and_preserves_failure():
    calls = []
    class Dependencies:
        def check(self):
            return [{'id': 'codex', 'state': 'Not installed'}]
        def manage(self, identity, action):
            calls.append((identity, action))
            return {'dependencies': [{'id': identity, 'state': 'Ready'}]}
    owner = SettingsOwner(None, dependencies=Dependencies())
    result = owner.dispatch('ensureDependency', ['codex'])
    assert result['dependencies'][0]['state'] == 'Ready'
    assert calls == [('codex', 'Install')]
    with pytest.raises(ValueError):
        owner.dispatch('ensureDependency', ['unknown'])
    assert len(calls) == 1
    owner.dependencies.check = lambda: [{'id': 'codex', 'state': 'Ready'}]
    assert owner.dispatch('ensureDependency', ['codex'])['dependencies'][0]['state'] == 'Ready'
    assert len(calls) == 1
    owner.dependencies.check = lambda: [{'id': 'codex', 'state': 'Needs repair'}]
    def refuse(*args):
        raise ValueError('Package manager refused')
    owner.dependencies.manage = refuse
    with pytest.raises(ValueError, match='Package manager refused'):
        owner.dispatch('ensureDependency', ['codex'])


def test_navigation_cancels_native_capture_even_after_origin_changes(bridge):
    commands, app, view = bridge
    entered = threading.Event()
    class Backend:
        def capture_once(self, *, cancel, timeout_seconds):
            entered.set()
            assert cancel.wait(1)
            raise BaboomVoiceCancelled('Voice capture was cancelled')
    commands._voice_input = BaboomVoiceInput(backend_factory=Backend)
    results = []
    commands.voiceFinished.connect(lambda key, data: results.append(data))
    assert commands.startVoice('navigate')['ok']
    assert entered.wait(1)
    view.url = lambda: QUrl('https://example.com/')
    for callback in view.navigation:
        callback(view.url())
    assert wait_result(app, results) == {'ok': True, 'cancelled': True}


def test_ensureDependency_runs_existing_manager_and_confirms_inventory(tmp_path, monkeypatch):
    import json
    import psutil
    from nodelang.managed_dependencies import ManagedDependencies
    monkeypatch.setattr(psutil, 'process_iter', lambda *args: [])
    installed = tmp_path / 'INVENTORY.json'
    installed.write_text('{}', encoding='utf-8')
    calls = []
    def run(args):
        calls.append(args)
        if args[0] == 'root':
            return str(tmp_path)
        if args[0] == 'ls':
            return json.dumps({'dependencies': json.loads(installed.read_text(encoding='utf-8'))})
        if args[0] == 'view':
            return json.dumps('1.0.0')
        assert args == ['install', '--global', '@openai/codex@latest']
        installed.write_text(json.dumps({'@openai/codex': {'version': '1.0.0'}}), encoding='utf-8')
        return ''
    def find(executable):
        return executable == 'codex' and '@openai/codex' in json.loads(installed.read_text(encoding='utf-8'))
    manager = ManagedDependencies(run=run, find=find)
    owner = SettingsOwner(None, dependencies=manager)
    result = owner.dispatch('ensureDependency', ['codex'])
    row = next(row for row in result['dependencies'] if row['id'] == 'codex')
    assert row['state'] == 'Ready'
    assert row['version'] == '1.0.0'
    assert ['install', '--global', '@openai/codex@latest'] in calls
    calls.clear()
    owner.dispatch('ensureDependency', ['codex'])
    assert not any(args[0] == 'install' for args in calls)


def test_voice_bridge_settles_native_receipts_and_cancels_on_pagehide():
    import json
    import subprocess
    from nodelang.window_commands import VOICE_BRIDGE
    script = """
const vm=require('node:vm'),assert=require('node:assert/strict');
let finished,stopped=0;const events=new Map();
const desktopWindow={voiceFinished:{connect:fn=>finished=fn},
 startVoice(id,reply){reply({ok:true});queueMicrotask(()=>finished(id,{ok:true,text:'native text'}));},
 stopVoice(reply){stopped++;reply({ok:true});}};
const window={crypto:require('node:crypto').webcrypto,addEventListener:(name,fn)=>events.set(name,fn),dispatchEvent(){}};
const context={channel:{objects:{desktopWindow}},window,crypto:window.crypto,Event:class{},console};
vm.runInNewContext(BRIDGE,context);
(async()=>{
 const result=await window.ARCHHUB_VOICE_START();assert.equal(result.text,'native text');
 assert.equal((await window.ARCHHUB_VOICE_STOP()).ok,true);events.get('pagehide')();assert.equal(stopped,2);
 desktopWindow.startVoice=(_id,reply)=>reply({ok:false,error:'Capture refused'});
 await assert.rejects(window.ARCHHUB_VOICE_START(),/Capture refused/);
 console.log('VOICE_BRIDGE_PROTOCOL_PASS');
})().catch(failure=>{console.error(failure);process.exitCode=1;});
""".replace('BRIDGE', json.dumps(VOICE_BRIDGE), 1)
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'VOICE_BRIDGE_PROTOCOL_PASS' in result.stdout
