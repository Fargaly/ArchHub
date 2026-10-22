"""Five settings effects on the existing durable graph, with physical owner doubles."""
import json
from io import BytesIO
from types import SimpleNamespace
import pytest
from nodelang.settings_owner import SettingsOwner
from nodelang.universal_cell import CellStore, Cell, NULL_CELL_ID, InvalidCell


@pytest.fixture
def owned(tmp_path, monkeypatch):
    from nodelang import model_router
    def forbidden(*args, **kwargs):
        raise AssertionError('Unexpected physical credential, catalogue, cloud or network access')
    monkeypatch.setattr(model_router, 'list_social_credentials', lambda: {'ok': True, 'items': []})
    monkeypatch.setattr(model_router, '_application_secrets_store', forbidden)
    monkeypatch.setattr(model_router, 'default_cloud_session', forbidden)
    monkeypatch.setattr('urllib.request.urlopen', forbidden)
    path = tmp_path / 'GRAPH.sqlite3'
    store = CellStore(path)
    store.commit(store.revision, create=(Cell('account', NULL_CELL_ID, NULL_CELL_ID, b'account'),
        Cell('application', NULL_CELL_ID, NULL_CELL_ID, b'application')))
    registry = SimpleNamespace(authorization=SimpleNamespace(subject_root='account'), application_root='application')
    runtime = SimpleNamespace(universal_registry=registry,
        _project_model_discovery=lambda path: {'groups': []})
    def owner():
        return SettingsOwner(store, runtime=runtime, dependencies=object(), authentication_context='context')
    def reopen():
        nonlocal store
        store.close()
        store = CellStore(path)
        return owner()
    yield owner, reopen, runtime
    store.close()


def test_exposeSettingsPage_selects_existing_owner_and_reopens(owned, monkeypatch):
    from nodelang import universal_application as app
    from nodelang.canvas_graph_owner import CanvasOwner
    owner, reopen, _runtime = owned
    projection = {'nodes':[{'id':'application', 'application':True, 'params':[
        {'label':'accent','setting':{'kind':'theme'}}]}]}
    monkeypatch.setattr(CanvasOwner, 'canvas', lambda self:projection)
    def select(store, registry, root, **kwargs):
        assert root == 'application' and kwargs['authentication_context'] == 'context'
        node = Cell('selection',root,'account',root.encode())
        store.commit(store.revision, **{'replace' if 'selection' in store.snapshot().cells else 'create':(node,)})
    monkeypatch.setattr(app,'select_universal_root',select)
    result = owner().dispatch('exposeSettingsPage',['Appearance'])
    assert result['id'] == 'application'
    assert reopen().store.snapshot().cells['selection'].link0 == 'application'
    before = owner().store.revision
    with pytest.raises(InvalidCell): owner().exposeSettingsPage('Invented')
    assert owner().store.revision == before


def test_setProviderModel_consumed_by_provider_call_and_reopens(owned, monkeypatch):
    from nodelang import model_router, universal_application as app
    from nodelang.application_server import ApplicationServer
    owner, reopen, runtime = owned
    runtime._project_model_discovery = lambda path:{'groups':[{'items':[
        {'routed':'ollama/first'}, {'routed':'ollama/second'}, {'routed':'lmstudio/other'}]}]}
    result = owner().dispatch('setProviderModel',['ollama','ollama/second'])
    assert result['providerPreferences']['ollama'] == 'ollama/second'
    restored = reopen()
    monkeypatch.setattr(app,'read_universal_composer_model',lambda *args:{'source':'graph','value':'ollama/first'})
    server = SimpleNamespace(universal_store=restored.store, universal_registry=runtime.universal_registry)
    route = ApplicationServer._read_agent_model(server)
    calls=[]
    def provider(request, *, timeout):
        calls.append(request)
        return BytesIO(json.dumps({'message': {'role': 'assistant', 'content': 'ok'}, 'done': True}).encode())
    response = model_router.route_chat(route,[{'role':'user','content':'test'}],
        opener=provider,environ={},secrets_loader=lambda key:'',cloud_session=None)
    assert response['text'] == 'ok'
    assert calls[0].full_url == 'http://127.0.0.1:11434/api/chat'
    assert json.loads(calls[0].data)['model'] == 'second'
    assert restored.providerModel('lmstudio/other') == 'lmstudio/other'
    before=restored.store.revision
    for args in [('ollama','lmstudio/other'),('unknown','ollama/second'),('ollama','ollama/not-listed')]:
        with pytest.raises(InvalidCell): restored.setProviderModel(*args)
    assert restored.store.revision == before


