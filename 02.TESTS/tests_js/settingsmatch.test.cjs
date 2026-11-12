// SETTINGSMATCH: the built Settings sheet against the approved board (penpot-settings-1680-r1963-native).
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');
const {chromium} = require('playwright');
const studio = path.resolve(__dirname, '../../01.APP/nodelang/studio');
process.stdout.write(execFileSync(process.execPath, ['--max-old-space-size=512', path.resolve(__dirname, '../../03.TOOLS/packaging/compile_studio.cjs')], {windowsHide: true}));
const compiled = name => fs.readFileSync(path.join(studio, 'compiled', name.replace(/\//g, '-').replace(/\.jsx$/, '.js')), 'utf8');
const sources = ['tokens.jsx', 'ds/index.jsx', 'icons.jsx', 'ui.jsx', 'answer-widgets.jsx', 'ds_home2.jsx', 'ds_library.jsx', 'ds_workshop3.jsx', 'surfaces.jsx', 'ds_settings3.jsx', 'app.jsx'].map(compiled);
const EMAIL = 'a.very.long.address.for.the.account.value.box@example-office-domain.test';
const SESSIONS = 'C:\\Users\\someone\\AppData\\Local\\Temp\\applook-7ngv12us\\LOCALAPPDATA\\ArchHub\\Sessions';
const LONG_TASK = 'Review the drawing set and '.repeat(30).trim();

function executable() {
  const cache = process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(os.userInfo().homedir, 'AppData/Local/ms-playwright');
  const shell = fs.existsSync(cache) && fs.readdirSync(cache).filter(name => /^chromium_headless_shell-\d+$/.test(name)).sort((a, b) => Number(b.split('-').at(-1)) - Number(a.split('-').at(-1)))[0];
  const full = fs.existsSync(cache) && fs.readdirSync(cache).filter(name => /^chromium-\d+$/.test(name)).sort((a, b) => Number(b.split('-').at(-1)) - Number(a.split('-').at(-1)))[0];
  return process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || (process.platform === 'win32' && (shell || full) ? path.join(cache, shell || full, shell ? 'chrome-headless-shell-win64/chrome-headless-shell.exe' : 'chrome-win64/chrome.exe') : undefined);
}

async function mount(page, profile, extra = {}) {
  await page.route('**/*', route => route.fulfill({contentType: 'text/html', body: '<div id="root"></div>'}));
  await page.goto('http://settingsmatch.test');
  await page.addStyleTag({path: path.join(studio, 'style.css')});
  await page.addStyleTag({content: 'html,body,#root{height:100%;margin:0}'});
  for (const name of ['react.js', 'react-dom.js']) await page.addScriptTag({path: path.join(studio, 'vendor', name)});
  await page.addScriptTag({content: require('./studio_xyflow.cjs').script()});
  await page.addScriptTag({path: path.join(studio, 'compiled/react-resizable-panels.js')});
  await page.evaluate(() => { window.fetch = () => new Promise(() => {}); });
  await page.addScriptTag({path: path.join(studio, 'compiled/api.js')});
  await page.evaluate(({profile, SESSIONS, LONG_TASK, extra}) => {
    const s = window.structuredClone(window.ArchHubAPI.getSnapshot());
    Object.assign(s.profile, profile);
    s.sync = 'Local session file';
    s.sessionsFolder = SESSIONS;
    s.graph = {...s.graph, id: 'long', name: LONG_TASK};
    s.tasks = [];
    Object.assign(s, extra);
    window.surfaces = [];
    window.ArchHubAPI = {...window.ArchHubAPI, getSnapshot: () => s, subscribe: () => () => {},
      executeAction: (id, callback) => { if (id === 'ui.select') return callback(); throw Error('Unexpected action: ' + id); },
      setActiveSurface: surface => window.surfaces.push(surface), supportsAction: () => true,
      readCanvasTabs: async () => ({canvasTabs: {tabs: [], active: '', split: '', collapsed: false}}), setCanvasTabs: async () => ({ok: true}),
      readSessionListFilters: async () => ({sessionListFilters: {home: 'all', library: 'all'}}), setSessionListFilter: async () => ({ok: true}),
      readHomeLayout: async () => ({homeLayout: {width: 300, collapsed: false, resume: '', order: [], hidden: []}}), setHomeLayout: async () => ({ok: true}),
      refreshAgentSurface: async () => null, refreshRouter: async () => ({default_model: 'free', models: [], fallback_models: [], requests: [], free_first: true}),
      readHostAvailability: async () => [], listAgentsWorking: async () => [], refreshSettingsControls: async () => ({}), readSessionsFolder: async () => SESSIONS};
  }, {profile, SESSIONS, LONG_TASK, extra});
  for (let i = 0; i < sources.length - 1; i++) await page.addScriptTag({content: sources[i]});
  await page.evaluate(() => {
    const blank = () => null;
    Object.assign(window.UI, {BaboomSprite: blank, ScheduleResponsibility: blank, Canvas: blank, Docs: () => React.createElement('div', null, 'Docs fixture')});
  });
  await page.addScriptTag({content: sources.at(-1)});
  await page.getByRole('navigation', {name: 'Main navigation'}).waitFor();
}

test('SETTINGSMATCH: Account sheet matches the board at 900-1920 and the composer chip stays one line', async () => {
  const browser = await chromium.launch({headless: true, executablePath: executable()});
  try {
    for (const [profile, account] of [[{name: 'Account', email: EMAIL, signedIn: false, checking: false}, 'Local session'],
                                       [{name: 'Fixture Person', email: EMAIL, signedIn: true, checking: false}, 'Signed in · ' + EMAIL]]) {
      for (const [width, height] of [[900, 900], [1009, 940], [1366, 900], [1440, 900], [1920, 1032]]) {
        const page = await browser.newPage({viewport: {width, height}});
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        await mount(page, profile);
        await page.getByRole('navigation', {name: 'Main navigation'}).getByRole('button', {name: 'Settings', exact: true}).click();
        await page.locator('[data-screen="settings/Account"] .sheet-columns:not([hidden])').waitFor();
        // 1. No composer on any settings route.
        assert.equal(await page.locator('.global-composer').count(), 0, 'composer on Settings at ' + width);
        // 2. The route reaches the API so the desktop companion can step aside.
        assert.ok((await page.evaluate(() => window.surfaces)).includes('settings/Account'));
        const fields = await page.locator('.sheet-field').evaluateAll(rows => rows.map(row => {
          const value = row.querySelector(':scope > div'), label = row.querySelector(':scope > span');
          const text = value.innerText.trim(), box = (value.querySelector('[title]') || value).getBoundingClientRect();
          return {label: label.firstChild?.textContent || '', description: label.querySelector('small')?.innerText || '', text,
            title: value.querySelector('[title]')?.getAttribute('title') || '', height: box.height,
            clipped: window.getComputedStyle(value.querySelector('[title]') || value).textOverflow};
        }));
        const field = name => fields.find(row => row.label === name);
        // 5. The account row shows the real state, never a permanent "Checking…".
        assert.equal(field('Account')?.text, account, JSON.stringify(fields));
        // 6. No dead control: rows without a settings-owner row are gone.
        assert.equal(await page.getByText('Not available').count(), 0);
        // 3. One-line value boxes; full value in the tooltip; a path is shown short.
        for (const name of ['Account', 'Email', 'Sessions folder']) {
          assert.ok(field(name).height <= 24, name + ' wraps at ' + width + ': ' + JSON.stringify(field(name)));
          assert.equal(field(name).clipped, 'ellipsis', name);
        }
        assert.equal(field('Email').title, EMAIL);
        assert.equal(field('Sessions folder').title, SESSIONS);
        assert.equal(field('Sessions folder').text, '…\\ArchHub\\Sessions');
        // 4. Label plus a one-line grey description for every Account row.
        for (const name of ['Account', 'Name', 'Email', 'Sessions folder', 'Workspace folder']) assert.ok(field(name)?.description, name + ' has no description');
        // 7. A subtitle under the heading.
        assert.ok((await page.locator('.sheet-page-heading p').innerText()).trim().length > 0);
        // 8. The header shows at most one short phrase on Settings.
        const status = (await page.locator('.header-status').innerText()).replace(/\s+/g, ' ').trim();
        assert.ok(!status.includes('·') && status.length <= 24, 'header status: ' + status);
        // Board heading size; no empty Privacy section, the secrets note stays.
        assert.equal(await page.locator('.sheet-page-heading h2').evaluate(el => window.getComputedStyle(el).fontSize), '22px');
        assert.equal(await page.getByRole('heading', {name: 'Privacy', exact: true}).count(), 0);
        await page.getByText('Secrets stay in protected connections, never in .archhub files.').waitFor();
        await page.getByRole('button', {name: 'Manage protected connections', exact: true}).waitFor();
        // Fluid: nothing scrolls sideways.
        assert.equal(await page.evaluate(() => window.document.documentElement.scrollWidth <= window.innerWidth), true, 'horizontal scroll at ' + width);
        // 9. The composer scope chip off Settings is one line with the full name in its tooltip.
        await page.getByRole('navigation', {name: 'Main navigation'}).getByRole('button', {name: 'Docs', exact: true}).click();
        const chip = page.locator('.global-composer .composer-scope .tab-button').first();
        await chip.waitFor();
        const chipBox = await chip.evaluate(el => ({height: el.getBoundingClientRect().height, title: el.getAttribute('title'), lines: Math.round(el.scrollHeight / parseFloat(window.getComputedStyle(el).lineHeight || '16'))}));
        assert.ok(chipBox.height <= 28, 'composer chip: ' + JSON.stringify(chipBox));
        assert.equal(chipBox.title, LONG_TASK);
        assert.deepEqual(errors, []);
        await page.close();
      }
    }
    console.log('PASS settingsmatch: Account sheet at 900/1009/1366/1440/1920, signed in and local');
  } finally { await browser.close(); }
});

test('SETTINGSMATCH: the active surface is reported to the app so the desktop companion can step aside', async () => {
  const requests = [];
  const window = {ARCHHUB_AUTHORITY: {}, structuredClone: globalThis.structuredClone, ARCHHUB_BOOT: {home_load_ms: 60000, token: 'lease', csrf: 'csrf'},
    Uint8Array: globalThis.Uint8Array, dispatchEvent() {}, addEventListener() {}, AH: {inkSoft: '#888'}, crypto: require('node:crypto')};
  window.ArchHubStudioAuthority = {create: ({get}) => { let snapshot = null; return {load: async () => { snapshot = {canvas: await get('/api/universal/canvas')}; return snapshot.canvas; }, getSnapshot: () => snapshot, clear: () => { snapshot = null; }, adopt: async canvas => { snapshot = {canvas}; return canvas; }, transact: async action => { const canvas = await action(); snapshot = {canvas}; return canvas; }}; }};
  const context = {window, setTimeout, clearTimeout, document: {hidden: false, addEventListener() {}}, CustomEvent: class {}, sessionStorage: {getItem() { return null; }},
    URLSearchParams, TextEncoder: globalThis.TextEncoder, AbortSignal: globalThis.AbortSignal, console,
    fetch: async (url, options) => {
      requests.push({url, body: options.body && JSON.parse(options.body)});
      const data = url === '/api/universal/canvas' ? {root: 'canvas', nodes: [], wires: [], authorization: {principal: 'local-process'}} : {ok: true};
      return {ok: true, status: 200, json: async () => data};
    }};
  vm.runInNewContext(fs.readFileSync(path.join(studio, 'api.js'), 'utf8'), context);
  await window.ArchHubAPI.ready;
  window.ArchHubAPI.setActiveSurface('settings/Account');
  window.ArchHubAPI.setActiveSurface('settings/Account');
  window.ArchHubAPI.setActiveSurface('home');
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.deepEqual(requests.filter(row => row.url === '/api/universal/studio-surface').map(row => row.body.surface), ['settings/Account', 'home']);
});

test('SETTINGSMATCH review: header keeps what waits for you, the account check ends and acts, sections never stand empty', async () => {
  const browser = await chromium.launch({headless: true, executablePath: executable()});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 900}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await mount(page, {name: 'Account', email: '', signedIn: false, checking: true},
      {runtimeParameters: {account_http_ms: 1500}, approvals: [{id: 'a1', title: 'Send', status: 'pending', rows: []}, {id: 'a2', title: 'Post', status: 'pending', rows: []}]});
    const nav = page.getByRole('navigation', {name: 'Main navigation'});
    await nav.getByRole('button', {name: 'Settings', exact: true}).click();
    await page.locator('[data-screen="settings/Account"] .sheet-columns:not([hidden])').waitFor();
    // 1. Something waiting for him is never hidden on Settings.
    assert.equal((await page.locator('.header-status').innerText()).trim(), '2 wait for you');
    // 6. The account check shows, then ends in a real state, and the row acts.
    const account = page.locator('.sheet-field').filter({has: page.locator(':scope > span', {hasText: /^Account/})}).first().locator(':scope > div');
    assert.equal((await account.innerText()).trim(), 'Checking…');
    await page.waitForFunction(() => [...window.document.querySelectorAll('.sheet-field')].some(row => row.innerText.includes('Local session')), null, {timeout: 12000});
    await account.locator('button').click();
    await page.getByRole('heading', {name: 'Sign in'}).first().waitFor();
    await page.getByRole('button', {name: 'Close dialog', exact: true}).click();
    // 3 + 4. Models: no empty section heading, no constant value, one label per switch.
    await page.getByRole('navigation', {name: 'Settings categories'}).getByRole('button', {name: 'Models', exact: true}).click();
    await page.locator('select[aria-label="Default model"]').waitFor();
    assert.equal(await page.getByRole('heading', {name: 'Follow through', exact: true}).count(), 0);
    assert.equal(await page.getByRole('heading', {name: 'Knowledge', exact: true}).count(), 0);
    assert.equal(await page.getByText('Not reported', {exact: true}).count(), 0);
    const free = page.locator('.sheet-field').filter({hasText: 'Prefer free models'});
    assert.equal(await free.locator(':scope > div span').count(), 0, 'a second On/Off label beside the switch');
    assert.equal(await free.getByRole('switch').getAttribute('aria-checked'), 'true');
    assert.equal(await page.locator('select[aria-label="Default model"]').getAttribute('title'), 'free');
    for (const section of await page.locator('.sheet-columns > section').all()) {
      assert.ok((await section.locator('.sheet-field, button, p, select').count()) > 0, 'empty section: ' + await section.innerText());
    }
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
});

test('SETTINGSMATCH review: a refused surface report is retried on the next change', async () => {
  const requests = [];
  let refuse = true;
  const window = {ARCHHUB_AUTHORITY: {}, structuredClone: globalThis.structuredClone, ARCHHUB_BOOT: {home_load_ms: 60000, token: 'lease', csrf: 'csrf'},
    Uint8Array: globalThis.Uint8Array, dispatchEvent() {}, addEventListener() {}, AH: {inkSoft: '#888'}, crypto: require('node:crypto')};
  window.ArchHubStudioAuthority = {create: ({get}) => { let snapshot = null; return {load: async () => { snapshot = {canvas: await get('/api/universal/canvas')}; return snapshot.canvas; }, getSnapshot: () => snapshot, clear: () => { snapshot = null; }, adopt: async canvas => { snapshot = {canvas}; return canvas; }, transact: async action => { const canvas = await action(); snapshot = {canvas}; return canvas; }}; }};
  const context = {window, setTimeout, clearTimeout, document: {hidden: false, addEventListener() {}}, CustomEvent: class {}, sessionStorage: {getItem() { return null; }},
    URLSearchParams, TextEncoder: globalThis.TextEncoder, AbortSignal: globalThis.AbortSignal, console,
    fetch: async (url, options) => {
      requests.push({url, body: options.body && JSON.parse(options.body)});
      if (url === '/api/universal/studio-surface' && refuse) { refuse = false; return {ok: false, status: 500, json: async () => ({ok: false, error: 'refused'})}; }
      const data = url === '/api/universal/canvas' ? {root: 'canvas', nodes: [], wires: [], authorization: {principal: 'local-process'}} : {ok: true};
      return {ok: true, status: 200, json: async () => data};
    }};
  vm.runInNewContext(fs.readFileSync(path.join(studio, 'api.js'), 'utf8'), context);
  await window.ArchHubAPI.ready;
  window.ArchHubAPI.setActiveSurface('settings/Account');
  await new Promise(resolve => setTimeout(resolve, 10));
  window.ArchHubAPI.setActiveSurface('settings/Account');
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.deepEqual(requests.filter(row => row.url === '/api/universal/studio-surface').map(row => row.body.surface), ['settings/Account', 'settings/Account']);
});
