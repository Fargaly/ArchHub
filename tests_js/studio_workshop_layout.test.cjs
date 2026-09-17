/* Workshop presets and the Chat · Workshop · Canvas switch on the real snapshot: no agents, tasks or progress are authored. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(process.env.ARCHHUB_WORKSPACE_TEST_PATH ||
  path.join(__dirname, '../nodelang/studio/studio-lm.jsx'), 'utf8');
const tokens = fs.readFileSync(path.join(__dirname, '../nodelang/studio/tokens.jsx'), 'utf8');

// The pane may read only palette names the shipped tokens.jsx defines; an unknown token throws.
const palette = tokens.slice(tokens.indexOf('window.AH = {'), tokens.indexOf('window.ArchHubTheme ='));
const LM = new Proxy(Object.fromEntries([...palette.matchAll(/^ {2}(\w+):/gm)].map(match => [match[1], 'token-' + match[1]])), {
  get:(held, key) => {
    if (key === 'rad') return {xs:3, sm:5, md:6, lg:8, xl:10, pill:999};
    if (typeof key === 'string' && !(key in held)) throw new Error('studio-lm.jsx reads an undefined token: ' + key);
    return held[key];
  }});

function modeHarness() {
  const start = source.indexOf('const workshopModeRoom =');
  const end = source.indexOf('const WsHeader =', start);
  assert.ok(start > 0 && end > start, 'the mode switch helpers are a slice of the shipped studio-lm.jsx');
  const context = vm.createContext({});
  vm.runInContext(source.slice(start, end) +
    '\nglobalThis.segments = workshopModeSegments; globalThis.choose = chooseWorkshopMode;', context);
  return context;
}

async function mount(component) {
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const start = source.indexOf('const WORKSHOP_LAYOUTS =');
  const end = source.indexOf('const WorkshopConversation =', start);
  assert.ok(start > 0 && end > start, 'the layout presets are a slice of the shipped studio-lm.jsx');
  const dom = new JSDOM('<div id="root"></div>');
  const oldWindow = global.window, oldDocument = global.document;
  global.window = dom.window; global.document = dom.window.document;
  global.IS_REACT_ACT_ENVIRONMENT = true;
  const context = vm.createContext({React, LM});
  vm.runInContext(transformSync(source.slice(start, end) +
    '\nglobalThis.Strip = WorkshopLayoutStrip; globalThis.Pane = WorkshopLayoutPane;', {loader:'jsx', format:'cjs'}).code, context);
  const root = createRoot(dom.window.document.getElementById('root'));
  const doc = dom.window.document;
  return {
    draw: async props => { await React.act(async () => root.render(React.createElement(context[component], props))); return doc; },
    click: async element => { await React.act(async () => { element.click(); }); },
    close: async () => {
      await React.act(async () => root.unmount());
      dom.window.close(); global.window = oldWindow; global.document = oldDocument;
      delete global.IS_REACT_ACT_ENVIRONMENT;
    },
  };
}
const rooms = [{root:'child-a', label:'Child', is_general:false}, {root:'general-a', label:'General', is_general:true}];
// The shipped snapshot shape (studio-existing-workshop.js publish()): one native Work status, no task list anywhere.
const nativeWork = {owner:'owner-a', view:'view-a', root:'workshop-a', scope:'scope-a', state:'idle', work:null, available_work:['work-a']};

test('Workshop is Chat with the held room, else the general room, else the first; no room disables the segment', () => {
  const {segments, choose} = modeHarness();
  const labels = view => segments(view).map(row => `${row.label}${row.active ? '*' : ''}${row.disabled ? '!' : ''}`).join(' ');
  assert.equal(labels({mode:'chat', conversationRoot:'', workshops:rooms}), 'Chat* Workshop Canvas');
  assert.equal(labels({mode:'chat', conversationRoot:'child-a', workshops:rooms}), 'Chat Workshop* Canvas');
  assert.equal(labels({mode:'canvas', conversationRoot:'child-a', workshops:rooms}), 'Chat Workshop Canvas*');
  assert.equal(labels({mode:'chat', conversationRoot:'', workshops:[]}), 'Chat* Workshop! Canvas');
  assert.equal(segments({mode:'chat', conversationRoot:'', workshops:[]})[1].title, 'No Workshop conversation in this scope');
  const calls = [];
  const view = (mode, conversationRoot, workshops = rooms) => ({mode, conversationRoot, workshops,
    setMode:value => calls.push(['mode', value]), setConversationRoot:value => calls.push(['root', value])});
  choose('workshop', view('chat', ''));                                   // the general room wins over the first row
  choose('workshop', view('canvas', 'child-a'));                          // the held room survives the return from Canvas
  choose('workshop', view('chat', 'child-a'));                            // already there: no write
  choose('chat', view('chat', 'child-a'));                                // Chat clears the root
  choose('chat', view('chat', ''));                                       // already plain Chat: no write
  choose('canvas', view('chat', 'child-a'));
  choose('workshop', view('chat', '', []));                               // no room in scope: no write
  choose('workshop', view('chat', '', [{root:'only-a', label:'Only'}])); // no general room: the first
  assert.deepEqual(calls, [['root', 'general-a'], ['root', 'child-a'], ['root', ''], ['mode', 'canvas'], ['root', 'only-a']]);
});

// Transcript rows in the shipped shape (Workshop messages projection): agents write notes that name a Work id.
const note = (root, sender, body) => ({root, sender_root:sender, body, state:'recorded', category:'note', recipient_roots:[]});
const transcriptRows = [
  note('m1', 'agent-a', 'Claimed Work assembly-instance:aaaaaaaa11112222.'),
  note('m2', 'agent-b', 'Please look at the export when you can.'),
  note('m3', 'agent-a', 'Submitted Work assembly-instance:aaaaaaaa11112222.'),
  note('m4', 'agent-b', 'Claimed Work assembly-instance:bbbbbbbb33334444.'),
  note('m5', 'agent-a', 'Claimed Work work:repair-export'),
  note('m6', 'agent-a', 'Gate failed for Work work:repair-export: pytest exit 1'),
];

test('task cards fold every event of one named Work into one card whose state is its latest verb', () => {
  {
    const context = vm.createContext({});
    const helpers = source.slice(source.indexOf('const WORKSHOP_WORK_REF ='), source.indexOf('const LM_SESSIONS ='));
    vm.runInContext(helpers + '\nglobalThis.items = workshopTaskItems;', context);
    const items = context.items(transcriptRows, [{id:'work:repair-export', title:'Repair export', status:'OPEN'}]);
    assert.deepEqual(Array.from(items, item => item.kind === 'task' ? `${item.title}|${item.state}|${item.events.map(e => e.root).join(',')}` : item.message.root), [
      'assembly-instance · aaaaaaaa|review|m1,m3', 'm2', 'assembly-instance · bbbbbbbb|run|m4', 'Repair export|block|m5,m6']);
    assert.equal(context.items([], []).length, 0);
    assert.equal(context.items([note('x', 'a', 'No Work named here.')], []).map(item => item.kind).join(), 'message');
  }
});

test('the task board draws the transcript-derived cards in state columns and an absent state without them', async () => {
  const {JSDOM} = await import('jsdom');
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const dom = new JSDOM('<div id="root"></div>');
  const oldWindow = global.window, oldDocument = global.document;
  global.window = dom.window; global.document = dom.window.document; global.IS_REACT_ACT_ENVIRONMENT = true;
  try {
    const context = vm.createContext({React, LM});
    vm.runInContext(transformSync(source.slice(source.indexOf('const WORKSHOP_WORK_REF ='), source.indexOf('const LM_SESSIONS =')) +
      source.slice(source.indexOf('const WORKSHOP_LAYOUTS ='), source.indexOf('const WorkshopConversation =')) +
      '\nglobalThis.Board = WorkshopTaskBoard; globalThis.items = workshopTaskItems; globalThis.Pane = WorkshopLayoutPane;', {loader:'jsx', format:'cjs'}).code, context);
    const root = createRoot(dom.window.document.getElementById('root'));
    const names = new Map([['agent-a', 'Codex'], ['agent-b', 'BABOOM']]);
    const picked = [];
    const cards = context.items(transcriptRows, []).filter(item => item.kind === 'task');
    await React.act(async () => root.render(React.createElement(context.Board, {cards, names, self:'', selected:'', onSelect:work => picked.push(work)})));
    const board = dom.window.document.querySelector('[aria-label="Workshop task board"]');
    assert.deepEqual([...board.querySelectorAll('h3')].map(h => h.textContent), ['NEEDS YOU', 'RUNNING', 'SUBMITTED']);
    assert.deepEqual([...board.querySelectorAll('[data-workshop-task]')].map(card => card.getAttribute('data-workshop-task')),
      ['work:repair-export', 'assembly-instance:bbbbbbbb33334444', 'assembly-instance:aaaaaaaa11112222']);
    await React.act(async () => { board.querySelector('[data-workshop-task]').click(); });
    assert.deepEqual(picked, ['work:repair-export']);
    await React.act(async () => root.render(React.createElement(context.Board, {cards:[], names, self:'', selected:'', onSelect:() => {}})));
    assert.equal(dom.window.document.querySelector('[role="status"]').textContent, 'No message on this page names a Work, so there is nothing to group.');
    await React.act(async () => root.render(React.createElement(context.Pane, {layout:'board', native:nativeWork, nodes:[], target:''})));
    assert.equal(dom.window.document.querySelector('section'), null, 'the board no longer draws in the participants column');
    await React.act(async () => root.unmount());
  } finally {
    dom.window.close(); global.window = oldWindow; global.document = oldDocument;
    delete global.IS_REACT_ACT_ENVIRONMENT;
  }
});

test('Chat + live graph draws only projected nodes, marks the admitted Work, and opens the Canvas only when it can', async () => {
  const modes = [];
  const {draw, click, close} = await mount('Pane');
  try {
    const empty = await draw({layout:'graph', native:null, nodes:[], target:'', setMode:value => modes.push(value)});
    const graph = empty.querySelector('[aria-label="Workshop live graph"]');
    assert.equal(graph.querySelector('h3').textContent, 'Live graph · 0 projected nodes');
    assert.equal(graph.querySelector('[role="status"]').textContent, 'No topology projection is held for this scope.');
    assert.equal(graph.querySelectorAll('[data-node]').length, 0);
    const nodes = [{id:'work-a', title:'Repair export', sub:'work', status:'OPEN'}, {id:'read-a', title:'Read DWG', sub:'cad.read_lines'}];
    const drawn = await draw({layout:'graph', native:null, nodes, target:'work-a', setMode:value => modes.push(value)});
    assert.equal(drawn.querySelector('h3').textContent, 'Live graph · 2 projected nodes');
    const rows = [...drawn.querySelectorAll('[data-node]')];
    assert.deepEqual(rows.map(row => row.getAttribute('data-node')), ['work-a', 'read-a']);
    assert.deepEqual(rows.map(row => row.getAttribute('aria-current')), ['true', null]);
    assert.equal(rows[0].textContent, 'Repair exportwork · OPEN');
    assert.equal(rows[1].textContent, 'Read DWGcad.read_lines');
    assert.equal(drawn.querySelector('[role="status"]'), null);
    await click([...drawn.querySelectorAll('button')].find(button => button.textContent.includes('Open as nodes')));
    assert.deepEqual(modes, ['canvas']);
    const detached = await draw({layout:'graph', native:null, nodes, target:''});
    assert.equal([...detached.querySelectorAll('button')].some(button => button.textContent.includes('Open as nodes')), false);
    assert.equal(detached.querySelector('[aria-current]'), null);
  } finally { await close(); }
});

test('the layout strip is three real buttons with one pressed preset', async () => {
  const picked = [];
  const {draw, click, close} = await mount('Strip');
  try {
    const doc = await draw({layout:'board', setLayout:value => picked.push(value)});
    const buttons = [...doc.querySelectorAll('[role="group"][aria-label="Workshop layout"] button')];
    assert.deepEqual(buttons.map(button => button.getAttribute('aria-label')), ['Conversation', 'Task board', 'Chat + live graph']);
    assert.deepEqual(buttons.map(button => button.getAttribute('aria-pressed')), ['false', 'true', 'false']);
    await click(buttons[2]);
    assert.deepEqual(picked, ['graph']);
  } finally { await close(); }
});

test('the shipped conversation mounts the strip in its header and the pane beside the participants; no scripted scene ships', () => {
  const conversation = source.slice(source.indexOf('const WorkshopConversation ='), source.indexOf('const WorkshopConversationMenu ='));
  assert.match(conversation, /^const WorkshopConversation = \(\{descriptor, target, setTarget, setMode\}\) => \{/);
  assert.match(conversation, /const \[layout, setLayout\] = React\.useState\('conversation'\)/);
  assert.match(conversation, /<WorkshopLayoutStrip layout=\{layout\} setLayout=\{setLayout\}\/>/);
  assert.match(conversation, /<aside aria-label="Workshop participants"[^]*?<WorkshopLayoutPane layout=\{layout\} native=\{native\} nodes=\{projectedWorkNodes\} target=\{nativeTarget\} setMode=\{setMode\}\/>/);
  assert.match(source, /<WorkshopConversation key=[^]*?setTarget=\{target => updateView\(\{target\}\)\} setMode=\{setMode\}\/>/);
  const header = source.slice(source.indexOf('const WsHeader ='), source.indexOf('const WsTab ='));
  assert.match(header, /workshopModeSegments\(\{mode, conversationRoot, workshops\}\)/);
  assert.match(header, /chooseWorkshopMode\(segment\.key, \{mode, conversationRoot, workshops, setMode, setConversationRoot\}\)/);
  // The design's authored scene (studio-workshop.jsx WS_AGENTS / WS_RUN / WS_FLOW / seedTasks / activity log / wsNode)
  // is not defined or bound anywhere in the shipped Studio: nothing seeded can render as if it were live.
  for (const scene of [/\bWS_(AGENTS|RUN|SCOPE|FLOW|WIRES)\s*=/, /\bseedTasks\s*=/, /window\.wsNode\b/, /ACTIVITY · LAST/]) {
    assert.doesNotMatch(source, scene);
  }
});
