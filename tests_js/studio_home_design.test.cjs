const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const seedText = read('nodelang/universal_presentation_seed.py').match(/^THEME = \{([\s\S]*?)^\}/m)[1];
const seed = Object.fromEntries([...seedText.matchAll(/'([^']+)':\s*'(#[0-9a-f]{6})'/g)].map(m => [m[1], m[2]]));

async function mountStudio(options = {}) {
  const manifest = JSON.parse(read('nodelang/studio/compiled/manifest.json'));
  const held = manifest.files.find(file => file.source === 'studio-lm.jsx');
  const live = createHash('sha256').update(fs.readFileSync(path.join(root, 'nodelang/studio/studio-lm.jsx'))).digest('hex');
  assert.equal(held && held.source_sha256, live, 'Studio build is stale for studio-lm.jsx: run npm run build:studio');
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1:53914/', runScripts:'outside-only', pretendToBeVisual:true});
  const win = dom.window;
  const graphCreates = [];
  const fileClicks = [];
  const agentCalls = [];
  const ownerCalls = [];
  const waitingItems = options.waiting || [];
  const accountCalls = [];
  const toolRows = options.tools || [
      {id:'studio', label:'Studio', state:'running', state_word:'RUNNING',
        description:'Canvas, chats and graph sessions.', stat_line:'3 sessions · 0 running.',
        off_sentence:'Switched off. Sessions are kept.', wire_summary:'Studio → Brain · Connectors · Workshop'},
      {id:'workshop', label:'Workshop', state:'running', state_word:'RUNNING',
        description:'Projects, tasks and governed work.', stat_line:'1 projects · 1 tasks · 1 blocked.',
        off_sentence:'Switched off. Tasks are paused.', wire_summary:'Workshop → Studio · Connectors · Brain'},
      {id:'brain', label:'Brain', state:'off', state_word:'OFF',
        description:'Memory, facts and local classification.', stat_line:'1 facts · 1 stay on this machine.',
        off_sentence:'Switched off. Nothing is remembered or recalled.', wire_summary:'Brain → Studio · Workshop · Cloud',
        empty_title:'Brain is off', empty_line:'What ArchHub remembers. Everything else keeps running.'},
      {id:'baboom', label:'BABOOM', state:'running', state_word:'RUNNING',
        description:'Desktop companion and approved execution.', stat_line:'quiet off · speaks at most 2 times an hour.',
        off_sentence:'Switched off. No companion on the desktop.', wire_summary:'BABOOM ← Studio · Workshop'},
      {id:'connectors', label:'Connectors', state:'running', state_word:'RUNNING',
        description:'Host bridges and Speckle access.', stat_line:'1/1 hosts running · Speckle connected.',
        off_sentence:'Switched off. No reads or writes to your programs.', wire_summary:'Connectors → Studio · Workshop · Speckle'},
      {id:'cloud', label:'Cloud', state:'starting', state_word:'STARTING',
        description:'Devices, grants and cloud agents.', stat_line:'device-a · 0 cloud agents.',
        off_sentence:'Switched off. Works on this machine only.', wire_summary:'Cloud ← Brain · Workshop'},
    ];
  win.fetch = url => String(url).includes('/api/universal/models')
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, groups:[], selected_route:'openrouter/thinkingmachines/inkling:free'})})
    : String(url) === '/tools'
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, tools:toolRows})})
    : String(url) === '/waiting' && waitingItems.length
    ? new Promise(() => {})
    : String(url) === '/waiting'
    ? Promise.resolve({ok:true, json:() => Promise.resolve({ok:true, items:[]})})
    : new Promise(() => {});
  win.ARCHHUB_THEME = {...seed};
  win.matchMedia = () => ({matches:false, addEventListener() {}, removeEventListener() {}});
  win.ARCHHUB_GRAPH_CREATE = async title => {
    graphCreates.push(title);
    throw new Error('fixture stops after ARCHHUB_GRAPH_CREATE');
  };
  const authorization = {subject:'owner-a', session:'view-a'};
  const graph = {nodes:[{id:'tool-a', title:'Tool node', cat:'ai', x:40, y:40, w:220, h:120, params:[], outs:[]}],
    wires:[{id:'wire-a', from:['tool-a','out'], to:['tool-a','in']}]};
  const snapshot = {canvas:{graph_id:'graph-a', root:'scope-a', revision:7, authorization},
    workshops:[{root:'room-a', label:'General Workshop', is_general:true}],
    nativeWork:{state:'awaiting_approval', work:'Layer choice', review_text:'Pick a layer', approved:false},
    theme:{configuration:{baboom_startup:{value:'on', source:'graph', available:true, revision:12}}, pending:false, error:''},
    applicationUpdate:{state:'idle', current_build:'20261009-w7'},
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'}, authorization, revision:7}, graph, selected:null}};
  const owner = {
    getSnapshot:() => snapshot,
    subscribe:() => () => {},
    watchApplicationUpdate:() => () => {},
    setBaboomStartup:async value => { ownerCalls.push(['setBaboomStartup', value]); snapshot.theme.configuration.baboom_startup.value = value; },
    approveNativeWork:async (root, inputDigest) => { ownerCalls.push(['approveNativeWork', root, inputDigest]); return {ok:true}; },
    nativeWorkAction:async (root, action, work) => { ownerCalls.push(['nativeWorkAction', root, action, work]); return {ok:true}; },
    decideSocialApproval:async body => { ownerCalls.push(['decideSocialApproval', body]); return {ok:true}; },
  };
  win.ARCHHUB_EXISTING_WORKSHOP = new Proxy(owner, {get:(target, key) => key in target || typeof key !== 'string' ||
    key === 'then' ? target[key] : () => new Promise(() => {})});
  win.ARCHHUB_AGENT = async text => { agentCalls.push(text); return 'ok'; };
  win.ARCHHUB_TOOL_HUB = {ok:true, tools:toolRows, waiting:waitingItems};
  win.ARCHHUB_LIVE = {sessions:[
      {id:'graph-a', title:'Mine', state:'idle', file:'mine.graph', owner:'mine'},
      {id:'graph-b', title:'Scheduled', state:'scheduled', file:'daily.graph'},
      {id:'graph-c', title:'Workflow', state:'workflow', file:'run.graph'},
    ], currentGraph:'graph-a',
    hosts:options.hosts || [{id:'r25', name:'Revit 2025', state:'connected', file:'Tower.rvt'}],
    connectors:[{id:'revit', drive:true}], graph, memory:[{id:'m1', text:'Remember this', src:'test'}], skills:[]};
  Object.defineProperty(win.HTMLInputElement.prototype, 'click', {
    configurable:true,
    value:function click() { if (this.type === 'file') fileClicks.push(this.getAttribute('aria-label') || 'file'); },
  });
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') win.eval(read('nodelang/studio/compiled/' + file.output));
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const home = [...win.document.querySelectorAll('button')].find(node => node.textContent.trim() === '+');
  if (home) win.ReactDOM.flushSync(() => home.click());
  const close = () => { try { win.ReactDOM.flushSync(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  const button = label => [...win.document.querySelectorAll('button')].find(node => node.textContent.trim() === label);
  const settle = () => new Promise(resolve => win.setTimeout(resolve, 60));
  const setAccount = rec => accountCalls.push(['setAccount', rec]);
  const onSignOut = () => accountCalls.push(['onSignOut']);
  return {win, doc:win.document, button, graphCreates, fileClicks, agentCalls, ownerCalls, accountCalls, setAccount, onSignOut, settle, close};
}

test('Home composer shows the four design chip buttons and no raw model route chip', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    for (const label of ['/ node', '@ skill', '# host', '+ attach']) {
      assert.ok(studio.button(label), label + ' is a clickable Home composer chip');
    }
    assert.equal(studio.doc.querySelector('form').textContent.includes('openrouter/thinkingmachines/inkling:free'), false,
      'the raw route is not shown under the Home composer');
    assert.equal(studio.doc.body.textContent.includes('New blank graph'), false,
      'the design does not show a second blank-graph composer');
  } finally { studio.close(); }
});

test('F2: Home starts rail-only, renders six hub tool cards, and hides waiting at zero', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    assert.equal(studio.doc.body.textContent.includes('Search nodes'), false,
      'Home does not render the Nodes library panel');
    assert.equal(studio.doc.querySelectorAll('[data-tool-rail]').length, 6,
      'rail has the six tool icons');
    assert.equal(studio.doc.querySelectorAll('[data-tool-card]').length, 6,
      'Home has the six tool cards');
    for (const id of ['studio', 'workshop', 'brain', 'baboom', 'connectors', 'cloud']) {
      assert.ok(studio.doc.querySelector(`[data-tool-card="${id}"]`), id + ' card exists');
      assert.ok(studio.doc.querySelector(`[data-tool-rail="${id}"]`), id + ' rail icon exists');
    }
    assert.equal(studio.doc.body.textContent.includes('Waiting for you'), false);
    assert.match(studio.doc.querySelector('[data-tool-card="studio"]').textContent, /StudioCanvas, chats and graph sessions\. 3 sessions · 0 running/);
  } finally { studio.close(); }
});

