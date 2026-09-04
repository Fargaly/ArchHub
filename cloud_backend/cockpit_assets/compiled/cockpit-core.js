function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }
function _toConsumableArray(r) { return _arrayWithoutHoles(r) || _iterableToArray(r) || _unsupportedIterableToArray(r) || _nonIterableSpread(); }
function _nonIterableSpread() { throw new TypeError("Invalid attempt to spread non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _iterableToArray(r) { if ("undefined" != typeof Symbol && null != r[Symbol.iterator] || null != r["@@iterator"]) return Array.from(r); }
function _arrayWithoutHoles(r) { if (Array.isArray(r)) return _arrayLikeToArray(r); }
function _slicedToArray(r, e) { return _arrayWithHoles(r) || _iterableToArrayLimit(r, e) || _unsupportedIterableToArray(r, e) || _nonIterableRest(); }
function _nonIterableRest() { throw new TypeError("Invalid attempt to destructure non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _unsupportedIterableToArray(r, a) { if (r) { if ("string" == typeof r) return _arrayLikeToArray(r, a); var t = {}.toString.call(r).slice(8, -1); return "Object" === t && r.constructor && (t = r.constructor.name), "Map" === t || "Set" === t ? Array.from(r) : "Arguments" === t || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t) ? _arrayLikeToArray(r, a) : void 0; } }
function _arrayLikeToArray(r, a) { (null == a || a > r.length) && (a = r.length); for (var e = 0, n = Array(a); e < a; e++) n[e] = r[e]; return n; }
function _iterableToArrayLimit(r, l) { var t = null == r ? null : "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (null != t) { var e, n, i, u, a = [], f = !0, o = !1; try { if (i = (t = t.call(r)).next, 0 === l) { if (Object(t) !== t) return; f = !1; } else for (; !(f = (e = i.call(t)).done) && (a.push(e.value), a.length !== l); f = !0); } catch (r) { o = !0, n = r; } finally { try { if (!f && null != t["return"] && (u = t["return"](), Object(u) !== u)) return; } finally { if (o) throw n; } } return a; } }
function _arrayWithHoles(r) { if (Array.isArray(r)) return r; }
function ownKeys(e, r) { var t = Object.keys(e); if (Object.getOwnPropertySymbols) { var o = Object.getOwnPropertySymbols(e); r && (o = o.filter(function (r) { return Object.getOwnPropertyDescriptor(e, r).enumerable; })), t.push.apply(t, o); } return t; }
function _objectSpread(e) { for (var r = 1; r < arguments.length; r++) { var t = null != arguments[r] ? arguments[r] : {}; r % 2 ? ownKeys(Object(t), !0).forEach(function (r) { _defineProperty(e, r, t[r]); }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) { Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r)); }); } return e; }
function _defineProperty(e, r, t) { return (r = _toPropertyKey(r)) in e ? Object.defineProperty(e, r, { value: t, enumerable: !0, configurable: !0, writable: !0 }) : e[r] = t, e; }
function _toPropertyKey(t) { var i = _toPrimitive(t, "string"); return "symbol" == _typeof(i) ? i : i + ""; }
function _toPrimitive(t, r) { if ("object" != _typeof(t) || !t) return t; var e = t[Symbol.toPrimitive]; if (void 0 !== e) { var i = e.call(t, r || "default"); if ("object" != _typeof(i)) return i; throw new TypeError("@@toPrimitive must return a primitive value."); } return ("string" === r ? String : Number)(t); }
// cockpit-core.jsx — ARCHHUB FOUNDER COCKPIT · God Mode. (rev2)
// Shared seed DATA (the actual application databases), persistence, and UI atoms.
// Derives 100% of its palette from window.AH (tokens.jsx) — no hardcoded hexes.
// Everything here is editable at runtime and persisted to localStorage; the
// cockpit is the real control surface, not a dashboard for show.

var CK = window.AH;
var CKLS = 'archhub.cockpit.v1';

/* ════════════════ persistence ════════════════ */
var ckLoad = function ckLoad() {
  try {
    var s = JSON.parse(localStorage.getItem(CKLS));
    if (s && s._v === 1) return s;
  } catch (e) {}
  return null;
};
var ckSave = function ckSave(db) {
  try {
    localStorage.setItem(CKLS, JSON.stringify(_objectSpread(_objectSpread({}, db), {}, {
      _v: 1
    })));
  } catch (e) {}
};
var uid = function uid() {
  var p = arguments.length > 0 && arguments[0] !== undefined ? arguments[0] : 'id';
  return p + '_' + Math.random().toString(36).slice(2, 8);
};

/* ════════════════ SEED — the application databases ════════════════ */
// These mirror what the live product would hold. The founder edits these directly.

var SEED_FIRMS = [{
  id: 'f_habib',
  name: 'Habib Studio',
  plan: 'Studio',
  seats: 14,
  mrr: 1106,
  region: 'MA·Casablanca',
  since: '2024-11',
  health: 'green',
  brain: 'br_habib'
}, {
  id: 'f_north',
  name: 'Northline Arch',
  plan: 'Studio',
  seats: 22,
  mrr: 1738,
  region: 'US·Chicago',
  since: '2025-01',
  health: 'green',
  brain: 'br_north'
}, {
  id: 'f_ksa',
  name: 'Riyadh BIM Lab',
  plan: 'Pro',
  seats: 8,
  mrr: 312,
  region: 'SA·Riyadh',
  since: '2025-03',
  health: 'amber',
  brain: 'br_ksa'
}, {
  id: 'f_solo',
  name: 'C. Fournier (solo)',
  plan: 'Pro',
  seats: 1,
  mrr: 39,
  region: 'FR·Lyon',
  since: '2025-02',
  health: 'green',
  brain: 'br_solo'
}, {
  id: 'f_atlas',
  name: 'Atlas Engineering',
  plan: 'Studio',
  seats: 31,
  mrr: 2449,
  region: 'UK·London',
  since: '2024-12',
  health: 'red',
  brain: 'br_atlas'
}, {
  id: 'f_delta',
  name: 'Delta Build Co',
  plan: 'Free',
  seats: 3,
  mrr: 0,
  region: 'US·Austin',
  since: '2025-04',
  health: 'green',
  brain: 'br_delta'
}];
var SEED_USERS = [{
  id: 'u_mh',
  name: 'Mehdi Habib',
  email: 'mehdi@habib.studio',
  role: 'founder',
  firm: 'f_habib',
  seat: 'owner',
  status: 'active',
  last: 'now',
  runs: 1284
}, {
  id: 'u_sa',
  name: 'Sara Amrani',
  email: 'sara@habib.studio',
  role: 'admin',
  firm: 'f_habib',
  seat: 'editor',
  status: 'active',
  last: '4m',
  runs: 642
}, {
  id: 'u_jd',
  name: 'James Dornan',
  email: 'james@northline.com',
  role: 'admin',
  firm: 'f_north',
  seat: 'owner',
  status: 'active',
  last: '20m',
  runs: 911
}, {
  id: 'u_kp',
  name: 'Kavya Pillai',
  email: 'kavya@northline.com',
  role: 'member',
  firm: 'f_north',
  seat: 'editor',
  status: 'active',
  last: '1h',
  runs: 388
}, {
  id: 'u_fa',
  name: 'Faisal Otaibi',
  email: 'faisal@riyadhbim.sa',
  role: 'admin',
  firm: 'f_ksa',
  seat: 'owner',
  status: 'active',
  last: '3h',
  runs: 204
}, {
  id: 'u_cf',
  name: 'Claire Fournier',
  email: 'claire@fournier.fr',
  role: 'member',
  firm: 'f_solo',
  seat: 'owner',
  status: 'active',
  last: 'yesterday',
  runs: 156
}, {
  id: 'u_ap',
  name: 'Adam Price',
  email: 'adam@atlas-eng.uk',
  role: 'admin',
  firm: 'f_atlas',
  seat: 'owner',
  status: 'suspended',
  last: '2d',
  runs: 1502
}, {
  id: 'u_rw',
  name: 'Rachel Wong',
  email: 'rachel@atlas-eng.uk',
  role: 'member',
  firm: 'f_atlas',
  seat: 'editor',
  status: 'active',
  last: '5h',
  runs: 720
}, {
  id: 'u_dt',
  name: 'Diego Torres',
  email: 'diego@deltabuild.co',
  role: 'member',
  firm: 'f_delta',
  seat: 'viewer',
  status: 'invited',
  last: '—',
  runs: 0
}];
var SEED_BRAINS = [{
  id: 'br_founder',
  name: 'Founder Brain',
  scope: 'global',
  firm: '—',
  memories: 2841,
  layers: 4,
  tokens: 18420,
  sync: 'private-relay',
  owner: 'u_mh',
  sees: 'everything'
}, {
  id: 'br_habib',
  name: 'Habib · Firm Brain',
  scope: 'firm',
  firm: 'f_habib',
  memories: 412,
  layers: 4,
  tokens: 7210,
  sync: 'private-relay',
  owner: 'u_mh',
  sees: 'firm'
}, {
  id: 'br_north',
  name: 'Northline Brain',
  scope: 'firm',
  firm: 'f_north',
  memories: 388,
  layers: 4,
  tokens: 6840,
  sync: 'private-relay',
  owner: 'u_jd',
  sees: 'firm'
}, {
  id: 'br_ksa',
  name: 'Riyadh Brain',
  scope: 'firm',
  firm: 'f_ksa',
  memories: 96,
  layers: 3,
  tokens: 2010,
  sync: 'local-only',
  owner: 'u_fa',
  sees: 'firm'
}, {
  id: 'br_solo',
  name: 'Fournier Brain',
  scope: 'personal',
  firm: 'f_solo',
  memories: 41,
  layers: 2,
  tokens: 880,
  sync: 'local-only',
  owner: 'u_cf',
  sees: 'self'
}, {
  id: 'br_atlas',
  name: 'Atlas Brain',
  scope: 'firm',
  firm: 'f_atlas',
  memories: 503,
  layers: 4,
  tokens: 9120,
  sync: 'private-relay',
  owner: 'u_ap',
  sees: 'firm'
}];
var SEED_MODELS = [{
  id: 'm_sonnet',
  name: 'Claude Sonnet 4.5',
  vendor: 'Anthropic',
  ctx: '200k',
  inCost: 3.0,
  outCost: 15.0,
  latency: 420,
  status: 'primary',
  share: 58,
  tasks: ['intent', 'vision', 'compose']
}, {
  id: 'm_opus',
  name: 'Claude Opus 4.1',
  vendor: 'Anthropic',
  ctx: '200k',
  inCost: 15.0,
  outCost: 75.0,
  latency: 980,
  status: 'enabled',
  share: 6,
  tasks: ['critique']
}, {
  id: 'm_gpt5',
  name: 'GPT-5',
  vendor: 'OpenAI',
  ctx: '256k',
  inCost: 5.0,
  outCost: 20.0,
  latency: 510,
  status: 'enabled',
  share: 26,
  tasks: ['fallback', 'vision']
}, {
  id: 'm_gemini',
  name: 'Gemini 2.5 Pro',
  vendor: 'Google',
  ctx: '1M',
  inCost: 2.0,
  outCost: 8.0,
  latency: 380,
  status: 'enabled',
  share: 9,
  tasks: ['extract']
}, {
  id: 'm_qwen',
  name: 'qwen3:32b',
  vendor: 'Ollama',
  ctx: '32k',
  inCost: 0,
  outCost: 0,
  latency: 980,
  status: 'local',
  share: 1,
  tasks: ['offline']
}, {
  id: 'm_mistral',
  name: 'Mistral Large',
  vendor: 'Mistral',
  ctx: '128k',
  inCost: 2.0,
  outCost: 6.0,
  latency: 440,
  status: 'disabled',
  share: 0,
  tasks: []
}];
var SEED_SKILLS = [{
  id: 's_sketch',
  name: 'Sketch → Production',
  author: 'archhub',
  scope: 'official',
  installs: 12400,
  version: '2.1.0',
  stages: 6,
  hosts: ['vision', 'revit', 'speckle'],
  status: 'published'
}, {
  id: 's_dim',
  name: 'Dimension walls',
  author: 'archhub',
  scope: 'official',
  installs: 18200,
  version: '1.4.2',
  stages: 1,
  hosts: ['revit'],
  status: 'published'
}, {
  id: 's_doors',
  name: 'Doors & windows from plan',
  author: '@mhabib',
  scope: 'firm',
  installs: 89,
  version: '0.9.0',
  stages: 2,
  hosts: ['revit'],
  status: 'published'
}, {
  id: 's_boq',
  name: 'BOQ → Excel',
  author: '@studio_lk',
  scope: 'community',
  installs: 3100,
  version: '1.1.0',
  stages: 3,
  hosts: ['revit', 'excel'],
  status: 'review'
}, {
  id: 's_layer',
  name: 'AutoCAD layer cleanup',
  author: '@drafter',
  scope: 'community',
  installs: 8100,
  version: '2.0.1',
  stages: 1,
  hosts: ['autocad'],
  status: 'published'
}, {
  id: 's_curtain',
  name: 'Curtain wall optimizer',
  author: '@panel_co',
  scope: 'community',
  installs: 4000,
  version: '1.2.0',
  stages: 3,
  hosts: ['rhino', 'revit'],
  status: 'flagged'
}];
var SEED_CONNECTORS = [{
  id: 'c_revit',
  name: 'Revit 2025',
  port: 48884,
  sessions: 1240,
  status: 'healthy',
  uptime: 99.97,
  heals7d: 47,
  p50: 340
}, {
  id: 'c_rhino',
  name: 'Rhino 8',
  port: 48887,
  sessions: 612,
  status: 'healthy',
  uptime: 99.99,
  heals7d: 12,
  p50: 210
}, {
  id: 'c_acad',
  name: 'AutoCAD 2025',
  port: 48885,
  sessions: 880,
  status: 'healing',
  uptime: 99.71,
  heals7d: 64,
  p50: 520
}, {
  id: 'c_speckle',
  name: 'Speckle',
  port: null,
  sessions: 430,
  status: 'healthy',
  uptime: 99.95,
  heals7d: 3,
  p50: 180
}, {
  id: 'c_blender',
  name: 'Blender 4.2',
  port: 9876,
  sessions: 254,
  status: 'degraded',
  uptime: 98.40,
  heals7d: 31,
  p50: 740
}, {
  id: 'c_max',
  name: '3ds Max 2025',
  port: 48886,
  sessions: 96,
  status: 'idle',
  uptime: 99.20,
  heals7d: 8,
  p50: 410
}];
var SEED_ISSUES = [{
  id: 'i_481',
  level: 'error',
  title: "TypeError: cannot read 'port' of null",
  where: 'connector/speckle.rebind',
  count: 142,
  users: 18,
  last: '6m',
  status: 'open',
  assignee: null,
  release: 'v0.27.0'
}, {
  id: 'i_477',
  level: 'error',
  title: 'RPC heartbeat timeout (3 retries) — AutoCAD',
  where: 'heal/watchdog',
  count: 64,
  users: 9,
  last: '21m',
  status: 'investigating',
  assignee: 'ag_heal',
  release: 'v0.27.0'
}, {
  id: 'i_469',
  level: 'warn',
  title: 'Skill JSON schema drift on import',
  where: 'brain/skill.parse',
  count: 38,
  users: 12,
  last: '1h',
  status: 'open',
  assignee: null,
  release: 'v0.26.4'
}, {
  id: 'i_462',
  level: 'error',
  title: 'OOM during 1M-token Gemini vision pass',
  where: 'model/router',
  count: 11,
  users: 3,
  last: '3h',
  status: 'open',
  assignee: 'ag_router',
  release: 'v0.27.0'
}, {
  id: 'i_455',
  level: 'info',
  title: 'Slow plot: sheet set > 80 sheets',
  where: 'compose/plot',
  count: 27,
  users: 7,
  last: '5h',
  status: 'triaged',
  assignee: null,
  release: 'v0.26.4'
}, {
  id: 'i_440',
  level: 'warn',
  title: 'Private relay cert rotation reminder',
  where: 'sync/relay',
  count: 6,
  users: 6,
  last: '1d',
  status: 'resolved',
  assignee: 'ag_ops',
  release: 'v0.26.3'
}];
var SEED_ROADMAP = [
// lane: now | next | later | shipped
{
  id: 'r_uikit',
  lane: 'now',
  type: 'feature',
  title: 'Drag-drop UI builder GA',
  goal: 'Let firms theme ArchHub without code',
  effort: 'L',
  owner: 'ag_ui',
  votes: 34,
  progress: 60
}, {
  id: 'r_relay',
  lane: 'now',
  type: 'infra',
  title: 'Private relay for Brain sync',
  goal: 'Brain never touches GitHub',
  effort: 'M',
  owner: 'ag_ops',
  votes: 51,
  progress: 80
}, {
  id: 'r_heal2',
  lane: 'next',
  type: 'feature',
  title: 'Self-heal v2 — predictive',
  goal: 'Reconnect before the drop',
  effort: 'L',
  owner: 'ag_heal',
  votes: 42,
  progress: 15
}, {
  id: 'r_market',
  lane: 'next',
  type: 'growth',
  title: 'Skill marketplace payouts',
  goal: 'Pay community skill authors',
  effort: 'M',
  owner: 'ag_growth',
  votes: 28,
  progress: 5
}, {
  id: 'r_mobile',
  lane: 'later',
  type: 'feature',
  title: 'Mobile companion · review on site',
  goal: 'Approve the line from the field',
  effort: 'L',
  owner: null,
  votes: 19,
  progress: 0
}, {
  id: 'r_sso',
  lane: 'later',
  type: 'infra',
  title: 'Enterprise SSO + audit log',
  goal: 'Unlock large firms',
  effort: 'M',
  owner: null,
  votes: 23,
  progress: 0
}, {
  id: 'r_dim',
  lane: 'shipped',
  type: 'feature',
  title: 'Auto-dimension active view',
  goal: 'Ship CD faster',
  effort: 'S',
  owner: 'ag_compose',
  votes: 67,
  progress: 100
}];
var SEED_AGENTS = [{
  id: 'ag_ui',
  name: 'UI-Builder Agent',
  model: 'm_sonnet',
  task: 'Wire drag-drop builder to live theme tokens',
  status: 'working',
  brain: 'br_founder',
  autonomy: 'propose',
  queue: 3
}, {
  id: 'ag_ops',
  name: 'Ops Agent',
  model: 'm_sonnet',
  task: 'Rotate private-relay certs, watch fleet',
  status: 'working',
  brain: 'br_founder',
  autonomy: 'act',
  queue: 1
}, {
  id: 'ag_heal',
  name: 'Self-Heal Agent',
  model: 'm_gemini',
  task: 'Triage AutoCAD heartbeat timeouts',
  status: 'working',
  brain: 'br_founder',
  autonomy: 'act',
  queue: 5
}, {
  id: 'ag_router',
  name: 'Model-Router Agent',
  model: 'm_qwen',
  task: 'Pick cheapest model per task within SLA',
  status: 'idle',
  brain: 'br_founder',
  autonomy: 'act',
  queue: 0
}, {
  id: 'ag_growth',
  name: 'Growth Agent',
  model: 'm_gpt5',
  task: 'Draft marketplace payout spec',
  status: 'paused',
  brain: 'br_founder',
  autonomy: 'propose',
  queue: 2
}, {
  id: 'ag_compose',
  name: 'Compose Agent',
  model: 'm_sonnet',
  task: 'Idle — last shipped auto-dimension',
  status: 'idle',
  brain: 'br_founder',
  autonomy: 'propose',
  queue: 0
}];

// Live org activity — "see and know what everyone is doing". Streamed in Pulse.
var SEED_ACTIVITY = [{
  id: uid('ev'),
  who: 'u_sa',
  verb: 'ran skill',
  what: 'Dimension walls · Tower-A',
  firm: 'f_habib',
  t: 2
}, {
  id: uid('ev'),
  who: 'u_jd',
  verb: 'edited brain',
  what: 'added detail-library standard',
  firm: 'f_north',
  t: 14
}, {
  id: uid('ev'),
  who: 'ag_heal',
  verb: 'healed',
  what: 'AutoCAD session #2841 · 38ms',
  firm: 'f_ksa',
  t: 22
}, {
  id: uid('ev'),
  who: 'u_fa',
  verb: 'wired host',
  what: 'Speckle → riyadh-bim/main',
  firm: 'f_ksa',
  t: 48
}, {
  id: uid('ev'),
  who: 'u_rw',
  verb: 'published skill',
  what: 'Curtain wall v1.2',
  firm: 'f_atlas',
  t: 90
}];
var SEED_METRICS = {
  mrr: 5644,
  mrrPrev: 5102,
  arr: 67728,
  users: 9,
  usersPrev: 8,
  firms: 6,
  churn: 1.8,
  churnPrev: 2.4,
  netNew: 542,
  modelSpend: 47.82,
  modelBudget: 200,
  mrrSeries: [3980, 4210, 4380, 4520, 4690, 4880, 5102, 5240, 5390, 5470, 5560, 5644],
  usersSeries: [4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9],
  spendSeries: [3.2, 5.1, 4.8, 8.9, 6.1, 11.4, 8.3, 9.1, 7.2, 10.4, 6.9, 8.0]
};
var SEED_FLAGS = [{
  id: 'fl_builder',
  name: 'ui_builder',
  desc: 'Drag-drop UI builder',
  stage: 'beta',
  rollout: 25,
  on: true
}, {
  id: 'fl_heal2',
  name: 'predictive_heal',
  desc: 'Self-heal v2 predictive reconnect',
  stage: 'internal',
  rollout: 5,
  on: true
}, {
  id: 'fl_payouts',
  name: 'marketplace_payouts',
  desc: 'Pay skill authors',
  stage: 'off',
  rollout: 0,
  on: false
}, {
  id: 'fl_mobile',
  name: 'mobile_review',
  desc: 'Mobile companion review',
  stage: 'off',
  rollout: 0,
  on: false
}, {
  id: 'fl_relay',
  name: 'private_relay',
  desc: 'Brain sync via private relay (no GitHub)',
  stage: 'ga',
  rollout: 100,
  on: true
}];
var SEED_DB = function SEED_DB() {
  return {
    firms: SEED_FIRMS,
    users: SEED_USERS,
    brains: SEED_BRAINS,
    models: SEED_MODELS,
    skills: SEED_SKILLS,
    connectors: SEED_CONNECTORS,
    issues: SEED_ISSUES,
    roadmap: SEED_ROADMAP,
    agents: SEED_AGENTS,
    activity: SEED_ACTIVITY,
    metrics: SEED_METRICS,
    flags: SEED_FLAGS,
    beat: 1 // founder-controlled simulation tempo
  };
};

/* ════════════════ status colour map ════════════════ */
var STAT = {
  green: CK.ok,
  amber: CK.warn,
  red: CK.err,
  healthy: CK.ok,
  healing: CK.warn,
  degraded: CK.err,
  idle: CK.inkMuted,
  active: CK.ok,
  suspended: CK.err,
  invited: CK.warn,
  working: CK.ok,
  paused: CK.warn,
  error: CK.err,
  warn: CK.warn,
  info: CK.cyan,
  open: CK.err,
  investigating: CK.warn,
  triaged: CK.cyan,
  resolved: CK.ok,
  primary: CK.accent,
  enabled: CK.ok,
  local: CK.cyan,
  disabled: CK.inkMuted,
  published: CK.ok,
  flagged: CK.err,
  review: CK.warn,
  now: CK.accent,
  next: CK.cyan,
  later: CK.purple,
  shipped: CK.ok,
  ga: CK.ok,
  beta: CK.cyan,
  internal: CK.purple,
  off: CK.inkMuted
};
var sc = function sc(k) {
  return STAT[k] || CK.inkMuted;
};

/* ════════════════ ICONS (inline, no deps) ════════════════ */
var CKIcon = function CKIcon(_ref) {
  var name = _ref.name,
    _ref$size = _ref.size,
    size = _ref$size === void 0 ? 16 : _ref$size,
    _ref$color = _ref.color,
    color = _ref$color === void 0 ? 'currentColor' : _ref$color,
    _ref$sw = _ref.sw,
    sw = _ref$sw === void 0 ? 1.6 : _ref$sw;
  var p = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: color,
    strokeWidth: sw,
    strokeLinecap: 'round',
    strokeLinejoin: 'round'
  };
  switch (name) {
    case 'pulse':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("path", {
        d: "M3 12h4l2-6 4 12 2-6h6"
      }));
    case 'db':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("ellipse", {
        cx: "12",
        cy: "5",
        rx: "8",
        ry: "3"
      }), /*#__PURE__*/React.createElement("path", {
        d: "M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"
      }));
    case 'agent':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("rect", {
        x: "4",
        y: "8",
        width: "16",
        height: "11",
        rx: "2"
      }), /*#__PURE__*/React.createElement("path", {
        d: "M12 4v4M9 14h.01M15 14h.01M2 13v3M22 13v3"
      }));
    case 'map':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("path", {
        d: "m9 4 6 2 5-2v15l-5 2-6-2-5 2V4l5-2Z"
      }), /*#__PURE__*/React.createElement("path", {
        d: "M9 2v18M15 4v18"
      }));
    case 'bug':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("rect", {
        x: "8",
        y: "6",
        width: "8",
        height: "13",
        rx: "4"
      }), /*#__PURE__*/React.createElement("path", {
        d: "M8 10H3M21 10h-5M8 14H4M20 14h-4M9 6 7 3M15 6l2-3"
      }));
    case 'layout':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("rect", {
        x: "3",
        y: "3",
        width: "18",
        height: "18",
        rx: "2"
      }), /*#__PURE__*/React.createElement("path", {
        d: "M3 9h18M9 21V9"
      }));
    case 'model':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("circle", {
        cx: "12",
        cy: "12",
        r: "3"
      }), /*#__PURE__*/React.createElement("path", {
        d: "M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"
      }));
    case 'brain':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("path", {
        d: "M9 3a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 1 5 3 3 0 0 0 6 1V4a3 3 0 0 0-2-1ZM15 3a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-1 5 3 3 0 0 1-6 1"
      }));
    case 'flag':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("path", {
        d: "M4 21V4M4 4h13l-2 4 2 4H4"
      }));
    case 'search':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("circle", {
        cx: "11",
        cy: "11",
        r: "7"
      }), /*#__PURE__*/React.createElement("path", {
        d: "m20 20-3.5-3.5"
      }));
    case 'plus':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("path", {
        d: "M12 5v14M5 12h14"
      }));
    case 'x':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("path", {
        d: "m6 6 12 12M18 6 6 18"
      }));
    case 'trash':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("path", {
        d: "M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"
      }));
    case 'edit':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("path", {
        d: "M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5Z"
      }));
    case 'check':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("path", {
        d: "m4 12 5 5L20 6"
      }));
    case 'play':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("path", {
        d: "M6 4v16l14-8L6 4Z"
      }));
    case 'pause':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("path", {
        d: "M7 4v16M17 4v16"
      }));
    case 'bolt':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("path", {
        d: "M13 2 4 14h7l-1 8 9-12h-7l1-8Z"
      }));
    case 'arrowUp':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("path", {
        d: "M12 19V5M5 12l7-7 7 7"
      }));
    case 'arrowDn':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("path", {
        d: "M12 5v14M19 12l-7 7-7-7"
      }));
    case 'dot':
      return /*#__PURE__*/React.createElement("svg", {
        viewBox: "0 0 8 8",
        width: size,
        height: size
      }, /*#__PURE__*/React.createElement("circle", {
        cx: "4",
        cy: "4",
        r: "3",
        fill: color
      }));
    case 'eye':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("path", {
        d: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"
      }), /*#__PURE__*/React.createElement("circle", {
        cx: "12",
        cy: "12",
        r: "3"
      }));
    case 'grid':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("rect", {
        x: "3",
        y: "3",
        width: "7",
        height: "7",
        rx: "1"
      }), /*#__PURE__*/React.createElement("rect", {
        x: "14",
        y: "3",
        width: "7",
        height: "7",
        rx: "1"
      }), /*#__PURE__*/React.createElement("rect", {
        x: "3",
        y: "14",
        width: "7",
        height: "7",
        rx: "1"
      }), /*#__PURE__*/React.createElement("rect", {
        x: "14",
        y: "14",
        width: "7",
        height: "7",
        rx: "1"
      }));
    case 'gear':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("circle", {
        cx: "12",
        cy: "12",
        r: "3"
      }), /*#__PURE__*/React.createElement("path", {
        d: "M19.4 15a1.7 1.7 0 0 0 .3 1.8M4.6 9a1.7 1.7 0 0 0-.3-1.8m0 9.6A1.7 1.7 0 0 0 4.6 15M19.4 9a1.7 1.7 0 0 1 .3-1.8M12 2v3M12 19v3M2 12h3M19 12h3"
      }));
    case 'logout':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("path", {
        d: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"
      }));
    case 'drag':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("circle", {
        cx: "9",
        cy: "6",
        r: "1"
      }), /*#__PURE__*/React.createElement("circle", {
        cx: "9",
        cy: "12",
        r: "1"
      }), /*#__PURE__*/React.createElement("circle", {
        cx: "9",
        cy: "18",
        r: "1"
      }), /*#__PURE__*/React.createElement("circle", {
        cx: "15",
        cy: "6",
        r: "1"
      }), /*#__PURE__*/React.createElement("circle", {
        cx: "15",
        cy: "12",
        r: "1"
      }), /*#__PURE__*/React.createElement("circle", {
        cx: "15",
        cy: "18",
        r: "1"
      }));
    case 'link':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("path", {
        d: "M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"
      }));
    case 'lock':
      return /*#__PURE__*/React.createElement("svg", p, /*#__PURE__*/React.createElement("rect", {
        x: "5",
        y: "11",
        width: "14",
        height: "10",
        rx: "2"
      }), /*#__PURE__*/React.createElement("path", {
        d: "M8 11V7a4 4 0 0 1 8 0v4"
      }));
    default:
      return null;
  }
};

