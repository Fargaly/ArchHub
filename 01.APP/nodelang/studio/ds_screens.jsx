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
  function measureWires(world, wires) {
    if (!world) return [];
    const bounds=world.getBoundingClientRect(), sockets=new Map([...world.querySelectorAll('[data-port-key]')].map(el=>{
      const r=el.getBoundingClientRect();return [el.dataset.portKey,{x:r.left+r.width/2-bounds.left,y:r.top+r.height/2-bounds.top}];
    }));
    return wires.map(w=>({w,a:sockets.get(`${w.from}:out:${w.fromPort}`),b:sockets.get(`${w.to}:in:${w.toPort}`)})).filter(p=>p.a&&p.b);
  }
  // Ping rev1047 canvas spec (archhub-canvas-build-spec.json): raw fills the spec does not tokenise.
  const SPEC = {node:'#17171c', line:'#2b2b34', slot:'#202026', hollow:'#77727f', panel:'#15151a', field:'#1D1D23', fieldLine:'#36343B',
    text:'#D9D6D2', label:'#A7A3A0', count:'#96918C', link:'#F09272', number:'#F2D9CC', typed:'#75BDBA', rule:'#2B292D', exposed:'#2D2624'};
  // Node-RED status pattern: one colour on the card edge plus one status line under it (spec State/* components).
  const nodeState = (n, rejected) => n.frozen ? ['Disabled', A.inkDim] : rejected ? ['Types do not match', A.err]
    : n.previewOff ? ['Preview off', A.inkSoft]
    : /approval|needs you|in review/i.test(n.status) ? ['Needs you', A.warn]
    : /agent|working|wip/i.test(n.status) ? ['Working', A.inkSoft]
    : /error|fail|refus/i.test(n.status) ? ['Failed · ' + (n.error || 'retry'), A.err]
    : /block|held|wait/i.test(n.status) ? ['Blocked · upstream', A.inkSoft]
    : /stale|changed|out of date/i.test(n.status) ? ['Out of date · Run', A.warn]
    : /running|updating/i.test(n.status) ? ['Updating…', A.cyan]
    : /done|ran/i.test(n.status) ? ['Done', A.ink] : ['Not run', A.inkSoft];
  // Spec Wire/*: compatible cyan, affected downstream warn, rejected drag err; one stroke width (wire.strokeWidth = 2).
  const wireColor = (w, nodes) => w.rejected ? A.err : /^(Updating|Out of date)/.test(nodeState(nodes.find(n=>n.id===w.to) || {}, false)[0]) ? A.warn : A.cyan;
  function GraphWires({paths,visibility='Visible',nodes=[]}) {
    return <>{paths.map(({w,a,b})=>{
      const portVisibility=nodes.find(n=>n.id===w.from)?.portVisibility?.[w.fromPort],
        opacity=visibility==='Hidden'||portVisibility==='Hidden' ? 0 : visibility==='Faint'||portVisibility==='Faint' ? .2 : .9;
      return <path key={w.id} data-graph-wire={w.id} d={curve(a,b)} stroke={typeColor(w.type)} strokeWidth="2" strokeLinecap="round" strokeDasharray={w.type==='event'?'6 2':undefined} opacity={opacity} fill="none" />;
    })}</>;
  }
  // e6e4a367 studio-lm.jsx NodeRenderer: category header, role edge and parameter body.
  function NodeRenderer({n, catalogue = [], selected, headerProps, headerEnd, renderPort, renderSocket, rejected, members, onMember, compact = false}) {
    const u = useApp(), s = useData(), [expanded,setExpanded] = React.useState(false), [parameterDrafts,setParameterDrafts] = React.useState({});
    const exact = catalogue.find(c=>c.id===n.definition||c.id===n.assembly||c.name===n.assembly||c.id===n.kind||c.name===n.kind),
      engines=catalogue.filter(c=>c.descriptor?.engine===n.kind), category=exact||(engines.length===1 ? engines[0] : null),
      family = (n.category || category?.family || n.kind).toLowerCase(), grouped = isGroup(n),
      [color, icon] = grouped ? [A.purple,'group'] : ({
        get:[A.cyan,'folder'],host:[A.cyan,'folder'],read:[A.cyan,'folder'],input:[A.blue,'code'],trigger:[A.cyan,'clock'],
        change:[A.warn,'edit'],shape:[A.warn,'group'],filter:[A.warn,'group'],transform:[A.warn,'edit'],document:[A.accent,'docs'],compose:[A.accent,'docs'],annotate:[A.accent,'edit'],
        decide:[A.purple,'brain'],logic:[A.purple,'code'],ai:[A.purple,'brain'],agent:[A.purple,'user'],
        see:[A.ok,'eye'],watch:[A.ok,'eye'],watcher:[A.ok,'eye'],check:[A.ok,'check'],send:[A.ok,'send'],output:[A.ok,'export']})[family] || [A.blue,'canvas'],
      state = n.frozen ? 'Disabled' : n.previewOff ? 'Preview off' : n.status || 'Idle',
      stateColor = /error|fail|refus/i.test(state) ? A.err : /approval|wait|warning|changed/i.test(state) ? A.warn : /running/i.test(state) ? A.accent : /done|ran/i.test(state) ? A.ok : A.inkSoft;
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
    return <D.Node className="lm-node" data-category={family} data-node-state={spec ? specFoot.split(' · ')[0] : undefined} data-spec={spec ? n.dataset ? 'dataset' : 'node' : undefined}
      w={spec ? n.dataset ? 478 : 156 : n.dataset ? 340 : 224} glyph={<window.AHIcon name={icon} size={12} />} gc={color}
      title={n.title} sub={grouped ? `group · ${(members || []).length} members` : category?.name || n.assembly || n.kind}
      style={spec ? {background:frame ? SPEC.panel : SPEC.node,border:frame ? 0 : '1px solid '+specColor,borderRadius:frame ? 12 : 8} : {borderTop:'2px solid '+color}} stacked={grouped}
      edge={spec ? undefined : !n.inputs.length && n.outputs.length ? 'l' : n.inputs.length && !n.outputs.length ? 'r' : undefined}
      selected={selected} run={!spec && /running/i.test(state)} dashed={!spec && n.frozen}
      foot={spec ? <span title={n.error || state}>{specFoot}</span> : <span title={state}>{foot + (n.error ? ' · '+n.error : '') + (n.elapsedMs ? ' · ' + n.elapsedMs + ' ms' : '')}</span>} footc={spec ? specColor : stateColor}
      ins={spec ? n.inputs.filter(p=>!(renderSocket && shownKeys.includes(p.id))) : n.inputs} outs={n.outputs} renderPort={renderPort} portsAfterContent={spec}
      headerProps={{...headerProps,style:spec ? headerProps?.style : {borderTop:'2px solid '+color,borderBottom:'1px solid '+A.lineSoft,...headerProps?.style}}}
      headerEnd={<>{typeof n.pure === 'boolean' && <span data-node-pure={String(n.pure)} style={{fontSize:10,color:n.pure ? A.inkSoft : A.warn}}
        title={n.pure ? 'Pure: re-solves on every edit' : 'Side effect: waits for Run'}>{n.pure ? 'Pure' : 'Side effect'}</span>}
        {spec && n.dataset && <span data-dataset-count>{n.dataset.records.length} records</span>}{headerEnd}</>} chip={grouped && <div className="canvas-members">{(members || []).map(m=><button key={m.id} data-group-member={m.id} className="canvas-member" title={'Open '+m.title} onClick={event=>executeAction('projects.controls.activate',{handler:()=>onMember?.(m)},event)}><span style={{background:color,color:A.onFill}}>{m.title.slice(0,1)}</span>{m.title}</button>)}</div>}>
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
      {!grouped && !n.bind && !n.dataset && !n.column && n.paramDefs && api.addNodeParameter && <AddParameter n={n} u={u} />}
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
      <div data-node-card-title="" style={{position: 'absolute', left: 12, top: 9, right: 40, fontSize: 14, lineHeight: 1.2, color: SPEC.text, whiteSpace: 'pre', overflow: 'hidden', textOverflow: 'ellipsis'}}>{typeGlyph(def.type) && typeGlyph(def.type) + '  '}{def.name}</div>
      <span data-record-count="" style={{position: 'absolute', right: 12, top: 11, fontSize: 12.5, color: SPEC.label}} title="All records">{values.length}</span>
      <div style={{position: 'absolute', left: 12, top: 34, fontSize: 12.5, lineHeight: 1.2, color: SPEC.typed}}>{n.column.label}{def.unit ? ' · ' + def.unit : ''}</div>
      <output data-column-of={n.column.dataset + '.' + n.column.field} data-todo="output-summary-expanded" style={{position: 'absolute', left: 8, right: 8, top: 56, height: 24, boxSizing: 'border-box', padding: '5px 6px', borderRadius: 5,
        background: SPEC.slot, fontSize: 12.5, lineHeight: 1.2, color: SPEC.text, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>{values.slice(0, 3).map(cellText).join(', ')}{values.length > 3 ? '…' : ''}  ›</output>
    </div>;
  }
  // Spec FieldTypeMenu: a listbox of the server's parameter types (node_params.py), labelled as the design names them.
  const TYPE_LABEL = {bool: 'Boolean', integer: 'Integer', number: 'Number · units', text: 'Text', choice: 'Choice', date: 'Date', file: 'File', folder: 'Folder', object: 'Object', list: 'List'};
  function FieldTypeMenu({label, value, onChange}) {
    const [open, setOpen] = React.useState(false);
    return <span style={{position: 'relative', display: 'block'}}>
      <button type="button" className="button-reset spec-input" aria-label={label} aria-haspopup="listbox" aria-expanded={open} onClick={event => executeAction('projects.controls.activate', {handler: () => setOpen(!open)}, event)}>
        {typeGlyph(value) && typeGlyph(value) + '  '}{(TYPE_LABEL[value] || value).split(' · ')[0]}{'  ⌄'}</button>
      {open && <div role="listbox" aria-label="Field type" data-field-type-menu className="spec-type-menu" onKeyDown={e => { if (e.key === 'Escape') { e.stopPropagation(); setOpen(false); } }}>
        <b>Field type</b>{api.parameterTypes().map(t => <button type="button" role="option" aria-selected={t === value} key={t} className="button-reset"
          onClick={event => executeAction('projects.controls.activate', {handler: () => { onChange(t); setOpen(false); }}, event)}>{TYPE_LABEL[t] || t}</button>)}</div>}
    </span>;
  }
  // Spec AddField numeric editor: one form for a dataset field and a node parameter; the value is checked once, on the server.
  function AddField({kind, title, sub, onAdd, onClose}) {
    const [name, setName] = React.useState(''), [type, setType] = React.useState('number'), [value, setValue] = React.useState(''), [options, setOptions] = React.useState(''),
      [limits, setLimits] = React.useState({min: '', max: '', step: '', unit: ''}), [asNode, setAsNode] = React.useState(false);
    const numeric = ['number', 'integer'].includes(type),
      limit = (key, text) => <label key={key}>{text}<input className="spec-input small" aria-label={kind + ' ' + key} value={limits[key]} onChange={e => setLimits(old => ({...old, [key]: e.target.value}))} /></label>;
    return <div data-add-field-form role="dialog" aria-label={title} className="spec-add-field" onPointerDown={e => e.stopPropagation()} onKeyDown={e => { if (e.key === 'Escape') onClose(); }}>
      <b>{title}</b><p>{sub}</p>
      <div className="spec-add-row"><label>Name<input className="spec-input" aria-label={kind + ' name'} placeholder="Width" value={name} onChange={e => setName(e.target.value)} /></label>
        <label>Type<FieldTypeMenu label={kind + ' type'} value={type} onChange={setType} /></label></div>
      {type === 'choice' && <label>Choices<input className="spec-input" aria-label={kind + ' options'} placeholder="Choices, comma separated" value={options} onChange={e => setOptions(e.target.value)} /></label>}
      <label><span>Default{type === 'number' && <> {'·'} <input className="spec-unit" aria-label={kind + ' unit'} placeholder="unit" value={limits.unit} onChange={e => setLimits(old => ({...old, unit: e.target.value}))} /></>}</span>
        <input className="spec-input" aria-label={kind + ' value'} type={numeric ? 'number' : type === 'date' ? 'date' : 'text'} value={value} onChange={e => setValue(e.target.value)} /></label>
      {numeric && <div className="spec-add-limits">{limit('min', 'Minimum')}{limit('max', 'Maximum')}{limit('step', 'Step')}</div>}
      <div className="spec-add-foot"><label><input type="checkbox" aria-label="Show as node" checked={asNode} onChange={e => setAsNode(e.target.checked)} /> Expose as node</label>
        <button type="button" className="button-reset spec-add-go" aria-label={title} onClick={event => executeAction('projects.controls.activate', {handler: () => onAdd({name, type, value, showAsNode: asNode,
          ...(numeric ? Object.fromEntries(Object.entries(limits).filter(([, v]) => v !== '').map(([k, v]) => [k, k === 'unit' ? v : Number(v)])) : {}),
          options: type === 'choice' ? options.split(',').map(x => x.trim()).filter(Boolean) : undefined}).then(onClose)}, event)}>{title}{'  →'}</button></div>
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
    return <div data-dataset-editor onPointerDown={e => e.stopPropagation()} style={{gridTemplateColumns: `repeat(${fields.length}, minmax(0,1fr)) 80px`}}>
      {fields.map(f => <button key={f.id} type="button" className="button-reset" data-field={f.id} data-exposed={exposed(f) || undefined} aria-label={'Show field ' + f.name + ' as node'}
        title={exposed(f) ? 'Shown as node' : 'Show as node: the whole column as a typed list'} onClick={event => executeAction('projects.controls.activate', {handler: () => exposed(f) || u.act(() => api.exposeDatasetField(n.id, f.id))}, event)}>
        {typeGlyph(f.type) && typeGlyph(f.type) + ' '}{f.name}{exposed(f) ? ' ↗' : ''}</button>)}
      <button type="button" className="button-reset" data-dataset-link aria-label={'Add field to ' + n.title} onClick={event => executeAction('projects.controls.activate', {handler: () => setAdding(!adding)}, event)}>+ Field</button>
      {records.map((r, index) => <React.Fragment key={r.id}>{fields.map(f => <span key={f.id} data-record={index} data-cell-type={f.type} data-exposed={exposed(f) || undefined}>{cell(index, f)}</span>)}<span data-record={index} /></React.Fragment>)}
      {fields.map((f, i) => <small key={f.id}>{i === 0 && <button type="button" className="button-reset" data-dataset-link aria-label={'Add record to ' + n.title} disabled={!fields.length}
        onClick={event => executeAction('projects.controls.activate', {handler: () => u.act(() => api.addDatasetRecord(n.id))}, event)}>+ Record</button>}{f.unit}</small>)}
      {!fields.length && <small />}<small />
      {adding && <AddField kind="Field" title="Add field" sub="A column shared by every record" onClose={() => setAdding(false)}
        onAdd={input => u.act(() => api.addDatasetField(n.id, input))} />}
    </div>;
  }
  // Add parameter: the same AddField editor, opened from the card's + (spec NodeCard "Add parameter").
  function AddParameter({n, u}) {
    const [open, setOpen] = React.useState(false);
    return <>
      <button className="button-reset canvas-card-add" data-add-parameter aria-label={'Add parameter to ' + n.title} title="Add parameter" onClick={event => executeAction('projects.controls.activate', {handler: () => setOpen(!open)}, event)}>+ Parameter</button>
      {open && <AddField kind="Parameter" title="Add parameter" sub="A value on this node" onClose={() => setOpen(false)} onAdd={input => u.act(() => api.addNodeParameter(n.id, input))} />}
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
  const LAYOUT = {nodeWidth: 280, datasetWidth: 478, inspectorWidth: 320};
  const CARD = {background: SPEC.field, border: '1px solid ' + SPEC.fieldLine, borderRadius: 6, boxSizing: 'border-box', position: 'relative', color: SPEC.text, fontSize: 12.5, lineHeight: 1.2};
  const SLOT = {background: SPEC.slot, borderRadius: 5, padding: '6px 9px', position: 'relative', display: 'flex', alignItems: 'center', gap: 6, minHeight: 28, boxSizing: 'border-box'};
  const edgeSocket = (side, top, inset = 0) => ({position: 'absolute', [side === 'in' ? 'left' : 'right']: -11 - inset, top, transform: 'translateY(-50%)', lineHeight: 0, zIndex: 2});
  function ValueWidget({n, p, value, u}) {
    const [draft, setDraft] = React.useState(null), shown = draft ?? value, label = n.title + ' ' + p.key;
    const save = v => { setDraft(v); return u.act(() => api.setNodeParam(n.id, p.key, v)).then(() => setDraft(null)); };
    if (!p.editable) return <span title={String(shown)}>{summary(shown)}</span>;
    if (p.type === 'boolean') return <D.Toggle label={label} checked={!!shown} onCheckedChange={save} />;
    if (p.options?.length) return <select className="nodrag" aria-label={label} value={shown} onChange={e => save(e.target.value)}>{p.options.map(o => <option key={o}>{o}</option>)}</select>;
    return <input className="nodrag" aria-label={label} title={String(shown)} type={p.type === 'number' ? 'number' : 'text'} min={p.min} max={p.max} step={p.step ?? 'any'}
      value={typeof shown === 'object' ? JSON.stringify(shown) : shown} style={{flex: 1, minWidth: 0, width: 0, background: 'transparent', border: 0, color: SPEC.text, font: 'inherit', fontSize: 12}}
      onChange={e => { if (p.type !== 'number' || Number.isFinite(e.target.valueAsNumber)) save(p.type === 'number' ? e.target.valueAsNumber : e.target.value); }} />;
  }
  function ParameterNode({n, socket, selected, u}) {
    // LimitParameter: one typed value, inline stepper and slider, one output socket; the value lives in this node only.
    // A value the owner does not hold (router.json without it) shows "unset", never a default.
    const p = n.parameterSchema?.find(x => x.key === 'value') || {key: 'value', type: 'number', editable: true}, unset = typeof n.params.value !== 'number',
      value = unset ? NaN : n.params.value, max = p.max ?? (unset || Math.abs(value) <= 2 ? 2 : Math.abs(value) * 2), min = p.min ?? 0, step = p.step ?? (max <= 2 ? .05 : 1),
      out = n.outputs[0], save = v => u.act(() => api.setNodeParam(n.id, 'value', Math.min(max, Math.max(min, +v.toFixed(6)))));
    return <div data-ds-node="" data-spec="parameter" className="node-header" style={{...CARD, width: 180, height: 80, outline: selected ? '2px solid ' + A.accent : 'none', outlineOffset: 2}}>
      <div data-node-card-title="" style={{position: 'absolute', left: 12, top: 9, right: 40, color: SPEC.typed}}>#  {n.title}</div>
      {!n.pure && <span data-node-pure="false" title="Side effect: waits for Run" style={{position: 'absolute', right: 10, top: 9, color: A.inkSoft}}>⚡</span>}
      <div style={{position: 'absolute', left: 12, top: 32, right: 12, display: 'flex', alignItems: 'center', gap: 6, color: SPEC.typed}}>
        {unset ? <span data-unset="" style={{flex: 1, color: SPEC.label}} title="Not set in router.json">unset</span> : <ValueWidget n={n} p={{...p, type: 'number', min, max, step}} value={value} u={u} />}
        <span>{p.unit || ''}</span>
        <button type="button" className="button-reset nodrag" aria-label={'Decrease ' + n.title} onClick={event => executeAction('projects.controls.activate', {handler: () => save((unset ? min : value) - step)}, event)}>◀</button>
        <button type="button" className="button-reset nodrag" aria-label={'Increase ' + n.title} onClick={event => executeAction('projects.controls.activate', {handler: () => save((unset ? min : value) + step)}, event)}>▶</button>
      </div>
      <input className="nodrag" type="range" aria-label={n.title + ' slider'} min={min} max={max} step={step} value={unset ? min : value}
        onChange={e => save(e.target.valueAsNumber)} style={{position: 'absolute', left: 12, right: 12, top: 58, width: 156, accentColor: SPEC.typed}} />
      {out && <span style={edgeSocket('out', 34)}>{socket(out, 'out')}</span>}
    </div>;
  }
  // Spec d9c0d514: one footer chip per card (Done / Not run / Out of date, or what stops it), never a second status line.
  const FOOT = {display: 'inline-block', justifySelf: 'start', padding: '1px 8px', borderRadius: 10, border: '1px solid ' + SPEC.fieldLine};
  function RefusedChip({refusal, onConvert}) {
    return <div data-refused-chip="" role="status" style={{color: A.err, display: 'flex', flexWrap: 'wrap', gap: 4}}>
      {refusal.outType === refusal.inType && refusal.reason ? <span>{refusal.reason}</span> : <><span>Needs a {refusal.outType} → {refusal.inType} converter ·</span>
      <button type="button" className="button-reset nodrag" style={{color: A.err, textDecoration: 'underline'}} onClick={event => executeAction('projects.controls.activate', {handler: onConvert}, event)}>Insert converter</button></>}
    </div>;
  }
  function FlowCard({n, s, u, selected, refusal, onConvert, socket, members, onMember, menu}) {
    // Spec section 0b P0: the default card is full capability (every row); compact (first three rows) is an opt-in toggle.
    const [compact, setCompact] = React.useState(false);
    const field = n.column && fieldColumn(n, s.graph);
    if (field) return <FieldNode n={n} field={field} selected={selected} headerProps={{className: 'node-header'}} renderSocket={socket} />;
    const scalarParameter = ['thing.setting', 'param.value'].includes(n.type) && n.outputs.length === 1 && (typeof n.params.value === 'number' || n.params.value === null);
    if (scalarParameter) return <ParameterNode n={n} socket={socket} selected={selected} u={u} />;
    const [state, stateColor] = nodeState(n, !!refusal), wiresIn = s.graph.wires.filter(w => w.to === n.id),
      sourceOf = port => { const w = wiresIn.find(x => x.toPort === port), a = w && s.graph.nodes.find(x => x.id === w.from); return a && a.title + '.' + (a.outputs.find(p => p.id === w.fromPort)?.name || w.fromPort); },
      slotPorts = new Set(), settingsKeys = new Set(n.settingsKeys || []),
      // Internal ids, hashes and serialized JSON stay in Properties; the face shows human values (CARDPOLISH), first three until expanded.
      shown = (n.parameterSchema || []).filter(p => p.editable || (!HIDDEN_PARAM.test(p.key) && (n.params[p.key] === null || typeof n.params[p.key] !== 'object') && !HIDDEN_VALUE.test(String(n.params[p.key]))))
        .filter(p => !(p.key === 'prompt' && n.inputs.some(x => x.id === 'prompt'))),
      params = compact ? shown.slice(0, 3) : shown,
      refusedHere = port => refusal && refusal.to.port === port && <RefusedChip refusal={refusal} onConvert={onConvert} />;
    for (const p of params) if (n.inputs.some(x => x.id === p.key || x.id === 'param:' + p.key)) slotPorts.add(n.inputs.find(x => x.id === p.key || x.id === 'param:' + p.key).id);
    const result = n.status === 'Done' ? summary(n.output) : '';
    return <div data-ds-node="" className="lm-node" data-spec={n.dataset ? 'dataset' : 'operation'} data-node-state={state.split(' · ')[0]}
      style={{...CARD, width: n.dataset ? LAYOUT.datasetWidth : LAYOUT.nodeWidth, paddingBottom: 10, border: '1px solid ' + (refusal ? A.err : SPEC.fieldLine), outline: selected ? '2px solid ' + A.accent : 'none', outlineOffset: 2}}>
      <div className="node-header" style={{display: 'flex', alignItems: 'flex-start', gap: 8, padding: '11px 12px 0'}}>
        <div data-node-card-title="" style={{flex: 1, minWidth: 0, fontSize: 14, overflowWrap: 'anywhere'}}>{n.title}</div>
        {!n.pure && <span data-node-pure="false" style={{paddingTop: 2, color: A.inkSoft}}
          title={'Side effect: waits for Run' + (n.budget ? ' · budget ' + [n.budget.seconds != null && n.budget.seconds + ' s', n.budget.calls != null && n.budget.calls + ' call(s)'].filter(Boolean).join(', ') : '')}>⚡</span>}{menu}
      </div>
      {members.length > 0 && <div className="canvas-members">{members.map(m => <button key={m.id} data-group-member={m.id} className="canvas-member nodrag" title={'Open ' + m.title} onClick={event => executeAction('projects.controls.activate', {handler: () => onMember(m)}, event)}><span style={{background: A.purple, color: A.onFill}}>{m.title.slice(0, 1)}</span>{m.title}</button>)}</div>}
      <div style={{display: 'grid', gap: 8, padding: '12px 12px 0'}}>
        {/* Full-node row (archhub-full-node-controls-native.png): name over its type, then the linked source or an inline control, then a row menu. Real data or empty. */}
        {[...n.inputs.filter(p => !slotPorts.has(p.id)).map(p => ({key: p.id, port: p})), ...params.map(p => ({key: 'param:' + p.key, param: p, port: n.inputs.find(x => x.id === p.key || x.id === 'param:' + p.key)}))].map(({key, port, param}) => {
          const from = port && sourceOf(port.id), name = param ? (param.label && param.label !== param.key ? param.label : param.key.replace(/_/g, ' ')) : port.name,
            type = param ? (param.dataType || (param.options?.length ? 'enum' : param.type === 'boolean' ? 'boolean' : param.type === 'number' ? 'number' : 'string')) + (param.unit ? ' · ' + param.unit : '') + (settingsKeys.has(param.key) ? ' · From Settings' : '') : typeName(port);
          return <React.Fragment key={key}><div data-port-row={param ? undefined : 'in'} data-parameter={param ? param.key : undefined}
            style={{...SLOT, display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1.2fr) auto', gap: 8, padding: '4px 4px 4px 10px', alignItems: 'center'}}>
            {port && <span style={edgeSocket('in', '50%', 12)}>{socket(port, 'in')}</span>}
            <span style={{minWidth: 0}}><span style={{display: 'block', fontSize: 13.5, overflowWrap: 'anywhere'}} title={param ? param.label || param.key : port.name}>{name}</span>
              <span style={{display: 'block', color: SPEC.label}}>{type}</span></span>
            <span data-row-value="" style={{display: 'flex', alignItems: 'center', gap: 6, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>
              {from ? <span data-linked-source="" style={{color: SPEC.typed}} title={from}>↳ {from}</span>
                : !param ? null : n.params[param.key] === null ? <span data-unset="" style={{color: SPEC.label}}>unset</span> : <ValueWidget n={n} p={param} value={n.params[param.key]} u={u} />}</span>
            <button type="button" className="button-reset nodrag" aria-label={name + ' row actions'} style={{color: SPEC.label, padding: '0 4px'}}
              onClick={event => executeAction('projects.controls.activate', {handler: () => u.show('Port menu', {id: n.id, port: port?.id || 'param:' + param.key, anchor: {x: event.clientX, y: event.clientY}})}, event)}>⋮</button>
          </div>{port && refusedHere(port.id)}</React.Fragment>;
        })}
        {shown.length > 3 && <button type="button" className="button-reset nodrag canvas-card-more" aria-pressed={compact} style={{justifySelf: 'start', color: SPEC.label}} onClick={event => executeAction('projects.controls.activate', {handler: () => setCompact(!compact)}, event)}>{compact ? `+${shown.length - 3} more` : 'Compact'}</button>}
        {n.loop && <div data-node-loop="" style={{color: SPEC.label}} title={'Trigger ' + n.loop.trigger + ' · stops when ' + n.loop.stop + (n.loop.evaluator ? ' · evaluator ' + n.loop.evaluator : '')}>Loop · cap {n.loop.cap} · until {n.loop.stop}</div>}
        {n.dataset && <DatasetEditor n={n} u={u} />}
        {!n.dataset && !n.column && n.paramDefs && api.addNodeParameter && <AddParameter n={n} u={u} />}
        {n.outputs.map(p => <div key={p.id} data-port-row="out" style={{position: 'relative', color: SPEC.typed, minHeight: 18, display: 'flex', alignItems: 'center'}}>
          <span>{p.name} · {typeName(p)}</span><span style={edgeSocket('out', '50%', 12)}>{socket(p, 'out')}</span></div>)}
        {n.outputs.length > 0 && <div data-node-result="" data-todo="output-summary-expanded" style={{...SLOT, color: result ? SPEC.text : SPEC.label, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', display: 'block'}} title={result}>{result ? '▸  ' + result : wiresIn.length || !n.inputs.length ? 'Run to inspect output' : 'Connect data to inspect output'}</div>}
        <span data-node-status="" style={{...FOOT, color: stateColor}} title={n.error || state}>{state.split(' · ')[0]}</span>
      </div>
    </div>;
  }
  // DESIGNSYS-050 4.9 Inspector (plate archhub-inspector-changed-native.png): Properties of the one selected node; its Inputs and Output, editable.
  function NodeInspector({n, s, u}) {
    const sourceOf = port => { const w = s.graph.wires.find(x => x.to === n.id && x.toPort === port), a = w && s.graph.nodes.find(x => x.id === w.from); return a && a.title + ' · ' + (a.outputs.find(p => p.id === w.fromPort)?.name || w.fromPort); };
    const params = (n.parameterSchema || []).filter(p => p.editable), [state] = nodeState(n, false), result = n.status === 'Done' ? summary(n.output) : '';
    const cap = {fontSize: 12, color: SPEC.label, margin: '16px 0 6px'};
    return <aside className="pane inspector" data-node-inspector={n.id} aria-label="Properties" style={{borderLeft: '1px solid ' + A.line, padding: 16, overflow: 'auto'}}>
      <div className="muted" style={{fontSize: 12}}>Properties</div>
      <h2 style={{margin: '4px 0 0', paddingLeft: 8, borderLeft: '2px solid ' + A.accent}}>{n.title}</h2>
      <div style={{color: SPEC.label, fontSize: 12, marginTop: 2}}>{state} · {n.pure ? 'pure' : 'side effect'}{n.kind ? ' · ' + n.kind : ''}</div>
      <div style={cap}>Inputs</div>
      <div style={{display: 'grid', gap: 6}}>{n.inputs.filter(p => !params.some(q => q.key === p.id || 'param:' + q.key === p.id)).map(p => <div key={p.id} style={SLOT}>
        <span style={{flex: 1, minWidth: 0}}><span style={{display: 'block', color: SPEC.label, fontSize: 11}}>{p.name} · {typeName(p)}</span>{sourceOf(p.id) || <span style={{color: SPEC.label}}>Not connected</span>}</span></div>)}
        {params.map(p => <label key={p.key} style={SLOT}><span style={{flex: 1, minWidth: 0}}><span style={{display: 'block', color: SPEC.label, fontSize: 11}}>{p.label || p.key.replace(/_/g, ' ')}</span>
          {n.params[p.key] === null ? <span style={{color: SPEC.label}}>unset</span> : <ValueWidget n={n} p={p} value={n.params[p.key]} u={u} />}</span></label>)}
        {!n.inputs.length && !params.length && <span style={{color: SPEC.label}}>No inputs</span>}</div>
      <div style={cap}>Output</div>
      {n.outputs.map(p => <div key={p.id} style={{color: SPEC.typed}}>{p.name} · {typeName(p)}</div>)}
      <div style={{color: result ? SPEC.text : SPEC.label, marginTop: 6, overflowWrap: 'anywhere'}}>{result || (n.outputs.length ? 'No output yet' : 'No output')}</div>
    </aside>;
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
    return <div ref={box} data-graph-node={id}>{c.renderNode(n, selected)}</div>;
  }
  function FlowWire({id, sourceX, sourceY, targetX, targetY, data}) {
    // xyflow anchors at the Handle's outer edge; the spec wire meets the socket centre (Handle is 22 px wide, see SOCKET_STYLE).
    const d = curve({x: sourceX - 11, y: sourceY}, {x: targetX + 11, y: targetY});
    return <>{data.selected && <path d={d} stroke={A.ink} strokeWidth="8" opacity=".22" fill="none" />}
      <path data-graph-wire={id} data-wire-state={data.state} d={d} stroke={data.color} strokeWidth="2" strokeLinecap="round" opacity={data.opacity} fill="none" />
      <path className="react-flow__edge-interaction" d={d} stroke="transparent" strokeWidth="16" fill="none" aria-label={'Inspect wire ' + id} />
    </>;
  }
  const nodeTypes = {archhub: FlowNode}, edgeTypes = {archhub: FlowWire};
  const SOCKET_STYLE = {position: 'relative', inset: 'auto', transform: 'none', display: 'inline-grid', placeItems: 'center', width: 22, height: 22,
    minWidth: 0, minHeight: 0, background: 'transparent', border: 0, borderRadius: 0};
  function Canvas({
    active = true
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
      [rejected, setRejected] = React.useState(null),
      [layout, setLayout] = React.useState({scope: null, positions: {}}),
      [flowNodes, setFlowNodes] = React.useState([]),
      [more, setMore] = React.useState(false),
      [wireTab, setWireTab] = React.useState('Rules');
    const area = React.useRef(),
      view = React.useRef(viewport),
      held = React.useRef(null),
      zoomWrites = React.useRef(Promise.resolve()),
      pendingZoomWrites = React.useRef(0);
    const fittedScope = React.useRef(null);
    const {zoom, pan} = viewport;
    const [requestState, setRequestState] = React.useState('waiting');
    const [requestError, setRequestError] = React.useState('');
    const zoomSetting = zoomRow?.value;
    const appliedZoomSetting = React.useRef(zoomSetting);
    const zoomSaveDelay = Number(s.canvasPolicy?.viewport_commit_debounce_ms ?? 140);
    const updateView = next => { view.current = next; setViewport(next); api.setSessionViewport?.({x:next.pan.x,y:next.pan.y,zoom:next.zoom}); };
    React.useEffect(()=>{const saved=s.graph.viewport;if(saved){const next={zoom:saved.zoom,pan:{x:saved.x,y:saved.y}};view.current=next;setViewport(next);}},[s.graph.scopeKey]);
    const zoomAt = (value, client = null) => {
      const bounds = area.current?.getBoundingClientRect();
      if (!bounds) return;
      const old = view.current, next = Math.max(zoomMin, Math.min(zoomMax, value));
      const x = client ? client.x - bounds.left : bounds.width / 2,
        y = client ? client.y - bounds.top : bounds.height / 2;
      updateView({zoom: next, pan: {x: x - (x - old.pan.x) * next / old.zoom, y: y - (y - old.pan.y) * next / old.zoom}});
    };
    React.useEffect(() => {
      if (!active || Object.is(appliedZoomSetting.current,zoomSetting)) return;
      if (pendingZoomWrites.current) { appliedZoomSetting.current=zoomSetting; return; }
      if (!Number.isFinite(Number(zoomSetting))) return;
      appliedZoomSetting.current=zoomSetting;
      zoomAt(Number(zoomSetting) / 100);
    }, [zoomSetting, requestState, active]);
    React.useEffect(() => {
      const percent = Math.round(zoom * 100);
      if (!active) return;
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
    React.useEffect(() => { if(active && requestState==='waiting'){reload(); u.setLibraryOpen?.(true);} }, [active]);
    React.useEffect(() => {
      if (requestState === 'loaded' || requestState === 'empty')
        setRequestState(s.graph.nodes.length ? 'loaded' : 'empty');
    }, [s.graph.nodes.length]);
    // A node whose group is not a node at this level is drawn here, never dropped.
    const atLevel = n => !s.graph.system && !n.application && ((n.parent || null) === parent || (parent === null && !s.graph.nodes.some(x => x.id === n.parent)));
    const scope = s.graph.id + ':' + (parent || ''), sourceNodes = s.graph.nodes.filter(atLevel);
    const visible = sourceNodes.map(n => ({...n, ...(layout.scope === scope ? layout.positions[n.id] : {})})),
      node = s.graph.nodes.find(n => n.id === selected.at(-1)),
      wire = s.graph.wires.find(w => w.id === wireId),
      inspected = !wire && selected.length === 1 && s.graph.nodes.find(n => n.id === selected[0]);
    React.useLayoutEffect(() => {
      if (!active) return;
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
    React.useEffect(() => {
      if (!active) return;
      const listener = e => {
        if (e.target.closest?.('input,textarea,select,[contenteditable="true"],[role="textbox"]')) return;
        if (area.current?.contains(e.target)) {
          if (e.key === '+' || e.key === '=') { e.preventDefault(); zoomAt(view.current.zoom * 1.2); }
          if (e.key === '-') { e.preventDefault(); zoomAt(view.current.zoom / 1.2); }
          if (e.key === '0') { e.preventDefault(); e.ctrlKey ? fit() : zoomAt(1); }
          if (e.shiftKey && (e.code === 'Digit1' || e.key === '1')) { e.preventDefault(); fit(); }
        }
        if (e.ctrlKey && e.key.toLowerCase() === 's') {
          e.preventDefault();
          u.act(() => api.saveSession());
        }
        if (e.ctrlKey && e.key.toLowerCase() === 'g') {
          e.preventDefault();
          group();
        }
        if (e.key === 'Delete' && selected.length) {
          e.preventDefault();
          remove();
        }
        if (e.key === 'Enter' && node && isGroup(node)) openNode(node);
        if (e.key === 'Escape') {
          setRejected(null);
          setSelected([]);
          setWireId(null);
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
    React.useEffect(() => u.setSelectedNodeId(selected.at(-1) || null), [selected.join(',')]);
    // The file is the source; xyflow keeps only what it measured (sizes) and an in-flight drag.
    React.useEffect(() => {
      setFlowNodes(old => {
        const prior = new Map(old.map(f => [f.id, f]));
        return visible.map(n => {
          const f = prior.get(n.id);
          // ComfyUI/Grasshopper: a card moves by its title bar; its fields and buttons keep the pointer.
          return {id: n.id, type: 'archhub', data: {n}, dragHandle: '.node-header', selected: selected.includes(n.id), measured: f?.measured, dragging: f?.dragging,
            position: f?.dragging ? f.position : held.current?.[n.id] || {x: n.x, y: n.y}};
        });
      });
    }, [s.graph, layout, parent, selected.join(','), requestState]);
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
      const positions = Object.fromEntries((all?.length ? all : [dragged]).map(f => [f.id, {x: f.position.x, y: f.position.y}]));
      held.current = positions;
      Promise.resolve(u.act(() => api.moveNodes(positions))).finally(() => { if (held.current === positions) held.current = null; });
    };
    const group = async () => {
      const g = await u.act(() => api.groupNodes(selected));
      if (g) setSelected([g.id]);
    };
    const remove = () => u.confirm(`Delete ${selected.length} selected node${selected.length === 1 ? '' : 's'}?`, async () => {
      for (const id of selected) await api.deleteNode(id);
      setSelected([]);
    });
    const connect = async (out, input) => {
      const word = p => (TYPE_NAME[p.type] || p.type || 'any').toLowerCase();
      if (out.id === input.id) return;
      const outputPort = s.graph.nodes.find(n=>n.id===out.id)?.outputs.find(p=>p.id===out.port),
        inputPort = s.graph.nodes.find(n=>n.id===input.id)?.inputs.find(p=>p.id===input.port);
      if (!outputPort || !inputPort || outputPort.connectable === false || inputPort.connectable === false || outputPort.read_only || inputPort.read_only) return;
      if (outputPort.type !== inputPort.type && outputPort.type !== 'any' && inputPort.type !== 'any') {
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
    const socket = (n, p, side) => {
      const locked = p.connectable === false || p.read_only;
      return <RF.Handle type={side === 'out' ? 'source' : 'target'} position={side === 'out' ? RF.Position.Right : RF.Position.Left} id={p.id} isConnectable={!locked}
        data-port-key={`${n.id}:${side}:${p.id}`} className="socket" data-port-type={p.type} data-port-list={p.list || undefined}
        title={`${p.name} · ${p.type}${p.list ? " list" : ""}${p.unit ? " · "+p.unit : ""}`} aria-disabled={locked || undefined} aria-label={`${n.title} ${side} ${p.name}`}
        style={SOCKET_STYLE} onContextMenu={e => {
          e.preventDefault();
          e.stopPropagation();
          u.show('Port menu', {id: n.id, port: p.id, anchor: {x: e.clientX, y: e.clientY}});
        }}><span data-socket-dot="" data-wired={side === 'out' || s.graph.wires.some(w => w.to === n.id && w.toPort === p.id) || undefined} /></RF.Handle>;
    };
    const renderNode = (n, isSelected) => {
      const members = (n.children || []).map(id => s.graph.nodes.find(x => x.id === id) || n.members?.find(m => m.id === id)).filter(Boolean);
      return <FlowCard n={n} s={s} u={u} selected={isSelected} refusal={rejected?.to.id === n.id ? rejected : null} onConvert={insertConverter} members={members} socket={(p, side = 'in') => socket(n, p, side)}
        onMember={m=>{if (s.graph.nodes.some(row => row.id === m.id)) {setParent(n.id);setSelected([m.id]);} else {setParent(null);u.act(async()=>{await api.selectGraph(n.id);setSelected([m.id]);});}}}
        menu={<button className="button-reset canvas-node-menu nodrag" aria-label={n.title+' menu'} title={n.title+' actions'} onClick={event=>executeAction('projects.ds_screens.NodeMenu.16',{n,openNode,setSelected,u},event)}>⋯</button>} />;
    };
    const stale = (s.solveStale || []).filter(id => s.graph.nodes.some(n => n.id === id)).length;
    const shownIds = new Set(visible.map(n => n.id));
    const edges = (rejected ? [...s.graph.wires,{id:'rejected',rejected:true,from:rejected.from.id,fromPort:rejected.from.port,to:rejected.to.id,toPort:rejected.to.port}] : s.graph.wires)
      .filter(w => shownIds.has(w.from) && shownIds.has(w.to)).map(w => {
        const color = w.rejected ? A.err : wireColor(w, s.graph.nodes), shown = s.graph.wireVisibility, portVisibility = s.graph.nodes.find(n=>n.id===w.from)?.portVisibility?.[w.fromPort];
        return {id: w.id, type: 'archhub', source: w.from, target: w.to, sourceHandle: w.fromPort, targetHandle: w.toPort, selectable: false, focusable: false,
          data: {color, state: w.rejected ? 'rejected' : color === A.warn ? 'affected' : 'compatible', selected: wireId === w.id && shown !== 'Hidden',
            opacity: w.rejected ? 1 : shown==='Hidden'||portVisibility==='Hidden' ? 0 : shown==='Faint'||portVisibility==='Faint' ? .2 : .9}};
      });
    const fit = () => {
      if (!visible.length || !area.current) return;
      const w = area.current.clientWidth, h = area.current.clientHeight;
      const boxes = [...area.current.querySelectorAll('[data-graph-node]')].map(el => {
        const n = visible.find(n => n.id === el.dataset.graphNode);
        return n && {x: n.x, y: n.y, w: n.w || el.offsetWidth || el.getBoundingClientRect().width / view.current.zoom || 224,
          h: n.h || el.offsetHeight || el.getBoundingClientRect().height / view.current.zoom || 160};
      }).filter(Boolean);
      if (!boxes.length) return;
      const minX = Math.min(...boxes.map(b => b.x)), minY = Math.min(...boxes.map(b => b.y)),
        width = Math.max(...boxes.map(b => b.x+b.w)) - minX,
        height = Math.max(...boxes.map(b => b.y+b.h)) - minY,
        z = Math.max(zoomMin, Math.min(zoomMax, Number(s.canvasPolicy?.zoom_fit_max ?? 1.25), (w-60) / Math.max(1,width), (h-60) / Math.max(1,height)));
      updateView({zoom: z, pan: {x: (w-width*z)/2-minX*z, y: (h-height*z)/2-minY*z}});
    };
    React.useEffect(() => {
      if (s.graph.viewport || !active || requestState !== 'loaded' || layout.scope !== scope || fittedScope.current === scope+':'+u.libraryOpen) return;
      fittedScope.current = scope+':'+u.libraryOpen;
      fit();
    }, [requestState, scope, layout, u.libraryOpen, active]);
    const openNode = n => {
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
    const body = <div data-screen="canvas" style={{
      display: 'grid',
      gridTemplateRows: 'minmax(0,1fr)',
      position: 'relative',
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
  {/* Spec d9c0d514 top bar: name · Unsaved, + Add node, ⋯, Run. Everything else lives in ⋯; saving is autosave plus Ctrl+S. */}
  <div data-canvas-overlay="" data-canvas-topbar="" className="spread" style={{
        position:'absolute',top:12,left:u.libraryOpen ? 264 : 16,right:16,zIndex:12,
        padding: '6px 12px',borderRadius:6,border:'1px solid '+A.lineSoft,
        background: A.bgPanel, fontSize: 13
      }}><div className="flex"><button className="button-reset" title="Workflows" aria-label="Workflows" onClick={event => executeAction("projects.ds_screens.Graphs.7", {u}, event)}>{s.graph.name} · {s.sessionDirty === false ? 'Saved' : 'Unsaved'}</button>
        {parent && <Btn variant="controls" sm ghost onClick={event => executeAction("projects.ds_screens.Parent.6", {parent,s,setParent,setSelected}, event)}>← Parent</Btn>}
        {stale > 0 && <span data-solve-status="" style={{color: A.warn}}>{stale} out of date · Run</span>}</div>
      <div className="flex" style={{position:'relative'}}> <Btn variant="controls" sm ghost aria-label="More canvas actions" aria-expanded={more} onClick={event => executeAction('projects.controls.activate', {handler: () => setMore(!more)}, event)}>⋯</Btn>
        <Btn variant="controls" p sm onClick={event => executeAction("projects.ds_screens.Run.15", {api,u}, event)}>▶ Run</Btn>
        {more && <div role="menu" aria-label="Canvas actions" data-canvas-more="" onKeyDown={e => { if (e.key === 'Escape') setMore(false); }} style={{position:'absolute',right:0,top:'calc(100% + 6px)',display:'grid',minWidth:200,padding:6,gap:2,
          background:A.bgPanel,border:'1px solid '+A.lineSoft,borderRadius:6,zIndex:20}}>{[
            ['Add node · Ctrl K', () => executeAction("projects.ds_screens.AddANodeCtrlK.24", {u})], ['New', () => u.act(() => api.newSession())], ['Open…', () => u.act(() => api.openSession())], ['Save · Ctrl S', () => u.act(() => api.saveSession())],
            ['Save as…', () => u.act(() => api.saveSessionAs())], ['Save as skill…', () => u.show('Save skill')], ['Workspaces · ' + s.workspaces.length, () => u.show('Workspaces')],
            [(u.libraryOpen ? 'Hide' : 'Show') + ' Library', () => u.setLibraryOpen(v => !v)], ['Group · Ctrl G', group, selected.length < 2],
            ['Undo · Ctrl Z', () => u.act(api.undo)], ['Redo · Ctrl Shift Z', () => u.act(api.redo)], ['Arrange', () => u.act(api.arrangeGraph)],
            ['Wires: ' + (s.graph.wireVisibility || 'Visible') + ' → ' + ({Visible: 'Faint', Faint: 'Hidden', Hidden: 'Visible'})[s.graph.wireVisibility || 'Visible'],
              () => u.act(() => api.setWireVisibility(({Visible: 'Faint', Faint: 'Hidden', Hidden: 'Visible'})[s.graph.wireVisibility || 'Visible']))],
          ].map(([label, run, disabled]) => <button key={label} role="menuitem" type="button" className="button-reset listbutton" disabled={disabled} style={{textAlign:'left',padding:'6px 8px'}}
            onClick={event => executeAction('projects.controls.activate', {handler: () => { setMore(false); return run(); }}, event)}>{label}</button>)}</div>}</div></div>
  <div style={{
        display: 'grid',
        gridTemplateColumns: (u.libraryOpen ? '248px ' : '') + 'minmax(0,1fr)' + (wire || inspected ? ' ' + LAYOUT.inspectorWidth + 'px' : ''),
        minHeight: 0
      }}>{u.libraryOpen && <window.UI.LibraryShelf onClose={() => u.setLibraryOpen(false)} />}
   <div ref={area} className={'node-canvas' + (visible.some(n => n.status === 'Running') ? ' running-wires' : '')} tabIndex={0} aria-label="Workflow canvas" style={{position:'relative',minHeight:0,'--xy-selection-background-color':A.accent+'16','--xy-selection-border':'1px solid '+A.accent,'--xy-background-color':'transparent'}}
        title="Drag to select · Shift adds · Middle or Space-drag to pan · Wheel to zoom · Double-click to fit"
        onDoubleClick={e => { if (e.target.classList?.contains('react-flow__pane')) fit(); }}
        onDragOver={e => e.preventDefault()} onDrop={e => {
          e.preventDefault();
          if(e.dataTransfer.files?.length){u.act(()=>api.importSession(e.dataTransfer.files[0]));return;}
          const name = e.dataTransfer.getData('node');
          if (name) u.act(() => api.addNode(name, toFlow(e)));
        }} onContextMenu={e => {
          e.preventDefault();
          u.show('Canvas menu', {
            selected,
            group,
            remove
          });
        }}>
    <CanvasContext.Provider value={{renderNode, openNode}}>
     <RF.ReactFlow nodes={flowNodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
       viewport={{x: pan.x, y: pan.y, zoom}} onViewportChange={v => updateView({zoom: v.zoom, pan: {x: v.x, y: v.y}})} minZoom={zoomMin} maxZoom={zoomMax}
       onNodesChange={onNodesChange} onNodeDragStop={onNodeDragStop} onNodeDoubleClick={(e, f) => openNode(f.data.n)}
       onConnect={c => connect({id: c.source, port: c.sourceHandle}, {id: c.target, port: c.targetHandle})}
       onConnectEnd={(e, state) => {
         // A wire dropped on empty canvas offers the nodes that can take it (spec Compatible nodes).
         if (!state || state.isValid || state.toHandle || !state.fromHandle || e.target.closest?.('.react-flow__node')) return;
         u.show('Compatible nodes', {endpoint: {id: state.fromNode.id, side: state.fromHandle.type === 'source' ? 'out' : 'in', port: state.fromHandle.id}, position: toFlow(e)});
       }}
       onEdgeClick={(e, edge) => { if (edge.id !== 'rejected') { setWireId(edge.id); setSelected([]); } }}
       onPaneClick={() => { setWireId(null); setRejected(null); }}
       selectionOnDrag panOnDrag={[1]} panActivationKeyCode="Space" multiSelectionKeyCode="Shift" selectionKeyCode={null} deleteKeyCode={null}
       zoomOnDoubleClick={false} connectionLineStyle={{stroke: A.cyan, strokeWidth: 2}} proOptions={{hideAttribution: true}} />
    </CanvasContext.Provider>
    <div data-canvas-overlay="" className="canvas-toolbar"><Btn variant="controls" sm ghost aria-label="Zoom out" onClick={event => executeAction("projects.ds_screens.ZoomOut.20", {zoomAt,view}, event)}>−</Btn><button className="button-reset" onClick={event => executeAction("projects.ds_screens.ResetZoom.21", {zoomAt}, event)} title="Reset zoom">{Math.round(zoom * 100)}%</button><Btn variant="controls" sm ghost aria-label="Zoom in" onClick={event => executeAction("projects.ds_screens.ZoomIn.22", {zoomAt,view}, event)}>+</Btn><Btn variant="controls" sm ghost onClick={event => executeAction("projects.ds_screens.Fit.23", {fit}, event)}>Fit</Btn></div>
   </div>
   {inspected && <NodeInspector n={inspected} s={s} u={u} />}
   {wire && <aside className="pane inspector" style={{borderLeft:'1px solid '+A.line,padding:16}} aria-label="Wire">
     <div className="spread"><h2>Wire</h2><Btn variant="controls" sm ghost aria-label="Close wire" onClick={event=>executeAction('projects.controls.activate',{handler:()=>setWireId(null)},event)}>×</Btn></div>
     <div className="grid" style={{marginTop:16}}><div className="flex">{['Rules','Data'].map(t=><button className="tab-button" key={t} aria-pressed={wireTab===t} onClick={event=>executeAction('projects.ds_screens.SetTabT.27',{setTab:setWireTab,t},event)}>{t}</button>)}</div>
       <label className="grid">Pass when<input aria-label="Wire rule" value={wire.rule || ''} onChange={e=>u.act(()=>api.setWireRule(wire.id,e.target.value))} /></label>
       {(() => {
         // Wire inspection (Dynamo/Grasshopper parity): its type, both sockets and the value it carries now.
         const a = s.graph.nodes.find(n => n.id === wire.from), b = s.graph.nodes.find(n => n.id === wire.to),
           out = a?.outputs.find(p => p.id === wire.fromPort), into = b?.inputs.find(p => p.id === wire.toPort),
           value = a?.status === 'Done' ? (a.output && typeof a.output === 'object' && !Array.isArray(a.output) && wire.fromPort in a.output ? a.output[wire.fromPort] : a.output) : undefined;
         return <dl data-wire-inspection="" style={{display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '6px 12px', fontSize: 13, margin: 0}}>
           <dt className="muted">Type</dt><dd style={{margin: 0}}>{out ? typeName(out) : wire.type}{into && out && into.type !== out.type ? ' → ' + typeName(into) : ''}</dd>
           <dt className="muted">From</dt><dd style={{margin: 0}}>{a?.title || wire.from} · {out?.name || wire.fromPort}</dd>
           <dt className="muted">To</dt><dd style={{margin: 0}}>{b?.title || wire.to} · {into?.name || wire.toPort}</dd>
           <dt className="muted">Value</dt><dd style={{margin: 0, overflowWrap: 'anywhere'}}>{value === undefined ? 'Not run yet' : summary(value) || 'empty'}</dd>
         </dl>;
       })()}
       <Btn variant="controls" danger sm onClick={event=>executeAction('projects.ds_screens.DeleteWire.28',{api,u,wire},event)}>Delete wire…</Btn>
     </div></aside>}

  </div>
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
            renderPort={(p,i,side)=><div className="canvas-port-row" style={{position:'relative',height:22,display:'flex',alignItems:'center',justifyContent:side==='out'?'flex-end':undefined,padding:'0 12px',fontSize:12}}><span data-port-key={`${n.id}:${side}:${p.id}`} style={{position:'absolute',[side==='in'?'left':'right']:-6}}><D.Socket t={p.type} list={p.list} /></span>{p.name}{p.unit ? ' · '+p.unit : ''}</div>} />
        </div>)}
      </div></section>)}</div>}
    </div>;
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
