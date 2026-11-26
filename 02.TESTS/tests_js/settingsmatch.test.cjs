// SETTINGSMATCH: the built Settings sheet against the saved ArchHub Directions Settings design.
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
const sources = ['tokens.jsx', 'ds/index.jsx', 'icons.jsx', 'ui.jsx', 'answer-widgets.jsx', 'dock.jsx', 'ds_home2.jsx', 'ds_library.jsx', 'ds_workshop3.jsx', 'surfaces.jsx', 'ds_settings3.jsx', 'app.jsx'].map(compiled);
const EMAIL = 'a.very.long.address.for.the.account.value.box@example-office-domain.test';
const SESSIONS = 'C:\\Users\\someone\\AppData\\Local\\Temp\\applook-7ngv12us\\LOCALAPPDATA\\ArchHub\\Sessions';
const LONG_TASK = 'Review the drawing set and '.repeat(30).trim();
// The real registered Studio commands from their owner (command_registry.STUDIO_COMMANDS), read in a throwaway profile.
let registry = null;
function studioRegistry() {
  if (registry) return registry;
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'settingsmatch-registry-'));
  try {
    const env = {...process.env, LOCALAPPDATA: profile, APPDATA: profile, USERPROFILE: profile};
    const script = "import json,sys;sys.path.insert(0,'.');from nodelang import command_registry as c;print(json.dumps({'ok':True,'contexts':list(c.CONTEXTS),'commands':list(c.STUDIO_COMMANDS)}))";
    registry = JSON.parse(execFileSync(process.env.ARCHHUB_PYTHON || 'python', ['-I', '-B', '-c', script], {cwd: path.resolve(__dirname, '../../01.APP'), env, windowsHide: true, encoding: 'utf8'}));
  } finally { fs.rmSync(profile, {recursive: true, force: true}); }
  return registry;
}

function executable() {
  const cache = process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(os.userInfo().homedir, 'AppData/Local/ms-playwright');
  const shell = fs.existsSync(cache) && fs.readdirSync(cache).filter(name => /^chromium_headless_shell-\d+$/.test(name)).sort((a, b) => Number(b.split('-').at(-1)) - Number(a.split('-').at(-1)))[0];
  const full = fs.existsSync(cache) && fs.readdirSync(cache).filter(name => /^chromium-\d+$/.test(name)).sort((a, b) => Number(b.split('-').at(-1)) - Number(a.split('-').at(-1)))[0];
  return process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || (process.platform === 'win32' && (shell || full) ? path.join(cache, shell || full, shell ? 'chrome-headless-shell-win64/chrome-headless-shell.exe' : 'chrome-win64/chrome.exe') : undefined);
}

async function mount(page, profile, extra = {}) {
  await page.route('**/*', route => route.fulfill({contentType: 'text/html', body: '<div id="root"></div>'}));
  // Intercepted loopback origin like the real app: api.js needs a secure context (crypto.randomUUID).
  await page.goto('http://127.0.0.1:1/settingsmatch');
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
    // The signed-in shell cases model an admitted, ready desktop account; the gate case passes its own pending access.
    s.desktopAccess = {admitted: true, state: 'admitted', subject: 'fixture-account', email: profile.email || null, ready: true};
    Object.assign(s, extra);
    window.surfaces = [];
    window.ArchHubAPI = {...window.ArchHubAPI, getSnapshot: () => s, subscribe: () => () => {},
      executeAction: (id, callback) => { if (id === 'ui.select') return callback(); throw Error('Unexpected action: ' + id); },
      setActiveSurface: surface => window.surfaces.push(surface), supportsAction: () => true,
      readCanvasTabs: async () => ({canvasTabs: {tabs: [], active: '', split: '', collapsed: false}}), setCanvasTabs: async () => ({ok: true}),
      readSessionListFilters: async () => ({sessionListFilters: {home: 'all'}}), setSessionListFilter: async () => ({ok: true}),
      readHomeLayout: async () => ({homeLayout: {width: 300, collapsed: false, resume: '', order: [], hidden: []}}), setHomeLayout: async () => ({ok: true}),
      refreshAgentSurface: async () => { if (extra.agentError) throw Error(extra.agentError); return null; }, refreshRouter: async () => ({default_model: 'free', models: [], fallback_models: [], requests: [], free_first: true}),
      readHostAvailability: async () => [], listAgentsWorking: async () => [], refreshSettingsControls: async () => ({}), readSessionsFolder: async () => SESSIONS};
  }, {profile, SESSIONS, LONG_TASK, extra});
  for (let i = 0; i < sources.length - 1; i++) await page.addScriptTag({content: sources[i]});
  await page.evaluate(() => {
    const blank = () => null;
    Object.assign(window.UI, {BaboomSprite: blank, ScheduleResponsibility: blank, Canvas: blank, Docs: () => React.createElement('div', null, 'Docs fixture')});
  });
  await page.addScriptTag({content: sources.at(-1)});
  if (extra.desktopAccess?.admitted === false) return;
  await page.getByRole('navigation', {name: 'Main navigation'}).waitFor();
}