test('F1b: rail tools match the hub order, state tooltips, and 6px dot colours', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    const tools = [...studio.doc.querySelectorAll('[data-tool-rail]')];
    assert.deepEqual(tools.map(node => node.getAttribute('data-tool-rail')),
      ['studio', 'workshop', 'brain', 'baboom', 'connectors', 'cloud']);
    assert.deepEqual(tools.map(node => node.title), [
      'Studio \u00b7 running',
      'Workshop \u00b7 running',
      'Brain \u00b7 off',
      'BABOOM \u00b7 unknown',
      'Connectors \u00b7 running',
      'Cloud \u00b7 starting',
    ]);
    const expected = {
      studio:'rgb(47, 184, 106)',
      workshop:'rgb(47, 184, 106)',
      brain:'rgb(212, 142, 42)',
      baboom:'rgb(139, 131, 122)',
      connectors:'rgb(47, 184, 106)',
      cloud:'rgb(39, 194, 230)',
    };
    for (const button of tools) {
      const dot = button.querySelector('[data-tool-dot]');
      assert.equal(dot.style.width, '6px', button.title + ' dot is 6px');
      assert.equal(dot.style.height, '6px', button.title + ' dot is 6px');
      assert.equal(dot.style.background, expected[button.getAttribute('data-tool-rail')]);
    }
  } finally { studio.close(); }
});

