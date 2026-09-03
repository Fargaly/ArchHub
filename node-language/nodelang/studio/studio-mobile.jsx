// studio-mobile.jsx — the companion as a device you operate, not three stills.
// The mobile case that actually matters on site: approve what the desktop is waiting on,
// watch a run, nudge a parameter, capture a sketch into a run. One phone, four tabs, real
// state — every control changes something and the workstation strip reflects it.

const MB = window.AH;

const MB_DEVICES = [
  { id: 'pc',  icon: '🖥', name: 'STUDIO-PC',  meta: 'Revit 2025 · awake',  state: 'awake' },
  { id: 'mac', icon: '💻', name: 'LAPTOP-M2',  meta: 'Mac · sleeping',      state: 'sleep' },
  { id: 'ws',  icon: '🏢', name: 'OFFICE-WS',  meta: 'offline 2h ago',      state: 'off' },
];

// Gates come from the same permission vocabulary the desktop uses: anything set to ASK
// surfaces here instead of blocking the run until someone is back at the machine.
const MB_GATES_SEED = [
  { id: 'g1', cap: 'Place new elements', detail: '14 dimensions on L03 exterior walls', node: 'auto-dimension', risk: 'low' },
  { id: 'g2', cap: 'Edit parameter values', detail: 'Set "Mark" on 23 walls → auto-number', node: 'set wall marks', risk: 'low' },
  { id: 'g3', cap: 'Publish / export', detail: 'Publish 6-sheet PDF set to project-share', node: 'publish PDF set', risk: 'high' },
];

const MB_RUNS_SEED = [
  { id: 'r1', title: 'Dimension L03 exterior', state: 'running', pct: 0.74, note: '17 / 23 placed', ms: '3.1 / 4.2s' },
  { id: 'r2', title: 'Wall schedule → sheet', state: 'queued', pct: 0, note: 'waiting on gate g2', ms: '—' },
  { id: 'r3', title: 'Speckle commit cbb8e2', state: 'done', pct: 1, note: '14 files pushed', ms: '2.4s' },
];

const MB_PARAMS_SEED = [
  { id: 'p1', k: 'min length', v: 800, min: 200, max: 2000, step: 50, unit: 'mm', node: 'where length ≥' },
  { id: 'p2', k: 'text size', v: 2.5, min: 1.5, max: 5, step: 0.5, unit: 'mm', node: 'auto-dimension' },
  { id: 'p3', k: 'offset', v: 6, min: 0, max: 20, step: 1, unit: 'mm', node: 'auto-dimension' },
];

const mbTabs = [['approve', 'Approve'], ['runs', 'Runs'], ['params', 'Params'], ['capture', 'Capture']];

