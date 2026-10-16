const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('./studio_ds_context.cjs');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const flat = value => String(value).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();

function createHarness() {
  const calls = [];
  const events = [];
  const React = {
    forwardRef:fn => fn,
    createElement(type, props, ...children) {
      return {type, props:props || {}, children:children.flat(Infinity)};
    },
    useState(initial) {
      return [initial, value => calls.push(['setState', value])];
    },
    useRef(initial) {return {current:initial};},
  };
  const W = {bg:'bg', bgPanel:'panel', bgSoft:'soft', bgHover:'hover', ink:'ink', inkSoft:'inkSoft',
    inkMuted:'muted', line:'line', lineSoft:'lineSoft', accent:'accent', accentDim:'accentDim',
    accentSoft:'accentSoft', onFill:'onFill', ok:'ok', warn:'warn', err:'err', cyan:'cyan',
    mono:'mono', sans:'sans', serif:'serif'};
  const window = {AH:W};
  const context = vm.createContext({React, window, console});
  const shared = read('nodelang/studio/shared-data.jsx');
  vm.runInContext(require('esbuild').transformSync(shared,{loader:'jsx'}).code, context);
  vm.runInContext(read('nodelang/studio/workshop-board.jsx'), context);
  const render = node => {
    if (node == null || node === false) return '';
    if (typeof node === 'string' || typeof node === 'number') return String(node);
    if (Array.isArray(node)) return node.map(render).join(' ');
    if (typeof node.type === 'function') return render(node.type({...node.props, children:node.children}));
    const attrs = Object.entries(node.props || {}).filter(([key, value]) =>
      key.startsWith('data-') || key === 'aria-label' || key === 'aria-pressed')
      .map(([key, value]) => `${key}="${value}"`).join(' ');
    return `<${node.type}${attrs ? ' ' + attrs : ''}>${node.children.map(render).join(' ')}</${node.type}>`;
  };
  const visit = (node, fn) => {
    if (node == null || node === false || typeof node === 'string' || typeof node === 'number') return;
    if (Array.isArray(node)) return node.forEach(child => visit(child, fn));
    if(typeof node.type === 'function'){visit(node.type({...node.props,children:node.children}),fn);return;}
    fn(node);
    visit(node.children || [], fn);
  };
  const clickButton = (tree, label) => {
    let found=null;
    const find=(node,parents=[])=>{
      if(node==null||node===false||typeof node==='string'||typeof node==='number')return;
      if(Array.isArray(node)){node.forEach(child=>find(child,parents));return;}
      if(typeof node.type==='function'){find(node.type({...node.props,children:node.children}),parents);return;}
      const expanded=node;
      if(!found&&expanded.type==='button'&&flat(render(expanded))===label)found={node:expanded,parents};
      (expanded.children||[]).forEach(child=>find(child,[expanded,...parents]));
    };
    find(tree);assert.ok(found,'button not found: '+label);
    let stopped=false;
    const event={stopPropagation:()=>{stopped=true;events.push('stopped');}};
    found.node.props.onClick?.(event);
    for(const parent of found.parents){if(stopped)break;parent.props?.onClick?.(event);}
  };
  const buttons = tree => {
    const found = [];
    visit(tree, node => {
      if (node.type === 'button') found.push({label:flat(render(node)), props:node.props || {}});
    });
    return found;
  };
  return {window, React, render, calls, events, clickButton, buttons};
}

