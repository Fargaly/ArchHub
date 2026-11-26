// Settings rows that change what the app does, in the compiled Studio on an isolated real server, with real input at
// 944x968 and 1920x1032: five quick clicks on one switch all land, Projects rows reach their owners, a new project
// takes the CDE folders, Numbers turns shown digits Arabic-Indic, Time zone sets shown times, unbuilt rows are status.
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
  const shot = async (page, name) => { if (input.shots) { fs.mkdirSync(input.shots, {recursive: true}); await page.screenshot({path: path.join(input.shots, name)}); } };
  try {
    for (const [width, height] of [[944, 968], [1920, 1032]]) {
      const at = '@' + width, context = await browser.newContext({viewport: {width, height}});
      await context.addCookies([{name: 'archhub_studio', value: input.cookie, url: input.url}]);
      const page = await context.newPage();
      await page.route('**/api/universal/desktop-access', route => route.fulfill({json: {ok: true, admitted: true, state: 'admitted', subject: 'settings-test', email: 'settings@example.test'}}));
      const errors = [], writes = [], flying = new Set();
      page.on('pageerror', error => errors.push(error.message));
      page.on('request', request => {
        if (request.url().includes('/settings-action') || request.url().includes('/workspace-roots')) flying.add(request);
        const body = request.postData() || ''; if (body.includes('"setAppearance"')) writes.push(JSON.parse(body).args);
      });
      for (const done of ['requestfinished', 'requestfailed']) page.on(done, request => flying.delete(request));
      await page.goto(input.url);
      const nav = page.getByRole('navigation', {name: 'Settings categories'}), sheet = page.locator('.sheet-columns:not([hidden])');
      const area = async name => { await nav.getByRole('button', {name, exact: true}).click(); await sheet.locator('section[data-design-section]').first().waitFor(); };
      const value = id => page.evaluate(id => window.ArchHubAPI.getSnapshot().settings.find(row => row.id === id)?.value, id);
      // Until no settings write is in flight and none started for a second (chained writes start one after another).
      const quiet = async () => { let last = -1; for (let i = 0; i < 300 && (last !== writes.length || flying.size); i++) { last = writes.length; await page.waitForTimeout(1000); } };

      // 1. Five quick clicks right after Settings opens, by mouse at the switch (no waiting for it to be ready).
      await page.locator('.app-rail button[aria-label="Settings"]').click();
      await area('Connections');
      const sound = sheet.locator('[data-row="sound"]').getByRole('switch');
      await sound.waitFor();
      await sound.evaluate(node => node.scrollIntoView({block: 'center'}));
      const before = await value('Connections.Sound');
      for (let i = 0; i < 5; i++) await sound.click({force: true, delay: 0});  // real mouse input, no waiting for the switch to be ready
      await quiet();
      report['rapid' + at] = {before, writes: writes.filter(args => args[0] === 'Connections.Sound').map(args => args[1]),
        shown: await sound.getAttribute('aria-checked'), held: await value('Connections.Sound')};
      await shot(page, `rapid-sound-${width}x${height}.png`);

      // 2. Projects rows read by the DWG and PDF exports, the sheet layout and the Session node.
      await area('Projects');
      for (const more of await sheet.getByRole('button', {name: /^\d+ more$/}).all()) await more.click();
      await sheet.locator('[data-row="layerStd"] select').selectOption('ISO 13567');
      await sheet.locator('[data-row="ctb"] select').selectOption('Office monochrome.ctb');
      await sheet.locator('[data-row="defaultScale"] select').selectOption('1:200');
      const template = sheet.locator('[data-row="revitTpl"] input');
      await template.fill('C:\\Templates\\Office ' + width + '.rte');
      await template.press('Enter');
      await quiet();
      await sheet.locator('[data-row="revitTpl"]').scrollIntoViewIfNeeded();
      await shot(page, `projects-rows-${width}x${height}.png`);

      // 3. CDE folders: the Projects folder is a registered workspace; New project takes it and builds the ISO tree.
      await page.evaluate(folder => window.ArchHubAPI.addWorkspace({folder}), input.parent);
      const root = sheet.locator('[data-row="cdeRoot"] input');
      await root.fill(input.parent);
      await root.press('Enter');
      const codes = sheet.locator('[data-row="disciplines"] input');
      await codes.fill('A, S, M');
      await codes.press('Enter');
      await quiet();
      const cde = sheet.locator('section[data-design-section="CDE folders"]');
      await cde.locator('summary', {hasText: 'Project folders'}).click();
      await cde.getByRole('button', {name: 'New project', exact: true}).click();
      const form = cde.getByRole('form', {name: 'New project'});
      await form.getByLabel('Project name').fill('CDE-' + width);
      report['parent' + at] = await form.getByLabel('Parent workspace').evaluate(node => node.selectedOptions[0]?.textContent);
      await form.getByLabel('New project folders').selectOption('ISO 19650 CDE tree');
      await form.scrollIntoViewIfNeeded();
      await shot(page, `cde-new-project-${width}x${height}.png`);
      await form.getByRole('button', {name: 'Create project'}).click();
      await form.waitFor({state: 'detached', timeout: 30000}).catch(() => {});
      report['created' + at] = fs.existsSync(path.join(input.parent, 'CDE-' + width, 'WIP', 'Models', 'A'));

      // 4. Account: unbuilt rows are a plain status; Time zone sets shown times; Numbers turns shown digits Arabic-Indic.
      await area('Account');
      for (const more of await sheet.getByRole('button', {name: /^\d+ more$/}).all()) await more.click();
      report['status' + at] = await sheet.locator('[data-row="commProfile"] [role="status"]').textContent();
      const noon = () => page.evaluate(() => new Date(Date.UTC(2026, 0, 1, 12, 0)).toLocaleTimeString('en-GB', window.UI.zoned({hour: '2-digit', minute: '2-digit'})));
      await sheet.locator('[data-row="timezone"] select').selectOption('UTC');
      await quiet();
      const utc = await noon();
      await sheet.locator('[data-row="timezone"] select').selectOption('Asia/Dubai (GMT+4)');
      await quiet();
      report['zone' + at] = {utc, dubai: await noon()};
      await sheet.locator('[data-row="numerals"]').getByRole('button', {name: '١٢٣'}).click();
      await quiet();
      await page.waitForTimeout(500);
      report['numbers' + at] = await page.evaluate(() => {
        const tabs = document.querySelector('.sheet-tabs')?.innerText || '';
        return {arabic: (document.body.innerText.match(/[٠-٩]/g) || []).length, latinInTabs: (tabs.match(/[0-9]/g) || []).length};
      });
      await sheet.locator('[data-row="numerals"]').scrollIntoViewIfNeeded();
      await shot(page, `numbers-arabic-${width}x${height}.png`);
      await sheet.locator('[data-row="numerals"]').getByRole('button', {name: '123'}).click();
      await quiet();
      report['errors' + at] = errors;
      await context.close();
    }
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify(report, null, 1));
})().catch(error => { console.error(error); process.exit(2); });
