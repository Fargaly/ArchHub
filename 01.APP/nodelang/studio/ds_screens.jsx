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

    Chip
  } = window.UI;
  const curve = (a, b) => `M${a.x} ${a.y} C${(a.x + b.x) / 2} ${a.y},${(a.x + b.x) / 2} ${b.y},${b.x} ${b.y}`;
  const wirePath = (a, b, kind) => kind === 'Straight' ? `M${a.x} ${a.y} L${b.x} ${b.y}` : kind === 'Step' ? `M${a.x} ${a.y} L${(a.x + b.x) / 2} ${a.y} L${(a.x + b.x) / 2} ${b.y} L${b.x} ${b.y}` : curve(a, b);
  const isGroup = n => n.children?.length > 0 || n.kind === 'Group' || n.kind === 'Workshop';
  const NODE_FAMILY_STYLE = {
    get:[A.cyan,'folder'],host:[A.cyan,'folder'],read:[A.cyan,'folder'],input:[A.blue,'code'],trigger:[A.cyan,'clock'],
    change:[A.warn,'edit'],shape:[A.warn,'group'],filter:[A.warn,'group'],transform:[A.warn,'edit'],document:[A.accent,'docs'],compose:[A.accent,'docs'],annotate:[A.accent,'edit'],
    decide:[A.purple,'brain'],logic:[A.purple,'code'],ai:[A.purple,'brain'],agent:[A.purple,'user'],
    see:[A.ok,'eye'],watch:[A.ok,'eye'],watcher:[A.ok,'eye'],check:[A.ok,'check'],send:[A.ok,'send'],output:[A.ok,'export']};
  function fitCanvasViewport(boxes, width, height, zoomMin, zoomMax, zoomFitMax) {
    if (!boxes.length || !(width > 0) || !(height > 0)) return null;
    const minX = Math.min(...boxes.map(box => box.x)), minY = Math.min(...boxes.map(box => box.y));
    const spanW = Math.max(...boxes.map(box => box.x + box.w)) - minX;
    const spanH = Math.max(...boxes.map(box => box.y + box.h)) - minY;
    const zoom = Math.max(zoomMin, Math.min(zoomMax, zoomFitMax, (width - 60) / Math.max(1, spanW), (height - 60) / Math.max(1, spanH)));
    return {zoom, pan: {x: (width - spanW * zoom) / 2 - minX * zoom, y: (height - spanH * zoom) / 2 - minY * zoom}};
  }
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
  function measureWires(world, wires) {
    if (!world) return [];
    const bounds=world.getBoundingClientRect(), scale=world.offsetWidth/bounds.width || 1, sockets=new Map([...world.querySelectorAll('[data-port-key]')].map(el=>{
      const r=el.getBoundingClientRect();return [el.dataset.portKey,{x:(r.left+r.width/2-bounds.left)*scale,y:(r.top+r.height/2-bounds.top)*scale}];
    }));
    return wires.map(w=>({w,a:sockets.get(`${w.from}:out:${w.fromPort}`),b:sockets.get(`${w.to}:in:${w.toPort}`)})).filter(p=>p.a&&p.b);
  }
  // Saved NodeCard colours come from the shared Penpot palette.
  const SPEC = {node:'var(--color-bg-panel)',line:'var(--color-line)',slot:'var(--color-bg-soft)',hollow:'var(--color-ink-muted)',panel:'var(--color-bg-panel)',field:'var(--color-bg-panel)',fieldLine:'var(--color-line)',
    text:'var(--color-ink)',label:'var(--color-ink-soft)',count:'var(--color-ink-muted)',link:'var(--color-accent-hi)',number:'var(--color-ink)',typed:'var(--color-cyan)',rule:'var(--color-bg-raised)',exposed:'var(--color-accent-dim)'};
  // Node-RED status pattern: one colour on the card edge plus one status line under it (spec State/* components).
  const nodeState = (n, rejected) => n.frozen ? ['Disabled', A.inkDim] : rejected ? ['Types do not match', A.err]
    : n.previewOff ? ['Preview off', A.inkSoft]
    : /saved/i.test(n.status) ? ['Saved', A.ok]
    : /await/i.test(n.status) ? ['Awaiting', A.warn]
    : /approval|needs you|in review/i.test(n.status) ? ['Needs you', A.warn]
    : /agent|working|wip/i.test(n.status) ? ['Working', A.ink]
    : /error|fail|refus/i.test(n.status) ? ['Failed · ' + (n.error || 'retry'), A.err]
    : /block|held|wait/i.test(n.status) ? ['Blocked · upstream', A.inkSoft]
    : /stale|changed|out of date/i.test(n.status) ? ['Out of date · Run', A.warn]
    : /running|updating/i.test(n.status) ? ['Updating…', A.cyan]
    : /done|ran/i.test(n.status) ? ['Done', A.ok] : ['Not run', A.inkSoft];
  // Spec Wire/*: compatible cyan, affected downstream warn, rejected drag err; one stroke width (wire.strokeWidth = 2).
  const wireColor = (w, nodes) => w.rejected ? A.err : /^(Updating|Out of date)/.test(nodeState(nodes.find(n=>n.id===w.to) || {}, false)[0]) ? A.warn : A.cyan;
  // DESIGNSYS-050 4.9 Wire: ONE stroke for the Canvas (FlowWire) and the System graph (GraphWires); Penpot Wire/Compatible, wire.strokeWidth 2.
  function WirePath({id, state, d, color, dash, opacity, route}) {
    return <path data-graph-wire={id} data-wire-state={state} data-wire-route={route || 'Bezier'} d={d} stroke={color} strokeWidth="2" strokeLinecap="round" strokeDasharray={dash} opacity={opacity} fill="none" />;
  }
  function GraphWires({paths,visibility='Visible',nodes=[]}) {
    return <>{paths.map(({w,a,b})=>{
      const portVisibility=nodes.find(n=>n.id===w.from)?.portVisibility?.[w.fromPort],
        opacity=visibility==='Hidden'||portVisibility==='Hidden' ? 0 : visibility==='Faint'||portVisibility==='Faint' ? .2 : .9;
      return <WirePath key={w.id} id={w.id} route={w.route} d={wirePath(a,b,w.route)} color={typeColor(w.type)} dash={w.type==='event'?'6 2':undefined} opacity={opacity} />;
    })}</>;
  }
  const hostLabel = {fontSize: 'calc(11px * var(--text-scale,1))', color:A.inkSoft};
  const hostControl = {width:'100%', boxSizing:'border-box', background:A.bgSoft, color:A.ink, border:'1px solid '+A.line, borderRadius:A.rad.sm, padding:'6px 8px', font:'12px Inter, sans-serif'};
  const hostBlock = {display:'flex', flexDirection:'column', gap:4, marginBottom:8};
  function codeLanguage(host) {
    if (host === 'revit' || host === 'acad') return 'C#';
    if (host === 'acad-core') return 'LISP';
    if (host === 'max') return 'MAXScript';
    if (host === 'office') return 'Operation';
    return 'Python';
  }
  function runWord(n) {
    if (/running/i.test(n.status || '')) return 'Running';
    if (n.display === 'Waiting for you') return 'Waiting for you';
    if (n.status === 'Error' || n.display === 'Failed') return 'Failed';
    if (n.status === 'Done') return 'Done';
    return 'Draft';
  }
  function RunModeChip({waiting, count}) {
    const u = useApp();
    const [attempt, setAttempt] = React.useState(0);
    const [load, setLoad] = React.useState({status:'waiting', runMode:'', message:''});
    React.useEffect(() => {
      let live = true;
      setLoad(current => ({...current, status:'waiting'}));
      api.readPermissions().then(result => {
        if (!live) return;
        const mode = result.runMode || '';
        setLoad({status: mode ? 'loaded' : 'empty', runMode: mode, message:''});
      }).catch(error => { if (live) setLoad({status:'error', runMode:'', message: error.message || 'Could not read the run mode.'}); });
      return () => { live = false; };
    }, [attempt]);
    const pending = Number(count) > 0;
    const hot = !!waiting || pending;
    const label = pending ? load.runMode + ' · ' + count : load.runMode;
    return <>
      {load.status === 'waiting' && <span role="status" style={{fontSize: 'calc(11px * var(--text-scale,1))', color:A.inkSoft}}>Reading run mode</span>}
      {load.status === 'empty' && <span data-run-mode="" style={{fontSize: 'calc(11px * var(--text-scale,1))', color:A.inkSoft}}>Run mode: not reported</span>}
      {load.status === 'error' && <span role="alert" style={{fontSize: 'calc(11px * var(--text-scale,1))', color:A.err}}>{load.message} <button type="button" className="button-reset" onClick={event => executeAction('projects.controls.activate', {handler:() => setAttempt(value => value + 1)}, event)}>Retry</button></span>}
      {load.status === 'loaded' && <button type="button" data-run-mode={load.runMode} data-ask-count={pending ? count : 0} className="button-reset" onClick={event => executeAction('projects.controls.activate', {handler:() => u.go('settings/Hooks')}, event)} style={{height:20, padding:'0 8px', borderRadius:A.rad.pill, border:'1px solid '+(hot ? A.warn : A.line), color: hot ? A.warn : A.inkSoft, background:'transparent', fontSize: 'calc(11px * var(--text-scale,1))'}}>{label}</button>}
    </>;
  }
  function HostExecNode({n, selected, headerProps, renderPort}) {
    const u = useApp();
    const params = n.params || {};
    const [attempt, setAttempt] = React.useState(0);
    const [load, setLoad] = React.useState({status:'waiting', programs:[], state:null, message:''});
    React.useEffect(() => {
      let live = true;
      setLoad(current => ({...current, status:'waiting'}));
      Promise.all([api.hostPrograms(), api.hostProgramState(params.host || 'revit')]).then(([programs, state]) => {
        if (!live) return;
        const rows = programs.programs || [];
        setLoad({status: rows.length ? 'loaded' : 'empty', programs: rows, state, message:''});
      }).catch(error => { if (live) setLoad({status:'error', programs:[], state:null, message: error.message || 'Could not read the program.'}); });
      return () => { live = false; };
    }, [attempt, params.host]);
    const save = (key, value) => u.act(() => api.setNodeParam(n.id, key, value));
    const reachable = !!(load.state && load.state.reachable);
    const word = runWord(n);
    const runLabel = reachable ? 'Run' : (load.state && load.state.state) || 'Not available';
    const foot = <span style={{display:'flex', alignItems:'center', gap:8}}><RunModeChip waiting={word === 'Waiting for you'} /><span style={{color: word === 'Failed' ? A.err : word === 'Waiting for you' ? A.warn : A.ink}}>{word}</span></span>;
    return <D.Node data-host-exec="" w={LAYOUT.nodeWidth} title="Run in program" sub={load.status === 'loaded' && load.state ? load.state.state : 'Run in program'} selected={selected} headerProps={headerProps} renderPort={renderPort} ins={n.inputs} outs={n.outputs} foot={foot} footc={word === 'Failed' ? A.err : word === 'Waiting for you' ? A.warn : A.inkSoft} glyph={<window.AHIcon name="folder" size={12} />} gc={A.inkSoft}>
      {load.status === 'waiting' && <div role="status" aria-label="Loading" style={{display:'grid', gap:6}}><div style={{height:32, borderRadius:A.rad.sm, background:A.bgSoft}} /><div style={{height:32, borderRadius:A.rad.sm, background:A.bgSoft}} /></div>}
      {load.status === 'empty' && <p style={{fontSize: 'calc(12px * var(--text-scale,1))', color:A.inkSoft}}>No programs available.</p>}
      {load.status === 'error' && <div role="alert" style={{fontSize: 'calc(12px * var(--text-scale,1))', color:A.err}}>{load.message} <button type="button" className="button-reset" onClick={event => executeAction('projects.controls.activate', {handler:() => setAttempt(value => value + 1)}, event)}>Retry</button></div>}
      {load.status === 'loaded' && <div>
        <label style={hostBlock}><span style={hostLabel}>Program</span>
          <select aria-label="Program" value={params.host || ''} onChange={event => save('host', event.target.value)} style={hostControl}>{load.programs.map(row => <option key={row.id} value={row.id}>{row.label}</option>)}</select>
        </label>
        <label style={hostBlock}><span style={hostLabel}>Code</span>
          <textarea aria-label="Code" value={params.code || ''} onChange={event => save('code', event.target.value)} style={{...hostControl, minHeight:72, resize:'vertical'}} />
        </label>
        <p style={{fontSize: 'calc(11px * var(--text-scale,1))', color:A.inkSoft, margin:'0 0 8px'}}>{codeLanguage(params.host)}{params.host === 'revit' ? '. Revit: ' + params.sheet_limit + ' sheet per run, up to ' + params.element_limit + ' elements.' : params.host === 'acad-core' ? '. Choose a drawing for AutoCAD (background). ' + Math.round((params.min_free_bytes || 0) / 1073741824) + ' GiB free before it starts.' : '.'}</p>
        <label style={hostBlock}><span style={hostLabel}>Document</span>
          <input aria-label="Document" value={params.document || ''} onChange={event => save('document', event.target.value)} style={hostControl} />
        </label>
        <label style={{...hostBlock, flexDirection:'row', alignItems:'center'}}><input aria-label="Use a transaction" type="checkbox" checked={!!params.transaction} onChange={event => save('transaction', event.target.checked)} /> <span style={hostLabel}>Use a transaction</span></label>
        <label style={hostBlock}><span style={hostLabel}>Transaction name</span>
          <input aria-label="Transaction name" value={params.transaction_name || ''} onChange={event => save('transaction_name', event.target.value)} style={hostControl} />
        </label>
        <button type="button" disabled={!reachable} onClick={event => executeAction('projects.controls.activate', {handler:() => reachable ? api.runNode(n.id) : undefined}, event)} style={{height:28, padding:'0 12px', borderRadius:A.rad.sm, border: reachable ? 'none' : '1px dashed '+A.line, background: reachable ? A.accent : 'transparent', color: reachable ? A.onFill : A.inkSoft, fontSize: 'calc(12px * var(--text-scale,1))'}}>{runLabel}</button>
      </div>}
    </D.Node>;
  }
  function ConnectorActionNode({n, selected, headerProps, renderPort}) {
    const u = useApp();
    const params = n.params || {};
    const [attempt, setAttempt] = React.useState(0);
    const [load, setLoad] = React.useState({status:'waiting', connectors:[], actions:[], message:''});
    const [preview, setPreview] = React.useState({preview:''});
    React.useEffect(() => {
      let live = true;
      setLoad(current => ({...current, status:'waiting'}));
      api.connectorActions(params.connector || '').then(result => {
        if (!live) return;
        const actions = result.actions || [];
        setLoad({status: result.error ? 'error' : actions.length ? 'loaded' : 'empty', connectors: result.connectors || [], actions, message: result.error || ''});
      }).catch(error => { if (live) setLoad({status:'error', connectors:[], actions:[], message: error.message || 'Could not read actions.'}); });
      return () => { live = false; };
    }, [attempt, params.connector]);
    React.useEffect(() => {
      let live = true;
      if (!params.action) { setPreview({preview:''}); return undefined; }
      api.connectorPreview(params.connector || '', params.action, params.args).then(result => { if (live) setPreview(result); }).catch(() => { if (live) setPreview({preview:''}); });
      return () => { live = false; };
    }, [params.connector, params.action, params.args]);
    const save = (key, value) => u.act(() => api.setNodeParam(n.id, key, value));
    const chosen = load.actions.find(row => row.name === params.action);
    const word = runWord(n);
    const foot = <span style={{display:'flex', alignItems:'center', gap:8}}><RunModeChip waiting={word === 'Waiting for you'} /><span style={{color: word === 'Failed' ? A.err : word === 'Waiting for you' ? A.warn : A.ink}}>{word}</span></span>;
    return <D.Node data-connector-action="" w={LAYOUT.nodeWidth} title="Connector action" sub="Connector action" selected={selected} headerProps={headerProps} renderPort={renderPort} ins={n.inputs} outs={n.outputs} foot={foot} footc={word === 'Failed' ? A.err : word === 'Waiting for you' ? A.warn : A.inkSoft} glyph={<window.AHIcon name="send" size={12} />} gc={A.inkSoft}>
      {load.status === 'waiting' && <div role="status" aria-label="Loading" style={{display:'grid', gap:6}}><div style={{height:32, borderRadius:A.rad.sm, background:A.bgSoft}} /><div style={{height:32, borderRadius:A.rad.sm, background:A.bgSoft}} /></div>}
      {load.status === 'empty' && <div>
        <label style={hostBlock}><span style={hostLabel}>Connector</span>
          <select aria-label="Connector" value={params.connector || ''} onChange={event => save('connector', event.target.value)} style={hostControl}>{(load.connectors || []).map(row => <option key={row.id} value={row.id}>{row.label}</option>)}</select>
        </label>
        <p style={{fontSize: 'calc(12px * var(--text-scale,1))', color:A.inkSoft}}>No actions available. Connect the account, then choose an action.</p>
      </div>}
      {load.status === 'error' && <div role="alert" style={{fontSize: 'calc(12px * var(--text-scale,1))', color:A.err}}>Could not read actions. {load.message} <button type="button" className="button-reset" onClick={event => executeAction('projects.controls.activate', {handler:() => setAttempt(value => value + 1)}, event)}>Retry</button></div>}
      {load.status === 'loaded' && <div>
        <label style={hostBlock}><span style={hostLabel}>Connector</span>
          <select aria-label="Connector" value={params.connector || ''} onChange={event => save('connector', event.target.value)} style={hostControl}>{load.connectors.map(row => <option key={row.id} value={row.id}>{row.label}</option>)}</select>
        </label>
        <label style={hostBlock}><span style={hostLabel}>Action</span>
          <select aria-label="Action" value={params.action || ''} onChange={event => save('action', event.target.value)} style={hostControl}><option value="">Choose an action</option>{load.actions.map(row => <option key={row.name} value={row.name}>{row.title}</option>)}</select>
        </label>
        {chosen && (chosen.inputs || []).length > 0 && (chosen.inputs || []).map(name => <label key={name} style={hostBlock}><span style={hostLabel}>{name}</span>
          <input aria-label={name} value={(params.args && params.args[name]) || ''} onChange={event => save('args', {...(params.args && typeof params.args === 'object' ? params.args : {}), [name]: event.target.value})} style={hostControl} />
        </label>)}
        {chosen && !(chosen.inputs || []).length && <label style={hostBlock}><span style={hostLabel}>Args</span>
          <input aria-label="Args" value={typeof params.args === 'string' ? params.args : JSON.stringify(params.args || '')} onChange={event => save('args', event.target.value)} style={hostControl} />
        </label>}
        {preview.preview && <div style={hostBlock}><span style={hostLabel}>Text to send</span><p style={{margin:0, whiteSpace:'pre-wrap', fontSize: 'calc(12px * var(--text-scale,1))', color:A.ink}}>{preview.preview}</p></div>}
        <div aria-label="Result" style={{fontSize: 'calc(11px * var(--text-scale,1))', color:A.inkSoft, marginBottom:8}}>Result {word === 'Done' && n.output ? (typeof n.output.result === 'object' ? JSON.stringify(n.output.result) : String(n.output.result ?? '')) : ''}</div>
        <button type="button" onClick={event => executeAction('projects.controls.activate', {handler:() => api.runNode(n.id)}, event)} style={{height:28, padding:'0 12px', borderRadius:A.rad.sm, border:'none', background:A.accent, color:A.onFill, fontSize: 'calc(12px * var(--text-scale,1))'}}>Run</button>
      </div>}
    </D.Node>;
  }
  // e6e4a367 studio-lm.jsx NodeRenderer: category header, role edge and parameter body.
  function AgentWorkflowCard({n, renderPort, headerProps, selected, headerEnd, width = 304}) {
    const u = useApp();
    const status = n.role==='step'&&n.status==='blocked' ? 'Blocked' : ({working:'Working',blocked:'Waiting for you',done:'Done',idle:'Idle',resting:'Idle',stopped:'Stopped',failed:'Failed',open:'Planned',claimed:'In progress'})[n.status] || n.status;
    const color = /Working|Done|progress/.test(status) ? A.ok : /Waiting|Blocked/.test(status) ? A.warn : /Failed/.test(status) ? A.err : A.inkMuted;
    const message=n.message, at=message?.at ? new Date(message.at) : null, minutes=at ? Math.max(0,Math.floor((Date.now()-at.getTime())/60000)) : null;
    const textStyle={overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'};
    if (n.role === 'step') return <D.Node w={300} className="v22g-node" selected={selected} gc={color} glyph={<window.AHIcon name="workshop" size={12}/>} title={n.title} sub={n.kicker} ins={n.inputs} outs={n.outputs} renderPort={renderPort} headerProps={headerProps} headerEnd={headerEnd}
      foot={<span className="v48-step-actions"><span style={{marginRight:'auto',color}}>{status}</span><button type="button" className="button-reset nodrag" onClick={event=>executeAction('projects.controls.activate',{handler:n.openResult},event)}>History</button>{n.agentWork?.runnable && <button type="button" className="button-reset nodrag" disabled={/Working|progress/.test(status)} onClick={event=>executeAction('projects.controls.activate',{handler:async()=>{const result=await u.act(()=>api.runNode(n.id));if(result?.approvalId)u.show('Approve',{id:result.approvalId});}},event)}>Run step</button>}</span>}>
      <div className="v48-step-body" style={{display:'grid',gap:4,padding:'8px 10px 6px'}}><div className="v48-step-preview"><ResultPreview value={n.result || message?.text || 'Run to inspect output'}/></div>{(n.parameterSchema || []).filter(p=>['goal','model','detail','prompt','language'].includes(p.key)).map(p=><label key={p.key} className="v48-session-param"><span>{p.label || p.key}</span><ValueWidget n={n} p={p} value={n.params[p.key]} u={u}/></label>)}{n.actions && <details className="nodrag"><summary>Details</summary>{n.actions}</details>}</div>
    </D.Node>;
    return <D.Node w={width} className="agent-workflow-card" selected={selected} gc={color} glyph={<window.AHIcon name={n.role==='task'?'docs':'workshop'} size={12} />}
      title={<><span style={{display:'block',fontSize:11,fontWeight:500,color:A.inkSoft,textTransform:'uppercase'}}>{n.kicker}</span><span title={n.title}>{n.title}</span></>}
      sub="" ins={n.inputs} outs={n.outputs} renderPort={renderPort} headerProps={headerProps} headerEnd={headerEnd}
      style={{borderTop:'2px solid '+color}} foot={null}>
      {n.role!=='start' && <div style={{padding:'0 12px 10px',display:'grid',gap:8}}>
        <span style={{color,fontSize:11,fontWeight:500,background:A.bgSoft,borderRadius:10,padding:'2px 6px',justifySelf:'start',display:'flex',alignItems:'center',gap:4}}><span aria-hidden="true" style={{width:6,height:6,borderRadius:'50%',background:status==='Stopped'?'transparent':color,border:'1px solid '+color}} />{status}</span>
        {n.role==='task' ? <span style={{fontSize:12,color:A.inkSoft}}>{n.path ? n.steps+' steps' : 'No workflow file'}</span> : <>
          <div style={{...textStyle,fontSize:13}}><span style={{fontSize:11,color:A.inkSoft}}>{n.role==='step'?'By':'Task'} </span><span>{n.by || n.taskTitle || 'No task'}</span></div>
          {message && <div style={{...textStyle,fontSize:12,color:A.inkSoft}} title={message.id+' · '+message.at+' · '+message.text}><time dateTime={message.at} title={at?.toLocaleString()} style={{color:A.inkMuted,fontSize:11}}>{minutes===0?'Just now':minutes+' min ago'} </time>{message.text.split('\n')[0]}</div>}
          {n.result && <button type="button" className="button-reset nodrag" onClick={event=>executeAction('projects.controls.activate',{handler:n.openResult},event)} style={{...textStyle,textAlign:'left',fontSize:12,fontFamily:A.mono,color:A.inkSoft}} title={n.result}>{n.result}</button>}
        </>}
        {n.actions && <div style={{display:'flex',gap:16,fontSize:12,fontWeight:500}}>{n.actions}</div>}
      </div>}
    </D.Node>;
  }
  function NodeRenderer({n, catalogue = [], selected, headerProps, headerEnd, renderPort, renderSocket, rejected, members, onMember, onDetach, compact = false}) {
    const u = useApp(), s = useData(), [expanded,setExpanded] = React.useState(false), [parameterDrafts,setParameterDrafts] = React.useState({});
    const exact = catalogue.find(c=>c.id===n.definition||c.id===n.assembly||c.name===n.assembly||c.id===n.kind||c.name===n.kind),
      engines=catalogue.filter(c=>c.descriptor?.engine===n.kind), category=exact||(engines.length===1 ? engines[0] : null),
      family = (n.category || category?.family || n.kind).toLowerCase(), grouped = isGroup(n),
      [color, icon] = grouped ? [A.purple,'group'] : NODE_FAMILY_STYLE[family] || [A.blue,'canvas'],
      state = n.frozen ? 'Disabled' : n.previewOff ? 'Preview off' : n.status || 'Idle',
      stateColor = /error|fail|refus/i.test(state) ? A.err : /await/i.test(state) ? A.inkSoft : /saved/i.test(state) ? A.ok : /working|wip/i.test(state) ? A.accent : /approval|wait|warning|changed/i.test(state) ? A.warn : /running/i.test(state) ? A.accent : /done|ran/i.test(state) ? A.ok : A.inkSoft;
    // Plate 4.3: only the first three human values; Properties keeps every parameter.
    const parameters = Object.entries(n.params).filter(([key,value])=>!compact || n.parameterSchema?.some(p=>p.key===key && p.editable) ||
      (!/(^_|(?:^|_)(?:id|hash|instance|ref)(?:_|$)|^template_|^(?:engine|responsibility|last_result|last_attempt)$)/i.test(key) &&
       (value === null || typeof value !== 'object') &&
       !/(?:[a-f0-9]{32,}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}|(?:assembly|template|node)-instance:|^\s*[\[{][\s\S]*[\]}]\s*$)/i.test(String(value)))),
      foot = compact && /(?:[a-f0-9]{32,}|(?:assembly|template|node)-instance:)/i.test(state)
        ? (state.match(/^(?:blocked|error|failed|held|waiting|refused)\b/i)?.[0] || 'See Properties').replace(/^./,c=>c.toUpperCase()) : state;
    // Spec NodeCard: ComfyUI widget-to-input pattern, a parameter that is also an input carries its socket on its own slot.
    const spec = compact, [specFoot, specColor] = nodeState(n, rejected), shownKeys = (compact && !expanded ? parameters.slice(0,3) : parameters).map(([key])=>'param:'+key),
      slotPort = key => spec && renderSocket && n.inputs.find(p=>p.id==='param:'+key),
      field = spec && n.column && fieldColumn(n, s.graph), frame = spec && (n.column || n.dataset);
    if (field) return <FieldNode n={n} field={field} selected={selected} headerProps={headerProps} renderSocket={renderSocket} />;
    if (n.type === 'host.exec') return <HostExecNode n={n} selected={selected} headerProps={headerProps} renderPort={renderPort} />;
    if (n.type === 'connector.call') return <ConnectorActionNode n={n} selected={selected} headerProps={headerProps} renderPort={renderPort} />;
    return <D.Node className="lm-node" data-category={family} data-node-state={spec ? specFoot.split(' · ')[0] : undefined} data-spec={spec ? n.dataset ? 'dataset' : 'node' : undefined}
      w={spec ? n.dataset ? 340 : 156 : n.dataset ? 340 : 224} glyph={<window.AHIcon name={icon} size={12} />} gc={color}
      title={n.title} sub={grouped ? `group · ${(members || []).length} members` : category?.name || n.assembly || n.kind}
      style={spec ? {background:frame ? SPEC.panel : SPEC.node,border:frame ? 0 : '1px solid '+specColor,borderRadius:frame ? 12 : 8} : {borderTop:'2px solid '+color}} stacked={grouped}
      edge={spec ? undefined : !n.inputs.length && n.outputs.length ? 'l' : n.inputs.length && !n.outputs.length ? 'r' : undefined}
      selected={selected} run={!spec && /running/i.test(state)} dashed={!spec && n.frozen}
      foot={spec ? (specFoot === 'Done' ? null : <span title={n.error || state}>{specFoot}</span>) : (/^done\b/i.test(foot) ? null : <span title={state}>{foot + (n.error ? ' · '+n.error : '') + (n.elapsedMs ? ' · ' + n.elapsedMs + ' ms' : '')}</span>)} footc={spec ? specColor : stateColor}
      ins={spec ? n.inputs.filter(p=>!(renderSocket && shownKeys.includes(p.id))) : n.inputs} outs={n.outputs} renderPort={renderPort} portsAfterContent={spec}
      headerProps={{...headerProps,style:spec ? headerProps?.style : {borderTop:'2px solid '+color,borderBottom:'1px solid '+A.lineSoft,...headerProps?.style}}}
      headerEnd={<>{typeof n.pure === 'boolean' && <span data-node-pure={String(n.pure)} style={{fontSize: 'calc(10px * var(--text-scale,1))',color:n.pure ? A.inkSoft : A.warn}}
        title={n.pure ? 'Pure: re-solves on every edit' : 'Side effect: waits for Run'}>{n.pure ? 'Pure' : 'Side effect'}</span>}
        {spec && n.dataset && <span data-dataset-count>{n.dataset.records.length} records</span>}{headerEnd}</>} chip={grouped && <div className="canvas-members">{(members || []).map(m=><button key={m.id} data-group-member={m.id} draggable={m.chip || undefined} className="canvas-member nodrag" title={m.chip ? 'Drag '+m.title+' out of the group' : 'Open '+m.title} onDragStart={event=>{if(!m.chip)return;event.stopPropagation();event.dataTransfer.setData('text/plain',m.id);event.dataTransfer.effectAllowed='move';event.currentTarget.dataset.dragged='1';}} onDragEnd={event=>{if(!m.chip||!onDetach)return;onDetach(m,event);}} onClick={event=>{if(event.currentTarget.dataset.dragged==='1'){event.currentTarget.dataset.dragged='';return;}executeAction('projects.controls.activate',{handler:()=>onMember?.(m)},event);}}><span style={{background:color,color:A.onFill}}>{m.title.slice(0,1)}</span>{m.title}</button>)}</div>}>
      {!grouped && (compact && !expanded ? parameters.slice(0,3) : parameters).map(([key,value])=>{
        const p=n.parameterSchema?.find(p=>p.key===key), label=n.title+' '+key,
          shown=Object.hasOwn(parameterDrafts,key)?parameterDrafts[key]:value,
          save=v=>{
            setParameterDrafts(old=>({...old,[key]:v}));
            return u.act(()=>api.setNodeParam(n.id,key,v)).then(saved=>{
              if(!saved || saved.ok===false)return;
              setParameterDrafts(old=>{if(!Object.is(old[key],v))return old;const next={...old};delete next[key];return next;});
            });
          };
        return <div className="canvas-card-param" data-parameter={key} key={key}>{slotPort(key) && <span className="canvas-port-socket in">{renderSocket(slotPort(key))}</span>}<span title={p?.label || key}>{p?.label && p.label!==key ? p.label : key.replace(/_/g,' ').replace(/^./,c=>c.toUpperCase())}{p?.unit ? ' · '+p.unit : ''}</span>
          {p?.editable && (['string','number','boolean'].includes(typeof value) || p.type==='json') ? p.type==='boolean'
            ? <D.Toggle label={label} checked={shown} onCheckedChange={save} />
            : p.options?.length ? <select aria-label={label} value={shown} onChange={e=>save(e.target.value)}>{p.options.map(v=><option key={v}>{v}</option>)}</select>
            : p.type==='color' ? <input aria-label={label} type="color" value={shown} onChange={e=>save(e.target.value)} />
            : p.type==='date' ? <input aria-label={label} type="date" value={shown} onChange={e=>save(e.target.value)} />
            : p.type==='json' ? <input aria-label={label} title={JSON.stringify(shown)} value={typeof shown==='string'?shown:JSON.stringify(shown)} style={{width:96,minWidth:0}} onChange={e=>setParameterDrafts(old=>({...old,[key]:e.target.value}))} onBlur={e=>save(e.target.value)} />
            : <input aria-label={label} title={String(shown)} type={p.type==='number'?'number':'text'} min={p.min} max={p.max} step={p.step} value={shown} style={{width:96,minWidth:0}} onChange={e=>{if(p.type!=='number'||Number.isFinite(e.target.valueAsNumber))save(p.type==='number'?e.target.valueAsNumber:e.target.value);}} />
            : <span tabIndex={0} title={typeof value==='object'?JSON.stringify(value):String(value)}>{typeof value==='object'?JSON.stringify(value):String(value)}</span>}
          {p?.dataType && <small className="muted" data-param-type={p.dataType}>{p.dataType}</small>}
          {p?.linkedTo && <small data-linked-to title="Same value as the parameter it is exposed from">linked {'\u2192'} {p.linkedTo}</small>}
          {p?.promoted && <small data-linked-node title="Edited here or on its Parameter node: one value">linked node</small>}
          {!n.bind && n.paramDefs && api.promoteParam && key!=='engine' && <button className="button-reset" aria-label={(p?.promoted?'Demote ':'Expose as node ')+key} title={p?.promoted?'Demote: back to an inline parameter':'Expose as node'}
            onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.act(()=>p?.promoted?api.demoteParam(n.id,key):api.promoteParam(n.id,key))},event)}>{p?.promoted?'\u21b2':'\u21f1'}</button>}
        </div>;
      })}
      {!grouped && n.dataset && <DatasetEditor n={n} u={u} />}
      {!grouped && n.column && <small data-column-of={n.column.dataset+'.'+n.column.field} className="muted">{n.column.dataset ? <>{n.column.dataset}.{n.column.field} {'\u00b7'} {n.column.label} {'\u00b7'} values live in {n.column.dataset}</> : 'Unbound: wire a dataset field into column'}</small>}
      {!grouped && !n.bind && !n.dataset && !n.column && !n.children?.length && api.addNodeParameter && <AddParameter n={n} u={u} />}
      {!grouped && n.status==='Done' && <output aria-label={n.title+' output'} style={{display:'block',maxHeight:100,overflow:'auto',whiteSpace:'pre-wrap'}}>{typeof n.output==='object'?JSON.stringify(n.output):String(n.output)}</output>}
      {!grouped && compact && parameters.length>3 && <button className="button-reset canvas-card-more" onClick={event=>executeAction('projects.controls.activate',{handler:()=>setExpanded(!expanded)},event)}>{expanded ? 'Show less' : `+${parameters.length-3} more`}</button>}
    </D.Node>;
  }
  // Spec FieldNode (bound): a field node is its dataset's column as a typed list; values are read from the dataset only.
  const typeGlyph = t => ['number', 'integer'].includes(t) ? '#' : t === 'object' ? '◇' : '';
  const cellText = v => v && typeof v === 'object' ? JSON.stringify(v) : String(v ?? '');
  const fieldColumn = (n, graph) => {
    const dataset = graph.nodes.find(d => d.dataset && d.title === n.column.dataset), def = dataset?.dataset.fields.find(f => f.id === n.column.field);
    return def && {dataset, def, values: dataset.dataset.records.map(r => r.cells[def.id])};
  };
  function FieldNode({n, field: {dataset, def, values}, selected, headerProps, renderSocket}) {
    // Spec FieldNode 180x92: name, typed line, record count, one value strip; sockets at the card edges (y 44).
    const edge = side => ({position: 'absolute', [side === 'in' ? 'left' : 'right']: -11, top: 44, transform: 'translateY(-50%)', lineHeight: 0, zIndex: 2});
    return <div data-ds-node="" data-spec="field" className={'lm-node ' + (headerProps?.className || '')} {...headerProps} title={dataset.title + ' · ' + def.name}
      style={{position: 'relative', width: 180, height: 92, boxSizing: 'border-box', background: SPEC.field, border: '1px solid ' + SPEC.fieldLine, borderRadius: 6,
        outline: selected ? `2px solid ${A.accent}` : 'none', outlineOffset: 2}}>
      {renderSocket && n.inputs.map(p => <span key={p.id} style={edge('in')}>{renderSocket(p, 'in')}</span>)}
      {renderSocket && n.outputs.map(p => <span key={p.id} style={edge('out')}>{renderSocket(p, 'out')}</span>)}
      <div data-node-card-title="" style={{position: 'absolute', left: 12, top: 9, right: 40, fontSize: 'calc(14px * var(--text-scale,1))', lineHeight: 1.2, color: SPEC.text, whiteSpace: 'pre', overflow: 'hidden', textOverflow: 'ellipsis'}}>{typeGlyph(def.type) && typeGlyph(def.type) + '  '}{def.name}</div>
      <span data-record-count="" style={{position: 'absolute', right: 12, top: 11, fontSize: 'calc(var(--type-size-label) * var(--text-scale,1))', color: SPEC.label}} title="All records">{values.length}</span>
      <div style={{position: 'absolute', left: 12, top: 34, fontSize: 'calc(var(--type-size-label) * var(--text-scale,1))', lineHeight: 1.2, color: SPEC.typed}}>{n.column.label}{def.unit ? ' · ' + def.unit : ''}</div>
      <output data-column-of={n.column.dataset + '.' + n.column.field} data-todo="output-summary-expanded" style={{position: 'absolute', left: 8, right: 8, top: 56, height: 24, boxSizing: 'border-box', padding: '5px 6px', borderRadius: 5,
        background: SPEC.slot, fontSize: 'calc(var(--type-size-label) * var(--text-scale,1))', lineHeight: 1.2, color: SPEC.text, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>{values.slice(0, 3).map(cellText).join(', ')}{values.length > 3 ? '…' : ''}  ›</output>
    </div>;
  }
  // Spec FieldTypeMenu: a listbox of the server's parameter types (node_params.py), labelled as the design names them.
  const TYPE_LABEL = {bool: 'Boolean', integer: 'Integer', number: 'Number · units', text: 'Text', choice: 'Choice', date: 'Date', file: 'File', folder: 'Folder', object: 'Object', list: 'List'};
  function FieldTypeMenu({label, value, onChange, design}) {
    const [open, setOpen] = React.useState(false);
    return <span style={{position: 'relative', display: 'block'}}>
      <button type="button" data-design={design} className="button-reset spec-input" aria-label={label} aria-haspopup="listbox" aria-expanded={open} onClick={event => executeAction('projects.controls.activate', {handler: () => setOpen(!open)}, event)}>
        {typeGlyph(value) && typeGlyph(value) + '  '}{(TYPE_LABEL[value] || value).split(' · ')[0]}{'  ⌄'}</button>
      {open && <div role="listbox" aria-label="Field type" data-field-type-menu className="spec-type-menu" onKeyDown={e => { if (e.key === 'Escape') { e.stopPropagation(); setOpen(false); } }}>
        <b>Field type</b>{api.parameterTypes().map(t => <button type="button" role="option" aria-selected={t === value} key={t} className="button-reset"
          onClick={event => executeAction('projects.controls.activate', {handler: () => { onChange(t); setOpen(false); }}, event)}>{TYPE_LABEL[t] || t}</button>)}</div>}
    </span>;
  }
  // Spec AddField numeric editor: one form for a dataset field and a node parameter; the value is checked once, on the server.
  function AddField({kind, title, sub, onAdd, onClose, modal=false}) {
    const action=window.UI.useAction();
    const [name, setName] = React.useState(''), [type, setType] = React.useState('number'), [value, setValue] = React.useState(''), [options, setOptions] = React.useState(''),
      [limits, setLimits] = React.useState({min: '', max: '', step: '', unit: ''}), [asNode, setAsNode] = React.useState(false);
    const numeric = ['number', 'integer'].includes(type),tag=id=>kind==='Parameter'?'field.'+id:undefined,
      limit = (key, text) => <label key={key}>{text}<input data-design={tag({min:'minimum',max:'maximum',step:'step'}[key])} className="spec-input small" aria-label={kind + ' ' + key} type="number" step="any" placeholder={key === 'step' ? 'Auto' : 'Unbounded'} value={limits[key]} onChange={e => setLimits(old => ({...old, [key]: e.target.value === '' ? '' : e.target.valueAsNumber}))} /></label>;
    return <div data-add-field-form role="dialog" aria-label={title} className={'spec-add-field'+(modal?' v22g-add-parameter':'')} onPointerDown={e => e.stopPropagation()} onKeyDown={e => { if (e.key === 'Escape') onClose(); }}>
      <b>{title}</b><p>{sub}</p><window.UI.ActionStatus action={action}/>
      <div className="spec-add-row"><label>Name<input data-design={tag('name')} className="spec-input" aria-label={kind + ' name'} placeholder="Width" value={name} onChange={e => setName(e.target.value)} /></label>
        <label>Type{modal?<span data-design="field.type"><select data-design="param.type" aria-label="Parameter type" value={(TYPE_LABEL[type]||type).split(' · ')[0]} onChange={e=>setType(Object.keys(TYPE_LABEL).find(key=>TYPE_LABEL[key].split(' · ')[0]===e.target.value))}>{Object.entries(TYPE_LABEL).map(([key,label])=><option key={key}>{label.split(' · ')[0]}</option>)}</select></span>:<FieldTypeMenu design={tag('type')} label={kind + ' type'} value={type} onChange={setType} />}</label></div>
      {type === 'choice' && <label>Choices<input data-design={tag('choices')} className="spec-input" aria-label={kind + ' options'} placeholder="Choices, comma separated" value={options} onChange={e => setOptions(e.target.value)} /></label>}
      <label><span>Default{type === 'number' && <> {'·'} <input data-design={tag('parameter-unit')} className="spec-unit" aria-label={kind + ' unit'} placeholder="unit" value={limits.unit} onChange={e => setLimits(old => ({...old, unit: e.target.value}))} /></>}</span>
        <input data-design={tag('default')} className="spec-input" aria-label={kind + ' value'} type={numeric ? 'number' : type === 'date' ? 'date' : type==='bool'?'checkbox':'text'} {...(type==='bool'?{checked:value===true||value==='true'}:{value})} onChange={e => setValue(type==='bool'?e.target.checked:e.target.value)} /></label>
      {numeric && <div className="spec-add-limits">{limit('min', 'Minimum')}{limit('max', 'Maximum')}{limit('step', 'Step')}</div>}
      <div className="spec-add-foot"><label><input data-design={tag('apx')} type="checkbox" aria-label="Show as node" checked={asNode} onChange={e => setAsNode(e.target.checked)} /> Expose as node</label>
        {modal&&<button type="button" data-design="action.cancel" className="button-reset" onClick={event=>executeAction('projects.controls.activate',{handler:onClose},event)}>Cancel</button>}
        <button type="button" data-design={modal?'action.add-parameter':undefined} className="button-reset spec-add-go" disabled={!name.trim()} aria-label={title} onClick={event => executeAction('projects.controls.activate', {handler: () => action.run(()=>onAdd({name, type, value, showAsNode: asNode,
          ...(numeric ? Object.fromEntries(Object.entries(limits).filter(([, v]) => v !== '').map(([k, v]) => [k, k === 'unit' ? v : Number(v)])) : {}),
          options: type === 'choice' ? options.split(',').map(x => x.trim()).filter(Boolean) : undefined})).then(result=>{if(result)onClose();})}, event)}>{title}{modal?'':'  →'}</button></div>
    </div>;
  }
  // Spec Dataset: fields are columns, records are rows, cells are typed values; an exposed field is highlighted and marked.
  function DatasetEditor({n, u}) {
    const s = useData(), [adding, setAdding] = React.useState(false), [drafts, setDrafts] = React.useState({});
    const {fields, records} = n.dataset, exposed = f => s.graph.wires.some(w => w.from === n.id && w.fromPort === 'field:' + f.id);
    const cell = (index, f) => {
      const key = index + ':' + f.id, value = Object.hasOwn(drafts, key) ? drafts[key] : records[index].cells[f.id], label = n.title + ' record ' + (index + 1) + ' ' + f.name;
      const save = v => u.act(() => api.setDatasetCell(n.id, index, f.id, v)).then(() => setDrafts(old => { const next = {...old}; delete next[key]; return next; }));
      if (f.type === 'bool') return <D.Toggle label={label} checked={!!value} onCheckedChange={save} />;
      if (f.options?.length) return <select aria-label={label} value={value} onChange={e => save(e.target.value)}>{f.options.map(o => <option key={o}>{o}</option>)}</select>;
      return <input aria-label={label} value={cellText(value)} type={['number', 'integer'].includes(f.type) ? 'number' : f.type === 'date' ? 'date' : 'text'}
        onChange={e => setDrafts(old => ({...old, [key]: e.target.value}))} onBlur={e => Object.hasOwn(drafts, key) && save(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur(); }} />;
    };
    const columns = fields.map(fieldWidth).join('px ') + (fields.length ? 'px ' : '') + '80px';
    return <div data-dataset-editor onPointerDown={e => e.stopPropagation()}>
      <div data-dataset-grid style={{gridTemplateColumns: columns}}>
        {fields.map(f => <button key={f.id} type="button" className="button-reset" data-field={f.id} data-exposed={exposed(f) || undefined} aria-label={'Show field ' + f.name + ' as node'}
          title={exposed(f) ? 'Shown as node' : 'Show as node: the whole column as a typed list'} onClick={event => executeAction('projects.controls.activate', {handler: () => exposed(f) || u.act(() => api.exposeDatasetField(n.id, f.id))}, event)}>
          {typeGlyph(f.type) && typeGlyph(f.type) + ' '}{f.name}{exposed(f) ? ' ↗' : ''}</button>)}
        <button type="button" className="button-reset" data-dataset-link aria-label={'Add field to ' + n.title} onClick={event => executeAction('projects.controls.activate', {handler: () => setAdding(!adding)}, event)}>+ Field</button>
        {records.map((r, index) => <React.Fragment key={r.id}>{fields.map(f => <span key={f.id} data-record={index} data-cell-type={f.type} data-exposed={exposed(f) || undefined}>{cell(index, f)}</span>)}<span data-record={index} /></React.Fragment>)}
      </div>
      <div data-dataset-foot>
        <button type="button" className="button-reset" data-dataset-link aria-label={'Add record to ' + n.title} disabled={!fields.length}
          onClick={event => executeAction('projects.controls.activate', {handler: () => u.act(() => api.addDatasetRecord(n.id))}, event)}>+ Record</button>
        {fields.map(f => <small key={f.id}>{f.unit}</small>)}
      </div>
      {adding && <AddField kind="Field" title="Add field" sub="A column shared by every record" onClose={() => setAdding(false)}
        onAdd={input => u.act(() => api.addDatasetField(n.id, input))} />}
    </div>;
  }
  // Add parameter: the same AddField editor, opened from the card's + (spec NodeCard "Add parameter").
  function AddParameter({n, u}) {
    return <>
      <button className="button-reset canvas-card-add" data-add-parameter aria-label={'Add parameter to ' + n.title} title="Add parameter" onClick={event => executeAction('projects.controls.activate', {handler: () => u.show('Add parameter',{id:n.id})}, event)}>+ Parameter</button>
    </>;
  }
  // CANVASXY node grammar, archhub-canvas-build-spec.json (Penpot 1052): compact parameter nodes (LimitParameter 180x80),
  // field nodes (FieldNode 180x92) and operation nodes with aligned typed socket rows, inline widgets, a Pure badge and a
  // collapsed result summary (Filter / Model). Designer TODO hooks: output-summary-expanded, dataset-compact-header,
  // field-unbound, cell-refused-feedback, node-auto-height, isolated-native-component-pngs.
  const TYPE_NAME = {number: 'Number', integer: 'Integer', string: 'Text', text: 'Text', boolean: 'Boolean', bool: 'Boolean',
    list: 'List', object: 'Record', file: 'File', any: 'Any', elements: 'Elements', event: 'Event', view: 'View'};
  const typeName = p => (TYPE_NAME[p.type] || (p.type ? p.type.replace(/^./, c => c.toUpperCase()) : 'Any')) + (p.list ? '[]' : '') + (p.unit ? ' · ' + p.unit : '');
  const summary = value => {
    if (value === undefined || value === null || value === '' || (Array.isArray(value) && !value.length)) return '';
    if (Array.isArray(value)) return value.length + ' item' + (value.length === 1 ? '' : 's') + ' · ' + value.slice(0, 3).map(summary).join(', ');
    if (typeof value === 'object') return Object.entries(value).slice(0, 3).map(([k, v]) => k + ' ' + (v && typeof v === 'object' ? (Array.isArray(v) ? v.length + ' items' : 'record') : String(v))).join(' · ');
    return String(value).slice(0, 60);
  };
  const HIDDEN_VALUE = /(?:[a-f0-9]{32,}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}|(?:assembly|template|node)-instance:|^\s*[\[{][\s\S]*[\]}]\s*$)/i;
  const HIDDEN_PARAM = /(^_|(?:^|_)(?:id|hash|instance|ref)(?:_|$)|^template_|^(?:engine|responsibility|last_result|last_attempt)$)/i;
  const LAYOUT = {nodeWidth: parseFloat(window.getComputedStyle(document.documentElement).getPropertyValue('--layout-node-width')) || 256, datasetWidth: 340, inspectorWidth: 320};
  const FIELD_WIDTH = {text: 70, number: 92, integer: 108, point: 112, object: 112, bool: 70, choice: 108, date: 108, file: 112, folder: 112, list: 112};
  const NAMED_WIDTH = {id: 70, width: 92, position: 112, height: 108};
  const fieldWidth = field => {
    const given = Number(field && field.width);
    if (Number.isFinite(given) && given > 0) return given;
    const name = String(field && (field.name || field.id) || '').toLowerCase();
    return NAMED_WIDTH[name] || FIELD_WIDTH[field && field.type] || 92;
  };
  const CARD = {background: SPEC.field, border: '1px solid ' + SPEC.fieldLine, borderRadius: 6, boxSizing: 'border-box', position: 'relative', color: SPEC.text, fontSize: 'calc(var(--type-size-label) * var(--text-scale,1))', lineHeight: 1.2};
  const SLOT = {background: SPEC.slot, borderRadius: 5, padding: '6px 9px', position: 'relative', display: 'flex', alignItems: 'center', gap: 6, minHeight: 28, boxSizing: 'border-box'};
  const edgeSocket = (side, top, inset = 0) => ({position: 'absolute', [side === 'in' ? 'left' : 'right']: -11 - inset, top, transform: 'translateY(-50%)', lineHeight: 0, zIndex: 2});
  function ValueWidget({n, p, value, u}) {
    const [draft, setDraft] = React.useState(null), [focused,setFocused] = React.useState(false), raw = draft ?? value,
      shown = !focused && ['file','folder'].includes(p.dataType) && typeof raw==='string' ? raw.split(/[\\/]/).filter(Boolean).pop() || raw : raw, label = n.title + ' ' + p.key;
    const save = v => { setDraft(v); return u.act(() => api.setNodeParam(n.id, p.key, v)).then(() => setDraft(null)); };
    if (!p.editable) return <span title={String(shown)}>{summary(shown)}</span>;
    if (Array.isArray(raw) && raw.every(item=>typeof item==='string')) return <details className="v48-list-widget nodrag nowheel"><summary>{raw.length} {raw.length===1?'item':'items'}</summary><div>{raw.map((item,index)=><label key={index}><input aria-label={label+' item '+(index+1)} value={item} onChange={event=>save(raw.map((value,i)=>i===index?event.target.value:value))}/><button type="button" className="button-reset" aria-label={'Remove '+label+' item '+(index+1)} onClick={event=>executeAction('projects.controls.activate',{handler:()=>save(raw.filter((_,i)=>i!==index))},event)}>×</button></label>)}<button type="button" className="button-reset" onClick={event=>executeAction('projects.controls.activate',{handler:()=>save([...raw,''])},event)}>Add item</button></div></details>;
    if (p.type === 'json') return <input className="nodrag" aria-label={label} defaultValue={JSON.stringify(raw)} key={JSON.stringify(value)} onChange={event=>event.target.setCustomValidity('')} onBlur={event=>{try{const parsed=JSON.parse(event.target.value);if(p.dataType==='list'&&!Array.isArray(parsed))throw Error('Enter a list.');save(parsed);}catch(error){event.target.setCustomValidity(error.message);event.target.reportValidity();}}}/>;
    if (p.type === 'boolean') return <D.Toggle label={label} checked={!!shown} onCheckedChange={save} />;
    if (['file','folder'].includes(p.dataType)) return <span className="v48-file-widget"><input className="nodrag" aria-label={label} title={String(raw || '')} value={shown || ''} onFocus={()=>setFocused(true)} onBlur={()=>setFocused(false)} onChange={e=>save(e.target.value)}/><button type="button" className="button-reset nodrag" onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.act(()=>api.pickNodeParameter(n.id,p.key,p.dataType))},event)}>Browse</button></span>;
    if (p.options?.length && p.options.length<=4) return <span className="v48-choice-widget" role="group" aria-label={label}>{p.options.map(option=><button type="button" className="button-reset nodrag" key={option} aria-pressed={shown===option} onClick={event=>executeAction('projects.controls.activate',{handler:()=>save(option)},event)}>{option}</button>)}</span>;
    if (p.options?.length) return <select className="nodrag" aria-label={label} value={shown} onChange={e => save(e.target.value)}>{p.options.map(o => <option key={o}>{o}</option>)}</select>;
    const unbounded = ['min', 'max'].includes(p.key) && (shown == null || shown === '');
    return <input className="nodrag" aria-label={label} title={unbounded ? 'Unbounded' : String(shown)} type={p.type === 'number' ? 'number' : 'text'} min={p.min} max={p.max} step={p.step ?? 'any'} placeholder={unbounded ? 'Unbounded' : undefined}
      value={shown == null ? '' : typeof shown === 'object' ? JSON.stringify(shown) : shown} style={{flex: 1, minWidth: 0, width: 0, background: 'transparent', border: 0, color: SPEC.text, font: 'inherit', fontSize: 'calc(13px * var(--text-scale,1))'}}
      onFocus={()=>setFocused(true)} onBlur={()=>setFocused(false)} onChange={e => { if (p.type !== 'number') save(e.target.value); else if (e.target.value === '') save(null); else if (Number.isFinite(e.target.valueAsNumber)) save(e.target.valueAsNumber); }} />;
  }
  function StepHistory({n,u}) {
    const [history,setHistory] = React.useState(null), [error,setError] = React.useState('');
    const load = async () => {try {setHistory(await api.readStepHistory(n.id));setError('');}catch(e){setError(e.message);}};
    return <div className="nodrag" style={{padding:'8px 12px',display:'grid',gap:8}}>
      <div style={{display:'flex',gap:12}}>{n.agentWork.runnable && <button className="button-reset" onClick={event=>executeAction('projects.controls.activate',{handler:async()=>{const result=await u.act(()=>api.runNode(n.id));if(result?.approvalId)u.show('Approve',{id:result.approvalId});}},event)}>Run</button>}
        <button className="button-reset" onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.act(()=>api.forkNode(n.id))},event)}>Fork from here</button></div>
      <details onToggle={e=>{if(e.currentTarget.open)load();}}><summary>History</summary>
        {error && <p role="alert">{error}</p>}{history && <pre data-step-history style={{maxHeight:220,overflow:'auto',whiteSpace:'pre-wrap',fontSize:11}}>{history.calls.length ? JSON.stringify(history.calls,null,2) : 'detail not available'}</pre>}
        {history?.limited && <small>Recent transcript only</small>}</details>
    </div>;
  }
  function ParameterNode({n, socket, selected, u}) {
    // LimitParameter: one typed value, inline stepper and slider, one output socket; the value lives in this node only.
    // A value the owner does not hold (router.json without it) shows "unset", never a default.
    const p = n.parameterSchema?.find(x => x.key === 'value') || {key: 'value', type: 'number', editable: true}, unset = typeof n.params.value !== 'number',
      value = unset ? NaN : n.params.value, max = p.max ?? (unset || Math.abs(value) <= 2 ? 2 : Math.abs(value) * 2), min = p.min ?? Math.min(0, unset ? 0 : value), step = p.step ?? (max <= 2 ? .05 : 1),
      out = n.outputs[0], save = v => Number.isFinite(v) ? u.act(() => api.setNodeParam(n.id, 'value', Math.min(p.max ?? Infinity, Math.max(p.min ?? -Infinity, v)))) : undefined;
    return <div data-ds-node="" data-spec="parameter" className="node-header" style={{...CARD, width: 180, height: 80, outline: selected ? '1.5px solid ' + A.accent : 'none', outlineOffset: 2}}>
      <div data-node-card-title="" style={{position: 'absolute', left: 12, top: 9, right: 40, color: SPEC.typed}}>#  {n.title}</div>
      {!n.pure && <span data-node-pure="false" title="Side effect: waits for Run" style={{position: 'absolute', right: 10, top: 9, color: A.inkSoft}}><window.AHIcon name="clock" size={12} /><span>Effect</span></span>}
      <div style={{position: 'absolute', left: 12, top: 32, right: 12, display: 'flex', alignItems: 'center', gap: 6, color: SPEC.typed}}>
        {unset ? <span data-unset="" style={{flex: 1, color: SPEC.label}} title="Not set in router.json">unset</span> : <ValueWidget n={n} p={{...p, type: 'number', step}} value={value} u={u} />}
        <span>{p.unit || ''}</span>
        <button type="button" className="button-reset nodrag" aria-label={'Decrease ' + n.title} onClick={event => executeAction('projects.controls.activate', {handler: () => save((unset ? min : value) - step)}, event)}>◀</button>
        <button type="button" className="button-reset nodrag" aria-label={'Increase ' + n.title} onClick={event => executeAction('projects.controls.activate', {handler: () => save((unset ? min : value) + step)}, event)}>▶</button>
      </div>
      <input className="nodrag" type="range" aria-label={n.title + ' slider'} min={min} max={max} step={step} value={unset ? min : value}
        onChange={e => save(e.target.valueAsNumber)} style={{position: 'absolute', left: 12, right: 12, top: 58, width: 156, accentColor: SPEC.typed}} />
      {out && <span style={edgeSocket('out', 34)}>{socket(out, 'out')}</span>}
    </div>;
  }
  // Successful output speaks for itself; the footer carries only actionable states.
  function RefusedChip({refusal, onConvert}) {
    return <div data-refused-chip="" role="status" style={{color: A.err, display: 'flex', flexWrap: 'wrap', gap: 4}}>
      {refusal.outType === refusal.inType && refusal.reason ? <span>{refusal.reason}</span> : <><span>Needs a {refusal.outType} → {refusal.inType} converter ·</span>
      <button type="button" className="button-reset nodrag" style={{color: A.err, textDecoration: 'underline'}} onClick={event => executeAction('projects.controls.activate', {handler: onConvert}, event)}>Insert converter</button></>}
    </div>;
  }
  function ResultPreview({value}) {
    if(value == null || value === '' || typeof value==='object' && (!Object.keys(value).length || !Array.isArray(value) && 'approvalId' in value)) return null;
    const picture = typeof value === 'object' && (value.thumbnail || value.thumb || value.image);
    if(typeof picture === 'string' && /^data:image\/(png|jpeg|webp|gif);base64,/.test(picture)) return <img src={picture} alt={value.name || value.title || 'Step output'} style={{width:'100%',maxHeight:148,objectFit:'contain'}}/>;
    if(Array.isArray(value) && value.every(row=>row && typeof row==='object' && !Array.isArray(row))){const keys=[...new Set(value.flatMap(Object.keys))].slice(0,4);return <table><thead><tr>{keys.map(key=><th key={key}>{key}</th>)}</tr></thead><tbody>{value.slice(0,8).map((row,i)=><tr key={i}>{keys.map(key=><td key={key}>{typeof row[key]==='object'?JSON.stringify(row[key]):String(row[key]??'')}</td>)}</tr>)}</tbody></table>;}
    if(Array.isArray(value))return <pre>{value.slice(0,8).map(item=>typeof item==='object'?JSON.stringify(item):String(item)).join('\n')}</pre>;
    if(typeof value==='object'){const rows=Object.entries(value);if(rows.length===1)return <ResultPreview value={rows[0][1]}/>;return <dl>{rows.slice(0,8).map(([key,item])=><React.Fragment key={key}><dt>{key.replace(/_/g,' ')}</dt><dd><ResultPreview value={item}/></dd></React.Fragment>)}</dl>;}
    return <pre>{String(value)}</pre>;
  }
  function SessionCard({n, s, u, selected, socket}) {
    const [open, setOpen] = React.useState({});
    const task = (s.tasks || []).find(row => row.id === n.agentTask);
    const messages = window.UI.homeTaskMessages?.(task) || [];
    const fixed = s.graph.nodes.filter(row => row.fixed && row.id !== n.id);
    const sessionAgents = s.graph.nodes.filter(row=>row.agentWork?.role==='session'&&!row.parent);
    const agent = fixed.find(row => row.type === 'thing.agent');
    const you = fixed.find(row => row.type === 'thing.you');
    const thread = fixed.find(row => row.type === 'thing.workshop');
    const name = agent?.params.agent || task?.agents?.[0] || 'Session';
    const live = (s.liveAgents || []).find(row=>[row.agent,row.name,row.handle].includes(name));
    const panels = [
      ['Agent', 'user', name, agent],
      ['You', 'user', [s.profile.name, s.profile.role].filter(Boolean).join(' · ') || 'Your profile', you],
      ['Parameters', 'settings', task?.rules?.join(' · ') || 'Session parameters', n],
      ['Tools', 'code', (s.hosts || []).filter(h => /connected|running|listening/.test(h.state)).length + ' connected programs'],
      ['Context', 'folder', task?.references?.join(' · ') || task?.scope || 'Task context'],
      ['Thread', 'workshop', messages.length + ' messages · opens beside the canvas', thread]
    ];
    const usedPorts = (owner, side) => (owner?.[side === 'out' ? 'outputs' : 'inputs'] || []).filter(p => s.graph.wires.some(w => side === 'out' ? w.from === owner.id && w.fromPort === p.id && !s.graph.nodes.find(r => r.id === w.to)?.fixed && !sessionAgents.some(row=>row.id===w.to) : w.to === owner.id && w.toPort === p.id && !s.graph.nodes.find(r => r.id === w.from)?.fixed && !sessionAgents.some(row=>row.id===w.from)));
    const panelSocket = (owner, p, side) => socket({...p, id: owner.id === n.id ? p.id : owner.id + ':' + p.id}, side);
    const edit = owner => (owner?.parameterSchema || []).filter(p => p.editable).map(p => <label key={p.key} className="v48-session-param"><span>{p.label || p.key}</span><ValueWidget n={owner} p={p} value={owner.params[p.key]} u={u}/></label>);
    return <div className={'v48-session' + (selected ? ' selected' : '')} data-design="session.node">
      <header className="node-header"><window.UI.Av id={name} size={24}/><div><b>{name}</b><small>{agent?.params.agent ? 'Agent session' : 'Session'}</small></div><span className="v48-state-dot"/></header>
      <div className="v48-session-body"><div><span>Task</span><b>{task?.title || s.graph.name}</b></div><div><span>Runs</span><b>{n.params.model || sessionAgents.find(row=>row.params.model)?.params.model || agent?.params.model || live?.model || 'No active agent'}</b></div>{messages.length > 0 && <p>{messages.at(-1).text}</p>}<button type="button" className="button-reset nodrag" onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.setTaskFace('split')},event)}>Open thread</button></div>
      {(usedPorts(n, 'out').length > 0 || usedPorts(n, 'in').length > 0) && <div className="v48-session-ports">{['in','out'].map(side => usedPorts(n,side).map(p => <span key={side+p.id} data-side={side}>{panelSocket(n,p,side)}{p.id === 'value' ? 'task' : p.name}</span>))}</div>}
      <div className="v48-session-panels">{panels.map(([label, icon, summary, owner]) => <section key={label} className="v48-session-panel">
        <button type="button" data-design={'session.panel.' + label.toLowerCase()} className="button-reset nodrag v48-session-panel-head" aria-expanded={label === 'Thread' ? undefined : !!open[label]} onClick={event=>executeAction('projects.controls.activate',{handler:()=>label === 'Thread' ? u.setTaskFace(u.taskFace === 'split' ? 'canvas' : 'split') : setOpen(v => ({...v,[label]:!v[label]}))},event)}>
          {label==='Agent'?<window.UI.Av id={name} size={22}/>:<span className="v48-panel-tile"><window.AHIcon name={icon} size={12}/></span>}<b>{label}</b><em>{summary}</em><span>{open[label] ? '⌄' : '→'}</span>
        </button>
        {(label==='Agent'?[owner,...sessionAgents]:[owner]).filter(row=>row&&row.id!==n.id).map(row=>['in','out'].map(side=>usedPorts(row,side).map(p=><span className="v48-panel-port" data-side={side} key={row.id+side+p.id}>{panelSocket(row,p,side)}</span>)))}
        {open[label] && label !== 'Thread' && <div className="v48-session-panel-body nodrag nowheel">
          {owner && edit(owner)}
          {label === 'Agent' && sessionAgents.map(row=><button key={row.id} type="button" className="dx-link" onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.show('Node',{id:row.id})},event)}>{row.title} · Properties</button>)}
          {label === 'Agent' && <button type="button" className="dx-link" onClick={() => u.go('settings/Agents')}>Manage agents</button>}
          {label === 'You' && <button type="button" className="dx-link" onClick={() => u.go('settings/Account')}>Settings › You</button>}
          {label === 'Tools' && <>{(s.hosts || []).map(h => <div key={h.id}>{h.name} · {h.state}</div>)}<button type="button" className="dx-link" onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.setLibraryOpen(true)},event)}>As nodes on this Canvas</button><button type="button" className="dx-link" onClick={() => u.go('settings/Connections')}>Connections</button></>}
          {label === 'Context' && <>{task && <><p>{task.scope}</p>{['rules','agents','folders','references'].map(key => <div key={key}><b>{key[0].toUpperCase()+key.slice(1)}</b><p>{(task[key] || []).join(' · ') || 'None'}</p></div>)}</> }<button type="button" className="dx-link" onClick={() => u.show('Task details', {id:task?.id})}>Edit task context</button></>}
          {label === 'Parameters' && <button type="button" className="dx-link" onClick={() => u.show('Node', {id:n.id})}>All parameters</button>}
        </div>}
      </section>)}</div>
      <footer>{(s.approvals || []).some(card=>card.status==='pending' && (card.path===api.getSessionPath() || card.canvasNodes?.some(ref=>ref.path===api.getSessionPath()))) ? 'Waiting for you' : s.graph.nodes.some(row => /running|working/i.test(row.params?.status || row.status)) ? 'Working' : s.graph.nodes.some(row=>/fail|error/i.test(row.status)) ? 'Failed' : 'Idle'}</footer>
    </div>;
  }
  function FlowCard({n, s, u, selected, refusal, onConvert, socket, members, onMember, onDetach, onOpen, menu}) {
    // v48 shows two rows beside a preview, otherwise three; Properties keeps every parameter.
    const [compact, setCompact] = React.useState(true);
    const pinned = n.fixed && n.type !== 'thing.session', task = n.fixed ? (s.tasks || []).find(row=>row.id===n.agentTask) : null, messages = window.UI.homeTaskMessages?.(task) || [];
    const pinnedSummary = n.type==='thing.you' ? [s.profile.name || 'Not signed in',s.profile.role].filter(Boolean).join(' · ')
      : n.type==='thing.workshop' ? messages.length+' messages'+(messages.length ? ' · '+messages.at(-1).text : '')
      : n.params.agent || 'Pick an agent, or message the thread';
    const approval = (s.approvals || []).find(card=>card.approvalKind==='canvas' && (card.nodeId===n.id && card.path===api.getSessionPath() || card.canvasNodes?.some(ref=>ref.nodeId===n.id && ref.path===api.getSessionPath())) && card.status==='pending');
    if (n.fixed && n.type === 'thing.session') return <SessionCard n={n} s={s} u={u} selected={selected} socket={socket}/>;
    if (n.agentStep || n.workflowStart && !n.fixed) return <AgentWorkflowCard n={{...n,role:n.workflowStart?'start':'step',kicker:n.workflowStart?'Start':'Agent · '+(n.params.vendor||'Agent'),status:n.params.status||n.status,by:n.params.display_name||n.params.agent,result:n.params.result||n.params.message_id,
      actions:n.agentWork?<div style={{display:'grid',gap:6}}><span>Goal: {n.params.goal}</span><span>Model: {n.params.model}</span><span>{n.params.detail}</span><button className="button-reset nodrag" onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.act(()=>api.forkNode(n.id))},event)}>Fork from here</button></div>:null,
      openResult:()=>u.openTaskFile(n.agentTask,'workshop'),
      inputs:n.workflowStart?[]:n.inputs.filter(p=>p.id==='task').map(p=>({...p,name:'Step'})),outputs:n.outputs.filter(p=>p.id===(n.workflowStart?'value':'result')).map(p=>({...p,name:'Step'}))}}
      renderPort={(p,i,side)=><div className="canvas-port-row" style={{position:'relative',height:22,display:'flex',alignItems:'center',justifyContent:side==='out'?'flex-end':undefined,padding:'0 12px',fontSize:12}}>{socket(p,side)}Step</div>}
      headerProps={{className:'node-header'}} selected={selected} headerEnd={menu} width={268} />;
    const field = n.column && fieldColumn(n, s.graph);
    if (field) return <FieldNode n={n} field={field} selected={selected} headerProps={{className: 'node-header'}} renderSocket={socket} />;
    const scalarParameter = ['thing.setting', 'param.value'].includes(n.type) && n.outputs.length === 1 && (typeof n.params.value === 'number' || n.params.value === null);
    if (scalarParameter) return <ParameterNode n={n} socket={socket} selected={selected} u={u} />;
    const liveSession=n.fixed && n.type==='thing.session' && (s.liveAgents || []).find(agent=>task?.declarations?.some(row=>row.agent===agent.agent) || agent.task && [task?.title,task?.description].includes(agent.task));
    const [state, stateColor] = n.fixed && n.type==='thing.session' ? [liveSession ? String(liveSession.status || 'Unknown').replace(/^./,c=>c.toUpperCase()) : 'Idle',liveSession && /running|working/i.test(liveSession.status) ? A.accent : A.inkSoft] : nodeState(n, !!refusal), wiresIn = s.graph.wires.filter(w => w.to === n.id),
      sourceOf = port => { const w = wiresIn.find(x => x.toPort === port), a = w && s.graph.nodes.find(x => x.id === w.from); return a && a.title + '.' + (a.outputs.find(p => p.id === w.fromPort)?.name || w.fromPort); },
      slotPorts = new Set(), settingsKeys = new Set(n.settingsKeys || []),
      // Internal ids, hashes and serialized JSON stay in Properties; the face shows human values (CARDPOLISH), first three until expanded.
      shown = (n.parameterSchema || []).filter(p => !n.fixed || !['reference','thread','limit','workspace'].includes(p.key)).filter(p => p.editable || (!HIDDEN_PARAM.test(p.key) && (n.params[p.key] === null || typeof n.params[p.key] !== 'object') && !HIDDEN_VALUE.test(String(n.params[p.key]))))
        .filter(p => !(p.key === 'prompt' && n.inputs.some(x => x.id === 'prompt'))).sort((a,b)=>Number(!!b.userParam)-Number(!!a.userParam)),
      pending = false,
      hasOutput = n.output != null && n.output !== '' && (typeof n.output!=='object' || Object.keys(n.output).length>0 && !('approvalId' in n.output)),
      rowLimit = hasOutput ? 2 : 3,
      params = pending || pinned && compact ? [] : compact ? shown.slice(0, rowLimit) : shown,
      refusedHere = port => refusal && refusal.to.port === port && <RefusedChip refusal={refusal} onConvert={onConvert} />;
    for (const p of params) for (const port of n.inputs.filter(x => x.id === p.key || x.id === 'param:' + p.key)) slotPorts.add(port.id);
    const headerSetting=s.settings.find(row=>row.id==='Appearance.Node header colour');
    const requestedHeader=n.color || (headerSetting?.value!==headerSetting?.default ? headerSetting?.value : '');
    const headerColor=typeof requestedHeader==='string'&&/^#[0-9a-f]{6}$/i.test(requestedHeader)?requestedHeader:undefined;
    const [familyColor,familyIcon] = NODE_FAMILY_STYLE[String(n.category||'').toLowerCase()] || [A.blue,'canvas'];
    const luminance = headerColor && headerColor.slice(1).match(/../g).map(hex => {const channel=parseInt(hex,16)/255;return channel<=0.04045?channel/12.92:((channel+0.055)/1.055)**2.4;}).reduce((sum,channel,index)=>sum+channel*[0.2126,0.7152,0.0722][index],0);
    return <D.Node className="v22g-node" data-pinned-card={pinned || undefined} data-design={!n.fixed ? 'node.' + (n.status==='Running'?'running':n.status==='Done'?'done':/approval/i.test(n.status)?'waiting':/error|fail/i.test(n.status)?'failed':'pending') : undefined} data-spec={n.dataset ? 'dataset' : 'operation'} data-node-state={state.split(' · ')[0]}
      w={n.fixed ? 300 : n.children?.length ? 224 : n.dataset ? LAYOUT.datasetWidth : 300} title={n.title} sub={pinned ? n.type==='thing.you' ? 'Profile · every agent reads it' : n.type==='thing.workshop' ? "This task’s thread" : 'Agent · '+(n.params.agent || 'pick one') : (n.category && n.category!=='Node' ? n.category : n.kind) + ' · ' + (n.pure ? 'Runs by itself' : 'Waits for you')}
      glyph={n.fixed && ['thing.agent','thing.session'].includes(n.type) ? <window.UI.Av id={n.params.agent || task?.agents?.[0] || ''} size={20}/> : <window.AHIcon name={n.icon || (n.type==='thing.you' ? 'user' : n.type==='thing.workshop' ? 'workshop' : familyIcon)} size={12}/>} gc={n.fixed ? A.purple : familyColor}
      selected={selected} headerProps={{className:'node-header','data-custom-header':headerColor?true:undefined,style:{background:headerColor,color:headerColor ? luminance>.179?'#000000':'#ffffff':SPEC.text}}} headerEnd={pinned ? <span className="v22g-pinned-badge">Pinned</span> : menu}
      style={{fontSize:'calc(12px * var(--text-scale,1))',borderRadius:'var(--node-radius,8px)',minHeight:pending?160:undefined}}
      ins={n.inputs.filter(port=>!slotPorts.has(port.id)&&(!pending||port.id===n.inputs[0]?.id||port.id==='param:'+n.inputs[0]?.id||wiresIn.some(w=>w.toPort===port.id)))} outs={n.outputs}
      renderPort={(port,index,side)=><div data-port-row={side} style={{position:'relative',height:22,display:'flex',alignItems:'center',justifyContent:side==='out'?'flex-end':undefined,padding:'0 12px'}}><span style={{position:'absolute',[side==='out'?'right':'left']:-11,top:0}}>{socket(port,side)}</span>{port.name}</div>}
      foot={n.children?.length&&!n.fixed?<span className="spread"><span>{n.children.length} nodes</span><button type="button" data-design="group.open" className="button-reset nodrag" onClick={event=>executeAction('projects.controls.activate',{handler:onOpen},event)}>Open</button></span>:pinned ? <span className="spread"><button type="button" className="button-reset nodrag" aria-expanded={!compact} onClick={event=>executeAction('projects.controls.activate',{handler:()=>setCompact(!compact)},event)}>{compact?'Parameters':'Fewer'}</button>{n.type==='thing.you' ? <button type="button" className="button-reset nodrag" onClick={()=>u.go('settings/Account')}>Settings › You</button> : n.type==='thing.workshop' ? <button type="button" className="button-reset nodrag" onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.setTaskFace('split')},event)}>Open thread</button> : null}</span> : <span className="v48-step-actions"><span title={n.error || state} style={{marginRight:'auto'}}>{state.split(' · ')[0]}{Number.isFinite(n.elapsedMs)?' · '+n.elapsedMs+' ms':''}</span><button type="button" className="button-reset nodrag" onClick={event=>executeAction('projects.controls.activate',{handler:()=>n.agentWork?.role==='step'?u.show('Node',{id:n.id}):u.go('runs')},event)}>History</button>{(!n.agentWork || n.agentWork.runnable) && <button type="button" className="button-reset nodrag" disabled={n.status==='Running'} onClick={event=>executeAction('projects.controls.activate',{handler:async()=>{const result=await u.act(()=>api.runNode(n.id));if(result?.approvalId)u.show('Approve',{id:result.approvalId});}},event)}>Run step</button>}</span>} footc={pinned ? A.inkSoft : stateColor}>

      {members.length > 0 && (n.fixed || !n.children?.length) && <div className="canvas-members">{members.map(m => <button key={m.id} data-group-member={m.id} draggable={m.chip || undefined} className="canvas-member nodrag" title={m.chip ? 'Drag ' + m.title + ' out of the group' : 'Open ' + m.title} onDragStart={event => { if (!m.chip) return; event.stopPropagation(); event.dataTransfer.setData('text/plain', m.id); event.dataTransfer.effectAllowed = 'move'; event.currentTarget.dataset.dragged = '1'; }} onDragEnd={event => { if (!m.chip || !onDetach) return; onDetach(m, event); }} onClick={event => { if (event.currentTarget.dataset.dragged === '1') { event.currentTarget.dataset.dragged = ''; return; } executeAction('projects.controls.activate', {handler: () => onMember(m)}, event); }}><span style={{background: A.purple, color: A.onFill}}>{m.title.slice(0, 1)}</span>{m.title}</button>)}</div>}
      {pinned && compact && <div className="v22g-pinned-summary">{pinnedSummary}</div>}
      <div className="v48-step-body" style={{display: 'grid', gap: 'var(--layout-node-row-gap,4px)', padding: pinned && compact ? 0 : '8px 10px 6px'}}>
        {!n.fixed && !n.children?.length && hasOutput && <div className="v48-step-preview" data-node-result="">{n.output != null && n.output !== '' && (!Array.isArray(n.output) || n.output.length) ? <ResultPreview value={n.output}/> : <span>{n.error || (n.status === 'Running' ? 'Running…' : 'Run to inspect output')}</span>}</div>}
        {pinned && !compact && n.type==='thing.you' && <><b>{s.profile.name || 'Not signed in'}</b><span>{s.profile.role || 'No role set'}</span></>}
        {pinned && !compact && n.type==='thing.workshop' && <span>{task?.rules?.join(' · ') || 'No rules set'}</span>}
        {n.fixed && n.type==='thing.session' && <span>{s.workspaces.find(row=>row.id===n.params.workspace)?.name || 'Sessions folder'}</span>}
        {/* Full-node row (archhub-full-node-controls-native.png): name over its type, then the linked source or an inline control, then a row menu. Real data or empty. */}
        {params.map(p => ({key: 'param:' + p.key, param: p, port: n.inputs.find(x => (x.id === p.key || x.id === 'param:' + p.key) && wiresIn.some(wire=>wire.toPort===x.id)) || n.inputs.find(x => x.id === 'param:' + p.key) || n.inputs.find(x => x.id === p.key)})).map(({key, port, param}) => {
          const ports = param ? n.inputs.filter(x => x.id === param.key || x.id === 'param:' + param.key) : port ? [port] : [];
          const from = ports.map(alias=>sourceOf(alias.id)).filter(Boolean).join(' · '), name = param ? (param.label && param.label !== param.key ? param.label : param.key.replace(/_/g, ' ')) : port.name,
            type = param ? ((['min', 'max', 'step'].includes(param.key) || param.type === 'number' || ['number', 'integer'].includes(param.dataType)) ? 'number' : (param.dataType || (param.options?.length ? 'enum' : param.type === 'boolean' ? 'boolean' : 'string'))) + (param.unit ? ' · ' + param.unit : '') + (settingsKeys.has(param.key) ? ' · From Settings' : '') : typeName(port);
          return <React.Fragment key={key}><div data-port-row={param ? undefined : 'in'} data-parameter={param ? param.key : undefined}
            style={{...SLOT, display: 'grid', gridTemplateColumns: 'minmax(64px,.8fr) minmax(0,1.3fr) 16px', minHeight:30, gap: 6, padding: '2px 0', alignItems: 'center'}}>
            {ports.map(alias=><span key={alias.id} aria-hidden={alias.id!==port.id||undefined} style={{...edgeSocket('in', '50%', 12),opacity:alias.id===port.id?1:0,pointerEvents:alias.id===port.id?undefined:'none'}}>{socket(alias, 'in')}</span>)}
            <span style={{minWidth: 0}}><span style={{display: 'block', fontSize: 'calc(var(--type-size-label) * var(--text-scale,1))', lineHeight: 1.25, overflowWrap: 'anywhere'}} title={param ? param.label || param.key : port.name}>{name}</span>
              <span data-row-type="" style={{display: 'none', color: SPEC.label}}>{type}</span></span>
            <span data-row-value="" style={{display: 'flex', alignItems: 'center', gap: 6, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>
              {from ? <span data-linked-source="" style={{color: SPEC.label}} title={from}>{from}</span>
                : !param ? null : n.params[param.key] === null && !(param.type === 'number' && ['min','max'].includes(param.key)) ? <span data-unset="" style={{color: SPEC.label}}>unset</span> : <ValueWidget n={n} p={param} value={n.params[param.key]} u={u} />}</span>
            <button type="button" className="button-reset nodrag" aria-label={name + ' row actions'} style={{color: SPEC.label, padding: '0 4px'}}
              onClick={event => executeAction('projects.controls.activate', {handler: () => u.show('Port menu', {id: n.id, port: port?.id || 'param:' + param.key, paramKey: param?.key, anchor: {x: event.clientX, y: event.clientY}})}, event)}>⋮</button>
          </div>{ports.map(alias=><React.Fragment key={alias.id}>{refusedHere(alias.id)}</React.Fragment>)}</React.Fragment>;
        })}
        {!pending && !pinned && shown.length > rowLimit && <button type="button" className="button-reset nodrag canvas-card-more" aria-pressed={compact} style={{justifySelf: 'start', color: SPEC.label}} onClick={event => executeAction('projects.controls.activate', {handler: () => setCompact(!compact)}, event)}>{compact ? `+${shown.length - rowLimit} more` : 'Compact'}</button>}
        {n.loop && <div data-node-loop="" style={{color: SPEC.label}} title={'Trigger ' + n.loop.trigger + ' · stops when ' + n.loop.stop + (n.loop.evaluator ? ' · evaluator ' + n.loop.evaluator : '')}>Loop · cap {n.loop.cap} · until {n.loop.stop}</div>}
        {n.dataset && <DatasetEditor n={n} u={u} />}
        {!n.dataset && !n.column && (!n.fixed || n.type==='thing.session') && !n.children?.length && api.addNodeParameter && <div className="flex">{pending&&<button type="button" className="button-reset nodrag" onClick={event=>executeAction('projects.controls.activate',{handler:()=>setCompact(false)},event)}>Parameters</button>}<AddParameter n={n} u={u} /></div>}

        {approval && <button type="button" className="button-reset nodrag" onClick={e=>u.show('Approve',{id:approval.id,anchor:{x:e.clientX,y:e.clientY}})}>Review</button>}
      </div>
    </D.Node>;
  }
  // DESIGNSYS-050 4.9 Inspector (plate archhub-inspector-changed-native.png): Properties of the one selected node; its Inputs and Output, editable.
  function ScriptInspector({n,u}) {
    const action=window.UI.useAction(),ports={source:n.outputs.filter(p=>!p.id.startsWith('param:')),target:n.inputs.filter(p=>!p.id.startsWith('param:')&&!['code','kind','timeout'].includes(p.id))};
    const edit=(side,index,patch)=>action.run(()=>api.setScriptPorts(n.id,{...ports,[side]:ports[side].map((p,i)=>i===index?{id:p.id,type:p.type,...patch}:{id:p.id,type:p.type})},patch.id?{side,from:ports[side][index].id,to:patch.id}:undefined));
    const add=side=>{const base=side==='target'?'abcdefgh'.split(''):['result','out2','out3','out4','out5','out6'],id=base.find(id=>!ports[side].some(p=>p.id===id))||'p'+ports[side].length;return action.run(()=>api.setScriptPorts(n.id,{...ports,[side]:[...ports[side].map(p=>({id:p.id,type:p.type})),{id,type:'text'}]}));};
    return <section className="v22g-script"><window.UI.ActionStatus action={action}/>{[['target','Inputs','addin'],['source','Outputs','addout']].map(([side,label,tag])=><React.Fragment key={side}><b>{label}</b>{ports[side].map((p,i)=><div className="v22g-script-row" key={p.id}><input aria-label={(side==='target'?'Input':'Output')+' name'} defaultValue={p.id} onBlur={e=>{if(e.target.value!==p.id)edit(side,i,{id:e.target.value});}}/><select aria-label={'Type of '+p.id} value={p.type} onChange={e=>edit(side,i,{type:e.target.value})}>{['text','number','file','elements','color','event','any'].map(t=><option key={t}>{t}</option>)}</select><button type="button" aria-label={'Remove '+p.id} disabled={side==='source'&&ports.source.length===1} onClick={event=>executeAction('projects.controls.activate',{handler:()=>action.run(()=>api.setScriptPorts(n.id,{...ports,[side]:ports[side].filter((_,index)=>index!==i)}))},event)}>×</button></div>)}<button type="button" className="dx-link" data-design={'script.'+tag} onClick={event=>executeAction('projects.controls.activate',{handler:()=>add(side)},event)}>+ {side==='target'?'Input':'Output'}</button></React.Fragment>)}
      <b>Runs in</b><div className="flex"><span>Python</span><span aria-disabled="true" title="Use Run in program for the existing host broker">Revit · later</span><span aria-disabled="true" title="Use Run in program for the existing host broker">AutoCAD · later</span></div>
      <label>Code<textarea data-design="script.code" aria-label="Script code" key={n.id+':'+n.params.code} defaultValue={n.params.code} spellCheck={false} rows={7} onBlur={e=>{if(e.target.value!==n.params.code)action.run(()=>api.setNodeParam(n.id,'code',e.target.value));}}/></label>
      <p className="muted">Inputs arrive as arguments. Return a dictionary with one value per output.</p><b>Kind</b><div className="flex" role="group" aria-label="Pure or effect"><button type="button" aria-pressed={n.pure} onClick={event=>executeAction('projects.controls.activate',{handler:()=>action.run(()=>api.setNodeParam(n.id,'kind','pure'))},event)}>Pure</button><button type="button" aria-pressed={!n.pure} onClick={event=>executeAction('projects.controls.activate',{handler:()=>action.run(()=>api.setNodeParam(n.id,'kind','effect'))},event)}>Effect</button></div><p className="muted">{n.pure?'Re-solves on every edit and writes nothing outside the file.':'Waits for Run and stops at Approve every time. Code outside the pure subset is always an Effect.'}</p><button type="button" data-design="script.savetype" onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.show('Save node type',{id:n.id})},event)}>Save as node type</button>
    </section>;
  }
  function NodeInspector({n, s, u, embedded = false, children}) {
    const Tag = embedded ? 'section' : 'aside';
    const sourceOf = port => { const w = s.graph.wires.find(x => x.to === n.id && x.toPort === port), a = w && s.graph.nodes.find(x => x.id === w.from); return a && a.title + ' · ' + (a.outputs.find(p => p.id === w.fromPort)?.name || w.fromPort); };
    const params = (n.parameterSchema || []).filter(p => p.editable && !(n.fixed && n.type==='thing.workshop' && ['thread','limit'].includes(p.key))), [state] = nodeState(n, false), result = n.status === 'Done' ? summary(n.output) : '';
    const headerSetting=s.settings.find(row=>row.id==='Appearance.Node header colour');
    const defaultColor=headerSetting?.value!==headerSetting?.default ? headerSetting?.value : window.getComputedStyle(document.documentElement).getPropertyValue('--color-bg-panel').trim() || A.bgPanel;
    const cap = {fontSize: 'calc(12px * var(--text-scale,1))', color: SPEC.label, margin: '16px 0 6px'};
    return <Tag className={embedded ? "inspector-content" : "pane inspector"} data-node-inspector={n.id} aria-label="Properties" style={{borderLeft: embedded ? 0 : '1px solid ' + A.line, padding: embedded ? 0 : 16, overflow: 'auto'}}>
      {!embedded && <div className="muted" style={{fontSize: 'calc(12px * var(--text-scale,1))'}}>Properties</div>}
      {!embedded && <h2 style={{margin:'4px 0 0'}}>{n.title}</h2>}
      <div style={{color: SPEC.label, fontSize: 'calc(12px * var(--text-scale,1))', marginTop: 2}}>{state} · {n.pure ? 'pure' : 'side effect'}{n.kind ? ' · ' + n.kind : ''}</div>
      {n.type==='script.python'&&<ScriptInspector n={n} u={u}/>}
      {n.agentWork?.role==='step' && <StepHistory n={n} u={u} />}
      <div className="node-presentation" style={{display:'grid',gap:8,marginTop:16}}>
        <label>Label<input aria-label="Node label" key={n.id+':'+n.title} defaultValue={n.title} onBlur={event=>{const title=event.target.value.trim();if(title && title!==n.title)u.act(()=>api.renameNode(n.id,title));else event.target.value=n.title;}} /></label>
        <label>Icon<select aria-label="Node icon" value={n.icon || ''} onChange={event=>u.act(()=>api.setNodePresentation(n.id,{icon:event.target.value}))}><option value="">Default</option>{api.nodeIcons.map(name=><option key={name} value={name}>{name}</option>)}</select></label>
        <label>Colour<span className="node-colour-value"><input type="color" aria-label="Node colour" value={n.color || defaultColor} onChange={event=>u.act(()=>api.setNodePresentation(n.id,{color:event.target.value}))} /><span>{n.color || defaultColor}</span></span></label>
      </div>
      <div style={cap}>Inputs</div>
      {children}
      <div style={{display: 'grid', gap: 6}}>{n.inputs.filter(p => !params.some(q => q.key === p.id || 'param:' + q.key === p.id)).map(p => <div key={p.id} style={SLOT}>
        <span style={{flex: 1, minWidth: 0}}><span style={{display: 'block', color: SPEC.label, fontSize: 'calc(11px * var(--text-scale,1))'}}>{p.name} · {typeName(p)}</span>{sourceOf(p.id) ? <span data-linked-source="">{sourceOf(p.id)}</span> : <span style={{color: SPEC.label}}>Not connected</span>}</span></div>)}
        {params.map(p => <label key={p.key} style={SLOT}><span style={{flex: 1, minWidth: 0}}><span style={{display: 'block', color: SPEC.label, fontSize: 'calc(11px * var(--text-scale,1))'}}>{p.label || p.key.replace(/_/g, ' ')}</span>
          {sourceOf('param:' + p.key) || sourceOf(p.key) ? <span data-linked-source="">{sourceOf('param:' + p.key) || sourceOf(p.key)}</span> : n.params[p.key] === null && !(p.type === 'number' && ['min','max'].includes(p.key)) ? <span style={{color: SPEC.label}}>unset</span> : <ValueWidget n={n} p={p} value={n.params[p.key]} u={u} />}</span></label>)}
        {!n.inputs.length && !params.length && <span style={{color: SPEC.label}}>No inputs</span>}</div>
      <div style={cap}>Output</div>
      {n.outputs.map(p => <div key={p.id} style={{color: SPEC.typed}}>{p.name} · {typeName(p)}</div>)}
      <div style={{color: result ? SPEC.text : SPEC.label, marginTop: 6, overflowWrap: 'anywhere'}}>{result || (n.outputs.length ? 'No output yet' : 'No output')}</div>
    </Tag>;
  }
  // Connection node: the selected wire's own parameters, in the same Inspector. Tokens from design-tokens.json via AH.
  function WireInspector({wire, s, u, onClose, embedded = false}) {
    const Tag = embedded ? 'section' : 'aside';
    const field = {width: '100%', boxSizing: 'border-box', background: A.bgRaised, color: A.ink, border: '1px solid ' + A.line, borderRadius: window.AH.rad.md, padding: '6px 8px', font: 'inherit', fontSize: 'calc(13px * var(--text-scale,1))', lineHeight: 1.35};
    const labelStyle = {color: A.inkMuted, fontSize: 'calc(11px * var(--text-scale,1))', lineHeight: 1.35};
    const a = s.graph.nodes.find(n => n.id === wire.from), b = s.graph.nodes.find(n => n.id === wire.to),
      out = a?.outputs.find(p => p.id === wire.fromPort), into = b?.inputs.find(p => p.id === wire.toPort),
      carried = a?.status === 'Done' ? (a.output && typeof a.output === 'object' && !Array.isArray(a.output) && wire.fromPort in a.output ? a.output[wire.fromPort] : a.output) : undefined,
      listSocket = !!(out?.list || into?.list || out?.type === 'list' || into?.type === 'list'),
      [runLabel] = nodeState(b || {}, !!wire.rejected),
      observed = wire.enabled===false?'Disabled':wire.rejected || runLabel === 'Types do not match' ? 'Rejected' : runLabel === 'Not run' ? 'Not observed' : /^(Updating|Out of date)/.test(runLabel) ? 'Affected' : runLabel === 'Done' ? 'Compatible' : runLabel;
    const shown = (name, choices) => choices.includes(wire[name]) ? wire[name] : choices[0];
    const read = (name, text, note) => <div data-wire-param={name} style={{display: 'grid', gap: 2}}><span style={labelStyle}>{name}</span><div style={field}><span style={{color: A.ink}}>{text}</span>{note && <span style={{color: A.inkMuted}}>{' · ' + note}</span>}</div></div>;
    return <Tag className={embedded ? "inspector-content" : "pane inspector"} style={{borderLeft: embedded ? 0 : '1px solid ' + A.line, padding: embedded ? 0 : 16, overflow: 'auto', minHeight: 0}} aria-label="Wire">
      <div className="spread" style={{position:'sticky',top:0,zIndex:1,background:A.bgRaised}}><h2 style={{margin: 0, fontSize: 'calc(16px * var(--text-scale,1))', fontWeight: 500}}>Connection</h2><Btn variant="controls" sm ghost aria-label="Close wire" onClick={event=>executeAction('projects.controls.activate',{handler:onClose},event)}>×</Btn></div>
      <div data-wire-inspection="" style={{display: 'grid', gap: window.AH.sp.sm, marginTop: window.AH.sp.md}}>
        {read('From', (a?.title || wire.from) + '.' + (out?.name || wire.fromPort), '')}
        {read('To', (b?.title || wire.to) + '.' + (into?.name || wire.toPort), '')}
        <label data-wire-param="Rule" style={{display: 'grid', gap: 2}}><span style={labelStyle}>Rule</span><input aria-label="Rule" key={wire.id+':'+wire.rule} defaultValue={wire.rule || ''} placeholder="None" onBlur={e=>{if(e.target.value!==wire.rule)u.act(()=>api.setWireRule(wire.id,e.target.value));}} style={field} /></label>
        {read('Data', out ? typeName(out) : (wire.type || 'Any'), 'derived')}
        {read('Access', listSocket ? 'List' : 'Item', 'derived')}
        {read('Direction', 'Output to input', 'derived')}
        {(api.wireMenus || []).map(([name, choices]) => <label key={name} data-wire-param={name.slice(0,1).toUpperCase()+name.slice(1)} style={{display: 'grid', gap: 2}}>
          <span style={labelStyle}>{name.slice(0,1).toUpperCase()+name.slice(1)}</span>
          <select aria-label={name.slice(0,1).toUpperCase()+name.slice(1)} value={shown(name, choices)} title={name === 'units' ? 'Saved on the wire. Run does not convert units.' : name === 'route' ? 'Draws the cable. Run does not read it.' : 'Applied when the wire runs.'} onChange={e=>u.act(()=>api.setWireParam(wire.id, name, e.target.value))} style={{...field, cursor: 'pointer'}}>{choices.map(choice => <option key={choice} value={choice}>{choice}</option>)}</select>
        </label>)}
        {read('State', observed, 'observed')}
        {read('Value', carried === undefined ? 'Not run yet' : summary(carried) || 'empty', '')}
        <Btn variant="controls" danger sm onClick={event=>executeAction('projects.ds_screens.DeleteWire.28',{api,u,wire},event)}>Delete wire</Btn>
      </div>
    </Tag>;
  }
  // CANVASXY: xyflow (React Flow 12, MIT, vendor/xyflow.js) owns pan, zoom, drag, marquee and wiring;
  // the cards, sockets, wire colours and every file edit stay the Studio's own.
  const RF = window.ReactFlow, CanvasContext = React.createContext(null);
  // One node component driven by node data; the card grammar inside renderNode is the designer's to replace.
  function FlowNode({id, data, selected}) {
    const c = React.useContext(CanvasContext), box = React.useRef(null), updateInternals = RF.useUpdateNodeInternals();
    // xyflow caches Handle positions; re-measure when the card's rows/sockets change or its size changes (auto-height, field add/hide/reorder).
    // Layout only: nothing here runs a node.
    const n = data.n, handles = [...n.inputs, ...n.outputs].map(p => p.id).join('|') + '#' + (n.parameterSchema || []).map(p => p.key).join('|');
    React.useLayoutEffect(() => {
      const measure = () => updateInternals(id);
      measure();
      const observer = new window.ResizeObserver(measure);
      if (box.current) observer.observe(box.current);
      return () => observer.disconnect();
    }, [id, handles, updateInternals]);
    const design = n.fixed ? ({'thing.session':'pin.session','thing.agent':'pin.agent','thing.you':'pin.you','thing.workshop':'pin.workshop'}[n.type]) : 'node.step';
    const frame=n.frameMembers || !n.fixed && n.children?.length && !n.collapsed;
    return <div ref={box} data-graph-node={id} data-design={frame ? n.frameMembers ? 'frame.box' : 'group.frame' : !n.fixed&&n.children?.length ? 'group.node' : design} data-fixed={n.fixed || undefined} style={{fontSize:'calc('+(frame?13:12)+'px * var(--text-scale,1))'}}><div inert={c.preview || undefined}>{frame ? c.renderFrame(n,selected) : c.renderNode(n, selected)}</div></div>;
  }
  function FlowWire({id, sourceX, sourceY, targetX, targetY, data}) {
    // xyflow anchors at the Handle's outer edge; the spec wire meets the socket centre (Handle is 22 px wide, see SOCKET_STYLE).
    const d = wirePath({x: sourceX - 11, y: sourceY}, {x: targetX + 11, y: targetY}, data.route);
    return <>{data.selected && <path d={d} stroke={A.ink} strokeWidth="8" opacity=".22" fill="none" />}
      <WirePath id={id} state={data.state} route={data.route} d={d} color={data.color} dash={data.inferred?'6 4':undefined} opacity={data.opacity} />
      <path className="react-flow__edge-interaction" d={d} stroke="transparent" strokeWidth="16" fill="none" aria-label={'Inspect wire ' + id} />
    </>;
  }
  const nodeTypes = {archhub: FlowNode}, edgeTypes = {archhub: FlowWire};
  const {Group: CanvasGroup, Panel: CanvasPanel, Separator: CanvasSeparator} = window.ReactResizablePanels;
  const SOCKET_STYLE = {position: 'relative', inset: 'auto', transform: 'none', display: 'inline-grid', placeItems: 'center', width: 22, height: 22,
    minWidth: 0, minHeight: 0, background: 'transparent', border: 0, borderRadius: 0};
  function Canvas({
    active = true,
    preview = null,
    onActivate,
    embedded = false,
    externalInspector = false,
    onInspect,
    onHandoff,
    controlsRef,
    occludedWidth = 0
  }) {
    const live = useData(), s = preview ? {...live, graph: preview, sessionBreadcrumbs: []} : live,
      u = useApp();
    const api = preview ? {getSnapshot:()=>s, refreshProjects:async()=>preview, setSessionViewport:()=>{}} : window.UI.api;
    const zoomRow = s.settings.find(r => r.id === 'Appearance.Default zoom') || s.settings.find(r => r.page === 'Appearance' && (r.label === 'Zoom percentage' || r.key === 'Zoom percentage'))
      || s.settings.find(r => r.id === 'Appearance.Zoom percentage');
    const zoomMin = Number(s.canvasPolicy?.zoom_min ?? .1), zoomMax = Number(s.canvasPolicy?.zoom_max ?? 4);
    const [selected, setSelected] = React.useState(u.selectedNodeId && s.graph.nodes.some(n => n.id === u.selectedNodeId) ? [u.selectedNodeId] : []),
      [wireId, setWireId] = React.useState(null),
      [selectedWires, setSelectedWires] = React.useState([]),
      [parent, setParent] = React.useState(null),
      [viewport, setViewport] = React.useState({zoom: Math.max(zoomMin, Math.min(zoomMax, (zoomRow?.value || 100) / 100)), pan: embedded ? {x:32,y:120} : {x:0,y:0}}),
      [rejected, setRejected] = React.useState(null),
      [layout, setLayout] = React.useState({scope: null, positions: {}}),
      [flowNodes, setFlowNodes] = React.useState([]),
      [more, setMore] = React.useState(false);
    const area = React.useRef(),
      view = React.useRef(viewport),
      held = React.useRef(null),
      zoomWrites = React.useRef(Promise.resolve()),
      pendingZoomWrites = React.useRef(0);
    const userViewport = React.useRef(false);
    const canvasTouched = React.useRef(false);
    React.useLayoutEffect(() => { canvasTouched.current = false; }, [s.graph.scopeKey, embedded]);
    const stopAutoFrame = () => { canvasTouched.current = true; };
    const paneBox = React.useRef(null), libraryPanel = React.useRef(null), inspectionPanel = React.useRef(null);
    const [paneWidth, setPaneWidth] = React.useState(window.innerWidth - 64), [libraryRail, setLibraryRail] = React.useState(false), [inspectionRail, setInspectionRail] = React.useState(false), [peek, setPeek] = React.useState('');
    const {zoom, pan} = viewport;
    const [requestState, setRequestState] = React.useState('waiting');
    const [requestError, setRequestError] = React.useState('');
    React.useLayoutEffect(() => {
      const observer = new window.ResizeObserver(entries => setPaneWidth(entries[0].contentRect.width));
      if (paneBox.current) observer.observe(paneBox.current);
      return () => observer.disconnect();
    }, [requestState]);
    const zoomSetting = zoomRow?.value;
    const appliedZoomSetting = React.useRef(zoomSetting);
    const zoomSaveDelay = Number(s.canvasPolicy?.viewport_commit_debounce_ms ?? 140);
    const persistView = ({x,y,zoom}) => {
      userViewport.current = true;
      api.setSessionViewport?.({x,y,zoom});
    };
    const updateView = (next, persist = true) => {
      view.current = next;
      setViewport(next);
      if (persist) persistView({x:next.pan.x,y:next.pan.y,zoom:next.zoom});
    };
    React.useEffect(() => {
      const saved = s.graph.viewport;
      userViewport.current = s.graph.viewportSaved === true;
      if (userViewport.current) updateView({zoom:saved.zoom,pan:{x:saved.x,y:saved.y}}, false);
    }, [s.graph.scopeKey, embedded, s.graph.viewportSaved, s.graph.viewport?.x, s.graph.viewport?.y, s.graph.viewport?.zoom]);
    const zoomAt = (value, client = null) => {
      const bounds = area.current?.getBoundingClientRect();
      if (!bounds) return;
      const old = view.current, next = Math.max(zoomMin, Math.min(zoomMax, value));
      const x = client ? client.x - bounds.left : bounds.width / 2,
        y = client ? client.y - bounds.top : bounds.height / 2;
      updateView({zoom: next, pan: {x: x - (x - old.pan.x) * next / old.zoom, y: y - (y - old.pan.y) * next / old.zoom}});
    };
    React.useEffect(() => {
      if (embedded || !active || Object.is(appliedZoomSetting.current,zoomSetting)) return;
      if (pendingZoomWrites.current) { appliedZoomSetting.current=zoomSetting; return; }
      if (!Number.isFinite(Number(zoomSetting))) return;
      appliedZoomSetting.current=zoomSetting;
      zoomAt(Number(zoomSetting) / 100);
    }, [zoomSetting, requestState, active]);
    React.useEffect(() => {
      const percent = Math.round(zoom * 100);
      if (embedded || !active) return;
      if (!['loaded','empty'].includes(requestState) || zoomSetting === undefined || percent === Number(zoomSetting)) return;
      const timer = setTimeout(() => {
        pendingZoomWrites.current++;
        zoomWrites.current = zoomWrites.current.then(() => u.act(() => api.setSetting(zoomRow.id, percent)))
          .then(() => { appliedZoomSetting.current=api.getSnapshot().settings.find(row=>row.id===zoomRow.id)?.value; })
          .finally(() => { pendingZoomWrites.current--; });
        // u.act reports failures; a refused save must not poison the next gesture.
        zoomWrites.current = zoomWrites.current.catch(() => {});
      }, zoomSaveDelay);
      return () => clearTimeout(timer);
    }, [zoom, zoomSetting, zoomRow?.id, zoomSaveDelay, requestState, active]);
    const reload = () => {
      setRequestState('waiting');
      return api.refreshProjects({userCanvas:true}).then(() => {
        setRequestState(api.getSnapshot().graph.nodes.length ? 'loaded' : 'empty');
      }).catch(error => {
        setRequestError(error.message);
        setRequestState('error');
      });
    };
    React.useEffect(() => { if(active && requestState==='waiting'){reload();} }, [active]);
    React.useEffect(() => {
      if (requestState === 'loaded' || requestState === 'empty')
        setRequestState(s.graph.nodes.length ? 'loaded' : 'empty');
    }, [s.graph.nodes.length]);
    const hasSession = s.graph.nodes.some(n=>n.fixed&&n.type==='thing.session');
    const foldedOwner = n => n && (n.fixed || hasSession&&n.agentWork?.role==='session'&&(!n.agentStep||s.graph.nodes.some(row=>row.agentWork?.owner===n.id))&&!n.parent);
    // A node whose group is not a node at this level is drawn here, never dropped.
    const atLevel = n => {
      if(foldedOwner(n)&&n.type!=='thing.session'||s.graph.system||n.application)return false;
      let owner=n.parent||null;const seen=new Set([n.id]);
      while(owner&&owner!==parent){if(seen.has(owner))return false;seen.add(owner);const group=s.graph.nodes.find(x=>x.id===owner);if(!group)return parent===null;if(group.collapsed!==false)return false;owner=group.parent||null;}
      return owner===parent;
    };
    const scope = s.graph.id + ':' + (parent || ''), sourceNodes = s.graph.nodes.filter(atLevel);
    React.useLayoutEffect(() => {
      if (!active || preview || parent || requestState !== 'loaded' || s.graph.canvasLayout === 'v48' || canvasTouched.current) return;
      const frame = window.requestAnimationFrame(() => u.act(() => api.arrangeGraph(true)));
      return () => window.cancelAnimationFrame(frame);
    }, [active, requestState, scope, s.graph.canvasLayout]);
    const visible = sourceNodes.map(n => ({...n, ...(layout.scope === scope ? layout.positions[n.id] : {})})),
      node = s.graph.nodes.find(n => n.id === selected.at(-1)),
      wire = s.graph.wires.find(w => w.id === wireId),
      inspected = !wire && selected.length === 1 && s.graph.nodes.find(n => n.id === selected[0]);
    React.useLayoutEffect(() => {
      onInspect?.({nodeId: inspected?.id || null, wireId: wire?.id || null});
    }, [inspected?.id, wire?.id]);
    React.useLayoutEffect(() => {
      if (!active || preview) return;
      const place = event => {
        if (!area.current || !['loaded','empty'].includes(requestState)) return;
        const {zoom:z,pan:p} = view.current, rect = area.current.getBoundingClientRect(),
          left = (8-p.x)/z, top = (8-p.y)/z, right = (rect.width-8-p.x)/z, bottom = (rect.height-8-p.y)/z;
        const boxes = [...area.current.querySelectorAll('[data-graph-node]')].map(el => {
          const r = el.getBoundingClientRect();
          return {id:el.dataset.graphNode,x:(r.left-rect.left-p.x)/z,y:(r.top-rect.top-p.y)/z,w:r.width/z,h:r.height/z};
        });
        const overlays = [...area.current.closest('[data-screen="canvas"]').querySelectorAll('[data-canvas-overlay]')].map(el=>{
          const r=el.getBoundingClientRect();return {x:(r.left-rect.left-p.x)/z,y:(r.top-rect.top-p.y)/z,w:r.width/z,h:r.height/z};
        });
        const made = boxes.find(b=>b.id===event.detail.nodeId), w = made?.w || 224,
          h = made?.h || Math.max(160,...boxes.map(b=>b.h)),
          unrendered = api.getSnapshot().graph.nodes.filter(atLevel).filter(n=>!boxes.some(b=>b.id===n.id))
            .map(n=>({x:n.x,y:n.y,w:224,h})),
          occupied = [...boxes.filter(b=>b.id!==event.detail.nodeId),...unrendered,...overlays,...event.detail.reserved],
          picked = boxes.find(b=>b.id===selected.at(-1)), center = {x:(left+right-w)/2,y:(top+bottom-h)/2};
        const clear = c=>!occupied.some(b=>c.x<b.x+b.w+16 && c.x+w+16>b.x && c.y<b.y+b.h+16 && c.y+h+16>b.y);
        const free = c=>c.x>=left && c.y>=top && c.x+w<=right && c.y+h<=bottom && clear(c);
        let point = [made,picked && {x:picked.x+Math.max(280,picked.w+36),y:picked.y},center].find(c=>c&&free(c));
        // Search obstacle edges lazily; keep the STUDIOFIX 280px adjacent offset.
        const xs = new Set([left,center.x,right-w]), ys = new Set([top,center.y,bottom-h]);
        for (const b of occupied) { xs.add(b.x+b.w+16); xs.add(b.x-w-16); ys.add(b.y+b.h+16); ys.add(b.y-h-16); }
        if (!point) outer: for (const y of ys) for (const x of xs) if (free({x,y})) { point={x,y};break outer; }
        if (!point) {
          // A full view must still add; obstacle edges contain the nearest free point.
          let distance = Infinity;
          for (const y of ys) for (const x of xs) {
            const d=(x-center.x)**2+(y-center.y)**2;
            if (d<distance && clear({x,y})) { point={x,y};distance=d; }
          }
        }
        const offscreen = [point.x<left && 'left',point.x+w>right && 'right',point.y<top && 'above',point.y+h>bottom && 'below'].filter(Boolean).join(' and ');
        event.detail.point = {...point,w,h,offscreen};
      };
      window.addEventListener('archhub:canvas-insertion',place);
      return () => window.removeEventListener('archhub:canvas-insertion',place);
    }, [active, requestState, selected, scope, parent, s.graph.nodes]);
    React.useLayoutEffect(() => {
      if (!active || requestState !== 'loaded' || !area.current) return;
      const positions = {}, points = new Map(), prior = layout.scope === scope ? layout.positions : {},
        minX = Math.min(...sourceNodes.map(n => n.x), 0), rowWidth = Math.max(760, Math.ceil(Math.sqrt(sourceNodes.length)) * 310);
      for (const n of sourceNodes) {
        const point = JSON.stringify([n.x,n.y]);points.set(point,(points.get(point)||0)+1);
      }
      const boxes = sourceNodes.map(n => {
        const previous = prior[n.id], unchanged = previous?.sourceX === n.x && previous?.sourceY === n.y,
          el = area.current.querySelector('[data-graph-node="' + n.id + '"]');
        return {id:n.id,x:unchanged ? previous.x : n.x,y:unchanged ? previous.y : n.y,sourceX:n.x,sourceY:n.y,
          w:(el?.offsetWidth || el?.getBoundingClientRect().width / view.current.zoom || 224) + (isGroup(n) ? 10 : 0),
          h:(el?.offsetHeight || el?.getBoundingClientRect().height / view.current.zoom || 160) + (isGroup(n) ? 10 : 0),
          stacked:points.get(JSON.stringify([n.x,n.y])) > 1};
      }), occupied = boxes.filter(box => !box.stacked);
      for (const box of boxes) {
        // CANVASLOOK display repair only for coincident defaults; distinct saved positions stay authoritative.
        if (box.stacked) {
          let hit;
          while ((hit = occupied.find(b => box.x < b.x+b.w+36 && box.x+box.w+36 > b.x && box.y < b.y+b.h+48 && box.y+box.h+48 > b.y))) {
            box.x = hit.x+hit.w+36;
            if (box.x+box.w > minX+rowWidth) { box.x=minX;box.y=Math.max(box.y,hit.y+hit.h)+64; }
          }
          occupied.push(box);
        }
        positions[box.id] = box;
      }
      setLayout(old => old.scope === scope && JSON.stringify(old.positions) === JSON.stringify(positions) ? old : {scope,positions});
    }, [requestState, scope, s.graph.nodes, active]);
    React.useLayoutEffect(() => {
      if (!active) return;
      const listener = e => {
        if (preview) return;
        if(e.defaultPrevented)return;
        if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === 's') {
          if (e.defaultPrevented) return;
          e.preventDefault();
          u.act(() => e.shiftKey ? api.saveSessionAs() : api.saveSession());
          return;
        }
        if (e.target.closest?.('input,textarea,select,[contenteditable="true"],[role="textbox"]')) return;
        if (area.current?.contains(e.target)) {
          if (e.key === '+' || e.key === '=') { e.preventDefault(); zoomAt(view.current.zoom * 1.2); }
          if (e.key === '-') { e.preventDefault(); zoomAt(view.current.zoom / 1.2); }
          if (e.key === '0') { e.preventDefault(); e.ctrlKey ? fit() : zoomAt(1); }
          if (e.shiftKey && (e.code === 'Digit1' || e.key === '1')) { e.preventDefault(); fit(); }
        }
        if (e.ctrlKey && e.key.toLowerCase() === 'g') {
          e.preventDefault();
          e.altKey ? frame() : e.shiftKey && node?.children?.length ? u.act(()=>api.ungroupNode(node.id)) : group();
        }
        const editable=selected.filter(id=>!s.graph.nodes.find(n=>n.id===id)?.fixed);
        const center={x:(area.current?.clientWidth/2-view.current.pan.x)/view.current.zoom,y:(area.current?.clientHeight/2-view.current.pan.y)/view.current.zoom,...(parent?{parent}:{})};
        if(e.ctrlKey&&['c','x','v','d'].includes(e.key.toLowerCase())){e.preventDefault();u.act(()=>e.key.toLowerCase()==='c'?api.copyNodes(editable):e.key.toLowerCase()==='x'?api.cutNodes(editable):e.key.toLowerCase()==='d'?api.duplicateNodes(editable):api.pasteNodes(center));}
        if(e.ctrlKey&&e.key.toLowerCase()==='f'){e.preventDefault();u.show('Find node');}
        if(e.ctrlKey&&e.key.toLowerCase()==='l'){e.preventDefault();u.act(()=>api.arrangeGraph());}
        if(e.shiftKey&&!e.ctrlKey&&!e.altKey&&e.key.toLowerCase()==='a'){e.preventDefault();u.show('Add node',{point:center});}
        if(!e.ctrlKey&&!e.altKey&&e.key.toLowerCase()==='n'){e.preventDefault();u.show('Note',{point:center});}
        if(e.key==='F2'&&node&&!node.fixed){e.preventDefault();u.show('Rename node',{id:node.id,text:node.title});}
        if(!e.ctrlKey&&!e.altKey&&e.key.toLowerCase()==='r'&&editable.length){e.preventDefault();u.act(()=>api.runSelection(editable));}
        if (e.key === 'Delete' && (selected.length || selectedWires.length)) {
          e.preventDefault();
          remove();
        }
        if (e.key === 'Enter' && node && isGroup(node)) openNode(node);
        if (e.key === 'Escape') {
          setRejected(null);
          setSelected([]);
          setSelectedWires([]);
          setWireId(null);
          if (parent) setParent(null);
          else if ((s.sessionBreadcrumbs||[]).length) u.act(()=>api.leaveSession());
        }
        if (e.ctrlKey && e.key.toLowerCase() === 'a') {
          e.preventDefault();
          setSelected(visible.map(n => n.id));
        }
      };
      window.addEventListener('keydown', listener);
      return () => window.removeEventListener('keydown', listener);
    });
    React.useLayoutEffect(() => {if(!preview&&active)u.setSelectedNodeId(selected.at(-1) || null);}, [selected.join(','),active]);
    React.useLayoutEffect(()=>{if(!preview&&active&&u.selectedNodeId&&!selected.includes(u.selectedNodeId)&&s.graph.nodes.some(n=>n.id===u.selectedNodeId))setSelected([u.selectedNodeId]);},[u.selectedNodeId,active]);
    React.useLayoutEffect(()=>{
      const nodes=new Set(s.graph.nodes.map(n=>n.id)),wires=new Set(s.graph.wires.map(w=>w.id));
      setSelected(old=>old.some(id=>!nodes.has(id))?old.filter(id=>nodes.has(id)):old);
      setSelectedWires(old=>old.some(id=>!wires.has(id))?old.filter(id=>wires.has(id)):old);
      if(wireId&&!wires.has(wireId))setWireId(null);
    },[s.graph.nodes.map(n=>n.id).join(','),s.graph.wires.map(w=>w.id).join(',')]);
    // The file is the source; xyflow keeps only what it measured (sizes) and an in-flight drag.
    React.useEffect(() => {
      setFlowNodes(old => {
        const prior = new Map(old.map(f => [f.id, f]));
        return visible.map(n => {
          const f = prior.get(n.id);
          // ComfyUI/Grasshopper: a card moves by its title bar; its fields and buttons keep the pointer.
          return {id: n.id, type: 'archhub', data: {n}, zIndex:n.frameMembers||!n.fixed&&n.children?.length&&!n.collapsed?-1:0, dragHandle: '.node-header', selected: selected.includes(n.id), measured: f?.measured, dragging: f?.dragging,
            position: f?.dragging ? f.position : held.current?.[n.id] || {x: n.x, y: n.y}};
        });
      });
    }, [s.graph, layout, parent, selected.join(','), requestState, u.canvasTabs?.collapsed]);
    const onNodesChange = changes => {
      setFlowNodes(nodes => RF.applyNodeChanges(changes.filter(c => c.type !== 'remove'), nodes));
      const picks = changes.filter(c => c.type === 'select');
      if (picks.length) setSelected(old => {
        const next = new Set(old);
        for (const c of picks) c.selected ? next.add(c.id) : next.delete(c.id);
        const ids = [...next];
        return ids.join(',') === old.join(',') ? old : ids;
      });
    };
    const onNodeDragStop = (event, dragged, all) => {
      const point = event.changedTouches?.[0] || event;
      const hits = point && document.elementsFromPoint ? document.elementsFromPoint(point.clientX, point.clientY) : [];
      const host = [...hits].map(el => el.closest && el.closest('[data-graph-node]')).find(el => el && el.dataset.graphNode !== dragged.id);
      const group = host && s.graph.nodes.find(n => n.id === host.dataset.graphNode);
      const node = s.graph.nodes.find(n => n.id === dragged.id);
      const grouped = group && group.id !== node?.id && (group.type === 'thing.workshop' || group.kind === 'Group' || group.kind === 'Workshop' || (group.children || []).length || (group.members || []).length);
      if (node?.type === 'thing.agent' && grouped) {
        held.current = null;
        u.act(() => api.attachMember(group.id, node.id));
        return;
      }
      const positions = Object.fromEntries((all?.length ? all : [dragged]).map(f => [f.id, {x: f.position.x, y: f.position.y}]));
      held.current = positions;
      Promise.resolve(u.act(() => api.moveNodes(positions))).finally(() => { if (held.current === positions) held.current = null; });
    };
    const group = async () => {
      const g = await u.act(() => api.groupNodes(selected.filter(id=>!s.graph.nodes.find(n=>n.id===id)?.fixed)));
      if (g) setSelected([g.id]);
    };
    const remove = () => u.confirm(`Delete ${selected.length + selectedWires.length} selected item(s)?`, async () => {
      await api.deleteSelection(selected, selectedWires);
      setSelected([]);
      setSelectedWires([]);
      setWireId(null);
    });
    const ownerSocket = (id, port) => {const owner=s.graph.nodes.find(n=>n.fixed&&n.type!=='thing.session'&&port?.startsWith(n.id+':'));return owner ? {id:owner.id,port:port.slice(owner.id.length+1)} : {id,port};};
    const connect = async (out, input) => {
      out=ownerSocket(out.id,out.port);input=ownerSocket(input.id,input.port);
      const word = p => (TYPE_NAME[p.type] || p.type || 'any').toLowerCase();
      if (out.id === input.id) return;
      const outputPort = s.graph.nodes.find(n=>n.id===out.id)?.outputs.find(p=>p.id===out.port),
        inputPort = s.graph.nodes.find(n=>n.id===input.id)?.inputs.find(p=>p.id===input.port);
      if (!outputPort || !inputPort || outputPort.connectable === false || inputPort.connectable === false || outputPort.read_only || inputPort.read_only) return;
      if (!api.socketCompatible(outputPort, inputPort)) {
        // Spec d9c0d514: an invalid drop draws the wire red at the drop and offers the converter on the target socket; no modal, nothing written.
        setRejected({from:out, to:input, outType:word(outputPort), inType:word(inputPort)}); return;
      }
      const choices = outputPort.connect_choices;
      if (Array.isArray(choices) && !choices.some(p=>p.id===input.id && p.interface===input.port)) {
        setRejected({from:out, to:input, outType:word(outputPort), inType:word(inputPort), reason:'These sockets do not share an admitted contract.'}); return;
      }
      const result = await u.act(() => api.connectSockets({
        from: out.id,
        to: input.id,
        fromPort: out.port,
        toPort: input.port
      }));
      // A refusal from the owner lands in the same inline state as a client-side type check: red wire, converter on the socket.
      if (result && !result.ok) setRejected({from:out, to:input, outType:word(outputPort), inType:word(inputPort), reason:result.error || result.reason || ''});
    };
    const insertConverter = async () => {
      const r = rejected, a = r && s.graph.nodes.find(n => n.id === r.from.id), b = r && s.graph.nodes.find(n => n.id === r.to.id);
      if (!a || !b) return;
      setRejected(null);
      await u.act(async () => {
        const c = await api.addNode('data.convert', {x: (a.x + b.x) / 2, y: Math.max(a.y, b.y) + 160});
        await api.setNodeParam(c.id, 'target_type', r.inType === 'number' ? 'number' : 'text');
        await api.connectSockets({from: r.from.id, fromPort: r.from.port, to: c.id, toPort: 'in'});
        return api.connectSockets({from: c.id, fromPort: 'out', to: r.to.id, toPort: r.to.port});
      });
    };
    const toFlow = e => {
      const r = area.current.getBoundingClientRect(), point = e.changedTouches?.[0] || e;
      return {x: (point.clientX - r.left - view.current.pan.x) / view.current.zoom, y: (point.clientY - r.top - view.current.pan.y) / view.current.zoom};
    };
    const frame = async()=>{const made=await u.act(()=>api.groupNodes(selected.filter(id=>!s.graph.nodes.find(n=>n.id===id)?.fixed),true));if(made)setSelected([made.id]);};
    const canvasActions = point=>({point:{...point,...(parent?{parent}:{})},group,frame,fit,select:ids=>setSelected(ids),selectAll:()=>setSelected(visible.map(n=>n.id)),inspectWire:id=>{setWireId(id);setSelected([]);}});
    const renderFrame = (n,isSelected)=>{
      const members=(n.frameMembers||n.children).map(id=>visible.find(row=>row.id===id)||s.graph.nodes.find(row=>row.id===id)).filter(Boolean);
      const width=Math.max(241,...members.map(child=>child.x+(area.current?.querySelector('[data-graph-node="'+child.id+'"]')?.offsetWidth||241)-n.x))+24;
      const height=Math.max(100,...members.map(child=>child.y+(area.current?.querySelector('[data-graph-node="'+child.id+'"]')?.offsetHeight||160)-n.y))+24;
      return <div className="v22g-group-frame" data-frame={n.frameMembers?true:undefined} style={{width,height,borderColor:n.color||undefined,outline:isSelected?'2px solid var(--color-accent)':undefined}}><header className="node-header"><b data-design="group.title">{n.title}</b><span>{members.length} nodes</span>{!n.frameMembers&&<button type="button" className="button-reset nodrag" data-design="group.collapse" aria-label="Collapse group" onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.act(()=>api.setGroupCollapsed(n.id,true))},event)}>−</button>}<button type="button" className="button-reset canvas-node-menu nodrag" aria-label={n.title+' menu'} onClick={()=>u.show(n.frameMembers?'Frame menu':'Group menu',{id:n.id,selected,open:()=>openNode(n),canvas:canvasActions({x:n.x,y:n.y})})}>⋯</button></header></div>;
    };
    const socket = (n, p, side) => {
      const locked = !!preview || p.connectable === false || p.read_only;
      return <RF.Handle type={side === 'out' ? 'source' : 'target'} position={side === 'out' ? RF.Position.Right : RF.Position.Left} id={p.id} isConnectable={!locked}
        data-port-key={`${n.id}:${side}:${p.id}`} className="socket" data-port-type={p.type} data-port-list={p.list || undefined}
        title={`${p.name} · ${p.type}${p.list ? " list" : ""}${p.unit ? " · "+p.unit : ""}`} aria-disabled={locked || undefined} aria-label={`${n.title} ${side} ${p.name}`}
        style={SOCKET_STYLE} onContextMenu={e => {
          e.preventDefault();
          e.stopPropagation();
          u.show('Port menu', {...ownerSocket(n.id,p.id), anchor: {x: e.clientX, y: e.clientY}});
        }}><span data-socket-dot="" data-wired={side === 'out' || s.graph.wires.some(w => w.to === n.id && w.toPort === p.id) || undefined} /></RF.Handle>;
    };
    const renderNode = (n, isSelected) => {
      const placed = new Set(s.graph.nodes.map(row => row.id));
      for (const row of s.graph.nodes) if (row.type === 'thing.agent' && row.params?.agent) placed.add(row.params.agent);
      const childMembers = (n.children || []).map(id => s.graph.nodes.find(x => x.id === id) || n.members?.find(m => m.id === id)).filter(Boolean);
      const chips = (n.members || []).filter(m => m && m.id && !placed.has(m.id) && !(n.children || []).includes(m.id)).map(m => ({...m, title: m.title || m.id, chip: true}));
      if (n.type === 'thing.workshop') {
        for (const agent of s.liveAgents || []) {
          const id = agent.session || agent.handle;
          const agentId = agent.agent || id;
          if (!id || placed.has(id) || placed.has(agentId) || chips.some(m => m.id === id || m.agent === agentId) || childMembers.some(m => m.id === id)) continue;
          chips.push({id, title: agent.name || agentId, agent: agentId, chip: true});
        }
      }
      const members = [...childMembers, ...chips];
      if(n.type==='note'&&!n.children?.length&&!n.frameMembers)return <div className="v22g-note node-header" style={{background:n.color||undefined}} onDoubleClick={()=>u.show('Note',{id:n.id,text:n.params.text||''})}>{n.params.text||n.title}</div>;
      return <FlowCard onOpen={()=>openNode(n)} n={n} s={s} u={u} selected={isSelected} refusal={rejected?.to.id === n.id ? rejected : null} onConvert={insertConverter} members={members} socket={(p, side = 'in') => socket(n, p, side)}
        onMember={m=>{if (s.graph.nodes.some(row => row.id === m.id)) {setParent(n.id);setSelected([m.id]);} else {setParent(null);u.act(async()=>{await api.selectGraph(n.id);setSelected([m.id]);});}}}
        onDetach={(m, event) => { const under = document.elementFromPoint(event.clientX, event.clientY); if (under && under.closest && under.closest('[data-graph-node="' + n.id + '"]')) return; u.act(() => api.detachMember(n.id, {id: m.id, title: m.title, agent: m.agent || m.id}, toFlow(event))); }}
        menu={<button className="button-reset canvas-node-menu nodrag" aria-label={n.title+' menu'} title={n.title+' actions'} onClick={event=>executeAction('projects.ds_screens.NodeMenu.16',{n,openNode,setSelected,u,canvas:canvasActions({x:n.x,y:n.y})},event)}>⋯</button>} />;
    };
    const stale = (s.solveStale || []).filter(id => s.graph.nodes.some(n => n.id === id)).length;
    const shownIds = new Set(visible.map(n => n.id));
    const sessionNode = visible.find(n => n.fixed && n.type === 'thing.session');
    const edges = (rejected ? [...s.graph.wires,{id:'rejected',rejected:true,from:rejected.from.id,fromPort:rejected.from.port,to:rejected.to.id,toPort:rejected.to.port}] : s.graph.wires)
      .filter(w => !(foldedOwner(s.graph.nodes.find(n=>n.id===w.from)) && foldedOwner(s.graph.nodes.find(n=>n.id===w.to))))
      .map(w => { const projected={...w}; if(sessionNode)for(const side of ['from','to']){const owner=s.graph.nodes.find(n=>n.id===w[side]);if(foldedOwner(owner)&&owner.id!==sessionNode.id){projected[side]=sessionNode.id;projected[side+'Port']=owner.id+':'+w[side+'Port'];}} return projected; })
      .filter(w => shownIds.has(w.from) && shownIds.has(w.to)).map(w => {
        const color = w.rejected ? A.err : wireColor(w, s.graph.nodes), shown = s.graph.wireVisibility, portVisibility = s.graph.nodes.find(n=>n.id===w.from)?.portVisibility?.[w.fromPort];
        return {id: w.id, type: 'archhub', source: w.from, target: w.to, sourceHandle: w.fromPort, targetHandle: w.toPort, selectable: !w.rejected, focusable: !w.rejected, selected: selectedWires.includes(w.id),
          data: {color, inferred:w.inferred||w.enabled===false, route: w.route, state: w.rejected ? 'rejected' : color === A.warn ? 'affected' : 'compatible', selected: (wireId === w.id || selectedWires.includes(w.id)) && shown !== 'Hidden',
            opacity: w.rejected ? 1 : shown==='Hidden'||portVisibility==='Hidden' ? 0 : shown==='Faint'||portVisibility==='Faint'||w.enabled===false ? .2 : .9}};
      });
    const fit = (persist = true) => {
      if (!visible.length || !area.current) return;
      const w = area.current.clientWidth, h = area.current.clientHeight;
      const boxes = [...area.current.querySelectorAll('[data-graph-node]')].map(el => {
        const n = visible.find(n => n.id === el.dataset.graphNode);
        return n && {x: n.x, y: n.y, w: el.offsetWidth || n.w || 224, h: el.offsetHeight || n.h || 160};
      }).filter(Boolean);
      if (!boxes.length) return;
      const fitted = fitCanvasViewport(boxes, w, h, zoomMin, zoomMax, embedded ? 1 : Number(s.canvasPolicy?.zoom_fit_max ?? 1.25));
      if (fitted) updateView(fitted, persist);
    };
    React.useEffect(() => {
      if (!active || preview) return undefined;
      window.UI.requestCanvasFit = fit;
      const currentViewport = () => ({x:view.current.pan.x,y:view.current.pan.y,zoom:view.current.zoom});
      window.UI.requestCanvasViewport = currentViewport;
      return () => {
        if (window.UI.requestCanvasFit === fit) window.UI.requestCanvasFit = null;
        if (window.UI.requestCanvasViewport === currentViewport) window.UI.requestCanvasViewport = null;
      };
    });
    React.useLayoutEffect(() => {
      if (!active || !visible.length || !area.current || requestState!=='loaded' || layout.scope!==scope) return undefined;
      const frame = () => {
        if (userViewport.current || canvasTouched.current) return;
        const boxes=[...area.current.querySelectorAll('[data-graph-node]')].map(element=>{
          const node=visible.find(node=>node.id===element.dataset.graphNode);
          return node && {node,x:node.x,y:node.y,w:element.offsetWidth,h:element.offsetHeight};
        }).filter(Boolean);
        if (boxes.length!==visible.length || boxes.some(box=>!box.w||!box.h)) return;
        const left=peek==='library'?248:0,right=peek==='inspector'?380:occludedWidth;
        const width=area.current.clientWidth-left-right,height=area.current.clientHeight;
        if (width<=48 || height<=144) return;
        // Opening follows pane/node sizing only until input; touching a node does not save the viewport.
        const session=boxes.find(box=>box.node.type==='thing.session');
        const x=session?session.x:Math.min(...boxes.map(box=>box.x)),y=Math.min(...boxes.map(box=>box.y));
        updateView({zoom:1,pan:{x:left+52-x,y:124-y}},false);
      };
      const observer=new window.ResizeObserver(frame);
      observer.observe(area.current);
      for (const element of area.current.querySelectorAll('[data-graph-node]')) observer.observe(element);
      const tick=window.requestAnimationFrame(frame);
      return () => {observer.disconnect();window.cancelAnimationFrame(tick);};
    }, [active,requestState,scope,layout,flowNodes.length,occludedWidth,peek]);
    const openNode = n => {
      if (n.params?.session_file) { setParent(null);setSelected([]);u.act(() => api.enterSession(n.id));return; }
      if (n.kind.toLowerCase().includes('meeting')) u.go('meetings');else if (n.kind === 'Watch program') u.act(() => api.windowAction('hide'));else if (n.kind === 'Present') u.go('present');else if (['Community', 'Community group', 'Marketplace listing', 'Project charge'].includes(n.kind)) u.go('community');else if (n.kind === 'Interface studio' || n.kind === 'UI element') u.go('interface');else if (n.kind.startsWith('TBP ')) u.go('model-review');else if (n.kind === 'Theme') u.go('settings/Appearance');else if (n.kind === 'Workflow link') {
        if (n.params.targetGraph) u.act(() => api.selectGraph(n.params.targetGraph));else u.show('Workflows');
      } else if (n.kind === 'Agent') u.show('Agent', {
        id: n.params.provider
      });else if (n.kind === 'Research') u.go('xray');else if (n.kind === 'History') u.go('receipts');else if (['Remember', 'Recall'].includes(n.kind)) u.go('brain');else if (['Social media', 'Read video', 'Read mail', 'Read file', 'Tutorial', 'Digest'].includes(n.kind)) u.go('social');else if (n.kind === 'X-RAY') u.go('xray');else if (['Account access', 'Billing & usage', 'Office invitations'].includes(n.kind)) u.go('access');else if (n.kind === 'Model routing') u.go('routing');else if (n.kind === 'Workshop') u.go('workshop');else if (n.kind === 'BABOOM') u.go('baboom');else if (n.kind === 'Watcher') u.go('watcher');else if (isGroup(n)) {
        if (n.children.some(id => s.graph.nodes.some(row => row.id === id))) setParent(n.id);
        else { setParent(null); u.act(() => api.selectGraph(n.id)); }
        setSelected([]);
      } else u.show('Node', {
        id: n.id
      });
    };
    React.useImperativeHandle(controlsRef, () => ({
      clearSelection: () => { setSelected([]); setSelectedWires([]); setWireId(null); },
      addNode: () => u.setLibraryOpen(true),
      run: () => executeAction('projects.ds_screens.Run.15', {api, u}),
      connections: () => { setSelected([]); setWireId(s.graph.wires[0]?.id || null); u.setToast(s.graph.wires.length ? 'Select a connection to inspect its declared types.' : 'This workflow has no connections.'); },
      fit: () => fit(),
      more: () => setMore(value => !value),
      arrange: () => u.act(() => api.arrangeGraph())
    }));
    const stateCounts=new Map();
    for(const node of visible){const state=nodeState(node,false)[0].split(' · ')[0],label=state==='Done'?'complete':state.toLowerCase();stateCounts.set(label,(stateCounts.get(label)||0)+1);}
    React.useLayoutEffect(() => {
      const frame = window.requestAnimationFrame(() => {
        for (const [panel, narrow] of [[libraryPanel, paneWidth < 480], [inspectionPanel, paneWidth < 1436]]) {
          if(narrow) panel.current?.collapse(); else panel.current?.expand();
        }
      });
      return () => window.cancelAnimationFrame(frame);
    }, [paneWidth < 480, paneWidth < 1436, u.libraryOpen, Boolean(inspected || wire)]);
    const actionsMenu = <> {more && <div role="menu" aria-label="Canvas actions" data-canvas-more="" onKeyDown={e => { if (e.key === 'Escape') setMore(false); }} style={{position:'absolute',right:0,top:8,display:'grid',minWidth:200,maxHeight:'calc(100% - 16px)',overflow:'auto',padding:6,gap:2,
          background:A.bgPanel,border:'1px solid '+A.lineSoft,borderRadius:6,zIndex:20}}><div aria-label="Workflow status" style={{padding:'6px 8px',color:A.inkSoft,fontSize:11}}>{[...stateCounts].map(([label,count])=>count+' '+label).join(' · ')}</div>{[
            ['Add node · Ctrl K', () => executeAction("projects.ds_screens.AddANodeCtrlK.24", {u})], ['New', () => u.act(() => api.newSession())], ['Open…', () => u.act(() => api.openSession())], ['Save · Ctrl S', () => u.act(() => api.saveSession())],
            ['Save as…', () => u.act(() => api.saveSessionAs())], ['Save as skill…', () => u.show('Save skill')], ['Add automation', () => u.act(() => api.addAutomation())], ['Workspaces · ' + s.workspaces.length, () => u.show('Workspaces')],
            ['Detach session (copy)', () => u.act(() => api.detachSession(selected[0])), selected.length!==1||!s.graph.nodes.find(n=>n.id===selected[0])?.params.session_file],
            ...(embedded ? [['Thread', () => u.setTaskFace(u.taskFace==='split'?'canvas':'split')]] : []),
            ...(embedded && onHandoff ? [['Handoff map',onHandoff]] : []),
            [(u.libraryOpen ? 'Hide' : 'Show') + ' Library', () => u.setLibraryOpen(v => !v)], ['Group · Ctrl G', group, selected.length < 2],
            ['Undo · Ctrl Z', () => u.act(api.undo)], ['Redo · Ctrl Shift Z', () => u.act(api.redo)], ['Arrange', () => u.act(api.arrangeGraph)],
            ['Wires: ' + (s.graph.wireVisibility || 'Visible') + ' → ' + ({Visible: 'Faint', Faint: 'Hidden', Hidden: 'Visible'})[s.graph.wireVisibility || 'Visible'],
              () => u.act(() => api.setWireVisibility(({Visible: 'Faint', Faint: 'Hidden', Hidden: 'Visible'})[s.graph.wireVisibility || 'Visible']))],
          ].map(([label, run, disabled]) => <button key={label} role="menuitem" type="button" className="button-reset listbutton" disabled={disabled} style={{textAlign:'left',padding:'6px 8px'}}
            onClick={event => executeAction('projects.controls.activate', {handler: () => { setMore(false); return run(); }}, event)}>{label}</button>)}</div>} </>;
    const body = <div ref={paneBox} data-screen="canvas" style={{
      display: 'grid',
      gridTemplateRows: 'minmax(0,1fr)',
      position: 'relative',
      minHeight: 0,
      height: embedded ? '100%' : undefined,
      '--canvas-bg': 'var(--color-bg-canvas)',
      '--canvas-panel': 'var(--color-bg-panel)',
      '--canvas-soft': 'var(--color-bg-soft)',
      '--canvas-hover': 'var(--color-bg-hover)',
      '--canvas-line': 'var(--color-line)',
      '--canvas-line-soft': 'var(--color-line-soft)',
      '--canvas-ink': 'var(--color-ink)',
      '--canvas-muted': 'var(--color-ink-soft)',
      '--canvas-accent': 'var(--color-accent)',
      '--canvas-accent-dim': 'var(--color-accent-dim)'
    }}>
  {/* Spec d9c0d514 top bar: name · Unsaved, + Add node, ⋯, Run. Everything else lives in ⋯; saving is autosave plus Ctrl+S. */}
  {!embedded && <div data-canvas-overlay="" data-canvas-topbar="" className="spread" style={{
        position:'absolute',top:12,left:u.libraryOpen ? 264 : 16,right:16 + (wire || inspected ? LAYOUT.inspectorWidth : 0),zIndex:12,
        minWidth:0,padding: '6px 12px',borderRadius:6,border:'1px solid '+A.lineSoft,
        background: A.bgPanel, fontSize: 'calc(13px * var(--text-scale,1))'
      }}><div className="flex" style={{minWidth:0}}><button className="button-reset" title={s.graph.name} aria-label="Workflows" style={{minWidth:0,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}} onClick={event => executeAction("projects.ds_screens.Graphs.7", {u}, event)}>{s.graph.name} · {s.sessionDirty === false ? 'Saved' : 'Unsaved'}</button>
        {(s.sessionBreadcrumbs||[]).length>0 && <button type="button" className="dx-quiet" aria-label="Parent session" onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.act(()=>api.leaveSession())},event)}>{s.sessionBreadcrumbs.map(row=>row.title).join(' / ')} / {s.graph.name} · ← Parent</button>}
        {parent && <Btn variant="controls" sm ghost onClick={event => executeAction("projects.ds_screens.Parent.6", {parent,s,setParent,setSelected}, event)}>← Parent</Btn>}
        {stale > 0 && <span data-solve-status="" style={{color: A.warn}}>{stale} out of date · Run</span>}</div>
      <div className="flex" style={{position:'relative',flexShrink:0}}> <Btn variant="controls" sm ghost aria-label="More canvas actions" aria-expanded={more} onClick={event => executeAction('projects.controls.activate', {handler: () => setMore(!more)}, event)}>⋯</Btn>
        <Btn variant="controls" p sm onClick={event => executeAction("projects.ds_screens.Run.15", {api,u}, event)}>▶ Run</Btn>
