// Design v63: on the Canvas the Library sits in its dock by default, and one click always shows or hides the whole Library.
// Compiled Studio on a fresh isolated profile at 1009, 1440 and 1920. Driven by 02.TESTS/tests/test_library_reach.py.
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
    const shelf = page.locator('[data-screen="library"]');
    const button = page.locator('[data-design="canvas.library"]');
    // The whole Library: its search box is on screen and wider than a rail.
    const whole = () => page.evaluate(() => { const box = document.querySelector('[data-screen="library"] [data-design="library.search"]'); if (!box) return false; const r = box.getBoundingClientRect(); return r.width > 120 && r.height > 0; });

    await page.goto(input.url);
    await page.getByRole('navigation').getByRole('button', {name: 'Canvas', exact: true}).first().click();
    await button.waitFor();
    for (const width of [1009, 1440, 1920]) {
      await page.setViewportSize({width, height: 900});
      await page.waitForTimeout(400);  // the panel group settles after a resize
      if (width === 1009) assert.equal(await button.getAttribute('aria-pressed'), 'true', 'a fresh profile sees the Library');
      if (await button.getAttribute('aria-pressed') === 'false') await button.click();
      await shelf.first().waitFor();
      await page.waitForTimeout(400);
      assert.equal(await whole(), true, width + ': the whole Library shows, not a rail');
      assert.equal(await page.getByRole('button', {name: 'Open Library', exact: true}).count(), 0, width + ': no rail to click first');
      // One click hides it, one click shows it whole again.
      await button.click();
      await shelf.first().waitFor({state: 'detached'});
      await button.click();
      await shelf.first().waitFor();
      await page.waitForTimeout(400);
      assert.equal(await whole(), true, width + ': one click shows the whole Library again');
      if (input.shots) await page.screenshot({path: path.join(input.shots, 'library-reach-' + width + '.png')});
    }
    // A selected node at 1440: the Inspector folds to its rail on a narrow pane (the canvas keeps its room); the Library does not.
    await page.setViewportSize({width: 1440, height: 900});
    await page.evaluate(() => window.ArchHubAPI.addNode('math_expression', {x: 300, y: 200}));
    await page.locator('[data-graph-node] .node-header').first().click();
    await page.waitForTimeout(400);
    assert.equal(await whole(), true, 'with a node selected the whole Library still shows');
    assert.equal(await page.getByRole('button', {name: 'Open Library', exact: true}).count(), 0);
    assert.deepEqual(errors, []);
    console.log('PASS library_reach_live: Library open by default and one click at 1009, 1440 and 1920');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
