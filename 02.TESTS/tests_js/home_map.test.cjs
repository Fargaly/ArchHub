// Home's map of the work, run as the Studio runs it (studio/ds_home2.jsx loaded without a page): sessions become cards in
// groups, an input link becomes one wire from card to card, and every map value is a parameter (design v56).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {transformSync} = require('esbuild');

const source = fs.readFileSync(path.join(__dirname, '../../01.APP/nodelang/studio/ds_home2.jsx'), 'utf8');
const context = vm.createContext({window: {ArchHubAPI: {executeAction() {}}, AHIcon() {}, UI: {useData() {}, useApp() {}, Btn() {}, taskRowReason: () => ''}}});
vm.runInContext(transformSync(source, {loader: 'jsx'}).code, context);
const {homeRows, homeMap} = context.window.UI;
const plain = value => JSON.parse(JSON.stringify(value));
const today = new Date().toISOString();
const DEFAULT = {group: 'Project', order: 'Needs you first', card: 'Steps and state', density: 'Comfortable', done: 'Show', filter: 'All'};
const session = (id, title, project, extra = {}) => ({id, title, path: 'C:/s/' + id + '.archhub', task: 't-' + id, state: 'open', pinned: false,
  project: {id: project, label: project}, members: [], automation: [], inputLinks: [], context: {plan: []}, ...extra});
const link = (source, output, input) => ({source: {path: source + '.archhub', id: source}, output, input});
// Tower: survey -> model -> sheets (a chain); Office: one finished session, one with a held run, one with a failed step.
const listed = {groups: [
  {project: {id: 'Office', label: 'Office'}, sessions: [session('std', 'Standard check', 'Office', {state: 'done'}), session('exp', 'Export package', 'Office', {automation: [{node: 'n', armed: true}]}),
    session('idx', 'Sheet index', 'Office')]},
  {project: {id: 'Tower', label: 'Tower'}, sessions: [session('sheets', 'Sheets', 'Tower', {inputLinks: [link('model', 'walls.out', 'walls')]}),
    session('model', 'Model', 'Tower', {inputLinks: [link('survey', 'points.out', 'points')], members: [{name: 'Claude Code / Tower / session-62fdf0706b09', live: true}]}), session('survey', 'Survey', 'Tower')]}]};
const task = (id, extra = {}) => ({id: 't-' + id, title: id, status: 'PLANNED', updated_at: today, sessionPath: 'C:/s/' + id + '.archhub', plan: [], progress: {}, ...extra});
const state = {
  tasks: [task('std', {status: 'DONE'}), task('exp'), task('sheets'), task('survey'),
    task('model', {plan: ['Read the model', 'Check the walls', 'Write the report'], progress: {'Read the model': 'done', 'Check the walls': 'working'}}),
    task('idx', {workflow: [{id: 'read', title: 'Read sheet index', type: 'param.value'}], activity: [{id: 'read', status: 'Error'}]})],
  approvals: [{id: 'a', status: 'pending', approvalKind: 'canvas', path: 'C:/s/exp.archhub', title: 'Send to client'},
    {id: 'b', status: 'pending', work: 'gone', title: 'Send the transmittal', who: 'Codex / Site / session-8dff5b479f68'}],
  graphs: [], agentGraph: {sessions: [{id: 'r1', name: 'Claude Code / Tower / session-62fdf0706b09', status: 'working', task: 't-model'},
    {id: 'r9', name: 'Codex / Site / session-8dff5b479f68', status: 'working', task: null}]},
};
const draw = (params = {}, hidden = []) => plain(homeMap({listed, rows: homeRows(state, {hidden, order: []}), params: {...DEFAULT, ...params}, hidden, titleOf: row => 'Live work of ' + row.id}));
const cards = chart => chart.nodes.filter(node => !node.group);
const at = (chart, id) => cards(chart).find(card => card.id === id);

