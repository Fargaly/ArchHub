// shared-data.jsx — fake AEC state shared by all three directions

const HOSTS = [
  { id: 'revit',   name: 'Revit 2025',     port: 48884, status: 'connected',    color: '#0696D7', file: 'Tower-A_central.rvt'   },
  { id: 'blender', name: 'Blender 4.2',    port: 9876,  status: 'connected',    color: '#E87D0D', file: 'site_massing.blend'    },
  { id: 'autocad', name: 'AutoCAD 2025',   port: 48885, status: 'reconnecting', color: '#E51937', file: 'L01_floorplan.dwg'     },
  { id: '3dsmax',  name: '3ds Max 2025',   port: 48886, status: 'idle',         color: '#0696D7', file: '—'                     },
  { id: 'speckle', name: 'Speckle',        port: null,  status: 'connected',    color: '#0F62FE', file: 'tower-a/main'          },
];

const LLMS = [
  { id: 'claude-sonnet-4.5', name: 'Claude Sonnet 4.5', vendor: 'Anthropic', latency: 420, cost: '$3/M', selected: true },
  { id: 'gpt-5',             name: 'GPT-5',             vendor: 'OpenAI',    latency: 510, cost: '$5/M' },
  { id: 'gemini-2.5-pro',    name: 'Gemini 2.5 Pro',    vendor: 'Google',    latency: 380, cost: '$2/M' },
  { id: 'qwen3-32b',         name: 'qwen3:32b (local)', vendor: 'Ollama',    latency: 980, cost: 'free' },
];

const SKILLS = [
  { id: 'sk-1',  name: 'Sketch → Production',          host: ['blender','speckle','revit'], stages: 6, runs: 47, fav: true,  cat: 'Pipeline' },
  { id: 'sk-2',  name: 'Dimension walls in active view', host: ['revit'],                   stages: 1, runs: 312, fav: true, cat: 'Annotate' },
  { id: 'sk-3',  name: 'Construction Doc Sprint',       host: ['revit'],                    stages: 4, runs: 18, fav: false, cat: 'Pipeline' },
  { id: 'sk-4',  name: 'Place doors & windows from plan', host: ['revit'],                  stages: 2, runs: 89, fav: true,  cat: 'Modeling' },
  { id: 'sk-5',  name: 'Site massing → Speckle',         host: ['blender','speckle'],       stages: 2, runs: 34, fav: false, cat: 'Pipeline' },
  { id: 'sk-6',  name: 'Detail callouts on sheet',       host: ['revit'],                   stages: 1, runs: 22, fav: false, cat: 'Annotate' },
  { id: 'sk-7',  name: 'Generate elevation tags',        host: ['revit'],                   stages: 1, runs: 67, fav: false, cat: 'Annotate' },
  { id: 'sk-8',  name: '3ds Max camera matrix',          host: ['3dsmax'],                  stages: 1, runs: 8,  fav: false, cat: 'Render' },
  { id: 'sk-9',  name: 'AutoCAD layer cleanup',          host: ['autocad'],                 stages: 1, runs: 41, fav: false, cat: 'Cleanup' },
  { id: 'sk-10', name: 'Curtain wall from façade image', host: ['revit'],                   stages: 3, runs: 12, fav: true,  cat: 'Vision' },
];

const RECENT_CHATS = [
  { id: 'c1', title: 'Tower A — schedule wall types',     when: 'now',         host: 'revit',   pinned: true },
  { id: 'c2', title: 'Convert sketch to 6m gabled mass',  when: '12 min',      host: 'blender', pinned: false },
  { id: 'c3', title: 'Why are doors flipping?',           when: '1 h',         host: 'revit',   pinned: false },
  { id: 'c4', title: 'Site massing → Speckle stream',     when: 'yesterday',   host: 'speckle', pinned: false },
  { id: 'c5', title: 'Camera rig — 12 angles',            when: '2 d',         host: '3dsmax',  pinned: false },
  { id: 'c6', title: 'L01 layer cleanup pass',            when: '3 d',         host: 'autocad', pinned: false },
];

