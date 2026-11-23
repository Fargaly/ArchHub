// Invite to watch UI: the Account watcher list, the invite form and the Home right-click item, in a real browser.
// Fixture API only (no cloud, no account, no send); the owner logic is proven in tests_replica/test_watch_grants.py.
const {test} = require('node:test');
const fs = require('node:fs'), path = require('node:path'), os = require('node:os'), assert = require('node:assert/strict');
const {chromium} = require('playwright'), {transformSync} = require('esbuild');
const studio = path.resolve(__dirname, '../../01.APP/nodelang/studio');

function executable() {
  const cache = process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(os.homedir(), 'AppData/Local/ms-playwright');
  const full = fs.existsSync(cache) && fs.readdirSync(cache).filter(name => /^chromium-\d+$/.test(name)).sort((a, b) => Number(b.split('-').at(-1)) - Number(a.split('-').at(-1)))[0];
  return process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || (process.platform === 'win32' && full ? path.join(cache, full, 'chrome-win64/chrome.exe') : undefined);
}

async function mountAccess(page, watch, watching = {capability: false, reason: 'Read-only watcher invitations are unavailable.', watching: []}) {
  page.on('pageerror', error => console.error('PAGEERROR ' + error.message));
  await page.route('**/*', route => route.fulfill({contentType: 'text/html', body: '<meta charset="utf-8"><div id="root"></div>'}));
  await page.goto('http://127.0.0.1:1/watch');
  await page.addStyleTag({path: path.join(studio, 'style.css')});
  for (const name of ['react.js', 'react-dom.js']) await page.addScriptTag({path: path.join(studio, 'vendor', name)});
  await page.evaluate(({watch, watching}) => {
    window.calls = [];
    const listeners = new Set();
    window.fixture = {profile: {name: 'Viewer One', email: 'viewer.one@example.test', plan: 'Office'}, people: [], devices: [], workspaces: [], settings: [], watch: undefined};
    const publish = values => { window.fixture = {...window.fixture, ...values}; listeners.forEach(f => f()); };
    window.ArchHubAPI = new Proxy({subscribe: f => { listeners.add(f); return () => listeners.delete(f); }, getSnapshot: () => window.fixture, supportsAction: () => true,
      readWatchGrants: async () => { window.calls.push(['readWatchGrants']); publish({watch}); return watch; },
      stopWatcher: async id => { window.calls.push(['stopWatcher', id]); return {message: 'Watching stopped.'}; },
      inviteWatcher: async (...args) => { window.calls.push(['inviteWatcher', ...args]); return {grant: {id: 'grant-1'}}; },
      readWatching: async () => { window.calls.push(['readWatching']); publish({watching}); return watching; },
      readWatchedSession: async id => { window.calls.push(['readWatchedSession', id]); return window.nextView; },
      readDevices: async () => []}, {get: (target, key) => key in target || typeof key !== 'string' ? target[key] : async () => ({})});
  }, {watch, watching});
  for (const name of ['tokens.jsx', 'ds/index.jsx', 'icons.jsx', 'ui.jsx', 'answer-widgets.jsx', 'access.jsx'])
    await page.addScriptTag({content: transformSync(fs.readFileSync(path.join(studio, name), 'utf8'), {loader: 'jsx'}).code});
  await page.evaluate(() => {
    for (const name of ['AccountUsage', 'BillingAccount']) window.UI[name] = () => null;
    function Harness() {
      const [modal, setModal] = React.useState(null);
      const u = {go: () => {}, act: async fn => fn(), show: (k, m) => setModal({k, m}), close: () => setModal(null)};
      window.closed = () => modal === null;
      return React.createElement(window.UI.Ctx.Provider, {value: u}, React.createElement('div', null,
        React.createElement(window.UI.Access), React.createElement('section', {'aria-label': 'Invite form'},
          React.createElement(window.UI.WatchInvite, {path: 'C:\\Fixture\\P-001\\Session B.archhub', title: 'Session B'})),
        modal && modal.k === 'Watching' && React.createElement('section', {role: 'dialog', 'aria-label': 'Watching'},
          React.createElement(window.UI.WatchView, {grant: modal.m.grant}))));
    }
    window.ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(Harness));
  });
}

