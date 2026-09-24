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

// Categories and signal colours come from node-registry.jsx - one definition, read by the
// canvas, the node library and the minimap alike.
const CAT = window.AH_CAT;
const WIRE = window.AH_WIRE;

const studioCategory = name => CAT[name] || {col:LM.accent, icon:'○', label:name, role:''};
const useStudioProjection = () => {
  const signed = window.ARCHHUB_STUDIO_AUTHORITY;
  const authority = signed || window.ARCHHUB_EXISTING_WORKSHOP;
  const read = () => signed ? authority.getSnapshot() : authority?.getSnapshot()?.topology || null;
  const [state, setState] = React.useState(read);
  React.useEffect(() => {
    const unsubscribe = authority?.subscribe(() => setState(read()));
    setState(read());
    return unsubscribe;
  }, [authority, signed]);
  return state;
};

// ──────────────────────── DATA ────────────────────────
const useWorkshopProjection = () => {
  const transport = window.ARCHHUB_STUDIO_AUTHORITY || window.ARCHHUB_EXISTING_WORKSHOP;
  const [state, setState] = React.useState(() => transport?.getSnapshot() || null);
  React.useEffect(() => {
    const read = () => setState(transport?.getSnapshot() || null);
    const unsubscribe = transport?.subscribe(read);
    read();
    return unsubscribe;
  }, [transport]);
  return state;
};
const studioCanvasScope = canvas => JSON.stringify([canvas?.graph_id || canvas?.application_root || '',
  canvas?.root || canvas?.scope?.current || '', canvas?.authorization?.subject || '', canvas?.authorization?.session || '']);
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

const LM_HOST_META = window.ArchHubTheme.derive((LM) => ({
  revit:{name:'Revit',col:LM.cyan},     blender:{name:'Blender',col:LM.accent},
  speckle:{name:'Speckle',col:LM.purple}, rhino:{name:'Rhino',col:LM.ok},
  autocad:{name:'AutoCAD',col:LM.err},  outlook:{name:'Outlook',col:LM.blue},
}));
const LM_STATE_META = window.ArchHubTheme.derive((LM) => ({
  idle:     { label:'saved',       col:LM.inkMuted },
  running:  { label:'running',     col:LM.accent, pulse:true },
  done:     { label:'done',        col:LM.ok },
  review:   { label:'needs review',col:LM.warn },
  paused:   { label:'paused',      col:LM.inkMuted },
  workflow: { label:'workflow',    col:LM.purple },
  scheduled:{ label:'scheduled',   col:LM.cyan },
}));

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

// The insertable nodes come from node-registry.jsx - one definition.
const LM_LIBRARY = window.AH_LIBRARY;

