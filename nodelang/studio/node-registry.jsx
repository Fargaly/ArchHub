// node-registry.jsx - THE node registry. One definition, every surface reads it.
//
// CAT (what kind of work a node does) and WIRE (what a signal carries) used to live inside
// studio-lm.jsx. Two copies of a registry is the defect
// this project has fixed three times (design DECISIONS.md "One node registry"). Load this file
// before any surface that draws a node. Studio keeps live re-theming: the colours are derived
// through ArchHubTheme when it exists, and built once from window.AH when it does not.
//
// Consumers: studio-lm.jsx (canvas, node library, minimap, wires).

(() => {

const derive = (window.ArchHubTheme && window.ArchHubTheme.derive) || ((build) => build(window.AH));

// COLOUR IS THE CATEGORY - the first thing read on a card, before the title.
const AH_CAT = derive((LM) => ({
  wire:      { col:LM.inkSoft, icon:'\u21c4', label:'CONNECTION' },
  host:      { col:LM.cyan,    icon:'\u232c', label:'HOST',      role:'Connected app' },
  read:      { col:LM.cyan,    icon:'\u25c7', label:'READ',      role:'Pulls data from a host' },
  filter:    { col:LM.inkSoft, icon:'\u2317', label:'FILTER',    role:'Filters a stream' },
  transform: { col:LM.warn,    icon:'\u232d', label:'TRANSFORM', role:'Modifies elements' },
  annotate:  { col:LM.accent,  icon:'\u270e', label:'ANNOTATE',  role:'Adds dims / tags / text' },
  compose:   { col:LM.accent,  icon:'\u25a4', label:'COMPOSE',   role:'Builds schedules / sheets' },
  logic:     { col:LM.purple,  icon:'\u2325', label:'LOGIC',     role:'Branch / loop / switch' },
  ai:        { col:LM.purple,  icon:'\u2726', label:'AI',        role:'LLM reasoning, vision, match' },
  output:    { col:LM.ok,      icon:'\u2197', label:'OUTPUT',    role:'Publishes / saves / notifies' },
  workshop:  { col:LM.purple,  icon:'◎', label:'WORKSHOP',  role:'Agents, Workshop and independent review' },
}));

// COLOUR IS THE SIGNAL - two ports of the same colour can be wired together.
const AH_WIRE = derive((LM) => ({
  view:LM.cyan, selection:LM.cyan, walls:LM.accent, doors:LM.accent, sheets:LM.accent,
  intent:LM.purple, prediction:LM.purple, trace:LM.inkSoft, dims:LM.ok, file:LM.ok,
  table:LM.purple, any:LM.inkSoft,
}));

// The insertable nodes are NOT typed here: the graph serves the one node library
// (GET /api/universal/node-library, library_engines.library_catalogue) and studio.html sets
// window.AH_LIBRARY from it before Studio mounts. A second copy here drifted from the engines.

Object.assign(window, { AH_CAT, AH_WIRE });

})();
