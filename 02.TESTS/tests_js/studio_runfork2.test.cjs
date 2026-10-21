/* Mounted RUNFORK2 courts. Production components; fake transports, no live app. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const React = require('react');
const {createRoot} = require('react-dom/client');
const {transformSync} = require('esbuild');
const studio = path.join(__dirname, '../../01.APP/nodelang/studio');
// A bounded two-file baseline extraction can run this exact court against the starting tree.
const read = name => fs.readFileSync(path.join(process.env.ARCHHUB_RUNFORK2_SOURCE &&
  ['studio-lm.jsx','studio-params.jsx'].includes(name) ? process.env.ARCHHUB_RUNFORK2_SOURCE : studio, name), 'utf8');
const source = read('studio-lm.jsx');
function slice(from, to) {
  const start = source.indexOf(from), end = source.indexOf(to, start);
  assert.ok(start >= 0 && end > start, from);
  return source.slice(start, end);
}
const tokens = () => new Proxy({}, {get:(_, key) => ['rad','sp'].includes(key)
  ? new Proxy({}, {get:() => 4}) : key === 'fs' ? {dataSm:{sz:11}} : '#555555'});
async function mount(code, extras = {}) {
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53918/'});
  const win = dom.window, previous = [globalThis.window, globalThis.document, globalThis.IS_REACT_ACT_ENVIRONMENT];
  globalThis.window = win; globalThis.document = win.document; globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const LM = tokens(); win.AH = LM; win.PM = LM;
  win.PM_TYPES = {text:{wire:false, label:'Text'}}; win.PM_WIRE = {};
  win.pmType = () => win.PM_TYPES.text; win.Socket = () => null;
  win.ArchHubTheme = {derive:fn => fn(LM)};
  const context = vm.createContext({React, LM, window:win, document:win.document,
    setTimeout, clearTimeout, console, ...extras});
  vm.runInContext(transformSync(read('ds/index.jsx'), {loader:'jsx', format:'cjs'}).code, context);
  vm.runInContext(transformSync(code, {loader:'jsx', format:'cjs'}).code, context);
  const root = createRoot(win.document.getElementById('root'));
  const act = fn => React.act(async () => { await fn(); });
  return {win, context, doc:win.document, act,
    render:props => act(() => root.render(React.createElement(context.Component, props))),
    click:node => act(() => { assert.ok(node, 'mounted control exists'); node.click(); }),
    close:async () => { await act(() => root.unmount()); win.close();
      [globalThis.window, globalThis.document, globalThis.IS_REACT_ACT_ENVIRONMENT] = previous; }};
}
const buttons = doc => [...doc.querySelectorAll('button')];

for (const libraryMode of [false, true]) for (const outcome of ['result', 'refused', 'missing-output']) {
test('item 1: ' + (libraryMode ? 'Library' : 'Canvas') + ' Rerun uses the signed run path and Runs shows ' + outcome, async () => {
  const params = read('studio-params.jsx');
  const runOwner = read('studio-authority.js');
  const start = runOwner.indexOf('    let running = null;');
  const end = runOwner.indexOf('    global.ARCHHUB_RETRACT', start);
  assert.ok(start > 0 && end > start);
  let resolveRun, rejectRun;
  const pending = new Promise((resolve, reject) => { resolveRun = resolve; rejectRun = reject; });
  const calls = [];
  const v = await mount(params + '\n' +
    slice('const useWorkshopProjection =', 'const studioCanvasScope =') +
    slice('const isWorkshopGraphNode =', 'const GraphWorkshopFace =') +
    slice('const watchPreviewFor =', 'const WATCH_TABLE_ROWS =') +
    slice('const isSessionInspectorNode =', '// One chat, two parts') +
    slice('const InspectorTabs =', '// ─── Conversation rail') +
    '\nglobalThis.Component = NodeRail;', {
      aiNodeWithMovedParams:node => node, studioCategory:() => ({label:'Logic'}),
      nodeModelRow:() => null, ScopeComposer:() => null, NodeModelConversation:() => null,
      HoverBtn:() => null,
      CalmRow:({k,v}) => React.createElement('div', null, k + ': ' + v),
    });
  const node = {id:'sketch', title:'Sketch Lines', cat:'logic', live:true, params:[], ins:[], outs:[]};
  try {
    const canvas = {ok:true, root:'graph-a', graph_id:'app-a', revision:1, selected:'sketch',
      nodes:[{id:'sketch', label:'Sketch Lines'}], wires:[],
      configuration:{design_system:{control_catalog:{controls:[{owner:'run-control', applicable:true,
        activation:{capability:'app:device-capability:execute'}}]}}},
      interaction_projection:{bindings:[{control:'run-control', interaction:'run-action', event:'activate'}]}};
    const transport = vm.createContext({window:v.win});
    vm.runInContext(runOwner, transport);
    const api = v.win.ArchHubStudioAuthority.create({get:async url => {
      assert.equal(url, '/api/universal/canvas'); return canvas;
    }, post:(url, body) => { calls.push({url, body}); return pending; }, uuid:() => 'run-command'});
    await api.load();
    // The actual boot-installed run function and actual authority client; only HTTP is fake.
    vm.runInContext(runOwner.slice(start, end), vm.createContext({global:v.win, api}));
    await v.render({libraryMode, node, graph:{nodes:[node], wires:[]}});
    await v.click(buttons(v.doc).find(b => /Rerun/.test(b.textContent)));
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, '/api/universal/run-graph');
    assert.equal(calls[0].body.command_id, 'run-command');
    assert.equal(calls[0].body.expected_scope, 'graph-a');
    assert.equal(calls[0].body.control, 'run-control');
    assert.ok(buttons(v.doc).find(b => /Running/.test(b.textContent))?.disabled);
    await v.click(buttons(v.doc).find(b => b.getAttribute('role') === 'tab' && b.textContent === 'Runs'));
    assert.match(v.doc.querySelector('section[aria-label="Runs"]')?.textContent || '', /Running/);
    await v.act(() => outcome === 'refused' ? rejectRun(new Error('Run refused by policy')) :
      resolveRun({...canvas, revision:2, display:outcome === 'result' ? {sketch:'Measured lines: 12'} : {}, pending:{}}));
    const expected = outcome === 'result' ? /Measured lines: 12/ : outcome === 'refused' ? /Run refused by policy/ : /no execution result for this node/;
    assert.match(v.doc.querySelector('section[aria-label="Runs"]')?.textContent || '', expected);
    await v.click(buttons(v.doc).find(b => b.getAttribute('role') === 'tab' && b.textContent === 'Properties'));
    assert.ok(!buttons(v.doc).find(b => /Rerun/.test(b.textContent))?.disabled);
    await v.click(buttons(v.doc).find(b => b.getAttribute('role') === 'tab' && b.textContent === 'Runs'));
    assert.match(v.doc.querySelector('section[aria-label="Runs"]')?.textContent || '', expected);
    assert.equal(calls.length, 1, 'switching tabs never replays the run');
  } finally { await v.close(); }
});
}

test('item 3: Home 082 supersedes session-state chips with real Workshop finishing work', async () => {
  const {mountStudio} = require('./studio_home3_helpers.cjs');
  const ui = await mountStudio({snapshot:{workshop:{root:'room-a', graph_id:'graph-a', scope_root:'scope-a',
    can_send:true, messages:[], participants:[], workflows:[
      {root:'running-work', title:'Drawing', state:'running', approval:{current:true}},
      {root:'done-work', title:'Issued drawing', state:'done', result_summary:'Measured result', completed_at:'2026-10-15T10:00:00Z'},
    ]}}});
  try {
    await ui.settle(); await ui.settle();
    assert.ok(ui.doc.querySelector('[data-home-design="082"]'));
    assert.match(ui.doc.querySelector('[data-home-heading]').textContent, /finishing 1 thing/);
    assert.deepEqual([...ui.doc.querySelectorAll('[data-home-result]')].map(row => row.dataset.homeResult), ['done-work']);
    assert.match(ui.doc.querySelector('[data-home-result]').textContent, /Measured result/);
    for (const label of ['all','saved','running','done','paused','workflow','scheduled','needs review'])
      assert.ok(![...ui.doc.querySelectorAll('button')].some(button => button.textContent.trim() === label), 'superseded chip: ' + label);
  } finally { ui.close(); }
});

test('item 4: mounted SettingsHub opens its tool and has no unused onWire prop', async () => {
  const hub = slice('const SettingsHub =', '\nconst ');
  const calls = [];
  const v = await mount(slice('const ToolCard =', '\nconst ') + hub +
    '\nglobalThis.Component = SettingsHub;', {ToolGlyph:() => null, toolStateWord:state => state});
  try {
    await v.render({toolRows:[{id:'brain', label:'Brain', state:'off'}], onClose:() => calls.push('close'), onOpenTool:id => calls.push(id)});
    await v.click(v.doc.querySelector('[data-tool-card="brain"]'));
    assert.deepEqual(calls, ['close','brain']);
    assert.doesNotMatch(hub, /\bonWire\s*=/, 'ToolCard consumes only onOpen; remove the dead prop');
  } finally { await v.close(); }
});
