'use strict';
// Cold transport courts. LAZYBOOT_COLD_REPORT is emitted by the persisted-store
// HTTP court; the optional desktop courts use only that isolated owner's URL.
// This file launches no application, host, server, scratch fixture or database.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
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
const slice = (from, to) => {
  const start = html.indexOf(from), end = html.indexOf(to, start);
  assert.ok(start >= 0 && end > start, 'actual Studio transport slice: ' + from);
  return html.slice(start, end);
};
const catalogues = slice('    let hosts = [], connectors = [];', '    let nodeLibrary = {};');
const canvasLoader = slice('    let canvasRead = null;', '    let hosts = [], connectors = [];');
const project = slice('    let nodeLibrary = {};', '    window.ARCHHUB_EXISTING_WORKSHOP.setTopologyCanvas(canvas);');
const transcript = slice('    window.ARCHHUB_WORKSHOP_TRANSCRIPT =', '    window.ARCHHUB_GRAPH_CREATE =');
const graphOpen = slice('    window.ARCHHUB_GRAPH_OPEN =', '    window.ARCHHUB_SCOPE_OPEN =');
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
const clone = value => JSON.parse(JSON.stringify(value));

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

test('desktop HTML: cold rail Skills completes its real admitted HTTP read', {skip:!process.env.LAZYBOOT_HTTP_URL}, async () => {
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

test('desktop HTML: Hub, status, Hosts and About share the admitted host total', {skip:!process.env.LAZYBOOT_HTTP_URL}, async () => {
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

test('desktop HTML: group created after lazy boot immediately renders member chips and permits drag-out', {skip:!process.env.LAZYBOOT_HTTP_URL}, async () => {
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

async function mount({authority = false, workspace = false, holdSkills = false} = {}) {
  const manifest = JSON.parse(read('01.APP/nodelang/studio/compiled/manifest.json'));
  for (const file of manifest.files) {
    if (!['studio-lm.jsx', 'studio-suite.jsx'].includes(file.source)) continue;
    assert.equal(file.source_sha256, createHash('sha256').update(read('01.APP/nodelang/studio/' + file.source)).digest('hex'),
      'Studio build is stale for ' + file.source + ': run npm run build:studio');
  }
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53941/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window, requests = [];
  const home = clone(report.home), full = clone(report.workspace);
  // The existing-workshop and clean authority transports name these same two
  // identities differently; aliases never alter the received node/member rows.
  for (const value of [home, full]) {
    value.graph_id ||= value.application_root;
    value.application_root ||= value.graph_id;
    value.root ||= value.scope.current;
    value.authorization = {...value.authorization, session:value.authorization?.session ||
      value.authorization?.browser_sessions?.[0]?.root || 'cold-browser'};
  }
  const savedGraph = full.canvas_root || full.scope.current;
  const index = clone(report.graphs || {ok:true, graphs:[{id:savedGraph,
    title:full.scope.current_label || 'Cold graph', state:'idle', file:'Graph composition'}], current_graph:savedGraph});
  const graphId = index.current_graph;
  const graphTitle = index.graphs.find(row => row.id === graphId).title;
  let releaseSkills;
  const skillGate = holdSkills ? new Promise(resolve => { releaseSkills = resolve; }) : Promise.resolve(report.skills);
  const response = body => ({ok:true, status:200, json:async () => clone(body)});
  win.fetch = async (input, init = {}) => {
    const url = String(input), body = init.body ? JSON.parse(init.body) : null;
    requests.push({url, method:init.method || 'GET', body});
    if (url === '/api/universal/session') return response({token:'court-token', csrf:'court-csrf'});
    if (url === '/api/universal/canvas?screen=home') return response(home);
    if (url === '/api/universal/canvas') return response(full);
    if (url.startsWith('/api/universal/graphs') || url === '/api/universal/graph-open') return response(index);
    if (url === '/api/universal/skills') {
      assert.deepEqual(body, {want:'catalogue'}, 'first Skills open uses the actual catalogue POST');
      return response(await skillGate);
    }
    if (url === '/api/universal/hosts') return response(report.hosts);
    if (url.startsWith('/api/universal/workshop-transcript?')) {
      const query = new URL(url, 'http://court').searchParams;
      assert.equal(query.get('node'), report.graph.page.node);
      assert.equal(query.get('scope'), full.scope.current);
      return response(report.graph.page);
    }
    if (url.startsWith('/api/universal/models')) return response({ok:true, groups:[], selected_route:'', readiness:{state:'no_model'}});
    if (url === '/tools') return response({ok:true, tools:[{id:'connectors', label:'Connectors', state:'off',
      description:'Connected programs', stat_line:'27 hosts', off_sentence:'22 hosts are offline', wire_summary:''}], authority:{}});
    if (url === '/waiting') return response({ok:true, items:[]});
    if (url === '/api/universal/node-library') return response({groups:[], categories:{}, wire_parameters:[]});
    return new Promise(() => {});
  };
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  win.ARCHHUB_THEME = {...theme};
  win.__get = async url => (await win.fetch(url)).json();
  win.__post = async (url, body) => (await win.fetch(url, {method:'POST', body:JSON.stringify(body)})).json();
  win.eval('(function(){ const jget=window.__get, jpost=window.__post, PARAM_SPECS={};\n' +
    project + '\nwindow.__project=projectStudioCanvas; })();');
  const listeners = new Set();
  let canvas = home, topology = {canvas, graph:win.__project(canvas), selected:null};
  const snapshot = () => ({canvas, topology, workshops:[],
    theme:{configuration:canvas.configuration}, applicationUpdate:{state:'idle', current_build:'cold-court'}});
  win.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:snapshot, subscribe:listener => {listeners.add(listener); return () => listeners.delete(listener);},
    watchApplicationUpdate:() => () => {}, refreshConversationCatalog:async () => {},
    setThemeCanvas:value => value.configuration || {theme},
    setTopologyCanvas:value => {canvas=value; topology={canvas, graph:win.__project(value), selected:value.selected};
      for (const listener of listeners) listener(); return value;},
    selectTopology:async (id, roots) => {canvas={...canvas, selected:id, selection:roots || (id ? [id] : [])};
      topology={...topology, canvas, selected:id}; for (const listener of listeners) listener();},
    refreshTopologyCanvas:async () => win.ARCHHUB_EXISTING_WORKSHOP.setTopologyCanvas(await win.__get('/api/universal/canvas')),
  };
  if (authority) {
    win.eval(read('01.APP/nodelang/studio/studio-authority.js'));
    await win.ArchHubStudioAuthority.boot({canvas_key:'court-key'});
  } else {
    win.eval('(function(){ const jget=window.__get, jpost=window.__post;\n' + canvasLoader + catalogues + transcript + '\n})();');
    win.ARCHHUB_LIVE = {sessions:index.graphs, currentGraph:graphId, graph:topology.graph, hosts:[], connectors:[], skills:[], memory:[]};
  }
  win.eval('(function(){const jpost=window.__post;\n' + graphOpen + '\n})();');
  if (workspace) win.ARCHHUB_BOOT = {open_graph:graphId};
  win.eval(read('01.APP/nodelang/studio/vendor/react.js'));
  win.eval(read('01.APP/nodelang/studio/vendor/react-dom.js'));
  for (const compiledOutput of manifest.files) if (compiledOutput.source !== 'mount.jsx') win.eval(read('01.APP/nodelang/studio/compiled/' + compiledOutput.output));
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const flush = action => win.ReactDOM.flushSync(action);
  const wait = async (predicate, note) => {
    for (let attempt=0; attempt<120; attempt+=1) {await new Promise(resolve => win.setTimeout(resolve, 5)); flush(() => {}); if (predicate()) return;}
    assert.ok(predicate(), note);
  };
  const settle = async () => {
    for (let attempt=0; attempt<6; attempt+=1) {await new Promise(resolve => win.setTimeout(resolve, 5)); flush(() => {});}
  };
  const click = element => {assert.ok(!!element, 'requested visible control exists'); flush(() => element.click());};
  const close = () => {try {flush(() => win.__studioRoot.unmount());} finally {win.close();}};
  return {win, doc:win.document, requests, wait, settle, click, flush, close, graphId, graphTitle,
    releaseSkills:() => releaseSkills(report.skills)};
}

for (const authority of [false, true]) {
  const mode = authority ? 'clean authority' : 'existing-workshop';
  test(mode + ': cold first Skills open settles its admitted catalogue path', async () => {
    const ui = await mount({authority, holdSkills:true});
    try {
      assert.equal(ui.requests.filter(row => row.url === '/api/universal/skills').length, 0, 'Home does not read Skills');
      await openSkills(ui);
      if (authority) {
        // The hosted clean server has no Skills route. Its absent reader must
        // settle to the existing empty state instead of retaining READING.
        assert.equal(typeof ui.win.ARCHHUB_LOAD_SKILLS, 'undefined');
        await ui.wait(() => ui.doc.body.textContent.includes('0 SAVED'), 'hosted no-reader Skills state settles');
        assert.doesNotMatch(ui.doc.body.textContent, /Loading catalogue|READING/);
        assert.equal(ui.requests.filter(row => row.url === '/api/universal/skills').length, 0);
        return;
      }
      await ui.wait(() => ui.requests.some(row => row.url === '/api/universal/skills'), 'Skills starts its first read');
      assert.match(ui.doc.body.textContent, /Loading catalogue|READING/, 'pending first read is visible');
      ui.releaseSkills();
      await ui.wait(() => ui.doc.body.textContent.includes(report.skills.result[0].name), 'persisted Skills reaches its mounted panel');
      assert.doesNotMatch(ui.doc.body.textContent, /Loading catalogue|READING/);
      assert.equal(ui.requests.filter(row => row.url === '/api/universal/skills').length, 1);
      assert.equal(ui.win.ARCHHUB_LIVE.skills.length, report.skills.result.length);
    } finally {ui.close();}
  });

  test(mode + ': group member chips appear on the first cold canvas render', async () => {
    const ui = await mount({authority, workspace:true});
    try {
      await ui.wait(() => ui.doc.querySelector('[data-member-chip]'), 'first canvas includes a draggable member chip');
      const group = ui.doc.querySelector('[data-node-id="' + report.group.root + '"]');
      assert.ok(!!group, 'the received group card is drawn');
      const members = report.workspace.nodes.find(row => row.id === report.group.root).members;
      assert.equal(group.querySelectorAll('[data-member-chip]').length, members.length);
      for (const member of members) assert.ok(group.textContent.includes(member.title || member.label || member.id));
      assert.equal(ui.requests.filter(row => row.url === '/api/universal/skills').length, 0, 'canvas opening does not prime Skills');
    } finally {ui.close();}
  });
}

test('cold graph panel rereads its durable message after leaving, reopening, and reselecting', async () => {
  const ui = await mount({workspace:true});
  try {
    const panel = () => ui.doc.querySelector('aside[aria-label="Selection inspector"]');
    await ui.wait(() => panel()?.textContent.includes(report.graph.message), 'first cold graph transcript arrives');
    const firstReads = ui.requests.filter(row => row.url.includes('/workshop-transcript?')).length;
    ui.click(ui.doc.querySelector('button[aria-label="Chats"]'));
    ui.click(ui.doc.querySelector('button[aria-label="Home"]'));
    await ui.wait(() => ui.doc.querySelector('[data-home-page]') && !panel(), 'Home unmounts the graph conversation');
    // Home 082 keeps saved graphs in Chats, rather than the retired Home grid.
    ui.click(ui.doc.querySelector('button[aria-label="Chats"]'));
    const card = () => [...ui.doc.querySelectorAll('[data-left-panel] button')].find(row => row.textContent.includes(ui.graphTitle));
    await ui.wait(card, 'Chats lists the saved graph after leaving Home');
    ui.click(card());
    await ui.wait(() => panel()?.textContent.includes(report.graph.message), 'reopened graph message arrives from transcript readback');
    assert.ok(ui.requests.filter(row => row.url.includes('/workshop-transcript?')).length > firstReads, 'reopen actually rereads history');
    const memberCard = ui.doc.querySelector('.lm-node[data-node-id="' + report.group.root + '"]');
    ui.click(memberCard);
    const canvas = ui.doc.querySelector('[role="region"][aria-label="Workflow canvas"]');
    ui.flush(() => canvas.dispatchEvent(new ui.win.MouseEvent('mousedown', {button:0, bubbles:true, cancelable:true})));
    ui.flush(() => ui.win.dispatchEvent(new ui.win.MouseEvent('mouseup', {button:0, bubbles:true})));
    await ui.wait(() => panel()?.textContent.includes(report.graph.message), 'cleared selection restores the graph message');
    assert.equal(panel().querySelector('[data-chat-local]'), null, 'message came from persisted HTTP readback');
  } finally {ui.close();}
});

test('cold host read gives Hub, footer, Settings badge, Hosts, and About one total', async () => {
  const ui = await mount();
  try {
    const hosts = report.hosts.connectors.filter(row => Object.hasOwn(row, 'drive')
      ? !!row.drive : !/no wire in this build/i.test(String(row.detail || '')));
    if (reportPath) {
      assert.equal(report.hosts.connectors.length, 27, 'actual HTTP cold fixture retains all 27 probe rows');
      assert.equal(hosts.length, 6, 'six admitted hosts must be counted consistently across views');
    }
    const running = hosts.filter(row => row.state === 'connected' || row.state === 'listening').length;
    const ratio = running + '/' + hosts.length;
    ui.click(ui.doc.querySelector('button[title="Settings"]'));
    await ui.wait(() => ui.doc.querySelector('[role="dialog"][aria-label="Settings"]'), 'Settings opens after its deferred canvas read');
    await ui.settle(); // hydrate the theme/initial-tab effects before the next gesture
    const dialog = () => ui.doc.querySelector('[role="dialog"][aria-label="Settings"]');
    assert.ok(!!dialog(), 'Settings opens');
    const nav = settingsNav(ui);
    await nav.tab('Hub');
    await ui.wait(() => ui.doc.body.textContent.includes(ratio + ' hosts'), 'Hub gets the actual host read');
    await ui.wait(() => ui.doc.querySelector('[data-tool-card="connectors"]'), 'Hub gets its Connectors card');
    assert.ok(ui.doc.querySelector('[data-tool-card="connectors"]').textContent.includes(ratio + ' hosts running'), 'Hub uses the shared host tally');
    const hostsTab = await nav.capability('Hosts');
    assert.ok(dialog().querySelector('[data-settings-host-total]').textContent.includes(ratio + ' running'), 'Settings badge agrees with Home and footer');
    ui.click(hostsTab);
    await ui.wait(() => dialog()?.querySelector('[data-host-total]'), 'Hosts panel reports its total');
    assert.equal(dialog().querySelector('[data-host-total]').getAttribute('data-host-total'), String(hosts.length));
    assert.match(dialog().querySelector('[data-connectors-bar]').textContent, new RegExp(ratio + ' running'));
    const aboutTab = await nav.capability('About');
    ui.click(aboutTab);
    await ui.wait(() => dialog()?.querySelector('[data-about-host-total]'), 'About reports the shared host totals');
    const aboutHosts = dialog().querySelector('[data-about-host-total]');
    assert.equal(aboutHosts.getAttribute('data-about-host-total'), String(hosts.length));
    assert.match(aboutHosts.textContent, new RegExp('\\b' + hosts.length + ' configured\\s*·\\s*' + running + ' live\\b'),
      'About visibly names the same configured and running host counts');
    assert.equal(ui.win.ARCHHUB_LIVE.hosts.length, report.hosts.connectors.length);
    assert.equal(ui.win.ARCHHUB_LIVE.connectors.length, report.hosts.connectors.length);
    assert.deepEqual(clone(ui.win.ARCHHUB_LIVE.hosts), report.hosts.connectors, 'host display filtering preserves every raw probe row');
    assert.deepEqual(clone(ui.win.ARCHHUB_LIVE.connectors), report.hosts.connectors, 'connector display filtering preserves every raw probe row');
  } finally {ui.close();}
});
