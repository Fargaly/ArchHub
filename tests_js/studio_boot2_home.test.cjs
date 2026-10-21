'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio-authority.js'), 'utf8');
const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/clean-canvas-fresh-runtime.json'), 'utf8'));

test('clean Studio boot requests Home metadata and defers the full graph until open', async () => {
  const reads = [], writes = [];
  const home = {ok:true, projection:'home', revision:fixture.revision, graph_id:fixture.graph_id,
    application_root:fixture.application_root, root:fixture.root,
    scope:{current:fixture.root, current_label:fixture.scope.current_label},
    authorization:{subject:fixture.authorization.subject, session:fixture.authorization.browser_sessions[0].root},
    nodes:[], wires:[], catalog:[], selected:[],
    warmup:{state:'almost_ready', message:'Almost ready — preparing your tools.'}};
  const session = {token:'boot2-session', csrf:'boot2-csrf'};
  const context = vm.createContext({URLSearchParams, crypto:require('node:crypto').webcrypto,
    sessionStorage:{getItem:() => JSON.stringify(session), setItem() {}, removeItem() {}},
    fetch:async (url, options = {}) => {
      reads.push(url);
      if (options.method === 'POST') writes.push(url);
      if (url === '/api/universal/boot') return {ok:true, status:200, json:async () => home.warmup};
      if (url === '/api/universal/canvas?screen=home') return {ok:true, status:200, json:async () => home};
      if (url === '/api/universal/canvas') return {ok:true, status:200, json:async () => fixture};
      throw new Error('unexpected request: ' + url);
    }});
  vm.runInContext(source, context);
  const api = await context.ArchHubStudioAuthority.boot({canvas_key:'fixture-key'});
  assert.equal(api.getSnapshot().canvas.projection, 'home');
  assert.equal(reads.includes('/api/universal/canvas'), false, 'opening Home never projects the graph');
  assert.equal(writes.length, 0, 'held session boot is read only');
  await api.load();
  assert.equal(api.getSnapshot().graph.nodes.length, fixture.nodes.length + 1);
  assert.equal(reads.at(-1), '/api/universal/canvas');
});

test('Home readiness banner follows actual warm-up, including a terminal refusal', async () => {
  const {JSDOM} = await import('jsdom');
  const html = fs.readFileSync(path.join(__dirname, '../nodelang/studio/studio.html'), 'utf8');
  const dom = new JSDOM(html, {url:'http://127.0.0.1:53914/', runScripts:'outside-only'});
  const win = dom.window;
  const progress = [
    {state:'almost_ready', message:'Almost ready — preparing your tools.'},
    {state:'failed', message:'Some tools are unavailable. Reopen ArchHub to try again.'},
  ];
  win.__archhubSession = {token:'fixture', csrf:'fixture-csrf'};
  const requests = [];
  win.fetch = async (url, options) => {
    requests.push({url, options});
    return {ok:true, json:async () => progress.shift()};
  };
  // Execute the shipped readiness controller with a fake clock and real DOM.
  const scripts = [...win.document.querySelectorAll('script:not([src])')];
  const controller = scripts.find(tag => tag.textContent.includes('function watchRuntimeReadiness'));
  assert.ok(controller, 'shipped page owns the readiness controller');
  const pending = [];
  win.setTimeout = fn => {pending.push(fn); return pending.length;};
  try {
    win.eval(controller.textContent);
    await win.watchRuntimeReadiness();
    const status = win.document.getElementById('studio-ready-status');
    assert.equal(status.hidden, false);
    assert.match(status.textContent, /Almost ready/);
    assert.equal(pending.length, 1);
    await pending.shift()();
    assert.match(status.textContent, /unavailable/);
    assert.equal(pending.length, 0, 'no endless polling after a refusal');
    assert.equal(requests[0].options.headers['X-ArchHub-Session'], 'fixture');
  } finally {dom.window.close();}
});
