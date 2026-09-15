import pytest
from nodelang import native_start_hook as hook, native_session_resume

SESSION='71743447-6dd5-4050-bc4f-d228f7a1d91e'

def test_start_uses_exact_payload_identity_and_no_owner(monkeypatch):
    calls=[]
    monkeypatch.setattr(native_session_resume,'resume_existing_links',lambda env,**kwargs:calls.append(env) or {'status':'observed'})
    result=hook.recover_start({'hook_event_name':'SessionStart','session_id':SESSION},
        state_directory='C:/instance/session-link',node_executable='C:/installed/runtime/node.exe',environment={})
    assert calls[0]['CLAUDE_CODE_SESSION_ID']==SESSION
    assert result['hookSpecificOutput']['hookEventName']=='SessionStart'
    assert 'original Work assignment' in result['hookSpecificOutput']['additionalContext']

def test_unrelated_task_is_untouched(monkeypatch):
    monkeypatch.setattr(native_session_resume,'resume_existing_links',lambda *a,**k:pytest.fail('unrelated task'))
    assert hook.recover_start({'hook_event_name':'SessionStart','session_id':'other'},
        state_directory='C:/instance',node_executable='C:/node.exe',expected_session=SESSION)=={}

def test_codex_start_uses_registered_root_and_required_links(monkeypatch):
    calls=[]
    monkeypatch.setattr(native_session_resume,'resume_existing_links',lambda env,**kwargs:calls.append((env,kwargs)) or {'status':'observed'})
    hook.recover_start({'hook_event_name':'SessionStart','session_id':SESSION},runtime='codex',
        expected_session=SESSION,state_directory='C:/instance',node_executable='C:/node.exe',
        required_connections=['a'*16],environment={})
    assert calls[0][0]['CODEX_THREAD_ID']==SESSION
    assert calls[0][1]['required_connections']==['a'*16]

def test_conflicting_native_identity_is_refused_before_transport(monkeypatch):
    monkeypatch.setattr(native_session_resume,'resume_existing_links',lambda _:pytest.fail('must not run'))
    with pytest.raises(ValueError):
        hook.recover_start({'hook_event_name':'SessionStart','session_id':SESSION},
            state_directory='C:/instance',node_executable='C:/node.exe',environment={'CLAUDE_CODE_SESSION_ID':'other'})
