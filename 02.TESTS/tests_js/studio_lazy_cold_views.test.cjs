'use strict';
// Cold transport courts. LAZYBOOT_COLD_REPORT is emitted by the persisted-store
// HTTP court; the optional desktop courts use only that isolated owner's URL.
// This file launches no application, host, server, scratch fixture or database.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..');
const {settingsNavigator} = require('./settings_navigation_helpers.cjs');
const settingsNav = ui => settingsNavigator({doc:ui.doc, waitFor:ui.wait,
  flush:action => ui.win.ReactDOM.flushSync(action),
  settle:async () => {await new Promise(resolve => ui.win.setTimeout(resolve, 30)); ui.win.ReactDOM.flushSync(() => {});}});
async function openSkills(ui) {
  if (!ui.doc.querySelector('[data-library-tab="skills"]')) {
    ui.click(ui.doc.querySelector('[data-rail-panel="Library"]'));
    await ui.wait(() => ui.doc.querySelector('[data-library-tab="skills"]'), 'Library exposes Skills');
  }
  ui.click(ui.doc.querySelector('[data-library-tab="skills"]'));
}

const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const html = read('01.APP/nodelang/studio/studio.html');

const themeText = read('01.APP/nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const theme = Object.fromEntries([...themeText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(row => [row[1], row[2]]));
const fallbackCanvas = {ok:true, graph_id:'cold-application', application_root:'cold-application',
  root:'cold-scope', canvas_root:'cold-scope', scope:{current:'cold-scope', current_label:'Cold graph',
    trail:[{root:'cold-scope', label:'Cold graph', current:true}]}, revision:7, selected:null, selection:[],
  authorization:{subject:'cold-owner', session:'cold-browser'}, configuration:{theme},
  nodes:[{id:'cold-group', label:'Cold group', kind:'group', assembly:'group', composition:true,
    openable:true, member_count:1, members:[{id:'cold-member', title:'Cold member'}], x:40, y:60,
    params:[], properties:[], ports:[]}], wires:[], catalog:[]};
const fallback = {home:{...fallbackCanvas, canvas_deferred:true, nodes:[], wires:[]}, workspace:fallbackCanvas,
  group:{root:'cold-group', members:[{id:'cold-member', title:'Cold member'}]},
  skills:{ok:true, result:[{id:'cold-skill', name:'Cold persisted skill', runs:0, args:'', when:''}]},
  hosts:{ok:true, connectors:[{id:'revit', name:'Revit', drive:'court.read', state:'connected', detail:'Connected to court'},
    {id:'rhino', name:'Rhino', drive:'court.read', state:'installed', detail:'Installed'},
    {id:'future', name:'Future host', drive:'', state:'unavailable', detail:'No wire in this build'},
    {id:'absent', name:'Absent host', drive:'', state:'absent', detail:'not found on this machine'},
    {id:'unconfigured', name:'Unconfigured host', drive:'', state:'needs-key', detail:'add a Procore token to connect'},
    {id:'listening', name:'Unwired port', drive:'', state:'connected', detail:'answering on :9999'}]},
  graph:{root:'cold-scope', message:'Cold persisted graph message', page:{ok:true, node:'graph:cold-scope',
    conversation_root:'cold-conversation', has_older:false, rows:[{id:'cold-message', who:'You', is_me:true,
      kind:'message', text:'Cold persisted graph message', time:''}]}}};
const reportPath = process.env.LAZYBOOT_COLD_REPORT;
const report = reportPath ? JSON.parse(fs.readFileSync(path.resolve(root, reportPath), 'utf8')) : fallback;
assert.ok(report.home.canvas_deferred && report.home.nodes.length === 0, 'cold report starts with Home only');
assert.ok(report.workspace.nodes.some(row => row.id === report.group.root && row.members?.length),
  'cold first-Workspace projection includes group members');
if (!process.env.LAZYBOOT_HTTP_URL) assert.ok(report.skills.result?.length && report.graph.page.rows?.length,
  'cold HTTP report has durable Skills and graph rows');

// The desktop branch must execute the page, including its authenticated jpost,
// transport owner, integrity checked script loader and mount.jsx. Sliced loaders
// cannot detect a request whose page-level admission/bootstrap never completes.
async function mountDesktop() {
  const {JSDOM} = await import('jsdom');
  const base = process.env.LAZYBOOT_HTTP_URL;
  assert.ok(base && /^http:\/\/127\.0\.0\.1:\d+\/?$/.test(base), 'desktop court uses only its isolated local HTTP owner');
  const dom = new JSDOM('<div id="root"></div><div id="studio-boot"></div>',
    {url:base, runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window, requests = [], scriptErrors = [];
  const started = Date.now();
  const trace = () => requests.filter(row => !row.url.startsWith('/studio/')).map(({url, method, started_ms, response_ms, body_ms, status, error}) =>
    ({url, method, started_ms, response_ms, body_ms, status, error}));
  Object.defineProperty(win.crypto, 'subtle', {value:require('node:crypto').webcrypto.subtle});
  win.TextEncoder = TextEncoder; win.TextDecoder = TextDecoder;
  // Native fetch requires a signal from its own realm.
  win.AbortController = AbortController; win.AbortSignal = AbortSignal;
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  win.fetch = async (input, init = {}) => {
    const url = new URL(String(input), base);
    assert.equal(url.origin, new URL(base).origin, 'no live service or host is contacted');
    const row = {url:url.pathname + url.search, method:init.method || 'GET', headers:init.headers, body:init.body,
      started_ms:Date.now() - started};
    requests.push(row);
    if (url.pathname.startsWith('/studio/')) {
      const file = path.resolve(root, 'nodelang', url.pathname.slice(1));
      assert.ok(file.startsWith(path.join(root, '01.APP/nodelang', 'studio') + path.sep));
      return new Response(fs.readFileSync(file), {status:200});
    }
    try {
      const response = await fetch(url, init);
      row.response_ms = Date.now() - started; row.status = response.status;
      const json = response.json.bind(response);
      response.json = async () => {const body = await json(); row.body_ms = Date.now() - started; return body;};
      return response;
    } catch (error) {row.error = error.message; throw error;}
  };
  const append = win.Element.prototype.appendChild;
  win.Element.prototype.appendChild = function (child) {
    if (child.tagName === 'SCRIPT' && child.src) {
      const url = new URL(child.src);
      const file = path.resolve(root, 'nodelang', url.pathname.slice(1));
      assert.ok(file.startsWith(path.join(root, '01.APP/nodelang', 'studio') + path.sep));
      Promise.resolve().then(() => {
        win.eval(fs.readFileSync(file, 'utf8'));
        child.onload?.();
      }).catch(error => {scriptErrors.push(error); child.onerror?.(error);});
      return child;
    }
    return append.call(this, child);
  };
  win.eval(read('01.APP/nodelang/studio/vendor/react.js'));
  win.eval(read('01.APP/nodelang/studio/vendor/react-dom.js'));
  win.eval(read('01.APP/nodelang/studio/studio-authority.js'));
  const createRoot = win.ReactDOM.createRoot;
  win.ReactDOM.createRoot = (...args) => (win.__studioRoot = createRoot(...args));
  let inline = html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
  const session = {token:process.env.LAZYBOOT_HTTP_TOKEN, csrf:process.env.LAZYBOOT_HTTP_CSRF};
  if (session.token) inline = inline.replace('/*__ARCHHUB_BOOT__*/ null', JSON.stringify(session));
  win.eval(inline);
  const wait = async (predicate, note) => {
    const deadline = Date.now() + 18000;
    while (Date.now() < deadline) {
      if (scriptErrors.length) throw scriptErrors[0];
      assert.doesNotMatch(win.document.getElementById('studio-boot')?.textContent || '', /^REFUSED:/);
      if (predicate()) return;
      await new Promise(resolve => setTimeout(resolve, 10));
    }
    const endState = {skills:win.document.querySelector('[data-skills-count]')?.textContent || '',
      statuses:[...win.document.querySelectorAll('[role="status"], [role="alert"]')].map(node => node.textContent).filter(text => /catalogue|list|skill/i.test(text)),
      modelReads:win.ARCHHUB_MODEL_READ_LOG || [], requests:trace()};
    assert.ok(predicate(), note + '\n' + JSON.stringify(endState));
  };
  const click = element => {assert.ok(element, 'desktop control exists'); win.ReactDOM.flushSync(() => element.click());};
  const close = () => {try {win.__studioRoot?.unmount();} finally {win.close();}};
  try {await wait(() => win.document.querySelector('[data-rail-panel="Library"]') && !win.document.getElementById('studio-boot'), 'full desktop mounts');}
  catch (error) {close(); throw error;}
  return {win, doc:win.document, requests, wait, click, close, trace};
}

test('desktop HTML: cold rail Skills completes its real admitted HTTP read', {skip:!process.env.LAZYBOOT_HTTP_URL && 'Requires isolated LAZYBOOT_HTTP_URL fixture; installed app is out of scope'}, async () => {
  const ui = await mountDesktop();
  try {
    assert.equal(ui.requests.filter(row => row.url === '/api/universal/skills').length, 0, 'Home leaves Skills cold');
    await openSkills(ui);
    await ui.wait(() => ui.doc.querySelector('[data-skills-count]')?.textContent.includes('SAVED'), 'desktop rail catalogue completes');
    assert.doesNotMatch(ui.doc.body.textContent, /Loading catalogue|READING/);
    const names = report.skills?.result?.map(row => row.name) || [process.env.LAZYBOOT_SKILL_NAME || 'cold-first-open'];
    for (const name of names) assert.ok(ui.doc.body.textContent.includes(name), 'HTTP skill row renders: ' + name);
    const request = ui.requests.find(row => row.url === '/api/universal/skills');
    assert.ok(request?.headers['X-ArchHub-Session'], 'actual page jpost carries its browser credential');
    assert.ok(request?.headers['X-ArchHub-CSRF'], 'actual page jpost carries CSRF');
    assert.deepEqual(JSON.parse(request.body), {want:'catalogue'});
    console.info('DESKTOP_SKILLS_HTTP ' + JSON.stringify(ui.trace()));
  } finally {ui.close();}
});

test('desktop HTML: Hub, status, Hosts and About share the admitted host total', {skip:!process.env.LAZYBOOT_HTTP_URL && 'Requires isolated LAZYBOOT_HTTP_URL fixture; installed app is out of scope'}, async () => {
  const ui = await mountDesktop();
  try {
    const hosts = report.hosts.connectors.filter(row => !!row.drive);
    const ratio = hosts.filter(row => ['connected', 'listening'].includes(row.state)).length + '/' + hosts.length;
    ui.click(ui.doc.querySelector('button[title="Settings"]'));
    const dialog = () => ui.doc.querySelector('[role="dialog"][aria-label="Settings"]');
    await ui.wait(() => dialog()?.querySelector('[data-settings54-nav]'), 'real deferred settings opens');
    const nav = settingsNav(ui);
    await nav.tab('Hub');
    assert.ok(ui.doc.body.textContent.includes(ratio + ' hosts'), 'desktop shared host state is visible');
    await ui.wait(() => ui.doc.querySelector('[data-tool-card="connectors"]')?.textContent.includes(ratio + ' hosts running'), 'desktop Hub uses admitted hosts');
    const tab = name => nav.capability(name);
    const hostsTab = await tab('Hosts');
    await ui.wait(() => dialog()?.querySelector('[data-settings-host-total]')?.textContent.includes(ratio + ' running'), 'desktop Settings badge agrees');
    ui.click(hostsTab);
    await ui.wait(() => dialog()?.querySelector('[data-host-total]'), 'desktop Hosts renders');
    assert.equal(dialog().querySelector('[data-host-total]').getAttribute('data-host-total'), String(hosts.length));
    ui.click(await tab('About'));
    await ui.wait(() => dialog()?.querySelector('[data-about-host-total]'), 'desktop About renders');
    assert.equal(dialog().querySelector('[data-about-host-total]').getAttribute('data-about-host-total'), String(hosts.length));
  } finally {ui.close();}
});

test('desktop HTML: group created after lazy boot immediately renders member chips and permits drag-out', {skip:!process.env.LAZYBOOT_HTTP_URL && 'Requires isolated LAZYBOOT_HTTP_URL fixture; installed app is out of scope'}, async () => {
  const ui = await mountDesktop();
  try {
    const owner = ui.win.ARCHHUB_EXISTING_WORKSHOP;
    const graph = report.graphs.graphs.find(row => row.id === report.graphs.current_graph);
    ui.click([...ui.doc.querySelectorAll('[data-home-page] button')].find(row => row.textContent.includes(graph.title)));
    await ui.wait(() => ui.doc.querySelector('[role="region"][aria-label="Workflow canvas"]'), 'desktop opens its cold saved canvas');
    const roots = [report.created_group.root, report.created_group.members[0]];
    await owner.composeTopology('group', roots);
    const created = owner.getSnapshot().topology.canvas.nodes.find(node => node.composition &&
      roots.every(id => node.members?.some(member => member.id === id)));
    assert.ok(created, 'receipt plus authoritative refresh carries new group members');
    const card = () => ui.doc.querySelector('.lm-node[data-node-id="' + created.id + '"]');
    await ui.wait(() => card()?.querySelectorAll('[data-member-chip]').length === roots.length, 'first new-group canvas render has every chip');
    const member = roots[1], chip = card().querySelector('[data-member-chip="' + member + '"]');
    const pointer = (target, type, x, y) => {
      const event = new ui.win.MouseEvent(type, {bubbles:true, cancelable:true, button:0,
        buttons:type === 'pointerup' ? 0 : 1, clientX:x, clientY:y});
      Object.defineProperties(event, {pointerId:{value:7}, pointerType:{value:'mouse'}, isPrimary:{value:true}});
      ui.win.ReactDOM.flushSync(() => target.dispatchEvent(event));
    };
    pointer(chip, 'pointerdown', 0, 0);
    pointer(ui.doc.querySelector('[role="region"][aria-label="Workflow canvas"]'), 'pointermove', 400, 300);
    pointer(ui.win, 'pointerup', 400, 300);
    await ui.wait(() => owner.getSnapshot().topology.canvas.nodes.some(node => node.id === member), 'drag-out restores the member at the parent scope');
    await ui.wait(() => !card()?.querySelector('[data-member-chip="' + member + '"]'), 'drag-out removes its group chip');
    await ui.wait(() => !owner.getSnapshot().topology.pending, 'drag-out receipt and refresh settle before cleanup');
    await owner.composeTopology('ungroup', [created.id]);
  } finally {ui.close();}
});
