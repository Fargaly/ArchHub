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
  const drain = async () => { for (let i = 0; i < 6; i += 1) await Promise.resolve(); };
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
  return {advance, now:() => now};
}

async function mountStudioForStopAll(options = {}) {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  const held = manifest.files.find(file => file.source === 'studio-lm.jsx');
  const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio/studio-lm.jsx'))).digest('hex');
  assert.equal(held && held.source_sha256, live, 'Studio build is stale for studio-lm.jsx: run npm run build:studio');
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53916/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  const clock = installIntervalClock(win);
  Object.defineProperty(win.document, 'hidden', {configurable:true, get:() => false});

  let serverStopped = false;
  const failToolsAfterStop = !!options.failToolsAfterStop;
  const postCalls = [];
  const toolRows = [
    {id:'studio', label:'Studio', state:'running', state_word:'RUNNING', description:'Canvas, chats and graph sessions.', stat_line:'3 sessions - 0 running.', off_sentence:'Switched off. Sessions are kept.', wire_summary:'Studio -> Brain'},
    {id:'workshop', label:'Workshop', state:'running', state_word:'RUNNING', description:'Projects, tasks and governed work.', stat_line:'1 projects - 1 tasks.', off_sentence:'Switched off. Tasks are paused.', wire_summary:'Workshop -> Studio'},
    {id:'brain', label:'Brain', state:'off', state_word:'OFF', description:'Memory, facts and local classification.', stat_line:'1 facts.', off_sentence:'Switched off.', wire_summary:'Brain -> Studio'},
    {id:'connectors', label:'Connectors', state:'running', state_word:'RUNNING', description:'Host bridges.', stat_line:'1/1 hosts running.', off_sentence:'Switched off.', wire_summary:'Connectors -> Studio'},
  ];

  win.fetch = (url, requestOptions = {}) => {
    const urlStr = String(url);
    const method = String(requestOptions.method || 'GET').toUpperCase();
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
      if (failToolsAfterStop && serverStopped) {
        return Promise.resolve({ok:false, json:() => Promise.resolve({ok:false, error:'owner unavailable'})});
      }
      return Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, tools:toolRows, stopped:serverStopped})});
    }
    if (urlStr === '/waiting') return Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, items:options.waiting || []})});
    return new Promise(() => {});
  };

  win.ARCHHUB_THEME = {...seed};
  if (options.loadHosts) win.ARCHHUB_LOAD_HOSTS = options.loadHosts;
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  const authorization = {subject:'owner-a', session:'view-a'};
  const graph = {nodes:[{id:'tool-a', title:'Tool node', cat:'ai', x:40, y:40, w:220, h:120, params:[], outs:[]}], wires:[]};
  const snapshot = {canvas:{graph_id:'graph-a', root:'scope-a', revision:7, authorization},
    workshops:[], nativeWork:null, applicationUpdate:{state:'idle', current_build:'20261010-o'},
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'}, authorization, revision:7}, graph, selected:null}};
  win.ARCHHUB_EXISTING_WORKSHOP = {
    getSnapshot:() => snapshot,
    subscribe:() => () => {},
    watchApplicationUpdate:() => () => {},
    refreshTopologyCanvas:async () => ({ok:true}),
  };
  win.ARCHHUB_TOOL_HUB = {ok:true, tools:toolRows, stopped:false, waiting:options.waiting || []};
  const hostRows = options.hosts || [{id:'local-host', name:'Local Host', state:'connected', file:'Tower.rvt'}];
  win.ARCHHUB_LIVE = {sessions:[
      {id:'graph-a', title:'Mine', state:'running', file:'mine.graph', owner:'mine'},
    ], currentGraph:'graph-a',
    hosts:hostRows,
    connectors:hostRows.map(row => ({id:row.id, drive:true})), graph, memory:[], skills:[]};

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

test('StatusBar: global Stop posts /stop-all, shows Stopped and keeps Resume reachable', async () => {
  const studio = await mountStudioForStopAll();
  try {
    const {win, postCalls, settle} = studio;
    const buttons = () => [...win.document.querySelectorAll('button')];
    const stopButton = buttons().find(button => button.textContent.trim() === 'Stop');
    assert.ok(stopButton, 'StatusBar contains Stop button');

    win.ReactDOM.flushSync(() => stopButton.click());
    await settle();

    assert.ok(postCalls.find(call => call.url === '/stop-all'), 'Stop clicked: POST /stop-all was sent');
    assert.ok(win.document.body.textContent.includes('Stopped'), 'StatusBar shows Stopped after confirmed stop');

    const resumeButton = buttons().find(button => button.textContent.trim() === 'Resume');
    assert.ok(resumeButton, 'StatusBar contains Resume button when stopped');
    win.ReactDOM.flushSync(() => resumeButton.click());
    await settle();

    assert.ok(postCalls.find(call => call.url === '/resume'), 'Resume clicked: POST /resume was sent');
    assert.ok(buttons().find(button => button.textContent.trim() === 'Stop'), 'StatusBar reverted to Stop button after resume');
  } finally {
    studio.close();
  }
});

test('StatusBar: host read states are explicit and running/waiting counts are independent', async () => {
  const pending = await mountStudioForStopAll({
    hosts:[],
    waiting:[{id:'wait-a', label:'Approve work', producer:'workshop_gate'}],
    loadHosts:() => new Promise(() => {}),
  });
  try {
    await pending.settle(() => pending.win.document.body.textContent.includes('1 waits for you'), 'pending waiting count rendered');
    assert.ok(pending.win.document.body.textContent.includes('Checking programs'), 'host read in flight does not claim no program connected');
    assert.ok(pending.win.document.body.textContent.includes('1 running'), 'running count remains visible without a connected host');
    assert.ok(pending.win.document.body.textContent.includes('1 waits for you'), 'waiting count remains visible without a connected host');
  } finally { pending.close(); }

  const failed = await mountStudioForStopAll({
    hosts:[],
    waiting:[{id:'wait-a', label:'Approve work', producer:'workshop_gate'}, {id:'wait-b', label:'Confirm cloud', producer:'social_approve'}],
    loadHosts:async () => { throw new Error('host read failed'); },
  });
  try {
    await failed.settle(() => failed.win.document.body.textContent.includes('2 waits for you'), 'failed waiting count rendered');
    assert.ok(failed.win.document.body.textContent.includes('Programs unavailable'), 'failed host read has a visible unavailable state');
    assert.ok([...failed.win.document.querySelectorAll('button')].some(button => button.textContent.trim() === 'Retry'), 'failed host read exposes Retry');
    assert.ok(failed.win.document.body.textContent.includes('1 running'), 'running count still renders after host read failure');
    assert.ok(failed.win.document.body.textContent.includes('2 waits for you'), 'waiting count still renders after host read failure');
  } finally { failed.close(); }

  const stale = await mountStudioForStopAll({
    hosts:[{id:'local-host', name:'Revit', version:'2026', state:'connected', file:'Tower.rvt'}],
    loadHosts:async () => { throw new Error('host read failed'); },
  });
  try {
    await stale.settle();
    const strip = stale.win.document.querySelector('footer')?.textContent || '';
    assert.match(strip, /Last known:\s*Revit 2026\s*·\s*Tower\.rvt\s*·\s*Retry/,
      'failed refresh keeps cached host explicitly last-known with retry');
    assert.doesNotMatch(strip, /●\s*Connected/, 'failed refresh never reports cached host as plain Connected');
  } finally { stale.close(); }

  const empty = await mountStudioForStopAll({hosts:[], loadHosts:async () => ({hosts:[], connectors:[]})});
  try {
    await empty.settle();
    assert.ok(empty.win.document.body.textContent.includes('No program connected'), 'no program appears only after a completed empty host read');
  } finally { empty.close(); }
});

test('StatusBar: confirmed Stop survives a failed /tools read and Resume remains reachable', async () => {
  const studio = await mountStudioForStopAll({failToolsAfterStop:true});
  try {
    const {win, postCalls, settle} = studio;
    const buttons = () => [...win.document.querySelectorAll('button')];
    const stopButton = buttons().find(button => button.textContent.trim() === 'Stop');
    assert.ok(stopButton, 'StatusBar contains Stop button');

    win.ReactDOM.flushSync(() => stopButton.click());
    await settle();
    await studio.clock.advance(1000);

    assert.ok(win.document.body.textContent.includes('Stopped'), 'confirmed stop survived failed /tools');
    const resumeButton = buttons().find(button => button.textContent.trim() === 'Resume');
    assert.ok(resumeButton, 'Resume remains reachable while owner reads fail');

    win.ReactDOM.flushSync(() => resumeButton.click());
    await settle();
    assert.ok(postCalls.find(call => call.url === '/resume'), 'Resume clicked: POST /resume was sent');
    assert.ok(buttons().find(button => button.textContent.trim() === 'Stop'), 'normal controls returned after resume');
  } finally {
    studio.close();
  }
});
