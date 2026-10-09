const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const flat = value => String(value).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();

function createHarness() {
  const calls = [];
  const events = [];
  const React = {
    createElement(type, props, ...children) {
      return {type, props:props || {}, children:children.flat(Infinity)};
    },
    useState(initial) {
      return [initial, value => calls.push(['setState', value])];
    },
  };
  const W = {bg:'bg', bgPanel:'panel', bgSoft:'soft', bgHover:'hover', ink:'ink', inkSoft:'inkSoft',
    inkMuted:'muted', line:'line', lineSoft:'lineSoft', accent:'accent', accentDim:'accentDim',
    accentSoft:'accentSoft', onFill:'onFill', ok:'ok', warn:'warn', err:'err', cyan:'cyan',
    mono:'mono', sans:'sans', serif:'serif'};
  const window = {AH:W};
  const context = vm.createContext({React, window, console});
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
    const expanded = typeof node.type === 'function' ? node.type({...node.props, children:node.children}) : node;
    fn(expanded);
    visit(expanded.children || [], fn);
  };
  const clickButton = (tree, label) => {
    let found = null;
    visit(tree, node => {
      if (!found && node.type === 'button' && flat(render(node)) === label) found = node;
    });
    assert.ok(found, 'button not found: ' + label);
    found.props.onClick && found.props.onClick({stopPropagation:() => events.push('stopped')});
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
  const done = Array.from({length:9}, (_, i) => ({work:'work:done-' + i, id:'T-done' + i, title:'Closed ' + i,
    state:'done', owner:mcp, agent:'Brain MCP', host:'mcp-brain', lead:'settled', tools:{n:1, list:'court', t:'done'}}));
  return {
    tasks:[
      {work:'work:backlog-a', id:'T-backlo', title:'Collect requirements', state:'created', owner:null, agent:null, host:'Workshop', lead:'created, no claim', tools:{n:0, list:'none', t:'step 1 of 3'}},
      {work:'work:claimed-a', id:'T-claime', title:'Draft plan', state:'open', owner:claude, agent:'Claude Code', host:'Claude', lead:'claimed', tools:{n:1, list:'plan', t:'step 2 of 3'}},
      {work:'work:claim-a', id:'T-claim', title:'Claim transfer', state:'claim', owner:null, agent:'Codex', host:'Codex', lead:'claim accepted', tools:{n:1, list:'claim', t:'step 1 of 2'}},
      {work:'work:running-a', id:'T-runni', title:'Run validation', state:'run', owner:codex, agent:'Codex', host:'Codex', lead:'running', tools:{n:2, list:'pytest', t:'step 2 of 3'}},
      {work:'work:blocked-a', id:'T-block', title:'Approve connector', state:'approving', owner:codex, agent:'Codex', host:'Codex', lead:'waiting for your approval', tools:{n:3, list:'connector', t:'waiting for your approval'}, approving:true,
        decision:[{label:'Approve', action:'approve'}, {label:'Reject', action:'reject'}]},
      {work:'work:tool-off', id:'T-tool', title:'Connector off', state:'block', owner:codex, agent:'Codex', host:'Codex', lead:'Connectors are off', tools:{n:3, list:'connector', t:'Connectors are off'},
        decision:[{label:'Approve', action:'approve'}, {label:'Reject', action:'reject'}]},
      ...done,
    ],
    agents:[
      {id:codex, name:'Codex', runtime:'codex', host:'Codex', kind:'local', status:'working', ago:'verified 30 s ago', doing:'Run validation', may:'read workspace · edit this work folder'},
      {id:mcp, name:'Brain MCP', runtime:'mcp-brain', host:'mcp-brain', kind:'cloud', status:'available', ago:'verified 12 s ago', doing:'Nothing active', may:'read facts'},
    ],
  };
}

