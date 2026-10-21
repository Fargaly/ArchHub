const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const studio = fs.readFileSync(path.join(root, 'nodelang/studio/studio-lm.jsx'), 'utf8');
const library = fs.readFileSync(path.join(root, 'nodelang/library_engines.py'), 'utf8');
const pipeline = fs.readFileSync(path.join(root, 'nodelang/pipeline_engines.py'), 'utf8');

test('tool icons are removed from the icon rail', () => {
  const rail = studio.slice(studio.indexOf('const Frame ='), studio.indexOf('const isHistoryNode ='));
  assert.doesNotMatch(rail, /toolRows\.map/);
  for (const id of ['studio', 'workshop', 'brain', 'baboom', 'connectors', 'cloud']) {
    assert.doesNotMatch(rail, new RegExp('dataToolRail=\\{' + id + '\\}|data-tool-rail="' + id + '"'));
  }
  assert.match(rail, /onSettings/);
});

test('every Hub tool has a node-library card backed by a real engine', () => {
  const expected = {
    studio: 'tool.studio',
    workshop: 'tool.workshop',
    brain: 'tool.brain',
    baboom: 'tool.baboom',
    connectors: 'tool.connectors',
    cloud: 'tool.cloud',
  };
  for (const [id, engine] of Object.entries(expected)) {
    assert.match(library, new RegExp('"tool_' + id + '"'));
    assert.match(library, new RegExp('"engine": "' + engine.replace('.', '\\.') + '"'));
    assert.match(pipeline, new RegExp('"' + engine.replace('.', '\\.') + '"'));
  }
});
