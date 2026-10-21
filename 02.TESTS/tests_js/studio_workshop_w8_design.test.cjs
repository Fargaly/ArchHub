/* W8 design court: Workshop must present the design's visible structure using live projections.
   No canvas-node opening card; chat starts with the real ask, plan, Brain facts and task row. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('./studio_ds_context.cjs');

const root = path.resolve(__dirname, '..', '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');

function fixture() {
  const now = Date.now() / 1000;
  const readNode = 'node:read-openings';
  const filterNode = 'node:filter-openings';
  const work = 'assembly-instance:tagdoors03';
  const watchNode = 'node:watch-tags';
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
      mode:'project', work, approved:false, review_text:'input', input_digest:'a'.repeat(64), document:'Nile Tower.rvt',
      review_expires_at:now + 600, available_work:[work], artifacts_work:work, selected_work_mode:'project'},
    topology:{canvas:{application_root:'graph-a', scope:{current:'scope-a'},
      authorization:{subject:'owner-a', session:'view-a'}, revision:9}, graph:{nodes:[
      {id:readNode, title:'Read openings from model', sub:'Host read', status:'done', engine:'host.read', x:70, y:120,
        outs:[{id:'doors', label:'doors', t:'elements', list:true}]},
      {id:filterNode, title:'Keep level 3 doors', sub:'Filter', status:'done', engine:'shape.filter', x:300, y:150,
        ins:[{id:'items', label:'items', t:'elements', list:true}], outs:[{id:'kept', label:'kept', t:'elements', list:true}]},
      {id:work, title:'Tag doors, level 3', sub:'Graph node', status:'awaiting approval', x:540, y:180,
        element_count:46, ins:[{id:'kept', label:'kept', t:'elements', list:true}], outs:[{id:'tags', label:'tags', t:'elements', list:true}],
        params:[{k:'description', v:'step 2 of 3'}]},
      {id:watchNode, title:'Watch tag result', sub:'Watch table', status:'idle', engine:'watch.preview', x:780, y:210,
        ins:[{id:'tags', label:'tags', t:'elements', list:true}],
        result:JSON.stringify([{Level:'L3', Door:'D-301', Tag:'queued'}, {Level:'L3', Door:'D-302', Tag:'queued'}])},
      {id:doneWork, title:'Door tagging complete', sub:'Graph node', status:'Delivered', x:520, y:260,
        params:[{k:'description', v:'saved graph'}]},
    ], wires:[
      {id:'wire-read-filter', from:[readNode, 'doors'], to:[filterNode, 'items']},
      {id:'wire-filter-tag', from:[filterNode, 'kept'], to:[work, 'kept']},
      {id:'wire-tag-watch', from:[work, 'tags'], to:[watchNode, 'tags']},
    ]}, selected:null}};
  const calls = [];
  const authority = {getSnapshot:() => state, subscribe:() => () => {},
    refreshWorkshop:async() => transcript, refreshNativeWork:async() => state.nativeWork,
    showWorkshopFeed:async() => transcript, nativeAgents:async() => ({status:'ok', contacts:[]}),
    sendModelConversation:async() => ({accepted:true}), approveNativeWork:async(...args) => { calls.push(['approveNativeWork', ...args]); return {}; },
    selectTopology:async() => null, refreshTopologyCanvas:async() => state.topology.canvas,
    sendWorkshopMessage:async(...args) => { calls.push(['sendWorkshopMessage', ...args]); return {}; }};
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
  const context = vm.createContext({React, window:win, document:win.document, setTimeout, clearTimeout, console, CustomEvent:win.CustomEvent, URL, Blob, TextEncoder,
    AbortController:win.AbortController,
    fetch:(...args) => win.fetch(...args)});
  vm.runInContext(read('01.APP/nodelang/studio/tokens.jsx'), context);
  vm.runInContext(transformSync(read('01.APP/nodelang/studio/workshop-board.jsx'), {loader:'jsx'}).code, context);
  vm.runInContext(transformSync(read('01.APP/nodelang/studio/shared-data.jsx'), {loader:'jsx'}).code, context);
  vm.runInContext(transformSync(read('01.APP/nodelang/studio/studio-workshop.jsx'), {loader:'jsx'}).code, context);
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
  gate_spec:{path:'02.TESTS/tests_js/studio_workshop_w8_design.test.cjs'}, tier:'T1'}, description:'proposed work',
  inputs:{}, priority:10, purpose:'general', requirements:{artifact_reviewers:['app:agent-session:runtime:reviewer']}, title,
  write_grants:[{path:'10.PRODUCT/11.ARCHHUB-APP/tests_js/studio_workshop_w8_design.test.cjs', scope:'exact', operations:['apply_patch']}]});

const {mounted,transport,plain}=require('./workshop72_regression_helpers.cjs');
const {mountWorkshopNode}=require('./workshop72_node_helpers.cjs');

test('W8 frame and thread contracts migrate to exact DSYS077 dimensions and one composer',async()=>{
  const fx=fixture();const ui=await mounted(fx.state,fx.authority);
  try {const frame=ui.doc.querySelector('[data-workshop72]');assert.ok(frame);assert.equal(frame.style.gridTemplateRows,'1fr 28px');
    assert.equal(ui.doc.querySelector('[data-workshop72-rail]').style.width,'64px');
    assert.equal(ui.doc.querySelector('[data-workshop72-list]').style.width,'340px');
    assert.equal(ui.doc.querySelector('[data-workshop72-thread]').style.width,'780px');
    assert.equal(ui.doc.querySelectorAll('textarea[aria-label="Workshop message"]').length,1);
    assert.equal(ui.doc.querySelectorAll('[data-workshop-approval-card]').length,1);
    assert.deepEqual([...ui.doc.querySelectorAll('[data-workshop-approval-card] button')].map(text),['Approve','Decline']);
    assert.equal(ui.doc.querySelector('[data-workshop-s1-inspector]'),null);assert.equal(ui.doc.querySelector('[role="tab"]'),null);
    assert.equal(ui.doc.querySelector('[data-workshop-summary]'),null);assert.equal(ui.doc.querySelector('[data-workshop-step-pill]'),null);
    assert.equal(ui.doc.querySelector('[data-workshop-plan-json]'),null);assert.equal(ui.doc.querySelector('[data-workshop-brain-facts]'),null);
    const primary=[...frame.querySelectorAll('button[data-workshop-primary]')];assert.ok(primary.length<=6);assert.deepEqual(primary.map(el=>(el.getAttribute('aria-label')||text(el)).replace(' · Not available yet','')).sort(),['Approve','Decline','New task','Open on canvas','Review','Send'].sort());
  }finally{await ui.close();}
});
test('W8g completed task messages remain plain while inspector rich cards and Save as skill stay removed',async()=>{
  const fx=fixture(),work='assembly-instance:tagdoorsdone';
  fx.state.topology.graph.nodes.find(row=>row.id===work).completed_at=Date.now()/1000;
  fx.state.workshop.messages.push({root:'completed',sender_root:fx.state.workshop.participants[1].root,body:`Completed Work ${work}: The requested check completed.`,agent_text:'The requested check completed.',created_at:Date.now()/1000});
  const ui=await mounted(fx.state,fx.authority,{sel:{agent:null,task:work}});
  try{assert.match(text(ui.doc.querySelector('[data-workshop-message="completed"]')),/The requested check completed/);
    assert.equal(ui.doc.querySelector('[data-workshop-task]'),null);assert.equal(ui.doc.querySelector('[data-workshop-save-skill]'),null);
    assert.equal(ui.doc.querySelector('[data-workshop-s1-inspector]'),null);
  }finally{await ui.close();}
});
test('P3 live graph ports move to the real Workshop node while Watch results remain graph data',async()=>{
  const fx=fixture(),node={id:'room-a',cat:'workshop',title:'Workshop',ins:[{id:'doors',label:'doors',t:'elements',list:true}],outs:[{id:'tags',label:'tags',t:'rows',list:true}]};
  fx.state.topology.graph.nodes.push(node);const ui=await mountWorkshopNode({state:fx.state,node});
  try{assert.deepEqual([...ui.doc.querySelectorAll('[data-socket-port]')].map(el=>el.dataset.socketPort),['doors','tags']);
    assert.deepEqual([...ui.doc.querySelectorAll('[data-socket-port]')].map(el=>el.dataset.socketShape),['diamond','diamond']);
    assert.ok(ui.model().graph.nodes.some(row=>row.engine==='watch.preview'));
    assert.equal(ui.doc.querySelector('[data-workshop-watch-table]'),null);
  }finally{await ui.close();}
});
test('W8f unapproved proposal has only inline Approve and Decline and no Open as graph card',async()=>{
  const fx=fixture();fx.state.nativeWork=null;fx.state.workshop.messages=[{root:'p1',message_id:'p1',body:proposalBody('Draft the tag workflow'),sender_root:'agent-proposal'}];
  const ui=await mounted(fx.state,fx.authority);
  try{const card=ui.doc.querySelector('[data-workshop-approval-card]');assert.ok(card);
    assert.deepEqual([...card.querySelectorAll('button')].map(text),['Approve','Decline']);assert.doesNotMatch(text(card),/Open as graph/);
  }finally{await ui.close();}
});
test('W8f proposal Decline declines the proposal route', async () => {
  const fx = fixture();
  fx.state.nativeWork = null;
  fx.state.workshop.messages = [{root:'p1', message_id:'p1', sequence:1, sender_root:'app:agent-session:runtime:proposal',
    recipient_roots:[], body:proposalBody('Draft the tag workflow'), category:'note', state:'recorded', created_at:Date.now() / 1000}];
  fx.state.topology.graph.nodes = [{id:'work:plannedwait', title:'Planned approval', status:'waits for you',
    x:320, y:160, ins:[], outs:[], params:[{k:'done_when', v:'Founder approval waits for you'}]}];
  fx.state.topology.graph.wires = [];
  const proposalRow = {message_id:'p1', title:'Draft the tag workflow', problem:null};
  fx.authority.readWorkProposals = async root => { fx.calls.push(['readWorkProposals', root]); return {rows:[proposalRow]}; };
  fx.authority.declineWorkProposals = async (root, rows) => {
    fx.calls.push(['declineWorkProposals', root, rows.map(row => row.message_id)]);
    return {declined:[{message_id:rows[0].message_id}]};
  };
  const ui = await mountModule();
  try {
    ui.win.ARCHHUB_EXISTING_WORKSHOP = fx.authority;
    await ui.render('WorkshopView', {state:fx.state, descriptor:fx.state.workshops[0], target:'',
      setTarget:() => {}, setMode:() => {}, setFocusId:() => {}, onLeave:() => {},
      sel:{agent:null, task:null}, setSel:() => {}});
    await ui.act(async () => {});
    const proposal = ui.doc.querySelector('[data-workshop-approval-card]');
    await ui.click([...proposal.querySelectorAll('button')].find(button => button.textContent.trim() === 'Decline'));
    assert.deepEqual(JSON.parse(JSON.stringify(fx.calls.filter(call => call[0] === 'declineWorkProposals'))),
      [['declineWorkProposals', 'room-a', ['p1']]]);
  } finally { await ui.close(); }
});

test('W8 native task Decline calls stop_native', async () => {
  const fx = fixture();
  fx.state.nativeWork = {...fx.state.nativeWork, mode:'agent', selected_work_mode:'agent'};
  fx.authority.nativeWorkAction = async (...args) => { fx.calls.push(['nativeWorkAction', ...args]); return {}; };
  const ui = await mountModule();
  try {
    ui.win.ARCHHUB_EXISTING_WORKSHOP = fx.authority;
    await ui.render('WorkshopView', {state:fx.state, descriptor:fx.state.workshops[0], target:'',
      setTarget:() => {}, setMode:() => {}, setFocusId:() => {}, onLeave:() => {},
      sel:{agent:null, task:null}, setSel:() => {}});
    await ui.act(async () => {});
    const taskRow = ui.doc.querySelector('[data-workshop-approval-card]');
    await ui.click([...taskRow.querySelectorAll('button')].find(button => button.textContent.trim() === 'Decline'));
    assert.deepEqual(fx.calls.filter(call => call[0] === 'nativeWorkAction'),
      [['nativeWorkAction', 'room-a', 'stop_native', fx.state.nativeWork.work]]);
  } finally { await ui.close(); }
});


test('WS022 planned approval-waiting Work moves to NEEDS YOU while preserving the real board state without invented authority',async()=>{
  const fx=fixture();fx.state.nativeWork=null;fx.state.workshop.messages=[];
  fx.state.workshop.planned_items=[{id:'work:plannedwait',title:'Planned approval',state:'PLANNED',done_when:'Founder approval waits for you'}];
  fx.state.topology.graph.nodes=[{id:'work:plannedwait',title:'Planned approval',status:'waits for you'}];fx.state.topology.graph.wires=[];
  const ui=await mounted(fx.state,fx.authority);
  try{assert.match(text(ui.doc.querySelector('[data-workshop-section="needs-user"]')),/Planned approval.*waits for you/);
    assert.doesNotMatch(text(ui.doc.querySelector('[data-workshop-section="working"]')),/Planned approval/);
    assert.equal(ui.doc.querySelector('[data-workshop-approval-card]'),null);assert.equal(ui.doc.querySelector('[data-workshop-summary]'),null);
  }finally{await ui.close();}
});
test('W8b Router removal retains one-click Settings routing without a catalogue read during Workshop open',async()=>{
  const fx=fixture(),routes=[],fetches=[];const ui=await mounted(fx.state,fx.authority,{onSettings:()=>routes.push('settings')});
  ui.win.fetch=async url=>{fetches.push(url);return{ok:true,json:async()=>({})};};
  try{assert.equal(ui.doc.querySelector('[aria-label="Workshop router"]'),null);
    await ui.click(ui.doc.querySelector('[role="link"][aria-label="Settings"]'));
    assert.deepEqual(routes,['settings']);assert.deepEqual(fetches,[]);
    assert.equal(ui.doc.querySelector('select[aria-label="Workshop model"]'),null);
    const source=read('01.APP/nodelang/studio/studio.html'), saved=[];
    const hydration=[];
    const ctx=vm.createContext({window:{ARCHHUB_LOAD_CANVAS:async()=>{hydration.push('canvas');},ARCHHUB_EXISTING_WORKSHOP:{setComposerModel:async value=>{saved.push(value);return{configuration_state:{composer_model:{value}}};}}}});
    vm.runInContext(source.slice(source.indexOf('    window.ARCHHUB_AGENT_SELECT ='),source.indexOf('    let graphRunPromise =')),ctx);
    assert.equal(await ctx.window.ARCHHUB_AGENT_SELECT('ollama/llama3'),'ollama/llama3');
    assert.deepEqual(saved,['ollama/llama3']);assert.deepEqual(hydration,['canvas'], 'model selection crosses the real lazy canvas barrier once');
  }finally{await ui.close();}
});
test('W8d Relay removal preserves the real cloud publish consent read and exact toggle authority',async()=>{
  const fx=transport({get:()=>({ok:true,allowed:false,account:'owner@example.com'}),post:(_url,body)=>({ok:true,allowed:body.allow,account:'owner@example.com'})});
  assert.deepEqual(plain(await fx.api.readCloudPublishConsent()),{allowed:false,account:'owner@example.com'});
  assert.deepEqual(plain(await fx.api.setCloudPublishConsent(true)),{allowed:true,account:'owner@example.com'});
  assert.deepEqual(fx.posts,[{url:'/api/universal/cloud-publish-consent',body:{allow:true}}]);
});
test('W8d unavailable cloud consent refuses an unconfirmed change rather than inventing a switch state',async()=>{
  const fx=transport({get:()=>({ok:false}),post:()=>({ok:true,allowed:false})});
  await assert.rejects(fx.api.readCloudPublishConsent(),/could not be read/);
  await assert.rejects(fx.api.setCloudPublishConsent(true),/could not be confirmed/);
  assert.equal(fx.posts.length,1);assert.deepEqual(fx.posts[0].body,{allow:true});
  const surface=read('01.APP/nodelang/studio/studio-workshop.jsx');assert.doesNotMatch(surface,/WorkshopRelayTab|aria-label="Workshop relay"/);
});
test('W8b saved prompt text uses the single real composer and share stays absent without authority',async()=>{
  const fx=fixture();fx.state.workshop.participants=[];const calls=[];
  fx.authority.sendModelConversation=async(...args)=>{calls.push(args);return{accepted:true};};
  const ui=await mounted(fx.state,fx.authority,{target:'model:'+fx.state.workshop.model_agent.root});
  try{await ui.input('Tag doors on level 3 and update door schedule.');await ui.click(ui.button('Send'));
    assert.deepEqual(plain(calls),[['room-a',fx.state.workshop.model_agent,'Tag doors on level 3 and update door schedule.']]);
    assert.equal(ui.doc.querySelector('[aria-label="Workshop prompts"]'),null);
    assert.equal([...ui.doc.querySelectorAll('button')].some(el=>text(el)==='Share with firm'),false);
    assert.equal(ui.doc.querySelectorAll('textarea').length,1);
  }finally{await ui.close();}
});
