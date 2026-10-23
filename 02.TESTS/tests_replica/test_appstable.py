"""Small behavioral courts for the existing Workshop projection and UI runner."""
from types import SimpleNamespace

import pytest

from nodelang import agent_declarations
from nodelang.cell_authorization import AuthorizationDenied
from nodelang.universal_cell import InvalidCell
from nodelang.workshop_api import WorkshopAPI

pytest_plugins = ['tests_replica.test_workshop_assign_to_agent']


@pytest.mark.parametrize('current,delegate,expected', [
    (False, None, 'codex'), (True, None, 'codex'),
    (False, 'claude', 'claude'),
])
def test_task_keeps_its_recorded_owner_after_the_session_finishes(monkeypatch, current, delegate, expected):
    monkeypatch.setattr(agent_declarations, 'declarations', lambda owner, **kw: [
        {'request_id':'work:fixture','app':'codex','status':'working' if current else 'done',
         'current':current,'session':'session:codex'}] if kw.get('include_archived') or current else [])
    api = WorkshopAPI(SimpleNamespace(universal_store=SimpleNamespace(revision=1)),
        None, 'room', 'scope', guard=lambda: None, request_id='fixture', route='fixture')
    monkeypatch.setattr(api, '_options', lambda task: {'delegate':delegate})
    monkeypatch.setattr(api, '_messages', lambda task: ([], False))
    task = api._task({'root':'work:fixture', 'operational':{'current_state_label':'open'},
                     'interfaces':{'title':{'value':'Existing saved task'}}})
    assert task['owner'] == expected
    assert task['status'] == ('WIP' if current else 'PLANNED')


def test_an_unassigned_task_never_invents_a_founder_or_agent(monkeypatch):
    monkeypatch.setattr(agent_declarations, 'declarations', lambda owner, **kw: [])
    api = WorkshopAPI(SimpleNamespace(universal_store=SimpleNamespace(revision=1)),
        None, 'room', 'scope', guard=lambda: None, request_id='fixture', route='fixture')
    monkeypatch.setattr(api, '_options', lambda task: {})
    monkeypatch.setattr(api, '_messages', lambda task: ([], False))
    task = api._task({'root':'work:fixture', 'operational':{'current_state_label':'open'},
                     'interfaces':{'title':{'value':'Existing unassigned task'}}})
    assert task['owner'] is None


@pytest.mark.parametrize('delegate,expected', [(None, None), ('claude', 'claude')])
def test_ambiguous_history_does_not_guess_an_owner(monkeypatch, delegate, expected):
    monkeypatch.setattr(agent_declarations, 'declarations', lambda owner, **kw: [
        {'request_id':'work:fixture','app':app,'status':'done','current':False}
        for app in ['claude', 'codex']] if kw.get('include_archived') else [])
    api = WorkshopAPI(SimpleNamespace(universal_store=SimpleNamespace(revision=1)),
        None, 'room', 'scope', guard=lambda: None, request_id='fixture', route='fixture')
    monkeypatch.setattr(api, '_options', lambda task: {'delegate':delegate})
    monkeypatch.setattr(api, '_messages', lambda task: ([], False))
    task = api._task({'root':'work:fixture', 'operational':{'current_state_label':'open'},
                     'interfaces':{'title':{'value':'Existing task with several past agents'}}})
    assert task['owner'] == expected
    assert task['status'] == 'PLANNED'


@pytest.mark.parametrize('runtimes,expected,failure', [
    (['codex'], 'codex', None), (['codex', 'claude'], None, None),
    (['expired'], None, InvalidCell), (['expired'], None, AuthorizationDenied),
])
def test_committed_claim_restores_owner_after_declaration_was_replaced(monkeypatch, runtimes, expected, failure):
    from nodelang import cell_agent_body, universal_application
    monkeypatch.setattr(agent_declarations, 'declarations', lambda owner, **kw: [])
    def read_session(snapshot, protocol, auth, root):
        if failure:
            raise failure('The fixture historical session is no longer readable')
        return root
    monkeypatch.setattr(cell_agent_body, 'read_agent_session', read_session)
    monkeypatch.setattr(universal_application, '_agent_body_catalog_entry_for_session',
                        lambda snapshot, registry, session: SimpleNamespace(runtime=session.rsplit(':', 1)[-1]))
    registry = SimpleNamespace(agent_body=SimpleNamespace(protocol=None),
                               authorization=SimpleNamespace(protocol=None))
    api = WorkshopAPI(SimpleNamespace(universal_store=SimpleNamespace(revision=1), universal_registry=registry),
        None, 'room', 'scope', guard=lambda: None, request_id='fixture', route='fixture')
    monkeypatch.setattr(api, 'admit', lambda: object())
    monkeypatch.setattr(api, '_options', lambda task: {})
    monkeypatch.setattr(api, '_messages', lambda task: ([], False))
    task = api._task({'root':'work:fixture', 'operational':{'current_state_label':'claimed',
        'history':[{'event_label':'claim','context':['app:agent-session:runtime:'+app for app in runtimes]}]},
        'interfaces':{'title':{'value':'Saved claimed task'}}})
    assert task['owner'] == expected
    assert task['status'] == 'WIP'


def test_real_work_claim_projects_its_owner_without_a_declaration(served, monkeypatch):
    from tests_replica.test_workshop_assign_to_agent import _work, _running_agent, _assign, _scope
    server, descriptor, provider = served
    work = _work(server, 'appstable:recorded-owner')['created_root']
    client, session = _running_agent(server, descriptor, provider, 'appstable-recorded-owner')
    assert _assign(server, work, session, 'app:workshop-assignment:appstable-owner')[0] == 200
    assert client.claim_work(work)['claimed'] is True
    monkeypatch.setattr(agent_declarations, 'declarations', lambda owner, **kw: [])
    binding = server._resolve_browser_session(server.browser_session_token)
    api = WorkshopAPI(server, binding, server.universal_registry.workshop_root, _scope(server),
        guard=lambda: None, request_id='appstable-owner-read', route='/api/universal/workshop')
    before = server.universal_store.revision
    task = next(task for task in api.listTasks() if task['id'] == work)
    assert task['owner'] == 'codex'
    assert task['status'] == 'WIP'
    assert server.universal_store.revision == before
