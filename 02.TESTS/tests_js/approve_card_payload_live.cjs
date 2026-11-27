// APPROVEPAYLOAD: a held Post's Approve card shows where it goes, what it says and what it attaches, and
// "Review on the node" opens the agent's session canvas with the held node selected. Compiled Studio, real
// owners, a seeded isolated Workshop. Driven by 02.TESTS/tests/test_approve_payload.py.
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
    page.on('pageerror', error => errors.push(error.message));
    const shot = async (name, target) => { if (input.shots) await target.screenshot({path: path.join(input.shots, name + '.png')}); };
    // The disposable server has no cloud account: the signed-in UI is exercised with a test-only account response.
    await page.route('**/api/universal/desktop-access', route => route.fulfill({
      json: {ok: true, admitted: true, state: 'admitted', subject: 'payload-test', email: 'payload@example.test'}}));
    await page.goto(input.url);
    await page.waitForFunction(ids => ids.every(id => window.ArchHubAPI?.getSnapshot().approvals?.some(card => card.id === id)), [input.post, input.push, input.empty]);
    // The bell lists every held action; "Review · <title>" opens its Approve card (the n-th of that title, in list order).
    const open = async id => {
      const pending = await page.evaluate(() => window.ArchHubAPI.getSnapshot().approvals.filter(c => ['pending', 'postponed', 'stale', 'refused', 'contested'].includes(c.status)).map(c => [c.id, c.title]));
      const title = pending.find(([key]) => key === id)[1], nth = pending.filter(([, t]) => t === title).findIndex(([key]) => key === id);
      await page.locator('button[aria-label="Notifications"]').first().click();
      await page.getByRole('dialog', {name: 'Notifications'}).getByRole('button', {name: 'Review · ' + title, exact: true}).nth(nth).click();
      const card = page.locator('section[role="dialog"][aria-modal="true"] [data-ask-card][data-approval="' + id + '"]');
      await card.waitFor();
      return card;
    };
    const close = () => page.locator('section[role="dialog"][aria-modal="true"]').getByRole('button', {name: 'Close dialog'}).click();

    // The LinkedIn post: destination, the full text, the attachments, why, Undo, then the four actions.
    const post = await open(input.post);
    const said = await post.innerText();
    for (const words of ['Needs your approval · requested by Claude', 'Door schedule release', 'LinkedIn · ArchHub page', 'Door schedule is out for review', 'plan-level-2.png', 'issue-sheet.pdf', 'Undo', 'Review on the node', 'Approve', 'Ask why', 'Reject'])
      assert.ok(said.includes(words), 'the post card says ' + words + ': ' + said);
    assert.ok(!said.includes('sk-proof'), 'a secret never reaches the card');
    assert.equal(await post.getByRole('button', {name: /^Approve/}).isDisabled(), false);
    await shot('01-post-card', post);
    await close();

    // The held git push (the defect): Post, the remote and branch, the command.
    const push = await open(input.push);
    const pushed = await push.innerText();
    for (const words of ['Push to ' + input.repository + ' main', 'Door schedule release', input.repository + ', branch main','git push -q origin HEAD:main', 'Review on the node'])
      assert.ok(pushed.includes(words), 'the push card says ' + words + ': ' + pushed);
    await shot('02-push-card', push);
    await close();

    // A held send with nothing in it: the card says so and Approve cannot be pressed.
    const empty = await open(input.empty);
    assert.ok((await empty.innerText()).includes('Nothing to review: the request carried no content'));
    assert.equal(await empty.getByRole('button', {name: /^Approve/}).isDisabled(), true);
    await shot('03-empty-card', empty);
    await close();

    // Review on the node: the session canvas, the held node selected, its inspector showing the same Approve card.
    const again = await open(input.post);
    await again.getByRole('button', {name: 'Review on the node'}).click();
    const canvas = page.getByLabel('Workflow canvas', {exact: true});
    await canvas.locator('.react-flow__node[data-id="' + input.node + '"]').waitFor({state: 'attached'});
    await page.waitForFunction(id => document.querySelector('.react-flow__node[data-id="' + id + '"]')?.classList.contains('selected'), input.node);
    await page.waitForTimeout(800);
    await shot('04-review-on-the-node', page);
    const inspector = await page.evaluate(() => [...document.querySelectorAll('[data-dock-panel], [data-slot]')].map(el => (el.getAttribute('aria-label') || '') + ':' + (el.innerText || '').slice(0, 80)).join(' | '));
    const inInspector = page.locator('.shared-properties-selection [data-ask-card][data-approval="' + input.post + '"]');
    assert.ok(await inInspector.count(), 'the inspector shows the Approve card: ' + inspector);
    await shot('05-inspector-card-beside-design-00', inInspector);
    assert.deepEqual(errors, []);
    console.log('APPROVEPAYLOAD OK');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.stack || error.message); process.exit(1); });
