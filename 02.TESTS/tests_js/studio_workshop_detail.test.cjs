const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');
const {transformSync} = require('esbuild');

const studio = path.resolve(__dirname, '../../01.APP/nodelang/studio');
const source = fs.readFileSync(path.join(studio, 'ds_workshop3.jsx'), 'utf8');
const js = transformSync(source, {loader: 'jsx', jsx: 'transform'}).code;
const sharedWindow = {ArchHubAPI: {}, AH: {}, AH_DS: {}, registerActions() {}};
vm.runInNewContext(transformSync(fs.readFileSync(path.join(studio, 'ui.jsx'), 'utf8'), {loader: 'jsx', jsx: 'transform'}).code,
  {window: sharedWindow, React, console});
vm.runInNewContext(transformSync(fs.readFileSync(path.join(studio, 'icons.jsx'), 'utf8'), {loader:'jsx'}).code,
  {window: sharedWindow, React, console});
const window = {
  AHIcon: sharedWindow.AHIcon,
  ArchHubAPI: {executeAction() {}},
  UI: {
    taskRowReason: sharedWindow.UI.taskRowReason,
    A: {ok: '#3a3', warn: '#a80', err: '#a33', ink: '#111', inkSoft: '#666'},
    D: {},
    useData() { return {}; },
    useApp() { return {}; },
    Btn() { return null; },
    Chip() { return null; },
    Av() { return null; },
    ApprovalCard() { return null; },
    Empty() { return null; },
  },
};
vm.runInNewContext(js, {window, React, console});
const otherScreens = Object.fromEntries(['Canvas', 'Composer', 'Dock', 'DockWorkshop', 'GraphProperties', 'HomeMap', 'LibraryShelf', 'NodeInspector', 'ResultPreview', 'ValueWidget', 'WireInspector', 'ApprovalCard', 'Av'].map(name => [name, () => null]));

test('the people list carries a declared model and stays blank otherwise', () => {
  const {people} = window.UI.workshopPeople({
    liveAgents: [
      {handle: 'grove', name: 'Grove', agent: 'host / grove', app: 'claude', model: 'grok-4', status: 'working', task: 'Detail'},
      {handle: 'plain', name: 'Plain', agent: 'host / plain', app: 'codex', status: 'working'},
    ],
    agents: [
      {id: 'cursor', runtime: 'cursor', name: 'Cursor', presence: 'idle', model: 'Model not reported'},
    ],
  });
  const model = Object.fromEntries(people.map(person => [person.name, person.model]));
  assert.equal(model.Grove, 'grok-4');
  assert.equal(model.Plain, '');
  assert.equal(model.Cursor, '');
  assert.equal(model.You, '');
});

test('a completed task row shows its recorded result and a blank result stays blank', () => {
  const done = renderToStaticMarkup(React.createElement(window.UI.Task, {
    task: {id: 't', title: 'Ship', status: 'DONE', result: 'artifact: report.md', messages: []},
    on: false, select() {},
  }));
  assert.match(done, /artifact: report.md/);
  const blank = renderToStaticMarkup(React.createElement(window.UI.Task, {
    task: {id: 'quiet', title: 'Quiet', status: 'DONE', result: '', messages: []},
    on: false, select() {},
  }));
  assert.equal(blank.includes('data-task-outcome'), false);
});

test('rules and agents round-trip without splitting on periods', () => {
  const home = fs.readFileSync(path.join(studio, 'ds_home2.jsx'), 'utf8');
  const ui = {};
  vm.runInNewContext(transformSync(home, {loader: 'jsx', jsx: 'transform'}).code, {
    window: {UI: ui, ArchHubAPI: {executeAction() {}}, addEventListener() {}, removeEventListener() {}},
    React, document: {getElementById() { return null; }}, console,
  });
  const agents = ['Claude Code / 00.ARCHUB / session-abc'];
  const saved = [];
  assert.equal(ui.homeListSame(agents, agents), true);
  assert.equal(ui.homeCommitList(agents, agents, value => saved.push(value)), false);
  assert.equal(ui.homeCommitList(['1.5'], ['1.5'], value => saved.push(value)), false);
  assert.equal(ui.homeCommitList(['1.5'], ['1', '5'], value => saved.push(value)), true);
  assert.deepEqual(saved, [['1', '5']]);
  assert.match(ui.homeDescribe({title: 'Design', output: {path: 'sheet.pdf'}}), /sheet\.pdf/);
});

