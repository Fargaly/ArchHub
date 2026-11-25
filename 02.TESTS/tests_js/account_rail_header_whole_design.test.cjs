'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {chromium} = require('playwright');
const {transformSync} = require('esbuild');

const studio = path.resolve(__dirname, '../../01.APP/nodelang/studio');

function chromiumExecutable() {
  const cache = process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(os.homedir(), 'AppData/Local/ms-playwright');
  const full = fs.existsSync(cache) && fs.readdirSync(cache).filter(name => /^chromium-\d+$/.test(name)).sort((a, b) => Number(b.split('-').at(-1)) - Number(a.split('-').at(-1)))[0];
  return process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || (process.platform === 'win32' && full ? path.join(cache, full, 'chrome-win64/chrome.exe') : undefined);
}

const TINY_PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAYAAACp8Z5+AAAAEklEQVR42mP8z8AARAwMjDAGACWBAQfb2s9AAAAAAElFTkSuQmCC';

async function mountAppShell(page) {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.route('**/*', route => route.fulfill({contentType: 'text/html', body: '<meta charset="utf-8"><div id="root"></div>'}));
  await page.goto('http://127.0.0.1:1/studio');
  await page.addStyleTag({path: path.join(studio, 'style.css')});
  await page.addStyleTag({content: 'html,body,#root{height:100%;margin:0}'});
  for (const name of ['react.js', 'react-dom.js']) {
    await page.addScriptTag({path: path.join(studio, 'vendor', name)});
  }
  await page.evaluate(tinyPng => {
    window.calls = [];
    window.openedUrls = [];
    window.open = url => { window.openedUrls.push(url); return null; };
    window.ArchHubRouteNames = {
      home: 'Home',
      canvas: 'Canvas',
      docs: 'Docs',
      community: 'Community',
      social: 'Social media',
      receipts: 'Receipts',
      library: 'Library',
      workshop: 'Workshop',
      agents: 'Agents'
    };
    window.ArchHubCommandRegistry = {
      palette_order: ['Pages', 'Nodes', 'Settings'],
      commands: [
        {id: 'page.home', label: 'Home', group: 'Pages', contexts: ['navigation'], action: {route: 'home'}},
        {id: 'page.docs', label: 'Docs', group: 'Pages', contexts: ['navigation'], action: {route: 'docs'}}
      ]
    };
    const listeners = new Set();
    let state = {
      app: {quit: false, hidden: false},
      desktopAccess: {ready: true, admitted: true, subject: 'user-1', email: 'architect@studio.test'},
      profile: {id: 'u1', name: 'Nadia Karim', email: 'architect@studio.test', firm: 'Studio North', plan: 'Personal', signedIn: true, role: 'Lead Architect', presence: 'Available', photo: ''},
      settingsDestination: {scope: 'User', workspace: 'ws-1', session: '', workspaceIdentity: 'h1'},
      settingsScopePending: false,
      settings: [
        {id: 'Appearance.Theme', value: 'Dark', default: 'Dark'},
        {id: 'Appearance.Accent colour', value: '#d97757', default: '#d97757'},
        {id: 'Account.App language', value: 'English', default: 'English', options: ['English', 'Arabic'], storageKey: 'language'},
        {id: 'Account.Right-to-left layout', value: 'Auto', default: 'Auto', options: ['Auto', 'Always', 'Never'], storageKey: 'rtl'},
        {id: 'Account.Presence status', value: 'Available', default: 'Available', options: ['Available', 'Busy', 'Away'], storageKey: 'profilePresence'},
        {id: 'Account.Your role', value: 'Lead Architect', default: '', storageKey: 'profileRole'},
        {id: 'Account.Photo', value: '', default: '', storageKey: 'profilePhoto'}
      ],
      runtimeParameters: {toast_visible_ms: 4000, export_release_ms: 1000, voice_hold_ms: 500},
      workspaces: [
        {id: 'ws-1', name: 'Tower North', available: true},
        {id: 'ws-2', name: 'Civic Museum', available: true}
      ],
      activeWorkspace: 'ws-1',
      hosts: [
        {id: 'revit', name: 'Revit 2026', state: 'connected'},
        {id: 'rhino', name: 'Rhino 8', state: 'listening'}
      ],
      hostsProbing: false,
      liveAgents: [
        {agent: 'claude-code', handle: 'claude-code', name: 'Claude Code', calls: 12, tokens: 18400, status: 'working'},
        {agent: 'codex', handle: 'codex', name: 'Codex', calls: 5, tokens: 6200, status: 'idle'}
      ],
      agents: [
        {id: 'claude-code', name: 'Claude Code', runtime: 'claude', status: 'working', models: ['claude-sonnet-4', 'claude-opus-4'], model: 'claude-sonnet-4'},
        {id: 'codex', name: 'Codex', runtime: 'codex', status: 'idle', models: ['gpt-5-codex'], model: 'gpt-5-codex'}
      ],
      providers: [
        {id: 'claude-code', name: 'Claude Code', model: 'claude-sonnet-4', models: ['claude-sonnet-4', 'claude-opus-4']},
        {id: 'codex', name: 'Codex', model: 'gpt-5-codex', models: ['gpt-5-codex']}
      ],
      people: [
        {id: 'person-1', name: 'Tariq Mansour', email: 'tariq@studio.test', accessRole: 'Member', selectionNodeId: 'node-wall-1'}
      ],
      watch: {
        capability: true,
        reason: '',
        grants: [
          {id: 'grant-watch-1', grantee: 'lina@client.test', name: 'Lina Haddad', session: 'C:/Fixture/Tower.archhub', expires: null, active: true}
        ]
      },
      watching: {capability: true, reason: '', watching: []},
      devices: [],
      tasks: [
        {id: 'task-alpha', title: 'Core facade grid', status: 'WIP', agent: 'claude-code', sessionPath: 'alpha.archhub', messages: []},
        {id: 'task-beta', title: 'Door schedule check', status: 'WIP', agent: 'codex', sessionPath: 'beta.archhub', messages: []}
      ],
      focusedTask: 'task-alpha',
      notifications: [
        {id: 'approval:card1', text: 'Write curtain wall mullions', taskId: 'task-alpha', approvalId: 'ap-1', read: false},
        {id: 'message:msg1', text: 'Core facade grid: Completed level 3 check', taskId: 'task-alpha', read: false}
      ],
      approvals: [
        {
          id: 'ap-1',
          title: 'Write curtain wall mullions',
          status: 'pending',
          approvalKind: 'ask',
          taskId: 'task-alpha',
          taskTitle: 'Core facade grid',
          who: 'Claude Code',
          summary: 'Updates 24 mullion profiles on Level 03.',
          preview: '24 elements in Curtain Wall North',
          why: 'Matches thermal mullion spec 65x150 mm.',
          diff: '- Mullion 50x120\n+ Mullion 65x150',
          rows: []
        }
      ],
      graph: {
        id: 'graph-1',
        scopeKey: 'graph-1',
        name: 'Tower North',
        nodes: [
          {id: 'node-wall-1', title: 'Read Curtain Walls', status: 'Done', color: '#d97757', inputs: [], outputs: [{name: 'Walls', type: 'Elements'}], params: {}, paramDefs: []}
        ],
        wires: []
      },
      graphs: [{id: 'graph-1', name: 'Tower North', nodes: []}],
      libraryPorts: [
        {id: 'revit.walls', title: 'Read Walls', category: 'Elements', inputs: [], outputs: [{name: 'Elements', type: 'Elements'}]},
        {id: 'text.join', title: 'Join Text', category: 'Text', inputs: [{name: 'Parts', type: 'Text'}], outputs: [{name: 'Text', type: 'Text'}]},
        {id: 'math.sum', title: 'Add Numbers', category: 'Number', inputs: [{name: 'A', type: 'Number'}], outputs: [{name: 'Sum', type: 'Number'}]},
        {id: 'sheet.pack', title: 'Place Views on Sheet', category: 'Sheet', inputs: [{name: 'Sheet', type: 'Sheet'}], outputs: []},
        {id: 'file.ifc', title: 'Export IFC File', category: 'File', inputs: [{name: 'Path', type: 'File'}], outputs: []}
      ],
      composerAttachments: [],
      composerAnswer: null,
      update: {available: false, state: 'ready', installed: '2026.11.25', next: '2026.11.25', detail: 'Whole-design studio chrome, account popover and live approval cards.'},
      secrets: [],
      files: [],
      connections: [],
      templates: [],
      catalogue: [],
      runs: [],
      schedules: [],
      timesheet: {rows: [], status: 'Draft'},
      meeting: {title: '', actions: []},
      watcher: {view: 'Level 03'},
      tinyPng
    };
    let canvasTabsState = {tabs: [], active: '', split: '', collapsed: false, rail: []};
    const publish = patch => {
      state = {...state, ...patch};
      listeners.forEach(fn => fn());
    };
    window.publishFixture = publish;
    window.getFixtureState = () => state;
    window.ArchHubAPI = new Proxy({
      subscribe: fn => { listeners.add(fn); return () => listeners.delete(fn); },
      getSnapshot: () => state,
      supportsAction: () => true,
      contextLabel: id => state.graph.nodes.find(n => n.id === id)?.title || String(id || ''),
      compatibleNodes: () => [],
      readDesktopView: () => ({route: 'home'}),
      rememberDesktopView: () => {},
      setActiveSurface: surface => { window.calls.push(['setActiveSurface', surface]); },
      readCanvasTabs: async () => ({canvasTabs: canvasTabsState}),
      setCanvasTabs: async next => { canvasTabsState = next; window.calls.push(['setCanvasTabs', next]); publish({}); return {canvasTabs: next}; },
      refreshAgentSurface: async () => ({}),
      readHostAvailability: async () => ({}),
      updateProfile: async patch => {
        window.calls.push(['updateProfile', patch]);
        publish({profile: {...state.profile, ...patch}});
        return {ok: true, profile: state.profile};
      },
      setSetting: async (id, value) => {
        window.calls.push(['setSetting', id, value]);
        publish({settings: state.settings.map(r => r.id === id ? {...r, value} : r)});
        return {ok: true};
      },
      selectWorkspace: async id => {
        window.calls.push(['selectWorkspace', id]);
        publish({activeWorkspace: id});
        return {ok: true};
      },
      readNotification: async id => {
        window.calls.push(['readNotification', id]);
        publish({notifications: state.notifications.map(n => (id === 'all' || n.id === id) ? {...n, read: true} : n)});
        return {ok: true};
      },
      approve: async (id, mode) => {
        window.calls.push(['approve', id, mode]);
        publish({approvals: state.approvals.map(a => a.id === id ? {...a, status: 'approved'} : a)});
        return {ok: true};
      },
      decline: async id => {
        window.calls.push(['decline', id]);
        publish({approvals: state.approvals.map(a => a.id === id ? {...a, status: 'declined'} : a)});
        return {ok: true};
      },
      addNode: async (typeId, point) => {
        const made = {id: 'added-' + (window.calls.length + 1), title: typeId, type: typeId, inputs: [], outputs: [], params: {}, paramDefs: []};
        window.calls.push(['addNode', typeId, point || null]);
        publish({graph: {...state.graph, nodes: [...state.graph.nodes, made]}});
        return made;
      },
      setNodeParam: async (id, key, val) => {
        window.calls.push(['setNodeParam', id, key, val]);
        return {ok: true};
      },
      setNodePresentation: async (id, values) => {
        window.calls.push(['setNodePresentation', id, values]);
        publish({graph: {...state.graph, nodes: state.graph.nodes.map(n => n.id === id ? {...n, ...values} : n)}});
        return {ok: true};
      },
      setNodeFlags: async (id, values) => {
        window.calls.push(['setNodeFlags', id, values]);
        publish({graph: {...state.graph, nodes: state.graph.nodes.map(n => n.id === id ? {...n, ...values, color: values.color || undefined} : n)}});
        return {ok: true};
      },
      openTaskGraph: async id => {
        window.calls.push(['openTaskGraph', id]);
        return {ok: true};
      },
      setTaskDelegate: async (taskId, agentId) => {
        window.calls.push(['setTaskDelegate', taskId, agentId]);
        return {ok: true};
      },
      setProviderModel: async (providerId, mdl) => {
        window.calls.push(['setProviderModel', providerId, mdl]);
        publish({providers: state.providers.map(p => p.id === providerId ? {...p, model: mdl} : p)});
        return {ok: true};
      },
      stopAgentSession: async id => {
        window.calls.push(['stopAgentSession', id]);
        return {ok: true};
      },
      readWatchGrants: async () => state.watch,
      readWatching: async () => state.watching,
      readWatchedSession: async () => ({state: 'live', updated: '2026-11-25T10:00:00Z', projection: {nodes: [{id: 'n1', label: 'Walls', status: 'done', position: {x: 0, y: 0}, result: {count: 4}}], wires: [], groups: []}}),
      stopWatcher: async id => {
        window.calls.push(['stopWatcher', id]);
        return {ok: true};
      },
      setGuestRole: async (id, role) => {
        window.calls.push(['setGuestRole', id, role]);
        return {ok: true};
      },
      removeGuest: async id => {
        window.calls.push(['removeGuest', id]);
        return {ok: true};
      },
      signIn: async flag => {
        window.calls.push(['signIn', flag]);
        return {ok: true};
      },
      sendFeedback: async text => {
        window.calls.push(['sendFeedback', text]);
        return {ok: true};
      },
      listTasks: async () => state.tasks
    }, {
      get: (target, key) => key in target || typeof key !== 'string' ? target[key] : async (...a) => {
        window.calls.push([key, ...a]);
        return {ok: true};
      }
    });
  }, TINY_PNG);

  for (const name of ['tokens.jsx', 'ds/index.jsx', 'icons.jsx', 'ui.jsx', 'answer-widgets.jsx', 'access.jsx']) {
    const code = transformSync(fs.readFileSync(path.join(studio, name), 'utf8'), {loader: 'jsx', target: 'es2022'}).code;
    await page.addScriptTag({content: code});
  }

  await page.evaluate(() => {
    const blank = () => null;
    window.UI.homeRows = s => ({
      running: (s.liveAgents || []).filter(a => a.status === 'working').length,
      needsYou: (s.approvals || []).filter(a => a.status === 'pending').length
    });
    window.UI.homeDestination = r => r === 'library' ? {face: 'canvas', library: true} : r === 'canvas' ? {face: 'canvas'} : null;
    window.UI.isHomeRegistration = () => false;
    window.UI.homeShown = () => 'task-alpha';
    window.UI.workshopPeople = () => ({choices: [{key: 'claude', name: 'Claude Code', handle: 'claude-code'}]});
    window.UI.chatTurn = (_c, _to, text) => ({prompt: text, agent: 'BABOOM'});
    window.UI.paletteCommands = (_s, u) => [
      {id: 'page.docs', label: 'Docs', group: 'Pages', action: () => u.go('docs')},
      {id: 'page.community', label: 'Community', group: 'Pages', action: () => u.go('community')}
    ];
    window.UI.openSurfaceMenu = () => {};
    window.UI.keyboardContextMenu = () => false;
    window.UI.ActionStatus = ({action}) => action?.error ? React.createElement('p', {role: 'alert'}, action.error) : null;
    window.UI.BaboomSprite = blank;
    window.UI.WorkspaceRows = () => React.createElement('div', {'data-workspace-picker': 'true'}, 'Workspace folder picker');
    window.UI.AccountUsage = blank;
    window.UI.BillingAccount = blank;
    window.UI.Canvas = () => React.createElement('div', {className: 'node-canvas'}, 'Canvas stage');
    window.UI.Docs = () => React.createElement('main', {'data-screen': 'docs'}, 'Docs screen');
    window.UI.Community = () => React.createElement('main', {'data-screen': 'community'}, 'Community screen');
    window.UI.Social = () => React.createElement('main', {'data-screen': 'social'}, 'Social screen');
    window.UI.Receipts = () => React.createElement('main', {'data-screen': 'receipts'}, 'App health receipts');
    window.UI.Settings = ({page}) => React.createElement('main', {'data-screen': 'settings', 'data-settings-page': page}, 'Settings · ' + page);
    window.UI.Home = () => {
      const u = window.UI.useApp();
      window.appCtx = u;
      return React.createElement('div', {style: {display: 'grid', gridTemplateRows: '1fr auto', height: '100%'}},
        React.createElement('div', {style: {padding: 16, display: 'flex', gap: 12, alignItems: 'flex-start'}},
          React.createElement(window.UI.Av, {id: 'claude-code', menu: true}),
          React.createElement(window.UI.Av, {id: 'person-1', person: true, menu: true, selectionNodeId: 'node-wall-1'}),
          React.createElement(window.UI.GuestAvatar, {grant: window.getFixtureState().watch.grants[0]})
        ),
        React.createElement(window.UI.Composer, null)
      );
    };
  });

  const appCode = transformSync(fs.readFileSync(path.join(studio, 'app.jsx'), 'utf8'), {loader: 'jsx', target: 'es2022'}).code;
  await page.addScriptTag({content: appCode});
  await page.getByRole('navigation', {name: 'Main navigation'}).waitFor();
  return pageErrors;
}

