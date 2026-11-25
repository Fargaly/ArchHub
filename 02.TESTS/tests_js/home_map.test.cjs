// Home's map of the work, run as the Studio runs it (studio/ds_home2.jsx loaded without a page): sessions become cards in
// groups, an input link becomes one wire from card to card, and every map value is a parameter (design v56).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {transformSync} = require('esbuild');

const source = fs.readFileSync(path.join(__dirname, '../../01.APP/nodelang/studio/ds_home2.jsx'), 'utf8');
const context = vm.createContext({
  window: {structuredClone:globalThis.structuredClone, crypto: require('node:crypto').webcrypto, addEventListener() {}, dispatchEvent() {},
    AHIcon() {}, UI: {useData() {}, useApp() {}, Btn() {}, taskRowReason: () => ''}},
  document: {hidden:true, addEventListener() {}}, fetch: () => new Promise(() => {}),
  setTimeout, clearTimeout, CustomEvent:class {}
});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../../01.APP/nodelang/studio/api.js'), 'utf8'), context);
vm.runInContext(transformSync(source, {loader: 'jsx'}).code, context);
const {homeRows, homeMap} = context.window.UI;

test('Continue cannot substitute the other task on the same canvas', async () => {
  const row = {id:'A', sessionPath:'shared.archhub'}, card = {task:'B', path:row.sessionPath};
  let opens=0, sends=0;
  await assert.rejects(context.window.UI.continueHomeWork(card,[row],()=>++opens,()=>({}),()=>++sends,()=>{},()=>{}), /selected task is unavailable/);
  assert.equal(opens,0); assert.equal(sends,0);
});

test('Continue retains the selected task reply if refreshing Home fails', async () => {
  const rows=['A','B'].map(id=>({id,sessionPath:'shared.archhub'}));
  const sent=[],shown=[];
  const reply=await context.window.UI.continueHomeWork({task:'B'},rows,async id=>id==='B',
    ()=>({agent:'Codex'}),async (turn,unused,id)=>{sent.push(id);return {provider:'Codex',answer:'Saved the step'};},
    text=>shown.push(text),async()=>{throw Error('refresh unavailable');});
  assert.deepEqual(sent,['B']);assert.deepEqual(shown,['Codex · Saved the step']);assert.equal(reply.answer,'Saved the step');
});

const plain = value => JSON.parse(JSON.stringify(value));
const today = new Date().toISOString();
const DEFAULT = {group: 'Project', order: 'Needs you first', card: 'Steps and state', density: 'Comfortable', done: 'Show', filter: 'All'};
const session = (id, title, project, extra = {}) => ({id, title, path: 'C:/s/' + id + '.archhub', task: 't-' + id, state: 'open', pinned: false,
  project: {id: project, label: project}, members: [], automation: [], inputLinks: [], context: {plan: []}, ...extra});
const link = (source, output, input) => ({source: {path: source + '.archhub', id: source}, output, input});
// Tower: survey -> model -> sheets (a chain); Office: one finished session, one with a held run, one with a failed step.
const listed = {groups: [
  {project: {id: 'Office', label: 'Office'}, sessions: [session('std', 'Standard check', 'Office', {state: 'done'}), session('exp', 'Export package', 'Office', {automation: [{node: 'n', armed: true, live: true}]}),
    session('idx', 'Sheet index', 'Office')]},
  {project: {id: 'Tower', label: 'Tower'}, sessions: [session('sheets', 'Sheets', 'Tower', {inputLinks: [link('model', 'walls.out', 'walls')]}),
    session('model', 'Model', 'Tower', {inputLinks: [link('survey', 'points.out', 'points')], members: [{name: 'Claude Code / Tower / session-62fdf0706b09', live: true}]}), session('survey', 'Survey', 'Tower')]}]};
const task = (id, extra = {}) => ({id: 't-' + id, title: id, status: 'PLANNED', updated_at: today, sessionPath: 'C:/s/' + id + '.archhub', plan: [], progress: {}, ...extra});
const state = {
  workspaces: ['Office', 'Other', 'Tower'].map(id => ({id, name: id})),
  tasks: [task('std', {status: 'DONE'}), task('exp'), task('sheets'), task('survey'),
    task('model', {plan: ['Read the model', 'Check the walls', 'Write the report'], progress: {'Read the model': 'done', 'Check the walls': 'working'}}),
    task('idx', {workflow: [{id: 'read', title: 'Read sheet index', type: 'param.value'}], activity: [{id: 'read', status: 'Error'}]})],
  approvals: [{id: 'a', status: 'pending', approvalKind: 'canvas', path: 'C:/s/exp.archhub', title: 'Send to client'},
    {id: 'b', status: 'pending', work: 'gone', title: 'Send the transmittal', who: 'Codex / Site / session-8dff5b479f68'}],
  graphs: [], agentGraph: {sessions: [{id: 'r1', name: 'Claude Code / Tower / session-62fdf0706b09', status: 'working', task: 't-model'},
    {id: 'r9', name: 'Codex / Site / session-8dff5b479f68', status: 'working', task: null}]},
};
const draw = (params = {}, hidden = [], view = {}) => plain(homeMap({listed, rows: homeRows(state, {hidden, order: []}), params: {...DEFAULT, ...params}, hidden, titleOf: row => row.title, history: true, ...view}));
const cards = chart => chart.nodes.filter(node => !node.group);
const at = (chart, id) => cards(chart).find(card => card.id === id);

