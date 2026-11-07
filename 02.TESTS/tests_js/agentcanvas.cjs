// Real mailbox calls and compiled Studio, confined to one disposable profile.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const readline = require('node:readline');
const modules = process.env.ARCHHUB_NODE_MODULES || path.join(process.cwd(), 'node_modules');
const {chromium} = require(require.resolve('playwright', {paths:[modules]}));
const serverScript = String.raw`
import json, os, sys, tempfile, traceback
from pathlib import Path
def main():
    temporary=tempfile.mkdtemp(prefix='agentcanvas-', dir=os.environ.get('ARCHHUB_TEST_STATE_DIR') or tempfile.gettempdir())
    root=Path(temporary).resolve()
    for key in ('USERPROFILE','HOME','LOCALAPPDATA','APPDATA','TEMP','TMP'):
        directory=root/key
        directory.mkdir()
        os.environ[key]=str(directory)
    os.environ['ARCHHUB_TEST_STATE_DIR']=str(root/'state')
    os.environ['ARCHHUB_TEST_NO_OPEN']='1'
    os.environ['ARCHHUB_TEST_SECRET_STORE']='memory'
    os.environ['ARCHHUB_AGENT_PROFILE']=str(root/'USERPROFILE')
    native=root/'USERPROFILE' / '.codex' / 'sessions' / 'fixture'
    native.mkdir(parents=True)
    (native/'rollout-fixture-canvas-codex.jsonl').write_text(json.dumps({'type':'response_item','payload':{'type':'message','role':'assistant','content':[{'type':'output_text','text':'Native Codex transcript text'}]}})+'\n',encoding='utf-8')
    native=root/'USERPROFILE' / '.claude' / 'projects' / 'fixture'
    native.mkdir(parents=True)
    (native/'canvas-claude.jsonl').write_text(json.dumps({'type':'assistant','message':{'role':'assistant','content':[{'type':'text','text':'Native Claude transcript text'}]}})+'\n',encoding='utf-8')
    sys.path.insert(0,str(Path('01.APP').resolve()))
    sys.path.insert(0,str(Path('02.TESTS/tests').resolve()))
    import psutil
    from nodelang import host_brokers, workshop_tasks as tasks
    from nodelang.workshop_mailbox import application_history, call, profile_database, ROOM, CATEGORY
    from types import SimpleNamespace as MachinePipePeer
    from nodelang.nograph_server import NoGraphServer, r_agents_canvas
    from test_task_session_roundtrip import _Studio
    host_brokers._com_probe=lambda program:False
    process=psutil.Process()
    peer=MachinePipePeer(pid=process.pid,created_at=process.create_time(),cwd=str(root))
    contexts=[{'threadId':'canvas-codex'},{'claude/sessionID':'canvas-claude'},{'ai.opencode/sessionID':'canvas-opencode'},{'gemini/sessionID':'canvas-idle'},{'goose/sessionID':'canvas-missing'}]
    runtimes=['codex','claude','opencode','gemini','goose']
    server=NoGraphServer(root/'state').start()
    client=_Studio(server)
    server._live_agents.get=lambda:{'processes':[{'runtime':runtime} for runtime in runtimes],'complete':True}
    server._providers.get=lambda:[]  # Provider CLI readiness is outside this isolated canvas court.
    def declare(index,title='Review drawings',status='working'):
        return call('declare',{'task':title,'request_id':task['taskId'] if index<3 else 'unassigned' if index==3 else missing['taskId'],
            'paths':[str(root/('lane'+str(index)))],'status':status,'display_name':'Fixture '+str(index)},contexts[index],database=profile_database(),peer=peer)
    try:
        task=client.workshop('createTask','Agent workflow review')
        missing=client.workshop('createTask','Missing workflow fixture')
        for index in range(5):
            result=declare(index,status='blocked' if index==1 else 'working')
            declaration=result['declaration']
            with application_history() as history:
                history.append(ROOM,author=declaration['agent']+' ['+declaration['session']+']',content='To *:\nReview update '+str(index),category=CATEGORY,idempotency_key='fixture-message-'+str(index))
                if index<3:
                    tasks.release(history,task['taskId'],declaration['session'])
        with application_history() as history:
            history._db.execute('UPDATE workshop_tasks SET session_path=NULL WHERE id=?',(missing['taskId'],))
        graph=r_agents_canvas(server,None)
        assert len(graph['sessions'])==5, graph
        assert len(graph['wires'])==3, graph
        print(json.dumps({'url':server.public_url,'cookie':server._cookie_token,'task':task['taskId'],'missing':missing['taskId'],'profile':str(root)}),flush=True)
        for line in sys.stdin:
            command=json.loads(line)
            try:
                if command['action']=='declare':
                    declare(0,'Export approved drawings')
                    answer={'ok':True}
                elif command['action']=='complete':
                    answer=call('task_complete',{'id':task['taskId'],'result':'commit 12345678'},contexts[0],database=profile_database(),peer=peer)
                    from nodelang.session_files import read_document
                    with application_history() as history:
                        held=tasks.get(history,task['taskId'])
                    answer['steps']=[{'title':n['title'],'status':n['params'].get('status'),'result':n['params'].get('result')} for n in read_document(held['session_path'])['nodes'] if n['type']=='thing.agent']
                elif command['action']=='empty':
                    with application_history() as history:
                        history._db.execute("UPDATE workshop_declarations SET record=json_set(record,'$.status','done')")
                    server._live_agents.get=lambda:{'processes':[],'complete':True}
                    answer={'ok':True}
                else:
                    raise ValueError('Unknown court command')
                print(json.dumps(answer),flush=True)
            except Exception:
                print(json.dumps({'courtError':traceback.format_exc()}),flush=True)
    finally:
        client.close()
        server.close()
main()
`;

