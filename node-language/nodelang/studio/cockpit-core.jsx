// cockpit-core.jsx — ARCHHUB FOUNDER COCKPIT · God Mode. (rev2)
// Shared seed DATA (the actual application databases), persistence, and UI atoms.
// Derives 100% of its palette from window.AH (tokens.jsx) — no hardcoded hexes.
// Everything here is editable at runtime and persisted to localStorage; the
// cockpit is the real control surface, not a dashboard for show.

const CK = window.AH;
const CKLS = 'archhub.cockpit.v1';

/* ════════════════ persistence ════════════════ */
const ckLoad = () => { try { const s = JSON.parse(localStorage.getItem(CKLS)); if (s && s._v === 1) return s; } catch (e) {} return null; };
const ckSave = (db) => { try { localStorage.setItem(CKLS, JSON.stringify({ ...db, _v: 1 })); } catch (e) {} };
const uid = (p = 'id') => p + '_' + Math.random().toString(36).slice(2, 8);

/* ════════════════ SEED — the application databases ════════════════ */
// These mirror what the live product would hold. The founder edits these directly.

const SEED_FIRMS = [
  { id: 'f_habib',  name: 'Habib Studio',      plan: 'Studio', seats: 14, mrr: 1106, region: 'MA·Casablanca', since: '2024-11', health: 'green',  brain: 'br_habib' },
  { id: 'f_north',  name: 'Northline Arch',    plan: 'Studio', seats: 22, mrr: 1738, region: 'US·Chicago',    since: '2025-01', health: 'green',  brain: 'br_north' },
  { id: 'f_ksa',    name: 'Riyadh BIM Lab',    plan: 'Pro',    seats: 8,  mrr: 312,  region: 'SA·Riyadh',     since: '2025-03', health: 'amber',  brain: 'br_ksa'   },
  { id: 'f_solo',   name: 'C. Fournier (solo)',plan: 'Pro',    seats: 1,  mrr: 39,   region: 'FR·Lyon',       since: '2025-02', health: 'green',  brain: 'br_solo'  },
  { id: 'f_atlas',  name: 'Atlas Engineering', plan: 'Studio', seats: 31, mrr: 2449, region: 'UK·London',     since: '2024-12', health: 'red',    brain: 'br_atlas' },
  { id: 'f_delta',  name: 'Delta Build Co',    plan: 'Free',   seats: 3,  mrr: 0,    region: 'US·Austin',     since: '2025-04', health: 'green',  brain: 'br_delta' },
];

const SEED_USERS = [
  { id: 'u_mh',   name: 'Mehdi Habib',     email: 'mehdi@habib.studio',   role: 'founder', firm: 'f_habib', seat: 'owner',  status: 'active',  last: 'now',     runs: 1284 },
  { id: 'u_sa',   name: 'Sara Amrani',     email: 'sara@habib.studio',    role: 'admin',  firm: 'f_habib', seat: 'editor', status: 'active',  last: '4m',      runs: 642  },
  { id: 'u_jd',   name: 'James Dornan',    email: 'james@northline.com',  role: 'admin',  firm: 'f_north', seat: 'owner',  status: 'active',  last: '20m',     runs: 911  },
  { id: 'u_kp',   name: 'Kavya Pillai',    email: 'kavya@northline.com',  role: 'member', firm: 'f_north', seat: 'editor', status: 'active',  last: '1h',      runs: 388  },
  { id: 'u_fa',   name: 'Faisal Otaibi',   email: 'faisal@riyadhbim.sa',  role: 'admin',  firm: 'f_ksa',   seat: 'owner',  status: 'active',  last: '3h',      runs: 204  },
  { id: 'u_cf',   name: 'Claire Fournier', email: 'claire@fournier.fr',   role: 'member', firm: 'f_solo',  seat: 'owner',  status: 'active',  last: 'yesterday', runs: 156 },
  { id: 'u_ap',   name: 'Adam Price',      email: 'adam@atlas-eng.uk',    role: 'admin',  firm: 'f_atlas', seat: 'owner',  status: 'suspended', last: '2d',    runs: 1502 },
  { id: 'u_rw',   name: 'Rachel Wong',     email: 'rachel@atlas-eng.uk',  role: 'member', firm: 'f_atlas', seat: 'editor', status: 'active',  last: '5h',      runs: 720  },
  { id: 'u_dt',   name: 'Diego Torres',    email: 'diego@deltabuild.co',  role: 'member', firm: 'f_delta', seat: 'viewer', status: 'invited', last: '—',       runs: 0    },
];