/* ════════════════ ATOMS ════════════════ */
var Btn = function Btn(_ref2) {
  var children = _ref2.children,
    onClick = _ref2.onClick,
    primary = _ref2.primary,
    danger = _ref2.danger,
    ghost = _ref2.ghost,
    small = _ref2.small,
    disabled = _ref2.disabled,
    style = _ref2.style,
    title = _ref2.title;
  return /*#__PURE__*/React.createElement("button", {
    title: title,
    onClick: onClick,
    disabled: disabled,
    style: _objectSpread({
      fontFamily: CK.sans,
      fontSize: small ? 11.5 : 12.5,
      fontWeight: 500,
      padding: small ? '4px 9px' : '7px 13px',
      borderRadius: CK.rad.md,
      border: "1px solid ".concat(primary ? CK.accent : danger ? CK.err + '66' : CK.line),
      background: primary ? CK.accent : ghost ? 'transparent' : CK.bgSoft,
      color: primary ? '#160d08' : danger ? CK.err : CK.ink,
      cursor: disabled ? 'not-allowed' : 'pointer',
      opacity: disabled ? 0.5 : 1,
      display: 'inline-flex',
      alignItems: 'center',
      gap: 6,
      whiteSpace: 'nowrap',
      transition: 'all .14s'
    }, style),
    onMouseEnter: function onMouseEnter(e) {
      if (!disabled && !primary) e.currentTarget.style.borderColor = CK.inkMuted;
    },
    onMouseLeave: function onMouseLeave(e) {
      if (!disabled && !primary) e.currentTarget.style.borderColor = danger ? CK.err + '66' : CK.line;
    }
  }, children);
};
var IconBtn = function IconBtn(_ref3) {
  var name = _ref3.name,
    onClick = _ref3.onClick,
    color = _ref3.color,
    title = _ref3.title,
    active = _ref3.active,
    _ref3$size = _ref3.size,
    size = _ref3$size === void 0 ? 14 : _ref3$size;
  return /*#__PURE__*/React.createElement("button", {
    title: title,
    onClick: onClick,
    style: {
      width: 28,
      height: 28,
      display: 'grid',
      placeItems: 'center',
      borderRadius: CK.rad.sm,
      border: "1px solid ".concat(active ? CK.accent : 'transparent'),
      background: active ? CK.accentSoft : 'transparent',
      color: color || CK.inkSoft,
      cursor: 'pointer',
      transition: 'all .14s'
    },
    onMouseEnter: function onMouseEnter(e) {
      e.currentTarget.style.background = CK.bgHover;
    },
    onMouseLeave: function onMouseLeave(e) {
      e.currentTarget.style.background = active ? CK.accentSoft : 'transparent';
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: name,
    size: size
  }));
};
var Pill = function Pill(_ref4) {
  var children = _ref4.children,
    k = _ref4.k,
    color = _ref4.color;
  var c = color || sc(k);
  return /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: CK.mono,
      fontSize: 9.5,
      letterSpacing: '0.08em',
      textTransform: 'uppercase',
      color: c,
      background: c + '1a',
      border: "1px solid ".concat(c, "33"),
      padding: '2px 7px',
      borderRadius: 4,
      display: 'inline-flex',
      alignItems: 'center',
      gap: 4,
      whiteSpace: 'nowrap'
    }
  }, children);
};
var Dot = function Dot(_ref5) {
  var k = _ref5.k,
    color = _ref5.color,
    pulse = _ref5.pulse;
  var c = color || sc(k);
  return /*#__PURE__*/React.createElement("span", {
    style: {
      width: 7,
      height: 7,
      borderRadius: '50%',
      background: c,
      flexShrink: 0,
      boxShadow: "0 0 0 0 ".concat(c),
      animation: pulse ? 'ckPulse 1.8s infinite' : 'none'
    }
  });
};
var Avatar = function Avatar(_ref6) {
  var name = _ref6.name,
    _ref6$size = _ref6.size,
    size = _ref6$size === void 0 ? 24 : _ref6$size,
    ring = _ref6.ring;
  var initials = (name || '?').split(' ').map(function (w) {
    return w[0];
  }).slice(0, 2).join('').toUpperCase();
  var hues = ['#d97757', '#5fb3b3', '#a98cd6', '#7ec18e', '#e5b25a', '#7898d6'];
  var h = hues[(name || '').length % hues.length];
  return /*#__PURE__*/React.createElement("span", {
    style: {
      width: size,
      height: size,
      borderRadius: '50%',
      background: h + '22',
      color: h,
      border: "1px solid ".concat(h, "55"),
      display: 'grid',
      placeItems: 'center',
      flexShrink: 0,
      fontFamily: CK.mono,
      fontSize: size * 0.36,
      fontWeight: 600,
      boxShadow: ring ? "0 0 0 2px ".concat(CK.bg) : 'none'
    }
  }, initials);
};
var Field = function Field(_ref7) {
  var label = _ref7.label,
    value = _ref7.value,
    _onChange = _ref7.onChange,
    placeholder = _ref7.placeholder,
    _ref7$type = _ref7.type,
    type = _ref7$type === void 0 ? 'text' : _ref7$type,
    full = _ref7.full,
    mono = _ref7.mono,
    style = _ref7.style;
  return /*#__PURE__*/React.createElement("label", {
    style: _objectSpread({
      display: 'flex',
      flexDirection: 'column',
      gap: 5,
      flex: full ? 1 : 'none'
    }, style)
  }, label && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: CK.mono,
      fontSize: 9.5,
      color: CK.inkMuted,
      letterSpacing: '0.1em',
      textTransform: 'uppercase'
    }
  }, label), /*#__PURE__*/React.createElement("input", {
    value: value !== null && value !== void 0 ? value : '',
    type: type,
    onChange: function onChange(e) {
      return _onChange && _onChange(e.target.value);
    },
    placeholder: placeholder,
    style: {
      padding: '7px 10px',
      borderRadius: CK.rad.sm,
      border: "1px solid ".concat(CK.line),
      background: CK.bgDeep,
      color: CK.ink,
      fontSize: 13,
      fontFamily: mono ? CK.mono : CK.sans,
      outline: 'none',
      width: full ? '100%' : 'auto'
    },
    onFocus: function onFocus(e) {
      return e.target.style.borderColor = CK.accent;
    },
    onBlur: function onBlur(e) {
      return e.target.style.borderColor = CK.line;
    }
  }));
};
var Select = function Select(_ref8) {
  var label = _ref8.label,
    value = _ref8.value,
    _onChange2 = _ref8.onChange,
    options = _ref8.options,
    full = _ref8.full;
  return /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 5,
      flex: full ? 1 : 'none'
    }
  }, label && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: CK.mono,
      fontSize: 9.5,
      color: CK.inkMuted,
      letterSpacing: '0.1em',
      textTransform: 'uppercase'
    }
  }, label), /*#__PURE__*/React.createElement("select", {
    value: value,
    onChange: function onChange(e) {
      return _onChange2 && _onChange2(e.target.value);
    },
    style: {
      padding: '7px 10px',
      borderRadius: CK.rad.sm,
      border: "1px solid ".concat(CK.line),
      background: CK.bgDeep,
      color: CK.ink,
      fontSize: 13,
      fontFamily: CK.sans,
      outline: 'none',
      cursor: 'pointer',
      width: full ? '100%' : 'auto'
    }
  }, options.map(function (o) {
    var _ref9 = Array.isArray(o) ? o : [o, o],
      _ref0 = _slicedToArray(_ref9, 2),
      v = _ref0[0],
      l = _ref0[1];
    return /*#__PURE__*/React.createElement("option", {
      key: v,
      value: v,
      style: {
        background: CK.bgPanel
      }
    }, l);
  })));
};
var Toggle = function Toggle(_ref1) {
  var value = _ref1.value,
    onChange = _ref1.onChange;
  return /*#__PURE__*/React.createElement("button", {
    onClick: function onClick() {
      return onChange && onChange(!value);
    },
    style: {
      width: 36,
      height: 21,
      borderRadius: 999,
      border: 'none',
      padding: 2,
      flexShrink: 0,
      background: value ? CK.accent : CK.bgHover,
      cursor: 'pointer',
      position: 'relative',
      transition: 'background .15s'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      position: 'absolute',
      top: 2,
      left: value ? 17 : 2,
      width: 17,
      height: 17,
      borderRadius: '50%',
      background: '#fff',
      transition: 'left .15s',
      boxShadow: '0 1px 2px rgba(0,0,0,.3)'
    }
  }));
};
var Modal = function Modal(_ref10) {
  var title = _ref10.title,
    sub = _ref10.sub,
    onClose = _ref10.onClose,
    children = _ref10.children,
    _ref10$w = _ref10.w,
    w = _ref10$w === void 0 ? 460 : _ref10$w;
  return /*#__PURE__*/React.createElement("div", {
    onClick: onClose,
    style: {
      position: 'fixed',
      inset: 0,
      zIndex: 100,
      background: 'rgba(8,8,11,0.72)',
      backdropFilter: 'blur(3px)',
      display: 'grid',
      placeItems: 'center',
      padding: 24,
      animation: 'ckFade .15s'
    }
  }, /*#__PURE__*/React.createElement("div", {
    onClick: function onClick(e) {
      return e.stopPropagation();
    },
    style: {
      width: w,
      maxWidth: '100%',
      maxHeight: '88vh',
      overflow: 'auto',
      background: CK.bgPanel,
      border: "1px solid ".concat(CK.line),
      borderRadius: CK.rad.xl,
      boxShadow: '0 40px 120px rgba(0,0,0,.6)',
      animation: 'ckPop .2s'
    },
    className: "ck-scroll"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'flex-start',
      justifyContent: 'space-between',
      gap: 12,
      padding: '16px 18px',
      borderBottom: "1px solid ".concat(CK.line)
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: CK.serif,
      fontSize: 22,
      letterSpacing: '-0.02em'
    }
  }, title), sub && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: CK.mono,
      fontSize: 10.5,
      color: CK.inkMuted,
      marginTop: 2,
      letterSpacing: '0.04em'
    }
  }, sub)), /*#__PURE__*/React.createElement(IconBtn, {
    name: "x",
    onClick: onClose
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 18
    }
  }, children)));
};

