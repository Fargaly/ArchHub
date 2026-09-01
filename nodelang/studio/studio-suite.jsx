// studio-suite.jsx — 7 deliverables, dark Studio theme throughout.
// 1) UIKit  2) Onboarding  3) Landing  4) SkillJson  5) MobileCompanion
// 6) Pricing  7) SelfHealInspector

// tokens.jsx — single source of truth (+ suite-specific extras)
const ST = { ...window.AH, accent2:window.AH.warn, selBg:'#241914' };

// ─────────────────────── shared atoms ───────────────────────
const SBox = ({ children, style }) => (
  <div style={{ background:ST.bgPanel, border:`1px solid ${ST.line}`, borderRadius:ST.rad.lg, padding:14, ...style }}>{children}</div>
);
const SLabel = ({ children, color }) => (
  <div style={{ fontFamily:ST.mono, fontSize:9.5, color:color||ST.inkMuted, letterSpacing:'0.14em', marginBottom:ST.sp.sm }}>{children}</div>
);
const SH = ({ num, title, sub }) => (
  <div style={{ display:'flex', alignItems:'baseline', gap:14, margin:'40px 48px 16px' }}>
    <span style={{ fontFamily:ST.mono, fontSize:11, color:ST.accent, letterSpacing:'0.16em' }}>{num}</span>
    <h2 style={{ fontFamily:ST.serif, fontSize:32, fontWeight:400, letterSpacing:'-0.02em', margin:0, color:ST.ink }}>{title}</h2>
    {sub && <span style={{ fontFamily:ST.mono, fontSize:11, color:ST.inkMuted, letterSpacing:'0.06em' }}>· {sub}</span>}
    <div style={{ flex:1, height:1, background:ST.lineSoft, marginLeft:6 }}/>
  </div>
);
const Grid = ({ cols, gap=10, children, style }) => (
  <div style={{ display:'grid', gridTemplateColumns:`repeat(${cols}, 1fr)`, gap, margin:'0 48px', ...style }}>{children}</div>
);
const Mark = ({ size=28, color=ST.accent }) => (
  <svg width={size} height={size} viewBox="0 0 64 64" fill="none">
    <path d="M10 56 V32 a22 22 0 0 1 44 0 V56" stroke={color} strokeWidth="4.5" strokeLinecap="square"/>
    <circle cx="32" cy="22" r="5.2" fill={ST.bg} stroke={color} strokeWidth="2.4"/>
    <circle cx="32" cy="22" r="1.8" fill={color}/>
    <path d="M6 58 H58" stroke={color} strokeWidth="1.5" strokeLinecap="round"/>
  </svg>
);
const Word = ({ size=22 }) => (
  <span style={{ fontFamily:ST.arch, fontSize:Math.round(size*0.82), letterSpacing:'0.02em', textTransform:'uppercase', color:ST.ink, lineHeight:1, display:'inline-flex', gap:'0.04em' }}>
    Arch<span style={{ color:ST.accent }}>Hub</span>
  </span>
);

