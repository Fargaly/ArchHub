const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');

const ROOT = path.resolve(__dirname, '../..');
const API_JS = fs.readFileSync(path.join(ROOT, '01.APP/nodelang/studio/api.js'), 'utf8');
const DOCK_JSX = fs.readFileSync(path.join(ROOT, '01.APP/nodelang/studio/dock.jsx'), 'utf8');
const SURFACES_JSX = fs.readFileSync(path.join(ROOT, '01.APP/nodelang/studio/surfaces.jsx'), 'utf8');

const TRIGGER_CATALOGUE = [
  {id: 'tr_manual', cat: 'trigger', title: 'Manual run', sub: 'starts when you press Run', engine: 'trigger.emit', params: {}, ports: {source: [{id: 'fire', type: 'any'}], target: []}},
  {id: 'tr_schedule', cat: 'trigger', title: 'Schedule trigger', sub: 'clock trigger', engine: 'trigger.schedule', params: {schedule: 'every day 08:00', every_seconds: '300', daily_at: '08:00'}, ports: {source: [{id: 'fire', type: 'any'}], target: []}},
  {id: 'tr_file', cat: 'trigger', title: 'File change', sub: 'folder and pattern watcher', engine: 'trigger.file', params: {folder: '', pattern: '*.*', debounce_seconds: '5'}, ports: {source: [{id: 'fire', type: 'any'}], target: []}},
  {id: 'tr_host', cat: 'trigger', title: 'Host event', sub: 'event from Revit or another host', engine: 'trigger.host', params: {event: 'revit.document_saved'}, ports: {source: [{id: 'fire', type: 'any'}], target: []}},
  {id: 'tr_approval', cat: 'trigger', title: 'Approval', sub: 'runs after approval grant', engine: 'trigger.approval', params: {grant_id: 'revit-write'}, ports: {source: [{id: 'fire', type: 'any'}], target: []}},
  {id: 'tr_webhook', cat: 'trigger', title: 'Webhook', sub: 'read-only URL trigger', engine: 'trigger.webhook', params: {url: '', token: ''}, ports: {source: [{id: 'fire', type: 'any'}], target: []}},
  {id: 's_count', cat: 'shape', title: 'Count', sub: 'count items', engine: 'shape.count', params: {}, ports: {source: [{id: 'count', type: 'number'}], target: [{id: 'items', type: 'list'}]}},
];

