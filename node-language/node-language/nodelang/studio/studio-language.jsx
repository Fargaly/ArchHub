// studio-language.jsx — complete design language sheet for Studio v2
// Every state, every token, every rule — one artboard.

const DL = window.AH;  // tokens.jsx — single source of truth

// ── atoms ──
const DLBox = ({ children, style, label, sub }) => (
  <div style={{ background:DL.bgPanel, border:`1px solid ${DL.line}`, borderRadius:DL.rad.lg, padding:14, display:'flex', flexDirection:'column', gap:10, ...style }}>
    {label && (
      <div style={{ display:'flex', alignItems:'baseline', gap:DL.sp.sm }}>
        <span style={{ fontFamily:DL.mono, fontSize:9.5, color:DL.inkMuted, letterSpacing:'0.14em' }}>{label}</span>
        {sub && <span style={{ fontFamily:DL.mono, fontSize:9.5, color:DL.inkDim }}>· {sub}</span>}
      </div>
    )}
    {children}
  </div>
);
const DLSection = ({ num, title, sub, children }) => (
  <section style={{ marginTop:42 }}>
    <div style={{ display:'flex', alignItems:'baseline', gap:14, margin:'0 56px 18px' }}>
      <span style={{ fontFamily:DL.mono, fontSize:11, color:DL.accent, letterSpacing:'0.18em' }}>{num}</span>
      <h2 style={{ fontFamily:DL.serif, fontSize:34, fontWeight:400, letterSpacing:'-0.025em', margin:0, color:DL.ink, lineHeight:1 }}>{title}</h2>
      {sub && <span style={{ fontFamily:DL.serif, fontStyle:'italic', fontSize:18, color:DL.inkSoft, letterSpacing:'-0.01em' }}>{sub}</span>}
      <div style={{ flex:1, height:1, background:DL.lineSoft, marginLeft:6 }}/>
    </div>
    <div style={{ padding:'0 56px' }}>{children}</div>
  </section>
);

const Mark = ({ size=28, color=DL.accent, bg=DL.bg }) => (
  <svg width={size} height={size} viewBox="0 0 64 64" fill="none">
    <path d="M10 56 V32 a22 22 0 0 1 44 0 V56" stroke={color} strokeWidth="4.5" strokeLinecap="square"/>
    <circle cx="32" cy="22" r="5.2" fill={bg} stroke={color} strokeWidth="2.4"/>
    <circle cx="32" cy="22" r="1.8" fill={color}/>
    <path d="M6 58 H58" stroke={color} strokeWidth="1.5" strokeLinecap="round"/>
  </svg>
);

