// atlas-cockpit.jsx — THE FOUNDER COCKPIT. A hierarchical wired graph of the whole system.
// MACRO (14 wired domains) → open a domain → its real member nodes + wires →
// open a node → its ego-graph of real connections. Central map + permanent control
// panels (left = VIEW, right = ACT). Vellum drafting aesthetic. Built from real data.

const { HB, hsc, HBtn, HIconBtn, HPill, HDot, HAvatar, MapCanvas, STC, catCol, SEED_DB, ckLoad, ckSave } = window;

const ALS = 'archhub.atlas.v3';
const aLoad = () => { try { return JSON.parse(localStorage.getItem(ALS)); } catch (e) { return null; } };
const aSave = (o) => { try { localStorage.setItem(ALS, JSON.stringify(o)); } catch (e) {} };

const STATUS_ORDER = ['live', 'partial', 'prototype', 'planned', 'vision', 'blocked', 'deprecated'];
const CAT_LIST = ['ai', 'skill', 'connector', 'logic', 'custom', 'output', 'input', 'trigger', 'compose', 'transform', 'host', 'agent', 'watch', 'note'];
const DOM_COLS = ['#BC4D2A', '#5fb3b3', '#7898d6', '#a98cd6', '#7ec18e', '#e5b25a', '#6a9bcc', '#cc7a52'];

// The connective-tissue palette — same node kinds as the in-app session canvas
// (stem-core grammar): typed inputs, sliders, triggers, floating rules, watchers,
// adapters (data-type translation), global-param containers, notes.
const STEM_KINDS = [
  { kind: 'input',   cat: 'input',   glyph: '◇', title: 'Input',   sub: 'typed value source',     params: [{ k: 'value', v: 'Tower A' }] },
  { kind: 'slider',  cat: 'slider',  glyph: '▤', title: 'Slider',  sub: 'number 0–1',             params: [{ k: 'value', v: '0.7' }, { k: 'min', v: '0' }, { k: 'max', v: '1' }] },
  { kind: 'trigger', cat: 'trigger', glyph: '▷', title: 'Trigger', sub: 'emits exec on an event',  params: [{ k: 'on', v: 'on save' }] },
  { kind: 'rule',    cat: 'rule',    glyph: '⌥', title: 'Rule',    sub: 'floating if / branch',    params: [{ k: 'when', v: 'value > 0' }] },
  { kind: 'watch',   cat: 'watch',   glyph: '◉', title: 'Watch',   sub: 'passthrough viewer',      params: [{ k: 'as', v: 'table' }] },
  { kind: 'adapter', cat: 'adapter', glyph: '⇄', title: 'Adapter', sub: 'data-type translation',   params: [{ k: 'from', v: 'any' }, { k: 'to', v: 'any' }] },
  { kind: 'globals', cat: 'globals', glyph: '▦', title: 'Globals', sub: 'shared param container',  params: [{ k: 'env', v: 'prod' }, { k: 'region', v: 'eu' }] },
  { kind: 'note',    cat: 'note',    glyph: '✎', title: 'Note',    sub: 'annotation',              params: [] },
];

// SCALE LADDER — everything is a NODE. A CELL (a parameter / value container) composes a
// NODE; nodes group into a DOMAIN; domains group into a FIELD. Stop there. A skill is just
// a saved field, a workflow a saved canvas — every grouping collapses back into a node.
function ScaleLadder({ level, onClimb }) {
  const rungs = [
    ['stage', 'CELL', 'parameter · value'],
    ['node', 'NODE', 'the building block'],
    ['domain', 'DOMAIN', 'group of nodes'],
    ['field', 'FIELD', 'group of domains'],
  ];
  return (
    <div style={{ position: 'absolute', top: 54, left: '50%', transform: 'translateX(-50%)', display: 'flex', alignItems: 'center', padding: '4px 6px', background: HB.card, border: `1px solid ${HB.line}`, borderRadius: 10, boxShadow: '0 3px 12px rgba(80,50,20,.08)', fontFamily: HB.mono, zIndex: 6 }}>
      <span style={{ fontSize: 7.5, color: HB.inkMute, letterSpacing: '0.18em', padding: '0 9px 0 5px' }}>SCALE</span>
      {rungs.map(([k, l, sub], i) => {
        const on = level === k;
        return (
          <React.Fragment key={k}>
            {i > 0 && <span style={{ color: HB.inkMute, fontSize: 9, padding: '0 1px', opacity: 0.6 }}>⊂</span>}
            <button onClick={() => onClimb(k)} title={'climb to ' + sub} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1, padding: '4px 10px', borderRadius: 7, border: `1px solid ${on ? HB.accent : 'transparent'}`, background: on ? HB.accentSoft : 'transparent', cursor: 'pointer', color: on ? HB.accentHi : HB.inkSoft }}
              onMouseEnter={e => { if (!on) e.currentTarget.style.background = HB.paper2; }} onMouseLeave={e => { if (!on) e.currentTarget.style.background = 'transparent'; }}>
              <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.08em' }}>{l}</span>
              <span style={{ fontSize: 6.5, color: on ? HB.accent : HB.inkMute, letterSpacing: '0.02em' }}>{sub}</span>
            </button>
          </React.Fragment>
        );
      })}
    </div>
  );
}

