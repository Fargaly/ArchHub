from types import SimpleNamespace as NS
import pytest
from nodelang import native_session_resume as resume


def test_missing_configuration_never_starts_process(monkeypatch):
    monkeypatch.setattr(resume.subprocess,'run',lambda *a,**k: (_ for _ in ()).throw(AssertionError()))
    assert resume.resume_existing_links({})['status']=='not_configured'


def test_resume_exact_current_without_message_or_new_session(tmp_path,monkeypatch):
    node=tmp_path/'node.exe'; node.touch()
    calls=[]
    def run(argv,**kwargs):
        calls.append((argv,kwargs))
        return NS(returncode=0,stdout='[{"id":"aaaaaaaaaaaaaaaa","status":"already_connected","endpoints_observed":true,"connection":{"id":"aaaaaaaaaaaaaaaa","codex":"exact-thread"}}]')
    monkeypatch.setattr(resume.subprocess,'run',run)
    result=resume.resume_existing_links({'SESSION_LINK_NODE':str(node),
        'SESSION_LINK_STATE_DIR':str(tmp_path),'CODEX_THREAD_ID':'exact-thread'},required_connections=['a'*16])
    assert result['status']=='observed'
    assert result['work_recovery_required'] is True
    assert calls[0][0][-4:]==['resume','--current','--connections','a'*16]
    assert calls[0][1]['env']['CODEX_THREAD_ID']=='exact-thread'
    assert calls[0][1]['timeout']==4


@pytest.mark.parametrize('stdout', ['[]',
    '[{"id":"aaaaaaaaaaaaaaaa","status":"already_connected","endpoints_observed":true,"connection":{"id":"aaaaaaaaaaaaaaaa","claude":"exact-thread","codex":"other"}}]',
    '[{"id":"aaaaaaaaaaaaaaaa","status":"recovery_required"}]'])
def test_missing_wrong_role_or_unresolved_required_result_refuses(tmp_path,monkeypatch,stdout):
    node=tmp_path/'node.exe';node.touch()
    monkeypatch.setattr(resume.subprocess,'run',lambda *a,**k:NS(returncode=0,stdout=stdout))
    result=resume.resume_existing_links({'SESSION_LINK_NODE':str(node),'SESSION_LINK_STATE_DIR':str(tmp_path),
        'CODEX_THREAD_ID':'exact-thread'},required_connections=['a'*16])
    assert result['status']=='recovery_required'


def test_timeout_is_distinguished_from_other_failures(tmp_path,monkeypatch):
    node=tmp_path/'node.exe';node.touch()
    def timeout(*args,**kwargs):raise resume.subprocess.TimeoutExpired(args[0],4)
    monkeypatch.setattr(resume.subprocess,'run',timeout)
    result=resume.resume_existing_links({'SESSION_LINK_NODE':str(node),'SESSION_LINK_STATE_DIR':str(tmp_path),
        'CODEX_THREAD_ID':'exact-thread'},required_connections=['a'*16])
    assert result['reason']=='transport_resume_timeout' and result['timeout_seconds']==4
