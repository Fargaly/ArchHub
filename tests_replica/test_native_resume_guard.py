from types import SimpleNamespace as NS
from nodelang.native_resume_guard import NativeResumeGuard


def fixture():
    calls=[]
    owner=NS(_environment={})
    status={'state':'bound','agent_session':'actor','rebind_pending':False,
        'recovery_required':False,'pinned':{'fingerprint':'old','instance_digest':'instance'},
        'current':{'fingerprint':'old','instance_digest':'instance'}}
    owner.owner_status=lambda:dict(status)
    def rebind(**kwargs):calls.append('rebind');status['recovery_required']=False
    owner.rebind_owner=rebind
    return owner,status,calls


def test_transport_failure_never_rebinds():
    owner,status,calls=fixture()
    guard=NativeResumeGuard(owner,transport_resume=lambda _: {'status':'recovery_required'})
    assert guard.recover()['status']=='recovery_required'
    assert calls==[]


def test_same_actor_recovery_is_not_work_admission():
    owner,status,calls=fixture();status['recovery_required']=True
    status['current']['fingerprint']='new'
    guard=NativeResumeGuard(owner,transport_resume=lambda _: {'status':'observed'})
    result=guard.recover()
    assert result['status']=='owner_restored' and result['work_admission_required'] is True
    assert calls==['rebind']


def test_uncertain_owner_is_not_reenrolled():
    owner,status,calls=fixture();status['state']='uncertain'
    guard=NativeResumeGuard(owner,transport_resume=lambda _: {'status':'observed'})
    assert guard.recover()['status']=='recovery_required'
    assert calls==[]


def test_fresh_process_continues_only_existing_expected_actor():
    owner,status,calls=fixture();status.update(state='unbound',agent_session=None)
    owner._expected_agent_session='original';owner._continued=False
    owner.inspect_enrollment=lambda **kwargs:calls.append('inspect')
    def connect(**kwargs):
        calls.append('conditional-connect');status.update(state='bound',agent_session='original');owner._continued=True
    owner.connect=connect
    guard=NativeResumeGuard(owner,transport_resume=lambda _: {'status':'observed'})
    assert guard.recover()['actor']=='original'
    assert calls==['inspect','conditional-connect']


def test_selected_effect_recovers_before_existing_claim_admission():
    from contextlib import contextmanager
    from nodelang.native_workshop_tools import _SelectedWork
    calls=[]
    client=NS(agent_session_root='actor',current_work_assignment=lambda: calls.append('assignment') or
        {'agent_session':'actor','projection':'assignment','revision':3,'work':None})
    @contextmanager
    def bound():yield client
    control=NS(bound_client=bound,resume_guard=NS(recover=lambda:calls.append('restore') or {'status':'owner_restored'}))
    selected=_SelectedWork(control,'assembly-instance:original')
    with selected.effect('claim',None):calls.append('effect')
    assert calls==['restore','assignment','effect']


def test_pending_selected_receipt_prevents_recovery_or_effect():
    from nodelang.native_workshop_tools import _SelectedWork
    from nodelang.application_machine_transport import MachineTransportError
    import pytest
    calls=[]
    selected=_SelectedWork(NS(resume_guard=NS(recover=lambda:calls.append('restore'))),'assembly-instance:original')
    selected.pending=('claim',3,None)
    with pytest.raises(MachineTransportError):
        with selected.effect('claim',None):calls.append('effect')
    assert calls==[] and selected.pending==('claim',3,None)


def test_recovery_server_keeps_tools_discoverable_without_connect(monkeypatch):
    from nodelang import native_agent_mcp as mcp
    from nodelang.native_resume_guard import NativeResumeGuard
    calls=[]
    owner=NS(owner_status=lambda:{'state':'unbound'},connect=lambda:calls.append('connect'))
    monkeypatch.setattr(NativeResumeGuard,'recover',lambda self:{'status':'recovery_required'})
    server,activate=mcp.build_recovery_server(owner)
    assert activate()['status']=='recovery_required'
    assert calls==[]
    names={tool.name for tool in server._tool_manager.list_tools()}
    assert names=={'native.owner_status','native.resume_recover','native.owner_recover','native.connection_recover','native.owner_inspect_effects'}


