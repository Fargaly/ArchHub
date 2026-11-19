// R28 rendered: the Session card's panels and the Inspector's Session group in the compiled Studio, with real clicks.
// Each async panel shows waiting, error -> Retry, empty and loaded; edits on the card reach the open file.
// Prints one SESSIONPROPS line; the Python test asserts it.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');

async function main() {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const newest = pattern => fs.readdirSync(input.browserCache).filter(name => pattern.test(name)).sort((a, b) => Number(b.split('-').at(-1)) - Number(a.split('-').at(-1)))[0];
  const full = newest(/^chromium-\d+$/), shell = newest(/^chromium_headless_shell-\d+$/);
  const executablePath = full ? path.join(input.browserCache, full, 'chrome-win64/chrome.exe') : path.join(input.browserCache, shell, 'chrome-headless-shell-win64/chrome-headless-shell.exe');
  const browser = await chromium.launch({headless: true, executablePath});
  const out = {permissions: [], session: [], edits: {}, errors: []};
  try {
    const context = await browser.newContext({viewport: {width: 1680, height: 1000}});
    await context.addCookies([{name: 'archhub_studio', value: input.cookie, url: input.url}]);
    context.setDefaultTimeout(15000);
    // The test decides how the next owner read answers: 'fail', 'slow' (held 900 ms), 'empty' or 'pass'.
    const mode = {permissions: 'pass', session: 'pass'};
    await context.route('**/api/universal/settings-action', async route => {
      if (route.request().postDataJSON()?.function !== 'readPermissions') return route.continue();
      const how = mode.permissions; mode.permissions = 'pass';
      if (how === 'fail') return route.fulfill({status: 500, contentType: 'application/json', body: JSON.stringify({ok: false, error: 'Permissions could not be read.'})});
      if (how === 'slow') await new Promise(done => setTimeout(done, 900));
      if (how === 'empty') return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true, result: {runMode: 'Ask first', runModes: [], tools: {}}})});
      return route.continue();
    });
    await context.route('**/api/session-model', async route => {
      if (route.request().postDataJSON()?.action !== 'get') return route.continue();
      const how = mode.session; mode.session = 'pass';
      if (how === 'fail') return route.fulfill({status: 500, contentType: 'application/json', body: JSON.stringify({ok: false, error: 'The session could not be read.'})});
      if (how === 'slow') await new Promise(done => setTimeout(done, 900));
      if (how === 'empty') return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true, session: null})});
      return route.continue();
    });
    const page = await context.newPage();
    page.on('pageerror', error => out.errors.push(error.message));
    await page.goto(input.url, {waitUntil: 'domcontentloaded'});
    await page.waitForFunction(() => window.ArchHubAPI && !document.getElementById('studio-boot') && document.querySelector('[data-home-ready]'), null, {timeout: 60000});
    // The task's own canvas, as he opens it from Home.
    const openCanvas = async () => { const open = page.getByRole('button', {name: 'Open its Canvas', exact: true}); await open.waitFor({timeout: 60000}); await open.click(); };
    await openCanvas();
    const card = page.locator('.react-flow__node[data-id="start"] [data-design="session.node"]');
    await card.waitFor({timeout: 60000});  // a cold first open on a busy machine
    const panel = name => card.locator('[data-design="session.panel.' + name + '"]');
    const seen = async (list, locator, label) => { await locator.waitFor(); list.push(label); };

    // Session card > Parameters > Permissions: error -> Retry -> waiting -> loaded, then empty on the next open.
    mode.permissions = 'fail';
    await panel('parameters').click();
    await seen(out.permissions, card.getByRole('alert').filter({hasText: 'Permissions could not be read.'}), 'error');
    mode.permissions = 'slow';
    await card.getByRole('button', {name: 'Retry permissions'}).click();
    await seen(out.permissions, card.getByRole('status').filter({hasText: 'Reading permissions'}), 'waiting');
    await seen(out.permissions, card.getByRole('combobox', {name: 'Permissions'}), 'loaded');
    await panel('parameters').click();   // fold
    mode.permissions = 'empty';
    await panel('parameters').click();   // open again: a new read
    await seen(out.permissions, card.getByText('No run modes. Settings › Permissions sets them.'), 'empty');
    await panel('parameters').click();
    await panel('parameters').click();   // loaded again for the edits below
    await card.getByRole('combobox', {name: 'Permissions'}).waitFor();

    // Real edits on the card. Permissions is the Settings owner (read back from it); the others are the session node's
    // own values and reach the file.
    await card.getByRole('combobox', {name: 'Permissions'}).selectOption('Accept edits');
    await page.waitForFunction(async () => (await window.ArchHubAPI.readPermissions()).runMode === 'Accept edits');
    out.permissionOwner = (await page.evaluate(() => window.ArchHubAPI.readPermissions())).runMode;
    await card.getByRole('group', {name: /run_budget$/}).getByRole('button', {name: '1 minute', exact: true}).click();  // 4 choices: the choice buttons
    await panel('tools').click();
    await card.getByRole('checkbox', {name: 'Revit · the agent may use it'}).click();  // controlled: it unticks once the file has the value
    await panel('context').click();
    const brief = card.locator('label.v48-session-param', {hasText: 'Brief'}).locator('input, textarea').first();
    await brief.fill('Issue for tender');
    await brief.press('Tab');
    const values = () => page.evaluate(() => { const n = window.ArchHubAPI.getSessionDocument().nodes.find(row => row.id === 'start'); return {run_budget: n.params.run_budget, brief: n.params.brief, tools_off: n.params.tools_off, defs: (n.paramDefs || []).length}; });
    await page.waitForFunction(() => { const n = window.ArchHubAPI.getSessionDocument().nodes.find(row => row.id === 'start'); return n?.params.run_budget === '1 minute' && n?.params.brief === 'Issue for tender' && (n?.params.tools_off || []).includes('revit'); });
    out.edits = await values();
    out.sockets = await card.locator('[data-design^="session.socket."]').evaluateAll(rows => rows.map(row => row.getAttribute('data-design')));
    // Saved, reloaded and reopened from disk: the values are still there.
    await page.evaluate(file => window.ArchHubAPI.saveSession(file), input.file);
    await page.reload({waitUntil: 'domcontentloaded'});
    await page.waitForFunction(() => window.ArchHubAPI && !document.getElementById('studio-boot') && document.querySelector('[data-home-ready]'), null, {timeout: 60000});
    await openCanvas();
    await card.waitFor({timeout: 60000});  // a cold first open on a busy machine
    out.reopened = await values();

    // TYPEDRECORD (R35): a record parameter on the session is edited field by field in the same widget, a nested
    // field too, on the Session card and in the Inspector; after save and reopen the values hold and the fields it
    // cannot edit (null, a mixed list) are byte-for-byte what they were.
    const record = {sheets: 12, revision: 'P01', issued: false, frame: {depth: 0.1, material: 'steel'}, note: null, mixed: [1, 'a']};
    const disk = JSON.parse(fs.readFileSync(input.file, 'utf8'));
    const start = disk.nodes.find(row => row.id === 'start');
    start.params.drawing_set = record;
    start.paramDefs = [...(start.paramDefs || []), {id: 'drawing_set', name: 'Drawing set', type: 'object', group: 'Context'}];
    fs.writeFileSync(input.file, JSON.stringify(disk, null, 2));
    const reopen = async () => {
      await page.reload({waitUntil: 'domcontentloaded'});
      await page.waitForFunction(() => window.ArchHubAPI && !document.getElementById('studio-boot') && document.querySelector('[data-home-ready]'), null, {timeout: 60000});
      await openCanvas();
      await card.waitFor({timeout: 60000});
    };
    const stored = () => page.evaluate(() => window.ArchHubAPI.getSessionDocument().nodes.find(row => row.id === 'start').params.drawing_set);
    await reopen();
    await panel('context').click();
    const onCard = card.locator('label.v48-session-param', {hasText: 'Drawing set'});
    await onCard.locator('summary').first().click();
    await onCard.getByRole('spinbutton', {name: /drawing_set sheets$/}).fill('14');
    await onCard.locator('[data-object-field="frame"] summary').first().click();
    await onCard.getByRole('spinbutton', {name: /drawing_set frame depth$/}).fill('0.12');
    await page.waitForFunction(() => { const v = window.ArchHubAPI.getSessionDocument().nodes.find(row => row.id === 'start').params.drawing_set; return v?.sheets === 14 && v?.frame?.depth === 0.12; });
    out.recordCard = await stored();
    // The Inspector's Properties for the same node edits the same value with the same widget.
    await page.locator('.react-flow__node[data-id="start"] .node-header, .react-flow__node[data-id="start"] [data-design="session.node"]').first().click();
    const inspector = page.locator('[data-node-inspector="start"]').first();
    await inspector.waitFor({timeout: 20000});
    const inInspector = inspector.locator('label', {hasText: /Drawing set|drawing set/}).first();
    await inInspector.locator('summary').first().click();
    await inInspector.getByRole('textbox', {name: /drawing_set revision$/}).fill('P02');
    await page.waitForFunction(() => window.ArchHubAPI.getSessionDocument().nodes.find(row => row.id === 'start').params.drawing_set?.revision === 'P02');
    await page.evaluate(file => window.ArchHubAPI.saveSession(file), input.file);
    await reopen();
    out.recordReopened = await stored();
    out.recordOnDisk = JSON.parse(fs.readFileSync(input.file, 'utf8')).nodes.find(row => row.id === 'start').params.drawing_set;
    out.recordExpected = {...record, sheets: 14, revision: 'P02', frame: {depth: 0.12, material: 'steel'}};
    assert.deepEqual(out.recordReopened, out.recordExpected);
    assert.deepEqual(out.recordOnDisk, out.recordExpected);

    // Inspector > This task > Session: error -> Retry -> waiting -> loaded; empty on a later read.
    const fold = page.getByRole('button', {name: 'Open Inspector', exact: true}).first();
    if (await fold.isVisible()) await fold.click();
    mode.session = 'fail';
    await page.locator('[data-design="inspector.task"]').first().click();
    const group = page.locator('section.v48-session-inspector');
    await page.evaluate(() => window.ArchHubAPI.setNodeParam('start', 'reply_in', 'Both'));  // a new revision: a new read
    await seen(out.session, group.getByRole('alert').filter({hasText: 'The session could not be read.'}), 'error');
    mode.session = 'slow';
    await group.getByRole('button', {name: 'Retry session'}).click();
    await seen(out.session, group.getByRole('status').filter({hasText: 'Reading this session'}), 'waiting');
    await seen(out.session, group.getByRole('combobox', {name: 'Done when'}), 'loaded');
    out.doneState = await group.locator('[data-design="inspector.session.donestate"]').textContent();
    mode.session = 'empty';
    await page.evaluate(() => window.ArchHubAPI.setNodeParam('start', 'reply_in', 'Arabic'));  // a new revision: a new read
    await seen(out.session, group.getByText('This file has no session record yet.'), 'empty');
    assert.deepEqual(out.errors, []);
  } catch (error) {
    out.errors.push(error.stack || String(error));
    out.view = await browser.contexts()[0]?.pages()[0]?.evaluate(() => ({nodes: [...document.querySelectorAll('.react-flow__node')].map(n => n.dataset.id), session: !!document.querySelector('[data-design="session.node"]'), file: window.ArchHubAPI?.getSessionPath?.(), docNodes: window.ArchHubAPI?.getSessionDocument?.()?.nodes?.map(n => n.id), text: document.body.innerText.slice(0, 300)})).catch(e => String(e));
  } finally {
    await browser.close();
  }
  console.log('SESSIONPROPS ' + JSON.stringify(out));
  process.exit(out.errors.length ? 1 : 0);
}
main();