test('Canvas resumes selected work, then the last opened task, then the most recently edited eligible file', () => {
  const a = session('a', 'Selected', '', {updated: '2026-11-17'});
  const b = session('b', 'Last opened', '', {updated: '2026-11-18'});
  const c = session('c', 'Last edited', '', {updated: '2026-11-20'});
  const archived = session('z', 'Archived', '', {state: 'archived', updated: '2026-11-21'});
  const model = {groups: [{sessions: [archived, {...c, task: ''}, c, b, a]}], recentTask: b.task};
  const resume = context.window.UI.homeSessionToResume;
  assert.equal(resume(model, [a.task]).id, a.id);
  assert.equal(resume(model, [archived.task]).id, b.id);
  assert.equal(resume({...model, recentTask: ''}, []).id, c.id);
  assert.equal(resume({groups: [{sessions: [archived, {...c, task: ''}]}]}, []), undefined);
  const presence = session('presence', 'Any title', '', {task:'declared-only', updated:'2026-11-22'});
  const mixed = {groups:[{sessions:[presence, c]}], recentTask:presence.task};
  assert.equal(resume(mixed, [presence.task]).id, c.id);
  assert.equal(resume({groups:[{sessions:[presence]}]}, [presence.task]), undefined);
  const joined = {id:presence.task, declarations:[{work:presence.task}]};
  assert.equal(resume(mixed, [presence.task], [joined]).id, presence.id);
  assert.equal(resume(mixed, [c.task], [{id:c.task, declaration:true}]), undefined);
});

test('active Home keeps pinned and explicitly resumed files; history offers unassigned saved work', () => {
  const files = [session('a', 'First task', ''), session('b', 'Pinned finished task', '', {state: 'done', pinned: true})];
  const rows = homeRows({tasks: [], graphs: [], approvals: [], agentGraph: {sessions: []}}, {hidden: [], order: []});
  const map = (params = {}, view = {}) => plain(homeMap({listed: {groups: [{sessions: files}]}, rows, params: {...DEFAULT, ...params}, ...view}));
  assert.deepEqual(map().groups.map(group => group.key), ['Work without a project']);
  assert.deepEqual(cards(map({done: 'Hide'})).map(card => card.id), ['b']);
  assert.deepEqual(cards(map({}, {focusPath: files[0].path})).map(card => card.id), ['a', 'b']);
  const history = map({}, {history: true});
  assert.deepEqual(history.groups.map(group => group.key), ['Unassigned']);
  assert.equal(cards(history).length, 2);
  assert.equal(cards(map({collapsed: ['Unassigned']}, {history: true})).length, 0);
});

test('a card is one whole session: who works on it, its state word, where it stands and what it needs', () => {
  const chart = draw();
  assert.deepEqual(chart.groups.map(group => group.key + ' ' + group.count), ['Office 3', 'Tower 3', 'Unassigned 1']);
  const model = at(chart, 'model');
  assert.deepEqual([model.title, model.agent, model.state, model.now, model.w], ['Model', 'Claude Code · Tower', 'Working', 'Step 2 of 3 · Check the walls', 300]);
  assert.deepEqual(model.steps.map(step => step.kind), ['done', 'working', 'unreported']);
  assert.equal(model.need, null);
  const held = at(chart, 'exp');
  assert.deepEqual([held.state, held.need], ['Needs you', {text: 'Send to client needs your approval', approval: 'a'}], 'a held run is the tinted line with Review');
  const failed = at(chart, 'idx');
  assert.deepEqual([failed.state, failed.now, failed.need], ['Failed', 'Step 1 of 1 · Read sheet index', {text: 'Read sheet index failed', failed: true}]);
  assert.deepEqual([at(chart, 'survey').state, at(chart, 'survey').agent, at(chart, 'survey').now], ['Planned', '', 'No steps yet']);
  assert.doesNotMatch(JSON.stringify(cards(chart).map(card => [card.title, card.agent, card.now])), /session-[0-9a-f]{6,}/, 'no raw session id on a card');
  for (const group of chart.nodes.filter(node => node.group)) for (const card of cards(chart).filter(item => item.project === group.title))
    assert.ok(card.x >= group.x && card.y >= group.y && card.x + card.w <= group.x + group.w && card.y + card.h <= group.y + group.h, card.title + ' sits inside ' + group.title);
});