// ═══════════════════════════════════════════════════════════════════════
// MAIN
// ═══════════════════════════════════════════════════════════════════════
const StudioLanguage = () => (
  <div className="ah-scroll" style={{ background:DL.bg, color:DL.ink, fontFamily:DL.sans, height:'100%', overflow:'auto', paddingBottom:60 }}>

    {/* MASTHEAD */}
    <div style={{ padding:'48px 56px 36px', borderBottom:`1px solid ${DL.line}`, display:'grid', gridTemplateColumns:'1.4fr 1fr', gap:36, alignItems:'end' }}>
      <div>
        <div style={{ fontFamily:DL.mono, fontSize:11, color:DL.inkMuted, letterSpacing:'0.18em' }}>STUDIO · DESIGN LANGUAGE · v1.0.1</div>
        <h1 style={{ fontFamily:DL.serif, fontSize:88, fontWeight:400, letterSpacing:'-0.035em', lineHeight:0.92, margin:'14px 0 6px' }}>
          Every detail,<br/><span style={{ fontStyle:'italic', color:DL.accent }}>on purpose.</span>
        </h1>
        <div style={{ fontFamily:DL.serif, fontStyle:'italic', fontSize:21, color:DL.inkSoft, letterSpacing:'-0.01em' }}>The complete system behind ArchHub Studio — identity, color, type, motion, voice, and every component state.</div>
      </div>
      <div style={{ display:'flex', flexDirection:'column', gap:14, alignItems:'flex-end' }}>
        <div style={{ display:'flex', alignItems:'center', gap:18 }}>
          <Mark size={88} color={DL.accent} bg={DL.bgPanel}/>
          <div style={{ fontFamily:DL.arch, fontSize:40, letterSpacing:'0.02em', textTransform:'uppercase' }}>Arch<span style={{ color:DL.accent }}>Hub</span></div>
        </div>
        <div style={{ display:'flex', gap:6, fontFamily:DL.mono, fontSize:10, color:DL.inkMuted, letterSpacing:'0.06em' }}>
          <span style={{ padding:'2px 7px', border:`1px solid ${DL.lineSoft}`, borderRadius:DL.rad.xs }}>14 SECTIONS</span>
          <span style={{ padding:'2px 7px', border:`1px solid ${DL.lineSoft}`, borderRadius:DL.rad.xs }}>72 TOKENS</span>
          <span style={{ padding:'2px 7px', border:`1px solid ${DL.lineSoft}`, borderRadius:DL.rad.xs }}>v1.0.1</span>
        </div>
      </div>
    </div>

    {/* ═════════ 01 · BRAND PROMISE ═════════ */}
    <DLSection num="01" title="Brand promise" sub="what the user feels when they open the app">
      <div style={{ display:'grid', gridTemplateColumns:'2fr 1fr', gap:14 }}>
        <DLBox label="THE FEELING">
          <div style={{ fontFamily:DL.serif, fontSize:34, lineHeight:1.15, letterSpacing:'-0.02em', color:DL.ink }}>
            Opening ArchHub should feel like sitting down at a senior architect's drafting table — paper, graphite, a single warm pot of terracotta, and an unreasonably calm hand.
          </div>
          <div style={{ fontFamily:DL.mono, fontSize:10.5, color:DL.inkMuted, letterSpacing:'0.04em', lineHeight:1.7, marginTop:DL.sp.sm }}>
            → not a chat wrapper · not a plugin store · not a SaaS lock-in · not a Revit replacement
          </div>
        </DLBox>
        <DLBox label="THE PROOFS · 4 GUARANTEES">
          {[
            ['Calm','no bouncing, no celebrations, no exclamation points'],
            ['Crafted','every spacing value chosen, every shadow earns its frame'],
            ['Open','MIT desktop · BYO key · JSON skills you own'],
            ['Healing','connectors recover themselves; you never restart them'],
          ].map(([t,d])=>(
            <div key={t} style={{ display:'flex', gap:10, padding:'7px 0', borderBottom:`1px dashed ${DL.lineSoft}` }}>
              <span style={{ fontFamily:DL.serif, fontSize:18, color:DL.accent, fontStyle:'italic', minWidth:64, letterSpacing:'-0.01em' }}>{t}</span>
              <span style={{ fontSize:12.5, color:DL.inkSoft, lineHeight:1.45 }}>{d}</span>
            </div>
          ))}
        </DLBox>
      </div>
    </DLSection>

    {/* ═════════ 02 · MARK SYSTEM ═════════ */}
    <DLSection num="02" title="The mark, in full" sub="arch · keystone · node — 8 lockups, 1 grid">
      <div style={{ display:'grid', gridTemplateColumns:'1.2fr 1fr 1fr', gap:14 }}>
        {/* Construction */}
        <DLBox label="GRID · 12 UNITS" sub="every measurement derives from u = side/12">
          <div style={{ position:'relative', height:240, background:DL.bgDeep, borderRadius:DL.rad.md, display:'grid', placeItems:'center', backgroundImage:`linear-gradient(${DL.line} 1px, transparent 1px), linear-gradient(90deg, ${DL.line} 1px, transparent 1px)`, backgroundSize:'20px 20px' }}>
            <div style={{ position:'relative' }}>
              <Mark size={160} color={DL.accent} bg={DL.bgDeep}/>
              {/* dimension lines */}
              <div style={{ position:'absolute', left:-26, top:0, bottom:0, display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'space-between', fontFamily:DL.mono, fontSize:9, color:DL.cyan }}>
                <span>↑</span><span style={{ writingMode:'vertical-rl', transform:'rotate(180deg)' }}>12u</span><span>↓</span>
              </div>
              <div style={{ position:'absolute', bottom:-22, left:0, right:0, display:'flex', justifyContent:'space-between', fontFamily:DL.mono, fontSize:9, color:DL.cyan }}>
                <span>←</span><span>12u</span><span>→</span>
              </div>
              {/* keystone callout */}
              <div style={{ position:'absolute', top:36, left:120, fontFamily:DL.mono, fontSize:9, color:DL.cyan, lineHeight:1.5 }}>
                <span>keystone ø 2.6u</span><br/>
                <span style={{ color:DL.inkMuted }}>(parametric node)</span>
              </div>
            </div>
          </div>
          <div style={{ fontFamily:DL.mono, fontSize:10, color:DL.inkMuted, lineHeight:1.7, letterSpacing:'0.04em' }}>
            <div>· arch span = 11u · arch rise = 11u</div>
            <div>· stroke 4.5u/12 · ground line 1.5u/12</div>
            <div>· clear space ≥ 0.5 × keystone ø on all sides</div>
          </div>
        </DLBox>
        {/* Lockups */}
        <DLBox label="LOCKUPS · 4">
          <div style={{ display:'grid', gridTemplateColumns:'1fr', gap:10 }}>
            {[
              { l:'PRIMARY', show:<div style={{ display:'flex', alignItems:'center', gap:10 }}><Mark size={32}/><span style={{ fontFamily:DL.arch, fontSize:18, letterSpacing:'0.02em', textTransform:'uppercase' }}>Arch<span style={{ color:DL.accent }}>Hub</span></span></div> },
              { l:'STACKED', show:<div style={{ textAlign:'center' }}><Mark size={30}/><div style={{ fontFamily:DL.arch, fontSize:14, marginTop:DL.sp.xs, letterSpacing:'0.02em', textTransform:'uppercase' }}>Arch<span style={{ color:DL.accent }}>Hub</span></div></div> },
              { l:'MARK ONLY', show:<Mark size={36}/> },
              { l:'WORDMARK ONLY', show:<span style={{ fontFamily:DL.arch, fontSize:20, letterSpacing:'0.02em', textTransform:'uppercase' }}>Arch<span style={{ color:DL.accent }}>Hub</span></span> },
            ].map((it,i)=>(
              <div key={i} style={{ background:DL.bg, border:`1px solid ${DL.lineSoft}`, borderRadius:DL.rad.md, padding:'12px 14px', display:'flex', alignItems:'center', gap:DL.sp.md }}>
                <span style={{ fontFamily:DL.mono, fontSize:9, color:DL.inkMuted, letterSpacing:'0.12em', width:90 }}>{it.l}</span>
                <div style={{ flex:1, display:'grid', placeItems:'center' }}>{it.show}</div>
              </div>
            ))}
          </div>
        </DLBox>
        {/* Min sizes */}
        <DLBox label="SIZES · 5 STEPS">
          <div style={{ display:'flex', alignItems:'flex-end', justifyContent:'space-around', padding:'12px 0', flex:1 }}>
            {[
              [16, '16 favicon'],
              [24, '24 ui'],
              [32, '32 app'],
              [48, '48 print'],
              [72, '72 hero'],
            ].map(([s, lab]) => (
              <div key={s} style={{ textAlign:'center', display:'flex', flexDirection:'column', alignItems:'center', gap:6 }}>
                <Mark size={s} bg={DL.bgPanel}/>
                <div style={{ fontFamily:DL.mono, fontSize:8.5, color:DL.inkMuted, letterSpacing:'0.06em' }}>{lab}</div>
              </div>
            ))}
          </div>
          <div style={{ fontFamily:DL.mono, fontSize:10, color:DL.inkMuted, lineHeight:1.6 }}>
            Floor: 16px. Below this the keystone is unreadable. Above 72px the stroke caps need to step up 1.5×.
          </div>
        </DLBox>
      </div>

      {/* color variants */}
      <div style={{ display:'grid', gridTemplateColumns:'repeat(6, 1fr)', gap:10, marginTop:14 }}>
        {[
          { bg:DL.bg,       c:DL.accent, l:'DEFAULT · DARK' },
          { bg:DL.bgPanel,  c:DL.accent, l:'ON PANEL' },
          { bg:DL.l_bg,     c:DL.l_accent, l:'ON PAPER' },
          { bg:'#ffffff',   c:DL.accent, l:'WHITE BG' },
          { bg:DL.accent,   c:'#ffffff', l:'INVERTED' },
          { bg:DL.bg,       c:DL.ink,   l:'MONO' },
        ].map((v, i) => (
          <div key={i} style={{ background:v.bg, border:`1px solid ${DL.line}`, borderRadius:DL.rad.md, padding:'24px 0 8px', display:'flex', flexDirection:'column', alignItems:'center', gap:DL.sp.sm }}>
            <Mark size={42} color={v.c} bg={v.bg}/>
            <div style={{ fontFamily:DL.mono, fontSize:9, color:v.bg===DL.l_bg||v.bg==='#ffffff'?DL.l_inkMuted:DL.inkMuted, letterSpacing:'0.1em' }}>{v.l}</div>
          </div>
        ))}
      </div>
    </DLSection>

    {/* ═════════ 03 · COLOR SYSTEM ═════════ */}
    <DLSection num="03" title="Color system" sub="dark = canonical · light = mirror · 7 semantic groups">
      {/* Brand swatches */}
      <div style={{ display:'grid', gridTemplateColumns:'2fr 1fr 1fr 1fr', gap:10 }}>
        <ColorSwatch hex={DL.accent} dark name="Terracotta" role="Primary · only emotional accent" hex2="#d97757" big note="Carries 100% of the brand weight. Buttons, accents, brand. Warmth, ground, made-by-hand. Stroke on the mark. The italic 'Hub' in the wordmark."/>
        <ColorSwatch hex={DL.cyan} dark name="Drafting cyan" role="Technical" note="Section ticks, system-prompt accent, code keys. Sparingly."/>
        <ColorSwatch hex={DL.ok} dark name="Verdigris" role="OK · fresh · connected"/>
        <ColorSwatch hex={DL.warn} dark name="Patina" role="Healing · stale"/>
      </div>

      {/* Surface scale dark + light, 5 steps each */}
      <div style={{ marginTop:14, display:'grid', gridTemplateColumns:'1fr 1fr', gap:14 }}>
        <DLBox label="DARK SURFACES · 5 STEPS" sub="bg → panel → soft → hover → raised">
          <div style={{ display:'flex', borderRadius:DL.rad.md, overflow:'hidden', border:`1px solid ${DL.line}` }}>
            {[DL.bgDeep, DL.bg, DL.bgPanel, DL.bgSoft, DL.bgHover, DL.bgRaised].map((c, i) => (
              <div key={i} style={{ flex:1, background:c, height:70, display:'flex', flexDirection:'column', justifyContent:'flex-end', padding:DL.sp.sm }}>
                <span style={{ fontFamily:DL.mono, fontSize:8.5, color:DL.inkMuted, letterSpacing:'0.06em' }}>{c}</span>
              </div>
            ))}
          </div>
          <div style={{ fontFamily:DL.mono, fontSize:10, color:DL.inkMuted, lineHeight:1.65 }}>
            Lightness deltas are deliberately small (~5 ticks). Calm density beats visible rectangles.
          </div>
        </DLBox>
        <DLBox label="LIGHT SURFACES · 5 STEPS" sub="mirror of dark, never pure white">
          <div style={{ display:'flex', borderRadius:DL.rad.md, overflow:'hidden', border:`1px solid ${DL.line}` }}>
            {[DL.l_bg, DL.l_bgPanel, DL.l_bgSoft, '#ebe6db', '#ffffff'].map((c, i) => (
              <div key={i} style={{ flex:1, background:c, height:70, display:'flex', flexDirection:'column', justifyContent:'flex-end', padding:DL.sp.sm }}>
                <span style={{ fontFamily:DL.mono, fontSize:8.5, color:DL.l_inkMuted, letterSpacing:'0.06em' }}>{c}</span>
              </div>
            ))}
          </div>
          <div style={{ fontFamily:DL.mono, fontSize:10, color:DL.inkMuted, lineHeight:1.65 }}>
            Page canvas is paper (#f7f4ee), never #fff. Cards lift via paperSoft, not shadow.
          </div>
        </DLBox>
      </div>

      {/* Semantic functional colors */}
      <div style={{ marginTop:14 }}>
        <div style={{ fontFamily:DL.mono, fontSize:9.5, color:DL.inkMuted, letterSpacing:'0.14em', marginBottom:DL.sp.sm }}>SEMANTIC · WHEN TO USE EACH</div>
        <div style={{ display:'grid', gridTemplateColumns:'repeat(5, 1fr)', gap:DL.sp.sm }}>
          {[
            ['accent','terra · #d97757','primary action · brand · selection'],
            ['cyan','drafting · #5fb3b3','technical · system · code keys'],
            ['ok','verdigris · #7ec18e','success · connected · fresh'],
            ['warn','patina · #e5b25a','healing · stale · attention'],
            ['err','brick · #e6705f','destructive · failure · only here'],
          ].map(([n, hex, when]) => {
            const c = DL[n];
            return (
              <div key={n} style={{ background:DL.bgPanel, border:`1px solid ${DL.line}`, borderRadius:DL.rad.md, padding:DL.sp.md }}>
                <div style={{ width:'100%', height:32, background:c, borderRadius:4, marginBottom:DL.sp.sm }}/>
                <div style={{ fontFamily:DL.mono, fontSize:9.5, color:DL.inkMuted, letterSpacing:'0.06em' }}>{hex.toUpperCase()}</div>
                <div style={{ fontSize:11.5, color:DL.inkSoft, marginTop:DL.sp.xs, lineHeight:1.4 }}>{when}</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Contrast pairs */}
      <div style={{ marginTop:14 }}>
        <div style={{ fontFamily:DL.mono, fontSize:9.5, color:DL.inkMuted, letterSpacing:'0.14em', marginBottom:DL.sp.sm }}>CONTRAST · WCAG AA ≥ 4.5:1 BODY · ≥ 3:1 CAPTIONS</div>
        <div style={{ display:'grid', gridTemplateColumns:'repeat(4, 1fr)', gap:DL.sp.sm }}>
          {[
            ['ink on bg',      DL.ink,      DL.bg,      '14.8:1 AAA'],
            ['inkSoft on bg',  DL.inkSoft,  DL.bg,      '6.2:1 AA'],
            ['inkMuted on bg', DL.inkMuted, DL.bg,      '3.1:1 AA(captions)'],
            ['accent on bg',   DL.accent,   DL.bg,      '5.4:1 AA'],
          ].map(([n, fg, bg, r]) => (
            <div key={n} style={{ background:bg, border:`1px solid ${DL.line}`, borderRadius:DL.rad.md, padding:14 }}>
              <div style={{ color:fg, fontSize:13, fontFamily:DL.sans }}>The quick brown fox</div>
              <div style={{ fontFamily:DL.mono, fontSize:9.5, color:DL.inkMuted, marginTop:6, letterSpacing:'0.05em' }}>{n} · {r}</div>
            </div>
          ))}
        </div>
      </div>
    </DLSection>

    {/* ═════════ 04 · TYPE SYSTEM ═════════ */}
    <DLSection num="04" title="Type system" sub="three voices · serif · sans · mono">
      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:14 }}>
        {[
          ['DISPLAY · INSTRUMENT SERIF', DL.serif, 'Aa', '400 / italic', 'Headlines, hero copy, the wordmark, room-headings. Italic carries warmth.'],
          ['UI · INTER', DL.sans, 'Aa', '400 / 500 / 600', 'Body, buttons, inputs. Quiet, neutral, hard-working.'],
          ['DATA · JETBRAINS MONO', DL.mono, 'Aa', '400 / 500', 'Parameters, status bar, code, IDs, times. Tells you it is measured.'],
        ].map(([lab, fam, ch, w, note]) => (
          <DLBox key={lab} label={lab}>
            <div style={{ fontFamily:fam, fontSize:80, lineHeight:0.95, letterSpacing:'-0.03em' }}>{ch}</div>
            <div style={{ fontFamily:fam, fontStyle:fam===DL.serif?'italic':'normal', fontSize:24, color:DL.inkSoft, marginTop:DL.sp.xs }}>{ch} Bb Gg Rr</div>
            <div style={{ fontFamily:DL.mono, fontSize:10, color:DL.inkMuted, letterSpacing:'0.05em' }}>{w}</div>
            <div style={{ fontSize:12.5, color:DL.inkSoft, lineHeight:1.5 }}>{note}</div>
          </DLBox>
        ))}
      </div>

      {/* Full scale */}
      <div style={{ marginTop:14, background:DL.bgPanel, border:`1px solid ${DL.line}`, borderRadius:DL.rad.lg, padding:'22px 26px' }}>
        <div style={{ fontFamily:DL.mono, fontSize:10, color:DL.inkMuted, letterSpacing:'0.14em', marginBottom:18 }}>SCALE · 11 STEPS</div>
        {[
          ['D1', 88, DL.serif, false, 'Drafting table for AI.', 'tracking -3% · lh 0.92'],
          ['D2', 56, DL.serif, false, 'Talk to your AEC stack.', 'tracking -2.5% · lh 0.95'],
          ['H1', 40, DL.serif, false, 'Connectors that heal themselves.', 'tracking -2% · lh 1.05'],
          ['H2', 24, DL.serif, true,  'Drop a connection — we put it back.', 'italic · tracking -1% · lh 1.15'],
          ['H3', 21, DL.serif, false, 'Skills, not prompts.', 'tracking -1% · lh 1.2'],
          ['B+', 16, DL.sans,  false, 'Body large — composer placeholder, inline editors.', 'tracking 0 · lh 1.55'],
          ['B',  14, DL.sans,  false, 'Body — chat bubbles, list rows, descriptions.', 'tracking 0 · lh 1.55'],
          ['B-', 13, DL.sans,  false, 'Body small — secondary text, dense lists.', 'tracking 0 · lh 1.5'],
          ['M',  12, DL.mono,  false, 'Mono data — params, prices, tokens.', 'tracking 2% · lh 1.5'],
          ['M-', 11, DL.mono,  false, 'mono muted — captions, timestamps.', 'tracking 4% · lh 1.55'],
          ['cap',  9, DL.mono, false, 'CAPS · 14% TRACKING · SECTION LABELS', 'all caps · tracking 12% · lh 1.4'],
        ].map(r => (
          <div key={r[0]} style={{ display:'grid', gridTemplateColumns:'40px 50px 1fr 240px', gap:18, alignItems:'baseline', padding:'7px 0', borderBottom:`1px dashed ${DL.lineSoft}` }}>
            <span style={{ fontFamily:DL.mono, fontSize:10, color:DL.accent, letterSpacing:'0.06em' }}>{r[0]}</span>
            <span style={{ fontFamily:DL.mono, fontSize:10, color:DL.inkMuted }}>{r[1]}px</span>
            <span style={{ fontFamily:r[2], fontStyle:r[3]?'italic':'normal', fontSize:Math.min(r[1], 32), color:DL.ink, letterSpacing:r[1]>30?'-0.02em':'0', textTransform: r[0]==='cap' ? 'uppercase' : 'none' }}>{r[4]}</span>
            <span style={{ fontFamily:DL.mono, fontSize:9.5, color:DL.inkMuted, letterSpacing:'0.04em', textAlign:'right' }}>{r[5]}</span>
          </div>
        ))}
      </div>
    </DLSection>

    {/* ═════════ 05 · SPACING & GRID ═════════ */}
    <DLSection num="05" title="Spacing & grid" sub="4pt base · 8 steps · 12-col grid · 3 density modes">
      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:14 }}>
        <DLBox label="SPACING · 4PT">
          {[['xs',4],['sm',8],['md',12],['lg',16],['xl',24],['2xl',32],['3xl',40],['4xl',56]].map(([n,v]) => (
            <div key={n} style={{ display:'flex', alignItems:'center', gap:10, padding:'2px 0' }}>
              <span style={{ fontFamily:DL.mono, fontSize:10, color:DL.inkMuted, width:34 }}>{n}</span>
              <span style={{ fontFamily:DL.mono, fontSize:10, color:DL.inkSoft, width:30 }}>{v}</span>
              <div style={{ width:v, height:10, background:DL.accent, borderRadius:2 }}/>
            </div>
          ))}
        </DLBox>
        <DLBox label="RADIUS">
          {[['xs',3],['sm',5],['md',6],['lg',8],['xl',10],['pill',999]].map(([n,r]) => (
            <div key={n} style={{ display:'flex', alignItems:'center', gap:DL.sp.md, padding:'3px 0' }}>
              <div style={{ width:32, height:32, background:DL.accentSoft, border:`1px solid ${DL.accent}`, borderRadius:r }}/>
              <span style={{ fontFamily:DL.mono, fontSize:10, color:DL.inkSoft, width:40 }}>{n}</span>
              <span style={{ fontFamily:DL.mono, fontSize:10, color:DL.inkMuted }}>{r === 999 ? 'pill' : `${r}px`}</span>
            </div>
          ))}
        </DLBox>
        <DLBox label="DENSITY · 3 MODES" sub="rail row · 32 / 26 / 22">
          {[['comfortable', 32, 'default · most users'], ['compact', 26, 'studio · power users'], ['cozy', 22, 'large monitors · dense data']].map(([n, h, note]) => (
            <div key={n} style={{ padding:'4px 0' }}>
              <div style={{ display:'flex', alignItems:'center', gap:DL.sp.sm, fontFamily:DL.mono, fontSize:10, color:DL.inkSoft, letterSpacing:'0.04em', marginBottom:3 }}>
                <span style={{ width:74 }}>{n}</span><span style={{ color:DL.inkMuted }}>{h}px</span>
              </div>
              <div style={{ height:h, background:DL.bgSoft, border:`1px solid ${DL.lineSoft}`, borderRadius:DL.rad.sm, padding:`0 10px`, display:'flex', alignItems:'center', gap:DL.sp.sm, fontSize:12.5, color:DL.inkSoft }}>
                <span style={{ width:6, height:6, borderRadius:'50%', background:DL.ok }}/>Revit · :7331
              </div>
              <div style={{ fontFamily:DL.mono, fontSize:9, color:DL.inkMuted, marginTop:2, letterSpacing:'0.04em' }}>{note}</div>
            </div>
          ))}
        </DLBox>
      </div>

      {/* Grid visualization */}
      <div style={{ marginTop:14 }}>
        <DLBox label="12-COL GRID" sub="248 rail · 1fr center · 288 inspector · 16 gutters">
          <div style={{ display:'grid', gridTemplateColumns:'248px 1fr 288px', gap:DL.sp.lg, height:140 }}>
            <div style={{ background:DL.bgSoft, borderRadius:DL.rad.md, padding:10, fontFamily:DL.mono, fontSize:10, color:DL.inkMuted, letterSpacing:'0.06em' }}>RAIL · 248</div>
            <div style={{ background:DL.bgSoft, borderRadius:DL.rad.md, padding:10, fontFamily:DL.mono, fontSize:10, color:DL.inkMuted, letterSpacing:'0.06em', display:'grid', gridTemplateColumns:'repeat(12, 1fr)', gap:DL.sp.xs }}>
              {Array.from({length:12}).map((_, i) => (
                <div key={i} style={{ background:DL.bg, borderRadius:DL.rad.xs, display:'grid', placeItems:'center', fontFamily:DL.mono, fontSize:8, color:DL.inkMuted, letterSpacing:'0.04em' }}>{i+1}</div>
              ))}
            </div>
            <div style={{ background:DL.bgSoft, borderRadius:DL.rad.md, padding:10, fontFamily:DL.mono, fontSize:10, color:DL.inkMuted, letterSpacing:'0.06em' }}>INSPECTOR · 288</div>
          </div>
        </DLBox>
      </div>
    </DLSection>

    {/* ═════════ 06 · COMPONENT STATES ═════════ */}
    <DLSection num="06" title="Component states" sub="every interaction state, drawn — never inferred">
      {/* Buttons */}
      <DLBox label="PRIMARY BUTTON · 5 STATES">
        <div style={{ display:'grid', gridTemplateColumns:'repeat(5, 1fr)', gap:10, padding:'8px 0' }}>
          {[
            { l:'default',  s:{ background:DL.accent, color: (window.AH && window.AH.onFill) || '#180f08' } },
            { l:'hover',    s:{ background:DL.accentHi, color: (window.AH && window.AH.onFill) || '#180f08' } },
            { l:'active',   s:{ background:DL.accentPress, color: (window.AH && window.AH.onFill) || '#180f08', transform:'translateY(1px)' } },
            { l:'focus',    s:{ background:DL.accent, color: (window.AH && window.AH.onFill) || '#180f08', boxShadow:`0 0 0 3px ${DL.accent}55, 0 0 0 5px ${DL.bg}` } },
            { l:'disabled', s:{ background:DL.bgSoft, color:DL.inkMuted, cursor:'not-allowed' } },
          ].map(it => (
            <div key={it.l} style={{ display:'flex', flexDirection:'column', alignItems:'center', gap:DL.sp.sm }}>
              <button style={{ padding:'7px 14px', borderRadius:DL.rad.sm, border:0, fontSize:13, fontWeight:500, fontFamily:DL.sans, transition:'all .12s', ...it.s }}>Run skill</button>
              <span style={{ fontFamily:DL.mono, fontSize:9.5, color:DL.inkMuted, letterSpacing:'0.1em' }}>{it.l.toUpperCase()}</span>
            </div>
          ))}
        </div>
      </DLBox>

      {/* Inputs */}
      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:14, marginTop:14 }}>
        <DLBox label="TEXT INPUT · 5 STATES">
          {[
            { l:'default', v:'Tower A — north elevation', bd:DL.line, msg:null },
            { l:'focus',   v:'Tower A — north elevation', bd:DL.accent, msg:null, ring:true },
            { l:'filled',  v:'Generic 200mm', bd:DL.line, msg:'wall type', hint:'2/9 matches' },
            { l:'error',   v:'tower-a-/!', bd:DL.err, msg:'Name cannot contain "/" or "!"' },
            { l:'disabled',v:'(locked)', bd:DL.lineSoft, msg:null, dis:true },
          ].map((it, i) => (
            <div key={i}>
              <div style={{ display:'flex', alignItems:'center', gap:DL.sp.sm, marginBottom:3 }}>
                <span style={{ fontFamily:DL.mono, fontSize:9.5, color:DL.inkMuted, letterSpacing:'0.1em', width:60 }}>{it.l.toUpperCase()}</span>
                {it.hint && <span style={{ fontFamily:DL.mono, fontSize:9.5, color:DL.inkMuted }}>{it.hint}</span>}
              </div>
              <input value={it.v} readOnly style={{
                width:'100%', padding:'7px 10px', borderRadius:DL.rad.sm,
                border:`1px solid ${it.bd}`,
                background:it.dis?DL.bgSoft:DL.bg, color:it.dis?DL.inkMuted:DL.ink,
                fontFamily:DL.sans, fontSize:13, outline:'none',
                boxShadow: it.ring ? `0 0 0 3px ${DL.accent}33` : 'none',
                opacity: it.dis ? 0.7 : 1,
              }}/>
              {it.msg && <div style={{ fontFamily:DL.mono, fontSize:10, color: it.l==='error'?DL.err:DL.inkMuted, marginTop:3, letterSpacing:'0.04em' }}>{it.msg}</div>}
            </div>
          ))}
        </DLBox>

        <DLBox label="TOGGLE · 4 STATES">
          <div style={{ display:'grid', gridTemplateColumns:'repeat(2, 1fr)', gap:DL.sp.md }}>
            {[
              { l:'off',           on:false, dis:false },
              { l:'on',            on:true,  dis:false },
              { l:'off · disabled',on:false, dis:true },
              { l:'on · disabled', on:true,  dis:true },
            ].map(it => (
              <div key={it.l} style={{ display:'flex', alignItems:'center', gap:9, padding:'8px 10px', background:DL.bg, borderRadius:DL.rad.sm, opacity: it.dis?0.5:1 }}>
                <div style={{ width:34, height:18, borderRadius:999, background:it.on?DL.accent:DL.lineSoft, position:'relative', cursor:it.dis?'not-allowed':'pointer' }}>
                  <div style={{ position:'absolute', top:2, left:it.on?18:2, width:14, height:14, borderRadius:'50%', background:'#fff' }}/>
                </div>
                <span style={{ fontFamily:DL.mono, fontSize:11, color:DL.inkSoft, letterSpacing:'0.04em' }}>{it.l}</span>
              </div>
            ))}
          </div>
          <div style={{ fontFamily:DL.mono, fontSize:10, color:DL.inkMuted, lineHeight:1.6 }}>
            Visual 34×18 · hit area ≥ 36×24. Always paired with a clickable label that toggles too.
          </div>
        </DLBox>
      </div>

      {/* Chip / pill */}
      <DLBox label="CHIP · PILL · 4 KINDS" style={{ marginTop:14 }}>
        <div style={{ display:'flex', flexWrap:'wrap', gap:DL.sp.sm, padding:'4px 0' }}>
          {[
            { l:'NEUTRAL',     bg:DL.bgSoft, c:DL.inkSoft, bd:DL.line },
            { l:'ACCENT',      bg:DL.accentSoft, c:DL.accent, bd:DL.accent+'55' },
            { l:'OK · 18 RUNS',bg:DL.ok+'15', c:DL.ok, bd:DL.ok+'33' },
            { l:'WARN · STALE',bg:DL.warn+'15', c:DL.warn, bd:DL.warn+'33' },
            { l:'ERR · FAILED',bg:DL.err+'15', c:DL.err, bd:DL.err+'33' },
            { l:'CYAN · SYSTEM', bg:DL.cyan+'15', c:DL.cyan, bd:DL.cyan+'33' },
          ].map(c => (
            <span key={c.l} style={{ padding:'3px 9px', borderRadius:999, background:c.bg, color:c.c, border:`1px solid ${c.bd}`, fontFamily:DL.mono, fontSize:10.5, letterSpacing:'0.06em' }}>{c.l}</span>
          ))}
        </div>
      </DLBox>

      {/* Row */}
      <DLBox label="LIST ROW · 5 STATES" style={{ marginTop:14 }}>
        {[
          { l:'default',  bg:'transparent' },
          { l:'hover',    bg:DL.bgHover },
          { l:'active',   bg:DL.bgSoft, accent:true },
          { l:'selected', bg:DL.accentSoft, mark:true },
          { l:'disabled', bg:'transparent', dis:true },
        ].map(it => (
          <div key={it.l} style={{ display:'flex', alignItems:'center', gap:10, padding:'8px 12px', background:it.bg, borderRadius:DL.rad.sm, opacity:it.dis?0.5:1, position:'relative', borderLeft: it.accent ? `2px solid ${DL.accent}` : '2px solid transparent', paddingLeft: it.accent ? 10 : 12 }}>
            {it.mark && <span style={{ width:3, height:18, background:DL.accent, borderRadius:2 }}/>}
            <span style={{ width:7, height:7, borderRadius:'50%', background:DL.ok, boxShadow:`0 0 0 3px ${DL.ok}22` }}/>
            <span style={{ flex:1, fontSize:13 }}>Schedule wall types</span>
            <span style={{ fontFamily:DL.mono, fontSize:10, color:DL.inkMuted }}>12m</span>
            <span style={{ fontFamily:DL.mono, fontSize:9.5, color:DL.inkMuted, width:80, textAlign:'right', letterSpacing:'0.06em', textTransform:'uppercase' }}>{it.l}</span>
          </div>
        ))}
      </DLBox>
    </DLSection>

    {/* ═════════ 07 · MOTION ═════════ */}
    <DLSection num="07" title="Motion principles" sub="things settle, dimension, heal · never bounce">
      <div style={{ display:'grid', gridTemplateColumns:'repeat(4, 1fr)', gap:14 }}>
        {[
          { t:'Settle',     d:'180 ms · ease-out (.2,.8,.2,1)', n:'Things land. Never overshoot. Never bounce.' },
          { t:'Dimension',  d:'240 ms · ease-out · stagger 40ms', n:'Lines extend, numbers fade in. The drawing thinks aloud.' },
          { t:'Heal',       d:'1.1 s · pulse · infinite', n:'Calm, not alarming. Only on patina/warn states.' },
          { t:'Cascade',    d:'200 ms × N stages · ease-out', n:'Stage chips re-run sequentially, never simultaneously.' },
        ].map(m => (
          <DLBox key={m.t} label={m.t.toUpperCase()}>
            <div style={{ fontFamily:DL.serif, fontSize:24, letterSpacing:'-0.015em' }}>{m.t}</div>
            <div style={{ fontFamily:DL.mono, fontSize:10, color:DL.accent, letterSpacing:'0.05em' }}>{m.d}</div>
            <div style={{ fontSize:12, color:DL.inkSoft, lineHeight:1.5 }}>{m.n}</div>
          </DLBox>
        ))}
      </div>

      <div style={{ marginTop:14, display:'grid', gridTemplateColumns:'1fr 1fr', gap:14 }}>
        <DLBox label="DURATIONS · 4 STEPS">
          {[['instant',60,'tooltip · select'],['fast',120,'hover · chip'],['med',180,'page · slide'],['slow',240,'overlay · cascade']].map(([n, ms, when]) => (
            <div key={n} style={{ display:'grid', gridTemplateColumns:'80px 60px 1fr', gap:10, alignItems:'baseline', padding:'4px 0', borderBottom:`1px dashed ${DL.lineSoft}` }}>
              <span style={{ fontFamily:DL.mono, fontSize:11, color:DL.ink }}>{n}</span>
              <span style={{ fontFamily:DL.mono, fontSize:11, color:DL.accent }}>{ms}ms</span>
              <span style={{ fontFamily:DL.mono, fontSize:10.5, color:DL.inkMuted }}>{when}</span>
            </div>
          ))}
        </DLBox>
        <DLBox label="EASINGS · 2 STEPS">
          <div style={{ padding:'4px 0' }}>
            <div style={{ display:'flex', gap:10, alignItems:'baseline', fontFamily:DL.mono, fontSize:11, marginBottom:DL.sp.xs }}>
              <span style={{ color:DL.ink, width:60 }}>ease-out</span>
              <span style={{ color:DL.accent, fontSize:10 }}>cubic-bezier(0.2, 0.8, 0.2, 1)</span>
            </div>
            <div style={{ fontFamily:DL.mono, fontSize:10, color:DL.inkMuted, marginBottom:10 }}>Almost everything. Things arriving feel certain.</div>
            <div style={{ display:'flex', gap:10, alignItems:'baseline', fontFamily:DL.mono, fontSize:11, marginBottom:DL.sp.xs }}>
              <span style={{ color:DL.ink, width:60 }}>ease-in</span>
              <span style={{ color:DL.accent, fontSize:10 }}>cubic-bezier(0.4, 0, 1, 1)</span>
            </div>
            <div style={{ fontFamily:DL.mono, fontSize:10, color:DL.inkMuted }}>Only for exits. Things leaving feel decisive.</div>
          </div>
        </DLBox>
      </div>

      <DLBox label="DO / DON'T" style={{ marginTop:14 }}>
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:14 }}>
          <div>
            <div style={{ fontFamily:DL.mono, fontSize:10, color:DL.ok, letterSpacing:'0.12em', marginBottom:6 }}>YES</div>
            <ul style={{ margin:0, padding:'0 0 0 18px', fontSize:13, color:DL.inkSoft, lineHeight:1.6, listStyle:'none' }}>
              <li style={{ marginBottom:DL.sp.xs }}>· Use ease-out for arrivals · ease-in for exits</li>
              <li style={{ marginBottom:DL.sp.xs }}>· Stagger when sequential (cascade, list-in)</li>
              <li style={{ marginBottom:DL.sp.xs }}>· Honor prefers-reduced-motion · drop to opacity</li>
              <li>· Pulse only the healing dot · nothing else loops</li>
            </ul>
          </div>
          <div>
            <div style={{ fontFamily:DL.mono, fontSize:10, color:DL.err, letterSpacing:'0.12em', marginBottom:6 }}>NO</div>
            <ul style={{ margin:0, padding:'0 0 0 18px', fontSize:13, color:DL.inkMuted, lineHeight:1.6, listStyle:'none', textDecoration:'line-through', textDecorationColor:DL.err+'88' }}>
              <li style={{ marginBottom:DL.sp.xs }}>· Spring overshoot — the interface is a tool</li>
              <li style={{ marginBottom:DL.sp.xs }}>· 60-frame celebrations on completion</li>
              <li style={{ marginBottom:DL.sp.xs }}>· Floating particles, parallax, depth blur</li>
              <li>· Sound effects unless the user opts in</li>
            </ul>
          </div>
        </div>
      </DLBox>
    </DLSection>

    {/* ═════════ 08 · ICONOGRAPHY ═════════ */}
    <DLSection num="08" title="Iconography" sub="1.5px stroke · 18×18 grid · drafted, not drawn">
      <div style={{ display:'grid', gridTemplateColumns:'2fr 1fr', gap:14 }}>
        <DLBox label="SET · 16 ICONS">
          <div style={{ display:'grid', gridTemplateColumns:'repeat(8, 1fr)', gap:6 }}>
            {Object.entries({
              arch:    'M3 17 V10 a6 6 0 0 1 12 0 V17',
              node:    'M9 9 a2 2 0 1 0 0 4 a2 2 0 1 0 0 -4 M5 11 H3 M15 11 H13 M9 5 v3 M9 13 v3',
              chain:   'M5 5 h4 v4 H5z M9 13 h4 v4 H9z M7 9 V13',
              dim:     'M3 9 H15 M3 7 V11 M15 7 V11',
              beam:    'M3 6 H15 M3 12 H15 M5 6 V12 M9 6 V12 M13 6 V12',
              door:    'M5 16 V4 h8 v12 M11 10 v1',
              spark:   'M9 3 L10 8 L15 9 L10 10 L9 15 L8 10 L3 9 L8 8z',
              layers:  'M9 3 L15 6 L9 9 L3 6z M3 10 L9 13 L15 10 M3 13 L9 16 L15 13',
              scale:   'M3 9 H15 M5 9 V5 H7 V9 M11 9 V7 H13 V9',
              pulse:   'M3 9 H6 L8 5 L11 13 L13 9 H15',
              key:     'M9 4 a3 3 0 0 1 0 6 v8 M7 16 H9 M7 14 H9',
              grid:    'M3 3 H15 V15 H3z M3 9 H15 M9 3 V15',
              plug:    'M7 3 V7 M11 3 V7 M5 7 H13 V11 a4 4 0 0 1 -8 0 V7 M9 15 V17',
              skill:   'M9 2 L11 6 L15 6.5 L12 9 L13 13 L9 11 L5 13 L6 9 L3 6.5 L7 6z',
              chat:    'M3 4 H15 V12 H8 L4 16 V12 H3z',
              flow:    'M3 5 H8 V15 H13 M11 13 L13 15 L15 13',
            }).map(([n, d]) => (
              <div key={n} style={{ display:'flex', flexDirection:'column', alignItems:'center', gap:5, padding:'10px 0', background:DL.bg, border:`1px solid ${DL.lineSoft}`, borderRadius:DL.rad.sm }}>
                <svg width="22" height="22" viewBox="0 0 18 18" fill="none" stroke={DL.ink} strokeWidth="1.5" strokeLinecap="square" strokeLinejoin="miter">
                  <path d={d}/>
                </svg>
                <span style={{ fontFamily:DL.mono, fontSize:8.5, color:DL.inkMuted, letterSpacing:'0.04em' }}>{n}</span>
              </div>
            ))}
          </div>
        </DLBox>
        <DLBox label="RULES">
          <ul style={{ margin:0, padding:'0 0 0 18px', fontSize:13, lineHeight:1.6, color:DL.inkSoft }}>
            <li style={{ marginBottom:5 }}>1.5px stroke at 18px. Scales linearly.</li>
            <li style={{ marginBottom:5 }}>Square caps. Miter joins. No round terminals.</li>
            <li style={{ marginBottom:5 }}>Geometric, not symbolic. A door is a door.</li>
            <li style={{ marginBottom:5 }}>Inherit currentColor. Never a fixed hue.</li>
            <li>One weight only — no filled/outlined twins.</li>
          </ul>
          <div style={{ marginTop:10, padding:10, background:DL.bgSoft, borderRadius:DL.rad.sm, fontFamily:DL.mono, fontSize:10, color:DL.inkSoft, lineHeight:1.6 }}>
            stroke = 1.5px<br/>
            box    = 18×18<br/>
            keyline= 1u from edge<br/>
            caps   = square<br/>
            joins  = miter
          </div>
        </DLBox>
      </div>
    </DLSection>

    {/* ═════════ 09 · STATES (empty / loading / error) ═════════ */}
    <DLSection num="09" title="States" sub="empty · loading · error · zero-data — drawn, never blanked">
      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:14 }}>
        <DLBox label="EMPTY · NO SKILLS YET">
          <div style={{ minHeight:200, display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', gap:10, background:DL.bg, border:`1px dashed ${DL.line}`, borderRadius:DL.rad.md }}>
            <Mark size={42} color={DL.inkMuted} bg={DL.bg}/>
            <div style={{ fontFamily:DL.serif, fontSize:18, color:DL.inkSoft, textAlign:'center' }}>No skills saved yet.</div>
            <div style={{ fontSize:12, color:DL.inkMuted, textAlign:'center', maxWidth:200, lineHeight:1.45 }}>Save your first useful chat — it becomes a Skill you can run again.</div>
            <button style={{ marginTop:6, padding:'6px 12px', background:DL.accent, color: (window.AH && window.AH.onFill) || '#180f08', border:0, borderRadius:DL.rad.sm, fontSize:12, fontWeight:500, cursor:'pointer' }}>+ Capture from chat</button>
          </div>
        </DLBox>
        <DLBox label="LOADING · GENERATING">
          <div style={{ minHeight:200, display:'flex', flexDirection:'column', gap:10, padding:DL.sp.md, background:DL.bg, border:`1px solid ${DL.line}`, borderRadius:DL.rad.md }}>
            <div style={{ display:'flex', alignItems:'center', gap:DL.sp.sm }}>
              <span style={{ width:8, height:8, borderRadius:'50%', background:DL.accent, animation:'studPulse 1.1s infinite' }}/>
              <span style={{ fontFamily:DL.mono, fontSize:10, color:DL.accent, letterSpacing:'0.1em' }}>STAGE 4/5</span>
              <div style={{ flex:1 }}/>
              <span style={{ fontFamily:DL.mono, fontSize:10, color:DL.inkMuted }}>~8s</span>
            </div>
            <div style={{ fontFamily:DL.serif, fontSize:15, color:DL.ink, lineHeight:1.4 }}>Placing doors and windows…</div>
            {/* Skeleton lines */}
            {[100, 80, 60, 90].map((w, i) => (
              <div key={i} style={{ width:`${w}%`, height:8, borderRadius:DL.rad.xs, background:`linear-gradient(90deg, ${DL.bgSoft}, ${DL.bgHover}, ${DL.bgSoft})`, backgroundSize:'200% 100%', animation:`studShimmer 1.4s infinite linear ${i*0.15}s` }}/>
            ))}
            <style>{`@keyframes studShimmer { 0% { background-position: -200% 0 } 100% { background-position: 200% 0 } }`}</style>
            <div style={{ marginTop:'auto', fontFamily:DL.mono, fontSize:10, color:DL.inkMuted }}>· asking revit for active view…</div>
          </div>
        </DLBox>
        <DLBox label="ERROR · ALWAYS WITH A FIX">
          <div style={{ minHeight:200, padding:DL.sp.md, background:DL.err+'08', border:`1px solid ${DL.err}33`, borderRadius:DL.rad.md, display:'flex', flexDirection:'column', gap:10 }}>
            <div style={{ display:'flex', alignItems:'center', gap:DL.sp.sm }}>
              <span style={{ fontFamily:DL.mono, fontSize:10, color:DL.err, letterSpacing:'0.1em' }}>● COULDN'T REACH REVIT</span>
            </div>
            <div style={{ fontFamily:DL.serif, fontSize:17, color:DL.ink, lineHeight:1.35, letterSpacing:'-0.01em' }}>Revit isn't responding on :7331.</div>
            <div style={{ fontSize:12.5, color:DL.inkSoft, lineHeight:1.5 }}>Most likely the addin is loading. We'll retry every 1.2s for 30s, then offer to regenerate the bridge.</div>
            <div style={{ marginTop:'auto', display:'flex', gap:6 }}>
              <button style={{ flex:1, padding:'6px 10px', background:'transparent', color:DL.inkSoft, border:`1px solid ${DL.line}`, borderRadius:DL.rad.sm, fontSize:12, cursor:'pointer' }}>Show logs</button>
              <button style={{ flex:1, padding:'6px 10px', background:DL.accent, color: (window.AH && window.AH.onFill) || '#180f08', border:0, borderRadius:DL.rad.sm, fontSize:12, fontWeight:500, cursor:'pointer' }}>Heal now ↻</button>
            </div>
          </div>
        </DLBox>
      </div>
    </DLSection>

    {/* ═════════ 10 · ACCESSIBILITY ═════════ */}
    <DLSection num="10" title="Accessibility" sub="WCAG AA · keyboard-first · 28×28 tap minimum">
      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:14 }}>
        <DLBox label="FOCUS RINGS">
          <div style={{ display:'flex', gap:10, padding:'8px 0' }}>
            <button style={{ padding:'7px 14px', borderRadius:DL.rad.sm, border:0, background:DL.accent, color: (window.AH && window.AH.onFill) || '#180f08', fontSize:13, fontWeight:500, boxShadow:`0 0 0 3px ${DL.accent}55, 0 0 0 5px ${DL.bg}`, fontFamily:DL.sans }}>Focused</button>
            <input value="focused input" readOnly style={{ padding:'7px 10px', borderRadius:DL.rad.sm, border:`1px solid ${DL.accent}`, background:DL.bg, color:DL.ink, fontSize:13, outline:'none', boxShadow:`0 0 0 3px ${DL.accent}33`, fontFamily:DL.sans }}/>
          </div>
          <div style={{ fontFamily:DL.mono, fontSize:10, color:DL.inkMuted, lineHeight:1.6 }}>
            2px accent ring · 3px gap to nearest border · always visible on keyboard focus (Qt6 StrongFocus + :focus-visible). Never suppressed.
          </div>
        </DLBox>
        <DLBox label="HIT TARGETS">
          <div style={{ display:'flex', gap:14, padding:'8px 0', alignItems:'center' }}>
            <div style={{ position:'relative', display:'flex', alignItems:'center', justifyContent:'center', width:36, height:36, background:DL.accent+'22', borderRadius:DL.rad.lg }}>
              <div style={{ width:24, height:24, background:DL.accent, borderRadius:4, display:'grid', placeItems:'center', color: (window.AH && window.AH.onFill) || '#180f08', fontFamily:DL.mono, fontSize:11 }}>+</div>
              <div style={{ position:'absolute', inset:0, border:`1px dashed ${DL.accent}55`, borderRadius:DL.rad.lg }}/>
            </div>
            <div style={{ fontFamily:DL.mono, fontSize:10, color:DL.inkSoft, lineHeight:1.6 }}>
              <div>visual: 24×24 (minimum)</div>
              <div>hit:    36×36 (minimum)</div>
              <div style={{ color:DL.inkMuted }}>relaxed from mobile 44 — this is desktop.</div>
            </div>
          </div>
        </DLBox>
        <DLBox label="REDUCED MOTION">
          <div style={{ fontFamily:DL.mono, fontSize:11, color:DL.inkSoft, lineHeight:1.7, padding:'6px 0' }}>
            <div>@media (prefers-reduced-motion: reduce) {'{'}</div>
            <div style={{ paddingLeft:14, color:DL.accent }}>animation-duration: 0.01ms</div>
            <div style={{ paddingLeft:14, color:DL.accent }}>transition: opacity .12s</div>
            <div>{'}'}</div>
          </div>
          <div style={{ fontFamily:DL.mono, fontSize:10, color:DL.inkMuted, lineHeight:1.6 }}>
            Movement collapses to opacity. Heal pulse stops. Cascades become instant. No info is lost.
          </div>
        </DLBox>
      </div>

      <DLBox label="KEYBOARD MAP · 18 SHORTCUTS" style={{ marginTop:14 }}>
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:18 }}>
          {[
            { group:'GLOBAL', items:[
              ['⌘K','command palette'],
              ['⌘N','new chat'],
              ['⌘,','settings'],
              ['⌘⇧L','toggle theme'],
              ['⌘1–5','switch view'],
              ['⌘/','docs'],
            ]},
            { group:'CHAT', items:[
              ['↵','send'],
              ['⇧↵','newline'],
              ['⌘↑','edit last'],
              ['⌘⇧E','fork from cursor'],
              ['⌘.','stop streaming'],
              ['⌘R','regenerate'],
            ]},
            { group:'CANVAS · WORKFLOW', items:[
              ['Space + drag','pan'],
              ['Drag','move node'],
              ['Drag socket','connect'],
              ['Del / ⌫','remove'],
              ['F','focus selection'],
              ['⌘D','duplicate'],
            ]},
          ].map(g => (
            <div key={g.group}>
              <div style={{ fontFamily:DL.mono, fontSize:9.5, color:DL.accent, letterSpacing:'0.14em', marginBottom:DL.sp.sm }}>{g.group}</div>
              {g.items.map(([k, v]) => (
                <div key={k} style={{ display:'flex', alignItems:'center', gap:10, padding:'4px 0', borderBottom:`1px dashed ${DL.lineSoft}` }}>
                  <kbd style={{ fontFamily:DL.mono, fontSize:10.5, padding:'2px 7px', background:DL.bg, border:`1px solid ${DL.line}`, borderRadius:4, color:DL.ink, minWidth:90, textAlign:'center' }}>{k}</kbd>
                  <span style={{ fontSize:12.5, color:DL.inkSoft, flex:1 }}>{v}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      </DLBox>
    </DLSection>

    {/* ═════════ 11 · VOICE & MICROCOPY ═════════ */}
    <DLSection num="11" title="Voice & microcopy" sub="how ArchHub speaks · every string follows these rules">
      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:14 }}>
        <DLBox label="VOICE · 6 RULES">
          {[
            'Calm. Like a senior architect, not an excited intern.',
            'Concrete. Numbers, units, files. Never "robust" or "leverage".',
            'Owns the craft. We talk about drawings, not "outputs".',
            'Quietly technical. No emoji. No exclamation points.',
            'Plural for systems. Singular for the architect.',
            'Time and money are always shown · never hidden.',
          ].map((r, i) => (
            <div key={i} style={{ display:'flex', gap:10, padding:'6px 0', borderBottom:`1px dashed ${DL.lineSoft}` }}>
              <span style={{ fontFamily:DL.mono, fontSize:10, color:DL.accent, minWidth:24 }}>{String(i+1).padStart(2,'0')}</span>
              <span style={{ fontFamily:DL.serif, fontSize:16, color:DL.ink, lineHeight:1.4, letterSpacing:'-0.005em' }}>{r}</span>
            </div>
          ))}
        </DLBox>
        <DLBox label="DO / DON'T · 6 PAIRS">
          {[
            ['Dimensioned 47 walls in active view.', 'Successfully completed your task! 🎉'],
            ['Revit dropped — reconnecting on :7331.', 'Oops! Something went wrong.'],
            ['Save this as a Skill — 3 clicks, JSON.', 'Unlock advanced workflows with Premium.'],
            ['$0.024 for that run. 4.2k tokens.', 'Approximate cost may vary.'],
            ['Ready in 1.8s.', 'Generating amazing content for you…'],
            ['Click Heal to retry the handshake.', 'Try clicking the button to fix this.'],
          ].map(([ok, bad], i) => (
            <div key={i} style={{ padding:'6px 0', borderBottom:`1px dashed ${DL.lineSoft}` }}>
              <div style={{ display:'flex', gap:DL.sp.sm, alignItems:'baseline' }}>
                <span style={{ fontFamily:DL.mono, fontSize:9.5, color:DL.ok, letterSpacing:'0.08em', minWidth:30 }}>YES</span>
                <span style={{ fontFamily:DL.serif, fontSize:14, color:DL.ink, flex:1, lineHeight:1.4 }}>{ok}</span>
              </div>
              <div style={{ display:'flex', gap:DL.sp.sm, alignItems:'baseline', marginTop:3 }}>
                <span style={{ fontFamily:DL.mono, fontSize:9.5, color:DL.err, letterSpacing:'0.08em', minWidth:30 }}>NO</span>
                <span style={{ fontFamily:DL.serif, fontSize:14, color:DL.inkMuted, flex:1, lineHeight:1.4, textDecoration:'line-through' }}>{bad}</span>
              </div>
            </div>
          ))}
        </DLBox>
      </div>

      <DLBox label="MICROCOPY · COMMON STRINGS" style={{ marginTop:14 }}>
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:14 }}>
          {[
            { h:'BUTTONS', items:[
              ['Primary CTA','Run skill · Send · Heal now · Install'],
              ['Secondary',  'Save preset · Show logs · View source'],
              ['Cancel',     'Cancel · Close · Discard · Pause'],
              ['Destructive','Delete · Remove · Reset · Disconnect'],
            ]},
            { h:'TIME & MONEY', items:[
              ['Latency','420 ms · 1.8 s · ~12 s'],
              ['Cost',   '$0.024 · $3/M tok · free · BYO key'],
              ['Tokens', '4.2k · 314 in · 412 out · 44k/200k ctx'],
              ['Files',  '12 sheets · 47 walls · 1.4 MB'],
            ]},
            { h:'STATUSES', items:[
              ['OK',      'Connected · Ready · Fresh · Synced'],
              ['Working', 'Reconnecting · Healing · Running · Indexing'],
              ['Off',     'Disabled · Paused · Idle · Off'],
              ['Failed',  'Couldn\'t reach Revit · Handshake timed out'],
            ]},
          ].map(g => (
            <div key={g.h}>
              <div style={{ fontFamily:DL.mono, fontSize:9.5, color:DL.accent, letterSpacing:'0.14em', marginBottom:DL.sp.sm }}>{g.h}</div>
              {g.items.map(([k, v]) => (
                <div key={k} style={{ padding:'5px 0', borderBottom:`1px dashed ${DL.lineSoft}` }}>
                  <div style={{ fontFamily:DL.mono, fontSize:9.5, color:DL.inkMuted, letterSpacing:'0.06em', marginBottom:2 }}>{k.toUpperCase()}</div>
                  <div style={{ fontFamily:DL.mono, fontSize:11, color:DL.inkSoft, lineHeight:1.45 }}>{v}</div>
                </div>
              ))}
            </div>
          ))}
        </div>
      </DLBox>
    </DLSection>

    {/* ═════════ 12 · DENSITY MAP ═════════ */}
    <DLSection num="12" title="Layout & rhythm" sub="3 zones · density rules · keep the eye moving">
      <div style={{ background:DL.bgPanel, border:`1px solid ${DL.line}`, borderRadius:DL.rad.lg, padding:14 }}>
        <div style={{ display:'grid', gridTemplateColumns:'248px 1fr 288px', gap:14, height:260 }}>
          <div style={{ background:DL.bg, border:`1px dashed ${DL.line}`, borderRadius:DL.rad.md, padding:DL.sp.md, display:'flex', flexDirection:'column', gap:6 }}>
            <span style={{ fontFamily:DL.mono, fontSize:9, color:DL.accent, letterSpacing:'0.14em' }}>RAIL · 248</span>
            <span style={{ fontFamily:DL.serif, fontSize:18, letterSpacing:'-0.01em' }}>Navigation</span>
            <span style={{ fontSize:11.5, color:DL.inkSoft, lineHeight:1.45 }}>Folders, threads, search. Dense rows, mono timestamps, color stripe on active.</span>
            <div style={{ flex:1 }}/>
            <span style={{ fontFamily:DL.mono, fontSize:9, color:DL.inkMuted, letterSpacing:'0.06em' }}>row 26 · gap 4 · radius 5</span>
          </div>
          <div style={{ background:DL.bg, border:`1px dashed ${DL.line}`, borderRadius:DL.rad.md, padding:DL.sp.md, display:'flex', flexDirection:'column', gap:6 }}>
            <span style={{ fontFamily:DL.mono, fontSize:9, color:DL.accent, letterSpacing:'0.14em' }}>CANVAS · 1fr</span>
            <span style={{ fontFamily:DL.serif, fontSize:18, letterSpacing:'-0.01em' }}>The conversation</span>
            <span style={{ fontSize:11.5, color:DL.inkSoft, lineHeight:1.45 }}>Generous line-height, serif italic for AI replies. Tool calls collapse to mono rows. System prompt always anchored at top.</span>
            <div style={{ flex:1 }}/>
            <span style={{ fontFamily:DL.mono, fontSize:9, color:DL.inkMuted, letterSpacing:'0.06em' }}>lh 1.55 · max 720 · padding 24/36</span>
          </div>
          <div style={{ background:DL.bg, border:`1px dashed ${DL.line}`, borderRadius:DL.rad.md, padding:DL.sp.md, display:'flex', flexDirection:'column', gap:6 }}>
            <span style={{ fontFamily:DL.mono, fontSize:9, color:DL.accent, letterSpacing:'0.14em' }}>INSPECTOR · 288</span>
            <span style={{ fontFamily:DL.serif, fontSize:18, letterSpacing:'-0.01em' }}>The live state</span>
            <span style={{ fontSize:11.5, color:DL.inkSoft, lineHeight:1.45 }}>Inference params, parametric chain, active connectors. Edit anything · downstream cascades.</span>
            <div style={{ flex:1 }}/>
            <span style={{ fontFamily:DL.mono, fontSize:9, color:DL.inkMuted, letterSpacing:'0.06em' }}>section gap 18 · row 7 · mono labels</span>
          </div>
        </div>
        <div style={{ marginTop:14, fontFamily:DL.mono, fontSize:10, color:DL.inkMuted, lineHeight:1.7, letterSpacing:'0.04em' }}>
          The eye moves rail → canvas → inspector → status bar → back to rail. Every panel has a clear job. No floating widgets, no draggable modals. The system prompt at the top of every chat anchors the conversation in context.
        </div>
      </div>
    </DLSection>

    {/* ═════════ 13 · COMMAND PALETTE ═════════ */}
    <DLSection num="13" title="The command palette" sub="⌘K everywhere · the operating system of ArchHub">
      <div style={{ display:'grid', gridTemplateColumns:'1.4fr 1fr', gap:14 }}>
        <DLBox label="ANATOMY">
          <div style={{ background:DL.bgPanel, border:`1px solid ${DL.line}`, borderRadius:DL.rad.lg, overflow:'hidden' }}>
            <div style={{ padding:'10px 12px', borderBottom:`1px solid ${DL.line}`, display:'flex', alignItems:'center', gap:10 }}>
              <span style={{ fontSize:14, color:DL.inkMuted }}>⌕</span>
              <span style={{ flex:1, fontSize:13, color:DL.inkSoft }}>Type to search · run · navigate…</span>
              <span style={{ fontFamily:DL.mono, fontSize:10, color:DL.inkMuted, padding:'1px 5px', background:DL.bgSoft, borderRadius:DL.rad.xs }}>esc</span>
            </div>
            <div style={{ padding:'4px 6px' }}>
              {[
                ['↗', 'Run skill — Dimension walls in active view', '⌘1', true],
                ['⚡', 'Restart AutoCAD connector', 'self-heal', false],
                ['◐', 'Toggle theme · light / dark', '⌘⇧L', false],
                ['+', 'New chat thread', '⌘N', false],
                ['☰', 'Open Skills library', '⌘3', false],
              ].map(([g, t, sub, hi], i) => (
                <div key={i} style={{
                  padding:'7px 9px', borderRadius:DL.rad.sm, display:'flex', alignItems:'center', gap:10, cursor:'pointer',
                  background: hi ? DL.bgHover : 'transparent',
                }}>
                  <span style={{ width:18, color: hi ? DL.accent : DL.inkSoft, fontFamily:DL.mono, textAlign:'center' }}>{g}</span>
                  <span style={{ flex:1, fontSize:12.5, color:DL.ink }}>{t}</span>
                  <span style={{ fontFamily:DL.mono, fontSize:10, color:DL.inkMuted }}>{sub}</span>
                </div>
              ))}
            </div>
            <div style={{ padding:'7px 12px', borderTop:`1px solid ${DL.line}`, display:'flex', gap:14, fontFamily:DL.mono, fontSize:10, color:DL.inkMuted, letterSpacing:'0.05em' }}>
              <span>↑↓ navigate</span><span>↵ run</span><span>tab filter</span>
              <div style={{ flex:1 }}/>
              <span>5 results</span>
            </div>
          </div>
        </DLBox>
        <DLBox label="ACTION TYPES · 5 PREFIXES">
          {[
            ['/skill','run, fork, save, delete'],
            ['>connector','restart, install, configure'],
            ['#tag','filter chats and skills'],
            ['@host','target a connector explicitly'],
            ['?','help · keyboard map · docs'],
          ].map(([p, w]) => (
            <div key={p} style={{ padding:'7px 0', borderBottom:`1px dashed ${DL.lineSoft}` }}>
              <div style={{ display:'flex', gap:10, alignItems:'center' }}>
                <kbd style={{ fontFamily:DL.mono, fontSize:11, padding:'2px 7px', background:DL.bg, color:DL.accent, border:`1px solid ${DL.line}`, borderRadius:4, minWidth:80, textAlign:'center' }}>{p}</kbd>
                <span style={{ fontFamily:DL.mono, fontSize:11, color:DL.inkSoft }}>{w}</span>
              </div>
            </div>
          ))}
          <div style={{ fontFamily:DL.mono, fontSize:10, color:DL.inkMuted, lineHeight:1.6, marginTop:DL.sp.xs }}>
            Empty palette = recent actions. First keystroke filters. Tab cycles category. Esc closes.
          </div>
        </DLBox>
      </div>
    </DLSection>

    {/* ═════════ 14 · APPLICATION BLUEPRINT ═════════ */}
    <DLSection num="14" title="Application blueprint" sub="the four surfaces · how every screen is built">
      <div style={{ display:'grid', gridTemplateColumns:'repeat(4, 1fr)', gap:14 }}>
        {[
          { n:'01', t:'Chat',     d:'Hero model picker · system prompt card · branched thread · inference inspector', when:'90% of sessions live here' },
          { n:'02', t:'Discover', d:'Filtered marketplace · install/buy · view JSON · fork to local', when:'Adopting community Skills' },
          { n:'03', t:'Server',   d:'Local API status · connector grid · curl example · keys · request metrics', when:'When IDEs/Cursor connect' },
          { n:'04', t:'Logs',     d:'Live tail · severity filter · module column · jump to source', when:'Debugging or auditing' },
        ].map(s => (
          <DLBox key={s.n} label={`${s.n} · ${s.t.toUpperCase()}`}>
            <div style={{ fontFamily:DL.serif, fontSize:26, letterSpacing:'-0.02em' }}>{s.t}</div>
            <div style={{ fontSize:12.5, color:DL.inkSoft, lineHeight:1.5, flex:1 }}>{s.d}</div>
            <div style={{ fontFamily:DL.mono, fontSize:9.5, color:DL.inkMuted, letterSpacing:'0.06em' }}>{s.when}</div>
          </DLBox>
        ))}
      </div>

      {/* Footer */}
      <div style={{ marginTop:DL.sp['2xl'], padding:'16px 20px', borderTop:`1px solid ${DL.line}`, display:'flex', alignItems:'center', gap:14 }}>
        <Mark size={24}/>
        <span style={{ fontFamily:DL.serif, fontSize:18, letterSpacing:'-0.01em' }}>ArchHub · Studio</span>
        <div style={{ flex:1 }}/>
        <span style={{ fontFamily:DL.mono, fontSize:10, color:DL.inkMuted, letterSpacing:'0.08em' }}>DESIGN LANGUAGE · v1.0.1 · MAY 2026 · FARGALY</span>
      </div>
    </DLSection>
  </div>
);

// Color swatch component
const ColorSwatch = ({ hex, dark, name, role, note, big }) => (
  <div style={{
    background: hex, color: '#fff', borderRadius:DL.rad.lg, padding:'14px 16px',
    minHeight: big ? 130 : 100,
    display:'flex', flexDirection:'column', justifyContent:'space-between',
    border:`1px solid ${DL.line}`,
  }}>
    <div>
      <div style={{ fontFamily:DL.mono, fontSize:10, letterSpacing:'0.12em', opacity:0.85 }}>{role}</div>
      <div style={{ fontFamily:DL.serif, fontSize: big ? 28 : 18, letterSpacing:'-0.01em', marginTop:2 }}>{name}</div>
      {note && <div style={{ fontFamily:DL.serif, fontStyle:'italic', fontSize:13, marginTop:6, opacity:0.92, maxWidth:340, lineHeight:1.4 }}>{note}</div>}
    </div>
    <div style={{ fontFamily:DL.mono, fontSize:10.5, letterSpacing:'0.08em', opacity:0.9, marginTop:DL.sp.sm }}>{hex.toUpperCase()}</div>
  </div>
);

window.StudioLanguage = StudioLanguage;
