function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }
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
// hub-kit.jsx — the cockpit's design foundation. Derives 100% from window.AH (tokens.jsx)
// so the cockpit IS the application, not a parallel product: same dark ground, same
// terracotta, same ink ramp, same radii, same type. Key NAMES are kept from the old
// light kit (paper / card / inkMute …) so every call site keeps working — only the
// values now point at the canonical dark set.

var AHX = window.AH;
var HB = {
  // surfaces — mirrors Studio: canvas = bg, panels/rails = bgPanel, raised = bgSoft
  paper: AHX.bg,
  // app ground / map canvas
  paper2: AHX.bgSoft,
  // raised rows, wells
  card: AHX.bgPanel,
  // rails, masthead, cards
  cardHi: AHX.bgRaised,
  // hovered / elevated card
  ink: AHX.ink,
  inkSoft: AHX.inkSoft,
  inkMute: AHX.inkMuted,
  // text-safe at the source (tokens.jsx)
  inkDim: AHX.inkDim,
  line: AHX.line,
  lineSoft: AHX.lineSoft,
  // accents — the real brand terracotta, not a light-bg substitute
  accent: AHX.accent,
  accentHi: AHX.accentHi,
  accentSoft: AHX.accentSoft,
  blue: AHX.blue,
  blueSoft: '#1b2233',
  green: AHX.ok,
  amber: AHX.warn,
  red: AHX.err,
  purple: AHX.purple,
  // fonts + radii straight from the app
  serif: AHX.serif,
  sans: AHX.sans,
  mono: AHX.mono,
  arch: AHX.arch,
  rad: AHX.rad
};
var HSTAT = {
  green: HB.green,
  amber: HB.amber,
  red: HB.red,
  healthy: HB.green,
  healing: HB.amber,
  degraded: HB.red,
  idle: HB.inkMute,
  active: HB.green,
  suspended: HB.red,
  invited: HB.amber,
  working: HB.green,
  paused: HB.amber,
  error: HB.red,
  warn: HB.amber,
  info: HB.blue,
  open: HB.red,
  investigating: HB.amber,
  triaged: HB.blue,
  resolved: HB.green,
  primary: HB.accent,
  enabled: HB.green,
  local: HB.blue,
  disabled: HB.inkMute,
  confirmed: HB.green,
  learned: HB.amber,
  proposed: HB.blue,
  founder: HB.accent,
  firm: HB.purple,
  project: HB.blue,
  personal: HB.green,
  system: HB.inkMute,
  now: HB.accent,
  next: HB.blue,
  later: HB.purple,
  shipped: HB.green,
  ga: HB.green,
  beta: HB.blue,
  internal: HB.purple,
  off: HB.inkMute
};
var hsc = function hsc(k) {
  return HSTAT[k] || HB.inkMute;
};