// section header inside a surface — dense, mission-control, mono kicker + rule
var SecHead = function SecHead(_ref11) {
  var icon = _ref11.icon,
    title = _ref11.title,
    sub = _ref11.sub,
    right = _ref11.right;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: 16,
      borderBottom: "1px solid ".concat(CK.line),
      paddingBottom: 13
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'flex-end',
      justifyContent: 'space-between',
      gap: 16
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'stretch',
      gap: 13
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 3,
      background: CK.accent,
      borderRadius: 2,
      flexShrink: 0
    }
  }), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 7,
      fontFamily: CK.mono,
      fontSize: 9.5,
      color: CK.accent,
      letterSpacing: '0.24em',
      textTransform: 'uppercase',
      marginBottom: 6
    }
  }, icon && /*#__PURE__*/React.createElement(CKIcon, {
    name: icon,
    size: 12
  }), /*#__PURE__*/React.createElement("span", null, "cockpit \xB7 ", title)), /*#__PURE__*/React.createElement("h2", {
    style: {
      fontFamily: CK.serif,
      fontSize: 36,
      fontWeight: 400,
      letterSpacing: '-0.03em',
      margin: 0,
      lineHeight: 0.92
    }
  }, title), sub && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: CK.mono,
      fontSize: 11,
      color: CK.inkSoft,
      letterSpacing: '0.02em',
      marginTop: 8
    }
  }, sub))), right));
};

