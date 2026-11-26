// Behavioral court for Whole-Design P2-D: 1009px single-row Home bar ("Session history" unclipped),
// Home River / This PC / Customise / Project crumb + Esc / Wire Inspector / keyboard nav / What came out,
// Canvas toolbar (Automate + adot, Run · needs Approve, Layout menu + presets + Focus + Bottom/Float dock),
// preview tab double-click pin + split peek "Work here", and Session + Automate Inspector triggers & runs.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {chromium} = require('playwright');
const {transformSync} = require('esbuild');

const root = path.resolve(__dirname, '../..');
const studio = path.join(root, '01.APP/nodelang/studio');
const compileJsx = rel => transformSync(fs.readFileSync(path.join(studio, rel), 'utf8'), {loader: 'jsx'}).code;

function resolveBrowserExecutable() {
  if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE && fs.existsSync(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE)) {
    return process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
  }
  const cache = process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(os.homedir(), 'AppData/Local/ms-playwright');
  if (!fs.existsSync(cache)) return undefined;
  const dirs = fs.readdirSync(cache);
  const full = dirs.filter(n => /^chromium-\d+$/.test(n)).sort((a, b) => Number(b.split('-').at(-1)) - Number(a.split('-').at(-1)))[0];
  if (full) {
    const exe = path.join(cache, full, 'chrome-win64/chrome.exe');
    if (fs.existsSync(exe)) return exe;
  }
  const shell = dirs.filter(n => /^chromium_headless_shell-\d+$/.test(n)).sort((a, b) => Number(b.split('-').at(-1)) - Number(a.split('-').at(-1)))[0];
  return shell ? path.join(cache, shell, 'chrome-headless-shell-win64/chrome-headless-shell.exe') : undefined;
}

const bundle = [
  'tokens.jsx', 'ds/index.jsx', 'icons.jsx', 'ui.jsx', 'answer-widgets.jsx',
  'dock.jsx', 'ds_home2.jsx', 'ds_workshop3.jsx', 'ds_screens.jsx',
  'ds_library.jsx', 'surfaces.jsx', 'context-menus.jsx', 'app.jsx',
].map(compileJsx);

