'use strict';
// D-017 building block: ONE design source. design-tokens.json is the Penpot file's token library
// (W3C DTCG); compile_studio.cjs generates the studio CSS variables and the window.AH palette from it.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..', '..');
const studio = path.join(root, '01.APP/nodelang/studio');
const read = name => fs.readFileSync(path.join(studio, name), 'utf8');
const {designTokens, tokenCss, cssName, CSS_BEGIN, CSS_END} = require(path.join(root, '03.TOOLS/packaging/compile_studio.cjs'));

const css = read('style.css');
const block = css.slice(0, css.indexOf(CSS_END) + CSS_END.length);
const rest = css.slice(block.length);

test('every design token is generated into the studio CSS, unchanged', () => {
  const tokens = designTokens();
  assert.ok(css.startsWith(CSS_BEGIN), 'style.css starts with the generated token block');
  assert.equal(block, tokenCss(tokens), 'the block is exactly what design-tokens.json generates');
  const declared = new Set([...block.matchAll(/(--[\w-]+):/g)].map(m => m[1]));
  for (const name of tokens.keys()) assert.ok(declared.has(cssName(name)), name + ' is declared');
  assert.equal(declared.size, tokens.size);
});

test('no studio CSS rule carries a colour of its own', () => {
  const named = /(?<![-\w])(white|black|red|green|blue|gray|grey|silver|orange|yellow|purple|pink|brown|navy|teal)(?![-\w])/i;
  const offenders = [];
  for (const [body] of rest.matchAll(/\{[^{}]*\}/g)) {
    for (const decl of body.slice(1, -1).split(';')) {
      const value = decl.slice(decl.indexOf(':') + 1);
      if (/#[0-9a-f]{3,8}\b/i.test(value) || /\b(rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(/i.test(value) || named.test(value)) offenders.push(decl);
    }
  }
  assert.deepEqual(offenders, []);
  const defined = new Set([...block.matchAll(/(--[\w-]+):/g)].map(m => m[1]));
  const tokenRefs = [...rest.matchAll(/var\((--(?:color|current|radius|space|layout|wire|control|node)-[\w-]+)/g)].map(m => m[1]);
  assert.ok(tokenRefs.length > 400);
  assert.deepEqual(tokenRefs.filter(name => !defined.has(name)), []);
});

test('the rendered studio paints with the token values', async () => {
  const {chromium} = require('playwright');
  const browser = await chromium.launch({headless:true, channel:'chrome'});
  try {
    const page = await browser.newPage();
    await page.setContent('<style>' + css + '</style><button>Run</button>');
    const name = /\}body\{background:var\((--[\w-]+)\)/.exec(rest)[1];
    const token = [...designTokens()].find(([n]) => cssName(n) === name)[1].value;
    const hex = token.match(/[0-9a-f]{2}/g).map(x => parseInt(x, 16));
    const actual = await page.locator('body').evaluate(el => el.ownerDocument.defaultView.getComputedStyle(el).backgroundColor);
    assert.equal(actual, 'rgb(' + hex.join(', ') + ')');
  } finally { await browser.close(); }
});

test('each DESIGNSYS-050 4.9 building block maps to one Penpot design and exists once in code', () => {
  const blocks = JSON.parse(read('design-tokens.json')).$extensions['archhub.blocks'];
  assert.deepEqual(Object.keys(blocks), ['AppHeader', 'WorkshopShell', 'AgentPicker', 'DeliveryReceipt', 'PeoplePanel',
    'NodeCard', 'Wire', 'Inspector', 'CanvasComposer', 'RunModeChip', 'HostExecNode', 'ConnectorActionNode']);
  const files = fs.readdirSync(studio).filter(f => f.endsWith('.jsx')).concat(fs.readdirSync(path.join(studio, 'ds')).map(f => 'ds/' + f));
  const sources = files.map(f => [f, read(f)]);
  for (const [name, {code, penpot}] of Object.entries(blocks)) {
    if (penpot) for (const id of Object.values(penpot)) assert.match(id, /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/, name);
    if (!code) continue;
    const where = sources.filter(([, text]) => text.includes(code.symbol)).map(([f]) => f);
    assert.deepEqual(where, [code.file], name + ' is defined once, in ' + code.file);
  }
});
