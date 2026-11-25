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
    try: server.close()
    except Exception:
        server.httpd.shutdown()
        server.httpd.server_close()
    thread.join(5)
`], {env, stdio:['pipe','pipe','pipe']});
  let stderr = '';
  server.stderr.on('data', chunk => {stderr += chunk;});
  t.after(async () => {
    if(browser)await browser.close();
    if(server.exitCode===null){
      server.stdin.end('\n');
      await Promise.race([once(server,'exit'), new Promise(r => setTimeout(() => { try { server.kill(); } catch {} r(); }, 3000))]);
    }
    fs.rmSync(profile, {recursive:true, force:true});
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
  page.setDefaultTimeout(10000);
  const errors = [];
  const opens = [];
  const actions = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if(request.url().endsWith('/api/session-files')){const body=request.postDataJSON();actions.push(body.action);if(body.action==='open')opens.push(body.path);}
  });
  await page.route(connection.url+'/', route => route.fulfill({contentType:'text/html', body:'<div id="root"></div>'}));
  await page.route('**/api/universal/desktop-access', route => route.fulfill({
    json: {ok: true, admitted: true, state: 'admitted', subject: 'studio-test', email: 'studio@example.test'}
  }));
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
        useApp:()=>app, Btn:component,Empty:component,Soon:component,Av:()=>null,AgentPicker:()=>null,TaskComposer:()=>null};
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
  await page.waitForFunction(()=>{const s=window.ArchHubAPI.getSnapshot();return s.libraryTree?.length>0&&s.catalogue.length>0;});
  await page.getByLabel('Search nodes',{exact:true}).fill('node');
  const {catalogue, libraryPorts, openSessionPath, hasSettingsApi} = await page.evaluate(()=>{
    const s=window.ArchHubAPI.getSnapshot();
    return {catalogue:s.catalogue, libraryPorts:s.libraryPorts||[], openSessionPath:window.ArchHubAPI.getSessionPath?.()||s.sessionFile||'',
      hasSettingsApi:typeof window.ArchHubAPI.exposeSettingsPage==='function'};
  });
  // The owner's tree names the categories; search filters directly across groups with zero .family-chips.
  const groups = (await page.evaluate(()=>window.ArchHubAPI.getSnapshot().libraryTree)).filter(group=>catalogue.some(row=>group.categories.includes(row.family)));
  assert.deepEqual(catalogue.filter(row=>!groups.some(group=>group.categories.includes(row.family))),[],'every card category sits in the tree');
  assert.equal(await page.locator('.family-chips').count(),0);
  // Search reads name, summary, program (engine) and tree row; an agent session is never offered as a skill (design row J7).
  const agentSessions = await page.evaluate(()=>window.ArchHubAPI.getSnapshot().templates.filter(row=>row.kind==='agent-session').map(row=>row.id));
  assert.equal(agentSessions.length,115);
  const pathKey = p => String(p || '').replace(/\\/g, '/').toLowerCase();
  const openKey = pathKey(openSessionPath);
  const portById = new Map(libraryPorts.map(item => [item.id, item]));
  const PROGS_G = ['Revit', 'AutoCAD', 'Excel', 'Outlook', '3ds Max', 'Rhino', 'Blender'];
  const SETTINGS_AREAS = [
    {key:'Account', label:'Account', description:'Your ArchHub account: the same values in the app and on archhub.io', pages:['Account','Brain']},
    {key:'Projects', label:'Projects', description:'Units, the standard, templates, naming and folders', pages:['Projects']},
    {key:'Agents', label:'Agents', description:'Who works for you, on which model, what they may do, the Workshop, automations and tools', pages:['Agents','BABOOM','Hooks','Workshop','Automations','Library & Mods']},
    {key:'Connections', label:'Connections', description:'Accounts, programs, your phone and notifications', pages:['Connections']},
    {key:'You', label:'This PC', description:'This PC: how ArchHub looks, workspaces, files, privacy, updates and the app', pages:['Appearance','Privacy','Advanced','System graph','Dependencies','Updates & About']}
  ];
  const areaBackingIds = new Set(SETTINGS_AREAS.map(a => 'settings_' + a.label.toLowerCase().replace(/\s+/g, '_')));
  const programOf = c => {
    const portItem = portById.get(c.id);
    if (portItem?.program && PROGS_G.includes(portItem.program)) return portItem.program;
    if (c.prog && PROGS_G.includes(c.prog)) return c.prog;
    if (c.program && PROGS_G.includes(c.program)) return c.program;
    const engine = String(c.descriptor?.engine || portItem?.engine || '').toLowerCase();
    const hostParam = engine === 'thing.host' ? String(portItem?.params?.host || c.params?.host || '').toLowerCase() : '';
    const text = `${c.name || ''} ${c.description || ''}`;
    if (engine.startsWith('revit.') || hostParam === 'revit' || /\brevit\b/i.test(text)) return 'Revit';
    if (engine.startsWith('acad.') || engine.startsWith('autocad.') || engine === 'cad.host_lines' || hostParam === 'acad' || /\b(autocad|dwg)\b/i.test(text)) return 'AutoCAD';
    if (hostParam === 'excel' || /\b(excel|workbook|xlsx)\b/i.test(text) || String(portItem?.params?.operation || '').startsWith('excel.')) return 'Excel';
    if (engine.startsWith('outlook.') || engine === 'library.draft_email' || hostParam === 'outlook' || /\boutlook\b/i.test(text)) return 'Outlook';
    if (engine.startsWith('max.') || hostParam === 'max' || /\b3ds\s*max\b/i.test(text)) return '3ds Max';
    if (engine.startsWith('rhino.') || hostParam === 'rhino' || /\brhino\b/i.test(text)) return 'Rhino';
    if (engine.startsWith('blender.') || hostParam === 'blender' || /\bblender\b/i.test(text)) return 'Blender';
    return '';
  };
  const shelfCards = group => {
    const base = catalogue.filter(row => {
      if (!group.categories.includes(row.family) || agentSessions.includes(row.id)) return false;
      if (group.id === 'settings' && (String(row.id || '').startsWith('thing:setting:') || areaBackingIds.has(row.id))) return false;
      const sf = portById.get(row.id)?.params?.session_file;
      if (sf && openKey && pathKey(sf) === openKey) return false;
      return true;
    });
    if (group.id === 'host') {
      const seen = new Set();
      const grouped = PROGS_G.flatMap(prog => base.filter(c => programOf(c) === prog && seen.add(c.id)));
      return [...grouped, ...base.filter(c => !seen.has(c.id))];
    }
    if (group.id === 'settings' && hasSettingsApi) {
      return [...SETTINGS_AREAS.map(a => ({name: a.label, isArea: true, area: a})), ...base];
    }
    return base;
  };
  const foundCard = (row, group, q) => row.isArea
    ? `${row.area.key} ${row.area.label} ${row.area.description} ${row.area.pages.join(' ')} settings`.toLowerCase().includes(q)
    : `${row.name} ${row.description||''} ${row.descriptor?.engine||''} ${programOf(row)} ${group.label}`.toLowerCase().includes(q);
  const expectedNodeMatches = groups.flatMap(group => shelfCards(group).filter(row => foundCard(row, group, 'node')).map(row => 'Add ' + row.name));
  assert.ok(expectedNodeMatches.length > 0);
  assert.deepEqual(await page.locator('.shelf-node').evaluateAll(rows=>rows.map(row=>row.getAttribute('aria-label'))), expectedNodeMatches);
  const unavailable = catalogue.find(row=>row.unavailable&&row.reason);
  assert.ok(unavailable,'real owner must expose an unavailable card with a reason');
  await page.getByLabel('Search nodes',{exact:true}).fill(unavailable.name);
  const card = page.getByRole('button',{name:'Add '+unavailable.name,exact:true});
  assert.equal(await card.getAttribute('aria-disabled'),'true');
  assert.equal(await card.evaluate(el => el.classList.contains('off')),true);
  assert.equal(await card.getByText(unavailable.reason,{exact:true}).count(),1);
  t.diagnostic('item 5 PASS: search filters real owner rows directly; unavailable card carries .off, aria-disabled="true" and its reason');
  await page.getByLabel('Search nodes',{exact:true}).fill('');
  // A fresh profile starts with the tree closed; the category he opens stays open after a reload.
  const category = page.locator('[data-library-category="trigger"] > .shelf-category');
  assert.equal(await category.getAttribute('aria-expanded'),'false');
  assert.equal(await page.locator('.shelf-node').count(),0);
  await category.click();
  await page.waitForFunction(()=>!window.ArchHubAPI.getSnapshot().libraryCollapsed.includes('trigger'));
  await assert.rejects(page.evaluate(()=>window.ArchHubAPI.setLibraryCollapsed(['unknown'])),/Unknown Library category/);
  await load('LibraryShelf');
  await page.locator('[data-library-category="trigger"] > .shelf-category[aria-expanded="true"]').waitFor();
  assert.equal(await page.locator('[data-library-category="host"] > .shelf-category').getAttribute('aria-expanded'),'false');
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
  // The Library shelf no longer carries a Sessions tab (design: saved work sits under "Workflows and skills").
  // The saved-document list is the shared SessionList that Home renders; it is mounted alone here.
  assert.equal(await page.locator('.shelf-tabs').count(),0);
  const list = (props={})=>page.evaluate(props=>window.ReactDOM.render(window.React.createElement(window.UI.SessionList,{list:'home',...props}),document.getElementById('root')),props);
  await list();
  await page.getByRole('alert').filter({hasText:'Filter temporarily unavailable'}).waitFor();
  await page.getByRole('button',{name:'Retry',exact:true}).click();
  await filter().waitFor({state:'visible'});
  assert.equal(await filter().count(),1);
  assert.deepEqual(await filter().getByRole('button').allTextContents(),['All','Workflows','Agent sessions']);
  assert.equal(await page.locator('select').count(),0);
  assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graphs.length),146,'owner catalogue must retain all fixtures');
  await choose('All',146,'button.listbutton');
  await list({query:'no-matching-document'});
  await page.getByText('No sessions found.',{exact:true}).waitFor();
  await list();
  await choose('Workflows',31,'button.listbutton');
  await choose('Agent sessions',115,'button.listbutton');
  await load('LibraryShelf');
  await list();
  await page.waitForFunction(()=>document.querySelectorAll('button.listbutton').length===115);
  assert.equal(await filter().getByRole('button',{name:'Agent sessions',exact:true}).getAttribute('aria-pressed'),'true');
  await choose('Workflows',31,'button.listbutton');
  await page.getByRole('button',{name:'Workflow 0',exact:true}).click();
  assert.equal(opens.length,1);
  // Home is the map of the work (design v61): its All / Agent sessions / Workflows filter is the same owner value, read here
  // through the map's own function on the real owner's rows (Home's Dock and canvas are proved by the rendered Home tests).
  const mapTitles = (kind, fixtures) => page.evaluate(({kind, fixtures}) => {
    const s = {...window.ArchHubAPI.getSnapshot(), ...(fixtures || {})}, layout = s.homeLayout;
    const params = {group: 'Project', order: 'Needs you first', card: 'Steps and state', density: 'Comfortable', done: 'Show', filter: 'All'};
    const chart = window.UI.homeMap({listed: {groups: []}, rows: window.UI.homeRows(s, layout), params, hidden: layout.hidden || [],
      titleOf: row => row.title || row.name, kind, order: layout.order || [], olderOpen: true, history: true});  // old files sit in the Older section: unfolded to count them
    return chart.nodes.filter(node => !node.group).map(node => node.title);
  }, {kind, fixtures});
  assert.equal((await mapTitles('all', null)).length, 31, 'the workflow files are cards');
  assert.equal((await mapTitles('agent-session', null)).length, 0);
  assert.equal((await mapTitles('workflow', null)).length, 31);
  await filter().getByRole('button',{name:'Workflows',exact:true}).click();
  assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().sessionListFilters?.home),'workflow','the filter is the one owner value Home reads');
  const homeFixtures = await page.evaluate(async()=>{
    const graphs=window.ArchHubAPI.getSnapshot().graphs;
    const file = title=>graphs.find(row=>row.title===title).path;
    const fixtures={tasks:[
      {id:'a',title:'Task workflow A',sessionPath:file('Workflow 0'),status:'PLANNED'},
      {id:'b',title:'Task workflow B',sessionPath:file('Workflow 1'),status:'PLANNED'},
      {id:'p',title:'Pinned workflow',sessionPath:file('Workflow 2'),status:'PLANNED',homePinned:true},
      {id:'h',title:'Hidden workflow',sessionPath:file('Workflow 3'),status:'PLANNED'},
      {id:'c',title:'Task agent C',sessionPath:file('Agent 31'),status:'PLANNED'},
      {id:'d',title:'Task agent D',sessionPath:file('Agent 32'),status:'PLANNED'},
      {id:'q',title:'Pinned agent',sessionPath:file('Agent 33'),status:'PLANNED',homePinned:true},
      {id:'i',title:'Hidden agent',sessionPath:file('Agent 34'),status:'PLANNED'},
      {id:'n',title:'Task without file',status:'PLANNED'}
    ]};
    await window.ArchHubAPI.setHomeLayout({width:300,collapsed:false,resume:'',order:['b','a','d','c','n'],hidden:['h','i']});
    await window.ArchHubAPI.readHomeLayout();
    return fixtures;
  });
  const orphanWorkflows=Array.from({length:27},(_,i)=>'Workflow '+(i+4));
  for(const [kind,expected] of [
    ['all',['Pinned workflow','Pinned agent','Task workflow B','Task workflow A','Task agent D','Task agent C','Task without file',...orphanWorkflows]],
    ['workflow',['Pinned workflow','Task workflow B','Task workflow A',...orphanWorkflows]],
    ['agent-session',['Pinned agent','Task agent D','Task agent C','Task without file']]
  ]) {
    const shown = await mapTitles(kind, homeFixtures);
    assert.deepEqual([...shown].sort(), [...expected].sort(), kind+': tasks, pins and appended workflow files; hidden ones are not drawn');
    const at = title => shown.indexOf(title);
    for (const [first, then] of [['Task workflow B','Task workflow A'],['Task agent D','Task agent C']])
      if (at(first) >= 0) assert.ok(at(first) < at(then), kind+': his order arranges the cards ('+first+' before '+then+')');
  }
  await page.evaluate(async()=>{const held=(await window.ArchHubAPI.readHomeLayout()).homeLayout;await window.ArchHubAPI.setHomeLayout({...held,hidden:[...held.hidden,'n']});await window.ArchHubAPI.readHomeLayout();});
  assert.equal((await mapTitles('agent-session', homeFixtures)).includes('Task without file'), false, 'a hidden session is no card');
  await page.evaluate(()=>window.ReactDOM.render(window.React.createElement(window.UI.SessionList,{list:'home',renderRow:()=>null}),document.getElementById('root')));
  await filter().waitFor();
  assert.equal(await page.locator('button.listbutton').count(),0,'null row renderer must not create plain file buttons');
  t.diagnostic('item 6 PASS: ordered tasks, pins, hidden tasks, fileless task, runtime agent and orphan workflow rows; saved-document list counts 146/31/115');
  assert.equal(actions.includes('run')||actions.includes('solve'),false);
  assert.deepEqual(errors,[]);
});
