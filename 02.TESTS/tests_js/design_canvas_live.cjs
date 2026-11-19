// DESIGNCANVAS: the Canvas rows of the approved design in the compiled Studio on a seeded isolated Workshop.
// Real input, real owners, at 1009, 1440 and 1920 px. Driven by 02.TESTS/tests/test_design_canvas.py.
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
    const shot = async name => { if (input.shots) await page.screenshot({path: path.join(input.shots, name + '.png')}); };
    const ws = page.locator('[data-dock-workspace]'), canvas = page.getByLabel('Workflow canvas', {exact: true});
    const snapshot = read => page.evaluate(read);
    const steps = ['list', 'slice', 'count'];

    await page.goto(input.url);
    // Home is the map of the work: a double-click on the session's card opens its canvas.
    await page.locator('[data-design="home.card"]').filter({hasText: 'Drawing set review'}).dblclick();
    await ws.waitFor();
    await canvas.locator('.react-flow__node[data-id="slice"]').waitFor({state: 'attached'});

    for (const width of [1009, 1440, 1920]) {
      await page.setViewportSize({width, height: 900});
      await page.getByRole('button', {name: 'Fit', exact: true}).click();
      const fits = await snapshot(() => ({page: document.documentElement.scrollWidth <= window.innerWidth, canvas: document.querySelector('[aria-label="Workflow canvas"]').getBoundingClientRect().width}));
      assert.ok(fits.page && fits.canvas >= 240, width + ': no sideways scroll and a usable canvas ' + JSON.stringify(fits));

      // Row 3: Flow view. One socket in and one out per step, one wire per pair; the tab holds it, the file does not change.
      // What Flow could change: nodes, wires, groups. Fit writes the viewport into the file on its own, so that is left out.
      const graph = () => snapshot(() => { const doc = window.ArchHubAPI.getSessionDocument(); return JSON.stringify([doc.nodes, doc.wires, doc.groups]); });
      const before = await graph();
      const flow = page.locator('[data-design="canvas.flow"]');
      assert.equal(await flow.getAttribute('aria-pressed'), 'false', width + ': Flow starts off');
      const sockets = await canvas.locator('[data-port-key]').count();
      await flow.click();
      await canvas.locator('[data-flow-socket="flow:in"]').first().waitFor({state: 'attached'});
      assert.equal(await flow.getAttribute('aria-pressed'), 'true');
      for (const id of steps) assert.equal(await canvas.locator('[data-graph-node="' + id + '"] [data-flow-socket]').count(), 2, width + ': ' + id + ' shows one socket in and one out');
      assert.equal(await canvas.locator('[data-fixed] [data-flow-socket]').count(), 0, 'pinned nodes keep no flow socket');
      assert.equal(await canvas.locator('[data-graph-node="slice"] [data-port-key]').evaluateAll(list => list.filter(node => node.getBoundingClientRect().width > 0).length), 0, 'the step shows only its header');
      await page.waitForFunction(() => document.querySelectorAll('[aria-label="Workflow canvas"] .react-flow__edge').length === 2);
      const after = await graph(), at = [...after].findIndex((ch, i) => ch !== before[i]);
      assert.equal(after, before, 'the Flow view changes no node, wire or group in the file; first change: ' + after.slice(Math.max(0, at - 120), at + 120));
      if (width === 1440) await shot('design-canvas-flow-1440');
      await flow.click();
      await page.waitForFunction(count => document.querySelectorAll('[aria-label="Workflow canvas"] [data-port-key]').length === count && !document.querySelector('[data-flow-socket]'), sockets);
      // Off is written to the owner before the next width: the open tab holds no Flow view.
      for (let tries = 0; (await snapshot(() => window.ArchHubAPI.readCanvasTabs())).canvasTabs.tabs.some(tab => tab.flow); tries++) assert.ok(tries < 200, width + ': the owner keeps the Flow view off');
    }

    assert.deepEqual(errors, []);
    console.log('PASS design_canvas_live at 1009, 1440 and 1920');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