test('P2-A1: Account popover, clamping above composer, inline profile/role/status, crop photo + undo, menus', async () => {
  const browser = await chromium.launch({headless: true, executablePath: chromiumExecutable()});
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 800}});
    const errors = await mountAppShell(page);

    const nav = page.getByRole('navigation', {name: 'Main navigation'});
    assert.deepEqual(
      await nav.getByRole('button').evaluateAll(btns => btns.map(b => b.getAttribute('aria-label'))),
      ['Home', 'Canvas', 'Docs', 'Settings', 'Your account']
    );

    await nav.getByRole('button', {name: 'Your account', exact: true}).click();
    const card = page.locator('[data-design="profile.card"]');
    await card.waitFor();
    assert.equal(await page.getByText(/0 people/).count(), 0, 'retired Account modal is never shown');

    const [cardBox, composerBox] = await Promise.all([
      card.boundingBox(),
      page.locator('[data-design="composer.surface"]').boundingBox()
    ]);
    assert.ok(cardBox.y + cardBox.height <= composerBox.y, `profile card (${cardBox.y + cardBox.height}) must stay above composer (${composerBox.y})`);

    assert.equal(await card.locator('[data-design="profile.plan"]').textContent(), 'Solo · beta');
    await card.getByText('architect@studio.test').waitFor();

    const nameInput = card.getByRole('textbox', {name: 'Name', exact: true});
    await nameInput.fill('Nadia K. Faris');
    await nameInput.press('Enter');
    await page.locator('[data-toast]').getByText('Name saved.').waitFor();

    const roleInput = card.getByRole('textbox', {name: 'Your role', exact: true});
    await roleInput.fill('Principal BIM Lead');
    await roleInput.press('Enter');
    await page.locator('[data-toast]').getByText('Role saved. Agents read it on the You node.').waitFor();

    await card.getByLabel('Presence status').selectOption('Busy');
    await page.waitForFunction(() => document.querySelector('[aria-label="Your account"] [data-presence="Busy"]') !== null);

    await card.getByRole('button', {name: /Language/}).click();
    await card.getByRole('button', {name: /العربية · Arabic/}).click();
    assert.equal(await page.evaluate(() => document.documentElement.lang), 'ar');
    await card.getByRole('button', {name: /English/}).click();
    assert.equal(await page.evaluate(() => document.documentElement.lang), 'en');

    await card.getByRole('button', {name: /Help and feedback/}).click();
    await card.getByRole('button', {name: 'Send feedback…', exact: true}).click();
    const fbDialog = page.getByRole('dialog', {name: 'Send feedback'});
    await fbDialog.waitFor();
    await fbDialog.getByLabel('Feedback').fill('Crisp account popover!');
    await fbDialog.getByRole('button', {name: 'Send', exact: true}).click();
    await page.locator('[data-toast]').getByText('Feedback sent.').waitFor();

    await nav.getByRole('button', {name: 'Your account', exact: true}).click();
    await card.waitFor();
    await card.getByRole('button', {name: 'Usage', exact: true}).click();
    const usageDlg = page.getByRole('dialog', {name: 'Usage today'});
    await usageDlg.waitFor();
    await usageDlg.getByText('Claude Code').waitFor();
    await usageDlg.getByRole('button', {name: 'Settings › Agents', exact: true}).click();
    assert.equal(await page.locator('[data-screen="settings"]').getAttribute('data-settings-page'), 'Agents');

    await nav.getByRole('button', {name: 'Your account', exact: true}).click();
    await card.getByRole('button', {name: "What's new", exact: true}).click();
    const wnDlg = page.getByRole('dialog', {name: "What's new"});
    await wnDlg.waitFor();
    await wnDlg.getByText('2026.11.25').waitFor();
    await wnDlg.getByRole('button', {name: 'Close dialog'}).click();

    await page.evaluate(() => window.appCtx.show('Crop your photo', {src: window.getFixtureState().tinyPng, prevPhoto: ''}));
    const cropDlg = page.getByRole('dialog', {name: 'Crop your photo'});
    await cropDlg.waitFor();
    await cropDlg.getByText('How it shows').waitFor();
    await cropDlg.getByLabel('Zoom').fill('1.5');
    await cropDlg.getByRole('button', {name: 'Use photo', exact: true}).click();
    await page.locator('[data-toast]').getByText('Photo updated.').waitFor();
    assert.ok(await page.evaluate(() => Boolean(window.getFixtureState().profile.photo)));

    await nav.getByRole('button', {name: 'Your account', exact: true}).click();
    await card.getByRole('button', {name: 'Remove photo', exact: true}).click();
    const undoToast = page.locator('[data-toast]');
    await undoToast.getByText('Photo removed.').waitFor();
    await undoToast.getByRole('button', {name: 'Undo', exact: true}).click();
    assert.ok(await page.evaluate(() => Boolean(window.getFixtureState().profile.photo)), 'Undo restores removed photo');

    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
});

