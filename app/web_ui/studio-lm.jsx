// studio-lm.jsx — Studio v2 · node canvas with movable typed nodes
//
// Real fixes:
//   • Nodes are DRAGGABLE — grab any title bar and move it
//   • Canvas pan/zoom WORK — pan empty canvas, zoom toolbar passes through
//   • ONE gear (workspace header). Sidebar has no settings entry.
//   • Real AEC NODE LIBRARY — categorized like Grasshopper / Dynamo / Comfy:
//     Hosts · Read · Filter · Transform · Annotate · Compose · Logic · AI · Output
//     Each category has a color, an icon, and body logic specific to its type.

(() => {

const LM = {
  bg:'#0e0e11', bgPanel:'#15151a', bgSoft:'#1c1c23', bgHover:'#22222a',
  bgDeep:'#0a0a0d', bgCanvas:'#101015', bgInk:'#18181e',
  ink:'#ece8e0', inkSoft:'#9b938a', inkMuted:'#5e574f', inkDim:'#3a3530',
  line:'#26262e', lineSoft:'#1e1e24', lineHair:'#1a1a20',
  accent:'#d97757', accentSoft:'#3a2018', accentDim:'#2a1812', accentHi:'#e8896a',
  ok:'#7ec18e', warn:'#e5b25a', err:'#e6705f', cyan:'#5fb3b3', purple:'#a98cd6', blue:'#7898d6',
  serif:"'Instrument Serif', Georgia, serif",
  sans:"'Inter', system-ui, sans-serif",
  mono:"'JetBrains Mono', ui-monospace, monospace",
};

// ─── Categories — each is a node type with color + icon + role ───
const CAT = {
  host:      { col:LM.cyan,    icon:'⌬', label:'HOST',      role:'Connected app' },
  read:      { col:LM.cyan,    icon:'◇', label:'READ',      role:'Pulls data from a host' },
  filter:    { col:LM.inkSoft, icon:'⌗', label:'FILTER',    role:'Filters a stream' },
  transform: { col:LM.warn,    icon:'⌭', label:'TRANSFORM', role:'Modifies elements' },
  annotate:  { col:LM.accent,  icon:'✎', label:'ANNOTATE',  role:'Adds dims / tags / text' },
  compose:   { col:LM.accent,  icon:'▤', label:'COMPOSE',   role:'Builds schedules / sheets' },
  logic:     { col:LM.purple,  icon:'⌥', label:'LOGIC',     role:'Branch / loop / switch' },
  ai:        { col:LM.purple,  icon:'✦', label:'AI',        role:'LLM reasoning, vision, match' },
  output:    { col:LM.ok,      icon:'↗', label:'OUTPUT',    role:'Publishes / saves / notifies' },
  trigger:   { col:LM.warn,    icon:'⚡', label:'TRIGGER',   role:'Event-sourced graph entry' },
  connector_op: { col:LM.cyan, icon:'⚙', label:'CONNECTOR', role:'A live host operation' },
  custom:    { col:LM.blue,    icon:'⊕', label:'CUSTOM',    role:'AI-minted custom node' },
};

// ─── Pipeline super-sections — the library's organising logic.
// Founder demand 2026-05-17: don't dump 10 flat categories; group them
// by WHERE a node sits in a graph's left-to-right flow. SOURCES bring
// data in, SHAPE processes it, AI reasons, SEND publishes. Each abstract
// CAT key maps into exactly one pipeline stage.
const PIPELINE = [
  { id:'sources', label:'SOURCES', hint:'bring data in',
    cats:['host', 'read', 'trigger'] },
  { id:'shape',   label:'SHAPE',   hint:'filter · modify',
    cats:['filter', 'transform', 'logic', 'annotate', 'compose'] },
  { id:'ai',      label:'AI',      hint:'reason · match',
    cats:['ai'] },
  { id:'send',    label:'SEND',    hint:'publish · save',
    cats:['output'] },
];

const WIRE = {
  view:LM.cyan, selection:LM.cyan, walls:LM.accent, doors:LM.accent, sheets:LM.accent,
  intent:LM.purple, prediction:LM.purple, trace:LM.inkSoft, dims:LM.ok, file:LM.ok, any:LM.inkSoft,
  event:LM.warn, completion:LM.purple,
};

// ──────────────────────── DATA ────────────────────────
// Founder demand #15 + #17: wrap all top-level arrays in window globals so
// index.html's bridge hydrator can splice() real data over the demo fallback.
// The const bindings below point at the SAME array instance every time —
// spliceInto() mutates contents, never replaces references.
// Founder direction 2026-05-14: NO fake demo sessions. Real sessions
// hydrate from bridge.get_sessions() via index.html's spliceInto().
// Empty array = brand-new install shows Home empty state until the
// user creates a session.
const LM_SESSIONS = window.__archhub_LM_SESSIONS = window.__archhub_LM_SESSIONS || [];

const LM_HOSTS = window.__archhub_LM_HOSTS = window.__archhub_LM_HOSTS || [
  { id:'r25', name:'Revit 2025',  port:'48884', state:'connected', file:'Tower-A_central.rvt · 47 walls' },
  { id:'r24', name:'Revit 2024',  port:'48886', state:'connected', file:'AssetA_lib.rvt' },
  { id:'bld', name:'Blender 5.1', port:'48890', state:'syncing',   file:'sketch.blend · awaiting handshake' },
  { id:'rhi', name:'Rhino 8',     port:'48892', state:'connected', file:'panels.3dm · 8 layers' },
  { id:'acd', name:'AutoCAD 2026',port:null,    state:'off',       file:'—' },
  { id:'spk', name:'Speckle',     port:'cloud', state:'connected', file:'tower-a/main · 14 commits' },
];

const LM_HOST_META = {
  revit:{name:'Revit',col:LM.cyan},     blender:{name:'Blender',col:LM.accent},
  speckle:{name:'Speckle',col:LM.purple}, rhino:{name:'Rhino',col:LM.ok},
  autocad:{name:'AutoCAD',col:LM.err},  outlook:{name:'Outlook',col:LM.blue},
};
const LM_STATE_META = {
  running:  { label:'running',     col:LM.accent, pulse:true },
  done:     { label:'done',        col:LM.ok },
  review:   { label:'needs review',col:LM.warn },
  paused:   { label:'paused',      col:LM.inkMuted },
  workflow: { label:'workflow',    col:LM.purple },
  scheduled:{ label:'scheduled',   col:LM.cyan },
  idle:     { label:'idle',        col:LM.inkMuted },
};

// ─── Safe-fallback helpers (founder demand #15) ────────────────────────
// Bridge may return states/categories the JSX doesn't know about. Never
// crash — fall back to "unknown" meta with sensible defaults.
const _STATE_FALLBACK = { label:'unknown', col:LM.inkMuted };
const _CAT_FALLBACK = { col:LM.inkSoft, icon:'·', label:'NODE', role:'' };
const stateMeta = (s) => (s && LM_STATE_META[s]) || _STATE_FALLBACK;
const catMeta = (c) => (c && CAT[c]) || _CAT_FALLBACK;

// ─── Bridge helpers — call slots safely, ignore in standalone mode. ────
const bridgeCall = (slot, ...args) => {
  try {
    const b = window.archhub;
    if (!b || typeof b[slot] !== 'function') return null;
    return b[slot](...args);
  } catch (e) { console.warn('[studio-lm] bridge ' + slot + ' failed:', e); return null; }
};
const bridgeJson = (slot, ...args) => {
  const raw = bridgeCall(slot, ...args);
  if (raw == null) return null;
  if (typeof raw !== 'string') return raw;
  try { return JSON.parse(raw); } catch { return null; }
};
// QWebChannel slot calls are ASYNC — `b[slot](args)` returns a Promise on
// Qt 6.4+ or undefined on older builds, never the raw return synchronously.
// This wrapper handles both: tries callback style for older Qt, awaits a
// Promise for newer, and races a 1.5s timeout so the user never hangs.
// Founder bug 2026-05-14: every composer + session-open round-trip was using
// the sync `bridgeJson` above, which returned null because Qt slots don't
// return synchronously. Result: silent no-ops everywhere.
const bridgeAsync = (slot, ...args) => new Promise((resolve) => {
  const b = window.archhub;
  if (!b || typeof b[slot] !== 'function') { resolve(null); return; }
  let resolved = false;
  const done = (raw) => {
    if (resolved) return; resolved = true;
    if (raw == null) { resolve(null); return; }
    if (typeof raw !== 'string') { resolve(raw); return; }
    try { resolve(JSON.parse(raw)); } catch { resolve(raw); }
  };
  try {
    const r = b[slot](...args, done);
    if (r && typeof r.then === 'function') r.then(done);
    setTimeout(() => { if (!resolved) done(null); }, 1500);
  } catch (e) {
    console.warn('[archhub] bridgeAsync ' + slot, e);
    resolve(null);
  }
});

// ─── Sessions — refresh + unified actions ──────────────────────────
// Founder bug 2026-05-18: the Home dashboard's session cards had NO
// management UI — rename/delete lived ONLY in the sidebar menu, which
// is reachable only AFTER a session is open. And the sidebar called
// the slots through the SYNC bridge, which returns null for slot
// results (Qt slots resolve async), so fork + duplicate were silent
// no-ops. One async path now, shared by the Home card and the sidebar.
async function refreshSessions() {
  const fetched = await bridgeAsync('get_sessions');
  if (Array.isArray(fetched)) {
    // Splice in place so every holder of the LM_SESSIONS reference
    // sees it. Accept an empty array — deleting the last session must
    // clear the list.
    LM_SESSIONS.splice(0, LM_SESSIONS.length, ...fetched);
  }
  return LM_SESSIONS;
}
const _lmToast = (msg, kind) => {
  try {
    window.dispatchEvent(new CustomEvent('lm-canvas-toast',
      { detail: { msg: msg, kind: kind || 'err' } }));
  } catch (e) {}
};
// action ∈ rename | fork | duplicate | delete. opts: { onOpen(id),
// openId, openAfterCreate, afterChange() }.
async function runSessionAction(action, sid, opts) {
  opts = opts || {};
  const sess = (LM_SESSIONS || []).find(s => s.id === sid);
  if (!sess) return;
  if (action === 'rename') {
    const next = window.prompt('Rename session', sess.title || '');
    if (next == null) return;
    const title = next.trim();
    if (!title || title === (sess.title || '')) return;
    const r = await bridgeAsync('rename_session', sid, title);
    if (!r || r.error) {
      _lmToast('Rename failed: ' + ((r && r.error) || 'no response'));
      return;
    }
  } else if (action === 'fork' || action === 'duplicate') {
    const r = action === 'fork'
      ? await bridgeAsync('fork_session', sid,
                            (sess.title || 'session') + ' (fork)')
      : await bridgeAsync('duplicate_session', sid);
    if (!r || r.error) {
      _lmToast(action + ' failed: ' + ((r && r.error) || 'no response'));
      return;
    }
    await refreshSessions();
    const newId = r.id || r.session_id;
    if (newId && opts.openAfterCreate && opts.onOpen) opts.onOpen(newId);
    if (opts.afterChange) opts.afterChange();
    return;
  } else if (action === 'delete') {
    if (!window.confirm('Delete "' + (sess.title || sid)
                          + '"? This can\'t be undone.')) return;
    const r = await bridgeAsync('delete_session', sid);
    if (!r || r.error) {
      _lmToast('Delete failed: ' + ((r && r.error) || 'no response'));
      return;
    }
    await refreshSessions();
    if (opts.openId === sid && opts.onOpen) {
      opts.onOpen((LM_SESSIONS[0] || {}).id || null);
    }
    if (opts.afterChange) opts.afterChange();
    return;
  } else {
    return;
  }
  await refreshSessions();
  if (opts.afterChange) opts.afterChange();
}

const currentSid = () => window.__archhub_session_id || 'default';
const saveCurrentGraph = () => {
  try {
    // Defensive merge: any leftover code that pushed into the legacy
    // userNodes state writes to window.__archhub_user_nodes so we still
    // capture it on save. Primary path is LM_GRAPH directly.
    const extra = Array.isArray(window.__archhub_user_nodes) ? window.__archhub_user_nodes : [];
    const merged = {
      nodes: [...(LM_GRAPH.nodes || []), ...extra.filter(n => n && !((LM_GRAPH.nodes || []).find(x => x.id === n.id)))],
      wires: LM_GRAPH.wires || [],
    };
    bridgeCall('save_graph', currentSid(), JSON.stringify(merged));
  } catch (e) {}
};

// ─── The active graph — typed AEC nodes.
// Founder demand #1: each saved session has its OWN graph blob on disk.
// Switching sessions splices nodes/wires wholesale via openSession().
// The window-global pattern lets the bridge mutate the same object the
// JSX render path is reading.
// Founder direction 2026-05-14: NO fake demo graph. Real graphs load
// from disk via bridge.load_session(id) which splices into LM_GRAPH.
// Empty graph by default — user sees a blank canvas until they spawn
// nodes via composer / right-click / node library.
const LM_GRAPH = window.__archhub_LM_GRAPH = window.__archhub_LM_GRAPH || { nodes: [], wires: [] };
const _LM_GRAPH_DEMO_DEAD = { nodes: [
    { id:'revit', cat:'host', x:24, y:48, w:220, h:124,
      title:'Revit 2025', sub:'Tower-A_central.rvt · L03',
      outs:[
        { id:'view', label:'active view', t:'view', val:'L03 · 1:50' },
        { id:'sel',  label:'selection',   t:'selection', val:'23 walls' },
      ],
    },
    { id:'ai_intent', cat:'ai', x:24, y:200, w:300, h:188,
      title:'Conversation', sub:'Claude Sonnet 4.5 · 412ms',
      ins: [{ id:'ctx', label:'context', t:'view' }],
      outs:[{ id:'intent', label:'intent', t:'intent', val:'dim ≥800mm, ext first' }],
      messages:[
        { who:'F', me:true, time:'14:31', text:'Open Tower-A_central.rvt and go to Level 03.' },
        { who:'C', time:'14:31', text:'Opened. 47 walls, 12 doors, 8 windows on this level.' },
        { who:'F', me:true, time:'14:32', text:'Dimension all walls in active view at 1:50. Exterior first, then partitions ≥ 800 mm.' },
        { who:'C', time:'14:32', text:'Filtering exterior first, then interior ≥ 800. Skipping shorter ones — noise floor on Level 03.' },
        { who:'F', me:true, time:'14:33', text:'Use the outer face as snap anchor, 240 mm offset is fine.' },
        { who:'C', time:'14:33', text:'Noted — snap_to=outer_face, offset_mm=240. Starting exterior pass.' },
        { who:'F', me:true, time:'14:34', text:'Also: skip the short bathroom partitions even if they\'re over 800.' },
        { who:'C', time:'14:34', text:'Got it — also excluding category=plumbing_fixture neighbors. Filter updated.' },
      ],
    },
    { id:'read_walls', cat:'read', x:360, y:60, w:220, h:96,
      title:'list_walls', sub:'revit.list_walls(view)',
      result:'47 walls', ms:'120ms',
      ins:[{ id:'view', label:'view', t:'view' }],
      outs:[{ id:'walls', label:'walls', t:'walls' }],
    },
    { id:'filter_ext', cat:'filter', x:360, y:190, w:220, h:118,
      title:'where exterior', sub:'predicate · element.is_exterior',
      result:'23 of 47', ms:'40ms',
      ins:[
        { id:'in',   label:'walls', t:'walls' },
        { id:'rule', label:'rule',  t:'intent' },
      ],
      outs:[{ id:'out', label:'matches', t:'walls' }],
    },
    { id:'filter_long', cat:'filter', x:360, y:340, w:220, h:90,
      title:'where length ≥ 800', sub:'predicate · length_mm ≥ 800',
      result:'14 of 24', ms:'18ms',
      ins:[{ id:'in', label:'walls', t:'walls' }],
      outs:[{ id:'out', label:'matches', t:'walls' }],
    },
    { id:'annotate', cat:'annotate', x:620, y:48, w:360, h:340,
      title:'Place exterior dimensions',
      sub:'revit.create_dimensions · stage 1 of 2',
      state:'running', progress:0.74, runtime:'3.1 / 4.2s',
      ins:[
        { id:'walls', label:'walls', t:'walls' },
        { id:'view',  label:'view',  t:'view' },
      ],
      outs:[{ id:'dims', label:'dimensions', t:'dims', val:'17 / 23 placed' }],
      params:[
        { k:'scale',     v:'1:50',       type:'select' },
        { k:'align',     v:'parallel',   type:'select' },
        { k:'offset_mm', v:240, min:60, max:600, step:10, type:'slider' },
        { k:'snap_to',   v:'outer face', type:'select' },
      ],
    },
    { id:'annotate2', cat:'annotate', x:620, y:420, w:240, h:110,
      title:'Place interior dimensions',
      sub:'stage 2 of 2 · queued',
      state:'queued',
      ins:[{ id:'walls', label:'walls (≥800)', t:'walls' }],
      outs:[{ id:'dims', label:'dimensions', t:'dims' }],
    },
    { id:'save', cat:'output', x:1010, y:170, w:260, h:160,
      title:'Save as Skill',
      sub:'2 stages · 4 tool calls · 8.9s',
      ins:[
        { id:'trace', label:'trace', t:'trace' },
        { id:'dims',  label:'dims',  t:'dims' },
      ],
      params:[
        { k:'name',      v:'Dimension active walls', type:'text' },
        { k:'arguments', v:'scale, min_length',      type:'text' },
      ],
    },
    // ─── category showcase ─ transform / logic / compose ───
    { id:'tx_marks', cat:'transform', x:620, y:560, w:260, h:122,
      title:'set wall marks', sub:'revit.set_param · "Mark" = auto',
      ins:[{ id:'walls', label:'walls', t:'walls' }],
      outs:[{ id:'walls', label:'walls', t:'walls' }],
      params:[
        { k:'parameter', v:'Mark', type:'select' },
        { k:'pattern',   v:'W-···', type:'text' },
      ],
    },
    { id:'lg_if', cat:'logic', x:1010, y:360, w:260, h:118,
      title:'if review needed', sub:'predicate · issues > 0',
      result:'→ yes · 8 issues', ms:'2ms',
      ins:[{ id:'in', label:'result', t:'dims' }],
      outs:[
        { id:'yes', label:'yes', t:'dims' },
        { id:'no',  label:'no',  t:'dims' },
      ],
    },
    { id:'cm_sched', cat:'compose', x:1300, y:60, w:280, h:204,
      title:'build wall schedule', sub:'revit.create_schedule',
      result:'24 rows · 6 columns', ms:'140ms',
      ins:[{ id:'walls', label:'walls', t:'walls' }],
      outs:[{ id:'sheet', label:'sheet', t:'sheets' }],
      params:[
        { k:'group_by',  v:'type',                  type:'select' },
        { k:'sort_by',   v:'length desc',           type:'select' },
        { k:'columns',   v:'type, level, length…',  type:'text' },
        { k:'totals',    v:'area, count',           type:'text' },
      ],
    },
    { id:'cm_pdf', cat:'output', x:1300, y:300, w:280, h:118,
      title:'publish PDF set', sub:'→ Dropbox / project-share',
      ins:[
        { id:'sheet', label:'sheet', t:'sheets' },
        { id:'dims',  label:'review', t:'dims' },
      ],
      params:[
        { k:'destination', v:'Dropbox · /Tower-A/issues', type:'text' },
        { k:'name',        v:'L03_walls_2026-05-13.pdf',  type:'text' },
      ],
    },
    // ─── second conversation ─ demonstrates concurrent AI sessions in one workspace
    { id:'ai_qa', cat:'ai', x:1640, y:340, w:300, h:188,
      title:'QA review conversation', sub:'Claude Sonnet 4.5 · ~520ms',
      ins:[
        { id:'ctx',  label:'context', t:'sheets' },
        { id:'dims', label:'dims',    t:'dims' },
      ],
      outs:[{ id:'intent', label:'review', t:'intent', val:'7 issues, 2 high' }],
      messages:[
        { who:'C', time:'14:35', text:'Reviewing the new schedule against the dimension run…' },
        { who:'C', time:'14:35', text:'2 walls in the table have length 0 — likely deleted but still tagged. Flagging.' },
        { who:'F', me:true, time:'14:35', text:'Drop those rows, keep the rest.' },
        { who:'C', time:'14:36', text:'Updated schedule → 24 rows, totals re-computed.' },
      ],
    },
    // ─── second host ─ demonstrates host→host wiring
    { id:'spk', cat:'host', x:1640, y:60, w:240, h:140,
      title:'Speckle', sub:'tower-a/main',
      ins:[
        { id:'sheet', label:'sheet',  t:'sheets' },
        { id:'view',  label:'model',  t:'view' },
      ],
      outs:[
        { id:'commit', label:'commit',  t:'trace', val:'cbb8e2 · 14 files' },
        { id:'url',    label:'permalink',t:'file' },
      ],
    },
  ],
  wires: [
    { from:['revit','view'],         to:['ai_intent','ctx']   },
    { from:['revit','view'],         to:['read_walls','view'] },
    { from:['read_walls','walls'],   to:['filter_ext','in']   },
    { from:['ai_intent','intent'],   to:['filter_ext','rule'] },
    { from:['filter_ext','out'],     to:['filter_long','in']  },
    { from:['filter_ext','out'],     to:['annotate','walls']  },
    { from:['revit','view'],         to:['annotate','view']   },
    { from:['filter_long','out'],    to:['annotate2','walls'] },
    { from:['annotate','dims'],      to:['save','dims']       },
    { from:['filter_long','out'],    to:['save','trace']      },
    // showcase wires
    { from:['filter_ext','out'],     to:['tx_marks','walls']  },
    { from:['tx_marks','walls'],     to:['cm_sched','walls']  },
    { from:['cm_sched','sheet'],     to:['cm_pdf','sheet']    },
    { from:['annotate','dims'],      to:['lg_if','in']        },
    { from:['lg_if','yes'],          to:['cm_pdf','dims']     },
    // second conversation — fed by schedule + dimensions
    { from:['cm_sched','sheet'],     to:['ai_qa','ctx']       },
    { from:['annotate','dims'],      to:['ai_qa','dims']      },
    // host → host — Revit's view + the published sheet flow into Speckle
    { from:['cm_sched','sheet'],     to:['spk','sheet']       },
    { from:['revit','view'],         to:['spk','view']        },
  ],
};

// ─── Library of nodes that can be inserted — Grasshopper/Dynamo style
// LM_LIBRARY v2 · 80 nodes / 10 categories · informed by Grasshopper /
// Dynamo / Speckle taxonomies + live host_detector.py PROBERS.
// Source spec: docs/NODE_LIBRARY_v2.md
const LM_LIBRARY = window.__archhub_LM_LIBRARY = window.__archhub_LM_LIBRARY || [
  // ──────── HOST · 18 families ────────
  { cat:'host', items:[
    { id:'h_revit',       title:'Revit',         sub:'open document, view, selection · broker @ :48884' },
    { id:'h_autocad',     title:'AutoCAD',       sub:'drawing, modelspace, layout · broker @ :48885' },
    { id:'h_max',         title:'3ds Max',       sub:'scene, viewport, render · broker @ :48886' },
    { id:'h_blender',     title:'Blender',       sub:'mesh, sketch, render · runner' },
    { id:'h_rhino',       title:'Rhino',         sub:'curves, meshes, layers · grasshopper bridge' },
    { id:'h_speckle',     title:'Speckle',       sub:'commit, stream, branch · GraphQL' },
    { id:'h_outlook',     title:'Outlook',       sub:'inbox, calendar, draft · COM' },
    { id:'h_teams',       title:'Microsoft Teams', sub:'channels, messages, mentions · Graph token' },
    { id:'h_notion',      title:'Notion',        sub:'pages, databases, blocks · internal token' },
    { id:'h_lmstudio',    title:'LM Studio',     sub:'local LLM @ 127.0.0.1:1234' },
    { id:'h_antigravity', title:'Antigravity',   sub:'desktop coding agent · process probe' },
    { id:'h_photoshop',   title:'Photoshop',     sub:'document, layers, actions · COM' },
    { id:'h_illustrator', title:'Illustrator',   sub:'document, artboards · COM' },
    { id:'h_indesign',    title:'InDesign',      sub:'document, spreads, frames · COM' },
    { id:'h_word',        title:'Word',          sub:'document, paragraphs, styles · COM' },
    { id:'h_excel',       title:'Excel',         sub:'workbook, sheet, range · COM' },
    { id:'h_powerpoint',  title:'PowerPoint',    sub:'presentation, slides, shapes · COM' },
    { id:'h_dropbox',     title:'Dropbox',       sub:'folder watch, upload, share link' },
  ]},
  // ──────── READ · pull data from a host ────────
  { cat:'read', items:[
    { id:'r_walls',     title:'list_walls',       sub:'pull walls from active Revit view' },
    { id:'r_doors',     title:'list_doors',       sub:'pull doors + swings + marks' },
    { id:'r_windows',   title:'list_windows',     sub:'pull windows + types' },
    { id:'r_rooms',     title:'list_rooms',       sub:'rooms with boundaries + names' },
    { id:'r_sheets',    title:'list_sheets',      sub:'enumerate sheets in set' },
    { id:'r_views',     title:'list_views',       sub:'plans, sections, schedules, 3D' },
    { id:'r_levels',    title:'list_levels',      sub:'levels + elevations + datums' },
    { id:'r_grids',     title:'list_grids',       sub:'gridlines · X / Y / radial' },
    { id:'r_families',  title:'list_families',    sub:'loaded family + type catalogue' },
    { id:'r_selection', title:'get_selection',    sub:'whatever is selected in host' },
    { id:'r_warnings',  title:'list_warnings',    sub:'host warnings · by severity' },
    { id:'r_emails',    title:'list_emails',      sub:'Outlook inbox · filter, sort' },
    { id:'r_files',     title:'list_files',       sub:'Dropbox / OneDrive · path glob' },
    { id:'r_pages',     title:'list_pages',       sub:'Notion db rows · filter, sort' },
    { id:'r_layers',    title:'list_layers',      sub:'CAD/PS/AI layers · visible only' },
    { id:'r_range',     title:'read_range',       sub:'Excel range → 2D array' },
  ]},
  // ──────── FILTER · predicate streams ────────
  { cat:'filter', items:[
    { id:'f_type',     title:'where type',         sub:'by family/type name' },
    { id:'f_cat',      title:'where category',     sub:'by Revit category id' },
    { id:'f_level',    title:'where level',        sub:'by level reference' },
    { id:'f_param',    title:'where parameter',    sub:'predicate on a parameter value' },
    { id:'f_phase',    title:'where phase',        sub:'by construction phase' },
    { id:'f_workset',  title:'where workset',      sub:'by workset assignment' },
    { id:'f_name',     title:'where name matches', sub:'glob / regex on element name' },
    { id:'f_pred',     title:'where custom',       sub:'arbitrary JS predicate' },
  ]},
  // ──────── TRANSFORM · mutate / reshape streams ────────
  { cat:'transform', items:[
    { id:'t_setp',     title:'set parameter',   sub:'mutates parameter values' },
    { id:'t_settype',  title:'set type',        sub:'change family type on each element' },
    { id:'t_move',     title:'move',            sub:'translation vector' },
    { id:'t_rot',      title:'rotate',          sub:'angle about axis' },
    { id:'t_scale',    title:'scale',           sub:'uniform / per-axis' },
    { id:'t_group',    title:'group by',        sub:'key → list of lists' },
    { id:'t_sort',     title:'sort by',         sub:'asc / desc on key' },
    { id:'t_dedupe',   title:'dedupe',          sub:'unique by identity or key' },
    { id:'t_paint',    title:'paint',           sub:'override colour / line / fill' },
    { id:'t_rename',   title:'rename',          sub:'pattern → new name' },
  ]},
  // ──────── ANNOTATE · markup-only ────────
  { cat:'annotate', items:[
    { id:'a_dims',     title:'create_dimensions', sub:'aligned, parallel, baseline' },
    { id:'a_tags',     title:'place_tags',        sub:'tag per element + leader' },
    { id:'a_text',     title:'add_text',          sub:'text note · positioned' },
    { id:'a_rooms',    title:'tag_rooms',         sub:'room boundaries + names' },
    { id:'a_cloud',    title:'revision_cloud',    sub:'cloud around dirty region' },
    { id:'a_grid',     title:'place_grid',        sub:'gridline + bubble' },
    { id:'a_level',    title:'place_level',       sub:'level + elevation bubble' },
  ]},
  // ──────── COMPOSE · build artefacts ────────
  { cat:'compose', items:[
    { id:'c_sched',    title:'build_schedule',    sub:'table from a stream' },
    { id:'c_sheet',    title:'place_on_sheet',    sub:'lay views onto a sheet' },
    { id:'c_legend',   title:'make_legend',       sub:'symbol legend block' },
    { id:'c_keynote',  title:'make_keynote',      sub:'keynote table + leaders' },
    { id:'c_index',    title:'drawing_index',     sub:'sheet list → cover page' },
  ]},
  // ──────── LOGIC · control flow ────────
  { cat:'logic', items:[
    { id:'l_if',       title:'if',                sub:'predicate → true / false branches' },
    { id:'l_switch',   title:'switch',            sub:'multi-branch on a key' },
    { id:'l_loop',     title:'loop',              sub:'iterate over a list' },
    { id:'l_foreach',  title:'foreach',           sub:'apply subgraph per item' },
    { id:'l_merge',    title:'merge',             sub:'concat / dedupe streams' },
    { id:'l_split',    title:'split',             sub:'partition by predicate' },
    { id:'l_delay',    title:'delay',             sub:'wait N ms before downstream' },
    { id:'l_throttle', title:'throttle',          sub:'rate-limit downstream' },
  ]},
  // ──────── AI · LLM-driven nodes ────────
  { cat:'ai', items:[
    { id:'i_conv',     title:'Conversation',      sub:'streaming chat node · system + history',
      ins:[{ id:'ctx', label:'context', t:'any' }],
      outs:[{ id:'response', label:'response', t:'completion' }] },
    { id:'i_think',    title:'think',             sub:'Claude reasoning · sonnet / opus / haiku' },
    { id:'i_vis',      title:'vision',            sub:'parse a sketch / screenshot' },
    { id:'i_embed',    title:'embed',             sub:'vectorize · similarity search' },
    { id:'i_match',    title:'match_skill',       sub:'find best saved skill for intent' },
    { id:'i_sum',      title:'summarise',         sub:'long text → bullet brief' },
    { id:'i_class',    title:'classify',          sub:'free text → enum label' },
    { id:'i_intent',   title:'extract_intent',    sub:'composer prompt → action plan' },
  ]},
  // ──────── OUTPUT · publish / save / notify ────────
  { cat:'output', items:[
    { id:'o_skill',    title:'save_skill',        sub:'template this run as a Skill' },
    { id:'o_pdf',      title:'publish_pdf',       sub:'sheets → PDF set' },
    { id:'o_spk',      title:'push_speckle',      sub:'commit to a branch' },
    { id:'o_email',    title:'send_email',        sub:'draft + send via Outlook' },
    { id:'o_notify',   title:'notify',            sub:'desktop / Teams ping' },
    { id:'o_csv',      title:'write_csv',         sub:'stream → .csv on disk' },
    { id:'o_xlsx',     title:'write_xlsx',        sub:'stream → workbook / sheet' },
    { id:'o_teams',    title:'post_teams',        sub:'channel message · markdown' },
    { id:'o_notion',   title:'create_notion_page',sub:'new page under parent' },
  ]},
  // ──────── TRIGGER · event-sourced graph entry ────────
  { cat:'trigger', items:[
    { id:'g_save',     title:'on_file_save',      sub:'fires when a host doc is saved' },
    { id:'g_email',    title:'on_email_arrive',   sub:'inbox watcher · sender / subject filter' },
    { id:'g_sched',    title:'on_schedule',       sub:'cron · every N min / hour / day' },
    { id:'g_revit',    title:'on_revit_event',    sub:'doc_opened / view_changed / sync_done' },
    { id:'g_warning',  title:'on_warning',        sub:'new host warning above threshold' },
  ]},
];

// ─── Connector op catalogue — hydrated from bridge.get_connectors().
// Each entry: { host, display_name, mechanism, ops:[{op_id,host,kind,
// label,description,inputs,output_type,destructive}] }. The node library
// reads this to surface all 116 connector operations as spawnable nodes.
const LM_CONNECTORS = window.__archhub_LM_CONNECTORS = window.__archhub_LM_CONNECTORS || [];
// User-minted custom nodes — AI-designed via Node Smith or hand-built.
const LM_CUSTOM_NODES = window.__archhub_LM_CUSTOM_NODES = window.__archhub_LM_CUSTOM_NODES || [];

// Per-host brand colors for connector op nodes / library grouping.
const CONNECTOR_COLORS = {
  revit:'#E87D0D', autocad:'#C66C0A', max:'#5b8def', blender:'#E87D0D',
  rhino:'#0696D7', speckle:'#3a6acc', outlook:'#0078D4', teams:'#5b5fc7',
  notion:'#b8b4ab', dropbox:'#0061ff', word:'#2B579A', excel:'#107C41',
  powerpoint:'#B7472A', photoshop:'#31A8FF', illustrator:'#FF9A00',
  indesign:'#FF3366',
};

// ──────────────────────── ROOT ────────────────────────
const StudioLM = () => {
  // Pick first session if hydrated, else fall back to demo "walls". Bridge
  // hydration may not have happened yet on the very first render.
  const initialId = (LM_SESSIONS && LM_SESSIONS[0]) ? LM_SESSIONS[0].id : null;
  const [openId, setOpenId] = React.useState(initialId);
  const [openTabs, setOpenTabs] = React.useState(initialId ? [initialId] : []);
  // Founder demand 2026-05-15: Auto is the default. Router picks the best
  // available model per turn — keeps the user out of provider drama.
  const [model, setModel] = React.useState({
    id:'auto', name:'Auto (router picks)', vendor:'ArchHub',
    tag:'AUTO', ctx:'—', col:'#cc785c', latency:0,
  });
  const [pickerOpen, setPickerOpen] = React.useState(false);
  const [settingsOpen, setSettingsOpen] = React.useState(false);
  const [libraryOpen, setLibraryOpen] = React.useState(false);
  const [createNodeOpen, setCreateNodeOpen] = React.useState(false);
  const [aiNodeOpen, setAiNodeOpen] = React.useState(false);
  // Roadmap #P0 2026-05-17: first-run profile capture. On first launch
  // (no profile.json) prompt once for firm / role / discipline.
  const [firstRunProfile, setFirstRunProfile] = React.useState(false);
  React.useEffect(() => {
    let cancelled = false;
    bridgeAsync('get_profile').then((p) => {
      if (cancelled || !p || typeof p !== 'object' || p.error) return;
      if (!(p.firm || p.role || p.discipline || p.skipped)) {
        setFirstRunProfile(true);
      }
    });
    return () => { cancelled = true; };
  }, []);
  const [panel, setPanel] = React.useState('nodes'); // only 'nodes' now — chats/skills/search panels removed
  // Default focus to the first AI node so the right-rail isn't empty.
  const [focusId, setFocusId] = React.useState(() => {
    const ai = (LM_GRAPH.nodes || []).find(n => n.cat === 'ai');
    return ai ? ai.id : ((LM_GRAPH.nodes || [])[0] && LM_GRAPH.nodes[0].id) || null;
  });
  // User-added nodes (deletable). LM_GRAPH.nodes is the demo graph (kept).
  const [userNodes, setUserNodes] = React.useState([]);
  // Bump counter to force rerender after we mutate LM_GRAPH.wires/nodes in place.
  const [graphBump, setGraphBump] = React.useState(0);
  const bumpGraph = React.useCallback(() => setGraphBump(b => b + 1), []);

  const session = openId ? (LM_SESSIONS || []).find(s => s.id === openId) : null;

  // ─── Founder demand #1: switching sessions swaps the WHOLE graph blob.
  // bridge.load_session(id) returns {nodes,wires,...}. We splice it into
  // LM_GRAPH so the renderer (and every downstream useMemo) sees fresh data.
  // Also exposes window.__archhub_session_id so save_graph() targets the right
  // file (founder demand #16: no more hardcoded 'workspace').
  const openSession = React.useCallback(async (id) => {
    if (!id) { setOpenId(null); return; }
    if (!openTabs.includes(id)) setOpenTabs(t => [...t, id]);
    setOpenId(id);
    window.__archhub_session_id = id;
    // Reset to empty immediately so stale graph doesn't flash while we wait.
    LM_GRAPH.nodes = []; LM_GRAPH.wires = [];
    setUserNodes([]); setFocusId(null);
    bumpGraph();
    // QWebChannel slots are async — use bridgeAsync, never sync bridgeJson.
    const blob = await bridgeAsync('load_session', id);
    if (blob && typeof blob === 'object' && !blob.error) {
      const g = (blob.graph && typeof blob.graph === 'object') ? blob.graph : blob;
      LM_GRAPH.nodes = Array.isArray(g.nodes) ? g.nodes : [];
      LM_GRAPH.wires = Array.isArray(g.wires) ? g.wires : [];
      const ai = (LM_GRAPH.nodes || []).find(n => n.cat === 'ai');
      setFocusId(ai ? ai.id : (LM_GRAPH.nodes[0] && LM_GRAPH.nodes[0].id) || null);
      bumpGraph();
    }
  }, [openTabs, bumpGraph]);

  const closeTab = (id) => {
    setOpenTabs(t => {
      const next = t.filter(x => x !== id);
      if (openId === id) {
        const replacement = next[next.length - 1] || null;
        if (replacement) openSession(replacement); else setOpenId(null);
      }
      return next;
    });
  };

  // ─── Founder demand #5+#6: mint a fresh session.
  // Founder bug 2026-05-15: "latest session edits weren't saved." Root
  // cause was a RACE: createSession returned a synthetic id immediately,
  // the caller dispatched a spawn 80ms later, but openSession(realSlug)
  // resolved AFTER that — and openSession resets LM_GRAPH to empty, which
  // wiped the just-spawned nodes, and saveCurrentGraph wrote to the wrong
  // file. Fix: createSession is now fully async — it awaits the bridge,
  // awaits openSession, THEN returns the real slug. Callers await it
  // before dispatching anything. No setTimeout, no race.
  const createSession = React.useCallback(async (title) => {
    const blob = await bridgeAsync('create_session', title || 'untitled');
    const id = (blob && (blob.id || blob.session_id))
               || ('s_' + Date.now().toString(36));
    if (blob && blob.session && !LM_SESSIONS.find(s => s.id === id)) {
      LM_SESSIONS.push(blob.session);
    } else if (!LM_SESSIONS.find(s => s.id === id)) {
      LM_SESSIONS.push({ id,
        title: (blob && blob.title) || title || 'untitled',
        state:'idle', host:'', file:'',
        model:'auto', when:'just now', last:'',
        saved_at: (blob && blob.saved_at) || '',
      });
    }
    // Await the open so window.__archhub_session_id is the real slug
    // BEFORE the caller dispatches a spawn that triggers saveCurrentGraph.
    await openSession(id);
    return id;
  }, [openSession]);

  // ─── One-time auto-open of the most recent session on first hydration.
  // Sessions arrive async (bridge get_sessions); on the very first render
  // LM_SESSIONS is usually empty so `openId` seeds to null (Home). When
  // the list lands, open the first session ONCE — and via openSession so
  // its graph actually loads. This replaces the old `key`-remount, which
  // re-seeded state on EVERY pull (nuking modals / canvas / focus) and
  // didn't even load the graph. Self-guards with a ref so it fires once.
  const didAutoOpenRef = React.useRef(false);
  React.useEffect(() => {
    if (didAutoOpenRef.current) return;
    if (openId) { didAutoOpenRef.current = true; return; }
    if ((LM_SESSIONS || []).length > 0) {
      didAutoOpenRef.current = true;
      openSession(LM_SESSIONS[0].id);
    }
  });

  // Insert a node from the library at canvas coords (x,y). called from drop or dbl-click
  const addNodeFromLibrary = (libItem, x = 200, y = 200) => {
    const cat = libItem.cat;
    // ── Connector-op node: a real host operation (revit.list_walls,
    // excel.read_range, …). Carries op_id + typed inputs so the canvas
    // can run it via bridge.run_connector_op. Founder demand 2026-05-15.
    if (libItem._connector_op) {
      const op = libItem._connector_op;
      const id = `op_${(op.op_id || 'op').replace(/[^a-z0-9]+/gi, '_')}_${Date.now().toString(36).slice(-4)}`;
      const params = (op.inputs || []).map(p => ({
        k: p.id, v: p.default != null ? p.default : '',
        type: p.type || 'text', label: p.label || p.id,
        options: p.options || [], required: !!p.required, help: p.help || '',
        options_source: p.options_source || '',   // dynamic dropdown source op
        _by: 'default',                            // provenance: default|you|ai|host
      }));
      const opNode = {
        id, cat:'connector_op', x, y, w:248, h:128,
        title: op.label || op.op_id, sub: op.host + ' · ' + (op.kind || 'op'),
        op_id: op.op_id, host: op.host, op_kind: op.kind || 'read',
        destructive: !!op.destructive,
        ins: [{ id:'in', label:'in', t:'any' }],
        outs: [{ id:'out', label:'result', t: op.output_type || 'any' }],
        params, _user: true,
      };
      LM_GRAPH.nodes.push(opNode);
      setFocusId(id);
      saveCurrentGraph();
      bumpGraph();
      return opNode;
    }
    // ── Custom node: an AI-minted (or hand-built) node type registered
    // server-side in the workflow registry. Carries `custom_type` (the
    // registered type id) + typed sockets straight off the spec, so it's
    // a real wireable node — not a decorative placeholder. Founder demand
    // 2026-05-16: "custom-make nodes on a whim using AI."
    if (libItem._custom_node) {
      const spec = libItem._custom_node;
      const port = (p, i, dir) => {
        if (typeof p === 'string') return { id: p, label: p, t:'any' };
        const nm = (p && p.name) || `${dir}${i}`;
        return { id: nm, label: nm, t: (p && p.type) || 'any' };
      };
      const id = `cn_${String(spec.type || 'custom').replace(/[^a-z0-9]+/gi,'_')}_${Date.now().toString(36).slice(-4)}`;
      const node = {
        id, cat:'custom', x, y, w:232, h:120,
        title: spec.title || spec.display_name || spec.type || 'Custom node',
        sub: spec.description || ('custom · ' + (spec.type || '')),
        custom_type: spec.type || '',
        icon: spec.icon || '⊕',
        ins:  (spec.inputs  || []).map((p,i) => port(p,i,'in')),
        outs: (spec.outputs || []).map((p,i) => port(p,i,'out')),
        params: [], _user: true,
      };
      LM_GRAPH.nodes.push(node);
      setFocusId(id);
      saveCurrentGraph();
      bumpGraph();
      return node;
    }
    const tmpl = LM_NODE_TEMPLATES[libItem.id] || LM_NODE_TEMPLATES[`__cat_${cat}`] || {};
    const id = `${libItem.id || cat}_${Date.now().toString(36).slice(-4)}`;
    const newNode = {
      id, cat, x, y, w: tmpl.w || libItem.w || 220, h: tmpl.h || libItem.h || 110,
      title: libItem.title, sub: libItem.sub,
      ins: libItem.ins || tmpl.ins || [],
      outs: libItem.outs || tmpl.outs || [],
      params: libItem.params || tmpl.params || [],
      _user: true,
    };
    // Push directly into LM_GRAPH so saveCurrentGraph() captures it
    // (userNodes state was a parallel array that never persisted —
    // founder bug: "auto-saving sessions isn't working").
    LM_GRAPH.nodes.push(newNode);
    setFocusId(id);
    saveCurrentGraph();
    bumpGraph();
    return newNode;
  };

  const removeUserNode = React.useCallback((id) => {
    setUserNodes(ns => ns.filter(n => n.id !== id));
  }, []);

  // ─── Founder demand #2 + #3: apply composer-parsed actions.
  // The bridge returns an action descriptor; we mutate canvas state per
  // `command`. This listener is the single point that handles every kind of
  // composer-driven canvas mutation, so the FloatingComposer can stay dumb.
  React.useEffect(() => {
    const handler = (ev) => {
      const detail = (ev && ev.detail) || {};
      const action = detail.action || {};
      const cmd = action.command || 'chat';
      // Founder demand: silent failures are unacceptable. Surface every
      // composer dispatch as a toast so the user always sees feedback.
      try {
        window.dispatchEvent(new CustomEvent('lm-canvas-toast', {
          detail: { msg: action.summary || `composer: ${cmd}`, kind:'info' },
        }));
      } catch (e) {}
      try {
      switch (cmd) {
        case 'help': {
          // /ping with no host, or any /unknown — flash the summary so
          // the user sees the parser's reply instead of a black hole.
          try {
            window.dispatchEvent(new CustomEvent('lm-canvas-toast', {
              detail: { msg: action.summary || action.error || 'unknown command', kind:'err' },
            }));
          } catch (e) {}
          break;
        }
        case '_refresh': {
          // FloatingComposer asks for a render bump after an async bridge
          // result mutated LM_GRAPH directly.
          bumpGraph();
          break;
        }
        case '_passthrough': {
          // Plain chat — push into focused conversation (same as default).
          const text = action.raw || detail.raw || '';
          if (!text) break;
          const convNode = (LM_GRAPH.nodes || []).find(n => n.id === detail.focusId && n.cat === 'ai')
                       || (LM_GRAPH.nodes || []).find(n => n.cat === 'ai');
          if (!convNode) {
            // No conversation yet — spawn one for visible feedback.
            const conv = addNodeFromLibrary({
              id:'i_conv', cat:'ai', title:'Conversation', sub:'Claude · streaming',
              ins:[{ id:'ctx', label:'context', t:'any' }],
              outs:[{ id:'response', label:'response', t:'completion' }],
            }, 200, 200);
            conv.messages = [{ me:true, text, time:new Date().toISOString().slice(11,16) }];
            bumpGraph();
            try { bridgeCall('send_chat_history', currentSid(), text, JSON.stringify([{ me:true, text }])); } catch (e) {}
          } else {
            const history = (convNode.messages || []).map(m => ({ me:m.me, text:m.text }));
            history.push({ me:true, text, time:new Date().toISOString().slice(11,16) });
            convNode.messages = history.concat([{ me:false, text:'…', streaming:true }]);
            bumpGraph();
            try { bridgeCall('send_chat_history', currentSid(), text, JSON.stringify(history)); } catch (e) {}
          }
          break;
        }
        case 'spawn_host_chat': {
          const family = action.family || action.host || 'revit';
          // Position new pair near the existing graph's centroid (or origin
          // for a fresh canvas) so the user actually sees the spawn instead
          // of it appearing offscreen.
          const existingNodes = LM_GRAPH.nodes || [];
          let baseX = 60, baseY = 60;
          if (existingNodes.length > 0) {
            const maxX = Math.max(...existingNodes.map(n => (n.x || 0) + (n.w || 220)));
            baseX = maxX + 60;
            baseY = 60 + (existingNodes.length % 3) * 320;
          }
          // De-dupe HOST: don't spawn a 2nd Outlook host if one already exists.
          const exists = existingNodes.find(n => n.cat === 'host' && (n.title || '').toLowerCase().includes(family));
          let hostNode = exists;
          if (!hostNode) {
            hostNode = addNodeFromLibrary({
              id: `h_${family}`, cat:'host', title: family.charAt(0).toUpperCase()+family.slice(1),
              sub: action.sub || 'host',
            }, baseX, baseY);
          }
          // ALWAYS spawn a fresh conversation per ping — founder demand.
          // Each "ping <host>" creates a new chat thread tied to the host.
          const convNode = addNodeFromLibrary({
            id:'i_conv', cat:'ai', title:'Conversation', sub:'Claude · streaming',
            ins:[{ id:'ctx', label:'context', t:'any' }],
            outs:[{ id:'response', label:'response', t:'completion' }],
            messages:[],
          }, (hostNode.x || baseX) + 280, (hostNode.y || baseY) + 40);
          // User-visible feedback — toast names what just spawned.
          try {
            window.dispatchEvent(new CustomEvent('lm-canvas-toast', {
              detail: { text: `Spawned ${family} host + conversation`, kind: 'info' },
            }));
          } catch (e) {}
          if (hostNode && convNode) {
            const outId = (hostNode.outs || [])[0]?.id || 'view';
            const inId = (convNode.ins || [])[0]?.id || 'ctx';
            LM_GRAPH.wires = [...(LM_GRAPH.wires || []), { from:[hostNode.id, outId], to:[convNode.id, inId] }];
            saveCurrentGraph(); bumpGraph();
            setFocusId(convNode.id);
          }
          // Founder bug 2026-05-15: "ping autocad" was sent to the LLM as
          // a chat turn — the model then HALLUCINATED a <function_calls>
          // block and a fake <function_result> ("Drawing1.dwg open").
          // Fix: a ping is an ACTION, not a conversation. Run a REAL
          // connector probe and write the true status into the conv. No
          // LLM round-trip for ping/info verbs.
          const text = action.text || detail.raw || '';
          const verb = (action.verb || '').toLowerCase();
          const now = () => new Date().toISOString().slice(11,16);
          if (convNode && (verb === 'ping' || verb === 'info')) {
            convNode.messages = [
              { me:true, text, who:'You', time:now() },
              { me:false, text:'…', streaming:true, time:now() },
            ];
            bumpGraph();
            bridgeAsync('probe_connector', family).then((res) => {
              const st = (res && res.status) || 'unknown';
              const note = (res && res.note) || '';
              const ok = st === 'live';
              const reply = ok
                ? `✓ ${family} is connected — ${note || 'live'}.`
                : (st === 'loaded_dead'
                    ? `${family} is running but the ArchHub connector isn't loaded — ${note}.`
                    : st === 'unauthorized'
                    ? `${family} needs authorization — ${note}.`
                    : `${family} is not reachable (${st})${note ? ' — ' + note : ''}.`);
              const msgs = convNode.messages || [];
              const ix = msgs.findIndex(m => m.streaming);
              const stamped = { me:false, text:reply, time:now(),
                                 who:'ArchHub', col: ok ? LM.ok : LM.warn };
              if (ix >= 0) msgs[ix] = stamped; else msgs.push(stamped);
              saveCurrentGraph(); bumpGraph();
            });
          } else if (text && convNode) {
            // A genuine question (not a ping) — LLM chat is appropriate.
            const history = (convNode.messages || []).map(m => ({ me:m.me, text:m.text }));
            history.push({ me:true, text, time:now() });
            convNode.messages = history.concat([{ me:false, text:'…', time:now(), streaming:true }]);
            bumpGraph();
            bridgeCall('send_chat_history', currentSid(), text, JSON.stringify(history));
          }
          break;
        }
        case 'wire': {
          // Two callers: slash-command parser (raw text → apply_composer_command)
          // and the LLM agent (structured src_node/src_port/dst_node/dst_port).
          // Agent path takes precedence when the descriptor already carries the
          // wired pair, so we don't make a no-op bridge round-trip.
          if (action.src_node && action.dst_node) {
            const w = { from: [action.src_node, action.src_port || 'out'],
                        to:   [action.dst_node, action.dst_port || 'in'] };
            LM_GRAPH.wires = [...(LM_GRAPH.wires || []), w];
            saveCurrentGraph(); bumpGraph();
            break;
          }
          const out = bridgeJson('apply_composer_command', JSON.stringify(LM_GRAPH), detail.raw || '', detail.focusId || '');
          if (out && out.graph && Array.isArray(out.graph.nodes)) {
            LM_GRAPH.nodes = out.graph.nodes;
            LM_GRAPH.wires = out.graph.wires || [];
            saveCurrentGraph(); bumpGraph();
          }
          break;
        }
        case 'set_node_param': {
          // Agent tool — direct param mutation on a node by id.
          const nid = action.node_id, key = action.key;
          if (!nid || !key) break;
          const target = (LM_GRAPH.nodes || []).find(n => n.id === nid);
          if (target) {
            target.params = target.params || {};
            target.params[key] = action.value;
            saveCurrentGraph(); bumpGraph();
          }
          break;
        }
        case 'run_node': {
          // Agent tool — cook a single node via the bridge runner.
          if (action.node_id) {
            try { bridgeCall('run_node', action.node_id); } catch (e) {}
          }
          break;
        }
        case 'run_workflow': {
          // Agent tool — cook every sink in the graph via the bridge.
          try { bridgeCall('run_workflow'); } catch (e) {}
          break;
        }
        case 'freeze':     // /freeze
        case 'delete':     // /delete
        case 'rename':     // /rename "new name"
        case 'duplicate':  // /duplicate
        case 'properties': // /properties
        case 'disconnect': { // /disconnect
          // The bridge's apply_composer_command returns the mutated graph,
          // so we ask for that one-shot. Safe if bridge missing — we no-op.
          const out = bridgeJson('apply_composer_command', JSON.stringify(LM_GRAPH), detail.raw || '', detail.focusId || '');
          if (out && out.graph && Array.isArray(out.graph.nodes)) {
            LM_GRAPH.nodes = out.graph.nodes;
            LM_GRAPH.wires = out.graph.wires || [];
            saveCurrentGraph(); bumpGraph();
          }
          break;
        }
        case 'createnode': {
          setCreateNodeOpen(action.spec || true);
          break;
        }
        case 'chat':
        default: {
          // Plain chat — push into focused conversation if any.
          const text = action.text || detail.raw || '';
          const detAtts = Array.isArray(detail.attachments) ? detail.attachments : [];
          // Image paths feed multimodal providers (Anthropic / OpenAI /
          // Google read m.images from the history JSON in bridge.send_chat_history).
          const imagePaths = detAtts.filter(a => a && a.kind === 'image').map(a => a.path);
          const otherAtts  = detAtts.filter(a => a && a.kind !== 'image');
          if (!text && !detAtts.length) break;
          const convNode = (LM_GRAPH.nodes || []).find(n => n.id === detail.focusId && n.cat === 'ai')
                       || userNodes.find(n => n.id === detail.focusId && n.cat === 'ai')
                       || (LM_GRAPH.nodes || []).find(n => n.cat === 'ai')
                       || userNodes.find(n => n.cat === 'ai');
          // Build a user-visible label for attachments (chip-style summary).
          const _attLabel = detAtts.length
            ? `\n[attached: ${detAtts.map(a => a.name).join(', ')}]`
            : '';
          const visibleText = (text || '') + _attLabel;
          // Stamp every assistant message with the active model so the
          // Conversation avatar reflects what's actually answering.
          const _modelStamp = {
            id: model.id || 'auto',
            name: model.name || 'Auto',
            vendor: model.vendor || 'ArchHub',
            col: model.col || LM.accent,
            who: ((model.name || 'A')[0] || 'A').toUpperCase(),
          };
          if (!convNode) {
            const conv = addNodeFromLibrary({
              id:'i_conv', cat:'ai',
              title:'Conversation', sub:`${_modelStamp.name} · streaming`,
              ins:[{ id:'ctx', label:'context', t:'any' }],
              outs:[{ id:'response', label:'response', t:'completion' }],
            }, 200, 200);
            conv.messages = [{ me:true, text: visibleText,
                                attachments: detAtts,
                                images: imagePaths,
                                who: 'You',
                                time:new Date().toISOString().slice(11,16) },
                              { me:false, text:'…', streaming:true,
                                model: _modelStamp,
                                who: _modelStamp.who,
                                col: _modelStamp.col,
                                time:new Date().toISOString().slice(11,16) }];
            bumpGraph();
            try {
              bridgeCall('send_chat_history', currentSid(), text || '(see attachments)',
                JSON.stringify([{ me:true, text: text || '(see attachments)',
                                    images: imagePaths }]));
            } catch (e) {}
          } else {
            const history = (convNode.messages || [])
              .filter(m => !m.streaming)
              .map(m => ({ me:m.me, text:m.text || '', images: m.images || [] }));
            history.push({ me:true, text: text || '(see attachments)',
                            images: imagePaths });
            convNode.messages = [
              ...(convNode.messages || []).filter(m => !m.streaming),
              { me:true, text: visibleText, attachments: detAtts,
                 images: imagePaths, who: 'You',
                 time:new Date().toISOString().slice(11,16) },
              { me:false, text:'…', streaming:true,
                 model: _modelStamp,
                 who: _modelStamp.who,
                 col: _modelStamp.col,
                 time:new Date().toISOString().slice(11,16) },
            ];
            bumpGraph();
            try {
              bridgeCall('send_chat_history', currentSid(),
                text || '(see attachments)', JSON.stringify(history));
            } catch (e) {}
          }
        }
      }
      } catch (err) {
        // Never let a handler crash kill the user's session silently.
        try {
          window.dispatchEvent(new CustomEvent('lm-canvas-toast', {
            detail: { msg: `composer error: ${err && err.message || err}`, kind:'err' },
          }));
        } catch (e) {}
      }
    };
    window.addEventListener('lm-composer-action', handler);
    return () => window.removeEventListener('lm-composer-action', handler);
  }, [userNodes, bumpGraph, model]);

  // ─── Founder demand #15: chat-streaming signals from the bridge.
  // CRITICAL: pair every connect with a disconnect on unmount or listeners
  // accumulate every render and crash the app after ~2 minutes.
  React.useEffect(() => {
    const b = window.archhub;
    if (!b) return;
    const onChunk = (sid, piece) => {
      // Find the most recent streaming assistant message in the focused AI node.
      const conv = (LM_GRAPH.nodes || []).find(n => n.cat === 'ai' && (n.messages || []).some(m => m.streaming))
                || (LM_GRAPH.nodes || []).find(n => n.cat === 'ai');
      if (!conv) return;
      const msgs = conv.messages || [];
      const lastIx = msgs.findIndex(m => m.streaming);
      if (lastIx >= 0) {
        msgs[lastIx] = { ...msgs[lastIx], text: (msgs[lastIx].text === '…' ? '' : msgs[lastIx].text) + piece };
      } else {
        msgs.push({ me:false, text:piece, streaming:true, time:new Date().toISOString().slice(11,16) });
      }
      bumpGraph();
    };
    const onDone = (sid) => {
      (LM_GRAPH.nodes || []).forEach(n => {
        (n.messages || []).forEach(m => { if (m.streaming) delete m.streaming; });
      });
      saveCurrentGraph(); bumpGraph();
    };
    const onError = (sid, err) => {
      console.warn('[studio-lm] chat error:', err);
      onDone(sid);
    };
    // Founder demand 2026-05-15: real reasoning trace, not the mocked
    // "reasoning · 4 steps" block. Each provider step lands on the
    // streaming assistant message under m.reasoning[].
    const onReasoning = (sid, step) => {
      if (!step) return;
      const conv = (LM_GRAPH.nodes || []).find(n => n.cat === 'ai' && (n.messages || []).some(m => m.streaming))
                || (LM_GRAPH.nodes || []).find(n => n.cat === 'ai');
      if (!conv) return;
      const msgs = conv.messages || [];
      let lastIx = msgs.findIndex(m => m.streaming);
      if (lastIx < 0) {
        // No streaming bubble yet — create one so reasoning has a home.
        msgs.push({ me:false, text:'', streaming:true,
                     reasoning:[step],
                     time:new Date().toISOString().slice(11,16) });
      } else {
        const cur = msgs[lastIx];
        const r = Array.isArray(cur.reasoning) ? cur.reasoning.slice() : [];
        r.push(step);
        msgs[lastIx] = { ...cur, reasoning: r };
      }
      bumpGraph();
    };
    const wires = [];
    const wire = (name, fn) => {
      try { if (b[name] && typeof b[name].connect === 'function') { b[name].connect(fn); wires.push(() => { try { b[name].disconnect(fn); } catch (e) {} }); } } catch (e) {}
    };
    // Founder demand 2026-05-15: TRIGGER nodes go live. When the
    // backend GraphTriggerScheduler fires a trigger, cook every node
    // downstream of it. Toast shows the user what fired.
    const onTrigger = (sid, nodeId, payloadJson) => {
      let payload = {};
      try { payload = JSON.parse(payloadJson || '{}') || {}; } catch (e) {}
      try {
        window.dispatchEvent(new CustomEvent('lm-canvas-toast', {
          detail: { msg: `trigger: ${payload.kind || 'fired'} → ${nodeId}`, kind:'info' },
        }));
      } catch (e) {}
      // BFS forward from trigger node, cook each downstream sink.
      const wires = LM_GRAPH.wires || [];
      const visited = new Set([nodeId]);
      const queue = [nodeId];
      while (queue.length) {
        const cur = queue.shift();
        wires.forEach(w => {
          if (w.from && w.from[0] === cur && !visited.has(w.to[0])) {
            visited.add(w.to[0]);
            queue.push(w.to[0]);
            try { bridgeCall('run_node', w.to[0]); } catch (e) {}
          }
        });
      }
    };
    // Founder bug 2026-05-15: agent_step froze the UI on the main thread.
    // It's now threaded server-side + emits agent_step_done(result_json).
    // Replay the LLM's tool calls as composer actions here.
    const onAgentStep = (resultJson) => {
      let step = null;
      try { step = JSON.parse(resultJson || '{}'); } catch (e) { return; }
      if (!step || !Array.isArray(step.actions)) return;
      step.actions.forEach((a) => {
        const tool = a && a.tool, args = (a && a.args) || {};
        let action = null;
        if (tool === 'spawn_node') {
          action = { command:'spawn_host_chat', family:args.family,
                      text:(step.text || ''), fresh_conversation:true };
        } else if (tool === 'add_wire') {
          action = { command:'wire', src_node:args.src_node, src_port:args.src_port,
                      dst_node:args.dst_node, dst_port:args.dst_port };
        } else if (tool === 'set_node_param') {
          action = { command:'set_node_param', node_id:args.node_id,
                      key:args.key, value:args.value };
        } else if (tool === 'run_node') {
          action = { command:'run_node', node_id:args.node_id };
        } else if (tool === 'run_workflow') {
          action = { command:'run_workflow' };
        } else if (tool === 'chat') {
          action = { command:'chat', text:args.text || step.text || '' };
        }
        if (action) {
          try {
            window.dispatchEvent(new CustomEvent('lm-composer-action', {
              detail: { action, raw: step.text || '', focusId: focusId },
            }));
          } catch (e) {}
        }
      });
    };
    // Connector-op result. run_connector_op is fire-and-forget + threaded;
    // it emits connector_op_done(result_json). The result carries op_id
    // but not node_id, so we FIFO-match against the pending queue per
    // op_id (window.__archhub_op_pending — populated by the run handler).
    const onConnectorOpDone = (resultJson) => {
      let res = null;
      try { res = JSON.parse(resultJson || '{}'); } catch (e) { return; }
      if (!res) return;
      const pend = window.__archhub_op_pending || {};
      const queue = pend[res.op_id] || [];
      const nodeId = queue.shift();
      pend[res.op_id] = queue;
      const node = (LM_GRAPH.nodes || []).find(
        n => n.id === nodeId || (!nodeId && n.op_id === res.op_id && n.op_running));
      if (node) {
        node.op_result = res;
        node.op_running = false;
        saveCurrentGraph();
      }
      bumpGraph();
    };
    // Dynamic dropdown options resolved (cascading host params). Stash by
    // req_id + fire lm-param-options so the waiting ParamField fills in.
    const onParamOptions = (json) => {
      let p = null;
      try { p = JSON.parse(json || '{}'); } catch (e) { return; }
      if (!p || !p.req_id) return;
      window.__archhub_param_opts = window.__archhub_param_opts || {};
      window.__archhub_param_opts[p.req_id] = p;
      try {
        window.dispatchEvent(new CustomEvent('lm-param-options',
          { detail: { req_id: p.req_id } }));
      } catch (e) {}
    };
    // AI-minted custom node registered — splice into the library so it
    // appears under MY NODES immediately, no relaunch.
    const onNodeCreated = (json) => {
      let r = null;
      try { r = JSON.parse(json || '{}'); } catch (e) { return; }
      try {
        window.dispatchEvent(new CustomEvent('lm-node-created', { detail: r }));
      } catch (e) {}
      if (r && r.ok && r.spec) {
        if (!LM_CUSTOM_NODES.find(n => n.type === r.spec.type)) {
          LM_CUSTOM_NODES.push(r.spec);
        }
        try {
          window.dispatchEvent(new CustomEvent('lm-canvas-toast', {
            detail: { msg: `node created: ${r.spec.title || r.type}`, kind:'info' },
          }));
        } catch (e) {}
        bumpGraph();
      }
    };
    wire('chat_chunk',     onChunk);
    wire('chat_reasoning', onReasoning);
    wire('chat_done',      onDone);
    wire('chat_error',     onError);
    wire('trigger_fired',  onTrigger);
    wire('agent_step_done', onAgentStep);
    wire('connector_op_done', onConnectorOpDone);
    wire('param_options_ready', onParamOptions);
    wire('node_created',   onNodeCreated);
    return () => { for (const off of wires) { try { off(); } catch (e) {} } };
  }, [bumpGraph, focusId]);

  // ─── Founder demand 2026-05-15: run a connector-op node. The node's
  // ConnectorOpBody fires `lm-run-connector-op` with the node id; we
  // serialise its params, call the threaded bridge slot, and queue the
  // node id so connector_op_done can route the result back.
  React.useEffect(() => {
    const onRunOp = (ev) => {
      const nodeId = ev && ev.detail && ev.detail.node_id;
      if (!nodeId) return;
      const node = (LM_GRAPH.nodes || []).find(n => n.id === nodeId);
      if (!node || !node.op_id) return;
      const params = {};
      (node.params || []).forEach(p => {
        if (p && p.k != null && p.v !== '' && p.v != null) params[p.k] = p.v;
      });
      node.op_running = true;
      node.op_result = null;
      bumpGraph();
      window.__archhub_op_pending = window.__archhub_op_pending || {};
      const q = window.__archhub_op_pending[node.op_id] || [];
      q.push(node.id);
      window.__archhub_op_pending[node.op_id] = q;
      try {
        bridgeCall('run_connector_op', node.op_id, JSON.stringify(params));
      } catch (e) {
        node.op_running = false;
        node.op_result = { ok:false, error:'bridge call failed' };
        bumpGraph();
      }
    };
    window.addEventListener('lm-run-connector-op', onRunOp);
    return () => window.removeEventListener('lm-run-connector-op', onRunOp);
  }, [bumpGraph]);

  // ─── Founder demand #4: clicking gear opens the NATIVE PyQt SettingsDialog.
  // The in-React Settings overlay is only a fallback when the bridge isn't wired.
  const openSettingsResolved = React.useCallback(() => {
    const ok = bridgeCall('open_settings');
    if (ok === null) setSettingsOpen(true); // fallback for preview/standalone
  }, []);

  // F2-B wiring: sidebar buttons + workspace pills fire custom events; StudioLM
  // is the single place that converts them into bridge calls. Anything missing
  // a bridge slot is a no-op (bridgeCall returns null), so the UI doesn't break.
  const [wirePromote, setWirePromote] = React.useState(null);
  React.useEffect(() => {
    const onNewSession = () => createSession('untitled');
    const onSpawnSkill = async (ev) => {
      const skill = ev && ev.detail;
      if (!skill) return;
      // Load the skill's graph (saved as JSON via save_as_skill).
      // bridgeAsync — QWebChannel slots resolve async; the old sync
      // bridgeJson always returned null here, so spawning a skill
      // silently no-op'd (founder bug 2026-05-18).
      const blob = await bridgeAsync('load_skill', skill.id || skill.name);
      if (blob && Array.isArray(blob.nodes)) {
        const offset = (LM_GRAPH.nodes || []).length * 6;
        blob.nodes.forEach(n => {
          n.x = (n.x || 0) + 40 + offset;
          n.y = (n.y || 0) + 40 + offset;
          n._user = true;
        });
        setUserNodes(ns => [...ns, ...blob.nodes]);
        if (Array.isArray(blob.wires)) {
          LM_GRAPH.wires = [...(LM_GRAPH.wires || []), ...blob.wires];
        }
        saveCurrentGraph(); bumpGraph();
      }
    };
    const onShareCanvas = () => {
      const sid = openId;
      const sess = sid && (LM_SESSIONS || []).find(s => s.id === sid);
      const name = (sess && sess.title) || 'canvas';
      bridgeCall('save_as_skill', name, JSON.stringify({
        nodes: LM_GRAPH.nodes || [], wires: LM_GRAPH.wires || [],
      }));
    };
    const onWirePromote = (ev) => {
      const d = ev && ev.detail;
      if (!d || !d.from) return;
      setWirePromote(d);
    };
    // Founder demand 2026-05-16: "+ new node" in the node library opens
    // the AI node-smith modal.
    const onNewNode = () => setAiNodeOpen(true);
    window.addEventListener('lm-new-session', onNewSession);
    window.addEventListener('lm-spawn-skill', onSpawnSkill);
    window.addEventListener('lm-share-canvas', onShareCanvas);
    window.addEventListener('lm-wire-promote', onWirePromote);
    window.addEventListener('lm-new-node', onNewNode);
    return () => {
      window.removeEventListener('lm-new-session', onNewSession);
      window.removeEventListener('lm-spawn-skill', onSpawnSkill);
      window.removeEventListener('lm-share-canvas', onShareCanvas);
      window.removeEventListener('lm-wire-promote', onWirePromote);
      window.removeEventListener('lm-new-node', onNewNode);
    };
  }, [createSession, openId, bumpGraph]);

  // Close the wire-promote palette by clicking outside or pressing Esc.
  React.useEffect(() => {
    if (!wirePromote) return;
    const close = () => setWirePromote(null);
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [wirePromote]);

  // Founder direction: Home page is a dashboard (sessions list + composer).
  // No node library shows up here — there's no canvas to drop onto. The
  // sidebar only appears once a session is open. On Home a thin 44px icon
  // rail stays so Settings is still reachable.
  return (
    <div style={{
      width:'100%', height:'100%', background:LM.bg, color:LM.ink,
      fontFamily:LM.sans, fontSize:13, lineHeight:1.5,
      display:'grid',
      // Sidebar widths: 292px (icon rail + Nodes panel) when canvas open,
      // 56px (icon rail only) on Home. Bumped from 44 → 56 so the icons
      // breathe and the rail reads as a proper nav strip instead of a
      // bald sliver. Founder bug 2026-05-14: "strip wasn't presented
      // properly" — too narrow + no separator + icons cramped.
      gridTemplateColumns: session ? '292px 1fr' : '56px 1fr',
      gridTemplateRows:'1fr 22px',
      overflow:'hidden', position:'relative',
    }}>
      {session ? (
        <Sidebar
          panel={panel} setPanel={setPanel}
          openId={openId} onOpen={openSession}
          onHome={() => setOpenId(null)} onSettings={openSettingsResolved}
          addNodeFromLibrary={addNodeFromLibrary} setFocusId={setFocusId}/>
      ) : (
        <aside style={{
          gridColumn:'1', gridRow:'1',
          background:LM.bgPanel,
          borderRight:`1px solid ${LM.line}`,
          boxShadow:`inset -1px 0 0 ${LM.lineSoft}`,
          minHeight:0, overflow:'hidden',
        }}>
          <IconRail panel={panel} setPanel={() => {}}
            onHome={() => setOpenId(null)} onSettings={openSettingsResolved}/>
        </aside>
      )}
      {session
        ? <Workspace
            session={session} model={model}
            openTabs={openTabs} setOpenId={openSession} closeTab={closeTab}
            setPickerOpen={setPickerOpen}
            setSettingsOpen={openSettingsResolved}
            setLibraryOpen={setLibraryOpen}
            focusId={focusId} setFocusId={setFocusId}
            userNodes={userNodes} addNodeFromLibrary={addNodeFromLibrary}
            removeUserNode={removeUserNode}
            bumpGraph={bumpGraph}
            graphBump={graphBump}
            onHome={() => setOpenId(null)}
            onCreateSession={createSession}/>
        : <Home onOpen={openSession} model={model} setPickerOpen={setPickerOpen}
                  onCreateSession={createSession}
                  onSettings={openSettingsResolved}/>}
      <ServerStrip session={session} model={model} setSettingsOpen={openSettingsResolved}/>
      {pickerOpen && <ModelPicker setModel={setModel} onClose={() => setPickerOpen(false)} model={model}/>}
      {settingsOpen && <Settings onClose={() => setSettingsOpen(false)}/>}
      {libraryOpen && <NodeLibrary onClose={() => setLibraryOpen(false)} addNodeFromLibrary={addNodeFromLibrary}/>}
      {createNodeOpen && <CreateNodeModal spec={typeof createNodeOpen === 'object' ? createNodeOpen : null} onClose={() => setCreateNodeOpen(false)}/>}
      {aiNodeOpen && <AINodeModal onClose={() => setAiNodeOpen(false)}
        addNodeFromLibrary={addNodeFromLibrary}/>}
      {firstRunProfile && <FirstRunProfile onClose={() => setFirstRunProfile(false)}/>}
      {wirePromote && <WirePromotePalette detail={wirePromote}
        onClose={() => setWirePromote(null)}
        onPick={(libItem) => {
          // Spawn the node near the drop, then auto-wire source → first matching input.
          const fromType = wirePromote.from && wirePromote.from.type;
          const node = addNodeFromLibrary(libItem, (wirePromote.x || 200) - 110, (wirePromote.y || 200) - 30);
          const matchIn = (node.ins || []).find(i => !fromType || i.t === fromType || i.t === 'any')
                       || (node.ins || [])[0];
          if (matchIn && wirePromote.from) {
            LM_GRAPH.wires = [...(LM_GRAPH.wires || []), {
              from: [wirePromote.from.nodeId, wirePromote.from.sockId],
              to:   [node.id, matchIn.id],
            }];
            saveCurrentGraph(); bumpGraph();
          }
          setWirePromote(null);
        }}/>}
      <style>{`
        @keyframes lmPulse { 0%,100% { opacity:.4 } 50% { opacity:1 } }
        @keyframes lmCaret { 50% { opacity: 0 } }
        @keyframes lmDash  { to { stroke-dashoffset: -16 } }
        @keyframes lmSlideIn { from { transform: translateX(8px); opacity: 0 } to { transform: translateX(0); opacity: 1 } }
        @keyframes lmPop    { from { transform: scale(.92); opacity: 0 } to { transform: scale(1); opacity: 1 } }
        @keyframes lmHintFade { 0% { opacity: 0; transform: translate(-50%, 8px) } 8% { opacity: 1; transform: translate(-50%, 0) } 80% { opacity: 1; transform: translate(-50%, 0) } 100% { opacity: 0; transform: translate(-50%, -4px) } }
      `}</style>
    </div>
  );
};

// ─── Founder demand #13: modal for /createnode. Posts spec to bridge. ──
// Lightweight label widget used inside CreateNodeModal. (Previously lived
// inside the Settings overlay we removed.)
const SField = ({ label }) => (
  <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.1em', marginBottom:4, marginTop:6 }}>
    {(label || '').toUpperCase()}
  </div>
);

const CreateNodeModal = ({ spec, onClose }) => {
  const [type, setType] = React.useState((spec && spec.type) || '');
  const [cat, setCat] = React.useState((spec && spec.cat) || 'filter');
  const [inputs, setInputs] = React.useState((spec && (spec.inputs || []).join(', ')) || '');
  const [outputs, setOutputs] = React.useState((spec && (spec.outputs || []).join(', ')) || '');
  const submit = () => {
    const payload = {
      type: type || ('custom.' + Date.now().toString(36)),
      category: cat,
      display_name: type || 'Custom',
      inputs: inputs.split(',').map(s => s.trim()).filter(Boolean),
      outputs: outputs.split(',').map(s => s.trim()).filter(Boolean),
    };
    bridgeJson('create_node_type', JSON.stringify(payload));
    onClose();
  };
  return (
    <div onClick={onClose} style={{ position:'absolute', inset:0, background:'rgba(0,0,0,.55)', zIndex:60, display:'grid', placeItems:'center' }}>
      <div onClick={e => e.stopPropagation()} style={{ width:460, background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:10, padding:22, boxShadow:'0 30px 80px rgba(0,0,0,.6)' }}>
        <div style={{ fontFamily:LM.serif, fontSize:20, marginBottom:14 }}>Create custom node</div>
        <SField label="Type ID"  value={type}    /><input value={type}    onChange={e=>setType(e.target.value)}    placeholder="my.filter"        style={modalInput()}/>
        <SField label="Category" value={cat}     /><input value={cat}     onChange={e=>setCat(e.target.value)}     placeholder="filter"           style={modalInput()}/>
        <SField label="Inputs (comma)"  value={inputs}/><input value={inputs}  onChange={e=>setInputs(e.target.value)}  placeholder="walls, view"      style={modalInput()}/>
        <SField label="Outputs (comma)" value={outputs}/><input value={outputs} onChange={e=>setOutputs(e.target.value)} placeholder="filtered"         style={modalInput()}/>
        <div style={{ display:'flex', gap:8, marginTop:14, justifyContent:'flex-end' }}>
          <button onClick={onClose} style={smallBtn()}>Cancel</button>
          <button onClick={submit}  style={smallBtn(true)}>Create</button>
        </div>
      </div>
    </div>
  );
};
const modalInput = () => ({
  width:'100%', padding:'8px 11px', background:LM.bg, border:`1px solid ${LM.line}`,
  borderRadius:5, color:LM.ink, fontFamily:LM.mono, fontSize:12, outline:'none',
  marginBottom:10,
});

// ─── AI Node Smith modal ──────────────────────────────────────────────
// Founder demand 2026-05-16: "user should be able to custom-make nodes on
// a whim using AI." The user types what they want in plain English; the
// bridge's `ai_create_node` slot asks an LLM (agents/node_smith) to design
// a full node spec — typed I/O + a sandboxed `execute()` body — registers
// it as a REAL node, and emits `node_created`. We listen for that signal
// (re-broadcast as `lm-node-created`) and surface the result.
const AINODE_EXAMPLES = [
  'Keep only walls taller than 3 meters',
  'Count elements grouped by level',
  'Round every number in a list to 2 decimals',
  'Filter rooms whose area is below a threshold',
];
const AINodeModal = ({ onClose, addNodeFromLibrary }) => {
  const [desc, setDesc] = React.useState('');
  const [phase, setPhase] = React.useState('idle'); // idle|working|done|error
  const [result, setResult] = React.useState(null);
  const [err, setErr] = React.useState('');
  const reqRef = React.useRef('');

  // Listen for the bridge's node_created signal (StudioLM re-dispatches it
  // as `lm-node-created`). Match on req_id so a stale modal can't catch
  // someone else's result.
  React.useEffect(() => {
    const onCreated = (ev) => {
      const r = (ev && ev.detail) || {};
      if (!reqRef.current || r.req_id !== reqRef.current) return;
      if (r.ok && r.spec) { setResult(r.spec); setPhase('done'); }
      else { setErr(r.error || 'the AI could not design that node'); setPhase('error'); }
    };
    window.addEventListener('lm-node-created', onCreated);
    return () => window.removeEventListener('lm-node-created', onCreated);
  }, []);

  // Esc closes (unless mid-generation — don't lose a pending request silently).
  React.useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && phase !== 'working') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [phase, onClose]);

  const generate = () => {
    const d = desc.trim();
    if (!d || phase === 'working') return;
    if (!window.archhub) {
      setErr('bridge not connected — relaunch the app to use AI node creation');
      setPhase('error');
      return;
    }
    const reqId = 'mk_' + Math.random().toString(36).slice(2, 10);
    reqRef.current = reqId;
    setErr(''); setResult(null); setPhase('working');
    bridgeCall('ai_create_node', reqId, d);
    // Safety net: LLM design can take a while, but never hang the modal.
    setTimeout(() => {
      if (reqRef.current === reqId) {
        setPhase((p) => {
          if (p === 'working') { setErr('timed out waiting for the AI — try again'); return 'error'; }
          return p;
        });
      }
    }, 90000);
  };

  const addToCanvas = () => {
    if (result && addNodeFromLibrary) {
      addNodeFromLibrary({ _custom_node: result, cat:'custom' });
    }
    onClose();
  };
  const reset = () => { reqRef.current = ''; setPhase('idle'); setResult(null); setErr(''); };

  return (
    <div onClick={() => phase !== 'working' && onClose()} style={{
      position:'absolute', inset:0, background:'rgba(0,0,0,.6)', zIndex:62,
      display:'grid', placeItems:'center',
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        width:520, maxWidth:'94%', background:LM.bgPanel,
        border:`1px solid ${LM.line}`, borderRadius:10, padding:'20px 22px',
        boxShadow:'0 30px 80px rgba(0,0,0,.6)',
      }}>
        <div style={{ display:'flex', alignItems:'center', gap:9, marginBottom:4 }}>
          <span style={{ color:LM.blue, fontSize:16 }}>⊕</span>
          <span style={{ fontFamily:LM.serif, fontSize:21, letterSpacing:'-0.01em' }}>Create a node with AI</span>
          <div style={{ flex:1 }}/>
          <button onClick={onClose} disabled={phase==='working'} style={{
            width:24, height:24, padding:0, border:`1px solid ${LM.line}`,
            background:'transparent', borderRadius:5,
            cursor: phase==='working' ? 'default' : 'pointer',
            color:LM.inkSoft, fontSize:12, opacity: phase==='working' ? 0.4 : 1,
          }}>✕</button>
        </div>
        <div style={{ fontFamily:LM.sans, fontSize:12, color:LM.inkSoft, marginBottom:14, lineHeight:1.5 }}>
          Describe the node in plain words. The AI designs its typed inputs,
          outputs and logic, then registers it in your library.
        </div>

        {phase === 'idle' && (
          <>
            <textarea autoFocus value={desc} onChange={e => setDesc(e.target.value)}
              onKeyDown={e => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') generate(); }}
              placeholder="e.g. keep only the walls taller than 3 metres"
              rows={3} style={{
                width:'100%', padding:'10px 12px', background:LM.bg,
                border:`1px solid ${LM.line}`, borderRadius:6, color:LM.ink,
                fontFamily:LM.sans, fontSize:13, outline:'none', resize:'vertical',
                lineHeight:1.5,
              }}/>
            <div style={{ display:'flex', flexWrap:'wrap', gap:5, marginTop:9 }}>
              {AINODE_EXAMPLES.map((ex, i) => (
                <button key={i} onClick={() => setDesc(ex)} style={{
                  padding:'4px 9px', borderRadius:11, cursor:'pointer',
                  background:LM.bgSoft, border:`1px solid ${LM.line}`,
                  color:LM.inkSoft, fontFamily:LM.sans, fontSize:11,
                }}>{ex}</button>
              ))}
            </div>
            <div style={{ display:'flex', gap:8, marginTop:16, justifyContent:'flex-end', alignItems:'center' }}>
              <span style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, marginRight:'auto' }}>⌘↵ to generate</span>
              <button onClick={onClose} style={smallBtn()}>Cancel</button>
              <button onClick={generate} disabled={!desc.trim()} style={{
                ...smallBtn(true),
                opacity: desc.trim() ? 1 : 0.45,
                cursor: desc.trim() ? 'pointer' : 'default',
              }}>Generate node</button>
            </div>
          </>
        )}

        {phase === 'working' && (
          <div style={{
            padding:'26px 0', display:'flex', flexDirection:'column',
            alignItems:'center', gap:12,
          }}>
            <div style={{ display:'flex', gap:5 }}>
              {[0,1,2].map(i => (
                <span key={i} style={{
                  width:7, height:7, borderRadius:'50%', background:LM.blue,
                  animation:`lmPulse 1s ${i*0.16}s infinite`,
                }}/>
              ))}
            </div>
            <div style={{ fontFamily:LM.sans, fontSize:12.5, color:LM.inkSoft }}>
              Designing your node…
            </div>
            <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, maxWidth:340, textAlign:'center', lineHeight:1.5 }}>
              “{desc.trim()}”
            </div>
          </div>
        )}

        {phase === 'done' && result && (
          <>
            <div style={{
              background:LM.bg, border:`1px solid ${LM.line}`,
              borderLeft:`2px solid ${LM.blue}`, borderRadius:6, padding:'12px 14px',
            }}>
              <div style={{ display:'flex', alignItems:'center', gap:8 }}>
                <span style={{ fontSize:16, color:LM.blue }}>{result.icon || '⊕'}</span>
                <span style={{ fontFamily:LM.sans, fontSize:14, fontWeight:600, color:LM.ink }}>
                  {result.title || result.type}
                </span>
                <span style={{
                  fontFamily:LM.mono, fontSize:8.5, color:LM.inkMuted,
                  border:`1px solid ${LM.line}`, borderRadius:3, padding:'1px 5px',
                  letterSpacing:'0.06em', textTransform:'uppercase',
                }}>{result.category || 'transform'}</span>
              </div>
              {result.description && (
                <div style={{ fontFamily:LM.sans, fontSize:11.5, color:LM.inkSoft, marginTop:6, lineHeight:1.5 }}>
                  {result.description}
                </div>
              )}
              <div style={{ display:'flex', gap:16, marginTop:9, fontFamily:LM.mono, fontSize:9.5 }}>
                <span style={{ color:LM.cyan }}>
                  → {(result.inputs || []).map(p => (p && p.name) || p).join(', ') || 'none'}
                </span>
                <span style={{ color:LM.ok }}>
                  ← {(result.outputs || []).map(p => (p && p.name) || p).join(', ') || 'none'}
                </span>
              </div>
              <div style={{ fontFamily:LM.mono, fontSize:8, color:LM.inkDim, marginTop:7, letterSpacing:'0.04em' }}>
                {result.type} · saved to your library
              </div>
            </div>
            <div style={{ display:'flex', gap:8, marginTop:16, justifyContent:'flex-end' }}>
              <button onClick={reset} style={smallBtn()}>Create another</button>
              <button onClick={addToCanvas} style={smallBtn(true)}>Add to canvas</button>
            </div>
          </>
        )}

        {phase === 'error' && (
          <>
            <div style={{
              background:LM.bg, border:`1px solid ${LM.err}`,
              borderLeft:`2px solid ${LM.err}`, borderRadius:6, padding:'12px 14px',
              fontFamily:LM.mono, fontSize:11, color:LM.err, lineHeight:1.55,
            }}>
              ✕ {err}
            </div>
            <div style={{ display:'flex', gap:8, marginTop:16, justifyContent:'flex-end' }}>
              <button onClick={onClose} style={smallBtn()}>Cancel</button>
              <button onClick={reset} style={smallBtn(true)}>Try again</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

// ─── First-run profile capture ────────────────────────────────────────
// Roadmap #P0 2026-05-17: on first launch capture firm / role /
// discipline → profile.json via bridge.save_profile. Shows exactly
// once (StudioLM gates it on get_profile being empty). Skippable —
// Skip writes {skipped:true} so it never nags again.
const FirstRunProfile = ({ onClose }) => {
  const [firm, setFirm] = React.useState('');
  const [role, setRole] = React.useState('');
  const [discipline, setDiscipline] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const ROLES = ['Architect', 'Engineer', 'BIM Manager', 'Designer',
                 'Project Manager', 'Drafter', 'Student', 'Other'];
  const DISCIPLINES = ['Architecture', 'Structural', 'MEP', 'Civil',
                       'Interior Design', 'Landscape', 'Urban Design', 'Other'];
  const filled = !!(firm.trim() || role || discipline);
  const save = (payload) => {
    if (saving) return;
    setSaving(true);
    bridgeAsync('save_profile', JSON.stringify(payload)).then(() => onClose());
  };
  return (
    <div style={{ position:'absolute', inset:0, background:'rgba(0,0,0,.6)',
      zIndex:64, display:'grid', placeItems:'center' }}>
      <div style={{ width:440, maxWidth:'94%', background:LM.bgPanel,
        border:`1px solid ${LM.line}`, borderRadius:10, padding:'22px 24px',
        boxShadow:'0 30px 80px rgba(0,0,0,.6)' }}>
        <div style={{ fontFamily:LM.serif, fontStyle:'italic', fontSize:24,
          color:LM.accent, marginBottom:4 }}>Welcome to ArchHub</div>
        <div style={{ fontFamily:LM.sans, fontSize:12, color:LM.inkSoft,
          marginBottom:18, lineHeight:1.5 }}>
          A couple of details about your practice — tailors host suggestions
          and defaults. Change them any time in Settings.
        </div>
        <SField label="Firm / company"/>
        <input value={firm} onChange={e => setFirm(e.target.value)}
          placeholder="e.g. Foster + Partners" style={modalInput()}/>
        <SField label="Your role"/>
        <select value={role} onChange={e => setRole(e.target.value)}
          style={{ ...modalInput(), cursor:'pointer' }}>
          <option value="">— select —</option>
          {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
        </select>
        <SField label="Discipline"/>
        <select value={discipline} onChange={e => setDiscipline(e.target.value)}
          style={{ ...modalInput(), cursor:'pointer' }}>
          <option value="">— select —</option>
          {DISCIPLINES.map(d => <option key={d} value={d}>{d}</option>)}
        </select>
        <div style={{ display:'flex', gap:8, marginTop:16,
          justifyContent:'flex-end', alignItems:'center' }}>
          <button onClick={() => save({ skipped:true })} disabled={saving}
            style={smallBtn()}>Skip</button>
          <button
            onClick={() => save({ firm:firm.trim(), role, discipline,
              captured_at:new Date().toISOString() })}
            disabled={saving || !filled}
            style={{ ...smallBtn(true),
              opacity:(filled && !saving) ? 1 : 0.45,
              cursor:(filled && !saving) ? 'pointer' : 'default' }}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
};

// ─── Wire-promote palette ─────────────────────────────────────────────
// Fired when a wire is dropped on empty canvas (lm-wire-promote). Shows the
// nodes from LM_LIBRARY whose first declared input accepts the dragged
// output's type. Picking one spawns + auto-wires the connection.
const WirePromotePalette = ({ detail, onClose, onPick }) => {
  const fromType = (detail && detail.from && detail.from.type) || '';
  // Use LM_NODE_TEMPLATES to peek at each library item's first input type.
  const candidates = [];
  (LM_LIBRARY || []).forEach(group => {
    (group.items || []).forEach(it => {
      const tmpl = (typeof LM_NODE_TEMPLATES !== 'undefined' && LM_NODE_TEMPLATES[it.id]) || {};
      const firstIn = (it.ins || tmpl.ins || [])[0];
      if (!firstIn) return;
      if (!fromType || firstIn.t === fromType || firstIn.t === 'any' || fromType === 'any') {
        candidates.push({ ...it, cat: group.cat });
      }
    });
  });
  // Position the palette near the drop coord, clamped to the viewport.
  const W = 280, H = 320;
  const px = Math.min(window.innerWidth - W - 12, Math.max(8, (detail.x || 200) - W/2));
  const py = Math.min(window.innerHeight - H - 12, Math.max(8, (detail.y || 200) + 8));
  return (
    <div onClick={onClose} style={{
      position:'fixed', inset:0, background:'transparent', zIndex:70,
    }}>
      <div onClick={e => e.stopPropagation()} data-no-pan style={{
        position:'absolute', left:px, top:py, width:W, maxHeight:H,
        background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:8,
        boxShadow:'0 20px 50px rgba(0,0,0,.55)', display:'flex', flexDirection:'column',
        overflow:'hidden', animation:'lmSlideIn .12s ease-out',
      }}>
        <div style={{ padding:'8px 12px', borderBottom:`1px solid ${LM.lineSoft}`, fontFamily:LM.mono, fontSize:9, letterSpacing:'0.12em', color:LM.inkMuted }}>
          PROMOTE WIRE → {fromType || 'any'}
        </div>
        <div className="ah-scroll" style={{ overflow:'auto', padding:'4px 4px 6px', flex:1 }}>
          {candidates.length === 0 ? (
            <div style={{ padding:'18px 12px', fontFamily:LM.serif, fontStyle:'italic', fontSize:12, color:LM.inkMuted }}>
              No compatible nodes for {fromType || 'any'}.
            </div>
          ) : candidates.map((c, i) => (
            <button key={i} onClick={() => onPick(c)} style={{
              width:'100%', display:'flex', alignItems:'center', gap:8, padding:'6px 10px',
              background:'transparent', border:0, borderRadius:5, cursor:'pointer',
              color:LM.ink, fontFamily:LM.sans, fontSize:12, textAlign:'left',
            }}
            onMouseEnter={e => e.currentTarget.style.background = LM.bgHover}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
              <span style={{ width:5, height:5, borderRadius:'50%', background:(catMeta(c.cat) || {}).col || LM.inkSoft, flexShrink:0 }}/>
              <span style={{ flex:1, fontFamily:LM.mono, fontSize:11.5 }}>{c.title}</span>
              <span style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.04em' }}>{c.cat}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};

// ─── Node templates ─ default I/O & params per library item ───
// keyed by library item id; falls back to a per-category template.
const LM_NODE_TEMPLATES = window.__archhub_LM_NODE_TEMPLATES = window.__archhub_LM_NODE_TEMPLATES || {
  // hosts
  h_revit:    { w:220, h:118, outs:[{ id:'view', label:'active view', t:'view' }, { id:'sel', label:'selection', t:'selection' }] },
  h_rhino:    { w:220, h:118, outs:[{ id:'mesh', label:'mesh', t:'view' }, { id:'crv', label:'curves', t:'walls' }] },
  h_blender:  { w:220, h:118, outs:[{ id:'mesh', label:'mesh', t:'view' }, { id:'sk', label:'sketch', t:'view' }] },
  h_speckle:  { w:240, h:140, ins:[{ id:'sheet', label:'sheet', t:'sheets' }, { id:'view', label:'model', t:'view' }], outs:[{ id:'commit', label:'commit', t:'trace' }] },
  h_dropbox:  { w:220, h:90, ins:[{ id:'file', label:'file', t:'file' }], outs:[{ id:'url', label:'url', t:'file' }] },
  h_outlook:  { w:220, h:90, outs:[{ id:'inbox', label:'inbox', t:'file' }] },
  h_autocad:  { w:220, h:118, outs:[{ id:'drawing', label:'drawing', t:'view' }, { id:'sel', label:'selection', t:'selection' }] },
  h_max:      { w:220, h:118, outs:[{ id:'scene', label:'scene', t:'view' }, { id:'sel', label:'selection', t:'selection' }] },
  h_teams:    { w:220, h:90, outs:[{ id:'channels', label:'channels', t:'file' }] },
  h_word:     { w:220, h:90, ins:[{ id:'doc', label:'doc', t:'file' }], outs:[{ id:'text', label:'text', t:'any' }] },
  h_excel:    { w:220, h:90, ins:[{ id:'wb', label:'workbook', t:'file' }], outs:[{ id:'range', label:'range', t:'any' }] },
  h_powerpoint:{ w:220, h:90, ins:[{ id:'deck', label:'deck', t:'file' }], outs:[{ id:'slides', label:'slides', t:'any' }] },
  h_photoshop:{ w:220, h:90, ins:[{ id:'psd', label:'psd', t:'file' }], outs:[{ id:'export', label:'export', t:'file' }] },
  h_illustrator:{ w:220, h:90, ins:[{ id:'ai', label:'ai', t:'file' }], outs:[{ id:'svg', label:'svg', t:'file' }] },
  h_indesign: { w:220, h:90, ins:[{ id:'indd', label:'indd', t:'file' }], outs:[{ id:'pdf', label:'pdf', t:'file' }] },
  h_notion:   { w:220, h:90, params:[{ k:'db_or_page', v:'', type:'text' }], outs:[{ id:'pages', label:'pages', t:'any' }] },
  h_lmstudio: { w:220, h:90, params:[{ k:'endpoint', v:'http://127.0.0.1:1234/v1', type:'text' }, { k:'model', v:'qwen2.5-coder:32b', type:'text' }], outs:[{ id:'completion', label:'completion', t:'completion' }] },
  h_antigravity:{ w:220, h:90, params:[{ k:'task', v:'open https://...', type:'text' }], outs:[{ id:'result', label:'result', t:'any' }] },
  // reads
  r_walls:    { w:220, h:96, ins:[{ id:'view', label:'view', t:'view' }], outs:[{ id:'walls', label:'walls', t:'walls' }] },
  r_doors:    { w:220, h:96, ins:[{ id:'view', label:'view', t:'view' }], outs:[{ id:'doors', label:'doors', t:'doors' }] },
  r_windows:  { w:220, h:96, ins:[{ id:'view', label:'view', t:'view' }], outs:[{ id:'wins', label:'windows', t:'doors' }] },
  r_sheets:   { w:220, h:96, outs:[{ id:'sheets', label:'sheets', t:'sheets' }] },
  r_views:    { w:220, h:96, outs:[{ id:'views', label:'views', t:'view' }] },
  r_selection:{ w:220, h:96, outs:[{ id:'sel', label:'selection', t:'selection' }] },
  // filters
  f_type:     { w:220, h:118, ins:[{ id:'in', label:'in', t:'walls' }], outs:[{ id:'out', label:'matches', t:'walls' }], params:[{ k:'type', v:'Generic 200', type:'select' }] },
  f_cat:      { w:220, h:118, ins:[{ id:'in', label:'in', t:'walls' }], outs:[{ id:'out', label:'matches', t:'walls' }], params:[{ k:'category', v:'Walls', type:'select' }] },
  f_level:    { w:220, h:118, ins:[{ id:'in', label:'in', t:'walls' }], outs:[{ id:'out', label:'matches', t:'walls' }], params:[{ k:'level', v:'L03', type:'select' }] },
  f_param:    { w:220, h:118, ins:[{ id:'in', label:'in', t:'walls' }], outs:[{ id:'out', label:'matches', t:'walls' }], params:[{ k:'param', v:'length', type:'select' }, { k:'op', v:'>=', type:'select' }, { k:'value', v:800, min:0, max:5000, step:50, type:'slider' }] },
  f_pred:     { w:220, h:118, ins:[{ id:'in', label:'in', t:'walls' }], outs:[{ id:'out', label:'matches', t:'walls' }], params:[{ k:'predicate', v:'el => el.length > 800', type:'text' }] },
  // transforms
  t_setp:     { w:240, h:122, ins:[{ id:'in', label:'in', t:'walls' }], outs:[{ id:'out', label:'out', t:'walls' }], params:[{ k:'parameter', v:'Mark', type:'select' }, { k:'value', v:'auto', type:'text' }] },
  t_move:     { w:220, h:122, ins:[{ id:'in', label:'in', t:'walls' }], outs:[{ id:'out', label:'out', t:'walls' }], params:[{ k:'dx', v:0, min:-5000, max:5000, step:50, type:'slider' }, { k:'dy', v:0, min:-5000, max:5000, step:50, type:'slider' }] },
  t_group:    { w:220, h:118, ins:[{ id:'in', label:'in', t:'walls' }], outs:[{ id:'out', label:'groups', t:'walls' }], params:[{ k:'key', v:'type', type:'select' }] },
  t_sort:     { w:220, h:118, ins:[{ id:'in', label:'in', t:'walls' }], outs:[{ id:'out', label:'sorted', t:'walls' }], params:[{ k:'key', v:'length', type:'select' }, { k:'order', v:'desc', type:'select' }] },
  // annotate
  a_dims:     { w:260, h:200, ins:[{ id:'walls', label:'walls', t:'walls' }, { id:'view', label:'view', t:'view' }], outs:[{ id:'dims', label:'dimensions', t:'dims' }], params:[{ k:'scale', v:'1:50', type:'select' }, { k:'align', v:'parallel', type:'select' }, { k:'offset_mm', v:240, min:60, max:600, step:10, type:'slider' }] },
  a_tags:     { w:220, h:140, ins:[{ id:'els', label:'elements', t:'walls' }], outs:[{ id:'tags', label:'tags', t:'dims' }], params:[{ k:'family', v:'Tag · Default', type:'select' }, { k:'leader', v:'on', type:'select' }] },
  a_text:     { w:220, h:118, ins:[{ id:'at', label:'point', t:'view' }], outs:[{ id:'text', label:'text', t:'dims' }], params:[{ k:'body', v:'placed automatically', type:'text' }] },
  a_rooms:    { w:220, h:118, ins:[{ id:'view', label:'view', t:'view' }], outs:[{ id:'tags', label:'tags', t:'dims' }] },
  // compose
  c_sched:    { w:260, h:180, ins:[{ id:'in', label:'rows', t:'walls' }], outs:[{ id:'sheet', label:'sheet', t:'sheets' }], params:[{ k:'group_by', v:'type', type:'select' }, { k:'columns', v:'type, level, length', type:'text' }] },
  c_sheet:    { w:220, h:118, ins:[{ id:'views', label:'views', t:'view' }], outs:[{ id:'sheet', label:'sheet', t:'sheets' }], params:[{ k:'layout', v:'A1 · portrait', type:'select' }] },
  c_legend:   { w:220, h:118, ins:[{ id:'items', label:'items', t:'walls' }], outs:[{ id:'sheet', label:'legend', t:'sheets' }] },
  // logic
  l_if:       { w:220, h:118, ins:[{ id:'in', label:'in', t:'walls' }], outs:[{ id:'yes', label:'yes', t:'walls' }, { id:'no', label:'no', t:'walls' }], params:[{ k:'predicate', v:'count > 0', type:'text' }] },
  l_switch:   { w:220, h:140, ins:[{ id:'in', label:'in', t:'walls' }], outs:[{ id:'a', label:'a', t:'walls' }, { id:'b', label:'b', t:'walls' }, { id:'c', label:'c', t:'walls' }] },
  l_loop:     { w:220, h:118, ins:[{ id:'list', label:'list', t:'walls' }], outs:[{ id:'each', label:'each', t:'walls' }] },
  l_merge:    { w:220, h:118, ins:[{ id:'a', label:'a', t:'walls' }, { id:'b', label:'b', t:'walls' }], outs:[{ id:'out', label:'out', t:'walls' }] },
  // ai
  i_conv:     { w:320, h:240, ins:[{ id:'ctx', label:'context', t:'any' }], outs:[{ id:'response', label:'response', t:'completion' }], messages:[], params:[{ k:'model', v:'Claude Sonnet 4.5', type:'select' }, { k:'system', v:'You are an architect copilot.', type:'text' }] },
  i_think:    { w:280, h:160, ins:[{ id:'ctx', label:'context', t:'view' }], outs:[{ id:'intent', label:'intent', t:'intent' }], params:[{ k:'model', v:'Claude Sonnet 4.5', type:'select' }, { k:'temperature', v:0.7, min:0, max:2, step:0.05, type:'slider' }, { k:'max_tokens', v:4096, min:256, max:32000, step:256, type:'slider' }, { k:'system', v:'concise + technical', type:'text' }] },
  i_vis:      { w:240, h:140, ins:[{ id:'img', label:'image', t:'file' }], outs:[{ id:'desc', label:'description', t:'intent' }], params:[{ k:'model', v:'Claude Sonnet 4.5 vision', type:'select' }] },
  i_match:    { w:240, h:140, ins:[{ id:'intent', label:'intent', t:'intent' }], outs:[{ id:'skill', label:'skill', t:'trace' }], params:[{ k:'top_k', v:3, min:1, max:10, step:1, type:'slider' }] },
  i_embed:    { w:220, h:118, ins:[{ id:'text', label:'text', t:'intent' }], outs:[{ id:'vec', label:'vector', t:'trace' }] },
  // output
  o_skill:    { w:240, h:140, ins:[{ id:'trace', label:'trace', t:'trace' }], params:[{ k:'name', v:'untitled skill', type:'text' }] },
  o_pdf:      { w:240, h:118, ins:[{ id:'sheet', label:'sheet', t:'sheets' }], params:[{ k:'destination', v:'/Tower-A/exports', type:'text' }] },
  o_spk:      { w:220, h:118, ins:[{ id:'in', label:'in', t:'view' }], params:[{ k:'branch', v:'main', type:'select' }] },
  o_email:    { w:220, h:118, ins:[{ id:'body', label:'body', t:'intent' }], params:[{ k:'to', v:'team@…', type:'text' }] },
  o_notify:   { w:220, h:96, ins:[{ id:'msg', label:'message', t:'intent' }] },
  // category fallbacks
  __cat_host:      { w:220, h:118, outs:[{ id:'out', label:'output', t:'view' }] },
  __cat_read:      { w:220, h:96, ins:[{ id:'in', label:'view', t:'view' }], outs:[{ id:'out', label:'result', t:'walls' }] },
  __cat_filter:    { w:220, h:118, ins:[{ id:'in', label:'in', t:'walls' }], outs:[{ id:'out', label:'matches', t:'walls' }] },
  __cat_transform: { w:220, h:122, ins:[{ id:'in', label:'in', t:'walls' }], outs:[{ id:'out', label:'out', t:'walls' }] },
  __cat_annotate:  { w:220, h:140, ins:[{ id:'els', label:'elements', t:'walls' }], outs:[{ id:'out', label:'output', t:'dims' }] },
  __cat_compose:   { w:220, h:140, ins:[{ id:'in', label:'in', t:'walls' }], outs:[{ id:'sheet', label:'sheet', t:'sheets' }] },
  __cat_logic:     { w:220, h:118, ins:[{ id:'in', label:'in', t:'walls' }], outs:[{ id:'a', label:'yes', t:'walls' }, { id:'b', label:'no', t:'walls' }] },
  __cat_ai:        { w:240, h:140, ins:[{ id:'ctx', label:'context', t:'view' }], outs:[{ id:'out', label:'output', t:'intent' }] },
  __cat_output:    { w:220, h:96, ins:[{ id:'in', label:'in', t:'intent' }] },
  __cat_trigger:   { w:220, h:118, outs:[{ id:'fire', label:'fire', t:'event' }] },
};

// ──────────────────────── SIDEBAR (icon rail + active panel) ────────────────────────
const Sidebar = ({ panel, setPanel, openId, onOpen, onHome, onSettings, addNodeFromLibrary, setFocusId }) => (
  <aside style={{
    gridColumn:'1', gridRow:'1',
    display:'grid', gridTemplateColumns:'56px 1fr',
    background:LM.bgPanel, borderRight:`1px solid ${LM.line}`,
    overflow:'hidden', minHeight:0,
  }}>
    <IconRail panel={panel} setPanel={setPanel} onHome={onHome} onSettings={onSettings}/>
    {/* Founder direction 2026-05-14: sidebar has Nodes library ONLY.
        Sessions live on Home page. Skills + Search were empty shells —
        purged. The icon rail still shows Nodes + Home + Settings. */}
    <NodesPanel addNodeFromLibrary={addNodeFromLibrary}/>
  </aside>
);

const IconRail = ({ panel, setPanel, onHome, onSettings }) => {
  // Founder direction 2026-05-14: Nodes is the only mid-rail item; Home
  // pin lives at the top, Share + Settings at the bottom. Rail uses
  // 56px width so icons + labels read without crowding.
  const items = [
    { id:'nodes',  title:'Nodes',  svg:(
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <rect x="3" y="3" width="7" height="7" rx="1"/>
        <rect x="14" y="3" width="7" height="7" rx="1"/>
        <rect x="3" y="14" width="7" height="7" rx="1"/>
        <rect x="14" y="14" width="7" height="7" rx="1"/>
      </svg>
    ) },
  ];
  return (
    <div style={{
      width:'100%', height:'100%',
      background:LM.bgDeep, borderRight:`1px solid ${LM.line}`,
      display:'flex', flexDirection:'column', alignItems:'stretch',
      padding:'12px 0 10px', gap:2,
    }}>
      <RailIcon active onClick={onHome} title="Home" label="home">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none">
          <path d="M3 21 V12 a9 9 0 0 1 18 0 V21" stroke={LM.accent} strokeWidth="2" strokeLinecap="round"/>
          <circle cx="12" cy="8.5" r="1.6" fill={LM.accent}/>
        </svg>
      </RailIcon>
      <div style={{ height:8 }}/>
      {items.map(it => (
        <RailIcon key={it.id} active={panel === it.id}
          onClick={() => setPanel(it.id)} title={it.title} label={it.title.toLowerCase()}>
          {it.svg}
        </RailIcon>
      ))}
      <div style={{ flex:1 }}/>
      {/* Subtle divider before footer actions */}
      <div style={{ height:1, margin:'6px 10px 4px', background:LM.line }}/>
      <RailIcon title="Share canvas as skill" label="share"
        onClick={() => { try { window.dispatchEvent(new CustomEvent('lm-share-canvas')); } catch (e) {} }}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/>
          <path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>
        </svg>
      </RailIcon>
      <RailIcon onClick={onSettings} title="Settings" label="settings">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.01a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.01a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </svg>
      </RailIcon>
    </div>
  );
};

const RailIcon = ({ active, onClick, title, label, children }) => {
  const [hover, setHover] = React.useState(false);
  return (
    <button onClick={onClick} title={title} style={{
      width:'100%', minHeight:48, padding:'4px 0', border:0,
      background: active ? LM.accentDim : (hover ? LM.bgSoft : 'transparent'),
      color: active ? LM.accent : (hover ? LM.ink : LM.inkSoft),
      cursor:'pointer',
      display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', gap:3,
      position:'relative',
      transition:'background .12s, color .12s',
    }}
    onMouseEnter={() => setHover(true)}
    onMouseLeave={() => setHover(false)}>
      {active && <span style={{ position:'absolute', left:0, top:8, bottom:8, width:2, background:LM.accent, borderRadius:2 }}/>}
      <span style={{ display:'grid', placeItems:'center' }}>{children}</span>
      {label && <span style={{
        fontFamily:LM.mono, fontSize:8.5, letterSpacing:'0.06em',
        textTransform:'uppercase',
        color: active ? LM.accent : (hover ? LM.inkSoft : LM.inkMuted),
        lineHeight:1,
      }}>{label}</span>}
    </button>
  );
};

const ChatsPanel = ({ openId, onOpen }) => {
  // Founder demand: search, more menu (rename/fork/duplicate/delete), new chat.
  // The "New Folder" button is removed — folders aren't a real model.
  const [q, setQ] = React.useState('');
  const [menuFor, setMenuFor] = React.useState(null); // {sid, type:'item'|'panel'}
  const [, bump] = React.useReducer(x => x + 1, 0);
  const sessions = React.useMemo(() => {
    const items = LM_SESSIONS || [];
    if (!q) return items;
    const needle = q.toLowerCase();
    return items.filter(s => (s.title || '').toLowerCase().includes(needle));
  }, [q, openId]);
  const onNewChat = () => {
    // StudioLM listens for lm-new-session and calls createSession().
    try { window.dispatchEvent(new CustomEvent('lm-new-session')); } catch (e) {}
  };
  const handleAction = (action, sid) => {
    setMenuFor(null);
    // Unified async path — see runSessionAction. Fixes fork + duplicate
    // (were sync no-ops on the null-returning sync bridge) and the
    // formerly-missing duplicate_session slot; rename/delete now act on
    // the real bridge result instead of an optimistic guess.
    runSessionAction(action, sid, {
      onOpen: onOpen, openId: openId,
      openAfterCreate: true, afterChange: bump,
    });
  };
  return (
    <div style={{ display:'flex', flexDirection:'column', overflow:'hidden', minHeight:0, position:'relative' }}>
      {/* Panel header */}
      <div style={{ padding:'12px 12px 10px', display:'flex', alignItems:'center', gap:8 }}>
        <span style={{ fontFamily:LM.sans, fontSize:14, fontWeight:600, letterSpacing:'-0.005em', color:LM.ink }}>Chats</span>
        <div style={{ flex:1 }}/>
        <button title="More" onClick={() => setMenuFor(m => m && m.type === 'panel' ? null : { sid: openId, type:'panel' })} style={panelIconBtn()}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>
        </button>
        <button title="New chat" onClick={onNewChat} style={panelIconBtn()}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 1 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/></svg>
        </button>
      </div>

      {/* Search */}
      <div style={{ padding:'0 10px 8px' }}>
        <div style={{
          display:'flex', alignItems:'center', gap:8, padding:'6px 10px',
          background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:6,
          color:LM.inkMuted, fontSize:12.5,
        }}>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search chats…" style={{
            flex:1, border:0, background:'transparent', color:LM.ink, fontSize:12.5, outline:'none', fontFamily:LM.sans,
          }}/>
        </div>
      </div>

      {/* Sessions list */}
      <div className="ah-scroll" style={{ flex:1, overflow:'auto', padding:'0 6px 8px', minHeight:0 }}>
        {sessions.map(s => {
          const a = openId === s.id;
          const sm = stateMeta(s.state);
          return (
            <div key={s.id} style={{ position:'relative', display:'flex', alignItems:'stretch', marginBottom:1 }}>
              <button onClick={() => onOpen(s.id)} style={{
                flex:1, padding:'7px 9px', borderRadius:5, border:0,
                background: a ? LM.bgSoft : 'transparent', color: a ? LM.ink : LM.inkSoft,
                cursor:'pointer', textAlign:'left', position:'relative',
                display:'flex', alignItems:'center', gap:8,
                fontFamily:LM.sans, fontSize:13, minWidth:0,
              }}
              onMouseEnter={e => !a && (e.currentTarget.style.background = LM.bgHover)}
              onMouseLeave={e => !a && (e.currentTarget.style.background = 'transparent')}>
                <span style={{
                  width:6, height:6, borderRadius:'50%', background: sm.col, flexShrink:0,
                  boxShadow: sm.pulse ? `0 0 0 2px ${sm.col}22` : 'none',
                  animation: sm.pulse ? 'lmPulse 1.2s infinite' : 'none',
                }}/>
                <span style={{ flex:1, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', fontWeight: a ? 500 : 400 }}>{s.title}</span>
              </button>
              <button title="More"
                onClick={(e) => { e.stopPropagation(); setMenuFor(m => m && m.sid === s.id ? null : { sid: s.id, type:'item' }); }}
                style={{
                  width:22, padding:0, border:0, background:'transparent',
                  color: a ? LM.ink : LM.inkMuted, cursor:'pointer',
                  display:'grid', placeItems:'center',
                }}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="19" cy="12" r="1.4"/></svg>
              </button>
              {menuFor && menuFor.sid === s.id && (
                <ChatItemMenu onClose={() => setMenuFor(null)} onAction={(a) => handleAction(a, s.id)}/>
              )}
            </div>
          );
        })}
        {sessions.length === 0 && (
          <div style={{ padding:'18px 12px', fontFamily:LM.serif, fontStyle:'italic', fontSize:13, color:LM.inkMuted }}>
            {q ? `No chats match "${q}".` : 'No chats yet.'}
          </div>
        )}
      </div>

      {menuFor && menuFor.type === 'panel' && openId && (
        <div style={{ position:'absolute', top:42, right:10, zIndex:30 }}>
          <ChatItemMenu onClose={() => setMenuFor(null)} onAction={(a) => handleAction(a, openId)}/>
        </div>
      )}

      {/* User */}
      <div style={{
        margin:8, padding:'7px 10px', borderRadius:6,
        background:LM.bgSoft, border:`1px solid ${LM.line}`,
        display:'flex', alignItems:'center', gap:9,
      }}>
        <div style={{ width:22, height:22, borderRadius:'50%', background:'#d8c5a8', display:'grid', placeItems:'center', fontSize:11, color:'#5a4a2a', fontWeight:700 }}>F</div>
        <div style={{ flex:1, lineHeight:1.1, minWidth:0 }}>
          <div style={{ fontSize:12, fontWeight:500, color:LM.ink }}>Fargaly</div>
          <div style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.08em' }}>BYO · CLOUD</div>
        </div>
      </div>
    </div>
  );
};

const ChatItemMenu = ({ onClose, onAction }) => {
  React.useEffect(() => {
    const dismiss = (e) => { if (!e.target.closest('[data-chat-menu]')) onClose(); };
    const onKey = (e) => e.key === 'Escape' && onClose();
    setTimeout(() => document.addEventListener('click', dismiss), 0);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('click', dismiss);
      document.removeEventListener('keydown', onKey);
    };
  }, [onClose]);
  const items = [
    { k:'rename',    t:'Rename' },
    { k:'fork',      t:'Fork' },
    { k:'duplicate', t:'Duplicate' },
    { sep:true },
    { k:'delete',    t:'Delete', danger:true },
  ];
  return (
    <div data-chat-menu onClick={e => e.stopPropagation()} style={{
      position:'absolute', right:0, top:'100%', marginTop:2, zIndex:30,
      background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:6,
      boxShadow:'0 12px 28px rgba(0,0,0,.55)', padding:4, minWidth:140,
      animation:'lmSlideIn .12s ease-out',
    }}>
      {items.map((it, i) => it.sep ? (
        <div key={i} style={{ height:1, background:LM.lineSoft, margin:'3px 4px' }}/>
      ) : (
        <button key={i} onClick={() => onAction(it.k)} style={{
          width:'100%', padding:'5px 10px', border:0, background:'transparent',
          borderRadius:4, cursor:'pointer', textAlign:'left',
          color: it.danger ? LM.err : LM.ink, fontFamily:LM.sans, fontSize:12,
        }}
        onMouseEnter={e => e.currentTarget.style.background = LM.bgHover}
        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
          {it.t}
        </button>
      ))}
    </div>
  );
};

const panelIconBtn = () => ({
  width:22, height:22, padding:0, border:0, background:'transparent',
  borderRadius:4, cursor:'pointer', color:LM.inkSoft,
  display:'grid', placeItems:'center',
});

// ─── Nodes panel — primary drag source ───
const NodesPanel = ({ addNodeFromLibrary }) => {
  const [q, setQ] = React.useState('');
  // Founder direction: ALL collapsed by default. Most-used row shown
  // first; user expands a category only when they need it.
  const [openCats, setOpenCats] = React.useState(() => Object.fromEntries(Object.keys(CAT).map(k => [k, false])));
  // Connector hosts collapse independently of the abstract categories.
  const [openConn, setOpenConn] = React.useState({});
  const [ctxMenu, setCtxMenu] = React.useState(null); // {x, y}
  const onPanelContextMenu = (e) => {
    e.preventDefault(); e.stopPropagation();
    setCtxMenu({ x: e.clientX, y: e.clientY });
  };
  React.useEffect(() => {
    if (!ctxMenu) return;
    const close = () => setCtxMenu(null);
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    document.addEventListener('click', close);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('click', close);
      document.removeEventListener('keydown', onKey);
    };
  }, [ctxMenu]);
  // Track usage so "Most used" section bubbles up the user's habits.
  // Persisted on window so it survives StudioLM remounts during hydration.
  if (!window.__archhub_node_usage) {
    try { window.__archhub_node_usage = JSON.parse(localStorage.getItem('archhub_node_usage') || '{}') || {}; }
    catch { window.__archhub_node_usage = {}; }
  }
  const usage = window.__archhub_node_usage;
  // ── Pinned favorites — founder demand 2026-05-17 "customize what
  // shows". Pin any node to a ★ PINNED section at the top. Persisted in
  // localStorage; window-cached so it survives StudioLM remounts.
  const [custTick, setCustTick] = React.useState(0);
  if (!window.__archhub_node_pins) {
    try { window.__archhub_node_pins = JSON.parse(localStorage.getItem('archhub_node_pins') || '[]') || []; }
    catch { window.__archhub_node_pins = []; }
  }
  const pins = window.__archhub_node_pins;   // [{it, cat:{col,icon,label}, spawnCat}]
  const isPinned = (id) => pins.some(p => p && p.it && p.it.id === id);
  const togglePin = (item, catMeta, spawnCat) => {
    if (!item || !item.id) return;
    const i = pins.findIndex(p => p && p.it && p.it.id === item.id);
    if (i >= 0) pins.splice(i, 1);
    else pins.push({ it: item,
      cat: { col: catMeta.col, icon: catMeta.icon, label: catMeta.label },
      spawnCat });
    try { localStorage.setItem('archhub_node_pins', JSON.stringify(pins)); } catch (e) {}
    setCustTick(t => t + 1);
  };
  // ── Hidden categories — founder demand 2026-05-17 "customize what
  // NOT to show". Right-click a category header to hide it; restore
  // via the panel context menu. localStorage-backed.
  if (!window.__archhub_node_hidden) {
    try { window.__archhub_node_hidden = JSON.parse(localStorage.getItem('archhub_node_hidden') || '[]') || []; }
    catch { window.__archhub_node_hidden = []; }
  }
  const hidden = window.__archhub_node_hidden;
  const isHidden = (cat) => hidden.indexOf(cat) >= 0;
  const toggleHidden = (cat) => {
    const i = hidden.indexOf(cat);
    if (i >= 0) hidden.splice(i, 1); else hidden.push(cat);
    try { localStorage.setItem('archhub_node_hidden', JSON.stringify(hidden)); } catch (e) {}
    setCustTick(t => t + 1);
  };
  const showAllHidden = () => {
    hidden.splice(0, hidden.length);
    try { localStorage.removeItem('archhub_node_hidden'); } catch (e) {}
    setCustTick(t => t + 1);
  };
  // ── Sort — within each category: library order, or A→Z by title.
  const [sortMode, setSortMode] = React.useState('default'); // 'default' | 'az'
  const collapseAll = () => setOpenCats({});
  const expandAll = () => setOpenCats(Object.fromEntries(Object.keys(CAT).map(k => [k, true])));
  const recordUse = (item, cat) => {
    try {
      usage[item.id] = (usage[item.id] || 0) + 1;
      localStorage.setItem('archhub_node_usage', JSON.stringify(usage));
    } catch (e) {}
    addNodeFromLibrary({ ...item, cat });
  };
  // Top-5 most-used items across all categories.
  const mostUsed = React.useMemo(() => {
    const rows = [];
    (LM_LIBRARY || []).forEach(group => (group.items || []).forEach(it => {
      const n = usage[it.id] || 0;
      if (n > 0) rows.push({ it, cat: group.cat, count: n });
    }));
    return rows.sort((a, b) => b.count - a.count).slice(0, 5);
  }, [q, openCats]);
  return (
    <div onContextMenu={onPanelContextMenu}
      style={{ display:'flex', flexDirection:'column', overflow:'hidden', minHeight:0 }}>
      <div style={{ padding:'12px 12px 10px', display:'flex', alignItems:'center', gap:8 }}>
        <span style={{ fontFamily:LM.sans, fontSize:14, fontWeight:600, color:LM.ink }}>Nodes</span>
        <span style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.08em' }}>
          drag · right-click
        </span>
        <div style={{ flex:1 }}/>
        {/* Founder demand 2026-05-17: NO "+ new node" button here. Custom
            node creation lives in the node library ("+ add node" on the
            canvas toolbar → NodeLibrary modal → "Create with AI"). One
            entry point for adding nodes, not a scatter of buttons. */}
      </div>
      {ctxMenu && (
        <div data-no-pan onClick={e => e.stopPropagation()} style={{
          position:'fixed', left: ctxMenu.x, top: ctxMenu.y, zIndex: 200,
          background: LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius: 6,
          boxShadow: '0 12px 30px rgba(0,0,0,.5)', padding: 4, minWidth: 180,
          fontFamily: LM.sans, fontSize: 12.5,
        }}>
          {[
            { label:'Expand all',   fn: () => { expandAll(); setCtxMenu(null); } },
            { label:'Collapse all', fn: () => { collapseAll(); setCtxMenu(null); } },
            ...(hidden.length > 0 ? [
              { sep:true },
              { label:`Show ${hidden.length} hidden categor${hidden.length === 1 ? 'y' : 'ies'}`,
                fn: () => { showAllHidden(); setCtxMenu(null); } },
            ] : []),
            { sep:true },
            { label:'Clear most-used', fn: () => {
                try { localStorage.removeItem('archhub_node_usage'); } catch (e) {}
                window.__archhub_node_usage = {};
                setCtxMenu(null);
              } },
          ].map((it, i) => it.sep
            ? <div key={i} style={{ height:1, background: LM.line, margin:'4px 0' }}/>
            : (
              <button key={i} onClick={it.fn} style={{
                width:'100%', textAlign:'left', padding:'7px 10px', border:0,
                background:'transparent', color: LM.ink, cursor:'pointer',
                fontFamily: LM.sans, fontSize: 12.5, borderRadius: 4,
              }}
              onMouseEnter={e => e.currentTarget.style.background = LM.bgHover}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                {it.label}
              </button>
            ))}
        </div>
      )}

      <div style={{ padding:'0 10px 8px' }}>
        <div style={{
          display:'flex', alignItems:'center', gap:8, padding:'6px 10px',
          background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:6,
        }}>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke={LM.inkMuted} strokeWidth="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
          <input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="Search nodes…" style={{
            flex:1, border:0, background:'transparent', color:LM.ink, fontSize:12, outline:'none', fontFamily:LM.sans,
          }}/>
          {/* Sort toggle — library order ⇄ A→Z. Founder demand 2026-05-17. */}
          <span onClick={() => setSortMode(m => m === 'az' ? 'default' : 'az')}
            title={sortMode === 'az' ? 'Sorted A–Z — click for default order' : 'Sort A–Z'}
            style={{
              cursor:'pointer', fontFamily:LM.mono, fontSize:9, flexShrink:0,
              padding:'2px 6px', borderRadius:4, letterSpacing:'0.06em',
              color: sortMode === 'az' ? LM.accent : LM.inkMuted,
              background: sortMode === 'az' ? LM.accentSoft : 'transparent',
            }}>A–Z</span>
        </div>
      </div>

      <div className="ah-scroll" style={{ flex:1, overflow:'auto', padding:'0 6px 8px', minHeight:0 }}>
        {/* ── PINNED — favorites the user starred (hover a node → ★).
            Founder demand 2026-05-17: "customize what shows". ── */}
        {pins.length > 0 && (() => {
          const shown = q
            ? pins.filter(p => p && p.it &&
                ((p.it.title || '') + ' ' + (p.it.sub || ''))
                  .toLowerCase().includes(q.toLowerCase()))
            : pins;
          if (shown.length === 0) return null;
          return (
            <div style={{ marginBottom:4 }}>
              <div style={{ padding:'5px 7px', color:LM.warn, fontFamily:LM.mono,
                fontSize:9.5, letterSpacing:'0.14em' }}>★ PINNED · {shown.length}</div>
              <div style={{ display:'flex', flexDirection:'column', gap:1, paddingLeft:6 }}>
                {shown.map(p => (
                  <NodeLibItem key={'pin-' + p.it.id} it={p.it}
                    cat={p.cat || _CAT_FALLBACK}
                    pinned={true}
                    onPin={() => togglePin(p.it, p.cat || _CAT_FALLBACK, p.spawnCat)}
                    onAdd={() => addNodeFromLibrary({ ...p.it,
                      cat: p.spawnCat || (p.cat && p.cat.label) || 'read' })}/>
                ))}
              </div>
            </div>
          );
        })()}
        {/* ── MY NODES + SKILLS — PINNED to the top of the library.
            Founder demand 2026-05-17: your own custom nodes and saved
            skills sit above the stock pipeline categories. ── */}
        {(() => {
          const mine = q
            ? (LM_CUSTOM_NODES || []).filter(c =>
                ((c.title || '') + ' ' + (c.description || '') + ' ' + (c.type || ''))
                  .toLowerCase().includes(q.toLowerCase()))
            : (LM_CUSTOM_NODES || []);
          if (mine.length === 0) return null;
          return (
            <div style={{ marginBottom:4 }}>
              <div style={{
                padding:'5px 7px', color:LM.inkSoft, fontFamily:LM.mono,
                fontSize:9.5, letterSpacing:'0.14em',
              }}>⊕ MY NODES · {mine.length}</div>
              <div style={{ display:'flex', flexDirection:'column', gap:1, paddingLeft:6 }}>
                {mine.map(c => {
                  const it = {
                    id: 'cn:' + c.type,
                    title: c.title || c.type,
                    sub: c.description || c.type,
                    _custom_node: c,
                  };
                  return (
                    <NodeLibItem key={c.type} it={it}
                      cat={{ col:LM.blue, icon:'⊕', label:'custom' }}
                      pinned={isPinned(it.id)}
                      onPin={() => togglePin(it, { col:LM.blue, icon:'⊕', label:'custom' }, 'custom')}
                      onAdd={() => {
                        try {
                          usage[it.id] = (usage[it.id] || 0) + 1;
                          localStorage.setItem('archhub_node_usage', JSON.stringify(usage));
                        } catch (e) {}
                        addNodeFromLibrary({ ...it, cat:'custom' });
                      }}/>
                  );
                })}
              </div>
            </div>
          );
        })()}
        {(() => {
          const skills = q
            ? (LM_SAVED_SKILLS || []).filter(s =>
                ((s.name || '') + ' ' + (s.args || ''))
                  .toLowerCase().includes(q.toLowerCase()))
            : (LM_SAVED_SKILLS || []);
          if (skills.length === 0) return null;
          return (
            <div style={{ marginBottom:4 }}>
              <div style={{
                padding:'5px 7px', color:LM.inkSoft, fontFamily:LM.mono,
                fontSize:9.5, letterSpacing:'0.14em',
              }}>★ SKILLS · {skills.length}</div>
              <div style={{ display:'flex', flexDirection:'column', gap:1, paddingLeft:6 }}>
                {skills.map(s => {
                  const it = {
                    id: 'sk:' + s.id,
                    title: s.name || s.id || 'skill',
                    sub: (s.args ? s.args + ' · ' : '')
                       + ((s.runs ? s.runs + ' runs' : 'saved template')),
                  };
                  return (
                    <NodeLibItem key={s.id} it={it} draggable={false}
                      cat={{ col:LM.warn, icon:'★', label:'skill' }}
                      onAdd={() => {
                        try { window.dispatchEvent(new CustomEvent('lm-spawn-skill', { detail: s })); }
                        catch (e) {}
                      }}/>
                  );
                })}
              </div>
            </div>
          );
        })()}
        {/* Most-used section — top 5 across all categories. Hidden until
            the user actually adds a node from the library. Persisted in
            localStorage so it survives relaunches. */}
        {!q && mostUsed.length > 0 && (
          <div style={{ marginBottom:8 }}>
            <div style={{
              padding:'5px 7px', color:LM.inkSoft, fontFamily:LM.mono,
              fontSize:9.5, letterSpacing:'0.14em',
            }}>
              ★ MOST USED · {mostUsed.length}
            </div>
            <div style={{ display:'flex', flexDirection:'column', gap:1, paddingLeft:6 }}>
              {mostUsed.map(({ it, cat, count }) => (
                <NodeLibItem key={'mu-'+it.id} it={{ ...it, sub:`${it.sub} · used ${count}×` }}
                  cat={catMeta(cat)} onAdd={() => recordUse(it, cat)}/>
              ))}
            </div>
          </div>
        )}
        {/* ── Pipeline super-sections — SOURCES → SHAPE → AI → SEND.
            Founder demand 2026-05-17: the library's organising logic is
            graph flow, not a flat 10-category dump. Each stage holds its
            collapsible categories. ── */}
        {PIPELINE.map(pipe => {
          const stage = pipe.cats
            .map(cat => (LM_LIBRARY || []).find(g => g.cat === cat))
            .filter(Boolean)
            // Hidden categories drop out entirely (restore via the panel
            // right-click menu). A search query overrides hide.
            .filter(group => q || !isHidden(group.cat))
            .map(group => {
              let items = q
                ? (group.items || []).filter(i =>
                    (i.title + ' ' + i.sub).toLowerCase().includes(q.toLowerCase()))
                : (group.items || []);
              if (sortMode === 'az') {
                items = [...items].sort((a, b) =>
                  (a.title || '').localeCompare(b.title || ''));
              }
              return { group, items };
            })
            .filter(x => x.items.length > 0);
          if (stage.length === 0) return null;
          return (
            <div key={pipe.id} style={{ marginBottom:2 }}>
              <div style={{ display:'flex', alignItems:'center', gap:8, padding:'9px 7px 3px' }}>
                <span style={{ fontFamily:LM.mono, fontSize:10, fontWeight:600,
                  color:LM.ink, letterSpacing:'0.18em' }}>{pipe.label}</span>
                <span style={{ fontFamily:LM.mono, fontSize:8.5, color:LM.inkMuted,
                  letterSpacing:'0.06em' }}>{pipe.hint}</span>
                <div style={{ flex:1, height:1, background:LM.line }}/>
              </div>
              {stage.map(({ group, items }) => {
                const c = catMeta(group.cat);
                const open = q ? true : !!openCats[group.cat];
                return (
                  <div key={group.cat} style={{ marginBottom:4 }}>
                    <button onClick={() => setOpenCats(o => ({ ...o, [group.cat]: !o[group.cat] }))}
                      onContextMenu={(e) => { e.preventDefault(); e.stopPropagation();
                        toggleHidden(group.cat); }}
                      title="Click to expand · right-click to hide this category" style={{
                      width:'100%', display:'flex', alignItems:'center', gap:7, padding:'5px 7px',
                      background:'transparent', border:0, borderRadius:4, cursor:'pointer',
                      color:LM.inkSoft, fontFamily:LM.mono, fontSize:9.5, letterSpacing:'0.14em',
                      textAlign:'left',
                    }}
                    onMouseEnter={e => e.currentTarget.style.background = LM.bgHover}
                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                      <span style={{ width:9, color:LM.inkMuted, transition:'transform .12s', display:'inline-block', transform: open ? 'rotate(90deg)' : 'rotate(0deg)' }}>▸</span>
                      <span style={{ color: c.col, fontSize:10 }}>{c.icon}</span>
                      <span style={{ flex:1, color:c.col }}>{c.label}</span>
                      <span style={{ color:LM.inkMuted, fontSize:9 }}>{items.length}</span>
                    </button>
                    {open && (
                      <div style={{ display:'flex', flexDirection:'column', gap:1, paddingLeft:6 }}>
                        {items.map(it => <NodeLibItem key={it.id} it={it} cat={c}
                          pinned={isPinned(it.id)}
                          onPin={() => togglePin(it, c, group.cat)}
                          onAdd={() => recordUse(it, group.cat)}/>)}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          );
        })}

        {/* ── Connector operations — all 116 ops across 16 hosts, grouped
            by host. Hydrated from bridge.get_connectors(). Each op is a
            spawnable node carrying its typed inputs + op_id. ── */}
        {(LM_CONNECTORS || []).length > 0 && (
          <div style={{ marginTop:10, marginBottom:4 }}>
            <div style={{
              padding:'5px 7px', color:LM.inkSoft, fontFamily:LM.mono,
              fontSize:9.5, letterSpacing:'0.14em',
            }}>⚡ CONNECTORS · {(LM_CONNECTORS || []).length} hosts</div>
            {(LM_CONNECTORS || []).map(conn => {
              const col = CONNECTOR_COLORS[conn.host] || LM.cyan;
              const ops = q
                ? (conn.ops || []).filter(o =>
                    ((o.label || '') + ' ' + (o.op_id || '') + ' ' + (o.description || ''))
                      .toLowerCase().includes(q.toLowerCase()))
                : (conn.ops || []);
              if (ops.length === 0) return null;
              const open = q ? true : !!openConn[conn.host];
              return (
                <div key={conn.host} style={{ marginBottom:4 }}>
                  <button onClick={() => setOpenConn(o => ({ ...o, [conn.host]: !o[conn.host] }))} style={{
                    width:'100%', display:'flex', alignItems:'center', gap:7, padding:'5px 7px',
                    background:'transparent', border:0, borderRadius:4, cursor:'pointer',
                    color:LM.inkSoft, fontFamily:LM.mono, fontSize:9.5, letterSpacing:'0.1em',
                    textAlign:'left',
                  }}
                  onMouseEnter={e => e.currentTarget.style.background = LM.bgHover}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                    <span style={{ width:9, color:LM.inkMuted, transition:'transform .12s', display:'inline-block', transform: open ? 'rotate(90deg)' : 'rotate(0deg)' }}>▸</span>
                    <span style={{ width:6, height:6, borderRadius:2, background:col }}/>
                    <span style={{ flex:1, color:col }}>{(conn.display_name || conn.host).toUpperCase()}</span>
                    <span style={{ color:LM.inkMuted, fontSize:9 }}>{ops.length}</span>
                  </button>
                  {open && (
                    <div style={{ display:'flex', flexDirection:'column', gap:1, paddingLeft:6 }}>
                      {ops.map(op => {
                        const it = {
                          id: 'op:' + op.op_id,
                          title: op.label || op.op_id,
                          sub: (op.kind === 'action' ? '◆ ' : '◇ ') + (op.description || op.op_id),
                          _connector_op: op,
                        };
                        return (
                          <NodeLibItem key={op.op_id} it={it}
                            cat={{ col, icon: op.kind === 'action' ? '◆' : '◇',
                                    label: conn.host }}
                            pinned={isPinned(it.id)}
                            onPin={() => togglePin(it,
                              { col, icon: op.kind === 'action' ? '◆' : '◇', label: conn.host },
                              op.kind === 'action' ? 'output' : 'read')}
                            onAdd={() => {
                              try {
                                usage[it.id] = (usage[it.id] || 0) + 1;
                                localStorage.setItem('archhub_node_usage', JSON.stringify(usage));
                              } catch (e) {}
                              addNodeFromLibrary({ ...it, cat: op.kind === 'action' ? 'output' : 'read' });
                            }}/>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

      </div>

      <div style={{
        margin:8, padding:'7px 10px', borderRadius:6,
        background:LM.bgSoft, border:`1px solid ${LM.line}`,
        display:'flex', alignItems:'center', gap:9,
      }}>
        <div style={{ width:22, height:22, borderRadius:'50%', background:'#d8c5a8', display:'grid', placeItems:'center', fontSize:11, color:'#5a4a2a', fontWeight:700 }}>F</div>
        <div style={{ flex:1, lineHeight:1.1, minWidth:0 }}>
          <div style={{ fontSize:12, fontWeight:500, color:LM.ink }}>Fargaly</div>
          <div style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.08em' }}>BYO · CLOUD</div>
        </div>
      </div>
    </div>
  );
};

const NodeLibItem = ({ it, cat, onAdd, draggable = true, pinned = false, onPin = null }) => {
  const [h, setH] = React.useState(false);
  const onDragStart = (e) => {
    // Skills aren't single nodes — they expand into a sub-graph, so they
    // spawn via double-click only (the canvas drop handler builds a single
    // node from the payload). Block the drag rather than drop a junk node.
    if (!draggable) { e.preventDefault(); return; }
    e.dataTransfer.effectAllowed = 'copy';
    e.dataTransfer.setData('application/x-lm-node', JSON.stringify({ ...it, cat: cat.label.toLowerCase() }));
    e.dataTransfer.setData('text/plain', it.title);
  };
  return (
    <div
      draggable={draggable ? 'true' : 'false'}
      onDragStart={onDragStart}
      onDoubleClick={onAdd}
      onMouseEnter={() => setH(true)}
      onMouseLeave={() => setH(false)}
      title={draggable ? 'Drag onto canvas, or double-click to add' : 'Double-click to add'}
      style={{
        display:'flex', alignItems:'center', gap:8, padding:'5px 8px',
        borderRadius:4, cursor: draggable ? 'grab' : 'pointer', userSelect:'none',
        background: h ? LM.bgHover : 'transparent',
        borderLeft:`2px solid ${h ? cat.col : 'transparent'}`,
        transition:'background .1s, border-color .1s',
      }}>
      <span style={{ width:5, height:5, borderRadius:'50%', background:cat.col, flexShrink:0, opacity:0.8 }}/>
      <div style={{ flex:1, minWidth:0, lineHeight:1.2 }}>
        <div style={{ fontFamily:LM.mono, fontSize:11, color:LM.ink, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{it.title}</div>
        <div style={{ fontFamily:LM.sans, fontSize:10, color:LM.inkMuted, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{it.sub}</div>
      </div>
      {onPin && (pinned || h) && (
        <span onClick={(e) => { e.stopPropagation(); e.preventDefault(); onPin(it); }}
          title={pinned ? 'Unpin' : 'Pin to top'}
          style={{ fontSize:11, lineHeight:1, cursor:'pointer', flexShrink:0,
            color: pinned ? LM.warn : LM.inkMuted }}>
          {pinned ? '★' : '☆'}
        </span>
      )}
      {h && !pinned && (
        <span style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.04em', flexShrink:0 }}>+</span>
      )}
    </div>
  );
};

// ─── Skills panel — saved templates the user has accrued ───
// Source: bridge.get_saved_skills, prefetched into this window var by
// index.html (and refreshed on the `skills_changed` signal). The
// fallback is EMPTY, never demo data \u2014 a failed prefetch shows an
// honest empty panel, not fabricated skills (founder, 2026-05-18).
const LM_SAVED_SKILLS = window.__archhub_LM_SAVED_SKILLS = window.__archhub_LM_SAVED_SKILLS || [];

const SkillsPanel = () => {
  // Real wiring: click to spawn the skill onto the active canvas via the
  // `lm-spawn-skill` event (StudioLM listens). Drag carries a typed payload
  // so the canvas drop handler can accept it. Search filters by name client-side.
  const [q, setQ] = React.useState('');
  const filtered = React.useMemo(() => {
    const items = LM_SAVED_SKILLS || [];
    if (!q) return items;
    const needle = q.toLowerCase();
    return items.filter(s => (s.name || '').toLowerCase().includes(needle));
  }, [q]);
  const onNewSkill = () => {
    // Open the CreateNodeModal pre-filled with category='compose'. We use a
    // window-level event so this dumb panel doesn't need access to StudioLM
    // state — the composer-action handler already routes 'createnode' commands.
    try {
      window.dispatchEvent(new CustomEvent('lm-composer-action', {
        detail: { action: { command:'createnode', spec:{ cat:'compose' } } },
      }));
    } catch (e) {}
  };
  return (
    <div style={{ display:'flex', flexDirection:'column', overflow:'hidden', minHeight:0 }}>
      <div style={{ padding:'12px 12px 10px', display:'flex', alignItems:'center', gap:8 }}>
        <span style={{ fontFamily:LM.sans, fontSize:14, fontWeight:600, color:LM.ink }}>Skills</span>
        <span style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.08em' }}>{(LM_SAVED_SKILLS || []).length} SAVED</span>
        <div style={{ flex:1 }}/>
        <button title="New skill" onClick={onNewSkill} style={panelIconBtn()}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 5v14M5 12h14"/></svg>
        </button>
      </div>
      <div style={{ padding:'0 10px 8px' }}>
        <div style={{
          display:'flex', alignItems:'center', gap:8, padding:'6px 10px',
          background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:6, color:LM.inkMuted, fontSize:12,
        }}>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search saved skills…" style={{
            flex:1, border:0, background:'transparent', color:LM.ink, fontSize:12, outline:'none', fontFamily:LM.sans,
          }}/>
        </div>
      </div>
      <div className="ah-scroll" style={{ flex:1, overflow:'auto', padding:'0 6px 8px' }}>
        {filtered.map(s => (
          <div key={s.id}
            draggable="true"
            onClick={() => { try { window.dispatchEvent(new CustomEvent('lm-spawn-skill', { detail: s })); } catch (e) {} }}
            onDragStart={(e) => { try { e.dataTransfer.setData('application/x-archhub-skill', JSON.stringify(s)); e.dataTransfer.effectAllowed = 'copy'; } catch (ex) {} }}
            style={{
              padding:'7px 9px', borderRadius:5, cursor:'grab', marginBottom:1,
              background:'transparent', borderLeft:`2px solid transparent`,
            }}
            onMouseEnter={e => { e.currentTarget.style.background = LM.bgHover; e.currentTarget.style.borderLeftColor = LM.accent; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.borderLeftColor = 'transparent'; }}>
            <div style={{ display:'flex', alignItems:'center', gap:7 }}>
              <span style={{ color:LM.accent, fontFamily:LM.mono, fontSize:11 }}>✦</span>
              <span style={{ flex:1, fontSize:12.5, color:LM.ink }}>{s.name}</span>
              <span style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted }}>{s.runs}</span>
            </div>
            <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, paddingLeft:18, marginTop:1, letterSpacing:'0.04em' }}>
              <span style={{ color:LM.accent+'aa' }}>args:</span> {s.args} <span style={{ color:LM.inkDim, margin:'0 5px' }}>·</span> {s.when}
            </div>
          </div>
        ))}
        {filtered.length === 0 && (
          <div style={{ padding:'18px 12px', fontFamily:LM.serif, fontStyle:'italic', fontSize:13, color:LM.inkMuted }}>
            No skills match "{q}".
          </div>
        )}
      </div>
    </div>
  );
};

// ─── Global search panel ───
const SearchPanel = ({ onOpen, setFocusId } = {}) => {
  const [q, setQ] = React.useState('');
  const [scope, setScope] = React.useState('all');
  // Live results — re-evaluated on every keystroke. Bridge slots may be
  // missing (F2-A); each call gracefully degrades to empty.
  const results = React.useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return { chats:[], nodes:[], skills:[], memory:[], files:[], hosts:[] };
    const matches = (s) => (s || '').toLowerCase().includes(needle);
    // Sessions: prefer bridge but fall back to LM_SESSIONS.
    let sessions = bridgeJson('get_sessions');
    if (!Array.isArray(sessions)) sessions = LM_SESSIONS || [];
    const chats = sessions.filter(s => matches(s.title) || matches(s.last));
    // Memory facts: bridge.list_memory_facts(query). When the bridge slot is
    // missing we have no local fallback — Settings overlay (which previously
    // owned LM_MEMORY) was removed in favor of the native PyQt dialog.
    let memoryHits = bridgeJson('list_memory_facts', needle);
    if (!Array.isArray(memoryHits)) memoryHits = [];
    // Saved skills: bridge.get_saved_skills() else local.
    let skills = bridgeJson('get_saved_skills');
    if (!Array.isArray(skills)) skills = LM_SAVED_SKILLS || [];
    skills = skills.filter(s => matches(s.name) || matches(s.args));
    // Nodes: in current LM_GRAPH.
    const nodes = (LM_GRAPH.nodes || []).filter(n => matches(n.title) || matches(n.sub) || matches(n.id));
    // Hosts: id, name, family.
    const hosts = (LM_HOSTS || []).filter(h => matches(h.id) || matches(h.name) || matches(h.file));
    // Files: collect from sessions for now (no dedicated registry).
    const files = sessions.filter(s => matches(s.file)).map(s => ({ id:s.id, label:s.file, sid:s.id }));
    return { chats, nodes, skills, memory: memoryHits, files, hosts };
  }, [q]);
  const counts = {
    all: results.chats.length + results.nodes.length + results.skills.length + results.memory.length + results.files.length + results.hosts.length,
    chats: results.chats.length, nodes: results.nodes.length, skills: results.skills.length,
    memory: results.memory.length, files: results.files.length, hosts: results.hosts.length,
  };
  const showChats  = scope === 'all' || scope === 'chats';
  const showNodes  = scope === 'all' || scope === 'nodes';
  const showSkills = scope === 'all' || scope === 'skills';
  const showMemory = scope === 'all' || scope === 'memory';
  const showFiles  = scope === 'all' || scope === 'files';
  const showHosts  = scope === 'all' || scope === 'hosts';
  return (
    <div style={{ display:'flex', flexDirection:'column', overflow:'hidden', minHeight:0 }}>
      <div style={{ padding:'12px 12px 10px', display:'flex', alignItems:'center', gap:8 }}>
        <span style={{ fontFamily:LM.sans, fontSize:14, fontWeight:600, color:LM.ink }}>Search</span>
        <div style={{ flex:1 }}/>
        <kbd style={kbd()}>⌘K</kbd>
      </div>
      <div style={{ padding:'0 10px 10px' }}>
        <div style={{
          display:'flex', alignItems:'center', gap:8, padding:'8px 12px',
          background:LM.bg, border:`1px solid ${LM.accent}55`, borderRadius:6,
          boxShadow:`0 0 0 3px ${LM.accentDim}`,
        }}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke={LM.accent} strokeWidth="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
          <input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="everything in studio…" style={{
            flex:1, border:0, background:'transparent', color:LM.ink, fontSize:13, outline:'none',
            fontFamily:LM.sans, fontStyle: q ? 'normal' : 'italic',
          }}/>
        </div>
      </div>
      <div style={{ padding:'4px 10px', fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.14em' }}>SCOPES</div>
      <div style={{ padding:'0 6px', display:'flex', flexDirection:'column', gap:1 }}>
        {[
          ['all',    'everything',                counts.all],
          ['chats',  'sessions + messages',       counts.chats],
          ['nodes',  'in current graph',          counts.nodes],
          ['skills', 'saved templates',           counts.skills],
          ['memory', 'what Claude remembers',     counts.memory],
          ['files',  'Revit / Rhino / Speckle',   counts.files],
          ['hosts',  'connectors',                counts.hosts],
        ].map(([k, sub, n]) => {
          const active = scope === k;
          return (
            <button key={k} onClick={() => setScope(k)} style={{
              padding:'6px 10px', borderRadius:5,
              background: active ? LM.bgSoft : 'transparent', border:0,
              borderLeft: `2px solid ${active ? LM.accent : 'transparent'}`,
              cursor:'pointer', textAlign:'left',
              display:'flex', alignItems:'center', gap:8,
            }}
            onMouseEnter={e => !active && (e.currentTarget.style.background = LM.bgHover)}
            onMouseLeave={e => !active && (e.currentTarget.style.background = 'transparent')}>
              <span style={{ fontFamily:LM.mono, fontSize:11, color: active ? LM.accent : LM.ink, width:54 }}>{k}</span>
              <span style={{ flex:1, fontSize:11, color:LM.inkSoft }}>{sub}</span>
              <span style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted }}>{n}</span>
            </button>
          );
        })}
      </div>
      <div className="ah-scroll" style={{ flex:1, overflow:'auto', padding:'8px 6px 8px', minHeight:0 }}>
        {!q && (
          <div style={{ padding:'24px 14px', fontFamily:LM.serif, fontStyle:'italic', fontSize:13, color:LM.inkMuted }}>
            Type to search across sessions, nodes, skills, memory, files, and hosts.
          </div>
        )}
        {q && counts[scope === 'all' ? 'all' : scope] === 0 && (
          <div style={{ padding:'16px 14px', fontFamily:LM.serif, fontStyle:'italic', fontSize:13, color:LM.inkMuted }}>
            No matches for "{q}".
          </div>
        )}
        {q && showChats && results.chats.map(s => (
          <SearchHit key={'ch_'+s.id} k="chat" label={s.title} sub={s.last}
            onClick={() => onOpen && onOpen(s.id)}/>
        ))}
        {q && showNodes && results.nodes.map(n => (
          <SearchHit key={'nd_'+n.id} k="node" label={n.title || n.id} sub={n.sub || n.cat}
            onClick={() => setFocusId && setFocusId(n.id)}/>
        ))}
        {q && showSkills && results.skills.map(s => (
          <SearchHit key={'sk_'+s.id} k="skill" label={s.name} sub={s.args}
            onClick={() => { try { window.dispatchEvent(new CustomEvent('lm-spawn-skill', { detail:s })); } catch (e) {} }}/>
        ))}
        {q && showMemory && results.memory.map((m, i) => (
          <SearchHit key={'mm_'+(m.id || i)} k="memory" label={m.text || String(m)} sub={m.src || ''}/>
        ))}
        {q && showFiles && results.files.map((f, i) => (
          <SearchHit key={'fi_'+(f.id || i)} k="file" label={f.label || f.path || String(f)} sub={f.sid ? `session ${f.sid}` : ''}
            onClick={() => f.sid && onOpen && onOpen(f.sid)}/>
        ))}
        {q && showHosts && results.hosts.map(h => (
          <SearchHit key={'hs_'+h.id} k="host" label={h.name} sub={`${h.state} · ${h.file}`}/>
        ))}
      </div>
    </div>
  );
};
const SearchHit = ({ k, label, sub, onClick }) => (
  <button onClick={onClick} disabled={!onClick} style={{
    width:'100%', padding:'6px 10px', borderRadius:5,
    background:'transparent', border:0, cursor: onClick ? 'pointer' : 'default',
    textAlign:'left', display:'flex', alignItems:'center', gap:8, marginBottom:1,
  }}
  onMouseEnter={e => onClick && (e.currentTarget.style.background = LM.bgHover)}
  onMouseLeave={e => onClick && (e.currentTarget.style.background = 'transparent')}>
    <span style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, width:42, letterSpacing:'0.08em', textTransform:'uppercase' }}>{k}</span>
    <div style={{ flex:1, minWidth:0, lineHeight:1.2 }}>
      <div style={{ fontSize:12, color:LM.ink, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{label}</div>
      {sub && <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{sub}</div>}
    </div>
  </button>
);

const kbd = () => ({
  fontFamily:LM.mono, fontSize:9, padding:'1px 5px', background:LM.bgSoft,
  border:`1px solid ${LM.lineHair}`, borderRadius:3, color:LM.inkMuted, letterSpacing:'0.06em',
});

// ──────────────────────── HOME ────────────────────────
// Founder demand #5: dashboard with session thumbnails. Composer pinned to
// the same bottom-center coords as the in-canvas composer so opening a
// session doesn't visually shift the input. + button or Enter on empty state
// mints a fresh session.
const Home = ({ onOpen, model, setPickerOpen, onCreateSession, onSettings }) => {
  const [title, setTitle] = React.useState('');
  const [filter, setFilter] = React.useState('all');
  // Founder demand 2026-05-15: composer parity. Home composer accepts
  // files / images / voice / paste / drag-drop just like the canvas one.
  const [attachments, setAttachments] = React.useState([]);
  const [recording, setRecording] = React.useState(false);
  const [dragOver, setDragOver] = React.useState(false);
  const fileInputRef = React.useRef(null);
  const recogRef = React.useRef(null);
  const _stashFile = async (file) => {
    if (!file) return null;
    try {
      const b64 = await _blobToB64(file);
      const res = await bridgeAsync('stash_attachment',
        file.name || 'paste', file.type || '', b64);
      if (!res || !res.ok) return null;
      const kind = (file.type || '').startsWith('image/') ? 'image'
                 : (file.type || '').startsWith('audio/') ? 'audio' : 'file';
      return { name: res.name, mime: res.mime, path: res.path,
                size: res.size, kind };
    } catch (e) { return null; }
  };
  const _addFiles = async (files) => {
    for (const f of Array.from(files || [])) {
      const att = await _stashFile(f);
      if (att) setAttachments(a => [...a, att]);
    }
  };
  const _onDragOver = (e) => {
    if (!e.dataTransfer || !e.dataTransfer.types) return;
    if (![...e.dataTransfer.types].includes('Files')) return;
    e.preventDefault(); e.stopPropagation(); setDragOver(true);
  };
  const _onDragLeave = (e) => { e.preventDefault(); setDragOver(false); };
  const _onDrop = async (e) => {
    if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files.length) return;
    e.preventDefault(); e.stopPropagation(); setDragOver(false);
    await _addFiles(e.dataTransfer.files);
  };
  const _onPaste = async (e) => {
    if (!e.clipboardData || !e.clipboardData.items) return;
    const files = [];
    for (const it of e.clipboardData.items) {
      if (it.kind === 'file') { const f = it.getAsFile(); if (f) files.push(f); }
    }
    if (files.length) { e.preventDefault(); await _addFiles(files); }
  };
  const SpeechRec = (typeof window !== 'undefined') &&
                    (window.SpeechRecognition || window.webkitSpeechRecognition);
  const _toggleRec = () => {
    if (!SpeechRec) {
      try { window.dispatchEvent(new CustomEvent('lm-canvas-toast', {
        detail: { msg:'voice not supported', kind:'err' } })); } catch (e) {}
      return;
    }
    if (recording) {
      try { recogRef.current && recogRef.current.stop(); } catch (e) {}
      setRecording(false); return;
    }
    try {
      const rec = new SpeechRec();
      rec.lang = 'en-US'; rec.interimResults = true; rec.continuous = false;
      rec.onresult = (ev) => {
        let final = '';
        for (let i = ev.resultIndex; i < ev.results.length; i++)
          final += ev.results[i][0].transcript;
        if (final) setTitle(t => (t ? t + ' ' : '') + final.trim());
      };
      rec.onend = () => setRecording(false);
      rec.onerror = () => setRecording(false);
      rec.start(); recogRef.current = rec; setRecording(true);
    } catch (e) { setRecording(false); }
  };
  // Defensive: fetch sessions on every Home mount so the list is fresh
  // even if the index.html hydration race lost. Splice in-place so
  // every consumer sees the same reference.
  const [, _setBump] = React.useState(0);
  React.useEffect(() => {
    let cancel = false;
    // bridgeJson is sync but QWebChannel slots are async — use bridgeAsync.
    bridgeAsync('get_sessions').then((fetched) => {
      if (cancel) return;
      if (Array.isArray(fetched) && fetched.length > 0) {
        LM_SESSIONS.splice(0, LM_SESSIONS.length, ...fetched);
        _setBump(b => b + 1);
      }
    });
    return () => { cancel = true; };
  }, []);
  const onSubmit = (e) => {
    e && e.preventDefault();
    const t = title.trim();
    setTitle('');
    if (!t) { onCreateSession && onCreateSession('untitled'); return; }
    // Client-side intent detection (mirror of detectIntentJS). The bridge
    // path was async-returning-undefined so it never matched — founder bug
    // 2026-05-14 root cause. Resolve locally so spawn happens instantly.
    const lower = t.toLowerCase();
    const tokens = lower.match(/[a-z0-9']+/g) || [];
    const FAMILIES = ['revit','autocad','max','blender','rhino','speckle',
      'outlook','lmstudio','antigravity','word','excel','powerpoint',
      'photoshop','illustrator','indesign','teams','notion','dropbox'];
    const VERBS = new Set(['ping','info','list','open','save','render','build',
      'draft','send','search','find','summarise','summarize','show','describe',
      'explain','what','where','how']);
    let host = null, hostIdx = -1;
    for (let i = 0; i < tokens.length; i++) {
      for (const fam of FAMILIES) {
        if (tokens[i].indexOf(fam) !== -1) { host = fam; hostIdx = i; break; }
      }
      if (host) break;
    }
    let verb = null;
    for (let i = 0; i < tokens.length && host; i++) {
      if (i === hostIdx) continue;
      const base = tokens[i].split("'")[0];
      if (VERBS.has(tokens[i])) { verb = tokens[i]; break; }
      if (base && VERBS.has(base)) { verb = base; break; }
    }
    const atts = attachments.slice();
    setAttachments([]);
    const isHostIntent = host && (verb || hostIdx === 0);
    // Founder bug 2026-05-15: edits lost to a create/open race. Fix is to
    // AWAIT createSession (which now awaits openSession) before dispatching
    // any spawn. By the time we dispatch, window.__archhub_session_id is
    // the real slug and LM_GRAPH is the loaded (empty) fresh graph.
    if (isHostIntent) {
      (async () => {
        await (onCreateSession && onCreateSession(t));
        try {
          window.dispatchEvent(new CustomEvent('lm-composer-action', {
            detail: {
              action: { command:'spawn_host_chat', family:host,
                         verb:verb||null, text:t,
                         summary:`Spawn ${host} host + chat` },
              raw: t, focusId: '', attachments: atts,
            },
          }));
        } catch (e) {}
      })();
    } else if (atts.length || (t && !host)) {
      (async () => {
        await (onCreateSession && onCreateSession(t || 'untitled'));
        try {
          window.dispatchEvent(new CustomEvent('lm-composer-action', {
            detail: { action: { command:'chat', text: t },
                       raw: t, focusId: '', attachments: atts },
          }));
        } catch (e) {}
      })();
    } else {
      onCreateSession && onCreateSession(t);
    }
  };
  const allSessions = LM_SESSIONS || [];
  // Filter semantics defined in the audit:
  //   all       → no filter
  //   mine      → author field matches; fall back to all when no authors exist
  //   scheduled → sessions with .schedule / .trigger config (none yet)
  //   workflows → graphs with 3+ nodes (peeks at .graph or .node_count)
  const sessions = React.useMemo(() => {
    if (filter === 'all') return allSessions;
    if (filter === 'mine') {
      const withAuthor = allSessions.filter(s => s.author);
      // If no authors are tracked anywhere, treat "mine" as "all" (single-user app).
      if (withAuthor.length === 0) return allSessions;
      return withAuthor.filter(s => s.author === 'me' || s.author === (window.__archhub_user || 'me'));
    }
    if (filter === 'scheduled') {
      return allSessions.filter(s => s.schedule || s.trigger);
    }
    if (filter === 'workflows') {
      return allSessions.filter(s => {
        const n = (s.graph && Array.isArray(s.graph.nodes) ? s.graph.nodes.length : null)
               || s.node_count || 0;
        return n >= 3;
      });
    }
    return allSessions;
  }, [filter, allSessions.length]);
  return (
    <main className="ah-scroll" style={{
      // Home renders in column 2 of the parent grid (column 1 is the
      // 56px icon rail).
      gridColumn:'2', gridRow:'1', overflow:'auto', minHeight:0,
      padding:'30px 44px 110px', display:'flex', flexDirection:'column', position:'relative',
    }}>
      <ModelStrip model={model} setPickerOpen={setPickerOpen}/>
      <div style={{ display:'flex', alignItems:'baseline', gap:10, margin:'24px 0 14px' }}>
        <h2 style={{ fontFamily:LM.serif, fontSize:26, fontWeight:400, letterSpacing:'-0.015em', margin:0 }}>Sessions</h2>
        <span style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.14em' }}>
          {sessions.length} · CLICK TO OPEN
        </span>
        <div style={{ flex:1 }}/>
        {['all','mine','scheduled','workflows'].map(k => (
          <button key={k} onClick={() => setFilter(k)} style={chipBtn(filter === k)}>{k}</button>
        ))}
        <button onClick={() => onCreateSession && onCreateSession('untitled')} style={chipBtn(true)}>+ new canvas</button>
      </div>
      {sessions.length === 0 ? (
        <div style={{
          padding:'48px 24px', textAlign:'center', color:LM.inkMuted, fontFamily:LM.serif,
          fontStyle:'italic', fontSize:18, background:LM.bgPanel, border:`1px dashed ${LM.line}`,
          borderRadius:9,
        }}>
          {filter === 'all'
            ? 'No sessions yet. Type a title above and hit ↵.'
            : `No sessions match "${filter}".`}
        </div>
      ) : (
        <div style={{
          display:'grid',
          // Founder demand 2026-05-15: thumbnails too huge. Shrink + auto-pack
          // by minmax so wide screens get more columns instead of giant cards.
          gridTemplateColumns:'repeat(auto-fill, minmax(220px, 1fr))',
          gap:10,
        }}>
          {sessions.map(s => <SessionCard key={s.id} s={s} onOpen={onOpen}
            onChanged={() => _setBump(b => b + 1)}/>)}
        </div>
      )}
      {/* Composer pinned bottom-center — full attach parity with the
          in-canvas FloatingComposer (paperclip + mic + drag-drop + paste). */}
      <form onSubmit={onSubmit} data-no-pan
        onWheel={(e) => e.stopPropagation()}
        onMouseDown={(e) => e.stopPropagation()}
        onDragOver={_onDragOver}
        onDragLeave={_onDragLeave}
        onDrop={_onDrop}
        style={{
        position:'fixed', left:'50%', bottom:80, transform:'translateX(-50%)',
        width:620, maxWidth:'82%',
        background:LM.bgPanel,
        border:`1px solid ${dragOver ? LM.accent : LM.accent+'66'}`,
        borderRadius:9, boxShadow:`0 14px 30px rgba(0,0,0,.5), 0 0 0 3px ${LM.accentDim}`,
        padding:'10px 13px', zIndex:10,
      }}>
        {attachments.length > 0 && (
          <div style={{ display:'flex', flexWrap:'wrap', gap:6, marginBottom:8 }}>
            {attachments.map((a, i) => (
              <div key={i} style={{
                display:'flex', alignItems:'center', gap:6,
                background:LM.bg, border:`1px solid ${LM.line}`,
                borderRadius:5, padding:'3px 8px',
                fontFamily:LM.mono, fontSize:10.5, color:LM.inkSoft,
              }}>
                <span style={{ color:LM.accent }}>
                  {a.kind === 'image' ? '◧' : a.kind === 'audio' ? '◉' : '⎙'}
                </span>
                <span style={{ maxWidth:160, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{a.name}</span>
                <span style={{ color:LM.inkDim, fontSize:9.5 }}>{Math.max(1, Math.round((a.size||0)/1024))}kb</span>
                <button type="button" onClick={(e) => { e.stopPropagation();
                  setAttachments(arr => arr.filter((_, j) => j !== i)); }}
                  style={{ border:0, background:'transparent', color:LM.inkMuted,
                            cursor:'pointer', padding:0, fontSize:13, lineHeight:1 }}>×</button>
              </div>
            ))}
          </div>
        )}
        <input ref={fileInputRef} type="file" multiple style={{ display:'none' }}
          onChange={async (e) => { await _addFiles(e.target.files); e.target.value = ''; }}/>
        <div style={{ display:'flex', alignItems:'center', gap:8 }}>
          <span style={{ color:LM.accent, fontFamily:LM.mono, fontSize:13 }}>/</span>
          <input value={title} onChange={e => setTitle(e.target.value)}
            onPaste={_onPaste}
            placeholder={dragOver ? 'drop files to attach…' : 'Start a new session… (Enter to create)'}
            style={{
              flex:1, border:0, background:'transparent', color:LM.ink, fontSize:14,
              fontFamily:LM.sans, outline:'none',
            }}/>
          <button type="button" title="Attach file or image"
            onClick={(e) => { e.stopPropagation(); fileInputRef.current && fileInputRef.current.click(); }}
            style={{ padding:'3px 9px', background:'transparent',
                      border:`1px solid ${LM.line}`, borderRadius:5,
                      color:LM.inkSoft, cursor:'pointer', fontSize:12 }}>📎</button>
          <button type="button"
            title={recording ? 'Stop recording' : 'Voice input'}
            onClick={(e) => { e.stopPropagation(); _toggleRec(); }}
            style={{ padding:'3px 9px',
                      background: recording ? LM.err+'22' : 'transparent',
                      border:`1px solid ${LM.line}`, borderRadius:5,
                      color: recording ? LM.err : LM.inkSoft,
                      cursor:'pointer', fontSize:12,
                      animation: recording ? 'lmPulse 1s ease-in-out infinite' : 'none' }}>
            {recording ? '● rec' : '🎤'}
          </button>
          <button type="submit" style={{
            padding:'4px 11px', background:LM.accent, color:'#fff',
            border:0, borderRadius:5, fontSize:11.5, fontWeight:500, cursor:'pointer',
          }}>Send ↵</button>
        </div>
      </form>
    </main>
  );
};

// ─── Tiny SVG thumbnail for a session's graph ───────────────────────
// We don't (yet) load each session's blob here — render a tasteful
// pseudo-thumbnail from the session's host(s). Looks like a graph at a
// distance, doesn't lie.
const SessionThumb = ({ s }) => {
  const hosts = (Array.isArray(s.host) ? s.host : [s.host]).filter(Boolean);
  const cols = hosts.map(h => (LM_HOST_META[h] || { col:LM.inkSoft }).col);
  if (cols.length === 0) cols.push(LM.inkSoft);
  return (
    <svg viewBox="0 0 100 40" style={{ width:'100%', height:40 }}>
      {cols.map((c, i) => (
        <g key={i}>
          <rect x={4 + i*30} y={6} width={22} height={12} rx={2} fill={c+'33'} stroke={c} strokeWidth={1}/>
          <rect x={4 + i*30} y={22} width={22} height={12} rx={2} fill={LM.bgDeep} stroke={LM.lineSoft} strokeWidth={1}/>
          <path d={`M${15 + i*30},18 L${15 + i*30},22`} stroke={c} strokeWidth={1.2}/>
        </g>
      ))}
    </svg>
  );
};

const chipBtn = (active) => ({
  padding:'4px 11px', borderRadius:999,
  background: active ? LM.accentDim : 'transparent',
  border:`1px solid ${active ? LM.accent : LM.line}`,
  color: active ? LM.accent : LM.inkSoft, fontFamily:LM.mono, fontSize:10,
  letterSpacing:'0.06em', cursor:'pointer',
});

const Chip = ({ children, mono }) => (
  <span style={{
    display:'inline-flex', alignItems:'center', gap:5, padding:'3px 9px',
    background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:5,
    color:LM.inkSoft, fontFamily: mono ? LM.mono : LM.sans, fontSize: mono ? 10.5 : 11.5,
    letterSpacing: mono ? '0.04em' : 'normal', cursor:'pointer',
  }}>{children}</span>
);

const SessionCard = ({ s, onOpen, onChanged }) => {
  const [menu, setMenu] = React.useState(false);
  const [hover, setHover] = React.useState(false);
  const sm = stateMeta(s.state);
  const hostList = (Array.isArray(s.host) ? s.host : [s.host])
    .filter(Boolean)
    .map(h => LM_HOST_META[h] || { name:h, col:LM.inkSoft });
  // Home stays put on fork/duplicate (openAfterCreate:false) — the new
  // card just appears in the grid rather than yanking the user away.
  const act = (a) => {
    setMenu(false);
    runSessionAction(a, s.id, { onOpen: onOpen, afterChange: onChanged,
                                openAfterCreate: false });
  };
  return (
    // role="button" (not a real <button>) so the rename/delete control
    // can be a nested <button> — nested interactive elements are
    // invalid HTML and break keyboard nav.
    <div role="button" tabIndex={0}
      onClick={() => onOpen(s.id)}
      onKeyDown={e => {
        if ((e.key === 'Enter' || e.key === ' ')
            && e.target === e.currentTarget) {
          e.preventDefault(); onOpen(s.id);
        }
      }}
      style={{
      background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:7,
      padding:'9px 11px', display:'flex', flexDirection:'column', gap:6,
      cursor:'pointer', textAlign:'left', color:LM.ink, fontFamily:LM.sans,
      transition:'border-color .12s, transform .12s',
      minHeight:0, position:'relative',
    }}
    onMouseEnter={e => { setHover(true); e.currentTarget.style.borderColor = LM.accent+'66'; e.currentTarget.style.transform='translateY(-1px)'; }}
    onMouseLeave={e => { setHover(false); e.currentTarget.style.borderColor = LM.line; e.currentTarget.style.transform='none'; }}>
      {/* Session actions — rename / fork / duplicate / delete. Hidden
          until card hover so the grid stays calm. */}
      <button title="Session actions"
        onClick={e => { e.stopPropagation(); setMenu(m => !m); }}
        style={{
          position:'absolute', top:5, right:5, width:22, height:22,
          display:'grid', placeItems:'center', padding:0,
          border:`1px solid ${menu ? LM.line : 'transparent'}`,
          borderRadius:5, background: menu ? LM.bg : 'transparent',
          color:LM.inkMuted, cursor:'pointer',
          opacity:(hover || menu) ? 1 : 0, transition:'opacity .12s',
        }}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>
      </button>
      {menu && <ChatItemMenu onClose={() => setMenu(false)} onAction={act}/>}
      {/* Top row: state dot + when */}
      <div style={{ display:'flex', alignItems:'center', gap:6, paddingRight:24 }}>
        <span style={{ width:5, height:5, borderRadius:'50%', background: sm.col,
                        boxShadow: sm.pulse ? `0 0 0 2px ${sm.col}22` : 'none',
                        animation: sm.pulse ? 'lmPulse 1.2s infinite' : 'none' }}/>
        <span style={{ fontFamily:LM.mono, fontSize:8.5, color:sm.col,
                        letterSpacing:'0.1em', textTransform:'uppercase' }}>{sm.label}</span>
        <div style={{ flex:1 }}/>
        <span style={{ fontFamily:LM.mono, fontSize:8.5, color:LM.inkMuted,
                        letterSpacing:'0.04em' }}>{s.when || ''}</span>
      </div>
      {/* Title */}
      <div style={{ fontFamily:LM.serif, fontSize:14.5, letterSpacing:'-0.01em',
                     lineHeight:1.2, overflow:'hidden', textOverflow:'ellipsis',
                     display:'-webkit-box', WebkitLineClamp:2, WebkitBoxOrient:'vertical' }}>
        {s.title || 'untitled'}
      </div>
      {/* Last message preview — single line */}
      {s.last && (
        <div style={{ fontSize:11, color:LM.inkSoft, lineHeight:1.35,
                       overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
          {s.last}
        </div>
      )}
      {/* Footer: file + host pills, only render if there's data */}
      {(s.file || hostList.length > 0) && (
        <div style={{
          display:'flex', alignItems:'center', gap:5, marginTop:'auto',
          paddingTop:5, borderTop:`1px solid ${LM.lineSoft}`,
          fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.04em',
        }}>
          <span style={{ flex:1, overflow:'hidden', textOverflow:'ellipsis',
                          whiteSpace:'nowrap' }}>{s.file || ''}</span>
          {hostList.map(h => (
            <span key={h.name} style={{ padding:'1px 5px', borderRadius:3,
                                          fontSize:8.5, background: h.col + '14',
                                          color: h.col, letterSpacing:'0.06em' }}>{h.name}</span>
          ))}
        </div>
      )}
    </div>
  );
};

// ──────────────────────── WORKSPACE ────────────────────────
const Workspace = ({ session, model, openTabs, setOpenId, closeTab, setPickerOpen, setSettingsOpen, setLibraryOpen, focusId, setFocusId, userNodes, addNodeFromLibrary, removeUserNode, bumpGraph, graphBump, onHome, onCreateSession }) => {
  const allNodes = [...(LM_GRAPH.nodes || []), ...(userNodes || [])];
  const focusNode = allNodes.find(n => n.id === focusId);
  return (
    <main style={{
      gridColumn:'2', gridRow:'1', minHeight:0, overflow:'hidden',
      display:'grid',
      gridTemplateColumns:'1fr 320px',
      gridTemplateRows:'36px 1fr',
    }}>
      <WsHeader
        session={session} model={model} openTabs={openTabs}
        setOpenId={setOpenId} closeTab={closeTab}
        setPickerOpen={setPickerOpen} setSettingsOpen={setSettingsOpen} onHome={onHome}
        onCreateSession={onCreateSession}/>
      <NodeCanvas focusId={focusId} setFocusId={setFocusId} setLibraryOpen={setLibraryOpen}
        userNodes={userNodes} addNodeFromLibrary={addNodeFromLibrary}
        removeUserNode={removeUserNode} bumpGraph={bumpGraph} graphBump={graphBump}/>
      <NodeRail node={focusNode} bumpGraph={bumpGraph}/>
    </main>
  );
};

// Workspace header is now SESSION TABS (browser-style) + right-side actions.
const WsHeader = ({ session, model, openTabs, setOpenId, closeTab, setPickerOpen, setSettingsOpen, onHome, onCreateSession }) => {
  // Founder demand: fork + save-as-skill act on the current session/canvas.
  // QWebChannel slots are async — sync bridgeJson returned a Promise so
  // fork silently no-op'd ("buttons are for show"). bridgeAsync + toast.
  const _toast = (msg, kind) => {
    try { window.dispatchEvent(new CustomEvent('lm-canvas-toast',
      { detail:{ msg, kind: kind || 'info' } })); } catch (e) {}
  };
  const onFork = async () => {
    if (!session) return;
    const title = (session.title || 'session') + ' (fork)';
    _toast('forking…');
    // Persist the current canvas first so the fork captures live edits.
    try { bridgeCall('save_graph', currentSid(),
      JSON.stringify({ nodes: LM_GRAPH.nodes || [], wires: LM_GRAPH.wires || [] })); } catch (e) {}
    const blob = await bridgeAsync('fork_session', session.id, title);
    const newId = blob && (blob.id || blob.session_id);
    if (newId) {
      if (blob.session && !(LM_SESSIONS || []).find(s => s.id === newId)) {
        LM_SESSIONS.push(blob.session);
      } else if (!(LM_SESSIONS || []).find(s => s.id === newId)) {
        LM_SESSIONS.push({ id:newId, title, state:'idle', host:'', file:'',
          model:'auto', when:'just now', last:'' });
      }
      _toast(`forked → ${title}`);
      setOpenId(newId);
    } else {
      _toast(`fork failed: ${(blob && blob.error) || 'no bridge'}`, 'err');
    }
  };
  // Founder demand 2026-05-16: plain Save = persist the session/canvas.
  // Distinct from "save as skill" (which packages the canvas into the
  // node library as a reusable node). Sessions autosave on every
  // mutation; this is the explicit, confirmed save the user expects.
  const onSave = () => {
    if (!session) return;
    try {
      bridgeCall('save_graph', currentSid(),
        JSON.stringify({ nodes: LM_GRAPH.nodes || [], wires: LM_GRAPH.wires || [] }));
      _toast('session saved');
    } catch (e) {
      _toast('save failed', 'err');
    }
  };
  const onSaveAsSkill = async () => {
    if (!session) return;
    _toast('packaging skill…');
    const res = await bridgeAsync('save_as_skill', session.title || session.id,
      JSON.stringify({ nodes: LM_GRAPH.nodes || [], wires: LM_GRAPH.wires || [] }));
    if (res && (res.ok || res.id || res.path)) {
      _toast(`skill added to node library: ${res.name || session.title || 'skill'}`);
      // Refresh the node library so the new skill appears immediately.
      try { window.dispatchEvent(new CustomEvent('lm-skills-changed')); } catch (e) {}
    } else {
      _toast(`save-as-skill failed: ${(res && res.error) || 'no bridge'}`, 'err');
    }
  };
  return (
    <div style={{
      gridColumn:'1 / -1', gridRow:'1',
      borderBottom:`1px solid ${LM.line}`, background:LM.bgDeep,
      padding:'0 10px 0 6px', display:'flex', alignItems:'center', gap:6, minWidth:0,
    }}>
      <button onClick={onHome} title="All sessions" style={{
        width:26, height:26, padding:0, border:0, borderRadius:5,
        background:'transparent', color:LM.inkMuted, cursor:'pointer',
        display:'grid', placeItems:'center', flexShrink:0,
      }}
      onMouseEnter={e => e.currentTarget.style.background = LM.bgSoft}
      onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
      </button>

      <div style={{ flex:1, minWidth:0, display:'flex', alignItems:'center', gap:2, overflow:'hidden' }}>
        {(openTabs || []).map(id => {
          const s = (LM_SESSIONS || []).find(x => x.id === id);
          if (!s) return null;
          const a = session.id === id;
          return <WsTab key={id} s={s} a={a} onClick={() => setOpenId(id)} onClose={(e) => { e.stopPropagation(); closeTab(id); }}/>;
        })}
        <button onClick={() => onCreateSession && onCreateSession('untitled')}
          title="New session" style={{
          width:26, height:26, padding:0, border:0, borderRadius:5,
          background:'transparent', color:LM.inkMuted, cursor:'pointer', flexShrink:0,
          display:'grid', placeItems:'center', fontSize:14,
        }}
        onMouseEnter={e => e.currentTarget.style.background = LM.bgSoft}
        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>+</button>
      </div>

      <ModelStrip model={model} setPickerOpen={setPickerOpen} compact/>
      <HoverBtn onClick={onFork}>fork</HoverBtn>
      <HoverBtn onClick={onSaveAsSkill} title="Package this canvas into the node library as a reusable node">save as skill</HoverBtn>
      <HoverBtn primary onClick={onSave} title="Save this session">save</HoverBtn>
    </div>
  );
};

const WsTab = ({ s, a, onClick, onClose }) => {
  // Founder demand #6: active tab title is inline-editable.
  const sm = stateMeta(s.state);
  const [h, setH] = React.useState(false);
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(s.title || '');
  React.useEffect(() => { setDraft(s.title || ''); }, [s.title]);
  const commit = () => {
    setEditing(false);
    if (draft && draft !== s.title) {
      s.title = draft;
      bridgeCall('rename_session', s.id, draft);
    }
  };
  return (
    <div
      onClick={(e) => { if (!editing) onClick(); }}
      onDoubleClick={() => { if (a) setEditing(true); }}
      onMouseEnter={() => setH(true)}
      onMouseLeave={() => setH(false)}
      style={{
        display:'flex', alignItems:'center', gap:7,
        padding:'0 8px 0 9px', height:28, borderRadius:5,
        background: a ? LM.bgPanel : (h ? LM.bgSoft : 'transparent'),
        border:`1px solid ${a ? LM.line : 'transparent'}`,
        borderBottom: a ? `1px solid ${LM.bgPanel}` : `1px solid transparent`,
        cursor:'pointer', minWidth:0, flexShrink:0,
        position:'relative', top: a ? 1 : 0,
      }}>
      <span style={{
        width:6, height:6, borderRadius:'50%', background: sm.col, flexShrink:0,
        boxShadow: sm.pulse ? `0 0 0 2px ${sm.col}22` : 'none',
        animation: sm.pulse ? 'lmPulse 1.2s infinite' : 'none',
      }}/>
      {editing ? (
        <input autoFocus value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit();
            if (e.key === 'Escape') { setDraft(s.title || ''); setEditing(false); }
          }}
          style={{
            background:'transparent', border:`1px solid ${LM.accent}66`, borderRadius:3,
            padding:'1px 4px', color:LM.ink, fontFamily:LM.sans, fontSize:12, outline:'none',
            maxWidth:160,
          }}/>
      ) : (
        <span style={{
          fontFamily:LM.sans, fontSize:12, color: a ? LM.ink : LM.inkSoft,
          fontWeight: a ? 500 : 400,
          maxWidth:160, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap',
        }}>{s.title}</span>
      )}
      <button onClick={onClose} title="Close tab" style={{
        width:14, height:14, padding:0, border:0, borderRadius:3,
        background:'transparent', color:LM.inkMuted, cursor:'pointer',
        display: a || h ? 'grid' : 'none', placeItems:'center',
        opacity: a ? 1 : 0.7, fontSize:11, lineHeight:1,
      }}
      onMouseEnter={e => { e.currentTarget.style.background = LM.bgHover; e.currentTarget.style.color = LM.ink; }}
      onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = LM.inkMuted; }}>×</button>
    </div>
  );
};

const smallBtn = (primary) => ({
  padding:'5px 11px', borderRadius:5, fontFamily:LM.sans, fontSize:11.5,
  border:`1px solid ${primary ? LM.accent : LM.line}`,
  background: primary ? LM.accent : 'transparent',
  color: primary ? '#fff' : LM.inkSoft, cursor:'pointer', fontWeight: primary ? 500 : 400,
  transition:'filter .12s, background .12s, border-color .12s',
});

// Hoverable button wrappers (cards style — actually responsive)
const HoverBtn = ({ primary, onClick, children, style, title }) => {
  const [h, setH] = React.useState(false);
  return (
    <button
      onClick={onClick}
      title={title}
      onMouseEnter={() => setH(true)}
      onMouseLeave={() => setH(false)}
      style={{
        ...smallBtn(primary),
        ...(primary
          ? { filter: h ? 'brightness(1.12)' : 'none' }
          : { background: h ? LM.bgHover : 'transparent', borderColor: h ? LM.accent+'66' : LM.line, color: h ? LM.ink : LM.inkSoft }),
        ...style,
      }}>{children}</button>
  );
};

const ModelStrip = ({ model, setPickerOpen, compact }) => {
  const [hover, setHover] = React.useState(false);
  return (
  <button
    onClick={(e) => { e.stopPropagation(); setPickerOpen(true); }}
    onMouseEnter={() => setHover(true)}
    onMouseLeave={() => setHover(false)}
    style={{
    display:'flex', alignItems:'center', gap: compact ? 8 : 12,
    padding: compact ? '4px 10px 4px 6px' : '8px 14px 8px 8px',
    background: hover ? LM.bgSoft : LM.bg,
    border:`1px solid ${hover ? LM.accent+'66' : LM.line}`, borderRadius:7,
    color:LM.ink, cursor:'pointer', fontFamily:LM.sans, minWidth: compact ? 280 : 380,
    transition:'background .12s, border-color .12s',
  }}>
    <span style={{
      width: compact ? 22 : 28, height: compact ? 22 : 28, borderRadius:5,
      background: model.col, color:'#fff', display:'grid', placeItems:'center',
      fontFamily:LM.mono, fontSize: compact ? 11 : 13, fontWeight:700,
    }}>{model.name[0]}</span>
    <div style={{ flex:1, textAlign:'left', lineHeight:1.15 }}>
      <div style={{ fontSize: compact ? 12.5 : 13.5, fontWeight:500 }}>{model.name}</div>
      <div style={{ fontFamily:LM.mono, fontSize: compact ? 9 : 10, color:LM.inkMuted, letterSpacing:'0.05em' }}>
        {model.vendor} · ctx {model.ctx} · {model.tag}
      </div>
    </div>
    <span style={{ fontFamily:LM.mono, fontSize:9, color:LM.ok, letterSpacing:'0.08em' }}>● {model.latency}ms</span>
    <span style={{ color:LM.inkSoft, fontSize:11, marginLeft:2 }}>▾</span>
  </button>
  );
};

// ──────────────────────── NODE CANVAS ────────────────────────
const SOCKET_TOP = 42;
const SOCKET_R = 5;
// Wire-drag magnet radius — v1.4 "Wire engine" spec (docs/CANVAS_PLAN.md).
// Module-scoped so the socket pitch below can be derived from it.
const SNAP_R = 28;
// Fitts's-Law constraint: vertically-stacked sockets must sit far enough apart
// that two adjacent snap zones can't both claim the cursor. When the pointer is
// anywhere on socket i's visible dot, socket i+1 must fall outside SNAP_R — i.e.
// pitch >= SNAP_R + socket radius. SOCKET_R is the dot radius; +3 covers the
// 1.5px border + 2px focus ring so the *visible* socket is fully clear. Was
// 19px, which let the hover preview light two sockets at once on 5+-port nodes.
const SOCKET_STEP = SNAP_R + SOCKET_R + 3;   // = 36px

const socketY = (i) => SOCKET_TOP + i * SOCKET_STEP;

const NodeCanvas = ({ focusId, setFocusId, setLibraryOpen, userNodes = [], addNodeFromLibrary, bumpGraph, graphBump = 0, removeUserNode }) => {
  // Combine demo graph + user-added nodes. graphBump is the COUNTER (not the
  // callback) — recomputes whenever LM_GRAPH mutates in place. Previously
  // depended on `bumpGraph` callback ref which is stable across renders, so
  // the useMemo never re-ran after first mount — new nodes never appeared
  // until the next state-bound prop changed. Founder bug: "ping outlook
  // did nothing." Root cause this. Fix: depend on graphBump number.
  const allNodes = React.useMemo(() => [...(LM_GRAPH.nodes || []), ...(userNodes || [])], [userNodes, graphBump]);

  // Persistent positions per node — initialized from node.x/y, then mutable via drag.
  const [positions, setPositions] = React.useState(() =>
    Object.fromEntries((allNodes || []).map(n => [n.id, { x: n.x, y: n.y }]))
  );
  // Add positions for newly-added / hydrated nodes
  React.useEffect(() => {
    setPositions(p => {
      const next = { ...p };
      let changed = false;
      (allNodes || []).forEach(n => { if (!next[n.id]) { next[n.id] = { x: n.x, y: n.y }; changed = true; } });
      return changed ? next : p;
    });
  }, [allNodes]);

  const [pan, setPan] = React.useState({ x: 14, y: 12 });
  const [zoom, setZoom] = React.useState(0.66);
  const [ctxMenu, setCtxMenu] = React.useState(null);
  const [nodeMenu, setNodeMenu] = React.useState(null);
  const [wireMenu, setWireMenu] = React.useState(null);
  const [expanded, setExpanded] = React.useState({});
  const [dropTarget, setDropTarget] = React.useState(null); // {x,y} canvas-local
  const [wireDrag, setWireDrag] = React.useState(null);     // wire-in-flight preview
  const [selectedWire, setSelectedWire] = React.useState(null); // wire index for delete
  const [wireFieldPicker, setWireFieldPicker] = React.useState(null); // {wireIdx, side, paths}
  const [toast, setToast] = React.useState(null);
  const [snapToGrid, setSnapToGrid] = React.useState(false);
  const dragRef = React.useRef(null);
  const wrapRef = React.useRef(null);

  // Window-level toast bridge — handlers in StudioLM root dispatch
  // `lm-canvas-toast` so feedback shows here. Previously orphaned: events
  // fired but no listener rendered them. Founder bug: spawn happens but
  // user sees "NOTHING" because the toast was silent.
  React.useEffect(() => {
    const onToast = (ev) => {
      const d = (ev && ev.detail) || {};
      const msg = d.msg || d.text;
      if (!msg) return;
      const kind = d.kind || 'info';
      setToast({ msg, kind });
      setTimeout(() => setToast(t => (t && t.msg === msg) ? null : t), 2200);
    };
    window.addEventListener('lm-canvas-toast', onToast);
    return () => window.removeEventListener('lm-canvas-toast', onToast);
  }, []);
  // Remember the original x/y per node so "Reset positions" can restore them.
  // We snapshot on first sight; later drags don't update the snapshot.
  const origPositionsRef = React.useRef({});
  React.useEffect(() => {
    (allNodes || []).forEach(n => {
      if (!origPositionsRef.current[n.id]) {
        origPositionsRef.current[n.id] = { x: n.x, y: n.y };
      }
    });
  }, [allNodes]);

  // ─── Convert client coords → canvas coords (the world space) ────────
  const toCanvasCoords = (clientX, clientY) => {
    if (!wrapRef.current) return { x: clientX, y: clientY };
    const rect = wrapRef.current.getBoundingClientRect();
    return {
      x: (clientX - rect.left - pan.x) / zoom,
      y: (clientY - rect.top  - pan.y) / zoom,
    };
  };

  // Founder demand #9: surface refusal reasons via lm-canvas-toast event so the
  // user knows WHY a wire didn't take.
  const flashToast = (msg, kind = 'info') => {
    setToast({ msg, kind });
    try { window.dispatchEvent(new CustomEvent('lm-canvas-toast', { detail:{ msg, kind } })); } catch (e) {}
    setTimeout(() => setToast(t => (t && t.msg === msg) ? null : t), 1800);
  };

  const onCanvasMouseDown = (e) => {
    if (e.button !== 0) return;
    if (e.target.closest('[data-no-pan]')) return;
    if (e.target.closest('.lm-node')) return;
    // Click on empty canvas cancels any pending click-to-wire mode.
    if (wireDrag) {
      if (wrapRef.current) wrapRef.current.querySelectorAll('[data-wire-hover]').forEach(n => n.removeAttribute('data-wire-hover'));
      setWireDrag(null);
    }
    setCtxMenu(null); setNodeMenu(null); setWireMenu(null); setSelectedWire(null);
    dragRef.current = { mode:'pan', sx:e.clientX, sy:e.clientY, px:pan.x, py:pan.y };
  };

  const onContextMenu = (e) => {
    if (e.target.closest('.lm-node') || e.target.closest('[data-no-pan]')) return;
    e.preventDefault();
    const rect = wrapRef.current.getBoundingClientRect();
    setCtxMenu({ x: e.clientX - rect.left, y: e.clientY - rect.top });
  };

  const onNodeDragStart = (id) => (e) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    e.preventDefault();
    const pos = positions[id] || { x: 0, y: 0 };
    dragRef.current = { mode:'node', id, sx:e.clientX, sy:e.clientY, nx:pos.x, ny:pos.y };
    setFocusId(id);
  };

  // Founder demand #8: right-click node opens NodeMenu.
  const onNodeContextMenu = (e, id) => {
    e.preventDefault(); e.stopPropagation();
    if (!wrapRef.current) return;
    const rect = wrapRef.current.getBoundingClientRect();
    setFocusId(id);
    setNodeMenu({ x: e.clientX - rect.left, y: e.clientY - rect.top, id });
  };

  // Founder demand #8: right-click port disconnects every wire touching that port.
  const onSocketContextMenu = (e, nodeId, sockId, side) => {
    e.preventDefault(); e.stopPropagation();
    if (!Array.isArray(LM_GRAPH.wires)) return;
    const before = (LM_GRAPH.wires || []).length;
    LM_GRAPH.wires = (LM_GRAPH.wires || []).filter(w => {
      const touches = (side === 'in')
        ? (w.to[0] === nodeId && w.to[1] === sockId)
        : (w.from[0] === nodeId && w.from[1] === sockId);
      return !touches;
    });
    const removed = before - (LM_GRAPH.wires || []).length;
    if (removed > 0) { saveCurrentGraph(); bumpGraph && bumpGraph(); flashToast(`Disconnected ${removed} wire${removed===1?'':'s'}`); }
  };

  // ─── Founder demand #9: Houdini/UE5-style wire-drag with 28px magnet. ────
  // Hovering an input socket while dragging a wire glows green (compat) or
  // red (refused) via data-wire-hover + CSS. Compatibility is pre-checked
  // against bridge.can_wire + would_create_cycle for native feel.
  // SNAP_R is module-scoped (top of NODE CANVAS) — socket pitch derives from it.
  const onSocketDown = (e, nodeId, sockId, side, ttype) => {
    if (e.button !== 0) return;
    e.stopPropagation(); e.preventDefault();
    const rect = wrapRef.current.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;
    // ── Click-to-wire path: if a pending wire is held AND user clicks an
    // input socket on a DIFFERENT node, commit immediately. No drag needed.
    if (wireDrag && side === 'in' && wireDrag.from.nodeId !== nodeId) {
      const fromN = wireDrag.from;
      const check = precheckWire(fromN.nodeId, fromN.sockId, fromN.type,
                                  nodeId, sockId, ttype);
      if (check.ok) {
        LM_GRAPH.wires = [...(LM_GRAPH.wires || []), {
          from:[fromN.nodeId, fromN.sockId], to:[nodeId, sockId],
        }];
        saveCurrentGraph(); bumpGraph && bumpGraph();
        flashToast('wired', 'info');
      } else {
        flashToast(`Refused: ${check.reason || 'incompatible'}`, 'err');
      }
      // Clear hover decorations + pending state.
      if (wrapRef.current) wrapRef.current.querySelectorAll('[data-wire-hover]').forEach(n => n.removeAttribute('data-wire-hover'));
      setWireDrag(null);
      return;
    }
    // ── Output socket: start a pending wire. Works for both click-and-
    // release-and-click (founder demand) AND drag (Houdini-style).
    if (side === 'out') {
      setWireDrag({
        from: { nodeId, sockId, type: ttype },
        mouse: { x: mouseX, y: mouseY },
        start: { x: e.clientX, y: e.clientY },
        hover: null,
      });
      return;
    }
    // Input socket clicked with no pending wire — hint user how to wire.
    flashToast('Click an output socket first', 'info');
  };

  // Compute the screen position of a socket's centre (for wire endpoints).
  const socketScreen = (nodeId, sockId, side) => {
    if (!wrapRef.current) return null;
    const sel = `[data-lm-socket="${side}:${nodeId}:${sockId}"] [data-lm-socket-dot="1"]`;
    const dot = wrapRef.current.querySelector(sel);
    if (!dot) return null;
    const r = dot.getBoundingClientRect();
    const root = wrapRef.current.getBoundingClientRect();
    return { x: r.left + r.width/2 - root.left, y: r.top + r.height/2 - root.top };
  };

  // Find the nearest compatible input socket within SNAP_R of (cx,cy).
  const findSnapTarget = (cx, cy, fromType) => {
    if (!wrapRef.current) return null;
    const sockets = wrapRef.current.querySelectorAll('[data-side="in"]');
    let best = null;
    sockets.forEach(el => {
      const dot = el.querySelector('[data-lm-socket-dot="1"]');
      if (!dot) return;
      const r = dot.getBoundingClientRect();
      const root = wrapRef.current.getBoundingClientRect();
      const sx = r.left + r.width/2 - root.left;
      const sy = r.top + r.height/2 - root.top;
      const d2 = (sx - cx) ** 2 + (sy - cy) ** 2;
      if (d2 > SNAP_R * SNAP_R) return;
      if (!best || d2 < best.d2) {
        best = {
          d2, x: sx, y: sy,
          nodeId: el.getAttribute('data-node'),
          sockId: el.getAttribute('data-pin'),
          type: el.getAttribute('data-type'),
          el,
        };
      }
    });
    return best;
  };

  // Type/cycle/dupe precheck. Returns { ok, reason }.
  // Bridge slots return *bare bools*, not envelopes:
  //   can_wire(out_t:str, in_t:str, out_exec:bool, in_exec:bool) -> bool
  //   would_create_cycle(sid:str, src_node:str, dst_node:str, graph_json:str) -> bool
  const precheckWire = (fromNodeId, fromSock, fromType, toNodeId, toSock, toType) => {
    if (fromNodeId === toNodeId) return { ok:false, reason:'self-loop' };
    // Bridge type-check (authoritative). bridgeCall returns the raw bool.
    const typeOk = bridgeCall('can_wire', fromType || '', toType || '', false, false);
    // Treat null (bridge missing in dev) as fail-open so the canvas still works.
    if (typeOk === false) return { ok:false, reason:'incompatible types' };
    // Duplicate wire
    if ((LM_GRAPH.wires || []).some(w =>
      w.from[0] === fromNodeId && w.from[1] === fromSock &&
      w.to[0]   === toNodeId   && w.to[1]   === toSock)) return { ok:false, reason:'already wired' };
    // Cycle precheck — bridge signature is (sid, src_node, dst_node, graph_json).
    const cycle = bridgeCall('would_create_cycle', currentSid(),
      fromNodeId, toNodeId, JSON.stringify(LM_GRAPH));
    if (cycle === true) return { ok:false, reason:'creates a cycle' };
    return { ok:true };
  };

  React.useEffect(() => {
    const onMove = (e) => {
      const d = dragRef.current;
      const rect = wrapRef.current && wrapRef.current.getBoundingClientRect();
      // ─── Wire drag-in-flight ─────────────────────────────────────
      if (wireDrag && rect) {
        const cx = e.clientX - rect.left;
        const cy = e.clientY - rect.top;
        const snap = findSnapTarget(cx, cy, wireDrag.from.type);
        let hover = null;
        // Clear previous hover decoration
        wrapRef.current.querySelectorAll('[data-wire-hover]').forEach(n => n.removeAttribute('data-wire-hover'));
        if (snap) {
          const check = precheckWire(
            wireDrag.from.nodeId, wireDrag.from.sockId, wireDrag.from.type,
            snap.nodeId, snap.sockId, snap.type,
          );
          snap.el.setAttribute('data-wire-hover', check.ok ? 'ok' : 'bad');
          hover = { ...snap, ok: check.ok, reason: check.reason };
        }
        setWireDrag(w => w && ({ ...w, mouse:{ x:cx, y:cy }, hover }));
        return;
      }
      if (!d) return;
      const dx = e.clientX - d.sx;
      const dy = e.clientY - d.sy;
      if (d.mode === 'pan') {
        setPan({ x: d.px + dx, y: d.py + dy });
      } else {
        setPositions(p => ({ ...p, [d.id]: { x: d.nx + dx / zoom, y: d.ny + dy / zoom } }));
      }
    };
    const onUp = (e) => {
      // Wire drag terminates here.
      if (wireDrag) {
        const hover = wireDrag.hover;
        const fromN = wireDrag.from;
        // ── Founder demand: if user clicked socket without dragging
        // (movement < 5px) AND there's no hover target, keep the wire
        // pending so the next click on an input socket finalises it.
        // Detected by comparing start position to up position.
        const start = wireDrag.start || { x: e.clientX, y: e.clientY };
        const dx = e.clientX - start.x, dy = e.clientY - start.y;
        const moved = (dx * dx + dy * dy) > 25;   // 5px threshold
        if (!moved && !hover) {
          // Click-to-wire mode active. Keep pending; user clicks input next.
          return;
        }
        // Clear hover decorations.
        if (wrapRef.current) wrapRef.current.querySelectorAll('[data-wire-hover]').forEach(n => n.removeAttribute('data-wire-hover'));
        if (hover && hover.ok) {
          // Commit the wire.
          LM_GRAPH.wires = [...(LM_GRAPH.wires || []), {
            from:[fromN.nodeId, fromN.sockId], to:[hover.nodeId, hover.sockId],
          }];
          saveCurrentGraph(); bumpGraph && bumpGraph();
        } else if (hover && !hover.ok) {
          flashToast(`Refused: ${hover.reason || 'incompatible'}`, 'err');
        } else if (wrapRef.current && e.target) {
          // Founder demand #9: drop on a node body (not socket) → auto-pick
          // first compatible unconnected input. Drop on empty → fire
          // lm-wire-promote for a future palette.
          const nodeEl = e.target.closest && e.target.closest('.lm-node');
          if (nodeEl) {
            const nodeId = nodeEl.getAttribute('data-node-id');
            const node = (LM_GRAPH.nodes || []).find(n => n.id === nodeId)
                       || (userNodes || []).find(n => n.id === nodeId);
            if (node) {
              const taken = new Set((LM_GRAPH.wires || []).filter(w => w.to[0] === nodeId).map(w => w.to[1]));
              const target = (node.ins || []).find(i => !taken.has(i.id) && (i.t === fromN.type || i.t === 'any'));
              if (target) {
                const check = precheckWire(fromN.nodeId, fromN.sockId, fromN.type, nodeId, target.id, target.t);
                if (check.ok) {
                  LM_GRAPH.wires = [...(LM_GRAPH.wires || []), {
                    from:[fromN.nodeId, fromN.sockId], to:[nodeId, target.id],
                  }];
                  saveCurrentGraph(); bumpGraph && bumpGraph();
                } else {
                  flashToast(`Refused: ${check.reason}`, 'err');
                }
              } else {
                flashToast('No compatible input', 'info');
              }
            }
          } else {
            try {
              window.dispatchEvent(new CustomEvent('lm-wire-promote', {
                detail: { from: fromN, x: e.clientX, y: e.clientY },
              }));
            } catch (ex) {}
          }
        }
        setWireDrag(null);
      }
      // ─── Persist final node position on drag-end (autosave) ────────
      if (dragRef.current && dragRef.current.mode === 'node') {
        const id = dragRef.current.id;
        let p = positions[id];
        if (p) {
          // Snap to 20px grid if the user enabled it from the canvas menu.
          if (snapToGrid) {
            const snapped = { x: Math.round(p.x / 20) * 20, y: Math.round(p.y / 20) * 20 };
            if (snapped.x !== p.x || snapped.y !== p.y) {
              setPositions(prev => ({ ...prev, [id]: snapped }));
              p = snapped;
            }
          }
          const node = (LM_GRAPH.nodes || []).find(n => n.id === id);
          if (node) { node.x = p.x; node.y = p.y; }
          saveCurrentGraph();
        }
      }
      dragRef.current = null;
    };
    // ESC cancels a pending click-to-wire (visible rubber-band line).
    const onKey = (e) => {
      if (e.key === 'Escape' && wireDrag) {
        if (wrapRef.current) wrapRef.current.querySelectorAll('[data-wire-hover]').forEach(n => n.removeAttribute('data-wire-hover'));
        setWireDrag(null);
      }
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.removeEventListener('keydown', onKey);
    };
  }, [zoom, wireDrag, positions, snapToGrid]);

  const onWheel = (e) => {
    // Guard: never zoom when the wheel happens inside any data-no-pan
    // overlay (composer, mini-map, modals, menus). Founder bug:
    // "drag/zoom clashing with composer" — root cause was the composer
    // not stopping the event in time. This is the canvas-side belt.
    if (e.target && e.target.closest && e.target.closest('[data-no-pan]')) return;
    e.preventDefault();
    const rect = wrapRef.current.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const delta = -e.deltaY * 0.0015;
    const next = Math.max(0.3, Math.min(2, +(zoom * (1 + delta)).toFixed(3)));
    if (next === zoom) return;
    setPan(p => ({ x: mx - (mx - p.x) * (next / zoom), y: my - (my - p.y) * (next / zoom) }));
    setZoom(next);
  };

  // ─── HTML5 drag-and-drop from sidebar library ───
  const onDragOver = (e) => {
    if (![...e.dataTransfer.types].includes('application/x-lm-node')) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    const rect = wrapRef.current.getBoundingClientRect();
    setDropTarget({ x: e.clientX - rect.left, y: e.clientY - rect.top });
  };
  const onDragLeave = (e) => {
    // ignore re-entries inside children
    if (e.target === wrapRef.current) setDropTarget(null);
  };
  const onDrop = (e) => {
    const raw = e.dataTransfer.getData('application/x-lm-node');
    if (!raw) return;
    e.preventDefault();
    let payload;
    try { payload = JSON.parse(raw); } catch { return; }
    const c = toCanvasCoords(e.clientX, e.clientY);
    addNodeFromLibrary && addNodeFromLibrary(payload, c.x - 110, c.y - 30);
    setDropTarget(null);
  };

  const nodeById = Object.fromEntries(
    (allNodes || []).map(n => [n.id, { ...n, x: positions[n.id]?.x ?? n.x, y: positions[n.id]?.y ?? n.y }])
  );

  const connectedIds = new Set([focusId]);
  (LM_GRAPH.wires || []).forEach(w => {
    if (w.from[0] === focusId) connectedIds.add(w.to[0]);
    if (w.to[0]   === focusId) connectedIds.add(w.from[0]);
  });

  const wires = (LM_GRAPH.wires || []).map((w, i) => {
    const fromNode = nodeById[w.from[0]];
    const toNode   = nodeById[w.to[0]];
    if (!fromNode || !toNode) return null;
    const fromIdx  = (fromNode.outs || []).findIndex(o => o.id === w.from[1]);
    const toIdx    = (toNode.ins   || []).findIndex(o => o.id === w.to[1]);
    if (fromIdx < 0 || toIdx < 0) return null;
    const x1 = fromNode.x + fromNode.w, y1 = fromNode.y + socketY(fromIdx);
    const x2 = toNode.x,                y2 = toNode.y + socketY(toIdx);
    const touches = w.from[0] === focusId || w.to[0] === focusId;
    return {
      i, x1, y1, x2, y2, raw: w,
      t: (fromNode.outs || [])[fromIdx]?.t,
      animated: fromNode.state === 'running' || toNode.state === 'running',
      focused: touches,
    };
  }).filter(Boolean);

  const toggleExpanded = (id) => setExpanded(e => ({ ...e, [id]: !e[id] }));
  const onResetView = () => { setPan({ x:14, y:12 }); setZoom(0.66); setCtxMenu(null); };

  // ─── Founder demand #8: delete focused node or selected wire on Delete/Backspace.
  // Use capture phase on BOTH window and document so QtWebEngine focus quirks
  // don't swallow the key.
  React.useEffect(() => {
    const onKey = (e) => {
      if (e.key !== 'Delete' && e.key !== 'Backspace') return;
      const tgt = e.target;
      // Don't steal Delete from inputs / textareas / contenteditable.
      const isEdit = tgt && (tgt.tagName === 'INPUT' || tgt.tagName === 'TEXTAREA' || tgt.isContentEditable);
      if (isEdit) return;
      if (selectedWire != null) {
        e.preventDefault();
        LM_GRAPH.wires = (LM_GRAPH.wires || []).filter((_, i) => i !== selectedWire);
        setSelectedWire(null);
        saveCurrentGraph(); bumpGraph && bumpGraph();
        flashToast('Wire deleted');
      } else if (focusId) {
        // v1.4 nodes live in LM_GRAPH.nodes. The userNodes parallel state
        // was deprecated — every node is deletable now. Founder bug:
        // 'why can't i delete the node named node?' — root cause this
        // branch returning silently when focusId wasn't in legacy state.
        const before = (LM_GRAPH.nodes || []).length;
        const filtered = (LM_GRAPH.nodes || []).filter(n => n.id !== focusId);
        if (filtered.length !== before) {
          e.preventDefault();
          LM_GRAPH.nodes = filtered;
          LM_GRAPH.wires = (LM_GRAPH.wires || []).filter(w => w.from[0] !== focusId && w.to[0] !== focusId);
          if (typeof removeUserNode === 'function') removeUserNode(focusId);
          setFocusId(null);
          saveCurrentGraph(); bumpGraph && bumpGraph();
          flashToast('Node deleted');
        }
      }
    };
    window.addEventListener('keydown', onKey, true);
    document.addEventListener('keydown', onKey, true);
    return () => {
      window.removeEventListener('keydown', onKey, true);
      document.removeEventListener('keydown', onKey, true);
    };
  }, [focusId, selectedWire, userNodes]);

  // ─── Founder demand #11: run the workflow on demand. Wire it up to keyboard
  // shortcut (Cmd/Ctrl+Enter) — the button on the rail also calls into here.
  // ─── Founder demand #14: Cmd/Ctrl+G composes the focused node + connected
  // chain into a subgraph composite. Right-click "Expand subgraph" undoes it.
  React.useEffect(() => {
    const onShortcut = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        bridgeCall('run_workflow', currentSid(), JSON.stringify(LM_GRAPH));
        flashToast('Workflow running…');
        return;
      }
      if ((e.metaKey || e.ctrlKey) && (e.key === 'g' || e.key === 'G')) {
        e.preventDefault();
        if (!focusId) { flashToast('Focus a node to group', 'info'); return; }
        const result = bridgeJson('compose_subgraph', JSON.stringify(LM_GRAPH), JSON.stringify([focusId]));
        if (result && result.graph) {
          LM_GRAPH.nodes = result.graph.nodes || [];
          LM_GRAPH.wires = result.graph.wires || [];
          saveCurrentGraph(); bumpGraph && bumpGraph(); flashToast('Composed subgraph');
        }
      }
    };
    window.addEventListener('keydown', onShortcut);
    return () => window.removeEventListener('keydown', onShortcut);
  }, [focusId]);

  return (
    <div
      ref={wrapRef}
      onMouseDown={onCanvasMouseDown}
      onContextMenu={onContextMenu}
      onWheel={onWheel}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      style={{
        gridColumn:'1', gridRow:'2', position:'relative', overflow:'hidden',
        background:LM.bgCanvas,
        backgroundImage:`radial-gradient(${LM.lineHair} 1px, transparent 1px)`,
        backgroundSize:`${20*zoom}px ${20*zoom}px`,
        backgroundPosition:`${pan.x}px ${pan.y}px`,
        cursor: dragRef.current?.mode === 'pan' ? 'grabbing' : 'grab',
        userSelect: dragRef.current ? 'none' : 'auto',
        outline: dropTarget ? `1px dashed ${LM.accent}66` : 'none',
        outlineOffset:-1,
      }}>
      <div style={{
        position:'absolute', left:pan.x, top:pan.y,
        transform:`scale(${zoom})`, transformOrigin:'0 0',
      }}>
        <svg width="2400" height="1400" style={{ position:'absolute', left:0, top:0, pointerEvents:'none', overflow:'visible' }}>
          <defs>
            <filter id="lm-wire-glow" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="1.5" result="b"/>
              <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>
          </defs>
          {wires.map(w => {
            const dx = Math.max(40, Math.abs(w.x2 - w.x1) * 0.5);
            const d = `M${w.x1},${w.y1} C${w.x1+dx},${w.y1} ${w.x2-dx},${w.y2} ${w.x2},${w.y2}`;
            const color = WIRE[w.t] || LM.inkSoft;
            const isSel = selectedWire === w.i;
            const strokeW = isSel ? 3.2 : (w.focused ? 2.4 : 1.4);
            const op = isSel ? 1 : (w.focused ? 1 : 0.5);
            return (
              <g key={w.i}>
                {/* Invisible fat path so the wire is easy to click. */}
                <path d={d} stroke="transparent" strokeWidth={16} fill="none"
                  style={{ pointerEvents:'stroke', cursor:'pointer' }}
                  onClick={(e) => { e.stopPropagation(); setSelectedWire(w.i); setNodeMenu(null); setCtxMenu(null); }}
                  onContextMenu={(e) => {
                    e.preventDefault(); e.stopPropagation();
                    const rect = wrapRef.current.getBoundingClientRect();
                    setSelectedWire(w.i);
                    setWireMenu({ x: e.clientX - rect.left, y: e.clientY - rect.top, idx: w.i, wire: w.raw });
                  }}/>
                <path d={d} stroke={color} strokeWidth={strokeW} fill="none" opacity={op}
                  filter={(w.focused || isSel) ? "url(#lm-wire-glow)" : undefined}
                  style={{ pointerEvents:'none' }}/>
                {w.animated && (
                  <path d={d} stroke={color} strokeWidth={strokeW} fill="none" strokeDasharray="6 10"
                    style={{ animation:'lmDash 0.9s linear infinite', pointerEvents:'none' }}/>
                )}
              </g>
            );
          })}
          {/* Wire-in-flight preview (founder demand #9: magnet snap) */}
          {wireDrag && (() => {
            const start = socketScreen(wireDrag.from.nodeId, wireDrag.from.sockId, 'out');
            if (!start) return null;
            // Convert screen→world (the svg lives inside the pan/zoom transform).
            const sx = (start.x - pan.x) / zoom;
            const sy = (start.y - pan.y) / zoom;
            // Endpoint snaps to hover socket if any, else follows mouse.
            const tx = wireDrag.hover ? (wireDrag.hover.x - pan.x) / zoom : (wireDrag.mouse.x - pan.x) / zoom;
            const ty = wireDrag.hover ? (wireDrag.hover.y - pan.y) / zoom : (wireDrag.mouse.y - pan.y) / zoom;
            const dx = Math.max(40, Math.abs(tx - sx) * 0.5);
            const d = `M${sx},${sy} C${sx+dx},${sy} ${tx-dx},${ty} ${tx},${ty}`;
            const col = wireDrag.hover ? (wireDrag.hover.ok ? LM.ok : LM.err)
                       : (WIRE[wireDrag.from.type] || LM.accent);
            return (
              <g pointerEvents="none">
                <path d={d} stroke={col} strokeWidth={2.6} fill="none"
                  strokeDasharray={wireDrag.hover ? '0' : '6 6'} opacity={0.9}/>
              </g>
            );
          })()}
        </svg>

        {(allNodes || []).map(n => {
          const pos = positions[n.id] || { x: n.x, y: n.y };
          return (
            <NodeRenderer
              key={n.id}
              n={{ ...n, x: pos.x, y: pos.y }}
              focused={n.id === focusId}
              dimmed={!connectedIds.has(n.id) && focusId !== n.id && !n._user}
              expanded={!!expanded[n.id]}
              onToggleExpand={() => toggleExpanded(n.id)}
              onDragStart={onNodeDragStart(n.id)}
              onFocus={() => setFocusId(n.id)}
              onSocketDown={onSocketDown}
              onSocketContextMenu={onSocketContextMenu}
              onNodeContextMenu={onNodeContextMenu}
            />
          );
        })}
      </div>

      {/* Drop-target ghost */}
      {dropTarget && (
        <div style={{
          position:'absolute', left:dropTarget.x - 90, top:dropTarget.y - 24,
          width:180, height:48, pointerEvents:'none',
          background:LM.accent + '14', border:`1.5px dashed ${LM.accent}`,
          borderRadius:6, display:'grid', placeItems:'center',
          fontFamily:LM.mono, fontSize:10.5, color:LM.accent, letterSpacing:'0.06em',
        }}>＋ DROP TO ADD NODE</div>
      )}

      <CanvasToolbar zoom={zoom} setZoom={(updater) => {
        setZoom(z => {
          const next = typeof updater === 'function' ? updater(z) : updater;
          return Math.max(0.3, Math.min(2, next));
        });
      }} onFit={onResetView} setLibraryOpen={setLibraryOpen} onRun={() => {
        bridgeCall('run_workflow', currentSid(), JSON.stringify(LM_GRAPH));
        flashToast('▶ Workflow running…');
      }}/>
      <FloatingComposer setLibraryOpen={setLibraryOpen} focusId={focusId}/>
      <MiniMap pan={pan} zoom={zoom} positions={positions} allNodes={allNodes}
        wrapRef={wrapRef} setPan={setPan}/>
      {ctxMenu && <CanvasMenu x={ctxMenu.x} y={ctxMenu.y}
        onAddNode={() => { setLibraryOpen(true); setCtxMenu(null); }}
        onFit={onResetView} onClose={() => setCtxMenu(null)}
        snapToGrid={snapToGrid}
        onPaste={async () => {
          // Read clipboard, attempt JSON.parse, splice as graph fragment.
          try {
            const raw = await navigator.clipboard.readText();
            const parsed = JSON.parse(raw);
            if (!parsed || !Array.isArray(parsed.nodes)) {
              flashToast('Clipboard is not a graph', 'err');
              return;
            }
            const offset = 24 + ((LM_GRAPH.nodes || []).length * 4);
            const idMap = {};
            const newNodes = parsed.nodes.map(n => {
              const newId = (n.id || 'node') + '_' + Date.now().toString(36).slice(-4) + Math.floor(Math.random()*100);
              idMap[n.id] = newId;
              return { ...n, id: newId, x: (n.x || 0) + offset, y: (n.y || 0) + offset, _user: true };
            });
            LM_GRAPH.nodes = [...(LM_GRAPH.nodes || []), ...newNodes];
            if (Array.isArray(parsed.wires)) {
              const newWires = parsed.wires
                .filter(w => idMap[w.from[0]] && idMap[w.to[0]])
                .map(w => ({ ...w, from:[idMap[w.from[0]], w.from[1]], to:[idMap[w.to[0]], w.to[1]] }));
              LM_GRAPH.wires = [...(LM_GRAPH.wires || []), ...newWires];
            }
            saveCurrentGraph(); bumpGraph && bumpGraph();
            flashToast(`Pasted ${newNodes.length} node${newNodes.length===1?'':'s'}`);
          } catch (ex) {
            flashToast('Clipboard is not a graph', 'err');
          }
        }}
        onZoom100={() => { setZoom(1); }}
        onToggleSnap={() => setSnapToGrid(s => !s)}
        onAutoLayout={() => {
          // Topological layout: BFS from sources to compute each node's depth,
          // group by column, lay out at 240px x-stride and 140px y-stride.
          const nodes = [...(LM_GRAPH.nodes || []), ...(userNodes || [])];
          const wires = LM_GRAPH.wires || [];
          if (nodes.length === 0) { flashToast('No nodes to layout', 'info'); return; }
          const incoming = new Map(nodes.map(n => [n.id, 0]));
          const outAdj = new Map(nodes.map(n => [n.id, []]));
          wires.forEach(w => {
            if (incoming.has(w.to[0])) incoming.set(w.to[0], incoming.get(w.to[0]) + 1);
            if (outAdj.has(w.from[0])) outAdj.get(w.from[0]).push(w.to[0]);
          });
          const depth = new Map();
          const queue = [];
          nodes.forEach(n => { if ((incoming.get(n.id) || 0) === 0) { depth.set(n.id, 0); queue.push(n.id); } });
          while (queue.length) {
            const id = queue.shift();
            const d = depth.get(id) || 0;
            (outAdj.get(id) || []).forEach(child => {
              const childDepth = Math.max(depth.get(child) || 0, d + 1);
              if (depth.get(child) !== childDepth) {
                depth.set(child, childDepth);
                queue.push(child);
              }
            });
          }
          // Any node never assigned (cycles) goes at maxDepth+1.
          let maxDepth = 0;
          depth.forEach(d => { if (d > maxDepth) maxDepth = d; });
          nodes.forEach(n => { if (!depth.has(n.id)) depth.set(n.id, maxDepth + 1); });
          // Group by depth, sort within each column by current y for stability.
          const cols = {};
          nodes.forEach(n => {
            const d = depth.get(n.id);
            if (!cols[d]) cols[d] = [];
            cols[d].push(n);
          });
          const X_STRIDE = 240, Y_STRIDE = 140, MARGIN_X = 40, MARGIN_Y = 40;
          const newPositions = { ...positions };
          Object.keys(cols).forEach(d => {
            const list = cols[d].sort((a, b) => (a.y || 0) - (b.y || 0));
            list.forEach((n, ix) => {
              const x = MARGIN_X + Number(d) * X_STRIDE;
              const y = MARGIN_Y + ix * Y_STRIDE;
              newPositions[n.id] = { x, y };
              n.x = x; n.y = y;
            });
          });
          setPositions(newPositions);
          saveCurrentGraph(); bumpGraph && bumpGraph();
          flashToast('Auto-laid out');
        }}
        onResetPositions={() => {
          // Restore from origPositionsRef (and back into the node objects).
          const fresh = {};
          (allNodes || []).forEach(n => {
            const o = origPositionsRef.current[n.id];
            if (o) {
              fresh[n.id] = { x: o.x, y: o.y };
              n.x = o.x; n.y = o.y;
            } else {
              fresh[n.id] = { x: n.x, y: n.y };
            }
          });
          setPositions(fresh);
          saveCurrentGraph(); bumpGraph && bumpGraph();
          flashToast('Positions reset');
        }}
        onClearAll={() => {
          LM_GRAPH.wires = [];
          // Don't blow up the demo nodes; only user-added are deletable.
          (userNodes || []).forEach(n => removeUserNode && removeUserNode(n.id));
          saveCurrentGraph(); bumpGraph && bumpGraph(); flashToast('Cleared');
        }}/>}
      {nodeMenu && (
        <NodeMenu x={nodeMenu.x} y={nodeMenu.y} nodeId={nodeMenu.id}
          onClose={() => setNodeMenu(null)}
          onRun={() => { bridgeCall('run_node', currentSid(), nodeMenu.id, JSON.stringify(LM_GRAPH)); flashToast('Running node…'); }}
          onFreeze={() => {
            const node = (LM_GRAPH.nodes || []).find(n => n.id === nodeMenu.id);
            if (node) { node.frozen = !node.frozen; saveCurrentGraph(); bumpGraph && bumpGraph(); }
          }}
          onRename={() => {
            const node = (LM_GRAPH.nodes || []).find(n => n.id === nodeMenu.id)
                       || (userNodes || []).find(n => n.id === nodeMenu.id);
            if (!node) return;
            const next = window.prompt('Rename node', node.title || '');
            if (next != null) { node.title = next; saveCurrentGraph(); bumpGraph && bumpGraph(); }
          }}
          onDuplicate={() => {
            const node = (LM_GRAPH.nodes || []).find(n => n.id === nodeMenu.id)
                       || (userNodes || []).find(n => n.id === nodeMenu.id);
            if (!node || !addNodeFromLibrary) return;
            addNodeFromLibrary({ ...node, id: undefined, cat: node.cat, title: (node.title||'')+' copy', sub: node.sub }, (node.x||0)+30, (node.y||0)+30);
          }}
          onDisconnect={() => {
            LM_GRAPH.wires = (LM_GRAPH.wires || []).filter(w => w.from[0] !== nodeMenu.id && w.to[0] !== nodeMenu.id);
            saveCurrentGraph(); bumpGraph && bumpGraph(); flashToast('Node disconnected');
          }}
          onDelete={() => {
            // Founder demand: deletion always works. v1.4 nodes live in
            // LM_GRAPH.nodes (the `userNodes` parallel state was deprecated).
            // Pull from LM_GRAPH directly; cascade-remove incident wires.
            const before = (LM_GRAPH.nodes || []).length;
            LM_GRAPH.nodes = (LM_GRAPH.nodes || []).filter(n => n.id !== nodeMenu.id);
            if ((LM_GRAPH.nodes || []).length === before) {
              flashToast('Node not found', 'err');
              return;
            }
            LM_GRAPH.wires = (LM_GRAPH.wires || []).filter(w => w.from[0] !== nodeMenu.id && w.to[0] !== nodeMenu.id);
            // Also clean userNodes for any legacy strays.
            if (typeof removeUserNode === 'function') removeUserNode(nodeMenu.id);
            setFocusId(null);
            saveCurrentGraph(); bumpGraph && bumpGraph(); flashToast('Node deleted');
          }}
          onProperties={() => { setFocusId(nodeMenu.id); }}
          onSaveSkill={() => {
            // Bridge slot is `save_as_skill(name, payload_json)` — there is no
            // `save_node_as_skill`. Build a tiny single-node subgraph payload
            // (the focused node only). A richer reachable-subgraph build can
            // come later; this at least persists the skill.
            const node = (LM_GRAPH.nodes || []).find(n => n.id === nodeMenu.id)
                       || (userNodes || []).find(n => n.id === nodeMenu.id);
            if (!node) { flashToast('Node not found', 'err'); return; }
            const payload = JSON.stringify({ nodes:[node], wires:[] });
            bridgeCall('save_as_skill', node.title || node.id, payload);
            flashToast('Saved as skill');
          }}
          onExpand={() => {
            const node = (LM_GRAPH.nodes || []).find(n => n.id === nodeMenu.id);
            if (!node || node.cat !== 'subgraph.user') { flashToast('Not a subgraph', 'info'); return; }
            // Bridge returns `{ok, graph: {nodes, wires}}` (not `{ok, nodes, wires}`).
            const result = bridgeJson('expand_subgraph', JSON.stringify(LM_GRAPH), nodeMenu.id);
            if (result && result.ok && result.graph) {
              LM_GRAPH.nodes = result.graph.nodes || [];
              LM_GRAPH.wires = result.graph.wires || [];
              saveCurrentGraph(); bumpGraph && bumpGraph(); flashToast('Subgraph expanded');
            } else if (result && result.error) {
              flashToast(`Expand failed: ${result.error}`, 'err');
            }
          }}/>
      )}
      {wireMenu && (
        <WireMenu x={wireMenu.x} y={wireMenu.y}
          onClose={() => setWireMenu(null)}
          onPickSource={() => {
            // Bridge `list_wire_fields(node_id, port_name, sample_json)` returns
            // `{paths:[...], sample, node, port}`. The wire here is the one
            // right-clicked; its `from` socket is the source.
            const wire = (LM_GRAPH.wires || [])[wireMenu.idx];
            if (!wire) { setWireMenu(null); return; }
            const sample = wire._preview != null ? JSON.stringify(wire._preview) : '';
            const res = bridgeJson('list_wire_fields', wire.from[0], wire.from[1], sample);
            const paths = (res && res.paths) || [];
            if (!paths.length) { setWireMenu(null); flashToast('No fields detected', 'info'); return; }
            setWireFieldPicker({ wireIdx: wireMenu.idx, side: 'src', paths });
            setWireMenu(null);
          }}
          onPickDest={() => {
            // The destination's schema is unknown from a wire alone, so we
            // introspect the *source* preview the same way — the picked path
            // is then assigned to `dst_field` on the wire (router applies the
            // remapping at runtime).
            const wire = (LM_GRAPH.wires || [])[wireMenu.idx];
            if (!wire) { setWireMenu(null); return; }
            const sample = wire._preview != null ? JSON.stringify(wire._preview) : '';
            const res = bridgeJson('list_wire_fields', wire.from[0], wire.from[1], sample);
            const paths = (res && res.paths) || [];
            if (!paths.length) { setWireMenu(null); flashToast('No fields detected', 'info'); return; }
            setWireFieldPicker({ wireIdx: wireMenu.idx, side: 'dst', paths });
            setWireMenu(null);
          }}
          onDisconnect={() => {
            LM_GRAPH.wires = (LM_GRAPH.wires || []).filter((_, i) => i !== wireMenu.idx);
            setSelectedWire(null);
            saveCurrentGraph(); bumpGraph && bumpGraph(); flashToast('Wire deleted');
          }}/>
      )}
      {wireFieldPicker && (
        <WireFieldPicker {...wireFieldPicker}
          onClose={() => setWireFieldPicker(null)}
          onPick={(path) => {
            const wire = (LM_GRAPH.wires || [])[wireFieldPicker.wireIdx];
            if (wire) {
              if (wireFieldPicker.side === 'src') wire.src_field = path;
              else wire.dst_field = path;
              saveCurrentGraph(); bumpGraph && bumpGraph();
              flashToast(`${wireFieldPicker.side === 'src' ? 'Source' : 'Destination'} field set: ${path}`);
            }
            setWireFieldPicker(null);
          }}/>
      )}
      {toast && (
        <div data-no-pan style={{
          position:'absolute', left:'50%', top:14, transform:'translateX(-50%)',
          padding:'6px 12px', background:toast.kind === 'err' ? LM.err : LM.bgPanel,
          border:`1px solid ${toast.kind === 'err' ? LM.err : LM.line}`, borderRadius:5,
          fontFamily:LM.mono, fontSize:10.5, color:toast.kind === 'err' ? '#fff' : LM.ink,
          letterSpacing:'0.04em', zIndex:40, animation:'lmSlideIn .15s ease-out',
        }}>{toast.msg}</div>
      )}
      <CanvasHint/>
    </div>
  );
};

// ─── Right-click on node → action menu (founder demand #8) ─────────
const NodeMenu = ({ x, y, nodeId, onRun, onFreeze, onRename, onDuplicate, onDisconnect, onDelete, onProperties, onSaveSkill, onExpand, onClose }) => {
  React.useEffect(() => {
    const dismiss = () => onClose();
    document.addEventListener('click', dismiss);
    const onKey = (e) => e.key === 'Escape' && dismiss();
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('click', dismiss);
      document.removeEventListener('keydown', onKey);
    };
  }, [onClose]);
  const isSubgraph = !!(LM_GRAPH.nodes || []).find(n => n.id === nodeId && n.cat === 'subgraph.user');
  const items = [
    { i:'▶', t:'Run',             on:onRun },
    { i:'❄', t:'Freeze / unfreeze', on:onFreeze },
    { i:'✎', t:'Rename',          on:onRename },
    { i:'⎘', t:'Duplicate',       on:onDuplicate },
    { i:'★', t:'Save as Skill',   on:onSaveSkill },
    isSubgraph && { i:'⤢', t:'Expand subgraph', on:onExpand },
    { sep:true },
    { i:'⊝', t:'Disconnect all',  on:onDisconnect },
    { i:'ⓘ', t:'Properties',      on:onProperties },
    { sep:true },
    { i:'✕', t:'Delete',          on:onDelete, danger:true },
  ].filter(Boolean);
  return (
    <div data-no-pan onClick={e => e.stopPropagation()} style={{
      position:'absolute', left:x, top:y, zIndex:30,
      background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:7,
      boxShadow:'0 16px 36px rgba(0,0,0,.55)', padding:5, minWidth:200,
      animation:'lmSlideIn .12s ease-out',
    }}>
      {items.map((it, i) => it.sep ? (
        <div key={i} style={{ height:1, background:LM.lineSoft, margin:'4px 4px' }}/>
      ) : (
        <button key={i} onClick={() => { it.on && it.on(); onClose(); }} style={{
          width:'100%', display:'flex', alignItems:'center', gap:10, padding:'6px 10px',
          background:'transparent', border:0, borderRadius:4, cursor:'pointer',
          color: it.danger ? LM.err : LM.ink, fontFamily:LM.sans, fontSize:12.5, textAlign:'left',
        }}
        onMouseEnter={e => e.currentTarget.style.background = LM.bgHover}
        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
          <span style={{ width:14, color: it.danger ? LM.err : LM.inkMuted, fontFamily:LM.mono, fontSize:11, textAlign:'center' }}>{it.i}</span>
          <span style={{ flex:1 }}>{it.t}</span>
        </button>
      ))}
    </div>
  );
};

// ─── Right-click on wire → menu (founder demand #8) ─────────────
const WireMenu = ({ x, y, onDisconnect, onPickSource, onPickDest, onClose }) => {
  React.useEffect(() => {
    const dismiss = () => onClose();
    document.addEventListener('click', dismiss);
    const onKey = (e) => e.key === 'Escape' && dismiss();
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('click', dismiss);
      document.removeEventListener('keydown', onKey);
    };
  }, [onClose]);
  const items = [
    { i:'⇄', t:'Pick source field…',      on:onPickSource },
    { i:'⇆', t:'Pick destination field…', on:onPickDest },
    { sep:true },
    { i:'⊝', t:'Disconnect',              on:onDisconnect, danger:true },
  ];
  return (
    <div data-no-pan onClick={e => e.stopPropagation()} style={{
      position:'absolute', left:x, top:y, zIndex:30,
      background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:7,
      boxShadow:'0 16px 36px rgba(0,0,0,.55)', padding:5, minWidth:200,
      animation:'lmSlideIn .12s ease-out',
    }}>
      {items.map((it, i) => it.sep ? (
        <div key={i} style={{ height:1, background:LM.lineSoft, margin:'4px 4px' }}/>
      ) : (
        <button key={i} onClick={() => { it.on && it.on(); onClose(); }} style={{
          width:'100%', display:'flex', alignItems:'center', gap:10, padding:'6px 10px',
          background:'transparent', border:0, borderRadius:4, cursor:'pointer',
          color: it.danger ? LM.err : LM.ink, fontFamily:LM.sans, fontSize:12.5, textAlign:'left',
        }}
        onMouseEnter={e => e.currentTarget.style.background = LM.bgHover}
        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
          <span style={{ width:14, color: it.danger ? LM.err : LM.inkMuted, fontFamily:LM.mono, fontSize:11, textAlign:'center' }}>{it.i}</span>
          <span style={{ flex:1 }}>{it.t}</span>
        </button>
      ))}
    </div>
  );
};

// ─── Wire-field picker modal ───────────────────────────────────
// Shown after a user picks "Pick source/destination field…" in the WireMenu.
// Lists the dotted paths returned by `bridge.list_wire_fields`. Click a row
// to assign it to wire.src_field or wire.dst_field.
const WireFieldPicker = ({ wireIdx, side, paths, onPick, onClose }) => {
  React.useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div data-no-pan onClick={onClose} style={{
      position:'fixed', inset:0, background:'rgba(0,0,0,0.45)', zIndex:50,
      display:'grid', placeItems:'center',
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        minWidth:340, maxWidth:520, maxHeight:'70vh', overflow:'auto',
        background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:8,
        boxShadow:'0 20px 50px rgba(0,0,0,.6)', padding:'10px 12px',
        fontFamily:LM.sans, color:LM.ink,
      }}>
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between',
          marginBottom:8, paddingBottom:6, borderBottom:`1px solid ${LM.lineSoft}` }}>
          <span style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, letterSpacing:'0.14em' }}>
            PICK {side === 'src' ? 'SOURCE' : 'DESTINATION'} FIELD
          </span>
          <button onClick={onClose} style={{
            background:'transparent', border:0, color:LM.inkMuted, fontSize:14, cursor:'pointer',
          }}>×</button>
        </div>
        {(!paths || paths.length === 0) ? (
          <div style={{ padding:10, color:LM.inkMuted, fontSize:12 }}>No fields detected.</div>
        ) : (
          <div style={{ display:'flex', flexDirection:'column', gap:2 }}>
            {paths.map((p, i) => (
              <button key={i} onClick={() => onPick(p)} style={{
                textAlign:'left', padding:'7px 9px', background:'transparent', border:0,
                borderRadius:4, cursor:'pointer', fontFamily:LM.mono, fontSize:12, color:LM.ink,
              }}
              onMouseEnter={e => e.currentTarget.style.background = LM.bgHover}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>{p}</button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

// ─── CSS hooks for wire-hover glow on snap-target sockets ────────────
const _LM_WIRE_STYLES = `
[data-wire-hover="ok"] [data-lm-socket-dot="1"] { box-shadow: 0 0 0 3px ${LM.ok}66, 0 0 12px ${LM.ok} !important; }
[data-wire-hover="bad"] [data-lm-socket-dot="1"] { box-shadow: 0 0 0 3px ${LM.err}66, 0 0 12px ${LM.err} !important; }
`;
const _injectWireStyles = (() => {
  if (typeof document === 'undefined') return;
  if (document.getElementById('lm-wire-styles')) return;
  const s = document.createElement('style');
  s.id = 'lm-wire-styles';
  s.textContent = _LM_WIRE_STYLES;
  document.head.appendChild(s);
})();

// Hint strip — sits above composer, auto-fades after first interaction or 6s
// One-time per session: once dismissed, never returns.
const CanvasHint = () => {
  const [visible, setVisible] = React.useState(() => {
    try { return !sessionStorage.getItem('lm-hint-dismissed'); } catch { return true; }
  });
  const dismiss = React.useCallback(() => {
    setVisible(false);
    try { sessionStorage.setItem('lm-hint-dismissed','1'); } catch {}
  }, []);
  React.useEffect(() => {
    if (!visible) return;
    const t = setTimeout(dismiss, 6000);
    const onAny = () => dismiss();
    window.addEventListener('mousedown', onAny, { once:true });
    window.addEventListener('keydown',   onAny, { once:true });
    window.addEventListener('wheel',     onAny, { once:true, passive:true });
    return () => {
      clearTimeout(t);
      window.removeEventListener('mousedown', onAny);
      window.removeEventListener('keydown',   onAny);
      window.removeEventListener('wheel',     onAny);
    };
  }, [visible, dismiss]);
  if (!visible) return null;
  return (
    <div data-no-pan style={{
      position:'absolute', left:'50%', bottom:140, transform:'translateX(-50%)',
      display:'flex', alignItems:'center', gap:8,
      background:LM.bgPanel+'cc', backdropFilter:'blur(6px)',
      border:`1px solid ${LM.lineSoft}`, borderRadius:5, padding:'4px 10px',
      fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.04em',
      pointerEvents:'none',
      animation:'lmHintFade 6s ease-in-out forwards',
      zIndex:5,
    }}>
      <span>scroll → zoom</span>
      <span style={{ color:LM.inkDim }}>·</span>
      <span>drag → pan</span>
      <span style={{ color:LM.inkDim }}>·</span>
      <span>right-click → menu</span>
    </div>
  );
};

// Right-click canvas context menu
const CanvasMenu = ({ x, y, onAddNode, onFit, onClose, onClearAll, onPaste, onZoom100, onToggleSnap, onAutoLayout, onResetPositions, snapToGrid }) => {
  React.useEffect(() => {
    const dismiss = () => onClose();
    document.addEventListener('click', dismiss);
    document.addEventListener('keydown', e => e.key === 'Escape' && dismiss());
    return () => document.removeEventListener('click', dismiss);
  }, [onClose]);
  const items = [
    { i:'＋',  t:'Add node…',          k:'⌘L',  on:onAddNode },
    { i:'⎘',  t:'Paste',               k:'⌘V',  on:onPaste },
    { sep:true },
    { i:'⌴',  t:'Fit graph to view',   k:'⌘0',  on:onFit },
    { i:'⊜',  t:'Zoom to 100%',        k:'⌘1',  on:onZoom100 },
    { sep:true },
    { i:'·',  t:'Snap to grid',        toggle:true, on: !!snapToGrid, action: onToggleSnap },
    { i:'⧉',  t:'Auto-layout',         k:'⌘⇧L', on:onAutoLayout },
    { sep:true },
    { i:'↻',  t:'Reset positions',     k:'⌘⇧R', on:onResetPositions },
    { i:'✕',  t:'Clear all nodes',     k:'',    danger:true, on:onClearAll },
  ];
  return (
    <div data-no-pan onClick={e => e.stopPropagation()} style={{
      position:'absolute', left:x, top:y, zIndex:30,
      background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:7,
      boxShadow:'0 16px 36px rgba(0,0,0,.55)', padding:5, minWidth:220,
      animation:'lmSlideIn .12s ease-out',
    }}>
      {items.map((it, i) => it.sep ? (
        <div key={i} style={{ height:1, background:LM.lineSoft, margin:'4px 4px' }}/>
      ) : (
        <button key={i} onClick={(e) => {
          // Toggle items keep the menu open so the user can see the state flip.
          if (it.toggle) { e.stopPropagation(); it.action && it.action(); return; }
          it.on && it.on(); onClose();
        }} style={{
          width:'100%', display:'flex', alignItems:'center', gap:10, padding:'6px 10px',
          background:'transparent', border:0, borderRadius:4, cursor:'pointer',
          color: it.danger ? LM.err : LM.ink, fontFamily:LM.sans, fontSize:12.5, textAlign:'left',
        }}
        onMouseEnter={e => e.currentTarget.style.background = LM.bgHover}
        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
          <span style={{ width:14, color: it.danger ? LM.err : LM.inkMuted, fontFamily:LM.mono, fontSize:11, textAlign:'center' }}>{it.i}</span>
          <span style={{ flex:1 }}>{it.t}</span>
          {it.toggle && (
            <span style={{
              width:22, height:12, borderRadius:999,
              background: it.on ? LM.accent : LM.lineSoft, position:'relative',
            }}>
              <span style={{ position:'absolute', top:1, left: it.on ? 11 : 1, width:10, height:10, borderRadius:'50%', background:'#fff' }}/>
            </span>
          )}
          {it.k && <kbd style={kbd()}>{it.k}</kbd>}
        </button>
      ))}
    </div>
  );
};

// ─── nodes dispatcher ───
const NodeRenderer = ({ n, focused, dimmed, expanded, onToggleExpand, onDragStart, onFocus, onSocketDown, onSocketContextMenu, onNodeContextMenu }) => {
  // Founder demand #15: spread defaults so a graph from disk with missing
  // arrays (older sessions, hand-edited JSON) doesn't crash the renderer.
  n = { ins:[], outs:[], messages:[], params:[], ...n };
  const cat = catMeta(n.cat);

  // Founder demand #12: every node auto-registers as MCP server on mount,
  // unregisters on unmount. The bridge fans out the envelope so other
  // canvases / sessions can reach this node by id.
  React.useEffect(() => {
    try {
      const envelope = JSON.stringify({
        id: n.id, type: n.title || n.cat, category: n.cat,
        inputs: (n.ins || []).map(i => ({ id:i.id, type:i.t, label:i.label })),
        outputs: (n.outs || []).map(o => ({ id:o.id, type:o.t, label:o.label })),
        config: n.config || {},
      });
      bridgeCall('register_node_mcp', n.id, n.title || n.cat, envelope);
    } catch (e) {}
    return () => { try { bridgeCall('unregister_node_mcp', n.id); } catch (e) {} };
  }, [n.id]);
  // AI nodes can expand horizontally for full conversation + search
  const w = (n.cat === 'ai' && expanded) ? Math.max(520, n.w) : n.w;
  const isAi = n.cat === 'ai';
  // Sockets are absolutely positioned, so they don't stretch the node's own
  // box. With the wider SOCKET_STEP a static n.h no longer covers nodes with
  // many ports — the deepest socket would hang past the bottom border. Floor
  // the height at (deepest socket centre + radius + bottom padding).
  const portRows = Math.max(n.ins.length, n.outs.length);
  const socketsMinH = portRows > 0 ? socketY(portRows - 1) + SOCKET_R + 12 : 0;
  const minH = Math.max(n.h || 0, socketsMinH);
  return (
    <div className="lm-node" data-node-id={n.id} onClick={onFocus}
      onContextMenu={onNodeContextMenu && ((e) => onNodeContextMenu(e, n.id))}
      style={{
        position:'absolute', left:n.x, top:n.y, width:w, minHeight:minH,
        background:LM.bgPanel,
        borderStyle:'solid',
        borderWidth:'2px 1px 1px 1px',
        borderColor: `${cat.col} ${focused ? LM.accent+'cc' : LM.line} ${focused ? LM.accent+'cc' : LM.line} ${focused ? LM.accent+'cc' : LM.line}`,
        borderRadius:9, color:LM.ink, fontFamily:LM.sans,
        boxShadow: focused
          ? `0 0 0 3px ${LM.accentDim}, 0 8px 24px rgba(0,0,0,.4)`
          : '0 2px 8px rgba(0,0,0,.35)',
        cursor: 'default',
        opacity: dimmed ? 0.42 : 1,
        transition:'border-color .12s, box-shadow .12s, opacity .15s, width .15s',
      }}>
      {/* Title bar — drag handle */}
      <div onMouseDown={onDragStart}
        style={{
          padding:'7px 11px', display:'flex', alignItems:'center', gap:8,
          borderBottom:`1px solid ${LM.lineSoft}`,
          background: focused ? LM.bgSoft : 'transparent',
          cursor:'move',
          borderTopLeftRadius:7, borderTopRightRadius:7,
        }}>
        <span style={{ width:14, height:14, display:'grid', placeItems:'center', color:cat.col, fontFamily:LM.mono, fontSize:11 }}>{cat.icon}</span>
        <span style={{ fontFamily:LM.mono, fontSize:8.5, color:cat.col, letterSpacing:'0.18em' }}>{cat.label}</span>
        <div style={{ flex:1 }}/>
        {n.state && <NodeStateDot s={n.state}/>}
        {n.ms && !n.state && <span style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted }}>{n.ms}</span>}
        {isAi && (
          <button onClick={(e) => { e.stopPropagation(); onToggleExpand(); }} title={expanded ? 'Collapse' : 'Expand & search'} style={{
            width:18, height:18, padding:0, border:0, borderRadius:3,
            background:'transparent', color:LM.inkMuted, cursor:'pointer',
            display:'grid', placeItems:'center', fontFamily:LM.mono, fontSize:10, marginLeft:2,
          }}
          onMouseEnter={e => { e.currentTarget.style.background = LM.bgHover; e.currentTarget.style.color = LM.ink; }}
          onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = LM.inkMuted; }}>
            {expanded ? '↖' : '⤢'}
          </button>
        )}
      </div>

      {/* Body */}
      <div style={{ padding:'9px 12px 11px' }}>
        <div style={{ fontSize:13, fontWeight:500, color:LM.ink, marginBottom:2, lineHeight:1.2 }}>{n.title}</div>
        {n.sub && <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, letterSpacing:'0.04em' }}>{n.sub}</div>}
        <NodeBody n={n} expanded={expanded} onToggleExpand={onToggleExpand}/>
      </div>

      {/* Sockets */}
      {(n.ins || []).map((s, i) => (
        <Socket key={'in-'+s.id} side="in" i={i} t={s.t} label={s.label}
          nodeId={n.id} sockId={s.id}
          onMouseDown={onSocketDown && ((e) => onSocketDown(e, n.id, s.id, 'in', s.t))}
          onContextMenu={onSocketContextMenu && ((e) => onSocketContextMenu(e, n.id, s.id, 'in'))}/>
      ))}
      {(n.outs || []).map((s, i) => (
        <Socket key={'out-'+s.id} side="out" i={i} t={s.t} label={s.label}
          nodeId={n.id} sockId={s.id}
          onMouseDown={onSocketDown && ((e) => onSocketDown(e, n.id, s.id, 'out', s.t))}
          onContextMenu={onSocketContextMenu && ((e) => onSocketContextMenu(e, n.id, s.id, 'out'))}/>
      ))}
    </div>
  );
};

const NodeStateDot = ({ s }) => {
  const col = s === 'running' ? LM.accent : s === 'queued' ? LM.inkMuted : LM.ok;
  return (
    <span style={{ display:'flex', alignItems:'center', gap:5 }}>
      <span style={{
        width:6, height:6, borderRadius:'50%', background: col,
        boxShadow: s === 'running' ? `0 0 0 2px ${col}22` : 'none',
        animation: s === 'running' ? 'lmPulse 1.2s infinite' : 'none',
      }}/>
      <span style={{ fontFamily:LM.mono, fontSize:9, color:col, letterSpacing:'0.1em', textTransform:'uppercase' }}>{s}</span>
    </span>
  );
};

// Founder demand #9: every socket needs to be discoverable by the wire-drag
// engine via data attributes so it can scan inputs each onMove and snap.
const Socket = ({ side, i, t, label, nodeId, sockId, onMouseDown, onContextMenu }) => {
  const col = WIRE[t] || LM.inkSoft;
  return (
    <div
      data-lm-socket={`${side}:${nodeId}:${sockId}`}
      data-side={side} data-node={nodeId} data-pin={sockId} data-type={t}
      onMouseDown={onMouseDown}
      onContextMenu={onContextMenu}
      style={{
        position:'absolute', top: socketY(i) - SOCKET_R,
        [side === 'in' ? 'left' : 'right']: -SOCKET_R,
        display:'flex', alignItems:'center', gap:6,
        flexDirection: side === 'in' ? 'row' : 'row-reverse',
        // pointerEvents enabled so we can grab sockets to drag wires.
        pointerEvents:'auto', cursor:'crosshair',
      }}>
      <span
        data-lm-socket-dot="1"
        style={{
          width: SOCKET_R*2, height: SOCKET_R*2, borderRadius:'50%',
          background: side === 'out' ? col : LM.bgPanel,
          border:`1.5px solid ${col}`, boxShadow:`0 0 0 2px ${LM.bgCanvas}`,
        }}/>
      <span style={{
        fontFamily:LM.mono, fontSize:8.5, color:LM.inkMuted, letterSpacing:'0.04em',
        whiteSpace:'nowrap', padding:'0 4px',
        opacity: label ? 0.85 : 0, pointerEvents:'none',
      }}>{label}</span>
    </div>
  );
};

// ─── per-category body content ───
const NodeBody = ({ n, expanded, onToggleExpand }) => {
  switch (n.cat) {
    case 'host':         return <HostBody n={n}/>;
    case 'ai':           return <AIBody n={n} expanded={expanded} onToggleExpand={onToggleExpand}/>;
    case 'read':         return <ReadBody n={n}/>;
    case 'filter':       return <FilterBody n={n}/>;
    case 'transform':    return <TransformBody n={n}/>;
    case 'logic':        return <LogicBody n={n}/>;
    case 'compose':      return <ComposeBody n={n}/>;
    case 'annotate':     return <AnnotateBody n={n}/>;
    case 'output':       return <OutputBody n={n}/>;
    case 'connector_op': return <ConnectorOpBody n={n}/>;
    case 'custom':       return <CustomBody n={n}/>;
    default:             return null;
  }
};

// ─── Custom-node body — an AI-minted node type. Shows the typed I/O
// contract the Node Smith generated. The node is real (registered in the
// workflow registry server-side); it cooks as part of a graph run. No
// per-node run button — custom nodes aren't a fire-and-forget op, they're
// graph cells. Founder demand 2026-05-16.
const CustomBody = ({ n }) => {
  const ins = n.ins || [], outs = n.outs || [];
  const Row = ({ s, dir }) => (
    <div style={{ display:'flex', alignItems:'center', gap:6, fontFamily:LM.mono, fontSize:9.5 }}>
      <span style={{ color: dir === 'in' ? LM.cyan : LM.ok, width:9, flexShrink:0 }}>
        {dir === 'in' ? '→' : '←'}
      </span>
      <span style={{ color:LM.ink, flex:1, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
        {s.label || s.id}
      </span>
      <span style={{ color:LM.inkMuted }}>{s.t || 'any'}</span>
    </div>
  );
  return (
    <div style={{ marginTop:8, display:'flex', flexDirection:'column', gap:4 }}>
      {ins.length === 0 && outs.length === 0
        ? <span style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkDim }}>no declared ports</span>
        : <>
            {ins.map(s => <Row key={'i'+s.id} s={s} dir="in"/>)}
            {outs.map(s => <Row key={'o'+s.id} s={s} dir="out"/>)}
          </>}
      {n.custom_type && (
        <span style={{ fontFamily:LM.mono, fontSize:8, color:LM.inkDim, letterSpacing:'0.04em', marginTop:2 }}>
          {n.custom_type}
        </span>
      )}
    </div>
  );
};

// ─── Connector-op node body — a live host operation. Shows the op's
// typed params (compact), a Run button, and the last result. Running it
// calls bridge.run_connector_op; the result lands via the connector_op_done
// signal (handled in StudioLM root). Founder demand 2026-05-15.
const ConnectorOpBody = ({ n }) => {
  const params = n.params || [];
  const running = !!n.op_running;
  const res = n.op_result;   // {ok, value_preview, error, elapsed_ms}
  const col = CONNECTOR_COLORS[n.host] || LM.cyan;
  const onRun = (e) => {
    e.stopPropagation();
    try {
      window.dispatchEvent(new CustomEvent('lm-run-connector-op', {
        detail: { node_id: n.id },
      }));
    } catch (err) {}
  };
  return (
    <div style={{ marginTop:8, display:'flex', flexDirection:'column', gap:6 }}>
      {params.length > 0 && (
        <div style={{ display:'flex', flexDirection:'column', gap:3 }}>
          {params.slice(0, 4).map((p, i) => (
            <div key={i} style={{ display:'flex', alignItems:'center', gap:6,
              fontFamily:LM.mono, fontSize:9.5 }}>
              <span style={{ color:LM.inkMuted, width:84, flexShrink:0,
                overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
                {p.label || p.k}{p.required ? ' *' : ''}
              </span>
              <span style={{ flex:1, color:LM.ink, background:LM.bg,
                border:`1px solid ${LM.lineSoft}`, borderRadius:3, padding:'2px 6px',
                overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
                {p.v === '' || p.v == null ? '—' : String(p.v)}
              </span>
            </div>
          ))}
          {params.length > 4 && (
            <span style={{ fontFamily:LM.mono, fontSize:8.5, color:LM.inkDim }}>
              +{params.length - 4} more in inspector
            </span>
          )}
        </div>
      )}
      <div style={{ display:'flex', alignItems:'center', gap:7 }}>
        <button onClick={onRun} disabled={running} style={{
          padding:'3px 12px', borderRadius:4, border:0, cursor: running ? 'default' : 'pointer',
          background: running ? LM.bgSoft : col, color: running ? LM.inkMuted : '#fff',
          fontFamily:LM.mono, fontSize:10, fontWeight:600, letterSpacing:'0.05em',
        }}>{running ? 'running…' : (n.destructive ? '▶ run (action)' : '▶ run')}</button>
        {n.destructive && !running && (
          <span style={{ fontFamily:LM.mono, fontSize:8, color:LM.warn,
            letterSpacing:'0.04em' }}>mutates host</span>
        )}
      </div>
      {res && (
        <div style={{
          background:LM.bgDeep, border:`1px solid ${res.ok ? LM.lineSoft : LM.err}`,
          borderLeft:`2px solid ${res.ok ? col : LM.err}`, borderRadius:3,
          padding:'5px 8px', fontFamily:LM.mono, fontSize:9.5,
          color: res.ok ? LM.inkSoft : LM.err, lineHeight:1.5,
        }}>
          {res.ok
            ? <span>✓ {res.value_preview || 'done'}{res.elapsed_ms ? ` · ${res.elapsed_ms}ms` : ''}</span>
            : <span>✕ {res.error || 'failed'}</span>}
        </div>
      )}
    </div>
  );
};

const HostBody = ({ n }) => (
  <div style={{ marginTop:9, display:'flex', flexDirection:'column', gap:4 }}>
    {n.outs.map(o => (
      <div key={o.id} style={{ display:'flex', gap:6, fontFamily:LM.mono, fontSize:10 }}>
        <span style={{ color:LM.inkMuted, letterSpacing:'0.04em' }}>{o.label}</span>
        <div style={{ flex:1, borderBottom:`1px dashed ${LM.lineSoft}`, marginBottom:2 }}/>
        <span style={{ color:LM.ink }}>{o.val}</span>
      </div>
    ))}
  </div>
);

const AIBody = ({ n, expanded, onToggleExpand }) => {
  const [showReasoning, setShowReasoning] = React.useState(false);
  const [q, setQ] = React.useState('');
  const messages = n.messages || [];
  const total = messages.length;

  if (expanded) {
    const filtered = q ? messages.filter(m => (m.text || '').toLowerCase().includes(q.toLowerCase())) : messages;
    return (
      <div onClick={e => e.stopPropagation()} style={{ marginTop:9, display:'flex', flexDirection:'column', gap:7 }}>
        {/* Search bar */}
        <div style={{
          display:'flex', alignItems:'center', gap:6, padding:'5px 9px',
          background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:5,
        }}>
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke={LM.inkMuted} strokeWidth="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
          <input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="Search this conversation…" style={{
            flex:1, border:0, background:'transparent', color:LM.ink, fontSize:12, outline:'none', fontFamily:LM.sans,
          }}/>
          <span style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted }}>{filtered.length}/{total}</span>
          {q && (
            <button onClick={() => setQ('')} style={{
              width:14, height:14, padding:0, border:0, background:'transparent',
              color:LM.inkMuted, cursor:'pointer', fontSize:11, lineHeight:1,
            }}>×</button>
          )}
        </div>

        {/* Scrollable full transcript */}
        <div className="ah-scroll" style={{
          maxHeight:260, overflow:'auto',
          background:LM.bgDeep, border:`1px solid ${LM.lineSoft}`, borderRadius:5,
          padding:'9px 11px', display:'flex', flexDirection:'column', gap:10,
        }}>
          {filtered.length === 0 && (
            <div style={{ padding:'12px 4px', fontSize:11, color:LM.inkMuted, textAlign:'center' }}>No matches for “{q}”.</div>
          )}
          {filtered.map((m, i) => {
            const aiColor = m.col || (m.model && m.model.col) || LM.accent;
            const aiLetter = m.who || (m.model && m.model.who)
                              || ((m.model && m.model.name && m.model.name[0]) || 'A');
            const aiName = m.me ? 'You' : ((m.model && m.model.name) || 'AI');
            return (
              <div key={i} style={{ display:'flex', gap:7 }}>
                <div title={aiName} style={{
                  width:18, height:18, borderRadius: m.me ? '50%' : 4, flexShrink:0,
                  background: m.me ? '#d8c5a8' : aiColor,
                  color: m.me ? '#5a4a2a' : '#fff',
                  display:'grid', placeItems:'center', fontSize:10, fontWeight:700,
                }}>{m.me ? 'Y' : aiLetter}</div>
                <div style={{ flex:1, minWidth:0 }}>
                  <div style={{ display:'flex', alignItems:'baseline', gap:7, marginBottom:1 }}>
                    <span style={{ fontFamily:LM.mono, fontSize:9,
                                    color: m.me ? LM.inkMuted : aiColor,
                                    letterSpacing:'0.04em' }}>{aiName}</span>
                    <span style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.04em' }}>{m.time || ''}</span>
                  </div>
                  <div style={{ fontSize:11.5, lineHeight:1.5, color: m.me ? LM.ink : LM.inkSoft }}>
                    {q ? highlight(m.text, q) : m.text}
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Inline reply */}
        <div style={{
          display:'flex', alignItems:'center', gap:6, padding:'5px 9px',
          background:LM.bg, border:`1px solid ${LM.accent}55`, borderRadius:5,
        }}>
          <span style={{ color:LM.accent, fontFamily:LM.mono, fontSize:11 }}>/</span>
          <span style={{ flex:1, fontStyle:'italic', fontFamily:LM.serif, fontSize:12, color:LM.inkMuted }}>Reply…</span>
          <button style={{ padding:'3px 8px', background:LM.accent, color:'#fff', border:0, borderRadius:4, fontSize:10, fontWeight:500, cursor:'pointer' }}>Send ↵</button>
        </div>
      </div>
    );
  }

  // Compact view
  const recent = messages.slice(-2);
  return (
    <div style={{ marginTop:9, display:'flex', flexDirection:'column', gap:9 }}>
      {total > 2 && (
        <button onClick={(e) => { e.stopPropagation(); onToggleExpand && onToggleExpand(); }} style={{
          fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.08em',
          padding:'4px 9px', background:LM.bgDeep, border:`1px solid ${LM.lineSoft}`, borderRadius:4,
          display:'flex', alignItems:'center', gap:6, cursor:'pointer', textAlign:'left',
        }}
        onMouseEnter={e => e.currentTarget.style.borderColor = LM.accent+'66'}
        onMouseLeave={e => e.currentTarget.style.borderColor = LM.lineSoft}>
          <span style={{ color:LM.accent }}>↑</span>
          <span>{total - 2} earlier messages</span>
          <span style={{ flex:1 }}/>
          <span style={{ color:LM.accent }}>expand + search ⤢</span>
        </button>
      )}
      {recent.map((m, i) => {
        const isLast = i === recent.length - 1;
        const isAssistant = !m.me;
        const aiColor = m.col || (m.model && m.model.col) || LM.accent;
        const aiLetter = m.who || (m.model && m.model.who)
                          || ((m.model && m.model.name && m.model.name[0]) || 'A');
        const aiName = m.me ? 'You' : ((m.model && m.model.name) || 'AI');
        return (
          <div key={i} style={{ display:'flex', gap:8 }}>
            <div title={aiName} style={{
              width:18, height:18, borderRadius: m.me ? '50%' : 4,
              background: m.me ? '#d8c5a8' : aiColor,
              color: m.me ? '#5a4a2a' : '#fff',
              display:'grid', placeItems:'center', fontSize:10, fontWeight:700, flexShrink:0,
            }}>{m.me ? 'Y' : aiLetter}</div>
            <div style={{ flex:1, minWidth:0 }}>
              {isAssistant && (
                <div style={{ fontFamily:LM.mono, fontSize:9,
                               color: aiColor, letterSpacing:'0.05em',
                               marginBottom:1 }}>{aiName}</div>
              )}
              <ClippedText text={m.text || ''} color={m.me ? LM.ink : LM.inkSoft}
                isStreaming={isAssistant && isLast}
                caretColor={aiColor}/>
              {/* Real reasoning trace from chat_reasoning signal — only
                  render when the provider actually emitted steps. The
                  v1.4 mocked 4-line block is gone (founder demand
                  2026-05-15: "mocked content damages trust"). */}
              {isAssistant && Array.isArray(m.reasoning) && m.reasoning.length > 0 && (
                <>
                  <button onClick={(e) => { e.stopPropagation(); setShowReasoning(s => !s); }} style={{
                    background:'transparent', border:0, padding:'3px 0', color:LM.inkMuted,
                    fontFamily:LM.mono, fontSize:9.5, letterSpacing:'0.06em', cursor:'pointer',
                    display:'flex', alignItems:'center', gap:4, marginTop:3,
                  }}>
                    <span>{showReasoning ? '▾' : '▸'}</span> reasoning · {m.reasoning.length} step{m.reasoning.length === 1 ? '' : 's'}
                  </button>
                  {showReasoning && (
                    <div style={{
                      marginTop:3, padding:'5px 8px', background:LM.bgDeep,
                      border:`1px solid ${LM.lineSoft}`, borderLeft:`2px solid ${LM.purple}`, borderRadius:3,
                      fontFamily:LM.mono, fontSize:9.5, color:LM.inkSoft, lineHeight:1.6,
                    }}>
                      {m.reasoning.map((step, ri) => (
                        <div key={ri}>{ri+1}. {step}</div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};

// Compact text renderer with overflow clip. Founder demand 2026-05-15:
// canvas heavy + laggy when an AI reply dumps 1800 chars of code into a
// Conversation node. Clip to 400 chars in the compact AIBody view; users
// click "show more" to expand inline, or open the right-rail for the full
// transcript. Prevents huge re-render trees on every bumpGraph().
const CLIP_CHARS = 400;
const ClippedText = ({ text, color, isStreaming, caretColor }) => {
  const [open, setOpen] = React.useState(false);
  const s = String(text || '');
  // Streaming-but-empty → thinking indicator, not a literal "…".
  if (isStreaming && (!s || s === '…')) {
    return <div style={{ fontSize:12, color, lineHeight:1.45 }}>
      <ThinkingDots color={caretColor}/>
    </div>;
  }
  const hasCode = s.indexOf('```') !== -1;
  // Code-bearing replies render fence-aware (code blocks self-collapse);
  // plain prose still clips at 400 chars to keep the node body light.
  if (hasCode) {
    return (
      <div style={{ fontSize:12, color, lineHeight:1.45 }}>
        <ChatText text={s}/>
        {isStreaming && (
          <span style={{ display:'inline-block', width:6, height:11,
            background: caretColor || LM.accent, marginLeft:2,
            verticalAlign:'-1px', animation:'lmCaret 1s infinite' }}/>
        )}
      </div>
    );
  }
  const long = s.length > CLIP_CHARS;
  const shown = open || !long ? s : s.slice(0, CLIP_CHARS) + '…';
  return (
    <div style={{ fontSize:12, color, lineHeight:1.45,
                   whiteSpace:'pre-wrap', wordBreak:'break-word' }}>
      {shown}
      {isStreaming && (
        <span style={{ display:'inline-block', width:6, height:11,
                        background: caretColor || LM.accent, marginLeft:2,
                        verticalAlign:'-1px', animation:'lmCaret 1s infinite' }}/>
      )}
      {long && (
        <button onClick={(e) => { e.stopPropagation(); setOpen(o => !o); }}
          style={{ background:'transparent', border:0, color:LM.accent,
                    cursor:'pointer', fontSize:10, fontFamily:LM.mono,
                    padding:'2px 0 0', letterSpacing:'0.04em', display:'block' }}>
          {open ? '▴ show less' : `▾ show ${s.length - CLIP_CHARS} more chars`}
        </button>
      )}
    </div>
  );
};

const highlight = (text, q) => {
  if (!q) return text;
  const parts = text.split(new RegExp(`(${q.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\$&')})`, 'gi'));
  return parts.map((p, i) =>
    p.toLowerCase() === q.toLowerCase()
      ? <mark key={i} style={{ background: LM.accent+'55', color: LM.ink, padding:'0 2px', borderRadius:2 }}>{p}</mark>
      : <React.Fragment key={i}>{p}</React.Fragment>
  );
};

const ReadBody = ({ n }) => (
  <div style={{ marginTop:7, fontFamily:LM.mono, fontSize:10.5, lineHeight:1.55 }}>
    <div style={{ display:'flex', alignItems:'center', gap:6 }}>
      <span style={{ color:LM.ok }}>✓</span>
      <span style={{ color:LM.ink, flex:1 }}>{n.result}</span>
      <span style={{ color:LM.inkMuted, fontSize:9.5 }}>{n.ms}</span>
    </div>
  </div>
);

const FilterBody = ({ n }) => (
  <div style={{ marginTop:7 }}>
    <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, marginBottom:4 }}>predicate</div>
    <div style={{ background:LM.bgDeep, border:`1px solid ${LM.lineSoft}`, borderRadius:4, padding:'5px 8px', fontFamily:LM.mono, fontSize:10.5, color:LM.cyan }}>
      {n.sub.replace(/^.*?·\s*/, '')}
    </div>
    <div style={{ display:'flex', alignItems:'center', gap:6, marginTop:6, fontFamily:LM.mono, fontSize:10.5 }}>
      <span style={{ color:LM.ok }}>→</span>
      <span style={{ color:LM.ink, flex:1 }}>{n.result}</span>
      <span style={{ color:LM.inkMuted, fontSize:9.5 }}>{n.ms}</span>
    </div>
  </div>
);

// Transform body — parameter assignment summary
const TransformBody = ({ n }) => (
  <div style={{ marginTop:8, display:'flex', flexDirection:'column', gap:6 }}>
    {n.params?.map(p => (
      <div key={p.k} style={{ display:'flex', alignItems:'center', gap:6, fontFamily:LM.mono, fontSize:10 }}>
        <span style={{ color:LM.inkMuted, letterSpacing:'0.04em' }}>{p.k}</span>
        <div style={{ flex:1, borderBottom:`1px dashed ${LM.lineSoft}`, marginBottom:2 }}/>
        <span style={{ color:LM.ink, padding:'1px 6px', background:LM.bg, border:`1px solid ${LM.lineSoft}`, borderRadius:3 }}>{p.v}</span>
      </div>
    ))}
    <div style={{
      marginTop:2, fontFamily:LM.mono, fontSize:10, color:LM.warn,
      padding:'4px 8px', background:LM.warn+'14', borderRadius:3,
      display:'flex', alignItems:'center', gap:6,
    }}>
      <span>⚠</span><span>mutates model · requires approval</span>
    </div>
  </div>
);

// Logic body — predicate with branch indicators
const LogicBody = ({ n }) => (
  <div style={{ marginTop:8 }}>
    <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, marginBottom:4 }}>predicate</div>
    <div style={{ background:LM.bgDeep, border:`1px solid ${LM.lineSoft}`, borderRadius:4, padding:'5px 8px', fontFamily:LM.mono, fontSize:10.5, color:LM.purple }}>
      {n.sub.replace(/^.*?·\s*/, '')}
    </div>
    {n.result && (
      <div style={{ display:'flex', alignItems:'center', gap:6, marginTop:6, fontFamily:LM.mono, fontSize:10.5 }}>
        <span style={{ color:LM.purple }}>→</span>
        <span style={{ color:LM.ink, flex:1 }}>{n.result}</span>
        <span style={{ color:LM.inkMuted, fontSize:9.5 }}>{n.ms}</span>
      </div>
    )}
  </div>
);

// Compose body — little table preview
const ComposeBody = ({ n }) => (
  <div style={{ marginTop:8 }}>
    <div style={{
      background:LM.bgInk, border:`1px solid ${LM.lineSoft}`, borderRadius:5, overflow:'hidden',
      fontFamily:LM.mono, fontSize:9.5,
    }}>
      {/* header */}
      <div style={{ display:'grid', gridTemplateColumns:'1.4fr 1fr 1fr', padding:'4px 8px', background:LM.bgDeep, color:LM.inkMuted, letterSpacing:'0.08em' }}>
        <span>TYPE</span><span>LEN</span><span style={{ textAlign:'right' }}>QTY</span>
      </div>
      {[
        ['Gen 200', '6 420', '12'],
        ['Gen 150', '4 800', '6'],
        ['CW 100',  '3 200', '5'],
        ['…',       '…',    '1'],
      ].map((r, i) => (
        <div key={i} style={{
          display:'grid', gridTemplateColumns:'1.4fr 1fr 1fr', padding:'3px 8px',
          color:LM.ink, borderTop:`1px solid ${LM.lineHair}`,
        }}>
          <span>{r[0]}</span><span>{r[1]}</span><span style={{ textAlign:'right' }}>{r[2]}</span>
        </div>
      ))}
    </div>
    {n.result && (
      <div style={{ display:'flex', alignItems:'center', gap:6, marginTop:6, fontFamily:LM.mono, fontSize:10.5 }}>
        <span style={{ color:LM.ok }}>→</span>
        <span style={{ color:LM.ink, flex:1 }}>{n.result}</span>
        <span style={{ color:LM.inkMuted, fontSize:9.5 }}>{n.ms}</span>
      </div>
    )}
  </div>
);

const AnnotateBody = ({ n }) => (
  <div style={{ marginTop:9 }}>
    {n.runtime && (
      <>
        <div style={{ display:'flex', alignItems:'center', gap:6, marginBottom:6 }}>
          <span style={{ fontFamily:LM.mono, fontSize:10, color:LM.accent, letterSpacing:'0.06em' }}>{n.runtime}</span>
          <div style={{ flex:1 }}/>
          <span style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted }}>{Math.round(n.progress*100)}%</span>
        </div>
        <div style={{ height:3, background:LM.bgDeep, borderRadius:2, overflow:'hidden', marginBottom:10 }}>
          <div style={{ width:`${n.progress*100}%`, height:'100%', background:LM.accent }}/>
        </div>
      </>
    )}
    {n.params && (
      <div style={{ display:'flex', flexDirection:'column', gap:7 }}>
        {n.params.slice(0, 3).map(p => <CompactParam key={p.k} p={p}/>)}
      </div>
    )}
    {n.runtime && (
      <>
        <div style={{ marginTop:10, fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.14em', marginBottom:5 }}>PREVIEW</div>
        <StagePreview/>
      </>
    )}
  </div>
);

const OutputBody = ({ n }) => (
  <div style={{ marginTop:8, display:'flex', flexDirection:'column', gap:7 }}>
    {n.params?.slice(0, 2).map(p => (
      <div key={p.k} style={{ display:'flex', flexDirection:'column', gap:2 }}>
        <span style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, letterSpacing:'0.04em' }}>{p.k}</span>
        <div style={{ background:LM.bg, border:`1px solid ${LM.lineSoft}`, borderRadius:4, padding:'4px 8px', fontFamily:LM.mono, fontSize:10.5, color:LM.ink }}>
          {p.v}
        </div>
      </div>
    ))}
    <div style={{ display:'flex', gap:6, marginTop:4 }}>
      <button style={smallBtn()}>preview</button>
      <button style={smallBtn(true)}>save</button>
    </div>
  </div>
);

const CompactParam = ({ p }) => {
  if (p.type === 'slider') {
    const pct = ((p.v - p.min) / (p.max - p.min)) * 100;
    return (
      <div>
        <div style={{ display:'flex', alignItems:'baseline', gap:6 }}>
          <span style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkSoft, flex:1, letterSpacing:'0.04em' }}>{p.k}</span>
          <span style={{ fontFamily:LM.mono, fontSize:10.5, color:LM.ink, fontWeight:500 }}>{p.v}</span>
        </div>
        <div style={{ height:3, background:LM.bgDeep, borderRadius:2, marginTop:4, position:'relative' }}>
          <div style={{ width:`${pct}%`, height:'100%', background:LM.accent, borderRadius:2 }}/>
          <div style={{ position:'absolute', left:`calc(${pct}% - 4px)`, top:-2.5, width:8, height:8, borderRadius:'50%', background:LM.ink, border:`1.5px solid ${LM.accent}` }}/>
        </div>
      </div>
    );
  }
  return (
    <div style={{ display:'flex', alignItems:'center', gap:6 }}>
      <span style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkSoft, flex:1, letterSpacing:'0.04em' }}>{p.k}</span>
      <span style={{ fontFamily:LM.mono, fontSize:10, color:LM.ink, padding:'1px 6px', background:LM.bg, border:`1px solid ${LM.lineSoft}`, borderRadius:3 }}>
        {p.v} <span style={{ color:LM.inkMuted, marginLeft:2 }}>▾</span>
      </span>
    </div>
  );
};

const StagePreview = () => (
  <div style={{
    aspectRatio:'2/1', background:LM.bgInk, border:`1px solid ${LM.lineSoft}`, borderRadius:5,
    position:'relative', overflow:'hidden',
    backgroundImage:`linear-gradient(${LM.lineHair} 1px, transparent 1px), linear-gradient(90deg, ${LM.lineHair} 1px, transparent 1px)`,
    backgroundSize:'12px 12px',
  }}>
    <svg viewBox="0 0 200 100" style={{ position:'absolute', inset:0, width:'100%', height:'100%' }}>
      <rect x="20" y="20" width="160" height="60" fill="none" stroke={LM.accent} strokeWidth="2"/>
      <line x1="100" y1="20" x2="100" y2="50" stroke={LM.inkSoft} strokeWidth="1"/>
      <line x1="20"  y1="50" x2="180" y2="50" stroke={LM.inkSoft} strokeWidth="1"/>
      <line x1="60"  y1="50" x2="60"  y2="80" stroke={LM.inkSoft} strokeWidth="1"/>
      <line x1="20" y1="90" x2="180" y2="90" stroke={LM.accent} strokeWidth="0.6"/>
      <line x1="20" y1="87" x2="20" y2="93" stroke={LM.accent} strokeWidth="0.6"/>
      <line x1="100" y1="87" x2="100" y2="93" stroke={LM.accent} strokeWidth="0.6"/>
      <line x1="180" y1="87" x2="180" y2="93" stroke={LM.accent} strokeWidth="0.6"/>
      <text x="60" y="86" textAnchor="middle" fontFamily="JetBrains Mono" fontSize="4" fill={LM.accent}>9 600</text>
      <text x="140" y="86" textAnchor="middle" fontFamily="JetBrains Mono" fontSize="4" fill={LM.accent}>10 400</text>
    </svg>
    <div style={{
      position:'absolute', top:5, right:6, fontFamily:LM.mono, fontSize:8,
      color:LM.accent, letterSpacing:'0.06em', background:LM.bgDeep+'cc', padding:'1px 5px', borderRadius:2,
    }}>17 / 23 placed</div>
  </div>
);

// ─── canvas toolbar (TOP-LEFT) ───
const CanvasToolbar = ({ zoom, setZoom, onFit, setLibraryOpen, onRun }) => (
  <div data-no-pan style={{
    position:'absolute', left:14, top:14, display:'flex', gap:4,
    background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:7, padding:4,
    boxShadow:'0 4px 12px rgba(0,0,0,.3)',
  }}>
    <button onClick={(e) => { e.stopPropagation(); setZoom(z => Math.min(2, +(z + 0.1).toFixed(2))); }} style={toolBtn()}>+</button>
    <button onClick={(e) => { e.stopPropagation(); setZoom(z => Math.max(0.3, +(z - 0.1).toFixed(2))); }} style={toolBtn()}>−</button>
    <div style={{ ...toolBtn(), width:48, color:LM.ink, background:LM.bg, fontFamily:LM.mono, fontSize:10, cursor:'default' }}>
      {Math.round(zoom * 100)}%
    </div>
    <button onClick={(e) => { e.stopPropagation(); onFit(); }} title="Reset view" style={toolBtn()}>⟲</button>
    <div style={{ width:1, background:LM.line, margin:'0 2px' }}/>
    <button onClick={(e) => { e.stopPropagation(); setLibraryOpen(true); }} title="Add node" style={{
      padding:'0 10px', height:22, border:0, background:'transparent', cursor:'pointer',
      color:LM.accent, fontFamily:LM.mono, fontSize:10, letterSpacing:'0.06em',
      display:'flex', alignItems:'center', gap:4,
    }}>＋ add node</button>
    <div style={{ width:1, background:LM.line, margin:'0 2px' }}/>
    {/* Founder demand #11: ▶ RUN WORKFLOW — calls bridge.run_workflow (M2 threaded). */}
    <button onClick={(e) => { e.stopPropagation(); onRun && onRun(); }} title="Run entire workflow (⌘↵)" style={{
      padding:'0 10px', height:22, border:0, background:LM.accent, cursor:'pointer',
      color:'#fff', fontFamily:LM.mono, fontSize:10, letterSpacing:'0.06em', borderRadius:4,
      display:'flex', alignItems:'center', gap:4, fontWeight:600,
    }}>▶ RUN</button>
  </div>
);

const toolBtn = () => ({
  width:24, height:22, padding:0, border:0, background:'transparent',
  color:LM.inkSoft, borderRadius:4, cursor:'pointer', fontSize:13,
});

// ─── floating composer (BOTTOM CENTER — always-bottom anchor) ───
// Founder demand #2: typing "ping outlook" detects host + spawns Outlook host,
// conversation node, wires them, streams reply. parse_composer_command on the
// bridge returns the action descriptor. We dispatch lm-composer-action and
// StudioLM root applies the mutations.
// Founder demand #3: slash commands /wire /freeze /delete /rename /duplicate
// /properties /disconnect /createnode — also routed through the bridge.
// Client-side host-family list — mirrors workflows/composer_commands.py
// HOST_FAMILIES. Kept inline so submit() does NOT round-trip the QWebChannel
// bridge (which is async — returning undefined synchronously, breaking the
// previous design). The bridge parse_composer_command path is still used by
// apply_composer_command for slash mutations like /wire, /freeze, etc. via
// the central handler. For host-spawn intent we resolve locally.
const HOST_FAMILIES_JS = [
  'revit','autocad','max','blender','rhino','speckle',
  'outlook','lmstudio','antigravity','word','excel',
  'powerpoint','photoshop','illustrator','indesign','teams',
  'notion','dropbox',
];
const INTENT_VERBS_JS = new Set([
  'ping','info','list','open','save','render','build','draft','send',
  'search','find','summarise','summarize','show','describe','explain',
  'what','where','how',
]);
function detectIntentJS(raw) {
  if (!raw) return null;
  const text = raw.trim().toLowerCase();
  if (!text) return null;
  const tokens = text.match(/[a-z0-9']+/g) || [];
  if (!tokens.length) return null;
  let host = null, hostIdx = -1;
  for (let i = 0; i < tokens.length; i++) {
    const tok = tokens[i];
    for (const fam of HOST_FAMILIES_JS) {
      if (tok.indexOf(fam) !== -1) { host = fam; hostIdx = i; break; }
    }
    if (host) break;
  }
  if (!host) return null;
  let verb = null;
  for (let i = 0; i < tokens.length; i++) {
    if (i === hostIdx) continue;
    const base = tokens[i].split("'")[0];
    if (INTENT_VERBS_JS.has(tokens[i])) { verb = tokens[i]; break; }
    if (base && INTENT_VERBS_JS.has(base)) { verb = base; break; }
  }
  // Accept iff host leads OR a verb co-occurs.
  if (!verb && hostIdx !== 0) return null;
  return { family: host, verb: verb || null };
}
function parseSlashJS(raw, focusId) {
  // Lightweight JS mirror of workflows/composer_commands.parse_composer_command
  // for commands we want to handle instantly without an async bridge round-
  // trip. Anything not handled here falls back to the bridge path.
  const body = (raw || '').trim().slice(1);   // strip leading '/'
  if (!body) return { command:'help', ok:true, summary:'Available commands' };
  const bits = body.split(/\s+/);
  const verb = (bits[0] || '').toLowerCase();
  const rest = bits.slice(1).join(' ');
  if (verb === 'ping') {
    const target = rest.toLowerCase();
    const intent = target ? detectIntentJS(target) : null;
    if (intent) {
      return { command:'spawn_host_chat', ok:true,
                family:intent.family, verb:'ping',
                remainder:'', original:raw,
                summary:`Spawn ${intent.family} host + chat` };
    }
    // Try matching a host family in the rest tokens.
    const tokens = (target.match(/[a-z0-9']+/g) || []);
    let fam = null;
    for (const t of tokens) {
      for (const f of HOST_FAMILIES_JS) { if (t.indexOf(f) !== -1) { fam = f; break; } }
      if (fam) break;
    }
    if (fam) {
      return { command:'spawn_host_chat', ok:true,
                family:fam, verb:'ping', remainder:target, original:raw,
                summary:`Spawn ${fam} host + chat` };
    }
    return { command:'help', ok:false,
              error:'ping needs a host name',
              summary:'try /ping outlook · /ping revit · /ping notion' };
  }
  return null;   // not handled locally — fall back to bridge
}

// Read a Blob → base64 string (no data: prefix). Used by attach + paste.
function _blobToB64(blob) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => {
      const r = fr.result || '';
      const comma = String(r).indexOf(',');
      resolve(comma >= 0 ? String(r).slice(comma+1) : String(r));
    };
    fr.onerror = () => reject(fr.error || new Error('FileReader failed'));
    fr.readAsDataURL(blob);
  });
}

const FloatingComposer = ({ setLibraryOpen, focusId }) => {
  const [text, setText] = React.useState('');
  const [showHelp, setShowHelp] = React.useState(false);
  const [attachments, setAttachments] = React.useState([]);
  const [recording, setRecording] = React.useState(false);
  const [dragOver, setDragOver] = React.useState(false);
  const inputRef = React.useRef(null);
  const fileInputRef = React.useRef(null);
  const recogRef = React.useRef(null);

  const dispatchAction = (action, raw, opts) => {
    try {
      window.dispatchEvent(new CustomEvent('lm-composer-action', {
        detail: { action, raw, focusId,
                   attachments: (opts && opts.attachments) || [] },
      }));
    } catch (e) {}
  };

  // ── attachment helpers ────────────────────────────────────────
  const stashFile = async (file) => {
    if (!file) return null;
    try {
      const b64 = await _blobToB64(file);
      const res = await bridgeAsync('stash_attachment',
        file.name || 'paste', file.type || '', b64);
      if (!res || !res.ok) {
        window.dispatchEvent(new CustomEvent('lm-canvas-toast', {
          detail: { msg: `attach failed: ${(res && res.error) || 'no bridge'}`, kind:'err' },
        }));
        return null;
      }
      const kind = (file.type || '').startsWith('image/') ? 'image'
                 : (file.type || '').startsWith('audio/') ? 'audio' : 'file';
      return { name: res.name, mime: res.mime, path: res.path,
                size: res.size, kind };
    } catch (e) {
      return null;
    }
  };
  const addFiles = async (files) => {
    const list = Array.from(files || []);
    for (const f of list) {
      const att = await stashFile(f);
      if (att) setAttachments(a => [...a, att]);
    }
  };
  const removeAttachment = (ix) => setAttachments(a => a.filter((_, i) => i !== ix));

  // ── drag-and-drop on the composer wrapper ────────────────────
  const onDragOver = (e) => {
    if (!e.dataTransfer || !e.dataTransfer.types) return;
    if (![...e.dataTransfer.types].includes('Files')) return;
    e.preventDefault(); e.stopPropagation(); setDragOver(true);
  };
  const onDragLeave = (e) => { e.preventDefault(); setDragOver(false); };
  const onDrop = async (e) => {
    if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files.length) return;
    e.preventDefault(); e.stopPropagation(); setDragOver(false);
    await addFiles(e.dataTransfer.files);
  };

  // ── paste image / file ──────────────────────────────────────
  const onPaste = async (e) => {
    if (!e.clipboardData || !e.clipboardData.items) return;
    const files = [];
    for (const it of e.clipboardData.items) {
      if (it.kind === 'file') {
        const f = it.getAsFile();
        if (f) files.push(f);
      }
    }
    if (files.length) {
      e.preventDefault();
      await addFiles(files);
    }
  };

  // ── voice input via Web Speech API ──────────────────────────
  const SpeechRec = (typeof window !== 'undefined') &&
                    (window.SpeechRecognition || window.webkitSpeechRecognition);
  const toggleRecord = () => {
    if (!SpeechRec) {
      window.dispatchEvent(new CustomEvent('lm-canvas-toast', {
        detail: { msg: 'voice not supported in this build', kind:'err' },
      }));
      return;
    }
    if (recording) {
      try { recogRef.current && recogRef.current.stop(); } catch (e) {}
      setRecording(false);
      return;
    }
    try {
      const rec = new SpeechRec();
      rec.lang = 'en-US';
      rec.interimResults = true;
      rec.continuous = false;
      rec.onresult = (ev) => {
        let final = '';
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          final += ev.results[i][0].transcript;
        }
        if (final) setText(t => (t ? t + ' ' : '') + final.trim());
      };
      rec.onend = () => setRecording(false);
      rec.onerror = () => setRecording(false);
      rec.start();
      recogRef.current = rec;
      setRecording(true);
    } catch (e) {
      setRecording(false);
    }
  };

  const submit = async () => {
    const t = text.trim();
    const atts = attachments.slice();
    // Allow submit with attachments only (no text). Voice/file workflow.
    if (!t && !atts.length) return;
    if (t === '/') { setShowHelp(true); return; }
    setText(''); setAttachments([]);

    // ── 1. Client-side intent first (no bridge round-trip). Founder demand:
    // spawn must be instant. "ping outlook" / "/ping outlook" / "what's in
    // my outlook?" all resolve here.
    let action = null;
    if (t.startsWith('/')) {
      action = parseSlashJS(t, focusId);
    } else {
      const intent = detectIntentJS(t);
      if (intent) {
        action = { command:'spawn_host_chat', ok:true,
                    family:intent.family, verb:intent.verb,
                    text:t, original:t,
                    summary:`Spawn ${intent.family} host + chat` };
      }
    }
    if (action) {
      dispatchAction({ ...action, text:t }, t, { attachments: atts });
      // If the slash command is something only the Python parser knows
      // (e.g. /wire, /freeze, /rename), fall through to the bridge path
      // below in parallel. parseSlashJS returns null for those.
      if (action.command !== 'help') return;
    }

    // ── 2. Slash commands not handled locally (wire / freeze / rename /
    // delete / etc.) — bridge round-trip via apply_composer_command.
    if (t.startsWith('/')) {
      const result = await bridgeAsync('apply_composer_command',
                                         JSON.stringify(LM_GRAPH), t,
                                         focusId || '');
      if (result && result.graph && Array.isArray(result.graph.nodes)) {
        LM_GRAPH.nodes = result.graph.nodes;
        LM_GRAPH.wires = result.graph.wires || [];
        try {
          window.dispatchEvent(new CustomEvent('lm-canvas-toast', {
            detail: { msg: (result.action && result.action.summary)
                            || 'applied', kind:'info' },
          }));
        } catch (e) {}
        // Ask the canvas to re-render via the existing dispatch path.
        dispatchAction({ command:'_refresh' }, t);
        return;
      }
      // Bridge silent — dispatch help so user sees feedback.
      dispatchAction({ command:'help', summary:`/${t.slice(1).split(' ')[0]}: no result` }, t);
      return;
    }

    // ── 3. Plain natural language — agent_step on the bridge. Founder
    // bug 2026-05-15: the app froze ("Not Responding") because agent_step
    // ran the host probes + LLM call on the Qt main thread. agent_step is
    // now fire-and-forget — it runs on a Python background thread and
    // emits `agent_step_done`. The StudioLM root listens for that signal
    // and replays the tool calls. Here we just kick it off + show chat.
    dispatchAction({ command:'chat', text:t }, t, { attachments: atts });
    try { bridgeCall('agent_step', t, JSON.stringify(LM_GRAPH), focusId || ''); }
    catch (e) {}
  };

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
    if (e.key === 'Escape') { setShowHelp(false); }
  };

  return (
    <div data-no-pan
      onWheel={(e) => { e.stopPropagation(); e.preventDefault(); }}
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
      onContextMenu={(e) => e.stopPropagation()}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      style={{
      position:'fixed', left:'50%', bottom:64, transform:'translateX(-50%)',
      width:620, maxWidth:'82%',
      background:LM.bgPanel,
      border:`1px solid ${dragOver ? LM.accent : LM.accent+'66'}`,
      borderRadius:9, boxShadow:`0 14px 30px rgba(0,0,0,.5), 0 0 0 3px ${LM.accentDim}`,
      padding:'10px 13px',
      zIndex:1000,
      isolation:'isolate',
    }}>
      {attachments.length > 0 && (
        <div style={{ display:'flex', flexWrap:'wrap', gap:6, marginBottom:8 }}>
          {attachments.map((a, i) => (
            <div key={i} style={{
              display:'flex', alignItems:'center', gap:6,
              background:LM.bg, border:`1px solid ${LM.line}`,
              borderRadius:5, padding:'3px 8px',
              fontFamily:LM.mono, fontSize:10.5, color:LM.inkSoft,
            }}>
              <span style={{ color:LM.accent }}>
                {a.kind === 'image' ? '◧' : a.kind === 'audio' ? '◉' : '⎙'}
              </span>
              <span style={{ maxWidth:160, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{a.name}</span>
              <span style={{ color:LM.inkDim, fontSize:9.5 }}>{Math.max(1, Math.round((a.size||0)/1024))}kb</span>
              <button onClick={(e) => { e.stopPropagation(); removeAttachment(i); }}
                style={{ border:0, background:'transparent', color:LM.inkMuted,
                          cursor:'pointer', padding:0, fontSize:13, lineHeight:1 }}>×</button>
            </div>
          ))}
        </div>
      )}
      <input ref={fileInputRef} type="file" multiple style={{ display:'none' }}
        onChange={async (e) => { await addFiles(e.target.files); e.target.value = ''; }}/>
      <div style={{ display:'flex', alignItems:'center', gap:8, fontSize:13.5, fontFamily:LM.sans, color:LM.ink, minHeight:24 }}>
        <span style={{ color:LM.accent, fontFamily:LM.mono, fontSize:13 }}>/</span>
        <input ref={inputRef} value={text}
          onChange={(e) => { setText(e.target.value); setShowHelp(e.target.value === '/'); }}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
          placeholder={dragOver ? 'drop files to attach…' : 'Reply, ping a host, or type / for commands…'}
          style={{
            flex:1, border:0, background:'transparent', color:LM.ink, fontSize:14,
            fontFamily:LM.sans, outline:'none',
          }}/>
        <button onClick={(e) => { e.stopPropagation(); fileInputRef.current && fileInputRef.current.click(); }}
          title="Attach file or image"
          style={{ ...smallBtn(), padding:'3px 9px', color:LM.inkSoft }}>📎</button>
        <button onClick={(e) => { e.stopPropagation(); toggleRecord(); }}
          title={recording ? 'Stop recording' : 'Voice input (browser SpeechRecognition)'}
          style={{ ...smallBtn(), padding:'3px 9px',
                    color: recording ? LM.err : LM.inkSoft,
                    background: recording ? LM.err+'22' : 'transparent',
                    animation: recording ? 'lmPulse 1s ease-in-out infinite' : 'none' }}>
          {recording ? '● rec' : '🎤'}
        </button>
        <button onClick={(e) => { e.stopPropagation(); setLibraryOpen(true); }} style={{ ...smallBtn(), padding:'3px 9px' }}>library</button>
        <button onClick={submit} style={{ padding:'4px 11px', background:LM.accent, color:'#fff', border:0, borderRadius:5, fontSize:11.5, fontWeight:500, cursor:'pointer' }}>Send ↵</button>
      </div>
      {showHelp && (
        <div style={{
          position:'absolute', left:0, bottom:'100%', marginBottom:6,
          background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:7,
          padding:'8px 10px', fontFamily:LM.mono, fontSize:10.5, color:LM.inkSoft,
          lineHeight:1.7, minWidth:320, boxShadow:'0 12px 30px rgba(0,0,0,.5)',
        }}>
          <div style={{ color:LM.accent, marginBottom:4 }}>SLASH COMMANDS</div>
          <div>/wire   <span style={{ color:LM.inkMuted }}>connect two nodes by name</span></div>
          <div>/freeze <span style={{ color:LM.inkMuted }}>pause focused node</span></div>
          <div>/delete <span style={{ color:LM.inkMuted }}>remove focused node</span></div>
          <div>/rename <span style={{ color:LM.inkMuted }}>edit focused node's title</span></div>
          <div>/duplicate <span style={{ color:LM.inkMuted }}>copy focused node</span></div>
          <div>/disconnect <span style={{ color:LM.inkMuted }}>cut wires on focused node</span></div>
          <div>/properties <span style={{ color:LM.inkMuted }}>open inspector</span></div>
          <div>/createnode type=foo cat=filter inputs=walls outputs=filtered</div>
        </div>
      )}
    </div>
  );
};

// ─── mini-map (TOP-RIGHT) ───
const MiniMap = ({ pan, zoom, positions, allNodes, wrapRef, setPan }) => {
  // World-space dimensions the minimap maps (must match the canvas
  // SVG's `viewBox` at the rendering site).
  const W = 2400, H = 1400;
  const MAP_W = 170, MAP_H = 96;
  const nodes = allNodes || (LM_GRAPH && LM_GRAPH.nodes) || [];

  // Compute the current viewport rect in world coords. The visible
  // window on screen at the canvas wrapper's size, projected back
  // through pan + zoom, is the source rectangle.
  const rect = (wrapRef && wrapRef.current && wrapRef.current.getBoundingClientRect())
              || { width: 1280, height: 720 };
  const vw = rect.width  / (zoom || 1);
  const vh = rect.height / (zoom || 1);
  const vx = -(pan && pan.x || 0) / (zoom || 1);
  const vy = -(pan && pan.y || 0) / (zoom || 1);

  // Map world → minimap (pixel) coords.
  const sx = MAP_W / W;
  const sy = MAP_H / H;

  // Click / drag handlers: convert minimap pixel coords back to world,
  // then back to pan. Centring the viewport on the clicked point.
  const _setPanToWorld = (wx, wy) => {
    if (!setPan || !wrapRef || !wrapRef.current) return;
    const r = wrapRef.current.getBoundingClientRect();
    const z = zoom || 1;
    // we want world (wx, wy) to land at viewport centre:
    //   wx = -pan.x / z + r.width  / (2z)
    //   -> pan.x = (r.width  / 2) - wx * z
    setPan({
      x: (r.width  / 2) - wx * z,
      y: (r.height / 2) - wy * z,
    });
  };

  const onMouseDown = (e) => {
    e.preventDefault(); e.stopPropagation();
    const map = e.currentTarget;
    const mr  = map.getBoundingClientRect();
    const toWorld = (clientX, clientY) => {
      const localX = clientX - mr.left;
      const localY = clientY - mr.top;
      return { wx: localX / sx, wy: localY / sy };
    };
    const { wx, wy } = toWorld(e.clientX, e.clientY);
    _setPanToWorld(wx, wy);

    const onMove = (ev) => {
      const { wx, wy } = toWorld(ev.clientX, ev.clientY);
      _setPanToWorld(wx, wy);
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  };

  return (
    <div data-no-pan onMouseDown={onMouseDown}
      title="Click or drag to pan the canvas"
      style={{
        position:'absolute', right:14, top:14, width:MAP_W, height:MAP_H,
        background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:6,
        overflow:'hidden', boxShadow:'0 4px 12px rgba(0,0,0,.3)',
        cursor:'pointer', userSelect:'none',
      }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width:'100%', height:'100%',
            pointerEvents:'none' }}>
        {(nodes || []).map(n => {
          if (!n) return null;
          const p = (positions && positions[n.id]) || { x: n.x || 0, y: n.y || 0 };
          const cat = catMeta(n.cat);
          return (
            <rect key={n.id} x={p.x} y={p.y}
              width={n.w || 220} height={n.h || 110}
              fill={(cat && cat.col || LM.inkSoft) + '66'}
              stroke={LM.lineSoft} strokeWidth="2" rx="4"/>
          );
        })}
        {/* Viewport rect overlay — shows what's currently visible. */}
        <rect x={vx} y={vy} width={vw} height={vh}
          fill={(LM.accent || '#d97757') + '22'}
          stroke={LM.accent || '#d97757'} strokeWidth="3"
          rx="6" pointerEvents="none"/>
      </svg>
      <div style={{
        position:'absolute', left:6, top:5, fontFamily:LM.mono, fontSize:8,
        color:LM.inkMuted, letterSpacing:'0.14em', background:LM.bgDeep+'cc',
        padding:'1px 5px', borderRadius:2, pointerEvents:'none',
      }}>MAP</div>
    </div>
  );
};

// ──────────────────────── NODE LIBRARY ────────────────────────
const NodeLibrary = ({ onClose, addNodeFromLibrary }) => {
  const [filter, setFilter] = React.useState('all');
  const [q, setQ] = React.useState('');
  const groups = filter === 'all' ? (LM_LIBRARY || []) : (LM_LIBRARY || []).filter(g => g.cat === filter);
  return (
    <div onClick={onClose} style={{
      position:'absolute', inset:0, background:'rgba(0,0,0,.55)', zIndex:60,
      display:'grid', placeItems:'center',
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        width:780, maxWidth:'94%', height:540, maxHeight:'88%',
        background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:10,
        overflow:'hidden', boxShadow:'0 30px 80px rgba(0,0,0,.6)',
        display:'grid', gridTemplateColumns:'180px 1fr', gridTemplateRows:'48px 1fr',
      }}>
        <div style={{ gridColumn:'1 / -1', gridRow:'1', borderBottom:`1px solid ${LM.line}`, padding:'0 14px', display:'flex', alignItems:'center', gap:10 }}>
          <span style={{ fontFamily:LM.serif, fontSize:18, letterSpacing:'-0.01em' }}>Node library</span>
          <span style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, letterSpacing:'0.1em' }}>
            {(LM_LIBRARY || []).reduce((n, g) => n + ((g.items || []).length), 0)} NODES · CLICK TO ADD
          </span>
          <div style={{ flex:1 }}/>
          <input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="Search… (e.g. dimension, schedule, push)" style={{
            padding:'6px 11px', background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:5,
            color:LM.ink, fontFamily:LM.sans, fontSize:12.5, outline:'none', width:280,
          }}/>
          <button onClick={onClose} style={{
            width:24, height:24, padding:0, border:`1px solid ${LM.line}`, background:'transparent',
            borderRadius:5, cursor:'pointer', color:LM.inkSoft, fontSize:12,
          }}>✕</button>
        </div>

        {/* Categories */}
        <div style={{ gridColumn:'1', gridRow:'2', borderRight:`1px solid ${LM.line}`, padding:'10px 8px', overflow:'auto' }}>
          <LibCatBtn id="all" label="All categories" active={filter==='all'} onSelect={setFilter}/>
          {Object.entries(CAT).map(([id, c]) => (
            <LibCatBtn key={id} id={id} label={c.label.toLowerCase()} icon={c.icon} col={c.col} active={filter===id} onSelect={setFilter}/>
          ))}
        </div>

        <div className="ah-scroll" style={{ gridColumn:'2', gridRow:'2', overflow:'auto', padding:'14px 18px' }}>
          {/* Founder demand 2026-05-17: adding a node is via "+ add node"
              (this modal). Custom-node creation lives HERE as the first
              entry — closes the library, opens the AI Node Smith modal.
              Replaces the panel-header "+ new node" button. */}
          <button onClick={() => { onClose();
              try { window.dispatchEvent(new CustomEvent('lm-new-node')); } catch (e) {} }}
            style={{
              width:'100%', marginBottom:16, padding:'12px 14px',
              display:'flex', alignItems:'center', gap:12, cursor:'pointer',
              background:LM.bgSoft, border:`1px solid ${LM.line}`,
              borderLeft:`2px solid ${LM.blue}`, borderRadius:8,
              textAlign:'left', color:LM.ink, fontFamily:LM.sans,
            }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = LM.blue; }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = LM.line;
              e.currentTarget.style.borderLeftColor = LM.blue; }}>
            <span style={{ fontSize:20, color:LM.blue, lineHeight:1 }}>⊕</span>
            <div style={{ display:'flex', flexDirection:'column', gap:2 }}>
              <span style={{ fontSize:13, fontWeight:600 }}>Create a custom node with AI</span>
              <span style={{ fontSize:11, color:LM.inkSoft }}>
                Describe what you want — AI designs the node with typed inputs and outputs.
              </span>
            </div>
          </button>
          {groups.map(g => {
            const c = catMeta(g.cat);
            const items = q ? (g.items || []).filter(i => (i.title + ' ' + i.sub).toLowerCase().includes(q.toLowerCase())) : (g.items || []);
            if (items.length === 0) return null;
            return (
              <div key={g.cat} style={{ marginBottom:18 }}>
                <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:8 }}>
                  <span style={{ color:c.col }}>{c.icon}</span>
                  <span style={{ fontFamily:LM.mono, fontSize:10, color:c.col, letterSpacing:'0.18em' }}>{c.label}</span>
                  <span style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.06em' }}>{c.role}</span>
                </div>
                <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:6 }}>
                  {items.map(i => (
                    <button key={i.id} onClick={() => { addNodeFromLibrary && addNodeFromLibrary({ ...i, cat:g.cat }); onClose(); }} style={{
                      background:LM.bg, border:`1px solid ${LM.line}`, borderLeft:`2px solid ${c.col}`,
                      borderRadius:6, padding:'8px 11px', textAlign:'left', cursor:'pointer',
                      color:LM.ink, fontFamily:LM.sans,
                      display:'flex', flexDirection:'column', gap:2,
                    }}
                    onMouseEnter={e => { e.currentTarget.style.borderColor = LM.accent+'88'; e.currentTarget.style.borderLeftColor = c.col; }}
                    onMouseLeave={e => { e.currentTarget.style.borderColor = LM.line; e.currentTarget.style.borderLeftColor = c.col; }}>
                      <span style={{ fontSize:12.5, fontWeight:500, fontFamily:LM.mono }}>{i.title}</span>
                      <span style={{ fontSize:11, color:LM.inkSoft }}>{i.sub}</span>
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

const LibCatBtn = ({ id, label, icon, col, active, onSelect }) => (
  <button onClick={() => onSelect(id)} style={{
    width:'100%', padding:'7px 11px', borderRadius:5, border:0,
    background: active ? LM.bgSoft : 'transparent',
    color: active ? LM.ink : LM.inkSoft,
    textAlign:'left', cursor:'pointer', fontFamily:LM.sans, fontSize:13,
    display:'flex', alignItems:'center', gap:8, marginBottom:1,
  }}>
    {icon && <span style={{ color:col, width:12, textAlign:'center', fontFamily:LM.mono, fontSize:11 }}>{icon}</span>}
    <span style={{ flex:1 }}>{label}</span>
  </button>
);

// ──────────────────────── NODE RAIL ────────────────────────
// ─── Dynamic options hook — when a param has `options_source` (an op_id
// whose result is the list), fetch live + re-fetch when sibling params
// change (cascading: document → views → levels). Founder demand 2026-05-15.
const useDynamicOptions = (p, siblings) => {
  const [opts, setOpts] = React.useState(null);   // null = not loaded
  const [loading, setLoading] = React.useState(false);
  // Context = every OTHER param's value (the source op filters to what it needs).
  const ctx = {};
  (siblings || []).forEach(s => { if (s && s.k !== p.k) ctx[s.k] = s.v; });
  const ctxKey = JSON.stringify(ctx);
  React.useEffect(() => {
    if (!p.options_source) { setOpts(null); return; }
    let cancelled = false;
    const reqId = 'po_' + Math.random().toString(36).slice(2, 10);
    setLoading(true);
    const onReady = (ev) => {
      if (!ev.detail || ev.detail.req_id !== reqId) return;
      const rec = (window.__archhub_param_opts || {})[reqId];
      if (rec && !cancelled) {
        setOpts(Array.isArray(rec.options) ? rec.options : []);
        setLoading(false);
      }
      window.removeEventListener('lm-param-options', onReady);
    };
    window.addEventListener('lm-param-options', onReady);
    try {
      bridgeCall('request_param_options', reqId, p.options_source, ctxKey);
    } catch (e) { setLoading(false); }
    // Safety: stop the spinner if nothing answers in 4s.
    const t = setTimeout(() => { if (!cancelled) setLoading(false); }, 4000);
    return () => {
      cancelled = true;
      clearTimeout(t);
      window.removeEventListener('lm-param-options', onReady);
    };
  }, [p.options_source, ctxKey]);
  return { dynamicOpts: opts, loading };
};

// Provenance dot — who set this value. Founder: "fields can be readers
// displaying what the AI is interacting with." The dot makes that visible.
const ProvDot = ({ by }) => {
  const map = {
    you:  { c:LM.accent, t:'set by you' },
    ai:   { c:LM.purple, t:'set by AI' },
    host: { c:LM.cyan,   t:'from host' },
  };
  const m = map[by];
  if (!m) return null;
  return <span title={m.t} style={{ width:5, height:5, borderRadius:'50%',
    background:m.c, display:'inline-block', flexShrink:0 }}/>;
};

// ─── Type-aware parameter field — the widget grammar for connector-op
// node params. Renders the right control per ParamSpec type: text /
// number / bool / choice / multi / list / range / file. Choice/multi
// fields with an `options_source` populate live + cascade. Founder demand
// 2026-05-15: "fields should comprehend the data type inside."
const ParamField = ({ p, onChange, siblings }) => {
  const lbl = p.label || p.k;
  const { dynamicOpts, loading } = useDynamicOptions(p, siblings);
  const labelRow = (
    <div style={{ display:'flex', alignItems:'baseline', gap:6, marginBottom:4 }}>
      <ProvDot by={p._by}/>
      <span style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkSoft,
        letterSpacing:'0.04em' }}>{lbl}</span>
      {p.required && <span style={{ color:LM.accent, fontSize:9 }}>required</span>}
      {loading && <span style={{ color:LM.inkDim, fontSize:8.5,
        fontFamily:LM.mono }}>loading…</span>}
      <div style={{ flex:1 }}/>
      {p.help && <span title={p.help} style={{ color:LM.inkDim, fontSize:10, cursor:'help' }}>?</span>}
    </div>
  );
  const inputStyle = {
    width:'100%', padding:'6px 9px', background:LM.bg, border:`1px solid ${LM.line}`,
    borderRadius:5, fontFamily:LM.mono, fontSize:11, color:LM.ink, outline:'none',
  };
  // boolean / bool → toggle
  if (p.type === 'bool' || p.type === 'boolean') {
    return (
      <div style={{ display:'flex', alignItems:'center', gap:8 }}>
        <span style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkSoft, flex:1 }}>{lbl}</span>
        <button onClick={() => onChange(!p.v)} style={{
          width:32, height:17, borderRadius:999, padding:1, position:'relative', cursor:'pointer',
          background: p.v ? LM.accent : LM.lineSoft, border:0,
        }}>
          <span style={{ position:'absolute', top:1, left: p.v ? 15 : 1, width:15, height:15,
            borderRadius:'50%', background:'#fff', transition:'left .12s' }}/>
        </button>
      </div>
    );
  }
  // number / range → stepper (+ slider when min/max known)
  if (p.type === 'number' || p.type === 'range') {
    const hasRange = p.min != null && p.max != null;
    return (
      <div>
        {labelRow}
        <input type="number" value={p.v == null ? '' : p.v}
          min={p.min} max={p.max} step={p.step || 1}
          onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
          style={inputStyle}/>
        {hasRange && (
          <input type="range" min={p.min} max={p.max} step={p.step || 1}
            value={Number(p.v) || p.min}
            onChange={(e) => onChange(Number(e.target.value))}
            style={{ width:'100%', accentColor:LM.accent, marginTop:6 }}/>
        )}
      </div>
    );
  }
  // choice / enum / select → dropdown (dynamic options when available)
  if (p.type === 'choice' || p.type === 'enum' || p.type === 'select') {
    const raw = (dynamicOpts != null && dynamicOpts.length >= 0 && p.options_source)
      ? dynamicOpts : (p.options || []);
    const opts = raw.map(o =>
      typeof o === 'string' ? { id:o, label:o } : { id:o.id || o.value || o.name, label:o.label || o.name || o.id });
    return (
      <div>
        {labelRow}
        {opts.length > 0 ? (
          <select value={p.v == null ? '' : p.v} onChange={(e) => onChange(e.target.value)} style={inputStyle}>
            <option value="">— pick —</option>
            {opts.map((o, i) => <option key={i} value={o.id}>{o.label}</option>)}
          </select>
        ) : (
          <input value={p.v == null ? '' : p.v} onChange={(e) => onChange(e.target.value)}
            placeholder={p.options_source ? (loading ? 'loading…' : '(host has none — type a value)') : '(no options — type a value)'}
            style={inputStyle}/>
        )}
      </div>
    );
  }
  // multi → chips multi-select (dynamic options when available)
  if (p.type === 'multi') {
    const sel = Array.isArray(p.v) ? p.v : (p.v ? String(p.v).split(',').map(s => s.trim()).filter(Boolean) : []);
    const raw = (dynamicOpts != null && p.options_source) ? dynamicOpts : (p.options || []);
    const opts = raw.map(o => typeof o === 'string' ? o : (o.id || o.label));
    const toggle = (o) => {
      const next = sel.includes(o) ? sel.filter(x => x !== o) : [...sel, o];
      onChange(next);
    };
    return (
      <div>
        {labelRow}
        {opts.length > 0 ? (
          <div style={{ display:'flex', flexWrap:'wrap', gap:4 }}>
            {opts.map((o, i) => {
              const on = sel.includes(o);
              return (
                <button key={i} onClick={() => toggle(o)} style={{
                  padding:'2px 8px', borderRadius:3, fontFamily:LM.mono, fontSize:9.5,
                  cursor:'pointer', border:`1px solid ${on ? LM.accent : LM.line}`,
                  background: on ? LM.accentDim : 'transparent',
                  color: on ? LM.accent : LM.inkSoft,
                }}>{o}</button>
              );
            })}
          </div>
        ) : (
          <input value={sel.join(', ')} onChange={(e) => onChange(e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
            placeholder="comma-separated" style={inputStyle}/>
        )}
      </div>
    );
  }
  // list → multi-line textarea (one per line)
  if (p.type === 'list') {
    const txt = Array.isArray(p.v) ? p.v.join('\n') : (p.v || '');
    return (
      <div>
        {labelRow}
        <textarea value={txt} rows={3}
          onChange={(e) => onChange(e.target.value.split('\n').map(s => s.trim()).filter(Boolean))}
          style={{ ...inputStyle, resize:'vertical', lineHeight:1.5 }}/>
      </div>
    );
  }
  // file → text + (browse is a future host-picker)
  if (p.type === 'file') {
    return (
      <div>
        {labelRow}
        <input value={p.v == null ? '' : p.v} onChange={(e) => onChange(e.target.value)}
          placeholder="path…" style={inputStyle}/>
      </div>
    );
  }
  // text + default
  return (
    <div>
      {labelRow}
      <input value={p.v == null ? '' : p.v} onChange={(e) => onChange(e.target.value)}
        placeholder={p.placeholder || ''} style={inputStyle}/>
    </div>
  );
};

// ─── Connector-op property rail — the deep host-node UI. When a
// connector-op node is focused, the NodeRail shows: op identity, a
// tabbed/grouped editable parameter panel (type-aware ParamField per
// input), Run, and the live result. Founder demand 2026-05-15.
const ConnectorOpRail = ({ node, bumpGraph }) => {
  const col = CONNECTOR_COLORS[node.host] || LM.cyan;
  const params = node.params || [];
  const [tab, setTab] = React.useState(null);
  const setParam = (k, v) => {
    const p = (node.params || []).find(x => x.k === k);
    if (p) {
      p.v = v;
      p._by = 'you';   // provenance — the architect set this
      saveCurrentGraph(); bumpGraph && bumpGraph();
    }
  };
  // Group params by their `group` field (if connectors supply one).
  const groups = {};
  params.forEach(p => {
    const g = p.group || 'Parameters';
    (groups[g] = groups[g] || []).push(p);
  });
  const groupNames = Object.keys(groups);
  const activeTab = tab && groups[tab] ? tab : groupNames[0];
  const res = node.op_result;
  const running = !!node.op_running;
  return (
    <aside className="ah-scroll" style={{
      gridColumn:'2', gridRow:'2', background:LM.bgPanel,
      borderLeft:`1px solid ${LM.line}`, overflow:'auto', minHeight:0,
      padding:'14px 16px 20px', display:'flex', flexDirection:'column', gap:14,
    }}>
      {/* identity */}
      <div>
        <div style={{ display:'flex', alignItems:'center', gap:7 }}>
          <span style={{ width:7, height:7, borderRadius:2, background:col }}/>
          <span style={{ fontFamily:LM.mono, fontSize:9, color:col, letterSpacing:'0.16em' }}>
            {(node.host || '').toUpperCase()} · {node.op_kind === 'action' ? 'ACTION' : 'READ'}
          </span>
        </div>
        <div style={{ fontFamily:LM.serif, fontSize:20, letterSpacing:'-0.015em',
          marginTop:5, lineHeight:1.1 }}>{node.title}</div>
        <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted,
          marginTop:4, letterSpacing:'0.04em' }}>{node.op_id}</div>
        {node.destructive && (
          <div style={{ marginTop:6, fontFamily:LM.mono, fontSize:9, color:LM.warn,
            letterSpacing:'0.04em' }}>⚠ mutates the host — runs only on explicit click</div>
        )}
      </div>

      {/* tabbed params */}
      {params.length > 0 ? (
        <div>
          {groupNames.length > 1 && (
            <div style={{ display:'flex', gap:3, marginBottom:10, flexWrap:'wrap' }}>
              {groupNames.map(g => (
                <button key={g} onClick={() => setTab(g)} style={{
                  padding:'3px 9px', borderRadius:4, fontFamily:LM.mono, fontSize:9,
                  letterSpacing:'0.06em', cursor:'pointer',
                  border:`1px solid ${g === activeTab ? col : LM.line}`,
                  background: g === activeTab ? LM.accentDim : 'transparent',
                  color: g === activeTab ? col : LM.inkSoft,
                }}>{g.toUpperCase()}</button>
              ))}
            </div>
          )}
          {groupNames.length <= 1 && (
            <div style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted,
              letterSpacing:'0.18em', marginBottom:10 }}>PARAMETERS</div>
          )}
          <div style={{ display:'flex', flexDirection:'column', gap:12 }}>
            {(groups[activeTab] || []).map(p => (
              <ParamField key={p.k} p={p} siblings={params}
                onChange={(v) => setParam(p.k, v)}/>
            ))}
          </div>
        </div>
      ) : (
        <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted }}>
          No parameters — this op takes its input from a wired upstream node.
        </div>
      )}

      {/* run + result */}
      <div style={{ display:'flex', flexDirection:'column', gap:7 }}>
        <button disabled={running}
          onClick={() => {
            try { window.dispatchEvent(new CustomEvent('lm-run-connector-op',
              { detail:{ node_id: node.id } })); } catch (e) {}
          }}
          style={{ ...railBtn(), border:0,
            background: running ? LM.bgSoft : col,
            color: running ? LM.inkMuted : '#fff', fontWeight:600,
            cursor: running ? 'default' : 'pointer' }}>
          {running ? 'running…' : (node.destructive ? '▶ Run (action)' : '▶ Run op')}
        </button>
        {res && (
          <div style={{
            background:LM.bg, border:`1px solid ${res.ok ? LM.line : LM.err}`,
            borderLeft:`2px solid ${res.ok ? col : LM.err}`, borderRadius:5,
            padding:'8px 10px', fontFamily:LM.mono, fontSize:10,
            color: res.ok ? LM.inkSoft : LM.err, lineHeight:1.6,
          }}>
            <div style={{ color: res.ok ? col : LM.err, marginBottom:3,
              letterSpacing:'0.1em', fontSize:8.5 }}>
              {res.ok ? 'RESULT' : 'ERROR'}{res.elapsed_ms ? ` · ${res.elapsed_ms}ms` : ''}
            </div>
            {res.ok
              ? <div>{res.value_preview || 'done'}</div>
              : <div>{res.error || 'failed'}</div>}
          </div>
        )}
      </div>

      {/* connections */}
      {(node.ins?.length > 0 || node.outs?.length > 0) && (
        <div>
          <div style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted,
            letterSpacing:'0.18em', marginBottom:8 }}>CONNECTIONS</div>
          <div style={{ background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:6,
            padding:'10px 12px', display:'flex', flexDirection:'column', gap:8 }}>
            {(node.ins || []).map(s => <PinRow key={s.id} s={s} side="in"/>)}
            {(node.outs || []).map(s => <PinRow key={s.id} s={s} side="out"/>)}
          </div>
        </div>
      )}
    </aside>
  );
};

const NodeRail = ({ node, bumpGraph }) => {
  if (!node) return <aside style={{ gridColumn:'2', gridRow:'2', background:LM.bgPanel, borderLeft:`1px solid ${LM.line}` }}/>;
  // Founder demand #15: spread defaults so a partial node blob never KOs the rail.
  node = { ins:[], outs:[], messages:[], params:[], ...node };
  // AI node gets a dedicated conversation rail — full scrollback + composer
  if (node.cat === 'ai') return <ConversationRail node={node} bumpGraph={bumpGraph}/>;
  // Connector-op node gets the deep tabbed property panel.
  if (node.cat === 'connector_op') return <ConnectorOpRail node={node} bumpGraph={bumpGraph}/>;
  const cat = catMeta(node.cat);

  // Founder demand #10: writing a param updates node.config + saves graph.
  const onParamChange = (k, v) => {
    node.config = { ...(node.config || {}), [k]: v };
    // Also reflect into params for visual fidelity.
    if (Array.isArray(node.params)) {
      const p = node.params.find(x => x.k === k);
      if (p) p.v = v;
    }
    saveCurrentGraph();
    bumpGraph && bumpGraph();
  };
  return (
    <aside className="ah-scroll" style={{
      gridColumn:'2', gridRow:'2',
      background:LM.bgPanel, borderLeft:`1px solid ${LM.line}`,
      overflow:'auto', minHeight:0,
      padding:'14px 16px 20px',
      display:'flex', flexDirection:'column', gap:16,
    }}>
      <div>
        <div style={{ display:'flex', alignItems:'center', gap:7 }}>
          <span style={{ color:cat.col, fontFamily:LM.mono }}>{cat.icon}</span>
          <span style={{ fontFamily:LM.mono, fontSize:9, color:cat.col, letterSpacing:'0.18em' }}>{cat.label}</span>
        </div>
        <div style={{ fontFamily:LM.serif, fontSize:21, letterSpacing:'-0.015em', marginTop:5, lineHeight:1.05 }}>
          {node.title}
        </div>
        {node.sub && <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, marginTop:5, letterSpacing:'0.04em' }}>{node.sub}</div>}
      </div>

      {(node.ins || node.outs) && (
        <div>
          <div style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.18em', marginBottom:8 }}>CONNECTIONS</div>
          <div style={{ background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:6, padding:'10px 12px', display:'flex', flexDirection:'column', gap:10 }}>
            {node.ins?.length > 0 && (
              <div>
                <div style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.14em', marginBottom:4 }}>RECEIVES</div>
                {node.ins.map(s => <PinRow key={s.id} s={s} side="in"/>)}
              </div>
            )}
            {node.outs?.length > 0 && (
              <div>
                <div style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.14em', marginBottom:4 }}>SENDS</div>
                {node.outs.map(s => <PinRow key={s.id} s={s} side="out"/>)}
              </div>
            )}
          </div>
        </div>
      )}

      {(node.params || []).length > 0 && (
        <div>
          <div style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.18em', marginBottom:10 }}>SETTINGS</div>
          <div style={{ display:'flex', flexDirection:'column', gap:13 }}>
            {(node.params || []).map(p => <FullParam key={p.k} p={p} node={node} onChange={(v) => onParamChange(p.k, v)}/>)}
          </div>
        </div>
      )}

      <div style={{ display:'flex', flexDirection:'column', gap:5 }}>
        <button onClick={() => bridgeCall('run_node', currentSid(), node.id, JSON.stringify(LM_GRAPH))}
          style={{ ...railBtn(), background:LM.accent, color:'#fff', border:0 }}>↻ Rerun this node</button>
        <button onClick={() => {
          // Same as NodeMenu "Save as Skill" — call the real `save_as_skill`
          // slot with a JSON payload containing the focused node.
          const payload = JSON.stringify({ nodes:[node], wires:[] });
          bridgeCall('save_as_skill', node.title || node.id, payload);
        }} style={railBtn()}>Pin to skill</button>
        <button onClick={() => {
          // Branch: duplicate the focused node and wire the original's first
          // output to the duplicate's first matching input. The bridge slot
          // `duplicate_node(graph_json, node_id)` returns the mutated graph
          // (F2-A); if it's missing we synthesize the duplicate client-side.
          const sourceNode = (LM_GRAPH.nodes || []).find(n => n.id === node.id);
          if (!sourceNode) return;
          const result = bridgeJson('duplicate_node', JSON.stringify(LM_GRAPH), node.id);
          let newId = null;
          if (result && result.graph && Array.isArray(result.graph.nodes)) {
            LM_GRAPH.nodes = result.graph.nodes;
            LM_GRAPH.wires = result.graph.wires || [];
            newId = result.new_id || result.id;
          } else {
            // Fallback: copy in place.
            newId = (sourceNode.id || 'node') + '_copy_' + Date.now().toString(36).slice(-4);
            const copy = JSON.parse(JSON.stringify(sourceNode));
            copy.id = newId;
            copy.x = (sourceNode.x || 0) + 280;
            copy.y = (sourceNode.y || 0) + 40;
            copy.title = (sourceNode.title || '') + ' (branch)';
            copy._user = true;
            LM_GRAPH.nodes = [...(LM_GRAPH.nodes || []), copy];
          }
          // Wire source.first-output → newCopy.first-matching-input.
          if (newId) {
            const newNode = (LM_GRAPH.nodes || []).find(n => n.id === newId);
            const srcOut = (sourceNode.outs || [])[0];
            if (newNode && srcOut) {
              const matchIn = (newNode.ins || []).find(i => i.t === srcOut.t || i.t === 'any')
                           || (newNode.ins || [])[0];
              if (matchIn) {
                LM_GRAPH.wires = [...(LM_GRAPH.wires || []), {
                  from:[sourceNode.id, srcOut.id], to:[newNode.id, matchIn.id],
                }];
              }
            }
          }
          saveCurrentGraph(); bumpGraph && bumpGraph();
        }} style={railBtn()}>Branch from here</button>
        <button onClick={() => {
          LM_GRAPH.wires = (LM_GRAPH.wires || []).filter(w => w.from[0] !== node.id && w.to[0] !== node.id);
          saveCurrentGraph(); bumpGraph && bumpGraph();
        }} style={{ ...railBtn(), color:LM.err, borderColor:LM.lineSoft }}>Disconnect all</button>
      </div>
    </aside>
  );
};

// ─── Conversation rail — full chat history + inline composer ───
// Shown when the focused node is an AI/chat node. THIS is where the user
// reads scrollback and continues the conversation.
const ConversationRail = ({ node, bumpGraph }) => {
  // Founder demand #15: spread defaults so an empty/streaming AI node renders.
  node = { ins:[], outs:[], messages:[], params:[], ...node };
  const cat = catMeta('ai');
  const scrollRef = React.useRef(null);
  // Auto-scroll to bottom on new messages.
  React.useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [node.id, (node.messages || []).length]);

  // Founder demand: regen, branch, edit, copy on each chat turn.
  // Resolves the focused node by ref so mutations re-render via bumpGraph.
  const onTurnAction = React.useCallback((action, ix) => {
    const msgs = node.messages || [];
    const msg = msgs[ix];
    if (!msg) return;
    if (action === 'copy') {
      try {
        navigator.clipboard.writeText(msg.text || '');
        window.dispatchEvent(new CustomEvent('lm-canvas-toast', { detail:{ msg:'Copied to clipboard' } }));
      } catch (e) {}
      return;
    }
    if (action === 'regen') {
      // Find the most recent user message and re-send history up to (but not
      // including) the last assistant reply, then mark a streaming placeholder.
      const lastUser = [...msgs].reverse().find(m => m.me);
      if (!lastUser) return;
      const truncated = msgs.slice(0, msgs.length - 1); // drop the assistant tail
      const historyJson = JSON.stringify(truncated.map(m => ({ me:m.me, text:m.text })));
      node.messages = [...truncated, { me:false, text:'…', streaming:true, time:new Date().toISOString().slice(11,16) }];
      bridgeCall('send_chat_history', currentSid(), lastUser.text || '', historyJson);
      bumpGraph && bumpGraph();
      return;
    }
    if (action === 'branch') {
      // Spawn a fresh conversation node with the conversation up to this turn,
      // wire it from the same context input as the parent.
      const contextMessages = msgs.slice(0, ix + 1).map(m => ({ ...m }));
      const newId = node.id + '_branch_' + Date.now().toString(36).slice(-4);
      const newNode = {
        id: newId, cat:'ai', x: (node.x || 0) + 360, y: (node.y || 0) + 40,
        w: node.w || 300, h: node.h || 188,
        title: (node.title || 'Conversation') + ' (branch)',
        sub: node.sub || '',
        ins: node.ins || [{ id:'ctx', label:'context', t:'view' }],
        outs: node.outs || [{ id:'intent', label:'intent', t:'intent' }],
        messages: contextMessages,
        _user: true,
      };
      LM_GRAPH.nodes = [...(LM_GRAPH.nodes || []), newNode];
      // Mirror the inbound wires of the source node so the branch has the same
      // upstream context.
      const inbound = (LM_GRAPH.wires || []).filter(w => w.to[0] === node.id);
      LM_GRAPH.wires = [...(LM_GRAPH.wires || []), ...inbound.map(w => ({ ...w, to:[newId, w.to[1]] }))];
      saveCurrentGraph(); bumpGraph && bumpGraph();
      try { window.dispatchEvent(new CustomEvent('lm-canvas-toast', { detail:{ msg:'Branched conversation' } })); } catch (e) {}
      return;
    }
    if (action === 'edit') {
      // Find the user message preceding this assistant reply, prompt for new
      // text, truncate the history below it, then re-send.
      const findUserIx = (start) => { for (let i = start; i >= 0; i--) if (msgs[i].me) return i; return -1; };
      const userIx = findUserIx(ix - 1);
      if (userIx < 0) { try { window.dispatchEvent(new CustomEvent('lm-canvas-toast', { detail:{ msg:'No user turn to edit', kind:'err' } })); } catch (e) {} return; }
      const userMsg = msgs[userIx];
      const next = window.prompt('Edit message', userMsg.text || '');
      if (next == null || next === userMsg.text) return;
      const truncated = msgs.slice(0, userIx).map(m => ({ ...m }));
      truncated.push({ ...userMsg, text: next });
      const historyJson = JSON.stringify(truncated.map(m => ({ me:m.me, text:m.text })));
      node.messages = [...truncated, { me:false, text:'…', streaming:true, time:new Date().toISOString().slice(11,16) }];
      bridgeCall('send_chat_history', currentSid(), next, historyJson);
      bumpGraph && bumpGraph();
      return;
    }
  }, [node, bumpGraph]);
  return (
    <aside key={node.id} style={{
      gridColumn:'2', gridRow:'2',
      background:LM.bgPanel, borderLeft:`1px solid ${LM.line}`,
      display:'grid', gridTemplateRows:'auto 1fr auto', minHeight:0, overflow:'hidden',
      animation:'lmSlideIn .18s ease-out',
    }}>
      {/* Header */}
      <div style={{ padding:'12px 16px 10px', borderBottom:`1px solid ${LM.lineSoft}` }}>
        <div style={{ display:'flex', alignItems:'center', gap:7 }}>
          <span style={{ color:cat.col, fontFamily:LM.mono }}>{cat.icon}</span>
          <span style={{ fontFamily:LM.mono, fontSize:9, color:cat.col, letterSpacing:'0.18em' }}>CONVERSATION</span>
          <div style={{ flex:1 }}/>
          <span style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.06em' }}>
            {node.messages.length} msgs
          </span>
        </div>
        <div style={{ fontFamily:LM.serif, fontSize:18, letterSpacing:'-0.01em', marginTop:5, lineHeight:1.1 }}>
          {node.title}
        </div>
        <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, marginTop:3, letterSpacing:'0.04em' }}>
          {node.sub}
        </div>
      </div>

      {/* Scrollback */}
      <div ref={scrollRef} className="ah-scroll" style={{
        overflow:'auto', padding:'14px 16px',
        display:'flex', flexDirection:'column', gap:14,
      }}>
        {/* Date breakpoint */}
        <div style={{ display:'flex', alignItems:'center', gap:8, fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.14em' }}>
          <span style={{ flex:1, height:1, background:LM.lineHair }}/>
          <span>WEDNESDAY · MAY 13</span>
          <span style={{ flex:1, height:1, background:LM.lineHair }}/>
        </div>

        {(node.messages || []).map((m, i) => <ChatTurn key={i} m={m} ix={i} onAction={onTurnAction} isLast={i === (node.messages || []).length - 1}/>)}

        {/* Live tool-trace (founder demand #10). When the bridge streams tool
            invocations they land in node.tool_trace; we surface them here. */}
        {(node.tool_trace || []).length > 0 && (
          <div style={{
            padding:'9px 12px', background:LM.bgDeep, border:`1px solid ${LM.lineSoft}`,
            borderLeft:`2px solid ${LM.cyan}`, borderRadius:5,
            fontFamily:LM.mono, fontSize:10.5, color:LM.inkSoft, lineHeight:1.7,
          }}>
            <div style={{ fontFamily:LM.mono, fontSize:9, color:LM.cyan, letterSpacing:'0.14em', marginBottom:4 }}>
              TOOL TRACE
            </div>
            {(node.tool_trace || []).map((t, i) => (
              <div key={i}>→ {t.tool || t.name || 'tool'}{t.summary ? ` · ${t.summary}` : ''}{t.ms ? ` · ${t.ms}ms` : ''}</div>
            ))}
          </div>
        )}
      </div>
      {/* Founder demand #10: NO own composer. The FloatingComposer at the
          bottom of the canvas is the single composer. ConversationRail just
          shows scrollback + tool trace. */}
    </aside>
  );
};

// ─── Thinking indicator — replaces the literal "…" placeholder so a
// streaming-but-empty message reads as activity, not broken content.
// Founder bug 2026-05-15: "reasoning shows 3 dots".
const ThinkingDots = ({ color }) => (
  <span style={{ display:'inline-flex', alignItems:'center', gap:4, padding:'2px 0' }}>
    {[0, 1, 2].map(i => (
      <span key={i} style={{
        width:5, height:5, borderRadius:'50%', background: color || LM.accent,
        animation:'lmPulse 1s ease-in-out infinite',
        animationDelay: `${i * 0.18}s`,
      }}/>
    ))}
    <span style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted,
      marginLeft:4, letterSpacing:'0.06em' }}>thinking</span>
  </span>
);

// ─── Chat message renderer — splits ```code fences``` out of prose so an
// AI reply never dumps a wall of raw code inline. Prose wraps; code goes
// in a compact collapsible mono block. Founder demand 2026-05-15:
// "AI conversations should be organized and simplified."
// Detect + strip ANY tool-call / tool-result markup a model fabricated
// in chat. Founder bug 2026-05-15 (recurring): the model role-played a
// tool — first <function_calls>, then <tool_call> — and invented a
// <tool_result>. Quick patches chased tag names; this is generic: it
// matches any pseudo-XML container OR standalone tag whose name looks
// like tool/function/invoke/parameter machinery, with or without the
// antml: prefix, plural, or underscore variants. Returns {clean,
// fabricated} — fabricated=true means the model faked a tool, and the
// UI must show a loud honest correction, NOT the gutted text.
const _TOOL_NAME = '(?:antml:)?(?:function[_-]?calls?|function[_-]?results?|' +
                   'tool[_-]?calls?|tool[_-]?use|tool[_-]?results?|invoke|' +
                   'parameter)';
function _scrubToolMarkup(s) {
  let t = String(s || '');
  const before = t;
  // Whole container blocks (open … close), tolerant of mismatched names.
  t = t.replace(new RegExp('<' + _TOOL_NAME + '\\b[^>]*>[\\s\\S]*?<\\/' + _TOOL_NAME + '>', 'gi'), '');
  // Any leftover standalone tool-ish tag.
  t = t.replace(new RegExp('<\\/?' + _TOOL_NAME + '\\b[^>]*>', 'gi'), '');
  t = t.replace(/\n{3,}/g, '\n\n').trim();
  return { clean: t, fabricated: t !== before };
}

const ChatText = ({ text, size }) => {
  const scrub = _scrubToolMarkup(text);
  // The model faked a tool call. Never render its invented result — show
  // the architect an honest correction instead.
  if (scrub.fabricated) {
    return (
      <div style={{
        background:LM.err + '18', border:`1px solid ${LM.err}55`,
        borderRadius:5, padding:'7px 10px', fontSize:11.5, color:LM.ink,
        lineHeight:1.5,
      }}>
        <div style={{ fontFamily:LM.mono, fontSize:9, color:LM.err,
          letterSpacing:'0.1em', marginBottom:3 }}>⚠ FABRICATED TOOL CALL — IGNORED</div>
        The AI tried to fake a tool call and invent a result. It cannot
        touch a host from chat. To do this for real, add the matching
        connector-op node from the library and run it.
        {scrub.clean && (
          <div style={{ marginTop:5, color:LM.inkSoft, fontSize:11 }}>{scrub.clean}</div>
        )}
      </div>
    );
  }
  const s = scrub.clean;
  if (s.indexOf('```') === -1) {
    return <span style={{ whiteSpace:'pre-wrap', wordBreak:'break-word' }}>{s}</span>;
  }
  const parts = s.split(/```/);
  return (
    <span>
      {parts.map((seg, i) => {
        if (i % 2 === 0) {
          return seg
            ? <span key={i} style={{ whiteSpace:'pre-wrap', wordBreak:'break-word' }}>{seg}</span>
            : null;
        }
        // odd = code fence. First line may be a language tag.
        const nl = seg.indexOf('\n');
        const lang = nl > 0 && nl < 20 ? seg.slice(0, nl).trim() : '';
        const code = (lang ? seg.slice(nl + 1) : seg).replace(/\s+$/, '');
        return <ChatCodeBlock key={i} lang={lang} code={code}/>;
      })}
    </span>
  );
};

const ChatCodeBlock = ({ lang, code }) => {
  const lines = code.split('\n');
  const long = lines.length > 8;
  const [open, setOpen] = React.useState(!long);
  const shown = open ? code : lines.slice(0, 8).join('\n');
  return (
    <div style={{
      margin:'5px 0', background:LM.bgDeep, border:`1px solid ${LM.lineSoft}`,
      borderRadius:5, overflow:'hidden',
    }}>
      <div style={{
        display:'flex', alignItems:'center', gap:6, padding:'3px 8px',
        borderBottom:`1px solid ${LM.lineSoft}`, background:LM.bg,
      }}>
        <span style={{ fontFamily:LM.mono, fontSize:8.5, color:LM.inkMuted,
          letterSpacing:'0.1em', textTransform:'uppercase' }}>{lang || 'code'}</span>
        <span style={{ fontFamily:LM.mono, fontSize:8.5, color:LM.inkDim }}>
          {lines.length} line{lines.length === 1 ? '' : 's'}
        </span>
        <div style={{ flex:1 }}/>
        <button onClick={(e) => { e.stopPropagation();
          try { navigator.clipboard.writeText(code); } catch (er) {} }}
          style={{ background:'transparent', border:0, color:LM.inkMuted,
            cursor:'pointer', fontFamily:LM.mono, fontSize:8.5 }}>copy</button>
        {long && (
          <button onClick={(e) => { e.stopPropagation(); setOpen(o => !o); }}
            style={{ background:'transparent', border:0, color:LM.accent,
              cursor:'pointer', fontFamily:LM.mono, fontSize:8.5 }}>
            {open ? 'collapse' : `+${lines.length - 8}`}
          </button>
        )}
      </div>
      <pre style={{
        margin:0, padding:'7px 9px', fontFamily:LM.mono, fontSize:10,
        color:LM.inkSoft, lineHeight:1.5, overflow:'auto', maxHeight: open ? 260 : 'auto',
        whiteSpace:'pre',
      }}>{shown}</pre>
    </div>
  );
};

const ChatTurn = ({ m, ix, isLast, onAction }) => {
  const [showReasoning, setShowReasoning] = React.useState(false);
  const isAssistant = !m.me;
  const aiColor = m.col || (m.model && m.model.col) || LM.accent;
  const aiLetter = m.who || (m.model && m.model.who)
                    || ((m.model && m.model.name && m.model.name[0]) || 'A');
  const aiName = m.me ? 'You' : ((m.model && m.model.name) || 'AI');
  const fire = (k) => (e) => { e.stopPropagation(); onAction && onAction(k, ix); };
  return (
    <div style={{ display:'flex', gap:10 }}>
      <div title={aiName} style={{
        width:24, height:24, borderRadius: m.me ? '50%' : 5, flexShrink:0,
        background: m.me ? '#d8c5a8' : aiColor,
        color: m.me ? '#5a4a2a' : '#fff',
        display:'grid', placeItems:'center', fontSize:12, fontWeight:700,
      }}>{m.me ? 'Y' : aiLetter}</div>
      <div style={{ flex:1, minWidth:0 }}>
        <div style={{ display:'flex', alignItems:'baseline', gap:8, marginBottom:3 }}>
          <span style={{ fontSize:12, fontWeight:500, color: m.me ? LM.ink : aiColor }}>{aiName}</span>
          <span style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.04em' }}>{m.time}</span>
        </div>
        <div style={{ fontSize:13, lineHeight:1.55, color:LM.ink }}>
          {m.streaming && (!m.text || m.text === '…')
            ? <ThinkingDots color={aiColor}/>
            : <>
                <ChatText text={m.text}/>
                {isAssistant && isLast && m.streaming && (
                  <span style={{ display:'inline-block', width:6, height:12, background:aiColor, marginLeft:2, verticalAlign:'-1px', animation:'lmCaret 1s infinite' }}/>
                )}
              </>}
        </div>
        {isAssistant && Array.isArray(m.reasoning) && m.reasoning.length > 0 && (
          <>
            <button onClick={() => setShowReasoning(s => !s)} style={{
              background:'transparent', border:0, padding:'3px 0', color:LM.inkMuted,
              fontFamily:LM.mono, fontSize:9.5, letterSpacing:'0.06em', cursor:'pointer',
              display:'flex', alignItems:'center', gap:4, marginTop:3,
            }}>
              <span>{showReasoning ? '▾' : '▸'}</span> reasoning · {m.reasoning.length} step{m.reasoning.length === 1 ? '' : 's'}
            </button>
            {showReasoning && (
              <div style={{
                marginTop:3, padding:'5px 8px', background:LM.bgDeep,
                border:`1px solid ${LM.lineSoft}`, borderLeft:`2px solid ${LM.purple}`, borderRadius:3,
                fontFamily:LM.mono, fontSize:9.5, color:LM.inkSoft, lineHeight:1.6,
              }}>
                {m.reasoning.map((step, ri) => (
                  <div key={ri}>{ri+1}. {step}</div>
                ))}
              </div>
            )}
            <div style={{
              display:'flex', alignItems:'center', gap:5, marginTop:5,
              fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.04em',
            }}>
              <ChatAction onClick={fire('regen')}>↻ regen</ChatAction>
              <ChatAction onClick={fire('branch')}>⎘ branch</ChatAction>
              <ChatAction onClick={fire('edit')}>✎ edit</ChatAction>
              <ChatAction onClick={fire('copy')}>⧉ copy</ChatAction>
              <div style={{ flex:1 }}/>
              {(m.tokens_in || m.tokens_out) ? (
                <span>{m.tokens_in || 0} → {m.tokens_out || 0} tok</span>
              ) : null}
            </div>
          </>
        )}
      </div>
    </div>
  );
};

const ChatAction = ({ children, onClick }) => (
  <button onClick={onClick || (e => e.stopPropagation())} style={{
    padding:'1px 5px', background:'transparent', border:`1px solid ${LM.lineSoft}`,
    borderRadius:3, color:LM.inkMuted, fontFamily:LM.mono, fontSize:9, cursor:'pointer',
  }}>{children}</button>
);

const PinRow = ({ s, side }) => {
  const col = WIRE[s.t] || LM.inkSoft;
  return (
    <div style={{ display:'flex', alignItems:'center', gap:7, padding:'2px 0', fontFamily:LM.mono, fontSize:10.5 }}>
      <span style={{ width:7, height:7, borderRadius:'50%', background: side==='out' ? col : LM.bgPanel, border:`1.5px solid ${col}`, flexShrink:0 }}/>
      <span style={{ color:LM.inkMuted, letterSpacing:'0.04em' }}>{s.label || s.id}</span>
      <div style={{ flex:1, borderBottom:`1px dashed ${LM.lineSoft}`, marginBottom:2 }}/>
      <span style={{ color:LM.ink }}>{s.val || s.t}</span>
    </div>
  );
};

const railBtn = () => ({
  display:'flex', alignItems:'center', gap:9, padding:'7px 11px',
  background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:5,
  color:LM.ink, fontFamily:LM.sans, fontSize:12.5, cursor:'pointer', textAlign:'center',
  justifyContent:'center', fontWeight:500,
});

const FullParam = ({ p, node, onChange }) => {
  // Founder demand #10: text/number/boolean/enum/version/document widgets.
  // Version + document widgets are dynamic — populated from bridge.list_host_sessions
  // and bridge.list_host_documents.
  if (p.type === 'slider' || p.type === 'number') {
    const pct = (p.max !== undefined && p.min !== undefined)
      ? ((Number(p.v) - p.min) / (p.max - p.min)) * 100 : 50;
    return (
      <div>
        <div style={{ display:'flex', alignItems:'baseline', gap:6 }}>
          <span style={{ fontFamily:LM.mono, fontSize:10.5, color:LM.inkSoft, flex:1, letterSpacing:'0.04em' }}>{p.k}</span>
          <input value={p.v}
            onChange={(e) => onChange && onChange(p.type === 'number' ? Number(e.target.value) : e.target.value)}
            style={{
              fontFamily:LM.mono, fontSize:11.5, color:LM.ink, fontWeight:500,
              border:0, background:'transparent', width:60, textAlign:'right', outline:'none',
            }}/>
        </div>
        {p.max !== undefined && p.min !== undefined && (
          <>
            <input type="range" min={p.min} max={p.max} step={p.step || 1} value={p.v}
              onChange={(e) => onChange && onChange(Number(e.target.value))}
              style={{ width:'100%', accentColor:LM.accent, marginTop:6 }}/>
            <div style={{ display:'flex', justifyContent:'space-between', marginTop:3, fontFamily:LM.mono, fontSize:9, color:LM.inkMuted }}>
              <span>{p.min}</span><span>{p.max}</span>
            </div>
          </>
        )}
      </div>
    );
  }
  if (p.type === 'boolean') {
    return (
      <div style={{ display:'flex', alignItems:'center', gap:8 }}>
        <span style={{ fontFamily:LM.mono, fontSize:10.5, color:LM.inkSoft, flex:1 }}>{p.k}</span>
        <button onClick={() => onChange && onChange(!p.v)} style={{
          width:30, height:16, borderRadius:999, padding:1, position:'relative', cursor:'pointer',
          background: p.v ? LM.accent : LM.lineSoft, border:0,
        }}>
          <span style={{ position:'absolute', top:1, left: p.v ? 14 : 1, width:14, height:14, borderRadius:'50%', background:'#fff' }}/>
        </button>
      </div>
    );
  }
  if (p.type === 'text') {
    return (
      <div>
        <div style={{ fontFamily:LM.mono, fontSize:10.5, color:LM.inkSoft, marginBottom:4, letterSpacing:'0.04em' }}>{p.k}</div>
        <input value={p.v} onChange={(e) => onChange && onChange(e.target.value)} style={{
          width:'100%', padding:'7px 10px', background:LM.bg, border:`1px solid ${LM.line}`,
          borderRadius:5, fontFamily:LM.mono, fontSize:11, color:LM.ink, outline:'none',
        }}/>
      </div>
    );
  }
  // version + document: dynamic enums from bridge.
  if (p.type === 'version' || p.type === 'document') {
    const family = (node && (node.host || (node.title || '').toLowerCase())) || (p.family || 'revit');
    const [options, setOptions] = React.useState(p.options || []);
    React.useEffect(() => {
      const slot = p.type === 'version' ? 'list_host_sessions' : 'list_host_documents';
      const args = p.type === 'version' ? [family] : [family, p.session || ''];
      const data = bridgeJson(slot, ...args);
      if (Array.isArray(data)) setOptions(data);
      else if (data && Array.isArray(data.items)) setOptions(data.items);
    }, [family, p.session]);
    return (
      <div>
        <div style={{ fontFamily:LM.mono, fontSize:10.5, color:LM.inkSoft, marginBottom:4 }}>{p.k}</div>
        <select value={p.v} onChange={(e) => onChange && onChange(e.target.value)} style={{
          width:'100%', padding:'7px 10px', background:LM.bg, border:`1px solid ${LM.line}`,
          borderRadius:5, fontFamily:LM.mono, fontSize:11, color:LM.ink, outline:'none',
        }}>
          {options.map((o, i) => {
            const v = typeof o === 'string' ? o : (o.id || o.name || o.label || '');
            const lbl = typeof o === 'string' ? o : (o.label || o.name || o.id || '');
            return <option key={i} value={v}>{lbl}</option>;
          })}
        </select>
      </div>
    );
  }
  // select / enum / default
  return (
    <div>
      <div style={{ fontFamily:LM.mono, fontSize:10.5, color:LM.inkSoft, marginBottom:4, letterSpacing:'0.04em' }}>{p.k}</div>
      {Array.isArray(p.options) && p.options.length > 0 ? (
        <select value={p.v} onChange={(e) => onChange && onChange(e.target.value)} style={{
          width:'100%', padding:'6px 10px', background:LM.bg, border:`1px solid ${LM.line}`,
          borderRadius:5, fontFamily:LM.mono, fontSize:11, color:LM.ink, outline:'none',
        }}>
          {p.options.map((o, i) => <option key={i} value={typeof o==='string' ? o : o.id}>{typeof o==='string' ? o : (o.label || o.id)}</option>)}
        </select>
      ) : (
        <input value={p.v} onChange={(e) => onChange && onChange(e.target.value)} style={{
          width:'100%', padding:'6px 10px', background:LM.bg, border:`1px solid ${LM.line}`,
          borderRadius:5, fontFamily:LM.mono, fontSize:11, color:LM.ink, outline:'none',
        }}/>
      )}
    </div>
  );
};

// ──────────────────────── SETTINGS ────────────────────────
// Founder demand #4 / brutal-audit #17: bridge.open_settings() opens the
// native PyQt SettingsDialog (single source of truth). The React Settings
// overlay was a mountain of hardcoded numbers that never reflected real
// state. We keep only a thin stub: when the fallback path mounts us (bridge
// missing in dev preview), we immediately delegate and close.
const Settings = ({ onClose }) => {
  React.useEffect(() => {
    if (window.archhub && typeof window.archhub.open_settings === 'function') {
      try { window.archhub.open_settings(); } catch (e) {}
    }
    onClose && onClose();
  }, []);
  return null;
};

// ──────────────────────── MODEL PICKER ────────────────────────
const ModelPicker = ({ setModel, onClose, model }) => {
  // Real model list from bridge.get_models. The router knows 15+ models
  // (Anthropic/OpenAI/Google/OpenRouter/Ollama/LMStudio) keyed by
  // `<provider>:<id>`. We map each into a UI row + group by vendor.
  const [groups, setGroups] = React.useState([]);
  const [q, setQ] = React.useState('');
  React.useEffect(() => {
    let cancel = false;
    const fallback = [{
      name:'CLOUD · subscription', items: [
        { id:'auto', name:'Auto (route to best available)', vendor:'ArchHub',
          tag:'AUTO', ctx:'—', col:'#cc785c', cost:'router picks', latency:0 },
      ],
    }];
    // Show fallback immediately so the UI never appears empty while bridge
    // round-trips. Replace once real list arrives.
    setGroups(fallback);
    // QWebChannel slot is async — sync bridgeJson returned null/Promise,
    // so the picker only ever showed "Auto". Founder bug 2026-05-15.
    Promise.all([
      bridgeAsync('get_models'),
      bridgeAsync('get_local_llms'),
    ]).then(([real, locals]) => {
      if (cancel) return;
      if (Array.isArray(real) && real.length > 0) {
        _hydrate(real, Array.isArray(locals) ? locals : []);
      } else if (Array.isArray(locals)) {
        _hydrate([], locals);
      }
    });
    return () => { cancel = true; };
  }, []);
  const _hydrate = (real, locals) => {
    // Bridge returns: [{id, label, provider, configured, blocked}, ...]
    const colorFor = (p) => ({
      anthropic:'#cc785c', openai:'#10a37f', google:'#4285f4',
      openrouter:'#3a6acc', ollama:'#1a8a4a', lmstudio:'#6a72ff',
      archhub_cloud:'#cc785c',
    })[String(p || '').toLowerCase()] || '#888888';
    const groupLabel = (p) => ({
      anthropic:'CLOUD · Anthropic',
      openai:'CLOUD · OpenAI',
      google:'CLOUD · Google',
      openrouter:'BYO · OpenRouter',
      ollama:'LOCAL · Ollama',
      lmstudio:'LOCAL · LM Studio',
      archhub_cloud:'CLOUD · ArchHub',
    })[String(p || '').toLowerCase()] || ('PROVIDER · ' + (p || '').toUpperCase());
    const tagFor = (p) => ({
      anthropic:'CLOUD', openai:'CLOUD', google:'CLOUD',
      openrouter:'BYO', ollama:'LOCAL', lmstudio:'LOCAL',
      archhub_cloud:'CLOUD',
    })[String(p || '').toLowerCase()] || 'BYO';
    const byProvider = {};
    real.forEach((m) => {
      const p = m.provider || (String(m.id || '').split(':')[0]) || 'unknown';
      const key = String(p).toLowerCase();
      (byProvider[key] = byProvider[key] || []).push({
        id: m.id, name: m.label || m.id, vendor: p, tag: tagFor(p),
        ctx: m.ctx || '', col: colorFor(p),
        cost: m.configured ? 'configured' : (m.blocked ? 'blocked' : 'no key set'),
        latency: m.latency || 0,
        configured: !!m.configured, blocked: !!m.blocked,
      });
    });
    const ordered = ['anthropic','openai','google','openrouter','ollama','lmstudio'];
    const next = [];
    ordered.forEach((k) => { if (byProvider[k]) {
      next.push({ name: groupLabel(k), items: byProvider[k] });
      delete byProvider[k];
    }});
    Object.keys(byProvider).forEach((k) => next.push({ name: groupLabel(k), items: byProvider[k] }));
    // ── Local LLM apps detected on this machine. Founder demand
    // 2026-05-15: surface Claude Desktop / Claude CLI / Codex CLI /
    // LM Studio / Ollama / Jan / GPT4All / LocalAI / Llamafile / Cursor.
    const detected = (locals || []).filter(l => l && (l.installed || l.running));
    if (detected.length) {
      next.push({
        name: 'LOCAL · detected on this machine',
        items: detected.map(l => ({
          id:   `local:${l.id}`,
          name: l.name,
          vendor: l.kind === 'cli' ? 'CLI' : (l.kind === 'app' ? 'App' : 'Endpoint'),
          tag:  l.running ? 'LIVE' : 'INSTALLED',
          ctx:  l.endpoint || (l.exec ? '· exec' : ''),
          col:  l.icon_color || '#888',
          cost: l.note,
          configured: !!l.running,
          blocked:    false,
        })),
      });
    }
    setGroups(next);
  };
  const filteredGroups = React.useMemo(() => {
    if (!q) return groups;
    const needle = q.toLowerCase();
    return groups
      .map(g => ({ ...g, items: (g.items || []).filter(m =>
        (m.name || '').toLowerCase().includes(needle)
        || (m.id || '').toLowerCase().includes(needle)
        || (m.vendor || '').toLowerCase().includes(needle))
      }))
      .filter(g => g.items.length > 0);
  }, [groups, q]);
  // F2-A bridge slot: persist the chosen model id so the backend sends future
  // messages to the right provider. Fails gracefully if bridge slot missing.
  const pickModel = (m) => {
    setModel(m);
    bridgeCall('set_model', m.id || m.name);
    onClose();
  };
  return (
    <div onClick={onClose} style={{
      position:'absolute', inset:0, background:'rgba(0,0,0,.55)',
      display:'grid', placeItems:'start center', paddingTop:60, zIndex:50,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        width:600, maxWidth:'92%', background:LM.bgPanel, border:`1px solid ${LM.line}`,
        borderRadius:10, overflow:'hidden', boxShadow:'0 30px 80px rgba(0,0,0,.6)',
      }}>
        <div style={{ padding:'12px 14px', borderBottom:`1px solid ${LM.line}`, display:'flex', alignItems:'center', gap:10 }}>
          <span style={{ fontSize:14 }}>⌕</span>
          <input autoFocus value={q} onChange={e => setQ(e.target.value)}
            placeholder="Search models or paste an OpenRouter id…" style={{
            flex:1, border:0, background:'transparent', color:LM.ink, fontSize:13.5, outline:'none', fontFamily:LM.sans,
          }}/>
          <kbd style={kbd()}>esc</kbd>
        </div>
        <div className="ah-scroll" style={{ maxHeight:420, overflow:'auto', padding:'6px 8px 10px' }}>
          {filteredGroups.length === 0 && (
            <div style={{ padding:'24px', fontFamily:LM.serif, fontStyle:'italic',
                          fontSize:13, color:LM.inkMuted, textAlign:'center' }}>
              No models match "{q}". Sign in to a provider in Settings to enable more.
            </div>
          )}
          {filteredGroups.map(g => (
            <div key={g.name} style={{ marginTop:8 }}>
              <div style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.18em', padding:'4px 10px' }}>{g.name}</div>
              {g.items.map(m => {
                const sel = m.name === model.name;
                return (
                  <div key={m.name} onClick={() => pickModel(m)} style={{
                    display:'flex', alignItems:'center', gap:10, padding:'8px 10px', borderRadius:6, cursor:'pointer',
                    background: sel ? LM.bgSoft : 'transparent',
                  }}
                  onMouseEnter={e => !sel && (e.currentTarget.style.background = LM.bgHover)}
                  onMouseLeave={e => !sel && (e.currentTarget.style.background = 'transparent')}>
                    <span style={{ width:22, height:22, borderRadius:4, background:m.col, color:'#fff', display:'grid', placeItems:'center', fontFamily:LM.mono, fontSize:11, fontWeight:700 }}>{m.name[0]}</span>
                    <div style={{ flex:1, lineHeight:1.15 }}>
                      <div style={{ fontSize:13 }}>{m.name}</div>
                      <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.04em' }}>{m.vendor} · ctx {m.ctx} · {m.cost}</div>
                    </div>
                    <span style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.ok }}>{m.latency}ms</span>
                    <span style={{
                      fontFamily:LM.mono, fontSize:9, padding:'2px 7px', borderRadius:3, letterSpacing:'0.08em',
                      background: m.tag==='CLOUD'?LM.accentDim : m.tag==='LOCAL'?LM.ok+'22' : LM.cyan+'22',
                      color:       m.tag==='CLOUD'?LM.accent    : m.tag==='LOCAL'?LM.ok      : LM.cyan,
                    }}>{m.tag}</span>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

// ──────────────────────── SERVER STRIP ────────────────────────
const ServerStrip = ({ session, model, setSettingsOpen }) => {
  const live = (LM_HOSTS || []).filter(h => h.state !== 'off').length;
  const StripItem = ({ onClick, children, accent }) => {
    const [h, setH] = React.useState(false);
    return (
      <button onClick={onClick}
        onMouseEnter={() => setH(true)} onMouseLeave={() => setH(false)}
        style={{
          background:'transparent', border:0, padding:'0 4px',
          cursor: onClick ? 'pointer' : 'default',
          color: h && onClick ? LM.ink : (accent || LM.inkMuted),
          fontFamily:LM.mono, fontSize:9.5, letterSpacing:'0.05em',
          transition:'color .12s',
        }}>{children}</button>
    );
  };
  return (
    <div style={{
      gridColumn:'1 / -1', gridRow:'2',
      background:LM.bgPanel, borderTop:`1px solid ${LM.line}`,
      padding:'0 10px', display:'flex', alignItems:'center', gap:4,
    }}>
      <StripItem onClick={() => setSettingsOpen && setSettingsOpen(true)}>
        <span style={{ color:LM.ok }}>●</span> server :7300 · {live}/{(LM_HOSTS || []).length} hosts
      </StripItem>
      {session ? (
        <>
          <span style={{ color:LM.inkDim, padding:'0 2px' }}>·</span>
          <StripItem>{session.file}</StripItem>
          <span style={{ color:LM.inkDim, padding:'0 2px' }}>·</span>
          <StripItem onClick={() => setSettingsOpen && setSettingsOpen(true)}>
            <span style={{ color:LM.inkSoft }}>{model.name.toLowerCase().replace(/\s+/g,'-')}</span> · 4.2k tok · $0.024
          </StripItem>
        </>
      ) : (
        <>
          <span style={{ color:LM.inkDim, padding:'0 2px' }}>·</span>
          <StripItem>{(LM_SESSIONS || []).length} sessions · {(LM_SESSIONS || []).filter(s=>s.state==='running').length} running</StripItem>
        </>
      )}
      <div style={{ flex:1 }}/>
      <StripItem onClick={() => setSettingsOpen && setSettingsOpen(true)}>settings</StripItem>
      <span style={{ color:LM.inkDim, padding:'0 2px' }}>·</span>
      <StripItem>v1.4 prototype</StripItem>
    </div>
  );
};

window.StudioLM = StudioLM;

})();
