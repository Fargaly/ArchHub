"""Release refusal executes the same predicate the real qualification calls."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pytest
from tools.real_app_check.agentlink_release import require_checks, QualificationRefused


@pytest.mark.parametrize('selector', [
    'openrouter/auto', 'vendor/auto', 'openrouter/auto-beta',
    'vendor/router', 'vendor/best', 'vendor/free-router',
    'vendor/free_router', 'vendor/free.router', 'auto/model',
    'router/model', 'best/model', 'openrouter/free',
    'vendor/automatic', 'vendor/auto-router',
    'vendor/autorouter', 'vendor/freerouter', 'vendor/AUTO',
    'openrouter/pareto-code', 'openrouter/fusion', 'openrouter/fusion-flash',
    'openrouter/bodybuilder', 'nvidia/switchyard', 'typesafe/jev-router',
    'openrouter/autopilot', 'openrouter/smart', 'openrouter/selector',
    'openrouter/dynamic', 'openrouter/fastest', 'openrouter/cheapest',
    'openrouter/a-u-t-o', 'openrouter/owl-alpha', 'vendor/unknown',
])
def test_freesel_refuses_selectors_before_any_attempt(tmp_path, monkeypatch, selector):
    from tools.real_app_check import agentlink_release as gate
    model = 'openrouter/' + selector + ':free'
    monkeypatch.setattr(gate.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('selector child'))
    attempt = lambda *_a: pytest.fail('selector attempt')
    for models in ((model, *gate._FREE_FALLBACKS), (gate._FREE_FALLBACKS[0], model)):
        with pytest.raises(QualificationRefused, match='release free-model allow-list'):
            gate._free_turn(models, attempt, env={}, timeout=150)
    with pytest.raises(QualificationRefused, match='release free-model allow-list'):
        gate.qualify(tmp_path / 'PROFILE', model=model)
    assert not (tmp_path / 'PROFILE').exists()
    with pytest.raises(QualificationRefused, match='release free-model allow-list'):
        gate._free_stream_models('message=stream providerID=openrouter modelID=' + selector + ':free', model)


@pytest.mark.parametrize('selector', ['auto-free', 'router-free', 'best-free', 'free-router-free', 'smart-free', 'unknown-free'])
def test_freesel_refuses_opencode_selectors(selector):
    from tools.real_app_check import agentlink_release as gate
    with pytest.raises(QualificationRefused, match='release free-model allow-list'):
        gate._require_free_model('opencode/' + selector)


@pytest.mark.parametrize('pool', ['_FREE_FALLBACKS', '_GOOSE_FALLBACKS'])
def test_freesel_refuses_selector_fallback_before_process(tmp_path, monkeypatch, pool):
    from tools.real_app_check import agentlink_release as gate
    monkeypatch.setattr(gate, pool, ('openrouter/openrouter/autopilot:free',))
    monkeypatch.setattr(gate.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('selector child'))
    with pytest.raises(QualificationRefused, match='release free-model allow-list'):
        if pool == '_GOOSE_FALLBACKS':
            gate._goose_turn('fixture', ['reply'], env={}, cwd=tmp_path, proof_factory=lambda: None)
        else:
            gate._opencode_turn(['fixture', '-m', 'opencode/mimo-v2.6-flash-free'],
                model='opencode/mimo-v2.6-flash-free', env={}, cwd=tmp_path, timeout=150,
                quota_log=tmp_path / 'opencode.log')


def test_freesel_keeps_explicit_free_identities():
    from tools.real_app_check import agentlink_release as gate
    models = (*gate._FREE_FALLBACKS, *gate._GOOSE_FALLBACKS,
        'openrouter/' + gate._GOOSE_MODEL, 'opencode/mimo-v2.6-flash-free')
    assert gate._RELEASE_FREE_MODELS == frozenset(models)
    for model in models:
        gate._require_free_model(model)
        provider, identity = model.split('/', 1)
        assert gate._free_stream_models(
            f'message=stream providerID={provider} modelID={identity}', model) == [model]


@pytest.mark.parametrize('variant', ['nitro', 'floor', 'online', 'free'])
def test_free_route_rejects_stacked_model_variants(variant):
    from tools.real_app_check import agentlink_release as gate
    for model in ('openrouter/openai/gpt-5:'+variant+':free',
                  'openrouter/openai/gpt-5:free:'+variant):
        with pytest.raises(QualificationRefused, match='explicitly free'):
            gate._require_free_model(model)


@pytest.mark.parametrize('failure', ['rate', 'empty', 'all', 'tool', 'auth'])
def test_gooseroute_native_acp_fallback_keeps_paired_proof(tmp_path, monkeypatch, failure):
    from tools.real_app_check import agentlink_release as gate
    from nodelang import model_router
    monkeypatch.setattr(model_router, 'discover_key', lambda _: ('fixture-key', 'fixture'))
    stub = tmp_path / 'GOOSE.py'
    stub.write_text('''import base64,json,pathlib,sys
failure=sys.argv[1]
model=''
for line in sys.stdin.buffer:
 r=json.loads(line); method=r['method']; result={}
 if method=='session/new':
  encoded=r['params']['_meta']['recipeDeeplink']; recipe=json.loads(base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)))
  model=recipe['settings']['goose_model']
  with pathlib.Path('CALLS.txt').open('a') as f: f.write(model+'\\n')
  result={'sessionId':model}
 if method=='session/prompt':
  primary=model.startswith('dots-studio/')
  if failure in ('auth','all') or (primary and failure=='rate'):
   print(json.dumps({'jsonrpc':'2.0','id':r['id'],'error':{'code':-32603,'message':'401 invalid key' if failure=='auth' else '429 Too Many Requests'}}),flush=True); continue
  if not (primary and failure=='empty'):
   for tool in ('read','send'):
    update={'sessionUpdate':'tool_call_update','toolCallId':tool,'status':'failed' if failure=='tool' else 'completed','content':[{'type':'text','text':tool+' proof'}],'_meta':{'goose':{'toolCall':{'toolName':'archhub-agent__'+tool}}}}
    print(json.dumps({'jsonrpc':'2.0','method':'session/update','params':{'sessionId':model,'update':update}}),flush=True)
  result={'stopReason':'end_turn'}
 print(json.dumps({'jsonrpc':'2.0','id':r['id'],'result':result}),flush=True)
''', encoding='utf-8')
    original = gate.subprocess.Popen
    children = []
    def popen(command, **options):
        process = original([sys.executable, str(stub), failure], **options)
        children.append(process)
        return process
    monkeypatch.setattr(gate.subprocess, 'Popen', popen)
    proven = []
    def verify(output, session):
        assert session.startswith('connector-')
        assert [tool for tool, _ in gate.tool_receipts(output)] == ['archhub-agent__read', 'archhub-agent__send'] * 2
        proven.append(session)
    if failure in {'all', 'tool', 'auth'}:
        with pytest.raises(QualificationRefused) as refused:
            gate._goose_turn('fixture', ['declare', 'reply'], env=dict(os.environ), cwd=tmp_path, proof_factory=lambda: verify)
        assert len(refused.value.routes) == (2 if failure == 'all' else 1)
        assert not proven
    else:
        output, session, pid, selected, routes = gate._goose_turn('fixture', ['declare', 'reply'],
            env=dict(os.environ), cwd=tmp_path, proof_factory=lambda: verify)
        assert session == 'thinkingmachines/inkling:free'
        assert gate.tool_receipts(output)
        assert selected == 'openrouter/thinkingmachines/inkling:free'
        assert len(proven) == 1
        assert pid == children[-1].pid
        assert routes[0]['timeout'] >= 120
        assert routes[0]['timeout'] <= 180
        assert [r['reason'] for r in routes][-1] == 'completed'
    assert all(child.poll() is not None for child in children)


def test_gooseroute_ack_falls_back_without_requiring_file_writes(tmp_path, monkeypatch):
    from tools.real_app_check import agentlink_release as gate
    model = 'opencode/mimo-v2.6-flash-free'
    calls = []
    def run(command, **options):
        calls.append((command, options))
        if len(calls) == 1:
            raise gate._FreeProviderFailure('rate limited')
        return '\n'.join(json.dumps({'type':'tool_use', 'part':{'tool':tool,
            'state':{'status':'completed', 'output':'ACK proof'}}}) for tool in ['workshop_read','workshop_send'])
    monkeypatch.setattr(gate, '_run', run)
    def verify(output):
        assert [tool for tool, _ in gate.tool_receipts(output)] == ['workshop_read','workshop_send']
    output, selected, routes = gate._opencode_turn(['fixture','-m',model,'ACK nonce'], model=model,
        env={'OPENROUTER_API_KEY':'fixture-key'}, cwd=tmp_path, timeout=150,
        quota_log=tmp_path/'opencode.log', proof_factory=lambda: verify)
    assert selected == gate._FREE_FALLBACKS[0]
    assert not gate.write_sequence(output)
    assert [row['reason'] for row in routes] == ['rate limited','completed']
    assert 120 <= routes[0]['timeout'] <= 150
    assert all(command[-1] == 'ACK nonce' for command, _ in calls)


def test_gooseroute_nonfree_goose_is_refused_before_process(tmp_path, monkeypatch):
    from tools.real_app_check import agentlink_release as gate
    monkeypatch.setattr(gate, '_GOOSE_FALLBACKS', ('openrouter/vendor/paid',), raising=False)
    monkeypatch.setattr(gate.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('paid child'))
    with pytest.raises(QualificationRefused, match='explicitly free'):
        gate._goose_turn('fixture', ['reply'], env={}, cwd=tmp_path, proof_factory=lambda: (lambda *_: None))


def test_gooseroute_auth_cannot_steal_first_route_minimum(tmp_path, monkeypatch):
    from tools.real_app_check import agentlink_release as gate
    from nodelang import model_router
    now = [0.0]
    monkeypatch.setattr(gate.time, 'monotonic', lambda: now[0])
    def key(_provider):
        now[0] = 61.0
        return 'fixture-key', 'fixture'
    monkeypatch.setattr(model_router, 'discover_key', key)
    monkeypatch.setattr(gate.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('no120s left'))
    with pytest.raises(QualificationRefused, match='first 120 seconds') as refused:
        gate._goose_turn('fixture', ['reply'], env={}, cwd=tmp_path, proof_factory=lambda: (lambda *_: None))
    assert refused.value.routes == []


@pytest.mark.parametrize('marker', ['AGENTLINK-REPLY n', 'AGENTLINK-ACK n'])
def test_gooseroute_old_attempt_messages_cannot_prove_selected_route(marker):
    from tools.real_app_check import agentlink_release as gate
    old = {'id':'old','author':'selected','reply_to':'request','content':marker}
    new = {**old,'id':'new'}
    options = dict(seen={'old'}, author='selected', reply_to='request', marker=marker)
    with pytest.raises(QualificationRefused, match='fresh paired message'):
        gate._new_paired_message([old], **options)
    assert gate._new_paired_message([old,new], **options) == new
    for field in ('author','reply_to','content'):
        with pytest.raises(QualificationRefused):
            gate._new_paired_message([old,{**new,field:'wrong'}], **options)


@pytest.mark.parametrize('failure', ['read','notice','refs','prose'])
def test_gooseroute_paired_read_still_requires_completed_receipts(failure):
    from tools.real_app_check import agentlink_release as gate
    notice = {'id':'notice','refs':['a','b']}
    rows = [{'id':'request'},notice]
    valid = json.dumps({'type':'tool_use','part':{'tool':'workshop_read','state':{
        'status':'completed','output':json.dumps({'messages':rows})}}})
    gate._require_paired_read(valid,'request',notice)
    if failure == 'read':
        rows = [notice]
    elif failure == 'notice':
        rows = [{'id':'request'}]
    elif failure == 'refs':
        rows = [{'id':'request'},{'id':'notice','refs':['old','b']}]
    output = json.dumps({'type':'tool_use','part':{'tool':'workshop_read','state':{
        'status':'completed','output':json.dumps({'messages':rows})}}}) if failure != 'prose' else json.dumps({'messages':rows})
    with pytest.raises(QualificationRefused, match='completed paired read proof'):
        gate._require_paired_read(output,'request',notice)


def test_gooseroute_acp_close_during_dispatch_is_an_explicit_refusal():
    from nodelang.goose_adapter import AcpTransport, GooseRefused
    transport = AcpTransport.__new__(AcpTransport)
    transport.sequence, transport.closed = 0, False
    transport.send = lambda _message: setattr(transport,'closed',True)
    with pytest.raises(GooseRefused, match='connection is closed'):
        transport.request('session/prompt',{},deadline=0)


@pytest.mark.parametrize("failure", ["quota", "rate", "harness", "empty", "timeout", "sequence"])
def test_second_free_route_proves_the_same_sequence_in_a_real_child(tmp_path, monkeypatch, failure):
    from tools.real_app_check import agentlink_release as gate
    from nodelang import model_router
    monkeypatch.setattr(model_router, "discover_key", lambda _: ("fixture-key", "fixture"))
    log = tmp_path / "opencode.log"
    stub = tmp_path / "PROVIDER.py"
    stub.write_text('''import json,pathlib,sys,time
model=sys.argv[sys.argv.index('-m')+1]
root=pathlib.Path(sys.argv[1])
with (root/'CALLS.txt').open('a') as stream: stream.write(model+'\\n')
failure=sys.argv[2]
if model.startswith('opencode/') or ('inkling' in model and failure in ('quota','rate','harness')):
 provider,identity=model.split('/',1)
 message='Free usage limit reached' if model.startswith('opencode/') or failure=='quota' else ('429 Too Many Requests' if failure=='rate' else '403 only available on agentic harnesses')
 with (root/'opencode.log').open('a') as stream: stream.write('message="stream error" providerID='+provider+' modelID='+identity+' small=false error="'+message+'"\\n')
 time.sleep(20)
elif 'inkling' in model and failure=='timeout': time.sleep(20)
elif 'inkling' in model and failure=='empty': pass
else:
 tools=['read'] if 'inkling' in model and failure=='sequence' else ['write','read','write','glob']
 for tool in tools: print(json.dumps({'type':'tool_use','sessionID':model,'part':{'tool':tool,'state':{'status':'completed','output':'ok'}}}),flush=True)
''', encoding="utf-8")
    primary = "opencode/mimo-v2.6-flash-free"
    command = [sys.executable, str(stub), str(tmp_path), failure, "-m", primary]
    result = gate._opencode_turn(command, model=primary, env=dict(os.environ), cwd=tmp_path,
        timeout=8, quota_log=log)
    output, selected = result[:2]
    assert selected == "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"
    assert gate.write_sequence(output)
    assert (tmp_path / "CALLS.txt").read_text().splitlines() == [primary,
        "openrouter/thinkingmachines/inkling:free", selected]
    routes = result[2]
    assert [row['model'] for row in routes] == [primary, "openrouter/thinkingmachines/inkling:free", selected]
    assert routes[-1]['reason'] == 'completed'
    assert all(0 < row['timeout'] <= 8 for row in routes)


@pytest.mark.parametrize("model", ["opencode/paid", "openrouter/thinkingmachines/inkling", "other/model:free", "openrouter/:free"])
def test_paid_or_unrecognized_models_refuse_before_profile_creation(tmp_path, model):
    from tools.real_app_check import agentlink_release as gate
    profile = tmp_path / "agentlink-qualification-paid"
    with pytest.raises(QualificationRefused, match="explicitly free"):
        gate.qualify(profile, model=model)
    assert not profile.exists()


@pytest.mark.parametrize("failure", ["empty", "tool", "governance", "auth", "403", "policy", "nonzero"])
def test_routes_exhaust_or_refuse_real_failures_without_hiding_them(tmp_path, monkeypatch, failure):
    from tools.real_app_check import agentlink_release as gate
    from nodelang import model_router
    monkeypatch.setattr(model_router, "discover_key", lambda _: ("fixture-key", "fixture"))
    if failure == 'empty':
        output = ''
    elif failure in {'tool', 'governance'}:
        output = json.dumps({'type':'tool_use', 'part':{'tool':'write' if failure == 'tool' else 'native_work_task_detach',
            'state':{'status':'error', 'error':'write failed' if failure == 'tool' else 'ArchHub OpenCode governance: No Work task surface is attached'}}})
    else:
        output = json.dumps({'type':'error', 'error':{'message':{'auth':'401 invalid API key', '403':'403 forbidden',
            'policy':'403 content policy', 'nonzero':'unclassified process error'}[failure]}})
    program = "import pathlib,sys;\nwith pathlib.Path(sys.argv[1]).open('a') as f: f.write(sys.argv[-1]+'\\n')\nprint(sys.argv[2])\nraise SystemExit(9 if sys.argv[3]=='nonzero' else 0)"
    command = [sys.executable, '-c', program, str(tmp_path/'CALLS.txt'), output, failure, '-m', 'opencode/mimo-v2.6-flash-free']
    with pytest.raises(QualificationRefused) as refused:
        gate._opencode_turn(command, model=command[-1], env=dict(os.environ), cwd=tmp_path,
            timeout=8, quota_log=tmp_path/'opencode.log')
    routes = refused.value.routes
    assert len(routes) == (3 if failure == 'empty' else 1)
    assert len((tmp_path/'CALLS.txt').read_text().splitlines()) == len(routes)
    assert all(row['reason'] != 'completed' for row in routes)


def test_no_route_combines_partial_tool_proofs(tmp_path, monkeypatch):
    from tools.real_app_check import agentlink_release as gate
    from nodelang import model_router
    monkeypatch.setattr(model_router, 'discover_key', lambda _: ('fixture-key', 'fixture'))
    program = "import json,sys\nm=sys.argv[-1]\nfor tool in (['write','read'] if m.startswith('opencode/') else ['write','glob']): print(json.dumps({'type':'tool_use','part':{'tool':tool,'state':{'status':'completed','output':'ok'}}}))"
    model = 'opencode/mimo-v2.6-flash-free'
    with pytest.raises(QualificationRefused, match='All explicitly free'):
        gate._opencode_turn([sys.executable, '-c', program, '-m', model], model=model, env=dict(os.environ),
            cwd=tmp_path, timeout=8, quota_log=tmp_path/'opencode.log')


def test_route_deadline_is_shared_and_exhausted_without_starting_another_child(tmp_path, monkeypatch):
    from tools.real_app_check import agentlink_release as gate
    now, calls = [100.0], []
    monkeypatch.setattr(gate.time, 'monotonic', lambda: now[0])
    def run(command, **options):
        calls.append(options['timeout'])
        now[0] += 301
        raise gate._FreeProviderFailure('provider timeout')
    monkeypatch.setattr(gate, '_run', run)
    model = 'opencode/mimo-v2.6-flash-free'
    with pytest.raises(QualificationRefused, match='deadline exhausted') as refused:
        gate._opencode_turn(['fixture', '-m', model], model=model, env={}, cwd=tmp_path,
            timeout=300, quota_log=tmp_path/'opencode.log')
    assert calls == [120.0]
    assert len(refused.value.routes) == 1


def test_nonfree_fallback_refuses_before_any_child(tmp_path, monkeypatch):
    from tools.real_app_check import agentlink_release as gate
    monkeypatch.setattr(gate, '_FREE_FALLBACKS', ('openrouter/vendor/paid',))
    monkeypatch.setattr(gate, '_run', lambda *_args, **_kw: pytest.fail('paid route must never start a child'))
    with pytest.raises(QualificationRefused, match='explicitly free'):
        gate._opencode_turn(['fixture','-m','opencode/mimo-v2.6-flash-free'], model='opencode/mimo-v2.6-flash-free',
            env={}, cwd=tmp_path, timeout=8, quota_log=tmp_path/'opencode.log')


def test_attempted_sequence_without_completed_receipts_is_terminal(tmp_path, monkeypatch):
    from tools.real_app_check import agentlink_release as gate
    calls = []
    def run(command, **_options):
        calls.append(command)
        return '\n'.join(json.dumps({'type':'tool_use','part':{'tool':tool,
            'state':{'status':'running'}}}) for tool in ['write','read','write','glob'])
    monkeypatch.setattr(gate, '_run', run)
    with pytest.raises(QualificationRefused, match='lack completed proof'):
        gate._opencode_turn(['fixture','-m','opencode/mimo-v2.6-flash-free'], model='opencode/mimo-v2.6-flash-free',
            env={}, cwd=tmp_path, timeout=8, quota_log=tmp_path/'opencode.log')
    assert len(calls) == 1


def test_credential_lookup_consumes_the_original_deadline(tmp_path, monkeypatch):
    from tools.real_app_check import agentlink_release as gate
    from nodelang import model_router
    now = [0.0]
    monkeypatch.setattr(gate.time, 'monotonic', lambda: now[0])
    def key(_provider):
        now[0] = 301.0
        return 'fixture-key', 'fixture'
    monkeypatch.setattr(model_router, 'discover_key', key)
    monkeypatch.setattr(gate, '_run', lambda *_args, **_kw: pytest.fail('deadline expired before child start'))
    model = 'openrouter/thinkingmachines/inkling:free'
    with pytest.raises(QualificationRefused, match='deadline exhausted'):
        gate._opencode_turn(['fixture','-m',model], model=model, env={}, cwd=tmp_path,
            timeout=300, quota_log=tmp_path/'opencode.log')


def test_retry_nonce_cannot_borrow_previous_attempt_file_proof(tmp_path, monkeypatch):
    from tools.real_app_check import agentlink_release as gate
    from nodelang import model_router
    monkeypatch.setattr(model_router, 'discover_key', lambda _: ('fixture-key', 'fixture'))
    calls = []
    def run(command, **_options):
        calls.append(command)
        if len(calls) == 1:
            (tmp_path/'a.txt').write_text(command[-1])
            return json.dumps({'type':'text','part':{'text':'did not attempt sequence'}})
        return '\n'.join(json.dumps({'type':'tool_use','part':{'tool':tool,
            'state':{'status':'completed','output':'ok'}}}) for tool in ['write','read','write','glob'])
    monkeypatch.setattr(gate, '_run', run)
    nonce = 'original-nonce'
    _output, _model, routes = gate._opencode_turn(['fixture','-m','opencode/mimo-v2.6-flash-free',nonce],
        model='opencode/mimo-v2.6-flash-free', env={}, cwd=tmp_path, timeout=8,
        quota_log=tmp_path/'opencode.log', nonce=nonce)
    assert routes[0]['nonce'] == nonce
    assert routes[1]['nonce'] != nonce
    assert calls[1][-1] == routes[1]['nonce']
    assert (tmp_path/'a.txt').read_text() != routes[1]['nonce']


@pytest.mark.parametrize('collision', ['old', 'duplicate', 'borrowed'])
def test_quota_fallback_binds_exactly_one_new_authenticated_declaration(tmp_path, monkeypatch, collision):
    import inspect
    from tools.real_app_check import agentlink_release as gate
    primary = 'opencode/mimo-v2.6-flash-free'
    page = {'declarations': [], 'messages': []}
    def read_page():
        return {key: list(rows) for key, rows in page.items()}
    def run(command, **_options):
        declaration = {'native_session_id':'ses_same', 'app':'opencode', 'agent':'OpenCode',
            'session':'attempt-'+str(len(page['declarations'])), 'root':'root-'+str(len(page['declarations']))}
        if not page['declarations']:
            page['declarations'].append(declaration)
            raise gate._FreeProviderFailure('free quota exhausted')
        if collision != 'borrowed':
            page['declarations'].append(declaration)
        if collision == 'duplicate':
            page['declarations'].append({**declaration, 'root':'duplicate'})
        nonce = command[-1]
        author = declaration['agent']+' ['+declaration['session']+']'
        page['messages'].append({'id':'request', 'author':author, 'content':'AGENTLINK-REQUEST '+nonce})
        results = [('archhub_agent_coordination_declare', json.dumps({'declaration':declaration,
            'sender_key':declaration['session']}))] if collision != 'borrowed' else []
        if collision == 'duplicate':
            results.append(('archhub_agent_coordination_declare', json.dumps({
                'declaration':{**declaration, 'root':'duplicate'}, 'sender_key':declaration['session']})))
        results.extend((tool, 'ok') for tool in ['write','read','write','glob'])
        return '\n'.join(json.dumps({'type':'tool_use', 'sessionID':'ses_same', 'part':{'tool':tool,
            'state':{'status':'completed', 'output':result}}}) for tool, result in results)
    monkeypatch.setattr(gate, '_run', run)
    arguments = dict(model=primary, env={'OPENROUTER_API_KEY':'fixture-key'}, cwd=tmp_path,
        timeout=300, quota_log=tmp_path/'log', nonce='nonce', declaration_page=read_page)
    if 'declaration_page' not in inspect.signature(gate._opencode_turn).parameters:
        del arguments['declaration_page']
    if collision != 'old':
        with pytest.raises(QualificationRefused, match='unique authenticated declaration'):
            gate._opencode_turn(['fixture','-m',primary,'nonce'], **arguments)
        return
    output, model, routes = gate._opencode_turn(['fixture','-m',primary,'nonce'], **arguments)
    if 'declaration' not in routes[-1]:
        gate._request_proof(page, 'ses_same', routes[-1]['nonce'])
    assert output and model == gate._FREE_FALLBACKS[0]
    assert routes[-1]['declaration'] == 'root-1'
    assert [route['reason'] for route in routes] == ['free quota exhausted','completed']
    with pytest.raises(QualificationRefused, match='unique authenticated declaration'):
        gate._request_proof(page, 'ses_same', routes[-1]['nonce'])
    selected = {**page, 'declarations':[row for row in page['declarations'] if row['root'] == routes[-1]['declaration']]}
    declaration, message = gate._request_proof(selected, 'ses_same', routes[-1]['nonce'])
    assert declaration['root'] == 'root-1' and message['id'] == 'request'


def test_quota_fallback_accepts_real_mailbox_same_root_redeclaration(tmp_path, monkeypatch):
    import sqlite3
    from nodelang.conversation_history import ConversationHistoryStore
    from nodelang import workshop_mailbox
    from tools.real_app_check import agentlink_release as gate
    context = {'ai.opencode/sessionID':'ses_same'}
    database = tmp_path/'MAIL.sqlite3'
    connection = sqlite3.connect(database, isolation_level=None)
    with ConversationHistoryStore(database, instance_id='route-court', connection=connection) as history:
        history.ensure_conversation('app:workshop')
        def call(method, body):
            return workshop_mailbox.call(method, body, context, history=history)
        def page():
            return call('read', {'since':0, 'include_archived':True})
        roots = []
        def run(command, **_options):
            receipt = call('declare', {'task':'Release proof', 'paths':[str(tmp_path)],
                'status':'working', 'request_id':'AGENTLINK-RELEASE'})
            roots.append(receipt['declaration']['root'])
            if len(roots) == 1:
                raise gate._FreeProviderFailure('free quota exhausted')
            call('send', {'to':'Goose', 'text':'AGENTLINK-REQUEST '+command[-1]})
            results = [('archhub_agent_coordination_declare', json.dumps(receipt))]
            results.extend((tool,'ok') for tool in ['write','read','write','glob'])
            return '\n'.join(json.dumps({'type':'tool_use','sessionID':'ses_same', 'part':{
                'tool':tool,'state':{'status':'completed','output':result}}}) for tool,result in results)
        monkeypatch.setattr(gate, '_run', run)
        output, selected, routes = gate._opencode_turn(['fixture','-m','opencode/mimo-v2.6-flash-free','nonce'],
            model='opencode/mimo-v2.6-flash-free', env={'OPENROUTER_API_KEY':'fixture-key'}, cwd=tmp_path,
            timeout=300, quota_log=tmp_path/'log', nonce='nonce', declaration_page=page)
        assert roots[0] == roots[1] == routes[-1]['declaration']
        assert len(page()['declarations']) == 1
        assert selected == gate._FREE_FALLBACKS[0]
        gate._request_proof(page(), 'ses_same', routes[-1]['nonce'], output=output)
    connection.close()


@pytest.mark.parametrize('failure', ['none', 'missing', 'sender', 'foreign', 'duplicate', 'session'])
def test_selected_declare_receipt_binds_metadata_absent_connector(failure):
    from tools.real_app_check import agentlink_release as gate
    declaration = {'root':'connector-root', 'session':'observed-connector',
        'native_session_id':None, 'agent':'OpenCode', 'app':'opencode'}
    receipt = {'declaration':dict(declaration), 'sender_key':declaration['session']}
    if failure == 'sender':
        receipt['sender_key'] = 'foreign-sender'
    if failure == 'foreign':
        receipt['declaration']['root'] = 'foreign-root'
    if failure == 'session':
        declaration['native_session_id'] = 'ses_foreign'
    output = json.dumps({'type':'tool_use','sessionID':'ses_current','part':{
        'tool':'archhub_agent_coordination_declare','state':{'status':'completed', 'output':json.dumps(receipt)}}})
    page = {'declarations':[declaration], 'messages':[{'id':'fresh','author':'OpenCode [observed-connector]',
        'content':'AGENTLINK-REQUEST fresh-nonce'}]}
    if failure == 'missing':
        output = ''
    if failure == 'duplicate':
        page['declarations'].append(dict(declaration))
    if failure == 'none':
        assert gate._request_proof(page, 'ses_current', 'fresh-nonce', output=output)[1]['id'] == 'fresh'
        with pytest.raises(QualificationRefused, match='publish its nonce'):
            gate._request_proof(page, 'ses_current', 'old-nonce', output=output)
    else:
        with pytest.raises(QualificationRefused, match='unique authenticated declaration'):
            gate._request_proof(page, 'ses_current', 'fresh-nonce', output=output)


def test_selected_session_requires_its_own_request_and_exact_overlap_pair():
    from tools.real_app_check import agentlink_release as gate
    def declaration(session, app):
        return {'native_session_id':session,'app':app,'agent':app,'session':session,'root':session+'-root'}
    failed, selected, peer = declaration('old','opencode'), declaration('selected','opencode'), declaration('peer','goose')
    old_request = {'id':'old-request','author':'opencode [old]','content':'AGENTLINK-REQUEST old-nonce'}
    request = {'id':'request','author':'opencode [selected]','content':'AGENTLINK-REQUEST new-nonce'}
    old_notice = {'id':'old-overlap','author':'Workshop coordination','content':'Your work overlaps at fixture',
        'refs':[failed['root'],peer['root']]}
    notice = {**old_notice,'id':'overlap','refs':[selected['root'],peer['root']]}
    reply = {'author':'goose [peer]'}
    page = {'declarations':[failed,selected,peer], 'messages':[old_request,request,old_notice,notice]}
    assert gate._request_proof(page,'selected','new-nonce') == (selected,request)
    assert gate._overlap_proof(page,selected,reply,'goose') == notice
    with pytest.raises(QualificationRefused, match='publish its nonce'):
        gate._request_proof({**page,'messages':[old_request]},'selected','old-nonce')
    with pytest.raises(QualificationRefused, match='paired reply and overlap'):
        gate._overlap_proof({**page,'messages':[old_notice]},selected,reply,'goose')
    with pytest.raises(QualificationRefused, match='publish its nonce'):
        gate._request_proof({**page,'messages':[request,request]},'selected','new-nonce')


@pytest.mark.parametrize('channel', ['json','log','mixed'])
def test_terminal_error_wins_over_retryable_error_in_the_same_attempt(tmp_path, channel):
    from tools.real_app_check import agentlink_release as gate
    model = 'opencode/mimo-v2.6-flash-free'
    log = tmp_path/'opencode.log'
    errors = ['429 Too Many Requests','401 invalid API key']
    if channel == 'json':
        output = '\n'.join(json.dumps({'type':'error','error':{'message':message}}) for message in errors)
        program = "import sys;print(sys.argv[1])"
    elif channel == 'log':
        output = '\n'.join('message="stream error" providerID=opencode modelID=mimo-v2.6-flash-free small=false '+message for message in errors)
        program = "import pathlib,sys;pathlib.Path(sys.argv[2]).write_text(sys.argv[1])"
    else:
        output = json.dumps({'type':'error','error':{'message':errors[0]}})
        program = "import pathlib,sys;pathlib.Path(sys.argv[2]).write_text('message=\"stream error\" providerID=opencode modelID=mimo-v2.6-flash-free small=false 401 invalid API key');print(sys.argv[1])"
    with pytest.raises(QualificationRefused, match='unclassified') as refused:
        gate._opencode_turn([sys.executable,'-c',program,output,str(log),'-m',model], model=model,
            env=dict(os.environ), cwd=tmp_path, timeout=8, quota_log=log)
    assert len(refused.value.routes) == 1


def test_running_tool_timeout_is_a_product_refusal(tmp_path):
    from tools.real_app_check import agentlink_release as gate
    model = 'opencode/mimo-v2.6-flash-free'
    event = json.dumps({'type':'tool_use','part':{'tool':'write','state':{'status':'running'}}})
    program = "import sys,time;print(sys.argv[1],flush=True);time.sleep(20)"
    with pytest.raises(QualificationRefused, match='tool timed out') as refused:
        gate._opencode_turn([sys.executable,'-c',program,event,'-m',model], model=model,
            env=dict(os.environ), cwd=tmp_path, timeout=8, quota_log=tmp_path/'opencode.log')
    assert len(refused.value.routes) == 1


def test_quota_cannot_hide_a_buffered_real_tool_failure(tmp_path):
    from tools.real_app_check import agentlink_release as gate
    model = 'opencode/mimo-v2.6-flash-free'
    event = json.dumps({'type':'tool_use','part':{'tool':'write','state':{'status':'error','error':'real write failure'}}})
    log = tmp_path/'opencode.log'
    program = "import pathlib,sys,time;print(sys.argv[1],flush=True);pathlib.Path(sys.argv[2]).write_text('message=\"stream error\" providerID=opencode modelID=mimo-v2.6-flash-free small=false Free usage limit reached');time.sleep(20)"
    with pytest.raises(QualificationRefused,match='tool failed') as refused:
        gate._opencode_turn([sys.executable,'-c',program,event,str(log),'-m',model], model=model,
            env=dict(os.environ), cwd=tmp_path, timeout=8, quota_log=log)
    assert len(refused.value.routes) == 1


@pytest.mark.parametrize('settles', [True,False])
def test_retry_cancels_only_its_isolated_server_and_requires_settlement(settles):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading
    import time
    from tools.real_app_check import agentlink_release as gate
    calls, busy = [], [True]
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(('GET',self.path))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({'ses_fixture':{'type':'busy' if busy[0] else 'idle'}}).encode())
        def do_POST(self):
            calls.append(('POST',self.path))
            busy[0] = not settles
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'true')
        def log_message(self,*_args):
            pass
    server = HTTPServer(('127.0.0.1',0),Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        command = ['fixture','--attach','http://127.0.0.1:'+str(server.server_port)]
        if settles:
            gate._stop_opencode_turn(command,time.monotonic()+5)
        else:
            with pytest.raises(QualificationRefused,match='still running'):
                gate._stop_opencode_turn(command,time.monotonic()+5)
        assert calls == [('GET','/session/status'),('POST','/session/ses_fixture/abort'),('GET','/session/status')]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_cancellation_deadline_bounds_the_whole_slow_http_body():
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading
    import time
    from tools.real_app_check import agentlink_release as gate
    release = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{')
            self.wfile.flush()
            release.wait(5)
            try:
                self.wfile.write(b'}')
            except OSError:
                pass
        def log_message(self,*_args):
            pass
    server = HTTPServer(('127.0.0.1',0),Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    started = time.monotonic()
    try:
        with pytest.raises(QualificationRefused,match='cancellation could not be verified'):
            gate._stop_opencode_turn(['fixture','--attach','http://127.0.0.1:'+str(server.server_port)],started+0.5)
        assert time.monotonic()-started < 3
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_quota_exhaustion_uses_one_free_route_through_the_same_cli(tmp_path, monkeypatch):
    from tools.real_app_check import agentlink_release as gate
    from nodelang import model_router
    log = tmp_path / "opencode.log"
    stub = tmp_path / "PROVIDER.py"
    stub.write_text("import pathlib,sys,time\n"
        "model=sys.argv[sys.argv.index('-m')+1]\n"
        "with pathlib.Path(sys.argv[1]).with_name('CALLS.txt').open('a') as calls: calls.write(model+'\\n')\n"
        "if model.startswith('opencode/'):\n"
        " pathlib.Path(sys.argv[1]).write_text('message=\"stream error\" providerID=opencode modelID=mimo-v2.6-flash-free small=false error=\"Free usage limit reached\"\\n')\n"
        " time.sleep(12)\n"
        "else:\n"
        " import os\n"
        " assert os.environ['OPENROUTER_API_KEY']=='fixture-key'\n"
        " import json\n"
        " for tool in ['write','read','write','glob']: print(json.dumps({'type':'tool_use','part':{'tool':tool,'state':{'status':'completed','output':'REAL_ROUTE_OUTPUT'}}}))\n", encoding="utf-8")
    monkeypatch.setattr(model_router, "discover_key", lambda _: ("fixture-key", "fixture"))
    env = dict(os.environ)
    # Replay the original direct _run call when exercising the pre-fix source.
    turn = getattr(gate, "_opencode_turn", lambda command, model, quota_log, **options: (gate._run(command, **options), model))
    output, selected, routes = turn([sys.executable, str(stub), str(log), "-m", "opencode/mimo-v2.6-flash-free"],
        model="opencode/mimo-v2.6-flash-free", env=env, cwd=tmp_path, timeout=8, quota_log=log)
    assert gate.write_sequence(output)
    assert "REAL_ROUTE_OUTPUT" in output
    assert [row['reason'] for row in routes] == ['free quota exhausted', 'completed']
    assert selected == "openrouter/thinkingmachines/inkling:free"
    assert (tmp_path / "CALLS.txt").read_text().splitlines() == ["opencode/mimo-v2.6-flash-free", selected]
    assert not any(path.name == "auth.json" for path in tmp_path.rglob("*"))
    for failed in ("exchange", "overlap", "opencode"):
        with pytest.raises(QualificationRefused):
            require_checks({"exchange":True, "overlap":True, "opencode":True, failed:False})


@pytest.mark.parametrize("line", [
    'providerID=opencode modelID=other-free small=false Free usage limit reached',
    'providerID=opencode modelID=mimo-v2.6-flash-free small=true Free usage limit reached',
    'providerID=opencode modelID=mimo-v2.6-flash-free small=false unrelated failure'])
def test_unrelated_or_stale_quota_does_not_switch_route(tmp_path, line):
    from tools.real_app_check import agentlink_release as gate
    log = tmp_path / "opencode.log"
    log.write_text('message="stream error" providerID=opencode modelID=mimo-v2.6-flash-free small=false Free usage limit reached\n')
    line = 'message="stream error" ' + line
    command = [sys.executable, "-c", "import pathlib,sys;pathlib.Path(sys.argv[1]).open('a').write(sys.argv[2]);raise SystemExit(9)",
        str(log), line, "-m", "opencode/mimo-v2.6-flash-free"]
    with pytest.raises(QualificationRefused, match="nonzero exit 9"):
        gate._opencode_turn(command, model="opencode/mimo-v2.6-flash-free", env=dict(os.environ),
            cwd=tmp_path, timeout=8, quota_log=log)


def test_explicit_free_openrouter_uses_existing_key_and_no_fallback(tmp_path, monkeypatch):
    from tools.real_app_check import agentlink_release as gate
    from nodelang import model_router
    monkeypatch.setattr(model_router, "discover_key", lambda _: ("fixture-key", "fixture"))
    model = "openrouter/thinkingmachines/inkling:free"
    program = "import json,os;assert os.environ['OPENROUTER_API_KEY']=='fixture-key';\nfor tool in ['write','read','write','glob']: print(json.dumps({'type':'tool_use','part':{'tool':tool,'state':{'status':'completed','output':'free'}}}))"
    command = [sys.executable, "-c", program, "-m", model]
    output, selected, routes = gate._opencode_turn(command, model=model, env=dict(os.environ), cwd=tmp_path,
        timeout=8, quota_log=tmp_path / "absent.log")
    assert gate.write_sequence(output)
    assert selected == model
    assert [row['model'] for row in routes] == [model]


@pytest.mark.parametrize("title", ["thinkingmachines/inkling:free", "google/gemini-nano-banana-2.1"])
def test_actual_stream_log_rejects_implicit_nonfree_title_model(title):
    from tools.real_app_check import agentlink_release as gate
    model = "openrouter/thinkingmachines/inkling:free"
    streams = ('message=stream providerID=openrouter modelID=thinkingmachines/inkling:free small=false\n'
        'message=stream providerID=openrouter modelID=' + title + ' small=true\n')
    if title.endswith(":free"):
        assert gate._free_stream_models(streams, model) == [model]
    else:
        with pytest.raises(QualificationRefused, match="explicitly free"):
            gate._free_stream_models(streams, model)
    with pytest.raises(QualificationRefused, match="no isolated server stream evidence"):
        gate._free_stream_models("", model)


@pytest.mark.parametrize("failed", ["exchange", "overlap", "opencode", "connector"])
def test_each_required_scenario_refuses_in_a_real_gate_process(failed):
    program = ("from tools.real_app_check.agentlink_release import require_checks; "
        "require_checks({'exchange':True,'overlap':True,'opencode':True,'connector':True," + repr(failed) + ":False})")
    result = subprocess.run([sys.executable, "-c", program],
        cwd=Path(__file__).resolve().parents[2] / "03.TOOLS", capture_output=True, encoding="utf-8",
        env={**os.environ, "PYTHONDONTWRITEBYTECODE":"1"},
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode != 0
    assert "AGENTLINK release refused: " + failed in result.stderr


def test_missing_or_unknown_state_never_becomes_pass():
    with pytest.raises(QualificationRefused):
        require_checks({"exchange":True,"overlap":True})
    with pytest.raises(QualificationRefused):
        require_checks({"exchange":True,"overlap":True,"opencode":"skipped"})
    with pytest.raises(QualificationRefused, match="connector"):
        require_checks({"exchange":True,"overlap":True,"opencode":True})
    require_checks({"exchange":True,"overlap":True,"opencode":True,"connector":True})


def test_connector_release_court_runs_real_stdio_with_workshop_hung_down_and_up(tmp_path):
    from tools.real_app_check.agentlink_release import qualify_connector
    profile = tmp_path / "CONNECTOR"
    result = qualify_connector(profile)
    assert result["status"] == "isolated-pass"
    assert result["declarations_arrived"]
    assert {row["workshop"] for row in result["cases"]} == {"hung", "down", "up"}
    assert all(row["initialize_seconds"] <= 5 and
               row["host_seconds"] <= row["broker_seconds"] + 1 for row in result["cases"])
    for case in result["cases"]:
        assert sorted(item["tool"] for item in case["tools"]) == case["registered_tools"]
        assert {"send", "read", "declare", "native.hook_stop", "native.hook_user_prompt_submit"} <= set(case["registered_tools"])
        assert all(item["seconds"] <= item["work_seconds"] + 1 for item in case["tools"])
    assert not profile.exists()


def test_echoed_ids_are_not_tool_read_receipts():
    import json
    from tools.real_app_check.agentlink_release import read_messages, write_sequence
    message = {"id":"overlap-proof", "refs":["one", "two"]}
    echoed = json.dumps({"type":"text","part":{"text":json.dumps({"messages":[message]})}})
    assert read_messages(echoed) == []
    result = json.dumps({"type":"tool_use", "part":{"tool":"archhub_agent_coordination_read",
        "state":{"status":"completed","output":json.dumps({"messages":[message]})}}})
    assert read_messages(result) == [message]
    good = "\n".join(json.dumps({"type":"tool_use","part":{"tool":tool,
        "state":{"status":"completed","output":"ok"}}}) for tool in ["write","read","write","glob"])
    assert write_sequence(good)
    assert not write_sequence(good.replace('"status": "completed"','"status": "error"',1))


def test_goose_only_auto_allows_the_shared_mailbox_boundary():
    from nodelang.goose_adapter import safe_workshop_call
    def identity(tool):
        return {"extensionName":"archhub-agent", "toolName":"archhub-agent__"+tool}
    assert safe_workshop_call(identity("read"), {"since":0})
    assert safe_workshop_call(identity("declare"), {"task":"Check fixture","paths":["fixture"],"status":"working","request_id":"proof"})
    assert safe_workshop_call(identity("send"), {"to":"OpenCode","text":"proof","reply_to":"root"})
    assert safe_workshop_call(identity("send"), {"to":"OpenCode","text":"proof","reply_to":"root","idempotency_key":"stable-reply"})
    assert not safe_workshop_call(identity("send"), {"to":"OpenCode","text":"proof","sender":"forged"})
    assert not safe_workshop_call(identity("office_execute"), {"code":"unsafe"})
    assert not safe_workshop_call({"extensionName":"other","toolName":"archhub-agent__read"}, {})


@pytest.mark.parametrize("peer", ["claude", "goose"])
@pytest.mark.parametrize("failure_stage", ["construct", "start"])
def test_qualification_server_and_native_mailbox_select_one_profile(tmp_path, monkeypatch, peer, failure_stage):
    from tools.real_app_check import agentlink_release as gate
    from nodelang import application_server, cell_secret_keys, model_router, workshop_mailbox
    from nodelang.persistence import application_database_path

    profile = tmp_path / "agentlink-qualification-profile"
    native_gate = tmp_path / "native_gate.py"
    native_gate.touch()
    monkeypatch.setattr(gate, "_executable", lambda *_: sys.executable)
    monkeypatch.setattr(gate, "_claude_auth", lambda *_: None)
    monkeypatch.setattr(model_router, "discover_key", lambda *_: ("fixture-credential", "fixture"))
    monkeypatch.setattr(gate, "source_digest", lambda *_: "source-fixture")
    monkeypatch.setattr(gate.shutil, "copytree", lambda *_args, **_kwargs: None)

    class Keys:
        def __init__(self, *_):
            pass
        def current(self, *_):
            pass

    class SelectedProfileChecked(Exception):
        pass

    class PartialServer:
        def __init__(self):
            import sqlite3
            self.connection = sqlite3.connect(application_database_path(profile))
            self.connection.execute("CREATE TABLE fixture(value)")
        def start(self):
            raise SelectedProfileChecked
        def close(self):
            self.connection.close()

    def server(**options):
        assert os.environ["OPENROUTER_API_KEY"] == "fixture-credential"
        assert json.loads(os.environ["OPENCODE_CONFIG_CONTENT"])["small_model"] == "opencode/mimo-v2.6-flash-free"
        if peer == "goose":
            assert json.loads(os.environ["OPENROUTER_PARAMETERS"]) == {"max_tokens":4096}
            assert os.environ["GOOSE_MODEL"] == gate._GOOSE_MODEL
        assert Path(options["machine_descriptor_path"]).parent == Path(os.environ["LOCALAPPDATA"]) / "ArchHub"
        selected = options["universal_state_path"]
        assert selected == application_database_path(profile)
        assert selected == workshop_mailbox.profile_database()
        if failure_stage == "construct":
            raise SelectedProfileChecked
        return PartialServer()

    monkeypatch.setattr(cell_secret_keys, "WindowsDpapiSigningKeyProvider", Keys)
    monkeypatch.setattr(application_server, "ApplicationServer", server)
    with pytest.raises(SelectedProfileChecked):
        gate.qualify(profile, native_gate=native_gate, peer=peer)
    assert not profile.exists()


@pytest.mark.parametrize("refused", ["compiler", "agentlink"])
def test_actual_installer_refuses_before_creating_output(tmp_path, refused):
    product = tmp_path / "01.WIP" / "PRODUCT"
    (product / "installer").mkdir(parents=True)
    (product / "tools" / "pipeline").mkdir(parents=True)
    (product / "tools" / "real_app_check").mkdir()
    root = Path(__file__).resolve().parents[2]
    shutil.copyfile(root / "03.TOOLS/installer/build_release.ps1", product / "installer/build_release.ps1")
    (product / "tools/__init__.py").touch()
    (product / "tools/real_app_check/__init__.py").touch()
    (product / "tools/pipeline/build.py").write_text(
        "print('COMPILER_REACHED',flush=True)\nraise SystemExit(" + ("23" if refused == "compiler" else "0") + ")\n")
    (product / "tools/real_app_check/agentlink_release.py").write_text(
        "print('AGENTLINK_REACHED',flush=True)\nraise SystemExit(24)\n")
    env = {**os.environ, "GIT_CONFIG_GLOBAL":os.devnull, "PYTHONPATH":str(product)}
    for args in (["init", "--quiet"], ["add", "."],
                 ["-c", "user.name=Gate fixture", "-c", "user.email=gate@example.invalid",
                  "commit", "--quiet", "-m", "Fixture"]):
        subprocess.run(["git", "-c", "core.longpaths=true", *args],
                       cwd=product, env=env, check=True, capture_output=True)
    archive = tmp_path / "GOOSE.zip"
    archive.touch()
    output = tmp_path / "OUTPUT"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-File",
        str(product / "installer/build_release.ps1"), "-BuildId", "candidate-FIXTURE",
        "-OutputDirectory", str(output), "-GooseArchivePath", str(archive), "-PythonPath", sys.executable],
        cwd=product, env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=30)
    assert result.returncode != 0
    assert "COMPILER_REACHED" in result.stdout
    assert ("AGENTLINK_REACHED" in result.stdout) == (refused == "agentlink")
    assert ("ACOMPILER refused release build" if refused == "compiler" else "AGENTLINK refused release") in result.stderr
    assert not output.exists()


def test_installer_includes_the_required_stylesheet_without_allowing_arbitrary_assets(tmp_path):
    script = tmp_path / "CHECK.ps1"
    script.write_text(r'''
param([string]$Build)
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Build,[ref]$tokens,[ref]$errors)
$function=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Test-CandidateInput'},$true)
Invoke-Expression $function.Extent.Text
$acompilerInputs=@()
@('nodelang/studio/style.css','nodelang/studio/other.css','nodelang/credentials.json','nodelang/.env') | ForEach-Object { Test-CandidateInput 'selected' $_ } | ConvertTo-Json -Compress
''', encoding="utf-8")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-File", str(script), "-Build",
        str(Path(__file__).resolve().parents[2] / "03.TOOLS/installer/build_release.ps1")],
        capture_output=True, encoding="utf-8", errors="replace", timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [True, False, False, False]


@pytest.mark.parametrize("version", ["1.18.34", "1.18.21"])
def test_isolated_opencode_dependencies_complete_before_bootstrap(tmp_path, monkeypatch, version):
    from tools.real_app_check import agentlink_release as gate
    env = gate.isolated_environment(tmp_path)
    env["OPENCODE_CONFIG_DIR"] = str(tmp_path / "opencode")
    monkeypatch.setattr(gate.shutil, "which", lambda *_args, **_kwargs: "npm-fixture")
    calls = []
    def run(command, **options):
        calls.append((command, options))
        if command[-1] == "--version":
            return version + "\n"
        config = options["cwd"]
        assert config == tmp_path / "opencode"
        assert json.loads((config / "package.json").read_text())["dependencies"] == {"@opencode-ai/plugin":version}
        assert options["env"] is env
        assert options["timeout"] == 90
        assert "--ignore-scripts" in command
        assert "--fetch-retries=0" in command
        return "installed"
    monkeypatch.setattr(gate, "_run", run)
    gate._prepare_opencode_dependencies("opencode-fixture", env=env, cwd=tmp_path)
    assert len(calls) == 2


@pytest.mark.parametrize("failure", ["version", "npm", "install"])
def test_dependency_preparation_failure_never_reaches_bootstrap(tmp_path, monkeypatch, failure):
    from tools.real_app_check import agentlink_release as gate
    env = gate.isolated_environment(tmp_path)
    env["OPENCODE_CONFIG_DIR"] = str(tmp_path / "opencode")
    monkeypatch.setattr(gate.shutil, "which", lambda *_args, **_kwargs: None if failure == "npm" else "npm-fixture")
    def run(command, **_options):
        if command[-1] == "--version":
            return "untrusted-version" if failure == "version" else "1.18.34\n"
        raise gate.QualificationRefused("dependency install failed")
    monkeypatch.setattr(gate, "_run", run)
    with pytest.raises(gate.QualificationRefused):
        gate._prepare_opencode_dependencies("opencode-fixture", env=env, cwd=tmp_path)


@pytest.fixture
def plugin_cache(tmp_path):
    """Real npm content-addressed cache, including a transitive dependency."""
    import base64
    import hashlib
    import io
    import tarfile
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        pytest.fail("npm is required for the dependency restoration court")
    npm_root = Path(npm).resolve().parent / "node_modules/npm"
    cache = tmp_path / "CACHE" / "_cacache"
    seed = []
    for name, version, dependencies in [("@opencode-ai/plugin", "1.18.34", {"fixture-dependency":"1.0.0", "fixture-optional":"2.0.0"}),
                                        ("fixture-dependency", "1.0.0", {})]:
        manifest = {"name":name, "version":version, "dependencies":dependencies}
        if name == "@opencode-ai/plugin":
            manifest["optionalDependencies"] = {"fixture-optional":"1.0.0"}
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w:gz") as archive:
            for filename, content in [("package.json", json.dumps(manifest).encode()), ("index.js", b"export const proof = true;\n")]:
                info = tarfile.TarInfo("package/" + filename)
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
        blob = data.getvalue()
        manifest["dist"] = {"integrity":"sha512-" + base64.b64encode(hashlib.sha512(blob).digest()).decode()}
        seed.append({"key":"make-fetch-happen:request-cache:https://registry.npmjs.org/" + name.replace("/", "%2f"),
                     "metadata":json.dumps({"versions":{version:manifest}}), "blob":base64.b64encode(blob).decode()})
    seed_file = tmp_path / "SEED.json"
    seed_file.write_text(json.dumps(seed), encoding="utf-8")
    program = "const fs=require('fs'),c=require(process.argv[1]+'/node_modules/cacache');(async()=>{for(const r of JSON.parse(fs.readFileSync(process.argv[3]))){await c.put(process.argv[2],r.key,r.metadata);await c.put(process.argv[2],'tar:'+r.key,Buffer.from(r.blob,'base64'));}})().catch(e=>{console.error(e);process.exitCode=1})"
    subprocess.run([shutil.which("node"), "-e", program, str(npm_root), str(cache), str(seed_file)], check=True, timeout=30)
    return cache, npm_root


def test_local_plugin_cache_avoids_npm_deadline(tmp_path, monkeypatch, plugin_cache):
    from tools.real_app_check import agentlink_release as gate
    cache, _ = plugin_cache
    env = gate.isolated_environment(tmp_path / "PROFILE")
    env["OPENCODE_CONFIG_DIR"] = str(tmp_path / "PROFILE/opencode")
    monkeypatch.setenv("npm_config_cache", str(cache.parent))
    original_run = gate._run
    calls = []
    def run(command, **options):
        calls.append(command)
        if command[-1] == "--version":
            return "1.18.34\n"
        if "install" in command:
            return original_run([sys.executable, "-c", "import time; time.sleep(95)"], **options)
        return original_run(command, **options)
    monkeypatch.setattr(gate, "_run", run)
    gate._prepare_opencode_dependencies("opencode-fixture", env=env, cwd=tmp_path)
    assert not any("install" in command for command in calls)
    plugin = Path(env["OPENCODE_CONFIG_DIR"]) / "node_modules/@opencode-ai/plugin"
    assert json.loads((plugin / "package.json").read_text())["version"] == "1.18.34"
    assert (plugin / "node_modules/fixture-dependency/index.js").read_bytes() == b"export const proof = true;\n"
    assert not (plugin / "node_modules/fixture-optional").exists()
    lock = json.loads((Path(env["OPENCODE_CONFIG_DIR"]) / "package-lock.json").read_text())
    assert lock["packages"][""]["dependencies"] == {"@opencode-ai/plugin":"1.18.34"}


@pytest.mark.parametrize("scenario", ["absent", "wrong-version", "corrupt", "traversal", "symlink"])
def test_local_dependency_cache_never_accepts_unverified_bytes(tmp_path, plugin_cache, scenario):
    import base64
    import hashlib
    import io
    import tarfile
    cache, npm_root = plugin_cache
    seed_file = tmp_path / "SEED.json"
    rows = json.loads(seed_file.read_text())
    if scenario == "absent":
        cache = tmp_path / "ABSENT"
    elif scenario == "corrupt":
        digest = hashlib.sha512(base64.b64decode(rows[0]["blob"])).hexdigest()
        (cache / "content-v2/sha512" / digest[:2] / digest[2:4] / digest[4:]).write_bytes(b"corrupted")
    else:
        metadata = json.loads(rows[0]["metadata"])
        manifest = metadata["versions"]["1.18.34"]
        if scenario == "wrong-version":
            metadata["versions"] = {"1.18.21":{**manifest, "version":"1.18.21"}}
        else:
            blob = io.BytesIO()
            with tarfile.open(fileobj=blob, mode="w:gz") as archive:
                info = tarfile.TarInfo("package/../../ESCAPED" if scenario == "traversal" else "package/link")
                if scenario == "symlink":
                    info.type = tarfile.SYMTYPE
                    info.linkname = "../../ESCAPED"
                archive.addfile(info)
            data = blob.getvalue()
            manifest["dist"]["integrity"] = "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()
            rows[0]["blob"] = base64.b64encode(data).decode()
        rows[0]["metadata"] = json.dumps(metadata)
        seed_file.write_text(json.dumps(rows), encoding="utf-8")
        program = "const fs=require('fs'),c=require(process.argv[1]+'/node_modules/cacache');(async()=>{const r=JSON.parse(fs.readFileSync(process.argv[3]))[0];await c.put(process.argv[2],r.key,r.metadata);await c.put(process.argv[2],'tar:'+r.key,Buffer.from(r.blob,'base64'));})().catch(e=>{console.error(e);process.exitCode=1})"
        subprocess.run([shutil.which("node"), "-e", program, str(npm_root), str(cache), str(seed_file)], check=True, timeout=30)
    helper = Path(__file__).resolve().parents[2] / "03.TOOLS/tools/real_app_check/agentlink_dependencies.cjs"
    output = tmp_path / "RESTORED"
    result = subprocess.run([shutil.which("node"), str(helper), str(npm_root), str(cache), str(output), "1.18.34"],
        capture_output=True, text=True, timeout=30)
    if scenario in {"absent", "wrong-version"}:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "LOCAL_DEPENDENCIES_ABSENT"
        assert not output.exists()
    elif scenario == "corrupt":
        assert result.returncode != 0
        assert "LOCAL_DEPENDENCIES_VERIFIED" not in result.stdout
    else:
        from tools.real_app_check import agentlink_release as gate
        assert result.returncode == 0, result.stderr
        with pytest.raises(gate.QualificationRefused, match="Unsafe cached dependency"):
            gate._extract_opencode_dependencies(output, tmp_path / "PLUGIN", "1.18.34")
    assert not (tmp_path / "ESCAPED").exists()


@pytest.mark.parametrize("scenario", ["running", "stopped", "tamper", "measured-budget", "expired"])
def test_snapshot_budget_keeps_rehash_integrity_and_deadline(tmp_path, scenario):
    root = tmp_path / "SOURCE"
    root.mkdir()
    source = root / "fixture.py"
    source.write_bytes(b"trusted")
    env = {**os.environ, "GIT_CONFIG_GLOBAL":os.devnull}
    for args in (["init", "--quiet"], ["add", "."], ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--quiet", "-m", "Fixture"]):
        subprocess.run(["git", *args], cwd=root, env=env, check=True, capture_output=True)
    output = tmp_path / "OUTPUT/source/selected"
    output.mkdir(parents=True)
    (output / "fixture.py").write_bytes(b"altered" if scenario == "tamper" else b"trusted")
    script = tmp_path / "COURT.ps1"
    script.write_text(r'''
param([string]$Build,[string]$Root,[string]$Output,[string]$Scenario)
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Build,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Build parse errors'}
foreach($name in @('Assert-PlainAncestors','Get-SourceIdentity','Get-RepositoryPath','Assert-TrackedInputs','Assert-CandidateSources','Assert-CandidateBudget','Read-CandidateFile','Assert-BuildSnapshot')){
  $function=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
  Invoke-Expression $function.Extent.Text
}
$plainDirectories=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$repositoryAreas=@{}
$selectedInputs=@('fixture.py');$isCandidate=$false
$sourceRevision=(& git -C $Root rev-parse HEAD).Trim()
$source=Join-Path $Root 'fixture.py'
$sha=[Security.Cryptography.SHA256]::Create()
try{$digest=([BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($source)))).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
$row=[pscustomobject]@{Source='selected';Path='fixture.py';Bytes=7;Sha256=$digest;SourcePath=$source;Identity=(Get-SourceIdentity $source)}
$manifest=[pscustomobject]@{Rows=@($row);SelectedCheckout=$Root}
$candidateBuffer=[byte[]]::new(1MB)
# A delayed real read remains charged; the measured budget admits slow valid verification.
$candidateClock=[Diagnostics.Stopwatch]::StartNew()
if($Scenario -eq 'stopped'){$candidateClock.Stop()}
$originalRead=${function:Read-CandidateFile}
function Read-CandidateFile { param($Row,$Path,$Destination) Start-Sleep -Milliseconds 250; & $originalRead $Row $Path $Destination }
$start=$candidateClock.Elapsed.TotalSeconds
$wall=[Diagnostics.Stopwatch]::StartNew()
if($Scenario -in @('measured-budget','expired')){
  $seconds=if($Scenario -eq 'expired'){421}else{200}
  $candidateClock=[pscustomobject]@{Elapsed=[pscustomobject]@{TotalSeconds=$seconds};IsRunning=$true}
}
$failed=$false
try { Assert-BuildSnapshot $manifest } catch {
  $failed=$true
  if($Scenario -eq 'tamper' -and $_.Exception.Message -notlike '*Source content differs*'){throw}
  if($Scenario -eq 'expired' -and $_.Exception.Message -notlike '*exceeded*seconds*'){throw}
}
if($Scenario -in @('tamper','expired')){if(-not $failed){throw 'Required refusal missing'}}elseif($failed){throw 'Valid snapshot refused'}
if($Scenario -notin @('expired','measured-budget')){
  if($candidateClock.IsRunning -ne ($Scenario -ne 'stopped')){throw 'Stopwatch running state changed'}
  if($Scenario -ne 'stopped' -and ($candidateClock.Elapsed.TotalSeconds-$start) -lt 0.20){throw 'Rehash time escaped snapshot budget'}
}
Write-Output ('SNAPSHOT COURT PASS '+$Scenario)
''', encoding="utf-8")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-File", str(script), "-Build",
        os.environ.get("RELFLAKE_BUILD_SCRIPT", str(Path(__file__).resolve().parents[2] / "03.TOOLS/installer/build_release.ps1")),
        "-Root", str(root), "-Output", str(tmp_path / "OUTPUT"), "-Scenario", scenario],
        capture_output=True, encoding="utf-8", errors="replace", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SNAPSHOT COURT PASS " + scenario in result.stdout


@pytest.mark.parametrize('declared_before_refusal', [False, True])
@pytest.mark.parametrize('outer', ['codex', 'claude'])
def test_relroute_quota_fallback_binds_owned_server(tmp_path, monkeypatch, declared_before_refusal, outer):
    import sqlite3
    import psutil
    from nodelang.conversation_history import ConversationHistoryStore
    from nodelang.application_machine_transport import MachinePipePeer
    from nodelang import workshop_mailbox, agent_runtime_registry as registry
    from tools.real_app_check import agentlink_release as gate
    class Process:
        def __init__(self, pid): self.pid = pid
        def name(self): return {300:'python.exe', 200:'opencode.exe', 100:outer+'.exe'}[self.pid]
        def create_time(self): return float(self.pid)
        def cmdline(self):
            return {300:['python.exe','-m','nodelang.native_agent_mcp'],
                200:['C:/CLI/opencode.exe','serve','--port','12345'],
                100:[outer+'.exe','exec']}[self.pid]
        def parent(self): return Process(self.pid-100) if self.pid>100 else None
    monkeypatch.setattr(psutil, 'Process', Process)
    peer = MachinePipePeer(pid=300, created_at=300, cwd=str(tmp_path))
    database = tmp_path/'MAIL.sqlite3'
    connection = sqlite3.connect(database, isolation_level=None)
    with ConversationHistoryStore(database, instance_id='relroute', connection=connection) as history:
        history.ensure_conversation('app:workshop')
        def call(method, body):
            return workshop_mailbox.call(method, body, {}, peer=peer, history=history)
        calls, receipts = [], []
        def declare():
            receipt = call('declare', {'task':'Release proof', 'paths':[str(tmp_path)],
                'status':'working', 'request_id':'AGENTLINK-RELEASE'})
            receipts.append(receipt)
            return receipt
        def run(command, **_options):
            calls.append(command)
            if len(calls) == 1:
                if declared_before_refusal: declare()
                raise gate._FreeProviderFailure('free quota exhausted')
            receipt = declare()
            call('send', {'to':'Goose','text':'AGENTLINK-REQUEST '+command[-1]})
            results = [('archhub_agent_coordination_declare',json.dumps(receipt))]
            results.extend((tool,'ok') for tool in ['write','read','write','glob'])
            return '\n'.join(json.dumps({'type':'tool_use','sessionID':'ses_selected','part':{
                'tool':tool,'state':{'status':'completed','output':result}}}) for tool,result in results)
        monkeypatch.setattr(gate, '_run', run)
        primary = 'opencode/mimo-v2.6-flash-free'
        page = lambda: call('read', {'since':0,'include_archived':True})
        output, selected, routes = gate._opencode_turn(['fixture','-m',primary,'nonce'], model=primary,
            env={'OPENROUTER_API_KEY':'fixture-key'}, cwd=tmp_path, timeout=300,
            quota_log=tmp_path/'log', nonce='nonce', declaration_page=page)
        assert selected == gate._FREE_FALLBACKS[0]
        assert [row['reason'] for row in routes] == ['free quota exhausted','completed']
        assert routes[-1]['nonce'] != routes[0]['nonce']
        declaration, request = gate._request_proof(page(),'ses_selected',routes[-1]['nonce'],output=output)
        assert declaration['root'] == routes[-1]['declaration'] == receipts[-1]['declaration']['root']
        assert declaration['app'] == declaration['native_process']['runtime'] == 'opencode'
        assert declaration['native_process']['pid'] == 200
        assert request['content'].endswith('AGENTLINK-REQUEST '+routes[-1]['nonce'])
        with pytest.raises(QualificationRefused, match='publish its nonce'):
            gate._request_proof(page(),'ses_selected',routes[0]['nonce'],output=output)
        # The accepted Agents list still excludes the server as a standalone row.
        assert registry._process_runtime(Process(200)) is None
    connection.close()