async function mountStudioPage(browser, viewport, {realCanvas = false, interrupted = false, arabic = false, folded = false} = {}) {
  const page = await browser.newPage({viewport});
  const errors = [];
  page.on('pageerror', err => { errors.push(err.message); console.error('PAGEERROR:', err.stack || err.message); });
  await page.route('**/*', route => route.fulfill({contentType: 'text/html', body: '<div id="root"></div>'}));
  await page.goto('http://127.0.0.1/');
  await page.addStyleTag({content: require('./studio_xyflow.cjs').css()});
  await page.addStyleTag({path: path.join(studio, 'style.css')});
  await page.addStyleTag({content: 'html,body,#root{height:100%;margin:0}'});
  for (const v of ['react.js', 'react-dom.js']) await page.addScriptTag({path: path.join(studio, 'vendor', v)});
  await page.addScriptTag({content: require('./studio_xyflow.cjs').script()});
  await page.addScriptTag({path: path.join(studio, 'compiled/react-resizable-panels.js')});
  await page.evaluate(() => { window.fetch = () => new Promise(() => {}); });
  await page.addScriptTag({path: path.join(studio, 'api.js')});

  await page.evaluate(({interrupted, arabic, folded}) => {
    const today = new Date().toISOString();
    window.ArchHubCommandRegistry = {
      commands: [
        {id: 'nav.home', label: 'Home', action: {route: 'home'}},
        {id: 'nav.canvas', label: 'Canvas', action: {route: 'canvas'}},
        {id: 'nav.docs', label: 'Docs', action: {route: 'docs'}},
        {id: 'nav.settings', label: 'Settings', action: {route: 'settings'}},
      ],
    };
    Object.assign(window.ArchHubRouteNames, {home: 'Home', canvas: 'Canvas', docs: 'Docs', settings: 'Settings'});
    const s = window.structuredClone(window.ArchHubAPI.getSnapshot());
    s.desktopAccess = {ready: true, admitted: true, subject: 'whole-design-test'};
    s.settings.push({id: 'Appearance.Inspector width', value: 320, overridden: true});
    s.workspaces = [{id: 'Tower', name: 'Tower'}, {id: 'Civic', name: 'Civic'}];
    s.hosts = [{id: 'revit', name: 'Revit 2026', state: 'connected'}];
    s.providers = [{id: 'claude-code', name: 'Claude Code', signedIn: true, model: 'Sonnet'}];
    s.agents = [{id: 'claude-code', name: 'Claude Code', status: 'idle'}];
    s.desktop = {automationsPaused: false, workflowActivity: {'C:/sessions/echo.archhub': {armed: 1}}};
    s.dockLayout = {layout: folded ? {left: {w: 268, c: true, st: [{p: ['workshop'], a: 'workshop', h: 1.15, c: false}, {p: ['library', 'map'], a: 'library', h: 1, c: false}]}, right: {c: true, st: [{p: ['insp'], a: 'insp', h: 1, c: false}]}} : null};
    if (arabic) s.settings.push({id: 'Account.App language', value: 'Arabic'}, {id: 'Account.Right-to-left layout', value: 'Auto'});
    s.homeLayout = {width: 300, collapsed: false, resume: '', order: [], hidden: [], map: {}};
    s.sessionListFilters = {home: 'all'};
    s.tasks = [
      {
        id: 't-echo', title: 'Facade wall audit', status: 'IN REVIEW', workspace: 'Tower', project: 'Tower',
        sessionPath: 'C:/sessions/echo.archhub', updated_at: today, queuedMessages: [{id: 'q1'}],
        members: [{id: 'm1', name: 'Claude Code', live: !interrupted}], agents: ['Claude Code'],
        plan: ['Read curtain walls', 'Export wall schedule'], progress: {'Read curtain walls': 'done', 'Export wall schedule': 'awaiting'},
        outputs: [{name: 'wall-schedule.csv', excerpt: '42 curtain panels verified'}], messages: [],
      },
      {
        id: 't-feed', title: 'Structural grid sync', status: 'WIP', workspace: 'Tower', project: 'Tower',
        sessionPath: 'C:/sessions/feed.archhub', updated_at: today,
        members: [{id: 'm2', name: 'Claude Code', live: !interrupted}], agents: ['Claude Code'],
        plan: ['Extract grid lines'], progress: {'Extract grid lines': 'done'},
        outputs: [{name: 'grids.json', excerpt: '12 axes'}], messages: [],
      },
    ];
    s.approvals = [{id: 'ap-1', status: 'pending', work: 't-echo', taskId: 't-echo', path: 'C:/sessions/echo.archhub', title: 'Publish wall report', who: 'Claude Code'}];
    s.graph = {
      id: 'g-echo', name: 'Facade wall audit', revision: 1, documentation: 'Audit tower curtain walls',
      nodes: [
        {id: 'start', fixed: true, type: 'thing.session', title: 'Facade wall audit', x: 80, y: 80, params: {read_only_agents: [], run_budget: 5}, parameterSchema: [{key: 'run_budget', label: 'Run budget', type: 'number', editable: true}], inputs: [], outputs: []},
        {id: 'chk-1', fixed: false, type: 'check.standard', category: 'Check', title: 'Wall clearance check', pure: true, status: 'Done', x: 420, y: 80, params: {}, parameterSchema: [], inputs: [], outputs: []},
        {id: 'eff-1', fixed: false, type: 'export.pdf', category: 'Export', title: 'Issue PDF package', pure: false, status: 'Waiting for approval', x: 760, y: 80, params: {}, parameterSchema: [], inputs: [], outputs: []},
      ],
      wires: [],
    };
    let tabsState = {tabs: [{id: 't-echo', kept: false}, {id: 't-feed', kept: true}], active: 't-echo', split: 't-feed', collapsed: false};
    let currentSessionPath = 'C:/sessions/echo.archhub';
    const sessionModels = {
      'C:/sessions/echo.archhub': {
        id: 'echo', path: 'C:/sessions/echo.archhub', task: 't-echo', title: 'Facade wall audit', state: 'open',
        project: {id: 'Tower', label: 'Tower'}, automation: [{node: 'trig-0', armed: true, live: true}],
        doneCheck: null,
        inputLinks: [{source: {id: 'feed', path: 'C:/sessions/feed.archhub'}, output: 'grids.out', input: 'grids', state: 'ready'}],
      },
      'C:/sessions/feed.archhub': {
        id: 'feed', path: 'C:/sessions/feed.archhub', task: 't-feed', title: 'Structural grid sync', state: 'open', pinned: true,
        project: {id: 'Tower', label: 'Tower'}, automation: [], doneCheck: null, inputLinks: [],
      },
    };
    const listeners = new Set();
    const notify = () => listeners.forEach(fn => fn());

    window.ArchHubAPI = {
      ...window.ArchHubAPI,
      getSnapshot: () => s,
      subscribe: fn => { listeners.add(fn); return () => listeners.delete(fn); },
      executeAction: (id, cb) => {
        if (id === 'ui.select') return cb();
        if (id === 'projects.controls.activate') return cb.handler();
        if (id === 'projects.automations.togglePause') { s.desktop.automationsPaused = !s.desktop.automationsPaused; notify(); return {ok: true}; }
        return typeof cb === 'function' ? cb() : null;
      },
      supportsAction: () => true,
      setActiveSurface: () => {},
      rememberDesktopView: () => {},
      readDesktopView: () => ({}),
      readHostAvailability: async () => ({}),
      hasSessionEdits: () => false,
      getSessionPath: () => currentSessionPath,
      getSessionDocument: () => ({id: 'g-echo', properties: {taskContext: {task: s.focusedTask || 't-echo'}}}),
      listSessionModel: async () => ({groups: [{project: {id: 'Tower', label: 'Tower'}, sessions: Object.values(sessionModels)}], recentTask: 't-echo'}),
      readSessionModel: async p => sessionModels[p] || sessionModels['C:/sessions/echo.archhub'],
      setSessionModel: async (p, patch) => { Object.assign(sessionModels[p] || sessionModels['C:/sessions/echo.archhub'], patch); notify(); return sessionModels[p] || sessionModels['C:/sessions/echo.archhub']; },
      sessionInputLinks: async p => (sessionModels[p] || sessionModels['C:/sessions/echo.archhub']).inputLinks || [],
      sessionRuns: async () => [],
      readHomeLayout: async () => ({
        homeLayout: s.homeLayout,
        homeMap: {group: ['Project', 'State', 'Agent'], order: ['Needs you first', 'Name'], card: ['Steps and state', 'State only'], density: ['Comfortable', 'Compact'], done: ['Show', 'Hide'], filter: ['All', 'Running', 'Needs you']},
      }),
      setHomeLayout: async val => { s.homeLayout = val; notify(); return {ok: true}; },
      setDockLayout: async val => { s.dockLayout = {layout: val}; notify(); return {ok: true}; },
      setInspectorWidth: async val => { s.settings.find(r => r.id === 'Appearance.Inspector width').value = val; notify(); return {ok: true}; },
      readCanvasTabs: async () => ({canvasTabs: tabsState}),
      setCanvasTabs: async val => { tabsState = val; notify(); return {canvasTabs: val, ok: true}; },
      readSessionListFilters: async () => ({sessionListFilters: s.sessionListFilters}),
      setSessionListFilter: async (k, v) => { s.sessionListFilters[k] = v; notify(); return {ok: true}; },
      openTaskGraph: async id => {
        const row = s.tasks.find(t => t.id === id);
        if (row) { currentSessionPath = row.sessionPath; s.focusedTask = id; s.tasks.forEach(t => { t.sessionOpen = t.id === id; }); notify(); }
        return {ok: true};
      },
      readTaskPreview: async id => ({id: 'prev-' + id, name: 'Structural grid sync', nodes: [], wires: [], viewport: {x: 0, y: 0, zoom: 1}}),
      setTaskSession: async (id, patch) => { const t = s.tasks.find(r => r.id === id); if (t) Object.assign(t, patch); notify(); return {ok: true}; },
      setNodeParam: async (id, k, v) => { const n = s.graph.nodes.find(r => r.id === id); if (n) n.params[k] = v; s.graph = {...s.graph, revision: (s.graph.revision || 1) + 1}; notify(); return {ok: true}; },
      deleteNode: async id => { s.graph = {...s.graph, nodes: s.graph.nodes.filter(n => n.id !== id), revision: (s.graph.revision || 1) + 1}; notify(); return {ok: true}; },
      refreshAgentSurface: async () => null,
    };
  }, {interrupted, arabic, folded});

  for (let i = 0; i < bundle.length - 1; i++) await page.addScriptTag({content: bundle[i]});
  await page.evaluate(realCanvas => {
    const blank = () => null;
    const baseExec = window.executeAction;
    window.executeAction = (id, context, ...rest) => (id === 'ui.select' || id === 'ui.state') ? context(...rest) : (baseExec ? baseExec(id, context, ...rest) : null);
    Object.assign(window.UI, {
      BaboomSprite: blank,
      ScheduleResponsibility: blank,
      ...(realCanvas ? {} : {Canvas: ({preview}) => window.React.createElement('div', {'data-test-canvas': preview ? 'preview' : 'main'}, preview ? 'Preview canvas' : 'Main canvas')}),
      GraphProperties: window.UI.GraphProperties || (({g}) => window.React.createElement('div', {'data-fixture-properties': true}, g?.name || '')),
      ApprovalCard: window.UI.ApprovalCard || (({id}) => window.React.createElement('div', {'data-approval': id}, 'Pending approval')),
      ResultPreview: window.UI.ResultPreview || (({value}) => window.React.createElement('span', null, String(value ?? ''))),
    });
  }, realCanvas);
  await page.addScriptTag({content: bundle.at(-1)});
  return {page, errors};
}