test('a card is work: a held run with no session is a card; an agent is a member of work, never a card of its own', () => {
  const chart = draw({}, [], {history: false}), rows = homeRows(state, {hidden: [], order: []});
  const orphan = at(chart, 'approval:b');
  assert.equal(at(chart, 'row:live:r9'), undefined, 'a live agent with no session is present in the Workshop, not a card');
  assert.deepEqual([orphan.title, orphan.state, orphan.agent, orphan.need], ['Send the transmittal', 'Needs you', 'Codex · Site', {text: 'Send the transmittal needs your approval', approval: 'b'}]);
  assert.equal(cards(chart).filter(card => card.state === 'Needs you').length, rows.needsYou);
  assert.equal(cards(chart).filter(card => card.state === 'Working').length, 1);
  assert.deepEqual([rows.needsYou, rows.running, chart.total, chart.armed], [2, 1, 7, 1]);
});

test('a planned task and a claimless registration are distinguished by owner identity in both views', () => {
  const title = 'Codex / Office / Review the door schedule';
  const work = task('review', {title, plan: ['Check door widths']});
  const presence = {...task('presence'), id: 'declared-old', title: 'Check door widths'};
  const files = [session('review', title, 'Office'), session('presence', presence.title, 'Office', {task:presence.id})];
  const rows = homeRows({...state, tasks:[work, presence], approvals:[]}, {});
  for (const history of [false, true]) {
    const chart = homeMap({listed:{groups:[{sessions:files}]}, rows, params:DEFAULT, titleOf:r=>r.title, history, olderOpen:true});
    assert.deepEqual(plain(cards(chart).map(c=>[c.title,c.state,c.steps.length])), [[title,'Planned',1]]);
  }
});

test('archived work stays off Active and its original file remains reachable from history', () => {
  const extra = {groups: [...listed.groups, {project: {id: 'Tower', label: 'Tower'}, sessions: [session('review7', 'independently reviewed build 11', 'Tower', {task: 'session-1f2e'})]}]};
  const tasks = [...state.tasks, {id: 'session-9a8b', title: '7/7 complete on Build 11', status: 'ARCHIVED', updated_at: today, plan: [], progress: {}},
    {id: 'session-1f2e', title: 'independently reviewed build 11', status: 'ARCHIVED', updated_at: today, sessionPath: 'C:/s/review7.archhub', plan: [], progress: {}}];
  const view = (taskRows, history, olderOpen = false) => plain(homeMap({
    listed: extra, rows: homeRows({...state, tasks: taskRows}, {hidden: [], order: []}),
    params: DEFAULT, titleOf: row => row.title, history, olderOpen,
  }));
  assert.equal(at(view(tasks, false), 'review7'), undefined);
  assert.equal(at(view(tasks, true), 'review7'), undefined, 'the Older section starts folded');
  const archive = at(view(tasks, true, true), 'review7');
  assert.deepEqual([archive.path, archive.task, archive.archived], ['C:/s/review7.archhub', '', true]);
  assert.equal(cards(view(tasks, true, true)).some(card => card.title === '7/7 complete on Build 11'), false, 'no fake file for a row without one');
  const kept = [...tasks, {id: 'session-5c6d', title: 'Review he answered in', status: 'PLANNED', updated_at: today, plan: [], progress: {}}];
  assert.ok(cards(view(kept, true)).some(card => card.title === 'Review he answered in'));
  assert.ok(cards(view(kept, false)).some(card => card.title === 'Review he answered in'));
});

test('an input link is one wire from card edge to card edge, laid left to right, with the design\'s default type and what it carries', () => {
  const chart = draw();
  assert.deepEqual(chart.wires.map(wire => [wire.from, wire.fromPort, wire.to, wire.toPort, wire.type, wire.list, wire.label].join(' | ')).sort(),
    ['model | out | sheets | in | file | true | walls.out \u2192 walls', 'survey | out | model | in | file | true | points.out \u2192 points']);
  assert.ok(at(chart, 'survey').x < at(chart, 'model').x && at(chart, 'model').x < at(chart, 'sheets').x, 'a source sits left of what it feeds');
});

test('group, order, card, density, finished and the filter are parameters', () => {
  assert.deepEqual(draw({group: 'State'}).groups.map(group => group.key), ['Needs you', 'Failed', 'Working', 'Planned', 'Idle']);
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
  assert.equal(cards(draw({}, ['t-exp'], {history: false})).some(card => card.id === 'exp'), false, 'a session hidden from Home is not drawn');
});

test('a collapsed group is one node; every wire that crosses its edge stays', () => {
  const chart = draw({group: 'State', collapsed: ['Planned']});  // survey and sheets are Planned; model is Working
  const idle = chart.nodes.find(node => node.id === 'group:Planned');
  assert.equal(idle.collapsed, true);
  assert.equal(cards(chart).some(card => ['survey', 'sheets'].includes(card.id)), false);
  assert.deepEqual(chart.wires.map(wire => [wire.from, wire.to].join(' > ')).sort(), ['group:Planned > model', 'model > group:Planned']);
});