const TASKS = [
  { id: 't1', label: 'Auto-update connector DLL',  state: 'running',  pct: 64, host: 'revit'   },
  { id: 't2', label: 'Sync Skills repo (28 files)', state: 'running', pct: 92, host: null      },
  { id: 't3', label: 'Reconnect AutoCAD (retry 2)', state: 'healing', pct: 30, host: 'autocad' },
  { id: 't4', label: 'Index Speckle commits',      state: 'queued',   pct: 0,  host: 'speckle' },
];

const FINANCE = {
  monthSpend: 47.82,
  budget: 200,
  lastWeek: [3.2, 5.1, 4.8, 8.9, 6.1, 11.4, 8.3],
  byProvider: [
    { name: 'Anthropic', amt: 28.10, pct: 58 },
    { name: 'OpenAI',    amt: 12.40, pct: 26 },
    { name: 'Google',    amt:  4.30, pct: 9  },
    { name: 'OpenRouter',amt:  3.02, pct: 7  },
  ],
};

const CHAT_TRANSCRIPT = [
  { role: 'user', text: 'Dimension all walls in the active view, exterior only.' },
  { role: 'assistant', text: 'I\'ll match the saved Skill `Dimension walls in active view` and constrain to exterior. Running on Revit (Tower-A_central.rvt).', skill: 'Dimension walls in active view', tools: ['revit.get_active_view', 'revit.filter_walls', 'revit.create_dimension'] },
  { role: 'tool',  text: 'revit.filter_walls(category=Walls, exterior=true) → 47 walls' },
  { role: 'tool',  text: 'revit.create_dimension(refs=[...47]) → ✓ 47 dimensions placed in 4.2s' },
  { role: 'assistant', text: 'Done — 47 exterior walls dimensioned in the active view. Save this run as a Skill variant?' },
];