test('Home at 1009px: non-overlapping bar with unclipped Session history, River/This PC/Customise, Crumb+Esc, Wire Inspector & keyboard nav', async t => {
  const browser = await chromium.launch({headless: true, executablePath: resolveBrowserExecutable()});
  t.after(() => browser.close());
  const {page, errors} = await mountStudioPage(browser, {width: 1009, height: 900});

  await page.locator('[data-home-map]').waitFor();
  await page.locator('[data-design="home.card"]').first().waitFor();

  // 1. 1009px .home-map-bar: single row, zero overlap, "Session history" unclipped, queued stat present, Saved document filter = All | Workflows
  const barMetrics = await page.evaluate(() => {
    const buttons = [...document.querySelectorAll('.home-map-bar > button')].filter(b => b.getClientRects().length > 0);
    return {
      queued: document.querySelector('[data-home-queued]')?.textContent?.trim(),
      buttons: buttons.map(b => {
        const r = b.getBoundingClientRect();
        return {text: b.textContent.trim(), left: r.left, right: r.right, top: r.top, unclipped: b.scrollWidth <= b.clientWidth + 1};
      }),
    };
  });
  assert.equal(barMetrics.queued, '1 queued');
  const histBtn = barMetrics.buttons.find(b => b.text === 'Session history');
  assert.ok(histBtn && histBtn.unclipped, 'Session history is visible and unclipped at 1009px: ' + JSON.stringify(histBtn));
  for (let i = 1; i < barMetrics.buttons.length; i++) {
    assert.ok(barMetrics.buttons[i].left >= barMetrics.buttons[i - 1].right - 1, 'bar buttons do not overlap or wrap at 1009px: ' + JSON.stringify(barMetrics.buttons));
  }
  const filterGroup = page.getByRole('group', {name: 'Saved document filter', exact: true});
  assert.deepEqual(await filterGroup.getByRole('button').allTextContents(), ['All', 'Workflows']);

  // Session history adds Agent sessions filter, and closing restores All | Workflows
  await page.locator('[data-home-history]').click();
  assert.deepEqual(await filterGroup.getByRole('button').allTextContents(), ['All', 'Agent sessions', 'Workflows']);
  await page.locator('[data-home-history]').click();

  // 2. River, This PC, and Customise Home strips
  await page.locator('[data-home-river-toggle]').click();
  await page.locator('[data-home-river="Recent"]').getByText('Last 24 hours').waitFor();
  await page.locator('[data-home-river-toggle]').click();
  await page.locator('[data-home-river="Live"]').waitFor();
  await page.locator('[data-home-river-toggle]').click();
  assert.equal(await page.locator('[data-home-river]').count(), 0);

  await page.locator('[data-home-floor-toggle]').click();
  await page.locator('[data-home-floor]').getByText('Install what it needs').waitFor();
  await page.locator('[data-home-floor-toggle]').click();

  await page.locator('[data-home-customise-btn]').click();
  const cust = page.locator('[data-home-customise]');
  await cust.getByRole('button', {name: 'Show as compact', exact: true}).click();
  await cust.getByRole('button', {name: 'Done', exact: true}).click();
  assert.equal(await cust.count(), 0);

  // 3. Open right dock at 1009px, inspect selected session ("What came out" + single title), clear pick, test Project crumb + Esc and Wire Inspector
  const openRight = page.getByRole('button', {name: 'Open Inspector', exact: true});
  if (await openRight.isVisible()) await openRight.click();
  const insp = page.locator('[data-home-inspector]');
  await insp.locator('[data-home-outputs]').getByText('42 curtain panels verified').waitFor();
  const headingLine = await insp.locator('.resume-heading p').first().textContent();
  assert.ok(!headingLine.includes('Facade wall audit'), 'session title is not repeated in subtitle');

  // Clear pick via Escape/pane, open Project scope -> All projects > Tower -> Esc
  await page.evaluate(() => document.querySelector('[data-home-map] .react-flow__pane')?.click());
  if (!await insp.isVisible()) await page.locator('.dock.right [data-tab="insp"]').click();
  await insp.getByRole('button', {name: 'Open project Tower', exact: true}).click();
  await page.locator('[data-home-crumb]').filter({hasText: 'Tower'}).waitFor();
  await page.locator('[data-home-page]').press('Escape');
  assert.equal(await page.locator('[data-home-crumb]').count(), 0);

  // Inspect feed wire -> .home-wire-focus + Home Wire Inspector ("What flows", "Passes on")
  if (!await insp.isVisible()) await page.locator('.dock.right [data-tab="insp"]').click();
  await insp.getByRole('button', {name: 'Inspect', exact: true}).first().click();
  await insp.locator('[data-home-wire-inspector]').getByText('What flows').waitFor();
  assert.equal(await page.locator('.home-map-stage.home-wire-focus').count(), 1);
  await insp.getByLabel('Passes on', {exact: true}).selectOption('Every time');
  await page.locator('[data-home-page]').press('Escape');

  // Keyboard ArrowRight + Enter opens picked session canvas
  await page.locator('[data-home-page]').press('ArrowRight');
  await page.locator('[data-home-page]').press('Enter');
  await page.locator('.dx-home-root[data-screen="task-file"]').waitFor({timeout: 5000});
  assert.deepEqual(errors, []);
});

