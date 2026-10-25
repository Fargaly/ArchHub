const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..', '..');

const websiteDocs = () => fs.readFileSync(path.join(root, '01.APP/nodelang/site_export.py'), 'utf8');

test('website docs describe provider connection without paste instructions', () => {
  const source = websiteDocs();
  for (const forbidden of [
    'BYO',
    'paste the credential',
    'OpenRouter field',
    'not promoted unless the running catalogue publishes',
    'Drag a node',
    'Search, then click a node',
    'Click an output socket',
    'Click a node to select',
    'Click empty canvas',
    'Press Run graph',
    'current released build',
  ]) {
    assert.doesNotMatch(source, new RegExp(forbidden.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.match(source, /Provider accounts are connected from Settings, Providers\./);
  assert.doesNotMatch(source, /pinned verified build 20260916-2130-e733a13/);
});

const studio = () => fs.readFileSync(path.join(root, '01.APP/nodelang/studio/docs.jsx'), 'utf8');

test('docs page removes invented local API and status claims', () => {
  const source = studio();
  for (const forbidden of [
    'GET  /v1/hosts',
    'GET  /v1/sessions',
    'GET  /v1/skills',
    'GET  /v1/brain?layer=project',
    '<DSub>STATUS</DSub>',
    'no relay owner',
    'route \' + route',
  ]) {
    assert.doesNotMatch(source, new RegExp(forbidden.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
});
test('docs search has no hand-written DOC_INDEX parallel store',()=>{assert.doesNotMatch(studio(),/\bconst\s+DOC_INDEX\b/);});
