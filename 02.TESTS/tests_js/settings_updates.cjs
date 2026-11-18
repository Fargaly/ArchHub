// Settings -> System -> Updates in the compiled Studio at 1009 and 1440: the update card (current build, state and
// Check for updates) shows instead of the empty Advanced section, and the click reaches /api/universal/application-update.
// Without input.stub the isolated server has no update lifecycle, so the refusal must show; with it, the stub answers.
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
    for (const width of [1009, 1440]) {
      const at = ' at ' + width;
      const context = await browser.newContext({viewport: {width, height: 900}});
      await context.addCookies([{name: 'archhub_studio', value: input.cookie, url: input.url}]);
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => { errors.push(error.message); console.error('PAGEERROR ' + error.message); });
      await page.goto(input.url);
      await page.locator('[data-home-page]').waitFor({state: 'attached'});
      await page.locator('[aria-label="Settings"]').first().click();
      await page.locator('.sheet-tabs').getByRole('button', {name: 'System', exact: true}).click();
      await page.locator('.sheet-tools').getByRole('button', {name: 'Updates', exact: true}).click();
      const check = page.getByRole('button', {name: 'Check for updates', exact: true});
      await check.waitFor();
      assert.equal(await page.getByText('No raw parameters for this section.').count(), 0, 'Updates does not open the empty Advanced section' + at);
      assert.equal(await page.locator('.sheet-tools').count(), 0, 'Updates shows the update card, not the System tool list' + at);
      assert.equal(await page.locator('.sheet-columns h2').filter({hasText: 'ArchHub'}).count(), 1, 'the one update card' + at);
      const build = (await page.locator('.sheet-columns h2', {hasText: 'ArchHub'}).locator('xpath=following-sibling::p').innerText()).trim();
      assert.ok(build.length > 0, 'the card names the current build' + at);
      const card = await page.locator('.sheet-columns h2', {hasText: 'ArchHub'}).evaluate(h => { const c = h.closest('.sheet-canvas-defaults'), r = c.getBoundingClientRect();
        return {right: r.right, overflow: [...c.querySelectorAll('button')].filter(b => b.getBoundingClientRect().right > r.right + 1).map(b => b.textContent)}; });
      assert.deepEqual(card.overflow, [], 'every card button stays inside the card' + at);
      const posted = page.waitForRequest(request => request.url().endsWith('/api/universal/application-update') && request.method() === 'POST');
      const answered = page.waitForResponse(response => response.url().endsWith('/api/universal/application-update') && response.request().method() === 'POST');
      await check.click();
      assert.deepEqual(JSON.parse((await posted).postData()), {action: 'check'}, 'the click posts check to the update route' + at);
      const response = await answered;
      if (input.stub) {
        assert.equal(response.status(), 200, 'the update route answered' + at);
        await page.getByText(/Stub feed: up to date/).first().waitFor();
      } else {
        assert.notEqual(response.status(), 200, 'the isolated server refuses without an update lifecycle' + at);
        await page.getByText(/Application updates require the installed desktop lifecycle/).first().waitFor();
        await check.waitFor();
        assert.equal(await check.isEnabled(), true, 'the failure leaves Check for updates available to retry' + at);
      }
      assert.deepEqual(errors, [], 'no page errors' + at);
      if (input.shots) await page.screenshot({path: path.join(input.shots, 'settings-updates-' + (input.stub ? 'stub' : 'refused') + '-' + width + '.png')});
      await context.close();
    }
    console.log('OK settings updates at 1009, 1440' + (input.stub ? ' (stub owner)' : ' (refusal shown)'));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
