// Design v63 C1-C2 in the compiled Studio on a seeded isolated Workshop: inside a session the composer talks to that session.
// Driven by 02.TESTS/tests/test_session_composer.py.
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
    // Every composer send and every session the page creates, as the server receives them.
    const chats = [], created = [];
    page.on('request', request => {
      const body = request.postData() || '';
      if (request.url().endsWith('/api/router/chat')) chats.push(JSON.parse(body));
      if (body.includes('"createTask"')) created.push(body);
    });
    const ws = page.locator('[data-dock-workspace]');
    const composer = page.locator('.v22g-composer-dock form');
    const target = () => composer.locator('.recipient-name').innerText();
    const sessionId = title => page.evaluate(name => window.ArchHubAPI.getSnapshot().tasks.find(task => task.title === name).id, title);
    const openTab = async title => {
      const tab = page.getByRole('tab', {name: title, exact: true});
      if (await tab.count()) await tab.click();
      else {
        await page.locator('[data-design="tab.add"]').click();
        await page.getByRole('menu', {name: 'Open tasks', exact: true}).getByRole('button', {name: title, exact: true}).click();
      }
      await page.getByRole('tab', {name: title, exact: true, selected: true}).waitFor();
      await composer.waitFor();
    };

    await page.goto(input.url);
    await page.locator('.dx-task, [data-dock-workspace]').first().waitFor({state: 'attached'});
    if (!await ws.count()) {
      const row = page.locator('.dx-task').filter({hasText: 'Drawing set review'}).first();
      if (await row.isVisible()) await row.click();
      await page.getByRole('button', {name: 'Open its Canvas', exact: true}).click();
    }
    await ws.waitFor();
    await composer.waitFor();

    // C1: the default is this session's agents, never BABOOM.
    assert.equal(await target(), 'All agents', 'inside a session the composer talks to its agents');
    assert.equal(await composer.locator('textarea').getAttribute('placeholder'), 'Message All agents');
    // With no agent of this session joined, Send says so and sends nothing; it never makes a session.
    await composer.locator('textarea').fill('Check the sheet index');
    await composer.getByRole('button', {name: 'Send', exact: true}).click();
    await page.getByText('No agent of this session has joined yet.', {exact: false}).first().waitFor();
    assert.equal(chats.length, 0, 'nothing was sent to anyone');
    assert.equal(await composer.locator('textarea').inputValue(), 'Check the sheet index', 'the text stays');

    // BABOOM only by an explicit pick; the send lands in this session's thread.
    await composer.getByRole('button', {name: 'Recipient', exact: true}).click();
    await page.getByRole('option', {name: /^BABOOM/}).click();
    assert.equal(await target(), '@BABOOM');
    await page.route('**/api/router/chat', route => route.fulfill({status: 200, contentType: 'application/x-ndjson', body: JSON.stringify({type: 'done', answer: 'ok', provider: 'test', model: 'test'}) + '\n'}));
    await composer.getByRole('button', {name: 'Send', exact: true}).click();
    for (let tries = 0; tries < 50 && !chats.length; tries++) await page.waitForTimeout(100);
    assert.equal(chats.length, 1, 'the picked BABOOM send went out once');
    assert.equal(chats[0].task, await sessionId('Drawing set review'), 'the send lands in this session\'s thread');
    await page.unroute('**/api/router/chat');

    // C2: the pick belongs to that session. Another session starts on All agents again, and so does coming back.
    await openTab('Export issue package');
    assert.equal(await target(), 'All agents', 'another session starts on its own agents');
    await openTab('Drawing set review');
    assert.equal(await target(), 'All agents', 'the pick cleared when he moved to another session');
    assert.equal(created.length, 0, 'the composer never created a session');
    assert.deepEqual(errors, []);
    console.log('PASS session_composer_live: All agents by default, BABOOM only by a pick, send in this thread, pick cleared on a session switch');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