test('a narrow room stacks a group: unlinked sessions sit under the chain and groups wrap, so the map stays readable', () => {
  const room = r => plain(homeMap({listed, rows: homeRows(state, {hidden: [], order: []}), params: DEFAULT, titleOf: row => row.title, room: r, history: true}));
  const wide = room(1.6), narrow = room(.7), span = (chart, x = 'x', w = 'w') => Math.max(...chart.nodes.map(node => node[x] + node[w])) - Math.min(...chart.nodes.map(node => node[x]));
  const shape = chart => span(chart) / span(chart, 'y', 'h');
  const office = chart => chart.nodes.find(node => node.id === 'group:Office');
  assert.ok(office(narrow).w < office(wide).w, 'Office (three unlinked sessions) is one card wide in a narrow room');
  assert.ok(shape(narrow) < shape(wide), 'the whole map is taller than wide in a narrow room: ' + [shape(narrow), shape(wide)]);
  assert.deepEqual(cards(narrow).map(card => card.id).sort(), cards(wide).map(card => card.id).sort(), 'the same sessions are drawn');
});

test('nothing given up from the list: the All / Agent sessions / Workflows filter, the folded Older section, and his own order', () => {
  const base = homeRows(state, {hidden: [], order: []}), draw2 = extra => plain(homeMap({listed, rows: base, params: DEFAULT, titleOf: row => row.title, history: true, ...extra}));
  assert.equal(cards(draw2({kind: 'workflow'})).length, 0, 'no workflow file here: the Workflows filter shows none');
  assert.equal(cards(draw2({kind: 'agent-session'})).length, cards(draw2({})).length, 'every session here is an agent session');
  const workflow = session('reference', 'Codex / Design archive / reference-01', '', {task: '', kind: 'workflow'});
  const withWorkflow = {groups: [...listed.groups, {sessions: [workflow]}]};
  assert.deepEqual(cards(draw2({listed: withWorkflow, kind: 'workflow'})).map(card => card.path), [workflow.path]);
  assert.equal(at(draw2({listed: withWorkflow, history: false}), workflow.id), undefined);
  const activeFilter = {filter: 'Running'};
  const before = draw(activeFilter, [], {history: false});
  assert.deepEqual(cards(before).map(card => card.id), ['model']);
  assert.deepEqual(cards(draw({filter: 'Needs you'}, [], {history: true})).map(card => card.id).sort(), ['approval:b', 'exp']);
  assert.deepEqual(draw(activeFilter, [], {history: false}), before, 'history uses separate parameters from Active');
  // His order: the idle sessions in the order he dragged them (grouped by state, so they share one group).
  const idle = chart => cards(chart).filter(card => card.state === 'Planned').sort((a, b) => a.y - b.y || a.x - b.x).map(card => card.id);
  const byState = order => idle(plain(homeMap({listed, rows: base, params: {...DEFAULT, group: 'State'}, titleOf: row => row.id, order, history: true})));
  assert.deepEqual(byState(['t-sheets', 't-survey']), ['sheets', 'survey'], 'the drag order arranges the cards');
  assert.deepEqual(byState(['t-survey', 't-sheets']), ['survey', 'sheets']);
  // Old runs sit in their own folded section; unfolding it shows them.
  const old = {...base, sectionOf: () => 'Older / archived'};
  const folded = plain(homeMap({listed, rows: old, params: DEFAULT, titleOf: row => row.id, history: true}));
  const older = chart => chart.groups.find(group => group.key === 'Older / archived');
  assert.equal(older(folded).collapsed, true, 'folded until he opens it');
  assert.equal(folded.groups.at(-1).key, 'Older / archived', 'the last section');
  const open = plain(homeMap({listed, rows: old, params: DEFAULT, titleOf: row => row.id, olderOpen: true, history: true}));
  assert.equal(older(open).collapsed, false);
  assert.ok(cards(open).length > cards(folded).length, 'unfolded, its sessions are cards');
});

