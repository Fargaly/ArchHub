const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const lm = fs.readFileSync(path.join(root, 'nodelang/studio/studio-lm.jsx'), 'utf8');
const params = fs.readFileSync(path.join(root, 'nodelang/studio/studio-params.jsx'), 'utf8');
const types = fs.readFileSync(path.join(root, 'nodelang/studio/param-types.jsx'), 'utf8');

function slice(source, start, end) {
  const a = source.indexOf(start);
  const b = source.indexOf(end, a + start.length);
  assert.ok(a >= 0 && b > a, 'missing slice: ' + start);
  return source.slice(a, b);
}

const renderer = slice(lm, 'const NodeRenderer = ', '// A card re-renders only when what it draws changed');
const socket = slice(lm, 'const Socket = ({ id, side', '// \u2500\u2500\u2500 per-category body content');
const liveBody = slice(lm, 'const LiveBody = ', 'const LinePreview = ');
const watchPreview = slice(lm, 'const WatchPreview = ', 'if (typeof window !==');
const paramRow = slice(params, 'function ParamRow', 'function AddParam');
const nodeInspector = slice(params, 'function NodeInspector', 'const editable = all.filter');

test('node cards use the DSYS 4.3 card anatomy and hide engine ids under the title', () => {
  assert.match(lm, /const NODE_CARD_W = 224;/);
  assert.match(renderer, /width:\s*cardW/);
  assert.match(renderer, /data-category-tile/);
  assert.match(renderer, /width:30,\s*height:30/);
  assert.match(renderer, /fontSize:14,\s*fontWeight:700/);
  assert.match(renderer, /fontSize:12/);
  assert.match(renderer, /nodeCardSubtitle\(n, cat\)/);
  assert.doesNotMatch(renderer, /\{n\.sub\}/);
  for (const raw of ['revit.sessions', 'core.watch', 'watch.preview']) {
    assert.equal(renderer.includes(raw), false, 'renderer exposes engine id ' + raw);
  }
});

test('ports are named, typed, coloured, and shaped by structure', () => {
  assert.match(socket, /data-socket-label=\{label/);
  assert.match(socket, /data-socket-type-label=\{socketTypeLabel\(t\)\}/);
  assert.match(socket, /data-socket-color=\{col\}/);
  assert.match(socket, /list \? 'diamond' : socketShapeOf\(t,\s*false\)/, 'list shape stays structural while scalar graph types remain intact');
  assert.match(socket, /data-socket-shape=\{socketShape\}/);
  assert.match(socket, /background: socketShape === 'any' \? 'transparent' : col/,'078 fills round and diamond sockets with the registry type colour');
  assert.match(socket, /border:`2px solid #17171c`/,'078 socket edge uses the card surface');
  assert.match(socket, /socketShape === 'diamond'/);
  assert.match(socket, /list \? 'diamond'.*'circle'/, '078 uses diamond lists and round scalar sockets while retaining the graph type');
  assert.match(socket, /data-socket-type=\{t \|\| 'any'\}/, 'the trigger/event type remains graph-owned');
  assert.match(socket, /socketShape === 'any'/);
  assert.match(renderer, /list=\{!!s\.list \|\| !!s\.multiple\}/);
});

test('Watch cards always render a DSYS 4.3b preview well', () => {
  assert.match(liveBody, /nodeIsWatch\(n\)/);
  assert.match(liveBody, /<WatchPreview node=\{n\}/);
  assert.match(watchPreview, /data-watch-well/);
  assert.match(watchPreview, /minWidth:\s*220/);
  assert.match(watchPreview, /maxHeight:\s*480/);
  assert.match(watchPreview, /preview = watchPreviewFor\(node\) \|\| watchFallbackPreview\(node\)/);
});

test('parameter rows use DSYS 4.6 one-row controls and hide internal params', () => {
  assert.match(params, /const PARAM_LABEL_COL = 96;/);
  assert.match(params, /const PARAM_ROW_H = 32;/);
  assert.match(paramRow, /data-param-row="true"/);
  assert.match(paramRow, /gridTemplateColumns:spec\.fixed \? [^\n]+ : `\$\{PARAM_LABEL_COL\}px minmax\(0,1fr\) auto`/);
  assert.match(paramRow, /minHeight:PARAM_ROW_H/);
  assert.match(paramRow, /humanParamLabel/);
  assert.match(paramRow, /data-param-control="true"/);
  assert.match(paramRow, /disabled:\s*false/);
  assert.match(nodeInspector, /INTERNAL_PARAM_KEYS\.has/);
  for (const key of ['source_digest', 'seed', 'image_path', 'session']) {
    assert.match(params, new RegExp("'" + key + "'"));
  }
});

test('parameter row actions use human labels only', () => {
  assert.doesNotMatch(paramRow, /skill JSON references it/);
  assert.doesNotMatch(paramRow, /key is fixed/);
  assert.doesNotMatch(paramRow, /<b[^>]*>\{spec\.k\}<\/b>/);
  assert.doesNotMatch(params, /fixed once created|key <b|new_param/);
  assert.match(paramRow, /stays compatible with saved runs/);
});

test('node-card lane has no snake_case labels or sub-11px card text', () => {
  assert.match(params, /humanParamLabel[\s\S]*replace\(\/[_-]\+\/g, ' '\)/);
  assert.match(lm, /nodeCardTitle\(n\)/);
  const cardSlices = [renderer, socket, liveBody, watchPreview, paramRow].join('\n');
  assert.doesNotMatch(cardSlices, /fontSize:\s*(?:[0-9](?:\.\d+)?|10(?:\.\d+)?)(?![0-9])/);
});

test('Revit wall parameters are human controls, and session stays the connected host', () => {
  assert.match(params, /level:\s*\{ label: 'Level', type: 'menu'/);
  assert.match(params, /scale_mm_px:\s*\{ label: 'Scale', unit: 'mm\/px'/);
  assert.match(params, /height_mm:\s*\{ label: 'Wall height', unit: 'mm'/);
  assert.match(params, /image_path:\s*\{ label: 'Image', type: 'path'/);
  assert.match(params, /session:\s*\{ label: 'Connected host', internal: true/);
});

test('node-card lane does not ship plate sample data in changed Studio JSX', () => {
  const changed = [lm, params, types].join('\n');
  for (const sample of ['Nile_Tower', 'Omar', 'sara@firm.com', 'Clinic', '46 doors', 'L3-D001', '09:14', 'run #48']) {
    assert.equal(changed.includes(sample), false, 'plate sample shipped: ' + sample);
  }
});

test('node-card controls are one-click routes or local state changes', () => {
  const surfaces = [renderer, socket, liveBody, watchPreview, paramRow].join('\n');
  const buttons = [...surfaces.matchAll(/<button\b/g)].map(match => surfaces.slice(match.index, surfaces.indexOf('</button>', match.index) + 9));
  assert.ok(buttons.length > 0, 'changed surfaces expose controls');
  for (const button of buttons) {
    assert.match(button, /onClick=\{/, 'button has a one-click action: ' + button);
  }
});