test('WorkshopBoardView groups governed Work into the five engine lanes with approval actions and bounded Done', () => {
  const {window, React, render, clickButton, events} = createHarness();
  const fx = fixture();
  const decisions = [];
  const tree = React.createElement(window.WorkshopBoardView, {tasks:fx.tasks, agents:fx.agents,
    selected:'', onSelect:() => {}, onDecide:(work, choice) => decisions.push([work, choice.action])});
  const html = render(tree);
  assert.match(html, /data-workshop-lane="backlog"/);
  assert.match(html, /data-workshop-lane="claimed"/);
  assert.match(html, /data-workshop-lane="running"/);
  assert.match(html, /data-workshop-lane="blocked"/);
  assert.match(html, /data-workshop-lane="done"/);
  assert.match(flat(html), /Backlog 1 .* Claimed 2 .* Running 1 .* Blocked 2 .* Done 9/);
  assert.match(flat(html), /Collect requirements no agent Workshop step 1 of 3/);
  assert.match(flat(html), /Claim transfer Codex Codex step 1 of 2/);
  assert.match(flat(html), /Approve connector Codex Codex waiting for your approval Approve Reject/);
  assert.doesNotMatch(flat(html), /Connector off Codex Codex Connectors are off Approve Reject/);
  clickButton(tree, 'Approve');
  assert.deepEqual(decisions, [['work:blocked-a', 'approve']]);
  assert.deepEqual(events, ['stopped']);
  assert.match(flat(html), /\+2 more/);
  assert.equal((html.match(/data-workshop-board-card="work:done-/g) || []).length, 7);
});

test('WorkshopAgentsView renders local and cloud agents with presence and hides engineering detail behind Details', () => {
  const {window, React, render, buttons} = createHarness();
  const fx = fixture();
  const tree = React.createElement(window.WorkshopAgentsView, {agents:fx.agents, details:false});
  const closed = render(tree);
  assert.match(flat(closed), /Codex local verified 30 s ago .* Run validation .* may: read workspace/);
  assert.match(flat(closed), /Brain MCP cloud verified 12 s ago .* Nothing active .* may: read facts/);
  assert.doesNotMatch(closed, /app:agent-session:runtime:codex-a1/);
  assert.match(flat(closed), /BABOOM companion listens: failed runs, stuck tasks, approvals/);
  assert.match(flat(closed), /Add an agent/);
  assert.deepEqual(buttons(tree).map(button => button.label), []);
});

test('Workshop views do not expose buttons without click handlers', () => {
  const {window, React, buttons} = createHarness();
  const fx = fixture();
  const views = [
    React.createElement(window.WorkshopBoardView, {tasks:fx.tasks, agents:fx.agents, selected:'', onSelect:() => {}, onDecide:() => {}}),
    React.createElement(window.WorkshopAgentsView, {agents:fx.agents}),
    React.createElement(window.WorkshopProjectsView, {projects:[{id:'p1', name:'Live project'}], onOpen:() => {}}),
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
  assert.match(flat(blocked), /THREAD .* Approve Reject/);
  const notBlocked = render(React.createElement(window.WorkshopTaskPage,
    {task:fx.tasks.find(task => task.work === 'work:tool-off'), agent:() => ({name:'Codex'}), onDecide:() => {}}));
  assert.doesNotMatch(flat(notBlocked), /THREAD .* Approve Reject/);
});

test('Workshop approvals list predicate matches the badge count predicate', () => {
  const source = read('nodelang/studio/studio-workshop.jsx');
  assert.match(source, /const approvalCount = allTasks\.filter\(t => \(t\.proposal && t\.state === 'block'\) \|\| t\.approving\)\.length;/);
  assert.match(source, /<window\.WorkshopApprovalsView tasks=\{allTasks\.filter\(t => \(t\.proposal && t\.state === 'block'\) \|\| t\.approving\)\}/);
  assert.doesNotMatch(source, /WorkshopApprovalsView tasks=\{allTasks\.filter\(t => t\.state === 'block' \|\| t\.approving \|\| t\.proposal\)\}/);
});

test('Workshop header exposes design-first Chat, Tasks, routed Router, Relay and Prompts tabs', () => {
  const source = read('nodelang/studio/studio-workshop.jsx');
  assert.match(source, /WORKSHOP_TABS = \[\['chat', 'Chat'\], \['tasks', 'Tasks'\], \['router', 'Router'\], \['relay', 'Relay'\], \['prompts', 'Prompts'\],\s+\['projects', 'Projects'\], \['board', 'Board'\], \['agents', 'Agents'\], \['approvals', 'Approvals'\]\]/);
  assert.match(source, /readCloudPublishConsent|setCloudPublishConsent|WorkshopRelayTab|Relay on\/off/);
  assert.match(source, /ARCHHUB_LOAD_SKILLS/);
});

test('gate row l: no agent card or linked panel shows "not projected" or an empty "may:"', async () => {
  const src = require('fs').readFileSync(require('path').join(__dirname, '..', 'nodelang', 'studio', 'workshop-board.jsx'), 'utf8');
  assert.doesNotMatch(src, /'not projected'/);
  const ws = require('fs').readFileSync(require('path').join(__dirname, '..', 'nodelang', 'studio', 'studio-workshop.jsx'), 'utf8');
  assert.doesNotMatch(ws, /v="not projected"/);
});
