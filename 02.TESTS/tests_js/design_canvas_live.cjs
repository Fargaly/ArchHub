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

    // ZOOMKEEP. The free area: the canvas minus the docks, the 56 px zoom band and what floats at its foot (composer, zoom bar).
    const free = () => page.evaluate(() => {
      const pane = document.querySelector('[aria-label="Workflow canvas"]').getBoundingClientRect();
      let x0 = pane.left, x1 = pane.right, y1 = pane.bottom; const y0 = pane.top + 56;
      for (const foot of [document.querySelector('[aria-label="Workflow canvas"] .canvas-toolbar'), document.querySelector('.v22g-composer-dock>form')]) { const b = foot?.getBoundingClientRect(); if (b?.width && b.top < pane.bottom && b.bottom > y0 && b.right > pane.left && b.left < pane.right) y1 = Math.min(y1, b.top); }
      for (const dock of document.querySelectorAll('.dockws > .dock')) { const b = dock.getBoundingClientRect(); if (!b.width || b.bottom < y0 || b.top > y1) continue; if (b.left <= x0 + 4 && b.right > x0) x0 = Math.max(x0, b.right); else if (b.right >= x1 - 4 && b.left < x1) x1 = Math.min(x1, b.left); }
      const cards = [...document.querySelectorAll('[aria-label="Workflow canvas"] [data-graph-node]')].map(card => card.getBoundingClientRect());
      const zoom = new window.DOMMatrix(window.getComputedStyle(document.querySelector('[aria-label="Workflow canvas"] .react-flow__viewport')).transform).a;
      return {x0, x1, y0, y1, zoom, inside: cards.every(c => c.left >= x0 - 2 && c.right <= x1 + 2 && c.top >= y0 - 2 && c.bottom <= y1 + 2), left: Math.min(...cards.map(c => c.left))};
    });
    // A canvas he never viewed opens fitted into the free area (design openView), or at the session's left edge at reading size below 62%.
    await page.waitForFunction(() => document.querySelectorAll('[aria-label="Workflow canvas"] [data-graph-node]').length > 0);
    const opened = await free();
    assert.ok(opened.inside && opened.zoom >= .62 || opened.zoom >= .8 && Math.abs(opened.left - opened.x0 - 16) < 24, 'the canvas opens fitted to the session, or at its left edge at reading size: ' + JSON.stringify(opened));
    // The zoom bar is % / Fit / Flow (design): no − or +.
    assert.equal(await canvas.locator('.canvas-toolbar [aria-label="Zoom in"], .canvas-toolbar [aria-label="Zoom out"]').count(), 0);
    // His zoom stays: zoom in at a point, then 30 s of polls and autosave, and the zoom is the same.
    const viewBox = await canvas.boundingBox(), zoomInput = await context.newCDPSession(page);  // input on this headless page only
    for (let step = 0; step < 4; step++) await zoomInput.send('Input.dispatchMouseEvent', {type: 'mouseWheel', x: viewBox.x + viewBox.width / 2, y: viewBox.y + viewBox.height / 2, deltaX: 0, deltaY: -400});
    await page.waitForFunction(was => new window.DOMMatrix(window.getComputedStyle(document.querySelector('[aria-label="Workflow canvas"] .react-flow__viewport')).transform).a > was * 1.2, opened.zoom);
    const zoomed = (await free()).zoom;
    assert.ok(zoomed <= 2.0001, 'zoom stops at 200%: ' + zoomed);
    await page.waitForTimeout(30000);
    assert.equal((await free()).zoom, zoomed, 'after 30 s of polls and autosave his zoom is unchanged');

    // DESIGNROWS2 row 22: the open tab counts the held run that needs him.
    await page.locator('[data-design="tab.active"] [data-design="tab.needs"]').waitFor();
    assert.equal((await page.locator('[data-design="tab.active"] [data-design="tab.needs"]').innerText()).trim(), '1');
    // Row 5: the held step is answered inside the thread too; Ask why puts the question in the composer.
    await page.getByRole('button', {name: 'Thread', exact: true}).click();
    const inThread = page.locator('[data-design="thread.approval"][data-approval="app:ask:rows2-step"]');
    await inThread.waitFor();
    assert.match(await inThread.innerText(), /Needs your approval[\s\S]*Drawing coordinator asked · Count the sheets/i);  // the label is shown in capitals
    for (const name of ['Review on the node', 'Approve', 'Ask why', 'Reject']) assert.equal(await inThread.getByRole('button', {name, exact: true}).count(), 1, name);
    await inThread.getByRole('button', {name: 'Ask why', exact: true}).click();
    await page.waitForFunction(() => [...document.querySelectorAll('textarea')].some(area => /^Why do you need to run /.test(area.value)));
    await page.getByRole('button', {name: 'Close thread', exact: true}).click();
    // Row 4: the Workshop panel lists every task with messages, with its Raw log.
    const threads = page.locator('[data-dock-workshop] [aria-label="Threads"]');
    await threads.waitFor({state: 'attached'});
    const withMessages = await snapshot(() => window.ArchHubAPI.getSnapshot().tasks.filter(task => task.status !== 'ARCHIVED' && (window.UI.homeTaskMessages?.(task) || []).length).length);
    assert.ok(withMessages >= 1, 'the seeded thread line is in a task');
    assert.equal(await threads.locator('[data-ws-thread]').count(), Math.min(8, withMessages));
    assert.equal(await threads.locator('.wsraw').count(), Math.min(8, withMessages));
    const row = threads.locator('[data-ws-thread]').filter({hasText: 'Drawing set review'});
    assert.match(await row.innerText(), /Drawing coordinator: I checked the sheet list\.[\s\S]*\b1\b/);
    // Row 23: the More menu carries this task's actions; each acts, or is drawn inert as coming soon.
    await page.getByRole('button', {name: 'More canvas actions', exact: true}).click();
    const more = page.getByRole('menu', {name: 'Canvas actions', exact: true});
    for (const name of ['Rename…', 'Show on Home', 'Keep at the top of Home', 'Delete task…']) assert.equal(await more.getByRole('menuitem', {name, exact: true}).isEnabled(), true, name);
    for (const name of ['Connection checks', 'Test this workflow', 'Publish to Community', 'Keyboard shortcuts']) assert.equal(await more.locator('[data-soon][aria-label^="' + name + '."]').count(), 1, name + ' is coming soon');
    await more.getByRole('menuitem', {name: 'Keep at the top of Home', exact: true}).click();
    await page.waitForFunction(() => window.ArchHubAPI.getSnapshot().tasks.find(task => task.title === 'Drawing set review').homePinned === true);
    for (const width of [1009, 1440, 1920]) {
      await page.setViewportSize({width, height: 900});
      await page.getByRole('button', {name: 'Fit', exact: true}).click();
      // Fit uses only the free area: every card lies inside it, unless that needs less than the design's 35% floor.
      const fitted = await free();
      assert.ok(fitted.inside || Math.abs(fitted.zoom - .35) < .001, width + ': after Fit every card is inside the free area ' + JSON.stringify(fitted));
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
      if (await more.count()) assert.match(await more.innerText(), /^(1 more step|[2-9]\d* more steps) →$/);

      // Row 12: the tab strip and the layout preset.
      assert.equal(await page.locator('[data-design="tab.add"]').getAttribute('aria-label'), 'Open another task');
      const layoutButton = page.locator('[data-design="toolbar.layout"]');
      assert.equal(await layoutButton.getAttribute('aria-label'), 'Layout: Build');
      assert.equal(await layoutButton.getAttribute('aria-pressed'), 'true');
      // "Wall checker" works on "Model view audit" right now: the pill must show it.
      const pill = page.locator('[data-design="toolbar.agents.more"]');
      assert.equal(await pill.getAttribute('aria-label'), '1 more agent working', width + ': the pill names the agent working elsewhere');
      assert.equal(await pill.innerText(), '+1');
    }

    // Row 12: a row of the pill opens the task that agent works on; Home takes us back.
    await page.locator('[data-design="toolbar.agents.more"]').click();
    await page.getByRole('menu', {name: 'Agents working on other tasks', exact: true}).getByRole('menuitem', {name: 'Wall checker · working · Model view audit', exact: true}).click();
    await page.locator('.app-header .header-here').filter({hasText: 'Model view audit'}).waitFor();
    await page.locator('.app-header .header-page').filter({hasText: 'Home'}).first().click();
    await page.locator('[data-design="home.card"]').filter({hasText: 'Drawing set review'}).dblclick();
    await canvas.locator('.react-flow__node[data-id="slice"]').waitFor({state: 'attached'});
    // Row 12: moving a panel renames the layout; Layout: Build puts every panel back.
    const cdp = await context.newCDPSession(page);  // input confined to this headless page, never the desktop pointer
    const pointer = (type, x, y) => cdp.send('Input.dispatchMouseEvent', {type, x, y, button: 'left', buttons: type === 'mouseReleased' ? 0 : 1, clickCount: 1});
    const dockTabs = () => page.evaluate(() => [...document.querySelectorAll('.dockws > .dock .dslot')].map(slot => [...slot.querySelectorAll('.dtab')].map(tab => tab.dataset.tab).join('|')).join(' / '));
    const home = await dockTabs(), from = await ws.locator('.dtab[data-tab="library"]').boundingBox(), head = await ws.locator('.dslot[data-slot="left:0"] .dtabs').boundingBox();
    const [x0, y0, x1, y1] = [from.x + from.width / 2, from.y + from.height / 2, head.x + head.width / 2, head.y + head.height / 2];
    await pointer('mousePressed', x0, y0);
    for (let step = 1; step <= 12; step++) await pointer('mouseMoved', x0 + (x1 - x0) * step / 12, y0 + (y1 - y0) * step / 12);
    await pointer('mouseReleased', x1, y1);
    const layoutButton = page.locator('[data-design="toolbar.layout"]');
    await page.waitForFunction(() => document.querySelector('[data-design="toolbar.layout"]').getAttribute('aria-label') === 'Layout: Build (changed)');
    assert.notEqual(await dockTabs(), home, 'the Library moved');
    assert.equal(await layoutButton.getAttribute('aria-pressed'), 'false');
    await layoutButton.click();
    await page.waitForFunction(() => document.querySelector('[data-design="toolbar.layout"]').getAttribute('aria-label') === 'Layout: Build');
    assert.equal(await layoutButton.getAttribute('aria-pressed'), 'true');
    assert.equal(await dockTabs(), home, 'every panel is back where Build puts it');
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
    // PINSFOLD: folded, no wire of a fixed node is drawn; expanded, the three fixed-node wires into the Session card are drawn and attached.
    const fixedWires = await snapshot(() => { const d = window.ArchHubAPI.getSessionDocument(), fixed = new Set(d.nodes.filter(n => n.fixed && n.type !== 'thing.session').map(n => n.id)), session = d.nodes.find(n => n.type === 'thing.session').id; return d.wires.filter(w => fixed.has(w.from.node) && w.to.node === session).map(w => w.id); });
    assert.equal(fixedWires.length, 3, 'the agent, profile and thread each feed the Session in the file');
    const drawn = () => page.evaluate(ids => ids.map(id => { const path = document.querySelector('[aria-label="Workflow canvas"] .react-flow__edge[data-id="' + id + '"] path'); return path ? path.getAttribute('d') || '' : null; }), fixedWires);
    const broken = () => page.evaluate(() => [...document.querySelectorAll('[aria-label="Workflow canvas"] .react-flow__edge path')].filter(path => !path.getAttribute('d') || /NaN/.test(path.getAttribute('d'))).length);
    assert.deepEqual(await drawn(), [null, null, null], 'folded: the fixed-node wires are not drawn');
    assert.equal(await broken(), 0);
    const pins = page.locator('[data-design="session.pins"]');
    await pins.click();
    await page.waitForFunction(() => document.querySelectorAll('[aria-label="Workflow canvas"] [data-graph-node][data-fixed]').length === 4);
    await page.waitForFunction(ids => ids.every(id => /^M\s*-?\d/.test(document.querySelector('[aria-label="Workflow canvas"] .react-flow__edge[data-id="' + id + '"] path')?.getAttribute('d') || '')), fixedWires);
    // Each wire ends on the Session card: its last point lies on the card's edge box.
    const ends = await page.evaluate(ids => { const card = document.querySelector('[aria-label="Workflow canvas"] [data-graph-node="start"]').getBoundingClientRect(); return ids.map(id => { const path = document.querySelector('[aria-label="Workflow canvas"] .react-flow__edge[data-id="' + id + '"] path'), end = path.getPointAtLength(path.getTotalLength()), m = path.getScreenCTM(), x = m.a * end.x + m.c * end.y + m.e, y = m.b * end.x + m.d * end.y + m.f; return x >= card.left - 12 && x <= card.right + 12 && y >= card.top - 4 && y <= card.bottom + 4; }); }, fixedWires);
    assert.deepEqual(ends, [true, true, true], 'expanded: the three wires end on the Session card');
    assert.equal(await broken(), 0);
    await pins.click();
    await page.waitForFunction(() => document.querySelectorAll('[aria-label="Workflow canvas"] [data-graph-node][data-fixed]').length === 1);
    assert.deepEqual(await drawn(), [null, null, null]);
    // APPROVALCONTEXT: the Workshop's Waiting card says what will change and where, in plain words; Show opens the draft itself.
    const held = page.locator('[data-ws-approval="app:ask:canvas-test-draft"]');
    await held.waitFor();
    const said = await held.innerText();
    for (const words of ['Draft a reply', 'site@example.com', 'RE: Site report', 'Thanks, the north entrance is fixed.', 'Outlook asked', 'Reply to the site report'])
      assert.ok(said.includes(words), 'the card says ' + words + ': ' + said);
    assert.ok(!said.includes('never-shown'), 'no other argument of the held call is shown');
    await held.getByRole('button', {name: 'Show', exact: true}).click();
    await held.locator('[data-ws-draft-body]').waitFor();
    assert.equal((await held.locator('[data-ws-draft-body]').innerText()).trim(), ('Thanks, the north entrance is fixed. '.repeat(8)).trim());
    assert.ok(await page.locator('.settings-page, [data-screen="settings"]').count() === 0, 'Show never opens Settings');
    await held.getByRole('button', {name: 'Hide', exact: true}).click();
    // Key 2 on the hovered card rejects it (design); nothing is sent.
    await held.hover();
    await held.dispatchEvent('keydown', {key: '2', bubbles: true});
    await held.waitFor({state: 'detached'});
    // Show on a held step of ANOTHER session opens that session with the step centred in the free area, over its opening view.
    await page.locator('.app-header .header-page').filter({hasText: 'Home'}).first().click();
    await page.locator('[data-design="home.card"]').filter({hasText: 'Drawing set review'}).dblclick();
    // (slice sits in the group the presence check made; count is still drawn on its own)
    await page.locator('.app-header .header-here').filter({hasText: 'Drawing set review'}).waitFor();
    await canvas.locator('[data-graph-node="count"]').waitFor({state: 'attached'});
    const step = page.locator('[data-ws-approval="app:ask:canvas-test-step"]');
    await step.getByRole('button', {name: 'Show', exact: true}).click();
    await page.locator('.app-header .header-here').filter({hasText: 'Model view audit'}).waitFor();
    // The step is brought into the free area at its centre: across exactly, and down within the band the composer and zoom bar settle in.
    await page.waitForFunction(() => {
      const pane = document.querySelector('[aria-label="Workflow canvas"]').getBoundingClientRect(), card = document.querySelector('[aria-label="Workflow canvas"] [data-graph-node="count"]')?.getBoundingClientRect();
      if (!card) return false;
      let x0 = pane.left, x1 = pane.right, y1 = pane.bottom; const y0 = pane.top + 56;
      for (const foot of [document.querySelector('[aria-label="Workflow canvas"] .canvas-toolbar'), document.querySelector('.v22g-composer-dock>form')]) { const b = foot?.getBoundingClientRect(); if (b?.width && b.top < pane.bottom && b.bottom > y0 && b.right > pane.left && b.left < pane.right) y1 = Math.min(y1, b.top); }
      for (const dock of document.querySelectorAll('.dockws > .dock')) { const b = dock.getBoundingClientRect(); if (!b.width || b.bottom < y0 || b.top > y1) continue; if (b.left <= x0 + 4 && b.right > x0) x0 = Math.max(x0, b.right); else if (b.right >= x1 - 4 && b.left < x1) x1 = Math.min(x1, b.left); }
      return Math.abs(card.left + card.width / 2 - (x0 + x1) / 2) < 4 && Math.abs(card.top + card.height / 2 - (y0 + y1) / 2) < 60 && card.left >= x0 && card.right <= x1 && card.top >= y0 && card.bottom <= y1;
    });
    // Row 23: Delete task archives it after a confirm; the tab closes, the task leaves the list, its file stays (checked by the driver).
    const archived = await snapshot(() => window.ArchHubAPI.getSnapshot().tasks.find(task => task.title === 'Model view audit')?.id);
    if (!await page.locator('.app-header .header-here').filter({hasText: 'Model view audit'}).count()) {
      await page.locator('.app-header .header-page').filter({hasText: 'Home'}).first().click();
      await page.locator('[data-design="home.card"]').filter({hasText: 'Model view audit'}).dblclick();
      await page.locator('.app-header .header-here').filter({hasText: 'Model view audit'}).waitFor();
    }
    await page.getByRole('button', {name: 'More canvas actions', exact: true}).click();
    await page.getByRole('menu', {name: 'Canvas actions', exact: true}).getByRole('menuitem', {name: 'Delete task…', exact: true}).click();
    const ask = page.getByRole('alertdialog', {name: 'Delete task', exact: true});
    assert.match(await ask.innerText(), /archived[\s\S]*leaves the active list and Home[\s\S]*file stays on disk[\s\S]*Nothing is deleted/);
    await ask.getByRole('button', {name: 'Archive', exact: true}).click();
    // The Studio reads archived tasks too (listTasks with archived): the task is now marked ARCHIVED, off the active list and Home.
    await page.waitForFunction(id => window.ArchHubAPI.getSnapshot().tasks.find(task => task.id === id)?.status === 'ARCHIVED', archived);
    console.log('ARCHIVED=' + archived);
    assert.deepEqual(errors, []);
    console.log('PASS design_canvas_live at 1009, 1440 and 1920');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
