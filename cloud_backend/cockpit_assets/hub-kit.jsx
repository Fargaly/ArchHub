// hub-kit.jsx — the cockpit's design foundation. Derives 100% from window.AH (tokens.jsx)
// so the cockpit IS the application, not a parallel product: same dark ground, same
// terracotta, same ink ramp, same radii, same type. Key NAMES are kept from the old
// light kit (paper / card / inkMute …) so every call site keeps working — only the
// values now point at the canonical dark set.

const AHX = window.AH;
const HB = {
  // surfaces — mirrors Studio: canvas = bg, panels/rails = bgPanel, raised = bgSoft
  paper:  AHX.bg,        // app ground / map canvas
  paper2: AHX.bgSoft,    // raised rows, wells
  card:   AHX.bgPanel,   // rails, masthead, cards
  cardHi: AHX.bgRaised,  // hovered / elevated card
  ink:     AHX.ink,
  inkSoft: AHX.inkSoft,
  inkMute: AHX.inkMuted,   // text-safe at the source (tokens.jsx)
  inkDim:  AHX.inkDim,
  line:     AHX.line,
  lineSoft: AHX.lineSoft,
  // accents — the real brand terracotta, not a light-bg substitute
  accent:    AHX.accent,
  accentHi:  AHX.accentHi,
  accentSoft:AHX.accentSoft,
  blue:   AHX.blue,
  blueSoft:'#1b2233',
  green:  AHX.ok,
  amber:  AHX.warn,
  red:    AHX.err,
  purple: AHX.purple,
  // fonts + radii straight from the app
  serif: AHX.serif, sans: AHX.sans, mono: AHX.mono, arch: AHX.arch,
  rad: AHX.rad,
};

const HSTAT = {
  green: HB.green, amber: HB.amber, red: HB.red,
  healthy: HB.green, healing: HB.amber, degraded: HB.red, idle: HB.inkMute,
  active: HB.green, suspended: HB.red, invited: HB.amber,
  working: HB.green, paused: HB.amber, error: HB.red, warn: HB.amber, info: HB.blue,
  open: HB.red, investigating: HB.amber, triaged: HB.blue, resolved: HB.green,
  primary: HB.accent, enabled: HB.green, local: HB.blue, disabled: HB.inkMute,
  confirmed: HB.green, learned: HB.amber, proposed: HB.blue,
  founder: HB.accent, firm: HB.purple, project: HB.blue, personal: HB.green, system: HB.inkMute,
  now: HB.accent, next: HB.blue, later: HB.purple, shipped: HB.green,
  ga: HB.green, beta: HB.blue, internal: HB.purple, off: HB.inkMute,
};
const hsc = (k) => HSTAT[k] || HB.inkMute;

/* ── atoms ── */
const HBtn = ({ children, onClick, primary, ghost, danger, small, disabled, title, style }) => (
  <button title={title} onClick={onClick} disabled={disabled} style={{
    fontFamily: HB.sans, fontSize: small ? 12 : 13, fontWeight: 500, letterSpacing: '0.01em',
    padding: small ? '6px 12px' : '9px 16px', borderRadius: HB.rad.md, cursor: disabled ? 'not-allowed' : 'pointer',
    border: `1px solid ${primary ? HB.accent : danger ? HB.red + '66' : HB.line}`,
    background: primary ? HB.accent : ghost ? 'transparent' : HB.cardHi,
    color: primary ? ((window.AH && window.AH.onFill) || '#180f08') : danger ? HB.red : HB.ink, opacity: disabled ? 0.5 : 1,
    display: 'inline-flex', alignItems: 'center', gap: 7, whiteSpace: 'nowrap', transition: 'all .15s',
    boxShadow: 'none', ...style,
  }}
  onMouseEnter={e => { if (!disabled) { e.currentTarget.style.transform = 'translateY(-1px)'; if (!primary && !ghost) e.currentTarget.style.borderColor = HB.inkMute; } }}
  onMouseLeave={e => { e.currentTarget.style.transform = 'none'; if (!primary && !ghost) e.currentTarget.style.borderColor = danger ? HB.red + '66' : HB.line; }}
  >{children}</button>
);

const HIconBtn = ({ name, onClick, title, active, size = 15, color }) => (
  <button title={title} onClick={onClick} style={{
    width: 30, height: 30, display: 'grid', placeItems: 'center', borderRadius: HB.rad.md, cursor: 'pointer',
    border: `1px solid ${active ? HB.accent : 'transparent'}`, background: active ? HB.accentSoft : 'transparent',
    color: color || HB.inkSoft, transition: 'all .14s',
  }}
  onMouseEnter={e => e.currentTarget.style.background = active ? HB.accentSoft : HB.lineSoft}
  onMouseLeave={e => e.currentTarget.style.background = active ? HB.accentSoft : 'transparent'}
  ><CKIcon name={name} size={size}/></button>
);