const SEED_BRAINS = [
  { id: 'br_founder', name: 'Founder Brain',     scope: 'global', firm: '—',       memories: 2841, layers: 4, tokens: 18420, sync: 'private-relay', owner: 'u_mh', sees: 'everything' },
  { id: 'br_habib',   name: 'Habib · Firm Brain',scope: 'firm',  firm: 'f_habib', memories: 412,  layers: 4, tokens: 7210,  sync: 'private-relay', owner: 'u_mh', sees: 'firm' },
  { id: 'br_north',   name: 'Northline Brain',   scope: 'firm',  firm: 'f_north', memories: 388,  layers: 4, tokens: 6840,  sync: 'private-relay', owner: 'u_jd', sees: 'firm' },
  { id: 'br_ksa',     name: 'Riyadh Brain',      scope: 'firm',  firm: 'f_ksa',   memories: 96,   layers: 3, tokens: 2010,  sync: 'local-only',    owner: 'u_fa', sees: 'firm' },
  { id: 'br_solo',    name: 'Fournier Brain',    scope: 'personal', firm: 'f_solo', memories: 41, layers: 2, tokens: 880,   sync: 'local-only',    owner: 'u_cf', sees: 'self' },
  { id: 'br_atlas',   name: 'Atlas Brain',       scope: 'firm',  firm: 'f_atlas', memories: 503,  layers: 4, tokens: 9120,  sync: 'private-relay', owner: 'u_ap', sees: 'firm' },
];

const SEED_MODELS = [
  { id: 'm_sonnet', name: 'Claude Sonnet 4.5', vendor: 'Anthropic', ctx: '200k', inCost: 3.0, outCost: 15.0, latency: 420, status: 'primary',  share: 58, tasks: ['intent','vision','compose'] },
  { id: 'm_opus',   name: 'Claude Opus 4.1',   vendor: 'Anthropic', ctx: '200k', inCost: 15.0, outCost: 75.0, latency: 980, status: 'enabled',  share: 6,  tasks: ['critique'] },
  { id: 'm_gpt5',   name: 'GPT-5',             vendor: 'OpenAI',    ctx: '256k', inCost: 5.0, outCost: 20.0, latency: 510, status: 'enabled',  share: 26, tasks: ['fallback','vision'] },
  { id: 'm_gemini', name: 'Gemini 2.5 Pro',    vendor: 'Google',    ctx: '1M',   inCost: 2.0, outCost: 8.0,  latency: 380, status: 'enabled',  share: 9,  tasks: ['extract'] },
  { id: 'm_qwen',   name: 'qwen3:32b',         vendor: 'Ollama',    ctx: '32k',  inCost: 0,   outCost: 0,    latency: 980, status: 'local',    share: 1,  tasks: ['offline'] },
  { id: 'm_mistral',name: 'Mistral Large',     vendor: 'Mistral',   ctx: '128k', inCost: 2.0, outCost: 6.0,  latency: 440, status: 'disabled', share: 0,  tasks: [] },
];

const SEED_SKILLS = [
  { id: 's_sketch', name: 'Sketch → Production', author: 'archhub', scope: 'official', installs: 12400, version: '2.1.0', stages: 6, hosts: ['vision','revit','speckle'], status: 'published' },
  { id: 's_dim',    name: 'Dimension walls',     author: 'archhub', scope: 'official', installs: 18200, version: '1.4.2', stages: 1, hosts: ['revit'],   status: 'published' },
  { id: 's_doors',  name: 'Doors & windows from plan', author: '@mhabib', scope: 'firm', installs: 89, version: '0.9.0', stages: 2, hosts: ['revit'], status: 'published' },
  { id: 's_boq',    name: 'BOQ → Excel',         author: '@studio_lk', scope: 'community', installs: 3100, version: '1.1.0', stages: 3, hosts: ['revit','excel'], status: 'review' },
  { id: 's_layer',  name: 'AutoCAD layer cleanup', author: '@drafter', scope: 'community', installs: 8100, version: '2.0.1', stages: 1, hosts: ['autocad'], status: 'published' },
  { id: 's_curtain',name: 'Curtain wall optimizer', author: '@panel_co', scope: 'community', installs: 4000, version: '1.2.0', stages: 3, hosts: ['rhino','revit'], status: 'flagged' },
];

