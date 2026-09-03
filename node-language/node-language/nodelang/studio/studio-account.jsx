// studio-account.jsx — the account arc: boot → sign-up → the account surfaces that keep
// the promise (usage, plan, brain). Split out of studio-lm.jsx (already 3.4k lines).
// Everything here reads tokens via LM (window.AH) and the shared settings store, so the
// website's "create account" and the app's Settings are one continuous experience.

const AC = window.AH;
const ACLS = 'archhub.account.v1';

// Local atoms — studio-lm.jsx is IIFE-scoped, so its SHead/smallBtn can't be borrowed.
// Same tokens, same look, no cross-file coupling.
const SHead = ({ title, sub }) => (
  <div style={{ marginBottom: 14 }}>
    <div style={{ fontFamily: AC.serif, fontSize: 22, letterSpacing: '-0.01em' }}>{title}</div>
    {sub && <div style={{ fontFamily: AC.sans, fontSize: 13, color: AC.inkSoft, marginTop: 3, lineHeight: 1.5 }}>{sub}</div>}
  </div>
);
const smallBtn = (primary) => ({
  padding: '5px 11px', borderRadius: AC.rad.sm, fontFamily: AC.sans, fontSize: 11.5,
  border: `1px solid ${primary ? AC.accent : AC.line}`,
  background: primary ? AC.accent : 'transparent',
  color: primary ? (AC.onFill || '#180f08') : AC.inkSoft, cursor: 'pointer', fontWeight: 500,
});

// ── the account record. One store, persisted, read by boot / sign-up / settings alike ──
const AC_SEED = {
  signedIn: false,
  email: '', name: '', firm: '', discipline: '', seat: 'Architect',
  plan: 'studio',                    // solo | studio | practice
  billing: 'monthly',
  created: null,
  brain: { local: true, path: '~/ArchHub/brain', size: 0, facts: 0, synced: null },
  usage: { spend: 0, cap: 120, ops: 0, opsCap: 5000, runs: 0, since: 'this cycle' },
  hostsSeen: [],
};

const acLoad = () => {
  try {
    const raw = localStorage.getItem(ACLS);
    if (!raw) return AC_SEED;
    const s = JSON.parse(raw) || {};
    // merge per key — a saved sub-object must never replace a seeded one wholesale
    return Object.assign({}, AC_SEED, s, {
      brain: Object.assign({}, AC_SEED.brain, s.brain || {}),
      usage: Object.assign({}, AC_SEED.usage, s.usage || {}),
    });
  } catch (e) { return AC_SEED; }
};
const acSave = (a) => { try { localStorage.setItem(ACLS, JSON.stringify(a)); } catch (e) {} };

const AC_PLANS = [
  { id: 'solo', name: 'Solo', price: 24, cap: 40, ops: 1500, seats: 1,
    line: 'One seat, one host, your own keys.' },
  { id: 'studio', name: 'Studio', price: 68, cap: 120, ops: 5000, seats: 5,
    line: 'Five seats, every host, shared skills.' },
  { id: 'practice', name: 'Practice', price: 210, cap: 500, ops: 25000, seats: 25,
    line: 'Firm-wide brain, SSO, audit export.' },
];

// ─────────────────────────────────────────────────────────────
// BOOT — the loading screen. A title block that fills in, not a spinner: each line is a
// real subsystem coming up, so the wait tells you what the app is doing and what it found.
// ─────────────────────────────────────────────────────────────
// Five real subsystems. Each detail is READ from what actually answered
// this boot -- never a fixed count, because a splash that recites numbers
// nobody measured is furniture, not a report.
const _bootDetail = (key) => {
  const live = window.ARCHHUB_LIVE || {};
  if (key === 'tokens') {
    const T = window.AH || {};
    return Object.keys(T).length + ' tokens';
  }
  if (key === 'brain') {
    return window.ARCHHUB_BRAIN_FACTS != null
      ? window.ARCHHUB_BRAIN_FACTS + ' facts' : 'connecting';
  }
  if (key === 'hosts') {
    const live_hosts = (live.connectors || []).filter(
      c => c.state === 'connected' || c.state === 'listening');
    return live_hosts.length
      ? live_hosts.map(c => c.name).join(' · ') : 'none listening';
  }
  if (key === 'skills') {
    return (live.skills || []).length + ' on this machine';
  }
  const nodes = (live.graph && live.graph.nodes) || [];
  return nodes.length + ' nodes restored';
};

