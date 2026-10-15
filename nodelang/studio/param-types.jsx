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

const PM_TYPES = window.ArchHubTheme.derive((T) => ({
  number:   { label: 'Number',     glyph: '#',  col: T.warn,     wire: false, def: 0 },
  toggle:   { label: 'Toggle',     glyph: '◐',  col: T.purple,   wire: false, def: false },
  text:     { label: 'Text',       glyph: 'T',  col: T.inkSoft,  wire: false, def: '' },
  menu:     { label: 'Menu',       glyph: '≡',  col: T.blue,     wire: false, def: '' },
  colour:   { label: 'Colour',     glyph: '◉',  col: T.ok,       wire: false, def: '#d97757' },
  elements: { label: 'Elements',   glyph: '▭',  col: T.accent,   wire: true },
  view:     { label: 'View',       glyph: '◱',  col: T.cyan,     wire: true },
  dims:     { label: 'Annotation', glyph: '↔',  col: T.ok,       wire: true },
  file:     { label: 'File',       glyph: '⎘',  col: T.ok,       wire: true },
  trigger:  { label: 'Trigger',    glyph: '▶',  col: T.cyan,     wire: true, shape: 'triangle' },
  any:      { label: 'Any',        glyph: '✳',  col: T.inkMuted, wire: true },
}));

// canvas wire-type names → the registry, so a wire on the map and a socket in a panel agree
const PM_WIRE = window.ArchHubTheme.derive((T) => ({
  view: T.cyan, selection: T.cyan, walls: T.accent, doors: T.accent, sheets: T.accent,
  intent: T.purple, prediction: T.purple, trace: T.inkSoft, dims: T.ok, file: T.ok,
  any: T.inkSoft, number: T.warn, text: T.inkSoft, string: T.inkSoft, trigger: T.cyan,
  boolean: T.purple, exec: T.accent,
}));

// the cockpit's older type names → registry names
const PM_ALIAS = { string: 'text', boolean: 'toggle', color: 'colour', event: 'trigger' };
const WATCH_VIEW_OPTIONS = ['table', 'list', 'json', 'image', 'number', 'text', 'chart', 'geometry'];

const pmType = (t) => PM_TYPES[t] || PM_TYPES[PM_ALIAS[t]] || PM_TYPES.any;

const socketShapeOf = (type, list) => {
  const held = pmType(type);
  if (held.shape === 'triangle') return 'triangle';
  if (list) return 'diamond';
  if (type === 'any') return 'any';
  return 'circle';
};

const socketTypeLabel = type => pmType(type).label;

const Socket = ({ type, list, filled, size = 10 }) => {
  const held = pmType(type);
  const c = held.col;
  const shape = socketShapeOf(type, list);
  if (shape === 'triangle') return <span data-socket-shape="triangle" style={{
    width: 0, height: 0, flexShrink: 0, display: 'inline-block',
    borderTop: `${size / 2}px solid transparent`, borderBottom: `${size / 2}px solid transparent`,
    borderLeft: `${size}px solid ${c}`, opacity: filled ? 1 : 0.55,
  }}/>;
  if (shape === 'any') return <span data-socket-shape="any" style={{
    width: size, height: size, flexShrink: 0, display: 'inline-block',
    background: 'transparent', border: `2px dashed ${c}`, borderRadius: '50%',
    boxSizing: 'border-box', opacity: filled ? 1 : 0.75,
  }}/>;
  return <span style={{
    width: size, height: size, flexShrink: 0, display: 'inline-block',
    background: filled ? c : 'transparent', border: `2px solid ${c}`,
    borderRadius: shape === 'diamond' ? 2 : '50%', transform: shape === 'diamond' ? 'rotate(45deg) scale(.86)' : 'none',
  }}/>;
};

// The parameters a connection carries are NOT declared here: the server holds the one list
// (universal_pipeline.WIRE_PARAMETER_SPECS) and serves it with the node library; studio.html and
// cockpit.html set window.WIRE_PARAMS from it. The run applies every row it lists.

Object.assign(window, { PM_TYPES, PM_WIRE, PM_ALIAS, WATCH_VIEW_OPTIONS, pmType, Socket, socketShapeOf, socketTypeLabel });
})();