test('F2: clicking an off tool opens the tool view first tab', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    studio.win.ReactDOM.flushSync(() => studio.doc.querySelector('[data-tool-rail="brain"]').click());
    await studio.settle();
    assert.equal(studio.doc.querySelector('[data-tool-view="brain"]')?.getAttribute('data-tool-tab'), 'facts');
    assert.match(studio.doc.body.textContent, /Brain/);
    assert.match(studio.doc.body.textContent, /Brain is off/);
  } finally { studio.close(); }
});

test('F1c: an off rail tool renders its hub empty state in the main area', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    studio.win.ReactDOM.flushSync(() => studio.doc.querySelector('[data-tool-rail="brain"]').click());
    await studio.settle();
    const main = studio.doc.querySelector('main[data-tool-view="brain"]');
    assert.ok(main, 'Brain opens in the main area');
    assert.match(main.textContent, /Brain is off/);
    assert.match(main.textContent, /What ArchHub remembers\. Everything else keeps running\./);
    assert.equal([...main.querySelectorAll('button')].some(node => node.textContent.trim() === 'Turn on'), false,
      'Brain has no fake generic owner toggle');
    assert.deepEqual(studio.ownerCalls, []);
  } finally { studio.close(); }
});

test('F1b: right-click on an on tool shows a six second in-panel off confirm', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    const baboom = studio.doc.querySelector('[data-tool-rail="baboom"]');
    studio.win.ReactDOM.flushSync(() => baboom.dispatchEvent(new studio.win.MouseEvent('contextmenu', {bubbles:true, cancelable:true})));
    await studio.settle();
    assert.match(studio.doc.body.textContent, /Switch BABOOM off\? Tools asking it will see 'BABOOM is off'\. \u00b7 Yes \u00b7 No/);
    assert.equal(studio.ownerCalls.length, 0, 'right-click does not stop until Yes');
    studio.win.ReactDOM.flushSync(() => studio.button('Yes').click());
    await studio.settle();
    assert.deepEqual(studio.ownerCalls, [['setBaboomStartup', 'off']]);
  } finally { studio.close(); }
});

