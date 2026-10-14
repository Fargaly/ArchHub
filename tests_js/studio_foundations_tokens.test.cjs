const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));

function tokens(win = {}) {
  const context = vm.createContext({window:win});
  vm.runInContext(read('nodelang/studio/tokens.jsx'), context);
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
  assert.deepEqual(plain(AH.sp), {xs:4, sm:8, md:12, lg:16, xl:24, '2xl':32, '3xl':40, '4xl':48});
  assert.deepEqual(plain(AH.rad), {chip:3, xs:3, control:5, sm:5, node:6, md:6, panel:8, lg:8, dialog:10, xl:10, pill:999});
  assert.deepEqual(plain(AH.shadow), {flat:'none', popover:'0 8px 24px rgba(0,0,0,.45)', dialog:'0 16px 48px rgba(0,0,0,.55)'});
  assert.equal(AH.scrim, 'rgba(0,0,0,.5)');
  assert.deepEqual(plain(AH.selection), {outline:'2px solid #d97757', outlineOffset:2});
  assert.deepEqual(plain(AH.dur), {instant:60, fast:120, med:180, slow:240, reduced:0});
  assert.deepEqual(plain(AH.rowH), {comfortable:32, compact:26, cozy:22});
  assert.deepEqual(plain(AH.icon), {ui:{size:16, stroke:1.5, box:20}, category:{size:12, box:20}});
  assert.deepEqual(plain(AH.fs), {
    display:{sz:24, ln:30, wt:600, fam:'sans'},
    title:{sz:16, ln:22, wt:600, fam:'sans'},
    body:{sz:14, ln:20, wt:400, fam:'sans'},
    bodySm:{sz:13, ln:18, wt:400, fam:'sans'},
    bodySmStrong:{sz:13, ln:18, wt:500, fam:'sans'},
    caption:{sz:12, ln:16, wt:400, fam:'sans'},
    label:{sz:11, ln:14, wt:500, fam:'sans', letter:'.04em'},
    data:{sz:12, ln:16, wt:400, fam:'mono'},
    dataSm:{sz:11, ln:14, wt:400, fam:'mono'},
  });
  assert.equal(AH.serif, AH.sans, 'product UI serif alias resolves to Inter');
  assert.match(AH.marketingSerif, /Instrument Serif/, 'marketing keeps the display serif');
});

test('DS-FOUNDATIONS B1 studio text has no numeric font size below 11px', () => {
  const source = read('nodelang/studio/studio-lm.jsx');
  const workshop = read('nodelang/studio/studio-workshop.jsx');
  const under11 = /fontSize:\s*(?:[0-9](?:\.[0-9]+)?|10(?:\.[0-9]+)?)\b|font-size:\s*(?:[0-9](?:\.[0-9]+)?|10(?:\.[0-9]+)?)px/;
  assert.doesNotMatch(source, under11);
  assert.doesNotMatch(workshop, under11);
});

test('DS-FOUNDATIONS B2 selection outline derives from the live accent', () => {
  const win = {};
  const AH = tokens(win);
  assert.equal(AH.selection.outline, '2px solid #d97757');
  const next = Object.fromEntries(win.ArchHubTheme.keys.map(key => [key, '#111111']));
  next.accent = '#55aaee';
  assert.equal(win.ArchHubTheme.apply(next), true);
  assert.equal(AH.selection.outline, '2px solid #55aaee');
});

test('DS-FOUNDATIONS Ping 2 reduced motion changes all token transition durations', () => {
  const listeners = new Set();
  const media = {matches:true, media:'(prefers-reduced-motion: reduce)',
    addEventListener(type, listener) { if (type === 'change') listeners.add(listener); },
    removeEventListener(type, listener) { if (type === 'change') listeners.delete(listener); }};
  const win = {matchMedia:query => query === '(prefers-reduced-motion: reduce)' ? media : {matches:false, addEventListener(){}, removeEventListener(){}}};
  const AH = tokens(win);
  assert.deepEqual(plain(AH.dur), {instant:0, fast:0, med:0, slow:0, reduced:0});
  media.matches = false;
  for (const listener of listeners) listener({matches:false});
  assert.deepEqual(plain(AH.dur), {instant:60, fast:120, med:180, slow:240, reduced:0});
});

test('DS-FOUNDATIONS shared controls consume tokens and do not alpha-disable', () => {
  const source = read('nodelang/studio/studio-lm.jsx');
  const workshop = read('nodelang/studio/studio-workshop.jsx');
  const between = (from, to) => source.slice(source.indexOf(from), source.indexOf(to, source.indexOf(from)));
  const betweenWorkshop = (from, to) => workshop.slice(workshop.indexOf(from), workshop.indexOf(to, workshop.indexOf(from)));
  const betweenAfter = (anchor, from, to) => {
    const base = source.indexOf(anchor);
    const start = source.indexOf(from, base);
    return source.slice(start, source.indexOf(to, start));
  };
  const shared = [
    between('const smallBtn =', 'const HoverBtn ='),
    between('const toolBtn =', '// ─── floating composer'),
    between('const LibCatBtn =', '// ──────────────────────── NODE RAIL'),
    between('const SettingsGenerationControl =', '// ── Models:'),
    between('const pickerGroupLabel =', 'const DISCOVERY_DEADLINE_MS'),
    betweenAfter('const ModelPicker =', '  const note =', '  const onFill ='),
    between('const dCode =', 'const DOC_INDEX ='),
    between('const ApplicationUpdateNotice =', 'window.StudioLM ='),
    betweenWorkshop('const Lbl =', 'const agentOf ='),
  ].join('\n');
  assert.doesNotMatch(shared, /fontSize:\s*(?:9|9\.5|10|10\.5|11\.5|12\.5|13\.5|15|18)\b/);
  assert.doesNotMatch(shared, /borderRadius:\s*(?:4|6|7|9|12|14|16)\b/);
  assert.doesNotMatch(shared, /opacity:\s*[^,}\n]+/);
  for (const required of ['LM.fs.bodySm.sz', 'LM.fs.caption.sz', 'LM.fs.label.sz', 'LM.sp.md', 'LM.rad.control', 'LM.icon.ui.box']) {
    assert.match(shared, new RegExp(required.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
});

const studioDir = path.join(root, 'nodelang', 'studio');
const studioTokenSource = read('nodelang/studio/tokens.jsx');
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

test('DS-FOUNDATIONS P9 BABOOM summary and pre do not use font sizes below 11px', () => {
  const source = read('nodelang/studio/studio-lm.jsx');
  const start = source.indexOf('const BaboomToolSteps =');
  const end = source.indexOf('// The wired pipeline', start);
  assert.ok(start > 0 && end > start, 'BABOOM step renderer exists near chat components');
  const body = source.slice(start, end);
  const failures = [];
  for (const tag of ['summary', 'pre']) {
    let search = 0;
    while (true) {
      const tagStart = body.indexOf(`<${tag}`, search);
      if (tagStart === -1) break;
      const styleStart = body.indexOf('style={{', tagStart);
      const tagEnd = body.indexOf('>', tagStart);
      if (styleStart !== -1 && tagEnd !== -1 && styleStart < tagEnd) {
        const objectStart = styleStart + 'style={'.length;
        const objectEnd = findMatchingBrace(body, objectStart);
        const size = objectEnd === -1 ? null : resolveFontSize(body.slice(objectStart + 1, objectEnd));
        if (size != null && size < 11) failures.push(`${tag} fontSize ${size}`);
      }
      search = tagEnd === -1 ? tagStart + 1 : tagEnd + 1;
    }
  }
  assert.deepEqual(failures, []);
});