</div></div>}
  {actionsMenu}
  <CanvasGroup className="canvas-panes" orientation="horizontal">
    {u.libraryOpen && <><CanvasPanel id="canvas-library" panelRef={libraryPanel} collapsible collapsedSize={48} minSize={200} maxSize={360} defaultSize={248} groupResizeBehavior="preserve-pixel-size" onResize={size=>setLibraryRail(size.inPixels<=49)}>
      {libraryRail ? <button type="button" className="canvas-pane-rail" aria-label="Open Library" onClick={event=>executeAction("projects.controls.activate",{handler:()=>setPeek(peek==='library'?'':'library')},event)}>Library</button> : <window.UI.LibraryShelf onClose={()=>u.setLibraryOpen(false)} />}
    </CanvasPanel><CanvasSeparator className="pane-splitter" aria-label="Resize Library" /></>}
    <CanvasPanel id="canvas-work" minSize={240}>
   <div ref={area} className={'node-canvas' + (visible.some(n => n.status === 'Running') ? ' running-wires' : '')} tabIndex={0} aria-label="Workflow canvas" style={{position:'relative',minHeight:0,'--xy-selection-background-color':A.accent+'16','--xy-selection-border':'1px solid '+A.accent,'--xy-background-color':'transparent'}}
        onPointerDownCapture={stopAutoFrame} onWheelCapture={stopAutoFrame} onDragStartCapture={stopAutoFrame}
        onKeyDownCapture={e=>{stopAutoFrame();if(e.key==='Escape'&&!parent&&(s.sessionBreadcrumbs||[]).length&&!e.target.closest?.('input,textarea,select,[contenteditable="true"]')){e.preventDefault();e.stopPropagation();u.act(()=>api.leaveSession());}}}
        title="Drag to select · Shift adds · Middle or Space-drag to pan · Wheel to zoom · Double-click to fit"
        onDoubleClick={e => { if (e.target.classList?.contains('react-flow__pane')) fit(); }}
        onDragOver={e => { stopAutoFrame(); e.preventDefault(); }} onDrop={e => {
          e.preventDefault();
          if(preview)return;
          if(e.dataTransfer.files?.length){u.act(()=>api.importSession(e.dataTransfer.files[0]));return;}
          const session=e.dataTransfer.getData('session');
          const task=e.dataTransfer.getData('task');
          const path=session||(s.tasks||[]).find(t=>t.id===task)?.sessionPath;
          if(path){u.act(()=>api.insertSession(path,toFlow(e)));return;}
          const name = e.dataTransfer.getData('node');
          if (name) u.act(() => api.addNode(name, toFlow(e)));
        }} onContextMenu={e => {
          e.preventDefault();
          if(preview)return;
          u.show('Canvas menu', {
            selected,
            group,
            remove,
            canvas:canvasActions(toFlow(e))
          });
        }}>
    <CanvasContext.Provider value={{renderNode, renderFrame, openNode, preview:!!preview}}>
     <RF.ReactFlow nodes={flowNodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} nodesDraggable={!preview} nodesConnectable={!preview}
       viewport={{x: pan.x, y: pan.y, zoom}} onMove={(event,v) => {if(event instanceof window.Event) updateView({zoom:v.zoom,pan:{x:v.x,y:v.y}},false);}}
       onMoveEnd={(event, v) => { if (event instanceof window.Event) persistView(v); }} minZoom={zoomMin} maxZoom={zoomMax}
       onNodesChange={onNodesChange} onNodeClick={(event,node)=>preview ? onActivate?.() : onInspect?.({nodeId:node.id,wireId:null})} onNodeDragStop={onNodeDragStop} onNodeDoubleClick={(e, f) => preview ? onActivate?.() : openNode(f.data.n)}
       onNodeContextMenu={(event,node)=>{event.preventDefault();event.stopPropagation();if(preview)return;const next=selected.includes(node.id)?selected:[node.id];setSelected(next);u.show(next.length>1?'Selection menu':node.data.n.frameMembers?'Frame menu':node.data.n.children?.length&&!node.data.n.fixed?'Group menu':'Node menu',{id:node.id,selected:next,open:()=>openNode(node.data.n),canvas:canvasActions(toFlow(event)),anchor:{x:event.clientX,y:event.clientY}});}}
       onEdgeContextMenu={(event,edge)=>{event.preventDefault();event.stopPropagation();if(preview||edge.id==='rejected')return;setWireId(edge.id);setSelected([]);u.show('Wire menu',{wireId:edge.id,canvas:canvasActions(toFlow(event)),anchor:{x:event.clientX,y:event.clientY}});}}
       onEdgesChange={changes => setSelectedWires(old => {const next=new Set(old);for(const c of changes)if(c.type==='select'&&c.id!=='rejected')c.selected?next.add(c.id):next.delete(c.id);return [...next];})}
       onConnect={c => connect({id: c.source, port: c.sourceHandle}, {id: c.target, port: c.targetHandle})}
       onConnectEnd={(e, state) => {
         if(preview)return;
         // A wire dropped on empty canvas offers the nodes that can take it (spec Compatible nodes).
         if (!state || state.isValid || state.toHandle || !state.fromHandle || e.target.closest?.('.react-flow__node')) return;
         u.show('Compatible nodes', {endpoint: {...ownerSocket(state.fromNode.id,state.fromHandle.id), side: state.fromHandle.type === 'source' ? 'out' : 'in'}, position: toFlow(e)});
       }}
       onEdgeClick={(e, edge) => { if (edge.id !== 'rejected') { setWireId(edge.id); if(!e.shiftKey&&!e.ctrlKey)setSelected([]); onInspect?.({nodeId:null,wireId:edge.id}); } }}
       onPaneClick={() => { if(preview){onActivate?.();return;} setSelected([]); setWireId(null); setSelectedWires([]); setRejected(null); }}
       selectionOnDrag panOnDrag={[1]} panActivationKeyCode="Space" multiSelectionKeyCode={['Shift','Control','Meta']} selectionKeyCode={null} deleteKeyCode={null}
       zoomOnDoubleClick={false} connectionLineStyle={{stroke: A.cyan, strokeWidth: 2}} proOptions={{hideAttribution: true}} />
    </CanvasContext.Provider>
    {embedded && <div className="v48-canvas-title" data-design="canvas.title"><b>{s.graph.name}</b><span>{visible.filter(n=>!n.fixed&&n.status==='Done').length} of {visible.filter(n=>!n.fixed).length} steps · {visible.some(n=>/approval|waiting/i.test(n.status))?'Needs you':visible.some(n=>n.status==='Running')?'Working':visible.some(n=>/fail|error/i.test(n.status))?'Failed':'Idle'}</span></div>}
    {visible.some(n=>!n.fixed && n.x*zoom+pan.x>(area.current?.clientWidth||paneWidth)-32) && <button type="button" className="v48-more-steps" data-design="canvas.more" onClick={event=>executeAction('projects.controls.activate',{handler:()=>{const next=visible.filter(n=>!n.fixed&&n.x*zoom+pan.x>(area.current?.clientWidth||paneWidth)-32).sort((a,b)=>a.x-b.x)[0];updateView({zoom,pan:{x:40-next.x*zoom,y:pan.y}});}},event)}>{visible.filter(n=>!n.fixed&&n.x*zoom+pan.x>(area.current?.clientWidth||paneWidth)-32).length} more steps →</button>}
    <div data-canvas-overlay="" className="canvas-toolbar">{embedded&&(s.sessionBreadcrumbs||[]).length>0&&<button type="button" className="dx-quiet" aria-label="Parent session" onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.act(()=>api.leaveSession())},event)}>{s.sessionBreadcrumbs.map(row=>row.title).join(' / ')} / {s.graph.name} · ← Parent</button>}{parent && <button type="button" data-design="group.back" className="dx-quiet" onClick={event=>executeAction("projects.ds_screens.Parent.6",{parent,s,setParent,setSelected},event)}>← {s.graph.nodes.find(node=>node.id===parent)?.title || 'Parent'}</button>}<Btn variant="controls" sm ghost aria-label="Zoom out" onClick={event => executeAction("projects.ds_screens.ZoomOut.20", {zoomAt,view}, event)}>−</Btn><button className="button-reset" onClick={event => executeAction("projects.ds_screens.ResetZoom.21", {zoomAt}, event)} title="Reset zoom">{Math.round(zoom * 100)}%</button><Btn variant="controls" sm ghost aria-label="Zoom in" onClick={event => executeAction("projects.ds_screens.ZoomIn.22", {zoomAt,view}, event)}>+</Btn><button type="button" data-design="canvas.fit" className="dx-quiet" onClick={event => executeAction("projects.ds_screens.Fit.23", {fit}, event)}>Fit</button></div>

   </div>
   </CanvasPanel>
   {!externalInspector && (inspected || wire) && <><CanvasSeparator className="pane-splitter" aria-label="Resize Inspector" /><CanvasPanel id="canvas-inspection" panelRef={inspectionPanel} collapsible collapsedSize={48} minSize={280} maxSize={480} defaultSize={320} groupResizeBehavior="preserve-pixel-size" onResize={size=>setInspectionRail(size.inPixels<=49)}>
     {inspectionRail ? <button type="button" className="canvas-pane-rail" aria-label="Open Inspector" onClick={event=>executeAction("projects.controls.activate",{handler:()=>setPeek(peek==='inspector'?'':'inspector')},event)}>Inspector</button> : inspected ? <NodeInspector n={inspected} s={s} u={u} /> : <WireInspector wire={wire} s={s} u={u} onClose={()=>setWireId(null)} />}
   </CanvasPanel></>}
  </CanvasGroup>
  {peek==='library'&&u.libraryOpen&&<div className="canvas-pane-peek" data-side="library"><window.UI.LibraryShelf onClose={()=>setPeek('')} /></div>}
  {peek==='inspector'&&!externalInspector&&(inspected||wire)&&<div className="canvas-pane-peek" data-side="inspector"><button type="button" className="dx-quiet" aria-label="Close Inspector" onClick={event=>executeAction("projects.controls.activate",{handler:()=>setPeek('')},event)}>×</button>{inspected?<NodeInspector n={inspected} s={s} u={u}/>:<WireInspector wire={wire} s={s} u={u} onClose={()=>setPeek('')} />}</div>}

 </div>;
    return <>
      {requestState === 'waiting' && <div role="status">Loading your workflow…</div>}
      {requestState === 'error' && <div role="alert">{requestError}<Btn variant="controls" onClick={event => executeAction('projects.controls.activate', {handler:reload}, event)}>Retry loading workflow</Btn></div>}
      {requestState === 'empty' && <>{body}</>}
      {requestState === 'loaded' && <>{body}</>}
    </>;
  }
  function SystemGraph() {
    const s = useData(), u = useApp(), world=React.useRef(), [paths,setPaths]=React.useState([]), [load,setLoad] = React.useState('waiting'), [error,setError] = React.useState(''), [attempt,setAttempt]=React.useState(0);
    const [system,setSystem]=React.useState({nodes:[],wires:[]});
    React.useEffect(()=>{
      let active=true;
      setLoad('waiting');
      api.readSystemGraph().then(graph=>{if(active){setSystem(graph);setLoad(graph.nodes.some(n=>n.application)?'loaded':'empty');}})
        .catch(e=>{if(active){setError(e.message);setLoad('error');}});
      return ()=>{active=false;};
    },[attempt,s.systemRevision]);
    const nodes = system.nodes.filter(n=>n.application), groups = [...new Set(nodes.map(n=>n.frame||n.category||'System'))];
    React.useLayoutEffect(()=>{
      const measure=()=>setPaths(measureWires(world.current,system.wires));
      measure();
      const observer=new window.ResizeObserver(measure);if(world.current)observer.observe(world.current);
      return ()=>observer.disconnect();
    },[s.revision,load,system]);
    return <div data-screen="system" className="system-workflow scroll" style={{minHeight:0,padding:24,overflow:'auto'}}>
      <div className="spread"><h2>System graph</h2><Chip>{nodes.length} nodes</Chip></div>
      {load==='waiting' && <p role="status">Loading the system graph…</p>}
      {load==='error' && <p role="alert">{error}<Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>setAttempt(n=>n+1)},event)}>Retry loading system graph</Btn></p>}
      {load==='empty' && <p>No system graph is available.</p>}
      {load==='loaded' && <div ref={world} style={{position:'relative'}}><svg data-system-wires="" width="100%" height="100%" style={{position:'absolute',inset:0,overflow:'visible',pointerEvents:'none'}}><GraphWires paths={paths} nodes={nodes} /></svg>
      {groups.map(group=><section key={group} data-system-group={group} style={{marginTop:24}}><h3 style={{marginBottom:12}}>{group}</h3><div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(224px,1fr))',gap:28,alignItems:'start'}}>
        {nodes.filter(n=>(n.frame||n.category||'System')===group).map(n=><div key={n.id} data-graph-node={n.id} style={{position:'relative',zIndex:1}}>
          <NodeRenderer n={n} catalogue={s.catalogue} headerProps={{className:'node-header'}}
            headerEnd={<Btn sm ghost onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.show('Node',{id:n.id})},event)}>Open</Btn>}
            renderPort={(p,i,side)=><div className="canvas-port-row" style={{position:'relative',height:22,display:'flex',alignItems:'center',justifyContent:side==='out'?'flex-end':undefined,padding:'0 12px',fontSize: 'calc(12px * var(--text-scale,1))'}}><span data-port-key={`${n.id}:${side}:${p.id}`} style={{position:'absolute',[side==='in'?'left':'right']:-6}}><D.Socket t={p.type} list={p.list} /></span>{p.name}{p.unit ? ' · '+p.unit : ''}</div>} />
        </div>)}
      </div></section>)}</div>}
    </div>;
  }
  window.UI.RunModeChip = RunModeChip;
  window.UI.Canvas = Canvas;
  window.UI.ResultPreview = ResultPreview;
  window.UI.AddField = AddField;
  window.UI.NodeInspector = NodeInspector;
  window.UI.WireInspector = WireInspector;
  window.UI.fitCanvasViewport = fitCanvasViewport;
  window.UI.SystemGraph = SystemGraph;

  function AgentsCanvas() {
    const s=useData(), u=useApp(), dialog=React.useRef();
    const [load,setLoad]=React.useState('waiting'),[error,setError]=React.useState(''),[attempt,setAttempt]=React.useState(0),[transcript,setTranscript]=React.useState(null);
    React.useEffect(()=>{
      let active=true;setLoad('waiting');
      api.readAgentsGraph().then(value=>{if(active){setLoad(value.sessions.length?'loaded':'empty');}})
        .catch(e=>{if(active){setError(e.message);setLoad('error');}});
      return()=>{active=false;};
    },[attempt]);
    const sessions=s.agentGraph?.sessions||[], tasks=s.agentGraph?.tasks||[];
    const openTranscript=async n=>{
      setTranscript({id:n.id,name:n.name,status:'waiting'});
      try{const data=await api.readAgentTranscript(n.id);setTranscript({id:n.id,name:n.name,...data,status:data.messages.length?'loaded':'empty'});}
      catch(e){setTranscript({id:n.id,name:n.name,status:'error',error:e.message});}
    };
    React.useEffect(()=>{const node=dialog.current;if(transcript&&!node?.open)node?.showModal();return()=>{if(node?.open)node.close();};},[!!transcript]);
    return <main data-screen="agents" className="scroll" style={{padding:24,overflow:'auto'}}>
      <h2>Agents</h2><p className="muted">Task sessions · open one workflow at a time</p>
      {load==='waiting' && <p role="status">Loading sessions…</p>}
      {load==='error' && <p role="alert">{error} <Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>setAttempt(n=>n+1)},event)}>Retry</Btn></p>}
      {(load==='loaded'||load==='empty')&&!sessions.length && <p>No agent sessions are running.</p>}
      <div aria-label="Task sessions">{tasks.map(task=><div key={task.id} data-agent-task={task.id} className="listbutton" tabIndex={0}
        draggable={!!task.path} onDragStart={e=>e.dataTransfer.setData('session',task.path||'')}
        onDoubleClick={()=>u.openTaskFile(task.id,'canvas')} onKeyDown={e=>{if(e.key==='Enter')u.openTaskFile(task.id,'canvas');}}>
        <b>{task.title}</b><span className="muted"> · {task.status} · {task.steps} steps</span>
        {!task.path&&<span>No workflow file</span>}
        <Btn sm ghost onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.openTaskFile(task.id,'canvas')},event)}>Open session</Btn>
      </div>)}</div>
      <div aria-label="Agents working">{sessions.map(n=><div key={n.id} data-agent-session={n.id} className="listbutton">
        <b>{n.name}</b><span> · {n.status==='blocked'?'Waiting for you':n.status} · {n.taskTitle||'No task'}</span>
        {n.task&&<Btn sm ghost onClick={event=>executeAction('projects.controls.activate',{handler:()=>u.openTaskFile(n.task,'canvas')},event)}>Open session</Btn>}
        <Btn sm ghost onClick={event=>executeAction('projects.controls.activate',{handler:()=>n.task?u.openTaskFile(n.task,'workshop'):u.go('workshop')},event)}>Open thread</Btn>
        {n.hasTranscript&&<Btn sm ghost onClick={event=>executeAction('projects.controls.activate',{handler:()=>openTranscript(n)},event)}>Open transcript</Btn>}
      </div>)}</div>
      {transcript && <dialog ref={dialog} aria-label="Agent transcript" onCancel={()=>setTranscript(null)} style={{color:A.ink,background:A.bgPanel,border:'1px solid '+A.line,borderRadius:8,padding:24,width:'min(720px,85vw)',maxHeight:'80vh',overflow:'auto'}}>
        <header className="spread"><h2>{transcript.name} transcript</h2><Btn sm ghost onClick={event=>executeAction('projects.controls.activate',{handler:()=>setTranscript(null)},event)}>Close transcript</Btn></header>
        {transcript.status==='waiting' && <p role="status">Reading transcript…</p>}
        {transcript.status==='error' && <p role="alert">{transcript.error} <Btn sm onClick={event=>executeAction('projects.controls.activate',{handler:()=>openTranscript(transcript)},event)}>Retry transcript</Btn></p>}
        {transcript.status==='empty' && <p>No text turns recorded.</p>}
        {transcript.status==='loaded' && <>{transcript.limited&&<p className="muted">Recent transcript only. Earlier turns remain in the native session.</p>}{transcript.messages.map((m,i)=><article key={i} style={{marginTop:16}}><b>{m.role==='user'?'You':'Agent'}</b><p style={{whiteSpace:'pre-wrap'}}>{m.text}</p></article>)}</>}
      </dialog>}
    </main>;
  }
  window.UI.AgentsCanvas=AgentsCanvas;

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
  const handler = () => u.show('Workflows');
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
            if (t?.approvalId) {
              const card=api.getSnapshot().approvals.find(row=>row.id===t.approvalId),box=card?.nodeId && document.querySelector('[data-graph-node="'+window.CSS.escape(card.nodeId)+'"]')?.getBoundingClientRect();
              u.show('Approve',{id:t.approvalId,...(box?{anchor:{x:box.right+12,y:box.top}}:{})});
            } else if (t && !api.getSessionDocument?.()?.properties?.taskContext?.task) {
              u.show('Run', {id:t.id});
            }
          };
  return handler ? Reflect.apply(handler, undefined, [event]) : undefined;
}
function projectsdsscreensjsxNodeMenu16({n,openNode,setSelected,u,canvas}, event) {
  const handler = () => {
                  setSelected([n.id]);
                  u.show('Node menu', {
                    id: n.id,
                    open: () => openNode(n), canvas, selected: [n.id]
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
  "projects.ds_screens.DeleteWire.28": "projectsdsscreensjsxDeleteWire28",
  "projects.ds_screens.Settings.30": "projectsdsscreensjsxSettings30",
  "projects.ds_screens.OpenParameters.31": "projectsdsscreensjsxOpenParameters31",
  "projects.ds_screens.Open.32": "projectsdsscreensjsxOpen32"
};
window.registerActions(PROJECT_ACTIONS, {projectsdsscreensjsxNavigateHome5,projectsdsscreensjsxParent6,projectsdsscreensjsxGraphs7,projectsdsscreensjsxWorkspaces8,projectsdsscreensjsxToggleLibrary9,projectsdsscreensjsxGroup10,projectsdsscreensjsxUndo11,projectsdsscreensjsxRedo12,projectsdsscreensjsxArrange13,projectsdsscreensjsxSaveSkill14,projectsdsscreensjsxRun15,projectsdsscreensjsxNodeMenu16,projectsdsscreensjsxZoomOut20,projectsdsscreensjsxResetZoom21,projectsdsscreensjsxZoomIn22,projectsdsscreensjsxFit23,projectsdsscreensjsxAddANodeCtrlK24,projectsdsscreensjsxDeleteWire28,projectsdsscreensjsxSettings30,projectsdsscreensjsxOpenParameters31,projectsdsscreensjsxOpen32});
})();