/* ── atoms ── */
var HBtn = function HBtn(_ref) {
  var children = _ref.children,
    onClick = _ref.onClick,
    primary = _ref.primary,
    ghost = _ref.ghost,
    danger = _ref.danger,
    small = _ref.small,
    disabled = _ref.disabled,
    title = _ref.title,
    style = _ref.style;
  return /*#__PURE__*/React.createElement("button", {
    title: title,
    onClick: onClick,
    disabled: disabled,
    style: _objectSpread({
      fontFamily: HB.sans,
      fontSize: small ? 12 : 13,
      fontWeight: 500,
      letterSpacing: '0.01em',
      padding: small ? '6px 12px' : '9px 16px',
      borderRadius: HB.rad.md,
      cursor: disabled ? 'not-allowed' : 'pointer',
      border: "1px solid ".concat(primary ? HB.accent : danger ? HB.red + '66' : HB.line),
      background: primary ? HB.accent : ghost ? 'transparent' : HB.cardHi,
      color: primary ? window.AH && window.AH.onFill || '#180f08' : danger ? HB.red : HB.ink,
      opacity: disabled ? 0.5 : 1,
      display: 'inline-flex',
      alignItems: 'center',
      gap: 7,
      whiteSpace: 'nowrap',
      transition: 'all .15s',
      boxShadow: 'none'
    }, style),
    onMouseEnter: function onMouseEnter(e) {
      if (!disabled) {
        e.currentTarget.style.transform = 'translateY(-1px)';
        if (!primary && !ghost) e.currentTarget.style.borderColor = HB.inkMute;
      }
    },
    onMouseLeave: function onMouseLeave(e) {
      e.currentTarget.style.transform = 'none';
      if (!primary && !ghost) e.currentTarget.style.borderColor = danger ? HB.red + '66' : HB.line;
    }
  }, children);
};
var HIconBtn = function HIconBtn(_ref2) {
  var name = _ref2.name,
    onClick = _ref2.onClick,
    title = _ref2.title,
    active = _ref2.active,
    _ref2$size = _ref2.size,
    size = _ref2$size === void 0 ? 15 : _ref2$size,
    color = _ref2.color;
  return /*#__PURE__*/React.createElement("button", {
    title: title,
    onClick: onClick,
    style: {
      width: 30,
      height: 30,
      display: 'grid',
      placeItems: 'center',
      borderRadius: HB.rad.md,
      cursor: 'pointer',
      border: "1px solid ".concat(active ? HB.accent : 'transparent'),
      background: active ? HB.accentSoft : 'transparent',
      color: color || HB.inkSoft,
      transition: 'all .14s'
    },
    onMouseEnter: function onMouseEnter(e) {
      return e.currentTarget.style.background = active ? HB.accentSoft : HB.lineSoft;
    },
    onMouseLeave: function onMouseLeave(e) {
      return e.currentTarget.style.background = active ? HB.accentSoft : 'transparent';
    }
  }, /*#__PURE__*/React.createElement(CKIcon, {
    name: name,
    size: size
  }));
};
var HPill = function HPill(_ref3) {
  var children = _ref3.children,
    k = _ref3.k,
    color = _ref3.color;
  var c = color || hsc(k);
  return /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: HB.mono,
      fontSize: 9.5,
      letterSpacing: '0.1em',
      textTransform: 'uppercase',
      color: c,
      background: c + '18',
      border: "1px solid ".concat(c, "3a"),
      padding: '2px 8px',
      borderRadius: 3,
      display: 'inline-flex',
      alignItems: 'center',
      gap: 5,
      whiteSpace: 'nowrap'
    }
  }, children);
};
var HDot = function HDot(_ref4) {
  var k = _ref4.k,
    color = _ref4.color,
    pulse = _ref4.pulse;
  var c = color || hsc(k);
  return /*#__PURE__*/React.createElement("span", {
    style: {
      width: 7,
      height: 7,
      borderRadius: '50%',
      background: c,
      flexShrink: 0,
      color: c,
      animation: pulse ? 'hbPulse 1.8s infinite' : 'none'
    }
  });
};
var HAvatar = function HAvatar(_ref5) {
  var name = _ref5.name,
    _ref5$size = _ref5.size,
    size = _ref5$size === void 0 ? 26 : _ref5$size;
  var initials = (name || '?').split(' ').map(function (w) {
    return w[0];
  }).slice(0, 2).join('').toUpperCase();
  var hues = [HB.accent, HB.blue, HB.purple, HB.green, HB.amber];
  var h = hues[(name || '').length % hues.length];
  return /*#__PURE__*/React.createElement("span", {
    style: {
      width: size,
      height: size,
      borderRadius: '50%',
      background: h + '1e',
      color: h,
      border: "1px solid ".concat(h, "55"),
      display: 'grid',
      placeItems: 'center',
      flexShrink: 0,
      fontFamily: HB.mono,
      fontSize: size * 0.36,
      fontWeight: 600
    }
  }, initials);
};
var HField = function HField(_ref6) {
  var label = _ref6.label,
    value = _ref6.value,
    _onChange = _ref6.onChange,
    placeholder = _ref6.placeholder,
    _ref6$type = _ref6.type,
    type = _ref6$type === void 0 ? 'text' : _ref6$type,
    full = _ref6.full,
    area = _ref6.area;
  return /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 6,
      flex: full ? 1 : 'none'
    }
  }, label && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: HB.mono,
      fontSize: 9.5,
      color: HB.inkMute,
      letterSpacing: '0.12em',
      textTransform: 'uppercase'
    }
  }, label), area ? /*#__PURE__*/React.createElement("textarea", {
    value: value !== null && value !== void 0 ? value : '',
    rows: 3,
    onChange: function onChange(e) {
      return _onChange && _onChange(e.target.value);
    },
    placeholder: placeholder,
    style: hInput()
  }) : /*#__PURE__*/React.createElement("input", {
    value: value !== null && value !== void 0 ? value : '',
    type: type,
    onChange: function onChange(e) {
      return _onChange && _onChange(e.target.value);
    },
    placeholder: placeholder,
    style: hInput()
  }));
};
var hInput = function hInput() {
  return {
    padding: '9px 11px',
    borderRadius: HB.rad.sm,
    border: "1px solid ".concat(HB.line),
    background: HB.cardHi,
    color: HB.ink,
    fontSize: 13.5,
    fontFamily: HB.sans,
    outline: 'none',
    width: '100%',
    resize: 'vertical'
  };
};
var HSelect = function HSelect(_ref7) {
  var label = _ref7.label,
    value = _ref7.value,
    _onChange2 = _ref7.onChange,
    options = _ref7.options,
    full = _ref7.full;
  return /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 6,
      flex: full ? 1 : 'none'
    }
  }, label && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: HB.mono,
      fontSize: 9.5,
      color: HB.inkMute,
      letterSpacing: '0.12em',
      textTransform: 'uppercase'
    }
  }, label), /*#__PURE__*/React.createElement("select", {
    value: value,
    onChange: function onChange(e) {
      return _onChange2 && _onChange2(e.target.value);
    },
    style: _objectSpread(_objectSpread({}, hInput()), {}, {
      cursor: 'pointer'
    })
  }, options.map(function (o) {
    var _ref8 = Array.isArray(o) ? o : [o, o],
      _ref9 = _slicedToArray(_ref8, 2),
      v = _ref9[0],
      l = _ref9[1];
    return /*#__PURE__*/React.createElement("option", {
      key: v,
      value: v
    }, l);
  })));
};
var HToggle = function HToggle(_ref0) {
  var value = _ref0.value,
    onChange = _ref0.onChange;
  return /*#__PURE__*/React.createElement("button", {
    onClick: function onClick() {
      return onChange && onChange(!value);
    },
    style: {
      width: 38,
      height: 22,
      borderRadius: 999,
      border: 'none',
      padding: 2,
      flexShrink: 0,
      background: value ? HB.accent : HB.line,
      cursor: 'pointer',
      position: 'relative',
      transition: 'background .15s'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      position: 'absolute',
      top: 2,
      left: value ? 18 : 2,
      width: 18,
      height: 18,
      borderRadius: '50%',
      background: '#fff',
      transition: 'left .15s',
      boxShadow: '0 1px 2px rgba(0,0,0,.25)'
    }
  }));
};
var HModal = function HModal(_ref1) {
  var title = _ref1.title,
    sub = _ref1.sub,
    onClose = _ref1.onClose,
    children = _ref1.children,
    _ref1$w = _ref1.w,
    w = _ref1$w === void 0 ? 480 : _ref1$w;
  return /*#__PURE__*/React.createElement("div", {
    onClick: onClose,
    style: {
      position: 'fixed',
      inset: 0,
      zIndex: 100,
      background: 'rgba(0,0,0,0.5)',
      backdropFilter: 'blur(2px)',
      display: 'grid',
      placeItems: 'center',
      padding: 24,
      animation: 'hbFade .15s'
    }
  }, /*#__PURE__*/React.createElement("div", {
    onClick: function onClick(e) {
      return e.stopPropagation();
    },
    className: "hb-scroll",
    style: {
      width: w,
      maxWidth: '100%',
      maxHeight: '88vh',
      overflow: 'auto',
      background: HB.card,
      border: "1px solid ".concat(HB.line),
      borderRadius: HB.rad.xl,
      boxShadow: '0 30px 90px rgba(0,0,0,.28)',
      animation: 'hbPop .2s'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'flex-start',
      justifyContent: 'space-between',
      gap: 12,
      padding: '18px 20px',
      borderBottom: "1px solid ".concat(HB.line)
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.serif,
      fontSize: 24,
      letterSpacing: '-0.02em',
      color: HB.ink
    }
  }, title), sub && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.mono,
      fontSize: 10.5,
      color: HB.inkMute,
      marginTop: 3,
      letterSpacing: '0.04em'
    }
  }, sub)), /*#__PURE__*/React.createElement(HIconBtn, {
    name: "x",
    onClick: onClose
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 20
    }
  }, children)));
};

