/* Canvas card ports: structural checks on the stylesheet the canvas RENDERS (the
   graph-held universal_presentation_seed.STYLESHEET) and on the port placement code.
   The acceptance proof is rendered, not here: tests_replica/test_canvas_ports_rendered.py
   measures real rects in headless Chrome (long text, absent value row, zoom 0.5 / 2,
   resize). The port band's numbers are read from this stylesheet when the canvas
   script is built (ui_runtime.card_content_rows), so nothing here mirrors them. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const runtime = fs.readFileSync(path.join(root, 'nodelang/ui_runtime.py'), 'utf8');
const css = fs.readFileSync(path.join(root, 'nodelang/universal_presentation_seed.py'), 'utf8');

function block(source, start) {
  const at = source.indexOf(start);
  if (at < 0) return null;
  let depth = 0, i = source.indexOf('{', at);
  for (; i < source.length; i++) {
    if (source[i] === '{') depth++;
    else if (source[i] === '}' && --depth === 0) break;
  }
  return source.slice(at, i + 1);
}
function rule(selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const found = [...css.matchAll(new RegExp("(?:^|}|'|\\n)" + escaped + '\\{([^}]*)\\}', 'g'))].map(m => m[1]);
  return found.length ? found[found.length - 1] : null;
}

test('the rendered stylesheet gives every card content row a fixed one-line height', () => {
  for (const selector of ['.graph-node>.node-head', '.graph-node>.node-title', '.graph-node>.node-summary',
      '.graph-node>.node-params>.node-param', '.graph-node>.node-value']) {
    const declarations = rule(selector) || '';
    assert.match(declarations, /(^|;)height:\d+px/, selector + ' has a fixed height');
    assert.match(declarations, /white-space:nowrap/, selector + ' does not wrap');
    assert.match(declarations, /overflow:hidden/, selector + ' clips');
  }
});

test('port names never draw inside the card; no legacy port-over-content rule', () => {
  assert.match(rule('.graph-node .node-port') || '', /font-size:0/);
  assert.equal(/\.node-port\[data-port-index="\d+"\]\{top:/.test(css), false);
  assert.equal(/\.node-value\{[^}]*background:var\(--bg-panel\)/.test(css), false);
});

test('the port band numbers are derived from the stylesheet, not written in the script', () => {
  assert.match(runtime, /const CARD_ROWS=\{__CARD_ROWS__,band:4\};/);
  assert.match(runtime, /def card_content_rows\(/);
});

test('port placement reads no layout, so zoom, pan and resize cannot thrash', () => {
  for (const start of ['function cardContentHeight(', 'function portBandTop(', 'function projectedNodeHeight(',
      'function positionCanvasPort(']) {
    const piece = block(runtime, start);
    assert.ok(piece, start);
    assert.doesNotMatch(piece, /offset(Top|Height|Left|Width)|getBoundingClientRect|getComputedStyle|clientHeight|scrollHeight/,
      start + ' reads no layout');
  }
});