const HPill = ({ children, k, color }) => {
  const c = color || hsc(k);
  return <span style={{ fontFamily: HB.mono, fontSize: 9.5, letterSpacing: '0.1em', textTransform: 'uppercase',
    color: c, background: c + '18', border: `1px solid ${c}3a`, padding: '2px 8px', borderRadius: 3,
    display: 'inline-flex', alignItems: 'center', gap: 5, whiteSpace: 'nowrap' }}>{children}</span>;
};

const HDot = ({ k, color, pulse }) => { const c = color || hsc(k); return <span style={{ width: 7, height: 7, borderRadius: '50%', background: c, flexShrink: 0, color: c, animation: pulse ? 'hbPulse 1.8s infinite' : 'none' }}/>; };

const HAvatar = ({ name, size = 26 }) => {
  const initials = (name || '?').split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase();
  const hues = [HB.accent, HB.blue, HB.purple, HB.green, HB.amber];
  const h = hues[(name || '').length % hues.length];
  return <span style={{ width: size, height: size, borderRadius: '50%', background: h + '1e', color: h, border: `1px solid ${h}55`,
    display: 'grid', placeItems: 'center', flexShrink: 0, fontFamily: HB.mono, fontSize: size * 0.36, fontWeight: 600 }}>{initials}</span>;
};

const HField = ({ label, value, onChange, placeholder, type = 'text', full, area }) => (
  <label style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: full ? 1 : 'none' }}>
    {label && <span style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute, letterSpacing: '0.12em', textTransform: 'uppercase' }}>{label}</span>}
    {area
      ? <textarea value={value ?? ''} rows={3} onChange={e => onChange && onChange(e.target.value)} placeholder={placeholder} style={hInput()}/>
      : <input value={value ?? ''} type={type} onChange={e => onChange && onChange(e.target.value)} placeholder={placeholder} style={hInput()}/>}
  </label>
);
const hInput = () => ({ padding: '9px 11px', borderRadius: HB.rad.sm, border: `1px solid ${HB.line}`, background: HB.cardHi, color: HB.ink, fontSize: 13.5, fontFamily: HB.sans, outline: 'none', width: '100%', resize: 'vertical' });

const HSelect = ({ label, value, onChange, options, full }) => (
  <label style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: full ? 1 : 'none' }}>
    {label && <span style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute, letterSpacing: '0.12em', textTransform: 'uppercase' }}>{label}</span>}
    <select value={value} onChange={e => onChange && onChange(e.target.value)} style={{ ...hInput(), cursor: 'pointer' }}>
      {options.map(o => { const [v, l] = Array.isArray(o) ? o : [o, o]; return <option key={v} value={v}>{l}</option>; })}
    </select>
  </label>
);

const HToggle = ({ value, onChange }) => (
  <button onClick={() => onChange && onChange(!value)} style={{ width: 38, height: 22, borderRadius: 999, border: 'none', padding: 2, flexShrink: 0,
    background: value ? HB.accent : HB.line, cursor: 'pointer', position: 'relative', transition: 'background .15s' }}>
    <span style={{ position: 'absolute', top: 2, left: value ? 18 : 2, width: 18, height: 18, borderRadius: '50%', background: '#fff', transition: 'left .15s', boxShadow: '0 1px 2px rgba(0,0,0,.25)' }}/>
  </button>
);

const HModal = ({ title, sub, onClose, children, w = 480 }) => (
  <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 100, background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(2px)', display: 'grid', placeItems: 'center', padding: 24, animation: 'hbFade .15s' }}>
    <div onClick={e => e.stopPropagation()} className="hb-scroll" style={{ width: w, maxWidth: '100%', maxHeight: '88vh', overflow: 'auto', background: HB.card, border: `1px solid ${HB.line}`, borderRadius: HB.rad.xl, boxShadow: '0 30px 90px rgba(0,0,0,.28)', animation: 'hbPop .2s' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, padding: '18px 20px', borderBottom: `1px solid ${HB.line}` }}>
        <div>
          <div style={{ fontFamily: HB.serif, fontSize: 24, letterSpacing: '-0.02em', color: HB.ink }}>{title}</div>
          {sub && <div style={{ fontFamily: HB.mono, fontSize: 10.5, color: HB.inkMute, marginTop: 3, letterSpacing: '0.04em' }}>{sub}</div>}
        </div>
        <HIconBtn name="x" onClick={onClose}/>
      </div>
      <div style={{ padding: 20 }}>{children}</div>
    </div>
  </div>
);

