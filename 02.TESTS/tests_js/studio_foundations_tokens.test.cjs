const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..', '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));

function tokens(win = {}) {
  const context = vm.createContext({window:win});
  vm.runInContext(read('01.APP/nodelang/studio/tokens.jsx'), context);
  return context.window.AH;
}

test('DS-FOUNDATIONS §3 tokens are the single product source', () => {
  const AH = tokens();
  assert.deepEqual({
    bgDeep:AH.bgDeep, bg:AH.bg, bgCanvas:AH.bgCanvas, bgPanel:AH.bgPanel,
    bgSoft:AH.bgSoft, bgRaised:AH.bgRaised, bgHover:AH.bgHover,
    line:AH.line, lineSoft:AH.lineSoft, ink:AH.ink, inkSoft:AH.inkSoft,
    inkMuted:AH.inkMuted, accent:AH.accent, accentSoft:AH.accentSoft,
    accentHi:AH.accentHi, accentPress:AH.accentPress, onFill:AH.onFill,
    ok:AH.ok, warn:AH.warn, err:AH.err, cyan:AH.cyan, purple:AH.purple, blue:AH.blue,
    l_bg:AH.l_bg, l_bgSoft:AH.l_bgSoft, l_bgPanel:AH.l_bgPanel,
    l_ink:AH.l_ink, l_inkSoft:AH.l_inkSoft, l_inkMuted:AH.l_inkMuted,
    l_line:AH.l_line, l_accent:AH.l_accent,
  }, {
    bgDeep:'#0a0a0d', bg:'#0e0e11', bgCanvas:'#101015', bgPanel:'#15151a',
    bgSoft:'#1c1c23', bgRaised:'#1d1d22', bgHover:'#22222a',
    line:'#26262e', lineSoft:'#1e1e24', ink:'#ece8e0', inkSoft:'#9b938a',
    inkMuted:'#8b837a', accent:'#d97757', accentSoft:'#3a2018',
    accentHi:'#e8896a', accentPress:'#a04832', onFill:'#180f08',
    ok:'#7ec18e', warn:'#e5b25a', err:'#e6705f', cyan:'#5fb3b3', purple:'#a98cd6', blue:'#7898d6',
    l_bg:'#f7f4ee', l_bgSoft:'#efeae0', l_bgPanel:'#fbf9f4',
    l_ink:'#1a1612', l_inkSoft:'#6b6256', l_inkMuted:'#9a9183',
    l_line:'#e3ddd0', l_accent:'#c96442',
  });
  assert.deepEqual(plain(AH.rowH), {comfortable:32, compact:26, cozy:22});
  assert.match(AH.sans,/Inter/);
  assert.match(AH.serif,/Instrument Serif/);
});

test('DS-FOUNDATIONS current typography scale permits 9px caps and no smaller text', () => {
  const files = JSON.parse(read('01.APP/nodelang/studio/compiled/manifest.json')).files;
  const source = files.map(file => read('01.APP/nodelang/studio/' + file.source)).join('\n');
  const AH=tokens();
  assert.equal(AH.fs.cap.sz,9);assert.equal(AH.fs.monoSm.sz,11);assert.equal(AH.fs.bodySm.sz,13);
  const under9 = /fontSize:\s*(?:[0-8](?:\.[0-9]+)?)\b|font-size:\s*(?:[0-8](?:\.[0-9]+)?)px/;
  assert.doesNotMatch(source, under9);

});

test('DS-FOUNDATIONS B2 current controls receive the live theme accent', () => {
  const win = {};
  const AH = tokens(win);
  assert.equal(AH.accent, '#d97757');
  const next = Object.fromEntries(win.ArchHubTheme.keys.map(key => [key, '#111111']));
  next.accent = '#55aaee';
  assert.equal(win.ArchHubTheme.apply(next), true);
  assert.equal(AH.accent, '#55aaee');
});

