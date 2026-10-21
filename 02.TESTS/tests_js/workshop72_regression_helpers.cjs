/* Mounted DSYS-072 regression support. Fixtures are fake transports, never app state. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createHash} = require('node:crypto');
const root = path.resolve(__dirname, '..', '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const text = el => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');
const plain = value => JSON.parse(JSON.stringify(value));

function transport(options = {}) {
  const context = vm.createContext({URLSearchParams, TextEncoder});
  vm.runInContext(read('01.APP/nodelang/studio/studio-existing-workshop.js'), context);
  const posts = [], gets = [], storage = new Map();
  let sequence = 0;
  const transcript = {graph_id:'graph-a', root:'room-a', scope_root:'scope-a', revision:4,
    owner:'owner-a', view:'view-a', self:'owner-a', can_send:true, can_join:false, messages:[],
    participants:[{root:'owner-a', label:'Owner', attached:true}, {root:'agent-a', label:'Claude Code', attached:true, connected:true}]};
  const api = context.ArchHubExistingWorkshop.create({
    pendingStorage:{getItem:key => storage.get(key) || null, setItem:(key,value) => storage.set(key,value)},
    uuid:() => 'request-' + (++sequence), hash:async value => createHash('sha256').update(value).digest('hex'),
    get:async url => { gets.push(url); return options.get ? options.get(url, transcript) : transcript; },
    post:async (url,body) => { posts.push({url,body:plain(body)}); return options.post ? options.post(url, body) :
      {ok:true, workshop:body.root, root:'entry-a', idempotency_key:body.idempotency_key, revision:5}; },
  });
  api.setCanvas({graph_id:'graph-a', root:'scope-a', revision:4,
    workshops:[{root:'room-a', label:'Workshop', send_category:'declared-message'}]});
  return {api, posts, gets, transcript};
}

async function mounted(state, authority, extra = {}) {
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1/', pretendToBeVisual:true});
  const oldWindow = global.window, oldDocument = global.document;
  global.window = dom.window; global.document = dom.window.document; global.IS_REACT_ACT_ENVIRONMENT = true;
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const win = dom.window;
  const context = vm.createContext({React, window:win, document:win.document, setTimeout, clearTimeout, console,
    URL, Blob, TextEncoder, CustomEvent:win.CustomEvent, AbortController:win.AbortController, fetch:(...args) => win.fetch(...args)});
  vm.runInContext(read('01.APP/nodelang/studio/tokens.jsx'), context);
  for (const source of ['ds/index.jsx','workshop-board.jsx','shared-data.jsx','studio-workshop.jsx']) {
    vm.runInContext(transformSync(read('01.APP/nodelang/studio/' + source), {loader:'jsx'}).code, context);
  }
  win.ARCHHUB_EXISTING_WORKSHOP = authority;
  const rootEl = createRoot(win.document.getElementById('root'));
  const act = async fn => { await React.act(async () => { await fn(); }); };
  const {sel:initialSelection, setSel:selectSpy, target:initialTarget, ...overrides} = extra;
  let selection = initialSelection || {agent:null, task:null}, target = initialTarget || '';
  const props = () => ({state, descriptor:state.workshops[0], target,
    setTarget:value => { target = value; }, setMode:() => {}, setFocusId:() => {}, onLeave:() => {},
    sel:selection, setSel:value => { selection = value; selectSpy?.(value); }, ...overrides});
  const render = () => act(() => rootEl.render(React.createElement(win.WorkshopView, props())));
  await render();
  const click = async el => { assert.ok(el, 'the live control must exist'); await act(() => el.click()); await render(); };
  const input = async value => act(() => {
    const el = win.document.querySelector('textarea[aria-label="Workshop message"]');
    assert.ok(el, 'one Workshop composer');
    Object.getOwnPropertyDescriptor(win.HTMLTextAreaElement.prototype, 'value').set.call(el, value);
    el.dispatchEvent(new win.Event('input', {bubbles:true}));
  });
  return {win, doc:win.document, act, click, input, render,
    selection:() => selection, target:() => target,
    button:label => [...win.document.querySelectorAll('button')].find(el => text(el) === label),
    close:async () => { await act(() => rootEl.unmount()); win.close();
      global.window = oldWindow; global.document = oldDocument; delete global.IS_REACT_ACT_ENVIRONMENT; }};
}

module.exports = {root, read, text, plain, transport, mounted};
