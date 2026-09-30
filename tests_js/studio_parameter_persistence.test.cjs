const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const sourcePath = process.env.ARCHHUB_PARAMS_TEST_PATH || path.join(__dirname, '../nodelang/studio/studio-params.jsx');
const source = fs.readFileSync(sourcePath, 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
function harness(api = {}) {
  const begin = source.indexOf('const PM_EDITS =');
  const end = source.indexOf('// A built-in parameter', begin);
  const inspector = source.indexOf('function NodeInspector(');
  const render = source.indexOf('\n  return (', inspector);
  const context = {
    window: api, console, setTimeout, clearTimeout,
    PM_PRESETS: {}, pmNorm2: p => ({...p}), pmType: () => ({wire: false}),
    React: {
      useMemo: f => f(), useEffect: f => f(),
      useState: initial => { let value = initial; return [value, next => { value = typeof next === 'function' ? next(value) : next; }]; },
    },
  };
  vm.createContext(context);
  vm.runInContext(source.slice(begin, end) + '\n' + source.slice(inspector, render) + `
    return { set, rec, applyValues: typeof applyValues === 'function' ? applyValues : null,
      runGraph: typeof runGraph === 'function' ? runGraph : null,
      discardCustom: typeof discardCustom === 'function' ? discardCustom : null };
  }
  globalThis.make = NodeInspector;
  globalThis.records = PM_EDITS;
  `, context);
  const node = {id: 'node-a', live: true, params: [{k: 'value', v: 'old', rel: 'relation-a'}]};
  const make = n => context.make({node: n});
  const panel = make(node);
  return {panel, node, make, context};
}

test('rapid edits do not send overlapping writes and the final value is saved', async () => {
  const writes = [];
  let active = 0, peak = 0;
  const {panel} = harness({ARCHHUB_SET_PROP: (relation, value) => {
    active++; peak = Math.max(peak, active);
    return new Promise(resolve => writes.push({relation, value, finish() { active--; resolve({ok: true}); }}));
  }});
  panel.set('value', 'first');
  await tick();
  panel.set('value', 'second');
  panel.set('value', 'final');
  await tick();
  assert.equal(peak, 1, 'parameter saves raced');
  writes[0].finish();
  await tick();
  assert.equal(writes.at(-1).value, 'final');
  writes.at(-1).finish();
  await tick();
});

test('the installed inspector action calls execution rather than incrementing a counter', async () => {
  let runs = 0;
  const {panel, context} = harness({ARCHHUB_RUN: async () => {
    runs++; return {display: {'node-a': 'calculated 42'}, pending: {}, revision: 12};
  }});
  if (panel.runGraph) await panel.runGraph();
  else {
    const original = source.match(/onClick=\{(\(\) => \{ setRan\(r => r \+ 1\); setCooked\(vals\); \})\}/);
    assert.ok(original, 'inspector action not found');
    Object.assign(context, {setRan: () => {}, setCooked: () => {}, vals: {}});
    vm.runInContext('(' + original[1] + ')()', context);
  }
  assert.equal(runs, 1, 'button never executed the graph');
  assert.equal(panel.rec.ran, 1);
});

test('a refused save retains the draft, blocks execution, and can be retried', async () => {
  let fail = true, runs = 0;
  const {panel} = harness({
    ARCHHUB_SET_PROP: async () => { if (fail) throw new Error('write denied'); return {ok: true}; },
    ARCHHUB_RUN: async () => { runs++; return {display: {'node-a': 'updated'}, pending: {}}; },
  });
  panel.set('value', 'new');
  await tick();
  assert.equal(panel.rec.vals.value, 'new');
  assert.match(panel.rec.persistence.errors.get('value'), /write denied/);
  await panel.runGraph();
  assert.equal(runs, 0);
  assert.equal(panel.rec.ran, 0);
  fail = false;
  panel.set('value', 'new');
  await panel.runGraph();
  assert.equal(runs, 1);
  assert.equal(panel.rec.cooked.value, 'new');
});

test('bulk edits use persistence and preserve partial failures', async () => {
  const calls = [];
  const {make} = harness({ARCHHUB_SET_PROP: async (relation, value) => {
    calls.push([relation, value]);
    if (relation === 'r-b') throw new Error('b refused');
    return {ok: true};
  }});
  const panel = make({id: 'bulk', live: true, params: [
    {k:'a', v:'old-a', rel:'r-a'}, {k:'b', v:'old-b', rel:'r-b'},
  ]});
  panel.applyValues({a:'new-a', b:'new-b'});
  await tick();
  assert.deepEqual(calls, [['r-a','new-a'], ['r-b','new-b']]);
  assert.equal(panel.rec.persistence.acknowledged.a, 'new-a');
  assert.equal(panel.rec.persistence.errors.size, 1);
});

test('changing selected nodes cannot redirect an in-flight save', async () => {
  const calls = [];
  let finish;
  const {panel, make} = harness({ARCHHUB_SET_PROP: (relation, value) => {
    calls.push([relation, value]);
    if (relation === 'relation-a') return new Promise(resolve => finish = resolve);
    return Promise.resolve({ok: true});
  }});
  panel.set('value', 'a-new');
  await tick();
  const other = make({id:'node-b', live:true, params:[{k:'value',v:'b-old',rel:'relation-b'}]});
  other.set('value', 'b-new');
  await tick();
  assert.equal(calls.length, 1);
  finish({ok:true});
  await tick();
  assert.deepEqual(calls, [['relation-a','a-new'], ['relation-b','b-new']]);
});

test('first wire edit creates a property; the next edits its projected relation', async () => {
  const writes = [], rows = [];
  const {make} = harness({
    ARCHHUB_GET_CANVAS: async () => ({wires:[{id:'wire-a',params:rows}]}),
    ARCHHUB_SET_WIRE_PROP: async (root, key, value) => {
      writes.push(['create',root,key,value]); rows.push({label:key,relation:'wire-relation'});
      return {ok:true,value_root:'not-a-relation'};
    },
    ARCHHUB_SET_PROP: async (relation,value) => { writes.push(['edit',relation,value]); return {ok:true}; },
  });
  const panel = make({id:'wire:0',isWire:true,live:true,wireRoot:'wire-a',held:{},params:[{k:'condition',v:''}]});
  panel.set('condition','first'); await tick();
  panel.set('condition','second'); await tick();
  assert.deepEqual(writes,[['create','wire-a','condition','first'],['edit','wire-relation','second']]);
});

test('run waits for pending saves and does not mark changed inputs current', async () => {
  let finishWrite, finishRun, runs = 0;
  const {panel} = harness({
    ARCHHUB_SET_PROP: () => new Promise(resolve => finishWrite = resolve),
    ARCHHUB_RUN: () => { runs++; return new Promise(resolve => finishRun = resolve); },
  });
  panel.set('value','first'); await tick();
  const running = panel.runGraph(); await tick();
  assert.equal(runs,0);
  finishWrite({ok:true}); await tick();
  assert.equal(runs,1);
  panel.set('value','changed-during-run'); await tick();
  finishRun({display:{'node-a':'old result'},pending:{}});
  await running;
  assert.equal(panel.rec.ran,0);
  assert.match(panel.rec.persistence.runError,/changed during execution/);
  finishWrite({ok:true}); await tick();
});

test('missing execution results and pending nodes never count as a success', async () => {
  for (const result of [{display:{},pending:{}},{display:{'node-a':'stale'},pending:{'node-a':'missing input'}}]) {
    const {panel} = harness({ARCHHUB_RUN: async () => result});
    await panel.runGraph();
    assert.equal(panel.rec.ran,0);
    assert.ok(panel.rec.persistence.runError);
  }
});

test('bulk buttons and execution control are bound to the actual save/run functions', () => {
  assert.match(source,/onClick=\{\(\) => applyValues\(allDefs\)\}/);
  assert.match(source,/onClick=\{\(\) => applyValues\(pr.vals\)\}/);
  assert.match(source,/onClick=\{runGraph\}/);
  assert.match(source,/↻ Rerun/);
});

test('switching inspectors during execution cannot start a second graph run', async () => {
  let runs = 0, finish;
  const {panel, make} = harness({ARCHHUB_RUN: () => {
    runs++; return new Promise(resolve => finish = resolve);
  }});
  const first = panel.runGraph(); await tick();
  const second = make({id:'node-b',live:true,params:[]});
  await second.runGraph();
  assert.equal(runs,1);
  finish({display:{'node-a':'done'},pending:{}}); await first;
});

test('discarding a local-only failed parameter clears its invisible run blocker', async () => {
  const {panel} = harness({ARCHHUB_RUN: async () => ({display:{'node-a':'done'},pending:{}})});
  panel.rec.custom.push({k:'draft-only',def:''});
  panel.set('draft-only','value'); await tick();
  assert.equal(panel.rec.persistence.errors.size,1);
  panel.discardCustom('draft-only');
  assert.equal(panel.rec.persistence.errors.size,0);
  assert.equal(panel.rec.custom.length,0);
  await panel.runGraph();
  assert.equal(panel.rec.ran,1);
});

test('an uncertain wire-property write cannot be silently discarded', async () => {
  const {make} = harness({
    ARCHHUB_GET_CANVAS: async () => ({wires:[{id:'wire-a',params:[]}]}),
    ARCHHUB_SET_WIRE_PROP: async () => { throw new Error('response lost'); },
  });
  const panel = make({id:'wire:0',isWire:true,live:true,wireRoot:'wire-a',held:{},params:[]});
  panel.rec.custom.push({k:'new-rule'});
  panel.set('new-rule','value'); await tick();
  panel.discardCustom('new-rule');
  assert.equal(panel.rec.custom.length,1);
  assert.equal(panel.rec.persistence.errors.size,1);
});

test('another caller cannot start or adopt an in-flight graph execution request', async () => {
  const html = fs.readFileSync(path.join(path.dirname(sourcePath), 'studio.html'), 'utf8');
  const start = html.indexOf('let graphRunPromise = null;');
  const end = html.indexOf('window.ARCHHUB_SET_PROP', start);
  assert.ok(start >= 0 && end > start);
  let calls = 0, finish;
  const ctx = {window:{},jpost: () => { calls++; return new Promise(resolve => finish=resolve); }};
  vm.runInNewContext(html.slice(start,end),ctx);
  const first = ctx.window.ARCHHUB_RUN();
  const second = ctx.window.ARCHHUB_RUN();
  await assert.rejects(second,/already running/);
  assert.equal(calls,1);
  finish({display:{}}); await first;
  const later = ctx.window.ARCHHUB_RUN();
  assert.equal(calls,2);
  finish({display:{}}); await later;
});

test('inspector cannot mark newer saved parameters executed by another controls older run', async () => {
  const html = fs.readFileSync(path.join(path.dirname(sourcePath), 'studio.html'), 'utf8');
  const start = html.indexOf('let graphRunPromise = null;');
  const end = html.indexOf('window.ARCHHUB_SET_PROP', start);
  let finish;
  const ctx = {window:{},jpost: () => new Promise(resolve => finish=resolve)};
  vm.runInNewContext(html.slice(start,end),ctx);
  const olderRun = ctx.window.ARCHHUB_RUN();
  ctx.window.ARCHHUB_SET_PROP = async () => ({ok:true});
  const {panel} = harness(ctx.window);
  panel.set('value','new-input'); await tick();
  await panel.runGraph();
  assert.equal(panel.rec.ran,0);
  assert.equal(panel.rec.cooked.value,'old');
  assert.match(panel.rec.persistence.runError,/already running/);
  finish({display:{'node-a':'older result'},pending:{}}); await olderRun;
  assert.equal(panel.rec.ran,0);
});
