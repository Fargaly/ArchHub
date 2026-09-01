// atlas-engine.jsx — the Grand Map as ONE federated BIM-style model.
// Everything in a single coordinated graph: all 14 domains, all 203 nodes, all
// 389 wires — at once. Level-of-detail by zoom: zoomed out you see domain volumes
// wired together; zoom in and the nodes resolve INSIDE their domains with live
// wiring. Domains can also be expanded/collapsed in place. Vellum drafting (HB).

const { HB } = window;
const NW = 152, NHt = 86;
const STC = { live: HB.green, partial: HB.amber, vision: HB.accent, blocked: HB.red, planned: HB.blue, prototype: HB.cyan || HB.blue, deprecated: HB.inkMute };
const CATCOL = { ai: HB.purple, skill: HB.blue, connector: HB.cyan || HB.blue, logic: HB.purple, custom: HB.blue, output: HB.green, input: HB.blue, trigger: HB.amber, compose: HB.accent, transform: HB.amber, host: HB.cyan || HB.blue, agent: HB.accent, watch: HB.green, preview: HB.cyan || HB.blue, note: HB.inkMute, adapter: HB.amber, slider: HB.blue, rule: HB.purple, globals: HB.cyan || HB.blue, attention: HB.accent };
const catCol = (c) => CATCOL[c] || HB.inkMute;
const DETAIL_W = 1650;          // viewBox width below which domains auto-resolve to nodes

// every node is a micro-domain: a detailed internal pipeline. Generated
// deterministically from category when not explicitly authored, so it's never empty.
const PIPE_ARCHE = {
  ai:        ['prompt assemble', 'context inject', 'model call', 'stream parse', 'validate', 'emit'],
  skill:     ['trigger', 'gather inputs', 'plan steps', 'execute', 'verify', 'write back'],
  connector: ['handshake', 'auth', 'open channel', 'marshal', 'heartbeat', 'reconnect'],
  logic:     ['receive', 'evaluate rules', 'branch', 'transform', 'emit'],
  compose:   ['collect', 'layout', 'render', 'paginate', 'export'],
  transform: ['parse', 'normalize', 'map', 'serialize'],
  input:     ['capture', 'sanitize', 'normalize', 'publish'],
  output:    ['subscribe', 'format', 'deliver', 'ack'],
  host:      ['discover', 'bind', 'session', 'dispatch'],
  trigger:   ['listen', 'debounce', 'match', 'fire'],
  custom:    ['input', 'process', 'output'],
  note:      ['note'],
};
const PSTAGE_COL = { in: HB.blue, process: HB.purple, out: HB.green };

// Every wire carries a typed SIGNAL = the canonical port type from the app's node
// grammar (stem-core.jsx DATA_TYPES). Same vocabulary as the in-app session canvas,
// so what's wired here is wired there. Category → its emitted data-type.
const SIGNAL = {
  ai: 'completion', skill: 'intent', connector: 'record', logic: 'boolean', compose: 'document',
  transform: 'object', input: 'string', output: 'any', host: 'host', trigger: 'exec',
  agent: 'intent', watch: 'view', preview: 'view', custom: 'any', note: 'any',
  adapter: 'any', slider: 'number', rule: 'boolean', globals: 'object', attention: 'number',
};
const sigOf = (n) => (n ? (SIGNAL[n.cat] || 'any') : 'any');
const typeOf = sigOf;
// type → colour (stem-core WIRE/typeCol families)
const TYPECOL = {
  any: HB.inkMute, string: HB.cyan || HB.blue, number: HB.blue, boolean: HB.amber,
  object: HB.purple, list: HB.purple, record: HB.accent, file: HB.green, view: HB.cyan || HB.blue,
  intent: HB.purple, completion: HB.purple, document: HB.accent, host: HB.cyan || HB.blue,
  exec: HB.ink, trigger: HB.amber, image: HB.accent, event: HB.amber,
};
const typeColOf = (t) => TYPECOL[t] || HB.inkMute;
// graph.py validate_v2: identical types pass; ANY bridges anything; else needs an Adapter.
const archCanConnect = (s, d) => s === d || s === 'any' || d === 'any';

// a node's ports = typed in/out sockets, reflected from its wiring
function nodePorts(M, id) {
  const ins = [], outs = [];
  M.wires.forEach(w => {
    if (w.b === id) { const s = M.nodes.find(n => n.id === w.a); if (s) ins.push({ peer: s, why: w.why, sig: sigOf(s) }); }
    if (w.a === id) { const t = M.nodes.find(n => n.id === w.b); if (t) outs.push({ peer: t, why: w.why, sig: sigOf(t) }); }
  });
  return { ins, outs };
}

function nodePipeline(n) {
  if (n.pipeline && n.pipeline.length) return n.pipeline;
  const arche = PIPE_ARCHE[n.cat] || PIPE_ARCHE.custom;
  return arche.map((t, i) => ({ id: n.id + '_s' + i, t, role: i === 0 ? 'in' : i === arche.length - 1 ? 'out' : 'process', status: i === 0 ? 'live' : i < arche.length - 1 ? (n.status === 'vision' ? 'vision' : 'partial') : n.status }));
}

