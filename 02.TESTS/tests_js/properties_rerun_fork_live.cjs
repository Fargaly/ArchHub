// F10 rendered: Rerun from the node menu and from the live Properties pane (Node > Open properties), and Fork from
// Properties, with real clicks in the compiled Studio. Prints one RERUNFORK line; the Python test asserts it.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');

async function main() {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const newest = pattern => fs.readdirSync(input.browserCache).filter(name => pattern.test(name)).sort((a, b) => Number(b.split('-').at(-1)) - Number(a.split('-').at(-1)))[0];
  const full = newest(/^chromium-\d+$/), shell = newest(/^chromium_headless_shell-\d+$/);
  const executablePath = full ? path.join(input.browserCache, full, 'chrome-win64/chrome.exe') : path.join(input.browserCache, shell, 'chrome-headless-shell-win64/chrome-headless-shell.exe');
  const browser = await chromium.launch({headless: true, executablePath});
  const report = {reruns: [], before: [], forked: '', reopened: [], errors: []};
  try {
    const context = await browser.newContext({viewport: {width: 1680, height: 1000}});
    await context.addCookies([{name: 'archhub_studio', value: input.cookie, url: input.url}]);
    context.setDefaultTimeout(15000);
    const page = await context.newPage();
    page.on('pageerror', error => report.errors.push(error.message));
    const ready = () => page.waitForFunction(() => window.ArchHubAPI && !document.getElementById('studio-boot') && document.querySelector('[data-home-ready]'), null, {timeout: 60000});
    const open = async () => {
      await page.getByRole('button', {name: 'Canvas', exact: true}).first().click();
      await page.evaluate(file => window.ArchHubAPI.openSession(file), input.file);
    };
    const ids = () => page.evaluate(() => window.ArchHubAPI.getSessionDocument().nodes.map(n => n.id).sort());
    await page.goto(input.url, {waitUntil: 'domcontentloaded'});
    await ready();
    await open();
    const title = page.locator('.react-flow__node[data-id="middle"] [data-node-card-title]').first();
    await title.waitFor();
    report.before = await ids();
    const isRun = response => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/session-files'
      && response.request().postDataJSON()?.action === 'run';
    const rerun = async button => {
      await button.waitFor({state: 'visible'});
      const [response] = await Promise.all([page.waitForResponse(isRun), button.click()]);
      const request = response.request().postDataJSON(), result = await response.json();
      assert.equal(response.status(), 200);
      const state = result.results?.middle || result.result?.results?.middle || {};
      report.reruns.push({again: request.again, root: (request.roots || [])[0], status: state.status, output: state.output});
      await page.waitForFunction(() => /Done|Solved/.test(window.ArchHubAPI.getSessionDocument().nodes.find(n => n.id === 'middle')?.result?.status || ''));
    };
    // 1. The node menu (right-click).
    await title.click({button: 'right'});
    await rerun(page.getByRole('menu', {name: 'Node menu'}).locator('[data-design="menu.rerun"]'));
    // 2. Node > Open properties > the rendered Inspector.
    await title.dblclick();
    const dialog = page.getByRole('dialog');
    await dialog.getByRole('button', {name: 'Open properties'}).click();
    if (await dialog.isVisible()) await dialog.getByRole('button', {name: 'Close dialog', exact: true}).click();
    const fold = page.getByRole('button', {name: 'Open Inspector', exact: true}).first();
    if (await fold.isVisible()) await fold.click();
    const inspector = page.locator('[data-node-inspector="middle"]');
    await inspector.waitFor();
    await rerun(inspector.locator('[data-command="menu.rerun"]'));
    const fork = inspector.locator('[data-command="menu.fork"]');
    await fork.click();
    await page.waitForFunction(count => window.ArchHubAPI.getSessionDocument().nodes.length === count + 1, report.before.length);
    report.forked = (await ids()).find(id => !report.before.includes(id)) || '';
    // 3. Saved and reloaded: the fork is still there.
    await page.evaluate(file => window.ArchHubAPI.saveSession(file), input.file);
    await page.reload({waitUntil: 'domcontentloaded'});
    await ready();
    await open();
    await title.waitFor();
    report.reopened = await ids();
    assert.deepEqual(report.errors, []);
  } catch (error) {
    report.errors.push(error.stack || String(error));
  } finally {
    await browser.close();
  }
  console.log('RERUNFORK ' + JSON.stringify(report));
  process.exit(report.errors.length ? 1 : 0);
}
main();
