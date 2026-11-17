// CHATPICKER in the compiled Studio, driven by 02.TESTS/tests/test_chat_picker_live.py in three phases:
//  refuse  (1009) a refused start on Home leaves nothing behind and keeps the typed text;
//  chat    (1009, 1440) Home and the Canvas composer offer "Start Claude Code"; three messages reach one chat; the
//          dock's Workshop card brings the one composer into its thread, where Claude Code can be started;
//  ended   (1009) the thread's chat process is gone: the next send says so and the chip offers Start again.
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
    for (const width of input.phase === 'chat' ? [1009, 1440] : [1009]) {
      const context = await browser.newContext({viewport: {width, height: 900}});
      await context.addCookies([{name: 'archhub_studio', value: input.cookie, url: input.url}]);
      const page = await context.newPage();
      const errors = [], chats = [], consoleErrors = [];
      page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()); });
      // On any failure the page says what it was showing: URL, title, the first 300 characters of its text, its errors.
      const describe = async () => {
        const seen = await page.evaluate(() => ({title: document.title, text: (document.body?.innerText || '').slice(0, 300)})).catch(error => ({title: '?', text: 'unreadable: ' + error.message}));
        return ['', '  page: ' + page.url(), '  title: ' + seen.title, '  text: ' + JSON.stringify(seen.text),
          '  page errors: ' + JSON.stringify(errors), '  console errors: ' + JSON.stringify(consoleErrors.slice(0, 5))].join('\n');
      };
      try {
      page.on('pageerror', error => { errors.push(error.message); console.error('PAGEERROR ' + error.message); });
      page.on('request', request => { if (request.url().endsWith('/api/router/chat')) chats.push(JSON.parse(request.postData() || '{}')); });
      const shot = async name => { if (input.shots) await page.screenshot({path: path.join(input.shots, input.phase + '-' + name + '-' + width + '.png')}); };
      // Open the Recipient menu inside `scope` by keyboard; the start choice is there, enabled, and says Start.
      const recipient = scope => scope.getByRole('button', {name: 'Recipient', exact: true}).first();
      // The open menu closes on Escape pressed on its own button (the menu listens on its .ws-to box); never a page-wide key.
      const closeMenu = scope => recipient(scope).press('Escape');
      const startChoice = async (scope, name) => {
        await recipient(scope).press('Enter');   // keyboard reachable: Enter on the menu's own button
        const option = scope.locator('[role="option"][data-chat-start="claude"]').first();
        await option.waitFor({timeout: 20000});
        assert.equal(await option.isDisabled(), false, name + ': the start choice is enabled');
        assert.match(await option.innerText(), /Start Claude Code/, name + ': it says start, not message');
        await shot(name);
        return option;
      };
      const send = async (scope, text) => { console.log('send ' + text);
        const field = scope.getByLabel('Message', {exact: true}).first();
        await field.fill(text);
        // answered: the answer text appears once more, or the open session's thread holds two more messages
        const seen = () => [document.body.innerText.split('There are 12 sheets.').length, Number((/Thread\s*(\d+) messages/.exec(document.body.innerText) || [0, 0])[1])];
        const sent = chats.length, [said, held] = await page.evaluate(seen);
        await field.press('Enter');
        await page.waitForFunction(([n, m, probe]) => { const [a, b] = eval(probe)(); return (a > n || b >= m + 2)
          && !document.querySelector('[data-design="composer.send"][aria-busy="true"]'); }, [said, held, seen.toString()], {timeout: 90000})
          .catch(async error => { await shot('send-timeout'); throw error; });
        assert.equal(chats.length, sent + 1, 'one request per send');
        // shortcut: the thread shows the answer before the composer's stream settles; wait for the field to be free
        // again (an Enter while it is sending is ignored by design). Upgrade: a settled marker on the composer.
        await page.waitForTimeout(3000);
        console.log('answered ' + text);
      };
      const chip = scope => scope.locator('.recipient-name').first().innerText();
      // Open the Home chat's session: double-click its row, or (narrow window, rows folded) Open its Canvas on the selected one.
      const openChat = async () => { const row = page.locator('.dx-task').filter({hasText: 'how many sheets?'}).first(); await row.waitFor({state: 'attached'});
        if (await row.isVisible()) await row.dblclick(); else await page.getByRole('button', {name: 'Open its Canvas', exact: true}).click(); };
      const toast = pattern => page.getByText(pattern).first().waitFor({timeout: 30000}).catch(async error => { await shot('failed'); throw error; });
      await page.goto(input.url);
      const home = page.locator('.global-composer'), canvas = page.locator('.dx-composer').first();
      await home.waitFor();
      assert.match(await chip(home), /BABOOM/, 'the default stays BABOOM');
      if (input.phase === 'refuse') {
        const chosen = await startChoice(home, 'home');
        await chosen.click();
        await home.getByLabel('Message', {exact: true}).fill('how many sheets?');
        await home.getByLabel('Message', {exact: true}).press('Enter');
        await toast(/still has tools that act/);
        await page.waitForTimeout(800);
        assert.equal(await home.getByLabel('Message', {exact: true}).inputValue(), 'how many sheets?', 'the typed text is kept');
        assert.equal(await page.locator('.dx-task').filter({hasText: 'how many sheets?'}).count(), 0, 'no session card remains');
        assert.equal(await home.locator('.composer-answer').count(), 0, 'no "Claude Code · starting…" line is left under the composer');
        await shot('refused');
      } else if (input.phase === 'chat' && width === 1009) {
        const chosen = await startChoice(home, 'home');
        await chosen.click();
        await send(home, 'how many sheets?');
        await page.getByText('There are 12 sheets.').first().waitFor({timeout: 60000});
        await canvas.waitFor();
        assert.match(await chip(canvas), /Claude Code chat/, 'the thread stays with its chat');
        await send(canvas, 'and the second one?');
        await send(canvas, 'and the third one?');
        assert.deepEqual(chats.map(body => [body.agent, Boolean(body.continue), body.prompt]),
          [['claude', false, 'how many sheets?'], ['claude', true, 'and the second one?'], ['claude', true, 'and the third one?']]);
        assert.equal(new Set(chats.slice(1).map(body => body.task)).size, 1, 'both follow-ups are in one thread');
        await shot('three-messages');
        await startChoice(canvas, 'canvas');
        await closeMenu(canvas);
      } else if (input.phase === 'chat') {
        await startChoice(home, 'home');
        await closeMenu(home);
        await openChat();
        await canvas.waitFor();
        assert.match(await chip(canvas), /Claude Code chat/, 'after a reload the thread still names its chat');
        await startChoice(canvas, 'canvas');
        await closeMenu(canvas);
      } else {
        await openChat();
        await canvas.waitFor();
        assert.match(await chip(canvas), /Claude Code chat/);
        await canvas.getByLabel('Message', {exact: true}).fill('are you still there?');
        await canvas.getByLabel('Message', {exact: true}).press('Enter');
        await toast(/chat in this thread has ended/);
        await page.waitForFunction(() => /Start Claude Code/.test(document.querySelector('.dx-composer .recipient-name')?.textContent || ''), null, {timeout: 10000});
        assert.equal(await canvas.getByLabel('Message', {exact: true}).inputValue(), 'are you still there?', 'the message is kept, not sent elsewhere');
        assert.deepEqual(chats.map(body => [body.agent, Boolean(body.continue)]), [['claude', true]], 'never sent to BABOOM');
        await shot('ended');
      }
      if (input.phase === 'chat') {
        // The Workshop: the dock panel's Working now card shows its thread in the one composer, focused.
        const card = page.locator('[data-dock-workshop] [data-ws-working]').filter({hasText: 'Model view audit'}).first();
        await card.waitFor({timeout: 20000});
        await card.click();
        await page.waitForFunction(() => document.activeElement?.closest('.dx-composer') && /Model view audit/.test(document.body.innerText), null, {timeout: 20000}).catch(async error => { await shot('card-timeout'); throw error; });
        const option = await startChoice(canvas, 'workshop');
        if (width === 1440) {
          await option.click();
          const before = chats.length;
          await send(canvas, 'how many sheets in this one?');
          assert.equal(chats.length, before + 1);
          assert.equal(chats.at(-1).agent, 'claude');
          await page.getByText('There are 12 sheets.').first().waitFor({timeout: 60000});
          await shot('workshop-answer');
        } else {
          await closeMenu(canvas);
        }
      }
      assert.deepEqual(errors, []);
      } catch (error) {
        console.error('PAGE STATE (' + input.phase + ', ' + width + ' px)' + await describe());   // the stack keeps the old message
        throw error;
      }
      await context.close();
    }
    console.log('chat picker phase ' + input.phase + ': passed');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
