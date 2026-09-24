// node-registry.jsx - THE node registry. One definition, every surface reads it.
//
// CAT (what kind of work a node does), WIRE (what a signal carries) and the library of
// insertable nodes used to live inside studio-lm.jsx. Two copies of a registry is the defect
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

// The insertable nodes, grouped by category - Grasshopper / Dynamo style. Every row names
// the engine that runs it; the node itself says when its host is closed.
const AH_LIBRARY = [
  { cat:'host', items:[
    // Every host the founder works with. Each row is a real wire; the node
    // itself says when its host is closed, so nothing here is a promise.
    { id:'h_revit',   title:'Revit',    sub:'live sessions on this machine', engine:'revit.sessions' },
    { id:'h_autocad', title:'AutoCAD',  sub:'line work from the live drawing', engine:'cad.host_lines' },
    { id:'h_max',     title:'3ds Max',  sub:'MAXScript / Python in the open scene', engine:'max.exec', params:{ code:'' } },
    { id:'h_rhino',   title:'Rhino',    sub:'RhinoPython in the open model', engine:'rhino.exec', params:{ code:'' } },
    { id:'h_blender', title:'Blender',  sub:'Python in the open scene', engine:'blender.exec', params:{ code:'' } },
    { id:'h_excel',   title:'Excel',    sub:'open workbooks and their sheets', engine:'office.read', params:{ operation:'excel.list_workbooks' } },
    { id:'h_word',    title:'Word',     sub:'open documents and their paragraphs', engine:'office.read', params:{ operation:'word.list_documents' } },
    { id:'h_ppt',     title:'PowerPoint', sub:'open decks and their slides', engine:'office.read', params:{ operation:'powerpoint.list_presentations' } },
    { id:'h_outlook', title:'Outlook',  sub:'the inbox, newest first', engine:'outlook.inbox', params:{ count:20 } },
    { id:'h_notion',  title:'Notion',   sub:'search your workspace', engine:'notion.search', params:{ query:'' } },
    { id:'h_dropbox', title:'Dropbox',  sub:'files in your Dropbox folder', engine:'dropbox.list', params:{ path:'' } },
    { id:'h_speckle', title:'Speckle',  sub:'commit the wired rows to a branch', engine:'library.push_speckle', params:{ project:'', branch:'archhub/main', message:'ArchHub push' } },
  ]},
  { cat:'read', items:[
    { id:'r_walls',     title:'list_walls',    sub:'pull walls from active view', engine:'revit.read', params:{ operation:'revit.list_walls' } },
    { id:'r_doors',     title:'list_doors',    sub:'pull doors + swings + marks', engine:'revit.read', params:{ operation:'revit.list_doors' } },
    { id:'r_windows',   title:'list_windows',  sub:'pull windows + types', engine:'revit.read', params:{ operation:'revit.list_windows' } },
    { id:'r_sheets',    title:'list_sheets',   sub:'enumerate sheets in set', engine:'revit.read', params:{ operation:'revit.list_sheets' } },
    { id:'r_views',     title:'list_views',    sub:'plans, sections, schedules', engine:'revit.read', params:{ operation:'revit.list_views' } },
    { id:'r_levels',    title:'list_levels',   sub:'levels + elevations', engine:'revit.read', params:{ operation:'revit.list_levels' } },
    { id:'r_selection', title:'get_selection', sub:'whatever is selected in host', engine:'revit.read', params:{ operation:'revit.get_selection' } },
    { id:'r_warnings',  title:'list_warnings', sub:'host warnings \u00b7 by severity', engine:'revit.read', params:{ operation:'revit.list_warnings' } },
    { id:'r_xl_sheets', title:'excel worksheets', sub:'sheets of the workbook in front', engine:'office.read', params:{ operation:'excel.list_worksheets' } },
    { id:'r_doc_paras', title:'word paragraphs', sub:'paragraphs of the document in front', engine:'office.read', params:{ operation:'word.list_paragraphs' } },
    { id:'r_ppt_slides', title:'powerpoint slides', sub:'slides of the deck in front', engine:'office.read', params:{ operation:'powerpoint.list_slides' } },
  ]},
  { cat:'filter', items:[
    { id:'f_type',  title:'where type',      sub:'by family/type' , engine:'library.filter_field'},
    { id:'f_cat',   title:'where category',  sub:'by Revit category' , engine:'library.filter_field'},
    { id:'f_level', title:'where level',     sub:'by level reference' , engine:'library.filter_field'},
    { id:'f_param', title:'where parameter', sub:'predicate on a parameter' , engine:'library.filter_compare'},
    { id:'f_pred',  title:'where custom',    sub:'arbitrary JS predicate' , engine:'library.filter_rule'},
  ]},
  { cat:'transform', items:[
    { id:'t_setp',  title:'set parameter',   sub:'mutates parameter values' , engine:'library.set_field'},
    { id:'t_move',  title:'move',            sub:'translation' , engine:'library.move'},
    { id:'t_rot',   title:'rotate',          sub:'rotation' , engine:'library.rotate'},
    { id:'t_scale', title:'scale',           sub:'uniform / per-axis' , engine:'library.scale'},
    { id:'t_group', title:'group by',        sub:'key \u2192 list' , engine:'library.group_by'},
    { id:'t_sort',  title:'sort by',         sub:'asc / desc on key' , engine:'library.sort_by'},
  ]},
  { cat:'annotate', items:[
    { id:'a_dims',  title:'create_dimensions', sub:'aligned, parallel, baseline' , engine:'library.dimensions'},
    { id:'a_tags',  title:'place_tags',         sub:'tag every untagged element of a category' , engine:'library.place_tags'},
    { id:'a_text',  title:'add_text',           sub:'text note \u00b7 positioned' , engine:'library.add_text'},
    { id:'a_rooms', title:'tag_rooms',          sub:'tag every untagged room in the view' , engine:'library.tag_rooms'},
  ]},
  { cat:'compose', items:[
    { id:'c_sched', title:'build_schedule',  sub:'table from a stream' , engine:'library.build_schedule'},
    { id:'c_sheet', title:'place_on_sheet',  sub:'named views onto a sheet' , engine:'library.place_on_sheet'},
    { id:'c_legend',title:'make_legend',     sub:'symbol legend block' , engine:'library.make_legend'},
  ]},
  { cat:'logic', items:[
    { id:'l_if',     title:'if',     sub:'predicate \u2192 true / false branches' , engine:'library.if'},
    { id:'l_switch', title:'switch', sub:'multi-branch on a key' , engine:'library.switch'},
    { id:'l_loop',   title:'loop',   sub:'iterate over a list' , engine:'library.loop'},
    { id:'l_merge',  title:'merge',  sub:'concat / dedupe streams' , engine:'library.merge'},
  ]},
  { cat:'ai', items:[
    { id:'i_think', title:'think',  sub:'reason with the picked model' , engine:'library.think'},
    { id:'i_vis',   title:'vision', sub:'read a sketch / screenshot with the picked model' , engine:'library.vision'},
    { id:'i_match', title:'match_skill', sub:'best saved skill for an intent' , engine:'library.match_skill'},
    { id:'i_embed', title:'embed',  sub:'similar facts from the brain' , engine:'library.embed'},
  ]},
  { cat:'workshop', items:[
    // Placing one runs nothing: these act only inside a Workshop workflow the
    // user has approved (workshop_workflow.py); the canvas Run refuses them.
    { id:'w_workshop', title:'Workshop',           sub:'this conversation; routes wired agents into it', engine:'workshop.conversation', params:{ conversation:'' } },
    { id:'w_agent',    title:'Agent session',      sub:'one live native session through Session Link', engine:'agent.session', params:{ agent:'', message:'' } },
    { id:'w_review',   title:'Independent review', sub:'a different agent reviews the wired artifact', engine:'workshop.review', params:{ reviewer:'' } },
  ]},
  { cat:'output', items:[
    { id:'o_skill', title:'save_skill',     sub:'template this run' , engine:'library.save_skill'},
    { id:'o_pdf',   title:'publish_pdf',    sub:'sheets \u2192 PDF files via the live Revit' , engine:'library.publish_pdf'},
    { id:'o_spk',   title:'push_speckle',   sub:'commit the wired rows to a branch' , engine:'library.push_speckle'},
    { id:'o_email', title:'draft_email',    sub:'draft in Outlook \u00b7 you send' , engine:'library.draft_email'},
    { id:'o_notify',title:'notify',         sub:'desktop notification' , engine:'library.notify'},
  ]},
];

// Counted, never typed.
const AH_LIB_COUNT = AH_LIBRARY.reduce((n, g) => n + g.items.length, 0);
const AH_CAT_COUNT = AH_LIBRARY.reduce((m, g) => { m[g.cat] = g.items.length; return m; }, {});

Object.assign(window, { AH_CAT, AH_WIRE, AH_LIBRARY, AH_LIB_COUNT, AH_CAT_COUNT });

})();