// Tiny inline SVG icons (no emoji, no fontawesome)
const Icon = ({ name, size=16, stroke=1.6, color='currentColor' }) => {
  const p = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: color, strokeWidth: stroke, strokeLinecap: 'round', strokeLinejoin: 'round' };
  switch (name) {
    case 'chat':     return <svg {...p}><path d="M21 12a8 8 0 1 1-3.5-6.6L21 4l-1 4.2A8 8 0 0 1 21 12Z"/></svg>;
    case 'skill':    return <svg {...p}><path d="M12 2 4 6v6c0 5 3.5 8.5 8 10 4.5-1.5 8-5 8-10V6l-8-4Z"/></svg>;
    case 'flow':     return <svg {...p}><circle cx="6" cy="6" r="2.4"/><circle cx="18" cy="6" r="2.4"/><circle cx="12" cy="18" r="2.4"/><path d="M8 7l3 9M16 7l-3 9"/></svg>;
    case 'gauge':    return <svg {...p}><path d="M3 12a9 9 0 0 1 18 0"/><path d="m12 12 4-3"/></svg>;
    case 'plug':     return <svg {...p}><path d="M9 2v6M15 2v6M7 8h10v4a5 5 0 0 1-10 0V8ZM12 17v5"/></svg>;
    case 'gear':     return <svg {...p}><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/></svg>;
    case 'send':     return <svg {...p}><path d="m22 2-7 20-4-9-9-4 20-7Z"/></svg>;
    case 'star':     return <svg {...p}><path d="m12 2 3 7 7 .6-5.3 4.6L18 22l-6-3.6L6 22l1.3-7.8L2 9.6 9 9l3-7Z"/></svg>;
    case 'starF':    return <svg viewBox="0 0 24 24" width={size} height={size} fill={color}><path d="m12 2 3 7 7 .6-5.3 4.6L18 22l-6-3.6L6 22l1.3-7.8L2 9.6 9 9l3-7Z"/></svg>;
    case 'plus':     return <svg {...p}><path d="M12 5v14M5 12h14"/></svg>;
    case 'search':   return <svg {...p}><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>;
    case 'play':     return <svg {...p}><path d="M6 4v16l14-8L6 4Z"/></svg>;
    case 'check':    return <svg {...p}><path d="m4 12 5 5L20 6"/></svg>;
    case 'alert':    return <svg {...p}><path d="M12 2 1 21h22L12 2Z"/><path d="M12 9v5M12 18v.01"/></svg>;
    case 'spark':    return <svg {...p}><path d="M12 2v4M12 18v4M2 12h4M18 12h4M5 5l3 3M16 16l3 3M19 5l-3 3M8 16l-3 3"/></svg>;
    case 'home':     return <svg {...p}><path d="m3 11 9-8 9 8"/><path d="M5 10v10h14V10"/></svg>;
    case 'history':  return <svg {...p}><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/></svg>;
    case 'folder':   return <svg {...p}><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"/></svg>;
    case 'sun':      return <svg {...p}><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>;
    case 'moon':     return <svg {...p}><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>;
    case 'mic':      return <svg {...p}><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>;
    case 'image':    return <svg {...p}><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5-9 9"/></svg>;
    case 'code':     return <svg {...p}><path d="m8 6-6 6 6 6M16 6l6 6-6 6"/></svg>;
    case 'wrench':   return <svg {...p}><path d="M14.7 6.3a4 4 0 0 1 5 5L17 14l-4-4 1.7-3.7Z"/><path d="m13 10-9 9 2 2 9-9"/></svg>;
    case 'dot':      return <svg viewBox="0 0 8 8" width={size} height={size}><circle cx="4" cy="4" r="3" fill={color}/></svg>;
    case 'x':        return <svg {...p}><path d="m6 6 12 12M18 6 6 18"/></svg>;
    case 'cmd':      return <svg {...p}><path d="M9 6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3V6Z"/></svg>;
    case 'arrowR':   return <svg {...p}><path d="M5 12h14M13 5l7 7-7 7"/></svg>;
    case 'menu':     return <svg {...p}><path d="M4 6h16M4 12h16M4 18h16"/></svg>;
    case 'paint':    return <svg {...p}><circle cx="12" cy="12" r="9"/><circle cx="7.5" cy="10.5" r="1.2" fill="currentColor"/><circle cx="11" cy="7" r="1.2" fill="currentColor"/><circle cx="15.5" cy="9" r="1.2" fill="currentColor"/><circle cx="16" cy="14" r="1.2" fill="currentColor"/></svg>;
    default:         return null;
  }
};

// Hook: typewriter for fake LLM streaming
function useTypewriter(text, speed=14, deps=[]) {
  const [shown, setShown] = React.useState('');
  React.useEffect(() => {
    setShown('');
    if (!text) return;
    let i = 0;
    const t = setInterval(() => {
      i += 1;
      setShown(text.slice(0, i));
      if (i >= text.length) clearInterval(t);
    }, speed);
    return () => clearInterval(t);
  }, deps);
  return shown;
}

// Self-healing connector: cycles AutoCAD: reconnecting -> connected -> idle -> reconnecting...
// to demonstrate the "self-healing" feel without user action.
function useSelfHealingHosts() {
  const [hosts, setHosts] = React.useState(HOSTS);
  React.useEffect(() => {
    const id = setInterval(() => {
      setHosts(prev => prev.map(h => {
        if (h.id !== 'autocad') return h;
        const order = ['reconnecting', 'connected', 'connected', 'connected', 'idle'];
        const next = order[(order.indexOf(h.status) + 1) % order.length];
        return { ...h, status: next };
      }));
    }, 4200);
    return () => clearInterval(id);
  }, []);
  return [hosts, setHosts];
}

Object.assign(window, { HOSTS, LLMS, SKILLS, RECENT_CHATS, TASKS, FINANCE, CHAT_TRANSCRIPT, Icon, useTypewriter, useSelfHealingHosts });