// sparkline
var Spark = function Spark(_ref12) {
  var data = _ref12.data,
    _ref12$w = _ref12.w,
    w = _ref12$w === void 0 ? 120 : _ref12$w,
    _ref12$h = _ref12.h,
    h = _ref12$h === void 0 ? 32 : _ref12$h,
    _ref12$color = _ref12.color,
    color = _ref12$color === void 0 ? CK.accent : _ref12$color,
    _ref12$fill = _ref12.fill,
    fill = _ref12$fill === void 0 ? true : _ref12$fill;
  if (!data || !data.length) return null;
  var mn = Math.min.apply(Math, _toConsumableArray(data)),
    mx = Math.max.apply(Math, _toConsumableArray(data)),
    rng = mx - mn || 1;
  var pts = data.map(function (v, i) {
    return [i / (data.length - 1) * w, h - (v - mn) / rng * (h - 4) - 2];
  });
  var d = pts.map(function (p, i) {
    return (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1);
  }).join(' ');
  return /*#__PURE__*/React.createElement("svg", {
    width: w,
    height: h,
    style: {
      display: 'block',
      overflow: 'visible'
    }
  }, fill && /*#__PURE__*/React.createElement("path", {
    d: "".concat(d, " L ").concat(w, " ").concat(h, " L 0 ").concat(h, " Z"),
    fill: color,
    opacity: "0.1"
  }), /*#__PURE__*/React.createElement("path", {
    d: d,
    fill: "none",
    stroke: color,
    strokeWidth: "1.6"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: pts[pts.length - 1][0],
    cy: pts[pts.length - 1][1],
    r: "2.4",
    fill: color
  }));
};