test('Canvas toolbar, preview tab pin, split peek Work here, Layout menu/Bottom/Float/Focus dock, and Session/Automate Inspector', async t => {
  const browser = await chromium.launch({headless: true, executablePath: resolveBrowserExecutable()});
  t.after(() => browser.close());
  const {page, errors} = await mountStudioPage(browser, {width: 1440, height: 900});

  await page.locator('[data-home-map]').waitFor();
  await page.locator('[data-design="home1.open"]').click();
  await page.locator('.dx-home-root[data-screen="task-file"]').waitFor({timeout: 5000});

  // 1. Run · needs Approve label, preview tab italic + double-click pin, split peek "Work here"
  assert.equal((await page.locator('[data-design="toolbar.run"]').textContent()).trim(), 'Run · needs Approve');
  const activeTabBtn = page.locator('[data-design="tab.active"] [role="tab"]');
  assert.equal(await activeTabBtn.getAttribute('data-preview'), 'true');
  await activeTabBtn.dblclick();
  assert.equal(await activeTabBtn.getAttribute('data-preview'), 'false');

  const peek = page.locator('[data-peek-pane]');
  await peek.getByText('Its own file. Click inside to work here').waitFor();
  await peek.locator('[data-peek-work-here]').click();
  assert.equal((await page.locator('[data-design="tab.active"] [role="tab"]').textContent()).trim(), 'Structural grid sync');

  // 2. Layout options caret menu: presets (Review, Meeting -> People panel), Focus mode + Esc, panel Move to bottom / Float, direct toolbar.layout reset to Build
  await page.locator('[data-design="toolbar.layout.menu"]').click();
  await page.getByRole('menu', {name: 'Layout', exact: true}).getByRole('menuitem', {name: /Meeting/}).click();
  await page.locator('[data-dock-people]').waitFor();
  assert.equal(await page.locator('[data-design="toolbar.layout"]').getAttribute('aria-label'), 'Layout: Meeting');

  // Panel options -> Move to the bottom & Float
  await page.locator('[data-panel-menu="people"]').click();
  await page.getByRole('menuitem', {name: 'Move to the bottom', exact: true}).click();
  await page.locator('.dock.bottom [data-tab="people"]').waitFor();

  await page.locator('[data-panel-menu="people"]').click();
  await page.getByRole('menuitem', {name: 'Float', exact: true}).click();
  await page.locator('.dfloat[data-float-panel="people"]').waitFor();

  // Focus mode via Layout menu + Escape exit
  await page.locator('[data-design="toolbar.layout.menu"]').click();
  await page.getByRole('menuitem', {name: /Focus mode/}).click();
  await page.locator('.dockws.focus-mode').waitFor();
  await page.locator('[data-focus-exit]').waitFor();
  await page.locator('body').press('Escape');
  assert.equal(await page.locator('.dockws.focus-mode').count(), 0);

  // Direct click on toolbar.layout resets directly to Build
  await page.locator('[data-design="toolbar.layout"]').click();
  assert.equal(await page.locator('[data-design="toolbar.layout"]').getAttribute('aria-label'), 'Layout: Build');

  // 3. Automate button -> Inspector Automate tab: + Schedule, + File change, + Program event, .adot, Pause/Arm, Run now -> Automation runs, Delete confirm, and Session tab
  await page.locator('[data-design="toolbar.automate"]').click();
  const autoPanel = page.locator('[data-design="inspector.automate.panel"]');
  await autoPanel.waitFor();
  for (const kind of ['schedule', 'file', 'program']) {
    await autoPanel.locator(`[data-automate-add="${kind}"]`).click();
  }
  assert.equal(await autoPanel.locator('[data-trigger-card]').count(), 3);

  const firstCard = autoPanel.locator('[data-trigger-card]').first();
  await firstCard.getByRole('button', {name: 'Pause', exact: true}).click();
  await firstCard.getByRole('button', {name: 'Arm', exact: true}).click();
  await firstCard.getByRole('button', {name: 'Run now', exact: true}).click();
  await autoPanel.locator('[data-automate-runs] .arow2').first().waitFor();

  await firstCard.getByRole('button', {name: /Delete/}).click();
  await firstCard.locator('[data-trigger-delete-confirm]').getByText('Delete this trigger?').waitFor();
  await firstCard.locator('[data-confirm-delete-trigger]').click();
  assert.equal(await autoPanel.locator('[data-trigger-card]').count(), 2);

  // Session tab ([data-design="inspector.task"]) keeps section.v48-session-inspector working
  await page.locator('[data-design="inspector.task"]').click();
  await page.locator('section.v48-session-inspector').getByLabel('Done when', {exact: true}).waitFor();

  assert.doesNotMatch(await page.evaluate(() => document.body.innerText), /Coming soon/i);
  assert.deepEqual(errors, []);
});

