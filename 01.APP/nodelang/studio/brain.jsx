// Brain full view uses the same adapter facts as the Settings projection.
(() => {
  const {executeAction} = window.ArchHubAPI;
  const {
    A,
    api,
    useData,
    useApp,
    Btn,
    Card,
    Chip,
    Heading
  } = window.UI;
  const Icon = window.AHIcon;
  function Brain() {
    const s = useData(),
      u = useApp();
    const [query, setQuery] = React.useState(''),
      [focus, setFocus] = React.useState('self'),
      [zoom, setZoom] = React.useState(1),
      [pan, setPan] = React.useState({
        x: 0,
        y: 0
      });
    const [request, setRequest] = React.useState({status:'waiting',error:''}),
      [attempt,setAttempt] = React.useState(0);
    React.useEffect(() => {
      let active=true; setRequest({status:'waiting',error:''});
      api.refreshBrain().then(rows=>{if(active)setRequest({status:rows.length?'loaded':'empty',error:''});})
        .catch(error=>{if(active)setRequest({status:'error',error:error.message});});
      return()=>{active=false;};
    },[attempt,s.profile.id]);
    const drag = React.useRef(null);
    const graph = api.getKnowledgeGraph(),
      selected = graph.nodes.find(n => n.id === focus);
    const q = query.toLowerCase();
    const shown = graph.nodes.filter(n => !q || n.label.toLowerCase().includes(q) || n.type.toLowerCase().includes(q));
    const colors = {
      You: A.accent,
      Project: A.blue,
      Person: A.ok,
      Program: A.purple,
      Preference: A.warn,
      Memory: A.inkSoft
    };
    return <main className="page brain-page" data-screen="brain"><Heading title="Brain" sub="A picture of what your agents know about you"><Chip c={A.ok}>{s.brain.length} memories</Chip><Btn sm onClick={() => executeAction("ui.download", u, 'Brain')}>Export</Btn><Btn sm onClick={() => executeAction("ui.go", u, 'settings/Brain')}>Settings</Btn></Heading>{request.status === 'waiting' && <p role="status">Reading your Brain…</p>}{request.status === 'error' && <div role="alert">{request.error}<Btn sm onClick={() => executeAction('ui.state',setAttempt,n=>n+1)}>Retry Brain</Btn></div>}{request.status === 'empty' && <p>No memories yet. Remember a rule to add one.</p>}{request.status === 'loaded' && <p role="status">Brain read confirmed.</p>}<div className="brain-layout"><section className="knowledge-map"><div className="map-header spread"><div className="flex"><Icon name="brain" /><h3>Your knowledge</h3></div><input aria-label="Search Brain" placeholder="People, projects, programs, memories…" value={query} onChange={e => setQuery(e.target.value)} /></div><svg className="knowledge-svg" viewBox="0 0 860 560" aria-label="Knowledge map" onWheel={e => setZoom(z => Math.max(.5, Math.min(2, z + (e.deltaY < 0 ? .08 : -.08))))} onPointerDown={e => {
            if (e.target.closest?.('[data-knowledge-node]')) return;
            drag.current = {
              x: e.clientX,
              y: e.clientY,
              pan
            };
            e.currentTarget.setPointerCapture(e.pointerId);
          }} onPointerMove={e => {
            if (drag.current) setPan({
              x: drag.current.pan.x + e.clientX - drag.current.x,
              y: drag.current.pan.y + e.clientY - drag.current.y
            });
          }} onPointerUp={() => drag.current = null}><defs><pattern id="brain-grid" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="#29292f" /></pattern><radialGradient id="brain-halo"><stop stopColor="#d97757" stopOpacity=".12" /><stop offset="1" stopColor="#d97757" stopOpacity="0" /></radialGradient></defs><rect width="860" height="560" fill="url(#brain-grid)" /><g transform={`translate(${pan.x} ${pan.y}) translate(430 280) scale(${zoom}) translate(-430 -280)`}><circle cx="430" cy="260" r="200" fill="url(#brain-halo)" />{graph.edges.map(e => {
                const a = graph.nodes.find(n => n.id === e.from),
                  b = graph.nodes.find(n => n.id === e.to);
                return <g key={e.to} opacity={q && !shown.includes(b) ? .2 : 1}><path d={`M${a.x} ${a.y} Q${(a.x + b.x) / 2} ${(a.y + b.y) / 2 - 35} ${b.x} ${b.y}`} stroke={focus === b.id ? colors[b.type] : '#3d3b40'} strokeWidth={focus === b.id ? 1.8 : 1} fill="none" /><text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 10} fontSize="9" fill="#77716c" textAnchor="middle">{e.label}</text></g>;
              })}{graph.nodes.map(n => <g key={n.id} data-knowledge-node={n.id} role="button" tabIndex="0" aria-label={'Focus ' + n.label} style={{
                cursor: 'pointer',
                outline: 'none'
              }} opacity={q && !shown.includes(n) ? .2 : 1} onClick={() => executeAction("ui.state", setFocus, n.id)} onKeyDown={e => {
                if (e.key === 'Enter') setFocus(n.id);
              }}><circle cx={n.x} cy={n.y} r={n.id === 'self' ? 37 : focus === n.id ? 23 : 17} fill={colors[n.type] + '20'} stroke={colors[n.type]} strokeWidth={focus === n.id ? 2 : 1} /><circle cx={n.x} cy={n.y} r={n.id === 'self' ? 9 : 4} fill={colors[n.type]} /><text x={n.x} y={n.y + (n.id === 'self' ? 58 : 37)} fill={focus === n.id ? '#ece8e0' : '#aaa29a'} fontSize={n.id === 'self' ? 13 : 11} textAnchor="middle">{n.label.length > 30 ? n.label.slice(0, 29) + '…' : n.label}</text></g>)}</g></svg><div className="map-controls flex"><Btn sm ghost aria-label="Brain zoom out" onClick={() => executeAction("ui.state", setZoom, z => Math.max(.5, z - .15))}><Icon name="minus" size={16} /></Btn><span className="mono">{Math.round(zoom * 100)}%</span><Btn sm ghost aria-label="Brain zoom in" onClick={() => executeAction("ui.state", setZoom, z => Math.min(2, z + .15))}><Icon name="plus" size={16} /></Btn><Btn sm onClick={() => {
              executeAction("ui.state", setZoom, 1);
              executeAction("ui.state", setPan, {
                x: 0,
                y: 0
              });
              executeAction("ui.state", setFocus, graph.nodes[0]?.id || null);
            }}>Fit</Btn></div><div className="knowledge-legend">{Object.entries(colors).map(([type, c]) => <span key={type}><i style={{
                background: c
              }} />{type}</span>)}</div></section><aside className="brain-side"><Card style={{
            padding: 20
          }}><div className="flex muted"><Icon name={selected?.type === 'Program' ? 'code' : ['Preference','Memory'].includes(selected?.type) ? 'pin' : 'user'} /><span className="label">{selected?.type || 'Search'}</span></div><h2 style={{
              margin: '15px 0 8px'
            }}>{selected?.label || 'Select a point'}</h2><p className="muted">{['Preference','Memory'].includes(selected?.type) ? 'A remembered rule your agents use.' : selected?.type === 'Project' ? 'Connected to your team, programs and project files.' : 'Connected through your shared work.'}</p>{['Preference','Memory'].includes(selected?.type) ? <div className="flex" style={{
              marginTop: 16
            }}><Btn sm onClick={() => executeAction("ui.show", u, 'Edit rule', {
                id: selected.id,
                text: selected.label
              })}>Edit</Btn><Btn sm onClick={() => executeAction("ui.confirm", u, 'Forget this rule?', () => api.forgetMemory(selected.id))}>Forget</Btn></div> : <button className="listbutton flex" style={{
              marginTop: 12
            }} onClick={() => selected?.type === 'Program' ? executeAction("ui.go", u, 'settings/Connections') : selected?.type === 'Project' ? executeAction("ui.go", u, 'canvas') : executeAction("ui.show", u, 'My profile')}>Open {selected?.type === 'Program' ? 'connection' : selected?.type === 'Project' ? 'project' : 'profile'}<Icon name="arrow" size={15} /></button>}</Card><Card style={{
            padding: 20
          }}><div className="spread"><h3>Sources</h3><Btn sm title="Check evidence" aria-label="Check evidence" onClick={async () => {
                await executeAction("addNode", u, "Evidence attribution");
                executeAction("ui.go", u, "canvas");
              }}><Icon name="shield" size={16} /></Btn></div>{s.connections.filter(c => ['Notion', 'Google Drive', 'Outlook', 'Revit'].includes(c.name)).map(c => <button key={c.id} className="source-row" onClick={() => executeAction("ui.show", u, 'Connection', {
              id: c.id
            })}><span className="source-icon"><Icon name={c.name === 'Revit' ? 'canvas' : c.name === 'Outlook' ? 'workshop' : 'docs'} size={16} /></span><span className="fill">{c.name}</span><span className={'status-dot ' + (!c.connected ? 'off' : '')} /></button>)}</Card></aside></div><window.UI.UncertainLinks /><window.UI.IntakeRules /><window.UI.BrainControls /><window.UI.BrainSuggestions /><div className="brain-bottom"><section><div className="spread" style={{
            marginBottom: 12
          }}><h2>What your agents know about you</h2><Btn sm ghost aria-label="Remember a rule" onClick={() => executeAction("ui.show", u, 'Remember')}><Icon name="plus" size={16} /></Btn></div><div className="memory-cards">{s.brain.filter(r => (s.settings.find(s => s.id === 'Brain.Namespace')?.value || 'User') === (r.scope || 'User')).filter(r => s.settings.find(s => s.id === 'Brain.Recall source')?.value === 'All' || r.source.includes(s.settings.find(s => s.id === 'Brain.Recall source')?.value || '')).filter(r => !q || r.text.toLowerCase().includes(q)).map(r => <Card key={r.id} style={{
              padding: 18
            }}><div className="spread"><span className="eyebrow">Preference</span><div className="flex"><Btn sm onClick={() => executeAction("ui.show", u, 'Edit rule', {
                    id: r.id,
                    text: r.text
                  })}>Edit</Btn><Btn sm onClick={() => executeAction("ui.confirm", u, 'Forget this rule?', () => api.forgetMemory(r.id))}>Forget</Btn></div></div><p style={{
                margin: '12px 0'
              }}>{r.text}</p><span className="muted mono" style={{
                fontSize: 11
              }}>{r.source}</span></Card>)}</div>{q && <p className="muted" style={{
            paddingTop: 12
          }}>{shown.length} knowledge matches</p>}</section><section className="memory-timeline"><h2>Recent memory</h2>{s.brain.map((r, i) => <div key={r.id} className="timeline-item"><i /><div><small className="muted">{i === 0 ? 'Most recent' : 'Earlier'} · {r.source}</small><p>{r.text}</p></div></div>)}</section></div></main>;
  }
  window.UI.Brain = Brain;
})();