// ═══════════════════════ 1 · UI KIT ═══════════════════════
const StudioUIKit = () => (
  <div className="ah-scroll" style={{ background:ST.bg, color:ST.ink, fontFamily:ST.sans, height:'100%', overflow:'auto', paddingBottom:48 }}>
    {/* Masthead */}
    <div style={{ padding:'40px 48px 28px', borderBottom:`1px solid ${ST.line}`, display:'flex', alignItems:'flex-end', gap:ST.sp.xl }}>
      <div style={{ flex:1 }}>
        <div style={{ fontFamily:ST.mono, fontSize:11, color:ST.inkMuted, letterSpacing:'0.16em' }}>STUDIO · UI KIT · v0.1</div>
        <h1 style={{ fontFamily:ST.serif, fontSize:72, fontWeight:400, letterSpacing:'-0.03em', lineHeight:0.95, margin:'10px 0 4px' }}>
          Components.
        </h1>
        <div style={{ fontFamily:ST.serif, fontStyle:'italic', fontSize:20, color:ST.inkSoft }}>Every screen reads from these.</div>
      </div>
      <Mark size={72}/>
    </div>

    {/* BUTTONS */}
    <SH num="01" title="Buttons" sub="primary · secondary · ghost · chip · icon"/>
    <Grid cols={4}>
      <SBox><SLabel>PRIMARY</SLabel>
        <div style={{ display:'flex', flexDirection:'column', gap:ST.sp.sm }}>
          <button style={btnPrimary()}>Send <span style={{ fontFamily:ST.mono, fontSize:10, opacity:.7 }}>↵</span></button>
          <button style={{...btnPrimary(), opacity:.55, cursor:'not-allowed'}}>Disabled</button>
          <button style={{...btnPrimary(), background:ST.accentSoft, color:ST.accent}}>Loading…</button>
        </div>
      </SBox>
      <SBox><SLabel>SECONDARY</SLabel>
        <div style={{ display:'flex', flexDirection:'column', gap:ST.sp.sm }}>
          <button style={btnSecondary()}>Save as Skill</button>
          <button style={btnSecondary()}>Cancel</button>
          <button style={{...btnSecondary(), borderColor:ST.err, color:ST.err}}>Delete</button>
        </div>
      </SBox>
      <SBox><SLabel>GHOST / CHIP</SLabel>
        <div style={{ display:'flex', flexDirection:'column', gap:ST.sp.sm }}>
          <button style={btnGhost()}>+ Add stage</button>
          <div style={{ display:'flex', gap:6, flexWrap:'wrap' }}>
            <Chip>@ Skill</Chip><Chip>+ Stage</Chip><Chip>↻ Re-run</Chip>
          </div>
        </div>
      </SBox>
      <SBox><SLabel>ICON</SLabel>
        <div style={{ display:'flex', gap:ST.sp.sm }}>
          {['+','↻','✕','↗','⚙','★'].map(g => (
            <button key={g} style={iconBtn()}>{g}</button>
          ))}
        </div>
      </SBox>
    </Grid>

    {/* INPUTS */}
    <SH num="02" title="Inputs" sub="text · search · slider · select · toggle"/>
    <Grid cols={3}>
      <SBox><SLabel>TEXT</SLabel>
        <input placeholder="Tower A — north elevation" style={txt()}/>
        <div style={{ height:8 }}/>
        <input placeholder="Disabled" disabled style={{...txt(), opacity:.5}}/>
        <div style={{ height:8 }}/>
        <input value="Invalid input" readOnly style={{...txt(), borderColor:ST.err}}/>
      </SBox>
      <SBox><SLabel>SEARCH / COMMAND</SLabel>
        <div style={{ position:'relative' }}>
          <span style={{ position:'absolute', left:9, top:8, color:ST.inkMuted, fontSize:13 }}>⌕</span>
          <input placeholder="Search skills, hosts, params…" style={{...txt(), paddingLeft:28}}/>
          <span style={{ position:'absolute', right:8, top:7, fontFamily:ST.mono, fontSize:10, color:ST.inkMuted, padding:'1px 5px', border:`1px solid ${ST.line}`, borderRadius:ST.rad.xs }}>⌘K</span>
        </div>
        <div style={{ height:10 }}/>
        <SLabel>SELECT</SLabel>
        <select style={txt()}><option>Generic 200mm</option><option>Curtain</option></select>
      </SBox>
      <SBox><SLabel>PARAMETER ROW</SLabel>
        <ParamDemo k="thickness" v={200} unit="mm"/>
        <ParamDemo k="wwr" v={0.42} unit="ratio"/>
        <ParamDemo k="rooms" v={true} kind="toggle"/>
      </SBox>
    </Grid>

    {/* CHAT */}
    <SH num="03" title="Chat" sub="user · claude · stage · composer"/>
    <Grid cols={2}>
      <SBox style={{ padding:0 }}>
        <div style={{ padding:14, borderBottom:`1px solid ${ST.lineSoft}` }}>
          <SLabel>USER + CLAUDE</SLabel>
          <div style={{ display:'flex', gap:10 }}>
            <Avatar/>
            <div style={{ flex:1 }}>
              <div style={{ fontFamily:ST.mono, fontSize:9.5, color:ST.inkMuted, letterSpacing:'0.06em', marginBottom:3 }}>YOU · 12:42</div>
              <div style={{ fontSize:14, lineHeight:1.55, color:ST.ink }}>Build this sketch as a 6m gabled mass, then push to Revit.</div>
            </div>
          </div>
          <div style={{ height:14 }}/>
          <div style={{ display:'flex', gap:10 }}>
            <Mark size={28}/>
            <div style={{ flex:1 }}>
              <div style={{ fontFamily:ST.mono, fontSize:9.5, color:ST.accent, letterSpacing:'0.08em', marginBottom:3 }}>CLAUDE · sonnet 4.5</div>
              <div style={{ fontSize:14, lineHeight:1.55, color:ST.ink }}>
                Reading the sketch. Detected a 9-storey rectangular massing with setback at level 6.
                Creating parameters: <code style={{ color:ST.accent, fontFamily:ST.mono, fontSize:12 }}>width=6m</code>, <code style={{ color:ST.accent, fontFamily:ST.mono, fontSize:12 }}>roof_pitch=30°</code>.
              </div>
            </div>
          </div>
        </div>
        <div style={{ padding:14 }}>
          <SLabel>COMPOSER</SLabel>
          <div style={{ background:ST.selBg, border:`1px solid ${ST.line}`, borderRadius:ST.rad.lg, padding:'10px 12px' }}>
            <div style={{ fontFamily:ST.serif, fontSize:16, fontStyle:'italic', color:ST.inkMuted, padding:'2px 0 6px' }}>
              Add a stage…
            </div>
            <div style={{ display:'flex', gap:6, alignItems:'center' }}>
              <Chip>📎 Sketch</Chip><Chip>+ Stage</Chip><Chip>@ Skill</Chip>
              <div style={{ flex:1 }}/>
              <span style={{ fontFamily:ST.mono, fontSize:10, color:ST.inkMuted }}>~420ms</span>
              <button style={btnPrimary()}>Send</button>
            </div>
          </div>
        </div>
      </SBox>
      <SBox><SLabel>PARAMETRIC STAGE CARD</SLabel>
        <StageCard idx={3} label="Build walls in Revit" host="REVIT" state="fresh"/>
        <div style={{ height:10 }}/>
        <StageCard idx={4} label="Doors & windows" host="REVIT" state="running"/>
        <div style={{ height:10 }}/>
        <StageCard idx={5} label="Production sheets" host="REVIT" state="stale"/>
      </SBox>
    </Grid>

    {/* HOSTS / FRESHNESS / NODES */}
    <SH num="04" title="State chips" sub="host · freshness · llm · ratings"/>
    <Grid cols={4}>
      <SBox><SLabel>HOST PILLS</SLabel>
        {[['Revit','#5fb3b3'],['Blender','#d97757'],['AutoCAD','#e6705f'],['3ds Max','#7ec18e'],['Speckle','#a98cd6']].map(([n,c]) => (
          <div key={n} style={{ display:'flex', alignItems:'center', gap:ST.sp.sm, padding:'5px 0' }}>
            <span style={{ width:8, height:8, borderRadius:'50%', background:c, boxShadow:`0 0 0 3px ${c}22` }}/>
            <span style={{ flex:1, fontSize:13 }}>{n}</span>
            <span style={{ fontFamily:ST.mono, fontSize:10, color:ST.inkMuted }}>:78{Math.floor(Math.random()*900)+100}</span>
          </div>
        ))}
      </SBox>
      <SBox><SLabel>FRESHNESS</SLabel>
        <div style={{ display:'flex', flexDirection:'column', gap:6 }}>
          <Freshness state="fresh"/><Freshness state="running"/><Freshness state="stale"/><Freshness state="error"/><Freshness state="off"/>
        </div>
      </SBox>
      <SBox><SLabel>LLM PROVIDERS</SLabel>
        {[['Claude 4.5','sonnet','#cc785c'],['GPT-5','reasoning','#10a37f'],['Gemini Pro','2.0','#4285f4'],['Llama 3.3','local','#9333ea'],['OpenRouter','auto','#737373']].map(([n,t,c])=>(
          <div key={n} style={{ display:'flex', alignItems:'center', gap:ST.sp.sm, padding:'4px 0', fontSize:13 }}>
            <span style={{ width:14, height:14, borderRadius:ST.rad.xs, background:c, color: (window.AH && window.AH.onFill) || '#180f08', display:'grid', placeItems:'center', fontFamily:ST.mono, fontSize:8, fontWeight:700 }}>{n[0]}</span>
            <span style={{ flex:1 }}>{n}</span>
            <span style={{ fontFamily:ST.mono, fontSize:9.5, color:ST.inkMuted, letterSpacing:'0.04em' }}>{t}</span>
          </div>
        ))}
      </SBox>
      <SBox><SLabel>NODE SOCKETS</SLabel>
        <svg width="100%" height="120" viewBox="0 0 240 120">
          {/* node */}
          <rect x="40" y="20" width="160" height="80" rx="6" fill={ST.bg} stroke={ST.line} strokeWidth="1.2"/>
          <text x="120" y="40" textAnchor="middle" fontFamily={ST.mono} fontSize="10" fill={ST.inkMuted} letterSpacing="2">REVIT · WALLS</text>
          {/* in sockets */}
          <circle cx="40" cy="55" r="5" fill={ST.bg} stroke={ST.cyan} strokeWidth="2"/>
          <circle cx="40" cy="80" r="5" fill={ST.bg} stroke={ST.accent2} strokeWidth="2"/>
          <text x="50" y="58" fontFamily={ST.mono} fontSize="9" fill={ST.inkSoft}>mass</text>
          <text x="50" y="83" fontFamily={ST.mono} fontSize="9" fill={ST.inkSoft}>wall_type</text>
          {/* out */}
          <circle cx="200" cy="60" r="5" fill={ST.accent} stroke={ST.accent} strokeWidth="2"/>
          <text x="190" y="63" textAnchor="end" fontFamily={ST.mono} fontSize="9" fill={ST.inkSoft}>walls</text>
        </svg>
      </SBox>
    </Grid>

    {/* CARDS */}
    <SH num="05" title="Cards" sub="skill · workflow · host · alert"/>
    <Grid cols={3}>
      <SBox style={{ padding:0, overflow:'hidden' }}>
        <div style={{ height:80, background:`linear-gradient(135deg, ${ST.accentSoft}, ${ST.bgPanel})`, borderBottom:`1px solid ${ST.line}`, display:'grid', placeItems:'center' }}>
          <Mark size={36}/>
        </div>
        <div style={{ padding:14 }}>
          <div style={{ display:'flex', alignItems:'center', gap:6, marginBottom:6 }}>
            <span style={{ fontFamily:ST.mono, fontSize:9, padding:'1px 5px', borderRadius:ST.rad.xs, background:ST.accent, color:((window.AH && window.AH.onFill) || '#180f08'), letterSpacing:'0.08em' }}>SKILL</span>
            <span style={{ fontFamily:ST.mono, fontSize:9.5, color:ST.inkMuted }}>★ 4.8 · 1.2k installs</span>
          </div>
          <div style={{ fontFamily:ST.serif, fontSize:18, letterSpacing:'-0.01em' }}>Sketch to production</div>
          <div style={{ fontSize:12.5, color:ST.inkSoft, lineHeight:1.5, marginTop:ST.sp.xs }}>Six-stage pipeline: extract mass → Speckle → Revit → walls → fenestration → sheets.</div>
        </div>
      </SBox>
      <SBox><SLabel>HOST · CONNECTED</SLabel>
        <div style={{ display:'flex', alignItems:'center', gap:10 }}>
          <div style={{ width:36, height:36, borderRadius:ST.rad.md, background:'#5fb3b3', display:'grid', placeItems:'center', color:'#0a0a0d', fontFamily:ST.serif, fontSize:18 }}>R</div>
          <div style={{ flex:1 }}>
            <div style={{ fontWeight:500 }}>Revit 2025</div>
            <div style={{ fontFamily:ST.mono, fontSize:10, color:ST.inkMuted }}>:48884 · 14 tools · 2.3MB/s</div>
          </div>
          <Freshness state="fresh" mini/>
        </div>
        <div style={{ height:10, background:ST.lineSoft, borderRadius:ST.rad.sm, marginTop:10, overflow:'hidden' }}>
          <div style={{ width:'72%', height:'100%', background:ST.ok }}/>
        </div>
        <div style={{ fontFamily:ST.mono, fontSize:10, color:ST.inkMuted, marginTop:ST.sp.xs }}>uptime 99.4% · 7d</div>
      </SBox>
      <SBox><SLabel>ALERT · HEALING</SLabel>
        <div style={{ background:`${ST.warn}11`, border:`1px solid ${ST.warn}33`, borderRadius:ST.rad.md, padding:10 }}>
          <div style={{ fontFamily:ST.mono, fontSize:10.5, color:ST.warn, letterSpacing:'0.06em', fontWeight:600 }}>BLENDER · SELF-HEALING</div>
          <div style={{ fontFamily:ST.mono, fontSize:10.5, color:ST.inkSoft, marginTop:5, lineHeight:1.7 }}>
            <div>retry 2/3 · backoff 1.2s</div>
            <div>DLL load OK</div>
            <div style={{ color:ST.warn }}>… awaiting handshake</div>
          </div>
        </div>
      </SBox>
    </Grid>

    {/* TYPE / SPACING / ELEVATION */}
    <SH num="06" title="Foundations" sub="type · spacing · radius · elevation"/>
    <Grid cols={4}>
      <SBox><SLabel>TYPE SCALE</SLabel>
        {[['D1',48,ST.serif],['H1',24,ST.serif],['B',14,ST.sans],['S',12,ST.sans],['M',11,ST.mono]].map(([n,s,f])=>(
          <div key={n} style={{ display:'flex', alignItems:'baseline', gap:10, padding:'3px 0', borderBottom:`1px dashed ${ST.lineSoft}` }}>
            <span style={{ fontFamily:ST.mono, fontSize:9.5, color:ST.inkMuted, width:24 }}>{n}</span>
            <span style={{ fontFamily:f, fontSize:s, lineHeight:1, color:ST.ink, letterSpacing:s>30?'-0.02em':'0' }}>Aa</span>
            <span style={{ flex:1 }}/>
            <span style={{ fontFamily:ST.mono, fontSize:9.5, color:ST.inkMuted }}>{s}</span>
          </div>
        ))}
      </SBox>
      <SBox><SLabel>SPACING · 4PT</SLabel>
        {[2,4,8,12,16,24,32,48].map(s=>(
          <div key={s} style={{ display:'flex', alignItems:'center', gap:ST.sp.sm, padding:'3px 0' }}>
            <span style={{ fontFamily:ST.mono, fontSize:10, color:ST.inkMuted, width:24 }}>{s}</span>
            <div style={{ width:s, height:10, background:ST.accent, borderRadius:2 }}/>
          </div>
        ))}
      </SBox>
      <SBox><SLabel>RADIUS</SLabel>
        {[3,5,8,12,'full'].map(r=>(
          <div key={r} style={{ display:'flex', alignItems:'center', gap:10, padding:'4px 0' }}>
            <div style={{ width:32, height:32, background:ST.accentSoft, border:`1px solid ${ST.accent}`, borderRadius:r==='full'?999:r }}/>
            <span style={{ fontFamily:ST.mono, fontSize:10.5, color:ST.inkSoft }}>{r}</span>
          </div>
        ))}
      </SBox>
      <SBox><SLabel>ELEVATION</SLabel>
        <div style={{ display:'flex', flexDirection:'column', gap:ST.sp.sm }}>
          {[
            ['flat','none'],
            ['raised','0 1px 2px rgba(0,0,0,.4)'],
            ['floating','0 6px 14px rgba(0,0,0,.45)'],
            ['modal','0 24px 60px rgba(0,0,0,.55)'],
          ].map(([n,sh])=>(
            <div key={n} style={{ background:ST.bg, padding:'8px 12px', borderRadius:ST.rad.md, boxShadow:sh, fontSize:12, color:ST.inkSoft, border:`1px solid ${ST.lineSoft}` }}>
              <span style={{ fontFamily:ST.mono, fontSize:10, color:ST.inkMuted, letterSpacing:'0.06em', marginRight:6 }}>{n.toUpperCase()}</span> {sh}
            </div>
          ))}
        </div>
      </SBox>
    </Grid>
  </div>
);