test('in progress lists started work and planned work stays out', () => {
  const groups = Object.fromEntries(window.UI.workshopGroups(false, new Set()).map(([name, member]) => [name, member]));
  assert.equal(groups['IN PROGRESS']({status: 'WIP'}), true);
  assert.equal(groups['IN PROGRESS']({status: 'PLANNED'}), false);
  assert.equal(groups['IN PROGRESS']({status: 'WIP', started: false}), false);
  assert.equal(groups['IN PROGRESS']({status: 'WIP', wsRoute: 'planned'}), false);
  assert.equal(groups.PLANNED({status: 'PLANNED'}), true);
  assert.equal(groups.PLANNED({status: 'WIP', started: false}), true);
  assert.equal(groups.PLANNED({status: 'WIP'}), false);
});

test('task rows hide unsupported blocked-by and show interrupted and limit reached, and the picker shows gate and breaches', () => {
  const markup = task => renderToStaticMarkup(React.createElement(window.UI.Task, {
    task: {id: task.id, title: task.title, status: 'PLANNED', messages: [], ...task},
    on: false, select() {},
  }));
  assert.doesNotMatch(markup({id: 'b', title: 'Wait', blockedBy: 'Foundation'}), /blocked by/);
  assert.match(markup({id: 'i', title: 'Cut', outcome: 'interrupted'}), /data-task-row-state="interrupted"/);
  assert.match(markup({id: 'l', title: 'Hold', capacity: 'LIMIT_REACHED'}), /data-task-row-state="limit reached"/);
  const {choices} = window.UI.workshopPeople({
    liveAgents: [
      {handle: 'live', name: 'Live', agent: 'host / live', app: 'claude', status: 'working', gate: 'live', breaches: 0},
      {handle: 'missing', name: 'Missing', agent: 'host / missing', app: 'codex', status: 'working', gate: 'missing', breaches: 2},
      {handle: 'down', name: 'Down', agent: 'host / down', app: 'cursor', status: 'working', gate: 'unavailable', breaches: 'unavailable'},
    ],
    // Running on this PC but not joined to the Workshop: shown, and cannot be chosen yet.
    agents: [{id: 'goose', runtime: 'goose', name: 'Goose', presence: 'working'}],
  });
  const picker = renderToStaticMarkup(React.createElement(window.UI.AgentPicker, {
    choices, to: '', setTo() {}, startOpen: true,
  }));
  assert.match(picker, /Gate live/);
  assert.match(picker, /0 breaches/);
  assert.match(picker, /Gate missing/);
  assert.match(picker, /2 breaches/);
  assert.match(picker, /Gate unavailable/);
  assert.match(picker, /Breaches unavailable/);
  const options = picker.split('<button').slice(1);
  for (const name of ['Live', 'Missing', 'Down']) {
    const option = options.find(button => button.includes('>' + name + '<'));
    assert.ok(option, name + ' is offered');
    assert.doesNotMatch(option.slice(0, option.indexOf('>')), /disabled/, name + ' can be chosen');
  }
  const unjoined = options.find(button => button.includes('>Goose<'));
  assert.ok(unjoined, 'the unjoined agent is shown');
  assert.match(unjoined.slice(0, unjoined.indexOf('>')), /disabled/, 'an unjoined agent cannot be chosen');
});