test('a card is one whole session: who works on it, its state word, where it stands and what it needs', () => {
  const chart = draw();
  assert.deepEqual(chart.groups.map(group => group.key + ' ' + group.count), ['No project 1', 'Office 3', 'Tower 3']);
  const model = at(chart, 'model');
  assert.deepEqual([model.title, model.agent, model.state, model.now, model.w], ['Model', 'Claude Code · Tower', 'Working', 'Step 2 of 3 · Check the walls', 300]);
  assert.deepEqual(model.steps.map(step => step.kind), ['done', 'working', 'unreported']);
  assert.equal(model.need, null);
  const held = at(chart, 'exp');
  assert.deepEqual([held.state, held.need], ['Needs you', {text: 'Send to client needs your approval', approval: 'a'}], 'a held run is the tinted line with Review');
  const failed = at(chart, 'idx');
  assert.deepEqual([failed.state, failed.now, failed.need], ['Failed', 'Step 1 of 1 · Read sheet index', {text: 'Read sheet index failed', failed: true}]);
  assert.deepEqual([at(chart, 'survey').state, at(chart, 'survey').agent, at(chart, 'survey').now], ['Idle', '', 'No steps yet']);
  assert.doesNotMatch(JSON.stringify(cards(chart).map(card => [card.title, card.agent, card.now])), /session-[0-9a-f]{6,}/, 'no raw session id on a card');
  for (const group of chart.nodes.filter(node => node.group)) for (const card of cards(chart).filter(item => item.project === group.title))
    assert.ok(card.x >= group.x && card.y >= group.y && card.x + card.w <= group.x + group.w && card.y + card.h <= group.y + group.h, card.title + ' sits inside ' + group.title);
});

test('a card is work: a held run with no session is a card; an agent is a member of work, never a card of its own', () => {
  const chart = draw(), rows = homeRows(state, {hidden: [], order: []});
  const orphan = at(chart, 'approval:b');
  assert.equal(at(chart, 'row:live:r9'), undefined, 'a live agent with no session is present in the Workshop, not a card');
  assert.deepEqual([orphan.title, orphan.state, orphan.agent, orphan.need], ['Send the transmittal', 'Needs you', 'Codex · Site', {text: 'Send the transmittal needs your approval', approval: 'b'}]);
  assert.equal(cards(chart).filter(card => card.state === 'Needs you').length, rows.needsYou);
  // The header still counts every agent at work; the map shows the one that works on a session, on that session's card.
  assert.equal(cards(chart).filter(card => card.state === 'Working').length, 1);
  assert.deepEqual([rows.needsYou, rows.running, chart.total, chart.armed], [2, 2, 7, 1]);
});

test('a retired declare-made session (its row archived) is no card, from its file or its row; an unretired one stays', () => {
  const extra = {groups: [...listed.groups, {project: {id: 'Tower', label: 'Tower'}, sessions: [session('review7', 'independently reviewed build 11', 'Tower', {task: 'session-1f2e'})]}]};
  const tasks = [...state.tasks, {id: 'session-9a8b', title: '7/7 complete on Build 11', status: 'ARCHIVED', updated_at: today, plan: [], progress: {}},
    {id: 'session-1f2e', title: 'independently reviewed build 11', status: 'ARCHIVED', updated_at: today, sessionPath: 'C:/s/review7.archhub', plan: [], progress: {}}];
  const chart = plain(homeMap({listed: extra, rows: homeRows({...state, tasks}, {hidden: [], order: []}), params: DEFAULT, titleOf: row => row.title}));
  assert.equal(cards(chart).some(card => /independently|7\/7/.test(card.title)), false);
  assert.equal(chart.total, 7, 'the work cards are unchanged');
  // One the retire left (a person wrote in its thread) is still a session and still a card.
  const kept = [...state.tasks, {id: 'session-5c6d', title: 'Review he answered in', status: 'PLANNED', updated_at: today, plan: [], progress: {}}];
  const again = plain(homeMap({listed, rows: homeRows({...state, tasks: kept}, {hidden: [], order: []}), params: DEFAULT, titleOf: row => row.title}));
  assert.ok(cards(again).some(card => card.title === 'Review he answered in'));
});

