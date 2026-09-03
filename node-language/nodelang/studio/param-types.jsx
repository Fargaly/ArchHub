// param-types.jsx — THE parameter type registry. One vocabulary for both graphs.
//
// The cockpit's grand map and the app's session canvas each grew their own idea of what a
// parameter type is (cockpit: string/number/boolean/color/trigger — app: number/toggle/text/
// menu/colour/elements/view/…). Two names for one concept is exactly the drift this project
// keeps paying for, so the registry lives here and both read it: a "toggle" is the same
// colour and the same socket in the cockpit and in Studio, and adding a type adds it to both.
//
// COLOUR encodes the data type. SHAPE encodes cardinality — round = one value, diamond = a
// list. That is Unreal Blueprint's convention, and it means connection legality is readable
// without a legend.
(() => {
const T = window.AH;

const PM_TYPES = {
  number:   { label: 'Number',     glyph: '#',  col: T.warn,     wire: false, def: 0 },
  toggle:   { label: 'Toggle',     glyph: '◐',  col: T.purple,   wire: false, def: false },
  text:     { label: 'Text',       glyph: 'T',  col: T.inkSoft,  wire: false, def: '' },
  menu:     { label: 'Menu',       glyph: '≡',  col: T.blue,     wire: false, def: '' },
  colour:   { label: 'Colour',     glyph: '◉',  col: T.ok,       wire: false, def: '#d97757' },
  elements: { label: 'Elements',   glyph: '▭',  col: T.accent,   wire: true },
  view:     { label: 'View',       glyph: '◱',  col: T.cyan,     wire: true },
  dims:     { label: 'Annotation', glyph: '↔',  col: T.ok,       wire: true },
  file:     { label: 'File',       glyph: '⎘',  col: T.ok,       wire: true },
  any:      { label: 'Any',        glyph: '✳',  col: T.inkMuted, wire: true },
};

// canvas wire-type names → the registry, so a wire on the map and a socket in a panel agree
const PM_WIRE = {
  view: T.cyan, selection: T.cyan, walls: T.accent, doors: T.accent, sheets: T.accent,
  intent: T.purple, prediction: T.purple, trace: T.inkSoft, dims: T.ok, file: T.ok,
  any: T.inkSoft, number: T.warn, text: T.inkSoft, string: T.inkSoft,
  boolean: T.purple, exec: T.accent,
};

// the cockpit's older type names → registry names
const PM_ALIAS = { string: 'text', boolean: 'toggle', color: 'colour', trigger: 'any' };

const pmType = (t) => PM_TYPES[t] || PM_TYPES[PM_ALIAS[t]] || PM_TYPES.any;

const Socket = ({ type, list, filled, size = 9 }) => {
  const c = pmType(type).col;
  return <span style={{
    width: size, height: size, flexShrink: 0, display: 'inline-block',
    background: filled ? c : 'transparent', border: `1.5px solid ${c}`,
    borderRadius: list ? 2 : '50%', transform: list ? 'rotate(45deg)' : 'none',
  }}/>;
};

// The parameters a real graph engine gives a CONNECTION. A wire is a node, so it is governed
// like one — and it must mean the same thing in the cockpit as in Studio, hence: defined once.
//   lacing   — Dynamo list lacing: how two lists of different length are paired.
//   tree     — Grasshopper data-tree ops.
//   condition/on_fail — the rule, and what downstream gets when the rule stops it.
//   throttle — rate limit for a wire fed by a live host.
const WIRE_PARAMS = [
  { k: 'enabled',     label: 'Enabled',   type: 'toggle', def: true,       help: 'Mute the connection without deleting it — downstream sees nothing.' },
  { k: 'lacing',      label: 'Lacing',    type: 'menu',   def: 'shortest', opts: ['shortest', 'longest', 'cross product'], help: 'How two lists of different length are paired.' },
  { k: 'tree',        label: 'Data tree', type: 'menu',   def: 'none',     opts: ['none', 'flatten', 'graft', 'simplify'], help: 'Restructure on the way through — flatten, graft, or simplify.' },
  { k: 'condition',   label: 'Condition', type: 'text',   def: '',         page: 'Rules', help: 'The wire only carries when this holds. Empty means always.' },
  { k: 'on_fail',     label: 'On block',  type: 'menu',   def: 'block',    opts: ['block', 'pass last', 'pass empty'], page: 'Rules', help: 'What downstream receives when the condition blocks or the source errors.' },
  { k: 'throttle_ms', label: 'Throttle',  type: 'number', def: 0,          unit: 'ms', min: 0, max: 2000, step: 50, page: 'Rules', help: 'Minimum gap between deliveries — for a wire fed by a live host.' },
];

Object.assign(window, { PM_TYPES, PM_WIRE, PM_ALIAS, pmType, Socket, WIRE_PARAMS });
})();
