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

async function mountStudioForStopAll() {
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

  let serverStopped = false;
  const postCalls = [];
  const toolRows = [
    {id:'studio', label:'Studio', state:'running', state_word:'RUNNING', description:'Canvas, chats and graph sessions.', stat_line:'3 sessions · 0 running.', off_sentence:'Switched off. Sessions are kept.', wire_summary:'Studio → Brain'},
    {id:'workshop', label:'Workshop', state:'running', state_word:'RUNNING', description:'Projects, tasks and governed work.', stat_line:'1 projects · 1 tasks.', off_sentence:'Switched off. Tasks are paused.', wire_summary:'Workshop → Studio'},
    {id:'brain', label:'Brain', state:'off', state_word:'OFF', description:'Memory, facts and local classification.', stat_line:'1 facts.', off_sentence:'Switched off.', wire_summary:'Brain → Studio'},
    {id:'baboom', label:'BABOOM', state:'running', state_word:'RUNNING', description:'Desktop companion and approved execution.', stat_line:'Attached runtime.', off_sentence:'Switched off.', wire_summary:'BABOOM ← Studio'},
    {id:'connectors', label:'Connectors', state:'running', state_word:'RUNNING', description:'Host bridges.', stat_line:'1/1 hosts running.', off_sentence:'Switched off.', wire_summary:'Connectors → Studio'},
    {id:'cloud', label:'Cloud', state:'starting', state_word:'STARTING', description:'Devices and cloud agents.', stat_line:'Not signed in.', off_sentence:'Switched off.', wire_summary:'Cloud ← Brain'},
  ];

  win.fetch = (url, options = {}) => {
    const urlStr = String(url);
    const method = String(options.method || 'GET').toUpperCase();
    if (urlStr === '/stop-all' && method === 'POST') {
      postCalls.push({url:urlStr, method, at:clock.now()});
      serverStopped = true;
      return Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, stopped:true})});
    }
    if (urlStr === '/resume' && method === 'POST') {
      postCalls.push({url:urlStr, method, at:clock.now()});
      serverStopped = false;
      return Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, stopped:false})});
    }
    if (urlStr.includes('/api/universal/models')) {
      return Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, groups:[], selected_route:'openrouter/free'})});
    }
    if (urlStr === '/tools') {
      return Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, tools:toolRows, stopped:serverStopped})});
    }
    if (urlStr === '/waiting') {
      return Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, items:[]})});
    }
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
  win.ARCHHUB_TOOL_HUB = {ok:true, tools:toolRows, stopped:false, waiting:[]};
  win.ARCHHUB_LIVE = {sessions:[
      {id:'graph-a', title:'Mine', state:'idle', file:'mine.graph', owner:'mine'},
    ], currentGraph:'graph-a',
    hosts:[{id:'r25', name:'Revit 2025', state:'connected', file:'Tower.rvt'}],
    connectors:[{id:'revit', drive:true}], graph, memory:[], skills:[]};

  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') win.eval(read('nodelang/studio/compiled/' + file.output));
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');

  const settle = async () => {
    await new Promise(resolve => setTimeout(resolve, 30));
    for (let i = 0; i < 10; i += 1) await Promise.resolve();
  };
  await settle();

  const close = () => { try { win.ReactDOM.flushSync(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  return {win, postCalls, clock, settle, close};
}

test('ServerStrip: Stop posts /stop-all, strip shows "Stopped · Resume", and Resume posts /resume', async () => {
  const studio = await mountStudioForStopAll();
  try {
    const {win, postCalls, settle} = studio;

    // 1. Find initial Stop button
    const buttons = () => [...win.document.querySelectorAll('button')];
    const stopButton = buttons().find(b => b.textContent.trim() === 'Stop');
    assert.ok(stopButton, 'ServerStrip contains Stop button');

    // 2. Click Stop -> posts /stop-all
    win.ReactDOM.flushSync(() => stopButton.click());
    await settle();

    const stopCall = postCalls.find(c => c.url === '/stop-all');
    assert.ok(stopCall, 'Stop clicked: POST /stop-all was sent');

    // 3. Verify strip shows "Stopped · Resume"
    const stripText = win.document.body.textContent;
    assert.ok(stripText.includes('Stopped · Resume'), `ServerStrip shows "Stopped · Resume": got text "${stripText}"`);

    // 4. Find Resume button
    const resumeButton = buttons().find(b => b.textContent.trim() === 'Resume');
    assert.ok(resumeButton, 'ServerStrip contains Resume button when stopped');

    // 5. Click Resume -> posts /resume
    win.ReactDOM.flushSync(() => resumeButton.click());
    await settle();

    const resumeCall = postCalls.find(c => c.url === '/resume');
    assert.ok(resumeCall, 'Resume clicked: POST /resume was sent');

    // 6. Verify strip reverts to Stop
    const revertedStop = buttons().find(b => b.textContent.trim() === 'Stop');
    assert.ok(revertedStop, 'ServerStrip reverted to Stop button after resume');
  } finally {
    studio.close();
  }
});
