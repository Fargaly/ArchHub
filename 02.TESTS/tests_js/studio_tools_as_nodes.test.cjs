const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..');

const library = fs.readFileSync(path.join(root, '01.APP/nodelang/library_engines.py'), 'utf8');
const pipeline = fs.readFileSync(path.join(root, '01.APP/nodelang/pipeline_engines.py'), 'utf8');

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
