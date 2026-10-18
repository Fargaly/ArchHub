// ONE studio component source. Visual values ported from inputs/ds.jsx,
// ds_ctrl.jsx (§4.7/4.8), ds_node.jsx and ds_settings3.jsx. No application state.
(() => {
  const A = window.AH;
  const TYPE = { elements:'accent', number:'warn', text:'inkSoft', boolean:'purple',
    event:'cyan', file:'ok', any:'inkSoft', view:'cyan' };
  const button = (kind = 'secondary', sm = false, variant = 'controls') => {
    const setting = variant === 'settings';
    if (variant === 'workshop') return {display:'inline-flex',alignItems:'center',gap:7,height:sm?30:36,padding:sm?'0 12px':'0 16px',borderRadius:8,
      fontFamily:A.sans,fontSize:sm?13:14,fontWeight:600,cursor:'pointer',background:kind==='primary'?`linear-gradient(180deg, ${A.accentHi || A.accent}, ${A.accent})`:A.workshop.buttonBackground,
      color:kind==='primary'?'#fff':A.ink,boxShadow:kind==='primary'?`0 1px 0 rgba(255,255,255,.25) inset, 0 4px 14px ${A.accent}44`:'0 1px 0 rgba(255,255,255,.06) inset',border:kind==='primary'?0:`1px solid ${A.line}`};
    const palette = {
      primary:[A.accent, setting ? '#fff' : A.onFill, A.accent], secondary:[setting ? '#26262d' : A.bgHover, A.ink, A.line],
      ghost:['transparent', setting ? A.inkSoft : A.ink, 'transparent'], danger:['transparent', A.err, 'transparent']
    }[kind] || [A.bgHover, A.ink, A.line];
    return { display:'inline-flex', alignItems:'center', justifyContent:'center', gap:6,
      height:setting ? (sm ? 30 : 34) : (sm ? 26 : 32), padding:sm && !setting ? '0 10px' : '0 14px',
      boxSizing:'border-box', borderRadius:setting ? 8 : (A.rad?.sm ?? 5), font:`${setting ? 600 : 500} 13px ${A.sans}`,
      whiteSpace:'nowrap', background:palette[0], color:palette[1],
      border:setting && (kind === 'primary' || kind === 'ghost') ? 0 : `1px solid ${palette[2]}` };
  };
  const styles = Object.freeze({ button, workshopButton:(primary, small) => button(primary?'primary':'secondary',small,'workshop'), flex:{ display:'flex', alignItems:'center', gap:8 },
    fill:{ flex:1 }, get muted() { return { color:A.inkSoft }; } });

  // Native buttons supply Enter/Space, disabled semantics and form behaviour.
  const Btn = React.forwardRef(function Btn({ children, kind = 'secondary', primary, sm, disabled, dis, icon, loading,
    variant = 'controls', style, type = 'button', onFocus, onBlur, onMouseEnter, onMouseLeave,
    onPointerDown, onPointerUp, ...props }, ref) {
    const [state, setState] = React.useState('default');
    const [focus, setFocus] = React.useState(false);
    const k = primary ? 'primary' : kind;
    const off = !!(disabled || dis);
    const base = button(k, sm, variant);
    const bg = state === 'pressed' ? (k === 'primary' ? A.accentPress : A.bgSoft)
      : state === 'hover' ? (k === 'primary' ? A.accentHi : k === 'secondary' ? '#2a2a33' : A.bgHover) : base.background;
    return <button {...props} ref={ref} type={type} disabled={off} aria-busy={loading || undefined}
      onFocus={e => { setFocus(true); onFocus?.(e); }}
      onBlur={e => { setFocus(false); setState('default'); onBlur?.(e); }}
      onMouseEnter={e => { setState('hover'); onMouseEnter?.(e); }}
      onMouseLeave={e => { setState('default'); onMouseLeave?.(e); }}
      onPointerDown={e => { setState('pressed'); onPointerDown?.(e); }}
      onPointerUp={e => { setState('hover'); onPointerUp?.(e); }}
      style={{ ...base, cursor:off ? 'default' : 'pointer', background:bg,
        boxShadow:focus ? `0 0 0 2px ${A.bgDeep}, 0 0 0 4px ${A.accent}` : 'none',
        transform:state === 'pressed' && !off ? 'translateY(1px)' : 'none',
        ...(icon ? { minWidth:sm ? 26 : 32, padding:0 } : {}), ...style,
        ...(off && variant !== 'workshop' ? { border:`1px dashed ${A.line}`, color:A.inkSoft, background:'transparent' } : {}) }}>
      {loading && <span aria-hidden="true" style={{ width:12, height:12, borderRadius:'50%', border:`2px solid ${base.color}`, borderRightColor:'transparent', display:'inline-block' }}/>}
      {icon || children}
    </button>;
  });

  function Toggle({ checked, on, disabled, off, onCheckedChange, onChange, onClick, label, title,
    variant = 'controls', style, ...props }) {
    const value = !!(checked ?? on);
    const dis = !!(disabled || off);
    const setting = variant === 'settings';
    return <button {...props} type="button" role="switch" aria-checked={value}
      aria-label={props['aria-label'] || label || title} title={title || label} disabled={dis}
      onClick={e => { onCheckedChange?.(!value); onChange?.(!value); onClick?.(e); }}
      style={{ width:setting ? 34 : 30, height:setting ? 20 : 18, borderRadius:999, padding:0,
        background:setting ? (dis ? '#1d1d22' : value ? A.accent : '#33333b') : value ? A.accent : A.bgHover,
        border:dis ? `1px dashed ${A.line}` : setting ? 0 : `1px solid ${value ? A.accent : A.line}`,
        position:'relative', display:'inline-block', boxSizing:'border-box', flexShrink:0,
        cursor:dis ? 'default' : 'pointer', opacity:dis ? (setting ? .6 : .5) : 1, ...style }}>
      <i aria-hidden="true" style={{ position:'absolute', top:setting ? 3 : 2, left:value ? (setting ? 17 : 14) : (setting ? 3 : 2),
        width:setting ? 14 : 12, height:setting ? 14 : 12, borderRadius:'50%',
        background:setting ? (dis ? A.inkSoft : '#fff') : value ? A.onFill : A.inkSoft }}/>
    </button>;
  }

  function Row({ k, label, children, changed, hint, onReset, style, raw = false, rowRef, ...props }) {
    return <div ref={rowRef} {...props} style={{ display:'grid', gridTemplateColumns:'96px 1fr auto', alignItems:'center', gap:8,
      minHeight:32, padding:'0 12px', borderTop:`1px solid ${A.lineSoft}`, ...style }}>
      {raw ? children : <><span style={{ fontSize:13, color:A.inkSoft, display:'flex', alignItems:'center', gap:6 }}>
        {changed && <i aria-hidden="true" style={{ width:6, height:6, borderRadius:'50%', background:A.accent, display:'inline-block' }}/>}{label ?? k}</span>
      <div style={{ display:'grid', gap:2, padding:'4px 0' }}>{children}{hint && <span style={{ fontSize:11, color:A.inkSoft }}>{hint}</span>}</div>
      {changed ? <Btn sm kind="ghost" onClick={onReset} disabled={!onReset} style={{ fontSize:12, color:A.inkSoft, textDecoration:'underline' }}>Reset</Btn> : <span/>}</>}
    </div>;
  }

  function Socket({ t = 'elements', type, list, filled, size = 10, hit, style, ...props }) {
    const dataType = type || t;
    const c = A[TYPE[dataType] || 'inkSoft'];
    const shape = dataType === 'event' && !list
      ? <svg width={size + 2} height={size + 2} style={{ display:'block', ...style }}><path d={`M1 1 L${size + 1} ${size / 2 + 1} L1 ${size + 1} Z`} fill={filled ? c : A.bgPanel} stroke={c} strokeWidth="2" strokeLinejoin="round"/></svg>
      : <span style={{ display:'block', width:size, height:size, boxSizing:'border-box',
        background:dataType === 'any' ? undefined : filled ? c : A.bgPanel,
        border:`2px ${dataType === 'any' ? 'dashed' : 'solid'} ${c}`,
        borderRadius:dataType !== 'any' && list ? 2 : '50%',
        transform:dataType !== 'any' && list ? 'rotate(45deg) scale(.86)' : 'none', ...style }}/>;
    return <span data-ds-socket="" {...props} title={props.title || `${dataType}${list ? ' list' : ''}`} role={props.role || 'img'}
      aria-label={props['aria-label'] || `${dataType}${list ? ' list' : ''}${filled ? ', wired' : ', unwired'}`}
      style={hit ? { display:'inline-grid', placeItems:'center', width:20, height:20 } : { display:'inline-block' }}>{shape}</span>;
  }

  const Node = React.forwardRef(function Node({ glyph, gc, title, sub, ins = [], outs = [], foot, footc, chip, sel, selected, run,
    w = 224, edge, dashed, children, style, bandRef, nodeRef, onHeaderMouseDown, headerExtra, headerEnd, headerProps, subtitleProps, stacked, portBand, renderPort, portsAfterContent = false, ...props }, forwardedRef) {
    const band = Math.max(ins.length, outs.length) > 0 && <div ref={bandRef} data-port-band="" style={{position:'relative',display:'grid',gridTemplateColumns:'1fr 1fr',height:renderPort ? Math.max(ins.length,outs.length)*22+8 : undefined,boxSizing:'border-box',borderTop:`1px solid ${A.line}`,padding:'4px 0'}}>
      {[['in',ins],['out',outs]].map(([side,ports])=><div key={side}>{ports.map((p,i)=>renderPort ? <React.Fragment key={p.id || p.l}>{renderPort(p,i,side)}</React.Fragment> :
        <div key={p.id || p.l} style={{position:'relative',height:22,display:'flex',alignItems:'center',justifyContent:side==='out'?'flex-end':undefined,padding:'0 12px',fontSize:12}}>
          <span style={{position:'absolute',[side==='in'?'left':'right']:-11,top:1}}><Socket {...p.socketProps} t={p.t} list={p.list} filled={p.f} hit aria-label={`Connect ${side==='in'?'input':'output'} ${p.l}`} title={`Connect ${side==='in'?'input':'output'} ${p.l}`} role={p.onUse?'button':undefined} tabIndex={p.onUse?0:undefined} onClick={p.onUse} onMouseDown={e=>e.stopPropagation()} onKeyDown={e=>{if(p.onUse&&(e.key==='Enter'||e.key===' ')){e.preventDefault();p.onUse(e);}}} onPointerDown={p.onDragStart}/></span>{p.l}</div>)}</div>)}
    </div>;
    return <div ref={nodeRef || forwardedRef} data-ds-node="" {...props} style={{ position:'relative', width:w, background:A.bgPanel,
      border:`1px ${dashed ? 'dashed' : 'solid'} ${A.line}`, borderRadius:6,
      borderLeft:edge === 'l' ? `4px solid ${gc}` : undefined, borderRight:edge === 'r' ? `4px solid ${gc}` : undefined,
      outline:sel || selected ? `2px solid ${A.accent}` : 'none', outlineColor:sel || selected ? A.accent : undefined, outlineOffset:2,
      boxShadow:run ? `0 0 0 1px ${A.accent}` : 'none', ...style }}>
      {stacked && [5,10].map((offset,i)=><span key={offset} data-stacked-edge={i+1} style={{position:'absolute',inset:0,transform:`translate(${offset}px,${offset}px)`,border:`1px solid ${A.line}`,borderRadius:6,background:A.bgPanel,opacity:i?.6:1,zIndex:-1-i,pointerEvents:'none'}}/>)}
      <div {...headerProps} onMouseDown={headerProps?.onMouseDown || onHeaderMouseDown} style={{ display:'flex', alignItems:'center', gap:8, padding:'7px 10px',...headerProps?.style }}>
        <span data-category-tile="" aria-hidden="true" style={{ width:20, height:20, borderRadius:5, background:gc, color:A.onFill,
          display:'grid', placeItems:'center', font:`600 12px ${A.sans}`, flex:'none' }}>{glyph}</span>
        <div style={{ minWidth:0, flex:1 }}><div data-node-card-title="" title={typeof title==='string'?title:undefined} style={{ fontSize:13, fontWeight:600, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis' }}>{title}</div>
          <div {...subtitleProps} data-node-card-subtitle="" style={{ fontSize:11, color:A.inkSoft, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis' }}>{sub}</div></div>
        {headerExtra || headerEnd}
        <span aria-hidden="true" style={{ width:8, height:8, borderRadius:'50%', background:footc || A.inkSoft, flex:'none' }}/>
      </div>
      {portBand || (!portsAfterContent && band)}{children}{chip && <div style={{ padding:'0 10px 6px' }}>{chip}</div>}{portsAfterContent && band}
      <div data-node-footer-status="" style={{ borderTop:`1px solid ${A.line}`, padding:'5px 10px', fontSize:11, color:footc || A.inkSoft }}>{foot}</div>
    </div>;
  });

  function Card({ title, children, style, variant, as:Tag = 'div', ...props }) {
    if (title !== undefined) return <Node {...props} title={title} style={style}>{children}</Node>;
    return <Tag data-ds-card="" {...props} style={{ background:['settings','home'].includes(variant) ? 'linear-gradient(180deg, #1c1c22 0%, #17171c 100%)' : A.bgPanel,
      border:`1px solid ${A.line}`, borderRadius:variant === 'settings' ? 14 : variant==='home'?12:6,
      ...(['settings','home'].includes(variant) ? { boxShadow:'0 1px 0 rgba(255,255,255,.04) inset, 0 1px 2px rgba(0,0,0,.4)' } : {}),
      overflow:'hidden', ...style }}>{children}</Tag>;
  }

  function Rail({ children, g, glyph, l, label, on, active, badge, variant, as:Tag = 'nav', style, ...props }) {
    const text = label ?? l;
    const selected = active ?? on;
    if (text === undefined) return <Tag {...props} style={{ background:A.bg, borderRight:`1px solid ${A.lineSoft}`,
      display:'grid', gridTemplateRows:'auto 1fr auto', paddingTop:6, width:44, ...style }}>{children}</Tag>;
    return <button {...props} type="button" title={props.title || text} aria-label={props['aria-label'] || text}
      aria-current={selected ? (props['aria-current'] ?? 'page') : undefined} style={{ width:44, height:52, display:'grid', placeItems:'center', alignContent:'center',
        gap:2, position:'relative', color:selected ? A.ink : A.inkSoft, border:0, padding:0, background:'transparent', fontFamily:A.sans, cursor:'pointer', ...style }}>
      {selected && variant!=='home' && <i aria-hidden="true" style={{ position:'absolute', left:0, top:12, bottom:12, width:2, background:A.accent, borderRadius:2 }}/>}
      <span aria-hidden="true" style={{ width:variant==='home'?36:28, height:variant==='home'?30:28, borderRadius:variant==='home'?8:6, display:'grid', placeItems:'center', background:selected ? A.bgHover : 'transparent', fontSize:15 }}>{glyph ?? g}</span>
      <span style={{ fontSize:11, lineHeight:'13px' }}>{text}</span>
      {badge && <span style={{ position:'absolute', right:6, top:6, minWidth:14, height:14, borderRadius:7, background:A.warn,
        color:A.onFill, fontSize:10, fontWeight:600, display:'grid', placeItems:'center' }}>{badge}</span>}{children}
    </button>;
  }

  // Plate composer shell; caller owns inputs, submit handlers and conversation state.
  function Composer({ children, as:Tag = 'div', w, variant, style, ...props }) {
    return <Tag data-ds-composer="" {...props} style={{ width:w, margin:'0 auto', border:`1px solid ${A.line}`, borderRadius:10,
      background:variant==='home'?'linear-gradient(180deg, #202027 0%, #1a1a20 100%)':A.bgPanel, padding:'12px 14px', display:'grid', gap:10, ...(variant==='home'?{borderRadius:14,boxShadow:'0 1px 0 rgba(255,255,255,.05) inset, 0 8px 24px rgba(0,0,0,.45)'}:{}), ...style }}>{children}</Tag>;
  }

  function EmptyState({ glyph = '◌', title = 'Nothing here yet', detail, children, action, onRetry,
    retryLabel = 'Retry', error, compact, style, ...props }) {
    return <div {...props} role={error ? 'alert' : 'status'} style={{ display:'grid', alignContent:'center',
      justifyItems:compact ? 'start' : 'center', gap:compact ? 8 : 18, padding:compact ? 12 : 24,
      ...(compact ? {border:`1px dashed ${A.line}`,borderRadius:8} : {}), color:A.ink, fontFamily:A.sans, textAlign:compact ? 'left' : 'center', ...style }}>
      {glyph && <span aria-hidden="true" style={{ fontSize:32, color:error ? A.err : A.inkSoft }}>{glyph}</span>}
      <div style={{ fontSize:compact ? 13 : 22, fontWeight:compact ? 400 : 600 }}>{error && title ? errorText(title) : title}</div>
      {detail && <div style={{ fontSize:13, color:A.inkSoft, lineHeight:'20px' }}>{error ? errorText(detail) : detail}</div>}
      {children}{action || (onRetry && <Btn onClick={onRetry}>{retryLabel}</Btn>)}
    </div>;
  }

  const TextField = React.forwardRef(function TextField({multiline, style, ...props}, ref) {
    const Tag = multiline ? 'textarea' : 'input';
    return <Tag ref={ref} {...props} style={{minWidth:0,border:0,background:'transparent',color:A.ink,fontFamily:A.sans,fontSize:13,outline:'none',...style}}/>;
  });
  function Segmented({options,value,onChange,label}) {
    const name = React.useId(), [focused,setFocused] = React.useState(null);
    return <span role="radiogroup" aria-label={label} style={{display:'inline-flex',height:26,border:`1px solid ${A.line}`,borderRadius:5,overflow:'hidden'}}>{options.map(option=>{
      const v=Array.isArray(option)?option[0]:option,l=Array.isArray(option)?option[1]:option;
      return <label key={v} style={{position:'relative',display:'inline-flex',alignItems:'center',padding:'0 4px',fontSize:11,cursor:'pointer',outline:focused===v?`1px solid ${A.accent}`:undefined,outlineOffset:-2,background:value===v?A.accentSoft:'transparent',color:value===v?A.accentHi:A.inkSoft}}>
        <input type="radio" name={name} value={v} checked={value===v} onChange={()=>onChange(v)} onFocus={()=>setFocused(v)} onBlur={()=>setFocused(null)} aria-label={String(l)}
          style={{position:'absolute',inset:0,opacity:0,width:'100%',height:'100%',margin:0,cursor:'pointer'}}/>{l}</label>;
    })}</span>;
  }
  function Select(props) { return <select {...props}/>; }
  function Frame({as:Tag = 'div', style, children, ...props}) {
    return <Tag data-ds-frame="" {...props} style={{display:'grid',minHeight:0,overflow:'hidden',color:A.ink,fontFamily:A.sans,...style}}>{children}</Tag>;
  }
  function Avatar({agent, size = 28, ring, style, ...props}) {
    return <span data-workshop-avatar={agent?.id || ''} {...props} style={{position:'relative',width:size,height:size,flex:'none',display:'inline-block',...style}}>
      <i style={{position:'absolute',inset:0,borderRadius:size/3.5,background:`linear-gradient(180deg, ${agent?.col || A.purple}, ${agent?.col || A.purple}cc)`,color:'#fff',display:'grid',placeItems:'center',fontStyle:'normal',fontSize:Math.max(11,size*.44),fontWeight:700,boxShadow:'0 1px 0 rgba(255,255,255,.25) inset'}}>
        {agent?.ini || Array.from(String(agent?.name || '').trim())[0]?.toUpperCase() || '?'}</i>
      {ring && <i data-presence-ring="" style={{position:'absolute',inset:-3,borderRadius:size/3.5+3,border:`2px solid ${ring}`,boxShadow:`0 0 10px ${ring}66`}}/>}
    </span>;
  }
  const avatar = (agent, size, ring) => <Avatar agent={agent} size={size} ring={ring === undefined ? agent?.presence==='needs-user'?A.warn:agent?.presence==='working'?A.accent:null : ring}/>;
  const dot = color => <i style={{width:8,height:8,borderRadius:'50%',background:color,boxShadow:`0 0 8px ${color}aa`,display:'inline-block',flex:'none'}}/>;
  const chip = (label,color) => <span style={{display:'inline-flex',alignItems:'center',gap:6,height:24,padding:'0 9px',borderRadius:999,background:`${color}1f`,color,fontSize:12,fontWeight:600}}>{label}</span>;
  function SelectionHeader({glyph, color, title, subtitle}) {
    return <header style={{display:'flex',alignItems:'center',gap:8,padding:12,minHeight:56}}><i style={{width:20,height:20,borderRadius:4,background:color,color:A.onFill,display:'grid',placeItems:'center',fontStyle:'normal',flex:'none'}}>{glyph}</i><div><div style={{fontSize:14,fontWeight:600}}>{title}</div>{subtitle&&<div style={{fontSize:12,color:A.inkSoft}}>{subtitle}</div>}</div></header>;
  }
  // Plate 064 Properties anatomy; values and all effects remain owned by the existing inspector.
  function Properties({params = [], parameterRows, ports = [], preview, actions = {}, onExport, examples = [], error}) {
    const [format,setFormat] = React.useState('Table');
    const value = preview?.value;
    const rows = Array.isArray(value) ? value : Array.isArray(value?.rows) ? value.rows : [];
    const show = item => item == null ? '' : typeof item === 'object' ? JSON.stringify(item) : String(item);
    const section = {padding:12,display:'grid',gap:8,borderTop:`1px solid ${A.lineSoft}`};
    const cap = {fontSize:11,color:A.inkSoft,letterSpacing:'.04em',textTransform:'uppercase'};
    return <div data-library-properties="" style={{display:'grid',alignContent:'start'}}>
      {parameterRows}
      {!params.length && <EmptyState compact glyph={null} title="No parameters in this selection"/>}
      {['Pin output','Disable'].map((label,index)=>{const p=params.find(row=>row.k===(index?'disabled':'pin_output'));return !p && <Row key={label} label={label}><span style={{display:'flex',alignItems:'center',gap:8}}><Toggle label={label+' unavailable'} disabled/><span style={{fontSize:11,color:A.inkSoft}}>Unavailable</span></span></Row>;})}
      <div style={section}><span style={cap}>Ports</span>{ports.map(p=><span key={p.side+':'+p.id} style={{display:'flex',alignItems:'center',gap:8,fontSize:12}}>
        <Socket {...p.socketProps} t={p.t} list={p.list} filled={p.connected}/>{p.label || p.id} · {p.t || 'unknown'}{p.list?' list':''}</span>)}</div>
      <div style={section}><div style={{display:'flex',alignItems:'center',gap:8}}><span style={cap}>Output</span><span style={{flex:1}}/>
        {['Table','JSON'].map(f=><Btn key={f} sm kind="ghost" aria-pressed={format===f} onClick={()=>setFormat(f)} style={{padding:'0 7px',background:format===f?A.accentSoft:'transparent'}}>{f}</Btn>)}</div>
        <div style={{background:A.bgSoft,border:`1px solid ${A.lineSoft}`,borderRadius:5,padding:'6px 8px',font:`400 11px/17px ${A.mono}`,color:A.inkSoft}}>
          {value == null ? 'Output unavailable. Run this node to read its result.' : format==='JSON' ? <pre style={{margin:0,whiteSpace:'pre-wrap'}}>{JSON.stringify(value,null,2)}</pre> : rows.slice(0,3).map((r,i)=><div key={i}>{typeof r==='object'&&r!==null?Object.values(r).map(show).join(' · '):show(r)}</div>)}
          {rows.length>3&&<div>+ {rows.length-3} more rows</div>}</div>
        <div style={{display:'flex',gap:6,flexWrap:'wrap'}}><Btn sm disabled={!actions.runToHere} onClick={actions.runToHere} title={actions.runToHere?'Run to here':'Node execution unavailable'}>Run to here</Btn>
          <Btn sm kind="ghost" disabled={!actions.showInRevit} onClick={actions.showInRevit}>Show in Revit</Btn><Btn sm kind="ghost" disabled={value==null || !onExport} onClick={onExport}>Export CSV</Btn></div>
      </div>
      <div style={section}><span style={cap}>Last run</span><span style={{fontSize:12}}>{preview?.executed_at || preview?.last_run || 'Unavailable'}</span></div>
      <div style={section}><span style={cap}>Examples</span>{examples.length ? examples.map(e=><Btn key={e.id || e.label} sm disabled={!e.run} onClick={e.run}>{e.label}</Btn>) : <span style={{fontSize:12,color:A.inkSoft}}>No examples in this catalogue entry.</span>}</div>
      {error && <EmptyState compact glyph={null} error title="Could not save" detail={error} onRetry={actions.retry}/>}
    </div>;
  }
  const errorText = value => {
    const text = String(value || 'The request could not be completed.');
    if (/relation root is missing/i.test(text)) return 'The selection changed. Select the nodes again and retry.';
    if (/127\.0\.0\.1|AppData[\\/]|%TEMP%|[A-Z]:[\\/]|\/(?:var\/)?tmp\/|\/(?:private\/)?var\/folders\/|\b(?:accent_dim|l_bg\w*|bgPanel|bgCanvas|inkSoft|onFill)\b/i.test(text))
      return 'The application could not complete this request. Refresh the view and retry.';
    return text.replace(/not available yet/gi, 'Unavailable');
  };
  window.AH_DS = Object.freeze({ errorText, Btn, Toggle, Row, Card, Rail, Node, Socket, Composer, EmptyState, TextField, Select, Segmented, Frame, Avatar, Properties, SelectionHeader, avatar, dot, chip, styles });
})();