// ─── kit atoms ───
const btnPrimary = () => ({
  padding:'7px 14px', borderRadius:ST.rad.sm, border:0, background:ST.accent, color:((window.AH && window.AH.onFill) || '#180f08'),
  fontSize:13, fontWeight:500, fontFamily:ST.sans, cursor:'pointer',
  display:'inline-flex', alignItems:'center', gap:7,
});
const btnSecondary = () => ({
  padding:'6px 13px', borderRadius:ST.rad.sm, border:`1px solid ${ST.line}`, background:'transparent', color:ST.ink,
  fontSize:13, fontFamily:ST.sans, cursor:'pointer',
});
const btnGhost = () => ({
  padding:'6px 12px', borderRadius:ST.rad.sm, border:0, background:'transparent', color:ST.accent,
  fontSize:13, fontFamily:ST.sans, cursor:'pointer', textAlign:'left',
});
const iconBtn = () => ({
  width:28, height:28, borderRadius:ST.rad.sm, border:`1px solid ${ST.line}`, background:'transparent', color:ST.inkSoft,
  fontSize:14, cursor:'pointer',
});
const Chip = ({ children }) => (
  <span style={{ padding:'3px 8px', borderRadius:999, background:ST.bg, border:`1px solid ${ST.line}`, fontSize:11.5, color:ST.inkSoft, fontFamily:ST.mono, letterSpacing:'0.02em', cursor:'pointer' }}>{children}</span>
);
const txt = () => ({
  width:'100%', padding:'7px 10px', borderRadius:ST.rad.sm, border:`1px solid ${ST.line}`,
  background:ST.bg, color:ST.ink, fontFamily:ST.sans, fontSize:13, outline:'none',
});
const Avatar = () => <div style={{ width:28, height:28, borderRadius:'50%', background:'#d8c5a8', display:'grid', placeItems:'center', fontFamily:ST.sans, fontSize:12, color:'#5a4a2a', fontWeight:700, flexShrink:0 }}>F</div>;
const ParamDemo = ({ k, v, unit, kind }) => {
  if (kind === 'toggle') return (
    <div style={{ display:'flex', alignItems:'center', gap:ST.sp.sm, padding:'5px 0', borderBottom:`1px dashed ${ST.lineSoft}` }}>
      <span style={{ fontFamily:ST.mono, fontSize:11, color:ST.inkSoft, flex:1 }}>{k}</span>
      <div style={{ width:24, height:14, borderRadius:999, background:v?ST.accent:ST.lineSoft, position:'relative' }}>
        <div style={{ position:'absolute', top:1, left:v?11:1, width:12, height:12, borderRadius:'50%', background:'#fff' }}/>
      </div>
    </div>
  );
  return (
    <div style={{ padding:'5px 0', borderBottom:`1px dashed ${ST.lineSoft}` }}>
      <div style={{ display:'flex', alignItems:'baseline', gap:6, marginBottom:2 }}>
        <span style={{ fontFamily:ST.mono, fontSize:11, color:ST.inkSoft, flex:1 }}>{k}</span>
        <span style={{ fontFamily:ST.mono, fontSize:12, color:ST.ink, fontWeight:500 }}>{v}<span style={{ color:ST.inkMuted, marginLeft:2, fontSize:10 }}> {unit}</span></span>
      </div>
      <input type="range" defaultValue={v*100} style={{ width:'100%', accentColor:ST.accent }}/>
    </div>
  );
};
const Freshness = ({ state, mini }) => {
  const map = {
    fresh:[ST.ok,'FRESH','✓'],
    running:[ST.accent,'RUNNING','↻'],
    stale:[ST.warn,'STALE','◈'],
    error:[ST.err,'ERROR','!'],
    off:[ST.inkMuted,'OFF','·'],
  };
  const [c, l, g] = map[state];
  return (
    <span style={{ display:'inline-flex', alignItems:'center', gap:5, padding:'2px 7px', borderRadius:ST.rad.xs, background:`${c}14`, border:`1px solid ${c}33`, fontFamily:ST.mono, fontSize:mini?9:10, color:c, letterSpacing:'0.08em', fontWeight:500 }}>
      <span style={{ fontSize:mini?9:10 }}>{g}</span>{l}
    </span>
  );
};
const StageCard = ({ idx, label, host, state }) => {
  const c = state === 'fresh' ? ST.ok : state === 'running' ? ST.accent : ST.warn;
  return (
    <div style={{ display:'flex', alignItems:'center', gap:10, padding:'8px 10px', background:ST.bg, border:`1px solid ${ST.lineSoft}`, borderRadius:ST.rad.md }}>
      <span style={{ width:22, height:22, borderRadius:'50%', border:`2px solid ${c}`, background:ST.bgPanel, display:'grid', placeItems:'center', fontFamily:ST.mono, fontSize:9, color:c, fontWeight:600 }}>{idx}</span>
      <span style={{ flex:1, fontSize:13.5, color:ST.ink }}>{label}</span>
      <span style={{ fontFamily:ST.mono, fontSize:9.5, padding:'1px 5px', borderRadius:ST.rad.xs, background:'#5fb3b314', color:'#5fb3b3', letterSpacing:'0.04em' }}>{host}</span>
      <Freshness state={state} mini/>
    </div>
  );
};

