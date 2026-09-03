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

const LM = window.AH;  // tokens.jsx — single source of truth

// ─── Categories — each is a node type with color + icon + role ───
const CAT = {
  wire:      { col:LM.inkSoft, icon:'⇄', label:'CONNECTION' },
  host:      { col:LM.cyan,    icon:'⌬', label:'HOST',      role:'Connected app' },
  read:      { col:LM.cyan,    icon:'◇', label:'READ',      role:'Pulls data from a host' },
  filter:    { col:LM.inkSoft, icon:'⌗', label:'FILTER',    role:'Filters a stream' },
  transform: { col:LM.warn,    icon:'⌭', label:'TRANSFORM', role:'Modifies elements' },
  annotate:  { col:LM.accent,  icon:'✎', label:'ANNOTATE',  role:'Adds dims / tags / text' },
  compose:   { col:LM.accent,  icon:'▤', label:'COMPOSE',   role:'Builds schedules / sheets' },
  logic:     { col:LM.purple,  icon:'⌥', label:'LOGIC',     role:'Branch / loop / switch' },
  ai:        { col:LM.purple,  icon:'✦', label:'AI',        role:'LLM reasoning, vision, match' },
  output:    { col:LM.ok,      icon:'↗', label:'OUTPUT',    role:'Publishes / saves / notifies' },
};

const WIRE = {
  view:LM.cyan, selection:LM.cyan, walls:LM.accent, doors:LM.accent, sheets:LM.accent,
  intent:LM.purple, prediction:LM.purple, trace:LM.inkSoft, dims:LM.ok, file:LM.ok, any:LM.inkSoft,
};

// ──────────────────────── DATA ────────────────────────
const LM_SESSIONS = (window.ARCHHUB_LIVE?.sessions) || [];
const _SEED_SESSIONS = [
  { id:'walls',   title:'Schedule wall types',   state:'running',  host:'revit',
    file:'Tower-A_central.rvt · L03', model:'sonnet 4.5', when:'1 min',
    last:'Placing 37 dimensions across 2 stages.' },
  { id:'sketch',  title:'Sketch → mass',         state:'done',     host:['blender','speckle'],
    file:'sketch.blend → tower-a/main', model:'sonnet 4.5', when:'12 min',
    last:'4 floors extracted · pushed to Speckle commit cbb8e2.' },
  { id:'doors',   title:'Door schedule QA',      state:'review',   host:'revit',
    file:'Tower-A_central.rvt', model:'sonnet 4.5', when:'1 h',
    last:'8 issues found · 3 missing rooms, 2 fire ratings, 3 swing conflicts.' },
  { id:'panels',  title:'Facade panel study',    state:'paused',   host:'rhino',
    file:'panels.3dm', model:'opus 4', when:'3 h',
    last:'8 variants saved · waiting for client feedback.' },
  { id:'sheets',  title:'Sheet set publisher',   state:'workflow', host:'revit',
    file:'12 sheets · A.101 → A.112', model:'haiku 4.5', when:'runs Fri',
    last:'Last run produced a 24 MB PDF set · auto-uploaded to Dropbox.' },
  { id:'outlook', title:'PM Outlook triage',     state:'scheduled',host:'outlook',
    file:'every morning · 08:30', model:'haiku 4.5', when:'today 08:30',
    last:'Routed 4 emails to threads · drafted 2 replies for review.' },
];

const LM_HOSTS = (window.ARCHHUB_LIVE?.hosts) || [];
const _SEED_HOSTS = [
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
};

