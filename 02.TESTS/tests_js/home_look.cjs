// Home in the compiled Studio on a seeded isolated Workshop, at 1009, 1440 and 1920: Home is the map of the work (session
// cards in groups between the Canvas docks), every map value is a parameter, the header's chips act, the composer stays in
// the map's column, no raw session id shows, a title is said once and the header agrees with the map.
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
      const errors = [], at = ' at ' + width;
      page.on('pageerror', error => { errors.push(error.message); console.error('PAGEERROR ' + error.message); });
      // Two live Claude Code sessions in one folder with no task, as on his PC: the agent owner's answer is stood in for here.
      const live = ['Claude Code / 00.ARCHUB / session-62fdf0706b09', 'Claude Code / 00.ARCHUB / session-8dff5b479f68'];
      await page.route('**/api/universal/agents-canvas', route => route.fulfill({status: 200, contentType: 'application/json',
        body: JSON.stringify({agents: [], sessions: live.map((name, index) => ({id: 'live' + index, name, status: 'working', task: null}))})}));
      await page.goto(input.url);
      const map = page.locator('[data-home-map]'), card = title => map.locator('.react-flow__node').filter({has: page.locator('[data-design="home.card"]'), hasText: title}).first();
      await map.waitFor();
      await card(input.echo).waitFor();
      // A map value is in the Home owner's published record (the write is back), not only on screen.
      const held = (key, value) => page.waitForFunction(([key, value]) => ((window.ArchHubAPI.getSnapshot().homeLayout?.map || {})[key] || '') === value, [key, value]);
      const read = () => page.evaluate(() => {
        const box = element => { const r = element.getBoundingClientRect(); return {left: r.left, right: r.right, width: r.width}; };
        const shown = element => !!element && element.getClientRects().length > 0;
        const header = document.querySelector('.app-header'), stage = document.querySelector('.home-map-stage');
        const composer = document.querySelector('.home-map-stage [data-design="composer.surface"]') || document.querySelector('.home-map-stage .global-composer form');
        const count = word => Number(([...document.querySelectorAll('.header-status button')].map(button => button.textContent.trim()).find(text => text.endsWith(word)) || '0').split(' ')[0]) || 0;
        return {
          inner: window.innerWidth, scroll: document.documentElement.scrollWidth, header: box(header), stage: box(stage), composer: composer ? box(composer) : null,
          docks: [...document.querySelectorAll('.dockws > .dock')].filter(shown).map(box), text: document.body.innerText,
          cards: [...document.querySelectorAll('[data-design="home.card"]')].map(element => ({state: element.dataset.homeState, title: element.querySelector('.home-card-head').textContent})),
          groups: [...document.querySelectorAll('[data-design="group.title"]')].map(element => element.textContent),
          wires: document.querySelectorAll('[data-home-canvas] [data-graph-wire]').length,
          headerNeeds: count('need you'), headerRunning: count('running'), barNeeds: Number(document.querySelector('[data-home-filter="Needs you"] b').textContent),
          pc: [...document.querySelectorAll('.header-status button')].some(button => shown(button) && button.textContent.startsWith('On this PC')),
          checking: /Checking for updates/.test(header.textContent), failed: [...header.querySelectorAll('button')].some(button => shown(button) && button.textContent.trim() === 'Update failed'),
        };
      });
      // The held runs arrive after the sessions (their own owner read): wait for the count before reading the screen.
      await page.waitForFunction(() => Number(document.querySelector('[data-home-filter="Needs you"] b')?.textContent) >= 1);
      let seen = await read();
      // The page uses the whole window; the map sits between the docks and the composer inside the map's column.
      assert.equal(seen.scroll, seen.inner, 'no sideways scroll' + at);
      assert.ok(Math.abs(seen.header.right - seen.inner) <= 1, 'the header ends at the window edge' + at);
      assert.ok(seen.docks.length >= 1, 'the Canvas docks stand beside the map' + at);
      assert.ok(seen.composer && seen.composer.left >= seen.stage.left - 1 && seen.composer.right <= seen.stage.right + 1, 'the composer is inside the map column' + at + ': ' + JSON.stringify([seen.composer, seen.stage]));
      for (const dock of seen.docks) assert.ok(seen.composer.right <= dock.left + 1 || seen.composer.left >= dock.right - 1, 'the composer does not cover a dock' + at);
      // Session cards in project groups, wired by the seeded input link.
      assert.deepEqual(seen.cards.map(row => row.title.includes(input.echo)).filter(Boolean).length, 1, 'the echo session is one card' + at);
      assert.ok(seen.cards.length >= 3 && seen.groups.length >= 1, 'cards in groups' + at + ': ' + JSON.stringify([seen.cards, seen.groups]));
      assert.ok(seen.wires >= 1, 'the input link is drawn as a wire' + at);
      assert.doesNotMatch(seen.text, /session-[0-9a-f]{6,}/i, 'no raw session id on Home' + at);
      // Two live sessions of one app in one folder are two cards told apart by name (design v61 C2), never identical.
      await page.waitForFunction(() => [...document.querySelectorAll('[data-design="home.card"] .home-card-head b')].filter(b => b.textContent.startsWith('Claude Code')).length === 2);
      const liveTitles = await page.evaluate(() => [...document.querySelectorAll('[data-design="home.card"] .home-card-head b')].map(b => b.textContent).filter(t => t.startsWith('Claude Code')).sort());
      assert.deepEqual(liveTitles, ['Claude Code · 62fdf0', 'Claude Code · 8dff5b'], 'live sessions are told apart' + at);
      // Every name on Home, the docks included, is readable: no raw session id; the map's bar words do not overlap.
      assert.doesNotMatch(await page.evaluate(() => document.body.innerText), /session-[0-9a-f]{6,}/i, 'no raw session id anywhere on Home' + at);
      const bar = await page.evaluate(() => [...document.querySelectorAll('.home-map-bar>button')].filter(b => b.getClientRects().length).map(b => { const r = b.getBoundingClientRect(); return [r.left, r.right, b.scrollWidth <= b.clientWidth + 1]; }));
      for (let i = 1; i < bar.length; i++) assert.ok(bar[i][0] >= bar[i - 1][1] - 1, 'the map bar buttons do not overlap' + at + ': ' + JSON.stringify(bar));
      assert.ok(bar.every(b => b[2]), 'no map bar word is cut' + at);
      // At every width a card's name is drawn at a readable size (the map wraps to its room).
      const nameSize = await page.evaluate(() => Math.min(...[...document.querySelectorAll('[data-design="home.card"] .home-card-head b')].map(b => b.getBoundingClientRect().height)));
      assert.ok(nameSize >= 11, 'card names are readable' + at + ': ' + nameSize);
      // The header and the map count the same sessions; one update state at a time.
      assert.ok(seen.barNeeds >= 1, 'the seeded held run needs him' + at);
      assert.equal(seen.headerNeeds, seen.barNeeds, 'the header agrees with the map' + at);
      assert.equal(seen.cards.filter(row => row.state === 'Needs you').length, seen.barNeeds, 'and with the cards' + at);
      assert.ok(!(seen.checking && seen.failed), 'never "Checking for updates" beside "Update failed"' + at);
      if (width >= 1500) assert.ok(seen.pc, 'the On this PC chip shows' + at);
      // Nothing selected: the Inspector holds the map's parameters. Group by State re-arranges the map, in the owner record.
      const inspector = page.locator('[data-home-inspector]');
      if (!await inspector.isVisible()) await page.locator('.dock.right [data-tab="insp"]').click();
      // 1009 with both docks open (left 268, right 320): the composer's message box keeps a real width with a picked session
      // (its name on the scope chip, the agent picker beside it) and, below, with nothing picked.
      const messageWidth = () => page.locator('.home-map-stage .global-composer textarea').evaluate(element => element.getBoundingClientRect().width);
      if (width === 1009) {
        const openRight = page.getByRole('button', {name: 'Open the right dock', exact: true});
        if (await openRight.count()) { await openRight.click(); await page.waitForTimeout(450); }
        await page.waitForFunction(() => (document.querySelector('.dockws > .dock.right')?.getBoundingClientRect().width || 0) > 200, null, {timeout: 5000}).catch(() => {});  // the dock eases open
        const docks = await page.evaluate(() => [...document.querySelectorAll('.dockws > .dock')].map(dock => dock.className + ' ' + Math.round(dock.getBoundingClientRect().width)));
        assert.equal(docks.filter(text => !text.split(' ').includes('col') && Number(text.split(' ').at(-1)) > 200).length, 2, 'both docks are open at 1009: ' + JSON.stringify(docks));
        await map.locator('.home-card.sel').first().waitFor();
        await page.locator('.home-map-stage .global-composer [data-design="composer.to"]').filter({hasText: input.echo}).waitFor();
        const picked = await messageWidth();
        assert.ok(picked >= 160, 'the message box is usable beside a picked session at 1009 with both docks: ' + picked + ' px');
      }
      // The owner's record selects a session on open (Home's saved selection); a click on the empty map clears it.
      await map.locator('.home-card.sel').first().waitFor();
      await map.locator('.react-flow__pane').click({position: (await page.evaluate(() => { const pane = document.querySelector('[data-home-map] .react-flow__pane'), r = pane.getBoundingClientRect(); for (let y = r.top + 4; y < r.bottom; y += 12) for (let x = r.left + 4; x < r.right; x += 12) if (document.elementFromPoint(x, y) === pane) return {x: x - r.left, y: y - r.top}; return {x: 4, y: 4}; }))});  // an empty spot of the map clears the pick
      await map.locator('.home-card.sel').waitFor({state: 'detached'});
      if (!await inspector.isVisible()) await page.locator('.dock.right [data-tab="insp"]').click();  // a folded dock's peek closes on a click outside it
      await inspector.getByRole('heading', {name: 'Map of the work', exact: true}).waitFor();
      if (width === 1009) {
        const empty = await messageWidth();
        assert.ok(empty >= 160, 'the message box is usable with nothing picked at 1009 with both docks: ' + empty + ' px');
      }
      for (const label of ['Group by', 'Order', 'Card', 'Density', 'Finished sessions', 'Show']) await inspector.getByLabel(label, {exact: true}).waitFor();
      const projects = seen.groups;
      await inspector.getByLabel('Group by', {exact: true}).selectOption('State');
      await map.locator('[data-design="group.title"]').filter({hasText: 'Needs you'}).first().waitFor();
      await held('group', 'State');  // the parameter is in the owner record
      // Undo and Redo step through Home changes.
      await map.getByRole('button', {name: 'Undo', exact: true}).click();
      await map.locator('[data-design="group.title"]').filter({hasText: projects[0]}).first().waitFor();
      await held('group', '');
      await map.getByRole('button', {name: 'Redo', exact: true}).click();
      await map.locator('[data-design="group.title"]').filter({hasText: 'Needs you'}).first().waitFor();
      await held('group', 'State');
      await map.getByRole('button', {name: 'Undo', exact: true}).click();
      await map.locator('[data-design="group.title"]').filter({hasText: projects[0]}).first().waitFor();
      await held('group', '');
      // A header count is a filter of the map.
      await page.locator('.header-status button').filter({hasText: 'need you'}).click();
      await map.locator('[data-home-filter="Needs you"][aria-pressed="true"]').waitFor();
      await held('filter', 'Needs you');
      seen = await read();
      assert.ok(seen.cards.length >= 1 && seen.cards.every(row => row.state === 'Needs you'), 'only what needs him is drawn' + at + ': ' + JSON.stringify(seen.cards));
      await map.locator('[data-home-filter="Needs you"]').click();
      await held('filter', 'All');
      await card(input.echo).waitFor();
      // A card selects its session: the Inspector says the title once (a step named like the session adds nothing).
      await card(input.echo).locator('.home-card-head').click();
      await inspector.locator('.resume-heading h1').filter({hasText: input.echo}).waitFor();
      const said = await inspector.evaluate((element, title) => ({line: element.querySelector('.resume-heading p').textContent, steps: [...element.querySelectorAll('.resume-step>header b')].map(b => b.textContent.trim()).includes(title)}), input.echo);
      assert.ok(!said.line.includes(input.echo) && !said.steps, 'the title is said once' + at + ': ' + JSON.stringify(said));
      // Two levels of one thing: a double-click enters the session; the path reads Home › <session>; the rail has one Home entry;
      // Home in the path goes up and lands on the map with that session's card selected.
      await card(input.echo).locator('.home-card-head').dblclick();
      await page.locator('.dx-home-root[data-screen="task-file"]').waitFor();
      await page.locator('.app-header .header-here').filter({hasText: input.echo}).waitFor();
      assert.equal(await page.locator('.app-rail button').filter({hasText: 'Home'}).count(), 1, 'one Home entry in the rail' + at);
      assert.equal(await page.locator('.app-rail button').filter({hasText: 'Canvas'}).count(), 1, 'the rail keeps one Canvas entry (Home and Canvas are two levels)' + at);
      await page.locator('.app-header .header-page').filter({hasText: 'Home'}).first().click();
      await map.waitFor();
      await map.locator('.home-card.sel').filter({hasText: input.echo}).waitFor();
      // The layout is one setting: change it on Home (fold or open the right dock), then it is the same in two sessions and on Home.
      const settle = () => page.waitForTimeout(450);  // the dock's easing, then the owner write
      const docks = () => page.evaluate(() => [...document.querySelectorAll('.dockws > .dock')].map(dock => [dock.classList.contains('left') ? 'left' : 'right', dock.classList.contains('col'),
        Math.round(dock.getBoundingClientRect().width), [...dock.querySelectorAll('.dtab')].map(tab => tab.dataset.tab + (tab.classList.contains('on') ? '*' : '')).join('|')]));
      const foldedRight = async () => (await docks()).some(([side, col]) => side === 'right' && col);
      const toggleRight = async () => { await page.getByRole('button', {name: await foldedRight() ? 'Open Inspector' : 'Fold the right dock to icons', exact: true}).first().click(); await settle(); };
      const before = await foldedRight();
      await map.evaluate(element => { element.dataset.mark = 'kept'; });  // a remount would drop this mark
      await toggleRight();
      const onHome = await docks();
      assert.notEqual(await foldedRight(), before, 'the right dock changed on Home' + at);
      // A layout change never touches the selection or remounts Home.
      assert.equal(await map.getAttribute('data-mark'), 'kept', 'Home is not remounted by a layout change' + at);
      await map.locator('.home-card.sel').filter({hasText: input.echo}).waitFor({timeout: 2000});
      // With a card picked it is the composer's recipient (design v61 C1-C3): the message joins its thread, Home stays, a toast offers Open.
      const composer = page.locator('.home-map-stage .global-composer'), chip = composer.locator('[data-design="composer.to"]'), sent = [];
      await page.route('**/api/router/chat', route => { sent.push(JSON.parse(route.request().postData() || '{}'));
        return route.fulfill({status: 200, contentType: 'text/event-stream', body: 'data: ' + JSON.stringify({result: {answer: 'Noted.', provider: 'BABOOM'}}) + '\n\n'}); });
      assert.equal((await chip.innerText()).trim(), input.echo, 'the picked card is the recipient' + at);
      const count = await page.evaluate(() => window.ArchHubAPI.getSnapshot().tasks.length);
      await composer.getByLabel('Message', {exact: true}).fill('Please re-check the walls');
      await composer.getByLabel('Message', {exact: true}).press('Enter');
      const toast = page.getByRole('alert').filter({hasText: 'Sent to ' + input.echo + '. It is in that session’s thread.'});
      await toast.waitFor();
      assert.deepEqual(sent.map(body => [body.task, body.prompt]), [[input.echoTask, 'Please re-check the walls']], 'one message, to the picked session' + at);
      assert.equal(await page.locator('.dx-home-root[data-screen="home"]').count(), 1, 'Home stays after a send to a picked card' + at);
      assert.equal(await page.evaluate(() => window.ArchHubAPI.getSnapshot().tasks.length), count, 'no new session' + at);
      await page.unroute('**/api/router/chat');
      // New session is an explicit pick on the chip; it does not follow to another card.
      await chip.click();
      assert.equal((await chip.innerText()).trim(), 'New session', 'New session picked' + at);
      // The toast's Open enters that session: its docks are Home's.
      await toast.getByRole('button', {name: 'Open', exact: true}).click();
      await page.locator('.app-header .header-here').filter({hasText: input.echo}).waitFor();
      await settle();
      assert.deepEqual(await docks(), onHome, "the first session has Home's layout" + at);
      await page.locator('.app-header .header-page').filter({hasText: 'Home'}).first().click();
      await card(input.other).waitFor();
      await settle();
      assert.deepEqual(await docks(), onHome, 'Home keeps its layout after a session' + at);
      // A double-click on a card that is not selected opens its own session.
      await card(input.other).locator('.home-card-head').dblclick();
      await page.locator('.app-header .header-here').filter({hasText: input.other}).waitFor();
      await settle();
      assert.deepEqual(await docks(), onHome, 'a second session has the same layout' + at);
      await page.locator('.app-header .header-page').filter({hasText: 'Home'}).first().click();
      await map.locator('.home-card.sel').filter({hasText: input.other}).waitFor();
      await settle();
      assert.deepEqual(await docks(), onHome, 'and Home again' + at);
      assert.equal((await page.locator('.home-map-stage .global-composer [data-design="composer.to"]').innerText()).trim(), input.other, 'the New session pick did not follow' + at);
      await toggleRight();  // back as it was for the next width
      assert.deepEqual(errors, [], 'no page errors' + at);
      if (input.shots) await page.screenshot({path: path.join(input.shots, 'home-' + width + '.png')});
      await context.close();
    }
    console.log('OK home map at 1009, 1440, 1920');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