// ═══════════════════════ 2 · ONBOARDING ═══════════════════════
const StudioOnboarding = () => (
  <div style={{ background:ST.bg, color:ST.ink, fontFamily:ST.sans, height:'100%', overflow:'auto', padding:'40px 48px' }} className="ah-scroll">
    <div style={{ marginBottom:28 }}>
      <div style={{ fontFamily:ST.mono, fontSize:11, color:ST.inkMuted, letterSpacing:'0.16em' }}>FIRST RUN · 60 SECONDS · 4 STEPS</div>
      <h1 style={{ fontFamily:ST.serif, fontSize:56, fontWeight:400, letterSpacing:'-0.03em', margin:'8px 0 4px' }}>Welcome.</h1>
      <div style={{ fontFamily:ST.serif, fontStyle:'italic', fontSize:18, color:ST.inkSoft }}>The four screens between download and "drag the slider".</div>
    </div>

    <div style={{ display:'grid', gridTemplateColumns:'repeat(4, 1fr)', gap:14 }}>
      {/* 1 · Welcome */}
      <OnbStep n="01" title="Welcome" sub="3 seconds">
        <div style={{ display:'grid', placeItems:'center', padding:'24px 0 12px' }}>
          <Mark size={56}/>
          <div style={{ marginTop:14 }}><Word size={28}/></div>
          <div style={{ fontFamily:ST.serif, fontStyle:'italic', fontSize:15, color:ST.inkSoft, marginTop:6 }}>Talk to your AEC stack.</div>
        </div>
        <div style={{ fontFamily:ST.mono, fontSize:10.5, color:ST.inkMuted, lineHeight:1.7, padding:'10px 0', borderTop:`1px solid ${ST.lineSoft}` }}>
          <div>· detected: Revit 2025, Blender 4.0</div>
          <div>· not detected: AutoCAD, 3ds Max</div>
          <div style={{ color:ST.ok }}>✓ ready in 12s</div>
        </div>
        <button style={{...btnPrimary(), width:'100%', justifyContent:'center'}}>Continue</button>
      </OnbStep>

      {/* 2 · Pick LLM */}
      <OnbStep n="02" title="Pick a brain" sub="who runs the chat">
        <SLabel>YOUR KEY (BYO)</SLabel>
        {[['Anthropic','sk-ant-•••','#cc785c'],['OpenAI','sk-•••','#10a37f'],['Google','AIza-•••','#4285f4']].map(([n,k,c])=>(
          <div key={n} style={pickRow()}>
            <span style={{ width:14, height:14, borderRadius:ST.rad.xs, background:c }}/>
            <span style={{ flex:1, fontSize:12.5 }}>{n}</span>
            <span style={{ fontFamily:ST.mono, fontSize:10, color:ST.inkMuted }}>{k}</span>
          </div>
        ))}
        <SLabel>OR</SLabel>
        <div style={pickRow()}><span style={{ width:14, height:14, borderRadius:ST.rad.xs, background:ST.accent }}/><span style={{ flex:1, fontSize:12.5 }}>ArchHub Cloud Relay</span><span style={{ fontFamily:ST.mono, fontSize:10, color:ST.accent }}>STUDIO</span></div>
        <div style={pickRow()}><span style={{ width:14, height:14, borderRadius:ST.rad.xs, background:'#9333ea' }}/><span style={{ flex:1, fontSize:12.5 }}>Local Ollama</span><span style={{ fontFamily:ST.mono, fontSize:10, color:ST.ok }}>OFFLINE</span></div>
        <button style={{...btnPrimary(), width:'100%', justifyContent:'center', marginTop:10}}>Use Anthropic</button>
      </OnbStep>

      {/* 3 · Connector birth */}
      <OnbStep n="03" title="Birth a connector" sub="Claude writes the bridge">
        <div style={{ background:ST.bgDeep, border:`1px solid ${ST.line}`, borderRadius:ST.rad.md, padding:10, fontFamily:ST.mono, fontSize:10.5, color:ST.inkSoft, lineHeight:1.7 }}>
          <div style={{ color:ST.ok }}>✓ analyze blender SDK</div>
          <div style={{ color:ST.ok }}>✓ generate addon · 1.2k chars</div>
          <div style={{ color:ST.ok }}>✓ install to plugin dir</div>
          <div style={{ color:ST.warn }}>↻ verify handshake :7331…</div>
          <div style={{ color:ST.inkMuted }}>· arm self-heal watchdog</div>
        </div>
        <div style={{ marginTop:10, padding:'8px 10px', background:`${ST.accent}11`, border:`1px solid ${ST.accent}33`, borderRadius:ST.rad.md }}>
          <div style={{ fontFamily:ST.mono, fontSize:9.5, color:ST.accent, letterSpacing:'0.08em' }}>WHY THIS MATTERS</div>
          <div style={{ fontSize:12, color:ST.inkSoft, marginTop:3, lineHeight:1.45 }}>No DLLs to ship per host per version. Claude regenerates on demand.</div>
        </div>
      </OnbStep>

      {/* 4 · First skill */}
      <OnbStep n="04" title="Your first skill" sub="drag a slider">
        <div style={{ background:ST.bgDeep, border:`1px solid ${ST.line}`, borderRadius:ST.rad.md, padding:'10px 12px' }}>
          <div style={{ fontFamily:ST.serif, fontSize:14, color:ST.ink }}>Sketch to production</div>
          <div style={{ fontFamily:ST.mono, fontSize:9.5, color:ST.inkMuted, marginTop:2, letterSpacing:'0.04em' }}>5 stages · 8 params · 12s e2e</div>
          <div style={{ display:'flex', gap:3, marginTop:ST.sp.sm }}>
            {[1,2,3,4,5].map(i => <span key={i} style={{ flex:1, height:3, borderRadius:2, background:i<=3?ST.ok:i===4?ST.accent:ST.lineSoft }}/>)}
          </div>
        </div>
        <ParamDemo k="roof_pitch" v={30} unit="°"/>
        <div style={{ fontFamily:ST.mono, fontSize:10, color:ST.accent, textAlign:'center', marginTop:ST.sp.xs }}>↻ chain re-running…</div>
        <button style={{...btnPrimary(), width:'100%', justifyContent:'center', marginTop:ST.sp.sm}}>Open Studio</button>
      </OnbStep>
    </div>

    {/* progress rail */}
    <div style={{ marginTop:ST.sp['2xl'], display:'flex', alignItems:'center', gap:0 }}>
      {[1,2,3,4].map(i=>(
        <React.Fragment key={i}>
          <div style={{ width:28, height:28, borderRadius:'50%', border:`2px solid ${i<=2?ST.ok:i===3?ST.accent:ST.line}`, background:i<=2?ST.ok:'transparent', color:i<=2?((window.AH && window.AH.onFill) || '#180f08'):ST.inkSoft, display:'grid', placeItems:'center', fontFamily:ST.mono, fontSize:11, fontWeight:600 }}>{i<=2?'✓':i}</div>
          {i<4 && <div style={{ flex:1, height:2, background:i<=2?ST.ok:ST.lineSoft }}/>}
        </React.Fragment>
      ))}
    </div>
  </div>
);
const OnbStep = ({ n, title, sub, children }) => (
  <div style={{ background:ST.bgPanel, border:`1px solid ${ST.line}`, borderRadius:ST.rad.lg, padding:14, display:'flex', flexDirection:'column', gap:ST.sp.sm }}>
    <div>
      <div style={{ fontFamily:ST.mono, fontSize:9.5, color:ST.accent, letterSpacing:'0.16em' }}>STEP {n}</div>
      <div style={{ fontFamily:ST.serif, fontSize:22, letterSpacing:'-0.01em', marginTop:2 }}>{title}</div>
      <div style={{ fontFamily:ST.mono, fontSize:10, color:ST.inkMuted, letterSpacing:'0.04em' }}>{sub}</div>
    </div>
    <div style={{ flex:1, display:'flex', flexDirection:'column', gap:6 }}>{children}</div>
  </div>
);
const pickRow = () => ({
  display:'flex', alignItems:'center', gap:ST.sp.sm, padding:'7px 9px', background:ST.bg,
  border:`1px solid ${ST.lineSoft}`, borderRadius:ST.rad.sm, marginBottom:5, cursor:'pointer',
});

