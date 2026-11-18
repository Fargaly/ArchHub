// Opening a saved workflow in the compiled Studio shows a tidy first view and leaves the file alone; his own Tidy up saves.
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
    const writes = [];
    page.on('request', request => { const body = request.postData() || ''; if (/"action":\s*"(autosave|save)"/.test(body)) writes.push(JSON.parse(body).action); });
    await page.goto(input.url);
    await page.locator('[data-design="home.card"]').filter({hasText: 'Drawing set review'}).first().click();
    await page.getByRole('button', {name: 'Open its Canvas', exact: true}).click();
    await page.getByLabel('Workflow canvas', {exact: true}).locator('.react-flow__node[data-id="slice"]').waitFor();
    const read = () => page.evaluate(() => ({
      shown: Object.fromEntries(window.ArchHubAPI.getSnapshot().graph.nodes.map(node => [node.id, [node.x, node.y]])),
      held: Object.fromEntries(window.ArchHubAPI.getSessionDocument().nodes.map(node => [node.id, [node.position.x, node.position.y]])),
      layout: window.ArchHubAPI.getSnapshot().graph.canvasLayout, dirty: window.ArchHubAPI.getSnapshot().sessionDirty}));
    await page.waitForFunction(() => window.ArchHubAPI.getSnapshot().graph.canvasLayout === 'v48');
    await page.waitForTimeout(2500);  // well past the autosave debounce
    const opened = await read();
    if (input.step === 'open') {
      assert.notDeepEqual(opened.shown.list, [800, 0], 'the first view shows the tidy layout');
      assert.deepEqual(opened.held.list, [800, 0], 'the open document keeps the saved position');
      assert.equal(opened.dirty, false, 'nothing is waiting to be saved');
      assert.deepEqual(writes, [], 'opening sends no save');
    } else {
      await page.getByRole('button', {name: 'Tidy up', exact: true}).click();
      await page.waitForFunction(() => window.ArchHubAPI.getSessionDocument().properties.canvasLayout === 'v48' && window.ArchHubAPI.getSnapshot().sessionDirty === false);
      const arranged = await read();
      assert.deepEqual(arranged.held.list, arranged.shown.list, 'his Tidy up is the document now');
      assert.ok(writes.length >= 1, 'his Tidy up is saved');
    }
    assert.deepEqual(errors, []);
    console.log('PASS open_never_writes ' + input.step);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