test('an input link is one wire from card edge to card edge, laid left to right, with the design\'s default type and what it carries', () => {
  const chart = draw();
  assert.deepEqual(chart.wires.map(wire => [wire.from, wire.fromPort, wire.to, wire.toPort, wire.type, wire.list, wire.label].join(' | ')).sort(),
    ['model | out | sheets | in | file | true | walls.out \u2192 walls', 'survey | out | model | in | file | true | points.out \u2192 points']);
  assert.ok(at(chart, 'survey').x < at(chart, 'model').x && at(chart, 'model').x < at(chart, 'sheets').x, 'a source sits left of what it feeds');
});

test('group, order, card, density, finished and the filter are parameters', () => {
  assert.deepEqual(draw({group: 'State'}).groups.map(group => group.key), ['Needs you', 'Failed', 'Working', 'Idle']);
  assert.deepEqual(draw({group: 'Agent'}).groups.map(group => group.key), ['Claude Code · Tower', 'Codex · Site', 'No agent yet']);
  const office = chart => cards(chart).filter(card => card.project === 'Office').sort((a, b) => a.y - b.y || a.x - b.x).map(card => card.title);
  assert.deepEqual(office(draw()), ['Export package', 'Sheet index', 'Standard check'], 'what needs him first, then what failed');
  assert.deepEqual(office(draw({order: 'Name'})), ['Export package', 'Sheet index', 'Standard check']);
  assert.equal(cards(draw({done: 'Hide'})).some(card => card.id === 'std'), false, 'a finished session can be hidden');
  assert.deepEqual(cards(draw({filter: 'Needs you'})).map(card => card.id).sort(), ['approval:b', 'exp']);
  assert.deepEqual(cards(draw({filter: 'Running'})).map(card => card.state), ['Working']);  // the agent on its session; an agent with no session is no card
  const gap = chart => at(chart, 'model').x - at(chart, 'survey').x;
  assert.ok(gap(draw({density: 'Compact'})) < gap(draw()), 'Compact brings the cards closer; a card stays 300 wide');
  assert.ok(cards(draw({card: 'State only'}))[0].h < cards(draw())[0].h);
  assert.equal(cards(draw({}, ['t-exp'])).some(card => card.id === 'exp'), false, 'a session hidden from Home is not drawn');
});

test('a collapsed group is one node; every wire that crosses its edge stays', () => {
  const chart = draw({group: 'State', collapsed: ['Idle']});  // survey and sheets are Idle; model is Working
  const idle = chart.nodes.find(node => node.id === 'group:Idle');
  assert.equal(idle.collapsed, true);
  assert.equal(cards(chart).some(card => ['survey', 'sheets'].includes(card.id)), false);
  assert.deepEqual(chart.wires.map(wire => [wire.from, wire.to].join(' > ')).sort(), ['group:Idle > model', 'model > group:Idle']);
});

test('a narrow room stacks a group: unlinked sessions sit under the chain and groups wrap, so the map stays readable', () => {
  const room = r => plain(homeMap({listed, rows: homeRows(state, {hidden: [], order: []}), params: DEFAULT, titleOf: row => 'Live work of ' + row.id, room: r}));
  const wide = room(1.6), narrow = room(.7), span = (chart, x = 'x', w = 'w') => Math.max(...chart.nodes.map(node => node[x] + node[w])) - Math.min(...chart.nodes.map(node => node[x]));
  const shape = chart => span(chart) / span(chart, 'y', 'h');
  const office = chart => chart.nodes.find(node => node.id === 'group:Office');
  assert.ok(office(narrow).w < office(wide).w, 'Office (three unlinked sessions) is one card wide in a narrow room');
  assert.ok(shape(narrow) < shape(wide), 'the whole map is taller than wide in a narrow room: ' + [shape(narrow), shape(wide)]);
  assert.deepEqual(cards(narrow).map(card => card.id).sort(), cards(wide).map(card => card.id).sort(), 'the same sessions are drawn');
});

