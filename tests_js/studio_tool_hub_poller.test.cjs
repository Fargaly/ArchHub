const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(match => [match[1], match[2]]));

function installIntervalClock(win) {
  let now = 0, nextId = 0;
  const intervals = new Map();
  win.setInterval = (fn, ms = 0) => {
    const id = ++nextId;
    intervals.set(id, {fn, ms:Number(ms) || 0, next:now + (Number(ms) || 0)});
    return id;
  };
  win.clearInterval = id => intervals.delete(id);
  // The Hub read watchdog is a one-shot timer on the same virtual clock.
  win.setTimeout = (fn, ms = 0) => {
    const id = ++nextId;
    intervals.set(id, {fn, ms:Number(ms) || 0, next:now + (Number(ms) || 0), once:true});
    return id;
  };
  win.clearTimeout = id => intervals.delete(id);
  const drain = async () => {
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
  };
  const advance = async ms => {
    const end = now + ms;
    while (true) {
      let dueAt = Infinity;
      for (const interval of intervals.values()) dueAt = Math.min(dueAt, interval.next);
      if (dueAt > end) break;
      now = dueAt;
      const due = [...intervals.entries()].filter(([, interval]) => interval.next <= now);
      for (const [id, interval] of due) {
        if (!intervals.has(id)) continue;
        if (interval.once) intervals.delete(id); else interval.next += interval.ms;
        interval.fn();
      }
      await drain();
    }
    now = end;
    await drain();
  };
  return {advance, intervals, now:() => now};
}

