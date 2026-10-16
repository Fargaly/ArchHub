const {settingsNavigator} = require('./settings_navigation_helpers.cjs');
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
        description:'Desktop companion and approved execution.', stat_line:'Attached signed runtime · 1 runtime session.',
        off_sentence:'Switched off. No companion on the desktop.', wire_summary:'BABOOM ← Studio · Workshop'},
      {id:'connectors', label:'Connectors', state:'running', state_word:'RUNNING',
        description:'Host bridges and Speckle access.', stat_line:'1/1 hosts connected · Speckle connected.',
        off_sentence:'Switched off. No reads or writes to your programs.', wire_summary:'Connectors → Studio · Workshop · Speckle'},
      {id:'cloud', label:'Cloud', state:'starting', state_word:'STARTING',
        description:'Devices, grants and cloud agents.', stat_line:'Not signed in.',
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
  if(options.nativeWork)graph.nodes.push({id:options.nativeWork.work,title:'Approve wall opening',status:'awaiting_approval',params:[]});
  const snapshot = {canvas:{graph_id:'graph-a', root:'scope-a', revision:7, authorization},
    workshops:[{root:'room-a', label:'General Workshop', is_general:true}],
    nativeWork:options.nativeWork || {state:'awaiting_approval', work:'Layer choice', review_text:'Pick a layer', approved:false},
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
  if (options.loadHosts) win.ARCHHUB_LOAD_HOSTS = options.loadHosts;
  Object.defineProperty(win.HTMLInputElement.prototype, 'click', {
    configurable:true,
    value:function click() { if (this.type === 'file') fileClicks.push(this.getAttribute('aria-label') || 'file'); },
  });
  win.eval(read('nodelang/studio/vendor/react.js'));
  win.eval(read('nodelang/studio/vendor/react-dom.js'));
  for (const file of manifest.files) {
    if (file.source !== 'mount.jsx') {
      let code = read('nodelang/studio/compiled/' + file.output);
      if (options.exposeInspector && file.source === 'studio-lm.jsx') {
        assert.ok(code.includes('window.StudioLM=StudioLM;'), 'actual compiled Studio export exists');
        code = code.replace('window.StudioLM=StudioLM;', 'window.__InferenceInspector=InferenceInspector;window.StudioLM=StudioLM;');
      }
      win.eval(code);
    }
  }
  win.eval('window.__studioRoot=ReactDOM.createRoot(document.getElementById("root")); ReactDOM.flushSync(()=>window.__studioRoot.render(React.createElement(StudioLM)));');
  const home = [...win.document.querySelectorAll('button')].find(node => node.title === 'All sessions');
  if (home) win.ReactDOM.flushSync(() => home.click());
  const close = () => { try { win.ReactDOM.flushSync(() => win.__studioRoot.unmount()); } finally { dom.window.close(); } };
  const button = label => [...win.document.querySelectorAll('button')].find(node => node.textContent.trim() === label);
  const settle = () => new Promise(resolve => win.setTimeout(resolve, 60));
  const setAccount = rec => accountCalls.push(['setAccount', rec]);
  const onSignOut = () => accountCalls.push(['onSignOut']);
  return {win, doc:win.document, button, graphCreates, fileClicks, agentCalls, ownerCalls, accountCalls, setAccount, onSignOut, settle, close};
}

async function openSettingsHub(studio) {
  const settings = studio.doc.querySelector('[title="Settings"]');
  assert.ok(settings, 'actual Studio Settings control exists');
  if (!studio.doc.querySelector('[data-settings54-shell]')) {
    studio.win.ReactDOM.flushSync(() => settings.click());
    await studio.settle();
  }
  const nav = settingsNavigator({doc:studio.doc, flush:action => studio.win.ReactDOM.flushSync(action), settle:studio.settle});
  const panel = await nav.tab('Hub');
  assert.equal(panel.querySelectorAll('[data-tool-card]').length, 6, 'Settings Hub has the six tool cards');
  return panel;
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

test('F2/H1: Settings Connections Hub alone shows six tool cards and Home hides waiting at zero', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    assert.equal(studio.doc.body.textContent.includes('Search nodes'), false,
      'Home does not render the Nodes library panel');
    assert.equal([...studio.doc.querySelectorAll('[data-tool-rail]')]
      .some(node => ['studio', 'workshop', 'brain', 'baboom', 'connectors', 'cloud'].includes(node.getAttribute('data-tool-rail'))),
      false, 'tools are not icon-rail entries');
    assert.equal(studio.doc.querySelector('[data-home-tools]'), null, 'Home has no duplicate Tools section');
    assert.equal(studio.doc.body.textContent.includes('Waiting for you'), false);
    const hub = await openSettingsHub(studio);
    assert.deepEqual([...hub.querySelectorAll('[data-tool-card]')].map(card => card.getAttribute('data-tool-card')),
      ['studio', 'workshop', 'brain', 'baboom', 'connectors', 'cloud'], 'Hub has the six tool cards');
    assert.equal(studio.doc.querySelectorAll('[data-tool-card]').length, 6, 'only Hub mounts the cards');
    for (const card of hub.querySelectorAll('[data-tool-card]')) {
      assert.ok(card.querySelector('[data-tool-description]') && card.querySelector('[data-tool-stat]') && card.querySelector('[data-tool-open]'),
        card.getAttribute('data-tool-card') + ' card has the same rows: description, one stat line, the open mark');
      assert.equal(card.getAttribute('tabindex'), '0', 'the card is the keyboard-focusable open control');
      assert.match(card.getAttribute('aria-label'), /^Open /, 'the card has an accessible open name');
    }
    assert.equal(hub.querySelector('[data-tool-grid]').style.gridTemplateColumns, 'repeat(3, minmax(0, 1fr))',
      'Hub uses the shared three-column card grid');
    for (const card of hub.querySelectorAll('[data-tool-card]')) {
      assert.equal(card.style.flex.split(' ')[0], '1', 'each card fills its grid cell, so a row is one even height');
      assert.equal(card.parentElement.style.display, 'flex', 'the cell lets the card stretch');
    }
    for (const id of ['studio', 'workshop', 'brain', 'baboom', 'connectors', 'cloud']) {
      assert.ok(hub.querySelector(`[data-tool-card="${id}"]`), id + ' Hub tool card exists');
    }
    assert.equal(studio.doc.body.textContent.includes('Waiting for you'), false);
    assert.match(hub.querySelector('[data-tool-card="studio"]').textContent, /StudioCanvas, chats and graph sessions\.\s*3 sessions · 0 running/);
  } finally { studio.close(); }
});