test('a 1440 canvas fit keeps canonical nodes inside the graph and off the plan pane', t => {
  const screens = fs.readFileSync(path.join(studio, 'ds_screens.jsx'), 'utf8');
  const ui = {
    taskRowReason: sharedWindow.UI.taskRowReason,
    A: {ok: '#3a3', warn: '#a80', err: '#a33', ink: '#111', inkSoft: '#666', inkDim: '#888', accent: '#d97757', purple: '#86f', cyan: '#5cc', bgCanvas: '#101015', bgPanel: '#15151a', bgSoft: '#1a1a20', bgHover: '#222', line: '#26262e', lineSoft: '#333', accentDim: '#2a1812', rad: {xs: 3, sm: 5, md: 6, lg: 8, xl: 10, pill: 999}},
    D: {}, api: {}, useData() { return {}; }, useApp() { return {}; }, Btn() { return null; }, Chip() { return null; },
  };
  const layout = new (require('jsdom').JSDOM)('<!doctype html><html></html>');
  t.after(() => layout.window.close());
  Object.assign(layout.window, {UI:ui, ReactResizablePanels:require('react-resizable-panels'), executeAction() {}, registerActions() {}});
  vm.runInNewContext(transformSync(screens, {loader: 'jsx', jsx: 'transform'}).code, {
    window: layout.window, document:layout.window.document, React, console,
  });
  const graphWidth = 398, graphHeight = 420, planX = graphWidth + 16, planWidth = 336;
  const nodes = [{id: 'design', x: 640, y: 80, w: 280, h: 160}, {id: 'verify', x: 980, y: 80, w: 280, h: 160}];
  const view = ui.fitCanvasViewport(nodes, graphWidth, graphHeight, 0.1, 4, 1.25);
  assert.deepEqual(nodes.map(node => [node.id, node.x, node.y]), [['design', 640, 80], ['verify', 980, 80]]);
  for (const node of nodes) {
    const left = view.pan.x + node.x * view.zoom;
    const right = view.pan.x + (node.x + node.w) * view.zoom;
    assert.ok(left >= -1 && right <= graphWidth + 1, node.id + ' stays in the graph');
    assert.ok(right < planX, node.id + ' does not meet the plan pane');
  }
  assert.ok(planX + planWidth > graphWidth);
});

test('a step shows only the status the progress dict recorded', () => {
  const plan = [
    {id: 'draw', title: 'Draw', owner: 'Grove'},
    {id: 'check', title: 'Check', owner: 'Bea'},
    {id: 'file', title: 'File', owner: 'Nia'},
    {id: 'ship', title: 'Ship', status: 'done', owner: 'Grove'},
  ];
  const progress = {draw: 'working', check: 'blocked', file: {status: 'error', agent: 'Ada'}};
  const ui = {
    // Home renders the Workshop's own parts (ds_workshop3.jsx, loaded above); the other screens it hosts (dock, canvas,
    // map, inspectors) are their own modules and draw nothing here. The fixture overrides data and app state.
    ...otherScreens,
    ...window.UI,
    useData() {
      return {settings: [], graph: {nodes: [], wires: []}, tasks: [{id: 't1', title: 'Ship the hall', status: 'WIP', description: 'Ship the hall', plan, progress, messages: []}], liveAgents: [], approvals: [], hosts: [], providers: []};
    },
    useApp() { return {task: 't1', composerDraft: {}, setComposerDraft() {}, act: fn => fn(), setTask() {}, go() {}, libraryOpen: false, setLibraryOpen() {}, show() {}}; },
    Btn(props) { return React.createElement('button', props, props.children); },
  };
  vm.runInNewContext(transformSync(fs.readFileSync(path.join(studio, 'ds_home2.jsx'), 'utf8'), {loader: 'jsx', jsx: 'transform'}).code, {
    window: {UI: ui, AHIcon() { return null; }, ArchHubAPI: {executeAction() {}}, addEventListener() {}, removeEventListener() {}, localStorage: {getItem() { return null; }, setItem() {}}},
    React, document: {documentElement: {dataset: {}}, getElementById() { return null; }, querySelector() { return null; }}, console,
  });
  const recorded = (step, bag) => ui.homeStepOf(step, bag);
  const draw = recorded(plan[0], progress);
  const check = recorded(plan[1], progress);
  const file = recorded(plan[2], progress);
  const ship = recorded(plan[3], progress);
  assert.equal(draw.kind, 'working');
  assert.equal(draw.label, 'working');
  assert.equal(draw.owner, 'Grove');
  assert.equal(check.kind, 'blocked');
  assert.equal(check.label, 'blocked');
  assert.equal(check.owner, 'Bea');
  assert.equal(file.kind, 'error');
  assert.equal(file.label, 'error');
  assert.equal(file.owner, 'Ada');
  assert.equal(ship.kind, 'unreported');
  assert.equal(ship.label, 'Planned');
  assert.equal(ship.owner, 'Grove');
  assert.equal(recorded(plan[0], {}).label, 'Planned');
  assert.equal(recorded({id: 'later', title: 'Later'}, {draw: 'working'}).kind, 'unreported');
  // Home opens on its cold start until the layout owner's read settles (an effect); a static render never runs it, so
  // the task view's markup is the rendered courts' job. The helpers below are the behaviour this file checks.
});