test('Account lists watchers with Stop only when the cloud serves watching', async () => {
  const browser = await chromium.launch({headless: true, executablePath: executable()});
  try {
    const off = await browser.newPage(), errors = [];
    off.on('pageerror', e => errors.push(e.message));
    await mountAccess(off, {capability: false, reason: 'Read-only watcher invitations are unavailable.', grants: []});
    const card = off.locator('[data-watch-sessions]');
    await card.getByText('Read-only watcher invitations are unavailable.').waitFor();
    assert.equal(await card.getByRole('button', {name: /^Stop/}).count(), 0);
    const on = await browser.newPage();
    on.on('pageerror', e => errors.push(e.message));
    await mountAccess(on, {capability: true, reason: '', grants: [
      {id: 'grant-0001-abcdef', grantee: 'viewer.one@example.test', session: 'C:\\Fixture\\P-001\\Session B.archhub', expires: null, active: true},
      {id: 'grant-0002-abcdef', grantee: 'viewer.two@example.test', session: 'C:\\Fixture\\P-001\\Session B.archhub', expires: null, active: false}]});
    const stop = on.getByRole('button', {name: 'Stop viewer.one@example.test watching', exact: true});
    await stop.waitFor();
    assert.equal(await on.getByRole('button', {name: 'Stop viewer.two@example.test watching'}).count(), 0, 'an ended grant is not listed');
    assert.equal(await on.locator('[data-watch-sessions]').getByText('Session B.archhub · while you share it').count(), 1);
    await stop.click();
    assert.deepEqual(await on.evaluate(() => window.calls.find(c => c[0] === 'stopWatcher')), ['stopWatcher', 'grant-0001-abcdef']);
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
});

test('the invite form sends the right-clicked session, the email and the chosen end', async () => {
  const browser = await chromium.launch({headless: true, executablePath: executable()});
  try {
    const page = await browser.newPage(), errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await mountAccess(page, {capability: true, reason: '', grants: []});
    const form = page.locator('[data-watch-invite]'), send = form.getByRole('button', {name: 'Send invite', exact: true});
    await form.getByText('They cannot change, run or approve anything.', {exact: false}).waitFor();
    assert.equal(await send.isDisabled(), true);
    await form.getByLabel('Watcher email').fill('not an email');
    assert.equal(await send.isDisabled(), true);
    await form.getByLabel('Watcher email').fill('viewer.one@example.test');
    await form.getByLabel('Watching ends').selectOption('1h');
    await send.click();
    assert.deepEqual(await page.evaluate(() => window.calls.find(c => c[0] === 'inviteWatcher')),
      ['inviteWatcher', 'C:\\Fixture\\P-001\\Session B.archhub', 'viewer.one@example.test', '1h']);
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
});

test('a named recipient sees shared sessions read-only, then paused, then ended', async () => {
  const browser = await chromium.launch({headless: true, executablePath: executable()});
  try {
    const page = await browser.newPage(), errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await mountAccess(page, {capability: true, reason: '', grants: []}, {capability: true, reason: '', watching: [
      {id: 'grant-0001-abcdef', state: 'shared', updated: '2026-11-23T10:00:00+00:00', expires: '2026-11-23T11:00:00+00:00'},
      {id: 'grant-0002-abcdef', state: 'waiting', updated: null, expires: null}]});
    await page.evaluate(() => { window.nextView = {state: 'live', pollMs: 500, updated: '2026-11-23T10:00:05+00:00', projection: {schema: 'archhub-watch/v1',
      nodes: [{id: 'n0', label: 'Read views', status: 'done', position: {x: 0, y: 0}, result: {items: 3, count: 0}},
              {id: 'n1', label: 'Skill', status: 'running', position: {x: 260, y: 0}, result: {count: 37}},
              {id: 'n2', label: 'Step', status: 'pending', position: {x: 0, y: 200}}], wires: [['n0', 'n1']], groups: [{children: ['n0', 'n1']}]}}; });
    const card = page.locator('[data-watching-shared]');
    await card.locator('[data-watching-row="grant-0002-abcdef"]').getByText('Not shared yet').waitFor();
    await card.getByRole('button', {name: 'Watch shared session 1', exact: true}).click();
    const view = page.locator('[role="dialog"][aria-label="Watching"] [data-watch-view="live"]');
    await view.waitFor();
    assert.deepEqual(await page.evaluate(() => window.calls.filter(c => c[0] === 'readWatchedSession')[0]), ['readWatchedSession', 'grant-0001-abcdef']);
    assert.deepEqual(await view.locator('[data-watch-node]').evaluateAll(nodes => nodes.map(n => [n.dataset.watchNode, n.dataset.status, n.textContent])),
      [['n0', 'done', 'Read viewsdone · 3 items · count 0'], ['n1', 'running', 'Skillrunning · count 37'], ['n2', 'pending', 'Steppending']]);
    assert.equal(await view.locator('line').count(), 1);
    const group = view.locator('[data-watch-group]');
    assert.equal(await group.count(), 1, 'one anonymous group outline');
    assert.equal(await group.getAttribute('data-members'), '2');
    const [box, a, b, c] = await Promise.all([group, ...['n0', 'n1', 'n2'].map(id => view.locator('[data-watch-node="' + id + '"]'))].map(l => l.evaluate(e => { const r = e.getBoundingClientRect(); return {x: r.x, y: r.y, width: r.width, height: r.height}; })));
    const inside = (r, s) => s.x >= r.x && s.y >= r.y && s.x + s.width <= r.x + r.width && s.y + s.height <= r.y + r.height;
    assert.ok(inside(box, a) && inside(box, b) && !inside(box, c), 'the outline holds exactly its projected members');
    assert.equal(await view.locator('text').evaluateAll(t => t.filter(e => e.closest('[data-watch-group]')).length), 0, 'a group carries no text');
    assert.equal(await page.locator('[role="dialog"][aria-label="Watching"]').locator('button, input, textarea, select, [contenteditable]').count(), 0,
      'the watcher view has no control that could change, run, approve or save anything');
    await page.evaluate(() => { window.nextView = {state: 'paused', pollMs: 500, message: "Not live right now. It comes back when the owner's ArchHub shares it again."}; });
    await page.locator('[data-watch-view="paused"]').getByText('Not live right now.', {exact: false}).waitFor({timeout: 8000});
    await page.evaluate(() => { window.nextView = {state: 'ended', message: 'Watching has ended.'}; });
    await page.locator('[data-watch-view="ended"]').getByText('Watching has ended.').waitFor({timeout: 8000});
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
});

test('the recipient card says when the cloud cannot share yet', async () => {
  const browser = await chromium.launch({headless: true, executablePath: executable()});
  try {
    const page = await browser.newPage(), errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await mountAccess(page, {capability: false, reason: 'Read-only watcher invitations are unavailable.', grants: []});
    const card = page.locator('[data-watching-shared]');
    await card.getByText('Read-only watcher invitations are unavailable.').waitFor();
    assert.equal(await card.getByRole('button', {name: /^Watch shared/}).count(), 0);
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
});
