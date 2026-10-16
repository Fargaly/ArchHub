// ONE studio component source. Visual values ported from inputs/ds.jsx,
// ds_ctrl.jsx (§4.7/4.8), ds_node.jsx and ds_settings3.jsx. No application state.
(() => {
  const A = window.AH;
  const TYPE = { elements:'accent', number:'warn', text:'inkSoft', boolean:'purple',
    event:'cyan', file:'ok', any:'inkSoft', view:'cyan' };
  const button = (kind = 'secondary', sm = false, variant = 'controls') => {
    const setting = variant === 'settings';
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
  const styles = Object.freeze({ button, flex:{ display:'flex', alignItems:'center', gap:8 },
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
        ...(off ? { border:`1px dashed ${A.line}`, color:A.inkSoft, background:'transparent' } : {}) }}>
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

  function Row({ k, label, children, changed, hint, onReset, style, ...props }) {
    return <div {...props} style={{ display:'grid', gridTemplateColumns:'96px 1fr auto', alignItems:'center', gap:8,
      minHeight:32, padding:'0 12px', borderTop:`1px solid ${A.lineSoft}`, ...style }}>
      <span style={{ fontSize:13, color:A.inkSoft, display:'flex', alignItems:'center', gap:6 }}>
        {changed && <i aria-hidden="true" style={{ width:6, height:6, borderRadius:'50%', background:A.accent, display:'inline-block' }}/>}{label ?? k}</span>
      <div style={{ display:'grid', gap:2, padding:'4px 0' }}>{children}{hint && <span style={{ fontSize:11, color:A.inkSoft }}>{hint}</span>}</div>
      {changed ? <Btn sm kind="ghost" onClick={onReset} disabled={!onReset} style={{ fontSize:12, color:A.inkSoft, textDecoration:'underline' }}>Reset</Btn> : <span/>}
    </div>;
  }

  function Socket({ t = 'elements', type, list, filled, size = 10, hit, style, ...props }) {
    const dataType = type || t;
    const c = A[TYPE[dataType] || 'inkSoft'];
    const shape = dataType === 'event'
      ? <svg width={size + 2} height={size + 2} style={{ display:'block', ...style }}><path d={`M1 1 L${size + 1} ${size / 2 + 1} L1 ${size + 1} Z`} fill={filled ? c : A.bgPanel} stroke={c} strokeWidth="2" strokeLinejoin="round"/></svg>
      : <span style={{ display:'block', width:size, height:size, boxSizing:'border-box',
        background:dataType === 'any' ? undefined : filled ? c : A.bgPanel,
        border:`2px ${dataType === 'any' ? 'dashed' : 'solid'} ${c}`,
        borderRadius:dataType !== 'any' && list ? 2 : '50%',
        transform:dataType !== 'any' && list ? 'rotate(45deg) scale(.86)' : 'none', ...style }}/>;
    return <span {...props} title={props.title || `${dataType}${list ? ' list' : ''}`} role={props.role || 'img'}
      aria-label={props['aria-label'] || `${dataType}${list ? ' list' : ''}${filled ? ', wired' : ', unwired'}`}
      style={hit ? { display:'inline-grid', placeItems:'center', width:20, height:20 } : { display:'inline-block' }}>{shape}</span>;
  }

  function Node({ glyph, gc, title, sub, ins = [], outs = [], foot, footc, chip, sel, selected, run,
    w = 224, edge, dashed, children, style, ...props }) {
    return <div {...props} style={{ position:'relative', width:w, background:A.bgPanel,
      border:`1px ${dashed ? 'dashed' : 'solid'} ${A.line}`, borderRadius:6,
      borderLeft:edge === 'l' ? `4px solid ${gc}` : undefined, borderRight:edge === 'r' ? `4px solid ${gc}` : undefined,
      outline:sel || selected ? `2px solid ${A.accent}` : 'none', outlineOffset:2,
      boxShadow:run ? `0 0 0 1px ${A.accent}` : 'none', ...style }}>
      <div style={{ display:'flex', alignItems:'center', gap:8, padding:'7px 10px' }}>
        <span aria-hidden="true" style={{ width:20, height:20, borderRadius:5, background:gc, color:A.onFill,
          display:'grid', placeItems:'center', font:`600 12px ${A.sans}`, flex:'none' }}>{glyph}</span>
        <div style={{ minWidth:0, flex:1 }}><div style={{ fontSize:13, fontWeight:600, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis' }}>{title}</div>
          <div style={{ fontSize:11, color:A.inkSoft, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis' }}>{sub}</div></div>
        <span aria-hidden="true" style={{ width:8, height:8, borderRadius:'50%', background:footc || A.inkSoft, flex:'none' }}/>
      </div>
      {Math.max(ins.length, outs.length) > 0 && <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', borderTop:`1px solid ${A.line}`, padding:'4px 0' }}>
        <div>{ins.map(p => <div key={p.l} style={{ position:'relative', height:22, display:'flex', alignItems:'center', padding:'0 12px', fontSize:12 }}>
          <span style={{ position:'absolute', left:-11, top:1 }}><Socket t={p.t} list={p.list} filled={p.f} hit/></span>{p.l}</div>)}</div>
        <div>{outs.map(p => <div key={p.l} style={{ position:'relative', height:22, display:'flex', alignItems:'center', justifyContent:'flex-end', padding:'0 12px', fontSize:12 }}>
          {p.l}<span style={{ position:'absolute', right:-11, top:1 }}><Socket t={p.t} list={p.list} filled={p.f} hit/></span></div>)}</div>
      </div>}
      {children}{chip && <div style={{ padding:'0 10px 6px' }}>{chip}</div>}
      <div style={{ borderTop:`1px solid ${A.line}`, padding:'5px 10px', fontSize:11, color:footc || A.inkSoft }}>{foot}</div>
    </div>;
  }

  function Card({ title, children, style, variant, ...props }) {
    if (title !== undefined) return <Node {...props} title={title} style={style}>{children}</Node>;
    return <div {...props} style={{ background:variant === 'settings' ? 'linear-gradient(180deg, #1c1c22 0%, #17171c 100%)' : A.bgPanel,
      border:`1px solid ${A.line}`, borderRadius:variant === 'settings' ? 14 : 6,
      ...(variant === 'settings' ? { boxShadow:'0 1px 0 rgba(255,255,255,.04) inset, 0 1px 2px rgba(0,0,0,.4)' } : {}),
      overflow:'hidden', ...style }}>{children}</div>;
  }

  function Rail({ children, g, glyph, l, label, on, active, badge, as:Tag = 'nav', style, ...props }) {
    const text = label ?? l;
    const selected = active ?? on;
    if (text === undefined) return <Tag {...props} style={{ background:A.bg, borderRight:`1px solid ${A.lineSoft}`,
      display:'grid', gridTemplateRows:'auto 1fr auto', paddingTop:6, width:44, ...style }}>{children}</Tag>;
    return <button {...props} type="button" title={props.title || text} aria-label={props['aria-label'] || text}
      aria-current={selected ? 'page' : undefined} style={{ width:44, height:52, display:'grid', placeItems:'center', alignContent:'center',
        gap:2, position:'relative', color:selected ? A.ink : A.inkSoft, border:0, padding:0, background:'transparent', fontFamily:A.sans, cursor:'pointer', ...style }}>
      {selected && <i aria-hidden="true" style={{ position:'absolute', left:0, top:12, bottom:12, width:2, background:A.accent, borderRadius:2 }}/>}
      <span aria-hidden="true" style={{ width:28, height:28, borderRadius:6, display:'grid', placeItems:'center', background:selected ? A.bgHover : 'transparent', fontSize:15 }}>{glyph ?? g}</span>
      <span style={{ fontSize:11, lineHeight:'13px' }}>{text}</span>
      {badge && <span style={{ position:'absolute', right:6, top:6, minWidth:14, height:14, borderRadius:7, background:A.warn,
        color:A.onFill, fontSize:10, fontWeight:600, display:'grid', placeItems:'center' }}>{badge}</span>}{children}
    </button>;
  }

  // Plate composer shell; caller owns inputs, submit handlers and conversation state.
  function Composer({ children, as:Tag = 'div', w, style, ...props }) {
    return <Tag {...props} style={{ width:w, margin:'0 auto', border:`1px solid ${A.line}`, borderRadius:10,
      background:A.bgPanel, padding:'12px 14px', display:'grid', gap:10, ...style }}>{children}</Tag>;
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

  const errorText = value => {
    const text = String(value || 'The request could not be completed.');
    if (/relation root is missing/i.test(text)) return 'The selection changed. Select the nodes again and retry.';
    if (/127\.0\.0\.1|AppData[\\/]|%TEMP%|[A-Z]:[\\/]|\/(?:var\/)?tmp\/|\/(?:private\/)?var\/folders\/|\b(?:accent_dim|l_bg\w*|bgPanel|bgCanvas|inkSoft|onFill)\b/i.test(text))
      return 'The application could not complete this request. Refresh the view and retry.';
    return text.replace(/not available yet/gi, 'Unavailable');
  };
  window.AH_DS = Object.freeze({ errorText, Btn, Toggle, Row, Card, Rail, Node, Socket, Composer, EmptyState, styles });
})();
