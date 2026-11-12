const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {chromium} = require('playwright');
const {transformSync} = require('esbuild');
const studio = path.resolve(__dirname, '../../01.APP/nodelang/studio');

test('real owner: All 146, Workflows 31, Agent sessions 115; filters and collapse survive reload', async t => {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'workflowscat-'));
  let browser;
  const env = {...process.env, USERPROFILE:profile, HOME:profile, LOCALAPPDATA:path.join(profile,'local'),
    APPDATA:path.join(profile,'roaming'), ARCHHUB_TEST_STATE_DIR:path.join(profile,'state'),
    ARCHHUB_TEST_SECRET_STORE:'memory', PYTHONDONTWRITEBYTECODE:'1',
    PATH:path.dirname(process.env.ARCHHUB_TEST_PYTHON)+path.delimiter+process.env.PATH,
    PYTHONPATH:path.resolve(studio,'../..')};
  const server = spawn(process.env.ARCHHUB_TEST_PYTHON, ['-u', '-c', `
import json, os, sys, threading
from pathlib import Path
from nodelang.session_files import SessionFiles, new_document
from nodelang.nograph_server import NoGraphServer
from nodelang.library_engines import LIBRARY_ITEMS_WITHOUT_ENGINE, LIBRARY_PRESENTATION, LIBRARY_ITEM_ENGINES
# Exercise the owner's declared unavailable state in this isolated server only.
missing = next(item for _, rows in LIBRARY_PRESENTATION for item, _, _ in rows if item in LIBRARY_ITEM_ENGINES)
LIBRARY_ITEMS_WITHOUT_ENGINE[missing] = 'Fixture engine is unavailable'
owner = SessionFiles()
for i in range(146):
    doc = new_document(('Workflow ' if i < 31 else 'Agent ') + str(i))
    if i >= 31: doc['properties']['taskContext'] = {'task': 'task-' + str(i)}
    if i == 0: doc['nodes'] = [{'id':'agent', 'title':'Agent node', 'type':'thing.agent', 'params':{}, 'position':{'x':0,'y':0}}]
    target = owner.directory / (str(i) + '.archhub')
    target.write_text(json.dumps(doc), encoding='utf-8')
first = owner.directory / '0.archhub'
owner.dispatch({'action':'open', 'path':str(first)})
server = NoGraphServer(Path(os.environ['ARCHHUB_TEST_STATE_DIR']))
thread = threading.Thread(target=server.httpd.serve_forever, daemon=True)
thread.start()
print(json.dumps({'url':server.public_url, 'token':server.browser_session_token, 'csrf':server.browser_csrf_token}), flush=True)
try: sys.stdin.readline()
finally:
    server.httpd.shutdown()
    server.httpd.server_close()
    thread.join(5)
`], {env, stdio:['pipe','pipe','pipe']});
  let stderr = '';
  server.stderr.on('data', chunk => {stderr += chunk;});
  t.after(async () => {
    if(browser)await browser.close();
    if(server.exitCode===null){server.stdin.end('\n');await once(server,'exit');}
    fs.rmSync(profile, {recursive:true, force:true});
    assert.equal(server.exitCode, 0, stderr);
  });
  const connection = await new Promise((resolve,reject) => {
    let output = '';
    server.stdout.on('data', chunk => {
      output += chunk;
      const line = output.split('\n').find(line => line.startsWith('{"url":'));
      if(line)resolve(JSON.parse(line));
    });
    server.once('exit', code => reject(Error('owner startup '+code+': '+stderr)));
    server.once('error', reject);
  });
  browser = await chromium.launch({headless:true, env, executablePath:process.env.ARCHHUB_TEST_CHROMIUM});

  const page = await browser.newPage();
  const errors = [];
  const opens = [];
  const actions = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if(request.url().endsWith('/api/session-files')){const body=request.postDataJSON();actions.push(body.action);if(body.action==='open')opens.push(body.path);}
  });
  await page.route(connection.url+'/', route => route.fulfill({contentType:'text/html', body:'<div id="root"></div>'}));
  async function load(name, homeFixtures=undefined) {
    await page.goto(connection.url);
    await page.evaluate(connection => {window.ARCHHUB_BOOT={token:connection.token,csrf:connection.csrf,nograph:true};}, connection);
    await page.evaluate(fixtures=>{window.homeFixtures=fixtures;},homeFixtures);
    for(const script of ['vendor/react.js','vendor/react-dom.js','studio-authority.js','api.js'])
      await page.addScriptTag({content:fs.readFileSync(path.join(studio,script),'utf8')});
    await page.evaluate(async()=>{window.ArchHubAPI.setActiveSurface('canvas');await window.ArchHubAPI.ready;await window.ArchHubAPI.readHomeLayout();});
    await page.evaluate(() => {
      const api = window.ArchHubAPI;
      window.routes = [];window.handlers = {};
      window.executeAction = (id, context) => id==='ui.select' ? context() : window.handlers[id](context);
      window.registerActions = (mapping, handlers) => {
        for(const [id,name] of Object.entries(mapping))window.handlers[id]=handlers[name];
      };
      const component = ({children})=>window.React.createElement('span',null,children);
      const app = {composerDraft:{},act:fn=>fn(),setSelectedNodeId:()=>{},taskFace:'canvas',go:route=>window.routes.push(route)};
      window.AHIcon = ()=>null;
      window.UI = {A:{},D:{Toggle:component},api,
        taskRowReason:()=>'',
        useData:()=>{const [data,setData]=window.React.useState(api.getSnapshot());window.React.useEffect(()=>api.subscribe(()=>setData(api.getSnapshot())),[]);return {...data,...window.homeFixtures};},
        useApp:()=>app, Btn:component,Empty:component,Av:()=>null,AgentPicker:()=>null,TaskComposer:()=>null};
      window.mount = name => window.ReactDOM.render(window.React.createElement(window.UI[name]),document.getElementById('root'));
    });
    for(const script of ['ds_library.jsx','ds_home2.jsx'])
      await page.addScriptTag({content:transformSync(fs.readFileSync(path.join(studio,script),'utf8'),{loader:'jsx'}).code});
    await page.evaluate(name=>window.mount(name), name);
  }
  const filter = () => page.getByRole('group',{name:'Saved document filter',exact:true});
  async function choose(label, count, selector) {
    await filter().getByRole('button',{name:label,exact:true}).click();
    await page.waitForFunction(({selector,count})=>document.querySelectorAll(selector).length===count,{selector,count});
    assert.equal(await filter().getByRole('button',{name:label,exact:true}).getAttribute('aria-pressed'),'true');
  }
  await load('LibraryShelf');
  await page.getByLabel('Search nodes',{exact:true}).fill('node');
  const catalogue = await page.evaluate(()=>window.ArchHubAPI.getSnapshot().catalogue);
  const families = [...new Set(catalogue.map(row=>row.family))];
  assert.deepEqual(await page.locator('.family-chips button').allTextContents(),['All',...families]);
  for(const family of families.filter(family=>catalogue.some(row=>row.family===family&&`${row.name} ${row.description}`.toLowerCase().includes('node')))) {
    await page.locator('.family-chips').getByRole('button',{name:family,exact:true}).click();
    assert.deepEqual(await page.locator('.shelf-node').evaluateAll(rows=>rows.map(row=>row.getAttribute('aria-label'))),
      catalogue.filter(row=>row.family===family&&`${row.name} ${row.description}`.toLowerCase().includes('node')).map(row=>'Add '+row.name));
  }
  const unavailable = catalogue.find(row=>row.unavailable&&row.reason);
  assert.ok(unavailable,'real owner must expose an unavailable card with a reason');
  await page.getByLabel('Search nodes',{exact:true}).fill(unavailable.name);
  await page.locator('.family-chips').getByRole('button',{name:'All',exact:true}).click();
  const card = page.getByRole('button',{name:'Add '+unavailable.name,exact:true});
  assert.equal(await card.isDisabled(),true);
  assert.equal(await card.getByText(unavailable.reason,{exact:true}).count(),1);
  t.diagnostic('item 5 PASS: category chips filter real owner rows; unavailable card is disabled and shows its reason');
  await page.getByLabel('Search nodes',{exact:true}).fill('');
  const category = await page.evaluate(()=>window.ArchHubAPI.getSnapshot().catalogue.find(row=>row.family==='trigger').family);
  await page.locator('.shelf-category').filter({hasText:category}).click();
  await page.waitForFunction(category=>window.ArchHubAPI.getSnapshot().libraryCollapsed.includes(category),category);
  await assert.rejects(page.evaluate(()=>window.ArchHubAPI.setLibraryCollapsed(['unknown'])),/Unknown Library category/);
  await load('LibraryShelf');
  assert.equal(await page.locator('.shelf-category').filter({hasText:category}).getAttribute('aria-expanded'),'false');
  const rejected = await page.evaluate(async()=>{
    const response=await fetch('/api/universal/settings-action',{method:'POST',headers:{'Content-Type':'application/json','X-ArchHub-Session':window.ARCHHUB_BOOT.token,'X-ArchHub-CSRF':window.ARCHHUB_BOOT.csrf},body:JSON.stringify({function:'setLibraryCollapsed',args:[['unknown']]})});return response.status;
  });
  assert.equal(rejected,409);
  let refuseFilterRead = true;
  await page.route('**/api/universal/settings-action', route => {
    if(route.request().postDataJSON()?.function==='readSessionListFilters'&&refuseFilterRead){
      refuseFilterRead=false;
      return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({ok:false,error:'Filter temporarily unavailable'})});
    }
    return route.continue();
  });
  await page.getByRole('button',{name:'Sessions',exact:true}).click();
  await page.getByRole('alert').filter({hasText:'Filter temporarily unavailable'}).waitFor();
  await page.getByRole('button',{name:'Retry',exact:true}).click();
  await filter().waitFor({state:'visible'});
  assert.equal(await filter().count(),1);
  assert.deepEqual(await filter().getByRole('button').allTextContents(),['All','Workflows','Agent sessions']);
  assert.equal(await page.locator('select').count(),0);
  assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graphs.length),146,'owner catalogue must retain all fixtures');
  await choose('All',146,'.scroll button.listbutton');
  await page.getByLabel('Search nodes',{exact:true}).fill('no-matching-document');
  await page.getByText('No sessions found.',{exact:true}).waitFor();
  await page.getByLabel('Search nodes',{exact:true}).fill('');
  await choose('Workflows',31,'.scroll button.listbutton');
  await choose('Agent sessions',115,'.scroll button.listbutton');
  await load('LibraryShelf');
  await page.getByRole('button',{name:'Sessions',exact:true}).click();
  await page.waitForFunction(()=>document.querySelectorAll('.scroll button.listbutton').length===115);
  assert.equal(await filter().getByRole('button',{name:'Agent sessions',exact:true}).getAttribute('aria-pressed'),'true');
  await choose('Workflows',31,'.scroll button.listbutton');
  await page.getByRole('button',{name:'Workflow 0',exact:true}).click();
  assert.equal(opens.length,1);
  await load('Home');
  await choose('All',31,'.resume-session-scroll .dx-task');
  await choose('Agent sessions',0,'.resume-session-scroll .dx-task');
  await choose('Workflows',31,'.resume-session-scroll .dx-task');
  await page.locator('.dx-task').filter({hasText:'Workflow 1'}).first().click();
  await page.waitForFunction(()=>window.routes.includes('canvas'));
  assert.equal(opens.length,2);
  await load('Home');
  await page.waitForFunction(()=>document.querySelectorAll('.resume-session-scroll .dx-task').length===31);
  assert.equal(await filter().getByRole('button',{name:'Workflows',exact:true}).getAttribute('aria-pressed'),'true');
  const homeFixtures = await page.evaluate(async()=>{
    const graphs=window.ArchHubAPI.getSnapshot().graphs;
    const file = title=>graphs.find(row=>row.title===title).path;
    window.homeFixtures={tasks:[
      {id:'a',title:'Task workflow A',sessionPath:file('Workflow 0'),status:'PLANNED'},
      {id:'b',title:'Task workflow B',sessionPath:file('Workflow 1'),status:'PLANNED'},
      {id:'p',title:'Pinned workflow',sessionPath:file('Workflow 2'),status:'PLANNED',homePinned:true},
      {id:'h',title:'Hidden workflow',sessionPath:file('Workflow 3'),status:'PLANNED'},
      {id:'c',title:'Task agent C',sessionPath:file('Agent 31'),status:'PLANNED'},
      {id:'d',title:'Task agent D',sessionPath:file('Agent 32'),status:'PLANNED'},
      {id:'q',title:'Pinned agent',sessionPath:file('Agent 33'),status:'PLANNED',homePinned:true},
      {id:'i',title:'Hidden agent',sessionPath:file('Agent 34'),status:'PLANNED'},
      {id:'n',title:'Task without file',status:'PLANNED'}
    ],agents:[{id:'runtime',name:'Unassigned runtime',runtime:'codex',status:'idle'}]};
    await window.ArchHubAPI.setHomeLayout({width:300,collapsed:false,resume:'',order:['b','a','d','c','n'],hidden:['h','i']});
    window.mount('LibraryShelf');window.mount('Home');
    return window.homeFixtures;
  });
  const titles=()=>page.locator('.resume-session-scroll .dx-task b').allTextContents();
  const orphanWorkflows=Array.from({length:27},(_,i)=>i+4).sort((a,b)=>(a+'.archhub').localeCompare(b+'.archhub')).map(i=>'Workflow '+i);
  for(const [label,expected] of [
    ['All',['Pinned workflow','Pinned agent','Task workflow B','Task workflow A','Task agent D','Task agent C','Task without file','Unassigned runtime',...orphanWorkflows]],
    ['Workflows',['Pinned workflow','Task workflow B','Task workflow A',...orphanWorkflows]],
    ['Agent sessions',['Pinned agent','Task agent D','Task agent C','Task without file','Unassigned runtime']]
  ]) {
    await choose(label,expected.length,'.resume-session-scroll .dx-task');
    assert.deepEqual(await titles(),expected,label+' preserves ordered tasks, pins, hiding and appended workflows');
    assert.equal(await page.locator('.resume-session-scroll').getByText(/^Hidden /).count(),0);
    assert.equal(await page.locator('.resume-session-scroll button.listbutton').count(),0,'no plain-file fallback');
    assert.equal(await page.getByRole('button',{name:'Unpin Pinned '+(label==='Agent sessions'?'agent':'workflow'),exact:true}).getAttribute('aria-pressed'),'true');
  }
  await choose('All',35,'.resume-session-scroll .dx-task');
  await page.getByRole('button',{name:'Hide Task without file from Home',exact:true}).click();
  await page.waitForFunction(()=>document.querySelectorAll('.resume-session-scroll .dx-task').length===34);
  await load('Home',homeFixtures);
  await choose('Agent sessions',4,'.resume-session-scroll .dx-task');
  assert.equal(await page.getByText('Task without file',{exact:true}).count(),0);
  await page.evaluate(()=>window.ReactDOM.render(window.React.createElement(window.UI.SessionList,{list:'home',renderRow:()=>null}),document.getElementById('root')));
  await filter().waitFor();
  assert.equal(await page.locator('button.listbutton').count(),0,'null row renderer must not create plain file buttons');
  t.diagnostic('item 6 PASS: ordered tasks, pins, hidden tasks, fileless task, runtime agent and orphan workflow rows; Library counts 146/31/115');
  assert.equal(actions.includes('run')||actions.includes('solve'),false);
  assert.deepEqual(errors,[]);
});