// drafting-style section header: tick + measured kicker + big serif + rule
var HHead = function HHead(_ref10) {
  var kicker = _ref10.kicker,
    title = _ref10.title,
    sub = _ref10.sub,
    right = _ref10.right;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: 22
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'flex-end',
      justifyContent: 'space-between',
      gap: 20
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      minWidth: 0
    }
  }, kicker && /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 9,
      marginBottom: 10
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 22,
      height: 1,
      background: HB.accent
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: HB.mono,
      fontSize: 10,
      color: HB.accent,
      letterSpacing: '0.26em',
      textTransform: 'uppercase'
    }
  }, kicker)), /*#__PURE__*/React.createElement("h1", {
    style: {
      fontFamily: HB.serif,
      fontSize: 46,
      fontWeight: 400,
      letterSpacing: '-0.03em',
      margin: 0,
      lineHeight: 0.95,
      color: HB.ink
    }
  }, title), sub && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: HB.sans,
      fontSize: 14,
      color: HB.inkSoft,
      marginTop: 10,
      maxWidth: 560,
      lineHeight: 1.5
    }
  }, sub)), right));
};

// global paper styles + grid + animations (once)
if (typeof document !== 'undefined' && !document.getElementById('hb-style')) {
  var s = document.createElement('style');
  s.id = 'hb-style';
  s.textContent = "\n    body{background:".concat(HB.paper, ";}\n    @keyframes hbPulse{0%{box-shadow:0 0 0 0 currentColor}70%{box-shadow:0 0 0 5px transparent}100%{box-shadow:0 0 0 0 transparent}}\n    @keyframes hbFade{from{opacity:0}to{opacity:1}}\n    @keyframes hbPop{from{opacity:0;transform:scale(.97) translateY(8px)}to{opacity:1;transform:none}}\n    @keyframes hbSlide{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:none}}\n    @keyframes hbDraw{from{transform:translateX(36px);opacity:.3}to{transform:none;opacity:1}}\n    .hb-scroll::-webkit-scrollbar{width:9px;height:9px}\n    .hb-scroll::-webkit-scrollbar-thumb{background:").concat(HB.line, ";border-radius:5px;border:2px solid ").concat(HB.paper, "}\n    .hb-scroll::-webkit-scrollbar-track{background:transparent}\n    .hb-blueprint{background-image:linear-gradient(").concat(HB.line, "55 1px,transparent 1px),linear-gradient(90deg,").concat(HB.line, "55 1px,transparent 1px);background-size:26px 26px;}\n    .hb-rowh:hover{background:").concat(HB.paper2, "!important}\n  ");
  document.head.appendChild(s);
}

