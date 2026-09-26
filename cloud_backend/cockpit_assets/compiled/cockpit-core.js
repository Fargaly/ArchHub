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
// cockpit-core.jsx — ARCHHUB FOUNDER COCKPIT · operate mode.
// NOT god mode (ADGR-0003): the cockpit is the founder's own personal brain plus operator
// permissions over the platform. It never reads inside another brain; per office it sees a size in MB.
// Persistence and UI atoms. No seed databases: the cockpit draws what the running
// application pushes, and absent data is drawn as absent.
// Derives 100% of its palette from window.AH (tokens.jsx) — no hardcoded hexes.
// The control surface is editable at runtime; what it SHOWS comes from the app.

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

/* ════════════════ the cockpit's collections ════════════════ */
// No seed databases. Every collection starts empty and is filled by what the
// founder's running application pushes, so a collection nobody has filled draws
// as absent instead of as invented firms, users or revenue (audit 2026-09-07).
// ADGR-0003: an operator reads a size per office, never memories, tokens or
// contents, and no brain is "global" or "sees everything".
var EMPTY_DB = function EMPTY_DB() {
  return {
    firms: [],
    users: [],
    brains: [],
    models: [],
    skills: [],
    connectors: [],
    issues: [],
    roadmap: [],
    agents: [],
    activity: [],
    metrics: null,
    flags: [],
    beat: 1 // founder-controlled tempo
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
  EMPTY_DB: EMPTY_DB,
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
