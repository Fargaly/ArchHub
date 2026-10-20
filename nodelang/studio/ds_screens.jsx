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
  const typeColor = t => ({
    elements: A.accent,
    text: A.cyan,
    number: A.warn,
    boolean: A.purple,
    file: A.ok,
    event: A.cyan,
    any: A.inkSoft,
    view: A.cyan
  })[t] || A.accent;
  function NodeProperties({
    node,
    socket,
    openNode
  }) {
    const u = useApp(),
      meta = api.getNodeParameters(node).filter(p => !node.parameterPresentation?.[p.key]?.hidden).sort((a, b) => (node.parameterPresentation?.[a.key]?.order ?? 0) - (node.parameterPresentation?.[b.key]?.order ?? 0)),
      groups = [...new Set(meta.map(p => p.group))];
    const [changed, setChanged] = React.useState(false);
    return <div className="node-properties"><div className="spread" style={{
        margin: '8px 0 12px'
      }}><span className="label">PROPERTIES</span><button className="icon-button" aria-label="Node actions" title="Node actions" onClick={event => executeAction("projects.ds_screens.NodeActions.1", {node,openNode,u}, event)}><window.AHIcon name="more" /></button></div><label className="parameter-row"><span>Name</span><input aria-label="Node name" value={node.title} onChange={e => u.act(() => api.renameNode(node.id, e.target.value))} /></label><div className="spread" style={{
        padding: '12px 0',
        fontSize: 12
      }}><span>Changed only</span><D.Toggle label="Changed only" checked={changed} onCheckedChange={setChanged} /></div>{groups.map(group => <section key={group} className="parameter-group"><h3>{group}</h3>{meta.filter(p => p.group === group && (!changed || node.params[p.key] !== node.defaults[p.key])).map(p => {
          const value = node.params[p.key],
            dirty = JSON.stringify(value) !== JSON.stringify(node.defaults[p.key]);
          return <div key={p.key} className="parameter-row" data-parameter={p.key}><label htmlFor={'param-' + node.id + '-' + p.key}>{dirty && <i className="changed-dot" />}{p.label}</label><div className="param-editor">{p.type === 'boolean' ? <span className="spread"><span className="mono muted">{value ? 'Yes' : 'No'}</span><D.Toggle label={p.label} checked={value} onCheckedChange={v => u.act(() => api.setNodeParam(node.id, p.key, v))} /></span> : p.options ? <select id={'param-' + node.id + '-' + p.key} aria-label={p.label} value={value} onChange={e => u.act(() => api.setNodeParam(node.id, p.key, e.target.value))}>{p.options.map(o => <option key={o} value={o}>{p.optionLabels?.[o] || o}</option>)}</select> : <div className="flex" style={{
                gap: 3
              }}><input id={'param-' + node.id + '-' + p.key} aria-label={p.label} type={p.type === 'number' ? 'number' : p.type === 'color' ? 'color' : 'text'} value={value} step={p.unit === 'mm' ? 100 : 1} onChange={e => u.act(() => api.setNodeParam(node.id, p.key, p.type === 'number' ? Number(e.target.value) : e.target.value))} /> {p.type === 'path' && <label className="icon-button" title={'Choose ' + p.label} aria-label={'Choose ' + p.label}><window.AHIcon name="folder" size={15} /><input className="sr-only" aria-label={'Browse ' + p.label} type="file" onChange={e => {
                    const f = e.target.files?.[0];
                    if (f) u.act(() => api.setNodeParam(node.id, p.key, f.name));
                    e.target.value = '';
                  }} /></label>}{p.unit && <span className="mono muted unit">{p.unit}</span>}</div>}</div><div className="flex parameter-socket-group" style={{
              gap: 2
            }}>{dirty && <button className="icon-button reset-param" aria-label={'Reset ' + p.label} title={'Reset ' + p.label} onClick={event => executeAction("projects.ds_screens.UActApiResetNodeParamNode.2", {api,node,p,u}, event)}><window.AHIcon name="undo" size={12} /></button>}{socket(node, {
                id: p.key,
                name: p.label,
                type: p.type === 'number' ? 'number' : p.type === 'boolean' ? 'boolean' : p.type === 'path' ? 'file' : 'text'
              }, 'in')}</div></div>;
        })}</section>)}<window.UI.NodeRunPolicy id={node.id} /><button className="listbutton flex muted" onClick={event => executeAction("projects.ds_screens.AddParameter.3", {node,u}, event)}><window.AHIcon name="plus" size={14} />Add parameter</button><div className="spread" style={{
        paddingTop: 18
      }}><span className="muted mono" style={{
          fontSize: 11
        }}>{node.status}</span><Btn p sm onClick={event => executeAction("projects.ds_screens.Run.4", {api,node,u}, event)}>Run</Btn></div></div>;
  }
  function Canvas({
    embedded = false
  }) {
    const s = useData(),
      u = useApp();
    const [selected, setSelected] = React.useState(u.selectedNodeId && s.graph.nodes.some(n => n.id === u.selectedNodeId) ? [u.selectedNodeId] : []),
      [wireId, setWireId] = React.useState(null),
      [tab, setTab] = React.useState('Parameters'),
      [parent, setParent] = React.useState(null),
      [zoom, setZoom] = React.useState((s.settings.find(r => r.id === 'Appearance.Zoom percentage')?.value || 80) / 100),
      [pan, setPan] = React.useState({
        x: 0,
        y: 0
      }),
      [draft, setDraft] = React.useState(null),
      [marquee, setMarquee] = React.useState(null),
      [from, setFrom] = React.useState(null),
      [paths, setPaths] = React.useState([]),
      [pinnedInspector, setPinnedInspector] = React.useState(null);
    const area = React.useRef(),
      world = React.useRef(),
      gesture = React.useRef(null);
    const [requestState, setRequestState] = React.useState('waiting');
    const [requestError, setRequestError] = React.useState('');
    const reload = () => {
      setRequestState('waiting');
      return api.refreshProjects().then(() => {
        setRequestState(api.getSnapshot().graph.nodes.length ? 'loaded' : 'empty');
      }).catch(error => {
        setRequestError(error.message);
        setRequestState('error');
      });
    };
    React.useEffect(() => { reload(); }, []);
    React.useEffect(() => {
      if (requestState === 'loaded' || requestState === 'empty')
        setRequestState(s.graph.nodes.length ? 'loaded' : 'empty');
    }, [s.graph.nodes.length]);
    const visible = s.graph.nodes.filter(n => (n.parent || null) === parent),
      node = s.graph.nodes.find(n => n.id === (pinnedInspector || selected.at(-1))),
      wire = s.graph.wires.find(w => w.id === wireId);
    React.useEffect(() => {
      const listener = e => {
        if (e.target.matches('input,textarea,select')) return;
        if (e.ctrlKey && e.key.toLowerCase() === 'g') {
          e.preventDefault();
          group();
        }
        if (e.key === 'Delete' && selected.length) {
          e.preventDefault();
          remove();
        }
        if (e.key === 'Enter' && node?.children) setParent(node.id);
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
      return () => window.removeEventListener('keydown', listener);
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
    }, [s.revision, parent, zoom, draft]);
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
      }}><D.Socket t={p.type} size={10} filled={s.graph.wires.some(w => side === 'out' ? w.from === n.id && w.fromPort === p.id : w.to === n.id && w.toPort === p.id)} /></span>;
    };
    const startNode = (e, n) => {
      if (e.button !== 0 || e.target.closest('button,input,select,[data-endpoint]')) return;
      e.stopPropagation();
      setWireId(null);
      setSelected(e.shiftKey ? [...new Set([...selected, n.id])] : selected.includes(n.id) ? selected : [n.id]);
      const moving = selected.includes(n.id) ? selected : [n.id];
      gesture.current = {
        nodes: s.graph.nodes.filter(x => moving.includes(x.id)).map(x => ({
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
      const g = gesture.current;
      if (g?.kind === 'node') {
        const dx = (e.clientX - g.sx) / zoom,
          dy = (e.clientY - g.sy) / zoom;
        setDraft({
          id: g.id,
          x: g.x + dx,
          y: g.y + dy,
          positions: Object.fromEntries(g.nodes.map(n => [n.id, {
            x: n.x + dx,
            y: n.y + dy
          }]))
        });
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
    const end = () => {
      const g = gesture.current;
      if (g?.kind === 'node' && draft) u.act(() => api.moveNodes(draft.positions));
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
      const w = area.current?.clientWidth || 1000,
        h = area.current?.clientHeight || 600;
      const maxX = Math.max(...visible.map(n => n.x + 260), 300),
        maxY = Math.max(...visible.map(n => n.y + 240), 300);
      setZoom(Math.min(1, (w - 60) / maxX, (h - 80) / maxY));
      setPan({
        x: 10,
        y: 10
      });
    };
    const openNode = n => {
      if (n.kind.toLowerCase().includes('meeting')) u.go('meetings');else if (n.kind === 'Watch program') u.act(() => api.windowAction('hide'));else if (n.kind === 'Present') u.go('present');else if (['Community', 'Community group', 'Marketplace listing', 'Project charge'].includes(n.kind)) u.go('community');else if (n.kind === 'Interface studio' || n.kind === 'UI element') u.go('interface');else if (n.kind.startsWith('TBP ')) u.go('model-review');else if (n.kind === 'Theme') u.go('settings/Appearance');else if (n.kind === 'Graph link') {
        if (n.params.targetGraph) u.act(() => api.selectGraph(n.params.targetGraph));else u.show('Graphs');
      } else if (n.kind === 'Agent') u.show('Agent', {
        id: n.params.provider
      });else if (n.kind === 'Research') u.go('xray');else if (n.kind === 'History') u.go('receipts');else if (['Remember', 'Recall'].includes(n.kind)) u.go('brain');else if (['Social media', 'Read video', 'Read mail', 'Read file', 'Tutorial', 'Digest'].includes(n.kind)) u.go('social');else if (n.kind === 'X-RAY') u.go('xray');else if (['Account access', 'Billing & usage', 'Office invitations'].includes(n.kind)) u.go('access');else if (n.kind === 'Model routing') u.go('routing');else if (n.kind === 'Workshop') u.go('workshop');else if (n.kind === 'BABOOM') u.go('baboom');else if (n.kind === 'Watcher') u.go('watcher');else if (n.children) {
        setParent(n.id);
        setSelected([]);
      } else u.show('Node', {
        id: n.id
      });
    };
    const body = <div data-screen="canvas" style={{
      display: 'grid',
      gridTemplateRows: '50px minmax(0,1fr)',
      minHeight: 0
    }}>
  <div className="spread" style={{
        padding: '0 18px',
        borderBottom: '1px solid ' + A.lineSoft,
        background: '#0f0f13'
      }}><div className="flex"><button className="button-reset muted" onClick={event => executeAction("projects.ds_screens.NavigateHome.5", {u}, event)}>{s.graph.name} ›</button>{parent ? <Btn sm ghost onClick={event => executeAction("projects.ds_screens.Parent.6", {parent,s,setParent,setSelected}, event)}>← Parent</Btn> : <button className="button-reset flex" title="Graphs" aria-label="Graphs" onClick={event => executeAction("projects.ds_screens.Graphs.7", {u}, event)}>{s.graph.name}<window.AHIcon name="more" size={16} /></button>}<Chip>{visible.length} nodes</Chip><Btn sm ghost onClick={event => executeAction("projects.ds_screens.Workspaces.8", {u}, event)}>Workspaces · {s.workspaces.length}</Btn></div><div className="flex"><button className="icon-button" aria-label="Toggle Library" title="Library" aria-expanded={u.libraryOpen} onClick={event => executeAction("projects.ds_screens.ToggleLibrary.9", {u}, event)}><window.AHIcon name="library" /></button><select aria-label="Wire visibility" value={s.graph.wireVisibility || 'Visible'} onChange={e => u.act(() => api.setWireVisibility(e.target.value))}>{['Visible', 'Faint', 'Hidden'].map(x => <option key={x}>{x}</option>)}</select><Btn sm title="Group · Ctrl G" onClick={event => executeAction("projects.ds_screens.Group.10", {group}, event)} disabled={selected.length < 2}>Group</Btn><Btn sm onClick={event => executeAction("projects.ds_screens.Undo.11", {api,u}, event)} title="Undo · Ctrl Z">↶</Btn><Btn sm onClick={event => executeAction("projects.ds_screens.Redo.12", {api,u}, event)} title="Redo · Ctrl Shift Z">↷</Btn><Btn sm onClick={event => executeAction("projects.ds_screens.Arrange.13", {api,u}, event)}>Arrange</Btn><Btn sm onClick={event => executeAction("projects.ds_screens.SaveSkill.14", {u}, event)}>Save skill</Btn><Btn p sm onClick={event => executeAction("projects.ds_screens.Run.15", {api,u}, event)}>▶ Run</Btn></div></div>
  <div style={{
        display: 'grid',
        gridTemplateColumns: (u.libraryOpen ? '248px ' : '') + 'minmax(0,1fr) 340px',
        minHeight: 0
      }}>{u.libraryOpen && <window.UI.LibraryShelf onClose={() => u.setLibraryOpen(false)} />}
   <div ref={area} className="node-canvas" title="Drag to pan · Shift-drag to select" onPointerDown={e => {
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
          gesture.current = null;
          setDraft(null);
        }} onWheel={e => {
          if (e.ctrlKey) {
            e.preventDefault();
            setZoom(z => Math.max(.2, Math.min(2, z + (e.deltaY < 0 ? .05 : -.05))));
          } else setPan(p => ({
            x: p.x - e.deltaX,
            y: p.y - e.deltaY
          }));
        }} onDragOver={e => e.preventDefault()} onDrop={e => {
          e.preventDefault();
          const name = e.dataTransfer.getData('node');
          if (name) {
            const r = area.current.getBoundingClientRect();
            u.act(() => api.addNode(name, {
              x: (e.clientX - r.left - pan.x) / zoom,
              y: (e.clientY - r.top - pan.y) / zoom
            }));
            u.setLibraryOpen(false);
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
              pointerEvents: 'none'
            }}>{paths.map(({
                w,
                a,
                b
              }) => <g key={w.id}><path d={curve(a, b)} stroke="transparent" strokeWidth="18" fill="none" style={{
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
                }} /><path d={curve(a, b)} stroke={wireId === w.id ? A.ink : typeColor(w.type)} strokeWidth={wireId === w.id ? 4 : 2} opacity={s.graph.wireVisibility === 'Hidden' || s.graph.nodes.find(n => n.id === w.from)?.portVisibility?.[w.fromPort] === 'Hidden' ? 0 : s.graph.wireVisibility === 'Faint' || s.graph.nodes.find(n => n.id === w.from)?.portVisibility?.[w.fromPort] === 'Faint' ? .2 : 1} fill="none" /></g>)}</svg>
     {visible.map(n => {
              const position = draft?.positions?.[n.id] || (draft?.id === n.id ? draft : n);
              return <div key={n.id} data-graph-node={n.id} style={{
                position: 'absolute',
                opacity: n.frozen ? .5 : 1,
                left: position.x,
                top: position.y
              }} onDoubleClick={() => openNode(n)}>
      <D.Node w={250} glyph={n.children ? '◎' : n.kind === 'Watcher' ? '◉' : n.kind === 'Workshop' ? '◎' : n.kind === 'Level' ? '#' : '⬡'} gc={typeColor(n.outputs[0]?.type)} title={n.title} sub={n.children ? `Group · ${n.children.length} nodes` : n.kind} selected={selected.includes(n.id)} foot={(n.status.startsWith('Error') ? '⚠ ' : n.status.startsWith('Warning') ? '△ ' : n.previewOff ? '◌ ' : 'ⓘ ') + (n.status.startsWith('Error') || n.status.startsWith('Warning') ? n.status : n.previewOff ? 'Preview off' : n.status) + (n.elapsedMs ? ' · ' + n.elapsedMs + ' ms' : '')} footc={n.status === 'Done' ? A.ok : n.status.includes('approval') ? A.warn : A.inkSoft} style={{
                  borderRadius: 12,
                  background: 'linear-gradient(180deg,#1c1c22,#17171c)',
                  boxShadow: '0 8px 24px #0007'
                }} headerProps={{
                  className: 'node-header',
                  onPointerDown: e => startNode(e, n),
                  title: n.children ? n.children.map(id => s.graph.nodes.find(x => x.id === id)?.title).join(' → ') : n.title,
                  onPointerMove: move,
                  onPointerUp: end,
                  onPointerCancel: () => {
                    gesture.current = null;
                    setDraft(null);
                  }
                }} headerEnd={<button className="button-reset" aria-label={n.title + ' menu'} onClick={event => executeAction("projects.ds_screens.NodeMenu.16", {n,openNode,setSelected,u}, event)}>⋯</button>}>
       <div style={{
                    padding: '4px 14px 10px'
                  }}>{Object.entries(n.params).filter((_, i) => i < 3).map(([k, v]) => <div className="spread" key={k} style={{
                      fontSize: 12,
                      minHeight: 30
                    }}><span className="flex">{socket(n, {
                          id: k,
                          name: k,
                          type: typeof v === 'number' ? 'number' : typeof v === 'boolean' ? 'boolean' : 'text'
                        }, 'in')}<span className="muted">{k}</span></span><button className="button-reset" style={{
                        background: '#24242b',
                        borderRadius: 5,
                        padding: '2px 8px'
                      }} onClick={event => executeAction("projects.ds_screens.SetSelectedNId.17", {n,setSelected}, event)}>{String(v)}</button></div>)}</div>
       <div className="spread" style={{
                    borderTop: '1px solid ' + A.line,
                    padding: '6px 0',
                    alignItems: 'start'
                  }}><div>{n.inputs.map(p => <div key={p.id} className="flex" style={{
                        gap: 2,
                        fontSize: 12,
                        marginLeft: -11
                      }}>{socket(n, p, 'in')}{p.name}</div>)}</div><div>{n.outputs.map(p => <div key={p.id} className="flex" style={{
                        gap: 2,
                        fontSize: 12,
                        marginRight: -11,
                        justifyContent: 'end'
                      }}>{p.name}{socket(n, p, 'out')}</div>)}</div></div>
       <div className="flex" style={{
                    padding: '6px 12px'
                  }}><Btn sm ghost onClick={event => executeAction("projects.ds_screens.Open.18", {n,openNode}, event)}>Open</Btn><Btn sm ghost onClick={event => executeAction("projects.ds_screens.Run.19", {api,n,u}, event)}>Run</Btn></div>
      </D.Node>
     </div>;
            })}
    </div>
    {from && <Chip c={A.warn}>Choose an input socket to connect</Chip>}
    <div className="canvas-toolbar"><Btn sm ghost aria-label="Zoom out" onClick={event => executeAction("projects.ds_screens.ZoomOut.20", {setZoom}, event)}>−</Btn><button className="button-reset" onClick={event => executeAction("projects.ds_screens.ResetZoom.21", {setZoom}, event)} title="Reset zoom">{Math.round(zoom * 100)}%</button><Btn sm ghost aria-label="Zoom in" onClick={event => executeAction("projects.ds_screens.ZoomIn.22", {setZoom}, event)}>+</Btn><Btn sm ghost onClick={event => executeAction("projects.ds_screens.Fit.23", {fit}, event)}>Fit</Btn></div>
    <div style={{
            position: 'absolute',
            bottom: 20,
            left: '50%',
            transform: 'translateX(-50%)'
          }}><Btn onClick={event => executeAction("projects.ds_screens.AddANodeCtrlK.24", {u}, event)}>/ Add a node · Ctrl K</Btn></div>
   </div>
   {node || wire ? <aside className="pane inspector" style={{
          borderLeft: '1px solid ' + A.line,
          padding: 16
        }}><div className="spread"><div><h2 style={{
                fontSize: 16
              }}>{wire ? 'Wire' : node.title}</h2><p className="muted mono" style={{
                fontSize: 10,
                marginTop: 4
              }}>{wire ? wire.type : node.kind}</p></div><button className="icon-button" title={pinnedInspector ? 'Unpin properties' : 'Pin properties'} aria-label={pinnedInspector ? 'Unpin properties' : 'Pin properties'} onClick={event => executeAction("projects.ds_screens.SetPinnedInspectorPinnedInspectorNullNodeId.25", {node,pinnedInspector,setPinnedInspector}, event)}><window.AHIcon name="pin" size={15} /></button><Btn sm ghost aria-label="Close properties" onClick={event => executeAction("projects.ds_screens.CloseProperties.26", {setPinnedInspector,setSelected,setWireId}, event)}>×</Btn></div>
    {wire ? <div className="grid" style={{
            marginTop: 16
          }}><div className="flex">{['Rules', 'Data'].map(t => <button className="tab-button" key={t} aria-pressed={tab === t} onClick={event => executeAction("projects.ds_screens.SetTabT.27", {setTab,t}, event)}>{t}</button>)}</div><label className="grid">Pass when<input aria-label="Wire rule" value={wire.rule} onChange={e => u.act(() => api.setWireRule(wire.id, e.target.value))} /></label>{tab === 'Data' && <window.UI.Table rows={[{
              from: s.graph.nodes.find(n => n.id === wire.from)?.title,
              to: s.graph.nodes.find(n => n.id === wire.to)?.title,
              type: wire.type
            }]} />}<Btn danger sm onClick={event => executeAction("projects.ds_screens.DeleteWire.28", {api,u,wire}, event)}>Delete wire…</Btn></div> : <>{selected.length > 1 && <window.UI.MixedProperties ids={selected} />}<NodeProperties key={node.id} node={node} socket={socket} openNode={openNode} />{node.children && <window.UI.CompositeParameters id={node.id} />}<details style={{
              marginTop: 16
            }}><summary>Results &amp; ports</summary><div className="grid" style={{
                paddingTop: 14
              }}><window.UI.Table rows={node.output || []} /><Btn sm onClick={event => executeAction("projects.ds_screens.Export.29", {node,u}, event)}>Export</Btn>{[...node.inputs, ...node.outputs].map(p => <div className="flex" key={p.id}>{socket(node, p, node.outputs.includes(p) ? 'out' : 'in')}{p.name} · {p.type}</div>)}</div></details></>}
   </aside> : <aside className="pane inspector" style={{
          padding: 18
        }}><window.UI.GraphProperties /></aside>}
  </div>
 </div>;
    return <>
      {requestState === 'waiting' && <div role="status">Loading your graph…</div>}
      {requestState === 'error' && <div role="alert">{requestError}<Btn onClick={event => executeAction('projects.controls.activate', {handler:reload}, event)}>Retry loading graph</Btn></div>}
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
function projectsdsscreensjsxNodeActions1({node,openNode,u}, event) {
  const handler = () => u.show('Node menu', {
          id: node.id,
          open: () => openNode(node)
        });
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxUActApiResetNodeParamNode2({api,node,p,u}, event) {
  const handler = () => u.act(() => api.resetNodeParam(node.id, p.key));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxAddParameter3({node,u}, event) {
  const handler = () => u.show('Add parameter', {
        id: node.id
      });
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxRun4({api,node,u}, event) {
  const handler = async () => {
          const t = await u.act(() => api.runNode(node.id));
          if (t?.approvalId) u.show('Approve', {
            id: t.approvalId
          });
        };
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
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
function projectsdsscreensjsxSetSelectedNId17({n,setSelected}, event) {
  const handler = () => setSelected([n.id]);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxOpen18({n,openNode}, event) {
  const handler = () => openNode(n);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxRun19({api,n,u}, event) {
  const handler = () => u.act(() => api.runNode(n.id));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxZoomOut20({setZoom}, event) {
  const handler = () => setZoom(z => Math.max(.2, z - .1));
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxResetZoom21({setZoom}, event) {
  const handler = () => setZoom(1);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxZoomIn22({setZoom}, event) {
  const handler = () => setZoom(z => Math.min(2, z + .1));
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
function projectsdsscreensjsxSetPinnedInspectorPinnedInspectorNullNodeId25({node,pinnedInspector,setPinnedInspector}, event) {
  const handler = () => setPinnedInspector(pinnedInspector ? null : node?.id);
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxCloseProperties26({setPinnedInspector,setSelected,setWireId}, event) {
  const handler = () => {
              setPinnedInspector(null);
              setSelected([]);
              setWireId(null);
            };
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
function projectsdsscreensjsxExport29({node,u}, event) {
  const handler = () => u.download('Results', node.id);
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
  "projects.ds_screens.NodeActions.1": "projectsdsscreensjsxNodeActions1",
  "projects.ds_screens.UActApiResetNodeParamNode.2": "projectsdsscreensjsxUActApiResetNodeParamNode2",
  "projects.ds_screens.AddParameter.3": "projectsdsscreensjsxAddParameter3",
  "projects.ds_screens.Run.4": "projectsdsscreensjsxRun4",
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
  "projects.ds_screens.SetSelectedNId.17": "projectsdsscreensjsxSetSelectedNId17",
  "projects.ds_screens.Open.18": "projectsdsscreensjsxOpen18",
  "projects.ds_screens.Run.19": "projectsdsscreensjsxRun19",
  "projects.ds_screens.ZoomOut.20": "projectsdsscreensjsxZoomOut20",
  "projects.ds_screens.ResetZoom.21": "projectsdsscreensjsxResetZoom21",
  "projects.ds_screens.ZoomIn.22": "projectsdsscreensjsxZoomIn22",
  "projects.ds_screens.Fit.23": "projectsdsscreensjsxFit23",
  "projects.ds_screens.AddANodeCtrlK.24": "projectsdsscreensjsxAddANodeCtrlK24",
  "projects.ds_screens.SetPinnedInspectorPinnedInspectorNullNodeId.25": "projectsdsscreensjsxSetPinnedInspectorPinnedInspectorNullNodeId25",
  "projects.ds_screens.CloseProperties.26": "projectsdsscreensjsxCloseProperties26",
  "projects.ds_screens.SetTabT.27": "projectsdsscreensjsxSetTabT27",
  "projects.ds_screens.DeleteWire.28": "projectsdsscreensjsxDeleteWire28",
  "projects.ds_screens.Export.29": "projectsdsscreensjsxExport29",
  "projects.ds_screens.Settings.30": "projectsdsscreensjsxSettings30",
  "projects.ds_screens.OpenParameters.31": "projectsdsscreensjsxOpenParameters31",
  "projects.ds_screens.Open.32": "projectsdsscreensjsxOpen32"
};
window.registerActions(PROJECT_ACTIONS, {projectsdsscreensjsxNodeActions1,projectsdsscreensjsxUActApiResetNodeParamNode2,projectsdsscreensjsxAddParameter3,projectsdsscreensjsxRun4,projectsdsscreensjsxNavigateHome5,projectsdsscreensjsxParent6,projectsdsscreensjsxGraphs7,projectsdsscreensjsxWorkspaces8,projectsdsscreensjsxToggleLibrary9,projectsdsscreensjsxGroup10,projectsdsscreensjsxUndo11,projectsdsscreensjsxRedo12,projectsdsscreensjsxArrange13,projectsdsscreensjsxSaveSkill14,projectsdsscreensjsxRun15,projectsdsscreensjsxNodeMenu16,projectsdsscreensjsxSetSelectedNId17,projectsdsscreensjsxOpen18,projectsdsscreensjsxRun19,projectsdsscreensjsxZoomOut20,projectsdsscreensjsxResetZoom21,projectsdsscreensjsxZoomIn22,projectsdsscreensjsxFit23,projectsdsscreensjsxAddANodeCtrlK24,projectsdsscreensjsxSetPinnedInspectorPinnedInspectorNullNodeId25,projectsdsscreensjsxCloseProperties26,projectsdsscreensjsxSetTabT27,projectsdsscreensjsxDeleteWire28,projectsdsscreensjsxExport29,projectsdsscreensjsxSettings30,projectsdsscreensjsxOpenParameters31,projectsdsscreensjsxOpen32});
})();
