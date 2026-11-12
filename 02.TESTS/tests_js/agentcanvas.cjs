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
protocol_stdout=sys.stdout
sys.stdout=sys.stderr
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
    roster={'processes':[{'runtime':runtime} for runtime in runtimes], 'complete':True}
    server=NoGraphServer(root/'state',agent_source=lambda:roster).start()
    server._live_agents.reset(roster)
    client=_Studio(server)
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
        print(json.dumps({'url':server.public_url,'cookie':server._cookie_token,'task':task['taskId'],'missing':missing['taskId'],'profile':str(root)}),file=protocol_stdout,flush=True)
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
                elif command['action']=='legacy':
                    print('Refreshing legacy workflow fixture',flush=True)
                    from nodelang.session_files import SessionFiles,new_document,write_document
                    document=new_document('Legacy task composition')
                    for key in ('a','b'):
                        document['nodes'].extend([
                            {'id':key,'type':'thing.agent','title':'Legacy '+key,'params':{'session':key},'agentWork':{'role':'session'},'position':{'x':0,'y':0}},
                            {'id':key+'-step','type':'note','title':'Step '+key,'params':{},'agentWork':{'role':'step','owner':key},'position':{'x':300,'y':0}}])
                    document['groups']=[{'id':'frame','nodes':['a-step','b-step']}]
                    document['notes']=[{'id':'annotation','text':'Retained migration annotation'}]
                    path=SessionFiles().directory/'Legacy task composition.archhub'
                    write_document(path,document)
                    answer={'path':str(path),'nodes':[n['id'] for n in document['nodes']],'groups':document['groups'],'notes':document['notes']}
                elif command['action']=='empty':
                    with application_history() as history:
                        history._db.execute("UPDATE workshop_declarations SET record=json_set(record,'$.status','done')")
                    roster['processes']=[]
                    server._live_agents.reset({'processes':[], 'complete':True})
                    answer={'ok':True}
                else:
                    raise ValueError('Unknown court command')
                print(json.dumps(answer),file=protocol_stdout,flush=True)
            except Exception:
                print(json.dumps({'courtError':traceback.format_exc()}),file=protocol_stdout,flush=True)
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
    const nodeCount=async count=>{
      await page.waitForFunction(n=>{const nodes=window.ArchHubAPI.getSnapshot().graph.nodes,session=nodes.some(node=>node.fixed&&node.type==='thing.session');const hidden=nodes.filter(node=>node.fixed&&node.type!=='thing.session'||session&&node.agentWork?.role==='session'&&!node.agentStep).length;return document.querySelectorAll('.react-flow__node').length===n-hidden;},count);
      const graph=await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.nodes);
      assert.equal(graph.length,count);
      assert.equal(await page.locator('.react-flow__node').count(),count-graph.filter(node=>node.fixed&&node.type!=='thing.session'||graph.some(row=>row.fixed&&row.type==='thing.session')&&node.agentWork?.role==='session'&&!node.agentStep).length);
      if(graph.some(node=>node.fixed&&node.type==='thing.session'))assert.equal(await page.locator('[data-design^="session.panel."]').count(),6);
    };
    // Input stays inside this private headless page, using the existing design court's CDP path.
    const inputSession=await context.newCDPSession(page);
    const key=async(name,code,modifiers=0)=>{
      await inputSession.send('Input.dispatchKeyEvent',{type:'keyDown',key:name,code:name,windowsVirtualKeyCode:code,modifiers,...(name==='Enter'?{text:String.fromCharCode(13)}:{})});
      await inputSession.send('Input.dispatchKeyEvent',{type:'keyUp',key:name,code:name,windowsVirtualKeyCode:code,modifiers});
    };
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto(input.url);
    await page.locator('[data-home-ready]').waitFor({state:'attached',timeout:60000});
    await page.getByRole('button',{name:'4 working · 0 idle · Nothing waiting for you',exact:true}).click();
    const view=page.locator('[data-screen="agents"]');
    await page.getByRole('button',{name:'4 working · 0 idle · Nothing waiting for you',exact:true}).waitFor();
    await view.locator('[data-agent-session]').first().waitFor();
    await page.waitForFunction(()=>document.querySelectorAll('[data-agent-session]').length===5);
    assert.equal(await view.locator('[data-agent-session]').count(),5);
    assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().agentWorkingCount),4);
    assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().agentSummary),'4 working · 0 idle');
    assert.ok(await view.locator('[data-agent-task]').count()>=2);
    assert.equal(await view.locator('[data-graph-wire]').count(),0);
    await view.getByText(/Waiting for you/).first().waitFor();
    await view.getByText(/No task/).first().waitFor();
    await view.getByText('No workflow file',{exact:true}).waitFor();
    assert.equal(await view.getByRole('button',{name:'Run',exact:true}).count(),0);
    for(const [width,height] of [[1366,768],[1680,893]]){
      await page.setViewportSize({width,height});
      assert.equal(await view.locator('[data-graph-node]').count(),0);
      await page.screenshot({path:`05.EVIDENCE/agentcanvas/agents-${width}.png`});
    }
    console.log('PASS Agents: live session list opens task files; no shared canvas or wires; waiting/unassigned/missing-file states; both viewports');
    for(const vendor of ['Codex','Claude']){
      await view.locator('[data-agent-session]').filter({hasText:'Fixture '+(vendor==='Codex'?0:1)}).getByRole('button',{name:'Open transcript',exact:true}).click();
      await page.getByRole('dialog',{name:'Agent transcript'}).getByText('Native '+vendor+' transcript text',{exact:true}).waitFor();
      await page.getByRole('button',{name:'Close transcript',exact:true}).click();
    }
    console.log('PASS Open transcript reads real Codex and Claude fixture native logs');
    await view.locator('[data-agent-session]').filter({hasText:'Fixture 0'}).getByRole('button',{name:'Open thread',exact:true}).click();
    await page.getByRole('region',{name:'Conversation',exact:true}).waitFor();
    console.log('PASS Open thread lands on the real task Workshop thread');
    await page.locator('button[title="Home"][aria-label="Home"]').click();
    await page.getByRole('button',{name:'4 working · 0 idle · Nothing waiting for you',exact:true}).click();
    await page.locator(`[data-agent-task="${input.task}"]`).dblclick();
    await page.locator('.react-flow__node[data-id="start"]').waitFor();
    await nodeCount(7);
    assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().nodes.filter(n=>n.params?.workshop_step).length),3);
    await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().sessionDirty===false);
    await command('declare');
    const started=Date.now();
    await page.locator('.react-flow__node').getByText('Export approved drawings',{exact:true}).waitFor({timeout:10000});
    const elapsed=Date.now()-started;
    console.log('PASS real declare() updates task Canvas without canvas tools in '+elapsed+' ms');
    const completed=await command('complete');
    assert.equal(completed.ok,true,JSON.stringify(completed));
    try{await page.locator('.react-flow__node').getByText('commit 12345678',{exact:true}).waitFor({timeout:10000});}
    catch(error){console.log('Completion diagnostic '+JSON.stringify({receipt:completed.steps,browser:await page.evaluate(()=>{const s=window.ArchHubAPI.getSnapshot();return {dirty:s.sessionDirty,nodes:s.graph.nodes.map(n=>({title:n.title,status:n.params.status,result:n.params.result}))};})}));throw error;}
    for(const [width,height] of [[1366,768],[1680,893]]){
      await page.setViewportSize({width,height});
      await page.getByRole('button',{name:'Fit',exact:true}).click();
      await page.screenshot({path:`05.EVIDENCE/agentcanvas/steps-${width}.png`});
    }
    console.log('PASS task_complete() records declared done status and commit; Start plus 3 real thing.agent steps');
    const linked=await page.evaluate(async()=>{
      const api=window.ArchHubAPI, child=api.getSessionPath(), before=api.getSessionDocument();
      await api.newSession('Composition');await api.saveSession();
      const parent=api.getSessionPath();await api.refreshLibraryPorts();
      const item=api.getSnapshot().libraryPorts.find(row=>row.path===child);
      const node=await api.addNode(item.id,{x:80,y:100});await api.saveSession();
      return {child,parent,node:node.id,before:before.nodes.length};
    });
    await nodeCount(1);
    await page.locator(`.react-flow__node[data-id="${linked.node}"]`).dblclick();
    await page.getByRole('button',{name:'Parent session',exact:true}).waitFor();
    assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSessionPath()),linked.child);
    await nodeCount(linked.before);
    await page.evaluate(async()=>{await window.ArchHubAPI.renameNode('start','Edited inside session');await window.ArchHubAPI.saveSession();});
    await page.getByRole('button',{name:'Parent session',exact:true}).click();
    await page.waitForFunction(parent=>window.ArchHubAPI.getSessionPath()===parent,linked.parent);
    await nodeCount(1);
    const card=page.locator(`.react-flow__node[data-id="${linked.node}"]`);
    await card.click();await key('Enter',13);
    await page.getByRole('button',{name:'Parent session',exact:true}).waitFor();
    await page.locator('.node-canvas').focus();await key('Escape',27);
    await page.waitForFunction(parent=>window.ArchHubAPI.getSessionPath()===parent,linked.parent);
    await nodeCount(1);
    console.log('PASS linked session: one group, double-click/Enter, original file edits, breadcrumb/Escape return');
    const legacy=await command('legacy');
    await page.evaluate(path=>window.ArchHubAPI.openSession(path),legacy.path);
    await nodeCount(2);
    await page.locator('.node-canvas').focus();await key('z',90,2);
    await page.waitForFunction(()=>window.ArchHubAPI?.getSessionDocument()?.nodes.length===4);
    const recovered=await page.evaluate(async()=>{await window.ArchHubAPI.saveSession();return window.ArchHubAPI.getSessionDocument();});
    assert.deepEqual(recovered.nodes.map(n=>n.id).sort(),legacy.nodes.sort());
    assert.deepEqual(recovered.groups,legacy.groups);assert.deepEqual(recovered.notes,legacy.notes);
    await page.evaluate(path=>window.ArchHubAPI.openSession(path),legacy.path);
    await nodeCount(4);
    await page.reload();
    await page.waitForFunction(()=>window.ArchHubAPI?.getSessionDocument()?.nodes.length===4);
    await nodeCount(4);
    const persisted=await page.evaluate(()=>window.ArchHubAPI.getSessionDocument());
    assert.deepEqual(persisted.groups,legacy.groups);assert.deepEqual(persisted.notes,legacy.notes);
    console.log('PASS automatic legacy migration is undoable through real CtrlZ with group membership and notes restored');
    await command('empty');
    await page.locator('button[title="Home"][aria-label="Home"]').click();
    await page.getByRole('button',{name:/working ·.*idle ·|No agents are running\. ·/}).click();
    await view.getByText('No agent sessions are running.',{exact:true}).waitFor();
    await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().agentSummary==='No agents are running.');
    assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().agentWorkingCount),0);
    await page.getByRole('button',{name:'No agents are running. · Nothing waiting for you',exact:true}).waitFor();
    await page.locator('button[title="Home"][aria-label="Home"]').click();
    await page.getByRole('button',{name:'No agents are running. · Nothing waiting for you',exact:true}).waitFor();
    await page.screenshot({path:'05.EVIDENCE/agentcanvas/agents-empty.png'});
    assert.deepEqual(errors,[]);
    console.log('PASS empty roster; no browser errors; derived view never saved');
    await context.close();
  } finally {
    if(browser)await browser.close();
    child.stdin.end();
    const closeTimer=setTimeout(()=>child.kill(),5000);
    const code=await new Promise(resolve=>child.exitCode===null?child.once('exit',resolve):resolve(child.exitCode));
    clearTimeout(closeTimer);
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
