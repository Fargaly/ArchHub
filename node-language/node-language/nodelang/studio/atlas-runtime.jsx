// atlas-runtime.jsx — the WORKING-GRAPH runtime, shared logic with the app's node canvas.
// Nodes run; wires carry the run downstream; editing marks dependents stale; watcher
// nodes show live results; every run is recorded (history / variants tree).
// Pure helpers + small UI + CSS. Exposed on window.RT.

const { HB } = window;

const RT_COL = { fresh: HB.green, stale: HB.amber, running: HB.accent, error: HB.red, idle: HB.inkMute };
const rtState = (n) => (n && n.rt && n.rt.state) || 'idle';
const rtRuns = (n) => (n && n.rt && n.rt.runs) || [];

// plausible result a node emits, by category — what a watcher would display
function rtResult(node) {
  const c = node.cat || 'logic';
  const map = {
    vision: '3 masses · 1,240 px → mesh', compose: 'sheet set A.101–A.108 · 8 sheets',
    output: '47 dimensions placed · 4.2s', transform: '212 elements remapped',
    extract: '18 rooms · 96 walls', logic: 'ok · 12 rules passed', skill: 'pipeline ✓ 6 stages',
    connector: 'session live · 41ms p50', host: 'handshake ✓ :48884', ai: '1,820 tok · $0.04',
    input: 'sketch.png · 1.2 MB', trigger: 'fired · 1 event', watch: '—', preview: '—', note: '—',
  };
  return map[c] || 'ok';
}

let RUN_SEQ = 1;
function mkRun(node, variantOf) {
  const ms = 200 + Math.floor(Math.random() * 1400);
  return { id: 'r' + (RUN_SEQ++), n: rtRuns(node).length + 1, t: Date.now(), ms, ok: Math.random() > 0.08, result: rtResult(node), variantOf: variantOf || null };
}

// downstream node ids reachable from id along out-wires (1 hop — direct dependents)
function downstream(M, id) { const out = []; M.wires.forEach(w => { if (w.a === id) out.push(w.b); }); return [...new Set(out)]; }
function upstreamIds(M, id) { const ins = []; M.wires.forEach(w => { if (w.b === id) ins.push(w.a); }); return [...new Set(ins)]; }

// inject runtime CSS once
if (typeof document !== 'undefined' && !document.getElementById('rt-anim')) {
  const s = document.createElement('style'); s.id = 'rt-anim';
  s.textContent = `
    @keyframes rtRing{0%{opacity:.9;r:4}70%{opacity:0;r:14}100%{opacity:0;r:14}}
    @keyframes rtDash{to{stroke-dashoffset:-22}}
    .rt-run-ring{animation:rtRing 1.3s ease-out infinite}
    .rt-flow{stroke-dasharray:6 6;animation:rtDash .6s linear infinite}
  `;
  document.head.appendChild(s);
}

// a small runtime chip for inspectors
function RTChip({ state }) {
  const c = RT_COL[state] || HB.inkMute;
  return <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '3px 9px', borderRadius: 999, background: c + '1e', border: `1px solid ${c}`, color: c, fontFamily: HB.mono, fontSize: 9.5, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
    <span style={{ width: 6, height: 6, borderRadius: '50%', background: c, animation: state === 'running' ? 'rtRing 1.2s infinite' : 'none' }}/>{state}
  </span>;
}

// the Runs / history (tree) tab body
function RunsBody({ node, onRun, onVariant }) {
  const runs = rtRuns(node).slice().reverse();
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <RTChip state={rtState(node)}/>
        <span style={{ fontFamily: HB.mono, fontSize: 10, color: HB.inkMute }}>{runs.length} runs</span>
        <div style={{ flex: 1 }}/>
        <button onClick={onRun} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 12px', borderRadius: 7, border: 'none', background: HB.accent, color: '#fff', cursor: 'pointer', fontFamily: HB.mono, fontSize: 11, fontWeight: 600 }}>▸ Run</button>
      </div>
      {runs.length === 0 && <div style={{ fontFamily: HB.serif, fontStyle: 'italic', fontSize: 13, color: HB.inkMute }}>No runs yet. Run it to produce a result and start the history tree.</div>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
        {runs.map((r, i) => (
          <div key={r.id} style={{ display: 'flex', gap: 10, paddingLeft: r.variantOf ? 18 : 0 }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: r.ok ? HB.green : HB.red, marginTop: 6 }}/>
              {i < runs.length - 1 && <span style={{ flex: 1, width: 1.5, background: HB.line }}/>}
            </div>
            <div style={{ flex: 1, paddingBottom: 12 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 7 }}>
                <span style={{ fontFamily: HB.mono, fontSize: 11.5, color: HB.ink }}>{r.variantOf ? '⌥ variant' : 'run'} #{r.n}</span>
                <span style={{ fontFamily: HB.mono, fontSize: 9.5, color: r.ok ? HB.green : HB.red }}>{r.ok ? '✓' : '✗ failed'}</span>
                <span style={{ fontFamily: HB.mono, fontSize: 9.5, color: HB.inkMute }}>{r.ms}ms</span>
                <button onClick={() => onVariant(r)} title="Branch a variant from this run" style={{ marginLeft: 'auto', border: `1px solid ${HB.line}`, background: HB.paper2, color: HB.inkSoft, borderRadius: 6, padding: '2px 7px', cursor: 'pointer', fontFamily: HB.mono, fontSize: 9 }}>⌥ variant</button>
              </div>
              <div style={{ fontFamily: HB.mono, fontSize: 11, color: HB.inkSoft, marginTop: 3 }}>{r.result}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

Object.assign(window, { RT: { RT_COL, rtState, rtRuns, rtResult, mkRun, downstream, upstreamIds, RTChip, RunsBody } });