// ═══════════════════════ 3 · LANDING ═══════════════════════
const StudioLanding = () => (
  <div style={{ background:ST.bg, color:ST.ink, fontFamily:ST.sans, height:'100%', overflow:'auto' }} className="ah-scroll">
    {/* Nav */}
    <div style={{ padding:'18px 64px', display:'flex', alignItems:'center', gap:ST.sp.xl, borderBottom:`1px solid ${ST.lineSoft}` }}>
      <div style={{ display:'flex', alignItems:'center', gap:ST.sp.sm }}>
        <Mark size={26}/><Word size={20}/>
      </div>
      <div style={{ flex:1, display:'flex', gap:18 }}>
        {['Product','Skills','Pricing','Docs','GitHub'].map(n => (
          <span key={n} style={{ fontSize:13, color:ST.inkSoft, cursor:'pointer' }}>{n}</span>
        ))}
      </div>
      <span style={{ fontFamily:ST.mono, fontSize:10.5, color:ST.inkMuted, letterSpacing:'0.06em' }}>v0.27.0 · MIT</span>
      <button style={btnSecondary()}>Sign in</button>
      <button style={btnPrimary()}>Download</button>
    </div>

    {/* Hero */}
    <div style={{ padding:'72px 64px 64px', display:'grid', gridTemplateColumns:'1.2fr 1fr', gap:ST.sp['4xl'], alignItems:'center', borderBottom:`1px solid ${ST.lineSoft}`, backgroundImage:`radial-gradient(${ST.lineSoft} 1px, transparent 1px)`, backgroundSize:'18px 18px' }}>
      <div>
        <div style={{ fontFamily:ST.mono, fontSize:11, color:ST.accent, letterSpacing:'0.18em', marginBottom:18 }}>● PARAMETRIC AI · FOR ARCHITECTS</div>
        <h1 style={{ fontFamily:ST.serif, fontSize:96, fontWeight:400, letterSpacing:'-0.04em', lineHeight:0.92, margin:0 }}>
          Talk to your<br/>
          <span style={{ fontStyle:'italic', color:ST.accent }}>AEC stack.</span>
        </h1>
        <div style={{ fontFamily:ST.serif, fontSize:22, color:ST.inkSoft, lineHeight:1.45, marginTop:22, maxWidth:540, letterSpacing:'-0.005em' }}>
          One chat drives Revit, Blender, AutoCAD, 3ds Max, and Speckle. Every step is a parametric node — drag a slider and the chain re-runs.
        </div>
        <div style={{ display:'flex', gap:10, marginTop:28 }}>
          <button style={{...btnPrimary(), padding:'10px 18px', fontSize:14}}>Download for Windows ↓</button>
          <button style={{...btnSecondary(), padding:'10px 18px', fontSize:14}}>Watch the 90s demo →</button>
        </div>
        <div style={{ fontFamily:ST.mono, fontSize:11, color:ST.inkMuted, marginTop:ST.sp.lg, letterSpacing:'0.04em' }}>
          MIT · BYO key · no credit card · Mac/Linux from source
        </div>
      </div>
      {/* Demo preview */}
      <div style={{ background:ST.bgPanel, border:`1px solid ${ST.line}`, borderRadius:12, overflow:'hidden', boxShadow:'0 30px 80px rgba(0,0,0,.5)' }}>
        <div style={{ padding:'8px 12px', borderBottom:`1px solid ${ST.line}`, display:'flex', gap:6, alignItems:'center' }}>
          <span style={{ width:10, height:10, borderRadius:'50%', background:'#666' }}/>
          <span style={{ width:10, height:10, borderRadius:'50%', background:'#666' }}/>
          <span style={{ width:10, height:10, borderRadius:'50%', background:'#666' }}/>
          <span style={{ flex:1, textAlign:'center', fontFamily:ST.mono, fontSize:10, color:ST.inkMuted }}>archhub.app · Tower A · /studio</span>
        </div>
        <div style={{ padding:18 }}>
          <div style={{ display:'flex', gap:9, marginBottom:14 }}>
            <Mark size={22}/>
            <div style={{ flex:1 }}>
              <div style={{ fontFamily:ST.mono, fontSize:9.5, color:ST.accent, letterSpacing:'0.08em' }}>CLAUDE</div>
              <div style={{ fontSize:13, color:ST.ink, lineHeight:1.5, marginTop:2 }}>Mass extracted at 9 storeys. Pushing to Speckle…</div>
            </div>
          </div>
          {/* chain */}
          <div style={{ display:'flex', alignItems:'center', gap:0, marginBottom:14 }}>
            {[1,2,3,4,5].map(i => (
              <React.Fragment key={i}>
                <div style={{ width:24, height:24, borderRadius:'50%', border:`2px solid ${i<=3?ST.ok:i===4?ST.accent:ST.lineSoft}`, background:ST.bg, display:'grid', placeItems:'center', fontFamily:ST.mono, fontSize:10, color:i<=3?ST.ok:i===4?ST.accent:ST.inkMuted, fontWeight:600 }}>{i}</div>
                {i<5 && <div style={{ flex:1, height:2, background:i<3?ST.ok:i===3?ST.accent:ST.lineSoft }}/>}
              </React.Fragment>
            ))}
          </div>
          <ParamDemo k="mass_height" v={32} unit="m"/>
          <ParamDemo k="wwr" v={0.42} unit="ratio"/>
          <div style={{ fontFamily:ST.mono, fontSize:10, color:ST.accent, textAlign:'right', marginTop:6 }}>↻ stages 4-5 re-running</div>
        </div>
      </div>
    </div>

    {/* Logos / trust */}
    <div style={{ padding:'24px 64px', display:'flex', alignItems:'center', gap:ST.sp['2xl'], borderBottom:`1px solid ${ST.lineSoft}`, fontFamily:ST.mono, fontSize:11, color:ST.inkMuted, letterSpacing:'0.08em' }}>
      <span>DRIVES</span>
      {['REVIT','BLENDER','AUTOCAD','3DS MAX','SPECKLE','RHINO','ARCHICAD','FORMA'].map(n=>(
        <span key={n} style={{ fontFamily:ST.serif, fontSize:18, color:ST.inkSoft, letterSpacing:'-0.005em' }}>{n}</span>
      ))}
    </div>

    {/* Three pillars */}
    <div style={{ padding:'72px 64px', borderBottom:`1px solid ${ST.lineSoft}` }}>
      <div style={{ fontFamily:ST.mono, fontSize:11, color:ST.accent, letterSpacing:'0.16em', marginBottom:18 }}>WHY ARCHHUB</div>
      <div style={{ display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:ST.sp.xl }}>
        {[
          ['Connectors build themselves','Toggle Blender on. Claude writes the addon, installs it, verifies the handshake. New host? Same loop. No DLLs to maintain.','♺'],
          ['Every step is a node','Every chat turn becomes a parameter in the sidebar. Drag the slider — the entire chain downstream re-runs.','◈'],
          ['Skills are JSON you own','Save any thread as a Skill. Copy-paste shareable. Synced via your private GitHub. No marketplace lock-in.','{ }'],
        ].map(([t,d,g])=>(
          <div key={t} style={{ borderTop:`1px solid ${ST.line}`, paddingTop:16 }}>
            <div style={{ fontFamily:ST.serif, fontSize:34, color:ST.accent, lineHeight:1, marginBottom:14 }}>{g}</div>
            <div style={{ fontFamily:ST.serif, fontSize:26, letterSpacing:'-0.02em', lineHeight:1.15 }}>{t}</div>
            <div style={{ fontSize:14, color:ST.inkSoft, lineHeight:1.55, marginTop:10, maxWidth:340 }}>{d}</div>
          </div>
        ))}
      </div>
    </div>

    {/* Pricing strip */}
    <div style={{ padding:'56px 64px', borderBottom:`1px solid ${ST.lineSoft}` }}>
      <div style={{ display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:14 }}>
        <PriceCard tier="Free" price="$0" copy="Up to 3 saved Skills · local Ollama or BYO key · single device. Forever free." cta="Download"/>
        <PriceCard tier="Pro" price="$39" hi copy="Unlimited Skills · cloud sync · 5-device · BYO key · email support." cta="Start Pro"/>
        <PriceCard tier="Studio" price="$79" copy="Pro + ArchHub Cloud Relay · firm-shared library · cost dashboard · SSO." cta="Talk to us"/>
      </div>
    </div>

    {/* Footer */}
    <div style={{ padding:'40px 64px 56px', display:'grid', gridTemplateColumns:'1.4fr 1fr 1fr 1fr', gap:ST.sp['2xl'] }}>
      <div>
        <div style={{ display:'flex', alignItems:'center', gap:ST.sp.sm, marginBottom:14 }}>
          <Mark size={26}/><Word size={20}/>
        </div>
        <div style={{ fontFamily:ST.serif, fontStyle:'italic', fontSize:16, color:ST.inkSoft, maxWidth:320, lineHeight:1.4 }}>
          Drafting table for AI. Built in the open. MIT, forever.
        </div>
      </div>
      {[['Product',['Studio','Skills','Connectors','Changelog']], ['Company',['About','Blog','Press','Contact']], ['Open',['GitHub','Discord','Roadmap','License']]].map(([t,xs])=>(
        <div key={t}>
          <div style={{ fontFamily:ST.mono, fontSize:10, color:ST.inkMuted, letterSpacing:'0.14em', marginBottom:10 }}>{t.toUpperCase()}</div>
          {xs.map(x => <div key={x} style={{ fontSize:13, color:ST.inkSoft, padding:'3px 0' }}>{x}</div>)}
        </div>
      ))}
    </div>
  </div>
);
const PriceCard = ({ tier, price, copy, cta, hi }) => (
  <div style={{ background:hi?ST.accentSoft:ST.bgPanel, border:`1px solid ${hi?ST.accent:ST.line}`, borderRadius:ST.rad.xl, padding:20, position:'relative' }}>
    {hi && <span style={{ position:'absolute', top:-9, right:14, padding:'2px 7px', background:ST.accent, color:((window.AH && window.AH.onFill) || '#180f08'), fontFamily:ST.mono, fontSize:9.5, borderRadius:ST.rad.xs, letterSpacing:'0.08em' }}>RECOMMENDED</span>}
    <div style={{ fontFamily:ST.mono, fontSize:11, color:hi?ST.accent:ST.inkMuted, letterSpacing:'0.14em' }}>{tier.toUpperCase()}</div>
    <div style={{ display:'flex', alignItems:'baseline', gap:6, marginTop:ST.sp.sm }}>
      <span style={{ fontFamily:ST.serif, fontSize:48, letterSpacing:'-0.03em' }}>{price}</span>
      <span style={{ fontFamily:ST.mono, fontSize:11, color:hi?ST.inkSoft:ST.inkMuted }}>/seat/mo</span>
    </div>
    <div style={{ fontSize:13, color:ST.inkSoft, lineHeight:1.55, margin:'12px 0 16px', minHeight:60 }}>{copy}</div>
    <button style={{...btnPrimary(), width:'100%', justifyContent:'center', background:hi?ST.accent:'transparent', border:hi?0:`1px solid ${ST.line}`, color:hi?((window.AH && window.AH.onFill) || '#180f08'):ST.ink}}>{cta}</button>
  </div>
);