test('F1b: Hub tool cards keep order, state words, and 6px dot colours', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    const hub = await openSettingsHub(studio);
    const tools = [...hub.querySelectorAll('[data-tool-card]')];
    assert.deepEqual(tools.map(node => node.getAttribute('data-tool-card')),
      ['studio', 'workshop', 'brain', 'baboom', 'connectors', 'cloud']);
    assert.deepEqual(tools.map(node => node.querySelector('[data-tool-dot]').nextElementSibling.textContent.trim()), [
      'RUNNING',
      'RUNNING',
      'OFF',
      'RUNNING',
      'Connected',
      'STARTING',
    ]);
    const expected = {
      studio:'rgb(47, 184, 106)',
      workshop:'rgb(47, 184, 106)',
      brain:'rgb(212, 142, 42)',
      baboom:'rgb(47, 184, 106)',
      connectors:'rgb(47, 184, 106)',
      cloud:'rgb(39, 194, 230)',
    };
    for (const button of tools) {
      const dot = button.querySelector('[data-tool-dot]');
      assert.equal(dot.style.width, '6px', button.getAttribute('data-tool-card') + ' dot is 6px');
      assert.equal(dot.style.height, '6px', button.getAttribute('data-tool-card') + ' dot is 6px');
      assert.equal(dot.style.background, expected[button.getAttribute('data-tool-card')]);
    }
    assert.equal(studio.doc.querySelectorAll('[data-tool-card]').length, 6, 'the Hub has no duplicate card owner');
  } finally { studio.close(); }
});