// Founder 2026-11-26 (P0-A): Home -> Canvas -> Home left Home's centre empty. Every way back must redraw the map with its cards in view.
async function homeMapDrawn(page, label) {
  await page.locator('[data-home-map] [data-design="home.card"]').first().waitFor({timeout: 5000});
  await page.waitForTimeout(120);
  const box = await page.evaluate(() => {
    const stage = document.querySelector('[data-home-canvas] .node-canvas')?.getBoundingClientRect();
    const cards = [...document.querySelectorAll('[data-home-map] [data-design="home.card"]')].map(card => card.getBoundingClientRect());
    return {stage: stage && {w: stage.width, h: stage.height, l: stage.left, r: stage.right, t: stage.top, b: stage.bottom}, cards: cards.map(c => ({l: c.left, r: c.right, t: c.top, b: c.bottom, w: c.width}))};
  });
  if (process.env.HOMETHREAD_SHOTS) await page.screenshot({path: path.join(process.env.HOMETHREAD_SHOTS, label.replace(/\W+/g, '-') + '-' + page.viewportSize().width + '.png')});
  assert.ok(box.stage && box.stage.w > 200 && box.stage.h > 300, label + ': the map stage has room ' + JSON.stringify(box.stage));
  assert.ok(box.cards.length >= 2 && box.cards.every(c => c.w > 40 && c.l >= box.stage.l - 1 && c.r <= box.stage.r + 1 && c.t >= box.stage.t - 1 && c.b <= box.stage.b + 1), label + ': every card is drawn inside the map ' + JSON.stringify(box));
}