async function mountStudioWithToolHubPoller(mountOptions = {}) {
  const pending = [];
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  const held = manifest.files.find(file => file.source === 'studio-lm.jsx');
  const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio/studio-lm.jsx'))).digest('hex');
  assert.equal(held && held.source_sha256, live, 'Studio build is stale for studio-lm.jsx: run npm run build:studio');
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53916/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  const clock = installIntervalClock(win);
  let hidden = false;
  Object.defineProperty(win.document, 'hidden', {configurable:true, get:() => hidden});
  const setHidden = value => {
    hidden = value;
    win.document.dispatchEvent(new win.Event('visibilitychange'));
  };
  const calls = [];
  const toolRows = [
    {id:'studio', label:'Studio', state:'running', state_word:'RUNNING', description:'Canvas, chats and graph sessions.', stat_line:'3 sessions · 0 running.', off_sentence:'Switched off. Sessions are kept.', wire_summary:'Studio → Brain'},
    {id:'workshop', label:'Workshop', state:'running', state_word:'RUNNING', description:'Projects, tasks and governed work.', stat_line:'1 projects · 1 tasks.', off_sentence:'Switched off. Tasks are paused.', wire_summary:'Workshop → Studio'},
    {id:'brain', label:'Brain', state:'off', state_word:'OFF', description:'Memory, facts and local classification.', stat_line:'1 facts.', off_sentence:'Switched off.', wire_summary:'Brain → Studio'},
    {id:'baboom', label:'BABOOM', state:'running', state_word:'RUNNING', description:'Desktop companion and approved execution.', stat_line:'Attached runtime.', off_sentence:'Switched off.', wire_summary:'BABOOM ← Studio'},
    {id:'connectors', label:'Connectors', state:'running', state_word:'RUNNING', description:'Host bridges.', stat_line:'1/1 hosts running.', off_sentence:'Switched off.', wire_summary:'Connectors → Studio'},
    {id:'cloud', label:'Cloud', state:'starting', state_word:'STARTING', description:'Devices and cloud agents.', stat_line:'Not signed in.', off_sentence:'Switched off.', wire_summary:'Cloud ← Brain'},
  ];
  win.fetch = (url, options = {}) => {
    calls.push({url:String(url), at:clock.now(), signal:options.signal || null});
    if (String(url).includes('/api/universal/models')) {
      return Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, groups:[], selected_route:'openrouter/free'})});
    }
    if (String(url) === '/tools') {
      const answer = {ok:true, json:() => Promise.resolve({ok:true, tools:toolRows})};
      if (mountOptions.hold) return new Promise(resolve => pending.push(() => resolve(answer)));
      return Promise.resolve(answer);
    }
    if (String(url) === '/waiting') return Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, items:[]})});
    return new Promise(() => {});
  };
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  const authorization = {subject:'owner-a', session:'view-a'};
  const graph = {nodes:[{id:'tool-a', title:'Tool node', cat:'ai', x:40, y:40, w:220, h:120, params:[], outs:[]}], wires:[]};
  const snapshot = {canvas:{graph_id:'graph-a', root:'scope-a', revision:7, authorization},
    workshops:[{root:'room-a', label:'General Workshop', is_general:true}],
    nativeWork:null,
    theme:{configuration:{baboom_startup:{value:'on', source:'graph', available:true, revision:12}}, pending:false, error:''},
    applicationUpdate:{state:'idle', current_build:'20261010-o'},
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'}, authorization, revision:7}, graph, selected:null}};
  const owner = {
    getSnapshot:() => snapshot,
    subscribe:() => () => {},
    watchApplicationUpdate:() => () => {},
    setBaboomStartup:async value => {
      snapshot.theme.configuration.baboom_startup.value = value;
      return {ok:true, value};
    },
  };
  win.ARCHHUB_EXISTING_WORKSHOP = new Proxy(owner, {get:(target, key) =>
    key in target || typeof key !== 'string' || key === 'then' ? target[key] : () => new Promise(() => {})});
  win.ARCHHUB_TOOL_HUB = {ok:true, tools:toolRows, waiting:[]};
  win.ARCHHUB_LIVE = {sessions:[
      {id:'graph-a', title:'Mine', state:'idle', file:'mine.graph', owner:'mine'},
      {id:'graph-b', title:'Scheduled', state:'scheduled', file:'daily.graph'},
    ], currentGraph:'graph-a',
    hosts:[{id:'r25', name:'Revit 2025', state:'connected', file:'Tower.rvt'}],
    connectors:[{id:'revit', drive:true}], graph, memory:[{id:'m1', text:'Remember this', src:'test'}], skills:[]};
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') win.eval(read('nodelang/studio/compiled/' + file.output));
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const settle = async () => { await new Promise(resolve => setTimeout(resolve, 25)); for (let i = 0; i < 6; i += 1) await Promise.resolve(); };
  await settle();
  const home = [...win.document.querySelectorAll('button')].find(node => node.textContent.trim() === '+');
  assert.ok(home, 'Home button exists');
  win.ReactDOM.flushSync(() => home.click());
  await settle();
  const settings = win.document.querySelector('[title="Settings"]');
  assert.ok(settings, 'Settings button exists');
  win.ReactDOM.flushSync(() => settings.click());
  await settle();
  const hub = [...win.document.querySelectorAll('button')].find(button => button.firstElementChild?.textContent === 'Hub');
  assert.ok(hub, 'Settings Hub is mounted');
  calls.length = 0;
  const close = () => { try { win.ReactDOM.flushSync(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  return {win, calls, clock, setHidden, close, held:pending};
}

function countEndpoint(calls, endpoint) {
  return calls.filter(call => call.url === endpoint).length;
}

function assertNoDuplicateEndpointInTick(calls, endpoint) {
  const byTick = new Map();
  for (const call of calls.filter(call => call.url === endpoint)) {
    byTick.set(call.at, (byTick.get(call.at) || 0) + 1);
  }
  for (const [tick, count] of byTick) {
    assert.equal(count, 1, `${endpoint} has no duplicate fetches at tick ${tick}`);
  }
}

test('tool hub poller shares one idle 5s cadence across Home, Settings Hub and the rail', async () => {
  const studio = await mountStudioWithToolHubPoller();
  try {
    await studio.clock.advance(60000);
    const tools = countEndpoint(studio.calls, '/tools');
    const waiting = countEndpoint(studio.calls, '/waiting');
    console.log(`tool hub idle counts: /tools=${tools} /waiting=${waiting}`);
    assert.ok(tools <= 12, '/tools is fetched at most 12 times over 60 s idle');
    assert.ok(waiting <= 12, '/waiting is fetched at most 12 times over 60 s idle');
    assertNoDuplicateEndpointInTick(studio.calls, '/tools');
    assertNoDuplicateEndpointInTick(studio.calls, '/waiting');
  } finally { studio.close(); }
});

test('tool hub poller pauses while hidden and refreshes once when visible again', async () => {
  const studio = await mountStudioWithToolHubPoller();
  try {
    studio.setHidden(true);
    await studio.clock.advance(60000);
    const hiddenTools = countEndpoint(studio.calls, '/tools');
    const hiddenWaiting = countEndpoint(studio.calls, '/waiting');
    assert.equal(hiddenTools, 0, 'hidden Studio fetches no /tools');
    assert.equal(hiddenWaiting, 0, 'hidden Studio fetches no /waiting');
    studio.setHidden(false);
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
    const visibleTools = countEndpoint(studio.calls, '/tools');
    const visibleWaiting = countEndpoint(studio.calls, '/waiting');
    console.log(`tool hub visibility counts: hidden /tools=${hiddenTools} /waiting=${hiddenWaiting}; visible refresh /tools=${visibleTools} /waiting=${visibleWaiting}`);
    assert.equal(visibleTools, 1, 'visible Studio immediately refreshes /tools once');
    assert.equal(visibleWaiting, 1, 'visible Studio immediately refreshes /waiting once');
  } finally { studio.close(); }
});

test('tool hub poller refreshes immediately after a local tool toggle', async () => {
  const studio = await mountStudioWithToolHubPoller();
  try {
    const toggle = studio.win.document.querySelector('[data-tool-card="baboom"] button[role="switch"]');
    assert.ok(toggle, 'BABOOM switch exists in Settings Hub');
    studio.win.ReactDOM.flushSync(() => toggle.click());
    await new Promise(resolve => setTimeout(resolve, 25));
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
    const tools = countEndpoint(studio.calls, '/tools');
    const waiting = countEndpoint(studio.calls, '/waiting');
    console.log(`tool hub toggle counts: /tools=${tools} /waiting=${waiting}`);
    assert.equal(tools, 1, 'toggle immediately refreshes /tools once');
    assert.equal(waiting, 1, 'toggle immediately refreshes /waiting once');
  } finally { studio.close(); }
});

test('an aborted older read settling late never lets a third read overlap the current one', async () => {
  const studio = await mountStudioWithToolHubPoller({hold:true});
  try {
    const flush = async () => { for (let i = 0; i < 8; i += 1) await Promise.resolve(); };
    studio.held.splice(0).forEach(release => release());
    await flush();
    studio.calls.length = 0;
    await studio.clock.advance(5000);
    await flush();
    assert.equal(countEndpoint(studio.calls, '/tools'), 1, 'first read is in flight');
    studio.setHidden(true);
    studio.setHidden(false);
    await flush();
    assert.equal(countEndpoint(studio.calls, '/tools'), 2, 'visible again starts the current read');
    studio.held[0]();
    await flush();
    await studio.clock.advance(5000);
    await flush();
    assert.equal(countEndpoint(studio.calls, '/tools'), 2, 'the stale read settling does not release the guard of the current read');
    studio.held[1]();
    await flush();
    await studio.clock.advance(5000);
    await flush();
    assert.equal(countEndpoint(studio.calls, '/tools'), 3, 'the poller resumes once the current read settles');
  } finally { studio.close(); }
});

test('a read that never settles is abandoned after 15 s and the poller carries on', async () => {
  const studio = await mountStudioWithToolHubPoller({hold:true});
  try {
    const flush = async () => { for (let i = 0; i < 8; i += 1) await Promise.resolve(); };
    studio.held.splice(0).forEach(release => release());
    await flush();
    studio.calls.length = 0;
    await studio.clock.advance(5000);
    await flush();
    assert.equal(countEndpoint(studio.calls, '/tools'), 1, 'a read is in flight and never settles');
    await studio.clock.advance(10000);
    await flush();
    assert.equal(countEndpoint(studio.calls, '/tools'), 1, 'no overlap while the hung read is within its 15 s');
    await studio.clock.advance(10000);
    await flush();
    assert.ok(countEndpoint(studio.calls, '/tools') >= 2, 'after the watchdog the poller fetches again');
  } finally { studio.close(); }
});
