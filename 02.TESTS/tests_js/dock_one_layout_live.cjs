// The dock layout is the user's ONE setting: compiled Studio on a seeded isolated Workshop, real pointer input.
// He sets a layout once; three other sessions, Home and back, and a reload all show the same layout, byte for byte.
// Driven by 02.TESTS/tests/test_dock_live.py.
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
    const ws = page.locator('[data-dock-workspace]');
    const settle = () => page.waitForTimeout(450);  // the dock's own 240 ms easing, then the owner write
    // What he sees: which panels sit where, which tab is open, what is folded, and both dock widths.
    const seen = () => ws.evaluate(root => JSON.stringify(['left', 'right'].map(side => {
      const dock = root.querySelector('.dock.' + side);
      return [dock.classList.contains('col'), [...dock.querySelectorAll('.dslot')].map(slot => [...slot.querySelectorAll('.dtab')].map(tab => tab.dataset.tab + (tab.classList.contains('on') ? '*' : '')).join('|') + (slot.classList.contains('c') ? ' (collapsed)' : '')),
        root.style.getPropertyValue(side === 'left' ? '--lw' : '--rw')];
    })));
    // What the owner holds: the one record, as the Studio read it from the Settings owner.
    const held = () => page.evaluate(() => JSON.stringify(window.ArchHubAPI.getSnapshot().dockLayout.layout));
    const openCanvas = async title => {
      await ws.first().waitFor({state: 'attached'});
      if (await page.locator('[data-home-map]').count()) {
        // Home is the map of the work: a double-click on the session's card opens its Canvas.
        const card = page.locator('[data-home-map] .react-flow__node').filter({hasText: title}).first();
        await card.waitFor();
        await card.locator('.home-card-head').dblclick();
      }
      await page.locator('.dx-home-root[data-screen="task-file"] [data-dock-workspace]').waitFor();
      await ws.locator('[data-dock-workshop]').waitFor({state: 'attached'});
      await settle();
    };
    const switchTo = async title => {
      const tab = page.getByRole('tab', {name: title, exact: true});
      if (await tab.count()) await tab.click();
      else {
        await page.locator('[data-design="tab.add"]').click();
        await page.getByRole('menu', {name: 'Open tasks', exact: true}).getByRole('button', {name: title, exact: true}).click();
      }
      await page.getByRole('tab', {name: title, exact: true, selected: true}).waitFor();
      await settle();
    };
    const dragTab = async (id, target) => {
      const from = await ws.locator('.dtab[data-tab="' + id + '"]').boundingBox();
      const x0 = from.x + from.width / 2, y0 = from.y + from.height / 2, [x1, y1] = await target();
      await pointer('mouseMoved', x0, y0);
      await pointer('mousePressed', x0, y0, true);
      for (let step = 1; step <= 12; step++) await pointer('mouseMoved', x0 + (x1 - x0) * step / 12, y0 + (y1 - y0) * step / 12, true);
      await page.waitForTimeout(200);
      await pointer('mouseReleased', x1, y1);
      await settle();
    };
    const upperHalf = slot => async () => {
      const box = await ws.locator('.dslot[data-slot="' + slot + '"]').boundingBox(), head = await ws.locator('.dslot[data-slot="' + slot + '"] .dtabs').boundingBox();
      return [box.x + box.width / 2, head.y + head.height + (box.y + box.height / 2 - head.y - head.height) / 2];
    };

    await page.goto(input.url);
    await openCanvas('Drawing set review');
    // He sets his layout once: Map above the Inspector, Map folded to its header, the left dock folded to icons.
    await dragTab('map', upperHalf('right:0'));
    await page.getByRole('button', {name: 'Fold Map', exact: true}).click();
    await settle();
    await page.getByRole('button', {name: 'Fold the left dock to icons', exact: true}).click();
    await settle();
    const layout = await seen(), record = await held();
    assert.ok(layout.includes('map* (collapsed)') && layout.startsWith('[[true'), 'his layout is set: ' + layout);
    assert.notEqual(record, 'null', 'the owner holds his layout');
    const same = async where => {
      // After a reload the owner's record arrives with the first Settings read; the dock shows it from then on.
      await page.waitForFunction(() => window.ArchHubAPI.getSnapshot().dockLayout);
      for (let tries = 0; tries < 30 && await seen() !== layout; tries++) await page.waitForTimeout(100);
      assert.equal(await seen(), layout, where + ': the layout on screen is what he set');
      assert.equal(await held(), record, where + ': the owner record is byte-identical');
    };

    // Selecting a node never changes the layout (the Inspector does not open by itself).
    await page.locator('[data-graph-node] .node-header').first().click();
    await settle();
    await same('after selecting a node');
    // Below 1280 px the right dock is shown folded; that fold is never saved, and above 1280 the layout is back as he set it.
    await page.setViewportSize({width: 1009, height: 900});
    await settle();
    assert.equal(await ws.locator('.dock.right').evaluate(dock => dock.classList.contains('col')), true, 'narrow: the right dock shows folded');
    assert.equal(await held(), record, 'narrow: the owner record is unchanged');
    await page.setViewportSize({width: 1440, height: 900});
    await settle();
    await same('back above 1280');

    for (const title of ['Export issue package', 'Sheet index check', 'Model view audit']) { await switchTo(title); await same('after opening ' + title); }
    await switchTo('Drawing set review');
    await same('back on the first session');
    // Home shows the same layout, and coming back from Home keeps it.
    await page.getByRole('navigation').getByRole('button', {name: 'Home', exact: true}).first().click();
    await page.locator('.dx-home-root[data-screen="home"] [data-dock-workspace]').waitFor();
    await settle();
    await same('on Home');
    await openCanvas('Drawing set review');
    await same('after Home and back');
    // A restart of the screen reads the same record, and no frame shows any other layout first (no default flash).
    const shape = () => ws.evaluate(root => JSON.stringify(['left', 'right'].map(side => {
      const dock = root.querySelector('.dock.' + side);
      return [dock.classList.contains('col'), [...dock.querySelectorAll('.dslot')].map(slot => [...slot.querySelectorAll('.dtab')].map(tab => tab.dataset.tab + (tab.classList.contains('on') ? '*' : '')).join('|') + (slot.classList.contains('c') ? ' (collapsed)' : ''))];
    })));
    const his = await shape();
    await page.addInitScript(() => {
      window.__dockFrames = [];
      new window.MutationObserver(() => {
        const root = document.querySelector('[data-dock-workspace]');
        if (!root) return;
        const frame = JSON.stringify(['left', 'right'].map(side => {
          const dock = root.querySelector('.dock.' + side);
          return dock ? [dock.classList.contains('col'), [...dock.querySelectorAll('.dslot')].map(slot => [...slot.querySelectorAll('.dtab')].map(tab => tab.dataset.tab + (tab.classList.contains('on') ? '*' : '')).join('|') + (slot.classList.contains('c') ? ' (collapsed)' : ''))] : null;
        }));
        if (window.__dockFrames.at(-1) !== frame) window.__dockFrames.push(frame);
      }).observe(document, {subtree: true, childList: true, attributes: true});
    });
    await page.reload();
    await openCanvas('Drawing set review');
    await same('after a reload');
    const frames = await page.evaluate(() => window.__dockFrames);
    assert.ok(frames.length > 0, 'the dock was drawn after the reload');
    assert.deepEqual([...new Set(frames)], [his], 'every frame after the reload shows his layout, never a default one first');
    await switchTo('Sheet index check');
    await same('after a reload, on another session');
    assert.deepEqual(errors, []);
    console.log('LAYOUT=' + record);
    console.log('PASS dock_one_layout_live: one layout across four sessions, Home and back, and a reload');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