for (const [width, height, opts] of [[1920, 1032, {}], [1920, 1032, {interrupted: true}], [944, 968, {}], [944, 968, {interrupted: true}], [900, 970, {arabic: true, folded: true}], [900, 970, {folded: true}], [1920, 1032, {arabic: true, folded: true}]]) test('Home after Canvas redraws its map on every way back at ' + width + 'px ' + JSON.stringify(opts) + ' (rail Home, breadcrumb Home, Esc; via rail Canvas and Open its Canvas)', async t => {
  const browser = await chromium.launch({headless: true, executablePath: resolveBrowserExecutable()});
  t.after(() => browser.close());
  const {page, errors} = await mountStudioPage(browser, {width, height}, {realCanvas: true, ...opts});
  const railIndex = {Home: 0, Canvas: 1};  // the rail's first two doors, whatever the app language names them
  const rail = name => page.locator('nav.app-rail > button').nth(railIndex[name]);
  await homeMapDrawn(page, 'first Home');
  const ways = {
    'rail Home': () => rail('Home').click(),
    'breadcrumb Home': () => page.locator('button.header-page').click(),
    // Esc first clears what the canvas holds (a selected step), then goes back to Home.
    'Esc': async () => { for (let i = 0; i < 3 && !(await page.locator('[data-home-page]').count()); i++) { await page.locator('body').press('Escape'); await page.waitForTimeout(80); } },
  };
  const openIts = async () => {
    if (!(await page.locator('[data-design="home1.open"]').count())) await page.locator('[data-home-map] [data-design="home.card"]').first().click();
    if (!(await page.locator('[data-design="home1.open"]').isVisible())) await page.locator('.dock.right [data-tab="insp"]').click();
    await page.locator('[data-design="home1.open"]').click();
  };
  for (const [enter, open] of [['rail Canvas', () => rail('Canvas').click()], ['Open its Canvas', openIts]]) for (const thread of [false, true]) {
    for (const [back, leave] of Object.entries(ways)) {
      await open();
      await page.locator('.dx-home-root[data-screen="task-file"]').waitFor({timeout: 5000});
      if (thread !== (await page.locator('[data-design="toolbar.thread"]').getAttribute('aria-pressed') === 'true')) {
        if (await page.locator('[data-design="toolbar.thread"]').isVisible()) await page.locator('[data-design="toolbar.thread"]').click();
        else {
          await page.locator('[data-design="toolbar.layout.menu"]').click();
          await page.getByRole('menuitem', {name: thread ? 'Show the thread' : 'Hide the thread', exact: true}).click();
        }
      }
      await page.waitForTimeout(150);
      await leave();
      await page.locator('[data-home-page]').waitFor({timeout: 5000});
      await homeMapDrawn(page, enter + (thread ? ' with its Thread' : '') + ' then ' + back + ' ' + JSON.stringify(opts));
    }
  }
  assert.deepEqual(errors, []);
});