test('P2-A2: Agent avatar menu, Person avatar menu, Guest avatar menu & User Rail context menu', async () => {
  const browser = await chromium.launch({headless: true, executablePath: chromiumExecutable()});
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 800}});
    const errors = await mountAppShell(page);

    await page.getByRole('button', {name: 'Agent Claude Code', exact: true}).click();
    const avMenu = page.locator('[data-design="avatar.menu"]');
    await avMenu.waitFor();
    for (const label of ['Go to its node', 'Open its thread', 'Message', 'Assign to a task…', 'See its work (1)', 'Switch model…', 'Stop']) {
      await avMenu.getByRole('menuitem', {name: new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))}).waitFor();
    }
    await avMenu.getByRole('menuitem', {name: /Switch model/}).click();
    await avMenu.getByRole('menuitemradio', {name: /claude-opus-4/}).click();
    await page.locator('[data-toast]').getByText('Switched Claude Code to claude-opus-4.').waitFor();

    await page.getByRole('button', {name: 'Person Tariq Mansour', exact: true}).click();
    const pMenu = page.locator('[data-design="person.menu"]');
    await pMenu.waitFor();
    await pMenu.getByRole('menuitem', {name: 'Mention Tariq Mansour', exact: true}).click();
    assert.match(await page.locator('[data-design="composer.msg"]').inputValue(), /@tariq-mansour/);

    await page.getByRole('button', {name: 'Guest Lina Haddad', exact: true}).click();
    const gMenu = page.locator('[data-design="guest.menu"]');
    await gMenu.waitFor();
    for (const label of ['Preview what they see', 'Stop sharing with Lina', 'Change to role', 'Remove from this Canvas']) {
      await gMenu.getByRole('menuitem', {name: new RegExp(label)}).waitFor();
    }
    await gMenu.getByRole('menuitem', {name: /Change to role/}).click();
    await gMenu.getByRole('menuitemradio', {name: /Change to Comment/}).click();
    await page.locator('[data-toast]').getByText('Changed Lina to Comment.').waitFor();

    await page.evaluate(async () => {
      await window.appCtx.setPinnedRail(['task-alpha', 'task-beta']);
    });
    const nav = page.getByRole('navigation', {name: 'Main navigation'});
    await nav.getByRole('button', {name: 'Core facade grid', exact: true}).waitFor();
    await nav.getByRole('button', {name: 'Door schedule check', exact: true}).click({button: 'right'});
    const railMenu = page.getByRole('menu', {name: 'Rail item menu'});
    await railMenu.waitFor();
    await railMenu.getByRole('menuitem', {name: 'Move up', exact: true}).click();
    assert.deepEqual(await page.evaluate(() => window.appCtx.pinnedRailIds), ['task-beta', 'task-alpha']);

    await nav.getByRole('button', {name: 'Door schedule check', exact: true}).click({button: 'right'});
    await page.getByRole('menu', {name: 'Rail item menu'}).getByRole('menuitem', {name: 'Remove from the rail', exact: true}).click();
    assert.deepEqual(await page.evaluate(() => window.appCtx.pinnedRailIds), ['task-alpha']);

    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
});

