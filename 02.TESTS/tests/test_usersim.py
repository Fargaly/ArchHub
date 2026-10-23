"""Acceptance-policy checks; installed application traces remain mandatory."""
import importlib.util
import subprocess
from pathlib import Path


TOOL = Path(__file__).resolve().parents[2] / '03.TOOLS/tools/real_app_check'


def load():
    spec = importlib.util.spec_from_file_location('usersim', TOOL / 'usersim.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_window_breaks_every_persona_even_if_critic_said_done():
    sim = load()
    rows = [{'id':str(i), 'job':job, 'core':True, 'status':'DONE'} for i,job in enumerate(sim.CORE_JOBS)]
    report = sim.release_verdict(rows, frozen=True, complete=True)
    assert report['release'] is False
    assert all(row['status'] == 'BROKEN' for row in report['personas'])


def test_incomplete_or_unproven_jobs_are_advisory_without_regressions():
    sim = load()
    rows = [{'id':str(i), 'job':job, 'core':True, 'status':'CONFUSING', 'proven':True} for i,job in enumerate(sim.CORE_JOBS)]
    assert sim.release_verdict(rows, frozen=False, complete=True)['release']
    rows[3]['proven'] = False
    assert sim.release_verdict(rows, frozen=False, complete=True)['release']
    assert sim.release_verdict(rows, frozen=False, complete=False)['release']
    for row in rows:
        row['core'] = False
    assert sim.release_verdict(rows, frozen=False, complete=True)['release']


def test_critic_cannot_accept_an_unobserved_goal_or_unknown_screenshot(tmp_path):
    sim = load()
    row = {'status':'DONE', 'evidence':'missing.png', 'objection':''}
    assert sim.validate_critic(row, [], tmp_path)['status'] == 'UNREACHED'


def test_return1_hang_crash_baseline_regression_and_unreached():
    sim = load()
    rows = [{'id':str(i), 'job':job, 'core':True, 'status':'BROKEN', 'proven':False}
            for i,job in enumerate(sorted(sim.CORE_JOBS))]
    baseline = {'build':'20261023-0602-66b2344','personas':[dict(row) for row in rows]}
    assert sim.release_verdict(rows, frozen=False, complete=False, baseline=baseline)['release']
    assert not sim.release_verdict(rows, frozen=True, complete=False, baseline=baseline)['release']
    assert not sim.release_verdict(rows, frozen=False, crashed=True, complete=False, baseline=baseline)['release']
    baseline['personas'][0].update(status='DONE',proven=True)
    regression = sim.release_verdict(rows, frozen=False, complete=True, baseline=baseline)
    assert regression['release'] is False
    assert regression['regressions'] == [rows[0]['job']]
    for status in ('UNREACHED','CONFUSING','DONE'):
        rows[0]['status'] = status
        assert sim.release_verdict(rows, frozen=False, complete=True, baseline=baseline)['release']
    rows[0].update(status='BROKEN',core=False)
    assert sim.release_verdict(rows, frozen=False, complete=True, baseline=baseline)['release']


def test_actor_must_attempt_and_type_before_text_job_is_judged(tmp_path):
    sim = load()
    (tmp_path/'step.png').write_bytes(b'screenshot fixture')
    verdict = {'status':'BROKEN','evidence':'step.png','proven':False}
    click = {'shot':'step.png','outcome':{'attempted':True}}
    assert sim.validate_critic(verdict, [click], tmp_path, requires_input=True)['status'] == 'UNREACHED'
    typed = {'shot':'step.png','outcome':{'attempted':True,'typed':True}}
    assert sim.validate_critic(verdict, [click,typed], tmp_path, requires_input=True)['status'] == 'BROKEN'
    actor_error = {'shot':'step.png','outcome':{'error':'The live action target changed; observe again.'}}
    assert sim.validate_critic(verdict, [click,typed,actor_error], tmp_path, requires_input=True)['status'] == 'UNREACHED'
    assert sim.validate_critic(verdict, [{'shot':'step.png','outcome':{'error':'actor failed'}}], tmp_path)['status'] == 'UNREACHED'


def test_app_exit_requires_observed_process_loss_before_cleanup():
    sim = load()
    live = {'windows':[{'pid':17,'Responding':True}],'pids':[17,18]}
    assert not sim.app_exited([live,{'windows':[],'pids':[17,18]}])
    assert not sim.app_exited([live])
    assert sim.app_exited([live,{'windows':[],'pids':[18]}])
    assert sim.app_exited([{'windows':[],'pids':[],'app_exited':True}])


def test_typing_uses_key_events_and_requires_focus_and_value_readback():
    script = """
    import assert from 'node:assert/strict';
    const {act}=await import(process.argv[1]);
    const input={id:0,label:'Message',x:10,y:10,editable:true,focused:true,value:''};
    const observation={url:'http://127.0.0.1/studio',controls:[input]};
    let calls=[], reads=0;
    const ctx={mouse:async()=>assert.fail('already focused'),
      cdp:async(method,args)=>calls.push({method,...args}),
      js:async()=>[++reads===1?{label:'Message',origin:'http://127.0.0.1'}:null,true,'Hi'][reads-1]};
    assert.deepEqual(await act(ctx,{action:'type',target:0,value:'Hi'},observation),
      {action:'type',attempted:true,typed:true});
    assert.deepEqual(calls.map(x=>x.type),['keyDown','keyUp','keyDown','keyUp']);
    assert(calls.every(x=>x.method==='Input.dispatchKeyEvent'));
    reads=0;ctx.js=async()=>++reads===1?{label:'Message',origin:'http://127.0.0.1'}:false;
    await assert.rejects(act(ctx,{action:'type',target:0,value:'Hi'},observation),/take focus/);
    reads=0;ctx.js=async()=>++reads===1?{label:'Message',origin:'http://127.0.0.1'}:reads===2?true:'';
    await assert.rejects(act(ctx,{action:'type',target:0,value:'Hi'},observation),/not observed/);
    """
    subprocess.run(['node','--input-type=module','-e',script,(TOOL/'usersim.mjs').as_uri()],check=True,timeout=10)


def test_signing_failure_and_borrowed_runtime_and_missing_readers_cannot_qualify():
    sim = load()
    reader = {'alive_before_close':True,'declaration':{'sender_key':'synthetic'},'samples':[{'ok':True}]}
    report = {'load_readers':[reader]*11,'scale':{'messages':60000},'samples':[{}],
              'signing_key_verdict':'PASS','scope_gaps':[]}
    assert sim.qualification_complete(report,completed=True,same_runtime=True,unchanged=True)
    assert not sim.qualification_complete(report,completed=True,same_runtime=False,unchanged=True)
    report['signing_key_verdict']='FAIL'
    assert not sim.qualification_complete(report,completed=True,same_runtime=True,unchanged=True)
    report['signing_key_verdict']='PASS'
    reader['alive_before_close']=False
    assert not sim.qualification_complete(report,completed=True,same_runtime=True,unchanged=True)


def test_personas_are_unique_editable_nodes_covering_founder_jobs():
    sim = load()
    nodes = sim.read_personas(TOOL / 'USERSIM-PERSONAS.json')
    assert len(nodes) >= 8
    assert len({node['id'] for node in nodes}) == len(nodes)
    assert {'router','connectors','workshop','profiling','install','update','workspaces','canvas'} <= {node['job'] for node in nodes}


def test_model_json_rejects_non_object_and_paid_route():
    sim = load()
    for value in ('[]', 'true', 'null'):
        try:
            sim.model_object(value)
        except ValueError:
            continue
        raise AssertionError(value)
    assert sim.model_object('```json\n{"action":"observe"}\n```')['action'] == 'observe'


def test_action_boundary_rejects_native_update_stale_targets_and_keyboard_navigation():
    script = """
    import assert from 'node:assert/strict';
    const {act}=await import(process.argv[1]);
    let inputs=0;
    const ctx={mouse:async()=>inputs++,cdp:async()=>inputs++,
      js:async()=>({label:'changed',disabled:false,origin:'http://127.0.0.1'})};
    const observation={url:'http://127.0.0.1/studio',controls:[{id:0,label:'Update available',x:10,y:10}]};
    await assert.rejects(act(ctx,{action:'click',target:0},observation),/native action/);
    observation.controls[0].label='Home';
    await assert.rejects(act(ctx,{action:'click',target:0},observation),/target changed/);
    ctx.js=async()=>({label:'Help',href:'https://example.com',origin:'http://127.0.0.1',submits:[]});
    await assert.rejects(act(ctx,{action:'key',value:'Enter'},observation),/External navigation/);
    ctx.js=async()=>({label:'Folder',submits:['Add']});
    await assert.rejects(act(ctx,{action:'key',value:'Enter'},observation),/Workspaces key/);
    assert.equal(inputs,0);
    """
    subprocess.run(['node','--input-type=module','-e',script,(TOOL/'usersim.mjs').as_uri()],check=True,timeout=10)