function fixture() {
  const codex = 'app:agent-session:runtime:codex-a1';
  const claude = 'app:agent-session:runtime:claude-b2';
  const mcp = 'mcp-server:brain';
  const old = Date.now() - 1000 * 60 * 60 * 24 * 25;
  const done = Array.from({length:9}, (_, i) => ({work:'work:done-' + i, id:'T-done' + i, title:'Closed ' + i,
    state:'done', owner:mcp, agent:'Brain MCP', host:'mcp-brain', lead:'settled', tools:{n:1, list:'court', t:'done'}}));
  return {
    tasks:[
      {work:'work:planned-a', id:'T-plan', title:'Collect requirements', state:'created', owner:null, agent:null, host:'Workshop', lead:'ready to start', tools:{n:0, list:'none', t:'step 1 of 3'}},
      {work:'work:released-a', id:'T-release', title:'Draft plan', state:'open', owner:claude, agent:'Claude Code', host:'Claude', lead:'ready to start', tools:{n:1, list:'plan', t:'step 2 of 3'}},
      {work:'work:review-a', id:'T-review', title:'Review package', state:'review', owner:claude, agent:'Claude Code', host:'Claude', lead:'submitted for review', tools:{n:1, list:'review', t:'ready for review'}},
      {work:'work:running-a', id:'T-runni', title:'Run validation', state:'run', owner:codex, agent:'Codex', host:'Codex', lead:'running', tools:{n:2, list:'pytest', t:'step 2 of 3'}},
      {work:'work:blocked-a', id:'T-block', title:'Approve connector', state:'approving', owner:codex, agent:'Codex', host:'Codex', lead:'waiting for your approval', tools:{n:3, list:'connector', t:'waiting for your approval'}, approving:true,
        decision:[{label:'Approve', action:'approve'}, {label:'Decline', action:'stop_native'}]},
      {work:'work:waiting-a', id:'T-wait', title:'Waiting card', state:'approving', owner:codex, agent:'Codex', host:'Codex', lead:'waiting for your approval', tools:{n:1, list:'review', t:'waiting for your approval'}, approving:true},
      {work:'work:tool-off', id:'T-tool', title:'Connector off', state:'block', owner:codex, agent:'Codex', host:'Codex', lead:'Connectors are off', tools:{n:3, list:'connector', t:'Connectors are off'},
        decision:[{label:'Turn on', action:'execute'}, {label:'Retry', action:'execute'}]},
      {work:'work:old-a', id:'T-old', title:'Dormant task', state:'created', owner:null, agent:null, host:'Workshop', lead:'inactive', updated_at:old, tools:{n:0, list:'none', t:'idle'}},
      {work:'work:archived-a', id:'T-archive', title:'Archived task', state:'archived', owner:null, agent:null, host:'Workshop', lead:'archived by sweep', updated_at:old, tools:{n:0, list:'none', t:'archived'}},
      ...done,
    ],
    agents:[
      {id:codex, root:codex, name:'Codex', runtime:'codex', host:'Codex', kind:'local', status:'working', verified:true, ago:'verified 30 s ago', doing:'Run validation', may:'read workspace · edit this work folder'},
      {id:claude, root:claude, name:'Claude Code', runtime:'claude', host:'Claude', kind:'local', status:'working', verified:true, ago:'verified 12 s ago', doing:'Review package', may:'read workspace'},
      {id:mcp, root:mcp, name:'Brain MCP', runtime:'mcp-brain', host:'mcp-brain', kind:'cloud', status:'available', verified:true, ago:'verified 12 s ago', doing:'Nothing active', may:'read facts'},
    ],
  };
}