// ── theme: light/dark swap, BOTH derived from tokens.jsx ──
// DARK is byte-identical to the application (window.AH canonical) — the cockpit is the
// same product as Studio, not a parallel one. LIGHT is the token light mirror (AH.l_*),
// for screen-sharing and print. No third palette.
var HB_DARK = {
  paper: AHX.bg,
  paper2: AHX.bgSoft,
  card: AHX.bgPanel,
  cardHi: AHX.bgRaised,
  ink: AHX.ink,
  inkSoft: AHX.inkSoft,
  inkMute: AHX.inkMuted,
  inkDim: AHX.inkDim,
  line: AHX.line,
  lineSoft: AHX.lineSoft,
  accent: AHX.accent,
  accentHi: AHX.accentHi,
  accentSoft: AHX.accentSoft,
  blue: AHX.blue,
  blueSoft: '#1b2233',
  green: AHX.ok,
  amber: AHX.warn,
  red: AHX.err,
  purple: AHX.purple
};
var HB_LIGHT = {
  paper: AHX.l_bg,
  paper2: AHX.l_bgSoft,
  card: AHX.l_bgPanel,
  cardHi: '#ffffff',
  ink: AHX.l_ink,
  inkSoft: AHX.l_inkSoft,
  inkMute: AHX.l_inkMuted,
  inkDim: '#b8b0a2',
  line: AHX.l_line,
  lineSoft: '#eee9de',
  accent: AHX.l_accent,
  accentHi: '#b4522f',
  accentSoft: '#f2e2d8',
  blue: '#395b86',
  blueSoft: '#dce4ee',
  green: '#4c7a4e',
  amber: '#a8772a',
  red: '#b0402f',
  purple: '#6a5699'
};
var hbInjectCSS = function hbInjectCSS() {
  var s = document.getElementById('hb-style-dyn');
  if (!s) {
    s = document.createElement('style');
    s.id = 'hb-style-dyn';
    document.head.appendChild(s);
  }
  s.textContent = "\n    body{background:".concat(HB.paper, ";}\n    .hb-scroll::-webkit-scrollbar-thumb{background:").concat(HB.line, ";border-radius:5px;border:2px solid ").concat(HB.paper, "}\n    .hb-blueprint{background-image:linear-gradient(").concat(HB.line, "55 1px,transparent 1px),linear-gradient(90deg,").concat(HB.line, "55 1px,transparent 1px);background-size:26px 26px;}\n    .hb-rowh:hover{background:").concat(HB.paper2, "!important}\n  ");
};
var applyHBTheme = function applyHBTheme(mode) {
  var src = mode === 'light' ? HB_LIGHT : HB_DARK;
  Object.keys(src).forEach(function (k) {
    HB[k] = src[k];
  });
  hbInjectCSS();
};
Object.assign(window, {
  HB: HB,
  HSTAT: HSTAT,
  hsc: hsc,
  HBtn: HBtn,
  HIconBtn: HIconBtn,
  HPill: HPill,
  HDot: HDot,
  HAvatar: HAvatar,
  HField: HField,
  HSelect: HSelect,
  HToggle: HToggle,
  HModal: HModal,
  HHead: HHead,
  applyHBTheme: applyHBTheme
});