test('DS-FOUNDATIONS reduced motion disables computed transitions and animations',async()=>{
 const {chromium}=require('playwright');const browser=await chromium.launch({headless:true,channel:'chrome'});
 try{const page=await browser.newPage();await page.emulateMedia({reducedMotion:'reduce'});
  await page.setContent('<style>'+read('01.APP/nodelang/studio/style.css')+'</style><div id="motion" style="transition:opacity 2s;animation:spin 2s infinite">Motion</div>');
  const actual=await page.locator('#motion').evaluate(el=>({transition:el.ownerDocument.defaultView.getComputedStyle(el).transitionProperty,animation:el.ownerDocument.defaultView.getComputedStyle(el).animationName}));
  assert.deepEqual(actual,{transition:'none',animation:'none'});
 }finally{await browser.close();}
});



const studioDir = path.join(root, '01.APP/nodelang', 'studio');
const studioTokenSource = read('01.APP/nodelang/studio/tokens.jsx');
const studioFontSizes = new Map(
  [...studioTokenSource.matchAll(/([A-Za-z][A-Za-z0-9]*):\{sz:(\d+(?:\.\d+)?)/g)]
    .map(match => [match[1], Number(match[2])])
);

function lineOf(source, index) {
  return source.slice(0, index).split(/\r?\n/).length;
}

function findMatchingBrace(source, start) {
  let depth = 0;
  let quote = '';
  let escaped = false;
  for (let index = start; index < source.length; index += 1) {
    const ch = source[index];
    if (quote) {
      if (escaped) { escaped = false; continue; }
      if (ch === '\\') { escaped = true; continue; }
      if (ch === quote) quote = '';
      continue;
    }
    if (ch === '"' || ch === "'" || ch === '`') { quote = ch; continue; }
    if (ch === '{') depth += 1;
    else if (ch === '}') {
      depth -= 1;
      if (depth === 0) return index;
    }
  }
  return -1;
}

function styleObjects(source) {
  const objects = [];
  let search = 0;
  while (true) {
    const attr = source.indexOf('style={{', search);
    if (attr === -1) break;
    const objectStart = attr + 'style={'.length;
    const objectEnd = findMatchingBrace(source, objectStart);
    if (objectEnd === -1) break;
    objects.push({body: source.slice(objectStart + 1, objectEnd), index: attr});
    search = objectEnd + 1;
  }
  return objects;
}

function resolveFontSize(style) {
  const token = style.match(/fontSize\s*:\s*[A-Z][A-Za-z0-9_]*\.fs\.([A-Za-z0-9]+)\.sz/);
  if (token) return studioFontSizes.get(token[1]);
  const raw = style.match(/fontSize\s*:\s*(\d+(?:\.\d+)?)/);
  return raw ? Number(raw[1]) : null;
}

function hasMutedInk(style) {
  return /color\s*:[^,}]*\b[A-Z][A-Za-z0-9_]*\.inkMuted\b/.test(style);
}

test('DS-FOUNDATIONS P9 text below 13px does not use inkMuted', () => {
  const failures = [];
  const files = fs.readdirSync(studioDir)
    .filter(name => name.endsWith('.jsx'))
    .filter(name => name !== 'tokens.jsx')
    .map(name => path.join(studioDir, name));
  files.push(path.join(studioDir, 'ds', 'index.jsx'));
  for (const file of files) {
    const source = fs.readFileSync(file, 'utf8');
    for (const style of styleObjects(source)) {
      const size = resolveFontSize(style.body);
      if (size != null && size < 13 && hasMutedInk(style.body)) {
        failures.push(`${path.relative(root, file)}:${lineOf(source, style.index)} fontSize ${size} with inkMuted`);
      }
    }
  }
  assert.deepEqual(failures, []);
});



test('DS-FOUNDATIONS shared buttons consume tokens and preserve native disabled state',()=>{
 const designSystem=read('01.APP/nodelang/studio/ds/index.jsx');
 const sharedButton=designSystem.slice(designSystem.indexOf('  const button ='),designSystem.indexOf('  function Toggle('));
 assert.ok(sharedButton.length>0);
 assert.match(designSystem,/const A = window\.AH/);
 assert.match(sharedButton,/A\.rad\?\.sm/);assert.match(sharedButton,/A\.sans/);
 assert.match(sharedButton,/const off = !!\(disabled \|\| dis\)/);assert.match(sharedButton,/disabled=\{off\}/);
});
