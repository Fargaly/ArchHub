// DSYS-078 + ds_screens.jsx: existing card/socket, grid and inspector grammar.
// Gesture changes stay local until pointer-up, then commit through the adapter.
(() => {
  function executeAction(...args) { return window.executeAction(...args); }
  const {
    A,
    D,
    api,
    useData,
    useApp,
    Btn,

    Chip,

    SettingControl
  } = window.UI;
  const curve = (a, b) => `M${a.x} ${a.y} C${(a.x + b.x) / 2} ${a.y},${(a.x + b.x) / 2} ${b.y},${b.x} ${b.y}`;
  const isGroup = n => n.children?.length > 0 || n.kind === 'Group' || n.kind === 'Workshop';
  const typeColor = t => ({
    elements: A.accent,
    text: A.inkSoft,
    number: A.warn,
    boolean: A.purple,
    file: A.ok,
    event: A.cyan,
    any: A.inkSoft,
    view: A.cyan
  })[t] || A.accent;
  function Canvas({
    embedded = false
  }) {
    const s = useData(),
      u = useApp();
    const zoomRow = s.settings.find(r => r.page === 'Appearance' && (r.label === 'Zoom percentage' || r.key === 'Zoom percentage'))
      || s.settings.find(r => r.id === 'Appearance.Zoom percentage');
    const zoomMin = Number(s.canvasPolicy?.zoom_min ?? .1), zoomMax = Number(s.canvasPolicy?.zoom_max ?? 4);
    const [selected, setSelected] = React.useState(u.selectedNodeId && s.graph.nodes.some(n => n.id === u.selectedNodeId) ? [u.selectedNodeId] : []),
      [wireId, setWireId] = React.useState(null),
      [parent, setParent] = React.useState(null),
      [viewport, setViewport] = React.useState({zoom: Math.max(zoomMin, Math.min(zoomMax, (zoomRow?.value || 80) / 100)), pan: {x: 0, y: 0}}),
      [draft, setDraft] = React.useState(null),
      [marquee, setMarquee] = React.useState(null),
      [from, setFrom] = React.useState(null),
      [paths, setPaths] = React.useState([]),
      [layout, setLayout] = React.useState({scope: null, positions: {}}),
      [wireTab, setWireTab] = React.useState('Rules');
    const area = React.useRef(),
      world = React.useRef(),
      gesture = React.useRef(null),
      view = React.useRef(viewport),
      space = React.useRef(false),
      touches = React.useRef(new Map()),
      zoomWrites = React.useRef(Promise.resolve()),
      pendingZoomWrites = React.useRef(0);
    const fittedScope = React.useRef(null), clipId = 'canvas-wires-' + React.useId().replace(/[^a-zA-Z0-9-]/g, '');
    const {zoom, pan} = viewport;
    const [requestState, setRequestState] = React.useState('waiting');
    const [requestError, setRequestError] = React.useState('');
    const zoomSetting = zoomRow?.value;
    const zoomSaveDelay = Number(s.canvasPolicy?.viewport_commit_debounce_ms ?? 140);
    const updateView = next => { view.current = next; setViewport(next); };
    const setPan = next => updateView({...view.current, pan: typeof next === 'function' ? next(view.current.pan) : next});
    const zoomAt = (value, client = null) => {
      const bounds = area.current?.getBoundingClientRect();
      if (!bounds) return;
      const old = view.current, next = Math.max(zoomMin, Math.min(zoomMax, value));
      const x = client ? client.x - bounds.left : bounds.width / 2,
        y = client ? client.y - bounds.top : bounds.height / 2;
      updateView({zoom: next, pan: {x: x - (x - old.pan.x) * next / old.zoom, y: y - (y - old.pan.y) * next / old.zoom}});
    };
    React.useEffect(() => {
      if (pendingZoomWrites.current || !Number.isFinite(Number(zoomSetting))) return;
      zoomAt(Number(zoomSetting) / 100);
    }, [zoomSetting, requestState]);
    React.useEffect(() => {
      const percent = Math.round(zoom * 100);
      if (!['loaded','empty'].includes(requestState) || zoomSetting === undefined || percent === Number(zoomSetting)) return;
      const timer = setTimeout(() => {
        pendingZoomWrites.current++;
        zoomWrites.current = zoomWrites.current.then(() => u.act(() => api.setSetting(zoomRow.id, percent)))
          .finally(() => { pendingZoomWrites.current--; });
        // u.act reports failures; a refused save must not poison the next gesture.
        zoomWrites.current = zoomWrites.current.catch(() => {});
      }, zoomSaveDelay);
      return () => clearTimeout(timer);
    }, [zoom, zoomSetting, zoomRow?.id, zoomSaveDelay, requestState]);
    const reload = () => {
      setRequestState('waiting');
      return api.refreshProjects().then(() => {
        setRequestState(api.getSnapshot().graph.nodes.length ? 'loaded' : 'empty');
      }).catch(error => {
        setRequestError(error.message);
        setRequestState('error');
      });
    };
    React.useEffect(() => { reload(); u.setLibraryOpen?.(true); }, []);
    React.useEffect(() => {
      if (requestState === 'loaded' || requestState === 'empty')
        setRequestState(s.graph.nodes.length ? 'loaded' : 'empty');
    }, [s.graph.nodes.length]);
    // A node whose group is not a node at this level is drawn here, never dropped.
    const atLevel = n => (n.parent || null) === parent || (parent === null && !s.graph.nodes.some(x => x.id === n.parent));
    const scope = s.graph.id + ':' + (parent || ''), sourceNodes = s.graph.nodes.filter(atLevel);
    const visible = sourceNodes.map(n => ({...n, ...(layout.scope === scope ? layout.positions[n.id] : {})})),
      node = s.graph.nodes.find(n => n.id === selected.at(-1)),
      wire = s.graph.wires.find(w => w.id === wireId);
    React.useLayoutEffect(() => {
      if (requestState !== 'loaded' || !world.current) return;
      const boxes = [], positions = {}, minX = Math.min(...sourceNodes.map(n => n.x), 0),
        rowWidth = Math.max(760, Math.ceil(Math.sqrt(sourceNodes.length)) * 310), prior = layout.scope === scope ? layout.positions : {};
      for (const n of sourceNodes) {
        const previous = prior[n.id], unchanged = previous?.sourceX === n.x && previous?.sourceY === n.y;
        const el = world.current.querySelector('[data-graph-node="' + n.id + '"]'),
          box = {x:unchanged ? previous.x : n.x, y:unchanged ? previous.y : n.y, w:(el?.offsetWidth || el?.getBoundingClientRect().width / view.current.zoom || 224) + (isGroup(n) ? 10 : 0),
            h:(el?.offsetHeight || el?.getBoundingClientRect().height / view.current.zoom || 160) + (isGroup(n) ? 10 : 0)};
        let hit;
        while ((hit = boxes.find(b => box.x < b.x+b.w+36 && box.x+box.w+36 > b.x && box.y < b.y+b.h+48 && box.y+box.h+48 > b.y))) {
          box.x = hit.x + hit.w + 36;
          if (box.x + box.w > minX + rowWidth) {
            box.x = minX;
            box.y = Math.max(box.y, hit.y+hit.h) + 64;
          }
        }
        positions[n.id] = {x:box.x,y:box.y,w:box.w,h:box.h,sourceX:n.x,sourceY:n.y}; boxes.push(box);
      }
      setLayout(old => old.scope === scope && JSON.stringify(old.positions) === JSON.stringify(positions) ? old : {scope,positions});
    }, [requestState, scope, s.graph.nodes]);
    React.useEffect(() => {
      const listener = e => {
        if (e.target.closest('input,textarea,select,[contenteditable="true"],[role="textbox"]')) return;
        if (area.current?.contains(e.target)) {
          if (e.key === ' ') { e.preventDefault(); space.current = true; }
          if (e.key === '+' || e.key === '=') { e.preventDefault(); zoomAt(view.current.zoom * 1.2); }
          if (e.key === '-') { e.preventDefault(); zoomAt(view.current.zoom / 1.2); }
          if (e.key === '0') { e.preventDefault(); e.ctrlKey ? fit() : zoomAt(1); }
          if (e.shiftKey && (e.code === 'Digit1' || e.key === '1')) { e.preventDefault(); fit(); }
        }
        if (e.ctrlKey && e.key.toLowerCase() === 'g') {
          e.preventDefault();
          group();
        }
        if (e.key === 'Delete' && selected.length) {
          e.preventDefault();
          remove();
        }
        if (e.key === 'Enter' && node && isGroup(node)) setParent(node.id);
        if (e.key === 'Escape') {
          setFrom(null);
          if (parent) setParent(null);
        }
        if (e.ctrlKey && e.key.toLowerCase() === 'a') {
          e.preventDefault();
          setSelected(visible.map(n => n.id));
        }
      };
      window.addEventListener('keydown', listener);
      const releaseSpace = () => { space.current = false; };
      const keyup = e => { if (e.key === ' ') releaseSpace(); };
      window.addEventListener('keyup', keyup);
      window.addEventListener('blur', releaseSpace);
      return () => {
        window.removeEventListener('keydown', listener);
        window.removeEventListener('keyup', keyup);
        window.removeEventListener('blur', releaseSpace);
      };
    });
    React.useLayoutEffect(() => {
      if (!world.current) return;
      const pos = (id, side, port) => {
        const el = world.current.querySelector(`[data-port-key="${id}:${side}:${port}"]`);
        if (!el) return null;
        const r = el.getBoundingClientRect(),
          w = world.current.getBoundingClientRect();
        return {
          x: (r.left + r.width / 2 - w.left) / zoom,
          y: (r.top + r.height / 2 - w.top) / zoom
        };
      };
      setPaths(s.graph.wires.map(w => ({
        w,
        a: pos(w.from, 'out', w.fromPort),
        b: pos(w.to, 'in', w.toPort)
      })).filter(p => p.a && p.b));
    }, [s.revision, parent, draft, requestState, layout]);
    React.useEffect(() => u.setSelectedNodeId(selected.at(-1) || null), [selected.join(',')]);
    const group = async () => {
      const g = await u.act(() => api.groupNodes(selected));
      if (g) setSelected([g.id]);
    };
    const remove = () => u.confirm(`Delete ${selected.length} selected node${selected.length === 1 ? '' : 's'}?`, async () => {
      for (const id of selected) await api.deleteNode(id);
      setSelected([]);
    });
    const connect = async (a, b) => {
      if (a.side === b.side || a.id === b.id) {
        setFrom(null);
        return;
      }
      const out = a.side === 'out' ? a : b,
        input = a.side === 'in' ? a : b;
      const result = await u.act(() => api.connectSockets({
        from: out.id,
        to: input.id,
        fromPort: out.port,
        toPort: input.port
      }));
      if (result && !result.ok) u.show('Type mismatch', result);
      setFrom(null);
    };
    const socket = (n, p, side) => {
      const endpoint = {
        id: n.id,
        side,
        port: p.id
      };
      const arm = () => {
        if (from) connect(from, endpoint);else setFrom(endpoint);
      };
      return <span data-port-key={`${n.id}:${side}:${p.id}`} data-endpoint={JSON.stringify(endpoint)} className="socket" onContextMenu={e => {
        e.preventDefault();
        e.stopPropagation();
        u.show('Port menu', {
          id: n.id,
          port: p.id,
          anchor: {
            x: e.clientX,
            y: e.clientY
          }
        });
      }} role="button" tabIndex={0} aria-label={`${n.title} ${side} ${p.name}`} aria-pressed={from?.id === n.id && from?.side === side && from?.port === p.id} style={{
        display: 'inline-grid',
        placeItems: 'center',
        width: 22,
        height: 22
      }} onPointerDown={e => {
        e.stopPropagation();
        gesture.current = {
          kind: 'wire',
          sx: e.clientX,
          sy: e.clientY,
          start: endpoint
        };
        e.currentTarget.setPointerCapture(e.pointerId);
      }} onPointerUp={e => {
        e.stopPropagation();
        if (gesture.current?.kind === 'wire') {
          const end = document.elementsFromPoint(e.clientX, e.clientY).map(x => x.closest('[data-endpoint]')).find(x => x && x.dataset.endpoint !== JSON.stringify(endpoint));
          if (end) connect(endpoint, JSON.parse(end.dataset.endpoint));else if (Math.hypot(e.clientX - gesture.current.sx, e.clientY - gesture.current.sy) > 25) {
            const bounds = area.current.getBoundingClientRect();
            u.show('Compatible nodes', {
              endpoint,
              position: {
                x: (e.clientX - bounds.left - pan.x) / zoom,
                y: (e.clientY - bounds.top - pan.y) / zoom
              }
            });
          } else arm();
          gesture.current = null;
        }
      }} onClick={e => {
        e.stopPropagation();
        if (e.detail === 0) arm();
      }} onKeyDown={e => {
        if (e.key === 'Escape') {
          e.preventDefault();
          e.stopPropagation();
          setFrom(null);
          return;
        }
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          e.stopPropagation();
          arm();
        }
      }}><D.Socket t={p.type} list={p.list} size={10} filled={s.graph.wires.some(w => side === 'out' ? w.from === n.id && w.fromPort === p.id : w.to === n.id && w.toPort === p.id)} /></span>;
    };
    const startNode = (e, n) => {
      if (e.button !== 0 || e.target.closest('button,input,select,[data-endpoint]')) return;
      e.stopPropagation();
      setWireId(null);
      setSelected(e.shiftKey ? [...new Set([...selected, n.id])] : selected.includes(n.id) ? selected : [n.id]);
      const moving = selected.includes(n.id) ? selected : [n.id];
      gesture.current = {
        nodes: visible.filter(x => moving.includes(x.id)).map(x => ({
          id: x.id,
          x: x.x,
          y: x.y
        })),
        kind: 'node',
        id: n.id,
        sx: e.clientX,
        sy: e.clientY,
        x: n.x,
        y: n.y
      };
      e.currentTarget.setPointerCapture(e.pointerId);
    };
    const move = e => {
      if (e.pointerType === 'touch' && touches.current.has(e.pointerId)) {
        touches.current.set(e.pointerId, {x: e.clientX, y: e.clientY});
        if (touches.current.size === 2 && gesture.current?.kind === 'pinch') {
          const [a,b] = [...touches.current.values()], g = gesture.current,
            midpoint = {x: (a.x+b.x)/2, y: (a.y+b.y)/2}, distance = Math.hypot(a.x-b.x,a.y-b.y);
          zoomAt(view.current.zoom * distance / g.distance, g.midpoint);
          setPan(p => ({x: p.x + midpoint.x - g.midpoint.x, y: p.y + midpoint.y - g.midpoint.y}));
          g.distance = Math.max(1, distance); g.midpoint = midpoint;
          return;
        }
      }
      const g = gesture.current;
      if (g?.kind === 'node') {
        if (!g.dragging && Math.hypot(e.clientX - g.sx, e.clientY - g.sy) < 4) return;
        g.dragging = true;
        const dx = (e.clientX - g.sx) / zoom,
          dy = (e.clientY - g.sy) / zoom;
        g.draft = {
          id: g.id,
          x: g.x + dx,
          y: g.y + dy,
          positions: Object.fromEntries(g.nodes.map(n => [n.id, {
            x: n.x + dx,
            y: n.y + dy
          }]))
        };
        setDraft(g.draft);
      }
      if (g?.kind === 'marquee') {
        g.box = {
          left: Math.min(g.sx, e.clientX),
          top: Math.min(g.sy, e.clientY),
          right: Math.max(g.sx, e.clientX),
          bottom: Math.max(g.sy, e.clientY)
        };
        setMarquee(g.box);
      }
      if (g?.kind === 'pan') setPan({
        x: g.x + e.clientX - g.sx,
        y: g.y + e.clientY - g.sy
      });
    };
    const end = e => {
      if (e?.pointerType === 'touch') touches.current.delete(e.pointerId);
      const g = gesture.current;
      if (g?.kind === 'node' && g.dragging && g.draft) u.act(() => api.moveNodes(g.draft.positions));
      if (g?.kind === 'marquee' && g.box) {
        const box = g.box;
        setSelected(visible.filter(n => {
          const r = world.current.querySelector('[data-graph-node="' + n.id + '"]')?.getBoundingClientRect();
          return r && r.right >= box.left && r.left <= box.right && r.bottom >= box.top && r.top <= box.bottom;
        }).map(n => n.id));
      }
      gesture.current = null;
      setDraft(null);
      setMarquee(null);
    };
    const fit = () => {
      if (!visible.length || !area.current) return;
      const w = area.current.clientWidth, h = area.current.clientHeight;
      const boxes = [...world.current.querySelectorAll('[data-graph-node]')].map(el => {
        const n = visible.find(n => n.id === el.dataset.graphNode);
        return {x: n.x, y: n.y, w: n.w || el.offsetWidth || el.getBoundingClientRect().width / view.current.zoom || 224,
          h: n.h || el.offsetHeight || el.getBoundingClientRect().height / view.current.zoom || 160};
      });
      if (!boxes.length) return;
      const minX = Math.min(...boxes.map(b => b.x)), minY = Math.min(...boxes.map(b => b.y)),
        width = Math.max(...boxes.map(b => b.x+b.w)) - minX,
        height = Math.max(...boxes.map(b => b.y+b.h)) - minY,
        z = Math.max(zoomMin, Math.min(zoomMax, Number(s.canvasPolicy?.zoom_fit_max ?? 1.25), (w-60) / Math.max(1,width), (h-60) / Math.max(1,height)));
      updateView({zoom: z, pan: {x: (w-width*z)/2-minX*z, y: (h-height*z)/2-minY*z}});
    };
    React.useEffect(() => {
      if (requestState !== 'loaded' || layout.scope !== scope || fittedScope.current === scope) return;
      fittedScope.current = scope;
      fit();
    }, [requestState, scope, layout]);
    React.useEffect(() => {
      const el = area.current;
      if (!el) return;
      const wheel = e => {
        if (e.target.closest('input,textarea,select,[contenteditable="true"]')) return;
        e.preventDefault();
        const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? el.clientHeight : 1,
          dx = e.deltaX * unit, dy = e.deltaY * unit;
        // shortcut: Chromium pinch is Ctrl+pixel-wheel without a held Ctrl key; track physical keys separately.
        const pinch = e.ctrlKey && !physicalCtrl.current && e.deltaMode === 0;
        if ((e.ctrlKey || e.shiftKey) && !pinch) setPan(p => ({x:p.x-dx,y:p.y-dy}));
        else zoomAt(view.current.zoom * Math.exp(-dy * .002), {x:e.clientX,y:e.clientY});
      };
      el.addEventListener('wheel', wheel, {passive:false});
      return () => el.removeEventListener('wheel', wheel);
    }, [requestState]);
    const physicalCtrl = React.useRef(false);
    React.useEffect(() => {
      const down = e => { if (e.key === 'Control') physicalCtrl.current = true; },
        up = e => { if (e.key === 'Control') physicalCtrl.current = false; },
        blur = () => { physicalCtrl.current = false; };
      window.addEventListener('keydown', down); window.addEventListener('keyup', up); window.addEventListener('blur', blur);
      return () => { window.removeEventListener('keydown', down); window.removeEventListener('keyup', up); window.removeEventListener('blur', blur); };
    }, []);
    const openNode = n => {
      if (n.kind.toLowerCase().includes('meeting')) u.go('meetings');else if (n.kind === 'Watch program') u.act(() => api.windowAction('hide'));else if (n.kind === 'Present') u.go('present');else if (['Community', 'Community group', 'Marketplace listing', 'Project charge'].includes(n.kind)) u.go('community');else if (n.kind === 'Interface studio' || n.kind === 'UI element') u.go('interface');else if (n.kind.startsWith('TBP ')) u.go('model-review');else if (n.kind === 'Theme') u.go('settings/Appearance');else if (n.kind === 'Graph link') {
        if (n.params.targetGraph) u.act(() => api.selectGraph(n.params.targetGraph));else u.show('Graphs');
      } else if (n.kind === 'Agent') u.show('Agent', {
        id: n.params.provider
      });else if (n.kind === 'Research') u.go('xray');else if (n.kind === 'History') u.go('receipts');else if (['Remember', 'Recall'].includes(n.kind)) u.go('brain');else if (['Social media', 'Read video', 'Read mail', 'Read file', 'Tutorial', 'Digest'].includes(n.kind)) u.go('social');else if (n.kind === 'X-RAY') u.go('xray');else if (['Account access', 'Billing & usage', 'Office invitations'].includes(n.kind)) u.go('access');else if (n.kind === 'Model routing') u.go('routing');else if (n.kind === 'Workshop') u.go('workshop');else if (n.kind === 'BABOOM') u.go('baboom');else if (n.kind === 'Watcher') u.go('watcher');else if (isGroup(n)) {
        setParent(n.id);
        setSelected([]);
      } else u.show('Node', {
        id: n.id
      });
    };
    const body = <div data-screen="canvas" style={{
      display: 'grid',
      gridTemplateRows: '50px minmax(0,1fr)',
      minHeight: 0,
      '--canvas-bg': A.bgCanvas,
      '--canvas-panel': A.bgPanel,
      '--canvas-soft': A.bgSoft,
      '--canvas-hover': A.bgHover,
      '--canvas-line': A.line,
      '--canvas-line-soft': A.lineSoft,
      '--canvas-ink': A.ink,
      '--canvas-muted': A.inkSoft,
      '--canvas-accent': A.accent,
      '--canvas-accent-dim': A.accentDim
    }}>
  <div className="spread" style={{
        padding: '0 18px',
        borderBottom: '1px solid ' + A.lineSoft,
        background: A.bg
      }}><div className="flex"><button className="button-reset muted" onClick={event => executeAction("projects.ds_screens.NavigateHome.5", {u}, event)}>{s.graph.name} ›</button>{parent ? <Btn variant="controls" sm ghost onClick={event => executeAction("projects.ds_screens.Parent.6", {parent,s,setParent,setSelected}, event)}>← Parent</Btn> : <button className="button-reset flex" title="Graphs" aria-label="Graphs" onClick={event => executeAction("projects.ds_screens.Graphs.7", {u}, event)}>{s.graph.name}<window.AHIcon name="more" size={16} /></button>}<Chip>{visible.length} nodes</Chip><Btn variant="controls" sm ghost onClick={event => executeAction("projects.ds_screens.Workspaces.8", {u}, event)}>Workspaces · {s.workspaces.length}</Btn></div><div className="flex"><button className="icon-button" aria-label="Toggle Library" title="Library" aria-expanded={u.libraryOpen} onClick={event => executeAction("projects.ds_screens.ToggleLibrary.9", {u}, event)}><window.AHIcon name="library" /></button><select aria-label="Wire visibility" value={s.graph.wireVisibility || 'Visible'} onChange={e => u.act(() => api.setWireVisibility(e.target.value))}>{['Visible', 'Faint', 'Hidden'].map(x => <option key={x}>{x}</option>)}</select><Btn variant="controls" sm title="Group · Ctrl G" onClick={event => executeAction("projects.ds_screens.Group.10", {group}, event)} disabled={selected.length < 2}>Group</Btn><Btn variant="controls" sm onClick={event => executeAction("projects.ds_screens.Undo.11", {api,u}, event)} title="Undo · Ctrl Z">↶</Btn><Btn variant="controls" sm onClick={event => executeAction("projects.ds_screens.Redo.12", {api,u}, event)} title="Redo · Ctrl Shift Z">↷</Btn><Btn variant="controls" sm onClick={event => executeAction("projects.ds_screens.Arrange.13", {api,u}, event)}>Arrange</Btn><Btn variant="controls" sm onClick={event => executeAction("projects.ds_screens.SaveSkill.14", {u}, event)}>Save skill</Btn><Btn variant="controls" p sm onClick={event => executeAction("projects.ds_screens.Run.15", {api,u}, event)}>▶ Run</Btn></div></div>
  <div style={{
        display: 'grid',
        gridTemplateColumns: (u.libraryOpen ? '248px ' : '') + 'minmax(0,1fr)' + (wire ? ' 320px' : ''),
        minHeight: 0
      }}>{u.libraryOpen && <window.UI.LibraryShelf onClose={() => u.setLibraryOpen(false)} />}
   <div ref={area} className="node-canvas" tabIndex={0} aria-label="Graph canvas" style={{touchAction:'none'}} title="Wheel to zoom · Middle or Space-drag to pan · Shift-drag to select · Double-click to fit" onPointerDownCapture={e => {
          if (e.target.closest('input,textarea,select,[contenteditable="true"]')) return;
          area.current.focus({preventScroll:true});
          if (e.pointerType === 'touch') {
            touches.current.set(e.pointerId, {x:e.clientX,y:e.clientY});
            if (touches.current.size === 2) {
              const [a,b] = [...touches.current.values()];
              gesture.current = {kind:'pinch',distance:Math.max(1,Math.hypot(a.x-b.x,a.y-b.y)),midpoint:{x:(a.x+b.x)/2,y:(a.y+b.y)/2}};
              setDraft(null);
              e.currentTarget.setPointerCapture(e.pointerId); e.stopPropagation(); e.preventDefault(); return;
            }
          }
          if (e.button === 1 || (e.button === 0 && space.current)) {
            e.preventDefault(); e.stopPropagation();
            gesture.current = {kind:'pan',sx:e.clientX,sy:e.clientY,x:view.current.pan.x,y:view.current.pan.y};
            e.currentTarget.setPointerCapture(e.pointerId);
          }
        }} onPointerUpCapture={e => {
          if (e.pointerType === 'touch') {
            touches.current.delete(e.pointerId);
            if (gesture.current?.kind === 'pinch') gesture.current = null;
          }
        }} onDoubleClick={e => {
          if (e.target === e.currentTarget || e.target === world.current) fit();
        }} onAuxClick={e => { if (e.button === 1) e.preventDefault(); }} onPointerDown={e => {
          if (e.button !== 0 || touches.current.size > 1) return;
          if (e.target === e.currentTarget || e.target === world.current) {
            setSelected([]);
            setWireId(null);
            gesture.current = {
              kind: e.shiftKey ? 'marquee' : 'pan',
              sx: e.clientX,
              sy: e.clientY,
              x: pan.x,
              y: pan.y
            };
            e.currentTarget.setPointerCapture(e.pointerId);
          }
        }} onPointerMove={move} onPointerUp={end} onPointerCancel={() => {
          touches.current.clear();
          gesture.current = null;
          setDraft(null);
          setMarquee(null);
        }} onDragOver={e => e.preventDefault()} onDrop={e => {
          e.preventDefault();
          const name = e.dataTransfer.getData('node');
          if (name) {
            const r = area.current.getBoundingClientRect();
            u.act(() => api.addNode(name, {
              x: (e.clientX - r.left - pan.x) / zoom,
              y: (e.clientY - r.top - pan.y) / zoom
            }));
          }
        }} onContextMenu={e => {
          e.preventDefault();
          u.show('Canvas menu', {
            selected,
            group,
            remove
          });
        }}>
    {marquee && <div aria-label="Selection marquee" style={{
            position: 'absolute',
            pointerEvents: 'none',
            zIndex: 8,
            border: '1px solid ' + A.accent,
            background: A.accent + '16',
            left: marquee.left - (area.current?.getBoundingClientRect().left || 0),
            top: marquee.top - (area.current?.getBoundingClientRect().top || 0),
            width: marquee.right - marquee.left,
            height: marquee.bottom - marquee.top
          }} />}<div ref={world} style={{
            position: 'absolute',
            width: 2000,
            height: 1600,
            transform: `translate(${pan.x}px,${pan.y}px) scale(${zoom})`,
            transformOrigin: '0 0'
          }}>
     <svg className={visible.some(n => n.status === 'Running') ? 'running-wires' : ''} width="2000" height="1600" style={{
              position: 'absolute',
              inset: 0,
              overflow: 'visible',
              pointerEvents: 'none'
            }}><defs><clipPath id={clipId} clipPathUnits="userSpaceOnUse"><path clipRule="evenodd" d={'M-100000 -100000H100000V100000H-100000Z '+visible.map(n=>{
              const p=draft?.positions?.[n.id] || n, b=layout.positions[n.id];
              return `M${p.x-3} ${p.y-3}h${(b?.w || 224)+6}v${(b?.h || 160)+6}h-${(b?.w || 224)+6}Z`;
            }).join(' ')} /></clipPath></defs><g clipPath={`url(#${clipId})`}>{paths.map(({
                w,
                a,
                b
              }) => <g key={w.id}><path d={curve(a, b)} stroke="transparent" strokeWidth="16" fill="none" style={{
                  pointerEvents: 'stroke',
                  cursor: 'pointer'
                }} role="button" tabIndex={0} aria-label={'Inspect wire ' + w.id} onClick={e => {
                  e.stopPropagation();
                  setWireId(w.id);
                  setSelected([]);
                }} onKeyDown={e => {
                  if (e.key === 'Enter') {
                    setWireId(w.id);
                    setSelected([]);
                  }
                }} />{wireId === w.id && s.graph.wireVisibility !== 'Hidden' && <path d={curve(a,b)} stroke={A.ink} strokeWidth="8" opacity=".22" fill="none" />}<path d={curve(a, b)} stroke={typeColor(w.type)} strokeWidth="2" strokeLinecap="round" strokeDasharray={w.type === 'event' ? '6 2' : undefined} opacity={s.graph.wireVisibility === 'Hidden' || s.graph.nodes.find(n => n.id === w.from)?.portVisibility?.[w.fromPort] === 'Hidden' ? 0 : s.graph.wireVisibility === 'Faint' || s.graph.nodes.find(n => n.id === w.from)?.portVisibility?.[w.fromPort] === 'Faint' ? .2 : .9} fill="none" /></g>)}</g></svg>
     {visible.map(n => {
       const position = draft?.positions?.[n.id] || (draft?.id === n.id ? draft : n), grouped = isGroup(n),
         category = s.catalogue?.find(c => c.id === n.kind || c.name === n.kind || c.descriptor?.engine === n.kind),
         categoryName = (category?.family || n.kind).toLowerCase(),
         [categoryColor, categoryIcon] = ({get:[A.cyan,'folder'],host:[A.cyan,'folder'],input:[A.blue,'code'],trigger:[A.cyan,'clock'],
           change:[A.warn,'edit'],shape:[A.warn,'group'],transform:[A.warn,'edit'],document:[A.accent,'docs'],
           decide:[A.purple,'brain'],logic:[A.purple,'code'],ai:[A.purple,'brain'],agent:[A.purple,'user'],
           see:[A.ok,'eye'],watch:[A.ok,'eye'],check:[A.ok,'check'],send:[A.ok,'send'],output:[A.ok,'export']})[categoryName] || [A.blue,'canvas'],
         color = grouped ? A.purple : categoryColor,
         members = (n.children || []).map(id => s.graph.nodes.find(x => x.id === id)).filter(Boolean),
         state = n.frozen ? 'Disabled' : n.previewOff ? 'Preview off' : n.status || 'Idle', stateColor = /error|fail|refus/i.test(state) ? A.err : /approval|wait|warning|changed/i.test(state) ? A.warn : /running/i.test(state) ? A.accent : /done|ran/i.test(state) ? A.ok : A.inkSoft;
       return <div key={n.id} data-graph-node={n.id} style={{position:'absolute',width:224,opacity:n.frozen ? .5 : 1,left:position.x,top:position.y}} onDoubleClick={() => openNode(n)}>
         <D.Node w={224} glyph={<window.AHIcon name={grouped ? 'group' : categoryIcon} size={12} />} gc={color}
           title={n.title} sub={grouped ? `group · ${members.length} members` : category?.name || n.kind}
           stacked={grouped} edge={!n.inputs.length && n.outputs.length ? 'l' : n.inputs.length && !n.outputs.length ? 'r' : undefined}
           selected={selected.includes(n.id)} run={/running/i.test(state)} dashed={n.frozen}
           foot={state + (n.elapsedMs ? ' · ' + n.elapsedMs + ' ms' : '')} footc={stateColor}
           ins={n.inputs} outs={n.outputs} renderPort={(p,i,side) => <div className="canvas-port-row" style={{justifyContent:side === 'out' ? 'flex-end' : undefined}}><span style={{position:'absolute',[side === 'in' ? 'left' : 'right']:-11,top:0}}>{socket(n,p,side)}</span>{p.name}</div>}
           headerProps={{className:'node-header',onPointerDown:e=>startNode(e,n),onPointerMove:move,onPointerUp:end,
             onPointerCancel:()=>{gesture.current=null;setDraft(null);}}}
           headerEnd={<button className="button-reset canvas-node-menu" aria-label={n.title+' menu'} title={n.title+' actions'} onClick={event=>executeAction('projects.ds_screens.NodeMenu.16',{n,openNode,setSelected,u},event)}>⋯</button>}
           chip={grouped && <div className="canvas-members">{members.map(m=><button key={m.id} data-group-member={m.id} className="canvas-member" title={'Open '+m.title} onClick={event=>executeAction('projects.controls.activate',{handler:()=>{setParent(n.id);setSelected([m.id]);}},event)}><span style={{background:color,color:A.onFill}}>{m.title.slice(0,1)}</span>{m.title}</button>)}</div>}>
           {!grouped && Object.entries(n.params).slice(0,3).map(([k,v])=><div className="canvas-card-param" key={k}><span>{k}</span><span>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span></div>)}
         </D.Node>
       </div>;
     })}
    </div>
    {from && <Chip c={A.warn}>Choose an input socket to connect</Chip>}
    <div className="canvas-toolbar"><Btn variant="controls" sm ghost aria-label="Zoom out" onClick={event => executeAction("projects.ds_screens.ZoomOut.20", {zoomAt,view}, event)}>−</Btn><button className="button-reset" onClick={event => executeAction("projects.ds_screens.ResetZoom.21", {zoomAt}, event)} title="Reset zoom">{Math.round(zoom * 100)}%</button><Btn variant="controls" sm ghost aria-label="Zoom in" onClick={event => executeAction("projects.ds_screens.ZoomIn.22", {zoomAt,view}, event)}>+</Btn><Btn variant="controls" sm ghost onClick={event => executeAction("projects.ds_screens.Fit.23", {fit}, event)}>Fit</Btn></div>
    <div style={{
            position: 'absolute',
            bottom: 20,
            left: '50%',
            transform: 'translateX(-50%)'
          }}><Btn variant="controls" onClick={event => executeAction("projects.ds_screens.AddANodeCtrlK.24", {u}, event)}>/ Add a node · Ctrl K</Btn></div>
   </div>
   {wire && <aside className="pane inspector" style={{borderLeft:'1px solid '+A.line,padding:16}} aria-label="Wire">
     <div className="spread"><h2>Wire</h2><Btn variant="controls" sm ghost aria-label="Close wire" onClick={event=>executeAction('projects.controls.activate',{handler:()=>setWireId(null)},event)}>×</Btn></div>
     <div className="grid" style={{marginTop:16}}><div className="flex">{['Rules','Data'].map(t=><button className="tab-button" key={t} aria-pressed={wireTab===t} onClick={event=>executeAction('projects.ds_screens.SetTabT.27',{setTab:setWireTab,t},event)}>{t}</button>)}</div>
       <label className="grid">Pass when<input aria-label="Wire rule" value={wire.rule || ''} onChange={e=>u.act(()=>api.setWireRule(wire.id,e.target.value))} /></label>
       {wireTab==='Data' && <window.UI.Table rows={[{from:s.graph.nodes.find(n=>n.id===wire.from)?.title,to:s.graph.nodes.find(n=>n.id===wire.to)?.title,type:wire.type}]} />}
       <Btn variant="controls" danger sm onClick={event=>executeAction('projects.ds_screens.DeleteWire.28',{api,u,wire},event)}>Delete wire…</Btn>
     </div></aside>}

  </div>
 </div>;
    return <>
      {requestState === 'waiting' && <div role="status">Loading your graph…</div>}
      {requestState === 'error' && <div role="alert">{requestError}<Btn variant="controls" onClick={event => executeAction('projects.controls.activate', {handler:reload}, event)}>Retry loading graph</Btn></div>}
      {requestState === 'empty' && <><p className="muted">Add a node from the Library to start this graph.</p>{body}</>}
      {requestState === 'loaded' && <>{body}</>}
    </>;
  }
  function SystemGraph() {
    const s = useData(),
      u = useApp();
    const [page, setPage] = React.useState('BABOOM');
    return <div data-screen="system" style={{
      display: 'grid',
      gridTemplateRows: '50px 1fr',
      minHeight: 0
    }}><div className="spread" style={{
        padding: '0 20px',
        borderBottom: '1px solid ' + A.line
      }}><div className="flex"><Btn sm ghost onClick={event => executeAction("projects.ds_screens.Settings.30", {u}, event)}>← Settings</Btn><h2>System graph</h2><Chip>{s.pages.length} nodes</Chip></div><Btn sm onClick={event => executeAction("projects.ds_screens.OpenParameters.31", {page,u}, event)}>Open parameters</Btn></div><div className="node-canvas scroll" style={{
        padding: 30,
        overflow: 'auto'
      }}><div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, minmax(240px,1fr))',
          gap: 30,
          alignItems: 'start'
        }}>{s.pages.map(p => <D.Node key={p} title={p} glyph="⬡" gc={A.purple} sub="Application node" selected={page === p} w="100%" foot={s.settings.filter(r => r.page === p).length + ' parameters'} headerProps={{
            onClick: () => setPage(p)
          }} headerEnd={<Btn sm ghost onClick={event => executeAction("projects.ds_screens.Open.32", {p,u}, event)}>Open</Btn>}><div style={{
              padding: 12
            }}>{s.settings.filter(r => r.page === p).slice(0, 3).map(row => <SettingControl key={row.id} row={row} />)}</div></D.Node>)}</div></div></div>;
  }
  window.UI.Canvas = Canvas;
  window.UI.SystemGraph = SystemGraph;