(async()=>{
  const child=spawn(process.env.ARCHHUB_COURT_PYTHON||'python',['-u','-c',serverScript],{windowsHide:true,stdio:['pipe','pipe','pipe']});
  const lines=readline.createInterface({input:child.stdout}), waiting=[], buffered=[];
  let stderr='', browser, profile;
  child.stderr.on('data',chunk=>stderr+=chunk);
  lines.on('line',line=>{const resolve=waiting.shift();if(resolve)resolve(line);else buffered.push(line);});
  const ended=new Promise(resolve=>child.once('exit',resolve));
  const next=()=>Promise.race([buffered.length?Promise.resolve(buffered.shift()):new Promise(resolve=>waiting.push(resolve)),ended.then(()=>{throw Error('Isolated fixture exited: '+stderr);})]);
  const command=async action=>{child.stdin.write(JSON.stringify({action})+'\n');const result=JSON.parse(await next());assert.equal(result.courtError,undefined,result.courtError);return result;};
  try {
    const input=JSON.parse(await next());
    profile=input.profile;
    const cache=process.env.PLAYWRIGHT_BROWSERS_PATH||path.join(process.env.LOCALAPPDATA,'ms-playwright');
    const entries=fs.readdirSync(cache), shell=entries.filter(n=>/^chromium_headless_shell-\d+$/.test(n)).sort((a,b)=>Number(b.split('-').at(-1))-Number(a.split('-').at(-1)))[0];
    const full=entries.filter(n=>/^chromium-\d+$/.test(n)).sort((a,b)=>Number(b.split('-').at(-1))-Number(a.split('-').at(-1)))[0];
    browser=await chromium.launch({headless:true,executablePath:path.join(cache,shell||full,shell?'chrome-headless-shell-win64/chrome-headless-shell.exe':'chrome-win64/chrome.exe')});
    const context=await browser.newContext({viewport:{width:1366,height:768}});
    await context.addCookies([{name:'archhub_studio',value:input.cookie,url:input.url}]);
    const page=await context.newPage(), errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto(input.url);
    await page.locator('[data-home-ready]').waitFor({state:'attached',timeout:60000});
    await page.getByRole('button',{name:/^Agents \d+$/}).click();
    const view=page.locator('[data-screen="agents"]');
    await view.locator('[data-agent-session]').first().waitFor();
    assert.equal(await view.locator('[data-agent-session]').count(),5);
    assert.equal(await view.locator('[data-agent-task]').count(),2);
    assert.equal(await view.locator('[data-graph-wire]').count(),3);
    await view.getByText('Waiting for you',{exact:true}).waitFor();
    await view.getByText('No task',{exact:true}).waitFor();
    await view.getByText('No workflow file',{exact:true}).waitFor();
    assert.equal(await view.getByRole('button',{name:'Run',exact:true}).count(),0);
    for(const [width,height] of [[1366,768],[1680,893]]){
      await page.setViewportSize({width,height});
      await view.getByRole('button',{name:'Fit',exact:true}).click();
      await page.screenshot({path:`05.EVIDENCE/agentcanvas/agents-${width}.png`});
    }
    console.log('PASS Agents: 5 live sessions, fan-in task wires, waiting/unassigned/missing-file states, no Run; both design viewports');
    for(const vendor of ['Codex','Claude']){
      await view.locator('[data-agent-session]').filter({hasText:'Fixture '+(vendor==='Codex'?0:1)}).getByRole('button',{name:'Open transcript',exact:true}).click();
      await page.getByRole('dialog',{name:'Agent transcript'}).getByText('Native '+vendor+' transcript text',{exact:true}).waitFor();
      await page.getByRole('button',{name:'Close transcript',exact:true}).click();
    }
    console.log('PASS Open transcript reads real Codex and Claude fixture native logs');
    await view.locator('[data-agent-session]').first().getByRole('button',{name:'Open thread',exact:true}).click();
    await page.getByRole('heading',{name:'Thread activity',exact:true}).waitFor();
    console.log('PASS Open thread lands on the real task Workshop thread');
    await page.getByRole('button',{name:'Home',exact:true}).click();
    await page.getByRole('button',{name:/^Agents \d+$/}).click();
    await page.locator(`[data-agent-task="${input.task}"]`).dblclick();
    await page.locator('.react-flow__node[data-id="start"]').waitFor();
    assert.equal(await page.locator('.react-flow__node').count(),4);
    await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().sessionDirty===false);
    const started=Date.now();
    await command('declare');
    await page.locator('.react-flow__node').getByText('Export approved drawings',{exact:true}).waitFor({timeout:2000});
    const elapsed=Date.now()-started;
    assert.ok(elapsed<=2000,'step refresh '+elapsed+' ms');
    console.log('PASS real declare() updates task Canvas without canvas tools in '+elapsed+' ms');
    const completed=await command('complete');
    assert.equal(completed.ok,true,JSON.stringify(completed));
    try{await page.locator('.react-flow__node').getByText('commit 12345678',{exact:true}).waitFor({timeout:2000});}
    catch(error){console.log('Completion diagnostic '+JSON.stringify({receipt:completed.steps,browser:await page.evaluate(()=>{const s=window.ArchHubAPI.getSnapshot();return {dirty:s.sessionDirty,nodes:s.graph.nodes.map(n=>({title:n.title,status:n.params.status,result:n.params.result}))};})}));throw error;}
    for(const [width,height] of [[1366,768],[1680,893]]){
      await page.setViewportSize({width,height});
      await page.getByRole('button',{name:'Fit',exact:true}).click();
      await page.screenshot({path:`05.EVIDENCE/agentcanvas/steps-${width}.png`});
    }
    console.log('PASS task_complete() records declared done status and commit; Start plus 3 real thing.agent steps');
    await command('empty');
    await page.getByRole('button',{name:'Home',exact:true}).click();
    await page.getByRole('button',{name:/^Agents \d+$/}).click();
    await view.getByText('No agent sessions are running.',{exact:true}).waitFor();
    await page.screenshot({path:'05.EVIDENCE/agentcanvas/agents-empty.png'});
    assert.deepEqual(errors,[]);
    console.log('PASS empty roster; no browser errors; derived view never saved');
    await context.close();
  } finally {
    if(browser)await browser.close();
    child.stdin.end();
    const code=await new Promise(resolve=>child.exitCode===null?child.once('exit',resolve):resolve(child.exitCode));
    if(profile){
      const resolved=path.resolve(profile), owned=path.resolve(process.env.ARCHHUB_TEST_STATE_DIR||os.tmpdir());
      assert.equal(path.dirname(resolved),owned);
      assert.ok(path.basename(resolved).startsWith('agentcanvas-'));
      assert.equal(fs.lstatSync(resolved).isSymbolicLink(),false);
      fs.rmSync(resolved,{recursive:true,maxRetries:10,retryDelay:100});
    }
    assert.equal(code,0,stderr);
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