test('F1: rail tool clicks open existing views', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    studio.win.ReactDOM.flushSync(() => [...studio.doc.querySelectorAll('[data-tool-card="brain"] button')]
      .find(node => node.textContent.trim() === 'OPEN').click());
    assert.equal(studio.doc.querySelector('[data-tool-view="brain"]')?.getAttribute('data-tool-tab'), 'facts');
    studio.win.ReactDOM.flushSync(() => studio.win.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Escape', bubbles:true})));
    studio.win.ReactDOM.flushSync(() => studio.doc.querySelector('[data-tool-rail="studio"]').click());
    await studio.settle();
    assert.match(studio.doc.body.textContent, /ChatWorkshopCanvas/);
    assert.match(studio.doc.body.textContent, /Tool node/);
    studio.win.ReactDOM.flushSync(() => studio.button('+').click());
  } finally { studio.close(); }
});

test('F2: waiting popover is fed by the hub and shows Workshop approval metadata', async () => {
  const studio = await mountStudio({waiting:[{
    id:'wait-a', producer:'workshop_gate', root:'room-a', work:'work-a', input_digest:'a'.repeat(64),
    summary:'Approve wall opening', who:'Claude',
    for:'you', time:'09:14', plan_hash:'8f2c', file:'Nile_Tower.rvt', to:'Connectors',
    second_approval:true, approvals_done:1, approvals_required:2, ask_member:'Mona',
  }]});
  try {
    await studio.settle(); await studio.settle();
    assert.match(studio.doc.body.textContent, /Waiting for youApprove wall opening/);
    studio.win.ReactDOM.flushSync(() => studio.doc.querySelector('[data-waiting-trigger="home"]').click());
    assert.match(studio.doc.body.textContent, /Approve wall opening/);
    assert.match(studio.doc.body.textContent, /asked by Claude · for you · 09:14 · plan 8f2c · Nile_Tower\.rvt/);
    assert.match(studio.doc.body.textContent, /1 of 2 · needs another member/);
    assert.ok(studio.button('Open in Approvals'));
  } finally { studio.close(); }
});

test('F2U repair: Workshop waiting opens Approvals and has no popover decision buttons', async () => {
  const studio = await mountStudio({waiting:[{
    id:'wait-a', producer:'workshop_gate', root:'room-a', work:'work-a', input_digest:'b'.repeat(64),
    summary:'Approve wall opening', who:'Claude', for:'you',
  }]});
  try {
    await studio.settle(); await studio.settle();
    studio.win.ReactDOM.flushSync(() => studio.doc.querySelector('[data-waiting-trigger="home"]').click());
    const popover = studio.doc.querySelector('[data-waiting-popover]');
    assert.ok(popover);
    assert.equal([...popover.querySelectorAll('button')].some(node => node.textContent.trim() === 'Approve'), false);
    assert.equal([...popover.querySelectorAll('button')].some(node => node.textContent.trim() === 'Reject'), false);
    studio.win.ReactDOM.flushSync(() => [...popover.querySelectorAll('button')]
      .find(node => node.textContent.trim() === 'Open in Approvals').click());
    await studio.settle();
    const approvals = studio.doc.querySelector('[role="tab"][aria-label="Approvals"]');
    assert.equal(approvals?.getAttribute('aria-selected'), 'true');
    assert.deepEqual(studio.ownerCalls, []);
  } finally { studio.close(); }
});