test('F2/CP1: clicking an off tool opens its Settings > Hub card over the current screen, never a page', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    const hubPanel = await openSettingsHub(studio);
    studio.win.ReactDOM.flushSync(() => hubPanel.querySelector('[data-tool-card="brain"]').click());
    await studio.settle();
    assert.equal(studio.doc.querySelector('[data-tool-view]'), null, 'no full-window tool page');
    const nav = settingsNavigator({doc:studio.doc, flush:action => studio.win.ReactDOM.flushSync(action), settle:studio.settle});
    const hub = await nav.capability('Hub');
    assert.ok(hub, 'Settings is open');
    const panel = await nav.tab('Hub');
    const card = panel.querySelector('[data-tool-card="brain"]');
    assert.ok(card, 'the Hub shows the Brain card, which states it is off');
  } finally { studio.close(); }
});

test('CP1: an off Hub tool card keeps the screen under it, so its composer stays mounted', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    assert.ok(studio.doc.querySelector('textarea[aria-label="Start a new session"]'), 'Home composer before');
    const hubPanel = await openSettingsHub(studio);
    studio.win.ReactDOM.flushSync(() => hubPanel.querySelector('[data-tool-card="brain"]').click());
    await studio.settle();
    assert.ok(studio.doc.querySelector('textarea[aria-label="Start a new session"]'), 'Home composer still mounted under Settings');
    assert.equal(studio.doc.querySelector('main[data-tool-view]'), null, 'no page replaced the screen');
    assert.deepEqual(studio.ownerCalls, [], 'opening never toggles the owner');
  } finally { studio.close(); }
});

test('F1b: right-click on an on Hub tool card shows a six second in-panel off confirm', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    const hub = await openSettingsHub(studio);
    const baboom = hub.querySelector('[data-tool-card="baboom"]').parentElement;
    studio.win.ReactDOM.flushSync(() => baboom.dispatchEvent(new studio.win.MouseEvent('contextmenu', {bubbles:true, cancelable:true})));
    await studio.settle();
    assert.match(studio.doc.body.textContent, /Switch BABOOM off\? Tools asking it will see 'BABOOM is off'\. \u00b7 Yes \u00b7 No/);
    assert.equal(studio.ownerCalls.length, 0, 'right-click does not stop until Yes');
    studio.win.ReactDOM.flushSync(() => studio.button('Yes').click());
    await studio.settle();
    assert.deepEqual(studio.ownerCalls, [['setBaboomStartup', 'off']]);
  } finally { studio.close(); }
});

// Ping F6a p2: the Connectors card and Hosts badge still share the same count. The app-frame status
// strip now names the connected program/document instead of exposing server/port host tallies.
test('F6a: host count stays in Connectors and Hosts badge; the status strip names the connected program', async () => {
  const studio = await mountStudio({hosts:[
    {id:'r25', name:'Revit 2025', state:'connected'}, {id:'acad', name:'AutoCAD', state:'listening'},
    {id:'rh8', name:'Rhino 8', state:'off'}, {id:'xl', name:'Excel', state:'installed'}]});
  try {
    await studio.settle(); await studio.settle();
    const hubPanel = await openSettingsHub(studio);
    const card = hubPanel.querySelector('[data-tool-card="connectors"]');
    assert.ok(card, 'Hub draws the Connectors card');
    assert.match(card.querySelector('[data-tool-stat]').textContent, /^2\/4 hosts running\.$/, 'card: 2 of the 4 listed hosts run');
    assert.match(studio.doc.body.textContent, /●\s*Connected.*Revit 2025/, 'status bar: connected program, not server tally');
    assert.equal(/server\s*:|2\/4 hosts|0\/0/.test(studio.doc.querySelector('footer')?.textContent || ''), false,
      'status strip has no server/host tally text');
    const hub = await openSettingsHub(studio);
    const nav = settingsNavigator({doc:studio.doc, flush:action => studio.win.ReactDOM.flushSync(action), settle:studio.settle});
    const hosts = await nav.tab('Hosts');
    assert.match(hosts.querySelector('[data-connectors-bar]').textContent, /2\/4 running/, 'Hosts owner carries the same 2/4 count');
  } finally { studio.close(); }
});

