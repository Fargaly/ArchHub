'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {transformSync} = require('esbuild');
const {chromium} = require('playwright');
const xyflow = require('./studio_xyflow.cjs');

const root = path.resolve(__dirname, '../..');
const studio = path.join(root, '01.APP/nodelang/studio');
const read = name => fs.readFileSync(path.join(studio, name), 'utf8');

function findBrowserExecutable() {
  if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE && fs.existsSync(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE)) {
    return process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
  }
  const cache = process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(os.userInfo().homedir, 'AppData/Local/ms-playwright');
  for (const [rx, rel] of [
    [/^chromium-\d+$/, 'chrome-win64/chrome.exe'],
    [/^chromium_headless_shell-\d+$/, 'chrome-headless-shell-win64/chrome-headless-shell.exe']
  ]) {
    const dir = fs.existsSync(cache) && fs.readdirSync(cache).filter(n => rx.test(n)).sort((a, b) => Number(b.split('-').at(-1)) - Number(a.split('-').at(-1)))[0];
    if (dir && fs.existsSync(path.join(cache, dir, rel))) return path.join(cache, dir, rel);
  }
  return 'C:/Program Files/Google/Chrome/Application/chrome.exe';
}

function seedState() {
  return {
    revision: 1,
    profile: {id: 'u1', name: 'Studio Architect', role: 'Lead'},
    settings: [],
    workspaces: [{id: 'ws-1', name: 'Tower Set', register: {number: '101'}}],
    hosts: [{id: 'revit', name: 'Revit', state: 'connected'}],
    approvals: [],
    liveAgents: [{id: 'ag-1', agent: 'Coordinator', name: 'Coordinator', task: 'task-1', status: 'working'}],
    tasks: [{
      id: 'task-1', title: 'Sheet Package', revision: 4, status: 'WIP',
      agents: ['Coordinator'], members: [{name: 'Coordinator', live: true}],
      homePinned: false, checkpointsOnHome: false,
      messages: [{id: 'm1', who: 'Coordinator', text: 'Prepared sheet list.'}]
    }],
    runs: [{id: 'run-1', time: '10:15', kind: 'Schedule', status: 'Retried', results: {'n-src': ['S101', 'S102']}}],
    catalogue: [],
    templates: [],
    mods: [],
    graph: {
      id: 'g-main', scopeKey: 'g-main', name: 'Sheet Package',
      nodes: [
        {
          id: 'sess', title: 'Session', type: 'thing.session', kind: 'Session', fixed: true, agentTask: 'task-1',
          x: 20, y: 40, status: 'Idle',
          params: {prefer_no_agent: true, run_budget: 'Standard', workspace: 'ws-1'},
          paramDefs: [{id: 'prefer_no_agent', group: 'Parameters'}, {id: 'run_budget', group: 'Parameters'}],
          parameterSchema: [
            {key: 'prefer_no_agent', label: 'Prefer steps with no agent', type: 'boolean', editable: true},
            {key: 'run_budget', label: 'Run budget', type: 'text', editable: true}
          ],
          inputs: [], outputs: [{id: 'value', name: 'task', type: 'event'}], children: []
        },
        {
          id: 'n-src', title: 'Collect sheets', type: 'revit.collect', kind: 'Host', pure: true,
          x: 360, y: 60, status: 'Done', output: ['A101'],
          params: {}, parameterSchema: [],
          inputs: [{id: 'in', name: 'model', type: 'text'}],
          outputs: [{id: 'out', name: 'sheets', type: 'text'}]
        },
        {
          id: 'n-eff', title: 'Write sheet PDF', type: 'library.publish_pdf', kind: 'Send', pure: false, approvalRequired: true,
          x: 700, y: 60, status: 'Idle',
          params: {count: 2}, parameterSchema: [{key: 'count', label: 'Copies', type: 'number', dataType: 'number', editable: true}],
          inputs: [{id: 'param:count', name: 'Copies', type: 'number'}, {id: 'in', name: 'sheets', type: 'text'}],
          outputs: [{id: 'out', name: 'pdf', type: 'file'}]
        },
        {
          id: 'n-fail', title: 'Broken export', type: 'revit.export', kind: 'Send', pure: false,
          x: 700, y: 280, status: 'Failed', error: 'Timeout',
          params: {}, parameterSchema: [], inputs: [], outputs: []
        },
        {
          id: 'n-unconf', title: 'Write index file', type: 'thing.file.write', kind: 'Send', pure: false,
          x: 1020, y: 60, status: 'Unconfirmed',
          params: {}, parameterSchema: [], inputs: [], outputs: []
        },
        {
          id: 'n-embed', title: 'Titleblock subflow', type: 'skill', kind: 'Skill', pure: true,
          x: 1020, y: 280, status: 'Idle', embedChanged: true,
          params: {session_file: 'C:/sessions/titleblock.archhub'}, parameterSchema: [],
          inputs: [], outputs: [{id: 'out', name: 'blocks', type: 'elements'}]
        },
        {
          id: 'g-outer', title: 'Outer Group', type: 'group', kind: 'Group', collapsed: true,
          x: 360, y: 300, status: 'Idle', params: {}, parameterSchema: [],
          inputs: [], outputs: [], children: ['g-inner', 'n-grouped']
        },
        {
          id: 'g-inner', title: 'Subgroup', type: 'group', kind: 'Group', parent: 'g-outer', collapsed: false,
          x: 380, y: 340, status: 'Idle', params: {}, parameterSchema: [],
          inputs: [], outputs: [], children: ['n-deep']
        },
        {
          id: 'n-grouped', title: 'Grouped filter', type: 'data.filter', kind: 'Filter', parent: 'g-outer', pure: true,
          x: 400, y: 360, status: 'Done', params: {}, parameterSchema: [],
          inputs: [{id: 'in', name: 'items', type: 'text'}], outputs: [{id: 'out', name: 'filtered', type: 'text'}]
        },
        {
          id: 'n-deep', title: 'Deep Leaf Step', type: 'data.count', kind: 'Check', parent: 'g-inner', pure: true,
          x: 420, y: 420, status: 'Done', params: {}, parameterSchema: [],
          inputs: [], outputs: []
        }
      ],
      wires: [
        {id: 'w-cross', from: 'n-src', fromPort: 'out', to: 'n-grouped', toPort: 'in', type: 'text'},
        {id: 'w-chain', from: 'n-src', fromPort: 'out', to: 'n-eff', toPort: 'in', type: 'text'}
      ]
    }
  };
}

