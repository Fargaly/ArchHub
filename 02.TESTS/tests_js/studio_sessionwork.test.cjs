// F337 SESSION-IS-THE-WORK: Home's cards are pieces of work (the map of the work, design v61), rendered from the real compiled Studio.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {execFileSync} = require('node:child_process');
const {chromium} = require('playwright');
const studio = path.resolve(__dirname, '../../01.APP/nodelang/studio');
process.stdout.write(execFileSync(process.execPath, ['--max-old-space-size=512', path.resolve(__dirname, '../../03.TOOLS/packaging/compile_studio.cjs')], {windowsHide: true}));
const compiled = name => fs.readFileSync(path.join(studio, 'compiled', name.replace(/\//g, '-').replace(/\.jsx$/, '.js')), 'utf8');
const sources = ['tokens.jsx', 'ds/index.jsx', 'icons.jsx', 'ui.jsx', 'answer-widgets.jsx', 'dock.jsx', 'ds_home2.jsx', 'ds_workshop3.jsx', 'ds_screens.jsx', 'ds_library.jsx', 'surfaces.jsx', 'app.jsx'].map(compiled);

test('SESSIONWORK: one card per piece of work, lead and member avatars, interrupted with Continue', async () => {
  const cache = process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(os.userInfo().homedir, 'AppData/Local/ms-playwright');
  const shell = fs.existsSync(cache) && fs.readdirSync(cache).filter(name => /^chromium_headless_shell-\d+$/.test(name)).sort((a, b) => Number(b.split('-').at(-1)) - Number(a.split('-').at(-1)))[0];
  const full = fs.readdirSync(cache).filter(name => /^chromium-\d+$/.test(name)).sort((a, b) => Number(b.split('-').at(-1)) - Number(a.split('-').at(-1)))[0];
  const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || (process.platform === 'win32' && (shell || full) ? path.join(cache, shell || full, shell ? 'chrome-headless-shell-win64/chrome-headless-shell.exe' : 'chrome-win64/chrome.exe') : undefined);
  const browser = await chromium.launch({headless: true, executablePath});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 900}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => route.fulfill({contentType: 'text/html', body: '<div id="root"></div>'}));
    await page.goto('http://sessionwork.test');
    await page.addStyleTag({path: path.join(studio, 'style.css')});
    await page.addStyleTag({content: 'html,body,#root{height:100%;margin:0}'});
    for (const name of ['react.js', 'react-dom.js']) await page.addScriptTag({path: path.join(studio, 'vendor', name)});
    await page.addScriptTag({content: require('./studio_xyflow.cjs').script()});
    await page.addScriptTag({path: path.join(studio, 'compiled/react-resizable-panels.js')});
    await page.evaluate(() => { window.fetch = () => new Promise(() => {}); });
    await page.addScriptTag({path: path.join(studio, 'compiled/api.js')});
    await page.evaluate(() => {
      const s = window.structuredClone(window.ArchHubAPI.getSnapshot());
      const now = new Date().toISOString();
      s.tasks = [
        {id: 'session-review', title: 'Drawing set review', status: 'WIP', sessionPath: 'review.archhub', messages: [], updated_at: now,
         members: [{name: 'Drawing coordinator', live: true}, {name: 'Model checker', live: true}, {name: 'Code checker', live: false}]},
        {id: 'session-library', title: 'Details library', status: 'PLANNED', outcome: 'interrupted', rowState: 'interrupted', sessionPath: 'library.archhub',
         messages: [], updated_at: now, members: [{name: 'Details assistant', live: false}]},
        {id: 'declared-oldrun', title: 'Old agent run', status: 'PLANNED', outcome: 'interrupted', rowState: 'interrupted', sessionPath: 'old.archhub',
         messages: [], updated_at: now, members: []}];
      // Two live agents on one piece of work: still one row, the second is an avatar on it.
      s.agentGraph = {...(s.agentGraph || {}), sessions: [
        {id: 'live-a', name: 'Drawing coordinator', status: 'working', task: 'session-review'},
        {id: 'live-b', name: 'Site reviewer', status: 'working', task: 'session-review'}]};
      s.focusedTask = '';
      window.selected = [];
      window.ArchHubAPI = {...window.ArchHubAPI, getSnapshot: () => s, subscribe: () => () => {},
        executeAction: (id, callback) => { if (id === 'ui.select') return callback(); throw Error('Unexpected action: ' + id); },
        setActiveSurface: () => {}, supportsAction: () => true,
        readCanvasTabs: async () => ({canvasTabs: {tabs: [], active: '', split: '', collapsed: false}}),
        setCanvasTabs: async () => ({ok: true}),
        readSessionListFilters: async () => ({sessionListFilters: {home: 'all'}}),
        setSessionListFilter: async () => ({ok: true}),
        readHomeLayout: async () => ({homeLayout: {width: 300, collapsed: false, resume: '', order: [], hidden: []},
          homeMap: {group: ['Project'], order: ['Needs you first'], card: ['Steps and state'], density: ['Comfortable'], done: ['Show'], filter: ['All']}}),
        setHomeLayout: async layout => { if (layout && layout.resume) window.selected.push(layout.resume); return {ok: true}; },
        refreshAgentSurface: async () => null, openTaskGraph: async () => ({ok: true})};
    });
    for (let i = 0; i < sources.length - 1; i++) await page.addScriptTag({content: sources[i]});
    await page.evaluate(() => {
      const blank = () => null;
      Object.assign(window.UI, {BaboomSprite: blank, ScheduleResponsibility: blank, Docs: blank, Settings: blank,
        Canvas: () => React.createElement('div', null, 'Task canvas'), GraphProperties: () => null});
    });
    await page.addScriptTag({content: sources.at(-1)});
    const card = title => page.locator('[data-design="home.card"]').filter({has: page.locator('.home-card-head b', {hasText: title})});
    await card('Drawing set review').waitFor();
    // One card for the piece of work: the lead is its agent, the others small avatars on the same card.
    assert.equal(await card('Drawing set review').count(), 1);
    assert.equal(await card('Drawing set review').locator('.home-card-head > div > small').textContent(), 'Drawing coordinator');
    const more = card('Drawing set review').locator('.home-card-members');
    assert.equal(await more.getAttribute('title'), 'Also on this work: Model checker, Code checker, Site reviewer');
    assert.equal(await more.locator(':scope > *').count(), 3);
    assert.equal(await card('Site reviewer').count(), 0, 'a second live agent on the work is no second card');
    assert.equal(await card('Drawing coordinator').count(), 0);
    // Interrupted work stays open with Continue; Continue selects it (the Home owner's record).
    const library = card('Details library');
    assert.equal(await library.count(), 1);
    assert.match(await library.locator('.home-card-need span').textContent(), /^Interrupted · waiting for an agent$/);
    await library.getByRole('button', {name: 'Continue', exact: true}).click();
    await page.waitForFunction(() => window.selected.includes('session-library'));
    // An old per-agent run offers no Continue.
    assert.equal(await card('Old agent run').getByRole('button', {name: 'Continue'}).count(), 0);
    assert.deepEqual(errors, []);
    console.log('PASS sessionwork Home cards: lead + members, interrupted Continue, no Continue on old runs');
    await page.close();
  } finally { await browser.close(); }
});
