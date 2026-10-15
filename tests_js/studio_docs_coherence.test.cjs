const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const studio = () => fs.readFileSync(path.join(root, 'nodelang/studio/studio-lm.jsx'), 'utf8');
const websiteDocs = () => fs.readFileSync(path.join(root, 'nodelang/website_docs_text.py'), 'utf8');

test('docs search has no hand-written DOC_INDEX parallel store', () => {
  const source = studio();
  assert.doesNotMatch(source, /\bconst\s+DOC_INDEX\b/);
  assert.match(source, /const buildDocsProjection = \(\{library, hosts\}\) =>/);
  assert.match(source, /sections\.map\(row => \(\{s:row\[0\], k:'page'/);
  assert.match(source, /nodeRows\.map\(row => \(\{s:'canvas', k:'topic'/);
  assert.match(source, /connectorRows\.map\(row => \(\{s:'connectors', k:'topic'/);
});

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

test('docs catalogue rows avoid raw engine ids and developer wording', () => {
  const source = studio();
  assert.match(source, /const docsNodeGroups = library =>/);
  assert.match(source, /<DNodeGroups groups=\{nodeGroups\}\/>/);
  assert.match(source, /data-docs-node-category=\{group\.cat\}/);
  assert.match(source, /data-docs-node-tile=""/);
  assert.doesNotMatch(source, new RegExp("cat \\+ ' / ' \\+ title"));
  assert.doesNotMatch(source, /item\.kind\s*\|\|\s*item\.engine/);
  assert.doesNotMatch(source, /item\.id\s*\|\|\s*'Untitled node'/);
  for (const forbidden of [
    'generated from the same catalogue',
    'registry owner publishes',
    'compatibility labels',
    'No host probe rows',
    'connector registry answered empty',
    'drag from the Nodes panel',
    'Press ⌘L',
  ]) {
    assert.doesNotMatch(source, new RegExp(forbidden.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
});

test('docs render node catalogue as grouped category tiles', () => {
  const source = studio();
  assert.match(source, /const\s+DNodeGroups\s*=/);
  assert.match(source, /data-docs-node-category=\{group\.cat\}/);
  assert.match(source, /data-docs-node-color=\{meta\.col\}/);
  assert.match(source, /data-docs-node-tile=""/);
  assert.match(source, /borderLeft:`3px solid \$\{meta\.col\}`/);
  assert.match(source, /background:meta\.col/);
  assert.match(source, /fontFamily:LM\.sans, fontSize:13/);
  assert.match(source, /<DNodeGroups\s+groups=\{nodeGroups\}\/>/);
  assert.doesNotMatch(source, /<DRows\s+rows=\{nodeRows\}\/>/);
});

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
  assert.match(source, /pinned verified build 20260916-2130-e733a13/);
});
