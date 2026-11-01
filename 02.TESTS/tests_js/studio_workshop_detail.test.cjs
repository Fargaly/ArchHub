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
