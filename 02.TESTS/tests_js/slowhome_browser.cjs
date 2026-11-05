// Real headless paints and hydrated layouts against the isolated NoGraphServer.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {chromium} = require('playwright');

(async () => {
  // Match the existing rail doors court's installed-cache discovery under an isolated profile.
  const cache = process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(os.userInfo().homedir, 'AppData/Local/ms-playwright');
  const shell = fs.existsSync(cache) && fs.readdirSync(cache).filter(name => /^chromium_headless_shell-\d+$/.test(name)).sort((a, b) => Number(b.split('-').at(-1)) - Number(a.split('-').at(-1)))[0];
  const executablePath = process.env.CHROME_PATH || (process.platform === 'win32' && shell ? path.join(cache, shell, 'chrome-headless-shell-win64/chrome-headless-shell.exe') : undefined);
  const browser = await chromium.launch({headless:true, executablePath});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const origin = new URL(process.env.SLOWHOME_URL).origin;
    await page.route('**/*', route => new URL(route.request().url()).origin === origin
      ? route.continue() : route.abort('internetdisconnected'));
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      window.slowhomeLoading = () => [...document.querySelectorAll('[role="status"], [data-home-loading], #studio-boot')]
        .filter(element => element.getClientRects().length && /loading|reading|opening|discovering|starting|restoring/i.test(element.textContent+' '+element.getAttribute('aria-label')))
        .map(element => element.textContent || element.getAttribute('aria-label'));
    });
    await page.goto(process.env.SLOWHOME_URL, {waitUntil:'domcontentloaded'});
    await page.waitForFunction(() => window.ArchHubAPI && !document.getElementById('studio-boot')
      && document.querySelector('[data-home-ready]') && window.slowhomeLoading().length === 0, null, {timeout:15000})
      .catch(async error => {
        console.log(JSON.stringify({errors, page:await page.locator('body').innerText(),
          loading:await page.evaluate(() => window.slowhomeLoading())}));
        throw error;
      });
    const home = await page.evaluate(() => ({
      first_paint_ms:window.performance.getEntriesByName('first-paint')[0]?.startTime,
      hydrated_ms:window.performance.now(), loading:window.slowhomeLoading(),
    }));
    assert.ok(home.first_paint_ms > 0, 'browser reports a real first paint');
    assert.ok(home.hydrated_ms >= home.first_paint_ms);
    console.log(JSON.stringify({surface:'Home', ...home}));
    console.log(JSON.stringify(await page.evaluate(() => ({resources:window.performance.getEntriesByType('resource')
      .sort((a,b)=>b.duration-a.duration).slice(0,8).map(row=>({path:new URL(row.name).pathname,ms:row.duration}))}))));
    const started = await page.evaluate(() => window.performance.now());
    await page.getByRole('button', {name:'Settings', exact:true}).first().click();
    await page.locator('[data-settings-full]').waitFor();
    const firstRender = await page.evaluate(start => new Promise(resolve => window.requestAnimationFrame(() =>
      window.requestAnimationFrame(() => resolve(window.performance.now()-start)))), started);
    await page.waitForFunction(() => {
      const settings = document.querySelector('[data-settings-full]');
      return settings && /Settings loaded\.|No connected programs or agent sessions reported\./.test(settings.textContent)
        && window.slowhomeLoading().length === 0;
    }, null, {timeout:15000});
    const settings = await page.evaluate(start => ({hydrated_ms:window.performance.now()-start,
      loading:window.slowhomeLoading()}), started);
    console.log(JSON.stringify({surface:'Settings', first_render_ms:firstRender, ...settings}));
    await page.getByLabel('Settings categories').getByRole('button', {name:'Account', exact:true}).click();
    await page.getByText('Sessions folder', {exact:true}).waitFor();
    assert.ok(await page.getByText(await page.evaluate(() => window.ArchHubAPI.getSnapshot().sessionsFolder), {exact:true}).isVisible());
    assert.deepEqual(await page.locator('[role="alert"]:visible').allTextContents(), []);
    assert.deepEqual(errors, []);
    assert.ok(home.hydrated_ms < 6000, 'Home clears loading before the reported 6 s stall');
    assert.ok(settings.hydrated_ms < 6000, 'Settings clears loading before the reported 6 s stall');
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode=1;});