function makeAdapterHarness(overrides = {}) {
  let savedDock = {layout: null};
  let routerState = {default_model: 'openrouter/free', fallback_models: ['openrouter/free'], free_first: true, providers: {openrouter: {credential: 'wcm://ArchHub/openrouter', enabled: true}}, agents: {}, providerPreferences: {}, models: ['openrouter/free'], requests: []};
  let depsProbed = null;
  let savedDocs = new Map();
  let tasks = [];
  const storageMap = new Map();
  const localStorage = {
    get length() { return storageMap.size; },
    key: i => [...storageMap.keys()][i] ?? null,
    getItem: k => storageMap.has(k) ? storageMap.get(k) : null,
    setItem: (k, v) => { storageMap.set(k, String(v)); },
    removeItem: k => { storageMap.delete(k); },
  };
  const sessionStorage = {getItem: () => null, setItem() {}, removeItem() {}};
  const unref = fn => (...a) => { const h = fn(...a); h?.unref?.(); return h; };
  const uTimeout = unref(setTimeout), uInterval = unref(setInterval);
  const window = {
    structuredClone: globalThis.structuredClone,
    crypto: crypto.webcrypto,
    localStorage,
    sessionStorage,
    innerWidth: 1440,
    ARCHHUB_BOOT: {nograph: true, home_load_ms: 60000, token: 'tok', csrf: 'csrf'},
    document: {hidden: true, addEventListener() {}, querySelectorAll: () => []},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() {},
    requestAnimationFrame: fn => uTimeout(fn, 0),
    cancelAnimationFrame: id => clearTimeout(id),
    setTimeout: uTimeout,
    clearTimeout,
    setInterval: uInterval,
    clearInterval,
    ArchHubStudioAuthority: {
      create: ({get}) => {
        let snapshot = null;
        return {
          load: async () => { snapshot = {canvas: await get('/api/universal/canvas')}; return snapshot.canvas; },
          getSnapshot: () => snapshot,
          clear: () => { snapshot = null; },
          adopt: async c => { snapshot = {canvas: c}; return c; },
          transact: async fn => { const c = await fn(); snapshot = {canvas: c}; return c; },
        };
      },
    },
  };

  const fetch = async (url, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : null;
    const reply = data => ({ok: data.ok !== false, status: data.ok === false ? 400 : 200, json: async () => data});
    if (overrides.handle) {
      const custom = await overrides.handle(url, body);
      if (custom !== undefined) return reply(custom);
    }
    if (url === '/api/universal/desktop-access') return reply({ok: true, admitted: true, state: 'admitted', subject: 'acct-1', email: 'architect@office.example'});
    if (url === '/api/universal/cloud-session') return reply({ok: true, signed_in: true, email: 'architect@office.example', state: 'signed_in'});
    if (url === '/api/commands') return reply({commands: []});
    if (url === '/api/universal/canvas') return reply({root: 'app:system', scope: {current: 'app:system'}, nodes: [], wires: [], catalog: [], workshops: [{root: 'app:workshop'}]});
    if (url === '/api/router/settings') {
      if (body && Object.keys(body).length) {
        if (typeof body.free_first === 'boolean') routerState = {...routerState, ...body};
        else if ('free_first' in body) return reply({ok: false, error: 'free_first must be Boolean'});
        else routerState = {...routerState, ...body};
      }
      return reply({ok: true, ...routerState});
    }
    if (url === '/api/universal/settings-action') {
      const fn = body.function, args = body.args || [];
      if (fn === 'checkDependencies') {
        depsProbed = [{id: 'ifcopenshell', name: 'IfcOpenShell', state: 'Ready', installedVersion: '0.8.0'}];
        return reply({ok: true, result: {dependencies: depsProbed}});
      }
      if (fn === 'readOperations') {
        // Test BOTH omitted dependencies and accidental empty [] from legacy callers via overrides.forceEmptyDepsOnReadOps
        return reply({ok: true, result: {ok: true, settingsScope: 'User', workspacePolicies: {}, ...(overrides.forceEmptyDepsOnReadOps ? {dependencies: []} : depsProbed ? {dependencies: depsProbed} : {})}});
      }
      if (fn === 'setDockLayout') {
        const layout = args[0];
        const nextSaved = {...(savedDock.saved || {})};
        if (args.length === 2 && args[1]) Object.assign(nextSaved, args[1]);
        else if (layout && layout.savedName && !layout.savedChanged) nextSaved[layout.savedName] = layout;
        savedDock = {layout, ...(Object.keys(nextSaved).length ? {saved: nextSaved} : {})};
        return reply({ok: true, result: {dockLayout: savedDock}});
      }
      if (fn === 'readDockLayout' || fn === 'readControls') {
        return reply({ok: true, result: {dockLayout: savedDock, appearanceSettings: []}});
      }
      return reply({ok: true, result: {ok: true}});
    }
    if (url === '/api/session-files') {
      const act = body.action;
      if (act === 'initial') return reply({ok: true, document: {format: 'archhub', version: 1, id: 'init', title: 'Untitled', nodes: [], wires: [], groups: [], notes: [], viewport: {x: 0, y: 0, zoom: 1}, properties: {}}, path: ''});
      if (act === 'catalogue') return reply({ok: true, directory: 'C:/isolated/sessions', items: TRIGGER_CATALOGUE, recent: [], sessions: [...savedDocs.entries()].map(([p, d]) => ({id: d.id, title: d.title, path: p, kind: 'workflow', pinned: !!d.properties?.pinned, nodes: d.nodes.map(n => ({id: n.id}))}))});
      if (act === 'validate') return reply({ok: true, document: body.document});
      if (act === 'save' || act === 'autosave') {
        const p = body.path || ('C:/isolated/sessions/' + body.document.id + '.archhub');
        const rev = (body.document.properties?.revision || 0) + 1;
        const doc = {...body.document, properties: {...(body.document.properties || {}), revision: rev}};
        savedDocs.set(p, doc);
        return reply({ok: true, path: p, document: doc, revision: rev});
      }
      if (act === 'solve') return reply({ok: true, results: {}, solved: [], stale: [], ms: 1});
      return reply({ok: true});
    }
    if (url === '/api/universal/workshop') {
      const fn = body.function, args = body.args || [];
      if (fn === 'createTask') {
        const id = 'session-' + (tasks.length + 1);
        const row = {id, taskId: id, title: args[0], status: 'PLANNED', agents: args[1] ? [args[1]] : [], messages: [], fileMessages: [], agentLog: []};
        tasks.push(row);
        return reply({ok: true, result: row});
      }
      if (fn === 'attachMeetingNotes') return reply({ok: true, result: {ok: true}});
      if (fn === 'setTaskAgentAccess' || fn === 'setTaskDelegate' || fn === 'reassignTask') {
        const [tid, ag, acc] = args;
        const t = tasks.find(r => r.id === tid);
        if (t) {
          t.readOnlyAgents = t.readOnlyAgents || [];
          t.agentAccess = t.agentAccess || {};
          if (fn === 'setTaskAgentAccess') {
            if (acc === 'read-only') { if (!t.agents.includes(ag)) t.agents.push(ag); if (!t.readOnlyAgents.includes(ag)) t.readOnlyAgents.push(ag); t.agentAccess[ag] = 'read-only'; }
            else if (acc === 'edit') { if (!t.agents.includes(ag)) t.agents.push(ag); t.readOnlyAgents = t.readOnlyAgents.filter(x => x !== ag); t.agentAccess[ag] = 'edit'; }
            else if (acc === 'remove') { t.agents = t.agents.filter(x => x !== ag); t.readOnlyAgents = t.readOnlyAgents.filter(x => x !== ag); delete t.agentAccess[ag]; }
          } else {
            t.owner = ag;
            t.agents = [ag, ...t.agents.filter(x => x !== ag)];
            t.agentAccess[ag] = 'edit';
          }
        }
        return reply({ok: true, result: t || {}});
      }
      if (fn === 'listTasks') return reply({ok: true, result: tasks});
      return reply({ok: true, result: {}});
    }
    if (url === '/api/universal/canvas-op') {
      if (body.op === 'trace_node') {
        const [nid, dir, doc] = body.args;
        const hits = (doc?.wires || []).filter(w => dir === 'forward' ? w.from.node === nid : w.to.node === nid).map(w => {
          const targetId = dir === 'forward' ? w.to.node : w.from.node;
          const n = doc.nodes.find(x => x.id === targetId);
          return {id: targetId, title: n.title, type: n.type, direction: dir, relation: `${w.from.node}.${w.from.socket} → ${w.to.node}.${w.to.socket}`};
        });
        return reply({ok: true, result: hits});
      }
      if (body.op === 'save_graph_version') {
        const [label, p] = body.args;
        const d = savedDocs.get(p);
        const cp = {id: 'cp-1', title: label || 'Checkpoint 1', at: '2026-11-26T00:00:00Z', document: JSON.parse(JSON.stringify(d))};
        d.properties = {...(d.properties || {}), checkpoints: [...(d.properties?.checkpoints || []), cp]};
        return reply({ok: true, result: {path: p, document: d, version: {id: cp.id, name: cp.title, nodes: d.nodes}, versions: [{id: cp.id, name: cp.title, nodes: d.nodes}]}});
      }
      if (body.op === 'restore_graph_version') {
        const [vid, p] = body.args;
        const d = savedDocs.get(p);
        const cp = d.properties.checkpoints.find(c => c.id === vid);
        const restored = {...cp.document, properties: {...cp.document.properties, checkpoints: d.properties.checkpoints}};
        savedDocs.set(p, restored);
        return reply({ok: true, result: {path: p, document: restored, versions: d.properties.checkpoints}});
      }
      if (body.op === 'remove_graph') {
        savedDocs.delete(body.args[0]);
        return reply({ok: true, result: {ok: true, removed: body.args[0]}});
      }
      return reply({ok: true, result: []});
    }
    return reply({ok: true, result: []});
  };

  const context = vm.createContext({
    window, document: window.document, fetch, URL, URLSearchParams,
    CustomEvent: class { constructor(type, opts) { this.type = type; this.detail = opts?.detail; } },
    setTimeout: uTimeout, clearTimeout, setInterval: uInterval, clearInterval, AbortSignal: globalThis.AbortSignal, console,
  });
  vm.runInContext(API_JS, context);
  return {api: window.ArchHubAPI, window, context, storageMap, savedDocs, getSavedDock: () => savedDock, tasks};
}