const AC_BOOT = [
  { k: 'tokens',  label: 'Design tokens', ms: 240,  get detail() { return _bootDetail('tokens'); } },
  { k: 'brain',   label: 'Brain',         ms: 620,  get detail() { return _bootDetail('brain'); } },
  { k: 'hosts',   label: 'Hosts',         ms: 900,  get detail() { return _bootDetail('hosts'); } },
  { k: 'skills',  label: 'Skills',        ms: 1180, get detail() { return _bootDetail('skills'); } },
  { k: 'canvas',  label: 'Canvas',        ms: 1460, get detail() { return _bootDetail('canvas'); } },
];

// The boot screen is a HELD MOMENT, not a dashboard. The old one was a full title block —
// header, five listed rows, a big percentage, a footer — which is a lot of furniture to read
// in two seconds. Reduced to the three things that belong on a splash: the mark, one light
// line naming what is happening right now, and a hairline of progress on the bottom edge of
// the screen. Everything it used to report is still true; it is reported one line at a time.
function AppBoot({ onDone, account }) {
  const [t, setT] = React.useState(0);
  const [failed, setFailed] = React.useState(false);
  const [live, setLive] = React.useState(null);
  React.useEffect(() => {
    const t0 = Date.now();
    const iv = setInterval(() => setT(Date.now() - t0), 60);
    // What the boot screen names must be what actually answered. The
    // capability probe is the truth; the timer only paces the reading.
    if (window.ARCHHUB_CAPABILITIES) {
      window.ARCHHUB_CAPABILITIES().then(setLive).catch(() => setLive(false));
    }
    const end = setTimeout(() => { clearInterval(iv); onDone && onDone(); }, 2050);
    return () => { clearInterval(iv); clearTimeout(end); };
  }, []);
  const done = AC_BOOT.filter(b => t >= b.ms).length;
  const pct = Math.min(100, Math.round((t / 1650) * 100));
  // the line reports the subsystem in flight, or the last one that reported in
  const cur = AC_BOOT[Math.min(done, AC_BOOT.length - 1)];
  const settled = done >= AC_BOOT.length;
  const line = settled
    ? (account && account.firm ? 'Opening ' + account.firm : 'Opening workspace')
    : cur.label + ' · ' + (done > 0 && t >= AC_BOOT[done - 1].ms && t - AC_BOOT[done - 1].ms < 180
        ? AC_BOOT[done - 1].detail : 'connecting…');

  return (
    <div style={{
      position: 'absolute', inset: 0, background: AC.bg, color: AC.ink, zIndex: 200,
      display: 'grid', placeItems: 'center', fontFamily: AC.sans, overflow: 'hidden',
    }}>
      {/* the same faint drafting ground the canvas uses, so boot belongs to the app */}
      <div style={{
        position: 'absolute', inset: 0, opacity: 0.35, pointerEvents: 'none',
        backgroundImage: `linear-gradient(${AC.lineHair} 1px, transparent 1px), linear-gradient(90deg, ${AC.lineHair} 1px, transparent 1px)`,
        backgroundSize: '48px 48px',
      }}/>

      <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 18 }}>
        <svg width={72} height={72} viewBox="0 0 64 64" fill="none" style={{ display: 'block' }}>
          <path d="M10 56 V32 a22 22 0 0 1 44 0 V56" stroke={AC.accent} strokeWidth="4.5" strokeLinecap="square"/>
          <circle cx="32" cy="22" r="5.2" fill={AC.bg} stroke={AC.accent} strokeWidth="2.4"/>
          <circle cx="32" cy="22" r="1.8" fill={AC.accent} style={{ animation: 'acPulse 1.1s infinite' }}/>
          <path d="M6 58 H58" stroke={AC.accent} strokeWidth="1.5" strokeLinecap="round"/>
        </svg>

        <div style={{ textAlign: 'center' }}>
          <div style={{ fontFamily: AC.arch, fontSize: 25, lineHeight: 1.15, letterSpacing: '0.02em', textTransform: 'uppercase' }}>
            Arch<span style={{ color: AC.accent }}>Hub</span>
          </div>
          {/* one light line — what is connecting, right now. Fixed height so it never jumps. */}
          <div style={{
            height: 15, marginTop: 9, fontFamily: AC.mono, fontSize: 10.5, color: AC.inkSoft,
            letterSpacing: '0.1em', marginRight: '-0.1em', whiteSpace: 'nowrap',
          }}>{line}</div>
        </div>
      </div>

      {failed && (
        <div style={{ position: 'absolute', bottom: 54, left: '50%', transform: 'translateX(-50%)', width: 380, maxWidth: '86vw', padding: '10px 12px', borderRadius: AC.rad.md, border: `1px solid ${AC.warn}`, background: AC.bgPanel }}>
          <div style={{ fontFamily: AC.mono, fontSize: 9, color: AC.warn, letterSpacing: '0.14em' }}>IF A HOST IS SLOW</div>
          <div style={{ fontSize: 12.5, color: AC.inkSoft, marginTop: 5, lineHeight: 1.5 }}>
            The canvas opens without it and the connector reconnects in the background — your
            graph is never blocked on a host. Skip straight in and watch it heal.
          </div>
          <button onClick={() => onDone && onDone()} style={{ ...smallBtn(true), marginTop: 9 }}>Open anyway</button>
        </div>
      )}

      {!failed && (
        <button onClick={() => setFailed(true)} style={{
          position: 'absolute', bottom: 16, right: 18, background: 'none', border: 0, padding: 0, cursor: 'pointer',
          fontFamily: AC.mono, fontSize: 9.5, color: AC.inkSoft, letterSpacing: '0.1em', textDecoration: 'underline dotted',
        }}>TAKING TOO LONG?</button>
      )}

      {/* progress rides the bottom EDGE — a hairline the eye can ignore until it matters */}
      <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: 2, background: AC.lineHair }}>
        <div style={{ width: pct + '%', height: '100%', background: AC.accent, transition: 'width .12s linear' }}/>
      </div>

      <style>{'@keyframes acPulse{0%,100%{opacity:1}50%{opacity:.25}}'}</style>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// SIGN-UP — four steps, each doing real work: identity, practice, hosts found on this