test('F2U repair: social waiting keeps real decideSocialApproval controls', async () => {
  const studio = await mountStudio({waiting:[{
    id:'social-a', producer:'social_approve', delegation:'delegation-a', input_digest:'c'.repeat(64),
    summary:'Approve LinkedIn post', who:'BABOOM', for:'you',
  }]});
  try {
    await studio.settle(); await studio.settle();
    studio.win.ReactDOM.flushSync(() => studio.doc.querySelector('[data-waiting-trigger="home"]').click());
    studio.win.ReactDOM.flushSync(() => studio.button('Approve').click());
    await studio.settle();
    assert.deepEqual(JSON.parse(JSON.stringify(studio.ownerCalls)), [
      ['decideSocialApproval', {delegation:'delegation-a', input_digest:'c'.repeat(64), decision:'approve'}],
    ]);
  } finally { studio.close(); }
});

test('F2R owner decisions: unsupported waiting producers are refused and not marked delivered', async () => {
  const studio = await mountStudio({waiting:[{
    id:'wait-a', producer:'unknown_owner', summary:'Approve impossible action', who:'Claude', for:'you',
  }]});
  try {
    await studio.settle(); await studio.settle();
    studio.win.ReactDOM.flushSync(() => studio.doc.querySelector('[data-waiting-trigger="home"]').click());
    studio.win.ReactDOM.flushSync(() => studio.button('Approve').click());
    await studio.settle();
    assert.match(studio.doc.body.textContent, /No owner route is available/);
    assert.deepEqual(studio.ownerCalls, []);
    assert.equal(studio.doc.body.textContent.includes('approved · delivered'), false);
  } finally { studio.close(); }
});

test('F2R D1: placeholder tool stats are replaced from owner projections after the first tools poll', async () => {
  const studio = await mountStudio({tools:[
    {id:'studio', label:'Studio', state:'running', state_word:'RUNNING',
      description:'Canvas, chats and graph sessions.', stat_line:'… sessions · … running.',
      off_sentence:'Switched off. Sessions are kept.', wire_summary:'Studio → Brain · Connectors · Workshop'},
    {id:'workshop', label:'Workshop', state:'running', state_word:'RUNNING',
      description:'Projects, tasks and governed work.', stat_line:'… projects · … tasks.',
      off_sentence:'Switched off. Tasks are paused.', wire_summary:'Workshop → Studio · Connectors · Brain'},
    {id:'brain', label:'Brain', state:'off', state_word:'OFF',
      description:'Memory, facts and local classification.', stat_line:'… facts · … stay on this machine.',
      off_sentence:'Switched off. Nothing is remembered or recalled.', wire_summary:'Brain → Studio · Workshop · Cloud',
      empty_title:'Brain is off', empty_line:'What ArchHub remembers. Everything else keeps running.'},
    {id:'baboom', label:'BABOOM', state:'running', state_word:'RUNNING',
      description:'Desktop companion and approved execution.', stat_line:'quiet off · speaks at most … times an hour.',
      off_sentence:'Switched off. No companion on the desktop.', wire_summary:'BABOOM ← Studio · Workshop'},
    {id:'connectors', label:'Connectors', state:'running', state_word:'RUNNING',
      description:'Host bridges and Speckle access.', stat_line:'…/… hosts running · Speckle not signed in.',
      off_sentence:'Switched off. No reads or writes to your programs.', wire_summary:'Connectors → Studio · Workshop · Speckle'},
    {id:'cloud', label:'Cloud', state:'starting', state_word:'STARTING',
      description:'Devices, grants and cloud agents.', stat_line:'not signed in.',
      off_sentence:'Switched off. Works on this machine only.', wire_summary:'Cloud ← Brain · Workshop'},
  ]});
  try {
    await studio.settle(); await studio.settle();
    assert.match(studio.doc.querySelector('[data-tool-card="studio"]').textContent, /3 sessions · 0 running/);
    assert.match(studio.doc.querySelector('[data-tool-card="workshop"]').textContent, /1 project · 1 task/);
    assert.match(studio.doc.querySelector('[data-tool-card="connectors"]').textContent, /1\/1 hosts running/);
    assert.match(studio.doc.querySelector('[data-tool-card="baboom"]').textContent, /Starts with Windows: on · runtime unknown/);
    assert.equal(studio.doc.querySelector('[data-tool-card="studio"]').textContent.includes('…'), false);
    assert.equal(studio.doc.querySelector('[data-tool-card="workshop"]').textContent.includes('…'), false);
    assert.equal(studio.doc.querySelector('[data-tool-card="connectors"]').textContent.includes('…'), false);
    assert.equal(studio.doc.querySelector('[data-tool-card="baboom"]').textContent.includes('…'), false);
  } finally { studio.close(); }
});

