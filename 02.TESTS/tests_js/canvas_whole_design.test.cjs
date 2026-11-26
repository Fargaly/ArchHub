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

test('Slice 2 + 3 Canvas whole-design court ([C1]-[C5], [I1], [T1]) at 1920x1032 and 944x968', async t => {
  const browser = await chromium.launch({headless: true, executablePath: findBrowserExecutable()});
  t.after(() => browser.close());
  const page = await browser.newPage({viewport: {width: 1920, height: 1032}});
  const errors = [];
  page.on('pageerror', err => { errors.push(err.message); console.error('PAGEERROR:', err.stack || err.message); });

  await page.route('**/*', route => {
    if (route.request().url().includes('/api/session-files')) {
      return route.fulfill({json: {ok: true, document: {title: 'Titleblock subflow', nodes: []}}});
    }
    return route.fulfill({contentType: 'text/html', body: '<!doctype html><html><body><div id="root" style="height:100%"></div></body></html>'});
  });
  await page.goto('http://127.0.0.1/');
  await page.addStyleTag({content: xyflow.css()});
  await page.addStyleTag({path: path.join(studio, 'style.css')});
  await page.addStyleTag({content: 'html,body,#root{height:100%;margin:0}'});
  // The packaged app serves Inter from /assets/fonts.css; load the same font so measured text matches.
  await page.addStyleTag({content: `@font-face{font-family:Inter;src:url(data:font/woff2;base64,${fs.readFileSync(path.join(studio, 'fonts/inter-variable.woff2')).toString('base64')}) format('woff2');font-weight:100 900}`});

  for (const v of ['react.js', 'react-dom.js']) await page.addScriptTag({path: path.join(studio, 'vendor', v)});
  await page.addScriptTag({content: xyflow.script()});
  const panelsCompiled = path.join(studio, 'compiled/react-resizable-panels.js');
  if (fs.existsSync(panelsCompiled)) {
    await page.addScriptTag({path: panelsCompiled});
  } else {
    await page.evaluate(() => {
      const R = window.React, h = R.createElement;
      window.ReactResizablePanels = {
        Group: ({className, children}) => h('div', {className, style: {display: 'flex', width: '100%', height: '100%'}}, children),
        Panel: ({children}) => h('div', {style: {flex: 1, minWidth: 0, minHeight: 0, height: '100%'}}, children),
        Separator: ({className, 'aria-label': ariaLabel}) => h('div', {className: className || 'pane-splitter', 'aria-label': ariaLabel})
      };
    });
  }
  await page.evaluate(() => { window.fetch = () => new Promise(() => {}); });
  await page.addScriptTag({path: path.join(studio, 'api.js')});

  await page.evaluate(() => {
    const today = new Date().toISOString();
    window.ArchHubCommandRegistry = {
      commands: [
        {id: 'nav.home', label: 'Home', action: {route: 'home'}},
        {id: 'nav.canvas', label: 'Canvas', action: {route: 'canvas'}},
        {id: 'nav.docs', label: 'Docs', action: {route: 'docs'}},
        {id: 'nav.settings', label: 'Settings', action: {route: 'settings'}}
      ]
    };
    Object.assign(window.ArchHubRouteNames, {home: 'Home', canvas: 'Canvas', docs: 'Docs', settings: 'Settings'});
    const s = window.structuredClone(window.ArchHubAPI.getSnapshot());
    s.desktopAccess = {ready: true, admitted: true, subject: 'slice2-court'};
    s.settings.push({id: 'Appearance.Inspector width', value: 320, overridden: true});
    s.workspaces = [{id: 'ws-1', name: 'Demo Block', register: {number: '101'}}];
    s.activeWorkspace = 'ws-1';
    s.hosts = [{id: 'revit', name: 'Revit 2026', state: 'connected'}];
    s.providers = [{id: 'claude-code', name: 'Claude Code', signedIn: true, model: 'Sonnet'}];
    s.agents = [{id: 'claude-code', name: 'Claude Code', status: 'idle'}];
    s.notifications = [{id: 'nt-1', title: 'Sheet check ready', read: false}];
    s.desktop = {automationsPaused: false, workflowActivity: {'C:/sessions/t1.archhub': {armed: 1}}};
    s.homeLayout = {width: 300, collapsed: false, resume: 't-1', order: [], hidden: [], map: {}};
    s.sessionListFilters = {home: 'all'};
    s.tasks = [
      {
        id: 't-1', title: 'Sheet set check', status: 'WIP', workspace: 'ws-1', project: 'ws-1',
        sessionPath: 'C:/sessions/t1.archhub', sessionOpen: true, updated_at: today,
        members: [{id: 'm1', name: 'Claude Code', live: true}], agents: ['Claude Code', 'Codex'],
        plan: ['Collect sheets', 'Publish PDF'], progress: {'Collect sheets': 'done'},
        outputs: [], messages: [{id: 'msg-1', who: 'Claude Code', text: 'Collected 42 sheets.'}]
      },
      {
        id: 't-2', title: 'CAD detail converter', status: 'WIP', workspace: 'ws-1', project: 'ws-1',
        sessionPath: 'C:/sessions/t2.archhub', sessionOpen: false, updated_at: today,
        members: [{id: 'm2', name: 'Codex', live: true}], agents: ['Codex'],
        plan: ['Read DWG'], progress: {}, outputs: [], messages: []
      }
    ];
    s.focusedTask = 't-1';
    s.graph = {
      id: 'g-s2', scopeKey: 'g-s2', name: 'Sheet set check', revision: 1,
      nodes: [
        {
          id: 'sess', fixed: true, type: 'thing.session', kind: 'Session', agentTask: 't-1',
          title: 'Claude Code', x: 40, y: 40, status: 'Idle',
          params: {prefer_no_agent: true, run_budget: '20k', workspace: 'ws-1'},
          paramDefs: [{id: 'prefer_no_agent', group: 'Parameters'}, {id: 'run_budget', group: 'Parameters'}],
          parameterSchema: [
            {key: 'prefer_no_agent', label: 'Prefer steps with no agent', type: 'boolean', editable: true},
            {key: 'run_budget', label: 'Run budget', type: 'text', editable: true}
          ],
          inputs: [{id: 'in-trig', name: 'start', type: 'event'}],
          outputs: [{id: 'value', name: 'task', type: 'event'}],
          children: []
        },
        {
          id: 'n-trig', fixed: false, type: 'trigger.schedule', category: 'Get', kind: 'Trigger',
          title: 'Nightly trigger', pure: true, status: 'Done', x: -400, y: 80,
          params: {}, parameterSchema: [],
          inputs: [], outputs: [{id: 'ev', name: 'tick', type: 'event'}]
        },
        {
          id: 'n-src', fixed: false, type: 'revit.collect', category: 'Get', kind: 'Host',
          title: 'Collect sheets', pure: true, status: 'Done', x: 400, y: 40,
          params: {prefix: 'A-10'},
          parameterSchema: [{key: 'prefix', label: 'Prefix', type: 'text', editable: true}],
          inputs: [{id: 'in', name: 'model', type: 'text'}],
          outputs: [
            {id: 'out', name: 'sheets', type: 'elements', list: true},
            {id: 'meta', name: 'summary', type: 'text'}
          ]
        },
        {
          id: 'n-eff', fixed: false, type: 'export.pdf', category: 'Send', kind: 'Send',
          title: 'Write PDF set', pure: false, approvalRequired: true, status: 'Idle', x: 760, y: 40,
          params: {copies: 2},
          parameterSchema: [{key: 'copies', label: 'Copies', type: 'number', dataType: 'number', editable: true}],
          inputs: [
            {id: 'in-sheets', name: 'sheets', type: 'elements', list: true},
            {id: 'param:copies', name: 'Copies', type: 'number'}
          ],
          outputs: [
            {id: 'pdf', name: 'pdf', type: 'file'},
            {id: 'unused', name: 'log', type: 'file'}
          ]
        },
        {
          id: 'n-arch', fixed: false, type: 'thing.file.write', category: 'Send', kind: 'Send',
          title: 'Archive package', pure: true, status: 'Idle', x: 1120, y: 40,
          params: {}, parameterSchema: [],
          inputs: [{id: 'in-pdf', name: 'pdf', type: 'file'}],
          outputs: [{id: 'out-zip', name: 'zip', type: 'text'}]
        },
        {
          id: 'n-param', fixed: false, type: 'param.value', kind: 'Parameter',
          title: 'Scale factor', pure: true, status: 'Done', x: 400, y: 340,
          params: {value: 1.25},
          parameterSchema: [{key: 'value', label: 'Value', type: 'number', min: 0, max: 5, step: 0.25, editable: true}],
          inputs: [], outputs: [{id: 'val', name: 'value', type: 'number'}]
        },
        {
          id: 'n-embed', fixed: false, type: 'skill', category: 'Decide', kind: 'Skill',
          title: 'Titleblock subflow', pure: true, status: 'Done', x: 760, y: 340,
          params: {session_file: 'C:/sessions/t2.archhub'}, parameterSchema: [],
          inputs: [], outputs: [{id: 'blocks', name: 'blocks', type: 'elements'}]
        },
        {
          id: 'n-frozen', fixed: false, type: 'check.standard', category: 'Check', kind: 'Check',
          title: 'Frozen naming check', pure: true, frozen: true, status: 'Idle', x: 1120, y: 340,
          params: {}, parameterSchema: [], inputs: [], outputs: []
        },
        {
          id: 'n-note', fixed: false, type: 'note', kind: 'Note',
          title: 'Note', x: 40, y: 640,
          params: {text: 'Check parapet flashing detail scale 1:5'},
          inputs: [], outputs: []
        }
      ],
      wires: [
        {id: 'w-sess-in', from: 'n-trig', fromPort: 'ev', to: 'sess', toPort: 'in-trig', type: 'event'},
        {id: 'w-list', from: 'n-src', fromPort: 'out', to: 'n-eff', toPort: 'in-sheets', type: 'elements', rule: 'sheets > 0'},
        {id: 'w-file', from: 'n-eff', fromPort: 'pdf', to: 'n-arch', toPort: 'in-pdf', type: 'file'},
        {id: 'w-num', from: 'n-param', fromPort: 'val', to: 'n-eff', toPort: 'param:copies', type: 'number'}
      ]
    };

    let tabsState = {tabs: [{id: 't-2', title: 'CAD detail converter', kept: true}, {id: 't-1', title: 'Sheet set check', kept: true}], active: 't-1', split: '', collapsed: false};
    const listeners = new Set();
    const notify = () => listeners.forEach(fn => fn());

    window.ArchHubAPI = {
      ...window.ArchHubAPI,
      getSnapshot: () => s,
      subscribe: fn => { listeners.add(fn); return () => listeners.delete(fn); },
      executeAction: (id, cb) => {
        if (id === 'ui.select') return cb();
        if (id === 'projects.controls.activate') return cb.handler();
        return typeof cb === 'function' ? cb() : null;
      },
      supportsAction: () => true,
      setActiveSurface: () => {},
      rememberDesktopView: () => {},
      readDesktopView: () => ({}),
      readHostAvailability: async () => ({}),
      hasSessionEdits: () => false,
      getSessionPath: () => 'C:/sessions/t1.archhub',
      getSessionDocument: () => ({id: 'g-s2', nodes: s.graph.nodes, wires: s.graph.wires, properties: {taskContext: {task: 't-1'}}}),
      listSessionModel: async () => ({groups: [{project: {id: 'ws-1', label: 'Demo Block'}, sessions: [{id: 's1', path: 'C:/sessions/t1.archhub', task: 't-1', title: 'Sheet set check', state: 'open', project: {id: 'ws-1', label: 'Demo Block'}, automation: [], inputLinks: []}]}], recentTask: 't-1'}),
      readSessionModel: async () => ({id: 's1', path: 'C:/sessions/t1.archhub', task: 't-1', title: 'Sheet set check', state: 'open', project: {id: 'ws-1', label: 'Demo Block'}, automation: [], inputLinks: []}),
      sessionInputLinks: async () => [],
      sessionRuns: async () => [],
      readPermissions: async () => ({runMode: 'Ask first', runModes: ['Ask first', 'Accept edits', 'Plan only']}),
      readHomeLayout: async () => ({
        homeLayout: s.homeLayout,
        homeMap: {group: ['Project', 'State', 'Agent'], order: ['Needs you first', 'Name'], card: ['Steps and state', 'State only'], density: ['Comfortable', 'Compact'], done: ['Show', 'Hide'], filter: ['All', 'Running', 'Needs you']}
      }),
      setHomeLayout: async val => { s.homeLayout = val; notify(); return {ok: true}; },
      setDockLayout: async val => { s.dockLayout = {layout: val}; notify(); return {ok: true}; },
      setInspectorWidth: async val => { s.settings.find(r => r.id === 'Appearance.Inspector width').value = val; notify(); return {ok: true}; },
      readCanvasTabs: async () => ({canvasTabs: tabsState}),
      setCanvasTabs: async val => { tabsState = val; notify(); return {canvasTabs: val, ok: true}; },
      readSessionListFilters: async () => ({sessionListFilters: s.sessionListFilters}),
      openTaskGraph: async id => { s.focusedTask = id; notify(); return {ok: true}; },
      refreshProjects: async () => s.graph,
      refreshLibraryPorts: async () => {},
      resolveLinkedSession: async () => ({document: {title: 'Titleblock subflow', nodes: []}}),
      setNodeParam: async (id, k, v) => {
        s.graph = {...s.graph, revision: s.graph.revision + 1, nodes: s.graph.nodes.map(n => n.id === id ? {...n, params: {...n.params, [k]: v}} : n)};
        notify();
        return {ok: true};
      },
      refreshAgentSurface: async () => null
    };
  });

  // The packaged Studio's own file order (03.TOOLS/packaging/compile_studio.cjs); api.js is loaded above.
  const shellFiles = JSON.parse(fs.readFileSync(path.join(root, '03.TOOLS/packaging/compile_studio.cjs'), 'utf8').match(/const names = (\[[^\]]+\])/)[1]).filter(name => name !== 'api.js');
  for (let i = 0; i < shellFiles.length - 1; i++) {
    await page.addScriptTag({content: transformSync(read(shellFiles[i]), {loader: 'jsx'}).code});
  }
  await page.evaluate(() => {
    const baseExec = window.executeAction;
    window.executeAction = (id, context, ...rest) => (id === 'ui.select' || id === 'ui.state') ? context(...rest) : (baseExec ? baseExec(id, context, ...rest) : null);
    window.UI.BaboomSprite = () => null;
  });
  await page.addScriptTag({content: transformSync(read('app.jsx'), {loader: 'jsx'}).code});

  await page.locator('[data-home-map] [data-design="home.card"]').first().waitFor({timeout: 6000});
  await page.locator('[data-home-map] [data-design="home.card"]').first().dblclick();
  await page.locator('.dx-home-root[data-screen="task-file"]').waitFor({timeout: 6000});
  await page.locator('[data-graph-node="n-src"]').waitFor({timeout: 6000});
  // Set zoom to 100% so unscaled card/note dimensions are measured cleanly
  const resetZoom = page.locator('.v22g-canvas .canvas-toolbar button[title="Reset zoom"]');
  if (await resetZoom.count()) await resetZoom.click();
  await page.waitForTimeout(200);

  // [C1] Active Canvas tab 2px copper top bar, bottom-flush docking, & 140..230px flexible width
  const c1 = await page.evaluate(() => {
    const strip = document.querySelector('.dx-workspace > .v22g-strip');
    const activeTab = document.querySelector('.dx-workspace > .v22g-strip .v22g-tab[data-active="true"]');
    const allTabs = [...document.querySelectorAll('.dx-workspace > .v22g-strip .v22g-tab')];
    const cadTab = allTabs.find(el => el.textContent.includes('CAD detail converter'));
    const cs = window.getComputedStyle(activeTab);
    const sr = strip.getBoundingClientRect(), tr = activeTab.getBoundingClientRect();
    return {
      boxShadow: cs.boxShadow,
      borderRadius: cs.borderRadius,
      height: cs.height,
      minWidth: cs.minWidth,
      maxWidth: cs.maxWidth,
      bottomDelta: Math.abs(tr.bottom - sr.bottom),
      cadTabWidth: cadTab ? cadTab.getBoundingClientRect().width : 0
    };
  });
  assert.match(c1.boxShadow, /rgb\(217,\s*119,\s*87\)[\s\S]*inset|inset[\s\S]*rgb\(217,\s*119,\s*87\)/, 'active tab has 2px copper inset top bar: ' + c1.boxShadow);
  assert.equal(c1.borderRadius, '6px 6px 0px 0px');
  assert.equal(c1.height, '30px');
  assert.equal(c1.minWidth, '150px');
  assert.equal(c1.maxWidth, '230px');
  assert.ok(c1.bottomDelta <= 1.5, 'active tab docks flush to bottom of 40px strip: ' + c1.bottomDelta);
  assert.ok(c1.cadTabWidth > 152 && c1.cadTabWidth <= 230, 'CAD detail converter tab expands flexibly beyond 150px: ' + c1.cadTabWidth);

  // [C2] Solid primary fill on Run button at 1920x1032
  const runStyle = await page.evaluate(() => {
    const btn = document.querySelector('[data-design="toolbar.run"]');
    const cs = window.getComputedStyle(btn);
    return {text: btn.textContent.trim(), bg: cs.backgroundColor, color: cs.color, weight: cs.fontWeight};
  });
  assert.equal(runStyle.text, 'Run · needs Approve');
  assert.equal(runStyle.bg, 'rgb(60, 41, 38)', 'prototype .btn-primary accentSoft fill');
  assert.equal(runStyle.color, 'rgb(236, 158, 133)', 'prototype .btn-primary accent ink');
  assert.equal(runStyle.weight, '600');

  // [C3] Note node 220px warm sticky-note card
  const noteMetrics = await page.evaluate(() => {
    const note = document.querySelector('.v22g-note[data-note-node]');
    const cs = window.getComputedStyle(note);
    return {
      width: cs.width,
      padding: cs.padding,
      bg: cs.backgroundColor,
      borderTopWidth: cs.borderTopWidth,
      hasEditBtn: Boolean(note.querySelector('button[aria-label="Edit note"]'))
    };
  });
  assert.equal(noteMetrics.width, '220px');
  assert.equal(noteMetrics.padding, '12px');
  assert.notEqual(noteMetrics.bg, 'rgba(0, 0, 0, 0)');
  assert.notEqual(noteMetrics.bg, 'rgb(21, 21, 26)');
  assert.equal(noteMetrics.borderTopWidth, '1px');
  assert.equal(noteMetrics.hasEditBtn, true);

  // [C4] 300px FlowCard, .prow2 parameter rows, hollow unwired vs filled wired 10x10 sockets, SessionCard 2-col ports, Embed stacked edge, frozen dashed, ParameterNode 88px unclipped
  const c4 = await page.evaluate(() => {
    const stepCard = document.querySelector('[data-graph-node="n-src"] [data-ds-node]');
    const prow = document.querySelector('[data-graph-node="n-src"] [data-parameter="prefix"]');
    const prowInput = prow.querySelector('[data-row-value] > input');
    const unwiredOutDot = document.querySelector('[data-port-key="n-src:out:meta"] [data-socket-dot]');
    const wiredOutDot = document.querySelector('[data-port-key="n-eff:out:pdf"] [data-socket-dot]');
    const unwiredFileDot = document.querySelector('[data-port-key="n-eff:out:unused"] [data-socket-dot]');
    const sessPorts = document.querySelector('.v48-session .v48-session-ports');
    const embedNode = document.querySelector('[data-graph-node="n-embed"] [data-ds-node]');
    const frozenNode = document.querySelector('[data-graph-node="n-frozen"] [data-ds-node]');
    const paramNode = document.querySelector('[data-graph-node="n-param"] [data-spec="parameter"]');
    const dotCs = window.getComputedStyle(unwiredOutDot);
    const wiredCs = window.getComputedStyle(wiredOutDot);
    const unwiredFileCs = window.getComputedStyle(unwiredFileDot);
    return {
      stepWidth: stepCard.style.width,
      prowBg: window.getComputedStyle(prow).backgroundColor,
      prowInputBorder: window.getComputedStyle(prowInput).borderTopWidth,
      prowInputBg: window.getComputedStyle(prowInput).backgroundColor,
      dotWidth: dotCs.width,
      dotHeight: dotCs.height,
      unwiredHasAttr: unwiredOutDot.hasAttribute('data-wired'),
      unwiredBg: dotCs.backgroundColor,
      wiredHasAttr: wiredOutDot.hasAttribute('data-wired'),
      wiredBg: wiredCs.backgroundColor,
      unwiredFileBg: unwiredFileCs.backgroundColor,
      unwiredFileBorder: unwiredFileCs.borderTopColor,
      sessGridCols: window.getComputedStyle(sessPorts).gridTemplateColumns.trim().split(/\s+/).length,
      sessHasInCol: Boolean(sessPorts.querySelector('[data-port-col="in"] [data-side="in"]')),
      sessHasOutCol: Boolean(sessPorts.querySelector('[data-port-col="out"] [data-side="out"]')),
      embedStackedCount: embedNode.querySelectorAll('[data-stacked-edge]').length,
      frozenBorderStyle: window.getComputedStyle(frozenNode).borderTopStyle,
      paramHeight: paramNode.style.height,
      paramScrollH: paramNode.scrollHeight,
      paramClientH: paramNode.clientHeight
    };
  });
  assert.equal(c4.stepWidth, '300px');
  assert.equal(c4.prowBg, 'rgba(0, 0, 0, 0)', 'prow2 row does not fill entire row with solid grey block');
  assert.equal(c4.prowInputBorder, '1px', 'prow2 input has bordered field styling');
  assert.notEqual(c4.prowInputBg, 'rgba(0, 0, 0, 0)');
  assert.equal(c4.dotWidth, '10px');
  assert.equal(c4.dotHeight, '10px');
  assert.equal(c4.unwiredHasAttr, false, 'unwired output socket has no data-wired');
  assert.equal(c4.unwiredBg, 'rgb(21, 21, 26)', 'unwired output socket is hollow (--color-bg-panel)');
  assert.equal(c4.wiredHasAttr, true, 'wired output socket has data-wired');
  assert.equal(c4.wiredBg, 'rgb(126, 193, 142)', 'wired file output socket is filled (--color-ok)');
  assert.equal(c4.unwiredFileBg, 'rgb(21, 21, 26)', 'unwired file output socket stays hollow');
  assert.equal(c4.unwiredFileBorder, 'rgb(126, 193, 142)', 'unwired file output socket keeps typed border');
  assert.equal(c4.sessGridCols, 2, 'SessionCard ports use 2-column band');
  assert.equal(c4.sessHasInCol, true);
  assert.equal(c4.sessHasOutCol, true);
  assert.equal(c4.embedStackedCount, 2, 'Embed node renders stacked card edges');
  assert.equal(c4.frozenBorderStyle, 'dashed', 'Frozen node renders dashed border');
  assert.equal(c4.paramHeight, '88px');
  assert.ok(c4.paramScrollH <= c4.paramClientH + 1, `ParameterNode slider is unclipped (${c4.paramScrollH} <= ${c4.paramClientH})`);

  // [C5] Typed wire colors, list double-stroke hollow cable, & midpoint rule diamond
  const c5 = await page.evaluate(() => {
    const listWire = document.querySelector('path[data-graph-wire="w-list"]');
    const listGap = document.querySelector('path[data-wire-list-gap="w-list"]');
    const fileWire = document.querySelector('path[data-graph-wire="w-file"]');
    const numWire = document.querySelector('path[data-graph-wire="w-num"]');
    const ruleDiamond = document.querySelector('rect[data-wire-rule="sheets > 0"]');
    return {
      listStroke: listWire?.getAttribute('stroke'),
      listAttr: listWire?.getAttribute('data-wire-list'),
      listWidth: listWire ? window.getComputedStyle(listWire).strokeWidth : '',
      gapExists: Boolean(listGap),
      gapWidth: listGap ? window.getComputedStyle(listGap).strokeWidth : '',
      fileStroke: fileWire?.getAttribute('stroke'),
      numStroke: numWire?.getAttribute('stroke'),
      numState: numWire?.getAttribute('data-wire-state'),
      diamondExists: Boolean(ruleDiamond),
      diamondW: ruleDiamond?.getAttribute('width'),
      diamondH: ruleDiamond?.getAttribute('height'),
      diamondStroke: ruleDiamond?.getAttribute('stroke'),
      diamondTransform: ruleDiamond?.getAttribute('transform') || ''
    };
  });
  assert.equal(c5.listStroke, '#d97757', 'elements wire uses --color-accent');
  assert.equal(c5.listAttr, 'true');
  assert.equal(c5.listWidth, '4.2px', 'list outer cable is 4.2px');
  assert.equal(c5.gapExists, true, 'list inner hollow cable path rendered');
  assert.equal(c5.gapWidth, '1.7px', 'list inner hollow cable is 1.7px');
  assert.equal(c5.fileStroke, '#7ec18e', 'file wire uses --color-ok');
  assert.equal(c5.numStroke, '#e5b25a', 'number wire uses --color-warn');
  assert.equal(c5.numState, 'compatible', 'number wire state stays compatible');
  assert.equal(c5.diamondExists, true, 'midpoint rule diamond rendered');
  assert.equal(c5.diamondW, '10');
  assert.equal(c5.diamondH, '10');
  assert.equal(c5.diamondStroke, '#e5b25a');
  assert.match(c5.diamondTransform, /^rotate\(45\s+/);

  // Proof shots for the side-by-side with the prototype; only when CANVAS_PROOF_DIR is set.
  const proof = process.env.CANVAS_PROOF_DIR;
  const shoot = async (size, parts) => {
    if (!proof) return;
    fs.mkdirSync(proof, {recursive: true});
    await page.screenshot({path: path.join(proof, `app-${size}-full.png`)});
    for (const [name, sel] of parts) {
      const el = page.locator(sel).first();
      if (await el.count()) await el.screenshot({path: path.join(proof, `app-${size}-${name}.png`)});
    }
  };
  await shoot('1920', [['tabs', '.dx-workspace > .v22g-strip'], ['note', '.v22g-note[data-note-node]'], ['step', '[data-graph-node="n-src"] [data-ds-node]'],
    ['effect', '[data-graph-node="n-eff"] [data-ds-node]'], ['embed', '[data-graph-node="n-embed"] [data-ds-node]'], ['session', '.v48-session'],
    ['parameter', '[data-graph-node="n-param"] [data-spec="parameter"]'], ['canvas', '.v22g-canvas']]);

  // [C2] Resize to 944x968 and verify zero header.app-header and .v48-toolbar overflow
  await page.setViewportSize({width: 944, height: 968});
  await page.waitForTimeout(250);
  const narrow = await page.evaluate(() => {
    const header = document.querySelector('header.app-header');
    const toolbar = document.querySelector('.dx-workspace > .v22g-strip > .v48-toolbar');
    const strip = document.querySelector('.dx-workspace > .v22g-strip');
    const activeTab = document.querySelector('.dx-workspace > .v22g-strip .v22g-tab[data-active="true"]');
    const tbBtns = [...toolbar.querySelectorAll(':scope > button, :scope > .v48-save > button, :scope > .v48-layout-split > button')]
      .filter(b => b.getClientRects().length > 0 && window.getComputedStyle(b).display !== 'none');
    const tops = tbBtns.map(b => Math.round(b.getBoundingClientRect().top));
    return {
      headerScrollW: header.scrollWidth,
      headerClientW: header.clientWidth,
      stripScrollW: strip.scrollWidth,
      stripClientW: strip.clientWidth,
      toolbarScrollW: toolbar.scrollWidth,
      toolbarClientW: toolbar.clientWidth,
      singleToolbarRow: tops.length > 0 && Math.max(...tops) - Math.min(...tops) <= 4,
      tabBottomDelta: Math.abs(activeTab.getBoundingClientRect().bottom - strip.getBoundingClientRect().bottom)
    };
  });
  assert.ok(narrow.headerScrollW <= narrow.headerClientW + 1, `944x968 header does not overflow (${narrow.headerScrollW} <= ${narrow.headerClientW})`);
  assert.ok(narrow.stripScrollW <= narrow.stripClientW + 1, `944x968 canvas strip does not overflow (${narrow.stripScrollW} <= ${narrow.stripClientW})`);
  assert.ok(narrow.toolbarScrollW <= narrow.toolbarClientW + 1, `944x968 canvas toolbar does not clip (${narrow.toolbarScrollW} <= ${narrow.toolbarClientW})`);
  assert.equal(narrow.singleToolbarRow, true, '944x968 canvas toolbar stays on a single row');
  assert.ok(narrow.tabBottomDelta <= 1.5, '944x968 active tab stays bottom-flush');
  await shoot('944', [['header', 'header.app-header'], ['tabs', '.dx-workspace > .v22g-strip']]);

  // Slice 3: Inspector, node and canvas menus, toasts at 1920x1032.
  await page.setViewportSize({width: 1920, height: 1032});
  await page.waitForTimeout(250);
  await page.locator('[data-graph-node="n-src"] [data-node-card-title]').click();
  await page.waitForTimeout(300);
  // [I1] The design's Inspector: four tabs, eyebrow naming the node family, state line, Parameters/Output/Sockets, Fork from here.
  const props = page.locator('[data-properties-pane]');
  assert.deepEqual(await props.getByRole('tab').allInnerTexts(), ['This task', 'Session', 'Properties', 'Automate']);
  assert.equal(await props.getByRole('tab', {name: 'Properties', exact: true}).getAttribute('aria-selected'), 'true');
  assert.equal(await props.locator('.properties-eyebrow').innerText(), 'GET NODE');
  const nodeInsp = page.locator('[data-node-inspector="n-src"]');
  assert.match(await nodeInsp.locator('[data-insp-state]').innerText(), /Done · Sheet set check\s*Pure: re-solves on every edit\./);
  assert.deepEqual(await nodeInsp.locator('.insp-eyebrow').allInnerTexts(), ['PARAMETERS', 'OUTPUT', 'SOCKETS', 'LOOK', 'RUNS']);
  assert.deepEqual(await nodeInsp.locator('[data-socket-row]').evaluateAll(rows => rows.map(r => r.querySelector('em').textContent)), ['Text · in', 'Elements[] · out', 'Text · out']);
  assert.equal(await nodeInsp.getByRole('button', {name: /^Fork from here/}).count(), 1);
  const tabFit = await props.locator('[role=tablist]').evaluate(el => el.scrollWidth <= el.clientWidth + 1);
  assert.equal(tabFit, true, 'four Inspector tabs fit the 320px pane');
  await shoot('1920', [['inspector', '[data-properties-pane]']]);
  await props.getByRole('tab', {name: 'Session', exact: true}).click();
  assert.equal(await props.locator('.properties-eyebrow').innerText(), 'SESSION SETTINGS');
  await shoot('1920', [['inspector-Session', '[data-properties-pane]']]);
  await props.getByRole('tab', {name: 'This task', exact: true}).click();
  assert.equal(await props.locator('.properties-eyebrow').innerText(), 'THIS TASK');
  await shoot('1920', [['inspector-Thistask', '[data-properties-pane]']]);

  // [T1] A raw network failure reaches the person as one plain line; the raw detail stays out unless Advanced is on.
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('archhub:notice', {detail: {message: '<urlopen error _ssl.c:1000: The handshake operation timed out>'}})));
  const toastEl = page.locator('[data-toast]');
  await toastEl.waitFor();
  assert.match(await toastEl.innerText(), /^Couldn’t reach ArchHub’s servers, trying again/);
  assert.doesNotMatch(await toastEl.innerText(), /urlopen|_ssl/);
  await shoot('1920', [['toast', '[data-toast]']]);
  await toastEl.getByRole('button', {name: 'Dismiss', exact: true}).click();
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('archhub:notice', {detail: {message: 'Export saved'}})));
  assert.equal(await toastEl.locator('span').first().innerText(), 'Export saved', 'ordinary toasts stay as written');

  assert.deepEqual(errors, []);
});