// ═══════════════════════ 4 · SKILL JSON ═══════════════════════
const StudioSkillJson = () => {
  const json = `{
  "name": "Sketch to production",
  "version": "1.4.2",
  "author": "fargaly",
  "license": "MIT",
  "stages": [
    { "id": "s1", "kind": "vision",
      "intent": "extract massing from sketch",
      "params": { "source": "sketch.png" } },
    { "id": "s2", "kind": "rhino.mass",
      "params": {
        "mass_height": { "type": "slider", "default": 32,
                         "min": 6, "max": 80, "unit": "m" },
        "levels": { "type": "slider", "default": 9 }
      } },
    { "id": "s3", "kind": "revit.walls",
      "params": {
        "wall_type": "Generic 200",
        "thickness": 200, "rooms": true
      } }
  ],
  "tags": ["aec","sketch-to-bim","flagship"]
}`;
  return (
    <div style={{ background:ST.bg, color:ST.ink, fontFamily:ST.sans, height:'100%', overflow:'auto' }} className="ah-scroll">
      <div style={{ padding:'32px 48px 24px', borderBottom:`1px solid ${ST.line}`, display:'flex', alignItems:'flex-end', gap:18 }}>
        <div style={{ flex:1 }}>
          <div style={{ fontFamily:ST.mono, fontSize:11, color:ST.inkMuted, letterSpacing:'0.16em' }}>SKILL · OPEN</div>
          <h1 style={{ fontFamily:ST.serif, fontSize:48, letterSpacing:'-0.02em', margin:'4px 0 4px', fontWeight:400 }}>Sketch to production</h1>
          <div style={{ display:'flex', gap:ST.sp.sm, alignItems:'center' }}>
            <span style={{ fontFamily:ST.mono, fontSize:10.5, color:ST.inkMuted }}>v1.4.2 · ★ 4.8 · 1.2k installs · MIT</span>
          </div>
        </div>
        <div style={{ display:'flex', gap:ST.sp.sm }}>
          <button style={btnSecondary()}>📋 Copy JSON</button>
          <button style={btnSecondary()}>↗ Fork</button>
          <button style={btnPrimary()}>Open in chat ▸</button>
        </div>
      </div>

      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', height:'calc(100% - 116px)' }}>
        {/* Description */}
        <div style={{ padding:'24px 32px', borderRight:`1px solid ${ST.line}`, overflow:'auto' }} className="ah-scroll">
          <SLabel>WHAT IT DOES</SLabel>
          <div style={{ fontFamily:ST.serif, fontSize:18, lineHeight:1.55, color:ST.ink, letterSpacing:'-0.005em' }}>
            Six-stage pipeline that takes a hand sketch to a production drawing set. Extracts massing, pushes through Speckle, builds walls in Revit, places fenestration, and paginates sheets at 1:50.
          </div>
          <div style={{ height:18 }}/>
          <SLabel>STAGES</SLabel>
          <div style={{ display:'flex', flexDirection:'column', gap:6 }}>
            {[
              ['1','Vision · sketch parse','vision'],
              ['2','Rhino · mass extract','rhino'],
              ['3','Revit · wall build','revit'],
              ['4','Revit · fenestration','revit'],
              ['5','Revit · sheets','revit'],
            ].map(([n,t,h])=>(
              <div key={n} style={{ display:'flex', gap:ST.sp.sm, alignItems:'center', padding:'6px 0', borderBottom:`1px dashed ${ST.lineSoft}` }}>
                <span style={{ width:18, height:18, borderRadius:'50%', border:`1.5px solid ${ST.ok}`, color:ST.ok, fontFamily:ST.mono, fontSize:9, display:'grid', placeItems:'center' }}>{n}</span>
                <span style={{ flex:1, fontSize:13.5 }}>{t}</span>
                <span style={{ fontFamily:ST.mono, fontSize:10, color:ST.inkMuted, letterSpacing:'0.04em' }}>{h.toUpperCase()}</span>
              </div>
            ))}
          </div>
          <div style={{ height:18 }}/>
          <SLabel>EXPOSED PARAMETERS</SLabel>
          <div style={{ display:'flex', gap:6, flexWrap:'wrap' }}>
            {['mass_height','levels','wall_type','thickness','wwr','door_w','scale','titleblock'].map(p=>(
              <span key={p} style={{ fontFamily:ST.mono, fontSize:11, padding:'2px 7px', borderRadius:4, background:ST.bgPanel, color:ST.accent, border:`1px solid ${ST.lineSoft}` }}>{p}</span>
            ))}
          </div>
          <div style={{ height:18 }}/>
          <div style={{ background:ST.bgPanel, border:`1px solid ${ST.line}`, borderRadius:ST.rad.lg, padding:14 }}>
            <div style={{ fontFamily:ST.mono, fontSize:9.5, color:ST.inkMuted, letterSpacing:'0.14em' }}>YOU OWN THIS</div>
            <div style={{ fontFamily:ST.serif, fontSize:15, color:ST.inkSoft, marginTop:6, fontStyle:'italic' }}>
              Skills are plain JSON files in your private GitHub repo. Edit them, version them, share them, take them with you. ArchHub is the runner — never the registry.
            </div>
          </div>
        </div>

        {/* JSON */}
        <div style={{ padding:'18px 24px', overflow:'auto', background:ST.bgDeep }} className="ah-scroll">
          <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:10 }}>
            <SLabel>SOURCE · skill.json</SLabel>
            <div style={{ flex:1 }}/>
            <span style={{ fontFamily:ST.mono, fontSize:10, color:ST.inkMuted }}>478 bytes · 23 lines</span>
          </div>
          <pre style={{ margin:0, fontFamily:ST.mono, fontSize:12.5, lineHeight:1.65, color:ST.ink, whiteSpace:'pre-wrap' }}>
            {json.split('\n').map((line, i) => (
              <div key={i} style={{ display:'flex', gap:14 }}>
                <span style={{ color:ST.inkMuted, opacity:0.5, width:20, textAlign:'right', userSelect:'none' }}>{i+1}</span>
                <span style={{ flex:1 }}>{colorJson(line)}</span>
              </div>
            ))}
          </pre>
        </div>
      </div>
    </div>
  );
};
const colorJson = (line) => {
  // very light syntax color
  const parts = line.split(/("[^"]*")/g);
  return parts.map((p, i) => {
    if (p.startsWith('"') && p.endsWith('"')) {
      const isKey = /^"[^"]+":?$/.test(p) && line.indexOf(p+':') >= 0;
      return <span key={i} style={{ color: isKey ? ST.cyan : ST.accent2 }}>{p}</span>;
    }
    return <span key={i} style={{ color: ST.inkSoft }}>{p}</span>;
  });
};