def test_dormant_recovery_inspection_uses_same_owner_and_never_activates():
    from nodelang import native_agent_mcp as mcp
    calls=[]
    owner=NS(inspect_enrollment=lambda **kwargs:calls.append(kwargs) or {'continued':False})
    server,_activate=mcp.build_recovery_server(owner)
    tool=next(tool for tool in server._tool_manager.list_tools() if tool.name=='native.owner_inspect_effects')
    assert tool.fn(expected_owner='exact-owner',cursor='next')=={'continued':False}
    assert calls==[{'expected_owner':'exact-owner','projection':'effects','cursor':'next'}]


def test_clean_entrypoint_expected_actor_exposes_recovery_without_activation(monkeypatch):
    import sys
    from nodelang import clean_coordination_mcp as clean
    from nodelang import native_agent_mcp as native
    from nodelang import native_agent_session as session
    calls=[];owner=object()
    monkeypatch.setattr(sys,'argv',['clean','--expected-actor','original'])
    monkeypatch.setattr(session,'NativeAgentSession',lambda **kwargs:calls.append(kwargs) or owner)
    monkeypatch.setattr(clean,'build_server',lambda **kwargs:(_ for _ in ()).throw(AssertionError('fresh bootstrap')))
    def recovery(selected):
        assert selected is owner
        return NS(run=lambda **kwargs:calls.append(kwargs)),lambda:(_ for _ in ()).throw(AssertionError('activation'))
    monkeypatch.setattr(native,'build_recovery_server',recovery)
    clean.main()
    assert calls==[{'expected_agent_session':'original'},{'transport':'stdio'}]


def test_recovery_server_publishes_existing_tools_only_after_same_owner(monkeypatch):
    from nodelang import native_agent_mcp as mcp
    from nodelang.native_resume_guard import NativeResumeGuard
    from mcp.server.fastmcp import FastMCP
    calls=[]
    owner=NS(owner_status=lambda:{'state':'bound'})
    monkeypatch.setattr(NativeResumeGuard,'recover',lambda self:calls.append('restore') or {'status':'owner_restored'})
    def build(**kwargs):
        assert kwargs['session'] is owner
        calls.append('build')
        result=FastMCP('fixture')
        @result.tool(name='workshop.task.claim')
        def claim():return {'fixture':True}
        return result
    monkeypatch.setattr(mcp,'build_server',build)
    server,activate=mcp.build_recovery_server(owner,workshop_task='assembly-instance:fixture')
    assert activate()['status']=='tools_available'
    assert activate()['status']=='tools_available'
    assert calls==['restore','build']
    assert 'workshop.task.claim' in {tool.name for tool in server._tool_manager.list_tools()}


def test_main_existing_resume_never_uses_fresh_bootstrap(monkeypatch):
    import sys
    from nodelang import native_agent_mcp as mcp
    calls=[]
    owner=object()
    monkeypatch.setattr(sys,'argv',['native-agent','--expected-actor','original'])
    monkeypatch.setattr(mcp,'NativeAgentSession',lambda **kwargs:calls.append(kwargs) or owner)
    monkeypatch.setattr(mcp,'build_server',lambda **kwargs:(_ for _ in ()).throw(AssertionError('fresh enrollment')))
    def recover(selected,**kwargs):
        assert selected is owner
        return NS(run=lambda **kwargs:calls.append('run')),lambda:calls.append('recover')
    monkeypatch.setattr(mcp,'build_recovery_server',recover)
    mcp.main()
    assert calls==[{'expected_agent_session':'original'},'recover','run']