// Ping F6a v3 p2: the mounted Studio reads the Hosts list at start. Before that, the status strip must
// use the approved checking sentence, never 0/0; after that it names the connected program.
test('F6a v3: the mounted Studio reads the Hosts list; status never shows 0/0', async () => {
  const rows = [{id:'r25', name:'Revit 2025', state:'connected'}, {id:'acad', name:'AutoCAD', state:'listening'},
    {id:'rh8', name:'Rhino 8', state:'off'}, {id:'xl', name:'Excel', state:'installed'}, {id:'wd', name:'Word', state:'installed'}];
  let release;
  const answered = new Promise(resolve => { release = resolve; });
  const studio = await mountStudio({hosts:[], loadHosts:async () => { await answered; return {hosts:rows, connectors:rows}; }});
  try {
    await studio.settle();
    const strip = () => studio.doc.querySelector('footer')?.textContent || '';
    const hubPanel = await openSettingsHub(studio);
    const card = () => hubPanel.querySelector('[data-tool-card="connectors"] [data-tool-stat]')?.textContent;
    assert.match(strip(), /Checking programs/, 'before the list is read the strip says so, never 0/0: ' + strip());
    assert.equal(/0\/0|server\s*:/.test(strip()), false, 'before read the strip has no zero/server tally: ' + strip());
    assert.equal(card(), 'Checking hosts.', 'before the list is read the card says so, never another number');
    release();
    for (let i = 0; i < 50 && !/Connected/.test(strip()); i += 1) await studio.settle();
    assert.match(strip(), /Connected.*Revit 2025/, 'status bar: connected host is named');
    assert.equal(/2\/5 hosts|server\s*:/.test(strip()), false, 'status bar no longer owns the host tally');
    assert.equal(card(), '2/4 hosts running.', 'Connectors card: Excel and Word share one Office row');
    const hub = await openSettingsHub(studio);
    const nav = settingsNavigator({doc:studio.doc, flush:action => studio.win.ReactDOM.flushSync(action), settle:studio.settle});
    const hosts = await nav.tab('Hosts');
    assert.match(hosts.querySelector('[data-connectors-bar]').textContent, /2\/4 running/, 'Hosts owner agrees with the folded Office count');
    assert.ok(hub, 'Settings opened');
  } finally { studio.close(); }
});

// Ping F6a: a card's dot says what its word says.
test('F6a: each tool dot follows its word: green only when the card says it runs', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    const green = new studio.win.Option().style; green.color = '#2fb86a';
    const hub = await openSettingsHub(studio);
    assert.equal(hub.querySelectorAll('[data-tool-card]').length, 6, 'all six dots are checked');
    for (const card of hub.querySelectorAll('[data-tool-card]')) {
      const dot = card.querySelector('[data-tool-dot]');
      const word = dot.nextElementSibling.textContent.trim().toUpperCase();
      const down = /^(OFF|NOT\b|DIDN'T|FAILED|STOPPED|DISCONNECTED)/.test(word);
      const pending = !down && /STARTING|CHECKING|UNKNOWN|WAITING/.test(word);
      const isGreen = dot.style.background === green.color;
      assert.equal(isGreen, !down && !pending, card.getAttribute('data-tool-card') + ' (' + word + ') dot is ' + dot.style.background);
    }
  } finally { studio.close(); }
});

test('F1: Settings Hub card click opens that tool\'s Settings tab; Studio Hub card opens Canvas', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    const hub = await openSettingsHub(studio);
    assert.equal([...hub.querySelectorAll('[data-tool-card] button')].some(node => node.textContent.trim() === 'OPEN'), false,
      'Tool cards have no separate OPEN pill');
    studio.win.ReactDOM.flushSync(() => hub.querySelector('[data-tool-card="connectors"]').click());
    await studio.settle();
    assert.equal(studio.doc.querySelector('[data-tool-view]'), null, 'no full-window tool page');
    const nav = settingsNavigator({doc:studio.doc, flush:action => studio.win.ReactDOM.flushSync(action), settle:studio.settle});
    const hosts = await nav.capability('Hosts');
    assert.ok(hosts, 'Connectors opens the Settings-owned Hosts behavior');
    assert.match((await nav.tab('Hosts')).textContent, /Local clients|Revit|AutoCAD|Hosts/i, 'Hosts behavior panel is shown');
    studio.win.ReactDOM.flushSync(() => studio.win.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Escape', bubbles:true})));
    const studioHub = await openSettingsHub(studio);
    studio.win.ReactDOM.flushSync(() => studioHub.querySelector('[data-tool-card="studio"]').click());
    await studio.settle();
    assert.ok(studio.doc.querySelector('[role="region"][aria-label="Workflow canvas"]'), 'Studio card opens the Studio canvas');
  } finally { studio.close(); }
});