function AtlasCockpit() {
  const [M, setM] = React.useState(null);
  const [expanded, setExpanded] = React.useState(() => ({ open: new Set(), collapsed: new Set() }));
  const [openNodes, setOpenNodes] = React.useState(() => new Set());
  const [activeWires, setActiveWires] = React.useState(() => new Set());
  const [sel, setSel] = React.useState({ domain: null, domains: new Set(), nodes: new Set(), field: null });
  const [query, setQuery] = React.useState('');
  const [selMode, setSelMode] = React.useState(false);
  const [vis, setVis] = React.useState(null);
  const [assign, setAssign] = React.useState(() => (aLoad() && aLoad().assign) || {});
  const [toast, setToast] = React.useState(null);
  const [cmd, setCmd] = React.useState('');
  const [domModal, setDomModal] = React.useState(false);
  const [ctx, setCtx] = React.useState(null);          // {type:'node'|'wire', id, a, b, x, y}
  const [confirmDel, setConfirmDel] = React.useState(null);  // { ids }
  const [leftTab, setLeftTab] = React.useState('inspect');    // inspect | view | index
  const canvas = React.useRef(null);
  const tRef = React.useRef(null);
  const [cdb, setCdb] = React.useState(() => ckLoad() || SEED_DB());
  React.useEffect(() => { ckSave(cdb); }, [cdb]);
  const setColl = (coll, fn) => setCdb(d => ({ ...d, [coll]: fn(d[coll]) }));
  const flash = (m) => { setToast(m); clearTimeout(tRef.current); tRef.current = setTimeout(() => setToast(null), 2000); };

  React.useEffect(() => {
    if (window.applyHBTheme) window.applyHBTheme('dark');   // cockpit is dark-only — single user
    const saved = aLoad();
    let data = (saved && saved.M) || window.ATLAS_MAP || { domains: [], nodes: [], wires: [], w: 2448, h: 2348 };
    // Attention is a real seed NODE (importance is a node, not a hardcoded rule) and it is
    // WIRED. This is a safety-net only — re-mints the node and/or its wires for any saved
    // state that predates them, so stale localStorage never shows Attention floating loose.
    if (!data.nodes.some(n => n.cat === 'attention')) {
      const d = data.domains.find(x => x.key === 'cockpit') || data.domains[0];
      if (d) data = { ...data, nodes: [...data.nodes, { id: 'sys_attention', dom: d.key, cat: 'attention', title: 'Attention', sub: 'ranks what needs the founder now — importance is a node, not a hardcoded rule (its params are the weights)', status: 'live', params: [{ k: 'weight.blocked', v: '3' }, { k: 'weight.gap', v: '2' }, { k: 'weight.agent', v: '1' }, { k: 'gap.threshold', v: '4' }], evidence_ref: 'self:right-panel/activity', x: d.x + 320, y: d.y + 72 }] };
    }
    if (data.nodes.some(n => n.id === 'sys_attention') && !data.wires.some(w => w.a === 'sys_attention' || w.b === 'sys_attention')) {
      const has = (id) => data.nodes.some(n => n.id === id);
      const inbound = [['cockpit_agent_loop', 'agent activity → weight.agent'], ['cockpit_live_metrics', 'metric gaps → weight.gap'], ['cockpit_audit_log', 'recent events to rank'], ['connectors_self_heal', 'heal/blocked signals → weight.blocked'], ['connectors_health_daemon', 'fleet health → blocked signal'], ['brain_daemon', 'brain activity to surface']];
      const outbound = [['cockpit_command_bar', 'ranked "what matters now" surfaces here'], ['cockpit_gate', 'high-rank items gate the founder view']];
      const add = [];
      inbound.forEach(([s, why]) => { if (has(s)) add.push({ a: s, b: 'sys_attention', why, dom: 'cockpit' }); });
      outbound.forEach(([t, why]) => { if (has(t)) add.push({ a: 'sys_attention', b: t, why, dom: 'cockpit' }); });
      if (add.length) data = { ...data, wires: [...data.wires, ...add] };
    }
    setM(data);
    setVis({ domains: new Set(data.domains.map(d => d.key)), status: new Set(STATUS_ORDER), wires: true, params: true, labels: true });
  }, []);
  React.useEffect(() => { if (M) aSave({ M, assign }); }, [M, assign]);
  React.useEffect(() => { if (sel.nodes.size || sel.domain || (sel.domains && sel.domains.size) || sel.field) setLeftTab('inspect'); }, [sel]);

  // ── attention layer: a NODE computes importance (its params are the weights) ──
  const attention = React.useMemo(() => {
    if (!M) return [];
    const dn = (k) => (M.domains.find(d => d.key === k) || {}).title || k;
    const att = M.nodes.find(n => n.cat === 'attention');
    const pv = (k, d) => { const p = (att && att.params || []).find(x => x.k === k); return p ? (parseFloat(p.v) || d) : d; };
    const W = { blocked: pv('weight.blocked', 3), gap: pv('weight.gap', 2), agent: pv('weight.agent', 1) };
    const gapMin = pv('gap.threshold', 4);
    const items = [];
    M.nodes.filter(n => n.status === 'blocked').forEach(n => items.push({ kind: 'blocked', label: n.title, sub: dn(n.dom), tone: 'red', nodeId: n.id, dom: n.dom, score: Math.round(W.blocked * 10) / 10 }));
    M.domains.map(d => { const ms = M.nodes.filter(n => n.dom === d.key); const v = ms.filter(n => n.status === 'vision').length; return { d, v, pct: v / (ms.length || 1) }; })
      .filter(x => x.v >= gapMin).sort((a, b) => b.v - a.v).slice(0, 4)
      .forEach(x => items.push({ kind: 'gap', label: x.d.title, sub: `${x.v} unbuilt · ${Math.round(x.pct * 100)}% vision`, tone: 'accent', dom: x.d.key, score: Math.round(W.gap * x.v * 10) / 10 }));
    Object.keys(assign).filter(id => (assign[id] || []).length && M.nodes.find(n => n.id === id)).slice(0, 5)
      .forEach(id => { const n = M.nodes.find(x => x.id === id); items.push({ kind: 'agent', label: n.title, sub: `${assign[id].length} agent${assign[id].length > 1 ? 's' : ''} · ${dn(n.dom)}`, tone: 'blue', nodeId: id, dom: n.dom, score: Math.round(W.agent * assign[id].length * 10) / 10 }); });
    return items.sort((a, b) => b.score - a.score);
  }, [M, assign]);

  if (!M || !vis) return <div style={{ position: 'fixed', inset: 0, display: 'grid', placeItems: 'center', color: '#9b938a', fontFamily: 'monospace', fontSize: 13 }}>loading the grand map…</div>;

  const DB = cdb;
  const counts = {}; STATUS_ORDER.forEach(s => counts[s] = 0); M.nodes.forEach(n => counts[n.status] = (counts[n.status] || 0) + 1);
  const total = M.nodes.length;
  const domName = (k) => (M.domains.find(d => d.key === k) || {}).title || k;
  const selNodes = M.nodes.filter(n => sel.nodes.has(n.id));

  // ── single-model navigation: zoom + expand/collapse in place ──
  const fitAll = () => { canvas.current && canvas.current.fitAll(); };
  const toggleDomain = (key, open) => { setExpanded(e => { const o = new Set(e.open), c = new Set(e.collapsed); if (open) { o.add(key); c.delete(key); } else { c.add(key); o.delete(key); } return { open: o, collapsed: c }; }); };
  const focusDomain = (key) => { setExpanded(e => { const o = new Set(e.open); o.add(key); const c = new Set(e.collapsed); c.delete(key); return { open: o, collapsed: c }; }); setTimeout(() => canvas.current && canvas.current.focusDomain(key), 30); };
  const expandAll = () => setExpanded({ open: new Set(M.domains.map(d => d.key)), collapsed: new Set() });
  const collapseAll = () => setExpanded({ open: new Set(), collapsed: new Set(M.domains.map(d => d.key)) });
  const autoOrganize = () => {
    setM(m => {
      const cols = 4, DW = 568, DH = 540, GAP = 36;
      const domains = m.domains.map((d, i) => ({ ...d, x: 40 + (i % cols) * (DW + GAP), y: 40 + Math.floor(i / cols) * (DH + GAP), w: DW, h: DH }));
      const byKey = {}; domains.forEach(d => byKey[d.key] = d);
      const byDom = {}; m.nodes.forEach(n => { (byDom[n.dom] = byDom[n.dom] || []).push(n); });
      const nodes = [];
      Object.entries(byDom).forEach(([key, ns]) => {
        const d = byKey[key]; if (!d) { ns.forEach(n => nodes.push(n)); return; }
        const ncols = Math.max(1, Math.floor((d.w - 48) / 138));
        ns.forEach((n, i) => nodes.push({ ...n, x: d.x + 24 + (i % ncols) * 138, y: d.y + 72 + Math.floor(i / ncols) * 104 }));
      });
      return { ...m, domains, nodes };
    });
    setExpanded({ open: new Set(), collapsed: new Set() }); setOpenNodes(new Set()); clearSel();
    flash('Auto-organized'); setTimeout(fitAll, 80);
  };
  const inspectNode = (id) => { const n = M.nodes.find(x => x.id === id); if (n) { focusDomain(n.dom); setSel({ domain: null, nodes: new Set([id]) }); setTimeout(() => canvas.current && canvas.current.focusNode(id), 60); } };
  const toggleNode = (id, open) => setOpenNodes(s => { const n = new Set(s); if (open) n.add(id); else n.delete(id); return n; });

  // ── selection ── (everything is a node on the graph: nodes, domains, fields all select the same way)
  const pickDomain = (key, additive) => setSel(s => {
    const cur = s.domains || new Set();
    if (additive) { const d = new Set(cur); d.has(key) ? d.delete(key) : d.add(key); return { domain: d.size === 1 ? [...d][0] : null, domains: d, nodes: new Set(), field: null }; }
    return { domain: key, domains: new Set([key]), nodes: new Set(), field: null };
  });
  const pickField = (id) => setSel({ domain: null, domains: new Set(), nodes: new Set(), field: id });
  const pickNode = (id, additive) => { if (id == null) { if (!additive) setSel(s => ({ ...s, nodes: new Set() })); return; } setSel(s => { const n = new Set(additive ? s.nodes : []); if (additive && n.has(id)) n.delete(id); else n.add(id); return { domain: additive ? s.domain : null, domains: additive ? (s.domains || new Set()) : new Set(), nodes: n, field: null }; }); };
  const onSelectBox = (ids, additive) => setSel(s => { const n = new Set(additive ? s.nodes : []); ids.forEach(i => n.add(i)); return { ...s, domains: additive ? (s.domains || new Set()) : new Set(), nodes: n, field: null }; });
  // scale-aware marquee: grabs collapsed DOMAINS + open-domain NODES in one drag (everything is a node)
  const onMarquee = (nodeIds, domKeys, additive) => setSel(s => {
    const n = new Set(additive ? s.nodes : []); nodeIds.forEach(i => n.add(i));
    const dms = new Set(additive ? (s.domains || new Set()) : []); domKeys.forEach(k => dms.add(k));
    return { domain: (dms.size === 1 && n.size === 0) ? [...dms][0] : null, domains: dms, nodes: n, field: null };
  });
  const clearSel = () => setSel({ domain: null, domains: new Set(), nodes: new Set(), field: null });
  const selectBy = (pred) => setSel(s => ({ domain: null, domains: new Set(), nodes: new Set(M.nodes.filter(pred).map(n => n.id)), field: null }));

  // ── mutations ──
  const patchNode = (id, patch) => setM(m => ({ ...m, nodes: m.nodes.map(n => n.id === id ? { ...n, ...patch } : n) }));
  // ── runtime: run a node, pulse its wires, mark dependents stale, record history ──
  const setRT = (id, rt) => setM(m => ({ ...m, nodes: m.nodes.map(n => n.id === id ? { ...n, rt: { ...(n.rt || { runs: [] }), ...rt } } : n) }));
  const markStaleDownstream = (id) => setM(m => { const RT = window.RT; const down = new Set(RT.downstream(m, id)); return { ...m, nodes: m.nodes.map(n => down.has(n.id) && (!n.rt || n.rt.state !== 'running') ? { ...n, rt: { ...(n.rt || { runs: [] }), state: 'stale' } } : n) }; });
  const runNode = (id) => {
    const RT = window.RT; const node = M.nodes.find(n => n.id === id); if (!node) return;
    if (node.frozen) { flash('Frozen — unfreeze to run'); return; }
    setRT(id, { state: 'running' });
    const outKeys = M.wires.filter(w => w.a === id).map(w => w.a + '>' + w.b);
    setActiveWires(new Set(outKeys));
    flash(`Running ${node.title}…`);
    setTimeout(() => {
      const run = RT.mkRun(node);
      setM(m => { const down = new Set(RT.downstream(m, id)); return { ...m, nodes: m.nodes.map(n => {
        if (n.id === id) { const runs = [...((n.rt && n.rt.runs) || []), run]; return { ...n, rt: { state: run.ok ? 'fresh' : 'error', runs, lastRun: run.t } }; }
        if (down.has(n.id) && (!n.rt || n.rt.state !== 'running')) return { ...n, rt: { ...(n.rt || { runs: [] }), state: 'stale' } };
        return n;
      }) }; });
      setActiveWires(new Set());
      flash(run.ok ? `✓ ${node.title} → ${run.result}` : `✗ ${node.title} failed`);
    }, 1100);
  };
  const runVariant = (id, fromRun) => { const RT = window.RT; const node = M.nodes.find(n => n.id === id); if (!node) return; const run = RT.mkRun(node, fromRun.id); setRT(id, { runs: [...RT.rtRuns(node), run], state: run.ok ? 'fresh' : 'error' }); flash(`⌥ variant of run #${fromRun.n}`); };
  const addWatcher = (id) => {
    const node = M.nodes.find(n => n.id === id); if (!node) return;
    const wid = 'watch_' + Date.now().toString(36);
    setM(m => ({ ...m, nodes: [...m.nodes, { id: wid, dom: node.dom, cat: 'watch', title: 'Watch · ' + node.title.slice(0, 14), sub: 'live result of ' + node.title, status: 'live', params: [], evidence_ref: '', x: node.x + 180, y: node.y + 30 }], wires: [...m.wires, { a: id, b: wid, why: 'streams its latest result to this watcher', kind: 'data' }] }));
    flash('Watcher added → wired'); setSel({ domain: null, nodes: new Set([wid]) });
  };
  const patchDomain = (key, patch) => setM(m => ({ ...m, domains: m.domains.map(d => d.key === key ? { ...d, ...patch } : d) }));
  const moveNode = (id, x, y) => setM(m => ({ ...m, nodes: m.nodes.map(n => n.id === id ? { ...n, x, y } : n) }));
  const moveDomain = (key, dx, dy) => setM(m => ({ ...m, domains: m.domains.map(d => d.key === key ? { ...d, x: d.x + dx, y: d.y + dy } : d), nodes: m.nodes.map(n => n.dom === key ? { ...n, x: n.x + dx, y: n.y + dy } : n) }));
  const delNodes = (ids) => { const s = new Set(ids); setM(m => ({ ...m, nodes: m.nodes.filter(n => !s.has(n.id)), wires: m.wires.filter(w => !s.has(w.a) && !s.has(w.b)) })); clearSel(); flash(`Deleted ${ids.length} node${ids.length > 1 ? 's' : ''}`); };
  const requestDelete = (ids) => { if (ids.length) setConfirmDel({ ids }); };
  // ── graph logic: wire / unwire / freeze / duplicate, via ports + right-click ──
  const connectNodes = (a, b) => {
    if (a === b) return;
    const na = M.nodes.find(n => n.id === a), nb = M.nodes.find(n => n.id === b);
    if (!na || !nb) return;
    if (M.wires.some(w => w.a === a && w.b === b)) { flash('Already wired'); return; }
    const ta = window.typeOf ? window.typeOf(na) : 'any';
    const tb = window.typeOf ? window.typeOf(nb) : 'any';
    const ok = window.archCanConnect ? window.archCanConnect(ta, tb) : true;
    if (ok) {
      setM(m => ({ ...m, wires: [...m.wires, { a, b, why: `carries ${ta}`, kind: 'flow', t: ta }] }));
      flash(ta === tb ? `Wired · ${ta}` : `Wired · ${ta} → ${tb} (any bridges)`);
    } else {
      // types differ — the app grammar inserts an ADAPTER that translates ta → tb
      const id = 'adp_' + Date.now().toString(36);
      const mx = Math.round((na.x + nb.x) / 2), my = Math.round((na.y + nb.y) / 2);
      setM(m => ({ ...m,
        nodes: [...m.nodes, { id, dom: na.dom, cat: 'adapter', title: `${ta} ⇄ ${tb}`, sub: 'type translation', status: 'live', params: [{ k: 'from', v: ta }, { k: 'to', v: tb }, { k: 'on_fail', v: 'coerce' }], evidence_ref: '', x: mx, y: my }],
        wires: [...m.wires, { a, b: id, why: `emits ${ta}`, kind: 'flow', t: ta }, { a: id, b, why: `translated to ${tb}`, kind: 'flow', t: tb }] }));
      setSel({ domain: null, nodes: new Set([id]) });
      flash(`✗ ${ta} → ${tb} can't connect — inserted Adapter`);
    }
  };
  const disconnectWire = (a, b) => { setM(m => ({ ...m, wires: m.wires.filter(w => !(w.a === a && w.b === b) && !(w.a === b && w.b === a)) })); flash('Wire cut'); };
  const disconnectAll = (id) => { setM(m => ({ ...m, wires: m.wires.filter(w => w.a !== id && w.b !== id) })); flash('Disconnected all wires'); };
  const freezeNode = (id) => { const n = M.nodes.find(x => x.id === id); patchNode(id, { frozen: !(n && n.frozen) }); flash(n && n.frozen ? 'Unfrozen' : 'Frozen — locked from edits & runs'); };
  const duplicateNode = (id) => { const n = M.nodes.find(x => x.id === id); if (!n) return; const nid = 'n_' + Date.now().toString(36); setM(m => ({ ...m, nodes: [...m.nodes, { ...n, id: nid, frozen: false, rt: undefined, x: n.x + 28, y: n.y + 28, title: n.title + ' copy' }] })); setSel({ domain: null, nodes: new Set([nid]) }); flash('Duplicated'); };
  const onNodeContext = (id, x, y) => { if (!sel.nodes.has(id)) setSel({ domain: null, nodes: new Set([id]) }); setCtx({ type: 'node', id, x, y }); };
  const onWireContext = (a, b, x, y) => setCtx({ type: 'wire', a, b, x, y });
  const bulkStatus = (st) => { const s = new Set(sel.nodes); setM(m => ({ ...m, nodes: m.nodes.map(n => s.has(n.id) ? { ...n, status: st } : n) })); flash(`${sel.nodes.size} → ${st}`); };
  const bulkDomain = (dom) => { const s = new Set(sel.nodes); setM(m => ({ ...m, nodes: m.nodes.map(n => s.has(n.id) ? { ...n, dom } : n) })); flash(`${sel.nodes.size} → ${domName(dom)}`); };
  const bulkAgent = (agentId) => { setAssign(a => { const next = { ...a }; sel.nodes.forEach(id => next[id] = [...new Set([...(next[id] || []), agentId])]); return next; }); flash(`Assigned ${sel.nodes.size} nodes`); };
  const toggleAgent = (nodeId, agentId) => setAssign(a => { const cur = a[nodeId] || []; return { ...a, [nodeId]: cur.includes(agentId) ? cur.filter(x => x !== agentId) : [...cur, agentId] }; });

  const addNode = (domKey) => {
    const key = domKey || sel.domain || (M.domains[0] || {}).key;
    const d = M.domains.find(x => x.key === key) || M.domains[0];
    const sibs = M.nodes.filter(n => n.dom === key).length;
    const id = 'n_' + Date.now().toString(36);
    const nx = d.x + 24 + (sibs % 4) * 138, ny = d.y + 64 + Math.floor(sibs / 4) * 104;
    setM(m => ({ ...m, nodes: [...m.nodes, { id, dom: key, cat: 'custom', title: 'New capability', sub: 'describe its intent', status: 'vision', params: [], evidence_ref: '', x: nx, y: ny }] }));
    focusDomain(key); setSel({ domain: null, nodes: new Set([id]) }); flash('Node created');
  };
  const addDomain = (title, col) => { const key = (title || 'domain').toLowerCase().replace(/[^a-z0-9]+/g, '_').slice(0, 14) + '_' + Math.random().toString(36).slice(2, 4); const cols = M.domains.length; const x = 40 + (cols % 4) * 600, y = 40 + Math.floor(cols / 4) * 572; setM(m => ({ ...m, domains: [...m.domains, { key, title: title || 'New Domain', col: col || DOM_COLS[cols % DOM_COLS.length], x, y, w: 568, h: 540 }] })); setVis(v => ({ ...v, domains: new Set([...v.domains, key]) })); flash(`Domain "${title}" created`); };
  // ── RECURSION: group selected nodes INTO a new grand node (a container domain).
  // Reuses the proven super-node machinery — it collapses to a volume, opens to its
  // members, grows interface knobs, edge-routes its wires. Grand nodes can be grouped
  // again one tier up (→ a field, the top of the ladder). og remembers each node's prior home. ──
  const groupSelection = () => {
    const ids = [...sel.nodes]; if (ids.length < 2) { flash('Select 2+ nodes to group into a grand node'); return; }
    const ns = M.nodes.filter(n => ids.includes(n.id));
    const key = 'grp_' + Date.now().toString(36);
    const cx = Math.round(ns.reduce((a, n) => a + n.x, 0) / ns.length);
    const cy = Math.round(ns.reduce((a, n) => a + n.y, 0) / ns.length);
    setM(m => ({ ...m,
      domains: [...m.domains, { key, title: 'New grand node', col: HB.accent, x: cx - 30, y: cy - 50, w: 340, h: 280, grouped: true }],
      nodes: m.nodes.map(n => ids.includes(n.id) ? { ...n, og: (n.og != null ? n.og : n.dom), dom: key } : n) }));
    setVis(v => ({ ...v, domains: new Set([...v.domains, key]) }));
    setExpanded(e => ({ open: new Set([...e.open, key]), collapsed: e.collapsed }));
    setSel({ domain: key, domains: new Set([key]), nodes: new Set(), field: null });
    flash(`Grouped ${ids.length} nodes → grand node`);
    setTimeout(() => canvas.current && canvas.current.focusDomain(key), 70);
  };
  // ── one tier up: group selected domains (and any loose nodes) INTO a field. ──
  // A field is just another node on the graph; loose nodes are first wrapped into a
  // grand node so the field is uniformly made of grand nodes. ──
  const fieldOf = (key) => (M.fields || []).find(f => (f.domKeys || []).includes(key));
  const groupIntoField = () => {
    const domKeys = [...(sel.domains || new Set())];
    const looseIds = [...sel.nodes];
    if (domKeys.length + (looseIds.length ? 1 : 0) < 2) { flash('Pick 2+ domains — or a domain plus nodes — to group into a field'); return; }
    const fid = 'fld_' + Date.now().toString(36);
    const gk = looseIds.length ? 'grp_' + Date.now().toString(36) : null;
    const allKeys = gk ? [...domKeys, gk] : domKeys;
    setM(m => {
      let domains = m.domains, nodes = m.nodes;
      if (gk) {
        const ns = m.nodes.filter(n => looseIds.includes(n.id));
        const cx = Math.round(ns.reduce((a, n) => a + n.x, 0) / ns.length), cy = Math.round(ns.reduce((a, n) => a + n.y, 0) / ns.length);
        domains = [...domains, { key: gk, title: 'Grand node', col: HB.accent, x: cx - 30, y: cy - 50, w: 340, h: 280, grouped: true }];
        nodes = m.nodes.map(n => looseIds.includes(n.id) ? { ...n, og: (n.og != null ? n.og : n.dom), dom: gk } : n);
      }
      return { ...m, domains, nodes, fields: [...(m.fields || []), { id: fid, title: 'New field', col: HB.blue, domKeys: allKeys }] };
    });
    if (gk) { setVis(v => ({ ...v, domains: new Set([...v.domains, gk]) })); setExpanded(e => ({ open: new Set([...e.open, gk]), collapsed: e.collapsed })); }
    setSel({ domain: null, domains: new Set(), nodes: new Set(), field: fid });
    flash(`Grouped ${allKeys.length} → field`);
  };
  const ungroupField = (id) => {
    setM(m => ({ ...m, fields: (m.fields || []).filter(f => f.id !== id) }));
    setSel(s => s.field === id ? { domain: null, domains: new Set(), nodes: new Set(), field: null } : s);
    flash('Field ungrouped — domains remain');
  };
  const patchField = (id, patch) => setM(m => ({ ...m, fields: (m.fields || []).map(f => f.id === id ? { ...f, ...patch } : f) }));
  // group dispatcher — picks the right tier from what's selected (everything is a node)
  const groupAny = () => { if ((sel.domains || new Set()).size >= 1) groupIntoField(); else groupSelection(); };
  const onDomainContext = (key, x, y) => { setSel(s => (s.domains && s.domains.has(key)) ? s : { domain: key, domains: new Set([key]), nodes: new Set(), field: null }); setCtx({ type: 'domain', key, x, y }); };
  const onFieldContext = (id, x, y) => { setSel({ domain: null, domains: new Set(), nodes: new Set(), field: id }); setCtx({ type: 'field', id, x, y }); };
  const ungroupDomain = (key) => {
    const d = M.domains.find(x => x.key === key); if (!d || !d.grouped) return;
    setM(m => { const fallback = (m.domains.find(z => z.key !== key) || {}).key; return { ...m,
      domains: m.domains.filter(x => x.key !== key),
      nodes: m.nodes.map(n => n.dom === key ? { ...n, dom: n.og || fallback, og: undefined } : n) }; });
    setVis(v => { const nd = new Set(v.domains); nd.delete(key); return { ...v, domains: nd }; });
    setSel({ domain: null, domains: new Set(), nodes: new Set(), field: null });
    flash('Ungrouped — nodes returned home');
  };
  // ── scale ladder: which rung of the recursive primitive is currently resolved ──
  const scaleLevel = openNodes.size ? 'stage' : expanded.open.size ? 'node' : (expanded.collapsed.size === M.domains.length ? 'domain' : 'field');
  const climbTo = (k) => {
    if (k === 'stage') { const id = [...sel.nodes][0]; if (id) { toggleNode(id, !openNodes.has(id)); flash('Cells — the node resolved into its parameters'); } else flash('Select a node, then climb to CELL to open its parameters'); }
    else if (k === 'node') { expandAll(); flash('Resolved to nodes — the building block'); }
    else if (k === 'domain') { collapseAll(); flash('Domains — each a grand node of its nodes'); }
    else if (k === 'field') { collapseAll(); setTimeout(fitAll, 40); flash('The field — every domain at once'); }
  };
  // ── agents AS NODES: drop an agent onto a domain and wire it to that domain's nodes ──
  const addAgentNode = (agentId) => {
    const ag = DB.agents.find(a => a.id === agentId); if (!ag) return;
    const key = sel.domain || (sel.nodes.size === 1 ? (M.nodes.find(n => sel.nodes.has(n.id)) || {}).dom : null) || (M.domains[0] || {}).key;
    const d = M.domains.find(x => x.key === key) || M.domains[0];
    const id = 'agn_' + agentId + '_' + Date.now().toString(36);
    const sibs = M.nodes.filter(n => n.dom === key);
    const nx = d.x + 24, ny = d.y + 64 + sibs.length % 3 * 100;
    // wire the agent node to up to 4 of the domain's nodes (it operates them)
    const targets = sibs.slice(0, 4);
    const newWires = targets.map(t => ({ a: id, b: t.id, why: `${ag.name} operates this`, kind: 'owns' }));
    setM(m => ({ ...m, nodes: [...m.nodes, { id, dom: key, cat: 'agent', agentId, title: ag.name, sub: ag.model ? (DB.models.find(mm => mm.id === ag.model) || {}).name || 'agent' : 'agent', status: 'live', params: [{ k: 'autonomy', v: ag.autonomy || 'propose' }], evidence_ref: '', x: nx, y: ny }], wires: [...m.wires, ...newWires] }));
    focusDomain(key); setSel({ domain: null, nodes: new Set([id]) }); flash(`${ag.name} attached → ${d.title}`);
  };

  // ── connective-tissue nodes: the SAME stem grammar as the app session canvas ──
  const addConnective = (spec) => {
    const key = sel.domain || (sel.nodes.size === 1 ? (M.nodes.find(n => sel.nodes.has(n.id)) || {}).dom : null) || (M.domains[0] || {}).key;
    const d = M.domains.find(x => x.key === key) || M.domains[0];
    const sibs = M.nodes.filter(n => n.dom === key).length;
    const id = spec.kind + '_' + Date.now().toString(36);
    const nx = d.x + 24 + (sibs % 4) * 138, ny = d.y + 64 + Math.floor(sibs / 4) * 104;
    setM(m => ({ ...m, nodes: [...m.nodes, { id, dom: key, cat: spec.cat, title: spec.title, sub: spec.sub, status: 'live', params: (spec.params || []).map(p => ({ ...p })), evidence_ref: '', x: nx, y: ny }] }));
    focusDomain(key); setSel({ domain: null, nodes: new Set([id]) }); flash(`${spec.title} dropped → ${d.title}`);
  };

  // ── visibility ──
  const toggleVisDomain = (k) => setVis(v => { const n = new Set(v.domains); n.has(k) ? n.delete(k) : n.add(k); return { ...v, domains: n }; });
  const toggleVisStatus = (k) => setVis(v => { const n = new Set(v.status); n.has(k) ? n.delete(k) : n.add(k); return { ...v, status: n }; });
  const allDomains = () => setVis(v => ({ ...v, domains: new Set(M.domains.map(d => d.key)) }));
  const openRoom = () => {};

  // ── command bar ──
  const runCmd = () => {
    const c = cmd.trim(); if (!c) return; setCmd(''); const lc = c.toLowerCase();
    const domHit = M.domains.find(d => lc.includes(d.key) || lc.includes(d.title.toLowerCase().split(' ')[0]));
    const stHit = STATUS_ORDER.find(s => lc.includes(s));
    if (/(enter|open|focus|fly|go|operate|room|control)/.test(lc) && domHit) { focusDomain(domHit.key); pickDomain(domHit.key); flash(`Opened ${domHit.title}`); }
    else if (/(expand all|open all)/.test(lc)) { expandAll(); flash('All domains expanded'); }
    else if (/(collapse all|close all)/.test(lc)) { collapseAll(); flash('All domains collapsed'); }
    else if (/(fit|whole|overview|macro|home|out)/.test(lc)) { collapseAll(); setTimeout(fitAll, 40); flash('Whole model'); }
    else if (/select/.test(lc) && stHit) { selectBy(n => n.status === stHit); flash(`Selected ${counts[stHit]} ${stHit}`); }
    else if (/select/.test(lc) && domHit) { selectBy(n => n.dom === domHit.key); flash(`Selected ${domHit.title}`); }
    else if (/(health|status|where|progress)/.test(lc)) { flash(`${counts.live} live · ${counts.partial} partial · ${counts.vision} vision · ${total} nodes / ${M.domains.length} domains`); }
    else if (domHit) { focusDomain(domHit.key); flash(domHit.title); }
    else flash('Try: "open brain", "operate models", "expand all", "fit", "health".');
  };

  // ── attention layer: what matters now ──
  const gotoAttention = (it) => { if (it.nodeId) inspectNode(it.nodeId); else { focusDomain(it.dom); pickDomain(it.dom); } };
  const tuneAttention = () => { const a = M.nodes.find(n => n.cat === 'attention'); if (a) inspectNode(a.id); };

  // ── INSPECT panel (left, selection-aware) ──
  let inspectPanel;
  const multiDom = (sel.domains || new Set()).size > 1 || ((sel.domains || new Set()).size >= 1 && sel.nodes.size >= 1);
  if (sel.field) inspectPanel = <FieldPanel M={M} fieldId={sel.field} patchField={patchField} onUngroup={ungroupField} onEnterDomain={(k) => { focusDomain(k); pickDomain(k); }} onClose={clearSel}/>;
  else if (multiDom) inspectPanel = <MultiPanel selDomains={[...(sel.domains || new Set())]} selNodes={sel.nodes} M={M} onGroupField={groupIntoField} clearSel={clearSel}/>;
  else if (sel.nodes.size > 1) inspectPanel = <BulkPanel sel={sel.nodes} selNodes={selNodes} M={M} DB={DB} STATUS={STATUS_ORDER} bulkStatus={bulkStatus} bulkDomain={bulkDomain} bulkAgent={bulkAgent} onGroup={groupSelection} onDelete={() => delNodes([...sel.nodes])} clearSel={clearSel} domName={domName}/>;
  else if (sel.nodes.size === 1) { const node = M.nodes.find(n => n.id === [...sel.nodes][0]); inspectPanel = <NodeInspector key={node.id} M={M} node={node} DB={DB} assign={assign} STATUS={STATUS_ORDER} CATS={CAT_LIST} patchNode={patchNode} delNode={(id) => delNodes([id])} toggleAgent={toggleAgent} onClose={clearSel} openRoom={openRoom} focusNode={(id) => inspectNode(id)} domName={domName} onRun={runNode} onVariant={runVariant} onWatch={addWatcher}/>; }
  else if (sel.domain) inspectPanel = <DomainPanel M={M} domKey={sel.domain} DB={DB} counts={counts} STATUS={STATUS_ORDER} CATS={CAT_LIST} patchDomain={patchDomain} assign={assign} toggleAgent={toggleAgent} onEnter={() => focusDomain(sel.domain)} onAddNode={() => addNode(sel.domain)} onUngroup={ungroupDomain} openRoom={openRoom} selectBy={selectBy} onClose={clearSel}/>;
  else inspectPanel = <SystemPanel M={M} counts={counts} total={total} STATUS={STATUS_ORDER} attention={[]} onGoto={gotoAttention} onAddDomain={() => setDomModal(true)} onEnter={(k) => { focusDomain(k); pickDomain(k); }} openRoom={openRoom}/>;

  const railW = 300, rightW = 332;
  const allExpanded = expanded.open.size === M.domains.length && expanded.collapsed.size === 0;
  const allCollapsed = expanded.collapsed.size === M.domains.length;

  return (
    <div style={{ position: 'fixed', inset: 0, background: HB.paper, color: HB.ink, fontFamily: HB.sans, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      {/* titleblock masthead */}
      <div style={{ height: 52, flexShrink: 0, display: 'flex', alignItems: 'center', gap: 14, padding: '0 16px', borderBottom: `1.5px solid ${HB.ink}`, background: HB.card, zIndex: 10 }}>
        <svg width="22" height="22" viewBox="0 0 64 64" fill="none"><path d="M10 56 V32 a22 22 0 0 1 44 0 V56" stroke={HB.accent} strokeWidth="4.5" strokeLinecap="square"/><circle cx="32" cy="22" r="5.2" fill={HB.card} stroke={HB.accent} strokeWidth="2.4"/><circle cx="32" cy="22" r="1.8" fill={HB.accent}/></svg>
        <div>
          <div style={{ fontFamily: HB.arch, fontSize: 15, textTransform: 'uppercase', letterSpacing: '0.02em', lineHeight: 1.15 }}>Arch<span style={{ color: HB.accent }}>Hub</span> <span style={{ fontFamily: HB.serif, textTransform: 'none', fontSize: 14, color: HB.inkSoft }}>· Founder Cockpit</span></div>
          <div style={{ fontFamily: HB.mono, fontSize: 7.5, color: HB.inkMute, letterSpacing: '0.2em', lineHeight: 1.4 }}>THE GRAND MAP</div>
        </div>
        <div style={{ marginLeft: 14, display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 200, height: 8, borderRadius: 4, overflow: 'hidden', display: 'flex', border: `1px solid ${HB.line}` }}>
            {STATUS_ORDER.filter(s => counts[s]).map(s => <span key={s} title={`${s}: ${counts[s]}`} style={{ width: `${counts[s] / total * 100}%`, background: STC[s] }}/>)}
          </div>
          <span style={{ fontFamily: HB.mono, fontSize: 10.5, color: HB.inkSoft }}><b style={{ color: HB.green }}>{counts.live}</b>L · <b style={{ color: HB.amber }}>{counts.partial}</b>P · <b style={{ color: HB.accent }}>{counts.vision}</b>V</span>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'stretch', border: `1px solid ${HB.line}`, borderRadius: 6, overflow: 'hidden', fontFamily: HB.mono }}>
          {[['NODES', total], ['DOMAINS', M.domains.length], ['WIRES', M.wires.length], ['SHEET', 'GA-01'], ['DRAWN', 'FOUNDER']].map(([k, v], i) => (
            <div key={k} style={{ padding: '4px 11px', borderLeft: i ? `1px solid ${HB.line}` : 'none', textAlign: 'center' }}>
              <div style={{ fontSize: 7, color: HB.inkMute, letterSpacing: '0.1em' }}>{k}</div><div style={{ fontSize: 11, color: HB.ink, marginTop: 1 }}>{v}</div>
            </div>
          ))}
        </div>
        <button onClick={() => setLeftTab('inspect')} title="Inspect" style={{ display: 'none' }}/>
        <HAvatar name="Mehdi Habib" size={28}/>
      </div>

      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        {/* LEFT — INSPECT / VIEW / INDEX */}
        <div style={{ width: railW, flexShrink: 0, borderRight: `1px solid ${HB.line}`, background: HB.card, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <div style={{ display: 'flex', borderBottom: `1px solid ${HB.line}`, flexShrink: 0 }}>
            {[['inspect', 'Inspect', 'layout'], ['view', 'View', 'eye'], ['index', 'Index', 'grid']].map(([k, l, ic]) => (
              <button key={k} onClick={() => setLeftTab(k)} style={ltab(leftTab === k)}><CKIcon name={ic} size={12}/>{l}</button>
            ))}
          </div>
          <div className="hb-scroll" style={{ flex: 1, overflow: 'auto' }}>
            {leftTab === 'inspect' && inspectPanel}
            {leftTab === 'view' && <div style={{ padding: '12px 11px' }}>
          <PanelLabel>DETAIL</PanelLabel>
          <div style={{ display: 'flex', background: HB.paper2, borderRadius: 8, padding: 3, gap: 3 }}>
            <button onClick={collapseAll} title="Show every domain as a single volume" style={segBtn(allCollapsed)}>◻ Volumes</button>
            <button onClick={expandAll} title="Resolve every domain into its nodes" style={segBtn(allExpanded)}>⊞ Nodes</button>
          </div>
          <div style={{ fontFamily: HB.mono, fontSize: 9, color: HB.inkMute, padding: '5px 4px 0', lineHeight: 1.4 }}>{allExpanded ? 'all domains open to their nodes' : allCollapsed ? 'all domains shown as volumes' : 'mixed — zoom in to resolve more'}</div>

          <PanelLabel>VIEW</PanelLabel>
          <div style={{ display: 'flex', gap: 6 }}>
            <MiniBtn onClick={() => { collapseAll(); setTimeout(fitAll, 40); }} icon="search">Frame all</MiniBtn>
            <MiniBtn onClick={autoOrganize} icon="grid">Tidy up</MiniBtn>
          </div>
          <button onClick={() => setSelMode(s => !s)} title="Drag a box on the map to select many at once — collapsed domains, or nodes inside open domains — then Group" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7, width: '100%', marginTop: 6, padding: '8px 0', borderRadius: 7, cursor: 'pointer', fontFamily: HB.mono, fontSize: 10.5, border: `1px solid ${selMode ? HB.accent : HB.line}`, background: selMode ? HB.accentSoft : HB.card, color: selMode ? HB.accentHi : HB.inkSoft }}>
            <CKIcon name="grid" size={12}/>{selMode ? 'Multi-select: ON — drag a box' : 'Multi-select (box)'}
          </button>
          <div style={{ fontFamily: HB.mono, fontSize: 9, color: HB.inkMute, padding: '5px 4px 0', lineHeight: 1.45 }}>Drag a box to grab many · or <b style={{ color: HB.inkSoft }}>⇧-click</b> domains / nodes to add · then <b style={{ color: HB.inkSoft }}>Group</b></div>

          <PanelLabel>LAYERS</PanelLabel>
          {[['wires', 'Wires'], ['params', 'Parameters'], ['labels', 'Category labels']].map(([k, l]) => <ToggleRow key={k} label={l} on={vis[k]} onClick={() => setVis(v => ({ ...v, [k]: !v[k] }))}/>)}

          <PanelLabel right={<button onClick={() => setVis(v => ({ ...v, status: new Set(STATUS_ORDER) }))} style={miniLink}>all</button>}>STATUS · SHOW</PanelLabel>
          {STATUS_ORDER.filter(s => counts[s]).map(s => (
            <button key={s} onClick={() => toggleVisStatus(s)} style={visRow(vis.status.has(s))}>
              <span style={{ width: 9, height: 9, borderRadius: 2, background: STC[s], opacity: vis.status.has(s) ? 1 : 0.3 }}/>
              <span style={{ textTransform: 'capitalize', flex: 1 }}>{s}</span>
              <span style={{ fontFamily: HB.mono, fontSize: 10, color: HB.inkMute }}>{counts[s]}</span>
              <CKIcon name={vis.status.has(s) ? 'eye' : 'x'} size={12}/>
            </button>
          ))}
            </div>}
            {leftTab === 'index' && <div style={{ padding: '12px 11px' }}>
          <PanelLabel right={<button onClick={allDomains} style={miniLink}>all</button>}>DOMAINS · {M.domains.length}</PanelLabel>
          {M.domains.map(d => { const n = M.nodes.filter(x => x.dom === d.key).length; const on = vis.domains.has(d.key); return (
            <div key={d.key} style={visRow(on)}>
              <span onClick={() => toggleVisDomain(d.key)} style={{ width: 9, height: 9, borderRadius: '50%', background: d.col, opacity: on ? 1 : 0.3, cursor: 'pointer', flexShrink: 0 }}/>
              <span onClick={() => focusDomain(d.key)} title="Open + zoom" style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', cursor: 'pointer', color: expanded.open.has(d.key) ? HB.accent : 'inherit' }}>{d.title}</span>
              <span style={{ fontFamily: HB.mono, fontSize: 10, color: HB.inkMute }}>{n}</span>
              <span onClick={() => toggleVisDomain(d.key)} style={{ cursor: 'pointer', display: 'grid', placeItems: 'center' }}><CKIcon name={on ? 'eye' : 'x'} size={12}/></span>
            </div>
          ); })}

          <PanelLabel>STEM · DROP NODES</PanelLabel>
          <div style={{ fontFamily: HB.mono, fontSize: 9, color: HB.inkMute, padding: '0 4px 6px', lineHeight: 1.4 }}>same grammar as the app canvas — wire them, type-check, translate</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, padding: '0 4px' }}>
            {STEM_KINDS.map(s => (
              <button key={s.kind} onClick={() => addConnective(s)} title={s.sub} style={{ display: 'flex', alignItems: 'center', gap: 8, textAlign: 'left', padding: '7px 9px', borderRadius: 7, border: `1px solid ${HB.line}`, background: HB.paper2, cursor: 'pointer', color: HB.ink }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = catCol(s.cat); e.currentTarget.style.background = HB.card; }} onMouseLeave={e => { e.currentTarget.style.borderColor = HB.line; e.currentTarget.style.background = HB.paper2; }}>
                <span style={{ width: 18, height: 18, borderRadius: 5, display: 'grid', placeItems: 'center', background: catCol(s.cat) + '22', color: catCol(s.cat), fontFamily: HB.mono, fontSize: 11, flexShrink: 0 }}>{s.glyph}</span>
                <span style={{ fontSize: 11.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.title}</span>
              </button>
            ))}
          </div>

          <PanelLabel>AGENTS · DROP AS NODES</PanelLabel>
          <div style={{ fontFamily: HB.mono, fontSize: 9, color: HB.inkMute, padding: '0 4px 6px', lineHeight: 1.4 }}>attaches into the open/selected domain & wires to its nodes</div>
          {DB.agents.map(a => (
            <button key={a.id} onClick={() => addAgentNode(a.id)} title="Drop onto the map" style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left', padding: '6px 8px', borderRadius: 7, border: 'none', background: 'transparent', cursor: 'pointer', color: HB.ink }}
              onMouseEnter={e => e.currentTarget.style.background = HB.paper2} onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
              <span style={{ width: 20, height: 20, borderRadius: 6, display: 'grid', placeItems: 'center', background: HB.accentSoft, color: HB.accent, flexShrink: 0 }}><CKIcon name="agent" size={12}/></span>
              <span style={{ flex: 1, fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.name}</span>
              <CKIcon name="plus" size={12} color={HB.inkMute}/>
            </button>
          ))}
            </div>}
          </div>
        </div>
        <div style={{ flex: 1, position: 'relative', minWidth: 0 }}>
          <div className="hb-blueprint" style={{ position: 'absolute', inset: 0, opacity: 0.4, pointerEvents: 'none' }}/>
          <MapCanvas ref={canvas} M={M} vis={vis} sel={sel} selMode={selMode} expanded={expanded} agentsByNode={assign} activeWires={activeWires}
            onSelect={pickNode} onSelectBox={onSelectBox} onMarquee={onMarquee} onMove={moveNode} onMoveDomain={moveDomain} onToggleDomain={toggleDomain} onToggleNode={toggleNode} openNodes={openNodes} onPickDomain={pickDomain} onPickField={pickField} onDomainContext={onDomainContext} onFieldContext={onFieldContext} onInspect={inspectNode} onNodeContext={onNodeContext} onConnect={connectNodes} onWireContext={onWireContext} query={query}/>

          {/* corner controls */}
          <div style={{ position: 'absolute', top: 12, left: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 11px', borderRadius: 8, background: HB.card, border: `1px solid ${HB.line}`, boxShadow: '0 3px 12px rgba(80,50,20,.08)' }}>
              <CKIcon name="map" size={13} color={HB.accent}/>
              <span style={{ fontFamily: HB.mono, fontSize: 11.5, color: HB.ink }}>Federated model</span>
              <span style={{ fontFamily: HB.mono, fontSize: 10, color: HB.inkMute }}>· {M.domains.length} domains</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px', borderRadius: 8, background: HB.card, border: `1px solid ${HB.line}`, width: 160 }}>
              <CKIcon name="search" size={12} color={HB.inkMute}/>
              <input value={query} onChange={e => setQuery(e.target.value)} placeholder="find…" style={{ flex: 1, border: 'none', background: 'transparent', color: HB.ink, fontSize: 12, outline: 'none' }}/>
            </div>
          </div>

          {/* SCALE LADDER — the recursive primitive, named and climbable */}
          <ScaleLadder level={scaleLevel} onClimb={climbTo}/>

          {/* LOD hint */}
          <div style={{ position: 'absolute', top: 12, right: 14, fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute, letterSpacing: '0.1em', padding: '6px 11px', background: HB.card, border: `1px solid ${HB.line}`, borderRadius: 8 }}>
            ZOOM TO RESOLVE · click a domain header to open/collapse
          </div>

          {/* selection toolbar — groups nodes→grand node, or domains(+nodes)→field */}
          {(() => {
            const selDom = (sel.domains || new Set()).size; const selCount = sel.nodes.size + selDom;
            if (selCount === 0) return null;
            const intoField = selDom >= 1; const canGroup = selCount >= 2;
            const label = selDom && sel.nodes.size ? `${selDom} domain${selDom > 1 ? 's' : ''} + ${sel.nodes.size} node${sel.nodes.size > 1 ? 's' : ''}` : selDom ? `${selDom} domain${selDom > 1 ? 's' : ''}` : `${sel.nodes.size} node${sel.nodes.size > 1 ? 's' : ''}`;
            return (
              <div style={{ position: 'absolute', bottom: 80, left: '50%', transform: 'translateX(-50%)', display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderRadius: 12, background: HB.ink, color: HB.paper, boxShadow: '0 14px 40px rgba(0,0,0,.28)' }}>
                <span style={{ fontFamily: HB.mono, fontSize: 11.5 }}>{label} selected</span>
                <div style={{ width: 1, height: 18, background: '#ffffff33' }}/>
                {canGroup && (
                  <button onClick={groupAny} title={intoField ? 'Wrap these into a field (a node one tier up)' : 'Wrap these nodes into a grand node'} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '5px 12px', borderRadius: 7, border: 'none', background: HB.accent, color: '#fff', cursor: 'pointer', fontFamily: HB.mono, fontSize: 11, fontWeight: 700 }}>
                    ⊞ Group → {intoField ? 'field' : 'grand node'}
                  </button>
                )}
                {sel.nodes.size > 0 && <DarkBtn onClick={() => requestDelete([...sel.nodes])} icon="trash">Delete</DarkBtn>}
                <DarkBtn onClick={clearSel} icon="x">Clear</DarkBtn>
              </div>
            );
          })()}

          {/* multi-select hint — always visible when nothing is grouped-up yet, so the gesture is discoverable */}
          {(() => {
            const selCount = sel.nodes.size + (sel.domains || new Set()).size;
            if (selCount > 0) return null;
            return (
              <div style={{ position: 'absolute', bottom: 80, left: '50%', transform: 'translateX(-50%)', display: 'flex', alignItems: 'center', gap: 9, padding: '7px 14px', borderRadius: 999, background: selMode ? HB.accent : HB.cardHi, color: selMode ? '#fff' : HB.inkSoft, border: `1px solid ${selMode ? HB.accent : HB.line}`, boxShadow: '0 6px 20px rgba(80,50,20,.12)', fontFamily: HB.mono, fontSize: 11, whiteSpace: 'nowrap', pointerEvents: 'none' }}>
                <span style={{ fontSize: 13 }}>⊞</span>
                {selMode
                  ? <span><b>Drag a box</b> over domains (or nodes) — then <b>Group</b></span>
                  : <span><b style={{ color: HB.accent }}>⇧-drag</b> a box, or <b style={{ color: HB.accent }}>⇧-click</b>, to multi-select → <b>Group → field</b></span>}
              </div>
            );
          })()}
          <div style={{ position: 'absolute', bottom: 16, left: '50%', transform: 'translateX(-50%)', width: 540, maxWidth: '90%' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '0 14px', height: 46, background: HB.cardHi, border: `1.5px solid ${HB.line}`, borderRadius: 999, boxShadow: '0 12px 34px rgba(80,50,20,.16)' }}>
              <span style={{ color: HB.accent }}><CKIcon name="brain" size={17}/></span>
              <input value={cmd} onChange={e => setCmd(e.target.value)} onKeyDown={e => e.key === 'Enter' && runCmd()} placeholder="Command — “enter brain”, “operate models”, “macro”, “health”…" style={{ flex: 1, border: 'none', background: 'transparent', color: HB.ink, fontSize: 13, outline: 'none', fontFamily: HB.sans }}/>
              <span style={{ fontFamily: HB.mono, fontSize: 10, color: HB.inkDim }}>↵</span>
            </div>
          </div>
        </div>

        {/* RIGHT — AGENTIC: notifications · sessions · history */}
        <div style={{ width: rightW, flexShrink: 0, borderLeft: `1px solid ${HB.line}`, background: HB.card, minHeight: 0 }}>
          <AgenticPanel M={M} DB={DB} assign={assign} attention={attention} onGoto={gotoAttention} onTuneAttention={tuneAttention}/>
        </div>
      </div>

      {domModal && <NameModal title="Create a domain" placeholder="e.g. Compliance & Audit" colors={DOM_COLS} onSave={(name, col) => { addDomain(name, col); setDomModal(false); }} onClose={() => setDomModal(false)}/>}
      {ctx && <ContextMenu ctx={ctx} M={M}
        node={ctx.type === 'node' ? M.nodes.find(n => n.id === ctx.id) : null}
        domain={ctx.type === 'domain' ? M.domains.find(d => d.key === ctx.key) : null}
        field={ctx.type === 'field' ? (M.fields || []).find(f => f.id === ctx.id) : null}
        openNodes={openNodes}
        selCount={sel.nodes.size + (sel.domains || new Set()).size}
        nodeDomGrouped={ctx.type === 'node' ? !!(M.domains.find(d => d.key === (M.nodes.find(n => n.id === ctx.id) || {}).dom) || {}).grouped : false}
        nodeField={ctx.type === 'node' ? fieldOf((M.nodes.find(n => n.id === ctx.id) || {}).dom) : null}
        domField={ctx.type === 'domain' ? fieldOf(ctx.key) : null}
        onClose={() => setCtx(null)}
        actions={{
          run: () => runNode(ctx.id), watch: () => addWatcher(ctx.id),
          pipeline: () => toggleNode(ctx.id, !openNodes.has(ctx.id)),
          freeze: () => freezeNode(ctx.id), duplicate: () => duplicateNode(ctx.id),
          disconnect: () => disconnectAll(ctx.id), del: () => requestDelete([ctx.id]),
          cutWire: () => disconnectWire(ctx.a, ctx.b),
          group: groupAny,
          ungroupGrandFromNode: () => { const n = M.nodes.find(x => x.id === ctx.id); if (n) ungroupDomain(n.dom); },
          ungroupGrand: () => ungroupDomain(ctx.key),
          ungroupFieldFromDomain: () => { const f = fieldOf(ctx.key); if (f) ungroupField(f.id); },
          ungroupField: () => ungroupField(ctx.id),
          openDomain: () => { const d = M.domains.find(x => x.key === ctx.key); toggleDomain(ctx.key, !(expanded.open.has(ctx.key) || (!expanded.collapsed.has(ctx.key)))); pickDomain(ctx.key); },
          enterDomain: () => focusDomain(ctx.key),
          addNodeHere: () => addNode(ctx.key),
          groupField: groupIntoField,
        }}/>}
      {confirmDel && <ConfirmModal count={confirmDel.ids.length}
        names={confirmDel.ids.map(id => (M.nodes.find(n => n.id === id) || {}).title).filter(Boolean)}
        wires={M.wires.filter(w => confirmDel.ids.includes(w.a) || confirmDel.ids.includes(w.b)).length}
        onCancel={() => setConfirmDel(null)} onConfirm={() => { delNodes(confirmDel.ids); setConfirmDel(null); }}/>}
      {toast && <div style={{ position: 'fixed', bottom: 74, left: '50%', transform: 'translateX(-50%)', zIndex: 80, background: HB.ink, color: HB.paper, borderRadius: 999, padding: '8px 16px', fontSize: 12, fontFamily: HB.mono, boxShadow: '0 14px 40px rgba(0,0,0,.3)', display: 'flex', alignItems: 'center', gap: 8 }}><span style={{ color: HB.accent }}><CKIcon name="check" size={13}/></span>{toast}</div>}
    </div>
  );
}