test('Item #2 & #8: checkDependencies survives readOperations and setRouterSettings toggles free_first', async () => {
  const {api} = makeAdapterHarness({forceEmptyDepsOnReadOps: true});
  await api.ready;
  await api.checkDependencies();
  assert.equal(api.getSnapshot().dependencies.length, 1);
  assert.equal(api.getSnapshot().dependencies[0].id, 'ifcopenshell');

  await api.refreshSettingsOperations();
  assert.equal(api.getSnapshot().dependencies.length, 1, 'readOperations must never wipe probed dependencies');

  const off = await api.setRouterSettings({free_first: false});
  assert.equal(off.free_first, false);
  const on = await api.setRouterSettings({free_first: true});
  assert.equal(on.free_first, true);
});

test('Item #7: dock.jsx uses zero localStorage keys and persists extended + named layouts via Settings owner', async () => {
  const {transformSync} = require('esbuild');
  const {api, window, context, storageMap, getSavedDock} = makeAdapterHarness();
  await api.ready;

  // Load pure dockModel + verify zero archhub.dock.* localStorage keys exist in dock.jsx runtime
  const compiledDock = transformSync(DOCK_JSX, {loader: 'jsx'}).code;
  vm.runInContext(compiledDock, context);
  const dm = window.UI.dockModel;
  assert.ok(dm.PANELS.thread, 'dockModel includes thread');
  const withThreadAndBottom = dm.place(dm.presetLayout('Meeting', 1440), 'thread', 0, 'above');
  const floated = dm.floatPanel(withThreadAndBottom, 'map', {x: 200, y: 100, w: 300, h: 240});
  const savedResp = await api.setDockLayout({...floated, savedName: 'Morning standup'});
  assert.equal(savedResp.dockLayout.saved['Morning standup'].savedName, 'Morning standup');
  assert.equal(getSavedDock().layout.float[0].id, 'map');
  assert.equal([...storageMap.keys()].some(k => k.includes('dock')), false, 'zero localStorage dock keys');
});

