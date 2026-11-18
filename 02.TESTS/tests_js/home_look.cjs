// Home in the compiled Studio on a seeded isolated Workshop, at 1009, 1440 and 1920: the page fills the window, the
// composer sits in the work column, no raw session id or cut word shows, a title is said once, one update state shows.
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
    for (const width of [1009, 1440, 1920]) {
      const context = await browser.newContext({viewport: {width, height: 900}});
      await context.addCookies([{name: 'archhub_studio', value: input.cookie, url: input.url}]);
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => { errors.push(error.message); console.error('PAGEERROR ' + error.message); });
      // Two live Claude Code sessions in one folder with no task, as on his PC: the agent owner's answer is stood in for here.
      const live = ['Claude Code / 00.ARCHUB / session-62fdf0706b09', 'Claude Code / 00.ARCHUB / session-8dff5b479f68'];
      await page.route('**/api/universal/agents-canvas', route => route.fulfill({status: 200, contentType: 'application/json',
        body: JSON.stringify({agents: [], sessions: live.map((name, index) => ({id: 'live' + index, name, status: 'working', task: null}))})}));
      await page.goto(input.url);
      await page.locator('[data-home-ready]').waitFor({state: 'attached'});
      await page.locator('.resume-heading h1').filter({hasText: input.echo}).waitFor();  // the owner's resume record selects it at every width
      // The seed is real: the session's one plan step is named like the session.
      const plan = await page.evaluate(id => window.ArchHubAPI.getSnapshot().tasks.find(task => task.id === id)?.plan, input.echoTask);
      assert.deepEqual(plan, [input.echo], 'the echo session carries one plan step with its own title');
      const seen = await page.evaluate(() => {
        const box = element => { const r = element.getBoundingClientRect(); return {left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width}; };
        const shown = element => !!element && element.getClientRects().length > 0;
        const main = document.querySelector('.resume-main'), list = document.querySelector('aside[aria-label="Sessions"]');
        const composer = document.querySelector('[data-design="composer.surface"]') || document.querySelector('.global-composer form');
        const header = document.querySelector('.app-header');
        return {
          inner: window.innerWidth, scroll: document.documentElement.scrollWidth, header: box(header), main: box(main), list: box(list), composer: box(composer),
          composerInColumn: !!composer.closest('.resume-main'),
          rows: [...document.querySelectorAll('.resume-row .dx-task')].filter(shown).map(row => ({title: row.querySelector('b').textContent, line: row.querySelector('span').textContent,
            clipped: row.querySelector('span').scrollWidth > row.querySelector('span').clientWidth + 1})),
          heading: document.querySelector('.resume-heading h1').textContent.trim(), stepLine: document.querySelector('.resume-heading p').textContent.trim(),
          stepTitles: [...document.querySelectorAll('.resume-step>header b')].map(b => b.textContent.trim()),
          checking: /Checking for updates/.test(header.textContent), failed: [...header.querySelectorAll('button')].some(button => shown(button) && button.textContent.trim() === 'Update failed'),
        };
      });
      const at = ' at ' + width;
      // A: the page uses the whole window; nothing scrolls sideways.
      assert.equal(seen.scroll, seen.inner, 'no sideways scroll' + at);
      assert.ok(Math.abs(seen.header.right - seen.inner) <= 1, 'the header ends at the window edge' + at);
      assert.ok(seen.main.right <= seen.inner + 1 && seen.main.right >= seen.inner - 1, 'the work column runs to the window edge' + at);
      // C: the composer is a child of the work column and stays inside it; it never covers the Sessions list.
      assert.ok(seen.composerInColumn, 'the composer belongs to the work column' + at);
      assert.ok(seen.composer.left >= seen.main.left - 1 && seen.composer.right <= seen.main.right + 1, 'the composer is inside the work column' + at + ': ' + JSON.stringify([seen.composer, seen.main]));
      assert.ok(seen.composer.left >= seen.list.right - 1, 'the composer does not cover the Sessions list' + at);
      // D: no raw session id as a visible name, and no line cut off.
      for (const row of seen.rows) {
        assert.doesNotMatch(row.title + ' ' + row.line, /session-[0-9a-f]{6,}/i, 'no raw session id in a row' + at);
        assert.equal(row.clipped, false, 'the second line fits or wraps' + at + ': ' + row.line);
      }
      // E: the title is said once.
      assert.equal(seen.heading, input.echo);
      assert.ok(!seen.stepLine.includes(input.echo), 'the step line does not repeat the title' + at + ': ' + seen.stepLine);
      assert.ok(!seen.stepTitles.includes(input.echo), 'no step card repeats the title' + at);
      // G: one update state at a time.
      assert.ok(!(seen.checking && seen.failed), 'never "Checking for updates" beside "Update failed"' + at);
      // C (design v61): below 1100 the list folds to avatars; each avatar names its session and selects it.
      if (width < 1100) {
        const avatars = page.locator('aside[aria-label="Sessions"] .resume-row .resume-avatar');
        await page.waitForFunction(() => (window.ArchHubAPI.getSnapshot().agentGraph?.sessions || []).length === 2);  // the agents arrive after the tasks
        await avatars.and(page.locator('[aria-label^="Claude Code · 00.ARCHUB"]')).nth(1).waitFor();
        const names = await avatars.evaluateAll(buttons => buttons.filter(button => button.getClientRects().length).map(button => button.getAttribute('aria-label')));
        assert.ok(names.length >= 3 && new Set(names).size === names.length, 'every folded session is told apart' + at + ': ' + JSON.stringify(names));
        assert.deepEqual(names.filter(name => name.startsWith('Claude Code · 00.ARCHUB')).sort(), ['Claude Code · 00.ARCHUB · 62fdf0', 'Claude Code · 00.ARCHUB · 8dff5b'], 'two live sessions of one app and folder are told apart' + at);
        const other = names.find(name => !name.startsWith(input.echo) && !name.startsWith('Claude Code'));
        await page.getByRole('button', {name: other, exact: true}).click();
        await page.locator('.resume-heading h1').filter({hasText: other.split(' · ')[0]}).waitFor();
        await page.getByRole('button', {name: names.find(name => name.startsWith(input.echo)), exact: true}).click();
        await page.locator('.resume-heading h1').filter({hasText: input.echo}).waitFor();
        // The selection is in the Home owner's record before this window closes (the next width opens on it).
        await page.waitForFunction(async id => (await window.ArchHubAPI.readHomeLayout()).homeLayout.resume === id, input.echoTask, {polling: 250});
      }
      // D (design v61 C1-C3): the session selected on Home is the composer's recipient; the message lands in its thread and Home stays.
      // The model's answer is stood in for (one streamed result); the recipient, the request and the screen are the app's own.
      const composer = page.locator('.global-composer'), chip = composer.locator('[data-design="composer.to"]'), sent = [];
      await page.route('**/api/router/chat', route => { sent.push(JSON.parse(route.request().postData() || '{}'));
        return route.fulfill({status: 200, contentType: 'text/event-stream', body: 'data: ' + JSON.stringify({result: {answer: 'Noted.', provider: 'BABOOM'}}) + '\n\n'}); });
      assert.equal((await chip.innerText()).trim(), input.echo, 'the selected session is the recipient' + at);
      const before = await page.evaluate(() => window.ArchHubAPI.getSnapshot().tasks.length);
      await composer.getByLabel('Message', {exact: true}).fill('Check the north elevation too');
      await composer.getByLabel('Message', {exact: true}).press('Enter');
      await page.getByText('Sent to ' + input.echo + '. It is in that session’s thread.').first().waitFor();
      assert.deepEqual(sent.map(body => [body.task, body.prompt]), [[input.echoTask, 'Check the north elevation too']], 'one message, to that session' + at);
      assert.equal(await page.locator('[data-home-page]').count(), 1, 'Home stays' + at);
      assert.equal(await page.evaluate(() => window.ArchHubAPI.getSnapshot().tasks.length), before, 'no new session' + at);
      // An explicit New session pick belongs to the session it was made on: selecting another session clears it.
      // (Only a session he selected is a recipient: a hidden or archived selection leaves the chip on New session.)
      await chip.click();
      assert.equal((await chip.innerText()).trim(), 'New session');
      const sessions = page.locator('aside[aria-label="Sessions"]');
      await sessions.getByRole('button', {name: /^Sheet index check/}).first().click();
      await page.locator('.resume-heading h1').filter({hasText: 'Sheet index check'}).waitFor();
      assert.equal((await chip.innerText()).trim(), 'Sheet index check', 'the pick does not follow to another session' + at);
      await sessions.getByRole('button', {name: new RegExp('^' + input.echo)}).first().click();
      await page.locator('.resume-heading h1').filter({hasText: input.echo}).waitFor();
      await page.waitForFunction(async id => (await window.ArchHubAPI.readHomeLayout()).homeLayout.resume === id, input.echoTask, {polling: 250});
      assert.equal((await chip.innerText()).trim(), input.echo);
      await page.unroute('**/api/router/chat');
      assert.deepEqual(errors, [], 'no page errors' + at);
      if (input.shots) await page.screenshot({path: path.join(input.shots, 'home-' + width + '.png')});
      await context.close();
    }
    console.log('OK home look at 1009, 1440, 1920');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