const MapCanvas = React.forwardRef(function MapCanvas(props, ref) {
  const { M, vis, sel, selMode, expanded, openNodes, agentsByNode, activeWires, onSelect, onSelectBox, onMarquee, onMove, onMoveDomain, onToggleDomain, onToggleNode, onInspect, onNodeContext, onConnect, onWireContext, query } = props;
  const svgRef = React.useRef(null);
  const worldRef = React.useRef(null);   // wrapper <g>: carries the live pan transform
  // FULL BOX — the extent "frame all" fits. Domains sitting OFF the published layout grid
  // are excluded from the FRAMING only (they still render, exactly where they are). One
  // off-cell box used to inflate the frame from 2610 to 3707 wide — a ~21% shrink of the
  // whole map that undid the label legibility work. The test is exact against M.grid, not
  // statistical, so there is no threshold to tune and nothing is silently rewritten.
  const layout = React.useMemo(() => {
    const ds = M.domains;
    if (!ds.length) return { box: { x: 0, y: 0, w: 1000, h: 800 }, outliers: [] };
    const g = M.grid;
    const aligned = (d) => {
      if (!g) return true;
      const rx = Math.abs((d.x - g.x0) % g.px), ry = Math.abs((d.y - g.y0) % g.py);
      return Math.min(rx, g.px - rx) <= 2 && Math.min(ry, g.py - ry) <= 2;
    };
    // cell coords, then keep only the contiguous run of occupied rows/cols containing the
    // MODE row/col — a domain across an empty gap is off-grid even if perfectly aligned.
    const cell = (d) => ({ c: Math.round((d.x - g.x0) / g.px), r: Math.round((d.y - g.y0) / g.py) });
    const run = (vals) => {
      const cnt = {}; vals.forEach(v => cnt[v] = (cnt[v] || 0) + 1);
      const occ = Object.keys(cnt).map(Number).sort((a, b) => a - b);
      const mode = occ.reduce((m, v) => cnt[v] > cnt[m] ? v : m, occ[0]);
      let lo = mode, hi = mode;
      while (occ.indexOf(lo - 1) >= 0) lo--;
      while (occ.indexOf(hi + 1) >= 0) hi++;
      return { lo, hi };
    };
    let keep = ds.filter(aligned);
    if (g && keep.length) {
      const cs = keep.map(d => cell(d));
      const R = run(cs.map(c => c.r)), C = run(cs.map(c => c.c));
      keep = keep.filter(d => { const c = cell(d); return c.r >= R.lo && c.r <= R.hi && c.c >= C.lo && c.c <= C.hi; });
    }
    if (keep.length < Math.max(2, Math.ceil(ds.length * 0.5))) keep = ds;
    const xs = keep.map(d => d.x), ys = keep.map(d => d.y);
    const xe = keep.map(d => d.x + d.w), ye = keep.map(d => d.y + d.h);
    const x0 = Math.min(...xs), y0 = Math.min(...ys);
    return {
      box: { x: x0 - 60, y: y0 - 60, w: Math.max(...xe) - x0 + 120, h: Math.max(...ye) - y0 + 120 },
      outliers: ds.filter(d => keep.indexOf(d) < 0).map(d => d.key),
    };
  }, [M.domains, M.grid]);
  const fullBox = layout.box;
  const offGridKey = layout.outliers.join('|');
  React.useEffect(() => { if (props.onOffGrid) props.onOffGrid(layout.outliers); }, [offGridKey]);
  const [vb, setVb] = React.useState(fullBox);
  const vbRef = React.useRef(vb); vbRef.current = vb;
  const raf = React.useRef(null); const drag = React.useRef(null);
  const [marquee, setMarquee] = React.useState(null);
  const [wire, setWire] = React.useState(null);
  const wireRef = React.useRef(null); wireRef.current = wire;
  const [hovDom, setHovDom] = React.useState(null);
  const [hovWire, setHovWire] = React.useState(null);
  const [dragDom, setDragDom] = React.useState(null);
  const dragDomRef = React.useRef(null); dragDomRef.current = dragDom;
  const domMovedRef = React.useRef(false);
  const off = (dom) => (dragDom && dragDom.key === dom ? dragDom : { dx: 0, dy: 0 });

  // cached canvas rect — refreshed by the ResizeObserver below, not per pointer event
  const rectRef = React.useRef(null);
  const rect = () => rectRef.current || (svgRef.current ? (rectRef.current = svgRef.current.getBoundingClientRect()) : { left: 0, top: 0, width: 1000, height: 800 });
  const [pxW, setPxW] = React.useState(0);
  React.useEffect(() => {
    // SELF-HEALING SIZE SIGNAL. This effect used to bail permanently when svgRef.current was
    // null on its single pass, and it only observed the <svg> itself — so a flex sibling
    // changing width produced NO re-render, the label attributes kept whatever size the last
    // render computed, and every screen-size floor appeared broken while actually never being
    // recomputed. It now never early-returns: it (re)attaches its observer whenever the ref
    // appears, watches the parent box too, and polls as a floor. pxW exists only to tell React
    // that geometry moved; the size maths reads the painted transform.
    let last = 0, ro = null, seen = null;
    const read = () => {
      const el = svgRef.current;
      if (!el) return;
      if (el !== seen) {                       // ref appeared or swapped — (re)subscribe
        seen = el;
        if (ro) ro.disconnect();
        ro = new ResizeObserver(read);
        ro.observe(el);
        if (el.parentElement) ro.observe(el.parentElement);
      }
      const r = el.getBoundingClientRect();
      rectRef.current = r;
      const w = r.width || 0;
      if (!w || Math.abs(w - last) < 2) return;
      last = w; setPxW(w);
    };
    read();
    window.addEventListener('resize', read);
    const poll = setInterval(read, 400);
    const inval = () => { rectRef.current = null; };
    window.addEventListener('scroll', inval, true);
    return () => {
      window.removeEventListener('resize', read);
      clearInterval(poll);
      if (ro) ro.disconnect();
      window.removeEventListener('scroll', inval, true);
    };
  }, []);
  // ── VIEWBOX TRANSPORT ──
  // The map is ~1400 SVG elements (204 node cards, 397 wire bundles, 794 sockets). Routing
  // every pan/zoom frame through React state re-rendered that whole tree per frame, which
  // is what made the motion stutter. During MOTION we write the viewBox straight to the DOM
  // — zero React work, the browser just re-rasterises — and commit to state once the
  // gesture settles, so everything derived from vb (label scaling, macro thresholds)
  // updates on a single render at the end.
  const pushVB = (v) => {
    vbRef.current = v;
    const el = svgRef.current;
    if (el) el.setAttribute('viewBox', `${v.x} ${v.y} ${v.w} ${v.h}`);
  };
  const commitTO = React.useRef(null);
  const commitVB = (delay = 0) => {
    clearTimeout(commitTO.current);
    commitTO.current = setTimeout(() => setVb({ ...vbRef.current }), delay);
  };
  const setVB = (v) => { pushVB(v); commitVB(0); };

  // Eased pan/zoom. Driven by rAF; falls back to a timer running the SAME ease if the frame
  // loop is starved (embedded/background frames) — so the motion stays smooth there instead
  // of snapping straight to the destination.
  const animFb = React.useRef(null);
  const animateTo = (t, ms = 460) => {
    cancelAnimationFrame(raf.current); clearInterval(animFb.current);
    const from = { ...vbRef.current }, t0 = performance.now();
    const ease = x => 1 - Math.pow(1 - x, 3);
    const at = (now) => {
      const p = Math.min(1, (now - t0) / ms), e = ease(p);
      pushVB({ x: from.x + (t.x - from.x) * e, y: from.y + (t.y - from.y) * e, w: from.w + (t.w - from.w) * e, h: from.h + (t.h - from.h) * e });
      if (p >= 1) { cancelAnimationFrame(raf.current); clearInterval(animFb.current); commitVB(0); return true; }
      return false;
    };
    let rafAlive = false;
    const step = (now) => { rafAlive = true; if (!at(now)) raf.current = requestAnimationFrame(step); };
    raf.current = requestAnimationFrame(step);
    setTimeout(() => { if (!rafAlive) animFb.current = setInterval(() => at(performance.now()), 16); }, 80);
  };
  const aspect = () => { const r = rect(); return r.height / r.width; };
  // FRAME — fits a world box inside the canvas SAFE AREA, not the raw viewport: the
  // masthead, scale ladder, hint bar and command bar float over the map, so centering
  // blindly buries the first and last rows under them.
  // Insets measured against the floating chrome: masthead + scale ladder above, hint bar +
  // command bar below. Content is fitted INSIDE this rect, never under the overlays.
  const SAFE = { t: 92, b: 84, l: 22, r: 22 };
  const frame = (x, y, w, h, pad = 0.03) => {
    const r = rect();
    const W = r.width || 1000, H = r.height || 800;
    const px = w * pad, py = h * pad;
    const tx = x - px, ty = y - py, tw = w + px * 2, th = h + py * 2;
    const availW = Math.max(80, W - SAFE.l - SAFE.r), availH = Math.max(80, H - SAFE.t - SAFE.b);
    const k = Math.min(availW / tw, availH / th);        // px per world unit
    const nw = W / k, nh = H / k;
    // centre the target inside the safe rect, then back out to the full viewBox
    const offX = SAFE.l + (availW - tw * k) / 2, offY = SAFE.t + (availH - th * k) / 2;
    animateTo({ x: tx - offX / k, y: ty - offY / k, w: nw, h: nh });
  };

  React.useImperativeHandle(ref, () => ({
    fitAll: () => frame(fullBox.x, fullBox.y, fullBox.w, fullBox.h, 0.02),
    focusDomain: (key) => { const d = M.domains.find(x => x.key === key); if (d) frame(d.x - 20, d.y - 20, d.w + 40, d.h + 40, 0.06); },
    focusNode: (id) => { const n = M.nodes.find(x => x.id === id); if (n) frame(n.x - 280, n.y - 200, NW + 560, NHt + 400, 0.04); },
    zoomTo: (w) => { const c = { x: vbRef.current.x + vbRef.current.w / 2, y: vbRef.current.y + vbRef.current.h / 2 }; const nh = w * aspect(); animateTo({ x: c.x - w / 2, y: c.y - nh / 2, w, h: nh }); },
  }));
  React.useEffect(() => { const t = setTimeout(() => frame(fullBox.x, fullBox.y, fullBox.w, fullBox.h, 0.02), 60); return () => clearTimeout(t); }, []);

  // published so the shell can resolve a library DROP point into world coordinates
  React.useEffect(() => { window.__atlasToWorld = (cx, cy) => toWorld(cx, cy); return () => { delete window.__atlasToWorld; }; }, []);
  const toWorld = (cx, cy) => { const r = rect(); return { x: vbRef.current.x + (cx - r.left) / r.width * vbRef.current.w, y: vbRef.current.y + (cy - r.top) / r.height * vbRef.current.h }; };
  const onWheel = (e) => { e.preventDefault(); const w = toWorld(e.clientX, e.clientY); const f = e.deltaY < 0 ? 0.85 : 1.18; const r = rect(); const nw = Math.min(fullBox.w * 1.3, Math.max(360, vbRef.current.w * f)); const nh = nw * (r.height / r.width); cancelAnimationFrame(raf.current); clearInterval(animFb.current); const t = { x: w.x - (w.x - vbRef.current.x) * (nw / vbRef.current.w), y: w.y - (w.y - vbRef.current.y) * (nh / vbRef.current.h), w: nw, h: nh }; perFrame(() => pushVB(t)); commitVB(140); };
  const onDown = (e) => {
    if (e.target.closest('.atlas-node') || e.target.closest('.dom-head')) return;
    if (selMode || e.shiftKey) { const w = toWorld(e.clientX, e.clientY); drag.current = { mode: 'marquee', sx: w.x, sy: w.y, additive: e.shiftKey }; setMarquee({ x: w.x, y: w.y, w: 0, h: 0 }); }
    else { drag.current = { mode: 'pan', sx: e.clientX, sy: e.clientY, vb0: { ...vbRef.current } }; if (!e.metaKey) onSelect(null, false); }
  };
  // one state update per animation frame, no matter how many mousemoves arrive
  const coalesce = React.useRef({ raf: 0, timer: 0, fn: null });
  // Coalesce to one update per frame, but NEVER depend on rAF alone: in a throttled or
  // background frame rAF may never fire, and since every pan and zoom routes through here that
  // silently froze the viewBox — the map could not be moved or zoomed at all, which also left
  // the node-card zoom gate with no way out. A timer races the frame callback; whichever
  // arrives first runs the work and cancels the other.
  const perFrame = (fn) => {
    coalesce.current.fn = fn;
    if (coalesce.current.raf || coalesce.current.timer) return;
    const run = () => {
      if (coalesce.current.raf) { cancelAnimationFrame(coalesce.current.raf); coalesce.current.raf = 0; }
      if (coalesce.current.timer) { clearTimeout(coalesce.current.timer); coalesce.current.timer = 0; }
      const f = coalesce.current.fn; coalesce.current.fn = null; if (f) f();
    };
    coalesce.current.raf = requestAnimationFrame(run);
    coalesce.current.timer = setTimeout(run, 24);
  };

  const onMoveBg = (e) => {
    if (!drag.current) return; const r = rect();
    if (drag.current.mode === 'pan') {
      const dx = (e.clientX - drag.current.sx) / r.width * drag.current.vb0.w, dy = (e.clientY - drag.current.sy) / r.height * drag.current.vb0.h;
      drag.current.dx = dx; drag.current.dy = dy;
      if (worldRef.current) worldRef.current.setAttribute('transform', `translate(${dx} ${dy})`);
    }
    else if (drag.current.mode === 'marquee') { const w = toWorld(e.clientX, e.clientY); perFrame(() => setMarquee({ x: Math.min(w.x, drag.current.sx), y: Math.min(w.y, drag.current.sy), w: Math.abs(w.x - drag.current.sx), h: Math.abs(w.y - drag.current.sy) })); }
    else if (drag.current.mode === 'node') { const w = toWorld(e.clientX, e.clientY); drag.current.moved = drag.current.moved || Math.abs(e.clientX - drag.current.sx) + Math.abs(e.clientY - drag.current.sy) > 3; const nx = w.x - drag.current.off.x, ny = w.y - drag.current.off.y; drag.current.el.setAttribute('transform', `translate(${nx},${ny})`); drag.current.last = { x: nx, y: ny }; }
    else if (drag.current.mode === 'domain') { const w = toWorld(e.clientX, e.clientY); const dx = w.x - drag.current.ox, dy = w.y - drag.current.oy; if (Math.abs(dx) + Math.abs(dy) > 4) { drag.current.moved = true; domMovedRef.current = true; } perFrame(() => setDragDom({ key: drag.current && drag.current.key, dx, dy })); }
    else if (drag.current.mode === 'wire') { const w = toWorld(e.clientX, e.clientY); perFrame(() => setWire({ from: drag.current && drag.current.from, x: w.x, y: w.y })); }
  };
  const onUp = () => {
    if (!drag.current) return;
    if (drag.current.mode === 'marquee' && marquee) {
      const r = marquee; const hit = (x, y, w, h) => x + w > r.x && x < r.x + r.w && y + h > r.y && y < r.y + r.h;
      // open domains → grab their nodes; collapsed domains → grab the domain itself (one gesture, every scale)
      const ids = M.nodes.filter(n => domOpen(n.dom) && hit(n.x, n.y, NW, NHt)).map(n => n.id);
      const domKeys = M.domains.filter(d => !domOpen(d.key) && hit(d.x, d.y, d.w, d.h)).map(d => d.key);
      if (onMarquee) onMarquee(ids, domKeys, drag.current.additive); else onSelectBox(ids, drag.current.additive);
      setMarquee(null);
    }
    if (drag.current.mode === 'pan') {
      const d = drag.current, g = worldRef.current;
      if (d.dx || d.dy) pushVB({ ...vbRef.current, x: d.vb0.x - d.dx, y: d.vb0.y - d.dy });
      if (g) g.removeAttribute('transform');
      commitVB(0);   // one render after the gesture, not per frame
    }
    if (drag.current.mode === 'node' && drag.current.moved && drag.current.last) onMove(drag.current.id, drag.current.last.x, drag.current.last.y);
    if (drag.current.mode === 'domain') { const dd = dragDomRef.current; if (drag.current.moved && dd) onMoveDomain(drag.current.key, dd.dx, dd.dy); setDragDom(null); }
    if (drag.current.mode === 'wire') { const wp = wireRef.current; if (wp) { const t = M.nodes.filter(n => visN(n) && domOpen(n.dom)).find(n => { const o = off(n.dom); const x = n.x + o.dx, y = n.y + o.dy; const w = openNodes.has(n.id) ? Math.max(NW, 56 + nodePipeline(n).length * 104) : NW; const h = openNodes.has(n.id) ? 150 : NHt; return wp.x >= x && wp.x <= x + w && wp.y >= y && wp.y <= y + h; }); if (t && t.id !== drag.current.from) onConnect && onConnect(drag.current.from, t.id); } setWire(null); }
    drag.current = null;
  };
  React.useEffect(() => () => { cancelAnimationFrame(raf.current); clearInterval(animFb.current); clearTimeout(commitTO.current); }, []);
  React.useEffect(() => { window.addEventListener('mousemove', onMoveBg); window.addEventListener('mouseup', onUp); return () => { window.removeEventListener('mousemove', onMoveBg); window.removeEventListener('mouseup', onUp); }; });
  const nodeDown = (e, n) => { if (selMode || n.frozen) return; e.stopPropagation(); const w = toWorld(e.clientX, e.clientY); drag.current = { mode: 'node', id: n.id, sx: e.clientX, sy: e.clientY, off: { x: w.x - n.x, y: w.y - n.y }, el: e.currentTarget, moved: false }; };
  const startWire = (e, n) => { e.stopPropagation(); const w = toWorld(e.clientX, e.clientY); drag.current = { mode: 'wire', from: n.id }; setWire({ from: n.id, x: w.x, y: w.y }); };
  const nodeCtx = (e, n) => { e.preventDefault(); e.stopPropagation(); onNodeContext && onNodeContext(n.id, e.clientX, e.clientY); };
  const domDown = (e, d) => { if (e.shiftKey) { e.stopPropagation(); return; } if (selMode) return; e.stopPropagation(); const w = toWorld(e.clientX, e.clientY); domMovedRef.current = false; drag.current = { mode: 'domain', key: d.key, ox: w.x, oy: w.y, moved: false }; };

  // ── LOD: a domain resolves to nodes when zoomed in OR force-expanded; collapses when force-collapsed ──
  const autoDetail = vb.w < DETAIL_W;
  const domOpen = (key) => { if (expanded.collapsed.has(key)) return false; if (expanded.open.has(key)) return true; return autoDetail; };
  // open domains hug their member nodes (so dragging a node reshapes the domain); collapsed use authored box
  // mass = members + external wiring; normalised 0..1 across the model
  const domMass = React.useMemo(() => {
    const memb = {}, deg = {};
    M.domains.forEach(d => { memb[d.key] = 0; deg[d.key] = 0; });
    M.nodes.forEach(n => { if (memb[n.dom] != null) memb[n.dom]++; });
    const domOfN = {}; M.nodes.forEach(n => domOfN[n.id] = n.dom);
    M.wires.forEach(w => { const a = domOfN[w.a], b = domOfN[w.b]; if (a && b && a !== b) { if (deg[a] != null) deg[a]++; if (deg[b] != null) deg[b]++; } });
    const raw = {}; M.domains.forEach(d => raw[d.key] = memb[d.key] + deg[d.key] * 0.8);
    const vals = Object.values(raw); const lo = Math.min(...vals), hi = Math.max(...vals);
    const out = {}; M.domains.forEach(d => out[d.key] = hi > lo ? (raw[d.key] - lo) / (hi - lo) : 0.5);
    return { t: out, members: memb, degree: deg };
  }, [M.domains, M.nodes, M.wires]);
  const domBounds = (d) => {
    if (!domOpen(d.key)) {
      // 0.62 → 1.0 of the authored cell: the lightest domain reads as clearly smaller than
      // the heaviest, without any box shrinking so far that its title stops fitting.
      const k = 0.78 + 0.22 * (domMass.t[d.key] != null ? domMass.t[d.key] : 0.5);
      const w = Math.round(d.w * k), h = Math.round(d.h * k);
      // centred in its cell so the grid rhythm survives
      return { x: d.x + Math.round((d.w - w) / 2), y: d.y + Math.round((d.h - h) / 2), w, h };
    }
    const ms = M.nodes.filter(n => n.dom === d.key);
    if (!ms.length) return { x: d.x, y: d.y, w: d.w, h: d.h };
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    ms.forEach(n => { const w = openNodes.has(n.id) ? Math.max(NW, 56 + nodePipeline(n).length * 104) : NW; const h = openNodes.has(n.id) ? 150 : NHt; x0 = Math.min(x0, n.x); y0 = Math.min(y0, n.y); x1 = Math.max(x1, n.x + w); y1 = Math.max(y1, n.y + h); });
    const padX = 26, padT = 56, padB = 26;
    return { x: x0 - padX, y: y0 - padT, w: (x1 - x0) + padX * 2, h: (y1 - y0) + padT + padB };
  };
  const domCenter = (d) => { const b = domBounds(d); return { x: b.x + b.w / 2, y: b.y + b.h / 2 }; };
  const nodeAnchor = (id) => { const n = M.nodes.find(x => x.id === id); if (!n) return null; const o = off(n.dom); if (domOpen(n.dom)) return { x: n.x + NW / 2 + o.dx, y: n.y + NHt / 2 + o.dy }; const d = M.domains.find(x => x.key === n.dom); return d ? { x: domCenter(d).x + o.dx, y: domCenter(d).y + o.dy } : null; };
  const domOf = React.useMemo(() => { const o = {}; M.nodes.forEach(n => o[n.id] = n.dom); return o; }, [M]);
  const nodeById = React.useMemo(() => { const m = {}; M.nodes.forEach(n => m[n.id] = n); return m; }, [M]);
  // typed port index: every node's in/out sockets, reflected from the wire graph (computed once)
  const portIndex = React.useMemo(() => {
    const idx = {}; M.nodes.forEach(n => idx[n.id] = { ins: [], outs: [] });
    M.wires.forEach(w => { const a = nodeById[w.a], b = nodeById[w.b]; if (!a || !b || a.id === b.id) return; const t = w.t || sigOf(a); idx[a.id].outs.push({ peer: b, why: w.why, sig: t }); idx[b.id].ins.push({ peer: a, why: w.why, sig: t }); });
    // DECLARED ports: params the user promoted, fields added, triggers — wireable knobs with no peer yet
    M.nodes.forEach(n => { const dp = n.ports || {}; (dp.ins || []).forEach(p => idx[n.id] && idx[n.id].ins.push({ declared: true, label: p.id, sig: p.t || 'any' })); (dp.outs || []).forEach(p => idx[n.id] && idx[n.id].outs.push({ declared: true, label: p.id, sig: p.t || 'any' })); });
    return idx;
  }, [M, nodeById]);
  // domain interface: roll-up of member nodes' cross-domain ports, grouped by peer domain (a reflection)
  const domIface = React.useMemo(() => {
    const out = {}; M.domains.forEach(d => out[d.key] = { inb: {}, outb: {} });
    M.wires.forEach(w => { const a = nodeById[w.a], b = nodeById[w.b]; if (!a || !b || a.dom === b.dom) return; if (out[a.dom]) out[a.dom].outb[b.dom] = (out[a.dom].outb[b.dom] || 0) + 1; if (out[b.dom]) out[b.dom].inb[a.dom] = (out[b.dom].inb[a.dom] || 0) + 1; });
    return out;
  }, [M, nodeById]);

  const visN = (n) => vis.domains.has(n.dom) && vis.status.has(n.status) && (!query || ((n.title || '') + (n.sub || '')).toLowerCase().includes(query.toLowerCase()));

  // ── wires: BUNDLED & WEIGHTED. Endpoints resolve to node (open) or domain centre
  // (collapsed); wires sharing the same pair collapse into one weighted edge. ──
  const endpoint = (id) => {
    const n = M.nodes.find(x => x.id === id); if (!n) return null; const o = off(n.dom);
    if (domOpen(n.dom)) {
      const isO = openNodes.has(id);
      const w = isO ? Math.max(NW, 56 + nodePipeline(n).length * 104) : NW;
      const h = isO ? 150 : NHt;
      return { key: 'n:' + id, x: n.x + w / 2 + o.dx, y: n.y + h / 2 + o.dy, dom: n.dom, box: { x: n.x + o.dx, y: n.y + o.dy, w, h } };
    }
    const d = M.domains.find(x => x.key === n.dom); if (!d) return null; const c = domCenter(d);
    return { key: 'd:' + n.dom, x: c.x + o.dx, y: c.y + o.dy, dom: n.dom };
  };
  // clip a wire endpoint to the node-card boundary so wires meet edges, not centers
  const trimToBox = (box, toward) => {
    const cx = box.x + box.w / 2, cy = box.y + box.h / 2; const dx = toward.x - cx, dy = toward.y - cy;
    if (!dx && !dy) return { x: cx, y: cy };
    const t = Math.min((box.w / 2 + 3) / (Math.abs(dx) || 1e-6), (box.h / 2 + 3) / (Math.abs(dy) || 1e-6));
    return { x: cx + dx * t, y: cy + dy * t };
  };
  // KNOB MAP — ONE authority for every collapsed domain's boundary sockets. Both the knob
  // render and the wire resolver read from this, so a wire always lands ON its socket.
  // (Previously each computed its own top-6 slice, so any peer past the 6th fell back to
  // the box centre and the wire visibly missed the knob.) Every wired peer gets a socket;
  // spacing compresses to fit the box rather than truncating the list.
  const knobMap = React.useMemo(() => {
    const out = {};
    M.domains.forEach(d => {
      if (domOpen(d.key)) return;
      const iface = domIface[d.key]; if (!iface) return;
      const bb = domBounds(d);
      const mk = (entries, side) => {
        const list = entries.filter(([k]) => vis.domains.has(k) && k !== d.key).sort((a, b2) => b2[1] - a[1]);
        const n = list.length; if (!n) return;
        const span = Math.max(0, bb.h - 150);
        const gap = n > 1 ? Math.min(34, span / (n - 1)) : 0;
        list.forEach(([pk, ct], i) => {
          out[d.key] = out[d.key] || {};
          out[d.key][pk] = {
            x: side === 'L' ? bb.x : bb.x + bb.w,
            y: bb.y + bb.h / 2 + (i - (n - 1) / 2) * gap,
            side, ct, peer: pk, gap,
          };
        });
      };
      // a peer appears on ONE side only — outbound wins, so a bidirectional pair gets a
      // single socket instead of two that both claim the same wire.
      const outE = Object.entries(iface.outb);
      const outKeys = new Set(outE.map(([k]) => k));
      mk(outE, 'R');
      mk(Object.entries(iface.inb).filter(([k]) => !outKeys.has(k)), 'L');
    });
    return out;
  }, [M, domIface, vis.domains, expanded, openNodes]);

  // NODE SOCKET MAP — the same single-authority rule as knobMap, one level down. Positions
  // are LOCAL to the node origin; both the port render and the wire resolver read them, so
  // a node-level wire terminates exactly on its socket instead of on an arbitrary point of
  // the card boundary. Every wired peer gets a socket (spacing compresses to fit) — the old
  // 5-port cap silently orphaned the rest.
  const nodeSock = React.useMemo(() => {
    const out = {};
    M.nodes.forEach(n => {
      const pp = portIndex[n.id]; if (!pp) return;
      const isO = openNodes.has(n.id);
      const w = isO ? Math.max(NW, 56 + nodePipeline(n).length * 104) : NW;
      const h = isO ? 150 : NHt;
      const rec = { ins: {}, outs: {}, list: [], w, h };
      const rail = (arr, edgeX, side) => {
        const cnt = arr.length; if (!cnt) return;
        const span = Math.max(0, h - 24);
        const gap = cnt > 1 ? Math.min(11, span / (cnt - 1)) : 0;
        arr.forEach((p, i) => {
          const s = { lx: edgeX, ly: h / 2 + (i - (cnt - 1) / 2) * gap, side, port: p, sig: p.sig };
          rec.list.push(s);
          if (p.peer) rec[side === 'in' ? 'ins' : 'outs'][p.peer.id] = s;
        });
      };
      rail(pp.ins, 0, 'in');
      rail(pp.outs, w, 'out');
      out[n.id] = rec;
    });
    return out;
  }, [M, portIndex, openNodes]);

  // world position of a node's socket facing a given peer (open domains only)
  const nodePortPos = (id, peerId, prefer) => {
    const n = nodeById[id]; if (!n || !domOpen(n.dom)) return null;
    const rec = nodeSock[id]; if (!rec) return null;
    const s = prefer === 'out' ? (rec.outs[peerId] || rec.ins[peerId]) : (rec.ins[peerId] || rec.outs[peerId]);
    if (!s) return null;
    const o = off(n.dom);
    return { x: n.x + s.lx + o.dx, y: n.y + s.ly + o.dy, side: s.side === 'in' ? 'L' : 'R', sock: true };
  };

  // resolve a COLLAPSED domain's boundary socket toward a given peer domain.
  const domPortPos = (domKey, peerKey) => {
    const d = M.domains.find(x => x.key === domKey); if (!d || domOpen(domKey)) return null;
    const k = knobMap[domKey] && knobMap[domKey][peerKey]; if (!k) return null;
    const o = off(domKey);
    return { x: k.x + o.dx, y: k.y + o.dy, knob: true };
  };
  const domCol = (k) => (M.domains.find(d => d.key === k) || {}).col || HB.inkMute;
  // Filled by the domain map, emitted after the wire layer — see "DOMAIN IDENTITY" below.
  const domChrome = [];
  const wireEls = vis.wires ? (() => {
    const bundles = {};
    M.wires.forEach(w => {
      const da = domOf[w.a], db = domOf[w.b]; if (!da || !db) return;
      if (!vis.domains.has(da) || !vis.domains.has(db)) return;
      const A = endpoint(w.a), B = endpoint(w.b); if (!A || !B || A.key === B.key) return;
      const k = [A.key, B.key].sort().join('|');
      if (!bundles[k]) bundles[k] = { A, B, wt: 0, da, db, rel: false, ia: w.a, ib: w.b };
      bundles[k].wt++; if (sel.nodes.has(w.a) || sel.nodes.has(w.b)) bundles[k].rel = true;
    });
    const labelOf = (bd) => {
      const nm = (id) => { const n = nodeById[id]; if (n) return n.title;
        const d = M.domains.find(x => x.key === id); return d ? d.title : id; };
      const an = bd.da !== bd.db ? (M.domains.find(x => x.key === bd.da) || {}).title : nm(bd.ia);
      const bn = bd.da !== bd.db ? (M.domains.find(x => x.key === bd.db) || {}).title : nm(bd.ib);
      return (an || bd.da) + ' → ' + (bn || bd.db);
    };
    return Object.entries(bundles).map(([k, bd]) => {
      const { A, B, wt } = bd; const cross = bd.da !== bd.db; const rel = bd.rel;
      const hovW = hovWire === k, selW = sel.wire && sel.wire.key === k;
      const hot = hovDom && (bd.da === hovDom || bd.db === hovDom);
      const nodeWire = A.box && B.box;   // both endpoints resolved to node cards — a real zoomed-in relation
      // MACRO LEGIBILITY: 72 cross-domain bundles at full weight reads as spaghetti. At rest
      // the inter-domain layer is a quiet substrate; hovering a domain or selecting a node
      // brings ITS relations forward. Node-level wires (zoomed in) always draw at full weight.
      const quiet = cross && !nodeWire && !rel && !hot;
      const col = rel ? HB.accent : hot ? domCol(hovDom) : domCol(bd.da);
      const sw = rel ? 3.4
        : quiet ? Math.min(2.6, 0.9 + Math.log2(wt + 1) * 0.55)
        : Math.min(8, 1.9 + Math.log2(wt + 1) * (cross ? 1.6 : 1.0));
      const pa = A.box ? null : domPortPos(bd.da, bd.db);
      const pb = B.box ? null : domPortPos(bd.db, bd.da);
      // node-level: terminate on the actual typed socket, not the card boundary
      const sa = A.box ? nodePortPos(bd.ia, bd.ib, 'out') : null;
      const sb = B.box ? nodePortPos(bd.ib, bd.ia, 'in') : null;
      const a0 = sa || (A.box ? trimToBox(A.box, B) : (pa || A));
      const b0 = sb || (B.box ? trimToBox(B.box, A) : (pb || B));
      const knobbed = !!(pa || pb || sa || sb);
      const op = selW ? 1 : hovW ? 0.95 : rel ? 0.97 : hovDom ? (hot ? 0.95 : 0.06) : sel.nodes.size ? 0.05
        : quiet ? 0.3 : nodeWire ? 0.72 : 0.6;
      // Socket-terminated wires leave the boundary HORIZONTALLY, like a node editor — a
      // cubic whose control points sit outboard of each socket. Reads as plugged in.
      const dpath = (() => {
        if (knobbed) {
          const dx = Math.max(nodeWire ? 26 : 60, Math.abs(b0.x - a0.x) * 0.42);
          const e1 = sa || pa, e2 = sb || pb;
          const s1 = e1 && e1.side === 'L' ? -1 : e1 ? 1 : (a0.x > b0.x ? -1 : 1);
          const s2 = e2 && e2.side === 'L' ? -1 : e2 ? 1 : (b0.x > a0.x ? -1 : 1);
          return `M${a0.x},${a0.y} C${a0.x + dx * s1},${a0.y} ${b0.x + dx * s2},${b0.y} ${b0.x},${b0.y}`;
        }
        const mx = (a0.x + b0.x) / 2, my = (a0.y + b0.y) / 2 + (cross && !nodeWire ? -34 : 0);
        return `M${a0.x},${a0.y} Q${mx},${my} ${b0.x},${b0.y}`;
      })();
      const mx = (a0.x + b0.x) / 2, my = (a0.y + b0.y) / 2 + (cross && !nodeWire && !knobbed ? -34 : 0);
      const ang = Math.atan2(b0.y - a0.y, b0.x - a0.x); const ah = Math.max(5, Math.min(9, sw + 2));
      return (
        <g key={k} style={{ transition: 'opacity .15s' }}>
          {op > 0.3 && !quiet && <path d={dpath} fill="none" stroke={col} strokeWidth={sw + 3} opacity={op * 0.18} strokeLinecap="round"/>}
          <path d={dpath} fill="none" stroke={selW ? HB.accent : col} strokeWidth={selW ? sw + 2.2 : hovW ? sw + 1.4 : sw} opacity={selW ? 1 : hovW ? Math.max(op, 0.9) : op} strokeLinecap="round"/>
          {/* pick target — the wire itself is selectable, inspectable and removable */}
          <path d={dpath} fill="none" stroke="transparent" strokeWidth={Math.max(13, sw + 11)} strokeLinecap="round"
            style={{ pointerEvents: 'stroke', cursor: 'pointer' }}
            onMouseEnter={() => setHovWire(k)} onMouseLeave={() => setHovWire(null)}
            onClick={ev => { ev.stopPropagation(); props.onPickWire && props.onPickWire({ key: k, a: bd.ia, b: bd.ib, da: bd.da, db: bd.db, wt, cross }); }}
            onContextMenu={ev => { ev.preventDefault(); ev.stopPropagation(); props.onWireContext && props.onWireContext(bd.ia, bd.ib, ev.clientX, ev.clientY, { key: k, wt, da: bd.da, db: bd.db }); }}>
            <title>{labelOf(bd) + ' · ' + wt + (wt > 1 ? ' wires' : ' wire')}</title>
          </path>
          {selW && <text x={mx} y={my - (sw + 9)} fontSize={Math.max(cardFs(11), sw * 3.4)} fontFamily={HB.mono} fontWeight="700" textAnchor="middle" fill={HB.accent}>{labelOf(bd)}</text>}
          {nodeWire && op > 0.2 && !knobbed && <path d={`M${b0.x - Math.cos(ang) * ah - Math.cos(ang - 0.5) * ah},${b0.y - Math.sin(ang) * ah - Math.sin(ang - 0.5) * ah} L${b0.x - Math.cos(ang) * ah},${b0.y - Math.sin(ang) * ah} L${b0.x - Math.cos(ang) * ah - Math.cos(ang + 0.5) * ah},${b0.y - Math.sin(ang) * ah - Math.sin(ang + 0.5) * ah}`} fill="none" stroke={col} strokeWidth={Math.max(1.4, sw * 0.7)} opacity={op}/>}
          {cross && !nodeWire && wt > 1 && hot && <text x={mx} y={my - 4} fontSize={cardFs(11)} fontFamily={HB.mono} fontWeight="700" textAnchor="middle" fill={col} opacity={0.95}>{wt}</text>}
        </g>
      );
    });
  })() : null;

  // ONE authority for header type: the title's real size, and where the header block ends.
  // Both the readout and the badge derive from these, so a short title (which sizes up to the
  // height cap rather than the width cap) can never run into the line beneath it.
  const titleSize = (d, b) => Math.max(12 * upp, Math.min(scr(15), b.h * 0.115));
  // ellipsize to the box: the cap limits how many CHARACTERS are drawn, not how big they are
  const fitTitle = (d, b, fsz) => {
    const t = String(d.title || '');
    // 22 left inset + the right-aligned readout's gutter. Keep the reserve tight and the
    // per-character factor honest (serif mixed case ≈ 0.44em) so a title keeps as much of its
    // meaning as the box allows — "Canvas & Grap…" tells you far more than "Canvas…".
    const avail = b.w - 22 - Math.max(52, scr(38, 120));
    const max = Math.floor(avail / Math.max(0.001, fsz * 0.44));
    if (max >= t.length) return t;
    if (max < 2) return '';
    return t.slice(0, max - 1).replace(/[\s&,·]+$/, '') + '\u2026';
  };
  const headerBottom = (d, b) => b.y + 26 + titleSize(d, b) * 1.5;
  const rollup = (ns) => { const s = {}; ns.forEach(n => s[n.status] = (s[n.status] || 0) + 1); return s; };
  const cardLegible = () => (NW / upp) >= 90;
  // status tally: floored to 9px on screen, drawn only if that size still fits the column
  const tallyPitch = (b) => { const avail = b.w - 60; const cols = Math.max(1, Math.floor(avail / 104)); return avail / cols; };
  const tallyFs = (b) => Math.max(9 * upp, Math.min(13, tallyPitch(b) * 0.13));
  const tallyFit = (b) => tallyFs(b) <= tallyPitch(b) * 0.2;              // is a node card wide enough to carry text?
  const cardFs = (px) => Math.max(9 * upp, px * Math.max(1, upp * 0.55));
  const fitStr = (str, availWorld, fsz) => {
    const t = String(str || '');
    const max = Math.floor(availWorld / Math.max(0.001, fsz * 0.44));
    if (max >= t.length) return t;
    if (max < 2) return '';
    return t.slice(0, max - 1).replace(/[\s:·,&]+$/, '') + '\u2026';
  };

  // SCREEN-CONSTANT TYPE — the whole model is ~2700×3000 world units, so at "fit all" a
  // 20px world label renders at ~5px and the map turns into unreadable confetti. Domain
  // identity (title, count, tally) is chrome, not geometry: it keeps a fixed SCREEN size
  // by scaling with world-units-per-pixel (observed, not measured mid-render), clamped so
  // it never dwarfs its own box.
  // Measure the element LIVE rather than trusting the pxW state mirror: pxW is only a
  // re-render trigger, and if its observer subscription goes stale the mirror silently keeps
  // the mount-time width — which made every screen floor below compute against 808px while
  // the map was actually 420px, dragging domain titles to 6px. The live rect is the truth at
  // paint time; pxW stays purely as the signal that tells React to re-render.
  // WORLD UNITS PER SCREEN PIXEL — read from the RENDERED transform, not from state.
  // The viewBox is written imperatively to the DOM by pushVB during pan/zoom without a state
  // update, so the `vb` state and the real viewBox routinely diverge; dividing the STATE width
  // by the live pixel width therefore under-reported the zoom-out and silently collapsed every
  // screen-size floor below (domain titles rendered at 7px on a narrow map). getScreenCTM().a
  // is the actual world→screen scale the browser is painting with, so it cannot disagree with
  // what the user sees. vbRef (the imperative source of truth) is the fallback, never `vb`.
  const upp = (() => {
    const el = svgRef.current;
    if (el && el.getScreenCTM) { const m = el.getScreenCTM(); if (m && m.a) return 1 / m.a; }
    // hostW is a change-signal, not a measurement — always measure the element itself.
    const w = (el && el.getBoundingClientRect().width) || props.hostW || pxW;
    const src = vbRef.current || vb;
    return w ? src.w / w : 1;
  })();
  const scr = (px, maxWorld) => Math.min(maxWorld == null ? Infinity : maxWorld, px * Math.max(1, upp));
  const macro = upp > 1.9;   // zoomed out far enough that node-level detail is noise

  // ── active run flow: animated pulse along wires currently carrying a run ──
  const flowEls = (activeWires && activeWires.size) ? [...activeWires].map(key => {
    const [a, b] = key.split('>'); const A = endpoint(a), B = endpoint(b); if (!A || !B) return null;
    const mx = (A.x + B.x) / 2, my = (A.y + B.y) / 2;
    return (
      <g key={'flow' + key}>
        <path d={`M${A.x},${A.y} Q${mx},${my} ${B.x},${B.y}`} fill="none" stroke={HB.accent} strokeWidth={2.6} opacity={0.9} className="rt-flow"/>
        <circle r={4} fill={HB.accent}><animateMotion dur="0.9s" repeatCount="indefinite" path={`M${A.x},${A.y} Q${mx},${my} ${B.x},${B.y}`}/></circle>
      </g>
    );
  }) : null;

  return (
    <svg ref={svgRef} viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`} onMouseDown={onDown} onWheel={onWheel}
         style={{ width: '100%', height: '100%', display: 'block', cursor: selMode ? 'crosshair' : (drag.current && drag.current.mode === 'pan' ? 'grabbing' : 'grab') }}>
      <g ref={worldRef}>
      {/* FIELDS — super grand nodes: a labelled boundary that encloses its member domains.
          A field is just another node one tier up; it follows its members as they move. */}
      {(() => {
        // A field encloses domains AND other fields, so its boundary is computed RECURSIVELY
        // and its padding grows with tier — a tier-3 boundary visibly contains the tier-2 one
        // inside it. Depth is unbounded: this walks whatever the founder built.
        const byId = {}; (M.fields || []).forEach(f => byId[f.id] = f);
        const depthOf = (id, seen) => { const f = byId[id]; if (!f) return 0;
          const g = seen || new Set(); if (g.has(id)) return 0; g.add(id);
          const k = (f.fieldIds || []).map(x => depthOf(x, g)); return 1 + (k.length ? Math.max(...k) : 0); };
        const boundsOf = (id, seen) => {
          const f = byId[id]; if (!f) return null;
          const g = seen || new Set(); if (g.has(id)) return null; g.add(id);
          let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity, any = false;
          M.domains.filter(d => (f.domKeys || []).includes(d.key) && vis.domains.has(d.key)).forEach(d => {
            const o = off(d.key), b = domBounds(d); any = true;
            x0 = Math.min(x0, b.x + o.dx); y0 = Math.min(y0, b.y + o.dy);
            x1 = Math.max(x1, b.x + b.w + o.dx); y1 = Math.max(y1, b.y + b.h + o.dy);
          });
          (f.fieldIds || []).forEach(k => { const cb = boundsOf(k, g); if (cb) { any = true;
            x0 = Math.min(x0, cb.x0); y0 = Math.min(y0, cb.y0); x1 = Math.max(x1, cb.x1); y1 = Math.max(y1, cb.y1); } });
          return any ? { x0, y0, x1, y1 } : null;
        };
        // deepest first, so an outer tier paints behind the tiers it contains
        const ordered = [...(M.fields || [])].sort((a, b) => depthOf(b.id) - depthOf(a.id));
        return ordered.map(f => {
          const bb = boundsOf(f.id); if (!bb) return null;
          const tier = depthOf(f.id);
          const pad = 30 + tier * 22, tabH = 26 + tier * 3;
          const bx = bb.x0 - pad, by = bb.y0 - pad - tabH, bw = (bb.x1 - bb.x0) + pad * 2, bh = (bb.y1 - bb.y0) + pad * 2 + tabH;
          const selF = sel.field === f.id || (sel.fields && sel.fields.has(f.id));
          const col = f.col || HB.blue;
          const SUP = ['', '', '²', '³', '⁴', '⁵', '⁶', '⁷', '⁸', '⁹'];
          const sup = tier > 1 ? (SUP[tier] != null ? SUP[tier] : '^' + tier) : '';
          const label = `FIELD${sup} · ${(f.title || '').toUpperCase()}`;
          const members = (f.domKeys || []).length + (f.fieldIds || []).length;
          return (
            <g key={f.id}>
              <rect x={bx} y={by} width={bw} height={bh} rx={26 + tier * 6} fill={col + (tier > 1 ? '14' : '0d')} stroke={selF ? col : col + 'b0'} strokeWidth={selF ? 3 : 2} strokeDasharray={tier > 1 ? '22 10' : '14 9'} style={{ pointerEvents: 'none', filter: `drop-shadow(0 0 8px ${col}44)` }}/>
              <g style={{ cursor: 'pointer' }} onClick={e => { e.stopPropagation(); props.onPickField && props.onPickField(f.id, e.shiftKey || e.metaKey); }} onContextMenu={e => { e.preventDefault(); e.stopPropagation(); props.onFieldContext && props.onFieldContext(f.id, e.clientX, e.clientY); }}>
                <rect x={bx + 20} y={by} width={Math.max(196, label.length * 8.4 + 82)} height={tabH} rx={9} fill={col}/>
                <text x={bx + 36} y={by + tabH * 0.68} fontSize={cardFs(12.5)} fontFamily={HB.mono} fontWeight="700" letterSpacing="0.14em" fill={(window.AH && window.AH.onFill) || "#180f08"}>⬡ {label}</text>
                <text x={bx + Math.max(196, label.length * 8.4 + 82) + 4} y={by + tabH * 0.68} fontSize={cardFs(10)} fontFamily={HB.mono} fill={col}>{members}</text>
              </g>
            </g>
          );
        });
      })()}
      {/* domain volumes — fills, ports and borders. Identity text is deferred to domChrome
          below so the wire layer cannot strike through it. */}
      {M.domains.filter(d => vis.domains.has(d.key)).map(d => {
        const open = domOpen(d.key); const ms = M.nodes.filter(n => n.dom === d.key); const st = rollup(ms);
        const isSelDom = sel.domain === d.key || (sel.domains && sel.domains.has(d.key)); const o = off(d.key); const b = domBounds(d);
        return (
          <g key={d.key} transform={`translate(${o.dx},${o.dy})`} onMouseEnter={() => setHovDom(d.key)} onMouseLeave={() => setHovDom(null)} onContextMenu={e => { e.preventDefault(); e.stopPropagation(); props.onDomainContext && props.onDomainContext(d.key, e.clientX, e.clientY); }}>
            <rect x={b.x} y={b.y} width={b.w} height={b.h} rx={18} fill={open ? HB.paper2 : HB.card} stroke={isSelDom || hovDom === d.key ? d.col : HB.line} strokeWidth={isSelDom ? 2.4 : 1.4} strokeDasharray={d.grouped ? '9 6' : undefined} opacity={open ? 0.6 : 1} style={{ filter: open ? 'none' : 'drop-shadow(0 5px 16px rgba(0,0,0,.1))', transition: 'none' }}/>
            {d.grouped && <text x={b.x + b.w - 20} y={b.y + 26 + titleSize(d, b) * 0.78} fontSize={Math.max(9 * upp, Math.min(scr(8), b.h * 0.036))} fontFamily={HB.mono} letterSpacing="0.16em" textAnchor="end" fill={d.col} opacity={0.8} style={{ pointerEvents: 'none' }}>⊞ GROUPED</text>}
            <rect x={b.x} y={b.y} width={6} height={b.h} rx={3} fill={d.col} opacity={0.85}/>
            {/* domain header (drag to move the whole super-node; click toggles open/collapse).
                Pushed to domChrome so it paints above the wires. */}
            {domChrome.push(
            <g key={'hd' + d.key} transform={`translate(${o.dx},${o.dy})`}
               onMouseEnter={() => setHovDom(d.key)} onMouseLeave={() => setHovDom(null)}
               onContextMenu={e => { e.preventDefault(); e.stopPropagation(); props.onDomainContext && props.onDomainContext(d.key, e.clientX, e.clientY); }}>
            <g className="dom-head" style={{ cursor: dragDom && dragDom.key === d.key ? 'grabbing' : 'grab' }} onMouseDown={e => domDown(e, d)} onClick={e => { e.stopPropagation(); if (domMovedRef.current) { domMovedRef.current = false; return; } if (e.shiftKey || e.metaKey || e.ctrlKey) { props.onPickDomain && props.onPickDomain(d.key, true); return; } onToggleDomain(d.key, !open); props.onPickDomain && props.onPickDomain(d.key); }}>
              <rect x={b.x + 10} y={b.y + 10} width={b.w - 20} height={Math.max(34, scr(30, 90))} rx={8} fill="transparent"/>
              {(() => {
                const fsz = titleSize(d, b);
                return <text x={b.x + 22} y={b.y + 26 + fsz * 0.78} fontSize={fsz} fontWeight="700" fontFamily={HB.serif} fill={d.col}><title>{d.title}</title>{fitTitle(d, b, fsz)}</text>;
              })()}
              {(() => {
                const fsz = Math.max(11 * upp, Math.min(scr(10.5), b.h * 0.062));
                return <text x={b.x + 22} y={headerBottom(d, b) + fsz * 0.86} fontSize={fsz} fontFamily={HB.mono} fill={HB.inkSoft}>{(d.params || []).length ? '⚙ ' + (d.params || []).length + ' · ' : ''}{ms.length} capabilities · {open ? '▾' : '▸'}</text>;
              })()}
            </g>
            </g>) && null}
            {/* collapsed: volume summary — also identity, so also deferred */}
            {!open && domChrome.push(<g key={'sm' + d.key} transform={`translate(${o.dx},${o.dy})`}>{(() => {
              const blocked = st.blocked || 0; const vision = st.vision || 0; const live = st.live || 0;
              const risk = blocked > 0 ? 'blocked' : (vision / (ms.length || 1) > 0.5 ? 'vision' : (live / (ms.length || 1) > 0.4 ? 'live' : null));
              const riskCol = risk === 'blocked' ? HB.red : risk === 'vision' ? HB.accent : risk === 'live' ? HB.green : null;
              return (
              <g style={{ pointerEvents: 'none' }}>
                {riskCol && <rect x={b.x} y={b.y} width={b.w} height={b.h} rx={18} fill="none" stroke={riskCol} strokeWidth={2.4} opacity={0.85}/>}
                {blocked > 0 && <g transform={`translate(${b.x + b.w - 30},${b.y + 18})`}><circle r={scr(7, 30)} fill={HB.red}/><text y={scr(3.5, 14)} fontSize={scr(9, 42)} fontWeight="700" fontFamily={HB.mono} textAnchor="middle" fill={(window.AH && window.AH.onFill) || "#180f08"}>{blocked}</text></g>}
                {(() => {
                  // ONE headline per card, sized from the box so it cannot collide: the
                  // dominant status. The raw count already reads in the header line, so a
                  // giant duplicate numeral was both redundant and the worst overflow.
                  const top = Object.entries(st).sort((a, c) => c[1] - a[1])[0];
                  if (!top) return null;
                  const fsz = Math.min(b.h * 0.16, b.w * 0.1);
                  const sub = Math.max(10 * upp, fsz * 0.28);
                  return (
                    <g>
                      <text x={b.x + b.w / 2} y={b.y + b.h * 0.56} fontSize={fsz} fontWeight="700" fontFamily={HB.serif} textAnchor="middle" fill={STC[top[0]] || d.col} opacity={0.95}>{top[1]}</text>
                      <text x={b.x + b.w / 2} y={b.y + b.h * 0.56 + fsz * 0.34 + sub * 1.5} fontSize={sub} fontFamily={HB.mono} letterSpacing="0.12em" textAnchor="middle" fill={HB.inkSoft}>{String(top[0]).toUpperCase()}</text>
                    </g>
                  );
                })()}
                {tallyFit(b) && <g transform={`translate(${b.x + 30},${b.y + b.h - 60})`}>
                  <rect width={b.w - 60} height={12} rx={6} fill={HB.paper}/>
                  {(() => { let acc = 0; const tot = ms.length || 1; return Object.entries(st).map(([s, n]) => { const w = (b.w - 60) * n / tot; const seg = <rect key={s} x={acc} width={w} height={12} fill={STC[s]}/>; acc += w; return seg; }); })()}
                </g>}
                {tallyFit(b) && (() => {
                  const avail = b.w - 60;
                  const entries = Object.entries(st);
                  const cols = Math.max(1, Math.min(entries.length, Math.floor(avail / 104)));
                  const pitch = avail / cols;
                  const fs = tallyFs(b);
                  return (
                    <g transform={`translate(${b.x + 30},${b.y + b.h - 36})`}>
                      {entries.slice(0, cols).map(([s, c], i) => (
                        <g key={s} transform={`translate(${i * pitch},0)`}>
                          <rect width={fs * 0.75} height={fs * 0.75} rx={2} y={2} fill={STC[s]}/>
                          <text x={fs * 1.15} y={fs * 0.85} fontSize={fs} fontFamily={HB.mono} fill={HB.inkSoft}>{c} {s}</text>
                        </g>
                      ))}
                      {entries.length > cols && <text x={avail} y={fs * 0.85} fontSize={fs} fontFamily={HB.mono} textAnchor="end" fill={HB.inkDim}>+{entries.length - cols}</text>}
                    </g>
                  );
                })()}
              </g>
              );
            })()}</g>) && null}
            {/* INTERFACE SOCKETS — read from knobMap, the same authority the wires resolve
                against, so every wire terminates exactly on its socket. */}
            {!open && (() => {
              const ks = knobMap[d.key]; if (!ks) return null;
              const entries = Object.values(ks);
              const hovK = hovDom && hovDom !== d.key ? hovDom : null;
              return (
                <g style={{ pointerEvents: 'none' }}>
                  {entries.map(k => {
                    const pc = (M.domains.find(x => x.key === k.peer) || {}).col || HB.inkMute;
                    const lit = !hovK || k.peer === hovK;
                    const lx = k.x + (k.side === 'L' ? scr(11, 50) : -scr(11, 50));
                    return (
                      <g key={k.side + k.peer} opacity={lit ? 1 : 0.18}>
                        <circle cx={k.x} cy={k.y} r={scr(4.6, 20)} fill={HB.paper} stroke={pc} strokeWidth={scr(1.7, 7)}/>
                        <circle cx={k.x} cy={k.y} r={scr(1.8, 8)} fill={pc}/>
                        {(!macro || lit) && (() => { const fsz = Math.min(scr(8.5), (k.gap || 34) * 0.62);
                          // the socket-gap cap can drive this to ~5px, which reads as speckle rather
                          // than a number — below 9px on screen the dot alone carries the connection
                          if (fsz / upp < 9) return null;
                          return <text x={lx} y={k.y + fsz * 0.36} fontSize={fsz} fontFamily={HB.mono} fontWeight="700" textAnchor={k.side === 'L' ? 'start' : 'end'} fill={pc} opacity={0.9}>{k.ct}</text>; })()}
                      </g>
                    );
                  })}
                  {entries.some(k => k.side === 'L') && <text x={b.x + 13} y={b.y + 62} fontSize={cardFs(8)} fontFamily={HB.mono} letterSpacing="0.12em" fill={HB.blue}>▸ IN</text>}
                  {entries.some(k => k.side === 'R') && <text x={b.x + b.w - 13} y={b.y + 62} fontSize={cardFs(8)} fontFamily={HB.mono} letterSpacing="0.12em" textAnchor="end" fill={HB.green}>OUT ▸</text>}
                </g>
              );
            })()}
          </g>
        );
      })}

      {/* all wires (federated) */}
      <g>{wireEls}</g>
      {/* active run flow */}
      <g>{flowEls}</g>

      {/* DOMAIN IDENTITY — painted after the wires so a bundle can never strike through a
          title. This layer is chrome: titles, capability lines, status tallies, badges. */}
      <g>{domChrome}</g>

      {/* nodes of open domains */}
      {M.nodes.filter(n => visN(n) && domOpen(n.dom)).map(n => {
        const isSel = sel.nodes.has(n.id); const ags = agentsByNode[n.id] || []; const o = off(n.dom);
        const isOpen = openNodes.has(n.id);
        if (isOpen) {
          const pipe = nodePipeline(n); const PW = Math.max(NW, 56 + pipe.length * 104), PH = 150;
          return (
            <g key={n.id} className="atlas-node" transform={`translate(${n.x + o.dx},${n.y + o.dy})`} style={{ cursor: 'pointer' }}
               onMouseDown={e => nodeDown(e, n)} onClick={e => { e.stopPropagation(); onSelect(n.id, e.shiftKey || e.metaKey); }} onContextMenu={e => nodeCtx(e, n)} onDoubleClick={e => { e.stopPropagation(); onToggleNode(n.id, false); }}>
              {isSel && <rect x={-4} y={-4} width={PW + 8} height={PH + 8} rx={13} fill="none" stroke={HB.accent} strokeWidth={2.5} strokeDasharray="5 4"/>}
              <rect width={PW} height={PH} rx={12} fill={HB.paper2} stroke={isSel ? HB.accent : catCol(n.cat)} strokeWidth={isSel ? 2 : 1.4} style={{ filter: 'drop-shadow(0 10px 24px rgba(0,0,0,.16))' }}/>
              <rect x={0} y={10} width={4} height={PH - 20} rx={2} fill={STC[n.status] || HB.inkMute}/>
              {(() => {
                const fCat = cardFs(7.5), fTitle = cardFs(13), fCnt = cardFs(9);
                const avail = PW - 130;   // leave the right-aligned stage count its gutter
                return (
                  <g>
                    <text x={14} y={22} fontSize={fCat} fontFamily={HB.mono} letterSpacing="0.14em" fill={catCol(n.cat)}>{fitStr((n.cat || '').toUpperCase() + ' · PIPELINE', avail, fCat)}</text>
                    <text x={14} y={40} fontSize={fTitle} fontWeight="700" fontFamily={HB.sans} fill={HB.ink}><title>{n.title}</title>{fitStr(n.title, avail, fTitle)}</text>
                    <text x={PW - 14} y={24} fontSize={fCnt} fontFamily={HB.mono} textAnchor="end" fill={HB.inkMute}>{pipe.length} stages ▾</text>
                  </g>
                );
              })()}
              {/* typed sockets \u2014 from nodeSock, so wires land on these exact points */}
              {(() => {
                const rec = nodeSock[n.id]; if (!rec) return null;
                const sigs = (side) => { const seen = []; rec.list.filter(s => s.side === side).forEach(s => { if (!seen.includes(s.sig)) seen.push(s.sig); }); return seen; };
                const cnt = (side) => rec.list.filter(s => s.side === side).length;
                const summary = (x, side, col) => { const c = cnt(side === 'L' ? 'in' : 'out'); if (!c) return null;
                  return (
                    <g style={{ pointerEvents: 'none' }}>
                      <text x={side === 'L' ? x + 11 : x - 11} y={PH - 26} fontSize={cardFs(7.5)} fontFamily={HB.mono} fontWeight="700" textAnchor={side === 'L' ? 'start' : 'end'} fill={col}>{side === 'L' ? '\u25b8 IN ' : 'OUT \u25b8 '}{c}</text>
                      <text x={side === 'L' ? x + 11 : x - 11} y={PH - 15} fontSize={cardFs(7)} fontFamily={HB.mono} textAnchor={side === 'L' ? 'start' : 'end'} fill={HB.inkMute}>{sigs(side === 'L' ? 'in' : 'out').slice(0, 2).join(' / ') || '\u2014'}</text>
                    </g>
                  ); };
                return (
                  <g>
                    {rec.list.map((s, i) => { const p = s.port; const col = typeColOf(s.sig); const wireable = s.side === 'out' && !n.frozen;
                      return (
                        <g key={s.side + i} style={{ cursor: wireable ? 'crosshair' : 'pointer' }}
                           onMouseDown={e => { if (wireable) startWire(e, n); else e.stopPropagation(); }}
                           onClick={e => { e.stopPropagation(); if (p.peer) { onSelect(p.peer.id, e.shiftKey || e.metaKey); onInspect(p.peer.id); } }}>
                          <title>{(s.side === 'in' ? '\u25b8 in \u00b7 ' : 'out \u25b8 ') + (p.peer ? p.peer.title : (p.label || 'port')) + ' \u00b7 ' + s.sig}</title>
                          <circle cx={s.lx} cy={s.ly} r={6} fill="transparent"/>
                          <circle cx={s.lx} cy={s.ly} r={3.4} fill={p.declared ? col : HB.card} stroke={col} strokeWidth={1.5}/>
                          <circle cx={s.lx} cy={s.ly} r={1.3} fill={p.declared ? HB.card : col}/>
                        </g>
                      ); })}
                    {summary(0, 'L', HB.blue)}
                    {summary(PW, 'R', HB.green)}
                  </g>
                );
              })()}
              {/* pipeline stages, wired left→right */}
              <g transform={`translate(28,72)`}>
                {pipe.map((s, i) => {
                  const x = i * 104; const col = PSTAGE_COL[s.role] || HB.purple;
                  return (
                    <g key={s.id} transform={`translate(${x},0)`}>
                      {i > 0 && <path d={`M${-12},26 L0,26`} stroke={HB.inkMute} strokeWidth={1.4} markerEnd=""/>}
                      {i > 0 && <path d={`M${-6},22 L0,26 L${-6},30`} fill="none" stroke={HB.inkMute} strokeWidth={1.2}/>}
                      <rect width={92} height={52} rx={8} fill={HB.card} stroke={col} strokeWidth={1.2}/>
                      <circle cx={12} cy={14} r={3.5} fill={STC[s.status] || col}/>
                      {(92 / upp) >= 74 ? (() => {
                        const fRole = cardFs(7), fName = cardFs(9.5);
                        return (
                          <g>
                            <text x={22} y={17} fontSize={fRole} fontFamily={HB.mono} fill={col} letterSpacing="0.06em">{fitStr(s.role.toUpperCase(), 62, fRole)}</text>
                            <text x={12} y={36} fontSize={fName} fontFamily={HB.sans} fontWeight="600" fill={HB.ink}><title>{s.t}</title>{fitStr(s.t, 70, fName)}</text>
                          </g>
                        );
                      })() : <rect x={12} y={30} width={62} height={5} rx={2.5} fill={col} opacity={0.5}/>}
                    </g>
                  );
                })}
              </g>
            </g>
          );
        }
        return (
          <g key={n.id} className="atlas-node" transform={`translate(${n.x + o.dx},${n.y + o.dy})`} style={{ cursor: 'pointer' }}
             onMouseDown={e => nodeDown(e, n)} onClick={e => { e.stopPropagation(); onSelect(n.id, e.shiftKey || e.metaKey); }} onContextMenu={e => nodeCtx(e, n)} onDoubleClick={e => { e.stopPropagation(); onToggleNode(n.id, true); onInspect(n.id); }}>
            {isSel && <rect x={-4} y={-4} width={NW + 8} height={NHt + 8} rx={11} fill="none" stroke={HB.accent} strokeWidth={2.5} strokeDasharray="5 4"/>}
            <rect width={NW} height={NHt} rx={9} fill={HB.card} stroke={n.frozen ? HB.inkMute : isSel ? HB.accent : HB.line} strokeWidth={isSel ? 2 : 1} strokeDasharray={n.frozen ? '5 3' : '0'} style={{ filter: isSel ? 'drop-shadow(0 8px 18px rgba(217,119,87,.28))' : 'none' }}/>
            <rect x={0} y={8} width={4} height={NHt - 16} rx={2} fill={STC[n.status] || HB.inkMute} opacity={n.frozen ? 0.5 : 1}/>
            <circle cx={NW - 13} cy={13} r={4} fill={STC[n.status] || HB.inkMute}/>
            {cardLegible() ? (() => {
              const avail = NW - 24;
              const fCat = cardFs(7.5), fTitle = cardFs(11), fSub = cardFs(8), fParam = cardFs(7.5), fTag = cardFs(7.5);
              return (
                <g>
                  {vis.labels && <text x={12} y={18} fontSize={fCat} fontFamily={HB.mono} letterSpacing="0.12em" fill={catCol(n.cat)}>{fitStr((n.cat || '').toUpperCase(), avail, fCat)}</text>}
                  <text x={12} y={vis.labels ? 36 : 28} fontSize={fTitle} fontWeight="700" fontFamily={HB.sans} fill={HB.ink}><title>{n.title}</title>{fitStr(n.title, avail, fTitle)}</text>
                  <text x={12} y={vis.labels ? 50 : 44} fontSize={fSub} fontFamily={HB.sans} fill={HB.inkSoft}>{fitStr(n.sub, avail, fSub)}</text>
                  {vis.params && (n.params || []).slice(0, 1).map((p, k) => <text key={k} x={12} y={66 + k * 11} fontSize={fParam} fontFamily={HB.mono} fill={HB.inkMute}>{fitStr(p.k + ': ' + p.v, avail, fParam)}</text>)}
                  <text x={NW - 12} y={NHt - 8} fontSize={fTag} fontFamily={HB.mono} textAnchor="end" fill={HB.inkMute} opacity={0.7}>{n.frozen ? '▣ frozen' : n.cat === 'watch' ? '◉ watcher' : '⊞ pipeline'}</text>
                </g>
              );
            })() : (
              // too small for type: the card becomes a status block, its category the only cue
              <g style={{ pointerEvents: 'none' }}>
                <rect x={10} y={NHt / 2 - 9} width={NW - 34} height={5} rx={2.5} fill={catCol(n.cat)} opacity={0.55}/>
                <rect x={10} y={NHt / 2 + 1} width={(NW - 34) * 0.6} height={5} rx={2.5} fill={HB.line}/>
                <title>{n.title}</title>
              </g>
            )}
            {/* TYPED SOCKETS — read from nodeSock, the same authority the wires resolve
                against. Out-sockets drag to wire; any socket hover-labels its peer/type and
                click-jumps to it. */}
            {(() => {
              const rec = nodeSock[n.id]; if (!rec || !rec.list.length) return null;
              return (
                <g>
                  {rec.list.map((s, i) => {
                    const p = s.port; const col = typeColOf(s.sig);
                    const wireable = s.side === 'out' && !n.frozen;
                    return (
                      <g key={s.side + i} style={{ cursor: wireable ? 'crosshair' : 'pointer' }}
                         onMouseDown={e => { if (wireable) startWire(e, n); else e.stopPropagation(); }}
                         onClick={e => { e.stopPropagation(); if (p.peer) { onSelect(p.peer.id, e.shiftKey || e.metaKey); onInspect(p.peer.id); } }}>
                        <title>{(s.side === 'in' ? '▸ in · ' : 'out ▸ ') + (p.peer ? p.peer.title : (p.label || 'port')) + ' · ' + s.sig + (p.declared ? ' · promoted' : '')}</title>
                        <circle cx={s.lx} cy={s.ly} r={6} fill="transparent"/>
                        <circle cx={s.lx} cy={s.ly} r={3.1} fill={p.declared ? col : HB.card} stroke={col} strokeWidth={1.4}/>
                        <circle cx={s.lx} cy={s.ly} r={1.2} fill={p.declared ? HB.card : col}/>
                      </g>
                    );
                  })}
                  <g style={{ pointerEvents: 'none' }}>
                    {cardLegible() && (() => { const ins = rec.list.filter(s => s.side === 'in').length; const f = cardFs(6.5); return ins > 0 && <text x={5} y={NHt - 7} fontSize={f} fontFamily={HB.mono} fill={HB.blue} opacity={0.75}>{ins}▸</text>; })()}
                  </g>
                </g>
              );
            })()}
            {cardLegible() && (() => { const rs = (n.rt && n.rt.state) || null; if (!rs || rs === 'idle') return null; const rc = (window.RT && window.RT.RT_COL[rs]) || HB.inkMute;
              return rs === 'running'
                ? <circle cx={NW / 2} cy={NHt / 2} r={5} fill="none" stroke={rc} strokeWidth={2} className="rt-run-ring"/>
                : <g transform={`translate(${NW - 30},${NHt - 17})`}><rect width={20} height={12} rx={3} fill={rc + '22'} stroke={rc} strokeWidth="0.7"/><text x={4} y={9} fontSize={cardFs(7)} fontFamily={HB.mono} fill={rc}>{rs === 'fresh' ? '✓ ok' : rs === 'stale' ? 'stale' : 'err'}</text></g>;
            })()}
            {cardLegible() && n.cat === 'watch' && (() => { const up = (window.RT ? window.RT.upstreamIds(M, n.id) : []).map(i => M.nodes.find(x => x.id === i)).filter(Boolean)[0]; const res = up && up.rt && up.rt.runs && up.rt.runs.length ? up.rt.runs[up.rt.runs.length - 1].result : (window.RT ? window.RT.rtResult(up || n) : '—'); return <text x={12} y={NHt - 22} fontSize={cardFs(8)} fontFamily={HB.mono} fill={HB.green}>▸ {String(res).slice(0, 22)}</text>; })()}
            {cardLegible() && ags.length > 0 && <g transform={`translate(14,${NHt - 16})`}><rect width={20} height={12} rx={6} fill={HB.accentSoft} stroke={HB.accent} strokeWidth="0.7"/><circle cx={6} cy={6} r={2.2} fill={HB.accent}/><text x={11} y={9} fontSize={cardFs(7)} fontFamily={HB.mono} fill={HB.accentHi}>{ags.length}</text></g>}
            {/* out-port: drag to another node to wire them */}
            {isSel && !n.frozen && <g><circle cx={NW} cy={NHt / 2} r={11} fill="transparent" style={{ cursor: 'crosshair' }} onMouseDown={e => startWire(e, n)}/><circle cx={NW} cy={NHt / 2} r={5.5} fill={HB.accent} stroke={HB.card} strokeWidth={2} style={{ cursor: 'crosshair', pointerEvents: 'none' }}/><path d={`M${NW - 2},${NHt / 2 - 2} L${NW + 2},${NHt / 2} L${NW - 2},${NHt / 2 + 2}`} stroke={HB.card} strokeWidth={1.2} fill="none" style={{ pointerEvents: 'none' }}/></g>}
            {isSel && <circle cx={0} cy={NHt / 2} r={4} fill={HB.card} stroke={HB.blue} strokeWidth={1.6}/>}
          </g>
        );
      })}

      {/* FOCUSED WIRING — select one node to see exactly what it wires to & why */}
      {(() => {
        const ids = [...sel.nodes]; if (ids.length !== 1) return null;
        const fid = ids[0]; const cn = M.nodes.find(n => n.id === fid);
        if (!cn || !domOpen(cn.dom) || !visN(cn)) return null;
        const o = off(cn.dom); const c = { x: cn.x + NW / 2 + o.dx, y: cn.y + NHt / 2 + o.dy };
        const conns = [];
        M.wires.forEach(w => {
          if (w.a === fid) { const t = M.nodes.find(n => n.id === w.b); if (t) { const A = nodeAnchor(w.b); if (A) conns.push({ dir: 'out', why: w.why, t: w.t || sigOf(cn), to: A, title: t.title, open: domOpen(t.dom), oid: w.b }); } }
          else if (w.b === fid) { const s = M.nodes.find(n => n.id === w.a); if (s) { const A = nodeAnchor(w.a); if (A) conns.push({ dir: 'in', why: w.why, t: w.t || sigOf(s), to: A, title: s.title, open: domOpen(s.dom), oid: w.a }); } }
        });
        if (!conns.length) return null;
        const hx = NW / 2 + 7, hy = NHt / 2 + 7;
        return (
          <g>
            {conns.map((cc, i) => {
              const ang = Math.atan2(cc.to.y - c.y, cc.to.x - c.x);
              const tmin = Math.min(Math.abs(Math.cos(ang)) < 1e-3 ? 1e6 : hx / Math.abs(Math.cos(ang)), Math.abs(Math.sin(ang)) < 1e-3 ? 1e6 : hy / Math.abs(Math.sin(ang)));
              const port = { x: c.x + Math.cos(ang) * tmin, y: c.y + Math.sin(ang) * tmin };
              const col = typeColOf(cc.t);
              const lab = (cc.t || 'any') + ' ' + (cc.dir === 'out' ? '▸' : '◂') + ' ' + (cc.title || '').slice(0, 20);
              const lx = port.x + (cc.to.x - port.x) * 0.42, ly = port.y + (cc.to.y - port.y) * 0.42;
              const ah = 7;
              const a2 = cc.dir === 'out' ? fid : cc.oid, b2 = cc.dir === 'out' ? cc.oid : fid;
              return (
                <g key={i}>
                  {/* right-click hit target to remove the wire */}
                  <path d={`M${port.x},${port.y} L${cc.to.x},${cc.to.y}`} stroke="transparent" strokeWidth={13} style={{ cursor: 'context-menu', pointerEvents: 'stroke' }} onContextMenu={e => { e.preventDefault(); e.stopPropagation(); onWireContext && onWireContext(a2, b2, e.clientX, e.clientY); }}/>
                  <g style={{ pointerEvents: 'none' }}>
                    <path d={`M${port.x},${port.y} L${cc.to.x},${cc.to.y}`} stroke={col} strokeWidth={2} opacity={0.92} strokeDasharray={cc.open ? '0' : '6 4'}/>
                    <path d={`M${cc.to.x - Math.cos(ang) * 14 - Math.cos(ang - 0.5) * ah},${cc.to.y - Math.sin(ang) * 14 - Math.sin(ang - 0.5) * ah} L${cc.to.x - Math.cos(ang) * 14},${cc.to.y - Math.sin(ang) * 14} L${cc.to.x - Math.cos(ang) * 14 - Math.cos(ang + 0.5) * ah},${cc.to.y - Math.sin(ang) * 14 - Math.sin(ang + 0.5) * ah}`} fill="none" stroke={col} strokeWidth={2}/>
                    <circle cx={port.x} cy={port.y} r={4.5} fill={HB.card} stroke={col} strokeWidth={2}/>
                    <circle cx={port.x} cy={port.y} r={1.6} fill={col}/>
                    <g transform={`translate(${lx},${ly})`}>
                      <rect x={-lab.length * 3.05 - 6} y={-9} width={lab.length * 6.1 + 12} height={18} rx={9} fill={HB.card} stroke={col} strokeWidth={0.8} opacity={0.97}/>
                      <text x={0} y={4} fontSize={cardFs(9.5)} fontFamily={HB.mono} textAnchor="middle" fill={col}>{lab}</text>
                    </g>
                  </g>
                </g>
              );
            })}
            <g transform={`translate(${c.x},${cn.y + o.dy - 14})`} style={{ pointerEvents: 'none' }}>
              <rect x={-64} y={-11} width={128} height={20} rx={10} fill={HB.paper2} stroke={HB.line} strokeWidth={1}/>
              <text x={0} y={3} fontSize={cardFs(9)} fontFamily={HB.mono} textAnchor="middle" fill={HB.ink}>{conns.filter(c => c.dir === 'out').length} out · {conns.filter(c => c.dir === 'in').length} in · right-click wire to cut</text>
            </g>
          </g>
        );
      })()}

      {/* wire being drawn from an out-port */}
      {wire && (() => { const f = M.nodes.find(n => n.id === wire.from); if (!f) return null; const o = off(f.dom); const fx = f.x + NW + o.dx, fy = f.y + NHt / 2 + o.dy; return (<g style={{ pointerEvents: 'none' }}><path d={`M${fx},${fy} C${fx + 70},${fy} ${wire.x - 70},${wire.y} ${wire.x},${wire.y}`} stroke={HB.accent} strokeWidth={2.4} strokeDasharray="6 4" fill="none"/><circle cx={wire.x} cy={wire.y} r={5} fill={HB.accent}/></g>); })()}

      {marquee && <rect x={marquee.x} y={marquee.y} width={marquee.w} height={marquee.h} fill={HB.accent} fillOpacity={0.08} stroke={HB.accent} strokeWidth={1.4} strokeDasharray="6 4"/>}
    </g>
    </svg>
  );
});

Object.assign(window, { MapCanvas, STC, catCol, NW_ATLAS: NW, DETAIL_W, nodePipeline, nodePorts, sigOf, typeOf, SIGNAL, TYPECOL, typeColOf, archCanConnect });