test('F2R D2: Workshop OPEN opens the Workshop tool view on the Projects tab, not Studio Chat', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    studio.win.ReactDOM.flushSync(() => [...studio.doc.querySelectorAll('[data-tool-card="workshop"] button')]
      .find(node => node.textContent.trim() === 'OPEN').click());
    await studio.settle();
    assert.equal(studio.doc.querySelector('[data-tool-view="workshop"]')?.getAttribute('data-tool-tab'), 'projects');
    assert.equal(studio.doc.querySelector('textarea[aria-label="Message the model"]'), null);
  } finally { studio.close(); }
});

test('F2R D3: BABOOM OPEN renders the companion settings body, never the Hosts panel', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    studio.win.ReactDOM.flushSync(() => [...studio.doc.querySelectorAll('[data-tool-card="baboom"] button')]
      .find(node => node.textContent.trim() === 'OPEN').click());
    await studio.settle();
    const main = studio.doc.querySelector('[data-tool-view="baboom"]');
    assert.ok(main, 'BABOOM opens its tool view');
    assert.match(main.textContent, /Start BABOOM when ArchHub opens/);
    assert.equal(main.textContent.includes('Local clients the host probe found on this machine'), false);
  } finally { studio.close(); }
});

test('F2R D4: Ctrl+Shift+W opens an empty waiting popover that says Nothing waiting', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    studio.win.ReactDOM.flushSync(() => studio.win.dispatchEvent(new studio.win.KeyboardEvent('keydown', {
      key:'W', ctrlKey:true, shiftKey:true, bubbles:true,
    })));
    await studio.settle();
    assert.match(studio.doc.querySelector('[data-waiting-popover]')?.textContent || '', /Nothing waiting\./);
  } finally { studio.close(); }
});

test('F2R cosmetic: tool wire summaries can wrap to two lines and expose the full text in a tooltip', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    const wire = studio.doc.querySelector('[data-tool-wire="studio"]');
    assert.equal(wire.title, 'Studio → Brain · Connectors · Workshop');
    assert.equal(wire.style.whiteSpace, 'normal');
    assert.match(wire.style.WebkitLineClamp || wire.style.webkitLineClamp || '', /2/);
  } finally { studio.close(); }
});

test('F2R owner controls: only BABOOM renders an on/off switch and uses setBaboomStartup', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    const switches = [...studio.doc.querySelectorAll('[data-tool-card] [role="switch"]')];
    assert.deepEqual(switches.map(node => node.closest('[data-tool-card]').getAttribute('data-tool-card')), ['baboom']);
    studio.win.ReactDOM.flushSync(() => switches[0].click());
    await studio.settle();
    assert.deepEqual(studio.ownerCalls, [['setBaboomStartup', 'off']]);
  } finally { studio.close(); }
});

test('F2U repair: BABOOM card separates Windows startup from runtime state', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    const card = studio.doc.querySelector('[data-tool-card="baboom"]');
    assert.match(card.textContent, /UNKNOWN/);
    assert.match(card.textContent, /Starts with Windows: on/);
    assert.match(card.textContent, /runtime unknown/);
    assert.doesNotMatch(card.textContent, /RUNNING/);
  } finally { studio.close(); }
});

test('F2R cloud tool view receives real account callbacks', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    studio.win.ReactDOM.flushSync(() => [...studio.doc.querySelectorAll('[data-tool-card="cloud"] button')]
      .find(node => node.textContent.trim() === 'OPEN').click());
    await studio.settle();
    assert.equal(studio.doc.querySelector('[data-tool-view="cloud"]')?.getAttribute('data-tool-tab'), 'account');
    const source = read('nodelang/studio/studio-lm.jsx');
    assert.doesNotMatch(source, /<SettingsAccount account=\{account\} setAccount=\{\(\) => \{\}\} onSignOut=\{\(\) => \{\}\}/);
  } finally { studio.close(); }
});

