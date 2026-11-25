'use strict';
const {test, before, after} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {transformSync} = require('esbuild');
const {chromium} = require('playwright');

const root = path.resolve(__dirname, '../..');
const studio = path.join(root, '01.APP/nodelang/studio');

function findBrowserExecutable() {
  if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE && fs.existsSync(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE)) {
    return process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
  }
  const cache = process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(os.userInfo().homedir, 'AppData/Local/ms-playwright');
  const shell = fs.readdirSync(cache).filter(name => /^chromium_headless_shell-\d+$/.test(name))
    .sort((a, b) => Number(b.split('-').at(-1)) - Number(a.split('-').at(-1)))[0];
  if (shell) return path.join(cache, shell, 'chrome-headless-shell-win64/chrome-headless-shell.exe');
  const full = fs.readdirSync(cache).filter(name => /^chromium-\d+$/.test(name))
    .sort((a, b) => Number(b.split('-').at(-1)) - Number(a.split('-').at(-1)))[0];
  return path.join(cache, full, 'chrome-win64/chrome.exe');
}

function loadRegistryPayload() {
  const python = process.env.ARCHHUB_TEST_PYTHON || process.env.ARCHHUB_COURT_PYTHON || 'python';
  const raw = execFileSync(
    python,
    ['-c', 'import json, sys; sys.path.insert(0, "01.APP"); from nodelang.command_registry import payload; print(json.dumps(payload()))'],
    {cwd: root, encoding: 'utf8', timeout: 25000, windowsHide: true}
  );
  return JSON.parse(raw);
}

let browser;
let page;
let registry;

