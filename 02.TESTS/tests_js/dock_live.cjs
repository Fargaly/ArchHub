// The Canvas dock in the compiled Studio on a seeded isolated Workshop: real pointer input, real owners, no substitutions.
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
    // CDP input is confined to this headless page; it never uses the desktop pointer.
    const cdp = await context.newCDPSession(page);
    const pointer = (type, x, y, pressed = false) => cdp.send('Input.dispatchMouseEvent', {type, x, y, ...(type === 'mouseMoved' ? pressed ? {button: 'left', buttons: 1} : {} : {button: 'left', buttons: pressed ? 1 : 0, clickCount: 1})});
    const errors = [];
    page.on('pageerror', error => { errors.push(error.message); console.error('PAGEERROR ' + error.message); });
    const answers = [];
    page.on('request', request => { const body = request.postData() || ''; if (body.includes('"answerApproval"')) answers.push(JSON.parse(body).args); });
    const shot = async name => { if (input.shots) await page.screenshot({path: path.join(input.shots, name + '.png')}); };
    const ws = page.locator('[data-dock-workspace]');
    const slots = side => ws.locator('.dock.' + side + ' .dslot').evaluateAll(list => list.map(slot => [...slot.querySelectorAll('.dtab')].map(tab => tab.dataset.tab + (tab.classList.contains('on') ? '*' : '')).join('|') + (slot.classList.contains('c') ? ' (collapsed)' : '')));
    const folded = side => ws.locator('.dock.' + side).evaluate(dock => dock.classList.contains('col'));
    const settle = () => page.waitForTimeout(450);  // the dock's own 240 ms easing, then the owner write
    const openCanvas = async () => {
      await ws.first().waitFor({state: 'attached'});
      if (await page.locator('[data-home-map]').count()) {
        // Home is the map of the work at every width: a double-click on the session's card opens its Canvas.
        const card = page.locator('[data-home-map] .react-flow__node').filter({hasText: 'Drawing set review'}).first();
        await card.waitFor();
        await card.locator('.home-card-head').dblclick();
      }
      await page.locator('.dx-home-root[data-screen="task-file"] [data-dock-workspace]').waitFor();
      await page.getByLabel('Workflow canvas', {exact: true}).locator('.react-flow__node[data-id="slice"]').waitFor();
      await ws.locator('[data-dock-workshop]').waitFor({state: 'attached'});  // it may sit behind another tab of a kept layout
      await settle();
    };
    // Drag one dock tab to a point chosen inside the target, with intermediate moves like a hand.
    const dragTab = async (id, target, during) => {
      const from = await ws.locator('.dtab[data-tab="' + id + '"]').boundingBox();
      const x0 = from.x + from.width / 2, y0 = from.y + from.height / 2, [x1, y1] = await target();
      await pointer('mouseMoved', x0, y0);
      await pointer('mousePressed', x0, y0, true);
      for (let step = 1; step <= 12; step++) await pointer('mouseMoved', x0 + (x1 - x0) * step / 12, y0 + (y1 - y0) * step / 12, true);
      await page.waitForTimeout(200);
      if (during) await during();
      await pointer('mouseReleased', x1, y1);
      await settle();
    };
    const inSlot = (slot, place) => async () => {
      const box = await ws.locator('.dslot[data-slot="' + slot + '"]').boundingBox(), head = await ws.locator('.dslot[data-slot="' + slot + '"] .dtabs').boundingBox();
      return [box.x + box.width / 2, place === 'header' ? head.y + head.height / 2 : place === 'upper' ? head.y + head.height + (box.y + box.height / 2 - head.y - head.height) / 2 : box.y + box.height * .75];
    };

    await page.route('**/api/universal/desktop-access', route => route.fulfill({
      json: {ok: true, admitted: true, state: 'admitted', subject: 'dock-test', email: 'dock@example.test'}
    }));
    await page.goto(input.url);
    await openCanvas();
    for (const width of [1009, 1440]) {
      await page.setViewportSize({width, height: 900});
      await settle();
      // Default: Workshop over Library|Map on the left; the Inspector open on the right, folded to icons only on a narrow window.
      const narrow = width < 1280;
      assert.deepEqual(await slots('left'), ['workshop*', 'library*|map'], width + ': default left dock');
      assert.equal(await folded('right'), narrow, width + ': the right dock is folded only on a narrow window');
      assert.equal(await ws.locator('[data-ws-approval]').count(), 1, 'one waiting approval from the approval owner');
      const waitingCard = ws.locator('[data-ws-approval]');
      assert.equal(await waitingCard.locator('.wsch b').innerText(), 'Export issue package');
      await waitingCard.click({button:'right'});
      const cardMenu = page.getByRole('menu', {name:'Workshop menu'});
      await cardMenu.getByRole('menuitem', {name:'Show', exact:true}).waitFor();
      await cardMenu.getByRole('menuitem', {name:'Show', exact:true}).press('Escape');
      assert.equal(await ws.locator('[data-ws-failed]').count(), 1, 'one failed step from the task owner');
      assert.equal(await ws.locator('[data-ws-working]').count(), 1, 'one working task from the task owner');
      assert.match(await ws.locator('[data-ws-failed]').innerText(), /The sheet index file was not found/);
      const thread = ws.locator('[data-ws-thread]').filter({hasText: 'Sheet index check'});
      await thread.getByRole('button', {name: 'Raw log'}).click();
      const log = page.getByRole('dialog', {name: 'Raw log · Sheet index check'});
      assert.match(await log.innerText(), /Checker.*Checked the sheet list/s);
      await log.getByRole('button', {name: 'Close dialog'}).click();
      const fits = await page.evaluate(() => ({page: document.documentElement.scrollWidth <= window.innerWidth, canvas: document.querySelector('[aria-label="Workflow canvas"]').getBoundingClientRect().width}));
      assert.ok(fits.page && fits.canvas >= 240, width + ': no sideways scroll and a usable canvas: ' + JSON.stringify(fits));
      await shot('dock-default-' + width);

      // His example: Map above the Inspector, made by dragging the Map tab onto the Inspector's upper half.
      if (narrow) await page.getByRole('button', {name: 'Open Inspector', exact: true}).click();
      await settle();
      assert.deepEqual(await slots('right'), ['insp*']);
      await dragTab('map', inSlot('right:0', 'upper'), async () => {
        assert.equal(await ws.locator('.dzp').getAttribute('data-lab'), 'Stack above');
        await shot('dock-drop-preview-' + width);
      });
      assert.deepEqual(await slots('right'), ['map*', 'insp*'], width + ': Map stacked above Inspector');
      assert.deepEqual(await slots('left'), ['workshop*', 'library*']);
      assert.ok(await ws.locator('.dock.right .mms').isVisible(), 'the mini map draws the open canvas');
      await shot('dock-stack-map-above-inspector-' + width);

      // One tab move: Library joins the Workshop slot by a drop on its header.
      await dragTab('library', inSlot('left:0', 'header'), null);
      assert.deepEqual(await slots('left'), ['workshop|library*'], width + ': Library tabbed with Workshop');
      await shot('dock-tab-move-' + width);

      // One panel collapsed to its header.
      await page.getByRole('button', {name: 'Fold Map', exact: true}).click();
      await settle();
      assert.deepEqual(await slots('right'), ['map* (collapsed)', 'insp*']);
      await shot('dock-collapsed-' + width);

      // The layout is the owner's record: it is still there after a reload (the write is back in the owner before the reload).
      await page.waitForFunction(() => (window.ArchHubAPI.getSnapshot().dockLayout?.layout?.right?.st || []).some(slot => slot.p.includes('map') && slot.c));
      await page.reload();
      await openCanvas();
      await page.waitForFunction(() => window.ArchHubAPI.getSnapshot().dockLayout?.layout);  // the owner's record has arrived
      await settle();
      // Below 1280 the right dock shows folded again after a reload (display only); the layout under it is what he set.
      if (narrow) { assert.equal(await folded('right'), true); await page.getByRole('button', {name: 'Open Inspector', exact: true}).click(); await page.waitForFunction(() => document.querySelectorAll('[data-dock-workspace] .dock.right .dslot').length === 2); await settle(); }
      assert.deepEqual(await slots('right'), ['map* (collapsed)', 'insp*'], width + ': the layout survives a reload');
      assert.deepEqual(await slots('left'), ['workshop|library*']);
      await shot('dock-after-reload-' + width);

      // Reset brings the default back.
      await page.getByRole('button', {name: 'More canvas actions', exact: true}).first().click();
      await page.getByRole('menuitem', {name: 'Reset panel layout', exact: true}).click();
      await settle();
      assert.deepEqual(await slots('left'), ['workshop*', 'library*|map'], width + ': Reset restores the default');
      assert.equal(await folded('right'), narrow);
    }

    // The zoom control and the floating composer never overlap: both docks open, and the Inspector folded, at four widths.
    const rects = () => page.evaluate(() => {
      const box = el => { const r = el.getBoundingClientRect(); return {left: Math.round(r.left), right: Math.round(r.right), top: Math.round(r.top), bottom: Math.round(r.bottom)}; };
      return {zoom: box(document.querySelector('[data-design="canvas.stage"] .canvas-toolbar')), composer: box(document.querySelector('.v22g-composer-dock form'))};
    });
    for (const width of [1009, 1280, 1440, 1920]) {
      await page.setViewportSize({width, height: 900});
      await settle();
      for (const state of ['open', 'folded']) {
        if (state === 'open' && await folded('right')) await page.getByRole('button', {name: 'Open Inspector', exact: true}).click();
        if (state === 'folded' && !await folded('right')) await page.getByRole('button', {name: 'Fold the right dock to icons', exact: true}).click();
        await settle();
        assert.equal(await folded('right'), state === 'folded');
        const {zoom, composer} = await rects();
        console.log('ZOOM-COMPOSER ' + width + ' ' + state + ' zoom=' + JSON.stringify(zoom) + ' composer=' + JSON.stringify(composer));
        const apart = zoom.right <= composer.left || composer.right <= zoom.left || zoom.bottom <= composer.top || composer.bottom <= zoom.top;
        assert.ok(apart, width + ' ' + state + ': the composer covers the zoom control');
        if (width === 1009 && state === 'folded' || width === 1440 && state === 'open') await shot('dock-v2-' + width + '-' + state);
      }
    }
    await page.setViewportSize({width: 1440, height: 900});
    await page.getByRole('button', {name: 'More canvas actions', exact: true}).first().click();
    await page.getByRole('menuitem', {name: 'Reset panel layout', exact: true}).click();
    await settle();

    // Approve acts in place through the one approval route.
    const card = ws.locator('[data-ws-approval]');
    const approval = await card.getAttribute('data-ws-approval');
    await shot('dock-workshop-before-approve-1440');
    await card.getByRole('button', {name: 'Approve', exact: true}).evaluate(button => { button.click(); button.click(); });
    await page.waitForFunction(id => window.ArchHubAPI.getSnapshot().approvals.find(row => row.id === id)?.status === 'approved', approval);
    await ws.locator('[data-ws-approval]').waitFor({state: 'detached'});
    assert.equal(answers.filter(args => args[1] === approval).length, 1, 'a double click sends one decision');
    assert.ok((await ws.getByLabel('Waiting for you', {exact: true}).textContent()).includes('Nothing waits for you.'));
    await shot('dock-workshop-approved-1440');
    assert.deepEqual(errors, []);
    console.log('PASS dock_live: default, stack by drag, tab move, collapse, reload, reset at 1009 and 1440; Approve through answerApproval once');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