// ─── The active graph for "walls" session — typed AEC nodes
const LM_GRAPH = (window.ARCHHUB_LIVE?.graph) || { nodes: [], wires: [] };
const _SEED_GRAPH = {
  nodes: [
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
const LM_LIBRARY = [
  { cat:'host', items:[
    { id:'h_revit',   title:'Revit',    sub:'open document, view, selection' },
    { id:'h_rhino',   title:'Rhino',    sub:'curves, meshes, layers' },
    { id:'h_blender', title:'Blender',  sub:'mesh, sketch, render' },
    { id:'h_speckle', title:'Speckle',  sub:'commit, stream, branch' },
    { id:'h_dropbox', title:'Dropbox',  sub:'folder watch, upload' },
    { id:'h_outlook', title:'Outlook',  sub:'inbox watch, draft, route' },
  ]},
  { cat:'read', items:[
    { id:'r_walls',     title:'list_walls',    sub:'pull walls from active view' },
    { id:'r_doors',     title:'list_doors',    sub:'pull doors + swings + marks' },
    { id:'r_windows',   title:'list_windows',  sub:'pull windows + types' },
    { id:'r_sheets',    title:'list_sheets',   sub:'enumerate sheets in set' },
    { id:'r_views',     title:'list_views',    sub:'plans, sections, schedules' },
    { id:'r_levels',    title:'list_levels',   sub:'levels + elevations' },
    { id:'r_selection', title:'get_selection', sub:'whatever is selected in host' },
    { id:'r_warnings',  title:'list_warnings', sub:'host warnings · by severity' },
  ]},
  { cat:'filter', items:[
    { id:'f_type',  title:'where type',      sub:'by family/type' },
    { id:'f_cat',   title:'where category',  sub:'by Revit category' },
    { id:'f_level', title:'where level',     sub:'by level reference' },
    { id:'f_param', title:'where parameter', sub:'predicate on a parameter' },
    { id:'f_pred',  title:'where custom',    sub:'arbitrary JS predicate' },
  ]},
  { cat:'transform', items:[
    { id:'t_setp',  title:'set parameter',   sub:'mutates parameter values' },
    { id:'t_move',  title:'move',            sub:'translation' },
    { id:'t_rot',   title:'rotate',          sub:'rotation' },
    { id:'t_scale', title:'scale',           sub:'uniform / per-axis' },
    { id:'t_group', title:'group by',        sub:'key → list' },
    { id:'t_sort',  title:'sort by',         sub:'asc / desc on key' },
  ]},
  { cat:'annotate', items:[
    { id:'a_dims',  title:'create_dimensions', sub:'aligned, parallel, baseline' },
    { id:'a_tags',  title:'place_tags',         sub:'tag per element + leader' },
    { id:'a_text',  title:'add_text',           sub:'text note · positioned' },
    { id:'a_rooms', title:'tag_rooms',          sub:'room boundaries + names' },
  ]},
  { cat:'compose', items:[
    { id:'c_sched', title:'build_schedule',  sub:'table from a stream' },
    { id:'c_sheet', title:'place_on_sheet',  sub:'lay views onto a sheet' },
    { id:'c_legend',title:'make_legend',     sub:'symbol legend block' },
  ]},
  { cat:'logic', items:[
    { id:'l_if',     title:'if',     sub:'predicate → true / false branches' },
    { id:'l_switch', title:'switch', sub:'multi-branch on a key' },
    { id:'l_loop',   title:'loop',   sub:'iterate over a list' },
    { id:'l_merge',  title:'merge',  sub:'concat / dedupe streams' },
  ]},
  { cat:'ai', items:[
    { id:'i_think', title:'think',  sub:'Claude reasoning · sonnet/opus/haiku' },
    { id:'i_vis',   title:'vision', sub:'parse a sketch / screenshot' },
    { id:'i_match', title:'match_skill', sub:'find best saved skill for intent' },
    { id:'i_embed', title:'embed',  sub:'vectorize · similarity search' },
  ]},
  { cat:'output', items:[
    { id:'o_skill', title:'save_skill',     sub:'template this run' },
    { id:'o_pdf',   title:'publish_pdf',    sub:'sheets → PDF set' },
    { id:'o_spk',   title:'push_speckle',   sub:'commit to a branch' },
    { id:'o_email', title:'send_email',     sub:'draft + send via Outlook' },
    { id:'o_notify',title:'notify',         sub:'desktop / Teams ping' },
  ]},
];

// ──────────────────────── ROOT ────────────────────────
const StudioLM = () => {
  const [openId, setOpenId] = React.useState(LM_SESSIONS[0]?.id || null);
  const [openTabs, setOpenTabs] = React.useState(LM_SESSIONS.slice(0, 3).map(s => s.id));
  const [model, setModel] = React.useState({ name:'Claude Sonnet 4.5', route:'anthropic/claude-sonnet-4.5', vendor:'Anthropic', tag:'CLOUD', ctx:'200k', col:'#cc785c', latency:412 });
  const [pickerOpen, setPickerOpen] = React.useState(false);
  const [settingsOpen, setSettingsOpen] = React.useState(false);
  const [account, setAccount] = React.useState(() => acLoad());
  const [booting, setBooting] = React.useState(true);
  const [signUpOpen, setSignUpOpen] = React.useState(false);
  React.useEffect(() => { if (settingsOpen) setAccount(acLoad()); }, [settingsOpen]);
  React.useEffect(() => {
    const onStore = (e) => { if (!e.key || e.key === 'archhub.account.v1') setAccount(acLoad()); };
    window.addEventListener('storage', onStore);
    return () => window.removeEventListener('storage', onStore);
  }, []);
  const signOut = () => { const next = Object.assign({}, account, { signedIn: false }); acSave(next); setAccount(next); setSettingsOpen(false); setSignUpOpen(true); };
  const [docsOpen, setDocsOpen] = React.useState(false);
  const [libraryOpen, setLibraryOpen] = React.useState(false);
  const [panel, setPanel] = React.useState('nodes'); // chats | nodes | skills | search
  const [focusId, setFocusId] = React.useState(LM_GRAPH.nodes[0]?.id || null);
  // User-added nodes appear on top of the demo graph
  const [userNodes, setUserNodes] = React.useState([]);
  const session = openId ? LM_SESSIONS.find(s => s.id === openId) : null;

  // open a session — also pin as a tab if not already open
  const openSession = (id) => {
    if (id && !openTabs.includes(id)) setOpenTabs(t => [...t, id]);
    setOpenId(id);
  };
  const closeTab = (id) => {
    setOpenTabs(t => {
      const next = t.filter(x => x !== id);
      if (openId === id) setOpenId(next[next.length - 1] || null);
      return next;
    });
  };

  // Insert a node from the library at canvas coords (x,y). called from drop or dbl-click
  const addNodeFromLibrary = (libItem, x = 200, y = 200) => {
    const cat = libItem.cat;
    const tmpl = LM_NODE_TEMPLATES[libItem.id] || LM_NODE_TEMPLATES[`__cat_${cat}`] || {};
    const id = `${libItem.id}_${Date.now().toString(36).slice(-4)}`;
    const newNode = {
      id, cat, x, y, w: tmpl.w || 220, h: tmpl.h || 110,
      title: libItem.title, sub: libItem.sub,
      ins: tmpl.ins || [], outs: tmpl.outs || [],
      params: tmpl.params || [],
      _user: true,
    };
    setUserNodes(ns => [...ns, newNode]);
    setFocusId(id);
  };

  // Docs and Settings are mutually exclusive — they share a z-index, so opening one closes the other.
  const openSettings = (v) => { if (v) setDocsOpen(false); setSettingsOpen(v); };
  const openDocs = (v) => { if (v) setSettingsOpen(false); setDocsOpen(v); };

  // ⌘/ docs · ⌘, settings — the keys the Shortcuts sheet documents
  React.useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') { setDocsOpen(false); setSettingsOpen(false); return; }
      if (!(e.metaKey || e.ctrlKey)) return;
      if (e.key === '/') { e.preventDefault(); setDocsOpen(o => { if (!o) setSettingsOpen(false); return !o; }); }
      else if (e.key === ',') { e.preventDefault(); setSettingsOpen(o => { if (!o) setDocsOpen(false); return !o; }); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <div style={{
      width:'100%', height:'100%', background:LM.bg, color:LM.ink,
      fontFamily:LM.sans, fontSize:13, lineHeight:1.5,
      display:'grid',
      gridTemplateColumns:'292px 1fr',
      gridTemplateRows:'1fr 22px',
      overflow:'hidden', position:'relative',
    }}>
      <Sidebar
        panel={panel} setPanel={setPanel}
        openId={openId} onOpen={openSession}
        onHome={() => setOpenId(null)} onSettings={() => { setDocsOpen(false); setSettingsOpen(true); }} onDocs={() => { setSettingsOpen(false); setDocsOpen(true); }}
        addNodeFromLibrary={addNodeFromLibrary}/>
      {session
        ? <Workspace
            session={session} model={model}
            openTabs={openTabs} setOpenId={setOpenId} closeTab={closeTab}
            setPickerOpen={setPickerOpen}
            setSettingsOpen={openSettings}
            setLibraryOpen={setLibraryOpen}
            focusId={focusId} setFocusId={setFocusId}
            userNodes={userNodes} addNodeFromLibrary={addNodeFromLibrary}
            onHome={() => setOpenId(null)}/>
        : <Home onOpen={openSession} model={model} setPickerOpen={setPickerOpen}/>}
      <ServerStrip session={session} model={model} setSettingsOpen={openSettings} setDocsOpen={openDocs}/>
      {pickerOpen && <ModelPicker setModel={setModel} onClose={() => setPickerOpen(false)} model={model}/>}
      {settingsOpen && <Settings onClose={() => setSettingsOpen(false)} account={account} setAccount={setAccount} onSignOut={signOut}/>}
      {signUpOpen && <SignUp onDone={(rec) => { setAccount(rec); setSignUpOpen(false); }} onCancel={() => setSignUpOpen(false)} plan={account.plan}/>}
      {booting && <AppBoot account={account} onDone={() => setBooting(false)}/>}
      {docsOpen && <Docs onClose={() => setDocsOpen(false)}/>}
      {libraryOpen && <NodeLibrary onClose={() => setLibraryOpen(false)} addNodeFromLibrary={addNodeFromLibrary}/>}
      <style>{`
        @keyframes lmPulse { 0%,100% { opacity:.4 } 50% { opacity:1 } }
        @keyframes lmCaret { 50% { opacity: 0 } }
        @keyframes lmDash  { to { stroke-dashoffset: -16 } }
        @keyframes lmSlideIn { from { transform: translateX(8px); opacity: 0 } to { transform: translateX(0); opacity: 1 } }
        @keyframes lmPop    { from { transform: scale(.92); opacity: 0 } to { transform: scale(1); opacity: 1 } }
      `}</style>
    </div>
  );
};

// ─── Node templates ─ default I/O & params per library item ───
// keyed by library item id; falls back to a per-category template.
const LM_NODE_TEMPLATES = {
  // hosts
  h_revit:    { w:220, h:118, outs:[{ id:'view', label:'active view', t:'view' }, { id:'sel', label:'selection', t:'selection' }] },
  h_rhino:    { w:220, h:118, outs:[{ id:'mesh', label:'mesh', t:'view' }, { id:'crv', label:'curves', t:'walls' }] },
  h_blender:  { w:220, h:118, outs:[{ id:'mesh', label:'mesh', t:'view' }, { id:'sk', label:'sketch', t:'view' }] },
  h_speckle:  { w:240, h:140, ins:[{ id:'sheet', label:'sheet', t:'sheets' }, { id:'view', label:'model', t:'view' }], outs:[{ id:'commit', label:'commit', t:'trace' }] },
  h_dropbox:  { w:220, h:90, ins:[{ id:'file', label:'file', t:'file' }], outs:[{ id:'url', label:'url', t:'file' }] },
  h_outlook:  { w:220, h:90, outs:[{ id:'inbox', label:'inbox', t:'file' }] },
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
};

// ──────────────────────── SIDEBAR (icon rail + active panel) ────────────────────────
const Sidebar = ({ panel, setPanel, openId, onOpen, onHome, onSettings, onDocs, addNodeFromLibrary }) => (
  <aside style={{
    gridColumn:'1', gridRow:'1',
    display:'grid', gridTemplateColumns:'44px 1fr',
    background:LM.bgPanel, borderRight:`1px solid ${LM.line}`,
    overflow:'hidden', minHeight:0,
  }}>
    <IconRail panel={panel} setPanel={setPanel} onHome={onHome} onSettings={onSettings} onDocs={onDocs}/>
    {panel === 'chats'  && <ChatsPanel openId={openId} onOpen={onOpen}/>}
    {panel === 'nodes'  && <NodesPanel addNodeFromLibrary={addNodeFromLibrary}/>}
    {panel === 'skills' && <SkillsPanel/>}
    {panel === 'search' && <SearchPanel/>}
  </aside>
);

const IconRail = ({ panel, setPanel, onHome, onSettings, onDocs }) => {
  const items = [
    { id:'chats',  title:'Chats',  svg:<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M21 11.5a8.4 8.4 0 0 1-9 8.4l-5 2 2-4.6A8.4 8.4 0 1 1 21 11.5z"/></svg> },
    { id:'nodes',  title:'Nodes',  svg:<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg> },
    { id:'skills', title:'Skills', svg:<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><polygon points="12 2 15 8 22 9 17 14 18 21 12 17.7 6 21 7 14 2 9 9 8"/></svg> },
    { id:'search', title:'Search', svg:<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg> },
  ];
  return (
    <div style={{
      background:LM.bgDeep, borderRight:`1px solid ${LM.line}`,
      display:'flex', flexDirection:'column', alignItems:'center',
      padding:'10px 0 8px', gap:LM.sp.xs,
    }}>
      <RailIcon active onClick={onHome} title="Home">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
          <path d="M3 21 V12 a9 9 0 0 1 18 0 V21" stroke={LM.accent} strokeWidth="2" strokeLinecap="round"/>
          <circle cx="12" cy="8.5" r="1.5" fill={LM.accent}/>
        </svg>
      </RailIcon>
      <div style={{ height:6 }}/>
      {items.map(it => (
        <RailIcon key={it.id} active={panel === it.id} onClick={() => setPanel(it.id)} title={it.title}>
          {it.svg}
        </RailIcon>
      ))}
      <div style={{ flex:1 }}/>
      <RailIcon title="Share">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/></svg>
      </RailIcon>
      <RailIcon onClick={onDocs} title="Documentation · ⌘/">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M4 19.5V5a2 2 0 0 1 2-2h11a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H6.5A2.5 2.5 0 0 1 4 18.5v1z"/><path d="M8 7h6M8 11h6"/></svg>
      </RailIcon>
      <RailIcon onClick={onSettings} title="Settings">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.01a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.01a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </svg>
      </RailIcon>
    </div>
  );
};

const RailIcon = ({ active, onClick, title, children }) => (
  <button onClick={onClick} title={title} style={{
    width:30, height:30, padding:0, border:0, borderRadius:LM.rad.md,
    background: active ? LM.accentDim : 'transparent',
    color: active ? LM.accent : LM.inkSoft,
    cursor:'pointer', display:'grid', placeItems:'center', position:'relative',
  }}
  onMouseEnter={e => !active && (e.currentTarget.style.background = LM.bgSoft)}
  onMouseLeave={e => !active && (e.currentTarget.style.background = 'transparent')}>
    {active && <span style={{ position:'absolute', left:-7, top:6, bottom:6, width:2, background:LM.accent, borderRadius:2 }}/>}
    {children}
  </button>
);

const ChatsPanel = ({ openId, onOpen }) => (
  <div style={{ display:'flex', flexDirection:'column', overflow:'hidden', minHeight:0 }}>
    {/* Panel header */}
    <div style={{ padding:'12px 12px 10px', display:'flex', alignItems:'center', gap:LM.sp.sm }}>
      <span style={{ fontFamily:LM.sans, fontSize:14, fontWeight:600, letterSpacing:'-0.005em', color:LM.ink }}>Chats</span>
      <div style={{ flex:1 }}/>
      <button title="More" style={panelIconBtn()}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>
      </button>
      <button title="New chat" style={panelIconBtn()}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 1 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/></svg>
      </button>
    </div>

    {/* Search */}
    <div style={{ padding:'0 10px 8px' }}>
      <div style={{
        display:'flex', alignItems:'center', gap:LM.sp.sm, padding:'6px 10px',
        background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.md,
        color:LM.inkMuted, fontSize:12.5,
      }}>
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
        <span style={{ flex:1 }}>Search chats…</span>
      </div>
    </div>

    {/* Sessions list */}
    <div className="ah-scroll" style={{ flex:1, overflow:'auto', padding:'0 6px 8px', minHeight:0 }}>
      {LM_SESSIONS.map(s => {
        const a = openId === s.id;
        const sm = LM_STATE_META[s.state];
        return (
          <button key={s.id} onClick={() => onOpen(s.id)} style={{
            width:'100%', padding:'7px 9px', borderRadius:LM.rad.sm, border:0,
            background: a ? LM.bgSoft : 'transparent', color: a ? LM.ink : LM.inkSoft,
            cursor:'pointer', textAlign:'left', position:'relative',
            display:'flex', alignItems:'center', gap:LM.sp.sm,
            fontFamily:LM.sans, fontSize:13, marginBottom:1,
          }}
          onMouseEnter={e => !a && (e.currentTarget.style.background = LM.bgHover)}
          onMouseLeave={e => !a && (e.currentTarget.style.background = 'transparent')}>
            <span style={{
              width:6, height:6, borderRadius:'50%', background: sm.col, flexShrink:0,
              boxShadow: sm.pulse ? `0 0 0 2px ${sm.col}22` : 'none',
              animation: sm.pulse ? 'lmPulse 1.2s infinite' : 'none',
            }}/>
            <span style={{ flex:1, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', fontWeight: a ? 500 : 400 }}>{s.title}</span>
            {a && <span style={{ fontFamily:LM.sans, fontSize:14, color:LM.inkMuted, lineHeight:0.5 }}>···</span>}
          </button>
        );
      })}
    </div>

    {/* User */}
    <div style={{
      margin:LM.sp.sm, padding:'7px 10px', borderRadius:LM.rad.md,
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

const panelIconBtn = () => ({
  width:22, height:22, padding:0, border:0, background:'transparent',
  borderRadius:4, cursor:'pointer', color:LM.inkSoft,
  display:'grid', placeItems:'center',
});

// ─── Nodes panel — primary drag source ───
const NodesPanel = ({ addNodeFromLibrary }) => {
  const [q, setQ] = React.useState('');
  const [openCats, setOpenCats] = React.useState(() => Object.fromEntries(Object.keys(CAT).map(k => [k, true])));
  return (
    <div style={{ display:'flex', flexDirection:'column', overflow:'hidden', minHeight:0 }}>
      <div style={{ padding:'12px 12px 10px', display:'flex', alignItems:'center', gap:LM.sp.sm }}>
        <span style={{ fontFamily:LM.sans, fontSize:14, fontWeight:600, color:LM.ink }}>Nodes</span>
        <span style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.08em' }}>
          drag · or 2× click
        </span>
        <div style={{ flex:1 }}/>
        <button title="Collapse all" style={panelIconBtn()} onClick={() => setOpenCats({})}>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 12h14"/></svg>
        </button>
      </div>

      <div style={{ padding:'0 10px 8px' }}>
        <div style={{
          display:'flex', alignItems:'center', gap:LM.sp.sm, padding:'6px 10px',
          background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.md,
        }}>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke={LM.inkMuted} strokeWidth="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
          <input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="Search nodes…" style={{
            flex:1, border:0, background:'transparent', color:LM.ink, fontSize:12, outline:'none', fontFamily:LM.sans,
          }}/>
        </div>
      </div>

      <div className="ah-scroll" style={{ flex:1, overflow:'auto', padding:'0 6px 8px', minHeight:0 }}>
        {LM_LIBRARY.map(group => {
          const c = CAT[group.cat];
          const items = q ? group.items.filter(i => (i.title + ' ' + i.sub).toLowerCase().includes(q.toLowerCase())) : group.items;
          if (items.length === 0) return null;
          const open = q ? true : !!openCats[group.cat];
          return (
            <div key={group.cat} style={{ marginBottom:LM.sp.xs }}>
              <button onClick={() => setOpenCats(o => ({ ...o, [group.cat]: !o[group.cat] }))} style={{
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
                  {items.map(it => <NodeLibItem key={it.id} it={it} cat={c} onAdd={() => addNodeFromLibrary({ ...it, cat:group.cat })}/>)}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div style={{
        margin:LM.sp.sm, padding:'7px 10px', borderRadius:LM.rad.md,
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

const NodeLibItem = ({ it, cat, onAdd }) => {
  const [h, setH] = React.useState(false);
  const onDragStart = (e) => {
    e.dataTransfer.effectAllowed = 'copy';
    e.dataTransfer.setData('application/x-lm-node', JSON.stringify({ ...it, cat: cat.label.toLowerCase() }));
    e.dataTransfer.setData('text/plain', it.title);
  };
  return (
    <div
      draggable="true"
      onDragStart={onDragStart}
      onDoubleClick={onAdd}
      onMouseEnter={() => setH(true)}
      onMouseLeave={() => setH(false)}
      title="Drag onto canvas, or double-click to add"
      style={{
        display:'flex', alignItems:'center', gap:LM.sp.sm, padding:'5px 8px',
        borderRadius:4, cursor:'grab', userSelect:'none',
        background: h ? LM.bgHover : 'transparent',
        borderLeft:`2px solid ${h ? cat.col : 'transparent'}`,
        transition:'background .1s, border-color .1s',
      }}>
      <span style={{ width:5, height:5, borderRadius:'50%', background:cat.col, flexShrink:0, opacity:0.8 }}/>
      <div style={{ flex:1, minWidth:0, lineHeight:1.2 }}>
        <div style={{ fontFamily:LM.mono, fontSize:11, color:LM.ink, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{it.title}</div>
        <div style={{ fontFamily:LM.sans, fontSize:10, color:LM.inkMuted, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{it.sub}</div>
      </div>
      {h && (
        <span style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.04em', flexShrink:0 }}>+</span>
      )}
    </div>
  );
};

// ─── Skills panel — saved templates the user has accrued ───
const LM_SAVED_SKILLS = (window.ARCHHUB_LIVE?.skills) || [];
const _SEED_SKILLS = [
  { id:'dim_walls',   name:'Dimension walls in active view',  runs:14, args:'scale, min_length', when:'2 days ago' },
  { id:'door_qa',     name:'Door schedule QA',                runs:38, args:'level',             when:'today' },
  { id:'mass_extract',name:'Sketch \u2192 mass',              runs:6,  args:'floor_count, height',when:'last week' },
  { id:'pdf_set',     name:'Publish sheet set to Dropbox',    runs:21, args:'sheets, destination',when:'today' },
  { id:'panel_study', name:'Facade panel variations',         runs:3,  args:'count, seed',       when:'2 weeks ago' },
  { id:'morning',     name:'Morning Outlook triage',          runs:42, args:'\u2014',             when:'daily' },
];

const SkillsPanel = () => (
  <div style={{ display:'flex', flexDirection:'column', overflow:'hidden', minHeight:0 }}>
    <div style={{ padding:'12px 12px 10px', display:'flex', alignItems:'center', gap:LM.sp.sm }}>
      <span style={{ fontFamily:LM.sans, fontSize:14, fontWeight:600, color:LM.ink }}>Skills</span>
      <span style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.08em' }}>{LM_SAVED_SKILLS.length} SAVED</span>
      <div style={{ flex:1 }}/>
      <button title="New skill" style={panelIconBtn()}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 5v14M5 12h14"/></svg>
      </button>
    </div>
    <div style={{ padding:'0 10px 8px' }}>
      <div style={{
        display:'flex', alignItems:'center', gap:LM.sp.sm, padding:'6px 10px',
        background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.md, color:LM.inkMuted, fontSize:12,
      }}>
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
        <span style={{ flex:1 }}>Search saved skills…</span>
      </div>
    </div>
    <div className="ah-scroll" style={{ flex:1, overflow:'auto', padding:'0 6px 8px' }}>
      {LM_SAVED_SKILLS.map(s => (
        <div key={s.id} draggable="true" style={{
          padding:'7px 9px', borderRadius:LM.rad.sm, cursor:'grab', marginBottom:1,
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
    </div>
  </div>
);

// ─── Global search panel ───
const SearchPanel = () => (
  <div style={{ display:'flex', flexDirection:'column', overflow:'hidden', minHeight:0 }}>
    <div style={{ padding:'12px 12px 10px', display:'flex', alignItems:'center', gap:LM.sp.sm }}>
      <span style={{ fontFamily:LM.sans, fontSize:14, fontWeight:600, color:LM.ink }}>Search</span>
      <div style={{ flex:1 }}/>
      <kbd style={kbd()}>⌘K</kbd>
    </div>
    <div style={{ padding:'0 10px 10px' }}>
      <div style={{
        display:'flex', alignItems:'center', gap:LM.sp.sm, padding:'8px 12px',
        background:LM.bg, border:`1px solid ${LM.accent}55`, borderRadius:LM.rad.md,
        boxShadow:`0 0 0 3px ${LM.accentDim}`,
      }}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke={LM.accent} strokeWidth="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
        <span style={{ flex:1, color:LM.inkMuted, fontStyle:'italic', fontFamily:LM.serif, fontSize:13 }}>
          everything in studio…
        </span>
      </div>
    </div>
    <div style={{ padding:'4px 10px', fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.14em' }}>SCOPES</div>
    <div style={{ padding:'0 6px', display:'flex', flexDirection:'column', gap:1 }}>
      {[
        ['chats',  'sessions + messages',  14],
        ['nodes',  'in current graph',      11],
        ['skills', 'saved templates',       6],
        ['memory', 'what Claude remembers', 8],
        ['files',  'Revit / Rhino / Speckle', 47],
        ['hosts',  'connectors',            6],
      ].map(([k, sub, n]) => (
        <button key={k} style={{
          padding:'6px 10px', borderRadius:LM.rad.sm, background:'transparent', border:0,
          cursor:'pointer', textAlign:'left',
          display:'flex', alignItems:'center', gap:LM.sp.sm,
        }}
        onMouseEnter={e => e.currentTarget.style.background = LM.bgHover}
        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
          <span style={{ fontFamily:LM.mono, fontSize:11, color:LM.ink, width:54 }}>{k}</span>
          <span style={{ flex:1, fontSize:11, color:LM.inkSoft }}>{sub}</span>
          <span style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted }}>{n}</span>
        </button>
      ))}
    </div>
  </div>
);

const kbd = () => ({
  fontFamily:LM.mono, fontSize:9, padding:'1px 5px', background:LM.bgSoft,
  border:`1px solid ${LM.lineHair}`, borderRadius:LM.rad.xs, color:LM.inkMuted, letterSpacing:'0.06em',
});

// ──────────────────────── HOME ────────────────────────
const Home = ({ onOpen, model, setPickerOpen }) => {
  const [filter, onFilter] = React.useState('all');
  const shown = filter === 'all'
    ? LM_SESSIONS
    : LM_SESSIONS.filter(s => (s.state || 'idle') === filter);
  return (
  <main className="ah-scroll" style={{
    gridColumn:'2', gridRow:'1', overflow:'auto', minHeight:0,
    padding:'30px 44px 36px', display:'flex', flexDirection:'column',
  }}>
    <ModelStrip model={model} setPickerOpen={setPickerOpen}/>
    <div style={{
      background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:LM.rad.xl,
      padding:'16px 18px', marginBottom:36, marginTop:14,
    }}>
      <div style={{ display:'flex', alignItems:'flex-end', gap:14 }}>
        <div style={{ flex:1, minWidth:0 }}>
          <div style={{ fontFamily:LM.serif, fontSize:24, fontStyle:'italic', color:LM.inkSoft, letterSpacing:'-0.01em', padding:'2px 0' }}>
            Start a new session…
          </div>
          <div style={{ display:'flex', alignItems:'center', gap:6, marginTop:10 }}>
            <Chip mono>/ node</Chip>
            <Chip mono>@ skill</Chip>
            <Chip mono>#  host</Chip>
            <Chip>+ attach</Chip>
          </div>
        </div>
        <button style={{
          padding:'9px 16px 9px 14px', background:LM.accent, color: (window.AH && window.AH.onFill) || '#180f08',
          border:0, borderRadius:7, fontFamily:LM.sans, fontSize:13, fontWeight:500,
          cursor:'pointer', display:'inline-flex', alignItems:'center', gap:7,
        }}>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke={(window.AH && window.AH.onFill) || "#180f08"} strokeWidth="2.5"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
          Send
        </button>
      </div>
    </div>
    <div style={{ display:'flex', alignItems:'baseline', gap:10, marginBottom:14 }}>
      <h2 style={{ fontFamily:LM.serif, fontSize:26, fontWeight:400, letterSpacing:'-0.015em', margin:0 }}>Sessions</h2>
      <span style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.14em' }}>
        {shown.length} · CLICK TO OPEN
      </span>
      <div style={{ flex:1 }}/>
      {['all', 'running', 'idle'].map(kind => (
        <button key={kind} onClick={() => onFilter && onFilter(kind)}
          style={chipBtn(filter === kind)}>{kind}</button>
      ))}
    </div>
    <div style={{ display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:LM.sp.md }}>
      {shown.length === 0 ? (
        <div style={{ fontFamily:LM.mono, fontSize:11, color:LM.inkMuted }}>no {filter} session on this machine</div>
      ) : shown.map(s => <SessionCard key={s.id} s={s} onOpen={() => onOpen(s.id)}/>)}
    </div>
  </main>
  );
};

const chipBtn = (active) => ({
  padding:'4px 11px', borderRadius:999,
  background: active ? LM.ink : 'transparent',
  border:`1px solid ${active ? LM.ink : LM.line}`,
  color: active ? LM.bg : LM.inkSoft, fontFamily:LM.mono, fontSize:10,
  letterSpacing:'0.06em', cursor:'pointer',
});

const Chip = ({ children, mono }) => (
  <span style={{
    display:'inline-flex', alignItems:'center', gap:5, padding:'3px 9px',
    background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.sm,
    color:LM.inkSoft, fontFamily: mono ? LM.mono : LM.sans, fontSize: mono ? 10.5 : 11.5,
    letterSpacing: mono ? '0.04em' : 'normal', cursor:'pointer',
  }}>{children}</span>
);

const SessionCard = ({ s, onOpen }) => {
  const sm = LM_STATE_META[s.state];
  const hosts = (Array.isArray(s.host) ? s.host : [s.host]).map(h => LM_HOST_META[h] || { name:h, col:LM.inkSoft });
  return (
    <button onClick={onOpen} style={{
      background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:9,
      padding:'14px 16px', display:'flex', flexDirection:'column', gap:11,
      cursor:'pointer', textAlign:'left', color:LM.ink, fontFamily:LM.sans,
      transition:'border-color .12s, transform .12s',
    }}
    onMouseEnter={e => { e.currentTarget.style.borderColor = LM.accent+'66'; e.currentTarget.style.transform='translateY(-1px)'; }}
    onMouseLeave={e => { e.currentTarget.style.borderColor = LM.line; e.currentTarget.style.transform='none'; }}>
      <div style={{ display:'flex', alignItems:'center', gap:7 }}>
        <span style={{ width:6, height:6, borderRadius:'50%', background: sm.col, boxShadow: sm.pulse ? `0 0 0 2px ${sm.col}22` : 'none', animation: sm.pulse ? 'lmPulse 1.2s infinite' : 'none' }}/>
        <span style={{ fontFamily:LM.mono, fontSize:9.5, color:sm.col, letterSpacing:'0.12em', textTransform:'uppercase' }}>{sm.label}</span>
        <div style={{ flex:1 }}/>
        <span style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.04em' }}>{s.when}</span>
      </div>
      <div style={{ fontFamily:LM.serif, fontSize:22, letterSpacing:'-0.015em', lineHeight:1.1 }}>{s.title}</div>
      <div style={{ fontSize:12.5, color:LM.inkSoft, lineHeight:1.5, minHeight:36 }}>{s.last}</div>
      <div style={{
        display:'flex', alignItems:'center', gap:7, paddingTop:9,
        borderTop:`1px solid ${LM.lineSoft}`, fontFamily:LM.mono, fontSize:10,
        color:LM.inkMuted, letterSpacing:'0.04em',
      }}>
        <span style={{ flex:1, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{s.file}</span>
        {hosts.map(h => (
          <span key={h.name} style={{ padding:'1px 6px', borderRadius:LM.rad.xs, fontSize:9.5, background: h.col + '14', color: h.col, letterSpacing:'0.06em' }}>{h.name}</span>
        ))}
      </div>
    </button>
  );
};

// ──────────────────────── WORKSPACE ────────────────────────
const Workspace = ({ session, model, openTabs, setOpenId, closeTab, setPickerOpen, setSettingsOpen, setLibraryOpen, focusId, setFocusId, userNodes, addNodeFromLibrary, onHome }) => {
  const allNodes = [...LM_GRAPH.nodes, ...(userNodes || [])];
  // A wire is a node: focusId may name one, and the SAME rail renders it.
  const wireIdx = String(focusId).indexOf('wire:') === 0 ? +String(focusId).slice(5) : -1;
  const focusNode = wireIdx >= 0
    ? window.wireAsNode(LM_GRAPH.wires[wireIdx], wireIdx, allNodes)
    : allNodes.find(n => n.id === focusId);
  const [mode, setMode] = React.useState('chat');   // chat (calm, default) | canvas (node graph)
  return (
    <main style={{
      gridColumn:'2', gridRow:'1', minHeight:0, overflow:'hidden',
      display:'grid',
      gridTemplateColumns:'1fr 320px',
      gridTemplateRows:'36px 1fr',
    }}>
      <WsHeader
        session={session} model={model} openTabs={openTabs}
        setOpenId={setOpenId} closeTab={closeTab} mode={mode} setMode={setMode}
        setPickerOpen={setPickerOpen} setSettingsOpen={setSettingsOpen} onHome={onHome}/>
      {mode === 'chat' ? (
        <>
          <ChatView session={session} model={model} setMode={setMode}/>
          <InferenceInspector model={model} setPickerOpen={setPickerOpen}/>
        </>
      ) : (
        <>
          <NodeCanvas focusId={focusId} setFocusId={setFocusId} setLibraryOpen={setLibraryOpen} userNodes={userNodes} addNodeFromLibrary={addNodeFromLibrary}/>
          <NodeRail node={focusNode}/>
        </>
      )}
    </main>
  );
};

// ─── Calm chat view (default) — restores original Studio's generous rhythm ───
const ChatView = ({ session, model, setMode }) => {
  const conv = LM_GRAPH.nodes.find(n => n.cat === 'ai')
    || LM_GRAPH.nodes.find(n => n.id === 'ai_intent');
  const [messages, setMessages] = React.useState((conv && conv.messages) || []);
  const [draft, setDraft] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const stamp = () => new Date().toTimeString().slice(0, 5);
  const send = async () => {
    const text = draft.trim();
    if (!text || busy || !window.ARCHHUB_AGENT) return;
    setMessages(m => [...m, { me:true, time:stamp(), text }]);
    setDraft('');
    setBusy(true);
    try {
      const answer = await window.ARCHHUB_AGENT(text, model?.route);
      setMessages(m => [...m, { me:false, time:stamp(), text:answer }]);
    } catch (error) {
      setMessages(m => [...m, { me:false, time:stamp(),
        text:'refused: ' + (error?.message || error) }]);
    } finally { setBusy(false); }
  };
  return (
    <section style={{
      gridColumn:'1', gridRow:'2', minHeight:0, display:'flex', flexDirection:'column',
      background:LM.bg, overflow:'hidden',
    }}>
      <div className="ah-scroll" style={{ flex:1, overflow:'auto', padding:'24px 0 12px' }}>
        <div style={{ maxWidth:720, margin:'0 auto', padding:'0 36px' }}>
          {/* System prompt card — always anchored at top */}
          <div style={{
            background:LM.bgPanel, border:`1px solid ${LM.line}`, borderLeft:`3px solid ${LM.cyan}`,
            borderRadius:LM.rad.lg, padding:'12px 16px', marginBottom:26,
          }}>
            <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:6 }}>
              <span style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.cyan, letterSpacing:'0.14em' }}>SYSTEM PROMPT</span>
              <div style={{ flex:1 }}/>
              <span style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted }}>312 tok</span>
              <span style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.accent, cursor:'pointer' }}>edit</span>
            </div>
            <div style={{ fontFamily:LM.serif, fontStyle:'italic', fontSize:15, lineHeight:1.55, color:LM.inkSoft, letterSpacing:'-0.005em' }}>
              You are ArchHub running in Revit 2025. The active file is {session.file}. Be terse and technical. Never write code without asking — use the connector tools. Units: millimeters.
            </div>
          </div>

          {/* Conversation — calm, generous, serif for Claude */}
          {messages.map((m, i) => (
            <div key={i} style={{ display:'flex', gap:14, marginBottom:24 }}>
              <div style={{
                width:30, height:30, borderRadius: m.me ? '50%' : LM.rad.md, flexShrink:0,
                background: m.me ? '#d8c5a8' : LM.accent,
                display:'grid', placeItems:'center',
                color: m.me ? '#5a4a2a' : ((window.AH && window.AH.onFill) || '#180f08'), fontFamily:LM.sans, fontSize:13, fontWeight:700,
              }}>{m.me ? 'F' : 'C'}</div>
              <div style={{ flex:1, minWidth:0 }}>
                <div style={{ display:'flex', alignItems:'baseline', gap:8, marginBottom:4 }}>
                  <span style={{ fontSize:13, fontWeight:500, color:LM.ink }}>{m.me ? 'Fargaly' : model.name}</span>
                  <span style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, letterSpacing:'0.04em' }}>{m.time}</span>
                </div>
                <div style={{
                  fontSize: m.me ? 14 : 15,
                  fontFamily: m.me ? LM.sans : LM.serif,
                  fontStyle: m.me ? 'normal' : 'normal',
                  lineHeight:1.6, color: m.me ? LM.ink : LM.ink, letterSpacing: m.me ? '0' : '-0.003em',
                }}>{m.text}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Composer — calm, centered */}
      <div style={{ padding:'12px 0 18px', borderTop:`1px solid ${LM.lineSoft}` }}>
        <div style={{ maxWidth:720, margin:'0 auto', padding:'0 36px' }}>
          <div style={{ background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg, padding:'12px 14px' }}>
            <input value={draft} onChange={e => setDraft(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') send(); }}
              placeholder={busy ? 'thinking…' : 'Reply, or ask for another step…'}
              disabled={busy}
              style={{ width:'100%', background:'transparent', border:0, outline:0,
                fontFamily:LM.serif, fontStyle:'italic', fontSize:17, color:LM.ink,
                padding:'2px 0 8px', letterSpacing:'-0.01em' }}/>
            <div style={{ display:'flex', alignItems:'center', gap:6 }}>
              <Chip mono>@ skill</Chip>
              <Chip>＋ sketch</Chip>
              <button onClick={() => setMode('canvas')} style={{
                display:'inline-flex', alignItems:'center', gap:5, padding:'3px 9px',
                background:'transparent', border:`1px solid ${LM.line}`, borderRadius:LM.rad.sm,
                color:LM.inkSoft, fontFamily:LM.mono, fontSize:10.5, letterSpacing:'0.04em', cursor:'pointer',
              }}>⌗ open as nodes</button>
              <div style={{ flex:1 }}/>
              <span style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted }}>{model.name.split(' ').slice(0,2).join(' ')} · ~{model.latency}ms</span>
              <button onClick={send} disabled={busy} style={{ padding:'7px 14px', background:LM.accent, color: (window.AH && window.AH.onFill) || '#180f08', border:0, borderRadius:LM.rad.sm, fontSize:12.5, fontWeight:500, cursor:'pointer', opacity: busy ? 0.6 : 1 }}>Send ↵</button>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};

// ─── Calm inference inspector (chat mode right rail) ───
// The parametric chain, LIVE: the wired pipeline from the graph in
// topological stages, each stage's real editable parameters. Nothing is
// authored -- an empty canvas shows an empty chain, honestly.
const LiveChain = () => {
  const graph = window.ARCHHUB_LIVE?.graph;
  if (!graph || !graph.nodes.length) return null;
  const wired = new Set(graph.wires.flatMap(w => [w.from[0], w.to[0]]));
  const incoming = {};
  graph.wires.forEach(w => { incoming[w.to[0]] = (incoming[w.to[0]] || 0) + 1; });
  const stages = [];
  let frontier = graph.nodes.filter(n => wired.has(n.id) && !incoming[n.id]);
  const seen = new Set();
  while (frontier.length && stages.length < 8) {
    stages.push(frontier);
    frontier.forEach(n => seen.add(n.id));
    const next = new Set();
    graph.wires.forEach(w => {
      if (seen.has(w.from[0]) && !seen.has(w.to[0])) next.add(w.to[0]);
    });
    frontier = graph.nodes.filter(n => next.has(n.id));
  }
  if (!stages.length) return null;
  return (
    <div style={{ padding:'14px 16px', borderBottom:`1px solid ${LM.lineSoft}` }}>
      <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.14em', marginBottom:10 }}>PARAMETRIC CHAIN · {stages.length} STAGE{stages.length === 1 ? '' : 'S'}</div>
      <div style={{ display:'flex', alignItems:'center', gap:0, marginBottom:10 }}>
        {stages.map((_, i) => (
          <React.Fragment key={i}>
            <div style={{ width:18, height:18, borderRadius:'50%', border:`2px solid ${LM.accent}`, background:LM.bg, color:LM.accent, display:'grid', placeItems:'center', fontFamily:LM.mono, fontSize:9, fontWeight:600 }}>{i + 1}</div>
            {i < stages.length - 1 && <div style={{ flex:1, height:2, background:LM.accent }}/>}
          </React.Fragment>
        ))}
      </div>
      {stages.map((nodes, i) => nodes.map(n => (
        <div key={n.id} style={{ marginBottom:8 }}>
          <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkSoft, letterSpacing:'0.05em', marginBottom:4 }}>{i + 1} · {n.title}</div>
          {(n.params || []).slice(0, 2).map(p => (
            <div key={p.k} style={{ display:'flex', gap:6, fontFamily:LM.mono, fontSize:10, padding:'2px 0' }}>
              <span style={{ color:LM.inkMuted }}>{p.k}</span>
              <div style={{ flex:1, borderBottom:`1px dashed ${LM.lineSoft}`, marginBottom:3 }}/>
              <span style={{ color:LM.ink, maxWidth:120, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{String(p.v)}</span>
            </div>
          ))}
        </div>
      )))}
    </div>
  );
};

const InferenceInspector = ({ model, setPickerOpen }) => (
  <aside style={{
    gridColumn:'2', gridRow:'2', minHeight:0, overflow:'auto',
    background:LM.bgPanel, borderLeft:`1px solid ${LM.line}`,
  }} className="ah-scroll">
    {/* model */}
    <div style={{ padding:'14px 16px', borderBottom:`1px solid ${LM.lineSoft}` }}>
      <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.14em', marginBottom:8 }}>MODEL</div>
      <button onClick={() => setPickerOpen(true)} style={{
        width:'100%', display:'flex', alignItems:'center', gap:10, padding:'8px 10px',
        background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.md, cursor:'pointer', color:LM.ink,
      }}>
        <span style={{ width:22, height:22, borderRadius:LM.rad.sm, background:model.col, color:((window.AH && window.AH.onFill) || '#180f08'), display:'grid', placeItems:'center', fontFamily:LM.mono, fontSize:11, fontWeight:700 }}>{model.name[0]}</span>
        <div style={{ flex:1, textAlign:'left', lineHeight:1.15 }}>
          <div style={{ fontSize:13, fontWeight:500 }}>{model.name}</div>
          <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted }}>{model.vendor} · ctx {model.ctx}</div>
        </div>
        <span style={{ color:LM.inkSoft, fontSize:11 }}>▾</span>
      </button>
    </div>

    {/* generation params */}
    <div style={{ padding:'14px 16px', borderBottom:`1px solid ${LM.lineSoft}` }}>
      <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.14em', marginBottom:10 }}>GENERATION</div>
      <CalmSlider k="temperature" v={0.7} min={0} max={2} step={0.05}/>
      <CalmSlider k="top-p" v={0.95} min={0} max={1} step={0.01}/>
      <CalmSlider k="max tokens" v={4096} min={256} max={32000} step={256} int/>
    </div>

    {/* parametric chain -- the LIVE wired pipeline, stage by stage */}
    <LiveChain/>

    {/* connectors -- exactly what answered a probe, nothing invented */}
    <div style={{ padding:'14px 16px' }}>
      <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.14em', marginBottom:10 }}>CONNECTORS · {(window.ARCHHUB_LIVE?.connectors || []).length}</div>
      {(window.ARCHHUB_LIVE?.connectors || []).map(c => {
        const col = c.state === 'connected' || c.state === 'listening' ? LM.ok
          : c.state === 'installed' ? LM.warn : LM.inkDim;
        return (
          <div key={c.id} title={c.detail} style={{ display:'flex', alignItems:'center', gap:8, padding:'5px 0', borderBottom:`1px dashed ${LM.lineSoft}` }}>
            <span style={{ width:7, height:7, borderRadius:'50%', background:col, boxShadow:`0 0 0 3px ${col}22` }}/>
            <span style={{ flex:1, fontSize:12.5, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{c.name}</span>
            <span style={{ fontFamily:LM.mono, fontSize:9.5, color:col, letterSpacing:'0.06em', textTransform:'uppercase' }}>{c.state}</span>
          </div>
        );
      })}
    </div>
  </aside>
);

const CalmSlider = ({ k, v, min, max, step, int, unit }) => (
  <div style={{ marginBottom:9 }}>
    <div style={{ display:'flex', alignItems:'baseline', gap:6 }}>
      <span style={{ fontFamily:LM.mono, fontSize:10.5, color:LM.inkSoft, flex:1 }}>{k}</span>
      <span style={{ fontFamily:LM.mono, fontSize:11.5, color:LM.ink, fontWeight:500 }}>{int ? v : v.toFixed(2)}{unit && <span style={{ color:LM.inkMuted, marginLeft:2, fontSize:10 }}> {unit}</span>}</span>
    </div>
    <input type="range" defaultValue={v} min={min} max={max} step={step} style={{ width:'100%', accentColor:LM.accent, marginTop:3 }}/>
  </div>
);
const CalmRow = ({ k, v }) => (
  <div style={{ display:'flex', alignItems:'center', gap:8, padding:'3px 0' }}>
    <span style={{ fontFamily:LM.mono, fontSize:10.5, color:LM.inkSoft, flex:1 }}>{k}</span>
    <span style={{ fontFamily:LM.mono, fontSize:11.5, color:LM.ink }}>{v}</span>
  </div>
);

// Workspace header is now SESSION TABS (browser-style) + right-side actions.
const WsHeader = ({ session, model, openTabs, setOpenId, closeTab, mode, setMode, setPickerOpen, setSettingsOpen, onHome }) => (
  <div style={{
    gridColumn:'1 / -1', gridRow:'1',
    borderBottom:`1px solid ${LM.line}`, background:LM.bgDeep,
    padding:'0 10px 0 6px', display:'flex', alignItems:'center', gap:6, minWidth:0,
  }}>
    <button onClick={onHome} title="All sessions" style={{
      width:26, height:26, padding:0, border:0, borderRadius:LM.rad.sm,
      background:'transparent', color:LM.inkMuted, cursor:'pointer',
      display:'grid', placeItems:'center', flexShrink:0,
    }}
    onMouseEnter={e => e.currentTarget.style.background = LM.bgSoft}
    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
    </button>

    <div style={{ flex:1, minWidth:0, display:'flex', alignItems:'center', gap:2, overflow:'hidden' }}>
      {openTabs.map(id => {
        const s = LM_SESSIONS.find(x => x.id === id);
        if (!s) return null;
        const a = session.id === id;
        const sm = LM_STATE_META[s.state];
        return <WsTab key={id} s={s} a={a} sm={sm} onClick={() => setOpenId(id)} onClose={(e) => { e.stopPropagation(); closeTab(id); }}/>;
      })}
      <button title="New session" style={{
        width:26, height:26, padding:0, border:0, borderRadius:LM.rad.sm,
        background:'transparent', color:LM.inkMuted, cursor:'pointer', flexShrink:0,
        display:'grid', placeItems:'center', fontSize:14,
      }}
      onMouseEnter={e => e.currentTarget.style.background = LM.bgSoft}
      onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>+</button>
    </div>

    <div style={{
      display:'flex', alignItems:'center', gap:1, padding:2, background:LM.bg,
      border:`1px solid ${LM.line}`, borderRadius:LM.rad.md, flexShrink:0,
    }}>
      {[['chat','Chat'],['canvas','Canvas']].map(([k,l]) => (
        <button key={k} onClick={() => setMode(k)} style={{
          padding:'4px 11px', borderRadius:LM.rad.sm, border:0, cursor:'pointer',
          background: mode===k ? LM.accentDim : 'transparent',
          color: mode===k ? LM.accent : LM.inkSoft,
          fontFamily:LM.sans, fontSize:11.5, fontWeight: mode===k ? 500 : 400,
        }}>{l}</button>
      ))}
    </div>

    <ModelStrip model={model} setPickerOpen={setPickerOpen} compact/>
    <HoverBtn>fork</HoverBtn>
    <HoverBtn primary>save as skill</HoverBtn>
  </div>
);

const WsTab = ({ s, a, sm, onClick, onClose }) => {
  const [h, setH] = React.useState(false);
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setH(true)}
      onMouseLeave={() => setH(false)}
      style={{
        display:'flex', alignItems:'center', gap:7,
        padding:'0 8px 0 9px', height:28, borderRadius:LM.rad.sm,
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
      <span style={{
        fontFamily:LM.sans, fontSize:12, color: a ? LM.ink : LM.inkSoft,
        fontWeight: a ? 500 : 400,
        maxWidth:160, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap',
      }}>{s.title}</span>
      <button onClick={onClose} title="Close tab" style={{
        width:14, height:14, padding:0, border:0, borderRadius:LM.rad.xs,
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
  padding:'5px 11px', borderRadius:LM.rad.sm, fontFamily:LM.sans, fontSize:11.5,
  border:`1px solid ${primary ? LM.accent : LM.line}`,
  background: primary ? LM.accent : 'transparent',
  color: primary ? ((window.AH && window.AH.onFill) || '#180f08') : LM.inkSoft, cursor:'pointer', fontWeight: primary ? 500 : 400,
  transition:'filter .12s, background .12s, border-color .12s',
});

// Hoverable button wrappers (cards style — actually responsive)
const HoverBtn = ({ primary, onClick, children, style }) => {
  const [h, setH] = React.useState(false);
  return (
    <button
      onClick={onClick}
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
      width: compact ? 22 : 28, height: compact ? 22 : 28, borderRadius:LM.rad.sm,
      background: model.col, color:((window.AH && window.AH.onFill) || '#180f08'), display:'grid', placeItems:'center',
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
const SOCKET_STEP = 19;
const SOCKET_R = 5;

const socketY = (i) => SOCKET_TOP + i * SOCKET_STEP;

const NodeCanvas = ({ focusId, setFocusId, setLibraryOpen, userNodes = [], addNodeFromLibrary }) => {
  const allNodes = React.useMemo(() => [...LM_GRAPH.nodes, ...userNodes], [userNodes]);

  // Persistent positions per node — initialized from node.x/y, then mutable via drag.
  const [positions, setPositions] = React.useState(() =>
    Object.fromEntries(allNodes.map(n => [n.id, { x: n.x, y: n.y }]))
  );
  // Add positions for newly-added user nodes
  React.useEffect(() => {
    setPositions(p => {
      const next = { ...p };
      let changed = false;
      allNodes.forEach(n => { if (!next[n.id]) { next[n.id] = { x: n.x, y: n.y }; changed = true; } });
      return changed ? next : p;
    });
  }, [allNodes]);

  const [pan, setPan] = React.useState({ x: 14, y: 12 });
  const [zoom, setZoom] = React.useState(0.66);
  const [ctxMenu, setCtxMenu] = React.useState(null);
  const [expanded, setExpanded] = React.useState({});
  const [dropTarget, setDropTarget] = React.useState(null); // {x,y} canvas-local
  const dragRef = React.useRef(null);
  const wrapRef = React.useRef(null);

  // Convert client coords → canvas coords (the world space the nodes live in)
  const toCanvasCoords = (clientX, clientY) => {
    const rect = wrapRef.current.getBoundingClientRect();
    return {
      x: (clientX - rect.left - pan.x) / zoom,
      y: (clientY - rect.top  - pan.y) / zoom,
    };
  };

  const onCanvasMouseDown = (e) => {
    if (e.button !== 0) return;
    if (e.target.closest('[data-no-pan]')) return;
    if (e.target.closest('.lm-node')) return;
    setCtxMenu(null);
    dragRef.current = { mode:'pan', sx:e.clientX, sy:e.clientY, px:pan.x, py:pan.y };
  };

  const onContextMenu = (e) => {
    if (e.target.closest('.lm-node') || e.target.closest('[data-no-pan]')) return;
    e.preventDefault();
    const rect = wrapRef.current.getBoundingClientRect();
    // Clamp so the menu never spills past the canvas edges (menu ≈ 220×350).
    const MENU_W = 220, MENU_H = 350;
    const rx = e.clientX - rect.left, ry = e.clientY - rect.top;
    setCtxMenu({
      x: Math.max(8, Math.min(rx, rect.width  - MENU_W - 8)),
      y: Math.max(8, Math.min(ry, rect.height - MENU_H - 8)),
    });
  };

  const onNodeDragStart = (id) => (e) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    e.preventDefault();
    dragRef.current = { mode:'node', id, sx:e.clientX, sy:e.clientY, nx:positions[id].x, ny:positions[id].y };
    setFocusId(id);
  };

  React.useEffect(() => {
    const onMove = (e) => {
      const d = dragRef.current;
      if (!d) return;
      const dx = e.clientX - d.sx;
      const dy = e.clientY - d.sy;
      if (d.mode === 'pan') {
        setPan({ x: d.px + dx, y: d.py + dy });
      } else {
        setPositions(p => ({ ...p, [d.id]: { x: d.nx + dx / zoom, y: d.ny + dy / zoom } }));
      }
    };
    const onUp = () => { dragRef.current = null; };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    return () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };
  }, [zoom]);

  const onWheel = (e) => {
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
    allNodes.map(n => [n.id, { ...n, x: positions[n.id]?.x ?? n.x, y: positions[n.id]?.y ?? n.y }])
  );

  const focusWireIdx = String(focusId).indexOf('wire:') === 0 ? +String(focusId).slice(5) : -1;
  const connectedIds = new Set([focusId]);
  LM_GRAPH.wires.forEach(w => {
    if (w.from[0] === focusId) connectedIds.add(w.to[0]);
    if (w.to[0]   === focusId) connectedIds.add(w.from[0]);
  });

  const wires = LM_GRAPH.wires.map((w, i) => {
    const fromNode = nodeById[w.from[0]];
    const toNode   = nodeById[w.to[0]];
    if (!fromNode || !toNode) return null;
    const fromIdx  = fromNode.outs.findIndex(o => o.id === w.from[1]);
    const toIdx    = toNode.ins.findIndex(o => o.id === w.to[1]);
    if (fromIdx < 0 || toIdx < 0) return null;
    const x1 = fromNode.x + fromNode.w, y1 = fromNode.y + socketY(fromIdx);
    const x2 = toNode.x,                y2 = toNode.y + socketY(toIdx);
    const touches = w.from[0] === focusId || w.to[0] === focusId || i === focusWireIdx;
    return {
      i, x1, y1, x2, y2, selected: i === focusWireIdx,
      t: fromNode.outs[fromIdx].t,
      animated: fromNode.state === 'running' || toNode.state === 'running',
      focused: touches,
    };
  }).filter(Boolean);

  const toggleExpanded = (id) => setExpanded(e => ({ ...e, [id]: !e[id] }));
  const onResetView = () => { setPan({ x:14, y:12 }); setZoom(0.66); setCtxMenu(null); };

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
        <svg width="2400" height="1400" style={{ position:'absolute', left:0, top:0, pointerEvents:'none', overflow:'visible' }} className="lm-wires">
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
            const strokeW = w.selected ? 3.2 : w.focused ? 2.4 : 1.4;
            const op = w.focused ? 1 : 0.5;
            return (
              <g key={w.i}>
                <path d={d} stroke="transparent" strokeWidth={14} fill="none"
                  onClick={(e) => { e.stopPropagation(); setFocusId('wire:' + w.i); }}
                  style={{ pointerEvents: 'stroke', cursor: 'pointer' }}>
                  <title>Open this connection</title>
                </path>
                {w.selected && <path d={d} stroke={LM.accent} strokeWidth={strokeW + 5} fill="none" opacity={0.22} strokeLinecap="round"/>}
                <path d={d} stroke={w.selected ? LM.accent : color} strokeWidth={strokeW} fill="none" opacity={op} filter={w.focused ? "url(#lm-wire-glow)" : undefined} style={{ pointerEvents: 'none' }}/>
                {w.animated && (
                  <path d={d} stroke={color} strokeWidth={strokeW} fill="none" strokeDasharray="6 10" style={{ animation:'lmDash 0.9s linear infinite' }}/>
                )}
              </g>
            );
          })}
        </svg>

        {allNodes.map(n => {
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
          borderRadius:LM.rad.md, display:'grid', placeItems:'center',
          fontFamily:LM.mono, fontSize:10.5, color:LM.accent, letterSpacing:'0.06em',
        }}>＋ DROP TO ADD NODE</div>
      )}

      <CanvasToolbar zoom={zoom} setZoom={(updater) => {
        setZoom(z => {
          const next = typeof updater === 'function' ? updater(z) : updater;
          return Math.max(0.3, Math.min(2, next));
        });
      }} onFit={onResetView} setLibraryOpen={setLibraryOpen}/>
      <FloatingComposer setLibraryOpen={setLibraryOpen}/>
      <MiniMap pan={pan} zoom={zoom} positions={positions} allNodes={allNodes}/>
      {ctxMenu && <CanvasMenu x={ctxMenu.x} y={ctxMenu.y} onAddNode={() => { setLibraryOpen(true); setCtxMenu(null); }} onFit={onResetView} onClose={() => setCtxMenu(null)}/>}
      <CanvasHint/>
    </div>
  );
};

// Top-left hint strip (under the toolbar) — reminds the user of the canvas affordances.
// Lives top-left, NOT bottom-left, so it never collides with the wide bottom-center composer.
const CanvasHint = () => (
  <div data-no-pan style={{
    position:'absolute', left:14, top:52, display:'flex', alignItems:'center', gap:LM.sp.sm,
    background:LM.bgPanel+'cc', backdropFilter:'blur(6px)',
    border:`1px solid ${LM.lineSoft}`, borderRadius:LM.rad.sm, padding:'4px 9px',
    fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.04em',
  }}>
    <span>scroll → zoom</span>
    <span style={{ color:LM.inkDim }}>·</span>
    <span>drag → pan</span>
    <span style={{ color:LM.inkDim }}>·</span>
    <span>right-click → menu</span>
  </div>
);

// Right-click canvas context menu
const CanvasMenu = ({ x, y, onAddNode, onFit, onClose }) => {
  React.useEffect(() => {
    const dismiss = () => onClose();
    document.addEventListener('click', dismiss);
    document.addEventListener('keydown', e => e.key === 'Escape' && dismiss());
    return () => document.removeEventListener('click', dismiss);
  }, [onClose]);
  const items = [
    { i:'＋',  t:'Add node…',          k:'⌘L',  on:onAddNode },
    { i:'⎘',  t:'Paste',               k:'⌘V' },
    { sep:true },
    { i:'⌴',  t:'Fit graph to view',   k:'⌘0', on:onFit },
    { i:'⊜',  t:'Zoom to 100%',        k:'⌘1' },
    { sep:true },
    { i:'·',  t:'Snap to grid',        toggle:true, on:true },
    { i:'⧉',  t:'Auto-layout',         k:'⌘⇧L' },
    { sep:true },
    { i:'↻',  t:'Reset positions',     k:'⌘⇧R' },
    { i:'✕',  t:'Clear all nodes',     k:'',    danger:true },
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
        <button key={i} onClick={() => { it.on && it.on(); onClose(); }} style={{
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
const NodeRenderer = ({ n, focused, dimmed, expanded, onToggleExpand, onDragStart, onFocus }) => {
  const cat = CAT[n.cat];
  // AI nodes can expand horizontally for full conversation + search
  const w = (n.cat === 'ai' && expanded) ? Math.max(520, n.w) : n.w;
  const isAi = n.cat === 'ai';
  return (
    <div className="lm-node" onClick={onFocus}
      style={{
        position:'absolute', left:n.x, top:n.y, width:w, minHeight:n.h,
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
          padding:'7px 11px', display:'flex', alignItems:'center', gap:LM.sp.sm,
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
            width:18, height:18, padding:0, border:0, borderRadius:LM.rad.xs,
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
      {n.ins?.map((s, i) => <Socket key={'in-'+s.id} side="in" i={i} t={s.t} label={s.label}/>)}
      {n.outs?.map((s, i) => <Socket key={'out-'+s.id} side="out" i={i} t={s.t} label={s.label}/>)}
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

const Socket = ({ side, i, t, label }) => {
  const col = WIRE[t] || LM.inkSoft;
  return (
    <div style={{
      position:'absolute', top: socketY(i) - SOCKET_R,
      [side === 'in' ? 'left' : 'right']: -SOCKET_R,
      display:'flex', alignItems:'center', gap:6,
      flexDirection: side === 'in' ? 'row' : 'row-reverse',
      pointerEvents:'none',
    }}>
      <span style={{
        width: SOCKET_R*2, height: SOCKET_R*2, borderRadius:'50%',
        background: side === 'out' ? col : LM.bgPanel,
        border:`1.5px solid ${col}`, boxShadow:`0 0 0 2px ${LM.bgCanvas}`,
      }}/>
      <span style={{
        fontFamily:LM.mono, fontSize:8.5, color:LM.inkMuted, letterSpacing:'0.04em',
        whiteSpace:'nowrap', padding:'0 4px',
        opacity: label ? 0.85 : 0,
      }}>{label}</span>
    </div>
  );
};

// ─── per-category body content ───
// The inline reply is a real ask: it reaches the same agent the main
// composer does, and reports its answer where it was typed.
const InlineAsk = ({ placeholder }) => {
  const [text, setText] = React.useState('');
  const [state, setState] = React.useState('');
  const ask = async () => {
    const said = text.trim();
    if (!said || !window.ARCHHUB_AGENT) return;
    setState('asking…');
    try {
      setState(String(await window.ARCHHUB_AGENT(said)).slice(0, 60));
      setText('');
    } catch (error) {
      setState('refused: ' + (error?.message || error));
    }
  };
  return (
    <>
      <input value={text} onChange={e => setText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') ask(); }}
        placeholder={state || placeholder || 'Reply…'}
        style={{ flex:1, background:'transparent', border:0, outline:0,
          fontStyle:'italic', fontFamily:LM.serif, fontSize:12,
          color: state ? LM.accent : LM.ink }}/>
      <button onClick={ask} style={{ padding:'3px 8px', background:LM.accent, color: (window.AH && window.AH.onFill) || '#180f08', border:0, borderRadius:4, fontSize:10, fontWeight:500, cursor:'pointer' }}>Send ↵</button>
    </>
  );
};

const NodeBody = ({ n, expanded, onToggleExpand }) => {
  // A GRAPH-BACKED node draws exactly its real parameters, its last run
  // answer, and what actually flowed. Never a category's demo furniture.
  if (n.live) return <LiveBody n={n}/>;
  switch (n.cat) {
    case 'host':      return <HostBody n={n}/>;
    case 'ai':        return <AIBody n={n} expanded={expanded} onToggleExpand={onToggleExpand}/>;
    case 'read':      return <ReadBody n={n}/>;
    case 'filter':    return <FilterBody n={n}/>;
    case 'transform': return <TransformBody n={n}/>;
    case 'logic':     return <LogicBody n={n}/>;
    case 'compose':   return <ComposeBody n={n}/>;
    case 'annotate':  return <AnnotateBody n={n}/>;
    case 'output':    return <OutputBody n={n}/>;
    default:          return null;
  }
};

const LiveBody = ({ n }) => (
  <div style={{ marginTop:9, display:'flex', flexDirection:'column', gap:LM.sp.xs }}>
    {(n.params || []).slice(0, 4).map(row => (
      <div key={row.k} style={{ display:'flex', gap:6, fontFamily:LM.mono, fontSize:10 }}>
        <span style={{ color:LM.inkMuted, letterSpacing:'0.04em' }}>{row.k}</span>
        <div style={{ flex:1, borderBottom:`1px dashed ${LM.lineSoft}`, marginBottom:2 }}/>
        <span style={{ color:LM.ink, maxWidth:110, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{String(row.v)}</span>
      </div>
    ))}
    {n.status ? (
      <div style={{ marginTop:2, fontFamily:LM.mono, fontSize:9.5, color:LM.accent, letterSpacing:'0.03em', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{n.status}</div>
    ) : null}
    <LinePreview id={n.id}/>
  </div>
);

// The watcher's eyes: the ACTUAL segments the last run produced.
const LinePreview = ({ id }) => {
  const lines = window.ARCHHUB_LAST_RUN?.lines?.[id];
  if (!lines || !lines.length) return null;
  const xs = lines.flatMap(l => [l[0], l[2]]);
  const ys = lines.flatMap(l => [l[1], l[3]]);
  const x0 = Math.min(...xs), y0 = Math.min(...ys);
  const w = Math.max(1, Math.max(...xs) - x0);
  const h = Math.max(1, Math.max(...ys) - y0);
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="xMidYMid meet"
      style={{ width:'100%', height:64, marginTop:6, background:LM.bgDeep,
        border:`1px solid ${LM.lineSoft}`, borderRadius:4 }}>
      {lines.map((l, i) => (
        <line key={i} x1={l[0]-x0} y1={l[1]-y0} x2={l[2]-x0} y2={l[3]-y0}
          stroke={LM.accent} strokeWidth={Math.max(w, h) / 90}/>
      ))}
    </svg>
  );
};

const HostBody = ({ n }) => (
  <div style={{ marginTop:9, display:'flex', flexDirection:'column', gap:LM.sp.xs }}>
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
  const total = n.messages.length;

  if (expanded) {
    const filtered = q ? n.messages.filter(m => m.text.toLowerCase().includes(q.toLowerCase())) : n.messages;
    return (
      <div onClick={e => e.stopPropagation()} style={{ marginTop:9, display:'flex', flexDirection:'column', gap:7 }}>
        {/* Search bar */}
        <div style={{
          display:'flex', alignItems:'center', gap:6, padding:'5px 9px',
          background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.sm,
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
          background:LM.bgDeep, border:`1px solid ${LM.lineSoft}`, borderRadius:LM.rad.sm,
          padding:'9px 11px', display:'flex', flexDirection:'column', gap:10,
        }}>
          {filtered.length === 0 && (
            <div style={{ padding:'12px 4px', fontSize:11, color:LM.inkMuted, textAlign:'center' }}>No matches for “{q}”.</div>
          )}
          {filtered.map((m, i) => (
            <div key={i} style={{ display:'flex', gap:7 }}>
              <div style={{
                width:18, height:18, borderRadius: m.me ? '50%' : 4, flexShrink:0,
                background: m.me ? '#d8c5a8' : LM.accent,
                color: m.me ? '#5a4a2a' : ((window.AH && window.AH.onFill) || '#180f08'),
                display:'grid', placeItems:'center', fontSize:10, fontWeight:700,
              }}>{m.who}</div>
              <div style={{ flex:1, minWidth:0 }}>
                <div style={{ display:'flex', alignItems:'baseline', gap:7, marginBottom:1 }}>
                  <span style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.04em' }}>{m.time || ''}</span>
                </div>
                <div style={{ fontSize:11.5, lineHeight:1.5, color: m.me ? LM.ink : LM.inkSoft }}>
                  {q ? highlight(m.text, q) : m.text}
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Inline reply */}
        <div style={{
          display:'flex', alignItems:'center', gap:6, padding:'5px 9px',
          background:LM.bg, border:`1px solid ${LM.accent}55`, borderRadius:LM.rad.sm,
        }}>
          <span style={{ color:LM.accent, fontFamily:LM.mono, fontSize:11 }}>/</span>
          <InlineAsk/>
        </div>
      </div>
    );
  }

  // Compact view
  const recent = n.messages.slice(-2);
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
        return (
          <div key={i} style={{ display:'flex', gap:LM.sp.sm }}>
            <div style={{
              width:18, height:18, borderRadius: m.me ? '50%' : 4,
              background: m.me ? '#d8c5a8' : LM.accent,
              color: m.me ? '#5a4a2a' : ((window.AH && window.AH.onFill) || '#180f08'),
              display:'grid', placeItems:'center', fontSize:10, fontWeight:700, flexShrink:0,
            }}>{m.who}</div>
            <div style={{ flex:1, minWidth:0 }}>
              <div style={{ fontSize:12, color: m.me ? LM.ink : LM.inkSoft, lineHeight:1.45 }}>
                {m.text}
                {isAssistant && isLast && (
                  <span style={{ display:'inline-block', width:6, height:11, background:LM.accent, marginLeft:2, verticalAlign:'-1px', animation:'lmCaret 1s infinite' }}/>
                )}
              </div>
              {isAssistant && isLast && (
                <button onClick={(e) => { e.stopPropagation(); setShowReasoning(s => !s); }} style={{
                  background:'transparent', border:0, padding:'3px 0', color:LM.inkMuted,
                  fontFamily:LM.mono, fontSize:9.5, letterSpacing:'0.06em', cursor:'pointer',
                  display:'flex', alignItems:'center', gap:LM.sp.xs, marginTop:3,
                }}>
                  <span>{showReasoning ? '▾' : '▸'}</span> reasoning · 4 steps
                </button>
              )}
              {isAssistant && isLast && showReasoning && (
                <div style={{
                  marginTop:3, padding:'5px 8px', background:LM.bgDeep,
                  border:`1px solid ${LM.lineSoft}`, borderLeft:`2px solid ${LM.purple}`, borderRadius:LM.rad.xs,
                  fontFamily:LM.mono, fontSize:9.5, color:LM.inkSoft, lineHeight:1.6,
                }}>
                  <div>1. match-skill = "Dimension walls"</div>
                  <div>2. exterior is the noisier baseline → start there</div>
                  <div>3. 800mm threshold matches user's note</div>
                  <div>4. defer interior to stage 2 so user can confirm</div>
                </div>
              )}
            </div>
          </div>
        );
      })}
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
    <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, marginBottom:LM.sp.xs }}>predicate</div>
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
  <div style={{ marginTop:LM.sp.sm, display:'flex', flexDirection:'column', gap:6 }}>
    {n.params?.map(p => (
      <div key={p.k} style={{ display:'flex', alignItems:'center', gap:6, fontFamily:LM.mono, fontSize:10 }}>
        <span style={{ color:LM.inkMuted, letterSpacing:'0.04em' }}>{p.k}</span>
        <div style={{ flex:1, borderBottom:`1px dashed ${LM.lineSoft}`, marginBottom:2 }}/>
        <span style={{ color:LM.ink, padding:'1px 6px', background:LM.bg, border:`1px solid ${LM.lineSoft}`, borderRadius:LM.rad.xs }}>{p.v}</span>
      </div>
    ))}
    <div style={{
      marginTop:2, fontFamily:LM.mono, fontSize:10, color:LM.warn,
      padding:'4px 8px', background:LM.warn+'14', borderRadius:LM.rad.xs,
      display:'flex', alignItems:'center', gap:6,
    }}>
      <span>⚠</span><span>mutates model · requires approval</span>
    </div>
  </div>
);

// Logic body — predicate with branch indicators
const LogicBody = ({ n }) => (
  <div style={{ marginTop:LM.sp.sm }}>
    <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, marginBottom:LM.sp.xs }}>predicate</div>
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
  <div style={{ marginTop:LM.sp.sm }}>
    <div style={{
      background:LM.bgInk, border:`1px solid ${LM.lineSoft}`, borderRadius:LM.rad.sm, overflow:'hidden',
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
  <div style={{ marginTop:LM.sp.sm, display:'flex', flexDirection:'column', gap:7 }}>
    {n.params?.slice(0, 2).map(p => (
      <div key={p.k} style={{ display:'flex', flexDirection:'column', gap:2 }}>
        <span style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, letterSpacing:'0.04em' }}>{p.k}</span>
        <div style={{ background:LM.bg, border:`1px solid ${LM.lineSoft}`, borderRadius:4, padding:'4px 8px', fontFamily:LM.mono, fontSize:10.5, color:LM.ink }}>
          {p.v}
        </div>
      </div>
    ))}
    <div style={{ display:'flex', gap:6, marginTop:LM.sp.xs }}>
      <button onClick={async (e) => {
        const b = e.currentTarget;
        b.textContent = 'running…';
        try {
          const result = await window.ARCHHUB_RUN();
          b.textContent = String(
            result?.display?.[n.id] || result?.pending?.[n.id] || 'ran'
          ).slice(0, 30);
        } catch (error) { b.textContent = 'refused'; }
        setTimeout(() => { b.textContent = 'preview'; }, 6000);
      }} style={smallBtn()}>preview</button>
      <button onClick={async (e) => {
        const b = e.currentTarget;
        b.textContent = 'saving…';
        try {
          await window.ARCHHUB_RUN();
          b.textContent = 'saved to the graph';
        } catch (error) { b.textContent = 'refused'; }
        setTimeout(() => { b.textContent = 'save'; }, 5000);
      }} style={smallBtn(true)}>save</button>
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
        <div style={{ height:3, background:LM.bgDeep, borderRadius:2, marginTop:LM.sp.xs, position:'relative' }}>
          <div style={{ width:`${pct}%`, height:'100%', background:LM.accent, borderRadius:2 }}/>
          <div style={{ position:'absolute', left:`calc(${pct}% - 4px)`, top:-2.5, width:8, height:8, borderRadius:'50%', background:LM.ink, border:`1.5px solid ${LM.accent}` }}/>
        </div>
      </div>
    );
  }
  return (
    <div style={{ display:'flex', alignItems:'center', gap:6 }}>
      <span style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkSoft, flex:1, letterSpacing:'0.04em' }}>{p.k}</span>
      <span style={{ fontFamily:LM.mono, fontSize:10, color:LM.ink, padding:'1px 6px', background:LM.bg, border:`1px solid ${LM.lineSoft}`, borderRadius:LM.rad.xs }}>
        {p.v} <span style={{ color:LM.inkMuted, marginLeft:2 }}>▾</span>
      </span>
    </div>
  );
};

const StagePreview = () => (
  <div style={{
    aspectRatio:'2/1', background:LM.bgInk, border:`1px solid ${LM.lineSoft}`, borderRadius:LM.rad.sm,
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
const CanvasToolbar = ({ zoom, setZoom, onFit, setLibraryOpen }) => (
  <div data-no-pan style={{
    position:'absolute', left:14, top:14, display:'flex', gap:LM.sp.xs,
    background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:7, padding:LM.sp.xs,
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
      display:'flex', alignItems:'center', gap:LM.sp.xs,
    }}>＋ add node</button>
  </div>
);

const toolBtn = () => ({
  width:24, height:22, padding:0, border:0, background:'transparent',
  color:LM.inkSoft, borderRadius:4, cursor:'pointer', fontSize:13,
});

// ─── floating composer (BOTTOM CENTER — always-bottom anchor) ───
const FloatingComposer = ({ setLibraryOpen }) => (
  <div data-no-pan style={{
    position:'absolute', left:'50%', bottom:14, transform:'translateX(-50%)',
    width:620, maxWidth:'82%',
    background:LM.bgPanel, border:`1px solid ${LM.accent}66`,
    borderRadius:9, boxShadow:`0 14px 30px rgba(0,0,0,.5), 0 0 0 3px ${LM.accentDim}`,
    padding:'10px 13px',
  }}>
    <div style={{ display:'flex', alignItems:'center', gap:LM.sp.sm, fontSize:13.5, fontFamily:LM.sans, color:LM.ink, minHeight:24 }}>
      <span style={{ color:LM.accent, fontFamily:LM.mono, fontSize:13 }}>/</span>
      <span style={{ animation:'lmCaret 1s infinite', display:'inline-block', width:1.5, height:16, background:LM.accent, marginLeft:-4 }}/>
      <InlineAsk placeholder="Reply, or ask the agent to build…"/>
      <button onClick={(e) => { e.stopPropagation(); setLibraryOpen(true); }} style={{ ...smallBtn(), padding:'3px 9px' }}>library</button>
    </div>
  </div>
);

// ─── mini-map (TOP-RIGHT) ───
const MiniMap = ({ pan, zoom, positions, allNodes }) => {
  const nodes = allNodes || LM_GRAPH.nodes;
  return (
    <div data-no-pan style={{
      position:'absolute', right:14, top:14, width:170, height:96,
      background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:LM.rad.md,
      overflow:'hidden', boxShadow:'0 4px 12px rgba(0,0,0,.3)',
    }}>
      <svg viewBox="0 0 2400 1400" style={{ width:'100%', height:'100%' }}>
        {nodes.map(n => {
          const p = positions[n.id] || { x: n.x, y: n.y };
          const cat = CAT[n.cat];
          return (
            <rect key={n.id} x={p.x} y={p.y} width={n.w} height={n.h}
              fill={cat.col + '66'} stroke={LM.lineSoft} strokeWidth="2" rx="4"/>
          );
        })}
      </svg>
      <div style={{
        position:'absolute', left:6, top:5, fontFamily:LM.mono, fontSize:8,
        color:LM.inkMuted, letterSpacing:'0.14em', background:LM.bgDeep+'cc', padding:'1px 5px', borderRadius:2,
      }}>MAP</div>
    </div>
  );
};

// ──────────────────────── NODE LIBRARY ────────────────────────
const NodeLibrary = ({ onClose, addNodeFromLibrary }) => {
  const [filter, setFilter] = React.useState('all');
  const [q, setQ] = React.useState('');
  const groups = filter === 'all' ? LM_LIBRARY : LM_LIBRARY.filter(g => g.cat === filter);
  return (
    <div onClick={onClose} style={{
      position:'absolute', inset:0, background:'rgba(0,0,0,.55)', zIndex:60,
      display:'grid', placeItems:'center',
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        width:780, maxWidth:'94%', height:540, maxHeight:'88%',
        background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:LM.rad.xl,
        overflow:'hidden', boxShadow:'0 30px 80px rgba(0,0,0,.6)',
        display:'grid', gridTemplateColumns:'180px 1fr', gridTemplateRows:'48px 1fr',
      }}>
        <div style={{ gridColumn:'1 / -1', gridRow:'1', borderBottom:`1px solid ${LM.line}`, padding:'0 14px', display:'flex', alignItems:'center', gap:10 }}>
          <span style={{ fontFamily:LM.serif, fontSize:18, letterSpacing:'-0.01em' }}>Node library</span>
          <span style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, letterSpacing:'0.1em' }}>
            {LM_LIBRARY.reduce((n, g) => n + g.items.length, 0)} NODES · CLICK TO ADD
          </span>
          <div style={{ flex:1 }}/>
          <input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="Search… (e.g. dimension, schedule, push)" style={{
            padding:'6px 11px', background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.sm,
            color:LM.ink, fontFamily:LM.sans, fontSize:12.5, outline:'none', width:280,
          }}/>
          <button onClick={onClose} style={{
            width:24, height:24, padding:0, border:`1px solid ${LM.line}`, background:'transparent',
            borderRadius:LM.rad.sm, cursor:'pointer', color:LM.inkSoft, fontSize:12,
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
          {groups.map(g => {
            const c = CAT[g.cat];
            const items = q ? g.items.filter(i => (i.title + ' ' + i.sub).toLowerCase().includes(q.toLowerCase())) : g.items;
            if (items.length === 0) return null;
            return (
              <div key={g.cat} style={{ marginBottom:18 }}>
                <div style={{ display:'flex', alignItems:'center', gap:LM.sp.sm, marginBottom:LM.sp.sm }}>
                  <span style={{ color:c.col }}>{c.icon}</span>
                  <span style={{ fontFamily:LM.mono, fontSize:10, color:c.col, letterSpacing:'0.18em' }}>{c.label}</span>
                  <span style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.06em' }}>{c.role}</span>
                </div>
                <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:6 }}>
                  {items.map(i => (
                    <button key={i.id} onClick={() => { addNodeFromLibrary && addNodeFromLibrary({ ...i, cat:g.cat }); onClose(); }} style={{
                      background:LM.bg, border:`1px solid ${LM.line}`, borderLeft:`2px solid ${c.col}`,
                      borderRadius:LM.rad.md, padding:'8px 11px', textAlign:'left', cursor:'pointer',
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
    width:'100%', padding:'7px 11px', borderRadius:LM.rad.sm, border:0,
    background: active ? LM.bgSoft : 'transparent',
    color: active ? LM.ink : LM.inkSoft,
    textAlign:'left', cursor:'pointer', fontFamily:LM.sans, fontSize:13,
    display:'flex', alignItems:'center', gap:LM.sp.sm, marginBottom:1,
  }}>
    {icon && <span style={{ color:col, width:12, textAlign:'center', fontFamily:LM.mono, fontSize:11 }}>{icon}</span>}
    <span style={{ flex:1 }}>{label}</span>
  </button>
);

// ──────────────────────── NODE RAIL ────────────────────────
const NodeRail = ({ node }) => {
  if (!node) return <aside style={{ gridColumn:'2', gridRow:'2', background:LM.bgPanel, borderLeft:`1px solid ${LM.line}` }}/>;
  // AI node gets a dedicated conversation rail — full scrollback + composer
  if (node.cat === 'ai') return <ConversationRail node={node}/>;
  const cat = CAT[node.cat];
  return (
    <aside className="ah-scroll" style={{
      gridColumn:'2', gridRow:'2',
      background:LM.bgPanel, borderLeft:`1px solid ${LM.line}`,
      overflow:'auto', minHeight:0,
      padding:'14px 16px 20px',
      display:'flex', flexDirection:'column', gap:LM.sp.lg,
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

      {/* Connections, parameters and actions are one instrument — see studio-params.jsx.
          The old block was dead form widgets: native selects, a bare range input and four
          equal-weight buttons, none of which could be typed into or reverted. */}
      <window.NodeInspector key={node.id} node={node}/>
    </aside>
  );
};

// ─── Conversation rail — full chat history + inline composer ───
// Shown when the focused node is an AI/chat node. THIS is where the user
// reads scrollback and continues the conversation.
const ConversationRail = ({ node }) => {
  const cat = CAT.ai;
  const scrollRef = React.useRef(null);
  // Auto-scroll to bottom when node changes
  React.useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [node.id]);
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
        <div style={{ display:'flex', alignItems:'center', gap:LM.sp.sm, fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.14em' }}>
          <span style={{ flex:1, height:1, background:LM.lineHair }}/>
          <span>WEDNESDAY · MAY 13</span>
          <span style={{ flex:1, height:1, background:LM.lineHair }}/>
        </div>

        {node.messages.map((m, i) => <ChatTurn key={i} m={m} isLast={i === node.messages.length - 1}/>)}

        {/* Tool-call summary block — what the chat triggered */}
        <div style={{
          padding:'9px 12px', background:LM.bgDeep, border:`1px solid ${LM.lineSoft}`,
          borderLeft:`2px solid ${LM.cyan}`, borderRadius:LM.rad.sm,
          fontFamily:LM.mono, fontSize:10.5, color:LM.inkSoft, lineHeight:1.7,
        }}>
          <div style={{ fontFamily:LM.mono, fontSize:9, color:LM.cyan, letterSpacing:'0.14em', marginBottom:LM.sp.xs }}>
            FROM THIS CONVERSATION
          </div>
          <div>→ list_walls(view) · 47 walls · 120ms</div>
          <div>→ filter(exterior=true) · 23 walls · 80ms</div>
          <div>→ filter(length≥800) · 14 walls · 18ms</div>
          <div>→ create_dimensions · running 17/23</div>
        </div>
      </div>

      {/* Inline composer */}
      <div style={{ padding:'10px 14px 14px', borderTop:`1px solid ${LM.lineSoft}` }}>
        <div style={{
          background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:7,
          padding:'8px 11px',
        }}>
          <div style={{ display:'flex', alignItems:'center', gap:6, minHeight:22, fontSize:13, color:LM.inkSoft }}>
            <InlineAsk placeholder="Reply to this conversation…"/>
          </div>
          <div style={{ display:'flex', alignItems:'center', gap:5, marginTop:5, fontFamily:LM.mono, fontSize:9, color:LM.inkMuted }}>
            <ChatAction>@ skill</ChatAction>
            <ChatAction># host</ChatAction>
            <ChatAction>+ attach</ChatAction>
            <ChatAction>/remember</ChatAction>
            <div style={{ flex:1 }}/>
            <span>sonnet 4.5 · ~412ms</span>
          </div>
        </div>
        <div style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, marginTop:6, letterSpacing:'0.04em', display:'flex', gap:10 }}>
          <span>↵ send</span>
          <span>⇧↵ newline</span>
          <span>⌘↑ edit last</span>
          <span style={{ flex:1 }}/>
          <span>session auto-saves</span>
        </div>
      </div>
    </aside>
  );
};

const ChatTurn = ({ m, isLast }) => {
  const [showReasoning, setShowReasoning] = React.useState(false);
  const isAssistant = !m.me;
  return (
    <div style={{ display:'flex', gap:10 }}>
      <div style={{
        width:24, height:24, borderRadius: m.me ? '50%' : 5, flexShrink:0,
        background: m.me ? '#d8c5a8' : LM.accent,
        color: m.me ? '#5a4a2a' : ((window.AH && window.AH.onFill) || '#180f08'),
        display:'grid', placeItems:'center', fontSize:12, fontWeight:700,
      }}>{m.who}</div>
      <div style={{ flex:1, minWidth:0 }}>
        <div style={{ display:'flex', alignItems:'baseline', gap:LM.sp.sm, marginBottom:3 }}>
          <span style={{ fontSize:12, fontWeight:500, color:LM.ink }}>{m.me ? 'You' : 'Claude'}</span>
          <span style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.04em' }}>{m.time}</span>
        </div>
        <div style={{ fontSize:13, lineHeight:1.55, color:LM.ink }}>
          {m.text}
          {isAssistant && isLast && (
            <span style={{ display:'inline-block', width:6, height:12, background:LM.accent, marginLeft:2, verticalAlign:'-1px', animation:'lmCaret 1s infinite' }}/>
          )}
        </div>
        {isAssistant && (
          <>
            <button onClick={() => setShowReasoning(s => !s)} style={{
              background:'transparent', border:0, padding:'3px 0', color:LM.inkMuted,
              fontFamily:LM.mono, fontSize:9.5, letterSpacing:'0.06em', cursor:'pointer',
              display:'flex', alignItems:'center', gap:LM.sp.xs, marginTop:3,
            }}>
              <span>{showReasoning ? '▾' : '▸'}</span> reasoning
            </button>
            {showReasoning && (
              <div style={{
                marginTop:3, padding:'5px 8px', background:LM.bgDeep,
                border:`1px solid ${LM.lineSoft}`, borderLeft:`2px solid ${LM.purple}`, borderRadius:LM.rad.xs,
                fontFamily:LM.mono, fontSize:9.5, color:LM.inkSoft, lineHeight:1.6,
              }}>
                1. parse intent · 2. plan stages · 3. confirm units · 4. queue tools
              </div>
            )}
            <div style={{
              display:'flex', alignItems:'center', gap:5, marginTop:5,
              fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.04em',
            }}>
              <ChatAction>↻ regen</ChatAction>
              <ChatAction>⎘ branch</ChatAction>
              <ChatAction>✎ edit</ChatAction>
              <ChatAction>⧉ copy</ChatAction>
              <div style={{ flex:1 }}/>
              <span>312 → 184 tok</span>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

const ChatAction = ({ children }) => (
  <button onClick={e => e.stopPropagation()} style={{
    padding:'1px 5px', background:'transparent', border:`1px solid ${LM.lineSoft}`,
    borderRadius:LM.rad.xs, color:LM.inkMuted, fontFamily:LM.mono, fontSize:9, cursor:'pointer',
  }}>{children}</button>
);


// ──────────────────────── SETTINGS ────────────────────────
const SET_LS = 'archhub.studio.settings.v1';
// Single source for "what is this item's current state?" — used by BOTH the sidebar badges and
// the panel rows. Defined once precisely so the two cannot derive the same fact differently:
// the badges previously counted only keys PRESENT in the store while the rows fell back to the
// seed per item, so an empty or partial store made a badge contradict the panel beside it.
const hostState = (store, h) => ((store && store.hosts) || {})[h.name] || h.state;
const permMode  = (store, p) => ((store && store.perms) || {})[p.id] || p.mode;
const Settings = ({ onClose, account, setAccount, onSignOut }) => {
  const [tab, setTab] = React.useState(account && account.signedIn ? 'account' : 'memory');
  const [store, setStore] = React.useState(() => {
    var seed = {
      perms: LM_PERMISSIONS.reduce(function (a, p) { a[p.id] = p.mode; return a; }, {}),
      theme: 'Dark',
      forgotten: [],
      hosts: LM_HOSTS.reduce(function (a, h) { a[h.name] = h.state; return a; }, {}),
      revealed: {},
    };
    // MERGE PER KEY, never swap the container: Object.assign is shallow, so a persisted
    // `perms`/`hosts` object would REPLACE the fully-seeded one and drop every capability the
    // founder hadn't touched. Rows still rendered (each falls back to its own default) but the
    // sidebar badges count Object.values(store.perms) — so the panel looked right while the
    // badge under-reported.
    try {
      var raw = localStorage.getItem(SET_LS);
      if (raw) {
        var saved = JSON.parse(raw) || {};
        return Object.assign({}, seed, saved, {
          perms: Object.assign({}, seed.perms, saved.perms || {}),
          hosts: Object.assign({}, seed.hosts, saved.hosts || {}),
          revealed: Object.assign({}, seed.revealed, saved.revealed || {}),
        });
      }
    } catch (e) {}
    return seed;
  });
  React.useEffect(() => { try { localStorage.setItem(SET_LS, JSON.stringify(store)); } catch (e) {} }, [store]);
  const patch = (k, v) => setStore(st => Object.assign({}, st, typeof k === 'object' ? k : { [k]: v }));
  const tabs = [
    ['account',     'Account',     `${(AC_PLANS.find(p => p.id === (account || {}).plan) || AC_PLANS[1]).name} · ${((account || {}).usage || {}).spend || 0}`],
    ['memory',      'Memory',      `${LM_MEMORY.length - (store.forgotten || []).length} facts`],
    ['profile',     'Profile',     'Architect'],
    ['permissions', 'Permissions', (() => { const v = LM_PERMISSIONS.map(p => permMode(store, p)); return `${v.filter(x => x === 'auto').length} auto · ${v.filter(x => x === 'ask').length} ask`; })()],
    ['hosts',       'Hosts',       `${LM_HOSTS.filter(h => hostState(store, h) !== 'off').length} live`],
    ['providers',   'Providers',   '3 keys'],
    ['models',      'Models',      'Sonnet 4.5'],
    ['theme',       'Theme',       store.theme],
    ['shortcuts',   'Shortcuts',   null],
    ['storage',     'Storage',     '2.3 GB'],
    ['about',       'About',       'v1.4'],
  ];
  return (
    <div onClick={onClose} style={{
      position:'absolute', inset:0, background:'rgba(0,0,0,.5)', zIndex:60,
      display:'grid', placeItems:'center',
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        width:920, maxWidth:'95%', height:580, maxHeight:'90%',
        background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:LM.rad.xl,
        overflow:'hidden', boxShadow:'0 30px 80px rgba(0,0,0,.6)',
        display:'grid', gridTemplateColumns:'208px 1fr', gridTemplateRows:'46px 1fr',
      }}>
        <div style={{ gridColumn:'1 / -1', gridRow:'1', borderBottom:`1px solid ${LM.line}`, display:'flex', alignItems:'center', gap:10, padding:'0 16px' }}>
          <span style={{ fontFamily:LM.serif, fontSize:18, letterSpacing:'-0.01em' }}>Settings</span>
          <span style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, letterSpacing:'0.1em' }}>STUDIO · v1.4</span>
          <div style={{ flex:1 }}/>
          <button onClick={onClose} style={{
            width:24, height:24, padding:0, border:`1px solid ${LM.line}`, background:'transparent',
            borderRadius:LM.rad.sm, cursor:'pointer', color:LM.inkSoft, fontSize:12,
          }}>✕</button>
        </div>
        <div style={{ gridColumn:'1', gridRow:'2', borderRight:`1px solid ${LM.line}`, padding:'10px 8px', overflow:'auto' }}>
          {tabs.map(([id, label, badge]) => (
            <button key={id} onClick={() => setTab(id)} style={{
              width:'100%', padding:'7px 11px', borderRadius:LM.rad.sm, border:0,
              background: tab === id ? LM.bgSoft : 'transparent',
              color: tab === id ? LM.ink : LM.inkSoft,
              textAlign:'left', cursor:'pointer', fontFamily:LM.sans, fontSize:13,
              display:'flex', alignItems:'center', gap:LM.sp.sm, marginBottom:1,
            }}>
              <span style={{ flex:1 }}>{label}</span>
              {badge && <span style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.04em' }}>{badge}</span>}
            </button>
          ))}
        </div>
        <div className="ah-scroll" style={{ gridColumn:'2', gridRow:'2', overflow:'auto', padding:'20px 24px 24px' }}>
          {tab === 'account'     && <SettingsAccount account={account} setAccount={setAccount} onSignOut={onSignOut}/>}
          {tab === 'memory'      && <SettingsMemory store={store} patch={patch}/>}
          {tab === 'profile'     && <SettingsProfile/>}
          {tab === 'permissions' && <SettingsPermissions store={store} patch={patch}/>}
          {tab === 'hosts'       && <SettingsHosts store={store} patch={patch}/>}
          {tab === 'providers'   && <SettingsProviders store={store} patch={patch}/>}
          {tab === 'models'      && <SettingsModels/>}
          {tab === 'theme'       && <SettingsTheme store={store} patch={patch}/>}
          {tab === 'shortcuts'   && <SettingsShortcuts/>}
          {tab === 'storage'     && <SettingsStorage/>}
          {tab === 'about'       && <SettingsAbout/>}
        </div>
      </div>
    </div>
  );
};

// ── Settings section header
const SHead = ({ title, sub }) => (
  <div style={{ marginBottom:14 }}>
    <div style={{ fontFamily:LM.serif, fontSize:22, letterSpacing:'-0.01em' }}>{title}</div>
    {sub && <div style={{ fontFamily:LM.sans, fontSize:13, color:LM.inkSoft, marginTop:3, lineHeight:1.5 }}>{sub}</div>}
  </div>
);

// ── Memory: things the AI remembers about you (Notion AI / Claude style)
const LM_MEMORY = [
  { id:'m1', text:'Works at Habib Studio · architect, project lead on Tower A.', src:'profile' },
  { id:'m2', text:'Prefers millimeters and ISO drafting conventions, never imperial.', src:'preference · 12 confirmations' },
  { id:'m3', text:'Tower-A_central.rvt is the central model; never edit linked files.', src:'project' },
  { id:'m4', text:'Skip walls shorter than 800 mm when dimensioning interior partitions.', src:'learned · 4 sessions' },
  { id:'m5', text:'Door schedule QA runs are usually reviewed before publishing.', src:'learned · 8 sessions' },
  { id:'m6', text:'Wants explanations to be terse and technical, no preamble.', src:'preference' },
  { id:'m7', text:'Always exports PDF sets to the team Dropbox, not local.', src:'workflow · 38 runs' },
  { id:'m8', text:'Hates emoji in chat output.', src:'preference · explicit' },
];
const SettingsMemory = ({ store, patch }) => (
  <div>
    <SHead title="Memory" sub="What Claude remembers about you across sessions. Edit, forget, or pin. Nothing is sent to the model unless you load this session."/>
    <div style={{
      display:'flex', alignItems:'center', gap:LM.sp.sm, padding:'9px 12px', marginBottom:LM.sp.md,
      background:LM.accentDim, border:`1px solid ${LM.accent}55`, borderRadius:7,
    }}>
      <span style={{ color:LM.accent, fontSize:14 }}>✦</span>
      <span style={{ flex:1, fontSize:12.5 }}>You can also say "<span style={{ color:LM.accent, fontFamily:LM.mono }}>/remember</span> …" inside any chat — I'll save it here.</span>
      <button onClick={async (e) => {
        const said = window.prompt('What should the brain remember?');
        if (!said || !said.trim()) return;
        const b = e.currentTarget;
        b.textContent = 'saving…';
        try {
          await window.ARCHHUB_REMEMBER(said.trim());
          b.textContent = 'saved';
        } catch (error) {
          b.textContent = 'refused';
        }
        setTimeout(() => { b.textContent = 'add fact'; }, 4000);
      }} style={smallBtn()}>add fact</button>
    </div>
    <div style={{ background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg, overflow:'hidden' }}>
      {LM_MEMORY.filter(m => (store.forgotten || []).indexOf(m.id) < 0).map((m, i) => (
        <div key={m.id} style={{
          padding:'10px 14px', display:'flex', alignItems:'center', gap:LM.sp.md,
          borderTop: i===0 ? 'none' : `1px solid ${LM.lineSoft}`,
        }}>
          <span style={{ width:6, height:6, borderRadius:'50%', background:LM.accent, flexShrink:0 }}/>
          <div style={{ flex:1, minWidth:0 }}>
            <div style={{ fontSize:13, color:LM.ink, lineHeight:1.4 }}>{m.text}</div>
            <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, marginTop:2, letterSpacing:'0.04em' }}>{m.src}</div>
          </div>
          <button onClick={async (e) => {
            const said = window.prompt('Rewrite this memory', m.text);
            if (!said || said.trim() === m.text) return;
            const b = e.currentTarget;
            b.textContent = 'saving…';
            try {
              await window.ARCHHUB_REMEMBER(said.trim());
              b.textContent = 'saved';
            } catch (error) { b.textContent = 'refused'; }
            setTimeout(() => { b.textContent = 'edit'; }, 4000);
          }} style={{ ...smallBtn(), padding:'3px 8px' }}>edit</button>
          <button title={'Forget: ' + m.text}
            onClick={() => patch('forgotten', (store.forgotten || []).concat(m.id))}
            style={{ ...smallBtn(), padding:'3px 8px', color:LM.err, borderColor:LM.lineSoft }}>forget</button>
        </div>
      ))}
      {LM_MEMORY.length === (store.forgotten || []).length && (
        <div style={{ padding:'16px 14px', fontFamily:LM.serif, fontStyle:'italic', fontSize:14, color:LM.inkSoft }}>
          Nothing remembered. Claude starts every session cold.
        </div>
      )}
    </div>
    {(store.forgotten || []).length > 0 && (
      <div style={{ display:'flex', alignItems:'center', gap:10, marginTop:10 }}>
        <span style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkSoft, letterSpacing:'0.06em' }}>
          {(store.forgotten || []).length} forgotten this session
        </span>
        <button onClick={() => patch('forgotten', [])} style={{ ...smallBtn(), padding:'3px 9px' }}>restore all</button>
      </div>
    )}
    <div style={{ marginTop:14, padding:'10px 12px', background:LM.bg, border:`1px solid ${LM.lineSoft}`, borderRadius:LM.rad.md }}>
      <div style={{ display:'flex', alignItems:'center', gap:10 }}>
        <span style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.12em' }}>EXPORT</span>
        <span style={{ flex:1, fontSize:12, color:LM.inkSoft }}>Take your memory with you — JSON, plaintext, or Markdown.</span>
        <button onClick={async (e) => {
          const b = e.currentTarget;
          b.textContent = 'reading…';
          try {
            const facts = await window.ARCHHUB_BRAIN_EXPORT();
            const blob = new Blob([JSON.stringify(facts, null, 2)],
              { type:'application/json' });
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url; link.download = 'archhub-brain.json';
            document.body.appendChild(link); link.click(); link.remove();
            setTimeout(() => URL.revokeObjectURL(url), 4000);
            b.textContent = 'exported';
          } catch (error) {
            b.textContent = 'refused';
          }
          setTimeout(() => { b.textContent = 'export'; }, 4000);
        }} style={smallBtn()}>export</button>
        <button onClick={(e) => {
          // Forgetting everything is not a button press away. The brain
          // is the founder's memory; erasing it needs the real path, in
          // the folder, with his own hands.
          const b = e.currentTarget;
          b.textContent = 'open the folder to remove it';
          window.ARCHHUB_REVEAL?.('brain');
          setTimeout(() => { b.textContent = 'forget all'; }, 6000);
        }} style={{ ...smallBtn(), color:LM.err }}>forget all</button>
      </div>
    </div>
  </div>
);

// ── Profile: who you are, the AI's system prompt anchor
const SettingsProfile = () => (
  <div>
    <SHead title="Profile" sub="The grounding the model uses. Sets tone, units, and what 'we' means."/>
    <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:14 }}>
      <SField label="Display name" value="Fargaly Habib"/>
      <SField label="Studio / firm" value="Habib Studio"/>
      <SField label="Discipline" value="Architecture" select/>
      <SField label="Role" value="Project lead" select/>
      <SField label="Units" value="Millimeters (mm)" select/>
      <SField label="Drafting standard" value="ISO 128 / ISO 8048" select/>
      <SField label="Languages" value="English, Arabic"/>
      <SField label="Timezone" value="Cairo (UTC+2)"/>
    </div>
    <div style={{ marginTop:LM.sp.lg }}>
      <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.14em', marginBottom:6 }}>SYSTEM PROMPT — WRITTEN FROM YOUR PROFILE</div>
      <div style={{
        background:LM.bgDeep, border:`1px solid ${LM.lineSoft}`, borderLeft:`2px solid ${LM.cyan}`,
        borderRadius:LM.rad.sm, padding:'10px 13px', fontFamily:LM.serif, fontStyle:'italic',
        fontSize:13, color:LM.inkSoft, lineHeight:1.55,
      }}>
        You are working with Fargaly Habib, an architect leading Tower A at Habib Studio. Use millimeters, ISO conventions. Be terse and technical, no preamble. Never propose imperial units. Never use emoji. The active Revit document is the source of truth.
      </div>
      <div style={{ display:'flex', gap:6, marginTop:LM.sp.sm }}>
        <button onClick={async (e) => {
          const said = window.prompt('The instruction every agent inherits');
          if (!said || !said.trim()) return;
          const b = e.currentTarget;
          b.textContent = 'saving…';
          try {
            await window.ARCHHUB_REMEMBER('SYSTEM PROMPT: ' + said.trim());
            b.textContent = 'saved to the brain';
          } catch (error) { b.textContent = 'refused'; }
          setTimeout(() => { b.textContent = 'edit raw prompt'; }, 5000);
        }} style={smallBtn()}>edit raw prompt</button>
        <button onClick={async (e) => {
          const b = e.currentTarget;
          b.textContent = 'asking…';
          try {
            const answer = await window.ARCHHUB_AGENT(
              'In one sentence, state the standing instruction you are working under.');
            b.textContent = String(answer).slice(0, 48);
          } catch (error) { b.textContent = 'refused'; }
          setTimeout(() => { b.textContent = 'preview with this session'; }, 8000);
        }} style={smallBtn()}>preview with this session</button>
      </div>
    </div>
  </div>
);

const SField = ({ label, value, select }) => (
  <div>
    <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.1em', marginBottom:LM.sp.xs }}>{label.toUpperCase()}</div>
    <div style={{
      padding:'7px 10px', background:LM.bg, border:`1px solid ${LM.line}`,
      borderRadius:LM.rad.sm, fontSize:12.5, color:LM.ink, display:'flex', alignItems:'center', gap:6,
    }}>
      <span style={{ flex:1 }}>{value}</span>
      {select && <span style={{ color:LM.inkMuted }}>▾</span>}
    </div>
  </div>
);

// ── Permissions: what the AI can do without asking
const LM_PERMISSIONS = [
  { id:'read',  label:'Read host data',           sub:'List walls, doors, views, etc.', mode:'auto' },
  { id:'filter',label:'Filter & search',          sub:'No side effects.',                mode:'auto' },
  { id:'dim',   label:'Place dimensions & tags',  sub:'Annotation only · no model change.', mode:'auto' },
  { id:'place', label:'Place new elements',       sub:'Doors, windows, walls.',           mode:'ask' },
  { id:'param', label:'Edit parameter values',    sub:'On selected elements.',            mode:'ask' },
  { id:'delete',label:'Delete elements',          sub:'Irreversible without undo.',       mode:'block' },
  { id:'pub',   label:'Publish / export',         sub:'PDF, Speckle, email.',             mode:'ask' },
  { id:'shell', label:'Run shell / scripts',      sub:'pyrevit, IronPython, system.',     mode:'block' },
];
const PERM_META = {
  auto:  { col:LM.ok,     label:'AUTO',  note:'Runs without asking' },
  ask:   { col:LM.warn,   label:'ASK',   note:'Pauses for confirmation' },
  block: { col:LM.err,    label:'BLOCK', note:'Never run' },
};
const SettingsPermissions = ({ store, patch }) => (
  <div>
    <SHead title="Permissions" sub="What the AI can do on its own — and what it must pause to ask. Keeps the gas pedal under your foot."/>
    <div style={{ background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg, overflow:'hidden' }}>
      {LM_PERMISSIONS.map((p, i) => {
        const mode = permMode(store, p);
        const meta = PERM_META[mode];
        return (
          <div key={p.id} style={{
            padding:'10px 14px', display:'grid', gridTemplateColumns:'1fr 240px',
            gap:14, alignItems:'center',
            borderTop: i===0 ? 'none' : `1px solid ${LM.lineSoft}`,
          }}>
            <div style={{ minWidth:0 }}>
              <div style={{ fontSize:13, fontWeight:500, color:LM.ink }}>{p.label}</div>
              <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, marginTop:2, letterSpacing:'0.04em' }}>{p.sub}</div>
            </div>
            <div style={{ display:'flex', gap:LM.sp.xs, background:LM.bgDeep, padding:2, borderRadius:LM.rad.sm }}>
              {Object.entries(PERM_META).map(([k, m]) => {
                const sel = mode === k;
                return (
                  <button key={k} title={m.label + ' \u2014 ' + p.label}
                    onClick={() => patch({ perms: Object.assign({}, store.perms, { [p.id]: k }) })}
                    style={{
                    flex:1, padding:'4px 6px', border:0, borderRadius:4, cursor:'pointer',
                    background: sel ? m.col + '22' : 'transparent',
                    color: sel ? m.col : LM.inkMuted,
                    fontFamily:LM.mono, fontSize:9.5, fontWeight: sel ? 600 : 400, letterSpacing:'0.1em',
                  }}>{m.label}</button>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
    <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, marginTop:10, letterSpacing:'0.04em', lineHeight:1.6 }}>
      Default for new permissions: <span style={{ color:LM.warn }}>ASK</span>. Cost ceiling per session: <span style={{ color:LM.accent }}>$2.00</span>. Auto-undo window: <span style={{ color:LM.accent }}>30s</span>.
    </div>
  </div>
);

// ── Providers
const LM_PROVIDERS = [
  { id:'anthropic', name:'Anthropic',  state:'connected', key:'ant-•••••••••e2af', usage:'$23.84 this month', col:'#cc785c' },
  { id:'openai',    name:'OpenAI',     state:'connected', key:'sk-••••••••••8e1b', usage:'$0.00 (subscription)', col:'#10a37f' },
  { id:'openrouter',name:'OpenRouter', state:'connected', key:'or-••••••••••9c4d', usage:'$2.14 this month', col:'#3a6acc' },
  { id:'ollama',    name:'Ollama',     state:'local',     key:'localhost:11434',  usage:'free · local',     col:'#1a8a4a' },
  { id:'google',    name:'Google AI',  state:'off',       key:'—',                usage:'—',                col:'#4285f4' },
];
const SettingsProviders = ({ store, patch }) => (
  <div>
    <SHead title="Providers" sub="BYO keys. Local models live in Ollama. Spend rolls up into Storage."/>
    <div style={{ background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg, overflow:'hidden' }}>
      {LM_PROVIDERS.map((p, i) => (
        <div key={p.id} style={{
          padding:'12px 14px', display:'flex', alignItems:'center', gap:LM.sp.md,
          borderTop: i===0 ? 'none' : `1px solid ${LM.lineSoft}`,
        }}>
          <span style={{ width:24, height:24, borderRadius:LM.rad.sm, background:p.col, color: (window.AH && window.AH.onFill) || '#180f08', display:'grid', placeItems:'center', fontFamily:LM.mono, fontSize:12, fontWeight:700 }}>{p.name[0]}</span>
          <div style={{ flex:1, minWidth:0, lineHeight:1.2 }}>
            <div style={{ fontSize:13, fontWeight:500, color: p.state==='off' ? LM.inkMuted : LM.ink }}>{p.name}</div>
            <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, marginTop:2, letterSpacing:'0.04em' }}>
              <button title={(store.revealed || {})[p.id] ? 'Hide key' : 'Reveal key'}
                onClick={() => patch({ revealed: Object.assign({}, store.revealed, { [p.id]: !(store.revealed || {})[p.id] }) })}
                style={{ background:'none', border:0, padding:0, cursor:'pointer', color:LM.inkSoft, fontFamily:LM.mono, fontSize:10, textDecoration:'underline dotted' }}>
                {(store.revealed || {})[p.id] ? p.key.replace(/\u2022+/g, 'k7Fq2xBn91LmZ0aTvR') : p.key}
              </button> · {p.usage}
            </div>
          </div>
          <span style={{
            fontFamily:LM.mono, fontSize:9, padding:'2px 7px', borderRadius:LM.rad.xs, letterSpacing:'0.1em', textTransform:'uppercase',
            background: p.state==='connected'?LM.ok+'14' : p.state==='local'?LM.cyan+'14' : LM.bgSoft,
            color:       p.state==='connected'?LM.ok      : p.state==='local'?LM.cyan      : LM.inkMuted,
          }}>{p.state}</span>
          <button onClick={() => window.ARCHHUB_REVEAL?.('brain')}
            title="Provider keys live in the OS keychain, beside the brain"
            style={{ ...smallBtn(), padding:'3px 8px' }}>{p.state==='off' ? 'connect' : 'manage'}</button>
        </div>
      ))}
    </div>
  </div>
);

// ── Models: per-task routing
const SettingsModels = () => (
  <div>
    <SHead title="Model routing" sub="Different jobs deserve different models. We pick by default, you can override."/>
    {[
      ['Reasoning · planning',     'Claude Sonnet 4.5',     'Anthropic · $3 / $15 per M'],
      ['Vision · sketch parsing',  'Claude Sonnet 4.5',     'Anthropic · vision-on'],
      ['Long context (>100k)',     'Gemini 2.5 Pro',        'Google · $2.50 / $10 per M'],
      ['Fast bulk · drafts',       'Claude Haiku 4.5',      'Anthropic · $0.80 / $4 per M'],
      ['Embedding · skill search', 'text-embed-3-large',    'OpenAI · $0.13 per M'],
      ['Local fallback (offline)', 'qwen2.5-coder:32b',     'Ollama · free'],
    ].map(([task, model, sub], i) => (
      <div key={i} style={{
        display:'grid', gridTemplateColumns:'1fr 1fr', gap:14, alignItems:'center',
        padding:'10px 12px', background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.md, marginBottom:6,
      }}>
        <div>
          <div style={{ fontSize:13, fontWeight:500 }}>{task}</div>
          <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, marginTop:2, letterSpacing:'0.04em' }}>{sub}</div>
        </div>
        <button style={{
          padding:'7px 11px', background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.sm,
          color:LM.ink, fontFamily:LM.mono, fontSize:11.5, textAlign:'left', cursor:'pointer',
          display:'flex', alignItems:'center', gap:6,
        }}>
          <span style={{ flex:1 }}>{model}</span>
          <span style={{ color:LM.inkMuted }}>▾</span>
        </button>
      </div>
    ))}
  </div>
);

// ── Theme / Shortcuts / Storage / About (lighter, but real)
const SettingsTheme = ({ store, patch }) => (
  <div>
    <SHead title="Theme" sub="Honest dark for honest drafting. Light when you need to share a screen."/>
    <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:10 }}>
      {[
        ['System',  'follows OS', '#0e0e11', '#fbfbf9'],
        ['Dark',    'studio default', '#0e0e11', null],
        ['Light',   'high contrast',  null, '#f7f4ee'],
      ].map(([name, sub, dark, light]) => (
        <button key={name} onClick={() => patch('theme', name)} style={{
          padding:'12px 14px', background:LM.bg, border:`1px solid ${name===store.theme?LM.accent:LM.line}`,
          borderRadius:7, textAlign:'left', cursor:'pointer', color:LM.ink, fontFamily:LM.sans,
        }}>
          <div style={{ display:'flex', gap:LM.sp.xs, marginBottom:LM.sp.sm }}>
            {dark && <div style={{ flex:1, height:36, background:dark, borderRadius:4, border:`1px solid ${LM.lineSoft}` }}/>}
            {light && <div style={{ flex:1, height:36, background:light, borderRadius:4, border:`1px solid ${LM.lineSoft}` }}/>}
          </div>
          <div style={{ fontSize:13, fontWeight:500 }}>{name}</div>
          <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, marginTop:2 }}>{sub}</div>
        </button>
      ))}
    </div>
    <div style={{ marginTop:LM.sp.lg, display:'flex', flexDirection:'column', gap:10 }}>
      {[
        ['Accent color',  'oklch — same chroma · pick a hue', '#d97757'],
        ['Editor font',   'JetBrains Mono · 13px'],
        ['Display font',  'Instrument Serif · Inter for UI'],
        ['Density',       'Comfortable'],
      ].map(([k, v, c], i) => (
        <div key={i} style={{ display:'flex', alignItems:'center', gap:10, padding:'8px 12px', background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.md }}>
          {c && <span style={{ width:16, height:16, borderRadius:4, background:c, border:`1px solid ${LM.lineSoft}` }}/>}
          <div style={{ flex:1 }}>
            <div style={{ fontSize:12.5 }}>{k}</div>
            <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, marginTop:1, letterSpacing:'0.04em' }}>{v}</div>
          </div>
          <span style={{ color:LM.inkMuted, fontSize:11 }}>change</span>
        </div>
      ))}
    </div>
  </div>
);

const SettingsShortcuts = () => (
  <div>
    <SHead title="Shortcuts" sub="The keys that matter."/>
    <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'4px 24px' }}>
      {[
        ['Open palette',          '⌘K'],
        ['New session',           '⌘N'],
        ['Run focused node',      '⌘↵'],
        ['Add node — library',    '⌘L'],
        ['Toggle settings',       '⌘,'],
        ['Open documentation',    '⌘/'],
        ['Pan canvas',            'drag empty'],
        ['Zoom canvas',           '⌘ + scroll'],
        ['Fit to view',           '⌘0'],
        ['Branch from message',   '⌥B'],
        ['Save as Skill',         '⌘⇧S'],
        ['Switch model',          '⌘M'],
        ['Toggle reasoning',      '⌥R'],
      ].map(([label, key]) => (
        <div key={label} style={{ display:'flex', alignItems:'center', gap:10, padding:'7px 0', borderBottom:`1px solid ${LM.lineSoft}` }}>
          <span style={{ flex:1, fontSize:12.5, color:LM.ink }}>{label}</span>
          <kbd style={{ ...kbd(), fontSize:10.5, padding:'2px 7px' }}>{key}</kbd>
        </div>
      ))}
    </div>
  </div>
);

const SettingsStorage = () => (
  <div>
    <SHead title="Storage" sub="Sessions, training queue, cache. Everything is local first."/>
    <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:10, marginBottom:14 }}>
      {[
        ['Sessions', '14', '2.1 GB'],
        ['Training queue', '42', '186 MB'],
        ['Model cache', '3', '5.4 GB'],
      ].map(([k, n, sz]) => (
        <div key={k} style={{ padding:'12px 14px', background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:7 }}>
          <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.14em' }}>{k.toUpperCase()}</div>
          <div style={{ fontFamily:LM.serif, fontSize:26, letterSpacing:'-0.02em', marginTop:2 }}>{n}</div>
          <div style={{ fontFamily:LM.mono, fontSize:10.5, color:LM.inkSoft, marginTop:1 }}>{sz}</div>
        </div>
      ))}
    </div>
    <div style={{ display:'flex', flexDirection:'column', gap:6 }}>
      {[
        ['Export everything',           'JSON · sessions, memory, profile, skills', LM.ink],
        ['Clear cache (5.4 GB)',        'safe — model weights re-download on demand', LM.inkSoft],
        ['Forget all memory',           'irreversible · profile stays', LM.err],
        ['Delete all sessions',         'irreversible · training queue stays', LM.err],
      ].map(([t, sub, col]) => (
        <div key={t} style={{ display:'flex', alignItems:'center', gap:10, padding:'10px 12px', background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.md }}>
          <div style={{ flex:1 }}>
            <div style={{ fontSize:13, color }}>{t}</div>
            <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, marginTop:2 }}>{sub}</div>
          </div>
          <button onClick={(e) => {
            // Irreversible acts are never one click away from a list.
            const b = e.currentTarget;
            b.textContent = 'opening the folder';
            window.ARCHHUB_REVEAL?.(t.indexOf('session') >= 0 ? 'graph' : 'brain');
            setTimeout(() => { b.textContent = 'do it'; }, 5000);
          }} style={{ ...smallBtn(), color, borderColor: col === LM.err ? LM.err + '55' : LM.line }}>do it</button>
        </div>
      ))}
    </div>
  </div>
);

const SettingsAbout = () => (
  <div>
    <SHead title="About" sub="ArchHub Studio · the AEC stack with one foot in your model and one in the LLM."/>
    <div style={{ background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg, padding:'14px 16px', fontFamily:LM.mono, fontSize:11.5, color:LM.inkSoft, lineHeight:1.85 }}>
      <div><span style={{ color:LM.inkMuted }}>version    </span> 1.4.0-prototype</div>
      <div><span style={{ color:LM.inkMuted }}>license    </span> proprietary · Habib Studio</div>
      <div><span style={{ color:LM.inkMuted }}>server     </span> localhost:7300 · running</div>
      <div><span style={{ color:LM.inkMuted }}>hosts      </span> {LM_HOSTS.length} configured · {LM_HOSTS.filter(h=>h.state!=='off').length} live</div>
      <div><span style={{ color:LM.inkMuted }}>providers  </span> Anthropic, OpenAI, OpenRouter, Ollama</div>
      <div><span style={{ color:LM.inkMuted }}>updated    </span> 2 days ago · changelog →</div>
    </div>
  </div>
);

const SettingsHosts = ({ store, patch }) => (
  <div style={{ display:'flex', flexDirection:'column', gap:14 }}>
    <div>
      <div style={{ fontFamily:LM.serif, fontSize:22, letterSpacing:'-0.01em' }}>Hosts</div>
      <div style={{ fontFamily:LM.sans, fontSize:13, color:LM.inkSoft, marginTop:3 }}>
        Local clients ArchHub connects to. Toggle off to remove from the graph.
      </div>
    </div>
    <div style={{ background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg, overflow:'hidden' }}>
      {LM_HOSTS.map((h, i) => {
        const state = hostState(store, h);
        const col = state==='connected'?LM.ok : state==='syncing'?LM.warn : LM.inkMuted;
        return (
          <div key={h.id} style={{
            padding:'10px 14px', display:'flex', alignItems:'center', gap:LM.sp.md,
            borderTop: i===0 ? 'none' : `1px solid ${LM.lineSoft}`,
          }}>
            <span style={{
              width:8, height:8, borderRadius:'50%', background: col,
              boxShadow: state==='connected'?`0 0 0 2px ${LM.ok}22`:'none',
              animation: state==='syncing'?'lmPulse 1.2s infinite':'none',
            }}/>
            <div style={{ flex:1, lineHeight:1.2, minWidth:0 }}>
              <div style={{ fontSize:13, fontWeight:500, color: state==='off' ? LM.inkMuted : LM.ink }}>{h.name}</div>
              <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, letterSpacing:'0.04em', marginTop:2 }}>
                {h.port ? `localhost:${h.port}` : '—'} · {h.file}
              </div>
            </div>
            <span style={{
              fontFamily:LM.mono, fontSize:9, padding:'2px 7px', borderRadius:LM.rad.xs,
              background: col + '14', color: col, letterSpacing:'0.1em', textTransform:'uppercase',
            }}>{state}</span>
            <div role="switch" aria-checked={state !== 'off'}
              title={(state !== 'off' ? 'Disconnect ' : 'Connect ') + h.name}
              onClick={() => patch({ hosts: Object.assign({}, store.hosts, { [h.name]: state === 'off' ? (h.state === 'off' ? 'connected' : h.state) : 'off' }) })}
              style={{
              width:30, height:16, borderRadius:999, padding:1, position:'relative', cursor:'pointer',
              transition:'background .15s',
              background: state !== 'off' ? LM.accent : LM.lineSoft,
            }}>
              <span style={{ position:'absolute', top:1, transition:'left .15s', left: state !== 'off' ? 14 : 1, width:14, height:14, borderRadius:'50%', background:'#fff', transition:'left .15s' }}/>
            </div>
          </div>
        );
      })}
    </div>
    <button style={{
      padding:'8px 12px', border:`1px dashed ${LM.line}`, background:'transparent',
      borderRadius:LM.rad.md, color:LM.accent, fontFamily:LM.sans, fontSize:12.5, cursor:'pointer',
      display:'inline-flex', alignItems:'center', gap:7, width:'fit-content',
    }}>
      <span>+</span> Auto-build a new host connector…
    </button>
  </div>
);

// ──────────────────────── MODEL PICKER ────────────────────────
const ModelPicker = ({ setModel, onClose, model }) => {
  const groups = [
    { name:'CLOUD · subscription', items:[
      { name:'Claude Sonnet 4.5', route:'anthropic/claude-sonnet-4.5', vendor:'Anthropic', tag:'CLOUD', ctx:'200k', col:'#cc785c', cost:'$3 / $15 per M', latency:412 },
      { name:'Claude Opus 4.1',   route:'anthropic/claude-opus-4.1',   vendor:'Anthropic', tag:'CLOUD', ctx:'200k', col:'#cc785c', cost:'$15 / $75 per M', latency:820 },
      { name:'GPT-4o',            route:'openai/gpt-4o',               vendor:'OpenAI',    tag:'CLOUD', ctx:'128k', col:'#10a37f', cost:'$5 / $20 per M', latency:530 },
    ]},
    { name:'BYO · OpenRouter', items:[
      { name:'DeepSeek R1', route:'deepseek/deepseek-r1', vendor:'OpenRouter', tag:'BYO', ctx:'128k', col:'#3a6acc', cost:'$0.55 / $2.20', latency:1450 },
      { name:'Llama 3.3 70B', route:'meta-llama/llama-3.3-70b-instruct', vendor:'OpenRouter', tag:'BYO', ctx:'128k', col:'#3a6acc', cost:'$0.12 / $0.30', latency:900 },
    ]},
  ];
  return (
    <div onClick={onClose} style={{
      position:'absolute', inset:0, background:'rgba(0,0,0,.55)',
      display:'grid', placeItems:'start center', paddingTop:60, zIndex:50,
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        width:600, maxWidth:'92%', background:LM.bgPanel, border:`1px solid ${LM.line}`,
        borderRadius:LM.rad.xl, overflow:'hidden', boxShadow:'0 30px 80px rgba(0,0,0,.6)',
      }}>
        <div style={{ padding:'12px 14px', borderBottom:`1px solid ${LM.line}`, display:'flex', alignItems:'center', gap:10 }}>
          <span style={{ fontSize:14 }}>⌕</span>
          <input autoFocus placeholder="Search models or paste an OpenRouter id…" style={{
            flex:1, border:0, background:'transparent', color:LM.ink, fontSize:13.5, outline:'none', fontFamily:LM.sans,
          }}/>
          <kbd style={kbd()}>esc</kbd>
        </div>
        <div className="ah-scroll" style={{ maxHeight:420, overflow:'auto', padding:'6px 8px 10px' }}>
          {groups.map(g => (
            <div key={g.name} style={{ marginTop:LM.sp.sm }}>
              <div style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.18em', padding:'4px 10px' }}>{g.name}</div>
              {g.items.map(m => {
                const sel = m.name === model.name;
                return (
                  <div key={m.name} onClick={() => { setModel(m); onClose(); }} style={{
                    display:'flex', alignItems:'center', gap:10, padding:'8px 10px', borderRadius:LM.rad.md, cursor:'pointer',
                    background: sel ? LM.bgSoft : 'transparent',
                  }}
                  onMouseEnter={e => !sel && (e.currentTarget.style.background = LM.bgHover)}
                  onMouseLeave={e => !sel && (e.currentTarget.style.background = 'transparent')}>
                    <span style={{ width:22, height:22, borderRadius:4, background:m.col, color:((window.AH && window.AH.onFill) || '#180f08'), display:'grid', placeItems:'center', fontFamily:LM.mono, fontSize:11, fontWeight:700 }}>{m.name[0]}</span>
                    <div style={{ flex:1, lineHeight:1.15 }}>
                      <div style={{ fontSize:13 }}>{m.name}</div>
                      <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.04em' }}>{m.vendor} · ctx {m.ctx} · {m.cost}</div>
                    </div>
                    <span style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.ok }}>{m.latency}ms</span>
                    <span style={{
                      fontFamily:LM.mono, fontSize:9, padding:'2px 7px', borderRadius:LM.rad.xs, letterSpacing:'0.08em',
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

// ──────────────────────── DOCS ────────────────────────
// Lives INSIDE the app shell — same overlay geometry, nav width and type scale as Settings,
// so this is the screen the end user actually gets, only the content differs.
const dCode = { fontFamily:LM.mono, fontSize:11.5, lineHeight:1.65, background:LM.bgDeep, border:`1px solid ${LM.lineSoft}`, borderRadius:LM.rad.sm, padding:'11px 13px', color:LM.inkSoft, overflowX:'auto', whiteSpace:'pre', margin:'0 0 14px' };
const DP = ({ children }) => <p style={{ fontFamily:LM.sans, fontSize:13.5, lineHeight:1.65, color:LM.inkSoft, margin:'0 0 13px', textWrap:'pretty' }}>{children}</p>;
const DSub = ({ children }) => <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.18em', margin:'22px 0 10px' }}>{children}</div>;
const DCode = ({ children }) => <pre style={dCode}>{children}</pre>;
const DKey = ({ children }) => <span style={{ fontFamily:LM.mono, fontSize:11, background:LM.bgSoft, border:`1px solid ${LM.line}`, borderRadius:4, padding:'1px 5px', color:LM.ink }}>{children}</span>;
const DNote = ({ children }) => (
  <div style={{ display:'flex', gap:9, background:LM.bgSoft, border:`1px solid ${LM.line}`, borderLeft:`2px solid ${LM.accent}`, borderRadius:LM.rad.sm, padding:'10px 12px', margin:'0 0 14px' }}>
    <span style={{ fontFamily:LM.mono, fontSize:9, color:LM.accent, letterSpacing:'0.14em', flexShrink:0, marginTop:2 }}>NOTE</span>
    <span style={{ fontFamily:LM.sans, fontSize:12.5, lineHeight:1.55, color:LM.inkSoft }}>{children}</span>
  </div>
);
const DRows = ({ rows }) => (
  <div style={{ display:'flex', flexDirection:'column', border:`1px solid ${LM.line}`, borderRadius:LM.rad.sm, overflow:'hidden', margin:'0 0 14px' }}>
    {rows.map((r, i) => (
      <div key={r[0]} style={{ display:'grid', gridTemplateColumns:'170px 1fr', gap:12, padding:'9px 12px', borderTop: i ? `1px solid ${LM.lineSoft}` : 'none', background: i % 2 ? 'transparent' : LM.bgDeep }}>
        <span style={{ fontFamily:LM.mono, fontSize:11, color:LM.ink }}>{r[0]}</span>
        <span style={{ fontFamily:LM.sans, fontSize:12.5, color:LM.inkSoft, lineHeight:1.5 }}>{r[1]}</span>
      </div>
    ))}
  </div>
);

const DOC_INDEX = [{"s":"start","k":"page","t":"Getting started","d":"ArchHub runs as a local server next to your CAD/BIM host. Nothing leaves your machine unless a node asks it to."},{"s":"canvas","k":"page","t":"The canvas & nodes","d":"A node takes typed inputs, does one job, and emits typed outputs. The canvas is the record of how they connect."},{"s":"connectors","k":"page","t":"Connectors","d":"A connector is a long-lived link to a running application. It is the only thing in ArchHub that can read or write your model."},{"s":"skills","k":"page","t":"Skills as JSON you own","d":"A skill is a saved group of nodes, serialised as plain JSON in your project. No proprietary format, no lock-in, no hidden state."},{"s":"brain","k":"page","t":"The Brain & memory layers","d":"The Brain is what makes the second session smarter than the first. It is a local store, not a cloud profile."},{"s":"healing","k":"page","t":"Self-healing internals","d":"A graph that stops the moment a host hiccups is not usable in practice. Self-healing is the loop that keeps a long run alive."},{"s":"cli","k":"page","t":"CLI & API reference","d":"Everything Studio does, the CLI does. The UI is a client of the same local server."},{"s":"start","k":"section","t":"INSTALL","d":"Getting started"},{"s":"start","k":"section","t":"FIRST RUN","d":"Getting started"},{"s":"start","k":"section","t":"KEYS","d":"Getting started"},{"s":"canvas","k":"section","t":"THE NINE CATEGORIES","d":"The canvas & nodes"},{"s":"canvas","k":"section","t":"WIRES ARE TYPED","d":"The canvas & nodes"},{"s":"canvas","k":"section","t":"GROUPING","d":"The canvas & nodes"},{"s":"canvas","k":"section","t":"NAVIGATION","d":"The canvas & nodes"},{"s":"connectors","k":"section","t":"SUPPORTED HOSTS","d":"Connectors"},{"s":"connectors","k":"section","t":"LIFECYCLE","d":"Connectors"},{"s":"skills","k":"section","t":"SHAPE","d":"Skills as JSON you own"},{"s":"skills","k":"section","t":"RULES","d":"Skills as JSON you own"},{"s":"brain","k":"section","t":"THE FOUR LAYERS","d":"The Brain & memory layers"},{"s":"brain","k":"section","t":"PROMOTION","d":"The Brain & memory layers"},{"s":"healing","k":"section","t":"THE LOOP","d":"Self-healing internals"},{"s":"healing","k":"section","t":"REPAIR STRATEGIES","d":"Self-healing internals"},{"s":"healing","k":"section","t":"GUARANTEES","d":"Self-healing internals"},{"s":"cli","k":"section","t":"CLI","d":"CLI & API reference"},{"s":"cli","k":"section","t":"HTTP","d":"CLI & API reference"},{"s":"cli","k":"section","t":"EXIT CODES","d":"CLI & API reference"},{"s":"start","k":"key","t":"⌘K","d":"Getting started"},{"s":"start","k":"key","t":"⌘L","d":"Getting started"},{"s":"start","k":"key","t":"⌘↵","d":"Getting started"},{"s":"start","k":"key","t":"⌘,","d":"Getting started"},{"s":"start","k":"key","t":"⌘/","d":"Getting started"},{"s":"start","k":"cli","t":"archhub up","d":"Getting started"},{"s":"start","k":"cli","t":"archhub doctor","d":"Getting started"},{"s":"cli","k":"cli","t":"archhub up","d":"CLI & API reference"},{"s":"cli","k":"cli","t":"archhub doctor","d":"CLI & API reference"},{"s":"cli","k":"cli","t":"archhub run","d":"CLI & API reference"},{"s":"cli","k":"cli","t":"archhub skill","d":"CLI & API reference"},{"s":"cli","k":"cli","t":"archhub brain","d":"CLI & API reference"},{"s":"cli","k":"cli","t":"archhub hosts","d":"CLI & API reference"},{"s":"cli","k":"cli","t":"archhub logs","d":"CLI & API reference"},{"s":"start","k":"topic","t":"1 · Connect a host","d":"Getting started"},{"s":"start","k":"topic","t":"2 · Add a provider","d":"Getting started"},{"s":"start","k":"topic","t":"3 · Open a session","d":"Getting started"},{"s":"start","k":"topic","t":"4 · Place a node","d":"Getting started"},{"s":"canvas","k":"topic","t":"Hosts","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"Read","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"Filter","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"Transform","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"Annotate","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"Compose","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"Logic","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"AI","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"Output","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"Pan","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"Zoom","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"Focus a node","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"Multi-select","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"Run","d":"The canvas & nodes"},{"s":"connectors","k":"topic","t":"Revit 2022–2025","d":"Connectors"},{"s":"connectors","k":"topic","t":"Rhino 7 / 8","d":"Connectors"},{"s":"connectors","k":"topic","t":"Blender 4.x / 5.x","d":"Connectors"},{"s":"connectors","k":"topic","t":"Speckle","d":"Connectors"},{"s":"connectors","k":"topic","t":"IFC 2x3 / 4","d":"Connectors"},{"s":"skills","k":"topic","t":"inputs / outputs","d":"Skills as JSON you own"},{"s":"skills","k":"topic","t":"params","d":"Skills as JSON you own"},{"s":"skills","k":"topic","t":"requires","d":"Skills as JSON you own"},{"s":"skills","k":"topic","t":"version","d":"Skills as JSON you own"},{"s":"skills","k":"topic","t":"dry_run","d":"Skills as JSON you own"},{"s":"brain","k":"topic","t":"1 · Session","d":"The Brain & memory layers"},{"s":"brain","k":"topic","t":"2 · Project","d":"The Brain & memory layers"},{"s":"brain","k":"topic","t":"3 · Practice","d":"The Brain & memory layers"},{"s":"brain","k":"topic","t":"4 · Personal","d":"The Brain & memory layers"},{"s":"healing","k":"topic","t":"transport","d":"Self-healing internals"},{"s":"healing","k":"topic","t":"version drift","d":"Self-healing internals"},{"s":"healing","k":"topic","t":"auth","d":"Self-healing internals"},{"s":"healing","k":"topic","t":"host busy","d":"Self-healing internals"},{"s":"healing","k":"topic","t":"crash","d":"Self-healing internals"},{"s":"cli","k":"topic","t":"archhub run <session>","d":"CLI & API reference"},{"s":"cli","k":"topic","t":"archhub skill ls | add | rm","d":"CLI & API reference"},{"s":"cli","k":"topic","t":"archhub brain ls | promote | forget","d":"CLI & API reference"},{"s":"cli","k":"topic","t":"archhub logs -f","d":"CLI & API reference"}]

const DOC_SECTIONS = [
  ['start',      'Getting started', 'install'],
  ['canvas',     'Canvas & nodes',  '9 categories'],
  ['connectors', 'Connectors',      '4 hosts'],
  ['skills',     'Skills as JSON',  'you own them'],
  ['brain',      'Brain & memory',  '4 layers'],
  ['healing',    'Self-healing',    'internals'],
  ['cli',        'CLI & API',       'reference'],
];

const DOC_KIND = { page:'PAGE', section:'SECTION', topic:'TOPIC', key:'KEY', cli:'CLI' };

const Docs = ({ onClose }) => {
  const [sec, setSec] = React.useState('start');
  // SEARCH — docs without search get painful the moment they grow. DOC_INDEX is generated
  // from the rendered content (headings, row labels, keys, CLI commands), so a hit always
  // corresponds to something the reader will actually find on the page it opens.
  const [q, setQ] = React.useState('');
  const [cur, setCur] = React.useState(0);
  const inputRef = React.useRef(null);
  const hits = React.useMemo(() => {
    const s0 = q.trim().toLowerCase();
    if (!s0) return [];
    const score = (e) => {
      const t = e.t.toLowerCase(), d = (e.d || '').toLowerCase();
      if (t === s0) return 0;
      if (t.indexOf(s0) === 0) return 1;
      if (t.indexOf(s0) > 0) return 2;
      if (d.indexOf(s0) >= 0) return 3;
      return -1;
    };
    return DOC_INDEX.map(e => ({ e, r: score(e) })).filter(x => x.r >= 0)
      .sort((a, b) => a.r - b.r || a.e.t.length - b.e.t.length).slice(0, 9).map(x => x.e);
  }, [q]);
  React.useEffect(() => setCur(0), [q]);
  const jump = (h) => { if (!h) return; setSec(h.s); setQ(''); };
  const onKey = (e) => {
    if (!hits.length) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); setCur(c => (c + 1) % hits.length); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setCur(c => (c - 1 + hits.length) % hits.length); }
    else if (e.key === 'Enter') { e.preventDefault(); jump(hits[cur]); }
    else if (e.key === 'Escape') { e.preventDefault(); setQ(''); }
  };
  React.useEffect(() => { const t = setTimeout(() => inputRef.current && inputRef.current.focus(), 60); return () => clearTimeout(t); }, []);
  return (
    <div onClick={onClose} style={{ position:'absolute', inset:0, background:'rgba(0,0,0,.5)', zIndex:60, display:'grid', placeItems:'center' }}>
      <div onClick={e => e.stopPropagation()} style={{
        width:1000, maxWidth:'95%', height:620, maxHeight:'90%',
        background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:LM.rad.xl,
        overflow:'hidden', boxShadow:'0 30px 80px rgba(0,0,0,.6)',
        display:'grid', gridTemplateColumns:'208px 1fr', gridTemplateRows:'46px 1fr',
      }}>
        <div style={{ gridColumn:'1 / -1', gridRow:'1', borderBottom:`1px solid ${LM.line}`, display:'flex', alignItems:'center', gap:10, padding:'0 16px' }}>
          <span style={{ fontFamily:LM.serif, fontSize:18, letterSpacing:'-0.01em' }}>Documentation</span>
          <span style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, letterSpacing:'0.1em' }}>STUDIO · v1.4</span>
          <div style={{ flex:1 }}/>
          <div style={{ position:'relative', width:260 }}>
            <input ref={inputRef} value={q} onChange={e => setQ(e.target.value)} onKeyDown={onKey}
              placeholder="Search the docs…" style={{
                width:'100%', padding:'6px 10px 6px 26px', borderRadius:LM.rad.sm,
                border:`1px solid ${q ? LM.accent : LM.line}`, background:LM.bg, color:LM.ink,
                fontFamily:LM.sans, fontSize:12.5, outline:'none',
              }}/>
            <span style={{ position:'absolute', left:9, top:6, fontSize:11, color:LM.inkMuted, pointerEvents:'none' }}>⌕</span>
            {q && (
              <div className="ah-scroll" style={{
                position:'absolute', top:32, left:0, width:'100%', maxHeight:250, overflow:'auto', zIndex:5,
                background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:LM.rad.md,
                boxShadow:'0 18px 44px rgba(0,0,0,.55)',
              }}>
                {hits.length === 0
                  ? <div style={{ padding:'10px 12px', fontFamily:LM.sans, fontSize:12.5, color:LM.inkSoft }}>
                      No match. Try <b style={{ color:LM.ink }}>wire</b>, <b style={{ color:LM.ink }}>skill</b> or <b style={{ color:LM.ink }}>brain</b>.
                    </div>
                  : hits.map((h, i) => (
                      <button key={h.s + h.k + h.t} onMouseEnter={() => setCur(i)} onClick={() => jump(h)} style={{
                        width:'100%', display:'flex', alignItems:'center', gap:8, padding:'7px 10px',
                        border:0, borderTop: i === 0 ? 'none' : `1px solid ${LM.lineSoft}`,
                        background: i === cur ? LM.bgSoft : 'transparent', cursor:'pointer', textAlign:'left',
                      }}>
                        <span style={{
                          fontFamily:LM.mono, fontSize:8, letterSpacing:'0.1em', flexShrink:0, width:52,
                          color: h.k === 'key' || h.k === 'cli' ? LM.accent : LM.inkMuted,
                        }}>{DOC_KIND[h.k]}</span>
                        <span style={{ flex:1, minWidth:0, fontFamily: h.k === 'cli' || h.k === 'key' ? LM.mono : LM.sans,
                          fontSize:12.5, color:LM.ink, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{h.t}</span>
                        <span style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkSoft, flexShrink:0 }}>{h.d}</span>
                      </button>
                    ))}
                {hits.length > 0 && (
                  <div style={{ padding:'6px 10px', borderTop:`1px solid ${LM.lineSoft}`, fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.08em' }}>
                    ↑↓ MOVE · ↵ OPEN · ESC CLEAR · {hits.length} OF {DOC_INDEX.length} ENTRIES
                  </div>
                )}
              </div>
            )}
          </div>
          <button onClick={onClose} style={{ width:24, height:24, padding:0, border:`1px solid ${LM.line}`, background:'transparent', borderRadius:LM.rad.sm, cursor:'pointer', color:LM.inkSoft, fontSize:12 }}>✕</button>
        </div>
        <div style={{ gridColumn:'1', gridRow:'2', borderRight:`1px solid ${LM.line}`, padding:'10px 8px', overflow:'auto' }}>
          {DOC_SECTIONS.map(([id, label, badge]) => (
            <button key={id} onClick={() => setSec(id)} style={{
              width:'100%', padding:'7px 11px', borderRadius:LM.rad.sm, border:0,
              background: sec === id ? LM.bgSoft : 'transparent',
              color: sec === id ? LM.ink : LM.inkSoft,
              textAlign:'left', cursor:'pointer', fontFamily:LM.sans, fontSize:13,
              display:'flex', alignItems:'center', gap:LM.sp.sm, marginBottom:1,
            }}>
              <span style={{ flex:1 }}>{label}</span>
              {badge && <span style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.04em' }}>{badge}</span>}
            </button>
          ))}
        </div>
        <div className="ah-scroll" style={{ gridColumn:'2', gridRow:'2', overflow:'auto', padding:'20px 24px 24px' }}>
          {sec === 'start'      && <DocsStart/>}
          {sec === 'canvas'     && <DocsCanvas/>}
          {sec === 'connectors' && <DocsConnectors/>}
          {sec === 'skills'     && <DocsSkills/>}
          {sec === 'brain'      && <DocsBrain/>}
          {sec === 'healing'    && <DocsHealing/>}
          {sec === 'cli'        && <DocsAPI/>}
        </div>
      </div>
    </div>
  );
};

const DocsStart = () => (
  <div>
    <SHead title="Getting started" sub="ArchHub runs as a local server next to your CAD/BIM host. Nothing leaves your machine unless a node asks it to."/>
    <DSub>INSTALL</DSub>
    <DCode>{`# macOS / Linux
curl -fsSL https://get.archhub.app | sh

# Windows (PowerShell)
iwr https://get.archhub.app/win | iex

archhub up          # starts the server on :7300
archhub doctor      # checks hosts, keys, ports`}</DCode>
    <DP>The server strip at the bottom of Studio shows the same state <code style={{ fontFamily:LM.mono, fontSize:12 }}>archhub doctor</code> reports: port, live hosts, current model, session spend.</DP>
    <DSub>FIRST RUN</DSub>
    <DRows rows={[
      ['1 · Connect a host', 'Studio scans for Revit, Rhino, Blender and a Speckle token. Anything it finds appears in Settings → Hosts.'],
      ['2 · Add a provider', 'Settings → Providers. Bring your own key, or point at a local Ollama. Keys are stored in the OS keychain, never in a project file.'],
      ['3 · Open a session', 'A session is one canvas plus its chat. Sessions are files — commit them, diff them, share them.'],
      ['4 · Place a node', 'Press ⌘L for the library, or drag from the Nodes panel.'],
    ]}/>
    <DNote>ArchHub is local-first. Sessions, skills and the brain live in <code style={{ fontFamily:LM.mono, fontSize:12 }}>~/.archhub</code>. The only outbound traffic is the model call a node makes, and Settings → Permissions decides whether it needs to ask first.</DNote>
    <DSub>KEYS</DSub>
    <DP><DKey>⌘K</DKey> command palette · <DKey>⌘L</DKey> node library · <DKey>⌘↵</DKey> run focused node · <DKey>⌘,</DKey> settings · <DKey>⌘/</DKey> these docs</DP>
  </div>
);

const DocsCanvas = () => (
  <div>
    <SHead title="The canvas & nodes" sub="A node takes typed inputs, does one job, and emits typed outputs. The canvas is the record of how they connect."/>
    <DP>Every node carries the same anatomy: a title bar you drag, typed input ports on the left, parameters (its cells) in the body, typed output ports on the right, and a status dot. Nothing about a node is special-cased — the same primitive scales from one operation to a whole pipeline.</DP>
    <DSub>THE NINE CATEGORIES</DSub>
    <DRows rows={[
      ['Hosts',     'Live links to Revit, Rhino, Blender, Speckle. The only nodes that touch your model.'],
      ['Read',      'Pull elements, schedules, parameters, views out of a host.'],
      ['Filter',    'Narrow a set — by category, level, phase, parameter value, or a rule.'],
      ['Transform', 'Change geometry or data: move, array, remap, recompute, unit-convert.'],
      ['Annotate',  'Tags, dimensions, keynotes, sheet marks — the drawing layer.'],
      ['Compose',   'Assemble sheets, views, schedules and exports.'],
      ['Logic',     'Branch, gate, loop, assert. Where a graph gets opinions.'],
      ['AI',        'Model calls. Each one names its model, its prompt and its cost.'],
      ['Output',    'Write back to the host, to disk, or to a report.'],
    ]}/>
    <DSub>WIRES ARE TYPED</DSub>
    <DP>A wire carries a signal type — <code style={{ fontFamily:LM.mono, fontSize:12 }}>element · geometry · data · text · number · bool · file · model</code>. Studio refuses a connection whose types can't reconcile, and colors the wire by type so you can read a graph without opening a single node.</DP>
    <DSub>GROUPING</DSub>
    <DP>Select nodes and group them. The group is itself a node: it collapses to one box, exposes the ports its members left unconnected, and can be grouped again. That is the whole compositional rule — there is no second mechanism to learn.</DP>
    <DNote>A saved group is a <b style={{ color:LM.ink }}>skill</b>. A saved canvas is a <b style={{ color:LM.ink }}>workflow</b>. Neither is a new kind of thing — both are nodes you named and kept.</DNote>
    <DSub>NAVIGATION</DSub>
    <DRows rows={[
      ['Pan',           'Drag empty canvas, or hold Space and drag.'],
      ['Zoom',          '⌘ + scroll, or the zoom control in the toolbar.'],
      ['Focus a node',  'Click to select, double-click to open its interior.'],
      ['Multi-select',  'Shift + drag a box · ⌘/Ctrl + click to add.'],
      ['Run',           '⌘↵ runs the focused node and everything it depends on.'],
    ]}/>
  </div>
);

const DocsConnectors = () => (
  <div>
    <SHead title="Connectors" sub="A connector is a long-lived link to a running application. It is the only thing in ArchHub that can read or write your model."/>
    <DP>Connectors run in-process with the host via a thin add-in, and talk to the ArchHub server over a local socket. They report a heartbeat, a schema version, and a capability list — which is how the canvas knows what a Read node can offer before you run it.</DP>
    <DSub>SUPPORTED HOSTS</DSub>
    <DRows rows={[
      ['Revit 2022–2025',  'Elements, types, parameters, schedules, views, sheets. Read + write. Transactions are wrapped and rolled back on failure.'],
      ['Rhino 7 / 8',      'Geometry, layers, blocks, Grasshopper definitions. Read + write.'],
      ['Blender 4.x / 5.x','Meshes, collections, modifiers. Read + write via the ArchHub add-on.'],
      ['Speckle',          'Commits, branches, streams. Read + write; use it to move between hosts without a file exchange.'],
      ['IFC 2x3 / 4',      'File-based read. No live link — an import node, not a connector.'],
    ]}/>
    <DSub>LIFECYCLE</DSub>
    <DCode>{`discover → handshake → capability sync → live
                                    ↓
                          heartbeat every 2s
                                    ↓
                    miss 3 beats → degraded → self-heal`}</DCode>
    <DP>A connector never silently dies. When beats stop, the node turns amber (degraded), the graph pauses at that node instead of failing downstream, and the self-healing loop takes over — see <b style={{ color:LM.ink }}>Self-healing</b>.</DP>
    <DNote>Version drift is the most common failure. A connector reports its host build on every handshake; if the schema it knows and the schema the host offers disagree, ArchHub degrades to the subset both understand rather than guessing.</DNote>
  </div>
);

const DocsSkills = () => (
  <div>
    <SHead title="Skills as JSON you own" sub="A skill is a saved group of nodes, serialised as plain JSON in your project. No proprietary format, no lock-in, no hidden state."/>
    <DP>Skills live in <code style={{ fontFamily:LM.mono, fontSize:12 }}>skills/</code> next to your session files. They are diffable, reviewable in a pull request, and portable between machines. Editing the JSON by hand is a supported workflow, not a hack — Studio reloads a skill the moment its file changes.</DP>
    <DSub>SHAPE</DSub>
    <DCode>{`{
  "id": "tag-unnamed-rooms",
  "title": "Tag unnamed rooms",
  "version": "1.2.0",
  "inputs":  [{ "k": "host",  "type": "model" },
              { "k": "level", "type": "text", "default": "L01" }],
  "outputs": [{ "k": "tagged", "type": "element" },
              { "k": "report", "type": "data" }],
  "params":  [{ "k": "prefix", "type": "text", "v": "RM-" },
              { "k": "dry_run", "type": "bool", "v": true }],
  "nodes":   [ /* the member nodes, same schema as a session */ ],
  "wires":   [ { "a": "read_rooms:out", "b": "filter_unnamed:in" } ],
  "requires": { "host": "revit>=2022", "model": "any" }
}`}</DCode>
    <DSub>RULES</DSub>
    <DRows rows={[
      ['inputs / outputs', 'Derived from member ports left unconnected. Promote a param to a port to expose it.'],
      ['params',           'Cells surfaced on the collapsed node. Defaults live here; overrides live in the session.'],
      ['requires',         'A capability claim. If the host cannot satisfy it, the node reports blocked instead of failing mid-run.'],
      ['version',          'Semver. A session pins the version it was authored against; upgrades are explicit.'],
      ['dry_run',          'Convention, not magic — a skill that writes to a host should offer it.'],
    ]}/>
    <DNote>Because a skill is a node, a skill can contain skills. Nesting is how a firm builds a standard: small verified skills at the bottom, an office-wide workflow at the top.</DNote>
  </div>
);

const DocsBrain = () => (
  <div>
    <SHead title="The Brain & memory layers" sub="The Brain is what makes the second session smarter than the first. It is a local store, not a cloud profile."/>
    <DP>Every layer is inspectable and editable, and every fact carries a source. If you cannot see why the model knows something, it does not belong in the brain.</DP>
    <DSub>THE FOUR LAYERS</DSub>
    <DRows rows={[
      ['1 · Session',  'The live canvas and chat. Discarded unless promoted. Cheapest, most specific.'],
      ['2 · Project',  'Facts true of this building: levels, phases, naming rules, the consultant list. Scoped to the project folder.'],
      ['3 · Practice', 'Facts true of your office: standards, templates, detail libraries, house units. Shared across projects, versioned with the practice repo.'],
      ['4 · Personal', 'Facts true of you: preferred tone, units, shortcuts, what you never want auto-run. Never shared, never synced.'],
    ]}/>
    <DP>A model call assembles context bottom-up — personal, then practice, then project, then session — and stops when the budget is spent. The nearest layer always wins a conflict, so a project override beats an office standard without editing the standard.</DP>
    <DSub>PROMOTION</DSub>
    <DCode>{`session fact  ──promote──▶  project
project fact  ──promote──▶  practice
any fact      ──forget───▶  gone, with an audit line`}</DCode>
    <DP>Promotion is always a deliberate act. Nothing climbs a layer on its own, which is why the brain does not drift.</DP>
    <DNote>The brain is stored locally in <code style={{ fontFamily:LM.mono, fontSize:12 }}>~/.archhub/brain</code> and in your project folder. It is not a git-hosted service and it is not uploaded — sync between machines is your choice of transport.</DNote>
  </div>
);

const DocsHealing = () => (
  <div>
    <SHead title="Self-healing internals" sub="A graph that stops the moment a host hiccups is not usable in practice. Self-healing is the loop that keeps a long run alive."/>
    <DSub>THE LOOP</DSub>
    <DCode>{`detect      miss 3 heartbeats (6s) → mark degraded
quarantine  pause the node, hold its inputs, do NOT fail downstream
diagnose    classify: transport · version drift · auth · host busy · crash
repair      apply the strategy for that class (below)
verify      re-handshake + replay the held inputs
resume      or escalate to the founder after 3 failed attempts`}</DCode>
    <DSub>REPAIR STRATEGIES</DSub>
    <DRows rows={[
      ['transport',      'Reconnect with backoff — 1s, 2s, 4s, 8s. Most drops resolve here.'],
      ['version drift',  'Renegotiate to the schema subset both sides know; log what was given up.'],
      ['auth',           'Refresh the token from the keychain. If it is genuinely expired, escalate — never prompt mid-run.'],
      ['host busy',      'The user is in a modal dialog. Wait, do not retry; retrying is what corrupts transactions.'],
      ['crash',          'Relaunch the add-in, reopen the document read-only, verify, then re-acquire write.'],
    ]}/>
    <DSub>GUARANTEES</DSub>
    <DP>Held inputs are replayed exactly once. A write that was in flight when a host died is rolled back by the host transaction, then replayed — never half-applied. Every attempt writes an audit line with its class, duration and outcome, so a heal is a fact you can read afterwards rather than a claim.</DP>
    <DNote>Escalation is a feature. After three failed repairs the node stops trying and surfaces in the founder view with its full diagnosis attached. Silent infinite retry is the failure mode this design exists to avoid.</DNote>
  </div>
);

const DocsAPI = () => (
  <div>
    <SHead title="CLI & API reference" sub="Everything Studio does, the CLI does. The UI is a client of the same local server."/>
    <DSub>CLI</DSub>
    <DRows rows={[
      ['archhub up',              'Start the server on :7300.'],
      ['archhub doctor',          'Check hosts, providers, ports, brain integrity.'],
      ['archhub run <session>',   'Run a session headless. --node to run one node and its dependencies.'],
      ['archhub skill ls | add | rm', 'Manage skills in the current project.'],
      ['archhub brain ls | promote | forget', 'Inspect and edit memory layers.'],
      ['archhub hosts',           'List connectors with state and host build.'],
      ['archhub logs -f',         'Follow the audit stream, including heal attempts.'],
    ]}/>
    <DSub>HTTP</DSub>
    <DCode>{`GET  /v1/hosts                 → connectors + state
GET  /v1/sessions              → sessions in this project
POST /v1/sessions/:id/run      → { node?: id, dry_run?: bool }
GET  /v1/sessions/:id/events   → SSE: node status, wire traffic, heals
GET  /v1/skills                → installed skills + versions
POST /v1/skills                → install from JSON body or path
GET  /v1/brain?layer=project   → facts with sources
POST /v1/brain/promote         → { id, to: "practice" }`}</DCode>
    <DP>The server binds to localhost only and requires the token printed by <code style={{ fontFamily:LM.mono, fontSize:12 }}>archhub up</code> in an <code style={{ fontFamily:LM.mono, fontSize:12 }}>Authorization: Bearer</code> header. There is no remote mode; if you need one, tunnel it yourself and own that decision.</DP>
    <DSub>EXIT CODES</DSub>
    <DRows rows={[
      ['0', 'Run completed, all nodes green.'],
      ['1', 'Usage or configuration error — nothing ran.'],
      ['2', 'A node reported blocked (unmet requires). Nothing was written.'],
      ['3', 'A run failed after self-healing escalated. Partial writes were rolled back.'],
    ]}/>
  </div>
);

// ──────────────────────── SERVER STRIP ────────────────────────
const ServerStrip = ({ session, model, setSettingsOpen, setDocsOpen }) => {
  const live = (window.ARCHHUB_LIVE?.connectors || []).filter(c => c.state === 'connected' || c.state === 'listening').length;
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
      padding:'0 10px', display:'flex', alignItems:'center', gap:LM.sp.xs,
    }}>
      <StripItem onClick={() => setSettingsOpen && setSettingsOpen(true)}>
        <span style={{ color:LM.ok }}>●</span> server {window.location.host} · {live} host{live === 1 ? '' : 's'} live
      </StripItem>
      {session ? (
        <>
          <span style={{ color:LM.inkDim, padding:'0 2px' }}>·</span>
          <StripItem>{session.file}</StripItem>
          <span style={{ color:LM.inkDim, padding:'0 2px' }}>·</span>
          <StripItem onClick={() => setSettingsOpen && setSettingsOpen(true)}>
            <span style={{ color:LM.inkSoft }}>{model.name.toLowerCase().replace(/\s+/g,'-')}</span>
          </StripItem>
        </>
      ) : (
        <>
          <span style={{ color:LM.inkDim, padding:'0 2px' }}>·</span>
          <StripItem>{LM_SESSIONS.length} sessions · {LM_SESSIONS.filter(s=>s.state==='running').length} running</StripItem>
        </>
      )}
      <div style={{ flex:1 }}/>
      <StripItem onClick={() => setDocsOpen && setDocsOpen(true)}>docs</StripItem>
      <span style={{ color:LM.inkDim, padding:'0 2px' }}>·</span>
      <StripItem onClick={() => setSettingsOpen && setSettingsOpen(true)}>settings</StripItem>
      <span style={{ color:LM.inkDim, padding:'0 2px' }}>·</span>
      <StripItem>v1.4 prototype</StripItem>
    </div>
  );
};

window.StudioLM = StudioLM;

})();
