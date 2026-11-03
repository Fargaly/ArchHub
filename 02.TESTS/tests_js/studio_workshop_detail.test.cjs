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
const window = {
  ArchHubAPI: {executeAction() {}},
  UI: {
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
  assert.equal(home.includes('split(/\\s*\\.\\s*/)'), false);
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
  assert.match(home, /ItemList label="Rules"/);
  assert.match(home, /ItemList label="Assigned agents"/);
  assert.match(home, /choices \? <select/);
  assert.equal(home.includes("join('. ')"), false);
  assert.match(home, /event\.target\.value === row\) return/);
  assert.match(home, /useState\('home'\)|data-screen="home"/);
  assert.equal(fs.readFileSync(path.join(studio, 'app.jsx'), 'utf8').includes("useState('workshop')"), false);
  assert.match(fs.readFileSync(path.join(studio, 'app.jsx'), 'utf8'), /useState\('home'\)/);
  assert.match(fs.readFileSync(path.join(studio, 'studio.html'), 'utf8'), /Starting ArchHub/);
  assert.match(fs.readFileSync(path.join(studio, 'style.css'), 'utf8'), /#studio-boot\{position:fixed/);
  const screens = fs.readFileSync(path.join(studio, 'ds_screens.jsx'), 'utf8');
  assert.match(screens, /datasetWidth: 340/);
  assert.equal(screens.includes('datasetWidth: 478'), false);
  assert.equal(screens.includes('minmax(0,1fr)) 80px'), false);
  assert.match(screens, /data-dataset-grid/);
  assert.match(screens, /FIELD_WIDTH = \{text: 70, number: 92, integer: 108, point: 112/);
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

test('home canvas at 1440 keeps fitted nodes off the plan pane', async () => {
  const home = fs.readFileSync(path.join(studio, 'ds_home2.jsx'), 'utf8');
  const canvas = fs.readFileSync(path.join(studio, 'ds_screens.jsx'), 'utf8');
  assert.match(home, /<window\.UI\.Canvas active embedded \/>/);
  assert.equal(home.includes('dx-arrow'), false);
  assert.match(canvas, /embedded/);
  const {chromium} = require('playwright');
  const browser = await chromium.launch({headless: true, channel: 'msedge'});
  const page = await browser.newPage({viewport: {width: 1440, height: 900}});
  try {
    await page.setContent(`<!doctype html><style>
      body{margin:0}
      .dx-mid{display:grid;grid-template-columns:minmax(0,1fr) 200px;gap:16px;width:1440px;height:640px}
      .dx-canvas-mount{position:relative;height:100%;overflow:hidden}
      .dx-panel{min-width:0;overflow:hidden;position:relative}
      .node{position:absolute;width:280px;height:160px;background:#243}
    </style>
    <div class="dx-mid">
      <section class="dx-panel" data-dx="workflow"><div class="dx-canvas-mount" id="graph"></div></section>
      <section class="dx-panel" data-dx="plan" id="plan">Plan and progress</section>
    </div>`);
    const overlap = await page.evaluate(() => {
      const graph = document.getElementById('graph');
      const plan = document.getElementById('plan').getBoundingClientRect();
      const area = graph.getBoundingClientRect();
      const boxes = [{id: 'design', x: 40, y: 24, w: 280, h: 160}, {id: 'verify', x: 980, y: 80, w: 280, h: 180}];
      const minX = Math.min(...boxes.map(b => b.x)), minY = Math.min(...boxes.map(b => b.y));
      const width = Math.max(...boxes.map(b => b.x + b.w)) - minX;
      const height = Math.max(...boxes.map(b => b.y + b.h)) - minY;
      const z = Math.max(0.1, Math.min(4, 1.25, (area.width - 60) / Math.max(1, width), (area.height - 60) / Math.max(1, height)));
      const pan = {x: (area.width - width * z) / 2 - minX * z, y: (area.height - height * z) / 2 - minY * z};
      return boxes.map(box => {
        const node = document.createElement('div');
        node.className = 'node';
        node.dataset.graphNode = box.id;
        node.style.left = (pan.x + box.x * z) + 'px';
        node.style.top = (pan.y + box.y * z) + 'px';
        node.style.width = (box.w * z) + 'px';
        node.style.height = (box.h * z) + 'px';
        graph.appendChild(node);
        const rect = node.getBoundingClientRect();
        const hitsPlan = rect.right > plan.left + 0.5 && rect.left < plan.right && rect.bottom > plan.top && rect.top < plan.bottom;
        return {id: box.id, hitsPlan, inside: rect.left >= area.left - 0.5 && rect.right <= area.right + 0.5, right: rect.right, areaRight: area.right, planLeft: plan.left};
      });
    });
    const shot = path.join(process.env.TEMP || process.env.TMP || '.', 'designexact-proof', 'home-canvas-1440.png');
    fs.mkdirSync(path.dirname(shot), {recursive: true});
    await page.screenshot({path: shot});
    for (const node of overlap) {
      assert.equal(node.hitsPlan, false, node.id);
      assert.equal(node.inside, true, node.id);
    }
  } finally {
    await browser.close();
  }
});

test('a 1440 canvas fit keeps canonical nodes inside the graph and off the plan pane', () => {
  const screens = fs.readFileSync(path.join(studio, 'ds_screens.jsx'), 'utf8');
  const ui = {
    A: {ok: '#3a3', warn: '#a80', err: '#a33', ink: '#111', inkSoft: '#666', inkDim: '#888', accent: '#d97757', purple: '#86f', cyan: '#5cc', bgCanvas: '#101015', bgPanel: '#15151a', bgSoft: '#1a1a20', bgHover: '#222', line: '#26262e', lineSoft: '#333', accentDim: '#2a1812', rad: {xs: 3, sm: 5, md: 6, lg: 8, xl: 10, pill: 999}},
    D: {}, api: {}, useData() { return {}; }, useApp() { return {}; }, Btn() { return null; }, Chip() { return null; },
  };
  vm.runInNewContext(transformSync(screens, {loader: 'jsx', jsx: 'transform'}).code, {
    window: {UI: ui, executeAction() {}, registerActions() {}}, React, console,
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
    useData() {
      return {tasks: [{id: 't1', title: 'Ship the hall', status: 'WIP', description: 'Ship the hall', plan, progress, messages: []}], liveAgents: [], approvals: [], hosts: [], providers: []};
    },
    useApp() { return {task: 't1', act: fn => fn(), setTask() {}, go() {}, libraryOpen: false, setLibraryOpen() {}, show() {}}; },
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
  assert.equal(ship.label, 'not reported');
  assert.equal(ship.owner, 'Grove');
  assert.equal(recorded(plan[0], {}).label, 'not reported');
  assert.equal(recorded({id: 'later', title: 'Later'}, {draw: 'working'}).kind, 'unreported');
  const shown = renderToStaticMarkup(React.createElement(ui.Home));
  assert.match(shown, /data-step="working"/);
  assert.match(shown, /data-step="blocked"/);
  assert.match(shown, /data-step="error"/);
  assert.match(shown, /data-step="unreported"/);
  assert.match(shown, /not reported/);
  assert.match(shown, /Ada/);
  assert.equal(shown.includes('data-step="done"'), false);
});

test('workshop and canvas routes open that face of the selected task on Home', () => {
  const ui = {
    useData() {
      return {tasks: [{id: 't1', title: 'Ship the hall', status: 'WIP', description: 'Ship the hall', plan: [], messages: []}], liveAgents: [], approvals: [], hosts: []};
    },
    useApp() { return {task: 't1', act: fn => fn(), setTask() {}, go() {}, libraryOpen: false, setLibraryOpen() {}, show() {}}; },
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
  const canvas = renderToStaticMarkup(React.createElement(ui.Home));
  assert.match(canvas, /data-home-face="canvas"/);
  assert.match(canvas, /aria-label="Canvas view" aria-pressed="true"/);
  const app = fs.readFileSync(path.join(studio, 'app.jsx'), 'utf8');
  const home = fs.readFileSync(path.join(studio, 'ds_home2.jsx'), 'utf8');
  assert.match(app, /window\.UI\.homeDestination\?\.\(r\)/);
  assert.match(app, /ArchHubHomeFace = home\.face/);
  assert.match(app, /setRoute\('home'\)/);
  assert.equal(app.includes("r = 'canvas'"), false);
  assert.match(app, /u\.go\('workshop'\)/);
  assert.match(app, /u\.go\('canvas'\)/);
  assert.match(home, /u\.go\('canvas'\)/);
  assert.match(home, /ArchHubHomeFace === 'canvas'/);
});

test('the workshop face shows task-file messages and refreshes them when the task opens', () => {
  const opened = [];
  const task = {
    id: 't1', title: 'Ship the hall', status: 'WIP', description: 'Ship the hall', plan: [],
    fileMessages: [{id: 'file-1', role: 'task', who: 'Grove', text: 'The hall drawing is in the file'}],
    messages: [{id: 'room-1', role: 'room', who: 'Room', text: 'This room line stays out'}, {id: 'task-2', role: 'task', who: 'Ada', text: 'Ada wrote on the task'}],
  };
  const ui = {
    useData() { return {tasks: [task], liveAgents: [], approvals: [], hosts: [], providers: []}; },
    useApp() { return {task: 't1', act: fn => fn(), setTask() {}, go() {}, libraryOpen: false, setLibraryOpen() {}, show() {}}; },
    Btn(props) { return React.createElement('button', props, props.children); },
  };
  const api = {executeAction() {}, openTaskGraph(id) { opened.push(id); return Promise.resolve({taskId: id, messages: task.fileMessages}); }};
  vm.runInNewContext(transformSync(fs.readFileSync(path.join(studio, 'ds_home2.jsx'), 'utf8'), {loader: 'jsx', jsx: 'transform'}).code, {
    window: {UI: ui, AHIcon() { return null; }, ArchHubAPI: api, addEventListener() {}, removeEventListener() {}, localStorage: {getItem() { return null; }, setItem() {}}},
    React, document: {documentElement: {dataset: {}}, getElementById() { return null; }, querySelector() { return null; }}, console,
  });
  assert.equal(Array.from(ui.homeTaskMessages(task), item => String(item.text)).join('|'), 'The hall drawing is in the file|Ada wrote on the task');
  const html = renderToStaticMarkup(React.createElement(ui.Home));
  assert.match(html, /data-dx="conversation"/);
  assert.match(html, /The hall drawing is in the file/);
  assert.match(html, /Ada wrote on the task/);
  assert.equal(html.includes('This room line stays out'), false);
  const home = fs.readFileSync(path.join(studio, 'ds_home2.jsx'), 'utf8');
  assert.match(home, /openTaskGraph\(id\)/);
  assert.match(home, /openTaskGraph\(task\.id\)/);
  assert.equal(opened.length, 0);
});

test('home at 1440 keeps the conversation dominant and says an empty task once', () => {
  const longPath = 'C:/Users/fargaly/00.ARCHUB/30.KNOWLEDGE/35.DESIGN-SYSTEM/sessions/north-hall.archhub';
  const request = 'Please draw the north hall and keep this request in one place.';
  let current = {id: 't1', title: 'North hall', status: 'PLANNED', description: 'North hall', plan: [], messages: []};
  const ui = {
    useData() {
      return {tasks: [current], liveAgents: [], approvals: [], hosts: [], providers: []};
    },
    useApp() { return {task: 't1', act: fn => fn(), setTask() {}, go() {}, libraryOpen: false, setLibraryOpen() {}, show() {}}; },
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
  const empty = renderToStaticMarkup(React.createElement(ui.Home));
  assert.equal(empty.includes('Not yet recorded'), false);
  assert.match(empty, /aria-label="Find a task"/);
  assert.match(empty, /placeholder="Find a task…"/);
  assert.match(empty, /Save checkpoint/);
  assert.match(empty, /aria-label="Task title"/);
  assert.match(empty, /data-dx="empty"/);
  current = {id: 't1', title: 'North hall', status: 'PLANNED', description: request, plan: [], messages: [], session: longPath};
  const html = renderToStaticMarkup(React.createElement(ui.Home));
  assert.equal(html.includes('Not yet recorded'), false);
  assert.equal(html.includes('data-dx="empty"'), false);
  assert.equal(html.split(request).length - 1, 1);
  assert.match(html, /title="[^"]*north-hall\.archhub"/);
  const home = fs.readFileSync(path.join(studio, 'ds_home2.jsx'), 'utf8');
  const css = fs.readFileSync(path.join(studio, 'style.css'), 'utf8');
  assert.match(home, /id="tasks" className="dx-col" defaultSize=\{224\}/);
  assert.match(home, /id="params" className="dx-col" defaultSize=\{256\}/);
  assert.match(css, /\.dx-checkpoint-row\{display:flex;flex-wrap:nowrap/);
  assert.match(css, /\.dx-mid\{flex:1 1 auto/);
  assert.match(css, /minmax\(140px,200px\)/);
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