// ──────────────────────── ROOT ────────────────────────
const StudioLM = () => {
  React.useSyncExternalStore(window.ArchHubTheme.subscribe, window.ArchHubTheme.getEpoch);
  useCatalogueVersion();
  const [openId, setOpenId] = React.useState(window.ARCHHUB_LIVE?.currentGraph || LM_SESSIONS[0]?.id || null);
  const [openTabs, setOpenTabs] = React.useState(() => [window.ARCHHUB_LIVE?.currentGraph || LM_SESSIONS[0]?.id].filter(Boolean));
  const [model, setModel] = React.useState(noModelPicked);
  const [homeNative, setHomeNative] = React.useState(null);
  const [pickerOpen, setPickerOpen] = React.useState(false);
  React.useEffect(() => {
    const controller = new AbortController();
    const session = window.__archhubSession || {};
    fetch('/api/universal/models', {signal:controller.signal,
      headers:{'X-ArchHub-Session':session.token || '', 'X-ArchHub-CSRF':session.csrf || ''}})
      .then(response => { if (!response.ok) throw new Error('Model selection unavailable'); return response.json(); })
      .then(result => {
        const saved = typeof result.selected_route === 'string' ? result.selected_route.trim() : '';
        // No saved pick: the owner names the model he already configured (settings
        // default_model); with none the Studio keeps asking him to choose one.
        const fallback = !saved && typeof result.default_route === 'string' ? result.default_route.trim() : '';
        const route = saved || fallback;
        if (!route || controller.signal.aborted) return;
        const selected = (result.groups || []).flatMap(group => group.items || [])
          .find(item => (item.routed || item.route) === route);
        setModel(current => current.routed || current.route ? current : selected || {
          name:route, route, routed:route, vendor:fallback ? 'Configured default' : 'Saved selection',
          tag:fallback ? 'settings default_model' : 'Availability not verified',
          ctx:'', col:LM.inkMuted, latency:null});
      }).catch(() => {});
    return () => controller.abort();
  }, []);
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
  // The cloud session on this machine decides signed-in, not a stored flag:
  // boot reads it, sign-out forgets it in the app before the dialog reopens.
  React.useEffect(() => {
    if (!window.ARCHHUB_CLOUD_SESSION) return;
    window.ARCHHUB_CLOUD_SESSION().then(s => {
      const held = acLoad();
      if (!s || s.ok === false) {
        // The app could not say who is signed in; a stored flag is not an
        // identity, so the strip says sign in rather than a stale email.
        if (held.signedIn) { const next = Object.assign({}, held, { signedIn: false }); acSave(next); setAccount(next); }
        return;
      }
      if (s.signed_in && (held.email !== s.email || !held.signedIn)) {
        const next = Object.assign({}, held, { email: s.email, signedIn: true });
        acSave(next); setAccount(next);
      } else if (!s.signed_in && held.signedIn) {
        const next = Object.assign({}, held, { signedIn: false });
        acSave(next); setAccount(next);
      }
    }).catch(() => {});
  }, []);
  const signOut = () => {
    // The app forgets the cloud session first; only then does the studio
    // forget the account. A refusal leaves the founder signed in, honestly.
    const forget = window.ARCHHUB_CLOUD_SIGNOUT ? window.ARCHHUB_CLOUD_SIGNOUT() : Promise.resolve({ ok: true });
    Promise.resolve(forget).then(() => {
      const next = Object.assign({}, account, { signedIn: false, email: '' });
      acSave(next); setAccount(next); setSettingsOpen(false); setSignUpOpen(true);
    }).catch(() => {});
  };
  const [docsOpen, setDocsOpen] = React.useState(false);
  const [libraryOpen, setLibraryOpen] = React.useState(false);
  const [panel, setPanel] = React.useState('nodes'); // chats | nodes | skills | search
  const authorityState = useStudioProjection();
  const [focusId, setLocalFocusId] = React.useState(() =>
    window.ARCHHUB_STUDIO_AUTHORITY?.getSnapshot()?.selected || LM_GRAPH.nodes[0]?.id || null);
  const setFocusId = root => {
    const signed = window.ARCHHUB_STUDIO_AUTHORITY, existing = window.ARCHHUB_EXISTING_WORKSHOP;
    if (root && signed) signed.select(root).catch(() => {});
    else if (root && existing?.selectTopology) existing.selectTopology(root).catch(() => {});
    else setLocalFocusId(root);
  };
  React.useEffect(() => {
    if (authorityState) setLocalFocusId(authorityState.selected);
  }, [authorityState?.selected]);
  const modelTarget = (authorityState?.graph?.nodes || LM_GRAPH.nodes).find(n =>
    n.id === focusId && n.live && nodeModelRow(n)?.editable === true) || null;
  const targetRoute = modelTarget ? nodeModelRoute(modelTarget) : '';
  const displayedModel = modelTarget ? {name:targetRoute || 'Choose a model', route:targetRoute,
    routed:targetRoute, vendor:modelTarget.title, col:LM.inkMuted, latency:null} : model;
  // User-added nodes appear on top of the demo graph
  const [userNodes, setUserNodes] = React.useState([]);
  const session = openId ? LM_SESSIONS.find(s => s.id === openId) : null;
  const workshopState = useWorkshopProjection();
  const viewScope = JSON.stringify([session?.id || '', workshopState?.canvas?.graph_id || '',
    workshopState?.canvas?.root || '',
    (workshopState?.topology?.canvas || workshopState?.canvas)?.authorization?.subject || '',
    (workshopState?.topology?.canvas || workshopState?.canvas)?.authorization?.session || '']);
  // Selection is presentation state. Participants and connection status stay owner projections.
  const [workspaceSelection, setWorkspaceSelection] = React.useState(null);
  const projectedAuthorization = (workshopState?.topology?.canvas || workshopState?.canvas)?.authorization;
  const workspaceReady = !!(session && workshopState?.canvas?.graph_id && workshopState?.canvas?.root &&
    projectedAuthorization?.subject && projectedAuthorization?.session && Array.isArray(workshopState.workshops) &&
    (!workshopState.topology?.canvas || (workshopState.topology.canvas.application_root === workshopState.canvas.graph_id &&
      workshopState.topology.canvas.scope?.current === workshopState.canvas.root)));
  const availableWorkshops = workspaceReady ? workshopState.workshops : [];
  const generalWorkshops = availableWorkshops.filter(row => row.is_general === true && row.root);
  const defaultWorkspaceView = {mode:'chat', conversationRoot:generalWorkshops.length === 1 ?
    generalWorkshops[0].root : '', target:'', notice:'', scope:viewScope, pending:false};
  const resolveWorkspaceView = previous => {
    if (!workspaceReady) return {mode:previous?.mode || 'chat', conversationRoot:'', target:'', pending:true,
      notice:workshopState?.error || workshopState?.topology?.error || 'Loading your workspace…'};
    if (previous?.scope !== viewScope) return defaultWorkspaceView;
    // Empty is an explicit Chat choice, distinct from no selection at startup.
    if (!previous.conversationRoot || availableWorkshops.some(row => row.root === previous.conversationRoot)) {
      return previous;
    }
    return {...defaultWorkspaceView, mode:previous.mode, notice:
      'The selected conversation is no longer available in this scope.'};
  };
  const workspaceView = resolveWorkspaceView(workspaceSelection);
  const updateWorkspaceView = change => setWorkspaceSelection(previous => !workspaceReady ? previous : ({
    ...resolveWorkspaceView(previous), ...change, notice:'', scope:viewScope,
  }));
  const selectedWorkshop = session && workshopState?.workshops?.find(row => row.root === workspaceView.conversationRoot);
  const workshopContext = selectedWorkshop && workspaceView.mode === 'chat' &&
    workshopState?.canvas?.graph_id && workshopState?.canvas?.root ? {
      descriptor:selectedWorkshop, graphId:workshopState.canvas.graph_id, scopeRoot:workshopState.canvas.root,
      transcript:workshopState.workshop, state:workshopState,
    } : null;
  // The workshop selection lives here because both halves read it: the agents rail in the sidebar and
  // the Workshop view (design studio-lm.jsx:270-272). It belongs to one Workshop and resets with it.
  const [workshopSelection, setWorkshopSelection] = React.useState({root:'', agent:null, task:null});
  const wsSel = workshopSelection.root === workspaceView.conversationRoot ? workshopSelection :
    {root:workspaceView.conversationRoot, agent:null, task:null};
  const setWsSel = next => setWorkshopSelection({root:workspaceView.conversationRoot, agent:next.agent ?? null, task:next.task ?? null});

  const nativeConnection = React.useRef(null);
  const connectNativeSession = async row => {
    const owner = window.ARCHHUB_EXISTING_WORKSHOP;
    if (!owner?.bindNativeContact || !window.ARCHHUB_SCOPE_OPEN) {
      throw new Error('Native agent connections are unavailable in this application view.');
    }
    const viewIdentity = () => {
      const snapshot = owner.getSnapshot();
      const authorization = (snapshot?.topology?.canvas || snapshot?.canvas)?.authorization;
      return JSON.stringify([snapshot?.canvas?.graph_id, snapshot?.canvas?.root,
        authorization?.subject, authorization?.session]);
    };
    const startedView = viewIdentity();
    const graph = owner.getSnapshot()?.canvas?.graph_id;
    const identity = JSON.stringify([startedView, row.app, row.session_id]);
    let connected = nativeConnection.current?.identity === identity ? nativeConnection.current.result : null;
    let navigationCurrent = true;
    if (!connected) {
      connected = await owner.bindNativeContact(row);
      navigationCurrent = connected.navigation_current !== false;
      // Once saved, a retry only opens the existing connection.
      nativeConnection.current = {identity,result:connected};
    }
    try {
      if (!navigationCurrent || viewIdentity() !== startedView) {
        throw new Error('Your graph or access changed while connecting; your current view was kept.');
      }
      window.sessionStorage.setItem('archhub.native-contact.selection.v1', JSON.stringify({
        graph, root:connected.root, contact:connected.contact}));
      if (!Array.isArray(connected.scope_path) || connected.scope_path.at(-1) !== connected.scope) {
        throw new Error('The application did not return its Workshop navigation path.');
      }
      if (viewIdentity() !== startedView) throw new Error('Your current view changed.');
      await window.ARCHHUB_SCOPE_OPEN(connected.scope_path);
      window.location.reload();
    } catch (error) {
      throw new Error('The agent connection is saved. Its Workshop could not open: ' + (error?.message || 'refresh the graph list'));
    }
  };

  // open a session — also pin as a tab if not already open
  const openSession = async (id) => {
    if (id && window.ARCHHUB_GRAPH_OPEN) {
      try {
        await window.ARCHHUB_GRAPH_OPEN(id);
        window.location.reload();
      } catch (error) { window.alert(error?.message || 'Graph opening was refused.'); }
      return;
    }
    if (id && !openTabs.includes(id)) setOpenTabs(t => [...t, id]);
    setOpenId(id);
  };
  const closeTab = (id) => {
    setOpenTabs(t => {
      const next = t.filter(x => x !== id);
      if (openId === id) setOpenId(null);
      return next;
    });
  };

  // Insert a node from the library at canvas coords (x,y). called from drop or dbl-click
  const addNodeFromLibrary = (libItem, x = 200, y = 200) => {
    if (window.ARCHHUB_STUDIO_AUTHORITY) {
      return window.ARCHHUB_NODE_CREATE({definition: libItem.definition || libItem.id,
        definition_revision: libItem.revision_root, x, y}).catch(() => false);
    }
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
    if (libItem.engine && window.ARCHHUB_NODE_CREATE) {
      // A node with an engine is created ON THE GRAPH through the same governed
      // write the seed uses, then the canvas reloads from the graph.
      window.ARCHHUB_NODE_CREATE({ title: libItem.title, engine: libItem.engine, x, y, params: libItem.params || {} })
        .then(r => { if (r && r.ok !== false) window.location.reload(); else window.alert('not created: ' + ((r && r.error) || '')); })
        .catch(e => window.alert('not created: ' + (e && e.message || e)));
      return;
    }
    if (libItem.noEngine) {
      // A card with no engine used to land in this component's memory only:
      // invisible to Run, never written to the graph, gone on the next reload.
      // Say so instead of pretending it was placed.
      window.alert(libItem.title + ' has no engine in this build, so it cannot run yet. '
        + 'It would vanish on reload, so it is not placed.');
      return;
    }
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
        addNodeFromLibrary={addNodeFromLibrary} workshopContext={workshopContext} account={account}
        wsSel={wsSel} setWsSel={setWsSel} onAddAgent={() => setLibraryOpen(true)}
        onWorkshopTarget={target => updateWorkspaceView({target})}/>
      {session
        ? <Workspace
            session={session} model={displayedModel}
            openTabs={openTabs} setOpenId={openSession} closeTab={closeTab}
            setPickerOpen={setPickerOpen}
            setSettingsOpen={openSettings}
            setLibraryOpen={setLibraryOpen}
            focusId={focusId} setFocusId={setFocusId}
            userNodes={userNodes} addNodeFromLibrary={addNodeFromLibrary}
            view={workspaceView} updateView={updateWorkspaceView} wsSel={wsSel} setWsSel={setWsSel}
            onHome={() => setOpenId(null)}/>
        : <Home onOpen={openSession} model={model} native={homeNative} setPickerOpen={setPickerOpen}
            onStarted={async (result, continueInView = () => true) => {
              const owner = window.ARCHHUB_EXISTING_WORKSHOP;
              const identity = () => {
                const state = owner.getSnapshot();
                const auth = (state.topology?.canvas || state.canvas)?.authorization;
                return JSON.stringify([state.canvas?.graph_id,auth?.subject,auth?.session]);
              };
              const startedIdentity = identity();
              const guard = () => {
                if (!continueInView() || identity() !== startedIdentity) {
                  throw new Error('Your session is saved. Your current view was kept because your connection changed.');
                }
              };
              guard();
              await window.ARCHHUB_SCOPE_OPEN(result.scope_path);
              guard();
              await owner.refreshTopologyCanvas();
              guard();
              const snapshot = owner.getSnapshot();
              const authorization = (snapshot.topology?.canvas || snapshot.canvas)?.authorization;
              if (snapshot.canvas?.graph_id !== result.graph_id ||
                  !snapshot.workshops?.some(row => row.root === result.root)) {
                throw new Error('Your session is saved. Refresh the Workshop to open it.');
              }
              setOpenTabs(tabs => tabs.includes(result.graph_id) ? tabs : [...tabs, result.graph_id]);
              setWorkspaceSelection({mode:'chat', conversationRoot:result.root,
                target:result.contact ? 'contact:' + result.contact : result.delivery?.node ? 'model:' + result.delivery.node : '',
                notice:result.warning || '', pending:false,
                scope:JSON.stringify([result.graph_id, snapshot.canvas.graph_id, snapshot.canvas.root,
                  authorization?.subject || '', authorization?.session || ''])});
              setOpenId(result.graph_id);
            }}/>}
      <ServerStrip session={session} model={model} setSettingsOpen={openSettings} setDocsOpen={openDocs}/>
      {pickerOpen && <ModelPicker setModel={m => !session
        ? rememberComposerModel(m).then(picked => { setHomeNative(null); setModel(picked); }) : modelTarget
        ? window.pmPersistValue(modelTarget, 'model', modelRoute(m))
        : window.ARCHHUB_STUDIO_AUTHORITY ? Promise.reject(new Error('Select an AI node on the canvas to set its model.'))
        : rememberComposerModel(m).then(setModel)} onClose={() => setPickerOpen(false)} model={displayedModel}
        onNativeSelect={window.ARCHHUB_EXISTING_WORKSHOP ? (!session ? row => setHomeNative(row) : connectNativeSession) : undefined}/>}
      {/* Every ask box in the app reads the current choice from here, so a
          box that was not handed a model still asks the model the founder
          picked instead of falling through to a server default. */}
      <ModelInWindow model={model}/>
      {settingsOpen && <Settings onClose={() => setSettingsOpen(false)} account={account} setAccount={setAccount} onSignOut={signOut}/>}
      {signUpOpen && <SignUp onDone={(rec) => { setAccount(rec); setSignUpOpen(false); }} onCancel={() => setSignUpOpen(false)} plan={account.plan}/>}
      {booting && <AppBoot account={account} onDone={() => setBooting(false)}/>}
      {/* The design's own full-bleed screens: first-run onboarding, a skill's split view, a connector's diagnostic. */}
      <StudioScreens model={model} onPickModel={() => setPickerOpen(true)}/>
      {docsOpen && <Docs onClose={() => setDocsOpen(false)}/>}
      {libraryOpen && <NodeLibrary onClose={() => setLibraryOpen(false)} addNodeFromLibrary={addNodeFromLibrary}/>}
      <style>{`
        @keyframes lmPulse { 0%,100% { opacity:.4 } 50% { opacity:1 } }
        @keyframes lmCaret { 50% { opacity: 0 } }
        @keyframes lmDash  { to { stroke-dashoffset: -16 } }
        @keyframes lmSlideIn { from { transform: translateX(8px); opacity: 0 } to { transform: translateX(0); opacity: 1 } }
        @keyframes lmPop    { from { transform: scale(.92); opacity: 0 } to { transform: scale(1); opacity: 1 } }
        .lm-home-draft::placeholder { color: ${LM.inkSoft}; font-style: italic; opacity: 1 }
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
  h_max:      { w:220, h:118, outs:[{ id:'out', label:'result', t:'trace' }] },
  h_blender:  { w:220, h:118, outs:[{ id:'out', label:'result', t:'trace' }] },
  h_excel:    { w:220, h:118, outs:[{ id:'out', label:'workbooks', t:'sheets' }] },
  h_word:     { w:220, h:118, outs:[{ id:'out', label:'documents', t:'sheets' }] },
  h_ppt:      { w:220, h:118, outs:[{ id:'out', label:'decks', t:'sheets' }] },
  h_outlook:  { w:220, h:118, outs:[{ id:'out', label:'inbox', t:'trace' }] },
  h_notion:   { w:220, h:118, outs:[{ id:'out', label:'pages', t:'trace' }] },
  h_dropbox:  { w:220, h:118, outs:[{ id:'out', label:'files', t:'trace' }] },
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
const Sidebar = ({ panel, setPanel, openId, onOpen, onHome, onSettings, onDocs, addNodeFromLibrary,
  workshopContext, wsSel, setWsSel, onAddAgent, onWorkshopTarget, account }) => (
  <aside style={{
    gridColumn:'1', gridRow:'1',
    display:'grid', gridTemplateColumns:'44px 1fr',
    background:LM.bgPanel, borderRight:`1px solid ${LM.line}`,
    overflow:'hidden', minHeight:0,
  }}>
    <IconRail panel={panel} setPanel={setPanel} onHome={onHome} onSettings={onSettings} onDocs={onDocs}/>
    {/* Workshop open: the agents take this panel's place, one rail, not two (design studio-lm.jsx:442-445). */}
    {workshopContext && window.WorkshopAgentsRail
      ? <window.WorkshopAgentsRail key={JSON.stringify([openId, workshopContext.graphId, workshopContext.scopeRoot,
          workshopContext.descriptor.root])} context={workshopContext} sel={wsSel.agent} onAddAgent={onAddAgent}
          onSelect={(id, addressable) => { setWsSel({agent:id, task:null}); if (addressable) onWorkshopTarget(id); }}/>
      : <>
    {panel === 'chats'  && <ChatsPanel openId={openId} onOpen={onOpen} onNew={onHome} account={account} onAccount={onSettings}/>}
    {panel === 'nodes'  && <NodesPanel addNodeFromLibrary={addNodeFromLibrary} account={account} onAccount={onSettings}/>}
    {panel === 'skills' && <SkillsPanel/>}
    {panel === 'search' && <SearchPanel/>}
      </>}
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
      {/* Share as drawn (design studio-lm.jsx:480-482). This build has no share action, so the icon is disabled and says so. */}
      <RailIcon disabled title="Share · not available in this build">
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

const RailIcon = ({ active, onClick, title, children, disabled }) => (
  <button onClick={onClick} title={title} disabled={disabled} style={{
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

const ChatsPanel = ({ openId, onOpen, onNew, account, onAccount }) => (
  <div style={{ display:'flex', flexDirection:'column', overflow:'hidden', minHeight:0 }}>
    {/* Panel header */}
    <div style={{ padding:'12px 12px 10px', display:'flex', alignItems:'center', gap:LM.sp.sm }}>
      <span style={{ fontFamily:LM.sans, fontSize:14, fontWeight:600, letterSpacing:'-0.005em', color:LM.ink }}>Chats</span>
      <div style={{ flex:1 }}/>
      <button title="More" style={panelIconBtn()}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>
      </button>
      <button title="New chat" onClick={onNew} style={panelIconBtn()}>
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
    <AccountChip account={account} onOpen={onAccount}/>
  </div>
);

// The account chip (design studio-lm.jsx:644-654) draws the account record: archhub.account.v1,
// reconciled with the cloud session in StudioLM. Never a seeded person. Signed out, it is the way
// in: Settings opens on Account. A part the record does not hold is omitted, not blanked.
const AccountChip = ({ account, onOpen }) => {
  const email = account && account.signedIn ? String(account.email || '') : '';
  const name = email ? String(account.name || email.split('@')[0]) : '';
  const tier = email ? String(account.graphTier || '').toUpperCase() : '';
  return (
    <button type="button" aria-label="Account" title={email || 'Sign in'} onClick={onOpen} style={{
      margin:LM.sp.sm, padding:'7px 10px', borderRadius:LM.rad.md,
      background:LM.bgSoft, border:`1px solid ${LM.line}`,
      display:'flex', alignItems:'center', gap:9, textAlign:'left',
      color:LM.ink, fontFamily:LM.sans, cursor:'pointer',
    }}>
      {name && <div style={{ width:22, height:22, borderRadius:'50%', background:LM.userAv, display:'grid', placeItems:'center', fontSize:11, color:LM.onUserAv, fontWeight:700, flexShrink:0 }}>{name[0].toUpperCase()}</div>}
      <div style={{ flex:1, lineHeight:1.1, minWidth:0 }}>
        <div style={{ fontSize:12, fontWeight:500, color:name ? LM.ink : LM.accent, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{name || 'Sign in'}</div>
        {tier && <div style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.08em' }}>{tier}</div>}
      </div>
    </button>
  );
};

const panelIconBtn = () => ({
  width:22, height:22, padding:0, border:0, background:'transparent',
  borderRadius:4, cursor:'pointer', color:LM.inkSoft,
  display:'grid', placeItems:'center',
});

// ─── Nodes panel — primary drag source ───
const NodesPanel = ({ addNodeFromLibrary, account, onAccount }) => {
  const library = useStudioProjection()?.library || LM_LIBRARY;
  const [q, setQ] = React.useState('');
  const [openCats, setOpenCats] = React.useState(() => Object.fromEntries(library.map(group => [group.cat, true])));
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
        {library.map(group => {
          const c = studioCategory(group.cat);
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

      <AccountChip account={account} onOpen={onAccount}/>
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

const catalogueStates = new Map(), catalogueListeners = new Set();
let catalogueVersion = 0;
const catalogueChanged = () => {
  catalogueVersion += 1;
  for (const notify of catalogueListeners) {try {notify();} catch (_) {}}
};
const useCatalogueVersion = () => React.useSyncExternalStore(
  React.useCallback(notify => {catalogueListeners.add(notify); return () => catalogueListeners.delete(notify);}, []),
  () => catalogueVersion);
const loadCatalogue = (loaderName, items) => {
  const load = window[loaderName];
  if (typeof load !== 'function') return Promise.resolve();
  let state = catalogueStates.get(loaderName);
  if (state?.pending) return state.pending;
  state = {loading:true, error:'', pending:null};
  catalogueStates.set(loaderName, state);
  state.pending = Promise.resolve().then(load).then(result => {
    const rows = loaderName === 'ARCHHUB_LOAD_HOSTS' ? result.hosts : result;
    const connectors = loaderName === 'ARCHHUB_LOAD_HOSTS' ? window.ARCHHUB_LIVE?.connectors : null;
    if (!Array.isArray(rows) || (loaderName === 'ARCHHUB_LOAD_HOSTS' &&
        (!Array.isArray(result.connectors) || !Array.isArray(connectors)))) {
      throw new Error('The catalogue response is invalid.');
    }
    items.splice(0, items.length, ...rows);
    if (loaderName === 'ARCHHUB_LOAD_HOSTS') {
      connectors.splice(0, connectors.length, ...result.connectors);
    }
  }).catch(error => {state.error = error.message || 'Catalogue unavailable.';})
    .finally(() => {state.loading = false; state.pending = null; catalogueChanged();});
  catalogueChanged();
  return state.pending;
};
const withLiveCatalogue = (loaderName, items, View) => props => {
  useCatalogueVersion();
  React.useEffect(() => {loadCatalogue(loaderName, items);}, []);
  const status = catalogueStates.get(loaderName) || {loading:false, error:''};
  return <>
    {status.loading && <p role="status">Loading catalogue…</p>}
    {status.error && <p role="alert">{status.error} <button onClick={() => loadCatalogue(loaderName, items)}>Retry</button></p>}
    <View {...props}/>
  </>;
};

const SkillsPanel = withLiveCatalogue('ARCHHUB_LOAD_SKILLS', LM_SAVED_SKILLS, () => (
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
));

// ─── Global search panel ───
const SearchPanel = () => {
  // Scope counts are read from what this Studio holds; a scope nothing counts draws no number.
  const projected = useStudioProjection();
  const live = window.ARCHHUB_LIVE || {};
  const count = list => Array.isArray(list) ? list.length : null;
  return (
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
        ['chats',  'sessions + messages',  count(LM_SESSIONS)],
        ['nodes',  'in current graph',     count(projected?.graph?.nodes || live.graph?.nodes)],
        ['skills', 'saved templates',      count(live.skills)],
        ['memory', 'what the brain governs', count(live.memory)],
        ['files',  'Revit / Rhino / Speckle', null],
        ['hosts',  'connectors',           count(live.connectors)],
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
          {n != null && <span style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted }}>{n}</span>}
        </button>
      ))}
    </div>
  </div>
  );
};

const kbd = () => ({
  fontFamily:LM.mono, fontSize:9, padding:'1px 5px', background:LM.bgSoft,
  border:`1px solid ${LM.lineHair}`, borderRadius:LM.rad.xs, color:LM.inkMuted, letterSpacing:'0.06em',
});

// ──────────────────────── HOME ────────────────────────
const Home = ({ onOpen, model, native, setPickerOpen, onStarted }) => {
  const [filter, onFilter] = React.useState('all');
  const [draft, setDraft] = React.useState('');
  const [starting, setStarting] = React.useState(false);
  const [startError, setStartError] = React.useState('');
  const startBusy = React.useRef(false), acceptedSession = React.useRef(null);
  const homeMounted = React.useRef(true);
  React.useEffect(() => {homeMounted.current = true; return () => {homeMounted.current = false;};}, []);
  const startSession = async event => {
    event.preventDefault();
    if (!draft.trim() || startBusy.current) return;
    if (!native && !modelRoute(model)) { setPickerOpen(true); return; }
    startBusy.current = true; setStarting(true); setStartError('');
    try {
      const owner = window.ARCHHUB_EXISTING_WORKSHOP;
      if (!owner?.startSession) throw new Error('Session creation is unavailable in this application view.');
      const details = {prompt:draft.trim(), ...(native ? {native:{app:native.app,session_id:native.session_id}} : {model:modelRoute(model)})};
      const viewIdentity = () => {
        const snapshot = owner.getSnapshot();
        const authorization = (snapshot?.topology?.canvas || snapshot?.canvas)?.authorization;
        return JSON.stringify([snapshot?.canvas?.graph_id,authorization?.subject,authorization?.session]);
      };
      const startedView = viewIdentity();
      const identity = JSON.stringify([startedView,details]);
      let result = acceptedSession.current?.identity === identity ? acceptedSession.current.result : null;
      let navigationCurrent = true;
      if (!result) {
        result = await owner.startSession(details);
        navigationCurrent = result.navigation_current !== false;
        acceptedSession.current = {identity,result};
      }
      if (!homeMounted.current) return;
      if (!navigationCurrent || viewIdentity() !== startedView) throw new Error('The session is saved in your previous workspace. Your current view was kept.');
      await onStarted(result, () => homeMounted.current && viewIdentity() === startedView);
      setDraft('');
    } catch (error) {
      setStartError(error?.message || 'The session could not be confirmed. Your text is still here.');
    } finally { startBusy.current = false; setStarting(false); }
  };

  const [title, setTitle] = React.useState('');
  const [creating, setCreating] = React.useState(false);
  const [createError, setCreateError] = React.useState('');
  const submitted = React.useRef(false);
  const createGraph = async event => {
    event.preventDefault();
    if (submitted.current || !title.trim()) return;
    submitted.current = true;
    setCreating(true); setCreateError('');
    try {
      if (!window.ARCHHUB_GRAPH_CREATE) throw new Error('Graph creation is unavailable in this view.');
      await window.ARCHHUB_GRAPH_CREATE(title.trim());
      window.location.reload();
    } catch (error) {
      // A lost receipt may follow a successful write. Re-open the saved
      // graph list before another creation; never automatically replay it.
      setCreateError((error?.message || 'Graph creation was not confirmed.') +
        ' Refresh the graph list before creating again.');
      setCreating(false);
    }
  };
  const shown = filter === 'all'
    ? LM_SESSIONS
    : LM_SESSIONS.filter(s => (s.state || 'idle') === filter);
  return (
  <main className="ah-scroll" style={{
    gridColumn:'2', gridRow:'1', overflow:'auto', minHeight:0,
    padding:'30px 44px 36px', display:'flex', flexDirection:'column',
  }}>
    <ModelStrip model={native ? {...model,name:native.title || native.app,vendor:native.app} : model} setPickerOpen={setPickerOpen}/>
    <form onSubmit={startSession} style={{
      background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:LM.rad.xl,
      padding:'16px 18px', marginBottom:16, marginTop:14,
    }}>
      <div style={{ display:'flex', alignItems:'flex-end', gap:14 }}>
        <div style={{ flex:1, minWidth:0 }}>
          <textarea aria-label="Start a new session" placeholder={'Start a new session\u2026'} className="lm-home-draft"
            value={draft} onChange={event => setDraft(event.target.value)} disabled={starting}
            onKeyDown={event => {if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent?.isComposing) startSession(event);}}
            rows={1} maxLength={12000} style={{width:'100%', boxSizing:'border-box', resize:'none', display:'block',
              background:'transparent', border:0, outline:'none', color:LM.ink, fontFamily:LM.serif, fontSize:24,
              letterSpacing:'-0.01em', lineHeight:1.4, padding:'2px 0'}}/>
          {/* The chip row (design studio-lm.jsx:811-816) names the route this session starts on. */}
          <div style={{ display:'flex', alignItems:'center', gap:6, marginTop:10, minWidth:0 }}>
            <Chip mono>{native ? native.app + ' \u00b7 ' + (native.title || 'Connected session') : modelRoute(model) || 'Choose an agent or model above'}</Chip>
          </div>
        </div>
        <button type="submit" disabled={starting || !draft.trim()} style={{
          padding:'9px 16px 9px 14px', background:LM.accent, color: (window.AH && window.AH.onFill) || '#180f08',
          border:0, borderRadius:7, fontFamily:LM.sans, fontSize:13, fontWeight:500,
          cursor:'pointer', display:'inline-flex', alignItems:'center', gap:7, flexShrink:0,
        }}>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke={(window.AH && window.AH.onFill) || "#180f08"} strokeWidth="2.5"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
          {starting ? 'Starting\u2026' : 'Send'}
        </button>
      </div>
      {startError && <p role="alert" style={{color:LM.warn,marginBottom:0}}>{startError}</p>}
    </form>
    <details style={{marginBottom:24}}>
      <summary style={{fontSize:12,color:LM.inkSoft,cursor:'pointer'}}>New blank graph</summary>
    <form onSubmit={createGraph} style={{
      background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:LM.rad.xl,
      padding:'16px 18px', marginBottom:36, marginTop:14,
    }}>
      <div style={{ display:'flex', alignItems:'flex-end', gap:14 }}>
        <div style={{ flex:1, minWidth:0 }}>
          <input aria-label="New graph name" placeholder="Name your new graph…" value={title}
            onChange={event => setTitle(event.target.value)} disabled={submitted.current} maxLength={80}
            style={{width:'100%', boxSizing:'border-box', background:'transparent', border:0,
              fontFamily:LM.serif, fontSize:24, color:LM.ink, padding:'2px 0'}}/>
          <p style={{color:LM.inkMuted, margin:'10px 0 0'}}>Start with a blank graph, then add nodes from the library.</p>
        </div>
        <button type="submit" disabled={submitted.current || !title.trim()} style={{
          padding:'9px 16px 9px 14px', background:LM.accent, color: (window.AH && window.AH.onFill) || '#180f08',
          border:0, borderRadius:7, fontFamily:LM.sans, fontSize:13, fontWeight:500,
          cursor:'pointer', display:'inline-flex', alignItems:'center', gap:7,
        }}>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke={(window.AH && window.AH.onFill) || "#180f08"} strokeWidth="2.5"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
          {creating ? 'Creating…' : 'Create graph'}
        </button>
      </div>
      {createError && <p role="alert" style={{color:LM.warn}}>{createError}
        {' '}<button type="button" onClick={() => window.location.reload()}>Refresh graphs</button></p>}
    </form>
    </details>
    <div style={{ display:'flex', alignItems:'baseline', gap:10, marginBottom:14 }}>
      <h2 style={{ fontFamily:LM.serif, fontSize:26, fontWeight:400, letterSpacing:'-0.015em', margin:0 }}>Sessions</h2>
      <span style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.14em' }}>
        {shown.length} · CLICK TO OPEN
      </span>
      <div style={{ flex:1 }}/>
      {/* The chips are the states sessions really carry: an 'idle' chip could
          never match, and scheduled and workflow sessions had no chip at all
          (2026-09-07). One list, derived from the same table the badges use. */}
      {['all'].concat(Object.keys(LM_STATE_META)).map(kind => (
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
const Workspace = ({ session, model, openTabs, setOpenId, closeTab, setPickerOpen, setSettingsOpen, setLibraryOpen, focusId, setFocusId, userNodes, addNodeFromLibrary, onHome, view, updateView, wsSel, setWsSel }) => {
  const authorityState = useStudioProjection();
  const graph = authorityState?.graph || LM_GRAPH;
  const allNodes = [...graph.nodes, ...(userNodes || [])];
  // A wire is a node: focusId may name one, and the SAME rail renders it.
  const wireIdx = authorityState ? graph.wires.findIndex(wire => wire.id === focusId) : (String(focusId).indexOf('wire:') === 0 ? +String(focusId).slice(5) : -1);
  const focusNode = wireIdx >= 0
    ? window.wireAsNode(graph.wires[wireIdx], wireIdx, allNodes)
    : allNodes.find(n => n.id === focusId);
  const {mode, conversationRoot, target} = view;
  const setMode = mode => updateView({mode});
  const workshopState = useWorkshopProjection();
  const workshops = workshopState?.workshops || [];
  const workshop = workshops.find(row => row.root === conversationRoot);
  if (view.pending) return <main style={{gridColumn:'2', gridRow:'1', padding:24, color:LM.inkSoft}}>
    <p role="status">{view.notice}</p>
  </main>;
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
        workshops={workshops} conversationRoot={workshop?.root || ''} conversationNotice={view.notice}
        workshopUnavailable={workshopState?.canvas?.unavailable || ''}
        workshopModel={workshopState?.nativeWork?.model}
        setConversationRoot={root => updateView({conversationRoot:root, mode:'chat', target:''})}
        setPickerOpen={setPickerOpen} setSettingsOpen={setSettingsOpen} onHome={onHome}/>
      {mode === 'chat' ? (
        workshop && window.WorkshopView ? <window.WorkshopView key={JSON.stringify([session.id, workshopState.canvas.graph_id,
          workshopState.canvas.root, workshop.root])} state={workshopState} descriptor={workshop} target={target}
          setTarget={target => updateView({target})} setMode={setMode} setFocusId={setFocusId}
          onLeave={() => updateView({conversationRoot:'', mode:'chat', target:''})}
          sel={wsSel} setSel={setWsSel} externalRail/> : <>
          <ChatView session={session} model={model} setMode={setMode} onPickModel={() => setPickerOpen(true)}
            workshopRoom={workshopModeRoom(workshops, '')}
            openWorkshop={root => updateView({conversationRoot:root, mode:'chat', target:''})}/>
          <InferenceInspector model={model} setPickerOpen={setPickerOpen}/>
        </>
      ) : (
        <>
          <NodeCanvas key={JSON.stringify([session.id, studioCanvasScope(authorityState?.canvas)])} focusId={focusId} setFocusId={setFocusId} setLibraryOpen={setLibraryOpen} userNodes={userNodes} addNodeFromLibrary={addNodeFromLibrary} model={model}/>
          <NodeRail node={focusNode} hiddenWork={!focusNode && authorityState?.canvas?.selection_hidden === true}
            workshopRoom={workshopModeRoom(workshops, workshop?.root || '')}
            onOpenWorkshop={() => chooseWorkshopMode('workshop', {mode, conversationRoot:workshop?.root || '', workshops, setMode,
              setConversationRoot:root => updateView({conversationRoot:root, mode:'chat', target:''})})}/>
        </>
      )}
    </main>
  );
};

// The string the server's router reads. The picker's rows carry `routed`
// (the cloud and OpenRouter ids are the same shape, so the row says which);
// older rows only have `route`.
const modelRoute = (m) => String((m && (m.routed || m.route)) || '');
// A composer pick is the owner's graph-held setting, saved when it is made.
// It lived only in this page until a Send reached the server, so a restart or
// an update came back "Choose a model" (2026-09-17). The signed clean engine
// has no selection route, so there the pick stays page state as before.
const noModelPicked = () => ({ name:'Choose a model', route:'', routed:'', vendor:'No model selected', tag:'', ctx:'', col:LM.inkMuted, latency:null });
const rememberComposerModel = async (m) => {
  const route = modelRoute(m);
  if (typeof window.ARCHHUB_AGENT_SELECT !== 'function') {
    if (window.ARCHHUB_STUDIO_AUTHORITY) return route ? m : noModelPicked();
    throw new Error('This connection cannot save a model selection.');
  }
  if (await window.ARCHHUB_AGENT_SELECT(route) !== route) throw new Error('The model selection could not be confirmed.');
  return route ? m : noModelPicked();
};
const nodeModelRow = n => (n?.params || []).find(row => row.k === 'model') || null;
const nodeModelRoute = n => {
  const route = String(nodeModelRow(n)?.v || '').trim();
  return route === 'provider-selected' ? '' : route;
};

// ─── Chat lane data seam ───
// ChatView, InferenceInspector and ModelPicker are the design bundle's components
// (archhub/project/studio-lm.jsx ChatView 939-1020, InferenceInspector 1023-1080, ModelPicker
// 3145-3208), kept to its layout, spacing, type, tokens and copy. This seam is where they differ:
// it maps what the application holds onto the shapes those components read. No seeded person,
// file, token count, stage progress, host or price is drawn.
const CHAT_SYSTEM_PROMPT = 'You operate the ArchHub node canvas. Prepare editable, wired changes for review; never claim that effects ran.';
const chatPeople = model => {
  const account = typeof acLoad === 'function' ? (acLoad() || {}) : {};
  const me = String(account.name || account.email || '').trim() || 'You';
  // Unrouted, the application's own composer answers, so the turn is signed ArchHub.
  const answerer = String((modelRoute(model) ? model.name : 'ArchHub') || 'ArchHub');
  return {me, answerer};
};
// The wired pipeline in topological stages (at most eight), read from the projected graph.
const chatStages = graph => {
  if (!graph) return [];
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
  return stages;
};
// Connectors are exactly what answered a probe. Green only for a host the product can DRIVE:
// seeing a process or a port is not a connection (founder rule: nothing green that is not wired).
const chatConnectors = () => (window.ARCHHUB_LIVE?.connectors || []).map(c => ({
  id:c.id, name:c.name, state:c.state, detail:c.detail,
  col: c.drive && (c.state === 'connected' || c.state === 'listening') ? LM.ok
    : c.state === 'installed' || c.state === 'reachable' ? LM.warn : LM.inkDim,
}));

// ─── Calm chat view (default) — restores original Studio's generous rhythm ───
const ChatView = ({ session, model, setMode, workshopRoom = '', openWorkshop, onPickModel }) => {
  const {me, answerer} = chatPeople(model);
  const routed = !!modelRoute(model);
  const conv = LM_GRAPH.nodes.find(n => n.cat === 'ai')
    || LM_GRAPH.nodes.find(n => n.id === 'ai_intent');
  const [messages, setMessages] = React.useState((conv && conv.messages) || []);
  const [draft, setDraft] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const stamp = () => new Date().toTimeString().slice(0, 5);
  const send = async () => {
    const text = draft.trim();
    // No model picked or configured: nothing is sent and no model is chosen for
    // him; the picker opens instead (founder 2026-09-23, coordination review).
    if (!routed && !/^\/remember\s+/s.test(text)) { if (typeof onPickModel === 'function') onPickModel(); return; }
    if (!text || busy || !window.ARCHHUB_AGENT) return;
    setMessages(m => [...m, { me:true, time:stamp(), text }]);
    // /remember <fact> is a command, not a question: it lands in the brain.
    const remember = text.match(/^\/remember\s+(.+)/s);
    if (remember) {
      setDraft('');
      try {
        const r = await window.ARCHHUB_REMEMBER(remember[1].trim());
        setMessages(m => [...m, { me:false, time:stamp(), text: r && r.ok === false ? 'not saved: ' + (r.error || '') : 'remembered.' }]);
      } catch (error) {
        setMessages(m => [...m, { me:false, time:stamp(), text:'not saved: ' + (error?.message || error) }]);
      }
      return;
    }
    setDraft('');
    setBusy(true);
    try {
      const answer = await window.ARCHHUB_AGENT(text, modelRoute(model));
      setMessages(m => [...m, { me:false, time:stamp(), text:answer }]);
    } catch (error) {
      setMessages(m => [...m, { me:false, time:stamp(),
        text:'refused: ' + (error?.message || error) }]);
    } finally { setBusy(false); }
  };
  const onFill = (window.AH && window.AH.onFill) || '#180f08';
  return (
    <section data-chat-view="" style={{
      gridColumn:'1', gridRow:'2', minHeight:0, display:'flex', flexDirection:'column',
      background:LM.bg, overflow:'hidden',
    }}>
      {/* The design draws the reply prompt in inkMuted; a real field has to be told. */}
      <style>{`.lm-chat-draft::placeholder { color: ${LM.inkMuted}; opacity: 1 }`}</style>
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
              <button type="button" disabled title="Editing the system prompt is not available in this build" style={{
                padding:0, background:'transparent', border:0, borderBottom:`1px dashed ${LM.line}`,
                fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, cursor:'default',
              }}>edit</button>
            </div>
            <div style={{ fontFamily:LM.serif, fontStyle:'italic', fontSize:15, lineHeight:1.55, color:LM.inkSoft, letterSpacing:'-0.005em' }}>
              {CHAT_SYSTEM_PROMPT}
            </div>
          </div>

          {/* Conversation — calm, generous, serif for Claude */}
          {messages.map((m, i) => (
            <div key={i} data-chat-turn={m.me ? 'me' : 'answer'} style={{ display:'flex', gap:14, marginBottom:24 }}>
              <div style={{
                width:30, height:30, borderRadius: m.me ? '50%' : LM.rad.md, flexShrink:0,
                background: m.me ? LM.userAv : LM.accent,
                display:'grid', placeItems:'center',
                color: m.me ? LM.onUserAv : onFill, fontFamily:LM.sans, fontSize:13, fontWeight:700,
              }}>{(m.me ? me : answerer)[0].toUpperCase()}</div>
              <div style={{ flex:1, minWidth:0 }}>
                <div style={{ display:'flex', alignItems:'baseline', gap:8, marginBottom:4 }}>
                  <span style={{ fontSize:13, fontWeight:500, color:LM.ink }}>{m.me ? me : answerer}</span>
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
            <input className="lm-chat-draft" aria-label="Reply" value={draft} onChange={e => setDraft(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') send(); }}
              placeholder={busy ? 'thinking…' : 'Reply, or ask for another step…'}
              disabled={busy}
              style={{ display:'block', width:'100%', margin:0, background:'transparent', border:0, outline:0,
                fontFamily:LM.serif, fontStyle:'italic', fontSize:17, lineHeight:1.5, color:LM.ink,
                padding:'2px 0 8px', letterSpacing:'-0.01em' }}/>
            <div style={{ display:'flex', alignItems:'center', gap:6 }}>
              <Chip mono>@ skill</Chip>
              <Chip>＋ sketch</Chip>
              <button type="button" disabled={!workshopRoom || !openWorkshop}
                onClick={() => workshopRoom && openWorkshop && openWorkshop(workshopRoom)}
                title={workshopRoom ? undefined : 'No Workshop conversation in this scope'} style={{
                display:'inline-flex', alignItems:'center', gap:5, padding:'3px 9px',
                background: workshopRoom ? LM.accentDim : 'transparent',
                border: workshopRoom ? `1px solid ${LM.accentSoft}` : `1px dashed ${LM.line}`, borderRadius:LM.rad.sm,
                color: workshopRoom ? LM.accent : LM.inkMuted, fontFamily:LM.mono, fontSize:10.5, letterSpacing:'0.04em',
                cursor: workshopRoom ? 'pointer' : 'default',
              }}>◆ workshop</button>
              <button onClick={() => setMode('canvas')} style={{
                display:'inline-flex', alignItems:'center', gap:5, padding:'3px 9px',
                background:'transparent', border:`1px solid ${LM.line}`, borderRadius:LM.rad.sm,
                color:LM.inkSoft, fontFamily:LM.mono, fontSize:10.5, letterSpacing:'0.04em', cursor:'pointer',
              }}>⌗ open as nodes</button>
              {/* The design's spacer and model label in one: a long live route takes the free width and
                  ellipsizes, so the chips beside it keep their one-line size. */}
              <span title={modelRoute(model) || undefined} style={{ flex:'1 1 0', minWidth:0, textAlign:'right', fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{routed ? model.name.split(' ').slice(0,2).join(' ') : model.name}{model.latency != null ? ' · ~' + model.latency + 'ms' : ''}</span>
              {/* While an answer is out Send is disabled: a dashed border, never alpha (DECISIONS.md). */}
              {routed ? <button onClick={send} disabled={busy} style={{
                padding: busy ? '6px 13px' : '7px 14px', background: busy ? 'transparent' : LM.accent,
                color: busy ? LM.inkMuted : onFill, border: busy ? `1px dashed ${LM.line}` : 0,
                borderRadius:LM.rad.sm, fontSize:12.5, fontWeight:500, cursor: busy ? 'default' : 'pointer',
              }}>Send ↵</button> : <button type="button" onClick={() => typeof onPickModel === 'function' && onPickModel()}
                title="No model is picked: choose one to send" style={{
                padding:'6px 13px', background:'transparent', color:LM.ink, border:`1px dashed ${LM.line}`,
                borderRadius:LM.rad.sm, fontSize:12.5, fontWeight:500, cursor:'pointer',
              }}>Choose a model</button>}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};

// ─── Calm inference inspector (chat mode right rail) ───
// The parametric chain, LIVE: the wired pipeline from the graph in topological stages, drawn with
// the design's stage track and CalmRow. Nothing is authored: an unwired canvas is 0 stages.
const LiveChain = () => {
  const graph = window.ARCHHUB_LIVE?.graph;
  if (!graph) return null;
  const stages = chatStages(graph);
  const rows = stages.flatMap((nodes, i) => nodes.flatMap(n => (n.params || []).slice(0, 2).map(p =>
    ({key:n.id + '|' + p.k, node:'stage ' + (i + 1) + ' · ' + n.title, k:p.k, v:String(p.v)}))));
  return (
    <div data-chat-chain="" style={{ padding:'14px 16px', borderBottom:`1px solid ${LM.lineSoft}` }}>
      <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.14em', marginBottom:10 }}>PARAMETRIC CHAIN · {stages.length} STAGE{stages.length === 1 ? '' : 'S'}</div>
      {stages.length > 0 && <div style={{ display:'flex', alignItems:'center', gap:0, marginBottom:10 }}>
        {stages.map((_, i) => (
          <React.Fragment key={i}>
            <div style={{ width:18, height:18, borderRadius:'50%', border:`2px solid ${LM.accent}`, background:LM.bg, color:LM.accent, display:'grid', placeItems:'center', fontFamily:LM.mono, fontSize:9, fontWeight:600 }}>{i + 1}</div>
            {i < stages.length - 1 && <div style={{ flex:1, height:2, background:LM.accent }}/>}
          </React.Fragment>
        ))}
      </div>}
      {rows.map(row => (
        <div key={row.key} title={row.node}>
          <CalmRow k={row.k} v={<span style={{ display:'inline-block', maxWidth:170, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', verticalAlign:'bottom' }}>{row.v}</span>}/>
        </div>
      ))}
    </div>
  );
};

const InferenceInspector = ({ model, setPickerOpen }) => {
  const connectors = chatConnectors();
  return (
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
          <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted }}>{model.vendor}{model.ctx ? ' · ctx ' + model.ctx : ''}</div>
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
    <div data-chat-connectors="" style={{ padding:'14px 16px' }}>
      <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.14em', marginBottom:10 }}>CONNECTORS · {connectors.length}</div>
      {connectors.map(c => (
        <div key={c.id} title={c.detail} style={{ display:'flex', alignItems:'center', gap:8, padding:'5px 0', borderBottom:`1px dashed ${LM.lineSoft}` }}>
          <span style={{ width:7, height:7, borderRadius:'50%', background:c.col, boxShadow:`0 0 0 3px ${c.col}22` }}/>
          <span style={{ flex:1, fontSize:12.5, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{c.name}</span>
          <span style={{ fontFamily:LM.mono, fontSize:9.5, color:c.col, letterSpacing:'0.06em', textTransform:'uppercase' }}>{c.state}</span>
        </div>
      ))}
      {/* A host that cannot connect on this machine says why, in words, not on hover. */}
      {connectors.filter(c => c.state === 'unavailable' && c.detail).map(c => (
        <div key={c.id + ':why'} data-connector-reason={c.id} style={{ fontSize:11, color:LM.inkSoft, lineHeight:1.45, whiteSpace:'normal', overflowWrap:'anywhere', padding:'4px 0 6px 15px' }}>{c.name}: {c.detail}</div>
      ))}
      {window.ARCHHUB_LIVE && !connectors.length &&
        <div role="status" style={{ fontFamily:LM.mono, fontSize:10.5, color:LM.inkMuted, lineHeight:1.5 }}>No host has answered a probe yet.</div>}
    </div>
  </aside>
  );
};

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

const visuallyHiddenStyle = {position:'absolute', width:1, height:1, padding:0, margin:-1, overflow:'hidden',
  clip:'rect(0, 0, 0, 0)', whiteSpace:'nowrap', border:0};
const StudioHeaderIcon = ({name}) => <svg aria-hidden="true" focusable="false" width="15" height="15"
  viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
  {name === 'download' ? <><path d="M12 3v12m-5-5 5 5 5-5"/><path d="M4 16v5h16v-5"/></> :
    name === 'reload' ? <><path d="M20 7v5h-5"/><path d="M19 12a7 7 0 1 0-2 5M20 12a8 8 0 0 0-14-6"/></> :
    name === 'skill' ? <><path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9Z"/></> :
    name === 'error' ? <><path d="m12 3 10 18H2Z"/><path d="M12 9v5m0 3h.01"/></> :
    name === 'ready' ? <><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></> :
    <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>}
</svg>;

// Restarting loses composer text that was never sent. The first click arms the restart and names that loss;
// a second click within 5 s restarts. The status strip notice and the Workspace header both confirm here.
const useRestartConfirmation = (ready, restart) => {
  const [confirming, setConfirming] = React.useState(false);
  React.useEffect(() => {
    if (!confirming) return undefined;
    const timer = window.setTimeout(() => setConfirming(false), 5000);
    return () => window.clearTimeout(timer);
  }, [confirming]);
  React.useEffect(() => { if (!ready) setConfirming(false); }, [ready]);
  return [confirming && 'Restart now - unsent text is lost', () => {
    if (!confirming) { setConfirming(true); return; }
    setConfirming(false);
    restart();
  }];
};

const ApplicationUpdateControls = ({compact = false}) => {
  const transport = window.ARCHHUB_EXISTING_WORKSHOP;
  const [snapshot, setSnapshot] = React.useState(() => transport?.getSnapshot() || null);
  const [localError, setLocalError] = React.useState('');
  const alive = React.useRef(true);
  React.useEffect(() => {
    alive.current = true;
    if (!transport?.watchApplicationUpdate) return () => { alive.current = false; };
    const unsubscribe = transport.subscribe(() => setSnapshot(transport.getSnapshot()));
    const unwatch = transport.watchApplicationUpdate();
    setSnapshot(transport.getSnapshot());
    return () => { alive.current = false; unsubscribe(); unwatch(); };
  }, [transport]);
  const [warning, restart] = useRestartConfirmation(snapshot?.applicationUpdate?.state === 'ready' &&
    !snapshot?.applicationUpdateError && !localError, () => act('reload'));
  if (!transport?.watchApplicationUpdate) return compact ? null :
    <p style={{fontSize:12, color:LM.inkSoft}}>Release updates are unavailable in this Studio connection.</p>;
  const status = snapshot?.applicationUpdate;
  const pending = !!snapshot?.applicationUpdatePending;
  const error = snapshot?.applicationUpdateError || localError;
  const active = ['checking', 'downloading', 'restarting'].includes(status?.state);
  const label = {idle:'No update in progress', checking:'Checking for a release…', downloading:'Downloading update…',
    ready:'Update ready', restarting:'Restart requested…', failed:'Update failed'}[status?.state] || 'Reading release status…';
  const act = async action => {
    setLocalError('');
    try {
      if (action === 'read') await transport.refreshApplicationUpdate();
      else await transport.applicationUpdateAction(action);
    } catch (failure) {
      if (alive.current) setLocalError(transport.getSnapshot()?.applicationUpdateError ? '' :
        failure.message || 'The update request could not be confirmed.');
    }
  };
  // Disabled controls use a dashed border and say why in their title, never alpha (design DECISIONS.md).
  // The dashed border replaces the whole border shorthand: a borderStyle longhand beside smallBtn's border
  // would be removed on re-enable and leave the browser's outset button border behind.
  const waiting = 'Waiting for the current update request to finish';
  const buttonStyle = disabled => ({...smallBtn(), fontSize:compact ? 10.5 : 12, flexShrink:0,
    ...(compact ? {width:28, height:28, padding:0, display:'grid', placeItems:'center'} : {}),
    ...(disabled ? {background:'transparent', border:`1px dashed ${LM.line}`, color:LM.inkSoft, cursor:'default'} : {})});
  return <section aria-label="Application release updates" style={compact ? {
    display:'flex', alignItems:'center', gap:6, flexShrink:0, paddingLeft:6,
  } : {marginTop:16, padding:'14px 16px', border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg}}>
    {!compact && <>
      <h3 style={{fontSize:14, margin:'0 0 8px'}}>Application updates</h3>
      <div style={{fontSize:12, color:LM.inkSoft, overflowWrap:'anywhere'}}>Current build: {status?.current_build || 'Reading…'}</div>
      {status?.available_build && <div style={{fontSize:12, color:LM.inkSoft, overflowWrap:'anywhere'}}>Available build: {status.available_build}</div>}
      <p style={{fontSize:12, lineHeight:1.5}}>Check and download fetches a release. Update and reload restarts ArchHub into that release. Save unsubmitted drafts before restarting.</p>
    </>}
    <span role={error || status?.state === 'failed' ? 'alert' : 'status'}
      title={[label, status?.current_build, status?.available_build, error || status?.detail].filter(Boolean).join(' · ')}
      aria-label={compact ? error || label : undefined} tabIndex={compact ? 0 : undefined}
      style={{display:compact ? 'inline-block' : 'block', fontSize:compact ? 10.5 : 12,
        color:error || status?.state === 'failed' ? LM.err : LM.inkSoft,
        ...(compact ? {width:24, height:28, display:'grid', placeItems:'center', position:'relative'} :
          {margin:'10px 0', overflowWrap:'anywhere', whiteSpace:'pre-wrap'})}}>
      {compact ? <><StudioHeaderIcon name={error || status?.state === 'failed' ? 'error' :
        status?.state === 'ready' ? 'ready' : active ? 'reload' : 'status'}/>
        <span style={visuallyHiddenStyle}>{error || label}</span></> : error || [label, status?.detail].filter(Boolean).join('\n')}
    </span>
    {status?.state === 'ready' && !error && <button disabled={pending || !status.restart_supported}
      onClick={compact ? restart : () => act('reload')}
      title={compact && warning || (pending ? waiting : status.restart_supported ?
        'Install the ready release through the desktop restart' : 'Desktop restart is unavailable in this session')}
      aria-label={compact && warning || 'Update and reload'}
      style={{...(pending || !status.restart_supported ? buttonStyle(true) : {...buttonStyle(false), color:LM.accent}),
        ...(compact && warning ? {background:LM.accent, border:`1px solid ${LM.accent}`, color:LM.bg} : {})}}>
      {compact ? <StudioHeaderIcon name="reload"/> : 'Update and reload'}</button>}
    {(!active && status?.state !== 'ready' && !error) && <button disabled={pending || !status}
      onClick={() => act('check')} title={pending ? waiting : !status ? 'Reading release status\u2026' : 'Check and download'}
      aria-label="Check and download" style={buttonStyle(pending || !status)}>
      {compact ? <StudioHeaderIcon name="download"/> : 'Check and download'}</button>}
    {error && <button disabled={pending} onClick={() => act('read')} title={pending ? waiting : 'Read status'}
      aria-label="Read status" style={buttonStyle(pending)}>
      {compact ? <StudioHeaderIcon name="reload"/> : 'Read status'}</button>}
    {status?.state === 'ready' && !status.restart_supported && <span style={{fontSize:11, color:LM.inkSoft}}>
      {compact ? 'Desktop restart unavailable' : 'Desktop restart is unavailable in this session.'}
    </span>}
  </section>;
};

const WorkshopStorageReview = ({root, label}) => {
  const authority = window.ARCHHUB_EXISTING_WORKSHOP;
  const [review, setReview] = React.useState(null), [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(false), [confirmPage, setConfirmPage] = React.useState(null);
  const [confirmTracking, setConfirmTracking] = React.useState(false);
  const [notice, setNotice] = React.useState('');
  const mounted = React.useRef(true), working = React.useRef(false);
  React.useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const read = async (after = null) => {
    if (working.current) return;
    working.current = true; setBusy(true); setError(''); setConfirmPage(null); setConfirmTracking(false);
    try {
      const result = await authority.reviewConversationPages(root, after);
      if (mounted.current) setReview(result);
    } catch (failure) { if (mounted.current) { setReview(null); setError(failure.message || 'Could not read protected editors.'); } }
    finally { working.current = false; if (mounted.current) setBusy(false); }
  };
  const release = async () => {
    if (working.current || !confirmPage) return;
    working.current = true; setBusy(true); setError(''); setNotice('');
    try {
      await authority.discardConversationPage(root, confirmPage);
      if (mounted.current) { setConfirmPage(null); setReview(null); setNotice('Editor protection released. Conversation messages and graph nodes are unchanged.'); }
    } catch (failure) {
      if (mounted.current) { setConfirmPage(null); setReview(null); setError(failure.message || 'Release is not confirmed. Refresh before continuing.'); }
    } finally { working.current = false; if (mounted.current) setBusy(false); }
  };
  const changeConversation = async action => {
    if (working.current || !review || action === 'resolveConversationTracking' && !confirmTracking) return;
    working.current = true; setBusy(true); setError(''); setNotice('');
    try {
      await authority[action](root, review);
      if (mounted.current) {
        setReview(null); setConfirmTracking(false);
        setNotice(action === 'archiveConversation' ? 'Conversation archived. Its messages and saved graph remain.' :
          'Earlier unsent drafts marked as resolved. Inactivity tracking starts now; open editors remain protected.');
      }
    } catch (failure) {
      if (mounted.current) { setReview(null); setConfirmTracking(false); setError(failure.message || 'Refresh storage before retrying.'); }
    } finally { working.current = false; if (mounted.current) setBusy(false); }
  };
  const control = {background:LM.bg, color:LM.ink, border:`1px solid ${LM.line}`, borderRadius:LM.rad.sm,
    padding:'5px 7px', fontSize:12, cursor:busy ? 'default' : 'pointer'};
  return <details style={{marginTop:12, borderTop:`1px solid ${LM.line}`, paddingTop:10}}
    onToggle={event => { if (event.currentTarget.open && !review) read(); }}>
    <summary style={{cursor:'pointer'}}>Conversation storage</summary>
    <p style={{color:LM.inkSoft, lineHeight:1.5}}>{label}: open editors and unresolved drafts prevent cleanup.
      An open record can remain after a browser closes; it does not prove a running session.</p>
    <div style={{display:'flex', justifyContent:'space-between', alignItems:'center'}}>
      <strong>Protected editors</strong>
      <button disabled={busy} onClick={() => read()} style={control} aria-label="Refresh protected editors"
        title="Refresh protected editors"><StudioHeaderIcon name="reload"/></button>
    </div>
    {review?.pages.map(page => <div key={page.page_id} style={{padding:'10px 0', borderBottom:`1px solid ${LM.lineSoft}`}}>
      <div style={{display:'flex', gap:8, alignItems:'center'}}>
        <span title={page.page_id} style={{flex:1}}>{page.editor_label}</span>
        <button disabled={busy} onClick={() => setConfirmPage(page)} style={control}
          aria-label={'Review release of editor ' + page.page_id.slice(-8)} title="Review release of cleanup protection">⋯</button>
      </div>
      <div style={{color:LM.inkSoft, marginTop:4}}>{page.state === 'open' ? 'Open record' : 'Closed record'} ·
        {page.draft_state === 'dirty' ? ' draft pending' : page.draft_state === 'unknown' ? ' draft state unknown' : ' no pending draft'}</div>
      <div title={'Session: ' + page.session_root + '\nView: ' + page.view_root} style={{color:LM.inkMuted, fontSize:11, marginTop:4}}>
        Browser {page.session_root.slice(-8)} · editor {page.page_id.slice(-8)}</div>
      <div style={{color:LM.inkMuted, fontSize:11, marginTop:4}}>Last changed {new Date(page.changed_at * 1000).toLocaleString()}</div>
      {confirmPage === page && <div style={{marginTop:8}}>
        <p style={{lineHeight:1.5}}>Release this editor’s protection only after saving or discarding its unsent work.
          Unsent text is not stored in this record. This action does not delete conversation messages or graph nodes.</p>
        <button disabled={busy} onClick={release} style={control}>Release protection</button>
        <button disabled={busy} onClick={() => setConfirmPage(null)} style={{...control, marginLeft:6}}>Cancel</button>
      </div>}
    </div>)}
    {review && review.pages.length === 0 && <p>No protected editor records in this conversation.</p>}
    {review?.protection.tracking_state === 'unknown' && <div style={{color:LM.inkSoft}}>
      <p>Earlier draft activity is still unknown. Automatic cleanup remains protected.</p>
      {!confirmTracking ? <button disabled={busy} style={control} onClick={() => setConfirmTracking(true)}>Review earlier activity…</button> : <>
        <p>Confirm that you have saved or discarded any earlier unsent drafts in this conversation.
          This starts its inactivity period now. Existing protected editor records stay protected.</p>
        <button disabled={busy} style={control} onClick={() => changeConversation('resolveConversationTracking')}>Confirm drafts resolved</button>
        <button disabled={busy} style={{...control, marginLeft:6}} onClick={() => setConfirmTracking(false)}>Cancel</button>
      </>}
    </div>}
    {review && <div style={{marginTop:10}}>
      {review.retention.archived_at !== null ? <p>Archived {new Date(review.retention.archived_at * 1000).toLocaleString()}. Saved graph nodes are preserved.</p> :
        <button disabled={busy || review.protection.protected} style={control} onClick={() => changeConversation('archiveConversation')}>Archive conversation</button>}
      {review.protection.protected && <p style={{color:LM.inkSoft}}>Close or resolve protected editors before archiving. Running or unresolved Work also prevents archiving.</p>}
    </div>}
    {review?.next_page_id && <button disabled={busy} onClick={() => read(review.next_page_id)} style={{...control, marginTop:8}}>More editors</button>}
    {notice && <p role="status">{notice}</p>}
    {error && <p role="alert" style={{color:LM.err}}>{error}</p>}
    {busy && <p role="status">Updating storage review…</p>}
  </details>;
};

const WorkshopConversationMenu = ({workshops, conversationRoot, setConversationRoot}) => {
  const state = useWorkshopProjection();
  const authority = window.ARCHHUB_EXISTING_WORKSHOP;
  const anchor = workshops.find(row => row.is_general === true);
  const selected = workshops.find(row => row.root === conversationRoot);
  const menu = React.useRef(null), button = React.useRef(null);
  const [open, setOpen] = React.useState(false), [creating, setCreating] = React.useState(false);
  const [title, setTitle] = React.useState(''), [chosen, setChosen] = React.useState([]);
  const [saved, setSaved] = React.useState(null);
  const [busy, setBusy] = React.useState(false), [error, setError] = React.useState('');
  const held = state?.conversationCatalog;
  const catalog = held?.root === anchor?.root && held?.scope_root === state?.canvas?.root ? held : null;
  const creation = saved && state?.conversationCreation?.root === saved.root ? state.conversationCreation : saved;
  const close = () => { setOpen(false); button.current?.focus(); };
  React.useEffect(() => {
    if (!open) return;
    const pointer = event => { if (!menu.current?.contains(event.target)) setOpen(false); };
    const key = event => { if (event.key === 'Escape') { event.stopPropagation(); close(); } };
    document.addEventListener('pointerdown', pointer);
    document.addEventListener('keydown', key);
    return () => { document.removeEventListener('pointerdown', pointer); document.removeEventListener('keydown', key); };
  }, [open]);
  const read = async (method = 'refreshConversationCatalog') => {
    if (busy || !anchor) return;
    setBusy(true); setError('');
    try { await authority[method](anchor.root); }
    catch (failure) { setError(failure.message || 'Could not read conversations.'); }
    finally { setBusy(false); }
  };
  const toggle = () => { if (open) close(); else { setOpen(true); if (anchor) read(); } };
  const choose = root => { setConversationRoot(root); close(); };
  const create = async event => {
    event.preventDefault();
    if (busy || !anchor || !catalog?.can_create) return;
    setBusy(true); setError('');
    try {
      const participant_roots = (catalog.participants || []).filter(row =>
        row.root === catalog.self || chosen.includes(row.root)).map(row => row.root);
      const result = await authority.createConversation(anchor.root, {title, participant_roots});
      if (result?.accepted) setSaved(result);
    } catch (failure) { setError(failure.message || 'Creation is not confirmed. Retry the same request.'); }
    finally { setBusy(false); }
  };
  const control = {background:LM.bg, color:LM.ink, border:`1px solid ${LM.line}`,
    borderRadius:LM.rad.sm, padding:'7px 9px', fontFamily:LM.sans, fontSize:12};
  return <div ref={menu} style={{position:'relative', minWidth:0}}>
    <button ref={button} onClick={toggle} aria-label="Conversations" aria-haspopup="dialog" aria-expanded={open}
      title={selected?.label || 'Conversations'} style={{...control, border:0, maxWidth:180,
        overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', cursor:'pointer'}}>
      {selected?.label || 'Conversations'} <span aria-hidden="true">⌄</span>
    </button>
    {open && <div role="dialog" aria-label="Workshop conversations" style={{position:'absolute', top:'calc(100% + 6px)',
      right:0, zIndex:300, width:340, maxWidth:'calc(100vw - 70px)', maxHeight:'min(70vh, 600px)', overflowY:'auto',
      background:LM.bgPanel, color:LM.ink, border:`1px solid ${LM.line}`, borderRadius:LM.rad.md,
      boxShadow:'0 12px 32px #0008', padding:12, fontSize:12}}>
      <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:8}}>
        <strong>Conversations</strong>
        {anchor && <button disabled={busy} onClick={() => read()} title="Refresh conversations" aria-label="Refresh conversations"
          style={{...control, display:'grid', placeItems:'center', padding:5}}><StudioHeaderIcon name="reload"/></button>}
      </div>
      <p style={{color:LM.inkSoft, margin:'0 0 10px', lineHeight:1.5}}>Saved rooms and their participants. A saved room does not mean its agents are running.</p>
      <div style={{display:'grid', gap:4}}>
        <button disabled={busy} onClick={() => choose('')} aria-current={!conversationRoot ? 'true' : undefined}
          style={{...control, textAlign:'left', cursor:'pointer', background:!conversationRoot ? LM.accentDim : LM.bg}}>
          Current conversation
        </button>
        {(catalog?.conversations || workshops.map(row => ({root:row.root, title:row.label}))).map(row => {
          const visible = workshops.some(item => item.root === row.root);
          return <button key={row.root} disabled={!visible || busy} onClick={() => choose(row.root)}
            aria-current={conversationRoot === row.root ? 'true' : undefined}
            title={visible ? row.title : 'Open the Workshop canvas to reach this conversation'}
            style={{...control, textAlign:'left', overflowWrap:'anywhere', cursor:visible ? 'pointer' : 'default',
              background:conversationRoot === row.root ? LM.accentDim : LM.bg}}>
            <div>{row.title}</div>
            {row.participant_roots && <small style={{color:LM.inkSoft}}>{row.participant_roots.length} participants{!visible ? ' · on Workshop canvas' : ''}</small>}
          </button>;
        })}
      </div>
      {catalog?.page_after && <button disabled={busy} onClick={() => read('showFirstConversationPage')} style={{...control, marginTop:8}}>First page</button>}
      {catalog?.has_more && <button disabled={busy} onClick={() => read('loadNextConversationPage')} style={{...control, margin:'8px 0 0 6px'}}>More conversations</button>}
      {catalog?.can_create && !creating && <button disabled={busy} onClick={() => { setCreating(true); setChosen([]); }}
        style={{...control, width:'100%', marginTop:12, cursor:'pointer'}}>＋ New conversation</button>}
      {creating && <form onSubmit={create} style={{marginTop:12, borderTop:`1px solid ${LM.line}`, paddingTop:12}}>
        <label style={{display:'block'}}>Conversation name
          <input autoFocus required disabled={busy || creation?.accepted} value={title} maxLength={512}
            onChange={event => setTitle(event.target.value)} placeholder="Wall conversion workflow"
            style={{...control, display:'block', width:'100%', margin:'6px 0 10px', boxSizing:'border-box'}}/>
        </label>
        <fieldset disabled={busy || creation?.accepted} style={{border:0, margin:0, padding:0}}>
          <legend style={{marginBottom:6}}>Participants</legend>
          {(catalog?.participants || []).filter(row => row.attached).map(row => <label key={row.root}
            style={{display:'flex', gap:7, alignItems:'center', marginBottom:7, overflowWrap:'anywhere'}}>
            <input type="checkbox" checked={row.root === catalog.self || chosen.includes(row.root)} disabled={row.root === catalog.self}
              onChange={event => setChosen(old => event.target.checked ? [...old, row.root] : old.filter(root => root !== row.root))}/>
            {row.label}{row.root === catalog.self ? ' (you)' : ''}
          </label>)}
        </fieldset>
        {!creation?.accepted && <button type="submit" disabled={busy || !catalog?.can_create || !title.trim()}
          style={{...control, marginTop:6}}>{busy ? 'Saving…' : error ? 'Retry creation' : 'Create conversation'}</button>}
        {creation?.accepted && <div role="status" style={{marginTop:8, lineHeight:1.5}}>
          Saved: {creation.title}. {creation.error || creation.notice || creation.warning}
          {workshops.some(row => row.root === creation.root) && <button type="button" onClick={() => choose(creation.root)}
            style={{...control, margin:'6px 0'}}>Open conversation</button>}
          <button type="button" onClick={() => { setSaved(null); setTitle(''); setChosen([]); setCreating(false); }}
            style={{...control, margin:'6px'}}>Done</button>
        </div>}
      </form>}
      {(catalog?.can_create || state?.workshop?.root === (selected || anchor)?.root && state.workshop.can_manage_history) &&
        (selected || anchor) && typeof authority.reviewConversationPages === 'function' &&
        <WorkshopStorageReview key={(selected || anchor).root} root={(selected || anchor).root} label={(selected || anchor).label}/>}
      {(error || catalog?.error) && <p role="alert" style={{color:LM.err, lineHeight:1.5}}>{error || catalog.error}</p>}
      {busy && <div role="status" style={{marginTop:8, color:LM.inkSoft}}>Updating…</div>}
    </div>}
  </div>;
};

// ── Chat · Workshop · Canvas (design studio-lm.jsx:270-272, 1136-1143). "Workshop" is not a
// fourth mode here: it is Chat with a conversation root from the real Workshop scope
// (window.ARCHHUB_EXISTING_WORKSHOP.getSnapshot().workshops, fed by canvas.workshop_scope).
// The segment selects the held room, else the general room, else the first; Chat clears the
// root; no room in scope disables the segment and says so. Nothing about agents, tasks or
// progress is inferred from the choice.
const workshopModeRoom = (workshops, conversationRoot) => conversationRoot ||
  workshops.find(row => row?.is_general === true && row.root)?.root || workshops.find(row => row?.root)?.root || '';
// The owner states why no Workshop room is available (workshop_scope.unavailable).
const workshopUnavailableText = reason => (typeof reason === 'string' && reason.trim()) ||
  'No Workshop conversation in this scope';
// Workshop is never disabled into silence: without a room the click answers with that reason.
const workshopModeSegments = ({mode, conversationRoot = '', workshops = [], unavailable = ''}) => {
  const room = workshopModeRoom(workshops, conversationRoot);
  const active = mode === 'chat' ? (conversationRoot ? 'workshop' : 'chat') : mode;
  return [['chat', 'Chat'], ['workshop', 'Workshop'], ['canvas', 'Canvas']].map(([key, label]) => ({
    key, label, active:active === key, disabled:false, unavailable:key === 'workshop' && !room,
    title:key === 'workshop' && !room ? workshopUnavailableText(unavailable) : undefined,
  }));
};
const chooseWorkshopMode = (key, {mode, conversationRoot = '', workshops = [], setMode, setConversationRoot,
  unavailable = '', onUnavailable}) => {
  if (key === 'canvas' || typeof setConversationRoot !== 'function') return setMode(key === 'canvas' ? 'canvas' : 'chat');
  const room = key === 'workshop' ? workshopModeRoom(workshops, conversationRoot) : '';
  if (key === 'workshop' && !room) {
    const reason = workshopUnavailableText(unavailable);
    if (typeof onUnavailable === 'function') onUnavailable(reason);
    return reason;
  }
  if (typeof onUnavailable === 'function') onUnavailable('');
  if (mode !== 'chat' || room !== conversationRoot) setConversationRoot(room);
};

// Workspace header uses workspace tabs and one compact conversation menu.
const WsHeader = ({ session, model, openTabs, setOpenId, closeTab, mode, setMode, setPickerOpen, setSettingsOpen, onHome,
  workshops = [], conversationRoot = '', setConversationRoot, workshopModel, conversationNotice = '',
  workshopUnavailable = '' }) => {
  const [workshopRefusal, setWorkshopRefusal] = React.useState('');
  const workshopRefused = workshopRefusal && !workshopModeRoom(workshops, conversationRoot) ? workshopRefusal : '';
  return (
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
      {/* New session after the tabs (design studio-lm.jsx:1123-1129). Home is where a session or a graph starts. */}
      <button type="button" onClick={onHome} title="Start a new session from Home" aria-label="Start a new session from Home" style={{
        width:26, height:26, padding:0, border:0, borderRadius:LM.rad.sm,
        background:'transparent', color:LM.inkMuted, cursor:'pointer', flexShrink:0,
        display:'grid', placeItems:'center', fontSize:14,
      }}
      onMouseEnter={e => e.currentTarget.style.background = LM.bgSoft}
      onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>+</button>
    </div>

    {/* Chat and Canvas draw the design row. While a Workshop conversation is open, its source menu sits beside the switch. */}
    {workshops.length > 0 && mode === 'chat' && conversationRoot && (window.ARCHHUB_EXISTING_WORKSHOP?.refreshConversationCatalog ?
        <WorkshopConversationMenu key={JSON.stringify([workshops.find(row => row.is_general)?.root, session.id])}
          workshops={workshops} conversationRoot={conversationRoot} setConversationRoot={setConversationRoot}/> :
        <select aria-label="Conversation source" value={conversationRoot}
        onChange={event => setConversationRoot(event.target.value)} style={{maxWidth:180,
          background:LM.bg, color:LM.ink, border:0, fontFamily:LM.sans, fontSize:12}}>
        <option value="">Conversation</option>
        {workshops.map(row => <option key={row.root} value={row.root}>{row.label}</option>)}
      </select>)}

    <div style={{
      display:'flex', alignItems:'center', gap:1, padding:2, background:LM.bg,
      border:`1px solid ${LM.line}`, borderRadius:LM.rad.md, flexShrink:0,
    }}>
      {workshopModeSegments({mode, conversationRoot, workshops, unavailable:workshopUnavailable}).map(segment => (
        <button key={segment.key} type="button" disabled={segment.disabled} title={segment.title} aria-pressed={segment.active}
          aria-disabled={segment.unavailable ? 'true' : undefined}
          onClick={() => chooseWorkshopMode(segment.key, {mode, conversationRoot, workshops, setMode, setConversationRoot,
            unavailable:workshopUnavailable, onUnavailable:setWorkshopRefusal})} style={{
          padding:'4px 11px', borderRadius:LM.rad.sm, border:0, cursor:segment.disabled ? 'default' : 'pointer',
          background:segment.active ? LM.accentDim : 'transparent',
          outline:segment.disabled || segment.unavailable ? `1px dashed ${LM.line}` : 'none', outlineOffset:-1,
          color:segment.active ? LM.accent : LM.inkSoft,
          fontFamily:LM.sans, fontSize:11.5, fontWeight:segment.active ? 500 : 400,
        }}>{segment.label}</button>
      ))}
    </div>

    {workshopRefused && <span role="alert" title={workshopRefused} style={{fontSize:11,
      color:LM.ink, maxWidth:320, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>
      {workshopRefused}</span>}
    {conversationNotice && <span role="status" title={conversationNotice} style={{fontSize:11,
      color:LM.inkSoft, maxWidth:220, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>
      {conversationNotice}</span>}
    {/* The model chip, fork and save as skill are drawn in every mode (design studio-lm.jsx:1146-1148).
        In a Workshop conversation the chip names the conversation's own model when it has one. */}
    <ModelStrip model={conversationRoot && workshopModel ? {...model, name:workshopModel, route:workshopModel,
      routed:workshopModel, vendor:'Workshop conversation', tag:'', ctx:'', latency:null} : model}
      setPickerOpen={setPickerOpen} compact/>
    {/* fork and save as skill have no binding in this build: drawn, disabled, and saying so. */}
    <HoverBtn disabled title="Fork is not available in this build">fork</HoverBtn>
    <HoverBtn primary disabled title="Save as skill is not available in this build">save as skill</HoverBtn>
    {/* The update icons stay in the header (founder, 2026-09-18: "just bring the update icons back").
        Settings > About keeps the full controls; the restart still needs the confirming second click. */}
    <ApplicationUpdateControls compact/>
  </div>
  );
};

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
const HoverBtn = ({ primary, onClick, children, style, disabled, title, 'aria-label':ariaLabel }) => {
  const [h, setH] = React.useState(false);
  return (
    <button
      disabled={disabled} title={title} aria-label={ariaLabel}
      onClick={onClick}
      onMouseEnter={() => setH(true)}
      onMouseLeave={() => setH(false)}
      style={{
        ...smallBtn(primary),
        ...(primary
          ? { filter: h ? 'brightness(1.12)' : 'none' }
          : { background: h ? LM.bgHover : 'transparent', borderColor: h ? LM.accent+'66' : LM.line, color: h ? LM.ink : LM.inkSoft }),
        ...style,
        // Disabled controls use a dashed border, never alpha (design DECISIONS.md, node-logic section).
        ...(disabled ? {background:'transparent', borderColor:LM.line, borderStyle:'dashed', color:LM.inkSoft, cursor:'default', filter:'none'} : {}),
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
        {[model.vendor, model.ctx ? 'ctx ' + model.ctx : '', model.tag].filter(Boolean).join(' \u00b7 ')}
      </div>
    </div>
    {/* Draw or omit: no latency dot until a latency was measured. */}
    {model.latency != null && <span style={{ fontFamily:LM.mono, fontSize:9, color:LM.ok, letterSpacing:'0.08em' }}>{'\u25cf ' + model.latency + 'ms'}</span>}
    <span style={{ color:LM.inkSoft, fontSize:11, marginLeft:2 }}>▾</span>
  </button>
  );
};

// ──────────────────────── NODE CANVAS ────────────────────────
const SOCKET_TOP = 42;
const SOCKET_STEP = 19;
const SOCKET_R = 5;

const socketY = (i) => SOCKET_TOP + i * SOCKET_STEP;
// Snap to grid (design CanvasMenu) uses the dot grid's own 20-unit pitch.
const CANVAS_GRID = 20;

const canvasConnectedNodeIds = (nodeIds, wires, seeds, whole) => {
  const adjacency = new Map(nodeIds.map(id => [id, new Set()]));
  for (const wire of wires) {
    const from = wire.from?.[0], to = wire.to?.[0];
    if (adjacency.has(from) && adjacency.has(to)) { adjacency.get(from).add(to); adjacency.get(to).add(from); }
  }
  const found = new Set(seeds.filter(id => adjacency.has(id))), queue = [...found];
  for (let index = 0; index < queue.length; index++) {
    for (const id of adjacency.get(queue[index])) {
      if (!found.has(id)) { found.add(id); if (whole) queue.push(id); }
    }
  }
  return [...found];
};
const canvasFitBounds = (ids, positions, sizes, viewport) => {
  const width = viewport.width - 48, height = viewport.height - 152;
  const left = Math.min(...ids.map(id => positions[id].x)), top = Math.min(...ids.map(id => positions[id].y));
  const right = Math.max(...ids.map(id => positions[id].x + sizes[id].w));
  const bottom = Math.max(...ids.map(id => positions[id].y + sizes[id].h));
  const zoom = Math.min(2, width / Math.max(1, right - left), height / Math.max(1, bottom - top));
  if (!ids.length || !Number.isFinite(zoom) || zoom < 0.01 || width < 1 || height < 1) {
    throw new Error('The selected bounds are too large for this view. Fit a smaller selection.');
  }
  return {zoom, pan:{x:24 + width / 2 - (left + right) * zoom / 2,
    y:72 + height / 2 - (top + bottom) * zoom / 2}, bounds:{left, top, right, bottom}};
};
const canvasArrangePositions = (ids, positions, sizes, allIds, wires) => {
  const stable = [...ids].sort((a, b) => positions[a].y - positions[b].y || positions[a].x - positions[b].x || a.localeCompare(b));
  const rank = new Map(stable.map((id, index) => [id, index]));
  const neighbours = new Map(stable.map(id => [id, new Set()])), outgoing = new Map(stable.map(id => [id, new Set()]));
  const indegree = new Map(stable.map(id => [id, 0]));
  for (const wire of wires) {
    const from = wire.from?.[0], to = wire.to?.[0];
    if (!rank.has(from) || !rank.has(to) || from === to || outgoing.get(from).has(to)) continue;
    neighbours.get(from).add(to); neighbours.get(to).add(from);
    outgoing.get(from).add(to); indegree.set(to, indegree.get(to) + 1);
  }
  const remaining = new Set(stable), groups = [];
  for (const seed of stable) {
    if (!remaining.has(seed)) continue;
    const component = new Set([seed]), queue = [seed];
    for (let index = 0; index < queue.length; index++) for (const id of neighbours.get(queue[index])) {
      if (!component.has(id)) { component.add(id); queue.push(id); }
    }
    const pending = new Set([...component].sort((a, b) => rank.get(a) - rank.get(b))), order = [];
    while (pending.size) {
      // Break cycles in stable visual order; acyclic edges retain upstream-first order.
      const id = [...pending].find(root => indegree.get(root) === 0) || pending.values().next().value;
      pending.delete(id); remaining.delete(id); order.push(id);
      for (const target of outgoing.get(id)) indegree.set(target, indegree.get(target) - 1);
    }
    groups.push(order);
  }
  const gap = 48, totalArea = stable.reduce((area, id) => area + (sizes[id].w + gap) * (sizes[id].h + gap), 0);
  const shelfWidth = Math.max(...stable.map(id => sizes[id].w), Math.sqrt(totalArea * 1.4));
  const local = {};
  let x = 0, y = 0, rowHeight = 0, packedWidth = 0;
  for (const group of groups) {
    if (x) { x = 0; y += rowHeight + gap; rowHeight = 0; }
    for (const id of group) {
      const size = sizes[id];
      if (x && x + size.w > shelfWidth) { x = 0; y += rowHeight + gap; rowHeight = 0; }
      local[id] = {x, y}; packedWidth = Math.max(packedWidth, x + size.w);
      x += size.w + gap; rowHeight = Math.max(rowHeight, size.h);
    }
  }
  const packedHeight = y + rowHeight, originX = Math.round(Math.min(...stable.map(id => positions[id].x)));
  let originY = Math.round(Math.min(...stable.map(id => positions[id].y)));
  const included = new Set(stable), obstacles = allIds.filter(id => !included.has(id));
  for (let pass = 0; pass <= obstacles.length; pass++) {
    const hits = obstacles.filter(id => {
      const point = positions[id], size = sizes[id];
      return originX < point.x + size.w + gap && originX + packedWidth + gap > point.x &&
        originY < point.y + size.h + gap && originY + packedHeight + gap > point.y;
    });
    if (!hits.length) break;
    originY = Math.ceil(Math.max(...hits.map(id => positions[id].y + sizes[id].h + gap)));
  }
  return Object.fromEntries(stable.map(id => [id, {x:originX + local[id].x, y:originY + local[id].y}]));
};

// A drag is a gesture, not a save. Every mouseup used to publish its own signed
// revision, so a burst of ten drags cost ten commits and ten receipts on the
// founder graph. A burst is written ONCE now, after the canvas has been still
// for this long; a drag inside the window extends it and merges into it.
const CANVAS_LAYOUT_COALESCE_MS = 500;
// The merged burst keeps the point each node started the BURST at, so a refusal
// restores the last confirmed layout and one undo reverses the whole burst.
const mergeCanvasLayoutBurst = (pending, drag) => {
  if (!drag || !drag.next || !drag.before) return pending || null;
  if (!pending) return {next:{...drag.next}, before:{...drag.before}, revision:drag.revision};
  return {
    next:{...pending.next, ...drag.next},
    before:Object.fromEntries([...Object.entries(drag.before), ...Object.entries(pending.before)]),
    revision:pending.revision,
  };
};
// Nothing is written for a node the burst put back where it started.
const canvasLayoutBurstMoves = burst => Object.entries(burst?.next || {})
  .filter(([id, point]) => burst.before[id]?.x !== point.x || burst.before[id]?.y !== point.y);
// A burst is movement the store has not been told about yet. That is cheap to leave a
// trace of: the merged burst is mirrored into sessionStorage on every arm and removed
// only when a write is confirmed, so a canvas that comes back after a crash, a kill or a
// closed window says which positions were never saved instead of losing them in silence.
const CANVAS_LAYOUT_TRACE_KEY = 'archhub.canvas.unwritten-layout';
const readCanvasLayoutTrace = scope => {
  try {
    const held = JSON.parse(window.sessionStorage.getItem(CANVAS_LAYOUT_TRACE_KEY) || 'null');
    return held && held.scope === scope && Object.keys(held.next || {}).length ? held : null;
  } catch (error) { return null; }
};
const writeCanvasLayoutTrace = (scope, burst) => {
  try {
    if (!burst) window.sessionStorage.removeItem(CANVAS_LAYOUT_TRACE_KEY);
    else window.sessionStorage.setItem(CANVAS_LAYOUT_TRACE_KEY, JSON.stringify(
      {scope, next:burst.next, before:burst.before, revision:burst.revision, at:Date.now()}));
  } catch (error) { /* a session with no storage still draws and still saves the canvas */ }
};

const NodeCanvas = ({ focusId, setFocusId, setLibraryOpen, userNodes = [], addNodeFromLibrary, model }) => {
  const authorityState = useStudioProjection();
  const graph = authorityState?.graph || LM_GRAPH;
  const authority = window.ARCHHUB_STUDIO_AUTHORITY;
  const normal = !authority && window.ARCHHUB_EXISTING_WORKSHOP;
  const [wireStart, setWireStart] = React.useState(null);
  const [wireError, setWireError] = React.useState('');
  React.useEffect(() => { setWireStart(null); setWireError(''); }, [authorityState?.canvas?.scope?.current]);
  const useSocket = async (root, port, side) => {
    if ((!authority && !normal) || authorityState?.pending || saving.current || layoutNeedsRefresh) return;
    setWireError('');
    if (normal && (authorityState?.requires_refresh || port.mode !== 'connection')) {
      setWireError(authorityState?.requires_refresh ? 'Refresh the canvas before editing connections.' :
        'This port does not expose a connection command.');
      return;
    }
    if (side === 'out') {
      if (normal && (!port.connect_control || !port.connect_choices?.length)) {
        setWireError('This output has no current compatible connection choices.'); return;
      }
      setWireStart({root, port}); return;
    }
    if (!wireStart) { setWireError('Choose an output first, then a compatible input.'); return; }
    try {
      if (authority) await authority.connect(wireStart.root, wireStart.port.id, root, port.id);
      else await normal.connectTopology(wireStart.root, wireStart.port.id, root, port.id);
      setWireStart(null);
    } catch (error) { setWireError(error.message || 'The connection was refused.'); }
  };
  const allNodes = React.useMemo(() => [...graph.nodes, ...userNodes], [graph.nodes, userNodes]);
  const scopeKey = studioCanvasScope(authorityState?.canvas);
  const mountedScope = React.useRef(scopeKey);
  const alive = React.useRef(true);
  const saving = React.useRef(false);
  const dragRef = React.useRef(null);
  const wrapRef = React.useRef(null);
  const saveRef = React.useRef(null);
  // What a burst of drags holds until the canvas goes still, and whether the chip
  // must say so. Nothing here blocks the canvas: the preview is already drawn.
  const burstRef = React.useRef(null);
  const burstTimer = React.useRef(null);
  const suppressNodeClick = React.useRef(false);
  const MAX_LAYOUT_NODES = 256;
  const [selectedIds, setSelectedIds] = React.useState([]);
  const selected = new Set(selectedIds.filter(id => allNodes.some(node => node.id === id)));
  const [layoutBusy, setLayoutBusy] = React.useState(false);
  const [layoutError, setLayoutError] = React.useState('');
  const [layoutNeedsRefresh, setLayoutNeedsRefresh] = React.useState(false);
  const [undoLayout, setUndoLayout] = React.useState(null);
  const [burstPending, setBurstPending] = React.useState(false);
  const revision = authorityState?.canvas?.revision;
  const scopeStillCurrent = () => alive.current && mountedScope.current === scopeKey &&
    studioCanvasScope(authority ? authority.getSnapshot()?.canvas : normal?.getSnapshot()?.topology?.canvas) === scopeKey;
  const blocked = layoutBusy || layoutNeedsRefresh || !!authorityState?.pending || !!authorityState?.requires_refresh;
  // `blocked` is a render snapshot, and the write path must not read it. The save it is
  // waiting on answers before React commits the render that clears it, so a burst parked
  // on `blocked` waits on something that has already stopped being true, and is then
  // either re-armed for ever or re-parked in a queue with nothing left to drain it
  // (verification, 2026-09-18: a burst armed during an in-flight save left saves == 1
  // with the chip still on; the same burst on the leave path wrote nothing at all).
  // The transport answers now, and `saving.current` already says whether OUR save is out;
  // the render snapshot stays exactly where it belongs, on the controls it disables.
  const needsRefresh = React.useRef(false);
  const transportBusy = () => {
    const held = authority ? authority.getSnapshot() : normal?.getSnapshot()?.topology;
    return needsRefresh.current || !!held?.pending || !!held?.requires_refresh;
  };
  const [unwrittenLayout, setUnwrittenLayout] = React.useState(() => readCanvasLayoutTrace(scopeKey));
  React.useEffect(() => { setUnwrittenLayout(readCanvasLayoutTrace(scopeKey)); }, [scopeKey]);
  const canSaveLayout = !!(authority?.moveMany || normal?.moveTopologyNodes) && Number.isSafeInteger(revision);
  // These positions are a gesture preview; the owner commits every completed map.
  const [positions, setPositions] = React.useState(() =>
    Object.fromEntries(allNodes.map(n => [n.id, { x: n.x, y: n.y }]))
  );
  React.useEffect(() => {
    setPositions(p => {
      const next = {};
      let changed = Object.keys(p).length !== allNodes.length;
      allNodes.forEach(n => {
        const held = p[n.id], protectedPreview = saving.current
          || !!dragRef.current?.before?.[n.id] || !!burstRef.current?.next?.[n.id];
        next[n.id] = protectedPreview && held ? held : {x:n.x, y:n.y};
        if (!held || held.x !== next[n.id].x || held.y !== next[n.id].y) changed = true;
      });
      return changed ? next : p;
    });
    setSelectedIds(ids => ids.filter(id => allNodes.some(node => node.id === id)));
  }, [allNodes, layoutBusy]);
  React.useEffect(() => {
    alive.current = true;
    return () => { flushRef.current(true); alive.current = false; pendingArrange.current = null; dragRef.current = null; };
  }, []);

  // A drag that ends while the previous save is still in flight is queued, not
  // dropped: on a large graph a save takes long enough that the next drag used
  // to land inside it and vanish with "Wait for the current change".
  // A burst handed over while a save is in flight waits here and goes out when that save
  // answers. One slot is enough: a drag cannot START while a save is in flight, so only
  // the drag already under the hand when the save left can arm a burst behind it.
  const queuedSave = React.useRef(null);
  const pendingArrange = React.useRef(null);
  const arrangeRunning = React.useRef(false);
  // `force` marks a save handed over on the way out (unmount, window close). It still
  // queues behind the save in flight, but it is not dropped when this canvas stops
  // being alive: the transport outlives the component.
  const savePositions = async (next, before, expectedRevision, remember = true, force = false) => {
    if (!scopeStillCurrent()) { pendingArrange.current = null; return false; }
    const entries = Object.entries(next).filter(([id, point]) => before[id]?.x !== point.x || before[id]?.y !== point.y);
    if (!entries.length) return true;
    const restore = () => setPositions(held => ({...held, ...before}));
    // A save that arrives while one is in flight queues behind it rather than being
    // refused with "Wait for the current change"; on the way out there is no later drag
    // to retry it, and a save behind a save is exactly what a burst needs to survive.
    if (saving.current && canSaveLayout && entries.length <= MAX_LAYOUT_NODES) {
      // The preview already shows the new place; the save runs right after the current one.
      queuedSave.current = {next, before, expectedRevision, remember, force};
      return true;
    }
    // The transport, never the render snapshot: the echo of a save that has just answered
    // must not refuse the burst that was waiting for exactly that save.
    const busy = transportBusy();
    if (!canSaveLayout || (busy && !force) || saving.current || entries.length > MAX_LAYOUT_NODES) {
      pendingArrange.current = null;
      restore();
      setLayoutError(entries.length > MAX_LAYOUT_NODES ? 'Move or arrange at most 256 nodes at a time.' :
        busy || saving.current ? 'Wait for the current change, then try again.' : 'This connection cannot save node positions.');
      return false;
    }
    const changes = Object.fromEntries(entries);
    const expectedPositions = Object.fromEntries(entries.map(([id]) => [id, before[id]]));
    saving.current = true; setLayoutBusy(true); setLayoutError('');
    setPositions(held => ({...held, ...changes}));
    try {
      if (authority) await authority.moveMany(changes, expectedRevision, expectedPositions);
      else await normal.moveTopologyNodes(changes, expectedRevision, expectedPositions);
      if (!scopeStillCurrent()) return false;
      setUndoLayout(remember ? {before:Object.fromEntries(entries.map(([id]) => [id, before[id]])), after:changes} : null);
      // Confirmed, and nothing else is owed: there is no unwritten movement left to report.
      if (!burstRef.current && !queuedSave.current) writeCanvasLayoutTrace(scopeKey, null);
      return true;
    } catch (error) {
      if (scopeStillCurrent()) {
        restore(); setUndoLayout(null); queuedSave.current = null; pendingArrange.current = null;
        burstRef.current = null; clearLayoutBurstTimer(); setBurstPending(false);
        // A refused save used to lock every later save behind a manual refresh.
        // Refresh once here instead; the next drag starts from the reconciled canvas.
        let recovered = false;
        try {
          if (authority) await authority.load();
          else if (normal) await normal.refreshTopologyCanvas();
          recovered = !!(authority || normal);
        } catch (refreshError) { recovered = false; }
        if (scopeStillCurrent()) {
          needsRefresh.current = !recovered; setLayoutNeedsRefresh(!recovered);
          setLayoutError((error.message || 'Positions could not be confirmed.')
            + ' The last confirmed layout was restored.' + (recovered
            ? ' The canvas was reloaded; move the node again.'
            : ' Refresh the canvas to reconcile any saved positions.'));
        }
      }
      return false;
    } finally {
      saving.current = false;
      const queued = queuedSave.current;
      queuedSave.current = null;
      const handOver = !!queued && (alive.current || queued.force) && scopeStillCurrent();
      // The receipt does not blink off while a handed-over save is still owed.
      if (alive.current) setLayoutBusy(handOver);
      if (handOver) {
        // Run the queued drag against the canvas as it is now; its `before` is the
        // preview the drag started from, which is what the server holds after the save.
        setTimeout(() => saveRef.current && saveRef.current(queued.next, queued.before, queued.expectedRevision, queued.remember, queued.force), 0);
      }
    }
  };
  saveRef.current = savePositions;

  const clearLayoutBurstTimer = () => {
    if (burstTimer.current) { clearTimeout(burstTimer.current); burstTimer.current = null; }
  };
  // One write for everything moved in the burst, against the points the burst started
  // from. A save already in flight is NOT a reason to wait another window: the burst is
  // handed to savePositions, which parks it behind that save and sends it when that save
  // answers. Waiting instead meant waiting on a render snapshot that had already stopped
  // being true, and the burst was never written at all (verification, 2026-09-18).
  // Only a canvas that cannot take a write -- a refresh is owed, or the transport is busy
  // with something that is not our save -- waits, and only while the canvas is still there
  // to fire the timer. `force` is the leave path: unmount, window close, tab hide.
  const flushLayoutBurst = (force = false) => {
    clearLayoutBurstTimer();
    const burst = burstRef.current;
    if (!burst) return false;
    if (transportBusy() && alive.current && !force) {
      burstTimer.current = setTimeout(() => flushRef.current(), CANVAS_LAYOUT_COALESCE_MS);
      return false;
    }
    burstRef.current = null;
    if (alive.current) setBurstPending(false);
    const moves = canvasLayoutBurstMoves(burst);
    if (!moves.length) return false;
    saveRef.current(Object.fromEntries(moves), burst.before, burst.revision, true, force);
    return true;
  };
  const flushRef = React.useRef(null);
  flushRef.current = flushLayoutBurst;
  // The canvas stays interactive: the drag is merged and the window restarted,
  // and the write happens in the background when the canvas goes still.
  const armLayoutBurst = drag => {
    burstRef.current = mergeCanvasLayoutBurst(burstRef.current, drag);
    writeCanvasLayoutTrace(scopeKey, burstRef.current);
    setUnwrittenLayout(null);
    setBurstPending(!!canvasLayoutBurstMoves(burstRef.current).length);
    clearLayoutBurstTimer();
    burstTimer.current = setTimeout(() => flushRef.current(), CANVAS_LAYOUT_COALESCE_MS);
  };
  const armLayoutRef = React.useRef(null);
  armLayoutRef.current = armLayoutBurst;
  // Leaving the canvas, closing the window and a quit request all write first.
  React.useEffect(() => {
    const leave = () => flushRef.current(true);
    window.addEventListener('beforeunload', leave);
    window.addEventListener('pagehide', leave);
    return () => {
      window.removeEventListener('beforeunload', leave);
      window.removeEventListener('pagehide', leave);
    };
  }, []);

  const [pan, setPan] = React.useState({ x: 14, y: 12 });
  const [zoom, setZoom] = React.useState(0.66);
  const [ctxMenu, setCtxMenu] = React.useState(null);
  const closeContextMenu = () => {
    setCtxMenu(null);
    if (ctxMenu?.opener?.isConnected) ctxMenu.opener.focus({preventScroll:true});
  };
  const [expanded, setExpanded] = React.useState({});
  const [dropTarget, setDropTarget] = React.useState(null); // {x,y} canvas-local
  // Snap to grid, on as drawn. A dragged node lands on the dot grid while it is on.
  const [snap, setSnap] = React.useState(true);
  const snapRef = React.useRef(snap);
  snapRef.current = snap;

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
    suppressNodeClick.current = false;
    if (ctxMenu) { e.preventDefault(); closeContextMenu(); }
    if (!e.shiftKey) setSelectedIds([]);
    dragRef.current = { mode:'pan', sx:e.clientX, sy:e.clientY, px:pan.x, py:pan.y };
  };

  const openContextMenu = (e, nodeId = null) => {
    e.preventDefault();
    e.stopPropagation();
    const rect = wrapRef.current.getBoundingClientRect();
    // Clamp so the menu never spills past the canvas edges (menu ≈ 220×350).
    const MENU_W = 220, MENU_H = Math.min(350, rect.height - 16);
    const opener = e.currentTarget;
    const anchor = opener.getBoundingClientRect();
    const keyboard = e.type === 'keydown';
    const rx = (keyboard ? anchor.left + 16 : e.clientX) - rect.left;
    const ry = (keyboard ? anchor.top + 24 : e.clientY) - rect.top;
    setCtxMenu({
      nodeId, opener, maxHeight:MENU_H,
      x: Math.max(8, Math.min(rx, rect.width  - MENU_W - 8)),
      y: Math.max(8, Math.min(ry, rect.height - MENU_H - 8)),
    });
  };
  const onContextMenu = e => {
    if (!e.target.closest('.lm-node') && !e.target.closest('[data-no-pan]')) openContextMenu(e);
  };
  const onNodeContextMenu = id => e => {
    if (e.target.isContentEditable || e.target.closest('input,textarea,select,[role="textbox"]')) return;
    if (!selected.has(id)) setSelectedIds([id]);
    setFocusId(id); openContextMenu(e, id);
  };
  const isContextKey = e => e.key === 'ContextMenu' || (e.key === 'F10' && e.shiftKey);
  const onCanvasKeyDown = e => {
    if (e.target === e.currentTarget && isContextKey(e)) { openContextMenu(e); return; }
    // The shortcuts the canvas menu names (design CanvasMenu), while focus is on the canvas and not in a field.
    if (!(e.metaKey || e.ctrlKey) || e.altKey || e.target.closest('input,textarea,select,[contenteditable="true"]')) return;
    const combo = (e.shiftKey ? 'shift+' : '') + String(e.key).toLowerCase();
    if (combo === 'a') { e.preventDefault(); setSelectedIds(allNodes.map(node => node.id)); return; }
    const item = canvasMenuItems.find(row => row.keys === combo);
    if (!item) return;
    e.preventDefault();
    if (!item.disabled && typeof item.action === 'function') item.action();
  };
  const onNodeKeyDown = id => e => {
    if (e.target === e.currentTarget && isContextKey(e)) onNodeContextMenu(id)(e);
  };
  const onNodeFocus = id => e => {
    if (suppressNodeClick.current) { suppressNodeClick.current = false; return; }
    if (e?.target.closest('button,input,textarea,select,a,[contenteditable="true"]')) return;
    if (e?.shiftKey) setSelectedIds(ids => ids.includes(id) ? ids.filter(root => root !== id) : [...ids, id]);
    else if (!selected.has(id)) setSelectedIds([id]);
    setFocusId(id);
  };

  const onNodeDragStart = (id) => (e) => {
    if (e.button !== 0 || e.target.closest('button,input,textarea,select,a')) return;
    e.stopPropagation();
    if (e.shiftKey) return;
    e.preventDefault();
    suppressNodeClick.current = false;
    const ids = selected.has(id) ? [...selected] : [id];
    setSelectedIds(ids); closeContextMenu();
    // A save in flight no longer swallows the next drag: the preview keeps the held
    // positions while it runs and the drag is queued behind it (see savePositions).
    if (!scopeStillCurrent() || layoutNeedsRefresh || !!authorityState?.pending || !!authorityState?.requires_refresh) return;
    if (!canSaveLayout || ids.length > MAX_LAYOUT_NODES) {
      setLayoutError(!canSaveLayout ? 'This connection cannot save node positions.' : 'Move or arrange at most 256 nodes at a time.');
      return;
    }
    const ourPreview = root => {
      const pending = burstRef.current?.next?.[root];
      return !!pending && pending.x === positions[root]?.x && pending.y === positions[root]?.y;
    };
    if (!saving.current && ids.some(root => !ourPreview(root) && !allNodes.some(node => node.id === root && node.x === positions[root]?.x && node.y === positions[root]?.y))) {
      setLayoutError('The canvas is receiving new positions. Try the drag again.'); return;
    }
    const before = Object.fromEntries(ids.filter(root => positions[root]).map(root => [root, {...positions[root]}]));
    dragRef.current = {mode:'nodes', sx:e.clientX, sy:e.clientY, before, zoom, revision, scope:scopeKey, lead:id};
  };

  React.useEffect(() => {
    const onMove = (e) => {
      const d = dragRef.current;
      if (!d) return;
      const dx = e.clientX - d.sx;
      const dy = e.clientY - d.sy;
      if (d.mode === 'pan') {
        setPan({ x: d.px + dx, y: d.py + dy });
      } else if (d.scope === mountedScope.current) {
        const mx = Math.round(dx / d.zoom), my = Math.round(dy / d.zoom);
        const place = value => snapRef.current ? Math.round(value / CANVAS_GRID) * CANVAS_GRID : value;
        const origin = d.before[d.lead];
        if (!origin) return;
        // Snap the grabbed member once, then translate the whole selection.
        // Returning to the pointer origin restores off-grid positions exactly.
        const tx = mx || my ? place(origin.x + mx) - origin.x : 0;
        const ty = mx || my ? place(origin.y + my) - origin.y : 0;
        if (!tx && !ty) {
          delete d.last;
          setPositions(p => ({...p, ...d.before}));
          return;
        }
        d.last = Object.fromEntries(Object.entries(d.before).map(([id, point]) => [id, {x:point.x + tx, y:point.y + ty}]));
        suppressNodeClick.current = true;
        setPositions(p => ({ ...p, ...d.last }));
      }
    };
    const onUp = () => {
      const drag = dragRef.current;
      dragRef.current = null;
      if (drag?.mode === 'nodes' && drag.last) {
        armLayoutRef.current({next:drag.last, before:drag.before, revision:drag.revision});
      }
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    return () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };
  }, []);

  const onWheel = (e) => {
    e.preventDefault();
    const rect = wrapRef.current.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const delta = -e.deltaY * 0.0015;
    const next = Math.max(0.01, Math.min(2, +(zoom * (1 + delta)).toFixed(3)));
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

  const focusWireIdx = authorityState ? graph.wires.findIndex(w => w.id === focusId) : (String(focusId).indexOf('wire:') === 0 ? +String(focusId).slice(5) : -1);
  const connectedIds = new Set([focusId]);
  graph.wires.forEach(w => {
    if (w.from[0] === focusId) connectedIds.add(w.to[0]);
    if (w.to[0]   === focusId) connectedIds.add(w.from[0]);
  });

  const unresolvedWires = [];
  const wires = graph.wires.map((w, i) => {
    const fromNode = nodeById[w.from[0]];
    const toNode   = nodeById[w.to[0]];
    if (!fromNode || !toNode) {
      unresolvedWires.push({i, id:w.id, reason:'An endpoint node is absent from this canvas.'});
      return null;
    }
    const hasSource = typeof w.from[1] === 'string' && w.from[1].length > 0;
    const hasTarget = typeof w.to[1] === 'string' && w.to[1].length > 0;
    const fromIdx = hasSource ? (fromNode.outs || []).findIndex(o => o.id === w.from[1]) : -1;
    const toIdx = hasTarget ? (toNode.ins || []).findIndex(o => o.id === w.to[1]) : -1;
    if (fromIdx < 0 || toIdx < 0) {
      unresolvedWires.push({i, id:w.id, reason:!hasSource || !hasTarget ?
        'The projection did not supply both port interfaces.' : 'A supplied port interface is absent from its node.'});
      return null;
    }
    const sourceWidth = fromNode.cat === 'ai' && expanded[fromNode.id] ? Math.max(520, fromNode.w) : fromNode.w;
    const x1 = fromNode.x + sourceWidth, y1 = fromNode.y + socketY(fromIdx);
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
  const measureCards = () => {
    if (document.fonts?.status === 'loading') {
      setLayoutError('Fonts are loading; try again in a moment.'); return null;
    }
    if (!wrapRef.current || allNodes.length > MAX_LAYOUT_NODES) {
      setLayoutError('Fit and Arrange support up to 256 visible nodes. Open a smaller canvas scope.'); return null;
    }
    const cards = new Map(Array.from(wrapRef.current.querySelectorAll('.lm-node[data-node-id]'))
      .map(element => [element.getAttribute('data-node-id'), element]));
    const sizes = {};
    for (const node of allNodes) {
      const card = cards.get(node.id), w = card?.offsetWidth, h = card?.offsetHeight;
      if (!w || !h || !Number.isFinite(positions[node.id]?.x) || !Number.isFinite(positions[node.id]?.y)) {
        setLayoutError('Wait for the node cards to finish rendering, then try again.'); return null;
      }
      const targetWidth = node.cat === 'ai' && expanded[node.id] ? Math.max(520, node.w) : node.w;
      sizes[node.id] = {w:Math.ceil(Math.max(w, targetWidth)), h:Math.ceil(h)};
    }
    return sizes;
  };
  const fitIds = ids => {
    if (!scopeStillCurrent() || !ids.length) return;
    const sizes = measureCards();
    if (!sizes) return;
    try {
      const result = canvasFitBounds(ids, positions, sizes, wrapRef.current.getBoundingClientRect());
      setZoom(result.zoom); setPan(result.pan); closeContextMenu();
    } catch (error) { setLayoutError(error.message); }
  };
  const selectConnected = whole => {
    if (!scopeStillCurrent()) return;
    if (allNodes.length > MAX_LAYOUT_NODES || graph.wires.length > 4096) {
      setLayoutError('Connected selection supports up to 256 nodes and 4096 visible wires. Open a smaller scope.'); return;
    }
    const nodeIds = allNodes.map(node => node.id);
    const seeds = ctxMenu?.nodeId
      ? (selected.has(ctxMenu.nodeId) ? [...selected] : [ctxMenu.nodeId])
      : selected.size ? [...selected] : nodeIds.includes(focusId) ? [focusId] : [];
    setSelectedIds(canvasConnectedNodeIds(nodeIds, graph.wires, seeds, whole));
  };
  const runPendingArrangeRef = React.useRef(null);
  const arrangeNeedsRefresh = () => needsRefresh.current || layoutNeedsRefresh ||
    !!(authority ? authority.getSnapshot() : normal?.getSnapshot()?.topology)?.requires_refresh;
  // Single-flight drain. Order matters: stale-scope, refresh-owed, auth, nodes,
  // wires, MAX all DISCARD; only our own in-flight save/burst/queue WAITS.
  const runPendingArrange = async () => {
    const wanted = pendingArrange.current;
    if (!wanted || arrangeRunning.current) return false;
    if (!alive.current || !scopeStillCurrent()) { pendingArrange.current = null; return false; }
    if (arrangeNeedsRefresh()) {
      pendingArrange.current = null;
      if (scopeStillCurrent()) setLayoutError('Refresh the canvas to reconcile any saved positions.');
      return false;
    }
    if (!canSaveLayout) {
      pendingArrange.current = null;
      if (scopeStillCurrent()) setLayoutError('This connection cannot save node positions.');
      return false;
    }
    const liveIds = wanted.ids.filter(id => allNodes.some(node => node.id === id));
    if (!liveIds.length || liveIds.length !== wanted.ids.length) {
      pendingArrange.current = null;
      if (scopeStillCurrent() && liveIds.length !== wanted.ids.length)
        setLayoutError('Arrange was discarded: some nodes are no longer on this canvas.');
      return false;
    }
    if (graph.wires.length > 4096) {
      pendingArrange.current = null;
      if (scopeStillCurrent()) setLayoutError('Arrange supports up to 4096 visible wires. Open a smaller scope.');
      return false;
    }
    if (liveIds.length > MAX_LAYOUT_NODES) {
      pendingArrange.current = null;
      if (scopeStillCurrent()) setLayoutError('Move or arrange at most 256 nodes at a time.');
      return false;
    }
    if (saving.current || burstRef.current || queuedSave.current || transportBusy()) return false;
    const sizes = measureCards();
    if (!sizes) return false;
    if (allNodes.some(node => positions[node.id]?.x !== node.x || positions[node.id]?.y !== node.y)) return false;
    pendingArrange.current = null;
    arrangeRunning.current = true;
    setLayoutError('');
    try {
      const before = Object.fromEntries(liveIds.map(id => [id, {...positions[id]}]));
      const next = canvasArrangePositions(liveIds, positions, sizes, allNodes.map(node => node.id), graph.wires);
      await savePositions(next, before, revision);
      return true;
    } catch (error) {
      if (scopeStillCurrent()) setLayoutError(error.message || 'Arrange could not be confirmed.');
      return false;
    } finally {
      arrangeRunning.current = false;
    }
  };
  runPendingArrangeRef.current = runPendingArrange;
  // Backstop: re-fire after reconciliation (positions/allNodes/permission/pending
  // are deps so a mismatch-parked slot drains; guard exits fast with no slot).
  React.useEffect(() => {
    if (!pendingArrange.current || arrangeRunning.current) return;
    if (layoutBusy || burstPending || saving.current) return;
    if (!scopeStillCurrent()) { pendingArrange.current = null; return; }
    runPendingArrangeRef.current && runPendingArrangeRef.current();
  }, [layoutBusy, burstPending, revision, scopeKey, positions, allNodes, canSaveLayout, !!authorityState?.pending, !!authorityState?.requires_refresh]);
  // Scope change discards the remembered click; refs die with unmount anyway.
  React.useEffect(() => {
    pendingArrange.current = null;
    arrangeRunning.current = false;
  }, [scopeKey]);
  const arrangeIds = async ids => {
    if (!alive.current || !scopeStillCurrent() || !ids.length) return;
    if (!canSaveLayout) { setLayoutError('This connection cannot save node positions.'); return; }
    const liveIds = ids.filter(id => allNodes.some(node => node.id === id));
    if (!liveIds.length) return;
    if (liveIds.length > MAX_LAYOUT_NODES) {
      setLayoutError('Move or arrange at most 256 nodes at a time.'); return;
    }
    if (arrangeNeedsRefresh()) {
      pendingArrange.current = null;
      setLayoutError('Refresh the canvas to reconcile any saved positions.'); return;
    }
    // Foreign-busy (transport held by what is not our save): refuse, never queue.
    if (transportBusy() && !saving.current && !queuedSave.current && !burstRef.current) {
      setLayoutError('Wait for the current change, then try again.'); return;
    }
    // Our-save busy: remember one click (latest intent wins, runs once).
    if (flushLayoutBurst() || saving.current || queuedSave.current || burstRef.current) {
      pendingArrange.current = {ids: [...liveIds]};
      setLayoutError('Arrange will run after the current save finishes.');
      return;
    }
    if (allNodes.some(node => positions[node.id]?.x !== node.x || positions[node.id]?.y !== node.y)) {
      setLayoutError('The canvas is receiving new positions. Try Arrange again.'); return;
    }
    if (graph.wires.length > 4096) { setLayoutError('Arrange supports up to 4096 visible wires. Open a smaller scope.'); return; }
    const expectedRevision = revision, sizes = measureCards();
    if (!sizes) return;
    const before = Object.fromEntries(liveIds.map(id => [id, {...positions[id]}]));
    const next = canvasArrangePositions(liveIds, positions, sizes, allNodes.map(node => node.id), graph.wires);
    await savePositions(next, before, expectedRevision);
  };
  const undoAvailable = !!undoLayout && Object.entries(undoLayout.after).every(([id, point]) =>
    allNodes.some(node => node.id === id && node.x === point.x && node.y === point.y) &&
    positions[id]?.x === point.x && positions[id]?.y === point.y);
  const undoPositions = () => {
    if (flushLayoutBurst()) {
      setLayoutError('Saving the moved nodes first. Try Reset positions again.'); return;
    }
    if (undoAvailable && !blocked) savePositions(undoLayout.before, undoLayout.after, revision, false);
  };
  const refreshCanvas = async () => {
    if (!scopeStillCurrent() || saving.current || authorityState?.pending) return;
    try {
      if (authority) await authority.load();
      else if (normal) await normal.refreshTopologyCanvas();
      else return;
      if (scopeStillCurrent()) { setLayoutError(''); setWireError(''); setLayoutNeedsRefresh(false); setUndoLayout(null); }
    } catch (error) { if (scopeStillCurrent()) setLayoutError(error.message || 'The canvas could not be refreshed.'); }
  };
  const allIds = allNodes.map(node => node.id);
  const menuHasSeed = !!ctxMenu?.nodeId || selected.size > 0 || allIds.includes(focusId);
  // Each action names why it is disabled; CanvasMenu shows that reason as the item title.
  const busyWhy = layoutBusy || authorityState?.pending ? 'Wait for the canvas to finish saving' : 'Refresh the canvas first';
  const noNodesWhy = 'This canvas has no nodes', noSelectionWhy = 'Nothing is selected', noSeedWhy = 'Select or right-click a node first';
  const layoutWhy = fallback => blocked ? busyWhy : !canSaveLayout ? 'This connection cannot save node positions' : fallback;
  // The design's canvas menu, row for row (design studio-lm.jsx:1520-1573). Each row runs the application's own
  // action; a row this build has no action for is drawn disabled and says why.
  const canvasMenuItems = [
    {i:'＋', t:'Add node…', k:'⌘L', keys:'l', action:() => setLibraryOpen(true), disabled:blocked, why:busyWhy},
    {i:'⎘', t:'Paste', k:'⌘V', disabled:true, why:'Pasting nodes is not available in this build'},
    {sep:true},
    {i:'⌴', t:'Fit graph to view', k:'⌘0', keys:'0', action:() => fitIds(allIds), disabled:!allIds.length, why:noNodesWhy},
    {i:'⊜', t:'Zoom to 100%', k:'⌘1', keys:'1', action:() => setZoom(1)},
    {sep:true},
    {i:'·', t:'Snap to grid', toggle:true, on:snap, action:() => setSnap(value => !value)},
    {i:'⧉', t:'Auto-layout', k:'⌘⇧L', keys:'shift+l', action:() => arrangeIds(selected.size ? [...selected] : allIds),
      disabled:layoutNeedsRefresh || !canSaveLayout || !allIds.length, why:layoutWhy(noNodesWhy)},
    {sep:true},
    {i:'↻', t:'Reset positions', k:'⌘⇧R', keys:'shift+r', action:undoPositions, disabled:blocked || !undoAvailable,
      why:blocked ? busyWhy : 'No layout change to reset'},
    {i:'✕', t:'Clear all nodes', danger:true, disabled:true,
      why:'Clearing the whole canvas is not available here; delete a node from its inspector'},
  ];
  // A node's own menu (right-click or Shift+F10 on a card) holds the selection, fit and refresh actions that have no
  // row in the design's canvas menu. A connection is deleted from its inspector; the inspector's Rerun runs the graph.
  const nodeMenuItems = [
    {i:'⇄', t:'Select direct neighbours', action:() => selectConnected(false), disabled:!menuHasSeed, why:noSeedWhy},
    {i:'⧉', t:'Select connected group', action:() => selectConnected(true), disabled:!menuHasSeed, why:noSeedWhy},
    {i:'▣', t:'Select all nodes', k:'⌘A', action:() => setSelectedIds(allIds), disabled:!allIds.length, why:noNodesWhy},
    {i:'✕', t:'Clear selection', action:() => setSelectedIds([]), disabled:!selected.size, why:noSelectionWhy},
    {sep:true},
    {i:'⌴', t:'Fit selection', action:() => fitIds([...selected]), disabled:!selected.size, why:noSelectionWhy},
    {i:'⧉', t:'Auto-layout selection', action:() => arrangeIds([...selected]),
      disabled:layoutNeedsRefresh || !canSaveLayout || !selected.size, why:layoutWhy(noSelectionWhy)},
    {sep:true},
    {i:'↻', t:'Refresh canvas', action:refreshCanvas, disabled:layoutBusy || !!authorityState?.pending || (!authority && !normal),
      why:!authority && !normal ? 'Refresh is not available in this connection' : 'Wait for the canvas to finish saving'},
  ];

  return (
    <div
      ref={wrapRef}
      tabIndex={0} role="region" aria-label="Workflow canvas" aria-haspopup="menu" aria-keyshortcuts="Shift+F10"
      onMouseDown={onCanvasMouseDown}
      onContextMenu={onContextMenu}
      onKeyDown={onCanvasKeyDown}
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
        outline: dropTarget ? `1px dashed ${LM.accent}66` : undefined,
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
                  onClick={(e) => { e.stopPropagation(); setFocusId(authorityState ? graph.wires[w.i].id : 'wire:' + w.i); }}
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
              focused={selected.has(n.id) || n.id === focusId}
              dimmed={!selected.has(n.id) && !connectedIds.has(n.id) && focusId !== n.id && !n._user}
              expanded={!!expanded[n.id]}
              onToggleExpand={() => toggleExpanded(n.id)}
              onDragStart={onNodeDragStart(n.id)}
              onFocus={onNodeFocus(n.id)}
              onContextMenu={onNodeContextMenu(n.id)}
              onKeyDown={onNodeKeyDown(n.id)}
              onSocket={(port, side) => useSocket(n.id, port, side)}
              onOpen={n.openable && authority ? () => authority.open(n.id).catch(() => {}) : undefined}
            />
          );
        })}
      </div>

      {unresolvedWires.length > 0 && <details data-no-pan style={{position:'absolute', left:14, top:88,
        zIndex:5, maxWidth:'min(420px, 70%)', maxHeight:180, overflow:'auto', padding:'7px 10px',
        background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:LM.rad.sm, fontSize:11, color:LM.warn}}>
        <summary role="status">{unresolvedWires.length} connections cannot be drawn with their supplied endpoints</summary>
        <p>The connections remain in the graph. Their display needs endpoint projection support.</p>
        <ul style={{paddingLeft:16, overflowWrap:'anywhere'}}>{unresolvedWires.slice(0, 20).map(wire =>
          <li key={wire.i}>{wire.id ? <button onClick={() => setFocusId(authorityState ? wire.id : 'wire:' + wire.i)}
            style={{...smallBtn(), overflowWrap:'anywhere', textAlign:'left', maxWidth:'100%'}}>{wire.id}</button> :
            'Unnamed connection'}: {wire.reason}</li>)}</ul>
        {unresolvedWires.length > 20 && <p>{unresolvedWires.length - 20} more connections are affected.</p>}
      </details>}
      {/* Below the minimap (MiniMap: right 14, top 14, 96 tall), never over it. The design canvas draws no status chip:
          only a save in flight, a refusal or a half-made wire draws one. Refresh is also in a node's own menu. */}
      {(layoutError || authorityState?.error || wireError || layoutBusy || burstPending || authorityState?.pending || wireStart || unwrittenLayout) &&
      <div data-no-pan style={{position:'absolute', top:118, right:14, zIndex:5,
        display:'flex', gap:8, alignItems:'center', maxWidth:'55%', background:LM.bgPanel, padding:'6px 10px', borderRadius:6}}>
        <span role={authorityState?.error || wireError || layoutError ? 'alert' : 'status'} style={{fontSize:12,
          color:authorityState?.error || wireError || layoutError ? LM.err : LM.inkSoft, overflowWrap:'anywhere'}}>
          {layoutError || authorityState?.error || wireError || (layoutBusy || burstPending ? 'Saving positions…' :
            authorityState?.pending ? 'Saving…' : unwrittenLayout ?
              'Positions moved in the last session were never confirmed (' +
              Object.keys(unwrittenLayout.next).length + '). Move them again to save them.' :
            'Choose an input for ' + wireStart.port.label)}
        </span>
        {wireStart && <button disabled={blocked} onClick={() => setWireStart(null)} title="Cancel wire" aria-label="Cancel wire" style={toolBtn()}>✕</button>}
        <button disabled={layoutBusy || !!authorityState?.pending || (!authority && !normal)} onClick={refreshCanvas}
          title="Refresh canvas" aria-label="Refresh canvas" style={toolBtn()}>↻</button>
      </div>}
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
          return Math.max(0.01, Math.min(2, next));
        });
      }} onFit={() => fitIds(selected.size ? [...selected] : allIds)}
        fitLabel={selected.size ? 'Fit selection' : 'Fit all nodes'} setLibraryOpen={setLibraryOpen}/>
      <FloatingComposer key={focusId || 'canvas'} setLibraryOpen={setLibraryOpen} model={model}
        node={allNodes.find(n => n.id === focusId && n.live && nodeModelRow(n))}/>
      <MiniMap pan={pan} zoom={zoom} positions={positions} allNodes={allNodes}/>
      {ctxMenu && <CanvasMenu x={ctxMenu.x} y={ctxMenu.y} maxHeight={ctxMenu.maxHeight}
        opener={ctxMenu.opener} items={ctxMenu.nodeId ? nodeMenuItems : canvasMenuItems}
        label={ctxMenu.nodeId ? 'Node actions' : 'Canvas actions'} onClose={closeContextMenu}/>}
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

// Right-click canvas context menu (design studio-lm.jsx:1519-1573)
const CanvasMenu = ({ x, y, maxHeight, opener, items, label, onClose }) => {
  const menuRef = React.useRef(null);
  const closeRef = React.useRef(onClose);
  const openerRef = React.useRef(opener);
  closeRef.current = onClose;
  openerRef.current = opener;
  const enabledItems = () => Array.from(menuRef.current?.querySelectorAll('button[role^="menuitem"]:not(:disabled)') || []);
  const dismiss = () => {
    closeRef.current();
    if (openerRef.current?.isConnected) openerRef.current.focus({preventScroll:true});
  };
  React.useLayoutEffect(() => {
    (enabledItems()[0] || menuRef.current)?.focus({preventScroll:true});
  }, [opener]);
  React.useEffect(() => {
    const outside = e => { if (!menuRef.current?.contains(e.target)) dismiss(); };
    const escape = e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); dismiss(); } };
    document.addEventListener('click', outside);
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('click', outside); document.removeEventListener('keydown', escape); };
  }, []);
  const navigate = e => {
    if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(e.key)) return;
    e.preventDefault(); e.stopPropagation();
    const rows = enabledItems();
    if (!rows.length) return;
    const current = rows.indexOf(document.activeElement);
    const next = e.key === 'Home' ? 0 : e.key === 'End' ? rows.length - 1 :
      e.key === 'ArrowDown' ? (current + 1) % rows.length : (current < 0 ? rows.length - 1 : (current + rows.length - 1) % rows.length);
    rows[next].focus({preventScroll:true});
    rows[next].scrollIntoView({block:'nearest', inline:'nearest'});
  };
  return (
    <div ref={menuRef} data-no-pan role="menu" tabIndex={-1} aria-label={label} onKeyDown={navigate}
      onClick={e => e.stopPropagation()} style={{
      position:'absolute', left:x, top:y, zIndex:30,
      background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:7,
      boxShadow:'0 16px 36px rgba(0,0,0,.55)', padding:5, minWidth:220,
      maxHeight, overflowY:'auto', outline:'none',
      animation:'lmSlideIn .12s ease-out',
    }}>
      {items.map((it, i) => it.sep ? (
        <div key={i} style={{ height:1, background:LM.lineSoft, margin:'4px 4px' }}/>
      ) : (
        <button key={i} role={it.toggle ? 'menuitemcheckbox' : 'menuitem'} aria-checked={it.toggle ? !!it.on : undefined}
          disabled={!!it.disabled} aria-label={it.t.replace(/…$/, '')}
          title={it.disabled ? it.why || it.t + ' is not available right now' : it.t}
          onClick={() => { if (!it.disabled && typeof it.action === 'function') { dismiss(); it.action(); } }} style={{
          width:'100%', display:'flex', alignItems:'center', gap:10, padding:'6px 10px',
          background:'transparent', border:0, borderRadius:4, cursor:it.disabled ? 'default' : 'pointer',
          // A row with no action in this build is dashed and says why in its title, never alpha (design DECISIONS.md).
          outline:it.disabled ? `1px dashed ${LM.line}` : 'none', outlineOffset:-1,
          color:it.disabled ? LM.inkSoft : it.danger ? LM.err : LM.ink, fontFamily:LM.sans, fontSize:12.5, textAlign:'left',
        }}
        onMouseEnter={e => { if (!it.disabled) e.currentTarget.style.background = LM.bgHover; }}
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
const NodeRenderer = ({ n, focused, dimmed, expanded, onToggleExpand, onDragStart, onFocus, onSocket, onOpen, onContextMenu, onKeyDown }) => {
  const cat = studioCategory(n.cat);
  // AI nodes can expand horizontally for full conversation + search
  const w = (n.cat === 'ai' && expanded) ? Math.max(520, n.w) : n.w;
  const isAi = n.cat === 'ai';
  return (
    <div className="lm-node" data-node-id={n.id} onClick={onFocus} onDoubleClick={onOpen} onContextMenu={onContextMenu}
      tabIndex={0} role="group" aria-label={(n.title || n.id) + ' node'} aria-haspopup="menu" aria-keyshortcuts="Shift+F10" onKeyDown={onKeyDown}
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
        cursor: 'default', outline:'none',
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
        <div title={n.title} style={{ fontSize:13, fontWeight:500, color:LM.ink, marginBottom:2, lineHeight:1.2 }}>{n.title}</div>
        {n.sub && <div title={n.description || n.sub} style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, letterSpacing:'0.04em' }}>{n.sub}</div>}
        <NodeBody n={n} expanded={expanded} onToggleExpand={onToggleExpand}/>
      </div>

      {/* Sockets */}
      {n.ins?.map((s, i) => <Socket key={'in-'+s.id} side="in" i={i} t={s.t} label={s.label} onUse={s.connectable && onSocket ? () => onSocket(s, 'in') : undefined}/>)}
      {n.outs?.map((s, i) => <Socket key={'out-'+s.id} side="out" i={i} t={s.t} label={s.label} onUse={s.connectable && onSocket ? () => onSocket(s, 'out') : undefined}/>)}
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

const Socket = ({ side, i, t, label, onUse }) => {
  const col = WIRE[t] || LM.inkSoft;
  // The dot is a button, so a connectable port starts or finishes a wire; a port that cannot be connected stays inert.
  return (
    <div style={{
      position:'absolute', top: socketY(i) - SOCKET_R,
      [side === 'in' ? 'left' : 'right']: -SOCKET_R,
      display:'flex', alignItems:'center', gap:6,
      flexDirection: side === 'in' ? 'row' : 'row-reverse',
      pointerEvents: onUse ? 'auto' : 'none',
    }}>
      <button type="button" aria-label={(side === 'out' ? 'Connect output ' : 'Connect input ') + label}
        disabled={!onUse} onMouseDown={e => e.stopPropagation()}
        onClick={e => { e.stopPropagation(); if (onUse) onUse(); }} style={{
        display:'block', padding:0, margin:0, flexShrink:0, cursor: onUse ? 'crosshair' : 'default',
        width: SOCKET_R*2, height: SOCKET_R*2, borderRadius:'50%',
        background: side === 'out' ? col : LM.bgPanel,
        border:`1.5px solid ${col}`, boxShadow:`0 0 0 2px ${LM.bgCanvas}`,
      }}/>
      <span style={{
        fontFamily:LM.mono, fontSize:8.5, color:LM.inkMuted, letterSpacing:'0.04em',
        whiteSpace:'nowrap', padding:'0 4px', pointerEvents:'none',
        opacity: label ? 0.85 : 0,
      }}>{label}</span>
    </div>
  );
};

// ─── per-category body content ───
// The inline reply is a real ask: it reaches the same agent the main
// composer does, and reports its answer where it was typed.
// The model the header picked is the model that answers, wherever the ask
// box is. Two of the three ask boxes passed no model at all, so they fell
// through to whatever the server defaulted to: the founder picked a local
// model and a cloud one answered. When no model is handed in, the picker's
// current choice on the window is used rather than a silent default.
const ModelInWindow = ({ model }) => {
  React.useEffect(() => {
    if (typeof window !== 'undefined') window.ARCHHUB_PICKED_MODEL = model;
  }, [model]);
  return null;
};

// Three scales, as he drew them: the canvas composer is the largest ask on
// the screen, the chat reply sits just under it, and the one inside a node
// is node chrome. Collapsing all three onto the smallest made the composer
// read as chrome (2026-09-07).
const ASK_SCALE = {
  composer: { field: 14, send: { padding: '4px 11px', radius: LM.rad.sm, size: 11.5 }, lead: 6 },
  reply:    { field: 13.5, send: { padding: '4px 11px', radius: LM.rad.sm, size: 11.5 }, lead: 0 },
  node:     { field: 12, send: { padding: '3px 8px', radius: 4, size: 10 }, lead: 0 },
};

const InlineAsk = ({ placeholder, model, node, onAnswer, scale, before }) => {
  const S = ASK_SCALE[scale] || ASK_SCALE.node;
  const picked = node ? null : model || (typeof window !== 'undefined' ? window.ARCHHUB_PICKED_MODEL : null);
  const route = node ? nodeModelRoute(node) : modelRoute(picked);
  const [asking, setAsking] = React.useState(false);
  const needsNode = !!window.ARCHHUB_STUDIO_AUTHORITY && !node;
  const [text, setText] = React.useState('');
  const [state, setState] = React.useState('');
  // The composer renders the answer itself; the older inline replies have
  // nowhere to put it, so they keep showing it in the field.
  const report = (line) => { if (onAnswer) onAnswer(line); else setState(String(line).slice(0, 60)); };
  const ask = async () => {
    const said = text.trim();
    if (!said || asking || !window.ARCHHUB_AGENT) return;
    if (needsNode) { report('Select an AI node on the canvas to ask.'); return; }
    if (node && !route) { report('Choose a model for this node first.'); return; }
    setAsking(true);
    report('asking ' + (node ? route : ((picked && picked.name) || 'the agent')) + '…');
    try {
      // Node asks carry the committed route as a consistency check.
      const answer = String(await window.ARCHHUB_AGENT(said, route, node ? node.id : undefined));
      report(answer);
      setText('');
    } catch (error) {
      report('refused: ' + ((error && error.message) || error));
    } finally {
      setAsking(false);
    }
  };
  return (
    <>
      <input value={text} disabled={needsNode} onChange={e => setText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') ask(); }}
        placeholder={needsNode ? 'Select an AI node to ask…' : state || placeholder || 'Reply…'}
        style={{ flex:1, background:'transparent', border:0, outline:0,
          fontStyle:'italic', fontFamily:LM.serif, fontSize:S.field,
          marginLeft: S.lead || 0,
          color: state ? LM.accent : LM.ink }}/>
      {before || null}
      <button onClick={ask} disabled={needsNode || asking || !text.trim()} style={{ padding:S.send.padding, background:LM.accent, color: (window.AH && window.AH.onFill) || '#180f08', border:0, borderRadius:S.send.radius, fontSize:S.send.size, fontWeight:500, cursor:'pointer' }}>{asking ? 'Waiting…' : 'Send ↵'}</button>
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
  const msgs = n.messages || [];   // Workshop / future ai nodes may carry no transcript
  const total = msgs.length;

  if (expanded) {
    const filtered = q ? msgs.filter(m => m.text.toLowerCase().includes(q.toLowerCase())) : msgs;
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
                background: m.me ? LM.userAv : LM.accent,
                color: m.me ? LM.onUserAv : ((window.AH && window.AH.onFill) || '#180f08'),
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
          <InlineAsk scale="node"/>
        </div>
      </div>
    );
  }

  // Compact view
  const recent = msgs.slice(-2);
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
              background: m.me ? LM.userAv : LM.accent,
              color: m.me ? LM.onUserAv : ((window.AH && window.AH.onFill) || '#180f08'),
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
const CanvasToolbar = ({ zoom, setZoom, onFit, fitLabel, setLibraryOpen }) => (
  <div data-no-pan style={{
    position:'absolute', left:14, top:14, display:'flex', gap:LM.sp.xs,
    background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:7, padding:LM.sp.xs,
    boxShadow:'0 4px 12px rgba(0,0,0,.3)',
  }}>
    <button onClick={(e) => { e.stopPropagation(); setZoom(z => Math.min(2, +(z + 0.1).toFixed(2))); }} title="Zoom in" aria-label="Zoom in" style={toolBtn()}>+</button>
    <button onClick={(e) => { e.stopPropagation(); setZoom(z => Math.max(0.01, +(z - 0.1).toFixed(2))); }} title="Zoom out" aria-label="Zoom out" style={toolBtn()}>−</button>
    <div style={{ ...toolBtn(), width:48, color:LM.ink, background:LM.bg, fontFamily:LM.mono, fontSize:10, cursor:'default' }}>
      {Math.round(zoom * 100)}%
    </div>
    <button onClick={(e) => { e.stopPropagation(); onFit(); }} title={fitLabel} aria-label={fitLabel} style={toolBtn()}>{'\u27f2'}</button>
    <div style={{ width:1, background:LM.line, margin:'0 2px' }}/>
    <button onClick={(e) => { e.stopPropagation(); setLibraryOpen(true); }} title="Add node" aria-label="Add node" style={{
      padding:'0 10px', height:22, border:0, background:'transparent', cursor:'pointer',
      color:LM.accent, fontFamily:LM.mono, fontSize:10, letterSpacing:'0.06em',
      display:'flex', alignItems:'center', gap:LM.sp.xs,
    }}>{'\uff0b add node'}</button>
  </div>
);

const toolBtn = () => ({
  width:24, height:22, padding:0, border:0, background:'transparent',
  color:LM.inkSoft, borderRadius:4, cursor:'pointer', fontSize:13,
});

// ─── floating composer (BOTTOM CENTER — always-bottom anchor) ───
// This box used to ignore the model picker and drop the answer on the floor:
// you typed, something happened somewhere, and nothing came back. It now asks
// the model selected in the header and prints the reply above the field.
const FloatingComposer = ({ setLibraryOpen, model, node }) => {
  const [answer, setAnswer] = React.useState('');
  // The drawn caret stands in for an idle field; once the field has focus its own caret is the only one.
  const [typing, setTyping] = React.useState(false);
  return (
    <div data-no-pan onFocus={() => setTyping(true)} onBlur={() => setTyping(false)} style={{
      position:'absolute', left:'50%', bottom:14, transform:'translateX(-50%)',
      width:620, maxWidth:'82%',
      background:LM.bgPanel, border:`1px solid ${LM.accent}66`,
      borderRadius:9, boxShadow:`0 14px 30px rgba(0,0,0,.5), 0 0 0 3px ${LM.accentDim}`,
      padding:'10px 13px',
    }}>
      {answer && (
        <div style={{
          marginBottom:9, padding:'9px 11px', background:LM.bg,
          border:`1px solid ${LM.line}`, borderRadius:7,
          fontFamily:LM.sans, fontSize:12.5, lineHeight:1.55, color:LM.inkSoft,
          maxHeight:190, overflow:'auto', whiteSpace:'pre-wrap',
        }}>{answer}</div>
      )}
      <div style={{ display:'flex', alignItems:'center', gap:LM.sp.sm, fontSize:13.5, fontFamily:LM.sans, color:LM.ink, minHeight:24 }}>
        <span style={{ color:LM.accent, fontFamily:LM.mono, fontSize:13 }}>/</span>
        <span style={{ animation:'lmCaret 1s infinite', display:'inline-block', width:1.5, height:16, background:LM.accent, marginLeft:-4, visibility:typing ? 'hidden' : 'visible' }}/>
        {/* His order: the slash glyph, the field, library, then Send as the
            rightmost control - the placeholder names the affordance drawn
            beside it again (2026-09-07). */}
        <InlineAsk scale="composer" placeholder={node ? 'Ask ' + node.title + '…' : 'Reply, or type / to add a node…'} model={model} node={node} onAnswer={setAnswer}
          before={<button onClick={(e) => { e.stopPropagation(); setLibraryOpen(true); }} style={{ ...smallBtn(), padding:'3px 9px' }}>library</button>}/>
      </div>
    </div>
  );
};

// ─── mini-map (TOP-RIGHT) ───
// The map frames the real nodes: their bounds plus a margin. The old fixed 2400 x 1400 box drew
// larger graphs, and nodes left of or above the origin, off the map. No nodes: nothing to frame.
const minimapViewBox = boxes => {
  if (!boxes.length) return '0 0 2400 1400';
  let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
  for (const box of boxes) {
    left = Math.min(left, box.x); top = Math.min(top, box.y);
    right = Math.max(right, box.x + box.w); bottom = Math.max(bottom, box.y + box.h);
  }
  const margin = Math.max(right - left, bottom - top) * 0.04 + 24;
  return [left - margin, top - margin, right - left + 2 * margin, bottom - top + 2 * margin].join(' ');
};
const MiniMap = ({ pan, zoom, positions, allNodes }) => {
  const nodes = allNodes || LM_GRAPH.nodes;
  const boxes = nodes.map(n => ({ n, p: positions[n.id] || { x: n.x, y: n.y } }))
    .filter(({ n, p }) => [p.x, p.y, n.w, n.h].every(Number.isFinite));
  return (
    <div data-no-pan style={{
      position:'absolute', right:14, top:14, width:170, height:96,
      background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:LM.rad.md,
      overflow:'hidden', boxShadow:'0 4px 12px rgba(0,0,0,.3)',
    }}>
      <svg viewBox={minimapViewBox(boxes.map(({ n, p }) => ({ x: p.x, y: p.y, w: n.w, h: n.h })))} style={{ width:'100%', height:'100%' }}>
        {boxes.map(({ n, p }) => {
          const cat = studioCategory(n.cat);
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
  const library = useStudioProjection()?.library || LM_LIBRARY;
  const [filter, setFilter] = React.useState('all');
  const [q, setQ] = React.useState('');
  const groups = filter === 'all' ? library : library.filter(g => g.cat === filter);
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
            {library.reduce((n, g) => n + g.items.length, 0)} NODES · CLICK TO ADD
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
            const c = studioCategory(g.cat);
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
const NodeModelConversation = ({node}) => {
  const [answer, setAnswer] = React.useState('');
  const cat = studioCategory('ai');
  const route = nodeModelRoute(node);
  return <section aria-label={'Conversation with ' + node.title} style={{ display:'flex', flexDirection:'column', gap:10, borderTop:`1px solid ${LM.lineSoft}`, paddingTop:12 }}>
    <div style={{ display:'flex', alignItems:'center', gap:7 }}>
      <span style={{ color:cat.col, fontFamily:LM.mono }}>{cat.icon}</span>
      <span style={{ fontFamily:LM.mono, fontSize:9, color:cat.col, letterSpacing:'0.18em' }}>CONVERSATION</span>
      <div style={{ flex:1 }}/>
      <p title={route || undefined} style={{ margin:0, maxWidth:170, fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.06em', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
        {route || 'Choose a model for this node'}</p>
    </div>
    {answer && <p role="status" style={{ margin:0, whiteSpace:'pre-wrap', overflowWrap:'anywhere', fontFamily:LM.serif, fontSize:14, lineHeight:1.55, color:LM.ink, letterSpacing:'-0.003em' }}>{answer}</p>}
    <div style={{ background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:7, padding:'8px 11px' }}>
      <div style={{ display:'flex', alignItems:'center', gap:6, minHeight:22, fontSize:13, color:LM.inkSoft }}>
        <InlineAsk scale="reply" node={node} onAnswer={setAnswer} placeholder={'Ask ' + node.title + '\u2026'}/>
      </div>
    </div>
  </section>;
};

const NodeRail = ({ node, hiddenWork = false, workshopRoom = '', onOpenWorkshop }) => {
  // Work lives in the Workshop. A selection the canvas does not draw points there instead of an empty panel.
  if (!node && hiddenWork) return (
    <aside role="status" style={{ gridColumn:'2', gridRow:'2', background:LM.bgPanel, borderLeft:`1px solid ${LM.line}`,
      padding:'14px 16px 20px', display:'flex', flexDirection:'column', gap:LM.sp.md }}>
      <div style={{ fontFamily:LM.serif, fontSize:19, lineHeight:1.1, color:LM.ink }}>Selected Work is in the Workshop</div>
      <div style={{ fontSize:12, lineHeight:1.5, color:LM.inkSoft }}>
        {workshopRoom ? 'Work is reviewed and edited in the Workshop, not on this canvas.' : 'No Workshop conversation is in this scope.'}</div>
      <div><HoverBtn primary disabled={!workshopRoom} onClick={onOpenWorkshop}>Open the Workshop</HoverBtn></div>
    </aside>
  );
  if (!node) return <aside style={{ gridColumn:'2', gridRow:'2', background:LM.bgPanel, borderLeft:`1px solid ${LM.line}` }}/>;
  // AI node gets a dedicated conversation rail — full scrollback + composer
  if (node.cat === 'ai' && !node.live) return <ConversationRail node={node}/>;
  const cat = studioCategory(node.cat);
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
      {node.live && nodeModelRow(node) && <NodeModelConversation key={node.id + ':conversation'} node={node}/>}
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
            <InlineAsk scale="reply" placeholder="Reply to this conversation…"/>
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
        background: m.me ? LM.userAv : LM.accent,
        color: m.me ? LM.onUserAv : ((window.AH && window.AH.onFill) || '#180f08'),
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
// Design studio-lm.jsx:2403-3142 (the Settings shell and its tabs), taken as drawn. Only the seeded
// data is replaced, through the data seam directly below: each value is read from a source the app
// already projects, and where no source exists the tab draws the design's own empty state.
const SET_LS = 'archhub.studio.settings.v1';
const usePersonalTheme = () => {
  const api = window.ARCHHUB_EXISTING_WORKSHOP;
  const read = () => api?.getSnapshot()?.theme || null;
  const [state, setState] = React.useState(read);
  React.useEffect(() => {
    const update = () => setState(read());
    update();
    return api?.subscribe(update);
  }, [api]);
  return state;
};

// ── Data seam. One reader per fact, shared by the sidebar badge and the panel that states it.
// Provider registry (/api/universal/providers through the authenticated transport): rows of
// {id, name, state: keyed | no key | running | not running, source, sets}. It never carries a key,
// so a key is only ever drawn masked.
const useProviderStatus = () => {
  const transport = window.ARCHHUB_EXISTING_WORKSHOP;
  const [rows, setRows] = React.useState(null);
  const [error, setError] = React.useState('');
  const [loading, setLoading] = React.useState(false);
  const mounted = React.useRef(true), readIntent = React.useRef(0);
  const refresh = React.useCallback(async () => {
    const intent = ++readIntent.current;
    setLoading(true); setError('');
    try {
      if (!transport?.readProviders) throw new Error('Provider settings require the authenticated application connection.');
      const current = await transport.readProviders();
      if (mounted.current && intent === readIntent.current) setRows(current);
    } catch (failure) {
      if (mounted.current && intent === readIntent.current) setError(failure.message || 'Provider status could not be read.');
    } finally { if (mounted.current && intent === readIntent.current) setLoading(false); }
  }, [transport]);
  React.useEffect(() => {
    mounted.current = true;
    refresh();
    return () => { mounted.current = false; readIntent.current += 1; };
  }, [refresh]);
  return {rows, error, loading, refresh, transport};
};
const providerKeyed = rows => (rows || []).filter(r => r.state === 'keyed').length;
const providerRunning = rows => (rows || []).filter(r => r.state === 'running').length;
// The model the composer asks (published once by ModelInWindow); nothing else routes per task.
const pickedModel = () => {
  const m = window.ARCHHUB_PICKED_MODEL;
  return m && (m.routed || m.route) ? m : null;
};
// The release status the update transport reads (current_build, state, updated_to).
const releaseStatus = snapshot => snapshot?.applicationUpdate || null;
// The Studio draws the dark tokens only. Personal Settings holds colours, not a mode, so the
// selected Theme card and the Theme badge both state the mode that is actually applied.
const STUDIO_THEME_MODE = 'Dark';
// A catalogue panel reads its loader once and states loading or failure in the design's own
// empty-state line, instead of an unstyled status paragraph above the panel.
const useLiveCatalogue = (loaderName, items) => {
  useCatalogueVersion();
  React.useEffect(() => { loadCatalogue(loaderName, items); }, []);
  const status = catalogueStates.get(loaderName) || {loading:false, error:''};
  return {loading:!!status.loading, error:status.error || '', retry:() => loadCatalogue(loaderName, items)};
};
const SettingsEmpty = ({ children, role = 'status', action }) => (
  <div role={role} style={{ padding:'12px 14px', fontFamily:LM.serif, fontStyle:'italic', fontSize:13.5, color:LM.inkSoft,
    display:'flex', alignItems:'center', gap:10 }}>
    <span style={{ flex:1, minWidth:0 }}>{children}</span>
    {action}
  </div>
);

// Single source for "what is this item's current state?" — used by BOTH the sidebar badges and
// the panel rows. Defined once precisely so the two cannot derive the same fact differently:
// the badges previously counted only keys PRESENT in the store while the rows fell back to the
// seed per item, so an empty or partial store made a badge contradict the panel beside it.
const hostState = (store, h) => ((store && store.hosts) || {})[h.name] || h.state;
const permMode  = (store, p) => ((store && store.perms) || {})[p.id] || p.mode;
const Settings = ({ onClose, account, setAccount, onSignOut }) => {
  const providers = useProviderStatus();
  const release = releaseStatus(useWorkshopProjection());
  // The Hosts and Brain badges state the catalogues their panels read, so both load when Settings opens.
  useLiveCatalogue('ARCHHUB_LOAD_HOSTS', LM_HOSTS);
  useLiveCatalogue('ARCHHUB_LOAD_MEMORY', LM_MEMORY);
  // Account first either way: signed in it states the account, signed out it is where you sign in.
  const [tab, setTab] = React.useState('account');
  const [store, setStore] = React.useState(() => {
    var seed = {
      perms: LM_PERMISSIONS.reduce(function (a, p) { a[p.id] = p.mode; return a; }, {}),
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
        delete saved.theme; // Saved appearance belongs to the graph, never this legacy UI cache.
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
  const keyed = providerKeyed(providers.rows);
  const tabs = [
    ['account',     'Account',     (account || {}).graphTier || null],
    ['memory',      'Brain',       `${(window.BRAIN_STRATA || []).length} strata \u00b7 ${LM_MEMORY.length - (store.forgotten || []).length} facts`],
    ['team',        'Team',        null],
    ['profile',     'Profile',     'Architect'],
    ['permissions', 'Permissions', (() => { const v = LM_PERMISSIONS.map(p => permMode(store, p)); return `${v.filter(x => x === 'auto').length} auto · ${v.filter(x => x === 'ask').length} ask`; })()],
    ['hosts',       'Hosts',       `${LM_HOSTS.filter(h => hostState(store, h) !== 'off').length} live`],
    ['providers',   'Providers',   providers.rows ? `${keyed} key${keyed === 1 ? '' : 's'}` : null],
    ['models',      'Models',      pickedModel() ? pickedModel().name : null],
    ['theme',       'Theme',       STUDIO_THEME_MODE],
    ['shortcuts',   'Shortcuts',   null],
    ['storage',     'Storage',     null],
    ['about',       'About',       null],
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
          <span style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, letterSpacing:'0.1em' }}>STUDIO{release?.current_build ? ' \u00b7 ' + release.current_build : ''}</span>
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
          {tab === 'team'        && <SettingsTeam/>}
          {tab === 'profile'     && <SettingsProfile/>}
          {tab === 'permissions' && <SettingsPermissions store={store} patch={patch}/>}
          {tab === 'hosts'       && <SettingsHosts store={store} patch={patch}/>}
          {tab === 'providers'   && <SettingsProviders providers={providers} onTab={setTab}/>}
          {tab === 'models'      && <SettingsModels/>}
          {tab === 'theme'       && <SettingsTheme/>}
          {tab === 'shortcuts'   && <SettingsShortcuts/>}
          {tab === 'storage'     && <SettingsStorage/>}
          {tab === 'about'       && <SettingsAbout providers={providers} release={release}/>}
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

// -- Brain: the governance layer, read from brain-model.jsx (the single definition).
// The strata, gates and key text come from brain-model.jsx; the facts are the real ones the brain
// holds (ARCHHUB_LOAD_MEMORY, see studio.html). Nothing in the shipped brain classifies a fact yet,
// so every real fact files under Instances as unclassified, which the model seals by default: a
// sealed fact has no share control (design), and the brain has no share path to bind one to.
const LM_MEMORY = (window.ARCHHUB_LIVE && window.ARCHHUB_LIVE.memory) || [];
const SettingsMemory = ({ store, patch }) => {
  const catalogue = useLiveCatalogue('ARCHHUB_LOAD_MEMORY', LM_MEMORY);
  const strata = window.BRAIN_STRATA || [];
  const CEIL   = window.BRAIN_CEIL || {};
  const gates  = window.BRAIN_GATES || [];
  const keys   = window.BRAIN_KEYS || {};
  const facts  = LM_MEMORY.map(m => ({ id:m.id, text:m.text, src:m.src, stratum:'instances', cls:null, sealed:true, unclassified:true, held:m }));
  const forgotten = store.forgotten || [];
  const log = store.consents || [];
  const live = facts.filter(f => forgotten.indexOf(f.id) < 0);
  // The design opens the stratum that holds facts; the real facts all file under Instances.
  const [chosen, setOpen] = React.useState('auto');
  const open = chosen === 'auto' ? (live.length ? 'instances' : 'category') : chosen;
  const [showGates, setShowGates] = React.useState(false);
  const [showLog, setShowLog] = React.useState(false);
  const [kit, setKit] = React.useState(null);
  const [rotate, setRotate] = React.useState(false);
  const [said, setSaid] = React.useState({});

  // THE CONSENT RECORD. Every crossing is written down: what, which gate, which way, when.
  const record = (act, f, gate) => ({
    t: new Date().toTimeString().slice(0, 5), act, gate,
    fact: f.text.length > 62 ? f.text.slice(0, 60) + '\u2026' : f.text,
    cls: f.cls || 'unclassified',
  });

  // The brain forgets first; the panel follows.
  const forget = async m => {
    try { await window.ARCHHUB_BRAIN_FORGET(m.id); } catch (e) { return; }
    patch({ forgotten: forgotten.concat(m.id), consents: [record('forgot', m, '\u2014')].concat(log).slice(0, 40) });
  };
  // Rewriting a fact is done on the fact's own text: click it. In place (the old text is replaced,
  // not duplicated), and the outcome is stated where the fact's source line sits.
  const note = (id, text) => {
    setSaid(s => Object.assign({}, s, { [id]: text }));
    if (text !== 'saving\u2026') setTimeout(() => setSaid(s => Object.assign({}, s, { [id]: '' })), 4000);
  };
  const edit = async m => {
    const next = window.prompt('Rewrite this memory', m.text);
    if (!next || next.trim() === m.text) return;
    note(m.id, 'saving\u2026');
    try {
      await window.ARCHHUB_BRAIN_EDIT(m.id, next.trim());
      m.held.text = next.trim();
      note(m.id, 'saved');
    } catch (error) { note(m.id, 'refused'); }
  };

  return (
  <div>
    <SHead title="Brain" sub="Not a list of facts &#x2014; the layer that decides what kinds of things exist, how they relate and how they are filed. The top three strata are structure and can be shared; instances stay put."/>

    {/* strata -- the spine */}
    <div style={{ display:'flex', flexDirection:'column', gap:6, marginBottom:LM.sp.md }}>
      {strata.map(s => {
        const mine = live.filter(f => f.stratum === s.id);
        const on = open === s.id;
        const reading = s.id === 'instances' && (catalogue.loading || catalogue.error);
        return (
          <div key={s.id} style={{ background:LM.bg, border:`1px solid ${on ? s.col + '66' : LM.line}`, borderRadius:LM.rad.lg, overflow:'hidden' }}>
            <div onClick={() => setOpen(on ? null : s.id)} style={{ display:'flex', alignItems:'center', gap:LM.sp.md, padding:'11px 14px', cursor:'pointer' }}>
              <span style={{ width:7, height:7, borderRadius:2, background:s.col, flexShrink:0 }}/>
              <div style={{ minWidth:0, flex:1 }}>
                <div style={{ fontSize:13.5, color:LM.ink }}>{s.n}
                  <span style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.05em', marginLeft:8 }}>{s.one}</span>
                </div>
                {on && <div style={{ fontSize:12, color:LM.inkSoft, lineHeight:1.5, marginTop:5 }}>{s.holds}</div>}
              </div>
              <span style={{ fontFamily:LM.mono, fontSize:9, letterSpacing:'0.1em', padding:'2px 7px', borderRadius:3,
                background: s.id === 'instances' ? LM.err + '1f' : s.col + '1c', color: s.id === 'instances' ? LM.err : s.col }}>
                {s.travels === 'freely' ? 'TRAVELS' : s.travels === 'on opt-in' ? 'OPT-IN' : 'STAYS'}
              </span>
              <span style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, minWidth:18, textAlign:'right' }}>{mine.length}</span>
              <span style={{ color:LM.inkMuted, fontSize:10 }}>{on ? '\u25be' : '\u25b8'}</span>
            </div>
            {on && (
              <div>
                {mine.map(f => {
                  const c = CEIL[f.cls] || { col:LM.err, label:'UNCLASSIFIED \u00b7 SEALED' };
                  return (
                    <div key={f.id} style={{ padding:'10px 14px', display:'flex', alignItems:'center', gap:LM.sp.md, borderTop:`1px solid ${LM.lineSoft}` }}>
                      <div style={{ flex:1, minWidth:0 }}>
                        <div onClick={() => edit(f)} title="Rewrite this memory"
                          style={{ fontSize:13, color: f.sealed ? LM.inkSoft : LM.ink, lineHeight:1.4, cursor:'text' }}>{f.text}</div>
                        <div style={{ display:'flex', alignItems:'center', gap:8, marginTop:4, flexWrap:'wrap' }}>
                          <span style={{ fontFamily:LM.mono, fontSize:9, letterSpacing:'0.1em', padding:'1px 6px', borderRadius:3, background:c.col + '1c', color:c.col }}>{c.label}</span>
                          <span role={said[f.id] ? 'status' : undefined} style={{ fontFamily:LM.mono, fontSize:9.5, color: said[f.id] === 'refused' ? LM.err : LM.inkMuted, letterSpacing:'0.04em' }}>{said[f.id] || f.src}</span>
                        </div>
                      </div>
                      <span title="The ontology could not place this, so it defaults to sealed &#x2014; there is no release path at all."
                        style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.err, letterSpacing:'0.08em' }}>&#x2298; sealed</span>
                      <button title={'Forget: ' + f.text}
                        onClick={() => forget(f)}
                        style={{ ...smallBtn(), padding:'3px 8px', color:LM.err, borderColor:LM.lineSoft }}>forget</button>
                    </div>
                  );
                })}
                {mine.length === 0 && (
                  <div style={{ padding:'12px 14px', borderTop:`1px solid ${LM.lineSoft}`, fontFamily:LM.serif, fontStyle:'italic', fontSize:13.5, color:LM.inkSoft,
                    display:'flex', alignItems:'center', gap:10 }}>
                    <span role={reading ? (catalogue.error ? 'alert' : 'status') : undefined} style={{ flex:1 }}>
                      {!reading ? 'Nothing at this stratum yet.'
                        : catalogue.loading ? 'Reading the brain\u2026' : 'The brain was not read: ' + catalogue.error}
                    </span>
                    {reading && catalogue.error && !catalogue.loading &&
                      <button onClick={catalogue.retry} style={{ ...smallBtn(), padding:'3px 9px', fontStyle:'normal' }}>read again</button>}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>

    {forgotten.length > 0 && (
      <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:LM.sp.md }}>
        <span style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkSoft, letterSpacing:'0.06em' }}>{forgotten.length} forgotten this session</span>
        <button onClick={() => patch('forgotten', [])} style={{ ...smallBtn(), padding:'3px 9px' }}>restore all</button>
      </div>
    )}

    {/* gates */}
    <div style={{ background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg, overflow:'hidden', marginBottom:LM.sp.md }}>
      <div onClick={() => setShowGates(!showGates)} style={{ display:'flex', alignItems:'center', gap:10, padding:'10px 14px', cursor:'pointer' }}>
        <span style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.12em' }}>GATES</span>
        <span style={{ flex:1, fontSize:12, color:LM.inkSoft }}>Four crossings, each with a decider and a way back. Nothing flows by default.</span>
        <span style={{ color:LM.inkMuted, fontSize:10 }}>{showGates ? '\u25be' : '\u25b8'}</span>
      </div>
      {showGates && gates.map(g => (
        <div key={g.id} style={{ padding:'10px 14px', borderTop:`1px solid ${LM.lineSoft}`, display:'flex', gap:LM.sp.md, alignItems:'flex-start' }}>
          <span style={{ fontFamily:LM.mono, fontSize:9, letterSpacing:'0.1em', color:LM.accent, minWidth:126 }}>{g.label}</span>
          <div style={{ flex:1, minWidth:0, fontSize:12, lineHeight:1.55, color:LM.inkSoft }}>
            <div>Decided by <b style={{ color:LM.ink, fontWeight:500 }}>{g.decider}</b> &#xb7; default {g.def} &#xb7; {g.revocable}</div>
            <div style={{ marginTop:3 }}>Passes: {g.passes}</div>
            {g.never !== '\u2014' && <div style={{ color:LM.err, marginTop:3 }}>Never: {g.never}</div>}
          </div>
        </div>
      ))}
    </div>

    {/* consent record -- the audit the gates are only real because of */}
    <div style={{ background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg, overflow:'hidden', marginBottom:LM.sp.sm }}>
      <div onClick={() => setShowLog(!showLog)} style={{ display:'flex', alignItems:'center', gap:10, padding:'10px 14px', cursor:'pointer' }}>
        <span style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.12em' }}>CONSENT RECORD</span>
        <span style={{ flex:1, fontSize:12, color:LM.inkSoft }}>
          {log.length ? `${log.length} crossing${log.length === 1 ? '' : 's'} this session \u00b7 append-only` : 'Nothing has crossed a gate yet.'}
        </span>
        <span style={{ color:LM.inkMuted, fontSize:10 }}>{showLog ? '\u25be' : '\u25b8'}</span>
      </div>
      {showLog && (log.length
        ? log.map((e, i) => (
            <div key={i} style={{ padding:'8px 14px', borderTop:`1px solid ${LM.lineSoft}`, display:'flex', gap:10, alignItems:'baseline', fontSize:12 }}>
              <span style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, minWidth:34 }}>{e.t}</span>
              <span style={{ fontFamily:LM.mono, fontSize:9, letterSpacing:'0.08em', minWidth:58,
                color: e.act === 'shared' ? LM.ok : e.act === 'withdrew' ? LM.warn : LM.err }}>{e.act.toUpperCase()}</span>
              <span style={{ flex:1, minWidth:0, color:LM.inkSoft, lineHeight:1.45 }}>{e.fact}</span>
              <span style={{ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.06em' }}>{e.gate}</span>
            </div>
          ))
        : <div style={{ padding:'12px 14px', borderTop:`1px solid ${LM.lineSoft}`, fontFamily:LM.serif, fontStyle:'italic', fontSize:13.5, color:LM.inkSoft }}>
            Share or withdraw a fact above and it appears here. The record cannot be edited, only exported.
          </div>)}
    </div>

    {/* keys + export */}
    <div style={{ padding:'11px 13px', background:LM.bg, border:`1px solid ${LM.lineSoft}`, borderRadius:LM.rad.md, marginBottom:LM.sp.sm }}>
      <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.12em', marginBottom:7 }}>KEY</div>
      <div style={{ fontSize:12, color:LM.inkSoft, lineHeight:1.6 }}>{keys.how}</div>
      <div style={{ fontSize:12, color:LM.inkSoft, lineHeight:1.6, marginTop:7 }}>{keys.cost}</div>

      {kit && (
        <div role="status" style={{ marginTop:11, padding:'11px 12px', background:LM.bgDeep, border:`1px solid ${LM.accentSoft}`, borderRadius:LM.rad.sm, fontFamily:LM.serif, fontStyle:'italic', fontSize:13.5, color:LM.inkSoft }}>
          No recovery kit exists in this connection. The login-wrapped key is proposed, not shipped, so there is nothing to write down yet.
        </div>
      )}

      {rotate && (
        <div role="status" style={{ marginTop:11, padding:'11px 12px', background:LM.bgDeep, border:`1px solid ${LM.line}`, borderRadius:LM.rad.sm, fontFamily:LM.serif, fontStyle:'italic', fontSize:13.5, color:LM.inkSoft }}>
          No wrapped key exists in this connection, so there is nothing to re-wrap.
        </div>
      )}

      <div style={{ display:'flex', gap:7, marginTop:10 }}>
        <button onClick={() => setKit(kit ? null : 'show')} style={{ ...smallBtn(), padding:'3px 9px' }}>
          {kit ? 'hide recovery kit' : 'show recovery kit'}
        </button>
        <button onClick={() => setRotate(!rotate)} style={{ ...smallBtn(), padding:'3px 9px' }}>rotate login</button>
      </div>
    </div>
    <div style={{ padding:'10px 12px', background:LM.bg, border:`1px solid ${LM.lineSoft}`, borderRadius:LM.rad.md }}>
      <div style={{ display:'flex', alignItems:'center', gap:10, flexWrap:'wrap' }}>
        <span style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.12em' }}>EXPORT</span>
        <span style={{ flex:1, fontSize:12, color:LM.inkSoft, minWidth:180 }}>Take the whole brain with you &#x2014; strata, facts, consent record.</span>
        <button onClick={async (e) => {
          const b = e.currentTarget;
          b.textContent = 'reading…';
          try {
            const held = await window.ARCHHUB_BRAIN_EXPORT();
            const blob = new Blob([JSON.stringify({ facts:held, consents:log }, null, 2)],
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
};

// -- Team: identity, seats, invites (design studio-lm.jsx:2731-2792). No data path projects a firm
// roster, seats or invite tokens into this view, so the layout stays and every value is empty.
const SettingsTeam = () => {
  const none = 'No firm in this connection';
  const off = { ...smallBtn(), padding:'4px 11px', borderStyle:'dashed', color:LM.inkMuted, cursor:'default' };
  return (
  <div>
    <SHead title="Team" sub="One person owns the workspace and invites teammates by email. Firm brain access follows membership &#x2014; removing someone stops what they can read next, not what they already hold."/>
    <div style={{ display:'flex', gap:LM.sp.sm, marginBottom:LM.sp.md, flexWrap:'wrap' }}>
      {[['FIRM','\u2014'],['SEATS','\u2014'],['USED','\u2014'],['YOUR ROLE','\u2014']].map(([k,v]) => (
        <div key={k} style={{ flex:'1 1 150px', padding:'9px 12px', background:LM.bg, border:`1px solid ${LM.lineSoft}`, borderRadius:LM.rad.md }}>
          <div style={{ fontFamily:LM.mono, fontSize:9, letterSpacing:'0.14em', color:LM.inkMuted }}>{k}</div>
          <div style={{ fontSize:13, marginTop:4, color:LM.inkMuted }}>{v}</div>
        </div>
      ))}
    </div>
    <div style={{ background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg, overflow:'hidden', marginBottom:LM.sp.sm }}>
      <div role="status" style={{ padding:'12px 14px', fontFamily:LM.serif, fontStyle:'italic', fontSize:13.5, color:LM.inkSoft }}>
        No firm in this connection. Members appear here when the workspace has one.
      </div>
    </div>
    <div style={{ display:'flex', gap:7, flexWrap:'wrap' }}>
      <button disabled title={none} style={off}>invite a teammate</button>
      <button disabled title={none} style={off}>set seat count</button>
      <button disabled title={none} style={off}>transfer ownership</button>
      <button disabled title={none} style={{ ...off, color:LM.err }}>leave firm</button>
    </div>
    <div style={{ marginTop:LM.sp.md, padding:'10px 12px', background:LM.bg, border:`1px solid ${LM.lineSoft}`, borderRadius:LM.rad.md }}>
      <div style={{ fontSize:12, color:LM.inkSoft, lineHeight:1.6 }}>
        <b style={{ color:LM.ink, fontWeight:500 }}>Seats are protected against over-inviting.</b> The check counts current members plus outstanding invites, so pending invites cannot squeeze past a seat limit once accepted.
      </div>
    </div>
  </div>
  );
};// ── Profile: who you are, the AI's system prompt anchor
const SettingsProfile = () => (
  <div>
    <SHead title="Profile" sub="The grounding the model uses. Sets tone, units, and what 'we' means."/>
    <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:14 }}>
      {/* The signed-in account, never an invented person. */}
      <SField label="Display name" value={(() => { const a = (typeof acLoad === 'function' && acLoad()) || {}; return a.name || (a.email ? String(a.email).split('@')[0] : '—'); })()}/>
      <SField label="Studio / firm" value={(window.ARCHHUB_LIVE && window.ARCHHUB_LIVE.firm) || '—'}/>
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
        You are working with the signed-in architect inside ArchHub. Use millimeters, ISO conventions. Be terse and technical, no preamble. Never propose imperial units. Never use emoji. The active Revit document is the source of truth.
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
const PERM_META = window.ArchHubTheme.derive((LM) => ({
  auto:  { col:LM.ok,     label:'AUTO',  note:'Runs without asking' },
  ask:   { col:LM.warn,   label:'ASK',   note:'Pauses for confirmation' },
  block: { col:LM.err,    label:'BLOCK', note:'Never run' },
}));
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

// ── Providers (design studio-lm.jsx:2895-2933). The rows are the provider registry's: a cloud
// provider is keyed or has no key, a local runtime is running or not. The registry never returns a
// key, so the key slot is masked and nothing can reveal it, and there is no spend figure because
// nothing on this machine measures one. The swatch identifies the vendor, as he drew it.
const BRAND = { openrouter: '#3a6acc', cloud: '#cc785c', ollama: '#1a8a4a', lmstudio: '#4285f4' };

const SettingsSocialEnrollment = ({transport}) => {
  const form = React.useRef(null), busy = React.useRef(false), alive = React.useRef(true);
  const [saving, setSaving] = React.useState(false), [message, setMessage] = React.useState('');
  const [failed, setFailed] = React.useState(false);
  React.useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; if (form.current) form.current.elements.token.value = ''; };
  }, []);
  const save = async event => {
    event.preventDefault();
    if (busy.current || !transport?.enrollSocialAccount) return;
    const fields = form.current.elements;
    const request = {provider:fields.provider.value, account_id:fields.account_id.value.trim(),
      vault_entry:fields.vault_entry.value.trim(), token:fields.token.value};
    fields.token.value = '';
    busy.current = true; setSaving(true); setMessage(''); setFailed(false);
    try {
      const result = await transport.enrollSocialAccount(request);
      if (alive.current) setMessage('Saved ' + result.vault_entry + ' for ' + result.account_id +
        '. Use this reference in the connector node. Provider ownership has not been checked.');
    } catch (error) {
      if (alive.current) { setFailed(true); setMessage(error.message); }
    } finally {
      request.token = ''; busy.current = false;
      if (alive.current) setSaving(false);
    }
  };
  const remove = async () => {
    if (busy.current || !transport?.removeLocalSocialAccount || !form.current) return;
    const fields = form.current.elements;
    if (!fields.account_id.reportValidity() || !fields.vault_entry.reportValidity()) return;
    const request = {provider:fields.provider.value, account_id:fields.account_id.value.trim(),
      vault_entry:fields.vault_entry.value.trim()};
    fields.token.value = '';
    busy.current = true; setSaving(true); setMessage(''); setFailed(false);
    try {
      const result = await transport.removeLocalSocialAccount(request);
      if (alive.current) setMessage((result.state === 'absent' ? 'No local credential remains for ' : 'Removed local credential for ') +
        result.vault_entry + '. Saved workflows remain. This does not revoke the token at the provider or stop a request already sent.');
    } catch (error) {
      if (alive.current) { setFailed(true); setMessage(error.message); }
    } finally { busy.current = false; if (alive.current) setSaving(false); }
  };
  const inputStyle = {display:'block', width:'100%', margin:'6px 0 12px', padding:'7px 10px',
    background:LM.bg, color:LM.ink, border:`1px solid ${LM.line}`, borderRadius:LM.rad.sm, fontFamily:LM.mono, fontSize:11.5};
  const labelStyle = {display:'block', fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.1em'};
  return <div style={{padding:'12px 14px', background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg}}>
    <div style={{fontSize:13, fontWeight:500}}>Social accounts</div>
    <div style={{fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, marginTop:2, marginBottom:12, letterSpacing:'0.04em'}}>Save an account credential on this machine and connect its reference to a Work node.</div>
    <form ref={form} onSubmit={save}>
      <fieldset disabled={saving || !transport?.enrollSocialAccount} style={{border:0, padding:0, margin:0, minWidth:0}}>
        <label style={labelStyle}>PROVIDER<select name="provider" style={inputStyle} defaultValue="linkedin">
          <option value="linkedin">LinkedIn</option><option value="meta">Facebook / Instagram</option>
        </select></label>
        <label style={labelStyle}>ACCOUNT ID<input name="account_id" required maxLength={256} style={inputStyle}
          placeholder="LinkedIn person URN, or Meta user / Page ID"/></label>
        <label style={labelStyle}>REFERENCE NAME<input name="vault_entry" required maxLength={128} pattern="social-[A-Za-z0-9._-]+"
          placeholder="social-studio" style={inputStyle}/></label>
        <label style={labelStyle}>ACCESS TOKEN<input name="token" type="password" required maxLength={16384} autoComplete="new-password"
          autoCapitalize="none" spellCheck={false} style={inputStyle}/></label>
        <div style={{fontSize:12, color:LM.inkSoft, lineHeight:1.55, marginBottom:10}}>You declare which account this token belongs to. Saving it does not publish anything or verify the account with the provider.</div>
        <div style={{display:'flex', gap:7, flexWrap:'wrap'}}>
          <button type="submit" style={smallBtn(true)}>{saving ? 'Applying change…' : 'Save account'}</button>
          <button type="button" disabled={!transport?.removeLocalSocialAccount} onClick={remove} style={{...smallBtn(), color:LM.err}}
            title="Uses the provider, account ID and reference above. No access token is needed. Saved workflows stay in the graph.">Remove local credential</button>
        </div>
      </fieldset>
      {!transport?.enrollSocialAccount && <p role="status" style={{fontSize:12, color:LM.inkSoft}}>Account enrollment is unavailable in this connection.</p>}
      {message && <p role={failed ? 'alert' : 'status'} style={{fontSize:12, overflowWrap:'anywhere', color:failed ? LM.err : LM.ok}}>{message}</p>}
    </form>
  </div>;
};

// The design's per-row "manage" / "connect" button opens what that provider actually offers here:
// OpenRouter takes a key into this machine's secrets store, the ArchHub cloud is keyed by signing
// in, and a local runtime is started on this machine. Each one can read the status again.
const ProviderManage = ({ p, providers, onTab }) => {
  const transport = providers.transport;
  const keyInput = React.useRef(null);
  const mounted = React.useRef(true), savingRef = React.useRef(false);
  const [saving, setSaving] = React.useState(false);
  const [hasKey, setHasKey] = React.useState(false);
  const [saved, setSaved] = React.useState('');
  const [err, setErr] = React.useState('');
  React.useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; if (keyInput.current) keyInput.current.value = ''; };
  }, []);
  const saveKey = async event => {
    event.preventDefault();
    if (savingRef.current || !keyInput.current?.value.trim()) return;
    savingRef.current = true; setSaving(true); setErr(''); setSaved('');
    try {
      if (!transport?.saveProviderKey) throw new Error('Provider key saving is unavailable in this connection.');
      await transport.saveProviderKey('openrouter', keyInput.current.value);
      if (!mounted.current) return;
      keyInput.current.value = ''; setHasKey(false);
      setSaved('Saved on this machine. Provider connectivity has not been checked.');
      await providers.refresh();
    } catch (error) {
      if (mounted.current) setErr(error.message || 'The provider key could not be saved.');
    } finally { savingRef.current = false; if (mounted.current) setSaving(false); }
  };
  const box = { padding:'11px 14px 12px', borderTop:`1px solid ${LM.lineSoft}`, background:LM.bgDeep };
  const line = { fontSize:12, color:LM.inkSoft, lineHeight:1.55 };
  const refresh = <button type="button" disabled={saving || providers.loading} onClick={providers.refresh} style={{ ...smallBtn(), padding:'3px 9px' }}>
    {providers.loading ? 'Reading status…' : 'Refresh provider status'}</button>;
  if (p.id === 'openrouter') {
    const blocked = saving || !hasKey || !transport?.saveProviderKey;
    return (
      <form onSubmit={saveKey} style={box}>
        <label style={{ display:'block', fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.1em' }}>OPENROUTER API KEY
          <input ref={keyInput} type="password" aria-label="OpenRouter API key" autoComplete="new-password"
            autoCapitalize="none" spellCheck={false} maxLength={8192} disabled={saving || !transport?.saveProviderKey}
            onChange={event => { setHasKey(!!event.target.value.trim()); setSaved(''); }}
            style={{ display:'block', width:'100%', margin:'6px 0 8px', padding:'7px 10px', background:LM.bg,
              color:LM.ink, border:`1px solid ${LM.line}`, borderRadius:LM.rad.sm, fontFamily:LM.mono, fontSize:11.5 }}/>
        </label>
        <div style={line}>Paste the raw key to save it in this machine’s encrypted secrets store. An existing environment key remains the active source when one is set.</div>
        <div style={{ display:'flex', gap:7, marginTop:9, flexWrap:'wrap' }}>
          <button type="submit" disabled={blocked}
            style={blocked ? { ...smallBtn(), padding:'3px 9px', borderStyle:'dashed', cursor:'default' } : { ...smallBtn(true), padding:'3px 9px' }}>
            {saving ? 'Saving key…' : 'Save OpenRouter key'}</button>
          {refresh}
        </div>
        {saved && <p role="status" style={{ fontSize:12, color:LM.ok, margin:'8px 0 0' }}>{saved}</p>}
        {err && <p role="alert" style={{ fontSize:12, color:LM.err, margin:'8px 0 0' }}>{err}</p>}
      </form>
    );
  }
  return (
    <div style={box}>
      <div style={line}>{p.id === 'cloud'
        ? 'The ArchHub cloud is keyed by the signed-in account' + (p.sets ? ' or by ' + p.sets : '') + '.'
        : p.state === 'running' ? p.name + ' is answering on ' + p.source + '. Its models appear in the model picker.'
        : p.sets ? 'Set ' + p.sets + ' on this machine, then read the status again.'
        : 'Start ' + p.name + ' on this machine (' + p.source + '), then read the status again.'}</div>
      <div style={{ display:'flex', gap:7, marginTop:9, flexWrap:'wrap' }}>
        {p.id === 'cloud' && <button type="button" onClick={() => onTab && onTab('account')} style={{ ...smallBtn(), padding:'3px 9px' }}>Open Account</button>}
        {refresh}
      </div>
    </div>
  );
};

const SettingsProviders = ({ providers, onTab }) => {
  const { rows, error, loading, transport } = providers;
  const [managing, setManaging] = React.useState(null);
  const [social, setSocial] = React.useState(false);
  const tone = (state) => state === 'keyed' ? LM.ok : state === 'running' ? LM.cyan : LM.inkMuted;
  const off = state => state === 'no key' || state === 'not running';
  const keyed = providerKeyed(rows), running = providerRunning(rows);
  return (
  <div>
    <SHead title="Providers" sub={'BYO keys. Local models live in Ollama or LM Studio. ' + (rows
      ? keyed + ' keyed \u00b7 ' + running + ' local runtime' + (running === 1 ? '' : 's') + ' running.'
      : error ? 'Not read.' : 'Reading this machine\u2026')}/>
    <div style={{ background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg, overflow:'hidden' }}>
      {(rows || []).map((p, i) => (
        <div key={p.id} style={{ borderTop: i===0 ? 'none' : `1px solid ${LM.lineSoft}` }}>
          <div style={{ padding:'12px 14px', display:'flex', alignItems:'center', gap:LM.sp.md }}>
            <span style={{ width:24, height:24, borderRadius:LM.rad.sm, background:BRAND[p.id] || tone(p.state), color: (window.AH && window.AH.onFill) || '#180f08', display:'grid', placeItems:'center', fontFamily:LM.mono, fontSize:12, fontWeight:700 }}>{p.name[0]}</span>
            <div style={{ flex:1, minWidth:0, lineHeight:1.2 }}>
              <div style={{ fontSize:13, fontWeight:500, color: off(p.state) ? LM.inkMuted : LM.ink }}>{p.name}</div>
              <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, marginTop:2, letterSpacing:'0.04em' }}>
                <span title={p.state === 'keyed' ? 'Stored keys are never shown' : undefined} style={{ color:LM.inkSoft }}>
                  {p.state === 'keyed' ? '\u2022'.repeat(12) : p.sets ? '\u2014' : p.source}
                </span> · {p.state === 'keyed' ? 'key from the ' + p.source
                  : p.state === 'no key' ? 'no key \u00b7 set ' + p.sets
                  : p.state === 'running' ? 'local runtime' : 'not running'}
              </div>
            </div>
            <span style={{
              fontFamily:LM.mono, fontSize:9, padding:'2px 7px', borderRadius:LM.rad.xs, letterSpacing:'0.1em', textTransform:'uppercase',
              background: off(p.state) ? LM.bgSoft : tone(p.state) + '14',
              color:       tone(p.state),
            }}>{p.state}</span>
            <button aria-expanded={managing === p.id} onClick={() => setManaging(managing === p.id ? null : p.id)}
              style={{ ...smallBtn(), padding:'3px 8px' }}>{off(p.state) ? 'connect' : 'manage'}</button>
          </div>
          {managing === p.id && <ProviderManage p={p} providers={providers} onTab={onTab}/>}
        </div>
      ))}
      {!rows && <SettingsEmpty role={error ? 'alert' : 'status'}
        action={error && <button onClick={providers.refresh} disabled={loading} style={{ ...smallBtn(), padding:'3px 9px', fontStyle:'normal' }}>read again</button>}>
        {error ? 'Provider status was not read: ' + error : 'Reading the providers on this machine\u2026'}</SettingsEmpty>}
      {rows && rows.length === 0 && <SettingsEmpty>No provider is registered on this machine.</SettingsEmpty>}
    </div>
    {/* Social account credentials for connector nodes are not in the design. They sit behind the
        design's own dashed "+ ..." affordance (drawn in Settings › Hosts), below the drawn list. */}
    <button onClick={() => setSocial(!social)} aria-expanded={social} style={{
      marginTop:14, padding:'8px 12px', border:`1px dashed ${LM.line}`, background:'transparent',
      borderRadius:LM.rad.md, color:LM.accent, fontFamily:LM.sans, fontSize:12.5, cursor:'pointer',
      display:'inline-flex', alignItems:'center', gap:7, width:'fit-content',
    }}>
      <span>{social ? '\u2212' : '+'}</span> Social account credentials…
    </button>
    {social && <div style={{ marginTop:10 }}><SettingsSocialEnrollment transport={transport}/></div>}
  </div>
  );
};

// ── Models: per-task routing (design studio-lm.jsx:2935-2966). One route is live: every ask goes
// to the model picked in the composer. The other jobs have no route of their own, so their rows
// say so instead of naming a model and a price.
const SettingsModels = () => {
  const picked = pickedModel();
  const routeless = 'not routed separately in this build';
  return (
  <div>
    <SHead title="Model routing" sub="Different jobs deserve different models. We pick by default, you can override."/>
    {[
      ['Reasoning · planning',     picked ? picked.name : '\u2014', picked ? ([picked.vendor, picked.tag].filter(Boolean).join(' \u00b7 ') || picked.routed || picked.route) : 'no model picked in the composer yet'],
      ['Vision · sketch parsing',  '\u2014', routeless],
      ['Long context (>100k)',     '\u2014', routeless],
      ['Fast bulk · drafts',       '\u2014', routeless],
      ['Embedding · skill search', '\u2014', routeless],
      ['Local fallback (offline)', '\u2014', 'none \u00b7 a refused model is never swapped'],
    ].map(([task, model, sub], i) => (
      <div key={i} style={{
        display:'grid', gridTemplateColumns:'1fr 1fr', gap:14, alignItems:'center',
        padding:'10px 12px', background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.md, marginBottom:6,
      }}>
        <div>
          <div style={{ fontSize:13, fontWeight:500 }}>{task}</div>
          <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, marginTop:2, letterSpacing:'0.04em' }}>{sub}</div>
        </div>
        <button disabled title={i === 0 ? 'Pick the model from the composer model chip' : 'This job has no route of its own'} style={{
          padding:'7px 11px', background:LM.bg, border:`1px dashed ${LM.line}`, borderRadius:LM.rad.sm,
          color: model === '\u2014' ? LM.inkMuted : LM.ink, fontFamily:LM.mono, fontSize:11.5, textAlign:'left', cursor:'default',
          display:'flex', alignItems:'center', gap:6,
        }}>
          <span style={{ flex:1 }}>{model}</span>
          <span style={{ color:LM.inkMuted }}>▾</span>
        </button>
      </div>
    ))}
  </div>
  );
};

// ── BABOOM startup: the owner's choice, saved in this ArchHub's graph (Personal Settings). The
// design has no BABOOM tab; the choice closes the design's own Hosts list, drawn as a host row.
const BaboomStartupRow = ({ first }) => {
  const state = usePersonalTheme(), api = window.ARCHHUB_EXISTING_WORKSHOP;
  const setting = state?.configuration?.baboom_startup;
  const [error, setError] = React.useState('');
  const busy = React.useRef(false);
  const unreadable = setting?.source === 'unreadable';
  const on = setting?.value === 'on';
  const enabled = !!api && setting?.available === true && !unreadable && !state?.pending;
  const change = async () => {
    if (!enabled || busy.current) return;
    busy.current = true;
    setError('');
    try { await api.setBaboomStartup(on ? 'off' : 'on'); }
    catch (failure) { setError(failure.message || 'BABOOM startup could not be changed.'); }
    finally { busy.current = false; }
  };
  const status = !setting ? 'Settings not read' : unreadable ? 'Unreadable' :
    setting.source === 'default' ? 'Default (on)' :
    [on ? 'On' : 'Off', setting.source === 'graph' ? 'Saved' : String(setting.source),
      setting.revision ? 'revision ' + String(setting.revision).slice(-10) : ''].filter(Boolean).join(' · ');
  const col = on && !unreadable ? LM.ok : LM.inkMuted;
  return (
    <div style={{ padding:'10px 14px', display:'flex', alignItems:'center', gap:LM.sp.md,
      borderTop: first ? 'none' : `1px solid ${LM.lineSoft}` }}>
      <span style={{ width:8, height:8, borderRadius:'50%', background:col, flexShrink:0,
        boxShadow: on && !unreadable ? `0 0 0 2px ${LM.ok}22` : 'none' }}/>
      <div style={{ flex:1, lineHeight:1.2, minWidth:0 }}>
        <div style={{ fontSize:13, fontWeight:500, color: on ? LM.ink : LM.inkMuted }}>BABOOM</div>
        <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, letterSpacing:'0.04em', marginTop:2, lineHeight:1.45 }}>
          Start BABOOM when ArchHub opens · {status} · Takes effect next time ArchHub opens.
        </div>
        {unreadable && <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.warn, marginTop:3, lineHeight:1.45 }}>
          Setting unreadable - BABOOM will not start until this is fixed{setting.error ? ' (' + setting.error + ')' : ''}
        </div>}
        {setting && !unreadable && setting.available !== true && <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkSoft, marginTop:3 }}>
          Only the owner of this ArchHub can change this.
        </div>}
        {error && <div role="alert" style={{ fontFamily:LM.mono, fontSize:10, color:LM.warn, marginTop:3, lineHeight:1.45 }}>{error}</div>}
      </div>
      <span style={{
        fontFamily:LM.mono, fontSize:9, padding:'2px 7px', borderRadius:LM.rad.xs,
        background: col + '14', color: col, letterSpacing:'0.1em', textTransform:'uppercase',
      }}>{!setting || unreadable ? 'unread' : on ? 'on start' : 'off'}</span>
      <button type="button" role="switch" aria-checked={on} aria-label="Start BABOOM when ArchHub opens"
        title={enabled ? (on ? 'Do not start BABOOM when ArchHub opens' : 'Start BABOOM when ArchHub opens') : 'BABOOM startup cannot be changed from this view'}
        disabled={!enabled} onClick={change} style={{width:30, height:16, borderRadius:999, padding:1, flexShrink:0,
          position:'relative', border:0, background:on ? LM.accent : LM.lineSoft, transition:'background .15s',
          cursor:enabled ? 'pointer' : 'default', ...(enabled ? {} : {outline:`1px dashed ${LM.line}`, outlineOffset:1})}}>
        <span style={{position:'absolute', top:1, left:on ? 14 : 1, width:14, height:14,
          borderRadius:'50%', background:'#fff', transition:'left .15s'}}/>
      </button>
    </div>
  );
};
// ── Theme / Shortcuts / Storage / About (lighter, but real)
// Theme (design studio-lm.jsx:2969-3009): the cards and rows as drawn, linked to Personal Settings.
// The accent row's "change" opens the saved-theme editor: its state, refresh, the accent and the
// version history all live inside that one design affordance.
const SettingsTheme = () => {
  const state = usePersonalTheme(), api = window.ARCHHUB_EXISTING_WORKSHOP;
  const config = state?.configuration;
  const [accent, setAccent] = React.useState(() => LM.accent);
  const [dirty, setDirty] = React.useState(false);
  const [error, setError] = React.useState('');
  const [editAccent, setEditAccent] = React.useState(false);
  React.useEffect(() => {
    if (!dirty && config?.theme?.accent) setAccent(config.theme.accent);
  }, [dirty, config?.theme?.accent]);
  const oneDraft = config?.personal_wip_heads?.length === 1;
  const unavailable = !api || !config || !oneDraft || state?.pending;
  const run = async (action, clearDraft = false) => {
    setError('');
    try { await action(); if (clearDraft) setDirty(false); }
    catch (failure) { setError(failure.message || 'Personal Settings could not be updated.'); }
  };
  const history = Array.isArray(config?.history) ? config.history : [];
  const versions = history.map((entry, index) => ({entry, index, time:Date.parse(entry.timestamp)}))
    .sort((a, b) => (Number.isFinite(b.time) ? b.time : -Infinity) -
      (Number.isFinite(a.time) ? a.time : -Infinity) || a.index - b.index)
    .slice(0, 10).map(row => row.entry);
  const fieldStyle = {background:LM.bg, color:LM.ink, border:`1px solid ${LM.line}`,
    borderRadius:LM.rad.sm, padding:'4px 9px', fontFamily:LM.mono, fontSize:11};
  const notLinked = 'Not linked to Personal Settings yet';
  const family = stack => String(stack || '').split(',')[0].replace(/['"]/g, '').trim();
  const saved = config?.theme?.accent || LM.accent;
  const alert = error || state?.error || window.ARCHHUB_THEME_ERROR;
  const toggle = () => setEditAccent(!editAccent);
  return <div>
    <SHead title="Theme" sub="Honest dark for honest drafting. Light when you need to share a screen."/>
    <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:10 }}>
      {[
        ['System',  'follows OS', LM.bg, LM.l_bg],
        ['Dark',    'studio default', LM.bg, null],
        ['Light',   'high contrast',  null, LM.l_bg],
      ].map(([name, sub, dark, light]) => (
        <button key={name} disabled title={name === STUDIO_THEME_MODE ? 'The mode the Studio draws' : notLinked} style={{
          padding:'12px 14px', background:LM.bg, border:`1px solid ${name===STUDIO_THEME_MODE?LM.accent:LM.line}`,
          borderRadius:7, textAlign:'left', cursor:'default', color:LM.ink, fontFamily:LM.sans,
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
      <div style={{ background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.md, overflow:'hidden' }}>
        <div style={{ display:'flex', alignItems:'center', gap:10, padding:'8px 12px' }}>
          <span title="Current graph accent" style={{ width:16, height:16, borderRadius:4, background:saved, border:`1px solid ${LM.lineSoft}` }}/>
          <div style={{ flex:1 }}>
            <div style={{ fontSize:12.5 }}>Accent color</div>
            <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, marginTop:1, letterSpacing:'0.04em' }}>{saved} &#xb7; {config ? 'saved in Personal Settings' : 'Personal Settings not read'}</div>
          </div>
          <span role="button" tabIndex={0} aria-expanded={editAccent} onClick={toggle}
            onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } }}
            style={{ color:LM.inkMuted, fontSize:11, cursor:'pointer' }}>{editAccent ? 'close' : 'change'}</span>
        </div>
        {editAccent && <div style={{ padding:'10px 12px 12px', borderTop:`1px solid ${LM.lineSoft}`, background:LM.bgDeep }}>
          <div style={{display:'flex', alignItems:'center', gap:8, fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, letterSpacing:'0.04em'}}>
            <span style={{flex:1}}>{config ? `${config.binding_mode} · ${config.state}` :
              !api && window.ArchHubTheme?.source === 'graph' ? 'Graph theme · read-only in this view' : 'Personal Settings not read'}</span>
            <button title="Refresh Personal Settings" aria-label="Refresh Personal Settings" disabled={!api || state?.pending}
              style={{ ...smallBtn(), padding:'3px 8px' }} onClick={() => run(() => api.refreshTheme())}>&#x21bb;</button>
          </div>
          <div style={{fontSize:11.5, color:LM.inkSoft, lineHeight:1.55, margin:'8px 0'}}>Check text and control contrast after changing colours; automatic contrast adjustment is not available.</div>
          {config && config.binding_mode !== 'personal-wip' && <div style={{fontSize:11.5, color:LM.warn, marginBottom:8}}>
            Saving switches this view to its personal draft, including that draft&#x2019;s other colours.
          </div>}
          <div style={{display:'flex', alignItems:'center', gap:8}}>
            <input aria-label="Choose accent colour" type="color" value={/^#[0-9a-fA-F]{6}$/.test(accent) ? accent : LM.accent}
              onChange={event => {setAccent(event.target.value); setDirty(true);}} disabled={!!state?.pending}
              style={{width:28, height:24, padding:0, border:`1px solid ${LM.line}`, borderRadius:4, background:'transparent'}}/>
            <input aria-label="Accent hex colour" value={accent} maxLength={7} style={{...fieldStyle, width:100}}
              onChange={event => {setAccent(event.target.value); setDirty(true);}} disabled={!!state?.pending}/>
            <button style={{ ...smallBtn(true), padding:'4px 10px' }} disabled={unavailable || !/^#[0-9a-fA-F]{6}$/.test(accent) || accent.toLowerCase() === config?.theme?.accent?.toLowerCase()}
              onClick={() => run(() => api.previewThemeToken('accent', accent), true)}>{state?.pending ? 'Saving\u2026' : 'Save accent'}</button>
          </div>
          {config && !oneDraft && <div style={{fontSize:11.5, color:LM.warn, marginTop:8}}>
            {config.personal_wip_heads.length > 1 ? 'Multiple theme drafts exist; merging is not linked yet.' : 'No personal theme draft is available.'}
          </div>}
          {!!history.length && <div style={{marginTop:12}}>
            <div style={{fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.12em', marginBottom:4}}>VERSIONS &#xb7; SHOWING {Math.min(10,history.length)} OF {history.length}</div>
            {versions.map(entry => <div key={entry.revision} style={{display:'flex', gap:8, alignItems:'center', padding:'7px 0', borderBottom:`1px solid ${LM.lineSoft}`}}>
              <span style={{flex:1, fontSize:11.5, color:LM.inkSoft}}>{entry.reason || entry.state} {entry.current ? '· current' : ''}
                <small style={{display:'block', fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted}}>{entry.timestamp || 'Time unavailable'} · {entry.state} · {entry.digest ? entry.digest.slice(0,10) : String(entry.revision).slice(-10)}</small></span>
              {!entry.current && entry.restore_control && <button style={{ ...smallBtn(), padding:'3px 9px' }} disabled={unavailable}
                onClick={() => run(() => api.restoreThemeRevision(entry.revision))}>Restore</button>}
            </div>)}
          </div>}
        </div>}
      </div>
      {[['Editor font', family(LM.mono)], ['Display font', family(LM.serif) + ' \u00b7 ' + family(LM.sans) + ' for UI'], ['Density', 'Comfortable']].map(([k, v]) => (
        <div key={k} style={{ display:'flex', alignItems:'center', gap:10, padding:'8px 12px', background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.md }}>
          <div style={{ flex:1, minWidth:0 }}>
            <div style={{ fontSize:12.5 }}>{k}</div>
            <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, marginTop:1, letterSpacing:'0.04em' }}>{v}</div>
          </div>
          <span title={notLinked} style={{ color:LM.inkMuted, fontSize:11 }}>change</span>
        </div>
      ))}
    </div>
    {alert && <p role="alert" style={{fontSize:12, color:LM.warn}}>{alert}</p>}
  </div>;
};
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

// Storage (design studio-lm.jsx:3039-3072). The session count is the graph index; nothing measures
// sizes, a training queue or a model cache, so those tiles state no number.
const SettingsStorage = () => (
  <div>
    <SHead title="Storage" sub="Sessions, training queue, cache. Everything is local first."/>
    <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:10, marginBottom:14 }}>
      {[
        ['Sessions', String(LM_SESSIONS.length), 'size not measured'],
        ['Training queue', '\u2014', 'not measured'],
        ['Model cache', '\u2014', 'not measured'],
      ].map(([k, n, sz]) => (
        <div key={k} style={{ padding:'12px 14px', background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:7 }}>
          <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.14em' }}>{k.toUpperCase()}</div>
          <div style={{ fontFamily:LM.serif, fontSize:26, letterSpacing:'-0.02em', marginTop:2, color: n === '\u2014' ? LM.inkMuted : LM.ink }}>{n}</div>
          <div style={{ fontFamily:LM.mono, fontSize:10.5, color:LM.inkSoft, marginTop:1 }}>{sz}</div>
        </div>
      ))}
    </div>
    <div style={{ display:'flex', flexDirection:'column', gap:6 }}>
      {[
        ['Export everything',           'JSON · sessions, memory, profile, skills', LM.ink],
        ['Clear cache',                 'safe — model weights re-download on demand', LM.inkSoft],
        ['Forget all memory',           'irreversible · profile stays', LM.err],
        ['Delete all sessions',         'irreversible · training queue stays', LM.err],
      ].map(([t, sub, col]) => (
        <div key={t} style={{ display:'flex', alignItems:'center', gap:10, padding:'10px 12px', background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.md }}>
          <div style={{ flex:1 }}>
            <div style={{ fontSize:13, color:col }}>{t}</div>
            <div style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, marginTop:2 }}>{sub}</div>
          </div>
          <button onClick={(e) => {
            // Irreversible acts are never one click away from a list.
            const b = e.currentTarget;
            b.textContent = 'opening the folder';
            window.ARCHHUB_REVEAL?.(t.indexOf('session') >= 0 ? 'graph' : 'brain');
            setTimeout(() => { b.textContent = 'do it'; }, 5000);
          }} style={{ ...smallBtn(), color:col, borderColor: col === LM.err ? LM.err + '55' : LM.line }}>do it</button>
        </div>
      ))}
    </div>
  </div>
);

// About (design studio-lm.jsx:3074-3086). Each line reads what answers it: the release transport
// for the build and its update state, this page's own server, the host catalogue and the provider
// registry. The "updated" line's link opens the release update controls.
const SettingsAbout = ({ providers, release }) => {
  const [updates, setUpdates] = React.useState(false);
  React.useEffect(() => {
    const transport = window.ARCHHUB_EXISTING_WORKSHOP;
    return transport?.watchApplicationUpdate ? transport.watchApplicationUpdate() : undefined;
  }, []);
  const rows = providers?.rows;
  const answering = (rows || []).filter(r => r.state === 'keyed' || r.state === 'running').map(r => r.name);
  const label = {idle:'no update in progress', checking:'checking for a release', downloading:'downloading an update',
    ready:'update ready', restarting:'restart requested', failed:'update failed'}[release?.state];
  const toggle = () => setUpdates(!updates);
  return (
  <div>
    <SHead title="About" sub="ArchHub Studio · the AEC stack with one foot in your model and one in the LLM."/>
    <div style={{ background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg, padding:'14px 16px', fontFamily:LM.mono, fontSize:11.5, color:LM.inkSoft, lineHeight:1.85 }}>
      <div><span style={{ color:LM.inkMuted }}>version    </span> {release?.current_build || 'reading\u2026'}</div>
      <div><span style={{ color:LM.inkMuted }}>license    </span> {'\u2014'}</div>
      <div><span style={{ color:LM.inkMuted }}>server     </span> {window.location.host || window.location.origin} &#xb7; running</div>
      <div><span style={{ color:LM.inkMuted }}>hosts      </span> {LM_HOSTS.length} configured &#xb7; {LM_HOSTS.filter(h=>h.state!=='off').length} live</div>
      <div><span style={{ color:LM.inkMuted }}>providers  </span> {rows ? (answering.length ? answering.join(', ') : 'none keyed or running') : providers?.error ? 'not read' : 'reading\u2026'}</div>
      <div><span style={{ color:LM.inkMuted }}>updated    </span> {release?.updated_to ? 'to ' + release.updated_to : (label || 'reading\u2026')} &#xb7; <span role="button" tabIndex={0} aria-expanded={updates}
        onClick={toggle} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } }}
        style={{ color:LM.inkSoft, cursor:'pointer' }}>{updates ? 'hide updates' : 'updates →'}</span></div>
    </div>
    {updates && <ApplicationUpdateControls/>}
  </div>
  );
};

// Hosts (design studio-lm.jsx:3088-3142). The rows are the host catalogue; the BABOOM startup
// choice closes the list as one more row.
const SettingsHosts = ({ store, patch }) => {
  const catalogue = useLiveCatalogue('ARCHHUB_LOAD_HOSTS', LM_HOSTS);
  return (
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
      {!LM_HOSTS.length && <SettingsEmpty role={catalogue.error ? 'alert' : 'status'}
        action={catalogue.error && !catalogue.loading && <button onClick={catalogue.retry} style={{ ...smallBtn(), padding:'3px 9px', fontStyle:'normal' }}>read again</button>}>
        {catalogue.loading ? 'Reading the hosts on this machine\u2026' : catalogue.error ? 'The hosts were not read: ' + catalogue.error : 'No host has answered a probe yet.'}</SettingsEmpty>}
      <BaboomStartupRow first={false}/>
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
};
// ──────────────────────── MODEL PICKER ────────────────────────
// The design's picker (archhub/project/studio-lm.jsx:3145-3208): search, esc, grouped rows. The
// groups are read LIVE from the app (/api/universal/models: the founder's cloud, OpenRouter, LM
// Studio / Ollama on this machine); only discovered rows are selectable, and no price is drawn.
// `routed` is what the router reads: a CLOUD row must reach the cloud, and a cloud id and an
// OpenRouter id look identical. What the design has no place for sits after its groups, in the
// same row shape: open native agent sessions, then Refresh and Clear selection.
const pickerSwatch = (col, fg) => ({ width:22, height:22, borderRadius:4, background:col, color:fg, display:'grid', placeItems:'center', fontFamily:LM.mono, fontSize:11, fontWeight:700, flexShrink:0 });
const pickerRow = (enabled, sel) => ({
  display:'flex', alignItems:'center', gap:10, padding:'8px 10px', borderRadius:LM.rad.md,
  cursor: enabled ? 'pointer' : 'default', background: sel ? LM.bgSoft : 'transparent',
  width:'100%', border:0, color:LM.ink, textAlign:'left', fontFamily:LM.sans,
});
const pickerHover = enabled => enabled ? {
  onMouseEnter:e => { e.currentTarget.style.background = LM.bgHover; },
  onMouseLeave:e => { e.currentTarget.style.background = 'transparent'; },
} : {};
const pickerGroupLabel = () => ({ fontFamily:LM.mono, fontSize:9, color:LM.inkMuted, letterSpacing:'0.18em', padding:'4px 10px' });
const pickerTag = tag => ({
  fontFamily:LM.mono, fontSize:9, padding:'2px 7px', borderRadius:LM.rad.xs, letterSpacing:'0.08em',
  background: tag==='CLOUD'?LM.accentDim : tag==='LOCAL'?LM.ok+'22' : LM.cyan+'22',
  color:       tag==='CLOUD'?LM.accent    : tag==='LOCAL'?LM.ok      : LM.cyan,
});
// Neither discovery waits for the other, and neither may leave the panel saying
// "Discovering..." for ever: whatever has not answered by the deadline says so
// in its own place, and a late answer still draws when it arrives (2026-09-18).
const DISCOVERY_DEADLINE_MS = 8000;
// A stale list is drawn at once; this is when the refresh running behind it is
// collected, without clearing the rows already on screen.
const STALE_REDRAW_MS = 2500;
const ModelPicker = ({ setModel, onClose, model, onNativeSelect }) => {
  const note = { margin:0, padding:'6px 10px', fontFamily:LM.mono, fontSize:10.5, color:LM.inkMuted, lineHeight:1.5, letterSpacing:'0.02em' };
  const onFill = (window.AH && window.AH.onFill) || '#180f08';
  const [live, setLive] = React.useState(null);
  const [catalogueError, setCatalogueError] = React.useState('');
  const [selectionError, setSelectionError] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const [q, setQ] = React.useState('');
  const [native, setNative] = React.useState(null);
  const [nativeError, setNativeError] = React.useState('');
  const [discovery, setDiscovery] = React.useState(0);
  const chooseNative = async row => {
    if (saving || row.kind !== 'native-session' || row.connected !== true ||
        row.selectable === false || row.reason === 'ambiguous_endpoint' || !onNativeSelect) return;
    setSaving(true); setSelectionError('');
    try { await onNativeSelect(row); onClose(); }
    catch (error) { setSelectionError(error?.message || 'The native session could not be selected.'); }
    finally { setSaving(false); }
  };
  const choose = async value => {
    if (saving) return;
    setSaving(true); setSelectionError('');
    try { await setModel(value); onClose(); }
    catch (error) { setSelectionError(error?.message || 'The model selection could not be saved.'); }
    finally { setSaving(false); }
  };
  React.useEffect(() => {
    const controller = new AbortController();
    setCatalogueError(''); setNativeError('');
    const s = window.__archhubSession || {};
    const headers = { 'X-ArchHub-Session': s.token || '', 'X-ArchHub-CSRF': s.csrf || '' };
    let models = false, agents = false, redraw = 0;
    fetch('/api/universal/models', { signal:controller.signal, headers })
      .then(r => { if (!r.ok) throw new Error('Catalogue unavailable'); return r.json(); })
      .then(d => { if (!d || d.ok === false || !Array.isArray(d.groups)) throw new Error('Invalid catalogue');
        models = true; setCatalogueError(''); setLive(d);
        if (d.stale && d.refreshing) redraw = setTimeout(() => setDiscovery(value => value + 1), STALE_REDRAW_MS); })
      .catch(() => { if (!controller.signal.aborted) setCatalogueError('Model discovery is unavailable. Check the provider connection and refresh.'); });
    if (onNativeSelect) fetch('/api/universal/native-agents?apps=claude,codex,opencode,antigravity,antigravity-ide', { signal:controller.signal, headers })
      .then(r => { if (!r.ok) throw new Error('Native discovery unavailable'); return r.json(); })
      .then(d => { if (!d || d.ok === false || !Array.isArray(d.rows)) throw new Error('Invalid native discovery'); agents = true; setNativeError(''); setNative(d); })
      .catch(() => { if (!controller.signal.aborted) setNativeError('Native session discovery is unavailable. Start the client and refresh.'); });
    const deadline = setTimeout(() => {
      const late = ' did not answer within ' + Math.round(DISCOVERY_DEADLINE_MS / 1000) + ' seconds. It is still being asked; use Refresh to ask again.';
      if (!models) setCatalogueError('Model discovery' + late);
      if (onNativeSelect && !agents) setNativeError('Native session discovery' + late);
    }, DISCOVERY_DEADLINE_MS);
    return () => { controller.abort(); clearTimeout(deadline); clearTimeout(redraw); };
  }, [discovery, !!onNativeSelect]);
  const matches = text => !q || String(text).toLowerCase().includes(q.toLowerCase());
  const groups = (live?.groups || []).map(g => ({ ...g, items: (g.items || []).filter(m => matches(m.name + ' ' + m.route + ' ' + (m.vendor||''))).slice(0, q ? 60 : 40) })).filter(g => g.items.length);
  const sessions = (native?.rows || []).filter(row => row.kind === 'native-session' && matches([row.app,row.title,row.workspace].join(' ')));
  const selectedRoute = modelRoute(model);
  return (
    <div onClick={onClose} style={{
      position:'absolute', inset:0, background:'rgba(0,0,0,.55)',
      display:'grid', placeItems:'start center', paddingTop:60, zIndex:50,
    }}>
      <div role="dialog" aria-label="Choose a model" onClick={e => e.stopPropagation()} style={{
        width:600, maxWidth:'92%', background:LM.bgPanel, border:`1px solid ${LM.line}`,
        borderRadius:LM.rad.xl, overflow:'hidden', boxShadow:'0 30px 80px rgba(0,0,0,.6)',
      }}>
        <div style={{ padding:'12px 14px', borderBottom:`1px solid ${LM.line}`, display:'flex', alignItems:'center', gap:10 }}>
          <span style={{ fontSize:14 }}>⌕</span>
          <input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="Search models or paste an OpenRouter id…" style={{
            flex:1, border:0, background:'transparent', color:LM.ink, fontSize:13.5, outline:'none', fontFamily:LM.sans,
          }}/>
          <kbd style={kbd()}>esc</kbd>
        </div>
        <div className="ah-scroll" style={{ maxHeight:420, overflow:'auto', padding:'6px 8px 10px' }}>
          {selectionError && <p role="alert" style={{...note,color:LM.err}}>{selectionError}</p>}
          {saving && <p role="status" style={note}>Saving model selection…</p>}
          {!live && <p role="status" style={note}>{catalogueError || 'Discovering models from connected providers…'}</p>}
          {live?.stale && <p role="status" data-picker-stale="" style={note}>Showing the list last discovered{live.age_seconds ? ' · ' + Math.round(live.age_seconds) + 's old' : ''}{live.refreshing ? ' · refreshing now' : ''}</p>}
          {live && !live.groups.some(group => group.items?.length) && <p role="status" style={note}>
            No models were discovered. Connect an online provider or start a local model service.</p>}
          {groups.map(g => (
            <div key={g.name} style={{ marginTop:LM.sp.sm }}>
              <div style={pickerGroupLabel()}>{g.name}</div>
              {g.items.map(m => {
                const sel = modelRoute(m) === selectedRoute;
                return (
                  <div key={m.route || m.name} onClick={() => choose(m)} style={pickerRow(true, sel)} {...pickerHover(!sel)}>
                    <span style={pickerSwatch(m.col, onFill)}>{m.name[0]}</span>
                    <div style={{ flex:1, lineHeight:1.15, minWidth:0 }}>
                      <div style={{ fontSize:13 }}>{m.name}</div>
                      <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.04em' }}>{m.vendor}{m.ctx ? ' · ctx ' + m.ctx : ''}</div>
                    </div>
                    {m.latency != null && <span style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.ok }}>{m.latency}ms</span>}
                    <span style={pickerTag(m.tag)}>{m.tag}</span>
                  </div>
                );
              })}
            </div>
          ))}
          {Object.keys(live?.source_notes || {}).filter(name => !groups.some(g => g.name === name)).map(name => (
            <div key={name} data-picker-source-note={name} style={{ marginTop:LM.sp.sm }}>
              <div style={pickerGroupLabel()}>{name}</div>
              <p role="status" style={note}>{live.source_notes[name]}</p>
            </div>
          ))}
          {onNativeSelect && <div data-picker-native="" style={{ marginTop:LM.sp.sm }}>
            <div style={pickerGroupLabel()}>NATIVE AGENT SESSIONS</div>
            {nativeError && <p role="status" style={note}>{nativeError}</p>}
            {!native && !nativeError && <p role="status" style={note}>Discovering open agent sessions…</p>}
            {native?.status === 'unavailable' && <p role="status" style={note}>Native session discovery is unavailable. Open your client and refresh.</p>}
            {(Array.isArray(native?.readiness) ? native.readiness : []).map(row =>
              <p key={row.app} style={note}>
                {row.app}: {row.state === 'executable-discovered' ? 'Command-line client found' : 'Command-line client not detected'}.
                {row.state === 'executable-discovered' && !(native.rows || []).some(session => session.app === row.app && session.connected === true)
                  ? ' No open session was discovered.' : ''}
              </p>)}
            {native?.status === 'ok' && !(native.rows || []).some(row => row.kind === 'native-session') &&
              <p role="status" style={note}>No open agent sessions were found. Open a session in your installed client, then refresh.</p>}
            {sessions.map(row => {
              const enabled = !saving && row.connected === true && row.selectable !== false && row.reason !== 'ambiguous_endpoint';
              return (
                <button type="button" key={JSON.stringify([row.app,row.session_id])} disabled={!enabled}
                  onClick={() => chooseNative(row)} style={pickerRow(enabled, false)} {...pickerHover(enabled)}>
                  <span style={pickerSwatch(LM.inkSoft, onFill)}>{String(row.app || '?')[0].toUpperCase()}</span>
                  <div style={{ flex:1, lineHeight:1.15, minWidth:0 }}>
                    <div style={{ fontSize:13 }}>{row.title || 'Untitled session'}</div>
                    <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.04em' }}>
                      {row.reason === 'ambiguous_endpoint' ? 'Multiple endpoints found; select one in the client' :
                        row.connected === true && row.selectable !== false ? 'Open session · connect to this graph' : 'Session unavailable'}
                      {row.workspace ? ' · ' + row.workspace : ''}
                    </div>
                  </div>
                  <span style={pickerTag('')}>{String(row.app || '').toUpperCase()}</span>
                </button>
              );
            })}
          </div>}
          <div data-picker-options="" style={{ marginTop:LM.sp.sm }}>
            <div style={pickerGroupLabel()}>OPTIONS</div>
            <button type="button" disabled={saving} onClick={() => {setLive(null); setNative(null); setDiscovery(value => value + 1);}}
              style={pickerRow(!saving, false)} {...pickerHover(!saving)}>
              <span style={pickerSwatch(LM.bgSoft, LM.inkSoft)}>↻</span>
              <div style={{ flex:1, lineHeight:1.15, minWidth:0 }}>
                <div style={{ fontSize:13 }}>Refresh</div>
                <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.04em' }}>Discover models and open agent sessions again</div>
              </div>
            </button>
            {selectedRoute && <button type="button" disabled={saving} aria-label="Clear this model selection"
              onClick={() => choose({name:'Choose a model', route:'', routed:''})}
              style={pickerRow(!saving, false)} {...pickerHover(!saving)}>
              <span style={pickerSwatch(LM.bgSoft, LM.inkSoft)}>×</span>
              <div style={{ flex:1, lineHeight:1.15, minWidth:0 }}>
                <div style={{ fontSize:13 }}>Clear selection</div>
                <div style={{ fontFamily:LM.mono, fontSize:9.5, color:LM.inkMuted, letterSpacing:'0.04em', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{selectedRoute}</div>
              </div>
            </button>}
          </div>
        </div>
      </div>
    </div>
  );
};

// ──────────────────────── DOCS ────────────────────────
// Lives INSIDE the app shell — same overlay geometry, nav width and type scale as Settings,
// so this is the screen the end user actually gets, only the content differs.
const dCode = window.ArchHubTheme.derive((LM) => ({ fontFamily:LM.mono, fontSize:11.5, lineHeight:1.65, background:LM.bgDeep, border:`1px solid ${LM.lineSoft}`, borderRadius:LM.rad.sm, padding:'11px 13px', color:LM.inkSoft, overflowX:'auto', whiteSpace:'pre', margin:'0 0 14px' }));
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

const DOC_INDEX = [{"s":"start","k":"page","t":"Getting started","d":"ArchHub runs as a local server next to your CAD/BIM host. Nothing leaves your machine unless a node asks it to."},{"s":"canvas","k":"page","t":"The canvas & nodes","d":"A node takes typed inputs, does one job, and emits typed outputs. The canvas is the record of how they connect."},{"s":"connectors","k":"page","t":"Connectors","d":"A connector is a long-lived link to a running application. It is the only thing in ArchHub that can read or write your model."},{"s":"skills","k":"page","t":"Skills as JSON you own","d":"A skill is a saved group of nodes, serialised as plain JSON in your project. No proprietary format, no lock-in, no hidden state."},{"s":"healing","k":"page","t":"Self-healing internals","d":"A graph that stops the moment a host hiccups is not usable in practice. Self-healing is the loop that keeps a long run alive."},{"s":"cli","k":"page","t":"CLI & API reference","d":"Everything Studio does, the CLI does. The UI is a client of the same local server."},{"s":"start","k":"section","t":"INSTALL","d":"Getting started"},{"s":"start","k":"section","t":"FIRST RUN","d":"Getting started"},{"s":"start","k":"section","t":"KEYS","d":"Getting started"},{"s":"canvas","k":"section","t":"THE NINE CATEGORIES","d":"The canvas & nodes"},{"s":"canvas","k":"section","t":"WIRES ARE TYPED","d":"The canvas & nodes"},{"s":"canvas","k":"section","t":"GROUPING","d":"The canvas & nodes"},{"s":"canvas","k":"section","t":"NAVIGATION","d":"The canvas & nodes"},{"s":"connectors","k":"section","t":"SUPPORTED HOSTS","d":"Connectors"},{"s":"connectors","k":"section","t":"LIFECYCLE","d":"Connectors"},{"s":"skills","k":"section","t":"SHAPE","d":"Skills as JSON you own"},{"s":"skills","k":"section","t":"RULES","d":"Skills as JSON you own"},{"s":"healing","k":"section","t":"THE LOOP","d":"Self-healing internals"},{"s":"healing","k":"section","t":"REPAIR STRATEGIES","d":"Self-healing internals"},{"s":"healing","k":"section","t":"GUARANTEES","d":"Self-healing internals"},{"s":"cli","k":"section","t":"CLI","d":"CLI & API reference"},{"s":"cli","k":"section","t":"HTTP","d":"CLI & API reference"},{"s":"cli","k":"section","t":"EXIT CODES","d":"CLI & API reference"},{"s":"start","k":"key","t":"\u2318K","d":"Getting started"},{"s":"start","k":"key","t":"\u2318L","d":"Getting started"},{"s":"start","k":"key","t":"\u2318\u21b5","d":"Getting started"},{"s":"start","k":"key","t":"\u2318,","d":"Getting started"},{"s":"start","k":"key","t":"\u2318/","d":"Getting started"},{"s":"start","k":"cli","t":"archhub up","d":"Getting started"},{"s":"start","k":"cli","t":"archhub doctor","d":"Getting started"},{"s":"cli","k":"cli","t":"archhub up","d":"CLI & API reference"},{"s":"cli","k":"cli","t":"archhub doctor","d":"CLI & API reference"},{"s":"cli","k":"cli","t":"archhub run","d":"CLI & API reference"},{"s":"cli","k":"cli","t":"archhub skill","d":"CLI & API reference"},{"s":"cli","k":"cli","t":"archhub brain","d":"CLI & API reference"},{"s":"cli","k":"cli","t":"archhub hosts","d":"CLI & API reference"},{"s":"cli","k":"cli","t":"archhub logs","d":"CLI & API reference"},{"s":"start","k":"topic","t":"1 \u00b7 Connect a host","d":"Getting started"},{"s":"start","k":"topic","t":"2 \u00b7 Add a provider","d":"Getting started"},{"s":"start","k":"topic","t":"3 \u00b7 Open a session","d":"Getting started"},{"s":"start","k":"topic","t":"4 \u00b7 Place a node","d":"Getting started"},{"s":"canvas","k":"topic","t":"Hosts","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"Read","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"Filter","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"Transform","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"Annotate","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"Compose","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"Logic","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"AI","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"Output","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"Pan","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"Zoom","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"Focus a node","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"Multi-select","d":"The canvas & nodes"},{"s":"canvas","k":"topic","t":"Run","d":"The canvas & nodes"},{"s":"connectors","k":"topic","t":"Revit 2022\u20132025","d":"Connectors"},{"s":"connectors","k":"topic","t":"Rhino 7 / 8","d":"Connectors"},{"s":"connectors","k":"topic","t":"Blender 4.x / 5.x","d":"Connectors"},{"s":"connectors","k":"topic","t":"Speckle","d":"Connectors"},{"s":"connectors","k":"topic","t":"IFC 2x3 / 4","d":"Connectors"},{"s":"skills","k":"topic","t":"inputs / outputs","d":"Skills as JSON you own"},{"s":"skills","k":"topic","t":"params","d":"Skills as JSON you own"},{"s":"skills","k":"topic","t":"requires","d":"Skills as JSON you own"},{"s":"skills","k":"topic","t":"version","d":"Skills as JSON you own"},{"s":"skills","k":"topic","t":"dry_run","d":"Skills as JSON you own"},{"s":"healing","k":"topic","t":"transport","d":"Self-healing internals"},{"s":"healing","k":"topic","t":"version drift","d":"Self-healing internals"},{"s":"healing","k":"topic","t":"auth","d":"Self-healing internals"},{"s":"healing","k":"topic","t":"host busy","d":"Self-healing internals"},{"s":"healing","k":"topic","t":"crash","d":"Self-healing internals"},{"s":"cli","k":"topic","t":"archhub run <session>","d":"CLI & API reference"},{"s":"cli","k":"topic","t":"archhub skill ls | add | rm","d":"CLI & API reference"},{"s":"cli","k":"topic","t":"archhub brain ls | share | forget","d":"CLI & API reference"},{"s":"cli","k":"topic","t":"archhub logs -f","d":"CLI & API reference"}];
// The brain's search entries are DERIVED from brain-model.jsx, never restated. The old static
// entries kept indexing the superseded layer model long after the page stopped saying it, so
// search returned a brain the page no longer held. Deriving makes that drift impossible.
(() => {
  const P = 'The Brain';
  DOC_INDEX.push({ s:'brain', k:'page', t:P, d:'Not a store of facts \u2014 the layer that governs what kinds of things exist, how they relate, and how they are filed.' });
  ['FOUR STRATA', 'THREE LAKES, NOT ONE CASCADE', 'GATES', 'YOUR KEY'].forEach(t => DOC_INDEX.push({ s:'brain', k:'section', t, d:P }));
  (window.BRAIN_STRATA || []).forEach(x => DOC_INDEX.push({ s:'brain', k:'topic', t:x.n + ' \u00b7 ' + x.one, d:P }));
  (window.BRAIN_LAKES  || []).forEach(x => DOC_INDEX.push({ s:'brain', k:'topic', t:x.n + ' brain', d:P }));
  (window.BRAIN_GATES  || []).forEach(x => DOC_INDEX.push({ s:'brain', k:'topic', t:x.label, d:P }));
})();

const DOC_SECTIONS = [
  ['start',      'Getting started', 'install'],
  ['canvas',     'Canvas & nodes',  '9 categories'],
  ['connectors', 'Connectors',      '4 hosts'],
  ['skills',     'Skills as JSON',  'you own them'],
  ['brain',      'Brain',           '4 strata'],
  ['healing',    'Self-healing',    'internals'],
  ['cli',        'CLI & API',       'reference'],
];

const DOC_KIND = { page:'PAGE', section:'SECTION', topic:'TOPIC', key:'KEY', cli:'CLI' };

// Live seam: the design's version slot ("STUDIO · v1.4") names the build this application runs, as the
// release transport reports it. Without that report the label stands alone; no version is typed here.
const docsBuild = () => {
  const build = window.ARCHHUB_EXISTING_WORKSHOP?.getSnapshot?.()?.applicationUpdate?.current_build;
  return typeof build === 'string' && build && build !== 'Unversioned build' ? build : '';
};

const Docs = ({ onClose }) => {
  const [sec, setSec] = React.useState('start');
  const build = docsBuild();
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
          <span style={{ fontFamily:LM.mono, fontSize:10, color:LM.inkMuted, letterSpacing:'0.1em' }}>STUDIO{build ? ' · ' + build : ''}</span>
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

const DocsBrain = () => {
  const strata = window.BRAIN_STRATA || [];
  const gates  = window.BRAIN_GATES || [];
  const keys   = window.BRAIN_KEYS || {};
  const paths  = window.BRAIN_PATHS || {};
  return (
  <div>
    <SHead title="The Brain" sub="Not a store of facts &#x2014; the layer that governs what kinds of things exist, how they relate, and how they are filed."/>
    <DP>The brain is what makes the second session smarter than the first, but it does not mainly hold things. It holds the shape things take. That distinction is the whole design: <b style={{ color:LM.ink, fontWeight:500 }}>the shape can be shared, the contents cannot</b> &#x2014; which is how an office can publish how it works without a single client fact leaving.</DP>
    <DSub>FOUR STRATA</DSub>
    <DRows rows={strata.map(s => [
      s.n + ' \u00b7 ' + s.one,
      s.holds + ' Example: \u201c' + s.eg + '\u201d. ' + (s.travels === 'never past firm' ? 'Stays inside the firm.' : 'Can travel ' + s.travels + '.'),
    ])}/>
    <DP>The top three are how a practice thinks. The bottom one is what it knows. A gate does not ask &#x201c;may this travel?&#x201d; so much as &#x201c;is this structure, or an instance wearing structure&#x2019;s clothes?&#x201d; Every fact is classified on the way in, and <b style={{ color:LM.ink, fontWeight:500 }}>anything the ontology cannot place defaults to sealed</b> &#x2014; it has no release path at all.</DP>
    <DSub>THREE LAKES, NOT ONE CASCADE</DSub>
    <DCode>{`personal     yours \u00b7 opened by your login \u00b7 invisible to the firm
firm         owned by your office's own admin \u00b7 shared inside it
community    structure only \u00b7 no instances, ever \u00b7 cleartext by design`}</DCode>
    <DP>They are separate bodies of water, not layers of one pool. Nothing flows by default; each crossing has a named decider, a consent record and a way back.</DP>
    <DSub>GATES</DSub>
    <DRows rows={gates.map(g => [g.label, 'Decided by ' + g.decider + ' \u00b7 default ' + g.def + '. Passes: ' + g.passes + (g.never !== '\u2014' ? '. Never: ' + g.never : '')])}/>
    <DSub>YOUR KEY</DSub>
    <DP>{keys.how}</DP>
    <DP>{keys.recovery} {keys.cost}</DP>
    <DCode>{`${paths.personal || ''}
  facts.db       encrypted \u00b7 key wrapped by your login
  sealed/        classes with no upload path
  consents.log   append-only \u00b7 what crossed, when, why`}</DCode>
    <DNote>Settings &#x2192; Brain shows the same strata, the same gates and the same classification this page describes &#x2014; both read <code style={{ fontFamily:LM.mono, fontSize:12 }}>brain-model.jsx</code>. If they ever disagree, that is a bug, not a difference of framing.</DNote>
  </div>
  );
};
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
      ['archhub brain ls | share | forget', 'Inspect the strata, share a fact into the firm brain, or forget one. Sealed and unclassified facts have no share path.'],
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

// Application update notice. The desktop check stages a verified release in the background and the
// launcher pushes it here. After any update, a release restart or a local install, the running build is
// confirmed once until dismissed. The notice never blocks work and restarts through the same reload
// action as Settings > About and the tray. Nothing renders while ArchHub is up to date.
const applicationUpdateNoticeState = transport => {
  const snapshot = transport?.getSnapshot?.() || null, status = snapshot?.applicationUpdate;
  return JSON.stringify([status?.state || '', status?.available_build || '', status?.restart_supported === true,
    status?.updated_from || '', status?.updated_to || '', snapshot?.applicationUpdatePending || '',
    snapshot?.applicationUpdateError || '']);
};
const ApplicationUpdateNotice = () => {
  const transport = window.ARCHHUB_EXISTING_WORKSHOP;
  // A string snapshot: unrelated Workshop publishes leave the strip unrendered.
  const [held, setHeld] = React.useState(() => applicationUpdateNoticeState(transport));
  const [refusal, setRefusal] = React.useState('');
  React.useEffect(() => {
    if (!transport?.watchApplicationUpdate) return undefined;
    const unsubscribe = transport.subscribe(() => setHeld(applicationUpdateNoticeState(transport)));
    const unwatch = transport.watchApplicationUpdate();
    setHeld(applicationUpdateNoticeState(transport));
    return () => { unsubscribe(); unwatch(); };
  }, [transport]);
  const [state, build, restartSupported, updatedFrom, updatedTo, pending, error] = JSON.parse(held);
  const message = error || refusal;
  const [warning, restart] = useRestartConfirmation(state === 'ready' && !message, () => act('reload'));
  const offered = !!build && ['ready', 'restarting'].includes(state);
  // A first read that failed or never answered stays visible with Read status, so its confirmation is not lost.
  if (!offered && !updatedTo && !(error && !state)) return null;
  const act = async action => {
    setRefusal('');
    try {
      if (action === 'read') await transport.refreshApplicationUpdate();
      else await transport.applicationUpdateAction(action);
    } catch (failure) {
      if (!transport.getSnapshot()?.applicationUpdateError) setRefusal(failure.message || 'The update request could not be confirmed.');
    }
  };
  const label = !offered ? 'Updated to build ' + updatedTo :
    state === 'restarting' ? 'Restarting into build ' + build : 'Update ready \u00b7 build ' + build;
  const title = message || (offered ? label :
    updatedFrom ? 'Updated from build ' + updatedFrom + ' to build ' + updatedTo : label);
  const action = {height:16, padding:'0 7px', borderRadius:LM.rad.xs, border:`1px solid ${LM.accent}`,
    background:LM.accentDim, color:LM.accent, fontFamily:LM.mono, fontSize:9.5, letterSpacing:'0.05em',
    lineHeight:'14px', flexShrink:0, cursor:pending ? 'default' : 'pointer', opacity:pending ? .6 : 1};
  return <div role={message ? 'alert' : 'status'} aria-label="Application update" title={title}
    style={{display:'flex', alignItems:'center', gap:6, minWidth:0, padding:'0 4px', whiteSpace:'nowrap',
      fontFamily:LM.mono, fontSize:9.5, letterSpacing:'0.05em', color:message ? LM.err : LM.accent}}>
    <span aria-hidden="true">{'\u25cf'}</span>
    <span style={{minWidth:0, overflow:'hidden', textOverflow:'ellipsis'}}>{message || label}</span>
    {state === 'ready' && offered && !message && restartSupported && <button type="button" disabled={!!pending}
      onClick={restart} title={warning ? 'Click again to restart into build ' + build : 'Restart into build ' + build}
      style={warning ? {...action, background:LM.accent, color:LM.bg} : action}>
      {warning || 'Restart to update'}</button>}
    {state === 'ready' && offered && !message && !restartSupported && <span style={{color:LM.inkSoft}}>
      restart ArchHub to install</span>}
    {!offered && !message && <button type="button" disabled={!!pending} onClick={() => act('acknowledge')}
      title="Hide this confirmation" style={action}>Dismiss</button>}
    {message && (state === 'ready' || !offered) && <button type="button" disabled={!!pending}
      onClick={() => act('read')} style={action}>Read status</button>}
    <span aria-hidden="true" style={{color:LM.inkDim, padding:'0 2px'}}>{'\u00b7'}</span>
  </div>;
};

// ──────────────────────── SERVER STRIP ────────────────────────
const ServerStrip = ({ session, model, setSettingsOpen, setDocsOpen }) => {
  // Live values in the design's slots: this server's port, the connectors that drive a host, and the running build.
  const drives = (window.ARCHHUB_LIVE?.connectors || []).filter(c => c.drive);
  const live = drives.filter(c => c.state === 'connected' || c.state === 'listening').length;
  const port = window.location.port || (window.location.protocol === 'https:' ? '443' : '80');
  const transport = window.ARCHHUB_EXISTING_WORKSHOP;
  const readBuild = () => String(transport?.getSnapshot?.()?.applicationUpdate?.current_build || '');
  const [build, setBuild] = React.useState(readBuild);
  React.useEffect(() => transport?.subscribe ? transport.subscribe(() => setBuild(readBuild())) : undefined, [transport]);
  const StripItem = ({ onClick, children, accent }) => {
    const [h, setH] = React.useState(false);
    return (
      <button onClick={onClick}
        onMouseEnter={() => setH(true)} onMouseLeave={() => setH(false)}
        style={{
          background:'transparent', border:0, padding:'0 4px',
          cursor: onClick ? 'pointer' : 'default',
          color: h && onClick ? LM.ink : (accent || LM.inkMuted),
          fontFamily:LM.mono, fontSize:9.5, letterSpacing:'0.05em', whiteSpace:'nowrap',
          transition:'color .12s',
        }}>{children}</button>
    );
  };
  return (
    <div style={{
      // minWidth 0: at the narrowest window the update notice ellipsizes instead of widening the shell grid.
      gridColumn:'1 / -1', gridRow:'2', minWidth:0,
      background:LM.bgPanel, borderTop:`1px solid ${LM.line}`,
      padding:'0 10px', display:'flex', alignItems:'center', gap:LM.sp.xs,
    }}>
      <StripItem onClick={() => setSettingsOpen && setSettingsOpen(true)}>
        <span style={{ color:LM.ok }}>●</span> server :{port} · {live}/{drives.length} hosts
      </StripItem>
      {session ? (
        <>
          <span style={{ color:LM.inkDim, padding:'0 2px' }}>·</span>
          <StripItem>{session.file}</StripItem>
          {/* The model slot names the picked model; with nothing picked it is not drawn, never the placeholder's slug. */}
          {modelRoute(model) && <>
            <span style={{ color:LM.inkDim, padding:'0 2px' }}>{'\u00b7'}</span>
            <StripItem onClick={() => setSettingsOpen && setSettingsOpen(true)}>
              <span style={{ color:LM.inkSoft }}>{String(model.name || modelRoute(model)).toLowerCase().replace(/\s+/g,'-')}</span>
            </StripItem>
          </>}
        </>
      ) : (
        <>
          <span style={{ color:LM.inkDim, padding:'0 2px' }}>·</span>
          <StripItem>{LM_SESSIONS.length} sessions · {LM_SESSIONS.filter(s=>s.state==='running').length} running</StripItem>
        </>
      )}
      <div style={{ flex:1 }}/>
      <ApplicationUpdateNotice/>
      <StripItem onClick={() => setDocsOpen && setDocsOpen(true)}>docs</StripItem>
      <span style={{ color:LM.inkDim, padding:'0 2px' }}>·</span>
      <StripItem onClick={() => setSettingsOpen && setSettingsOpen(true)}>settings</StripItem>
      {build && <>
        <span style={{ color:LM.inkDim, padding:'0 2px' }}>·</span>
        <StripItem>{build}</StripItem>
      </>}
    </div>
  );
};

window.StudioLM = StudioLM;

})();
