// Driven by 02.TESTS/tests/test_boot_splash.py: the server holds the Library catalogue until this page prints
// "LIBRARY LOADING SHOWN". The splash must be gone before that, the Library says it is loading, then shows its rows.
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
    const errors = [], answered = [];
    page.on('pageerror', error => { errors.push(error.message); console.error('PAGEERROR ' + error.message); });
    page.on('response', response => { if (/\/api\/session-files$/.test(response.url()) && /"action":"catalogue"/.test(response.request().postData() || '')) answered.push(response.status()); });
    await page.goto(input.url);
    // The splash goes with sign-in, commands and the first file; the catalogue is still held by the server.
    await page.locator('#studio-boot').waitFor({state: 'detached'});
    assert.equal(answered.length, 0, 'the splash went before the catalogue answered');
    assert.equal(await page.evaluate(() => window.ArchHubAPI.getSnapshot().libraryStatus), 'waiting');
    // The Library says it is loading: no blank and no stand-in rows.
    await page.locator('[data-design="home1.open"]').click();
    const library = page.locator('aside.library-shelf');
    await library.locator('[data-library-loading]').waitFor();
    assert.equal(await library.locator('[data-library-category]').count(), 0, 'no categories or rows before the catalogue');
    if (input.shots) await page.screenshot({path: path.join(input.shots, 'boot-library-loading.png')});
    console.log('LIBRARY LOADING SHOWN');
    // Then the catalogue arrives and the Library shows its categories (folded by default; each holds its rows).
    await library.locator('[data-library-category]').first().waitFor({timeout: 150000});
    await library.locator('.shelf-category').first().click();
    await library.locator('[data-design="library.row"]').first().waitFor();
    assert.equal(await library.locator('[data-library-loading]').count(), 0);
    assert.ok(answered.length >= 1 && answered.every(status => status === 200), JSON.stringify(answered));
    assert.deepEqual(errors, [], 'no page errors');
    console.log('OK the splash never waits for the Library');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
