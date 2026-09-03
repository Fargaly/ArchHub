// tokens.jsx — ARCHHUB single source of truth for design tokens.
// ────────────────────────────────────────────────────────────────────────
// Every surface (Brand Book, Studio canvas, Brain, Self-Heal, Website) derives
// its local palette from window.AH. DO NOT hardcode surface hexes anywhere else.
// Change a value here once and all five apps update. This file replaces the old
// per-file copies (BB / LM / DL / ST / C) that were hand-synced and drifting.
//
// In the Studio app this file is loaded by index.html BEFORE the bundle
// (jsx-boot.js → studio-lm.compiled.js), so `window.AH` exists before
// studio-lm.jsx's IIFE runs — THEMES.forge derives FROM window.AH (no
// hand-copied hexes). It is the byte-for-byte mirror of the design handoff
// source of truth at _handoff/archhub/project/tokens.jsx.
//
// Two key conventions exist downstream:
//   • long keys  (bgPanel, bgSoft, bgHover …) → BB, LM, DL, ST, critique-C
//   • short keys (panel, soft, hover, deep)   → brain-model C, self-heal C
// Both map from the SAME canonical values below.

window.AH = {
  // ── surfaces (dark canonical) ──
  bgDeep:  '#0a0a0d',
  bg:      '#0e0e11',
  bgPanel: '#15151a',
  bgSoft:  '#1c1c23',
  bgHover: '#22222a',
  bgRaised:'#1d1d22',
  bgInk:   '#18181e',
  bgCanvas:'#101015',
  // ── ink ──
  ink:      '#ece8e0',
  inkSoft:  '#9b938a',
  inkMuted: '#5e574f',
  inkDim:   '#3a3530',
  // ── lines ──
  line:     '#26262e',
  lineSoft: '#1e1e24',
  lineHair: '#1a1a20',
  // ── accents ──
  accent:    '#d97757',  // terracotta — the only emotional accent
  accentSoft:'#3a2018',
  accentDim: '#2a1812',
  accentHi:  '#e8896a',
  accentPress:'#a04832',
  // ── functional ──
  ok:    '#7ec18e',
  warn:  '#e5b25a',
  err:   '#e6705f',
  cyan:  '#5fb3b3',
  purple:'#a98cd6',
  blue:  '#7898d6',
  // ── light mirror (side-by-side demos) ──
  l_bg:      '#f7f4ee',
  l_bgPanel: '#fbf9f4',
  l_bgSoft:  '#efeae0',
  l_ink:     '#1a1612',
  l_inkSoft: '#6b6256',
  l_inkMuted:'#9a9183',
  l_line:    '#e3ddd0',
  l_accent:  '#c96442',
  // ── type ──
  serif: "'Instrument Serif', Georgia, serif",
  sans:  "'Inter', system-ui, sans-serif",
  mono:  "'JetBrains Mono', ui-monospace, monospace",
  arch:  "'Architects Daughter', 'Comic Sans MS', cursive",
  // ── scales ──
  sp:  { xs:4, sm:8, md:12, lg:16, xl:24, '2xl':32, '3xl':40, '4xl':48, '5xl':56, '6xl':72, '7xl':96 },
  rad: { xs:3, sm:5, md:6, lg:8, xl:10, pill:999 },
  fs: {
    d0:  { sz:104, ln:0.90, fam:'serif', use:'Web marketing hero — archhub.app only' },
    d1:  { sz:88,  ln:0.92, fam:'serif', use:'Cover · product hero' },
    d2:  { sz:56,  ln:0.95, fam:'serif', use:'Section openers' },
    h1:  { sz:40,  ln:1.05, fam:'serif', use:'Page heading' },
    h2:  { sz:24,  ln:1.15, fam:'serif', use:'Italic lede · pull-quote' },
    h3:  { sz:21,  ln:1.20, fam:'serif', use:'In-product section title' },
    bodyLg: { sz:16, ln:1.55, fam:'sans', use:'Body large · composer' },
    body:   { sz:14, ln:1.55, fam:'sans', use:'Body · rows · descriptions' },
    bodySm: { sz:13, ln:1.50, fam:'sans', use:'Body small · dense lists' },
    mono:   { sz:12, ln:1.50, fam:'mono', use:'Data · params · prices · tokens' },
    monoSm: { sz:11, ln:1.55, fam:'mono', use:'Mono small · captions · timestamps' },
    cap:    { sz:9,  ln:1.40, fam:'mono', use:'All-caps section labels · tags' },
  },
  dur:  { instant:60, fast:120, med:180, slow:240 },
  rowH: { comfortable:32, compact:26, cozy:22 },
};

// Convenience: short-key projection (brain / self-heal style) so those files can
// do `const C = window.AHShort` if they prefer. Kept in sync automatically.
window.AHShort = (() => {
  const A = window.AH;
  return {
    bg:A.bg, panel:A.bgPanel, soft:A.bgSoft, deep:A.bgDeep, hover:A.bgHover,
    raised:A.bgRaised, ink:A.ink, inkSoft:A.inkSoft, inkMuted:A.inkMuted, inkDim:A.inkDim,
    line:A.line, lineSoft:A.lineSoft, lineHair:A.lineHair,
    accent:A.accent, accentSoft:A.accentSoft, accentDim:A.accentDim, accentHi:A.accentHi,
    ok:A.ok, warn:A.warn, err:A.err, cyan:A.cyan, purple:A.purple, blue:A.blue,
    sp:A.sp, rad:A.rad,
  };
})();
