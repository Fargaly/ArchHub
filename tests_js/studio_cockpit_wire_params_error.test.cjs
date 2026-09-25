/* The cockpit's wire inspector draws the server's wire rows. When the list cannot be read (no session,
   a refused or failed request), the panel says why instead of drawing an empty WIRE PARAMETERS block.
   Runs the real cockpit.html boot script and the real atlas-panels.jsx WirePanel through the vendored Babel. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const studio = path.join(__dirname, '../nodelang/studio');
const html = fs.readFileSync(path.join(studio, 'cockpit.html'), 'utf8');
const bootScript = html.slice(html.indexOf('<script>') + '<script>'.length, html.indexOf('</script>'));

function bootCockpit(session, fetchImpl) {
  const window = {fetch: fetchImpl};
  const context = vm.createContext({window, fetch: fetchImpl, Error, Array, String, JSON});
  vm.runInContext(bootScript.replace('/*__ARCHHUB_BOOT__*/ null', JSON.stringify(session)), context);
  return window;
}

function renderWirePanel(window) {
  const Babel = {};
  vm.runInNewContext(fs.readFileSync(path.join(studio, 'vendor/babel.js'), 'utf8'), {exports: Babel, module: {exports: Babel}});
  const code = Babel.transform(fs.readFileSync(path.join(studio, 'atlas-panels.jsx'), 'utf8'), {presets: ['env', 'react']}).code;
  const any = new Proxy(function () { return null; }, {get: (_t, key) => key === Symbol.toPrimitive ? () => 'x' : any});
  const React = {createElement: (type, props, ...children) => ({type, props: props || {}, children}), Fragment: 'frag', useState: v => [v, () => {}], useEffect: () => {}, useRef: v => ({current: v}), useMemo: f => f()};
  const box = Object.assign(window, {React, HB: any, hsc: any, HBtn: any, HIconBtn: any, HPill: any, HDot: any, HAvatar: any, STC: any, catCol: any, CKIcon: any});
  const context = vm.createContext(Object.assign({window: box, React, console}, box));
  vm.runInContext(code, context);
  const tree = box.WirePanel({M: {nodes: [], domains: [], wires: []}, w: {a: 'x', b: 'y', da: 'x', db: 'y'}});
  const text = [];
  const walk = node => {
    if (node == null || node === false || node === true) return;
    if (Array.isArray(node)) return node.forEach(walk);
    if (typeof node !== 'object') { text.push(String(node)); return; }
    walk(node.children);
  };
  walk(tree);
  return text.join('');
}

test('a refused node-library read names its reason in the wire panel', async () => {
  const window = bootCockpit({token: 't', csrf: 'c'}, async () => ({ok: false, status: 403, json: async () => ({ok: false, error: 'browser session is required'})}));
  await window.ARCHHUB_WIRE_PARAMS_LOAD;
  assert.equal(window.WIRE_PARAMS.length, 0);
  assert.equal(window.WIRE_PARAMS_ERROR, 'browser session is required');
  assert.match(renderWirePanel(window), /Wire parameters could not be loaded: browser session is required/);
});

test('a network failure and a missing session are both said, never an empty panel', async () => {
  const offline = bootCockpit({token: 't', csrf: 'c'}, async () => { throw new Error('network down'); });
  await offline.ARCHHUB_WIRE_PARAMS_LOAD;
  assert.match(renderWirePanel(offline), /Wire parameters could not be loaded: network down/);
  const signedOut = bootCockpit(null, async () => { throw new Error('must not fetch'); });
  assert.equal(signedOut.WIRE_PARAMS_ERROR, 'this page has no signed-in session');
  assert.match(renderWirePanel(signedOut), /Wire parameters could not be loaded: this page has no signed-in session/);
});

test('served rows are drawn and no error is shown', async () => {
  const rows = [{k: 'enabled', label: 'Enabled', type: 'toggle', def: true}];
  const window = bootCockpit({token: 't', csrf: 'c'}, async () => ({ok: true, status: 200, json: async () => ({ok: true, wire_parameters: rows})}));
  await window.ARCHHUB_WIRE_PARAMS_LOAD;
  assert.equal(window.WIRE_PARAMS_ERROR, '');
  assert.doesNotMatch(renderWirePanel(window), /could not be loaded/);
});