test('projects > tasks > subtasks: a subtask sits in its parent task group, one column right, wired from it; folding the parent hides every level under it', () => {
  const tree = {groups: [{project: {id: 'Tower', label: 'Tower'}, sessions: [session('drawings', 'Drawings', 'Tower'), session('plan', 'Ground floor plan', 'Tower'),
    session('tags', 'Door tags', 'Other')]}]};
  const tasks = [task('drawings'), task('plan', {parent: 't-drawings'}), task('tags', {parent: 't-plan'})];
  const view = (params = {}) => plain(homeMap({listed: tree, rows: homeRows({...state, tasks, approvals: []}, {hidden: [], order: []}), params: {...DEFAULT, ...params}, titleOf: row => row.id, history: true}));
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

test('the clicked Home file resolves across Windows path spellings in the command menu', async () => {
  const {chromium} = require('playwright');
  const browser = await chromium.launch({headless:true, channel:process.platform==='win32'?'chrome':undefined, executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
  try {
    const page = await browser.newPage();
    await page.route('https://home.test/**', route => route.fulfill({contentType:'text/html',
      body:'<main data-home-page><button data-home-session-path="C:/Sessions/B.archhub">B</button></main>'}));
    await page.goto('https://home.test/');
    await page.evaluate(() => { window.fetch = () => new Promise(() => {}); });
    const studio = path.resolve(__dirname, '../../01.APP/nodelang/studio');
    await page.addScriptTag({path:path.join(studio,'api.js')});
    await page.evaluate(() => {
      const winPath = name => ['c:','SESSIONS',name+'.ARCHHUB'].join(String.fromCharCode(92));
      let current = winPath('A');
      window.calls = [];
      window.UI = {api:{...window.ArchHubAPI, getSessionPath:()=>current,
        duplicateHomeTask:async(id,path)=>{window.calls.push(['duplicate',path]);return {taskId:'copy'};},
        runNode:()=>window.calls.push(current)}};
      window.ArchHubCommandRegistry = {commands:[{id:'menu.home.run',contexts:['session'],label:'Run'},{id:'menu.home.duplicate',contexts:['session'],label:'Duplicate'}]};
      const u = {close(){document.querySelectorAll('[role=menuitem]').forEach(e=>e.remove());}, openTaskFile:id=>window.calls.push(['open',id]), act:fn=>fn(), openSavedSession:async()=>{current=winPath('B');return {ok:true};},
        show:(_,props)=>{
          for(const [label,,,action] of props.surface.groups.flat()){
          const item=document.createElement('button');
          item.setAttribute('role','menuitem');item.textContent=label;item.onclick=action;
          document.body.append(item);
          }
        }};
      document.addEventListener('contextmenu',event=>window.UI.openSurfaceMenu(event,{tasks:[]},u));
    });
    await page.addScriptTag({content:transformSync(fs.readFileSync(path.join(studio,'context-menus.jsx'),'utf8'),{loader:'jsx'}).code});
    await page.getByRole('button',{name:'B',exact:true}).click({button:'right'});
    await page.getByRole('menuitem',{name:'Run'}).click();
    await page.getByRole('button',{name:'B',exact:true}).click({button:'right'});
    await page.getByRole('menuitem',{name:'Duplicate'}).click();
    assert.deepEqual(await page.evaluate(()=>window.calls),[['c:','SESSIONS','B.ARCHHUB'].join(path.win32.sep),
      ['duplicate','C:/Sessions/B.archhub'],['open','copy']]);
  } finally { await browser.close(); }
});

test('Duplicate on card B creates a distinct task and file while A is selected', async t => {
  const {chromium} = require('playwright');
  const {execFileSync} = require('node:child_process');
  const os = require('node:os');
  const root = path.resolve(__dirname, '../..');
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'home-duplicate-'));
  t.after(() => {
    if (path.dirname(profile) !== path.resolve(os.tmpdir())) throw Error('Unexpected fixture directory');
    fs.rmSync(profile, {recursive:true,force:true});
  });
  const env = {...process.env, PYTHONPATH:path.join(root,'01.APP'), PYTHONDONTWRITEBYTECODE:'1',
    USERPROFILE:profile, HOME:profile, LOCALAPPDATA:profile, APPDATA:profile, TEMP:profile, TMP:profile,
    ARCHHUB_TEST_STATE_DIR:path.join(profile,'state'), ARCHHUB_TEST_SECRET_STORE:'memory'};
  const owner = (script, input) => JSON.parse(execFileSync(process.env.ARCHHUB_TEST_PYTHON || process.env.ARCHHUB_COURT_PYTHON || 'python',
    ['-c',script], {cwd:root, env, input:JSON.stringify(input || {}), encoding:'utf8', timeout:20000, windowsHide:true}));
  const fixture = owner(`
import json
from nodelang import workshop_tasks as tasks
from nodelang.session_files import read_document, write_document
from nodelang.workshop_mailbox import application_history
with application_history() as history:
    a,b = [tasks.create(history,title,'founder') for title in ('Selected A','Clicked B')]
    doc = read_document(b['session_path'])
    doc['nodes'].append({'id':'clicked-step','title':'Clicked step','type':'note','params':{'text':'from B'},'position':{'x':0,'y':0}})
    write_document(b['session_path'],doc)
    tasks.open_session(history,a['id'])
    print(json.dumps({'a':a['id'],'b':b['id'],'path':b['session_path']}))
`, {});
  const before = fs.readFileSync(fixture.path);
  const browser = await chromium.launch({headless:true, channel:process.platform==='win32'?'chrome':undefined,
    executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
  t.after(() => browser.close());
  const page = await browser.newPage();
  await page.route('https://home.test/**',route=>route.fulfill({contentType:'text/html',
    body:'<main data-home-page><button>B</button></main><div id="menu"></div>'}));
  await page.goto('https://home.test/');
  await page.evaluate(()=>{window.fetch=()=>new Promise(()=>{});});
  const studio = path.join(root,'01.APP/nodelang/studio');
  await page.addScriptTag({path:path.join(studio,'api.js')});
  for(const file of ['react.js','react-dom.js'])await page.addScriptTag({path:path.join(studio,'vendor',file)});
  let created;
  await page.exposeFunction('duplicateFixture',(task,file)=>{
    assert.equal(task,fixture.b);
    created=owner(`
import json,sys
from nodelang.session_files import SessionFiles
print(json.dumps(SessionFiles().dispatch(json.load(sys.stdin))))
`,{action:'duplicate-home-task',task,path:file});
    return created;
  });
  await page.evaluate(f=>{
    const button=document.querySelector('main button');
    button.dataset.homeTask=f.b;
    button.dataset.homeSessionPath=f.path;
    const s={tasks:[{id:f.a,title:'A'},{id:f.b,title:'B',sessionPath:f.path}]};
    const root=window.ReactDOM.createRoot(document.getElementById('menu'));
    const u={task:f.a,close:()=>root.render(null),act:fn=>fn(),
      openTaskFile:id=>document.body.dataset.opened=id,
      show:(kind,props)=>root.render(React.createElement(window.UI.ContextMenu,{...props,kind,close:u.close}))};
    window.AHIcon=()=>null;
    window.UI={api:{...window.ArchHubAPI,duplicateHomeTask:window.duplicateFixture},
      useData:()=>s,useApp:()=>u,useAction:()=>null,ActionStatus:()=>null,
      bindActions:(names,handlers)=>(id,...args)=>handlers[names[id]](...args)};
    window.ArchHubCommandRegistry={commands:[{id:'menu.home.duplicate',contexts:['session'],label:'Duplicate'}]};
    document.addEventListener('contextmenu',event=>window.UI.openSurfaceMenu(event,s,u));
  },fixture);
  await page.addScriptTag({content:transformSync(fs.readFileSync(path.join(studio,'context-menus.jsx'),'utf8'),{loader:'jsx'}).code});
  await page.getByRole('button',{name:'B',exact:true}).click({button:'right'});
  await page.getByRole('menuitem',{name:'Duplicate',exact:true}).click();
  await page.waitForFunction(()=>document.body.dataset.opened);
  assert.equal(await page.locator('body').getAttribute('data-opened'),created.taskId);
  assert.ok(![fixture.a,fixture.b].includes(created.taskId));
  assert.notEqual(path.resolve(created.path),path.resolve(fixture.path));
  const copy=JSON.parse(fs.readFileSync(created.path));
  assert.equal(copy.properties.taskContext.task,created.taskId);
  assert.equal(copy.nodes.find(n=>n.id==='clicked-step').params.text,'from B');
  assert.deepEqual(fs.readFileSync(fixture.path),before);
});


test('Running filter and count use live work and held runs; interrupted work still offers recovery', () => {
  const tasks = [task('lost',{status:'WIP',outcome:'interrupted',stale:false,members:[{live:false}]}),
    task('worker',{status:'WIP',members:[{live:true}]}),task('paused',{status:'WIP',outcome:'paused',members:[{live:true}]}),
    task('approval',{status:'WIP',members:[{live:true}]})];
  for(const activity of ['resting','stopped','idle']){
    tasks.push(task(activity,{status:'WIP',members:[{id:activity,live:true}]}));
  }
  const sessions=['worker','resting','stopped','idle','paused','approval'].map(id=>({
    id,task:'t-'+id,status:['worker','paused','approval'].includes(id)?'working':id}));
  const rows = homeRows({tasks,agentGraph:{sessions},approvals:[{id:'gate',status:'pending',taskId:'t-approval'}]}, {});
  const build = filter => cards(homeMap({listed:{groups:[]},rows,params:{...DEFAULT,filter},titleOf:r=>r.title,olderOpen:true}));
  const items = build('All');
  assert.equal(items.find(c=>c.task==='t-lost').need.resume,true);
  assert.equal(items.find(c=>c.task==='t-lost').state,'Needs you');
  assert.equal(items.find(c=>c.task==='t-paused').state,'Paused');
  assert.equal(items.find(c=>c.task==='t-approval').state,'Needs you');
  assert.deepEqual(plain(build('Running').map(c=>c.task)),['t-worker']);
  assert.equal(rows.running,build('Running').length);
});

test('History opens the edited declaration canvas at its file path and omits an automatic registration', () => {
  const files = [false,true].map((authored,i)=>session('old'+i,'Earlier '+i,'Office',{
    task:'declared-'+i, authoredRegistration:authored}));
  const tasks = files.map(item=>({id:item.task,sessionPath:item.path,status:'WIP'}));
  const rows=homeRows({tasks},{}),listed={groups:[{sessions:files}]};
  const build = history => cards(homeMap({listed,rows,params:DEFAULT,titleOf:r=>r.title,history,olderOpen:true}));
  assert.equal(build(false).length,0);
  assert.deepEqual(plain(build(true).map(c=>[c.path,c.task])),[[files[1].path,'']]);
});

test('Tasks sharing one canvas each retain their own Home card and agent', () => {
  const document=session('shared','Project canvas','Tower',{task:'t-a'}), path=document.path;
  const make=(id,name)=>task(id,{sessionPath:path,workspace:'Tower',members:[{name}]});
  const rows=homeRows({...state,approvals:[],agentGraph:{sessions:[]},tasks:[make('b','Peer B'),make('a','Peer A')]},{});
  const chart=homeMap({listed:{groups:[{sessions:[document]}]},rows,params:DEFAULT,hidden:[],
    titleOf:r=>r.title,history:true,focus:'t-b',focusPath:path});
  const found=Array.from(chart.nodes).filter(n=>n.task);
  assert.deepEqual(found.map(n=>[n.task,n.agent]).sort(),[['t-a','Peer A'],['t-b','Peer B']]);
});

test('A folded and reopened project reports one canvas and its distinct tasks and subtasks', () => {
  const document=session('shared','Package','Tower',{task:'t-a'}), common={sessionPath:document.path,workspace:'Tower'};
  const tasks=[task('a',common),task('b',common),task('child',{...common,parent:'t-b'})];
  const rows=homeRows({...state, approvals:[], agentGraph:{sessions:[]}, tasks},{});
  for (const collapsed of [[],['Tower'],['task:t-b']]) {
    const chart=homeMap({listed:{groups:[{sessions:[document]}]}, rows, params:{...DEFAULT,collapsed},
      hidden:[],titleOf:r=>r.title,history:true});
    assert.equal(chart.groups[0].countText,'1 canvas · 2 tasks · 1 subtask');
    assert.equal(chart.nodes.find(n=>n.group).countText,chart.groups[0].countText);
  }
});

test('Make a task from this uses the message owner even with another task selected', async () => {
  const calls=[], opened=[];
  const ui={api:{createTask:async(...args)=>{calls.push(args);return {taskId:'new-task'};}}};
  const command={id:'menu.make.a.task.from.this',label:'Make a task from this',contexts:['message']};
  const sandbox=vm.createContext({window:{UI:ui,ArchHubCommandRegistry:{commands:[command]}}});
  const menu=fs.readFileSync(path.join(__dirname,'../../01.APP/nodelang/studio/context-menus.jsx'),'utf8');
  vm.runInContext(transformSync(menu,{loader:'jsx'}).code,sandbox);
  const menuRows=ui.contextCommandGroups({kind:'Task message menu',taskId:'B',message:{id:'msg',text:'Door check'},close(){}},
    {tasks:[{id:'A'},{id:'B'}],graph:{nodes:[]}}, {task:'A',openTaskFile:id=>opened.push(id)}, {run:fn=>fn()});
  await menuRows.flat().find(item=>item.command.id===command.id)[3]();
  assert.deepEqual(calls,[['Door check','','','','B']]);
  assert.deepEqual(opened,['new-task']);
});

test('A held task on a shared canvas has one Review action and one Needs you count', () => {
  const document=session('shared','Package','Tower',{task:'t-a'}), path=document.path;
  const tasks=['a','b'].map(id=>task(id,{sessionPath:path,workspace:'Tower'}));
  const card={id:'receipt',status:'pending',taskId:'t-a',taskIds:['t-a'],path,canvasNodes:[{taskId:'t-a',path,nodeId:'door'}]};
  const rows=homeRows({...state,agentGraph:{sessions:[]},tasks,approvals:[card]},{});
  assert.equal(rows.needsYou,1);
  assert.equal(rows.heldOf(tasks[1]),undefined);
  const chart=homeMap({listed:{groups:[{sessions:[document]}]},rows,params:DEFAULT,hidden:[],titleOf:r=>r.title,history:true});
  assert.deepEqual(Array.from(chart.nodes).filter(n=>n.need?.approval==='receipt').map(n=>n.task),['t-a']);
  const fileOnly=homeRows({...state,agentGraph:{sessions:[]},tasks,approvals:[{id:'file-hold',path,status:'pending'}]},{});
  assert.equal(fileOnly.needsYou,1);
  assert.equal(fileOnly.sessionRows.filter(row=>row.approval==='file-hold').length,1);
});

test('taskless workflows appear only while monitored or running, and pause stays reversible', () => {
  const files = ['timer','run','closed','manual'].map(id => session(id, id, '', {task: '',
    automation: [{kind: id === 'manual' ? 'trigger.manual' : 'trigger.schedule', armed: true}]}));
  const view = {history: false, rows: homeRows({...state,tasks:[],graphs:[],approvals:[],agentGraph:{sessions:[]}}, {hidden:[],order:[]}),
    listed: {groups:[{sessions:files}]}, workflowActivity: {[files[0].path]:{armed:1},[files[1].path]:{running:true}}};
  const active = draw({}, [], view);
  assert.deepEqual(cards(active).map(c=>c.id).sort(), ['run','timer']);
  assert.equal(at(active,'timer').state, 'Armed');
  assert.equal(at(active,'run').state, 'Running');
  assert.equal(active.running, 1);
  assert.equal(active.armed, 1);
  assert.deepEqual(cards(draw({filter:'Running'}, [], view)).map(c=>c.id), ['run']);
  const history = draw({}, [], {...view, history:true});
  assert.equal(at(history,'closed').state, 'Idle');
  assert.equal(at(history,'manual').state, 'Idle');
  const paused = draw({}, [], {...view, workflowActivity:{[files[0].path]:{paused:1}}});
  assert.equal(at(paused,'timer').state, 'Paused');
  assert.deepEqual([paused.running, paused.armed, paused.paused], [0,0,1]);
});

test('Home card with historical session members renders strictly live member avatars with no index numbers', () => {
  const React = require('react');
  const {renderToStaticMarkup} = require('react-dom/server');
  const uiContext = vm.createContext({
    React,
    window: {
      executeAction() {},
      registerActions() {},
      ArchHubAPI: {subscribe: () => () => {}, getSnapshot: () => ({agents: [], providers: [], agentGraph: {sessions: []}, tasks: []})},
      AH: {userAv: '#888', accent: '#3b82f6', blue: '#2563eb', purple: '#8b5cf6', ok: '#10b981', warn: '#f59e0b', cyan: '#06b6d4'},
      AH_DS: {Avatar: ({agent, size}) => React.createElement('span', {className: 'ds-avatar', 'data-size': size}, agent.ini)},
      UI: {}
    },
    console
  });
  const uiSrc = fs.readFileSync(path.join(__dirname, '../../01.APP/nodelang/studio/ui.jsx'), 'utf8');
  vm.runInContext(transformSync(uiSrc, {loader: 'jsx'}).code, uiContext);
  const Av = uiContext.window.UI.Av;

  const historical = Array.from({length: 80}, (_, i) => ({
    id: 'session-hist-' + i,
    name: 'Historical Agent ' + (i + 1),
    live: false,
    left: 1700000000 + i
  }));
  const liveMembers = [
    {id: 'live-lead', name: 'Live Lead Agent', live: true},
    {id: 'live-peer', name: 'Live Peer Agent', live: true}
  ];
  const allMembers = [...historical, ...liveMembers];

  const cardTask = task('multi-members', {status: 'WIP', members: allMembers});
  const cardSession = session('multi', 'Collaborative Session', 'Tower', {task: cardTask.id});
  const rows = homeRows({workspaces: [{id: 'Tower', name: 'Tower'}], tasks: [cardTask], graphs: [], approvals: [], agentGraph: {sessions: []}}, {});
  const chart = homeMap({
    listed: {groups: [{sessions: [cardSession]}]},
    rows,
    params: DEFAULT,
    hidden: [],
    titleOf: r => r.title,
    history: true
  });
  const node = at(chart, 'multi');
  assert.ok(node, 'card node exists in home map');
  assert.equal(node.agent, 'Live Lead Agent');
  assert.deepEqual(node.members, ['Live Peer Agent']);

  const cardElement = React.createElement('header', {className: 'home-card-head'},
    node.agent ? React.createElement(Av, {id: node.agent, size: 28}) : null,
    React.createElement('div', null,
      React.createElement('b', null, node.title),
      React.createElement('small', null, node.agent || 'No agent yet')
    ),
    node.members?.length > 0 ? React.createElement('span', {className: 'home-card-members', title: 'Also on this work: ' + node.members.join(', ')},
      node.members.slice(0, 3).map(name => React.createElement(Av, {key: name, id: name, size: 18}))
    ) : null,
    React.createElement('span', {className: 'home-card-state', 'data-state': node.state}, node.state)
  );

  const html = renderToStaticMarkup(cardElement);
  const avatarMatches = html.match(/class="agent-avatar"/g) || [];
  assert.equal(avatarMatches.length, 2, 'strictly live members rendered as avatars');

  const avatarSubstrings = [...html.matchAll(/<span class="agent-avatar"[^>]*>([\s\S]*?)<\/span>/g)].map(m => m[1]);
  for (const inner of avatarSubstrings) {
    assert.equal(inner.includes('<small>'), false, 'agent-avatar contains no <small> index tag');
  }
});