test('082: the visible shared card is fed by the hub and preserves Workshop approval metadata', async () => {
  const studio = await mountStudio({waiting:[{
    id:'wait-a', producer:'workshop_gate', root:'room-a', work:'work-a', input_digest:'a'.repeat(64),
    summary:'Approve wall opening', who:'Claude',
    for:'you', time:'09:14', plan_hash:'8f2c', file:'Nile_Tower.rvt', to:'Connectors',
    second_approval:true, approvals_done:1, approvals_required:2, ask_member:'Mona',
  }]});
  try {
    await studio.settle(); await studio.settle();
    assert.match(studio.doc.body.textContent, /Approve wall opening/);
    assert.ok(studio.doc.querySelector('[data-home-results] [data-approval-component="shared"]'));
    assert.match(studio.doc.body.textContent, /Approve wall opening/);
    assert.match(studio.doc.body.textContent, /1 needs your OK/);
    assert.equal(studio.doc.querySelector('[data-home-design]').dataset.homeDesign,'082');
    assert.equal(studio.doc.querySelectorAll('[data-home-results] [data-approval-component="shared"]').length,1);
  } finally { studio.close(); }
});

test('F2U repair: Workshop waiting uses one shared digest approval and Review opens the same Workshop', async () => {
  const studio = await mountStudio({waiting:[{
    id:'wait-a', producer:'workshop_gate', root:'room-a', work:'work-a', input_digest:'b'.repeat(64),
    summary:'Approve wall opening', who:'Claude', for:'you',
  }],nativeWork:{root:'room-a',scope:'scope-a',owner:'owner-a',view:'view-a',work:'work-a',state:'awaiting_approval',mode:'agent',review_text:'Approve wall opening',input_digest:'b'.repeat(64),approved:false}});
  try {
    await studio.settle(); await studio.settle();
    assert.ok(studio.doc.querySelector('[data-home-results] [data-approval-component="shared"]'));
    const popover = studio.doc.querySelector('[data-home-results]');
    assert.ok(popover);
    const cards=popover.querySelectorAll('[data-approval-component="shared"]');assert.equal(cards.length,1);
    const buttons=[...cards[0].querySelectorAll('button')];
    assert.deepEqual(buttons.map(node=>node.textContent.trim()),['Approve','Decline']);
    assert.equal([...popover.querySelectorAll('button')].filter(node=>/^Approve/.test(node.textContent.trim())&&!node.closest('[data-approval-component="shared"]')).length,0,'no parallel popover approval control');
    assert.equal([...popover.querySelectorAll('button')].some(node=>node.textContent.trim()==='Reject'),false);
    assert.deepEqual(studio.ownerCalls,[],'opening the review never auto-approves');
    studio.win.ReactDOM.flushSync(()=>{buttons[0].click();buttons[0].click();});
    await studio.settle();await studio.settle();
    assert.deepEqual(studio.ownerCalls,[['approveNativeWork','room-a','b'.repeat(64)]],'shared approval binds the shown digest once');
    studio.win.ReactDOM.flushSync(() => studio.doc.querySelector('[data-rail-panel="Workshop"]').click());
    await studio.settle();
    assert.ok(studio.doc.querySelector('[data-workshop-s1]'), 'Open in Approvals enters the S1 Workshop view');
    assert.match(studio.doc.body.textContent, /waits for you/);
    assert.deepEqual(studio.ownerCalls,[['approveNativeWork','room-a','b'.repeat(64)]],'Review does not replay the accepted decision');
  } finally { studio.close(); }
});