test('nothing given up from the list: the All / Agent sessions / Workflows filter, the folded Older section, and his own order', () => {
  const base = homeRows(state, {hidden: [], order: []}), draw2 = extra => plain(homeMap({listed, rows: base, params: DEFAULT, titleOf: row => 'Live work of ' + row.id, ...extra}));
  assert.equal(cards(draw2({kind: 'workflow'})).length, 0, 'no workflow file here: the Workflows filter shows none');
  assert.equal(cards(draw2({kind: 'agent-session'})).length, cards(draw2({})).length, 'every session here is an agent session');
  // His order: the idle sessions in the order he dragged them (grouped by state, so they share one group).
  const idle = chart => cards(chart).filter(card => card.state === 'Idle').sort((a, b) => a.y - b.y || a.x - b.x).map(card => card.id);
  const byState = order => idle(plain(homeMap({listed, rows: base, params: {...DEFAULT, group: 'State'}, titleOf: row => row.id, order})));
  assert.deepEqual(byState(['t-sheets', 't-std', 't-survey']), ['sheets', 'std', 'survey'], 'the drag order arranges the cards');
  assert.deepEqual(byState(['t-survey', 't-std', 't-sheets']), ['survey', 'std', 'sheets']);
  // Old runs sit in their own folded section; unfolding it shows them.
  const old = {...base, sectionOf: () => 'Older / archived'};
  const folded = plain(homeMap({listed, rows: old, params: DEFAULT, titleOf: row => row.id}));
  const older = chart => chart.groups.find(group => group.key === 'Older / archived');
  assert.equal(older(folded).collapsed, true, 'folded until he opens it');
  assert.equal(folded.groups.at(-1).key, 'Older / archived', 'the last section');
  const open = plain(homeMap({listed, rows: old, params: DEFAULT, titleOf: row => row.id, olderOpen: true}));
  assert.equal(older(open).collapsed, false);
  assert.ok(cards(open).length > cards(folded).length, 'unfolded, its sessions are cards');
});

test('projects > tasks > subtasks: a subtask sits in its parent task group, one column right, wired from it; folding the parent hides every level under it', () => {
  const tree = {groups: [{project: {id: 'Tower', label: 'Tower'}, sessions: [session('drawings', 'Drawings', 'Tower'), session('plan', 'Ground floor plan', 'Tower'),
    session('tags', 'Door tags', 'Other')]}]};
  const tasks = [task('drawings'), task('plan', {parent: 't-drawings'}), task('tags', {parent: 't-plan'})];
  const view = (params = {}) => plain(homeMap({listed: tree, rows: homeRows({...state, tasks, approvals: []}, {hidden: [], order: []}), params: {...DEFAULT, ...params}, titleOf: row => row.id}));
  const chart = view();
  assert.deepEqual(chart.groups.map(group => group.key + ' ' + group.count), ['Tower 3'], 'a subtask is drawn in its top task\'s project');
  assert.deepEqual(chart.wires.map(wire => [wire.from, wire.to, wire.label].join(' > ')).sort(), ['drawings > plan > Subtask', 'plan > tags > Subtask']);
  assert.ok(at(chart, 'drawings').x < at(chart, 'plan').x && at(chart, 'plan').x < at(chart, 'tags').x, 'each level one column to the right');
  assert.deepEqual([at(chart, 'drawings').subtasks, at(chart, 'plan').subtasks, at(chart, 'tags').subtasks], [1, 1, 0]);
  assert.deepEqual(['drawings', 'plan', 'tags'].map(id => at(chart, id).task), ['t-drawings', 't-plan', 't-tags'], 'every level opens its own session');
  const folded = view({collapsed: ['task:t-drawings']});
  assert.deepEqual(cards(folded).map(card => card.id), ['drawings']);
  assert.equal(at(folded, 'drawings').subtasksFolded, true);
  const middle = view({collapsed: ['task:t-plan']});
  assert.deepEqual(cards(middle).map(card => card.id).sort(), ['drawings', 'plan']);
});