// WIRE-projects: each rendered callback is registered with its executable owner.
function projectsdsscreensjsxNavigateHome5({u}, event) {
  const handler = () => u.go('home');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxParent6({parent,s,setParent,setSelected}, event) {
  const handler = () => {
            const g = s.graph.nodes.find(n => n.id === parent);
            setParent(g?.parent || null);
            setSelected(g ? [g.id] : []);
          };
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxGraphs7({u}, event) {
  const handler = () => u.show('Graphs');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxWorkspaces8({u}, event) {
  const handler = () => u.show('Workspaces');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxToggleLibrary9({u}, event) {
  const handler = () => u.setLibraryOpen(v => !v);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxGroup10({group}, event) {
  const handler = group;
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxUndo11({api,u}, event) {
  const handler = () => u.act(api.undo);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxRedo12({api,u}, event) {
  const handler = () => u.act(api.redo);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxArrange13({api,u}, event) {
  const handler = () => u.act(api.arrangeGraph);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxSaveSkill14({u}, event) {
  const handler = () => u.show('Save skill');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxRun15({api,u}, event) {
  const handler = async () => {
            const t = await u.act(() => api.runNode());
            if (t) {
              u.show('Run', {id:t.id});
            }
          };
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxNodeMenu16({n,openNode,setSelected,u}, event) {
  const handler = () => {
                  setSelected([n.id]);
                  u.show('Node menu', {
                    id: n.id,
                    open: () => openNode(n)
                  });
                };
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxZoomOut20({zoomAt,view}, event) {
  const handler = () => zoomAt(view.current.zoom / 1.2);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxResetZoom21({zoomAt}, event) {
  const handler = () => zoomAt(1);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxZoomIn22({zoomAt,view}, event) {
  const handler = () => zoomAt(view.current.zoom * 1.2);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxFit23({fit}, event) {
  const handler = fit;
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxAddANodeCtrlK24({u}, event) {
  const handler = () => u.show('Search');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxSetTabT27({setTab,t}, event) {
  const handler = () => setTab(t);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxDeleteWire28({api,u,wire}, event) {
  const handler = () => u.confirm('Delete this wire?', () => api.deleteWire(wire.id));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxSettings30({u}, event) {
  const handler = () => u.go('settings/System graph');
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxOpenParameters31({page,u}, event) {
  const handler = () => u.go('settings/' + page);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxOpen32({p,u}, event) {
  const handler = () => u.go('settings/' + p);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
const PROJECT_ACTIONS = {
  "projects.ds_screens.NavigateHome.5": "projectsdsscreensjsxNavigateHome5",
  "projects.ds_screens.Parent.6": "projectsdsscreensjsxParent6",
  "projects.ds_screens.Graphs.7": "projectsdsscreensjsxGraphs7",
  "projects.ds_screens.Workspaces.8": "projectsdsscreensjsxWorkspaces8",
  "projects.ds_screens.ToggleLibrary.9": "projectsdsscreensjsxToggleLibrary9",
  "projects.ds_screens.Group.10": "projectsdsscreensjsxGroup10",
  "projects.ds_screens.Undo.11": "projectsdsscreensjsxUndo11",
  "projects.ds_screens.Redo.12": "projectsdsscreensjsxRedo12",
  "projects.ds_screens.Arrange.13": "projectsdsscreensjsxArrange13",
  "projects.ds_screens.SaveSkill.14": "projectsdsscreensjsxSaveSkill14",
  "projects.ds_screens.Run.15": "projectsdsscreensjsxRun15",
  "projects.ds_screens.NodeMenu.16": "projectsdsscreensjsxNodeMenu16",
  "projects.ds_screens.ZoomOut.20": "projectsdsscreensjsxZoomOut20",
  "projects.ds_screens.ResetZoom.21": "projectsdsscreensjsxResetZoom21",
  "projects.ds_screens.ZoomIn.22": "projectsdsscreensjsxZoomIn22",
  "projects.ds_screens.Fit.23": "projectsdsscreensjsxFit23",
  "projects.ds_screens.AddANodeCtrlK.24": "projectsdsscreensjsxAddANodeCtrlK24",
  "projects.ds_screens.SetTabT.27": "projectsdsscreensjsxSetTabT27",
  "projects.ds_screens.DeleteWire.28": "projectsdsscreensjsxDeleteWire28",
  "projects.ds_screens.Settings.30": "projectsdsscreensjsxSettings30",
  "projects.ds_screens.OpenParameters.31": "projectsdsscreensjsxOpenParameters31",
  "projects.ds_screens.Open.32": "projectsdsscreensjsxOpen32"
};
window.registerActions(PROJECT_ACTIONS, {projectsdsscreensjsxNavigateHome5,projectsdsscreensjsxParent6,projectsdsscreensjsxGraphs7,projectsdsscreensjsxWorkspaces8,projectsdsscreensjsxToggleLibrary9,projectsdsscreensjsxGroup10,projectsdsscreensjsxUndo11,projectsdsscreensjsxRedo12,projectsdsscreensjsxArrange13,projectsdsscreensjsxSaveSkill14,projectsdsscreensjsxRun15,projectsdsscreensjsxNodeMenu16,projectsdsscreensjsxZoomOut20,projectsdsscreensjsxResetZoom21,projectsdsscreensjsxZoomIn22,projectsdsscreensjsxFit23,projectsdsscreensjsxAddANodeCtrlK24,projectsdsscreensjsxSetTabT27,projectsdsscreensjsxDeleteWire28,projectsdsscreensjsxSettings30,projectsdsscreensjsxOpenParameters31,projectsdsscreensjsxOpen32});
})();
