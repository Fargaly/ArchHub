'use strict';
// Browser plugin not available: regular Playwright, isolated replica HTTP owner.
// Never launches the installed desktop application or a host application.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const enabled = !!process.env.LAZYBOOT_HTTP_URL;
const root = path.resolve(__dirname, '..');
const report = enabled ? JSON.parse(fs.readFileSync(path.resolve(root, process.env.LAZYBOOT_COLD_REPORT), 'utf8')) : null;

async function desktop(run) {
  const base = process.env.LAZYBOOT_HTTP_URL;
  assert.match(base, /^http:\/\/127\.0\.0\.1:\d+\/?$/, 'only the isolated replica owner is admitted');
  const browser = await chromium.launch({headless:true});
  let context;
  try {
    context = await browser.newContext({viewport:{width:1440, height:1000}, extraHTTPHeaders:{
      'X-ArchHub-Session':process.env.LAZYBOOT_HTTP_TOKEN,
      'X-ArchHub-CSRF':process.env.LAZYBOOT_HTTP_CSRF,
    }});
    const errors = [], requests = [];
    await context.route('**/*', route => {
      const url = new URL(route.request().url());
      return url.origin === new URL(base).origin ? route.continue() : route.abort('blockedbyclient');
    });
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => requests.push({url:new URL(request.url()).pathname, method:request.method(), body:request.postData()}));
    const response = await page.goto(base.replace(/\/$/, '') + '/studio', {waitUntil:'domcontentloaded'});
    assert.equal(response.status(), 200);
    await page.locator('#studio-boot').waitFor({state:'detached', timeout:15000});
    await page.locator('[data-rail-panel="Library"]').waitFor();
    await run({page, requests});
    assert.deepEqual(errors, [], 'rendered Studio has no browser runtime errors');
  } finally {
    try {await context?.close();} finally {await browser.close();}
  }
}

test('desktop browser: cold rail Skills renders the admitted catalogue', {skip:!enabled}, async () => {
  await desktop(async ({page, requests}) => {
    assert.equal(requests.filter(row => row.url === '/api/universal/skills').length, 0, 'Home leaves Skills cold');
    await page.locator('[data-rail-panel="Library"]').click();
    await page.locator('[data-library-tab="skills"]').first().click();
    await page.locator('[data-skills-count]').filter({hasText:'SAVED'}).waitFor();
    for (const row of report.skills.result) await page.getByText(row.name, {exact:true}).waitFor();
    assert.doesNotMatch(await page.locator('body').innerText(), /Loading catalogue|READING/);
    const reads = requests.filter(row => row.url === '/api/universal/skills');
    assert.equal(reads.length, 1);
    assert.equal(reads[0].method, 'POST');
    assert.deepEqual(JSON.parse(reads[0].body), {want:'catalogue'});
    await page.screenshot({path:path.join(root, 'evidence/lazyboot/round3-skills-browser.png')});
  });
});

test('desktop browser: Home, status, Hosts and About share one total', {skip:!enabled}, async () => {
  await desktop(async ({page}) => {
    const hosts = report.hosts.connectors.filter(row => !!row.drive);
    const ratio = hosts.filter(row => ['connected', 'listening'].includes(row.state)).length + '/' + hosts.length;
    await page.locator('[data-tool-card="connectors"]').filter({hasText:ratio + ' hosts running'}).waitFor();
    assert.ok((await page.locator('body').innerText()).includes(ratio + ' hosts'), 'status agrees with Home');
    await page.locator('button[title="Settings"]').click();
    const dialog = page.getByRole('dialog', {name:'Settings', exact:true});
    await dialog.waitFor();
    await dialog.locator('[data-settings54-group-title]').filter({hasText:/^Connections$/}).click();
    const hostsTab = dialog.locator('[data-settings54-capability-nav] button').filter({hasText:/^Hosts/});
    await dialog.locator('[data-settings-host-total]').filter({hasText:ratio + ' running'}).waitFor();
    await hostsTab.click();
    await dialog.locator('[data-host-total]').waitFor();
    assert.equal(await dialog.locator('[data-host-total]').getAttribute('data-host-total'), String(hosts.length));
    await page.screenshot({path:path.join(root, 'evidence/lazyboot/round3-hosts-panel-browser.png')});
    await dialog.locator('[data-settings54-group-title]').filter({hasText:/^Storage & About$/}).click();
    await dialog.locator('[data-settings54-capability-nav] button').filter({hasText:/^About$/}).click();
    await dialog.locator('[data-about-host-total]').waitFor();
    assert.equal(await dialog.locator('[data-about-host-total]').getAttribute('data-about-host-total'), String(hosts.length));
    await page.screenshot({path:path.join(root, 'evidence/lazyboot/round3-hosts-browser.png')});
  });
});

test('desktop browser: group created after lazy boot renders chips and permits real pointer drag-out', {skip:!enabled}, async () => {
  await desktop(async ({page}) => {
    const graph = report.graphs.graphs.find(row => row.id === report.graphs.current_graph);
    await page.locator('[data-home-page] button').filter({has:page.getByText(graph.title, {exact:true})}).click();
    const canvas = page.getByRole('region', {name:'Workflow canvas', exact:true});
    await canvas.waitFor();
    const roots = [report.created_group.root, report.created_group.members[0]];
    const created = await page.evaluate(async roots => {
      const owner = window.ARCHHUB_EXISTING_WORKSHOP;
      await owner.composeTopology('group', roots);
      return owner.getSnapshot().topology.canvas.nodes.find(node => node.composition &&
        roots.every(id => node.members?.some(member => member.id === id)));
    }, roots);
    assert.ok(created, 'real create receipt and refreshed projection include group members');
    const card = page.locator('.lm-node[data-node-id="' + created.id + '"]');
    await card.locator('[data-member-chip]').nth(roots.length - 1).waitFor();
    assert.equal(await card.locator('[data-member-chip]').count(), roots.length);
    await page.screenshot({path:path.join(root, 'evidence/lazyboot/round3-group-chips-browser.png')});
    const member = roots[1], chip = card.locator('[data-member-chip="' + member + '"]');
    const from = await chip.boundingBox(), bounds = await canvas.boundingBox();
    assert.ok(from && bounds, 'newly rendered member chip has real browser geometry');
    await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
    await page.mouse.down();
    await page.mouse.move(bounds.x + bounds.width - 70, bounds.y + bounds.height - 70, {steps:12});
    await page.mouse.up();
    await page.waitForFunction(member => window.ARCHHUB_EXISTING_WORKSHOP.getSnapshot().topology.canvas.nodes.some(node => node.id === member), member);
    await chip.waitFor({state:'detached'});
    await page.screenshot({path:path.join(root, 'evidence/lazyboot/round3-group-dragout-browser.png')});
    await page.waitForFunction(() => !window.ARCHHUB_EXISTING_WORKSHOP.getSnapshot().topology.pending);
    await page.evaluate(root => window.ARCHHUB_EXISTING_WORKSHOP.composeTopology('ungroup', [root]), created.id);
  });
});
