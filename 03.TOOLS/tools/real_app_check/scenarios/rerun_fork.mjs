import fs from 'node:fs';
import path from 'node:path';

export const steps = ['Rerun Number from its node menu', 'Rerun Number from its Inspector', 'Fork Number, save and reopen'];

export default async function ({step, js, until, clickText, cdp, on, rectOf, mouse, out}) {
  const fixture = path.join(out, 'rerun-fork.archhub');
  let docId, numberId, convertId;
  const openFixture = async () => {
    if (fs.existsSync(fixture)) throw Error('Canvas fixture already exists');
    if (!await until(() => js('Boolean(window.ArchHubAPI && !document.getElementById("studio-boot"))'), Boolean))
      throw Error('Installed Studio did not finish opening');
    await clickText('Canvas');
    const created = await js(`(async () => {
      const api = window.ArchHubAPI;
      await api.newSession('Rerun and Fork');
      const number = await api.addNode('n_number', {x:100,y:180});
      const convert = await api.addNode('data.convert', {x:450,y:180});
      await api.setNodeParam(number.id, 'value', 31);
      await api.connectSockets({from:number.id, fromPort:'value', to:convert.id, toPort:'in'});
      await api.saveSession(${JSON.stringify(fixture)});
      return {id:api.getSessionDocument().id, number:number.id, convert:convert.id};
    })()`);
    docId = created.id;
    numberId = created.number;
    convertId = created.convert;
    await js(`window.ArchHubAPI.openSession(${JSON.stringify(fixture)})`);
    await clickText('Overview') || await clickText('Fit');
    if (!await js(`window.ArchHubAPI.getSessionDocument().id === ${JSON.stringify(docId)}`))
      throw Error('Installed file owner did not open the synthetic document');
  };
  const exchange = [], byId = new Map();
  const settingsRequests = new Set(), settingsFailures = [];
  const knownFunctions = new Set([
    'readPreferences', 'readEffectivePreferences', 'setAppearance', 'resetAppearance', 'setSettingsScope',
    'exportPreferences', 'importPreferences', 'resetPreferences', 'setKeybinding', 'resetKeybindings',
    'readControls', 'readKeybindings', 'readCanvasTabs', 'setCanvasTabs', 'readDockLayout', 'setDockLayout',
    'readLibraryCollapsed', 'setLibraryCollapsed', 'readOperations', 'readSessionsFolder', 'readApplicationSettings',
  ]);
  const checkedStep = async (label, check) => {
    const first = settingsFailures.length;
    const row = await step(label, check);
    const failures = settingsFailures.slice(first);
    if (!failures.length) return;
    row.settings_errors = await Promise.all(failures.map(async ({requestId, status}) => {
      const diagnostic = {function:'unknown', status, reason:'unknown'};
      try {
        const {result} = await cdp('Network.getRequestPostData', {requestId});
        const name = JSON.parse(result.postData).function;
        if (knownFunctions.has(name)) diagnostic.function = name;
      } catch (error) {
        diagnostic.function = error instanceof SyntaxError ? 'request_invalid_json' : 'request_unavailable';
      }
      try {
        const {result} = await cdp('Network.getResponseBody', {requestId});
        const body = JSON.parse(result.base64Encoded ? Buffer.from(result.body, 'base64').toString() : result.body);
        if (body.code === 'settings_destination_changed') diagnostic.reason = body.code;
      } catch (error) {
        diagnostic.reason = error instanceof SyntaxError ? 'response_invalid_json' : 'response_unavailable';
      }
      return diagnostic;
    }));
  };
  on('Network.requestWillBeSent', async ({requestId, request}) => {
    if (request.method !== 'POST') return;
    const route = new URL(request.url).pathname;
    if (route === '/api/universal/settings-action') settingsRequests.add(requestId);
    if (route !== '/api/session-files') return;
    const row = {requestId};
    exchange.push(row);
    byId.set(requestId, row);
    try {
      const data = request.postData ?? (await cdp('Network.getRequestPostData', {requestId})).result.postData;
      const body = JSON.parse(data);
      if (body.path === fixture && body.document?.id === docId && body.action === 'run') {
        Object.assign(row, {action:'run', again:body.again, roots:body.roots});
      }
    } catch { row.error = 'request body unavailable or invalid'; }
  });
  on('Network.responseReceived', ({requestId, response}) => {
    if (settingsRequests.delete(requestId) && response.status >= 400)
      settingsFailures.push({requestId, status:response.status});
    if (byId.has(requestId)) byId.get(requestId).http = response.status;
  });
  on('Network.loadingFailed', ({requestId}) => settingsRequests.delete(requestId));
  on('Network.loadingFinished', ({requestId}) => {
    if (byId.has(requestId)) byId.get(requestId).finished = true;
  });
  const at = selector => until(() => rectOf(`[...document.querySelectorAll(${JSON.stringify(selector)})].find(e=>e.getClientRects().length)`), p => p?.w && p.h, 25, 200);
  const click = async selector => {
    const point = await at(selector);
    if (!point?.w || !point.h) throw Error('Control missing: ' + selector);
    await mouse(point);
  };
  const title = () => `.react-flow__node[data-id=${JSON.stringify(numberId)}] [data-node-card-title]`;
  const inspector = () => `[data-node-inspector=${JSON.stringify(numberId)}]`;
  const rerun = async selector => {
    const first = exchange.length;
    await click(selector);
    const entry = await until(() => exchange.slice(first).find(r => r.action === 'run' && r.finished), Boolean);
    if (!entry) return {pass:false, got:{unreadable_requests:exchange.slice(first).filter(row=>row.error).length}, why:'No completed run request for the synthetic file'};
    const {requestId, again, roots, http} = entry;
    const request = {again, roots, http};
    const {result} = await cdp('Network.getResponseBody', {requestId});
    const payload = JSON.parse(result.base64Encoded ? Buffer.from(result.body, 'base64').toString() : result.body);
    const actual = (payload.results || payload.result?.results)?.[numberId];
    const visible = await until(() => js(`window.ArchHubAPI.getSessionDocument().nodes.find(n=>n.id===${JSON.stringify(numberId)})?.result`),
                                value => actual && value?.status === actual.status);
    const pass = exchange.slice(first).filter(r=>r.action==='run').length === 1 && request.http === 200 && request.again === true
      && request.roots?.length === 1 && request.roots[0] === numberId && ['Done','Solved'].includes(actual?.status)
      && actual.output?.value === 31 && visible?.status === actual.status && JSON.stringify(visible.output) === JSON.stringify(actual.output);
    return {pass, got:{interaction_pass:pass, request, actual, visible}, why:pass ? '' : 'Rerun request, owner result or Canvas result differs'};
  };
  await checkedStep(steps[0], async () => {
    await openFixture();
    const point = await at(title());
    if (!point?.w) throw Error('Number card is missing on the installed Canvas');
    await mouse(point, 'right');
    return rerun('[role="menu"][aria-label="Node menu"] [data-design="menu.rerun"]');
  });
  const openInspector = async () => {
    if (await js(`Boolean(document.querySelector(${JSON.stringify(inspector() + ' [data-command]')})?.getClientRects().length)`)) return;
    const point = await at(title());
    if (!point?.w) throw Error('Number card is missing from Canvas');
    await mouse(point);
    await mouse(point, 'left', 2);
    if (!await until(() => clickText('Open properties', '[role="dialog"] button'), Boolean, 20, 200))
      throw Error('Node dialog did not offer Open properties');
    await clickText('Close dialog', '[role="dialog"] button');
    await clickText('Open Inspector');
  };
  await checkedStep(steps[1], async () => {
    await openInspector();
    return rerun(inspector() + ' [data-command="menu.rerun"]');
  });
  await checkedStep(steps[2], async () => {
    await openInspector();
    const ids = () => js('window.ArchHubAPI.getSessionDocument().nodes.map(n=>n.id).sort()');
    const before = await ids();
    if (!before.includes(numberId) || !before.includes(convertId)) return {pass:false, got:before, why:'Original nodes missing'};
    await click(inspector() + ' [data-command="menu.fork"]');
    const after = await until(ids, values => values.length === before.length + 1);
    const added = after.filter(id => !before.includes(id));
    if (after.length !== before.length + 1 || added.length !== 1 || !before.every(id => after.includes(id)))
      return {pass:false, got:{before,after}, why:'Fork did not preserve the original nodes and add one node'};
    await js(`window.ArchHubAPI.saveSession(${JSON.stringify(fixture)})`);
    const saved = JSON.parse(fs.readFileSync(fixture, 'utf8')).nodes.map(n=>n.id).sort();
    await js('window.ArchHubAPI.newSession()');
    if ((await ids()).length) return {pass:false, why:'Canvas did not clear before reopening'};
    await js(`window.ArchHubAPI.openSession(${JSON.stringify(fixture)})`);
    const reopened = await ids();
    const pass = [saved, reopened].every(values => JSON.stringify(values) === JSON.stringify(after));
    return {pass, got:{interaction_pass:pass, before, added, saved, reopened}, why:pass ? '' : 'Saved or reopened node IDs differ'};
  });
}
