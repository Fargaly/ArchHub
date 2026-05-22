// AgDR-0026 Phase 2 — extracted from index.html so jsx-boot.js can
// hash + cache it the same way as shared-data.jsx and studio-lm.jsx.
// Functionally identical to the previous inline
//   <script type="text/babel" data-presets="env,react">…</script>.
//
// Boot order (jsx-boot.js):  shared-data.jsx → studio-lm.jsx → app-boot.jsx

const { useState, useEffect, useRef } = React;

// ─── ErrorBoundary: catches render crashes so the app never goes white.
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null, info: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  componentDidCatch(error, info) {
    this.setState({ info });
    try { console.error('[archhub] render crash:', error, info); } catch (e) {}
  }
  render() {
    if (!this.state.error) return this.props.children;
    const stack = (this.state.error && this.state.error.stack) || String(this.state.error);
    const compStack = (this.state.info && this.state.info.componentStack) || '';
    return (
      <div style={{
        minHeight:'100vh', padding:'32px 40px', background:'#0e0e11', color:'#f3efe8',
        fontFamily:'JetBrains Mono, ui-monospace, monospace', fontSize:13, lineHeight:1.55,
      }}>
        <div style={{
          fontFamily:'Instrument Serif, serif', fontStyle:'italic',
          fontSize:42, color:'#e8743a', marginBottom:18,
        }}>ArchHub render crash</div>
        <div style={{ color:'#c9c4ba', marginBottom:18, maxWidth:980 }}>
          The UI hit an exception while rendering. Reload to retry. If it keeps
          happening, copy the trace below for the bridge log.
        </div>
        <pre style={{
          whiteSpace:'pre-wrap', background:'#17171c', border:'1px solid #2a2a32',
          borderRadius:8, padding:'14px 16px', color:'#f3efe8', maxWidth:1100,
          overflow:'auto',
        }}>{stack}{compStack ? '\n\nComponent stack:' + compStack : ''}</pre>
        <button
          onClick={() => location.reload()}
          style={{
            marginTop:18, padding:'10px 18px', borderRadius:6,
            background:'#e8743a', color:'#0e0e11', border:'none',
            fontFamily:'Inter, system-ui, sans-serif', fontWeight:600, fontSize:13,
            cursor:'pointer',
          }}
        >Reload</button>
      </div>
    );
  }
}

// ─── splice helper: replace the contents of a window-exposed array in place.
function spliceInto(targetName, mapped) {
  const target = window[targetName];
  if (!Array.isArray(target) || !Array.isArray(mapped)) return false;
  target.splice(0, target.length, ...mapped);
  return true;
}

// ─── Pull all bridge data, splice into the matching window.__archhub_LM_* arrays.
async function pullAll() {
  const pulls = [
    ['get_sessions',     '__archhub_LM_SESSIONS'],
    ['get_hosts',        '__archhub_LM_HOSTS'],
    ['get_models',       '__archhub_LM_MODELS'],
    ['get_memory_stats', '__archhub_LM_MEMORY_STATS'],
    ['get_saved_skills', '__archhub_LM_SAVED_SKILLS'],
    ['get_permissions',  '__archhub_LM_PERMISSIONS'],
    ['get_providers',    '__archhub_LM_PROVIDERS'],
    ['list_memory_facts','__archhub_LM_MEMORY'],
    // The 16-connector op catalogue — drives the node library.
    ['get_connectors',   '__archhub_LM_CONNECTORS'],
    // The node grammar — the ~12-primitive set the palette is built from.
    ['get_node_grammar', '__archhub_LM_NODE_GRAMMAR'],
    // User-minted custom nodes (AI-designed or hand-built).
    ['get_custom_nodes', '__archhub_LM_CUSTOM_NODES'],
  ];
  let any = false;
  for (const [slot, target] of pulls) {
    try {
      const data = await window.bridgeJson(slot);
      if (data == null) continue;
      const mapped = Array.isArray(data) ? data
                  : (data && Array.isArray(data.items)) ? data.items
                  : (data && Array.isArray(data.facts)) ? data.facts
                  : null;
      if (mapped && spliceInto(target, mapped)) any = true;
    } catch (e) {
      console.warn('[archhub] pull ' + slot + ' failed:', e);
    }
  }
  return any;
}

function App() {
  const [tick, setTick] = useState(0);
  const bumpRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    // Schedule a RE-RENDER (not a remount) after each successful pull
    // batch. bumpRef bumps `tick`, which flows to StudioLM as the
    // `dataVersion` prop below — App re-renders, StudioLM re-renders and
    // re-reads the freshly-spliced window.__archhub_LM_* arrays, but its
    // component state survives.
    bumpRef.current = () => { if (!cancelled) setTick(t => t + 1); };

    pullAll().then((any) => { if (any) bumpRef.current(); });

    // Wire bridge signals. CRITICAL: return disconnect funcs in cleanup
    // so listeners don't accumulate (the 2-min crash root cause).
    const disconnects = [];
    window.archhubReady.then((b) => {
      if (cancelled || !b) return;
      const wire = (sig) => {
        if (!b[sig] || typeof b[sig].connect !== 'function') return;
        const handler = () => { pullAll().then((any) => { if (any) bumpRef.current(); }); };
        b[sig].connect(handler);
        disconnects.push(() => {
          try { b[sig].disconnect(handler); } catch (e) {}
        });
      };
      wire('sessions_changed');
      wire('hosts_changed');
      wire('memory_changed');
      wire('skills_changed');
    });

    return () => {
      cancelled = true;
      bumpRef.current = null;
      for (const off of disconnects) { try { off(); } catch (e) {} }
    };
  }, []);

  // `dataVersion`, NOT `key`. A changing `key` would unmount + remount
  // StudioLM on every background pull — nuking open modals, canvas pan,
  // focus, the active session. Passing it as a prop re-renders the tree
  // (children re-read the LM_* arrays) while preserving all UI state.
  return <StudioLM dataVersion={tick} />;
}

// ─── Boot.
const SplashFader = () => {
  useEffect(() => {
    const s = document.getElementById('__archhub_splash');
    if (!s) return;
    // The splash shows for as long as the boot actually takes — this
    // component mounts only once the full JSX tree is up.  A 350ms
    // floor so even an instant (cache-hit) boot reads as an
    // intentional splash, not a flicker.  Then a 320ms opacity fade.
    const t = setTimeout(() => {
      s.classList.add('fade');
      setTimeout(() => { try { s.remove(); } catch (e) {} }, 320);
    }, 350);
    return () => clearTimeout(t);
  }, []);
  return null;
};

ReactDOM.createRoot(document.getElementById('root')).render(
  <ErrorBoundary>
    <SplashFader />
    <App />
  </ErrorBoundary>
);