test('F2U repair: social waiting keeps real decideSocialApproval controls', async () => {
  const studio = await mountStudio({waiting:[{
    id:'social-a', producer:'social_approve', delegation:'delegation-a', input_digest:'c'.repeat(64),
    summary:'Approve LinkedIn post', who:'BABOOM', for:'you',
  }]});
  try {
    await studio.settle(); await studio.settle();
    assert.ok(studio.doc.querySelector('[data-home-results] [data-approval-component="shared"]'));
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
    assert.ok(studio.doc.querySelector('[data-home-results] [data-approval-component="shared"]'));
    const approve=studio.button('Approve');
    assert.equal(approve.disabled,true,'unknown producer has no admitted decision route');
    assert.equal(approve.title,'Unavailable');
    studio.win.ReactDOM.flushSync(() => approve.click());
    await studio.settle();
    assert.equal(studio.doc.querySelector('[data-approval-component="shared"]')!==null,true,'refusal is visible through the single approval component');
    assert.deepEqual(studio.ownerCalls, []);
    assert.equal(studio.doc.body.textContent.includes('approved · delivered'), false);
  } finally { studio.close(); }
});

test('F2R D1: Settings Hub cards show owner state lines, no placeholders or plumbing', async () => {
  const studio = await mountStudio({tools:[
    {id:'studio', label:'Studio', state:'running', state_word:'RUNNING',
      description:'Canvas, chats and graph sessions.', stat_line:'3 sessions · 0 running.',
      off_sentence:'Switched off. Sessions are kept.', wire_summary:'Studio → Brain · Connectors · Workshop'},
    {id:'workshop', label:'Workshop', state:'running', state_word:'RUNNING',
      description:'Projects, tasks and governed work.', stat_line:'1 project · 1 task.',
      off_sentence:'Switched off. Tasks are paused.', wire_summary:'Workshop → Studio · Connectors · Brain'},
    {id:'brain', label:'Brain', state:'running', state_word:'RUNNING',
      description:'Memory, facts and local classification.', stat_line:'1 fact in local Brain.',
      off_sentence:'Switched off. Nothing is remembered or recalled.', wire_summary:'Brain → Studio · Workshop · Cloud',
      empty_title:'Brain is off', empty_line:'What ArchHub remembers. Everything else keeps running.'},
    {id:'baboom', label:'BABOOM', state:'running', state_word:'ATTACHED',
      description:'Desktop companion and approved execution.', stat_line:'Attached signed runtime · 1 runtime session.',
      off_sentence:'Switched off. No companion on the desktop.', wire_summary:'BABOOM ← Studio · Workshop'},
    {id:'connectors', label:'Connectors', state:'running', state_word:'RUNNING',
      description:'Host bridges and Speckle access.', stat_line:'1/1 hosts connected.',
      off_sentence:'Switched off. No reads or writes to your programs.', wire_summary:'Connectors → Studio · Workshop · Speckle'},
    {id:'cloud', label:'Cloud', state:'starting', state_word:'NOT SIGNED IN',
      description:'Devices, grants and cloud agents.', stat_line:'Not signed in.',
      off_sentence:'Switched off. Works on this machine only.', wire_summary:'Cloud ← Brain · Workshop'},
  ]});
  try {
    await studio.settle(); await studio.settle();
    const hub = await openSettingsHub(studio);
    assert.equal(hub.querySelectorAll('[data-tool-card]').length, 6);
    for (const text of [
      '3 sessions · 0 running.', '1 project · 1 task.', '1 fact in local Brain.',
      'Attached signed runtime · 1 runtime session.',
      '1/1 hosts running.', 'Not signed in.',
    ]) {
      assert.ok(hub.textContent.includes(text), 'missing owner state line: ' + text);
    }
    assert.doesNotMatch(hub.textContent, /unknown|UNKNOWN|…/);
    assert.doesNotMatch(hub.textContent, /Studio → Brain|Workshop → Studio|Brain → Studio|BABOOM ← Studio|Connectors → Studio|Cloud ← Brain|no device list owner|cloud session owner/);
  } finally { studio.close(); }
});

test('F2R D2 / WS-022: Workshop card opens the DSYS077 window and DSYS074 empty state without a board', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    const hub = await openSettingsHub(studio);
    studio.win.ReactDOM.flushSync(() => hub.querySelector('[data-tool-card="workshop"]').click());
    await studio.settle();
    assert.ok(studio.doc.querySelector('[data-workshop-s1]'), 'Workshop card opens the S1 Workshop view');
    assert.ok(studio.doc.querySelector('[data-workshop-empty]'),'empty authority opens the DSYS074 composer state');
    assert.equal(studio.doc.querySelector('[data-workshop-s1-canvas]'),null,'removed duplicate canvas stays absent');
    assert.equal(studio.doc.querySelector('[role="tablist"]'),null);
    assert.equal(studio.doc.querySelector('textarea[aria-label="Message the model"]'), null);
  } finally { studio.close(); }
});

