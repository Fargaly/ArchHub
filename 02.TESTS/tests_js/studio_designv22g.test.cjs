const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {spawn}=require('node:child_process');
const {chromium}=require('playwright');

const root=path.resolve(__dirname,'../..'),app=path.join(root,'01.APP');
const python=process.env.ARCHHUB_COURT_PYTHON || 'C:/Users/fargaly/AppData/Local/ArchHub/.venv/Scripts/python.exe';

async function openCourt(t){
  const cache=path.join(root,'.cache');fs.mkdirSync(cache,{recursive:true});
  const profile=fs.mkdtempSync(path.join(cache,'testiso-designv22g-ui-'));
  const env={...process.env,USERPROFILE:profile,HOME:profile,LOCALAPPDATA:path.join(profile,'LOCAL'),APPDATA:path.join(profile,'ROAMING'),TEMP:path.join(profile,'tmp'),TMP:path.join(profile,'tmp'),ARCHHUB_HOME:profile,ARCHHUB_TEST_STATE_DIR:path.join(profile,'state'),ARCHHUB_TEST_SECRET_STORE:'memory',PYTHONPATH:app};
  for(const key of ['LOCALAPPDATA','APPDATA','TEMP','ARCHHUB_TEST_STATE_DIR'])fs.mkdirSync(env[key],{recursive:true});
  const code=`import sys,json\ndef audit(event,args):\n    if event == 'os.rename' and str(args[1]).endswith('.archhub'):\n        with open(${JSON.stringify(path.join(profile,'writes.jsonl'))},'a') as log: log.write(json.dumps(str(args[1]))+'\\n')\nsys.addaudithook(audit)\nsys.path.insert(0,${JSON.stringify(app)})\nfrom nodelang.nograph_server import NoGraphServer\nfrom nodelang.pipeline_engines import PIPELINE_ENGINES\ns=NoGraphServer(${JSON.stringify(env.ARCHHUB_TEST_STATE_DIR)},port=0,engines=PIPELINE_ENGINES).start()\nprint(json.dumps({'url':s.public_url,'bootstrap':s.browser_bootstrap_token}),flush=True)\ntry:\n    sys.stdin.read()\nfinally:\n    s.close()\n`;
  let child,ended,browser;
  const start=()=>{
    child=spawn(python,['-E','-s','-B','-c',code],{cwd:app,env,windowsHide:true});
    let stderr='';child.stderr.on('data',data=>stderr+=data);
    ended=new Promise(resolve=>child.once('exit',resolve));
    return new Promise((resolve,reject)=>{let output='';const timeout=setTimeout(()=>reject(Error('Studio start timed out: '+stderr)),60000);child.stdout.on('data',data=>{output+=data;if(output.includes('\n')){clearTimeout(timeout);try{resolve(JSON.parse(output.split('\n')[0]));}catch(error){reject(error);}}});child.once('exit',code=>{clearTimeout(timeout);reject(Error('Studio exited '+code+': '+stderr));});});
  };
  t.after(async()=>{await browser?.close();child.stdin.end();await ended;const relative=path.relative(cache,profile);assert.ok(relative&&!relative.startsWith('..')&&!path.isAbsolute(relative));fs.rmSync(profile,{recursive:true,force:true,maxRetries:5,retryDelay:100});});
  let server=await start();
  const courtChrome=path.join(process.env.LOCALAPPDATA,'ms-playwright/chromium-1228/chrome-win64/chrome.exe');
  browser=await chromium.launch({headless:true,executablePath:fs.existsSync(courtChrome)?courtChrome:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({viewport:{width:1864,height:949}}),errors=[];
  page.setDefaultTimeout(15000);
  page.on('pageerror',error=>errors.push(error.message));
  const url=server.url+'/studio?bootstrap='+server.bootstrap;
  await page.goto(url);await page.locator('[data-home-page]').waitFor({state:'attached',timeout:15000}).catch(async error=>{throw Error(error.message+'; page errors='+JSON.stringify(errors)+'; body='+(await page.locator('body').innerText()).slice(0,2000));});
  const restart=async()=>{child.stdin.end();await ended;return start();};
  return {page,profile,server,errors,restart};
}

test('Canvas save conflict recovery on compiled Studio at 1009 and 1440', {timeout:120000}, async t=>{
  const {page,profile,errors}=await openCourt(t);
  const wire=(id,from,to)=>({id,from:{node:from,socket:'out'},to:{node:to,socket:'in'}});
  await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Canvas',exact:true}).click();
  for(const width of [1009,1440])for(const keep of [true,false]){
    await page.setViewportSize({width,height:900});
    const id='recovery-'+width+(keep?'-keep':'-discard');
    const file=path.join(profile,id+'.archhub');
    const nodes=['source','middle','end'].map((id,index)=>({id,type:'data.convert',item:'data.convert',title:id,
      params:{target_type:'text'},position:{x:120+index*350,y:180}}));
    fs.writeFileSync(file,JSON.stringify({format:'archhub',version:1,id,title:id,nodes,
      wires:[wire('original','source','middle')],groups:[],notes:[],viewport:{x:0,y:0,zoom:1},properties:{viewportSaved:false}}));
    await page.evaluate(file=>window.ArchHubAPI.openSession(file),file);
    const base=await page.evaluate(()=>window.ArchHubAPI.getSessionDocument());
    const newer=JSON.parse(JSON.stringify(base));
    newer.wires.push(wire('committed','middle','end'));
    let bytes;
    const handler=async route=>{
      const draft=route.request().postDataJSON();
      if(!bytes&&draft?.action==='autosave'&&draft.path===file&&
          draft.document.wires.some(w=>w.from.node==='source'&&w.to.node==='end')){
        const saved=await page.request.post(route.request().url(),{headers:route.request().headers(),
          data:{...draft,document:newer,base_revision:base.properties?.revision||0}});
        assert.equal(saved.ok(),true);
        bytes=fs.readFileSync(file);
      }
      await route.continue();
    };
    await page.route('**/api/session-files',handler);
    try{
      await page.evaluate(async()=>{
        const api=window.ArchHubAPI;
        await api.deleteWire('original');
        await api.connectSockets({from:'source',fromPort:'out',to:'end',toPort:'in'});
      });
      const alert=page.getByRole('alert').filter({hasText:'This workflow changed elsewhere'});
      await alert.waitFor();
      assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().sessionDirty),true);
      const keepButton=alert.getByRole('button',{name:'Keep my changes as a copy',exact:true});
      const discardButton=alert.getByRole('button',{name:'Discard my changes and reload',exact:true});
      assert.ok(await keepButton.isVisible()&&await discardButton.isVisible());
      const action=keep?keepButton:discardButton;
      await action.click();
      await alert.waitFor({state:'hidden'});
      const recovered=await page.evaluate(()=>({document:window.ArchHubAPI.getSessionDocument(),
        file:window.ArchHubAPI.getSessionPath(),dirty:window.ArchHubAPI.getSnapshot().sessionDirty}));
      assert.equal(recovered.file,file);
      assert.equal(recovered.dirty,false);
      assert.deepEqual(recovered.document.wires,newer.wires);
      assert.deepEqual(fs.readFileSync(file),bytes);
      const copies=fs.readdirSync(profile).filter(name=>name.startsWith(id+' (my changes ')&&name.endsWith('.archhub'));
      assert.equal(copies.length,keep?1:0);
      if(keep){
        const copy=JSON.parse(fs.readFileSync(path.join(profile,copies[0]),'utf8'));
        assert.notEqual(copy.id,base.id);
        assert.deepEqual(copy.wires.map(w=>[w.from.node,w.to.node]),[['source','end']]);
      }
    }finally{await page.unroute('**/api/session-files',handler);}
  }
  assert.deepEqual(errors,[]);
});