// ═══════════════════════ 5 · MOBILE COMPANION ═══════════════════════
const StudioMobile = () => (
  <div style={{ background:ST.bg, color:ST.ink, fontFamily:ST.sans, height:'100%', overflow:'auto', padding:'40px 48px' }} className="ah-scroll">
    <div style={{ marginBottom:28 }}>
      <div style={{ fontFamily:ST.mono, fontSize:11, color:ST.inkMuted, letterSpacing:'0.16em' }}>MOBILE COMPANION · iOS</div>
      <h1 style={{ fontFamily:ST.serif, fontSize:48, letterSpacing:'-0.03em', margin:'8px 0 4px', fontWeight:400 }}>Sketch in pocket. Run on workstation.</h1>
      <div style={{ fontFamily:ST.serif, fontStyle:'italic', fontSize:16, color:ST.inkSoft }}>Capture → handoff → live params from anywhere.</div>
    </div>

    <div style={{ display:'flex', gap:ST.sp['2xl'], justifyContent:'center', flexWrap:'wrap' }}>
      {/* Phone 1 — Capture */}
      <PhoneShell label="01 · Capture sketch">
        <div style={{ flex:1, background:`linear-gradient(180deg, ${ST.bgDeep}, ${ST.bg})`, padding:'12px 14px', display:'flex', flexDirection:'column' }}>
          <div style={{ display:'flex', alignItems:'center', gap:ST.sp.sm, marginBottom:14 }}>
            <Mark size={22}/><Word size={16}/>
            <div style={{ flex:1 }}/>
            <span style={{ fontFamily:ST.mono, fontSize:9, color:ST.ok, letterSpacing:'0.06em' }}>● PAIRED</span>
          </div>
          {/* sketch placeholder */}
          <div style={{ flex:1, background:'#f0e8d8', borderRadius:ST.rad.xl, position:'relative', overflow:'hidden' }}>
            <svg viewBox="0 0 200 280" style={{ width:'100%', height:'100%' }}>
              <path d="M30 240 L30 130 L100 70 L170 130 L170 240 Z" fill="none" stroke="#3a2418" strokeWidth="1.5"/>
              <line x1="30" y1="180" x2="170" y2="180" stroke="#3a2418" strokeWidth="0.8"/>
              <rect x="60" y="200" width="22" height="40" fill="none" stroke="#3a2418" strokeWidth="0.8"/>
              <rect x="118" y="200" width="22" height="40" fill="none" stroke="#3a2418" strokeWidth="0.8"/>
              <text x="100" y="265" textAnchor="middle" fontFamily="JetBrains Mono" fontSize="7" fill="#7a7064">~6m wide · gabled · 2 storey</text>
            </svg>
            <span style={{ position:'absolute', top:8, right:8, padding:'2px 6px', background:ST.bg, color:ST.accent, fontFamily:ST.mono, fontSize:8.5, borderRadius:ST.rad.xs, letterSpacing:'0.06em' }}>● 12.4MP</span>
          </div>
          <div style={{ display:'flex', gap:6, marginTop:10 }}>
            <button style={{...btnSecondary(), flex:1, fontSize:11, padding:'7px 10px'}}>📷 Retake</button>
            <button style={{...btnPrimary(), flex:2, fontSize:11, padding:'7px 10px', justifyContent:'center'}}>Send to workstation →</button>
          </div>
        </div>
      </PhoneShell>

      {/* Phone 2 — Handoff */}
      <PhoneShell label="02 · Handoff">
        <div style={{ flex:1, padding:'14px', display:'flex', flexDirection:'column', gap:10 }}>
          <div>
            <div style={{ fontFamily:ST.mono, fontSize:9, color:ST.inkMuted, letterSpacing:'0.1em' }}>YOUR DEVICES</div>
            <div style={{ marginTop:ST.sp.sm, padding:'10px 12px', background:ST.accentSoft, border:`1px solid ${ST.accent}`, borderRadius:7, display:'flex', alignItems:'center', gap:10 }}>
              <span style={{ width:32, height:32, borderRadius:ST.rad.sm, background:ST.accent, color:((window.AH && window.AH.onFill) || '#180f08'), display:'grid', placeItems:'center' }}>🖥</span>
              <div style={{ flex:1 }}>
                <div style={{ fontSize:13, fontWeight:500 }}>STUDIO-PC</div>
                <div style={{ fontFamily:ST.mono, fontSize:9.5, color:ST.inkSoft }}>Revit 2025 · awake</div>
              </div>
              <span style={{ fontFamily:ST.mono, fontSize:9, color:ST.ok }}>SELECT</span>
            </div>
            {[['💻','LAPTOP-M2','Mac · sleeping'],['🏢','OFFICE-WS','offline 2h ago']].map(([g,n,s])=>(
              <div key={n} style={{ marginTop:6, padding:'8px 12px', background:ST.bgPanel, border:`1px solid ${ST.lineSoft}`, borderRadius:7, display:'flex', alignItems:'center', gap:10 }}>
                <span style={{ width:28, height:28, borderRadius:ST.rad.sm, background:ST.bg, display:'grid', placeItems:'center', opacity:0.6 }}>{g}</span>
                <div style={{ flex:1 }}>
                  <div style={{ fontSize:12, color:ST.inkSoft }}>{n}</div>
                  <div style={{ fontFamily:ST.mono, fontSize:9, color:ST.inkMuted }}>{s}</div>
                </div>
              </div>
            ))}
          </div>
          <div style={{ flex:1 }}/>
          <div style={{ background:ST.bgPanel, border:`1px solid ${ST.line}`, borderRadius:7, padding:'10px 12px' }}>
            <div style={{ fontFamily:ST.mono, fontSize:9, color:ST.inkMuted, letterSpacing:'0.1em' }}>QUEUED</div>
            <div style={{ fontSize:12.5, marginTop:ST.sp.xs }}>Sketch_2026-05-08.png</div>
            <div style={{ fontFamily:ST.mono, fontSize:9.5, color:ST.accent, marginTop:2 }}>↻ uploading · 64%</div>
          </div>
        </div>
      </PhoneShell>

      {/* Phone 3 — Live params */}
      <PhoneShell label="03 · Live params">
        <div style={{ flex:1, padding:'14px', display:'flex', flexDirection:'column', gap:10 }}>
          <div>
            <div style={{ fontFamily:ST.serif, fontSize:18, letterSpacing:'-0.01em' }}>Tower A</div>
            <div style={{ fontFamily:ST.mono, fontSize:9.5, color:ST.inkMuted }}>5 stages · running on STUDIO-PC</div>
          </div>
          <div style={{ display:'flex', gap:3 }}>
            {[1,2,3,4,5].map(i => <span key={i} style={{ flex:1, height:3, borderRadius:2, background:i<=3?ST.ok:i===4?ST.accent:ST.lineSoft }}/>)}
          </div>
          <div style={{ background:ST.bgPanel, border:`1px solid ${ST.lineSoft}`, borderRadius:ST.rad.md, padding:10 }}>
            <ParamDemo k="mass_height" v={32} unit="m"/>
            <ParamDemo k="wwr" v={0.42} unit="ratio"/>
            <ParamDemo k="rooms" v={true} kind="toggle"/>
          </div>
          <div style={{ flex:1 }}/>
          <div style={{ padding:10, background:ST.bgDeep, borderRadius:ST.rad.md, fontFamily:ST.mono, fontSize:10, color:ST.inkSoft, lineHeight:1.7 }}>
            <div style={{ color:ST.accent }}>↻ stages 4-5 re-running</div>
            <div style={{ color:ST.inkMuted }}>· est. 4.8s</div>
          </div>
          <button style={{...btnPrimary(), width:'100%', justifyContent:'center', fontSize:12}}>Open Studio on PC</button>
        </div>
      </PhoneShell>
    </div>
  </div>
);
const PhoneShell = ({ label, children }) => (
  <div>
    <div style={{ fontFamily:ST.mono, fontSize:10, color:ST.inkMuted, letterSpacing:'0.14em', marginBottom:ST.sp.md, textAlign:'center' }}>{label}</div>
    <div style={{ width:280, height:580, borderRadius:42, background:'#000', padding:ST.sp.sm, boxShadow:'0 30px 80px rgba(0,0,0,.5), inset 0 0 0 1.5px #2a2620' }}>
      <div style={{ width:'100%', height:'100%', borderRadius:34, background:ST.bg, overflow:'hidden', display:'flex', flexDirection:'column', position:'relative' }}>
        {/* Status bar */}
        <div style={{ padding:'10px 22px 4px', display:'flex', alignItems:'center', justifyContent:'space-between', fontFamily:ST.sans, fontSize:11, fontWeight:600, color:ST.ink }}>
          <span>9:41</span>
          <span style={{ position:'absolute', top:10, left:'50%', transform:'translateX(-50%)', width:80, height:22, background:'#000', borderRadius:14 }}/>
          <span style={{ display:'flex', gap:5, alignItems:'center', fontSize:10 }}>● ●● ▮</span>
        </div>
        {children}
        <div style={{ height:20, display:'grid', placeItems:'center', paddingBottom:6 }}>
          <span style={{ width:108, height:4, borderRadius:2, background:ST.inkSoft, opacity:0.5 }}/>
        </div>
      </div>
    </div>
  </div>
);

// ═══════════════════════ 6 · PRICING DIALOG ═══════════════════════
const StudioPricing = () => (
  <div style={{ background:ST.bgDeep, height:'100%', display:'grid', placeItems:'center', padding:ST.sp['3xl'] }}>
    <div style={{ width:'100%', maxWidth:1100, background:ST.bg, border:`1px solid ${ST.line}`, borderRadius:14, overflow:'hidden', boxShadow:'0 40px 120px rgba(0,0,0,.7)' }}>
      <div style={{ padding:'28px 36px 20px', borderBottom:`1px solid ${ST.line}`, display:'flex', alignItems:'flex-end', gap:18 }}>
        <Mark size={42}/>
        <div style={{ flex:1 }}>
          <div style={{ fontFamily:ST.mono, fontSize:11, color:ST.inkMuted, letterSpacing:'0.16em' }}>UPGRADE · v0.27.0</div>
          <div style={{ fontFamily:ST.serif, fontSize:36, letterSpacing:'-0.02em' }}>Pick a plan that fits.</div>
          <div style={{ fontFamily:ST.serif, fontStyle:'italic', fontSize:15, color:ST.inkSoft, marginTop:2 }}>Annual saves 2 months. Pause anytime. No surprise fees.</div>
        </div>
        <button style={{ background:'transparent', border:0, color:ST.inkSoft, fontSize:22, cursor:'pointer' }}>×</button>
      </div>

      <div style={{ padding:'28px 36px', display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:14 }}>
        <PlanCard
          tier="Free" price="$0" sub="Forever"
          features={[
            ['Up to 3 saved Skills', true],
            ['Local Ollama only', true],
            ['Single device', true],
            ['Community support', true],
            ['Cloud sync', false],
            ['Cloud relay (BYO key replacement)', false],
            ['Firm-shared library', false],
          ]}
          cta="Current plan" disabled
        />
        <PlanCard
          tier="Pro" price="$39" sub="per seat / mo" hi recommended="Most architects"
          features={[
            ['Unlimited saved Skills', true],
            ['BYO API keys', true],
            ['5-device sync', true],
            ['Cloud sync via private GitHub', true],
            ['Email support', true],
            ['Cloud relay', false],
            ['Firm-shared library', false],
          ]}
          cta="Upgrade to Pro"
        />
        <PlanCard
          tier="Studio" price="$79" sub="per seat / mo"
          features={[
            ['Everything in Pro', true],
            ['ArchHub Cloud Relay', true],
            ['Firm-shared Skill library', true],
            ['Cost & usage dashboard', true],
            ['Priority Skills (monthly)', true],
            ['Phone + email support', true],
            ['SSO', true],
          ]}
          cta="Talk to us"
        />
      </div>

      <div style={{ padding:'18px 36px 28px', borderTop:`1px solid ${ST.line}`, display:'flex', alignItems:'center', gap:14 }}>
        <span style={{ fontFamily:ST.mono, fontSize:10.5, color:ST.inkMuted, letterSpacing:'0.06em', flex:1 }}>
          ✓ MIT desktop · ✓ BYO key on every tier · ✓ no credit card on Free · ✓ pause or downgrade anytime
        </span>
        <button style={{ ...btnSecondary(), fontFamily:ST.mono, fontSize:11 }}>View full feature matrix →</button>
      </div>
    </div>
  </div>
);
const PlanCard = ({ tier, price, sub, features, cta, hi, disabled, recommended }) => (
  <div style={{ background:hi?ST.accentSoft:ST.bgPanel, border:`1.5px solid ${hi?ST.accent:ST.line}`, borderRadius:ST.rad.xl, padding:22, position:'relative', display:'flex', flexDirection:'column' }}>
    {recommended && <span style={{ position:'absolute', top:-11, left:'50%', transform:'translateX(-50%)', padding:'3px 10px', background:ST.accent, color:((window.AH && window.AH.onFill) || '#180f08'), fontFamily:ST.mono, fontSize:9.5, borderRadius:ST.rad.xs, letterSpacing:'0.1em' }}>{recommended.toUpperCase()}</span>}
    <div style={{ fontFamily:ST.mono, fontSize:11, color:hi?ST.accent:ST.inkMuted, letterSpacing:'0.14em' }}>{tier.toUpperCase()}</div>
    <div style={{ display:'flex', alignItems:'baseline', gap:6, marginTop:6 }}>
      <span style={{ fontFamily:ST.serif, fontSize:48, letterSpacing:'-0.03em', lineHeight:1 }}>{price}</span>
      <span style={{ fontFamily:ST.mono, fontSize:11, color:hi?ST.inkSoft:ST.inkMuted }}>{sub}</span>
    </div>
    <div style={{ height:1, background:hi?`${ST.accent}33`:ST.lineSoft, margin:'16px 0' }}/>
    <div style={{ flex:1, display:'flex', flexDirection:'column', gap:7 }}>
      {features.map(([f, on]) => (
        <div key={f} style={{ display:'flex', alignItems:'center', gap:ST.sp.sm, fontSize:13, color:on?ST.ink:(hi?ST.inkSoft:ST.inkMuted), opacity:on?1:0.62 }}>
          <span style={{ color:on?ST.ok:(hi?ST.inkSoft:ST.inkMuted), fontFamily:ST.mono, width:14, textAlign:'center' }}>{on?'✓':'·'}</span>
          {f}
        </div>
      ))}
    </div>
    <button disabled={disabled} style={{
      ...btnPrimary(), width:'100%', justifyContent:'center', marginTop:18,
      background: disabled?ST.bg:hi?ST.accent:'transparent',
      color: disabled?ST.inkMuted:hi?((window.AH && window.AH.onFill) || '#180f08'):ST.ink,
      border: hi?0:`1px solid ${ST.line}`,
      cursor: disabled?'default':'pointer', opacity: disabled?0.6:1,
    }}>{cta}</button>
  </div>
);

