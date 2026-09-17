// cockpit-core.jsx — ARCHHUB FOUNDER COCKPIT · operate mode.
// NOT god mode (ADGR-0003): the cockpit is the founder's own personal brain plus operator
// permissions over the platform. It never reads inside another brain; per office it sees a size in MB.
// Persistence and UI atoms. No seed databases: the cockpit draws what the running
// application pushes, and absent data is drawn as absent.
// Derives 100% of its palette from window.AH (tokens.jsx) — no hardcoded hexes.
// The control surface is editable at runtime; what it SHOWS comes from the app.

const CK = window.AH;
const CKLS = 'archhub.cockpit.v1';

/* ════════════════ persistence ════════════════ */
const ckLoad = () => { try { const s = JSON.parse(localStorage.getItem(CKLS)); if (s && s._v === 1) return s; } catch (e) {} return null; };
const ckSave = (db) => { try { localStorage.setItem(CKLS, JSON.stringify({ ...db, _v: 1 })); } catch (e) {} };
const uid = (p = 'id') => p + '_' + Math.random().toString(36).slice(2, 8);

/* ════════════════ the cockpit's collections ════════════════ */
// No seed databases. Every collection starts empty and is filled by what the
// founder's running application pushes, so a collection nobody has filled draws
// as absent instead of as invented firms, users or revenue (audit 2026-09-07).
// ADGR-0003: an operator reads a size per office, never memories, tokens or
// contents, and no brain is "global" or "sees everything".
const EMPTY_DB = () => ({
  firms: [], users: [], brains: [], models: [],
  skills: [], connectors: [], issues: [],
  roadmap: [], agents: [], activity: [],
  metrics: null, flags: [],
  beat: 1,            // founder-controlled tempo
});

/* ════════════════ status colour map ════════════════ */
const STAT = {
  green: CK.ok, amber: CK.warn, red: CK.err,
  healthy: CK.ok, healing: CK.warn, degraded: CK.err, idle: CK.inkMuted,
  active: CK.ok, suspended: CK.err, invited: CK.warn,
  working: CK.ok, paused: CK.warn, error: CK.err, warn: CK.warn, info: CK.cyan,
  open: CK.err, investigating: CK.warn, triaged: CK.cyan, resolved: CK.ok,
  primary: CK.accent, enabled: CK.ok, local: CK.cyan, disabled: CK.inkMuted,
  published: CK.ok, flagged: CK.err, review: CK.warn,
  now: CK.accent, next: CK.cyan, later: CK.purple, shipped: CK.ok,
  ga: CK.ok, beta: CK.cyan, internal: CK.purple, off: CK.inkMuted,
};
const sc = (k) => STAT[k] || CK.inkMuted;

/* ════════════════ ICONS (inline, no deps) ════════════════ */
const CKIcon = ({ name, size = 16, color = 'currentColor', sw = 1.6 }) => {
  const p = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: color, strokeWidth: sw, strokeLinecap: 'round', strokeLinejoin: 'round' };
  switch (name) {
    case 'pulse':   return <svg {...p}><path d="M3 12h4l2-6 4 12 2-6h6"/></svg>;
    case 'db':      return <svg {...p}><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/></svg>;
    case 'agent':   return <svg {...p}><rect x="4" y="8" width="16" height="11" rx="2"/><path d="M12 4v4M9 14h.01M15 14h.01M2 13v3M22 13v3"/></svg>;
    case 'map':     return <svg {...p}><path d="m9 4 6 2 5-2v15l-5 2-6-2-5 2V4l5-2Z"/><path d="M9 2v18M15 4v18"/></svg>;
    case 'bug':     return <svg {...p}><rect x="8" y="6" width="8" height="13" rx="4"/><path d="M8 10H3M21 10h-5M8 14H4M20 14h-4M9 6 7 3M15 6l2-3"/></svg>;
    case 'layout':  return <svg {...p}><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>;
    case 'model':   return <svg {...p}><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/></svg>;
    case 'brain':   return <svg {...p}><path d="M9 3a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 1 5 3 3 0 0 0 6 1V4a3 3 0 0 0-2-1ZM15 3a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-1 5 3 3 0 0 1-6 1"/></svg>;
    case 'flag':    return <svg {...p}><path d="M4 21V4M4 4h13l-2 4 2 4H4"/></svg>;
    case 'search':  return <svg {...p}><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>;
    case 'plus':    return <svg {...p}><path d="M12 5v14M5 12h14"/></svg>;
    case 'x':       return <svg {...p}><path d="m6 6 12 12M18 6 6 18"/></svg>;
    case 'trash':   return <svg {...p}><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/></svg>;
    case 'edit':    return <svg {...p}><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5Z"/></svg>;
    case 'check':   return <svg {...p}><path d="m4 12 5 5L20 6"/></svg>;
    case 'play':    return <svg {...p}><path d="M6 4v16l14-8L6 4Z"/></svg>;
    case 'pause':   return <svg {...p}><path d="M7 4v16M17 4v16"/></svg>;
    case 'bolt':    return <svg {...p}><path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z"/></svg>;
    case 'arrowUp': return <svg {...p}><path d="M12 19V5M5 12l7-7 7 7"/></svg>;
    case 'arrowDn': return <svg {...p}><path d="M12 5v14M19 12l-7 7-7-7"/></svg>;
    case 'dot':     return <svg viewBox="0 0 8 8" width={size} height={size}><circle cx="4" cy="4" r="3" fill={color}/></svg>;
    case 'eye':     return <svg {...p}><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>;
    case 'grid':    return <svg {...p}><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>;
    case 'gear':    return <svg {...p}><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8M4.6 9a1.7 1.7 0 0 0-.3-1.8m0 9.6A1.7 1.7 0 0 0 4.6 15M19.4 9a1.7 1.7 0 0 1 .3-1.8M12 2v3M12 19v3M2 12h3M19 12h3"/></svg>;
    case 'logout':  return <svg {...p}><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/></svg>;
    case 'drag':    return <svg {...p}><circle cx="9" cy="6" r="1"/><circle cx="9" cy="12" r="1"/><circle cx="9" cy="18" r="1"/><circle cx="15" cy="6" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="15" cy="18" r="1"/></svg>;
    case 'link':    return <svg {...p}><path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/></svg>;
    case 'lock':    return <svg {...p}><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>;
    default:        return null;
  }
};

