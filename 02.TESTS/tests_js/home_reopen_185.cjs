// React error 185 (installed 20261118-1419 and 1857), driven by 02.TESTS/tests/test_home_reopen_185.py on an unseeded profile.
// A session mounting with its thread beside the canvas while the Library was hidden made Home's Library mirror and its dock
// ping-pong until React stopped the render ("Could not open this view"). Antigravity's two reproducers, each on a fresh window
// at 1440; old code ends each in the error screen.
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
    const fresh = async (label, run) => {
      const context = await browser.newContext({viewport: {width: 1440, height: 900}});
      await context.addCookies([{name: 'archhub_studio', value: input.cookie, url: input.url}]);
      const page = await context.newPage(), failed = [];
      page.on('pageerror', error => failed.push(error.message));
      await page.goto(input.url);
      await page.locator('[data-home-page]').waitFor();
      const broken = page.getByText('Could not open this view');
      const settle = async (shown, step) => {
        await page.locator(shown).or(broken).first().waitFor();
        await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));  // a render loop breaks within the next frames
        assert.equal(await broken.count(), 0, label + ': ' + step + ' opens without the error screen ' + failed.join(' | '));
      };
      await run(page, settle);
      assert.deepEqual(failed, [], label + ': no page errors');
      if (input.shots) await page.screenshot({path: path.join(input.shots, 'home-185-' + label.split(' ')[0] + '.png')});
      await context.close();
    };
    const canvasView = '[data-screen="task-file"] [data-task-face="canvas"]', threadView = '[data-screen="task-file"] [data-task-face="split"]';
    const create = (page, title) => page.evaluate(async name => { const row = await window.ArchHubAPI.createTask(name); await window.ArchHubAPI.listTasks?.(); return row?.taskId || ''; }, title);
    const openTask = (page, id) => page.evaluate(task => window.dispatchEvent(new CustomEvent('archhub:open-task', {detail: {task_id: task}})), id);
    const rail = (page, label) => page.getByRole('navigation').getByRole('button', {name: label, exact: true}).first();
    // 1. On the Canvas the bar's Library button hides the Library; Home; a new session; ArchHub menu, Workshop: the new
    //    session opens with its thread while the Library is hidden.
    await fresh('1 menu Workshop with the Library hidden', async (page, settle) => {
      await rail(page, 'Canvas').click();
      const library = page.locator('[data-design="canvas.library"]');
      await page.locator('[data-design="canvas.library"][aria-pressed="true"]').waitFor();
      await library.click();
      await page.locator('[data-design="canvas.library"][aria-pressed="false"]').waitFor();
      await rail(page, 'Home').click();
      await settle('[data-home-page]', 'Home');
      assert.ok(await create(page, 'Session A for the menu'));
      await page.getByRole('button', {name: 'ArchHub menu', exact: true}).click();
      await page.locator('[role="menu"]').getByText('Workshop', {exact: true}).first().click();
      await settle(threadView, 'Workshop from the menu');
    });
    // 2. Codex e988's route: a session's canvas, its thread, Home, a second session, then the first reopened by its id
    //    (as BABOOM, a task link and the tray do). From Home the rail's Canvas then opens that open session.
    await fresh('2 reopen with its thread', async (page, settle) => {
      const first = await create(page, 'Canvas session to reopen');
      await openTask(page, first);
      await settle(canvasView, 'its canvas');
      await page.locator('[data-design="toolbar.thread"]').click();
      await settle(threadView, 'its thread');
      await rail(page, 'Home').click();
      await settle('[data-home-page]', 'Home');
      assert.ok(await create(page, 'A second session'));
      await openTask(page, first);
      await settle('[data-screen="task-file"]', 'the first session again');
      await rail(page, 'Home').click();
      await settle('[data-home-page]', 'Home again');
      await rail(page, 'Canvas').click();
      await settle(canvasView, 'Canvas from Home');
      assert.equal((await page.locator('.v22g-tab[data-active="true"] [role="tab"]').textContent()).trim(), 'Canvas session to reopen', 'the open session wins');
    });
    await fresh('3 recover the Home filters without losing saved work', async page => {
      const id = await create(page, 'Saved task behind the running filter');
      const hidden = await create(page, 'Hidden task');
      const archived = await create(page, 'Archived task');
      await page.evaluate(id => window.ArchHubAPI.archiveTask(id), archived);
      await page.evaluate(async hidden => {
        const api = window.ArchHubAPI;
        const {homeLayout} = await api.readHomeLayout();
        await api.setSessionListFilter('home', 'workflow');
        await api.setHomeLayout({...homeLayout, hidden:[...homeLayout.hidden,hidden], map: {...homeLayout.map, group:'Project', filter:'Running'}});
      }, hidden);
      await page.getByRole('heading', {name: '0 running', exact: true}).waitFor();
      const saved = page.waitForResponse(response => response.url().endsWith('/api/universal/settings-action')
        && response.request().method() === 'POST' && response.request().postDataJSON()?.function === 'setHomeLayout');
      await page.getByRole('button', {name: /^Show all \([1-9]\d*\)$/}).click();
      assert.ok((await saved).ok(), 'the settings owner accepted the filter change');
      await page.locator('[data-home-kind="all"][aria-pressed="true"]').waitFor();
      const card = task => page.locator('[data-design="home.card"][data-home-task="'+task+'"]');
      await card(id).waitFor();
      assert.equal(await card(hidden).count(), 0);
      assert.equal(await page.locator('[data-design="home.card"]').filter({hasText:'Archived task'}).count(), 0);
      assert.equal(await page.locator('[data-home-task^="declared-"]').count(), 0);
      assert.equal(await page.locator('[data-home-history]').getAttribute('aria-pressed'), 'false');
      const [layout, kinds] = await page.evaluate(async () => Promise.all([
        window.ArchHubAPI.readHomeLayout(),window.ArchHubAPI.readSessionListFilters()
      ]));
      assert.equal(layout.homeLayout.map.filter, 'All');
      assert.equal(layout.homeLayout.map.group, 'Project');
      assert.ok(layout.homeLayout.hidden.includes(hidden));
      assert.equal(kinds.sessionListFilters.home, 'all');
      assert.equal(await page.getByRole('heading', {name: 'What do you need?', exact: true}).count(), 0);
    });
    console.log('OK both reopening routes and the Home filter recovery');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