// ═══════════════════════ 7 · SELF-HEAL INSPECTOR ═══════════════════════
const StudioSelfHeal = () => {
  const checks = [
    { t:'Process check',       sub:'Revit.exe found, PID 14728', ok:true,  d:'42ms' },
    { t:'Plugin DLL loaded',   sub:'ArchHubBridge.dll · v2.4.1', ok:true,  d:'18ms' },
    { t:'Port :48884 reachable', sub:'localhost · TCP open',     ok:true,  d:'7ms' },
    { t:'Handshake',           sub:'awaiting hello frame…',     warn:true, d:'1.8s' },
    { t:'API version match',   sub:'expected ≥2.4.0',           pending:true, d:'—' },
    { t:'Tool catalog sync',   sub:'14 tools registered',       pending:true, d:'—' },
  ];
  return (
    <div style={{ background:ST.bg, color:ST.ink, fontFamily:ST.sans, height:'100%', overflow:'auto', padding:'40px 48px' }} className="ah-scroll">
      <div style={{ marginBottom:ST.sp.xl }}>
        <div style={{ fontFamily:ST.mono, fontSize:11, color:ST.inkMuted, letterSpacing:'0.16em' }}>CONNECTOR · DIAGNOSTIC</div>
        <h1 style={{ fontFamily:ST.serif, fontSize:48, letterSpacing:'-0.03em', margin:'8px 0 4px', fontWeight:400 }}>
          Revit dropped — <span style={{ color:ST.accent, fontStyle:'italic' }}>healing.</span>
        </h1>
        <div style={{ fontFamily:ST.serif, fontStyle:'italic', fontSize:16, color:ST.inkSoft }}>You don't restart it. ArchHub does.</div>
      </div>

      <div style={{ display:'grid', gridTemplateColumns:'1.2fr 1fr', gap:18 }}>
        {/* Diagnostic chain */}
        <SBox style={{ padding:0 }}>
          <div style={{ padding:'14px 18px', borderBottom:`1px solid ${ST.lineSoft}`, display:'flex', alignItems:'center', gap:10 }}>
            <span style={{ width:36, height:36, borderRadius:7, background:'#5fb3b3', color:'#0a0a0d', display:'grid', placeItems:'center', fontFamily:ST.serif, fontSize:18 }}>R</span>
            <div style={{ flex:1 }}>
              <div style={{ fontFamily:ST.serif, fontSize:18 }}>Revit 2025</div>
              <div style={{ fontFamily:ST.mono, fontSize:10, color:ST.inkMuted }}>:48884 · PID 14728 · attempt 2/3</div>
            </div>
            <Freshness state="running"/>
          </div>
          <div style={{ padding:'4px 0' }}>
            {checks.map((c, i) => (
              <div key={i} style={{ display:'flex', alignItems:'center', gap:ST.sp.md, padding:'10px 18px', borderBottom: i < checks.length-1 ? `1px solid ${ST.lineSoft}` : 0 }}>
                <span style={{
                  width:20, height:20, borderRadius:'50%',
                  background: c.ok ? ST.ok : c.warn ? ST.warn : 'transparent',
                  border: c.pending ? `1.5px dashed ${ST.lineSoft}` : 0,
                  color: (window.AH && window.AH.onFill) || '#180f08', display:'grid', placeItems:'center',
                  fontFamily:ST.mono, fontSize:10, fontWeight:600,
                  boxShadow: c.warn ? `0 0 0 4px ${ST.warn}22` : 'none',
                  animation: c.warn ? 'studPulse 1.1s infinite' : 'none',
                }}>{c.ok ? '✓' : c.warn ? '↻' : ''}</span>
                <div style={{ flex:1 }}>
                  <div style={{ fontSize:13.5 }}>{c.t}</div>
                  <div style={{ fontFamily:ST.mono, fontSize:10.5, color:ST.inkMuted, marginTop:1 }}>{c.sub}</div>
                </div>
                <span style={{ fontFamily:ST.mono, fontSize:10, color:c.warn?ST.warn:ST.inkMuted, letterSpacing:'0.04em' }}>{c.d}</span>
              </div>
            ))}
          </div>
          <div style={{ padding:'12px 18px', borderTop:`1px solid ${ST.line}`, display:'flex', alignItems:'center', gap:10 }}>
            <span style={{ fontFamily:ST.mono, fontSize:10.5, color:ST.inkMuted, flex:1 }}>backoff · 1.2s · next attempt at 12:43:14</span>
            <button style={btnSecondary()}>Pause</button>
            <button style={btnPrimary()}>Heal now ↻</button>
          </div>
        </SBox>

        {/* Side panels */}
        <div style={{ display:'flex', flexDirection:'column', gap:14 }}>
          <SBox><SLabel>SUGGESTED FIX · CLAUDE</SLabel>
            <div style={{ fontFamily:ST.serif, fontSize:16, lineHeight:1.45, color:ST.ink, letterSpacing:'-0.005em' }}>
              Revit's plugin loader is alive but no hello frame is coming back. This usually means the addon DLL is locked by an open transaction. I'll send a soft cancel and re-handshake. If that fails, I'll regenerate the addon (your changes are safe — Skills are JSON).
            </div>
            <div style={{ display:'flex', gap:ST.sp.sm, marginTop:ST.sp.md }}>
              <button style={btnSecondary()}>Show diff</button>
              <button style={btnPrimary()}>Apply fix</button>
            </div>
          </SBox>
          <SBox><SLabel>CONTEXT</SLabel>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:ST.sp.sm, fontFamily:ST.mono, fontSize:10.5, color:ST.inkSoft, letterSpacing:'0.04em' }}>
              <div><div style={{ color:ST.inkMuted }}>UPTIME</div><div style={{ color:ST.ink }}>4h 12m</div></div>
              <div><div style={{ color:ST.inkMuted }}>LAST OK</div><div style={{ color:ST.ink }}>12:42:01</div></div>
              <div><div style={{ color:ST.inkMuted }}>FAILURES 7d</div><div style={{ color:ST.ink }}>3 (auto-healed)</div></div>
              <div><div style={{ color:ST.inkMuted }}>HEAL P95</div><div style={{ color:ST.ink }}>2.1s</div></div>
            </div>
          </SBox>
          <SBox><SLabel>RECENT HEALS</SLabel>
            {[['12:14','handshake timeout','2.4s'],['09:08','DLL locked','5.1s'],['Yesterday','version mismatch · rewrote','12.8s']].map(([t,r,d])=>(
              <div key={t} style={{ display:'flex', alignItems:'center', gap:ST.sp.sm, padding:'5px 0', borderBottom:`1px dashed ${ST.lineSoft}`, fontFamily:ST.mono, fontSize:10.5 }}>
                <span style={{ color:ST.ok }}>✓</span>
                <span style={{ color:ST.inkMuted, width:64 }}>{t}</span>
                <span style={{ flex:1, color:ST.inkSoft }}>{r}</span>
                <span style={{ color:ST.inkMuted }}>{d}</span>
              </div>
            ))}
          </SBox>
        </div>
      </div>
    </div>
  );
};

// ─── expose ───
window.StudioUIKit = StudioUIKit;
window.StudioOnboarding = StudioOnboarding;
window.StudioLanding = StudioLanding;
window.StudioSkillJson = StudioSkillJson;
window.StudioMobile = StudioMobile;
window.StudioPricing = StudioPricing;
window.StudioSelfHeal = StudioSelfHeal;
