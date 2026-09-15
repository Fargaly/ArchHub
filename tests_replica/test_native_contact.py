"""Real graph contact + indexed content; simulated external transport only."""
import time
from types import SimpleNamespace as NS
from nodelang import native_contact as contact
from nodelang import universal_application as app
from tests_replica.test_workshop_project_revision import owner

class Transport:
    endpoint={'app':'claude','id':'existing-external','title':'Existing Claude','cwd':'fixture','pid':123}
    def __init__(self):self.calls=[];self.status="replied"
    def discover(self,timeout_seconds=3,**kwargs):return {'status':'ok','recipients':[self.endpoint]}
    def request(self,recipient,text,**kwargs):
        self.calls.append((recipient,text))
        return {'status':self.status,'reply':{'text':'Fixture reply'}}
    def cancel_pending(self,**kwargs):return {'local_call_joined':True,'worker_stopped':True}
    def close(self):pass


def test_contact_creates_atomic_user_node_and_relays_once_in_same_content(owner,tmp_path):
    transport=Transport();owner.native_recipient_relay._transport=transport
    browser=owner._resolve_browser_session(owner.browser_session_token)
    registry=owner.universal_registry
    from nodelang.conversation_content import prepare_empty_content_binding
    from nodelang.conversation_history import ConversationHistoryStore
    owner.conversation_content._path=tmp_path/'contact-history.sqlite3'
    adopted=prepare_empty_content_binding(owner.universal_store.snapshot(),registry.deliberation_protocol,
        application_root=registry.application_root,space_root=registry.workshop_root)
    with ConversationHistoryStore(owner.conversation_content._path,instance_id=adopted.binding.instance_id) as history:
        history.ensure_conversation(registry.workshop_root);history.initialize_retention()
    owner.universal_store.commit(adopted.expected_revision,create=adopted.create,replace=adopted.replace)
    before=owner.universal_store.revision
    bound=contact.bind_native_contact(owner,browser,{'root':registry.workshop_root,'scope':registry.workshop_workbench_root,
        'node':None,'app':'claude','session_id':'existing-external','revision':before},browser_guard=lambda:None)
    assert bound['revision']==before+1
    assert bound['contact'].startswith('app:wip-cell:')
    assert not owner._machine_agent_sessions
    reused=contact.bind_native_contact(owner,browser,{'root':registry.workshop_root,'scope':registry.workshop_workbench_root,
        'node':None,'app':'claude','session_id':'existing-external','revision':before},browser_guard=lambda:None)
    assert reused['contact']==bound['contact'] and reused['reused'] is True
    assert owner.universal_store.revision==bound['revision']
    app.set_universal_scope(owner.universal_store,registry,registry.map.domains["brain"],authentication_context=browser.context)
    app.set_universal_scope(owner.universal_store,registry,registry.workshop_workbench_root,authentication_context=browser.context)
    discovery=contact.discover_native_agents(owner)
    assert {row['app'] for row in discovery['readiness']}=={'claude','codex','gemini'}
    rows=contact.project_native_contacts(owner,browser,root=bound['root'],scope=bound['scope'],discovery=discovery)
    assert rows[0]['root']==bound['contact'] and rows[0]['connected'] is True
    body={'root':bound['root'],'scope':bound['scope'],'contact':bound['contact'],
        'binding_digest':bound['binding_digest'],'text':'User message','idempotency_key':'contact-one'}
    result=contact.send_native_contact(owner,browser,body,browser_guard=lambda:None)
    deadline=time.monotonic()+3
    while owner.native_recipient_relay._pending_jobs and time.monotonic()<deadline:time.sleep(.01)
    assert owner.native_recipient_relay.last_error is None
    assert len(transport.calls)==1
    again=contact.send_native_contact(owner,browser,body,browser_guard=lambda:None)
    assert again['message_id']==result['message_id']
    assert again['relay']['state']=='already_recorded'
    assert len(transport.calls)==1 and not owner._machine_agent_sessions
    page=owner.conversation_content.page_for_workshop_browser(owner.browser_session_token,binding=browser,space_root=bound['root'])
    assert 'Fixture reply' in str(page)
    # A process change after binding may not redirect the persisted contact.
    transport.endpoint={**transport.endpoint,'pid':124}
    changed=contact.send_native_contact(owner,browser,{**body,'idempotency_key':'changed-endpoint'},browser_guard=lambda:None)
    deadline=time.monotonic()+3
    while owner.native_recipient_relay._pending_jobs and time.monotonic()<deadline:time.sleep(.01)
    assert len(transport.calls)==1
    transport.endpoint={**transport.endpoint,'pid':123};transport.status='held'
    held=contact.send_native_contact(owner,browser,{**body,'idempotency_key':'held-endpoint'},browser_guard=lambda:None)
    deadline=time.monotonic()+3
    while owner.native_recipient_relay._pending_jobs and time.monotonic()<deadline:time.sleep(.01)
    assert len(transport.calls)==2
    page=owner.conversation_content.page_for_workshop_browser(owner.browser_session_token,binding=browser,space_root=bound['root'])
    assert 'held or refused' in str(page)
    assert not owner._machine_agent_sessions
    # A real registered child uses this same content owner and exact retry binding.
    from nodelang.workshop_conversation_catalog import create_workshop_conversation
    child=create_workshop_conversation(owner,authentication_context=browser.context,
        expected_revision=owner.universal_store.revision,title='Native child',
        participant_roots=[browser.subject_root],idempotency_key='native-child')
    selection={'root':child['root'],'scope':registry.workshop_workbench_root,
        'node':None,'app':'claude','session_id':'existing-external','revision':owner.universal_store.revision}
    child_bound=contact.bind_native_contact(owner,browser,selection,browser_guard=lambda:None)
    child_again=contact.bind_native_contact(owner,browser,selection,browser_guard=lambda:None)
    assert child_again['contact']==child_bound['contact'] and child_again['reused']
    assert child_bound['contact']!=bound['contact'] and child_bound['root']==child['root']
    transport.status='replied'
    child_body={**body,'root':child['root'],'contact':child_bound['contact'],
        'binding_digest':child_bound['binding_digest'],'idempotency_key':'child-one'}
    child_sent=contact.send_native_contact(owner,browser,child_body,browser_guard=lambda:None)
    deadline=time.monotonic()+3
    while owner.native_recipient_relay._pending_jobs and time.monotonic()<deadline:time.sleep(.01)
    assert owner.native_recipient_relay.last_error is None
    assert len(transport.calls)==3
    child_retry=contact.send_native_contact(owner,browser,child_body,browser_guard=lambda:None)
    assert child_retry['message_id']==child_sent['message_id'] and len(transport.calls)==3
    child_page=owner.conversation_content.page_for_workshop_browser(owner.browser_session_token,
        binding=browser,space_root=child['root'])
    assert 'Fixture reply' in str(child_page) and not owner._machine_agent_sessions
    import pytest
    from nodelang.cell_authorization import AuthorizationDenied
    with pytest.raises(AuthorizationDenied):
        contact.read_contact(owner,browser,child_bound['contact'],child_bound['binding_digest'],
            registry.workshop_root,registry.workshop_workbench_root)


