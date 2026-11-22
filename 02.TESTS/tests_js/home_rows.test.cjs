// The Home list's rows and sections, run as the Studio runs them (studio/ds_home2.jsx loaded without a page).
// The header's "wait for you" count and the Canvas rail read the same rows, so they cannot disagree with the list.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {transformSync} = require('esbuild');

const source = fs.readFileSync(path.join(__dirname, '../../01.APP/nodelang/studio/ds_home2.jsx'), 'utf8');
const context = vm.createContext({window: {ArchHubAPI: {executeAction() {}}, AHIcon() {}, UI: {useData() {}, useApp() {}, Btn() {}, taskRowReason: () => ''}}});
vm.runInContext(transformSync(source, {loader: 'jsx'}).code, context);
const homeRows = context.window.UI.homeRows;
const today = new Date().toISOString();
const task = (id, extra = {}) => ({id, title: 'Task ' + id, status: 'PLANNED', updated_at: today, sessionPath: 'C:/s/' + id + '.archhub', ...extra});
const needing = seen => Array.from(seen.sessionRows).filter(row => seen.sectionOf(row) === 'Needs you').map(row => row.id).sort();

test('one count of what needs him: sessions with a held run or in review, plus a held run that belongs to no session here', () => {
  const state = {
    tasks: [task('a', {status: 'WIP', members: [{name: 'Agent one'}]}), task('b', {status: 'IN REVIEW'}), task('c'), task('d'), task('e')],
    approvals: [
      {id: '1', status: 'pending', work: 'a', input_digest: 'run-a'}, {id: '2', status: 'pending', work: 'a', input_digest: 'run-a'},  // two cards of one held run
      {id: '3', status: 'pending', approvalKind: 'canvas', path: 'C:/s/d.archhub'},        // a canvas run names its session by its file
      {id: '4', status: 'pending', work: 'elsewhere', title: 'Send the transmittal', who: 'Codex / Site / session-8dff5b479f68'},  // no session here
      {id: '5', status: 'pending', work: 'c'},                                             // on a session he hid from Home
      {id: '6', status: 'approved', work: 'e'}],
    graphs: [], agentGraph: {sessions: [{id: 'r1', name: 'Agent one', status: 'working', task: 'a'}]},
  };
  const seen = homeRows(state, {hidden: ['c'], order: []});
  assert.deepEqual(needing(seen), ['a', 'approval:4', 'approval:5', 'b', 'd']);
  assert.equal(seen.sectionOf(Array.from(seen.sessionRows).find(row => row.id === 'a')), 'Needs you', 'a held run needs him even while an agent works on the session');
  assert.equal(seen.needsYou, 5, 'the header says what the list shows: never "Nothing waiting" while a run is held');
  const orphan = Array.from(seen.sessionRows).find(row => row.id === 'approval:4');
  assert.deepEqual([orphan.title, orphan.approval, orphan.who], ['Send the transmittal', '4', 'Codex / Site / session-8dff5b479f68']);
  assert.deepEqual(needing(homeRows(state, undefined)), ['a', 'approval:4', 'b', 'c', 'd'], 'shown again, the hidden session carries its own run');
  assert.equal(homeRows({...state, tasks: []}, undefined).needsYou, 4, 'with no session at all every held run is a row, two cards of one run once');
  assert.equal(homeRows({...state, approvals: []}, undefined).needsYou, 1);
});

test('Home and the Canvas rail pick the selected session in one order: asked for, pinned, first listed; never a hidden one', () => {
  const state = {tasks: [task('a'), task('b', {homePinned: true}), task('c')], approvals: [], graphs: [], agentGraph: {sessions: []}};
  const seen = homeRows(state, {hidden: ['c'], order: []});
  assert.equal(seen.resumed('a').id, 'a');
  assert.equal(seen.resumed('').id, 'b');
  assert.equal(seen.resumed('c').id, 'b');
  assert.equal(homeRows({...state, tasks: [task('a'), task('c')]}, {hidden: ['c'], order: []}).resumed(undefined).id, 'a');
  assert.equal(homeRows({...state, tasks: []}, undefined).resumed('a'), undefined);
});

test('a live agent on a known session is a member of its row; standalone presence creates no Home row', () => {
  const state = {
    tasks: [task('a')], approvals: [], graphs: [],
    agentGraph: {sessions: [{id: 'r1', name: 'Claude Code / 00.ARCHUB / session-62fdf0706b09', status: 'working', task: 'a'},
      {id: 'r2', name: 'Codex / 11.ARCHHUB-APP / session-8dff5b479f68', status: 'working', task: null},
      {id: 'r3', name: 'Gemini CLI / site / session-07fb27aabcc0', status: 'idle', task: null}]},
  };
  const seen = homeRows(state, {hidden: [], order: []});
  assert.deepEqual(Array.from(seen.sessionRows, row => row.id + ' · ' + seen.sectionOf(row)), ['a · Working now']);
  assert.equal(seen.running, 1);
  assert.deepEqual(Array.from(seen.sessionRows[0].members, member => member.name), ['Claude Code / 00.ARCHUB / session-62fdf0706b09']);
  assert.equal(state.tasks[0].workingNow, undefined, 'the owner\'s task records are not changed');
});