// Founder 2026-11-26 (P0-B): the Thread is one more dock panel: it docks, stacks, tabs, resizes, folds into the same tab strip and closes
// like the Library or the Inspector; it has no strip of its own, never shrinks to a word column, and no tint stays over it.
for (const [width, height] of [[1920, 1032], [944, 968]]) test('Thread is a dock panel at ' + width + 'px: shown, folded into the dock strip, moved, resized, closed', async t => {
  const browser = await chromium.launch({headless: true, executablePath: resolveBrowserExecutable()});
  t.after(() => browser.close());
  const {page, errors} = await mountStudioPage(browser, {width, height}, {realCanvas: true});
  await page.locator('[data-home-map] [data-design="home.card"]').first().waitFor();
  await page.getByRole('navigation', {name: 'Main navigation'}).getByRole('button', {name: 'Canvas', exact: true}).click();
  await page.locator('.dx-home-root[data-screen="task-file"]').waitFor({timeout: 5000});
  const toggle = async label => { await page.locator('[data-design="toolbar.layout.menu"]').click(); await page.getByRole('menuitem', {name: label, exact: true}).click(); };
  await toggle('Show the thread');
  const thread = page.locator('.dock [data-tab="thread"]');
  await thread.waitFor();
  const pane = page.locator('.dockws .pnl[data-p="thread"] .v22g-thread');
  await pane.waitFor();
  await page.waitForTimeout(300);  // the dock eases its width in (240 ms)
  const shot = name => process.env.HOMETHREAD_SHOTS && page.screenshot({path: path.join(process.env.HOMETHREAD_SHOTS, 'thread-' + name + '-' + width + '.png')});
  await shot('docked');
  // One dock system: no private thread strip, no resizable split column, no peek overlay.
  assert.equal(await page.locator('[aria-label="Open Thread"].canvas-pane-rail, [data-thread-peek], [aria-label="Resize thread"]').count(), 0);
  const room = await pane.evaluate(el => ({w: el.getBoundingClientRect().width, line: el.querySelector('.dx-talk')?.getBoundingClientRect().width || 0}));
  assert.ok(room.w >= 280 && room.line >= 240, 'the thread keeps a readable width: ' + JSON.stringify(room));
  // Fold the dock that holds it: the Thread becomes a tab in that dock's strip, and the tab opens it again.
  const side = await thread.evaluate(el => el.closest('.dock').dataset.dock);
  await page.getByRole('button', {name: 'Fold the ' + side + ' dock to icons', exact: true}).click();
  await page.locator('.dock.' + side + '.col [data-tab="thread"]').waitFor();
  await page.waitForTimeout(300);
  await shot('folded');
  assert.equal(await page.locator('[data-design="toolbar.thread"]').getAttribute('aria-pressed'), 'true', 'folding keeps the thread shown in the strip');
  await page.locator('.dock.' + side + '.col [data-tab="thread"]').click();
  await pane.waitFor();
  // Its panel menu moves it like any panel.
  await page.locator('[data-panel-menu="thread"]').click();
  await page.getByRole('menuitem', {name: 'Move to the left', exact: true}).click();
  await page.locator('.dock.left [data-tab="thread"]').waitFor();
  // Resize the left dock with the real pointer; the thread follows the dock width.
  await page.locator('[data-sash="left"]').dragTo(page.locator('.dockws .dcenter-main'), {sourcePosition: {x: 3, y: 200}, targetPosition: {x: 80, y: 200}});
  const wide = await pane.evaluate(el => el.getBoundingClientRect().width);
  assert.ok(wide > room.w - 1 || wide >= 300, 'resizing the dock widens the thread: ' + JSON.stringify({wide, before: room.w}));
  // A real tab drag shows the drop preview while it moves and leaves no tint once it ends.
  await page.locator('.dock.left [data-tab="thread"]').dragTo(page.locator('.dockws .dcenter-main'), {targetPosition: {x: 160, y: 200}});
  assert.equal(await page.locator('.dockws .dzp:not([hidden]), .dghost').count(), 0, 'no drop tint or ghost stays after the drag');
  // Closing the panel hides the thread; the toolbar follows.
  await page.locator('[data-panel-menu="thread"]').click();
  await page.getByRole('menuitem', {name: 'Close panel', exact: true}).click();
  await page.waitForFunction(() => document.querySelector('[data-design="toolbar.thread"]')?.getAttribute('aria-pressed') === 'false');
  assert.equal(await page.locator('.dock [data-tab="thread"]').count(), 0);
  // Back to Home and in again: Home shows no Thread tab; the session shows it again when asked.
  await page.getByRole('navigation', {name: 'Main navigation'}).getByRole('button', {name: 'Home', exact: true}).click();
  await page.locator('[data-home-page]').waitFor();
  assert.equal(await page.locator('.dock [data-tab="thread"]').count(), 0);
  assert.deepEqual(errors, []);
});

