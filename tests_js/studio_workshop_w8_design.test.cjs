/* W8 design court: Workshop must present the design's visible structure using live projections.
   No canvas-node opening card; chat starts with the real ask, plan, Brain facts and task row. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');

function fixture() {
  const now = Date.now() / 1000;
  const work = 'assembly-instance:tagdoors03';
  const doneWork = 'assembly-instance:tagdoorsdone';
  const agent = 'app:agent-session:runtime:claude-code';
  const transcript = {ok:true, graph_id:'graph-a', root:'room-a', scope_root:'scope-a', revision:9,
    owner:'owner-a', view:'view-a', self:'owner-a', can_send:true, storage:'conversation-content',
    content_cursor:'c9', page_before:null, next_before:null, total:3, has_older:false, feed:'messages',
    model_agent:{root:'model-a', model:'Sonnet', route:'auto', binding_digest:'b'.repeat(64)},
    participants:[
      {root:'owner-a', label:'Fargaly', attached:true, is_agent:false},
      {root:agent, label:'Claude Code', attached:true, is_agent:true, connection_status:'connected',
        connection_basis:'authenticated-request', observed_at:now - 30, expires_at:now + 600,
        runtime:'claude-code', host:'Claude Code', session_link:'attached'},
    ],
    messages:[
      {root:'m1', sequence:1, sender_root:'owner-a', recipient_roots:[], body:'Tag the doors on level 3 and update the door schedule.',
        category:'note', state:'recorded', created_at:now - 90},
      {root:'m2', sequence:2, sender_root:agent, recipient_roots:['owner-a'],
        body:`Claimed Work ${work}. Plan: read 46 doors on Level 3, place tags, then rerun Door schedule.`,
        facts_used:[{label:'door tags use the level prefix', root:'fact-level-prefix'},
          {label:'fire rating before hardware', root:'fact-fire-rating'}],
        category:'note', state:'acted', created_at:now - 60},
      {root:'m3', sequence:3, sender_root:agent, recipient_roots:['owner-a'],
        body:`Completed Work ${doneWork}: door tags and schedule are ready.`,
        category:'note', state:'acted', created_at:now - 30},
    ]};
  const state = {canvas:{graph_id:'graph-a', root:'scope-a', revision:9,
      authorization:{subject:'owner-a', session:'view-a'}},
    workshops:[{root:'room-a', label:'Nile Tower', is_general:true, native_work_available:true}],
    workshop:transcript, workshopPage:{root:'room-a', before:null, feed:'messages', feedInitialized:true},
    workshopNotice:'',
    nativeWork:{owner:'owner-a', view:'view-a', root:'room-a', scope:'scope-a', state:'awaiting_approval',
      mode:'project', work, approved:false, review_text:'input', input_digest:'a'.repeat(64),
      review_expires_at:now + 600, available_work:[work], artifacts_work:work, selected_work_mode:'project'},
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'},
      authorization:{subject:'owner-a', session:'view-a'}, revision:9}, graph:{nodes:[
      {id:work, title:'Tag doors, level 3', sub:'Graph node', status:'Revit write', x:320, y:220,
        params:[{k:'description', v:'46 doors · step 2 of 3'}]},
      {id:doneWork, title:'Door tagging complete', sub:'Graph node', status:'Delivered', x:520, y:260,
        params:[{k:'description', v:'saved graph'}]},
    ], wires:[]}, selected:null}};
  const calls = [];
  const authority = {getSnapshot:() => state, subscribe:() => () => {},
    refreshWorkshop:async() => transcript, refreshNativeWork:async() => state.nativeWork,
    showWorkshopFeed:async() => transcript, nativeAgents:async() => ({status:'ok', contacts:[]}),
    sendModelConversation:async() => ({accepted:true}), approveNativeWork:async(...args) => { calls.push(['approveNativeWork', ...args]); return {}; },
    selectTopology:async() => null, refreshTopologyCanvas:async() => state.topology.canvas,
    workshopAction:async(...args) => { calls.push(['workshopAction', ...args]); return {}; }};
  return {state, authority, calls};
}

async function mountModule() {
  const {JSDOM} = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', {url:'http://127.0.0.1/', pretendToBeVisual:true});
  const oldWindow = global.window, oldDocument = global.document;
  global.window = dom.window; global.document = dom.window.document; global.IS_REACT_ACT_ENVIRONMENT = true;
  const React = require('react');
  const {createRoot} = require('react-dom/client');
  const {transformSync} = require('esbuild');
  const win = dom.window;
  const context = vm.createContext({React, window:win, document:win.document, setTimeout, clearTimeout, console, URL, Blob, TextEncoder,
    AbortController:win.AbortController,
    fetch:(...args) => win.fetch(...args)});
  vm.runInContext(read('nodelang/studio/tokens.jsx'), context);
  vm.runInContext(transformSync(read('nodelang/studio/workshop-board.jsx'), {loader:'jsx'}).code, context);
  vm.runInContext(transformSync(read('nodelang/studio/studio-workshop.jsx'), {loader:'jsx'}).code, context);
  const container = win.document.getElementById('root');
  const reactRoot = createRoot(container);
  const act = async fn => { await React.act(async () => { await fn(); }); };
  const click = el => act(() => el.dispatchEvent(new win.MouseEvent('click', {bubbles:true})));
  return {win, doc:win.document, act, click,
    render:(component, props) => act(() => reactRoot.render(React.createElement(win[component], props))),
    close:async () => { await act(() => reactRoot.unmount()); win.close(); global.window = oldWindow; global.document = oldDocument; delete global.IS_REACT_ACT_ENVIRONMENT; }};
}

const text = el => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');
const PROPOSAL_MARKER = 'ArchHub work proposal v1\n';
const proposalBody = title => PROPOSAL_MARKER + JSON.stringify({container:{container_id:'GM.nodes.workshop', gate_kind:'node-test',
  gate_spec:{path:'tests_js/studio_workshop_w8_design.test.cjs'}, tier:'T1'}, description:'proposed work',
  inputs:{}, priority:10, purpose:'general', requirements:{artifact_reviewers:['app:agent-session:runtime:reviewer']}, title,
  write_grants:[{path:'10.PRODUCT/13.NODE-LANGUAGE/tests_js/studio_workshop_w8_design.test.cjs', scope:'exact', operations:['apply_patch']}]});

test('W8 Workshop matches the design tab/header/chat contract from live data', async () => {
  const fx = fixture();
  const ui = await mountModule();
  try {
    ui.win.ARCHHUB_EXISTING_WORKSHOP = fx.authority;
    ui.win.ARCHHUB_LOAD_HOSTS = async () => ({hosts:[{id:'rvt', name:'Revit 2025', state:'connected', file:'Nile_Tower.rvt'}], connectors:[]});
    let target = '', mode = '', focus = '';
    await ui.render('WorkshopView', {state:fx.state, descriptor:fx.state.workshops[0], target,
      setTarget:value => { target = value; }, setMode:() => {}, setFocusId:() => {},
      onLeave:() => {}, sel:{agent:null, task:null}, setSel:() => {}});
    await ui.act(async () => {});

    const tabs = [...ui.doc.querySelectorAll('[role="tablist"][aria-label="Workshop tabs"] [role="tab"]')];
    assert.deepEqual(tabs.map(tab => tab.getAttribute('aria-label')),
      ['Chat', 'Tasks', 'Router', 'Relay', 'Prompts', 'Projects', 'Board', 'Agents', 'Approvals']);
    assert.match(text(ui.doc.querySelector('[data-workshop-head]')), /Nile Tower/);
    assert.match(text(ui.doc.querySelector('[aria-label="Workshop header chips"]')), /Sonnet · route auto/);
    assert.match(text(ui.doc.querySelector('[aria-label="Workshop header chips"]')), /Relay Off/);
    assert.match(text(ui.doc.querySelector('[aria-label="Workshop header chips"]')), /Hub/);

    const body = text(ui.doc.querySelector('[aria-label="Workshop conversation"]'));
    assert.match(body, /Tag the doors on level 3 and update the door schedule\./);
    assert.match(body, /Here(?:'|’)s the plan: read 46 doors on Level 3, place tags, then rerun Door schedule\./);
    assert.match(body, /Used 2 facts from Brain: door tags use the level prefix .* fire rating before hardware/);
    assert.match(body, /Tag doors, level 3\s+step 2 of 3 .* Revit write .* 46 doors .* waiting for approval/);
    assert.match(body, /Approve/);
    assert.match(body, /Open as graph/);
    assert.doesNotMatch(body, /Save as skill/);
    assert.doesNotMatch(body, /Here is the workflow on this canvas/);
    assert.doesNotMatch(body, /\b12 nodes\b/);

    const taskRow = ui.doc.querySelector('[data-workshop-task]');
    assert.ok(taskRow, 'task row is rendered');
    await ui.click([...taskRow.querySelectorAll('button')].find(button => button.textContent.trim() === 'Approve'));
    assert.deepEqual(fx.calls[0], ['approveNativeWork', 'room-a', 'a'.repeat(64)]);

    await ui.render('WorkshopView', {state:fx.state, descriptor:fx.state.workshops[0], target,
      setTarget:value => { target = value; }, setMode:value => { mode = value; },
      setFocusId:value => { focus = value; }, onLeave:() => {}, sel:{agent:null, task:null}, setSel:() => {}});
    await ui.click([...ui.doc.querySelector('[data-workshop-task]').querySelectorAll('button')]
      .find(button => button.textContent.trim() === 'Open as graph'));
    assert.equal(mode, 'canvas');
    assert.equal(focus, 'assembly-instance:tagdoors03');
  } finally {
    await ui.close();
  }
});

test('W8g completed task does not offer unsafe Save as skill without governed graph capture', async () => {
  const fx = fixture();
  const ui = await mountModule();
  try {
    ui.win.ARCHHUB_EXISTING_WORKSHOP = fx.authority;
    ui.win.ARCHHUB_LOAD_HOSTS = async () => ({hosts:[], connectors:[]});
    await ui.render('WorkshopView', {state:fx.state, descriptor:fx.state.workshops[0], target:'',
      setTarget:() => {}, setMode:() => {}, setFocusId:() => {}, onLeave:() => {}, sel:{agent:null, task:null}, setSel:() => {}});
    await ui.act(async () => {});
    const completed = [...ui.doc.querySelectorAll('[data-workshop-task]')]
      .find(card => /Door tagging complete/.test(text(card)));
    assert.ok(completed, 'completed task is rendered');
    const save = [...completed.querySelectorAll('button')].find(button => button.textContent.trim() === 'Save as skill');
    assert.equal(save, undefined, 'Save as skill is absent until a governed graph-capture route exists');
  } finally { await ui.close(); }
});

test('W8f unapproved proposals do not render Open as graph', async () => {
  const fx = fixture();
  fx.state.nativeWork = null;
  fx.state.workshop.messages = [{root:'p1', message_id:'p1', sequence:1, sender_root:'app:agent-session:runtime:proposal',
    recipient_roots:[], body:proposalBody('Draft the tag workflow'), category:'note', state:'recorded', created_at:Date.now() / 1000}];
  fx.state.topology.graph.nodes = [];
  const ui = await mountModule();
  try {
    ui.win.ARCHHUB_EXISTING_WORKSHOP = fx.authority;
    await ui.render('WorkshopView', {state:fx.state, descriptor:fx.state.workshops[0], target:'',
      setTarget:() => {}, setMode:() => { throw new Error('proposal should not open canvas'); },
      setFocusId:() => {}, onLeave:() => {}, sel:{agent:null, task:null}, setSel:() => {}});
    await ui.act(async () => {});
    const proposal = ui.doc.querySelector('[data-workshop-task="proposal:p1"]');
    assert.ok(proposal, 'proposal task card is rendered');
    assert.deepEqual([...proposal.querySelectorAll('button')].map(button => button.textContent.trim()), ['Approve', 'Reject']);
    assert.doesNotMatch(text(proposal), /Open as graph/);
  } finally { await ui.close(); }
});

test('W8b Router tab uses the model catalogue and saves through the existing selection route', async () => {
  const fx = fixture();
  const ui = await mountModule();
  try {
    const saved = [];
    ui.win.ARCHHUB_EXISTING_WORKSHOP = fx.authority;
    ui.win.ARCHHUB_AGENT_SELECT = async route => { saved.push(route); return route; };
    ui.win.fetch = async url => {
      assert.equal(String(url), '/api/universal/models');
      return {ok:true, json:async () => ({ok:true, selected_route:'openrouter/qwen/free:free', groups:[{name:'BYO', items:[
        {name:'Qwen free', route:'openrouter/qwen/free:free', routed:'openrouter/qwen/free:free', vendor:'qwen', tag:'BYO', cost:'$0 / $0 per M'},
        {name:'Paid', route:'openrouter/vendor/paid', routed:'openrouter/vendor/paid', vendor:'paid', tag:'BYO', cost:'$1 / $1 per M'},
        {name:'Local', route:'ollama/llama3', routed:'ollama/llama3', vendor:'Ollama', tag:'LOCAL', cost:'free · local'},
      ]}]})};
    };
    await ui.render('WorkshopView', {state:fx.state, descriptor:fx.state.workshops[0], target:'',
      setTarget:() => {}, setMode:() => {}, setFocusId:() => {}, onLeave:() => {}, sel:{agent:null, task:null}, setSel:() => {}});
    await ui.click([...ui.doc.querySelectorAll('[role="tab"]')].find(tab => tab.getAttribute('aria-label') === 'Router'));
    await ui.act(async () => {});
    const panel = ui.doc.querySelector('[aria-label="Workshop router"]');
    assert.match(text(panel), /Workshop model selects the one recorded composer model/);
    assert.match(text(panel), /Tag doors, level 3/);
    assert.match(text(panel), /model not recorded/);
    assert.equal(panel.textContent.includes('Paid'), false);
    assert.equal(panel.querySelectorAll('select').length, 1);
    assert.equal(panel.querySelector('select[aria-label="Inner loop model"]'), null);
    assert.equal(panel.querySelector('select[aria-label="Plans that write to a host model"]'), null);
    const select = panel.querySelector('select[aria-label="Workshop model"]');
    await ui.act(() => { Object.getOwnPropertyDescriptor(ui.win.HTMLSelectElement.prototype, 'value').set.call(select, 'ollama/llama3');
      select.dispatchEvent(new ui.win.Event('change', {bubbles:true})); });
    assert.deepEqual(saved, ['ollama/llama3']);
  } finally { await ui.close(); }
});

test('W8d Relay tab reads and toggles the cloud publish consent record', async () => {
  const fx = fixture();
  const ui = await mountModule();
  try {
    const calls = [];
    fx.authority.readCloudPublishConsent = async () => { calls.push('read'); return {allowed:false, account:'owner@example.com'}; };
    fx.authority.setCloudPublishConsent = async allow => { calls.push(allow); return {allowed:allow, account:'owner@example.com'}; };
    ui.win.ARCHHUB_EXISTING_WORKSHOP = fx.authority;
    ui.win.ARCHHUB_CLOUD_SESSION = async () => ({ok:true, state:'signed_in', email:'owner@example.com'});
    await ui.render('WorkshopView', {state:fx.state, descriptor:fx.state.workshops[0], target:'',
      setTarget:() => {}, setMode:() => {}, setFocusId:() => {}, onLeave:() => {}, sel:{agent:null, task:null}, setSel:() => {}});
    await ui.act(async () => {});
    assert.match(text(ui.doc.querySelector('[aria-label="Workshop header chips"]')), /Relay Off/);
    await ui.click([...ui.doc.querySelectorAll('[role="tab"]')].find(tab => tab.getAttribute('aria-label') === 'Relay'));
    await ui.act(async () => {});
    const panel = ui.doc.querySelector('[aria-label="Workshop relay"]');
    assert.match(text(panel), /Cloud relay/);
    assert.match(text(panel), /lets the cockpit send instructions to this app and see the map/);
    assert.match(text(panel), /State: Off/);
    const relaySwitch = panel.querySelector('button[role="switch"][aria-label="Relay on/off"]');
    assert.ok(relaySwitch);
    assert.equal(relaySwitch.getAttribute('aria-checked'), 'false');
    await ui.click(relaySwitch);
    await ui.act(async () => {});
    assert.deepEqual(calls, ['read', true]);
    assert.equal(relaySwitch.getAttribute('aria-checked'), 'true');
    assert.match(text(ui.doc.querySelector('[aria-label="Workshop header chips"]')), /Relay On/);
  } finally { await ui.close(); }
});

test('W8d Relay tab shows cloud sign-in instead of the switch when there is no cloud session', async () => {
  const fx = fixture();
  const ui = await mountModule();
  try {
    const calls = [];
    fx.authority.readCloudPublishConsent = async () => { calls.push('read'); return {allowed:false, account:''}; };
    fx.authority.setCloudPublishConsent = async allow => { calls.push(allow); return {allowed:allow, account:'owner@example.com'}; };
    ui.win.ARCHHUB_EXISTING_WORKSHOP = fx.authority;
    ui.win.ARCHHUB_CLOUD_SESSION = async () => ({ok:true, state:'signed_out'});
    const signins = [];
    ui.win.ARCHHUB_CLOUD_SIGNIN = async method => { signins.push(method || 'default'); return {ok:true}; };
    await ui.render('WorkshopView', {state:fx.state, descriptor:fx.state.workshops[0], target:'',
      setTarget:() => {}, setMode:() => {}, setFocusId:() => {}, onLeave:() => {}, sel:{agent:null, task:null}, setSel:() => {}});
    await ui.click([...ui.doc.querySelectorAll('[role="tab"]')].find(tab => tab.getAttribute('aria-label') === 'Relay'));
    await ui.act(async () => {});
    const panel = ui.doc.querySelector('[aria-label="Workshop relay"]');
    assert.match(text(panel), /Sign in to use the cloud relay/);
    assert.equal(panel.querySelector('button[role="switch"]'), null);
    const signIn = [...panel.querySelectorAll('button')].find(button => button.textContent.trim() === 'Sign in');
    assert.ok(signIn);
    await ui.click(signIn);
    assert.deepEqual(signins, ['google']);
    assert.deepEqual(calls, ['read']);
  } finally { await ui.close(); }
});

test('W8b Prompts tab reads saved prompts, fills blanks into the composer, and hides share without a route', async () => {
  const fx = fixture();
  const ui = await mountModule();
  try {
    ui.win.ARCHHUB_EXISTING_WORKSHOP = fx.authority;
    ui.win.ARCHHUB_LOAD_SKILLS = async () => [{id:'p1', name:'Door tags prompt'}];
    ui.win.ARCHHUB_READ_SKILL = async () => 'Tag doors on {level} and update {schedule}.';
    await ui.render('WorkshopView', {state:fx.state, descriptor:fx.state.workshops[0], target:'',
      setTarget:() => {}, setMode:() => {}, setFocusId:() => {}, onLeave:() => {}, sel:{agent:null, task:null}, setSel:() => {}});
    await ui.click([...ui.doc.querySelectorAll('[role="tab"]')].find(tab => tab.getAttribute('aria-label') === 'Prompts'));
    await ui.act(async () => {});
    const panel = ui.doc.querySelector('[aria-label="Workshop prompts"]');
    assert.match(text(panel), /Door tags prompt/);
    assert.equal([...panel.querySelectorAll('button')].some(button => button.textContent.trim() === 'Share with firm'), false);
    const blanks = [...panel.querySelectorAll('input')];
    await ui.act(() => { Object.getOwnPropertyDescriptor(ui.win.HTMLInputElement.prototype, 'value').set.call(blanks[0], 'level 3');
      blanks[0].dispatchEvent(new ui.win.Event('input', {bubbles:true})); });
    await ui.act(() => { Object.getOwnPropertyDescriptor(ui.win.HTMLInputElement.prototype, 'value').set.call(blanks[1], 'door schedule');
      blanks[1].dispatchEvent(new ui.win.Event('input', {bubbles:true})); });
    await ui.click([...panel.querySelectorAll('button')].find(button => button.textContent.trim() === 'Use'));
    assert.equal(ui.doc.querySelector('input[aria-label="Workshop message"]').value, 'Tag doors on level 3 and update door schedule.');
  } finally { await ui.close(); }
});