/* ════════════════ ATOMS ════════════════ */
const Btn = ({ children, onClick, primary, danger, ghost, small, disabled, style, title }) => (
  <button title={title} onClick={onClick} disabled={disabled} style={{
    fontFamily: CK.sans, fontSize: small ? 11.5 : 12.5, fontWeight: 500,
    padding: small ? '4px 9px' : '7px 13px', borderRadius: CK.rad.md,
    border: `1px solid ${primary ? CK.accent : danger ? CK.err + '66' : CK.line}`,
    background: primary ? CK.accent : ghost ? 'transparent' : CK.bgSoft,
    color: primary ? '#160d08' : danger ? CK.err : CK.ink,
    cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.5 : 1,
    display: 'inline-flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap',
    transition: 'all .14s', ...style,
  }}
  onMouseEnter={e => { if (!disabled && !primary) e.currentTarget.style.borderColor = CK.inkMuted; }}
  onMouseLeave={e => { if (!disabled && !primary) e.currentTarget.style.borderColor = danger ? CK.err + '66' : CK.line; }}
  >{children}</button>
);

const IconBtn = ({ name, onClick, color, title, active, size = 14 }) => (
  <button title={title} onClick={onClick} style={{
    width: 28, height: 28, display: 'grid', placeItems: 'center', borderRadius: CK.rad.sm,
    border: `1px solid ${active ? CK.accent : 'transparent'}`, background: active ? CK.accentSoft : 'transparent',
    color: color || CK.inkSoft, cursor: 'pointer', transition: 'all .14s',
  }}
  onMouseEnter={e => { e.currentTarget.style.background = CK.bgHover; }}
  onMouseLeave={e => { e.currentTarget.style.background = active ? CK.accentSoft : 'transparent'; }}
  ><CKIcon name={name} size={size}/></button>
);

const Pill = ({ children, k, color }) => {
  const c = color || sc(k);
  return <span style={{
    fontFamily: CK.mono, fontSize: 9.5, letterSpacing: '0.08em', textTransform: 'uppercase',
    color: c, background: c + '1a', border: `1px solid ${c}33`, padding: '2px 7px', borderRadius: 4,
    display: 'inline-flex', alignItems: 'center', gap: 4, whiteSpace: 'nowrap',
  }}>{children}</span>;
};

const Dot = ({ k, color, pulse }) => {
  const c = color || sc(k);
  return <span style={{ width: 7, height: 7, borderRadius: '50%', background: c, flexShrink: 0,
    boxShadow: `0 0 0 0 ${c}`, animation: pulse ? 'ckPulse 1.8s infinite' : 'none' }}/>;
};