test('F2R D3: BABOOM card opens Settings > BABOOM with the companion settings body, never the Hosts panel', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    const hub = await openSettingsHub(studio);
    studio.win.ReactDOM.flushSync(() => hub.querySelector('[data-tool-card="baboom"]').click());
    await studio.settle();
    assert.equal(studio.doc.querySelector('[data-tool-view="baboom"]'), null, 'no full-window BABOOM page (founder 2026-10-12)');
    const nav = settingsNavigator({doc:studio.doc, flush:action => studio.win.ReactDOM.flushSync(action), settle:studio.settle});
    const tab = await nav.capability('BABOOM');
    assert.ok(tab, 'Settings is open with its BABOOM tab');
    const main = await nav.tab('BABOOM');
    assert.match(main.textContent, /Speech budget|Start BABOOM/);
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

test('F2R cosmetic: tool cards hide plumbing wire summaries', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    const hub = await openSettingsHub(studio);
    assert.equal(hub.querySelector('[data-tool-wire]'), null);
    assert.doesNotMatch(hub.textContent, /Studio → Brain|Workshop → Studio|Brain → Studio|BABOOM ← Studio|Connectors → Studio|Cloud ← Brain/);
  } finally { studio.close(); }
});

test('F2R owner controls: only BABOOM renders an on/off switch and off-confirm works from Settings Hub', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    const hub = await openSettingsHub(studio);
    const switches = [...hub.querySelectorAll('[data-tool-card] [role="switch"]')];
    assert.deepEqual(switches.map(node => node.closest('[data-tool-card]').getAttribute('data-tool-card')), ['baboom']);
    studio.win.ReactDOM.flushSync(() => hub.querySelector('[data-tool-card="baboom"]').dispatchEvent(
      new studio.win.MouseEvent('contextmenu', {bubbles:true, cancelable:true})));
    await studio.settle();
    assert.match(studio.doc.body.textContent, /Switch BABOOM off\? Tools asking it will see 'BABOOM is off'\. · Yes · No/);
    assert.deepEqual(studio.ownerCalls, []);
    studio.win.ReactDOM.flushSync(() => studio.button('Yes').click());
    await studio.settle();
    assert.deepEqual(studio.ownerCalls, [['setBaboomStartup', 'off']]);
  } finally { studio.close(); }
});

test('F2U repair: BABOOM card states its runtime; Windows startup lives in Settings > BABOOM', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    const hub = await openSettingsHub(studio);
    const card = hub.querySelector('[data-tool-card="baboom"]');
    assert.doesNotMatch(card.textContent, /UNKNOWN|unknown|…/);
    assert.match(card.textContent, /RUNNING|ATTACHED/);
    assert.match(card.querySelector('[data-tool-stat]').textContent, /Attached signed runtime/);
    assert.doesNotMatch(card.textContent, /Starts with Windows/, 'startup detail is not packed into the card (Ping F6a)');
  } finally { studio.close(); }
});

test('F2R cloud card opens Settings > Account, the one place that states sign-in', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    const hub = await openSettingsHub(studio);
    studio.win.ReactDOM.flushSync(() => hub.querySelector('[data-tool-card="cloud"]').click());
    await studio.settle();
    assert.equal(studio.doc.querySelector('[data-tool-view="cloud"]'), null, 'no full-window Cloud page (founder 2026-10-12)');
    const nav = settingsNavigator({doc:studio.doc, flush:action => studio.win.ReactDOM.flushSync(action), settle:studio.settle});
    const account = await nav.capability('Account');
    assert.ok(account, 'Settings is open');
    assert.equal((await nav.tab('Account')).textContent.includes('Cloud status'), false, 'no second sign-in verdict');
    const source = read('nodelang/studio/studio-lm.jsx');
    assert.doesNotMatch(source, /tool === 'cloud' && <SettingsAccount/);
  } finally { studio.close(); }
});