test('F2R tool wire button does not invent a tool:* focus root', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    studio.win.ReactDOM.flushSync(() => studio.doc.querySelector('[data-tool-wire="brain"]').click());
    await studio.settle();
    assert.equal(studio.doc.querySelector('[data-tool-view="brain"]')?.getAttribute('data-tool-tab'), 'facts');
    assert.equal(studio.doc.body.textContent.includes('tool:brain'), false);
  } finally { studio.close(); }
});

test('Home composer chips call their existing handlers', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    studio.win.ReactDOM.flushSync(() => studio.button('/ node').click());
    assert.ok([...studio.doc.querySelectorAll('span')].some(node => node.textContent === 'Node library'));
    studio.win.ReactDOM.flushSync(() => studio.win.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Escape', bubbles:true})));
    studio.win.ReactDOM.flushSync(() => studio.button('@ skill').click());
    assert.ok(studio.doc.body.textContent.includes('Search saved skills'),
      '@ skill opens the existing Skills panel');
    studio.win.ReactDOM.flushSync(() => studio.button('# host').click());
    assert.ok(studio.doc.querySelector('[role="menu"] button')?.textContent.includes('Revit 2025'),
      '# host opens a live host picker');
    studio.win.ReactDOM.flushSync(() => studio.doc.querySelector('[role="menu"] button').click());
    assert.match(studio.doc.querySelector('textarea[aria-label="Start a new session"]').value, /#Revit 2025/);
    studio.win.ReactDOM.flushSync(() => studio.button('+ attach').click());
    assert.deepEqual(studio.fileClicks, ['Attach file to new session']);
  } finally { studio.close(); }
});

test('Home # host chip opens known host starters when no host is live', async () => {
  const studio = await mountStudio({hosts:[
    {id:'r25', name:'Revit 2025', state:'off', file:'\u2014'},
    {id:'acad', name:'AutoCAD', state:'absent', file:'\u2014'},
    {id:'rhino', name:'Rhino 8', state:'off', file:'\u2014'},
    {id:'blender', name:'Blender 5.1', state:'off', file:'\u2014'},
    {id:'3ds', name:'3ds Max', state:'off', file:'\u2014'},
  ]});
  try {
    await studio.settle(); await studio.settle();
    assert.ok(studio.button('# host'), '# host remains visible when no host is live');
    studio.win.ReactDOM.flushSync(() => studio.button('# host').click());
    const menuItems = [...studio.doc.querySelectorAll('[role="menu"] button')].map(node => node.textContent.trim());
    for (const name of ['Revit', 'AutoCAD', 'Rhino', 'Blender', '3ds Max']) {
      assert.ok(menuItems.some(text => text.includes(name) && text.includes('Start')), name + ' has a Start action');
    }
    studio.win.ReactDOM.flushSync(() => [...studio.doc.querySelectorAll('[role="menu"] button')]
      .find(node => node.textContent.includes('Revit')).click());
    await studio.settle();
    assert.deepEqual(studio.agentCalls, ['open Revit']);
    assert.equal(studio.doc.querySelector('textarea[aria-label="Start a new session"]').value, '',
      'no-live-host start does not insert a dead #host token');
  } finally { studio.close(); }
});

test('Home Sessions header creates a new graph through ARCHHUB_GRAPH_CREATE', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    const before = studio.doc.querySelectorAll('form').length;
    studio.win.ReactDOM.flushSync(() => studio.button('+ new graph').click());
    const input = studio.doc.querySelector('input[aria-label="New graph name"]');
    assert.ok(input, '+ new graph opens the inline name field');
    const set = Object.getOwnPropertyDescriptor(studio.win.HTMLInputElement.prototype, 'value').set;
    studio.win.ReactDOM.flushSync(() => { set.call(input, 'Site options'); input.dispatchEvent(new studio.win.Event('input', {bubbles:true})); });
    studio.win.ReactDOM.flushSync(() => studio.button('Create').click());
    await studio.settle();
    assert.deepEqual(studio.graphCreates, ['Site options']);
    assert.equal(before, 1, 'Home has only the session-start form before the inline graph field opens');
  } finally { studio.close(); }
});