function StudioMobile() {
  const [tab, setTab] = React.useState('approve');
  const [device, setDevice] = React.useState('pc');
  const [gates, setGates] = React.useState(MB_GATES_SEED);
  const [runs, setRuns] = React.useState(MB_RUNS_SEED);
  const [params, setParams] = React.useState(MB_PARAMS_SEED);
  const [log, setLog] = React.useState([]);
  const [pushed, setPushed] = React.useState(false);
  const [sent, setSent] = React.useState(false);

  const say = (t) => setLog(l => [{ t, at: new Date().toLocaleTimeString('en-GB').slice(0, 8) }].concat(l).slice(0, 6));

  // a live run so the phone is never a frozen still
  React.useEffect(() => {
    const iv = setInterval(() => setRuns(rs => rs.map(r =>
      r.state === 'running' ? Object.assign({}, r, {
        pct: r.pct >= 1 ? 1 : +(r.pct + 0.02).toFixed(2),
        state: r.pct >= 0.98 ? 'done' : 'running',
        note: r.pct >= 0.98 ? '23 / 23 placed' : Math.round((r.pct + 0.02) * 23) + ' / 23 placed',
      }) : r)), 900);
    return () => clearInterval(iv);
  }, []);

  const decide = (id, ok) => {
    const g = gates.find(x => x.id === id);
    setGates(gs => gs.filter(x => x.id !== id));
    say((ok ? 'Approved' : 'Rejected') + ' · ' + g.cap.toLowerCase());
    if (ok) setRuns(rs => rs.map(r => r.note === 'waiting on gate ' + id
      ? Object.assign({}, r, { state: 'running', note: 'started from phone', pct: 0.05 }) : r));
    else setRuns(rs => rs.filter(r => r.note !== 'waiting on gate ' + id));
  };

  const dev = MB_DEVICES.find(d => d.id === device);
  const pend = gates.length;
  const live = runs.filter(r => r.state === 'running').length;

  const shell = (children) => (
    <div style={{
      width: 322, height: 660, borderRadius: 44, padding: 11, flexShrink: 0,
      background: '#08080a', border: `1px solid ${MB.line}`, boxShadow: '0 30px 70px rgba(0,0,0,.6)',
    }}>
      <div style={{
        width: '100%', height: '100%', borderRadius: 34, overflow: 'hidden',
        background: MB.bg, display: 'flex', flexDirection: 'column', position: 'relative',
      }}>{children}</div>
    </div>
  );

  const row = (label, right, on, onClick, sub) => (
    <button key={label} onClick={onClick} style={{
      width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 10,
      padding: '11px 12px', minHeight: 46, cursor: onClick ? 'pointer' : 'default',
      border: `1px solid ${on ? MB.accent : MB.lineSoft}`, borderRadius: MB.rad.md,
      background: on ? MB.accentSoft : MB.bgPanel, color: MB.ink, marginBottom: 7,
    }}>
      <span style={{ flex: 1, minWidth: 0 }}>
        <span style={{ display: 'block', fontSize: 13, fontFamily: MB.sans }}>{label}</span>
        {sub && <span style={{ display: 'block', fontFamily: MB.mono, fontSize: 9.5, color: MB.inkSoft, marginTop: 2 }}>{sub}</span>}
      </span>
      {right}
    </button>
  );

  return (
    <div className="ah-scroll" style={{ background: MB.bg, color: MB.ink, fontFamily: MB.sans, height: '100%', overflow: 'auto', padding: '34px 44px' }}>
      <div style={{ marginBottom: 22 }}>
        <div style={{ fontFamily: MB.mono, fontSize: 11, color: MB.inkMuted, letterSpacing: '0.16em' }}>MOBILE COMPANION · iOS</div>
        <h1 style={{ fontFamily: MB.serif, fontSize: 44, letterSpacing: '-0.03em', margin: '8px 0 4px', fontWeight: 400 }}>
          Approve from the scaffold.
        </h1>
        <div style={{ fontFamily: MB.serif, fontStyle: 'italic', fontSize: 16, color: MB.inkSoft, maxWidth: 620 }}>
          The desktop pauses on anything set to <b style={{ fontStyle: 'normal', fontWeight: 400, color: MB.ink }}>ask</b>.
          This is where you answer — so a run isn’t stuck until someone walks back to the machine.
        </div>
      </div>

      <div style={{ display: 'flex', gap: 34, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        {shell(
          <>
            {/* status bar + paired device */}
            <div style={{ padding: '9px 16px 0', display: 'flex', alignItems: 'center', fontFamily: MB.mono, fontSize: 10, color: MB.inkSoft }}>
              <span>9:41</span><span style={{ flex: 1 }}/>
              <span style={{ color: dev.state === 'awake' ? MB.ok : MB.warn }}>●</span>
              <span style={{ marginLeft: 5 }}>{dev.name}</span>
            </div>
            <div style={{ padding: '10px 14px 8px', borderBottom: `1px solid ${MB.lineSoft}` }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 7 }}>
                <span style={{ fontFamily: MB.serif, fontSize: 26, color: pend ? MB.accent : MB.ok, lineHeight: 1 }}>{pend}</span>
                <span style={{ fontSize: 13 }}>{pend === 1 ? 'request waiting' : 'requests waiting'}</span>
                <span style={{ flex: 1 }}/>
                <span style={{ fontFamily: MB.mono, fontSize: 9.5, color: MB.inkSoft }}>{live} running</span>
              </div>
            </div>

            {/* body */}
            <div className="ah-scroll" style={{ flex: 1, overflow: 'auto', padding: '12px 12px 4px' }}>
              {tab === 'approve' && (pend === 0
                ? <div style={{ padding: '30px 8px', textAlign: 'center' }}>
                    <div style={{ fontFamily: MB.serif, fontSize: 19 }}>Nothing waiting.</div>
                    <div style={{ fontFamily: MB.mono, fontSize: 10.5, color: MB.inkSoft, marginTop: 6, lineHeight: 1.6 }}>
                      The desktop is running unattended.<br/>You’ll get a push when it needs you.
                    </div>
                    <button onClick={() => { setGates(MB_GATES_SEED); say('Reset · 3 requests restored'); }}
                      style={Object.assign({}, mbBtn(), { marginTop: 14 })}>Simulate new requests</button>
                  </div>
                : gates.map(g => (
                    <div key={g.id} style={{ padding: '11px 12px', border: `1px solid ${g.risk === 'high' ? MB.warn : MB.line}`, borderRadius: MB.rad.md, background: MB.bgPanel, marginBottom: 9 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                        <span style={{ fontFamily: MB.mono, fontSize: 8.5, letterSpacing: '0.12em', padding: '2px 6px', borderRadius: 3, border: `1px solid ${g.risk === 'high' ? MB.warn : MB.inkMuted}`, color: g.risk === 'high' ? MB.warn : MB.inkSoft }}>
                          {g.risk === 'high' ? 'NEEDS CARE' : 'ROUTINE'}
                        </span>
                        <span style={{ fontFamily: MB.mono, fontSize: 9.5, color: MB.inkSoft, flex: 1, textAlign: 'right' }}>{g.node}</span>
                      </div>
                      <div style={{ fontSize: 13.5, marginTop: 7, lineHeight: 1.35 }}>{g.cap}</div>
                      <div style={{ fontSize: 12, color: MB.inkSoft, marginTop: 3, lineHeight: 1.45 }}>{g.detail}</div>
                      <div style={{ display: 'flex', gap: 7, marginTop: 10 }}>
                        <button onClick={() => decide(g.id, false)} style={Object.assign({}, mbBtn(), { flex: 1, minHeight: 44, color: MB.err, borderColor: MB.lineSoft })}>Reject</button>
                        <button onClick={() => decide(g.id, true)} style={Object.assign({}, mbBtn(true), { flex: 2, minHeight: 44 })}>Approve</button>
                      </div>
                    </div>
                  )))}

              {tab === 'runs' && runs.map(r => (
                <div key={r.id} style={{ padding: '10px 12px', border: `1px solid ${MB.lineSoft}`, borderRadius: MB.rad.md, background: MB.bgPanel, marginBottom: 8 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                    <span style={{ width: 7, height: 7, borderRadius: '50%', background: r.state === 'running' ? MB.accent : r.state === 'done' ? MB.ok : MB.inkMuted, flexShrink: 0 }}/>
                    <span style={{ fontSize: 13, flex: 1, minWidth: 0 }}>{r.title}</span>
                    <span style={{ fontFamily: MB.mono, fontSize: 9.5, color: MB.inkSoft }}>{r.ms}</span>
                  </div>
                  <div style={{ height: 3, background: MB.lineSoft, borderRadius: 2, margin: '8px 0 5px', overflow: 'hidden' }}>
                    <div style={{ width: (r.pct * 100) + '%', height: '100%', background: r.state === 'done' ? MB.ok : MB.accent, transition: 'width .5s' }}/>
                  </div>
                  <div style={{ fontFamily: MB.mono, fontSize: 9.5, color: MB.inkSoft }}>{r.note}</div>
                </div>
              ))}

              {tab === 'params' && (
                <div>
                  <div style={{ fontFamily: MB.mono, fontSize: 9, color: MB.inkMuted, letterSpacing: '0.14em', marginBottom: 9 }}>LIVE ON {dev.name}</div>
                  {params.map(p => (
                    <div key={p.id} style={{ padding: '11px 12px', border: `1px solid ${MB.lineSoft}`, borderRadius: MB.rad.md, background: MB.bgPanel, marginBottom: 9 }}>
                      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                        <span style={{ fontSize: 13, flex: 1 }}>{p.k}</span>
                        <span style={{ fontFamily: MB.serif, fontSize: 19, color: MB.accent, lineHeight: 1 }}>{p.v}</span>
                        <span style={{ fontFamily: MB.mono, fontSize: 10, color: MB.inkSoft }}>{p.unit}</span>
                      </div>
                      <input type="range" min={p.min} max={p.max} step={p.step} value={p.v}
                        onChange={e => { const v = +e.target.value; setParams(ps => ps.map(x => x.id === p.id ? Object.assign({}, x, { v }) : x)); setPushed(false); }}
                        style={{ width: '100%', marginTop: 9, accentColor: MB.accent, height: 22 }}/>
                      <div style={{ fontFamily: MB.mono, fontSize: 9.5, color: MB.inkMuted, marginTop: 2 }}>{p.node}</div>
                    </div>
                  ))}
                  <button onClick={() => { setPushed(true); say('Pushed 3 params → ' + dev.name); }}
                    style={Object.assign({}, mbBtn(!pushed), { width: '100%', minHeight: 46, justifyContent: 'center' })}>
                    {pushed ? '✓ In sync with workstation' : 'Push to workstation →'}
                  </button>
                </div>
              )}

              {tab === 'capture' && (
                <div>
                  <div style={{ borderRadius: MB.rad.lg, overflow: 'hidden', background: '#f0e8d8', aspectRatio: '3 / 4' }}>
                    <svg viewBox="0 0 200 260" style={{ width: '100%', height: '100%', display: 'block' }}>
                      <path d="M30 225 L30 125 L100 66 L170 125 L170 225 Z" fill="none" stroke="#3a2418" strokeWidth="1.5"/>
                      <line x1="30" y1="170" x2="170" y2="170" stroke="#3a2418" strokeWidth="0.8"/>
                      <rect x="60" y="188" width="22" height="37" fill="none" stroke="#3a2418" strokeWidth="0.8"/>
                      <rect x="118" y="188" width="22" height="37" fill="none" stroke="#3a2418" strokeWidth="0.8"/>
                      <text x="100" y="248" textAnchor="middle" fontFamily="JetBrains Mono" fontSize="7" fill="#7a7064">~6m wide · gabled · 2 storey</text>
                    </svg>
                  </div>
                  <div style={{ fontFamily: MB.mono, fontSize: 9, color: MB.inkMuted, letterSpacing: '0.14em', margin: '14px 0 7px' }}>SEND TO</div>
                  {MB_DEVICES.map(d => row(d.name,
                    <span style={{ fontFamily: MB.mono, fontSize: 9, color: d.state === 'awake' ? MB.ok : MB.inkMuted, letterSpacing: '0.1em' }}>
                      {d.state === 'awake' ? 'AWAKE' : d.state === 'sleep' ? 'WAKE' : 'OFFLINE'}
                    </span>,
                    device === d.id, d.state === 'off' ? null : () => { setDevice(d.id); setSent(false); }, d.meta))}
                  <button disabled={sent} onClick={() => { setSent(true); say('Sketch sent → ' + dev.name); setRuns(rs => [{ id: 'r' + Date.now(), title: 'Trace sketch → mass', state: 'running', pct: 0.08, note: 'from phone capture', ms: '0.4s' }].concat(rs)); setTab('runs'); }}
                    style={Object.assign({}, mbBtn(true), { width: '100%', minHeight: 46, marginTop: 4, justifyContent: 'center', opacity: sent ? 0.5 : 1 })}>
                    {sent ? '✓ Sent' : 'Send to ' + dev.name + ' →'}
                  </button>
                </div>
              )}
            </div>

            {/* tab bar — 44px+ targets */}
            <div style={{ display: 'flex', borderTop: `1px solid ${MB.line}`, background: MB.bgPanel }}>
              {mbTabs.map(([id, label]) => (
                <button key={id} onClick={() => setTab(id)} style={{
                  flex: 1, minHeight: 52, border: 0, background: 'transparent', cursor: 'pointer',
                  color: tab === id ? MB.accent : MB.inkMuted, fontFamily: MB.mono, fontSize: 10,
                  letterSpacing: '0.06em', position: 'relative',
                }}>
                  {label.toUpperCase()}
                  {id === 'approve' && pend > 0 && (
                    <span style={{ position: 'absolute', top: 9, right: 12, minWidth: 15, height: 15, borderRadius: 999, background: MB.accent, color: '#180f08', fontSize: 9, fontWeight: 700, display: 'grid', placeItems: 'center' }}>{pend}</span>
                  )}
                  {tab === id && <span style={{ position: 'absolute', top: 0, left: '25%', width: '50%', height: 2, background: MB.accent }}/>}
                </button>
              ))}
            </div>
          </>
        )}

        {/* what the workstation sees — the phone is only credible if the other end reacts */}
        <div style={{ minWidth: 300, flex: 1, maxWidth: 460 }}>
          <div style={{ fontFamily: MB.mono, fontSize: 9, color: MB.inkMuted, letterSpacing: '0.16em', marginBottom: 10 }}>WHAT {dev.name} SEES</div>
          <div style={{ border: `1px solid ${MB.line}`, borderRadius: MB.rad.md, background: MB.bgPanel, overflow: 'hidden' }}>
            <div style={{ padding: '10px 13px', borderBottom: `1px solid ${MB.lineSoft}`, display: 'flex', alignItems: 'center', gap: 8, fontFamily: MB.mono, fontSize: 10.5 }}>
              <span style={{ color: MB.ok }}>●</span>
              <span style={{ color: MB.inkSoft }}>server :7300</span>
              <span style={{ flex: 1 }}/>
              <span style={{ color: pend ? MB.warn : MB.ok }}>{pend ? pend + ' paused on ask' : 'running unattended'}</span>
            </div>
            {log.length === 0
              ? <div style={{ padding: '18px 13px', fontFamily: MB.serif, fontStyle: 'italic', fontSize: 14, color: MB.inkSoft }}>
                  Nothing from the phone yet. Approve a request, move a parameter, or send a capture.
                </div>
              : log.map((l, i) => (
                  <div key={i} style={{ padding: '8px 13px', borderTop: i === 0 ? 'none' : `1px solid ${MB.lineHair}`, display: 'flex', gap: 10, fontFamily: MB.mono, fontSize: 11 }}>
                    <span style={{ color: MB.inkMuted, flexShrink: 0 }}>{l.at}</span>
                    <span style={{ color: MB.inkSoft }}>{l.t}</span>
                  </div>
                ))}
          </div>
          <div style={{ fontFamily: MB.mono, fontSize: 9.5, color: MB.inkMuted, marginTop: 10, lineHeight: 1.7, letterSpacing: '0.04em' }}>
            GATES COME FROM SETTINGS → PERMISSIONS.<br/>
            ANYTHING SET TO <span style={{ color: MB.warn }}>ASK</span> ARRIVES HERE INSTEAD OF BLOCKING THE RUN.
          </div>
        </div>
      </div>
    </div>
  );
}

const mbBtn = (primary) => ({
  padding: '8px 13px', borderRadius: MB.rad.sm, fontFamily: MB.sans, fontSize: 12.5,
  border: `1px solid ${primary ? MB.accent : MB.line}`,
  background: primary ? MB.accent : 'transparent',
  color: primary ? (MB.onFill || '#180f08') : MB.inkSoft,
  cursor: 'pointer', fontWeight: 500, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
});

Object.assign(window, { StudioMobile });