def test_discovery_projection_strips_transport_credentials_and_addresses():
    class Discovery:
        def discover(self,**kwargs):
            assert kwargs=={'timeout_seconds':3,'apps':['claude']}
            return {'status':'ok','recipients':[{'app':'claude','id':'session','title':'Chat',
                'socket':'private-pipe','token':'secret-sentinel','keyPath':'private-key-file'}]}
    result=contact.discover_native_agents(NS(native_recipient_relay=NS(_transport=Discovery())))
    assert result['rows'][0]['selectable'] is True
    assert all(value not in str(result) for value in ('secret-sentinel','private-key-file','private-pipe'))


def test_discovery_ambiguous_identity_cannot_be_selected():
    target={'app':'claude','id':'same','pid':1}
    transport=NS(discover=lambda **kwargs:{'status':'ok','recipients':[target,{**target,'pid':2}]})
    result=contact.discover_native_agents(NS(native_recipient_relay=NS(_transport=transport)))
    assert len(result['rows'])==1 and result['rows'][0]['selectable'] is False


def test_scoped_contact_absence_is_unknown_unless_complete():
    result={'status':'ok','rows':[],'queried_apps':['claude'],'complete_apps':['claude'],'truncated':False}
    assert contact.native_contact_presence(result,'codex','saved') is None
    assert contact.native_contact_presence(result,'claude','saved') is False
    assert contact.native_contact_presence({**result,'truncated':True},'claude','saved') is None
    assert contact.native_contact_presence({**result,'complete_apps':[]},'claude','saved') is None
    assert contact.native_contact_presence({**result,'status':'unavailable'},'claude','saved') is None
    assert contact.native_contact_presence({**result,'rows':[{'app':'claude','session_id':'saved','selectable':False}]},'claude','saved') is None
