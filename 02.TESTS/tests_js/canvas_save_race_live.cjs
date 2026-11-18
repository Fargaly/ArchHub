// A canvas edit made while an autosave is in flight: the next autosave builds on the revision the owner returned,
// so one client never sees "This workflow changed elsewhere". Compiled Studio on a real server (it checks base_revision).
// Driven by 02.TESTS/tests/test_canvas_save_race.py.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');

(async () => {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const newest = pattern => fs.readdirSync(input.browserCache).filter(name => pattern.test(name)).sort((a, b) => Number(b.split('-').at(-1)) - Number(a.split('-').at(-1)))[0];
  const full = newest(/^chromium-\d+$/), shell = newest(/^chromium_headless_shell-\d+$/);
  const executablePath = full ? path.join(input.browserCache, full, 'chrome-win64/chrome.exe') : path.join(input.browserCache, shell, 'chrome-headless-shell-win64/chrome-headless-shell.exe');
  const browser = await chromium.launch({headless: true, executablePath});
  try {
    const context = await browser.newContext({viewport: {width: 1440, height: 900}});
    await context.addCookies([{name: 'archhub_studio', value: input.cookie, url: input.url}]);
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => { errors.push(error.message); console.error('PAGEERROR ' + error.message); });
    await page.goto(input.url);
    // The Studio is ready once its tasks and the Library's node catalogue have loaded.
    await page.waitForFunction(() => window.ArchHubAPI?.getSnapshot && Array.isArray(window.ArchHubAPI.getSnapshot().tasks) && Array.isArray(window.ArchHubAPI.getSnapshot().libraryPorts));
    await page.evaluate(task => window.ArchHubAPI.openTaskGraph(task), input.task);
    await page.waitForFunction(task => window.ArchHubAPI.getSessionDocument()?.properties?.taskContext?.task === task, input.task);

    // Hold the first autosave's answer at the network until an edit has been made locally.
    const saves = [];
    let release, held = new Promise(resolve => { release = resolve; });
    await page.route('**/api/session-files', async route => {
      const body = JSON.parse(route.request().postData() || '{}');
      if (body.action !== 'autosave') return route.continue();
      saves.push(body.base_revision);
      if (saves.length === 1) {
        const answer = await route.fetch();   // the owner has written it; only its answer waits
        await held;
        return route.fulfill({response: answer});
      }
      return route.continue();
    });
    const first = await page.evaluate(() => window.ArchHubAPI.addNode('math_expression', {x: 300, y: 200}).then(node => node.id));
    for (let tries = 0; tries < 50 && saves.length < 1; tries++) await page.waitForTimeout(100);
    assert.equal(saves.length, 1, 'the first autosave left');
    // An edit while that save is in flight.
    await page.evaluate(id => window.ArchHubAPI.moveNodes({[id]: {x: 520, y: 260}}), first);
    release();
    // The next autosave carries the edit and must be accepted by the owner.
    for (let tries = 0; tries < 80 && saves.length < 2; tries++) await page.waitForTimeout(100);
    assert.ok(saves.length >= 2, 'the edit made during the first save was saved too');
    await page.waitForFunction(() => !window.ArchHubAPI.getSnapshot().sessionDirty, null, {timeout: 10000});
    const state = await page.evaluate(() => ({conflict: window.ArchHubAPI.getSnapshot().canvasSaveConflict || '', saves: null}));
    assert.equal(state.conflict, '', 'no "changed elsewhere" for a single client');
    assert.ok(saves[1] > saves[0], 'the second save builds on the revision the first one returned: ' + JSON.stringify(saves));
    const node = await page.evaluate(id => window.ArchHubAPI.getSessionDocument().nodes.find(row => row.id === id)?.position, first);
    assert.deepEqual(node, {x: 520, y: 260});
    assert.deepEqual(errors, []);
    console.log('SAVED_NODE=' + first);
    console.log('PASS canvas_save_race_live: an edit during an in-flight autosave is saved with no conflict');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