/* left-panel atoms */
const PanelLabel = ({ children, right }) =><div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontFamily: HB.mono, fontSize: 8.5, color: HB.inkMute, letterSpacing: '0.16em', padding: '14px 6px 7px' }}><span>{children}</span>{right}</div>;
const miniLink = { border: 'none', background: 'transparent', color: HB.accent, cursor: 'pointer', fontFamily: HB.mono, fontSize: 9, letterSpacing: '0.1em' };
const ltab = (on) => ({ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5, padding: '10px 0', border: 'none', borderBottom: `2px solid ${on ? HB.accent : 'transparent'}`, background: 'transparent', cursor: 'pointer', fontFamily: HB.mono, fontSize: 10.5, letterSpacing: '0.04em', color: on ? HB.ink : HB.inkMute });
const segBtn = (on) => ({ flex: 1, padding: '6px 0', borderRadius: 6, border: 'none', cursor: 'pointer', fontFamily: HB.mono, fontSize: 10.5, background: on ? HB.card : 'transparent', color: on ? HB.accentHi : HB.inkSoft, boxShadow: on ? '0 1px 4px rgba(0,0,0,.08)' : 'none' });
const visRow = (on) => ({ display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left', padding: '6px 8px', borderRadius: 7, border: 'none', background: 'transparent', cursor: 'default', color: on ? HB.ink : HB.inkMute, fontSize: 12, opacity: on ? 1 : 0.7 });
const MiniBtn = ({ children, onClick, on, icon }) => <button onClick={onClick} style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, padding: '7px 0', borderRadius: 7, cursor: 'pointer', fontFamily: HB.mono, fontSize: 10.5, border: `1px solid ${on ? HB.accent : HB.line}`, background: on ? HB.accentSoft : HB.card, color: on ? HB.accentHi : HB.inkSoft }}><CKIcon name={icon} size={12}/>{children}</button>;
const ToggleRow = ({ label, on, onClick }) => <button onClick={onClick} style={{ display: 'flex', alignItems: 'center', gap: 9, width: '100%', padding: '7px 8px', borderRadius: 7, border: 'none', background: 'transparent', cursor: 'pointer', color: HB.ink, fontSize: 12 }}><span style={{ width: 30, height: 17, borderRadius: 99, background: on ? HB.accent : HB.line, position: 'relative', flexShrink: 0 }}><span style={{ position: 'absolute', top: 2, left: on ? 15 : 2, width: 13, height: 13, borderRadius: '50%', background: '#fff', transition: 'left .15s' }}/></span>{label}</button>;
const DarkBtn = ({ children, onClick, icon }) => <button onClick={onClick} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '5px 10px', borderRadius: 7, border: '1px solid #ffffff22', background: '#ffffff10', color: HB.paper, cursor: 'pointer', fontFamily: HB.mono, fontSize: 11 }}><CKIcon name={icon} size={12}/>{children}</button>;