test('Pasted file watcher preserves its source folder across workflows and stays paused', {timeout:75000}, async t=>{
  const {page,profile,errors}=await openCourt(t);
  const sourceRoot=path.join(profile,'source'),targetRoot=path.join(profile,'target');
  for(const root of [sourceRoot,targetRoot])fs.mkdirSync(path.join(root,'watched'),{recursive:true});
  const source=path.join(sourceRoot,'original.archhub'),target=path.join(targetRoot,'destination.archhub');
  const watcher={id:'watch',type:'trigger.file',item:'tr_file',title:'Watcher',
    params:{folder:'watched',pattern:'*.txt',debounce_seconds:600,armed:true,ask_before_running:false},
    position:{x:120,y:120}};
  for(const [id,file,nodes] of [['original',source,[watcher]],['destination',target,[]]]){
    fs.writeFileSync(file,JSON.stringify({format:'archhub',version:1,id,title:id,nodes,wires:[],groups:[],
      notes:[],viewport:{x:0,y:0,zoom:1},properties:{viewportSaved:true}}));
  }
  await page.evaluate(async ({source,target})=>{
    const api=window.ArchHubAPI;
    await api.ready;
    await api.openSession(source);
    await api.copyNodes(['watch']);
    await api.openSession(target);
    await api.pasteNodes();
    await api.saveSession();
  },{source,target});
  const original=JSON.parse(fs.readFileSync(source,'utf8')).nodes[0];
  const pasted=JSON.parse(fs.readFileSync(target,'utf8')).nodes[0];
  assert.equal(original.params.armed,true);
  assert.equal(pasted.params.armed,false);
  assert.equal(pasted.params.pattern,original.params.pattern);
  assert.equal(path.resolve(targetRoot,pasted.params.folder),path.join(sourceRoot,'watched'));
  assert.deepEqual(errors,[]);
});