def test_disconnectSecret_exact_vault_binding_effect_and_reopens(owned, monkeypatch):
    from nodelang import model_router
    owner,reopen,runtime=owned
    entries=[{'vault_entry':'social-fixture','provider':'meta','account_id':'123','account_binding':'verified'}]
    monkeypatch.setattr(model_router,'list_social_credentials',lambda:{'ok':True,'items':list(entries)})
    calls=[]
    runtime.require_universal_http_route=lambda *args,**kwargs:calls.append((args,kwargs))
    def remove(body, *, before_replace):
        assert body == {'vault_entry':'social-fixture','provider':'meta','account_id':'123'}
        before_replace()
        entries.clear()
        return {**body,'ok':True,'state':'removed','provider_token_revoked':False}
    monkeypatch.setattr(model_router,'revoke_social_credential',remove)
    with pytest.raises(InvalidCell):owner().disconnectSecret('raw-secret-id')
    assert entries and not calls
    result=owner().dispatch('disconnectSecret',['social-fixture'])
    assert result['secrets']==[] and result['provider_token_revoked'] is False and len(calls)==1
    restored=reopen()
    assert restored.readControls()['secrets']==[]
    assert restored._preferences('account')['disconnectedAccounts']['social-fixture']['account_id']=='123'


def test_readNotification_source_bound_receipt_and_reopens(owned, monkeypatch):
    from nodelang.workshop_api import WorkshopAPI
    from nodelang import universal_application as app
    owner,reopen,runtime=owned
    settings=owner()
    store=settings.store
    store.commit(store.revision,create=(Cell('work','application','account',b'work'),))
    runtime.universal_store=store
    runtime.universal_registry.roles={'member':'application'}
    api=WorkshopAPI(runtime,SimpleNamespace(subject_root='account',context='context'),'application','application',
        guard=lambda:None,request_id='test',route='/api/universal/workshop')
    monkeypatch.setattr(WorkshopAPI,'admit',lambda self:self.owner.universal_store.snapshot())
    monkeypatch.setattr(WorkshopAPI,'_works',lambda self:[{'root':'work'}])
    monkeypatch.setattr(WorkshopAPI,'_messages',lambda self,task:([{'id':'message','who':'agent','text':'Actual result'}],False))
    monkeypatch.setattr(app,'_view_session_for_context',lambda *args:('view','context'))
    monkeypatch.setattr('nodelang.workshop_api.prepare_append_relation_members',lambda *args:SimpleNamespace(create=(),replace=()))
    def commit(store,registry,view,context,snapshot,**kwargs):
        return store.commit(snapshot.revision,create=kwargs['create'],replace=kwargs['replace'])
    monkeypatch.setattr(app,'_commit_universal_user_change',commit)
    assert api.listNotifications()['notifications'][0]['read'] is False
    with pytest.raises(InvalidCell):api.readNotification('unknown')
    result=api.readNotification('message')
    assert result['notifications'][0]['read'] is True
    restored=reopen();runtime.universal_store=restored.store
    assert api.listNotifications()['notifications'][0]['read'] is True
    receipt=restored.store.snapshot().cells[result['receipt']]
    assert receipt.link0=='work' and receipt.link1=='account'
    assert json.loads(receipt.atom)['message']=='message'
    before = restored.store.revision
    assert api.readNotification('message')['receipt'] == receipt.id
    assert restored.store.revision == before
    api.binding.subject_root = 'another-account'
    assert api.listNotifications()['notifications'][0]['read'] is False


def test_setCompanionState_snapshot_getter_and_reopens(owned):
    from nodelang.app_agents import AgentsAPI
    owner,reopen,_runtime=owned
    result=owner().dispatch('setCompanionState',[{'mode':'listening','x':120,'y':240,'pinned':True}])
    assert result['companion']['mode']=='listening'
    restored=reopen()
    api=AgentsAPI(transport=None,companion=SimpleNamespace(running=False),settings=restored)
    assert api.getDesktopCompanion()['companion']=={'mode':'listening','x':120,'y':240,'pinned':True}
    restored.setCompanionState({'pinned':False})
    assert restored.readControls()['companion']['x']==120
    before=restored.store.revision
    for values in [{'mode':'invented'},{'mode':[]},{'x':float('nan')},{'pinned':1},{'secret':'x'},{'x':1}]:
        with pytest.raises(InvalidCell):restored.setCompanionState(values)
    assert restored.store.revision==before