test('Item #9 & #10: all 6 Automations Trigger buttons, traceNode, versions, flags, pinned output, and Feedback work', async () => {
  const {transformSync} = require('esbuild');
  const {api, window, context, savedDocs, tasks} = makeAdapterHarness();
  await api.ready;

  const actions = {};
  window.executeAction = (id, ctx, ev) => actions[id](ctx, ev);
  window.registerActions = (map, fns) => {
    for (const [k, name] of Object.entries(map)) actions[k] = fns[name];
  };
  window.React = {createElement: () => null, Fragment: 'fragment', useState: v => [v, () => {}], useEffect() {}, useRef: v => ({current: v})};
  window.UI = {
    A: {ok: 'green', warn: 'amber'}, D: {Toggle: () => null}, api,
    useData: () => api.getSnapshot(), useApp: () => ({}),
    Btn: () => null, Card: () => null, Chip: () => null, Heading: () => null, Empty: () => null, Table: () => null,
  };
  const compiledSurfaces = transformSync(SURFACES_JSX, {loader: 'jsx'}).code;
  vm.runInContext(compiledSurfaces, context);

  // Start with no open session and empty libraryPorts to prove Automations Trigger buttons self-initialize cleanly.
  const navigated = [];
  const u = {act: fn => fn(), go: (route, target) => navigated.push([route, target])};
  const expectedEngines = {
    'Manual': 'trigger.emit',
    'Schedule': 'trigger.schedule',
    'File changed': 'trigger.file',
    'Host event': 'trigger.host',
    'Approval granted': 'trigger.approval',
    'Webhook': 'trigger.webhook',
  };
  for (const [label, engine] of Object.entries(expectedEngines)) {
    await actions['projects.surfaces.AsyncConstNAwaitU.3']({api, t: label, u});
    const added = api.getSnapshot().graph.nodes.at(-1);
    assert.equal(added.type, engine, `Trigger button "${label}" should create ${engine}`);
  }
  assert.equal(navigated.length, 6);
  assert.equal(savedDocs.size >= 1, true, 'Trigger creation persists to .archhub session file');

  // Add a downstream node, wire it, trace forward, set flags, pin edited JSON output, save & restore version
  const countNode = await api.addNode('s_count', {x: 420, y: 100});
  const firstTrigger = api.getSnapshot().graph.nodes[0];
  await api.connectSockets({from: firstTrigger.id, fromPort: 'fire', to: countNode.id, toPort: 'items'});
  const traced = await api.traceNode(firstTrigger.id, 'forward');
  assert.equal(traced.length, 1);
  assert.equal(traced[0].id, countNode.id);

  await api.setNodePresentation(countNode.id, {color: '#d97757'});
  assert.equal(api.getSnapshot().graph.nodes.find(n => n.id === countNode.id).color, '#d97757');
  await api.setNodeFlags(countNode.id, {color: '', frozen: true});
  const afterFlags = api.getSnapshot().graph.nodes.find(n => n.id === countNode.id);
  assert.equal(afterFlags.color, undefined);
  assert.equal(afterFlags.frozen, true);

  await api.setPinnedOutput(countNode.id, '[{"count": 42}]');
  assert.equal(api.getSnapshot().graph.nodes.find(n => n.id === countNode.id).pinned, true);

  const ver = await api.saveGraphVersion('Before delete');
  assert.equal(ver.id, 'cp-1');
  assert.equal(api.getSnapshot().graph.versions.length, 1);
  await api.deleteNode(countNode.id);
  assert.equal(api.getSnapshot().graph.nodes.some(n => n.id === countNode.id), false);
  await api.restoreGraphVersion('cp-1');
  assert.equal(api.getSnapshot().graph.nodes.some(n => n.id === countNode.id), true);

  // Feedback creates a Workshop task and checkFeedback reads agent reply from agentLog
  const sent = await api.sendFeedback('Make schedule picker keyboard-friendly');
  assert.equal(api.getSnapshot().feedback.length, 1);
  tasks[0].status = 'DONE';
  tasks[0].agentLog.push({id: 'm1', who: 'BABOOM', text: 'Keyboard navigation landed.'});
  await api.checkFeedback(sent.id);
  assert.equal(api.getSnapshot().feedback[0].status, 'DONE');
  assert.equal(api.getSnapshot().feedback[0].response, 'Keyboard navigation landed.');

  // Who works on it: continueTaskWithAgent / setTaskDelegate / setTaskAgentAccess (read-only, edit, remove)
  await api.setTaskAgentAccess(sent.id, 'Gemini CLI', 'read-only');
  assert.equal(api.getSnapshot().tasks[0].agentAccess['Gemini CLI'], 'read-only');
  await api.setTaskAgentAccess(sent.id, 'Gemini CLI', 'edit');
  assert.equal(api.getSnapshot().tasks[0].agentAccess['Gemini CLI'], 'edit');
  await api.continueTaskWithAgent(sent.id, 'Claude Code');
  assert.equal(api.getSnapshot().tasks[0].owner, 'Claude Code');
  await api.setTaskAgentAccess(sent.id, 'Gemini CLI', 'remove');
  assert.equal(api.getSnapshot().tasks[0].agents.includes('Gemini CLI'), false);
});
