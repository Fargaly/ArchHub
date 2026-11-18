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
      assert.deepEqual(errors, [], 'no page errors' + at);
      if (input.shots) await page.screenshot({path: path.join(input.shots, 'home-' + width + '.png')});
      await context.close();
    }
    console.log('OK home look at 1009, 1440, 1920');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
