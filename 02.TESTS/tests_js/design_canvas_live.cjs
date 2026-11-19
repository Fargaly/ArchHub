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
      // Row 11: steps past the right edge are counted on the edge pill, in the singular for one.
      const more = page.locator('[data-design="canvas.more"]');
      if (await more.count()) assert.match(await more.innerText(), /^(1 more step|[2-9]\d* more steps) →$/);    }

    // Row 11: the running step shows its agent's presence chip, working.
    await page.setViewportSize({width: 1440, height: 900});
    const presence = canvas.locator('[data-design="canvas.presence"]'), follow = presence.locator('[data-design="canvas.follow"]');
    await presence.waitFor();
    assert.equal(await presence.getAttribute('data-state'), 'working');
    assert.equal(await presence.getAttribute('data-on'), 'slice');
    assert.match(await presence.innerText(), /Drawing coordinator\s*working/);
    // Follow centres the step in the canvas area no dock covers: under the 56 px zoom band, above the composer and zoom bar as measured.
    const centred = id => page.waitForFunction(id => {
      const pane = document.querySelector('[aria-label="Workflow canvas"]').getBoundingClientRect(), card = document.querySelector('[aria-label="Workflow canvas"] [data-graph-node="' + id + '"]').getBoundingClientRect();
      let x0 = pane.left, x1 = pane.right, y1 = pane.bottom; const y0 = pane.top + 56;
      for (const foot of [document.querySelector('[aria-label="Workflow canvas"] .canvas-toolbar'), document.querySelector('.v22g-composer-dock>form')]) { const b = foot?.getBoundingClientRect(); if (b?.width && b.top < pane.bottom && b.bottom > y0 && b.right > pane.left && b.left < pane.right) y1 = Math.min(y1, b.top); }
      for (const dock of document.querySelectorAll('.dockws > .dock')) { const b = dock.getBoundingClientRect(); if (!b.width || b.bottom < y0 || b.top > y1) continue; if (b.left <= x0 + 4 && b.right > x0) x0 = Math.max(x0, b.right); else if (b.right >= x1 - 4 && b.left < x1) x1 = Math.min(x1, b.left); }
      return Math.abs(card.left + card.width / 2 - (x0 + x1) / 2) < 4 && Math.abs(card.top + card.height / 2 - (y0 + y1) / 2) < 4;
    }, id);
    await page.getByRole('button', {name: 'Fit', exact: true}).click();
    await follow.click();
    assert.equal(await follow.getAttribute('aria-pressed'), 'true');
    await centred('slice');
    // A press on a node keeps Follow on; Esc with the focus in the composer stops it.
    await canvas.locator('[data-graph-node="count"] .node-header').first().click();
    assert.equal(await follow.getAttribute('aria-pressed'), 'true', 'a press on a node keeps Follow on');
    await page.locator('textarea:visible').first().press('Escape');
    await page.waitForFunction(() => document.querySelector('[data-design="canvas.follow"]').getAttribute('aria-pressed') === 'false');
    // A wheel on the canvas stops it too.
    await follow.click();
    await page.waitForFunction(() => document.querySelector('[data-design="canvas.follow"]').getAttribute('aria-pressed') === 'true');
    await canvas.dispatchEvent('wheel', {deltaY: 120});  // a wheel on the canvas element, not page-wide input
    await page.waitForFunction(() => document.querySelector('[data-design="canvas.follow"]').getAttribute('aria-pressed') === 'false');
    await shot('design-canvas-presence-1440');
    // In a collapsed group the chip sits on the group.
    const group = await snapshot(() => window.ArchHubAPI.groupNodes(['slice']).then(node => node.id));
    await page.waitForFunction(id => document.querySelector('[data-design="canvas.presence"]')?.dataset.on === id, group);
    await follow.click();
    await centred(group);
    await follow.click();

    // Row 11: the other session's step waits for approval: its chip says the agent needs you.
    await page.locator('.app-header .header-page').filter({hasText: 'Home'}).first().click();
    await page.locator('[data-design="home.card"]').filter({hasText: 'Model view audit'}).dblclick();
    await page.waitForFunction(() => document.querySelector('[data-design="canvas.presence"]')?.dataset.state === 'waiting');
    assert.match(await presence.innerText(), /Drawing coordinator\s*needs you/);
    assert.deepEqual(errors, []);
    console.log('PASS design_canvas_live at 1009, 1440 and 1920');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