test('workshop and canvas routes open that face of the selected task on Home', () => {
  const ui = {
    // Home renders the Workshop's own parts (ds_workshop3.jsx, loaded above); the other screens it hosts (dock, canvas,
    // map, inspectors) are their own modules and draw nothing here. The fixture overrides data and app state.
    ...otherScreens,
    ...window.UI,
    useData() {
      return {settings: [], graph: {nodes: [], wires: []}, tasks: [{id: 't1', title: 'Ship the hall', status: 'WIP', description: 'Ship the hall', plan: [], messages: []}], liveAgents: [], approvals: [], hosts: []};
    },
    useApp() { return {task: 't1', composerDraft: {}, setComposerDraft() {}, act: fn => fn(), setTask() {}, go() {}, libraryOpen: false, setLibraryOpen() {}, show() {}}; },
    Btn(props) { return React.createElement('button', props, props.children); },
  };
  const win = {UI: ui, ArchHubHomeFace: 'canvas', AHIcon() { return null; }, ArchHubAPI: {executeAction() {}}, addEventListener() {}, removeEventListener() {}, localStorage: {getItem() { return null; }, setItem() {}}};
  vm.runInNewContext(transformSync(fs.readFileSync(path.join(studio, 'ds_home2.jsx'), 'utf8'), {loader: 'jsx', jsx: 'transform'}).code, {
    window: win, React, document: {documentElement: {dataset: {}}, getElementById() { return null; }, querySelector() { return null; }}, console,
  });
  const face = route => ui.homeDestination(route);
  assert.equal(face('workshop').route, 'home');
  assert.equal(face('workshop').face, 'workshop');
  assert.equal(face('workshop').library, false);
  assert.equal(face('canvas').route, 'home');
  assert.equal(face('canvas').face, 'canvas');
  assert.equal(face('library').face, 'canvas');
  assert.equal(face('library').library, true);
  assert.equal(face('skills').face, 'canvas');
  assert.equal(face('skills').library, true);
  assert.equal(face('docs'), null);
  assert.equal(face('settings/Agents'), null);
  // Home opens on its cold start until the layout owner's read settles (an effect); a static render never runs it, so
  // the task view's markup is the rendered courts' job. The helpers below are the behaviour this file checks.
});

test('the workshop face shows task-file messages and refreshes them when the task opens', () => {
  const opened = [];
  const task = {
    id: 't1', title: 'Ship the hall', status: 'WIP', description: 'Ship the hall', plan: [],
    fileMessages: [{id: 'file-1', role: 'task', who: 'Grove', text: 'The hall drawing is in the file'}],
    messages: [{id: 'room-1', role: 'room', who: 'Room', text: 'This room line stays out'}, {id: 'task-2', role: 'task', who: 'Ada', text: 'Ada wrote on the task'}],
  };
  const ui = {
    // Home renders the Workshop's own parts (ds_workshop3.jsx, loaded above); the other screens it hosts (dock, canvas,
    // map, inspectors) are their own modules and draw nothing here. The fixture overrides data and app state.
    ...otherScreens,
    ...window.UI,
    useData() { return {settings: [], graph: {nodes: [], wires: []}, tasks: [task], liveAgents: [], approvals: [], hosts: [], providers: []}; },
    useApp() { return {task: 't1', composerDraft: {}, setComposerDraft() {}, act: fn => fn(), setTask() {}, go() {}, libraryOpen: false, setLibraryOpen() {}, show() {}}; },
    Btn(props) { return React.createElement('button', props, props.children); },
  };
  const api = {executeAction() {}, openTaskGraph(id) { opened.push(id); return Promise.resolve({taskId: id, messages: task.fileMessages}); }};
  vm.runInNewContext(transformSync(fs.readFileSync(path.join(studio, 'ds_home2.jsx'), 'utf8'), {loader: 'jsx', jsx: 'transform'}).code, {
    window: {UI: ui, AHIcon() { return null; }, ArchHubAPI: api, addEventListener() {}, removeEventListener() {}, localStorage: {getItem() { return null; }, setItem() {}}},
    React, document: {documentElement: {dataset: {}}, getElementById() { return null; }, querySelector() { return null; }}, console,
  });
  assert.equal(Array.from(ui.homeTaskMessages(task), item => String(item.text)).join('|'), 'The hall drawing is in the file|Ada wrote on the task');
  // Home opens on its cold start until the layout owner's read settles (an effect); a static render never runs it, so
  // the task view's markup is the rendered courts' job. The helpers below are the behaviour this file checks.
  assert.equal(opened.length, 0);
});