// Founder 2026-11-26 (P0-A, verifier repro on 75f10a3): after several Home -> Canvas -> Home trips at 900x970, Arabic, docks folded,
// Home showed "Loading sessions" and no card while the owner held the task. The verifier's sequence 20 times, then the same trip while
// the owners stop answering (a busy server): the last known map stays drawn and the stalled read ends as a Retry that works.
test('Home keeps its cards over 20 Canvas round trips and while its owners are slow (900x970, Arabic, docks folded)', async t => {
  const browser = await chromium.launch({headless: true, executablePath: resolveBrowserExecutable()});
  t.after(() => browser.close());
  const {page, errors} = await mountStudioPage(browser, {width: 900, height: 970}, {realCanvas: true, arabic: true, folded: true});
  const door = index => page.locator('nav.app-rail > button').nth(index);
  const cards = async label => {
    await page.locator('[data-home-page]').waitFor({timeout: 5000});
    await page.locator('[data-home-map] [data-design="home.card"]').first().waitFor({timeout: 5000});
    const seen = await page.evaluate(() => ({cards: document.querySelectorAll('[data-home-map] [data-design="home.card"]').length,
      loading: !!document.querySelector('[data-home-page] > p[role="status"]')}));
    assert.ok(seen.cards >= 2, label + ': ' + JSON.stringify(seen));
    return seen;
  };
  await cards('first Home');
  for (let trip = 1; trip <= 20; trip++) {
    await door(1).click();
    await page.locator('.dx-home-root[data-screen="task-file"]').waitFor({timeout: 5000});
    await door(0).click();
    const seen = await cards('trip ' + trip);
    await page.waitForFunction(() => !document.querySelector('[data-home-page] > p[role="status"]'), null, {timeout: 5000});
    assert.equal(seen.cards >= 2, true);
  }
  // The owners stop answering: the map drawn from the last reads stays, and the stalled reads end as a Retry.
  await page.evaluate(() => {
    window.ArchHubAPI.getSnapshot().runtimeParameters = {...window.ArchHubAPI.getSnapshot().runtimeParameters, home_load_ms: 2000};  // the Home load budget
    const held = window.ArchHubAPI;
    window.__answer = {readHomeLayout: held.readHomeLayout, listSessionModel: held.listSessionModel};
    held.readHomeLayout = () => new Promise(() => {});
    held.listSessionModel = () => new Promise(() => {});
  });
  await door(1).click();
  await page.locator('.dx-home-root[data-screen="task-file"]').waitFor({timeout: 5000});
  await door(0).click();
  await cards('owners not answering');
  const retry = page.locator('[data-home-page] [role="alert"] button').first();
  await retry.waitFor({timeout: 12000});
  await page.evaluate(() => Object.assign(window.ArchHubAPI, window.__answer));
  await retry.click();
  await page.waitForFunction(() => !document.querySelector('[data-home-page] > p[role="alert"]'), null, {timeout: 5000});
  await cards('after Retry');
  // Another account signs in while the owners are slow: nothing read for the first account is shown to it.
  await page.evaluate(() => {
    const api = window.ArchHubAPI, snap = api.getSnapshot();
    snap.profile = {...snap.profile, id: 'another-account'};
    api.readHomeLayout = () => new Promise(() => {});
    api.listSessionModel = () => new Promise(() => {});
  });
  await door(1).click();
  await page.locator('.dx-home-root[data-screen="task-file"]').waitFor({timeout: 5000});
  await door(0).click();
  await page.locator('[data-home-page]').waitFor({timeout: 5000});
  await page.waitForTimeout(300);
  assert.equal(await page.locator('[data-home-map] [data-design="home.card"]').count(), 0, 'another account starts from nothing');
  assert.deepEqual(errors, []);
});