before(async () => {
  registry = loadRegistryPayload();
  browser = await chromium.launch({headless: true, executablePath: findBrowserExecutable()});
  page = await browser.newPage({viewport: {width: 1440, height: 900}});
  await page.route('https://menus.test/**', route => route.fulfill({
    contentType: 'text/html',
    body: [
      '<!doctype html><html><head><meta charset="utf-8"></head><body>',
      '<main data-home-page>',
      '  <div data-project="Tower Package" data-design="group.frame"><span data-design="group.title">Tower Package</span><button data-design="group.collapse" aria-label="Collapse Tower Package">-</button></div>',
      '  <div data-project="Folded Wing" data-design="group.node"><span data-design="group.title">Folded Wing</span><button aria-label="Expand Folded Wing">Expand</button></div>',
      '  <div data-home-task="task-alpha" data-home-session-path="C:/probe/alpha.archhub"><button type="button" id="card-alpha">Alpha task</button></div>',
      '  <div id="home-empty" style="width:180px;height:80px">Empty Home Space</div>',
      '</main>',
      '<div id="menu-host"></div>',
      '</body></html>'
    ].join('\n')
  }));
  await page.goto('https://menus.test/');
  await page.addStyleTag({path: path.join(studio, 'style.css')});
  for (const vendorFile of ['react.js', 'react-dom.js']) {
    await page.addScriptTag({path: path.join(studio, 'vendor', vendorFile)});
  }
  await page.evaluate(reg => {
    window.calls = [];
    window.menuState = {
      copied: true,
      update: {available: true},
      watch: {capability: true, reason: ''},
      workspaces: [{id: 'ws-tower', name: 'Tower Package', canvas: 'C:/probe/tower.archhub'}],
      approvals: [{id: 'ap-hold', approvalKind: 'canvas', nodeId: 'n-held', status: 'pending'}],
      tasks: [
        {id: 'task-alpha', title: 'Alpha task', project: 'Tower Package', workspace: 'ws-tower', sessionPath: 'C:/probe/alpha.archhub', status: 'WIP', homePinned: false, pinnedMessages: [], workflow: [{id: 'n-step', type: 'script.python'}]},
        {id: 'task-beta', title: 'Beta task', project: 'Tower Package', workspace: 'ws-tower', sessionPath: 'C:/probe/beta.archhub', status: 'WIP', homePinned: false, pinnedMessages: []}
      ],
      graph: {
        id: 'g-1',
        undoLabel: 'Add wall check',
        redoLabel: 'Wire sheet output',
        nodes: [
          {id: 'n-up', title: 'Upstream source', type: 'data.text', x: 60, y: 120, inputs: [], outputs: [{id: 'out'}], parameterSchema: [], status: 'Done'},
          {id: 'n-step', title: 'Sheet check', type: 'script.python', x: 240, y: 120, inputs: [{id: 'in'}], outputs: [{id: 'out'}], parameterSchema: [{key: 'prefix', editable: true}], status: 'Idle', frozen: false, bypassed: false, pinned: false},
          {id: 'n-done', title: 'Finished count', type: 'script.python', x: 620, y: 120, inputs: [{id: 'in'}], outputs: [{id: 'out'}], parameterSchema: [], status: 'Done', output: ['ok']},
          {id: 'n-effect', title: 'Send issue mail', type: 'mail.send', pure: false, approvalRequired: true, x: 300, y: 300, inputs: [{id: 'in'}], outputs: [], parameterSchema: [], status: 'Idle'},
          {id: 'n-held', title: 'Held door edit', type: 'revit.write', openable: true, x: 480, y: 300, inputs: [], outputs: [], parameterSchema: [], status: 'Waiting for approval'},
          {id: 'n-tunnel', title: 'Remote tunnel', type: 'network.tunnel', x: 660, y: 300, params: {armed: true}, members: [{id: 'm-1', title: 'Codex', live: true}], inputs: [], outputs: [], parameterSchema: [], status: 'Running'},
          {id: 'n-note', title: 'Note', type: 'note', params: {text: 'Check north stair'}, x: 100, y: 420, inputs: [], outputs: [], parameterSchema: []},
          {id: 'n-group', title: 'Door checks', type: 'note', children: ['n-step', 'n-done'], collapsed: false, x: 200, y: 80, inputs: [], outputs: [], parameterSchema: []},
          {id: 'n-embed', title: 'Linked facade', type: 'skill', params: {session_file: 'C:/probe/beta.archhub'}, x: 860, y: 180, inputs: [], outputs: [], parameterSchema: [], status: 'Idle'}
        ],
        wires: [
          {id: 'w-1', from: 'n-up', fromPort: 'out', to: 'n-step', toPort: 'in', rule: '', enabled: true},
          {id: 'w-2', from: 'n-step', fromPort: 'out', to: 'n-done', toPort: 'in', rule: 'count > 0', enabled: false}
        ]
      },
      settings: []
    };
    const rec = name => async (...args) => {
      window.calls.push([name, ...args.filter(a => typeof a !== 'function')]);
      return {ok: true, taskId: 'dup-task'};
    };
    const api = {
      hasCopiedNodes: () => window.menuState.copied,
      getSessionPath: () => 'C:/probe/alpha.archhub',
      getSessionDocument: () => ({properties: {taskContext: {task: 'task-alpha'}}}),
      sameSessionPath: (a, b) => Boolean(a && b && String(a).replaceAll('\\', '/').toLowerCase() === String(b).replaceAll('\\', '/').toLowerCase()),
      pasteNodes: rec('api.pasteNodes'),
      arrangeGraph: rec('api.arrangeGraph'),
      undo: rec('api.undo'),
      redo: rec('api.redo'),
      runNode: rec('api.runNode'),
      runToHere: rec('api.runToHere'),
      runSelection: rec('api.runSelection'),
      setNodeFlags: rec('api.setNodeFlags'),
      duplicateNodes: rec('api.duplicateNodes'),
      copyNodes: rec('api.copyNodes'),
      cutNodes: rec('api.cutNodes'),
      deleteNode: rec('api.deleteNode'),
      deleteSelection: rec('api.deleteSelection'),
      forkNode: rec('api.forkNode'),
      alignNodes: rec('api.alignNodes'),
      moveNodes: rec('api.moveNodes'),
      setGroupCollapsed: rec('api.setGroupCollapsed'),
      ungroupNode: rec('api.ungroupNode'),
      deleteGroup: rec('api.deleteGroup'),
      setWireEnabled: rec('api.setWireEnabled'),
      insertConvertOnWire: rec('api.insertConvertOnWire'),
      deleteWire: rec('api.deleteWire'),
      enterSession: rec('api.enterSession'),
      detachSession: rec('api.detachSession'),
      refreshLibraryPorts: rec('api.refreshLibraryPorts'),
      refreshProjects: rec('api.refreshProjects'),
      approve: rec('api.approve'),
      decline: rec('api.decline'),
      setNodeParam: rec('api.setNodeParam'),
      detachMember: rec('api.detachMember'),
      stopEverything: rec('api.stopEverything'),
      installUpdate: rec('api.installUpdate'),
      checkForUpdates: rec('api.checkForUpdates'),
      windowAction: rec('api.windowAction'),
      selectWorkspace: rec('api.selectWorkspace'),
      duplicateHomeTask: rec('api.duplicateHomeTask'),
      addAutomation: rec('api.addAutomation'),
      setTaskSession: rec('api.setTaskSession'),
      archiveTask: rec('api.archiveTask'),
      createTask: rec('api.createTask'),
      pinTaskMessage: rec('api.pinTaskMessage')
    };
    const rootHost = window.ReactDOM.createRoot(document.getElementById('menu-host'));
    window.menuSeq = 0;
    const syncRender = node => {
      if (typeof window.ReactDOM.flushSync === 'function') window.ReactDOM.flushSync(() => rootHost.render(node));
      else rootHost.render(node);
    };
    window.appStub = {
      task: 'task-alpha',
      taskFace: 'canvas',
      canvasFace: 'canvas',
      canvasTabs: {active: 'task-alpha', tabs: [{id: 'task-alpha', kept: true}]},
      close: () => { window.calls.push(['u.close']); syncRender(null); },
      act: fn => fn(),
      setTaskFace: face => { window.appStub.taskFace = face; window.calls.push(['u.setTaskFace', face]); },
      setCanvasFace: face => { window.appStub.canvasFace = face; window.calls.push(['u.setCanvasFace', face]); },
      setSelectedNodeId: id => window.calls.push(['u.setSelectedNodeId', id]),
      openTaskFile: (id, face) => { window.calls.push(['u.openTaskFile', id, face || 'canvas']); return {ok: true}; },
      openSavedSession: p => { window.calls.push(['u.openSavedSession', p]); return {ok: true}; },
      openSystem: p => { window.calls.push(['u.openSystem', p]); return {ok: true}; },
      go: r => window.calls.push(['u.go', r]),
      schedule: id => window.calls.push(['u.schedule', id]),
      trace: (id, dir) => window.calls.push(['u.trace', id, dir]),
      setHomeInspector: v => window.calls.push(['u.setHomeInspector', v]),
      setToast: v => window.calls.push(['u.setToast', v?.text || v]),
      confirm: (title, fn) => { window.calls.push(['u.confirm', title]); return fn(); },
      show: (kind, props = {}) => {
        window.calls.push(['u.show', kind, props.id || props.wireId || props.title || '']);
        if (['Node menu', 'Embed menu', 'Group menu', 'Wire menu', 'Selection menu', 'Canvas menu', 'Tray', 'Task message menu', 'Surface menu'].includes(kind)) {
          syncRender(window.React.createElement(window.UI.ContextMenu, {...props, key: 'm-' + (++window.menuSeq), kind, close: window.appStub.close}));
        }
      }
    };
    window.canvasStub = {
      point: {x: 320, y: 180},
      select: ids => window.calls.push(['canvas.select', ids]),
      selectAll: () => window.calls.push(['canvas.selectAll']),
      fit: () => window.calls.push(['canvas.fit']),
      group: () => { window.calls.push(['canvas.group']); return {ok: true}; },
      inspectWire: id => window.calls.push(['canvas.inspectWire', id])
    };
    window.AHIcon = () => null;
    window.ArchHubCommandRegistry = reg;
    window.ArchHubRouteNames = Object.fromEntries(reg.commands.filter(c => c.action.route).map(c => [c.action.route, c.label]));
    window.UI = {
      api,
      useData: () => window.menuState,
      useApp: () => window.appStub,
      useAction: () => ({run: fn => fn()}),
      ActionStatus: () => null,
      productLabel: (label, settings) => (settings?.labelPrefix ? settings.labelPrefix + label : label),
      shortcutFor: id => reg.commands.find(c => c.id === id)?.shortcut || '',
      bindActions: (names, handlers) => (id, ...args) => handlers[names[id]](...args)
    };
    document.querySelector('[data-project="Tower Package"] button').addEventListener('click', () => {
      window.calls.push(['dom.collapseTower']);
    });
    document.addEventListener('contextmenu', event => window.UI.openSurfaceMenu(event, window.menuState, window.appStub));
    window.openTestMenu = (kind, props = {}) => {
      window.calls.length = 0;
      syncRender(window.React.createElement(window.UI.ContextMenu, {
        key: 'm-' + (++window.menuSeq),
        kind,
        canvas: window.canvasStub,
        close: window.appStub.close,
        ...props
      }));
    };
    window.readMenuGroups = () => [...document.querySelectorAll('.context-menu .context-group')].map(grp =>
      [...grp.querySelectorAll('button > span')].map(span => span.textContent)
    );
  }, registry);
  const compiled = transformSync(fs.readFileSync(path.join(studio, 'context-menus.jsx'), 'utf8'), {loader: 'jsx'}).code;
  await page.addScriptTag({content: compiled});
});