const Avatar = ({ name, size = 24, ring }) => {
  const initials = (name || '?').split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase();
  const hues = ['#d97757', '#5fb3b3', '#a98cd6', '#7ec18e', '#e5b25a', '#7898d6'];
  const h = hues[(name || '').length % hues.length];
  return <span style={{
    width: size, height: size, borderRadius: '50%', background: h + '22', color: h,
    border: `1px solid ${h}55`, display: 'grid', placeItems: 'center', flexShrink: 0,
    fontFamily: CK.mono, fontSize: size * 0.36, fontWeight: 600,
    boxShadow: ring ? `0 0 0 2px ${CK.bg}` : 'none',
  }}>{initials}</span>;
};

const Field = ({ label, value, onChange, placeholder, type = 'text', full, mono, style }) => (
  <label style={{ display: 'flex', flexDirection: 'column', gap: 5, flex: full ? 1 : 'none', ...style }}>
    {label && <span style={{ fontFamily: CK.mono, fontSize: 9.5, color: CK.inkMuted, letterSpacing: '0.1em', textTransform: 'uppercase' }}>{label}</span>}
    <input value={value ?? ''} type={type} onChange={e => onChange && onChange(e.target.value)} placeholder={placeholder} style={{
      padding: '7px 10px', borderRadius: CK.rad.sm, border: `1px solid ${CK.line}`, background: CK.bgDeep,
      color: CK.ink, fontSize: 13, fontFamily: mono ? CK.mono : CK.sans, outline: 'none', width: full ? '100%' : 'auto',
    }}
    onFocus={e => e.target.style.borderColor = CK.accent}
    onBlur={e => e.target.style.borderColor = CK.line}/>
  </label>
);

const Select = ({ label, value, onChange, options, full }) => (
  <label style={{ display: 'flex', flexDirection: 'column', gap: 5, flex: full ? 1 : 'none' }}>
    {label && <span style={{ fontFamily: CK.mono, fontSize: 9.5, color: CK.inkMuted, letterSpacing: '0.1em', textTransform: 'uppercase' }}>{label}</span>}
    <select value={value} onChange={e => onChange && onChange(e.target.value)} style={{
      padding: '7px 10px', borderRadius: CK.rad.sm, border: `1px solid ${CK.line}`, background: CK.bgDeep,
      color: CK.ink, fontSize: 13, fontFamily: CK.sans, outline: 'none', cursor: 'pointer', width: full ? '100%' : 'auto',
    }}>
      {options.map(o => { const [v, l] = Array.isArray(o) ? o : [o, o]; return <option key={v} value={v} style={{ background: CK.bgPanel }}>{l}</option>; })}
    </select>
  </label>
);

const Toggle = ({ value, onChange }) => (
  <button onClick={() => onChange && onChange(!value)} style={{
    width: 36, height: 21, borderRadius: 999, border: 'none', padding: 2, flexShrink: 0,
    background: value ? CK.accent : CK.bgHover, cursor: 'pointer', position: 'relative', transition: 'background .15s',
  }}>
    <span style={{ position: 'absolute', top: 2, left: value ? 17 : 2, width: 17, height: 17, borderRadius: '50%',
      background: '#fff', transition: 'left .15s', boxShadow: '0 1px 2px rgba(0,0,0,.3)' }}/>
  </button>
);

const Modal = ({ title, sub, onClose, children, w = 460 }) => (
  <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 100, background: 'rgba(8,8,11,0.72)',
    backdropFilter: 'blur(3px)', display: 'grid', placeItems: 'center', padding: 24, animation: 'ckFade .15s' }}>
    <div onClick={e => e.stopPropagation()} style={{ width: w, maxWidth: '100%', maxHeight: '88vh', overflow: 'auto',
      background: CK.bgPanel, border: `1px solid ${CK.line}`, borderRadius: CK.rad.xl,
      boxShadow: '0 40px 120px rgba(0,0,0,.6)', animation: 'ckPop .2s' }} className="ck-scroll">
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12,
        padding: '16px 18px', borderBottom: `1px solid ${CK.line}` }}>
        <div>
          <div style={{ fontFamily: CK.serif, fontSize: 22, letterSpacing: '-0.02em' }}>{title}</div>
          {sub && <div style={{ fontFamily: CK.mono, fontSize: 10.5, color: CK.inkMuted, marginTop: 2, letterSpacing: '0.04em' }}>{sub}</div>}
        </div>
        <IconBtn name="x" onClick={onClose}/>
      </div>
      <div style={{ padding: 18 }}>{children}</div>
    </div>
  </div>
);

