import assert from 'node:assert/strict';
import {mkdirSync} from 'node:fs';
import path from 'node:path';

export const steps = ['Logs and receipts shows the completed run of this canvas', 'Dependencies displays the package inventory returned by Check all'];

export default async function run({input, isolatedRoot, out, step, js, clickText, rectOf, mouse, until, on, cdp, shot}) {
  assert.ok(input?.qaEmail && isolatedRoot, 'An admitted isolated QA profile is required');
  const page = (fn, ...args) => js('(' + fn.toString() + ')(...' + JSON.stringify(args) + ')');
  assert.ok(await page(email => {
    const user = window.ArchHubAPI.getSnapshot().desktopAccess;
    return user.admitted && [user.email, user.subject].includes(email);
  }, input.qaEmail));
  const click = async (selector, label = '') => {
    const source = label ? '[...document.querySelectorAll(' + JSON.stringify(selector) + ')].find(e=>e.textContent.trim()===' + JSON.stringify(label) + ')' : 'document.querySelector(' + JSON.stringify(selector) + ')';
    const point = await until(async () => {
      await js(source + '?.scrollIntoView({block:"center",behavior:"instant"})');
      const p = await rectOf(source);
      return p?.w && p.h && await js(source + '?.contains(document.elementFromPoint(' + p.x + ',' + p.y + '))') ? p : null;
    }, Boolean, 20, 150);
    assert.ok(point, 'No visible control at ' + selector);
    await mouse(point);
  };

  await step(steps[0], async () => {
    const folder = path.join(isolatedRoot, 'settings-fixture', path.basename(out), 'receipts');
    mkdirSync(folder, {recursive:true});
    const file = path.join(folder, 'Receipt check.archhub');
    const node = await page(async (folder, file) => {
      const a = window.ArchHubAPI;
      await a.addWorkspace({folder});
      await a.newSession('Receipt check');
      await a.refreshLibraryPorts();
      const number = await a.addNode('n_number', {x:80, y:100});
      await a.saveSession(file);
      const doc = a.getSessionDocument();
      if (doc.nodes.length !== 1 || doc.wires.length || doc.nodes[0].type !== 'data.constant' || a.sessionPathKey(a.getSessionPath()) !== a.sessionPathKey(file)) throw Error('Expected a saved canvas with only one pure Number node');
      return number.id;
    }, folder, file);
    await click('button[data-design="header.mark"]');
    assert.ok(await clickText('App health', '[role="menuitem"]'));
    const selector = '[data-screen="receipts"]';
    assert.ok(await until(() => page(s => !!document.querySelector(s), selector), Boolean));
    const rows = () => page(s => Array.from(document.querySelectorAll(s + ' table:first-of-type tbody tr'), tr => tr.innerText.trim()), selector);
    const before = await rows();
    await shot('Logs before the Number run');
    const proof = await page(async (node, file) => {
      const a = window.ArchHubAPI, prior = await a.sessionRuns(file, 20);
      const result = await a.runNode(node);
      const latest = await a.sessionRuns(file, 20);
      return {succeeded:result.succeeded, nodeStatus:result.results?.[node]?.status, additionalRuns:latest.length-prior.length};
    }, node, file);
    assert.equal(proof.succeeded, true); assert.equal(proof.additionalRuns, 1, 'Run owner did not record exactly one new run');
    const after = await until(rows, list => list.some(row => !before.includes(row) && /run|number|receipt check/i.test(row)), 20, 150);
    const added = after.filter(row => !before.includes(row));
    const pass = added.some(row => /run|number|receipt check/i.test(row));
    return {pass, why:pass ? undefined : 'The saved canvas has a completed Number run, but Logs and receipts shows no new run row',
      got:{...proof, rowsBefore:before.length, rowsAfter:after.length, newVisibleRun:pass}};
  });

  await step(steps[1], async () => {
    await click('nav button[aria-label="Settings"]');
    await click('nav[aria-label="Settings categories"] button[aria-label="This PC"]');
    await click('[data-settings-full] button','Open dependencies');
    const contents = () => page(() => {
      const root = document.querySelector('[data-screen="dependencies"]');
      return root && {ready:Number([...root.querySelectorAll('.dependency-metric')].find(e=>e.querySelector('span.muted')?.textContent==='Ready')?.querySelector('b')?.textContent),
        names:[...root.querySelectorAll('.package-summary .fill b')].map(e=>e.textContent.trim()).sort()};
    });
    const before = await until(contents, Boolean);
    assert.ok(before && Number.isFinite(before.ready), 'Dependencies did not show its Ready count');
    await shot('Dependencies before package check');
    let requestId, status, inventory, lookupError;
    on('Network.requestWillBeSent', e => {
      if (new URL(e.request.url).pathname !== '/api/universal/settings-action') return;
      try {
        if (JSON.parse(e.request.postData ?? '{}').function === 'checkDependencies') requestId=e.requestId;
      } catch {
        lookupError = 'The settings action request could not be decoded';
      }
    });
    on('Network.responseReceived', e => { if (requestId && e.requestId===requestId) status=e.response.status; });
    on('Network.loadingFinished', async e => {
      if (!requestId || e.requestId !== requestId) return;
      try {
        const {result} = await cdp('Network.getResponseBody', {requestId});
        const body = result.base64Encoded ? Buffer.from(result.body,'base64').toString('utf8') : result.body;
        const response = JSON.parse(body), packages = response.result?.dependencies;
        if (!Array.isArray(packages)) {
          const code = /^[a-z0-9_-]{1,64}$/i.test(response.code || '') ? ' ('+response.code+')' : '';
          throw Error('The package owner returned HTTP '+status+code+' without an inventory');
        }
        inventory = {ready:packages.filter(p=>p.state==='Ready').length, names:packages.map(p=>p.name).sort()};
      } catch(error) { lookupError=error.message; }
    });
    assert.ok(await clickText('Check all'));
    await until(async () => inventory || lookupError, Boolean, 140, 300);
    if (!inventory) return {not_exercised:lookupError || 'The package inventory did not finish within the readback window',got:{before}};
    const after = await until(contents, v => v?.names.length === inventory.names.length, 20, 150);
    assert.deepEqual(after, inventory, 'Displayed agent packages disagree with their package owner');
    return {pass:true,got:{before,after,owner:inventory}};
  });
}