after(async () => {
  await browser?.close();
});

test('Canvas menu renders 4 groups, dynamic Undo/Redo labels, and Show/Hide thread toggle', async () => {
  await page.evaluate(() => {
    window.appStub.taskFace = 'canvas';
    window.appStub.canvasFace = 'canvas';
    window.openTestMenu('Canvas menu');
  });
  await page.getByRole('menu', {name: 'Canvas menu'}).waitFor();
  assert.deepEqual(await page.evaluate(() => window.readMenuGroups()), [
    ['Add node here', 'Paste here', 'Add note'],
    ['Find a node', 'Select all', 'Arrange', 'Fit'],
    ['Undo Add wall check', 'Redo Wire sheet output'],
    ['Ask the agent', 'Show the thread']
  ]);
  await page.locator('[data-design="menu.show-the-thread"]').click();
  assert.equal(await page.evaluate(() => window.appStub.canvasFace), 'split');
  assert.equal(await page.evaluate(() => window.appStub.taskFace), 'split');

  await page.evaluate(() => {
    window.menuState.graph.undoLabel = '';
    window.menuState.graph.redoLabel = '';
    window.openTestMenu('Canvas menu');
  });
  assert.deepEqual(await page.evaluate(() => window.readMenuGroups()), [
    ['Add node here', 'Paste here', 'Add note'],
    ['Find a node', 'Select all', 'Arrange', 'Fit'],
    ['Undo', 'Redo'],
    ['Ask the agent', 'Hide the thread']
  ]);
  await page.locator('[data-design="menu.hide-the-thread"]').click();
  assert.equal(await page.evaluate(() => window.appStub.canvasFace), 'canvas');
});