const SEED_CONNECTORS = [
  { id: 'c_revit',  name: 'Revit 2025',  port: 48884, sessions: 1240, status: 'healthy',  uptime: 99.97, heals7d: 47, p50: 340 },
  { id: 'c_rhino',  name: 'Rhino 8',     port: 48887, sessions: 612,  status: 'healthy',  uptime: 99.99, heals7d: 12, p50: 210 },
  { id: 'c_acad',   name: 'AutoCAD 2025',port: 48885, sessions: 880,  status: 'healing',  uptime: 99.71, heals7d: 64, p50: 520 },
  { id: 'c_speckle',name: 'Speckle',     port: null,  sessions: 430,  status: 'healthy',  uptime: 99.95, heals7d: 3,  p50: 180 },
  { id: 'c_blender',name: 'Blender 4.2', port: 9876,  sessions: 254,  status: 'degraded', uptime: 98.40, heals7d: 31, p50: 740 },
  { id: 'c_max',    name: '3ds Max 2025',port: 48886, sessions: 96,   status: 'idle',     uptime: 99.20, heals7d: 8,  p50: 410 },
];

const SEED_ISSUES = [
  { id: 'i_481', level: 'error', title: "TypeError: cannot read 'port' of null", where: 'connector/speckle.rebind', count: 142, users: 18, last: '6m', status: 'open',  assignee: null,  release: 'v0.27.0' },
  { id: 'i_477', level: 'error', title: 'RPC heartbeat timeout (3 retries) — AutoCAD', where: 'heal/watchdog', count: 64, users: 9, last: '21m', status: 'investigating', assignee: 'ag_heal', release: 'v0.27.0' },
  { id: 'i_469', level: 'warn',  title: 'Skill JSON schema drift on import', where: 'brain/skill.parse', count: 38, users: 12, last: '1h', status: 'open',  assignee: null,  release: 'v0.26.4' },
  { id: 'i_462', level: 'error', title: 'OOM during 1M-token Gemini vision pass', where: 'model/router', count: 11, users: 3, last: '3h', status: 'open',  assignee: 'ag_router', release: 'v0.27.0' },
  { id: 'i_455', level: 'info',  title: 'Slow plot: sheet set > 80 sheets', where: 'compose/plot', count: 27, users: 7, last: '5h', status: 'triaged', assignee: null, release: 'v0.26.4' },
  { id: 'i_440', level: 'warn',  title: 'Private relay cert rotation reminder', where: 'sync/relay', count: 6, users: 6, last: '1d', status: 'resolved', assignee: 'ag_ops', release: 'v0.26.3' },
];

const SEED_ROADMAP = [
  // lane: now | next | later | shipped
  { id: 'r_uikit', lane: 'now',   type: 'feature', title: 'Drag-drop UI builder GA', goal: 'Let firms theme ArchHub without code', effort: 'L', owner: 'ag_ui', votes: 34, progress: 60 },
  { id: 'r_relay', lane: 'now',   type: 'infra',   title: 'Private relay for Brain sync', goal: 'Brain never touches GitHub', effort: 'M', owner: 'ag_ops', votes: 51, progress: 80 },
  { id: 'r_heal2', lane: 'next',  type: 'feature', title: 'Self-heal v2 — predictive', goal: 'Reconnect before the drop', effort: 'L', owner: 'ag_heal', votes: 42, progress: 15 },
  { id: 'r_market',lane: 'next',  type: 'growth',  title: 'Skill marketplace payouts', goal: 'Pay community skill authors', effort: 'M', owner: 'ag_growth', votes: 28, progress: 5 },
  { id: 'r_mobile',lane: 'later', type: 'feature', title: 'Mobile companion · review on site', goal: 'Approve the line from the field', effort: 'L', owner: null, votes: 19, progress: 0 },
  { id: 'r_sso',   lane: 'later', type: 'infra',   title: 'Enterprise SSO + audit log', goal: 'Unlock large firms', effort: 'M', owner: null, votes: 23, progress: 0 },
  { id: 'r_dim',   lane: 'shipped', type: 'feature', title: 'Auto-dimension active view', goal: 'Ship CD faster', effort: 'S', owner: 'ag_compose', votes: 67, progress: 100 },
];