test('F2R tool card keyboard open does not invent a tool:* focus root', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    const hub = await openSettingsHub(studio);
    studio.win.ReactDOM.flushSync(() => hub.querySelector('[data-tool-card="brain"]').dispatchEvent(
      new studio.win.KeyboardEvent('keydown', {key:'Enter', bubbles:true})));
    await studio.settle();
    assert.equal(studio.doc.querySelector('[data-tool-view]'), null, 'no full-window tool page');
    assert.equal(studio.doc.body.textContent.includes('tool:brain'), false);
  } finally { studio.close(); }
});

test('Home composer chips call their existing handlers', async () => {
  const studio = await mountStudio();
  try {
    await studio.settle(); await studio.settle();
    studio.win.ReactDOM.flushSync(() => studio.button('/ node').click());
    assert.ok([...studio.doc.querySelectorAll('span')].some(node => node.textContent === 'Library'));
    studio.win.ReactDOM.flushSync(() => studio.win.dispatchEvent(new studio.win.KeyboardEvent('keydown', {key:'Escape', bubbles:true})));
    studio.win.ReactDOM.flushSync(() => studio.button('@ skill').click());
    assert.ok(studio.doc.body.textContent.includes('Search saved skills'),
      '@ skill opens the existing Skills panel');
    studio.win.ReactDOM.flushSync(() => studio.doc.querySelector('[data-app-rail] [data-rail-panel="Home"]').click());
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

test('082 replaces the Sessions grid while Chats keeps the real graph list', async () => {
  const studio=await mountStudio();try {
    await studio.settle();await studio.settle();
    assert.equal(studio.button('+ new graph'),undefined,'067 inline graph form is removed');
    assert.equal(studio.doc.querySelectorAll('[data-home-page] form').length,1);
    studio.win.ReactDOM.flushSync(()=>studio.doc.querySelector('[data-rail-panel="Chats"]').click());
    await studio.settle();
    assert.match(studio.doc.body.textContent,/Mine|Scheduled|Workflow/,'saved graph navigation belongs to Chats');
  }finally{studio.close();}
});

test('LAZYONREL Chat shares the drive-aware Office-collapsed host total', async () => {
  const studio = await mountStudio({exposeInspector:true,hosts:[
    {id:'revit', name:'Revit', drive:'host.read', state:'connected', detail:'connected'},
    {id:'excel', name:'Excel', drive:'host.read', state:'connected', detail:'connected'},
    {id:'word', name:'Word', drive:'host.read', state:'installed', detail:'installed'},
    {id:'future', name:'Future host', drive:'', state:'connected', detail:'answering without a connector'},
  ]});
  try {
    const target = studio.doc.createElement('div'); studio.doc.body.appendChild(target);
    studio.win.__chatCountTarget = target;
    studio.win.eval('window.__chatCountRoot=ReactDOM.createRoot(window.__chatCountTarget); ReactDOM.flushSync(()=>window.__chatCountRoot.render(React.createElement(window.__InferenceInspector,{model:{name:"Court",vendor:"fake",col:"#ffffff"},setPickerOpen:()=>{}})));');
    const panel = target.querySelector('[data-chat-connectors]');
    assert.equal(panel.firstElementChild.textContent.trim(), 'CONNECTORS · 2', 'Chat counts Revit and one Office aggregate through the shared tally');
    assert.ok(panel.textContent.includes('Excel') && panel.textContent.includes('Word'), 'Office keeps both program names');
    const office = [...panel.children].find(row => row.textContent.includes('Excel') && row.textContent.includes('Word'));
    assert.equal(office.lastElementChild.textContent, 'Connected', 'the running Office aggregate stays connected in Chat');
    const green = studio.doc.createElement('span'); green.style.color = studio.win.AH.ok;
    assert.equal(office.lastElementChild.style.color, green.style.color, 'connected Office uses the live host tone');
    assert.equal(panel.textContent.includes('Future host'), false, 'an explicitly unwired answering probe never becomes a Chat connector');
  } finally {
    if (studio.win.__chatCountRoot) studio.win.ReactDOM.flushSync(() => studio.win.__chatCountRoot.unmount());
    studio.close();
  }
});