/* right-click contextual menu (node · domain · field · wire) */
function ContextMenu({ ctx, node, domain, field, openNodes, selCount, nodeDomGrouped, nodeField, domField, actions, onClose }) {
  React.useEffect(() => { const h = () => onClose(); window.addEventListener('click', h); window.addEventListener('contextmenu', h); return () => { window.removeEventListener('click', h); window.removeEventListener('contextmenu', h); }; }, []);
  let items;
  if (ctx.type === 'wire') items = [{ icon: 'trash', label: 'Cut this wire', fn: actions.cutWire, danger: true }];
  else if (ctx.type === 'field') items = [
    { icon: 'eye', label: 'Focus field', fn: () => {} , dim: true },
    { icon: 'grid', label: 'Ungroup field — keep domains', fn: actions.ungroupField },
  ];
  else if (ctx.type === 'domain') items = [
    { icon: 'eye', label: 'Open / collapse', fn: actions.openDomain },
    { icon: 'layout', label: 'Enter domain', fn: actions.enterDomain },
    { icon: 'plus', label: 'Add node', fn: actions.addNodeHere },
    { sep: true },
    ...(selCount >= 2 ? [{ icon: 'grid', label: 'Group selection → field', fn: actions.groupField, accent: true }] : []),
    ...(domain && domain.grouped ? [{ icon: 'grid', label: 'Ungroup grand node', fn: actions.ungroupGrand }] : []),
    ...(domField ? [{ icon: 'grid', label: 'Ungroup from field', fn: actions.ungroupFieldFromDomain }] : []),
  ];
  else items = [
    ...(selCount >= 2 ? [{ icon: 'grid', label: 'Group selection → grand node', fn: actions.group, accent: true }, { sep: true }] : []),
    { icon: 'play', label: node && node.frozen ? 'Run (frozen)' : 'Run node', fn: actions.run, dim: node && node.frozen },
    { icon: 'eye', label: 'Add watcher', fn: actions.watch },
    { icon: 'layout', label: openNodes.has(ctx.id) ? 'Collapse pipeline' : 'Open pipeline', fn: actions.pipeline },
    { sep: true },
    { icon: 'lock', label: node && node.frozen ? 'Unfreeze' : 'Freeze node', fn: actions.freeze, on: node && node.frozen },
    { icon: 'plus', label: 'Duplicate', fn: actions.duplicate },
    { icon: 'link', label: 'Disconnect all wires', fn: actions.disconnect },
    ...(nodeDomGrouped ? [{ sep: true }, { icon: 'grid', label: 'Ungroup grand node', fn: actions.ungroupGrandFromNode }] : []),
    { sep: true },
    { icon: 'trash', label: 'Delete node…', fn: actions.del, danger: true },
  ];
  const W = 224, est = items.length * 34 + 10;
  const x = Math.min(ctx.x, window.innerWidth - W - 8), y = Math.min(ctx.y, window.innerHeight - est - 8);
  const head = ctx.type === 'node' && node ? { tag: (node.cat || '').toUpperCase() + (node.frozen ? ' · FROZEN' : ''), title: node.title }
    : ctx.type === 'domain' && domain ? { tag: domain.grouped ? 'GRAND NODE · GROUPED' : 'DOMAIN · SUPER-NODE', title: domain.title }
    : ctx.type === 'field' && field ? { tag: 'FIELD · SUPER GRAND NODE', title: field.title } : null;
  return (
    <div onClick={e => e.stopPropagation()} onContextMenu={e => { e.preventDefault(); e.stopPropagation(); }} style={{ position: 'fixed', left: x, top: y, width: W, zIndex: 200, background: HB.card, border: `1px solid ${HB.line}`, borderRadius: 10, boxShadow: '0 16px 50px rgba(40,30,20,.3)', padding: 5, fontFamily: HB.sans }}>
      {head && <div style={{ padding: '7px 9px 8px', borderBottom: `1px solid ${HB.lineSoft}`, marginBottom: 4 }}><div style={{ fontFamily: HB.mono, fontSize: 8, color: HB.inkMute, letterSpacing: '0.14em' }}>{head.tag}</div><div style={{ fontSize: 13, fontWeight: 600, color: HB.ink, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{head.title}</div></div>}
      {items.map((it, i) => it.sep ? <div key={i} style={{ height: 1, background: HB.lineSoft, margin: '4px 6px' }}/> : (
        <button key={i} onClick={() => { it.fn(); onClose(); }} style={{ display: 'flex', alignItems: 'center', gap: 10, width: '100%', textAlign: 'left', padding: '8px 9px', borderRadius: 7, border: 'none', background: it.on ? HB.accentSoft : 'transparent', cursor: 'pointer', color: it.danger ? HB.red : it.accent ? HB.accentHi : it.dim ? HB.inkMute : HB.ink, fontSize: 12.5, fontWeight: it.accent ? 700 : 400, opacity: it.dim ? 0.6 : 1 }}
          onMouseEnter={e => e.currentTarget.style.background = it.danger ? HB.red + '14' : HB.paper2} onMouseLeave={e => e.currentTarget.style.background = it.on ? HB.accentSoft : 'transparent'}>
          <CKIcon name={it.icon} size={14}/>{it.label}
        </button>
      ))}
    </div>
  );
}

/* delete-with-warning */
function ConfirmModal({ count, names, wires, onCancel, onConfirm }) {
  return (
    <div onClick={onCancel} style={{ position: 'fixed', inset: 0, zIndex: 210, background: 'rgba(40,32,24,0.4)', display: 'grid', placeItems: 'center', animation: 'hbFade .14s' }}>
      <div onClick={e => e.stopPropagation()} style={{ width: 380, background: HB.card, border: `1px solid ${HB.line}`, borderRadius: 14, padding: 20, boxShadow: '0 30px 80px rgba(60,40,20,.3)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <span style={{ width: 34, height: 34, borderRadius: 9, display: 'grid', placeItems: 'center', background: HB.red + '1e', color: HB.red, flexShrink: 0 }}><CKIcon name="trash" size={17}/></span>
          <div style={{ fontFamily: HB.serif, fontSize: 21, letterSpacing: '-0.01em' }}>Delete {count > 1 ? `${count} nodes` : 'node'}?</div>
        </div>
        <div style={{ fontSize: 13, color: HB.inkSoft, lineHeight: 1.55 }}>
          {count === 1 && names[0] ? <>This removes <b style={{ color: HB.ink }}>{names[0]}</b> from the model.</> : <>This removes <b style={{ color: HB.ink }}>{count} nodes</b> from the model.</>}
          {wires > 0 && <> It also cuts <b style={{ color: HB.ink }}>{wires}</b> wire{wires > 1 ? 's' : ''} connected to {count > 1 ? 'them' : 'it'}.</>} This can't be undone.
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 18 }}>
          <HBtn onClick={onCancel}>Cancel</HBtn>
          <HBtn onClick={onConfirm} style={{ background: HB.red, borderColor: HB.red, color: '#fff' }}><CKIcon name="trash" size={13}/>Delete</HBtn>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { AtlasCockpit, STATUS_ORDER, CAT_LIST, DOM_COLS });
ReactDOM.createRoot(document.getElementById('root')).render(<AtlasCockpit/>);