// big metric stat card — terminal-framed readout
var StatCard = function StatCard(_ref13) {
  var label = _ref13.label,
    value = _ref13.value,
    unit = _ref13.unit,
    delta = _ref13.delta,
    deltaGood = _ref13.deltaGood,
    spark = _ref13.spark,
    sparkColor = _ref13.sparkColor,
    foot = _ref13.foot;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      background: CK.bgPanel,
      border: "1px solid ".concat(CK.line),
      borderRadius: CK.rad.lg,
      padding: '14px 16px',
      display: 'flex',
      flexDirection: 'column',
      gap: 9,
      minWidth: 0,
      position: 'relative',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      position: 'absolute',
      top: 0,
      left: 0,
      right: 0,
      height: 2,
      background: "linear-gradient(90deg, ".concat(sparkColor || CK.accent, ", transparent 70%)")
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: CK.mono,
      fontSize: 9.5,
      color: CK.inkSoft,
      letterSpacing: '0.16em',
      textTransform: 'uppercase'
    }
  }, label), delta != null && /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 2,
      fontFamily: CK.mono,
      fontSize: 10.5,
      fontWeight: 600,
      color: deltaGood ? CK.ok : CK.err
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: deltaGood ? 'arrowUp' : 'arrowDn',
    size: 11
  }), delta)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'baseline',
      gap: 5
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: CK.serif,
      fontSize: 46,
      letterSpacing: '-0.035em',
      lineHeight: 0.85,
      color: CK.ink,
      fontVariantNumeric: 'tabular-nums'
    }
  }, value), unit && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: CK.mono,
      fontSize: 12,
      color: CK.inkMuted
    }
  }, unit)), spark && /*#__PURE__*/React.createElement(Spark, {
    data: spark,
    w: 200,
    h: 28,
    color: sparkColor || CK.accent
  }), foot && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: CK.mono,
      fontSize: 10,
      color: CK.inkMuted,
      letterSpacing: '0.04em',
      borderTop: "1px solid ".concat(CK.lineSoft),
      paddingTop: 7
    }
  }, foot));
};