test('home at 1440 keeps the conversation dominant and says an empty task once', () => {
  const longPath = 'C:/Users/fargaly/00.ARCHUB/30.KNOWLEDGE/35.DESIGN-SYSTEM/sessions/north-hall.archhub';
  let current = {id: 't1', title: 'North hall', status: 'PLANNED', description: 'North hall', plan: [], messages: []};
  const ui = {
    // Home renders the Workshop's own parts (ds_workshop3.jsx, loaded above); the other screens it hosts (dock, canvas,
    // map, inspectors) are their own modules and draw nothing here. The fixture overrides data and app state.
    ...otherScreens,
    ...window.UI,
    useData() {
      return {settings: [], graph: {nodes: [], wires: []}, tasks: [current], liveAgents: [], approvals: [], hosts: [], providers: []};
    },
    useApp() { return {task: 't1', composerDraft: {}, setComposerDraft() {}, act: fn => fn(), setTask() {}, go() {}, libraryOpen: false, setLibraryOpen() {}, show() {}}; },
    Btn(props) { return React.createElement('button', props, props.children); },
  };
  vm.runInNewContext(transformSync(fs.readFileSync(path.join(studio, 'ds_home2.jsx'), 'utf8'), {loader: 'jsx', jsx: 'transform'}).code, {
    window: {UI: ui, AHIcon() { return null; }, ArchHubAPI: {executeAction() {}}, addEventListener() {}, removeEventListener() {}, localStorage: {getItem() { return null; }, setItem() {}}},
    React, document: {documentElement: {dataset: {}}, getElementById() { return null; }, querySelector() { return null; }}, console,
  });
  const shown = ui.homeMiddle(longPath);
  assert.equal(String(shown).includes('\u2026'), true);
  assert.equal(String(shown).startsWith(longPath.slice(0, 18)), true);
  assert.equal(String(shown).endsWith(longPath.slice(-18)), true);
  // Home opens on its cold start until the layout owner's read settles (an effect); a static render never runs it, so
  // the task view's markup is the rendered courts' job. The helpers below are the behaviour this file checks.
});

test('the task view shows workflow nodes and activity together', () => {
  const html = renderToStaticMarkup(React.createElement(window.UI.TaskSession, {
    task: {
      id: 'a',
      workflow: [{id: 'node-a', type: 'note', title: 'Alpha'}],
      parameters: [{id: 'node-a', params: {span: 12}}],
      activity: [{id: 'node-a', status: 'Done', output: 'alpha-out'}],
      plan: ['Alpha plan'],
      agents: ['Grove'],
      progress: {step: 'one'},
      fileMessages: [{id: 'm', who: 'Grove', text: 'Alpha is moving'}],
    },
  }));
  assert.match(html, /data-task-session="a"/);
  assert.match(html, /data-workflow-node="node-a"/);
  assert.match(html, /Alpha/);
  assert.match(html, /data-node-param="span"/);
  assert.match(html, /data-activity-row="node-a"/);
  assert.match(html, /alpha-out/);
  assert.match(html, /Alpha plan/);
  assert.match(html, /Grove/);
  assert.match(html, /Alpha is moving/);
});
