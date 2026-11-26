// Settings › Account, Connections and Projects in the compiled Studio on an isolated real server, opened with real clicks
// at 944x968 and 1920x1032: no row is held as "Coming soon", and every row shows a real control from its owner.
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

(async () => {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const newest = pattern => fs.readdirSync(input.browserCache).filter(name => pattern.test(name)).sort((a, b) => Number(b.split('-').at(-1)) - Number(a.split('-').at(-1)))[0];
  const full = newest(/^chromium-\d+$/), shell = newest(/^chromium_headless_shell-\d+$/);
  const executablePath = full ? path.join(input.browserCache, full, 'chrome-win64/chrome.exe') : path.join(input.browserCache, shell, 'chrome-headless-shell-win64/chrome-headless-shell.exe');
  const browser = await chromium.launch({headless: true, executablePath});
  const report = {};
  try {
    for (const [width, height] of [[944, 968], [1920, 1032]]) {
      const context = await browser.newContext({viewport: {width, height}});
      await context.addCookies([{name: 'archhub_studio', value: input.cookie, url: input.url}]);
      const page = await context.newPage();
      await page.route('**/api/universal/desktop-access', route => route.fulfill({json: {ok: true, admitted: true, state: 'admitted', subject: 'settings-test', email: 'settings@example.test'}}));
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(input.url);
      await page.locator('.app-rail button[aria-label="Settings"]').click();
      const nav = page.getByRole('navigation', {name: 'Settings categories'});
      for (const area of ['Account', 'Connections', 'Projects']) {
        await nav.getByRole('button', {name: area, exact: true}).click();
        const sheet = page.locator('.sheet-columns:not([hidden])');
        await sheet.locator('section[data-design-section]').first().waitFor();
        await page.waitForTimeout(1500);
        const held = await sheet.evaluate(root => [...root.querySelectorAll('[data-soon]')].map(node => {
          const row = node.closest('[data-row]');
          return (node.closest('section[data-design-section]')?.dataset.designSection || '?') + ' › ' + (row?.dataset.row || node.getAttribute('aria-label'));
        }));
        report[area + '@' + width] = held;
        // Real input on owner rows: the Python side reads settings/settings.json after the run.
        if (width === 1920 && area === 'Connections') {
          const sound = sheet.locator('[data-row="sound"]').getByRole('switch');
          await page.waitForFunction(() => { const s = window.ArchHubAPI.getSnapshot(); return s.settingsDestination && !s.settingsScopePending; });
          await page.waitForTimeout(1000);
          const wrote = page.waitForResponse(response => (response.request().postData() || '').includes('Connections.Sound'), {timeout: 150000});
          await sound.click();
          console.log('SOUND write', (await wrote).status());
        }
        if (width === 1920 && area === 'Projects') {
          const east = sheet.locator('[data-row="surveyE"] input');
          const wrote = page.waitForResponse(response => (response.request().postData() || '').includes('Survey point east'), {timeout: 150000});
          // Edits wait while Settings re-reads its destination (the row is disabled meanwhile, as for a person).
          await page.waitForFunction(() => { const s = window.ArchHubAPI.getSnapshot(); return s.settingsDestination && !s.settingsScopePending; });
          await page.waitForTimeout(1000);
          await east.click();
          await east.fill('1250.5');
          await east.press('Enter');
          console.log('SURVEY write', (await wrote).status());
        }
        if (input.shots) {
          fs.mkdirSync(input.shots, {recursive: true});
          await page.screenshot({path: path.join(input.shots, `settings-${area.toLowerCase()}-${width}x${height}.png`)});
          // The sheet scrolls inside the window: the lower cards are a second shot.
          await sheet.locator('section[data-design-section]').last().scrollIntoViewIfNeeded();
          await page.screenshot({path: path.join(input.shots, `settings-${area.toLowerCase()}-${width}x${height}-end.png`)});
        }
      }
      report['errors@' + width] = errors;
      await context.close();
    }
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify(report, null, 1));
  const held = Object.entries(report).filter(([key, rows]) => !key.startsWith('errors') && rows.length);
  const errors = Object.entries(report).filter(([key, rows]) => key.startsWith('errors') && rows.length);
  process.exit(input.probe ? 0 : held.length || errors.length ? 1 : 0);
})().catch(error => { console.error(error); process.exit(2); });
