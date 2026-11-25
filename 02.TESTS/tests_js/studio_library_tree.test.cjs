// Design row 6 (archhub-directions 2d9fe5ceeed7): the Library shelf is the owner's category tree, closed at first,
// with Library options beside the search; no tabs and no footer. Real owner, real catalogue, the real stylesheet.
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
// Never the bare python on PATH (on this PC that is the Windows Store stub).
const python = process.env.ARCHHUB_TEST_PYTHON || process.env.PYTHON || path.join(process.env.LOCALAPPDATA, 'Python/bin/python.exe');
const DESIGN = ['Programs', 'Files', 'Workflows and skills', 'Starts a run', 'Checks and standards', 'Agents and AI', 'Lists and data', 'Change geometry', 'Decide and branch'];
const OPTIONS = [['Library & Mods', ['go', 'settings/Library & Mods']], ['Community', ['go', 'community']], ['Import a node…', ['show', 'Install mod']]];

test('LIBRARY tree: owner categories under plain labels, closed first, every option acts, fluid at 1009/1440/1920', async t => {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'librarytree-'));
  let browser;
  const env = {...process.env, USERPROFILE:profile, HOME:profile, LOCALAPPDATA:path.join(profile,'local'),
    APPDATA:path.join(profile,'roaming'), ARCHHUB_TEST_STATE_DIR:path.join(profile,'state'),
    ARCHHUB_TEST_SECRET_STORE:'memory', PYTHONDONTWRITEBYTECODE:'1', ARCHHUB_DISABLE_WORKSHOP_WATCH:'1',
    PATH:path.dirname(python)+path.delimiter+process.env.PATH,
    PYTHONPATH:path.resolve(studio,'../..')};
  const server = spawn(python, ['-u', '-c', `
import json, os, sys, threading
from pathlib import Path
from nodelang.session_files import SessionFiles, new_document
from nodelang.nograph_server import NoGraphServer
# Session files belong to the admitted account: they are written under its resume signer (cloud_session.DesktopAccess.check).
from nodelang.cloud_session import _ResumeSigner
signer = _ResumeSigner(b'isolated-test-key', 'isolated', 'librarytree-fixture', 'isolated')
owner = SessionFiles(sign_resume_pointer=signer)
for name in ('door-schedule', 'sheet-check'):
    (owner.directory / (name + '.archhub')).write_text(json.dumps(new_document(name)), encoding='utf-8')
talk = new_document('agent-talk')
talk['properties']['taskContext'] = {'task': 'task-1'}
(owner.directory / 'agent-talk.archhub').write_text(json.dumps(talk), encoding='utf-8')
owner.dispatch({'action':'open', 'path':str(owner.directory / 'door-schedule.archhub')})
# Desktop work needs a verified ArchHub account (cd19d5d4); this isolated owner is signed in.
class Admitted:
    def check(self, *, expected_bearer=None, bind_resume=False):
        return {'ok': True, 'admitted': True, 'state': 'admitted', 'subject': 'librarytree-fixture', 'email': None,
                '_sign_resume_pointer': signer}
server = NoGraphServer(Path(os.environ['ARCHHUB_TEST_STATE_DIR']), desktop_access=Admitted())
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

  for (const width of [1009, 1440, 1920]) {
    const page = await browser.newPage({viewport:{width, height:900}});
    page.setDefaultTimeout(10000);
    const errors = [], actions = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => {if(request.url().endsWith('/api/session-files'))actions.push(request.postDataJSON().action);});
    // The shelf sits in the Canvas peek container the stylesheet already defines; its width is changed below to the dock's own limits.
    await page.route(connection.url+'/', route => route.fulfill({contentType:'text/html',
      body:'<div id="root" data-screen="canvas" style="position:relative"><div id="shelf-host" class="canvas-pane-peek" data-side="library"></div></div>'}));
    await page.route('**/api/universal/desktop-access', route => route.fulfill({
      json: {ok: true, admitted: true, state: 'admitted', subject: 'studio-test', email: 'studio@example.test'}
    }));
    await page.goto(connection.url);
    await page.addStyleTag({path:path.join(studio,'style.css')});
    await page.evaluate(connection => {window.ARCHHUB_BOOT={token:connection.token,csrf:connection.csrf,nograph:true};}, connection);
    for(const script of ['vendor/react.js','vendor/react-dom.js','studio-authority.js','api.js'])
      await page.addScriptTag({content:fs.readFileSync(path.join(studio,script),'utf8')});
    await page.evaluate(async()=>{window.ArchHubAPI.setActiveSurface('canvas');await window.ArchHubAPI.ready;});
    // The real shared UI: tokens, the action table, UI.Soon and the rest. Only the app shell (go, show) is a recorder,
    // and the icon is a tag that carries its name so the test can read which icon a row asked for.
    for(const script of ['tokens.jsx','ds/index.jsx','icons.jsx','ui.jsx'])
      await page.addScriptTag({content:transformSync(fs.readFileSync(path.join(studio,script),'utf8'),{loader:'jsx'}).code});
    await page.evaluate(() => {
      window.calls = [];
      const app = {act:fn=>fn(),setSelectedNodeId:()=>{},go:route=>window.calls.push(['go',route]),show:kind=>window.calls.push(['show',kind])};
      window.AHIcon = ({name,size})=>window.React.createElement('svg',{'data-icon':name,width:size,height:size});
      window.UI.useApp = ()=>app;
    });
    await page.addScriptTag({content:transformSync(fs.readFileSync(path.join(studio,'ds_library.jsx'),'utf8'),{loader:'jsx'}).code});
    await page.evaluate(()=>window.ReactDOM.render(window.React.createElement(window.UI.LibraryShelf),document.getElementById('shelf-host')));
    await page.waitForFunction(()=>{const s=window.ArchHubAPI.getSnapshot();return s.libraryTree?.length>0&&s.catalogue.length>0&&Array.isArray(s.libraryCollapsed);});
    const {tree, catalogue: served, libraryPorts, agentSessions, openSessionPath, hasSettingsApi} = await page.evaluate(()=>{
      const s=window.ArchHubAPI.getSnapshot();
      return {tree:s.libraryTree,catalogue:s.catalogue,libraryPorts:s.libraryPorts||[],
        agentSessions:s.templates.filter(row=>row.kind==='agent-session').map(row=>row.id),
        openSessionPath:window.ArchHubAPI.getSessionPath?.()||s.sessionFile||'',
        hasSettingsApi:typeof window.ArchHubAPI.exposeSettingsPage==='function'};
    });
    // The fixture holds one agent session; the shelf never lists it, browsing or searching (design row J7).
    assert.equal(agentSessions.length,1);
    assert.ok(served.some(card=>agentSessions.includes(card.id)),'the owner serves the agent session as a card');
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
    const catalogue = served.filter(card => {
      if (agentSessions.includes(card.id)) return false;
      const sf = portById.get(card.id)?.params?.session_file;
      if (sf && openKey && pathKey(sf) === openKey) return false;
      return true;
    });
    const cards = group => {
      const base = catalogue.filter(card => group.categories.includes(card.family) && !(group.id === 'settings' && (String(card.id || '').startsWith('thing:setting:') || areaBackingIds.has(card.id))));
      if (group.id === 'host') {
        const seen = new Set();
        const grouped = PROGS_G.flatMap(prog => base.filter(c => programOf(c) === prog && seen.add(c.id)));
        return [...grouped, ...base.filter(c => !seen.has(c.id))];
      }
      if (group.id === 'settings' && hasSettingsApi) {
        const areas = SETTINGS_AREAS.map(a => ({id: 'sput:' + a.key, name: a.label, family: 'settings', isArea: true, area: a}));
        return [...areas, ...base];
      }
      return base;
    };
    const groups = tree.filter(group=>cards(group).length);
    const shelf = page.getByRole('complementary',{name:'Library shelf',exact:true});

    // 1. The tree: the owner's rows in the design's order, each with its icon and the real number of cards, all closed.
    assert.deepEqual(catalogue.filter(card=>!groups.some(group=>group.categories.includes(card.family))),[],'every card sits under a tree row');
    const rows = await shelf.locator('.shelf-category').evaluateAll(buttons=>buttons.map(button=>({label:button.querySelector('b').textContent,
      count:Number(button.querySelector('em').textContent),icon:button.querySelectorAll('svg')[1].getAttribute('data-icon'),open:button.getAttribute('aria-expanded')})));
    assert.deepEqual(rows.map(row=>row.label),groups.map(group=>group.label));
    assert.deepEqual(rows.map(row=>row.label).slice(0,DESIGN.length),DESIGN,'the nine categories the design names lead the tree at '+width);
    assert.deepEqual(rows.map(row=>row.count),groups.map(group=>cards(group).length));
    assert.deepEqual(rows.map(row=>row.icon),groups.map(group=>group.icon));
    assert.ok(rows.every(row=>row.open==='false'),'the tree starts closed at '+width);
    assert.equal(await shelf.locator('.shelf-node').count(),0);
    const saved = cards(groups.find(group=>group.id==='skill')).map(card=>card.name);
    assert.equal(saved.includes('agent-talk'),false,'no agent session under Workflows and skills');
    if (openKey.endsWith('door-schedule.archhub')) assert.equal(saved.includes('door-schedule'),false,'the open session is omitted from self-embedding');
    assert.ok(saved.includes('sheet-check'),'saved sessions are cards under Workflows and skills: '+saved);

    // 2. Nothing else is in the shelf: no tabs, no footer, and the moved actions are not shelf buttons.
    assert.equal(await shelf.locator('.shelf-tabs, .shelf-footer').count(),0);
    for(const name of ['Sessions','Runs','MCP tools','Install mod','Share session','Open session'])
      assert.equal(await shelf.getByRole('button',{name,exact:true}).count(),0,name+' is a shelf button at '+width);

    // 3. Opening a row shows the cards the owner files under it; the owner keeps the choice.
    const trigger = shelf.locator('[data-library-category="trigger"]');
    await trigger.locator('.shelf-category').click();
    await page.waitForFunction(()=>!window.ArchHubAPI.getSnapshot().libraryCollapsed.includes('trigger'));
    await trigger.locator('.shelf-category[aria-expanded="true"]').waitFor();
    const named = card => 'Add ' + card.name;
    assert.deepEqual(await trigger.locator('.shelf-node').evaluateAll(buttons=>buttons.map(button=>button.getAttribute('aria-label'))),
      catalogue.filter(card=>card.family==='trigger').map(named));
    assert.equal(await shelf.locator('.shelf-node').count(),catalogue.filter(card=>card.family==='trigger').length,'only the opened row shows cards');

    // 3b. Design rows 7 and 8: every card has a live engine; zero inert placeholders remain in the shelf.
    assert.deepEqual(catalogue.filter(card=>card.soon),[]);
    assert.equal(await shelf.locator('[data-soon], [data-soon-card], .soon').count(),0);
    const tunnel = trigger.getByRole('button',{name:'Add Remote tunnel',exact:true});
    assert.equal(await tunnel.count(),1);
    assert.equal(await tunnel.getAttribute('aria-disabled'),null);

    // 4. Fluid: at the dock's narrowest, base and widest panel a row stays one 30px line and nothing runs sideways.
    for(const panel of [200, 268, 520]) {
      const box = await page.evaluate(panel=>{
        const host=document.getElementById('shelf-host');host.style.width=panel+'px';
        const shelf=host.querySelector('.library-shelf'),scroller=shelf.querySelector(':scope > .scroll'),edge=shelf.getBoundingClientRect();
        const inside=element=>{const r=element.getBoundingClientRect();return r.left>=edge.left-0.5&&r.right<=edge.right+0.5;};
        return {shelf:shelf.getBoundingClientRect().width,sideways:shelf.scrollWidth>shelf.clientWidth||scroller.scrollWidth>scroller.clientWidth,
          rows:[...shelf.querySelectorAll('.shelf-category')].map(row=>({height:row.getBoundingClientRect().height,inside:inside(row)})),
          cards:[...shelf.querySelectorAll('.shelf-node')].every(inside),search:[...shelf.querySelectorAll('.shelf-search > *')].every(inside),
          page:document.documentElement.scrollWidth<=window.innerWidth};
      },panel);
      assert.ok(box.shelf<=panel&&box.shelf>=panel-2,'shelf fills its panel at '+width+' / '+panel+': '+box.shelf);
      assert.equal(box.sideways,false,'sideways scroll at '+width+' / '+panel);
      assert.ok(box.rows.every(row=>row.height===30&&row.inside),'category rows at '+width+' / '+panel+': '+JSON.stringify(box.rows));
      assert.ok(box.cards&&box.search&&box.page,'cards, search row and page at '+width+' / '+panel+': '+JSON.stringify(box));

      // 5. Library options at this panel width: the menu stays inside the shelf and the window, and Escape returns to the button.
      const options = shelf.getByRole('button',{name:'Library options',exact:true}), menu = shelf.getByRole('menu',{name:'Library options',exact:true});
      await options.click();
      assert.deepEqual(await menu.getByRole('menuitem').allTextContents(),OPTIONS.map(([label])=>label));
      assert.equal(await options.getAttribute('aria-expanded'),'true');
      assert.equal(await page.evaluate(()=>{
        const m=document.querySelector('.shelf-options-menu').getBoundingClientRect(),s=document.querySelector('.library-shelf').getBoundingClientRect();
        return m.width>0&&m.left>=s.left-0.5&&m.right<=s.right+0.5&&m.top>=s.top&&m.bottom<=window.innerHeight;
      }),true,'options menu placement at '+width+' / '+panel);
      await menu.getByRole('menuitem').first().press('Escape');
      await menu.waitFor({state:'detached'});
      assert.equal(await options.evaluate(button=>button===document.activeElement),true);
    }
    await page.evaluate(()=>{document.getElementById('shelf-host').style.width='';});

    // 6. The menu holds the design's three items and each one acts.
    const options = shelf.getByRole('button',{name:'Library options',exact:true}), menu = shelf.getByRole('menu',{name:'Library options',exact:true});
    for(const [label,call] of OPTIONS) {
      await options.click();
      await menu.getByRole('menuitem',{name:label,exact:true}).click();
      await menu.waitFor({state:'detached'});
      assert.deepEqual(await page.evaluate(()=>window.calls.splice(0)),[call],label+' at '+width);
    }
    // Leaving the menu closes it.
    await options.click();
    await menu.waitFor();
    await shelf.getByLabel('Search nodes',{exact:true}).click();
    await menu.waitFor({state:'detached'});

    // 7. Search is view state: it opens every row with a match, in tree order, and says when nothing matches.
    const search = shelf.getByLabel('Search nodes',{exact:true});
    await search.fill('number');
    const finds = (card,group,asked)=>card.isArea
      ? `${card.area.key} ${card.area.label} ${card.area.description} ${card.area.pages.join(' ')} settings`.toLowerCase().includes(asked)
      : `${card.name} ${card.description||''} ${card.descriptor?.engine||''} ${programOf(card)} ${group.label}`.toLowerCase().includes(asked);
    const shown = asked=>groups.flatMap(group=>cards(group).filter(card=>finds(card,group,asked))).map(named);
    const listed = ()=>shelf.locator('.shelf-node').evaluateAll(buttons=>buttons.map(button=>button.getAttribute('aria-label')));
    assert.ok(shown('number').length>0);
    assert.deepEqual(await listed(),shown('number'));
    assert.equal(await shelf.locator('.shelf-category[aria-expanded="false"]').count(),0);
    assert.equal(await shelf.locator('.family-chips').count(),0);
    // 7b. Design row J7: a program name or a tree row's name finds its cards, and an agent session is not offered as a skill.
    await search.fill('revit');
    assert.deepEqual(await listed(),shown('revit'));
    assert.ok(shown('revit').length>0);
    await search.fill('starts a run');
    assert.deepEqual(await listed(),shown('starts a run'));
    for(const card of catalogue.filter(card=>card.family==='trigger'))assert.ok(shown('starts a run').includes(named(card)),card.name+' is found by its tree row');
    await search.fill('sheet-check');
    await shelf.getByRole('button',{name:'Add sheet-check',exact:true}).waitFor();
    await search.fill('agent-talk');
    await shelf.getByText('Nothing matches.',{exact:true}).waitFor();
    assert.equal(await shelf.locator('.shelf-node').count(),0,'an agent session is not listed as a skill in search');
    await search.fill('no-card-has-this-name');
    await shelf.getByText('Nothing matches.',{exact:true}).waitFor();
    await search.fill('');
    const kept = await page.evaluate(()=>window.ArchHubAPI.getSnapshot().libraryCollapsed);
    assert.equal(kept.includes('trigger'),false,'searching changed no stored choice');
    assert.equal(kept.length,tree.length-1);

    // 8. Closing the row again is kept too, so the next window width starts from the closed tree.
    await trigger.locator('.shelf-category').click();
    await page.waitForFunction(()=>window.ArchHubAPI.getSnapshot().libraryCollapsed.includes('trigger'));
    assert.equal(actions.includes('run')||actions.includes('solve'),false,'the shelf ran nothing');
    const beforeCount = await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.nodes.length);
    const addedTunnel = await page.evaluate(()=>window.ArchHubAPI.addNode('remote_tunnel'));
    assert.ok(addedTunnel?.id,'addNode("remote_tunnel") places the real node');
    assert.equal(await page.evaluate(()=>window.ArchHubAPI.getSnapshot().graph.nodes.length),beforeCount+1);
    await page.evaluate(id=>window.ArchHubAPI.deleteNode(id),addedTunnel.id);
    assert.deepEqual(errors,[]);
    await page.close();
  }
  t.diagnostic('LIBRARY tree PASS at 1009, 1440 and 1920: labels, counts, closed first, options, search, panel widths 200/268/520');
});