// section header inside a surface — dense, mission-control, mono kicker + rule
const SecHead = ({ icon, title, sub, right }) => (
  <div style={{ marginBottom: 16, borderBottom: `1px solid ${CK.line}`, paddingBottom: 13 }}>
    <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 16 }}>
      <div style={{ display: 'flex', alignItems: 'stretch', gap: 13 }}>
        <span style={{ width: 3, background: CK.accent, borderRadius: 2, flexShrink: 0 }}/>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, fontFamily: CK.mono, fontSize: 9.5, color: CK.accent, letterSpacing: '0.24em', textTransform: 'uppercase', marginBottom: 6 }}>
            {icon && <CKIcon name={icon} size={12}/>}<span>cockpit · {title}</span>
          </div>
          <h2 style={{ fontFamily: CK.serif, fontSize: 36, fontWeight: 400, letterSpacing: '-0.03em', margin: 0, lineHeight: 0.92 }}>{title}</h2>
          {sub && <div style={{ fontFamily: CK.mono, fontSize: 11, color: CK.inkSoft, letterSpacing: '0.02em', marginTop: 8 }}>{sub}</div>}
        </div>
      </div>
      {right}
    </div>
  </div>
);

// sparkline
const Spark = ({ data, w = 120, h = 32, color = CK.accent, fill = true }) => {
  if (!data || !data.length) return null;
  const mn = Math.min(...data), mx = Math.max(...data), rng = mx - mn || 1;
  const pts = data.map((v, i) => [i / (data.length - 1) * w, h - ((v - mn) / rng) * (h - 4) - 2]);
  const d = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
  return (
    <svg width={w} height={h} style={{ display: 'block', overflow: 'visible' }}>
      {fill && <path d={`${d} L ${w} ${h} L 0 ${h} Z`} fill={color} opacity="0.1"/>}
      <path d={d} fill="none" stroke={color} strokeWidth="1.6"/>
      <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="2.4" fill={color}/>
    </svg>
  );
};

// big metric stat card — terminal-framed readout
const StatCard = ({ label, value, unit, delta, deltaGood, spark, sparkColor, foot }) => (
  <div style={{ background: CK.bgPanel, border: `1px solid ${CK.line}`, borderRadius: CK.rad.lg, padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 9, minWidth: 0, position: 'relative', overflow: 'hidden' }}>
    <span style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 2, background: `linear-gradient(90deg, ${sparkColor || CK.accent}, transparent 70%)` }}/>
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
      <span style={{ fontFamily: CK.mono, fontSize: 9.5, color: CK.inkSoft, letterSpacing: '0.16em', textTransform: 'uppercase' }}>{label}</span>
      {delta != null && (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 2, fontFamily: CK.mono, fontSize: 10.5, fontWeight: 600, color: deltaGood ? CK.ok : CK.err }}>
          <CKIcon name={deltaGood ? 'arrowUp' : 'arrowDn'} size={11}/>{delta}
        </span>
      )}
    </div>
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 5 }}>
      <span style={{ fontFamily: CK.serif, fontSize: 46, letterSpacing: '-0.035em', lineHeight: 0.85, color: CK.ink, fontVariantNumeric: 'tabular-nums' }}>{value}</span>
      {unit && <span style={{ fontFamily: CK.mono, fontSize: 12, color: CK.inkMuted }}>{unit}</span>}
    </div>
    {spark && <Spark data={spark} w={200} h={28} color={sparkColor || CK.accent}/>}
    {foot && <div style={{ fontFamily: CK.mono, fontSize: 10, color: CK.inkMuted, letterSpacing: '0.04em', borderTop: `1px solid ${CK.lineSoft}`, paddingTop: 7 }}>{foot}</div>}
  </div>
);

// keyframes + scrollbar (once)
if (typeof document !== 'undefined' && !document.getElementById('ck-anim')) {
  const s = document.createElement('style'); s.id = 'ck-anim';
  s.textContent = `
    @keyframes ckPulse{0%{box-shadow:0 0 0 0 currentColor}70%{box-shadow:0 0 0 5px transparent}100%{box-shadow:0 0 0 0 transparent}}
    @keyframes ckFade{from{opacity:0}to{opacity:1}}
    @keyframes ckPop{from{opacity:0;transform:scale(.97) translateY(6px)}to{opacity:1;transform:none}}
    @keyframes ckSlide{from{opacity:0;transform:translateY(-5px)}to{opacity:1;transform:none}}
    .ck-scroll::-webkit-scrollbar{width:8px;height:8px}
    .ck-scroll::-webkit-scrollbar-thumb{background:#2c2c34;border-radius:4px}
    .ck-scroll::-webkit-scrollbar-track{background:transparent}
    .ck-row:hover{background:${CK.bgSoft}!important}
  `;
  document.head.appendChild(s);
}

Object.assign(window, {
  CK, CKLS, ckLoad, ckSave, uid, EMPTY_DB, sc, STAT,
  CKIcon, Btn, IconBtn, Pill, Dot, Avatar, Field, Select, Toggle, Modal, SecHead, Spark, StatCard,
});