test('DESIGNV22G Canvas behaviours on compiled Studio and real file owners', {timeout:240000}, async t=>{
  const court=await openCourt(t);
  const {page,profile,errors,restart}=court;
  let {server}=court;
  const opened=title=>page.waitForFunction(title=>window.ArchHubAPI.getSessionDocument()?.title===title&&!window.ArchHubAPI.getSnapshot().sessionDirty&&document.querySelector('[role="tab"][aria-selected="true"]')?.textContent===title,title);
  const create=async(name,workspace='')=>{await page.locator('body').press('Control+n');await page.getByRole('textbox',{name:'Task name',exact:true}).fill(name);if(workspace)await page.getByRole('combobox',{name:'Workspace',exact:true}).selectOption(workspace);await page.getByRole('button',{name:'Create and open',exact:true}).click();await page.getByRole('dialog',{name:'New task',exact:true}).waitFor({state:'hidden'});await page.getByRole('tab',{name,exact:true}).waitFor();await page.waitForFunction(title=>window.ArchHubAPI.getSessionDocument()?.title===title&&!window.ArchHubAPI.getSnapshot().sessionDirty,name);};
  const current=()=>page.evaluate(()=>window.ArchHubAPI.getSnapshot().focusedTask);
  let first,second;
  await t.test('New task creates one file with four fixed nodes and never runs on open',async()=>{
    await create('Canvas UI first');first=await current();
    assert.equal(await page.locator('.react-flow').count(),1);
    assert.equal(await page.locator('[data-graph-node][data-fixed]').count(),4);
    assert.equal(await page.locator('[aria-label="Task view"]').count(),0);
    assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().nodes.some(node=>node.result)),false);
    assert.equal(await page.locator('[data-graph-node="start"] [data-node-footer-status]').innerText(),'Idle');
    assert.ok(await page.locator('[data-design="composer.msg"]').isVisible());
    assert.equal(await page.getByRole('button',{name:'Layout',exact:true}).count(),0);
    await page.locator('.react-flow__pane').click({button:'right',position:{x:700,y:520}});
    assert.equal(await page.locator('[data-design="menu.paste-here"]').isDisabled(),true);
    assert.equal(await page.locator('[data-design="menu.paste-here"]').getAttribute('title'),'Copy nodes first.');
    await page.locator('.context-dismiss').click({position:{x:10,y:10}});
    assert.equal(await page.getByRole('tab',{name:'Canvas UI first',exact:true}).getAttribute('data-preview'),'false');
    const profile=page.locator('[data-graph-node="fixed-you"]');
    await profile.getByRole('button',{name:'Parameters',exact:true}).click();
    await profile.getByRole('button',{name:'Fewer',exact:true}).waitFor();
    assert.ok(await profile.getByRole('button',{name:'Settings › You',exact:true}).isVisible());
    await profile.getByRole('button',{name:'Fewer',exact:true}).click();
  });
  await t.test('Legacy view frames without writes; pan and explicit Save restore exact views',async()=>{
    await page.evaluate(()=>window.ArchHubAPI.saveSession());await page.waitForTimeout(400);
    const file=await page.evaluate(()=>window.ArchHubAPI.getSessionPath());
    const legacy=JSON.parse(fs.readFileSync(file,'utf8'));
    delete legacy.properties.viewportSaved;
    legacy.viewport={x:-9000,y:-8000,zoom:1};
    await page.goto('about:blank');await page.waitForTimeout(400);
    fs.writeFileSync(file,JSON.stringify(legacy));
    const before=fs.readFileSync(file),writes=()=>fs.readFileSync(path.join(profile,'writes.jsonl'),'utf8').trim().split('\n').filter(Boolean).map(JSON.parse).filter(p=>path.resolve(p)===path.resolve(file)).length;
    const rendered=()=>page.locator('.react-flow__viewport').evaluate(el=>{const m=new window.DOMMatrix(window.getComputedStyle(el).transform);return {x:m.e,y:m.f,zoom:m.a};});
    const reopen=async()=>{await page.goto(server.url+'/studio');await page.locator('[data-home-page]').waitFor({state:'attached'});await page.getByRole('button',{name:'Open its Canvas',exact:true}).click();await page.locator('.react-flow__viewport').waitFor();await page.waitForTimeout(400);};
    const count=writes();await reopen();
    assert.notDeepEqual(await rendered(),legacy.viewport);
    assert.equal(fs.readFileSync(file).equals(before),true,'Open changed fields: '+JSON.stringify(Object.keys(legacy).filter(key=>JSON.stringify(legacy[key])!==JSON.stringify(JSON.parse(fs.readFileSync(file,'utf8'))[key]))));
    assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().properties.viewportSaved),undefined);
    await page.waitForTimeout(5000);
    assert.equal(fs.readFileSync(file).equals(before),true,'Open changed fields: '+JSON.stringify(Object.keys(legacy).filter(key=>JSON.stringify(legacy[key])!==JSON.stringify(JSON.parse(fs.readFileSync(file,'utf8'))[key]))));assert.equal(writes(),count);
    console.log('PASS legacy viewport: framed on open; bytes unchanged after open and 5s idle; writes=0');
    const framed=await rendered();
    await page.setViewportSize({width:1764,height:949});await page.waitForTimeout(150);
    assert.deepEqual(await rendered(),framed);
    await page.setViewportSize({width:1864,height:949});await page.waitForTimeout(150);
    assert.deepEqual(await rendered(),framed);
    const pane=await page.locator('.react-flow__pane').boundingBox(),x=pane.x+pane.width-100,y=pane.y+100;
    const inputSession=await page.context().newCDPSession(page);
    await inputSession.send('Input.dispatchMouseEvent',{type:'mouseMoved',x,y});
    await inputSession.send('Input.dispatchMouseEvent',{type:'mousePressed',x,y,button:'middle',buttons:4,clickCount:1});
    for(let step=1;step<=8;step++)await inputSession.send('Input.dispatchMouseEvent',{type:'mouseMoved',x:x-90*step/8,y:y+60*step/8,button:'middle',buttons:4});
    await inputSession.send('Input.dispatchMouseEvent',{type:'mouseReleased',x:x-90,y:y+60,button:'middle',buttons:0,clickCount:1});
    await inputSession.detach();
    await page.waitForFunction(()=>window.ArchHubAPI.getSessionDocument().properties.viewportSaved===true&&!window.ArchHubAPI.getSnapshot().sessionDirty);
    const panned=await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().viewport);
    assert.notDeepEqual(panned,framed);
    assert.deepEqual(JSON.parse(fs.readFileSync(file,'utf8')).viewport,panned);
    assert.equal(JSON.parse(fs.readFileSync(file,'utf8')).properties.viewportSaved,true);
    await reopen();assert.deepEqual(await rendered(),panned);
    const settled=writes();await page.waitForTimeout(5000);assert.equal(writes(),settled);
    console.log('PASS user pan: viewport + flag persisted; reopen exact; 5s unchanged idle writes=0');
    await page.evaluate(async()=>{window.ArchHubAPI.setSessionViewport({x:0,y:0,zoom:1});await window.ArchHubAPI.saveSession();});
    assert.equal(JSON.parse(fs.readFileSync(file,'utf8')).properties.viewportSaved,true);
    await reopen();assert.deepEqual(await rendered(),{x:0,y:0,zoom:1});
    console.log('PASS saved origin: {x:0,y:0,zoom:1} + flag restored exactly');
    const fresh=JSON.parse(fs.readFileSync(file,'utf8'));delete fresh.properties.viewportSaved;fresh.viewport=legacy.viewport;await page.goto('about:blank');await page.waitForTimeout(400);fs.writeFileSync(file,JSON.stringify(fresh));
    await reopen();const toSave=await rendered();
    await page.locator('body').press('Control+s');
    await page.waitForFunction(()=>window.ArchHubAPI.getSessionDocument().properties.viewportSaved===true&&!window.ArchHubAPI.getSnapshot().sessionDirty);
    const saved=JSON.parse(fs.readFileSync(file,'utf8'));assert.equal(saved.properties.viewportSaved,true);assert.deepEqual(saved.viewport,toSave);
    await reopen();assert.deepEqual(await rendered(),toSave);
    console.log('PASS explicit Save: untouched legacy framing + flag persisted; reopen exact');
  });
  await t.test('New task Workspace is stored by the real task file owner',async()=>{
    const workspace=path.join(profile,'workspace');fs.mkdirSync(workspace);
    const id=await page.evaluate(async folder=>{await window.ArchHubAPI.addWorkspace({folder});return window.ArchHubAPI.getSnapshot().workspaces.find(row=>row.folder===folder)?.id;},workspace);
    assert.ok(id);await page.locator('[data-design="tab.active"]').dblclick();
    await create('Canvas UI second',id);second=await current();
    assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().properties.taskContext.workspace),id);
  });
  await t.test('Tabs keep open, reorder and restore after server restart',async()=>{
    await page.locator('[data-design="tab.active"]').dblclick();
    const tabs=page.locator('.v22g-tab');assert.equal(await tabs.count(),2);
    await tabs.nth(1).dragTo(tabs.nth(0));
    await page.waitForFunction(async id=>(await window.ArchHubAPI.readCanvasTabs()).canvasTabs.tabs[0].id===id,second);
    await page.goto('about:blank');server=await restart();
    await page.goto(server.url+'/studio?bootstrap='+server.bootstrap);await page.locator('[data-home-page]').waitFor({state:'attached'});
    await page.getByRole('button',{name:/^Canvas UI second/}).click();
    await page.getByRole('button',{name:'Open its Canvas',exact:true}).click();
    await opened('Canvas UI second');
    await page.locator('.v22g-strip').waitFor();
    assert.equal(await page.locator('.v22g-tab').count(),2);
  });
  await t.test('Tab Rename and Show on Home use the existing task owner',async()=>{
    await page.locator('[data-design="tab.active"]').click({button:'right'});
    assert.equal(await page.locator('.context-menu button:not(:disabled)').first().evaluate(el=>document.activeElement===el),true);
    await page.waitForFunction(()=>window.getComputedStyle(document.querySelector('.context-menu button:not(:disabled)')).backgroundColor==='rgb(37, 37, 42)');
    assert.equal(await page.locator('.context-menu button:not(:disabled)').first().evaluate(el=>window.getComputedStyle(el).backgroundColor),'rgb(37, 37, 42)');
    await page.getByRole('button',{name:'Rename',exact:true}).click();
    await page.getByRole('textbox',{name:'Task name',exact:true}).fill('Canvas renamed');
    await page.getByRole('button',{name:'Rename',exact:true}).click();
    await page.getByRole('tab',{name:'Canvas renamed',exact:true}).waitFor();
    await page.locator('[data-design="tab.active"]').click({button:'right'});
    await page.getByRole('button',{name:'Show on Home',exact:true}).click();
    await page.locator('[data-home-page]').waitFor();
    assert.equal(await page.evaluate(id=>window.ArchHubAPI.getSnapshot().tasks.find(row=>row.id===id).homePinned,second),true);
    await page.getByRole('button',{name:'Open its Canvas',exact:true}).click();
    await opened('Canvas renamed');
  });
  await t.test('Plus opens a closed task as a preview and editing keeps it open',async()=>{
    await page.getByRole('button',{name:'Close Canvas UI first',exact:true}).click();
    await page.getByRole('tab',{name:'Canvas UI first',exact:true}).waitFor({state:'detached'});
    await page.getByRole('button',{name:'Open tasks',exact:true}).click();
    await page.getByRole('menu',{name:'Open tasks',exact:true}).getByRole('button',{name:'Canvas UI first',exact:true}).click();
    const tab=page.getByRole('tab',{name:'Canvas UI first',exact:true});
    await page.waitForFunction(()=>window.ArchHubAPI.getSessionDocument()?.title==='Canvas UI first'&&!window.ArchHubAPI.getSnapshot().sessionDirty);
    assert.equal(await tab.getAttribute('data-preview'),'true');
    await page.evaluate(()=>window.ArchHubAPI.addNode('math_expression',{x:450,y:260}));
    await page.waitForFunction(id=>window.ArchHubAPI.readCanvasTabs().then(result=>result.canvasTabs.tabs.find(row=>row.id===id)?.kept),first);
    assert.equal(await tab.getAttribute('data-preview'),'false');
    await page.getByRole('tab',{name:'Canvas renamed',exact:true}).click();
    await opened('Canvas renamed');
  });
  await t.test('Thread split keeps the Canvas and shares one composer draft',async()=>{
    await page.locator('[data-design="composer.msg"]').fill('Unsent draft');
    await page.locator('body').press('Control+\\');
    await page.locator('[data-design="thread.msg"]').waitFor();
    await page.waitForFunction(()=>document.querySelector('[aria-label="Resize the Properties pane"]').getBoundingClientRect().width===1);
    assert.equal(await page.locator('.react-flow').count(),1);
    assert.equal(await page.locator('textarea[aria-label="Message"]').count(),1);
    assert.equal(await page.locator('[data-design="thread.msg"]').inputValue(),'Unsent draft');
    await page.locator('[data-design="thread.rules"]').click();
    assert.equal(await page.locator('[data-design="inspector.selection"]').getAttribute('aria-selected'),'true');
    const rules=page.locator('.shared-properties-selection [data-dx-list="Rules"]');
    await rules.locator('summary').click();
    assert.equal((await page.locator('[aria-label="Resize the Properties pane"]').boundingBox()).width,6);
    await rules.getByRole('button',{name:'+ Add',exact:true}).click();
    await rules.getByRole('textbox',{name:'Rules 1',exact:true}).fill('Keep the entrance reference with this task.');
    await rules.getByRole('textbox',{name:'Rules 1',exact:true}).press('Tab');
    await page.waitForFunction(()=>window.ArchHubAPI.getSessionDocument().nodes.find(node=>node.id==='fixed-workshop').result?.output?.rules?.includes('Keep the entrance reference with this task.'));
    assert.equal(await page.locator('[data-node-inspector="fixed-workshop"]').getByText('Inputs',{exact:true}).count(),1);
    await page.getByRole('button',{name:'Close thread',exact:true}).click();
    assert.equal(await page.locator('[data-design="composer.msg"]').inputValue(),'Unsent draft');
  });
  await t.test('Meeting notes attach to the thread and Pin persists',async()=>{
    await page.getByRole('button',{name:'Attach',exact:true}).click();
    await page.getByRole('button',{name:'Meeting notes',exact:true}).click();
    await page.getByRole('textbox',{name:'Meeting notes',exact:true}).fill('Reviewed north entrance at the real meeting.');
    await page.getByRole('button',{name:'Attach to thread',exact:true}).click();
    await page.locator('body').press('Control+\\');
    const message=page.locator('[data-design="thread.message"]').filter({hasText:'Reviewed north entrance at the real meeting.'});
    await message.waitFor();await message.click({button:'right'});
    assert.equal(await page.evaluate(()=>document.activeElement.textContent.trim()),'Copy text');
    await page.getByRole('button',{name:'Copy text',exact:true}).press('ArrowDown');
    assert.equal(await page.evaluate(()=>document.activeElement.textContent.trim()),'Reply');
    await page.getByRole('menu',{name:'Task message menu',exact:true}).getByRole('button',{name:'Reply',exact:true}).press('ArrowDown');
    assert.equal(await page.evaluate(()=>document.activeElement.textContent.trim()),'Make a task from this');
    assert.equal(await page.getByRole('button',{name:'Show on canvas',exact:true}).isDisabled(),true);
    assert.equal(await page.getByRole('button',{name:'Show on canvas',exact:true}).getAttribute('title'),'This message names no node on this canvas.');
    await page.getByRole('button',{name:'Pin to the task',exact:true}).click();
    await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().tasks.some(task=>task.pinnedMessages?.length===1));
    assert.equal(await message.getAttribute('data-pinned'),'true');
    await page.getByRole('button',{name:'Close thread',exact:true}).click();
  });
  await t.test('Pinned-node collapse changes view metadata and retains all four nodes',async()=>{
    await page.getByRole('button',{name:'On every canvas · Collapse',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('[data-graph-node][data-fixed]').length===1);
    assert.equal(await page.locator('[data-graph-node][data-fixed]').count(),1);
    assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().nodes.filter(node=>node.fixed).length),4);
    await page.getByRole('button',{name:'On every canvas · Expand',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('[data-graph-node][data-fixed]').length===4);
    assert.equal(await page.locator('[data-graph-node][data-fixed]').count(),4);
  });
  await t.test('Open beside reads a different task file and keeps the active file selected',async()=>{
    await page.getByRole('tab',{name:'Canvas UI first',exact:true}).click({button:'right'});
    await page.getByRole('button',{name:'Open beside',exact:true}).click();
    await page.getByRole('menu',{name:'Task tab menu',exact:true}).waitFor({state:'hidden',timeout:30000}).catch(async error=>{console.log('Tab action refusal: '+await page.getByRole('menu',{name:'Task tab menu',exact:true}).innerText());throw error;});
    await page.locator('.v22g-beside .react-flow').waitFor();
    assert.equal(await page.locator('.react-flow').count(),2);
    assert.equal(await current(),second);
    await page.getByRole('button',{name:'Thread',exact:true}).click();
    for(const size of [{width:900,height:700},{width:1009,height:940}]){
      await page.setViewportSize(size);await page.waitForTimeout(250);
      const panes=await page.locator('.v22g-views > [data-panel]').evaluateAll(elements=>elements.map(el=>({id:el.id,width:el.getBoundingClientRect().width})));
      for(const pane of panes.filter(pane=>!pane.id.includes('thread')))assert.ok(pane.width>=319,JSON.stringify({size,panes}));
      const toggle=page.getByRole('group',{name:'Visible canvas',exact:true});
      if(await toggle.count()){
        assert.equal(await page.locator('.react-flow').count(),1);
        await toggle.getByRole('button',{name:'Canvas UI first',exact:true}).click();
        await page.locator('.v22g-beside .react-flow').waitFor();
        assert.equal(await page.locator('.react-flow').count(),1);
        await toggle.getByRole('button',{name:'Canvas renamed',exact:true}).click();
        await page.locator('.v22g-canvas .react-flow').waitFor();
      }else assert.equal(await page.locator('.react-flow').count(),2);
      console.log(`PASS side-by-side ${size.width}x${size.height}: canvas minimums preserved; visible switch when collapsed`);
    }
    await page.setViewportSize({width:900,height:700});
    await page.getByRole('group',{name:'Visible canvas',exact:true}).waitFor();
    await page.getByRole('button',{name:'More canvas actions',exact:true}).click();
    await page.getByRole('menuitem',{name:'Thread',exact:true}).click();
    await page.setViewportSize({width:1864,height:949});
    await page.getByRole('button',{name:'Close split',exact:true}).click();
  });
  await t.test('Canvas selection, pointer capture, wheel zoom, middle pan, wiring and keyboard stay live',async()=>{
    // Existing designbuild.cjs input path: this private headless page, never the desktop pointer.
    const inputSession=await page.context().newCDPSession(page);
    const pointer=(type,x,y,pressed=false,button='left')=>inputSession.send('Input.dispatchMouseEvent',{type,x,y,...(type==='mouseMoved'?pressed?{button,buttons:button==='middle'?4:1}:{}:{button,buttons:pressed?button==='middle'?4:1:0,clickCount:1})});
    const id=await page.evaluate(async()=>{const node=await window.ArchHubAPI.addNode('math_expression',{x:450,y:260});return node.id;});
    await page.getByRole('button',{name:'Fit',exact:true}).click();
    const node=page.locator('[data-graph-node="'+id+'"]'),header=node.locator('.node-header');
    await header.click();
    assert.equal(await page.locator('.react-flow__node.selected').count(),1);
    const before=await page.evaluate(id=>window.ArchHubAPI.getSessionDocument().nodes.find(n=>n.id===id).position,id);
    const box=await header.boundingBox();
    // The captured drag ends beyond its title bar; the saved position proves delivery.
    const x=box.x+box.width/2,y=box.y+box.height/2;
    await pointer('mouseMoved',x,y);await pointer('mousePressed',x,y,true);
    for(let step=1;step<=12;step++)await pointer('mouseMoved',x+65*step/12,y+35*step/12,true);
    await pointer('mouseReleased',x+65,y+35);
    await page.waitForFunction(({id,before})=>window.ArchHubAPI.getSessionDocument().nodes.find(n=>n.id===id).position.x>before.x+10,{id,before});
    const pane=page.locator('.react-flow__pane'),bounds=await pane.boundingBox();
    const viewport=()=>page.evaluate(()=>window.ArchHubAPI.getSessionDocument().viewport);
    const initial=await viewport();
    await inputSession.send('Input.dispatchMouseEvent',{type:'mouseWheel',x:bounds.x+bounds.width-50,y:bounds.y+150,deltaX:0,deltaY:-140});
    await page.waitForFunction(zoom=>window.ArchHubAPI.getSessionDocument().viewport.zoom>zoom,initial.zoom);
    await page.waitForFunction(()=>!window.ArchHubAPI.getSnapshot().sessionDirty);
    const zoomed=await viewport();
    const empty=await pane.evaluate(el=>{const r=el.getBoundingClientRect();for(let y=r.y+120;y<r.bottom-100;y+=50)for(let x=r.x+120;x<r.right-120;x+=50)if(document.elementFromPoint(x,y)?.classList.contains('react-flow__pane'))return {x:x-r.x,y:y-r.y};return null;});
    assert.ok(empty,'The real Canvas has a clear pan surface');
    const px=bounds.x+empty.x,py=bounds.y+empty.y;
    await pointer('mouseMoved',px,py);await pointer('mousePressed',px,py,true,'middle');
    for(let step=1;step<=8;step++)await pointer('mouseMoved',px+50*step/8,py+40*step/8,true,'middle');
    await pointer('mouseReleased',px+50,py+40,false,'middle');
    await page.waitForFunction(x=>window.ArchHubAPI.getSessionDocument().viewport.x!==x,zoomed.x);
    await page.getByRole('button',{name:'Fit',exact:true}).click();
    const from=page.locator('.react-flow__handle.source[data-nodeid="start"][data-handleid="value"]');
    const to=page.locator('.react-flow__handle.target[data-nodeid="'+id+'"][data-handleid="param:a"]');
    if(!await to.count())await node.getByRole('button',{name:'Parameters',exact:true}).click();
    await from.dragTo(to);
    await page.waitForFunction(id=>window.ArchHubAPI.getSessionDocument().wires.some(w=>w.from.node==='start'&&w.to.node===id),id);
    await page.locator('body').press('Control+a');
    await page.waitForFunction(()=>document.querySelectorAll('.react-flow__node.selected').length>1);
    assert.ok(await page.locator('.react-flow__node.selected').count()>1);
    await page.locator('body').press('Escape');
    await page.waitForFunction(()=>document.querySelectorAll('.react-flow__node.selected').length===0);
    assert.equal(await page.locator('.react-flow__node.selected').count(),0);
    assert.ok(await page.locator('[data-design="toolbar.run"]').isVisible());
  });
  await t.test('Canvas Run keeps the task open and reports its actual node results',async()=>{
    let release;
    const held=new Promise(resolve=>{release=resolve;});
    const holdRun=async route=>{if(route.request().postDataJSON()?.action==='run')await held;await route.continue();};
    await page.route('**/api/session-files',holdRun);
    try{
      await page.locator('[data-design="toolbar.run"]').click();
      await page.locator('[data-design="node.running"]').first().waitFor();
      await page.waitForTimeout(1500);
      assert.ok(await page.locator('[data-design="node.running"]').count()>0,'Running survives the solve and file-poll interval');
    }finally{release();await page.unrouteAll({behavior:'wait'});}
    await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().lastResult?.rows.length>0&&!window.ArchHubAPI.getSnapshot().graph.nodes.some(node=>node.status==='Running')).catch(async error=>{console.log('Canvas Run readback: '+JSON.stringify(await page.evaluate(()=>({nodes:window.ArchHubAPI.getSnapshot().graph.nodes.map(node=>({title:node.title,status:node.status,error:node.error})),result:window.ArchHubAPI.getSnapshot().lastResult,text:document.body.innerText.slice(-1200)}))));throw error;});
    assert.equal(await page.getByRole('dialog').count(),0);
    assert.ok(await page.locator('[data-design="composer.msg"]').isVisible());
    assert.ok(await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().nodes.every(node=>['Done','Error','Blocked'].includes(node.result?.status))));
  });
  await t.test('A real Canvas gate waits, appears in Bell and resumes through one Approve card',async()=>{
    await page.evaluate(()=>window.ArchHubAPI.addNode('g_approval_gate',{x:500,y:200}));
    await page.locator('[data-design="toolbar.run"]').click();
    await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().graph.nodes.some(node=>node.status==='Waiting for approval'));
    await page.locator('[data-design="approval.panel"]').waitFor();
    await page.locator('body').press('Escape');
    await page.getByRole('button',{name:'Notifications',exact:true}).click();
    await page.locator('[role="dialog"][aria-label="Notifications"] .listbutton').first().click();
    await page.locator('[data-design="approval.panel"]').waitFor();
    await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().notifications.some(row=>row.read));
    await page.locator('body').press('Escape');
    await page.getByRole('button',{name:'Review',exact:true}).click();
    assert.equal(await page.locator('[data-design="approval.panel"]').count(),1);
    await page.getByRole('button',{name:'Approve',exact:true}).click();
    await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().graph.nodes.some(node=>node.type==='approval.gate'&&node.status==='Done'));
    await page.locator('body').press('Escape');
    await page.getByRole('button',{name:'Notifications',exact:true}).click();
    assert.equal(await page.locator('[role="dialog"][aria-label="Notifications"]').count(),1);
  });
  await t.test('Dropping another task creates one linked node and Detach copies explicitly',async()=>{
    await page.locator('body').press('Escape');
    const source=await page.evaluate(id=>window.ArchHubAPI.getSnapshot().tasks.find(task=>task.id===id).sessionPath,first);
    const original=fs.readFileSync(source,'utf8');
    const before=await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().nodes.length);
    const transfer=await page.evaluateHandle(()=>new window.DataTransfer());
    await page.getByRole('tab',{name:'Canvas UI first',exact:true}).locator('..').dispatchEvent('dragstart',{dataTransfer:transfer});
    await page.locator('[aria-label="Workflow canvas"]').dispatchEvent('drop',{dataTransfer:transfer,clientX:650,clientY:400});
    await transfer.dispose();
    await page.waitForFunction(source=>window.ArchHubAPI.getSessionDocument().nodes.some(node=>node.params.session_file===source),source);
    assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().nodes.length),before+1);
    const id=await page.evaluate(source=>window.ArchHubAPI.getSessionDocument().nodes.find(node=>node.params.session_file===source).id,source);
    await page.getByRole('button',{name:'Fit',exact:true}).click();
    await page.locator('[data-graph-node="'+id+'"] .node-header').click();
    await page.locator('[data-design="toolbar.more"]').click();
    await page.getByRole('menuitem',{name:'Detach session (copy)',exact:true}).click();
    await page.waitForFunction(({id,source})=>window.ArchHubAPI.getSessionDocument().nodes.find(node=>node.id===id).params.session_file!==source,{id,source});
    const detached=await page.evaluate(id=>window.ArchHubAPI.getSessionDocument().nodes.find(node=>node.id===id).params.session_file,id);
    assert.equal(fs.readFileSync(source,'utf8'),original);
    assert.deepEqual(JSON.parse(fs.readFileSync(detached,'utf8')).nodes,JSON.parse(original).nodes);
    assert.notEqual(JSON.parse(fs.readFileSync(detached,'utf8')).id,JSON.parse(original).id);
    assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().nodes.length),before+1);
  });
  await t.test('Ungroup keeps both members, their wire and positions; group and ungroup each undo once',async()=>{
    await create('Group safety');
    const ids=await page.evaluate(async()=>{
      const a=await window.ArchHubAPI.addNode('math_expression',{x:420,y:200});
      const b=await window.ArchHubAPI.addNode('math_expression',{x:760,y:200});
      await window.ArchHubAPI.connectSockets({from:a.id,fromPort:'value',to:b.id,toPort:'param:a'});
      return [a.id,b.id];
    });
    await page.getByRole('button',{name:'Fit',exact:true}).click();
    await page.locator('[data-graph-node="'+ids[0]+'"] .node-header').click();
    await page.locator('[data-graph-node="'+ids[1]+'"] .node-header').click({modifiers:['Shift']});
    const original=await page.evaluate(()=>window.ArchHubAPI.getSessionDocument());
    await page.locator('body').press('Control+g');
    await page.waitForFunction(()=>window.ArchHubAPI.getSessionDocument().groups.length===1);
    const group=await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().groups[0].id);
    await page.locator('body').press('Control+z');
    await page.waitForFunction(()=>window.ArchHubAPI.getSessionDocument().groups.length===0);
    const authoring=nodes=>nodes.map(({result,...node})=>node).sort((a,b)=>a.id.localeCompare(b.id));
    assert.deepEqual(authoring(await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().nodes)),authoring(original.nodes));
    await page.locator('body').press('Control+Shift+z');
    await page.waitForFunction(()=>window.ArchHubAPI.getSessionDocument().groups.length===1);
    await page.getByRole('button',{name:'Fit',exact:true}).click();
    await page.locator('[data-graph-node="'+group+'"] .canvas-node-menu').click();
    await page.getByRole('button',{name:'Ungroup',exact:true}).click();
    await page.waitForFunction(()=>window.ArchHubAPI.getSessionDocument().groups.length===0);
    await page.evaluate(()=>window.ArchHubAPI.saveSession());
    assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().groups.length),0);
    const ungrouped=await page.evaluate(()=>window.ArchHubAPI.getSessionDocument());
    assert.deepEqual(authoring(ungrouped.nodes),authoring(original.nodes));
    assert.deepEqual(ungrouped.wires,original.wires);
    await page.locator('body').press('Control+z');
    await page.waitForFunction(()=>window.ArchHubAPI.getSessionDocument().groups.length===1);
  });
  let scriptId,stepIds;
  await t.test('Shift A places a real Script; its Inspector edits typed inputs, outputs and executable code',async()=>{
    await create('Group b owners');
    await page.locator('body').press('Shift+A');
    await page.getByRole('textbox',{name:'Add node',exact:true}).fill('Script');
    await page.getByRole('dialog',{name:'Add node',exact:true}).getByRole('button',{name:'Script',exact:true}).click();
    await page.locator('[data-design="script.code"]').waitFor();
    scriptId=await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().nodes.find(n=>n.type==='script.python').id);
    await page.locator('[data-design="script.addin"]').click();
    await page.getByRole('combobox',{name:'Type of a',exact:true}).selectOption('number');
    await page.getByRole('combobox',{name:'Type of b',exact:true}).selectOption('number');
    await page.getByRole('combobox',{name:'Type of result',exact:true}).selectOption('number');
    await page.locator('[data-design="script.code"]').fill('def run(a, b):\n    return {"result": a + b}\n');
    await page.locator('[data-design="script.code"]').press('Tab');
    await page.waitForFunction(id=>window.ArchHubAPI.getSessionDocument().nodes.find(n=>n.id===id).params.code.includes('a + b'),scriptId);
    await page.evaluate(async id=>{await window.ArchHubAPI.setNodeParam(id,'a',4);await window.ArchHubAPI.setNodeParam(id,'b',5);},scriptId);
    await page.locator('[data-design="toolbar.run"]').click();
    await page.waitForFunction(id=>window.ArchHubAPI.getSessionDocument().nodes.find(n=>n.id===id).result?.output?.result===9,scriptId);
    assert.deepEqual(await page.evaluate(id=>Object.fromEntries(Object.entries(window.ArchHubAPI.getSessionDocument().nodes.find(n=>n.id===id).ports).map(([side,ports])=>[side,ports.map(({id,type})=>({id,type}))])),scriptId),{source:[{id:'result',type:'number'}],target:[{id:'a',type:'number'},{id:'b',type:'number'}]});
  });
  await t.test('Script Effect edits do not execute; Run stops at one Approve card and resumes',async()=>{
    await page.getByRole('group',{name:'Pure or effect',exact:true}).getByRole('button',{name:'Effect',exact:true}).click();
    await page.waitForFunction(id=>window.ArchHubAPI.getSessionDocument().nodes.find(n=>n.id===id).pure===false,scriptId);
    await page.locator('[data-design="toolbar.run"]').click();
    await page.getByRole('button',{name:'Review',exact:true}).waitFor();
    await page.getByRole('button',{name:'Review',exact:true}).click();
    assert.equal(await page.locator('[data-design="approval.panel"]').count(),1);
    assert.equal(Math.round((await page.locator('[data-design="approval.panel"]').boundingBox()).height),324);
    await page.getByRole('button',{name:'Approve',exact:true}).click();
    await page.waitForFunction(id=>window.ArchHubAPI.getSessionDocument().nodes.find(n=>n.id===id).result?.output?.result===9,scriptId).catch(async()=>{throw Error('Approved script readback '+JSON.stringify(await page.evaluate(id=>({node:window.ArchHubAPI.getSessionDocument().nodes.find(n=>n.id===id),approvals:window.ArchHubAPI.getSnapshot().approvals.map(c=>({status:c.status,error:c.error}))}),scriptId)));});
    await page.locator('body').press('Escape');
  });
  await t.test('Save as node type scans, preserves the task and creates a real reusable Library file',async()=>{
    let refusedScan=false;
    const scanRoute=async route=>{if(route.request().postDataJSON()?.action==='scan-node-type'&&!refusedScan){refusedScan=true;await route.fulfill({status:503,json:{error:'Scan temporarily unavailable'}});}else await route.continue();};
    await page.route('**/api/session-files',scanRoute);
    await page.locator('[data-design="script.savetype"]').click();
    await page.getByRole('button',{name:'Retry check',exact:true}).click();
    await page.getByRole('status').filter({hasText:'No embedded credentials detected.'}).waitFor();
    await page.unroute('**/api/session-files',scanRoute);
    await page.getByRole('textbox',{name:'Node type name',exact:true}).fill('Reusable add');
    await page.getByRole('combobox',{name:'Category',exact:true}).selectOption('Checks');
    await page.getByRole('dialog',{name:'Save as node type',exact:true}).getByRole('button',{name:'Save',exact:true}).click();
    await page.getByRole('dialog',{name:'Save as node type',exact:true}).waitFor({state:'hidden'});
    const item=await page.evaluate(()=>window.ArchHubAPI.getSnapshot().libraryPorts.find(n=>n.title==='Reusable add'));
    assert.ok(item);assert.equal(item.cat,'Checks');assert.equal(item.engine,'skill');
    const saved=JSON.parse(fs.readFileSync(item.path,'utf8'));
    assert.equal(saved.nodes.length,1);assert.equal(saved.nodes[0].id,scriptId);assert.equal(saved.properties.taskContext,undefined);
    assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().title),'Group b owners');
  });
  await t.test('Add parameter supports Choice and an exposed typed parameter on a step',async()=>{
    const id=await page.evaluate(async()=>{const n=await window.ArchHubAPI.addNode('math_expression',{x:760,y:300});return n.id;});
    stepIds=[id];await page.getByRole('button',{name:'Fit',exact:true}).click();
    await page.locator('[data-graph-node="'+id+'"] .node-header').click({button:'right'});
    await page.getByRole('button',{name:'Add parameter',exact:true}).click();
    const form=page.getByRole('dialog',{name:'Add parameter',exact:true});
    await form.getByRole('textbox',{name:'Parameter name',exact:true}).fill('Finish');
    await form.getByRole('combobox',{name:'Parameter type',exact:true}).selectOption('Choice');
    await form.getByRole('textbox',{name:'Parameter options',exact:true}).fill('Brick, Stone');
    await form.getByRole('checkbox',{name:'Show as node',exact:true}).check();
    await form.getByRole('button',{name:'Add parameter',exact:true}).click();
    await form.waitFor({state:'hidden'});
    await page.waitForFunction(id=>window.ArchHubAPI.getSessionDocument().nodes.some(n=>n.bind?.node===id&&n.bind.param==='finish'),id);
    assert.equal(await page.evaluate(id=>window.ArchHubAPI.getSessionDocument().nodes.find(n=>n.id===id).params.finish,id),'Brick');
  });
  await t.test('Add parameter on the agent session persists a typed socket and undoes once',async()=>{
    await page.locator('[data-graph-node="start"] .node-header').click({button:'right'});
    await page.getByRole('button',{name:'Add parameter',exact:true}).click();
    const form=page.getByRole('dialog',{name:'Add parameter',exact:true});
    await form.getByRole('textbox',{name:'Parameter name',exact:true}).fill('Review limit');
    await form.getByRole('spinbutton',{name:'Parameter value',exact:true}).fill('3');
    await form.getByRole('button',{name:'Add parameter',exact:true}).click();
    await form.waitFor({state:'hidden'});
    await page.evaluate(()=>window.ArchHubAPI.saveSession());
    assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().nodes.find(n=>n.id==='start').params.review_limit),3);
    assert.ok(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.nodes.find(n=>n.id==='start').inputs.some(p=>p.id==='param:review_limit'&&p.type==='number')));
    await page.locator('body').press('Control+z');
    await page.waitForFunction(()=>!Object.hasOwn(window.ArchHubAPI.getSessionDocument().nodes.find(n=>n.id==='start').params,'review_limit'));
  });
  await t.test('Canvas note, Find and Rename write the current document and undo once',async()=>{
    await page.locator('body').press('n');
    await page.getByRole('textbox',{name:'Note',exact:true}).fill('A real drawing note');
    await page.getByRole('dialog',{name:'Note',exact:true}).getByRole('button',{name:'Save',exact:true}).click();
    await page.locator('body').press('Control+f');
    await page.getByRole('textbox',{name:'Find a node',exact:true}).fill('Note');
    await page.getByRole('dialog',{name:'Find node',exact:true}).getByRole('button',{name:'Note',exact:true}).click();
    await page.locator('body').press('F2');
    await page.getByRole('textbox',{name:'Node name',exact:true}).fill('Drawing note');
    await page.getByRole('button',{name:'Rename',exact:true}).click();
    await page.waitForFunction(()=>window.ArchHubAPI.getSessionDocument().nodes.some(n=>n.title==='Drawing note'&&n.params.text==='A real drawing note'));
    await page.locator('body').press('Control+z');
    await page.waitForFunction(()=>window.ArchHubAPI.getSessionDocument().nodes.some(n=>n.title==='Note'&&n.params.text==='A real drawing note'));
  });
  let editable,wireId;
  await t.test('Ctrl+G makes one collapsed group; it enters both ways, expands and collapses in place, and ungroups without losing members',async()=>{
    await create('Group b navigation');
    editable=await page.evaluate(async()=>{const a=await window.ArchHubAPI.addNode('math_expression',{x:420,y:240}),b=await window.ArchHubAPI.addNode('math_expression',{x:760,y:240});await window.ArchHubAPI.setNodeParam(a.id,'expression','7');await window.ArchHubAPI.setNodeParam(b.id,'expression','a + 1');await window.ArchHubAPI.connectSockets({from:a.id,fromPort:'value',to:b.id,toPort:'a'});return [a.id,b.id];});
    wireId=await page.evaluate(ids=>window.ArchHubAPI.getSessionDocument().wires.find(w=>w.from.node===ids[0]&&w.to.node===ids[1]).id,editable);
    await page.getByRole('button',{name:'Fit',exact:true}).click();
    await page.locator('[data-graph-node="'+editable[0]+'"] .node-header').click();
    await page.locator('[data-graph-node="'+editable[1]+'"] .node-header').click({modifiers:['Control']});
    await page.locator('body').press('Control+g');
    const collapsed = page.locator('[data-design="group.node"]'),frame=page.locator('[data-design="group.frame"]');
    await collapsed.waitFor();
    assert.equal(await frame.count(),0,'the new group is one node, not a frame');
    const expectedSockets=await page.evaluate(ids=>window.ArchHubAPI.getSnapshot().graph.nodes.filter(n=>ids.includes(n.id))
      .flatMap(n=>[['in',n.inputs],['out',n.outputs]].flatMap(([side,ports])=>ports.map(p=>[side+':'+n.id+':'+p.id,p.type])))
      .sort(),editable);
    assert.ok(expectedSockets.length>2);
    const visibleSockets=await collapsed.locator('[data-port-key]').evaluateAll(ports=>ports
      .map(p=>[p.dataset.portKey.split(':').slice(2).join(':'),p.dataset.portType]).sort());
    assert.deepEqual(visibleSockets,expectedSockets);
    assert.equal(await page.locator('[data-graph-node="'+editable[0]+'"]').count(),0);
    await page.locator('[data-design="group.open"]').click();
    await page.locator('[data-design="group.back"]').waitFor();
    await page.locator('[data-graph-node="'+editable[0]+'"]').waitFor();
    assert.equal(await page.locator('[data-graph-node="'+editable[0]+'"]').count(),1);
    await page.locator('body').press('Escape');
    await page.locator('[data-design="group.node"]').waitFor();
    // Expand in place: the frame sits around its members and the wire between them is still drawn.
    await page.locator('[data-design="group.node"] .node-header').click({button:'right'});
    await page.getByRole('button',{name:'Expand',exact:true}).click();
    await frame.waitFor();
    const [outer,...inner]=await Promise.all([frame,...editable.map(id=>page.locator('[data-graph-node="'+id+'"]'))].map(box=>box.boundingBox()));
    for(const box of inner)assert.ok(box.x>=outer.x&&box.y>=outer.y&&box.x+box.width<=outer.x+outer.width&&box.y+box.height<=outer.y+outer.height,'the frame sits around its members '+JSON.stringify({outer,box}));
    assert.equal(await page.locator('.react-flow__edge[data-id="'+wireId+'"]').count(),1,'the member wire stays drawn while the group is expanded');
    // The frame border takes the pointer: a double-click on it enters, Escape leaves, and Enter on the selected group enters again.
    await page.locator('body').dblclick({position:{x:outer.x+1,y:outer.y+outer.height/2}});
    await page.locator('[data-design="group.back"]').waitFor();
    await page.locator('body').press('Escape');
    await frame.waitFor();
    const groupId=await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().groups[0].id);
    // Its own socket reads the wire through the member it stands for.
    await page.locator('[data-node-inspector="'+groupId+'"] [data-linked-source]').first().waitFor({state:'attached'});
    assert.equal(await page.locator('[data-node-inspector="'+groupId+'"] [data-linked-source]').count(),1);
    await page.locator('.node-canvas').press('Enter');
    await page.locator('[data-design="group.back"]').waitFor();
    await page.locator('body').press('Escape');
    await frame.waitFor();
    await page.locator('[data-design="group.collapse"]').click();
    await page.locator('[data-design="group.node"]').waitFor();
    assert.equal(await frame.count(),0,'collapse happens in place');
    await page.locator('[data-design="group.node"] .node-header').click({button:'right'});
    await page.getByRole('button',{name:'Ungroup',exact:true}).click();
    await page.waitForFunction(()=>window.ArchHubAPI.getSessionDocument().groups.length===0);
    assert.equal(await page.evaluate(ids=>ids.every(id=>window.ArchHubAPI.getSessionDocument().nodes.some(n=>n.id===id)),editable),true);
  });
  await t.test('Window drag, Ctrl+G, then a double-click enters the group: no selection box is left over it',async()=>{
    await page.getByRole('button',{name:'Fit',exact:true}).click();
    // A selection window from empty canvas around both nodes, by real pointer input on this headless page only.
    const boxes=await Promise.all(editable.map(id=>page.locator('[data-graph-node="'+id+'"]').boundingBox()));
    const a={x:Math.min(...boxes.map(b=>b.x))-12,y:Math.min(...boxes.map(b=>b.y))-12},b={x:Math.max(...boxes.map(b=>b.x+b.width))+12,y:Math.max(...boxes.map(b=>b.y+b.height))+12};
    const input=await page.context().newCDPSession(page);
    await input.send('Input.dispatchMouseEvent',{type:'mouseMoved',x:a.x,y:a.y});
    await input.send('Input.dispatchMouseEvent',{type:'mousePressed',x:a.x,y:a.y,button:'left',buttons:1,clickCount:1});
    for(let step=1;step<=8;step++)await input.send('Input.dispatchMouseEvent',{type:'mouseMoved',x:a.x+(b.x-a.x)*step/8,y:a.y+(b.y-a.y)*step/8,button:'left',buttons:1});
    await input.send('Input.dispatchMouseEvent',{type:'mouseReleased',x:b.x,y:b.y,button:'left',buttons:0,clickCount:1});
    await input.detach();
    await page.waitForFunction(ids=>ids.every(id=>window.getComputedStyle(document.querySelector('[data-graph-node="'+id+'"] [data-ds-node]')).outlineStyle==='solid'),editable);
    await page.locator('body').press('Control+g');
    const header=page.locator('[data-design="group.node"] .node-header');
    await header.waitFor();
    assert.equal(await page.locator('.react-flow__nodesselection-rect').isVisible(),false,'the selection box is gone once the new group is the selection');
    const hit=await header.evaluate(el=>{const r=el.getBoundingClientRect(),top=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return !!top&&el.contains(top);});
    assert.equal(hit,true,'the group header is what the pointer reaches');
    await header.dblclick();
    await page.locator('[data-design="group.back"]').waitFor();
    await page.locator('body').press('Escape');
    await page.locator('[data-design="group.node"]').waitFor();
    await page.locator('body').press('Control+Shift+g');
    await page.waitForFunction(()=>window.ArchHubAPI.getSessionDocument().groups.length===0);
  });
  await t.test('One Group action holds a single node; Ungroup keeps its contents and undo restores it',async()=>{
    await page.getByRole('button',{name:'Fit',exact:true}).click();
    await page.locator('[data-graph-node="'+editable[0]+'"] .node-header').click();
    await page.locator('body').press('Control+Alt+g');
    await page.waitForFunction(id=>window.ArchHubAPI.getSessionDocument().nodes.some(n=>n.children?.length===1&&n.children[0]===id),editable[0]);
    const header=page.locator('[data-design="group.node"] .node-header');
    await header.waitFor();
    await header.click({button:'right'});
    await page.getByRole('button',{name:'Ungroup',exact:true}).click();
    assert.equal(await page.evaluate(id=>window.ArchHubAPI.getSessionDocument().nodes.some(n=>n.id===id),editable[0]),true);
    await page.locator('body').press('Control+z');
    await header.waitFor();
    await page.locator('body').press('Control+Shift+z');
    await header.waitFor({state:'detached'});
  });
  const wireMenu=async()=>{const point=await page.locator('.react-flow__edge[data-id="'+wireId+'"] path.react-flow__edge-interaction').evaluate(el=>{const p=el.getPointAtLength(el.getTotalLength()/2),m=el.getScreenCTM();return {x:p.x*m.a+m.e,y:p.y*m.d+m.f};});await page.locator('body').click({position:point,button:'right'});await page.getByRole('menu',{name:'Wire menu',exact:true}).waitFor();};
  await t.test('Wire rule and Enable/Disable change actual Run; Insert Convert is one undo step',async()=>{
    await page.getByRole('button',{name:'Fit',exact:true}).click();
    await wireMenu();await page.getByRole('button',{name:'Add rule',exact:true}).click();
    await page.getByRole('textbox',{name:'Only pass values when',exact:true}).fill('value > 0');
    await page.getByRole('dialog',{name:'Wire rule',exact:true}).getByRole('button',{name:'Save',exact:true}).click();
    await page.waitForFunction(id=>window.ArchHubAPI.getSessionDocument().wires.find(w=>w.id===id).rule==='value > 0',wireId);
    await wireMenu();await page.getByRole('button',{name:'Disable',exact:true}).click();
    await page.locator('[data-design="toolbar.run"]').click();
    await page.waitForFunction(id=>window.ArchHubAPI.getSessionDocument().nodes.find(n=>n.id===id).result?.output?.value===1,editable[1]).catch(async()=>{throw Error('Disabled wire result '+JSON.stringify(await page.evaluate(id=>({node:window.ArchHubAPI.getSessionDocument().nodes.find(n=>n.id===id),wires:window.ArchHubAPI.getSessionDocument().wires}),editable[1])));});
    await wireMenu();await page.getByRole('button',{name:'Enable',exact:true}).click();
    await page.locator('[data-design="toolbar.run"]').click();
    await page.waitForFunction(id=>window.ArchHubAPI.getSessionDocument().nodes.find(n=>n.id===id).result?.output?.value===8,editable[1]);
    await wireMenu();await page.getByRole('button',{name:'Insert Convert',exact:true}).click();
    await page.waitForFunction(()=>window.ArchHubAPI.getSessionDocument().nodes.some(n=>n.type==='data.convert'));
    await page.locator('body').press('Control+z');
    await page.waitForFunction(id=>window.ArchHubAPI.getSessionDocument().wires.some(w=>w.id===id)&&!window.ArchHubAPI.getSessionDocument().nodes.some(n=>n.type==='data.convert'),wireId);
  });
  await t.test('More/Back, Copy, Paste and Duplicate use real nodes and one undo each',async()=>{
    await page.locator('[data-graph-node="'+editable[0]+'"] .node-header').click({button:'right'});
    await page.getByRole('button',{name:'More',exact:true}).click();
    await page.getByRole('button',{name:'Back',exact:true}).click();
    await page.locator('[data-design="menu.copy"]').click();
    const count=await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().nodes.length);
    await page.locator('body').press('Control+v');
    await page.waitForFunction(count=>window.ArchHubAPI.getSessionDocument().nodes.length===count+1,count);
    await page.locator('body').press('Control+z');
    await page.waitForFunction(count=>window.ArchHubAPI.getSessionDocument().nodes.length===count,count);
    await page.locator('body').press('Control+d');
    await page.waitForFunction(count=>window.ArchHubAPI.getSessionDocument().nodes.length===count+1,count);
    await page.locator('body').press('Control+z');
    await page.waitForFunction(count=>window.ArchHubAPI.getSessionDocument().nodes.length===count,count);
  });
  await t.test('Save acknowledgements reconcile concurrent view and title without losing in-flight edits',async()=>{
    const file=path.join(profile,'concurrent.archhub');
    await page.evaluate(async file=>{const api=window.ArchHubAPI,d=api.getSessionDocument();delete d.properties.taskContext;d.id=window.crypto.randomUUID();const text=JSON.stringify(d);await api.importSession(new File([text],'concurrent.archhub'));await api.saveSession(file,true);},file);
    await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Canvas',exact:true}).click();
    const rendered=()=>page.locator('.react-flow__viewport').evaluate(el=>{const m=new window.DOMMatrix(window.getComputedStyle(el).transform);return {x:m.e,y:m.f,zoom:m.a};});
    for(const mirror of [false,true]){
      await page.evaluate(()=>window.ArchHubAPI.saveSession());
      const base=await page.evaluate(()=>window.ArchHubAPI.getSessionDocument());
      const remote=JSON.parse(JSON.stringify(base)),title=mirror?'Editor A title':'Browser title';
      let view={x:147,y:-67,zoom:.8};
      remote.notes.push({text:'Concurrent owner note '+mirror});
      if(mirror)remote.title=title;else {remote.viewport=view;remote.properties.viewportSaved=true;}
      let release,acknowledged;
      const held=new Promise(resolve=>release=resolve),received=new Promise(resolve=>acknowledged=resolve);
      let intercepted=false;
      const handler=async route=>{
        const sent=route.request().postDataJSON();
        if(sent.action!=='autosave'||intercepted)return route.continue();
        intercepted=true;
        const owner=await page.request.post(route.request().url(),{headers:route.request().headers(),data:{...sent,document:remote,base_revision:base.properties.revision}});
        assert.equal(owner.ok(),true);
        const committed=await owner.json();
        const response=await route.fetch({postData:JSON.stringify({...sent,path:committed.path})});
        const merged=await response.json();
        assert.deepEqual(merged.document.viewport,mirror?sent.document.viewport:view);
        assert.equal(merged.document.title,mirror?title:sent.document.title);
        acknowledged();await held;return route.fulfill({response});
      };
      await page.route('**/api/session-files',handler);
      try{
        await page.evaluate(mirror=>mirror?window.ArchHubAPI.setSessionViewport({x:21,y:13,zoom:1}):window.ArchHubAPI.updateGraph(null,{name:'Browser title sent'}),mirror);
        await received;
        if(mirror){
          await page.waitForFunction(()=>{const m=new window.DOMMatrix(window.getComputedStyle(document.querySelector('.react-flow__viewport')).transform);return m.e===21&&m.f===13&&m.a===1;});
          const pane=await page.locator('.react-flow__pane').boundingBox(),x=pane.x+pane.width-100,y=pane.y+100,input=await page.context().newCDPSession(page);
          try{
            await input.send('Input.dispatchMouseEvent',{type:'mouseMoved',x,y});
            await input.send('Input.dispatchMouseEvent',{type:'mousePressed',x,y,button:'middle',buttons:4,clickCount:1});
            for(let step=1;step<=8;step++)await input.send('Input.dispatchMouseEvent',{type:'mouseMoved',x:x-72*step/8,y:y+45*step/8,button:'middle',buttons:4});
            await input.send('Input.dispatchMouseEvent',{type:'mouseReleased',x:x-72,y:y+45,button:'middle',buttons:0,clickCount:1});
          }finally{await input.detach();}
          await page.waitForFunction(()=>JSON.stringify(window.ArchHubAPI.getSessionDocument().viewport)!==JSON.stringify({x:21,y:13,zoom:1}));
          view=await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().viewport);
          assert.notDeepEqual(view,{x:21,y:13,zoom:1});
        }else await page.evaluate(title=>window.ArchHubAPI.updateGraph(null,{name:title}),title);
        release();
        await page.waitForFunction(({title,view})=>{const d=window.ArchHubAPI.getSessionDocument();return d.title===title&&JSON.stringify(d.viewport)===JSON.stringify(view)&&d.properties.viewportSaved===true;},{title,view});
        assert.deepEqual(await rendered(),view);
        assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.name),title);
        assert.deepEqual(await page.evaluate(()=>window.ArchHubAPI.getSessionDocument().notes),remote.notes);
        await page.evaluate(()=>window.ArchHubAPI.saveSession());
      }finally{release();await page.unrouteAll({behavior:'wait'});}
      await page.goto('about:blank');server=await restart();
      await page.goto(server.url+'/studio?bootstrap='+server.bootstrap);await page.locator('[data-home-page]').waitFor({state:'attached'});
      await page.waitForFunction(()=>Array.isArray(window.ArchHubAPI.getSnapshot().libraryPorts));
      await page.evaluate(file=>window.ArchHubAPI.openSession(file),file);
      await page.getByRole('navigation',{name:'Main navigation'}).getByRole('button',{name:'Canvas',exact:true}).click();
      await page.waitForFunction(id=>window.ArchHubAPI.getSessionDocument()?.id===id,base.id);
      await page.waitForFunction(()=>!window.ArchHubAPI.getSnapshot().sessionDirty);
      await page.waitForFunction(view=>{const el=document.querySelector('.react-flow__viewport');if(!el)return false;const m=new window.DOMMatrix(window.getComputedStyle(el).transform);return m.e===view.x&&m.f===view.y&&m.a===view.zoom;},view);
      assert.deepEqual(await rendered(),view);
      const before=fs.readFileSync(file);await page.waitForTimeout(5000);
      assert.equal(fs.readFileSync(file).equals(before),true);
      const saved=JSON.parse(before);assert.equal(saved.title,title);assert.deepEqual(saved.viewport,view);assert.equal(saved.properties.viewportSaved,true);
      console.log('PASS acknowledged '+(mirror?'remote title + local pan':'remote view + local title')+': in-flight edit retained; next save + restart + 5s idle preserve both');
    }
  });
  assert.deepEqual(errors,[]);
});