// keyframes + scrollbar (once)
if (typeof document !== 'undefined' && !document.getElementById('ck-anim')) {
  var s = document.createElement('style');
  s.id = 'ck-anim';
  s.textContent = "\n    @keyframes ckPulse{0%{box-shadow:0 0 0 0 currentColor}70%{box-shadow:0 0 0 5px transparent}100%{box-shadow:0 0 0 0 transparent}}\n    @keyframes ckFade{from{opacity:0}to{opacity:1}}\n    @keyframes ckPop{from{opacity:0;transform:scale(.97) translateY(6px)}to{opacity:1;transform:none}}\n    @keyframes ckSlide{from{opacity:0;transform:translateY(-5px)}to{opacity:1;transform:none}}\n    .ck-scroll::-webkit-scrollbar{width:8px;height:8px}\n    .ck-scroll::-webkit-scrollbar-thumb{background:#2c2c34;border-radius:4px}\n    .ck-scroll::-webkit-scrollbar-track{background:transparent}\n    .ck-row:hover{background:".concat(CK.bgSoft, "!important}\n  ");
  document.head.appendChild(s);
}
Object.assign(window, {
  CK: CK,
  CKLS: CKLS,
  ckLoad: ckLoad,
  ckSave: ckSave,
  uid: uid,
  SEED_DB: SEED_DB,
  sc: sc,
  STAT: STAT,
  CKIcon: CKIcon,
  Btn: Btn,
  IconBtn: IconBtn,
  Pill: Pill,
  Dot: Dot,
  Avatar: Avatar,
  Field: Field,
  Select: Select,
  Toggle: Toggle,
  Modal: Modal,
  SecHead: SecHead,
  Spark: Spark,
  StatCard: StatCard
});