const SEED_AGENTS = [
  { id: 'ag_ui',      name: 'UI-Builder Agent', model: 'm_sonnet', task: 'Wire drag-drop builder to live theme tokens', status: 'working', brain: 'br_founder', autonomy: 'propose', queue: 3 },
  { id: 'ag_ops',     name: 'Ops Agent',        model: 'm_sonnet', task: 'Rotate private-relay certs, watch fleet', status: 'working', brain: 'br_founder', autonomy: 'act', queue: 1 },
  { id: 'ag_heal',    name: 'Self-Heal Agent',  model: 'm_gemini', task: 'Triage AutoCAD heartbeat timeouts', status: 'working', brain: 'br_founder', autonomy: 'act', queue: 5 },
  { id: 'ag_router',  name: 'Model-Router Agent',model: 'm_qwen',  task: 'Pick cheapest model per task within SLA', status: 'idle', brain: 'br_founder', autonomy: 'act', queue: 0 },
  { id: 'ag_growth',  name: 'Growth Agent',     model: 'm_gpt5',   task: 'Draft marketplace payout spec', status: 'paused', brain: 'br_founder', autonomy: 'propose', queue: 2 },
  { id: 'ag_compose', name: 'Compose Agent',    model: 'm_sonnet', task: 'Idle — last shipped auto-dimension', status: 'idle', brain: 'br_founder', autonomy: 'propose', queue: 0 },
];

// Live org activity — "see and know what everyone is doing". Streamed in Pulse.
const SEED_ACTIVITY = [
  { id: uid('ev'), who: 'u_sa', verb: 'ran skill', what: 'Dimension walls · Tower-A', firm: 'f_habib', t: 2 },
  { id: uid('ev'), who: 'u_jd', verb: 'edited brain', what: 'added detail-library standard', firm: 'f_north', t: 14 },
  { id: uid('ev'), who: 'ag_heal', verb: 'healed', what: 'AutoCAD session #2841 · 38ms', firm: 'f_ksa', t: 22 },
  { id: uid('ev'), who: 'u_fa', verb: 'wired host', what: 'Speckle → riyadh-bim/main', firm: 'f_ksa', t: 48 },
  { id: uid('ev'), who: 'u_rw', verb: 'published skill', what: 'Curtain wall v1.2', firm: 'f_atlas', t: 90 },
];

const SEED_METRICS = {
  mrr: 5644, mrrPrev: 5102, arr: 67728,
  users: 9, usersPrev: 8, firms: 6,
  churn: 1.8, churnPrev: 2.4,
  netNew: 542,
  modelSpend: 47.82, modelBudget: 200,
  mrrSeries: [3980, 4210, 4380, 4520, 4690, 4880, 5102, 5240, 5390, 5470, 5560, 5644],
  usersSeries: [4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9],
  spendSeries: [3.2, 5.1, 4.8, 8.9, 6.1, 11.4, 8.3, 9.1, 7.2, 10.4, 6.9, 8.0],
};

const SEED_FLAGS = [
  { id: 'fl_builder', name: 'ui_builder', desc: 'Drag-drop UI builder', stage: 'beta', rollout: 25, on: true },
  { id: 'fl_heal2',   name: 'predictive_heal', desc: 'Self-heal v2 predictive reconnect', stage: 'internal', rollout: 5, on: true },
  { id: 'fl_payouts', name: 'marketplace_payouts', desc: 'Pay skill authors', stage: 'off', rollout: 0, on: false },
  { id: 'fl_mobile',  name: 'mobile_review', desc: 'Mobile companion review', stage: 'off', rollout: 0, on: false },
  { id: 'fl_relay',   name: 'private_relay', desc: 'Brain sync via private relay (no GitHub)', stage: 'ga', rollout: 100, on: true },
];

const SEED_DB = () => ({
  firms: SEED_FIRMS, users: SEED_USERS, brains: SEED_BRAINS, models: SEED_MODELS,
  skills: SEED_SKILLS, connectors: SEED_CONNECTORS, issues: SEED_ISSUES,
  roadmap: SEED_ROADMAP, agents: SEED_AGENTS, activity: SEED_ACTIVITY,
  metrics: SEED_METRICS, flags: SEED_FLAGS,
  beat: 1,            // founder-controlled simulation tempo
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
  CK, CKLS, ckLoad, ckSave, uid, SEED_DB, sc, STAT,
  CKIcon, Btn, IconBtn, Pill, Dot, Avatar, Field, Select, Toggle, Modal, SecHead, Spark, StatCard,
});