test('P2-A5: Header mark/workspace/bell popovers, Add node filters+keys+value, Colour swatches, Toasts, Confirm & ApprovalCard', async () => {
  const browser = await chromium.launch({headless: true, executablePath: chromiumExecutable()});
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 800}});
    const errors = await mountAppShell(page);

    assert.match(await page.locator('[data-design="status.on-this-pc"]').textContent(), /On this PC · 2 ready.*1 live agent/);
    assert.equal(await page.locator('.app-window > footer').count(), 0, 'no app-window footer band');

    await page.locator('[data-design="header.mark"]').click();
    const markMenu = page.locator('[data-design="mark.menu"]');
    await markMenu.waitFor();
    for (const item of ['All pages…', 'How everything connects', 'App health', 'Community', 'Social media', 'Docs']) {
      await markMenu.getByRole('menuitem', {name: item, exact: true}).waitFor();
    }
    await markMenu.getByRole('menuitem', {name: 'App health', exact: true}).click();
    await page.locator('[data-screen="receipts"]').waitFor();

    await page.locator('[data-design="header.workspace"]').click();
    const wsMenu = page.locator('[data-design="workspace.menu"]');
    await wsMenu.waitFor();
    assert.match(await wsMenu.getByRole('menuitemradio', {name: /Tower North/}).textContent(), /✓/);
    await wsMenu.getByRole('menuitemradio', {name: /Civic Museum/}).click();
    assert.equal(await page.evaluate(() => window.getFixtureState().activeWorkspace), 'ws-2');

    await page.locator('[data-design="header.bell"]').click();
    const bellPop = page.locator('[data-design="notifications.popover"]');
    await bellPop.waitFor();
    await bellPop.getByRole('button', {name: 'Mark all read', exact: true}).click();
    assert.equal(await page.locator('.header-count').count(), 0);
    await bellPop.getByRole('button', {name: /Write curtain wall mullions/}).first().click();
    const approvalDlg = page.getByRole('dialog', {name: 'Approve'});
    await approvalDlg.waitFor();
    await approvalDlg.getByText('Needs your approval').waitFor();
    await approvalDlg.getByText(/Core facade grid · Claude Code asked/).waitFor();
    await approvalDlg.getByText('24 elements in Curtain Wall North').waitFor();
    await approvalDlg.getByText(/Matches thermal mullion spec/).waitFor();
    await approvalDlg.getByText(/\+ Mullion 65x150/).waitFor();
    await approvalDlg.getByRole('button', {name: /Ask why/}).waitFor();
    await approvalDlg.getByRole('button', {name: 'Reject', exact: true}).waitFor();
    await approvalDlg.getByRole('button', {name: /Approve\s+Enter/}).click();
    await approvalDlg.locator('[data-design="approval.confirmed"]').getByText('Approved. Running now.').waitFor();
    await approvalDlg.getByRole('button', {name: 'Close dialog'}).click();

    await page.evaluate(() => window.appCtx.show('Add node'));
    const addDlg = page.getByRole('dialog', {name: 'Add node'});
    await addDlg.waitFor();
    for (const pill of ['All', 'Text', 'Number', 'Elements', 'Sheet', 'File']) {
      await addDlg.getByRole('button', {name: pill, exact: true}).waitFor();
    }
    assert.equal(await addDlg.locator('kbd').first().textContent(), '1');
    await addDlg.getByRole('button', {name: 'Number', exact: true}).click();
    assert.equal(await addDlg.locator('.v22g-results button').count(), 1);
    await addDlg.getByLabel('Add node').fill('42.5');
    await addDlg.locator('[data-design="addnode.value"]').getByText(/Value: 42\.5/).click();
    await addDlg.waitFor({state: 'hidden'});
    assert.ok(await page.evaluate(() => window.calls.some(c => c[0] === 'addNode')));

    await page.evaluate(() => window.appCtx.show('Colour', {id: 'node-wall-1'}));
    const colDlg = page.getByRole('dialog', {name: 'Colour'});
    await colDlg.waitFor();
    for (const sw of ['Accent', 'Amber', 'Green', 'Teal', 'Blue', 'Violet', 'None']) {
      await colDlg.getByRole('button', {name: sw, exact: true}).waitFor();
    }
    await colDlg.getByRole('button', {name: 'None', exact: true}).click();
    assert.equal(await page.evaluate(() => window.getFixtureState().graph.nodes[0].color), undefined);

    await page.evaluate(() => {
      window.confirmed = false;
      window.appCtx.confirm('Remove Tower North from workspaces?', () => { window.confirmed = true; return {ok: true}; }, {
        heading: 'Remove workspace',
        detail: 'Files on disk stay untouched.',
        confirmLabel: 'Remove workspace'
      });
    });
    const confDlg = page.getByRole('dialog', {name: 'Remove workspace'});
    await confDlg.waitFor();
    await confDlg.getByText('Files on disk stay untouched.').waitFor();
    await confDlg.getByRole('button', {name: 'Remove workspace', exact: true}).click();
    assert.equal(await page.evaluate(() => window.confirmed), true);

    await page.evaluate(() => window.appCtx.setToast({text: 'Connector warning', tone: 'warn', label: 'Inspect', action: () => { window.toastActed = true; }}));
    const toast = page.locator('[data-toast]');
    await toast.waitFor();
    assert.equal(await toast.getAttribute('data-toast-tone'), 'warn');
    await toast.hover();
    assert.equal(await toast.getAttribute('data-toast-paused'), 'true');
    await toast.getByRole('button', {name: 'Inspect', exact: true}).click();
    assert.equal(await page.evaluate(() => window.toastActed), true);

    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
});
