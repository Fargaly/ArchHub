function _createForOfIteratorHelper(r, e) { var t = "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (!t) { if (Array.isArray(r) || (t = _unsupportedIterableToArray(r)) || e && r && "number" == typeof r.length) { t && (r = t); var _n = 0, F = function F() {}; return { s: F, n: function n() { return _n >= r.length ? { done: !0 } : { done: !1, value: r[_n++] }; }, e: function e(r) { throw r; }, f: F }; } throw new TypeError("Invalid attempt to iterate non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); } var o, a = !0, u = !1; return { s: function s() { t = t.call(r); }, n: function n() { var r = t.next(); return a = r.done, r; }, e: function e(r) { u = !0, o = r; }, f: function f() { try { a || null == t["return"] || t["return"](); } finally { if (u) throw o; } } }; }
function _unsupportedIterableToArray(r, a) { if (r) { if ("string" == typeof r) return _arrayLikeToArray(r, a); var t = {}.toString.call(r).slice(8, -1); return "Object" === t && r.constructor && (t = r.constructor.name), "Map" === t || "Set" === t ? Array.from(r) : "Arguments" === t || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t) ? _arrayLikeToArray(r, a) : void 0; } }
function _arrayLikeToArray(r, a) { (null == a || a > r.length) && (a = r.length); for (var e = 0, n = Array(a); e < a; e++) n[e] = r[e]; return n; }
function ownKeys(e, r) { var t = Object.keys(e); if (Object.getOwnPropertySymbols) { var o = Object.getOwnPropertySymbols(e); r && (o = o.filter(function (r) { return Object.getOwnPropertyDescriptor(e, r).enumerable; })), t.push.apply(t, o); } return t; }
function _objectSpread(e) { for (var r = 1; r < arguments.length; r++) { var t = null != arguments[r] ? arguments[r] : {}; r % 2 ? ownKeys(Object(t), !0).forEach(function (r) { _defineProperty(e, r, t[r]); }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) { Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r)); }); } return e; }
function _defineProperty(e, r, t) { return (r = _toPropertyKey(r)) in e ? Object.defineProperty(e, r, { value: t, enumerable: !0, configurable: !0, writable: !0 }) : e[r] = t, e; }
function _toPropertyKey(t) { var i = _toPrimitive(t, "string"); return "symbol" == _typeof(i) ? i : i + ""; }
function _toPrimitive(t, r) { if ("object" != _typeof(t) || !t) return t; var e = t[Symbol.toPrimitive]; if (void 0 !== e) { var i = e.call(t, r || "default"); if ("object" != _typeof(i)) return i; throw new TypeError("@@toPrimitive must return a primitive value."); } return ("string" === r ? String : Number)(t); }
function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }
// tokens.jsx — Studio projection of the current view's graph theme.
// ────────────────────────────────────────────────────────────────────────
// The static palette is the boot fallback. Personal Settings in the graph owns
// saved appearance; this module holds no persistence or cross-view selection.
//
// Two key conventions exist downstream:
//   • long keys  (bgPanel, bgSoft, bgHover …) → BB, LM, DL, ST, critique-C
//   • short keys (panel, soft, hover, deep)   → self-heal C
// Both map from the SAME canonical values below.

