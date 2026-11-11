// F296: compiled Studio, real declarations and both native formats in one disposable profile.
const fs=require('node:fs'), path=require('node:path'), assert=require('node:assert/strict');
const {spawn}=require('node:child_process'), readline=require('node:readline');
const {chromium}=require(require.resolve('playwright',{paths:[process.env.ARCHHUB_NODE_MODULES||path.join(process.cwd(),'node_modules')]}));
const script=String.raw`
import json, os, sys, tempfile, traceback
from pathlib import Path
root=Path(tempfile.mkdtemp(prefix='agentwork-',dir=str(Path.cwd()/'.cache'))).resolve()
for key in ('USERPROFILE','HOME','LOCALAPPDATA','APPDATA','TEMP','TMP'):
    directory=root/key
    directory.mkdir()
    os.environ[key]=str(directory)
os.environ.update(ARCHHUB_TEST_STATE_DIR=str(root/'state'),ARCHHUB_TEST_NO_OPEN='1',ARCHHUB_TEST_SECRET_STORE='memory',ARCHHUB_AGENT_PROFILE=str(root/'USERPROFILE'))
sys.path[:0]=[str(Path.cwd()/'01.APP'),str(Path.cwd()/'02.TESTS/tests')]
import psutil
from test_agentwork import native
from test_task_session_roundtrip import _Studio
from nodelang import host_brokers, workshop_tasks as tasks
from nodelang.workshop_mailbox import application_history,call,profile_database
from types import SimpleNamespace as MachinePipePeer
from nodelang.nograph_server import NoGraphServer
host_brokers._com_probe=lambda program:False
process=psutil.Process()
peer=MachinePipePeer(pid=process.pid,created_at=process.create_time(),cwd=str(root))
server=NoGraphServer(root/'state').start()
client=_Studio(server)
server._live_agents.get=lambda:{'processes':[{'runtime':'codex'},{'runtime':'claude'}],'complete':True}
server._providers.get=lambda:[]
contexts={'codex':{'threadId':'work-codex'},'claude':{'claude/sessionID':'work-claude'}}
held={}
def declare(vendor):
    return call('declare',{'task':'BA details '+vendor,'request_id':held[vendor]['taskId'],'paths':[str(root)],'status':'working','display_name':'Fixture '+vendor},contexts[vendor],database=profile_database(),peer=peer)
try:
    for vendor in contexts:
        held[vendor]=client.workshop('createTask','BA details '+vendor)
        declare(vendor)
    print(json.dumps({'url':server.public_url,'cookie':server._cookie_token,'tasks':held,'profile':str(root)}),flush=True)
    for line in sys.stdin:
        command=json.loads(line)
        try:
            vendor=command['vendor']
            if command['action']=='declare':
                folder=root/vendor
                folder.mkdir(exist_ok=True)
                first,second,edited=folder/'INDEX.csv',folder/'details.json',folder/'EDITED.csv'
                first.write_text('original index',encoding='utf-8')
                second.write_text('detail data',encoding='utf-8')
                edited.write_text('edited index',encoding='utf-8')
                calls=[]
                for title,tool,args,out in [
                    ('Read details index','Read',{'file_path':str(first),'api_key':'fixture-secret-text'},str(second)),
                    ('Read converted details','Read',{'file_path':str(second)},'detail data'),
                    ('Inspect native commands','Bash',{'command':'echo inspection','cwd':str(folder)},'inspection'),
                    ('Write reviewed details','Write',{'file_path':str(folder/'reviewed.txt'),'content':'reviewed'},'written'),
                    ('Read Revit views','r_views',{},'views'),
                    ('Set native parameters','b_set_parameter',{'parameter_name':'Comments','value':'Reviewed'},'done'),
                    ('Send review summary','send',{'to':'Fixture reviewer','text':'Review complete'},'receipt')]:
                    calls.extend([('declare',{'task':title,'request_id':held[vendor]['taskId']},'{}'),(tool,args,out)])
                native(root/'USERPROFILE',vendor,'work-'+vendor,calls)
                declare(vendor)
                answer={'ok':True,'edited':str(edited)}
            elif command['action']=='proof':
                from nodelang.session_files import read_document, _metadata_io
                with application_history() as history:
                    row=tasks.get(history,held[vendor]['taskId'])
                raw=_metadata_io(Path(row['session_path']).read_text,encoding='utf-8')
                assert 'fixture-secret-text' not in raw
                answer={'ok':True,'written':(root/vendor/'reviewed.txt').exists(),'nodes':len(read_document(row['session_path'])['nodes'])}
            else:
                raise ValueError('Unknown court command')
            print(json.dumps(answer),flush=True)
        except Exception:
            print(json.dumps({'courtError':traceback.format_exc()}),flush=True)
finally:
    client.close()
    server.close()
`;
(async()=>{
 const cache=process.env.PLAYWRIGHT_BROWSERS_PATH||path.join(process.env.LOCALAPPDATA,'ms-playwright');
 const entries=fs.readdirSync(cache), shell=entries.filter(n=>/^chromium_headless_shell-\d+$/.test(n)).sort((a,b)=>Number(b.split('-').at(-1))-Number(a.split('-').at(-1)))[0];
 const full=entries.filter(n=>/^chromium-\d+$/.test(n)).sort((a,b)=>Number(b.split('-').at(-1))-Number(a.split('-').at(-1)))[0];
 const child=spawn(process.env.ARCHHUB_COURT_PYTHON||'python',['-u','-B','-c',script],{windowsHide:true,stdio:['pipe','pipe','pipe']});
 let stderr='',browser,profile;const buffered=[],waiting=[];
 child.stderr.on('data',data=>stderr+=data);
 readline.createInterface({input:child.stdout}).on('line',line=>{const resolve=waiting.shift();resolve?resolve(line):buffered.push(line);});
 const ended=new Promise(resolve=>child.once('exit',resolve));
 const next=()=>Promise.race([buffered.length?Promise.resolve(buffered.shift()):new Promise(resolve=>waiting.push(resolve)),ended.then(()=>{throw Error(stderr);})]);
 const command=async(action,vendor)=>{child.stdin.write(JSON.stringify({action,vendor})+'\n');const r=JSON.parse(await next());assert.equal(r.courtError,undefined,r.courtError);return r;};
 try{
  const input=JSON.parse(await next());profile=input.profile;
  browser=await chromium.launch({headless:true,executablePath:path.join(cache,shell||full,shell?'chrome-headless-shell-win64/chrome-headless-shell.exe':'chrome-win64/chrome.exe')});
  const context=await browser.newContext({viewport:{width:1680,height:1000}});
  await context.addCookies([{name:'archhub_studio',value:input.cookie,url:input.url}]);
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(input.url);await page.locator('[data-home-ready]').waitFor({state:'attached',timeout:60000});
  for(const vendor of ['codex','claude']){
   await page.getByRole('button',{name:/^Agents \d+$/}).click();
   await page.locator('[data-agent-task="'+input.tasks[vendor].taskId+'"]').dblclick();
   try{await page.locator('.react-flow__node[data-id="start"]').waitFor();}
   catch(e){console.log(JSON.stringify(await page.evaluate(()=>{const s=window.ArchHubAPI.getSnapshot();return {file:s.sessionFile,opening:s.graphOpening,notice:s.connectionNotice,nodes:s.graph.nodes.map(n=>({id:n.id,title:n.title})),text:document.body.innerText.slice(-1500)};})));console.log(JSON.stringify(errors));throw e;}
   const opens=[];
   const track=request=>{try{const body=request.postDataJSON();if(body?.function==='openTaskGraph')opens.push(body.args[0]);}catch{}};
   page.on('request',track);
   await page.evaluate(async id=>{await Promise.all([window.ArchHubAPI.openTaskGraph(id),window.ArchHubAPI.openTaskGraph(id)]);},input.tasks[vendor].taskId);
   page.off('request',track);
   assert.deepEqual(opens,[input.tasks[vendor].taskId]);
   await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().sessionDirty===false);
   const started=Date.now(),receipt=await command('declare',vendor);
   const step=page.locator('.react-flow__node').filter({has:page.getByText('Read details index',{exact:true})});
   await step.waitFor({timeout:2000});assert.ok(Date.now()-started<=2000);
   assert.equal(await page.locator('.react-flow__node').count(),12,JSON.stringify(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.nodes.map(n=>({id:n.id,title:n.title,work:n.agentWork})))));
   await page.getByText('Model: fixture-model',{exact:true}).waitFor();
   await step.locator('[data-node-card-title]').click();
   const inspector=page.locator('[data-node-inspector]');
   const editor=inspector.getByRole('textbox',{name:'Read details index path'});
   assert.equal(await editor.inputValue(),'INDEX.csv');
   await editor.click();await editor.fill(receipt.edited);await step.locator('[data-node-card-title]').click();
   await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().sessionDirty===false);
   await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().graph.nodes.some(n=>n.title==='Read details index'&&n.output?.text==='edited index')&&window.ArchHubAPI.getSnapshot().sessionDirty===false);
   const saveSeen=Promise.withResolvers(),runSeen=Promise.withResolvers();
   const readRunSeen=Promise.withResolvers();
   const saveReply=Promise.withResolvers(),runReply=Promise.withResolvers();
   let heldSave=false,heldRun=false,readRan=false;
   const hold=async route=>{
    const body=route.request().postDataJSON();
    if(body.action==='run'&&body.document.nodes.some(n=>n.id===body.roots?.[0]&&n.title==='Read details index')){
     const response=await route.fetch();readRan=true;await route.fulfill({response});readRunSeen.resolve();
    }else if(body.action==='autosave'&&readRan&&!heldSave&&body.document.nodes.some(n=>n.title==='Read details index'&&n.result?.output?.text==='edited index')){
     heldSave=true;const response=await route.fetch();saveSeen.resolve();await saveReply.promise;await route.fulfill({response});
    }else if(body.action==='run'&&!heldRun&&body.document.nodes.some(n=>n.id===body.roots?.[0]&&n.title==='Write reviewed details')){
     heldRun=true;const response=await route.fetch();runSeen.resolve();await runReply.promise;await route.fulfill({response});
    }else await route.continue();
   };
   await page.route('**/api/session-files',hold);
   await inspector.getByRole('button',{name:'Run',exact:true}).click();
   await readRunSeen.promise;
   try{await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().graph.nodes.some(n=>n.title==='Read details index'&&n.output?.text==='edited index'));}
   catch(e){console.log(JSON.stringify(await page.evaluate(()=>({nodes:window.ArchHubAPI.getSnapshot().graph.nodes,notice:window.ArchHubAPI.getSnapshot().connectionNotice}))));throw e;}
   await inspector.locator('summary').filter({hasText:'History'}).click();await inspector.locator('[data-step-history]').waitFor();
   assert.match(await inspector.locator('[data-step-history]').innerText(),/call-1/);
   const shellNode=page.locator('.react-flow__node').filter({has:page.getByText('Inspect native commands',{exact:true})});
   assert.equal(await shellNode.getByRole('button',{name:'Run',exact:true}).count(),0);
   assert.ok(await page.locator('[data-graph-wire][stroke-dasharray="6 4"]').count()>0);
   const write=page.locator('.react-flow__node').filter({has:page.getByText('Write reviewed details',{exact:true})});
   await saveSeen.promise;
   await write.locator('[data-node-card-title]').click();
   await inspector.getByRole('button',{name:'Run',exact:true}).click();
   // Run drains pending saves; a read cannot replace the locally dirty document.
   await page.waitForTimeout(250);
   assert.equal(heldRun,false);
   saveReply.resolve();await runSeen.promise;
   runReply.resolve();
   try{await page.locator('[data-ask-card]').waitFor();}
   catch(error){console.log(JSON.stringify(await page.evaluate(()=>({text:document.body.innerText.slice(-3000),graph:window.ArchHubAPI.getSnapshot().graph,approvals:window.ArchHubAPI.getSnapshot().approvals}))));throw error;}
   await page.unroute('**/api/session-files',hold);
   assert.equal((await command('proof',vendor)).written,false);
   await page.locator('[data-ask-card]').getByRole('button',{name:'Approve',exact:true}).click();
   await page.locator('[data-ask-card]').getByText('Released',{exact:true}).first().waitFor();
   assert.equal((await command('proof',vendor)).written,true);
   await page.getByRole('dialog').press('Escape');
   await step.locator('[data-node-card-title]').click();
   await inspector.getByRole('button',{name:'Fork from here',exact:true}).click();
   await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().graph.nodes.filter(n=>!n.agentWork&&!n.workflowStart&&!n.fixed).length===7);
   // Return to the graph via the existing task route after inspecting the approval.
   await page.getByRole('button',{name:'Home',exact:true}).click();
   await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().tasks.filter(t=>t.description?.startsWith('BA details')).length===2);
   console.log('PASS '+vendor+': 7 typed steps within 2s, edited read Run, History by id, dashed dependency, shell has no Run, write held then approved, Fork copies 7 normal nodes, secret-free file, Home one task per session');
  }
  assert.deepEqual(errors,[]);await context.close();
 }finally{
  if(browser)await browser.close();child.stdin.end();
  await new Promise(resolve=>child.exitCode===null?child.once('exit',resolve):resolve());
  if(profile){const resolved=path.resolve(profile);assert.equal(path.dirname(resolved),path.resolve('.cache'));assert.ok(path.basename(resolved).startsWith('agentwork-'));assert.equal(fs.lstatSync(resolved).isSymbolicLink(),false);fs.rmSync(resolved,{recursive:true,maxRetries:10,retryDelay:100});}
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