test('WS-022 court: real board lanes retain blocked recovery in WIP and founder approval tasks in review', () => {
  const {window, React, render, clickButton, events, buttons} = createHarness();
  const fx = fixture();
  const decisions = [];
  const tree = React.createElement(window.WorkshopBoardView, {tasks:fx.tasks, agents:fx.agents,
    selected:'', archiveDays:20, onSelect:() => {}, onDecide:(work, choice) => decisions.push([work, choice.action])});
  const html = render(tree);
  assert.match(html, /data-workshop-lane="planned"/);
  assert.match(html, /data-workshop-lane="wip"/);
  assert.match(html, /data-workshop-lane="review"/);
  assert.match(html, /data-workshop-lane="done"/);
  assert.match(html, /data-workshop-lane="archived"/);
  assert.doesNotMatch(html, /data-workshop-lane="claimed"|data-workshop-lane="blocked"|Claimed|Blocked|no agent|host unknown|CDE/);
  assert.match(flat(html), /PLANNED 3 .* WIP 2 .* IN REVIEW 3 .* DONE 9 .* ARCHIVED 1/);
  assert.doesNotMatch(flat(html), /Archive after|archive_after_idle_days/);
  assert.match(flat(html), /Collect requirements Workshop step 1 of 3/);
  assert.match(flat(html), /Approve connector Codex Codex waiting for your approval .* Approve Decline/);
  assert.match(flat(html), /Waiting card Codex Codex waiting for your approval waits for you Review/);
  assert.match(flat(html), /Connector off Codex Codex Connectors are off Turn on Retry/);
  clickButton(tree, 'Approve');
  assert.deepEqual(decisions, [['work:blocked-a', 'approve']]);
  assert.deepEqual(events, ['stopped']);
  assert.match(flat(html), /\+2 more/);
  assert.equal((html.match(/data-workshop-board-card="work:done-/g) || []).length, 7);
});

test('WS-022 v2 court: approval-blocked card without a decision has one Review action that selects it', () => {
  const {window, React, render, clickButton, events, buttons} = createHarness();
  const fx = fixture();
  const selected = [];
  const decisions = [];
  const waiting = fx.tasks.find(task => task.work === 'work:waiting-a');
  const tree = React.createElement(window.WorkshopBoardView, {tasks:[waiting], agents:fx.agents,
    selected:'', onSelect:work => selected.push(work), onDecide:(work, choice) => decisions.push([work, choice.action])});
  const html = render(tree);
  assert.match(flat(html), /Waiting card Codex Codex waiting for your approval waits for you Review/);
  assert.deepEqual(buttons(tree).map(button => button.label), ['Review']);
  clickButton(tree, 'Review');
  assert.deepEqual(selected, ['work:waiting-a']);
  assert.deepEqual(decisions, []);
  assert.deepEqual(events, ['stopped']);
});

test('WS-022 v2 court: board lanes use stored state, not idle age or unverified/name agent matches', () => {
  const {window} = createHarness();
  const old = Date.now() - 45 * 86400000;
  const live = 'app:agent-session:runtime:live-a';
  const grouped = window.WorkshopBoard.groupTasks([
    {work:'work:old-live', title:'Old live', state:'run', owner:live, agent:'Codex', updated_at:old, tools:{t:'running'}},
    {work:'work:old-review', title:'Old review', state:'review', owner:live, updated_at:old, tools:{t:'submitted'}},
    {work:'work:old-open', title:'Old open', state:'open', owner:null, updated_at:old, tools:{t:'idle'}},
    {work:'work:archived', title:'Archived row', state:'archived', restore_state:'open', updated_at:Date.now(), tools:{t:'archived'}},
    {work:'work:name-only', title:'Name only', state:'run', owner:'Architect Name', agent:'Architect Name', updated_at:Date.now(), tools:{t:'running'}},
    {work:'work:stale', title:'Stale agent', state:'run', owner:'app:agent-session:runtime:stale', updated_at:Date.now(), tools:{t:'running'}},
  ], [
    {id:live, root:live, status:'working', verified:true},
    {id:'Codex', name:'Codex', status:'working', verified:true},
    {id:'app:agent-session:runtime:stale', status:'stale', verified:false},
  ], 20);
  assert.deepEqual(JSON.parse(JSON.stringify(grouped.wip.map(task => task.work))), ['work:old-live']);
  assert.deepEqual(JSON.parse(JSON.stringify(grouped.review.map(task => task.work))), ['work:old-review']);
  assert.deepEqual(JSON.parse(JSON.stringify(grouped.archived.map(task => task.work))), ['work:archived']);
  assert.ok(grouped.planned.map(task => task.work).includes('work:old-open'));
  assert.ok(grouped.planned.map(task => task.work).includes('work:name-only'));
  assert.ok(grouped.planned.map(task => task.work).includes('work:stale'));
});

test('WS-022 v2 court: archive-days row is hidden while no owner setting drives archiving (F31)', () => {
  const {window, React, render, buttons} = createHarness();
  const tree = React.createElement(window.WorkshopBoardView, {tasks:[], agents:[], archiveDays:30, onArchiveDays:() => {
    throw new Error('dead setter should not be called');
  }});
  const html = render(tree);
  assert.doesNotMatch(flat(html), /Archive after|archive_after_idle_days/);
  assert.doesNotMatch(html, /type="number"|Archive inactive tasks after days/);
  assert.deepEqual(buttons(tree).map(button => button.label), []);
});

test('WorkshopAgentsView renders local and cloud agents with presence and hides engineering detail behind Details', () => {
  const {window, React, render, buttons} = createHarness();
  const fx = fixture();
  const tree = React.createElement(window.WorkshopAgentsView, {agents:fx.agents, details:false});
  const closed = render(tree);
  assert.match(flat(closed), /Codex local verified 30 s ago .* Run validation .* may: read workspace/);
  assert.match(flat(closed), /Brain MCP cloud verified 12 s ago .* Nothing active .* may: read facts/);
  assert.doesNotMatch(closed, /app:agent-session:runtime:codex-a1/);
  assert.doesNotMatch(flat(closed), /BABOOM companion listens: failed runs, stuck tasks, approvals/, 'no synthetic companion agent without live evidence');
  assert.match(flat(closed), /Add an agent/);
  assert.deepEqual(buttons(tree).map(button => button.label), []);
});

test('Workshop views do not expose buttons without click handlers', () => {
  const {window, React, buttons} = createHarness();
  const fx = fixture();
  const views = [
    React.createElement(window.WorkshopBoardView, {tasks:fx.tasks, agents:fx.agents, selected:'', onSelect:() => {}, onDecide:() => {}}),
    React.createElement(window.WorkshopAgentsView, {agents:fx.agents}),
    React.createElement(window.WorkshopApprovalsView, {tasks:fx.tasks.filter(task => task.approving), selected:'', onSelect:() => {}, onDecide:() => {}}),
    React.createElement(window.WorkshopTaskPage, {task:fx.tasks.find(task => task.approving), agent:() => ({name:'Codex'}), onDecide:() => {}}),
  ];
  const dead = views.flatMap(buttons).filter(button => typeof button.props.onClick !== 'function').map(button => button.label);
  assert.deepEqual(dead, []);
});

test('WorkshopTaskPage hides decision buttons unless the task is approval-blocked', () => {
  const {window, React, render} = createHarness();
  const fx = fixture();
  const blocked = render(React.createElement(window.WorkshopTaskPage,
    {task:fx.tasks.find(task => task.approving), agent:() => ({name:'Codex'}), onDecide:() => {}}));
  assert.match(flat(blocked), /THREAD .* Approve Decline/);
  const notBlocked = render(React.createElement(window.WorkshopTaskPage,
    {task:fx.tasks.find(task => task.work === 'work:tool-off'), agent:() => ({name:'Codex'}), onDecide:() => {}}));
  assert.doesNotMatch(flat(notBlocked), /THREAD .* Approve Decline/);
});

test('WS-022 court: task page shows task, linked, steps, thread, with raw ids only in details', () => {
  const {window, React, render} = createHarness();
  const fx = fixture();
  const task = fx.tasks.find(row => row.approving);
  const closed = render(React.createElement(window.WorkshopTaskPage,
    {task, agent:() => ({name:'Codex'}), details:false, onDecide:() => {}}));
  assert.match(flat(closed), /TASK .* LINKED .* STEPS .* THREAD/);
  assert.doesNotMatch(flat(closed), /work:blocked-a|Host:|Tools:|CDE/);
  const open = render(React.createElement(window.WorkshopTaskPage,
    {task, agent:() => ({name:'Codex'}), details:true, onDecide:() => {}}));
  assert.match(flat(open), /DETAILS .* work:blocked-a .* connector/);
});


test('Workshop approval status and inline card predicate derive from the same selected authority snapshot',()=>{
  const {window}=createHarness();const shared=read('nodelang/studio/shared-data.jsx');
  vm.runInNewContext(shared.slice(0,shared.indexOf('const HOSTS =')),{window});
  const state={workshops:[{root:'room-a'}],canvas:{graph_id:'graph-a',root:'scope-a'},topology:{canvas:{application_root:'graph-a',scope:{current:'scope-a'},authorization:{subject:'owner-a',session:'view-a'}},graph:{nodes:[{id:'work:blocked-a',title:'Blocked task'}],wires:[]}},nativeWork:{root:'room-a',scope:'scope-a',owner:'owner-a',view:'view-a',work:'work:blocked-a',state:'awaiting_approval',input_digest:'a'.repeat(64)}};
  const model=window.ARCHHUB_WORKSHOP_MODEL({state,descriptor:{root:'room-a'},tasks:[],messages:[]});
  assert.equal(model.approval.work,'work:blocked-a');assert.equal(model.status.waiting,1);
  state.nativeWork.approved=true;const settled=window.ARCHHUB_WORKSHOP_MODEL({state,descriptor:{root:'room-a'},tasks:[],messages:[]});
  assert.equal(settled.approval,null);assert.equal(settled.status.waiting,0);
});
test('WS022 window replaces Board Chat Agents Approvals Router Relay Prompts navigation with one real thread',()=>{
  const source=read('nodelang/studio/studio-workshop.jsx');
  assert.doesNotMatch(source,/WORKSHOP_TABS|WORKSHOP_TASK_PRESETS|WorkshopTabs|WorkshopRouterTab|WorkshopRelayTab|WorkshopPromptsTab/);
  assert.match(source,/aria-label="Workshop conversation"/);assert.match(source,/data-workshop72-sections/);
  assert.match(source,/data-workshop72-composer/);assert.match(source,/Open on canvas/);
});
test('WS022 model route and labels use recorded registry state; message costs require recorded data',()=>{
  const source=read('nodelang/studio/studio-workshop.jsx');
  assert.match(source,/ARCHHUB_WORKSHOP_AGENT_MODEL/);
  const shared=read('nodelang/studio/shared-data.jsx');
  assert.match(shared,/registry|model_registry|modelRegistry/);
  for(const placeholder of ['Sonnet 4.6','GPT-5.5','Qwen3 free'])assert.equal(source.includes(placeholder),false,'model labels must come from the live registry: '+placeholder);
  assert.doesNotMatch(source,/cost:\s*[0-9]|price:\s*[0-9]/,'no invented cost constants');
});

test('gate row l: no agent card or linked panel shows "not projected" or an empty "may:"', async () => {
  const src = require('fs').readFileSync(require('path').join(__dirname, '..', 'nodelang', 'studio', 'workshop-board.jsx'), 'utf8');
  assert.doesNotMatch(src, /'not projected'/);
  const ws = require('fs').readFileSync(require('path').join(__dirname, '..', 'nodelang', 'studio', 'studio-workshop.jsx'), 'utf8');
  assert.doesNotMatch(ws, /v="not projected"/);
});

test('WS-022 v3 court: only verified session roots make WIP; group root and stale child do not', () => {
  const {window, React, render} = createHarness();
  const task = (work, owner) => ({work, title:work, state:'running', owner});
  const agents = [{id:'app:codex', root:'app:codex', verified:true, status:'live',
    live_roots:['session:live'], children:[{root:'session:live'}, {root:'session:stale'}]}];
  const html = render(React.createElement(window.WorkshopBoardView, {agents,
    tasks:[task('LiveTask', 'session:live'), task('StaleTask', 'session:stale'), task('GroupTask', 'app:codex')]}));
  const lane = id => (html.split(`data-workshop-lane="${id}"`)[1] || '').split('data-workshop-lane=')[0];
  assert.match(lane('wip'), /LiveTask/);
  assert.doesNotMatch(lane('wip'), /StaleTask|GroupTask/);
});