def test_disconnect_unconfirmed_or_unadmitted_never_records_success(owned, monkeypatch):
    from nodelang import model_router
    owner, _reopen, runtime = owned
    entry = {'vault_entry':'social-fixture', 'provider':'meta', 'account_id':'123'}
    monkeypatch.setattr(model_router, 'list_social_credentials', lambda: {'ok':True, 'items':[entry]})
    monkeypatch.setattr(model_router, 'revoke_social_credential',
        lambda *args, **kwargs: {**entry, 'ok':True, 'state':'removed', 'provider_token_revoked':False})
    before = owner().store.revision
    with pytest.raises(InvalidCell, match='not confirmed'):
        owner().disconnectSecret('social-fixture')
    assert owner().store.revision == before
    def refused(*args, **kwargs):
        raise InvalidCell('route revoked')
    runtime.require_universal_http_route = refused
    def revoke(body, *, before_replace):
        before_replace()
        pytest.fail('Revoked route reached physical removal')
    monkeypatch.setattr(model_router, 'revoke_social_credential', revoke)
    with pytest.raises(InvalidCell, match='route revoked'):
        owner().disconnectSecret('social-fixture')
    assert owner().store.revision == before


def test_readControls_keeps_companion_when_other_owners_unavailable(owned, monkeypatch):
    from nodelang import model_router
    owner, _reopen, runtime = owned
    owner().setCompanionState({'pinned': True})
    def unavailable():
        raise model_router.ProviderCredentialError('secure_store_invalid')
    monkeypatch.setattr(model_router, 'list_social_credentials', unavailable)
    runtime._project_model_discovery = lambda path: {'ok':False}
    result = owner().readControls()
    assert result['companion']['pinned'] is True
    assert set(result['controlErrors']) == {'secrets', 'providerModels'}


def test_settings_real_application_selection_and_reopen(tmp_path, monkeypatch):
    from nodelang import commit_intent, universal_pipeline, universal_application as app
    from nodelang.canvas_graph_owner import CanvasOwner
    from tests_replica import test_approval_actions as support
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(universal_pipeline, 'seed_engine_library', lambda *args: 0)
    fixture = support.approvals.__wrapped__(tmp_path, monkeypatch,
        SimpleNamespace(node=SimpleNamespace(name='settings_durable')))
    surface = next(fixture)
    try:
        def owner():
            return SettingsOwner(surface.store, runtime=surface.server, dependencies=object(),
                authentication_context=surface.binding.context)
        monkeypatch.setattr(surface.server, '_project_model_discovery', lambda path: {
            'groups':[{'items':[{'routed':'ollama/first'}, {'routed':'ollama/second'}]}]})
        with commit_intent.declare(commit_intent.USER_ACTION, actor=surface.binding.subject_root,
                                   reason='isolated settings effects'):
            selected = owner().exposeSettingsPage('Appearance')
            assert selected['id'] in surface.store.snapshot().cells
            owner().setCompanionState({'mode': 'listening', 'x': 120, 'y': 240, 'pinned': True})
            app.set_universal_composer_model(surface.store, surface.registry, 'ollama/first',
                authentication_context=surface.binding.context)
            owner().setProviderModel('ollama', 'ollama/second')
        assert surface.server._read_agent_model() == 'ollama/second'
        projected = CanvasOwner(surface.store, surface.registry, surface.binding.context).canvas()
        assert projected['selected'] == selected['id']
        surface.server.close()
        surface.start()
        assert owner().companionState() == {'mode': 'listening', 'x': 120, 'y': 240, 'pinned': True}
        assert surface.server._read_agent_model() == 'ollama/second'
        projected = CanvasOwner(surface.store, surface.registry, surface.binding.context).canvas()
        assert projected['selected'] == selected['id']
    finally:
        try:
            next(fixture)
        except StopIteration:
            pass