test('Node menu and Node More cover dynamic run labels, approval, disconnect, note edit, Fork from here, and trace selection', async () => {
  // Idle step -> Run this step, Bypass; More -> Back, Colour/Save as skill/Save as node type, Pin/Fork from here/Repeat, Trace back/forward
  await page.evaluate(() => window.openTestMenu('Node menu', {nodeId: 'n-step', selected: ['n-step']}));
  assert.deepEqual(await page.evaluate(() => window.readMenuGroups()), [
    ['Properties', 'Add parameter', 'Show output', 'Ask the agent'],
    ['Run this step', 'Run to here', 'Freeze', 'Bypass'],
    ['Duplicate', 'Copy', 'Cut'],
    ['Rename', 'Group'],
    ['More'],
    ['Delete']
  ]);
  await page.getByRole('button', {name: 'More', exact: true}).click();
  assert.deepEqual(await page.evaluate(() => window.readMenuGroups()), [
    ['Back'],
    ['Colour', 'Save as skill', 'Save as node type'],
    ['Pin output', 'Fork from here', 'Repeat this'],
    ['Trace back', 'Trace forward']
  ]);
  await page.getByRole('button', {name: 'Trace forward', exact: true}).click();
  const traceCalls = await page.evaluate(() => window.calls);
  assert.deepEqual(traceCalls, [
    ['u.close'],
    ['canvas.select', ['n-step', 'n-done']],
    ['u.trace', 'n-step', 'forward']
  ]);

  // Fork from here calls api.forkNode via menu.fork
  await page.evaluate(() => window.openTestMenu('Node menu', {nodeId: 'n-step', selected: ['n-step']}));
  await page.getByRole('button', {name: 'More', exact: true}).click();
  await page.getByRole('button', {name: 'Fork from here', exact: true}).click();
  assert.deepEqual(await page.evaluate(() => window.calls), [['api.forkNode', 'n-step'], ['u.close']]);

  // Already-run bypassed node -> Rerun + Stop bypassing
  await page.evaluate(() => {
    const done = window.menuState.graph.nodes.find(n => n.id === 'n-done');
    done.bypassed = true;
    done.frozen = true;
    window.openTestMenu('Node menu', {nodeId: 'n-done', selected: ['n-done']});
  });
  const doneExecGroup = (await page.evaluate(() => window.readMenuGroups()))[1];
  assert.deepEqual(doneExecGroup, ['Rerun', 'Run to here', 'Unfreeze', 'Stop bypassing']);

  // Effect node requiring approval -> Ask to run (needs Approve)
  await page.evaluate(() => window.openTestMenu('Node menu', {nodeId: 'n-effect', selected: ['n-effect']}));
  assert.equal((await page.evaluate(() => window.readMenuGroups()))[1][0], 'Ask to run (needs Approve)');

  // Held node with pending approval + openable -> Review, Approve, Reject + Open
  await page.evaluate(() => window.openTestMenu('Node menu', {nodeId: 'n-held', selected: ['n-held']}));
  const heldGroups = await page.evaluate(() => window.readMenuGroups());
  assert.deepEqual(heldGroups[0], ['Review', 'Approve', 'Reject']);
  assert.equal(heldGroups[1][0], 'Open');
  await page.getByRole('button', {name: 'Approve', exact: true}).click();
  assert.deepEqual(await page.evaluate(() => window.calls), [['api.approve', 'ap-hold'], ['u.close']]);

  // Tunnel / live-member node -> Disconnect everyone now
  await page.evaluate(() => window.openTestMenu('Node menu', {nodeId: 'n-tunnel', selected: ['n-tunnel']}));
  assert.deepEqual((await page.evaluate(() => window.readMenuGroups()))[1], ['Disconnect everyone now']);
  await page.getByRole('button', {name: 'Disconnect everyone now', exact: true}).click();
  const disconnectCalls = await page.evaluate(() => window.calls);
  assert.deepEqual(disconnectCalls, [
    ['api.setNodeParam', 'n-tunnel', 'armed', false],
    ['api.detachMember', 'n-tunnel', {id: 'm-1', title: 'Codex', live: true}],
    ['u.close']
  ]);

  // Note node -> Edit note
  await page.evaluate(() => window.openTestMenu('Node menu', {nodeId: 'n-note', selected: ['n-note']}));
  await page.locator('[data-design="menu.edit-note"]').click();
  assert.deepEqual(await page.evaluate(() => window.calls), [['u.show', 'Note', 'n-note']]);
  await page.evaluate(() => window.appStub.close());
});