test('SETTINGSMATCH gate: a pending or signed-out desktop account shows only sign-in, never the shell', async () => {
  const browser = await chromium.launch({headless: true, executablePath: executable()});
  try {
    for (const state of ['pending', 'signed_out']) {
      const page = await browser.newPage({viewport: {width: 1366, height: 900}}), errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await mount(page, {name: '', email: '', signedIn: false, checking: false}, {desktopAccess: {admitted: false, state, subject: null, email: null, ready: false}});
      await page.getByRole('button', {name: 'Sign in with your browser', exact: true}).waitFor();
      assert.equal(await page.getByRole('navigation', {name: 'Main navigation'}).count(), 0, state + ' shows no shell');
      assert.equal(await page.locator('[data-screen^="settings/"]').count(), 0, state + ' shows no Settings');
      assert.deepEqual(errors, []);
      await page.close();
    }
  } finally { await browser.close(); }
});

test('SETTINGSMATCH: Account sheet matches the board at 900-1920 and the composer chip stays one line', async () => {
  const browser = await chromium.launch({headless: true, executablePath: executable()});
  try {
    for (const [profile, account] of [[{name: 'Account', email: EMAIL, signedIn: false, checking: false}, 'Local session'],
                                       [{name: 'Fixture Person', email: EMAIL, signedIn: true, checking: false}, 'Signed in as ' + EMAIL]]) {
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
        const accountCard = page.locator('[data-design-section="Account"]');
        const state = accountCard.locator('.sheet-account-state');
        assert.equal(await state.textContent(), account);
        if (profile.signedIn) assert.equal(await state.getAttribute('title'), EMAIL);
        assert.equal(await state.evaluate(el => window.getComputedStyle(el).textOverflow), 'ellipsis');
        assert.equal(await accountCard.getByRole('textbox', {name:'Email',exact:true}).inputValue(), EMAIL);
        assert.equal(await accountCard.getByRole('textbox', {name:'Name',exact:true}).inputValue(), profile.name);
        for (const id of ['account','name','email']) {
          assert.ok((await accountCard.locator('[data-row="'+id+'"] .sheet-property-copy small').innerText()).trim());
        }
        // Photo is built (founder 2026-11-26): the picture or initials with Change, never its data text and never Coming soon.
        const photo = accountCard.locator('[data-row=photo] [data-design="settings.photo"]');
        await photo.getByRole('button', {name: 'Change', exact: true}).waitFor();
        assert.equal(await accountCard.locator('[data-row=photo] [data-soon]').count(), 0);
        assert.ok(!(await photo.innerText()).includes('data:image'));
        // 7. A subtitle under the heading.
        assert.ok((await page.locator('.sheet-page-heading p').innerText()).trim().length > 0);
        // 8. The header shows at most one short phrase on Settings.
        const status = (await page.locator('.header-status').innerText()).replace(/\s+/g, ' ').trim();
        assert.ok(!status.includes('·') && status.length <= 24, 'header status: ' + status);
        assert.equal(await page.locator('.sheet-page-heading h2').evaluate(el=>window.getComputedStyle(el).fontSize),'20px');
        assert.equal(await accountCard.getByRole('heading',{name:'Privacy',exact:true}).count(),0);
        await page.getByRole('navigation',{name:'Settings categories'}).getByRole('button',{name:'This PC',exact:true}).click();
        const files = page.locator('[data-design-section="Workspaces and files"]');
        const folder = files.locator('[data-row=sessions] button').first();
        assert.equal(await folder.innerText(),'…\\ArchHub\\Sessions');
        assert.equal(await folder.getAttribute('title'),SESSIONS);
        for (const id of ['ws','sessions']) assert.ok((await files.locator('[data-row="'+id+'"] .sheet-property-copy small').innerText()).trim());
        await page.locator('[data-design-section="Privacy and keys"]').getByRole('button',{name:'Manage protected connections'}).waitFor();
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
      // The desktop account is admitted for these signed-in surface cases (the gate case covers pending/signed out).
      const data = url === '/api/universal/canvas' ? {root: 'canvas', nodes: [], wires: [], authorization: {principal: 'local-process'}}
        : url === '/api/universal/desktop-access' ? {admitted: true, state: 'admitted', subject: 'fixture-account', email: null}
        : url === '/api/commands' ? studioRegistry() : {ok: true};
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
    const account = page.locator('[data-row=account]');
    assert.equal(await account.locator('.sheet-account-state').innerText(),'Checking…');
    await account.getByText('Local session',{exact:true}).waitFor({timeout:12000});
    await account.getByRole('button',{name:'Sign in with Google'}).click();
    await page.getByRole('heading', {name: 'Sign in'}).first().waitFor();
    await page.getByRole('button', {name: 'Close dialog', exact: true}).click();
    // 3 + 4. Models: no empty section heading, no constant value, one label per switch.
    await page.getByRole('navigation', {name: 'Settings categories'}).getByRole('button', {name: 'Agents', exact: true}).click();
    await page.locator('select[aria-label="Default model"]').waitFor();
    assert.equal(await page.getByRole('heading', {name: 'Follow through', exact: true}).count(), 0);
    assert.equal(await page.getByRole('heading', {name: 'Knowledge', exact: true}).count(), 0);
    assert.equal(await page.getByText('Not reported', {exact: true}).count(), 0);
    const free = page.locator('[data-row=preferFree]');
    assert.equal(await free.getByText(/^(On|Off)$/).count(), 0, 'no duplicate On/Off label beside the switch');
    assert.equal(await free.getByRole('switch').getAttribute('aria-checked'), 'true');
    assert.equal(await page.locator('select[aria-label="Default model"]').inputValue(), 'free');
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
      // The desktop account is admitted for these signed-in surface cases (the gate case covers pending/signed out).
      const data = url === '/api/universal/canvas' ? {root: 'canvas', nodes: [], wires: [], authorization: {principal: 'local-process'}}
        : url === '/api/universal/desktop-access' ? {admitted: true, state: 'admitted', subject: 'fixture-account', email: null}
        : url === '/api/commands' ? studioRegistry() : {ok: true};
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

test('SETTINGSMATCH name: the Name row shows the real profile name or asks for one, never a placeholder word', async () => {
  // The cloud session names the admitted desktop subject; another account's name is never shown.
  for (const [account, expected] of [[{signed_in: false}, ''], [{signed_in: true, user_id: 'fixture-account', email: 'person@example.test', display_name: 'Fixture Person'}, 'Fixture Person'], [{signed_in: true, user_id: 'fixture-account', email: 'person@example.test'}, ''], [{signed_in: true, user_id: 'another-account', display_name: 'Someone Else'}, '']]) {
    const window = {ARCHHUB_AUTHORITY: {}, structuredClone: globalThis.structuredClone, ARCHHUB_BOOT: {home_load_ms: 60000, token: 'lease', csrf: 'csrf'},
      Uint8Array: globalThis.Uint8Array, dispatchEvent() {}, addEventListener() {}, AH: {inkSoft: '#888'}, crypto: require('node:crypto')};
    window.ArchHubStudioAuthority = {create: ({get}) => { let snapshot = null; return {load: async () => { snapshot = {canvas: await get('/api/universal/canvas')}; return snapshot.canvas; }, getSnapshot: () => snapshot, clear: () => { snapshot = null; }, adopt: async canvas => { snapshot = {canvas}; return canvas; }, transact: async action => { const canvas = await action(); snapshot = {canvas}; return canvas; }}; }};
    const context = {window, setTimeout, clearTimeout, document: {hidden: true, addEventListener() {}}, CustomEvent: class {}, sessionStorage: {getItem() { return null; }},
      URLSearchParams, TextEncoder: globalThis.TextEncoder, AbortSignal: globalThis.AbortSignal, console,
      fetch: async url => ({ok: true, status: 200, json: async () => url === '/api/universal/canvas' ? {root: 'canvas', nodes: [], wires: [], authorization: {principal: 'local-process'}} : url === '/api/universal/cloud-session' ? {...account}
        : url === '/api/universal/desktop-access' ? {admitted: true, state: 'admitted', subject: 'fixture-account', email: null} : url === '/api/commands' ? studioRegistry()
        : {ok: true, result: {profile: {}, officeInvitations: [], controlErrors: {}}}})};
    vm.runInNewContext(fs.readFileSync(path.join(studio, 'api.js'), 'utf8'), context);
    await window.ArchHubAPI.ready;
    await window.ArchHubAPI.syncAccount();
    assert.equal(window.ArchHubAPI.getSnapshot().profile.name, expected, JSON.stringify(account));
  }
  const browser = await chromium.launch({headless: true, executablePath: executable()});
  try {
    for (const [name, shown, initial] of [['', 'Add your name', 'P'], ['Fixture Person', 'Fixture Person', 'FP']]) {
      const page = await browser.newPage({viewport: {width: 1009, height: 940}});
      await mount(page, {name, email: 'person@example.test', signedIn: true, checking: false});
      const nav = page.getByRole('navigation', {name: 'Main navigation'});
      assert.equal((await nav.getByRole('button', {name: 'Your account', exact: true}).innerText()).trim(), initial);
      await nav.getByRole('button', {name: 'Settings', exact: true}).click();
      await page.locator('[data-screen="settings/Account"] .sheet-columns:not([hidden])').waitFor();
      const input=page.getByRole('textbox',{name:'Name',exact:true});
      assert.equal((await input.inputValue()) || (await input.getAttribute('placeholder')),shown);
      await page.close();
    }
  } finally { await browser.close(); }
});

test('SETTINGSMATCH second review: value boxes open, Retry stays visible, no empty sections, empty fallback reads None', async () => {
  const browser = await chromium.launch({headless: true, executablePath: executable()});
  try {
    // Viewing account identity never signs anyone out. Only its explicit action may do so.
    for (const signedIn of [true,false]) {
      const page = await browser.newPage({viewport: {width: 1440, height: 900}});
      await mount(page, {name: 'Fixture Person', email: EMAIL, signedIn, checking: false});
      await page.evaluate(() => { window.ArchHubAPI.signIn = async () => { window.signedOut = true; }; });
      await page.getByRole('navigation', {name: 'Main navigation'}).getByRole('button', {name: 'Settings', exact: true}).click();
      await page.locator('[data-screen="settings/Account"] .sheet-columns:not([hidden])').waitFor();
      const account=page.locator('[data-row=account]');
      await account.locator('.sheet-account-state').click();
      assert.equal(await page.evaluate(()=>window.signedOut===true),false);
      if(signedIn){
        await account.getByRole('button',{name:'Sign out',exact:true}).click();
        await page.waitForFunction(()=>window.signedOut===true);
      } else {
        await account.getByRole('button',{name:'Sign in with Google',exact:true}).click();
        await page.getByRole('heading',{name:'Sign in',exact:true}).first().waitFor();
        assert.equal(await page.evaluate(()=>window.signedOut===true),false);
      }
      await page.close();
    }
    // 2. A 200-character Workshop error keeps Retry in view.
    const error = 'Workshop settings could not be read because '.padEnd(200, 'x');
    let page = await browser.newPage({viewport: {width: 1009, height: 940}});
    await mount(page, {name: 'Fixture Person', email: EMAIL, signedIn: true, checking: false}, {agentError: error});
    await page.getByRole('navigation', {name: 'Main navigation'}).getByRole('button', {name: 'Settings', exact: true}).click();
    const retry = page.getByRole('button', {name: 'Retry Workshop connection', exact: true});
    await retry.waitFor();
    const box = await retry.boundingBox(), header = await page.locator('.app-header').boundingBox();
    assert.ok(box && box.width > 10 && box.x >= header.x && box.x + box.width <= header.x + header.width, JSON.stringify({box, header}));
    assert.equal(await page.locator('.header-error-text').getAttribute('title'), error);
    // 3 + 4. Changed only on Appearance with nothing changed: no bare headings, one line instead.
    await page.getByRole('navigation', {name: 'Settings categories'}).getByRole('button', {name: 'This PC', exact: true}).click();
    await page.getByRole('button', {name: /^Changed(?: \d+)?$/}).click();
    await page.getByText('No settings differ from their defaults.', {exact: true}).waitFor();
    assert.equal(await page.getByRole('heading', {name: 'Interface', exact: true}).count(), 0);
    assert.equal(await page.getByRole('heading', {name: 'Canvas', exact: true}).count(), 0);
    await page.getByRole('navigation', {name: 'Settings categories'}).getByRole('button', {name: 'Agents', exact: true}).click();
    const fallback = page.locator('[data-row=fallback] .sheet-property-control');
    await fallback.waitFor();
    assert.equal((await fallback.innerText()).trim(), 'None');
    await page.close();
  } finally { await browser.close(); }
});