// machine, brain seeded from what you just said. No step is a formality.
// ─────────────────────────────────────────────────────────────
const AC_DISCIPLINES = ['Architecture', 'Structure', 'MEP', 'Interiors', 'Landscape', 'BIM management'];
const AC_DETECT = [
  { name: 'Revit 2025',  ops: 28, found: true },
  { name: 'Rhino 8',     ops: 16, found: true },
  { name: 'AutoCAD 2024',ops: 19, found: true },
  { name: 'Speckle',     ops: 14, found: false },
  { name: 'Excel',       ops: 13, found: true },
];

function SignUp({ onDone, onCancel, plan }) {
  const [step, setStep] = React.useState(0);
  const [a, setA] = React.useState(() => Object.assign({}, acLoad(), plan ? { plan } : {}));
  const [hosts, setHosts] = React.useState(() => AC_DETECT.filter(h => h.found).map(h => h.name));
  const set = (k, v) => setA(p => Object.assign({}, p, { [k]: v }));

  const steps = ['Identity', 'Practice', 'Hosts', 'Brain'];
  const canNext = [
    /\S+@\S+\.\S+/.test(a.email) && a.name.trim().length > 1,
    a.firm.trim().length > 1 && !!a.discipline,
    true,
    true,
  ][step];

  const finish = () => {
    const p = AC_PLANS.find(x => x.id === a.plan) || AC_PLANS[1];
    const facts = 3 + (a.firm ? 1 : 0) + (a.discipline ? 1 : 0) + hosts.length;
    const rec = Object.assign({}, a, {
      signedIn: true,
      created: new Date().toISOString().slice(0, 10),
      hostsSeen: hosts,
      brain: Object.assign({}, a.brain, { facts, size: +(facts * 0.4).toFixed(1), synced: 'just now' }),
      usage: Object.assign({}, a.usage, { cap: p.cap, opsCap: p.ops }),
    });
    acSave(rec);
    // The account is a GRAPH record, not just localStorage: land it and
    // take the tier the graph answers with.
    if (window.ARCHHUB_LOGIN && rec.email) {
      window.ARCHHUB_LOGIN(rec.email).then(live => {
        if (live && live.tier) {
          acSave(Object.assign({}, rec, {
            plan: live.tier, graphTier: live.tier, founder: !!live.founder,
          }));
        }
      }).catch(() => {});
    }
    onDone && onDone(rec);
  };

  const field = (label, val, on, ph, type) => (
    <label style={{ display: 'block', marginBottom: 12 }}>
      <span style={{ display: 'block', fontFamily: AC.mono, fontSize: 9, color: AC.inkMuted, letterSpacing: '0.14em', marginBottom: 5 }}>{label}</span>
      <input value={val} onChange={e => on(e.target.value)} placeholder={ph} type={type || 'text'} style={{
        width: '100%', padding: '9px 11px', borderRadius: AC.rad.sm, border: `1px solid ${AC.line}`,
        background: AC.bg, color: AC.ink, fontFamily: AC.sans, fontSize: 13.5, outline: 'none',
      }}/>
    </label>
  );

  return (
    <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,.55)', zIndex: 80, display: 'grid', placeItems: 'center', fontFamily: AC.sans }}>
      <div onClick={e => e.stopPropagation()} style={{
        width: 620, maxWidth: '92vw', maxHeight: '90%', overflow: 'auto', background: AC.bgPanel,
        border: `1px solid ${AC.line}`, borderRadius: AC.rad.xl, color: AC.ink,
        boxShadow: '0 40px 100px rgba(0,0,0,.6)',
      }}>
        {/* step rail */}
        <div style={{ display: 'flex', borderBottom: `1px solid ${AC.line}` }}>
          {steps.map((s, i) => (
            <div key={s} style={{
              flex: 1, padding: '11px 0', textAlign: 'center',
              fontFamily: AC.mono, fontSize: 9.5, letterSpacing: '0.12em',
              color: i === step ? AC.ink : i < step ? AC.ok : AC.inkMuted,
              borderBottom: `2px solid ${i === step ? AC.accent : 'transparent'}`,
            }}>{i < step ? '✓ ' : ''}{s.toUpperCase()}</div>
          ))}
        </div>

        <div style={{ padding: '20px 24px 22px' }}>
          {step === 0 && (
            <div>
              <SHead title="Create your account" sub="Your keys and your brain stay on your machine. This is the only thing we store server-side."/>
              {field('YOUR NAME', a.name, v => set('name', v), 'Amina Habib')}
              {field('WORK EMAIL', a.email, v => set('email', v), 'you@practice.com', 'email')}
              <div style={{ fontFamily: AC.mono, fontSize: 10.5, color: AC.inkSoft, marginTop: 4, lineHeight: 1.6 }}>
                No credit card until you publish your first sheet set.
              </div>
            </div>
          )}

          {step === 1 && (
            <div>
              <SHead title="Your practice" sub="This seeds the brain — it becomes the context Claude carries into every session, and you can edit or forget any of it later."/>
              {field('PRACTICE', a.firm, v => set('firm', v), 'Habib Studio')}
              <span style={{ display: 'block', fontFamily: AC.mono, fontSize: 9, color: AC.inkMuted, letterSpacing: '0.14em', marginBottom: 6 }}>DISCIPLINE</span>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 7 }}>
                {AC_DISCIPLINES.map(d => (
                  <button key={d} onClick={() => set('discipline', d)} style={{
                    padding: '6px 12px', borderRadius: AC.rad.pill, cursor: 'pointer', fontSize: 12.5,
                    fontFamily: AC.sans, transition: '.14s',
                    border: `1px solid ${a.discipline === d ? AC.accent : AC.line}`,
                    background: a.discipline === d ? AC.accentSoft : 'transparent',
                    color: a.discipline === d ? AC.ink : AC.inkSoft,
                  }}>{d}</button>
                ))}
              </div>
            </div>
          )}

          {step === 2 && (
            <div>
              <SHead title="Hosts on this machine" sub="Found by scanning your install paths. Each one becomes a node group on your canvas — untick anything you don't want reachable."/>
              <div style={{ border: `1px solid ${AC.line}`, borderRadius: AC.rad.md, overflow: 'hidden' }}>
                {AC_DETECT.map((h, i) => {
                  const on = hosts.indexOf(h.name) >= 0;
                  return (
                    <div key={h.name} onClick={() => setHosts(p => on ? p.filter(x => x !== h.name) : p.concat(h.name))}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 12, padding: '10px 13px', cursor: 'pointer',
                        borderTop: i === 0 ? 'none' : `1px solid ${AC.lineSoft}`,
                        background: on ? AC.bgSoft : 'transparent',
                      }}>
                      <span style={{
                        width: 15, height: 15, borderRadius: 4, flexShrink: 0, display: 'grid', placeItems: 'center',
                        border: `1px solid ${on ? AC.accent : AC.line}`, background: on ? AC.accent : 'transparent',
                        color: '#180f08', fontSize: 10, fontWeight: 700,
                      }}>{on ? '✓' : ''}</span>
                      <span style={{ flex: 1, fontSize: 13 }}>{h.name}</span>
                      <span style={{ fontFamily: AC.mono, fontSize: 10.5, color: AC.inkSoft }}>{h.ops} ops</span>
                      <span style={{ fontFamily: AC.mono, fontSize: 9, letterSpacing: '0.12em', color: h.found ? AC.ok : AC.inkMuted }}>
                        {h.found ? 'FOUND' : 'NOT INSTALLED'}
                      </span>
                    </div>
                  );
                })}
              </div>
              <div style={{ fontFamily: AC.mono, fontSize: 10.5, color: AC.inkSoft, marginTop: 10 }}>
                {hosts.length} hosts · {AC_DETECT.filter(h => hosts.indexOf(h.name) >= 0).reduce((s, h) => s + h.ops, 0)} operations available as nodes
              </div>
            </div>
          )}

          {step === 3 && (
            <div>
              <SHead title="Your brain" sub="It lives on your disk, not our servers and not a git remote. Sync is a folder you choose."/>
              <div style={{ padding: '13px 14px', borderRadius: AC.rad.md, border: `1px solid ${AC.line}`, background: AC.bg }}>
                <div style={{ fontFamily: AC.mono, fontSize: 9, color: AC.accent, letterSpacing: '0.14em' }}>SEEDED FROM THIS SIGN-UP</div>
                <div style={{ marginTop: 8 }}>
                  {[
                    a.name && `You are ${a.name}.`,
                    a.firm && `Works at ${a.firm}${a.discipline ? ' · ' + a.discipline.toLowerCase() : ''}.`,
                    hosts.length && `Reachable hosts: ${hosts.join(' · ')}.`,
                    'Prefers dimensions on exterior walls first.',
                  ].filter(Boolean).map((f, i) => (
                    <div key={i} style={{ display: 'flex', gap: 8, padding: '4px 0', fontSize: 12.5, color: AC.inkSoft, lineHeight: 1.5 }}>
                      <span style={{ color: AC.accent }}>▸</span><span>{f}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12, fontFamily: AC.mono, fontSize: 10.5, color: AC.inkSoft }}>
                <span style={{ padding: '3px 8px', borderRadius: AC.rad.sm, border: `1px solid ${AC.ok}`, color: AC.ok, fontSize: 9, letterSpacing: '0.12em' }}>LOCAL</span>
                <span>{a.brain.path}</span>
              </div>
            </div>
          )}
        </div>

        {/* footer */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '13px 24px', borderTop: `1px solid ${AC.line}`, background: AC.bg }}>
          <button onClick={step === 0 ? onCancel : () => setStep(s => s - 1)} style={smallBtn()}>
            {step === 0 ? 'Cancel' : '← Back'}
          </button>
          <span style={{ flex: 1, fontFamily: AC.mono, fontSize: 9.5, color: AC.inkMuted, letterSpacing: '0.1em' }}>
            STEP {step + 1} / 4 · {(AC_PLANS.find(p => p.id === a.plan) || AC_PLANS[1]).name.toUpperCase()} PLAN
          </span>
          <button disabled={!canNext} onClick={step === 3 ? finish : () => setStep(s => s + 1)}
            style={Object.assign({}, smallBtn(true), { padding: '7px 16px', opacity: canNext ? 1 : 0.4, cursor: canNext ? 'pointer' : 'not-allowed' })}>
            {step === 3 ? 'Open my workspace →' : 'Continue →'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// SETTINGS › ACCOUNT & USAGE — the surface that has to keep the website's promises:
// what you're on, what you've spent against your own cap, and where the brain lives.
// ─────────────────────────────────────────────────────────────
const acMeter = (label, val, max, unit, col) => {
  const pct = Math.min(100, Math.round((val / max) * 100));
  const hot = pct >= 80;
  return (
    <div key={label} style={{ marginBottom: 14 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 5 }}>
        <span style={{ fontSize: 12.5, color: AC.ink }}>{label}</span>
        <span style={{ flex: 1 }}/>
        <span style={{ fontFamily: AC.serif, fontSize: 19, color: hot ? AC.warn : col || AC.ink, lineHeight: 1 }}>
          {unit === '$' ? '$' : ''}{val.toLocaleString()}
        </span>
        <span style={{ fontFamily: AC.mono, fontSize: 10, color: AC.inkSoft }}>
          / {unit === '$' ? '$' : ''}{max.toLocaleString()}{unit !== '$' ? ' ' + unit : ''}
        </span>
      </div>
      <div style={{ height: 5, background: AC.lineSoft, borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: pct + '%', height: '100%', background: hot ? AC.warn : col || AC.accent, transition: 'width .3s' }}/>
      </div>
      <div style={{ fontFamily: AC.mono, fontSize: 9.5, color: hot ? AC.warn : AC.inkMuted, marginTop: 4, letterSpacing: '0.06em' }}>
        {pct}% USED{hot ? ' · APPROACHING YOUR CAP' : ''}
      </div>
    </div>
  );
};

// The three brain-folder controls, each doing the thing it names: open
// the folder in Explorer, choose where a copy syncs, and hand the
// founder his own record as a file. Every answer is reported in place.
function BrainFolderActions() {
  const [said, setSaid] = React.useState('');
  const speak = (text) => { setSaid(text); setTimeout(() => setSaid(''), 5000); };
  const reveal = async () => {
    try {
      const answer = await window.ARCHHUB_REVEAL('brain');
      speak(answer.ok ? 'opened ' + answer.opened : answer.error);
    } catch (error) { speak('refused: ' + (error?.message || error)); }
  };
  const choose = async () => {
    try {
      const chosen = await window.ARCHHUB_PICK_FILE(
        'Choose a folder to sync into (pick any file inside it)', '');
      if (!chosen) return;
      const folder = chosen.replace(/[\/][^\/]*$/, '');
      const held = acLoad();
      acSave(Object.assign({}, held, { syncFolder: folder }));
      speak('sync folder: ' + folder);
    } catch (error) { speak('refused: ' + (error?.message || error)); }
  };
  const exportJson = () => {
    const payload = JSON.stringify({
      account: acLoad(),
      graph: window.ARCHHUB_LIVE?.graph
        ? { nodes: window.ARCHHUB_LIVE.graph.nodes.length,
            wires: window.ARCHHUB_LIVE.graph.wires.length }
        : null,
      connectors: window.ARCHHUB_LIVE?.connectors || [],
      skills: (window.ARCHHUB_LIVE?.skills || []).map(s => s.name),
      exported_at: new Date().toISOString(),
    }, null, 2);
    const url = URL.createObjectURL(new Blob([payload], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url; link.download = 'archhub-account.json';
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
    speak('exported archhub-account.json');
  };
  return (
    <div style={{ display: 'flex', gap: 7, alignItems: 'center', flexWrap: 'wrap' }}>
      <button onClick={reveal} style={smallBtn()}>Reveal in explorer</button>
      <button onClick={choose} style={smallBtn()}>Choose sync folder</button>
      <button onClick={exportJson} style={smallBtn()}>Export as JSON</button>
      {said ? <span style={{ fontFamily: AC.mono, fontSize: 10, color: AC.inkSoft }}>{said}</span> : null}
    </div>
  );
}

function SettingsAccount({ account, setAccount, onSignOut }) {
  // Prefer the live record on disk when the passed snapshot predates a sign-up — this panel
  // states someone's plan and spend, so it must not render a stale one.
  const live = acLoad();
  const a = (account && account.signedIn) || !live.signedIn ? (account || live) : live;
  const plan = AC_PLANS.find(p => p.id === a.plan) || AC_PLANS[1];
  const u = a.usage;
  const patchA = (patch) => { const next = Object.assign({}, a, patch); acSave(next); setAccount && setAccount(next); };
  return (
    <div>
      <SHead title="Account & usage" sub="What you're on, what you've spent against your own cap, and where your brain lives. The cap is yours to set — we stop, we don't invoice past it."/>

      {/* identity */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 14px', border: `1px solid ${AC.line}`, borderRadius: AC.rad.md, marginBottom: 16 }}>
        <span style={{
          width: 38, height: 38, borderRadius: '50%', flexShrink: 0, display: 'grid', placeItems: 'center',
          background: AC.accentSoft, color: AC.accent, fontFamily: AC.serif, fontSize: 17,
        }}>{(a.name || 'A').slice(0, 1).toUpperCase()}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13.5, fontWeight: 500 }}>{a.name || 'Not signed in'}</div>
          <div style={{ fontFamily: AC.mono, fontSize: 10.5, color: AC.inkSoft, marginTop: 2 }}>
            {a.email || '—'}{a.firm ? ' · ' + a.firm : ''}
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontFamily: AC.mono, fontSize: 9, color: AC.inkMuted, letterSpacing: '0.12em' }}>SINCE</div>
          <div style={{ fontFamily: AC.mono, fontSize: 11, color: AC.inkSoft }}>{a.created || '—'}</div>
        </div>
      </div>

      {/* usage meters — real numbers against the plan the account actually holds */}
      <div style={{ fontFamily: AC.mono, fontSize: 9, color: AC.inkMuted, letterSpacing: '0.16em', marginBottom: 9 }}>THIS CYCLE</div>
      {acMeter('Model spend', u.spend, u.cap, '$')}
      {acMeter('Operations run', u.ops, u.opsCap, 'ops', AC.blue)}
      {acMeter('Brain size', a.brain.size, 50, 'MB', AC.purple)}

      {/* spend cap — editable, because the subhead just promised it */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '10px 12px', borderRadius: AC.rad.md, background: AC.bgSoft, marginBottom: 18 }}>
        <span style={{ fontFamily: AC.mono, fontSize: 10, color: AC.inkSoft, letterSpacing: '0.08em' }}>HARD CAP</span>
        {[40, 120, 250, 500].map(c => (
          <button key={c} onClick={() => patchA({ usage: Object.assign({}, u, { cap: c }) })} style={{
            padding: '4px 10px', borderRadius: AC.rad.sm, cursor: 'pointer', fontFamily: AC.mono, fontSize: 11,
            border: `1px solid ${u.cap === c ? AC.accent : AC.line}`,
            background: u.cap === c ? AC.accentSoft : 'transparent',
            color: u.cap === c ? AC.ink : AC.inkSoft,
          }}>${c}</button>
        ))}
        <span style={{ flex: 1 }}/>
        <span style={{ fontFamily: AC.mono, fontSize: 9.5, color: AC.inkMuted }}>runs stop at the cap</span>
      </div>

      {/* plan */}
      <div style={{ fontFamily: AC.mono, fontSize: 9, color: AC.inkMuted, letterSpacing: '0.16em', marginBottom: 9 }}>SUBSCRIPTION</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 8, marginBottom: 10 }}>
        {AC_PLANS.map(p => {
          const on = p.id === a.plan;
          return (
            <button key={p.id} onClick={() => patchA({ plan: p.id, usage: Object.assign({}, u, { cap: p.cap, opsCap: p.ops }) })}
              style={{
                textAlign: 'left', padding: '11px 12px', cursor: 'pointer', borderRadius: AC.rad.md,
                border: `1px solid ${on ? AC.accent : AC.line}`, background: on ? AC.accentSoft : AC.bg,
                color: AC.ink, fontFamily: AC.sans,
              }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 5 }}>
                <span style={{ fontFamily: AC.serif, fontSize: 22, lineHeight: 1 }}>${p.price}</span>
                <span style={{ fontFamily: AC.mono, fontSize: 9.5, color: AC.inkSoft }}>/mo</span>
              </div>
              <div style={{ fontSize: 12.5, fontWeight: 500, marginTop: 5 }}>{p.name}{on ? ' · current' : ''}</div>
              <div style={{ fontSize: 11, color: AC.inkSoft, marginTop: 3, lineHeight: 1.45 }}>{p.line}</div>
              <div style={{ fontFamily: AC.mono, fontSize: 9.5, color: AC.inkMuted, marginTop: 6 }}>
                ${p.cap} cap · {(p.ops / 1000)}k ops · {p.seats} seat{p.seats > 1 ? 's' : ''}
              </div>
            </button>
          );
        })}
      </div>

      {/* brain access — the one thing the user was explicit about: NOT on a git remote */}
      <div style={{ fontFamily: AC.mono, fontSize: 9, color: AC.inkMuted, letterSpacing: '0.16em', margin: '18px 0 9px' }}>BRAIN ACCESS</div>
      <div style={{ padding: '12px 14px', border: `1px solid ${AC.line}`, borderRadius: AC.rad.md }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ padding: '3px 8px', borderRadius: AC.rad.sm, border: `1px solid ${AC.ok}`, color: AC.ok, fontFamily: AC.mono, fontSize: 9, letterSpacing: '0.12em' }}>LOCAL</span>
          <span style={{ fontFamily: AC.mono, fontSize: 11.5, color: AC.ink, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>{a.brain.path}</span>
          <span style={{ fontFamily: AC.mono, fontSize: 10.5, color: AC.inkSoft }}>{a.brain.facts} facts · {a.brain.size} MB</span>
        </div>
        <div style={{ fontSize: 12, color: AC.inkSoft, marginTop: 9, lineHeight: 1.55 }}>
          Your brain is a folder on your disk. It is never uploaded to us and never pushed to a
          git remote — sync is a directory you nominate, so the practice controls the copy.
        </div>
        <div style={{ display: 'flex', gap: 7, marginTop: 10 }}>
          <BrainFolderActions/>
        </div>
      </div>

      {a.signedIn && (
        <button onClick={onSignOut} style={Object.assign({}, smallBtn(), { marginTop: 16, color: AC.err, borderColor: AC.lineSoft })}>
          Sign out
        </button>
      )}
    </div>
  );
}

Object.assign(window, { AppBoot, SignUp, SettingsAccount, acLoad, acSave, AC_PLANS, AC_SEED });
