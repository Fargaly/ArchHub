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

const Icon = window.Icon;
const ReactDOM = window.ReactDOM;
const LM = window.AH;  // tokens.jsx — single source of truth
LM.fs = LM.fs || {};
LM.fs.label = LM.fs.label || {sz:11, ln:14, wt:500, letter:'.04em'};
LM.fs.dataSm = LM.fs.dataSm || {sz:11, ln:14, wt:400};
LM.fs.caption = LM.fs.caption || {sz:12, ln:16, wt:400};
LM.icon = LM.icon || {};
LM.icon.category = LM.icon.category || {size:12, box:20};
const WORKSHOP_UNAVAILABLE_ROOT = 'studio:workshop-unavailable';

// Categories and signal colours come from node-registry.jsx - one definition, read by the
// canvas, the node library and the minimap alike.
const CAT = window.AH_CAT;
const WIRE = window.AH_WIRE;

const studioCategory = name => CAT[name] || CAT[String(name || '').toLowerCase()] || {col:LM.accent, icon:'○', label:name, role:''};
// A cleared selection retains the server's primary focus for navigation. That
// retained card or wire is not the empty-selection graph inspector's target.
const studioInspectorFocus = state => {
  const root = state?.selected || null, canvas = state?.canvas;
  if (!root || !Array.isArray(canvas?.selection) || canvas.selection.length ||
      canvas.selection_hidden === true) return root;
  return [...(state.graph?.nodes || []), ...(state.graph?.wires || [])].some(item => item.id === root) ? null : root;
};
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
const systemAllowed = (canvas, graph) => canvas?.authorization?.system_view === true &&
  (graph?.nodes || []).some(node => node.application === true);
const systemSessionId = (rootCanvas, gateCanvas, graph) => {
  const root = rootCanvas?.application_root || rootCanvas?.graph_id ||
    gateCanvas?.application_root || gateCanvas?.graph_id || '';
  // A child scope has no application cards. Admission must precede the root
  // projection; the renderer still checks systemAllowed on the returned graph.
  return root && gateCanvas?.authorization?.system_view === true ? 'system:' + root : '';
};
const systemGraphSession = id => ({ id, title:'ArchHub application', state:'idle', host:'archhub', when:'saved',
  file:'Application graph', last:'ArchHub application parts and registries.', model:'' });
const studioCreatedNodeId = (result, refreshed, beforeIds) => {
  const direct = result && (result.node || result.selected || result.id);
  if (direct) return direct;
  const scopeRoot = refreshed?.root || refreshed?.scope?.current || refreshed?.canvas?.root || refreshed?.canvas?.scope?.current;
  const root = result?.root;
  if (root && root !== scopeRoot) return root;
  const held = refreshed?.nodes || refreshed?.graph?.nodes ||
    refreshed?.topology?.canvas?.nodes ||
    window.ARCHHUB_STUDIO_AUTHORITY?.getSnapshot?.()?.canvas?.nodes ||
    window.ARCHHUB_EXISTING_WORKSHOP?.getSnapshot?.()?.topology?.canvas?.nodes || [];
  return (held.find(node => node?.id && !beforeIds.has(node.id)) || {}).id || null;
};
let LM_SESSIONS = (window.ARCHHUB_LIVE?.sessions) || [];
const LM_HOSTS = (window.ARCHHUB_LIVE?.hosts) || [];
const LM_STATE_META = window.ArchHubTheme.derive((LM) => ({
  idle:     { label:'saved',       col:LM.inkSoft },
  running:  { label:'running',     col:LM.accent, pulse:true },
  done:     { label:'done',        col:LM.ok },
  review:   { label:'needs review',col:LM.warn },
  paused:   { label:'paused',      col:LM.inkSoft },
  workflow: { label:'workflow',    col:LM.purple },
  scheduled:{ label:'scheduled',   col:LM.cyan },
}));

// DSYS-060 app frame parts. The frame is one shell around Home, graph, Workshop and tool pages.
const Crumb = ({ items }) => <span style={{ fontSize:12, color:LM.inkSoft }}>
  {items.map((t, i) => <span key={String(t) + ':' + i}>{i > 0 && <span style={{ margin:'0 6px' }}>▸</span>}
    <span style={{ color:i === items.length - 1 ? LM.ink : LM.inkSoft }}>{t}</span></span>)}
</span>;
const PanelHead = ({ title, children }) => (
  <div style={{ display:'flex', alignItems:'center', gap:8, height:44, padding:'0 12px',
    borderBottom:`1px solid ${LM.lineSoft}` }}>
    <span style={{ fontSize:16, fontWeight:600 }}>{title}</span><span style={window.AH_DS.styles.fill}/>{children}
  </div>
);
const Search = ({ ph, children }) => (
  <div style={{ margin:'10px 12px', height:32, borderRadius:5, background:LM.bgSoft,
    border:`1px solid ${LM.line}`, display:'flex', alignItems:'center', gap:8, padding:'0 10px',
    fontSize:13, color:LM.inkSoft }}>
    <span>⌕</span>{children || <span>{ph}</span>}<span style={window.AH_DS.styles.fill}/><span style={{ fontSize:11 }}>Ctrl K</span>
  </div>
);
const Frame = ({ rail, left, top, children, insp, status, onHome, onPanel, onSettings, onWorkshop, onCanvas, onChats, onDocs, onCockpit, onAccount, account, workshopWindow = false }) => {
  const AppRail = window.ARCHHUB_APP_RAIL;
  const waiting = workshopWaitingItems(useWorkshopProjection()).length;
  const hasLeft = !!left;
  const contentColumn = hasLeft ? '3 / -1' : '2 / -1';
  const railWidth = hasLeft || rail === 'Library' ? 44 : 64;
  return (
    <section data-app-frame="" style={{
      width:'100%', height:'100%', background:LM.bgDeep, color:LM.ink, fontFamily:LM.sans,
      fontSize:13, lineHeight:1.5, display:'grid',
      gridTemplateColumns:hasLeft ? `${railWidth}px 248px minmax(0, 1fr) 320px` : `${railWidth}px minmax(0, 1fr)`,
      gridTemplateRows:'36px minmax(0, 1fr) 22px',
      overflow:'hidden', position:'relative',
    }}>
      <AppRail persistent compact={railWidth===44} workshop={workshopWindow} active={rail || 'Home'} waiting={waiting} account={account} onNavigate={name => {
        const route = {Home:onHome, Chats:onChats, Workshop:onWorkshop, Canvas:onCanvas, Library:() => onPanel?.('nodes'), Docs:onDocs, Cockpit:onCockpit, Settings:onSettings, Account:onAccount || onSettings}[name];
        route?.();
      }}/>

      {hasLeft && <aside data-left-panel="" style={{ gridColumn:'2', gridRow:'1 / span 2', background:LM.bgPanel, borderRight:`1px solid ${LM.line}`,
        minHeight:0, overflow:'hidden' }}>{left}</aside>}
      <div data-workspace-frame="" style={{ gridColumn:contentColumn, gridRow:'1 / span 2',
        height:'100%', minHeight:0, minWidth:0, overflow:'hidden' }}>
        {children}
      </div>
      {top && !workshopWindow && <div style={{ gridColumn:contentColumn, gridRow:'1', display:'flex', alignItems:'center', gap:10,
        padding:'0 12px', borderBottom:`1px solid ${LM.lineSoft}`, background:LM.bg }}>{top}</div>}
      {insp && <aside style={{ gridColumn:'4', gridRow:'2', background:LM.bgPanel, minHeight:0, overflow:'hidden',
        display:'grid', gridTemplateRows:'auto 1fr' }}>{insp}</aside>}
      <footer data-app-status="" style={{ gridColumn:'1 / -1', gridRow:'3', display:'flex', alignItems:'center', gap:14, padding:'0 12px',
        fontSize:11, color:LM.inkSoft, borderTop:`1px solid ${LM.lineSoft}`, background:LM.bgDeep, minWidth:0 }}>
        {status}
      </footer>
    </section>
  );
};
const isHistoryNode = node => !!node && (
  node.kind === 'history' ||
  node.engine === 'app:history'
);
const historyShortTime = timestamp => {
  const date = new Date(timestamp || '');
  if (!Number.isFinite(date.getTime())) return '';
  const now = new Date();
  const day = value => new Date(value.getFullYear(), value.getMonth(), value.getDate()).getTime();
  const daysAgo = Math.round((day(now) - day(date)) / 86400000);
  const time = date.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', hour12:false});
  if (daysAgo === 0) return time + ' · today';
  if (daysAgo === 1) return 'yesterday ' + time;
  return date.toLocaleDateString([], {year:date.getFullYear() === now.getFullYear() ? undefined : 'numeric', month:'short', day:'numeric'});
};
const historyTargetLabel = row => row?.target_label || row?.operation_type || row?.type || row?.operation || 'graph';
window.ArchHubHistory = {isNode:isHistoryNode, shortTime:historyShortTime, targetLabel:historyTargetLabel};
const historyRowsFromCanvas = canvas => Array.isArray(canvas?.action_history?.transactions)
  ? canvas.action_history.transactions : [];
const decorateHistoryNode = (node, canvas) => {
  if (!isHistoryNode(node)) return node;
  const rows = historyRowsFromCanvas(canvas);
  const params = Array.isArray(node.params) ? node.params : [];
  return {
    ...node,
    cat:node.cat || 'app',
    sub:node.sub || 'signed authority history',
    history_node:true,
    history_rows:rows,
    action_history:canvas?.action_history || null,
    params,
  };
};

const HISTORY_LIBRARY_ITEM = Object.freeze({id:'app-history', title:'History', sub:'Signed authority history', engine:'app:history',
  kind:'history', noEngine:false});
// Graph-held compatibility aliases stay available by identity in the API, but
// only the public catalogue entries belong in counts, search and insert controls.
const visibleLibraryGroups = groups => (Array.isArray(groups) ? groups : [])
  .map(group => ({...group, items:(Array.isArray(group?.items) ? group.items : [])
    .filter(item => item && item.hidden !== true)}))
  .filter(group => group.items.length);
const withHistoryLibrary = groups => {
  const source = visibleLibraryGroups(groups);
  if (source.some(group => (group.items || []).some(item => item.engine === 'app:history' || item.id === 'app-history'))) return source;
  const appIndex = source.findIndex(group => group.cat === 'App');
  if (appIndex >= 0) return source.map((group, index) => index === appIndex
    ? {...group, items:[...(group.items || []), HISTORY_LIBRARY_ITEM]} : group);
  return [...source, {cat:'App', items:[HISTORY_LIBRARY_ITEM]}];
};

const HistoryBody = ({ n }) => {
  const rows = Array.isArray(n.history_rows) ? n.history_rows : [];
  const preview = rows.slice(0, 5);
  const openInspector = () => {
    window.__archhubSelectNodeById?.(n.id);
  };
  return <div data-history-card="true" style={{ margin:'8px 10px 8px', background:LM.bgSoft, border:`1px solid ${LM.lineSoft}`,
    borderRadius:5, padding:'6px 7px', display:'flex', flexDirection:'column', gap:5 }}>
    {preview.length ? preview.map(row => (
      <div key={row.root || row.timestamp || row.operation} data-history-row={row.root || ''} style={{
        display:'grid', gridTemplateColumns:'minmax(0,1fr) auto', gap:6, alignItems:'center',
        fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, lineHeight:LM.fs.dataSm.ln + 'px', color:LM.ink }}>
        <span style={{ overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
          {historyShortTime(row.timestamp)} {row.actor || row.capability || 'Graph'} · {row.operation || 'Graph change'} · {historyTargetLabel(row)}
        </span>
        <span style={{ color:row.state === 'applied' ? LM.ok : LM.inkSoft }}>{row.state || 'kept'}</span>
      </div>
    )) : <div role="status" style={{ fontSize:11, color:LM.inkSoft }}>No graph actions yet.</div>}
    {rows.length > preview.length && <window.AH_DS.Btn type="button" onClick={openInspector} style={{ border:0, padding:0, background:'transparent',
      textAlign:'left', cursor:'pointer', fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, lineHeight:LM.fs.dataSm.ln + 'px', color:LM.inkSoft }}>
      +{rows.length - preview.length} more
    </window.AH_DS.Btn>}
  </div>;
};


const CommandBar = ({ open, onClose, addNodeFromLibrary, onOpenSession, onChats }) => {
  useNodeLibrary(open);
  useCatalogueVersion();
  React.useEffect(() => {
    if (open && !catalogueStates.get('ARCHHUB_LOAD_SKILLS')?.read) loadCatalogue('ARCHHUB_LOAD_SKILLS', LM_SAVED_SKILLS);
  }, [open]);
  const projected = useStudioProjection();
  const library = withHistoryLibrary(window.AH_LIBRARY || projected?.library || LM_LIBRARY);
  const [q, setQ] = React.useState('');
  const [commandError, setCommandError] = React.useState('');
  const inputRef = React.useRef(null);
  React.useEffect(() => { if (open) setTimeout(() => inputRef.current?.focus(), 0); else { setQ(''); setCommandError(''); } }, [open]);
  if (!open) return null;
  const needle = q.trim().toLowerCase();
  const match = text => !needle || String(text || '').toLowerCase().includes(needle);
  const rows = [];
  const updateRestart = document.querySelector('[data-update-restart]');
  if (updateRestart && !updateRestart.disabled && match(updateRestart.textContent)) {
    rows.push({group:'Application', icon:'↻', color:LM.accent, label:updateRestart.textContent.trim(),
      meta:'Ctrl+Shift+U', run:()=>updateRestart.click()});
  }
  for (const button of document.querySelectorAll('[data-social-provider] button')) {
    if (button.disabled) continue;
    const provider = button.closest('[data-social-provider]');
    const label = button.textContent.trim() + ' · ' + provider.getAttribute('data-social-name');
    if (match(label)) rows.push({group:'Connections',icon:'⌁',color:LM.accent,label,run:()=>button.click()});
  }
  // The palette invokes the visible Home controls, retaining their one guarded handler.
  for (const button of document.querySelectorAll('[data-home-page] [data-template-start], [data-home-page] [data-template-edit], [data-home-page] [data-template-editor] button, [data-home-page] [data-workshop-primary], [data-home-page] [data-approval-open-sheets], [data-home-result] button')) {
    if (button.disabled) continue;
    const template = button.closest('[data-home-template]'), result = button.closest('[data-home-result]');
    const label = button.textContent.trim() + (template ? ' · '+(template.querySelector('[data-template-edit]')?.textContent || '') : result ? ' · '+result.textContent.replace(button.textContent,'').trim() : '');
    if (match(label)) rows.push({group:'Home',icon:'⌂',color:LM.inkSoft,label,run:()=>button.click()});
  }
  for (const group of library) {
    for (const item of (group.items || [])) {
      if (!match([item.title, item.sub, group.cat].join(' '))) continue;
      rows.push({group:'Add node', icon:studioCategory(group.cat).icon, color:studioCategory(group.cat).col,
        label:item.title, meta:item.sub || group.cat, hint:rows.length === 0 ? 'Enter' : '',
        run:() => addNodeFromLibrary && addNodeFromLibrary({...item, cat:group.cat})});
      if (rows.filter(row => row.group === 'Add node').length >= 4) break;
    }
    if (rows.filter(row => row.group === 'Add node').length >= 4) break;
  }
  for (const skill of LM_SAVED_SKILLS.filter(skill => match([skill.name, skill.description, skill.source].join(' ')))) {
    rows.push({group:'Skills', icon:'✦', color:LM.accent, label:skill.name || 'Skill',
      meta:skill.source || skill.description || 'saved workflow',
      run:() => {
        const openSkill = window.ArchHubStudioScreens?.open;
        if (typeof openSkill !== 'function') {
          setCommandError('Skill viewer is unavailable. Open Library > Skills instead.');
          return false;
        }
        try {
          openSkill('skill', skill);
          return true;
        } catch (error) {
          setCommandError(error?.message || 'Skill viewer is unavailable.');
          return false;
        }
      }});
  }
  for (const chat of LM_SESSIONS.filter(session => match([session.title, session.file, session.state].join(' '))).slice(0, 3)) {
    rows.push({group:'Chats', icon:'◌', color:LM.inkSoft, label:chat.title || 'Graph',
      meta:chat.when || chat.file || 'conversation', run:() => onOpenSession && onOpenSession(chat.id)});
  }
  if (onChats && match('Chats conversations')) rows.push({group:'Navigation', icon:'◌', color:LM.inkSoft,
    label:'Chats', meta:'Conversations', run:onChats});
  const activate = row => {
    if (!row) return;
    setCommandError('');
    const keepOpen = row.run?.() === false;
    if (!keepOpen) onClose?.();
  };
  const onKeyDown = e => {
    if (e.key === 'Escape') { e.preventDefault(); onClose?.(); return; }
    if (e.key === 'Enter') { e.preventDefault(); activate(rows[0]); }
  };
  const grouped = rows.reduce((acc, row) => ((acc[row.group] ||= []).push(row), acc), {});
  return (
    <div data-command-bar="" role="dialog" aria-label="Command bar" onMouseDown={e => { if (e.target === e.currentTarget) onClose?.(); }}
      style={{ position:'absolute', inset:0, zIndex:80, background:'rgba(0,0,0,.18)' }}>
      <div style={{ position:'absolute', left:206, top:244, width:462, maxWidth:'calc(100% - 64px)',
        background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:8, boxShadow:LM.shadow.dialog,
        overflow:'hidden', color:LM.ink }}>
        <div style={{ height:44, display:'flex', alignItems:'center', gap:9, padding:'0 14px', borderBottom:`1px solid ${LM.lineSoft}` }}>
          <span style={window.AH_DS.styles.muted}>⌕</span>
          <input ref={inputRef} value={q} onChange={e => setQ(e.target.value)} onKeyDown={onKeyDown}
            placeholder="Search" aria-label="Search commands" style={{ flex:1, minWidth:0, border:0, outline:0,
            background:'transparent', color:LM.ink, fontFamily:LM.sans, fontSize:13 }}/>
          <span style={{ fontSize:11, color:LM.inkSoft }}>Esc</span>
        </div>
        {commandError && <div role="alert" style={{ padding:'7px 14px 0', color:LM.err, fontSize:12 }}>{commandError}</div>}
        <div style={{ padding:'7px 6px 10px', display:'grid', gap:7, maxHeight:360, overflow:'auto' }}>
          {Object.entries(grouped).map(([group, groupRows]) => (
            <div key={group}>
              <div style={{ padding:'0 9px 5px', color:LM.inkSoft, fontSize:11 }}>{group}</div>
              {groupRows.map((row, index) => (
                <window.AH_DS.Btn type="button" key={group + ':' + row.label + ':' + index} onClick={() => activate(row)}
                  style={{ width:'100%', height:32, display:'flex', alignItems:'center', gap:9, padding:'0 9px',
                    border:0, borderRadius:5, background:index === 0 && group === Object.keys(grouped)[0] ? LM.bgHover : 'transparent',
                    color:LM.ink, fontFamily:LM.sans, textAlign:'left', cursor:'pointer' }}>
                  <span style={{ width:18, height:18, borderRadius:5, display:'grid', placeItems:'center', flex:'none',
                    background:row.color + '33', color:row.color, fontSize:11 }}>{row.icon}</span>
                  <span style={{ flex:1, minWidth:0, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap',
                    fontSize:13, fontWeight:600 }}>{row.label}</span>
                  <span style={{ color:LM.inkSoft, fontSize:12, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{row.meta}</span>
                  {row.hint && <span style={{ color:LM.inkSoft, fontSize:11, marginLeft:6 }}>{row.hint}</span>}
                </window.AH_DS.Btn>
              ))}
            </div>
          ))}
          {!rows.length && <div role="status" style={{ padding:'10px 9px', color:LM.inkSoft, fontSize:12 }}>No matching commands.</div>}
        </div>
      </div>
    </div>
  );
};
const AppToast = ({ toast }) => {
  React.useEffect(() => {
    if (!toast?.id || !toast.close) return;
    const timer = window.setTimeout(toast.close, 6000);
    return () => window.clearTimeout(timer);
  }, [toast?.id]);
  if (!toast) return null;
  const isErr = toast.tone === 'err';
  const icon = toast.icon || (isErr ? '✕' : toast.tone === 'run' ? '●' : '✓');
  return (
    <div data-app-toast="" data-no-pan="" role={isErr ? 'alert' : 'status'} style={{
      position:'fixed', left:'50%', bottom:28, transform:'translateX(-50%)', zIndex:120,
      minWidth:320, maxWidth:'min(520px, calc(100% - 48px))', height:42, boxSizing:'border-box',
      display:'flex', alignItems:'center', gap:10, padding:'0 14px',
      background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:6, boxShadow:LM.shadow.dialog,
      color:LM.ink, fontFamily:LM.sans, fontSize:13,
    }}>
      <span style={{ color:isErr ? LM.err : toast.tone === 'run' ? LM.accent : LM.ok }}>{icon}</span>
      <span style={{ flex:1, minWidth:0, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', fontWeight:600 }}>{isErr ? window.AH_DS.errorText(toast.text) : toast.text}</span>
      {toast.actionLabel && <window.AH_DS.Btn type="button" onClick={toast.action} style={{
        border:0, background:'transparent', color:LM.ink, fontFamily:LM.sans, fontSize:13, fontWeight:700, cursor:'pointer',
      }}>{toast.actionLabel}</window.AH_DS.Btn>}
    </div>
  );
};
const DestructiveDialog = ({ confirming, onCancel, onConfirm }) => {
  if (!confirming) return null;
  const nodes = confirming.ids?.length || 0;
  const wires = confirming.wires || 0;
  const noun = (n, one) => n + ' ' + one + (n === 1 ? '' : 's');
  const title = confirming.kind === 'clear' ? 'Delete all nodes?' : 'Delete “' + confirming.title + '”?';
  return (
    <div data-no-pan="" role="presentation" style={{ position:'absolute', inset:0, zIndex:75, background:'rgba(0,0,0,.5)',
      display:'grid', placeItems:'center' }}>
      <div role="alertdialog" aria-label="Confirm delete" aria-modal="true" style={{
        width:400, maxWidth:'calc(100% - 48px)', background:LM.bgPanel, border:`1px solid ${LM.line}`,
        borderRadius:8, boxShadow:LM.shadow.dialog, padding:20, color:LM.ink, fontFamily:LM.sans,
      }}>
        <h2 style={{ margin:'0 0 10px', fontSize:16, lineHeight:'22px', fontWeight:700 }}>{title}</h2>
        <p style={{ margin:'0 0 16px', fontSize:13, lineHeight:'19px', color:LM.inkSoft }}>
          {noun(nodes, 'node') + ' and ' + noun(wires, 'wire') + ' go with it. Undo brings them back.'}
        </p>
        <div style={{ display:'flex', justifyContent:'flex-end', gap:12 }}>
          <window.AH_DS.Btn type="button" autoFocus onClick={onCancel} style={{...window.AH_DS.styles.button("ghost", true), color:LM.ink, border:'1px solid transparent'}}>Cancel</window.AH_DS.Btn>
          <window.AH_DS.Btn type="button" onClick={onConfirm} style={{...window.AH_DS.styles.button("ghost", true), background:LM.err, border:`1px solid ${LM.err}`, color:LM.onFill}}>Delete</window.AH_DS.Btn>
        </div>
      </div>
    </div>
  );
};

// ─── The active graph for "walls" session — typed AEC nodes
let LM_GRAPH = (window.ARCHHUB_LIVE?.graph) || { nodes: [], wires: [] };


// The insertable nodes: one definition, served by the graph (library_engines).
// Served by the graph (studio.html sets it from /api/universal/node-library); never typed here.
const LM_LIBRARY = visibleLibraryGroups(window.AH_LIBRARY || []);

// ──────────────────────── ROOT ────────────────────────
// Alt+Left / Alt+Right and the keyboard's Back / Forward keys ask the page to navigate away.
const studioLeavesPage = e => e.key === 'BrowserBack' || e.key === 'BrowserForward' ||
  (e.altKey && !e.ctrlKey && !e.metaKey && (e.key === 'ArrowLeft' || e.key === 'ArrowRight'));
const studioTextEntryTarget = target => !!target?.closest?.('input,textarea,select,[contenteditable="true"],[role="textbox"]');
const studioShortcut = binding => Object.freeze({
  ...binding,
  combos:Object.freeze(binding.combos.map(combo => Object.freeze(combo))),
});
const STUDIO_SHORTCUT_BINDINGS = Object.freeze([
  studioShortcut({id:'open-command-bar', label:'Open the command bar', scope:'global', display:'Ctrl/Cmd+K', menu:'⌘K', action:'open-command-bar', combos:[{key:'k', ctrlOrMeta:true}]}),
  studioShortcut({id:'toggle-settings', label:'Toggle settings', scope:'global', display:'Ctrl/Cmd+,', menu:'⌘,', action:'toggle-settings', combos:[{key:',', ctrlOrMeta:true}]}),
  studioShortcut({id:'open-documentation', label:'Open documentation', scope:'global', display:'Ctrl/Cmd+/', menu:'⌘/', action:'open-documentation', combos:[{key:'/', ctrlOrMeta:true}]}),
  studioShortcut({id:'close-overlays', label:'Close settings, docs, or catalogue', scope:'global', display:'Esc', menu:'Esc', action:'close-overlays', combos:[{key:'Escape', anyModifiers:true}]}),
  studioShortcut({id:'canvas-open-menu', label:'Open canvas menu', scope:'canvas', display:'Menu / Shift+F10', menu:'⇧F10', action:'open-canvas-menu', combos:[{key:'ContextMenu'}, {key:'F10', shift:true}]}),
  studioShortcut({id:'canvas-select-all', label:'Select all nodes', scope:'canvas', display:'Ctrl/Cmd+A', menu:'⌘A', action:'select-all-nodes', combos:[{key:'a', ctrlOrMeta:true}]}),
  studioShortcut({id:'canvas-group', label:'Group selected nodes', scope:'canvas', display:'Ctrl/Cmd+G', menu:'⌘G', action:'group-selection', combos:[{key:'g', ctrlOrMeta:true}]}),
  studioShortcut({id:'canvas-add-node', label:'Add node from library', scope:'canvas', display:'Ctrl/Cmd+L', menu:'⌘L', action:'add-node-library', combos:[{key:'l', ctrlOrMeta:true}]}),
  studioShortcut({id:'canvas-fit-graph', label:'Fit graph to view', scope:'canvas', display:'Ctrl/Cmd+0', menu:'⌘0', action:'fit-graph', combos:[{key:'0', ctrlOrMeta:true}]}),
  studioShortcut({id:'canvas-zoom-100', label:'Zoom to 100%', scope:'canvas', display:'Ctrl/Cmd+1', menu:'⌘1', action:'zoom-100', combos:[{key:'1', ctrlOrMeta:true}]}),
  studioShortcut({id:'canvas-auto-layout', label:'Auto-layout', scope:'canvas', display:'Ctrl/Cmd+Shift+L', menu:'⌘⇧L', action:'auto-layout', combos:[{key:'l', ctrlOrMeta:true, shift:true}]}),
  studioShortcut({id:'canvas-undo', label:'Undo', scope:'canvas', display:'Ctrl/Cmd+Z', menu:'⌘Z', action:'undo', combos:[{key:'z', ctrlOrMeta:true}]}),
  studioShortcut({id:'canvas-redo', label:'Redo', scope:'canvas', display:'Ctrl/Cmd+Shift+Z / Ctrl/Cmd+Y', menu:'⌘⇧Z', action:'redo', combos:[{key:'z', ctrlOrMeta:true, shift:true}, {key:'y', ctrlOrMeta:true}]}),
  studioShortcut({id:'canvas-fit-selection', label:'Fit selection or all', scope:'canvas', display:'F', menu:'F', action:'fit-selection-or-all', combos:[{key:'f'}]}),
  studioShortcut({id:'canvas-move-selection', label:'Move selected nodes', scope:'canvas', display:'Arrows / Shift+Arrows', menu:'← ↑ → ↓', action:'move-selection', combos:[
    {key:'ArrowLeft', allowShift:true}, {key:'ArrowRight', allowShift:true}, {key:'ArrowUp', allowShift:true}, {key:'ArrowDown', allowShift:true},
  ]}),
  studioShortcut({id:'canvas-cut-wire', label:'Cut selected wire', scope:'canvas', display:'Delete / Backspace', menu:'Del', action:'cut-wire', combos:[{key:'Delete', allowShift:true}, {key:'Backspace', allowShift:true}]}),
]);
if (typeof window !== 'undefined') window.STUDIO_SHORTCUT_BINDINGS = STUDIO_SHORTCUT_BINDINGS;
const studioShortcutMatchesCombo = (combo, e) => {
  if (combo.anyModifiers) return String(e.key).toLowerCase() === String(combo.key).toLowerCase();
  if (!!combo.alt !== !!e.altKey) return false;
  if (!combo.allowShift && !!combo.shift !== !!e.shiftKey) return false;
  if (combo.ctrlOrMeta) {
    if (!(e.ctrlKey || e.metaKey)) return false;
  } else if (e.ctrlKey || e.metaKey) return false;
  return String(e.key).toLowerCase() === String(combo.key).toLowerCase();
};
const studioShortcutMatches = (binding, e) => binding.combos.some(combo => studioShortcutMatchesCombo(combo, e));
const studioShortcutFromEvent = (e, scope = null) =>
  STUDIO_SHORTCUT_BINDINGS.find(binding => (!scope || binding.scope === scope) && studioShortcutMatches(binding, e)) || null;
const studioShortcutById = id => STUDIO_SHORTCUT_BINDINGS.find(binding => binding.id === id) || null;
const studioShortcutMenu = id => studioShortcutById(id)?.menu || '';
const studioShortcutScopeLabel = scope => String(scope || '').replace(/^\w/, c => c.toUpperCase());
// An ordinary canvas edit (place, copy, delete) re-reads the canvas in place. Reloading the whole
// Studio page re-ran its boot, which on a large graph looked like the app breaking after every edit.
// Where a library card goes when it has no drop point: start at the visible
// canvas centre when the canvas reports one, then search lattice slots outward.
const studioFreeSlot = (nodes, originOrSize = null, size = {w:210, h:230}, gap = 40, columns = 6) => {
  const hasOrigin = originOrSize && Number.isFinite(originOrSize.x) && Number.isFinite(originOrSize.y);
  if (originOrSize && !hasOrigin && Number.isFinite(originOrSize.w) && Number.isFinite(originOrSize.h)) size = originOrSize;
  const rects = (nodes || []).filter(n => Number.isFinite(n.x) && Number.isFinite(n.y))
    .map(n => ({x:n.x, y:n.y, w:Number.isFinite(n.w) ? n.w : size.w, h:Math.max(Number.isFinite(n.h) ? n.h : 0, size.h)}));
  const x0 = hasOrigin ? originOrSize.x - size.w / 2 : rects.length ? Math.min(...rects.map(r => r.x)) : 60;
  const y0 = hasOrigin ? originOrSize.y - size.h / 2 : rects.length ? Math.min(...rects.map(r => r.y)) : 92;
  const meets = (x, y) => rects.some(r => x < r.x + r.w + gap && r.x < x + size.w + gap && y < r.y + r.h + gap && r.y < y + size.h + gap);
  if (hasOrigin) {
    const stepX = size.w + gap, stepY = size.h + gap;
    for (let radius = 0; radius < 64; radius += 1) {
      for (let dy = -radius; dy <= radius; dy += 1) for (let dx = -radius; dx <= radius; dx += 1) {
        if (Math.max(Math.abs(dx), Math.abs(dy)) !== radius) continue;
        const x = x0 + dx * stepX, y = y0 + dy * stepY;
        if (!meets(x, y)) return {x, y};
      }
    }
  }
  for (let i = 0; i < 4096; i += 1) {
    const x = x0 + (i % columns) * (size.w + gap), y = y0 + Math.floor(i / columns) * (size.h + gap);
    if (!meets(x, y)) return {x, y};
  }
  return {x:x0, y:(rects.length ? Math.max(...rects.map(r => r.y + r.h)) + gap : y0)};
};

const studioRefreshCanvasInPlace = async (options = {}) => {
  const applyLiveGraph = options.applyLiveGraph !== false;
  const authority = window.ARCHHUB_STUDIO_AUTHORITY;
  let refreshed = null;
  if (typeof authority?.load === 'function') refreshed = await authority.load();
  else {
    const workshop = window.ARCHHUB_EXISTING_WORKSHOP;
    if (typeof workshop?.refreshTopologyCanvas === 'function') refreshed = await workshop.refreshTopologyCanvas();
    else if (typeof window.ARCHHUB_GET_CANVAS === 'function') refreshed = await window.ARCHHUB_GET_CANVAS();
  }
  const graph = authority?.getSnapshot?.()?.graph ||
    window.ARCHHUB_EXISTING_WORKSHOP?.getSnapshot?.()?.topology?.graph ||
    window.ARCHHUB_EXISTING_WORKSHOP?.getSnapshot?.()?.graph;
  if (applyLiveGraph && graph && window.ARCHHUB_LIVE) {
    LM_GRAPH = graph;
    window.ARCHHUB_LIVE.graph = graph;
  }
  return refreshed;
};
if (typeof window !== 'undefined') window.__archhubRefreshCanvasInPlace = studioRefreshCanvasInPlace;
const StudioLM = () => {
  const themeEpoch = React.useSyncExternalStore(window.ArchHubTheme.subscribe, window.ArchHubTheme.getEpoch);
  useCatalogueVersion();
  React.useEffect(() => {
    const read = () => { if (!window.ARCHHUB_HOSTS_READ) loadCatalogue('ARCHHUB_LOAD_HOSTS', LM_HOSTS); };
    read();
    // Saved skills share one list, first read by Skills or Search.
    const timer = setInterval(() => { if (window.ARCHHUB_HOSTS_READ) clearInterval(timer); else read(); }, 10000);
    return () => clearInterval(timer);
  }, []);
  // Founder 2026-10-13: ArchHub opens on the Home page, never inside a graph. The current graph stays
  // in the tab strip so one click reopens it.
  // A deep link (ARCHHUB_BOOT.open_graph) is the only way to start inside a graph.
  const [openId, setOpenId] = React.useState(window.ARCHHUB_BOOT?.open_graph || null);
  React.useEffect(() => {
    if (!window.ARCHHUB_BOOT?.open_graph && document.querySelector('[data-home-page]')) {
      window.dispatchEvent(new CustomEvent('archhub-home-ready'));
    }
  }, []);
  const [openTabs, setOpenTabs] = React.useState(() => [window.ARCHHUB_LIVE?.currentGraph || LM_SESSIONS[0]?.id].filter(Boolean));
  const [, refreshLiveProjection] = React.useState(0);
  const [sessionOpenError, setSessionOpenError] = React.useState('');
  const [model, setModel] = React.useState(pendingModelAnswer);
  const [homeNative, setHomeNative] = React.useState(null);
  const [pickerOpen, setPickerOpen] = React.useState(false);
  const [commandOpen, setCommandOpen] = React.useState(false);
  // The server's answer to "can a Send reach a model": ready, no_model or no_key
  // (model_router.composer_readiness). Chat and the boot Brain line show it.
  const [readiness, setReadiness] = React.useState(null);
  const modelReadRetryTimer = React.useRef(null);
  const modelReadRetryAttempt = React.useRef(0);
  const modelReadRetryRead = React.useRef(null);
  const clearModelReadRetry = React.useCallback(() => {
    if (modelReadRetryTimer.current != null) window.clearTimeout(modelReadRetryTimer.current);
    modelReadRetryTimer.current = null;
  }, []);
  const scheduleModelReadRetry = React.useCallback(() => {
    clearModelReadRetry();
    const configured = Array.isArray(window.__ARCHHUB_MODEL_RETRY_DELAYS_MS)
      ? window.__ARCHHUB_MODEL_RETRY_DELAYS_MS.map(n => Number(n)).filter(n => n >= 0)
      : DEFAULT_MODEL_READ_RETRY_DELAYS_MS;
    const index = modelReadRetryAttempt.current;
    const delay = index < configured.length ? configured[index] : 30000;
    modelReadRetryAttempt.current = index + 1;
    modelReadRetryTimer.current = window.setTimeout(() => {
      modelReadRetryTimer.current = null;
      if (document.hidden) { scheduleModelReadRetry(); return; }
      if (typeof modelReadRetryRead.current === 'function') modelReadRetryRead.current({automatic:true});
    }, delay);
  }, [clearModelReadRetry]);
  const readInitialModel = React.useCallback((options = {}) => {
    clearModelReadRetry();
    if (!options.automatic) modelReadRetryAttempt.current = 0;
    const controller = new AbortController();
    let timedOut = false;
    const timeoutMs = Number(window.__ARCHHUB_MODEL_READ_TIMEOUT_MS) > 0 ? Number(window.__ARCHHUB_MODEL_READ_TIMEOUT_MS) : 15000;
    let timeoutId = null;
    const timeout = new Promise((_, reject) => { timeoutId = setTimeout(() => {
      timedOut = true;
      controller.abort();
      reject(new Error('Model selection timed out'));
    }, timeoutMs); });
    const session = window.__archhubSession || {};
    // Boot diagnostics (PM 2026-10-13: two failing boots left no trace): every model read
    // attempt is recorded with its outcome and duration, in the console and in
    // window.ARCHHUB_MODEL_READ_LOG for the rig. No tokens or bodies are logged.
    const attempt = modelReadRetryAttempt.current + 1;
    const startedAt = Date.now();
    const noteRead = (outcome, detail) => {
      const entry = {attempt, outcome, ms:Date.now() - startedAt, detail:detail ? String(detail).slice(0, 120) : ''};
      try {
        (window.ARCHHUB_MODEL_READ_LOG = window.ARCHHUB_MODEL_READ_LOG || []).push(entry);
        if (window.ARCHHUB_MODEL_READ_LOG.length > 50) window.ARCHHUB_MODEL_READ_LOG.shift();
        console.info('[models] read attempt ' + attempt + ': ' + outcome + ' in ' + entry.ms + 'ms' + (entry.detail ? ' (' + entry.detail + ')' : ''));
      } catch (e) {}
    };
    setReadiness(null);
    setModel(current => modelRoute(current) && !current.unknown ? current : pendingModelAnswer());
    const request = fetch('/api/universal/models', {signal:controller.signal,
      headers:{'X-ArchHub-Session':session.token || '', 'X-ArchHub-CSRF':session.csrf || ''}});
    Promise.race([request, timeout])
      .then(response => { if (!response.ok) throw new Error('Model selection unavailable'); return response.json(); })
      .then(result => {
        if (!result || result.ok === false) throw new Error('Model selection unavailable');
        const saved = typeof result.selected_route === 'string' ? result.selected_route.trim() : '';
        // No saved pick: the server offers the one free route it enforces free at
        // dispatch (openrouter/free) and names its source; with none the Studio keeps
        // asking him to choose one.
        const fallback = !saved && typeof result.default_route === 'string' ? result.default_route.trim() : '';
        const source = typeof result.default_source === 'string' ? result.default_source.trim() : '';
        const route = saved || fallback;
        noteRead('ok', route ? 'selected model route' : 'no route');
        clearModelReadRetry();
        modelReadRetryAttempt.current = 0;
        if (!controller.signal.aborted && result.readiness && typeof result.readiness === 'object') {
          window.ARCHHUB_MODEL_READINESS = result.readiness;
          setReadiness(result.readiness);
        }
        if (!route || controller.signal.aborted) {
          if (!controller.signal.aborted) {
            setModel(current => modelRoute(current) && !current.unknown ? current : noModelPicked());
          }
          return;
        }
        const selected = (result.groups || []).flatMap(group => group.items || [])
          .find(item => (item.routed || item.route) === route);
        const serverDefault = defaultModelRowFromPayload(result, route);
        setModel(current => modelRoute(current) && !current.unknown && !current.pending ? current :
          selected || (serverDefault && fallback ? {...serverDefault, defaultRouteModel:true} : serverDefault) ||
          defaultModelRow(route, source, fallback));
      }).catch(error => {
        noteRead(timedOut ? 'timeout' : controller.signal.aborted ? 'aborted' : 'refused', error && error.message);
        if (!controller.signal.aborted || timedOut) {
          const unknown = modelCatalogueUnknown();
          window.ARCHHUB_MODEL_READINESS = unknown;
          setReadiness(unknown);
          setModel(current => modelRoute(current) ? current : unknownModelAnswer());
          scheduleModelReadRetry();
        }
      }).finally(() => clearTimeout(timeoutId));
    return () => { clearTimeout(timeoutId); controller.abort(); };
  }, [clearModelReadRetry, scheduleModelReadRetry]);
  React.useEffect(() => { modelReadRetryRead.current = readInitialModel; return () => {
    if (modelReadRetryRead.current === readInitialModel) modelReadRetryRead.current = null;
  }; }, [readInitialModel]);
  React.useEffect(() => () => clearModelReadRetry(), [clearModelReadRetry]);
  React.useEffect(() => readInitialModel(), [readInitialModel]);
  const [settingsOpen, setSettingsOpen] = React.useState(false);
  const [settingsTab, setSettingsTab] = React.useState('hub');
  const [account, setAccount] = React.useState(() => acLoad());
  const [booting, setBooting] = React.useState(() => window.ARCHHUB_STUDIO_AUTHORITY?.getSnapshot?.()?.canvas?.projection !== 'home');
  const [signUpOpen, setSignUpOpen] = React.useState(false);
  // Readiness is read again whenever what it depends on may have changed: a new
  // pick, or a sign-in (the account dialogs closing, or the Chat state's own
  // sign-in). A stale NO KEY never stays up (verifier, 2026-09-28).
  const readReadiness = React.useCallback(() => {
    const held = window.__archhubSession || {};
    return fetch('/api/universal/models', {headers:{'X-ArchHub-Session':held.token || '', 'X-ArchHub-CSRF':held.csrf || ''}})
      .then(response => response.ok ? response.json() : null)
      .then(result => {
        if (result && result.readiness && typeof result.readiness === 'object') {
          window.ARCHHUB_MODEL_READINESS = result.readiness;
          setReadiness(result.readiness);
        }
      }).catch(() => {});
  }, []);
  const pickedRoute = modelRoute(model);
  React.useEffect(() => {
    if (typeof window !== 'undefined') window.ARCHHUB_PICKED_MODEL = model;
  }, [model]);
  React.useEffect(() => {
    // A route the held answer already describes is not read twice.
    if (readiness && readiness.route === pickedRoute) return;
    if (!readiness && !pickedRoute) return;
    readReadiness();
  }, [pickedRoute]);
  const accountDialogOpen = settingsOpen || signUpOpen;
  const accountDialogWasOpen = React.useRef(accountDialogOpen);
  React.useEffect(() => {
    if (accountDialogWasOpen.current && !accountDialogOpen) readReadiness();
    accountDialogWasOpen.current = accountDialogOpen;
  }, [accountDialogOpen, readReadiness]);
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
      acSave(next); setAccount(next); setSettingsOpen(false); setSettingsTab('hub'); setSignUpOpen(true);
    }).catch(() => {});
  };
  const [docsOpen, setDocsOpen] = React.useState(false);
  const [libraryOpen, setLibraryOpen] = React.useState(false);
  const navGeneration = React.useRef(0);
  // Home opens with no panel; a rail click opens one over Home. A deep link keeps Nodes beside its graph.
  const [panel, setPanel] = React.useState(() => (window.ARCHHUB_BOOT?.open_graph ? 'nodes' : null)); // chats | nodes | skills | search
  const [toolView, setToolView] = React.useState(null);
  const [pendingCanvasReveal, setPendingCanvasReveal] = React.useState(null);
  const requestCanvasReveal = ids => setPendingCanvasReveal({ids:[...new Set((ids || []).filter(Boolean))], at:Date.now()});
  const canvasViewportRef = React.useRef(null);
  const updateCanvasViewport = React.useCallback(view => { canvasViewportRef.current = view; }, []);
  const visibleCanvasCenter = () => {
    const view = canvasViewportRef.current;
    if (!view || !Number.isFinite(view.width) || !Number.isFinite(view.height) ||
        !Number.isFinite(view.zoom) || view.zoom <= 0 || !view.pan) return null;
    return {x:(view.width / 2 - view.pan.x) / view.zoom, y:(view.height / 2 - view.pan.y) / view.zoom};
  };
  const authorityState = useStudioProjection();
  const [focusId, setLocalFocusId] = React.useState(() =>
    studioInspectorFocus(window.ARCHHUB_STUDIO_AUTHORITY?.getSnapshot()));
  const restoringSelection = React.useRef(true);
  // Selection is optimistic while the owner saves it. An empty-selection
  // projection from mount or an earlier clear cannot cancel a newer click.
  const focusIntent = React.useRef(null);
  const focusGeneration = React.useRef(0);
  const setFocusId = (root, roots = null) => {
    const signed = window.ARCHHUB_STUDIO_AUTHORITY, existing = window.ARCHHUB_EXISTING_WORKSHOP;
    restoringSelection.current = false;
    focusGeneration.current += 1;
    const intent = {root:root || null, scope:studioCanvasScope((signed?.getSnapshot() || existing?.getSnapshot()?.topology)?.canvas)};
    focusIntent.current = intent;
    setLocalFocusId(root || null);
    const heldRoots = root ? roots : [];
    if (!signed && !existing?.selectTopology) { focusIntent.current = null; return; }
    const save = signed ? signed.select(root || null, heldRoots) : existing?.selectTopology?.(root || null, heldRoots);
    Promise.resolve(save).then(() => {
      if (focusIntent.current !== intent) return;
      focusIntent.current = null;
      const latest = signed?.getSnapshot() || existing?.getSnapshot()?.topology;
      setLocalFocusId(studioInspectorFocus(latest));
    }).catch(() => {
      if (focusIntent.current !== intent) return;
      focusIntent.current = null;
      // Keep the clicked card inspectable; the owner exposes the save error.
    });
  };
  React.useEffect(() => {
    if (authorityState && !authorityState.pending && !authorityState.error && !authorityState.requires_refresh) {
      const restoring = restoringSelection.current;
      restoringSelection.current = false;
      if (focusIntent.current) {
        if (focusIntent.current.scope === studioCanvasScope(authorityState.canvas)) return;
        focusIntent.current = null;
      }
      if (restoring && Array.isArray(authorityState.canvas?.selection) && authorityState.canvas.selection.length &&
          authorityState.graph?.wires?.some(wire => wire.id === authorityState.selected)) {
        setFocusId(null, []); return;
      }
      setLocalFocusId(studioInspectorFocus(authorityState));
    }
  }, [authorityState?.selected, authorityState?.pending, authorityState?.error, authorityState?.requires_refresh,
    JSON.stringify(authorityState?.canvas?.selection),
    authorityState?.canvas?.selection_hidden, studioCanvasScope(authorityState?.canvas),
    !!authorityState?.graph?.wires?.some(wire => wire.id === authorityState?.selected)]);
  const modelTarget = (authorityState?.graph?.nodes || LM_GRAPH.nodes).find(n =>
    n.id === focusId && n.live && nodeModelRow(n)?.editable === true) || null;
  const targetRoute = modelTarget ? nodeModelRoute(modelTarget) : '';
  const displayedModel = modelTarget ? {name:targetRoute || 'Choose a model', route:targetRoute,
    routed:targetRoute, vendor:modelTarget.title, col:LM.inkSoft, latency:null} : model;
  // User-added nodes appear on top of the demo graph
  const [userNodes, setUserNodes] = React.useState([]);
  const workshopState = useWorkshopProjection();
  const visibleSessions = LM_SESSIONS;
  const openSystemId = systemSessionId(workshopState?.canvas, authorityState?.canvas, authorityState?.graph || LM_GRAPH);
  const session = openId ? (openId === openSystemId ? systemGraphSession(openId) : visibleSessions.find(s => s.id === openId)) : null;
  const applyGraphIndex = React.useCallback((result, fallbackId, options = {}) => {
    const activate = options.activate !== false;
    const rows = Array.isArray(result?.graphs) ? result.graphs : null;
    const current = result?.current_graph || result?.graph?.id || fallbackId || '';
    if (rows) {
      LM_SESSIONS = rows;
    } else if (result?.graph?.id) {
      const known = new Map(LM_SESSIONS.map(row => [row.id, row]));
      known.set(result.graph.id, {...(known.get(result.graph.id) || {}), ...result.graph});
      LM_SESSIONS = [...known.values()];
    } else if (current && !LM_SESSIONS.some(row => row.id === current)) {
      LM_SESSIONS = [...LM_SESSIONS, {
        id:current, title:result?.canvas?.scope?.current_label || 'Graph',
        state:'idle', host:'archhub', when:'saved', file:'Graph composition',
        last:'Open graph', model:'',
      }];
    }
    if (window.ARCHHUB_LIVE) {
      window.ARCHHUB_LIVE.sessions = LM_SESSIONS;
      if (activate) window.ARCHHUB_LIVE.currentGraph = current || window.ARCHHUB_LIVE.currentGraph;
    }
    refreshLiveProjection(value => value + 1);
    return current;
  }, []);
  const switchOpenGraphInPlace = React.useCallback(async (result, fallbackId, options = {}) => {
    // The installed app refused the graph-open/create receipt's canvas as the topology
    // canvas ("current graph interaction authority", rig nav-g1-final 2026-10-10), so the same
    // page re-reads its canvas once: no navigation, no new connection, no re-post.
    const guard = typeof options.guard === 'function' ? options.guard : null;
    const refreshed = await studioRefreshCanvasInPlace({applyLiveGraph: !guard});
    const active = !guard || guard();
    const current = applyGraphIndex(result, fallbackId, {activate:active});
    const known = current ? (Array.isArray(result?.graphs) && result.graphs.find(row => row?.id === current)) ||
      (result?.graph?.id === current ? result.graph : null) : null;
    const graph = window.ARCHHUB_STUDIO_AUTHORITY?.getSnapshot?.()?.graph ||
      window.ARCHHUB_EXISTING_WORKSHOP?.getSnapshot?.()?.topology?.graph ||
      window.ARCHHUB_EXISTING_WORKSHOP?.getSnapshot?.()?.graph;
    if (active && current && known) {
      setOpenTabs(tabs => tabs.includes(current) ? tabs : [...tabs, current]);
      setOpenId(current);
    }
    if (active && graph && window.ARCHHUB_LIVE) {
      LM_GRAPH = graph;
      window.ARCHHUB_LIVE.graph = graph;
    }
    return {current, refreshed, stale:!active};
  }, [applyGraphIndex]);
  const graphCreateBusy = React.useRef(false);
  // A navigation intent is a generation: the latest one (Home, an open, a tool) decides what is shown.
  const beginNavigation = React.useCallback(() => ++navGeneration.current, []);
  const openCreatedGraphInPlace = React.useCallback(async (result, generation = beginNavigation()) => {
    const fallbackId = result?.graph?.id || result?.current_graph;
    if (generation !== navGeneration.current) {
      const current = applyGraphIndex(result, fallbackId, {activate:false}) || fallbackId;
      setSessionOpenError('');
      return current;
    }
    const opened = await switchOpenGraphInPlace(result, fallbackId, {guard:() => generation === navGeneration.current});
    const current = opened.current || result?.graph?.id || result?.current_graph;
    // The graph was created either way (never re-posted); it is only shown if no later choice was made.
    if (current && !opened.stale) {
      setOpenTabs(tabs => tabs.includes(current) ? tabs : [...tabs, current]);
      setOpenId(current);
    }
    setSessionOpenError('');
    return current;
  }, [switchOpenGraphInPlace, beginNavigation, applyGraphIndex]);
  const createSessionGraphInPlace = React.useCallback(async () => {
    if (graphCreateBusy.current) return;
    if (!window.ARCHHUB_GRAPH_CREATE) {
      setSessionOpenError('Graph creation is unavailable in this view.');
      return;
    }
    graphCreateBusy.current = true;
    setToolView(null);
    setWorkspaceSelection(canvasWorkspaceView(''));
    setSessionOpenError('');
    const generation = beginNavigation();
    try {
      await openCreatedGraphInPlace(await window.ARCHHUB_GRAPH_CREATE('New session'), generation);
      graphCreateBusy.current = false;
    } catch (error) {
      if (generation !== navGeneration.current) return;
      // A lost receipt may follow a successful create: never post it again from here.
      // The guard stays held until the graph list is refreshed (the Refresh graphs control).
      setSessionOpenError((error?.message || 'Graph creation was not confirmed.') +
        ' Refresh the graph list before creating again.');
    }
  }, [openCreatedGraphInPlace, beginNavigation]);
  const viewScope = JSON.stringify([session?.id || '', workshopState?.canvas?.graph_id || '',
    workshopState?.canvas?.root || '',
    (workshopState?.topology?.canvas || workshopState?.canvas)?.authorization?.subject || '',
    (workshopState?.topology?.canvas || workshopState?.canvas)?.authorization?.session || '']);
  const canvasWorkspaceView = scope => ({mode:'canvas', conversationRoot:'', target:'', notice:'', scope, pending:false});
  // Selection is presentation state. Participants and connection status stay owner projections.
  const [workspaceSelection, setWorkspaceSelection] = React.useState(null);
  const projectedAuthorization = (workshopState?.topology?.canvas || workshopState?.canvas)?.authorization;
  const workspaceReady = !!(session && workshopState?.canvas?.graph_id && workshopState?.canvas?.root &&
    projectedAuthorization?.subject && projectedAuthorization?.session && Array.isArray(workshopState.workshops) &&
    (!workshopState.topology?.canvas || (workshopState.topology.canvas.application_root === workshopState.canvas.graph_id &&
      workshopState.topology.canvas.scope?.current === workshopState.canvas.root)));
  const availableWorkshops = workspaceReady ? workshopState.workshops : [];
  // Studio sessions open as the graph canvas. Workshop and System are separate Hub/Cockpit surfaces,
  // not Studio header modes.
  const defaultWorkspaceView = canvasWorkspaceView(viewScope);
  const resolveWorkspaceView = previous => {
    const unavailableWorkshopRoot = 'studio:workshop-unavailable';
    if (!workspaceReady && previous?.mode === 'chat' && previous?.conversationRoot === unavailableWorkshopRoot) {
      return {...previous, target:'', pending:false, notice:previous.notice || workshopUnavailableText(workshopState?.canvas?.unavailable)};
    }
    if (!workspaceReady) return {mode:previous?.mode || 'chat', conversationRoot:'', target:'', pending:true,
      notice:workshopState?.error || workshopState?.topology?.error || 'Loading your workspace…'};
    if (previous?.scope !== viewScope) return {
      ...defaultWorkspaceView,
      mode:previous?.mode === 'system' && String(session?.id || '').startsWith('system:') ? 'system' : defaultWorkspaceView.mode,
    };
    if (previous?.mode === 'chat' && previous?.conversationRoot === unavailableWorkshopRoot) {
      return {...previous, target:'', pending:false, notice:previous.notice || workshopUnavailableText(workshopState?.canvas?.unavailable)};
    }
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
  const viewScopeForSession = id => JSON.stringify([id || '', workshopState?.canvas?.graph_id || '',
    workshopState?.canvas?.root || '',
    (workshopState?.topology?.canvas || workshopState?.canvas)?.authorization?.subject || '',
    (workshopState?.topology?.canvas || workshopState?.canvas)?.authorization?.session || '']);
  const openSessionView = async (id, view) => {
    setLocalFocusId(null);
    if (id && (window.ARCHHUB_GRAPH_OPEN || authorityState?.canvas?.projection === 'home')) {
      const opened = await openSession(id);
      if (!opened?.ok) return;
    } else if (id) {
      if (!openTabs.includes(id)) setOpenTabs(t => [...t, id]);
      setOpenId(id);
    }
    setWorkspaceSelection({...view, notice:'', scope:viewScopeForSession(id), pending:false});
  };
  const openTool = (tool, options = {}) => {
    beginNavigation();
    requestToolHubRefresh();
    if (tool === 'workshop') {
      const workshopRows = Array.isArray(workshopState?.workshops) ? workshopState.workshops : [];
      const room = workshopRows.find(row => row.root === options.root) ||
        workshopRows.find(row => row.is_general === true) || workshopRows[0];
      const liveSessions = Array.isArray(window.ARCHHUB_LIVE?.sessions) ? window.ARCHHUB_LIVE.sessions : [];
      const graphId = openId || window.ARCHHUB_LIVE?.currentGraph || visibleSessions[0]?.id ||
        liveSessions[0]?.id || LM_SESSIONS[0]?.id || workshopState?.canvas?.graph_id || '';
      if (options.window) {
        setOpenId(null);
        setWorkspaceSelection(canvasWorkspaceView(viewScope));
        setToolView({id:'workshop', root:room?.root || WORKSHOP_UNAVAILABLE_ROOT, focus:options.focus || null});
        return;
      }
      if (graphId) {
        const authorization = (workshopState?.topology?.canvas || workshopState?.canvas)?.authorization || {};
        const conversationRoot = room?.root || WORKSHOP_UNAVAILABLE_ROOT;
        setToolView(null);
        if (graphId) setOpenTabs(tabs => tabs.includes(graphId) ? tabs : [...tabs, graphId]);
        setWorkspaceSelection({mode:'chat', conversationRoot, target:'', notice:room ? '' : workshopUnavailableText(workshopState?.canvas?.unavailable), pending:false,
          scope:JSON.stringify([graphId, workshopState?.canvas?.graph_id || '', workshopState?.canvas?.root || '',
            authorization.subject || '', authorization.session || ''])});
        setWorkshopSelection({root:conversationRoot, agent:null, task:options.focus || null, tab:options.tab || 'tasks'});
        if (graphId) setOpenId(graphId);
        return;
      }
      setOpenId(null);
      setToolView({id:'workshop', root:room?.root || WORKSHOP_UNAVAILABLE_ROOT, focus:options.focus || null});
      return;
    }
    const toolRow = toolRowsFromOwners({workshopState, account, personal:readPersonalThemeSnapshot(), hub:window.ARCHHUB_TOOL_HUB})
      .find(row => row.id === tool);
    // Settings opens over the current view: the workspace (a Workshop chat, a selection) is left as it is.
    if (TOOL_SETTINGS_TAB[tool] && toolRow?.state !== 'off') {
      openSettings(true, TOOL_SETTINGS_TAB[tool]);
      return;
    }
    // Founder 2026-10-12 "did you remove the composer?!": an off tool never replaces the screen (that
    // closed the session and its right-panel composer). Its state and turn-on are its Settings > Hub card.
    if (toolRow?.state === 'off' && tool !== 'workshop') {
      openSettings(true, 'hub');
      return;
    }
    setWorkspaceSelection(canvasWorkspaceView(viewScope));
    if (toolRow?.state === 'off') {
      setOpenId(null);
      setToolView({id:tool, tab:firstToolTab(tool)});
      return;
    }
    const firstSession = openId || window.ARCHHUB_LIVE?.currentGraph || visibleSessions[0]?.id || null;
    if (tool === 'studio') {
      setToolView(null);
      if (firstSession) openSessionView(firstSession, {mode:'canvas', conversationRoot:'', target:''});
      else { setOpenId(null); setToolView({id:'studio', tab:'canvas'}); }
      return;
    }
    // No graph exists at all yet: the Workshop tool page still opens (never a silent no-op on Home).
    setOpenId(null);
    setToolView({id:tool, tab:options.tab || firstToolTab(tool), focus:options.focus || ''});
  };
  const openToolGraph = async tool => {
    requestToolHubRefresh();
    if (tool === 'system') {
      const id = systemSessionId(workshopState?.canvas, authorityState?.canvas, authorityState?.graph || LM_GRAPH);
      if (!id) {
        setSessionOpenError('System graph is not admitted in this workspace.');
        return {ok:false, error:'System graph is not admitted in this workspace.'};
      }
      return await openSession(id);
    }
    setWorkspaceSelection(canvasWorkspaceView(viewScope));
    setOpenId(null);
    setToolView({id:tool, tab:firstToolTab(tool)});
    return {ok:true};
  };
  // A Conversations row that first walked to the Workshop canvas (WorkshopConversationMenu) names
  // its room here: the menu itself unmounts when the scope changes, and a selection made under the
  // old scope is reset. The room opens on the first render that lists it at the new scope.
  const [reachingRoom, setReachingRoom] = React.useState('');
  const [reachingApproval, setReachingApproval] = React.useState(null);
  React.useEffect(() => {
    const listen = event => {
      setReachingRoom(typeof event.detail === 'string' ? event.detail : event.detail?.root || '');
      setReachingApproval(typeof event.detail === 'object' ? event.detail?.work || null : null);
    };
    window.addEventListener('archhub:reach-conversation', listen);
    return () => window.removeEventListener('archhub:reach-conversation', listen);
  }, []);
  React.useEffect(() => {
    if (!reachingRoom || !workspaceReady || !availableWorkshops.some(row => row.root === reachingRoom)) return;
    setReachingRoom('');
    setWorkshopSelection({root:reachingRoom, agent:null, task:reachingApproval, review:!!reachingApproval});
    setWorkspaceSelection({mode:'chat', conversationRoot:reachingRoom, target:'', notice:'', pending:false, scope:viewScope});
  }, [reachingRoom, reachingApproval, workspaceReady, availableWorkshops, viewScope]);
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
  const setWsSel = next => setWorkshopSelection({root:workspaceView.conversationRoot, agent:next.agent ?? null,
    task:next.task ?? null, tab:next.tab ?? null, review:next.review === true});

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
    const generation = ++navGeneration.current;
    const selectionGeneration = focusGeneration.current;
    setLocalFocusId(null);
    const systemId = systemSessionId(workshopState?.canvas, authorityState?.canvas, authorityState?.graph || LM_GRAPH);
    const isSystem = id && id === systemId;
    // The System view is a mode of the application's root graph (as the old System tab was):
    // open the admitted root graph, then switch to the system view. The application root itself
    // is not an admitted graph, so it is never posted to graph-open.
    const rootCanvas = authorityState?.canvas;
    const projectedRoot = rootCanvas?.canvas_root || rootCanvas?.scope?.trail?.[0]?.root;
    const rootGraphId = LM_SESSIONS.find(row => row.id === projectedRoot)?.id ||
      (LM_SESSIONS.find(row => row && row.id && !String(row.id).startsWith('system:')) || {}).id || '';
    const graphId = isSystem ? rootGraphId : id;
    const viewFor = targetId => isSystem ? {...canvasWorkspaceView(viewScopeForSession(targetId || id)), mode:'system'} :
      canvasWorkspaceView(viewScopeForSession(targetId || id));
    setToolView(null);
    if (rootCanvas?.projection === 'home' && window.ARCHHUB_STUDIO_AUTHORITY?.load) {
      try {
        await studioRefreshCanvasInPlace();
        if (generation !== navGeneration.current) return {ok:false, stale:true};
      } catch (error) {
        if (generation === navGeneration.current) setSessionOpenError(error?.message || 'Graph opening was refused.');
        return {ok:false};
      }
    }
    setWorkspaceSelection(viewFor(id));
    setSessionOpenError('');
    if (graphId && window.ARCHHUB_GRAPH_OPEN) {
      try {
        const result = await window.ARCHHUB_GRAPH_OPEN(graphId);
        if (generation !== navGeneration.current) {
          applyGraphIndex(result, graphId, {activate:false});
          return {ok:false, stale:true};
        }
        const opened = await switchOpenGraphInPlace(result, graphId, {guard:() => generation === navGeneration.current});
        // Home (or another open) was chosen while this graph was opening: it wins.
        if (opened.stale) return {ok:false, stale:true};
        // Reopening does not count as explicitly selecting the retained relation.
        const restored = window.ARCHHUB_STUDIO_AUTHORITY?.getSnapshot?.() ||
          window.ARCHHUB_EXISTING_WORKSHOP?.getSnapshot?.()?.topology;
        if (selectionGeneration === focusGeneration.current &&
            restored?.graph?.wires?.some(wire => wire.id === restored.selected)) setFocusId(null, []);
        const current = isSystem ? id : (opened.current || graphId);
        if (current && !isSystem && !openTabs.includes(current)) setOpenTabs(t => t.includes(current) ? t : [...t, current]);
        setWorkspaceSelection(viewFor(current || id));
        setOpenId(current || id);
        return {ok:true, current:current || id};
      } catch (error) {
        if (generation !== navGeneration.current) return {ok:false, stale:true};
        const message = error?.message || 'Graph opening was refused.';
        setSessionOpenError(message);
        setOpenId(null);
        return {ok:false, error:message};
      }
      return {ok:false};
    }
    setWorkspaceSelection(viewFor(id));
    if (id && !openTabs.includes(id)) setOpenTabs(t => [...t, id]);
    setOpenId(id);
    return {ok:true, current:id};
  };
  const closeTab = (id) => {
    setOpenTabs(t => {
      const next = t.filter(x => x !== id);
      if (openId === id) setOpenId(null);
      return next;
    });
  };

  // Insert a node from the library at canvas coords (x,y). called from drop or dbl-click
  const addNodeFromLibrary = (libItem, dropX, dropY) => {
    // A drop places the card where it was dropped; a double-click has no point, so it takes a free slot.
    const dropped = Number.isFinite(dropX) && Number.isFinite(dropY);
    const graphNodesBefore = authorityState?.graph?.nodes || [];
    const beforeIds = new Set(graphNodesBefore.map(node => node.id).filter(Boolean));
    const {x, y} = dropped ? {x:dropX, y:dropY} : studioFreeSlot(graphNodesBefore, visibleCanvasCenter());
    const revealCreated = async result => {
      const refreshed = await studioRefreshCanvasInPlace();
      const newId = studioCreatedNodeId(result, refreshed, beforeIds);
      if (newId) { setFocusId(newId); requestCanvasReveal([newId]); }
      return refreshed;
    };
    if (libItem.children?.length && !libItem.noEngine && window.ARCHHUB_NODE_CREATE) {
      return window.ARCHHUB_NODE_CREATE({template:libItem.id})
        .then(revealCreated).catch(e => {window.alert('not created: '+(e?.message || e));return false;});
    }
    if (window.ARCHHUB_STUDIO_AUTHORITY) {
      // A signed canvas places published definitions only. A card without one
      // is refused by name: its item id is not a definition id.
      if (!libItem.definition) {
        window.alert(libItem.title + ' is not a published definition on this canvas, so it cannot be placed here.');
        return Promise.resolve(false);
      }
      return window.ARCHHUB_NODE_CREATE({definition: libItem.definition,
        definition_revision: libItem.revision_root, x, y})
        .then(r => { if (r && r.ok === false) { window.alert('not created: ' + (r.error || '')); return false; } return revealCreated(r); })
        .catch(e => { window.alert('not created: ' + (e && e.message || e)); return false; });
    }
    if (libItem.noEngine || !libItem.engine || !window.ARCHHUB_NODE_CREATE) {
      // A card with no engine used to land in this component's memory only:
      // invisible to Run, never written to the graph, gone on the next reload.
      // Say so instead of pretending it was placed.
      window.alert(libItem.title + ' has no engine in this build, so it cannot run yet. '
        + (libItem.reason ? '(' + libItem.reason + ') ' : '')
        + 'It would vanish on reload, so it is not placed.');
      return;
    }
    // A node with an engine is created ON THE GRAPH through the same governed
    // write the seed uses, then the canvas reloads from the graph. The item id
    // names the card, so a shared engine gets that card's own defaults.
    return window.ARCHHUB_NODE_CREATE({ item: libItem.id, title: libItem.title, engine: libItem.engine, x, y, params: libItem.params || {} })
      .then(r => { if (r && r.ok !== false) return revealCreated(r); window.alert('not created: ' + ((r && r.error) || '')); return false; })
      .catch(e => window.alert('not created: ' + (e && e.message || e)));
  };

  // Docs and Settings are mutually exclusive — they share a z-index, so opening one closes the other.
  // Settings lands on its designed controls. The System graph is an explicit destination.
  const openSettings = (v, tab) => { if (v) {beginNavigation(); setDocsOpen(false);} setSettingsTab(v && tab ? tab : 'theme'); setSettingsOpen(v); };
  const openDocs = (v) => {
    if (v) {
      beginNavigation();
      openSettings(false);
      setPanel(null);
      setToolView(null);
      setOpenTabs(t => t.filter(id => !String(id || '').startsWith('system:')));
      setOpenId(null);
      setLibraryOpen(false);
      setWorkspaceSelection(canvasWorkspaceView(viewScope));
    }
    setDocsOpen(v);
  };
  const goHome = () => {
    navGeneration.current += 1;
    setWorkspaceSelection(canvasWorkspaceView(viewScope));
    setToolView(null);
    setPanel(null);
    setSettingsOpen(false);
    setOpenTabs(t => t.filter(id => !String(id || '').startsWith('system:')));
    setOpenId(null);
    setDocsOpen(false);
    setLibraryOpen(false);
  };

  // The Settings shortcut sheet and this handler read the same binding table.
  React.useEffect(() => {
    const onKey = (e) => {
      // The Studio is the whole window: Back and Forward keys never leave it.
      if (studioLeavesPage(e)) { e.preventDefault(); return; }
      const inField = studioTextEntryTarget(e.target);
      if (!inField && !e.ctrlKey && !e.metaKey && !e.altKey && e.key === '/') {
        e.preventDefault();
        setCommandOpen(true);
        return;
      }
      const shortcut = studioShortcutFromEvent(e, 'global');
      if (!shortcut) return;
      e.preventDefault();
      if (shortcut.action === 'close-overlays') {
        setDocsOpen(false); openSettings(false); setLibraryOpen(false); setCommandOpen(false); return;
      }
      if (shortcut.action === 'open-command-bar') { setCommandOpen(true); return; }
      if (shortcut.action === 'open-documentation') {
        setDocsOpen(o => { if (!o) openSettings(false); return !o; }); return;
      }
      if (shortcut.action === 'toggle-settings') {
        setSettingsTab('system'); setSettingsOpen(o => { if (!o) setDocsOpen(false); return !o; }); return;
      }
    };
    // The mouse's Back and Forward buttons (3 and 4) are the same request.
    const onButton = (e) => { if (e.button === 3 || e.button === 4) e.preventDefault(); };
    window.addEventListener('keydown', onKey);
    for (const type of ['mousedown', 'mouseup', 'auxclick']) window.addEventListener(type, onButton);
    return () => {
      window.removeEventListener('keydown', onKey);
      for (const type of ['mousedown', 'mouseup', 'auxclick']) window.removeEventListener(type, onButton);
    };
  }, []);

  const systemView = String(session?.id || '').startsWith('system:');
  const frameRail = systemView ? 'Settings' : settingsOpen ? (settingsTab === 'account' ? 'Account' : 'Settings') : docsOpen ? 'Docs' : panel === 'chats' ? 'Chats' : ['nodes', 'skills', 'search'].includes(panel) ? 'Library' :
    toolView?.id === 'workshop' || (session && workspaceView.mode === 'chat' && workspaceView.conversationRoot) ? 'Workshop' :
    session ? 'Canvas' : 'Home';
  return (
    <Frame workshopWindow={(!!session && workspaceView.mode === 'chat' && !!workspaceView.conversationRoot) || (!session && toolView?.id === 'workshop')}
      rail={frameRail} onHome={goHome} onPanel={value => { beginNavigation(); setSettingsOpen(false); setDocsOpen(false); setLibraryOpen(false); setToolView(null); setPanel(value); if(value === 'nodes') { setWorkspaceSelection(canvasWorkspaceView(viewScope)); if(!session && visibleSessions[0]?.id) openSession(visibleSessions[0].id); } }}
      onSettings={() => openSettings(true)} onAccount={() => openSettings(true,'account')} account={account}
      onChats={() => { goHome(); setPanel('chats'); }}
      onDocs={() => openDocs(true)}
      onCockpit={() => openTool('cockpit')}
      onWorkshop={() => { setSettingsOpen(false); setDocsOpen(false); setLibraryOpen(false); setPanel(null); openTool('workshop', {window:true}); }}
      onCanvas={() => { setPanel(null); setSettingsOpen(false); setDocsOpen(false); openTool('studio'); }}
      left={systemView ? <SystemSettingsNav selectedId={focusId} onSelect={setFocusId} onOpen={tab=>openSettings(true,tab)}/> : (panel || session && workspaceView.mode==='canvas') && !workshopContext ? <Sidebar
        panel={panel || 'chats'} setPanel={setPanel}
        openId={openId} onOpen={openSession}
        onHome={goHome} onSettings={() => openSettings(true)} onAccount={() => openSettings(true, 'account')} onDocs={() => openDocs(true)}
        onOpenTool={openTool}
        addNodeFromLibrary={addNodeFromLibrary} workshopContext={workshopContext} railOnly={!panel || !!workshopContext} account={account}
        wsSel={wsSel} setWsSel={setWsSel} onAddAgent={() => setLibraryOpen(true)}
        onWorkshopTarget={target => updateWorkspaceView({target})}/> : null}
      top={null}
      status={<StatusBar session={session} model={displayedModel} setDocsOpen={openDocs} onOpenWaitingTask={openTool}/>}>
      {session && sessionOpenError && <div role="alert" style={{position:'absolute', top:56, left:'50%', transform:'translateX(-50%)',
        zIndex:40, maxWidth:560, padding:'8px 12px', background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:LM.rad.md,
        color:LM.warn, fontFamily:LM.sans, fontSize:12.5}}>{sessionOpenError}
        {' '}<window.AH_DS.Btn type="button" onClick={() => window.location.reload()}>Refresh graphs</window.AH_DS.Btn></div>}
      {toolView && !session
        ? <ToolMainView view={toolView} account={account} setAccount={setAccount} onSignOut={signOut} onSettings={openSettings}
            onHome={goHome} onChats={() => { goHome(); setPanel('chats'); }} onCockpit={() => openTool('cockpit')} onDocs={() => openDocs(true)} onLibrary={() => setLibraryOpen(true)} updateView={setToolView}/>
        : session
        ? <Workspace libraryMode={panel === 'nodes'}
            session={session} account={account} model={displayedModel} readiness={readiness} onReadinessStale={readReadiness}
            onModelReadRetry={readInitialModel}
            updateCanvasViewport={updateCanvasViewport}
            openTabs={openTabs} sessionRows={visibleSessions} setOpenId={openSession} closeTab={closeTab}
            setPickerOpen={setPickerOpen}
            setLibraryOpen={setLibraryOpen}
            focusId={focusId} setFocusId={setFocusId}
            pendingCanvasReveal={pendingCanvasReveal} requestCanvasReveal={requestCanvasReveal}
            clearPendingCanvasReveal={() => setPendingCanvasReveal(null)}
            userNodes={userNodes} addNodeFromLibrary={addNodeFromLibrary}
            themeEpoch={themeEpoch}
            view={workspaceView} updateView={updateWorkspaceView} wsSel={wsSel} setWsSel={setWsSel}
            onHome={goHome} onChats={() => { goHome(); setPanel('chats'); }} onCockpit={() => openTool('cockpit')} onDocs={() => openDocs(true)}
            onNewSession={createSessionGraphInPlace}
            onSettings={() => openSettings(true, 'system')}
            onAccount={() => openSettings(true, 'account')}/>
        : panel ? <main data-rail-workspace={panel} style={{height:'100%',display:'grid',placeItems:'center'}}>
            <window.AH_DS.EmptyState title={sessionOpenError ? 'Graph could not be read' : panel === 'chats' ? 'Choose a chat' : 'Build your graph'}
              detail={sessionOpenError || (panel === 'chats' ? 'Open a session from Chats to continue its conversation.' : 'Choose a node in the Library, or open a graph to add it to your canvas.')}
              action={sessionOpenError ? <window.AH_DS.Btn onClick={() => window.location.reload()}>Refresh graphs</window.AH_DS.Btn> : panel !== 'chats' ? <window.AH_DS.Btn onClick={() => setLibraryOpen(true)}>Add node</window.AH_DS.Btn> : undefined}/>
          </main> : <Home onOpen={openSession} sessions={visibleSessions} model={model} native={homeNative}
            readiness={readiness} onModelReadRetry={readInitialModel} setPickerOpen={setPickerOpen}
            setLibraryOpen={setLibraryOpen} setPanel={setPanel}
            onOpenTool={openTool} onOpenToolGraph={openToolGraph} workshopState={workshopState} account={account}
            sessionError={sessionOpenError}
            beginNavigation={beginNavigation}
            isNavigationCurrent={generation => generation === navGeneration.current}
            onCreateGraph={async (result, generation) => {
              await openCreatedGraphInPlace(result, generation);
            }}
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
      {pickerOpen && <ModelPicker setModel={m => !session
        ? rememberComposerModel(m).then(picked => { setHomeNative(null); setModel(picked); }) : modelTarget
        ? window.pmPersistValue(modelTarget, 'model', modelRoute(m))
        : window.ARCHHUB_STUDIO_AUTHORITY ? Promise.reject(new Error('Select an AI node on the canvas to set its model.'))
        : rememberComposerModel(m).then(setModel)} onClose={() => setPickerOpen(false)} model={displayedModel}
        onNativeSelect={window.ARCHHUB_EXISTING_WORKSHOP ? (!session ? row => setHomeNative(row) : connectNativeSession) : undefined}/>}
      {settingsOpen && <Settings onHome={goHome} onClose={() => openSettings(false)} account={account} setAccount={setAccount} onSignOut={signOut}
        initialTab={settingsTab} onOpenTool={openTool} onOpenToolGraph={openToolGraph}/>}
      {signUpOpen && <SignUp onDone={(rec) => { setAccount(rec); setSignUpOpen(false); }} onCancel={() => setSignUpOpen(false)} plan={account.plan}/>}
      {booting && <AppBoot account={account} onDone={() => setBooting(false)}/>}
      {/* The design's own full-bleed screens: first-run onboarding, a skill's split view, a connector's diagnostic. */}
      <StudioScreens model={model} onPickModel={() => setPickerOpen(true)}
        onAddSkillToCanvas={skill => addNodeFromLibrary(studioSkillLibraryItem(skill))}/>
      {docsOpen && <Docs onClose={() => setDocsOpen(false)} onHome={goHome}/>}
      {libraryOpen && <NodeLibrary onClose={() => setLibraryOpen(false)} addNodeFromLibrary={addNodeFromLibrary}
        initialQuery={typeof libraryOpen === 'string' ? libraryOpen : ''} onSwitchPanel={value=>{setLibraryOpen(false);setPanel(value);}}/>}
      <CommandBar open={commandOpen} onClose={() => setCommandOpen(false)}
        addNodeFromLibrary={addNodeFromLibrary} onOpenSession={openSession} onChats={() => { goHome(); setPanel('chats'); }}/>
      <style>{`
        @keyframes lmPulse { 0%,100% { opacity:.4 } 50% { opacity:1 } }
        @keyframes lmCaret { 50% { opacity: 0 } }
        @keyframes lmDash  { to { stroke-dashoffset: -16 } }
        @keyframes lmSlideIn { from { transform: translateX(8px); opacity: 0 } to { transform: translateX(0); opacity: 1 } }
        @keyframes lmPop    { from { transform: scale(.92); opacity: 0 } to { transform: scale(1); opacity: 1 } }
        .lm-home-draft::placeholder { color: ${LM.inkSoft}; font-style: normal; opacity: 1 }
      `}</style>
    </Frame>
  );
};

// ──────────────────────── SIDEBAR (icon rail + active panel) ────────────────────────
const Sidebar = ({ panel, setPanel, openId, onOpen, onHome, onSettings, onAccount, onDocs, onOpenTool, addNodeFromLibrary,
  workshopContext, railOnly, wsSel, setWsSel, onAddAgent, onWorkshopTarget, account }) => (
  <aside style={{
    height:'100%',
    display:'grid', gridTemplateRows:railOnly || ['nodes','chats'].includes(panel) ? '1fr' : '36px minmax(0, 1fr)',
    background:LM.bgPanel, borderRight:`1px solid ${LM.line}`,
    overflow:'hidden', minHeight:0,
  }}>
    {!railOnly && !['nodes','chats'].includes(panel) && <div aria-label="Library tabs" style={{
      display:'grid', gridTemplateColumns:'repeat(3, 1fr)', alignItems:'stretch',
      padding:'4px 6px', gap:4, borderBottom:`1px solid ${LM.lineSoft}`,
    }}>
      {[
        ['nodes', 'Nodes'],
        ['skills', 'Skills'],
        ['search', 'Search'],
      ].map(([id, label]) => (
        <window.AH_DS.Btn key={id} type="button" title={label} data-library-tab={id} aria-current={panel === id ? 'true' : undefined}
          onClick={() => setPanel(id)} style={{
            height:28, border:0, borderRadius:LM.rad.sm,
            background:panel === id ? LM.bgHover : 'transparent',
            color:panel === id ? LM.ink : LM.inkSoft,
            fontFamily:LM.sans, fontSize:12, fontWeight:600, cursor:'pointer',
          }}>{label}</window.AH_DS.Btn>
      ))}
    </div>}
    {railOnly ? null : <>
    {panel === 'chats'  && <ChatsPanel openId={openId} onOpen={onOpen} onNew={onHome} onHome={onHome} account={account} onAccount={onAccount || onSettings}/>}
    {panel === 'nodes'  && <NodesPanel addNodeFromLibrary={addNodeFromLibrary} onHome={onHome} account={account} onAccount={onAccount || onSettings} onSwitchPanel={setPanel}/>}
    {panel === 'skills' && <SkillsPanel addNodeFromLibrary={addNodeFromLibrary} onHome={onHome}/>}
    {panel === 'runs' && <RunsPanel onHome={onHome} onOpenTask={item => onOpenTool && onOpenTool('workshop', {focus:item?.id || item?.label || ''})}/>}
    {panel === 'search' && <SearchPanel onHome={onHome}/>}
    {String(panel || '').startsWith('tool:') && <ToolOffPanelFromOwners panel={panel} account={account}/>}
      </>}
  </aside>
);

const PanelHomeButton = ({ onHome }) => (
  <window.AH_DS.Btn onClick={onHome} aria-label="Home" data-home-button style={{
    height:26, padding:'0 9px', border:`1px solid ${LM.line}`,
    background:LM.bg, color:LM.inkSoft, borderRadius:LM.rad.sm,
    fontFamily:LM.sans, fontSize:12, fontWeight:500, cursor:'pointer',
  }}>Home</window.AH_DS.Btn>
);

const ToolOffPanelFromOwners = ({ panel, account }) => {
  const workshopState = useWorkshopProjection();
  const personal = usePersonalTheme();
  const hub = useToolHubProjection();
  const tool = toolRowsFromOwners({workshopState, account, personal, hub}).find(row => row.id === String(panel).slice(5));
  return <ToolOffPanel tool={tool}/>;
};



const ToolGlyph = ({ id }) => {
  const stroke = 'currentColor';
  const common = {width:14, height:14, viewBox:'0 0 24 24', fill:'none', stroke, strokeWidth:1.8, strokeLinecap:'round', strokeLinejoin:'round'};
  const paths = {
    studio:<><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M12 8v8M8 12h8"/></>,
    workshop:<><path d="M5 7h14M5 12h14M5 17h14"/></>,
    brain:<><path d="M12 3l1.8 6.2L20 12l-6.2 2.8L12 21l-1.8-6.2L4 12l6.2-2.8z"/></>,
    baboom:<><circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2.4" fill="currentColor" stroke="none"/></>,
    connectors:<><rect x="4" y="7" width="5" height="5" rx="1"/><rect x="15" y="12" width="5" height="5" rx="1"/><path d="M9 10h3c1.5 0 1.5 4 3 4"/></>,
    cloud:<><path d="M17.5 18H8a5 5 0 1 1 .9-9.9A6 6 0 0 1 20 10.5 3.8 3.8 0 0 1 17.5 18z"/></>,
  };
  return <svg {...common}>{paths[id] || paths.studio}</svg>;
};

const TOOL_STATE_COLOR = {
  running:'#2fb86a',
  starting:'#27c2e6',
  off:'#d48e2a',
  failed:'#d94a4a',
  unknown:LM.inkSoft,
  not_installed:LM.inkSoft,
};
const toolColor = state => TOOL_STATE_COLOR[state] || LM.inkSoft;
const hostRunningState = row => ['connected', 'listening', 'running'].includes(String(row?.state || '').toLowerCase());
const isOfficeHost = row => /^(excel|word|powerpoint|outlook)$/i.test(String(row?.name || row?.id || '').trim());
const hostConnectorRows = (rows = LM_HOSTS) => {
  const list = Array.isArray(rows) ? rows.filter(Boolean) : [];
  const office = list.filter(isOfficeHost);
  const officeRunning = office.filter(hostRunningState);
  const officeKnown = office.filter(h => typeof h.enabled === 'boolean');
  const officeOn = officeKnown.filter(h => h.enabled === true);
  const officeSummary = officeKnown.length
    ? String(officeOn.length) + ' of ' + office.length + ' on'
    : String(office.length) + ' Office host' + (office.length === 1 ? '' : 's');
  const officeRow = office.length ? {
    id:'office',
    name:office.map(h => h.name || h.id).join(' · '),
    state:officeRunning.length ? 'running' : (office[0].state || 'unknown'),
    connector_built:true,
    officeAggregate:true,
    officeChildren:office,
    officeEnabledSummary:officeSummary,
    officeDetail:officeRunning.length
      ? String(officeRunning.length) + ' Office host' + (officeRunning.length === 1 ? '' : 's') + ' running'
      : 'installed · reads when a file is open',
  } : null;
  return list.flatMap(row => !isOfficeHost(row) ? [row] : row === office[0] ? [officeRow] : []);
};
const hostCatalogueRows = (rows = window.ARCHHUB_HOSTS_READ || LM_HOSTS.length || typeof window.ARCHHUB_LOAD_HOSTS === 'function'
    ? LM_HOSTS : (window.ARCHHUB_LIVE?.connectors || LM_HOSTS)) => {
  // Current probes name an executable drive, or explicitly name no drive.
  // An absent/unconfigured catalogue entry also has no drive, but its detail
  // says "not found"/"add a token" rather than "no wire". Count the contract,
  // not that changing prose. Older hosted projections omit drive entirely.
  return rows.filter(row => Object.prototype.hasOwnProperty.call(row || {}, 'drive')
    ? typeof row.drive === 'string' && !!row.drive.trim()
    : !/no wire in this build/i.test(String(row?.detail || '')));
};
// One host count for the Connectors card, the status bar and the Hosts badge: every Settings row,
// with Office collapsed the same way everywhere.
const hostTally = (rows = window.ARCHHUB_HOSTS_READ || LM_HOSTS.length || typeof window.ARCHHUB_LOAD_HOSTS === 'function' ? LM_HOSTS : (window.ARCHHUB_LIVE?.connectors || LM_HOSTS)) => {
  // The Hosts list itself (studio.html fills it and ARCHHUB_LIVE.connectors from the same probe rows).
  // With no host reader at all there is nothing to wait for: the empty list is the answer.
  const list = hostConnectorRows(rows);
  const read = window.ARCHHUB_HOSTS_READ === true || list.length > 0 || typeof window.ARCHHUB_LOAD_HOSTS !== 'function';
  const builtRows = hostConnectorRows(hostCatalogueRows(rows)).filter(row => row?.connector_built !== false && !/no wire in this build|no connector yet/i.test(String(row?.detail || '')));
  return {
    running:builtRows.filter(hostRunningState).length,
    total:builtRows.length,
    coming:list.length - builtRows.length,
    builtRows,
    rows:list,
    read,
  };
};
const plural = (n, one, many = one + 's') => String(n) + ' ' + (n === 1 ? one : many);
const workshopWaitingItems = state => {
  const items = [];
  const work = state?.nativeWork;
  if (work && (work.state === 'awaiting_approval' || work.approving || work.approved === false && work.review_text)) {
    items.push({label:work.title || work.work || 'Workshop approval', source:'Workshop'});
  }
  const messages = state?.workshop?.messages || [];
  for (const msg of messages) {
    if (/ArchHub work proposal v1/.test(String(msg.body || ''))) {
      let title = 'Work proposal';
      try {
        const body = String(msg.body || ''), json = body.slice(body.indexOf('\n') + 1);
        title = JSON.parse(json).title || title;
      } catch (_) {}
      items.push({label:title, source:'Workshop proposal'});
    }
  }
  return items;
};
const readPersonalThemeSnapshot = () => {
  try { return window.ARCHHUB_EXISTING_WORKSHOP?.getSnapshot?.()?.theme || null; }
  catch (_) { return null; }
};
const TOOL_HUB_POLL_MS = 5000;
const TOOL_HUB_READ_TIMEOUT_MS = 15000;
let toolHubSnapshot = window.ARCHHUB_TOOL_HUB || null;
let toolHubTimer = null;
let toolHubController = null;
let toolHubInFlight = false;
let toolHubListeningVisibility = false;
let toolHubSnapshotSignature = toolHubSnapshot ? JSON.stringify(toolHubSnapshot) : '';
const toolHubSubscribers = new Set();
const getToolHubSnapshot = () => toolHubSnapshot || window.ARCHHUB_TOOL_HUB || null;
const notifyToolHubSubscribers = () => {
  for (const subscriber of [...toolHubSubscribers]) subscriber();
};
const currentArchHubSession = () => {
  const direct = window.__archhubSession || {};
  if (direct.token) return direct;
  try {
    const stored = JSON.parse(window.sessionStorage?.getItem('archhub.studio.session') || 'null') || {};
    if (stored.token) return stored;
  } catch (_) {}
  const boot = window.ARCHHUB_BOOT || {};
  return boot.token ? boot : {};
};
const toolHubFetchOptions = controller => {
  const session = currentArchHubSession();
  const headers = session.token ? {'X-ArchHub-Session':session.token, 'X-ArchHub-CSRF':session.csrf || ''} : null;
  return {...(controller ? {signal:controller.signal} : {}), ...(headers ? {headers} : {})};
};
const stopToolHubTimer = () => {
  if (toolHubTimer != null) window.clearInterval(toolHubTimer);
  toolHubTimer = null;
};
let toolHubWatchdog = null;
const abortToolHubRead = () => {
  if (toolHubWatchdog != null) window.clearTimeout(toolHubWatchdog);
  toolHubWatchdog = null;
  if (toolHubController) toolHubController.abort();
  toolHubController = null;
  toolHubInFlight = false;
};
const readToolHubProjection = () => {
  if (toolHubSubscribers.size === 0 || document.hidden || toolHubInFlight) return Promise.resolve(null);
  const request = typeof window.fetch === 'function' ? window.fetch.bind(window) :
    (typeof fetch === 'function' ? fetch : null);
  if (!request) return Promise.resolve(null);
  toolHubInFlight = true;
  const controller = typeof AbortController === 'function' ? new AbortController() : null;
  toolHubController = controller;
  // A read that never settles must not silence the Hub: after 15 s it is
  // abandoned (aborted) and the guard is released for the next tick.
  const watchdog = window.setTimeout(() => {
    if (toolHubController !== controller) return;
    controller?.abort();
    toolHubController = null;
    toolHubInFlight = false;
    toolHubWatchdog = null;
  }, TOOL_HUB_READ_TIMEOUT_MS);
  toolHubWatchdog = watchdog;
  const options = toolHubFetchOptions(controller);
  return Promise.all([
    request('/tools', options).then(response => response.ok ? response.json() : null).catch(() => null),
    request('/waiting', options).then(response => response.ok ? response.json() : null).catch(() => null),
  ]).then(([tools, waiting]) => {
    if (controller?.signal.aborted || toolHubSubscribers.size === 0) return null;
    const confirmedStopped = typeof tools?.stopped === 'boolean'
      ? tools.stopped
      : Boolean(toolHubSnapshot?.stopped);
    const payload = {
      ...(tools && Array.isArray(tools.tools) ? tools : {}),
      stopped: confirmedStopped,
      waiting:Array.isArray(waiting?.items) ? waiting.items : [],
      waiting_payload:waiting && typeof waiting === 'object' ? waiting : null,
    };
    if (!Array.isArray(payload.tools)) return null;
    const signature = JSON.stringify(payload);
    if (signature === toolHubSnapshotSignature) return toolHubSnapshot;
    toolHubSnapshotSignature = signature;
    toolHubSnapshot = payload;
    window.ARCHHUB_TOOL_HUB = payload;
    notifyToolHubSubscribers();
    return payload;
  }).catch(() => null).finally(() => {
    window.clearTimeout(watchdog);
    if (toolHubWatchdog === watchdog) toolHubWatchdog = null;
    // Only the current read releases the guard: an aborted older read that
    // settles after a newer one started must not let a third read overlap it.
    if (toolHubController === controller) {
      toolHubController = null;
      toolHubInFlight = false;
    }
  });
};
const armToolHubTimer = () => {
  if (toolHubTimer == null && toolHubSubscribers.size > 0 && !document.hidden) {
    toolHubTimer = window.setInterval(readToolHubProjection, TOOL_HUB_POLL_MS);
  }
};
const onToolHubVisibilityChange = () => {
  if (document.hidden) {
    stopToolHubTimer();
    abortToolHubRead();
    return;
  }
  armToolHubTimer();
  readToolHubProjection();
};
const subscribeToolHubProjection = subscriber => {
  toolHubSubscribers.add(subscriber);
  const first = toolHubSubscribers.size === 1;
  if (first && !toolHubListeningVisibility) {
    document.addEventListener('visibilitychange', onToolHubVisibilityChange);
    toolHubListeningVisibility = true;
  }
  if (first) {
    armToolHubTimer();
    readToolHubProjection();
  }
  return () => {
    toolHubSubscribers.delete(subscriber);
    if (toolHubSubscribers.size !== 0) return;
    stopToolHubTimer();
    abortToolHubRead();
    if (toolHubListeningVisibility) {
      document.removeEventListener('visibilitychange', onToolHubVisibilityChange);
      toolHubListeningVisibility = false;
    }
  };
};
const requestToolHubRefresh = () => readToolHubProjection();
const publishToolHubStopState = (stopped, error = '') => {
  const base = toolHubSnapshot || window.ARCHHUB_TOOL_HUB || {};
  const payload = {
    ...base,
    stopped: stopped === true,
    stop_error: String(error || ''),
    tools: Array.isArray(base.tools) ? base.tools : [],
    waiting: Array.isArray(base.waiting) ? base.waiting : [],
  };
  const signature = JSON.stringify(payload);
  if (signature === toolHubSnapshotSignature) return payload;
  toolHubSnapshotSignature = signature;
  toolHubSnapshot = payload;
  window.ARCHHUB_TOOL_HUB = payload;
  notifyToolHubSubscribers();
  return payload;
};
const refreshToolHubAfter = action => Promise.resolve(action).catch(() => null).finally(() => requestToolHubRefresh());
const useToolHubProjection = () => React.useSyncExternalStore(
  subscribeToolHubProjection,
  getToolHubSnapshot,
  getToolHubSnapshot
);
const useWaitingOpenShortcut = setOpen => {
  React.useEffect(() => {
    const onKey = event => {
      if ((event.ctrlKey || event.metaKey) && event.shiftKey && String(event.key).toLowerCase() === 'w') {
        event.preventDefault();
        setOpen(open => !open);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [setOpen]);
};
// The Workshop opens on its one Tasks tab: Tasks, Board and Projects are folded together (founder 2026-10-11).
// Founder 2026-10-12: a tool whose page is settings opens its Settings tab; the rail entry stays.
// Cloud's page only restated sign-in, which Settings > Account owns (one verdict, one place).
const TOOL_SETTINGS_TAB = {brain:'memory', connectors:'hosts', baboom:'baboom', cloud:'account'};
const firstToolTab = tool => tool === 'workshop' ? 'tasks' : tool === 'brain' ? 'facts' :
  tool === 'connectors' ? 'hosts' : tool === 'cloud' ? 'account' : tool === 'baboom' ? 'settings' : 'workspace';
const HOST_STATE_WORD = {
  connected:'Connected',
  listening:'Connected',
  reachable:'Checking',
  syncing:'Checking',
  starting:'Checking',
  checking:'Checking',
  installed:'Not running',
  running:'Not running',
  absent:'Not running',
  off:'Not running',
  unavailable:'Not running',
  'not running':'Not running',
  not_running:'Not running',
  not_installed:'Not installed',
  'not installed':'Not installed',
  needs_key:'Not installed',
  'needs-key':'Not installed',
};
const hostStateWord = row => HOST_STATE_WORD[String(row?.state || '').toLowerCase()] || 'Checking';
const hostStateTone = row => {
  const word = hostStateWord(row);
  return word === 'Connected' ? LM.ok : word === 'Checking' ? LM.warn : LM.inkSoft;
};
const hostPanelStateWord = row => {
  const state = String(row?.state || '').toLowerCase();
  if (state === 'connected' || state === 'listening' || state === 'running') return 'Running';
  if (state === 'installed' || state === 'prerequisites-ready' || state === 'needs-sign-in' || state === 'needs_key' || state === 'needs-key') return 'Installed';
  if (state === 'off' || state === 'stopped' || state === 'idle') return 'Not running';
  if (state === 'absent' || state === 'not_installed' || state === 'not installed' || state === 'unavailable') return 'Not installed';
  return 'Unknown';
};
const hostPanelStateTone = row => {
  const word = hostPanelStateWord(row);
  return word === 'Running' ? LM.ok : word === 'Unknown' ? LM.warn : LM.inkSoft;
};
const providerStateWord = p => {
  const state = String(p?.state || '').toLowerCase();
  if (state === 'keyed' || state === 'running') return 'Connected';
  if (state === 'no key' || state === 'missing' || state === 'signed out') return 'Sign in needed';
  if (state === 'key invalid' || state === 'unavailable' || state === 'not installed') return 'Unavailable';
  return 'Not connected';
};
// Ping F6a review: the Tools count states what the cards say. A card reading NOT RUNNING or NOT
// SIGNED IN is not running, whatever its owner row's raw state; STARTING / CHECKING is counted apart.
const toolLiveness = tool => {
  const word = String(tool?.stateWord || '').toUpperCase();
  if (tool?.state === 'off' || /^(OFF|NOT\b|DIDN'T|FAILED|STOPPED|DISCONNECTED)/.test(word)) return 'down';
  if (tool?.state === 'starting' || /STARTING|CHECKING|UNKNOWN|WAITING/.test(word)) return 'pending';
  return 'live';
};
const toolStateWord = state => ({
  running:'RUNNING', starting:'STARTING', off:'OFF', failed:"DIDN'T START", not_installed:'NOT INSTALLED',
  didnt_start:"DIDN'T START",
})[state] || String(state || 'OFF').replace(/_/g, ' ').toUpperCase();
const waitingLine = item => {
  const summary = String(item?.summary || item?.label || '').trim();
  if (summary) return summary;
  return `${item?.from || 'Someone'} wants ${item?.to || 'you'} to ${item?.action || 'review'}`;
};
const waitingMeta = item => {
  const bits = [
    'asked by ' + (item?.who || item?.from || 'someone'),
    'for ' + (item?.for || 'you'),
    item?.time || '',
    item?.plan_hash ? 'plan ' + item.plan_hash : '',
    item?.file || '',
  ].filter(Boolean);
  if (item?.second_approval) bits.push(`${item.approvals_done || 1} of ${item.approvals_required || 2} · needs another member`);
  if (item?.asker_alive === false) bits.push('asker restarted; approving delivers anyway');
  return bits.join(' · ');
};
const toolStatLineIsPlaceholder = value => /…|unknown/i.test(String(value || ''));
const WaitingButton = ({ items = [], variant = 'strip', onOpenTask }) => {
  const [open, setOpen] = React.useState(false);
  const [status, setStatus] = React.useState({});
  const liveItems = Array.isArray(items) ? items : [];
  useWaitingOpenShortcut(setOpen);
  if (!liveItems.length && !open) return <span data-waiting-empty-host="" style={{display:'contents'}}/>;
  const decide = (item, decision) => {
    setStatus(state => ({...state, [item.id]:'pending'}));
    const owner = window.ARCHHUB_EXISTING_WORKSHOP;
    const postRoute = (path, body) => {
      const session = window.__archhubSession || {};
      if (typeof window.fetch !== 'function') throw new Error('No owner route is available for ' + (item.producer || 'this request') + '.');
      return window.fetch(path, {method:'POST', headers:{'Content-Type':'application/json',
        'X-ArchHub-Session':session.token || '', 'X-ArchHub-CSRF':session.csrf || ''}, body:JSON.stringify(body)})
        .then(response => response.json().catch(() => ({})).then(payload => {
          if (!response.ok || payload?.ok === false) throw new Error(payload?.error || 'Decision refused.');
          return payload;
        }));
    };
    const run = () => {
      if (item.producer === 'workshop_gate') {
        const root = item.root || item.workshop || '';
        if (decision === 'approve' && owner?.approveNativeWork) return owner.approveNativeWork(root, item.input_digest);
        if (decision === 'reject' && owner?.nativeWorkAction) return owner.nativeWorkAction(root, 'stop_native', item.work || item.open_target || '');
      }
      if (item.producer === 'social_approve' && owner?.decideSocialApproval) {
        return owner.decideSocialApproval({delegation:item.delegation, input_digest:item.input_digest,
          decision:decision === 'approve' ? 'approve' : 'deny'});
      }
      if (decision === 'approve' && item.producer === 'model_delegation' && item.delegation) {
        return postRoute('/api/universal/model-delegation-approve', {delegation:item.delegation});
      }
      if (decision === 'approve' && (item.producer === 'baboom_execute' || item.producer === 'host_write') && item.delegation) {
        return postRoute('/api/universal/connector-delegation-approve', {delegation:item.delegation});
      }
      throw new Error('No owner route is available for ' + (item.producer || 'this request') + '.');
    };
    return Promise.resolve().then(run).then(() => {
      const finish = decision === 'approve' ? 'approved · delivered to ' + (item.to || item.producer || 'producer') : 'rejected';
      setStatus(state => ({...state, [item.id]: finish}));
      window.setTimeout(() => setStatus(state => ({...state, [item.id]: ''})), 2000);
    }).catch(error => {setStatus(state => ({...state, [item.id]: error?.message || 'decision refused'})); throw error;});
  };
  const showHost = item => {
    const ids = item.host_ids || item.ids || [];
    if (!ids.length || !window.ARCHHUB_CONNECTORS?.highlight) {
      setStatus(state => ({...state, [item.id]:'No host route is available.'}));
      return;
    }
    window.ARCHHUB_CONNECTORS.highlight({ids, readonly:true});
    setStatus(state => ({...state, [item.id]:'shown'}));
    window.setTimeout(() => setStatus(state => ({...state, [item.id]: ''})), 2000);
  };
  const label = variant === 'home' ? 'Waiting for you' : `${liveItems.length} waiting for you`;
  return <span style={{position:'relative', display:variant === 'home' ? 'block' : 'inline-flex'}}>
    <window.AH_DS.Btn type="button" data-waiting-trigger={variant} onClick={() => setOpen(value => !value)} style={{
      width:variant === 'home' ? '100%' : 'auto', textAlign:'left', padding:variant === 'home' ? '8px 10px' : '0 4px',
      border:variant === 'home' ? `1px solid ${LM.lineSoft}` : 0, borderRadius:variant === 'home' ? LM.rad.sm : 0,
      background:variant === 'home' ? LM.bg : 'transparent', color:LM.inkSoft, cursor:'pointer',
      fontFamily:LM.mono, fontSize:variant === 'home' ? 10.5 : 9.5, letterSpacing:'0.04em',
    }}>
      <span style={{color:LM.warn}}>{label}</span>
      {variant === 'home' && <span style={{color:LM.ink, marginLeft:8}}>{waitingLine(liveItems[0])}</span>}
    </window.AH_DS.Btn>
    {open && <div data-waiting-popover="" style={{
      position:'absolute', zIndex:20, bottom:variant === 'strip' ? 22 : 'auto', top:variant === 'home' ? '100%' : 'auto',
      left:0, width:480, maxWidth:'calc(100vw - 40px)', maxHeight:'70vh', overflow:'auto',
      background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:LM.rad.sm,
      boxShadow:'0 18px 44px rgba(0,0,0,.32)', padding:10,
    }}>
      {liveItems.length === 0 ? <div style={{fontSize:13, color:LM.inkSoft}}>Nothing waiting.</div> :
        liveItems.map(item => <div key={item.id} data-waiting-item={item.id} style={{
          border:`1px solid ${item.second_approval ? '#8b5cf6' : LM.lineSoft}`,
          borderRadius:LM.rad.sm, padding:'9px 10px', marginBottom:8,
        }}>
          {window.ARCHHUB_APPROVAL_CARD && React.createElement(window.ARCHHUB_APPROVAL_CARD, {
            surface:variant === 'home' ? 'home' : 'status', approveLabel:'Approve',
            approval:{...item,state:'needs-user',title:waitingLine(item),target:item.target || item.to || '',
              scope:waitingMeta(item),rows:item.changes || item.approval_rows || [],
              preview:item.preview || (item.review_text ? {kind:'post',text:item.review_text} : undefined)},
            busy:status[item.id] === 'pending',
            canApprove:!(item.second_approval && String(status[item.id] || '').startsWith('approved')) &&
              (item.producer === 'workshop_gate' ? typeof window.ARCHHUB_EXISTING_WORKSHOP?.approveNativeWork === 'function' && !!item.input_digest :
                item.producer === 'social_approve' ? typeof window.ARCHHUB_EXISTING_WORKSHOP?.decideSocialApproval === 'function' :
                ['model_delegation','baboom_execute','host_write'].includes(item.producer) && !!item.delegation && typeof window.fetch === 'function'),
            canDecline:item.producer === 'social_approve' ? typeof window.ARCHHUB_EXISTING_WORKSHOP?.decideSocialApproval === 'function' :
              item.producer === 'workshop_gate' &&
                (item.mode === 'agent' || window.ARCHHUB_EXISTING_WORKSHOP?.getSnapshot?.()?.nativeWork?.mode === 'agent') &&
                typeof window.ARCHHUB_EXISTING_WORKSHOP?.nativeWorkAction === 'function',
            onApprove:() => decide(item,'approve'),onDecline:() => decide(item,'reject')})}
          <div style={{display:'flex', gap:6, alignItems:'center', marginTop:8, flexWrap:'wrap'}}>
            {item.producer === 'workshop_gate' ? (
              <window.AH_DS.Btn type="button" onClick={() => onOpenTask ? onOpenTask(item) :
                setStatus(state => ({...state, [item.id]:'Approvals view is unavailable.'}))} style={window.AH_DS.styles.button(true ? 'primary' : 'secondary', true)}>
                {item.open_label || 'Open in Approvals'}
              </window.AH_DS.Btn>
            ) : null}
            {(item.host_ids || item.ids || []).length > 0 && window.ARCHHUB_CONNECTORS?.highlight &&
              <window.AH_DS.Btn type="button" onClick={() => showHost(item)} style={window.AH_DS.styles.button("secondary", true)}>Show in host</window.AH_DS.Btn>}
            {onOpenTask && item.producer !== 'workshop_gate' && <window.AH_DS.Btn type="button" onClick={() => onOpenTask(item)} style={window.AH_DS.styles.button("secondary", true)}>Open task</window.AH_DS.Btn>}
            {item.second_approval && <span style={{fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft}}>Needs {item.ask_member || 'member'}</span>}
            {status[item.id] && status[item.id] !== 'pending' && <span style={{fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft}}>{status[item.id]}</span>}
          </div>
        </div>)}
    </div>}
  </span>;
};
const FRAME_TOOL_DEFAULTS = [
  ['studio', 'Studio', 'running', 'Canvas, chats and graph sessions.', '0 sessions · 0 running.', 'Switched off. Sessions are kept.', 'Studio → Brain · Connectors · Workshop', 'Studio is off', 'Canvas view unavailable. The window itself stays up.'],
  ['workshop', 'Workshop', 'running', 'Projects, tasks and governed work.', '0 projects · 0 tasks.', 'Switched off. Tasks are paused.', 'Workshop → Studio · Connectors · Brain', 'Workshop is off', 'No agent loop, no tasks run, no router. Chat still works locally.'],
  ['brain', 'Brain', 'off', 'Memory, facts and local classification.', '0 facts in local Brain.', 'Switched off. Nothing is remembered or recalled.', 'Brain → Studio · Workshop · Cloud', 'Brain is off', 'What ArchHub remembers. Everything else keeps running.'],
  ['baboom', 'BABOOM', 'starting', 'Desktop companion and approved execution.', 'No signed runtime attached.', 'Switched off. No companion on the desktop.', 'BABOOM ← Studio · Workshop', 'BABOOM is off', 'The companion is closed. Nothing else changes.'],
  ['connectors', 'Connectors', 'running', 'Host bridges and Speckle access.', '0/0 hosts connected.', 'Switched off. No reads or writes to your programs.', 'Connectors → Studio · Workshop · Speckle', 'Connectors are off', 'No host reads or writes. Pinned host outputs still feed downstream.'],
  ['cloud', 'Cloud', 'starting', 'Devices, grants and cloud agents.', 'Not signed in.', 'Switched off. Works on this machine only.', 'Cloud ← Brain · Workshop', 'Cloud is off', 'No tunnel, heartbeat, or sync. Everything local is unchanged.'],
].map(([id, label, state, description, statLine, offSentence, wireSummary, emptyTitle, emptyLine]) => ({
  id, label, state, description, stat_line:statLine, off_sentence:offSentence, wire_summary:wireSummary, emptyTitle, emptyLine,
}));
const toolRowsFromOwners = ({workshopState, account, personal, hub}) => {
  const liveHosts = LM_HOSTS.filter(host => hostState(host) === 'connected');
  const connectorHostWord = hostStateWord(liveHosts[0] || {state:'off'});
  const waiting = workshopWaitingItems(workshopState);
  const graph = window.ARCHHUB_LIVE?.graph || LM_GRAPH;
  const baboom = personal?.configuration?.baboom_startup;
  const baboomOn = baboom?.value === 'on';
  const signedIn = !!(account && account.signedIn);
  const api = window.ARCHHUB_EXISTING_WORKSHOP;
  const projects = (workshopState?.workshops || []).length;
  const tasks = Math.max(waiting.length, workshopState?.nativeWork ? 1 : 0);
  const connectorsTally = hostTally();
  const stats = {
    studio:{stat:plural(LM_SESSIONS.length, 'session') + ' · ' + plural(LM_SESSIONS.filter(s => s.state === 'running').length, 'running', 'running'), wire:plural((graph?.wires || []).length, 'wire')},
    workshop:{stat:plural(projects, 'project') + ' · ' + plural(tasks, 'task'), wire:waiting.length ? plural(waiting.length, 'waiting') : 'no waiting work'},
    brain:{stat:plural(LM_MEMORY.length, 'fact'), wire:plural((window.BRAIN_STRATA || []).length, 'stratum', 'strata')},
    baboom:{stat:'Starts with Windows: ' + (baboomOn ? 'on' : 'off'), wire:baboom?.source ? String(baboom.source) : 'Personal Settings'},
    connectors:{stat:String(connectorsTally.running) + '/' + String(connectorsTally.total) + ' hosts running.', wire:plural(connectorsTally.total, 'connector')},
    cloud:{stat:signedIn ? String(account.email || 'signed in') : 'signed out', wire:window.ARCHHUB_CLOUD_SESSION ? 'cloud session owner' : 'no device list owner'},
  };
  const baboomToggle = {
    canToggle:!!api?.setBaboomStartup && !!baboom,
    toggleChecked:baboomOn,
    turnOn:() => api?.setBaboomStartup ? refreshToolHubAfter(api.setBaboomStartup('on')) : requestToolHubRefresh(),
    turnOff:() => api?.setBaboomStartup ? refreshToolHubAfter(api.setBaboomStartup('off')) : requestToolHubRefresh(),
  };
  const hubRows = Array.isArray(hub?.tools) && hub.tools.length ? hub.tools
    : Array.isArray(window.ARCHHUB_TOOL_HUB?.tools) && window.ARCHHUB_TOOL_HUB.tools.length ? window.ARCHHUB_TOOL_HUB.tools
    : FRAME_TOOL_DEFAULTS;
  return hubRows.map(row => {
    const rawState = String(row.state || 'off');
    const normalizedState = rawState === 'unknown' ? 'starting' : rawState;
    const rowWord = String(row.state_word || '');
    const stateWord = row.id === 'connectors' ? connectorHostWord :
      /unknown/i.test(rowWord) ? toolStateWord(normalizedState) : (rowWord || toolStateWord(normalizedState));
    const tally = row.id === 'connectors' ? connectorsTally : null;
    const ownerLine = tally ? (tally.read ? stats.connectors.stat : 'Checking hosts.')
      : toolStatLineIsPlaceholder(row.stat_line) ? stats[row.id]?.stat : (row.stat_line || stats[row.id]?.stat || '');
    const baboomRuntime = ownerLine || 'No signed runtime attached.';
    const statLine = row.id === 'baboom'
      ? [baboomRuntime, stats.baboom.stat].filter(Boolean).join(' · ')
      : tally ? ownerLine
      : normalizedState === 'off' ? (row.off_sentence || stats[row.id]?.stat || ownerLine || '') : ownerLine;
    return {
      ...row,
      ...(stats[row.id] || {}),
      state:row.id === 'baboom' && baboom?.value === 'off' ? 'off' : normalizedState,
      stateWord:row.id === 'baboom' && baboom?.value === 'off' ? 'OFF' : stateWord,
      description:row.description || '',
      emptyTitle:row.emptyTitle || row.empty_title || row.label + ' is off',
      emptyLine:row.emptyLine || row.empty_line || row.off_sentence || '',
      statLine,
      cardStat:row.id === 'baboom' ? baboomRuntime : statLine,
      wireSummary:row.wire_summary || stats[row.id]?.wire || '',
      // The dot says what the word says, in the designed palette: running green, starting cyan,
      // off amber, and any other not-running word grey (a NOT RUNNING card is never green).
      color:(liveness => toolColor(liveness === 'live' ? 'running' : liveness === 'pending' ? 'starting'
        : (row.id === 'baboom' && baboom?.value === 'off') || normalizedState === 'off' ? 'off' : 'unknown'))(
        toolLiveness({state:row.id === 'baboom' && baboom?.value === 'off' ? 'off' : normalizedState,
          stateWord:row.id === 'baboom' && baboom?.value === 'off' ? 'OFF' : stateWord})),
      ...(row.id === 'baboom' ? baboomToggle : {}),
    };
  });
};

const ToolOffPanel = ({ tool }) => {
  if (!tool) return null;
  return <div style={{display:'flex', flexDirection:'column', minHeight:0, padding:'12px'}}>
    <div style={{display:'flex', alignItems:'center', gap:8, marginBottom:14}}>
      <span style={{color:tool.color, display:'inline-flex'}}><ToolGlyph id={tool.id}/></span>
      <span style={{fontFamily:LM.sans, fontSize:14, fontWeight:600, color:LM.ink}}>{tool.label}</span>
    </div>
    <div style={{padding:'10px 0 0'}}>
      <h2 style={{fontFamily:LM.sans, fontSize:15, fontWeight:400, margin:'0 0 8px', color:LM.ink}}>{tool.emptyTitle}</h2>
      <p style={{fontFamily:LM.sans, fontSize:13, color:LM.inkSoft, margin:'0 0 14px'}}>{tool.emptyLine}</p>
      {tool.turnOn && <window.AH_DS.Btn type="button" onClick={tool.turnOn} style={{
        padding:'7px 11px', border:0, borderRadius:LM.rad.sm, background:LM.accent,
        color:(window.AH && window.AH.onFill) || '#180f08', fontFamily:LM.sans,
        fontSize:12.5, fontWeight:600, cursor:'pointer',
      }}>Turn on</window.AH_DS.Btn>}
    </div>
  </div>;
};

const ChatsPanel = ({ openId, onOpen, onNew, onHome, account, onAccount }) => (
  <div style={{ display:'flex', flexDirection:'column', overflow:'hidden', minHeight:0 }}>
    <PanelHead title="Chats">
      <window.AH_DS.Btn title="New chat" onClick={onNew} style={window.AH_DS.styles.button("ghost", true)}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 1 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/></svg>
      </window.AH_DS.Btn>
    </PanelHead>

    <Search ph="Search chats..."/>

    {/* Sessions list */}
    <div className="ah-scroll" style={{ flex:1, overflow:'auto', padding:'0 6px 8px', minHeight:0 }}>
      {LM_SESSIONS.map(s => {
        const a = openId === s.id;
        const sm = LM_STATE_META[s.state];
        return (
          <window.AH_DS.Btn key={s.id} onClick={() => onOpen(s.id)} style={{
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
            {a && <span style={{ fontFamily:LM.sans, fontSize:14, color:LM.inkSoft, lineHeight:0.5 }}>···</span>}
          </window.AH_DS.Btn>
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
    <window.AH_DS.Btn type="button" aria-label="Account" title={email || 'Sign in'} onClick={onOpen} style={{
      margin:LM.sp.sm, padding:'7px 10px', borderRadius:LM.rad.md,
      background:LM.bgSoft, border:`1px solid ${LM.line}`,
      display:'flex', alignItems:'center', gap:9, textAlign:'left',
      color:LM.ink, fontFamily:LM.sans, cursor:'pointer',
    }}>
      {name && <div style={{ width:22, height:22, borderRadius:'50%', background:LM.userAv, display:'grid', placeItems:'center', fontSize:11, color:LM.onUserAv, fontWeight:700, flexShrink:0 }}>{name[0].toUpperCase()}</div>}
      <div style={{ flex:1, lineHeight:1.1, minWidth:0 }}>
        <div style={{ fontSize:12, fontWeight:500, color:name ? LM.ink : LM.accent, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{name || 'Sign in'}</div>
        {tier && <div style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.08em' }}>{tier}</div>}
      </div>
    </window.AH_DS.Btn>
  );
};



const useNodeLibrary = (enabled = true) => {
  const [, refresh] = React.useState(0);
  const [attempt, setAttempt] = React.useState(0);
  const [timedOut, setTimedOut] = React.useState(false);
  const pending = enabled && (window.AH_LIBRARY_LOADING === true ||
    (typeof window.AH_LOAD_LIBRARY === 'function' && !window.AH_LIBRARY_LOADED && !window.AH_LIBRARY_ERROR));
  React.useEffect(() => {
    const changed = () => refresh(value => value + 1);
    window.addEventListener('archhub:library-refresh', changed);
    return () => window.removeEventListener('archhub:library-refresh', changed);
  }, []);
  React.useEffect(() => {
    if (enabled && typeof window.AH_LOAD_LIBRARY === 'function') window.AH_LOAD_LIBRARY().catch(() => {});
  }, [enabled]);
  React.useEffect(() => {
    setTimedOut(false);
    if (!pending) return;
    const timer = setTimeout(() => setTimedOut(true), 1900);
    return () => clearTimeout(timer);
  }, [pending, attempt]);
  const retry = React.useCallback(() => {
    setAttempt(value => value + 1);
    if (typeof window.AH_LOAD_LIBRARY === 'function') window.AH_LOAD_LIBRARY(true).catch(() => {});
  }, []);
  return {loading:pending && !timedOut, error:timedOut ? 'The node library did not answer. Check the connection and try again.' : window.AH_LIBRARY_ERROR || '', retry};
};

// ─── Library panel — primary drag source ───
const LIBRARY_FAMILIES = [
  {id:'all', label:'All', cats:null},
  {id:'get', label:'Get', cats:['host', 'input', 'trigger']},
  {id:'change', label:'Change', cats:['shape', 'transform', 'document']},
  {id:'decide', label:'Decide', cats:['logic', 'ai', 'agent']},
  {id:'see', label:'See', cats:['watch', 'check']},
  {id:'send', label:'Send', cats:['output']},
];
const LIBRARY_FAMILY_BY_CAT = LIBRARY_FAMILIES.reduce((out, family) => {
  (family.cats || []).forEach(cat => { out[cat] = family.id; });
  return out;
}, {});
const LIBRARY_CATEGORY_ORDER = ['host', 'input', 'trigger', 'shape', 'transform', 'document', 'logic', 'ai', 'agent', 'watch', 'check', 'output'];
const LIBRARY_DISPLAY_CAT_BY_RAW = {
  host:'host', input:'input', trigger:'trigger', shape:'shape', transform:'transform',
  document:'document', file:'output', text:'shape', math:'shape', logic:'logic',
  ai:'ai', governance:'agent', watch:'watch', output:'output', note:'shape', skill:'agent',
};
const LIBRARY_CHECK_ITEMS = new Set(['g_dryrun_diff', 'g_host_health', 'g_evidence_attach', 'g_rule_check']);
const libraryHumanText = value => String(value || '').replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();
const libraryTitle = item => libraryHumanText(item.title || item.name || item.label || 'Untitled node');
const librarySub = (item, cat) => libraryHumanText(item.sub || item.description || cat.role || '');
const librarySearchText = (group, item) => [group.cat, studioCategory(group.cat).label, libraryTitle(item), librarySub(item, studioCategory(group.cat))]
  .join(' ').toLowerCase();
const libraryTotal = groups => visibleLibraryGroups(groups).reduce((n, group) => n + group.items.length, 0);
const librarySource = projected => {
  if (Array.isArray(window.AH_LIBRARY)) return visibleLibraryGroups(window.AH_LIBRARY);
  if (Array.isArray(projected?.library) && projected.library.length) return visibleLibraryGroups(projected.library);
  return [];
};
const libraryDisplayCategory = (rawCat, item) => {
  if (LIBRARY_CHECK_ITEMS.has(String(item?.id || ''))) return 'check';
  return LIBRARY_DISPLAY_CAT_BY_RAW[String(rawCat || '').toLowerCase()] || String(rawCat || '').toLowerCase() || 'shape';
};
const libraryDisplayGroups = library => {
  const buckets = Object.fromEntries(LIBRARY_CATEGORY_ORDER.map(cat => [cat, []]));
  const seen = new Set();
  for (const group of visibleLibraryGroups(library)) {
    for (const item of group.items || []) {
      const id = String(item.id || '');
      if (!id || seen.has(id)) continue;
      seen.add(id);
      const displayCat = libraryDisplayCategory(group.cat, item);
      if (!buckets[displayCat]) buckets[displayCat] = [];
      buckets[displayCat].push({...item, rawCat:group.cat, displayCat});
    }
  }
  const known = LIBRARY_CATEGORY_ORDER
    .filter(cat => (buckets[cat] || []).length)
    .map(cat => ({cat, items:buckets[cat]}));
  const custom = Object.keys(buckets)
    .filter(cat => !LIBRARY_CATEGORY_ORDER.includes(cat) && (buckets[cat] || []).length)
    .sort((a, b) => a.localeCompare(b))
    .map(cat => ({cat, items:buckets[cat]}));
  return [...known, ...custom];
};
const libraryVisibleGroups = (library, family, q) => {
  const query = q.trim().toLowerCase();
  return visibleLibraryGroups(library).map(group => {
    const catId = String(group.cat || '').toLowerCase();
    if (family !== 'all' && LIBRARY_FAMILY_BY_CAT[catId] !== family) return {...group, items:[]};
    const items = (group.items || []).filter(item => !query || librarySearchText(group, item).includes(query));
    return {...group, items};
  }).filter(group => group.items.length);
};
const libraryPortKind = port => {
  const type = String(port?.type || port?.t || port?.logical_type || '').toLowerCase();
  const cardinality = String(port?.cardinality || (port?.multiple ? 'many' : '')).toLowerCase();
  if (!type || type === 'unknown' || cardinality === 'unknown') return 'unknown';
  if (type === 'trigger' || type === 'event' || type === 'exec' || port?.shape === 'triangle') return 'trigger';
  if (cardinality === 'many' || cardinality === 'list' || cardinality === 'multiple') return 'list';
  return 'single';
};
const libraryPortGlyph = kind => kind === 'trigger' ? '▷' : kind === 'list' ? '◇' : kind === 'unknown' ? '?' : '●';
const libraryPortSummary = item => {
  const rows = [];
  const ports = item?.ports || item?.port_metadata || null;
  for (const [side, dir] of [['target', 'in'], ['source', 'out']]) {
    const declared = Array.isArray(ports?.[side]) ? ports[side] : null;
    const fallback = !declared && Array.isArray(item?.sockets?.[side])
      ? item.sockets[side].map(name => ({id:name, type:'unknown', cardinality:'unknown'}))
      : [];
    for (const port of declared || fallback) {
      const kind = libraryPortKind(port);
      const name = port.id || port.name || port.port_id || '';
      rows.push({glyph:libraryPortGlyph(kind), label:(kind === 'trigger' ? 'trigger' : kind) + ' ' + dir, name, dir});
    }
  }
  return rows;
};
const LibraryTile = ({ cat, group, open, onToggle }) => (
  <window.AH_DS.Btn type="button" onClick={onToggle} data-library-category={String(group.cat || '')} style={{
    width:'100%', height:30, padding:'0 6px', border:0, borderRadius:5,
    background:open ? LM.bgHover : 'transparent', color:LM.ink, cursor:'pointer',
    display:'flex', alignItems:'center', gap:8, fontFamily:LM.sans, fontSize:13, textAlign:'left',
  }}>
    <span style={{ width:8, color:LM.inkSoft, fontSize:11 }}>{open ? '▾' : '▸'}</span>
    <span style={{ width:18, height:18, borderRadius:4, background:cat.col, color:LM.onFill,
      display:'grid', placeItems:'center', fontSize:11, fontWeight:600, flex:'none' }}>{cat.icon}</span>
    <span style={{ flex:1, minWidth:0, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{cat.label[0] + cat.label.slice(1).toLowerCase()}</span>
    <span style={{ color:LM.inkSoft, fontSize:11 }}>{(group.items || []).length}</span>
  </window.AH_DS.Btn>
);
const NodesPanel = ({ addNodeFromLibrary, onHome, account, onAccount, onSwitchPanel, onOpenRuns, initialQuery = '' }) => {
  const libraryRead = useNodeLibrary();
  const projected = useStudioProjection();
  const workshopState = useWorkshopProjection();
  const hub = useToolHubProjection();
  const runsWaiting = Array.isArray(hub?.waiting) ? hub.waiting.length : workshopWaitingItems(workshopState).length;
  const library = libraryDisplayGroups(librarySource(projected));
  const [q, setQ] = React.useState(initialQuery);
  const [family, setFamily] = React.useState('all');
  const [openCats, setOpenCats] = React.useState(() => ({shape:true}));
  const [selectedId, setSelectedId] = React.useState('');
  const [insertBusy, setInsertBusy] = React.useState(false), [insertError, setInsertError] = React.useState('');
  const admission = React.useRef({busy:false,live:true,last:null});
  React.useEffect(()=>{admission.current.live=true;return()=>{admission.current.live=false;};},[]);
  const addRef = React.useRef(addNodeFromLibrary);
  addRef.current = addNodeFromLibrary;
  const addFromLibrary = React.useCallback(async item => {
    const held=admission.current;
    if(held.busy || !held.live || !addRef.current)return false;
    held.busy=true;held.last=item;setInsertBusy(true);setInsertError('');
    try {
      const result=await addRef.current(item);
      if(result===false && held.live)setInsertError('The node was not added. Retry or choose another node.');
      return result;
    } catch(error) {if(held.live)setInsertError(window.AH_DS.errorText(error.message || 'The node could not be added.'));return false;}
    finally {held.busy=false;if(held.live)setInsertBusy(false);}
  }, []);
  const toggleCat = React.useCallback(cat => setOpenCats(o => ({ ...o, [cat]: !o[cat] })), []);
  const groups = libraryVisibleGroups(library, family, q);
  return (
    <window.AH_DS.Frame data-library-panel="" style={{ display:'flex', flexDirection:'column', overflow:'hidden', minHeight:0 }}>
      <div style={{ display:'flex', gap:4, padding:'10px 10px 0' }}>
        {[
          ['Library', 'nodes', onSwitchPanel ? () => onSwitchPanel('nodes') : null],
          ['Graphs', 'chats', onSwitchPanel ? () => onSwitchPanel('chats') : null],
          ['Skills', 'skills', onSwitchPanel ? () => onSwitchPanel('skills') : null],
          ['Runs', 'runs', onOpenRuns || (onSwitchPanel ? () => onSwitchPanel('runs') : null)],
        ].map(([tab, route, act]) => (
          <window.AH_DS.Btn key={tab} type="button" data-library-tab={route} onClick={act} disabled={!act && route !== 'nodes'} style={{ height:28, display:'inline-flex', alignItems:'center', gap:5, padding:'0 7px',
            borderRadius:5, fontFamily:LM.sans, fontSize:13,
            background:route === 'nodes' ? LM.accentDim : 'transparent',
            color:route === 'nodes' ? LM.accent : LM.inkSoft, border:0, cursor:'pointer' }}>
            {tab}{tab === 'Runs' && runsWaiting > 0 && <span style={{ fontSize:11, background:LM.bgHover, color:LM.ink, borderRadius:999, padding:'0 6px' }}>{runsWaiting}</span>}
          </window.AH_DS.Btn>
        ))}
      </div>

      <div style={{ padding:'10px 10px 8px' }}>
        <div style={{
          height:32, boxSizing:'border-box', display:'flex', alignItems:'center', gap:8, padding:'0 10px',
          background:LM.bgSoft, border:`1px solid ${LM.line}`, borderRadius:5,
        }}>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke={LM.inkSoft} strokeWidth="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
          <window.AH_DS.TextField autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder={`Search ${libraryTotal(groups)} nodes`} style={{
            flex:1, minWidth:0, border:0, background:'transparent', color:LM.ink, fontSize:13, outline:'none', fontFamily:LM.sans,
          }}/>
          <span style={{ color:LM.inkSoft, fontSize:11 }}>/</span>
        </div>
      </div>

      <div style={{ display:'flex', flexWrap:'wrap', gap:6, padding:'0 10px 8px' }}>
        {LIBRARY_FAMILIES.map(filter => (
          <span key={filter.id} role="button" tabIndex={0}
            onClick={() => setFamily(filter.id)}
            onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setFamily(filter.id); } }}
            style={{
            height:24, display:'inline-flex', alignItems:'center', padding:'0 9px',
            borderRadius:999, border:filter.id === family ? '1px solid transparent' : `1px solid ${LM.line}`,
            background:filter.id === family ? LM.accentDim : 'transparent',
            color:filter.id === family ? LM.accent : LM.ink,
            cursor:'pointer', fontFamily:LM.sans, fontSize:12,
          }}>{filter.label}</span>
        ))}
      </div>

      {insertError && <window.AH_DS.EmptyState compact glyph={null} error title="Node not added" detail={insertError} onRetry={()=>addFromLibrary(admission.current.last)}/>}
      <div className="ah-scroll" style={{ flex:1, overflow:'auto', padding:'0 6px 8px', minHeight:0 }}>
        {(libraryRead.loading || libraryRead.error || !library.length) && <window.AH_DS.EmptyState glyph={null} title={libraryRead.loading ? "Reading nodes…" : libraryRead.error ? "Library unavailable" : !library.length ? "No nodes yet" : ""} error={!!libraryRead.error} detail={libraryRead.error} onRetry={libraryRead.error || !library.length ? libraryRead.retry : undefined}/>}

        <NodeLibraryGroups library={groups} q={q} openCats={openCats} onToggle={toggleCat} onAdd={addFromLibrary}
          selectedId={selectedId} onSelect={setSelectedId} disabled={insertBusy}/>
      </div>

    </window.AH_DS.Frame>
  );
};

// The library rows re-render on every owner publish; memoizing keeps drag/search calm.
const NodeLibraryGroups = React.memo(({ library, q, openCats, onToggle, onAdd, selectedId = '', onSelect = null, disabled = false }) => (
  <>
        {library.map((group, index) => {
          const c = studioCategory(group.cat);
          const items = group.items || [];
          if (items.length === 0) return null;
          const open = q ? true : !!openCats[group.cat];
          const family = LIBRARY_FAMILIES.find(row => row.id === LIBRARY_FAMILY_BY_CAT[String(group.cat || '').toLowerCase()]);
          const prev = library.slice(0, index).reverse().find(row => (row.items || []).length);
          const prevFamily = prev && LIBRARY_FAMILIES.find(row => row.id === LIBRARY_FAMILY_BY_CAT[String(prev.cat || '').toLowerCase()]);
          const showFamily = family && family.id !== prevFamily?.id;
          return (
            <div key={group.cat} data-library-family={family?.label || 'Other'} style={{ marginBottom:2 }}>
              {showFamily && <div style={{ fontSize:11, color:LM.inkSoft, padding:'8px 6px 2px', letterSpacing:'.04em', textTransform:'uppercase', fontFamily:LM.sans }}>{family.label}</div>}
              <LibraryTile cat={c} group={{...group, items}} open={open} onToggle={() => onToggle(group.cat)}/>
              {open && (
                <div style={{ display:'flex', flexDirection:'column', gap:1, paddingLeft:34 }}>
                  {items.map(it => <NodeLibItem key={it.id} it={it} cat={c} catId={group.cat}
                    selected={selectedId === it.id} disabled={disabled}
                    onAdd={() => { onSelect && onSelect(it.id); onAdd({ ...it, cat:it.rawCat || group.cat }); }}/>)}
                </div>
              )}
            </div>
          );
        })}
  </>
));

const NodeLibItem = ({ it, cat, catId, selected = false, onAdd, disabled = false }) => {
  const [h, setH] = React.useState(false);
  const onDragStart = (e) => {
    e.dataTransfer.effectAllowed = 'copy';
    e.dataTransfer.setData('application/x-lm-node', JSON.stringify({ ...it, cat: catId }));
    e.dataTransfer.setData('text/plain', libraryTitle(it));
    window.__archhubDraggingLibraryTitle = libraryTitle(it);
  };
  const title = libraryTitle(it);
  const sub = librarySub(it, cat);
  const ports = libraryPortSummary(it);
  const outlined = h || selected;
  return (
    <window.AH_DS.Btn type="button"
      disabled={disabled}
      draggable={!disabled}
      onDragStart={onDragStart}
      onDragEnd={() => { delete window.__archhubDraggingLibraryTitle; }}
      onClick={onAdd}
      onMouseEnter={() => setH(true)}
      onMouseLeave={() => setH(false)}
      data-library-row={title}
      style={{
        width:'100%', minHeight:32, display:'flex', alignItems:'center', gap:8, padding:'5px 8px',
        borderRadius:4, cursor:'grab', userSelect:'none',
        background: h || selected ? LM.bgHover : 'transparent',
        border:`1px ${outlined ? 'dashed' : 'solid'} ${outlined ? LM.accent : 'transparent'}`,
        transition:`background ${LM.dur.fast}ms, border-color ${LM.dur.fast}ms`,
        color:LM.ink, fontFamily:LM.sans, textAlign:'left',
      }}>
      <div style={{ flex:1, minWidth:0, lineHeight:1.2 }}>
        <div style={{ fontFamily:LM.sans, fontSize:13, color:LM.ink, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{title}</div>
        <div style={{ fontFamily:LM.sans, fontSize:11, color:LM.inkSoft, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{sub}</div>
      </div>
      <span data-library-port-glyphs="" aria-label={ports.map(port => port.label + ' ' + port.name).join(' · ')}
        title={ports.map(port => port.label + ' · ' + port.name).join('\n')}
        style={{ display:'inline-flex', alignItems:'center', justifyContent:'flex-end', gap:3, minWidth:38,
          color:LM.inkSoft, fontSize:12, flexShrink:0 }}>
        {ports.slice(0, 4).map((port, index) => <React.Fragment key={port.dir + port.name + index}>{index > 0 && ports[index-1].dir !== port.dir && <span aria-hidden="true">→</span>}<span>{port.glyph}</span></React.Fragment>)}
      </span>
    </window.AH_DS.Btn>
  );
};

// ─── Skills panel — saved templates the user has accrued ───
const LM_SAVED_SKILLS = (window.ARCHHUB_LIVE?.skills) || [];


const catalogueStates = new Map(), catalogueListeners = new Set();
const CATALOGUE_TIMEOUT_MS = 15000;
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
  // No loader (a hosted page): the list ARCHHUB_LIVE holds is the whole list, so it counts as read.
  if (typeof load !== 'function') {
    if (!catalogueStates.has(loaderName)) {
      catalogueStates.set(loaderName, {loading:false, error:'', read:true});
      catalogueChanged();
    }
    return Promise.resolve();
  }
  let state = catalogueStates.get(loaderName);
  if (state?.pending) return state.pending;
  state = {loading:true, error:'', pending:null};
  catalogueStates.set(loaderName, state);
  // Wait at most CATALOGUE_TIMEOUT_MS (window.ARCHHUB_CATALOGUE_TIMEOUT_MS overrides it); then say so and offer Retry.
  const waitMs = Number(window.ARCHHUB_CATALOGUE_TIMEOUT_MS) > 0 ? Number(window.ARCHHUB_CATALOGUE_TIMEOUT_MS) : CATALOGUE_TIMEOUT_MS;
  let timer = null;
  const later = typeof window.setTimeout === 'function' ? window.setTimeout.bind(window) : null;
  const timeout = later ? new Promise((_, reject) => { timer = later(() => reject(new Error(
    'This list did not answer in ' + Math.round(waitMs / 1000) + ' seconds.')), waitMs); }) : null;
  state.pending = (timeout ? Promise.race([Promise.resolve().then(load), timeout]) : Promise.resolve().then(load)).then(result => {
    const rows = loaderName === 'ARCHHUB_LOAD_HOSTS' ? result.hosts : result;
    const connectors = loaderName === 'ARCHHUB_LOAD_HOSTS' ? window.ARCHHUB_LIVE?.connectors : null;
    if (!Array.isArray(rows) || (loaderName === 'ARCHHUB_LOAD_HOSTS' &&
        (!Array.isArray(result.connectors) || !Array.isArray(connectors)))) {
      throw new Error('The catalogue response is invalid.');
    }
    items.splice(0, items.length, ...rows);
    state.read = true;
    if (loaderName === 'ARCHHUB_LOAD_SKILLS' && window.ARCHHUB_LIVE && window.ARCHHUB_LIVE.skills !== items) window.ARCHHUB_LIVE.skills = items;
    if (loaderName === 'ARCHHUB_LOAD_HOSTS') {
      window.ARCHHUB_HOSTS_READ = true;
      connectors.splice(0, connectors.length, ...result.connectors);
    }
  }).catch(error => {state.error = error.message || 'Catalogue unavailable.';})
    .finally(() => {if (timer !== null && typeof window.clearTimeout === 'function') window.clearTimeout(timer); state.loading = false; state.pending = null; catalogueChanged();});
  catalogueChanged();
  return state.pending;
};
const withLiveCatalogue = (loaderName, items, View) => props => {
  useCatalogueVersion();
  React.useEffect(() => {if (!catalogueStates.get(loaderName)?.read) loadCatalogue(loaderName, items);}, []);
  const status = catalogueStates.get(loaderName) || {loading:false, error:''};
  // One element: the Sidebar grid is "44px 1fr", so a loading line beside the panel would push the panel into the rail column.
  return <div style={{ display:'flex', flexDirection:'column', overflow:'hidden', minHeight:0 }}>
    {status.loading && !status.read && <p role="status" style={{ margin:0, padding:'8px 12px 0', fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft }}>Loading catalogue…</p>}
    {status.error && <p role="alert" style={{ margin:0, padding:'8px 12px 0', fontSize:12, color:LM.inkSoft }}>{status.error} <window.AH_DS.Btn onClick={() => loadCatalogue(loaderName, items)}>Retry</window.AH_DS.Btn></p>}
    <View {...props} catalogue={status}/>
  </div>;
};

const studioSkillLibraryItem = skill => ({
  id:'skill:' + (skill.id || skill.name || skill.path),
  title:skill.name || 'Skill',
  cat:'skill',
  engine:'skill',
  params:{skill:{
    id:skill.id || '',
    name:skill.name || '',
    source:skill.source || '',
    path:skill.path || '',
    description:skill.description || '',
  }},
});

const SkillsPanel = withLiveCatalogue('ARCHHUB_LOAD_SKILLS', LM_SAVED_SKILLS, ({ catalogue = {}, addNodeFromLibrary, onHome }) => (
  <div style={{ display:'flex', flexDirection:'column', overflow:'hidden', minHeight:0 }}>
    <PanelHead title="Skills">
      <span data-skills-count="" style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.08em' }}>
        {catalogue.read ? LM_SAVED_SKILLS.length + ' SAVED' : catalogue.error ? 'UNAVAILABLE' : 'READING\u2026'}</span>
      <PanelHomeButton onHome={onHome}/>
    </PanelHead>
    <Search ph="Search saved skills..."/>
    <div className="ah-scroll" style={{ flex:1, overflow:'auto', padding:'0 6px 8px' }}>
      {LM_SAVED_SKILLS.map((s, index) => (
        <window.AH_DS.Btn key={s.id || s.path || ((s.source || '') + ':' + (s.name || index))} type="button"
        data-skill-row="" aria-label={'Open skill ' + (s.name || 'Skill')} title={s.path || undefined} draggable="true" style={{
          display:'block', width:'100%', padding:'7px 9px', borderRadius:LM.rad.sm, cursor:'pointer', marginBottom:1,
          background:'transparent', border:'0', borderLeft:`2px solid transparent`, textAlign:'left', fontFamily:LM.sans,
        }}
        onClick={() => window.ArchHubStudioScreens && window.ArchHubStudioScreens.open('skill', s)}
        onKeyDown={e => { if ((e.key === 'Enter' || e.key === ' ') && window.ArchHubStudioScreens) { e.preventDefault(); window.ArchHubStudioScreens.open('skill', s); } }}
        onDragStart={e => e.dataTransfer.setData('application/x-lm-node', JSON.stringify(studioSkillLibraryItem(s)))}
        onMouseEnter={e => { e.currentTarget.style.background = LM.bgHover; e.currentTarget.style.borderLeftColor = LM.accent; }}
        onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.borderLeftColor = 'transparent'; }}>
          <div style={{ display:'flex', alignItems:'center', gap:7 }}>
            <span style={{ color:LM.accent, fontFamily:LM.mono, fontSize:11 }}>✦</span>
            <span style={{ flex:1, minWidth:0, fontSize:12.5, color:LM.ink, overflowWrap:'anywhere' }}>{s.name}</span>
            {s.source && <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft }}>{s.source}</span>}
          </div>
          {s.description && <div style={{ fontSize:11, color:LM.inkSoft, paddingLeft:18, marginTop:2, lineHeight:1.4,
            display:'-webkit-box', WebkitLineClamp:2, WebkitBoxOrient:'vertical', overflow:'hidden' }}>{s.description}</div>}
        </window.AH_DS.Btn>
      ))}
      {!LM_SAVED_SKILLS.length && catalogue.read && <div data-skills-empty="" role="status" style={{
        padding:'14px 10px', fontFamily:LM.serif, fontStyle:'italic', fontSize:13.5, color:LM.inkSoft, lineHeight:1.45 }}>
        No saved skills yet.
        <div style={{ fontFamily:LM.sans, fontStyle:'normal', fontSize:12, color:LM.inkSoft, marginTop:4 }}>
          Skills saved from finished work appear here, and Search counts the same list.</div>
      </div>}
    </div>
  </div>
));

const RunsPanel = ({ onHome, onOpenTask }) => {
  const hub = useToolHubProjection();
  const workshopState = useWorkshopProjection();
  const items = Array.isArray(hub?.waiting) ? hub.waiting : workshopWaitingItems(workshopState);
  return (
  <div style={{ display:'flex', flexDirection:'column', overflow:'hidden', minHeight:0 }}>
    <div style={{ padding:'12px 12px 10px', display:'flex', alignItems:'center', gap:LM.sp.sm }}>
      <span style={{ fontFamily:LM.sans, fontSize:14, fontWeight:600, color:LM.ink }}>Runs</span>
      <span data-runs-count="" style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.08em' }}>
        {items.length ? items.length + ' WAITING' : 'NONE WAITING'}</span>
      <div style={window.AH_DS.styles.fill}/>
      <PanelHomeButton onHome={onHome}/>
    </div>
    <div className="ah-scroll" style={{ flex:1, overflow:'auto', padding:'0 6px 8px' }}>
      {items.map((item, index) => (
        <window.AH_DS.Btn key={item.id || item.label || index} type="button" data-run-waiting-row="" onClick={() => onOpenTask && onOpenTask(item)} style={{
          display:'block', width:'100%', padding:'7px 9px', borderRadius:LM.rad.sm, cursor:'pointer', marginBottom:1,
          background:'transparent', border:'0', borderLeft:`2px solid transparent`, textAlign:'left', fontFamily:LM.sans,
        }}
        onMouseEnter={e => { e.currentTarget.style.background = LM.bgHover; e.currentTarget.style.borderLeftColor = LM.warn; }}
        onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.borderLeftColor = 'transparent'; }}>
          <div style={{ display:'flex', alignItems:'center', gap:7 }}>
            <span style={{ color:LM.warn, fontFamily:LM.mono, fontSize:11 }}>▶</span>
            <span style={{ flex:1, minWidth:0, fontSize:12.5, color:LM.ink, overflowWrap:'anywhere' }}>{waitingLine(item)}</span>
          </div>
          <div style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, paddingLeft:18, marginTop:3 }}>{waitingMeta(item)}</div>
        </window.AH_DS.Btn>
      ))}
      {!items.length && <div data-runs-empty="" role="status" style={{
        padding:'14px 10px', fontFamily:LM.sans, fontSize:13, color:LM.inkSoft, lineHeight:1.45 }}>
        Nothing waiting.</div>}
    </div>
  </div>
  );
};

// ─── Global search panel ───
const SearchPanel = ({ onHome }) => {
  useCatalogueVersion();
  React.useEffect(() => {
    if (!catalogueStates.get('ARCHHUB_LOAD_SKILLS')?.read) loadCatalogue('ARCHHUB_LOAD_SKILLS', LM_SAVED_SKILLS);
  }, []);
  // Scope counts are read from what this Studio holds; a scope nothing counts draws no number.
  const projected = useStudioProjection();
  const live = window.ARCHHUB_LIVE || {};
  const count = list => Array.isArray(list) ? list.length : null;
  return (
  <div style={{ display:'flex', flexDirection:'column', overflow:'hidden', minHeight:0 }}>
    <PanelHead title="Search">
      <PanelHomeButton onHome={onHome}/>
      <kbd style={kbd()}>⌘K</kbd>
    </PanelHead>
    <Search ph="Search everything..."/>
    <div style={{ padding:'4px 10px', fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.14em' }}>SCOPES</div>
    <div style={{ padding:'0 6px', display:'flex', flexDirection:'column', gap:1 }}>
      {[
        ['chats',  'sessions + messages',  count(LM_SESSIONS)],
        ['nodes',  'in current graph',     count(projected?.graph?.nodes || live.graph?.nodes)],
        ['skills', 'saved templates',      count(live.skills)],
        ['memory', 'what the brain governs', count(live.memory)],
        ['files',  'Revit / Rhino / Speckle', null],
        ['hosts',  'connectors',           count(live.connectors)],
      ].map(([k, sub, n]) => (
        <window.AH_DS.Btn key={k} style={{
          padding:'6px 10px', borderRadius:LM.rad.sm, background:'transparent', border:0,
          cursor:'pointer', textAlign:'left',
          display:'flex', alignItems:'center', gap:LM.sp.sm,
        }}
        onMouseEnter={e => e.currentTarget.style.background = LM.bgHover}
        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
          <span style={{ fontFamily:LM.mono, fontSize:11, color:LM.ink, width:54 }}>{k}</span>
          <span style={{ flex:1, fontSize:11, color:LM.inkSoft }}>{sub}</span>
          {n != null && <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft }}>{n}</span>}
        </window.AH_DS.Btn>
      ))}
    </div>
  </div>
  );
};

const kbd = () => ({
  fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, padding:'1px 5px', background:LM.bgSoft,
  border:`1px solid ${LM.lineHair}`, borderRadius:LM.rad.xs, color:LM.inkSoft, letterSpacing:'0.06em',
});

// ──────────────────────── HOME · DSYS-082 ────────────────────────
const homeMissionProjection = (state, hub, sessions = LM_SESSIONS, hosts = LM_HOSTS) => {
  const approvals = new Map(), agents = new Map(), members = new Map(), results = new Map(), inFlight = new Map();
  const descriptors = state?.workshops || [];
  const project = window.ARCHHUB_WORKSHOP_MODEL;
  for (const descriptor of descriptors) {
    if (typeof project !== 'function') continue;
    const page = state?.workshopPages?.find(row => row.root === descriptor.root) ||
      (state?.workshop?.root === descriptor.root && !state.workshop.page_before && (!state.workshop.feed || state.workshop.feed === 'all') ? state.workshop : null);
    const participants = [...(page?.participants || [])];
    for (const contact of state?.nativeContacts?.[descriptor.root] || []) {
      if (!participants.some(row => row.root === contact.root)) participants.push({...contact,is_agent:true,attached:contact.connected === true});
    }
    const view = {...state,workshop:page ? {...page,participants} : null};
    const model = project({state:view, descriptor});
    for (const task of model.tasks || []) {
      const selected = project({state:view, descriptor, selected:task.work});
      if (selected.approval) approvals.set(selected.approval.work || selected.approval.id,
        {...selected.approval, home_root:descriptor.root, home_native:selected.native});
      const ownsTask = task.workflow || task.proposal || page?.assignments?.some(row=>row.work===task.work) ||
        (state?.nativeWork?.root===descriptor.root && state.nativeWork.work===task.work) ||
        page?.messages?.some(row=>String(row.text || row.content || (typeof row.body==='string' ? row.body : row.body?.text) || '').includes(task.work));
      if (['run','running','working','claimed','executing','review','submitted','needs-user','needs_user','awaiting_approval','block','blocked'].includes(String(task.state || task.nodeStatus)))
        inFlight.set(task.work,{...task,home_root:ownsTask ? descriptor.root : inFlight.get(task.work)?.home_root});
      if (['done','completed','settled','published','failed','error'].includes(String(task.state || task.nodeStatus))) {
        results.set(task.work, {...task, home_root:ownsTask ? descriptor.root : results.get(task.work)?.home_root});
      }
    }
    if (model.approval) approvals.set(model.approval.work || model.approval.id,
      {...model.approval, home_root:descriptor.root, home_native:model.native});
    for (const member of model.members || []) {
      members.set(member.id, member);
      const active = (model.tasks || []).filter(task => task.owner === member.id &&
        !['done','completed','settled','published','failed','error','archived','planned','open','queued'].includes(task.state));
      const working = ['working','run','running','executing'].includes(member.state || member.liveState);
      if (!active.length && !working) continue;
      const task = active[0], node = (state?.topology?.graph?.nodes || []).find(row => row.id === task?.work);
      const progress = member.progress ?? task?.progress ?? node?.progress;
      agents.set(member.id, {...member, task, home_root:descriptor.root, working,
        progress:Number.isFinite(progress) ? Math.max(0,Math.min(100,progress)) : null});
    }
  }
  for (const item of hub?.waiting || []) {
    const key = item.work || item.id;
    const held = approvals.get(key);
    approvals.set(key, {...held, ...item, id:held?.id || item.id, kind:held?.kind || item.producer,
      title:held?.title || item.summary, state:'needs-user', home_root:item.root || held?.home_root,
      home_native:held?.home_native, rows:held?.rows || item.changes || item.approval_rows || []});
  }
  const liveAgents = [...agents.values()];
  return {approvals:[...approvals.values()], agents:liveAgents, members:[...members.values()], inFlight:[...inFlight.values()],
    results:[...results.values()].sort((a,b) => String(b.completed_at || b.done_at || b.updated_at || '').localeCompare(String(a.completed_at || a.done_at || a.updated_at || ''))),
    hosts:hosts.filter(Boolean), baboom:(hub?.tools || []).find(row => row.id === 'baboom') || null,
    unavailable:Object.keys(state?.workshopErrors || {}).length > 0 || !!state?.workshop?.error || !!state?.error,
    loading:descriptors.some(row=>!state?.workshopPages?.some(page=>page.root===row.root) && state?.workshop?.root!==row.root && !state?.workshopErrors?.[row.root]),
    counts:{needs:approvals.size, programs:hosts.filter(Boolean).length, sessions:sessions.length,
      running:liveAgents.filter(row => row.working).length}};
};
const homeDecisionAvailable = (card, owner, choice) => {
  if (choice === 'approve' && Number.isFinite(card.home_native?.review_expires_at) && card.home_native.review_expires_at <= Date.now()/1000) return false;
  if (card.kind === 'native' || card.producer === 'workshop_gate') return choice === 'approve'
    ? !!card.input_digest && typeof owner?.approveNativeWork === 'function'
    : (card.mode || card.home_native?.mode) === 'agent' && typeof owner?.nativeWorkAction === 'function';
  if (card.kind === 'workflow') return choice === 'approve' && !!card.workflow?.digest && typeof owner?.workshopWorkflow === 'function';
  if (card.kind === 'proposal') return typeof owner?.readWorkProposals === 'function' &&
    typeof owner?.[choice === 'approve' ? 'bindWorkProposals' : 'declineWorkProposals'] === 'function';
  return card.producer === 'social_approve' && typeof owner?.decideSocialApproval === 'function';
};
const decideHomeApproval = async (card, choice) => {
  const owner = window.ARCHHUB_EXISTING_WORKSHOP;
  if (!homeDecisionAvailable(card,owner,choice)) throw new Error('This decision is unavailable.');
  if (card.kind === 'native' || card.producer === 'workshop_gate') {
    if (choice === 'approve') await owner.approveNativeWork(card.home_root,card.input_digest);
    else await owner.nativeWorkAction(card.home_root,'stop_native',card.work);
  } else if (card.kind === 'workflow') {
    const details = {workflow:card.workflow.root,digest:card.workflow.digest};
    const approved = await owner.workshopWorkflow(card.home_root,'workflow-approve',details);
    if (approved?.navigation_current === false) return {accepted:true,warning:'Approval recorded in the previous workspace. Publication was not started.'};
    if (card.package?.available) {
      try { const receipt = await owner.workshopWorkflow(card.home_root,'workflow-execute',{workflow:card.workflow.root});
        if (receipt?.ok !== true || Object.keys(receipt.pending || {}).length || !receipt.publication?.receipt ||
            receipt.publication.destination !== card.package.destination || receipt.publication.files?.length !== card.package.sheets.length)
          throw new Error(receipt?.error || 'The publication receipt did not confirm success.'); }
      catch (error) { return {accepted:true,warning:'Approval recorded. Publication is not confirmed; open Workshop to reconcile. ' + (error?.message || '')}; }
    }
  }
  else if (card.kind === 'proposal') {
    const message = card.proposal.decision?.find(row => row.action === (choice === 'approve' ? 'approve-proposal' : 'decline-proposal'))?.message;
    const row = (await owner.readWorkProposals(card.home_root)).rows.find(item => item.message_id === message);
    if (!row || row.problem) throw new Error(row?.problem || 'Refresh this proposal before deciding.');
    if (choice === 'approve') { if (!row.work_root) await owner.bindWorkProposals(card.home_root,[row]); }
    else await owner.declineWorkProposals(card.home_root,[row]);
  } else await owner.decideSocialApproval({delegation:card.delegation,input_digest:card.input_digest,
    decision:choice === 'approve' ? 'approve' : 'deny'});
  // An accepted decision is never replayed if its subsequent read fails.
  try { await owner.refreshTopologyCanvas?.(); } catch (_) {}
  try { if (card.home_root) await owner.refreshWorkshop?.(card.home_root); } catch (_) {}
  await requestToolHubRefresh();
};

const Home = ({ onOpen, sessions = LM_SESSIONS, model, native, readiness = null, onModelReadRetry, setPickerOpen, setLibraryOpen, setPanel, onOpenTool, onOpenToolGraph, workshopState, account,
  onStarted, sessionError = '', beginNavigation, isNavigationCurrent }) => {
  const [draft, setDraft] = React.useState('');
  const [attachments, setAttachments] = React.useState([]);
  const [attachmentError, setAttachmentError] = React.useState('');
  const [hostMenuOpen, setHostMenuOpen] = React.useState(false);
  const [composerToolsOpen,setComposerToolsOpen] = React.useState(false);
  const fileInputRef = React.useRef(null);
  const [starting, setStarting] = React.useState(false);
  const [startError, setStartError] = React.useState('');
  const startBusy = React.useRef(false), acceptedSession = React.useRef(null);
  const homeMounted = React.useRef(true);
  const hub = useToolHubProjection();
  const blocked = !native ? routeReadiness(modelRoute(model), readiness, model?.pending === true) : null;
  const offers = new Set((blocked && blocked.actions) || []);
  React.useEffect(() => {homeMounted.current = true; return () => {homeMounted.current = false;};}, []);
  const liveHosts = LM_HOSTS.filter(host => hostState(host) === 'connected');
  const knownHosts = startableHosts(LM_HOSTS);
  const attachFiles = async event => {
    const picked = Array.from(event.target.files || []).slice(0, 4);
    event.target.value = '';
    if (!picked.length) return;
    setAttachmentError('');
    try {
      const rows = [];
      for (const file of picked) {
        if (file.size > 65536) throw new Error(file.name + ' is over the 64 KiB attachment limit.');
        rows.push({name:file.name, size:file.size, type:file.type || 'application/octet-stream',
          content:await file.text()});
      }
      setAttachments(old => [...old, ...rows].slice(0, 4));
    } catch (error) {
      setAttachmentError(error?.message || 'The file could not be attached.');
    }
  };
  const appendDraftToken = token => {
    setDraft(text => {
      const trimmed = text.replace(/\s+$/,'');
      return (trimmed ? trimmed + ' ' : '') + token + ' ';
    });
  };
  const startKnownHost = async host => {
    const phrase = hostOpenPhrase(host);
    if (!phrase) return;
    setHostMenuOpen(false);
    if (typeof window.ARCHHUB_AGENT !== 'function') {
      setStartError('Host start is unavailable in this application view.');
      return;
    }
    setStartError('');
    try { await window.ARCHHUB_AGENT(phrase); }
    catch (error) { setStartError(error?.message || 'Host start was refused.'); }
  };
  const startPrompt = () => {
    if (!attachments.length) return draft.trim();
    const block = attachments.map(file => [
      'File: ' + file.name,
      'Type: ' + file.type,
      'Bytes: ' + file.size,
      file.content,
    ].join('\n')).join('\n\n');
    return draft.trim() + '\n\nAttached files:\n' + block;
  };
  const startSession = async event => {
    event.preventDefault();
    const prompt = startPrompt();
    if (!draft.trim() || startBusy.current) return;
    if (prompt.length > 12000) { setStartError('The request and attachments exceed the session start limit.'); return; }
    if (!native && !modelRoute(model)) {
      setStartError('Choose a model before sending. Your text is still here.');
      return;
    }
    startBusy.current = true; setStarting(true); setStartError('');
    try {
      const owner = window.ARCHHUB_EXISTING_WORKSHOP;
      if (!owner?.startSession) throw new Error('Session creation is unavailable in this application view.');
      const details = {prompt, ...(native ? {native:{app:native.app,session_id:native.session_id}} : {model:modelRoute(model)})};
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
      setAttachments([]);
    } catch (error) {
      setStartError(error?.message || 'The session could not be confirmed. Your text is still here.');
    } finally { startBusy.current = false; setStarting(false); }
  };

  const mission = homeMissionProjection(workshopState,hub,sessions);
  const [templateView,setTemplateView] = React.useState({identity:null,rows:[]}), [templateError,setTemplateError] = React.useState('');
  const [startingTemplate,setStartingTemplate] = React.useState(null);
  const [templateAttempt,setTemplateAttempt] = React.useState(0);
  const [editingTemplate,setEditingTemplate] = React.useState(null);
  const templateBusy = React.useRef(false);
  const identity = JSON.stringify([workshopState?.canvas?.graph_id,workshopState?.canvas?.root,
    (workshopState?.topology?.canvas || workshopState?.canvas)?.authorization?.subject,(workshopState?.topology?.canvas || workshopState?.canvas)?.authorization?.session]);
  const templates = templateView.identity === identity ? templateView.rows : [];
  const editTemplate = async (template, change) => {
    if (templateBusy.current) return;
    templateBusy.current=true;setStartingTemplate(template.id);setTemplateError('');
    const viewIdentity=()=>{const state=window.ARCHHUB_EXISTING_WORKSHOP?.getSnapshot?.();const canvas=state?.topology?.canvas || state?.canvas;return JSON.stringify([canvas?.application_root || canvas?.graph_id,canvas?.scope?.current || canvas?.root,canvas?.authorization?.subject,canvas?.authorization?.session]);};
    const startedView=viewIdentity(), owner=window.ARCHHUB_EXISTING_WORKSHOP;
    try {
      if(typeof owner?.editHomeTemplate !== 'function') throw new Error('Template editing is unavailable.');
      await owner.editHomeTemplate(template.id,change);
      const result=await owner.readHomeTemplates();
      if(homeMounted.current && viewIdentity()===startedView){setTemplateView({identity,rows:result.templates});setEditingTemplate(null);}
    }catch(error){if(homeMounted.current && viewIdentity()===startedView)setTemplateError(error?.message || 'Template edit was not confirmed.');}
    finally{templateBusy.current=false;if(homeMounted.current)setStartingTemplate(null);}
  };
  React.useEffect(() => {
    Promise.resolve(window.ARCHHUB_EXISTING_WORKSHOP?.refreshHomeWorkshops?.()).catch(() => {});
  },[identity,workshopState?.topology?.canvas?.revision || workshopState?.canvas?.revision,
    JSON.stringify((workshopState?.workshops || []).map(row=>row.root))]);
  React.useEffect(() => {
    let active = true;
    setTemplateError('');setTemplateView({identity:null,rows:[]});
    const owner = window.ARCHHUB_EXISTING_WORKSHOP;
    if (typeof owner?.readHomeTemplates === 'function') owner.readHomeTemplates().then(result => {
      if (active) setTemplateView({identity,rows:(result?.templates || []).filter(row => row.child_count > 0)
        .sort((a,b) => b.run_count - a.run_count || (b.scenario_frequency || 0) - (a.scenario_frequency || 0))});
    }).catch(error => {if(active) setTemplateError(error?.message || 'Templates unavailable');});
    return () => {active = false;};
  },[identity,workshopState?.topology?.canvas?.revision || workshopState?.canvas?.revision,templateAttempt]);
  const startTemplate = async template => {
    if (templateBusy.current) return;
    templateBusy.current = true; setStartingTemplate(template.id); setTemplateError('');
    const owner = window.ARCHHUB_EXISTING_WORKSHOP;
    try {
      if (typeof owner?.startHomeTemplate !== 'function') throw new Error('Template start is unavailable.');
      const generation = beginNavigation?.();
      const result = await owner.startHomeTemplate(template.id);
      if (isNavigationCurrent?.(generation) === false) return;
      if (!homeMounted.current || result.navigation_current === false) return;
      onOpen?.(workshopState?.canvas?.graph_id);
    } catch(error) {if(homeMounted.current) setTemplateError((error?.message || 'Start was not confirmed.') + ' Refresh the canvas before starting again.');}
    finally {templateBusy.current = false;if(homeMounted.current)setStartingTemplate(null);}
  };
  const [reviewedCard,setReviewedCard] = React.useState(null), [decisionStatus,setDecisionStatus] = React.useState(null);
  const card = reviewedCard?.identity === identity ? reviewedCard.card : mission.approvals.find(row=>row.package?.available) || mission.approvals[0];
  const decide = async choice => {
    setReviewedCard({identity,card});
    try {
      const receipt = await decideHomeApproval(card,choice);
      if(homeMounted.current) {setDecisionStatus({identity,text:receipt?.warning || (card.package ? 'Package issued.' : 'Decision recorded.'),warning:!!receipt?.warning});setReviewedCard(null);}
      return receipt;
    } catch(error) {setReviewedCard(null);throw error;}
  };
  const ApprovalCard = window.ARCHHUB_APPROVAL_CARD;
  const openWork = row => row.home_root ? onOpenTool?.('workshop',{window:true,root:row.home_root,focus:row.work || row.id}) : onOpen?.(workshopState?.canvas?.graph_id);
  const action = window.AH_DS.styles.workshopButton(false,true);
  return (
  <window.AH_DS.Frame as="main" className="ah-scroll" data-home-page="" data-home-design="082" style={{
    height:'100%',boxSizing:'border-box',overflow:'auto',minHeight:0,minWidth:0,
    padding:'26px 40px 22px',display:'flex',flexDirection:'column',gap:22,
    background:'radial-gradient(1200px 500px at 30% -10%, #1a1a22 0%, #0c0c0f 60%)',
  }}>
    <header style={{display:'flex',alignItems:'center',gap:14}}>
      <div><h1 data-home-heading="" style={{fontSize:24,lineHeight:1.3,fontWeight:700,margin:0}}>{mission.loading ? 'Reading your agents’ work…' : mission.unavailable && !mission.inFlight.length ? 'Workshop updates unavailable' : mission.inFlight.length
        ? `Your agents are finishing ${mission.inFlight.length} ${mission.inFlight.length===1?'thing':'things'} for you` : 'No tasks in flight'}</h1>
        <div style={{fontSize:13.5,color:LM.inkSoft,marginTop:4}}>{mission.unavailable ? 'Some Workshop updates are unavailable' :
          `${mission.approvals.length ? mission.approvals.length + ' needs your OK' : 'Nothing needs you'} · ${mission.agents.filter(row=>row.working).length} working`}</div></div>
      <span style={window.AH_DS.styles.fill}/>{mission.agents.length > 0 && <window.AH_DS.Card variant="home" data-home-presence="" style={{display:'flex',alignItems:'center',gap:10,padding:'8px 12px',fontSize:13}}>
        {mission.agents.slice(0,3).map(row=><span key={row.id} title={row.name}><window.AH_DS.Avatar agent={row} size={22} ring={row.working?LM.accent:null}/></span>)}
        <span style={window.AH_DS.styles.muted}>{mission.agents.filter(row=>row.working).length} working</span></window.AH_DS.Card>}
    </header>
    <section data-home-results="" aria-label="Your agents' work" style={{display:'grid',gridTemplateColumns:'minmax(0,1.45fr) minmax(0,1fr)',gap:16}}>
      <div style={{minWidth:0}}>{card ? <ApprovalCard key={card.id + ':' + (card.input_digest || card.workflow?.digest || '')} approval={card}
        surface="home" variant={card.package ? 'set-approve' : undefined} approveLabel={card.package ? 'Approve and issue' : 'Approve'}
        canApprove={homeDecisionAvailable(card,window.ARCHHUB_EXISTING_WORKSHOP,'approve')}
        canDecline={homeDecisionAvailable(card,window.ARCHHUB_EXISTING_WORKSHOP,'decline')}
        onApprove={()=>decide('approve')} onDecline={()=>decide('decline')}/>
        : null}
        {decisionStatus?.identity===identity && <div data-home-decision-receipt="" role={decisionStatus.warning ? 'alert' : 'status'} style={{fontSize:13,color:decisionStatus.warning ? LM.warn : LM.ok,marginTop:12}}>{decisionStatus.text}</div>}
        {mission.approvals.length > 1 && <window.AH_DS.Btn type="button" title="More approvals · Ctrl+K" onClick={()=>openWork(card)} style={{...action,marginTop:10}}>View {mission.approvals.length - 1} more in Workshop</window.AH_DS.Btn>}</div>
      <div style={{display:'grid',gap:12,alignContent:'start',minWidth:0}}>
        {mission.results.slice(0,2).map(row=><window.AH_DS.Card as="article" variant="home" key={row.work} data-home-result={row.work} style={{padding:14,display:'grid',gridTemplateColumns:'30px minmax(0,1fr) auto',gap:12,alignItems:'center'}}>
          <window.AH_DS.Avatar agent={mission.members.find(agent=>agent.id===row.owner) || {name:row.owner_name}} size={30}/><div><div style={{fontSize:14.5,fontWeight:700}}>{row.title}</div>
          <div style={{fontSize:12.5,color:LM.inkSoft,marginTop:2}}>{row.result_summary || row.latest?.text || row.state}</div></div>
          <window.AH_DS.Btn type="button" title="Open result · Ctrl+K" onClick={()=>openWork(row)} style={action}>Open result</window.AH_DS.Btn></window.AH_DS.Card>)}
        {mission.inFlight.filter(row=>!mission.approvals.some(a=>a.work===row.work)).slice(0,1).map(row=><window.AH_DS.Btn key={row.work} type="button" data-home-finishing={row.work}
          title="Open work · Ctrl+K" onClick={()=>openWork(row)} style={{...action,height:'auto',textAlign:'left',borderStyle:'dashed',background:'transparent',padding:'12px 14px',fontWeight:400,color:LM.inkSoft}}>{row.title} · {row.state}</window.AH_DS.Btn>)}
      </div>
      {!card && !mission.results.length && !mission.inFlight.length && <window.AH_DS.EmptyState data-home-work-state="" compact glyph={null}
        error={mission.unavailable} title={mission.loading ? 'Reading your agents’ work…' : mission.unavailable ? 'Workshop updates unavailable' : 'What should the agents do?'}
        detail={mission.loading ? 'Your work appears here as soon as it answers.' : mission.unavailable ? 'Read your work again to continue.' : 'Start a task below. Results and approvals will appear here.'}
        onRetry={mission.unavailable ? ()=>window.ARCHHUB_EXISTING_WORKSHOP?.refreshHomeWorkshops?.() : undefined} style={{gridColumn:'1 / -1'}}/>}
    </section>
    <section data-home-templates="" style={{display:'grid',gap:12,alignContent:'start'}}>
      <div style={{display:'flex',alignItems:'baseline',gap:10}}><h2 style={{fontSize:16,fontWeight:700,margin:0}}>Start something</h2>
        <span style={{fontSize:13,color:LM.inkSoft}}>your most-run work, one click · each is a node you can open</span></div>
      <window.AH_DS.EmptyState compact glyph={null} error={!!templateError} title={templateError ? "Templates unavailable" : "Reading templates…"} detail={templateError} onRetry={()=>setTemplateAttempt(value=>value+1)} style={{display:templateError || templateView.identity!==identity ? undefined : 'none'}}/>
      <div style={{display:'grid',gridTemplateColumns:'repeat(3, minmax(0,1fr))',gap:12}}>
        {templates.map(template=><window.AH_DS.Card as="article" variant="home" key={template.id} data-home-template={template.id} style={{padding:14,display:'grid',gap:10}}>
          <div style={{display:'flex',alignItems:'baseline',gap:8}}><window.AH_DS.Btn kind="ghost" data-template-edit={template.id} disabled={startingTemplate!==null}
              title={'Open '+template.title+' · Ctrl+K'} aria-expanded={editingTemplate?.id===template.id && editingTemplate?.identity===identity}
              onClick={()=>setEditingTemplate(editingTemplate?.id===template.id?null:{...template,identity,children:template.children.map(child=>({...child,params:{...child.params}}))})}
              style={{padding:0,height:'auto',fontSize:14.5,fontWeight:700,flex:1,justifyContent:'flex-start'}}>{template.title}</window.AH_DS.Btn><span data-template-runs="" style={{fontSize:12,color:LM.inkSoft}}>{template.run_count > 0 ? `ran ${template.run_count}×` : null}</span></div>
          <div style={{display:'flex',alignItems:'center',gap:4,overflow:'hidden',whiteSpace:'nowrap'}}>{template.children.slice(0,4).map((child,index)=><React.Fragment key={child.id || index}>
            {index > 0 && <i style={{width:10,height:2,background:LM.accent,opacity:.6,flex:'none'}}/>}<span style={{height:24,padding:'0 8px',borderRadius:6,background:LM.bgHover,fontSize:12,display:'inline-flex',alignItems:'center'}}>{child.title || child.engine}</span></React.Fragment>)}
            {template.child_count > 4 && <span style={{fontSize:12,color:LM.inkSoft}}>+{template.child_count - 4}</span>}</div>
          <div style={window.AH_DS.styles.flex}><span style={{fontSize:12.5,color:LM.inkSoft,flex:1}}>{template.sub || `${template.child_count} steps`}</span>
            <window.AH_DS.Btn type="button" data-template-start={template.id} disabled={startingTemplate !== null} title={'Start '+template.title+' · Ctrl+K'} onClick={()=>startTemplate(template)} style={action}>{startingTemplate===template.id ? 'Starting…' : 'Start'}</window.AH_DS.Btn></div>
          {editingTemplate?.id===template.id && editingTemplate.identity===identity && <form data-template-editor="" onSubmit={event=>{event.preventDefault();editTemplate(template,{update:{title:editingTemplate.title,children:editingTemplate.children}});}}
            onKeyDown={event=>{if(event.key==='Escape')setEditingTemplate(null);}} style={{display:'grid',gap:8}}>
            <label style={{fontSize:12,display:'grid',gap:4}}>Template name<window.AH_DS.TextField aria-label="Template name" style={{background:LM.bgPanel,color:LM.ink,border:`1px solid ${LM.line}`,borderRadius:6,padding:7,fontFamily:LM.sans}} value={editingTemplate.title} onChange={event=>setEditingTemplate({...editingTemplate,title:event.target.value})}/></label>
            {editingTemplate.children.map((child,index)=><fieldset key={index} style={{border:`1px solid ${LM.line}`,borderRadius:6,display:'grid',gap:6}}><legend>{child.title}</legend>
              {Object.entries(child.params).map(([name,value])=><label key={name} style={{fontSize:12,display:'grid',gap:4}}>{name.replaceAll('_',' ')}<window.AH_DS.TextField aria-label={child.title+' '+name} style={{background:LM.bgPanel,color:LM.ink,border:`1px solid ${LM.line}`,borderRadius:6,padding:7,fontFamily:LM.sans}} value={value}
                onChange={event=>setEditingTemplate({...editingTemplate,children:editingTemplate.children.map((row,i)=>i===index ? {...row,params:{...row.params,[name]:event.target.value}} : row)})}/></label>)}</fieldset>)}
            <div style={{display:'flex',gap:8}}><window.AH_DS.Btn type="submit" disabled={startingTemplate!==null} title="Save template · Ctrl+K / Enter" style={action}>Save</window.AH_DS.Btn>
              <window.AH_DS.Btn type="button" disabled={startingTemplate!==null} title="Delete template · Ctrl+K" data-template-delete={template.id} onClick={()=>editTemplate(template,{delete:true})} style={action}>Delete</window.AH_DS.Btn>
              <window.AH_DS.Btn type="button" onClick={()=>setEditingTemplate(null)} title="Cancel · Ctrl+K / Escape" style={action}>Cancel</window.AH_DS.Btn></div>
          </form>}
        </window.AH_DS.Card>)}
      </div>{!templates.length && !templateError && templateView.identity===identity && <window.AH_DS.EmptyState compact glyph={null} title="No saved composite templates."/>}
    </section>
    <div data-home-composer="" style={{marginTop:'auto',alignSelf:'center',width:'min(100%, 850px)'}}>
    {blocked && <div data-home-model-state="" role="status" style={{
      background:LM.bgPanel, border:`1px solid ${LM.line}`, borderLeft:`3px solid ${LM.warn}`,
      borderRadius:LM.rad.md, padding:'9px 10px', marginTop:12, display:'flex', alignItems:'center', gap:10, flexWrap:'wrap',
    }}>
      <span style={{ fontFamily:LM.mono, fontSize:11, color:LM.warn, letterSpacing:'0.14em' }}>
        {READINESS_LABELS[blocked.state] || 'NO MODEL'}</span>
      <span style={{ fontSize:12.5, lineHeight:1.45, color:LM.ink, flex:'1 1 240px' }}>{blocked.message}</span>
      {offers.has('retry_models') && <window.AH_DS.Btn type="button" onClick={() => typeof onModelReadRetry === 'function' && onModelReadRetry()} style={{
        padding:'4px 9px', background:'transparent', color:LM.ink, border:`1px solid ${LM.line}`,
        borderRadius:LM.rad.sm, fontSize:11.5, fontWeight:500, cursor:'pointer' }}>Retry</window.AH_DS.Btn>}
      {offers.has('choose_model') && <window.AH_DS.Btn type="button" onClick={() => typeof setPickerOpen === 'function' && setPickerOpen(true)} style={{
        padding:'4px 9px', background:'transparent', color:LM.ink, border:`1px solid ${LM.line}`,
        borderRadius:LM.rad.sm, fontSize:11.5, fontWeight:500, cursor:'pointer' }}>Choose a model</window.AH_DS.Btn>}
    </div>}
    <window.AH_DS.Composer as="form" variant="home" onSubmit={startSession} style={{marginTop:10}}>
      <div style={{ display:'flex', alignItems:'center', gap:10 }}>
        <ModelStrip compact inline model={native ? {...model,name:native.title || native.app,vendor:native.app} : model} setPickerOpen={setPickerOpen}/>
        <div style={{flex:1,minWidth:0,position:'relative',paddingRight:26}}>
          <window.AH_DS.TextField multiline aria-label="Start a new session" placeholder={'Ask for anything, or @ an agent…'} className="lm-home-draft"
            value={draft} onChange={event => setDraft(event.target.value)} disabled={starting}
            onKeyDown={event => {if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent?.isComposing) startSession(event);}}
            rows={1} maxLength={12000} style={{width:'100%', boxSizing:'border-box', resize:'none', display:'block',
              background:'transparent', border:0, outline:'none', color:LM.ink, fontFamily:LM.sans, fontSize:15,
              letterSpacing:'-0.01em', lineHeight:1.4, padding:'2px 0'}}/>
          <div style={{position:'absolute',right:0,top:0}}>
            <window.AH_DS.Btn sm kind="ghost" aria-label="More composer actions" title="More actions · Ctrl+K" aria-expanded={composerToolsOpen} onClick={()=>setComposerToolsOpen(value=>!value)}>+</window.AH_DS.Btn>
            <div hidden={!composerToolsOpen} data-home-composer-actions="" style={{position:'absolute',bottom:32,right:0,zIndex:10,background:LM.bgPanel,border:`1px solid ${LM.line}`,borderRadius:8,padding:8,whiteSpace:'nowrap'}}>
            <HomeChip mono onClick={() => setLibraryOpen(true)}>/ node</HomeChip>
            <HomeChip mono onClick={() => setPanel('skills')}>@ skill</HomeChip>
            <HomeChip mono onClick={() => setHostMenuOpen(open => !open)}># host</HomeChip>
            <HomeChip onClick={() => fileInputRef.current?.click()}>+ attach</HomeChip>
            <input ref={fileInputRef} aria-label="Attach file to new session" type="file" multiple
              onChange={attachFiles} style={{display:'none'}}/>
            {hostMenuOpen && <div role="menu" style={{
              position:'absolute', zIndex:4, top:'100%', left:0, marginTop:6,
              background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.sm,
              padding:4, minWidth:190, boxShadow:'0 12px 24px rgba(0,0,0,.22)',
            }}>
              {liveHosts.length > 0 ? liveHosts.map(host => <window.AH_DS.Btn key={host.id || host.name} type="button" role="menuitem"
                onClick={() => { appendDraftToken('#' + host.name); setHostMenuOpen(false); }}
                style={{display:'block', width:'100%', textAlign:'left', padding:'5px 8px',
                  background:'transparent', border:0, color:LM.ink, fontFamily:LM.sans,
                  fontSize:12, cursor:'pointer'}}>{host.name}</window.AH_DS.Btn>) :
                knownHosts.map(host => <window.AH_DS.Btn key={hostStartName(host)} type="button" role="menuitem"
                  onClick={() => startKnownHost(host)}
                  style={{display:'flex', width:'100%', alignItems:'center', justifyContent:'space-between', gap:14,
                    textAlign:'left', padding:'5px 8px', background:'transparent', border:0,
                    color:LM.ink, fontFamily:LM.sans, fontSize:12, cursor:'pointer'}}>
                  <span>{hostDisplayName(host)}</span>
                  <span style={{fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.accent, letterSpacing:'0.06em', textTransform:'uppercase'}}>Start</span>
                </window.AH_DS.Btn>)}
            </div>}
            </div>{attachments.map(file => <Chip key={file.name + ':' + file.size} mono>{file.name}</Chip>)}
          </div>
        </div>
        <span style={{fontSize:11,border:`1px solid ${LM.line}`,borderRadius:4,padding:'1px 5px',color:LM.inkSoft}}>Ctrl K</span>
        <window.AH_DS.Btn sm kind="ghost" disabled title="Voice input is unavailable in this connection" aria-label="Voice input"><Icon name="mic" size={14}/></window.AH_DS.Btn>
        <window.AH_DS.Btn variant="workshop" sm type="submit" disabled={starting || !draft.trim()}>
          {starting ? 'Starting\u2026' : 'Send'}
        </window.AH_DS.Btn>
      </div>
      {startError && <p role="alert" style={{color:LM.warn,marginBottom:0}}>{startError}</p>}
      {attachmentError && <p role="alert" style={{color:LM.warn,marginBottom:0}}>{attachmentError}</p>}
    </window.AH_DS.Composer>
    </div>
    {sessionError && <p role="alert" style={{color:LM.warn,margin:0}}>{sessionError} <window.AH_DS.Btn type="button" onClick={()=>window.location.reload()}>Refresh graphs</window.AH_DS.Btn></p>}
  </window.AH_DS.Frame>
  );
};

const Chip = ({ children, mono }) => (
  <span style={{
    display:'inline-flex', alignItems:'center', gap:5, padding:'3px 9px',
    background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.sm,
    color:LM.inkSoft, fontFamily: mono ? LM.mono : LM.sans, fontSize: mono ? 10.5 : 11.5,
    letterSpacing: mono ? '0.04em' : 'normal', cursor:'pointer',
  }}>{children}</span>
);

const HomeChip = ({ children, mono, onClick }) => (
  <window.AH_DS.Btn type="button" onClick={onClick} style={{
    display:'inline-flex', alignItems:'center', gap:5, padding:'3px 9px',
    background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.sm,
    color:LM.inkSoft, fontFamily: mono ? LM.mono : LM.sans, fontSize: mono ? 10.5 : 11.5,
    letterSpacing: mono ? '0.04em' : 'normal', cursor:'pointer',
  }}>{children}</window.AH_DS.Btn>
);

const ToolCard = ({ tool, onOpen }) => (
  <div data-tool-card={tool.id} role="button" tabIndex={0}
    aria-label={`Open ${tool.label}`}
    onClick={onOpen}
    onKeyDown={event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        onOpen?.();
      }
    }}
    style={{
    flex:1, minHeight:134, padding:'10px 11px', textAlign:'left', background:LM.bgPanel,
    border:`1px solid ${LM.line}`, borderRadius:LM.rad.sm, color:LM.ink,
    display:'flex', flexDirection:'column', gap:8, minWidth:0, cursor:'pointer',
  }}>
    <div style={{display:'flex', alignItems:'center', gap:7, minWidth:0}}>
      <span data-tool-dot="" style={{width:6, height:6, borderRadius:'50%', background:tool.color, flexShrink:0}}/>
      <span style={{fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:tool.color, letterSpacing:'0.08em', textTransform:'uppercase'}}>
        {tool.stateWord || toolStateWord(tool.state)}
      </span>
      <span style={window.AH_DS.styles.fill}/>
      {tool.canToggle && <window.AH_DS.Btn type="button" role="switch" aria-checked={!!tool.toggleChecked} title={tool.toggleChecked ? 'Turn off' : 'Turn on'}
        onClick={event => { event.stopPropagation(); tool.toggleChecked ? tool.turnOff?.() : tool.turnOn?.(); }} style={{
        width:28, height:16, padding:2, border:0, borderRadius:8,
        background:tool.toggleChecked ? LM.ok : LM.line, cursor:'pointer',
      }}>
        <span style={{display:'block', width:12, height:12, borderRadius:'50%', background:LM.bg,
          transform:tool.toggleChecked ? 'translateX(12px)' : 'translateX(0)'}}/>
      </window.AH_DS.Btn>}
    </div>
    <div style={{display:'flex', alignItems:'center', gap:8, minWidth:0}}>
      <span aria-hidden="true" style={{width:24, height:24, borderRadius:LM.rad.sm, display:'grid', placeItems:'center',
        color:tool.color, background:tool.color + '1a', flexShrink:0}}><ToolGlyph id={tool.id}/></span>
      <span style={{fontFamily:LM.serif, fontSize:22, lineHeight:1, fontWeight:400, flex:1, minWidth:0,
        overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{tool.label}</span>
    </div>
    <div data-tool-description="" title={tool.description || undefined} style={{fontFamily:LM.sans, fontSize:12.5, color:LM.inkSoft,
      lineHeight:1.35, minHeight:34, overflow:'hidden', display:'-webkit-box', WebkitLineClamp:2, WebkitBoxOrient:'vertical'}}>
      {tool.description}</div>
    <div data-tool-stat="" title={tool.cardStat ?? tool.statLine ?? tool.stat ?? undefined} style={{fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz,
      color:LM.inkSoft, letterSpacing:'0.03em', lineHeight:1.4, minHeight:30, whiteSpace:'normal', overflowWrap:'anywhere'}}>
      {tool.cardStat ?? tool.statLine ?? tool.stat}</div>
    <div style={{marginTop:'auto', display:'flex', justifyContent:'flex-end'}}>
      <span data-tool-open="" aria-hidden="true" style={{fontFamily:LM.mono, fontSize:12, color:LM.inkSoft}}>{'\u2192'}</span>
    </div>
  </div>
);

const SettingsBaboom = ({ onOpenToolGraph, onClose }) => {
  const openToolGraphFromSettings = id => { onClose?.(); onOpenToolGraph?.(id); };
  return <div style={{display:'flex', flexDirection:'column', gap:14}}>
    <div style={{background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg, overflow:'hidden'}}>
      <BaboomStartupRow first/>
    </div>
    <div style={{display:'flex', alignItems:'center', gap:10}}>
      <span style={window.AH_DS.styles.fill}/>
      <window.AH_DS.Btn type="button" onClick={() => openToolGraphFromSettings('baboom')} style={window.AH_DS.styles.button(false ? 'primary' : 'secondary', true)}>Open as node ↗</window.AH_DS.Btn>
    </div>
  </div>;
};

const SettingsCloudStatus = ({ toolRow, account, onSettings }) => {
  const signedIn = !!(account && account.signedIn);
  const hasToolRow = !!toolRow;
  const stateWord = hasToolRow
    ? (toolRow.stateWord || toolRow.state_word || toolStateWord(toolRow.state || 'starting'))
    : (signedIn ? 'SIGNED IN' : 'STARTING');
  const accountLine = signedIn ? 'Signed in as ' + String(account.email || 'this account') + '.' : 'Not signed in.';
  const statusLine = hasToolRow ? (toolRow.statLine || toolRow.stat_line || '') : accountLine;
  const rows = [
    ['STATE', stateWord],
    ['STATUS', statusLine],
  ];  // No wiring line: the founder removed tool-to-tool plumbing text from the Hub (ITEM 3b).
  return <div style={{display:'flex', flexDirection:'column', gap:14}}>
    <SHead title="Cloud status" sub={toolRow?.description || 'Devices, grants and cloud agents.'}/>
    <div style={{background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg, overflow:'hidden'}}>
      {rows.map((row, i) => (
        <div key={row[0]} style={{padding:'10px 14px', display:'flex', gap:LM.sp.md, borderTop:i ? `1px solid ${LM.lineSoft}` : 'none', alignItems:'baseline'}}>
          <span style={{fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.12em', width:58, flexShrink:0}}>{row[0]}</span>
          <span style={{fontSize:13, color:LM.ink, minWidth:0, overflowWrap:'anywhere'}}>{row[1]}</span>
        </div>
      ))}
    </div>
    <div>
      <window.AH_DS.Btn type="button" onClick={() => onSettings && onSettings(true, 'account')}
        style={{...window.AH_DS.styles.button("secondary", true), padding:'4px 10px', fontStyle:'normal'}}>Manage account in Settings › Account</window.AH_DS.Btn>
    </div>
  </div>;
};

const ToolMainView = ({ view, account, setAccount, onSignOut, onSettings, onHome, onChats, onCockpit, onDocs, onLibrary, updateView }) => {
  const [store, setStore] = React.useState(() => ({forgotten:[], revealed:{}}));
  const patch = (k, v) => setStore(old => Object.assign({}, old, typeof k === 'object' ? k : {[k]:v}));
  const tool = view?.id || 'brain';
  const title = tool === 'baboom' ? 'BABOOM' : tool[0].toUpperCase() + tool.slice(1);
  const tab = view?.tab || firstToolTab(tool);
  const workshopState = useWorkshopProjection();
  const personal = usePersonalTheme();
  const hub = useToolHubProjection();
  const toolRow = toolRowsFromOwners({workshopState, account, personal, hub}).find(row => row.id === tool);
  const offTool = toolRow?.state === 'off' ? toolRow : null;
  if (tool === 'workshop') {
    const descriptor = (workshopState?.workshops || []).find(row => row.root === view?.root) ||
      {root:WORKSHOP_UNAVAILABLE_ROOT, label:'Workshop', unavailable:true, native_work_available:false};
    return <LazyWorkshopWindow embedded state={workshopState || {}} descriptor={descriptor} account={account} sel={{task:view?.focus || null}}
      setSel={next => updateView?.({...view, focus:next.task || null})} onHome={onHome} onDocs={onDocs}
      onChats={onChats} onCockpit={onCockpit} onSettings={() => onSettings?.(true)} onLibrary={onLibrary} onAddNode={onLibrary} onLeave={onHome}/>;
  }
  return <main data-tool-view={tool} data-tool-tab={tab} data-tool-focus={view?.focus || ''} className="ah-scroll" style={{
    gridColumn:'2', gridRow:'1', overflow:'auto', minHeight:0, padding:'28px 44px 36px',
    background:LM.bg, color:LM.ink,
  }}>
    <div style={{display:'flex', alignItems:'baseline', gap:10, marginBottom:18}}>
      <h1 style={{fontFamily:LM.serif, fontSize:30, fontWeight:400, margin:0}}>{title}</h1>
      <span style={{fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.08em', textTransform:'uppercase'}}>
        {tab}
      </span>
    </div>
    {offTool ? <ToolOffPanel tool={offTool}/> : <>
    {tool === 'brain' && <SettingsMemory store={store} patch={patch}/>}
    {tool === 'connectors' && <SettingsHosts/>}
    {tool === 'cloud' && <SettingsCloudStatus toolRow={toolRow} account={account} onSettings={onSettings}/>}
    {tool === 'baboom' && <SettingsBaboom/>}
    {!['workshop','brain','connectors','cloud','baboom'].includes(tool) && <ToolOffPanel tool={{id:tool,label:title,state:'off',color:LM.inkSoft,
      emptyTitle:title + ' is off', emptyLine:'This tool has no active view.'}}/>}
    </>}
  </main>;
};

// ──────────────────────── WORKSPACE ────────────────────────
const useDeferredCanvas = (needsDocumentation = false) => {
  const signed = window.ARCHHUB_STUDIO_AUTHORITY;
  const signedLoader = React.useCallback(() => {
    const held = signed.getSnapshot()?.canvas;
    return held?.projection !== 'home' && (!needsDocumentation || held?.documentation?.tutorials?.length)
      ? Promise.resolve(held) : signed.load();
  }, [signed, needsDocumentation]);
  const loader = signed ? signedLoader : window.ARCHHUB_LOAD_CANVAS;
  const held = signed?.getSnapshot()?.canvas;
  const deferred = signed ? held?.projection === 'home' || needsDocumentation && !held?.documentation?.tutorials?.length
    : window.ARCHHUB_EXISTING_WORKSHOP?.getSnapshot()?.topology?.canvas?.canvas_deferred === true;
  const [state, setState] = React.useState(() => ({pending:!!loader && deferred, error:''}));
  const [attempt, setAttempt] = React.useState(0);
  React.useEffect(() => {
    if (typeof loader !== 'function') return;
    let active = true;
    setState({pending:deferred, error:''});
    const timer = deferred ? setTimeout(() => {
      if (active) setState({pending:false, error:'The canvas did not answer. Check the connection and retry.'});
    }, signed ? 30000 : 1900) : null;
    Promise.resolve().then(loader).then(() => {
      clearTimeout(timer);
      if (active) setState({pending:false, error:''});
    }, error => {
      clearTimeout(timer);
      if (active) setState({pending:false, error:error?.message || 'Canvas reading was refused.'});
    });
    return () => {active = false; clearTimeout(timer);};
  }, [loader, deferred, attempt, signed]);
  return {...state, retry:() => setAttempt(value => value + 1)};
};
// Loading this face is the only point where its code enters Studio.
const LazyWorkshopWindow = props => {
  const [View, setView] = React.useState(() => window.WorkshopView || null);
  const [error, setError] = React.useState('');
  const [attempt, setAttempt] = React.useState(0);
  React.useEffect(() => {
    if (View) return undefined;
    let live = true;
    setError('');
    const timer = setTimeout(() => { if (live) setError('Workshop did not answer. Retry opening it.'); }, 1900);
    const load = window.ARCHHUB_LOAD_WORKSHOP;
    if (typeof load !== 'function') {
      clearTimeout(timer); setError('Workshop could not be opened. Refresh the application and try again.');
      return () => {live = false;};
    }
    Promise.resolve().then(load).then(component => {
      clearTimeout(timer);
      if (live) setView(() => component);
    }).catch(reason => {
      clearTimeout(timer);
      if (live) setError(reason?.message || 'Workshop could not be opened. Retry opening it.');
    });
    return () => { live = false; clearTimeout(timer); };
  }, [View, attempt]);
  return View ? <View {...props}/> : <window.AH_DS.EmptyState data-workshop-loading="" error={!!error}
    title={error ? 'Workshop unavailable' : 'Opening Workshop…'} detail={error}
    onRetry={error ? () => setAttempt(value => value + 1) : undefined}
    style={{gridColumn:'1 / -1',gridRow:'1 / -1',background:LM.bgDeep}}/>;
};

const Workspace = ({ libraryMode = false, session, account, model, readiness = null, onReadinessStale, onModelReadRetry, openTabs, sessionRows = LM_SESSIONS, setOpenId, closeTab, setPickerOpen, setLibraryOpen, focusId, setFocusId, pendingCanvasReveal, requestCanvasReveal, clearPendingCanvasReveal, userNodes, addNodeFromLibrary, themeEpoch = 0, onHome, onChats, onCockpit, onDocs, onNewSession, onSettings, onAccount, view, updateView, wsSel, setWsSel, updateCanvasViewport }) => {
  const [toolbarHost,setToolbarHost]=React.useState(null);
  const canvasRead = useDeferredCanvas();
  useNodeLibrary();
  const authorityState = useStudioProjection();
  const graph = authorityState?.graph || LM_GRAPH;
  const historyDecorator = typeof decorateHistoryNode === 'function' ? decorateHistoryNode : node => node;
  const allNodes = [...graph.nodes, ...(userNodes || [])].map(node =>
    historyDecorator(node, authorityState?.canvas || {}));
  // A wire is a node: focusId may name one, and the SAME rail renders it.
  const wireIdx = authorityState ? graph.wires.findIndex(wire => wire.id === focusId) : (String(focusId).indexOf('wire:') === 0 ? +String(focusId).slice(5) : -1);
  const focusNode = wireIdx >= 0
    ? window.wireAsNode(graph.wires[wireIdx], wireIdx, allNodes)
    : allNodes.find(n => n.id === focusId && (typeof n.application!=='boolean' || n.application === (String(session?.id || '').startsWith('system:') || view.mode==='system'))) ||
      ((String(session?.id || '').startsWith('system:') || view.mode==='system') ? allNodes.find(n=>n.application) : null);
  const {mode, conversationRoot, target} = view;
  const effectiveMode = String(session?.id || '').startsWith('system:') ? 'system' : mode;
  const setMode = mode => updateView({mode});
  const [systemArrangeSummary, setSystemArrangeSummary] = React.useState(null);
  React.useEffect(() => {
    if (effectiveMode !== 'system') setSystemArrangeSummary(null);
  }, [effectiveMode, session?.id]);
  const workshopState = useWorkshopProjection();
  const workshops = workshopState?.workshops || [];
  const workshop = workshops.find(row => row.root === conversationRoot) ||
    (conversationRoot === WORKSHOP_UNAVAILABLE_ROOT ? {root:WORKSHOP_UNAVAILABLE_ROOT, label:'Workshop',
      is_general:true, native_work_available:false, unavailable:true,
      unavailable_reason:view.notice || workshopUnavailableText(workshopState?.canvas?.unavailable)} : null);
  const graphScopeKey = JSON.stringify([session.id, studioCanvasScope(authorityState?.canvas)]);
  const workshopWindow = effectiveMode === 'chat' && !!workshop;
  if (canvasRead.pending || canvasRead.error) return <main data-workspace-canvas-loading="" style={{gridColumn:'2', gridRow:'1', padding:24, color:LM.inkSoft}}>
    <window.AH_DS.EmptyState title={canvasRead.error ? 'Canvas unavailable' : 'Reading your workspace…'} error={!!canvasRead.error}
      detail={canvasRead.error} onRetry={canvasRead.error ? canvasRead.retry : undefined}/>
  </main>;
  if (view.pending) return <main style={{gridColumn:'2', gridRow:'1', padding:24, color:LM.inkSoft}}>
    <p role="status">{view.notice}</p>
  </main>;
  return (
    <main data-workspace-main="" style={{
      gridColumn:'2', gridRow:'1', minHeight:0, minWidth:0, overflow:'hidden',
      height:'100%',
      display:'grid',
      gridTemplateColumns:workshopWindow ? 'minmax(0, 1fr)' : 'minmax(0, 1fr) 320px',
      gridTemplateRows:workshopWindow || libraryMode ? '1fr' : '36px 1fr',
    }}>
      {!workshopWindow && !libraryMode && <WsHeader
        toolbarRef={setToolbarHost} session={session} model={model} openTabs={openTabs}
        sessionRows={sessionRows}
        setOpenId={setOpenId} closeTab={closeTab} mode={effectiveMode} setMode={setMode}
        workshops={workshops} conversationRoot={workshop?.root || ''} conversationNotice={view.notice}
        workshopUnavailable={workshopState?.canvas?.unavailable || ''}
        workshopModel={workshopState?.nativeWork?.model}
        setConversationRoot={root => updateView({conversationRoot:root, mode:'chat', target:''})}
        setPickerOpen={setPickerOpen} onHome={onHome} onNewSession={onNewSession}
        onSettings={onSettings}
        systemAllowed={systemAllowed(authorityState?.canvas, graph)}
        systemArrangeSummary={systemArrangeSummary} projection={authorityState}/>}
      {effectiveMode === 'chat' && workshop ? (
        <LazyWorkshopWindow embedded key={JSON.stringify([session.id, workshopState.canvas.graph_id,
          workshopState.canvas.root, workshop.root])} state={workshopState} descriptor={workshop} account={account} target={target}
          setTarget={target => updateView({target})} setMode={setMode} setFocusId={setFocusId}
          requestCanvasReveal={requestCanvasReveal} onHome={onHome} onChats={onChats} onCockpit={onCockpit} onDocs={onDocs} onSettings={onSettings}
          onAddNode={() => setLibraryOpen(true)} onLibrary={() => setLibraryOpen(true)}
          onLeave={() => updateView({conversationRoot:'', mode:'canvas', target:''})}
          sel={wsSel} setSel={setWsSel}/>
      ) : (
        <>
          <NodeCanvas toolbarHost={toolbarHost} libraryMode={libraryMode} key={JSON.stringify([session.id, studioCanvasScope(authorityState?.canvas), effectiveMode === 'system'])} system={effectiveMode === 'system'} focusId={focusId} setFocusId={setFocusId} pendingReveal={pendingCanvasReveal} clearPendingReveal={clearPendingCanvasReveal} setLibraryOpen={setLibraryOpen} userNodes={userNodes} addNodeFromLibrary={addNodeFromLibrary} model={model} onViewportChange={updateCanvasViewport} fitOnOpen={!libraryMode} onSystemArrangeSummary={setSystemArrangeSummary} themeEpoch={themeEpoch}/>
          <NodeRail libraryMode={libraryMode} node={focusNode} hiddenWork={!focusNode && authorityState?.canvas?.selection_hidden === true}
            graph={graph} canvas={authorityState?.canvas} session={session} sessionRows={sessionRows}
            model={model} setPickerOpen={setPickerOpen} readiness={readiness}
            onReadinessStale={onReadinessStale} onModelReadRetry={onModelReadRetry} onAccount={onAccount}
            scope={authorityState?.canvas?.scope?.current || authorityState?.canvas?.root || ''}
            openConversation={root => updateView({conversationRoot:root, mode:'chat', target:''})}
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
const defaultModelRowFromPayload = (payload, route) => {
  const row = payload && payload.default_model && typeof payload.default_model === 'object' ? payload.default_model : null;
  if (!row || modelRoute(row) !== route) return null;
  return {...row, route:row.route || route, routed:row.routed || route};
};
const defaultModelRow = (route, source, fallback) => {
  return {name:route, route, routed:route, vendor:fallback ? 'Default' : 'Saved selection',
    tag:fallback ? (source || 'default') : 'Availability unverified',
    ctx:'', col:LM.inkSoft, latency:null};
};
const DEFAULT_FREE_MODEL_ROUTE = 'openrouter/free';
const DEFAULT_MODEL_READ_RETRY_DELAYS_MS = [2000, 5000, 10000];
// A composer pick is the owner's graph-held setting, saved when it is made.
// It lived only in this page until a Send reached the server, so a restart or
// an update came back "Choose a model" (2026-09-17). The signed clean engine
// has no selection route, so there the pick stays page state as before.
const pendingModelAnswer = () => ({ name:'Model pending', route:'', routed:'', vendor:'Checking availability', tag:'', ctx:'', col:LM.inkSoft, latency:null, pending:true });
const unknownModelAnswer = () => ({ name:'Checking', route:DEFAULT_FREE_MODEL_ROUTE, routed:DEFAULT_FREE_MODEL_ROUTE,
  vendor:'Default free route', tag:'', ctx:'', col:LM.inkSoft, latency:null, unknown:true });
const noModelPicked = () => ({ name:'Choose a model', route:'', routed:'', vendor:'No model selected', tag:'', ctx:'', col:LM.inkSoft, latency:null });
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
const modelDisplayName = m => {
  const name = String((m && m.name) || '').trim();
  if (m?.pending) return name;
  if (m?.unknown) return name || 'checking';
  if (m?.defaultRouteModel && name && name !== 'Choose a model') return name;
  return modelRoute(m) || name;
};
const GENERATION_SPECS = [
  { k:'temperature', label:'temperature', type:'number', min:0, max:2, step:0.05, v:0.7, page:'Model' },
  { k:'top-p', label:'top-p', type:'number', min:0, max:1, step:0.01, v:0.95, page:'Model' },
  { k:'max tokens', label:'max tokens', type:'number', min:256, max:32000, step:256, v:4096, page:'Model' },
];
const normalizeGenerationDefaults = values => Object.fromEntries(GENERATION_SPECS.map(spec => {
  const raw = values && Object.prototype.hasOwnProperty.call(values, spec.k) ? values[spec.k] : spec.v;
  const number = Number(raw);
  return [spec.k, Number.isFinite(number) ? number : spec.v];
}));
const modelGenerationDefaults = () => normalizeGenerationDefaults(
  window.ARCHHUB_EXISTING_WORKSHOP?.getSnapshot?.()?.theme?.configuration?.model_defaults ||
  window.ARCHHUB_STUDIO_AUTHORITY?.getSnapshot?.()?.canvas?.configuration?.model_defaults ||
  window.ARCHHUB_EXISTING_WORKSHOP?.getSnapshot?.()?.topology?.canvas?.configuration?.model_defaults || window.ARCHHUB_MODEL_DEFAULTS ||
  window.ARCHHUB_PICKED_MODEL?.generation ||
  window.ARCHHUB_LIVE?.model_defaults ||
  window.ARCHHUB_STUDIO_AUTHORITY?.getSnapshot?.()?.canvas?.configuration?.model_defaults ||
  window.ARCHHUB_EXISTING_WORKSHOP?.getSnapshot?.()?.canvas?.configuration?.model_defaults || {});
const generationRequestOptions = values => {
  const next = normalizeGenerationDefaults(values || modelGenerationDefaults());
  return {temperature:next.temperature, top_p:next['top-p'], max_tokens:next['max tokens']};
};
const saveModelDefaults = async values => {
  const next = normalizeGenerationDefaults(values);
  if (typeof window.ARCHHUB_MODEL_DEFAULTS_SAVE === 'function') {
    const saved = await window.ARCHHUB_MODEL_DEFAULTS_SAVE(next);
    window.ARCHHUB_MODEL_DEFAULTS = normalizeGenerationDefaults(saved?.model_defaults || saved?.defaults || next);
  } else {
    const owner = window.ARCHHUB_EXISTING_WORKSHOP;
    const configuration = owner?.getSnapshot?.()?.theme?.configuration ||
      window.ARCHHUB_STUDIO_AUTHORITY?.getSnapshot?.()?.canvas?.configuration ||
      owner?.getSnapshot?.()?.topology?.canvas?.configuration;
    const selection = configuration?.composer_model;
    const route = selection?.source === 'graph' ? String(selection.value ?? '') : modelRoute(pickedModel());
    if (!owner?.setComposerModel) throw new Error('Model settings are unavailable in this connection.');
    const saved = await owner.setComposerModel(route, next);
    window.ARCHHUB_MODEL_DEFAULTS = normalizeGenerationDefaults(
      saved?.configuration_state?.model_defaults || saved?.model_defaults || next);
    window.ARCHHUB_PICKED_MODEL = {...window.ARCHHUB_PICKED_MODEL, generation:window.ARCHHUB_MODEL_DEFAULTS};
  }
  return window.ARCHHUB_MODEL_DEFAULTS;
};
Object.assign(window, {saveModelDefaults, modelGenerationDefaults});
const aiNodeWithMovedParams = node => {
  if (!node || node.cat !== 'ai') return node;
  const params = [...(node.params || [])];
  const has = key => params.some(row => row.k === key || row.label === key);
  GENERATION_SPECS.forEach(spec => {
    if (!has(spec.k)) params.push({...spec, owner:node.id});
  });
  return {...node, params};
};

// ─── Chat lane data seam ───
// ChatView, InferenceInspector and ModelPicker are the design bundle's components
// (archhub/project/studio-lm.jsx ChatView 939-1020, InferenceInspector 1023-1080, ModelPicker
// 3145-3208), kept to its layout, spacing, type, tokens and copy. This seam is where they differ:
// it maps what the application holds onto the shapes those components read. No seeded person,
// file, token count, stage progress, host or price is drawn.
const chatPeople = model => {
  const account = typeof acLoad === 'function' ? (acLoad() || {}) : {};
  const me = String(account.name || account.email || '').trim() || 'You';
  // Unrouted, the application's own composer answers, so the turn is signed ArchHub.
  const answerer = String((modelRoute(model) ? model.name : 'ArchHub') || 'ArchHub');
  return {me, answerer};
};
const agentAnswerText = answer => {
  if (answer && typeof answer === 'object' && !Array.isArray(answer)) return String(answer.answer || answer.text || answer.error || '');
  return String(answer || '');
};
const agentAnswerSteps = answer => {
  if (!answer || typeof answer !== 'object' || Array.isArray(answer) || !Array.isArray(answer.steps)) return [];
  return answer.steps.filter(step => step && typeof step === 'object').map((step, index) => ({
    id:String(step.id || step.call_id || index),
    tool:String(step.tool || step.name || 'tool'),
    status:String(step.status || (step.ok === false ? 'refused' : 'ok')),
    ok:step.ok !== false && String(step.status || '').toLowerCase() !== 'refused',
    args:step.args || step.arguments || {},
    summary:String(step.summary || step.result_summary || step.error || ''),
    readback:step.readback ? String(step.readback) : '',
  }));
};
const agentAnswerVia = answer => {
  if (!answer || typeof answer !== 'object' || Array.isArray(answer)) return null;
  const via = answer.via;
  if (!via || typeof via !== 'object' || Array.isArray(via)) return null;
  const provider = String(via.provider || via.family || '').trim();
  const model = String(via.model || '').trim();
  if (!provider && !model) return null;
  return {provider, model};
};
const agentViaLabel = via => via ? ('via ' + (via.provider || 'model') + (via.model ? ' · ' + via.model : '')) : '';
const formatBaboomStepDetail = step => {
  if (!step || typeof step !== 'object') return '';
  const parts = [];
  const args = step.args && typeof step.args === 'object' && !Array.isArray(step.args) ? step.args : {};
  Object.keys(args).sort().forEach(key => {
    const value = args[key];
    const text = value && typeof value === 'object' ? String(value.label || value.name || value.status || 'set') : String(value);
    parts.push(`${key}: ${text}`);
  });
  if (step.readback) parts.push(`readback: ${step.readback}`);
  return parts.join('\n');
};
const BaboomToolSteps = ({steps}) => {
  const rows = Array.isArray(steps) ? steps : [];
  if (!rows.length) return null;
  return <div data-baboom-steps="" style={{display:'flex', flexDirection:'column', gap:5, marginTop:8}}>
    {rows.map((step, index) => (
      <details key={step.id || index} data-baboom-step="" data-status={step.status} style={{
        border:`1px solid ${LM.lineSoft}`, borderRadius:5, background:LM.bg, padding:'5px 7px',
      }}>
        <summary style={{cursor:'pointer', display:'flex', alignItems:'center', gap:7,
          fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:step.ok ? LM.ok : LM.warn, letterSpacing:0}}>
          <span style={{color:LM.ink}}>{step.tool}</span>
          <span>{step.status}</span>
          {step.summary ? <span style={{color:LM.inkSoft, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{step.summary}</span> : null}
        </summary>
        <pre style={{margin:'6px 0 0', whiteSpace:'pre-wrap', overflowWrap:'anywhere',
          fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, lineHeight:LM.fs.dataSm.ln + 'px', color:LM.inkSoft}}>
          {formatBaboomStepDetail(step)}
        </pre>
      </details>
    ))}
  </div>;
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
const chatConnectors = () => hostTally().builtRows.map(c => ({
  id:c.id, name:c.name, state:c.state, word:c.officeAggregate && hostRunningState(c) ? 'Connected' : hostStateWord(c), detail:c.detail,
  col:c.officeAggregate && hostRunningState(c) ? LM.ok : hostStateTone(c),
}));

// ─── Calm chat view (default) — restores original Studio's generous rhythm ───
const NO_MODEL_STATE = {state:'no_model', route:'', actions:['sign_in', 'choose_model'],
  message:'No model yet. Sign in to ArchHub, or choose a model.'};
const modelCatalogueUnknown = () => ({state:'unknown', route:DEFAULT_FREE_MODEL_ROUTE, actions:['retry_models'],
  message:'Models unavailable · retrying…'});
// The route shown is judged here: the composer pick or the selected node's own model
// (review 2026-09-28). The provider states and the copy are the server's
// (model_router.composer_readiness families/messages); only the route's family is read here.
const ROUTE_FAMILIES = [['cloud/', 'cloud'], ['openrouter/', 'openrouter'], ['lmstudio/', 'lmstudio'], ['ollama/', 'ollama'],
  ['local-cli/', 'local-cli']];
// A bare vendor/model:free is OpenRouter's legacy form; a family-prefixed route (lmstudio/x:free)
// stays in its own family, as model_router._legacy_free_route rules.
const routeFamily = route => {
  const prefixed = ROUTE_FAMILIES.some(([prefix]) => route.startsWith(prefix));
  if (route === 'openrouter/free' || (!prefixed && /^[^\s/]+\/[^\s/]+:free$/.test(route))) return 'openrouter';
  const hit = ROUTE_FAMILIES.find(([prefix]) => route.startsWith(prefix) && route.slice(prefix.length).replace(/\//g, '').trim());
  return hit ? hit[1] : '';
};
const READINESS_LABELS = {unknown:'MODELS', no_model:'NO MODEL', no_key:'NO KEY', invalid:'UNSUPPORTED MODEL', unavailable:'NOT RUNNING'};
const routeReadiness = (route, held, pending = false) => {
  const text = String(route || '').trim();
  const messages = (held && held.messages) || {};
  if (!text && !held && pending) return null;
  if (held?.state === 'unknown') return held;
  if (!text) return {...NO_MODEL_STATE, message:messages.no_model || NO_MODEL_STATE.message};
  if (!held) return null;
  if (!held.families) return held.state && held.state !== 'ready' && held.route === text ? held : null;
  const family = routeFamily(text);
  if (!family) return {state:'invalid', route:text, actions:['choose_model'],
    message:messages.invalid || 'ArchHub cannot reach this model. Choose another model.'};
  const answer = held.families[family];
  return answer && answer.state !== 'ready' ? {...answer, route:text} : null;
};
const ChatView = ({ session, model, setMode, workshopRoom = '', openWorkshop, onPickModel, onAccount, workshopUnavailable = '', readiness = null, onReadinessStale, onModelReadRetry }) => {
  // The Workshop is opened from here (it is not a header segment). Without a room the click answers
  // with the owner's reason as visible text, never a silent no-op (founder report 2026-09-23).
  const [workshopRefusal, setWorkshopRefusal] = React.useState('');
  const {me, answerer} = chatPeople(model);
  const routed = !!modelRoute(model);
  // Never silent (fresh machine, 2026-09-28): the route shown, whatever its state, is said
  // with the ways out that apply to it.
  const blocked = routeReadiness(modelRoute(model), readiness, model?.pending === true);
  const offers = new Set((blocked && blocked.actions) || []);
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
      const answer = await window.ARCHHUB_AGENT(text, modelRoute(model),
        {generation:generationRequestOptions(), returnResult:true});
      setMessages(m => [...m, { me:false, time:stamp(), text:agentAnswerText(answer),
        via:agentAnswerVia(answer), steps:agentAnswerSteps(answer) }]);
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
      {/* The design draws the reply prompt softly; a real field has to be told. */}
      <style>{`.lm-chat-draft::placeholder { color: ${LM.inkSoft}; opacity: 1 }`}</style>
      <div className="ah-scroll" style={{ flex:1, overflow:'auto', padding:'24px 0 12px' }}>
        <div style={{ maxWidth:720, margin:'0 auto', padding:'0 36px' }}>
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
                  <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.04em' }}>{m.time}</span>
                </div>
                <div style={{
                  fontSize: m.me ? 14 : 15,
                  fontFamily: m.me ? LM.sans : LM.serif,
                  fontStyle: m.me ? 'normal' : 'normal',
                  lineHeight:1.6, color: m.me ? LM.ink : LM.ink, letterSpacing: m.me ? '0' : '-0.003em',
                }}>{m.text}</div>
                {!m.me && <BaboomToolSteps steps={m.steps}/>}
                {!m.me && m.via && <div data-chat-via="" style={{
                  marginTop:6, fontFamily:LM.sans, fontSize:11, lineHeight:1.35,
                  color:LM.inkSoft, letterSpacing:0,
                }}>{agentViaLabel(m.via)}</div>}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Composer — calm, centered */}
      <div style={{ padding:'12px 0 18px', borderTop:`1px solid ${LM.lineSoft}` }}>
        <div style={{ maxWidth:720, margin:'0 auto', padding:'0 36px' }}>
            {/* Stands above the composer, where Send would be; the conversation column keeps the design. */}
            {blocked && blocked.state !== 'unknown' && (
              <div data-chat-no-model="" role="status" style={{
                background:LM.bgPanel, border:`1px solid ${LM.line}`, borderLeft:`3px solid ${LM.warn}`,
                borderRadius:LM.rad.lg, padding:'12px 16px', marginBottom:10,
              }}>
                <div style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.warn, letterSpacing:'0.14em', marginBottom:6 }}>
                  {READINESS_LABELS[blocked.state] || 'NO MODEL'}</div>
                <div style={{ fontSize:14, lineHeight:1.55, color:LM.ink, marginBottom:10 }}>{blocked.message}</div>
                <div style={{ display:'flex', gap:8 }}>
                      {offers.has('sign_in') && <window.AH_DS.Btn type="button" onClick={() => {
                        if (typeof onAccount === 'function') onAccount();
                        else if (typeof onReadinessStale === 'function') onReadinessStale();
                      }} style={{
                        padding:'7px 14px', background:LM.accent, color:(window.AH && window.AH.onFill) || '#180f08', border:0,
                        borderRadius:LM.rad.sm, fontSize:12.5, fontWeight:500, cursor:'pointer',
                      }}>Sign in</window.AH_DS.Btn>}
                      {offers.has('retry_models') && <window.AH_DS.Btn type="button" onClick={() => typeof onModelReadRetry === 'function' && onModelReadRetry()} style={{
                        padding:'6px 13px', background:'transparent', color:LM.ink, border:`1px solid ${LM.line}`,
                        borderRadius:LM.rad.sm, fontSize:12.5, fontWeight:500, cursor:'pointer',
                      }}>Retry</window.AH_DS.Btn>}
                      {offers.has('choose_model') && <window.AH_DS.Btn type="button" onClick={() => typeof onPickModel === 'function' && onPickModel()} style={{
                        padding:'6px 13px', background:'transparent', color:LM.ink, border:`1px solid ${LM.line}`,
                        borderRadius:LM.rad.sm, fontSize:12.5, fontWeight:500, cursor:'pointer',
                      }}>Choose a model</window.AH_DS.Btn>}
                    </div>
              </div>
            )}
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
              <window.AH_DS.Btn type="button" aria-label="Open the Workshop" aria-disabled={workshopRoom && openWorkshop ? undefined : 'true'}
                onClick={() => {
                  if (workshopRoom && openWorkshop) { setWorkshopRefusal(''); openWorkshop(workshopRoom); }
                  else setWorkshopRefusal(workshopUnavailableText(workshopUnavailable));
                }}
                title={workshopRoom ? 'Open the Workshop conversation' : workshopUnavailableText(workshopUnavailable)} style={{
                display:'inline-flex', alignItems:'center', gap:5, padding:'3px 9px',
                background: workshopRoom ? LM.accentDim : 'transparent',
                border: workshopRoom ? `1px solid ${LM.accentSoft}` : `1px dashed ${LM.line}`, borderRadius:LM.rad.sm,
                color: workshopRoom ? LM.accent : LM.inkSoft, fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, letterSpacing:'0.04em',
                cursor: workshopRoom ? 'pointer' : 'default',
              }}>◆ workshop</window.AH_DS.Btn>
              {workshopRefusal && <span role="alert" style={{fontSize:11, color:LM.ink, maxWidth:260, overflow:'hidden',
                textOverflow:'ellipsis', whiteSpace:'nowrap'}} title={workshopRefusal}>{workshopRefusal}</span>}
              <window.AH_DS.Btn onClick={() => setMode('canvas')} style={{
                display:'inline-flex', alignItems:'center', gap:5, padding:'3px 9px',
                background:'transparent', border:`1px solid ${LM.line}`, borderRadius:LM.rad.sm,
                color:LM.inkSoft, fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, letterSpacing:'0.04em', cursor:'pointer',
              }}>⌗ open as nodes</window.AH_DS.Btn>
              <span aria-hidden="true" style={{ flex:'1 1 0', minWidth:0, textAlign:'right', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}/>
              {/* While an answer is out Send is disabled: a dashed border, never alpha (DECISIONS.md). */}
              {routed ? <window.AH_DS.Btn onClick={send} disabled={busy} style={{
                padding: busy ? '6px 13px' : '7px 14px', background: busy ? 'transparent' : LM.accent,
                color: busy ? LM.inkSoft : onFill, border: busy ? `1px dashed ${LM.line}` : 0,
                borderRadius:LM.rad.sm, fontSize:12.5, fontWeight:500, cursor: busy ? 'default' : 'pointer',
              }}>Send ↵</window.AH_DS.Btn> : <window.AH_DS.Btn type="button" onClick={() => typeof onPickModel === 'function' && onPickModel()}
                title="No model is picked: choose one to send" style={{
                padding:'6px 13px', background:'transparent', color:LM.ink, border:`1px dashed ${LM.line}`,
                borderRadius:LM.rad.sm, fontSize:12.5, fontWeight:500, cursor:'pointer',
              }}>Choose a model</window.AH_DS.Btn>}
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
  const hidden = window.ARCHHUB_INTERNAL_PARAM_KEYS || new Set(['source_digest', 'seed', 'image_path']);
  const rows = stages.flatMap((nodes, i) => nodes.flatMap(n => (n.params || [])
    .filter(p => !hidden.has(String(p.k || p.label || '').toLowerCase()))
    .slice(0, 2).map(p =>
    ({key:n.id + '|' + p.k, node:'stage ' + (i + 1) + ' · ' + n.title, k:p.k, v:String(p.v)}))));
  return (
    <div data-chat-chain="" style={{ padding:'14px 16px', borderBottom:`1px solid ${LM.lineSoft}` }}>
      <div style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.14em', marginBottom:10 }}>PARAMETRIC CHAIN · {stages.length} STAGE{stages.length === 1 ? '' : 'S'}</div>
      {stages.length > 0 && <div style={{ display:'flex', alignItems:'center', gap:0, marginBottom:10 }}>
        {stages.map((_, i) => (
          <React.Fragment key={i}>
            <div style={{ width:18, height:18, borderRadius:'50%', border:`2px solid ${LM.accent}`, background:LM.bg, color:LM.accent, display:'grid', placeItems:'center', fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, fontWeight:600 }}>{i + 1}</div>
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
      <div style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.14em', marginBottom:8 }}>MODEL</div>
      <window.AH_DS.Btn data-model-indicator="" onClick={() => setPickerOpen(true)} style={{
        width:'100%', display:'flex', alignItems:'center', gap:10, padding:'8px 10px',
        background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.md, cursor:'pointer', color:LM.ink,
      }}>
        <span style={{ width:22, height:22, borderRadius:LM.rad.sm, background:model.col, color:((window.AH && window.AH.onFill) || '#180f08'), display:'grid', placeItems:'center', fontFamily:LM.mono, fontSize:11, fontWeight:700 }}>{model.name[0]}</span>
        <div style={{ flex:1, textAlign:'left', lineHeight:1.15 }}>
          <div style={{ fontSize:13, fontWeight:500 }}>{model.name}</div>
          <div style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft }}>{model.vendor}{model.ctx ? ' · ctx ' + model.ctx : ''}</div>
        </div>
        <span style={{ color:LM.inkSoft, fontSize:11 }}>▾</span>
      </window.AH_DS.Btn>
    </div>

    {/* parametric chain -- the LIVE wired pipeline, stage by stage */}
    <LiveChain/>

    {/* connectors -- exactly what answered a probe, nothing invented */}
    <div data-chat-connectors="" style={{ padding:'14px 16px' }}>
      <div style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.14em', marginBottom:10 }}>CONNECTORS · {connectors.length}</div>
      {connectors.map(c => (
        <div key={c.id} title={c.detail} style={{ display:'flex', alignItems:'center', gap:8, padding:'5px 0', borderBottom:`1px dashed ${LM.lineSoft}` }}>
          <span style={{ width:7, height:7, borderRadius:'50%', background:c.col, boxShadow:`0 0 0 3px ${c.col}22` }}/>
          <span style={{ flex:1, fontSize:12.5, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{c.name}</span>
          <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:c.col, letterSpacing:'0.06em' }}>{c.word}</span>
        </div>
      ))}
      {/* A host that cannot connect on this machine says why, in words, not on hover. */}
      {connectors.filter(c => c.word !== 'Connected' && c.detail).map(c => (
        <div key={c.id + ':why'} data-connector-reason={c.id} style={{ fontSize:11, color:LM.inkSoft, lineHeight:1.45, whiteSpace:'normal', overflowWrap:'anywhere', padding:'4px 0 6px 15px' }}>{c.name}: {c.detail}</div>
      ))}
      {window.ARCHHUB_LIVE && !connectors.length &&
        <div role="status" style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, lineHeight:1.5 }}>No connected program found yet.</div>}
    </div>
  </aside>
  );
};

const CalmRow = ({ k, v }) => (
  <div style={{ display:'flex', alignItems:'center', gap:8, padding:'3px 0' }}>
    <span style={{ fontFamily:LM.mono, fontSize:11, color:LM.inkSoft, flex:1 }}>{k}</span>
    <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.ink }}>{v}</span>
  </div>
);

const StudioHeaderIcon = ({name}) => <svg aria-hidden="true" focusable="false" width="15" height="15"
  viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
  {name === 'download' ? <><path d="M12 3v12m-5-5 5 5 5-5"/><path d="M4 16v5h16v-5"/></> :
    name === 'reload' ? <><path d="M20 7v5h-5"/><path d="M19 12a7 7 0 1 0-2 5M20 12a8 8 0 0 0-14-6"/></> :
    name === 'skill' ? <><path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9Z"/></> :
    name === 'error' ? <><path d="m12 3 10 18H2Z"/><path d="M12 9v5m0 3h.01"/></> :
    name === 'ready' ? <><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></> :
    <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>}
</svg>;

const applicationUpdateHasUnsentWork = () => Array.from(
  document.querySelectorAll('textarea, [contenteditable=true][data-dirty=true]'))
  .some(e => e.tagName === 'TEXTAREA' ? !e.readOnly && !e.disabled && !!e.value.trim() : true);
window.ARCHHUB_UPDATE_RESTART_BLOCKED = applicationUpdateHasUnsentWork;

// One admitted restart: unsent text stays in place and a running job is never interrupted.
const useUpdateRestart = (ready, restart) => {
  const [refusal, setRefusal] = React.useState('');
  const run = () => {
    if (!ready) return;
    if (applicationUpdateHasUnsentWork()) { setRefusal('Save unsaved work before restarting.'); return; }
    setRefusal('');
    return restart();
  };
  React.useEffect(() => {
    const key = e => { if (e.ctrlKey && e.shiftKey && e.code === 'KeyU') { e.preventDefault(); run(); } };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  });
  React.useEffect(() => { if (!ready) setRefusal(''); }, [ready]);
  return [refusal, run];
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
      <window.AH_DS.Btn disabled={busy} onClick={() => read()} style={control} aria-label="Refresh protected editors"
        title="Refresh protected editors"><StudioHeaderIcon name="reload"/></window.AH_DS.Btn>
    </div>
    {review?.pages.map(page => <div key={page.page_id} style={{padding:'10px 0', borderBottom:`1px solid ${LM.lineSoft}`}}>
      <div style={{display:'flex', gap:8, alignItems:'center'}}>
        <span title={page.page_id} style={window.AH_DS.styles.fill}>{page.editor_label}</span>
        <window.AH_DS.Btn disabled={busy} onClick={() => setConfirmPage(page)} style={control}
          aria-label={'Review release of editor ' + page.page_id.slice(-8)} title="Review release of cleanup protection">⋯</window.AH_DS.Btn>
      </div>
      <div style={{color:LM.inkSoft, marginTop:4}}>{page.state === 'open' ? 'Open record' : 'Closed record'} ·
        {page.draft_state === 'dirty' ? ' draft pending' : page.draft_state === 'unknown' ? ' draft state not recorded' : ' no pending draft'}</div>
      <div title={'Session: ' + page.session_root + '\nView: ' + page.view_root} style={{color:LM.inkSoft, fontSize:11, marginTop:4}}>
        Browser {page.session_root.slice(-8)} · editor {page.page_id.slice(-8)}</div>
      <div style={{color:LM.inkSoft, fontSize:11, marginTop:4}}>Last changed {new Date(page.changed_at * 1000).toLocaleString()}</div>
      {confirmPage === page && <div style={{marginTop:8}}>
        <p style={{lineHeight:1.5}}>Release this editor’s protection only after saving or discarding its unsent work.
          Unsent text is not stored in this record. This action does not delete conversation messages or graph nodes.</p>
        <window.AH_DS.Btn disabled={busy} onClick={release} style={control}>Release protection</window.AH_DS.Btn>
        <window.AH_DS.Btn disabled={busy} onClick={() => setConfirmPage(null)} style={{...control, marginLeft:6}}>Cancel</window.AH_DS.Btn>
      </div>}
    </div>)}
    {review && review.pages.length === 0 && <p>No protected editor records in this conversation.</p>}
    {review?.protection.tracking_state === 'unknown' && <div style={window.AH_DS.styles.muted}>
      <p>Earlier draft activity is not recorded yet. Automatic cleanup remains protected.</p>
      {!confirmTracking ? <window.AH_DS.Btn disabled={busy} style={control} onClick={() => setConfirmTracking(true)}>Review earlier activity…</window.AH_DS.Btn> : <>
        <p>Confirm that you have saved or discarded any earlier unsent drafts in this conversation.
          This starts its inactivity period now. Existing protected editor records stay protected.</p>
        <window.AH_DS.Btn disabled={busy} style={control} onClick={() => changeConversation('resolveConversationTracking')}>Confirm drafts resolved</window.AH_DS.Btn>
        <window.AH_DS.Btn disabled={busy} style={{...control, marginLeft:6}} onClick={() => setConfirmTracking(false)}>Cancel</window.AH_DS.Btn>
      </>}
    </div>}
    {review && <div style={{marginTop:10}}>
      {review.retention.archived_at !== null ? <p>Archived {new Date(review.retention.archived_at * 1000).toLocaleString()}. Saved graph nodes are preserved.</p> :
        <window.AH_DS.Btn disabled={busy || review.protection.protected} style={control} onClick={() => changeConversation('archiveConversation')}>Archive conversation</window.AH_DS.Btn>}
      {review.protection.protected && <p style={window.AH_DS.styles.muted}>Close or resolve protected editors before archiving. Running or unresolved Work also prevents archiving.</p>}
    </div>}
    {review?.next_page_id && <window.AH_DS.Btn disabled={busy} onClick={() => read(review.next_page_id)} style={{...control, marginTop:8}}>More editors</window.AH_DS.Btn>}
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
  // A saved conversation lives on the Workshop canvas. Its row walks there with the canvas's own
  // open interactions (the catalog names the path from the graph), then hands the room to the
  // Studio view, which opens it once the new scope lists it (see 'archhub:reach-conversation').
  const path = Array.isArray(catalog?.workbench_path) ? catalog.workbench_path : [];
  const reach = async root => {
    if (busy || !path.length) return;
    setBusy(true); setError('');
    try {
      const signed = window.ARCHHUB_STUDIO_AUTHORITY;
      if (signed && typeof signed.open === 'function') {
        let canvas = await signed.load();
        const top = canvas?.scope?.trail?.[0]?.root;
        if (top && canvas.scope.current !== top && canvas.scope.current !== path[path.length - 1]) canvas = await signed.open(top);
        for (const step of path) { if (canvas?.scope?.current !== step) canvas = await signed.open(step); }
      } else if (typeof window.ARCHHUB_SCOPE_OPEN === 'function') {
        await window.ARCHHUB_SCOPE_OPEN(path);
        await studioRefreshCanvasInPlace();
      } else throw new Error('The Workshop canvas cannot be opened from here.');
      window.dispatchEvent(new CustomEvent('archhub:reach-conversation', {detail:root}));
      close();
    } catch (failure) { setError(failure.message || 'Could not open the Workshop canvas.'); }
    finally { setBusy(false); }
  };
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
    <window.AH_DS.Btn ref={button} onClick={toggle} aria-label="Conversations" aria-haspopup="dialog" aria-expanded={open}
      title={selected?.label || 'Conversations'} style={{...control, border:0, maxWidth:180,
        overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', cursor:'pointer'}}>
      {selected?.label || 'Conversations'} <span aria-hidden="true">⌄</span>
    </window.AH_DS.Btn>
    {open && <div role="dialog" aria-label="Workshop conversations" style={{position:'absolute', top:'calc(100% + 6px)',
      right:0, zIndex:300, width:340, maxWidth:'calc(100vw - 70px)', maxHeight:'min(70vh, 600px)', overflowY:'auto',
      background:LM.bgPanel, color:LM.ink, border:`1px solid ${LM.line}`, borderRadius:LM.rad.md,
      boxShadow:'0 12px 32px #0008', padding:12, fontSize:12}}>
      <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:8}}>
        <strong>Conversations</strong>
        {anchor && <window.AH_DS.Btn disabled={busy} onClick={() => read()} title="Refresh conversations" aria-label="Refresh conversations"
          style={{...control, display:'grid', placeItems:'center', padding:5}}><StudioHeaderIcon name="reload"/></window.AH_DS.Btn>}
      </div>
      <p style={{color:LM.inkSoft, margin:'0 0 10px', lineHeight:1.5}}>Saved rooms and their participants. A saved room does not mean its agents are running.</p>
      <div style={{display:'grid', gap:4}}>
        <window.AH_DS.Btn disabled={busy} onClick={() => choose('')} aria-current={!conversationRoot ? 'true' : undefined}
          style={{...control, textAlign:'left', cursor:'pointer', background:!conversationRoot ? LM.accentDim : LM.bg}}>
          Current conversation
        </window.AH_DS.Btn>
        {(catalog?.conversations || workshops.map(row => ({root:row.root, title:row.label}))).map(row => {
          const visible = workshops.some(item => item.root === row.root);
          const reachable = visible || path.length > 0;
          return <window.AH_DS.Btn key={row.root} disabled={!reachable || busy}
            onClick={() => visible ? choose(row.root) : reach(row.root)}
            aria-current={conversationRoot === row.root ? 'true' : undefined}
            title={visible ? row.title : reachable ? 'Open the Workshop canvas and this conversation'
              : 'Open the Workshop canvas to reach this conversation'}
            style={{...control, textAlign:'left', overflowWrap:'anywhere', cursor:reachable ? 'pointer' : 'default',
              background:conversationRoot === row.root ? LM.accentDim : LM.bg}}>
            <div>{row.title}</div>
            {row.participant_roots && <small style={window.AH_DS.styles.muted}>{row.participant_roots.length} participants{!visible ? ' · on Workshop canvas' : ''}</small>}
          </window.AH_DS.Btn>;
        })}
      </div>
      {catalog?.page_after && <window.AH_DS.Btn disabled={busy} onClick={() => read('showFirstConversationPage')} style={{...control, marginTop:8}}>First page</window.AH_DS.Btn>}
      {catalog?.has_more && <window.AH_DS.Btn disabled={busy} onClick={() => read('loadNextConversationPage')} style={{...control, margin:'8px 0 0 6px'}}>More conversations</window.AH_DS.Btn>}
      {catalog?.can_create && !creating && <window.AH_DS.Btn disabled={busy} onClick={() => { setCreating(true); setChosen([]); }}
        style={{...control, width:'100%', marginTop:12, cursor:'pointer'}}>＋ New conversation</window.AH_DS.Btn>}
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
        {!creation?.accepted && <window.AH_DS.Btn type="submit" disabled={busy || !catalog?.can_create || !title.trim()}
          style={{...control, marginTop:6}}>{busy ? 'Saving…' : error ? 'Retry creation' : 'Create conversation'}</window.AH_DS.Btn>}
        {creation?.accepted && <div role="status" style={{marginTop:8, lineHeight:1.5}}>
          Saved: {creation.title}. {creation.error || creation.notice || creation.warning}
          {workshops.some(row => row.root === creation.root) && <window.AH_DS.Btn type="button" onClick={() => choose(creation.root)}
            style={{...control, margin:'6px 0'}}>Open conversation</window.AH_DS.Btn>}
          <window.AH_DS.Btn type="button" onClick={() => { setSaved(null); setTitle(''); setChosen([]); setCreating(false); }}
            style={{...control, margin:'6px'}}>Done</window.AH_DS.Btn>
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

// Workshop opens through the tool rail or a selection-panel handoff. A Studio session itself stays
// on Canvas; chat lives in the selection panel composer, not in a session-level tab.
const workshopModeRoom = (workshops, conversationRoot) => conversationRoot ||
  workshops.find(row => row?.is_general === true && row.root)?.root || workshops.find(row => row?.root)?.root || '';
// The owner states why no Workshop room is available (workshop_scope.unavailable).
const workshopUnavailableText = reason => (typeof reason === 'string' && reason.trim()) ||
  'No Workshop conversation in this scope';
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
const WsHeader = ({ toolbarRef, session, model, openTabs, sessionRows = LM_SESSIONS, setOpenId, closeTab, mode, setMode, setPickerOpen, onHome, onNewSession, onSettings, systemAllowed = false,
  systemArrangeSummary = null, projection = null,
  workshops = [], conversationRoot = '', setConversationRoot, workshopModel, conversationNotice = '',
  workshopUnavailable = '' }) => {
  const [sessionsOpen,setSessionsOpen] = React.useState(false);
  if (mode === 'system') return <window.AH_DS.Frame as="header" data-system-graph="" data-system-header=""
    style={{gridColumn:'1 / -1',gridRow:'1',display:'flex',alignItems:'center',gap:8,padding:'0 12px',background:LM.bg,borderBottom:`1px solid ${LM.lineSoft}`,userSelect:'none'}}>
    <window.AH_DS.Btn sm kind="ghost" onClick={onSettings} title="Back to Settings · Esc">Settings</window.AH_DS.Btn>
    <span>▸</span><strong>System</strong><span style={{fontSize:11,color:LM.inkSoft}}>{projection?.error?'Unavailable':projection?.pending?'Reading…':projection?.canvas?'live':''}</span><span style={window.AH_DS.styles.fill}/><span ref={toolbarRef}/>
  </window.AH_DS.Frame>;
  return <window.AH_DS.Frame as="header" data-session-header="" style={{gridColumn:'1 / -1',gridRow:'1',display:'flex',alignItems:'center',gap:8,padding:'0 12px',background:LM.bg,borderBottom:`1px solid ${LM.lineSoft}`,userSelect:'none',overflow:'visible',position:'relative',zIndex:10}}>
    {session?.project && <><span style={{color:LM.inkSoft}}>{session.project}</span><span>▸</span></>}
    <window.AH_DS.Btn sm kind="ghost" title="Sessions · Ctrl+K" aria-expanded={sessionsOpen} onClick={()=>setSessionsOpen(value=>!value)}>{session?.title || 'Canvas'}</window.AH_DS.Btn>
    {sessionsOpen && <window.AH_DS.Card data-session-menu="" style={{position:'absolute',top:36,left:12,minWidth:248,zIndex:20,padding:6}}>
      {openTabs.map(id=>{const row=sessionRows.find(s=>s.id===id);return row && <div key={id} style={{display:'flex'}}>
        <window.AH_DS.Btn sm kind="ghost" onClick={()=>{setOpenId(id);setSessionsOpen(false);}}>{row.title}</window.AH_DS.Btn>
        <window.AH_DS.Btn sm kind="ghost" title={'Close '+row.title} aria-label={'Close '+row.title} onClick={()=>closeTab(id)}>×</window.AH_DS.Btn></div>;})}
      <window.AH_DS.Btn sm kind="ghost" onClick={onNewSession || onHome}>New session</window.AH_DS.Btn>
      <window.AH_DS.Btn sm kind="ghost" onClick={onHome}>Home</window.AH_DS.Btn>
    </window.AH_DS.Card>}
    <span style={window.AH_DS.styles.fill}/>{conversationNotice && <span role="status">{conversationNotice}</span>}<span ref={toolbarRef}/>
  </window.AH_DS.Frame>;
};




// Hoverable button wrappers (cards style — actually responsive)


const ModelStrip = ({ model, setPickerOpen, compact, inline }) => {
  const label = inline && (model.unknown || !model.name || model.name.includes('/')) ? 'Choose model' : model.name;
  const [hover, setHover] = React.useState(false);
  return (
  <window.AH_DS.Btn
    onClick={(e) => { e.stopPropagation(); setPickerOpen(true); }}
    onMouseEnter={() => setHover(true)}
    onMouseLeave={() => setHover(false)}
    style={{
    display:'flex', alignItems:'center', gap: compact ? 8 : 12,
    padding: compact ? '4px 10px 4px 6px' : '8px 14px 8px 8px',
    background: hover ? LM.bgSoft : LM.bg,
    border:`1px solid ${hover ? LM.accent+'66' : LM.line}`, borderRadius:7,
    color:LM.ink, cursor:'pointer', fontFamily:LM.sans, minWidth:inline ? 0 : compact ? 280 : 380,
    transition:`background ${LM.dur.fast}ms, border-color ${LM.dur.fast}ms`,
  }}>
    <span style={{
      width: compact ? 22 : 28, height: compact ? 22 : 28, borderRadius:LM.rad.sm,
      background: model.col, color:((window.AH && window.AH.onFill) || '#180f08'), display:'grid', placeItems:'center',
      fontFamily:LM.mono, fontSize: compact ? 11 : 13, fontWeight:700,
    }}>{model.name[0]}</span>
    <div style={{ flex:1, textAlign:'left', lineHeight:1.15 }}>
      <div style={{ fontSize: compact ? 12.5 : 13.5, fontWeight:500 }}>{label}</div>
      <div style={{ display:inline ? 'none' : undefined, fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.05em' }}>
        {[model.vendor, model.ctx ? 'ctx ' + model.ctx : '', model.tag].filter(Boolean).join(' \u00b7 ')}
      </div>
    </div>
    {/* Draw or omit: no latency dot until a latency was measured. */}
    {model.latency != null && <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.ok, letterSpacing:'0.08em' }}>{'\u25cf ' + model.latency + 'ms'}</span>}
    <span style={{ color:LM.inkSoft, fontSize:11, marginLeft:2 }}>▾</span>
  </window.AH_DS.Btn>
  );
};

// ──────────────────────── NODE CANVAS ────────────────────────
const SOCKET_TOP = 42;
const NODE_CARD_W = 224;
const SOCKET_STEP = 22;
const SOCKET_R = 5.5;
const LM_CANVAS_TOKENS = typeof LM !== 'undefined' ? LM : {};
const LM_FS_SOURCE = LM_CANVAS_TOKENS.fs && typeof LM_CANVAS_TOKENS.fs === 'object' ? LM_CANVAS_TOKENS.fs : {};
const LM_FS_LABEL = LM_FS_SOURCE.label || {sz:11, ln:14, wt:500, letter:'.04em'};
const LM_FS_DATASM = LM_FS_SOURCE.dataSm || {sz:11, ln:14, wt:400};
// DSYS-078 is a thin skin on every real graph card; content and handlers stay graph-owned.
const canvasCardSurface = (needsUser = false) => ({background:LM.surf,
  boxShadow:needsUser ? `${LM.elev.e2}, ${LM.glow.warn}` : LM.elev.e2, borderRadius:12});
const canvasNeedsUser = node => ['needs-user', 'needs_user', 'awaiting_approval', 'waiting_approval'].includes(node?.state || node?.status);
const canvasStatusColor = node => canvasNeedsUser(node) ? LM.warn :
  /done|complete|ready|success/.test(node?.state || node?.status || '') ? LM.ok :
  /running|working/.test(node?.state || node?.status || '') ? LM.accent : LM.inkSoft;
const canvasStatusText = node => {
  const value=String(node?.status || node?.state || '');
  return /^(?:open|planned|queued|claimed)$/i.test(value) ? 'ready to start' : value.replaceAll('_',' ');
};
const canvasAgentRecord = node => {
  const owner = window.ARCHHUB_STUDIO_AUTHORITY || window.ARCHHUB_EXISTING_WORKSHOP;
  const state = owner?.getSnapshot?.() || {};
  const participants = state.workshop?.participants || [];
  const identities = [node.id, node.agent_id, node.agent_session].filter(Boolean);
  const agent = participants.find(row => row.is_agent !== false &&
    [row.root,row.id,row.app_root,row.account_root,row.node_root,row.agent_root].filter(Boolean).some(id => identities.includes(id)));
  if (!agent) return null;
  const assignment = (state.workshop?.assignments || []).find(row => row.agent_session === (agent.root || agent.id));
  const graph = state.topology?.graph || state.graph || {};
  const task = (graph.nodes || []).find(row => row.id === assignment?.work);
  return {...agent, taskTitle:task?.title || task?.name || '',
    modelLabel:window.ARCHHUB_WORKSHOP_AGENT_MODEL?.(agent, state) || 'Unavailable'};
};

// Ports sit in a band BELOW the card's content (never over its title, summary or
// parameters): one row per port pair. Each card reports where its band starts, and a
// wire ends at the centre of its port's row in that band.
const PORT_BAND_PAD = 4;
const portRowCentre = (i) => PORT_BAND_PAD + i * SOCKET_STEP + SOCKET_STEP / 2;
const portY = (bandTop, i) => (Number.isFinite(bandTop) ? bandTop : SOCKET_TOP) + portRowCentre(i);
const nodeCardTitle = n => String(n?.title || n?.name || 'Node');
const nodeCardSubtitle = (n, cat) => {
  if (n?.application) return n.subtitle || 'Application settings';
  const role = cat?.role || cat?.label || 'Node';
  if (typeof n?.subtitle === 'string' && n.subtitle.trim()) return n.subtitle;
  if (n?.cat === 'watch' || n?.engine === 'watch.preview' || n?.sub === 'watch.preview') {
    const as = (n.params || []).find(row => row.k === 'as')?.v || 'table';
    return 'Watch · as ' + as;
  }
  const host = (n?.host || n?.source || '').replace(/\bid[:=]\S+/gi, '').trim();
  return [role, host].filter(Boolean).join(' · ');
};
const nodeIsWatch = n => !!n && (n.cat === 'watch' || n.engine === 'watch.preview' || n.sub === 'watch.preview');
const visibleNodeParams = n => (n.params || []).filter(row => {
  const key = String(row.k || row.label || '').toLowerCase();
  if (nodeIsWatch(n) && key === 'watchsize') return false;
  const hidden = window.ARCHHUB_INTERNAL_PARAM_KEYS;
  return !(hidden && typeof hidden.has === 'function' && hidden.has(key));
});
const socketShapeOf = (t, list) => window.socketShapeOf ? window.socketShapeOf(t, list) : (t === 'trigger' || t === 'event' ? 'triangle' : list ? 'diamond' : t === 'any' ? 'any' : 'circle');
const socketTypeLabel = t => window.socketTypeLabel ? window.socketTypeLabel(t) : ((window.pmType && window.pmType(t)?.label) || String(t || 'Any'));
// Snap to grid (design CanvasMenu) uses the dot grid's own 20-unit pitch.
const CANVAS_GRID = 20;
// What an Undo or Redo changed, in plain words, read from the canvas before and after it.
const canvasHistoryToast = (operation, before, after) => {
  const verb = operation === 'redo' ? 'Redid' : 'Undid';
  const titles = graph => new Map((graph?.nodes || []).map(node => [node.id, node.title || node.id]));
  const was = titles(before), now = titles(after);
  const back = [...now.keys()].filter(id => !was.has(id)).map(id => now.get(id));
  const gone = [...was.keys()].filter(id => !now.has(id)).map(id => was.get(id));
  const name = list => '\u2018' + list[0] + '\u2019' + (list.length > 1 ? ' and ' + (list.length - 1) + ' more' : '');
  // A collapsed group hides its members: a card appearing/disappearing may be
  // membership, not creation/deletion. Describe the action being undone/redone.
  const membership = graph => new Map((graph?.nodes || []).filter(group => was.has(group.id) && now.has(group.id)).flatMap(group =>
    (group.members || []).map(member => [typeof member === 'string' ? member : member.id || member.root,
      {group:group.id, title:typeof member === 'string' ? member : member.title || member.label || member.id || member.root}])));
  const wasIn = membership(before), nowIn = membership(after);
  const joined = [...nowIn].filter(([id, member]) => was.has(id) && wasIn.get(id)?.group !== member.group).map(([id]) => was.get(id));
  const left = [...wasIn].filter(([id, member]) => now.has(id) && nowIn.get(id)?.group !== member.group).map(([id]) => now.get(id));
  if (joined.length) return verb + ': ' + (operation === 'redo' ? 'added ' : 'removed ') + name(joined) + (operation === 'redo' ? ' to the group' : ' from the group');
  if (left.length) return verb + ': ' + (operation === 'redo' ? 'removed ' : 'added ') + name(left) + (operation === 'redo' ? ' from the group' : ' to the group');
  // Undo that brings a card back took back its deletion; one that removes a card took back its creation.
  if (back.length) return verb + ': ' + (operation === 'redo' ? 'added ' : 'deleted ') + name(back);
  if (gone.length) return verb + ': ' + (operation === 'redo' ? 'deleted ' : 'added ') + name(gone);
  const wires = (after?.wires || []).length - (before?.wires || []).length;
  if (wires) return verb + ': ' + ((wires > 0) === (operation === 'redo') ? 'connected ' : 'removed ') +
    Math.abs(wires) + ' wire' + (Math.abs(wires) === 1 ? '' : 's');
  const moved = (after?.nodes || []).filter(node => { const held = (before?.nodes || []).find(row => row.id === node.id);
    return held && (held.x !== node.x || held.y !== node.y); }).length;
  if (moved) return verb + ': moved ' + moved + ' node' + (moved === 1 ? '' : 's');
  return verb + ' the last change';
};
// Wheel zoom: never below 30% (cards stay readable), and one wheel notch is a gentle, even step.
const CANVAS_ZOOM_MIN = 0.3, CANVAS_ZOOM_MAX = 2;
const canvasClampZoom = value => Math.max(CANVAS_ZOOM_MIN, Math.min(CANVAS_ZOOM_MAX, value));
const canvasWheelZoom = (zoom, deltaY) => canvasClampZoom(+(zoom * Math.exp(-deltaY * 0.001)).toFixed(3));
// The pan and zoom a canvas scope was left at. Switching to Chat unmounts the canvas; coming
// back reads the view from here instead of resetting it.
const CANVAS_VIEWS = new Map();
const readCanvasView = scope => CANVAS_VIEWS.get(scope) || {pan:{x:14, y:12}, zoom:0.66};
// Dimming (design README "the rest dim"): only while something on the canvas is focused or
// selected. Nothing focused dims nothing; a focused wire keeps both of its ends lit.
const canvasDimmedIds = (nodeIds, wires, focusId, selectedIds = []) => {
  const lit = new Set(selectedIds.filter(id => nodeIds.includes(id)));
  if (nodeIds.includes(focusId)) {
    lit.add(focusId);
    for (const wire of wires) {
      if (wire.from?.[0] === focusId) lit.add(wire.to?.[0]);
      if (wire.to?.[0] === focusId) lit.add(wire.from?.[0]);
    }
  }
  const focusWire = wires.find((wire, i) => (wire.id && wire.id === focusId) || 'wire:' + i === focusId);
  if (focusWire) { lit.add(focusWire.from?.[0]); lit.add(focusWire.to?.[0]); }
  if (!lit.size) return new Set();
  return new Set(nodeIds.filter(id => !lit.has(id)));
};
const pinnedArrangeMessage = (pinnedCount, movedCount = 0) => pinnedCount === 1
  ? `Arrange kept 1 pinned card in place${movedCount ? ` and moved ${movedCount}.` : '.'}`
  : `Arrange kept ${pinnedCount} pinned cards in place${movedCount ? ` and moved ${movedCount}.` : '.'}`;

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
// DSYS-078 has a 56px top bar; equal 80px clear bands centre the graph vertically.
const CANVAS_FIT_TOP = 80, CANVAS_FIT_BOTTOM = 80;
const canvasFitBounds = (ids, positions, sizes, viewport, maxZoom = 2) => {
  const width = viewport.width - 48, height = viewport.height - CANVAS_FIT_TOP - CANVAS_FIT_BOTTOM;
  const left = Math.min(...ids.map(id => positions[id].x)), top = Math.min(...ids.map(id => positions[id].y));
  const right = Math.max(...ids.map(id => positions[id].x + sizes[id].w));
  const bottom = Math.max(...ids.map(id => positions[id].y + sizes[id].h));
  const zoom = Math.min(maxZoom, width / Math.max(1, right - left), height / Math.max(1, bottom - top));
  if (!ids.length || !Number.isFinite(zoom) || zoom < 0.01 || width < 1 || height < 1) {
    throw new Error('The selected bounds are too large for this view. Fit a smaller selection.');
  }
  return {zoom, pan:{x:24 + width / 2 - (left + right) * zoom / 2,
    y:CANVAS_FIT_TOP + height / 2 - (top + bottom) * zoom / 2}, bounds:{left, top, right, bottom}};
};
const canvasRevealBounds = (ids, positions, sizes, viewport, currentZoom, currentPan) => {
  const fit = canvasFitBounds(ids, positions, sizes, viewport);
  const targetZoom = canvasClampZoom(Math.min(currentZoom, fit.zoom));
  const usable = {left:24, right:viewport.width - 24, top:CANVAS_FIT_TOP, bottom:viewport.height - CANVAS_FIT_BOTTOM};
  const bounds = fit.bounds;
  const pan = {x:currentPan.x, y:currentPan.y};
  const adjust = (low, high, viewLow, viewHigh, held) => {
    const span = high - low, viewSpan = viewHigh - viewLow;
    if (span > viewSpan) return viewLow + viewSpan / 2 - (low + high) / 2;
    if (low < viewLow) return held + (viewLow - low);
    if (high > viewHigh) return held - (high - viewHigh);
    return held;
  };
  const left = pan.x + bounds.left * targetZoom, right = pan.x + bounds.right * targetZoom;
  const top = pan.y + bounds.top * targetZoom, bottom = pan.y + bounds.bottom * targetZoom;
  pan.x = adjust(left, right, usable.left, usable.right, pan.x);
  pan.y = adjust(top, bottom, usable.top, usable.bottom, pan.y);
  return {zoom:targetZoom, pan, bounds};
};
const computeLayoutSummary = (ids, positions, sizes, wires, viewport, zoom, pan) => {
  const boxes = ids.filter(id => positions[id] && sizes[id]).map(id => ({
    id, x:positions[id].x, y:positions[id].y, w:sizes[id].w, h:sizes[id].h,
  }));
  const overlaps = [];
  for (let a = 0; a < boxes.length; a += 1) for (let b = a + 1; b < boxes.length; b += 1) {
    const p = boxes[a], q = boxes[b];
    if (p.x < q.x + q.w && q.x < p.x + p.w && p.y < q.y + q.h && q.y < p.y + p.h) overlaps.push([p.id, q.id]);
  }
  // The viewport is the canvas's own rect (the inspector is already outside it): judge clipping
  // against the same reserved bands canvasFitBounds fits into, with a 2 px rounding tolerance.
  const usable = viewport ? {left:24 - 2, top:CANVAS_FIT_TOP - 2,
    right:viewport.width - 24 + 2, bottom:viewport.height - CANVAS_FIT_BOTTOM + 2} : null;
  const clipped = usable ? boxes.filter(box => {
    const left = pan.x + box.x * zoom, top = pan.y + box.y * zoom;
    const right = pan.x + (box.x + box.w) * zoom, bottom = pan.y + (box.y + box.h) * zoom;
    return left < usable.left || top < usable.top || right > usable.right || bottom > usable.bottom;
  }).length : 0;
  const byId = new Map(boxes.map(box => [box.id, box]));
  const segments = wires.map(wire => {
    const from = byId.get(wire.from?.[0]), to = byId.get(wire.to?.[0]);
    return from && to ? {
      a:{x:from.x + from.w, y:from.y + from.h / 2},
      b:{x:to.x, y:to.y + to.h / 2},
    } : null;
  }).filter(Boolean);
  const ccw = (a, b, c) => (c.y - a.y) * (b.x - a.x) > (b.y - a.y) * (c.x - a.x);
  const crosses = (one, two) => ccw(one.a, two.a, two.b) !== ccw(one.b, two.a, two.b) &&
    ccw(one.a, one.b, two.a) !== ccw(one.a, one.b, two.b);
  let crossings = 0;
  for (let a = 0; a < segments.length; a += 1) for (let b = a + 1; b < segments.length; b += 1) {
    if (crosses(segments[a], segments[b])) crossings += 1;
  }
  return {cards:boxes.length, overlaps:overlaps.length, clipped, crossings};
};
// Arrange is graph-topological, not frame-topological: old projection group
// labels are decoration only. Sources land left, sinks land right, and each
// layer is ordered by the barycenter of neighbouring layers to reduce crossings.
const canvasArrangePositions = (ids, positions, sizes, allIds, wires, groupOf = null) => {
  const barycentrePasses = 6;
  const byPlace = (a, b) => positions[a].y - positions[b].y || positions[a].x - positions[b].x || a.localeCompare(b);
  const placed = [...ids].sort(byPlace);
  const stable = placed;
  const rank = new Map(stable.map((id, index) => [id, index]));
  const incoming = new Map(stable.map(id => [id, new Set()])), outgoing = new Map(stable.map(id => [id, new Set()]));
  const indegree = new Map(stable.map(id => [id, 0]));
  for (const wire of wires) {
    const from = wire.from?.[0], to = wire.to?.[0];
    if (!rank.has(from) || !rank.has(to) || from === to || outgoing.get(from).has(to)) continue;
    outgoing.get(from).add(to); incoming.get(to).add(from); indegree.set(to, indegree.get(to) + 1);
  }
  const indeg = new Map(indegree), queue = stable.filter(id => indeg.get(id) === 0).sort((a, b) => rank.get(a) - rank.get(b));
  const topo = [];
  while (queue.length) {
    const id = queue.shift(); topo.push(id);
    for (const target of [...outgoing.get(id)].sort((a, b) => rank.get(a) - rank.get(b))) {
      indeg.set(target, indeg.get(target) - 1);
      if (indeg.get(target) === 0) queue.push(target);
    }
    queue.sort((a, b) => rank.get(a) - rank.get(b));
  }
  for (const id of stable) if (!topo.includes(id)) topo.push(id);
  const layer = new Map(stable.map(id => [id, 0]));
  for (const id of topo) for (const target of outgoing.get(id)) {
    layer.set(target, Math.max(layer.get(target), layer.get(id) + 1));
  }
  const byLayer = new Map();
  for (const id of stable) {
    const key = layer.get(id);
    if (!byLayer.has(key)) byLayer.set(key, []);
    byLayer.get(key).push(id);
  }
  const layers = [...byLayer.keys()].sort((a, b) => a - b).map(key => byLayer.get(key).sort((a, b) => rank.get(a) - rank.get(b)));
  const orderIndex = () => new Map(layers.flatMap((ids, layerIndex) => ids.map((id, index) => [id, {layer:layerIndex, index}])));
  for (let pass = 0; pass < barycentrePasses; pass += 1) {
    let index = orderIndex();
    for (let li = 1; li < layers.length; li += 1) {
      layers[li].sort((a, b) => {
        const ba = [...incoming.get(a)].filter(id => index.has(id)).reduce((sum, id) => sum + index.get(id).index, 0) / Math.max(1, [...incoming.get(a)].filter(id => index.has(id)).length);
        const bb = [...incoming.get(b)].filter(id => index.has(id)).reduce((sum, id) => sum + index.get(id).index, 0) / Math.max(1, [...incoming.get(b)].filter(id => index.has(id)).length);
        return ba - bb || rank.get(a) - rank.get(b);
      });
    }
    index = orderIndex();
    for (let li = layers.length - 2; li >= 0; li -= 1) {
      layers[li].sort((a, b) => {
        const ba = [...outgoing.get(a)].filter(id => index.has(id)).reduce((sum, id) => sum + index.get(id).index, 0) / Math.max(1, [...outgoing.get(a)].filter(id => index.has(id)).length);
        const bb = [...outgoing.get(b)].filter(id => index.has(id)).reduce((sum, id) => sum + index.get(id).index, 0) / Math.max(1, [...outgoing.get(b)].filter(id => index.has(id)).length);
        return ba - bb || rank.get(a) - rank.get(b);
      });
    }
  }
  const colGap = 76, rowGap = 44, local = {};
  const visualColumns = [];
  for (let li = 0; li < layers.length; li += 1) {
    const ids = layers[li];
    const maxRows = ids.length > 8 ? 5 : ids.length;
    for (let start = 0; start < ids.length; start += maxRows) {
      visualColumns.push(ids.slice(start, start + maxRows));
    }
  }
  const columnWidths = visualColumns.map(ids => Math.max(0, ...ids.map(id => sizes[id].w)));
  const columnX = [];
  for (let ci = 0, x = 0; ci < visualColumns.length; ci += 1) {
    columnX[ci] = x;
    x += columnWidths[ci] + colGap;
  }
  let packedWidth = Math.max(0, ...visualColumns.map((ids, ci) => columnX[ci] + columnWidths[ci]));
  let packedHeight = 0;
  for (let ci = 0; ci < visualColumns.length; ci += 1) {
    let y = 0;
    for (const id of visualColumns[ci]) {
      local[id] = {x:columnX[ci], y};
      y += sizes[id].h + rowGap;
    }
    packedHeight = Math.max(packedHeight, Math.max(0, y - rowGap));
  }
  const originX = Math.round(Math.min(...stable.map(id => positions[id].x)));
  let originY = Math.round(Math.min(...stable.map(id => positions[id].y)));
  const included = new Set(stable), obstacles = allIds.filter(id => !included.has(id));
  const gap = 48;
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
const canvasNodeBox = (node, positions, heights = {}) => {
  const p = positions[node.id] || node;
  const w = (typeof isWorkshopGraphNode === 'function' && isWorkshopGraphNode(node)) ? (node.w || 320) : Number.isFinite(node.w) ? node.w : 220;
  const h = Number.isFinite(heights[node.id]) ? heights[node.id] : Number.isFinite(node.h) ? node.h : 110;
  return {id:node.id, x:p.x, y:p.y, w, h, group:node.group || ''};
};
const isSessionNodeShape = node => /^session$/i.test(String(node?.kind || node?.assembly || node?.cat || ''));
const canvasGroupBounds = (nodes, positions, heights, group, exclude = new Set()) => {
  const boxes = nodes.filter(node => ((node.group || '') === group ||
      (node.id === group && node.composition && !isSessionNodeShape(node))) && !exclude.has(node.id))
    .map(node => canvasNodeBox(node, positions, heights))
    .filter(box => [box.x, box.y, box.w, box.h].every(Number.isFinite));
  if (!boxes.length) return null;
  const left = Math.min(...boxes.map(box => box.x)) - 18;
  const top = Math.min(...boxes.map(box => box.y)) - 18;
  const right = Math.max(...boxes.map(box => box.x + box.w)) + 18;
  const bottom = Math.max(...boxes.map(box => box.y + box.h)) + 18;
  return {group, left, top, right, bottom};
};
const canvasPointInBounds = (point, bounds) => !!bounds &&
  point.x >= bounds.left && point.x <= bounds.right && point.y >= bounds.top && point.y <= bounds.bottom;
const canvasGroupMembershipDelta = (nodes, positions, heights, movedIds) => {
  const moved = new Set(movedIds || []);
  const groups = [...new Set(nodes.flatMap(node => [
    node.group || '',
    node.composition && !isSessionNodeShape(node) ? node.id : '',
  ]).filter(Boolean))];
  const before = {}, after = {};
  for (const node of nodes) {
    if (!moved.has(node.id)) continue;
    const box = canvasNodeBox(node, positions, heights);
    const center = {x:box.x + box.w / 2, y:box.y + box.h / 2};
    let next = node.group || '';
    if (next && !canvasPointInBounds(center, canvasGroupBounds(nodes, positions, heights, next, new Set([node.id])))) next = '';
    if (!next) {
      const hit = groups.map(group => canvasGroupBounds(nodes, positions, heights, group, new Set([node.id])))
        .filter(Boolean).find(bounds => canvasPointInBounds(center, bounds));
      next = hit?.group || '';
    }
    if ((node.group || '') !== next) { before[node.id] = node.group || ''; after[node.id] = next; }
  }
  return Object.keys(after).length ? {before, after} : null;
};
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

const NodeCanvas = ({ toolbarHost, libraryMode = false, focusId, setFocusId, pendingReveal = null, clearPendingReveal = null, setLibraryOpen, userNodes = [], addNodeFromLibrary, model, system = false, onViewportChange = null, fitOnOpen = false, onSystemArrangeSummary = null, themeEpoch = 0 }) => {
  const authorityState = useStudioProjection();
  const workshopSnapshot = typeof useWorkshopProjection === 'function' ? useWorkshopProjection() : null;
  const workshopDescriptor = workshopSnapshot?.workshops?.find(row=>row.root===workshopSnapshot.workshop?.root);
  const workshopModel = workshopDescriptor ? window.ARCHHUB_WORKSHOP_MODEL?.({state:workshopSnapshot,descriptor:workshopDescriptor}) : null;
  const projectedGraph = authorityState?.graph || LM_GRAPH;
  const [draggingNode, setDraggingNode] = React.useState(false);
  const setSystemArrangeSummary = onSystemArrangeSummary;
  // The owner marks every top-level card with who placed it (graph shape, not a list of names).
  // The canvas draws the user's cards; the application's own -- map domains, core values,
  // registries, agent sessions -- are the founder's System view, framed by domain. Only the
  // founder's view holds them, and only the founder is offered the switch.
  const showingSystem = system && systemAllowed(authorityState?.canvas, projectedGraph);
  const graph = React.useMemo(() => {
    const nodes = projectedGraph.nodes.filter(node =>
      typeof node.application !== 'boolean' || node.application === showingSystem);
    const drawn = new Set(nodes.map(node => node.id));
    return {...projectedGraph, nodes,
      wires:projectedGraph.wires.filter(wire => drawn.has(wire.from?.[0]) && drawn.has(wire.to?.[0]))};
  }, [projectedGraph, showingSystem]);
  const authority = window.ARCHHUB_STUDIO_AUTHORITY;
  const normal = !authority && window.ARCHHUB_EXISTING_WORKSHOP;
  const [wireStart, setWireStart] = React.useState(null);
  const wireStartRef = React.useRef(null);
  const setWireStartState = value => { wireStartRef.current = value; setWireStart(value); };
  const [wireError, setWireError] = React.useState('');
  const [wirePreview, setWirePreview] = React.useState(null);
  React.useEffect(() => { setWireStartState(null); setWirePreview(null); setWireError(''); }, [authorityState?.canvas?.scope?.current]);
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
      const waitingStart = wireStartRef.current;
      if (!waitingStart?.reverse) { setWireStartState({root, port}); return; }
      // An input chosen first: this output completes the wire when that input is one of its choices.
      const waiting = waitingStart.port.owner || waitingStart.root;
      if (normal && !port.connect_choices.some(choice => choice.id === waitingStart.port.id && (choice.owner ?? waiting) === waiting)) {
        setWireError('This output cannot feed ' + waitingStart.port.label + '.'); return;
      }
      return joinWire(root, port, waitingStart.root, waitingStart.port);
    }
    // Either end may be chosen first: an input with no output waiting waits for its output.
    const waitingStart = wireStartRef.current;
    if (!waitingStart || waitingStart.reverse) { setWireStartState({root, port, reverse:true}); return; }
    return joinWire(waitingStart.root, waitingStart.port, root, port);
  };
  // A group's member port wires its member (the port's owner), never the group card itself.
  const joinWire = async (card, output, other, input) => {
    const source = output.owner || card, target = input.owner || other;
    try {
      if (authority) await authority.connect(source, output.id, target, input.id);
      else await normal.connectTopology(source, output.id, target, input.id);
      setWireStartState(null);
    } catch (error) { setWireError(window.AH_DS.errorText(error.message || 'The connection was refused.')); }
  };
  const actionCanvas = authorityState?.canvas || {};
  const historyDecorator = typeof decorateHistoryNode === 'function' ? decorateHistoryNode : node => node;
  const allNodes = React.useMemo(() => [...graph.nodes, ...userNodes].map(node =>
    historyDecorator(node, actionCanvas)), [graph.nodes, userNodes, actionCanvas?.action_history]);
  const selectableNodeIds = React.useMemo(() => new Set(allNodes
    .filter(node => !String(node.id || '').startsWith('app:system-tool:'))
    .map(node => node.id)), [allNodes]);
  const wireActionRef = React.useRef({useSocket:null, nodes:[]});
  wireActionRef.current = {useSocket, nodes:allNodes};
  // Where each card's port band starts (card-local px), reported by the card itself.
  const [portBands, setPortBands] = React.useState({});
  // Each card's drawn height (content + port band): frames and the no-overlap pass use it, never n.h.
  const [cardHeights, setCardHeights] = React.useState({});
  const setPortBand = (id, top, height) => {
    if (Number.isFinite(top)) setPortBands(held => held[id] === top ? held : {...held, [id]:top});
    if (Number.isFinite(height) && height > 0) setCardHeights(held => held[id] === height ? held : {...held, [id]:height});
  };
  const scopeKey = studioCanvasScope(authorityState?.canvas);
  const mountedScope = React.useRef(scopeKey);
  const alive = React.useRef(true);
  const saving = React.useRef(false);
  const dragRef = React.useRef(null);
  const wireDragRef = React.useRef(null);
  const suppressWireClick = React.useRef(false);
  const canvasRequestState = authorityState?.error ? 'error' : !graph.nodes.length && authorityState?.pending ? 'waiting' : graph.nodes.length ? 'loaded' : 'empty';
  const wrapRef = React.useRef(null);
  const saveRef = React.useRef(null);
  // What a burst of drags holds until the canvas goes still, and whether the chip
  // must say so. Nothing here blocks the canvas: the preview is already drawn.
  const burstRef = React.useRef(null);
  const burstTimer = React.useRef(null);
  const suppressNodeClick = React.useRef(false);
  const MAX_LAYOUT_NODES = 2048;
  const [selectedIds, commitSelectedIds] = React.useState([]);
  const selectedIdsRef = React.useRef(selectedIds);
  const setCanvasSelectedIds = React.useCallback(updater => {
    // A second click can arrive before React applies the first queued update.
    // Keep the current gesture intent synchronously; state updaters may defer or replay.
    const next = typeof updater === 'function' ? updater(selectedIdsRef.current) : updater;
    selectedIdsRef.current = Array.isArray(next) ? next : [];
    commitSelectedIds(selectedIdsRef.current);
  }, []);
  const selected = new Set(selectedIds.filter(id => selectableNodeIds.has(id)));
  const membershipDragRef = React.useRef(null);
  membershipDragRef.current = drag => {
    if (!authority?.moveMember) return false;
    const ids = Object.keys(drag?.last || {});
    if (!ids.length) return false;
    const nextPositions = {...positions, ...drag.last};
    const delta = canvasGroupMembershipDelta(allNodes, nextPositions, cardHeights, ids);
    if (!delta) return false;
    const moves = Object.keys(delta.after).filter(id => delta.before[id] !== delta.after[id]);
    if (!moves.length) return false;
    menuTask(async () => {
      for (const memberId of moves) await authority.moveMember(memberId, delta.before[memberId] || '', delta.after[memberId] || '', drag.last?.[memberId] || null);
      setMenuNotice('Membership saved by the graph owner.');
      return 'Membership saved by the graph owner.';
    });
    return true;
  };
  // Memoized card handlers must use today's action admission, never a captured busy state.
  const menuTaskRef = React.useRef(null);
  const leaveGroupMember = React.useCallback((memberId, groupId, position = null) => {
    const owner = window.ARCHHUB_STUDIO_AUTHORITY || authority || normal;
    // The drop owns focus now; a later response must not steal a newly edited field.
    if (!document.querySelector('[role="dialog"],[role="menu"],dialog[open]')) wrapRef.current?.focus({preventScroll:true});
    return menuTaskRef.current(async () => {
      if (!memberId) throw new Error('Choose a group member to move.');
      if (!owner?.moveMember) throw new Error('Removing a member is unavailable in this connection.');
    const node = allNodes.find(item => item.id === memberId);
    const beforeGroup = node?.group || groupId || '';
      if (!beforeGroup) throw new Error('The member has no group to leave. Refresh the canvas.');
      const result = await owner.moveMember(memberId, beforeGroup, '', position);
      if (!result || result.ok === false) throw new Error(result?.error || 'Membership was not confirmed by the graph owner.');
      if (alive.current && (document.activeElement === document.body || document.activeElement === wrapRef.current) &&
          !document.querySelector('[role="dialog"],[role="menu"],dialog[open]')) {
        wrapRef.current?.focus({preventScroll:true});
      }
      return 'Membership saved by the graph owner.';
    });
  }, [allNodes, authority, normal]);
  // Box selection (the retired '/' canvas's marquee): Shift-drag on empty canvas adds,
  // Alt-drag removes; left-to-right takes whole cards, right-to-left takes touched ones.
  const [marquee, setMarquee] = React.useState(null);
  const marqueeHits = React.useRef(null);
  const [layoutBusy, setLayoutBusy] = React.useState(false);
  const [layoutError, setLayoutError] = React.useState('');
  const [layoutNeedsRefresh, setLayoutNeedsRefresh] = React.useState(false);
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
    setCanvasSelectedIds(ids => ids.filter(id => selectableNodeIds.has(id)));
  }, [allNodes, layoutBusy, selectableNodeIds]);
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
  // `placement` is 'arrange' for Arrange; anything else is a hand move, which the owner pins.
  const savePositions = async (next, before, expectedRevision, remember = true, force = false, placement = null) => {
    if (!scopeStillCurrent()) { pendingArrange.current = null; return false; }
    const entries = Object.entries(next).filter(([id, point]) => before[id]?.x !== point.x || before[id]?.y !== point.y);
    if (!entries.length) return true;
    const restore = () => setPositions(held => ({...held, ...before}));
    // A save that arrives while one is in flight queues behind it rather than being
    // refused with "Wait for the current change"; on the way out there is no later drag
    // to retry it, and a save behind a save is exactly what a burst needs to survive.
    if (saving.current && canSaveLayout && entries.length <= MAX_LAYOUT_NODES) {
      // The preview already shows the new place; the save runs right after the current one.
      queuedSave.current = {next, before, expectedRevision, remember, force, placement};
      return true;
    }
    // The transport, never the render snapshot: the echo of a save that has just answered
    // must not refuse the burst that was waiting for exactly that save.
    const busy = transportBusy();
    if (!canSaveLayout || (busy && !force) || saving.current || entries.length > MAX_LAYOUT_NODES) {
      pendingArrange.current = null;
      restore();
      setLayoutError(entries.length > MAX_LAYOUT_NODES ? 'Move or arrange at most 2048 nodes at a time.' :
        busy || saving.current ? 'Wait for the current change, then try again.' : 'This connection cannot save node positions.');
      return false;
    }
    const changes = Object.fromEntries(entries);
    const expectedPositions = Object.fromEntries(entries.map(([id]) => [id, before[id]]));
    saving.current = true; setLayoutBusy(true); setLayoutError('');
    setPositions(held => ({...held, ...changes}));
    try {
      if (authority) await authority.moveMany(changes, expectedRevision, expectedPositions, placement);
      else await normal.moveTopologyNodes(changes, expectedRevision, expectedPositions, placement);
      if (!scopeStillCurrent()) return false;
      // Confirmed, and nothing else is owed: there is no unwritten movement left to report.
      if (!burstRef.current && !queuedSave.current) writeCanvasLayoutTrace(scopeKey, null);
      return true;
    } catch (error) {
      if (scopeStillCurrent()) {
        restore(); queuedSave.current = null; pendingArrange.current = null;
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
        setTimeout(() => saveRef.current && saveRef.current(queued.next, queued.before, queued.expectedRevision, queued.remember, queued.force, queued.placement), 0);
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

  // A scope seen for the first time has no stored view: it opens fitted to its cards (below).
  const workshopCanvas = graph.nodes.some(node => typeof isWorkshopGraphNode === 'function' && isWorkshopGraphNode(node));
  const openFitPending = React.useRef(workshopCanvas || (fitOnOpen && !CANVAS_VIEWS.has(scopeKey)));
  const workshopOpenFitCompleted = React.useRef(false);
  const [pan, setPan] = React.useState(() => libraryMode && !CANVAS_VIEWS.has(scopeKey) ? {x:0,y:36} : readCanvasView(scopeKey).pan);
  const [zoom, setZoom] = React.useState(() => libraryMode && !CANVAS_VIEWS.has(scopeKey) ? 1 : readCanvasView(scopeKey).zoom);
  const viewportTransformRef = React.useRef({pan, zoom});
  viewportTransformRef.current = {pan, zoom};
  React.useEffect(() => { CANVAS_VIEWS.set(scopeKey, {pan, zoom}); }, [scopeKey, pan, zoom]);
  React.useEffect(() => {
    if (typeof onViewportChange !== 'function' || !wrapRef.current) return;
    const rect = wrapRef.current.getBoundingClientRect();
    onViewportChange({scope:scopeKey, pan, zoom, width:rect.width, height:rect.height});
  }, [onViewportChange, scopeKey, pan, zoom]);
  const [menuNotice, setMenuNotice] = React.useState('');
  const [appToast, setAppToast] = React.useState(null);
  // What the person picked on this canvas (a node or a wire), held here so the dim follows the click at
  // once without waiting on the owner. Nothing picked -- including a selection restored at start -- dims nothing.
  const [pickedId, setPickedId] = React.useState(null);
  const [confirming, setConfirming] = React.useState(null); // {kind:'node'|'clear', ids, title, wires}
  const [menuBusy, setMenuBusy] = React.useState(false);
  const menuBusyRef = React.useRef(false);
  const [ctxMenu, setCtxMenu] = React.useState(null);
  const CanvasToast = typeof AppToast === 'function' ? AppToast : ({toast}) => toast ? <div data-app-toast="" data-no-pan="" role={toast.tone === 'err' ? 'alert' : 'status'}>{toast.tone === 'err' ? window.AH_DS.errorText(toast.text) : toast.text}{toast.actionLabel && <window.AH_DS.Btn onClick={toast.action}>{toast.actionLabel}</window.AH_DS.Btn>}</div> : null;
  const CanvasDestructiveDialog = typeof DestructiveDialog === 'function' ? DestructiveDialog : ({confirming, onCancel, onConfirm}) => {
    if (!confirming) return null;
    return <div data-no-pan="" role="presentation"><div role="alertdialog" aria-label="Confirm delete">
      <h2>{confirming.kind === 'clear' ? 'Delete all nodes?' : 'Delete “' + confirming.title + '”?'}</h2>
      <p>{(confirming.ids?.length || 0) + ' nodes and ' + (confirming.wires || 0) + ' wires go with it. Undo brings them back.'}</p>
      <window.AH_DS.Btn autoFocus onClick={onCancel}>Cancel</window.AH_DS.Btn><window.AH_DS.Btn onClick={onConfirm}>Delete</window.AH_DS.Btn>
    </div></div>;
  };
  const closeContextMenu = () => {
    setCtxMenu(null);
    if (ctxMenu?.opener?.isConnected) ctxMenu.opener.focus({preventScroll:true});
  };
  const [expanded, setExpanded] = React.useState({});
  const [dropTarget, setDropTarget] = React.useState(null); // {x,y,title} canvas-local
  // Snap to grid, on as drawn. A dragged node lands on the dot grid while it is on.
  const [snap, setSnap] = React.useState(true);
  const snapRef = React.useRef(snap);
  snapRef.current = snap;

  // Convert client coords → canvas coords (the world space the nodes live in)
  const toCanvasCoords = (clientX, clientY) => {
    const rect = wrapRef.current.getBoundingClientRect();
    const view = viewportTransformRef.current;
    return {
      x: (clientX - rect.left - view.pan.x) / view.zoom,
      y: (clientY - rect.top  - view.pan.y) / view.zoom,
    };
  };
  const screenToCanvasPoint = React.useCallback((clientX, clientY) => toCanvasCoords(clientX, clientY), []);
  const dragPoint = (d, clientX, clientY) => ({
    x: (clientX - d.rect.left - d.pan.x) / d.zoom,
    y: (clientY - d.rect.top - d.pan.y) / d.zoom,
  });

  const startSocketDrag = (root, port, side, e) => {
    if ((e.button ?? 0) !== 0 || (!authority && !normal) || authorityState?.pending || saving.current || layoutNeedsRefresh) return;
    e.stopPropagation();
    const rect = wrapRef.current?.getBoundingClientRect();
    const socketRect = e.currentTarget.getBoundingClientRect();
    if (!rect || !socketRect) return;
    const start = {
      x: (socketRect.left + socketRect.width / 2 - rect.left - pan.x) / zoom,
      y: (socketRect.top + socketRect.height / 2 - rect.top - pan.y) / zoom,
    };
    wireDragRef.current = {
      root, port, side, sx:e.clientX, sy:e.clientY, rect, pan:{...pan}, zoom,
      x1:start.x, y1:start.y, t:port.t || port.type || 'any', active:false,
    };
    try { e.currentTarget.setPointerCapture?.(e.pointerId); } catch (error) { /* pointer capture is best effort */ }
  };

  const socketFromPoint = (clientX, clientY) => {
    const element = document.elementFromPoint?.(clientX, clientY);
    const button = element?.closest?.('[data-studio-socket="true"]');
    if (!button) return null;
    const root = button.closest('.lm-node[data-node-id]')?.getAttribute('data-node-id');
    const side = button.getAttribute('data-socket-side');
    const portId = button.getAttribute('data-socket-port');
    const node = wireActionRef.current.nodes.find(item => item.id === root);
    const port = (side === 'in' ? node?.ins : node?.outs)?.find(item => item.id === portId);
    return root && port && (side === 'in' || side === 'out') ? {root, port, side} : null;
  };
  const wireDragCompletion = (drag, target) => {
    if (!target || target.side === drag.side) return null;
    const output = drag.side === 'out' ? {root:drag.root, port:drag.port} :
      target.side === 'out' ? {root:target.root, port:target.port} : null;
    const input = drag.side === 'in' ? {root:drag.root, port:drag.port} :
      target.side === 'in' ? {root:target.root, port:target.port} : null;
    if (!output || !input) return null;
    if (normal) {
      const inputOwner = input.port.owner || input.root;
      if (!output.port.connect_choices?.some(choice => choice.id === input.port.id && (choice.owner ?? inputOwner) === inputOwner)) {
        setWireError('This output cannot feed ' + input.port.label + '.');
        return null;
      }
    }
    return drag.side === 'out'
      ? {start:{root:output.root, port:output.port}, root:input.root, port:input.port, side:'in'}
      : {start:{root:input.root, port:input.port, reverse:true}, root:output.root, port:output.port, side:'out'};
  };

  const onCanvasMouseDown = (e) => {
    // Middle-drag pans from anywhere on the canvas, over cards too.
    if (e.button === 1) {
      if (e.target.closest('[data-no-pan]')) return;
      e.preventDefault();
      dragRef.current = { mode:'pan', sx:e.clientX, sy:e.clientY, px:pan.x, py:pan.y };
      return;
    }
    if (e.button !== 0) return;
    if (e.target.closest('[data-no-pan]')) return;
    if (e.target.closest('.lm-node')) return;
    suppressNodeClick.current = false;
    if (ctxMenu) { e.preventDefault(); closeContextMenu(); }
    if (e.shiftKey || e.altKey) {
      e.preventDefault();
      const rect = wrapRef.current.getBoundingClientRect();
      const at = toCanvasCoords(e.clientX, e.clientY);
      dragRef.current = {mode:'marquee', remove:e.altKey, base:[...selected], rect, pan:{...pan}, zoom, x0:at.x, y0:at.y};
      setMarquee({x0:at.x, y0:at.y, x1:at.x, y1:at.y});
      return;
    }
    setCanvasSelectedIds([]); setPickedId(null); setFocusId(null);
    dragRef.current = { mode:'pan', sx:e.clientX, sy:e.clientY, px:pan.x, py:pan.y };
  };
  // Which cards a box takes, read from the drawn cards (their real size) at their current places.
  marqueeHits.current = (box, crossing) => {
    const left = Math.min(box.x0, box.x1), right = Math.max(box.x0, box.x1);
    const top = Math.min(box.y0, box.y1), bottom = Math.max(box.y0, box.y1);
    return [...(wrapRef.current?.querySelectorAll('.lm-node[data-node-id]') || [])].filter(card => {
      const id = card.getAttribute('data-node-id'), at = positions[id];
      if (!at || !selectableNodeIds.has(id)) return false;
      const x0 = at.x, y0 = at.y, x1 = at.x + card.offsetWidth, y1 = at.y + card.offsetHeight;
      return crossing ? x0 < right && x1 > left && y0 < bottom && y1 > top
        : x0 >= left && x1 <= right && y0 >= top && y1 <= bottom;
    }).map(card => card.getAttribute('data-node-id'));
  };

  const openContextMenu = (e, nodeId = null, wireId = null) => {
    e.preventDefault();
    e.stopPropagation();
    setMenuNotice('');
    const rect = wrapRef.current.getBoundingClientRect();
    // Clamp so the menu never spills past the canvas edges (menu ≈ 220×350).
    const MENU_W = 220, MENU_H = Math.min(350, rect.height - 16);
    const opener = e.currentTarget;
    const anchor = opener.getBoundingClientRect();
    const keyboard = e.type === 'keydown';
    const rx = (keyboard ? anchor.left + 16 : e.clientX) - rect.left;
    const ry = (keyboard ? anchor.top + 24 : e.clientY) - rect.top;
    setCtxMenu({
      nodeId, wireId, opener, maxHeight:MENU_H,
      x: Math.max(8, Math.min(rx, rect.width  - MENU_W - 8)),
      y: Math.max(8, Math.min(ry, rect.height - MENU_H - 8)),
    });
  };
  const onContextMenu = e => {
    if (!e.target.closest('.lm-node') && !e.target.closest('[data-no-pan]')) openContextMenu(e);
  };
  const onNodeContextMenu = id => e => {
    if (e.target.isContentEditable || e.target.closest('input,textarea,select,[role="textbox"]')) return;
    if (!selected.has(id)) setCanvasSelectedIds([id]);
    setPickedId(id); setFocusId(id); openContextMenu(e, id);
  };
  const isContextKey = e => e.key === 'ContextMenu' || (e.key === 'F10' && e.shiftKey);
  // Arrow keys move the selection one grid step (Shift: one unit); the move saves like a drag.
  const nudgeSelection = (dx, dy) => {
    const ids = [...selected].filter(id => positions[id]);
    if (!ids.length) return false;
    if (!canSaveLayout || layoutNeedsRefresh || !scopeStillCurrent()) {
      setLayoutError(!canSaveLayout ? 'This connection cannot save node positions.' : 'Refresh the canvas first.');
      return true;
    }
    const before = Object.fromEntries(ids.map(id => [id, {...positions[id]}]));
    const next = Object.fromEntries(ids.map(id => [id, {x:positions[id].x + dx, y:positions[id].y + dy}]));
    setPositions(held => ({...held, ...next}));
    armLayoutRef.current({next, before, revision});
    return true;
  };
  const ARROWS = {ArrowLeft:[-1, 0], ArrowRight:[1, 0], ArrowUp:[0, -1], ArrowDown:[0, 1]};
  const onCanvasKeyDown = e => {
    const shortcut = studioShortcutFromEvent(e, 'canvas');
    // History is admitted once, by the document listener, including canvas bubbling.
    if (shortcut?.action === 'undo' || shortcut?.action === 'redo') return;
    if (e.target === e.currentTarget && shortcut?.action === 'open-canvas-menu') { openContextMenu(e); return; }
    const inField = e.target.closest('input,textarea,select,[contenteditable="true"],[role="menu"]');
    if (!inField && !e.metaKey && !e.ctrlKey && !e.altKey) {
      if (shortcut?.action === 'move-selection' && ARROWS[e.key]) {
        const step = e.shiftKey ? 1 : CANVAS_GRID;
        if (nudgeSelection(ARROWS[e.key][0] * step, ARROWS[e.key][1] * step)) e.preventDefault();
        return;
      }
      // Delete or Backspace on a picked wire cuts it, the same route as the wire's "Cut this wire". The
      // click picks the wire at once; the graph confirms the selection a moment later, so a Delete pressed
      // in between still names the wire the person clicked (menuDisconnect waits for that selection write).
      const pickedWireIdx = pickedId == null ? -1 : authorityState ? graph.wires.findIndex(w => w.id === pickedId)
        : (String(pickedId).indexOf('wire:') === 0 ? +String(pickedId).slice(5) : -1);
      const cutIdx = pickedWireIdx >= 0 ? pickedWireIdx : focusWireIdx;
      if (shortcut?.action === 'cut-wire' && cutIdx >= 0 && graph.wires[cutIdx]?.id && cutWire) {
        e.preventDefault();
        if (layoutNeedsRefresh) { setWireError('Refresh the canvas before editing connections.'); return; }
        menuDisconnect([graph.wires[cutIdx].id]);
        return;
      }
      if (shortcut?.action === 'fit-selection-or-all') {
        e.preventDefault(); fitIds(selected.size ? [...selected] : allNodes.map(node => node.id)); return;
      }
    }
    // The shortcuts the canvas menu names (design CanvasMenu), while focus is on the canvas and not in a field.
    if (!(e.metaKey || e.ctrlKey) || e.altKey || e.target.closest('input,textarea,select,[contenteditable="true"]')) return;
    if (shortcut?.action === 'select-all-nodes') { e.preventDefault(); setCanvasSelectedIds(allNodes.map(node => node.id).filter(id => selectableNodeIds.has(id))); return; }
    const item = canvasMenuItems.find(row => row.shortcutId && studioShortcutById(row.shortcutId)?.action === shortcut?.action);
    if (!item) return;
    e.preventDefault();
    if (!item.disabled && typeof item.action === 'function') item.action();
  };
  const onNodeKeyDown = id => e => {
    if (e.target === e.currentTarget && isContextKey(e)) onNodeContextMenu(id)(e);
  };
  const onNodeFocus = id => e => {
    if (suppressNodeClick.current) { suppressNodeClick.current = false; return; }
    if (e?.target.isContentEditable || e?.target.closest('button,input,textarea,select,a,[contenteditable]:not([contenteditable="false"])')) return;
    let roots = selectedIdsRef.current.filter(root => selectableNodeIds.has(root));
    if (e?.shiftKey) roots = roots.includes(id) ? roots.filter(root => root !== id) : [...roots, id];
    else if (!roots.includes(id)) roots = [id];
    setCanvasSelectedIds(roots);
    setPickedId(roots.length ? id : null); setFocusId(roots.length ? id : null, roots);
    wrapRef.current?.focus({preventScroll:true});
  };

  const onNodeDragStart = (id) => (e) => {
    if (e.button !== 0 || e.target.closest('button,input,textarea,select,a')) return;
    e.stopPropagation();
    if (e.shiftKey) return;
    e.preventDefault();
    setDraggingNode(true);
    suppressNodeClick.current = false;
    const ids = selected.has(id) ? [...selected] : [id];
    setCanvasSelectedIds(ids); closeContextMenu();
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
    const finishWireDrag = (drag, target, event) => {
      suppressWireClick.current = true;

      setWirePreview(null);
      const completion = wireDragCompletion(drag, target);
      if (!completion) {
        setWireStartState(null);
        return;
      }
      setWireStartState(completion.start);
      Promise.resolve(wireActionRef.current.useSocket?.(completion.root, completion.port, completion.side)).finally(() => {
        const held = wireStartRef.current;
        if (held && held.root === completion.start.root && held.port?.id === completion.start.port.id) setWireStartState(null);
      });
      event?.preventDefault?.();
      event?.stopPropagation?.();
    };
    const onPointerMove = e => {
      const d = wireDragRef.current;
      if (!d) return;
      const dx = e.clientX - d.sx, dy = e.clientY - d.sy;
      if (!d.active && Math.hypot(dx, dy) >= 4) {
        d.active = true;
        setWireStartState(null);
      }
      if (!d.active) return;
      const at = dragPoint(d, e.clientX, e.clientY);
      setWirePreview({x1:d.x1, y1:d.y1, x2:at.x, y2:at.y, t:d.t});
      e.preventDefault(); e.stopPropagation();
    };
    const onPointerUp = e => {
      const d = wireDragRef.current;
      if (!d) return;
      wireDragRef.current = null;
      if (!d.active) return;
      finishWireDrag(d, socketFromPoint(e.clientX, e.clientY), e);
    };
    const onPointerCancel = () => {
      if (!wireDragRef.current) return;
      wireDragRef.current = null;
      setWirePreview(null);
      setWireStartState(null);
    };
    const onKeyDown = e => {
      if (e.key !== 'Escape') return;
      if (!wireDragRef.current && !wireStartRef.current && document.querySelector('[role="dialog"],[role="menu"]')) return;
      const cancellingWire=!!wireDragRef.current || !!wireStartRef.current;
      if (wireDragRef.current) suppressWireClick.current=true;
      wireDragRef.current = null;
      setWirePreview(null);
      setWireStartState(null);
      if(!cancellingWire){setCanvasSelectedIds([]);setPickedId(null);setFocusId(null,[]);}
      e.preventDefault(); e.stopPropagation();
    };
    const onMove = (e) => {
      const d = dragRef.current;
      if (!d) return;
      const dx = e.clientX - d.sx;
      const dy = e.clientY - d.sy;
      if (d.mode === 'pan') {
        setPan({ x: d.px + dx, y: d.py + dy });
      } else if (d.mode === 'marquee') {
        d.x1 = (e.clientX - d.rect.left - d.pan.x) / d.zoom;
        d.y1 = (e.clientY - d.rect.top - d.pan.y) / d.zoom;
        setMarquee({x0:d.x0, y0:d.y0, x1:d.x1, y1:d.y1});
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
      setDraggingNode(false);
      if (drag?.mode === 'marquee') {
        setMarquee(null);
        if (drag.x1 === undefined) return;
        const hits = marqueeHits.current({x0:drag.x0, y0:drag.y0, x1:drag.x1, y1:drag.y1}, drag.x1 < drag.x0);
        const roots = drag.remove ? drag.base.filter(id => !hits.includes(id)) : [...new Set([...drag.base, ...hits])];
        setCanvasSelectedIds(roots);
        if (!roots.length) { setPickedId(null); setFocusId(null, []); }
        return;
      }
      if (drag?.mode === 'nodes' && drag.last) {
        if (!(membershipDragRef.current && membershipDragRef.current(drag))) {
          armLayoutRef.current({next:drag.last, before:drag.before, revision:drag.revision});
        }
      }
    };
    document.addEventListener('pointermove', onPointerMove);
    document.addEventListener('pointerup', onPointerUp);
    document.addEventListener('pointercancel', onPointerCancel);
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    return () => {
      document.removeEventListener('pointermove', onPointerMove);
      document.removeEventListener('pointerup', onPointerUp);
      document.removeEventListener('pointercancel', onPointerCancel);
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };
  }, []);

  const onWheel = (e) => {
    e.preventDefault();
    const rect = wrapRef.current.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const next = canvasWheelZoom(zoom, e.deltaY);
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
    const title = e.dataTransfer.getData('text/plain') || window.__archhubDraggingLibraryTitle || 'node';
    setDropTarget({ x: e.clientX - rect.left, y: e.clientY - rect.top, title });
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
    wrapRef.current?.focus({preventScroll:true});
  };

  const nodeById = Object.fromEntries(
    allNodes.map(n => [n.id, { ...n, x: positions[n.id]?.x ?? n.x, y: positions[n.id]?.y ?? n.y }])
  );

  const focusWireIdx = authorityState ? graph.wires.findIndex(w => w.id === focusId) : (String(focusId).indexOf('wire:') === 0 ? +String(focusId).slice(5) : -1);
  const dimmedIds = pickedId ? canvasDimmedIds(allNodes.map(node => node.id), graph.wires, pickedId, [...selected]) : new Set();

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
    const sourceWidth = (typeof isWorkshopGraphNode === 'function' && isWorkshopGraphNode(fromNode)) ? (fromNode.w || 320) : fromNode.cat === 'ai' && expanded[fromNode.id] ? Math.max(520, fromNode.w || NODE_CARD_W) :
      Number.isFinite(fromNode.w) && fromNode.w >= 120 ? fromNode.w : nodeIsWatch(fromNode) ? 260 : NODE_CARD_W;
    const x1 = fromNode.x + sourceWidth, y1 = fromNode.y + portY(portBands[fromNode.id], fromIdx);
    const x2 = toNode.x,                y2 = toNode.y + portY(portBands[toNode.id], toIdx);
    const touches = w.from[0] === focusId || w.to[0] === focusId || i === focusWireIdx;
    return {
      i, x1, y1, x2, y2, selected: i === focusWireIdx,
      t: fromNode.outs[fromIdx].t,
      list:!!fromNode.outs[fromIdx].list || !!fromNode.outs[fromIdx].multiple,
      animated: fromNode.state === 'running' || toNode.state === 'running',
      focused: touches,
    };
  }).filter(Boolean);

  const toggleExpanded = (id) => setExpanded(e => ({ ...e, [id]: !e[id] }));
  // One set of handlers per card for the canvas's life. Each calls the CURRENT closure through a ref,
  // so a memoized card that did not re-render still acts on today's selection and positions.
  const latest = React.useRef(null);
  // A frame collapses into ONE graph group node (the composition owner's own Group); a group expands back.
  const composer = typeof authority?.composition === 'function' ? (op, roots) => authority.composition(op, roots)
    : typeof normal?.composeTopology === 'function' ? (op, roots) => normal.composeTopology(op, roots) : null;
  const selectedCardIds = () => Array.from(wrapRef.current?.querySelectorAll('.lm-node[data-node-id][data-selected="true"]') || [])
    .map(card => card.getAttribute('data-node-id'))
    .filter(id => id && selectableNodeIds.has(id));
  const currentSelectionIds = () => {
    const fromCards = selectedCardIds();
    return fromCards.length ? fromCards : [...selected];
  };
  const composeCurrentSelection = () => {
    const roots = currentSelectionIds();
    composeGroup('group', roots, 'Grouped ' + roots.length + ' nodes into one node.');
  };
  const composeGroup = (operation, roots, what) => {
    closeContextMenu();
    return menuTaskRef.current(async () => {
      if (!composer) throw new Error('Grouping needs the live graph.');
      const result = await composer(operation, roots);
      if (!result || result.ok === false) throw new Error(result?.error || 'The group change was not confirmed.');
      return what;
    });
  };
  const consumeSocketClick = () => {
    if (!suppressWireClick.current) return false;
    suppressWireClick.current = false;
    return true;
  };
  latest.current = {toggleExpanded, onNodeDragStart, onNodeFocus, onNodeContextMenu, onNodeKeyDown, useSocket, startSocketDrag, consumeSocketClick, setPortBand, composeGroup,
    open:id => {
      if (authority) { authority.open(id).catch(() => {}); return; }
      const trail = authorityState?.canvas?.scope?.trail || normal?.getSnapshot?.()?.topology?.canvas?.scope?.trail || [];
      if (typeof window.ARCHHUB_SCOPE_OPEN === 'function' && Array.isArray(trail)) {
        window.ARCHHUB_SCOPE_OPEN([...trail.map(step => step.root).filter(Boolean), id]);
      }
    },
    watchAddInput:id => {
      const node = allNodes.find(row => row.id === id);
      setFocusId(id);
      const input = (node?.ins || []).find(port => port.connectable) || (node?.ins || [])[0];
      if (input?.connectable) useSocket(id, input, 'in');
      setLibraryOpen(true);
    },
    watchRun:id => runNodeToHere(id),
    watchShowAll:id => {
      setFocusId(id);
      window.dispatchEvent(new CustomEvent('archhub:watch-show-all', {detail:{node:id}}));
    },
    watchStop:id => window.ARCHHUB_CANCEL_RUN?.(id),
    watchShowInRevit:id => (window.ARCHHUB_SHOW_IN_REVIT || window.ARCHHUB_HIGHLIGHT_IN_HOST)?.(id),
    watchTurnOn:id => window.ARCHHUB_TURN_ON_NODE?.(id)
  };
  const handlerCache = React.useRef(new Map());
  const cardHandlers = id => {
    let held = handlerCache.current.get(id);
    if (!held) {
      held = {toggle:() => latest.current.toggleExpanded(id), drag:e => latest.current.onNodeDragStart(id)(e),
        focus:e => latest.current.onNodeFocus(id)(e), menu:e => latest.current.onNodeContextMenu(id)(e),
        key:e => latest.current.onNodeKeyDown(id)(e), socket:(port, side) => {
          if (latest.current.consumeSocketClick()) return;
          return latest.current.useSocket(id, port, side);
        },
        socketDrag:(e, port, side) => latest.current.startSocketDrag(id, port, side, e),
        band:(top, height) => latest.current.setPortBand(id, top, height),
        expand:() => latest.current.composeGroup('ungroup', [id], 'Expanded the group.'),
        open:() => latest.current.open(id)};
      handlerCache.current.set(id, held);
    }
    held.watch = {
      addInput:() => latest.current.watchAddInput(id),
      runToHere:() => latest.current.watchRun(id),
      retry:() => latest.current.watchRun(id),
      showAll:() => latest.current.watchShowAll(id),
      stop:typeof window.ARCHHUB_CANCEL_RUN === 'function' ? () => latest.current.watchStop(id) : null,
      showInRevit:(typeof window.ARCHHUB_SHOW_IN_REVIT === 'function' || typeof window.ARCHHUB_HIGHLIGHT_IN_HOST === 'function') ? () => latest.current.watchShowInRevit(id) : null,
      turnOn:typeof window.ARCHHUB_TURN_ON_NODE === 'function' ? () => latest.current.watchTurnOn(id) : null,
    };
    if (typeof window !== 'undefined') {
      if (!window.ARCHHUB_WATCH_ACTIONS || typeof window.ARCHHUB_WATCH_ACTIONS.get !== 'function') {
        window.ARCHHUB_WATCH_ACTIONS = new Map();
      }
      window.ARCHHUB_WATCH_ACTIONS.set(id, held.watch);
    }
    return held;
  };
  const measureCards = (silent = false) => {
    if (document.fonts?.status === 'loading') {
      if (!silent) setLayoutError('Fonts are loading; try again in a moment.'); return null;
    }
    if (!wrapRef.current || allNodes.length > MAX_LAYOUT_NODES) {
      if (!silent) setLayoutError('Fit and Arrange support up to 2048 visible nodes. Open a smaller canvas scope.'); return null;
    }
    const cards = new Map(Array.from(wrapRef.current.querySelectorAll('.lm-node[data-node-id]'))
      .map(element => [element.getAttribute('data-node-id'), element]));
    const sizes = {};
    for (const node of allNodes) {
      const card = cards.get(node.id), w = card?.offsetWidth, h = card?.offsetHeight;
      if (!w || !h || !Number.isFinite(positions[node.id]?.x) || !Number.isFinite(positions[node.id]?.y)) {
        if (!silent) setLayoutError('Wait for the node cards to finish rendering, then try again.'); return null;
      }
      const targetWidth = node.cat === 'ai' && expanded[node.id] ? Math.max(520, node.w || NODE_CARD_W) :
        Number.isFinite(node.w) ? node.w : w;
      sizes[node.id] = {w:Math.ceil(Math.max(w, targetWidth)), h:Math.ceil(h)};
    }
    return sizes;
  };
  const fitIds = (ids, silent = false, maxZoom = 2) => {
    if (!scopeStillCurrent() || !ids.length) return false;
    const sizes = measureCards(silent);
    if (!sizes) return false;
    try {
      const result = canvasFitBounds(ids, positions, sizes, wrapRef.current.getBoundingClientRect(), maxZoom);
      setZoom(result.zoom); setPan(result.pan); closeContextMenu();
      return true;
    } catch (error) { if (!silent) setLayoutError(window.AH_DS.errorText(error.message)); }
    return false;
  };
  const revealIds = (ids, silent = false) => {
    if (!scopeStillCurrent() || !ids.length) return false;
    const sizes = measureCards(silent);
    if (!sizes) return false;
    try {
      const result = canvasRevealBounds(ids, positions, sizes, wrapRef.current.getBoundingClientRect(), zoom, pan);
      setZoom(result.zoom); setPan(result.pan); closeContextMenu();
      return true;
    } catch (error) { if (!silent) setLayoutError(window.AH_DS.errorText(error.message)); }
    return false;
  };
  React.useEffect(() => {
    const ids = Array.isArray(pendingReveal?.ids) ? pendingReveal.ids.filter(Boolean) : [];
    if (!ids.length) return;
    let frame = 0, cancelled = false, timer = null;
    const tick = () => {
      if (cancelled) return;
      if (revealIds(ids, true)) {
        if (clearPendingReveal) clearPendingReveal();
        return;
      }
      frame += 1;
      if (frame >= 10) {
        if (clearPendingReveal) clearPendingReveal();
        return;
      }
      const raf = window.requestAnimationFrame || (fn => window.setTimeout(fn, 16));
      timer = raf(tick);
    };
    const raf = window.requestAnimationFrame || (fn => window.setTimeout(fn, 16));
    timer = raf(tick);
    return () => {
      cancelled = true;
      if (timer != null && window.cancelAnimationFrame) window.cancelAnimationFrame(timer);
      else if (timer != null) window.clearTimeout(timer);
    };
  }, [pendingReveal?.at, allNodes, positions]);
  const selectConnected = whole => {
    if (!scopeStillCurrent()) return;
    if (allNodes.length > MAX_LAYOUT_NODES || graph.wires.length > 4096) {
      setLayoutError('Connected selection supports up to 2048 nodes and 4096 visible wires. Open a smaller scope.'); return;
    }
    const nodeIds = allNodes.map(node => node.id);
    const seeds = ctxMenu?.nodeId
      ? (selected.has(ctxMenu.nodeId) ? [...selected] : [ctxMenu.nodeId])
      : selected.size ? [...selected] : nodeIds.includes(focusId) ? [focusId] : [];
    setCanvasSelectedIds(canvasConnectedNodeIds(nodeIds, graph.wires, seeds, whole));
  };
  const runPendingArrangeRef = React.useRef(null);
  const nodeByRoot = new Map(allNodes.map(node => [node.id, node]));
  const arrangeMovable = ids => ids.filter(id => !nodeByRoot.get(id)?.pinned);
  const arrangePinnedCount = ids => ids.filter(id => nodeByRoot.get(id)?.pinned).length;
  const arrangeFrameOf = id => '';
  const arrangeNeedsRefresh = () => needsRefresh.current || layoutNeedsRefresh ||
    !!(authority ? authority.getSnapshot() : normal?.getSnapshot()?.topology)?.requires_refresh;
  // Single-flight drain. Order matters: stale-scope, refresh-owed, auth, nodes,
  // wires, MAX all DISCARD; only our own in-flight save/burst/queue WAITS.
  const runPendingArrange = async () => {
    const wanted = pendingArrange.current;
    if (!wanted || arrangeRunning.current) return false;
    if (!alive.current || !scopeStillCurrent()) { pendingArrange.current = null; return false; }
    if (arrangeNeedsRefresh()) {
      if (scopeStillCurrent()) setLayoutError('Refresh the canvas to reconcile any saved positions.');
      return false;
    }
    if (!canSaveLayout) {
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
      if (scopeStillCurrent()) setLayoutError('Move or arrange at most 2048 nodes at a time.');
      return false;
    }
    if (saving.current || burstRef.current || queuedSave.current || transportBusy()) return false;
    const sizes = measureCards();
    if (!sizes) return false;
    if (allNodes.some(node => positions[node.id]?.x !== node.x || positions[node.id]?.y !== node.y)) return false;
    pendingArrange.current = null;
    const movable = arrangeMovable(liveIds);
    const pinnedCount = arrangePinnedCount(liveIds);
    if (!movable.length) { setLayoutError(pinnedArrangeMessage(pinnedCount)); return false; }
    arrangeRunning.current = true;
    setLayoutError('');
    try {
      const before = Object.fromEntries(movable.map(id => [id, {...positions[id]}]));
      const next = canvasArrangePositions(movable, positions, sizes, allNodes.map(node => node.id), graph.wires, arrangeFrameOf);
      let summaryZoom = zoom, summaryPan = pan;
      if (wanted.options?.fitAfter && wrapRef.current) {
        const fit = canvasFitBounds(allIds, {...positions, ...next}, sizes, wrapRef.current.getBoundingClientRect());
        summaryZoom = fit.zoom; summaryPan = fit.pan;
        setZoom(fit.zoom); setPan(fit.pan);
      }
      await savePositions(next, before, revision, true, false, 'arrange');
      if (pinnedCount && scopeStillCurrent()) setLayoutError(pinnedArrangeMessage(pinnedCount, movable.length));
      if (system && setSystemArrangeSummary && wrapRef.current) {
        setSystemArrangeSummary(computeLayoutSummary(
          allNodes.map(node => node.id),
          {...positions, ...next},
          sizes,
          graph.wires,
          wrapRef.current.getBoundingClientRect(),
          summaryZoom,
          summaryPan,
        ));
      }
      return true;
    } catch (error) {
      if (scopeStillCurrent()) setLayoutError(window.AH_DS.errorText(error.message || 'Arrange could not be confirmed.'));
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
  const allIds = allNodes.map(node => node.id);
  // Cards that intersect by their DRAWN size (content + port band). Nothing moves on its own: the canvas says so
  // and offers Arrange, the one user-initiated write that lays them out by the same measured sizes.
  const overlapCount = (() => {
    if (!allNodes.length || !allNodes.every(node => Number.isFinite(cardHeights[node.id]))) return 0;
    const boxes = allNodes.map(node => ({id:node.id, ...(positions[node.id] || node), w:(typeof isWorkshopGraphNode === 'function' && isWorkshopGraphNode(node)) ? (node.w || 320) : node.w || 220, h:cardHeights[node.id]}));
    const hit = new Set();
    for (let a = 0; a < boxes.length; a += 1) for (let b = a + 1; b < boxes.length; b += 1) {
      const p = boxes[a], q = boxes[b];
      if (p.x < q.x + q.w && q.x < p.x + p.w && p.y < q.y + q.h && q.y < p.y + p.h) { hit.add(p.id); hit.add(q.id); }
    }
    return hit.size;
  })();
  const arrangeIds = async (ids, options = {}) => {
    if (!alive.current || !scopeStillCurrent() || !ids.length) return false;
    if (!canSaveLayout) { if (!options.silent) setLayoutError('This connection cannot save node positions.'); return false; }
    const liveIds = ids.filter(id => allNodes.some(node => node.id === id));
    if (!liveIds.length) return false;
    if (liveIds.length > MAX_LAYOUT_NODES) {
      if (!options.silent) setLayoutError('Move or arrange at most 2048 nodes at a time.'); return false;
    }
    if (arrangeNeedsRefresh()) {
      if (!options.silent) setLayoutError('Refresh the canvas to reconcile any saved positions.'); return false;
    }
    // Foreign-busy (transport held by what is not our save): refuse, never queue.
    if (transportBusy() && !saving.current && !queuedSave.current && !burstRef.current) {
      if (!options.silent) setLayoutError('Wait for the current change, then try again.'); return false;
    }
    // Our-save busy: remember one click (latest intent wins, runs once).
    if (flushLayoutBurst() || saving.current || queuedSave.current || burstRef.current) {
      pendingArrange.current = {ids: [...liveIds], options};
      if (!options.silent) setLayoutError('Arrange will run after the current save finishes.');
      return false;
    }
    if (allNodes.some(node => positions[node.id]?.x !== node.x || positions[node.id]?.y !== node.y)) {
      if (!options.silent) setLayoutError('The canvas is receiving new positions. Try Arrange again.'); return false;
    }
    if (graph.wires.length > 4096) { if (!options.silent) setLayoutError('Arrange supports up to 4096 visible wires. Open a smaller scope.'); return false; }
    const movable = arrangeMovable(liveIds);
    const pinnedCount = arrangePinnedCount(liveIds);
    if (!movable.length) { if (!options.silent) setLayoutError(pinnedArrangeMessage(pinnedCount)); return false; }
    const expectedRevision = revision, sizes = measureCards();
    if (!sizes) return false;
    const before = Object.fromEntries(movable.map(id => [id, {...positions[id]}]));
    const next = canvasArrangePositions(movable, positions, sizes, allNodes.map(node => node.id), graph.wires, arrangeFrameOf);
    let summaryZoom = zoom, summaryPan = pan;
    if (options.fitAfter && wrapRef.current) {
      try {
        const fit = canvasFitBounds(allIds, {...positions, ...next}, sizes, wrapRef.current.getBoundingClientRect());
        summaryZoom = fit.zoom; summaryPan = fit.pan;
        setZoom(fit.zoom); setPan(fit.pan);
      } catch (error) { if (!options.silent) setLayoutError(window.AH_DS.errorText(error.message)); }
    }
    // Ping v4c item 2: success only when the layout write is confirmed; a refused, busy or
    // stale save restores the confirmed layout, publishes no summary and lets auto-arrange retry.
    const saved = await savePositions(next, before, expectedRevision, true, false, 'arrange');
    if (saved === false) return false;
    if (pinnedCount && !options.silent) setLayoutError(pinnedArrangeMessage(pinnedCount, movable.length));
    if (system && setSystemArrangeSummary && wrapRef.current) {
      setSystemArrangeSummary(computeLayoutSummary(
        allNodes.map(node => node.id),
        {...positions, ...next},
        sizes,
        graph.wires,
        wrapRef.current.getBoundingClientRect(),
        summaryZoom,
        summaryPan,
      ));
    }
    return true;
  };
  // Undo / Redo are the graph's own history (07a1364), not a positions-only reset: every recorded change on
  // this canvas -- a move, an Arrange, a new card, a wire, a value -- is taken back by the same route.
  const history = authorityState?.canvas?.action_history;
  const canUndo = authority ? typeof authority.undo === 'function' :
    typeof window.ARCHHUB_HISTORY === 'function' && history?.can_undo === true;
  const canRedo = (authority ? typeof authority.redo === 'function' : typeof window.ARCHHUB_HISTORY === 'function') && history?.can_redo === true;
  const undoWhy = typeof window.ARCHHUB_HISTORY !== 'function' && !authority?.undo ? 'Undo is not available in this connection' : 'Nothing to undo';
  const redoWhy = authority ? (typeof authority.redo === 'function' ? 'Nothing to redo' : 'Redo is not available on this canvas') : typeof window.ARCHHUB_HISTORY !== 'function' ?
    'Redo is not available in this connection' : 'Nothing to redo';
  const runHistory = operation => {
    if (blocked || menuBusyRef.current) return;
    if (operation === 'undo' ? !canUndo : !canRedo) { setLayoutError(operation === 'undo' ? undoWhy : redoWhy); return; }
    if (flushLayoutBurst()) { setLayoutError('Saving the moved nodes first. Try again in a moment.'); return; }
    const read = () => (authority ? authority.getSnapshot() : normal?.getSnapshot()?.topology)?.graph || {nodes:[], wires:[]};
    menuTask(async () => {
      const before = read();
      try {
        if (authority) await authority[operation](); else await window.ARCHHUB_HISTORY(operation);
      } catch (error) {
        // The history refuses to take back a change a later change depends on; say that in plain words.
        if (/gained references|lost references|Conflict/i.test(String(error?.message || ''))) {
          throw new Error((operation === 'redo' ? 'Redo' : 'Undo') + ' stopped: a later change depends on this one, so it cannot be taken back here.');
        }
        throw error;
      }
      if (authority) await authority.load(); else if (normal) await normal.refreshTopologyCanvas();
      return canvasHistoryToast(operation, before, read());
    });
  };
  // NodeCanvas is mounted only for the active Studio canvas. Keep today's toolbar
  // path in a ref; one document listener owns history regardless of keyboard focus.
  const historyKeyRef = React.useRef(null);
  historyKeyRef.current = e => {
    if (e.defaultPrevented || e.isComposing || e.repeat) return;
    const shortcut = studioShortcutFromEvent(e, 'canvas');
    if (shortcut?.action !== 'undo' && shortcut?.action !== 'redo') return;
    const editing = node => node?.isContentEditable || node?.closest?.('input,textarea,select,[role="textbox"],[contenteditable]:not([contenteditable="false"])');
    if (editing(e.target) || editing(document.activeElement) || document.querySelector('[role="dialog"],[role="menu"],dialog[open]')) return;
    if (blocked || menuBusyRef.current || !scopeStillCurrent() || (shortcut.action === 'undo' ? !canUndo : !canRedo)) return;
    e.preventDefault();
    runHistory(shortcut.action);
  };
  React.useEffect(() => {
    const key = e => historyKeyRef.current?.(e);
    document.addEventListener('keydown', key);
    return () => document.removeEventListener('keydown', key);
  }, []);
  const refreshCanvas = async () => {
    if (!scopeStillCurrent() || saving.current || authorityState?.pending) return;
    try {
      if (authority) await authority.load();
      else if (normal) await normal.refreshTopologyCanvas();
      else return;
      if (scopeStillCurrent()) { setLayoutError(''); setWireError(''); setLayoutNeedsRefresh(false); }
    } catch (error) { if (scopeStillCurrent()) setLayoutError(window.AH_DS.errorText(error.message || 'The canvas could not be refreshed.')); }
  };
  React.useEffect(() => {
    const text = layoutError || authorityState?.error || wireError || menuNotice;
    if (!text) return;
    const error = !!(layoutError || authorityState?.error || wireError);
    const canUndoToast = !error && canUndo && /(deleted|removed|Grouped|Fork placed|Batch placed|Automation trigger selected)/i.test(text);
    setAppToast({
      id:Date.now() + ':' + text,
      tone:error ? 'err' : 'ok',
      text,
      actionLabel:error ? 'Retry' : canUndoToast ? 'Undo' : '',
      action:error ? refreshCanvas : canUndoToast ? () => runHistory('undo') : undefined,
      close:() => setAppToast(null),
    });
  }, [layoutError, authorityState?.error, wireError, menuNotice, canUndo]);
  // Open fitted (founder window 2026-10-12: a graph opened at 66% under the toolbar, cut at the left).
  // Once per scope, after the cards have measured; never above 100%; a stored view is kept as left.
  React.useEffect(() => {
    if (workshopCanvas && !workshopOpenFitCompleted.current) openFitPending.current = true;
    if (!openFitPending.current || !allIds.length) return undefined;
    let frame = 0, cancelled = false;
    const raf = window.requestAnimationFrame || (fn => window.setTimeout(fn, 16));
    const tick = () => {
      if (cancelled || !openFitPending.current) return;
      if (fitIds(allIds, true, 1)) { openFitPending.current = false; workshopOpenFitCompleted.current = true; return; }
      if (++frame < 20) raf(tick); else openFitPending.current = false;
    };
    raf(tick);
    return () => { cancelled = true; };
  }, [scopeKey, allIds.length, workshopCanvas]);
  // The routes the menus call. Each one already exists: the inspector's Delete (ARCHHUB_RETRACT ->
  // /api/universal/retract), its connection Delete (disconnectTopology / authority.remove), Rerun (ARCHHUB_RUN ->
  // /api/universal/run-graph), the library's placement (ARCHHUB_NODE_CREATE -> /api/universal/node-create) and
  // the scope opening that double-click and sessions use (authority.open / ARCHHUB_SCOPE_OPEN).
  const cutWire = authority ? root => authority.remove(root) : normal?.disconnectTopology ? root => normal.disconnectTopology(root) : null;
  const removeNode = typeof window.ARCHHUB_RETRACT === 'function' ? root => window.ARCHHUB_RETRACT(root) : null;
  const menuTask = async (task, done) => {
    const refuse = error => {
      if (scopeStillCurrent()) setLayoutError(error);
      return {ok:false, error};
    };
    if (menuBusyRef.current) return refuse('Wait for the current action to finish, then try again.');
    menuBusyRef.current = true;
    setMenuBusy(true); setMenuNotice(''); setLayoutError('');
    try {
      // Selection may still be in flight when Group is clicked. Keep the click's roots,
      // then wait for the transport's current state before asking for the group control.
      for (let i = 0; i < 100 && transportBusy(); i += 1) {
        if (!scopeStillCurrent()) throw new Error('The canvas scope changed. Choose the nodes again.');
        const held = authority ? authority.getSnapshot() : normal?.getSnapshot()?.topology;
        if (needsRefresh.current || held?.requires_refresh) throw new Error('Refresh the canvas before trying this action again.');
        await new Promise(done => setTimeout(done, 100));
      }
      if (!scopeStillCurrent()) throw new Error('The canvas scope changed. Choose the nodes again.');
      if (transportBusy()) throw new Error('The current canvas change did not finish. Try again after it finishes.');
      const said = await task();
      if (said?.ok === false) throw new Error(said.error || 'The action was refused.');
      if (scopeStillCurrent()) setMenuNotice(typeof said === 'string' ? said : done || '');
      return {ok:true};
    }
    catch (error) { return refuse(error?.message || 'The action was refused.'); }
    finally { menuBusyRef.current = false; if (alive.current) setMenuBusy(false); }
  };
  menuTaskRef.current = menuTask;
  const menuRun = () => menuTask(async () => {
    const result = await window.ARCHHUB_RUN();
    if (!result || result.ok === false) throw new Error(result?.error || 'The graph run failed.');
    const waiting = Object.keys(result.pending || {}).length;
    return 'The graph ran' + (waiting ? '; ' + waiting + ' node(s) did not finish' : '') + '.';
  });
  const runNodeToHere = id => menuTask(async () => {
    const result = await window.ARCHHUB_RUN({node:id});
    if (!result || result.ok === false) throw new Error(result?.error || 'The graph run failed.');
    if (result.pending?.[id]) throw new Error(String(result.pending[id]));
    return 'Ran to this node.';
  });
  const menuDisconnect = roots => menuTask(async () => {
    let cut = 0;
    for (const root of roots.filter(Boolean)) { await cutWire(root); cut += 1; }
    return cut === 1 ? 'The wire was removed.' : cut + ' wires were removed.';
  });
  const duplicateNode = React.useCallback(async node => {
    if (!node) throw new Error('Fork is unavailable in this view.');
    if (typeof window.ARCHHUB_NODE_CREATE !== 'function') throw new Error('Fork is unavailable in this view.');
    const params = Object.fromEntries((node.params || []).filter(row => row.k && row.k !== 'seed').map(row => [row.k, row.v ?? '']));
    const at = positions[node.id] || node;
    const cards = new Map(Array.from(wrapRef.current?.querySelectorAll('.lm-node[data-node-id]') || [])
      .map(card => [card.getAttribute('data-node-id'), card]));
    const occupied = allNodes.map(held => ({...held, ...(positions[held.id] || {}),
      w:cards.get(held.id)?.offsetWidth || held.w || NODE_CARD_W,
      h:cards.get(held.id)?.offsetHeight || cardHeights[held.id] || held.h || 230}));
    const sourceBox = occupied.find(held => held.id === node.id) || {...at, w:node.w || NODE_CARD_W, h:node.h || 230};
    const free = studioFreeSlot(occupied, {x:at.x + sourceBox.w * 1.5 + 40, y:at.y + sourceBox.h / 2},
      {w:sourceBox.w, h:sourceBox.h});
    const created = await window.ARCHHUB_NODE_CREATE({title:(node.title || node.engine) + ' copy', engine:node.engine,
      x:free.x, y:free.y, params});
    if (created && created.ok === false) throw new Error(String(created.error || 'The fork was refused.').split(/\r?\n/)[0]);
    const createdId = created?.node?.id || created?.id || created?.node_id || created?.root;
    if (!createdId) throw new Error('Fork not confirmed');
    await studioRefreshCanvasInPlace();
    if (createdId) setCanvasSelectedIds([createdId]);
    return 'Fork placed.';
  }, [positions, allNodes, cardHeights]);
  React.useEffect(() => {
    window.__archhubDuplicateNode = duplicateNode;
    window.__archhubSelectNodeById = nodeId => { if (nodeId) { setCanvasSelectedIds([nodeId]); setPickedId(nodeId); setFocusId(nodeId); } };
    return () => {
      if (window.__archhubDuplicateNode === duplicateNode) delete window.__archhubDuplicateNode;
      delete window.__archhubSelectNodeById;
    };
  }, [duplicateNode]);
  const menuDuplicate = node => menuTask(() => duplicateNode(node));
  const menuOpenInside = node => menuTask(async () => {
    if (authority) { await authority.open(node.id); return ''; }
    await window.ARCHHUB_SCOPE_OPEN([...openScope.trail.map(step => step.root).filter(Boolean), node.id]);
    window.location.reload();
    return '';
  });
  const askClearAll = () => setConfirming({kind:'clear', ids:[...allIds], title:allIds.length + ' nodes', wires:graph.wires.length});
  const confirmRemoval = () => {
    const held = confirming;
    setConfirming(null);
    if (!held) return;
    menuTask(async () => {
      let removed = 0;
      try {
        for (const root of held.ids) { await removeNode(root); removed += 1; }
      } catch (error) {
        throw new Error((removed ? removed + ' of ' + held.ids.length + ' nodes were removed, then: ' : '') +
          (error?.message || 'Removal was refused.'));
      }
      await studioRefreshCanvasInPlace();
      return removed === 1 ? 'The node was deleted.' : removed + ' nodes were deleted.';
    });
  };
  const menuHasSeed = !!ctxMenu?.nodeId || selected.size > 0 || allIds.includes(focusId);
  // Each action names why it is disabled; CanvasMenu shows that reason as the item title.
  const busyWhy = layoutBusy || authorityState?.pending ? 'Wait for the canvas to finish saving' : 'Refresh the canvas first';
  const menuWhyBusy = menuBusy ? 'Wait for the current action to finish' : busyWhy;
  const noNodesWhy = 'This canvas has no nodes', noSelectionWhy = 'Nothing is selected', noSeedWhy = 'Select or right-click a node first';
  const layoutWhy = fallback => blocked ? busyWhy : !canSaveLayout ? 'This connection cannot save node positions' : fallback;
  // The design's canvas menu, row for row (design studio-lm.jsx:1520-1573). Each row runs the application's own
  // action; a row this build has no action for is drawn disabled and says why.
  const canvasMenuItems = [
    {i:'＋', t:'Add node…', k:studioShortcutMenu('canvas-add-node'), shortcutId:'canvas-add-node', action:() => setLibraryOpen(true), disabled:blocked, why:busyWhy},
    ...(selected.size >= 2 ? [{i:'⊞', t:'Group selection → grand node', k:studioShortcutMenu('canvas-group'), shortcutId:'canvas-group',
      action:composeCurrentSelection, disabled:!composer || blocked || menuBusy, why:!composer ? 'Grouping needs the live graph' : menuWhyBusy}] : []),
    {i:'⎘', t:'Paste', k:'⌘V', disabled:true, why:'Copying and pasting nodes is not available in this build'},
    {sep:true},
    {i:'⌴', t:'Fit graph to view', k:studioShortcutMenu('canvas-fit-graph'), shortcutId:'canvas-fit-graph', action:() => fitIds(allIds), disabled:!allIds.length, why:noNodesWhy},
    {i:'⊜', t:'Zoom to 100%', k:studioShortcutMenu('canvas-zoom-100'), shortcutId:'canvas-zoom-100', action:() => setZoom(1)},
    {sep:true},
    {i:'·', t:'Snap to grid', toggle:true, on:snap, action:() => setSnap(value => !value)},
    {i:'⧉', t:'Auto-layout', k:studioShortcutMenu('canvas-auto-layout'), shortcutId:'canvas-auto-layout', action:() => arrangeIds(selected.size ? [...selected] : allIds),
      disabled:layoutNeedsRefresh || !canSaveLayout || !allIds.length, why:layoutWhy(noNodesWhy)},
    {sep:true},
    {i:'↶', t:'Undo', k:studioShortcutMenu('canvas-undo'), shortcutId:'canvas-undo', action:() => runHistory('undo'), disabled:blocked || menuBusy || !canUndo,
      why:blocked || menuBusy ? menuWhyBusy : undoWhy},
    {i:'↷', t:'Redo', k:studioShortcutMenu('canvas-redo'), shortcutId:'canvas-redo', action:() => runHistory('redo'), disabled:blocked || menuBusy || !canRedo,
      why:blocked || menuBusy ? menuWhyBusy : redoWhy},
    {i:'✕', t:'Clear all nodes', danger:true, action:() => askClearAll(),
      disabled:!allIds.length || !removeNode || menuBusy || blocked,
      why:!allIds.length ? noNodesWhy : !removeNode ? 'Removing nodes is not available in this connection' : busyWhy},
  ];
  // A node's own menu (right-click or Shift+F10 on a card): the design's node actions first (atlas-cockpit.jsx
  // ContextMenu, node branch), each through the application's existing route, then the selection, fit and
  // refresh actions this build adds. An action with no route here is dashed and says why.
  const menuNode = allNodes.find(node => node.id === ctxMenu?.nodeId) || null;
  const menuNodeWires = menuNode ? graph.wires.filter(wire => wire.id && (wire.from?.[0] === menuNode.id || wire.to?.[0] === menuNode.id)) : [];
  const openScope = authorityState?.canvas?.scope;
  const canOpenInside = !!menuNode?.openable && (authority ? true :
    typeof window.ARCHHUB_SCOPE_OPEN === 'function' && Array.isArray(openScope?.trail) && openScope.trail.length > 0);
  const canDuplicate = !authority && !!menuNode?.engine && typeof window.ARCHHUB_NODE_CREATE === 'function';
  // Design ContextMenu: with two or more cards selected, the node menu leads with grouping them into one
  // grand node, the same graph Group a frame's collapse runs; wires crossing the selection's edge then end
  // on the group's boundary ports.
  const nodeMenuItems = [
    ...(selected.size >= 2 ? [{i:'⊞', t:'Group selection → grand node', accent:true,
      action:composeCurrentSelection,
      disabled:!composer || blocked || menuBusy, why:!composer ? 'Grouping needs the live graph' : menuWhyBusy}, {sep:true}] : []),
    {i:'▶', t:'Run graph', action:() => menuRun(), disabled:typeof window.ARCHHUB_RUN !== 'function' || menuBusy,
      why:menuBusy ? menuWhyBusy : 'Running is not available in this connection'},
    {i:'◉', t:'Add watcher', disabled:true, why:'Watchers are not available in this build'},
    {i:'▤', t:'Open pipeline', action:() => menuOpenInside(menuNode), disabled:!canOpenInside,
      why:menuNode && !menuNode.openable ? 'This node has nothing inside to open' : 'Opening a node is not available in this connection'},
    {sep:true},
    {i:'❄', t:'Freeze node', disabled:true, why:'Freezing a node is not available in this build'},
    {i:'⧉', t:'Duplicate', action:() => menuDuplicate(menuNode), disabled:!canDuplicate || menuBusy,
      why:menuBusy ? menuWhyBusy : authority ? 'Duplicate is not available on this canvas' : 'This node has no engine to copy'},
    {i:'⌁', t:'Disconnect all wires', action:() => menuDisconnect(menuNodeWires.map(wire => wire.id)),
      disabled:!menuNodeWires.length || !cutWire || menuBusy || layoutNeedsRefresh,
      why:!menuNodeWires.length ? 'This node has no wires' : !cutWire ? 'Removing wires is not available in this connection' : menuWhyBusy},
    {sep:true},
    {i:'✕', t:'Delete node…', danger:true, action:() => menuNode && setConfirming({kind:'node', ids:[menuNode.id],
      title:menuNode.title || menuNode.id, wires:menuNodeWires.length}),
      disabled:!removeNode || menuBusy || layoutNeedsRefresh, why:!removeNode ? 'Removing nodes is not available in this connection' : menuWhyBusy},
    {sep:true},
    {i:'⇄', t:'Select direct neighbours', action:() => selectConnected(false), disabled:!menuHasSeed, why:noSeedWhy},
    {i:'⧉', t:'Select connected group', action:() => selectConnected(true), disabled:!menuHasSeed, why:noSeedWhy},
    {i:'▣', t:'Select all nodes', k:studioShortcutMenu('canvas-select-all'), action:() => setCanvasSelectedIds(allIds), disabled:!allIds.length, why:noNodesWhy},
    {i:'✕', t:'Clear selection', action:() => { setCanvasSelectedIds([]); setPickedId(null); setFocusId(null, []); }, disabled:!selected.size, why:noSelectionWhy},
    {sep:true},
    {i:'⌴', t:'Fit selection', action:() => fitIds([...selected]), disabled:!selected.size, why:noSelectionWhy},
    {i:'⧉', t:'Auto-layout selection', action:() => arrangeIds([...selected]),
      disabled:layoutNeedsRefresh || !canSaveLayout || !selected.size, why:layoutWhy(noSelectionWhy)},
    {sep:true},
    {i:'↻', t:'Refresh canvas', action:refreshCanvas, disabled:layoutBusy || !!authorityState?.pending || (!authority && !normal),
      why:!authority && !normal ? 'Refresh is not available in this connection' : 'Wait for the canvas to finish saving'},
  ];
  // A wire's own menu (design ContextMenu wire branch): one action, through the existing unwire route.
  const wireMenuItems = [
    {i:'✕', t:'Cut this wire', danger:true, action:() => menuDisconnect([ctxMenu?.wireId]),
      disabled:!ctxMenu?.wireId || !cutWire || menuBusy || layoutNeedsRefresh,
      why:!cutWire ? 'Removing wires is not available in this connection' : menuWhyBusy},
  ];

  return (
    <div
      ref={wrapRef}
      tabIndex={0} role="region" aria-label="Workflow canvas" aria-haspopup="menu" aria-keyshortcuts="Shift+F10"
      onPointerDownCapture={()=>{suppressWireClick.current=false;}}
      onKeyDownCapture={event=>{if(event.key==='Enter'||event.key===' ')suppressWireClick.current=false;}}
      onMouseDown={onCanvasMouseDown}
      onContextMenu={onContextMenu}
      onKeyDown={onCanvasKeyDown}
      onWheel={onWheel}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      style={{
        gridColumn:'1', gridRow:libraryMode?'1':'2', position:'relative', overflow:'hidden',
        height:'100%', minHeight:0,
        background:LM.bgCanvas,
        backgroundImage:`radial-gradient(${LM.lineHair} 1px, transparent 1px)`,
        // The dot grid is fixed: shifting it on every pan repainted the whole canvas (canvas-perf).
        backgroundSize:`${20*zoom}px ${20*zoom}px`,
        cursor: dragRef.current?.mode === 'pan' ? 'grabbing' : 'grab',
        userSelect:'none',
        outline: dropTarget ? `1px dashed ${LM.accent}66` : undefined,
        outlineOffset:-1,
      }}>
      {canvasRequestState === 'error' && <window.AH_DS.EmptyState data-canvas-state="error" error
        title="Canvas unavailable" detail={authorityState.error} onRetry={refreshCanvas} style={{position:'absolute',inset:60}}/>}
      {canvasRequestState === 'waiting' && <window.AH_DS.EmptyState data-canvas-state="waiting"
        title="Reading your workspace…" style={{position:'absolute',inset:60}}/>}
      {canvasRequestState === 'empty' && <window.AH_DS.EmptyState data-canvas-state="empty"
        title="Build your graph" detail="Add a node to start, or open a session from Chats."
        action={<window.AH_DS.Btn onClick={()=>setLibraryOpen(true)}>Add node</window.AH_DS.Btn>} style={{position:'absolute',inset:60}}/>}
      <div style={{
        // One composited layer: pan and zoom are a single transform, never left/top (canvas-perf).
        position:'absolute', left:0, top:0, willChange:'transform',
        transform:`translate3d(${pan.x}px, ${pan.y}px, 0) scale(${zoom})`, transformOrigin:'0 0',
      }}>
        {marquee && <div data-marquee={marquee.x1 < marquee.x0 ? 'crossing' : 'window'} aria-hidden="true" style={{
          position:'absolute', pointerEvents:'none', zIndex:4,
          left:Math.min(marquee.x0, marquee.x1), top:Math.min(marquee.y0, marquee.y1),
          width:Math.abs(marquee.x1 - marquee.x0), height:Math.abs(marquee.y1 - marquee.y0),
          border:`1px ${marquee.x1 < marquee.x0 ? 'dashed' : 'solid'} ${LM.accent}`, background:LM.accent + '14'}}/>}
        {draggingNode && Array.isArray(openScope?.trail) && openScope.trail.length > 1 && <div data-group-drop-band role="note"
          aria-label={'Move out to ' + (openScope.trail[openScope.trail.length - 2]?.label || 'parent')} style={{
          position:'absolute', left:0, right:0, top:0, height:34, zIndex:7, pointerEvents:'none',
          display:'grid', placeItems:'center', background:LM.accentDim,
          borderBottom:`1.5px dashed ${LM.accent}`, color:LM.accent, fontSize:12, fontWeight:600}}>
          {'Move out to ' + (openScope.trail[openScope.trail.length - 2]?.label || 'parent')}
        </div>}
        <svg width="2400" height="1400" style={{ position:'absolute', left:0, top:0, pointerEvents:'none', overflow:'visible' }} className="lm-wires">
          {wires.map(w => {
            const dx = Math.max(40, Math.abs(w.x2 - w.x1) * 0.5);
            const d = `M${w.x1},${w.y1} C${w.x1+dx},${w.y1} ${w.x2-dx},${w.y2} ${w.x2},${w.y2}`;
            const color = WIRE[w.t] || LM.inkSoft;
            const strokeW = w.selected ? 3.2 : w.focused ? 2.4 : 1.4;
            // Resting .72 (3:1 on the canvas); wires touching the selection are 1. The graph
            // always holds a selection, so wires outside it keep the resting .72, never fade.
            const op = w.focused ? 1 : 0.72;
            return (
              <g key={w.i}>
                <path d={d} stroke="transparent" strokeWidth={14} fill="none"
                  onClick={(e) => { e.stopPropagation(); const root = authorityState ? graph.wires[w.i].id : 'wire:' + w.i; setPickedId(root); setFocusId(root); }}
                  onContextMenu={(e) => {
                    const root = authorityState ? graph.wires[w.i].id : 'wire:' + w.i;
                    setPickedId(root); setFocusId(root);
                    openContextMenu(e, null, graph.wires[w.i].id || null);
                  }}
                  data-wire-id={graph.wires[w.i].id || undefined}
                  style={{ pointerEvents: 'stroke', cursor: 'pointer' }}>
                  <title>{graph.wires[w.i].label || 'Open this connection · right-click for actions'}</title>
                </path>
                <path data-wire-list={w.list ? 'true' : undefined} d={d} stroke={w.selected ? LM.accent : color} strokeWidth={strokeW} fill="none" opacity={op} style={{ pointerEvents: 'none' }}/>
                {system && graph.wires[w.i].label && <text data-sysnode-wire-label={graph.wires[w.i].id}
                  x={(w.x1 + w.x2) / 2} y={(w.y1 + w.y2) / 2 - 5} textAnchor="middle"
                  fill={LM.ink} stroke={LM.bgCanvas || LM.bgDeep} strokeWidth={4} paintOrder="stroke"
                  style={{fontFamily:LM.sans, fontSize:12, pointerEvents:'none'}}>{graph.wires[w.i].label}</text>}
                {w.list && <path data-wire-list-strand="" d={`M${w.x1},${w.y1+4} C${w.x1+dx},${w.y1+4} ${w.x2-dx},${w.y2+4} ${w.x2},${w.y2+4}`}
                  stroke={w.selected ? LM.accent : color} strokeWidth={strokeW} fill="none" opacity={op} style={{pointerEvents:'none'}}/>}
                {w.animated && (
                  <path d={d} stroke={color} strokeWidth={strokeW} fill="none" strokeDasharray="6 10" style={{ animation:'lmDash 0.9s linear infinite' }}/>
                )}
              </g>
            );
          })}
          {wirePreview && (() => {
            const dx = Math.max(40, Math.abs(wirePreview.x2 - wirePreview.x1) * 0.5);
            const d = `M${wirePreview.x1},${wirePreview.y1} C${wirePreview.x1+dx},${wirePreview.y1} ${wirePreview.x2-dx},${wirePreview.y2} ${wirePreview.x2},${wirePreview.y2}`;
            const color = WIRE[wirePreview.t] || LM.inkSoft;
            return <path data-pending-wire="" d={d} stroke={color} strokeWidth={2.2} fill="none" opacity={0.9}
              strokeDasharray="6 7" style={{ pointerEvents:'none' }}/>;
          })()}
        </svg>

        {allNodes.map(n => {
          const pos = positions[n.id] || { x: n.x, y: n.y };
          const on = cardHandlers(n.id);
          return (
            <MemoNodeRenderer libraryMode={libraryMode}
              key={n.id}
              n={n} x={pos.x} y={pos.y}
              themeEpoch={themeEpoch}
              selected={selected.has(n.id)}
              focused={n.id === focusId}
              onPortBand={on.band}
              onExpand={n.composition && composer ? on.expand : undefined}
              dimmed={dimmedIds.has(n.id) && !n._user}
              expanded={!!expanded[n.id]}
              onToggleExpand={on.toggle}
              onDragStart={on.drag}
              onFocus={on.focus}
              onContextMenu={on.menu}
              onKeyDown={on.key}
              onSocket={on.socket}
              onSocketDrag={on.socketDrag}
              onOpen={n.openable && (authority || typeof window.ARCHHUB_SCOPE_OPEN === 'function') ? on.open : undefined}
              onMemberLeave={leaveGroupMember}
              watchActions={on.watch}
              screenToCanvasPoint={screenToCanvasPoint}
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
          <li key={wire.i}>{wire.id ? <window.AH_DS.Btn onClick={() => setFocusId(authorityState ? wire.id : 'wire:' + wire.i)}
            style={{...window.AH_DS.styles.button("secondary", true), overflowWrap:'anywhere', textAlign:'left', maxWidth:'100%'}}>{wire.id}</window.AH_DS.Btn> :
            'Unnamed connection'}: {wire.reason}</li>)}</ul>
        {unresolvedWires.length > 20 && <p>{unresolvedWires.length - 20} more connections are affected.</p>}
      </details>}
      {/* Below the minimap (MiniMap: right 14, top 14, 96 tall), never over it. The design canvas draws no status chip:
          only a save in flight, a refusal or a half-made wire draws one. Refresh is also in a node's own menu. */}
      {overlapCount > 1 && canSaveLayout && !layoutBusy && <div data-no-pan data-overlap-chip={overlapCount} role="group" aria-label={overlapCount + ' cards overlap'} style={{
        position:'absolute', left:14, bottom:14, zIndex:6, display:'flex', gap:8, alignItems:'center',
        background:LM.bgPanel, border:`1px solid ${LM.line}`, padding:'5px 8px 5px 10px', borderRadius:6, fontSize:12, color:LM.inkSoft}}>
        {overlapCount} cards overlap
        <window.AH_DS.Btn type="button" onClick={() => arrangeIds(allNodes.map(node => node.id))} style={{...window.AH_DS.styles.button("secondary", true)}}>Arrange</window.AH_DS.Btn>
      </div>}
      {(layoutBusy || burstPending || authorityState?.pending || wireStart || unwrittenLayout || menuBusy) &&
      <div data-no-pan style={{position:'absolute', top:118, right:14, zIndex:5,
        display:'flex', gap:8, alignItems:'center', maxWidth:'55%', background:LM.bgPanel, padding:'6px 10px', borderRadius:6}}>
        <span role="status" style={{fontSize:12,
          color:LM.inkSoft, overflowWrap:'anywhere'}}>
          {menuBusy ? 'Working…' : layoutBusy || burstPending ? 'Saving positions…' :
            authorityState?.pending ? 'Saving…' : unwrittenLayout ?
              'Positions moved in the last session were never confirmed (' +
              Object.keys(unwrittenLayout.next).length + '). Move them again to save them.' :
            (wireStart.reverse ? 'Choose an output for ' : 'Choose an input for ') + wireStart.port.label}
        </span>
        {wireStart && <window.AH_DS.Btn disabled={blocked} onClick={() => setWireStartState(null)} title="Cancel wire" aria-label="Cancel wire" style={window.AH_DS.styles.button("ghost", true)}>✕</window.AH_DS.Btn>}
        <window.AH_DS.Btn disabled={layoutBusy || !!authorityState?.pending || (!authority && !normal)} onClick={refreshCanvas}
          title="Refresh canvas" aria-label="Refresh canvas" style={window.AH_DS.styles.button("ghost", true)}>↻</window.AH_DS.Btn>
      </div>}
      {/* Drop-target ghost */}
      {dropTarget && (
        <div style={{
          position:'absolute', left:dropTarget.x - 90, top:dropTarget.y - 24,
          width:180, height:48, pointerEvents:'none',
          background:LM.accent + '14', border:`1.5px dashed ${LM.accent}`,
          borderRadius:LM.rad.md, display:'grid', placeItems:'center',
          fontFamily:LM.mono, fontSize:LM_FS_DATASM.sz, color:LM.accent, letterSpacing:'0.06em',
        }}>Adding {dropTarget.title || 'node'}</div>
      )}

      {selected.size >= 2 && <div data-no-pan data-selection-bar style={{
        position:'absolute', left:'50%', bottom:48, transform:'translateX(-50%)', zIndex:8,
        display:'flex', gap:8, alignItems:'center', padding:'5px',
        background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:LM.rad.md,
        boxShadow:'0 10px 24px rgba(0,0,0,.35)',
      }}>
        <window.AH_DS.Btn type="button" onClick={composeCurrentSelection} title="Group selected nodes · Ctrl+G"
          disabled={!composer || layoutBusy || layoutNeedsRefresh || authorityState?.requires_refresh || menuBusy} style={window.AH_DS.styles.button(false ? 'primary' : 'secondary', true)}>
          Group {selected.size} nodes <kbd style={kbd()}>Ctrl+G</kbd>
        </window.AH_DS.Btn>
        <window.AH_DS.Btn type="button" onClick={() => arrangeIds([...selected])}
          disabled={layoutNeedsRefresh || !canSaveLayout} style={window.AH_DS.styles.button(false ? 'primary' : 'secondary', true)}>Arrange selected</window.AH_DS.Btn>
        <window.AH_DS.Btn type="button" onClick={() => selectConnected(true)}
          style={window.AH_DS.styles.button(false ? 'primary' : 'secondary', true)}>Select connected</window.AH_DS.Btn>
      </div>}

      {canvasRequestState === 'loaded' && !system && !libraryMode && allIds.length>0 && <window.AH_DS.Card data-canvas-scope-frame="" style={{position:'absolute',inset:'14px 14px 110px',top:toolbarHost?14:50,background:'transparent',borderRadius:10,overflow:'visible',pointerEvents:'none'}}>
        <div style={{position:'absolute',top:-12,left:12,right:8,display:'flex',alignItems:'center',gap:8,fontSize:12}}>
          <span style={{background:LM.bgCanvas,padding:'0 8px'}}><strong>{authorityState?.canvas?.scope?.label || authorityState?.canvas?.label || 'Canvas'}</strong> · {allIds.length} nodes · {graph.wires.length} wires</span>
          {graph.nodes.some(node=>node.state==='running') && <span data-canvas-live-state="" style={{background:LM.accent+'1f',color:LM.accent,borderRadius:999,padding:'2px 8px'}}>{graph.nodes.filter(node=>node.state==='running').length} running</span>}
          {graph.nodes.some(node=>canvasNeedsUser(node) || typeof isWorkshopGraphNode==='function' && isWorkshopGraphNode(node) && workshopModel?.needs_user) && <span data-canvas-needs-user="" style={{background:LM.warn+'1f',color:LM.warn,borderRadius:999,padding:'2px 8px'}}>{graph.nodes.filter(node=>canvasNeedsUser(node) || typeof isWorkshopGraphNode==='function' && isWorkshopGraphNode(node) && workshopModel?.needs_user).length} waits for you</span>}
          <span style={window.AH_DS.styles.fill}/><window.AH_DS.Btn sm kind="ghost" style={{pointerEvents:'auto'}} disabled={!composer || blocked} onClick={()=>composeGroup('group',allIds,'Collapsed this scope into one group.')} title="Collapse group · Ctrl+K">⊞ Collapse</window.AH_DS.Btn>
        </div>
      </window.AH_DS.Card>}
      <CanvasToolbar host={toolbarHost} compact={true} system={system} onRun={() => menuRun()} runDisabled={typeof window.ARCHHUB_RUN !== 'function' || menuBusy || blocked}
        title={system ? '' : authorityState?.canvas?.scope?.label || authorityState?.canvas?.label || ''}
        project={system ? '' : authorityState?.canvas?.project_label || ''} waiting={system ? 0 : graph.nodes.filter(node=>canvasNeedsUser(node)||typeof isWorkshopGraphNode==='function'&&isWorkshopGraphNode(node)&&workshopModel?.needs_user).length}
        status={!system && (workshopSnapshot?.nativeWork?.state === 'executing' || workshopModel?.members?.some(row=>row.presence==='working')) ? 'Running' : ''}
        undo={{run:() => runHistory('undo'), disabled:blocked || menuBusy || !canUndo, why:undoWhy}}
        redo={{run:() => runHistory('redo'), disabled:blocked || menuBusy || !canRedo, why:redoWhy}}
        zoom={zoom} setZoom={(updater) => {
        setZoom(z => {
          const next = typeof updater === 'function' ? updater(z) : updater;
          return canvasClampZoom(next);
        });
      }} onFit={() => fitIds(selected.size ? [...selected] : allIds)}
        onArrange={() => arrangeIds(allIds, {fitAfter:true})}
        arrangeDisabled={layoutNeedsRefresh || !canSaveLayout || !allIds.length}
        arrangeWhy={layoutWhy(noNodesWhy)}
        fitLabel={selected.size ? 'Fit selection' : 'Fit all nodes'} setLibraryOpen={setLibraryOpen}/>

      <CanvasAddBox compact={system || libraryMode} setLibraryOpen={setLibraryOpen}/>
      {ctxMenu && <CanvasMenu x={ctxMenu.x} y={ctxMenu.y} maxHeight={ctxMenu.maxHeight}
        opener={ctxMenu.opener} items={ctxMenu.nodeId ? nodeMenuItems : ctxMenu.wireId ? wireMenuItems : canvasMenuItems}
        label={ctxMenu.nodeId ? 'Node actions' : ctxMenu.wireId ? 'Wire actions' : 'Canvas actions'} onClose={closeContextMenu}/>}
      <CanvasDestructiveDialog confirming={confirming} onCancel={() => setConfirming(null)} onConfirm={confirmRemoval}/>
      <CanvasToast toast={appToast}/>
    </div>
  );
};

const CanvasContextHint = () => null;

const CanvasHint = () => null;

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
        <window.AH_DS.Btn key={i} role={it.toggle ? 'menuitemcheckbox' : 'menuitem'} aria-checked={it.toggle ? !!it.on : undefined}
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
          <span style={{ width:14, color: it.danger ? LM.err : LM.inkSoft, fontFamily:LM.mono, fontSize:11, textAlign:'center' }}>{it.i}</span>
          <span style={window.AH_DS.styles.fill}>{it.t}</span>
          {it.toggle && (
            <span style={{
              width:22, height:12, borderRadius:999,
              background: it.on ? LM.accent : LM.lineSoft, position:'relative',
            }}>
              <span style={{ position:'absolute', top:1, left: it.on ? 11 : 1, width:10, height:10, borderRadius:'50%', background:'#fff' }}/>
            </span>
          )}
          {it.k && <kbd style={kbd()}>{it.k}</kbd>}
        </window.AH_DS.Btn>
      ))}
    </div>
  );
};

// ─── nodes dispatcher ───
const NodeRenderer = ({ libraryMode = false, n: held, x = held.x, y = held.y, selected, focused, dimmed, expanded, onToggleExpand, onDragStart, onFocus, onSocket, onSocketDrag, onOpen, onContextMenu, onKeyDown, onPortBand, onExpand, onMemberLeave, screenToCanvasPoint, watchActions }) => {
  const n = held.x === x && held.y === y ? held : {...held, x, y};
  if (typeof window !== 'undefined' && window.__archhubCardRenders) window.__archhubCardRenders[held.id] = (window.__archhubCardRenders[held.id] || 0) + 1;
  const cat = studioCategory(n.cat);
  // AI nodes can expand horizontally for full conversation + search
  const isAi = n.cat === 'ai';
  const workshopCard = !n.application && typeof isWorkshopGraphNode === 'function' && isWorkshopGraphNode(n);
  const cardW = workshopCard ? (n.w || 320) : (isAi && expanded) ? Math.max(520, n.w || NODE_CARD_W) :
    Number.isFinite(n.w) && n.w >= 120 ? n.w : nodeIsWatch(n) ? 260 : NODE_CARD_W;
  const agent = n.application ? null : canvasAgentRecord(n);
  const title = agent?.label || agent?.name || nodeCardTitle(n);
  const subtitle = agent ? agent.modelLabel : nodeCardSubtitle(n, cat);
  const lit = selected || focused;
  const cardRef = React.useRef(null), bandRef = React.useRef(null);
  const rows = Math.max(n.ins?.length || 0, n.outs?.length || 0);
  const sessionCard = isSessionNodeShape(n);
  const groupCard = !!n.composition && !sessionCard && !n.application;
  const groupMembers = Array.isArray(n.members) ? n.members : [];
  const handleClick = e => {
    onFocus && onFocus(e);
  };
  const handleKeyDown = e => {
    if ((e.key === 'Enter' || e.key === ' ') && workshopCard) {
      e.preventDefault();
      const root = n.conversation_root || n.workshop_root || n.id;
      window.dispatchEvent(new window.CustomEvent('archhub:reach-conversation', {detail:root}));
      return;
    }
    if ((e.key === 'Enter' || e.key === ' ') && onOpen && (sessionCard || groupCard)) {
      e.preventDefault(); onOpen(e); return;
    }
    onKeyDown && onKeyDown(e);
  };
  const [memberDragTrace, setMemberDragTrace] = React.useState({});
  const memberDragActive = React.useRef(null);
  const memberDragCleanup = React.useRef(null);
  React.useEffect(() => () => {
    memberDragCleanup.current?.();
  }, []);
  const startMemberDrag = (member, e) => {
    const memberId = typeof member === 'string' ? member : member.id || member.root || member.title || member.label;
    if (!memberId || !onMemberLeave) return;
    if ((e.button ?? 0) !== 0) return;
    if (memberDragActive.current) return;
    e.preventDefault(); e.stopPropagation();
    const chip = e.currentTarget;
    const setDragState = state => {
      chip?.setAttribute?.('data-member-drag', state);
      setMemberDragTrace(trace => trace[memberId] === state ? trace : {...trace, [memberId]:state});
    };
    const bounds = cardRef.current?.getBoundingClientRect?.();
    const sx = e.clientX, sy = e.clientY;
    let moved = false, last = {x:sx, y:sy};
    const outside = point => !bounds || point.x < bounds.left || point.x > bounds.right || point.y < bounds.top || point.y > bounds.bottom;
    memberDragActive.current = memberId;
    setDragState('armed');
    try { chip?.setPointerCapture?.(e.pointerId); } catch (error) { /* best effort; window listeners are the fallback */ }
    let finished = false;
    const move = ev => {
      ev.preventDefault?.(); ev.stopPropagation?.();
      last = {x:ev.clientX, y:ev.clientY};
      if (Math.hypot(last.x - sx, last.y - sy) >= 8) moved = true;
      if (moved && outside(last)) setDragState('left');
    };
    const finish = (ev, commit, quiet = false) => {
      if (finished) return;
      finished = true;
      ev?.preventDefault?.(); ev?.stopPropagation?.();
      if (Number.isFinite(ev?.clientX) && Number.isFinite(ev?.clientY)) {
        last = {x:ev.clientX, y:ev.clientY};
        // Native shells can coalesce all movement into the release event.
        if (Math.hypot(last.x - sx, last.y - sy) >= 8) moved = true;
      }
      for (const target of [document, window]) {
        target.removeEventListener('mousemove', move, true);
        target.removeEventListener('mouseup', up, true);
        target.removeEventListener('pointermove', move, true);
        target.removeEventListener('pointerup', up, true);
        target.removeEventListener('pointercancel', cancel, true);
      }
      try { chip?.releasePointerCapture?.(e.pointerId); } catch (error) { /* best effort */ }
      memberDragActive.current = null;
      memberDragCleanup.current = null;
      if (!commit) {
        if (!quiet) setDragState('cancelled');
        return;
      }
      if (moved && outside(last)) {
        const point = typeof screenToCanvasPoint === 'function'
          ? screenToCanvasPoint(last.x, last.y)
          : {x:last.x, y:last.y};
        setDragState('pending');
        // A trace is evidence of the transport result, not of a pointer release.
        Promise.resolve().then(() => onMemberLeave(memberId, n.id, point)).then(result => {
          if (!result || result.ok === false) setDragState('refused: ' + (result?.error || 'Membership was not sent.'));
          else setDragState('posted');
        }).catch(error => setDragState('refused: ' + (error?.message || 'Membership was not sent.')));
      }
    };
    const up = ev => finish(ev, true);
    const cancel = ev => finish(ev, false);
    memberDragCleanup.current = () => finish(null, false, true);
    for (const target of [document, window]) {
      target.addEventListener('mousemove', move, true);
      target.addEventListener('mouseup', up, true);
      target.addEventListener('pointermove', move, true);
      target.addEventListener('pointerup', up, true);
      target.addEventListener('pointercancel', cancel, true);
    }
  };
  // The band follows the content: report its card-local top whenever the card resizes.
  React.useLayoutEffect(() => {
    const card = cardRef.current, band = bandRef.current;
    if (!card || !onPortBand) return undefined;
    const report = () => onPortBand(band ? card.clientTop + band.offsetTop : NaN, card.offsetHeight);
    report();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const watch = new ResizeObserver(report); watch.observe(card);
    return () => watch.disconnect();
  }, [rows, onPortBand]);
  if (workshopCard) return <GraphWorkshopFace n={n} nodeRef={cardRef} rootProps={{className:'lm-node','data-node-id':n.id,'data-library-canvas-node':libraryMode?'':undefined,'data-group':n.group || undefined,'data-selected':selected?'true':undefined,'data-focused':focused?'true':undefined,onClick:handleClick,onContextMenu,onKeyDown:handleKeyDown,tabIndex:0,role:'group','aria-label':'Workshop node',style:{position:'absolute',left:n.x,top:n.y,width:cardW,opacity:dimmed?.42:1,zIndex:lit?3:2,outline:focused?LM.selection.outline:'none',outlineColor:LM.accent}}}
    onDragStart={onDragStart} bandRef={bandRef} onSocket={onSocket} onSocketDrag={onSocketDrag}
    startMemberDrag={onMemberLeave?startMemberDrag:null} memberDragTrace={memberDragTrace}/>;
  return <window.AH_DS.Node nodeRef={cardRef} bandRef={bandRef} className="lm-node" data-node-id={n.id} data-library-canvas-node={libraryMode?'':undefined}
    data-group={n.group || undefined} data-canvas-card-skin="061" data-agent-node={agent ? n.id : undefined}
    data-node-state={canvasNeedsUser(n) ? 'needs-user' : n.state || n.status || 'unavailable'}
    data-session-card={sessionCard ? 'true' : undefined} data-group-card={groupCard ? 'true' : undefined}
    data-selected={selected ? 'true' : undefined} data-focused={focused ? 'true' : undefined}
    onClick={handleClick} onDoubleClick={onOpen} onContextMenu={onContextMenu} onKeyDown={handleKeyDown}
    tabIndex={0} role="group" aria-label={(n.title || n.id) + ' node'} aria-haspopup="menu" aria-keyshortcuts="Shift+F10"
    title={title} sub={subtitle} glyph={agent ? String(title).slice(0,1).toUpperCase() : cat.icon} gc={cat.col}
    w={cardW} edge={n.edge} stacked={groupCard} selected={lit} run={n.state==='running'} onHeaderMouseDown={onDragStart}
    ins={n.ins || []} outs={n.outs || []}
    renderPort={(s,i,side)=><Socket key={side+'-'+s.id} id={s.id} side={side} i={i} t={s.t} label={s.label}
      list={!!s.list || !!s.multiple} half={cardW/2} connected={!!s.connected}
      onUse={s.connectable && onSocket ? ()=>onSocket(s,side) : undefined}
      onDragStart={s.connectable && onSocketDrag ? e=>onSocketDrag(e,s,side) : undefined}/>}
    footc={canvasStatusColor(n)} foot={n.application ? <window.ApplicationNodeParameters node={n} compact footer status={n.result_summary || canvasStatusText(n)}/> : [agent?.taskTitle,n.result_summary || canvasStatusText({...n,state:n.state || agent?.state || agent?.live_state})].filter(Boolean).join(' · ') || 'Not run'}
    style={{position:'absolute',left:n.x,top:n.y,width:cardW,minHeight:n.h,color:LM.ink,fontFamily:LM.sans,
      opacity:dimmed ? .42 : 1,zIndex:lit?3:2,userSelect:'none'}}
    headerExtra={<>
      {groupCard && Number.isSafeInteger(n.memberCount) && <span data-member-count={n.memberCount}>{n.memberCount} nodes</span>}
      {onExpand && groupCard && <window.AH_DS.Btn sm kind="ghost" aria-label={'Expand '+(n.title || 'group')} title="Expand group · Enter"
        onMouseDown={e=>e.stopPropagation()} onClick={e=>{e.stopPropagation();onExpand();}}>Ungroup</window.AH_DS.Btn>}
      {isAi && !agent && !n.application && <window.AH_DS.Btn sm kind="ghost" title={expanded?'Collapse':'Expand & search'} aria-label={expanded?'Collapse':'Expand & search'}
        onClick={e=>{e.stopPropagation();onToggleExpand?.();}}>{expanded?'↖':'⤢'}</window.AH_DS.Btn>}
    </>}>
      {/* Body */}
      <div style={{ padding:n.application ? 0 : '0 10px 8px' }}>
        {sessionCard && <div data-session-ports style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:8, marginTop:8,
          fontSize:11, color:LM.inkSoft}}>
          <div><strong style={{fontSize:LM_FS_LABEL.sz, color:LM.inkSoft, textTransform:'uppercase'}}>Accepts</strong><br/>{(n.ins || []).length || 0} sockets</div>
          <div><strong style={{fontSize:LM_FS_LABEL.sz, color:LM.inkSoft, textTransform:'uppercase'}}>Emits</strong><br/>{(n.outs || []).length || 0} sockets</div>
        </div>}
        {groupCard && <div data-boundary-sockets style={{fontFamily:LM.mono, fontSize:LM_FS_DATASM.sz, color:LM.inkSoft, marginTop:6}}>
          boundary sockets · {(n.ins?.length || 0)} in · {(n.outs?.length || 0)} out
        </div>}
        {groupCard && groupMembers.length > 0 && <div data-member-chips style={{display:'flex', flexWrap:'wrap', gap:6, marginTop:8}}>
          {groupMembers.map(member => {
            const id = typeof member === 'string' ? member : member.id || member.title || member.label;
            const name = typeof member === 'string' ? member : member.title || member.label || member.id;
            return <span key={id || name} data-member-chip={id || name} data-member-drag={memberDragTrace[id || name] || undefined} draggable={false} onDragStart={e => e.preventDefault()}
              onPointerDown={onMemberLeave ? e => startMemberDrag(member, e) : undefined}
              onMouseDown={onMemberLeave ? e => startMemberDrag(member, e) : undefined} style={{height:24, display:'inline-flex',
              alignItems:'center', gap:5, padding:'0 7px', border:`1px solid ${LM.line}`, borderRadius:6, background:LM.bgSoft,
              fontSize:12, color:LM.ink, cursor:onMemberLeave ? 'grab' : 'default'}}>
              <span aria-hidden="true" style={{width:16, height:16, borderRadius:4, display:'grid', placeItems:'center',
                background:cat.col + '22', color:cat.col, fontSize:LM_FS_LABEL.sz}}>{String(name || '?').slice(0, 1).toUpperCase()}</span>
              {name}
            </span>;
          })}
        </div>}
        <div data-node-preview-slot="" style={{minHeight:0, borderRadius:8, overflow:'hidden'}}>
          {!agent && <NodeBody n={n} expanded={expanded} onToggleExpand={onToggleExpand} watchActions={watchActions}/>}
          {!nodeIsWatch(n) && nodePlanPreviewFor(n) ? <NodePlanPreview node={n}/> : !nodeIsWatch(n) && n.preview && typeof WatchPreview === 'function' &&
            (n.preview.kind === 'image' && n.preview.state === 'ready' ? <WatchImage value={n.preview.value}/> : <WatchPreview node={n} actions={watchActions}/>)}
          {agent && !n.preview && n.result != null && <span style={{fontSize:12.5,color:LM.inkSoft}}>{typeof n.result === 'object' ? JSON.stringify(n.result) : String(n.result)}</span>}
          {!n.application && !nodeIsWatch(n) && !n.preview && !n.result && !(n.params || []).some(row=>!window.ARCHHUB_INTERNAL_PARAM_KEYS?.has(row.k)) && !n.status && !n.state && !n.result_summary && !(window.ARCHHUB_LAST_RUN?.lines?.[n.id]?.length) &&
            <span aria-disabled="true" style={{fontSize:12.5, color:LM.inkSoft}}>Unavailable</span>}
        </div>
      </div>

  </window.AH_DS.Node>;
};

// A card re-renders only when what it draws changed: its node record, its place, or its focus, dim and
// expansion. Its handlers are stable (NodeCanvas cardHandlers), so a drag re-renders the moving card only.
const MemoNodeRenderer = React.memo(NodeRenderer, (a, b) => a.n === b.n && a.x === b.x && a.y === b.y &&
  a.themeEpoch === b.themeEpoch && a.libraryMode === b.libraryMode &&
  a.focused === b.focused && a.selected === b.selected && a.dimmed === b.dimmed && a.expanded === b.expanded && !!a.onOpen === !!b.onOpen && !!a.onExpand === !!b.onExpand && a.onMemberLeave === b.onMemberLeave);

const Socket = ({ id, side, i, t, label, list = false, onUse, onDragStart, half = 110, connected = false, plate = false }) => {
  const col = WIRE[t] || window.PM_WIRE?.[t] || (window.pmType && window.pmType(t)?.col) || LM.inkSoft;
  const socketShape = list ? 'diamond' : socketShapeOf(t, false);
  // The dot is a button, so a connectable port starts or finishes a wire; a port that cannot be connected stays inert.
  return (
    <div style={{
      position:'absolute', top: portRowCentre(i) - SOCKET_R - 1,
      [side === 'in' ? 'left' : 'right']: -SOCKET_R - 1,
      display:'flex', alignItems:'center', gap:6,
      flexDirection: side === 'in' ? 'row' : 'row-reverse',
      pointerEvents: onUse ? 'auto' : 'none',
    }}>
      <window.AH_DS.Btn type="button" role="button" aria-label={(side === 'out' ? 'Connect output ' : 'Connect input ') + label}
        title={(side === 'out' ? 'Connect output ' : 'Connect input ') + label}
        data-studio-socket={onUse ? 'true' : undefined}
        data-socket-side={side}
        data-socket-port={id}
        data-socket-type={t || 'any'}
        data-socket-label={label}
        data-socket-type-label={socketTypeLabel(t)}
        data-socket-color={col}
        data-socket-shape={socketShape}
        data-socket-connected={connected ? 'true' : 'false'}
        disabled={!onUse} onPointerDown={onDragStart} onMouseDown={e => e.stopPropagation()}
        onKeyDown={e=>{if(onUse&&(e.key==='Enter'||e.key===' ')){e.preventDefault();e.stopPropagation();onUse();}}}
        onClick={e => { e.stopPropagation(); if (onUse) onUse(); }} style={{
        display:'block', padding:0, margin:0, flexShrink:0, cursor: onUse ? 'crosshair' : 'default',
        width: SOCKET_R*2, height: SOCKET_R*2, border:0, background:'transparent', boxShadow:'none',
      }}><window.AH_DS.Socket t={t==='trigger'?'event':t || 'any'} list={list} filled={connected} size={10} style={{borderColor:col}}/></window.AH_DS.Btn>
      {/* An input's and an output's label share one row: each gets half the card, never the other's half. */}
      <span title={label || undefined} style={{
          fontFamily:LM.sans, fontSize:12.5, color:LM.inkSoft, letterSpacing:0,
        whiteSpace:'nowrap', padding:'0 4px', pointerEvents:'none',
        maxWidth:Math.max(24, half - SOCKET_R * 2 - 10), overflow:'hidden', textOverflow:'ellipsis',
        opacity: label ? 0.85 : 0,
      }}>{label}</span>
    </div>
  );
};

// ─── per-category body content ───
// The inline reply is a real ask: it reaches the same agent the main
// composer does, and reports its answer where it was typed.
// Three scales, as he drew them: the canvas composer is the largest ask on
// the screen, the chat reply sits just under it, and the one inside a node
// is node chrome. Collapsing all three onto the smallest made the composer
// read as chrome (2026-09-07).
const ASK_SCALE = {
  composer: { field: 14, send: { padding: '4px 11px', radius: LM.rad.sm, size: 11.5 }, lead: 6 },
  reply:    { field: 13.5, send: { padding: '4px 11px', radius: LM.rad.sm, size: 11.5 }, lead: 0 },
  node:     { field: 12, send: { padding: '3px 8px', radius: 4, size: 10 }, lead: 0 },
};
// agentAnswerText (above, with the chat view) reads both the structured result and a plain string.
const agentDeliveryState = result => result && typeof result === 'object' && !Array.isArray(result) && result.delivery
  ? result.delivery.state : null;
const agentRefusalText = result => result && typeof result === 'object' && !Array.isArray(result) && result.ok === false
  ? 'The reply did not arrive: ' + String(result.error || 'provider refused the request') : '';
const agentTurnTimeoutMs = () => {
  const configured = Number(window.ARCHHUB_AGENT_TURN_TIMEOUT_MS);
  return Number.isFinite(configured) ? Math.max(1, Math.min(45000, configured)) : 45000;
};
const agentTurnWithTimeout = promise => new Promise((resolve, reject) => {
  const timer = window.setTimeout(() => reject(Object.assign(new Error('The reply did not arrive within 45 seconds. Retry when ready.'),
    {code:'AGENT_TURN_TIMEOUT'})),
    agentTurnTimeoutMs());
  Promise.resolve(promise).then(resolve, reject).finally(() => window.clearTimeout(timer));
});

const InlineAsk = ({ placeholder, model, node, onAnswer, scale, before }) => {
  const S = ASK_SCALE[scale] || ASK_SCALE.node;
  const picked = node ? null : model || (typeof window !== 'undefined' ? window.ARCHHUB_PICKED_MODEL : null);
  const route = node ? nodeModelRoute(node) : modelRoute(picked);
  const [asking, setAsking] = React.useState(false);
  const needsNode = !!window.ARCHHUB_STUDIO_AUTHORITY && !node;
  const [text, setText] = React.useState('');
  const [state, setState] = React.useState('');
  const pendingSend = React.useRef(null);
  // The composer renders the answer itself; the older inline replies have
  // nowhere to put it, so they keep showing it in the field.
  const report = (line) => { if (onAnswer) onAnswer(line); else setState(String(line).slice(0, 60)); };
  const updateText = next => {
    if (pendingSend.current && next !== pendingSend.current.raw) pendingSend.current = null;
    setText(next);
  };
  const ask = async () => {
    const said = text.trim();
    if (!said || asking || !window.ARCHHUB_AGENT) return;
    if (needsNode) { report('Select an AI node on the canvas to ask.'); return; }
    if (node && !route) { report('Choose a model for this node first.'); return; }
    setAsking(true);
    report('asking ' + (node ? route : ((picked && picked.name) || 'the agent')) + '…');
    try {
      // Node asks carry the committed route as a consistency check.
      const held = pendingSend.current;
      const requestId = node ? (held && held.raw === text && held.said === said
        ? held.requestId : window.crypto.randomUUID()) : null;
      if (node) pendingSend.current = {raw:text, said, requestId};
      const result = await window.ARCHHUB_AGENT(said, route,
        node ? {node:node.id, request_id:requestId, generation:generationRequestOptions()} : {generation:generationRequestOptions()});
      const answer = agentAnswerText(result);
      const deliveryState = agentDeliveryState(result);
      if (deliveryState && deliveryState !== 'replied') {
        report(answer);
        return;
      }
      pendingSend.current = null;
      report(answer);
      setText('');
    } catch (error) {
      // The send failed or its reply was lost: keep the text; a retry reuses the same request id,
      // so the server answers from what it already holds instead of asking the model twice.
      report('refused: ' + ((error && error.message) || error || 'no reply') +
        (node ? ' Your text is still here; sending again will not ask twice.' : ''));
    } finally {
      setAsking(false);
    }
  };
  return (
    <>
      <input value={text} disabled={needsNode} onChange={e => updateText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') ask(); }}
        placeholder={needsNode ? 'Select an AI node to ask…' : state || placeholder || 'Reply…'}
        style={{ flex:1, background:'transparent', border:0, outline:0,
          fontStyle:'italic', fontFamily:LM.serif, fontSize:S.field,
          marginLeft: S.lead || 0,
          color: state ? LM.accent : LM.ink }}/>
      {before || null}
      <window.AH_DS.Btn onClick={ask} disabled={needsNode || asking || !text.trim()} style={{ padding:S.send.padding, background:node||scale==='node'?'#26262d':LM.accent, color:node||scale==='node'?LM.ink:(window.AH && window.AH.onFill) || '#180f08', border:node||scale==='node'?`1px solid ${LM.line}`:0, borderRadius:S.send.radius, fontSize:S.send.size, fontWeight:500, cursor:'pointer' }}>{asking ? 'Waiting…' : 'Send ↵'}</window.AH_DS.Btn>
    </>
  );
};

const useLastRunEpoch = () => {
  const [epoch, setEpoch] = React.useState(0);
  React.useEffect(() => {
    const bump = () => setEpoch(value => value + 1);
    window.addEventListener('archhub-last-run', bump);
    return () => window.removeEventListener('archhub-last-run', bump);
  }, []);
  return epoch;
};

const watchPreviewFor = node => {
  const run = (typeof window !== 'undefined' && window.ARCHHUB_LAST_RUN) || {};
  return run.previews?.[node.id] || node.preview || null;
};

const WATCH_TABLE_ROWS = 20;
const WATCH_TABLE_ROWS_INSPECTOR = 25;
const WATCH_TABLE_COLS = 8;
const WATCH_TEXT_LIMIT = 200 * 1024;
const WATCH_IMAGE_DATA = /^data:image\/[a-z0-9.+-]+;base64,/i;
const WATCH_MODES = [
  ['table', 'table'], ['list', 'list'], ['json', 'json'], ['image', 'image'],
  ['number', 'number'], ['chart', 'chart'], ['geometry', '3D'],
];
const WATCH_FS_DATA = LM.fs?.dataSm || {sz:11, ln:14};
const WATCH_FS_LABEL = LM.fs?.label || {sz:10, ln:12};


const watchCellText = value => value === null || value === undefined ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value);

const parseWatchLiteral = text => {
  if (typeof text !== 'string' || text.length > WATCH_TEXT_LIMIT) return undefined;
  try { return JSON.parse(text); } catch (_) {}
  let i = 0;
  const fail = () => { throw new Error('not a bounded literal'); };
  const space = () => { while (i < text.length && /\s/.test(text[i])) i += 1; };
  const value = depth => {
    if (depth > 8) fail();
    space();
    const c = text[i];
    if (c === '"' || c === "'") {
      const quote = c; i += 1; let out = '';
      while (i < text.length && text[i] !== quote) {
        if (text[i] === '\\') { i += 1; if (i < text.length) out += text[i++]; }
        else out += text[i++];
      }
      if (text[i] !== quote) fail();
      i += 1; return out;
    }
    if (c === '[' || c === '(') {
      i += 1; const out = [];
      for (space(); text[i] !== (c === '[' ? ']' : ')'); space()) {
        out.push(value(depth + 1)); space();
        if (text[i] === ',') i += 1; else if (text[i] !== (c === '[' ? ']' : ')')) fail();
      }
      i += 1; return out;
    }
    if (c === '{') {
      i += 1; const out = {};
      for (space(); text[i] !== '}'; space()) {
        const key = value(depth + 1); space(); if (text[i] !== ':') fail(); i += 1;
        out[String(key)] = value(depth + 1); space();
        if (text[i] === ',') i += 1; else if (text[i] !== '}') fail();
      }
      i += 1; return out;
    }
    const word = /^(None|True|False|-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)/.exec(text.slice(i));
    if (!word) fail();
    i += word[0].length;
    return word[0] === 'None' ? null : word[0] === 'True' ? true : word[0] === 'False' ? false : Number(word[0]);
  };
  try { const held = value(0); space(); return i === text.length ? held : undefined; } catch (_) { return undefined; }
};

const watchPreviewFromResult = node => {
  if (node?.engine !== 'watch.preview' || typeof node.result !== 'string') return null;
  const text = node.result.trim();
  if (!text) return null;
  if (WATCH_IMAGE_DATA.test(text)) return {kind:'image', value:text, shape:{}};
  const parsed = parseWatchLiteral(text);
  if (Array.isArray(parsed) && parsed.length && (
    parsed.every(row => row && typeof row === 'object' && !Array.isArray(row)) ||
    (parsed.length > 1 && parsed.every(Array.isArray))
  )) return {kind:'table', value:parsed, shape:{rows:parsed.length}};
  return null;
};

const watchParamValue = (node, key) => Array.isArray(node?.params)
  ? (node.params.find(row => row.k === key || row.label === key) || {}).v
  : undefined;

const watchSizeValue = node => {
  const raw = String(watchParamValue(node, 'watchSize') || '').trim();
  const match = /^(\d{2,4})x(\d{2,4})$/.exec(raw);
  if (!match) return '310x140';
  const w = Math.max(180, Math.min(900, Number(match[1])));
  const h = Math.max(100, Math.min(700, Number(match[2])));
  return `${w}x${h}`;
};

const watchPersistParam = (node, key, value) => {
  if (typeof window === 'undefined' || typeof window.pmPersistValue !== 'function') return;
  try { window.pmPersistValue(node, key, value); } catch (_) {}
};

const watchRows = value => Array.isArray(value) ? value : value === null || value === undefined ? [] : [value];

const watchCsvText = value => {
  const rows = watchRows(value);
  const columns = rows.every(row => row && typeof row === 'object' && !Array.isArray(row))
    ? Array.from(rows.reduce((set, row) => { Object.keys(row).forEach(k => set.add(k)); return set; }, new Set()))
    : ['value'];
  const quote = value => `"${watchCellText(value).replace(/"/g, '""')}"`;
  return [columns.map(quote).join(','), ...rows.map(row => columns.map(col => quote(col === 'value' && !(row && typeof row === 'object' && !Array.isArray(row)) ? row : row?.[col])).join(','))].join('\n');
};

const watchExportCsv = (node, preview) => {
  const text = watchCsvText(preview?.value);
  if (typeof window !== 'undefined') {
    window.ARCHHUB_WATCH_EXPORTS = window.ARCHHUB_WATCH_EXPORTS || [];
    window.ARCHHUB_WATCH_EXPORTS.push({node:node.id, text});
  }
  return text;
};

const watchMode = value => WATCH_MODES.some(([key]) => key === value) ? value : 'table';
const watchFallbackPreview = node => watchPreviewFromResult(node) || {kind:watchParamValue(node, 'as') || 'table', state:'empty', value:null, shape:{}};

const watchState = (preview, mode) => {
  if (!preview) return 'empty';
  if (preview.state) return preview.state;
  if (mode === 'image' && !WATCH_IMAGE_DATA.test(String(preview.value || ''))) return 'empty';
  return 'ready';
};

const WatchPreview = ({ node, inspector = false, actions = {} }) => {
  useLastRunEpoch();
  const preview = watchPreviewFor(node) || watchFallbackPreview(node);
  const initialMode = watchMode(preview?.kind || watchParamValue(node, 'as') || 'table');
  const [mode, setMode] = React.useState(initialMode);
  React.useEffect(() => setMode(initialMode), [initialMode, node.id]);
  const setModePersisted = key => {
    setMode(key);
    watchPersistParam(node, 'as', key);
  };
  const safePreview = preview && typeof preview === 'object' ? preview : {kind:mode, state:'empty', value:null, shape:{}};
  const state = watchState(safePreview, mode);
  return <div data-watch-preview="" style={{display:'grid', gap:6, marginTop:6}}>
    {inspector && <div data-watch-show-as="" style={{display:'flex', gap:4, flexWrap:'wrap'}}>
      {WATCH_MODES.map(([key, label]) => <window.AH_DS.Btn key={key} type="button" onClick={() => setModePersisted(key)} style={{
        border:`1px solid ${key === mode ? LM.accent : LM.lineSoft}`, background:key === mode ? LM.accent + '22' : 'transparent',
        color:key === mode ? LM.ink : LM.inkSoft, borderRadius:4, padding:'2px 6px', fontFamily:LM.mono, fontSize:WATCH_FS_LABEL.sz, cursor:'pointer'
      }}>{label}</window.AH_DS.Btn>)}
    </div>}
    <WatchWell node={node} preview={safePreview} mode={mode} state={state} inspector={inspector} actions={actions}/>
  </div>;
};

const WatchWell = ({ node, preview, mode, state, inspector, actions }) => {
  const size = watchSizeValue(node);
  const [w, h] = size.split('x').map(Number);
  const onMouseUp = event => {
    if (!inspector || !event.currentTarget?.style) return;
    const nextW = parseInt(event.currentTarget.style.width, 10);
    const nextH = parseInt(event.currentTarget.style.height, 10);
    if (Number.isFinite(nextW) && Number.isFinite(nextH)) watchPersistParam(node, 'watchSize', `${nextW}x${nextH}`);
  };
  return <div data-watch-well="" data-watch-size={size} onMouseUp={onMouseUp} style={{
    minWidth:inspector ? 220 : 0, maxWidth:inspector ? undefined : '100%', maxHeight:480,
    width:inspector ? w : '100%', height:h, overflow:'auto', resize:inspector ? 'both' : 'none',
    border:`1px solid ${LM.lineSoft}`, background:LM.bgDeep || LM.bg, color:LM.ink,
    borderRadius:5, display:'grid', gridTemplateRows:'1fr auto'
  }}>
    <div style={{overflow:'auto'}}>
      {state === 'ready' ? <WatchRender node={node} preview={preview} mode={mode} inspector={inspector}/> : <WatchState state={state} preview={preview} actions={actions}/>}
    </div>
    <WatchFoot node={node} preview={preview} mode={mode} state={state} actions={actions}/>
  </div>;
};

const WatchState = ({ state, preview, actions = {} }) => {
  const label = state === 'empty' ? 'Add input' : state === 'error' ? 'Retry' : state === 'too-big' ? 'Show all' : null;
  const handler = state === 'empty' ? actions.addInput : state === 'error' ? actions.retry : state === 'too-big' ? actions.showAll : null;
  return <div data-watch-state={state} style={{padding:10, display:'grid', gap:7, placeItems:'center', minHeight:70, fontFamily:LM.mono, fontSize:WATCH_FS_DATA.sz, color:LM.inkSoft}}>
    <span>{preview?.error || (state === 'loading' ? 'loading' : state)}</span>
    {label && handler ? <window.AH_DS.Btn data-watch-state-action="" type="button" onClick={handler} style={window.AH_DS.styles.button("secondary", true)}>{label}</window.AH_DS.Btn> : null}
  </div>;
};

const WatchRender = ({ node, preview, mode, inspector }) => {
  const value = preview?.value;
  if (mode === 'table') return <WatchTable rows={watchRows(value)} inspector={inspector}/>;
  if (mode === 'list') return <WatchList rows={watchRows(value)}/>;
  if (mode === 'json') return <pre data-watch-json="" style={{margin:0, padding:8, fontFamily:LM.mono, fontSize:WATCH_FS_DATA.sz, color:LM.ink, whiteSpace:'pre-wrap'}}>{typeof value === 'string' ? value : JSON.stringify(value, null, 2)}</pre>;
  if (mode === 'image') return <WatchImage value={value}/>;
  if (mode === 'number') return <WatchNumber value={value} preview={preview}/>;
  if (mode === 'chart') return <WatchChart values={watchRows(value)}/>;
  if (mode === 'geometry') return <WatchGeometry node={node} mesh={value} inspector={inspector}/>;
  return null;
};

const watchFootStateAction = (node, preview, state, actions = {}) => {
  if (node.state === 'out-of-date' && actions.runToHere) return ['Run', actions.runToHere];
  if (node.state === 'refused' && actions.retry) return ['Retry', actions.retry];
  if (node.state === 'off' && actions.turnOn) return ['Turn on', actions.turnOn];
  if (state === 'ready' && actions.runToHere) return ['Run to here', actions.runToHere];
  return null;
};

const WatchFoot = ({ node, preview, mode, state, actions = {} }) => {
  const stateAction = watchFootStateAction(node, preview, state, actions);
  const ready = state === 'ready';
  const actionList = [];
  if (stateAction) actionList.push(stateAction);
  if (ready && actions.showInRevit) actionList.push(['Show in Revit', actions.showInRevit]);
  if (ready && (mode === 'table' || preview?.kind === 'table')) actionList.push(['Export CSV', () => watchExportCsv(node, preview)]);
  return <div data-watch-actions="" style={{display:'flex', flexWrap:'wrap', alignItems:'center', justifyContent:'space-between', gap:6, padding:'5px 6px', borderTop:`1px solid ${LM.lineSoft}`}}>
    <span data-watch-caption="" style={{fontFamily:LM.sans, fontSize:13, color:LM.inkMuted}}>{watchFootText(preview, mode, state)}</span>
    <span style={{display:'flex', gap:4, flexWrap:'wrap', justifyContent:'flex-end'}}>
      {actionList.map(([label, handler]) => <window.AH_DS.Btn key={label} type="button" onClick={handler} style={window.AH_DS.styles.button("secondary", true)}>{label}</window.AH_DS.Btn>)}
    </span>
  </div>;
};

const watchFootText = (preview, mode, state) => {
  if (state !== 'ready') return state === 'empty' ? 'needs input' : state;
  const value = preview?.value;
  const shape = preview?.shape || {};
  if (mode === 'table') return `${shape.rows ?? watchRows(value).length} rows`;
  if (mode === 'list') return `${shape.items ?? watchRows(value).length} items`;
  if (mode === 'json') return typeof value === 'object' && value !== null ? '1 object' : '1 value';
  if (mode === 'image') return shape.file || shape.size || '';
  if (mode === 'geometry') return `${shape.vertices ?? 0} vertices`;
  return '';
};

const WatchTable = ({ rows, inspector = false }) => {
  const matrixRows = rows.length > 1 && rows.every(Array.isArray);
  const sourceRows = matrixRows ? rows.slice(1) : rows;
  const visible = sourceRows.slice(0, inspector ? WATCH_TABLE_ROWS_INSPECTOR : WATCH_TABLE_ROWS);
  const objectRows = !matrixRows && visible.every(row => row && typeof row === 'object' && !Array.isArray(row));
  const columns = matrixRows ? rows[0].slice(0, WATCH_TABLE_COLS).map(watchCellText)
    : objectRows ? Array.from(visible.reduce((set, row) => { Object.keys(row).forEach(k => set.add(k)); return set; }, new Set())).slice(0, WATCH_TABLE_COLS)
    : ['value'];
  const more = Math.max(0, sourceRows.length - visible.length);
  return <div data-watch-table="" style={{padding:7}}>
    <table style={{width:'100%', borderCollapse:'collapse', fontFamily:LM.mono, fontSize:WATCH_FS_DATA.sz, color:LM.ink}}>
      <thead style={{fontFamily:LM.sans,fontSize:12.5}}><tr>{columns.map(col => <th key={col} style={{textAlign:'left', color:LM.inkSoft, borderBottom:`1px solid ${LM.lineSoft}`, padding:'2px 4px'}}>{col}</th>)}</tr></thead>
      <tbody>{visible.map((row, idx) => <tr key={idx}>{columns.map((col, cidx) => <td key={col} style={{borderBottom:`1px solid ${LM.lineSoft}`, padding:'2px 4px'}}>{watchCellText(matrixRows ? row[cidx] : col === 'value' && !objectRows ? row : row?.[col])}</td>)}</tr>)}</tbody>
    </table>
    {more > 0 ? <div style={{fontFamily:LM.sans, fontSize:13, color:LM.inkMuted, paddingTop:4}}>+{more} more rows</div> : null}
  </div>;
};

const WatchList = ({ rows }) => <div data-watch-list="" style={{padding:7, display:'grid', gap:3}}>
  {rows.map((row, idx) => <div key={idx} style={{fontFamily:LM.mono, fontSize:WATCH_FS_DATA.sz, color:LM.ink}}>{watchCellText(row)}</div>)}
</div>;

const WatchImage = ({ value }) => WATCH_IMAGE_DATA.test(String(value || ''))
  ? <img data-watch-image="" src={value} alt="" style={{maxWidth:'100%', maxHeight:'100%', display:'block'}}/>
  : <WatchState state="empty" preview={{}}/>;

const WatchNumber = ({ value, preview }) => <div data-watch-number="" style={{padding:12, display:'grid', gap:5}}>
  <div style={{fontFamily:LM.mono, fontSize:(LM.fs?.title?.sz || 28), lineHeight:'34px', color:LM.ink}}>{Number(value).toLocaleString()}</div>
  <div style={{fontSize:(LM.fs?.caption?.sz || 12), color:LM.inkSoft}}>{preview?.shape?.caption || ''}</div>
</div>;

const WatchChart = ({ values }) => {
  const nums = values.map(row => typeof row === 'number' ? row : Number(row?.value ?? row?.y)).filter(Number.isFinite);
  const max = Math.max(1, ...nums.map(Math.abs));
  return <div data-watch-chart="" style={{padding:8, display:'flex', alignItems:'end', gap:3, height:90}}>
    {nums.slice(0, 24).map((value, idx) => <span key={idx} title={String(value)} style={{width:8, height:Math.max(2, Math.round(Math.abs(value) / max * 76)), background:LM.accent, display:'block'}}/>)}
  </div>;
};

const watchVector = value => Array.isArray(value) ? value : [value?.x, value?.y, value?.z];
const normalizeWatchVertices = vertices => (Array.isArray(vertices) ? vertices : [])
  .map(watchVector)
  .filter(row => row.length >= 3 && row.slice(0, 3).every(Number.isFinite))
  .map(row => row.slice(0, 3));

const triangulateWatchFace = (face, countPrefixed = false) => {
  const held = Array.isArray(face) ? face : [];
  const ids = countPrefixed && held.length && held.length === Number(held[0]) + 1 ? held.slice(1) : held;
  if (ids.length < 3 || !ids.every(Number.isInteger)) return [];
  const out = [];
  for (let i = 1; i < ids.length - 1; i += 1) out.push([ids[0], ids[i], ids[i + 1]]);
  return out;
};

const triangulateWatchFaces = faces => {
  if (!Array.isArray(faces)) return [];
  if (faces.every(Number.isInteger)) {
    const out = [];
    for (let i = 0; i < faces.length;) {
      const n = faces[i++];
      const face = faces.slice(i, i + n); i += n;
      out.push(...triangulateWatchFace([n, ...face], true));
    }
    return out;
  }
  return faces.flatMap(face => triangulateWatchFace(face, false));
};

const decodeWatchGeometryMesh = mesh => {
  const vertices = normalizeWatchVertices(mesh?.vertices || mesh?.points || []);
  const faces = triangulateWatchFaces(mesh?.faces || mesh?.triangles || [])
    .filter(face => face.every(i => i >= 0 && i < vertices.length));
  return {vertices, faces, shape:{vertices:vertices.length, faces:faces.length}};
};

const watchCameraAfterDrag = (camera, drag, x, y) => ({
  ...camera,
  yaw:camera.yaw + (x - drag.x) * 0.01,
  pitch:Math.max(-1.4, Math.min(1.4, camera.pitch + (y - drag.y) * 0.01)),
});

const watchCameraAfterWheel = (camera, deltaY) => ({
  ...camera,
  zoom:Math.max(0.2, Math.min(5, camera.zoom * (deltaY < 0 ? 1.12 : 0.88))),
});

const WatchGeometry = ({ node, mesh, inspector }) => {
  const ref = React.useRef(null);
  const dragRef = React.useRef(null);
  const [camera, setCamera] = React.useState({yaw:0.7, pitch:-0.55, zoom:1, panX:0, panY:0});
  const decoded = React.useMemo(() => decodeWatchGeometryMesh(mesh), [mesh]);
  React.useEffect(() => {
    if (typeof window !== 'undefined') {
      window.ARCHHUB_LAST_WATCH_MESH = window.ARCHHUB_LAST_WATCH_MESH || {};
      window.ARCHHUB_LAST_WATCH_MESH[node.id] = decoded;
    }
  }, [node.id, decoded]);
  const onPointerDown = event => { dragRef.current = {x:event.clientX, y:event.clientY}; };
  const onPointerMove = event => {
    if (!dragRef.current) return;
    setCamera(prev => watchCameraAfterDrag(prev, dragRef.current, event.clientX, event.clientY));
    dragRef.current = {x:event.clientX, y:event.clientY};
  };
  const endDrag = () => { dragRef.current = null; };
  const onWheel = event => {
    event.preventDefault?.();
    setCamera(prev => watchCameraAfterWheel(prev, event.deltaY));
  };
  return <canvas ref={ref} data-watch-geometry="" data-vertices={decoded.shape.vertices}
    data-faces={decoded.shape.faces} data-camera={`${camera.yaw.toFixed(3)},${camera.pitch.toFixed(3)}`}
    data-zoom={camera.zoom.toFixed(3)} width={inspector ? 460 : 260} height={inspector ? 260 : 140}
    onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={endDrag} onPointerLeave={endDrag} onWheel={onWheel}
    style={{display:'block', width:'100%', height:'100%', background:LM.bgDeep || LM.bg}}/>;
};

if (typeof window !== 'undefined') {
  window.WatchPreview = WatchPreview;
  window.ARCHHUB_WATCH_GEOMETRY = {decodeWatchGeometryMesh, watchCameraAfterDrag, watchCameraAfterWheel};
}

const isWorkshopGraphNode = n => {
  if (!n || typeof n.id !== 'string' || !n.id) return false;
  const authority = window.ARCHHUB_STUDIO_AUTHORITY || window.ARCHHUB_EXISTING_WORKSHOP;
  const descriptors = authority?.getSnapshot?.()?.workshops;
  return (Array.isArray(descriptors) && descriptors.some(row => row?.root === n.id || row?.node_root === n.id)) ||
    n.cat === 'workshop' || n.kind === 'workshop';
};
const GraphWorkshopFace = ({ n, nodeRef, rootProps={}, onDragStart, bandRef, onSocket, onSocketDrag, startMemberDrag, memberDragTrace = {} }) => {
  const state = useWorkshopProjection();
  const root = n.conversation_root || n.workshop_root || n.id;
  const descriptor = (state?.workshops || []).find(row => row.root === root || row.node_root === n.id) ||
    (root ? {root, label:n.title || 'Workshop'} : null);
  const model = window.ARCHHUB_WORKSHOP_MODEL?.({state:state || {}, descriptor:descriptor || {}});
  const members = model?.task_agents?.length ? model.task_agents : model?.members || [];
  const approval = model?.approval;
  // One review owns the accent in this canvas; all other Review routes stay available.
  const reviewNodes = (state?.topology?.graph?.nodes || [n]).filter(isWorkshopGraphNode);
  const accentReview = reviewNodes.find(node => window.ARCHHUB_WORKSHOP_MODEL?.({state:state || {},
    descriptor:{root:node.conversation_root || node.workshop_root || node.id}})?.approval)?.id;
  const reviewPrimary = !accentReview || accentReview === n.id;
  const authority = window.ARCHHUB_STUDIO_AUTHORITY || window.ARCHHUB_EXISTING_WORKSHOP;
  const canMoveMember = typeof authority?.moveMember === 'function';
  const color = approval ? LM.warn : /done|complete|submitted/i.test(model?.status?.text || '') ? LM.ok : LM.inkSoft;
  const outputCount = Number.isSafeInteger(model?.count) && model.count >= 0 ?
    ` · ${model.count}${model.output_label ? ' ' + model.output_label : ''}` : '';
  const openWindow = (event, review = false) => {
    event?.stopPropagation();
    if (!descriptor?.root) return;
    window.dispatchEvent(new window.CustomEvent('archhub:reach-conversation', {
      detail:review ? {root:descriptor.root, work:approval?.work || approval?.id} : descriptor.root}));
  };
  return <window.AH_DS.Node nodeRef={nodeRef} data-ds-card="" data-workshop-node-face="" data-workshop-id={descriptor?.root || ''}
    data-canvas-card-skin="061" data-workshop-node-state={model?.needs_user?'needs-user':model?.status?.text}
    data-workshop-approval={approval?.work || approval?.id || undefined} onDoubleClick={openWindow}
    glyph="◎" gc={LM.purple} title="Workshop" subtitleProps={{'data-workshop-node-title':''}} sub={n.subtitle || model?.title || 'Unavailable'} w={n.w || 260}
    onHeaderMouseDown={onDragStart} bandRef={bandRef} ins={n.ins || []} outs={n.outs || []}
    renderPort={(port,index,side)=><Socket id={port.id} side={side} i={index} t={port.t} label={port.label} list={!!port.list || !!port.multiple}
      half={(n.w || 260)/2} connected={!!port.connected} onUse={port.connectable && onSocket?()=>onSocket(port,side):undefined}
      onDragStart={port.connectable && onSocketDrag?event=>onSocketDrag(event,port,side):undefined}/>}
    chip={<span data-workshop-node-agent-stack="" style={{display:'flex',flexWrap:'wrap',gap:6,paddingTop:4}}>{members.map(member => {
        const participant = member.row?.root || member.root || member.id;
        const id = member.graph_member_id || participant;
        const canDrag = !!startMemberDrag && canMoveMember && !!member.graph_member_id && member.graph_group_id === n.id;
        const name = member.name || member.label || member.row?.label || 'Unavailable';
        return <span key={id} data-workshop-node-member={id} data-member-drag={memberDragTrace[id] || undefined}
          data-workshop-participant-root={participant} data-workshop-member-draggable={canDrag ? 'true' : 'false'}
          title={canDrag ? name : name + ' · Unavailable'} aria-label={name} aria-disabled={!canDrag} draggable={false} onDragStart={event => event.preventDefault()}
          onPointerDown={canDrag ? event => startMemberDrag({...member, id}, event) : undefined}
          onMouseDown={event => {event.stopPropagation(); if (canDrag) startMemberDrag({...member, id}, event);}}
          data-agent-presence={member.presence || member.liveState || 'unavailable'}
          style={{display:'inline-flex',alignItems:'center',gap:5,padding:'3px 5px',borderRadius:4,background:LM.bgSoft,color:LM.ink,fontSize:12,cursor:canDrag?'grab':'default'}}>
          <window.AH_DS.Avatar data-agent-initial="" agent={{name,ini:member.ini || name.slice(0,1).toUpperCase(),col:member.col || member.c || member.color || LM.purple}} size={16}/>{name}</span>;
      })}</span>} footc={color} foot={<span style={{display:'flex',alignItems:'center',gap:8}}>      <span data-workshop-node-status="" style={{fontSize:13, fontWeight:400, color, flex:1}}>{approval && Number.isSafeInteger(model?.count) ? `Waits for you · ${model.count}${model.output_label ? ' ' + model.output_label : ''}` : <>{model?.status?.text || 'Unavailable'}{outputCount}</>}</span>
      {approval && <window.AH_DS.Btn type="button" data-workshop-node-review="" onMouseDown={event => event.stopPropagation()}
        onClick={event => openWindow(event, true)} disabled={!descriptor?.root || !(approval.work || approval.id)}
        style={{border:reviewPrimary?0:`1px solid ${LM.line}`, borderRadius:5, background:reviewPrimary?LM.accent:LM.bgHover, color:reviewPrimary?LM.onFill:LM.ink,boxShadow:'none',
          height:26, display:'inline-flex', alignItems:'center', fontFamily:LM.sans, fontSize:13, fontWeight:500, padding:'0 10px', cursor:'pointer'}}>Review</window.AH_DS.Btn>}</span>} {...rootProps} style={{borderColor:approval?LM.warn:LM.line,lineHeight:'normal',...rootProps.style}}/>;
};
// Host locations and crop coordinates are projected data; never invent plan rooms or marks.
const nodePlanPreviewFor = node => {
  const preview = watchPreviewFor(node);
  const value = preview?.value;
  const read = node.cat === 'read' || /\bread\b/i.test(node.subtitle || node.sub || node.engine || '');
  if(!read)return null;
  const elements = [preview?.elements,value?.elements,value,node.result].find(Array.isArray);
  const count = elements?.length ?? preview?.shape?.items ?? preview?.element_count ?? node.element_count;
  if (!Number.isSafeInteger(count) || count < 0) return null;
  const marks = (Array.isArray(elements) ? elements : []).flatMap((element,index)=>{
    const point = element?.location?.point || element?.location;
    const x = Array.isArray(point) ? point[0] : point?.x ?? point?.X;
    const y = Array.isArray(point) ? point[1] : point?.y ?? point?.Y;
    return Number.isFinite(x) && Number.isFinite(y) ? [{id:element?.id ?? index,x,y}] : [];
  });
  const crop = preview?.plan_crop || node.plan_crop;
  const url = typeof crop === 'string' ? crop : crop?.url || crop?.data_url || (preview?.kind==='image' ? value : null);
  const cropSafe = typeof url === 'string' && /^(?:data:image\/(?:png|jpeg|webp);base64,|blob:|\/api\/)/.test(url);
  const label = node.output_label || node.outs?.find(port=>port.list || port.multiple)?.label || 'elements';
  return {marks,count,label,url:cropSafe ? url : null,width:crop?.width || preview?.shape?.width || 220,height:crop?.height || preview?.shape?.height || 100};
};
const NodePlanPreview = ({ node }) => {
  const plan=nodePlanPreviewFor(node);
  if(!plan)return null;
  if(!plan.marks.length)return <div data-node-plan-count="" style={{minHeight:96,display:'grid',placeItems:'center',
    fontFamily:LM.sans,fontSize:22,fontWeight:700,color:LM.ink}}>{plan.count} {plan.label}</div>;
  const xs=plan.marks.map(mark=>mark.x),ys=plan.marks.map(mark=>mark.y);
  const spanX=Math.max(...xs)-Math.min(...xs),spanY=Math.max(...ys)-Math.min(...ys);
  const padding=Math.max(spanX,spanY,1)*.08;
  const box=plan.url ? [0,0,plan.width,plan.height] : [Math.min(...xs)-padding,Math.min(...ys)-padding,spanX+2*padding,spanY+2*padding];
  const radius=plan.url ? 3 : padding*.35;
  return <svg data-node-plan-preview="" viewBox={box.join(' ')} role="img" aria-label={`${plan.count} ${plan.label} on plan`}
    style={{display:'block',width:'100%',height:96,borderRadius:8,background:LM.bgDeep || LM.bg}}>
    {plan.url&&<image href={plan.url} width={plan.width} height={plan.height}/>}
    {plan.marks.map(mark=><circle key={mark.id} data-node-plan-mark={mark.id} cx={mark.x} cy={mark.y} r={radius} fill={LM.accent}/>)}</svg>;
};

const NodeBody = ({ n, expanded, onToggleExpand, watchActions }) => {
  if (n.application) return <window.ApplicationNodeParameters node={n} compact/>;
  if (isWorkshopGraphNode(n)) return <GraphWorkshopFace n={n}/>;
  if (isHistoryNode(n)) return <HistoryBody n={n}/>;
  // A GRAPH-BACKED node draws exactly its real parameters, its last run
  // answer, and what actually flowed. Never a category's demo furniture.
  if (n.live || nodeIsWatch(n)) return <LiveBody n={n} watchActions={watchActions}/>;
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

const LiveBody = ({ n, watchActions }) => (
  <div style={{ marginTop:0, display:'flex', flexDirection:'column', gap:LM.sp.xs }}>
    {visibleNodeParams(n).slice(0, 3).map(row => (
      <div key={row.k} data-node-inline-param={row.k} style={{ display:'flex', justifyContent:'space-between', gap:6, fontFamily:LM.sans, fontSize:12.5, padding:'3px 0' }}>
        <span data-node-param-label="" style={{ color:LM.inkSoft, minWidth:0 }}>{typeof window.humanParamLabel === 'function' ? window.humanParamLabel(row) : String(row.label || row.k).replace(/([a-z])([A-Z])/g,'$1 $2').replaceAll('_',' ').replace(/^./,ch=>ch.toUpperCase())}</span>
        <span data-node-param-value="" title={String(row.v)} style={{ background:LM.bgHover, borderRadius:5, padding:'1px 8px', color:LM.ink, maxWidth:'65%', minWidth:0, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{String(row.v)}</span>
      </div>
    ))}
    {n.result && !nodePlanPreviewFor(n) ? (
      <div style={{ display:'flex', gap:6, fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, marginTop:2 }}>
        <span style={{ color:LM.inkSoft, letterSpacing:'0.04em' }}>result</span>
        <div style={{ flex:1, borderBottom:`1px dashed ${LM.lineSoft}`, marginBottom:2 }}/>
        <span title={n.result} style={{ color:LM.ink, maxWidth:150, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{n.result}</span>
      </div>
    ) : null}
    {n.mutates ? (
      <div style={{ display:'flex', alignItems:'center', gap:6, marginTop:4, fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.warn || LM.accent }}>
        <span aria-hidden="true">⚠</span><span>mutates model · requires approval</span>
      </div>
    ) : null}
    {nodeIsWatch(n) ? <WatchPreview node={n} actions={watchActions}/> : null}
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
      <div key={o.id} style={{ display:'flex', gap:6, fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz }}>
        <span style={{ color:LM.inkSoft, letterSpacing:'0.04em' }}>{o.label}</span>
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
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke={LM.inkSoft} strokeWidth="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
          <input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="Search this conversation…" style={{
            flex:1, border:0, background:'transparent', color:LM.ink, fontSize:12, outline:'none', fontFamily:LM.sans,
          }}/>
          <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft }}>{filtered.length}/{total}</span>
          {q && (
            <window.AH_DS.Btn onClick={() => setQ('')} title="Clear conversation search" aria-label="Clear conversation search" style={{
              width:14, height:14, padding:0, border:0, background:'transparent',
              color:LM.inkSoft, cursor:'pointer', fontSize:11, lineHeight:1,
            }}>×</window.AH_DS.Btn>
          )}
        </div>

        {/* Scrollable full transcript */}
        <div className="ah-scroll" style={{
          maxHeight:260, overflow:'auto',
          background:LM.bgDeep, border:`1px solid ${LM.lineSoft}`, borderRadius:LM.rad.sm,
          padding:'9px 11px', display:'flex', flexDirection:'column', gap:10,
        }}>
          {filtered.length === 0 && (
            <div style={{ padding:'12px 4px', fontSize:11, color:LM.inkSoft, textAlign:'center' }}>No matches for “{q}”.</div>
          )}
          {filtered.map((m, i) => (
            <div key={i} style={{ display:'flex', gap:7 }}>
              <div style={{
                width:18, height:18, borderRadius: m.me ? '50%' : 4, flexShrink:0,
                background: m.me ? LM.userAv : LM.accent,
                color: m.me ? LM.onUserAv : ((window.AH && window.AH.onFill) || '#180f08'),
                display:'grid', placeItems:'center', fontSize:LM.fs.label.sz, fontWeight:700,
              }}>{m.who}</div>
              <div style={{ flex:1, minWidth:0 }}>
                <div style={{ display:'flex', alignItems:'baseline', gap:7, marginBottom:1 }}>
                  <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.04em' }}>{m.time || ''}</span>
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
        <window.AH_DS.Btn onClick={(e) => { e.stopPropagation(); onToggleExpand && onToggleExpand(); }} style={{
          fontFamily:LM.mono, fontSize:11, color:LM.inkSoft, letterSpacing:'0.08em',
          padding:'4px 9px', background:LM.bgDeep, border:`1px solid ${LM.lineSoft}`, borderRadius:4,
          display:'flex', alignItems:'center', gap:6, cursor:'pointer', textAlign:'left',
        }}
        onMouseEnter={e => e.currentTarget.style.borderColor = LM.accent+'66'}
        onMouseLeave={e => e.currentTarget.style.borderColor = LM.lineSoft}>
          <span style={{ color:LM.accent }}>↑</span>
          <span>{total - 2} earlier messages</span>
          <span style={window.AH_DS.styles.fill}/>
          <span style={{ color:LM.accent }}>expand + search ⤢</span>
        </window.AH_DS.Btn>
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
              display:'grid', placeItems:'center', fontSize:LM.fs.label.sz, fontWeight:700, flexShrink:0,
            }}>{m.who}</div>
            <div style={{ flex:1, minWidth:0 }}>
              <div style={{ fontSize:12, color: m.me ? LM.ink : LM.inkSoft, lineHeight:1.45 }}>
                {m.text}
                {isAssistant && isLast && (
                  <span style={{ display:'inline-block', width:6, height:11, background:LM.accent, marginLeft:2, verticalAlign:'-1px', animation:'lmCaret 1s infinite' }}/>
                )}
              </div>
              {isAssistant && isLast && (
                <window.AH_DS.Btn onClick={(e) => { e.stopPropagation(); setShowReasoning(s => !s); }} style={{
                  background:'transparent', border:0, padding:'3px 0', color:LM.inkSoft,
                  fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, letterSpacing:'0.06em', cursor:'pointer',
                  display:'flex', alignItems:'center', gap:LM.sp.xs, marginTop:3,
                }}>
                  <span>{showReasoning ? '▾' : '▸'}</span> reasoning · 4 steps
                </window.AH_DS.Btn>
              )}
              {isAssistant && isLast && showReasoning && (
                <div style={{
                  marginTop:3, padding:'5px 8px', background:LM.bgDeep,
                  border:`1px solid ${LM.lineSoft}`, borderLeft:`2px solid ${LM.purple}`, borderRadius:LM.rad.xs,
                  fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, lineHeight:1.6,
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
  <div style={{ marginTop:7, fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, lineHeight:1.55 }}>
    <div style={{ display:'flex', alignItems:'center', gap:6 }}>
      <span style={{ color:LM.ok }}>✓</span>
      <span style={{ color:LM.ink, flex:1 }}>{n.result}</span>
        <span style={{ color:LM.inkSoft, fontSize:LM.fs.label.sz }}>{n.ms}</span>
    </div>
  </div>
);

const FilterBody = ({ n }) => (
  <div style={{ marginTop:7 }}>
    <div style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, marginBottom:LM.sp.xs }}>predicate</div>
    <div style={{ background:LM.bgDeep, border:`1px solid ${LM.lineSoft}`, borderRadius:4, padding:'5px 8px', fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.purple }}>
      {n.sub.replace(/^.*?·\s*/, '')}
    </div>
      <div style={{ display:'flex', alignItems:'center', gap:6, marginTop:6, fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz }}>
      <span style={{ color:LM.ok }}>→</span>
      <span style={{ color:LM.ink, flex:1 }}>{n.result}</span>
      <span style={{ color:LM.inkSoft, fontSize:11 }}>{n.ms}</span>
    </div>
  </div>
);

// Transform body — parameter assignment summary
const TransformBody = ({ n }) => (
  <div style={{ marginTop:LM.sp.sm, display:'flex', flexDirection:'column', gap:6 }}>
    {n.params?.map(p => (
      <div key={p.k} style={{ display:'flex', alignItems:'center', gap:6, fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz }}>
        <span style={{ color:LM.inkSoft, letterSpacing:'0.04em' }}>{p.k}</span>
        <div style={{ flex:1, borderBottom:`1px dashed ${LM.lineSoft}`, marginBottom:2 }}/>
        <span style={{ color:LM.ink, padding:'1px 6px', background:LM.bg, border:`1px solid ${LM.lineSoft}`, borderRadius:LM.rad.xs }}>{p.v}</span>
      </div>
    ))}
    <div style={{
      marginTop:2, fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.warn,
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
    <div style={{ fontFamily:LM.mono, fontSize:11, color:LM.inkSoft, marginBottom:LM.sp.xs }}>predicate</div>
    <div style={{ background:LM.bgDeep, border:`1px solid ${LM.lineSoft}`, borderRadius:4, padding:'5px 8px', fontFamily:LM.mono, fontSize:11, color:LM.purple }}>
      {n.sub.replace(/^.*?·\s*/, '')}
    </div>
    {n.result && (
      <div style={{ display:'flex', alignItems:'center', gap:6, marginTop:6, fontFamily:LM.mono, fontSize:11 }}>
        <span style={{ color:LM.purple }}>→</span>
        <span style={{ color:LM.ink, flex:1 }}>{n.result}</span>
        <span style={{ color:LM.inkSoft, fontSize:11 }}>{n.ms}</span>
      </div>
    )}
  </div>
);

// Compose body — little table preview
const ComposeBody = ({ n }) => (
  <div style={{ marginTop:LM.sp.sm }}>
    <div style={{
      background:LM.bgInk, border:`1px solid ${LM.lineSoft}`, borderRadius:LM.rad.sm, overflow:'hidden',
      fontFamily:LM.mono, fontSize:11,
    }}>
      {/* header */}
      <div style={{ display:'grid', gridTemplateColumns:'1.4fr 1fr 1fr', padding:'4px 8px', background:LM.bgDeep, color:LM.inkSoft, letterSpacing:'0.08em' }}>
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
      <div style={{ display:'flex', alignItems:'center', gap:6, marginTop:6, fontFamily:LM.mono, fontSize:11 }}>
        <span style={{ color:LM.ok }}>→</span>
        <span style={{ color:LM.ink, flex:1 }}>{n.result}</span>
        <span style={{ color:LM.inkSoft, fontSize:11 }}>{n.ms}</span>
      </div>
    )}
  </div>
);

const AnnotateBody = ({ n }) => (
  <div style={{ marginTop:9 }}>
    {n.runtime && (
      <>
        <div style={{ display:'flex', alignItems:'center', gap:6, marginBottom:6 }}>
          <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.accent, letterSpacing:'0.06em' }}>{n.runtime}</span>
          <div style={window.AH_DS.styles.fill}/>
          <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft }}>{Math.round(n.progress*100)}%</span>
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
        <div style={{ marginTop:10, fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.14em', marginBottom:5 }}>PREVIEW</div>
        <StagePreview/>
      </>
    )}
  </div>
);

const OutputBody = ({ n }) => (
  <div style={{ marginTop:LM.sp.sm, display:'flex', flexDirection:'column', gap:7 }}>
    {n.params?.slice(0, 2).map(p => (
      <div key={p.k} style={{ display:'flex', flexDirection:'column', gap:2 }}>
        <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.04em' }}>{p.k}</span>
        <div style={{ background:LM.bg, border:`1px solid ${LM.lineSoft}`, borderRadius:4, padding:'4px 8px', fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.ink }}>
          {p.v}
        </div>
      </div>
    ))}
    <div style={{ display:'flex', gap:6, marginTop:LM.sp.xs }}>
      <window.AH_DS.Btn onClick={async (e) => {
        const b = e.currentTarget;
        b.textContent = 'running…';
        try {
          const result = await window.ARCHHUB_RUN();
          b.textContent = String(
            result?.display?.[n.id] || result?.pending?.[n.id] || 'ran'
          ).slice(0, 30);
        } catch (error) { b.textContent = 'refused'; }
        setTimeout(() => { b.textContent = 'preview'; }, 6000);
      }} style={window.AH_DS.styles.button("secondary", true)}>preview</window.AH_DS.Btn>
      <window.AH_DS.Btn onClick={async (e) => {
        const b = e.currentTarget;
        b.textContent = 'saving…';
        try {
          await window.ARCHHUB_RUN();
          b.textContent = 'saved to the graph';
        } catch (error) { b.textContent = 'refused'; }
        setTimeout(() => { b.textContent = 'save'; }, 5000);
      }} style={window.AH_DS.styles.button(true ? 'primary' : 'secondary', true)}>save</window.AH_DS.Btn>
    </div>
  </div>
);

const CompactParam = ({ p }) => {
  if (p.type === 'slider') {
    const pct = ((p.v - p.min) / (p.max - p.min)) * 100;
    return (
      <div>
        <div style={{ display:'flex', alignItems:'baseline', gap:6 }}>
          <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, flex:1, letterSpacing:'0.04em' }}>{p.k}</span>
          <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.ink, fontWeight:500 }}>{p.v}</span>
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
      <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, flex:1, letterSpacing:'0.04em' }}>{p.k}</span>
      <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.ink, padding:'1px 6px', background:LM.bg, border:`1px solid ${LM.lineSoft}`, borderRadius:LM.rad.xs }}>
        {p.v} <span style={{ color:LM.inkSoft, marginLeft:2 }}>▾</span>
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
      <text x="60" y="86" textAnchor="middle" fontFamily="JetBrains Mono" fontSize={LM.fs.dataSm.sz} fill={LM.accent}>9 600</text>
      <text x="140" y="86" textAnchor="middle" fontFamily="JetBrains Mono" fontSize={LM.fs.dataSm.sz} fill={LM.accent}>10 400</text>
    </svg>
    <div style={{
      position:'absolute', top:5, right:6, fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz,
      color:LM.accent, letterSpacing:'0.06em', background:LM.bgDeep+'cc', padding:'1px 5px', borderRadius:2,
    }}>17 / 23 placed</div>
  </div>
);

// ─── canvas toolbar (TOP-LEFT) ───
const CanvasToolbar = ({ host, compact = false, system = false, zoom, setZoom, onFit, fitLabel, onArrange, arrangeDisabled = false, arrangeWhy = 'Arrange', setLibraryOpen, undo, redo, onRun, runDisabled = true, title = '', project = '', status = '', waiting = 0 }) => {
  const history = [['Undo', '\u21b6', undo], ['Redo', '\u21b7', redo]].filter(([, , held]) => held).map(([label, icon, held]) => (
    <window.AH_DS.Btn key={label} disabled={held.disabled} onClick={(e) => { e.stopPropagation(); held.run(); }}
      title={label} aria-label={label} aria-description={held.disabled ? held.why : undefined}
      style={{...window.AH_DS.styles.button("ghost", true), cursor:held.disabled ? 'default' : 'pointer', color:LM.inkSoft}}>{icon}</window.AH_DS.Btn>
  ));
  const topbar = (
  <div data-canvas-topbar="" data-no-pan style={{position:host?'static':'absolute',left:0,right:0,top:0,height:compact?36:56,
    display:'flex',alignItems:'center',gap:compact?10:14,padding:compact?'0 12px':'0 24px',borderBottom:host?0:`1px solid ${LM.lineSoft}`,background:host?'transparent':'#0f0f13'}}>
    {!host && !system && <><span style={{fontSize:compact?12:17,fontWeight:compact?500:700}}>{title}</span></>}
    {!host&&!system&&status&&<span data-canvas-live-state="" style={{borderRadius:999,padding:'4px 9px',background:LM.accent+'1f',color:LM.accent,fontSize:12,fontWeight:600}}>{status}</span>}
    {!host&&!system&&waiting>0&&<span data-canvas-needs-user="" style={{borderRadius:999,padding:'4px 9px',background:LM.warn+'1f',color:LM.warn,fontSize:12,fontWeight:600}}>{waiting} needs you</span>}<span style={window.AH_DS.styles.fill}/>
    {/* History remains in the canvas menu and keyboard shortcuts. */}
    <window.AH_DS.Btn disabled={arrangeDisabled} onClick={event => {event.stopPropagation(); onArrange();}}
      title={arrangeDisabled ? arrangeWhy : 'Arrange'} aria-label="Arrange" style={{...window.AH_DS.styles.button(compact?"ghost":"secondary", true),height:compact?26:30,fontSize:13}}>Arrange</window.AH_DS.Btn>
    {!system && <window.AH_DS.Btn data-canvas-run-primary="" disabled={runDisabled} onClick={event => {event.stopPropagation(); onRun?.();}}
      style={compact?window.AH_DS.styles.button('primary',true):{height:30,padding:'0 12px',border:waiting>0?`1px solid ${LM.line}`:0,borderRadius:8,fontFamily:LM.sans,fontSize:13,fontWeight:600,color:waiting>0?LM.ink:'#fff',background:waiting>0?'#26262d':`linear-gradient(180deg, ${LM.accentHi || LM.accent}, ${LM.accent})`,boxShadow:waiting>0?'0 1px 0 rgba(255,255,255,.06) inset':`0 1px 0 rgba(255,255,255,.25) inset, 0 4px 14px ${LM.accent}44`,cursor:'pointer'}}>Run</window.AH_DS.Btn>}
  </div>
  );
  return <>{host?ReactDOM.createPortal(topbar,host):topbar}
  <div data-no-pan style={{
    position:'absolute', left:compact?16:40, bottom:system?16:compact?110:28, display:'flex', gap:LM.sp.xs,
    ...canvasCardSurface(), border:`1px solid ${LM.line}`, borderRadius:compact?6:10, padding:compact?3:LM.sp.xs,
  }}>
    <window.AH_DS.Btn onClick={(e) => { e.stopPropagation(); setZoom(z => Math.max(0.3, +(z - 0.1).toFixed(2))); }} title="Zoom out" aria-label="Zoom out" style={{...window.AH_DS.styles.button("ghost", true),width:'auto',padding:'0 6px',fontFamily:LM.sans,fontSize:13}}>{compact?'−':'Zoom out'}</window.AH_DS.Btn>
    <div data-canvas-zoom="" style={{ ...window.AH_DS.styles.button("ghost", true), width:48, color:LM.ink, background:LM.bg, fontFamily:LM.sans, fontSize:13, cursor:'default' }}>
      {Math.round(zoom * 100)}%
    </div>
    <window.AH_DS.Btn onClick={(e) => { e.stopPropagation(); setZoom(z => Math.min(2, +(z + 0.1).toFixed(2))); }} title="Zoom in" aria-label="Zoom in" style={{...window.AH_DS.styles.button("ghost", true),width:'auto',padding:'0 6px',fontFamily:LM.sans,fontSize:13}}>{compact?'+':'Zoom in'}</window.AH_DS.Btn>
    <window.AH_DS.Btn onClick={(e) => { e.stopPropagation(); onFit(); }} title={fitLabel} aria-label={fitLabel} style={{...window.AH_DS.styles.button("ghost", true),width:'auto',padding:'0 6px',fontFamily:LM.sans,fontSize:13}}>{compact?'⤢':'Fit'}</window.AH_DS.Btn>
    {!compact && <><div style={{ width:1, background:LM.line, margin:'0 2px' }}/>{history}
    <div style={{ width:1, background:LM.line, margin:'0 2px' }}/>
    <window.AH_DS.Btn onClick={(e) => { e.stopPropagation(); setLibraryOpen(true); }} title="Add node" aria-label="Add node" style={{
      padding:'0 10px', height:22, border:0, background:'transparent', cursor:'pointer',
      color:LM.accent, fontFamily:LM.sans, fontSize:12, fontWeight:600, letterSpacing:0,
      display:'flex', alignItems:'center', gap:LM.sp.xs,
    }}>{'\uff0b add node'}</window.AH_DS.Btn></>}
  </div></>;
};



// ─── floating composer (BOTTOM CENTER — always-bottom anchor) ───
// This box used to ignore the model picker and drop the answer on the floor:
// you typed, something happened somewhere, and nothing came back. It now asks
// the model selected in the header and prints the reply above the field.
const FloatingComposer = ({ setLibraryOpen, model, node }) => {
  const [answer, setAnswer] = React.useState('');
  // The drawn caret stands in for an idle field; once the field has focus its own caret is the only one.
  const [typing, setTyping] = React.useState(false);
  return (
    <window.AH_DS.Composer data-no-pan onFocus={() => setTyping(true)} onBlur={() => setTyping(false)} style={{
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
          before={<window.AH_DS.Btn onClick={(e) => { e.stopPropagation(); setLibraryOpen(true); }} style={{ ...window.AH_DS.styles.button("secondary", true), padding:'3px 9px' }}>library</window.AH_DS.Btn>}/>
      </div>
    </window.AH_DS.Composer>
  );
};

// ─── add-node box (BOTTOM CENTER) ───
// Founder 2026-10-12 (C1): the canvas keeps the design's bottom '/' box for adding nodes and opening
// the library ONLY. It has no model, sends nothing, and is not a chat: the one chat is the right panel.
const CanvasAddBox = ({ compact = false, setLibraryOpen }) => {
  const [q, setQ] = React.useState('');
  React.useEffect(()=>{const key=event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){
    event.preventDefault();setLibraryOpen(true);
  }};document.addEventListener('keydown',key);return()=>document.removeEventListener('keydown',key);},[setLibraryOpen]);
  const open = () => { setLibraryOpen(q.replace(/^\/+/, '').trim() || true); setQ(''); };
  return (
    <window.AH_DS.Composer data-no-pan data-canvas-add style={{
      position:'absolute', left:'50%', bottom:compact?16:24, transform:'translateX(-50%)',
      width:compact?440:520, maxWidth:'70%', height:compact?36:44, background:compact?LM.bgPanel:LM.surf2, border:`1px solid ${LM.line}`,
      borderRadius:compact?8:12, boxShadow:LM.elev.e2, padding:compact?'0 12px':'0 14px',
      display:'flex', alignItems:'center', gap:LM.sp.sm,
    }}>
      <span aria-hidden="true" style={{ color:LM.accent, fontFamily:LM.mono, fontSize:13 }}>/</span>
      <window.AH_DS.TextField aria-label="Add a node" value={q} placeholder={compact?'Add node':'Add a node, or ask the Workshop…'}
        onChange={e => setQ(e.target.value)}
        onKeyDown={e => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); open(); } else if (e.key === 'Escape') setQ(''); }}
        style={{ flex:1, minWidth:0, background:'transparent', border:0, outline:'none', color:LM.ink, fontFamily:LM.sans, fontSize:13 }}/>
      <window.AH_DS.Btn type="button" aria-label="Open node library" onClick={e => { e.stopPropagation(); setLibraryOpen(true); }} style={{fontFamily:LM.sans,fontSize:11,color:LM.inkSoft,border:`1px solid ${LM.line}`,borderRadius:4,padding:'1px 5px',background:'transparent',cursor:'pointer'}}>Ctrl K</window.AH_DS.Btn>
    </window.AH_DS.Composer>
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
    <div data-no-pan data-canvas-minimap="" style={{
      position:'absolute', right:28, bottom:24, width:180, height:110,
      ...canvasCardSurface(), border:`1px solid ${LM.line}`, borderRadius:10,
      overflow:'hidden',
    }}>
      <svg viewBox={minimapViewBox(boxes.map(({ n, p }) => ({ x: p.x, y: p.y, w: n.w, h: n.h })))} style={{ width:'100%', height:'100%' }}>
        {boxes.map(({ n, p }) => {
          const cat = studioCategory(n.cat);
          return (
            <rect key={n.id} data-minimap-node={n.id} x={p.x} y={p.y} width={n.w} height={n.h}
              fill={cat.col + '66'} stroke={LM.lineSoft} strokeWidth="2" rx="4"/>
          );
        })}
      </svg>
      <div style={{
        position:'absolute', left:6, top:5, fontFamily:LM.sans, fontSize:12,
        color:LM.inkSoft, letterSpacing:'0.14em', background:LM.bgDeep+'cc', padding:'1px 5px', borderRadius:2,
      }}>Overview</div>
    </div>
  );
};

// ──────────────────────── NODE LIBRARY ────────────────────────
const useLibraryRefreshEpoch = () => {
  const [epoch, setEpoch] = React.useState(0);
  React.useEffect(() => {
    const refresh = () => setEpoch(value => value + 1);
    window.addEventListener('archhub:library-refresh', refresh);
    return () => window.removeEventListener('archhub:library-refresh', refresh);
  }, []);
  return epoch;
};


const NodeLibrary = ({ onClose, addNodeFromLibrary, initialQuery = '', onSwitchPanel }) => {
  const live=React.useRef(true);
  React.useEffect(()=>{live.current=true;const escape=event=>{if(event.key==='Escape')onClose();};document.addEventListener('keydown',escape);return()=>{live.current=false;document.removeEventListener('keydown',escape);};},[]);
  return (
  <div data-node-library-overlay="" onClick={onClose} style={{position:'absolute',inset:0,background:'rgba(0,0,0,.55)',zIndex:60,display:'grid',placeItems:'center'}}>
    <window.AH_DS.Card role="dialog" aria-modal="true" aria-label="Node library" onClick={event=>event.stopPropagation()}
      style={{fontFamily:LM.sans,width:320,maxWidth:'94%',height:660,maxHeight:'88%',display:'grid',gridTemplateRows:'auto minmax(0,1fr)',boxShadow:LM.shadow.dialog}}>
      <window.AH_DS.Btn sm kind="ghost" aria-label="Close library" title="Close library (Escape)" onClick={onClose} style={{justifySelf:'end'}}>Close</window.AH_DS.Btn>
      <NodesPanel initialQuery={initialQuery} onSwitchPanel={onSwitchPanel} addNodeFromLibrary={async item=>{
        const result=await addNodeFromLibrary?.(item);
        if(result!==false && live.current)onClose();
        return result;
      }}/>
    </window.AH_DS.Card>
  </div>
);
};

// ──────────────────────── NODE RAIL ────────────────────────
const NodeModelConversation = ({node, scope = '', openConversation, active = true}) => {
  const [answer, setAnswer] = React.useState('');
  const [transcriptTick, setTranscriptTick] = React.useState(0);
  // Turns sent from the panel composer that the transcript has not read back yet (UX-CHAT1).
  // Identity: a turn is reconciled with the transcript by the server's message ids (delivery.message_id /
  // reply_message_id). Before those ids exist, its question may only match a row that is NEW since this
  // send (baseline = the row ids shown when it was sent), never a row from history (Ping P1).
  const [turns, setTurns] = React.useState([]);
  const rowsRef = React.useRef([]);
  React.useEffect(() => {
    const onTurn = event => {
      const d = event && event.detail;
      if (!d || d.target !== node.id) return;
      setTurns(held => {
        const prior = held.find(t => t.requestId === d.requestId);
        const turn = {requestId:d.requestId, said:d.said, model:d.model,
          baseline:prior && !(prior.queued && d.phase === 'pending') ? prior.baseline : new Set(rowsRef.current.map(row => row.id)),
          answer:d.phase === 'answer' || d.phase === 'failed' ? (d.answer || '') : null,
          failed:d.phase === 'failed',
          queued:d.phase === 'queued',
          steps:Array.isArray(d.steps) ? d.steps : (prior ? prior.steps || [] : []),
          messageId:d.messageId || '', replyId:d.replyId || ''};
        return prior ? held.map(t => t.requestId === d.requestId ? turn : t) : [...held, turn];
      });
      // Read the store on send (the question may already be saved) and on the answer.
      if (d.phase === 'pending' || d.phase === 'answer') setTranscriptTick(tick => tick + 1);
    };
    window.addEventListener(CHAT_TURN_EVENT, onTurn);
    return () => window.removeEventListener(CHAT_TURN_EVENT, onTurn);
  }, [node.id]);
  // The node's Workshop transcript, read only. null while the first read is in flight.
  const [transcript, setTranscript] = React.useState(null);
  const cat = studioCategory('ai');
  // Transcript shows for ANY conversation-bound node (a workflow's Workshop room has a
  // `conversation` and no `model`); the model route + composer are for model-bearing nodes only.
  const model = nodeModelRow(node);
  const route = model ? nodeModelRoute(node) : '';
  const bound = node.graphNode === true || (node.has_conversation === true && !!node.conversation_root);
  React.useEffect(() => {
    // Keep local turn identity while another inspector tab is open; hidden
    // conversations retain their listener without polling the transcript.
    if (!active) return;
    if (!bound || typeof window === 'undefined' || typeof window.ARCHHUB_WORKSHOP_TRANSCRIPT !== 'function') {
      setTranscript(null); return;
    }
    setTranscript(null);                     // clear the previous binding's rows before the new read lands
    const want = {node: node.id, conv: node.conversation_root, scope};
    let live = true, inFlight = false;
    const read = async () => {
      if (!live || inFlight) return;         // one read at a time: a poll never overlaps an earlier one
      inFlight = true;
      try {
        const result = await window.ARCHHUB_WORKSHOP_TRANSCRIPT(want.node, want.scope);
        if (!live) return;                   // the binding changed while this read was in flight: drop it
        if (!result || result.ok === false) {
          setTranscript({rows:[], error: result?.error || 'This conversation could not be read.', has_older:false}); return;
        }
        // Exact bound-root match: a response for another node, or one whose conversation_root is
        // null/missing/different while this node is bound, is refused — never rendered.
        if (result.node !== want.node || (want.conv && result.conversation_root !== want.conv)) {
          setTranscript({rows:[], error:'This conversation does not match the selected graph or node. Reopen its original scope.', has_older:false});
          return;
        }
        setTranscript({rows: Array.isArray(result.rows) ? result.rows : [], error:'', has_older: result.has_older === true});
      } catch (reason) { if (live) setTranscript({rows:[], error: reason?.message || String(reason), has_older:false}); }
      finally { inFlight = false; }
    };
    read();                                 // re-read whenever the rail opens or the bound node/scope changes
    const timer = setInterval(read, 8000);  // light poll \u2014 messages live in content, so the revision never moves
    return () => { live = false; clearInterval(timer); };
  }, [active, bound, node.id, node.conversation_root, scope, transcriptTick]);
  const rows = transcript ? transcript.rows : [];
  const hasOlder = !!(transcript && transcript.has_older);
  rowsRef.current = rows;
  const rowIds = new Set(rows.map(row => row.id));
  const claimed = new Set();
  const turnRows = [];
  for (const turn of turns) {
    // The store holds the whole turn (its reply id): the transcript draws it; the local copy steps aside.
    if (turn.replyId && rowIds.has(turn.replyId)) continue;
    // Is the question already in the transcript? By its id when known; otherwise only a new-since-send row.
    let questionShown = !!(turn.messageId && rowIds.has(turn.messageId));
    if (!questionShown && !turn.messageId && !turn.queued) {
      const fresh = rows.find(row => row.is_me && !turn.baseline.has(row.id) && !claimed.has(row.id)
        && String(row.text || '').trim() === turn.said);
      if (fresh) { claimed.add(fresh.id); questionShown = true; }
    }
    if (!questionShown) turnRows.push({id:turn.requestId + ':q', who:'You', is_me:true, text:turn.said, time:''});
    turnRows.push({id:turn.requestId + ':a', who:turn.model || 'model', is_me:false, kind:turn.failed ? 'error' : turn.answer === null ? 'waiting' : 'message',
      text:turn.answer === null ? (turn.queued ? 'Pending · queued for ' : 'Waiting for ') + (turn.model || 'the model') + '\u2026' : turn.answer, time:'',
      steps:turn.steps || [], queued:turn.queued});
  }
  // PM gate 2026-10-13: a new turn scrolls into view (the newest answer must be on screen),
  // unless the user has scrolled up to read history; then their place is kept.
  const scrollRef = React.useRef(null);
  const pinnedRef = React.useRef(true);
  const lastTurn = turnRows.length ? turnRows[turnRows.length - 1] : null;
  const tailKey = [rows.length, rows.length ? rows[rows.length - 1].id : '', turnRows.length,
    lastTurn ? lastTurn.kind + ':' + String(lastTurn.text || '').length : ''].join('|');
  React.useEffect(() => {
    const box = scrollRef.current;
    if (box && pinnedRef.current) box.scrollTop = box.scrollHeight;
  }, [tailKey, active]);
  const onTranscriptScroll = event => {
    const box = event.currentTarget;
    pinnedRef.current = box.scrollHeight - box.scrollTop - box.clientHeight < 24;
  };
  // The section leaves the DOM on other tabs; its turn listener remains held
  // so an admitted reply cannot disappear while the founder inspects properties.
  if (!active) return null;
  return <section aria-label={'Conversation with ' + node.title} style={{ display:'flex', flexDirection:'column', gap:10, borderTop:`1px solid ${LM.lineSoft}`, paddingTop:12 }}>
    <div style={{ display:'flex', alignItems:'center', gap:7 }}>
      <span style={{ color:cat.col }}>{cat.icon}</span>
      <span style={{ fontFamily:LM.sans, fontSize:11, fontWeight:600, color:LM.inkSoft, letterSpacing:0 }}>Conversation</span>
      <div style={window.AH_DS.styles.fill}/>
      {model ? (
        <p title={route || undefined} style={{ margin:0, maxWidth:170, fontFamily:LM.sans, fontSize:11, fontWeight:600, color:LM.inkSoft, letterSpacing:0, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
          {route || 'Choose a model for this node'}</p>
      ) : null}
    </div>
    {bound || turnRows.length > 0 ? (
      <div ref={scrollRef} onScroll={onTranscriptScroll} data-chat-scroll className="ah-scroll" style={{ maxHeight:260, overflow:'auto', display:'flex', flexDirection:'column', gap:11 }}>
        {transcript === null && !turnRows.length ? (
          <p style={{ margin:0, fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft }}>Reading the conversation…</p>
        ) : transcript && transcript.error ? (
          <p role="alert" style={{ margin:0, fontSize:12, color:LM.warn || LM.accent }}>{transcript.error}</p>
        ) : rows.length === 0 && !turnRows.length ? (
          <p role="status" style={{ margin:0, fontSize:12, lineHeight:1.5, color:LM.inkSoft }}>No conversation yet · ask below to start one.</p>
        ) : (<>
          {hasOlder ? (
            <p style={{ margin:0, fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.04em' }}>Latest messages only · full history in the Workshop</p>
          ) : null}
          {rows.map(row => <div key={row.id} data-chat-turn={row.is_me ? 'question' : 'answer'}><NodeTranscriptRow row={row}/></div>)}
          {turnRows.map(row => <div key={row.id} data-chat-local data-chat-pending={row.queued ? 'queued' : undefined} data-chat-turn={row.is_me ? 'question' : row.kind}><NodeTranscriptRow row={row}/></div>)}
        </>)}
      </div>
    ) : null}
    {bound && hasOlder ? (
      <div>
        <window.AH_DS.Btn onClick={() => { if (openConversation) openConversation(node.conversation_root); }} disabled={!openConversation}>
          Full history in the Workshop →</window.AH_DS.Btn>
      </div>
    ) : null}
    {answer && <p role="status" style={{ margin:0, whiteSpace:'pre-wrap', overflowWrap:'anywhere', fontFamily:LM.serif, fontSize:14, lineHeight:1.55, color:LM.ink, letterSpacing:'-0.003em' }}>{answer}</p>}
    {!bound && model ? <InlineAsk placeholder={'Ask ' + node.title + '...'} model={null} node={node} onAnswer={setAnswer} scale="node"/> : null}
  </section>;
};

const formatNodeConversationTime = iso => {
  try { const when = new Date(iso); return isNaN(when.getTime()) ? ''
    : when.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}); } catch (e) { return ''; }
};
// One transcript turn, read only. The sender label, an optional kind tag (reply/tool) and the body.
const NodeTranscriptRow = ({row}) => <div style={{display:'grid',gridTemplateColumns:'20px minmax(0,1fr)',gap:8,fontSize:13,lineHeight:'19px'}}>
  <window.AH_DS.Avatar agent={{name:row.who || 'Unavailable',col:row.is_me?LM.userAv:LM.accent}} size={20}/>
  <div><span style={{fontWeight:600}}>{row.who}</span> <time dateTime={row.time} style={{fontSize:11,color:LM.inkSoft}}>{formatNodeConversationTime(row.time)}</time>
    {row.kind && row.kind!=='message' && <span style={{fontSize:11,color:LM.inkSoft}}> · {row.kind}</span>}
    <div style={{fontFamily:LM.sans,fontSize:13,lineHeight:'19px',whiteSpace:'pre-wrap',overflowWrap:'anywhere',maxHeight:150,overflow:'auto'}}>{row.text}</div>
    {typeof BaboomToolSteps==='function'?<BaboomToolSteps steps={row.steps}/>:null}</div>
</div>;
const graphInspectorNode = (canvas, graph, session, sessionRows = []) => {
  const scope = canvas?.scope || {};
  const graphId = scope.current || canvas?.root || session?.id || 'current';
  const name = scope.current_label || session?.title || canvas?.graph_title || canvas?.title || 'ArchHub graph';
  const params = [{k:'name', v:name}];
  if (canvas?.authorization?.subject) params.push({k:'owner', v:canvas.authorization.subject});
  if (canvas?.description) params.push({k:'description', v:canvas.description});
  if (Array.isArray(sessionRows) && sessionRows.length) params.push({k:'sessions', v:sessionRows.length});
  if (Array.isArray(graph?.agents) && graph.agents.length) params.push({k:'agents', v:graph.agents.length});
  if (Array.isArray(graph?.programs) && graph.programs.length) params.push({k:'programs', v:graph.programs.length});
  if (session?.last) params.push({k:'last run', v:session.last});
  return {id:'graph:' + graphId, graph_id:graphId, cat:'graph',
    title:name, sub:'the graph as a node', live:true, params, ins:[], outs:[], messages:[],
    graphNode:true, has_conversation:true, conversation_root:''};
};
// A session node is a node of the session kind; an ordinary node that has chatted is still an ordinary node.
const isSessionInspectorNode = node => /^session$/i.test(String(node?.kind || node?.assembly || node?.cat || '')) ||
  /session/i.test(String(node?.sub || node?.engine || ''));
const hasRunsPanel = (node, graph, execution = null) => {
  if (!node || node.graphNode) return false;
  return !!(execution || node.last_run || node.run || node.status || (graph?.wires || []).some(wire =>
    wire.from?.[0] === node.id || wire.to?.[0] === node.id));
};
// One chat, two parts of one panel: the composer announces each turn; the target's Conversation section shows it.
const CHAT_TURN_EVENT = 'archhub:chat-turn';
const announceChatTurn = detail => {
  try { window.dispatchEvent(new window.CustomEvent(CHAT_TURN_EVENT, {detail})); } catch (_) {}
};
const applicationSettingsProjection = () => window.ARCHHUB_STUDIO_AUTHORITY?.getSnapshot?.() ||
  window.ARCHHUB_EXISTING_WORKSHOP?.getSnapshot?.()?.topology || {graph:LM_GRAPH};
const applicationSettingProposal = (said, target) => {
  if (target.kind !== 'graph' && !target.node?.application) return null;
  const command = /^@ArchHub\s+set\s+(.+?)\s+to\s+(.+)$/i.exec(said);
  if (!command) return null;
  const normal = text => String(text).replace(/[_-]/g,' ').replace(/\s+/g,' ').trim().toLowerCase();
  const key = normal(command[1]), raw = command[2].trim().replace(/^['"]|['"]$/g,'');
  const state = applicationSettingsProjection();
  const choices = (state.graph?.nodes || []).filter(node => node.application &&
    (target.kind === 'graph' || target.node.id === node.id)).flatMap(node => (node.params || [])
    .filter(row => row.editable === true && [row.k, row.label, node.title + ' ' + row.k, node.title + ' ' + row.label]
      .some(label => label && normal(label) === key)).map(row => ({node, row})));
  const distinct = [...new Map(choices.map(choice => [choice.row.cell_id || choice.row.value_root || choice.row.rel || choice.node.id + ':' + choice.row.k, choice])).values()];
  if (distinct.length !== 1) throw new Error(distinct.length ? 'Name the node as well as its setting.' : 'No editable setting with that name is visible in this graph.');
  const {node, row} = distinct[0], type = String(row.type || '').toLowerCase();
  const options = row.opts || row.options || row.constraints?.options;
  let value = raw;
  if (type === 'toggle' || type === 'boolean' || typeof row.v === 'boolean') {
    if (!/^(true|false|on|off|yes|no)$/i.test(raw)) throw new Error('Choose on or off.');
    value = /^(true|on|yes)$/i.test(raw);
  } else if (type === 'number' || type === 'integer') {
    value = Number(raw);
    if (!Number.isFinite(value) || (type === 'integer' && !Number.isInteger(value)) ||
        (row.min != null && value < row.min) || (row.max != null && value > row.max)) throw new Error('The value is outside this setting’s range.');
  } else if (type === 'color' || type === 'colour') {
    value = ({green:'#008000', red:'#ff0000', blue:'#0000ff', orange:'#ffa500', purple:'#800080', white:'#ffffff', black:'#000000'})[raw.toLowerCase()] || raw;
    if (!/^#[0-9a-f]{6}$/i.test(value)) throw new Error('Use a six-digit colour or a named colour.');
  } else if (Array.isArray(options) && options.length) {
    value = options.map(option => Array.isArray(option) ? option[0] : option).find(option => normal(option) === normal(raw));
    if (value === undefined) throw new Error('Choose one of this setting’s published options.');
  }
  return {id:window.crypto?.randomUUID?.() || String(Date.now()), node:node.id, key:row.k,
    cell:row.cell_id || row.value_root || row.rel, before:row.v, value, scope:studioCanvasScope(state.canvas),
    title:'Set ' + (row.label || row.k), target:node.title};
};
const ScopeComposer = ({ target, model, setPickerOpen, readiness = null, onReadinessStale, onModelReadRetry, onAccount, onSend }) => {
  const [text, setText] = React.useState('');
  const [state, setState] = React.useState('');
  const [stateModel, setStateModel] = React.useState('');
  const [asking, setAsking] = React.useState(false);
  const [settingProposal, setSettingProposal] = React.useState(null);
  const pendingSend = React.useRef(null);
  const draftRef = React.useRef('');
  const sendQueue = React.useRef([]);
  const sending = React.useRef(false);
  const pausedRequest = React.useRef(null);
  const [savedDrafts, setSavedDrafts] = React.useState([]);
  const nodeRoute = target?.node && nodeModelRow(target.node) ? nodeModelRoute(target.node) : '';
  const route = nodeRoute || modelRoute(model);
  const blocked = routeReadiness(route, readiness, model?.pending === true);
  const offers = new Set((blocked && blocked.actions) || []);
  const modelName = nodeRoute || modelDisplayName(model) || route || 'Choose a model';
  const placeholder = target.kind === 'session' ? 'reply in this session · @ agent' :
    target.kind === 'graph' ? 'whole graph · @ agent or session' : 'ask about this node · @ agent';
  const updateText = next => {
    if (pendingSend.current && next !== pendingSend.current.raw) pendingSend.current = null;
    draftRef.current = next;
    setText(next);
  };
  const nextRequestId = said => {
    const held = [pendingSend.current, pausedRequest.current].find(turn => turn &&
      turn.raw === draftRef.current && turn.said === said && turn.target === target.id);
    if (held && held.raw === draftRef.current && held.said === said && held.target === target.id) return held.requestId;
    return window.crypto?.randomUUID?.() || String(Date.now()) + '-' + String(Math.random()).slice(2);
  };
  const drainQueue = async () => {
    if (sending.current || pausedRequest.current) return;
    sending.current = true;
    setAsking(true);
    try {
      while (sendQueue.current.length) {
        const turn = sendQueue.current.shift();
        const announce = detail => announceChatTurn({target:turn.target, requestId:turn.requestId,
          said:turn.said, model:turn.model, ...detail});
        const admit = result => {
          const refusal = agentRefusalText(result);
          if (refusal) throw new Error(refusal);
          const deliveryState = agentDeliveryState(result);
          if (deliveryState && deliveryState !== 'replied') throw Object.assign(new Error(agentAnswerText(result) || 'reply not confirmed - check before sending again'), {unconfirmed:true});
          const delivery = (result && typeof result === 'object' && result.delivery) || {};
          announce({phase:'answer', answer:agentAnswerText(result), steps:agentAnswerSteps(result),
            messageId:delivery.message_id || '', replyId:delivery.reply_message_id || ''});
        };
        const refused = error => {
          const message = String(error?.message || error || 'The reply did not arrive.') +
            ' Your text is still here; retry will use the same request.';
          announce({phase:'failed', answer:message});
          if (draftRef.current && (draftRef.current !== turn.raw ||
              (pendingSend.current && pendingSend.current.requestId !== turn.requestId))) {
            const saved = {raw:draftRef.current, retry:pendingSend.current};
            setSavedDrafts(held => [...held, saved]);
          }
          draftRef.current = turn.raw; setText(turn.raw);
          pendingSend.current = turn;
          setState(message); setStateModel(turn.model);
        };
        announce({phase:'pending'});
        let outcome;
        try {
          outcome = Promise.resolve(window.ARCHHUB_AGENT(turn.said, turn.route, turn.context));
          admit(await agentTurnWithTimeout(outcome));
        } catch (error) {
          refused(error);
          if (error?.code === 'AGENT_TURN_TIMEOUT') {
            // A timeout does not cancel the provider. Keep the FIFO lock until
            // its original promise settles; never overlap the next request.
            try {
              admit(await outcome);
              if (pendingSend.current?.requestId === turn.requestId) {
                pendingSend.current = null;
                if (draftRef.current === turn.raw) { draftRef.current = ''; setText(''); }
                setState(''); setStateModel('');
              }
            } catch (lateError) {
              refused(lateError);
              if (lateError?.unconfirmed) pausedRequest.current = turn;
            }
          } else if (error?.unconfirmed) pausedRequest.current = turn;
          if (pausedRequest.current) break;
        }
      }
    } finally { sending.current = false; setAsking(false); }
  };
  const ask = () => {
    const raw = draftRef.current, said = raw.trim();
    if (!said) return;
    try {
      const proposed = applicationSettingProposal(said, target);
      if (proposed) {
        if (settingProposal) { setState('Review the current setting change first.'); return; }
        setSettingProposal(proposed); setState(''); draftRef.current = ''; setText(''); return;
      }
    } catch (error) { setState(error.message); return; }
    const retry = [pendingSend.current, pausedRequest.current].find(turn => turn &&
      turn.raw === raw && turn.said === said && turn.target === target.id);
    if (!window.ARCHHUB_AGENT) { setState('Sending is unavailable in this view. Your text is still here.'); return; }
    if (!retry && ((blocked && blocked.state !== 'unknown') || !route)) {
      setState(blocked?.message || 'Choose a model before sending. Your text is still here.');
      return;
    }
    if (typeof onSend === 'function') onSend();
    const requestId = nextRequestId(said);
    if (sending.current && pendingSend.current?.requestId === requestId) {
      setState('The original request is still in flight. Queued messages will wait for its reply.'); return;
    }
    const context = target.kind === 'graph'
        ? {graph:true, graph_id:target.graphId, request_id:requestId, generation:generationRequestOptions()}
        : {node:target.node.id, request_id:requestId, generation:generationRequestOptions()};
    const turn = retry || {raw, said, target:target.id, requestId, route, model:modelName, context};
    const retrying = pausedRequest.current?.requestId === requestId;
    if (retrying) { pausedRequest.current = null; sendQueue.current.unshift(turn); }
    else sendQueue.current.push(turn);
    pendingSend.current = null;
    draftRef.current = ''; setText('');
    setState(pausedRequest.current ? 'Queued messages are waiting for confirmation of the original request. Retry that request to continue.' : '');
    setStateModel(pausedRequest.current?.model || '');
    announceChatTurn({target:target.id, requestId, said, model:modelName, phase:sending.current || pausedRequest.current ? 'queued' : 'pending'});
    void drainQueue();
  };
  const retryOriginal = () => {
    const turn = pausedRequest.current || pendingSend.current;
    if (!turn || sending.current) return;
    pausedRequest.current = null; pendingSend.current = null;
    sendQueue.current.unshift(turn);
    if (draftRef.current === turn.raw) { draftRef.current = ''; setText(''); }
    setState(''); setStateModel('');
    announceChatTurn({target:turn.target, requestId:turn.requestId, said:turn.said, model:turn.model, phase:'pending'});
    void drainQueue();
  };
  return <window.AH_DS.Composer style={{width:'100%',margin:0,border:0,borderRadius:0, borderTop:`1px solid ${LM.lineSoft}`, padding:'10px 12px 12px', display:'flex', flexDirection:'column', gap:8, minWidth:0 }}>
    {settingProposal && window.ARCHHUB_APPROVAL_CARD && React.createElement(window.ARCHHUB_APPROVAL_CARD, {
      surface:'sysnodes', approval:{...settingProposal, state:'needs-user', agent:'ArchHub',
        changes:[{label:settingProposal.key, now:String(settingProposal.before), after:String(settingProposal.value)}],
        summary:String(settingProposal.before) + ' → ' + String(settingProposal.value)},
      onApprove:async () => {
        const held = applicationSettingsProjection();
        const node = held.graph?.nodes?.find(node => node.id === settingProposal.node);
        const row = node?.params?.find(row => row.k === settingProposal.key);
        if (!node || !row || row.editable !== true || studioCanvasScope(held.canvas) !== settingProposal.scope ||
            (row.cell_id || row.value_root || row.rel) !== settingProposal.cell || String(row.v) !== String(settingProposal.before)) {
          throw new Error('This setting changed. Reject this proposal and ask again.');
        }
        const saved = await window.pmPersistValue(node, row.k, settingProposal.value);
        setSettingProposal(null); setState(saved?.refresh_required ? 'Saved. Refresh the System graph to review the value.' : 'Saved ' + (row.label || row.k));
      },
      onDecline:() => { setSettingProposal(null); setState('Rejected.'); },
    })}
    {savedDrafts.map((saved, index) => <div key={index} role="status" data-saved-draft style={{fontSize:12, whiteSpace:'pre-wrap', overflowWrap:'anywhere'}}>
      <span>{saved.raw}</span>{' '}
      <window.AH_DS.Btn type="button" onClick={() => {
        const current = {raw:draftRef.current, retry:pendingSend.current};
        setSavedDrafts(held => held.flatMap((row, i) => i !== index ? [row] : current.raw ? [current] : []));
        draftRef.current = saved.raw; setText(saved.raw); pendingSend.current = saved.retry;
      }} style={window.AH_DS.styles.button("secondary", true)}>Restore draft</window.AH_DS.Btn>
    </div>)}
    {state && <div role="status" data-chat-turn="error" style={{ margin:0, display:'flex', alignItems:'flex-start', gap:8, maxHeight:120, overflow:'auto',
      whiteSpace:'pre-wrap', overflowWrap:'anywhere', fontFamily:LM.serif, fontSize:13, lineHeight:1.45, color:LM.ink }}>
      <div style={{ flex:1, minWidth:0 }}>
        {stateModel && <span style={{ display:'block', fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.06em', marginBottom:3 }}>{stateModel}</span>}
        <span>{state}</span>
      </div>
      {(pendingSend.current || pausedRequest.current) && <window.AH_DS.Btn type="button" onClick={retryOriginal} disabled={asking} style={{
        ...window.AH_DS.styles.button("secondary", true), flexShrink:0, padding:'4px 9px',
      }}>{asking ? 'Waiting...' : 'Retry'}</window.AH_DS.Btn>}
    </div>}
    {blocked && <div data-chat-no-model="" role="status" style={{
      background:LM.bgPanel, border:`1px solid ${LM.line}`, borderLeft:`3px solid ${LM.warn}`,
      borderRadius:LM.rad.md, padding:'9px 10px', display:'flex', flexDirection:'column', gap:7,
    }}>
      <div style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.warn, letterSpacing:'0.14em' }}>
        {READINESS_LABELS[blocked.state] || 'NO MODEL'}</div>
      <div style={{ fontSize:12.5, lineHeight:1.45, color:LM.ink }}>{blocked.message}</div>
      <div style={{ display:'flex', gap:7, flexWrap:'wrap' }}>
        {offers.has('sign_in') && <window.AH_DS.Btn type="button" onClick={() => {
          if (typeof onAccount === 'function') onAccount();
          else if (typeof onReadinessStale === 'function') onReadinessStale();
        }} style={{ padding:'5px 10px', background:LM.accent, color:(window.AH && window.AH.onFill) || '#180f08',
          border:0, borderRadius:LM.rad.sm, fontSize:11.5, fontWeight:500, cursor:'pointer' }}>Sign in</window.AH_DS.Btn>}
        {offers.has('retry_models') && <window.AH_DS.Btn type="button" onClick={() => typeof onModelReadRetry === 'function' && onModelReadRetry()} style={{
          padding:'4px 9px', background:'transparent', color:LM.ink, border:`1px solid ${LM.line}`,
          borderRadius:LM.rad.sm, fontSize:11.5, fontWeight:500, cursor:'pointer' }}>Retry</window.AH_DS.Btn>}
        {offers.has('choose_model') && <window.AH_DS.Btn type="button" onClick={() => typeof setPickerOpen === 'function' && setPickerOpen(true)} style={{
          padding:'4px 9px', background:'transparent', color:LM.ink, border:`1px solid ${LM.line}`,
          borderRadius:LM.rad.sm, fontSize:11.5, fontWeight:500, cursor:'pointer' }}>Choose a model</window.AH_DS.Btn>}
      </div>
    </div>}
    <window.AH_DS.Btn type="button" data-model-indicator="" onClick={() => setPickerOpen && setPickerOpen(true)}
      title={'Choose agent for '+target.name+' · Ctrl+K'}
      style={{ alignSelf:'flex-start', maxWidth:'100%', minWidth:0, display:'flex', alignItems:'center', gap:6, padding:'5px 9px',
        background:LM.bg, border:`1px solid ${LM.accent}66`, borderRadius:LM.rad.sm, color:LM.accent,
        fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, cursor:'pointer' }}>
      <span style={{ overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{'to '+target.name}</span>
      <span aria-hidden="true">▾</span>
    </window.AH_DS.Btn>
    <div style={{display:'grid',gap:8}}>
      <window.AH_DS.TextField multiline data-sysnodes-chat={target.kind === 'graph' || target.node?.application ? '' : undefined} aria-label="Ask selection" value={text} onChange={e => updateText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) {e.preventDefault();ask();} }} placeholder={placeholder}
        style={{width:'100%',minHeight:56,resize:'vertical',minWidth:0,background:LM.bgSoft,border:`1px solid ${LM.line}`,borderRadius:5,padding:'8px 10px',outline:0,color:LM.ink,fontFamily:LM.sans,fontSize:13}}/>
      <window.AH_DS.Btn onClick={ask} disabled={!text.trim()} style={{alignSelf:'end',justifySelf:'end', padding:'4px 11px', background:LM.accent,
        color:(window.AH && window.AH.onFill) || '#180f08', border:0, borderRadius:LM.rad.sm,
        fontSize:11.5, fontWeight:500, cursor:!text.trim() ? 'default' : 'pointer' }}>{asking ? (text.trim() ? 'Queue' : 'Waiting…') : 'Send'}</window.AH_DS.Btn>
    </div>
  </window.AH_DS.Composer>;
};
const InspectorTabs = ({ labels, active, onSelect, plate = false }) => <div role="tablist" aria-label="Selection inspector tabs" style={{ display:'flex', gap:plate?2:6, flexWrap:'wrap',borderBottom:plate?`1px solid ${LM.line}`:undefined,padding:plate?'0 12px':undefined }}>
  {labels.map(label => {
    const selected = active === label;
    return <window.AH_DS.Btn key={label} type="button" role="tab" aria-selected={selected ? 'true' : 'false'}
      onClick={() => onSelect(label)} style={{
      padding:plate?'0 10px':'4px 9px',height:plate?32:undefined,border:0,borderBottom:plate?`2px solid ${selected?LM.accent:'transparent'}`:undefined,borderRadius:plate?0:LM.rad.sm,background:plate?'transparent':selected?LM.accentDim:'transparent',
      color:selected ? plate?LM.ink:LM.accent : LM.inkSoft, fontFamily:LM.sans, fontSize:11.5, cursor:'pointer' }}>{label}</window.AH_DS.Btn>;
  })}
</div>;
const InspectorRuns = ({ node, graph, execution }) => {
  const wires = (graph?.wires || []).filter(wire => wire.from?.[0] === node.id || wire.to?.[0] === node.id);
  if (!hasRunsPanel(node, graph, execution)) return null;
  return <section aria-label="Runs" style={{ display:'flex', flexDirection:'column', gap:7 }}>
    {execution?.running && <div role="status">Running…</div>}
    {execution?.error && <div role="alert">{execution.error}</div>}
    {execution?.result && <CalmRow k="result" v={execution.result}/>}
    {node.status && <CalmRow k="last run" v={node.status}/>}
    {wires.map((wire, index) => <CalmRow key={wire.id || index} k={wire.from?.[0] === node.id ? 'out' : 'in'}
      v={wire.id || [wire.from?.[0], wire.to?.[0]].filter(Boolean).join(' → ')}/>)}
  </section>;
};
const forkThroughCanvas = node => {
  const duplicate = window.__archhubDuplicateNode;
  if (typeof duplicate !== 'function') throw new Error('Fork is unavailable in this view.');
  return duplicate(node);
};
const NodeRail = ({ libraryMode = false, node, hiddenWork = false, workshopRoom = '', onOpenWorkshop, scope = '', openConversation,
  graph = null, canvas = null, session = null, sessionRows = [], model, setPickerOpen, readiness = null,
  onReadinessStale, onModelReadRetry, onAccount }) => {
  // Work lives in the Workshop. A selection the canvas does not draw points there instead of an empty panel.
  if (!node && hiddenWork) return (
    <aside role="status" style={{ gridColumn:'2', gridRow:libraryMode?'1':'2', background:LM.bgPanel, borderLeft:`1px solid ${LM.line}`,
      padding:libraryMode?'12px':'14px 16px 20px', display:'flex', flexDirection:'column', gap:LM.sp.md }}>
      <div style={{ fontFamily:LM.serif, fontSize:19, lineHeight:1.1, color:LM.ink }}>Selected Work is in the Workshop</div>
      <div style={{ fontSize:12, lineHeight:1.5, color:LM.inkSoft }}>
        {workshopRoom ? 'Work is reviewed and edited in the Workshop, not on this canvas.' : 'No Workshop conversation is in this scope.'}</div>
      <div><window.AH_DS.Btn primary disabled={!workshopRoom} onClick={onOpenWorkshop}>Open the Workshop</window.AH_DS.Btn></div>
    </aside>
  );
  const workshopState=useWorkshopProjection();
  const inspectedNode = node ? aiNodeWithMovedParams(node) : graphInspectorNode(canvas, graph, session, sessionRows);
  const execution = window.useInspectorRun ? window.useInspectorRun(inspectedNode.id) : null;
  const sessionNode = isSessionInspectorNode(inspectedNode);
  const cat = studioCategory(inspectedNode.cat);
  const groupNode = !!inspectedNode.composition && !inspectedNode.application;
  const workshopNode = typeof isWorkshopGraphNode==='function' && isWorkshopGraphNode(inspectedNode) && !inspectedNode.application;
  const labels = groupNode ? ['Interface', 'Exposed parameters', 'Chat'] : inspectedNode.application || workshopNode ? ['Chat','Properties'] : libraryMode ? ['Chat','Properties', ...(hasRunsPanel(inspectedNode, graph, execution) ? ['Runs'] : [])] : [sessionNode || inspectedNode.graphNode || workshopNode ? 'Chat' : 'Properties',
    sessionNode || inspectedNode.graphNode || workshopNode ? 'Properties' : 'Chat',
    ...(hasRunsPanel(inspectedNode, graph, execution) ? ['Runs'] : [])];
  const roomConversationNode = inspectedNode.cat === 'ai' && inspectedNode.has_conversation && !nodeModelRow(inspectedNode);
  const defaultInspectorTab = groupNode ? 'Interface' :
    sessionNode || inspectedNode.graphNode || roomConversationNode || workshopNode ? 'Chat' : 'Properties';
  const [activeTab, setActiveTab] = React.useState(defaultInspectorTab);
  React.useEffect(() => setActiveTab(defaultInspectorTab), [defaultInspectorTab, inspectedNode.id]);
  const visibleTab = labels.includes(activeTab) ? activeTab : defaultInspectorTab;
  const authority = typeof window !== 'undefined' ? window.ARCHHUB_STUDIO_AUTHORITY : null;
  const openInspectedGroup = () => authority?.open?.(inspectedNode.id);
  const ungroupInspectedGroup = () => authority?.composition?.('ungroup', [inspectedNode.id]);
  const renameInspectedGroup = () => {
    const next = typeof window !== 'undefined' && window.prompt ? window.prompt('Rename group', inspectedNode.title || '') : '';
    if (next && next.trim()) authority?.setProperty?.(inspectedNode.id, 'name', next.trim());
  };
  const target = {kind:inspectedNode.graphNode ? 'graph' : sessionNode ? 'session' : 'node',
    id:inspectedNode.id, graphId:inspectedNode.graph_id || '', name:inspectedNode.title,
    node:inspectedNode.graphNode ? null : inspectedNode};
  const properties = <section aria-label="Properties"><window.NodeInspector key={inspectedNode.id} node={inspectedNode} onFork={forkThroughCanvas} plate={true} preview={watchPreviewFor(inspectedNode)}
    watchActions={{...(window.ARCHHUB_WATCH_ACTIONS?.get(inspectedNode.id) || {}),runToHere:typeof window.ARCHHUB_RUN_TO_HERE==='function'?()=>window.ARCHHUB_RUN_TO_HERE(inspectedNode.id):null}} onExport={()=>{
      const csv=watchExportCsv(inspectedNode,watchPreviewFor(inspectedNode));const url=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));
      const link=document.createElement('a');link.href=url;link.download=(inspectedNode.title || 'output')+'.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),0);
    }}/></section>;
  const groupInterface = <section aria-label="Interface" style={{display:'flex', flexDirection:'column', gap:10}}>
    <div style={{fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.14em'}}>INTERFACE · computed from crossing wires</div>
    {[...(inspectedNode.ins || []).map(port => ['in', port]), ...(inspectedNode.outs || []).map(port => ['out', port])].map(([dir, port]) => (
      <CalmRow key={dir + ':' + port.id} k={dir + ' · ' + (port.label || port.name || port.id)} v={dir === 'in' ? '→ Request' : 'Commit →'}/>
    ))}
    <div style={{display:'flex', gap:8, flexWrap:'wrap', marginTop:4}}>
      <window.AH_DS.Btn primary disabled={!authority?.open} onClick={openInspectedGroup}>Open</window.AH_DS.Btn>
      <window.AH_DS.Btn disabled={!authority?.composition} onClick={ungroupInspectedGroup}>Ungroup</window.AH_DS.Btn>
      <window.AH_DS.Btn disabled={!authority?.setProperty} onClick={renameInspectedGroup}>Rename</window.AH_DS.Btn>
    </div>
  </section>;
  const groupParameters = <section aria-label="Exposed parameters"><window.NodeInspector key={inspectedNode.id + ':group-params'} node={inspectedNode} onFork={forkThroughCanvas}/></section>;
  const selectionDescriptor=isWorkshopGraphNode(inspectedNode)?(workshopState?.workshops || []).find(row=>row.root===(inspectedNode.conversation_root || inspectedNode.workshop_root || inspectedNode.id)):null;
  const chat = <section aria-label={visibleTab === 'Chat' ? 'Chat' : undefined}>{inspectedNode.live ?
    <NodeModelConversation key={inspectedNode.id + ':conversation'} node={inspectedNode} scope={scope} openConversation={openConversation} active={visibleTab === 'Chat'}/> :
    <window.AH_DS.EmptyState compact glyph={null} title="Ask about this selection" detail="Message below, or @ an agent."/>}</section>;
  return (
    <aside aria-label="Selection inspector" style={{
      gridColumn:'2', gridRow:libraryMode?'1':'2',
      background:LM.bgPanel, borderLeft:`1px solid ${LM.line}`,
      overflow:'hidden', minHeight:0, minWidth:0,
      // One column, never wider than the 320px track: a long chip or value ellipsizes instead of
      // widening the panel past the window edge (founder window, 2026-10-12).
      display:'grid', gridTemplateRows:visibleTab!=='Chat'?'1fr':'1fr auto', gridTemplateColumns:'minmax(0, 1fr)',
    }}>
      <div className="ah-scroll" style={{ overflowY:'auto', overflowX:'hidden', minWidth:0, padding:0, display:'flex', flexDirection:'column', gap:0 }}>
        <window.AH_DS.SelectionHeader glyph={cat.icon} color={cat.col} title={inspectedNode.title} subtitle={inspectedNode.subtitle || inspectedNode.sub || inspectedNode.description}/>
        <InspectorTabs plate={true} labels={labels} active={visibleTab} onSelect={setActiveTab}/>
        {visibleTab === 'Interface' && groupInterface}
        {visibleTab === 'Exposed parameters' && groupParameters}
        <div hidden={visibleTab !== 'Chat'} style={{padding:12}}>{chat}{visibleTab==='Chat' && selectionDescriptor && window.ARCHHUB_WORKSHOP_SELECTION_APPROVAL && React.createElement(window.ARCHHUB_WORKSHOP_SELECTION_APPROVAL,{state:workshopState,descriptor:selectionDescriptor})}</div>
        {visibleTab === 'Properties' && properties}
        {visibleTab === 'Runs' && <InspectorRuns node={inspectedNode} graph={graph} execution={execution}/>}
      </div>
      {visibleTab==='Chat' && <ScopeComposer target={target} model={model} setPickerOpen={setPickerOpen} readiness={readiness} onSend={() => setActiveTab('Chat')}
        onReadinessStale={onReadinessStale} onModelReadRetry={onModelReadRetry} onAccount={onAccount}/>}
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
          <span style={{ color:cat.col }}>{cat.icon}</span>
          <span style={{ fontFamily:LM.sans, fontSize:11, fontWeight:600, color:LM.inkSoft, letterSpacing:0 }}>Conversation</span>
          <div style={window.AH_DS.styles.fill}/>
          <span style={{ fontFamily:LM.sans, fontSize:11, fontWeight:600, color:LM.inkSoft, letterSpacing:0 }}>
            {node.messages.length} msgs
          </span>
        </div>
        <div style={{ fontFamily:LM.sans, fontSize:16, fontWeight:600, letterSpacing:0, marginTop:5, lineHeight:'20px' }}>
          {node.title}
        </div>
        <div style={{ fontFamily:LM.sans, fontSize:11, fontWeight:600, color:LM.inkSoft, marginTop:3, letterSpacing:0 }}>
          {node.sub}
        </div>
      </div>

      {/* Scrollback */}
      <div ref={scrollRef} className="ah-scroll" style={{
        overflow:'auto', padding:'14px 16px',
        display:'flex', flexDirection:'column', gap:14,
      }}>
        <window.NodeInspector key={node.id + ':params'} node={node} onFork={forkThroughCanvas}/>

        {/* Date breakpoint */}
        <div style={{ display:'flex', alignItems:'center', gap:LM.sp.sm, fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.14em' }}>
          <span style={{ flex:1, height:1, background:LM.lineHair }}/>
          <span>WEDNESDAY · MAY 13</span>
          <span style={{ flex:1, height:1, background:LM.lineHair }}/>
        </div>

        {node.messages.map((m, i) => <ChatTurn key={i} m={m} isLast={i === node.messages.length - 1}/>)}

        {/* Tool-call summary block — what the chat triggered */}
        <div style={{
          padding:'9px 12px', background:LM.bgDeep, border:`1px solid ${LM.lineSoft}`,
          borderLeft:`2px solid ${LM.cyan}`, borderRadius:LM.rad.sm,
                fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, lineHeight:1.6,
        }}>
          <div style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.cyan, letterSpacing:'0.14em', marginBottom:LM.sp.xs }}>
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
          <div style={{ display:'flex', alignItems:'center', gap:5, marginTop:5, fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft }}>
            <ChatAction>@ skill</ChatAction>
            <ChatAction># host</ChatAction>
            <ChatAction>+ attach</ChatAction>
            <ChatAction>/remember</ChatAction>
            <div style={window.AH_DS.styles.fill}/>
            <span>sonnet 4.5 · ~412ms</span>
          </div>
        </div>
        <div style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, marginTop:6, letterSpacing:'0.04em', display:'flex', gap:10 }}>
          <span>↵ send</span>
          <span>⇧↵ newline</span>
          <span>⌘↑ edit last</span>
          <span style={window.AH_DS.styles.fill}/>
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
          <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.04em' }}>{m.time}</span>
        </div>
        <div style={{ fontSize:13, lineHeight:1.55, color:LM.ink }}>
          {m.text}
          {isAssistant && isLast && (
            <span style={{ display:'inline-block', width:6, height:12, background:LM.accent, marginLeft:2, verticalAlign:'-1px', animation:'lmCaret 1s infinite' }}/>
          )}
        </div>
        {isAssistant && (
          <>
            <window.AH_DS.Btn onClick={() => setShowReasoning(s => !s)} style={{
              background:'transparent', border:0, padding:'3px 0', color:LM.inkSoft,
              fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, letterSpacing:'0.06em', cursor:'pointer',
              display:'flex', alignItems:'center', gap:LM.sp.xs, marginTop:3,
            }}>
              <span>{showReasoning ? '▾' : '▸'}</span> reasoning
            </window.AH_DS.Btn>
            {showReasoning && (
              <div style={{
                marginTop:3, padding:'5px 8px', background:LM.bgDeep,
                border:`1px solid ${LM.lineSoft}`, borderLeft:`2px solid ${LM.purple}`, borderRadius:LM.rad.xs,
                fontFamily:LM.mono, fontSize:11, color:LM.inkSoft, lineHeight:1.6,
              }}>
                1. parse intent · 2. plan stages · 3. confirm units · 4. queue tools
              </div>
            )}
            <div style={{
              display:'flex', alignItems:'center', gap:5, marginTop:5,
              fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.04em',
            }}>
              <ChatAction>↻ regen</ChatAction>
              <ChatAction>⎘ branch</ChatAction>
              <ChatAction>✎ edit</ChatAction>
              <ChatAction>⧉ copy</ChatAction>
              <div style={window.AH_DS.styles.fill}/>
              <span>312 → 184 tok</span>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

const ChatAction = ({ children }) => (
  <window.AH_DS.Btn onClick={e => e.stopPropagation()} style={{
    padding:'1px 5px', background:'transparent', border:`1px solid ${LM.lineSoft}`,
    borderRadius:LM.rad.xs, color:LM.inkSoft, fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, cursor:'pointer',
  }}>{children}</window.AH_DS.Btn>
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
// The model the composer asks (published once by StudioLM); nothing else routes per task.
const pickedModel = () => {
  const m = window.ARCHHUB_PICKED_MODEL;
  return m && (m.routed || m.route) ? m : null;
};
const freeModelRoute = item => {
  const route = modelRoute(item).trim();
  if (!route) return false;
  if (/(safety|guard|moderation|embed|rerank|whisper|tts|audio)/i.test(route)) return false;
  if (route === 'openrouter/free' || route.endsWith(':free')) return true;
  return route.startsWith('lmstudio/') || route.startsWith('ollama/');
};
const modelOptionLabel = item => {
  const route = modelRoute(item);
  return [item.name || route, item.vendor, item.tag].filter(Boolean).join(' · ');
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
  <window.AH_DS.EmptyState title="" glyph={null} error={role === 'alert'} action={action}
    style={{padding:'12px 14px',fontSize:13,color:LM.inkSoft}}>{React.Children.map(children, child => typeof child === 'string' ? window.AH_DS.errorText(child) : child)}</window.AH_DS.EmptyState>
);

// Single source for "what is this item's current state?" — used by BOTH the sidebar badges and
// the panel rows. Defined once precisely so the two cannot derive the same fact differently:
// the badges previously counted only keys PRESENT in the store while the rows fell back to the
// seed per item, so an empty or partial store made a badge contradict the panel beside it.
const hostState = h => h.state; // the probe's answer; there is no local override
const systemGraphNodeCount = graph => (graph?.nodes || []).filter(node => node.application === true).length || (graph?.nodes || []).length;
const settingsRunningCount = (scope, data = {}) => {
  const transport = window.ARCHHUB_EXISTING_WORKSHOP;
  if (typeof transport?.settingsRunningCount === 'function') {
    const live = transport.settingsRunningCount(scope);
    if (live && Number.isFinite(live.running) && Number.isFinite(live.total)) return live;
  }
  if (scope === 'hub') {
    const rows = data.toolRows || [];
    return { running:rows.filter(row => row.status === 'running').length, total:rows.length };
  }
  const hosts = data.hosts || window.ARCHHUB_LIVE?.hosts || LM_HOSTS || [];
  const visible = hosts.filter(Boolean);
  const running = visible.filter(host => /running|connected|listening|syncing/i.test(String(host.state || ''))).length;
  return { running, total:visible.length };
};
const SETTINGS54_GROUPS = [
  {id:'account', glyph:'◍', color:LM.accent, title:'Account', items:['Account', 'Profile', 'Team'], focus:'Account'},
  {id:'connections', glyph:'⌁', color:LM.accent, title:'Connections', items:['Hub', 'Hosts', 'Providers', 'Connections'], focus:'Connections'},
  {id:'ai', glyph:'✦', color:LM.accent, title:'AI', items:['BABOOM', 'Models', 'Brain'], focus:'Workshop'},
  {id:'permissions', glyph:'⚑', color:LM.accent, title:'Permissions', items:['Permissions', 'Workspaces'], focus:'Permissions'},
  {id:'appearance', glyph:'◐', color:LM.accent, title:'Appearance', items:['Theme', 'Shortcuts'], focus:'UI & Design System'},
  {id:'storage', glyph:'▤', color:LM.accent, title:'Storage & About', items:['Storage', 'About'], focus:'Storage & About'},
];
const settings54NodeTitle = node => node?.title || node?.label || node?.id || 'System node';
const settings54ParamKey = row => row?.k || row?.key || row?.label || row?.name || '';
const settings54ParamLabel = row => row?.label || row?.name || row?.k || row?.key || '';
const settings54ParamValue = row => row?.v ?? row?.value ?? row?.current ?? '';
const settings54SystemNodes = graph => (graph?.nodes || []).filter(node => node?.application === true);
const settings54NodeGroup = node => {
  const text = [node?.group, node?.title, node?.sub, node?.engine, node?.id].filter(Boolean).join(' ').toLowerCase();
  if (/account|profile|team/.test(text)) return 'account';
  if (/connection|host|provider|hub|relay|connector/.test(text)) return 'connections';
  if (/ai|agent|model|brain|workshop|baboom/.test(text)) return 'ai';
  if (/permission|workspace|approval|consent|govern/.test(text)) return 'permissions';
  if (/theme|appearance|ui|design|shortcut/.test(text)) return 'appearance';
  if (/storage|about|update|archive|release/.test(text)) return 'storage';
  return '';
};
const settings54GroupNodes = (group, nodes) => nodes.filter(node =>
  settings54NodeGroup(node) === group.id ||
  group.items.some(item => settings54NodeTitle(node).toLowerCase().includes(item.toLowerCase())) ||
  settings54NodeTitle(node).toLowerCase().includes(group.focus.toLowerCase()));
const settings54FindNodeForGroup = (group, nodes) => settings54GroupNodes(group, nodes)[0] || null;
const settings54MatchNode = (node, query) => {
  const q = String(query || '').trim().toLowerCase();
  if (!q) return true;
  return [settings54NodeTitle(node), node?.sub, node?.group, node?.engine, ...(node?.params || []).map(settings54ParamLabel)]
    .some(value => String(value || '').toLowerCase().includes(q));
};
const SystemSettingsNav = ({onOpen,selectedId,onSelect}) => {
  const projection=useStudioProjection(), [query,setQuery]=React.useState('');
  const nodes=settings54SystemNodes(projection?.graph || LM_GRAPH);
  const selected=nodes.find(node=>node.id===(selectedId || projection?.selected));
  const active=selected && settings54NodeGroup(selected);
  const matches=nodes.filter(node=>settings54MatchNode(node,query));
  return <window.AH_DS.Frame as="aside" data-system-settings-nav="" style={{height:'100%',background:LM.bgPanel,gridTemplateRows:'44px 52px 1fr'}}>
    <PanelHead title="Settings"/><div style={{padding:'10px 8px'}}><window.AH_DS.TextField value={query} onChange={e=>setQuery(e.target.value)} placeholder="Find a setting" aria-label="Find a setting"/></div>
    <div style={{display:'grid',alignContent:'start',gap:3,padding:'0 6px'}}>{query.trim() ? matches.length ? matches.map(node=><window.AH_DS.Btn key={node.id} kind="ghost" onClick={()=>onSelect?.(node.id)}>{settings54NodeTitle(node)}</window.AH_DS.Btn>) : <window.AH_DS.EmptyState title="No settings found"/> : SETTINGS54_GROUPS.map(group=><window.AH_DS.Btn key={group.id} kind="ghost"
      title={group.title+' · Ctrl+K'} aria-current={group.id===active?'page':undefined} onClick={()=>onOpen(group.items[0].toLowerCase())}
      style={{height:56,justifyContent:'flex-start',textAlign:'left',gap:10,background:group.id===active?LM.bgHover:'transparent'}}>
      <Settings54Tile glyph={group.glyph} color={group.color}/><span><strong style={{display:'block',fontSize:13}}>{group.title}</strong><span style={{display:'block',fontSize:11,color:LM.inkSoft}}>{settings54GroupSub(group)}</span></span>
    </window.AH_DS.Btn>)}</div>
  </window.AH_DS.Frame>;
};
const settings54GroupSub = group => ({account:'Account · Profile · Team', connections:'Hosts · AI accounts · apps', ai:'Models · Brain', permissions:'what agents may do · Workspaces', appearance:'Theme · Shortcuts', storage:'disk · version · updates'})[group.id];

const Settings54Tile = ({ glyph, color, size=20 }) => (
  <span aria-hidden="true" style={{ width:size, height:size, borderRadius:size === 30 ? 8 : 5, background:color, color:LM.onFill,
    display:'grid', placeItems:'center', fontFamily:LM.sans, fontSize:size === 30 ? 15 : 11, fontWeight:600, flex:'none' }}>{glyph}</span>
);
const Settings54Seg = ({ value, options=['Ask', 'Allow', 'Off'], onChange, ariaLabel, disabled=false }) => (
  <span data-seg-control="" aria-label={ariaLabel} style={{ display:'inline-flex', border:`1px solid ${LM.line}`, borderRadius:LM.rad.control,
    overflow:'hidden', height:26, fontFamily:LM.sans }}>
    {options.map((option, index) => <window.AH_DS.Btn key={option} type="button" disabled={disabled} onClick={() => onChange && onChange(option)}
      style={{ border:0, borderLeft:index ? `1px solid ${LM.line}` : 0, background:option === value ? LM.accentSoft : 'transparent',
        color:option === value ? LM.accentHi : LM.ink, padding:'0 8px', minWidth:42, fontFamily:LM.sans, fontSize:12,
        cursor:disabled ? 'default' : 'pointer', opacity:disabled ? .55 : 1 }}>{option}</window.AH_DS.Btn>)}
  </span>
);
const Settings54Select = ({ label, value, onChange, options = [], disabled=false }) => (
  <select aria-label={label} value={value} disabled={disabled} onChange={event => onChange && onChange(event.target.value)}
    data-settings54-sel="" style={{ width:200, height:26, boxSizing:'border-box', padding:'0 8px',
      border:`1px solid ${LM.line}`, borderRadius:LM.rad.control, background:LM.bgSoft,
      color:LM.ink, fontFamily:LM.sans, fontSize:12, opacity:disabled ? .55 : 1 }}>
    {options.map(option => Array.isArray(option)
      ? <option key={option[0]} value={option[0]}>{option[1]}</option>
      : <option key={option} value={option}>{option}</option>)}
  </select>
);
const Settings54Switch = ({ on, disabled, onClick, label }) => (
  <window.AH_DS.Toggle on={on} disabled={disabled} onClick={onClick} label={label}/>
);
const Settings54Num = ({ value, unit, onChange, label, disabled=false }) => (
  <span style={{ display:'inline-flex', alignItems:'center', gap:6 }}>
    <input aria-label={label} type="number" value={value} disabled={disabled} onChange={event => onChange && onChange(event.target.value)}
      style={{ width:68, height:26, boxSizing:'border-box', padding:'0 8px', textAlign:'right',
        border:`1px solid ${LM.line}`, borderRadius:LM.rad.control, background:LM.bgSoft, color:LM.ink,
        fontFamily:LM.sans, fontSize:12, opacity:disabled ? .55 : 1 }}/>
    {unit && <span style={{ fontSize:12, color:LM.inkSoft }}>{unit}</span>}
  </span>
);
const settings54ParamWriter = row => {
  const key = settings54ParamKey(row);
  if (!key) return { ok:false, reason:'No parameter key is published for this setting.' };
  if (row?.editable === false) return { ok:false, reason:'This setting is read-only in the System projection.' };
  const wanted = String(row?.writer || row?.write_route || row?.writeRoute || row?.setter || '').trim();
  const hasPersist = typeof window !== 'undefined' && typeof window.pmPersistValue === 'function';
  const hasNodeProp = typeof window !== 'undefined' && typeof window.ARCHHUB_SET_NODE_PROP === 'function';
  if (wanted) {
    if (/pmPersistValue/i.test(wanted)) return hasPersist
      ? { ok:true, route:'pmPersistValue' }
      : { ok:false, reason:'Writer pmPersistValue is not available in this runtime.' };
    if (/ARCHHUB_SET_NODE_PROP|node[-_ ]?prop|system[-_ ]?param/i.test(wanted)) return hasNodeProp
      ? { ok:true, route:'ARCHHUB_SET_NODE_PROP' }
      : { ok:false, reason:'Writer ARCHHUB_SET_NODE_PROP is not available in this runtime.' };
    return { ok:false, reason:'Writer ' + wanted + ' is not supported in this runtime.' };
  }
  if (hasNodeProp) return { ok:true, route:'ARCHHUB_SET_NODE_PROP' };
  return { ok:false, reason:'Parameter writer is not available in this runtime.' };
};
const Settings54ParamRow = ({ label, children, changed, hint, onReset }) => (
  <window.AH_DS.Row data-settings54-param-row="" label={label} changed={changed && !!onReset} hint={hint} onReset={onReset}
    style={{gridTemplateColumns:'96px minmax(0, 1fr) auto',fontFamily:LM.sans}}>
    <span style={window.AH_DS.styles.flex}>{children}</span>
  </window.AH_DS.Row>
);
const Settings = props => {
  const canvasRead = useDeferredCanvas();
  if (canvasRead.pending || canvasRead.error) return <div data-settings-canvas-loading="" role="dialog" style={{position:'absolute', top:0, bottom:22, left:64, right:0, zIndex:60, padding:24, background:LM.bg, color:LM.ink}}>
    <window.AH_DS.EmptyState title={canvasRead.error ? 'Settings unavailable' : 'Reading your settings…'} error={!!canvasRead.error}
      detail={canvasRead.error} onRetry={canvasRead.error ? canvasRead.retry : undefined}/>
    <window.AH_DS.Btn onClick={props.onClose}>Close</window.AH_DS.Btn>
  </div>;
  return <SettingsLoaded {...props}/>;
};
const SettingsLoaded = ({ onClose, onHome = onClose, account, setAccount, onSignOut, initialTab = 'theme', onOpenTool, onOpenToolGraph }) => {
  const providers = useProviderStatus();
  const workshopState = useWorkshopProjection();
  const release = releaseStatus(workshopState);
  const personal = usePersonalTheme();
  const hub = useToolHubProjection();
  const toolRows = toolRowsFromOwners({workshopState, account, personal, hub});
  const authorityState = useStudioProjection();
  const projectedGraph = authorityState?.graph || LM_GRAPH;
  const systemNodes = settings54SystemNodes(projectedGraph);
  const canOpenSystem = systemAllowed(authorityState?.canvas, projectedGraph);
  const projectionRevision = authorityState?.canvas?.revision ?? workshopState?.canvas?.revision ?? '';
  useLiveCatalogue('ARCHHUB_LOAD_HOSTS', LM_HOSTS);
  const [store, setStore] = React.useState(() => {
    var seed = { forgotten: [], revealed: {} };
    try {
      var raw = localStorage.getItem(SET_LS);
      if (raw) {
        var saved = JSON.parse(raw) || {};
        delete saved.theme; delete saved.perms; delete saved.hosts;
        return Object.assign({}, seed, saved, { revealed: Object.assign({}, seed.revealed, saved.revealed || {}) });
      }
    } catch (e) {}
    return seed;
  });
  React.useEffect(() => { try { localStorage.setItem(SET_LS, JSON.stringify(store)); } catch (e) {} }, [store]);
  const patch = (k, v) => setStore(st => Object.assign({}, st, typeof k === 'object' ? k : { [k]: v }));
  const groupFromTab = tabName => {
    const map = {hub:'connections', hosts:'connections', providers:'connections', connections:'connections', account:'account', profile:'account', team:'account',
      memory:'ai', brain:'ai', baboom:'ai', models:'ai', permissions:'permissions', workspaces:'permissions',
      theme:'appearance', shortcuts:'appearance', storage:'storage', about:'storage', system:'appearance'};
    return SETTINGS54_GROUPS.find(group => group.id === (map[tabName] || 'appearance')) || SETTINGS54_GROUPS[4];
  };
  const initialGroup = groupFromTab(initialTab);
  const [selectedGroupId, setSelectedGroupId] = React.useState(initialGroup.id);
  const userSelection = React.useRef({tab:initialTab, manual:false});
  const [selectedId, setSelectedId] = React.useState(() => settings54FindNodeForGroup(initialGroup, systemNodes)?.id || '');
  const [query, setQuery] = React.useState('');
  const [statusMessage, setStatusMessage] = React.useState('');
  const [activeCapability, setActiveCapability] = React.useState(initialGroup.items[0] || 'Theme');
  const selectedGroup = SETTINGS54_GROUPS.find(group => group.id === selectedGroupId) || initialGroup;
  React.useEffect(() => {
    const capabilityMap = {hub:'Hub', hosts:'Hosts', providers:'Providers', connections:'Connections', account:'Account', profile:'Profile', team:'Team',
      memory:'Brain', brain:'Brain', baboom:'BABOOM', models:'Models', permissions:'Permissions', workspaces:'Workspaces',
      theme:'Theme', shortcuts:'Shortcuts', storage:'Storage', about:'About', system:'System'};
    if (userSelection.current.tab !== initialTab) userSelection.current = {tab:initialTab, manual:false};
    if (initialTab && !userSelection.current.manual) {
      const group = groupFromTab(initialTab);
      const node = settings54FindNodeForGroup(group, systemNodes);
      setSelectedGroupId(group.id);
      setSelectedId(node?.id || '');
      setActiveCapability(capabilityMap[initialTab] || 'Hub');
    }
  }, [initialTab, systemNodes.map(node => node.id).join('|')]);
  React.useEffect(() => {
    const selectedStillLive = !!selectedId && systemNodes.some(node => node.id === selectedId);
    if (selectedStillLive) return;
    const node = settings54FindNodeForGroup(selectedGroup, systemNodes);
    setSelectedId(node?.id || '');
  }, [selectedId, selectedGroup.id, systemNodes.map(node => node.id).join('|')]);
  const selectedNode = systemNodes.find(node => node.id === selectedId) || null;
  const visibleGroups = SETTINGS54_GROUPS.filter(group => !query.trim() ||
    group.title.toLowerCase().includes(query.trim().toLowerCase()) ||
    group.items.some(item => item.toLowerCase().includes(query.trim().toLowerCase())) ||
    settings54GroupNodes(group, systemNodes).some(node => settings54MatchNode(node, query)));
  const chooseGroup = group => {
    userSelection.current = {tab:initialTab, manual:true};
    const node = settings54FindNodeForGroup(group, systemNodes);
    setSelectedGroupId(group.id);
    setSelectedId(node?.id || '');
    setActiveCapability(group.items[0] || group.title);
  };
  const chooseCapability = (group, label) => {
    userSelection.current = {tab:initialTab, manual:true};
    const node = systemNodes.find(item =>
      settings54NodeGroup(item) === group.id &&
      settings54NodeTitle(item).toLowerCase().includes(String(label || '').toLowerCase())) ||
      settings54FindNodeForGroup(group, systemNodes);
    setSelectedGroupId(group.id);
    setSelectedId(node?.id || '');
    setActiveCapability(label);
  };
  const findSetting = value => {
    userSelection.current = {tab:initialTab, manual:true};
    setQuery(value);
    const match = systemNodes.find(node => settings54MatchNode(node, value));
    if (match) {
      const group = SETTINGS54_GROUPS.find(item => settings54GroupNodes(item, [match]).length);
      if (group) setSelectedGroupId(group.id);
      setSelectedId(match.id);
      setActiveCapability('Properties');
    }
  };
  const writeParam = async (node, row, value) => {
    const key = settings54ParamKey(row);
    if (!node || !key) throw new Error('Unavailable');
    const writer = settings54ParamWriter(row);
    if (!writer.ok) { setStatusMessage(writer.reason); return; }
    setStatusMessage('');
    try {
      if (writer.route === 'pmPersistValue') await window.pmPersistValue(node, key, value);
      else if (writer.route === 'ARCHHUB_SET_NODE_PROP') await window.ARCHHUB_SET_NODE_PROP(node.id, key, value);
      else throw new Error(writer.reason || 'Parameter writer is not available in this runtime.');
      setStatusMessage('Saved ' + settings54ParamLabel(row));
    } catch (error) {
      setStatusMessage(error.message || 'Parameter write failed.');
    }
  };
  const optionsFor = row => {
    const opts = row?.options || row?.opts || row?.choices || row?.enum;
    if (Array.isArray(opts)) return opts.map(option => Array.isArray(option) ? option : String(option));
    return [];
  };
  const paramControl = (node, row) => {
    const label = settings54ParamLabel(row);
    const value = settings54ParamValue(row);
    const type = String(row?.type || row?.kind || '').toLowerCase();
    const writer = settings54ParamWriter(row);
    const opts = optionsFor(row);
    const unavailable = !writer.ok;
    const title = writer.ok ? '' : writer.reason;
    if (opts.length) return <span title={title}><Settings54Select label={label} value={String(value)} options={opts} disabled={unavailable}
      onChange={next => writeParam(node, row, next)}/></span>;
    if (type.includes('bool') || type.includes('toggle') || typeof value === 'boolean') return <span title={title}><Settings54Switch on={value === true || String(value).toLowerCase() === 'true' || String(value).toLowerCase() === 'on'}
      disabled={unavailable} label={label} onClick={() => writeParam(node, row, !(value === true || String(value).toLowerCase() === 'true' || String(value).toLowerCase() === 'on'))}/></span>;
    if (type.includes('number') || type.includes('int') || type.includes('float') || (String(value) !== '' && !Number.isNaN(Number(value)))) return <span title={title}><Settings54Num value={String(value)} disabled={unavailable}
      unit={row?.unit || ''} label={label} onChange={next => writeParam(node, row, next)}/></span>;
    if (type.includes('color') || /^#[0-9a-f]{6}$/i.test(String(value))) return <input aria-label={label} title={title} type="color" defaultValue={String(value || '#4f8cff')} disabled={unavailable}
      onChange={event => writeParam(node, row, event.target.value)}
      style={{ width:26, height:26, padding:0, border:`1px solid ${LM.line}`, borderRadius:LM.rad.control, background:LM.bgSoft, opacity:unavailable ? .55 : 1 }}/>;
    return <input aria-label={label} title={title} defaultValue={String(value)} disabled={unavailable} onBlur={event => writeParam(node, row, event.target.value)}
      style={{ height:26, width:'100%', background:LM.bgSoft, color:LM.ink, border:`1px solid ${LM.line}`, borderRadius:LM.rad.control, fontFamily:LM.sans, fontSize:12, padding:'0 8px', opacity:unavailable ? .55 : 1 }}/>;
  };
  const openCompatibilityTab = tabName => {
    const key = String(tabName || '').toLowerCase();
    const names = {hub:'Hub', hosts:'Hosts', providers:'Providers', connections:'Connections',
      account:'Account', profile:'Profile', team:'Team', memory:'Brain', brain:'Brain', baboom:'BABOOM',
      models:'Models', permissions:'Permissions', workspaces:'Workspaces', theme:'Theme',
      shortcuts:'Shortcuts', storage:'Storage', about:'About', system:'System'};
    chooseCapability(groupFromTab(key), names[key] || String(tabName || ''));
  };
  const openSystemGraph = async () => {
    setStatusMessage('');
    const opened = await onOpenToolGraph?.('system');
    if (opened?.ok) onClose?.();
    else if (!opened?.stale) setStatusMessage(opened?.error || 'System graph is not admitted in this workspace.');
  };
  const inspectorRows = () => {
    const capabilityBelongsToNode = selectedGroup.items.includes(activeCapability) ||
      (selectedGroup.id === 'appearance' && activeCapability === 'System');
    const showingProperties = activeCapability === 'Properties' ||
      (!!selectedNode && !capabilityBelongsToNode) ||
      (!!query.trim() && selectedNode && settings54MatchNode(selectedNode, query));
    if (showingProperties && selectedNode?.application) return <window.NodeInspector node={selectedNode}/>;
    const capabilityPanel = () => {
      if (showingProperties) return null;
      if (activeCapability === 'Hub') return <SettingsHub toolRows={toolRows} onClose={onClose} onOpenTool={onOpenTool} columns={3}/>;
      if (activeCapability === 'System') return <SettingsSystem graph={authorityState?.graph || LM_GRAPH} projection={authorityState} onClose={onClose} onOpenToolGraph={onOpenToolGraph} onBackToSettings={() => openCompatibilityTab('hub')}/>;
      if (activeCapability === 'Account') return <SettingsAccount account={account} setAccount={setAccount} onSignOut={onSignOut}/>;
      if (activeCapability === 'Brain') return <SettingsMemory store={store} patch={patch}/>;
      if (activeCapability === 'BABOOM') return <SettingsBaboom onOpenToolGraph={onOpenToolGraph} onClose={onClose}/>;
      if (activeCapability === 'Team') return <SettingsTeam account={account} onAccount={() => openCompatibilityTab('account')}/>;
      if (activeCapability === 'Profile') return <SettingsProfile/>;
      if (activeCapability === 'Permissions') return <SettingsPermissions account={account} onTab={openCompatibilityTab}/>;
      if (activeCapability === 'Workspaces') return <SettingsWorkspaces/>;
      if (activeCapability === 'Hosts') return <SettingsHosts/>;
      if (activeCapability === 'Connections') return <SettingsConnections/>;
      if (activeCapability === 'Providers') return <SettingsProviders providers={providers} onTab={openCompatibilityTab}/>;
      if (activeCapability === 'Models') return <SettingsModels/>;
      if (activeCapability === 'Theme') return <SettingsTheme/>;
      if (activeCapability === 'Shortcuts') return <SettingsShortcuts/>;
      if (activeCapability === 'Storage') return <SettingsStorage/>;
      if (activeCapability === 'About') return <SettingsAbout providers={providers} release={release}/>;
      return null;
    };
    const panel = capabilityPanel();
    if (panel) return <div data-settings54-capability={activeCapability} style={{ padding:12 }}>{panel}</div>;
    const rows = selectedNode?.params || [];
    if (!selectedNode) return null;
    if (!rows.length) return null;
    return rows.map(row => <Settings54ParamRow key={settings54ParamKey(row) || settings54ParamLabel(row)} label={settings54ParamLabel(row)}
      hint={[row?.hint || row?.description || '', settings54ParamWriter(row).ok ? '' : settings54ParamWriter(row).reason].filter(Boolean).join(' ')}>
      {paramControl(selectedNode, row)}</Settings54ParamRow>);
  };
  return (
    <div onClick={onClose} style={{
      position:'absolute', top:0, bottom:22, left:64, right:0, background:LM.bgDeep, zIndex:60,
      display:'grid',
    }}>
      <div data-settings54-shell="" role="dialog" aria-modal="true" aria-label="Settings" onClick={e => e.stopPropagation()} style={{
        width:'100%', height:'100%', background:LM.bgDeep, color:LM.ink, overflow:'hidden',
        display:'grid', gridTemplateRows:'1fr', fontFamily:LM.sans,
      }}>
        <div style={{ display:'grid', gridTemplateColumns:'248px minmax(0,1fr)', minHeight:0 }}>
          <aside style={{ background:LM.bgPanel, borderRight:`1px solid ${LM.line}`, display:'grid', gridTemplateRows:'44px auto 1fr', minWidth:0 }}>
            <div style={{ display:'flex', alignItems:'center', padding:'0 12px', borderBottom:`1px solid ${LM.lineSoft}`, fontSize:16, fontWeight:600 }}>Settings</div>
            <label style={{ margin:10, height:32, borderRadius:5, background:LM.bgSoft, border:`1px solid ${LM.line}`, display:'flex', alignItems:'center', gap:8, padding:'0 10px', color:LM.inkSoft }}>
              <span>⌕</span><input aria-label="Find a setting" placeholder="Find a setting" value={query} onChange={event => findSetting(event.target.value)}
                style={{ flex:1, minWidth:0, border:0, outline:0, background:'transparent', color:LM.ink, fontFamily:LM.sans, fontSize:13 }}/>
            </label>
            <div data-settings54-nav="" className="ah-scroll" style={{ display:'grid', alignContent:'start', gap:3, padding:'0 6px', overflow:'auto' }}>
              {visibleGroups.map(group => {
                const active = group.id === selectedGroup.id;
                return <div key={group.id} style={{ borderRadius:6, background:active ? LM.bgHover : 'transparent', padding:4 }}>
                  <window.AH_DS.Btn type="button" onClick={() => chooseGroup(group)} style={{ width:'100%', minHeight:34, border:0, background:'transparent',
                    color:active ? LM.ink : LM.inkSoft, display:'grid', gridTemplateColumns:'20px 1fr', gap:10, alignItems:'center',
                    textAlign:'left', cursor:'pointer', fontFamily:LM.sans, padding:4 }}>
                    <Settings54Tile glyph={group.glyph} color={group.color}/>
                    <span style={{ minWidth:0 }}>
                      <span data-settings54-group-title="" style={{ display:'block', fontSize:13, fontWeight:active ? 600 : 400, color:active ? LM.ink : LM.inkSoft }}>{group.title}</span>
                      <span style={{ display:'block', fontSize:11, color:LM.inkSoft, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis' }}>{settings54GroupSub(group)}</span>
                    </span>
                  </window.AH_DS.Btn>
                  {(active || group.id === 'appearance') && <div data-settings54-capability-nav={group.id} style={{ display:'flex', flexWrap:'wrap', gap:4, padding:'0 4px 4px 34px' }}>
                    {(active ? group.items : []).map(item => <React.Fragment key={item}>
                      <window.AH_DS.Btn type="button" onClick={() => chooseCapability(group, item)}
                        style={({...window.AH_DS.styles.button('secondary', true), borderColor:activeCapability === item ? LM.accent : LM.line, ...{height:22, padding:'0 7px', fontSize:11, maxWidth:'100%'}})}>{item}</window.AH_DS.Btn>
                      {item === 'Hosts' && <span data-settings-host-total={hostTally().total} style={{fontSize:11, color:LM.inkSoft, alignSelf:'center'}}>
                        {hostTally().read ? hostTally().running + '/' + hostTally().total + ' running' : 'checking hosts'}
                      </span>}
                    </React.Fragment>)}
                    {group.id === 'appearance' && <window.AH_DS.Btn type="button" onClick={() => chooseCapability(group, 'System')}
                      style={({...window.AH_DS.styles.button('secondary', true), borderColor:activeCapability === 'System' ? LM.accent : LM.line, ...{height:22, padding:'0 7px', fontSize:11}})}>System</window.AH_DS.Btn>}
                  </div>}
                </div>;
              })}
            </div>
          </aside>
          <main style={{ display:'grid', gridTemplateRows:'36px 1fr', minHeight:0, borderRight:`1px solid ${LM.line}` }}>
            <div style={{ display:'flex', alignItems:'center', gap:10, padding:'0 12px', borderBottom:`1px solid ${LM.lineSoft}`, background:LM.bg }}>
              <span style={{ fontSize:12, color:LM.inkSoft }}>Settings <span style={{ margin:'0 6px' }}>›</span><span style={{ color:LM.ink }}>{activeCapability === 'Properties' ? 'System' : activeCapability || selectedGroup.title}</span></span>
              <span style={{ fontSize:11, color:canOpenSystem ? LM.ok : LM.warn }}>{canOpenSystem ? 'Connected · live' : 'System graph unavailable'}</span><span style={window.AH_DS.styles.fill}/>
              {statusMessage && <span role="status" style={{ fontSize:11, color:LM.inkSoft, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', maxWidth:260 }}>{statusMessage}</span>}

              <window.AH_DS.Btn type="button" onClick={openSystemGraph} style={({...window.AH_DS.styles.button('secondary', true), borderColor:false ? LM.accent : LM.line, ...{}})}>System graph</window.AH_DS.Btn>
              <window.AH_DS.Btn type="button" onClick={onHome} title="Home (Alt+Home)" style={({...window.AH_DS.styles.button('secondary', true), borderColor:false ? LM.accent : LM.line, ...{}})}>Home</window.AH_DS.Btn>
              <window.AH_DS.Btn type="button" aria-label="Close" data-close-button="" onClick={onClose} style={({...window.AH_DS.styles.button('secondary', true), borderColor:false ? LM.accent : LM.line, ...{}})}>Close</window.AH_DS.Btn>
            </div>
            <div data-settings54-landing="" className="ah-scroll" style={{overflow:'auto',padding:'20px 24px 24px',background:LM.bgPanel}}>{inspectorRows()}</div>
          </main>

        </div>
      </div>
    </div>
  );
};
const SystemMiniGraph = ({ graph }) => {
  const nodes = (graph?.nodes || []).filter(node => node.application === true);
  const drawn = nodes.length ? nodes : (graph?.nodes || []);
  const nodeIds = drawn.map(node => node.id);
  const idSet = new Set(nodeIds);
  const wires = (graph?.wires || []).filter(wire => idSet.has(wire.from?.[0]) && idSet.has(wire.to?.[0]));
  const sizes = Object.fromEntries(drawn.map(node => [node.id, {w:92, h:32}]));
  const positions = Object.fromEntries(drawn.map((node, index) => [node.id, {
    x:Number.isFinite(node.x) ? node.x : (index % 6) * 120,
    y:Number.isFinite(node.y) ? node.y : Math.floor(index / 6) * 56,
  }]));
  const arranged = drawn.length ? canvasArrangePositions(nodeIds, positions, sizes, nodeIds, wires) : {};
  const boxes = drawn.map(node => ({node, ...(arranged[node.id] || positions[node.id]), ...sizes[node.id]}));
  const left = Math.min(0, ...boxes.map(box => box.x)) - 28;
  const top = Math.min(0, ...boxes.map(box => box.y)) - 28;
  const right = Math.max(260, ...boxes.map(box => box.x + box.w)) + 28;
  const bottom = Math.max(160, ...boxes.map(box => box.y + box.h)) + 28;
  const groups = new Map();
  for (const box of boxes) {
    const key = box.node.group || box.node.domain || '';
    if (!key) continue;
    const held = groups.get(key) || {label:key, left:Infinity, top:Infinity, right:-Infinity, bottom:-Infinity};
    held.left = Math.min(held.left, box.x - 8); held.top = Math.min(held.top, box.y - 8);
    held.right = Math.max(held.right, box.x + box.w + 8); held.bottom = Math.max(held.bottom, box.y + box.h + 8);
    groups.set(key, held);
  }
  return <div style={{display:'flex', flexDirection:'column', gap:14}}>
    <div data-settings-system-preview data-system-mini-graph aria-label="Read-only System graph preview" style={{
      background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg, padding:16,
      minHeight:210, position:'relative', overflow:'hidden',
      backgroundImage:`radial-gradient(${LM.lineSoft} 1px, transparent 1px)`,
      backgroundSize:'18px 18px',
    }}>
      <svg viewBox={`${left} ${top} ${right - left} ${bottom - top}`} preserveAspectRatio="xMidYMid meet"
        style={{position:'absolute', inset:12, width:'calc(100% - 24px)', height:'calc(100% - 24px)', overflow:'visible'}}>
        {[...groups.values()].map(group => <g key={group.label} data-system-mini-group-boundary="group boundary">
          <rect x={group.left} y={group.top} width={group.right - group.left} height={group.bottom - group.top}
            rx="8" fill={LM.bgSoft + '66'} stroke={LM.lineSoft} strokeDasharray="6 6"/>
          <text x={group.left + 8} y={group.top + 12} fill={LM.inkSoft} fontFamily="JetBrains Mono" fontSize={LM.fs.label.sz}>{group.label}</text>
        </g>)}
        {wires.map((wire, index) => {
          const from = boxes.find(box => box.node.id === wire.from?.[0]);
          const to = boxes.find(box => box.node.id === wire.to?.[0]);
          if (!from || !to) return null;
          const x1 = from.x + from.w, y1 = from.y + from.h / 2, x2 = to.x, y2 = to.y + to.h / 2;
          const dx = Math.max(24, Math.abs(x2 - x1) * 0.45);
          return <path key={wire.id || index} data-system-mini-wire d={`M${x1},${y1} C${x1+dx},${y1} ${x2-dx},${y2} ${x2},${y2}`}
            fill="none" stroke={LM.inkSoft} strokeWidth="1.4" opacity="0.72"/>;
        })}
        {boxes.map(({node, x, y, w, h}) => {
          const cat = studioCategory(node.cat || (node.tool ? 'tools' : 'logic'));
          return <g key={node.id} data-system-mini-node={node.id}>
            <rect x={x} y={y} width={w} height={h} rx="5" fill={LM.bgPanel} stroke={LM.line}/>
            <rect x={x} y={y} width={w} height="3" rx="2" fill={cat.col}/>
            <text x={x + 8} y={y + 20} fill={LM.ink} fontFamily="JetBrains Mono" fontSize={LM.fs.dataSm.sz}>
              {node.title || node.label || node.id}
            </text>
          </g>;
        })}
      </svg>
    </div>
  </div>;
};
const SettingsMods = ({ compact=false }) => {
  const [state, setState] = React.useState(null);
  const [toast, setToast] = React.useState('');
  const call = async body => {
    const api = window.ARCHHUB_MODS;
    if (!api) return null;
    const answer = await api(body || {action:'state'});
    if (answer?.mods) setState(answer.mods);
    return answer;
  };
  const reloadLibrary = async () => {
    try { await window.ARCHHUB_REFRESH_NODE_LIBRARY?.(); }
    catch (_) { window.dispatchEvent(new CustomEvent('archhub:library-refresh')); }
  };
  React.useEffect(() => { call({action:'state'}).catch(error => setToast(window.AH_DS.errorText(error.message || String(error)))); }, []);
  const toggle = async row => {
    try {
      await call({action:'enable', id:row.id, enabled:!row.enabled});
      await reloadLibrary();
    } catch (error) {
      setToast(window.AH_DS.errorText(error.message || String(error)));
    }
  };
  const updateParam = async (row, key, value) => {
    try {
      await call({action:'param', id:row.id, param:key, value});
    } catch (error) {
      setToast(window.AH_DS.errorText(error.message || String(error)));
    }
  };
  const rows = state?.rows || [];
  if (typeof window.ARCHHUB_MODS !== 'function') return null;
  if (!state) return <SettingsEmpty role={toast ? 'alert' : 'status'}>{toast || 'Reading installed mods…'}</SettingsEmpty>;
  return <section data-settings-mods style={{
    border:`1px solid ${LM.line}`, borderRadius:LM.rad.md, background:LM.bgPanel,
    overflow:'hidden', color:LM.ink,
  }}>
    <div style={{display:'flex', alignItems:'center', gap:10, padding:'12px 12px', borderBottom:`1px solid ${LM.line}`}}>
      <div style={{width:20, height:20, display:'grid', placeItems:'center', borderRadius:5, background:LM.accent, color:LM.bg, fontSize:13}}>⌘</div>
      <div style={window.AH_DS.styles.fill}>
        <div style={{fontFamily:LM.sans, fontSize:20, lineHeight:1.1, fontWeight:700}}>Mods</div>
        <div style={{fontSize:13, color:LM.inkSoft}}>{state.built_in || 0} built in · {state.installed || 0} installed · {state.failed || 0} did not load</div>
      </div>
    </div>
    <div style={{padding:'10px 12px', display:'grid', gap:8}}>
      {rows.map(row => {
        const failed = row.status === 'failed';
        const tag = row.shipped ? 'built in'
          : row.tutorials?.length ? `${row.nodes?.length || 0} nodes · ${row.tutorials.length} tutorial` : row.author ? 'mine' : `${row.nodes?.length || 0} node`;
        return <div key={row.id} data-mod-row={row.status} style={{display:'grid', gridTemplateColumns:'12px 1fr auto', gap:8, alignItems:'center', position:'relative'}}>
          <span style={{width:8, height:8, borderRadius:8, background:failed ? LM.err : row.enabled ? LM.ok : LM.inkMuted}}/>
          <div style={{minWidth:0}}>
            <div style={{display:'flex', alignItems:'center', gap:6, minWidth:0}}>
              <span style={{fontSize:13, fontWeight:700, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{row.name}</span>
              <span style={{fontSize:13, color:LM.inkSoft, border:`1px solid ${LM.line}`, borderRadius:10, padding:'1px 6px'}}>{tag}</span>
              {row.fired_today > 0 && <span style={{fontSize:13, color:LM.inkSoft}}>fired {row.fired_today} times today</span>}
            </div>
            <div style={{fontSize:13, color:failed ? LM.err : LM.inkSoft, lineHeight:1.35}}>
              {failed ? String(row.error || '').split(/\r?\n/)[0] : row.description || (row.nodes || []).map(n => n.title).join(' and ')}
            </div>
            {(row.nodes || []).flatMap(n => Object.entries(n.params || {})).slice(0, 2).map(([k, v]) =>
              <span key={k} style={{fontSize:13, color:LM.ink, marginRight:10}}>{k.replace(/_/g, ' ')}: <input value={String(v)} onChange={event => updateParam(row, k, event.target.value)} style={{width:58, background:LM.bg, color:LM.ink, border:`1px solid ${LM.line}`, borderRadius:5, fontSize:13, padding:'2px 4px'}}/></span>)}
          </div>
          <window.AH_DS.Btn type="button" role="switch" aria-checked={!!row.enabled} onClick={() => toggle(row)} style={{
            width:34, height:18, border:0, borderRadius:18, background:row.enabled ? LM.accent : LM.inkMuted,
            padding:2, cursor:'pointer',
          }}><span style={{display:'block', width:14, height:14, borderRadius:14, background:LM.bg, marginLeft:row.enabled ? 16 : 0}}/></window.AH_DS.Btn>
        </div>;
      })}
      {toast && <div role="status" style={{fontSize:13, color:LM.inkSoft}}>{toast}</div>}
    </div>
  </section>;
};


const SettingsSystem = ({ graph, projection, onClose, onOpenToolGraph, onBackToSettings }) => {
  const count = systemGraphNodeCount(graph);
  const nodes = (graph?.nodes || []).filter(node => node.application === true);
  const pinnedCount = nodes.filter(node => node.pinned).length;
  const [openError, setOpenError] = React.useState('');
  const readAgain = async () => {
    const owner = window.ARCHHUB_STUDIO_AUTHORITY || window.ARCHHUB_EXISTING_WORKSHOP;
    if (typeof owner?.load === 'function') return owner.load();
    if (typeof owner?.refreshTopologyCanvas === 'function') return owner.refreshTopologyCanvas();
    return null;
  };
  const open = async () => {
    setOpenError('');
    const opened = await onOpenToolGraph?.('system');
    if (opened === false || !opened || opened.ok === false) {
      if (!opened?.stale) setOpenError(opened?.error || 'System graph is not admitted in this workspace.');
      return;
    }
    onClose?.();
  };
  const state = projection?.error ? 'error' : count === 0 ? 'empty' : pinnedCount ? 'refused' : '';
  return <div style={{display:'flex', flexDirection:'column', gap:14}}>
    <SHead title="System" sub="The application is itself a node. Its parts, tools and wiring are this graph; open it to inspect or change what you are permitted to."/>
    <SystemMiniGraph graph={graph}/>
    <div style={{display:'flex', alignItems:'center', gap:10}}>
      <div style={window.AH_DS.styles.fill}>
        <div style={{fontSize:13, color:LM.ink}}>ArchHub application <span style={{fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft}}>· {count} nodes · {(graph?.wires || []).length} relations · WIP head</span></div>
        <div style={{fontSize:11.5, color:LM.inkSoft, marginTop:4}}>Opens over this window in its own scope. Esc or the breadcrumb returns here, then to where you were. It is never a Studio session tab.</div>
      </div>
      <window.AH_DS.Btn primary onClick={open}>Open the System graph</window.AH_DS.Btn>
    </div>
    <SettingsMods/>
    {openError && <p role="status" style={{margin:0, color:LM.warn, fontSize:12.5}}>{openError}</p>}
    {state && <SystemGraphStates state={state} error={projection?.error || ''} pinnedCount={pinnedCount}
      movedCount={Math.max(0, count - pinnedCount)} onReadAgain={readAgain} onBackToSettings={onBackToSettings}
      onAddNode={open} onUnpinAndArrange={open}/>}
  </div>;
};
const SystemGraphStates = ({ state, error = '', pinnedCount = 0, movedCount = 0, onReadAgain, onBackToSettings, onAddNode, onUnpinAndArrange }) => (
  <window.AH_DS.EmptyState data-system-graph-states="" compact error={state==='error'}
    data-system-loading={state==='loading'?true:undefined} data-system-empty={state==='empty'?true:undefined}
    data-system-error={state==='error'?true:undefined} data-system-refused={state==='refused'?true:undefined}
    title={state==='loading'?'Reading the application graph…':state==='empty'?'This group has no nodes yet.':state==='refused'?`Arrange kept ${pinnedCount} pinned cards in place.`:'The application graph could not be read.'}
    detail={state==='error'?error || 'Nothing was changed. Your layout is kept.':state==='refused'?`Arrange moved ${movedCount}.`:undefined}
    action={<><window.AH_DS.Btn onClick={state==='empty'?onAddNode:state==='refused'?onUnpinAndArrange:onReadAgain} disabled={state==='loading'}>{state==='empty'?'Add node':state==='refused'?'Open System graph':'Read again'}</window.AH_DS.Btn>
      <window.AH_DS.Btn onClick={onBackToSettings}>Back to Settings</window.AH_DS.Btn></>}/>
);
const SettingsHub = ({ toolRows, onClose, onOpenTool, columns }) => {
  const [confirmOff, setConfirmOff] = React.useState(null);
  React.useEffect(() => {
    if (!confirmOff) return undefined;
    const timer = setTimeout(() => setConfirmOff(null), 6000);
    return () => clearTimeout(timer);
  }, [confirmOff]);
  const requestOff = tool => {
    if (tool.state === 'off') {
      tool.turnOn?.();
      return;
    }
    setConfirmOff(tool);
  };
  const openToolFromHub = id => {
    onClose?.();
    onOpenTool?.(id);
  };
  return <div style={{position:'relative'}}>
    <div data-tool-grid style={{ display:'grid', gap:8,
      gridTemplateColumns:columns ? `repeat(${columns}, minmax(0, 1fr))` : 'repeat(auto-fill, minmax(180px, 1fr))' }}>
      {toolRows.map(tool => <div key={tool.id} style={{display:'flex', minWidth:0}}
        onContextMenu={event => { event.preventDefault(); requestOff(tool); }}>
        <ToolCard tool={tool} onOpen={() => openToolFromHub(tool.id)}/>
      </div>)}
    </div>
    {confirmOff && <div data-tool-off-confirm={confirmOff.id} style={{
      position:'absolute', left:0, top:0, zIndex:8, width:232,
      background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.sm,
      padding:'8px 9px', color:LM.ink, fontFamily:LM.sans, fontSize:12,
      boxShadow:'0 12px 24px rgba(0,0,0,.22)',
    }}>
      <span>Switch {confirmOff.label} off? Tools asking it will see '{confirmOff.label} is off'. · </span>
      <window.AH_DS.Btn type="button" onClick={() => { confirmOff.turnOff?.(); setConfirmOff(null); }} style={window.AH_DS.styles.button("ghost", true)}>Yes</window.AH_DS.Btn>
      <span> · </span>
      <window.AH_DS.Btn type="button" onClick={() => setConfirmOff(null)} style={window.AH_DS.styles.button("ghost", true)}>No</window.AH_DS.Btn>
    </div>}
  </div>;
};
// ── Settings section header
const SHead = ({ title, sub, onClose, showClose = false }) => (
  <div style={{ marginBottom:14 }}>
    <div style={{ display:'flex', alignItems:'center', gap:12 }}>
      <div style={{ fontFamily:LM.serif, fontSize:22, letterSpacing:'-0.01em', flex:1 }}>{title}</div>
      {showClose && <window.AH_DS.Btn onClick={onClose} aria-label="Close" data-close-button style={{
        height:28, padding:'0 10px', border:`1px solid ${LM.line}`,
        background:'transparent', borderRadius:LM.rad.sm, cursor:'pointer',
        color:LM.inkSoft, fontFamily:LM.sans, fontSize:12, fontWeight:500,
      }}>Close</window.AH_DS.Btn>}
    </div>
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
  // Sharing is the owner's deliberate act on one fact (ADGR-0004): the brain files
  // it as a published skill; the founder review decides before any member sees it.
  const share = async m => {
    note(m.id, 'sharing\u2026');
    try {
      const said = await window.ARCHHUB_BRAIN_PUBLISH(m.id);
      note(m.id, !said || !said.ok ? ((said && said.error) || 'refused')
        : said.published ? 'shared \u2014 reviewed before other members see it'
        : 'waiting for your firm: ' + said.waiting);
    } catch (error) { note(m.id, 'refused'); }
  };

  return (
  <div>
    <SHead title="Brain" sub="Not a list of facts &#x2014; the layer that decides what kinds of things exist, how they relate and how they are filed. The top three strata are structure and can be shared; instances stay put."/>

    {/* A failed read is said once, above the strata, whatever facts are already on screen. */}
    {catalogue.error && !catalogue.loading && (
      <SettingsEmpty role="alert" action={<window.AH_DS.Btn onClick={catalogue.retry} style={{ ...window.AH_DS.styles.button("secondary", true), padding:'3px 9px', fontStyle:'normal' }}>read again</window.AH_DS.Btn>}>
        {/not answering/i.test(catalogue.error) ? 'Brain not answering. Nothing here is lost; read again when it is back.' : 'The brain was not read: ' + catalogue.error}
      </SettingsEmpty>
    )}
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
                  <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.05em', marginLeft:8 }}>{s.one}</span>
                </div>
                {on && <div style={{ fontSize:12, color:LM.inkSoft, lineHeight:1.5, marginTop:5 }}>{s.holds}</div>}
              </div>
              <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, letterSpacing:'0.1em', padding:'2px 7px', borderRadius:3,
                background: s.id === 'instances' ? LM.err + '1f' : s.col + '1c', color: s.id === 'instances' ? LM.err : s.col }}>
                {s.travels === 'freely' ? 'TRAVELS' : s.travels === 'on opt-in' ? 'OPT-IN' : 'STAYS'}
              </span>
              <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, minWidth:18, textAlign:'right' }}>{mine.length}</span>
              <span style={{ color:LM.inkSoft, fontSize:LM.fs.label.sz }}>{on ? '\u25be' : '\u25b8'}</span>
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
                          <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, letterSpacing:'0.1em', padding:'1px 6px', borderRadius:3, background:c.col + '1c', color:c.col }}>{c.label}</span>
                          <span role={said[f.id] ? 'status' : undefined} style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color: said[f.id] === 'refused' ? LM.err : LM.inkSoft, letterSpacing:'0.04em' }}>{said[f.id] || f.src}</span>
                        </div>
                      </div>
                      <span title="The ontology could not place this, so it defaults to sealed &#x2014; there is no release path at all."
                        style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.err, letterSpacing:'0.08em' }}>&#x2298; sealed</span>
                      {window.ARCHHUB_BRAIN_PUBLISH && (
                        <window.AH_DS.Btn title="Share this with the ArchHub community. It is reviewed before other members see it; a fact that names the client folder or a project code is refused."
                          onClick={() => share(f)}
                          style={{ ...window.AH_DS.styles.button("secondary", true), padding:'3px 8px' }}>share</window.AH_DS.Btn>
                      )}
                      <window.AH_DS.Btn title={'Forget: ' + f.text}
                        onClick={() => forget(f)}
                        style={{ ...window.AH_DS.styles.button("secondary", true), padding:'3px 8px', color:LM.err, borderColor:LM.lineSoft }}>forget</window.AH_DS.Btn>
                    </div>
                  );
                })}
                {mine.length === 0 && (
                  <div style={{ padding:`${LM.sp.md}px ${LM.sp.lg}px`, borderTop:`1px solid ${LM.lineSoft}`, fontFamily:LM.sans, fontSize:LM.fs.bodySm.sz, lineHeight:LM.fs.bodySm.ln + 'px', color:LM.inkSoft,
                    display:'flex', alignItems:'center', gap:LM.sp.md }}>
                    <span role={reading ? (catalogue.error ? 'alert' : 'status') : undefined} style={window.AH_DS.styles.fill}>
                      {!reading ? 'Nothing at this stratum yet.'
                        : catalogue.loading ? 'Reading the brain\u2026'
                        : 'Brain facts are unavailable. Try reading again.'}
                    </span>
                    {reading && catalogue.error && !catalogue.loading &&
                      <window.AH_DS.Btn onClick={catalogue.retry} style={{ ...window.AH_DS.styles.button("secondary", true), padding:'3px 9px', fontStyle:'normal' }}>read again</window.AH_DS.Btn>}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>

    {/* No "restore all": the brain has already forgotten these facts (ARCHHUB_BRAIN_FORGET), so
        un-hiding them here would show facts the brain no longer holds. */}
    {forgotten.length > 0 && (
      <div role="status" style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.06em', marginBottom:LM.sp.md }}>
        {forgotten.length} forgotten this session
      </div>
    )}

    {/* gates */}
    <div style={{ background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg, overflow:'hidden', marginBottom:LM.sp.md }}>
      <div onClick={() => setShowGates(!showGates)} style={{ display:'flex', alignItems:'center', gap:10, padding:'10px 14px', cursor:'pointer' }}>
        <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.12em' }}>GATES</span>
        <span style={{ flex:1, fontSize:12, color:LM.inkSoft }}>Four crossings, each with a decider and a way back. Nothing flows by default.</span>
        <span style={{ color:LM.inkSoft, fontSize:LM.fs.label.sz }}>{showGates ? '\u25be' : '\u25b8'}</span>
      </div>
      {showGates && gates.map(g => (
        <div key={g.id} style={{ padding:'10px 14px', borderTop:`1px solid ${LM.lineSoft}`, display:'flex', gap:LM.sp.md, alignItems:'flex-start' }}>
          <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, letterSpacing:'0.1em', color:LM.accent, minWidth:126 }}>{g.label}</span>
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
        <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.12em' }}>CONSENT RECORD</span>
        <span style={{ flex:1, fontSize:12, color:LM.inkSoft }}>
          {log.length ? `${log.length} crossing${log.length === 1 ? '' : 's'} this session \u00b7 append-only` : 'Nothing has crossed a gate yet.'}
        </span>
        <span style={{ color:LM.inkSoft, fontSize:LM.fs.label.sz }}>{showLog ? '\u25be' : '\u25b8'}</span>
      </div>
      {showLog && (log.length
        ? log.map((e, i) => (
            <div key={i} style={{ padding:'8px 14px', borderTop:`1px solid ${LM.lineSoft}`, display:'flex', gap:10, alignItems:'baseline', fontSize:12 }}>
              <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, minWidth:34 }}>{e.t}</span>
              <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, letterSpacing:'0.08em', minWidth:58,
                color: e.act === 'shared' ? LM.ok : e.act === 'withdrew' ? LM.warn : LM.err }}>{e.act.toUpperCase()}</span>
              <span style={{ flex:1, minWidth:0, color:LM.inkSoft, lineHeight:1.45 }}>{e.fact}</span>
              <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.06em' }}>{e.gate}</span>
            </div>
          ))
        : <div style={{ padding:`${LM.sp.md}px ${LM.sp.lg}px`, borderTop:`1px solid ${LM.lineSoft}`, fontFamily:LM.sans, fontSize:LM.fs.bodySm.sz, lineHeight:LM.fs.bodySm.ln + 'px', color:LM.inkSoft }}>
            Share or withdraw a fact above and it appears here. The record cannot be edited, only exported.
          </div>)}
    </div>

    {/* keys + export */}
    <div style={{ padding:'11px 13px', background:LM.bg, border:`1px solid ${LM.lineSoft}`, borderRadius:LM.rad.md, marginBottom:LM.sp.sm }}>
      <div style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.12em', marginBottom:7 }}>KEY</div>
      <div style={{ fontSize:12, color:LM.inkSoft, lineHeight:1.6 }}>{keys.how}</div>
      <div style={{ fontSize:12, color:LM.inkSoft, lineHeight:1.6, marginTop:7 }}>{keys.cost}</div>

      {/* The login-wrapped key is proposed, not shipped: no recovery kit or rotation control is
          drawn until one exists (the old buttons only toggled this sentence). */}
      <div role="status" style={{ marginTop:9, fontSize:12, color:LM.inkSoft, lineHeight:1.6 }}>
        No recovery kit or wrapped login key exists in this build.
      </div>
    </div>
    <div style={{ padding:'10px 12px', background:LM.bg, border:`1px solid ${LM.lineSoft}`, borderRadius:LM.rad.md }}>
      <div style={{ display:'flex', alignItems:'center', gap:10, flexWrap:'wrap' }}>
        <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.12em' }}>EXPORT</span>
        <span style={{ flex:1, fontSize:12, color:LM.inkSoft, minWidth:180 }}>Take the whole brain with you &#x2014; strata, facts, consent record.</span>
        <window.AH_DS.Btn onClick={async (e) => {
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
        }} style={window.AH_DS.styles.button("secondary", true)}>export</window.AH_DS.Btn>
        <window.AH_DS.Btn onClick={(e) => {
          // Forgetting everything is not a button press away. The brain
          // is the founder's memory; erasing it needs the real path, in
          // the folder, with his own hands.
          const b = e.currentTarget;
          b.textContent = 'open the folder to remove it';
          window.ARCHHUB_REVEAL?.('brain');
          setTimeout(() => { b.textContent = 'forget all'; }, 6000);
        }} style={{ ...window.AH_DS.styles.button("secondary", true), color:LM.err }}>forget all</window.AH_DS.Btn>
      </div>
    </div>
  </div>
  );
};

// -- Team: identity, seats, invites. There is no member/invite route in the current cloud client,
// so the only roster fact drawn here is the signed-in account the app already holds.
const SettingsTeam = ({ account, onAccount }) => {
  const signedIn = !!account?.signedIn;
  const email = String(account?.email || '');
  const name = String(account?.name || '') || (email ? email.split('@')[0] : '');
  return (
  <div>
    <SHead title="Team" sub="The signed-in workspace owner and their account settings."/>
    <div style={{ background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg, overflow:'hidden', marginBottom:LM.sp.sm }}>
      {!signedIn && <div role="status" style={{ padding:'12px 14px', display:'flex', alignItems:'center', gap:10 }}>
        <span style={{ flex:1, minWidth:0, fontFamily:LM.sans, fontSize:LM.fs.bodySm.sz, lineHeight:LM.fs.bodySm.ln + 'px', color:LM.inkSoft }}>Sign in to see your team</span>
        <window.AH_DS.Btn type="button" onClick={onAccount} style={{...window.AH_DS.styles.button(true ? 'primary' : 'secondary', true), padding:'4px 10px'}}>Sign in</window.AH_DS.Btn>
      </div>}
      {signedIn && <div style={{ padding:'12px 14px', display:'grid', gridTemplateColumns:'minmax(0,1fr) auto', gap:12, alignItems:'center' }}>
        <div style={{ minWidth:0 }}>
          <div style={{ fontSize:13.5, color:LM.ink, fontWeight:500 }}>{name || email}</div>
          <div style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, marginTop:3, overflowWrap:'anywhere' }}>{email}</div>
        </div>
        <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, padding:'2px 7px', borderRadius:LM.rad.xs, background:LM.accentSoft, color:LM.accent, letterSpacing:'0.08em', textTransform:'uppercase' }}>Owner</span>
      </div>}
    </div>
    <div style={{ marginTop:LM.sp.md, padding:'10px 12px', background:LM.bg, border:`1px solid ${LM.lineSoft}`, borderRadius:LM.rad.md }}>
      <div style={{ display:'flex', alignItems:'center', gap:10 }}>
        <div style={{ flex:1, minWidth:0, fontSize:12, color:LM.inkSoft, lineHeight:1.6 }}>
          Manage your account.
        </div>
        {signedIn && <window.AH_DS.Btn type="button" onClick={onAccount} style={{...window.AH_DS.styles.button("secondary", true), padding:'4px 10px'}}>Manage account</window.AH_DS.Btn>}
      </div>
    </div>
  </div>
  );
};// ── Profile: who you are, the AI's system prompt anchor
const SettingsProfile = () => (
  <div>
    <SHead title="Profile" sub="Who the app says you are, and the standing instruction agents read from your brain."/>
    <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:14 }}>
      {/* The signed-in account, never an invented person. Discipline, units, standard, languages
          and timezone were drawn as dropdowns with invented values and no store; removed 2026-09-24. */}
      <SField label="Display name" value={(() => { const a = (typeof acLoad === 'function' && acLoad()) || {}; return a.name || (a.email ? String(a.email).split('@')[0] : '—'); })()}/>
      <SField label="Studio / firm" value={(() => { const a = (typeof acLoad === 'function' && acLoad()) || {}; return a.firm || (window.ARCHHUB_LIVE && window.ARCHHUB_LIVE.firm) || '—'; })()}/>
    </div>
    <div style={{ marginTop:LM.sp.lg }}>
      <div style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.14em', marginBottom:6 }}>STANDING INSTRUCTION</div>
      <div style={{ fontSize:12, color:LM.inkSoft, lineHeight:1.55 }}>
        Saved as a brain fact that begins with SYSTEM PROMPT. Preview asks the current session which instruction it is working under.
      </div>
      <div style={{ display:'flex', gap:6, marginTop:LM.sp.sm }}>
        <window.AH_DS.Btn onClick={async (e) => {
          const said = window.prompt('The instruction every agent inherits');
          if (!said || !said.trim()) return;
          const b = e.currentTarget;
          b.textContent = 'saving…';
          try {
            await window.ARCHHUB_REMEMBER('SYSTEM PROMPT: ' + said.trim());
            b.textContent = 'saved to the brain';
          } catch (error) { b.textContent = 'refused'; }
          setTimeout(() => { b.textContent = 'edit raw prompt'; }, 5000);
        }} style={window.AH_DS.styles.button("secondary", true)}>edit raw prompt</window.AH_DS.Btn>
        <window.AH_DS.Btn onClick={async (e) => {
          const b = e.currentTarget;
          b.textContent = 'asking…';
          try {
            const answer = await window.ARCHHUB_AGENT(
              'In one sentence, state the standing instruction you are working under.');
            b.textContent = agentAnswerText(answer).slice(0, 48);
          } catch (error) { b.textContent = 'refused'; }
          setTimeout(() => { b.textContent = 'preview with this session'; }, 8000);
        }} style={window.AH_DS.styles.button("secondary", true)}>preview with this session</window.AH_DS.Btn>
      </div>
    </div>
  </div>
);

const SField = ({ label, value }) => (
  <div>
    <div style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, letterSpacing:'0.1em', marginBottom:LM.sp.xs }}>{label.toUpperCase()}</div>
    <div style={{
      padding:'7px 10px', background:LM.bg, border:`1px solid ${LM.line}`,
      borderRadius:LM.rad.sm, fontSize:12.5, color:LM.ink, display:'flex', alignItems:'center', gap:6,
    }}>
      <span style={window.AH_DS.styles.fill}>{value}</span>
    </div>
  </div>
);

const SettingsPermissions = ({ account, onTab, compact=false }) => {
  const transport = window.ARCHHUB_EXISTING_WORKSHOP;
  const [rows, setRows] = React.useState([]);
  const [busy, setBusy] = React.useState('');
  const [message, setMessage] = React.useState('');
  const hasPermissionBackend = !!transport?.readSettingsPermissionRows;
  const readRows = React.useCallback(() => {
    let alive = true;
    setMessage('');
    if (!hasPermissionBackend) {
      setRows([]);
      return () => { alive = false; };
    }
    transport.readSettingsPermissionRows().then(next => {
      if (!alive) return;
      setRows((Array.isArray(next) ? next : []).map(row => ({
        ...row,
        read:String(row.read || 'Ask').replace(/^./, c => c.toUpperCase()),
        write:String(row.write || 'Ask').replace(/^./, c => c.toUpperCase()),
        send:String(row.send || 'Ask').replace(/^./, c => c.toUpperCase()),
      })));
    }).catch(error => {
      if (alive) setMessage(error.message || 'Permission store unavailable.');
    });
    return () => { alive = false; };
  }, [transport, hasPermissionBackend]);
  React.useEffect(() => readRows(), [readRows]);
  const change = async (index, col, value) => {
    const row = rows[index];
    if (!row || busy) return;
    if (!hasPermissionBackend || !transport?.setSettingsPermission) {
      setMessage('Per-agent permissions: Unavailable');
      return;
    }
    const next = rows.map((item, idx) => idx === index ? {...item, [col.toLowerCase()]:value} : item);
    setRows(next);
    setBusy(row.actor + col); setMessage('');
    try {
      await transport.setSettingsPermission({actor:row.actor, column:col.toLowerCase(), value});
    } catch (error) {
      setRows(rows);
      setMessage(error.message || 'Permission change was not saved.');
    } finally { setBusy(''); }
  };
  const writable = hasPermissionBackend && !!transport?.setSettingsPermission;
  return (
  <div style={{ fontFamily:LM.sans }}>
    <div style={{ padding:'8px 12px', borderBottom:`1px solid ${LM.lineSoft}`, fontSize:13, color:LM.ink }}>Writes always ask unless you allow them</div>
    {typeof window !== 'undefined' && window.CloudPublishConsent && <div style={{ padding:'10px 12px', borderBottom:`1px solid ${LM.lineSoft}` }}>
      <window.CloudPublishConsent signedIn={!!account?.signedIn}/>
    </div>}
    {typeof SettingsConnectedSocialAccounts !== 'undefined' && <div style={{ padding:'10px 12px', borderBottom:`1px solid ${LM.lineSoft}` }}>
      <SettingsConnectedSocialAccounts transport={transport}/>
    </div>}
    {typeof SettingsSocialApprovals !== 'undefined' && <div style={{ padding:'10px 12px', borderBottom:`1px solid ${LM.lineSoft}` }}>
      <SettingsSocialApprovals transport={transport}/>
    </div>}
    {hasPermissionBackend && <div style={{ display:'grid', gridTemplateColumns:'minmax(0, 1fr) repeat(3, auto)', gap:8, alignItems:'center',
      padding:'6px 12px', borderBottom:`1px solid ${LM.lineSoft}`, fontSize:11, color:LM.inkSoft }}>
      <span>Actor</span><span>Read</span><span>Write</span><span>Send</span>
    </div>}
    {message && <div role="alert" style={{ display:'flex', alignItems:'center', gap:8, padding:'8px 12px', color:LM.err, fontSize:12, borderBottom:`1px solid ${LM.lineSoft}` }}>
      <span style={{ flex:1, minWidth:0, overflowWrap:'anywhere' }}>{message}</span>
      {hasPermissionBackend && <window.AH_DS.Btn type="button" onClick={readRows} style={({...window.AH_DS.styles.button('secondary', true), borderColor:false ? LM.accent : LM.line, ...{background:LM.bgHover, color:LM.ink}})}>Retry</window.AH_DS.Btn>}
    </div>}
    {hasPermissionBackend && rows.map((row, index) => <div key={row.actor + index} data-permission-row="" style={{ display:'grid',
      gridTemplateColumns:'minmax(0, 1fr) repeat(3, auto)', gap:8, alignItems:'center', minHeight:32,
      padding:'4px 12px', borderTop:index ? `1px solid ${LM.lineSoft}` : 'none' }}>
      <span style={{ minWidth:0 }}>
        <span style={{ display:'block', fontSize:13, color:LM.ink, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis' }}>{row.actor}</span>
        <span style={{ display:'block', fontSize:11, color:LM.inkSoft }}>{row.kind === 'agent' ? 'Agent app' : 'Connection'}</span>
      </span>
      {['Read', 'Write', 'Send'].map(col => <span key={col} data-permission-col={col}>
        <Settings54Seg value={row[col.toLowerCase()] || 'Ask'} onChange={value => change(index, col, value)}
          ariaLabel={row.actor + ' ' + col} disabled={!writable || busy === row.actor + col}/>
      </span>)}
    </div>)}

  </div>
  );
};

// ── Providers (design studio-lm.jsx:2895-2933). The rows are the provider registry's: a cloud
// provider is keyed or has no key, a local runtime is running or not. The registry never returns a
// key, so the key slot is masked and nothing can reveal it, and there is no spend figure because
// nothing on this machine measures one. The swatch identifies the vendor, as he drew it.
const BRAND = { openrouter: '#3a6acc', cloud: '#cc785c', ollama: '#1a8a4a', lmstudio: '#4285f4', openai: '#10a37f', google: '#4285f4', anthropic: '#cc785c' };
// Providers whose key is pasted here (model_router.KEYED_IN_SETTINGS).
const KEY_LABEL = { openrouter: 'OpenRouter', openai: 'OpenAI', google: 'Google', anthropic: 'Anthropic' };
const cleanDetail = text => String(text || '')
  .replace(/\b[A-Z][A-Z0-9_]{2,}\b/g, '')
  .replace(/\b(?:127\.0\.0\.1|localhost):\d+\b/g, '')
  .replace(/:\d{3,5}\b/g, '')
  .replace(/\b[\w.-]+\.(?:py|ps1|cjs|mjs|js|json|exe|bat)\b/gi, '')
  .replace(/\bcourt\b/gi, 'review')
  .replace(/\s*[·,;:]\s*[·,;:]\s*/g, ' · ')
  .replace(/\s{2,}/g, ' ')
  .replace(/^[\s·,;:-]+|[\s·,;:-]+$/g, '')
  .slice(0, 60);
const providerDetail = p => {
  if (p.id === 'cloud') return 'Sign in to use ArchHub cloud';
  if (p.state === 'keyed') return 'Connected on this machine';
  if (p.state === 'key invalid') return 'Not reachable from this machine \u00b7 check the key in Manage';
  if (p.state === 'running') return 'Connected on this machine';
  if (p.state === 'not running') return 'Not connected on this machine';
  if (p.state === 'not installed') return 'Unavailable on this machine';
  return providerStateWord(p);
};
const hostDetail = h => {
  const id = String(h.id || '').toLowerCase(), name = String(h.name || '').toLowerCase();
  if (name.includes('3ds max') || id.includes('3ds')) return 'Start 3ds Max from ArchHub when needed';
  if (name.includes('rhino') || id.includes('rhino')) return 'Start Rhino from ArchHub when needed';
  if (name.includes('blender') || id.includes('blender')) return 'Start Blender from ArchHub when needed';
  if (name.includes('speckle') || id.includes('speckle')) return h.state === 'absent' ? 'Manager not found' : 'Ready to publish with stored account';
  const said = String(h.detail || '');
  const sessions = /^(\d+) session\(s\)$/i.exec(said.trim());
  if (sessions) return sessions[1] === '1' ? '1 session open' : sessions[1] + ' sessions open';
  if (/open a file and the reads answer/i.test(said)) return 'installed \u00b7 reads when a file is open';
  if (/open Outlook and the inbox reads answer/i.test(said)) return 'installed \u00b7 reads the inbox when Outlook is open';
  if (/^no session listening\b/i.test(said)) return hostOpenPhrase(h) ? 'Not open \u00b7 Start opens it' : 'Not open';
  if (h.detail) return cleanDetail(h.detail);
  if (h.file && h.file !== '\u2014') return cleanDetail(h.file);
  return hostStateWord(h);
};
const hostStartName = h => {
  const id = String(h?.id || '').toLowerCase(), name = String(h?.name || '').toLowerCase();
  if (name.includes('3ds max') || id.includes('3ds')) return '3ds Max';
  if (name.includes('autocad') || id.includes('acad')) return 'AutoCAD';
  if (name.includes('revit') || id.includes('revit') || /^r\d{2}$/.test(id)) return 'Revit';
  if (name.includes('rhino') || id.includes('rhino')) return 'Rhino';
  if (name.includes('blender') || id.includes('blender')) return 'Blender';
  return '';
};
const hostOpenPhrase = h => {
  const name = hostStartName(h);
  return name ? 'open ' + name : '';
};
const hostDisplayName = h => hostStartName(h) || h?.name || h?.id || 'Host';
const HOST_STARTERS = [
  {id:'known-revit', name:'Revit', state:'off', file:'\u2014'},
  {id:'known-autocad', name:'AutoCAD', state:'off', file:'\u2014'},
  {id:'known-rhino', name:'Rhino', state:'off', file:'\u2014'},
  {id:'known-blender', name:'Blender', state:'off', file:'\u2014'},
  {id:'known-3ds-max', name:'3ds Max', state:'off', file:'\u2014'},
];
const startableHosts = hosts => {
  const byName = new Map();
  for (const host of [...(hosts || []), ...HOST_STARTERS]) {
    const name = hostStartName(host);
    if (name && !byName.has(name)) byName.set(name, {...host, name:host.name || name});
  }
  return [...byName.values()];
};

// Posts waiting for the founder (social_approval): the exact request an agent prepared,
// then his own Approve or Deny. Nothing is posted until he approves.
const SettingsSocialApprovals = ({transport}) => {
  const alive = React.useRef(true), timer = React.useRef(null);
  const [items, setItems] = React.useState([]), [busy, setBusy] = React.useState(''), [message, setMessage] = React.useState('');
  const load = React.useCallback(async () => {
    if (!transport?.listSocialApprovals) return;
    try { const next = await transport.listSocialApprovals(); if (alive.current) setItems(next); }
    catch (error) { if (alive.current) setMessage(error.message); }
    if (alive.current) timer.current = setTimeout(load, 5000);
  }, [transport]);
  React.useEffect(() => { alive.current = true; load(); return () => { alive.current = false; clearTimeout(timer.current); }; }, [load]);
  const decide = async (item, decision) => {
    setBusy(item.delegation); setMessage('');
    try {
      await transport.decideSocialApproval({delegation:item.delegation, input_digest:item.input_digest, decision});
      if (alive.current) { setMessage(decision === 'approve' ? 'Approved. The agent can post it once.' : 'Denied. It will not be posted.');
        setItems(items.filter(other => other.delegation !== item.delegation)); }
    } catch (error) { if (alive.current) setMessage(error.message); throw error; }
    finally { if (alive.current) setBusy(''); }
  };
  const providerName = item => {
    const operation = String(item.operation || '');
    if (operation.startsWith('instagram.')) return 'Instagram';
    if (operation.startsWith('facebook.')) return 'Facebook';
    if (operation.startsWith('linkedin.')) return 'LinkedIn';
    if (operation.startsWith('whatsapp.')) return 'WhatsApp Business';
    if (operation.startsWith('x.')) return 'X';
    if (operation.startsWith('tiktok.')) return 'TikTok';
    return 'provider';
  };
  if (!transport?.listSocialApprovals || (!items.length && !message)) return null;
  return <div style={{padding:'12px 14px', background:LM.bg, border:`1px solid ${LM.accent || LM.line}`, borderRadius:LM.rad.lg, marginBottom:10}}>
    <div style={{fontSize:13, fontWeight:500}}>Posts waiting for your approval</div>
    {items.map(item => <div key={item.delegation} style={{marginTop:10}}>
      <div style={{fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft}}>{item.operation} · {item.account_id} · {
        item.account_binding === 'provider-verified' ? 'account confirmed by ' + providerName(item)
          : item.account_binding === 'operator-declared' ? 'account typed in, not confirmed' : 'account not checked'}</div>
      {window.ARCHHUB_APPROVAL_CARD && React.createElement(window.ARCHHUB_APPROVAL_CARD, {
        surface:'social',approveLabel:'Approve',approval:{...item,id:item.delegation,state:'needs-user',title:'Post to ' + providerName(item),
          host:providerName(item),target:item.account_id,scope:item.scope || item.operation,
          preview:{kind:'post',text:item.review_text}},busy:!!busy,
        canApprove:typeof transport?.decideSocialApproval === 'function',canDecline:typeof transport?.decideSocialApproval === 'function',
        onApprove:() => decide(item,'approve'),onDecline:() => decide(item,'deny')})}
    </div>)}
    {message && <p role="status" style={{fontSize:12, overflowWrap:'anywhere'}}>{message}</p>}
  </div>;
};

const socialAccountView = account => {
  const vault = String(account?.vault_entry || '');
  const provider = String(account?.provider || '').toLowerCase();
  if (provider === 'linkedin') return {icon:'in', name:'LinkedIn'};
  if (vault.startsWith('social-meta-page-')) return {icon:'f', name:'Facebook Page'};
  if (vault.startsWith('social-meta-ig-')) return {icon:'ig', name:'Instagram'};
  if (provider === 'meta') return {icon:'m', name:'Meta'};
  return {icon:'•', name:provider ? provider[0].toUpperCase() + provider.slice(1) : 'Social'};
};

const SettingsConnectedSocialAccounts = ({transport}) => {
  const alive = React.useRef(true);
  const [accounts, setAccounts] = React.useState([]), [busy, setBusy] = React.useState(''), [message, setMessage] = React.useState('');
  const load = React.useCallback(async () => {
    if (!transport?.listLocalSocialAccounts) return;
    try { const next = await transport.listLocalSocialAccounts(); if (alive.current) setAccounts(Array.isArray(next) ? next : []); }
    catch (error) { if (alive.current) setMessage(error.message); }
  }, [transport]);
  React.useEffect(() => { alive.current = true; load(); return () => { alive.current = false; }; }, [load]);
  const disconnect = async account => {
    const key = [account.provider, account.account_id, account.vault_entry].join('|');
    setBusy(key); setMessage('');
    try {
      await transport.removeLocalSocialAccount({
        provider:account.provider, account_id:account.account_id, vault_entry:account.vault_entry});
      if (alive.current) {
        setAccounts(accounts.filter(row => row.provider !== account.provider || row.account_id !== account.account_id || row.vault_entry !== account.vault_entry));
        setMessage('Disconnected local credential.');
      }
    } catch (error) { if (alive.current) setMessage(error.message); }
    finally { if (alive.current) setBusy(''); }
  };
  if (!transport?.listLocalSocialAccounts || accounts.length === 0) return null;
  return <div style={{padding:'12px 14px', background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg, marginBottom:10}}>
    <div style={{fontSize:13, fontWeight:500}}>Connected accounts</div>
    <div style={{display:'flex', flexDirection:'column', gap:6, marginTop:10}}>
      {accounts.map(account => {
        const view = socialAccountView(account);
        const key = [account.provider, account.account_id, account.vault_entry].join('|');
        const display = account.display_name || account.name || account.username || account.account_id;
        return <div key={key} style={{display:'grid', gridTemplateColumns:'auto minmax(0,1fr) auto', gap:10, alignItems:'center',
          padding:'8px 10px', border:`1px solid ${LM.lineSoft}`, borderRadius:LM.rad.md}}>
          <span aria-hidden="true" style={{width:24, height:24, borderRadius:'50%', display:'inline-flex', alignItems:'center', justifyContent:'center',
            background:LM.lineSoft, color:LM.ink, fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, textTransform:'uppercase'}}>{view.icon}</span>
          <span style={{minWidth:0}}>
            <span style={{display:'block', fontSize:12.5, fontWeight:500}}>{view.name}</span>
            <span style={{display:'block', fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, color:LM.inkSoft, overflowWrap:'anywhere'}}>{display || account.vault_entry}</span>
          </span>
          <window.AH_DS.Btn type="button" disabled={!!busy || !transport?.removeLocalSocialAccount} onClick={() => disconnect(account)} style={window.AH_DS.styles.button("secondary", true)}>
            Disconnect
          </window.AH_DS.Btn>
        </div>;
      })}
    </div>
    {message && <p role="status" style={{fontSize:12, overflowWrap:'anywhere'}}>{message}</p>}
  </div>;
};

const SocialConnectionRow = ({icon, name, detail, control}) => (
  <div style={{display:'grid', gridTemplateColumns:'24px minmax(0,1fr) auto', alignItems:'center', gap:10,
    padding:'10px 0', borderTop:`1px solid ${LM.lineSoft}`}}>
    <span style={{width:24, height:24, borderRadius:LM.rad.sm, background:LM.bgSoft, color:LM.ink,
      display:'grid', placeItems:'center', fontFamily:LM.mono, fontSize:11, fontWeight:700}}>{icon}</span>
    <div style={{minWidth:0}}>
      <div style={{fontSize:13, fontWeight:500}}>{name}</div>
      <div style={{fontSize:11.5, color:LM.inkSoft, lineHeight:1.35}}>{detail}</div>
    </div>
    {control}
  </div>
);

const MCP_CLIENT_TARGETS = {
  notion: {name:'Notion', icon:'N', button:'Add ArchHub to Notion',
    fallback:'https://www.notion.so/profile/connections'},
  gemini: {name:'Gemini', icon:'G', button:'Add ArchHub to Gemini',
    fallback:'https://gemini.google.com/settings/connected-apps'},
};

const SettingsMcpClientRow = ({provider}) => {
  const target = MCP_CLIENT_TARGETS[provider];
  const transport = window.ARCHHUB_EXISTING_WORKSHOP;
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState('');
  const [failed, setFailed] = React.useState(false);
  const connect = async (mode = 'client') => {
    setBusy(true); setMessage(''); setFailed(false);
    try {
      if (mode === 'workspace') {
        if (!transport?.connectNotion) throw new Error('Notion workspace sign-in is unavailable in this Studio session.');
        const result = await transport.connectNotion();
        setMessage(result.label || 'Notion sign-in opened.'); return;
      } else if (transport?.installMcpClient) {
        await transport.installMcpClient(provider);
      } else if (typeof window.open === 'function') {
        window.open(target.fallback, '_blank', 'noopener,noreferrer');
      } else {
        throw new Error(target.name + ' connection is unavailable in this Studio session.');
      }
      setMessage(target.name + ' opened.');
    } catch (error) {
      setFailed(true); setMessage(error?.message || target.name + ' connection was refused.');
    } finally { setBusy(false); }
  };
  return <SocialConnectionRow icon={target.icon} name={target.name} detail="ArchHub remote MCP"
    control={<div style={{display:'flex', flexDirection:'column', alignItems:'flex-end', gap:6}}>
      <window.AH_DS.Btn type="button" disabled={busy} onClick={() => connect()} style={window.AH_DS.styles.button(true ? 'primary' : 'secondary', true)}>
        {busy ? 'Opening...' : target.button}
      </window.AH_DS.Btn>
      {provider === 'notion' && <window.AH_DS.Btn type="button" disabled={busy || !transport?.connectNotion} onClick={() => connect('workspace')} style={window.AH_DS.styles.button("secondary", true)}>Connect Notion</window.AH_DS.Btn>}
      {message && <span role={failed ? 'alert' : 'status'} style={{fontSize:11.5, color:failed ? LM.err : LM.ok, maxWidth:240, textAlign:'right'}}>{message}</span>}
    </div>}/>;
};

const SOCIAL_NETWORKS = [
  {provider:'instagram', name:'Instagram', icon:'◎'},
  {provider:'facebook', name:'Facebook', icon:'f'},
  {provider:'linkedin', name:'LinkedIn', icon:'in'},
  {provider:'whatsapp', name:'WhatsApp Business', icon:'◉'},
  {provider:'x', name:'X', icon:'𝕏'},
  {provider:'tiktok', name:'TikTok', icon:'♪'},
];

const SocialProviderConnection = ({network, initial, transport}) => {
  const [row, setRow] = React.useState(initial);
  const alive = React.useRef(true), generation = React.useRef(0), timer = React.useRef(null);
  React.useEffect(() => { alive.current = true; return () => { alive.current = false; generation.current++; clearTimeout(timer.current); }; }, []);
  const fail = (error, fence) => {
    if (alive.current && generation.current === fence) setRow(previous => ({...previous,state:'blocked',can_connect:true,blocker:error?.message || 'Cloud connection status unavailable'}));
  };
  const accept = async (next, fence) => {
    if (!alive.current || generation.current !== fence) return;
    if (!next?.state) throw new Error('Cloud connection status unavailable');
    setRow(previous => ({...previous,...next}));
    const accounts = next.accounts || [];
    if (next.state === 'ready' || (next.state === 'choosing' && accounts.length === 1)) {
      const account = accounts[0];
      const saved = await transport.finishSocialConnection(network.provider,account ? account.account_id || account.id : undefined);
      if (alive.current && generation.current === fence) setRow(previous => ({...previous,...saved}));
    } else if (next.state === 'connecting') {
      timer.current = setTimeout(() => poll(fence), 1500);
    }
  };
  const poll = async fence => {
    try { await accept(await transport.socialConnectionStatus(network.provider),fence); }
    catch (error) { fail(error,fence); }
  };
  const connect = async () => {
    const fence = ++generation.current;
    clearTimeout(timer.current);
    setRow(previous => ({...previous,state:'connecting',blocker:''}));
    try {
      const started = await transport.startSocialConnection(network.provider);
      await accept(started,fence);
      if (started.state === 'connecting' && alive.current && generation.current === fence) {
        clearTimeout(timer.current); await poll(fence);
      }
    } catch (error) { fail(error,fence); }
  };
  const choose = async account => {
    const fence = ++generation.current;
    setRow(previous => ({...previous,state:'connecting'}));
    try { await accept(await transport.finishSocialConnection(network.provider,account.account_id || account.id),fence); }
    catch (error) { fail(error,fence); }
  };
  const cancel = async () => {
    const fence = ++generation.current;
    clearTimeout(timer.current);
    try { await accept(await transport.cancelSocialConnection(network.provider),fence); }
    catch (error) { fail(error,fence); }
  };
  React.useEffect(() => {
    const fence = ++generation.current;
    clearTimeout(timer.current); setRow(initial);
    if (initial.state === 'connecting') poll(fence);
    else if (initial.state === 'ready' || (initial.state === 'choosing' && initial.accounts?.length === 1)) {
      accept(initial,fence).catch(error => fail(error,fence));
    }
  }, [initial,transport]);
  const pending = row.state === 'connecting' || row.state === 'choosing' || row.state === 'ready';
  const blocked = row.state === 'blocked' && !row.can_connect;
  const label = row.state === 'connected' ? 'Reconnect' : row.state === 'connecting' ? 'Connecting…' : 'Connect';
  const rawName = row.username || row.display_name;
  const displayName = rawName && rawName !== row.account_id && ['instagram','x'].includes(network.provider) && !rawName.startsWith('@') ? '@'+rawName : rawName;
  const waitingReview = row.publish_blocker || (row.review_state && row.review_state !== 'approved');
  const status = row.state === 'connected' ? 'Connected as ' + (displayName || 'provider-confirmed account')
    : row.state === 'connecting' ? 'Connecting… Finish in the provider window.'
    : row.state === 'choosing' ? 'Choose your account' : row.state === 'loading' ? 'Reading connection status…'
    : row.state === 'blocked' ? '' : 'Not connected';
  return <div data-social-provider={network.provider} data-social-name={network.name}>
    <SocialConnectionRow icon={network.icon} name={network.name}
      detail={<span><span role="status" style={{display:'block',color:row.state === 'connected' ? LM.ok : LM.inkSoft}}>{status}</span>
        {waitingReview && <span role="status" style={{display:'block',marginTop:3,color:LM.inkSoft}}>Waiting for {network.name} approval</span>}
        {(row.blocker || row.publish_blocker) && <span role="status" style={{display:'block',marginTop:3,color:LM.inkSoft,overflowWrap:'anywhere'}}>{row.blocker || row.publish_blocker}</span>}</span>}
      control={<div style={{display:'flex',flexDirection:'column',gap:6,alignItems:'flex-end'}}>
        <window.AH_DS.Btn type="button" onClick={connect} disabled={pending || blocked || row.state === 'loading'}
          title={(row.blocker && blocked ? row.blocker + ' · ' : '') + 'Connect ' + network.name + ' · Ctrl+K / Enter'}
          aria-label={label + ' ' + network.name} style={{...window.AH_DS.styles.button(!blocked ? 'primary' : 'secondary', true),minWidth:94}}>{label}</window.AH_DS.Btn>
        {pending && <window.AH_DS.Btn type="button" onClick={cancel} title={'Cancel '+network.name+' sign-in · Ctrl+K / Enter'} style={window.AH_DS.styles.button("secondary", true)}>Cancel</window.AH_DS.Btn>}
        {row.state === 'choosing' && (row.accounts || []).map(account => <window.AH_DS.Btn type="button" key={account.account_id || account.id}
          onClick={() => choose(account)} title={'Use '+(account.name || account.display_name)+' · Ctrl+K / Enter'} style={window.AH_DS.styles.button(true ? 'primary' : 'secondary', true)}>Use {account.name || account.display_name}</window.AH_DS.Btn>)}
      </div>}/>
  </div>;
};

const SettingsConnections = ({transport = window.ARCHHUB_EXISTING_WORKSHOP}) => {
  const [rows,setRows] = React.useState(null), [error,setError] = React.useState('');
  React.useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        if (!transport?.listSocialConnections) throw new Error('ArchHub cloud connection broker unavailable');
        const next = await transport.listSocialConnections();
        if (!Array.isArray(next)) throw new Error('Cloud connection status unavailable');
        if (active) setRows(next);
      } catch (failure) { if (active) setError(failure.message || 'Cloud connection status unavailable'); }
    };
    load(); return () => { active = false; };
  }, [transport]);
  return <section aria-label="Connections" style={{display:'flex',flexDirection:'column',gap:14,maxWidth:850}}>
    <div><div style={{fontFamily:LM.serif,fontSize:22,letterSpacing:'-0.01em'}}>Connections</div>
      <p style={{fontSize:12,color:LM.inkSoft,lineHeight:1.5,margin:'6px 0 0'}}>Your accounts, connected through each provider's own sign-in. Agents draft; you approve every send.</p></div>
    <div style={{padding:`${LM.sp.md}px ${LM.sp.lg}px`,background:LM.bg,border:`1px solid ${LM.line}`,borderRadius:LM.rad.lg}}>
      {SOCIAL_NETWORKS.map(network => <SocialProviderConnection key={network.provider} network={network} transport={transport}
        initial={rows?.find(row => row.provider === network.provider) || {provider:network.provider,state:error || rows ? 'blocked' : 'loading',blocker:error || (rows ? network.name + ' cloud connection status unavailable' : '')}}/>)}
    </div>
    <SettingsSocialApprovals transport={transport}/>
    <div style={{padding:`${LM.sp.md}px ${LM.sp.lg}px`,background:LM.bg,border:`1px solid ${LM.line}`,borderRadius:LM.rad.lg}}>
      <div style={{fontSize:12,color:LM.inkSoft}}>Other apps</div>
      <SettingsMcpClientRow provider="notion"/>
      <SettingsMcpClientRow provider="gemini"/>
    </div>
  </section>;
};
window.SocialConnections = SettingsConnections;

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
      await transport.saveProviderKey(p.id, keyInput.current.value);
      if (!mounted.current) return;
      keyInput.current.value = ''; setHasKey(false);
      setSaved('Saved on this machine. Provider connectivity has not been checked.');
      await providers.refresh();
    } catch (error) {
      if (mounted.current) setErr(error.message || 'The provider key could not be saved.');
    } finally { savingRef.current = false; if (mounted.current) setSaving(false); }
  };
  const box = { padding:`${LM.sp.md}px ${LM.sp.lg}px ${LM.sp.md}px`, borderTop:`1px solid ${LM.lineSoft}`, background:LM.bgDeep };
  const line = { fontSize:LM.fs.caption.sz, color:LM.inkSoft, lineHeight:LM.fs.caption.ln + 'px' };
  const refresh = <window.AH_DS.Btn type="button" disabled={saving || providers.loading} onClick={providers.refresh} style={{ ...window.AH_DS.styles.button("secondary", true), padding:`${LM.sp.xs}px ${LM.sp.md}px` }}>
    {providers.loading ? 'Reading status…' : 'Refresh provider status'}</window.AH_DS.Btn>;
  const useOpenCode = async () => {
    if (savingRef.current) return;
    savingRef.current = true; setSaving(true); setErr(''); setSaved('');
    try {
      const savedModel = await rememberComposerModel({
        name:'OpenCode (local)', route:'local-cli/opencode', routed:'local-cli/opencode',
        vendor:'OpenCode', tag:'LOCAL', cost:'free · OpenRouter',
      });
      window.ARCHHUB_PICKED_MODEL = savedModel;
      if (mounted.current) setSaved('OpenCode is now the chat model.');
    } catch (error) {
      if (mounted.current) setErr(error.message || 'OpenCode could not be selected.');
    } finally { savingRef.current = false; if (mounted.current) setSaving(false); }
  };
  if (KEY_LABEL[p.id]) {
    const label = KEY_LABEL[p.id];
    return (
      <div style={box}>
        <div style={line}>{label} keys are managed by the configured service owner. This Settings screen does not accept pasted keys.</div>
        <div style={{ display:'flex', gap:LM.sp.sm, marginTop:LM.sp.sm, flexWrap:'wrap' }}>
          {refresh}
        </div>
        {saved && <p role="status" style={{ fontSize:LM.fs.caption.sz, color:LM.ok, margin:`${LM.sp.sm}px 0 0` }}>{saved}</p>}
        {err && <p role="alert" style={{ fontSize:LM.fs.caption.sz, color:LM.err, margin:`${LM.sp.sm}px 0 0` }}>{err}</p>}
      </div>
    );
  }
  if (p.id === 'opencode') {
    return (
      <div style={box}>
        <div style={line}>{providerDetail(p)}. Chat uses local-cli/opencode with the approved free OpenRouter model.</div>
        <div style={{ display:'flex', gap:LM.sp.sm, marginTop:LM.sp.sm, flexWrap:'wrap' }}>
          <window.AH_DS.Btn type="button" disabled={saving || p.state !== 'installed'} onClick={useOpenCode}
            style={saving || p.state !== 'installed' ? { ...window.AH_DS.styles.button("secondary", true), padding:`${LM.sp.xs}px ${LM.sp.md}px`, borderStyle:'dashed', cursor:'default' } : { ...window.AH_DS.styles.button(true ? 'primary' : 'secondary', true), padding:`${LM.sp.xs}px ${LM.sp.md}px` }}>
            {saving ? 'Selecting…' : 'Use OpenCode'}</window.AH_DS.Btn>
          {refresh}
        </div>
        {saved && <p role="status" style={{ fontSize:LM.fs.caption.sz, color:LM.ok, margin:`${LM.sp.sm}px 0 0` }}>{saved}</p>}
        {err && <p role="alert" style={{ fontSize:LM.fs.caption.sz, color:LM.err, margin:`${LM.sp.sm}px 0 0` }}>{err}</p>}
      </div>
    );
  }
  return (
    <div style={box}>
      <div style={line}>{p.id === 'cloud'
        ? 'Sign in to use ArchHub cloud.'
        : p.state === 'running' ? p.name + ' is connected. Its models appear in the model picker.'
        : p.state === 'installed' || p.state === 'not installed' ? providerDetail(p) + '.'
        : p.sets ? 'Sign in or connect this provider, then read the status again.'
        : 'Start ' + p.name + ' on this machine (' + p.source + '), then read the status again.'}</div>
      <div style={{ display:'flex', gap:LM.sp.sm, marginTop:LM.sp.sm, flexWrap:'wrap' }}>
        {p.id === 'cloud' && <window.AH_DS.Btn type="button" onClick={() => onTab && onTab('account')} style={{ ...window.AH_DS.styles.button("secondary", true), padding:`${LM.sp.xs}px ${LM.sp.md}px` }}>Open Account</window.AH_DS.Btn>}
        {refresh}
      </div>
    </div>
  );
};

const SettingsProviders = ({ providers, onTab }) => {
  const { rows, error, loading, transport } = providers;
  const [managing, setManaging] = React.useState(null);

  const tone = (state) => state === 'keyed' ? LM.ok : state === 'running' ? LM.cyan :
    state === 'key invalid' ? LM.err : LM.inkSoft;
  const off = state => state === 'no key' || state === 'not running' || state === 'not installed';
  const warn = state => state === 'key invalid';
  const keyed = providerKeyed(rows), running = providerRunning(rows);
  return (
  <div>
    <SHead title="Providers" sub={'BYO keys. Local models live in Ollama or LM Studio. ' + (rows
      ? keyed + ' connected key' + (keyed === 1 ? '' : 's') + ' \u00b7 ' + running + ' local provider' + (running === 1 ? '' : 's') + ' connected.'
      : error ? 'Unavailable.' : 'Reading this machine\u2026')}/>
    <div style={{ background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg, overflow:'hidden' }}>
      {(rows || []).map((p, i) => (
        <div key={p.id} style={{ borderTop: i===0 ? 'none' : `1px solid ${LM.lineSoft}` }}>
          <div style={{ padding:`${LM.sp.md}px ${LM.sp.lg}px`, display:'flex', alignItems:'center', gap:LM.sp.md }}>
            <span style={{ width:24, height:24, borderRadius:LM.rad.sm, background:BRAND[p.id] || tone(p.state), color: (window.AH && window.AH.onFill) || '#180f08', display:'grid', placeItems:'center', fontFamily:LM.mono, fontSize:12, fontWeight:700 }}>{p.name[0]}</span>
            <div style={{ flex:1, minWidth:0, lineHeight:LM.fs.caption.ln + 'px' }}>
              <div style={{ fontSize:LM.fs.bodySm.sz, fontWeight:LM.fs.bodySmStrong.wt, color: off(p.state) ? LM.inkSoft : LM.ink }}>{p.name}</div>
              <div style={{ fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', fontWeight:LM.fs.label.wt, color:LM.inkSoft, marginTop:LM.sp.xs, letterSpacing:LM.fs.label.letter }}>
                <span title={p.state === 'keyed' ? 'Stored keys are never shown' : undefined} style={window.AH_DS.styles.muted}>
                  {providerDetail(p)}
                </span>
              </div>
            </div>
            <span style={{
              fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', fontWeight:LM.fs.label.wt, padding:`2px ${LM.sp.sm}px`, borderRadius:LM.rad.chip, letterSpacing:LM.fs.label.letter, textTransform:'uppercase',
              background: off(p.state) ? LM.bgSoft : tone(p.state) + '14',
              color:       warn(p.state) ? LM.err : tone(p.state),
            }}>{providerStateWord(p)}</span>
            <window.AH_DS.Btn aria-expanded={managing === p.id} onClick={() => setManaging(managing === p.id ? null : p.id)}
              style={{ ...window.AH_DS.styles.button("secondary", true), padding:`${LM.sp.xs}px ${LM.sp.sm}px` }}>{off(p.state) || warn(p.state) ? 'connect' : 'manage'}</window.AH_DS.Btn>
          </div>
          {managing === p.id && <ProviderManage p={p} providers={providers} onTab={onTab}/>}
        </div>
      ))}
      {!rows && <SettingsEmpty role={error ? 'alert' : 'status'}
        action={error && <window.AH_DS.Btn onClick={providers.refresh} disabled={loading} style={{ ...window.AH_DS.styles.button("secondary", true), padding:`${LM.sp.xs}px ${LM.sp.md}px` }}>read again</window.AH_DS.Btn>}>
        {error ? 'Provider status was not read: ' + error : 'Reading the providers on this machine\u2026'}</SettingsEmpty>}
      {rows && rows.length === 0 && <SettingsEmpty>No provider is registered on this machine.</SettingsEmpty>}
    </div>
  </div>
  );
};

const SettingsGenerationControl = ({ spec, value, disabled, onChange }) => (
  <div style={{ display:'grid', gridTemplateColumns:'1fr 1.3fr auto', gap:LM.sp.sm, alignItems:'center',
    padding:`${LM.sp.sm}px ${LM.sp.md}px`, background:LM.bg, border:`1px solid ${LM.lineSoft}`, borderRadius:LM.rad.control, marginBottom:LM.sp.sm }}>
    <label htmlFor={'model-default-' + spec.k} style={{ fontSize:LM.fs.caption.sz, color:LM.ink }}>{spec.label}</label>
    <input id={'model-default-' + spec.k} aria-label={spec.label} type="range" value={value}
      min={spec.min} max={spec.max} step={spec.step} disabled={disabled}
      onChange={event => onChange(spec.k, Number(event.target.value))}
      style={{ width:'100%', accentColor:LM.accent }}/>
    <input aria-label={spec.label + ' value'} type="number" value={value}
      min={spec.min} max={spec.max} step={spec.step} disabled={disabled}
      onChange={event => onChange(spec.k, Number(event.target.value))}
      style={{ width:80, boxSizing:'border-box', padding:`${LM.sp.xs}px ${LM.sp.sm}px`, borderRadius:LM.rad.control,
        border:`1px solid ${LM.line}`, background:LM.bgDeep, color:LM.ink, fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz }}/>
  </div>
);

// ── Models: route only jobs the app can really route in this build. The router exposes one
// persisted composer route, so Reasoning is editable and the other jobs are stated once.
const SettingsModels = () => {
  const projection = useStudioProjection();
  const generationNode = projection?.graph?.nodes?.find(node => node.application &&
    (node.params || []).some(row => row.setting?.kind === 'generation'));
  const [live, setLive] = React.useState(null);
  const [error, setError] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const [selected, setSelected] = React.useState(() => modelRoute(pickedModel()));
  const [defaults, setDefaults] = React.useState(() => modelGenerationDefaults());
  const [defaultsStatus, setDefaultsStatus] = React.useState('');
  const read = React.useCallback(() => {
    const controller = new AbortController();
    const s = window.__archhubSession || {};
    setError('');
    fetch('/api/universal/models', {signal:controller.signal,
      headers:{'X-ArchHub-Session':s.token || '', 'X-ArchHub-CSRF':s.csrf || ''}})
      .then(r => { if (!r.ok) throw new Error('Model catalogue unavailable'); return r.json(); })
      .then(d => {
        if (!d || d.ok === false || !Array.isArray(d.groups)) throw new Error('Model catalogue unavailable');
        setLive(d);
        const route = (typeof d.selected_route === 'string' && d.selected_route.trim()) ||
          (typeof d.default_route === 'string' && d.default_route.trim()) || modelRoute(pickedModel());
        setSelected(route);
      })
      .catch(failure => { if (!controller.signal.aborted) setError(failure.message || 'Model catalogue unavailable'); });
    return () => controller.abort();
  }, []);
  React.useEffect(() => read(), [read]);
  const options = (live?.groups || []).flatMap(group => group.items || [])
    .filter(freeModelRoute)
    .filter((item, index, all) => all.findIndex(other => modelRoute(other) === modelRoute(item)) === index);
  const selectedItem = options.find(item => modelRoute(item) === selected) || pickedModel();
  const localOptions = options.filter(item => modelRoute(item).startsWith('lmstudio/') || modelRoute(item).startsWith('ollama/'));
  const save = async event => {
    const route = event.target.value;
    const item = options.find(row => modelRoute(row) === route);
    if (!item || saving) return;
    setSaving(true); setError('');
    try {
      const saved = await rememberComposerModel(item);
      window.ARCHHUB_PICKED_MODEL = saved;
      setSelected(modelRoute(saved));
    } catch (failure) {
      setError(failure?.message || 'The model selection could not be saved.');
    } finally { setSaving(false); }
  };
  const saveDefault = (key, value) => {
    const next = normalizeGenerationDefaults({...defaults, [key]: value});
    setDefaults(next); setDefaultsStatus('saving');
    saveModelDefaults(next).then(saved => {
      setDefaults(normalizeGenerationDefaults(saved));
      setDefaultsStatus('saved');
    }).catch(failure => setDefaultsStatus(failure?.message || 'not saved'));
  };
  const selectStyle = { width:'100%', padding:`${LM.sp.sm}px ${LM.sp.md}px`, background:LM.bgDeep, color:LM.ink,
    border:`1px solid ${LM.line}`, borderRadius:LM.rad.control, fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz };
  const rowStyle = { display:'grid', gridTemplateColumns:'1fr 1.25fr', gap:LM.sp.lg, alignItems:'center',
    padding:`${LM.sp.md}px ${LM.sp.md}px`, background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.md, marginBottom:LM.sp.sm };
  return (
  <div>
    <SHead title="Model routing" sub="Reasoning uses the model you choose here. Only free or local routes are listed."/>
    <div style={rowStyle}>
        <div>
          <div style={{ fontSize:LM.fs.bodySm.sz, fontWeight:LM.fs.bodySmStrong.wt }}>Reasoning · planning</div>
          <div style={{ fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', fontWeight:LM.fs.label.wt, color:LM.inkSoft, marginTop:LM.sp.xs, letterSpacing:LM.fs.label.letter }}>
            {selectedItem ? ([selectedItem.vendor, selectedItem.tag].filter(Boolean).join(' · ') || modelRoute(selectedItem)) : 'Choose a free model'}
          </div>
        </div>
        <select aria-label="Reasoning model" value={options.some(item => modelRoute(item) === selected) ? selected : ''}
          disabled={saving || options.length === 0} onChange={save} style={selectStyle}>
          <option value="">{error || (!live ? 'Reading free models…' : 'Choose a free model')}</option>
          {options.map(item => <option key={modelRoute(item)} value={modelRoute(item)}>{modelOptionLabel(item)}</option>)}
        </select>
      </div>
    {localOptions.length > 0 && <div style={rowStyle}>
      <div>
        <div style={{ fontSize:LM.fs.bodySm.sz, fontWeight:LM.fs.bodySmStrong.wt }}>Local fallback (offline)</div>
        <div style={{ fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', fontWeight:LM.fs.label.wt, color:LM.inkSoft, marginTop:LM.sp.xs, letterSpacing:LM.fs.label.letter }}>Available local model routes</div>
      </div>
      <div style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, lineHeight:LM.fs.dataSm.ln + 'px', color:LM.inkSoft, overflowWrap:'anywhere' }}>
        {localOptions.map(item => modelRoute(item)).join(' · ')}
      </div>
    </div>}
    <div style={rowStyle}>
      <div>
        <div style={{ fontSize:LM.fs.bodySm.sz, fontWeight:LM.fs.bodySmStrong.wt }}>Generation defaults</div>
        <div style={{ fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', fontWeight:LM.fs.label.wt, color:LM.inkSoft, marginTop:LM.sp.xs, letterSpacing:LM.fs.label.letter }}>
          saved with model settings
        </div>
      </div>
      <div>
        {generationNode ? <window.ApplicationNodeParameters node={{...generationNode, actions:[],
          params:generationNode.params.filter(row => row.setting?.kind === 'generation')}}/>
          : GENERATION_SPECS.map(spec => <SettingsGenerationControl key={spec.k} spec={spec}
            value={defaults[spec.k]} disabled={saving} onChange={saveDefault}/>)}
        {defaultsStatus && <div role="status" style={{ fontFamily:LM.sans, fontSize:LM.fs.label.sz, color:defaultsStatus === 'not saved' ? LM.err : LM.inkSoft }}>
          {defaultsStatus}
        </div>}
      </div>
    </div>
    <div role="status" style={{ padding:`${LM.sp.sm}px ${LM.sp.md}px`, fontFamily:LM.sans, fontSize:LM.fs.bodySm.sz, lineHeight:LM.fs.bodySm.ln + 'px', color:LM.inkSoft }}>
      Other jobs use the reasoning model.
    </div>
    {error && <div role="alert" style={{ padding:`${LM.sp.sm}px ${LM.sp.md}px`, fontSize:LM.fs.caption.sz, color:LM.err }}>{error}</div>}
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
  const col = on && !unreadable ? LM.ok : LM.inkSoft;
  return (
    <div style={{ padding:`${LM.sp.md}px ${LM.sp.lg}px`, display:'flex', alignItems:'center', gap:LM.sp.md,
      borderTop: first ? 'none' : `1px solid ${LM.lineSoft}` }}>
      <span style={{ width:8, height:8, borderRadius:'50%', background:col, flexShrink:0,
        boxShadow: on && !unreadable ? `0 0 0 2px ${LM.ok}22` : 'none' }}/>
      <div style={{ flex:1, lineHeight:LM.fs.caption.ln + 'px', minWidth:0 }}>
        <div style={{ fontSize:LM.fs.bodySm.sz, fontWeight:LM.fs.bodySmStrong.wt, color: on ? LM.ink : LM.inkSoft }}>BABOOM</div>
        <div style={{ fontFamily:LM.sans, fontSize:LM.fs.caption.sz, color:LM.inkSoft, marginTop:LM.sp.xs, lineHeight:LM.fs.caption.ln + 'px' }}>
          Start BABOOM when ArchHub opens · {status} · Takes effect next time ArchHub opens.
        </div>
        {unreadable && <div style={{ fontFamily:LM.sans, fontSize:LM.fs.caption.sz, color:LM.warn, marginTop:LM.sp.xs, lineHeight:LM.fs.caption.ln + 'px' }}>
          Setting unreadable - BABOOM will not start until this is fixed{setting.error ? ' (' + setting.error + ')' : ''}
        </div>}
        {setting && !unreadable && setting.available !== true && <div style={{ fontFamily:LM.sans, fontSize:LM.fs.caption.sz, color:LM.inkSoft, marginTop:LM.sp.xs }}>
          Only the owner of this ArchHub can change this.
        </div>}
        {error && <div role="alert" style={{ fontFamily:LM.sans, fontSize:LM.fs.caption.sz, color:LM.warn, marginTop:LM.sp.xs, lineHeight:LM.fs.caption.ln + 'px' }}>{error}</div>}
      </div>
      <span style={{
        fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', fontWeight:LM.fs.label.wt, padding:`2px ${LM.sp.sm}px`, borderRadius:LM.rad.chip,
        background: col + '14', color: col, letterSpacing:LM.fs.label.letter, textTransform:'uppercase',
      }}>{!setting || unreadable ? 'unread' : on ? 'on start' : 'off'}</span>
      <window.AH_DS.Btn type="button" role="switch" aria-checked={on} aria-label="Start BABOOM when ArchHub opens"
        title={enabled ? (on ? 'Do not start BABOOM when ArchHub opens' : 'Start BABOOM when ArchHub opens') : 'BABOOM startup cannot be changed from this view'}
        disabled={!enabled} onClick={change} style={{width:30, height:16, borderRadius:LM.rad.pill, padding:1, flexShrink:0,
          position:'relative', border:0, background:on ? LM.accent : LM.lineSoft, transition:`background ${LM.dur.fast}ms`,
          cursor:enabled ? 'pointer' : 'default', ...(enabled ? {} : {outline:`1px dashed ${LM.line}`, outlineOffset:1})}}>
        <span style={{position:'absolute', top:1, left:on ? 14 : 1, width:14, height:14,
          borderRadius:'50%', background:'#fff', transition:`left ${LM.dur.fast}ms`}}/>
      </window.AH_DS.Btn>
    </div>
  );
};
// ── Theme / Shortcuts / Storage / About (lighter, but real)
// Theme (design studio-lm.jsx:2969-3009): the cards and rows as drawn, linked to Personal Settings.
// The accent row's "change" opens the saved-theme editor: its state, refresh, the accent and the
// version history all live inside that one design affordance.
const SettingsTheme = () => {
  const projection = useStudioProjection();
  const node = projection?.graph?.nodes?.find(node => node.application &&
    (node.params || []).some(row => row.k === 'accent' && row.editable === true));
  return node ? <div><SHead title="Theme" sub="The same settings cells as the application node."/>
    <window.ApplicationNodeParameters node={node}/><PersonalThemeHistory/></div> : <SettingsPersonalTheme/>;
};
const PersonalThemeHistory = () => {
  const state = usePersonalTheme(), api = window.ARCHHUB_EXISTING_WORKSHOP;
  const [error, setError] = React.useState('');
  return <div style={{marginTop:12}}>{(state?.configuration?.history || []).slice(0,10).map(entry =>
    <div key={entry.revision} style={{padding:8, fontSize:12}}>{entry.reason || entry.state}
      {!entry.current && entry.restore_control && <window.AH_DS.Btn style={window.AH_DS.styles.button("secondary", true)} onClick={async () => {
        try { await api.restoreThemeRevision(entry.revision); setError(''); }
        catch (failure) { setError(failure.message); }
      }}>Restore</window.AH_DS.Btn>}</div>)}{error && <p role="alert">{error}</p>}</div>;
};
const SettingsPersonalTheme = () => {
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
    borderRadius:LM.rad.control, padding:`${LM.sp.xs}px ${LM.sp.md}px`, fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz};
  const notLinked = 'Not linked to Personal Settings yet';
  const saved = config?.theme?.accent || LM.accent;
  const alert = error || state?.error || window.ARCHHUB_THEME_ERROR;
  const toggle = () => setEditAccent(!editAccent);
  return <div>
    <SHead title="Theme" sub="The themes this graph offers. A theme is listed only when it repaints every colour."/>
    {/* One display card per theme the graph offers (configuration.design_system.themes). */}
    <div data-theme-cards style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:LM.sp.sm }}>
      {(config?.design_system?.themes?.offered || []).map(({name, label}) => {
        const active = name === config.design_system.themes.active;
        return <div key={name} data-theme={name} aria-current={active ? 'true' : undefined}
          title={active ? 'The theme the Studio draws' : undefined} style={{
          padding:`${LM.sp.md}px ${LM.sp.lg}px`, background:LM.bg, border:`1px solid ${active?LM.accent:LM.line}`,
          borderRadius:LM.rad.panel, textAlign:'left', color:LM.ink, fontFamily:LM.sans,
        }}>
          <div style={{ display:'flex', gap:LM.sp.xs, marginBottom:LM.sp.sm }}>
            <div style={{ flex:1, height:36, background:active ? LM.bg : LM.bgSoft, borderRadius:LM.rad.control, border:`1px solid ${LM.lineSoft}` }}/>
          </div>
          <div style={{ fontSize:LM.fs.bodySm.sz, fontWeight:LM.fs.bodySmStrong.wt, textTransform:'capitalize' }}>{name}</div>
          <div style={{ fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', fontWeight:LM.fs.label.wt, color:LM.inkSoft, letterSpacing:LM.fs.label.letter, marginTop:LM.sp.xs }}>{label}{active ? ' · active' : ''}</div>
        </div>;
      })}
      {!config?.design_system?.themes && <div style={{ gridColumn:'1 / -1', fontSize:LM.fs.caption.sz, lineHeight:LM.fs.caption.ln + 'px', color:LM.inkSoft }}>Personal Settings not read</div>}
    </div>
    <div style={{ marginTop:LM.sp.lg, display:'flex', flexDirection:'column', gap:LM.sp.sm }}>
      <div style={{ background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.md, overflow:'hidden' }}>
        <div style={{ display:'flex', alignItems:'center', gap:LM.sp.sm, padding:`${LM.sp.sm}px ${LM.sp.md}px` }}>
          <span title="Current graph accent" style={{ width:16, height:16, borderRadius:LM.rad.chip, background:saved, border:`1px solid ${LM.lineSoft}` }}/>
          <div style={window.AH_DS.styles.fill}>
            <div style={{ fontSize:LM.fs.caption.sz }}>Accent colour</div>
            <div style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, lineHeight:LM.fs.dataSm.ln + 'px', color:LM.inkSoft, marginTop:1 }}>{saved} &#xb7; {config ? 'saved in Personal Settings' : 'Personal Settings not read'}</div>
          </div>
          <span role="button" tabIndex={0} aria-expanded={editAccent} onClick={toggle}
            onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } }}
            style={{ color:LM.inkSoft, fontSize:LM.fs.label.sz, cursor:'pointer' }}>{editAccent ? 'close' : 'change'}</span>
        </div>
        {editAccent && <div style={{ padding:`${LM.sp.md}px ${LM.sp.md}px ${LM.sp.md}px`, borderTop:`1px solid ${LM.lineSoft}`, background:LM.bgDeep }}>
          <div style={{display:'flex', alignItems:'center', gap:LM.sp.sm, fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', fontWeight:LM.fs.label.wt, color:LM.inkSoft, letterSpacing:LM.fs.label.letter}}>
            <span style={window.AH_DS.styles.fill}>{config ? `${config.binding_mode} · ${config.state}` :
              !api && window.ArchHubTheme?.source === 'graph' ? 'Graph theme · read-only in this view' : 'Personal Settings not read'}</span>
            <window.AH_DS.Btn title="Refresh Personal Settings" aria-label="Refresh Personal Settings" disabled={!api || state?.pending}
              style={{ ...window.AH_DS.styles.button("secondary", true), padding:`${LM.sp.xs}px ${LM.sp.sm}px` }} onClick={() => run(() => api.refreshTheme())}>&#x21bb;</window.AH_DS.Btn>
          </div>
          <div style={{fontSize:LM.fs.caption.sz, lineHeight:LM.fs.caption.ln + 'px', color:LM.inkSoft, margin:`${LM.sp.sm}px 0`}}>Check text and control contrast after changing colours; automatic contrast adjustment is not available.</div>
          {config && config.binding_mode !== 'personal-wip' && <div style={{fontSize:LM.fs.caption.sz, lineHeight:LM.fs.caption.ln + 'px', color:LM.warn, marginBottom:LM.sp.sm}}>
            Saving switches this view to its personal draft, including that draft&#x2019;s other colours.
          </div>}
          <div style={{display:'flex', alignItems:'center', gap:LM.sp.sm}}>
            <input aria-label="Choose accent colour" type="color" value={/^#[0-9a-fA-F]{6}$/.test(accent) ? accent : LM.accent}
              onChange={event => {setAccent(event.target.value); setDirty(true);}} disabled={!!state?.pending}
              style={{width:28, height:24, padding:0, border:`1px solid ${LM.line}`, borderRadius:LM.rad.control, background:'transparent'}}/>
            <input aria-label="Accent hex colour" value={accent} maxLength={7} style={{...fieldStyle, width:100}}
              onChange={event => {setAccent(event.target.value); setDirty(true);}} disabled={!!state?.pending}/>
            <window.AH_DS.Btn style={{ ...window.AH_DS.styles.button(true ? 'primary' : 'secondary', true), padding:`${LM.sp.xs}px ${LM.sp.md}px` }} disabled={unavailable || !/^#[0-9a-fA-F]{6}$/.test(accent) || accent.toLowerCase() === config?.theme?.accent?.toLowerCase()}
              onClick={() => run(() => api.previewThemeToken('accent', accent), true)}>{state?.pending ? 'Applying\u2026' : 'Apply accent'}</window.AH_DS.Btn>
          </div>
          {config && !oneDraft && <div style={{fontSize:LM.fs.caption.sz, lineHeight:LM.fs.caption.ln + 'px', color:LM.warn, marginTop:LM.sp.sm}}>
            {config.personal_wip_heads.length > 1 ? 'Multiple theme drafts exist; merging is not linked yet.' : 'No personal theme draft is available.'}
          </div>}
          {!!history.length && <div style={{marginTop:LM.sp.md}}>
            <div style={{fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', fontWeight:LM.fs.label.wt, color:LM.inkSoft, letterSpacing:LM.fs.label.letter, marginBottom:LM.sp.xs}}>VERSIONS &#xb7; SHOWING {Math.min(10,history.length)} OF {history.length}</div>
            {versions.map(entry => <div key={entry.revision} style={{display:'flex', gap:LM.sp.sm, alignItems:'center', padding:`${LM.sp.sm}px 0`, borderBottom:`1px solid ${LM.lineSoft}`}}>
              <span style={{flex:1, fontSize:LM.fs.caption.sz, lineHeight:LM.fs.caption.ln + 'px', color:LM.inkSoft}}>{entry.reason || entry.state} {entry.current ? '· current' : ''}
                <small style={{display:'block', fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, lineHeight:LM.fs.dataSm.ln + 'px', color:LM.inkSoft}}>{entry.timestamp || 'Time unavailable'} · {entry.state} · {entry.digest ? entry.digest.slice(0,10) : String(entry.revision).slice(-10)}</small></span>
              {!entry.current && entry.restore_control && <window.AH_DS.Btn style={{ ...window.AH_DS.styles.button("secondary", true), padding:`${LM.sp.xs}px ${LM.sp.md}px` }} disabled={unavailable}
                onClick={() => run(() => api.restoreThemeRevision(entry.revision))}>Restore</window.AH_DS.Btn>}
            </div>)}
          </div>}
        </div>}
      </div>
    </div>
    {alert && <p role="alert" style={{fontSize:12, color:LM.warn}}>{alert}</p>}
  </div>;
};
const SettingsShortcuts = () => {
  const [q, setQ] = React.useState('');
  const needle = q.trim().toLowerCase();
  const rows = STUDIO_SHORTCUT_BINDINGS.filter(binding =>
    !needle || [binding.label, binding.scope, binding.display].some(value => String(value || '').toLowerCase().includes(needle)));
  return (
    <div>
      <SHead title="Shortcuts" sub="Keyboard bindings handled by this Studio build."/>
      <div style={{display:'flex', alignItems:'center', gap:LM.sp.sm, padding:`${LM.sp.sm}px ${LM.sp.md}px`, margin:`0 0 ${LM.sp.lg}px`,
        background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.md}}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke={LM.inkSoft} strokeWidth="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
        <input aria-label="Filter shortcuts" value={q} onChange={e => setQ(e.target.value)} placeholder="Filter shortcuts..." style={{
          flex:1, border:0, background:'transparent', color:LM.ink, fontSize:LM.fs.caption.sz, lineHeight:LM.fs.caption.ln + 'px', outline:'none', fontFamily:LM.sans,
        }}/>
      </div>
      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:`${LM.sp.xs}px ${LM.sp.xl}px` }}>
        {rows.map(binding => (
          <div key={binding.id} data-shortcut-id={binding.id} style={{ display:'flex', alignItems:'center', gap:LM.sp.sm, padding:`${LM.sp.sm}px 0`, borderBottom:`1px solid ${LM.lineSoft}` }}>
            <span style={{ flex:1, fontSize:LM.fs.caption.sz, color:LM.ink }}>{binding.label}</span>
            <span style={{ fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', fontWeight:LM.fs.label.wt, color:LM.inkSoft, letterSpacing:LM.fs.label.letter, textTransform:'uppercase' }}>{studioShortcutScopeLabel(binding.scope)}</span>
            <kbd style={{ ...kbd(), fontSize:LM.fs.label.sz, padding:`2px ${LM.sp.sm}px` }}>{binding.display}</kbd>
          </div>
        ))}
      </div>
      {!rows.length && <SettingsEmpty>No shortcut matches this filter.</SettingsEmpty>}
    </div>
  );
};

// Conversation retention (Settings > Storage). Everything shown is read from
// /api/universal/conversation-retention: the policy the idle maintenance pass
// runs under, its last pass, and each archived conversation with its file.
const retentionWhen = seconds => (typeof seconds === 'number' && isFinite(seconds))
  ? new Date(seconds * 1000).toLocaleString(undefined, {year:'numeric', month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'})
  : null;
const retentionPass = run => run
  ? `${retentionWhen(run.at)} · ${run.status} · ${run.inspected} checked · ${run.protected} kept · ${run.archived} archived · ${run.purged} messages moved`
  : null;
const SettingsRetention = () => {
  const [state, setState] = React.useState({loading:true, error:'', data:null});
  const [busy, setBusy] = React.useState('');
  const [note, setNote] = React.useState('');
  const load = React.useCallback(() => {
    if (!window.ARCHHUB_CONVERSATION_RETENTION) {
      setState({loading:false, error:'Conversation retention is not available in this window.', data:null});
      return;
    }
    setState(current => Object.assign({}, current, {loading:true, error:''}));
    window.ARCHHUB_CONVERSATION_RETENTION()
      .then(data => setState({loading:false, error:'', data}))
      .catch(error => setState({loading:false, error:error.message || 'Conversation retention could not be read.', data:null}));
  }, []);
  React.useEffect(load, [load]);
  const act = (kind, row) => {
    const call = kind === 'restore' ? window.ARCHHUB_CONVERSATION_RESTORE : window.ARCHHUB_CONVERSATION_ARCHIVE_OPEN;
    if (!call) return;
    setBusy(kind + ':' + row.conversation); setNote('');
    call(row.conversation)
      .then(result => {
        if (kind === 'restore') {
          setNote(`Restored ${result.restored} message${result.restored === 1 ? '' : 's'} to ${row.title || 'the conversation'}.`);
          load();
        } else setNote('Opened ' + result.path);
      })
      .catch(error => setNote(error.message || 'Refused.'))
      .finally(() => setBusy(''));
  };
  const data = state.data;
  const policy = data && data.policy;
  const rows = (data && data.archived) || [];
  const change = data && data.last_change;
  return (
    <div style={{ marginBottom:LM.sp.lg }}>
      <div style={{ fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', fontWeight:LM.fs.label.wt, color:LM.inkSoft, letterSpacing:LM.fs.label.letter, marginBottom:LM.sp.sm }}>CONVERSATION RETENTION</div>
      {state.loading && !data && <SettingsEmpty>Reading the retention policy…</SettingsEmpty>}
      {/* retry only where a read exists to retry: never an inert action */}
      {state.error && <SettingsEmpty role="alert" action={window.ARCHHUB_CONVERSATION_RETENTION
        ? <window.AH_DS.Btn onClick={load} style={window.AH_DS.styles.button("secondary", true)}>retry</window.AH_DS.Btn> : null}>{state.error}</SettingsEmpty>}
      {policy && (
        <div style={{ padding:`${LM.sp.md}px ${LM.sp.lg}px`, background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.panel, fontSize:LM.fs.bodySm.sz, lineHeight:LM.fs.bodySm.ln + 'px', color:LM.inkSoft }}>
          <div style={{ color:LM.ink }}>
            A conversation with no activity for {policy.inactive_days} days is written to its archive file, then removed from the working store,
            {' '}{policy.messages_per_pass} messages at a time, only after {policy.idle_seconds} seconds without a click.
          </div>
          <div style={{ marginTop:LM.sp.xs }}>{policy.preserved}</div>
          {data.reason && <div style={{ marginTop:LM.sp.xs, color:LM.ink }}>{data.reason}</div>}
          <div style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, lineHeight:LM.fs.dataSm.ln + 'px', marginTop:LM.sp.sm, wordBreak:'break-all' }}>{policy.archive_folder || 'No archive folder: conversation content is not enabled.'}</div>
          <div style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, lineHeight:LM.fs.dataSm.ln + 'px', marginTop:LM.sp.sm }}>
            Last pass: {retentionPass(data.last_run) || 'none since ArchHub started'}
          </div>
          {change && <div style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, lineHeight:LM.fs.dataSm.ln + 'px', marginTop:LM.sp.xs }}>
            Last removal: {retentionWhen(change.at)} · {change.purged} messages moved · {change.exported} written to the archive
          </div>}
        </div>
      )}
      {data && !rows.length && <SettingsEmpty>No conversation has been archived.</SettingsEmpty>}
      {rows.map(row => (
        <div key={row.conversation} style={{ display:'flex', alignItems:'center', gap:LM.sp.sm, padding:`${LM.sp.md}px ${LM.sp.md}px`, marginTop:LM.sp.sm,
          background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.md }}>
          <div style={{ flex:1, minWidth:0 }}>
            <div title={row.conversation} style={{ fontSize:LM.fs.bodySm.sz, color:LM.ink, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{row.title || row.conversation}</div>
            <div style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, lineHeight:LM.fs.dataSm.ln + 'px', color:LM.inkSoft, marginTop:LM.sp.xs }}>
              {row.archived_at ? 'archived on ' + (retentionWhen(row.archived_at) || 'a date not recorded') : 'restored'} · {row.removed_messages} in the archive file{row.archive_exists ? '' : ' · file missing'}
            </div>
          </div>
          <window.AH_DS.Btn disabled={!!busy || !row.archive_exists} onClick={() => act('open', row)} style={window.AH_DS.styles.button("secondary", true)}>open archive</window.AH_DS.Btn>
          <window.AH_DS.Btn disabled={!!busy || !row.archive_exists} onClick={() => act('restore', row)} style={window.AH_DS.styles.button(true ? 'primary' : 'secondary', true)}>{busy === 'restore:' + row.conversation ? 'restoring…' : 'restore'}</window.AH_DS.Btn>
        </div>
      ))}
      {data && data.more && <SettingsEmpty>More archived conversations are in the archive folder.</SettingsEmpty>}
      {note && <SettingsEmpty>{note}</SettingsEmpty>}
    </div>
  );
};

// Storage (design studio-lm.jsx:3039-3072). The session count is the graph index; nothing measures
// sizes, a training queue or a model cache, so those unsupported tiles are omitted.
const SettingsStorage = () => {
  const projection = useStudioProjection();
  const backupOwner = projection?.graph?.nodes?.find(node => node.application &&
    (node.params || []).some(row => row.setting?.key === 'backup_count'));
  return (
  <div>
    <SHead title="Storage" sub="Saved sessions and the folders that hold your data."/>
    {backupOwner && <window.ApplicationNodeParameters node={{...backupOwner, actions:[],
      params:backupOwner.params.filter(row => ['backup_count', 'backup_budget_bytes'].includes(row.setting?.key))}}/>}
    <SettingsRetention/>
    <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:10, marginBottom:14 }}>
      {[
        ['Sessions', String(LM_SESSIONS.length), 'saved graphs'],
      ].map(([k, n, sz]) => (
        <div key={k} style={{ padding:`${LM.sp.md}px ${LM.sp.lg}px`, background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.panel }}>
          <div style={{ fontFamily:LM.sans, fontSize:LM.fs.label.sz, color:LM.inkSoft, letterSpacing:LM.fs.label.letter, fontWeight:LM.fs.label.wt }}>{k.toUpperCase()}</div>
          <div style={{ fontFamily:LM.sans, fontSize:LM.fs.display.sz, lineHeight:LM.fs.display.ln + 'px', fontWeight:LM.fs.display.wt, marginTop:LM.sp.xs, color: n === '\u2014' ? LM.inkMuted : LM.ink }}>{n}</div>
          <div style={{ fontFamily:LM.sans, fontSize:LM.fs.caption.sz, lineHeight:LM.fs.caption.ln + 'px', color:LM.inkSoft, marginTop:LM.sp.xs }}>{sz}</div>
        </div>
      ))}
    </div>
    {/* The design's Export / Clear cache / Forget all / Delete all rows each opened a folder while
        naming an action they did not perform. The rows now name what they do. Deleting sessions or
        the brain is done by hand in the folder; the Brain tab exports the brain. */}
    <div style={{ display:'flex', flexDirection:'column', gap:LM.sp.sm }}>
      {[
        ['Graph folder', 'the graph database and its backups', 'graph'],
        ['Brain folder', 'the brain on this machine', 'brain'],
      ].map(([t, sub, target]) => (
        <div key={t} style={{ display:'flex', alignItems:'center', gap:LM.sp.sm, padding:`${LM.sp.md}px ${LM.sp.md}px`, background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.md }}>
          <div style={window.AH_DS.styles.fill}>
            <div style={{ fontSize:LM.fs.bodySm.sz, color:LM.ink }}>{t}</div>
            <div style={{ fontFamily:LM.sans, fontSize:LM.fs.caption.sz, lineHeight:LM.fs.caption.ln + 'px', color:LM.inkSoft, marginTop:LM.sp.xs }}>{sub}</div>
          </div>
          <window.AH_DS.Btn onClick={async (e) => {
            const b = e.currentTarget;
            try {
              const answer = await window.ARCHHUB_REVEAL(target);
              b.textContent = answer && answer.ok ? 'opened' : 'refused';
            } catch (error) { b.textContent = 'refused'; }
            setTimeout(() => { b.textContent = 'open folder'; }, 4000);
          }} style={window.AH_DS.styles.button("secondary", true)}>open folder</window.AH_DS.Btn>
        </div>
      ))}
    </div>
  </div>
);
};

// About (design studio-lm.jsx:3074-3086). Each line reads what answers it: the release transport
// for the build and its update state, this page's own server, the host catalogue and the provider
// registry. The "updated" line's link opens the release update controls.
const SettingsAbout = ({ providers, release }) => {
  const hosts = hostTally();
  React.useEffect(() => {
    const transport = window.ARCHHUB_EXISTING_WORKSHOP;
    return transport?.watchApplicationUpdate ? transport.watchApplicationUpdate() : undefined;
  }, []);
  const rows = providers?.rows;
  const answering = (rows || []).filter(r => r.state === 'keyed' || r.state === 'running').map(r => r.name);
  const label = {idle:'no update in progress', checking:'checking for a release', downloading:'downloading an update',
    ready:'update ready', restarting:'restart requested', failed:'update failed'}[release?.state];
  return (
  <div>
    <SHead title="About" sub="ArchHub Studio · the AEC stack with one foot in your model and one in the LLM."/>
    <div style={{ background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg, padding:`${LM.sp.lg}px ${LM.sp.lg}px`, fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, lineHeight:LM.fs.dataSm.ln + 'px', color:LM.inkSoft }}>
      <div><span style={window.AH_DS.styles.muted}>version    </span> {release?.current_build || 'reading\u2026'}</div>
      <div><span style={window.AH_DS.styles.muted}>server     </span> {window.location.host || window.location.origin} &#xb7; running</div>
      <div data-about-host-total={hosts.total}><span style={window.AH_DS.styles.muted}>hosts      </span> {hosts.read ? <>{hosts.total} configured &#xb7; {hosts.running} live</> : 'checking hosts'}</div>
      <div><span style={window.AH_DS.styles.muted}>providers  </span> {rows ? (answering.length ? answering.join(', ') : 'none connected') : providers?.error ? 'not read' : 'reading\u2026'}</div>
      <div><span style={window.AH_DS.styles.muted}>updated    </span> {release?.updated_to ? 'to ' + release.updated_to : (label || 'reading\u2026')}</div>
    </div>
  </div>
  );
};

// Hosts (design studio-lm.jsx:3088-3142). The rows are the host catalogue; the BABOOM startup
// choice closes the list as one more row.
// Settings > Hosts > Assistants. Each of the person's assistants (Claude Code, Codex, OpenCode)
// shows whether it carries the ArchHub MCP entry. Connect writes that one client's entry, and only
// when pressed: the press is the consent. A client that cannot take the entry says why.
const ASSISTANT_NAMES = { 'claude-code':'Claude Code', codex:'Codex', opencode:'OpenCode', 'gemini-cli':'Gemini CLI' };
const ASSISTANT_SAID = {
  hook_only:'end-of-turn check set; no connection entry', registered:'configured', ready_to_register:'not connected', conflict:'a different entry is there; left unchanged',
  legacy_migration_required:'an old ArchHub entry is there; left unchanged', unsupported:'connection setup is unavailable',
  not_installed:'not installed', install_incomplete:'this install is incomplete', config_unreadable:'its settings file is unreadable',
  config_location_unverified:'its settings location is unverified', registration_unconfirmed:'the entry was not confirmed',
  migration_available:"ArchHub's old development start is there and cannot start; Replace moves it to this install",
  migration_unconfirmed:'the replacement was not confirmed; your settings are unchanged or backed up',
};
// Claude Code's Replace goes through its own command: nothing is copied, the retired entries are named.
const CLAUDE_CODE_SAID = {
  migration_available:"ArchHub's old development entry runs the source checkout; Replace moves Claude Code to this install and keeps your host tools",
  migration_unconfirmed:"ArchHub's old entry was not retired; this install's entry stays. Replace tries again",
};
const SettingsAssistants = () => {
  const [held, setHeld] = React.useState({ clients:null, error:'' });
  const [busy, setBusy] = React.useState('');
  const read = () => {
    const api = window.ARCHHUB_ASSISTANTS;
    if (!api) { setHeld({ clients:null, error:'This needs the application connection.' }); return; }
    api.read().then(d => setHeld({ clients:(d && d.clients) || [], error:'' }),
      e => setHeld({ clients:null, error:'Your assistants could not be read. Try again.' }));
  };
  React.useEffect(read, []);
  const connect = client => {
    if (busy) return;
    setBusy(client);
    window.ARCHHUB_ASSISTANTS.connect(client).then(read,
      e => setHeld(h => ({ ...h, error:'The connection settings could not be saved.' }))).finally(() => setBusy(''));
  };
  const [hookPreview, setHookPreview] = React.useState(null);
  const [hookNotice, setHookNotice] = React.useState('');
  const previewHooks = client => {
    if (busy) return;
    setBusy(client);
    setHookPreview(null);
    setHookNotice('');
    window.ARCHHUB_ASSISTANTS.previewHooks(client).then(
      d => setHookPreview({...d.result, client}),
      e => setHeld(h => ({...h, error:'The safety settings could not be reviewed. Try again.'}))
    ).finally(() => setBusy(''));
  };
  const repairHooks = () => {
    if (busy || !hookPreview) return;
    const reviewed = hookPreview;
    setBusy(reviewed.client);
    window.ARCHHUB_ASSISTANTS.repairHooks(reviewed.client, reviewed.plan_digest).then(d => {
      setHookPreview(null);
      setHookNotice(d.result.changed
        ? 'Safety settings saved. We still need to check that the assistant is using them.'
        : 'Safety settings already match. We still need to check that the assistant is using them.');
      read();
    }, e => {
      setHookPreview(null);
      setHeld(h => ({...h, error:'The repair was not applied. Review the current settings and try again.'}));
    }).finally(() => setBusy(''));
  };

  return (
    <div style={{ background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg, overflow:'hidden' }}>
      <div style={{ padding:`${LM.sp.md}px ${LM.sp.lg}px`, fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', fontWeight:LM.fs.label.wt, color:LM.inkSoft, letterSpacing:LM.fs.label.letter }}>
        ASSISTANTS · CONNECTIONS AND SAFETY
      </div>
      <div style={{padding:`0 ${LM.sp.lg}px ${LM.sp.md}px`, fontSize:LM.fs.caption.sz, lineHeight:LM.fs.caption.ln + 'px', color:LM.inkSoft}}>
        Saved settings do not prove a live connection. Actions require an assigned task and your approval.
      </div>
      {(held.clients || []).map(c => (
        <div key={c.client} style={{ padding:`${LM.sp.md}px ${LM.sp.lg}px`, display:'flex', alignItems:'center', gap:LM.sp.md, borderTop:`1px solid ${LM.lineSoft}` }}>
          <div style={{ flex:1, minWidth:0, lineHeight:LM.fs.caption.ln + 'px' }}>
            <div style={{ fontSize:LM.fs.bodySm.sz, fontWeight:LM.fs.bodySmStrong.wt, color:LM.ink }}>{ASSISTANT_NAMES[c.client] || 'Assistant'}</div>
            <div style={{ fontSize:LM.fs.caption.sz, color:LM.inkSoft }}>{((c.client === 'claude-code' && CLAUDE_CODE_SAID[c.state]) || ASSISTANT_SAID[c.state]) || 'Connection status unavailable'}</div>
            {c.hooks && (c.hooks.events || []).map(e => (
              <div key={e.event} style={{fontSize:LM.fs.caption.sz, color:LM.inkSoft}}>{e.said || 'Status unavailable'}</div>
            ))}
            {c.hooks && c.hooks.approval && <div style={{fontSize:LM.fs.caption.sz, color:LM.inkSoft}}>{c.hooks.approval}</div>}
            {c.hooks && !c.hooks.available && <div style={{fontSize:LM.fs.caption.sz, color:LM.inkSoft}}>{c.hooks.state === 'per_session' ? 'Connects when you open a session' : c.hooks.state === 'unsupported' ? 'Not supported yet' : c.hooks.state === 'not_installed' ? 'Not installed' : c.hooks.state === 'install_required' ? 'Open the installed ArchHub to connect this assistant.' : 'Settings could not be read. Repair the assistant installation first.'}</div>}
          </div>
          {c.hooks && c.hooks.available && (
            <window.AH_DS.Btn onClick={() => previewHooks(c.client)} disabled={!!busy}
              title="Review what Repair will change before applying it"
              style={{...window.AH_DS.styles.button("secondary", true), padding:`${LM.sp.xs}px ${LM.sp.md}px`}}>
              Repair
            </window.AH_DS.Btn>
          )}

          {c.state === 'ready_to_register' && (
            <window.AH_DS.Btn onClick={() => connect(c.client)} disabled={!!busy}
              title={'Adds one ArchHub entry to ' + (ASSISTANT_NAMES[c.client] || 'Assistant') + "'s connection settings"}
              style={{ ...window.AH_DS.styles.button("secondary", true), padding:`${LM.sp.xs}px ${LM.sp.md}px` }}>{busy === c.client ? 'Connecting…' : 'Connect'}</window.AH_DS.Btn>
          )}
          {c.state === 'migration_available' && (
            <window.AH_DS.Btn onClick={() => connect(c.client)} disabled={!!busy}
              title={c.client === 'claude-code' ? "Registers this install in Claude Code and retires only ArchHub's old development coordination entry through Claude Code's own command" : "Replaces only ArchHub's old entry in " + (ASSISTANT_NAMES[c.client] || 'Assistant') + "'s settings and keeps an encrypted copy of the file"}
              style={{ ...window.AH_DS.styles.button("secondary", true), padding:`${LM.sp.xs}px ${LM.sp.md}px` }}>{busy === c.client ? 'Replacing…' : 'Replace'}</window.AH_DS.Btn>
          )}
        </div>
      ))}
      {hookPreview && (
        <div role="region" aria-label="Review assistant safety settings" style={{padding:`${LM.sp.md}px ${LM.sp.lg}px`, borderTop:'1px solid '+LM.lineSoft}}>
          <div>{ASSISTANT_NAMES[hookPreview.client] || 'Assistant'}: {hookPreview.migration ? 'Repair: move the end-of-turn check to this install' : hookPreview.changed ? 'Repair: add the end-of-turn check' : 'Already set; nothing to change'}</div>
          <p>{hookPreview.description || 'Adds ArchHub\'s end-of-turn check while keeping your other settings and an encrypted backup. The assistant may still need to approve and load the changes.'}</p>
          <window.AH_DS.Btn onClick={repairHooks} disabled={!!busy || !hookPreview.changed} style={window.AH_DS.styles.button("secondary", true)}>Apply reviewed repair</window.AH_DS.Btn>
          <window.AH_DS.Btn onClick={() => setHookPreview(null)} disabled={!!busy} style={window.AH_DS.styles.button("secondary", true)}>Cancel</window.AH_DS.Btn>
        </div>
      )}
      {hookNotice && <div role="status" style={{padding:`${LM.sp.md}px ${LM.sp.lg}px`}}>{hookNotice}</div>}

      {!held.clients && <SettingsEmpty role={held.error ? 'alert' : 'status'}>{held.error || 'Reading your assistants…'}</SettingsEmpty>}
      {held.clients && held.error && <SettingsEmpty role="alert">{held.error}</SettingsEmpty>}
    </div>
  );
};
// Settings > Hosts > Operations: every operation the connectors declare, each with its evidence --
// a real court that ran it, or the exact thing that keeps it unavailable -- beside the live state.
const SettingsOperations = () => {
  useCatalogueVersion();
  const rows = Array.isArray(window.ARCHHUB_HOST_OPERATIONS) ? window.ARCHHUB_HOST_OPERATIONS : [];
  if (!rows.length) return null;
  const proven = rows.filter(r => r.evidence === 'court').length;
  const statusLabel = r => r.evidence === 'court' ? 'Ready' : ('Needs ' + (r.need || r.missing || 'setup'));
  const publicDetail = r => {
    const text = String(r.user_detail || r.label || r.summary || r.detail || '').trim();
    if (!text || /tests_replica|court/i.test(text)) return r.evidence === 'court' ? 'Verified in this build.' : 'Setup required before this can run.';
    return text;
  };
  return (
    <details style={{ background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg, overflow:'hidden' }}>
      <summary style={{ padding:`${LM.sp.md}px ${LM.sp.lg}px`, cursor:'pointer', fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', fontWeight:LM.fs.label.wt, color:LM.inkSoft, letterSpacing:LM.fs.label.letter }}>
        OPERATIONS · {proven} READY · {rows.length - proven} NEED SETUP
      </summary>
      {rows.map(r => (
        <div key={r.op} style={{ padding:`${LM.sp.sm}px ${LM.sp.lg}px`, display:'flex', gap:LM.sp.md, borderTop:`1px solid ${LM.lineSoft}`, alignItems:'baseline' }}>
          <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, lineHeight:LM.fs.dataSm.ln + 'px', color:LM.ink, width:190, flexShrink:0 }}>{r.op}</span>
          <span style={{ fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', fontWeight:LM.fs.label.wt, letterSpacing:LM.fs.label.letter, padding:`1px ${LM.sp.sm}px`, borderRadius:LM.rad.chip, flexShrink:0,
            background:(r.evidence === 'court' ? LM.ok : LM.inkSoft) + '1f', color:r.evidence === 'court' ? LM.ok : LM.inkSoft }}>
            {statusLabel(r)}</span>
          <span style={{ fontSize:LM.fs.caption.sz, lineHeight:LM.fs.caption.ln + 'px', color:LM.inkSoft, minWidth:0, overflowWrap:'anywhere' }}>
            {publicDetail(r)}{r.connector_state ? ' · ' + r.connector_state : ''}</span>
        </div>
      ))}
    </details>
  );
};
// -- Workspaces: the folders ArchHub governs besides 00.ARCHUB. Held in the graph (Governance),
// changed only here, and every change is approved by the owner's own Windows key prompt before it
// is written. The hooks read the signed projection. Nothing here ever deletes a file.
const WORKSPACE_CHECK_MS = 1500;
const WORKSPACE_CHECK_READS = 40;
const WORKSPACE_OWNER_RETRY_MS = [2000, 5000, 10000];
const WORKSPACE_CHANGE = 'Saving workspace';
const workspaceRefusal = message => /^the owner did not approve/i.test(String(message || ''))
  ? 'The workspace change was not saved. Try again from Settings > Workspaces.' : message;
const workspaceGraphOwnerDown = message => /graph owner is not answering/i.test(String(message || ''));
const WORKSPACE_PROMISE = 'Removing a workspace only stops ArchHub from governing it. Your files are never deleted.';
const WORKSPACE_AGENTS = ['claude','codex','gemini','opencode','antigravity','cursor','windsurf','zed','aider'];
const workspaceSlug = path => String(path || '').replace(/[\\/]+$/, '').split(/[\\/]/).pop()
  .toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 63);
async function workspaceRoots(body, renewed) {
  const s = window.__archhubSession || {};
  const isRead = body?.action === 'list';
  const response = await fetch('/api/universal/workspace-roots', {
    method:'POST',
    headers:{ 'Content-Type':'application/json', 'X-ArchHub-Session':s.token || '', 'X-ArchHub-CSRF':s.csrf || '' },
    body:JSON.stringify(body),
  });
  // A refused session (403: expired, revoked or a CSRF that no longer matches) is
  // replaced once by a fresh sign-in; a second refusal is shown as it is.
  if (response.status === 403 && !renewed && typeof window.__archhubRenewSession === 'function') {
    await window.__archhubRenewSession();
    if (isRead) return workspaceRoots(body, true);
  }
  let data = null;
  try { data = await response.json(); } catch (e) {}
  if (!response.ok || !data || data.ok === false) throw new Error((data && data.error) || 'The workspace registry did not answer.');
  return data;
}
const SettingsWorkspaces = () => {
  const [view, setView] = React.useState(null);
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState('');
  const [path, setPath] = React.useState('');
  const [rootId, setRootId] = React.useState('');
  const [privacy, setPrivacy] = React.useState('private');
  const [confirming, setConfirming] = React.useState(null);
  const run = async (label, body) => {
    setBusy(label); setError('');
    try { const next = await workspaceRoots(body); setView(next); return next; }
    catch (e) { setError(workspaceRefusal(e.message)); return null; }
    finally { setBusy(''); }
  };
  const [reads, setReads] = React.useState(0);
  const [ownerReadRetries, setOwnerReadRetries] = React.useState(0);
  const read = () => run('Reading', { action:'list' });
  React.useEffect(() => { read(); }, []);
  const registered = (view?.roots || []).filter(r => r.state === 'registered');
  const history = (view?.roots || []).filter(r => r.state !== 'registered');
  const boot = view?.boot;
  const checking = boot === 'checking';
  // Changes are offered only when the start-up check and this read agree the hooks'
  // registry is the graph's projection (or nothing is registered yet).
  const ready = !!view && (boot === 'match' || boot === 'missing') && view.projection === boot;
  const mismatch = !!view && !checking && !ready;
  // The start-up check runs beside the app: read again until it answers (bounded).
  React.useEffect(() => {
    if (!checking || reads >= WORKSPACE_CHECK_READS) return undefined;
    const timer = setTimeout(() => { setReads(n => n + 1); read(); }, WORKSPACE_CHECK_MS);
    return () => clearTimeout(timer);
  }, [checking, reads, view]);
  React.useEffect(() => {
    if (view || busy || !workspaceGraphOwnerDown(error)) return undefined;
    const delay = WORKSPACE_OWNER_RETRY_MS[ownerReadRetries] || 30000;
    const timer = setTimeout(() => { setOwnerReadRetries(n => n + 1); read(); }, delay);
    return () => clearTimeout(timer);
  }, [view, busy, error, ownerReadRetries]);
  const add = async () => {
    if (!ready || busy) return;
    const id = rootId || workspaceSlug(path);
    const done = await run(WORKSPACE_CHANGE, {
      action:'register', id, path:path.trim(), privacy, writers:WORKSPACE_AGENTS });
    if (done) { setPath(''); setRootId(''); setPrivacy('private'); }
  };
  const browse = async () => {
    if (busy) return;
    setBusy('Choose the folder in the Windows dialog'); setError('');
    try { const picked = await workspaceRoots({ action:'browse' }); if (picked.path) setPath(picked.path); }
    catch (e) { setError(e.message); }
    finally { setBusy(''); }
  };
  const toggleWriter = async (root, writer) => {
    if (!ready || busy) return;
    const current = new Set(root.writers || []);
    if (current.has(writer)) current.delete(writer); else current.add(writer);
    await run(WORKSPACE_CHANGE, {
      action:'update-writers', id:root.root_id,
      writers:WORKSPACE_AGENTS.filter(agent => current.has(agent)),
    });
  };
  const row = { padding:`${LM.sp.md}px ${LM.sp.lg}px`, display:'flex', alignItems:'center', gap:LM.sp.md };
  const mono = { fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, lineHeight:LM.fs.dataSm.ln + 'px', color:LM.inkSoft, marginTop:LM.sp.xs };
  const chip = col => ({ fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', fontWeight:LM.fs.label.wt, padding:`2px ${LM.sp.sm}px`, borderRadius:LM.rad.chip,
    background:col + '14', color:col, letterSpacing:LM.fs.label.letter, textTransform:'uppercase' });
  const field = { background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.sm, color:LM.ink,
    padding:`${LM.sp.sm}px ${LM.sp.md}px`, fontFamily:LM.sans, fontSize:LM.fs.bodySm.sz };
  return (
    <div style={{ display:'flex', flexDirection:'column', gap:LM.sp.lg }}>
      <SHead title="Workspaces" sub="Private workspaces are never shared publicly."/>
      {checking && (
        <div role="status" style={{ fontSize:LM.fs.caption.sz, color:LM.inkSoft }}>
          Checking the registry the governance hooks read against the graph{'\u2026'} Changes wait for the check.
        </div>
      )}
      {mismatch && (
        <div role="alert" style={{ padding:`${LM.sp.md}px ${LM.sp.lg}px`, border:`1px solid ${LM.warn}`, borderRadius:LM.rad.panel,
          background:LM.warn + '12', display:'flex', alignItems:'center', gap:LM.sp.md, fontSize:LM.fs.bodySm.sz }}>
          <span style={window.AH_DS.styles.fill}>The registry the governance hooks read does not match the graph (start-up check: {boot}; now: {view.projection}). Changes are paused until it is republished.</span>
          {view.key_pinned && (
            <window.AH_DS.Btn disabled={!!busy} onClick={() => { if (!busy && mismatch && view.key_pinned) run(WORKSPACE_CHANGE, { action:'republish' }); }}
              style={{ ...window.AH_DS.styles.button(true ? 'primary' : 'secondary', true), padding:`${LM.sp.xs}px ${LM.sp.md}px` }}>Republish</window.AH_DS.Btn>
          )}
        </div>
      )}
      <div style={{ background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg, overflow:'hidden' }}>
        <div style={row}>
          <div style={{ flex:1, minWidth:0 }}>
            <div style={{ fontSize:13, fontWeight:500 }}>00.ARCHUB</div>
            <div style={mono}>{view?.built_in?.path || 'C:\\Users\\fargaly\\00.ARCHUB'}</div>
          </div>
          <span style={chip(LM.inkSoft)}>built in</span>
        </div>
        {registered.map(r => (
          <div key={r.root_id} style={{ ...row, borderTop:`1px solid ${LM.lineSoft}` }}>
            <div style={{ flex:1, minWidth:0 }}>
              <div style={{ fontSize:13, fontWeight:500 }}>{r.root_id}</div>
              <div style={mono}>{r.path}</div>
              {r.privacy === 'private' && (
                <div style={{ display:'flex', gap:LM.sp.sm, flexWrap:'wrap', marginTop:LM.sp.sm }}>
                  {WORKSPACE_AGENTS.map(w => {
                    const active = (r.writers || []).includes(w);
                    return (
                      <label key={w} style={{ display:'inline-flex', alignItems:'center', gap:LM.sp.xs,
                        padding:`2px ${LM.sp.sm}px`, border:`1px solid ${active ? LM.ok : LM.line}`,
                        borderRadius:LM.rad.chip, fontFamily:LM.sans, fontSize:LM.fs.label.sz, fontWeight:LM.fs.label.wt, letterSpacing:LM.fs.label.letter,
                        color:active ? LM.ink : LM.inkSoft, textTransform:'uppercase' }}>
                        <input type="checkbox" checked={active} disabled={!!busy || !ready}
                          aria-label={`Allow ${w} to write ${r.root_id}`}
                          onChange={() => toggleWriter(r, w)}/>
                        {w}
                      </label>
                    );
                  })}
                </div>
              )}
            </div>
            <span style={chip(r.privacy === 'private' ? LM.ok : LM.warn)}>{r.privacy}</span>
            <window.AH_DS.Btn disabled={!!busy || !ready} onClick={() => { if (ready && !busy) setConfirming(r); }}
              style={{ ...window.AH_DS.styles.button("secondary", true), padding:`${LM.sp.xs}px ${LM.sp.md}px` }}>Remove</window.AH_DS.Btn>
          </div>
        ))}
        {view && !registered.length && <SettingsEmpty>No workspace is registered yet.</SettingsEmpty>}
        {!view && !error && <SettingsEmpty>Reading the workspace registry{'\u2026'}</SettingsEmpty>}
        {!view && error && workspaceGraphOwnerDown(error) && <SettingsEmpty action={<window.AH_DS.Btn disabled={!!busy} onClick={() => { setOwnerReadRetries(0); read(); }} style={{ ...window.AH_DS.styles.button("secondary", true), padding:`${LM.sp.xs}px ${LM.sp.md}px` }}>Retry</window.AH_DS.Btn>}>Starting ArchHub's graph service{'\u2026'} {'\u00b7'}</SettingsEmpty>}
        {!view && error && !workspaceGraphOwnerDown(error) && <SettingsEmpty role="alert" action={<window.AH_DS.Btn disabled={!!busy} onClick={read} style={{ ...window.AH_DS.styles.button("secondary", true), padding:`${LM.sp.xs}px ${LM.sp.md}px` }}>Read again</window.AH_DS.Btn>}>The workspace registry is unavailable: {error}</SettingsEmpty>}
      </div>
      {confirming && (
        <div role="dialog" style={{ padding:`${LM.sp.md}px ${LM.sp.lg}px`, border:`1px solid ${LM.line}`, borderRadius:LM.rad.panel, background:LM.bgSoft, fontSize:LM.fs.bodySm.sz, display:'flex', flexDirection:'column', gap:LM.sp.sm }}>
          <div>Stop governing <b>{confirming.root_id}</b> ({confirming.path})?</div>
          <div style={window.AH_DS.styles.muted}>{WORKSPACE_PROMISE}</div>
          <div style={{ display:'flex', gap:LM.sp.sm, justifyContent:'flex-end' }}>
            <window.AH_DS.Btn onClick={() => setConfirming(null)} style={{ ...window.AH_DS.styles.button("secondary", true), padding:`${LM.sp.xs}px ${LM.sp.md}px` }}>Keep it</window.AH_DS.Btn>
            <window.AH_DS.Btn disabled={!!busy || !ready} onClick={async () => { if (!ready || busy) return; const r = confirming; setConfirming(null);
              await run(WORKSPACE_CHANGE, { action:'unregister', id:r.root_id }); }}
              style={{ ...window.AH_DS.styles.button(true ? 'primary' : 'secondary', true), padding:`${LM.sp.xs}px ${LM.sp.md}px` }}>Stop governing</window.AH_DS.Btn>
          </div>
        </div>
      )}
      <div style={{ display:'grid', gridTemplateColumns:ready ? '1fr auto 150px 110px auto' : '1fr auto 150px 110px', gap:LM.sp.sm, alignItems:'center' }}>
        <input value={path} onChange={e => setPath(e.target.value)} placeholder="Folder, e.g. D:\Clients\Project"
          aria-label="Workspace folder" style={field}/>
        <window.AH_DS.Btn disabled={!!busy} onClick={browse} aria-label="Browse for a folder"
          style={{ ...window.AH_DS.styles.button(false ? 'primary' : 'secondary', true), padding:`${LM.sp.sm}px ${LM.sp.md}px` }}>Browse…</window.AH_DS.Btn>
        <input value={rootId} onChange={e => setRootId(e.target.value)} placeholder={workspaceSlug(path) || 'name'}
          aria-label="Workspace name" style={field}/>
        <select value={privacy} onChange={e => setPrivacy(e.target.value)} aria-label="Privacy" style={field}>
          <option value="private">Private</option>
          <option value="public">Public</option>
        </select>
        {ready && <window.AH_DS.Btn disabled={!!busy || !path.trim()} title={!path.trim() ? 'Choose a folder first' : undefined}
          onClick={add} style={{ ...window.AH_DS.styles.button(true ? 'primary' : 'secondary', true), padding:`${LM.sp.sm}px ${LM.sp.md}px` }}>Add</window.AH_DS.Btn>}
      </div>
      {!ready && (
        <div style={{ fontFamily:LM.sans, fontSize:LM.fs.caption.sz, lineHeight:LM.fs.caption.ln + 'px', color:LM.inkSoft }}>
          Workspaces are added in Settings > Workspaces after the workspace registry check passes.
        </div>
      )}
      {busy && <div role="status" style={{ fontSize:LM.fs.caption.sz, color:LM.inkSoft }}>{busy}{'\u2026'}</div>}
      {view && error && <div role="alert" style={{ fontSize:LM.fs.caption.sz, color:LM.err || LM.warn }}>{error}</div>}
      {history.length > 0 && (
        <div style={{ fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', fontWeight:LM.fs.label.wt, color:LM.inkSoft, letterSpacing:LM.fs.label.letter }}>
          NO LONGER GOVERNED: {history.map(r => r.root_id).join(', ')}
        </div>
      )}
    </div>
  );
};
// Design #connectors "Never removed": programs without a connector yet stay in the host catalogue.
const CONNECTORS_NOT_BUILT = [];
const HostEnableSwitch = ({ hostId, enabled, enabledState, enabledFreshness, disabledReason, authorityReading, onChange }) => {
  const pendingState = React.useState(false);
  const pending = pendingState[0], setPending = pendingState[1];
  const errorState = React.useState('');
  const error = errorState[0], setError = errorState[1];
  const row = (window.ARCHHUB_LIVE?.connectors || LM_HOSTS || []).find(h => h && h.id === hostId) || {id:hostId};
  const name = hostDisplayName(row);
  const state = enabledState || (typeof enabled === 'boolean' ? 'confirmed' : 'unknown');
  const unknown = state === 'unknown' || typeof enabled !== 'boolean';
  const stale = state === 'last_confirmed';
  const checked = !unknown && enabled === true;
  const confirmedOn = checked && state === 'confirmed';
  const reason = name + ' is turned off in Settings \u203a Connectors.';
  const freshness = Number.isFinite(Number(enabledFreshness)) ? Math.max(0, Math.floor(Number(enabledFreshness))) : null;
  const baseDisabledReason = String(disabledReason || row.enable_disabled_reason || row.write_disabled_reason || '').trim();
  const unavailableReason = baseDisabledReason || "Could not read this host's state.";
  const unavailable = unknown && !authorityReading;
  const writeDisabledReason = (!unknown && !stale) ? baseDisabledReason : '';
  const freshnessText = freshness !== null ? freshness + 's ago' : 'recently';
  const stateStatus = unknown
    ? unavailable ? '' : 'Checking\u2026'
    : stale
      ? 'Last known: ' + (enabled === true ? 'on' : 'off') + ', ' + freshnessText + '.' + (baseDisabledReason ? ' ' + baseDisabledReason : '')
      : '';
  const switchDisabledReason = pending ? 'Change is being saved.'
    : unavailable ? unavailableReason
      : unknown ? 'Reading host authority.'
        : stale ? 'Host authority is stale; retry before changing this.'
          : writeDisabledReason;
  const switchDisabled = pending || unknown || stale || !!writeDisabledReason;
  const refreshRows = () => window.fetch('/tools', toolHubFetchOptions(null)).then(r => r.ok ? r.json() : null).catch(() => null).then(tools => {
    if (tools && Array.isArray(tools.tools)) {
      window.ARCHHUB_TOOL_HUB = {...(window.ARCHHUB_TOOL_HUB || {}), ...tools};
      toolHubSnapshot = window.ARCHHUB_TOOL_HUB;
      toolHubSnapshotSignature = JSON.stringify(toolHubSnapshot);
      notifyToolHubSubscribers();
    }
    const state = catalogueStates.get('ARCHHUB_LOAD_HOSTS');
    if (state) state.read = false;
    return loadCatalogue('ARCHHUB_LOAD_HOSTS', LM_HOSTS);
  });
  const toggle = () => {
    if (switchDisabled || typeof window.fetch !== 'function') return;
    const session = window.__archhubSession || {};
    const next = !checked;
    setPending(true);
    setError('');
    window.fetch('/api/universal/host-enabled', {
      method:'POST',
      headers:{'Content-Type':'application/json', 'X-ArchHub-Session':session.token || '', 'X-ArchHub-CSRF':session.csrf || ''},
      body:JSON.stringify({host_id:hostId, enabled:next}),
    }).then(response => response.json().catch(() => ({})).then(payload => {
      if (!response.ok || payload?.ok === false) throw new Error(payload?.error || 'Host setting was refused.');
      return payload.host || {id:hostId, enabled:next};
    })).then(host => refreshRows().then(() => { onChange && onChange(host); }))
      .catch(exc => setError(exc?.message || 'Host setting was refused.'))
      .finally(() => setPending(false));
  };
  return (
    <span style={{ display:'inline-flex', alignItems:'center', gap:LM.sp.sm, minWidth:0 }}>
      <window.AH_DS.Btn type="button" role="switch" aria-checked={checked ? 'true' : 'false'} aria-label={'Turn ' + name + ' on/off' + (switchDisabledReason ? ': ' + switchDisabledReason : '')}
        title={switchDisabledReason || ''}
        disabled={switchDisabled} onClick={toggle} style={{
          width:34, height:18, borderRadius:LM.rad.pill, border:`1px solid ${confirmedOn ? LM.ok : LM.line}`,
          background:confirmedOn ? LM.ok : LM.bgPanel, padding:2, display:'inline-flex',
          justifyContent:checked ? 'flex-end' : 'flex-start', alignItems:'center', cursor:pending ? 'wait' : switchDisabled ? 'not-allowed' : 'pointer',
        }}>
        <span aria-hidden="true" style={{ width:12, height:12, borderRadius:'50%', background:checked ? '#fff' : LM.inkSoft, display:'block' }}/>
      </window.AH_DS.Btn>
      {unavailable && <span role="status" style={{ fontSize:LM.fs.label.sz, color:LM.inkSoft, lineHeight:LM.fs.label.ln + 'px', maxWidth:220 }}>Unavailable. {unavailableReason}</span>}
      {unavailable && <window.AH_DS.Btn type="button" onClick={refreshRows}
        style={{ fontFamily:LM.sans, fontSize:LM.fs.caption.sz, fontWeight:LM.fs.label.wt, color:LM.ink, background:LM.bgHover, border:`1px solid ${LM.line}`,
          borderRadius:LM.rad.control, padding:`${LM.sp.xs}px ${LM.sp.sm}px`, cursor:'pointer' }}>Retry</window.AH_DS.Btn>}
      {writeDisabledReason && <span role="status" style={{ fontSize:LM.fs.label.sz, color:LM.inkSoft, lineHeight:LM.fs.label.ln + 'px', maxWidth:220 }}>{writeDisabledReason}</span>}
      {stateStatus && <span role="status" style={{ fontSize:LM.fs.label.sz, color:LM.inkSoft, lineHeight:LM.fs.label.ln + 'px', maxWidth:220 }}>{stateStatus}</span>}
      {!unknown && !checked && <span role="status" style={{ fontSize:LM.fs.label.sz, color:LM.inkSoft, lineHeight:LM.fs.label.ln + 'px', maxWidth:220 }}>{reason}</span>}
      {error && <span role="alert" style={{ fontSize:LM.fs.label.sz, color:LM.err || LM.warn, lineHeight:LM.fs.label.ln + 'px', maxWidth:220 }}>{error}</span>}
    </span>
  );
};
const SettingsHosts = () => {
  const catalogue = useLiveCatalogue('ARCHHUB_LOAD_HOSTS', LM_HOSTS);
  const visibleHosts = LM_HOSTS;
  const officeExpandedState = React.useState(true);
  const officeExpanded = officeExpandedState[0], setOfficeExpanded = officeExpandedState[1];
  const hostRowsRevisionState = React.useState(0);
  const setHostRowsRevision = hostRowsRevisionState[1];
  const startHost = (h, button) => {
    const phrase = hostOpenPhrase(h);
    if (!phrase || typeof window.ARCHHUB_AGENT !== 'function') return;
    const before = button.textContent;
    button.textContent = 'Starting...';
    Promise.resolve(window.ARCHHUB_AGENT(phrase))
      .then(() => { button.textContent = 'Started'; })
      .catch(() => { button.textContent = 'Refused'; })
      .finally(() => { setTimeout(() => { button.textContent = before; }, 4000); });
  };
  // DP-CONNECTORS (design: ArchHub Product.html #connectors). One row per program: state dot,
  // name, what the probe says, then its live state word and Start. Programs ArchHub has no
  // connector for yet stay listed as "no connector yet" (design: "Never removed").
  // Design CONN: Excel · Word · PowerPoint · Outlook is ONE count row; governed controls stay on the real child rows.
  const connectorRows = hostConnectorRows(visibleHosts);
  const speckle = visibleHosts.find(h => /speckle/i.test(String(h.name || h.id || '')));
  // Built-vs-coming uses hostTally's shared "no wire in this build" / "no connector yet" filter.
  const tally = hostTally();
  const builtRows = tally.builtRows;
  const coming = tally.coming;
  const running = tally.running;
  const dotStyle = (col, dashed) => ({ width:8, height:8, borderRadius:'50%', flex:'none',
    background: dashed ? 'transparent' : col, border: dashed ? `1px dashed ${LM.inkSoft}` : 0 });
  const rowStyle = { display:'flex', alignItems:'center', gap:LM.sp.sm, padding:`${LM.sp.sm}px ${LM.sp.md}px`, flexWrap:'wrap',
    border:`1px solid ${LM.line}`, borderRadius:LM.rad.node, background:LM.bgPanel };
  const tagStyle = col => ({ fontFamily:LM.sans, fontSize:LM.fs.label.sz, fontWeight:LM.fs.label.wt, letterSpacing:LM.fs.label.letter, padding:`2px ${LM.sp.sm}px`,
    borderRadius:LM.rad.chip, background:LM.bgHover, color:col, whiteSpace:'nowrap' });
  return (
  <div style={{ display:'flex', flexDirection:'column', gap:14 }}>
    <div style={{ background:LM.bg, border:`1px solid ${LM.line}`, borderRadius:LM.rad.lg, overflow:'hidden' }}>
      <div data-connectors-bar="" style={{ display:'flex', alignItems:'center', gap:LM.sp.sm, padding:`${LM.sp.sm}px ${LM.sp.md}px`,
        background:LM.bgPanel, borderBottom:`1px solid ${LM.line}` }}>
        <b style={{ fontWeight:LM.fs.bodySmStrong.wt, fontSize:LM.fs.bodySm.sz }}>Connectors</b>
        <span data-host-total={tally.total} style={tagStyle(LM.inkSoft)}>{running}/{builtRows.length} running{coming ? ` \u00b7 ${coming} coming` : ''}</span>
        <span style={window.AH_DS.styles.fill}/>
        {speckle && <span style={tagStyle(LM.inkSoft)}>Speckle {'·'} {hostDetail(speckle)}</span>}
        {/* a live control on every state: re-read the hosts probe (never an inert action) */}
        <window.AH_DS.Btn type="button" onClick={catalogue.retry} disabled={catalogue.loading}
          style={{ fontFamily:LM.sans, fontSize:LM.fs.caption.sz, fontWeight:LM.fs.label.wt, color:LM.ink, background:LM.bgHover, border:`1px ${catalogue.loading ? 'dashed' : 'solid'} ${LM.line}`,
            borderRadius:LM.rad.control, padding:`${LM.sp.xs}px ${LM.sp.md}px`, cursor: catalogue.loading ? 'default' : 'pointer' }}>{catalogue.loading ? 'Checking\u2026' : 'Check again'}</window.AH_DS.Btn>
      </div>
      <div style={{ display:'grid', gap:LM.sp.sm, padding:LM.sp.lg }}>
      {connectorRows.flatMap(h => {
        const built = builtRows.some(row => row.id === h.id);
        const word = built ? hostPanelStateWord(h) : 'no connector yet';
        const col = built ? hostPanelStateTone(h) : LM.inkSoft;
        const rows = [(
          <div key={h.id} data-connector-row="" style={rowStyle}>
            <span style={{ ...dotStyle(word === 'Running' ? LM.ok : word === 'Unknown' ? LM.warn : LM.line, !built),
              animation: word === 'Unknown' ? 'lmPulse 1.2s infinite' : 'none' }}/>
            <div style={{ minWidth:0 }}>
              <div style={{ fontWeight:LM.fs.bodySmStrong.wt, fontSize:LM.fs.bodySm.sz, color:LM.ink }}>{h.name}</div>
              <div style={{ fontFamily:LM.sans, fontSize:LM.fs.caption.sz, color:LM.inkSoft }}>{h.officeEnabledSummary ? h.officeEnabledSummary + ' · ' : ''}{h.officeDetail || hostDetail(h)}</div>
            </div>
            <span style={window.AH_DS.styles.fill}/>
            <span data-host-state="" style={{ fontFamily:LM.sans, fontSize:LM.fs.caption.sz, color:col }}>{word}</span>
            {built && hostOpenPhrase(h) && word !== 'Running' && (
              <window.AH_DS.Btn type="button" onClick={e => startHost(h, e.currentTarget)}
                style={{ ...window.AH_DS.styles.button("secondary", true), padding:`${LM.sp.xs}px ${LM.sp.md}px` }}>Start</window.AH_DS.Btn>
            )}
            {built && !h.officeAggregate && <HostEnableSwitch hostId={h.id} enabled={h.enabled}
              enabledState={h.enabled_state} enabledFreshness={h.enabled_freshness_seconds}
              disabledReason={h.enable_disabled_reason || h.write_disabled_reason || ''}
              authorityReading={catalogue.loading}
              onChange={row => { Object.assign(h, row); setHostRowsRevision(v => v + 1); catalogueChanged(); }}/>}
            {h.officeAggregate && <window.AH_DS.Btn type="button" aria-expanded={officeExpanded ? 'true' : 'false'} aria-label="Show Office host controls"
              onClick={() => setOfficeExpanded(!officeExpanded)}
              style={{ ...window.AH_DS.styles.button("secondary", true), padding:`${LM.sp.xs}px ${LM.sp.md}px` }}>{officeExpanded ? 'Hide' : 'Show'}</window.AH_DS.Btn>}
          </div>
        )];
        if (h.officeAggregate && officeExpanded) {
          rows.push(...(h.officeChildren || []).map(child => {
            const childWord = hostPanelStateWord(child);
            const childCol = hostPanelStateTone(child);
            return (
              <div key={child.id} data-connector-row="" data-office-child="" style={{ ...rowStyle, marginLeft:LM.sp.lg, background:LM.bg }}>
                <span style={{ ...dotStyle(childWord === 'Running' ? LM.ok : childWord === 'Unknown' ? LM.warn : LM.line, false),
                  animation: childWord === 'Unknown' ? 'lmPulse 1.2s infinite' : 'none' }}/>
                <div style={{ minWidth:0 }}>
                  <div style={{ fontWeight:LM.fs.bodySmStrong.wt, fontSize:LM.fs.bodySm.sz, color:LM.ink }}>{child.name || child.id}</div>
                  <div style={{ fontFamily:LM.sans, fontSize:LM.fs.caption.sz, color:LM.inkSoft }}>{hostDetail(child)}</div>
                </div>
                <span style={window.AH_DS.styles.fill}/>
                <span data-host-state="" style={{ fontFamily:LM.sans, fontSize:LM.fs.caption.sz, color:childCol }}>{childWord}</span>
                {hostOpenPhrase(child) && childWord !== 'Running' && (
                  <window.AH_DS.Btn type="button" onClick={e => startHost(child, e.currentTarget)}
                    style={{ ...window.AH_DS.styles.button("secondary", true), padding:`${LM.sp.xs}px ${LM.sp.md}px` }}>Start</window.AH_DS.Btn>
                )}
                <HostEnableSwitch hostId={child.id} enabled={child.enabled}
                  enabledState={child.enabled_state} enabledFreshness={child.enabled_freshness_seconds}
                  disabledReason={child.enable_disabled_reason || child.write_disabled_reason || ''}
                  authorityReading={catalogue.loading}
                  onChange={row => { Object.assign(child, row); setHostRowsRevision(v => v + 1); catalogueChanged(); }}/>
              </div>
            );
          }));
        }
        return rows;
      })}
      {!connectorRows.length && <SettingsEmpty role={catalogue.error ? 'alert' : 'status'}
        action={catalogue.error && !catalogue.loading && <window.AH_DS.Btn onClick={catalogue.retry} style={{ ...window.AH_DS.styles.button("secondary", true), padding:`${LM.sp.xs}px ${LM.sp.md}px` }}>read again</window.AH_DS.Btn>}>
        {catalogue.loading ? 'Reading the programs on this machine…' : catalogue.error ? 'Connected programs: ' + catalogue.error + '.' : 'No connected program found yet.'}</SettingsEmpty>}
      </div>
    </div>
    <SettingsAssistants/>
    <SettingsOperations/>
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
const pickerSwatch = (col, fg) => ({ width:LM.rowH.cozy, height:LM.rowH.cozy, borderRadius:LM.rad.chip, background:col, color:fg, display:'grid', placeItems:'center', fontFamily:LM.sans, fontSize:LM.fs.label.sz, fontWeight:LM.fs.label.wt, flexShrink:0 });
const pickerRow = (enabled, sel) => ({
  display:'flex', alignItems:'center', gap:LM.sp.sm, padding:`${LM.sp.sm}px ${LM.sp.md}px`, borderRadius:LM.rad.node,
  cursor: enabled ? 'pointer' : 'default', background: sel ? LM.bgSoft : 'transparent',
  width:'100%', border:0, color:LM.ink, textAlign:'left', fontFamily:LM.sans,
});
const pickerHover = enabled => enabled ? {
  onMouseEnter:e => { e.currentTarget.style.background = LM.bgHover; },
  onMouseLeave:e => { e.currentTarget.style.background = 'transparent'; },
} : {};
const pickerGroupLabel = () => ({ fontFamily:LM.sans, fontSize:LM.fs.label.sz, color:LM.inkSoft, letterSpacing:LM.fs.label.letter, padding:`${LM.sp.xs}px ${LM.sp.md}px`, fontWeight:LM.fs.label.wt });
const pickerTag = tag => ({
  fontFamily:LM.sans, fontSize:LM.fs.label.sz, padding:`2px ${LM.sp.sm}px`, borderRadius:LM.rad.chip, letterSpacing:LM.fs.label.letter, fontWeight:LM.fs.label.wt,
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
  const note = { margin:0, padding:`${LM.sp.sm}px ${LM.sp.md}px`, fontFamily:LM.sans, fontSize:LM.fs.caption.sz, color:LM.inkSoft, lineHeight:LM.fs.caption.ln + 'px' };
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
    const target = row.kind === 'native-agent' && Array.isArray(row.children)
      ? row.children.find(child => child.session_id === row.session_id) : row;
    if (saving || !target || target.kind !== 'native-session' || target.connected !== true ||
        row.selectable === false || row.reason === 'ambiguous_endpoint' || !onNativeSelect) return;
    setSaving(true); setSelectionError('');
    try { await onNativeSelect(target); onClose(); }
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
  const sessions = (native?.rows || []).filter(row => row.kind === 'native-agent' && matches([row.app,row.title,row.workspace].join(' ')));
  const selectedRoute = modelRoute(model);
  return (
    <div onClick={onClose} style={{
      position:'absolute', inset:0, background:LM.scrim,
      display:'grid', placeItems:'start center', paddingTop:60, zIndex:50,
    }}>
      <div role="dialog" aria-label="Choose a model" onClick={e => e.stopPropagation()} style={{
        width:600, maxWidth:'92%', background:LM.bgPanel, border:`1px solid ${LM.line}`,
        borderRadius:LM.rad.dialog, overflow:'hidden', boxShadow:LM.shadow.dialog,
      }}>
        <div style={{ padding:`${LM.sp.md}px ${LM.sp.lg}px`, borderBottom:`1px solid ${LM.line}`, display:'flex', alignItems:'center', gap:LM.sp.md }}>
          <span style={{ fontSize:LM.icon.ui.size }}>⌕</span>
          <input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="Search models or paste an OpenRouter id…" style={{
            flex:1, border:0, background:'transparent', color:LM.ink, fontSize:LM.fs.bodySm.sz, lineHeight:LM.fs.bodySm.ln + 'px', outline:'none', fontFamily:LM.sans,
          }}/>
          <kbd style={kbd()}>esc</kbd>
        </div>
        <div className="ah-scroll" style={{ maxHeight:420, overflow:'auto', padding:`${LM.sp.sm}px ${LM.sp.sm}px ${LM.sp.md}px` }}>
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
                    <div style={{ flex:1, lineHeight:LM.fs.bodySm.ln + 'px', minWidth:0 }}>
                      <div style={{ fontSize:LM.fs.bodySm.sz }}>{m.name}</div>
                      <div style={{ fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', color:LM.inkSoft, letterSpacing:LM.fs.label.letter, fontWeight:LM.fs.label.wt }}>{m.vendor}{m.ctx ? ' · ctx ' + m.ctx : ''}</div>
                    </div>
                    {m.latency != null && <span style={{ fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', color:LM.ok }}>{m.latency}ms</span>}
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
            <div style={pickerGroupLabel()}>NATIVE AGENTS</div>
            {nativeError && <p role="status" style={note}>{nativeError}</p>}
            {!native && !nativeError && <p role="status" style={note}>Discovering open agent sessions…</p>}
            {native?.status === 'unavailable' && <p role="status" style={note}>Native session discovery is unavailable. Open your client and refresh.</p>}
            {(Array.isArray(native?.readiness) ? native.readiness : []).map(row =>
              <p key={row.app} style={note}>
                {row.app}: {row.state === 'executable-discovered' ? 'Command-line client found' : 'Command-line client not detected'}.
                {row.state === 'executable-discovered' && !(native.rows || []).some(session => session.app === row.app && session.connected === true)
                  ? ' No open session was discovered.' : ''}
              </p>)}
            {native?.status === 'ok' && !(native.rows || []).some(row => row.kind === 'native-agent') &&
              <p role="status" style={note}>No open agents were found. Open a session in your installed client, then refresh.</p>}
            {sessions.map(row => {
              const enabled = !saving && row.connected === true && row.selectable !== false && row.reason !== 'ambiguous_endpoint';
              return (
                <window.AH_DS.Btn type="button" key={JSON.stringify([row.app,row.session_id])} disabled={!enabled}
                  onClick={() => chooseNative(row)} style={pickerRow(enabled, false)} {...pickerHover(enabled)}>
                  <span style={pickerSwatch(LM.inkSoft, onFill)}>{String(row.app || '?')[0].toUpperCase()}</span>
                  <div style={{ flex:1, lineHeight:LM.fs.bodySm.ln + 'px', minWidth:0 }}>
                    <div style={{ fontSize:LM.fs.bodySm.sz }}>{row.title || 'Untitled session'}</div>
                    <div style={{ fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', color:LM.inkSoft, letterSpacing:LM.fs.label.letter, fontWeight:LM.fs.label.wt }}>
                      {row.reason === 'multiple_live_sessions' ? 'Multiple live sessions · open Details to choose one' :
                        row.reason === 'no_live_session' ? 'No live session' :
                        row.connected === true && row.selectable !== false ? 'Selectable · ' + row.live_session_count + ' live session' : 'Agent unavailable'}
                      {row.workspace ? ' · ' + row.workspace : ''}
                    </div>
                  </div>
                  <span style={pickerTag('')}>{String(row.app || '').toUpperCase()}</span>
                </window.AH_DS.Btn>
              );
            })}
          </div>}
          <div data-picker-options="" style={{ marginTop:LM.sp.sm }}>
            <div style={pickerGroupLabel()}>OPTIONS</div>
            <window.AH_DS.Btn type="button" disabled={saving} onClick={() => {setLive(null); setNative(null); setDiscovery(value => value + 1);}}
              style={pickerRow(!saving, false)} {...pickerHover(!saving)}>
              <span style={pickerSwatch(LM.bgSoft, LM.inkSoft)}>↻</span>
              <div style={{ flex:1, lineHeight:LM.fs.bodySm.ln + 'px', minWidth:0 }}>
                <div style={{ fontSize:LM.fs.bodySm.sz }}>Refresh</div>
                <div style={{ fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', color:LM.inkSoft, letterSpacing:LM.fs.label.letter, fontWeight:LM.fs.label.wt }}>Discover models and open agent sessions again</div>
              </div>
            </window.AH_DS.Btn>
            {selectedRoute && <window.AH_DS.Btn type="button" disabled={saving} aria-label="Clear this model selection"
              onClick={() => choose({name:'Choose a model', route:'', routed:''})}
              style={pickerRow(!saving, false)} {...pickerHover(!saving)}>
              <span style={pickerSwatch(LM.bgSoft, LM.inkSoft)}>×</span>
              <div style={{ flex:1, lineHeight:LM.fs.bodySm.ln + 'px', minWidth:0 }}>
                <div style={{ fontSize:LM.fs.bodySm.sz }}>Clear selection</div>
                <div style={{ fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', color:LM.inkSoft, letterSpacing:LM.fs.label.letter, fontWeight:LM.fs.label.wt, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{selectedRoute}</div>
              </div>
            </window.AH_DS.Btn>}
          </div>
        </div>
      </div>
    </div>
  );
};

// ──────────────────────── DOCS ────────────────────────
// Lives INSIDE the app shell — same overlay geometry, nav width and type scale as Settings,
// so this is the screen the end user actually gets, only the content differs.
const DP = ({ children, ...rest }) => <p {...rest} style={{ fontFamily:LM.sans, fontSize:LM.fs.body.sz, lineHeight:LM.fs.body.ln + 'px', color:LM.inkSoft, margin:`0 0 ${LM.sp.lg}px`, textWrap:'pretty' }}>{children}</p>;
const DSub = ({ children }) => <div style={{ fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', fontWeight:LM.fs.label.wt, color:LM.inkSoft, letterSpacing:LM.fs.label.letter, margin:`${LM.sp.xl}px 0 ${LM.sp.md}px` }}>{children}</div>;
const DRows = ({ rows }) => (
  <div style={{ display:'flex', flexDirection:'column', border:`1px solid ${LM.line}`, borderRadius:LM.rad.control, overflow:'hidden', margin:`0 0 ${LM.sp.lg}px` }}>
    {rows.map((r, i) => (
      <div key={r[0]} style={{ display:'grid', gridTemplateColumns:'170px 1fr', gap:LM.sp.md, padding:`${LM.sp.sm}px ${LM.sp.md}px`, borderTop: i ? `1px solid ${LM.lineSoft}` : 'none', background: i % 2 ? 'transparent' : LM.bgDeep }}>
        <span style={{ fontFamily:LM.mono, fontSize:LM.fs.dataSm.sz, lineHeight:LM.fs.dataSm.ln + 'px', color:LM.ink }}>{r[0]}</span>
        <span style={{ fontFamily:LM.sans, fontSize:LM.fs.caption.sz, lineHeight:LM.fs.caption.ln + 'px', color:LM.inkSoft }}>{r[1]}</span>
      </div>
    ))}
  </div>
);

const docsNodeGroups = nodes => {
  const groups = [];
  for (const row of nodes || []) {
    const cat = row.category || 'Nodes';
    let group = groups.find(item => item.cat === cat);
    if (!group) { group = {cat, rows:[]}; groups.push(group); }
    group.rows.push({id:row.id, title:row.title, detail:row.detail});
  }
  return groups;
};
const docsNodeIndexRows = nodeGroups => (nodeGroups || []).flatMap(group =>
  (group.rows || []).map(row => ({...row, cat:group.cat || 'Nodes'}))
);
const DNodeGroups = ({ groups = [] }) => (
  <div data-docs-node-catalogue="" style={{ display:'flex', flexDirection:'column', gap:LM.sp.md, margin:`0 0 ${LM.sp.lg}px` }}>
    {groups.map(group => {
      const meta = studioCategory(group.cat);
      return (
      <section key={group.cat} data-docs-node-category={group.cat} data-docs-node-color={meta.col}>
        <div style={{ fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', fontWeight:LM.fs.label.wt, color:meta.col, marginBottom:LM.sp.xs }}>{meta.label || group.cat}</div>
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit, minmax(180px, 1fr))', gap:LM.sp.sm }}>
          {(group.rows || []).map(row => (
            <div key={row.id || row.title} data-docs-node-tile="" data-docs-node-id={row.id} style={{ border:`1px solid ${LM.line}`, borderLeft:`3px solid ${meta.col}`, borderRadius:LM.rad.control, background:LM.bgDeep, padding:`${LM.sp.sm}px ${LM.sp.md}px`, minHeight:78 }}>
              <div style={{ display:'flex', alignItems:'center', gap:LM.sp.sm, marginBottom:4 }}>
                <span aria-hidden="true" style={{ width:LM.icon.category.box, height:LM.icon.category.box, borderRadius:LM.rad.sm, background:meta.col, color:LM.onFill, display:'grid', placeItems:'center', fontFamily:LM.sans, fontSize:LM.icon.category.size, fontWeight:700, flex:'0 0 auto' }}>{meta.icon}</span>
                <div data-docs-node-title="" style={{ fontFamily:LM.sans, fontSize:13, lineHeight:'18px', fontWeight:600, color:LM.ink, minWidth:0 }}>{row.title}</div>
              </div>
              <div data-docs-node-detail="" style={{ fontFamily:LM.sans, fontSize:LM.fs.caption.sz, lineHeight:LM.fs.caption.ln + 'px', color:LM.inkSoft }}>{row.detail}</div>
            </div>
          ))}
        </div>
      </section>
    );})}
  </div>
);
const connectorLabel = row => row.name || row.label || row.host || row.id || 'Connector';
const connectorState = row => hostStateWord(row || {state:'off'});
const docsConnectorRows = hosts => {
  const rows = (hosts || []).map(row => {
    const parts = [connectorState(row)];
    if (row.port) parts.push('port ' + row.port);
    if (row.detail || row.file) parts.push(row.detail || row.file);
    return [connectorLabel(row), parts.filter(Boolean).join(' · ')];
  });
  return rows.length ? rows : [[hostTally().read ? 'No hosts available' : 'Checking hosts', hostTally().read ? 'No hosts are available yet.' : 'Looking for local host apps.']];
};
const buildDocsProjection = ({documentation = {}, hosts}) => {
  const tutorials = documentation.tutorials || [];
  const nodeGroups = docsNodeGroups(documentation.nodes || []);
  const nodeRows = docsNodeIndexRows(nodeGroups);
  const connectorRows = docsConnectorRows(hosts);
  const sections = DOC_SECTIONS.map(row => row[0] === 'canvas' ? ['canvas', 'Nodes', plural(nodeRows.length, 'node')]
    : row[0] === 'connectors' ? ['connectors', 'Connectors', hostTally().read ? plural((hosts || []).length, 'host') : 'checking']
    : row).concat(tutorials.filter(page => !['getting-started', 'composer-canvas', 'connectors', 'brain'].includes(page.id))
      .map(page => [page.id, page.title, '']));
  const index = sections.map(row => ({s:row[0], k:'page', t:row[1], d:row[2] || ''})).concat(
    tutorials.flatMap(page => docsTutorialSections(page).map(section => ({s:docsTutorialSection(page.id), k:'topic', t:section.title || page.title, d:section.text}))),
    nodeRows.map(row => ({s:'canvas', k:'topic', t:row.title, d:row.cat})),
    connectorRows.map(row => ({s:'connectors', k:'topic', t:row[0], d:'Connectors'}))
  );
  return {nodeGroups, nodeRows, connectorRows, index, sections};
};

const DOC_SECTIONS = [
  ['start', 'Getting started', ''],
  ['canvas', 'Nodes', ''],
  ['connectors', 'Connectors', ''],
  ['brain', 'Brain', ''],
];
const docsTutorialSection = id => ({'getting-started':'start', 'composer-canvas':'canvas', connectors:'connectors', brain:'brain'}[id] || id);
const docsTutorialSections = page => String(page?.text || '').split(/(?:^|\n)## /).map((part, index) => {
  if (!index) return {title:'', text:part.trim()};
  const end = part.indexOf('\n');
  return {title:end < 0 ? part : part.slice(0, end), text:end < 0 ? '' : part.slice(end + 1).trim()};
});
const DocsTutorial = ({ page, skipCatalogue = false }) => page ? (
  <div data-docs-tutorial={page.id}>
    <SHead title={page.title} sub={page.description}/>
    {docsTutorialSections(page).filter(section => !skipCatalogue || section.title !== 'Node catalogue').map((section, index) => (
      <section key={index}>
        {section.title && <DSub>{section.title}</DSub>}
        <DP data-docs-install={section.title === 'Install' ? '' : undefined}
          data-docs-strip={section.title === 'Studio' ? '' : undefined}>
          <span style={{whiteSpace:'pre-wrap'}}>{section.text}</span>
        </DP>
      </section>
    ))}
  </div>
) : <DP>Documentation is loading.</DP>;

const DOC_KIND = { page:'PAGE', section:'SECTION', topic:'TOPIC', key:'KEY', cli:'CLI' };

// Live seam: the design's version slot ("STUDIO · v1.4") names the build this application runs, as the
// release transport reports it. Without that report the label stands alone; no version is typed here.
const docsBuild = () => {
  const build = window.ARCHHUB_EXISTING_WORKSHOP?.getSnapshot?.()?.applicationUpdate?.current_build;
  return typeof build === 'string' && build && build !== 'Unversioned build' ? build : '';
};

const Docs = ({ onClose, onHome }) => {
  const [sec, setSec] = React.useState('start');
  const canvasRead = useDeferredCanvas(true);
  const build = docsBuild();
  const authorityState = useStudioProjection();
  useLiveCatalogue('ARCHHUB_LOAD_HOSTS', LM_HOSTS);
  const documentation = authorityState?.canvas?.documentation || {};
  const tutorials = documentation.tutorials || [];
  const tutorial = id => tutorials.find(page => page.id === id);
  const projection = buildDocsProjection({documentation, hosts:LM_HOSTS});
  // SEARCH uses the same section and row data rendered by these pages, plus live catalogue rows.
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
    return projection.index.map(e => ({ e, r: score(e) })).filter(x => x.r >= 0)
      .sort((a, b) => a.r - b.r || a.e.t.length - b.e.t.length).slice(0, 9).map(x => x.e);
  }, [q, projection.index]);
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
    <div onClick={onClose} style={{ position:'absolute', inset:0, background:LM.scrim, zIndex:60, display:'grid', placeItems:'center' }}>
      <div role="dialog" aria-modal="true" aria-label="Documentation" onClick={e => e.stopPropagation()} style={{
        width:1000, maxWidth:'95%', height:620, maxHeight:'90%',
        background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:LM.rad.xl,
        overflow:'hidden', boxShadow:'0 30px 80px rgba(0,0,0,.6)',
        display:'grid', gridTemplateColumns:'208px 1fr', gridTemplateRows:'46px 1fr',
      }}>
        <div style={{ gridColumn:'1 / -1', gridRow:'1', borderBottom:`1px solid ${LM.line}`, display:'flex', alignItems:'center', gap:LM.sp.md, padding:`0 ${LM.sp.lg}px` }}>
          <span style={{ fontFamily:LM.sans, fontSize:LM.fs.title.sz, lineHeight:LM.fs.title.ln + 'px', fontWeight:LM.fs.title.wt }}>Documentation</span>
          <span style={{ fontFamily:LM.sans, fontSize:LM.fs.label.sz, color:LM.inkSoft, letterSpacing:LM.fs.label.letter, fontWeight:LM.fs.label.wt }}>STUDIO{build ? ' · ' + build : ''}</span>
          <div style={window.AH_DS.styles.fill}/>
          <window.AH_DS.Btn onClick={onHome} aria-label="Home" data-home-button style={{
            height:28, padding:'0 10px', border:`1px solid ${LM.line}`,
            background:'transparent', borderRadius:LM.rad.sm, cursor:'pointer',
            color:LM.inkSoft, fontFamily:LM.sans, fontSize:12, fontWeight:500,
          }}>Home</window.AH_DS.Btn>
          <div style={{ position:'relative', width:260 }}>
            <input ref={inputRef} value={q} onChange={e => setQ(e.target.value)} onKeyDown={onKey}
              placeholder="Search the docs…" style={{
                width:'100%', padding:`${LM.sp.sm}px ${LM.sp.md}px ${LM.sp.sm}px ${LM.sp['2xl']}px`, borderRadius:LM.rad.control,
                border:`1px solid ${q ? LM.accent : LM.line}`, background:LM.bg, color:LM.ink,
                fontFamily:LM.sans, fontSize:LM.fs.caption.sz, lineHeight:LM.fs.caption.ln + 'px', outline:'none',
              }}/>
            <span style={{ position:'absolute', left:LM.sp.md, top:LM.sp.sm, fontSize:LM.fs.label.sz, color:LM.inkSoft, pointerEvents:'none' }}>⌕</span>
            {q && (
              <div className="ah-scroll" style={{
                position:'absolute', top:32, left:0, width:'100%', maxHeight:250, overflow:'auto', zIndex:5,
                background:LM.bgPanel, border:`1px solid ${LM.line}`, borderRadius:LM.rad.panel,
                boxShadow:LM.shadow.popover,
              }}>
                {hits.length === 0
                  ? <div style={{ padding:`${LM.sp.md}px ${LM.sp.md}px`, fontFamily:LM.sans, fontSize:LM.fs.caption.sz, lineHeight:LM.fs.caption.ln + 'px', color:LM.inkSoft }}>
                      No match. Try <b style={{ color:LM.ink }}>wire</b>, <b style={{ color:LM.ink }}>skill</b> or <b style={{ color:LM.ink }}>brain</b>.
                    </div>
                  : hits.map((h, i) => (
                      <window.AH_DS.Btn key={h.s + h.k + h.t} onMouseEnter={() => setCur(i)} onClick={() => jump(h)} style={{
                        width:'100%', display:'flex', alignItems:'center', gap:LM.sp.sm, padding:`${LM.sp.sm}px ${LM.sp.md}px`,
                        border:0, borderTop: i === 0 ? 'none' : `1px solid ${LM.lineSoft}`,
                        background: i === cur ? LM.bgSoft : 'transparent', cursor:'pointer', textAlign:'left',
                      }}>
                        <span style={{
                          fontFamily:LM.sans, fontSize:LM.fs.label.sz, letterSpacing:LM.fs.label.letter, fontWeight:LM.fs.label.wt, flexShrink:0, width:52,
                          color: h.k === 'key' || h.k === 'cli' ? LM.accent : LM.inkSoft,
                        }}>{DOC_KIND[h.k]}</span>
                        <span style={{ flex:1, minWidth:0, fontFamily: h.k === 'cli' || h.k === 'key' ? LM.mono : LM.sans,
                          fontSize:LM.fs.caption.sz, lineHeight:LM.fs.caption.ln + 'px', color:LM.ink, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{h.t}</span>
                        <span style={{ fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', color:LM.inkSoft, flexShrink:0 }}>{h.d}</span>
                      </window.AH_DS.Btn>
                    ))}
                {hits.length > 0 && (
                  <div style={{ padding:`${LM.sp.sm}px ${LM.sp.md}px`, borderTop:`1px solid ${LM.lineSoft}`, fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', fontWeight:LM.fs.label.wt, color:LM.inkSoft, letterSpacing:LM.fs.label.letter }}>
                    ↑↓ MOVE · ↵ OPEN · ESC CLEAR · {hits.length} OF {projection.index.length} ENTRIES
                  </div>
                )}
              </div>
            )}
          </div>
          <window.AH_DS.Btn onClick={onClose} style={{ width:24, height:24, padding:0, border:`1px solid ${LM.line}`, background:'transparent', borderRadius:LM.rad.control, cursor:'pointer', color:LM.inkSoft, fontSize:LM.icon.ui.size }}>✕</window.AH_DS.Btn>
        </div>
        <div style={{ gridColumn:'1', gridRow:'2', borderRight:`1px solid ${LM.line}`, padding:'10px 8px', overflow:'auto' }}>
          {projection.sections.map(([id, label, badge]) => (
            <window.AH_DS.Btn key={id} onClick={() => setSec(id)} style={{
              width:'100%', padding:`${LM.sp.sm}px ${LM.sp.md}px`, borderRadius:LM.rad.control, border:0,
              background: sec === id ? LM.bgSoft : 'transparent',
              color: sec === id ? LM.ink : LM.inkSoft,
              textAlign:'left', cursor:'pointer', fontFamily:LM.sans, fontSize:LM.fs.bodySm.sz,
              display:'flex', alignItems:'center', gap:LM.sp.sm, marginBottom:1,
            }}>
              <span style={window.AH_DS.styles.fill}>{label}</span>
              {badge && <span style={{ fontFamily:LM.sans, fontSize:LM.fs.label.sz, color:LM.inkSoft, letterSpacing:LM.fs.label.letter, fontWeight:LM.fs.label.wt }}>{badge}</span>}
            </window.AH_DS.Btn>
          ))}
        </div>
        <div className="ah-scroll" style={{ gridColumn:'2', gridRow:'2', overflow:'auto', padding:`20px ${LM.sp.xl}px ${LM.sp.xl}px` }}>
          {build && <DP data-docs-build="">Build {build}</DP>}
          {canvasRead.pending || canvasRead.error || !tutorials.length ? <window.AH_DS.EmptyState
            title={canvasRead.pending ? 'Reading documentation…' : 'Documentation unavailable'}
            error={!!canvasRead.error} detail={canvasRead.error}
            onRetry={canvasRead.pending ? undefined : canvasRead.retry}/> : <>
          {sec === 'start'      && <DocsTutorial page={tutorial('getting-started')}/>}
          {sec === 'canvas'     && <DocsCanvas nodeGroups={projection.nodeGroups} page={tutorial('composer-canvas')}/>}
          {sec === 'connectors' && <DocsConnectors connectorRows={projection.connectorRows} page={tutorial('connectors')}/>}
          {sec === 'brain'      && <DocsTutorial page={tutorial('brain')}/>}
          {!['start', 'canvas', 'connectors', 'brain'].includes(sec) && <DocsTutorial page={tutorial(sec)}/>}
          </>}
        </div>
      </div>
    </div>
  );
};

const DocsCanvas = ({ nodeGroups = [], page }) => (
  <div>
    <SHead title="Nodes" sub="The node list below matches the Node library."/>
    <DNodeGroups groups={nodeGroups}/>
    <DocsTutorial page={page} skipCatalogue/>
  </div>
);
const DocsConnectors = ({ connectorRows = [], page }) => (
  <div>
    <SHead title="Connectors" sub="These rows match Settings > Hosts."/>
    <div data-docs-connectors=""><DRows rows={connectorRows}/></div>
    <DocsTutorial page={page}/>
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
    snapshot?.applicationUpdateError || '', status?.restart_refusal || '']);
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
  const [state, build, restartSupported, updatedFrom, updatedTo, pending, error, desktopRefusal] = JSON.parse(held);
  const [warning, restart] = useUpdateRestart(state === 'ready', () => act('reload'));
  const message = error || refusal || warning || desktopRefusal;
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
  const action = disabled => ({height:LM.icon.ui.box, padding:`0 ${LM.sp.sm}px`, borderRadius:LM.rad.chip, border:`1px solid ${LM.accent}`,
    background:disabled ? 'transparent' : LM.accentDim, color:disabled ? LM.inkSoft : LM.accent, fontFamily:LM.sans,
    fontSize:LM.fs.label.sz, letterSpacing:LM.fs.label.letter, fontWeight:LM.fs.label.wt,
    lineHeight:LM.fs.label.ln + 'px', flexShrink:0, cursor:disabled ? 'default' : 'pointer',
    borderStyle:disabled ? 'dashed' : 'solid'});
  return <div role={message ? 'alert' : 'status'} aria-label="Application update" title={title}
    style={{display:'flex', alignItems:'center', gap:LM.sp.sm, minWidth:0, padding:`0 ${LM.sp.xs}px`, whiteSpace:'nowrap',
      fontFamily:LM.sans, fontSize:LM.fs.label.sz, letterSpacing:LM.fs.label.letter, fontWeight:LM.fs.label.wt, color:message ? LM.err : LM.accent}}>
    <span aria-hidden="true">{'\u25cf'}</span>
    <span style={{minWidth:0, overflow:'hidden', textOverflow:'ellipsis'}}>{message || label}</span>
    {state === 'ready' && offered && !error && !refusal && restartSupported && <window.AH_DS.Btn type="button" data-update-restart="" disabled={!!pending}
      onClick={restart} title={'Restart into build ' + build + ' (Ctrl+Shift+U)'}
      style={action(!!pending)}>
      {'Update ready — Restart'}</window.AH_DS.Btn>}
    {state === 'ready' && offered && !message && !restartSupported && <span style={window.AH_DS.styles.muted}>
      restart ArchHub to install</span>}
    {!offered && !message && <window.AH_DS.Btn type="button" disabled={!!pending} onClick={() => act('acknowledge')}
      title="Hide this confirmation" style={action(!!pending)}>Dismiss</window.AH_DS.Btn>}
    {(error || refusal) && (state === 'ready' || !offered) && <window.AH_DS.Btn type="button" disabled={!!pending}
      onClick={() => act('read')} style={action(!!pending)}>Read status</window.AH_DS.Btn>}
    <span aria-hidden="true" style={{color:LM.inkDim, padding:`0 ${LM.sp.xs}px`}}>{'\u00b7'}</span>
  </div>;
};

// ──────────────────────── STATUS BAR ────────────────────────
const StatusBar = ({ session, model, setDocsOpen, onOpenWaitingTask }) => {
  // Live values in the design's slots: connected program, active graph document, running work and waiting work.
  useCatalogueVersion();
  const hub = useToolHubProjection();
  const hostCatalogue = catalogueStates.get('ARCHHUB_LOAD_HOSTS') || {};
  const waitingItems = Array.isArray(hub?.waiting) ? hub.waiting : [];
  const waitingCount = waitingItems.length;
  const connectedHost = LM_HOSTS.find(row => ['connected', 'listening', 'running'].includes(String(row?.state || '').toLowerCase()));
  const sessionsForStatus = Array.isArray(typeof LM_SESSIONS === 'undefined' ? null : LM_SESSIONS)
    ? LM_SESSIONS
    : (Array.isArray(window.ARCHHUB_LIVE?.sessions) ? window.ARCHHUB_LIVE.sessions : []);
  const runningCount = sessionsForStatus.filter(s => s.state === 'running').length;
  const documentLabel = session?.file || connectedHost?.file || '';
  const hostLabel = connectedHost ? [connectedHost.name, connectedHost.version].filter(Boolean).join(' ') : '';
  const hostReadFailed = !!hostCatalogue.error;
  const hostReadSucceeded = hostCatalogue.read === true && !hostReadFailed;
  const hostReadInFlight = !!hostCatalogue.loading || (!hostReadSucceeded && !hostReadFailed);
  const hostStripState = hostReadFailed ? 'failed' : hostReadInFlight ? 'checking' : connectedHost ? 'connected' : 'empty';
  const modelLabel = model?.tag === 'free' || /(^|\/)free$/i.test(modelRoute(model))
    ? ['free models', model?.provider || model?.vendor || 'OpenRouter'].filter(Boolean).join(' · ')
    : [model?.name,model?.vendor || model?.provider].filter(Boolean).join(' · ');
  const [stopError, setStopError] = React.useState('');
  const postStopControl = (path, expectedStopped) => {
    const session = window.__archhubSession || {};
    const fetcher = typeof window.fetch === 'function' ? window.fetch.bind(window) : (typeof fetch === 'function' ? fetch : null);
    if (!fetcher) {
      setStopError('Stop control is unavailable.');
      return;
    }
    setStopError('');
    fetcher(path, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-ArchHub-Session': session.token || '',
        'X-ArchHub-CSRF': session.csrf || '',
      },
      body: JSON.stringify({}),
    }).then(response => response.json().catch(() => null).then(payload => {
      if (!response.ok || !payload || payload.ok === false || typeof payload.stopped !== 'boolean') {
        throw new Error(String(payload?.error || 'Stop control was refused'));
      }
      if (payload.stopped !== expectedStopped) throw new Error('Stop control returned an unexpected state');
      publishToolHubStopState(payload.stopped, '');
    })).catch(error => {
      setStopError(String(error?.message || 'Stop control was refused'));
    }).finally(() => requestToolHubRefresh());
  };
  const handleStop = () => postStopControl('/stop-all', true);
  const handleResume = () => postStopControl('/resume', false);
  const StripItem = ({ onClick, children, accent }) => {
    const [h, setH] = React.useState(false);
    const style = {
      background:'transparent', border:0, padding:`0 ${LM.sp.xs}px`,
      cursor: onClick ? 'pointer' : 'default',
      color: h && onClick ? LM.ink : (accent || LM.inkSoft),
      fontFamily:LM.sans, fontSize:LM.fs.label.sz, lineHeight:LM.fs.label.ln + 'px', fontWeight:LM.fs.label.wt, letterSpacing:LM.fs.label.letter, whiteSpace:'nowrap',
      transition:`color ${LM.dur.fast}ms`,
    };
    if (!onClick) return <span style={style}>{children}</span>;
    return (
      <window.AH_DS.Btn onClick={onClick}
        onMouseEnter={() => setH(true)} onMouseLeave={() => setH(false)}
        style={style}>{children}</window.AH_DS.Btn>
    );
  };
  return (
    <div style={{
      // minWidth 0: at the narrowest window the update notice ellipsizes instead of widening the shell grid.
      minWidth:0, width:'100%', height:'100%',
      background:'transparent',
      display:'flex', alignItems:'center', gap:LM.sp.xs,
    }}>
      {hostStripState === 'connected' ? <>
        <StripItem><span style={{ color:LM.ok }}>●</span> Connected</StripItem>
        {hostLabel && <><span style={{ color:LM.inkDim, padding:`0 ${LM.sp.xs}px` }}>·</span><StripItem>{hostLabel}</StripItem></>}
        {documentLabel && <><span style={{ color:LM.inkDim, padding:`0 ${LM.sp.xs}px` }}>·</span><StripItem>{documentLabel}</StripItem></>}
      </> : hostStripState === 'checking' ? (
        <StripItem><span style={window.AH_DS.styles.muted}>○</span> Checking programs…</StripItem>
      ) : hostStripState === 'failed' && connectedHost ? (
        <>
          <StripItem>{'Last known: ' + [hostLabel, documentLabel].filter(Boolean).join(' · ')}</StripItem>
          <span style={{ color:LM.inkDim, padding:`0 ${LM.sp.xs}px` }}>·</span>
          <StripItem onClick={() => loadCatalogue('ARCHHUB_LOAD_HOSTS', LM_HOSTS)}>Retry</StripItem>
        </>
      ) : hostStripState === 'failed' ? (
        <>
          <StripItem accent={LM.err}>Programs unavailable</StripItem>
          <span style={{ color:LM.inkDim, padding:`0 ${LM.sp.xs}px` }}>·</span>
          <StripItem onClick={() => loadCatalogue('ARCHHUB_LOAD_HOSTS', LM_HOSTS)}>Retry</StripItem>
        </>
      ) : <StripItem><span style={window.AH_DS.styles.muted}>○</span> No program connected</StripItem>}
      {runningCount > 0 && <><span style={{ color:LM.inkDim, padding:`0 ${LM.sp.xs}px` }}>·</span><StripItem>{plural(runningCount, 'running', 'running')}</StripItem></>}
      {waitingCount > 0 && <><span style={{ color:LM.inkDim, padding:`0 ${LM.sp.xs}px` }}>·</span><StripItem>{waitingCount + ' waits for you'}</StripItem></>}
      <div style={window.AH_DS.styles.fill}/>
      <ApplicationUpdateNotice/>
      <WaitingButton variant="strip" items={waitingItems} onOpenTask={item => onOpenWaitingTask && onOpenWaitingTask(
        item.producer === 'social_approve' ? 'cloud' : 'workshop',
        item.producer === 'workshop_gate' ? {tab:'approvals', root:item.root || item.workshop || '', focus:item.open_target || item.work || item.id} : {})}/>
      {waitingCount > 0 && modelLabel && <span style={{ color:LM.inkDim, padding:'0 2px' }}>·</span>}
      {modelLabel && <>
        <StripItem>{modelLabel}</StripItem>
      </>}
      <span style={{ color:LM.inkDim, padding:'0 2px' }}>·</span>
      {hub?.stopped ? (
        <>
          <StripItem accent={LM.err}>Stopped</StripItem>
          <span style={{ color:LM.inkDim, padding:'0 2px' }}>·</span>
          <StripItem onClick={handleResume}>Resume</StripItem>
        </>
      ) : runningCount>0 ? (
        <StripItem onClick={handleStop} accent={LM.err}>Stop</StripItem>
      ) : null}
      {stopError && <>
        <span style={{ color:LM.inkDim, padding:'0 2px' }}>·</span>
        <StripItem accent={LM.err}>{stopError}</StripItem>
      </>}
      <span style={{ color:LM.inkDim, padding:'0 2px' }}>·</span>
      <StripItem>Ctrl K</StripItem>
    </div>
  );
};
const ServerStrip = StatusBar;

window.StudioLM = StudioLM;

})();