// drafting-style section header: tick + measured kicker + big serif + rule
const HHead = ({ kicker, title, sub, right }) => (
  <div style={{ marginBottom: 22 }}>
    <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 20 }}>
      <div style={{ minWidth: 0 }}>
        {kicker && <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 10 }}>
          <span style={{ width: 22, height: 1, background: HB.accent }}/>
          <span style={{ fontFamily: HB.mono, fontSize: 10, color: HB.accent, letterSpacing: '0.26em', textTransform: 'uppercase' }}>{kicker}</span>
        </div>}
        <h1 style={{ fontFamily: HB.serif, fontSize: 46, fontWeight: 400, letterSpacing: '-0.03em', margin: 0, lineHeight: 0.95, color: HB.ink }}>{title}</h1>
        {sub && <div style={{ fontFamily: HB.sans, fontSize: 14, color: HB.inkSoft, marginTop: 10, maxWidth: 560, lineHeight: 1.5 }}>{sub}</div>}
      </div>
      {right}
    </div>
  </div>
);

// global paper styles + grid + animations (once)
if (typeof document !== 'undefined' && !document.getElementById('hb-style')) {
  const s = document.createElement('style'); s.id = 'hb-style';
  s.textContent = `
    body{background:${HB.paper};}
    @keyframes hbPulse{0%{box-shadow:0 0 0 0 currentColor}70%{box-shadow:0 0 0 5px transparent}100%{box-shadow:0 0 0 0 transparent}}
    @keyframes hbFade{from{opacity:0}to{opacity:1}}
    @keyframes hbPop{from{opacity:0;transform:scale(.97) translateY(8px)}to{opacity:1;transform:none}}
    @keyframes hbSlide{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:none}}
    @keyframes hbDraw{from{transform:translateX(36px);opacity:.3}to{transform:none;opacity:1}}
    .hb-scroll::-webkit-scrollbar{width:9px;height:9px}
    .hb-scroll::-webkit-scrollbar-thumb{background:${HB.line};border-radius:5px;border:2px solid ${HB.paper}}
    .hb-scroll::-webkit-scrollbar-track{background:transparent}
    .hb-blueprint{background-image:linear-gradient(${HB.line}55 1px,transparent 1px),linear-gradient(90deg,${HB.line}55 1px,transparent 1px);background-size:26px 26px;}
    .hb-rowh:hover{background:${HB.paper2}!important}
  `;
  document.head.appendChild(s);
}

// ── theme: light/dark swap, BOTH derived from tokens.jsx ──
// DARK is byte-identical to the application (window.AH canonical) — the cockpit is the
// same product as Studio, not a parallel one. LIGHT is the token light mirror (AH.l_*),
// for screen-sharing and print. No third palette.
const HB_DARK = {
  paper: AHX.bg, paper2: AHX.bgSoft, card: AHX.bgPanel, cardHi: AHX.bgRaised,
  ink: AHX.ink, inkSoft: AHX.inkSoft, inkMute: AHX.inkMuted, inkDim: AHX.inkDim,
  line: AHX.line, lineSoft: AHX.lineSoft,
  accent: AHX.accent, accentHi: AHX.accentHi, accentSoft: AHX.accentSoft,
  blue: AHX.blue, blueSoft: '#1b2233',
  green: AHX.ok, amber: AHX.warn, red: AHX.err, purple: AHX.purple,
};
const HB_LIGHT = {
  paper: AHX.l_bg, paper2: AHX.l_bgSoft, card: AHX.l_bgPanel, cardHi: '#ffffff',
  ink: AHX.l_ink, inkSoft: AHX.l_inkSoft, inkMute: AHX.l_inkMuted, inkDim: '#b8b0a2',
  line: AHX.l_line, lineSoft: '#eee9de',
  accent: AHX.l_accent, accentHi: '#b4522f', accentSoft: '#f2e2d8',
  blue: '#395b86', blueSoft: '#dce4ee',
  green: '#4c7a4e', amber: '#a8772a', red: '#b0402f', purple: '#6a5699',
};
const hbInjectCSS = () => {
  let s = document.getElementById('hb-style-dyn'); if (!s) { s = document.createElement('style'); s.id = 'hb-style-dyn'; document.head.appendChild(s); }
  s.textContent = `
    body{background:${HB.paper};}
    .hb-scroll::-webkit-scrollbar-thumb{background:${HB.line};border-radius:5px;border:2px solid ${HB.paper}}
    .hb-blueprint{background-image:linear-gradient(${HB.line}55 1px,transparent 1px),linear-gradient(90deg,${HB.line}55 1px,transparent 1px);background-size:26px 26px;}
    .hb-rowh:hover{background:${HB.paper2}!important}
  `;
};
const applyHBTheme = (mode) => { const src = mode === 'light' ? HB_LIGHT : HB_DARK; Object.keys(src).forEach(k => { HB[k] = src[k]; }); hbInjectCSS(); };

Object.assign(window, { HB, HSTAT, hsc, HBtn, HIconBtn, HPill, HDot, HAvatar, HField, HSelect, HToggle, HModal, HHead, applyHBTheme });