window.AH = {
  // ── surfaces (dark canonical) ──
  bgDeep: '#0a0a0d',
  bg: '#0e0e11',
  bgPanel: '#15151a',
  bgSoft: '#1c1c23',
  bgHover: '#22222a',
  bgRaised: '#1d1d22',
  bgInk: '#18181e',
  bgCanvas: '#101015',
  // ── ink ──
  ink: '#ece8e0',
  inkSoft: '#9b938a',
  // TEXT-SAFE STEPS. Both carry TEXT throughout this project (subtitles, counts, captions,
  // affordance hints), not hairlines. The previous #5e574f / #3a3530 measured 2.56:1 and
  // 1.50:1 on our dark surfaces — failing WCAG AA at every size used. Fixed HERE, at the
  // source, because three separate consumers (hub-kit.jsx, the tokens.css generator,
  // studio-lm.jsx) each needed the identical override. Hairlines use line / lineSoft /
  // lineHair and are unaffected; anything dimmer than inkDim is a non-text role.
  inkMuted: '#8b837a',
  // inkDim is now only a HAIR dimmer than inkMuted, and that is the honest answer: on our
  // darkest panels (bgSoft #1c1c23) there is exactly ONE muted grey step that still clears
  // 4.5:1, so a genuinely dimmer TEXT tier is not available. Both names are kept so existing
  // call sites work; treat "dimmer than this" as a non-text role (line / lineSoft / lineHair).
  inkDim: '#8a837c',
  // ON-FILL INK. Text sitting ON a filled swatch (accent / ok / warn / err buttons, badges,
  // avatars) needs a DARK ink, not white: #fff on accent #d97757 measures only 3.12:1, and on
  // ok #7ec18e just 2.12:1. This near-black warm ink clears AA on every fill in the palette
  // (5.9:1 on accent, 8.7:1 on ok). White on a mid-tone fill is the single most common
  // contrast mistake in this project — use onFill instead.
  onFill: '#180f08',
  // ── lines ──
  line: '#26262e',
  lineSoft: '#1e1e24',
  lineHair: '#1a1a20',
  // ── accents ──
  accent: '#d97757',
  // terracotta — the only emotional accent
  accentSoft: '#3a2018',
  accentDim: '#2a1812',
  accentHi: '#e8896a',
  accentPress: '#a04832',
  // ── functional ──
  ok: '#7ec18e',
  // USER AVATAR pair (design tokens.jsx:56-61): the human's own mark in conversations.
  // Defined HERE because studio-lm.jsx drew it inline in six places; onUserAv is the ink on it.
  // Static in window.AH only — not in ArchHubTheme.keys, so a graph theme cannot recolour it.
  userAv: '#d8c5a8',
  onUserAv: '#5a4a2a',
  warn: '#e5b25a',
  err: '#e6705f',
  cyan: '#5fb3b3',
  purple: '#a98cd6',
  blue: '#7898d6',
  // ── light mirror (side-by-side demos) ──
  l_bg: '#f7f4ee',
  l_bgPanel: '#fbf9f4',
  l_bgSoft: '#efeae0',
  l_ink: '#1a1612',
  l_inkSoft: '#6b6256',
  l_inkMuted: '#9a9183',
  l_line: '#e3ddd0',
  l_accent: '#c96442',
  // ── type ──
  serif: "'Instrument Serif', Georgia, serif",
  sans: "'Inter', system-ui, sans-serif",
  mono: "'JetBrains Mono', ui-monospace, monospace",
  arch: "'Architects Daughter', 'Comic Sans MS', cursive",
  // ── scales ──
  sp: {
    xs: 4,
    sm: 8,
    md: 12,
    lg: 16,
    xl: 24,
    '2xl': 32,
    '3xl': 40,
    '4xl': 48,
    '5xl': 56,
    '6xl': 72,
    '7xl': 96
  },
  rad: {
    xs: 3,
    sm: 5,
    md: 6,
    lg: 8,
    xl: 10,
    pill: 999
  },
  fs: {
    d0: {
      sz: 104,
      ln: 0.90,
      fam: 'serif',
      use: 'Web marketing hero — archhub.app only'
    },
    d1: {
      sz: 88,
      ln: 0.92,
      fam: 'serif',
      use: 'Cover · product hero'
    },
    d2: {
      sz: 56,
      ln: 0.95,
      fam: 'serif',
      use: 'Section openers'
    },
    h1: {
      sz: 40,
      ln: 1.05,
      fam: 'serif',
      use: 'Page heading'
    },
    h2: {
      sz: 24,
      ln: 1.15,
      fam: 'serif',
      use: 'Italic lede · pull-quote'
    },
    h3: {
      sz: 21,
      ln: 1.20,
      fam: 'serif',
      use: 'In-product section title'
    },
    bodyLg: {
      sz: 16,
      ln: 1.55,
      fam: 'sans',
      use: 'Body large · composer'
    },
    body: {
      sz: 14,
      ln: 1.55,
      fam: 'sans',
      use: 'Body · rows · descriptions'
    },
    bodySm: {
      sz: 13,
      ln: 1.50,
      fam: 'sans',
      use: 'Body small · dense lists'
    },
    mono: {
      sz: 12,
      ln: 1.50,
      fam: 'mono',
      use: 'Data · params · prices · tokens'
    },
    monoSm: {
      sz: 11,
      ln: 1.55,
      fam: 'mono',
      use: 'Mono small · captions · timestamps'
    },
    cap: {
      sz: 9,
      ln: 1.40,
      fam: 'mono',
      use: 'All-caps section labels · tags'
    }
  },
  dur: {
    instant: 60,
    fast: 120,
    med: 180,
    slow: 240
  },
  rowH: {
    comfortable: 32,
    compact: 26,
    cozy: 22
  }
};
window.ArchHubTheme = function () {
  var keys = Object.freeze(['bg_deep', 'bg', 'bg_panel', 'bg_soft', 'bg_hover', 'bg_raised', 'bg_ink', 'bg_canvas', 'ink', 'ink_soft', 'ink_muted', 'ink_dim', 'on_fill', 'line', 'line_soft', 'line_hair', 'accent', 'accent_soft', 'accent_dim', 'accent_hi', 'accent_press', 'ok', 'warn', 'err', 'cyan', 'purple', 'blue', 'l_bg', 'l_bg_panel', 'l_bg_soft', 'l_ink', 'l_ink_soft', 'l_ink_muted', 'l_line', 'l_accent']);
  var listeners = new Set(),
    derived = [];
  var epoch = 0,
    source = 'not-read';
  var tokenKey = function tokenKey(key) {
    var light = key.startsWith('l_');
    var base = light ? key.slice(2) : key;
    return (light ? 'l_' : '') + base.replace(/_([a-z])/g, function (_, letter) {
      return letter.toUpperCase();
    });
  };
  var validate = function validate(theme) {
    if (!theme || _typeof(theme) !== 'object' || Array.isArray(theme) || Object.keys(theme).length !== keys.length || keys.some(function (key) {
      return !Object.prototype.hasOwnProperty.call(theme, key) || typeof theme[key] !== 'string' || !/^#[0-9a-fA-F]{6}$/.test(theme[key]);
    })) {
      throw new Error('Personal Settings did not return a complete colour theme.');
    }
    return Object.fromEntries(keys.map(function (key) {
      return [tokenKey(key), theme[key]];
    }));
  };
  var apply = function apply(theme) {
    var values = validate(theme); // Reject the whole document before changing any token.
    var changed = Object.keys(values).some(function (key) {
      return window.AH[key] !== values[key];
    });
    if (!changed && source === 'graph') {
      window.ARCHHUB_THEME_ERROR = '';
      return false;
    }
    var next = _objectSpread(_objectSpread({}, window.AH), values);
    // Build every dependent projection first; a failed builder cannot partially apply.
    var updates = derived.map(function (_ref) {
      var target = _ref.target,
        build = _ref.build;
      return {
        target: target,
        values: build(next)
      };
    });
    Object.assign(window.AH, values);
    var _iterator = _createForOfIteratorHelper(updates),
      _step;
    try {
      for (_iterator.s(); !(_step = _iterator.n()).done;) {
        var update = _step.value;
        Object.assign(update.target, update.values);
      }
    } catch (err) {
      _iterator.e(err);
    } finally {
      _iterator.f();
    }
    source = 'graph';
    window.ARCHHUB_THEME_ERROR = '';
    epoch += 1;
    var _iterator2 = _createForOfIteratorHelper(listeners),
      _step2;
    try {
      for (_iterator2.s(); !(_step2 = _iterator2.n()).done;) {
        var notify = _step2.value;
        try {
          notify();
        } catch (_) {}
      }
    } catch (err) {
      _iterator2.e(err);
    } finally {
      _iterator2.f();
    }
    return true;
  };
  var derive = function derive(build) {
    var target = build(window.AH);
    derived.push({
      target: target,
      build: build
    });
    return target;
  };
  var store = Object.freeze({
    keys: keys,
    validate: validate,
    apply: apply,
    derive: derive,
    get source() {
      return source;
    },
    subscribe: function subscribe(listener) {
      listeners.add(listener);
      return function () {
        return listeners["delete"](listener);
      };
    },
    getEpoch: function getEpoch() {
      return epoch;
    }
  });
  window.ARCHHUB_THEME_ERROR = '';
  if (window.ARCHHUB_THEME != null) {
    try {
      apply(window.ARCHHUB_THEME);
    } catch (error) {
      source = 'rejected';
      window.ARCHHUB_THEME_ERROR = error.message;
    }
  }
  return store;
}();

// Convenience: short-key projection (brain / self-heal style) so those files can
// do `const C = window.AHShort` if they prefer. This legacy projection is boot-only.
window.AHShort = function () {
  var A = window.AH;
  return {
    bg: A.bg,
    panel: A.bgPanel,
    soft: A.bgSoft,
    deep: A.bgDeep,
    hover: A.bgHover,
    raised: A.bgRaised,
    ink: A.ink,
    inkSoft: A.inkSoft,
    inkMuted: A.inkMuted,
    inkDim: A.inkDim,
    line: A.line,
    lineSoft: A.lineSoft,
    lineHair: A.lineHair,
    accent: A.accent,
    accentSoft: A.accentSoft,
    accentDim: A.accentDim,
    accentHi: A.accentHi,
    ok: A.ok,
    warn: A.warn,
    err: A.err,
    cyan: A.cyan,
    purple: A.purple,
    blue: A.blue,
    sp: A.sp,
    rad: A.rad
  };
}();