test('Selection, Group, Wire, and Embed menus wire every whole-design action to real owners', async () => {
  // Selection menu: Distribute evenly spaces 3 nodes evenly across X
  await page.evaluate(() => window.openTestMenu('Selection menu', {selected: ['n-up', 'n-step', 'n-done']}));
  assert.deepEqual(await page.evaluate(() => window.readMenuGroups()), [
    ['Run 3 steps', 'Ask the agent'],
    ['Group', 'Save as skill'],
    ['Align left', 'Align top', 'Distribute evenly'],
    ['Duplicate', 'Copy', 'Cut'],
    ['Delete 3 nodes']
  ]);
  await page.getByRole('button', {name: 'Distribute evenly', exact: true}).click();
  assert.deepEqual(await page.evaluate(() => window.calls), [
    ['api.moveNodes', {'n-up': {x: 60, y: 120}, 'n-step': {x: 340, y: 120}, 'n-done': {x: 620, y: 120}}],
    ['u.close']
  ]);

  // Group menu: Open, Collapse, Freeze the group, Bypass the group, Arrange inside, Rename, Colour, Select contents, Save as skill/node type, Ungroup, Delete
  await page.evaluate(() => {
    const done = window.menuState.graph.nodes.find(n => n.id === 'n-done');
    done.frozen = false;
    done.bypassed = false;
    window.openTestMenu('Group menu', {nodeId: 'n-group', selected: ['n-group']});
  });
  assert.deepEqual(await page.evaluate(() => window.readMenuGroups()), [
    ['Open', 'Collapse'],
    ['Freeze the group', 'Bypass the group', 'Arrange inside'],
    ['Rename', 'Colour', 'Select contents'],
    ['Save as skill', 'Save as node type'],
    ['Ungroup', 'Delete group and nodes']
  ]);
  await page.getByRole('button', {name: 'Freeze the group', exact: true}).click();
  assert.deepEqual(await page.evaluate(() => window.calls), [
    ['api.setNodeFlags', 'n-step', {frozen: true}],
    ['api.setNodeFlags', 'n-done', {frozen: true}],
    ['u.close']
  ]);
  await page.evaluate(() => window.openTestMenu('Group menu', {nodeId: 'n-group', selected: ['n-group']}));
  await page.getByRole('button', {name: 'Arrange inside', exact: true}).click();
  assert.deepEqual(await page.evaluate(() => window.calls), [
    ['api.moveNodes', {'n-step': {x: 240, y: 120}, 'n-done': {x: 560, y: 120}}],
    ['u.close']
  ]);

  // Wire menu: Group 1 [Go to source, Go to target, Select connected], Group 2 [Add rule / Edit rule, ...], Group 3 [Delete]
  await page.evaluate(() => window.openTestMenu('Wire menu', {wireId: 'w-1'}));
  assert.deepEqual(await page.evaluate(() => window.readMenuGroups()), [
    ['Go to source', 'Go to target', 'Select connected'],
    ['Add rule', 'Disable', 'Insert Convert', 'Insert node here', 'Show in Inspector'],
    ['Delete']
  ]);
  await page.getByRole('button', {name: 'Select connected', exact: true}).click();
  assert.deepEqual(await page.evaluate(() => window.calls), [
    ['u.close'],
    ['canvas.select', ['n-up', 'n-step', 'n-done']]
  ]);
  await page.evaluate(() => window.openTestMenu('Wire menu', {wireId: 'w-2'}));
  assert.deepEqual((await page.evaluate(() => window.readMenuGroups()))[1], [
    'Edit rule', 'Enable', 'Insert Convert', 'Insert node here', 'Show in Inspector'
  ]);

  // Embed menu via right-clicking an embedded session node (`Node menu` with `params.session_file`) AND `Embed menu`
  for (const kind of ['Node menu', 'Embed menu']) {
    await page.evaluate(k => window.openTestMenu(k, {nodeId: 'n-embed', selected: ['n-embed']}), kind);
    assert.deepEqual(await page.evaluate(() => window.readMenuGroups()), [
      ['Open', 'Run', 'Update', 'Show its tab'],
      ['Rename', 'Colour'],
      ['Detach as copy', 'Delete']
    ]);
  }
  await page.getByRole('button', {name: 'Show its tab', exact: true}).click();
  assert.deepEqual(await page.evaluate(() => window.calls), [
    ['u.openTaskFile', 'task-beta', 'canvas'],
    ['u.close']
  ]);
});