test('Canvas whole design + B:313 court', async t => {
  const browser = await chromium.launch({headless: true, executablePath: findBrowserExecutable()});
  t.after(() => browser.close());
  const page = await browser.newPage({viewport: {width: 1480, height: 940}});
  const errors = [];
  page.on('pageerror', err => { errors.push(err.message); console.error('PAGEERROR:', err.stack || err.message); });
  page.on('console', msg => { if (msg.type() === 'error') console.error('CONSOLE:', msg.text()); });

  await page.route('**/*', route => {
    if (route.request().url().includes('/api/session-files')) {
      return route.fulfill({json: {ok: true, document: {title: 'Titleblock subflow v2', nodes: []}}});
    }
    return route.fulfill({contentType: 'text/html', body: '<!doctype html><html><body><div id="root" style="display:grid;height:100vh"></div></body></html>'});
  });
  await page.goto('http://canvas-court.test/');
  await page.addStyleTag({content: xyflow.css() + read('style.css') + 'html,body{margin:0;height:100%}'});

  for (const sName of ['vendor/react.js', 'vendor/react-dom.js', 'xyflow']) {
    const code = sName === 'xyflow' ? xyflow.script() : read(sName);
    await page.addScriptTag({content: code});
  }

  await page.evaluate(initial => {
    const R = window.React, h = R.createElement;
    window.ReactResizablePanels = {
      Group: ({className, children}) => h('div', {className, style: {display: 'flex', width: '100%', height: '100%'}}, children),
      Panel: ({children}) => h('div', {style: {flex: 1, minWidth: 0, minHeight: 0, height: '100%'}}, children),
      Separator: () => h('div', {className: 'pane-splitter'})
    };
    let state = initial;
    let history = [];
    const listeners = new Set();
    window.recorded = [];
    window.toasts = [];
    window.modals = [];
    window.refuseNextDelete = true;
    const publish = () => { state = {...state, revision: state.revision + 1}; listeners.forEach(fn => fn()); };
    const snap = () => JSON.parse(JSON.stringify(state.graph));

    const api = {
      subscribe: fn => { listeners.add(fn); return () => listeners.delete(fn); },
      nodeIcons: ['canvas', 'docs', 'folder', 'check'],
      wireMenus: [['route', ['Bezier', 'Straight', 'Step']]],
      refreshProjects: async () => state.graph,
      refreshLibraryPorts: async () => {},
      getSnapshot: () => state,
      getSessionPath: () => 'C:/sessions/sheet-package.archhub',
      getSessionDocument: () => ({nodes: state.graph.nodes, wires: state.graph.wires, properties: {checkpointsOnHome: state.tasks[0].checkpointsOnHome, taskContext: {task: 'task-1'}}}),
      readPermissions: async () => ({runMode: 'Ask first', runModes: ['Ask first', 'Accept edits', 'Plan only']}),
      setPermissions: async ({runMode}) => ({runMode, runModes: ['Ask first', 'Accept edits', 'Plan only']}),
      sessionRuns: async () => state.runs,
      socketCompatible: (outP, inP) => outP.type === inP.type || inP.type === 'any',
      connectSockets: async w => {
        history.push(snap());
        state.graph = {...state.graph, wires: [...state.graph.wires, {id: 'w-' + Date.now(), ...w, type: 'text'}]};
        publish();
        return {ok: true};
      },
      setNodeParam: async (id, key, val) => {
        window.recorded.push(['setNodeParam', id, key, val]);
        history.push(snap());
        state.graph = {...state.graph, nodes: state.graph.nodes.map(n => n.id === id ? {...n, params: {...n.params, [key]: val}} : n)};
        publish();
        return {ok: true};
      },
      addNode: async (kind, pos) => {
        const node = {id: 'conv-1', title: 'Convert', type: kind, kind: 'Transform', pure: true, x: pos?.x || 500, y: pos?.y || 200, status: 'Idle', params: {}, parameterSchema: [], inputs: [{id: 'in', name: 'in', type: 'any'}], outputs: [{id: 'out', name: 'out', type: 'number'}]};
        state.graph = {...state.graph, nodes: [...state.graph.nodes, node]};
        publish();
        return node;
      },
      addNote: async (txt, pos) => {
        history.push(snap());
        const note = {id: 'note-' + (state.graph.nodes.length + 1), title: 'Note', type: 'note', kind: 'Note', x: pos?.x || 240, y: pos?.y || 220, params: {text: txt}, inputs: [], outputs: []};
        state.graph = {...state.graph, nodes: [...state.graph.nodes, note]};
        publish();
        return note;
      },
      deleteSelection: async ids => {
        state.graph = {...state.graph, nodes: state.graph.nodes.filter(n => !ids.includes(n.id))};
        publish();
        return {ok: true};
      },
      setGroupCollapsed: async (id, collapsed) => {
        window.recorded.push(['setGroupCollapsed', id, collapsed]);
        state.graph = {...state.graph, nodes: state.graph.nodes.map(n => n.id === id ? {...n, collapsed} : n)};
        publish();
        return {ok: true};
      },
      ungroupNode: async id => {
        window.recorded.push(['ungroupNode', id]);
        const grp = state.graph.nodes.find(n => n.id === id);
        const kids = new Set(grp?.children || []);
        state.graph = {...state.graph, nodes: state.graph.nodes.filter(n => n.id !== id).map(n => kids.has(n.id) ? {...n, parent: grp?.parent || null} : n)};
        publish();
        return {ok: true};
      },
      arrangeGraph: async () => {
        window.recorded.push(['arrangeGraph']);
        history.push(snap());
        state.graph = {...state.graph, nodes: state.graph.nodes.map((n, idx) => ({...n, x: n.x + (idx % 2 ? 12 : 0)}))};
        publish();
        return {ok: true};
      },
      undo: async () => {
        window.recorded.push(['undo']);
        if (history.length) { state.graph = history.pop(); publish(); }
        return {ok: true};
      },
      redo: async () => { window.recorded.push(['redo']); return {ok: true}; },
      recoverRun: async (id, mode) => { window.recorded.push(['recoverRun', id, mode]); return {ok: true}; },
      runNode: async (id, again) => { window.recorded.push(['runNode', id, Boolean(again)]); return {ok: true}; },
      updateEmbeddedSession: async id => {
        window.recorded.push(['updateEmbeddedSession', id]);
        state.graph = {...state.graph, nodes: state.graph.nodes.map(n => n.id === id ? {...n, embedChanged: false, title: 'Titleblock subflow v2'} : n)};
        publish();
        return {ok: true};
      },
      setTaskSession: async (id, patch) => {
        window.recorded.push(['setTaskSession', id, patch]);
        state.tasks = state.tasks.map(tk => tk.id === id ? {...tk, ...patch} : tk);
        publish();
        return {ok: true};
      },
      archiveTask: async id => { window.recorded.push(['archiveTask', id]); return {ok: true}; },
      deleteTask: async id => {
        window.recorded.push(['deleteTask', id]);
        if (window.refuseNextDelete) {
          window.refuseNextDelete = false;
          return {ok: false, error: 'Task lease is busy.'};
        }
        return {ok: true, deleted: true, id};
      }
    };
    window.ArchHubAPI = api;
  }, seedState());

  for (const sName of ['tokens.jsx', 'ds/index.jsx', 'icons.jsx', 'ui.jsx']) {
    await page.addScriptTag({content: transformSync(read(sName), {loader: 'jsx'}).code});
  }

  await page.evaluate(() => {
    const R = window.React, h = R.createElement, api = window.ArchHubAPI;
    window.UI = {
      ...window.UI, A: window.AH, D: window.AH_DS, api,
      matchesShortcut: (id, e) => (id === 'menu.find.a.node' && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f'),
      homeTaskMessages: tk => tk?.messages || [],
      useApp: () => window.appCtx
    };

    window.mountCourt = () => {
      function Host() {
        const [libraryOpen, setLibraryOpen] = R.useState(false);
        const [selectedNodeId, setSelectedNodeId] = R.useState(null);
        const [canvasTabs, saveCanvasTabs] = R.useState({active: 'task-1', tabs: [{id: 'task-1', kept: true, flow: false}], expanded: false});
        const controlsRef = R.useRef(null);
        window.canvasControls = controlsRef;
        window.appCtx = {
          libraryOpen, setLibraryOpen, selectedNodeId, setSelectedNodeId,
          canvasTabs, saveCanvasTabs: async next => { saveCanvasTabs(next); return true; },
          taskFace: 'canvas', setTaskFace: () => {},
          act: fn => Promise.resolve(fn()),
          setToast: msg => window.toasts.push(typeof msg === 'object' ? msg.text : String(msg)),
          show: (kind, payload) => window.modals.push({kind, id: payload?.id}),
          close: () => {},
          closeTaskTab: async id => window.recorded.push(['closeTaskTab', id]),
          setTask: () => {},
          go: route => window.recorded.push(['go', route])
        };
        return h('div', {style: {height: '100vh', display: 'grid', gridTemplateRows: '32px minmax(0,1fr)', position: 'relative'}},
          h('div', null, h('button', {type: 'button', 'aria-label': 'More canvas actions', onClick: () => controlsRef.current?.more()}, 'More')),
          h(window.UI.Canvas, {active: true, embedded: true, externalInspector: false, controlsRef})
        );
      }
      window.ReactDOM.createRoot(document.getElementById('root')).render(h(Host));
    };
  });

  for (const name of ['ds_library.jsx', 'ds_screens.jsx']) {
    await page.addScriptTag({content: transformSync(read(name), {loader: 'jsx'}).code});
  }
  await page.evaluate(() => window.mountCourt());
  await page.locator('[data-graph-node="sess"]').waitFor({timeout: 6000});
  assert.equal(await page.locator('[data-soon]').count(), 0, 'zero Coming soon wrappers');

  // 1. B:313 SessionCard prefer_no_agent working bool toggle
  await page.locator('[data-design="session.panel.parameters"]').click();
  const prefRow = page.locator('[data-design="session.prefer-no-agent"]');
  await prefRow.waitFor();
  assert.match(await prefRow.innerText(), /steps with no agent first/);
  await prefRow.getByRole('switch', {name: 'Prefer steps with no agent'}).click();
  await page.waitForFunction(() => document.querySelector('[data-design="session.prefer-no-agent"]')?.innerText.includes('agent decides'));
  assert.match(await prefRow.innerText(), /agent decides/);

  // 2. Node card approval/recovery labels + embed update bar + Embed menu
  assert.equal(await page.locator('[data-graph-node="n-eff"]').getByRole('button', {name: 'Run · needs Approve', exact: true}).count(), 1);
  assert.equal(await page.locator('[data-graph-node="n-fail"]').getByRole('button', {name: 'Retry', exact: true}).count(), 1);
  assert.equal(await page.locator('[data-graph-node="n-unconf"]').getByRole('button', {name: 'Check result', exact: true}).count(), 1);
  assert.equal(await page.locator('[data-graph-node="n-unconf"]').getByRole('button', {name: 'Run this step again', exact: true}).count(), 1);
  const embedBar = page.locator('[data-graph-node="n-embed"] [data-embed-update]');
  assert.match(await embedBar.innerText(), /Its outputs changed in its file/);
  await embedBar.getByRole('button', {name: 'Update', exact: true}).click();
  await embedBar.waitFor({state: 'detached'});
  await page.locator('[data-graph-node="n-embed"]').getByRole('button', {name: 'Titleblock subflow v2 menu', exact: true}).click();
  assert.equal((await page.evaluate(() => window.modals.at(-1)))?.kind, 'Embed menu');

  // 3. Collapsed group crossing wire socket + footer [Open, Expand, Ungroup] + breadcrumb + Esc
  const outerCard = page.locator('[data-graph-node="g-outer"]');
  assert.equal(await outerCard.locator('[data-port-key="g-outer:in:n-grouped:in"]').count(), 1, 'collapsed group keeps crossing socket');
  for (const btn of ['Open', 'Expand', 'Ungroup']) {
    assert.equal(await outerCard.locator('[data-design="group.' + btn.toLowerCase() + '"]').count(), 1, 'collapsed group footer ' + btn);
  }
  await outerCard.locator('[data-design="group.open"]').click();
  await page.locator('[data-graph-node="g-inner"]').getByRole('button', {name: 'Open', exact: true}).click();
  const crumbNav = page.getByRole('navigation', {name: 'Group breadcrumb'});
  assert.match(await crumbNav.innerText(), /Sheet Package[\s\S]*Outer Group[\s\S]*Subgroup/);
  await crumbNav.getByRole('button', {name: 'Outer Group', exact: true}).click();
  await page.locator('[data-graph-node="n-grouped"]').waitFor();
  await page.getByLabel('Workflow canvas', {exact: true}).press('Escape');
  await page.locator('[data-graph-node="g-outer"]').waitFor();

  // 4. Ctrl+F inline Find a node expanding collapsed ancestor groups
  const canvasStage = page.getByLabel('Workflow canvas', {exact: true});
  await canvasStage.press('Control+f');
  const findBar = page.locator('[data-find-bar]');
  await findBar.waitFor();
  await findBar.getByRole('textbox', {name: 'Find a node', exact: true}).fill('Grouped filter');
  assert.match(await findBar.innerText(), /in Outer Group/);
  await findBar.getByRole('textbox', {name: 'Find a node', exact: true}).press('Enter');
  await page.locator('[data-graph-node="n-grouped"]').waitFor();

  // 5. Inline Note editor via n key, Edit button, and double-click
  await canvasStage.click({position: {x: 40, y: 40}});
  await canvasStage.press('n');
  const noteEditor = page.locator('[data-note-editor]');
  await noteEditor.waitFor();
  await noteEditor.getByRole('textbox', {name: 'Note', exact: true}).fill('Verify stair fire rating');
  await noteEditor.getByRole('button', {name: 'Save', exact: true}).click();
  await noteEditor.waitFor({state: 'detached'});
  await page.waitForFunction(() => document.querySelector('[data-note-node]')?.innerText.includes('Verify stair fire rating'));
  const savedNote = page.locator('[data-note-node]').first();
  assert.match(await savedNote.innerText(), /Verify stair fire rating/);
  await savedNote.getByRole('button', {name: 'Edit note', exact: true}).click();
  await page.locator('[data-note-editor]').getByRole('button', {name: 'Cancel', exact: true}).click();

  // 6. NodeInspector Runs section -> Run view read-only top bar -> Exit run view
  await page.locator('[data-graph-node="n-src"] .node-header').click();
  const insp = page.locator('[data-node-inspector="n-src"]');
  await insp.waitFor();
  await insp.locator('[data-run-row="run-1"]').click();
  const runBar = page.locator('[data-run-view-bar]');
  await runBar.waitFor();
  assert.match(await runBar.innerText(), /Run view · 10:15 · Schedule · Retried/);
  await runBar.getByRole('button', {name: 'Exit run view', exact: true}).click();
  await runBar.waitFor({state: 'detached'});

  // 7. Wire cycle detection + inline Insert converter? offer keeping [data-refused-chip]
  await page.evaluate(() => {
    // Programmatically invoke ReactFlow's onConnect via socket mismatch & cycle
    const propsKey = Object.keys(document.querySelector('.react-flow')).find(k => k.startsWith('__reactFiber$'));
    let fiber = document.querySelector('.react-flow')[propsKey];
    while (fiber && !fiber.memoizedProps?.onConnect) fiber = fiber.return;
    fiber.memoizedProps.onConnect({source: 'n-eff', sourceHandle: 'out', target: 'n-src', targetHandle: 'in'});
  });
  assert.ok((await page.evaluate(() => window.toasts)).some(t => /Cycle detected/i.test(t)), 'cycle toast');
  await page.evaluate(() => {
    const propsKey = Object.keys(document.querySelector('.react-flow')).find(k => k.startsWith('__reactFiber$'));
    let fiber = document.querySelector('.react-flow')[propsKey];
    while (fiber && !fiber.memoizedProps?.onConnect) fiber = fiber.return;
    fiber.memoizedProps.onConnect({source: 'n-src', sourceHandle: 'out', target: 'n-eff', targetHandle: 'param:count'});
  });
  const refused = page.locator('[data-refused-chip]');
  await refused.waitFor();
  assert.match(await refused.innerText(), /Insert converter\?[\s\S]*Needs a text → number converter/);
  await refused.getByRole('button', {name: 'Cancel', exact: true}).click();
  await refused.waitFor({state: 'detached'});

  // 8. Canvas actions Task More menu: Arrange toast, dynamic Undo, Handoff map, Checkpoints on Home, Delete task live-agent warning + single role="alert"
  await page.getByRole('button', {name: 'More canvas actions', exact: true}).click();
  let menu = page.getByRole('menu', {name: 'Canvas actions', exact: true});
  await menu.getByRole('menuitem', {name: 'Arrange', exact: true}).click();
  await page.waitForFunction(() => window.toasts.some(t => /Tidied up: left to right in wire order/i.test(t)));

  await page.getByRole('button', {name: 'More canvas actions', exact: true}).click();
  menu = page.getByRole('menu', {name: 'Canvas actions', exact: true});
  await menu.getByRole('menuitem', {name: 'Undo Arrange · Ctrl Z', exact: true}).click();
  await page.waitForFunction(() => window.toasts.some(t => /Undid: Arrange/i.test(t)));

  await page.getByRole('button', {name: 'More canvas actions', exact: true}).click();
  await page.getByRole('menuitem', {name: 'Handoff map', exact: true}).click();
  const handoff = page.getByRole('dialog', {name: 'Handoff map', exact: true});
  await handoff.waitFor();
  assert.match(await handoff.innerText(), /Who handed work to whom in Sheet Package[\s\S]*Coordinator[\s\S]*Collect sheets/);
  await handoff.getByRole('button', {name: 'Close', exact: true}).click();

  await page.getByRole('button', {name: 'More canvas actions', exact: true}).click();
  await page.getByRole('menuitem', {name: 'Mark checkpoint on Home', exact: true}).click();
  await page.waitForFunction(() => window.recorded.some(r => r[0] === 'setTaskSession' && r[2]?.checkpointsOnHome === true));
  await page.getByRole('button', {name: 'More canvas actions', exact: true}).click();
  assert.equal(await page.getByRole('menuitem', {name: 'Remove checkpoint on Home', exact: true}).count(), 1);
  await page.getByRole('menuitem', {name: 'Delete task…', exact: true}).click();

  const delAsk = page.getByRole('alertdialog', {name: 'Delete task', exact: true});
  await delAsk.waitFor();
  assert.match(await delAsk.innerText(), /An agent is still working on this task: Coordinator/);
  assert.equal(await delAsk.getByRole('alert').count(), 0, 'zero role=alert before deleteError');
  await delAsk.getByRole('button', {name: 'Delete', exact: true}).click();
  await delAsk.getByRole('alert').waitFor();
  assert.equal(await delAsk.getByRole('alert').count(), 1, 'single role=alert on deleteError');
  assert.equal(await delAsk.getByRole('alert').innerText(), 'Task lease is busy.');
  await delAsk.getByRole('button', {name: 'Delete', exact: true}).click();
  await delAsk.waitFor({state: 'detached'});

  assert.deepEqual(errors, []);
});