test('Home row, Home project, Home background, Message, and Tray menus match whole-design groups and actions', async () => {
  // Home session card right-click -> 4 visual groups, exact Duplicate / Archive / Delete labels
  await page.evaluate(() => { window.calls.length = 0; });
  await page.locator('#card-alpha').hover();
  await page.locator('#card-alpha').click({button: 'right'});
  const sessionMenu = page.getByRole('menu', {name: 'Home session menu'});
  await sessionMenu.waitFor();
  assert.deepEqual(await page.evaluate(() => window.readMenuGroups()), [
    ['Open session', 'Open the thread', 'Run'],
    ['Invite to watch…', 'Make this an automation', 'Settings for this session'],
    ['Add to another task', 'Rename', 'Duplicate', 'Keep at the top'],
    ['Archive', 'Delete']
  ]);
  await sessionMenu.getByRole('menuitem', {name: 'Duplicate', exact: true}).click();
  assert.deepEqual(await page.evaluate(() => window.calls.filter(c => c[0].startsWith('api.') || c[0] === 'u.openTaskFile')), [
    ['api.duplicateHomeTask', 'task-alpha', 'C:/probe/alpha.archhub'],
    ['u.openTaskFile', 'dup-task', 'canvas']
  ]);

  // Home project right-click -> Open {project}, Collapse/Expand, Settings for {project}
  await page.evaluate(() => { window.calls.length = 0; });
  await page.locator('[data-project="Tower Package"] [data-design="group.title"]').click({button: 'right'});
  const projectMenu = page.getByRole('menu', {name: 'Home project menu'});
  await projectMenu.waitFor();
  assert.deepEqual(await page.evaluate(() => window.readMenuGroups()), [
    ['Open Tower Package', 'Collapse', 'Settings for Tower Package']
  ]);
  await projectMenu.getByRole('menuitem', {name: 'Settings for Tower Package', exact: true}).click();
  assert.ok((await page.evaluate(() => window.calls)).some(c => c[0] === 'u.openSystem' && c[1] === 'Projects'));

  await page.locator('[data-project="Folded Wing"] [data-design="group.title"]').click({button: 'right'});
  assert.deepEqual(await page.evaluate(() => window.readMenuGroups()), [
    ['Open Folded Wing', 'Expand', 'Settings for Folded Wing']
  ]);
  await page.locator('.context-dismiss').click({position: {x: 10, y: 10}});

  // Home empty background right-click -> no menu drawn
  await page.locator('#home-empty').click({button: 'right'});
  assert.equal(await page.locator('.context-menu').count(), 0);

  // Task message menu -> 2 groups: [Copy text, Reply], [Show on canvas, Make a task from this, Pin to the task]
  await page.evaluate(() => window.openTestMenu('Task message menu', {
    taskId: 'task-alpha',
    message: {id: 'msg-1', text: 'Updated Sheet check output'}
  }));
  assert.deepEqual(await page.evaluate(() => window.readMenuGroups()), [
    ['Copy text', 'Reply'],
    ['Show on canvas', 'Make a task from this', 'Pin to the task']
  ]);

  // Tray menu -> Install the update (when update.available), Open Home, Send feedback, Open thread, Check for updates, Receipts, BABOOM, Stop everything, Hide, Quit ArchHub
  await page.evaluate(() => {
    window.menuState.update = {available: true};
    window.openTestMenu('Tray');
  });
  assert.deepEqual(await page.evaluate(() => window.readMenuGroups()), [
    ['Install the update'],
    ['Open Home', 'Send feedback', 'Open thread', 'Check for updates', 'Receipts', 'BABOOM', 'Stop everything'],
    ['Hide', 'Quit ArchHub']
  ]);
  await page.getByRole('button', {name: 'Check for updates', exact: true}).click();
  assert.deepEqual(await page.evaluate(() => window.calls), [['api.checkForUpdates'], ['u.close']]);
  await page.evaluate(() => window.appStub.close());
});
